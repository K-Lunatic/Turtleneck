"""Reuse a protected TLS session before falling back to the saved password."""
from __future__ import annotations

import os
import subprocess
import threading

from providers.credentials import (
    clear_session,
    load,
    load_active_alias,
    load_session,
    load_username,
    ProtectedStoreAccessError,
    profile_db_path,
    resolve,
    resolve_profile,
    save,
    save_session,
    site_key,
)
from providers.moodle_session import MoodleSession, LoginError, RequestBackoff
from features.sync_policy import SyncLock


_PROCESS_SESSIONS = {}
_PROCESS_SESSIONS_LOCK = threading.Lock()


def clear_process_session_cache() -> None:
    """Clear only the in-memory session reuse cache; OS credentials are untouched."""
    with _PROCESS_SESSIONS_LOCK:
        _PROCESS_SESSIONS.clear()


def _session_cache_key(base_url: str, site: str, alias: str, username: str | None) -> tuple[str, str, str, str]:
    return base_url.rstrip('/'), site, alias, username or ''


def _cached_process_session(key):
    with _PROCESS_SESSIONS_LOCK:
        cached = _PROCESS_SESSIONS.get(key)
        if cached and getattr(cached[1], 'logged_in', True):
            return cached
        _PROCESS_SESSIONS.pop(key, None)
    return None


def _remember_process_session(key, value):
    with _PROCESS_SESSIONS_LOCK:
        _PROCESS_SESSIONS[key] = value


def _remember_authenticated_session(base_url: str, site: str, alias: str, value):
    username = value[0]
    _remember_process_session(_session_cache_key(base_url, site, alias, username), value)
    _remember_process_session(_session_cache_key(base_url, site, alias, None), value)


def resume_saved_session(base_url: str, requested_username: str | None = None,
                         profile_alias: str | None = None):
    """Return a verified session or None; cookie values never leave this module."""
    site = site_key(base_url)
    profile_alias = profile_alias or os.environ.get("TLS_ACCOUNT_ALIAS") or load_active_alias(site)
    username = None
    try:
        username = load_username(profile_alias, site)
        if requested_username and requested_username != username:
            return None
        session = MoodleSession(base_url)
        session.restore_cookies(load_session(username, profile_alias, site))
        if session.resume():
            return username, session
        clear_session(username, profile_alias, site)
    except RequestBackoff:
        raise
    except LoginError:
        if username:
            clear_session(username, profile_alias, site)
    except ProtectedStoreAccessError:
        raise
    except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
        return None
    return None


def _authenticated_session_unlocked(base_url: str, requested_username: str | None,
                                    *, stored_only: bool, profile_alias: str,
                                    allow_prompt: bool):
    """Reuse local auth; only an explicit connection flow may open the form."""
    site = site_key(base_url)
    requested_username = requested_username or os.environ.get("TLS_USERNAME")
    cached = _cached_process_session(_session_cache_key(base_url, site, profile_alias, requested_username))
    if cached:
        return cached
    try:
        resumed = resume_saved_session(base_url, requested_username, profile_alias)
    except ProtectedStoreAccessError as error:
        raise RuntimeError(
            'macOS Keychain 접근이 거부됐어요. 연결 화면에서 이 앱의 Keychain 접근을 한 번 허용한 뒤 다시 시도해 주세요.'
        ) from error
    if resumed:
        _remember_authenticated_session(base_url, site, profile_alias, resumed)
        return resumed
    if stored_only:
        username, password = load(profile_alias, site)
        if not username or not password:
            raise RuntimeError('저장된 학교 계정의 비밀번호가 비어 있어요. 연결 명령으로 한 번만 다시 입력해 주세요.')
    else:
        needs_prompt = False
        try:
            username, password = load(profile_alias, site)
        except ProtectedStoreAccessError as error:
            raise RuntimeError(
                'macOS Keychain 접근이 거부됐어요. 연결 화면에서 이 앱의 Keychain 접근을 한 번 허용한 뒤 다시 시도해 주세요.'
            ) from error
        except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError) as error:
            if not allow_prompt:
                raise RuntimeError(
                    '저장된 학교 연결을 읽지 못했어요. 연결 명령으로 한 번만 다시 로그인해 주세요.'
                ) from error
            needs_prompt = True
        else:
            if not username or not password:
                raise RuntimeError('저장된 학교 계정의 비밀번호가 비어 있어요. 연결 명령으로 한 번만 다시 입력해 주세요.')
        if needs_prompt:
            username, password, profile_alias = resolve_profile(requested_username, profile_alias, site=site)
    session = MoodleSession(base_url)
    try:
        session.login(username, password)
        if not stored_only:
            save(username, password, profile_alias, site)
    finally:
        password = None
    try:
        save_session(username, session.cookies, profile_alias, site)
    except (OSError, RuntimeError, ValueError):
        # Keep this login usable, but explain why the next run may authenticate again.
        print('학교 로그인은 성공했지만 보호 저장소에 세션을 보관하지 못했어요. 다음 실행에서 다시 연결할 수 있어요.', flush=True)
    _remember_authenticated_session(base_url, site, profile_alias, (username, session))
    return username, session


def authenticated_session(base_url: str | None = None, requested_username: str | None = None,
                          *, stored_only: bool = False, profile_alias: str | None = None,
                          allow_prompt: bool = False):
    """Authenticate once per profile, even when separate commands start together."""
    base_url = base_url or os.environ.get("TLS_BASE_URL", "https://tls.kku.ac.kr")
    site = site_key(base_url)
    profile_alias = profile_alias or os.environ.get("TLS_ACCOUNT_ALIAS") or load_active_alias(site)
    cached = _cached_process_session(_session_cache_key(base_url, site, profile_alias, requested_username))
    if cached:
        return cached
    # A second process must wait for the first login, then reuse its protected cookie.
    db_path = profile_db_path(base_url, profile_alias)
    auth_path = db_path.with_name(db_path.name + '.auth')
    with SyncLock(auth_path, timeout=120):
        cached = _cached_process_session(_session_cache_key(base_url, site, profile_alias, requested_username))
        if cached:
            return cached
        return _authenticated_session_unlocked(
            base_url, requested_username, stored_only=stored_only,
            profile_alias=profile_alias, allow_prompt=allow_prompt,
        )
