#!/usr/bin/env python3
"""Optional local menu-bar/notification-area companion.

The companion reads only non-secret profile markers and local database counts.
Passwords, cookies and session values stay behind the existing credential APIs.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
import secrets
import uuid
from contextlib import closing
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

_SCRIPT_PATH = Path(__file__).resolve()
ROOT = next(
    (candidate for candidate in (_SCRIPT_PATH.parent, _SCRIPT_PATH.parents[1])
     if (candidate / "assets" / "turtleneck.png").is_file()),
    _SCRIPT_PATH.parents[1],
)
if getattr(sys, 'frozen', False):
    bundled_skill = Path(getattr(sys, '_MEIPASS', ROOT)) / 'skills' / 'university-agent'
    if (bundled_skill / 'SKILL.md').is_file():
        ROOT = bundled_skill
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STATE_PATH = Path.home() / ".university-agent" / "companion.json"
RUNTIME_PATH = Path.home() / ".university-agent" / "companion-runtime.json"
ICON_PATH = ROOT / "assets" / "turtleneck.png"
POLL_SECONDS = 60
EXAM_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def list_profiles():
    """Load non-secret profile markers only when a screen actually needs them."""
    from providers.credentials import list_profiles as load_profiles
    return load_profiles()


def skill_status(skill_root: Path = ROOT) -> dict[str, str | bool]:
    """Check the installed skill without opening credentials or databases."""
    root = Path(skill_root).expanduser().resolve()
    ready = (root / "SKILL.md").is_file()
    return {"installed": ready, "path": str(root) if ready else ""}


def _db_summary(path: Path) -> dict[str, int | str | None]:
    result: dict[str, int | str | None] = {
        "databaseBytes": 0, "courses": 0, "resources": 0, "localFiles": 0,
        "localBytes": 0, "lastSyncedAt": None,
    }
    try:
        result["databaseBytes"] = path.stat().st_size
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            user = db.execute("SELECT id FROM users ORDER BY updated_at DESC LIMIT 1").fetchone()
            if not user:
                return result
            user_id = user[0]
            result["courses"] = db.execute(
                "SELECT COUNT(*) FROM courses c JOIN enrollments e ON e.course_id=c.id WHERE e.user_id=?",
                (user_id,),
            ).fetchone()[0]
            rows = db.execute(
                "SELECT r.local_path FROM resources r JOIN enrollments e ON e.course_id=r.course_id WHERE e.user_id=?",
                (user_id,),
            ).fetchall()
            result["resources"] = len(rows)
            for (local_path,) in rows:
                if not local_path:
                    continue
                try:
                    size = Path(local_path).stat().st_size
                except OSError:
                    continue
                result["localFiles"] += 1
                result["localBytes"] += size
            try:
                row = db.execute(
                    "SELECT state_value FROM sync_state WHERE user_id=? AND state_key IN ('gateway_checked_at','academic_checked_at') "
                    "ORDER BY CASE state_key WHEN 'gateway_checked_at' THEN 0 ELSE 1 END LIMIT 1",
                    (user_id,),
                ).fetchone()
                result["lastSyncedAt"] = row[0] if row else None
            except sqlite3.OperationalError:
                pass
    except (OSError, sqlite3.Error):
        return result
    return result


def snapshot() -> dict:
    """Return a safe, UI-ready snapshot; never include secret values."""
    skill = skill_status()
    if not skill['installed']:
        return {'skill': skill, 'profiles': [], 'checkedAt': time.time()}
    profiles = []
    for profile in list_profiles():
        item = {key: profile.get(key) for key in ("site", "alias", "username", "active")}
        db_path = Path(str(profile.get("dbPath", ""))).expanduser()
        item.update(_db_summary(db_path) if db_path.is_file() else {
            "databaseBytes": 0, "courses": 0, "resources": 0, "localFiles": 0,
            "localBytes": 0, "lastSyncedAt": None,
        })
        profiles.append(item)
    return {"skill": skill, "profiles": profiles, "checkedAt": time.time()}


def _study_exams(profile: dict) -> list[dict[str, object]]:
    """Read saved exam markers without opening the writable study engine."""
    db_path = Path(str(profile.get("dbPath", ""))).expanduser()
    path = db_path.parent / "study-sessions.db"
    if not path.is_file():
        return []
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            rows = db.execute(
                "SELECT exam_id, created_at, title, question_count, phase, score "
                "FROM study_exams WHERE user=? ORDER BY created_at DESC, exam_id LIMIT 50",
                (str(profile.get("username", "")),),
            ).fetchall()
    except (OSError, sqlite3.Error):
        return []
    return [
        {
            "examId": row[0], "createdAt": row[1], "title": row[2] or "저장된 시험지",
            "questionCount": row[3], "status": row[4], "score": row[5],
            "site": profile.get("site"), "alias": profile.get("alias"),
        }
        for row in rows
        if isinstance(row[0], str) and EXAM_ID_PATTERN.fullmatch(row[0])
    ]


def dashboard_snapshot() -> dict:
    """Return the local dashboard payload; never include questions or credentials."""
    from features import study_sources

    data = snapshot()
    exams = []
    documents = []
    internal_profiles = {(item['site'], item['alias']): item for item in list_profiles()} if data['skill']['installed'] else {}
    for profile in data["profiles"]:
        internal = internal_profiles.get((profile['site'], profile['alias']), profile)
        exams.extend(_study_exams(internal))
        try:
            documents.extend({**item, 'site': profile['site'], 'alias': profile['alias']}
                for item in study_sources.list_documents(Path(str(internal.get('dbPath', ''))).parent,
                    str(internal.get('username', ''))))
        except (OSError, ValueError, KeyError):
            data['sourceLibraryError'] = '일부 저장 자료를 읽지 못했어요. 자료 저장 상태를 확인해 주세요.'
    exams.sort(key=lambda item: (str(item.get("createdAt") or ""), str(item.get("examId"))), reverse=True)
    finished = [item for item in exams if item.get("status") == "finished" and isinstance(item.get("score"), (int, float))]
    scores = [float(item["score"]) for item in finished]
    data["exams"] = exams[:50]
    data['documents'] = sorted(documents, key=lambda item: item['savedAt'], reverse=True)[:50]
    data["scoreSummary"] = {
        "finished": len(finished),
        "average": round(sum(scores) / len(scores), 2) if scores else None,
        "best": max(scores) if scores else None,
        "latest": scores[0] if scores else None,
    }
    return data


def _main_bundle() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    names = ("turtleneck.exe", "turtleneck") if sys.platform == "win32" else ("turtleneck",)
    candidates: list[Path] = []
    for directory in (executable.parent, *executable.parents):
        for name in names:
            candidates.extend((directory / name, directory / "turtleneck" / name))
        if directory.parent != directory:
            for name in names:
                candidates.append(directory.parent / "turtleneck" / name)
    installed = shutil.which("turtleneck")
    if installed:
        candidates.append(Path(installed))
    return next((candidate for candidate in dict.fromkeys(candidates) if candidate.is_file()), None)


def _exam_command() -> list[str]:
    if getattr(sys, "frozen", False):
        main_bundle = _main_bundle()
        if main_bundle:
            return [str(main_bundle), "skills/university-agent/scripts/exam_web.py"]
        return [sys.executable, "skills/university-agent/scripts/exam_web.py"]
    return [sys.executable, str(ROOT / "scripts" / "exam_web.py")]


def _setup_command() -> list[str]:
    """Use the main bundle for setup when this process is the frozen companion."""
    if getattr(sys, "frozen", False):
        main_bundle = _main_bundle()
        if main_bundle:
            return [str(main_bundle), "skills/university-agent/scripts/setup_turtleneck.py"]
        return [sys.executable, "skills/university-agent/scripts/setup_turtleneck.py"]
    return [sys.executable, str(ROOT / "scripts" / "setup_turtleneck.py")]


def _watch_command() -> list[str]:
    """Use the main bundle for the same bounded TLS watcher as scheduled runs."""
    if getattr(sys, "frozen", False):
        main_bundle = _main_bundle()
        if main_bundle:
            return [str(main_bundle), "skills/university-agent/scripts/academic_watch.py", "--once"]
        return [sys.executable, "skills/university-agent/scripts/academic_watch.py", "--once"]
    return [sys.executable, str(ROOT / "scripts" / "academic_watch.py"), "--once"]


def _open_exam(site: str, alias: str, exam_id: str) -> None:
    if not EXAM_ID_PATTERN.fullmatch(exam_id):
        raise ValueError("시험지 ID를 확인하지 못했어요.")
    profiles = [item for item in list_profiles() if item.get("site") == site and item.get("alias") == alias]
    if len(profiles) != 1:
        raise ValueError("해당 로컬 프로필을 찾지 못했어요.")
    profile = profiles[0]
    db_path = Path(str(profile["dbPath"])).expanduser().resolve()
    command = _exam_command() + [
        "--conversation", f"companion-{uuid.uuid4().hex}", "--exam-id", exam_id,
    ]
    env = os.environ.copy()
    env.update({"UNIVERSITY_AGENT_DB": str(db_path), "UNIVERSITY_AGENT_USER_ID": str(profile["username"])})
    subprocess.Popen(command, cwd=str(ROOT.parent), env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class DashboardServer:
    """Loopback-only dashboard bridge for the tray app."""

    def __init__(self, presenter=None):
        self.token = secrets.token_urlsafe(24)
        self.server = None
        self.thread = None
        self.presenter = presenter

    def start(self) -> str:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def _send(self, status, body, content_type="text/html; charset=utf-8"):
                payload = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                if query.get("token", [""])[0] != owner.token:
                    self._send(403, "터틀넥 보조 앱에서 연 대시보드만 사용할 수 있어요.")
                    return
                if parsed.path == "/":
                    try:
                        body = (ROOT / "assets" / "companion.html").read_text(encoding="utf-8")
                    except OSError:
                        self._send(500, "대시보드 파일을 읽지 못했어요.")
                        return
                    self._send(200, body)
                elif parsed.path == "/api/dashboard":
                    self._send(200, json.dumps(dashboard_snapshot(), ensure_ascii=False), "application/json; charset=utf-8")
                elif parsed.path == '/api/source':
                    try:
                        from providers.credentials import list_profiles
                        from features import study_sources

                        if not skill_status()['installed']:
                            raise ValueError('스킬 설치를 먼저 확인해 주세요.')
                        profiles = [item for item in list_profiles()
                            if item['site'] == query.get('site', [''])[0] and item['alias'] == query.get('alias', [''])[0]]
                        if len(profiles) != 1:
                            raise ValueError('자료의 프로필을 확인해 주세요.')
                        profile = profiles[0]
                        page = study_sources.read_document(Path(str(profile['dbPath'])).parent, profile['username'],
                            query.get('id', [''])[0], section=int(query.get('section', ['0'])[0]),
                            text_offset=int(query.get('textOffset', ['0'])[0]))
                    except (OSError, ValueError, KeyError) as error:
                        self._send(400, json.dumps({'error': str(error)}, ensure_ascii=False), 'application/json; charset=utf-8')
                        return
                    self._send(200, json.dumps(page, ensure_ascii=False), 'application/json; charset=utf-8')
                elif parsed.path == "/open-exam":
                    try:
                        _open_exam(query.get("site", [""])[0], query.get("alias", [""])[0], query.get("examId", [""])[0])
                    except (OSError, ValueError, subprocess.SubprocessError) as error:
                        self._send(400, str(error))
                        return
                    self.send_response(303)
                    self.send_header("Location", "/?" + urlencode({"token": owner.token}))
                    self.end_headers()
                else:
                    self._send(404, "찾을 수 없는 대시보드 경로예요.")

            def do_POST(self):
                expected_host = f'127.0.0.1:{self.server.server_port}'
                if (self.path != '/present' or self.headers.get('Host') != expected_host
                        or not secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + owner.token)):
                    self._send(403, '{}', 'application/json')
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 8192 or owner.presenter is None:
                        raise ValueError('화면 요청을 확인하지 못했어요.')
                    value = json.loads(self.rfile.read(length))
                    from features.presentation import validate_page
                    url = validate_page(value['url'], value['kind'])
                    owner.presenter(url, value['kind'])
                except (ValueError, TypeError, KeyError, RuntimeError):
                    self._send(400, '{}', 'application/json')
                    return
                self._send(200, '{"accepted":true}', 'application/json')

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        if self.presenter is not None:
            from storage.private_files import atomic_write_text
            atomic_write_text(RUNTIME_PATH, json.dumps({'port': self.server.server_port, 'token': self.token}))
        return f"http://127.0.0.1:{self.server.server_port}/?{urlencode({'token': self.token})}"

    def open(self) -> str:
        from features.presentation import open_local_page

        if self.server is None:
            url = self.start()
        else:
            url = f"http://127.0.0.1:{self.server.server_port}/?{urlencode({'token': self.token})}"
        open_local_page(url, kind='dashboard')
        return url

    def stop(self) -> None:
        if self.server is not None:
            if self.presenter is not None:
                try:
                    marker = json.loads(RUNTIME_PATH.read_text(encoding='utf-8'))
                    if marker.get('token') == self.token:
                        RUNTIME_PATH.unlink(missing_ok=True)
                except (OSError, ValueError, AttributeError):
                    pass
            self.server.shutdown()
            self.server.server_close()
            self.server = None


def companion_status() -> dict[str, str]:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if data.get("status") in {"DECLINED", "INSTALLED"}:
            return {"status": data["status"]}
    except (OSError, ValueError, TypeError):
        pass
    return {"status": "OFFER"}


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            return f"{amount:.0f}{unit}" if unit == "B" else f"{amount:.1f}{unit}"
        amount /= 1024
    return "0B"


def _build_tray_icon(image_module, draw_module):
    """Draw a crisp monochrome mark instead of shrinking the full-color mascot."""
    image = image_module.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = draw_module.Draw(image)
    ink = (17, 24, 39, 255)
    width = 4
    draw.ellipse((10, 8, 54, 52), outline=ink, width=width)
    draw.ellipse((20, 20, 34, 34), outline=ink, width=width)
    draw.ellipse((32, 20, 46, 34), outline=ink, width=width)
    draw.line((34, 27, 32, 27), fill=ink, width=width)
    draw.arc((24, 31, 47, 46), 10, 165, fill=ink, width=width)
    draw.arc((8, 42, 56, 72), 200, 340, fill=ink, width=width)
    return image


def _open_setup() -> None:
    # Let setup_turtleneck decide whether a login form is needed; --status alone
    # can never reach the form from the companion menu.
    command = _setup_command() + ["--only", "tls"]
    options = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        options["start_new_session"] = True
    subprocess.Popen(command, **options)


def run_tray() -> int:
    """Start the native tray icon when the optional desktop dependencies exist."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        print("보조 앱 구성요소가 없어요. 데스크톱 번들을 설치하거나 pystray와 Pillow를 준비해 주세요.")
        return 2

    image = _build_tray_icon(Image, ImageDraw)
    image.thumbnail((32, 32), Image.Resampling.LANCZOS)
    state = {"snapshot": snapshot()}
    try:
        import webview
    except ImportError:
        webview = None
    windows = {}

    def present(url, kind):
        window = windows.get(kind)
        if window is None:
            window = webview.create_window({'login': '터틀넥 연결', 'exam': '터틀넥 시험',
                'dashboard': '터틀넥 학습 자료'}[kind], url, width=1100, height=780)
            windows[kind] = window
            window.events.closed += lambda: windows.pop(kind, None)
        else:
            window.load_url(url)
            window.show()

    dashboard = DashboardServer(presenter=present if webview else None)
    stop = threading.Event()

    def refresh(icon=None, _item=None):
        state["snapshot"] = snapshot()
        if icon is not None:
            icon.update_menu()

    def run_watch(_icon, _item):
        options = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            options["start_new_session"] = True
        try:
            subprocess.Popen(_watch_command(), cwd=str(ROOT.parent), **options)
        except OSError:
            return
        refresh(_icon)

    def poll(icon):
        while not stop.wait(POLL_SECONDS):
            refresh(icon)

    def label(_item):
        current = state["snapshot"]
        return "터틀넥 · 스킬 확인됨" if current["skill"]["installed"] else "터틀넥 · 스킬 없음"

    def profile_items(_item):
        items = []
        for profile in state["snapshot"]["profiles"]:
            title = f"{profile['site']} / {profile['alias']} · {profile['username']}"
            detail = f"자료 {profile['localFiles']}개 · {_format_bytes(int(profile['localBytes']))}"
            items.append(pystray.MenuItem(f"{title} ({detail})", None, enabled=False))
        return items or [pystray.MenuItem("아직 연결된 프로필이 없어요", None, enabled=False)]

    def open_repository(_icon, _item):
        webbrowser.open("https://github.com/K-Lunatic/Turtleneck")

    def open_dashboard(_icon, _item):
        dashboard.open()

    def quit_app(icon, _item):
        stop.set()
        dashboard.stop()
        icon.stop()
        if webview:
            for window in list(webview.windows):
                window.destroy()

    menu = pystray.Menu(
        pystray.MenuItem(label, None, enabled=False),
        pystray.MenuItem("프로필 보기", profile_items),
        pystray.MenuItem("시험·점수 대시보드", open_dashboard),
        pystray.MenuItem("새로 확인", run_watch),
        pystray.MenuItem("학교 로그인·연결", lambda _icon, _item: _open_setup()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("터틀넥 안내", open_repository),
        pystray.MenuItem("종료", quit_app),
    )
    icon = pystray.Icon("turtleneck", image, "터틀넥", menu)
    threading.Thread(target=poll, args=(icon,), daemon=True).start()
    if webview:
        webview.create_window('터틀넥', html='<html></html>', hidden=True)
        icon.run_detached()
        try:
            webview.start(dashboard.start)
        finally:
            stop.set()
            dashboard.stop()
            icon.stop()
    else:
        icon.run()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="터틀넥 로컬 메뉴 바·알림 영역 보조 앱")
    parser.add_argument("--status", action="store_true", help="비밀값 없는 상태 JSON 출력")
    parser.add_argument("--dashboard", action="store_true", help="로컬 시험·점수 대시보드만 실행")
    args = parser.parse_args(argv)
    if args.status:
        print(json.dumps(snapshot(), ensure_ascii=False))
        return 0
    if args.dashboard:
        dashboard = DashboardServer()
        url = dashboard.start()
        print(url, flush=True)
        webbrowser.open(url)
        try:
            dashboard.thread.join()
        except KeyboardInterrupt:
            dashboard.stop()
        return 0
    return run_tray()


if __name__ == "__main__":
    raise SystemExit(main())
