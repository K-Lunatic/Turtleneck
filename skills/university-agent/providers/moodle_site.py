"""Small site-module registry shared by standard Moodle and KKU TLS."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from providers.moodle_kku import (
    AUTONOMOUS_COURSE_PATH,
    COURSE_PATHS,
    HOST as KKU_HOST,
)


@dataclass(frozen=True)
class MoodleSiteModule:
    key: str
    source: str
    host: str
    course_paths: tuple[str, ...]
    autonomous_course_path: str | None = None
    custom_viewers: bool = False

    @property
    def origin(self) -> str:
        return f"https://{self.host}"

    def is_standard_resource_view(self, path: str) -> bool:
        return not self.custom_viewers and path == "/mod/resource/view.php"

    def is_kku_resource_view(self, path: str) -> bool:
        return self.custom_viewers and path == "/mod/ubfile/view.php"

    def is_standard_file(self, path: str) -> bool:
        return not self.custom_viewers and path.startswith("/pluginfile.php/")

    def is_custom_document(self, path: str) -> bool:
        return self.custom_viewers and path in (
            "/local/ubdoc/", "/mod/ubfile/viewer.php")


STANDARD_MOODLE = MoodleSiteModule(
    key="standard_moodle",
    source="moodle",
    host="",
    course_paths=("/my/", "/course/index.php"),
)

KKU_TLS = MoodleSiteModule(
    key="kku_tls",
    source="tls",
    host=KKU_HOST,
    course_paths=COURSE_PATHS,
    autonomous_course_path=AUTONOMOUS_COURSE_PATH,
    custom_viewers=True,
)


def module_for(base_url: str) -> MoodleSiteModule:
    """Select only a known site module; unknown hosts use standard Moodle."""
    host = (urlsplit(base_url).hostname or "").casefold()
    if host == KKU_HOST:
        return KKU_TLS
    return MoodleSiteModule(
        key=STANDARD_MOODLE.key,
        source=STANDARD_MOODLE.source,
        host=host,
        course_paths=STANDARD_MOODLE.course_paths,
    )
