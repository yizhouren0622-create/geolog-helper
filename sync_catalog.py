"""Maintenance entry point. Never submits geocaching logs or opens sign-in UI."""
import argparse
from http.cookiejar import CookieJar
import json
import time
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener


def run(scope='all'):
    url = 'http://127.0.0.1:8765'
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
    try:
        with opener.open(url + '/api/state', timeout=3) as response:
            running = json.load(response).get('app') == 'GeoLogHelper'
    except Exception:
        running = False
    if running:
        with opener.open(url + '/', timeout=5) as response:
            response.read()
        request = Request(url + '/api/catalog/refresh', data=json.dumps({'scope': scope, 'force': False}).encode(),
                          headers={'Content-Type': 'application/json', 'Origin': url})
        with opener.open(request, timeout=10) as response:
            job_id = json.load(response)['job_id']
        for _ in range(1800):
            with opener.open(url + '/api/state', timeout=10) as response:
                job = json.load(response).get('jobs', {}).get(job_id, {})
            if job.get('state') != 'running':
                return {'state': job.get('state', 'unknown'), 'message': job.get('message', ''), 'catalog': job.get('catalog')}
            time.sleep(2)
        return {'state': 'pending', 'message': '维护仍在进行，请稍后查看软件中的数据面板。'}
    from app import GCClient
    client = GCClient(headless=True)
    try:
        return client.refresh_catalog({'scope': scope})
    finally:
        if client.ctx:
            client.ctx.close()
        if client.pw:
            client.pw.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope', choices=['all', 'regions', 'global'], default='all')
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.scope), ensure_ascii=False))
    except Exception:
        print(json.dumps({'state': 'error', 'message': '数据维护未完成；请检查登录或网络，旧数据已保留。'}, ensure_ascii=False))
        raise SystemExit(1)
