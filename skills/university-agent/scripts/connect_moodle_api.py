#!/usr/bin/env python3
"""Issue and validate one Moodle Web Service token through the local secure form."""
from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.credentials import resolve_profile, save, site_key
from providers.moodle_api import MoodleWebServiceClient
from providers.moodle_api_credentials import DEFAULT_SERVICE, save_token
from providers.moodle_api_auth import normalize_moodle_domain


def issue_token(base_url: str, username: str, password: str, service: str, *, opener=urlopen) -> dict:
    domain = normalize_moodle_domain(base_url)
    request = Request(domain + "/login/token.php", data=urlencode({
        "username": username,
        "password": password,
        "service": service,
    }).encode("utf-8"), headers={
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Turtleneck/MoodleProvider",
    }, method="POST")
    try:
        with opener(request, timeout=30) as response:
            payload = json.loads(response.read(200_000).decode("utf-8", "replace"))
    except HTTPError as error:
        raise RuntimeError("학교가 Moodle 토큰 발급 요청을 거부했어요.") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("Moodle 토큰 발급 응답을 확인하지 못했어요.") from error
    if not isinstance(payload, dict) or not payload.get("token"):
        message = str(payload.get("error") or payload.get("message") or "토큰이 발급되지 않았어요.") if isinstance(payload, dict) else "토큰 응답 형식이 아니에요."
        lowered = message.casefold()
        if any(term in lowered for term in ("경로 전환", "web service", "웹서비스", "서비스", "권한", "permission")):
            raise RuntimeError(
                "TLS가 Moodle Web Service 토큰 발급을 허용하지 않았어요. "
                "학교 관리자에게 외부 서비스와 토큰 발급 권한을 확인해 달라고 요청해 주세요."
            )
        if any(term in lowered for term in ("아이디", "비밀번호", "로그인", "사용자", "invalidlogin")):
            raise RuntimeError("학교 로그인 정보가 확인되지 않아 토큰을 발급하지 못했어요.")
        raise RuntimeError("TLS에서 Moodle API 토큰을 발급하지 못했어요.")
    token = str(payload["token"])
    client = MoodleWebServiceClient(domain, token, opener=opener)
    info = client.site_info()
    if not isinstance(info, dict) or info.get("userid") is None:
        raise RuntimeError("발급된 토큰의 Moodle 사용자 정보를 확인하지 못했어요.")
    return {"domain": domain, "site": site_key(domain), "token": token, "info": info}


def connect(base_url: str, alias: str | None, service: str) -> dict:
    from providers.forms import TLS_CREDENTIALS_FORM, collect_browser
    # Explicit connection only: this is never reached by ordinary sync.
    values = collect_browser(TLS_CREDENTIALS_FORM, initial={"alias": alias or ""})
    username, password, selected = values["username"], values["password"], values.get("alias") or alias or "default"
    try:
        result = issue_token(base_url, username, password, service)
        save(username, password, selected, result["site"])
        save_token(result["token"], selected, result["site"], service=service,
                   user_id=f"moodle:{result['site']}:{result['info']['userid']}")
    finally:
        password = None
    return {"status": "READY", "site": result["site"], "alias": selected,
            "service": service, "userId": result["info"]["userid"],
            "passwordStoredSeparately": True, "tokenStoredSeparately": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Moodle Web Service 토큰을 안전하게 발급·저장")
    parser.add_argument("--base-url", default="https://tls.kku.ac.kr")
    parser.add_argument("--account-alias", default="default")
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    args = parser.parse_args()
    print(json.dumps(connect(args.base_url, args.account_alias, args.service), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
