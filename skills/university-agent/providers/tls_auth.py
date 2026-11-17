"""Reuse a protected TLS session before falling back to the saved password."""
from __future__ import annotations

import os
import subprocess

from providers.credentials import (
    clear_session,
    load,
    load_active_alias,
    load_session,
    load_username,
    resolve,
    resolve_profile,
    save,
    save_session,
    site_key,
)
from providers.moodle_session import MoodleSession, LoginError, RequestBackoff


def resume_saved_session(base_url: str, requested_username: str | None = None,
                         profile_alias: str | None = None):
    """Return a verified session or None; cookie values never leave this module."""
    site = site_key(base_url)
    profile_alias = profile_alias or os.environ.get("TLS_ACCOUNT_ALIAS") or load_active_alias(site)
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
        clear_session(username, profile_alias, site)
    except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
        return None
    return None


def authenticated_session(base_url: str | None = None, requested_username: str | None = None,
                          *, stored_only: bool = False, profile_alias: str | None = None,
                          allow_prompt: bool = False):
    """Reuse local auth; only an explicit connection flow may open the form."""
    base_url = base_url or os.environ.get("TLS_BASE_URL", "https://tls.kku.ac.kr")
    site = site_key(base_url)
    profile_alias = profile_alias or os.environ.get("TLS_ACCOUNT_ALIAS") or load_active_alias(site)
    requested_username = requested_username or os.environ.get("TLS_USERNAME")
    resumed = resume_saved_session(base_url, requested_username, profile_alias)
    if resumed:
        return resumed
    if stored_only:
        username, password = load(profile_alias, site)
        if not username or not password:
            raise RuntimeError('저장된 학교 계정의 비밀번호가 비어 있어요. 연결 명령으로 한 번만 다시 입력해 주세요.')
    else:
        needs_prompt = False
        try:
            username, password = load(profile_alias, site)
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
        save(username, password, profile_alias, site)
    finally:
        password = None
    try:
        save_session(username, session.cookies, profile_alias, site)
    except (OSError, RuntimeError, ValueError):
        # Keep this login usable, but explain why the next run may authenticate again.
        print('학교 로그인은 성공했지만 보호 저장소에 세션을 보관하지 못했어요. 다음 실행에서 다시 연결할 수 있어요.', flush=True)
    return username, session
