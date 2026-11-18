"""Local TLS credential storage using the OS secret store."""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wintypes
import json
import os
import re
import subprocess
import sys
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from urllib.parse import urlsplit

from providers.forms import FormUnavailable, TLS_CREDENTIALS_FORM, collect_secure
from storage.private_files import atomic_write_text, private_dir, private_file

SERVICE = "university-agent/tls"
SESSION_SERVICE = "university-agent/tls-session"
CONFIG_PATH = Path.home() / ".university-agent" / "tls-account.json"
SESSION_PATH = CONFIG_PATH.with_name("tls-session.json")
DEFAULT_SITE = "tls.kku.ac.kr"
DEFAULT_ALIAS = "default"


CredentialInputRequired = FormUnavailable


def site_key(base_url: str | None = None) -> str:
    """Return a stable, non-secret account namespace for one LMS host."""
    value = (base_url or DEFAULT_SITE).strip()
    parsed = urlsplit(value if "://" in value else "https://" + value)
    host = (parsed.hostname or "").casefold().strip(".")
    if (not host or host in {".", ".."} or ".." in host
            or not re.fullmatch(r"[a-z0-9.-]+", host)):
        raise ValueError("학교 LMS 주소를 확인하지 못했어요.")
    return host


def normalize_alias(alias: str | None) -> str:
    value = (alias or DEFAULT_ALIAS).strip()
    if not value:
        return DEFAULT_ALIAS
    if (value in {".", ".."} or len(value) > 64
            or any(char in value for char in '<>:"/\\|?*\x00\r\n')):
        raise ValueError("계정 별칭은 64자 이내로 입력해 주세요.")
    return value


def _config_path(site: str) -> Path:
    site = site_key(site)
    if site == DEFAULT_SITE:
        return CONFIG_PATH
    return CONFIG_PATH.with_name(f"tls-account-{site.replace('.', '-')}.json")


def _session_path(site: str) -> Path:
    site = site_key(site)
    if site == DEFAULT_SITE:
        return SESSION_PATH
    return SESSION_PATH.with_name(f"tls-session-{site.replace('.', '-')}.json")


def _credential_service(site: str) -> str:
    site = site_key(site)
    return SERVICE if site == DEFAULT_SITE else f"university-agent/tls/{site}"


def _session_service(site: str) -> str:
    site = site_key(site)
    return SESSION_SERVICE if site == DEFAULT_SITE else f"university-agent/tls-session/{site}"


def _read_keychain_secret(service: str, account: str) -> str:
    if sys.platform == "darwin":
        try:
            security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
            security.SecKeychainFindGenericPassword.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32,
                ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_void_p),
            ]
            security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
            security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            security.SecKeychainItemFreeContent.restype = ctypes.c_int32
            core_foundation = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
            length = ctypes.c_uint32()
            data = ctypes.c_void_p()
            item = ctypes.c_void_p()
            status = security.SecKeychainFindGenericPassword(
                None, len(service.encode()), service.encode(), len(account.encode()), account.encode(),
                ctypes.byref(length), ctypes.byref(data), ctypes.byref(item),
            )
            if status == 0:
                try:
                    secret = ctypes.string_at(data, length.value).decode("utf-8")
                    if not secret:
                        raise ValueError("보호 저장소 항목이 비어 있어요.")
                    return secret
                finally:
                    security.SecKeychainItemFreeContent(None, data)
                    if item:
                        core_foundation.CFRelease(item)
            if status != -25300:  # errSecItemNotFound
                raise OSError(f"Keychain read failed ({status})")
        except OSError as error:
            # Do not fall back to a new `security` process during normal use:
            # macOS can treat it as a different app and ask for approval again.
            # Reconnect explicitly if an old item needs migration.
            if os.environ.get("TURTLENECK_ALLOW_KEYCHAIN_MIGRATION") != "1":
                raise error
        except (AttributeError, ctypes.ArgumentError, ValueError):
            if os.environ.get("TURTLENECK_ALLOW_KEYCHAIN_MIGRATION") != "1":
                raise
    elif os.name == "nt":
        raise OSError("Windows protected storage must use the DPAPI path")
    if sys.platform == "darwin" and os.environ.get("TURTLENECK_ALLOW_KEYCHAIN_MIGRATION") != "1":
        raise OSError("macOS Keychain access needs one explicit reconnect")
    result = subprocess.run(
        ("/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"),
        check=True, capture_output=True, text=True, timeout=5,
    )
    secret = result.stdout.rstrip("\n")
    if not secret:
        raise ValueError("보호 저장소 항목이 비어 있어요.")
    return secret


