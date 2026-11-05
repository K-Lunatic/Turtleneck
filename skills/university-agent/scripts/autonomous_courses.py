#!/usr/bin/env python3
"""Read the signed-in user's KKU TLS autonomous-course list."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from socket import timeout as SocketTimeout
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.credentials import CredentialInputRequired
from providers.moodle_provider import MoodleTLSProvider
from providers.moodle_session import LoginError
from providers.tls_auth import authenticated_session


def main() -> None:
    try:
        username, session = authenticated_session()
    except CredentialInputRequired as error:
        raise SystemExit(str(error)) from error
    try:
        courses = MoodleTLSProvider(session).get_autonomous_courses(username)
    except SocketTimeout as error:
        raise SystemExit("자율강좌 목록을 30초 안에 받지 못했어요. 잠시 후 다시 확인해 주세요.") from error
    except (LoginError, URLError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps({"source": "tls_autonomous", "courses": courses}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
