#!/usr/bin/env python3
"""Login to KKU TLS, fetch normalized records, and replace local DB data."""
from __future__ import annotations

import os
import argparse
import re
import sys
import json
import subprocess
import hashlib
import shutil
import tempfile
from contextlib import closing
from datetime import datetime, timezone
import errno
from pathlib import Path
from urllib.error import URLError
from socket import timeout as SocketTimeout
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.moodle_provider import MoodleTLSProvider
from providers.moodle_session import LoginError, MoodleSession, RequestBackoff
from providers.credentials import (CredentialInputRequired, load, load_active_alias, load_username,
                                   link_account, normalize_alias, profile_db_path, resolve, save, save_session,
                                   set_active_alias, site_key)
from storage.local_db import LocalDatabase
from features.guidance import resource_unavailable_reason
from features.autonomous_course_watch import refresh as refresh_autonomous_course
from providers.tls_auth import resume_saved_session
from providers.native_backend import activate as activate_native_backend
from providers.request_metrics import RequestMetrics, measure_requests
from features import sync_policy


def _cached_resources(db_path: Path, user_id: str, file_root: Path) -> dict[str, dict[str, object]]:
    """Reuse checked originals, retaining HTTP validators when TLS supplies them."""
    if not db_path.exists():
        return {}
    database = None
    try:
        database = LocalDatabase(db_path, read_only=True)
        root = file_root.resolve()
        cached = {}
        counts = {}
        records = database.get_resources(user_id, include_permissions=False)
        for item in records:
            value = item.get('localPath')
            if value:
                counts[str(Path(value).resolve())] = counts.get(str(Path(value).resolve()), 0) + 1
        for item in records:
            if item.get('downloadStatus') == 'PROHIBITED':
                continue
            path_value = item.get("localPath")
            if not path_value:
                continue
            path = Path(path_value).expanduser()
            try:
                inside_root = path.resolve().is_relative_to(root)
            except (OSError, ValueError):
                inside_root = False
            cached_mime = str(item.get("mimeType") or "").lower()
            cached_extension = str(item.get("extension") or "").lower()
            looks_like_html = False
            if inside_root and path.is_file() and ("html" in cached_mime or cached_extension in {"html", "htm", "php", "unknown"}):
                try:
                    with path.open('rb') as source:
                        sample = source.read(4096).lstrip().lower()
                    looks_like_html = b"<html" in sample or b"<!doctype" in sample or b"<a " in sample or b"<script" in sample or b"<body" in sample
                except OSError:
                    looks_like_html = True
            if inside_root and path.is_file() and not looks_like_html and counts[str(path.resolve())] == 1:
                try:
                    validators = json.loads(path.with_name(path.name + '.http.json').read_text(encoding='utf-8'))
                    item.update({k: v for k, v in validators.items() if k in ('etag', 'lastModified') and isinstance(v, str)})
                except (OSError, ValueError, AttributeError):
                    pass
                cached[str(item.get("externalId", ""))] = item
        return cached
    except (OSError, RuntimeError):
        return {}
    finally:
        if database is not None:
            database.close()