# Other local providers use the same native read path so their first use does
# not fall back to a new `security` process on every request.
read_keychain_secret = _read_keychain_secret


def _delete_keychain_secret(service: str, account: str) -> None:
    """Delete one secret without spawning a second macOS security client."""
    if sys.platform == "darwin":
        security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        security.SecKeychainFindGenericPassword.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32,
            ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        security.SecKeychainItemFreeContent.restype = ctypes.c_int32
        security.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
        security.SecKeychainItemDelete.restype = ctypes.c_int32
        core_foundation = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
        length = ctypes.c_uint32()
        data = ctypes.c_void_p()
        item = ctypes.c_void_p()
        status = security.SecKeychainFindGenericPassword(
            None, len(service.encode()), service.encode(), len(account.encode()), account.encode(),
            ctypes.byref(length), ctypes.byref(data), ctypes.byref(item),
        )
        if data:
            security.SecKeychainItemFreeContent(None, data)
        if status == -25300:  # errSecItemNotFound
            return
        if status != 0:
            raise OSError(f"Keychain lookup failed ({status})")
        try:
            status = security.SecKeychainItemDelete(item)
            if status not in (0, -25300):
                raise OSError(f"Keychain delete failed ({status})")
        finally:
            if item:
                core_foundation.CFRelease(item)
        return
    subprocess.run(
        ("/usr/bin/security", "delete-generic-password", "-s", service, "-a", account),
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _save_keychain_secret(service: str, account: str, secret: str) -> None:
    """Write a Keychain value without putting the secret in the process argv."""
    if sys.platform == "darwin":
        security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        security.SecKeychainAddGenericPassword.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32,
            ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        ]
        security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        core_foundation = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        core_foundation.CFRelease.argtypes = [ctypes.c_void_p]

        service_bytes = service.encode("utf-8")
        account_bytes = account.encode("utf-8")
        secret_bytes = secret.encode("utf-8")
        item = ctypes.c_void_p()
        password_buffer = ctypes.create_string_buffer(secret_bytes)
        status = security.SecKeychainAddGenericPassword(
            None, len(service_bytes), service_bytes, len(account_bytes), account_bytes,
            len(secret_bytes), ctypes.cast(password_buffer, ctypes.c_void_p), ctypes.byref(item),
        )
        try:
            if status == -25299:  # errSecDuplicateItem: replace only this exact entry.
                _delete_keychain_secret(service, account)
                status = security.SecKeychainAddGenericPassword(
                    None, len(service_bytes), service_bytes, len(account_bytes), account_bytes,
                    len(secret_bytes), ctypes.cast(password_buffer, ctypes.c_void_p), ctypes.byref(item),
                )
            if status != 0:
                raise OSError(f"Keychain write failed ({status})")
        finally:
            if item:
                core_foundation.CFRelease(item)
        if _read_keychain_secret(service, account) != secret:
            raise OSError("Keychain write verification failed")
        return
    subprocess.run(
        ("/usr/bin/security", "add-generic-password", "-U", "-s", service,
         "-a", account, "-w"),
        input=f"{secret}\n", text=True, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if _read_keychain_secret(service, account) != secret:
        raise OSError("Keychain write verification failed")


def _read_accounts(path: Path) -> tuple[str, dict[str, dict[str, str]], bool]:
    private_file(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    profiles = data.get("profiles")
    if isinstance(profiles, dict):
        active = normalize_alias(data.get("activeAlias"))
        return active, {str(key): value for key, value in profiles.items() if isinstance(value, dict)}, False
    # Migrate the original one-account marker in memory. The old Keychain item
    # is read as a fallback until the account is saved again under its alias.
    username = data.get("username")
    if not isinstance(username, str) or not username:
        raise ValueError("저장된 학교 계정을 읽지 못했어요.")
    profile = {"username": username}
    if isinstance(data.get("passwordProtected"), str):
        profile["passwordProtected"] = data["passwordProtected"]
    return DEFAULT_ALIAS, {DEFAULT_ALIAS: profile}, True


def _write_accounts(path: Path, active: str, profiles: dict[str, dict[str, str]], site: str = DEFAULT_SITE) -> None:
    private_dir(path.parent)
    payload = {"activeAlias": normalize_alias(active), "profiles": profiles}
    payload["site"] = site_key(site)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False) + "\n")


