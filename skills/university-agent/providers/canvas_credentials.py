"""Canvas API token storage using the OS secret store."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from providers.credentials import (
    read_keychain_secret,
    _save_keychain_secret,
    _windows_protect,
    _windows_unprotect,
    normalize_alias,
    site_key,
)
from storage.private_files import atomic_write_text, private_dir, private_file


CONFIG_PATH = Path.home() / ".university-agent" / "canvas-accounts.json"
SERVICE_PREFIX = "university-agent/canvas-token"
DEFAULT_ALIAS = "default"
DEFAULT_SITE = "canvas.instructure.com"


def _service(site: str) -> str:
    return f"{SERVICE_PREFIX}/{site_key(site)}"


def _config_path(site: str) -> Path:
    site = site_key(site)
    if site == DEFAULT_SITE:
        return CONFIG_PATH
    return CONFIG_PATH.with_name(f"canvas-accounts-{site.replace('.', '-')}.json")


def _read(site: str) -> tuple[str, dict[str, dict[str, str]]]:
    path = _config_path(site)
    if not path.exists():
        return DEFAULT_ALIAS, {}
    private_file(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("site") != site_key(site):
        return DEFAULT_ALIAS, {}
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        return DEFAULT_ALIAS, {}
    return normalize_alias(data.get("activeAlias")), {
        str(alias): value for alias, value in profiles.items() if isinstance(value, dict)
    }


def save_token(token: str, alias: str, site: str, *, user_id: str | None = None) -> None:
    token = str(token or "").strip()
    site = site_key(site)
    alias = normalize_alias(alias)
    if not token or len(token) > 20000 or any(char in token for char in "\r\n"):
        raise ValueError("Canvas API 토큰 형식을 확인하지 못했어요.")
    path = _config_path(site)
    private_dir(path.parent)
    _active, profiles = _read(site)
    if os.name == "nt":
        protected = base64.b64encode(_windows_protect(token.encode("utf-8"))).decode("ascii")
        # The marker file contains no token, only an encrypted blob.
        profiles[alias] = {"protected": protected}
        if user_id is not None:
            profiles[alias]["userId"] = str(user_id)
        payload = {"site": site, "activeAlias": alias, "profiles": profiles}
    else:
        _save_keychain_secret(_service(site), alias, token)
        profiles[alias] = {"userId": str(user_id)} if user_id is not None else {}
        payload = {"site": site, "activeAlias": alias, "profiles": profiles}
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False) + "\n")


def load_token(alias: str | None, site: str) -> str:
    site = site_key(site)
    active, profiles = _read(site)
    alias = normalize_alias(alias or active)
    profile = profiles.get(alias)
    if not isinstance(profile, dict):
        raise ValueError("저장된 Canvas 계정 별칭이 없어요.")
    if os.name == "nt":
        protected = profile.get("protected")
        if not protected:
            raise ValueError("저장된 Canvas 토큰을 읽지 못했어요.")
        return _windows_unprotect(base64.b64decode(protected)).decode("utf-8")
    token = read_keychain_secret(_service(site), alias)
    if not token:
        raise ValueError("저장된 Canvas 토큰을 읽지 못했어요.")
    return token


def list_accounts(site: str) -> list[dict[str, str | bool]]:
    active, profiles = _read(site)
    return [
        {"alias": alias, "active": alias == active,
         **({"userId": str(value["userId"])} if value.get("userId") else {})}
        for alias, value in sorted(profiles.items())
    ]
