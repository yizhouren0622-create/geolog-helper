"""Local Geocaching log helper. Apache-2.0; see THIRD_PARTY.md.

The GC transport is adapted from c:geo GCAuthAPI.java and GCLogAPI.java
at d23e863148ca64cb1d51bee6e10d776c657a6a94 (Apache-2.0).
No password handling, private API keys, cloud storage, or AI subscription.
"""
import base64
import concurrent.futures
from contextlib import contextmanager
import datetime as dt
import io
import json
import os
from pathlib import Path
import queue
import re
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import getproxies

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('GEOLOG_DATA', str(ROOT / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
(DATA / 'photos').mkdir(exist_ok=True)
PORT = int(os.environ.get('GEOLOG_PORT', '8765'))
BASE = 'https://www.geocaching.com'
LOCK = threading.RLock()
SESSION = secrets.token_urlsafe(32)
JOBS = {}
START_DATE = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()


class Problem(Exception):
    pass


class Uncertain(Problem):
    pass


@contextmanager
def db():
    conn = sqlite3.connect(DATA / 'drafts.sqlite3')
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        with conn:
            yield conn
    finally:
        conn.close()


def save(draft):
    draft['updated'] = time.time()
    with LOCK, db() as conn:
        conn.execute('INSERT OR REPLACE INTO drafts VALUES (?,?)', (draft['id'], json.dumps(draft, ensure_ascii=False)))
    return draft


def get(draft_id):
    with LOCK, db() as conn:
        row = conn.execute('SELECT body FROM drafts WHERE id=?', (draft_id,)).fetchone()
    if not row:
        raise Problem('找不到这条草稿')
    return json.loads(row[0])


def drafts():
    with LOCK, db() as conn:
        return sorted([json.loads(r[0]) for r in conn.execute('SELECT body FROM drafts')], key=lambda d: d['updated'], reverse=True)


def code(value, prefix='GC'):
    match = re.search(r'\b' + prefix + r'[0-9A-Z]+\b', str(value).upper())
    if not match:
        raise Problem('请输入有效的 ' + prefix + ' 编号或链接')
    return match[0]


def validate(draft):
    draft['gc'] = code(draft.get('gc', ''))
    try:
        day = dt.date.fromisoformat(draft['date'])
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
        if day > today:
            raise Problem('日期不能晚于今天，请核对实际寻宝日期')
    except (ValueError, KeyError):
        raise Problem('请填写有效日期')
    if int(draft.get('type', 0)) not in (2, 3, 4, 10):
        raise Problem('请选择日志类型')
    if not str(draft.get('text', '')).strip():
        raise Problem('请选择描述或填写日志内容')
    if len(draft['text']) > 10000:
        raise Problem('日志内容请控制在 10000 字以内')


class GCClient:
    """One browser context, owned only by BrowserWorker's thread."""
    def __init__(self):
        self.ctx = None
        self.pw = None

    def start(self):
        if self.ctx:
            try:
                _ = self.ctx.cookies()
                return
            except Exception:
                self.ctx = None
        from playwright.sync_api import sync_playwright
        if not self.pw:
            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.browsers')
            self.pw = sync_playwright().start()
        options = dict(headless=False, no_viewport=True, timeout=30000)
        proxy = getproxies().get('https') or getproxies().get('http')
        if proxy and urlparse(proxy).hostname in ('127.0.0.1', 'localhost'):
            options['proxy'] = {'server': proxy}
        self.ctx = self.pw.firefox.launch_persistent_context(str(DATA / 'firefox-profile'), **options)
        self.ctx.set_default_timeout(25000)
        self.ctx.on('close', lambda *args: setattr(self, 'ctx', None))

    def helper(self):
        self.start()
        url = 'http://127.0.0.1:' + str(PORT) + '/'
        pages = [p for p in self.ctx.pages if p.url.startswith(url)]
        page = pages[0] if pages else self.ctx.new_page()
        if not pages:
            page.goto(url, wait_until='domcontentloaded', timeout=15000)
        page.bring_to_front()
        return {'message': '日志助手已在火狐浏览器打开。'}

    def login(self):
        self.helper()
        pages = [p for p in self.ctx.pages if BASE in p.url]
        page = pages[0] if pages else self.ctx.new_page()
        page.goto(BASE + '/account/signin', wait_until='domcontentloaded', timeout=45000)
        page.bring_to_front()
        return {'message': '请在打开的火狐窗口登录，然后回到“寻宝手记”标签页点击“检查登录”。'}

    def auth(self):
        self.start()
        try:
            response = self.ctx.request.get(BASE + '/account/oauth/token', timeout=25000)
            value = response.json() if response.ok else {}
        except Exception:
            raise Problem('暂时无法检查登录，请检查网络，并在专用火狐窗口完成登录')
        if not value.get('access_token'):
            raise Problem('尚未登录，请先点击“登录 Geocaching”并在 Edge 窗口完成登录')
        return {'Authorization': value.get('token_type', 'Bearer') + ' ' + value['access_token']}

    def ready(self):
        self.auth()
        return {'logged_in': True, 'message': '已登录，可以发布日志。'}

    def headers(self):
        headers = self.auth()
        response = self.ctx.request.get(BASE + '/api/auth/csrf', headers=headers, timeout=25000)
        try:
            token = response.json().get('csrfToken') if response.ok else None
        except Exception:
            token = None
        if not token:
            raise Problem('无法取得发布凭据，请重新登录后再试')
        return dict(headers, **{'CSRF-Token': token, 'Referer': BASE + '/'})

    @staticmethod
    def parse(response, image=False):
        if not response.ok:
            if 400 <= response.status < 500 and response.status not in (408,):
                raise Problem('网站拒绝本次请求（HTTP %s），请打开官网核对账号权限和日志内容' % response.status)
            raise Uncertain('网站响应异常（HTTP %s），请先到官网核对是否成功' % response.status)
        try:
            return response.json()
        except Exception:
            raise Uncertain('网站没有返回可确认的结果，请先到官网核对')

    def create(self, draft, headers):
        payload = {'0': {'referenceCode': draft['gc'], 'body': {
            'images': [], 'logDate': draft['date'] + 'T12:00:00',
            'logText': draft['text'], 'logType': int(draft['type']),
            'trackables': [], 'geocacheReferenceCode': ''}}}
        try:
            response = self.ctx.request.post(BASE + '/api/live/v1/trpc/web.logs.createGeocacheLog?batch=1',
                                             headers=headers, data=payload, timeout=45000)
        except Exception:
            raise Uncertain('连接中断，日志可能已经成功。请在官网核对，避免重复发布')
        result = self.parse(response)
        try:
            result = result[0]['result']['data']['logReferenceCode']
            if not re.fullmatch(r'GL[0-9A-Z]+', result):
                raise ValueError()
            return result
        except Exception:
            raise Uncertain('网站未返回日志编号。请先到官网核对，再关联已发布的 GL 编号')

    def image(self, log_code, photo, headers):
        path = DATA / 'photos' / (photo['id'] + '.jpg')
        try:
            response = self.ctx.request.post(BASE + '/api/live/v1/logs/' + log_code + '/images',
                headers=headers, multipart={'image': {'name': photo['id'] + '.jpg',
                'mimeType': 'image/jpeg', 'buffer': path.read_bytes()}}, timeout=60000)
        except Exception:
            raise Uncertain('照片连接中断，可能已经上传。请到日志页面核对')
        result = self.parse(response, True)
        if not result.get('guid') or not result.get('url'):
            raise Uncertain('无法确认照片上传结果，请到日志页面核对')
        return result['guid']

    def caption(self, log_code, photo, headers):
        if not photo.get('caption'):
            return
        response = self.ctx.request.put(BASE + '/api/live/v1/images/' + log_code + '/' + photo['guid'] + '/replace',
                                       headers=headers, multipart={'name': photo['caption']}, timeout=30000)
        self.parse(response)

    def open_log(self, draft):
        self.start()
        url = BASE + ('/live/log/' + draft['log_code'] if draft.get('log_code') else '/geocache/' + code(draft['gc']))
        page = self.ctx.new_page()
        page.goto(url, wait_until='domcontentloaded', timeout=45000)
        page.bring_to_front()
        return {'message': '已打开官网，核对完成后回到助手。'}


def publish(draft_id, client):
    """Persist remote IDs before moving on; never retry uncertain writes."""
    draft = get(draft_id)
    if draft.get('state') in ('creating', 'uncertain') and not draft.get('log_code'):
        raise Problem('上次日志结果待核对。请在官网找到已发布日志，填入 GL 编号后再继续')
    validate(draft)
    try:
        headers = client.headers()  # Auth failure occurs before any write.
    except Exception:
        if draft.get('state') == 'queued':
            draft['state'] = 'draft'
            save(draft)
        raise
    if not draft.get('log_code'):
        draft['state'] = 'creating'
        save(draft)
        try:
            draft['log_code'] = client.create(draft, headers)
            draft['state'] = 'partial'
            save(draft)
        except Uncertain as error:
            draft['state'] = 'uncertain'
            draft['error'] = str(error)
            save(draft)
            raise
        except Problem as error:
            draft['state'] = 'draft'
            draft['error'] = str(error)
            save(draft)
            raise
    for photo in draft['photos']:
        if photo.get('state') in ('uncertain', 'uploading'):
            raise Problem('有照片的上传结果待核对，请到官网核对后处理这张照片')
        if photo.get('state') == 'done':
            continue
        if not photo.get('guid'):
            photo['state'] = 'uploading'
            save(draft)
            try:
                photo['guid'] = client.image(draft['log_code'], photo, headers)
                photo['state'] = 'caption'
                save(draft)
            except Exception as error:
                photo['state'] = 'uncertain' if isinstance(error, Uncertain) or not isinstance(error, Problem) else 'failed'
                draft['state'] = 'partial'
                draft['error'] = str(error) if isinstance(error, Problem) else '照片处理失败，请核对官网结果'
                save(draft)
                raise Problem(draft['error'])
        try:
            client.caption(draft['log_code'], photo, headers)
            photo['state'] = 'done'
            save(draft)
        except Exception:
            draft['error'] = '照片已上传，标题暂未保存；再次点击发布只会重试标题'
            save(draft)
            raise Problem(draft['error'])
    draft['state'] = 'published'
    draft.pop('error', None)
    save(draft)
    return {'log_code': draft['log_code'], 'message': '日志和所选照片均已发布。'}


class BrowserWorker:
    def __init__(self):
        self.queue = queue.Queue()
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        client = GCClient()
        while True:
            action, arg, future = self.queue.get()
            try:
                if action == 'publish':
                    result = publish(arg, client)
                elif action == 'open':
                    result = client.open_log(get(arg))
                else:
                    result = getattr(client, action)()
                future.set_result(result)
            except Exception as error:
                if action == 'login' and not isinstance(error, Problem):
                    # Browser launch/navigation errors only; no authenticated API requests are made by login().
                    (DATA / 'login-diagnostic.txt').write_text(type(error).__name__ + ': ' + str(error).split('\n')[0], encoding='utf-8')
                # Do not expose Playwright exception dumps: they may contain request headers.
                future.set_exception(Problem(str(error) if isinstance(error, Problem) else '操作未完成，请检查网络或重新打开专用浏览器'))

    def submit(self, action, arg=None):
        future = concurrent.futures.Future()
        self.queue.put((action, arg, future))
        return future


def new_draft():
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    return save({'id': secrets.token_hex(12), 'gc': '', 'name': '', 'date': today,
                 'type': 2, 'text': '', 'tags': [], 'extra': '', 'photos': [], 'state': 'draft'})


def add_photo(draft, item):
    from PIL import Image, ImageOps
    if len(draft['photos']) >= 10:
        raise Problem('每条日志最多先选择 10 张照片')
    try:
        raw = base64.b64decode(item['data'], validate=True)
        if len(raw) > 24 * 1024 * 1024:
            raise Problem('单张照片请小于 24 MB')
        image = Image.open(io.BytesIO(raw))
        taken = image.getexif().get(36867) or image.getexif().get(306)
        image = ImageOps.exif_transpose(image)
        image.thumbnail((2000, 2000))
        if image.mode != 'RGB':
            if image.mode == 'RGBA':
                canvas = Image.new('RGB', image.size, 'white')
                canvas.paste(image, mask=image.getchannel('A'))
                image = canvas
            else:
                image = image.convert('RGB')
        photo_id = secrets.token_hex(16)
        # EXIF is intentionally omitted from upload copies, including GPS coordinates.
        image.save(DATA / 'photos' / (photo_id + '.jpg'), quality=87, optimize=True)
        photo = {'id': photo_id, 'name': str(item.get('name', '照片'))[:150],
                 'caption': '', 'state': 'pending', 'taken': str(taken or '')[:20]}
        draft['photos'].append(photo)
        return save(draft)
    except Problem:
        raise
    except Exception:
        raise Problem('无法读取这张图片。请选 JPG、PNG 或 WebP；HEIC 请先转成 JPG')


WORKER = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, value, mime='application/json; charset=utf-8'):
        body = json.dumps(value, ensure_ascii=False).encode() if mime.startswith('application/json') else value
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if self.path == '/':
            self.send_header('Set-Cookie', 'geolog=' + SESSION + '; HttpOnly; SameSite=Strict; Path=/')
        self.end_headers()
        self.wfile.write(body)

    def allowed(self, write=False):
        if self.headers.get('Host') not in ('127.0.0.1:' + str(PORT), 'localhost:' + str(PORT)):
            return False
        if write:
            if self.headers.get('Origin') not in ('http://127.0.0.1:' + str(PORT), 'http://localhost:' + str(PORT)):
                return False
            if 'geolog=' + SESSION not in self.headers.get('Cookie', ''):
                return False
        return True

    def do_GET(self):
        try:
            if not self.allowed():
                return self.send(403, {'error': 'Local access only'})
            if self.path in ('/', '/app.js', '/tutorial.js', '/style.css'):
                name = {'/': 'index.html', '/app.js': 'app.js', '/tutorial.js': 'tutorial.js', '/style.css': 'style.css'}[self.path]
                mime = {'/': 'text/html; charset=utf-8', '/app.js': 'text/javascript; charset=utf-8', '/tutorial.js': 'text/javascript; charset=utf-8', '/style.css': 'text/css; charset=utf-8'}[self.path]
                return self.send(200, (ROOT / name).read_bytes(), mime)
            if self.path == '/api/state':
                return self.send(200, {'app': 'GeoLogHelper', 'drafts': drafts(), 'today': dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat(),
                                       'jobs': {k: v for k, v in JOBS.items()}, 'live_verified': False})
            if self.path.startswith('/photos/') and re.fullmatch(r'/photos/[a-f0-9]{32}\.jpg', self.path):
                return self.send(200, (DATA / 'photos' / self.path.rsplit('/', 1)[1]).read_bytes(), 'image/jpeg')
            self.send(404, {'error': 'Not found'})
        except Exception:
            self.send(500, {'error': '读取本地数据失败'})

    def do_POST(self):
        try:
            if not self.allowed(True):
                return self.send(403, {'error': '请求来源无效，请从本地助手页面操作'})
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 34 * 1024 * 1024:
                return self.send(413, {'error': '请求过大'})
            item = json.loads(self.rfile.read(size))
            if self.path == '/api/new':
                return self.send(200, new_draft())
            if self.path in ('/api/login', '/api/check', '/api/helper'):
                action = {'/api/login': 'login', '/api/check': 'ready', '/api/helper': 'helper'}[self.path]
                return self.send(200, WORKER.submit(action).result(timeout=65))
            draft = get(item.get('id', ''))
            if self.path == '/api/save':
                if draft['state'] != 'draft':
                    raise Problem('这条日志已进入发布流程，正文已锁定，请在官网修改')
                for key in ('gc', 'name', 'date', 'type', 'text', 'tags', 'extra'):
                    if key in item:
                        draft[key] = item[key]
                captions = item.get('captions', {})
                for photo in draft['photos']:
                    photo['caption'] = str(captions.get(photo['id'], photo['caption']))[:200]
                return self.send(200, save(draft))
            if self.path == '/api/photo':
                if draft['state'] != 'draft':
                    raise Problem('日志发布后照片列表已锁定')
                return self.send(200, add_photo(draft, item))
            if self.path == '/api/remove-photo':
                if draft['state'] != 'draft':
                    raise Problem('这条日志已进入发布流程')
                draft['photos'] = [p for p in draft['photos'] if p['id'] != item.get('photo_id')]
                return self.send(200, save(draft))
            if self.path == '/api/publish':
                if item.get('confirmed') is not True:
                    raise Problem('请先在预览窗口核对并确认发布')
                with LOCK:
                    draft = get(item.get('id', ''))
                    if any(j.get('draft_id') == draft['id'] and j['state'] == 'running' for j in JOBS.values()):
                        raise Problem('这条日志正在发布，请等待结果')
                    if draft['state'] in ('creating', 'uncertain') and not draft.get('log_code'):
                        raise Problem('上次日志结果待核对。请先到官网核对，避免重复发布')
                    validate(draft)
                    if draft['state'] == 'published':
                        raise Problem('这条日志已发布，请查看官网')
                    job_id = secrets.token_hex(10)
                    JOBS[job_id] = {'state': 'running', 'draft_id': draft['id'], 'message': '正在发布，请稍候…'}
                    if not draft.get('log_code'):
                        draft['state'] = 'queued'
                        save(draft)
                    future = WORKER.submit('publish', draft['id'])
                def finished(f):
                    try:
                        JOBS[job_id].update(state='done', **f.result())
                    except Exception as error:
                        JOBS[job_id].update(state='error', message=str(error))
                future.add_done_callback(finished)
                return self.send(200, {'job_id': job_id})
            if self.path == '/api/open':
                return self.send(200, WORKER.submit('open', draft['id']).result(timeout=65))
            if self.path == '/api/reconcile':
                if any(j.get('draft_id') == draft['id'] and j['state'] == 'running' for j in JOBS.values()):
                    raise Problem('请等待当前上传结束后再核对')
                if draft.get('log_code'):
                    raise Problem('该日志已经关联 GL 编号')
                if item.get('log_code'):
                    draft['log_code'] = code(item['log_code'], 'GL')
                    draft['state'] = 'partial'
                elif item.get('verified_absent') is True and draft['state'] in ('creating', 'uncertain'):
                    draft['state'] = 'draft'
                else:
                    raise Problem('请填入核对过的 GL 编号')
                draft.pop('error', None)
                return self.send(200, save(draft))
            if self.path == '/api/reconcile-photo':
                if any(j.get('draft_id') == draft['id'] and j['state'] == 'running' for j in JOBS.values()):
                    raise Problem('请等待当前上传结束')
                photo = next(p for p in draft['photos'] if p['id'] == item.get('photo_id'))
                if photo.get('state') not in ('uncertain', 'uploading'):
                    raise Problem('此照片无需核对')
                if item.get('exists') is True:
                    photo['state'] = 'done'
                elif item.get('verified_absent') is True:
                    photo['state'] = 'pending'
                else:
                    raise Problem('请先核对官网照片')
                return self.send(200, save(draft))
            self.send(404, {'error': 'Not found'})
        except Problem as error:
            self.send(400, {'error': str(error)})
        except concurrent.futures.TimeoutError:
            self.send(504, {'error': '等待超时，请稍后检查状态'})
        except Exception:
            self.send(500, {'error': '本地操作未完成，请检查输入或重启助手'})


def main():
    global WORKER
    for draft in drafts():
        if draft.get('state') == 'queued':
            draft['state'] = 'draft'
            save(draft)
    WORKER = BrowserWorker()
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    server.serve_forever()


if __name__ == '__main__':
    main()
