"""Local, account-visible cache index; no coordinates are inferred when withheld."""
import calendar
from contextlib import contextmanager
import csv
import datetime as dt
import gzip
import io
import ipaddress
import json
import math
import re
import socket
import sqlite3
import time
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

REGIONS = [
    {'id': 'shanghai', 'name': '上海', 'lat': 31.2304, 'lng': 121.4737, 'box': [31.90, 120.85, 30.65, 122.30]},
    {'id': 'beijing', 'name': '北京', 'lat': 39.9042, 'lng': 116.4074, 'box': [41.10, 115.40, 39.40, 117.60]},
    {'id': 'shenzhen', 'name': '深圳', 'lat': 22.5431, 'lng': 114.0579, 'box': [22.90, 113.70, 22.40, 114.65]},
    {'id': 'hongkong', 'name': '香港', 'lat': 22.3193, 'lng': 114.1694, 'box': [22.60, 113.80, 22.15, 114.45]},
    {'id': 'macau', 'name': '澳门', 'lat': 22.1987, 'lng': 113.5439, 'box': [22.25, 113.52, 22.10, 113.65]},
    {'id': 'taiwan', 'name': '台湾', 'lat': 23.6978, 'lng': 120.9605, 'box': [25.50, 119.30, 21.80, 122.10]},
]
INTERVAL = 15 * 86400


def coordinates(value):
    """Decimal degrees or N31 13.824 E121 28.422; always latitude first."""
    text = str(value).strip().upper().replace('，', ',').replace('°', ' ').replace('′', ' ').replace("'", ' ')
    if re.search('[NSEW]', text):
        match = re.fullmatch(r'([NS])\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*[, ]*([EW])\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)', text)
        if not match:
            raise ValueError('坐标格式示例：31.2304, 121.4737 或 N31 13.824 E121 28.422')
        ns, dlat, mlat, ew, dlng, mlng = match.groups()
        if float(mlat) >= 60 or float(mlng) >= 60:
            raise ValueError('坐标的分数必须小于 60')
        lat = (float(dlat) + float(mlat) / 60) * (-1 if ns == 'S' else 1)
        lng = (float(dlng) + float(mlng) / 60) * (-1 if ew == 'W' else 1)
    else:
        parts = re.split(r'[,\s]+', text)
        if len(parts) != 2:
            raise ValueError('请按“纬度, 经度”输入两个数字')
        lat, lng = map(float, parts)
    if not math.isfinite(lat) or not math.isfinite(lng) or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError('纬度应在 -90～90，经度应在 -180～180')
    return lat, lng


def query_params(item, skip=0, take=100):
    region = next((r for r in REGIONS if r['id'] == item.get('region')), REGIONS[0])
    lat, lng = coordinates(item.get('coordinates') or f"{region['lat']},{region['lng']}")
    params = {'origin': f'{lat},{lng}', 'asc': 'true', 'sort': 'distance',
              'take': str(min(100, max(1, int(take)))), 'skip': str(max(0, int(skip))), 'app': 'geolog-helper'}
    if item.get('box'):
        box = list(map(float, item['box']))
        if len(box) != 4:
            raise ValueError('地图范围无效')
        north, west, south, east = box
        coordinates(f'{north},{west}'); coordinates(f'{south},{east}')
        if north <= south or east <= west or (north - south) * (east - west) > 100:
            raise ValueError('请放大地图后再查询当前范围')
        params.update(box=','.join(map(str, box)), rad='16000')
    else:
        radius = float(item.get('radius', 25))
        if not math.isfinite(radius) or not 1 <= radius <= 100:
            raise ValueError('搜索半径应在 1～100 公里')
        params.update(rad=str(radius * 0.621371192), dorigin=f'{lat},{lng}')  # gc radius is miles
    if str(item.get('keyword', '')).strip():
        params['cn'] = str(item['keyword']).strip()[:150]
    return params


