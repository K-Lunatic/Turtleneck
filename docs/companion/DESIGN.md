# 터틀넥 보조 앱 디자인

## 방향

터틀넥 보조 앱은 별도 작업 창이 아니라 macOS 메뉴 바와 Windows 알림 영역에
머무는 로컬 상태판이다. 평소에는 아이콘과 짧은 상태만 보여주고, 클릭했을 때
프로필·자료·동기화 상태와 자주 쓰는 명령을 펼친다.

이 구조는 macOS가 메뉴 바에 앱 명령을 두고 중요한 메뉴를 먼저 배치하도록 하는
가이드와, Windows 알림 영역을 상태·비중단성 알림 중심으로 사용하고 알림을
과도하게 보내지 말라는 가이드에 맞춘다.

## 1차 범위

- 프로필별 사이트·별칭·아이디 표시
- 과목 수·로컬 자료 수·로컬 자료 용량 표시
- 저장된 시험지 목록·문항 수·풀이 상태·점수 요약 표시
- 기존 로컬 시험지를 읽기 전용으로 열고 재시험 흐름으로 넘기기
- 스킬 설치 여부 표시
- 상태 새로 확인
- 연결 상태 확인
- 앱 종료

비밀번호·쿠키·세션·시험 문항 원문은 대시보드 API에 넣지 않는다. 대시보드는
127.0.0.1에만 열리고 실행 때 발급한 일회성 토큰이 있어야 읽을 수 있다. 시험 열기는
기존 읽기 전용 `exam_web.py`를 다시 사용하며, 보조 앱이 시험 데이터를 직접 수정하지 않는다.

## 동작 원칙

- 핵심 스킬은 보조 앱 없이도 동작한다.
- 보조 앱 설치는 선택 사항이며 최초 설정 때 한 번만 권장한다.
- 스킬이 없으면 자료나 자격증명을 읽지 않고 `스킬 없음` 상태로 멈춘다.
- 삭제는 앱·스킬·자료·보호 저장소를 분리해 확인한다.
- 자동 시작과 알림은 기본적으로 켜지지 않으며 사용자가 선택한다.
- 알림은 새 자료·동기화 실패·사용자 요청 작업 완료처럼 행동 가치가 있을 때만 보낸다.
- `새로 확인`은 보조 앱이 직접 학교 요청을 처리하지 않고, 기존 `academic_watch.py`를 한 번 실행한다. 결과는 로컬 DB와 운영체제 알림으로만 반영한다.

## 다음 단계

1. macOS 메뉴 바·Windows 알림 영역 패키징 검증
2. 앱 삭제 도우미와 앱·스킬·자료 분리 확인
3. 대시보드의 자료·동기화 상세 화면
4. 자동 시작·알림 설정

참고:

- [Apple Human Interface Guidelines: Designing for macOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-macos/)
- [Apple Human Interface Guidelines: Menus](https://developer.apple.com/design/human-interface-guidelines/menus)
- [Microsoft Learn: Notifications and the Notification Area](https://learn.microsoft.com/en-us/windows/win32/shell/notification-area)