def list_accounts(site: str = DEFAULT_SITE) -> list[dict[str, str | bool]]:
    """List only non-secret profile markers for the selected LMS host."""
    path = _config_path(site)
    if not path.exists():
        return []
    active, profiles, _legacy = _read_accounts(path)
    return [{"alias": alias, "username": str(profile.get("username", "")), "active": alias == active}
            for alias, profile in sorted(profiles.items()) if profile.get("username")]


def profile_db_path(site: str = DEFAULT_SITE, alias: str | None = None) -> Path:
    """Return the private SQLite path for one site/account profile."""
    site = site_key(site)
    alias = normalize_alias(alias or load_active_alias(site))
    configured = os.environ.get("UNIVERSITY_AGENT_DB")
    if configured:
        # An explicit path is an isolation boundary; do not redirect it because
        # another profile happens to be active in the host environment.
        return Path(configured).expanduser()
    base = CONFIG_PATH.parent / "university.db"
    if site == DEFAULT_SITE and alias == DEFAULT_ALIAS:
        return base
    return base.parent / "profiles" / site / alias / "university.db"


def list_profiles() -> list[dict[str, str | bool]]:
    """List profile markers and paths without reading passwords or cookies."""
    paths = [CONFIG_PATH, *CONFIG_PATH.parent.glob("tls-account-*.json")]
    result = []
    seen = set()
    for path in paths:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            site = site_key(data.get("site") or (DEFAULT_SITE if path == CONFIG_PATH else path.stem.removeprefix("tls-account-").replace("-", ".")))
            if site in seen:
                continue
            seen.add(site)
            for account in list_accounts(site):
                result.append({**account, "site": site, "dbPath": str(profile_db_path(site, account["alias"]))})
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
    # Canvas keeps token markers in a separate file. Import only alias/user markers;
    # the token itself remains in the OS secret store or protected Windows blob.
    try:
        from providers.canvas_credentials import list_accounts as canvas_accounts
        for path in CONFIG_PATH.parent.glob("canvas-accounts*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                site = site_key(data.get("site"))
                for account in canvas_accounts(site):
                    alias = normalize_alias(account.get("alias"))
                    username = str(account.get("userId") or f"canvas:{site}:{alias}")
                    result.append({"alias": alias, "username": username, "active": bool(account.get("active")),
                                  "site": site, "dbPath": str(profile_db_path(site, alias))})
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
    except (ImportError, OSError, ValueError):
        pass
    # Moodle Web Service tokens are additional credentials, never a replacement
    # for the site's password profile.
    for path in CONFIG_PATH.parent.glob("moodle-api-accounts*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            site = site_key(data.get("site") or (DEFAULT_SITE if path == CONFIG_PATH.parent / "moodle-api-accounts.json"
                                                  else path.stem.removeprefix("moodle-api-accounts-").replace("-", ".")))
            profiles = data.get("profiles")
            if not isinstance(profiles, dict):
                continue
            active = normalize_alias(data.get("activeAlias"))
            for alias, account in profiles.items():
                if not isinstance(account, dict):
                    continue
                result.append({"alias": normalize_alias(alias),
                               "username": str(account.get("userId") or f"moodle-api:{site}:{alias}"),
                               "active": alias == active, "site": site,
                               "apiService": str(account.get("service", "moodle_mobile_app")),
                               "dbPath": str(profile_db_path(site, alias))})
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
    return result


