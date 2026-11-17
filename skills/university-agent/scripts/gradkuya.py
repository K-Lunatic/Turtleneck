#!/usr/bin/env python3
"""Local GradKUya entry point shared by Codex and Claude."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features import gradkuya
from features.secret_boundary import redact_output
from storage.private_files import atomic_write_text


def add_arguments(parser):
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--status', action='store_true')
    group.add_argument('--input', type=Path, help='작업·성적·시간표 조건을 담은 JSON')
    group.add_argument('--transcript', type=Path, help='사용자가 선택한 성적표 PDF 또는 TXT')
    parser.add_argument('--output', type=Path, help='결과를 비공개 로컬 JSON으로 저장')


def execute(args) -> dict:
    try:
        if args.status:
            result = gradkuya.run({'action': 'status'})
        elif args.transcript:
            result = gradkuya.analyze_file(args.transcript)
        else:
            if not args.input.is_file() or args.input.stat().st_size > gradkuya.MAX_INPUT:
                raise ValueError('입력은 4MB 이하의 JSON 파일이어야 해요.')
            request = json.loads(args.input.read_text(encoding='utf-8-sig'))
            if not isinstance(request, dict):
                raise ValueError('작업 입력은 JSON 객체여야 해요.')
            result = gradkuya.run(request)
        result = redact_output(result)
        if args.output:
            atomic_write_text(args.output, json.dumps(result, ensure_ascii=False))
        return {'toolCalls': ['gradkuya'], **result}
    except (OSError, ValueError, RuntimeError) as error:
        return {'toolCalls': ['gradkuya'], 'status': 'ERROR',
                'error': {'code': 'GRADKUYA_FAILED', 'message': str(error)}, 'answer': str(error)}


def main():
    parser = argparse.ArgumentParser(description='로컬 성적·졸업요건·시간표 계산')
    add_arguments(parser)
    result = redact_output(execute(parser.parse_args()))
    print(json.dumps(result, ensure_ascii=False))
    return int('error' in result)


if __name__ == '__main__':
    raise SystemExit(main())
