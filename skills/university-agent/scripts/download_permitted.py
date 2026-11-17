#!/usr/bin/env python3
"""Explicit, single-file instructor permission; not part of ordinary sync."""
import argparse
from contextlib import closing, contextmanager
import json
import os
import subprocess
import sqlite3
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from providers.credentials import load_active_alias, load_username, profile_db_path, site_key
from providers.moodle_provider import MoodleTLSProvider, validate_permission
from providers.moodle_session import DownloadRestricted, LoginError
from providers.tls_auth import authenticated_session
from storage.local_db import LocalDatabase
from sync_tls import store_resource, _prepare_requested_resources
from features import sync_policy
from providers.moodle_session import RequestBackoff
from providers.request_metrics import RequestMetrics, measure_requests


@contextmanager
def download_scope(path, scope):
    with sync_policy.SyncLock(path, timeout=5) as guard:
        if guard.remaining(scope):
            raise RequestBackoff(guard.remaining(scope))
        try:
            yield
        except (URLError, TimeoutError, ConnectionError) as error:
            guard.record(scope, failed=bool(guard.state(scope).get('failed')),
                delay=error.seconds if isinstance(error, RequestBackoff) else 60)
            raise


def permission_records(value, user, targets):
    records = value if isinstance(value, list) else [value]
    if not 1 <= len(records) <= 20 or len(targets) != len(set(targets)):
        raise ValueError('대상 자료를 중복 없이 1~20개 지정해 주세요.')
    result = {}
    for record in records:
        identifier = record.get('resourceId') if isinstance(record, dict) else None
        validate_permission(record, user, identifier)
        if identifier in result:
            raise ValueError('같은 자료의 허락 기록이 중복되어 있어요.')
        result[identifier] = record
    if set(result) != set(targets):
        raise ValueError('요청한 각 자료에 일치하는 허락 기록이 필요해요.')
    return result


