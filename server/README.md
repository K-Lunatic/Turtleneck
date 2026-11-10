# 이 컴퓨터에서 ChatGPT 웹·모바일 연결

별도 호스팅 서버·도메인·Docker 없이 한 사용자의 컴퓨터에서 실행하는 보조 경로입니다. ChatGPT가 컴퓨터에 도달하도록 HTTPS 터널을 사용합니다. 휴대폰 사용자는 Custom GPT의 로그인 화면에서 TLS에 로그인하며 Python이나 터미널을 사용하지 않습니다. 데이터 조회·동기화를 처리하므로 컴퓨터와 실행 프로세스가 켜져 있어야 합니다. 학교 전체에 공유하는 공용 서버나 다중 사용자 서비스로 배포하지 마세요. 계정별 DB·메모리 세션·터널 운영 책임이 생기므로, 학교 배포가 필요하면 별도 개인정보·보안 검토와 운영 설계가 먼저입니다.

이 게이트웨이는 원본 미디어를 자동으로 일괄 수집하거나 학교에 업로드하지 않습니다. 모바일 학습 팩은 게이트웨이 컴퓨터로만 처리되고, TLS 자율강좌 복구는 별도의 명시적 명령입니다. 원본 파일·HLS 미디어 조각·재시도 요청은 학교의 이용 제한을 따르며, 필요한 경우에만 실행해야 합니다.

현재 연결 방식은 **Custom GPT Actions**이며, 모바일을 포함한 정식 보조 경로입니다. 로컬 플러그인만 설치하면 일반 ChatGPT 대화에 자동 연결되는 방식은 아닙니다. 실제 GPT ID와 Actions 설정을 마쳐야 조회할 수 있습니다. ChatGPT 앱 디렉터리/MCP 등록이나 독립 실행형 모바일 앱은 포함하지 않습니다.

## 모바일 지원 범위

모바일은 사용자의 Mac·Windows에서 실행 중인 이 게이트웨이에 HTTPS로 접속합니다. 게이트웨이 컴퓨터나 터널이 꺼지면 모바일 기능도 사용할 수 없습니다. 지원 범위는 과목·과제·강의·공지·할 일 조회와 동기화, 연결 해제, 과제 진행 기록, `.tpack` 업로드 후 웹 시험 시작·재시험·답안 저장입니다.

모바일 Actions에는 원본 강의 파일 다운로드, 수업자료 본문 읽기, Everytime, 로컬 Codex 학습 세션을 연결하지 않습니다. 비밀번호·TLS 쿠키·원본 파일은 모바일 응답과 학습 팩에 포함하지 않습니다. 실제 iOS·Android·ChatGPT 계정 왕복은 자동화 테스트와 별도로 배포 전 대상 계정에서 한 번 확인해야 합니다.

## 시작하기

[Mac](../University%20Agent.command)은 `.command` 파일을 더블클릭하고, [Windows](../University%20Agent.bat)는 `.bat` 파일을 더블클릭합니다. 처음에는 저장한 Custom GPT의 `g-...` ID를 입력합니다. 이후 저장된 ID를 재사용합니다. 터널이 연결되면 비공개 설정 페이지가 열립니다.

