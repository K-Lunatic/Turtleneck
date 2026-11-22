"""Small Moodle session client; credentials and cookies stay in memory."""
from __future__ import annotations

import gzip
import json
import mimetypes
import os
import random
import re
import secrets
import ssl
import sys
import threading
import time
import zlib
from copy import copy
from urllib.error import HTTPError, URLError
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import Request, build_opener, BaseHandler, HTTPRedirectHandler, HTTPCookieProcessor, HTTPSHandler
from providers.request_metrics import MetricsHandler, current_metrics


class LoginError(RuntimeError):
    pass


class DownloadRestricted(RuntimeError):
    pass


class RequestBackoff(URLError):
    def __init__(self, seconds):
        self.seconds = max(0, seconds)
        super().__init__('학교 요청을 잠시 쉬어야 해요. 대기 시간이 지난 후 다시 확인해 주세요.')


def _retry_after(value):
    if not value:
        return 0
    try:
        if value.strip().isdigit():
            return int(value)
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, (parsed - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return 0


class _RequestLimiter:
    """Keep parallel reads bounded per logged-in account."""
    def __init__(self, gap: float = 0.25):
        self.gap = gap
        self.next_at = 0.0
        self.lock = threading.Lock()
        self.deferred_until = 0.0

    def wait(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                if self.deferred_until > now:
                    raise RequestBackoff(self.deferred_until - now)
                delay = self.next_at - now
                if delay <= 0:
                    self.next_at = now + self.gap
                    return
            time.sleep(delay)

    def pause(self, seconds, *, deferred=False):
        with self.lock:
            if deferred:
                self.deferred_until = max(self.deferred_until, time.monotonic() + seconds)
            else:
                self.next_at = max(self.next_at, time.monotonic() + seconds)


class _RateLimitHandler(BaseHandler):
    handler_order = 480

    def __init__(self, limiter):
        self.limiter = limiter

    def http_request(self, request):
        self.limiter.wait()
        return request

    https_request = http_request


def _default_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    paths = ssl.get_default_verify_paths()
    has_trust_store = ((paths.cafile and Path(paths.cafile).is_file()) or
                       (paths.capath and Path(paths.capath).is_dir()))
    if not has_trust_store and sys.platform == "darwin":
        for candidate in ("/private/etc/ssl/cert.pem", "/etc/ssl/cert.pem"):
            if Path(candidate).is_file():
                context.load_verify_locations(cafile=candidate)
                break
    return context


def check_download_url(url: str) -> None:
    query = {key.lower(): values for key, values in parse_qs(urlsplit(url).query).items()}
    denied = any(value.lower() in {"1", "true", "yes"} for key in ("nodownload", "disable_download", "disabledownload") for value in query.get(key, []))
    denied |= any(value.lower() in {"0", "false", "no"} for key in ("allowdownload", "allow_download") for value in query.get(key, []))
    if denied:
        raise DownloadRestricted("파일 주소에 다운로드 금지가 표시되어 파일을 가져오지 않았습니다.")
    # A viewer URL alone is not a prohibition. The course page's visible text
    # is checked by the Moodle adapter; forcedownload=0 also only means inline display.


def check_download_origin(url, origin):
    if not origin:
        return
    try:
        parts = urlsplit(url)
        expected = urlsplit('https://' + origin)
        allowed = (parts.scheme == 'https' and parts.hostname == expected.hostname and
                   (parts.port or 443) == (expected.port or 443) and
                   not parts.username and not parts.password)
    except ValueError:
        allowed = False
    if not allowed:
        raise DownloadRestricted('학교 자료 주소가 달라져 가져오기를 멈췄어요.')


class _DownloadRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            check_download_url(newurl)
            check_download_origin(newurl, getattr(req, 'allowed_origin', None))
        except DownloadRestricted:
            fp.close()
            raise
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.allowed_origin = getattr(req, 'allowed_origin', None)
            redirected.metrics_kind = getattr(req, 'metrics_kind', 'page')
        return redirected


class _HiddenInputs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}
        self.action: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form" and self.action is None:
            self.action = values.get("action")
        if tag == "input" and values.get("type", "").lower() == "hidden" and values.get("name"):
            self.values[values["name"]] = values.get("value") or ""


class MoodleSession:
    def __init__(self, base_url: str = "https://tls.kku.ac.kr", *, metrics=None, _limiter=None):
        self.base_url = base_url.rstrip("/")
        self.metrics = metrics if metrics is not None else current_metrics.get()
        self.cookies = CookieJar()
        self._request_limiter = _limiter if _limiter is not None else _RequestLimiter()
        self._build_opener()
        self.logged_in = False

    def _build_opener(self) -> None:
        handlers = [HTTPCookieProcessor(self.cookies), _DownloadRedirectHandler(),
                    _RateLimitHandler(self._request_limiter), HTTPSHandler(context=_default_ssl_context())]
        if self.metrics is not None:
            handlers.append(MetricsHandler(self.metrics))
        self.opener = build_opener(*handlers)

    def _open(self, request, *, kind):
        request.metrics_kind = kind
        retry_safe = request.get_method() == 'GET' or getattr(request, 'retry_safe', False)
        for attempt in range(3):
            try:
                return self.opener.open(request, timeout=30)
            except Exception as error:
                if self.metrics is not None:
                    self.metrics.failed()
                if isinstance(error, RequestBackoff):
                    raise
                if isinstance(error, HTTPError):
                    if error.code not in (429, 502, 503, 504):
                        raise
                    server_delay = _retry_after(error.headers.get('Retry-After') if error.headers else None)
                    error.close()
                elif isinstance(error, (URLError, TimeoutError, ConnectionError)):
                    if isinstance(getattr(error, 'reason', error), ssl.SSLError):
                        raise
                    server_delay = 0
                else:
                    raise
                delay = max(server_delay, 2 ** attempt + random.uniform(0, 0.25))
                if not retry_safe or attempt == 2 or delay > 5:
                    delay = max(server_delay, 60)
                    self._request_limiter.pause(delay, deferred=True)
                    raise RequestBackoff(delay) from error
                self._request_limiter.pause(delay)

    def restore_cookies(self, cookies: CookieJar) -> None:
        self.cookies = cookies
        self._build_opener()

    def resume(self) -> bool:
        """Verify a protected cookie jar without sending credentials."""
        if not any(cookie.name and cookie.value for cookie in self.cookies):
            return False
        self.logged_in = True
        try:
            self._request("/")
        except LoginError:
            self.logged_in = False
            return False
        except Exception:
            self.logged_in = False
            raise
        return True

    def fork(self):
        """Independent cookie jar/opener per read worker; login remains single-threaded."""
        child = MoodleSession(self.base_url, metrics=self.metrics, _limiter=self._request_limiter)
        for cookie in self.cookies:
            child.cookies.set_cookie(copy(cookie))
        child.logged_in = self.logged_in
        return child

    def revalidate(self, path, cached):
        headers = {name: cached[key] for name, key in
                   (('If-None-Match', 'etag'), ('If-Modified-Since', 'lastModified')) if cached.get(key)}
        return self.get_bytes(path, conditional=headers, allowed_origin=urlsplit(self.base_url).hostname)

    @staticmethod
    def _decode_bytes(payload: bytes, response: Any) -> bytes:
        encoding = response.headers.get("Content-Encoding", "").lower()
        if "gzip" in encoding:
            return gzip.decompress(payload)
        elif "deflate" in encoding:
            return zlib.decompress(payload)
        return payload

    @classmethod
    def _decode(cls, response: Any) -> str:
        return cls._decode_bytes(response.read(), response).decode("utf-8", errors="replace")

    def _request(self, path: str, *, data: bytes | None = None, referer: str | None = None, allowed_origin=None, page_only=False, retry_safe=False) -> tuple[str, Any]:
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        check_download_origin(url, allowed_origin)
        if data is None:
            check_download_url(url)
        headers = {
            "User-Agent": "UniversityAgent/0.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        }
        if data is not None:
            headers.update({"Content-Type": "application/x-www-form-urlencoded", "Origin": self.base_url, "Referer": referer or url})
        request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
        request.allowed_origin = allowed_origin
        request.retry_safe = retry_safe
        response = self._open(request, kind='post' if data is not None else 'page')
        try:
            check_download_origin(response.geturl(), allowed_origin)
            if data is None:
                check_download_url(response.geturl())
            content_type = response.headers.get('Content-Type', '').split(';', 1)[0].lower().strip()
            # File redirects are not HTML notices. Do not transfer an entire
            # cached PDF merely to look for a download prohibition in a page.
            binary_file = content_type.startswith(('application/pdf', 'application/octet-stream',
                'application/msword', 'application/vnd.', 'application/x-hwp', 'image/', 'video/', 'audio/'))
            binary_file |= content_type in ('application/zip', 'application/x-zip-compressed', 'application/x-7z-compressed', 'application/x-rar-compressed')
            html = '' if data is None and (binary_file or (page_only and content_type not in ('text/html', 'application/xhtml+xml'))) else self._decode(response)
        finally:
            response.close()
        if self.logged_in and ("/login" in urlsplit(response.geturl()).path or re.search(r'name=["\']username["\']', html, re.I)):
            self.logged_in = False
            raise LoginError("TLS session expired; sign in again")
        return html, response

    def login(self, username: str, password: str) -> None:
        login_path = "/login/index.php"
        login_html, login_response = self._request(login_path)
        parser = _HiddenInputs()
        parser.feed(login_html)
        form_path = parser.action or login_path
        fields = {**parser.values, "username": username, "password": password}
        try:
            html, response = self._request(form_path, data=urlencode(fields).encode(), referer=login_response.geturl())
        finally:
            fields["password"] = None
        has_cookie = any(cookie.name == "MoodleSession" for cookie in self.cookies)
        still_login_form = bool(re.search(r'name=["\']username["\']', html, re.I))
        if not has_cookie or still_login_form or "/login" in response.geturl():
            code = parse_qs(urlsplit(response.geturl()).query).get("errorcode", [None])[0]
            detail = f" (Moodle errorcode={code})" if code else ""
            raise LoginError(f"TLS login failed{detail}; check credentials or Moodle login flow")
        self.logged_in = True
        try:
            # A Moodle session cookie can be issued before the account is actually accepted.
            self._request("/")
        except LoginError:
            self.logged_in = False
            raise LoginError("TLS login could not be verified; please sign in again") from None
        except Exception:
            self.logged_in = False
            raise

    def get(self, path: str) -> str:
        return self.get_page(path)[0]

    def get_page(self, path: str, *, allowed_origin=None) -> tuple[str, str]:
        if not self.logged_in:
            raise LoginError("Call login() before get()")
        html, response = self._request(path, allowed_origin=allowed_origin)
        return html, response.geturl()

    def get_page_info(self, path: str, *, allowed_origin=None):
        if not self.logged_in:
            raise LoginError('Call login() before get()')
        html, response = self._request(path, allowed_origin=allowed_origin, page_only=True)
        return html, response.geturl(), response.headers

    def post_bytes(self, path: str, payload: bytes, *, content_type: str,
                   referer: str | None = None, allowed_origin=None) -> tuple[str, Any]:
        """POST a browser-compatible body while keeping cookies in this session."""
        if not self.logged_in:
            raise LoginError('Call login() before post_bytes()')
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        check_download_origin(url, allowed_origin)
        headers = {
            "User-Agent": "UniversityAgent/0.1",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": content_type,
            "Origin": self.base_url,
            "Referer": referer or url,
        }
        request = Request(url, data=payload, headers=headers, method="POST")
        request.allowed_origin = allowed_origin
        response = self._open(request, kind='post')
        try:
            check_download_origin(response.geturl(), allowed_origin)
            html = self._decode(response)
        finally:
            response.close()
        if "/login" in urlsplit(response.geturl()).path or re.search(r'name=["\']username["\']', html, re.I):
            self.logged_in = False
            raise LoginError("TLS session expired; sign in again")
        return html, response

    def post_multipart_file(self, path: str, fields: dict[str, str], field_name: str,
                            file_path, *, referer: str | None = None,
                            allowed_origin=None) -> tuple[str, Any, int]:
        """POST a multipart file without materializing its bytes in memory."""
        if not self.logged_in:
            raise LoginError('Call login() before post_multipart_file()')
        file_path = Path(file_path)
        if not file_path.is_file():
            raise FileNotFoundError(file_path)
        boundary = '----Turtleneck' + secrets.token_hex(12)
        prefix = b''.join(
            part
            for name, value in fields.items()
            for part in (f'--{boundary}\r\n'.encode(),
                         f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                         str(value).encode(), b'\r\n'))
        filename = file_path.name.replace('"', '_').replace('\r', '_').replace('\n', '_')
        content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        file_prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; '
                       f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n').encode()
        suffix = f'\r\n--{boundary}--\r\n'.encode()
        total = len(prefix) + len(file_prefix) + file_path.stat().st_size + len(suffix)

        class _Body:
            def __init__(self):
                self.parts = iter((prefix, file_prefix))
                self.current = b''
                self.stream = None
                self.finished_prefix = False
                self.finished_file = False

            def read(self, size=-1):
                if size == 0:
                    return b''
                output = bytearray()
                while size < 0 or len(output) < size:
                    if not self.current:
                        if not self.finished_prefix:
                            self.current = next(self.parts, b'')
                            if not self.current:
                                self.finished_prefix = True
                                self.stream = file_path.open('rb')
                                continue
                        elif not self.finished_file:
                            self.current = self.stream.read(size if size > 0 else 1024 * 1024)
                            if not self.current:
                                self.stream.close()
                                self.finished_file = True
                                self.current = suffix
                        else:
                            break
                    if not self.current:
                        continue
                    take = len(self.current) if size < 0 else min(len(self.current), size - len(output))
                    output.extend(self.current[:take])
                    self.current = self.current[take:]
                    if size > 0 and len(output) >= size:
                        break
                return bytes(output)

            def close(self):
                if self.stream is not None and not self.stream.closed:
                    self.stream.close()

        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        check_download_origin(url, allowed_origin)
        body = _Body()
        request = Request(url, data=body, headers={
            'User-Agent': 'UniversityAgent/0.1',
            'Accept': 'text/html,application/json;q=0.9,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Content-Length': str(total),
            'Origin': self.base_url,
            'Referer': referer or url,
        }, method='POST')
        request.allowed_origin = allowed_origin
        try:
            response = self._open(request, kind='post')
            try:
                check_download_origin(response.geturl(), allowed_origin)
                html = self._decode(response)
                response_url = response.geturl()
            finally:
                response.close()
            if "/login" in urlsplit(response_url).path or re.search(r'name=["\']username["\']', html, re.I):
                self.logged_in = False
                raise LoginError("TLS session expired; sign in again")
            return html, response, total
        finally:
            body.close()

    def document_state(self, viewer_url):
        """The viewer's read-only status request; never start file conversion/upload."""
        if not self.logged_in:
            raise LoginError('Call login() before get()')
        check_download_origin(viewer_url, 'tls.kku.ac.kr')
        check_download_url(viewer_url)
        parts = urlsplit(viewer_url)
        query = parse_qs(parts.query, keep_blank_values=True)
        if (parts.path != '/local/ubdoc/' or parts.fragment or set(query) != {'id', 'tp', 'pg'} or
            any(len(values) != 1 for values in query.values()) or not re.fullmatch(r'[1-9][0-9]*', query['id'][0]) or
            query['tp'] != ['m'] or query['pg'] != ['ubfile']):
            raise ValueError('문서 상태를 확인할 주소가 올바르지 않아요.')
        fields = {key: values[0] for key, values in query.items()}
        html, _ = self._request('/local/ubdoc/worker.php',
            data=urlencode({**fields, 'job': 'checkState', 'item': '', 'fid': ''}).encode(),
            referer=viewer_url, allowed_origin='tls.kku.ac.kr', retry_safe=True)
        try:
            value = json.loads(html)
        except ValueError as error:
            raise ValueError('학교의 문서 상태 응답을 읽지 못했어요.') from error
        if not isinstance(value, dict):
            raise ValueError('학교의 문서 상태 응답 형식이 달라요.')
        return {key: value.get(key) for key in ('state_code', 'file_download')}

    def get_bytes(self, path: str, *, conditional=None, allowed_origin=None, max_bytes=None) -> tuple[bytes | None, Any]:
        if not self.logged_in:
            raise LoginError("Call login() before get_bytes()")
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        check_download_url(url)
        check_download_origin(url, allowed_origin)
        try:
            request = Request(url, headers={"User-Agent": "UniversityAgent/0.1", "Accept-Encoding": "identity" if max_bytes is not None else "gzip, deflate", **(conditional or {})})
            request.allowed_origin = allowed_origin
            response = self._open(request, kind='file')
        except HTTPError as error:
            if error.code != 304:
                error.close()
                raise
            try:
                check_download_url(error.geturl())
                check_download_origin(error.geturl(), allowed_origin)
                return None, error
            finally:
                error.close()
        try:
            check_download_url(response.geturl())
            check_download_origin(response.geturl(), allowed_origin)
            if "/login" in urlsplit(response.geturl()).path:
                self.logged_in = False
                raise LoginError("TLS session expired; sign in again")
            payload = response.read() if max_bytes is None else response.read(max_bytes + 1)
            if max_bytes is not None and len(payload) > max_bytes:
                raise ValueError('영상 조각이 너무 커서 가져오기를 멈췄어요.')
            if max_bytes is not None and response.headers.get('Content-Encoding', '').lower() not in ('', 'identity'):
                raise ValueError('영상 응답 형식이 달라 가져오기를 멈췄어요.')
            payload = self._decode_bytes(payload, response)
            if max_bytes is not None and len(payload) > max_bytes:
                raise ValueError('영상 조각이 너무 커서 가져오기를 멈췄어요.')
            return payload, response
        finally:
            response.close()

    def stream_bytes_to_file(self, path: str, target, *, allowed_origin=None,
                             max_bytes=None, chunk_size=1024 * 1024,
                             resume_existing=False) -> dict:
        """Write one binary response directly to a temporary file, resuming safe ranges."""
        if not self.logged_in:
            raise LoginError("Call login() before stream_bytes_to_file()")
        if not isinstance(chunk_size, int) or chunk_size <= 0:
            raise ValueError('영상 조각 저장 단위가 올바르지 않아요.')
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        check_download_url(url)
        check_download_origin(url, allowed_origin)
        written = 0
        if resume_existing and Path(target).is_file():
            written = Path(target).stat().st_size
            if max_bytes is not None and written > max_bytes:
                raise ValueError('자료가 허용된 크기를 넘어 가져오기를 멈췄어요.')
        response_url = url
        response_headers = None
        for attempt in range(3):
            request_start = written
            headers = {"User-Agent": "UniversityAgent/0.1", "Accept-Encoding": "identity"}
            if written:
                headers['Range'] = f'bytes={written}-'
            request = Request(url, headers=headers)
            request.allowed_origin = allowed_origin
            response = None
            try:
                response = self._open(request, kind='file')
                check_download_url(response.geturl())
                check_download_origin(response.geturl(), allowed_origin)
                if "/login" in urlsplit(response.geturl()).path:
                    self.logged_in = False
                    raise LoginError("TLS session expired; sign in again")
                if response.headers.get('Content-Encoding', '').lower() not in ('', 'identity'):
                    raise ValueError('영상 응답 형식이 달라 가져오기를 멈췄어요.')
                status = response.getcode() if hasattr(response, 'getcode') else getattr(response, 'status', 200)
                total_size = None
                if written:
                    content_range = response.headers.get('Content-Range', '')
                    match = re.fullmatch(r'bytes\s+(\d+)-(\d+)/(\d+|\*)', content_range.strip(), re.I)
                    if status != 206 or not match or int(match.group(1)) != written:
                        raise ValueError('학교가 자료 이어받기를 지원하지 않아 처음부터 다시 확인해야 해요.')
                    range_start, range_end = int(match.group(1)), int(match.group(2))
                    if range_end < range_start or (match.group(3) != '*' and int(match.group(3)) <= range_end):
                        raise ValueError('학교가 자료 이어받기 범위를 올바르게 알려주지 않았어요.')
                    if match.group(3) != '*':
                        total_size = int(match.group(3))
                    if declared := response.headers.get('Content-Length'):
                        try:
                            if int(declared) != range_end - range_start + 1:
                                raise ValueError('학교가 자료 이어받기 크기를 올바르게 알려주지 않았어요.')
                        except ValueError:
                            raise ValueError('학교가 자료 이어받기 크기를 올바르게 알려주지 않았어요.')
                declared = response.headers.get('Content-Length')
                try:
                    declared_size = int(declared) if declared is not None else None
                except (TypeError, ValueError):
                    declared_size = None
                if declared_size is not None and declared_size < 0:
                    raise ValueError('학교가 자료 크기를 올바르게 알려주지 않아 가져오기를 멈췄어요.')
                if max_bytes is not None and written + (declared_size or 0) > max_bytes:
                    raise ValueError('자료가 허용된 크기를 넘어 가져오기를 멈췄어요.')
                if total_size is None and status == 200 and declared_size is not None:
                    total_size = declared_size
                response_url = response.geturl()
                response_headers = response.headers
                with open(target, 'ab' if written else 'wb') as output:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        if total_size is not None and written + len(chunk) > total_size:
                            raise ValueError('학교가 알려준 자료 크기보다 많은 데이터를 보내 가져오기를 멈췄어요.')
                        written += len(chunk)
                        if max_bytes is not None and written > max_bytes:
                            raise ValueError('자료가 허용된 크기를 넘어 가져오기를 멈췄어요.')
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if total_size is not None and written < total_size:
                    if attempt == 2:
                        raise URLError('자료가 끝까지 전송되지 않았어요.')
                    continue
                return {'size': written, 'url': response_url, 'headers': response_headers}
            except (URLError, TimeoutError, ConnectionError, OSError) as error:
                if isinstance(error, RequestBackoff) or attempt == 2:
                    raise
            finally:
                if response is not None:
                    response.close()
        raise URLError('자료를 끝까지 받지 못했어요.')
