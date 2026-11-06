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
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from socket import timeout as SocketTimeout
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.moodle_provider import MoodleTLSProvider
from providers.moodle_session import LoginError, MoodleSession, RequestBackoff
from providers.credentials import CredentialInputRequired, load, load_username, resolve, save, save_session
from storage.local_db import LocalDatabase
from features.guidance import resource_unavailable_reason
from features.autonomous_course_watch import refresh as refresh_autonomous_course
from providers.tls_auth import resume_saved_session
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
    content = item.pop('_content')
    course, resource = item['courseId'], item['id']
    if not all(re.fullmatch(r'[A-Za-z0-9_-]+', value) for value in (course, resource)):
        raise ValueError('자료 저장 식별자가 올바르지 않습니다.')
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', re.split(r'[\\/]', item['fileName'])[-1]).rstrip(' .')
    if not name or name in ('.', '..'):
        name = 'resource.' + item['extension']
    if re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name, re.I):
        name = '_' + name
    root = file_root.resolve()
    target = root / course / resource / hashlib.sha256(content).hexdigest() / name
    if not target.resolve().is_relative_to(root):
        raise ValueError('자료 저장 위치가 허용된 폴더 밖입니다.')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not target.resolve().is_relative_to(root):
        raise ValueError('자료 저장 위치가 허용된 폴더 밖입니다.')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    validators = item.pop('_validators', {})
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
    command = command or [sys.executable, str(Path(__file__).resolve())]
    options = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    if os.name == 'nt':
        options['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    else:
        options['start_new_session'] = True
    subprocess.Popen(command, **options)
    print('학교 연결 절차를 시작했어요. 브라우저에 입력 화면이 실제로 보이는지 확인해 주세요.', flush=True)


def _login_with_retries(base_url: str, requested_username: str | None = None, *, stored_only=False) -> tuple[str, MoodleSession]:
    """Login without ever returning the password to the caller."""
    resumed = resume_saved_session(base_url, requested_username)
    if resumed:
        print("저장된 학교 연결을 재사용했어요.", flush=True)
        return resumed
    total_attempts = 1 if stored_only else 3
    for attempt in range(1, total_attempts + 1):
        if stored_only:
            try:
                username, password = load()
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                raise RuntimeError('저장된 학교 연결 정보가 없어요. 학교 연결을 다시 마쳐 주세요.') from error
            if requested_username and username != requested_username:
                raise RuntimeError('저장된 학교 계정이 달라요. 학교 연결을 다시 확인해 주세요.')
        else:
            username, password = resolve(requested_username, force_input=attempt > 1)
        print(f"학교 로그인을 확인 중이에요… ({attempt}/{total_attempts})", flush=True)
        session = MoodleSession(base_url)
        try:
            session.login(username, password)
        except LoginError:
            if stored_only or attempt == 3:
                raise
            requested_username = username
            print("로그인이 되지 않았어요. 아이디나 비밀번호를 다시 확인할게요.", flush=True)
            continue
        if not stored_only:
            save(username, password)
        if hasattr(session, "cookies"):
            try:
                save_session(username, session.cookies)
            except (OSError, RuntimeError, ValueError):
                pass
        return username, session
    raise AssertionError("unreachable")


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
    if state.get('sync_scope') != scope:
        return False
    since = requested_at if args.force or args.full else None
    if args.academic_only:
        return sync_policy.fresh(state.get('academic_checked_at'), sync_policy.ACADEMIC_TTL, since=since)
    if state.get('resource_response_version') != MoodleTLSProvider.RESOURCE_RESPONSE_VERSION:
        return False
    if not sync_policy.fresh(state.get('catalog_checked_at'), sync_policy.CATALOG_TTL, since=since):
        return False
    if state.get('autonomous_course_watch_url') and (
            state.get('autonomous_course_check_status') not in ('OK', 'CHANGED') or
            not sync_policy.fresh(state.get('autonomous_course_checked_at'), sync_policy.CATALOG_TTL, since=since)):
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
    parser.add_argument('--metadata-only', action='store_true', help='Refresh records without downloading new file contents')
    parser.add_argument('--academic-only', action='store_true', help='Check assignment/watch status; reuse a successful check for up to 15 minutes')
    parser.add_argument('--ensure', action='store_true', help='Check course changes and refresh only required scopes')
    parser.add_argument('--full', action='store_true', help='Force a complete refresh')
    parser.add_argument('--force', action='store_true', help='Bypass successful-check ages; still respect active syncs and server cooldowns')
    parser.add_argument('--resource-id', action='append', default=[], help='Prepare the requested original file after checking current permissions')
    parser.add_argument('--metrics', action='store_true', help='Print private aggregate HTTP request counters to stderr')
    args = parser.parse_args()
    if args.academic_only and (args.ensure or args.full or args.resource_id or args.connect):
        parser.error('--academic-only는 다른 동기화 범위나 연결 모드와 함께 사용할 수 없습니다.')
    if args.ensure and args.full:
        parser.error('--ensure와 --full은 함께 사용할 수 없습니다.')
    if args.connect:
        try:
            open_connection_terminal()
        except (OSError, subprocess.SubprocessError) as error:
            raise SystemExit('연결창을 자동으로 열지 못했어요. 직접 터미널에서 sync_tls.py를 실행해 주세요.') from error
        return
    db_path = Path(os.environ.get('UNIVERSITY_AGENT_DB', Path.home() / '.university-agent' / 'university.db'))
    base_url = os.environ.get('TLS_BASE_URL', 'https://tls.kku.ac.kr')
    requested_at = sync_policy.now()
    try:
        local_username = os.environ.get('TLS_USERNAME') or load_username()
    except (OSError, KeyError, TypeError, ValueError):
        local_username = None
    scope = sync_policy.scope_key(base_url, local_username) if local_username else None
    try:
        with sync_policy.SyncLock(db_path) as guard:
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
                username, session = _login_with_retries(base_url, os.environ.get('TLS_USERNAME'), stored_only=args.academic_only)
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
    except (sync_policy.SyncBusy, CredentialInputRequired, RuntimeError) as error:
        raise SystemExit(str(error)) from error
    except (URLError, TimeoutError) as error:
        raise SystemExit('학교 확인이 끝나지 않았어요. 기존 기록은 보존했으며 잠시 후 다시 확인할 수 있어요.') from error


def _perform_sync(args, db_path, user_id, username, session, scope, *, retry_failed=False):
    started = monotonic()
    force = args.full or args.force or retry_failed
    provider = MoodleTLSProvider(session)
    provider.progress = lambda message: print(message, flush=True)
    state = _saved_sync_state(db_path, user_id)
    if state.get('sync_scope') != scope:
        force = True
    if args.academic_only:
        courses, assignments, lectures = provider.get_academic_snapshot(user_id)
        persist(db_path, user_id, username, courses, assignments=assignments, lectures=lectures)
        ids = {course['id'] for course in courses}
        _mark_checks(db_path, user_id, 'academic', ids, ids, scope)
        print(f'과제·시청 상태 확인 완료 · 과제 {len(assignments)}개 · 강의 {len(lectures)}개')
        return
    autonomous_url = state.get('autonomous_course_watch_url')
    if autonomous_url and (force or not sync_policy.fresh(state.get('autonomous_course_checked_at'), sync_policy.CATALOG_TTL)):
        watch = refresh_autonomous_course(provider, user_id, autonomous_url,
                                         {'fingerprint': state.get('autonomous_course_fingerprint')})
        with closing(LocalDatabase(db_path)) as database:
            update = {'autonomous_course_checked_at': sync_policy.now().isoformat(),
                      'autonomous_course_check_status': 'CHANGED' if watch.get('changed') else 'OK'}
            if watch['ok']:
                update.update(autonomous_course_fingerprint=watch['fingerprint'],
                              autonomous_course_snapshot=json.dumps(watch['snapshot'], ensure_ascii=False),
                              autonomous_course_check_error='')
            else:
                update.update(autonomous_course_check_status='FAILED', autonomous_course_check_error=watch['reason'])
            database.merge_sync_state(user_id, update)
        if not watch['ok']:
            raise RuntimeError(watch['reason'])
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
            save_file=lambda item: store_resource(file_root, item))
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
    print(f'학교 확인 완료 · 과목 {len(ids)}개 · 과제·시청 상태 {len(academic)}과목 · 공지 {len(notices_scope)}과목 · 자료 {len(resources_scope)}과목 · {monotonic() - started:.1f}초')


if __name__ == '__main__':
    main()
