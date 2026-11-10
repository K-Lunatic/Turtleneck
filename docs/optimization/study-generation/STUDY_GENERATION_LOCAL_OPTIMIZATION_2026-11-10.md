# 로컬 학습·전사 최적화 비교

2026-11-10 · 기준 커밋 `b64d82b` · 결정적 호스트 fixture 30회 중앙값

## 변경 내용

- 분석 중간의 큰 `pipeline` JSON을 `study_pipelines`에 분리해 세션 행을 작게 유지한다.
- 캐시 조회에서 쓰기 잠금을 제거하고, 최초 스키마 생성 때만 잠근다.
- 전사 CPU 재시도는 CUDA/Metal/Vulkan의 메모리·장치 초기화 오류에만 적용한다.

## 성능 비교

기준은 저장소에 기록된 `experiments/study-generation/results/after.json`이며, 동일한 30문항·1개/4개 파일 fixture를 현재 코드에서 다시 측정했다. AI 추론 시간과 학교 네트워크 요청은 포함하지 않는다.

| 시나리오 | 기준 로컬 처리 | 현재 로컬 처리 | 감소 | 기준 warm 재사용 | 현재 warm 재사용 | 감소 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 파일 1개 | 153.24 ms | 93.92 ms | **38.71%** | 19.34 ms | 14.33 ms | **25.89%** |
| 파일 4개 | 214.99 ms | 101.50 ms | **52.79%** | 33.13 ms | 24.53 ms | **25.96%** |

도구 호출 수와 응답 바이트는 동일했다. 따라서 속도 감소가 자료 범위·문항 수·호스트 전달량을 줄여 얻은 결과는 아니다. 이 비교는 서로 다른 실행의 중앙값이므로 실제 장치별 체감 속도나 AI 생성 시간으로 일반화하지 않는다.

## 검증

- `test_study*.py`: 79개 통과, 선택적 PDF 테스트 1개 건너뜀
- `test_lecture_audio.py`: 22개 통과
- `git diff --check`: 통과

재현 명령:

```text
python experiments/study-generation/benchmark.py --output /private/tmp/turtleneck-current-benchmark.json --samples 30
```

