# 정규 강좌와 자율강좌의 Moodle 경계

현재 확인한 구조에서는 자율강좌가 별도 학습 시스템인 것이 아니라, 강좌 목록에 들어오는 방식과
운영자용 관리 화면만 학교 플러그인으로 분리되어 있습니다.

| 흐름 | 정규 강좌 | 자율강좌 | 터틀넥의 공통 처리 |
| --- | --- | --- | --- |
| 목록 발견 | KKU 수강 목록 화면 | `/local/ubeclass/my.php` 자율강좌 표 | 목록 단계만 분리 |
| 강좌 본문 | `/course/view.php?id=...` | `/course/view.php?id=...` | 같은 `get_course_structure()`·토픽/활동 파서 |
| 활동 추가·수정 | `/course/modedit.php` 및 활동 양식 | 같은 Moodle 양식, 운영 권한 필요 | 실제 화면에서 확인한 양식만 사용 |
| 백업·복구 | Moodle `/backup/*` 흐름 | 같은 Moodle `/backup/*` 흐름 | 백업 검증 후 별도 승인 |
| 권한 | 수강·교수·관리 역할 | 운영자·교수 역할과 강좌 소유 여부 | 화면 링크만으로 추측하지 않고 별도 확인 |

Moodle 코어의 `course/view.php`는 강좌 ID로 강좌를 읽고 로그인·컨텍스트 권한을 확인한 뒤 강좌
format을 렌더링합니다. `course/modedit.php`도 강좌 ID와 활동 종류를 받아 같은 활동 추가 양식을
사용합니다. 따라서 “자율강좌라서 자료·퀴즈 파서가 달라진다”는 전제는 두지 않습니다.

반대로 `/local/ubeclass/my.php`와 그 안의 운영자 표시·수정 링크는 KKU 설치의 자율강좌 플러그인
부분입니다. 다른 Moodle에 이 주소를 보내면 안 되므로 목록 발견만 KKU 전용으로 남겼습니다. 자율강좌가
확인된 뒤의 `/course/view.php`, 표준 `resource`의 `pluginfile.php`, `/course/modedit.php`와
`/backup/*`는 공통 Moodle 경로로 다룹니다.

이 구분은 다음 공식 Moodle 코어 소스와 현재 관찰된 TLS 응답을 대조한 결과입니다.

- [Moodle `course/view.php`](https://github.com/moodle/moodle/blob/main/public/course/view.php)
- [Moodle `course/modedit.php`](https://github.com/moodle/moodle/blob/main/public/course/modedit.php)
- [Moodle `backup/backup.php`](https://github.com/moodle/moodle/blob/main/public/backup/backup.php)
- [Moodle `backup/restorefile.php`](https://github.com/moodle/moodle/blob/main/public/backup/restorefile.php)

아직 하지 않은 것: KKU 외 학교의 실제 로그인·자율강좌 목록·교수 권한·활동 양식을 실계정으로
검증하지 않았습니다. 표준 Moodle fixture 검사는 공통 경로의 파싱과 보안 경계만 보장합니다.