def link_account(site: str, alias: str, source_site: str, source_alias: str) -> None:
    """Explicitly reuse one source profile's password on another LMS host."""
    site, source_site = site_key(site), site_key(source_site)
    alias, source_alias = normalize_alias(alias), normalize_alias(source_alias)
    if (site, alias) == (source_site, source_alias):
        raise ValueError("같은 학교 계정 자체를 다시 연결할 수 없어요.")
    source_path = _config_path(source_site)
    _active, source_profiles, _legacy = _read_accounts(source_path)
    source = source_profiles.get(source_alias)
    if not isinstance(source, dict) or not source.get("username"):
        raise ValueError("재사용할 원본 학교 계정 별칭을 찾지 못했어요.")
    target_path = _config_path(site)
    if target_path.exists():
        _target_active, profiles, _target_legacy = _read_accounts(target_path)
    else:
        profiles = {}
    profiles[alias] = {
        "username": str(source["username"]),
        "credentialRef": {"site": source_site, "alias": source_alias},
    }
    _write_accounts(target_path, alias, profiles, site)


def set_active_alias(alias: str, site: str = DEFAULT_SITE, *, allow_missing: bool = False) -> None:
    alias = normalize_alias(alias)
    path = _config_path(site)
    if path.exists():
        _active, profiles, _legacy = _read_accounts(path)
    else:
        profiles = {}
    if not allow_missing and alias not in profiles:
        raise ValueError("해당 사이트에 저장된 계정 별칭이 없어요.")
    _write_accounts(path, alias, profiles, site)


def load_active_alias(site: str = DEFAULT_SITE) -> str:
    path = _config_path(site)
    if not path.exists():
        return DEFAULT_ALIAS
    active, _profiles, _legacy = _read_accounts(path)
    return active


def save(username: str, password: str, alias: str | None = None, site: str = DEFAULT_SITE) -> None:
    if not username or not password:
        raise ValueError("TLS username and password are required")
    site = site_key(site)
    alias = normalize_alias(alias or load_active_alias(site))
    path = _config_path(site)
    profiles = {}
    if path.exists():
        try:
            _active, profiles, _legacy = _read_accounts(path)
        except (OSError, ValueError, KeyError, TypeError):
            profiles = {}
    existing = profiles.get(alias)
    reference = existing.get("credentialRef") if isinstance(existing, dict) else None
    if isinstance(reference, dict):
        try:
            linked_username, linked_password = _load_secret(alias, site)
            if linked_username == username and linked_password == password:
                profiles[alias] = {"username": username, "credentialRef": reference}
                _write_accounts(path, alias, profiles, site)
                return
        except (OSError, KeyError, ValueError, TypeError, subprocess.SubprocessError):
            pass
    if os.name == "nt":
        protected = base64.b64encode(_windows_protect(password.encode("utf-8"))).decode("ascii")
        profiles[alias] = {"username": username, "passwordProtected": protected}
        _write_accounts(path, alias, profiles, site)
        return
    try:
        _save_keychain_secret(_credential_service(site), alias, password)
    except (FileNotFoundError, subprocess.SubprocessError) as error:
        raise RuntimeError("운영체제 보안 저장소를 사용할 수 없어 비밀번호를 저장하지 못했어요.") from error
    profiles[alias] = {"username": username}
    _write_accounts(path, alias, profiles, site)


def _load_secret(alias: str | None, site: str, seen: set[tuple[str, str]] | None = None) -> tuple[str, str]:
    site = site_key(site)
    path = _config_path(site)
    active, profiles, legacy = _read_accounts(path)
    alias = normalize_alias(alias or active)
    account = profiles.get(alias)
    if not account:
        raise ValueError("저장된 학교 계정 별칭이 없어요.")
    username = account["username"]
    reference = account.get("credentialRef")
    if isinstance(reference, dict):
        source_site = site_key(str(reference.get("site", "")))
        source_alias = normalize_alias(str(reference.get("alias", "")))
        seen = seen or set()
        key = (site, alias)
        if key in seen:
            raise ValueError("학교 계정 연결이 서로를 가리켜 비밀번호를 읽지 못했어요.")
        return _load_secret(source_alias, source_site, seen | {key})
    if os.name == "nt":
        password = _windows_unprotect(base64.b64decode(account["passwordProtected"])).decode("utf-8")
        return username, password
    accounts = [alias]
    # The first multi-profile migration kept the original password under the
    # username. Only the default profile may use that exact legacy fallback;
    # never infer a shared secret for a separately named account.
    if legacy or (site == DEFAULT_SITE and alias == DEFAULT_ALIAS):
        accounts.append(username)
    last_error = None
    for key in accounts:
        try:
            return username, _read_keychain_secret(_credential_service(site), key)
        except (subprocess.SubprocessError, ValueError) as error:
            last_error = error
    if last_error:
        raise last_error
    raise ValueError("저장된 학교 비밀번호를 읽지 못했어요.")


