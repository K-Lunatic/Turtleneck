#!/usr/bin/env python3
"""Detect supported local agents and optionally install Turtleneck through their official CLIs."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = 'K-Lunatic/Turtleneck'
SKILL_URL = 'https://github.com/K-Lunatic/Turtleneck.git'
SOURCE_REF_API = 'https://api.github.com/repos/K-Lunatic/Turtleneck/commits/turtleneck'
ZIP_URL = 'https://github.com/K-Lunatic/Turtleneck/archive/{ref}.zip'
MAX_SOURCE_BYTES = 50 * 1024 * 1024

INSTALLERS = {
    'codex': {
        'command': 'codex',
        'install': [['codex', 'plugin', 'marketplace', 'add', REPO, '--ref', 'turtleneck'],
                    ['codex', 'plugin', 'add', 'university-agent@turtleneck']],
        'verify': ['codex', 'plugin', 'list'],
    },
    'claude': {
        'command': 'claude',
        'install': [['claude', 'plugin', 'marketplace', 'add', REPO],
                    ['claude', 'plugin', 'install', 'university-agent@turtleneck']],
        'verify': ['claude', 'plugin', 'list'],
    },
    'gemini': {
        'command': 'gemini',
        'install': [['gemini', 'skills', 'install', SKILL_URL, '--path', 'skills/university-agent', '--scope', 'user']],
        'verify': ['gemini', 'skills', 'list', '--all'],
    },
}


def detect() -> dict:
    return {
        'python': bool(shutil.which('python3') or shutil.which('python') or shutil.which('py')),
        'agents': {name: {'installed': bool(shutil.which(item['command']))}
                   for name, item in INSTALLERS.items()},
    }


def _run(command: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    lines = (result.stdout or result.stderr or '').strip().splitlines()
    return result.returncode == 0, lines[-1] if lines else ''


def _local_source() -> Path | None:
    root = Path(__file__).resolve().parents[3]
    return root if (root / 'plugin.json').is_file() else None


def _pinned_archive_url(metadata: dict) -> str:
    ref = str(metadata.get('sha', '')).lower()
    if len(ref) != 40 or any(char not in '0123456789abcdef' for char in ref):
        raise ValueError('터틀넥 원본 커밋을 확인하지 못했어요.')
    return ZIP_URL.format(ref=ref)


def _download_source() -> tuple[tempfile.TemporaryDirectory, Path]:
    temp = tempfile.TemporaryDirectory(prefix='turtleneck-install-')
    archive = Path(temp.name) / 'turtleneck.zip'
    try:
        request = urllib.request.Request(SOURCE_REF_API, headers={'Accept': 'application/vnd.github+json',
                                                                    'User-Agent': 'TurtleneckInstaller/1.0'})
        with urllib.request.urlopen(request, timeout=20) as response:
            archive_url = _pinned_archive_url(json.load(response))
        request = urllib.request.Request(archive_url, headers={'User-Agent': 'TurtleneckInstaller/1.0'})
        with urllib.request.urlopen(request, timeout=30) as response, archive.open('wb') as output:
            length = response.headers.get('Content-Length')
            if length and int(length) > MAX_SOURCE_BYTES:
                raise ValueError('터틀넥 설치 파일이 예상보다 커서 중단했어요.')
            remaining = MAX_SOURCE_BYTES
            while remaining:
                chunk = response.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                output.write(chunk)
                remaining -= len(chunk)
            if remaining == 0 and response.read(1):
                raise ValueError('터틀넥 설치 파일이 예상보다 커서 중단했어요.')
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.namelist()
            if any(Path(member).is_absolute() or '..' in Path(member).parts for member in members):
                raise ValueError('설치 파일의 경로가 안전하지 않아 중단했어요.')
            bundle.extractall(temp.name)
        roots = [Path(temp.name) / member.rstrip('/') for member in members
                 if member.count('/') == 1 and member.endswith('/')]
        root = next((candidate for candidate in roots if (candidate / 'plugin.json').is_file()), None)
        if root is None:
            raise ValueError('터틀넥 설치 파일의 구조를 확인하지 못했어요.')
        return temp, root
    except Exception:
        temp.cleanup()
        raise


def _source_without_git() -> tuple[tempfile.TemporaryDirectory | None, Path | None, str | None]:
    local = _local_source()
    if local:
        return None, local, 'local ZIP/폴더 경로'
    try:
        temp, source = _download_source()
        return temp, source, 'GitHub ZIP'
    except (OSError, ValueError, zipfile.BadZipFile, urllib.error.URLError) as error:
        return None, None, str(error)


def _commands(agent: str, source: Path | None) -> list[list[str]]:
    if source is None:
        return INSTALLERS[agent]['install']
    source = str(source)
    if agent == 'codex':
        return [['codex', 'plugin', 'marketplace', 'add', source],
                ['codex', 'plugin', 'add', 'university-agent@turtleneck']]
    if agent == 'claude':
        return [['claude', 'plugin', 'marketplace', 'add', source],
                ['claude', 'plugin', 'install', 'university-agent@turtleneck']]
    return [['gemini', 'skills', 'install', str(Path(source) / 'skills' / 'university-agent'), '--scope', 'user']]


def install(agent: str) -> dict:
    info = INSTALLERS[agent]
    if not shutil.which(info['command']):
        return {'agent': agent, 'status': 'UNAVAILABLE', 'message': f'{info["command"]}를 찾지 못했어요.'}
    temporary = None
    source = None
    mode = None
    if not shutil.which('git'):
        temporary, source, mode = _source_without_git()
        if source is None:
            return {'agent': agent, 'status': 'FAILED',
                    'message': f'Git이 없고 ZIP 설치도 준비하지 못했어요: {mode}'}
    try:
        for command in _commands(agent, source):
            ok, message = _run(command)
            if not ok:
                return {'agent': agent, 'status': 'FAILED', 'message': message or '공식 설치 명령이 실패했어요.'}
        ok, message = _run(info['verify'])
        return {'agent': agent, 'status': 'READY' if ok else 'VERIFY_FAILED',
                'message': message or ('설치와 확인을 마쳤어요.' if ok else '설치 후 목록 확인에 실패했어요.'),
                **({'source': mode} if mode else {})}
    finally:
        if temporary:
            temporary.cleanup()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='터틀넥 공식 설치 환경 확인 및 명시적 등록')
    parser.add_argument('--agent', choices=tuple(INSTALLERS), action='append', help='등록할 에이전트; 생략하면 설치된 에이전트')
    parser.add_argument('--apply', action='store_true', help='공식 설치 명령을 실제로 실행')
    args = parser.parse_args(argv)
    state = detect()
    selected = args.agent or [name for name, item in state['agents'].items() if item['installed']]
    if not args.apply:
        print(json.dumps({'status': 'CHECKED', 'environment': state, 'selected': selected,
                          'message': '설치를 진행하려면 사용자가 --apply를 선택해야 해요.'}, ensure_ascii=False))
        return 0
    if not selected:
        print(json.dumps({
            'status': 'UNAVAILABLE',
            'environment': state,
            'results': [],
            'message': '지원되는 에이전트를 찾지 못했어요. Codex·Claude Code·Gemini를 먼저 설치해 주세요.',
        }, ensure_ascii=False))
        return 1
    results = [install(name) for name in selected]
    failed = any(item['status'] != 'READY' for item in results)
    print(json.dumps({'status': 'FAILED' if failed else 'READY', 'environment': state, 'results': results}, ensure_ascii=False))
    if not failed:
        print('설치가 끝났어요. 도움이 됐다면 GitHub에서 별 하나만 눌러 주세요: https://github.com/K-Lunatic/Turtleneck')
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
