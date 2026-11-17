"""KKU TLS-only routing and document policy.

Keep observed KKU paths here so the generic Moodle provider never guesses them
for another school.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlsplit

from providers.moodle_session import check_download_origin


HOST = "tls.kku.ac.kr"
COURSE_PATHS = ("/local/ubion/user/", "/my/", "/course/index.php")
AUTONOMOUS_COURSE_PATH = "/local/ubeclass/my.php"


def is_kku(base_url: str) -> bool:
    return (urlsplit(base_url).hostname or "").casefold() == HOST


def permitted_download_url(viewer_url: str) -> str:
    """Map only an observed KKU ubdoc viewer to its download endpoint."""
    check_download_origin(viewer_url, HOST)
    parts = urlsplit(viewer_url)
    query = parse_qs(parts.query, keep_blank_values=True)
    if (parts.path != "/local/ubdoc/" or parts.fragment or
        set(query) != {"id", "tp", "pg"} or query["tp"] != ["m"] or
        query["pg"] != ["ubfile"] or len(query["id"]) != 1 or
        not re.fullmatch(r"[1-9][0-9]*", query["id"][0])):
        raise ValueError("자료의 원래 주소를 확인하지 못해 가져오지 않았어요.")
    return "https://tls.kku.ac.kr/local/ubdoc/download.php?" + urlencode({
        "id": query["id"][0], "tp": "m", "pg": "ubfile"})
