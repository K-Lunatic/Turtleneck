#!/usr/bin/env python3
"""Small frozen-runtime dispatcher used by the no-install desktop bundle."""
from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path


def package_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[1]


def run_script(relative: str, args: list[str]) -> int:
    root = package_root().resolve()
    script = (root / relative).resolve()
    if root not in script.parents or not script.is_file():
        raise SystemExit("터틀넥 실행 파일에 필요한 구성요소를 찾지 못했어요.")
    skill_root = root / "skills" / "university-agent"
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(skill_root))
    sys.argv = [str(script), *args]
    runpy.run_path(str(script), run_name="__main__")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] in {"--version", "-V"}:
        try:
            version = json.loads((package_root() / "plugin.json").read_text(encoding="utf-8"))["version"]
        except (OSError, ValueError, KeyError):
            version = "unknown"
        print(f"turtleneck {version}")
        return 0
    if args and args[0].endswith(".py"):
        return run_script(args[0], args[1:])
    return run_script("server/local.py", args)


if __name__ == "__main__":
    raise SystemExit(main())
