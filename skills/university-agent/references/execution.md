# 실행 경로

학교·에타 데이터 작업은 설치된 Python 실행기와 Provider로 수행한다. Codex의 Browser Computer Use,
Playwright, 화면 클릭·스크린샷 순회는 기본 조회 경로에 포함하지 않는다. 사용자가 실제 화면 조작을
명시한 작업에서만 해당 도구를 사용한다. HTTP 응답의 HTML 양식은 기존 코드로 읽는다.

| 요청 | 실행 경로 |
| --- | --- |
| 연결 상태 | `scripts/setup_turtleneck.py --status` |
| 학교 로그인·갱신 | `scripts/sync_tls.py --connect` 또는 `--ensure --metadata-only` |
| 최신 제출·시청 상태 | `scripts/academic_watch.py --daily-report` |
| 과제·공지·자료·강의 | `scripts/run_agent.py`의 기존 조회 명령 |
| 이전에 받은 자료 | `run_agent.py source-library --query "검색어"` |
| 과제 제출 | `scripts/submit_tls_assignment.py`로 양식 확인 후 승인된 전송 |
| 강좌·활동·퀴즈 관리 | 기존 `tls-activity-*`, `tls-quiz-question-*`, 강좌 관리 실행기 |
| 에타 조회·수정 | `integrations/everytime/scripts/` 실행기와 승인 계약 |
| 성적표·졸업·시간표 계산 | `run_agent.py gradkuya` |
| 시험 풀이 화면 | 기존 `scripts/exam_web.py` |

`--help`와 해당 기능 참조 문서를 먼저 확인해 이미 구현된 명령을 찾는다. 지원되지 않는 양식,
세션 만료, 서버 대기, 다운로드 제한은 실행기가 반환한 원인으로 안내한다. 오류를 보고 자동으로
브라우저 순회를 시작하거나 엔드포인트를 추측하지 않는다. 로그인 재연결은 기존 보안 폼을 연다.

로그인 폼·웹 시험·자료 대시보드의 화면 표시는 유지한다. 실행 중인 보조 앱이 로컬 화면 요청을
받으면 앱 내부 창에 표시하고, 보조 앱이 응답하지 않으면 기본 브라우저로 연다. 앱 설치 표식만으로
현재 실행 중이라고 가정하지 않는다. 화면 열기 요청, 실제 페이지 접근, 인증 완료를 각각 확인한다.
에타 공식 로그인·2차 인증은 기존 공식 브라우저 절차를 사용한다.

`webOpened: false`여도 `webUrl`이 반환되면 같은 서버의 링크를 안내한다. 이미 준비된 시험을 위해
서버를 다시 시작하지 않는다. `displayTarget`은 `companion` 또는 `browser`이고,
`displayRequested`는 열기 요청 여부다. `opened`는 시험 페이지의 실제 GET 확인 결과다.
