# GradKUya 로컬 계산

`integrations/gradkuya/engine/`은 GradKUya의 성적·요람·시간표 로직에서 생성한 실행 코드다.
사용자 환경에는 Node.js 22 이상이 필요하다. 기존 무설치 Python 번들에는 Node.js가 포함되지 않는다.
소스와 변경 내용의 해시는 `engine/manifest.json`에 기록한다. 재생성은 저장소 루트에서
`node packaging/build_gradkuya.mjs <GradKUya 작업 폴더>`로 수행한다.

일반 진입점은 `python3 scripts/run_agent.py gradkuya`다. 학교 로그인 없이 호출할 수 있다.

```bash
python3 scripts/run_agent.py gradkuya --status
python3 scripts/run_agent.py gradkuya --transcript "<사용자가 선택한 PDF 또는 TXT>"
python3 scripts/run_agent.py gradkuya --input "<계산 요청.json>" --output "<결과.json>"
```

입력과 결과는 로컬 프로세스 안에서 처리한다. 비밀번호·세션·React 상태는 입력에 포함하지 않는다.
학번·이름은 성적표 파싱에만 쓰며 결과에는 학과·입학연도·과목·계산 내용을 반환한다.

| action | 필수 입력 | 결과 |
| --- | --- | --- |
| `status` | 없음 | 요람 연도·지원 작업 |
| `transcript` | `text` | 성적표 본문 파싱·졸업요건 |
| `audit` | `transcript` | 구조화 성적 재계산 |
| `schedule` | `courses`, 선택 `preferences`, `maxCredits` | 상위 5개 시간표·조건 미충족 이유 |
| `catalog` | `rows` | 이미 확보한 KUPIS 행의 병합·공통 과목 형식 |

`audit.transcript`에는 `department`, `admissionYear`, `totalCredits`, `courses`가 필요하다.
각 과목에는 `year`, `semester`, `category`, `code`, `name`, `credits`, `grade`를 넣는다.
같은 과목의 재이수 기록이 중복되면 최종 인정 기록을 확인한 뒤 다시 계산한다. F·NP는 필수 과목의
이수 완료로 계산하지 않는다. 정확한 입학연도 요람이 없거나 학과 요건이 충분하지 않으면 오류를 반환한다.

`schedule.courses`는 각 분반의 `id`, `name`, `group`(동일 과목 식별값), `credits`,
`day`, `start`, `end`를 받는다. 복수 수업 시간은 `meetings` 배열로 지정한다.
`fixed: true`는 반드시 포함할 분반이다. `deliveryMode: "이러닝"`은 시간 없는 온라인 과목이다.
선호 조건은 `freeDays`, `noMorning`, `lunch`, `blockedSlots`, `preferredProfessors`,
`avoidedProfessors`, `preferredCourses`, `preferredCategories`, `coursePriorities`를 지원한다.
시간은 24시간제 소수 시간이다. 예를 들어 10시 30분은 `10.5`다.

수강편람의 실시간 수집·좌석 감시는 원본 GradKUya와 별도 작업이다. 현재 터틀넥 계산 실행기는 네트워크를
차단하고 제공된 목록으로 계산한다. 요람은 번들에 포함된 스냅샷이며 계산 결과는 학사 담당자의 최종 판정을
대체하지 않는다. 편입·복수전공·특례의 개별 인정 여부는 확인이 필요하다.
