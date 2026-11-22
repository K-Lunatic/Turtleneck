# 최적화 메모 모음

같은 주제의 계획·보고·상세 결과를 함께 보관한다. 문서 안의 수치와 당시 판정은 유지했다.

- [TLS 수집 최적화](tls/README.md) · 5개 문서
- [Rust 전환](rust/README.md) · 4개 문서
- [문제 생성 최적화](study-generation/README.md) · 7개 문서
- [최적화 보류 목록](OPTIMIZATION_BACKLOG.md) · 다음 실행 항목
- [파트별 벤치마크 기준](BENCHMARK_PROTOCOL.md) · OS·버전별 비교 규칙과 브라우저 트래픽 비교 방법
- [상징 버전별 비교 기준](VERSION_BENCHMARKS.md) · 해커톤·최적화·Rust·현재 버전
- [최신 벤치마크 결과](BENCHMARK_RESULTS.md) · macOS/Windows 독립 실행 누적 기록

## 기록 보존

원시 결과·소스 보관본·기존 hashes.json은 측정 당시 경로와 해시를 보존한다.
이동한 문서는 상대 링크를 조정했으므로 현재 문서 해시가 달라질 수 있다.
[경로 이동표](relocation.json)에서 이전/현재 경로와 정리 전후 해시를 확인할 수 있다.
## 소량·대량 회귀 벤치마크

현재 환경에서 사용자 체감 문제를 먼저 잡기 위해 네트워크를 끈 동일한 재생 fixture로
소량과 대량을 비교합니다. `experiments/benchmarks/scale_benchmark.py`는 1/40과목,
1/20자료, 2/1,000개 미디어 조각을 같은 수집·저장 경로에 넣고 요청 수·본문량·시간·저장
결과를 비교합니다. 이 결과는 학교 서버 부하 측정이 아니며, 대량에서만 발생하는 중복·메모리·
체크포인트 문제를 CI에서 재현하는 회귀 기준입니다.
실측 결과는 [SCALE_BENCHMARK_RESULTS.md](SCALE_BENCHMARK_RESULTS.md)에 기록한다.
