"""Reuse a protected TLS session before falling back to the saved password."""
from __future__ import annotations

import os

from providers.credentials import (
    clear_session,
    load,
    load_session,
    load_username,
    resolve,
    save,
    save_session,
)
from providers.moodle_session import MoodleSession, LoginError, RequestBackoff


def resume_saved_session(base_url: str, requested_username: str | None = None):
    """Return a verified session or None; cookie values never leave this module."""
    try:
        username = load_username()
        if requested_username and requested_username != username:
            return None
        session = MoodleSession(base_url)
        session.restore_cookies(load_session(username))
        if session.resume():
            return username, session
        clear_session(username)
    except RequestBackoff:
        raise
    except LoginError:
        clear_session(username)
    except (OSError, KeyError, TypeError, ValueError):
        return None
    return None


def authenticated_session(base_url: str | None = None, requested_username: str | None = None,
                          *, stored_only: bool = False):
    """Use a valid protected session, otherwise perform one credential login."""
    base_url = base_url or os.environ.get("TLS_BASE_URL", "https://tls.kku.ac.kr")
    requested_username = requested_username or os.environ.get("TLS_USERNAME")
    resumed = resume_saved_session(base_url, requested_username)
    if resumed:
        return resumed
    if stored_only:
        username, password = load()
    else:
        username, password = resolve(requested_username)
    session = MoodleSession(base_url)
    session.login(username, password)
    save(username, password)
    try:
        save_session(username, session.cookies)
    except (OSError, RuntimeError, ValueError):
        # A valid login must remain usable even if the OS refuses session caching.
        pass
    return username, session
