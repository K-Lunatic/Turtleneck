# Rust 부분 채택 후속 기록

작성일: 2026-11-20 · 운영 경로 부분 적용

## 결론과 변경한 기준

전체 동기화의 20% 개선만으로 부분 전환까지 막던 1차 기준을 분리했다. **활동 파서와
섹션 개요 파서는 부분 채택**, **개념 우선순위 계산의 현재 Rust 경로는 미채택**이다.
내부 웹의 실제 시험 상태 API와 프로파일도 비교했다. Rust 웹 서버를 새로 만든 것은 아니다.

모듈은 중간/큰 입력 모두에서 호출·직렬화 비용을 포함해 중앙값 20% 이상 빨라지고, 95%
쌍별 반복 구간이 개선 방향이며 출력이 같아야 한다. 해당 전체 흐름은 중앙값과 95% 구간이
5% 이상 악화되지 않아야 한다. 기존 기능 회귀와 실험 검사도 통과해야 한다. 이 조건은
[PARTIAL_PLAN.md](../../../experiments/rust-core/PARTIAL_PLAN.md)에 정리했다.

활동·개요 파서는 일반 `sync_tls.py` 동기화 경로에 선택적으로 적용했다. Rust 설치·라이브러리가
없거나 ABI가 맞지 않으면 같은 실행에서 기존 Python 파서로 돌아간다. 개념 순위화와 전체 앱
재작성은 승인하지 않았다. [partial-decision.json](../../../experiments/rust-core/results/partial-decision.json)이
모듈별 판정을 담고 있다.

## 파서와 지문 계산

Release Rust, 같은 입력, 30쌍 교대 순서 측정이다. Rust 시간은 UTF-8·FFI·Rust 계산·JSON
복원·Python fallback까지 포함한다. 준비·복사·결과 확인은 타이머 밖에서 수행했다.

| 모듈/입력 | Python | Rust 경로 | 중앙값 시간 단축 |
| --- | ---: | ---: | ---: |
| 활동 100개 | 1.350 ms | 0.266 ms | 80.28% |
| 활동 1,000개 | 13.310 ms | 2.641 ms | 80.16% |
| 섹션 개요 100개 | 2.849 ms | 0.316 ms | 88.92% |
| 섹션 개요 1,000개 | 28.296 ms | 3.068 ms | 89.16% |
| 실제 9과목 전체 지문 계산 | 79.768 ms | 27.013 ms | 66.14% |

실제 9과목에서 개요 10개를 추출했고 전후 값이 같았다. 실제 페이지 fallback은 0개다.
전체 지문은 활동 추출·섹션 개요·JSON·해시 계산을 포함한 로컬 단계이며 실제 HTTP 시간을
줄였다는 의미는 아니다. 실제 HTML은 메모리에서만 사용했고 저장하지 않았다. 인증·준비
15회 요청은 이 타이머에서 제외했다.

개요 파서는 숨김·활동 내용 제외, 잘못 중첩된 태그의 복구, Unicode 글자 수, ID의 CR/LF,
분할 입력을 기존 Python과 맞췄다. URL/ID의 원래 바이트를 바꾸거나 권한 필터를 옮기지 않았다.

## 전체 동기화 비악화 확인

8과목 고정 HTTP 응답과 동일한 초기 DB를 사용했다. 전후 학교 요청 종류·수와 저장된 학업
정보가 같았다. 네트워크 지연은 없는 재현이며, 학교 서버 부하 감소율로 해석하지 않는다.

| 전체 재현 흐름 | Python | 활동+개요 Rust | 중앙값 단축 | 95% 단축 구간 |
| --- | ---: | ---: | ---: | ---: |
| 변경 없는 목록 확인 | 214.735 ms | 209.875 ms | 2.26% | [1.478%, 2.916%] |
| 전체 메타데이터 수집 | 1,144.236 ms | 1,136.586 ms | 0.67% | [-0.035%, 1.509%] |