def _main():
    parser = argparse.ArgumentParser(description='Process one explicitly permitted local resource')
    parser.add_argument('--resource-id', required=True, action='append')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--permission-file', type=Path)
    action.add_argument('--revoke', action='store_true')
    parser.add_argument('--viewer-url')
    parser.add_argument('--course-id', action='append', default=[], help='새 자료가 올라온 현재 수강 과목 ID')
    parser.add_argument('--metrics', action='store_true', help='요청 수·응답 본문량·경과 시간만 출력')
    args = parser.parse_args()
    if args.viewer_url and len(args.resource_id) != 1:
        parser.error('--viewer-url은 자료 하나를 선택했을 때만 사용해 주세요.')
    base_url = os.environ.get('TLS_BASE_URL', 'https://tls.kku.ac.kr')
    alias = os.environ.get('TLS_ACCOUNT_ALIAS') or load_active_alias(site_key(base_url))
    path = profile_db_path(base_url, alias)
    try:
        # Load and validate the attestation before credentials or network access.
        if args.permission_file and args.permission_file.stat().st_size > 16000:
            raise ValueError('허락 내용이 너무 길어 자료를 가져오지 않았어요.')
        permission = json.loads(args.permission_file.read_text(encoding='utf-8')) if args.permission_file else None
        if permission is not None:
            first = permission[0] if isinstance(permission, list) and permission else permission
            permission_records(permission, first.get('userId') if isinstance(first, dict) else None, args.resource_id)
        elif not args.revoke:
            raise ValueError('이 자료에 대해 확인된 허락 내용이 없어 가져오지 않았어요.')
        try:
            if args.revoke:
                username = os.environ.get('UNIVERSITY_AGENT_USER_ID') or load_username(alias, site_key(base_url))
            else:
                username = os.environ.get('UNIVERSITY_AGENT_USER_ID') or load_username(alias, site_key(base_url))
        except (OSError, KeyError, ValueError, subprocess.CalledProcessError) as error:
            raise SystemExit('학교 연결이 먼저 필요해요. 비밀번호는 대화에 보내지 말고 연결창에서 입력해 주세요.') from error
        user = os.environ.get('UNIVERSITY_AGENT_USER_ID', username)
        if permission is not None:
            permissions = permission_records(permission, user, args.resource_id)
        if not path.is_file():
            raise ValueError('먼저 학교 자료 목록을 가져와 주세요.')
        if args.revoke:
            with closing(LocalDatabase(path)) as database:
                known = {item['id'] for item in database.get_resources(user, include_permissions=False)}
                if not set(args.resource_id) <= known:
                    raise ValueError('선택한 수업 자료를 찾지 못했어요.')
                for identifier in args.resource_id:
                    database.revoke_resource_permission(user, identifier)
                print('이 자료에 대한 허락 기록을 해제했어요. 저장했던 원본은 지우지 않았어요.', flush=True)
                return
        scope = sync_policy.scope_key(base_url, username)
        with download_scope(path, scope):
            authenticated_user, session = authenticated_session(base_url, username, profile_alias=alias)
            if authenticated_user != username:
                raise LoginError('account mismatch')
            provider = MoodleTLSProvider(session, lambda message: print(message, flush=True))
            with closing(LocalDatabase(path, read_only=True)) as database:
                originals = {r['id']: r for r in database.get_resources(user, include_permissions=False)}
                state = database.get_sync_state(user)
            if any(identifier not in originals for identifier in args.resource_id):
                _prepare_requested_resources(SimpleNamespace(resource_id=args.resource_id,
                    course_id=args.course_id, metadata_only=True), path, user, username, provider, scope, state)
                with closing(LocalDatabase(path, read_only=True)) as database:
                    originals = {r['id']: r for r in database.get_resources(user, include_permissions=False)}
            for index, identifier in enumerate(args.resource_id, 1):
                original = originals.get(identifier)
                if not original:
                    raise ValueError('선택한 수업 자료를 현재 과목에서 찾지 못했어요.')
                print(f"자료 {index}/{len(args.resource_id)} · {original['title']}을 확인하고 있어요…", flush=True)
                item = provider.download_permitted_resource(user, original, permissions[identifier], args.viewer_url)
                saved = store_resource(path.parent / 'files', item)
                with closing(LocalDatabase(path)) as database:
                    database.save_permitted_resource(user, original, saved, permissions[identifier])
                print(f'자료 {index}/{len(args.resource_id)} 보관 완료', flush=True)
    except json.JSONDecodeError as error:
        raise SystemExit('허락 내용을 읽지 못했어요. 이번에는 자료를 가져오지 않았어요.') from error
    except RequestBackoff as error:
        raise SystemExit(f'학교가 요청 대기를 요구했어요. 약 {max(1, int(error.seconds + 0.999))}초 후 같은 대상만 다시 요청해 주세요. 앞서 보관한 파일은 유지해요.') from error
    except LoginError as error:
        raise SystemExit('학교 연결을 확인하지 못했어요. 앞서 보관한 파일은 유지해요.') from error
    except (URLError, TimeoutError, ConnectionError) as error:
        raise SystemExit('학교 연결이 끊기거나 응답이 늦어 남은 자료를 멈췄어요. 앞서 보관한 파일은 유지해요.') from error
    except sync_policy.SyncBusy as error:
        raise SystemExit('다른 학교 확인이 진행 중이라 5초 안에 시작하지 못했어요. 전체 갱신을 반복하지 말고 진행 중인 작업이 끝난 뒤 같은 대상만 다시 요청해 주세요.') from error
    except (DownloadRestricted, ValueError) as error:
        raise SystemExit(str(error)) from error
    except sqlite3.Error as error:
        raise SystemExit('자료 보관을 마무리하지 못했어요. 저장돼 있던 파일은 그대로 남겨 뒀어요.') from error
    except OSError as error:
        raise SystemExit('자료를 보관할 폴더에 접근하지 못했어요. 기존 파일은 그대로 남겨 뒀어요.') from error


def main():
    metrics = RequestMetrics() if '--metrics' in sys.argv else None
    with measure_requests(metrics):
        try:
            _main()
        finally:
            if metrics:
                print('TLS_METRICS ' + json.dumps(metrics.snapshot(), sort_keys=True), file=sys.stderr)


if __name__ == '__main__':
    main()
