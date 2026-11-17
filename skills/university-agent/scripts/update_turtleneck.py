#!/usr/bin/env python3
"""Check and safely update an installed Turtleneck package from the trusted repo."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError


REPO = "K-Lunatic/Turtleneck"
BRANCH = "turtleneck"
REMOTE_PLUGIN = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/plugin.json"
REMOTE_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
SOURCE_ARCHIVE_NAME = "turtleneck-source.zip"
SOURCE_CHECKSUM_NAME = "turtleneck-source.sha256"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60


def version_tuple(value: str) -> tuple[int, ...]:
    parts = str(value).lstrip("v").split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"지원하지 않는 버전 형식: {value}")
    return tuple(int(part) for part in parts)


def is_newer(remote: str, local: str) -> bool:
    return version_tuple(remote) > version_tuple(local)


def find_package_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / "plugin.json").is_file():
            return candidate
    return None


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def package_root() -> Path | None:
    root = find_package_root(skill_root())
    if root is not None:
        return root
    # Older local installs contain only skills/university-agent, not plugin.json.
    return skill_root() if (skill_root() / "SKILL.md").is_file() else None


def development_checkout(root: Path | None) -> bool:
    return bool(root and (root / ".git").exists())


def _read_plugin(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "turtleneck-updater/0.4"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def _verified_source_archive(remote_version: str) -> bytes:
    """Download only the tagged source asset whose published checksum matches."""
    release = json.loads(_fetch(REMOTE_RELEASE_API))
    tag = str(release.get("tag_name", "")).lstrip("v")
    if version_tuple(tag) != version_tuple(remote_version):
        raise ValueError("업데이트 버전과 릴리스 태그가 일치하지 않아요.")
    assets = {
        str(asset.get("name")): str(asset.get("browser_download_url"))
        for asset in release.get("assets", [])
        if isinstance(asset, dict) and asset.get("name") and asset.get("browser_download_url")
    }
    archive_url = assets.get(SOURCE_ARCHIVE_NAME)
    checksum_url = assets.get(SOURCE_CHECKSUM_NAME)
    if not archive_url or not checksum_url:
        raise ValueError("검증 가능한 업데이트 파일이 릴리스에 없어요.")
    archive = _fetch(archive_url)
    checksum_lines = _fetch(checksum_url).decode("utf-8", "strict").splitlines()
    expected = next((line.split()[0] for line in checksum_lines if SOURCE_ARCHIVE_NAME in line), "")
    actual = hashlib.sha256(archive).hexdigest()
    if len(expected) != 64 or expected.casefold() != actual:
        raise ValueError("업데이트 파일 체크섬이 일치하지 않아요.")
    return archive


def _cache_path() -> Path:
    return Path(os.environ.get("UNIVERSITY_AGENT_UPDATE_CACHE", Path.home() / ".university-agent" / "update-check.json"))


def _extract_archive(bundle: zipfile.ZipFile, target: Path) -> None:
    root = target.resolve()
    for member in bundle.infolist():
        destination = (root / member.filename).resolve()
        if destination != root and root not in destination.parents:
            raise ValueError("업데이트 압축 파일의 경로를 확인하지 못했어요.")
        bundle.extract(member, root)


def _recent_cache(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        checked = datetime.fromisoformat(value["checkedAt"])
        if (datetime.now(timezone.utc) - checked).total_seconds() < CHECK_INTERVAL_SECONDS:
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def check(*, force: bool = False) -> dict[str, str | bool]:
    root = package_root()
    if root is None:
        return {"status": "UNAVAILABLE", "message": "설치된 터틀넥 버전을 확인할 수 없어요."}
    local = _read_plugin(root / "plugin.json") if (root / "plugin.json").is_file() else {}
    local_version = str(local.get("version", "0.0.0"))
    cache = None if force else _recent_cache(_cache_path())
    if cache:
        remote_version = str(cache.get("remoteVersion", local_version))
    else:
        try:
            remote_version = str(json.loads(_fetch(REMOTE_PLUGIN))["version"])
        except (OSError, ValueError, KeyError, TypeError):
            return {"status": "UNAVAILABLE", "localVersion": local_version, "message": "새 버전을 확인하지 못했어요. 현재 버전으로 계속 사용할게요."}
        try:
            path = _cache_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"checkedAt": datetime.now(timezone.utc).isoformat(), "remoteVersion": remote_version}), encoding="utf-8")
        except OSError:
            pass
    try:
        newer = is_newer(remote_version, local_version)
    except ValueError:
        return {"status": "UNAVAILABLE", "localVersion": local_version, "message": "버전 정보를 읽지 못했어요."}
    return {"status": "UPDATE_AVAILABLE" if newer else "CURRENT", "localVersion": local_version, "remoteVersion": remote_version,
            "message": f"터틀넥 {remote_version} 버전이 있어요." if newer else f"터틀넥 {local_version} 버전이 최신이에요."}


def apply_update(*, force: bool = False) -> dict[str, str | bool]:
    installed_package = package_root()
    target = skill_root()
    if installed_package is None or development_checkout(installed_package):
        return {"status": "SKIPPED", "message": "개발 중인 Git 저장소는 자동으로 덮어쓰지 않아요. 최신 turtleneck 브랜치를 확인해 주세요."}
    state = check(force=force)
    if state.get("status") != "UPDATE_AVAILABLE":
        return state
    staging = None
    backup_dir = None
    staged_files: list[tuple[Path, Path]] = []
    moved_backups: list[tuple[Path, Path]] = []
    try:
        archive = _verified_source_archive(str(state["remoteVersion"]))
        with tempfile.TemporaryDirectory() as folder:
            archive_path = Path(folder) / "turtleneck.zip"
            archive_path.write_bytes(archive)
            with zipfile.ZipFile(archive_path) as bundle:
                _extract_archive(bundle, Path(folder))
            extracted = next(Path(folder).glob(f"{REPO.rsplit('/', 1)[1]}-*/skills/university-agent"), None)
            if extracted is None:
                raise ValueError("업데이트 파일 구조를 확인하지 못했어요.")
            staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
            staging.rmdir()
            shutil.copytree(extracted, staging)
            source_plugin = extracted.parents[1] / "plugin.json"
            if source_plugin.is_file():
                plugin_stage = Path(tempfile.mkstemp(prefix=".plugin.json.stage-", dir=installed_package)[1])
                shutil.copy2(source_plugin, plugin_stage)
                staged_files.append((plugin_stage, installed_package / "plugin.json"))
            source_claude = extracted.parents[1] / '.claude-plugin/plugin.json'
            if source_claude.is_file() and (installed_package / '.claude-plugin/plugin.json').is_file():
                claude_stage = Path(tempfile.mkstemp(prefix=".claude-plugin.json.stage-", dir=installed_package)[1])
                shutil.copy2(source_claude, claude_stage)
                staged_files.append((claude_stage, installed_package / '.claude-plugin/plugin.json'))
        backup_dir = Path(tempfile.mkdtemp(prefix=".turtleneck-update-backup-", dir=target.parent))
        os.replace(target, backup_dir / "skill")
        os.replace(staging, target)
        for staged, destination in staged_files:
            backup = backup_dir / f"file-{len(moved_backups)}"
            if destination.exists():
                os.replace(destination, backup)
                moved_backups.append((backup, destination))
            os.replace(staged, destination)
        shutil.rmtree(backup_dir, ignore_errors=True)
        backup_dir = None
        return {"status": "UPDATED", "message": f"터틀넥 {state['remoteVersion']} 버전으로 업데이트했어요."}
    except (OSError, ValueError, zipfile.BadZipFile, URLError):
        if backup_dir is not None:
            try:
                if target.exists():
                    shutil.rmtree(target)
                backup_skill = backup_dir / "skill"
                if backup_skill.exists():
                    os.replace(backup_skill, target)
                for backup, destination in reversed(moved_backups):
                    if destination.exists():
                        destination.unlink()
                    if backup.exists():
                        os.replace(backup, destination)
            except OSError:
                pass
            shutil.rmtree(backup_dir, ignore_errors=True)
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        for staged, _destination in staged_files:
            staged.unlink(missing_ok=True)
        return {"status": "FAILED", "message": "업데이트를 끝내지 못했어요. 설치본을 다시 확인해 주세요. 로그인·학습 데이터는 변경하지 않았어요."}


def main() -> int:
    parser = argparse.ArgumentParser(description="터틀넥 버전 확인 및 명시적 업데이트")
    parser.add_argument("--auto", action="store_true", help="새 버전만 확인합니다 (자동 덮어쓰기는 하지 않음)")
    parser.add_argument("--apply", action="store_true", help="확인된 새 버전을 명시적으로 적용")
    parser.add_argument("--force", action="store_true", help="캐시를 무시하고 버전 확인")
    args = parser.parse_args()
    if args.auto and args.apply:
        parser.error("--auto와 --apply는 함께 사용할 수 없습니다.")
    # Automatic startup checks must not replace executable code. Applying is an explicit action.
    result = apply_update(force=args.force) if args.apply else check(force=args.force)
    print(result["message"])
    return 0 if result["status"] not in {"FAILED", "UNAVAILABLE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
