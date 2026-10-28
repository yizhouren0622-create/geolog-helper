"""Focused transport/state tests. No requests are sent to Geocaching."""
import base64
import importlib.util
import io
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
import concurrent.futures
import threading
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

TEST_DATA = tempfile.TemporaryDirectory()
os.environ['GEOLOG_DATA'] = TEST_DATA.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('app', Path(__file__).resolve().parents[1] / 'app.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class FakeClient:
    def __init__(self):
        self.creates = 0
        self.images = 0
        self.fail_create = False
        self.fail_image = False
        self.fail_caption = False
        self.fail_auth = False
    def headers(self):
        if self.fail_auth:
            raise app.Problem('login needed')
        return {}
    def create(self, draft, headers):
        self.creates += 1
        if self.fail_create:
            raise app.Uncertain('network interrupted')
        return 'GL12345'
    def image(self, log, photo, headers):
        self.images += 1
        if self.fail_image:
            raise app.Uncertain('network interrupted')
        return 'image-guid'
    def caption(self, log, photo, headers):
        if self.fail_caption:
            raise app.Problem('caption failed')

class TestPublishing(unittest.TestCase):
    def test_catalog_refresh_reports_incomplete_results(self):
        client = app.GCClient()
        with patch.object(app.CATALOG, 'due_regions', return_value=[{'id': 'shanghai'}]), \
             patch.object(app.CATALOG, 'status', return_value={}), \
             patch.object(app.CATALOG, 'meta', return_value=0), \
             patch.object(client, 'auth', return_value={}), \
             patch.object(app.CATALOG, 'sync_regions') as sync:
            for state, expected in [('error', '失败'), ('partial', '尚未完整'), ('ok', '已完成')]:
                with self.subTest(state=state):
                    sync.return_value = [{'state': state}]
                    self.assertIn(expected, client.refresh_catalog({'scope': 'regions'})['message'])
        with patch.object(app.CATALOG, 'due_regions', return_value=[]), \
             patch.object(app.CATALOG, 'status', return_value={}), \
             patch.object(app.CATALOG, 'sync_global', return_value={'state': 'unconfigured'}):
            self.assertIn('没有更新全球数据', client.refresh_catalog({'scope': 'global'})['message'])

    def draft(self, photo=False):
        d = app.new_draft()
        d.update(gc='GC12345', date='2026-01-01', text='真实经历', photos=[{'id':'a'*32, 'caption':'风景','state':'pending'}] if photo else [])
        return app.save(d)
    def test_success_saved_before_return(self):
        d = self.draft(True)
        client = FakeClient()
        app.publish(d['id'], client)
        saved = app.get(d['id'])
        self.assertEqual(saved['state'], 'published')
        self.assertEqual(saved['log_code'], 'GL12345')
        self.assertEqual(saved['photos'][0]['state'], 'done')
        app.publish(d['id'], client)
        self.assertEqual(client.creates, 1)
        self.assertEqual(client.images, 1)
    def test_uncertain_text_never_reposts(self):
        d = self.draft()
        client = FakeClient(); client.fail_create = True
        with self.assertRaises(app.Uncertain): app.publish(d['id'], client)
        self.assertEqual(app.get(d['id'])['state'], 'uncertain')
        client.fail_create = False
        with self.assertRaises(app.Problem): app.publish(d['id'], client)
        self.assertEqual(client.creates, 1)
    def test_caption_retry_does_not_reupload(self):
        d = self.draft(True)
        client = FakeClient(); client.fail_caption = True
        with self.assertRaises(app.Problem): app.publish(d['id'], client)
        client.fail_caption = False
        app.publish(d['id'], client)
        self.assertEqual(client.creates, 1)
        self.assertEqual(client.images, 1)
        self.assertEqual(app.get(d['id'])['state'], 'published')
    def test_uncertain_photo_does_not_duplicate_text_or_photo(self):
        d = self.draft(True)
        client = FakeClient(); client.fail_image = True
        with self.assertRaises(app.Problem): app.publish(d['id'], client)
        client.fail_image = False
        with self.assertRaises(app.Problem): app.publish(d['id'], client)
        self.assertEqual(client.creates, 1)
        self.assertEqual(client.images, 1)
        self.assertEqual(app.get(d['id'])['log_code'], 'GL12345')
    def test_auth_failure_unlocks_queued_draft(self):
        d = self.draft(); d['state']='queued'; app.save(d)
        client=FakeClient(); client.fail_auth=True
        with self.assertRaises(app.Problem): app.publish(d['id'],client)
        self.assertEqual(app.get(d['id'])['state'],'draft')
        self.assertEqual(client.creates,0)
    def test_missing_text_and_future_dates_rejected(self):
        d=self.draft(); d['text']=''; app.save(d)
        with self.assertRaises(app.Problem): app.publish(d['id'],FakeClient())
        d['text']='真实'; d['date']='2099-01-01'; app.save(d)
        with self.assertRaises(app.Problem): app.publish(d['id'],FakeClient())
    def test_ftf_cannot_be_published_as_dnf(self):
        d = self.draft()
        d.update(type=3, ftf=True)
        app.save(d)
        client = FakeClient()
        with self.assertRaises(app.Problem):
            app.publish(d['id'], client)
        self.assertEqual(client.creates, 0)
    def test_name_search_filters_server_results_and_keeps_scan_cursor(self):
        class Response:
            ok = True
            status = 200
            headers = {'content-type': 'application/json'}
            def __init__(self, rows): self.rows = rows
            def json(self): return {'results': self.rows, 'total': 150}
        class Request:
            def get(self, url, params, **kwargs):
                skip = int(params['skip'])
                rows = [{'code': 'GC' + str(i), 'name': 'Park' if i == 120 else 'Unrelated'}
                        for i in range(skip, min(skip + 100, 150))]
                return Response(rows)
        class Context: request = Request()
        client = app.GCClient()
        client.ctx = Context()
        with patch.object(app.time, 'sleep'):
            result = client.search_caches({'keyword': 'Park', 'region': 'shanghai'}, headers={'test': 'only'}, store=False)
        self.assertEqual([row['gc'] for row in result['caches']], ['GC120'])
        self.assertEqual(result['next_skip'], 150)
        self.assertFalse(result['has_more'])
    def test_image_upload_copy_has_no_exif_and_is_compressed(self):
        from PIL import Image
        image=Image.new('RGB',(3000,2400),'green')
        exif=Image.Exif(); exif[306]='2026:01:01 09:00:00'
        buf=io.BytesIO(); image.save(buf,format='JPEG',exif=exif)
        d=app.add_photo(self.draft(),{'name':'test.jpg','data':base64.b64encode(buf.getvalue()).decode()})
        photo=d['photos'][0]
        with Image.open(app.DATA/'photos'/(photo['id']+'.jpg')) as out:
            self.assertEqual(len(out.getexif()),0)
            self.assertLessEqual(max(out.size),2000)
        self.assertIn('2026',photo['taken'])

class TestLocalEndpoints(unittest.TestCase):
    def setUp(self):
        self.old_port, self.old_worker = app.PORT, app.WORKER
        app.JOBS.clear()
        self.calls = []
        self.future = concurrent.futures.Future()
        owner = self
        class Worker:
            def submit(self, action, arg=None):
                owner.calls.append((action, arg))
                return owner.future
        app.WORKER = Worker()
        self.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        app.PORT = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(app.PORT)
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.future.cancel()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        app.PORT, app.WORKER = self.old_port, self.old_worker
        app.JOBS.clear()

    def post(self, draft):
        request = Request(self.url + '/api/publish',
            data=json.dumps({'id': draft['id'], 'confirmed': True}).encode(),
            headers={'Content-Type': 'application/json', 'Origin': self.url,
                     'Cookie': 'geolog=' + app.SESSION})
        try:
            with self.opener.open(request, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_uncertain_result_cannot_be_overwritten_by_http_retry(self):
        for state in ('creating', 'uncertain'):
            with self.subTest(state=state):
                draft = app.new_draft()
                draft.update(gc='GC12345', text='本地测试，禁止发布', state=state)
                app.save(draft)
                status, result = self.post(draft)
                self.assertEqual(status, 400)
                self.assertIn('核对', result['error'])
                self.assertEqual(app.get(draft['id'])['state'], state)
        self.assertEqual(self.calls, [])

    def test_repeat_confirm_click_only_queues_once(self):
        draft = app.new_draft()
        draft.update(gc='GC12345', text='本地测试，禁止发布')
        app.save(draft)
        self.assertEqual(self.post(draft)[0], 200)
        self.assertEqual(self.post(draft)[0], 400)
        self.assertEqual(len(self.calls), 1)

    def test_inflight_autosave_cannot_unlock_a_queued_publish(self):
        draft = app.new_draft()
        draft.update(gc='GC12345', text='本地测试，禁止发布')
        app.save(draft)
        read, release = threading.Event(), threading.Event()
        original_get = app.get
        result = []
        def delayed_get(draft_id):
            value = original_get(draft_id)
            if not read.is_set():
                read.set()
                if not release.wait(5):
                    raise RuntimeError('test coordination timed out')
            return value
        def autosave():
            req = Request(self.url + '/api/save',
                data=json.dumps({'id': draft['id'], 'text': 'outdated autosave'}).encode(),
                headers={'Content-Type': 'application/json', 'Origin': self.url,
                         'Cookie': 'geolog=' + app.SESSION})
            try:
                with self.opener.open(req, timeout=5) as response:
                    result.append(response.status)
            except HTTPError as error:
                result.append(error.code)
        with patch.object(app, 'get', side_effect=delayed_get):
            thread = threading.Thread(target=autosave)
            thread.start()
            try:
                self.assertTrue(read.wait(3))
                self.assertEqual(self.post(draft)[0], 200)
            finally:
                release.set()
                thread.join(5)
        self.assertEqual(result, [400])
        self.assertEqual(app.get(draft['id'])['state'], 'queued')
        self.assertEqual(app.get(draft['id'])['text'], '本地测试，禁止发布')

if __name__=='__main__':
    unittest.main()
