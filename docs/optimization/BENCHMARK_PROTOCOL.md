# 파트별 벤치마크 기준

터틀넥의 로컬 성능은 한 숫자로 합치지 않고 파트별로 측정한다. 각 실행 결과는 커밋,
운영체제, Python 버전, 머신, 논리 코어 수, 실행 시작·종료 시각(Asia/Seoul)을 JSON에 남긴다.

## 측정 파트

| 파트 | 역할 | 기준 지표 | 범위 |
| --- | --- | --- | --- |
| `study_pipeline` | 파일별 분석·문제은행·캐시 재사용 | cold/warm 로컬 처리 시간, 호출 수, 응답 바이트 | AI 추론 제외, 1개·4개 파일, 30문항 fixture |
| `study_storage` | 시험 분석 중간 상태 저장 | 세션 행·분리 파이프라인 행의 UTF-8 바이트 | 첫 추출 배치 직후, 4개 파일 fixture |
| `material_cache` | 분석 결과 병렬 조회 | 4개 worker의 40회 cache hit 중앙값 | 로컬 SQLite만 측정 |
| `lecture_media` | 미디어 조각 검증·순서 보존 | fixture 다운로드 시간·요청 수·바이트 | 2개 MPEG-TS 조각, 학교 접속 제외 |
| `tls_sync` | 변경 감지·부분 동기화 | 8과목 unchanged ensure 시간·HTTP 요청·본문량 | 재현 HTTP fixture, 실제 TLS 제외 |
| `local_asr` | 로컬 음성 전사 | 실제 모델이 있을 때만 전사 시간 | 모델·원본·GPU가 없으면 `not_measured` |

## 버전 비교

버전별 결과는 같은 fixture, 문항 수, 반복 횟수로 각각 실행한다. `environment.commit`을
기준으로 비교하며, 서로 다른 OS 결과는 합치지 않는다. 시간 감소율은
`(이전 중앙값 - 현재 중앙값) / 이전 중앙값`으로 계산하고, 호출 수·응답 바이트가 달라지면
기능 범위가 바뀐 비교로 표시한다.

```bash
python experiments/benchmarks/benchmark_parts.py \
  --repo /path/to/checkout \
  --output /tmp/turtleneck-benchmark.json \
  --samples 30
```

Windows와 macOS는 [.github/workflows/benchmark.yml](../../.github/workflows/benchmark.yml)에서
서로 다른 runner job으로 실행하고 결과 artifact도 분리한다. 이 workflow는 pull request와
수동 실행에만 연결해 일반 push 테스트 시간을 늘리지 않는다.

