"""Canvas connection flow with a local secure form."""
from __future__ import annotations

import subprocess

from providers.canvas_credentials import load_token, save_token
from providers.canvas_provider import CanvasApiError, CanvasClient, CanvasProvider, normalize_canvas_domain
from providers.credentials import load_active_alias, normalize_alias, site_key
from providers.forms import CANVAS_CONNECTION_FORM, collect_secure


def authenticated_canvas(
    domain: str | None = None,
    alias: str | None = None,
    *,
    force_input: bool = False,
) -> tuple[str, CanvasProvider]:
    """Reuse a protected token or collect a new one, then validate it."""
    alias = normalize_alias(alias)
    if domain and not force_input:
        normalized = normalize_canvas_domain(domain)
        try:
            token = load_token(alias, site_key(normalized))
            provider = CanvasProvider(CanvasClient(normalized, token))
            provider.get_user()
            return alias, provider
        except CanvasApiError as error:
            if error.status not in (401, 403, 404):
                raise
        except (OSError, KeyError, ValueError, subprocess.CalledProcessError):
            pass

    values = collect_secure(CANVAS_CONNECTION_FORM, initial={
        "alias": alias,
        "domain": domain or "",
    })
    normalized = normalize_canvas_domain(values["domain"])
    selected = normalize_alias(values.get("alias") or alias or load_active_alias(site_key(normalized)))
    token = values["token"]
    provider = CanvasProvider(CanvasClient(normalized, token))
    user = provider.get_user()
    if not isinstance(user, dict) or user.get("id") is None:
        raise ValueError("Canvas 로그인을 확인하지 못했어요.")
    save_token(token, selected, site_key(normalized), user_id=f"canvas:{site_key(normalized)}:{user['id']}")
    return selected, provider
