"""Start the local server without a console; open the helper in its Firefox."""
import json
from pathlib import Path
import subprocess
import sys
import time
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

root = Path(__file__).resolve().parent
url = 'http://127.0.0.1:8765'
opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
def running():
    try:
        with opener.open(url + '/api/state', timeout=1) as response:
            return json.load(response).get('app') == 'GeoLogHelper'
    except Exception:
        return False

if not running():
    with (root / 'startup.log').open('a', encoding='utf-8') as log:
        subprocess.Popen([sys.executable, str(root / 'app.py')], cwd=root,
            stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for _ in range(40):
        if running():
            break
        time.sleep(.25)
try:
    with opener.open(url + '/', timeout=5) as response:
        response.read()
    request = Request(url + '/api/helper', data=b'{}', headers={
        'Content-Type': 'application/json', 'Origin': url})
    with opener.open(request, timeout=70) as response:
        response.read()
except Exception as error:
    with (root / 'startup.log').open('a', encoding='utf-8') as log:
        log.write('Could not open Firefox helper: ' + type(error).__name__ + '\n')