런처에 Python 3.10 이상과 `cloudflared` 실행 파일이 필요합니다. 공식 [Python 설치 안내](https://www.python.org/downloads/)와 [cloudflared 다운로드 안내](https://developers.cloudflare.com/tunnel/downloads/)에 따라 운영체제에 맞는 파일을 설치하고 PATH에 등록합니다. Python 패키지 설치는 필요 없습니다.

CLI 실행도 가능합니다. 다음 명령은 컴퓨터 운영자용이며 휴대폰 사용자에게 요구하지 않습니다.

```sh
python3 -m server.local --gpt-id g-YOUR-GPT-ID
# Windows: py -3 -m server.local --gpt-id g-YOUR-GPT-ID
```

직접 준비한 고정 HTTPS 터널을 쓰려면 `--public-url https://<터널 주소>`를 추가하고 터널을 `http://127.0.0.1:8766`에 연결합니다. 기본 실행은 계정·도메인 없이 임시 Quick Tunnel을 시작합니다. [Cloudflare 공식 문서](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)에 따르면 임시 터널은 테스트용이며 재실행 시 주소가 바뀌고 가동 시간을 보장하지 않습니다. 주소가 바뀌면 GPT의 스키마·OAuth URL을 갱신합니다. 안정적인 고정 주소가 필요할 때는 운영체제에 맞는 named tunnel을 운영할 수 있습니다.

## GPT에 연결

컴퓨터에 열리는 `.university-agent/chatgpt/settings.html`을 따라 설정합니다. 파일은 권한 600으로 저장하며 API로 공개하지 않습니다. 학교 비밀번호와 다른 OAuth Client secret이 들어 있으므로 이 파일을 채팅에 보내지 않습니다.

| GPT 설정 | 값 |
| --- | --- |
| Action schema | 런처가 알려준 `https://<터널 주소>/openapi.json` |
| Authentication | OAuth |
| Client ID, Client secret | 비공개 설정 페이지의 값 |
| Authorization URL | `https://<터널 주소>/oauth/authorize` |
| Token URL | `https://<터널 주소>/oauth/token` |
| Scope | `academic:read` |
| Token exchange | POST, `application/x-www-form-urlencoded`; Basic 인증도 지원 |
| Privacy policy | `https://<터널 주소>/privacy` |

GPT Instructions에는 [gpt-instructions.md](gpt-instructions.md)를 넣습니다. OAuth 콜백은 입력한 GPT ID의 `https://chatgpt.com/aip/g-.../oauth/callback`과 `https://chat.openai.com/aip/g-.../oauth/callback`만 허용합니다.

기존 Custom GPT에도 새 저장·목록 Actions를 적용하려면 GPT 편집 화면에서 Action schema를 현재 `/openapi.json`으로 다시 가져오고 Instructions를 최신 [gpt-instructions.md](gpt-instructions.md)로 교체한 뒤 저장합니다.

OpenAI의 [GPT Action 인증](https://developers.openai.com/api/docs/actions/authentication)과 [HTTPS·시간 제한](https://developers.openai.com/api/docs/actions/production)을 따릅니다. 계정의 GPT/Actions 사용 가능 여부와 웹·iOS·Android 인증 동작은 실제 대상 계정에서 확인해야 합니다.

## 데이터와 실패 처리

- TLS 비밀번호는 브라우저→터널→컴퓨터→학교 TLS로 전송되며 저장하지 않습니다. Action 스키마에 로그인 비밀번호를 받는 경로는 없습니다. HTTPS 터널 제공자는 연결을 중계합니다.
- TLS 쿠키·OAuth 토큰은 실행 중인 프로세스 메모리에만 있고 학사 데이터는 `.university-agent/chatgpt/data/`의 사용자별 DB에 있습니다. 기존 Codex DB를 자동 업로드하거나 합치지 않습니다. 설정·DB·터널 실행 파일은 `.gitignore`로 제외합니다.
- 로그인 ticket 10분, OAuth 코드 2분, Access token 1시간, Refresh token 30일입니다. 코드와 Refresh token은 일회용이며 state·콜백·선택적 S256 PKCE를 검증합니다.
- 로그인 이후 동기화는 백그라운드에서 실행합니다. 과제를 저장한 뒤 강의 조회가 실패해도 과제는 조회할 수 있습니다. 실패 시 이미 저장된 과제를 지우지 않습니다.
- 응답의 `sync`는 `syncedAt`, `availableSections`, `running`, `stage`, `error`를 포함합니다. 아직 동기화되지 않은 섹션은 503이며 “과제 없음”이 아닙니다. 프로세스 재시작·학교 세션 만료 후에는 재연결합니다.
- 과제 마감 범위는 시간대가 있는 `due_from` 이상, `due_before` 미만입니다. 이미 마감된 과제도 필요하면 하한 없이 조회합니다. 마감일 없는 과제는 날짜 필터에서 제외되므로 별도 미제출 조회로 확인합니다.
- 페이지 기본 20개, 최대 50개이며 `nextOffset`을 따라 조회합니다. 공지 본문은 1,000자 미리보기입니다. 할 일은 과목명이 있는 항목 목록입니다.
- 연결 해제는 계정의 모든 토큰과 메모리 세션을 폐기합니다. 로컬 DB·학습 팩·원본 파일은 자동 삭제하지 않으므로, 사용을 끝낼 때는 동기화를 멈춘 뒤 `~/.university-agent`와 `.university-agent/chatgpt/data/`에서 본인 데이터만 확인해 삭제하세요. 학교 전체 배포에서는 보존 기간·삭제 요청·접근 로그 정책을 별도로 정해야 합니다.

현재 모바일 지원: 과목·과제·강의·공지·할 일 조회, 동기화, 연결 해제, 과제 진행 기록 저장·불러오기, 미완성 저장 목록, 직접 등록한 과제 제출 확인 후 완료 처리. TLS 과제는 `save "과제명"`, 캡처 문제처럼 TLS에 없는 과제는 `save new "제목"`으로 저장합니다. 직접 등록한 과제는 사용자 답변이 정확히 `예`일 때만 완료 처리하고 체크포인트를 제거합니다. `아니요`나 다른 답변에는 유지합니다. TLS 과제는 동기화에서 `SUBMITTED` 또는 `LATE`가 확인될 때 제거합니다. `load "과제명"`으로 기록을 불러오고 정확한 `list` 명령으로 저장 목록을 조회합니다. 응답의 `nextCommands`에는 이어서 사용할 명령이 있습니다. 학습 팩 링크는 처음 연 기기에만 10분 동안 붙고 다른 기기에서 재사용할 수 없습니다. 일반 과제 편집·학사 북마크·수업자료 파일 다운로드·본문 읽기는 Actions에 연결되지 않았습니다. 수업자료 기반 학습은 사용자가 대화에 파일을 직접 첨부했을 때 ChatGPT가 실제 읽은 범위에서 진행합니다. 로컬 Codex의 `study` 세션·인용 검증은 모바일 Actions 경로에 적용되지 않습니다.

이 실행기는 단일 컴퓨터에서 연결을 확인하는 용도입니다. 표준 라이브러리 WSGI 실행기와 메모리 토큰을 사용합니다. 여러 프로세스나 장기 운영용으로 확대할 때는 HTTP 실행기·공유 토큰 저장소를 교체해야 합니다.

## 확인

```sh
python3 -m unittest server.test_app server.test_local
python3 -m unittest discover -s skills/university-agent/tests -p 'test_*.py'
```

가짜 TLS로 사용자 격리·OAuth 재사용 차단·만료·토큰 회전·마감 필터·부분 동기화 보존·비밀값 미노출을 확인합니다. 실제 ChatGPT 왕복 조회는 GPT 연결 설정 후 별도로 확인합니다.
