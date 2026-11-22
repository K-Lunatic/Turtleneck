"""Compare small and bulk local replay workloads without contacting a school server."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
SCENARIOS = {
    "small": {"courses": 1, "files": 1, "mediaChunks": 2},
    "large": {"courses": 40, "files": 20, "mediaChunks": 1000},
}


def _import(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _median(rows: list[dict[str, object]]) -> dict[str, object]:
    return {key: statistics.median(row[key] for row in rows)
            for key in rows[0]
            if all(isinstance(row[key], (int, float)) and not isinstance(row[key], bool) for row in rows)}


def _study(repo: Path, files: int, samples: int) -> dict[str, object]:
    benchmark = _import(repo / "experiments/study-generation/benchmark.py", "scale_study_benchmark")
    rows = [benchmark.run(files) for _ in range(samples)]
    return {"samples": rows, "median": _median(rows), "aiLatencyMeasured": False}


def _tls(repo: Path, courses: int, samples: int) -> dict[str, object]:
    sys.path[:0] = [str(repo / "skills/university-agent/tests"), str(repo / "skills/university-agent/scripts"),
                    str(repo / "skills/university-agent")]
    from test_tls_optimization import fixture_pages, run_sync
    import sync_tls

    rows = []
    pages = fixture_pages(courses)
    for _ in range(samples):
        with tempfile.TemporaryDirectory(prefix="turtleneck-scale-tls-") as folder:
            seed = Path(folder) / "seed.db"
            run_sync(sync_tls, pages, seed, "--full", "--metadata-only")
            case = Path(folder) / "case.db"
            case.write_bytes(seed.read_bytes())
            started = time.perf_counter()
            metrics = run_sync(sync_tls, pages, case, "--ensure", "--metadata-only")
            metrics["elapsedMs"] = round((time.perf_counter() - started) * 1000, 3)
            rows.append({key: value for key, value in metrics.items()
                         if key in {"requests", "response_body_bytes", "elapsed_seconds", "elapsedMs"}})
    return {"samples": rows, "median": _median(rows), "fixtureOnly": True}


def _media(repo: Path, chunks: int, samples: int) -> dict[str, object]:
    sys.path[:0] = [str(repo / "skills/university-agent/tests"), str(repo / "skills/university-agent")]
    from test_lecture_audio import SOURCE, Session
    from providers.lecture_media import download_media, media_plan

    rows = []
    for _ in range(samples):
        session = Session()
        plan = media_plan(session, SOURCE)
        plan = {**plan, "chunks": (plan["chunks"] * ((chunks + 1) // 2))[:chunks],
                "sourceKey": f"scale-{chunks}"}
        with tempfile.TemporaryDirectory(prefix="turtleneck-scale-media-") as folder:
            target = Path(folder) / "media.bin"
            started = time.perf_counter()
            download_media(session, plan, target)
            rows.append({"chunks": chunks, "bytes": target.stat().st_size,
                         "requests": len(session.calls),
                         "elapsedMs": round((time.perf_counter() - started) * 1000, 3)})
    return {"samples": rows, "median": _median(rows), "fixtureOnly": True}


def run(repo: Path, samples: int = 3, scenarios: tuple[str, ...] = ("small", "large")) -> dict[str, object]:
    if samples < 1 or not set(scenarios) <= set(SCENARIOS):
        raise ValueError("samples must be positive and scenarios must be small/large")
    result: dict[str, object] = {
        "benchmarkVersion": 1,
        "run": {"startedAt": datetime.now(KST).isoformat(timespec="milliseconds"), "timezone": "Asia/Seoul",
                "samples": samples, "network": "disabled"},
        "environment": {"python": platform.python_version(), "os": platform.platform(),
                        "machine": platform.machine(), "logicalCores": os.cpu_count(),
                        "commit": _commit(repo)},
        "scenarios": {},
    }
    for name in scenarios:
        config = SCENARIOS[name]
        result["scenarios"][name] = {
            "config": config,
            "study": _study(repo, config["files"], samples),
            "tls": _tls(repo, config["courses"], samples),
            "media": _media(repo, config["mediaChunks"], samples),
        }
    result["run"]["finishedAt"] = datetime.now(KST).isoformat(timespec="milliseconds")
    return result


def _commit(repo: Path) -> str | None:
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--scenario", choices=tuple(SCENARIOS), action="append")
    args = parser.parse_args()
    result = run(args.repo.resolve(), args.samples, tuple(args.scenario or SCENARIOS))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: value["config"] for name, value in result["scenarios"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