전체 수집의 구간에는 0이 있어 확실한 전체 가속으로 주장하지 않는다. 모듈의 뚜렷한 개선과
전체 흐름의 비악화를 근거로 부분 채택했다. 통신·인증·요청 간격·DB 처리 비용은 남는다.

## 개념 분류·우선순위 계산 검토

현재 `build_insights`는 저장 분석과 학습 이력을 읽고, 자료 권한·과목·사용자 근거를 걸러
개념별 중요도/취약도를 합산하고 정렬한다. 호스트 AI가 맡는 의미 분류·문항 생성 시간과는
다르다. 이번에는 이 중 마지막 점수·정렬을 순수 함수 `_rank_bucket`으로 분리했다.
기본 Python 동작은 같으며 권한·근거 필터와 DB 조회는 Python에 남겼다.

| 개념 우선순위 후보 | Python | Rust+JSON/FFI | 판정 |
| --- | ---: | ---: | --- |
| 개념 100개 점수·정렬 | 0.118 ms | 0.475 ms | 느려짐 |
| 개념 1,000개 점수·정렬 | 1.295 ms | 4.134 ms | 약 3.19배 시간 |
| SQLite부터 개념 100개 조회 | 0.894 ms | 1.274 ms | 42.40% 증가 |
| SQLite부터 개념 1,000개 조회 | 4.838 ms | 7.415 ms | 53.26% 증가 |

출력·근거 순서·반올림·오류 결과는 같았다. Python의 ties-to-even 반올림과 선택되지 않은
개념의 잘못된 값도 검증했다. **현재 경계의 JSON 왕복 비용이 이득보다 커서 개념 Rust
경로는 런처에서 제외했다.** Rust로 전체 개념 처리가 항상 느리다는 결론은 아니다.
향후 집계/JSON 읽기를 포함한 더 큰 단위나 다른 바인딩을 검토하려면 별도 비교가 필요하다.

한 번의 cProfile에서는 `_add`, `_rank_bucket`, JSON 읽기가 주요 후보로 잡혔다. 프로파일
시간에는 계측 오버헤드가 있으므로 위 반복 중앙값과 섞거나 CPU 비율로 일반화하지 않는다.

## 내부 웹 API 검토

기존 `ThreadingHTTPServer`와 실제 `StudySession`/SQLite를 사용했다. 격리된 6문항 활성
시험의 `/api/exam`을 루프백 HTTP로 읽었고, 시험 시각을 고정해 동일 상태를 비교했다.
두 backend 조건의 응답 본문이 모두 같았으며 잘못된 Origin/토큰은 403이었다.

| HTTP 진단 | Python | HTML 부분 backend 활성 | 해석 |
| --- | ---: | ---: | --- |
| 1클라이언트 API 완료 중앙값 | 2.242 ms | 2.176 ms | HTML 호출 0회 |
| 4동시 요청의 배치 완료 중앙값 | 46.613 ms | 46.248 ms | HTML 호출 0회 |

4클라이언트 값은 4개 요청이 모두 끝나는 배치 시간이며 개별 요청 지연으로 나누어 주장하지
않는다. 각 조건은 30쌍·표본당 3배치이고 초기화·서버 생성은 제외했다. 예시 시험 상태이며
실사용 전체 트래픽 처리량을 대표하지 않는다.

**이 API는 활동/개요 파서를 부르지 않아 파서 Rust 전환의 효과를 얻지 않는다.** 위 작은
차이를 Rust 웹 서버의 개선으로 주장하지 않는다. 서버 자체는 포팅하지 않았다. 직접
세션 처리 프로파일에서 SQLite 실행·연결·폴더/파일 작업 비용이 관측되어, 다음 웹 후보는
상태 저장/DB 경합·반복 I/O부터 검토하는 것이 적절하다. 호스트 AI 대기와도 구분해야 한다.

## 검증과 실행