def normalize(row):
    gc = str(row.get('code') or row.get('gc') or '').upper().strip()
    if not re.fullmatch(r'GC[0-9A-Z]+', gc):
        raise ValueError('藏宝点编号无效')
    point = row.get('postedCoordinates')
    if isinstance(point, dict) and point.get('latitude') is not None and point.get('longitude') is not None:
        lat, lng = coordinates(f"{point.get('latitude')},{point.get('longitude')}")
    elif row.get('lat') not in (None, '') and row.get('lng') not in (None, ''):
        lat, lng = coordinates(f"{row['lat']},{row['lng']}")
    else:
        lat, lng = None, None
    return {'gc': gc, 'name': str(row.get('name') or gc)[:300], 'lat': lat, 'lng': lng,
            'type': str(row.get('geocacheType') or row.get('type') or ''),
            'status': str(row.get('cacheStatus') or row.get('status') or ''),
            'premium': bool(row.get('premiumOnly')), 'updated': time.time()}


def six_months_later(timestamp):
    value = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc)
    month = value.month + 6
    year = value.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1])).timestamp()


def public_feed_url(url):
    parsed = urlparse(str(url).strip())
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('数据源须为不含账号密码的公开 HTTPS CSV 链接')
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise ValueError('无法解析数据源域名')
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('数据源必须位于公网，不能使用本机或内网地址')
    return parsed.geturl()


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_feed_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Catalog:
    def __init__(self, data):
        self.path = data / 'catalog.sqlite3'

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            conn.execute('CREATE TABLE IF NOT EXISTS caches (gc TEXT PRIMARY KEY, name TEXT, lat REAL, lng REAL, body TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)')
            with conn:
                yield conn
        finally:
            conn.close()

    def meta(self, key, default=None):
        with self.db() as conn:
            row = conn.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        with self.db() as conn:
            conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, json.dumps(value)))

    @staticmethod
    def insert(conn, row):
        conn.execute('INSERT OR REPLACE INTO caches VALUES (?,?,?,?,?)',
                     (row['gc'], row['name'], row['lat'], row['lng'], json.dumps(row, ensure_ascii=False)))

    def upsert(self, rows):
        with self.db() as conn:
            for row in rows:
                self.insert(conn, row)

    def search(self, keyword='', box=None, limit=500):
        clauses, args = [], []
        if keyword:
            escaped = str(keyword).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')[:150]
            clauses.append("(name LIKE ? ESCAPE '\\' OR gc LIKE ? ESCAPE '\\')")
            args += ['%' + escaped + '%'] * 2
        if box:
            north, west, south, east = map(float, box)
            clauses.append('lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?')
            args += [south, north, west, east]
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.db() as conn:
            total = conn.execute('SELECT COUNT(*) FROM caches' + where, args).fetchone()[0]
            rows = conn.execute('SELECT body FROM caches' + where + ' ORDER BY name LIMIT ?', args + [max(1, min(int(limit), 2000))]).fetchall()
        return {'caches': [json.loads(row[0]) for row in rows], 'total': total, 'source': 'local'}

    def status(self):
        with self.db() as conn:
            count = conn.execute('SELECT COUNT(*) FROM caches').fetchone()[0]
        entries = []
        for region in REGIONS:
            info = self.meta('region:' + region['id'], {})
            info.pop('resume_codes', None)
            entries.append({**region, **info})
        return {'count': count, 'regions': entries, 'backoff_until': self.meta('backoff_until', 0),
                'global': self.meta('global', {}), 'global_configured': bool(self.meta('global_url')),
                'regional_interval_days': 15, 'global_interval_months': 6}

    def due_regions(self, force=False, region_ids=None):
        if region_ids is not None:
            if not isinstance(region_ids, list) or not region_ids or any(
                    value not in {r['id'] for r in REGIONS} for value in region_ids):
                raise ValueError('请选择有效的更新地区')
        now = time.time()
        if now < self.meta('backoff_until', 0):
            return []
        return [r for r in REGIONS if (region_ids is None or r['id'] in region_ids)
                and (force or now >= self.meta('region:' + r['id'], {}).get('next_update', 0))]

    def sync_regions(self, fetch, force=False, region_ids=None):
        results = []
        for region in self.due_regions(force, region_ids):
            info = self.meta('region:' + region['id'], {})
            recent_resume = time.time() - info.get('resume_since', 0) < 86400
            start = info.get('resume_skip', 0) if recent_resume else 0
            seen = set(info.get('resume_codes', [])) if recent_resume else set()
            total = (info.get('total', 0) or 0) if recent_resume else 0
            started = info.get('resume_since', time.time()) if recent_resume else time.time()
            try:
                for skip in range(start, 5000, 100):
                    page = fetch({'region': region['id'], 'box': region['box']}, skip)
                    total = max(total, int(page.get('total', 0)))
                    self.upsert(page['caches'])
                    seen.update(row['gc'] for row in page['caches'])
                    info.update(state='updating', loaded=len(seen), total=total,
                                resume_skip=skip + len(page['caches']), resume_codes=sorted(seen), resume_since=started)
                    self.set_meta('region:' + region['id'], info)
                    if not page['caches'] or skip + len(page['caches']) >= total:
                        break
                    time.sleep(2)
                now = time.time()
                info = {'last_update': now, 'next_update': now + INTERVAL, 'loaded': len(seen), 'total': total,
                        'state': 'partial' if len(seen) < total else 'ok', 'error': ''}
                self.set_meta('region:' + region['id'], info)
                results.append({'region': region['name'], **info})
            except Exception as error:
                # Keep the last successful timestamp and old records on a failed refresh.
                info = self.meta('region:' + region['id'], {})
                info.update(state='error', error='更新失败；旧数据已保留。' + str(error).split('\n')[0][:180])
                self.set_meta('region:' + region['id'], info)
                results.append({'region': region['name'], **{k: v for k, v in info.items() if k != 'resume_codes'}})
                if getattr(error, 'retry_after', None):
                    self.set_meta('backoff_until', time.time() + error.retry_after)
                    break
        return results

    def configure_global(self, url):
        if url:
            url = public_feed_url(url)
        self.set_meta('global_url', url)
        self.set_meta('global', {'state': 'pending' if url else 'unconfigured', 'next_update': 0})

    def sync_global(self, force=False, opener=None):
        url = self.meta('global_url')
        state = self.meta('global', {})
        if not url:
            return {'state': 'unconfigured', 'message': '全球全量数据尚未配置获授权的 CSV 来源。'}
        if not force and time.time() < state.get('next_update', 0):
            return state
        try:
            public_feed_url(url)
            request = Request(url, headers={'User-Agent': 'GeoLogHelper/0.2 (+https://github.com/yizhouren0622-create/geolog-helper)'})
            response = (opener or build_opener(SafeRedirect())).open(request, timeout=60)
            with response:
                if int(response.headers.get('Content-Length', 0)) > 1024 ** 3:
                    raise ValueError('数据源超过 1 GB')
                stream = gzip.GzipFile(fileobj=response) if urlparse(url).path.endswith('.gz') else response
                reader = csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig', newline=''))
                if not {'gc', 'name', 'lat', 'lng'}.issubset(set(reader.fieldnames or [])):
                    raise ValueError('CSV 缺少 gc,name,lat,lng 字段')
                count = 0
                with self.db() as conn:
                    for raw in reader:
                        count += 1
                        if count > 5000000:
                            raise ValueError('数据源超过 500 万条')
                        self.insert(conn, normalize(raw))
                    if count == 0:
                        raise ValueError('数据源为空')
                now = time.time()
                state = {'state': 'ok', 'last_update': now, 'next_update': six_months_later(now), 'loaded': count, 'error': ''}
        except Exception:
            state.update(state='error', error='全球数据更新失败；请检查公开 CSV 来源和网络，旧数据已保留。')
        self.set_meta('global', state)
        return state
