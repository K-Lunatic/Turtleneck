"""Open local study pages in a running companion, with browser fallback."""
from __future__ import annotations

import json
from pathlib import Path
import re
import webbrowser
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler

RUNTIME_PATH = Path.home() / '.university-agent' / 'companion-runtime.json'
PAGE_KINDS = {'login', 'exam', 'dashboard'}


def validate_page(url: str, kind: str) -> str:
    parsed = urlsplit(url)
    if (kind not in PAGE_KINDS or parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
            or parsed.username or parsed.password or not parsed.port or len(url) > 4096):
        raise ValueError('이 컴퓨터에서 준비한 터틀넥 화면만 열 수 있어요.')
    return url


def open_local_page(url: str, *, kind: str = 'exam') -> dict:
    validate_page(url, kind)
    try:
        if RUNTIME_PATH.is_symlink() or RUNTIME_PATH.stat().st_size > 1024:
            raise ValueError('invalid companion marker')
        marker = json.loads(RUNTIME_PATH.read_text(encoding='utf-8'))
        port, token = marker['port'], marker['token']
        if type(port) is not int or not 1 <= port <= 65535 or not re.fullmatch(r'[\w-]{32,128}', token):
            raise ValueError('invalid companion address')
        request = Request(f'http://127.0.0.1:{port}/present',
            data=json.dumps({'url': url, 'kind': kind}).encode(), method='POST',
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        with build_opener(ProxyHandler({})).open(request, timeout=2) as response:
            result = json.loads(response.read(4096))
        if result.get('accepted') is True:
            return {'target': 'companion', 'requested': True}
    except (OSError, ValueError, TypeError, KeyError):
        pass
    try:
        requested = bool(webbrowser.open(url))
    except (OSError, webbrowser.Error):
        requested = False
    return {'target': 'browser', 'requested': requested}
