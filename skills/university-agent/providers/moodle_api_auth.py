"""Explicit Moodle Web Service token connection flow."""
from __future__ import annotations

import subprocess
from urllib.parse import urlsplit

from providers.credentials import normalize_alias, site_key
from providers.forms import MOODLE_API_CONNECTION_FORM, collect_secure
from providers.moodle_api import MoodleWebServiceClient
from providers.moodle_api_credentials import DEFAULT_SERVICE, load_token, save_token


def normalize_moodle_domain(value: str) -> str:
    raw = str(value or "").strip()
    if "//" not in raw:
        raw = "https://" + raw
    parsed = urlsplit(raw)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or
            parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("Moodle 주소는 HTTPS 도메인만 사용할 수 있어요.")
    return f"https://{parsed.hostname}" + (f":{parsed.port}" if parsed.port else "")


def authenticated_moodle_api(base_url: str | None = None, alias: str | None = None, *,
                             service: str = DEFAULT_SERVICE, force_input: bool = False):
    alias = normalize_alias(alias)
    if base_url and not force_input:
        normalized = normalize_moodle_domain(base_url)
        try:
            token = load_token(alias, site_key(normalized), service=service)
            client = MoodleWebServiceClient(normalized, token)
            info = client.site_info()
            return alias, client, info
        except (OSError, KeyError, ValueError, subprocess.SubprocessError):
            pass

    values = collect_secure(MOODLE_API_CONNECTION_FORM, initial={
        "alias": alias,
        "domain": base_url or "",
        "service": service,
    })
    normalized = normalize_moodle_domain(values["domain"])
    selected = normalize_alias(values.get("alias") or alias)
    selected_service = values.get("service") or DEFAULT_SERVICE
    token = values["token"]
    client = MoodleWebServiceClient(normalized, token)
    info = client.site_info()
    if not isinstance(info, dict) or info.get("userid") is None:
        raise ValueError("Moodle API 사용자 정보를 확인하지 못했어요.")
    save_token(token, selected, site_key(normalized), service=selected_service,
               user_id=f"moodle:{site_key(normalized)}:{info['userid']}")
    return selected, client, info