def load(alias: str | None = None, site: str = DEFAULT_SITE) -> tuple[str, str]:
    return _load_secret(alias, site)


def load_username(alias: str | None = None, site: str = DEFAULT_SITE) -> str:
    """Read only the non-secret account marker for session lookup."""
    active, profiles, _legacy = _read_accounts(_config_path(site))
    account = profiles.get(normalize_alias(alias or active))
    if not account:
        raise ValueError("저장된 학교 계정 별칭이 없어요.")
    username = account["username"]
    if not isinstance(username, str) or not username:
        raise ValueError("TLS username is missing")
    return username


def _cookie_payload(username: str, cookies: CookieJar) -> str:
    items = []
    for cookie in cookies:
        if not cookie.name or not cookie.value or not cookie.domain:
            continue
        items.append({
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path or "/",
            "secure": bool(cookie.secure),
            "expires": cookie.expires,
        })
    if not items:
        raise ValueError("TLS session has no cookies")
    return json.dumps({"username": username, "cookies": items}, ensure_ascii=False, separators=(",", ":"))


def _cookie_jar(payload: str, username: str) -> CookieJar:
    data = json.loads(payload)
    if data.get("username") != username or not isinstance(data.get("cookies"), list):
        raise ValueError("TLS session belongs to another account")
    jar = CookieJar()
    for item in data["cookies"]:
        if not isinstance(item, dict) or not item.get("name") or not item.get("domain"):
            continue
        expires = item.get("expires")
        if expires is not None:
            try:
                expires = int(expires)
            except (TypeError, ValueError):
                expires = None
        jar.set_cookie(Cookie(
            version=0,
            name=str(item["name"]),
            value=str(item.get("value", "")),
            port=None,
            port_specified=False,
            domain=str(item["domain"]),
            domain_specified=bool(item["domain"]),
            domain_initial_dot=str(item["domain"]).startswith("."),
            path=str(item.get("path") or "/"),
            path_specified=True,
            secure=bool(item.get("secure")),
            expires=expires,
            discard=expires is None,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        ))
    return jar


def _read_sessions(path: Path) -> tuple[str, dict[str, dict[str, str]]]:
    if not path.exists():
        return DEFAULT_ALIAS, {}
    private_file(path)
    state = json.loads(path.read_text(encoding="utf-8"))
    profiles = state.get("profiles")
    if isinstance(profiles, dict):
        return normalize_alias(state.get("activeAlias")), {str(key): value for key, value in profiles.items() if isinstance(value, dict)}
    # Original session marker: its macOS secret was stored under the username.
    username = state.get("username")
    return DEFAULT_ALIAS, ({DEFAULT_ALIAS: {"username": username}} if isinstance(username, str) and username else {})


def save_session(username: str, cookies: CookieJar, alias: str | None = None, site: str = DEFAULT_SITE) -> None:
    """Keep the short-lived TLS session only in the OS-protected store."""
    site = site_key(site)
    alias = normalize_alias(alias or load_active_alias(site))
    payload = _cookie_payload(username, cookies)
    path = _session_path(site)
    private_dir(path.parent)
    _active, profiles = _read_sessions(path)
    if os.name == "nt":
        protected = base64.b64encode(_windows_protect(payload.encode("utf-8"))).decode("ascii")
        profiles[alias] = {"username": username, "protected": protected}
        atomic_write_text(path, json.dumps({"activeAlias": alias, "profiles": profiles}) + "\n")
        return
    try:
        _save_keychain_secret(_session_service(site), alias, payload)
    except (FileNotFoundError, subprocess.SubprocessError) as error:
        raise RuntimeError("운영체제 보안 저장소를 사용할 수 없어 학교 세션을 저장하지 못했어요.") from error
    profiles[alias] = {"username": username}
    atomic_write_text(path, json.dumps({"activeAlias": alias, "profiles": profiles}) + "\n")


