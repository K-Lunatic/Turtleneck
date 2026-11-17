# Turtleneck 지원

설치, 실행, 자료 읽기, 시험 화면, 모바일 게이트웨이 문제는 먼저 [README](README.md)와 [게이트웨이 안내](server/README.md)를 확인해 주세요.

## 도움 요청

재현 가능한 일반 버그는 [GitHub Issues](https://github.com/K-Lunatic/Turtleneck/issues)에 남겨 주세요. 다음 정보를 포함하면 확인이 빠릅니다.

- 운영체제와 터틀넥 버전
- 사용한 설치 방식과 실행한 기능
- 비밀값을 제거한 오류 메시지
- 재현 순서

비밀번호, 쿠키, OAuth 값, 개인 강좌 ID, 서명된 다운로드 URL, 원본 강의자료와 백업 파일은 이슈에 올리지 마세요.

### 학교별 Moodle 최적화 기여

기본 Moodle 연결이 동작한 뒤 학교별 차이를 공유하려면 다음 명령으로 안전한 마이그레이션 리포트를 만들 수
있습니다.

```bash
python3 skills/university-agent/scripts/moodle_migration.py \
  --base-url https://lms.example.ac.kr \
  --account-alias 본계정 \
  --output ~/Downloads/turtleneck-moodle-migration.json
```

리포트는 호스트·활동 유형·요청량만 기록하고 강좌명·ID·원문·파일·비밀번호·쿠키·세션은 기록하지 않습니다.
생성 후 내용을 직접 확인해 [GitHub Issues](https://github.com/K-Lunatic/Turtleneck/issues)에 첨부해 주세요.
학교 담당자의 비공개 협조가 필요한 경우에는 공개 이슈에 자격증명이나 원본 자료를 남기지 말고 먼저 이슈에
비공개 연락이 필요하다고 적어 주세요.

학교별 협력 요청부터 읽기 전용 검증, 트래픽 측정, 최적화 모듈 배포까지의 기준은
[대학교 협력·최적화 로드맵](docs/UNIVERSITY_COLLABORATION_PLAN.md)에 정리했습니다.

## 보안 문제

자격 증명 노출, 인증 우회, 임의 코드 실행, 로컬 게이트웨이 인증 문제는 공개 이슈가 아니라 [보안 안내](SECURITY.md)에 따라 비공개로 알려 주세요.

## 지원 범위

터틀넥은 macOS·Windows 로컬 실행을 기본으로 지원합니다. 모바일은 사용자의 컴퓨터에서 실행 중인 선택적 ChatGPT Actions 게이트웨이를 통해서만 지원하며, 독립 모바일 앱이나 기기 간 DB 동기화는 제공하지 않습니다.