def store_resource(file_root, item):
    """Keep original names, isolate activities and versions, publish only complete files."""
    content = item.pop('_content', None)
    content_path = item.pop('_content_path', None)
    if content is None and not content_path:
        raise ValueError('자료 원본이 없어 저장하지 않았어요.')
    course, resource = item['courseId'], item['id']
    if not all(re.fullmatch(r'[A-Za-z0-9_-]+', value) for value in (course, resource)):
        raise ValueError('자료 저장 식별자가 올바르지 않습니다.')
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', re.split(r'[\\/]', item['fileName'])[-1]).rstrip(' .')
    if not name or name in ('.', '..'):
        name = 'resource.' + item['extension']
    if re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name, re.I):
        name = '_' + name
    root = file_root.resolve()
    if content_path:
        digest = hashlib.sha256()
        with open(content_path, 'rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        content_hash = digest.hexdigest()
    else:
        content_hash = hashlib.sha256(content).hexdigest()
    target = root / course / resource / content_hash / name
    if not target.resolve().is_relative_to(root):
        raise ValueError('자료 저장 위치가 허용된 폴더 밖입니다.')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not target.resolve().is_relative_to(root):
        raise ValueError('자료 저장 위치가 허용된 폴더 밖입니다.')
    temporary = None
    moved = False
    try:
        if content_path:
            # The stream was already fsynced by the downloader; avoid a second
            # full read/write when the temporary file is on this filesystem.
            try:
                os.replace(content_path, target)
                moved = True
            except OSError as error:
                if error.errno != errno.EXDEV:
                    raise
        if not moved:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
                if content_path:
                    with open(content_path, 'rb') as source:
                        shutil.copyfileobj(source, stream, length=1024 * 1024)
                else:
                    stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    validators = item.pop('_validators', {})
    if content_path:
        Path(content_path).unlink(missing_ok=True)
    target.with_name(target.name + '.http.json').write_text(json.dumps(validators), encoding='utf-8')
    item.update(localPath=str(target), downloadedAt=datetime.now(timezone.utc).isoformat(), downloadStatus='DOWNLOADED')
    return item


def persist(db_path, user_id, username, courses, *, assignments=None, lectures=None, notices=None, resources=None, activities=None, refreshed_course_ids=None):
    with closing(LocalDatabase(db_path)) as database:
        if refreshed_course_ids is not None:
            retained = {course['id'] for course in courses} - refreshed_course_ids

            def merge(items, previous):
                if items is None:
                    return None
                return [item for item in previous if item.get('courseId') in retained] + items

            assignments = merge(assignments, [x for x in database.get_assignments(user_id) if x.get('source') != 'manual'])
            lectures = merge(lectures, database.get_lectures(user_id))
            notices = merge(notices, database.get_notices(user_id))
            resources = merge(resources, database.get_resources(user_id, include_permissions=False))
            activities = merge(activities, database.get_activities(user_id))
        database.upsert_tls_snapshot(user_id, courses,
            assignments if assignments is not None else [x for x in database.get_assignments(user_id) if x.get('source') != 'manual'],
            lectures if lectures is not None else database.get_lectures(user_id), username, None,
            notices=notices, resources=resources, activities=activities)


def _saved_sync_state(db_path: Path, user_id: str) -> dict[str, str]:
    if not db_path.exists():
        return {}
    try:
        with closing(LocalDatabase(db_path, read_only=True)) as database:
            return database.get_sync_state(user_id)
    except (OSError, RuntimeError):
        return {}


def _resource_needs_data(db_path: Path, user_id: str, resource_ids: list[str]) -> bool:
    if not resource_ids:
        return False
    if not db_path.exists():
        return True
    try:
        with closing(LocalDatabase(db_path, read_only=True)) as database:
            resources = {item['id']: item for item in database.get_resources(user_id, include_permissions=True)}
    except (OSError, RuntimeError):
        return True
    for resource_id in resource_ids:
        item = resources.get(resource_id)
        if item is None:
            return True
        if item.get('downloadStatus') == 'PROHIBITED':
            return True
        if item.get('downloadStatus') != 'DOWNLOADED' or not item.get('localPath') or not Path(item['localPath']).is_file():
            return True
    return False


def _changed_course_ids(state: dict[str, str], result: dict) -> set[str] | None:
    """None requires a full refresh; an empty set can still mean unenrollment."""
    if state.get('resource_response_version') != MoodleTLSProvider.RESOURCE_RESPONSE_VERSION:
        return None
    try:
        saved_courses = json.loads(state['course_ids'])
        saved_fingerprints = json.loads(state['course_fingerprints'])
        if (not isinstance(saved_courses, list) or not all(isinstance(value, str) for value in saved_courses)
                or not isinstance(saved_fingerprints, dict)):
            return None
        return {course_id for course_id in result['courseIds']
                if course_id not in saved_courses or not result['fingerprints'].get(course_id)
                or saved_fingerprints.get(course_id) != result['fingerprints'][course_id]}
    except (KeyError, TypeError, ValueError):
        return None


def _preflight_changed(state: dict[str, str], result: dict, *, needs_data: bool) -> bool:
    changed = _changed_course_ids(state, result)
    if needs_data or changed is None or changed:
        return True
    return set(json.loads(state['course_ids'])) != set(result['courseIds'])


def _requested_course_ids(db_path, user_id, resource_ids):
    with closing(LocalDatabase(db_path, read_only=True)) as database:
        resources = {item['id']: item for item in database.get_resources(user_id, include_permissions=False)}
    if any(identifier not in resources for identifier in resource_ids):
        return None
    return {resources[identifier]['courseId'] for identifier in resource_ids}


def _save_sync_state(db_path: Path, user_id: str, provider: MoodleTLSProvider) -> None:
    state = {
        'course_ids': json.dumps(sorted(course['id'] for course in provider.get_courses(user_id)), ensure_ascii=False),
        'course_fingerprints': json.dumps(provider.activity_fingerprints(user_id), ensure_ascii=False, sort_keys=True),
        'resource_response_version': MoodleTLSProvider.RESOURCE_RESPONSE_VERSION,
    }
    with closing(LocalDatabase(db_path)) as database:
        database.merge_sync_state(user_id, state)


def _progress(step: int, total: int, message: str) -> None:
    print(f"[{step}/{total}] {message}", flush=True)


def open_connection_terminal(command: list[str] | None = None) -> None:
    """Start the private local flow without opening a terminal window."""
    command = command or [sys.executable, str(Path(__file__).resolve()), '--reconnect']
    options = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    if os.name == 'nt':
        options['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    else:
        options['start_new_session'] = True
    subprocess.Popen(command, **options)
    print('학교 연결 절차를 시작했어요. 브라우저에 입력 화면이 실제로 보이는지 확인해 주세요.', flush=True)


def _login_with_retries_unlocked(base_url: str, requested_username: str | None = None, *, stored_only=False,
                                 profile_alias: str | None = None, force_input=False,
                                 _session_checked=False) -> tuple[str, MoodleSession]:
    """Login without ever returning the password to the caller."""
    site = site_key(base_url)
    profile_alias = profile_alias or os.environ.get('TLS_ACCOUNT_ALIAS') or load_active_alias(site)
    if not _session_checked:
        resumed = resume_saved_session(base_url, requested_username, profile_alias)
        if resumed:
            print("저장된 학교 연결을 재사용했어요.", flush=True)
            try:
                resumed[1].profile_alias = profile_alias
            except AttributeError:
                pass
            return resumed
    if not force_input and not os.environ.get('UNIVERSITY_AGENT_DB'):
        try:
            stored_username, stored_password = load(profile_alias, site)
        except (OSError, KeyError, ValueError, subprocess.SubprocessError):
            try:
                load_username(profile_alias, site)
            except (OSError, KeyError, ValueError, subprocess.SubprocessError):
                pass
            else:
                raise RuntimeError('저장된 학교 계정의 비밀번호를 읽지 못했어요. 연결 명령으로 한 번만 다시 입력해 주세요.')
        else:
            if stored_username and not stored_password:
                raise RuntimeError('저장된 학교 계정의 비밀번호가 비어 있어요. 연결 명령으로 한 번만 다시 입력해 주세요.')
    total_attempts = 1 if stored_only else 3
    for attempt in range(1, total_attempts + 1):
        verified = {}

        def verify_form(values):
            """Validate credentials before the browser can show completion."""
            selected_alias = normalize_alias(values.get('alias') or profile_alias)
            candidate_username = values.get('username', '')
            candidate_password = values.get('password', '')
            if not candidate_username or not candidate_password:
                return '아이디와 비밀번호를 모두 입력해 주세요.'
            candidate_session = MoodleSession(base_url)
            try:
                candidate_session.login(candidate_username, candidate_password)
                save(candidate_username, candidate_password, selected_alias, site)
                save_session(candidate_username, candidate_session.cookies, selected_alias, site)
            except LoginError:
                return '학교 로그인에 실패했어요. 아이디와 비밀번호를 다시 확인해 주세요.'
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                return '로그인은 확인했지만 보호 저장소에 안전하게 등록하지 못했어요. 다시 시도해 주세요.'
            candidate_session.profile_alias = selected_alias
            verified['result'] = (candidate_username, candidate_session, selected_alias)
            return None

        if stored_only:
            try:
                username, password = load(profile_alias, site)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                raise RuntimeError('저장된 학교 연결 정보가 없어요. 학교 연결을 다시 마쳐 주세요.') from error
            if requested_username and username != requested_username:
                raise RuntimeError('저장된 학교 계정이 달라요. 학교 연결을 다시 확인해 주세요.')
            if not username or not password:
                raise RuntimeError('저장된 학교 계정의 비밀번호가 비어 있어요. 연결 명령으로 한 번만 다시 입력해 주세요.')
        else:
            input_mode = force_input or attempt > 1
            # The first form must also verify the login before showing success.
            # Otherwise a wrong password can look like a completed registration.
            resolve_options = {'force_input': input_mode, 'site': site, 'submit_check': verify_form}
            username, password = resolve(requested_username, **resolve_options)
            if verified.get('result'):
                username, session, profile_alias = verified['result']
                print("학교 로그인과 보호 저장소 등록을 확인했어요.", flush=True)
                return username, session
            profile_alias = load_active_alias(site)
        print(f"학교 로그인을 확인 중이에요… ({attempt}/{total_attempts})", flush=True)
        session = MoodleSession(base_url)
        try:
            session.login(username, password)
        except LoginError:
            password = None
            if stored_only:
                raise RuntimeError(
                    '저장된 학교 연결이 더 이상 유효하지 않아요. 터틀넥 연결 화면을 다시 열어 로그인해 주세요. '
                    '비밀번호는 채팅이나 터미널에 입력하지 마세요.'
                ) from None
            if attempt == 3:
                raise
            requested_username = username
            print("로그인이 되지 않았어요. 아이디나 비밀번호를 다시 확인할게요.", flush=True)
            continue
        try:
            if not stored_only:
                save(username, password, profile_alias, site)
        finally:
            password = None
        if hasattr(session, "cookies"):
            try:
                save_session(username, session.cookies, profile_alias, site)
            except (OSError, RuntimeError, ValueError):
                # A successful login must remain usable, but do not hide why the
                # next run may need another login when the OS store is unavailable.
                print("학교 연결은 성공했지만 이 컴퓨터의 보호 저장소에 세션을 보관하지 못했어요. 다음 실행에서 다시 로그인할 수 있어요.", flush=True)
        session.profile_alias = profile_alias
        return username, session
    raise AssertionError("unreachable")


def _login_with_retries(base_url: str, requested_username: str | None = None, *, stored_only=False,
                        profile_alias: str | None = None, force_input=False) -> tuple[str, MoodleSession]:
    """Serialize cross-process login and re-check the session after waiting."""
    site = site_key(base_url)
    alias = profile_alias or os.environ.get('TLS_ACCOUNT_ALIAS') or load_active_alias(site)
    db_path = profile_db_path(base_url, alias)
    with sync_policy.SyncLock(db_path.with_name(db_path.name + '.auth'), timeout=120):
        resumed = resume_saved_session(base_url, requested_username, alias)
        if resumed:
            print("저장된 학교 연결을 재사용했어요.", flush=True)
            try:
                resumed[1].profile_alias = alias
            except AttributeError:
                pass
            return resumed
        return _login_with_retries_unlocked(
            base_url, requested_username, stored_only=stored_only,
            profile_alias=alias, force_input=force_input, _session_checked=True,
        )


def main() -> None:
    metrics = RequestMetrics() if '--metrics' in sys.argv else None
    with measure_requests(metrics):
        try:
            _main()
        finally:
            if metrics is not None:
                print('TLS_METRICS ' + json.dumps(metrics.snapshot(), sort_keys=True), file=sys.stderr)


def _mark_checks(db_path, user_id, kind, refreshed, course_ids, scope):
    with closing(LocalDatabase(db_path)) as database:
        previous = sync_policy.checks(database.get_sync_state(user_id), kind)
        previous = {key: value for key, value in previous.items() if key in course_ids}
        checked = sync_policy.now().isoformat()
        previous.update(dict.fromkeys(refreshed, checked))
        update = {kind + '_course_checks': json.dumps(previous), 'sync_scope': scope}
        if set(course_ids) <= set(refreshed):
            update[kind + '_checked_at'] = checked
        database.merge_sync_state(user_id, update)


def _can_reuse(args, state, scope, db_path, user_id, requested_at):
    if getattr(args, 'resource_only', False):
        return False  # Explicit file preparation rechecks current enrollment and restrictions.
    if state.get('sync_scope') != scope:
        return False
    since = requested_at if args.force or args.full else None
    if args.academic_only:
        return sync_policy.fresh(state.get('academic_checked_at'), sync_policy.ACADEMIC_TTL, since=since)
    if state.get('resource_response_version') != MoodleTLSProvider.RESOURCE_RESPONSE_VERSION:
        return False
    if not sync_policy.fresh(state.get('catalog_checked_at'), sync_policy.CATALOG_TTL, since=since):
        return False
    if state.get('autonomous_course_watch_url') and not sync_policy.fresh(
            state.get('autonomous_course_checked_at'), sync_policy.AUTONOMOUS_TTL, since=since):
        return False
    try:
        course_ids = json.loads(state['course_ids'])
        if not isinstance(course_ids, list) or not all(isinstance(value, str) for value in course_ids):
            return False
    except (KeyError, TypeError, ValueError):
        return False
    if args.resource_id:
        if _resource_needs_data(db_path, user_id, args.resource_id):
            return False
        targets = _requested_course_ids(db_path, user_id, args.resource_id)
        try:
            item_checks = json.loads(state.get('resource_item_checks', '{}'))
        except (TypeError, ValueError):
            item_checks = {}
        if not isinstance(item_checks, dict):
            item_checks = {}
        return (targets is not None
                and not sync_policy.due_courses(state, 'notice', targets, sync_policy.CATALOG_TTL, since=requested_at)
                and (not sync_policy.due_courses(state, 'resource', targets, sync_policy.CATALOG_TTL, since=requested_at)
                     or all(sync_policy.fresh(item_checks.get(identifier), sync_policy.CATALOG_TTL,
                                              since=requested_at) for identifier in args.resource_id)))
    required = [('academic', sync_policy.ACADEMIC_TTL), ('notice', sync_policy.NOTICE_TTL),
                ('resource', sync_policy.RESOURCE_TTL)]
    if not args.metadata_only:
        required.append(('file', sync_policy.RESOURCE_TTL))
    return not any(sync_policy.due_courses(state, kind, course_ids, ttl, since=since) for kind, ttl in required)


def _main() -> None:
    parser = argparse.ArgumentParser(description="Sync KKU TLS data into the local SQLite database")
    parser.add_argument('--connect', action='store_true', help='Open a private native terminal for account connection')
    parser.add_argument('--reconnect', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--base-url', help='사용할 학교 LMS 주소 (예: https://lms.example.ac.kr)')
    parser.add_argument('--account-alias', help='사이트별 저장 계정 별칭')
    parser.add_argument('--reuse-site', help='명시적으로 인증정보를 재사용할 원본 LMS 주소')
    parser.add_argument('--reuse-account-alias', help='명시적으로 인증정보를 재사용할 원본 계정 별칭')
    parser.add_argument('--metadata-only', action='store_true', help='Refresh records without downloading new file contents')
    parser.add_argument('--academic-only', action='store_true', help='Check assignment/watch status; reuse a successful check for up to 15 minutes')
    parser.add_argument('--ensure', action='store_true', help='Check course changes and refresh only required scopes')
    parser.add_argument('--full', action='store_true', help='Force a complete refresh')
    parser.add_argument('--force', action='store_true', help='Bypass successful-check ages; still respect active syncs and server cooldowns')
    parser.add_argument('--resource-id', action='append', default=[], help='Prepare the requested original file after checking current permissions')
    parser.add_argument('--resource-only', action='store_true', help='Prepare selected files, discovering new IDs from enrolled course lists only')
    parser.add_argument('--course-id', action='append', default=[], help='새 자료를 찾을 현재 수강 과목 ID; --resource-only와 함께 사용')
    parser.add_argument('--metrics', action='store_true', help='Print private aggregate HTTP request counters to stderr')
    args = parser.parse_args()
    if args.resource_only and (not args.resource_id and not args.course_id or args.full or args.academic_only or args.connect):
        parser.error('--resource-only는 --resource-id 또는 --course-id와 함께 쓰며 전체/학사/연결 모드와 함께 쓸 수 없습니다.')
    if args.course_id and not args.resource_only:
        parser.error('--course-id는 --resource-only와 함께 사용해 주세요.')
    if args.academic_only and (args.ensure or args.full or args.resource_id or args.connect):
        parser.error('--academic-only는 다른 동기화 범위나 연결 모드와 함께 사용할 수 없습니다.')
    if args.ensure and args.full:
        parser.error('--ensure와 --full은 함께 사용할 수 없습니다.')
    if bool(args.reuse_site) != bool(args.reuse_account_alias):
        parser.error('--reuse-site와 --reuse-account-alias는 함께 지정해야 합니다.')
    base_url = args.base_url or os.environ.get('TLS_BASE_URL', 'https://tls.kku.ac.kr')
    target_site = site_key(base_url)
    explicit_profile_alias = args.account_alias or os.environ.get('TLS_ACCOUNT_ALIAS')
    profile_alias = explicit_profile_alias or load_active_alias(target_site)
    if args.reuse_site:
        link_account(target_site, profile_alias, args.reuse_site, args.reuse_account_alias)
    if args.connect:
        if args.account_alias:
            set_active_alias(args.account_alias, site_key(base_url), allow_missing=True)
        try:
            open_connection_terminal([sys.executable, str(Path(__file__).resolve()), '--reconnect', '--base-url', base_url,
                                     *(['--account-alias', args.account_alias] if args.account_alias else [])])
        except (OSError, subprocess.SubprocessError) as error:
            raise SystemExit('연결창을 자동으로 열지 못했어요. 직접 터미널에서 sync_tls.py를 실행해 주세요.') from error
        return
    db_path = profile_db_path(base_url, explicit_profile_alias or ("default" if os.environ.get("UNIVERSITY_AGENT_DB") else profile_alias))
    requested_at = sync_policy.now()
    try:
        local_username = os.environ.get('TLS_USERNAME') or load_username(profile_alias, site_key(base_url))
    except (OSError, KeyError, TypeError, ValueError):
        local_username = None
    scope = sync_policy.scope_key(base_url, local_username) if local_username else None
    try:
        with sync_policy.SyncLock(db_path, timeout=5 if args.resource_only else 120) as guard:
            try:
                previous_scope = scope
                previous_failure = bool(guard.state(scope).get('failed')) if scope else False
                if scope:
                    remaining = guard.remaining(scope)
                    if remaining:
                        raise RequestBackoff(remaining)
                    user_id = os.environ.get('UNIVERSITY_AGENT_USER_ID', local_username)
                    state = _saved_sync_state(db_path, user_id)
                    if not guard.state(scope).get('failed') and _can_reuse(args, state, scope, db_path, user_id, requested_at):
                        print('최근에 성공한 학교 확인 결과를 재사용했어요. 기존 확인 시각을 유지해요.')
                        return
                    guard.record(scope, failed=True)
                if explicit_profile_alias:
                    set_active_alias(profile_alias, site_key(base_url), allow_missing=True)
                username, session = _login_with_retries(base_url, os.environ.get('TLS_USERNAME'),
                                                       stored_only=args.academic_only,
                                                       profile_alias=profile_alias,
                                                       force_input=args.reconnect)
                selected_alias = getattr(session, 'profile_alias', profile_alias)
                if selected_alias != profile_alias:
                    # The browser form may choose a new alias during first login.
                    # Keep that first sync out of the previous profile's database.
                    profile_alias = selected_alias
                    db_path = profile_db_path(base_url, profile_alias)
                user_id = os.environ.get('UNIVERSITY_AGENT_USER_ID', username)
                scope = sync_policy.scope_key(base_url, username)
                if guard.remaining(scope):
                    raise RequestBackoff(guard.remaining(scope))
                retry_failed = previous_failure if scope == previous_scope else bool(guard.state(scope).get('failed'))
                guard.record(scope, failed=True)
                _perform_sync(args, db_path, user_id, username, session, scope,
                              retry_failed=retry_failed)
                guard.record(scope)
            except BaseException as error:
                if scope:
                    delay = error.seconds if isinstance(error, RequestBackoff) else 60 if isinstance(error, (URLError, TimeoutError)) else 0
                    guard.record(scope, failed=True, delay=max(delay, guard.remaining(scope)))
                raise
    except RequestBackoff as error:
        raise SystemExit(f'학교 요청을 잠시 쉬고 있어요. 약 {max(1, int(error.seconds + 0.999))}초 후 다시 확인해 주세요. 기존 기록의 확인 시각은 갱신하지 않았어요.') from error
    except LoginError as error:
        raise SystemExit('학교에 연결하지 못했어요. 아이디와 비밀번호를 확인해 주세요.') from error
    except (sync_policy.SyncBusy, CredentialInputRequired, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    except (URLError, TimeoutError, ConnectionError) as error:
        raise SystemExit('학교 확인이 끝나지 않았어요. 기존 기록은 보존했으며 잠시 후 다시 확인할 수 있어요.') from error
    except OSError as error:
        raise SystemExit('학교 정보 저장 폴더에 접근할 수 없어요. 저장 위치 권한을 확인한 뒤 다시 시도해 주세요.') from error


def _prepare_requested_resources(args, db_path, user_id, username, provider, scope, state):
    if state.get('sync_scope') != scope or not db_path.exists():
        raise RuntimeError('자료의 연결 범위를 먼저 전체 목록 갱신으로 확인해 주세요.')
    targets = set(args.resource_id)
    requested = (_requested_course_ids(db_path, user_id, args.resource_id)
                 if targets else set(args.course_id))
    courses = provider.get_courses(user_id)
    ids = {c['id'] for c in courses}
    # Reconcile enrollment even when a formerly accessible target is no longer available.
    persist(db_path, user_id, username, courses)
    if requested is None:
        print('새 자료의 위치를 강좌 목록에서 찾고 있어요. 과제·동영상 상태는 확인하지 않아요.', flush=True)
        requested = provider.locate_resource_courses(user_id, set(args.resource_id), set(getattr(args, 'course_id', [])))
    if not requested <= ids:
        raise RuntimeError('현재 수강 중인 과목의 알려진 자료만 준비할 수 있어요. 자료 목록을 갱신해 주세요.')
    reader = provider.for_courses(user_id, requested)
    with closing(LocalDatabase(db_path, read_only=True)) as database:
        previous_notices = database.get_notices(user_id)
        previous_resources = database.get_resources(user_id, include_permissions=False)
    notices = reader.get_notices(user_id, existing_notices=previous_notices, force_details=True)
    persist(db_path, user_id, username, courses, notices=notices, refreshed_course_ids=requested)
    file_root = db_path.parent / 'files'
    resources = reader.get_resources(user_id, notices=notices,
        existing_resources=_cached_resources(db_path, user_id, file_root), resource_ids=targets or None,
        detail_course_ids=requested if not targets else set(),
        download_new_files=not args.metadata_only, save_file=lambda item: store_resource(file_root, item),
        partial_root=file_root)
    if any(item.get('_checkFailed') for item in resources):
        raise URLError('요청한 자료의 현재 상태를 확인하지 못했어요.')
    seen = {item['id'] for item in resources}
    if targets:
        resources += [{**item, 'downloadStatus': 'PROHIBITED', 'downloadReason': '현재 과목 자료 목록에서 확인되지 않습니다.'}
                      for item in previous_resources if item['id'] in targets - seen]
    if targets:
        resources += [item for item in previous_resources
                      if item['id'] not in seen and item['id'] not in targets]
    else:
        resources += [item for item in previous_resources
                      if item['courseId'] not in requested and item['id'] not in seen]
    persist(db_path, user_id, username, courses, resources=resources, refreshed_course_ids=requested)
    try:
        checks = json.loads(state.get('resource_item_checks', '{}'))
    except (TypeError, ValueError):
        checks = {}
    if not isinstance(checks, dict):
        checks = {}
    checks.update(dict.fromkeys(seen if not targets else seen & targets, sync_policy.now().isoformat()))
    with closing(LocalDatabase(db_path)) as database:
        database.merge_sync_state(user_id, {'resource_item_checks': json.dumps(checks)})
    label = f'자료 {len(targets)}개' if targets else f'강좌 자료 전체 ({len(seen)}개)'
    print(f'요청한 자료 확인 완료 · 대상 {label} · 관련 과목 {len(requested)}개')


def _perform_sync(args, db_path, user_id, username, session, scope, *, retry_failed=False):
    with activate_native_backend():
        return _perform_sync_python(args, db_path, user_id, username, session, scope,
                                    retry_failed=retry_failed)


def _perform_sync_python(args, db_path, user_id, username, session, scope, *, retry_failed=False):
    started = monotonic()
    force = args.full or args.force or retry_failed
    provider = MoodleTLSProvider(session)
    provider.progress = lambda message: print(message, flush=True)
    state = _saved_sync_state(db_path, user_id)
    if state.get('sync_scope') != scope:
        force = True
    if getattr(args, 'resource_only', False):
        _prepare_requested_resources(args, db_path, user_id, username, provider, scope, state)
        return
    if args.academic_only:
        courses, assignments, lectures = provider.get_academic_snapshot(user_id)
        persist(db_path, user_id, username, courses, assignments=assignments, lectures=lectures)
        ids = {course['id'] for course in courses}
        _mark_checks(db_path, user_id, 'academic', ids, ids, scope)
        print(f'과제·시청 상태 확인 완료 · 과제 {len(assignments)}개 · 강의 {len(lectures)}개')
        return
    autonomous_message = ''
    autonomous_url = state.get('autonomous_course_watch_url')
    if autonomous_url and (force or not sync_policy.fresh(
            state.get('autonomous_course_checked_at'), sync_policy.AUTONOMOUS_TTL)):
        previous_snapshot = None
        try:
            previous_snapshot = json.loads(state.get('autonomous_course_snapshot', ''))
        except (TypeError, ValueError):
            pass
        watch = refresh_autonomous_course(provider, user_id, autonomous_url,
                                         {'fingerprint': state.get('autonomous_course_fingerprint'),
                                          'snapshot': previous_snapshot})
        with closing(LocalDatabase(db_path)) as database:
            update = {'autonomous_course_checked_at': sync_policy.now().isoformat(),
                      'autonomous_course_check_status': 'CHANGED' if watch.get('changed') else 'OK'}
            if watch['ok']:
                update.update(autonomous_course_fingerprint=watch['fingerprint'],
                              autonomous_course_snapshot=json.dumps(watch['snapshot'], ensure_ascii=False),
                              autonomous_course_check_error='')
                if watch.get('changed'):
                    update.update(autonomous_course_last_change_summary=json.dumps(
                        watch.get('changes', {}), ensure_ascii=False, sort_keys=True),
                        autonomous_course_last_changed_at=sync_policy.now().isoformat())
            else:
                update.update(autonomous_course_check_status='FAILED', autonomous_course_check_error=watch['reason'])
            database.merge_sync_state(user_id, update)
        if not watch['ok']:
            autonomous_message = f"자율강좌 확인을 건너뛰었어요 · {watch['reason']} · 다른 학사 확인은 계속했어요."
        elif watch.get('changed'):
            autonomous_message = (f"자율강좌 구조 변경을 확인했어요 · {watch.get('changeMessage', '변경 있음')} · "
                                  "원격 강좌는 수정하지 않았어요.")
        else:
            autonomous_message = '자율강좌 구조를 확인했어요 · 변경 없음 · 원격 강좌는 수정하지 않았어요.'
    preflight = provider.preflight(user_id)
    courses = provider.get_courses(user_id)
    ids = set(preflight['courseIds'])
    changed = None if force else _changed_course_ids(state, preflight)
    changed = ids if changed is None else changed
    academic = changed | sync_policy.due_courses(state, 'academic', ids, sync_policy.ACADEMIC_TTL)
    notices_scope = changed | sync_policy.due_courses(state, 'notice', ids, sync_policy.NOTICE_TTL)
    resources_scope = changed | sync_policy.due_courses(state, 'resource', ids, sync_policy.RESOURCE_TTL)
    detail_courses = resources_scope.copy()
    if args.resource_id:
        requested = _requested_course_ids(db_path, user_id, args.resource_id) if db_path.exists() else None
        if requested is None:
            detail_courses |= ids
        requested = ids if requested is None else requested & ids
        resources_scope |= requested
        notices_scope |= requested  # Recheck restrictions stated in notices before an explicit download.
    elif not args.metadata_only:
        resources_scope |= sync_policy.due_courses(state, 'file', ids, sync_policy.RESOURCE_TTL)
    if not args.metadata_only:
        notices_scope |= resources_scope
    # Reconcile enrollment without discarding data that a later failing read must preserve.
    persist(db_path, user_id, username, courses, assignments=[], lectures=[], refreshed_course_ids=set())
    if changed:
        activities = provider.for_courses(user_id, changed).get_activity_catalog(user_id)
    if academic:
        reader = provider.for_courses(user_id, academic)
        assignments = reader.get_assignments(user_id)
        persist(db_path, user_id, username, courses, assignments=assignments, refreshed_course_ids=academic)
        lectures = reader.get_lectures(user_id)
        persist(db_path, user_id, username, courses, lectures=lectures, refreshed_course_ids=academic)
        _mark_checks(db_path, user_id, 'academic', academic, ids, scope)
    if changed:
        persist(db_path, user_id, username, courses, activities=activities, refreshed_course_ids=changed)
    if notices_scope:
        with closing(LocalDatabase(db_path, read_only=True)) as database:
            previous_notices = database.get_notices(user_id)
        try:
            notice_cache = json.loads(state.get('notice_detail_checks', '{}'))
        except (TypeError, ValueError):
            notice_cache = {}
        if not isinstance(notice_cache, dict):
            notice_cache = {}
        notices = provider.for_courses(user_id, notices_scope).get_notices(
            user_id, existing_notices=previous_notices, notice_cache=notice_cache,
            force_details=force or bool(args.resource_id) or not args.metadata_only or bool(
                sync_policy.due_courses(state, 'notice', notices_scope, sync_policy.NOTICE_TTL)))
        retained_notice_ids = {item['id'] for item in previous_notices
                               if item['courseId'] in ids - notices_scope}
        notice_cache = {key: value for key, value in notice_cache.items() if key in retained_notice_ids}
        reused_notice_courses = set()
        for notice in notices:
            if notice.pop('_notice_reused', False):
                reused_notice_courses.add(notice['courseId'])
            checked = notice.pop('_notice_check', None)
            if checked is not None:
                notice_cache[notice['id']] = checked
        persist(db_path, user_id, username, courses, notices=notices, refreshed_course_ids=notices_scope)
        with closing(LocalDatabase(db_path)) as database:
            database.merge_sync_state(user_id, {'notice_detail_checks': json.dumps(notice_cache, sort_keys=True)})
        _mark_checks(db_path, user_id, 'notice', notices_scope - reused_notice_courses, ids, scope)
    if resources_scope:
        file_root = db_path.parent / 'files'
        with closing(LocalDatabase(db_path, read_only=True)) as database:
            notices = database.get_notices(user_id)
            previous_resources = database.get_resources(user_id, include_permissions=False)
        resources = provider.for_courses(user_id, resources_scope).get_resources(
            user_id, notices=notices, existing_resources=_cached_resources(db_path, user_id, file_root),
            download_new_files=not args.metadata_only, resource_ids=set(args.resource_id) if args.resource_id else None,
            detail_course_ids=detail_courses if args.resource_id else None,
            save_file=lambda item: store_resource(file_root, item), partial_root=file_root)
        if any(item.get('_checkFailed') for item in resources):
            raise URLError('일부 자료의 현재 상태를 확인하지 못했어요.')
        checked_resource_ids = {item['id'] for item in resources}
        partial_courses = resources_scope - detail_courses if args.resource_id else set()
        resources += [item for item in previous_resources if item['courseId'] in partial_courses
                      and item['id'] not in checked_resource_ids]
        persist(db_path, user_id, username, courses, resources=resources, refreshed_course_ids=resources_scope)
        _mark_checks(db_path, user_id, 'resource', resources_scope - partial_courses, ids, scope)
        if args.resource_id:
            try:
                item_checks = json.loads(state.get('resource_item_checks', '{}'))
            except (TypeError, ValueError):
                item_checks = {}
            if not isinstance(item_checks, dict):
                item_checks = {}
            current_ids = {item['id'] for item in resources} | {
                item['id'] for item in previous_resources if item['courseId'] in ids - resources_scope}
            item_checks = {key: value for key, value in item_checks.items() if key in current_ids}
            item_checks.update(dict.fromkeys(checked_resource_ids & set(args.resource_id), sync_policy.now().isoformat()))
            with closing(LocalDatabase(db_path)) as database:
                database.merge_sync_state(user_id, {'resource_item_checks': json.dumps(item_checks)})
        if not args.metadata_only and not args.resource_id:
            complete = {identifier for identifier in resources_scope if all(
                item.get('downloadStatus') in ('DOWNLOADED', 'PROHIBITED')
                for item in resources if item['courseId'] == identifier)}
            _mark_checks(db_path, user_id, 'file', complete, ids, scope)
    _save_sync_state(db_path, user_id, provider)
    with closing(LocalDatabase(db_path)) as database:
        database.merge_sync_state(user_id, {'catalog_checked_at': sync_policy.now().isoformat(), 'sync_scope': scope})
    if autonomous_message:
        print(autonomous_message)
    print(f'학교 확인 완료 · 과목 {len(ids)}개 · 과제·시청 상태 {len(academic)}과목 · 공지 {len(notices_scope)}과목 · 자료 {len(resources_scope)}과목 · {monotonic() - started:.1f}초')


if __name__ == '__main__':
    main()
