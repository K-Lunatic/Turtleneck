"""Read-only Moodle Web Service REST client."""
from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


class MoodleApiError(RuntimeError):
    def __init__(self, status: int, errorcode: str, message: str):
        self.status, self.errorcode, self.message = status, errorcode, message
        super().__init__(f"Moodle API 요청 실패: {message}")


MAX_API_RESPONSE_BYTES = 16 * 1024 * 1024


def _flatten(prefix: str, value, output: dict[str, str]) -> None:
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _flatten(f"{prefix}[{index}]", item, output)
    elif isinstance(value, dict):
        for key, item in value.items():
            _flatten(f"{prefix}[{key}]", item, output)
    else:
        output[prefix] = "" if value is None else str(value)


class MoodleWebServiceClient:
    """POST-only client; token is never returned, logged, or put in a URL."""

    def __init__(self, base_url: str, token: str, *, opener=urlopen, timeout: int = 30):
        parsed = urlsplit(str(base_url).rstrip("/"))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Moodle 주소는 HTTPS 주소여야 해요.")
        self.base_url = f"https://{parsed.hostname}" + (f":{parsed.port}" if parsed.port else "")
        self._token = str(token or "").strip()
        if not self._token or any(char in self._token for char in "\r\n"):
            raise ValueError("Moodle API 토큰이 필요해요.")
        self._opener, self.timeout = opener, timeout

    def _request(self, function: str, params: dict | None = None):
        if not function or "/" in function or "\\" in function:
            raise ValueError("Moodle API 함수 이름을 확인하지 못했어요.")
        values = {"wstoken": self._token, "wsfunction": function, "moodlewsrestformat": "json"}
        for key, value in (params or {}).items():
            _flatten(str(key), value, values)
        request = Request(self.base_url + "/webservice/rest/server.php",
                          data=urlencode(values).encode("utf-8"),
                          headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded",
                                   "User-Agent": "Turtleneck/MoodleProvider"}, method="POST")
        try:
            with self._opener(request, timeout=self.timeout) as response:
                status = response.status
                declared = response.headers.get("Content-Length")
                try:
                    declared_size = int(declared) if declared else None
                except (TypeError, ValueError):
                    declared_size = None
                if declared_size is not None and declared_size > MAX_API_RESPONSE_BYTES:
                    raise MoodleApiError(status, "response_too_large", "Moodle API 응답이 너무 커서 안전하게 처리하지 못했어요.")
                raw = response.read(MAX_API_RESPONSE_BYTES + 1)
                if len(raw) > MAX_API_RESPONSE_BYTES:
                    raise MoodleApiError(status, "response_too_large", "Moodle API 응답이 너무 커서 안전하게 처리하지 못했어요.")
                body = raw.decode("utf-8", "replace")
        except HTTPError as error:
            body = error.read(4096).decode("utf-8", "replace")
            raise MoodleApiError(error.code, "http_error", body[:500]) from error
        except URLError as error:
            raise ConnectionError("Moodle API에 연결하지 못했어요.") from error
        try:
            data = json.loads(body)
        except json.JSONDecodeError as error:
            raise MoodleApiError(status, "invalid_json", "Moodle API 응답을 읽지 못했어요.") from error
        if isinstance(data, dict) and (data.get("exception") or data.get("errorcode")):
            raise MoodleApiError(status, str(data.get("errorcode", "moodle_error")),
                                 str(data.get("message", "Moodle API 오류")))
        return data

    def site_info(self):
        return self._request("core_webservice_get_site_info")

    def courses(self, user_id: int | str):
        return self._request("core_enrol_get_users_courses", {"userid": user_id})

    def contents(self, course_id: int | str):
        return self._request("core_course_get_contents", {"courseid": course_id})

    def updates_since(self, course_id: int | str, since: int):
        return self._request("core_course_get_updates_since", {"courseid": course_id, "since": since})
