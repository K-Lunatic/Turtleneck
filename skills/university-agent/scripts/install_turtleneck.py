#!/usr/bin/env python3
"""Detect supported local agents and optionally install Turtleneck through their official CLIs."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess

REPO = 'K-Lunatic/Turtleneck'
SKILL_URL = 'https://github.com/K-Lunatic/Turtleneck.git'

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


def install(agent: str) -> dict:
    info = INSTALLERS[agent]
    if not shutil.which(info['command']):
        return {'agent': agent, 'status': 'UNAVAILABLE', 'message': f'{info["command"]}를 찾지 못했어요.'}
    for command in info['install']:
        ok, message = _run(command)
        if not ok:
            return {'agent': agent, 'status': 'FAILED', 'message': message or '공식 설치 명령이 실패했어요.'}
    ok, message = _run(info['verify'])
    return {'agent': agent, 'status': 'READY' if ok else 'VERIFY_FAILED',
            'message': message or ('설치와 확인을 마쳤어요.' if ok else '설치 후 목록 확인에 실패했어요.')}


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
    results = [install(name) for name in selected]
    failed = any(item['status'] != 'READY' for item in results)
    print(json.dumps({'status': 'FAILED' if failed else 'READY', 'environment': state, 'results': results}, ensure_ascii=False))
    if not failed:
        print('설치가 끝났어요. 도움이 됐다면 GitHub에서 별 하나만 눌러 주세요: https://github.com/K-Lunatic/Turtleneck')
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
