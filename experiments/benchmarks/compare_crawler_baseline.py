"""Compare Turtleneck with a deliberately naive, no-cache Moodle crawler.

The baseline is not a competing product. It is a reproducible reference model:
after authentication it reads the course list, every course page, every visible
activity page, and every notice article on every run.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "skills" / "university-agent" / "tests"
SKILL = ROOT / "skills" / "university-agent"
SCRIPTS = SKILL / "scripts"
sys.path[:0] = [str(TESTS), str(SCRIPTS), str(SKILL)]

from providers.moodle_session import MoodleSession
from test_tls_optimization import fixture_pages, replay_opener, run_sync
import sync_tls


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href.replace("&amp;", "&"))


def _links(html: str, needle: str) -> list[str]:
    parser = _Links()
    parser.feed(html)
    return [href for href in parser.links if needle in href]


def naive_crawl(pages: dict[str, object], course_count: int) -> dict[str, object]:
    """Run the no-cache reference traversal against the deterministic fixture."""
    from providers.request_metrics import RequestMetrics

    # The fixture models the provider's normalized VOD viewer URL. A generic
    # browser crawler first opens the visible activity URL, so expose the same
    # fixture response at that URL without changing the measured scope.
    pages = dict(pages)
    for path, value in list(pages.items()):
        if "/mod/vod/viewer.php" in path:
            pages[path.replace("/mod/vod/viewer.php", "/mod/vod/view.php")] = value

    metrics = RequestMetrics()
    with replay_opener(pages):
        session = MoodleSession(metrics=metrics)
        session.logged_in = True
        session._request_limiter.gap = 0
        started = time.perf_counter()
        catalog = session.get("/local/ubion/user/")
        course_links = _links(catalog, "/course/view.php?id=")[:course_count]
        for course_link in course_links:
            course = session.get(course_link)
            activity_links = _links(course, "/mod/")
            for activity_link in activity_links:
                activity = session.get(activity_link)
                if "/mod/ubboard/view.php" in activity_link:
                    for article_link in _links(activity, "/mod/ubboard/article.php"):
                        session.get(article_link)
        result = metrics.snapshot()
    result["elapsedMs"] = round((time.perf_counter() - started) * 1000, 3)
    result["model"] = "naive_depth_first_no_cache"
    result["scope"] = "course list + every course + every activity + notice articles"
    return result


def _optimized_pair(course_count: int) -> dict[str, object]:
    pages = fixture_pages(course_count)
    with tempfile.TemporaryDirectory(prefix="turtleneck-baseline-") as folder:
        db = Path(folder) / "fixture.db"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            cold = run_sync(sync_tls, pages, db, "--full", "--metadata-only")
            warm = run_sync(sync_tls, pages, db, "--ensure", "--metadata-only")
    return {"cold": cold, "warm": warm}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--courses", type=int, default=8)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.courses < 1 or args.samples < 1:
        raise SystemExit("--courses와 --samples는 양수여야 해요.")
    baseline = [naive_crawl(fixture_pages(args.courses), args.courses) for _ in range(args.samples)]
    optimized = [_optimized_pair(args.courses) for _ in range(args.samples)]
    result = {
        "benchmark": "naive-crawler-vs-turtleneck",
        "definition": "baseline re-reads all visible course/activity/notice pages; Turtleneck reuses unchanged local state",
        "fixture": {"courses": args.courses, "samples": args.samples, "authenticated": True, "filesDownloaded": False},
        "baseline": baseline,
        "turtleneck": optimized,
        "limits": [
            "offline replay fixture; not a live school-server measurement",
            "HTTP body totals exclude headers, TLS/TCP overhead, browser cache and server CPU/DB load",
            "cold runs compare collection scope; warm runs compare repeated unchanged checks",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "baselineRequestsMedian": sorted(row["requests"] for row in baseline)[len(baseline) // 2],
        "turtleneckColdRequests": [row["cold"]["requests"] for row in optimized],
        "turtleneckWarmRequests": [row["warm"]["requests"] for row in optimized],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
