# Gemini 실행

이 문서는 **로컬 Gemini CLI** 기준이다. 로컬 파일·명령 실행 권한이 없는 일반 Gemini 웹 대화에서는 이 컴퓨터의 Keychain/Windows 보호 저장소·브라우저·로컬 DB를 사용할 수 없으므로, 연결·동기화·로컬 시험을 지원한다고 말하지 않는다.

## 설치와 첫 확인

Gemini CLI에서 저장소 전체를 막연히 연결하지 말고 스킬 경로를 직접 지정한다.

```bash
gemini skills install https://github.com/K-Lunatic/Turtleneck.git \
  --path skills/university-agent --scope user
gemini skills list --all
```

개발 중인 로컬 저장소를 바로 시험할 때는 저장소 루트에서 다음처럼 연결한다.

```bash
gemini skills link "$PWD/skills/university-agent" --scope workspace
gemini skills list --all
```

목록에 `turtleneck`가 보인 뒤 새 Gemini CLI 세션에서 “터틀넥으로 학교 자료 연결 상태 확인해줘”처럼 자연어로 시작한다. Codex 전용 `codex plugin` 명령이나 Claude 전용 `/university-agent:turtleneck` 명령은 Gemini에 안내하지 않는다.

## 실행 규칙

- 모든 명령은 이 `SKILL.md`가 있는 디렉터리(연결된 저장소의 `skills/university-agent`)를 기준으로 실행한다. 경로와 인수는 각각 인용한다.
- 명령 실행은 기본 `PATH`의 `python3`를 사용하고, Windows에서는 `py -3`를 우선한다. Python이 없으면 저장소 루트의 `run_with_python.command` 또는 `run_with_python.bat`를 사용한다.
- TLS·에브리타임 동기화나 로컬 로그인 폼·시험지를 실행할 때 Gemini CLI가 네트워크 또는 `127.0.0.1` 접근 승인을 묻는 경우, 무엇을 위해 필요한지 사용자에게 보여주고 그 요청만 승인받는다. Gemini CLI에 없는 `RequiresNetworkAccess`, `WaitMsBeforeAsync` 같은 인자를 만들어 명령에 넣지 않는다. 승인이 거부되면 성공한 것처럼 진행하지 않고 막힌 이유를 설명한다.
- 로컬 DB 기본 경로는 `$HOME/.university-agent`와 `$HOME/.everytime`(또는 `UNIVERSITY_AGENT_DB`, `EVERYTIME_DB`)다. 기존 데이터를 쓰려면 해당 폴더를 Gemini 작업공간에 연결하거나 같은 환경 변수를 지정한다.
- `setup_turtleneck.py`는 별도 연결 절차를 시작한다. 사용자가 TLS 로그인과 에타 2차 인증을 직접 끝낸 뒤 `--status`로 READY/PARTIAL/RUNNING을 확인한다. 비밀번호·쿠키·Keychain 값을 명령 출력이나 대화로 가져오지 않는다.
- 로컬 파일·명령 실행 도구가 없는 Gemini 웹 환경에서는 설치 명령이나 로컬 결과를 지어내지 말고, 데스크톱 Gemini CLI에서 다시 실행해야 한다고 말한다.
- Codex가 먼저 분석한 자료를 Claude Code 또는 Gemini CLI가 이어서 사용할 때도 같은 기기의 로컬 분석 캐시와 문제은행을 먼저 재사용한다. 파일·권한·범위가 바뀌지 않았다면 원문 전체를 다시 호스트에 보내지 않으며, 캐시된 검증 근거 밖의 내용을 추측하지 않는다.

## 학습과 웹 시험

- 공부는 [공통 학습 계약](study.md)을 그대로 사용한다. SOURCE의 현재 부분만 분석하고 `extract`가 성공한 뒤 다음 부분으로 넘어간다. 큰 JSON은 임시 파일에 기록해 `study --event-file`로 전달한다.
- 시험지 응답에 `webOpened: true`가 있으면 반환된 `webUrl`을 그대로 안내하고 서버를 다시 시작하지 않는다. 자동 브라우저 열림이 확인되지 않았거나 `webOpened: false`면 다음처럼 직접 실행해 반환된 URL을 사용자에게 보여준다.

  ```bash
  python3 scripts/exam_web.py --conversation '<대화 ID>' --no-open
  ```

  Gemini가 백그라운드 프로세스를 유지하지 못하면 사용자의 별도 터미널에서 위 명령을 실행하게 하고, 시험이 끝날 때까지 프로세스를 종료하지 않도록 안내한다. 채팅에 문제를 대신 내거나 URL 없이 시험이 열렸다고 말하지 않는다.
- 사용자가 제출 후 돌아오면 `status`의 `hostOnly.answers`를 **현재 Gemini가** 평가하고 `gradeId`와 모든 문항의 기준별 `met`/`feedback`을 `grade_batch`로 전달한다. 별도 외부 모델 API 키는 필요 없다.
