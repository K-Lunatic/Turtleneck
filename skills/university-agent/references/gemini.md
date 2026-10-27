# Gemini 실행

데스크톱의 로컬 Gemini(Task Mode)에서 사용한다. 로컬 파일시스템 및 명령 실행 도구가 없는 일반 웹 전용 환경에서는 이 컴퓨터의 Keychain/DPAPI·브라우저·로컬 DB를 사용할 수 없으므로 같은 기능을 제공한다고 설명하지 않는다.

- 스킬 호출은 사용자 스킬(`turtleneck`) 자동 감지 또는 직접 요청으로 시작한다. Codex 전용 `codex plugin` 명령이나 Claude 전용 `/university-agent:turtleneck` 슬래시 명령을 Gemini에서 안내하지 않는다.
- 이 `SKILL.md`가 있는 절대 디렉터리(연결된 저장소의 `skills/university-agent` 또는 로컬 설치 경로 `$HOME/skills/turtleneck`)를 기준으로 실행한다. 경로에 공백이 있어도 실행 파일과 인수를 각각 인용한다.
- 명령 실행 시 기본 `PATH`의 `python3`(또는 `/opt/homebrew/bin/python3`)를 사용한다. Python이 없으면 패키지의 `run_with_python.command` 또는 `run_with_python.bat`를 사용한다.
- Gemini의 로컬 명령 샌드박스는 기본적으로 네트워크와 루프백(`127.0.0.1`) 소켓 바인딩을 차단한다. 따라서 TLS·에브리타임 동기화(`setup_turtleneck.py`, `sync_tls.py`, `academic_watch.py`, `everytime.py`)나 로컬 웹 시험지·로그인 폼 서버(`exam_web.py`, `connect.py`)를 실행할 때는 반드시 `RequiresNetworkAccess: true`와 한국어 `intent`를 지정해 사용자 승인을 받는다.
- 로컬 DB 저장 기본 경로는 실행 환경의 `$HOME/.university-agent`와 `$HOME/.everytime`(또는 `UNIVERSITY_AGENT_DB`, `EVERYTIME_DB`)이다. 기존 사용자 홈(`~/.university-agent`)을 공유하려면 Connected Folders에 해당 폴더를 연결하거나 환경 변수로 지정한다.
- `setup_turtleneck.py`는 연결 프로세스를 별도로 시작하므로 장시간 대기 명령을 만들 필요가 없다. 사용자가 직접 TLS 로그인·에타 2차 인증을 마치면 `--status`로 완료를 확인한다. 비밀번호·쿠키·Keychain 값을 명령 출력이나 모델 대화로 가져오지 않는다.
- 공부는 [공통 학습 계약](study.md)을 그대로 사용한다. SOURCE의 현재 부분만 분석하고 `extract` 성공 뒤 다음 부분으로 넘어간다. 큰 JSON은 작업용 임시 파일에 기록해 `--event-file`로 전달한다.
- `webOpened: true`이면 반환 URL을 안내하고 서버를 또 실행하지 않는다. 서버를 직접 실행해야 할 때만 `exam_web.py`를 백그라운드 명령(`WaitMsBeforeAsync`)으로 유지하고 시험 중에는 종료하지 않는다.
- 사용자가 제출 후 돌아오면 `status`의 `hostOnly.answers`를 **현재 Gemini가** 평가하고 `gradeId`와 모든 기준의 `met`/`feedback`을 `grade_batch`로 전달한다. 별도 외부 모델 API 키는 필요 없다.
