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

## 서버 트래픽 비교

로컬 처리 시간만으로는 학교 서버 부담을 판단할 수 없다. 같은 작업 단위의 실제 브라우저 사용과
터틀넥 실행을 각각 기록해 요청 수, 요청·응답 본문량, 리디렉션·실패·재시도, MIME별 요청 수를
비교한다.

사람 기준값은 브라우저에서 같은 시나리오를 수행해 내보낸 HAR로 만든다. 로그인·초기 준비는
`academic_sync`, `open_one_course`, `download_one_file`, `watch_one_lecture` 같은 작업과 분리하고,
스킬도 같은 범위의 계측 결과만 비교한다. HAR 요약기는 URL·쿼리·헤더·쿠키·요청 본문·응답 본문을
저장하지 않으며, 크기와 집계값만 남긴다.

```bash
python experiments/benchmarks/traffic_profile.py \
  --har /path/to/exported.har \
  --scenario academic_sync \
  --skill-json /tmp/turtleneck-benchmark.json \
  --output /tmp/turtleneck-traffic-compare.json
```

현재 저장소에는 스킬 측정 도구와 개인정보 제거 요약기는 있지만 실제 학생 브라우저의 HAR가 아직
등록되어 있지 않다. 따라서 HAR를 받기 전에는 “일반 사용자보다 몇 % 적다”라고 주장하지 않는다.
본문량은 헤더·TLS·TCP·압축 전송 조건을 모두 포함하지 않는 하한이므로 회선 전체 사용량이나 학교
내부 CPU·DB 부하와 동일한 값으로 해석하지 않는다.

### 일반 크롤러 기준선

브라우저 HAR와 별개로 반복 조회 정책의 효과를 확인할 때는 `experiments/benchmarks/compare_crawler_baseline.py`를
사용한다. 기준선은 특정 라이브러리나 서비스의 성능값이 아니라, 캐시와 변경 감지를 사용하지 않는
단순 depth-first 크롤러의 명시적 모델이다. 인증 이후 매 실행마다 수강목록, 모든 과목 페이지,
모든 활동 페이지, 공지 본문을 다시 요청한다. 파일 원본과 동영상은 비교 범위에서 제외한다.

```bash
python experiments/benchmarks/compare_crawler_baseline.py \
  --courses 8 --samples 3 --output /tmp/crawler-baseline.json
```

cold 결과는 첫 수집 비용 비교로만 보고, warm 결과에서 같은 범위를 반복 조회할 때의 차이를 본다.
기준선보다 적은 요청이 나와도 실제 학생 브라우저보다 적다는 뜻은 아니다. 실제 사용자 비교는
동일 시나리오 HAR가 확보된 뒤에만 별도로 판정한다.

