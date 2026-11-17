"""Invoke the bundled GradKUya calculation engine using explicit local inputs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ENGINE = Path(__file__).resolve().parents[1] / 'integrations' / 'gradkuya' / 'run.mjs'
MAX_INPUT = 4 * 1024 * 1024


def run(request: dict) -> dict:
    node = shutil.which('node')
    if not node:
        raise ValueError('GradKUya 계산에는 Node.js 22 이상이 필요해요. 설치 후 같은 요청을 이어갈 수 있어요.')
    payload = json.dumps(request, ensure_ascii=False, allow_nan=False)
    if len(payload.encode('utf-8')) > MAX_INPUT:
        raise ValueError('GradKUya 입력은 4MB 이하여야 해요.')
    # Pass only process essentials, never the parent's credential configuration.
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL'}}
    try:
        result = subprocess.run([node, str(ENGINE)], input=payload, capture_output=True,
                                text=True, encoding='utf-8', timeout=45, env=environment)
        response = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        raise ValueError('시간표 계산이 오래 걸려 멈췄어요. 후보 과목·분반을 줄여 다시 요청해 주세요.') from None
    except (OSError, ValueError):
        raise ValueError('GradKUya 실행기를 시작하지 못했어요. Node.js 22 이상과 설치 파일을 확인해 주세요.') from None
    if not isinstance(response, dict) or response.get('status') != 'READY' or result.returncode:
        message = response.get('error', {}).get('message', 'GradKUya 계산에 실패했어요.') if isinstance(response, dict) else 'GradKUya 응답 형식을 확인하지 못했어요.'
        raise ValueError(message)
    return response


def analyze_file(path: Path) -> dict:
    path = path.expanduser().resolve(strict=True)
    if not path.is_file() or path.stat().st_size > 10_000_000:
        raise ValueError('성적표는 10MB 이하의 일반 PDF·TXT 파일로 골라 주세요.')
    if path.suffix.lower() == '.pdf':
        from features.study_materials import _pdf_sections
        with tempfile.TemporaryDirectory(prefix='turtleneck-transcript-') as folder:
            # Reuse the portable extractor without leaving a transcript cache beside the PDF.
            sections = _pdf_sections([path], ENGINE.parents[2] / 'scripts' / 'extract_pdf.swift', Path(folder))
            text = '\n'.join(section['text'] for section in sections[str(path)])
    elif path.suffix.lower() == '.txt':
        text = path.read_text(encoding='utf-8-sig')
    else:
        raise ValueError('성적표는 PDF 또는 UTF-8 TXT로 골라 주세요.')
    return run({'action': 'transcript', 'text': text})
