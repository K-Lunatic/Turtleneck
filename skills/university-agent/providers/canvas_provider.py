"""Read-only Canvas LMS API provider."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


class CanvasApiError(RuntimeError):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"Canvas API request failed ({status})")


def normalize_canvas_domain(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Canvas 주소를 입력해 주세요.")
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlsplit(raw)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or
            parsed.path not in ("", "/")):
        raise ValueError("Canvas 주소는 HTTPS 도메인만 사용할 수 있어요.")
    return urlunsplit(("https", parsed.netloc, "", "", "")).rstrip("/")


class CanvasClient:
    """Small HTTPS client; the token never appears in returned data."""

    def __init__(self, domain: str, token: str, *, opener=urlopen, timeout: int = 30):
        self.domain = normalize_canvas_domain(domain)
        self._token = str(token or "").strip()
        if not self._token:
            raise ValueError("Canvas API 토큰이 필요해요.")
        self._opener = opener
        self.timeout = timeout

    def _same_origin(self, url: str) -> bool:
        parsed = urlsplit(url)
        expected = urlsplit(self.domain)
        return parsed.scheme == "https" and parsed.hostname == expected.hostname and parsed.port == expected.port

    def _url(self, path: str, params: dict[str, str] | None = None) -> str:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Canvas API 경로를 확인하지 못했어요.")
        url = f"{self.domain}/api/v1{path}"
        if params:
            url += "?" + urlencode(params)
        return url

    def _request(self, url: str):
        if not self._same_origin(url):
            raise ValueError("Canvas 응답이 다른 주소로 이동해 요청을 멈췄어요.")
        request = Request(url, headers={
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": "Turtleneck/CanvasProvider",
        })
        try:
            return self._opener(request, timeout=self.timeout)
        except HTTPError as error:
            body = error.read(4096).decode("utf-8", "replace")
            raise CanvasApiError(error.code, body) from error
        except URLError as error:
            raise ConnectionError("Canvas에 연결하지 못했어요.") from error

    def get(self, path: str, params: dict[str, str] | None = None):
        url = self._url(path, params)
        with self._request(url) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _next_link(header: str | None) -> str | None:
        if not header:
            return None
        match = re.search(r'<([^>]+)>\s*;\s*rel="next"', header, re.I)
        return match.group(1) if match else None

    def get_all(self, path: str, params: dict[str, str] | None = None) -> list[dict]:
        query = dict(params or {})
        query.setdefault("per_page", "100")
        next_url = self._url(path, query)
        result: list[dict] = []
        while next_url:
            with self._request(next_url) as response:
                data = json.loads(response.read().decode("utf-8"))
                if not isinstance(data, list):
                    raise CanvasApiError(200, "Canvas 목록 응답 형식이 아니에요.")
                result.extend(data)
                next_url = self._next_link(response.headers.get("Link"))
                if next_url and not self._same_origin(next_url):
                    raise ValueError("Canvas 페이지 이동 주소가 같은 학교가 아니어서 멈췄어요.")
        return result

    def validate(self) -> dict:
        return self.get("/users/self/profile")


class CanvasProvider:
    """Normalize read-only Canvas data into the shared academic shape."""

    def __init__(self, client: CanvasClient):
        self.client = client
        self._courses: list[dict] | None = None

    def get_user(self) -> dict:
        return self.client.validate()

    def get_courses(self, _user_id: str | None = None) -> list[dict]:
        if self._courses is None:
            rows = self.client.get_all("/courses", {
                "enrollment_state": "active",
                "include[]": "total_scores",
            })
            self._courses = [{
                "id": f"canvas-course-{row['id']}",
                "externalId": str(row["id"]),
                "name": row.get("name") or row.get("course_code") or f"Canvas course {row['id']}",
                "courseCode": row.get("course_code"),
                "currentGrade": (row.get("enrollments") or [{}])[0].get("computed_current_grade"),
                "currentScore": (row.get("enrollments") or [{}])[0].get("computed_current_score"),
                "description": row.get("public_description") or row.get("syllabus_body"),
                "source": "canvas",
            } for row in rows if isinstance(row, dict) and row.get("id") is not None]
        return [dict(item) for item in self._courses]

    def _course(self, course_id: str | int) -> dict:
        value = str(course_id).removeprefix("canvas-course-")
        if not value.isdigit():
            raise ValueError("Canvas 과목 ID를 확인하지 못했어요.")
        return next((course for course in self.get_courses()
                     if course["externalId"] == value), {
                         "id": f"canvas-course-{value}", "externalId": value,
                         "name": f"Canvas course {value}", "source": "canvas"})

    @staticmethod
    def _submission_status(row: dict) -> str:
        submission = row.get("submission")
        if not isinstance(submission, dict):
            return "UNKNOWN"
        if not submission.get("submitted_at"):
            return "NOT_SUBMITTED"
        return "LATE" if submission.get("late") else "SUBMITTED"

    def get_assignments(self, _user_id: str | None = None) -> list[dict]:
        result = []
        for course in self.get_courses():
            rows = self.client.get_all(
                f"/courses/{course['externalId']}/assignments",
                {"include[]": "submission"})
            for row in rows:
                if row.get("id") is None:
                    continue
                result.append({
                    "id": f"canvas-assignment-{row['id']}",
                    "externalId": str(row["id"]),
                    "courseId": course["id"],
                    "courseName": course["name"],
                    "title": row.get("name") or f"Canvas assignment {row['id']}",
                    "description": row.get("description") or "",
                    "url": row.get("html_url"),
                    "dueAt": row.get("due_at"),
                    "submissionStatus": self._submission_status(row),
                    "source": "canvas",
                })
        return result

    def get_modules(self, course_id: str | int) -> list[dict]:
        course = self._course(course_id)
        rows = self.client.get_all(
            f"/courses/{course['externalId']}/modules", {"include[]": "items"})
        return [{
            "id": f"canvas-module-{row['id']}",
            "externalId": str(row["id"]),
            "courseId": course["id"],
            "name": row.get("name") or f"Canvas module {row['id']}",
            "position": row.get("position"),
            "state": row.get("state"),
            "items": row.get("items") or [],
            "source": "canvas",
        } for row in rows if row.get("id") is not None]

    def get_course_resources(self, course_id: str | int) -> list[dict]:
        course = self._course(course_id)
        rows = self.client.get_all(
            f"/courses/{course['externalId']}/files",
            {"sort": "updated_at", "order": "desc"})
        return [{
            "id": f"canvas-resource-{row['id']}",
            "externalId": str(row["id"]),
            "courseId": course["id"],
            "title": row.get("display_name") or row.get("filename") or f"Canvas file {row['id']}",
            "fileName": row.get("filename") or row.get("display_name") or f"file-{row['id']}",
            "extension": Path(row.get("filename") or "").suffix.lower().lstrip(".") or "unknown",
            "mimeType": row.get("content-type"),
            "remotePath": row.get("url") or row.get("html_url"),
            "sizeBytes": row.get("size"),
            "downloadStatus": "NOT_DOWNLOADED",
            "source": "canvas",
        } for row in rows if row.get("id") is not None]

    def get_resources(self, _user_id: str | None = None) -> list[dict]:
        """Return all enrolled-course files in the shared Provider shape."""
        result = []
        for course in self.get_courses():
            result.extend(self.get_course_resources(course["id"]))
        return result

    def get_course_notices(self, course_id: str | int) -> list[dict]:
        course = self._course(course_id)
        rows = self.client.get_all(
            f"/courses/{course['externalId']}/discussion_topics",
            {"only_announcements": "true"})
        return [{
            "id": f"canvas-notice-{row['id']}",
            "externalId": str(row["id"]),
            "courseId": course["id"],
            "title": row.get("title") or f"Canvas notice {row['id']}",
            "content": row.get("message") or "",
            "publishedAt": row.get("posted_at") or row.get("published_at"),
            "url": row.get("html_url"),
            "source": "canvas",
        } for row in rows if row.get("id") is not None]

    def get_notices(self, _user_id: str | None = None) -> list[dict]:
        """Return all enrolled-course announcements in the shared Provider shape."""
        result = []
        for course in self.get_courses():
            result.extend(self.get_course_notices(course["id"]))
        return result

    def get_lectures(self, _user_id: str | None = None) -> list[dict]:
        """Canvas modules do not prove watch completion; expose no guessed lectures."""
        return []

    def get_calendar_events(self, course_id: str | int | None = None) -> list[dict]:
        params = {}
        if course_id is not None:
            course = self._course(course_id)
            params["context_codes[]"] = f"course_{course['externalId']}"
        return self.client.get_all("/calendar_events", params)

    def snapshot(self, user_id: str | None = None) -> dict[str, list[dict]]:
        courses = self.get_courses(user_id)
        assignments = self.get_assignments(user_id)
        resources = []
        notices = []
        modules = []
        for course in courses:
            resources.extend(self.get_course_resources(course["id"]))
            notices.extend(self.get_course_notices(course["id"]))
            modules.extend(self.get_modules(course["id"]))
        return {
            "courses": courses,
            "assignments": assignments,
            "resources": resources,
            "notices": notices,
            "modules": modules,
        }

    def download_file(self, remote_url: str, target: str | os.PathLike[str]) -> str:
        """Download one already-listed same-origin file; never bulk downloads."""
        if not self.client._same_origin(remote_url):
            raise ValueError("Canvas 파일 주소가 학교 주소와 달라요.")
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        partial = target_path.with_name(target_path.name + ".part")
        try:
            with self.client._request(remote_url) as response, partial.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            os.replace(partial, target_path)
        finally:
            partial.unlink(missing_ok=True)
        return str(target_path)
