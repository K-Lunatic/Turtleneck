"""Summarize a browser HAR without retaining URLs, cookies, headers or bodies."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import platform
from zoneinfo import ZoneInfo


KST = ZoneInfo('Asia/Seoul')


def _number(value):
    return value if isinstance(value, (int, float)) and value >= 0 else 0


def summarize_har(payload, scenario):
    entries = payload.get('log', {}).get('entries', []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        raise ValueError('HAR entries가 목록이 아니에요.')
    requests = response_bytes = request_bytes = redirects = failures = 0
    by_kind = {'document': 0, 'data': 0, 'media': 0, 'image': 0, 'other': 0}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        request, response = entry.get('request', {}), entry.get('response', {})
        if not isinstance(request, dict) or not isinstance(response, dict):
            continue
        requests += 1
        request_bytes += _number(request.get('bodySize'))
        content = response.get('content', {})
        body_size = response.get('bodySize')
        response_bytes += _number(body_size if isinstance(body_size, (int, float)) and body_size >= 0
                                  else content.get('size') if isinstance(content, dict) else 0)
        status = response.get('status')
        if isinstance(status, int) and 300 <= status < 400:
            redirects += 1
        if isinstance(status, int) and status >= 400:
            failures += 1
        mime = str(content.get('mimeType', '')).lower() if isinstance(content, dict) else ''
        kind = 'media' if mime.startswith(('video/', 'audio/')) else 'image' if mime.startswith('image/') else \
            'document' if mime.startswith(('text/html', 'application/pdf', 'application/vnd')) else \
            'data' if mime.startswith(('application/json', 'text/')) else 'other'
        by_kind[kind] += 1
    return {
        'source': 'sanitized_har', 'scenario': scenario, 'capturedAt': payload.get('log', {}).get('startedDateTime'),
        'processedAt': datetime.now(KST).isoformat(timespec='milliseconds'), 'timezone': 'Asia/Seoul',
        'environment': {'os': platform.platform(), 'python': platform.python_version()},
        'requests': requests, 'redirects': redirects, 'failures': failures,
        'requestBodyBytes': request_bytes, 'responseBodyBytes': response_bytes,
        'bodyBytesLowerBound': request_bytes + response_bytes, 'requestsByKind': by_kind,
        'privacy': 'URLs, query strings, headers, cookies, post bodies and response bodies were not retained.',
        'limits': 'HAR body sizes exclude TLS/TCP/header overhead when the browser did not record it.',
    }


def _skill_metrics(payload, scenario):
    if payload.get('scenario') == scenario and 'requests' in payload:
        return payload
    if payload.get('results', {}).get('tls_sync', {}).get('median'):
        metrics = payload['results']['tls_sync']['median']
    elif payload.get('tls_sync', {}).get('median'):
        metrics = payload['tls_sync']['median']
    else:
        raise ValueError('TLS 스킬 계측 결과를 찾지 못했어요.')
    statuses = metrics.get('statuses', {})
    return {'source': 'skill_request_metrics', 'scenario': scenario,
            'requests': metrics.get('requests'), 'redirects': sum(int(value) for key, value in statuses.items()
                                                                  if key.isdigit() and 300 <= int(key) < 400),
            'failures': sum(int(value) for key, value in statuses.items()
                            if key == 'transport_error' or (key.isdigit() and int(key) >= 400)),
            'requestBodyBytes': metrics.get('request_body_bytes', 0),
            'responseBodyBytes': metrics.get('response_body_bytes'),
            'bodyBytesLowerBound': metrics.get('request_body_bytes', 0) + (metrics.get('response_body_bytes') or 0),
            'requestsByKind': metrics.get('requests_by_kind', {}),
            'limits': '스킬 계측은 응답 본문량 중심이며 요청 헤더·TLS/TCP 오버헤드는 제외합니다.'}


def compare(skill, user):
    if skill.get('scenario') != user.get('scenario'):
        raise ValueError('같은 시나리오끼리만 트래픽을 비교할 수 있어요.')
    result = {'scenario': skill['scenario'], 'skill': skill, 'user': user, 'comparison': {}}
    for key in ('requests', 'redirects', 'failures', 'requestBodyBytes', 'responseBodyBytes', 'bodyBytesLowerBound'):
        left, right = skill.get(key), user.get(key)
        result['comparison'][key] = {'skill': left, 'user': right,
                                     'userVsSkillPercent': round((right - left) / left * 100, 2)
                                     if isinstance(left, (int, float)) and left else None}
    result['comparison']['interpretation'] = '실제 회선 총량이 아니라 기록된 HTTP 본문·요청 크기의 하한 비교입니다.'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--har', type=Path, required=True)
    parser.add_argument('--scenario', required=True, help='예: academic_sync 또는 watch_one_lecture')
    parser.add_argument('--skill-json', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    user = summarize_har(json.loads(args.har.read_text(encoding='utf-8')), args.scenario)
    result = user if not args.skill_json else compare(
        _skill_metrics(json.loads(args.skill_json.read_text(encoding='utf-8')), args.scenario), user)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'scenario': args.scenario, 'requests': user['requests'],
                      'responseBodyBytes': user['responseBodyBytes'], 'compared': bool(args.skill_json)},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
