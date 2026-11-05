---
version: 1
slug: "skills-university-agent-assets-exam-html"
primary_target: "skills/university-agent/assets/exam.html"
related_targets: ["skills/university-agent/assets/sets.html","skills/university-agent/assets/match.html"]
---

---
version: 1
slug: "skills-university-agent-assets-exam-html"
primary_target: "skills/university-agent/assets/exam.html"
related_targets: ["skills/university-agent/assets/sets.html","skills/university-agent/assets/match.html"]
---

# 터틀넥 웹 화면 (연습 시험지 · 문제 세트 · 개념 매칭)

Mode: Operate. 범위: exam.html, sets.html, match.html와 공용 exam.css. 책상 노트북(1280+) 우선, 대화 창 옆 반쪽 창(~720px) 지원, 밝은 화면만.
사용자: 도서관·자취방 책상에서 Codex 대화 옆에 띄워 푸는 대학생. 할 일: 시험 풀기·문항별 확인·최종 제출·결과 보기, 세트 고르기, 개념 매칭.
근거: 문제별 출처(자료 이름 + 위치)는 채점 전 공개, 인용문·정답은 채점 전 비공개.
고정 제약: 오프라인, 시스템 폰트, CSP self, Mac·Windows 동일 자산, 마스코트·초록 계열 유지.
미결정: 없음.

## Direction contract

THESIS: 모든 문제·세트·개념에 청구기호처럼 쌓인 출처 라벨을 붙여, "읽은 자료에서만 나왔다"가 화면의 정리 체계가 된다. 시험지·OMR 은유와 둥근 퀴즈 카드라는 카테고리 기본값을 거부한다.
OWN-WORLD: 짙은 서가 안내판 초록 #1d4d3a의 상단 바, 옅은 초록 회색 바탕, 흰 라벨지 작업면, 초록 단계색 주차 띠, 오류·틀림에만 #c8452b. 회색 없음, 보조 글자·선은 초록 틴트. 시스템 고딕 단일 서체, 고정폭 숫자, 코드만 시스템 모노. 라벨 = 흰 스티커 + 얇은 초록 테두리 + 위쪽 색 띠 + 3줄(과목/주차·자료/위치).
STORY: 학생은 지금 문제가 어느 자료 어느 위치에서 나왔는지 보며 풀고, 문항마다 답을 제출해 바로 정답·해설을 확인하고(현재 모든 시험은 study.py가 immediateFeedback=True로 만든다), 남은 문항·시간·저장 상태를 한눈에 확인한 뒤, 틀린 문항만 펼쳐진 결과에서 근거 인용을 다시 읽는다. 예전에 저장된 일괄 채점 시험(immediateFeedback=False)에서만 떨어져 놓인 최종 제출로 끝낸다.
FIRST VIEWPORT: 상단 56px 초록 바(마스코트, 시험 제목, 푼 시간, 저장 상태, 지난 시험). 왼쪽 280px 레일: 진행률과 6~20개 문항 행(번호·유형·상태·배점 비례 띠·풀이 시간), 맨 아래 빈 공간 뒤 마무리 줄 — 기본(문항별 즉시 채점)에서는 진행 방식 안내 한 줄, 일괄 채점 시험에서만 채워진 최종 제출 버튼. 가운데 흰 작업면: 문제마다 큰 번호 + 출처 라벨 + 유형·배점, 문제, 입력, 테두리 보조 버튼 "답 제출하고 정답 보기", "헷갈렸어요". 720px 이하에서 레일은 상단 가로 줄로.
FORM: 서가 라벨(도서관 청구기호·서가 안내판), 내 목록 6번째. Raises: 제출 격리(개발자 콘솔), 정확한 길이의 시간 막대(무용 악보), 회색 금지(이케다), 분량 비례 띠(매뉴얼 탭), 오른쪽 정렬 합계(카세트). seed:cf006ec4787c569e
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