- 기존 대학 기능 368개 중 366개 통과·2개 건너뜀, 서버 16개 통과.
- 활동·개요·개념 후보를 모두 연결한 회귀에서 활동 1,030회, 개요 758회, 개념 77회 호출.
  해당 회귀 입력의 fallback은 0회였다. 하위 Python 프로세스는 기존 Python 경로일 수 있다.
- Rust 단위 6개, 실험 Python 27개 통과. 새 개요/개념 동등성, 판정, DLL 실패/복구와
  승인 모듈만 실행하는 런처를 포함한다. 느린 개념 후보의 기능 통과가 성능 채택을 뜻하지 않는다.
- 환경상 건너뛴 2개는 기존 PDFKit/선택적 PDF 의존성 검사다. 원본 사용자 DB와 학교 데이터는
  수정하지 않았고 내부 웹의 인증·보안 규칙도 바꾸지 않았다.

```powershell
# 저장소 루트(.publish-tls)에서, 빌드 후 실행
$env:PYTHONUTF8='1'
cargo test --release --locked --manifest-path experiments/rust-core/Cargo.toml
cargo build --release --locked --manifest-path experiments/rust-core/Cargo.toml
python -m unittest discover -s experiments/rust-core -p 'test_*.py'
python experiments/rust-core/partial_benchmark.py --live
python experiments/rust-core/assess_partial.py
# 승인된 활동/개요만 쓰는 명시적 경로. 실제 DB를 갱신하는 일반 동기화 명령이다.
python experiments/rust-core/run.py sync_tls --ensure --metadata-only --metrics
```

기본 `python skills/university-agent/scripts/sync_tls.py ...`도 Rust 라이브러리가 번들되거나
소스 위치에 있으면 승인된 두 파서를 사용한다. backend 설치는 요청 스레드를 시작하기 전에
동기화 한 번에 수행하며 실행 도중 전환하지 않는다. 라이브러리가 없으면 Python만 사용한다.
실험 런처는 기존 재현용으로 남아 있고, 일반 동기화와 같은 읽기/저장 효과를 갖는다.

원시 시간·프로파일·p95·CI: [partial-benchmark.json](../../../experiments/rust-core/results/partial-benchmark.json).
검사: [partial-regression.json](../../../experiments/rust-core/results/partial-regression.json),
[partial-tests.json](../../../experiments/rust-core/results/partial-tests.json).
한계: macOS ARM64와 Windows CI의 Rust 빌드·회귀는 확인했지만 Windows 실기기에서의 번들
알림·서명과 현재 두 모듈 조합의 최대 메모리는 아직 별도 측정하지 않았다.

## macOS ARM64 재검증

2026-11-17(Asia/Seoul), macOS 26.6.2 ARM64, Python 3.11.6, Rust 1.100.0에서
`cargo build --release --locked` 후 같은 실험을 다시 실행했다. Rust 단위 6개와 실험
Python 27개가 통과했고, 활동·개요는 채택 판정을 유지했으며 개념 순위는 여전히 미채택이다.

| 조건 | Python 중앙값 | Rust 경로 중앙값 | 측정된 단축 |
| --- | ---: | ---: | ---: |
| 활동 100개 | 1.246 ms | 0.339 ms | 72.76% |
| 활동 1,000개 | 12.620 ms | 3.405 ms | 73.02% |
| 섹션 개요 100개 | 2.593 ms | 0.419 ms | 83.84% |
| 섹션 개요 1,000개 | 25.832 ms | 4.142 ms | 83.97% |
| 변경 없는 목록 재현 | 44.128 ms | 41.892 ms | 5.07% |
| 전체 메타데이터 재현 | 221.732 ms | 219.035 ms | 1.22% |

실험 결과 원문은 `experiments/rust-core/results/partial-benchmark.json`, 빌드 환경과
라이브러리 해시는 `partial-environment-macos.json`에 기록했다. 이 결과는 보조 앱 전체의
Rust 전환 속도나 학교 서버 트래픽 감소를 뜻하지 않는다. 네트워크·SQLite·AI 분석은 여전히
별도 병목이며, 동기화의 나머지 경로는 Python이다.