def load_session(username: str, alias: str | None = None, site: str = DEFAULT_SITE) -> CookieJar:
    site = site_key(site)
    path = _session_path(site)
    private_file(path)
    state = json.loads(path.read_text(encoding="utf-8"))
    profiles = state.get("profiles")
    legacy = not isinstance(profiles, dict)
    if legacy:
        profiles = {DEFAULT_ALIAS: state}
    alias = normalize_alias(alias or state.get("activeAlias") or DEFAULT_ALIAS)
    profile = profiles.get(alias)
    if not isinstance(profile, dict) or profile.get("username") != username:
        raise ValueError("TLS session belongs to another account")
    if os.name == "nt":
        payload = _windows_unprotect(base64.b64decode(profile["protected"])).decode("utf-8")
    else:
        accounts = [alias]
        if legacy:
            accounts.append(username)
        last_error = None
        for key in accounts:
            try:
                payload = _read_keychain_secret(_session_service(site), key)
                break
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                last_error = error
        else:
            raise last_error or ValueError("저장된 학교 세션을 읽지 못했어요.")
    return _cookie_jar(payload, username)


def clear_session(username: str, alias: str | None = None, site: str = DEFAULT_SITE) -> None:
    site = site_key(site)
    path = _session_path(site)
    if path.exists():
        private_file(path)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    profiles = state.get("profiles") if isinstance(state.get("profiles"), dict) else {}
    selected = normalize_alias(alias or state.get("activeAlias") or DEFAULT_ALIAS)
    if os.name != "nt":
        for key in ({selected, username} if not profiles else {selected}):
            _delete_keychain_secret(_session_service(site), key)
    if profiles and selected in profiles:
        profiles.pop(selected, None)
        if profiles:
            next_alias = next(iter(profiles))
            atomic_write_text(path, json.dumps({"activeAlias": next_alias, "profiles": profiles}) + "\n")
        else:
            path.unlink(missing_ok=True)
    else:
        path.unlink(missing_ok=True)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _windows_protect(value: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Windows secret storage is unavailable")
    source_buffer = (ctypes.c_byte * len(value)).from_buffer_copy(value)
    source = _DataBlob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    result = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def _windows_unprotect(value: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Windows secret storage is unavailable")
    source_buffer = (ctypes.c_byte * len(value)).from_buffer_copy(value)
    source = _DataBlob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    result = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def resolve_profile(username: str | None = None, alias: str | None = None, *, force_input: bool = False,
                    site: str = DEFAULT_SITE,
                    submit_check=None) -> tuple[str, str, str]:
    site = site_key(site)
    alias = normalize_alias(alias or os.environ.get("TLS_ACCOUNT_ALIAS") or load_active_alias(site))
    try:
        stored_username, stored_password = load(alias, site)
    except (OSError, KeyError, ValueError, subprocess.SubprocessError):
        try:
            load_username(alias, site)
        except (OSError, KeyError, ValueError, subprocess.SubprocessError):
            stored_username, stored_password = "", ""
        else:
            raise FormUnavailable(
                "저장된 학교 계정의 비밀번호가 비어 있어요. 연결 명령으로 한 번만 다시 입력해 주세요."
            ) from None
    if force_input:
        values = collect_secure(
            TLS_CREDENTIALS_FORM,
            initial={"alias": alias, "username": username or stored_username},
            submit_check=submit_check,
            success_message="안전하게 등록되었습니다. 학교 연결과 보호 저장소 저장을 확인했어요.",
        )
        selected = normalize_alias(values.get("alias") or alias)
        set_active_alias(selected, site, allow_missing=True)
        return values["username"], values["password"], selected
    if stored_username and stored_password and (not username or username == stored_username):
        return username or stored_username, stored_password, alias
    values = collect_secure(TLS_CREDENTIALS_FORM, initial={"alias": alias, "username": username or stored_username},
                            submit_check=submit_check)
    selected = normalize_alias(values.get("alias") or alias)
    set_active_alias(selected, site, allow_missing=True)
    return values["username"], values["password"], selected


def resolve(username: str | None = None, *, force_input: bool = False,
            site: str = DEFAULT_SITE, submit_check=None) -> tuple[str, str]:
    selected_username, password, _alias = resolve_profile(username, force_input=force_input, site=site,
                                                         submit_check=submit_check)
    return selected_username, password
