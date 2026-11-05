---
name: 터틀넥 · Turtleneck
description: 읽은 수업자료에서만 나온 연습 시험을, 청구기호처럼 출처 라벨을 붙여 푸는 로컬 화면
colors:
  shelf: "#1d4d3a"
  shelf-deep: "#143a2b"
  ground: "#e4ece7"
  paper: "#fbfcfa"
  white: "#ffffff"
  ink: "#14271f"
  ink-2: "#3f5a4c"
  ink-3: "#5a7366"
  line: "#c3d4ca"
  line-soft: "#dbe6df"
  tint: "#eef4f0"
  tint-strong: "#d5e6db"
  focus: "#2f7a56"
  errata: "#b83d24"
  errata-tint: "#f8e7e2"
  errata-line: "#ecc7bd"
  on-shelf: "#d6e8dd"
  alert-on-shelf: "#ffd2c6"
  band-1: "#2f7a56"
  band-2: "#7fb592"
  band-3: "#1d4d3a"
  band-4: "#a9cfb3"
  band-5: "#4f9a6e"
typography:
  score:
    fontFamily: "Apple SD Gothic Neo, Malgun Gothic, 맑은 고딕, Noto Sans KR, system-ui, sans-serif"
    fontSize: "44px"
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: "-0.03em"
    fontFeature: "tnum"
  headline:
    fontFamily: "Apple SD Gothic Neo, Malgun Gothic, 맑은 고딕, Noto Sans KR, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 800
    lineHeight: 1.35
    letterSpacing: "-0.02em"
  question-number:
    fontFamily: "Apple SD Gothic Neo, Malgun Gothic, 맑은 고딕, Noto Sans KR, system-ui, sans-serif"
    fontSize: "32px"
    fontWeight: 800
    lineHeight: 1
    fontFeature: "tnum"
  question:
    fontFamily: "Apple SD Gothic Neo, Malgun Gothic, 맑은 고딕, Noto Sans KR, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 500
    lineHeight: 1.7
  answer:
    fontFamily: "Apple SD Gothic Neo, Malgun Gothic, 맑은 고딕, Noto Sans KR, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.7
  body:
    fontFamily: "Apple SD Gothic Neo, Malgun Gothic, 맑은 고딕, Noto Sans KR, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "Apple SD Gothic Neo, Malgun Gothic, 맑은 고딕, Noto Sans KR, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: 1.35
  meta:
    fontFamily: "Apple SD Gothic Neo, Malgun Gothic, 맑은 고딕, Noto Sans KR, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    fontFeature: "tnum"
  code:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, D2Coding, monospace"
    fontSize: "14px"
    lineHeight: 1.7
rounded:
  none: "0px"
  bar: "2px"
  tag: "4px"
  control: "6px"
  surface: "8px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "40px"
components:
  shell-bar:
    backgroundColor: "{colors.shelf}"
    textColor: "{colors.white}"
    height: "56px"
    padding: "8px 24px"
  source-label:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "9px 12px 8px"
  source-label-small:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "6px 10px 5px"
  button-primary:
    backgroundColor: "{colors.shelf}"
    textColor: "{colors.white}"
    rounded: "{rounded.control}"
    height: "46px"
    padding: "0 16px"
  button-primary-hover:
    backgroundColor: "{colors.shelf-deep}"
  button-primary-armed:
    backgroundColor: "{colors.errata}"
    textColor: "{colors.white}"
  button-secondary:
    backgroundColor: "{colors.white}"
    textColor: "{colors.shelf}"
    rounded: "{rounded.control}"
    height: "40px"
    padding: "0 16px"
  button-secondary-hover:
    backgroundColor: "{colors.tint}"
  button-quiet:
    textColor: "{colors.shelf}"
    rounded: "{rounded.control}"
    height: "32px"
  option-selected:
    backgroundColor: "{colors.tint-strong}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  option-tag-mine:
    textColor: "{colors.ink}"
    rounded: "{rounded.tag}"
    padding: "1px 8px"
  option-tag-answer:
    backgroundColor: "{colors.shelf}"
    textColor: "{colors.white}"
    rounded: "{rounded.tag}"
    padding: "1px 8px"
  rail-row-current:
    backgroundColor: "{colors.tint-strong}"
    padding: "10px 12px 12px 8px"
  match-tile:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "14px 16px 12px"
  match-tile-selected:
    backgroundColor: "{colors.tint-strong}"
  match-tile-matched:
    backgroundColor: "{colors.tint}"
    textColor: "{colors.ink-2}"
  input-text:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
  errata-panel:
    backgroundColor: "{colors.errata-tint}"
    textColor: "{colors.errata}"
    rounded: "{rounded.control}"
    padding: "20px 24px"
---

# Design System: 터틀넥 · Turtleneck

## Overview

**Creative North Star: "서가 라벨 (The Shelf Label)"**

도서관 서가에서 책등의 청구기호 스티커와 서가 끝 안내판이 자료의 자리를 알려주듯, 이 화면의 모든 문제·세트·개념에는 출처 라벨이 붙는다. "읽은 자료에서만 나왔다"는 제품 원칙이 장식이 아니라 화면의 정리 체계가 된다. 상단은 짙은 서가 안내판 초록 바, 바탕은 옅은 초록 회색, 작업면은 흰 라벨지 색이다. 시험지·OMR 은유와 둥근 퀴즈 카드는 이 세계의 기본값이 아니다.

밀도는 차분하고 높다. 왼쪽 280px 레일에 문항 행이 장부처럼 쌓이고, 가운데 작업면에서는 큰 번호와 라벨, 문제, 입력이 위에서 아래로 한 줄기로 흐른다. 숫자는 모두 고정폭이라 시간·배점·점수가 세로로 맞는다. 깊이는 그림자가 아니라 초록 틴트 면과 가는 선으로 만든다.

색은 초록 한 가족이다. 보조 글자와 선까지 초록 틴트를 띠고, 빨강은 틀림과 오류에만 나온다. 다섯 단계 초록 띠가 자료마다 하나씩 붙어 라벨·레일·세트 행에서 같은 자료를 같은 색으로 묶는다.

**Key Characteristics:**
- 출처 라벨: 흰 스티커, `--ink-3` 실선, 위쪽 4px 색 띠, 자료 이름 위·위치 아래, 각진 모서리
- 초록 한 가족, 중립 회색 없음, 빨강은 정오표(errata) 전용
- 시스템 고딕 단일 서체, 모든 숫자 고정폭, 모노는 코드에만
- 분량에 비례하는 띠(레일 최대 64px, 세트 최대 160px)
- 그림자 없는 평면, 틴트 면과 가는 선으로 층을 나눈다
- 880px 이하에서 레일이 위쪽 칩 줄로 접힌다

## Colors

서가 안내판의 짙은 초록에서 라벨지의 흰색까지 이어지는 단일 초록 가족에, 정오표 빨강 하나를 더한 팔레트다.

### Primary
- **서가 안내판 초록 (Shelf Green)** (`shelf`): 상단 셸 바, 채워진 주 버튼, 선택된 선택지 원, 정답 태그, 진행 막대와 시간 막대 채움, 맞은 문항 번호와 상태 글자, 링크. 화면의 "확정된 것"을 표시한다.
- **깊은 서가 초록 (Shelf Deep)** (`shelf-deep`): 주 버튼과 셸 바 버튼의 hover에만 쓴다.
- **포커스 초록 (Focus Green)** (`focus`): `:focus-visible` 외곽선(2px, offset 2px). 셸 바 안에서는 흰색 외곽선으로 바뀐다.

### Secondary
- **주차 띠 다섯 단계 (Band 1~5)** (`band-1` ~ `band-5`): 자료마다 하나씩 순서대로 배정되는 초록 단계색. 출처 라벨의 위쪽 띠, 레일 행의 배점 띠, 세트 행의 분량 띠에 같은 자료는 같은 색으로 나온다. 여섯 번째 자료부터는 다시 1번으로 돈다. 매칭 판에서는 개념 타일 위 띠가 `band-1`, 설명 타일 위 띠가 `band-4`다.

### Tertiary
- **정오표 빨강 (Errata Red)** (`errata`): 틀린·일부 맞은 문항 번호와 결과 글자, "아쉬워요" 기준, 오류 메시지, "다시 볼 개념" 제목, 최종 제출을 한 번 더 확인하는 무장(armed) 상태 버튼.
- **정오표 틴트 (Errata Tint)** (`errata-tint`): 오류 상자와 "다시 볼 개념" 패널의 바탕.

### Neutral
- **서가 바탕 (Ground)** (`ground`): 페이지 바탕. 작업면 바깥 전부.
- **라벨지 (Paper)** (`paper`): 시험지와 페이지 카드의 작업면.
- **스티커 흰색 (White)** (`white`): 출처 라벨, 매칭 타일, 입력 칸, 보조 버튼, 패널처럼 작업면 위에 "붙은" 것.
- **먹 초록 (Ink)** (`ink`): 본문 글자. 순수 검정이 아니라 초록이 섞인 먹색이다.
- **보조 먹 (Ink 2)** (`ink-2`): 보조 글자, 메타 정보, 라벨의 위치 줄.
- **연한 먹 (Ink 3)** (`ink-3`): 출처 라벨 테두리, 선택지 원 테두리, "내 답" 태그 테두리, 입력 hover 테두리, placeholder.
- **선 (Line / Line Soft)** (`line`, `line-soft`): 구획선과 테두리. `line`은 레일·목록·헤더 구분, `line-soft`는 문항 사이와 작업면 테두리.
- **틴트 (Tint / Tint Strong)** (`tint`, `tint-strong`): hover 면은 `tint`, 선택·현재·정답 면은 `tint-strong`. 코드 블록과 코드 입력 바탕도 `tint`다.

### Named Rules
**The No-Grey Rule.** 중립 회색은 없다. 보조 글자·선·비활성 상태까지 모두 초록 틴트 토큰(`ink-2`, `ink-3`, `line`, `line-soft`)에서 고른다. 새 회색 hex를 만들지 않는다.

**The Errata-Only Rule.** `errata` 빨강은 틀림, 일부 맞음, 오류, 그리고 되돌릴 수 없는 제출의 확인 단계에만 쓴다. 강조·경고·장식 용도로 쓰지 않는다.

**The One Source, One Band Rule.** 한 자료의 띠 색은 그 화면 안에서 라벨·레일·세트 어디서든 같다. 띠 색으로 상태나 중요도를 표현하지 않는다.

## Typography

**Display Font:** 없음 (단일 서체)
**Body Font:** 시스템 고딕 (`"Apple SD Gothic Neo", "Malgun Gothic", "맑은 고딕", "Noto Sans KR", system-ui, sans-serif`)
**Label/Mono Font:** 시스템 모노 (`ui-monospace, SFMono-Regular, Menlo, Consolas, "D2Coding", monospace`), 코드에만

**Character:** macOS와 Windows의 기본 한글 고딕 하나로 모든 위계를 굵기와 크기만으로 만든다. 오프라인·시스템 폰트 제약을 그대로 받아들인, 안내판처럼 담백한 글자다. 본문은 `word-break: keep-all`로 어절 단위로 줄을 바꾼다.

### Hierarchy
- **Score** (800, 44px / 880px 이하 32px, 1.05, -0.03em): 채점 후 오른쪽 위 점수. 뒤의 "/ 100"은 17px 600 `ink-2`.
- **Headline** (800, 26px, 1.35, -0.02em): 시험지·세트·매칭 페이지 제목.
- **Question Number** (800, 32px, 1): 문항 번호. 결과에 따라 `shelf` 또는 `errata`로 물든다.
- **Question** (500, 17px, 1.7, 최대 68ch): 문제 본문.
- **Answer** (400, 16px, 1.7): 선택지와 답안 입력. 입력칸은 iOS 확대를 피하려고 16px 아래로 내리지 않는다.
- **Body** (400, 15px, 1.6): 기본 본문.
- **Label** (700, 13px, 1.35): 출처 라벨 이름 줄, 결과 글자(14px), 정의 목록 머리(13px).
- **Meta** (400, 12~13px, `ink-2`): 라벨 위치 줄, 시간, 진행, 도움말.
- **Code** (14px, 1.7, 시스템 모노, tab-size 4): `pre`와 코드 입력.

### Named Rules
**The Tabular Numerals Rule.** 시간·배점·점수·문항 번호·진행 수치·라벨 위치는 모두 `font-variant-numeric: tabular-nums`로 쓴다. 숫자가 바뀌어도 열이 흔들리지 않는다.

**The Mono-Is-Code Rule.** 고정폭 서체는 코드 블록과 코드 입력에만 쓴다. 숫자나 라벨에 모노를 쓰지 않는다. 코드 블록의 언어 이름도 고딕이다.

## Layout

시험지는 두 열 격자다. 왼쪽 280px 레일, 오른쪽 작업면, 간격 24px, 최대 폭 1360px, 바깥 여백 24px(아래 72px). 레일은 셸 바 아래 `top: 80px`에 붙어 따라오고, 행이 많으면 레일 안에서 스크롤된다. 작업면 안쪽 여백은 40px 56px 56px.

세트·매칭 페이지는 한 열 카드다. 세트는 최대 880px, 매칭은 최대 1040px, 카드 안쪽 여백 40px 48px 48px. 매칭 판은 개념·설명 두 열(간격 32px)이다.

간격 리듬은 4px 배수를 따른다(4·8·12·16·24·32·40). 문항 사이는 위 40px + 선 + 32px, 되돌릴 수 없는 최종 제출 영역은 레일 맨 아래에 40px 빈 공간을 두고 떨어져 놓인다.

**880px 브레이크포인트.** 창을 채팅 옆 절반으로 줄였을 때를 기준으로 한다. 레일은 작업면 위 가로 칩 줄(테두리 `line`, 모서리 6px, 높이 36px, 간격 6px)이 되고 유형·시간·띠는 숨긴다. 셸 바 상태 줄은 아래로 감기고, 작업면 여백은 24px 20px 32px, 페이지 바깥 여백은 16px 12px 40px로 줄어든다. 세트 행의 띠는 행 아래 줄로 내려간다.

### Named Rules
**The Proportional Band Rule.** 띠의 길이는 분량에 비례하고, 고정된 최대 폭에 맞춘다. 레일 배점 띠는 가장 큰 배점을 64px(높이 3px, 최소 8px), 세트 분량 띠는 가장 많은 문항 수를 160px(높이 4px, 최소 12px)로 둔다. 문항 시간 막대는 160px 트랙 안에서 가장 오래 걸린 문항을 100%로 둔다. 띠를 컨테이너 폭에 늘리지 않는다.

## Elevation & Depth

그림자 없는 평면이다. 층은 바탕(`ground`) → 라벨지 작업면(`paper`) → 붙은 흰 물건(`white`)의 세 단계 명도와 가는 선으로 나뉜다. 상태는 면의 틴트(`tint` hover, `tint-strong` 선택)로 표시한다. `box-shadow`는 그림자가 아니라 링으로만 나온다.

### Shadow Vocabulary
- **입력 포커스 링** (`box-shadow: 0 0 0 3px var(--tint-strong)`): 단답·서술·코드 입력의 `:focus-visible`. 테두리는 `shelf`로 바뀐다.
- **선택 타일 링** (`box-shadow: 0 0 0 2px var(--shelf)`): 매칭 판에서 짝을 고르는 중인 타일.

### Named Rules
**The Flat Sticker Rule.** 라벨과 타일은 종이에 붙은 스티커처럼 납작하다. 떠 보이게 하는 흐린 그림자나 단단한 오프셋 그림자를 쓰지 않는다.

## Shapes

모서리는 쓰임에 따라 네 단계다. 출처 라벨과 매칭 타일은 각진 모서리(0), 유형 칩과 선택지 태그는 4px, 버튼·입력·선택지 행·패널은 6px, 작업면 카드는 8px. 선택지 원은 완전한 원(26px), 복수 선택은 4px 둥근 사각형이다. 띠와 막대만 2px로 끝을 살짝 굴린다. 테두리는 1px이 기본이고, 색 띠만 위쪽 3~4px로 두껍다. 마스코트 아이콘은 흰 원 안에 놓인다.

## Components

### Source Label (서명 컴포넌트)
청구기호 스티커. 이 시스템의 정체성이다.
- **Shape:** 각진 모서리(0), 최소 96px·최대 260px 폭.
- **Border:** 1px `ink-3` 실선, 위쪽만 4px 자료 띠 색(`band-1`~`band-5`).
- **Content:** 두 줄. 위는 자료 이름(13px 700, 넘치면 말줄임), 아래는 정확한 위치(12px `ink-2`, 고정폭 숫자). 출처가 여럿이면 위치 뒤에 "외 N곳".
- **Small:** 레일 밖 목록(다시 볼 개념, 세트 행, 매칭 결과)에서는 여백 6px 10px 5px, 위 띠 3px.
- **접근성:** `aria-label="출처 {이름}, {위치}"`.

### Rail Rows
문항 장부. 행마다 번호(700, 고정폭) | 유형(14px 600) | 풀이 시간(13px `ink-2`, 오른쪽 정렬), 둘째 줄에 상태 글자(12px)와 배점 띠. 행 사이는 1px `line`. hover는 `tint`, 현재 문항은 `tint-strong`. 상태 글자는 답함·맞음이면 `shelf`, 틀림·일부 맞음이면 `errata`. 레일 머리에는 진행률 글자와 4px 진행 막대(`shelf`, 너비 전환 .3s `cubic-bezier(.2,.7,.2,1)`).

### Buttons
- **Shape:** 6px 모서리, 700 굵기.
- **Primary (채움):** `shelf` 바탕, 흰 글자, 높이 46px, 15px. 되돌릴 수 없거나 화면의 주 행동(시험 시작, 최종 답안 제출)에만 쓴다. hover는 `shelf-deep`. 최종 제출은 한 번 누르면 `errata`로 무장되고 확인 문구가 뜬다.
- **Secondary (테두리):** 흰 바탕, 1px `shelf` 테두리, `shelf` 글자, 높이 40px, 14px. 문항마다 반복되는 행동("답 제출하고 정답 보기", 지난 시험 다시 풀기). hover는 `tint`.
- **Quiet:** 테두리·바탕 없음, 높이 32px. 패널 닫기.
- **셸 바 버튼:** 투명 바탕, 반투명 흰 테두리, 높이 32px, hover `shelf-deep`.
- **Disabled:** 불투명도 .55.
- **헷갈렸어요 토글:** 흰 바탕, `line` 테두리, `ink-2` 글자, 선 그림 SVG 표시. 선택되면 `shelf` 테두리·`tint-strong` 바탕·`shelf` 글자.

### Options & Option Tags
선택지 행은 원 번호(26px, 1.5px `ink-3`) + 본문(16px). hover `tint`, 고르면 `shelf` 테두리 + `tint-strong` 면 + 원이 `shelf`로 채워진다. 채점 후에는 상태를 반드시 글자로 붙인다.
- **"내 답" 태그:** 1px `ink-3` 테두리, `ink` 글자, 4px 모서리. 내가 고른 원은 `ink`로 채운다.
- **"정답" 태그:** `shelf` 바탕, 흰 글자. 정답 행은 `shelf` 테두리 + `tint-strong` 면 + 본문 700.
- 두 태그는 행 오른쪽 끝에 6px 간격으로 나란히 선다.

### Result States
결과 줄(14px 700, 고정폭 숫자)은 "맞았어요 10/10점"처럼 글자와 점수로 말한다. 맞음은 `shelf`, 틀림·일부 맞음은 `errata`, 채점 대기는 `ink-2`. 맞은 문항은 결과가 접히고 밑줄 친 "해설 보기"로 펼친다. 틀린 문항은 펼친 채 정의 목록(머리 72px 열)으로 내 답·정답·해설을 보이고, 서술 기준은 "충족"(`shelf`)·"아쉬워요"(`errata`)로 표시한다. 근거 인용은 15px 1.8, 글자 아래 42%에 `tint-strong` 형광펜을 긋는다. 시험 끝의 "다시 볼 개념"은 `errata-tint` 패널에 개념과 작은 출처 라벨을 늘어놓는다.

### Inputs / Fields
- **Style:** 흰 바탕, 1px `line` 테두리, 6px 모서리, 16px. 단답은 최대 420px, 서술은 최대 72ch·최소 높이 140px. 코드 입력은 `tint` 바탕에 모노.
- **Hover:** 테두리 `ink-3`.
- **Focus:** 테두리 `shelf` + 3px `tint-strong` 링.
- **순서 맞추기:** 블록은 흰 바탕 `line` 테두리, 빈 칸은 `ink-3` 점선, 채운 칸은 `shelf` 실선 + `tint`.

### Navigation
상단 셸 바(최소 높이 56px, `shelf`, sticky). 왼쪽에 흰 원 마스코트 + "터틀넥"(16px 700)과 반투명 세로 구분선, 이어서 페이지 제목(600, 말줄임), 오른쪽에 시간(17px 700 고정폭)·저장 상태·셸 바 버튼. 880px 이하에서 상태 줄이 둘째 줄로 감긴다.

### Set Rows
세트 목록의 한 행 전체가 버튼이다. 회차 이름(17px) | 작은 출처 라벨 | 분량 띠 | 상태(13px, 끝났으면 `shelf` 700 "다시 풀기"). 행 최소 높이 64px, 사이는 1px `line`, hover `tint`.

### Match Tiles
흰 바탕, 1px `line` 테두리, 위쪽 4px 띠(개념 `band-1`, 설명 `band-4`), 각진 모서리, 최소 높이 72px. 개념 타일은 700. hover는 `shelf` 테두리 + `tint`, 고르는 중은 `tint-strong` + 2px `shelf` 링, 연결됨은 `tint` 면 + `ink-2` 글자 + 위 띠 `shelf` + "연결됨" 글자.

### Named Rules
**The No-Leak Label Rule.** 아직 연결하지 않은 매칭 타일에는 출처 라벨을 절대 붙이지 않는다. 출처가 같으면 짝이 드러나기 때문이다. 라벨은 연결된 타일과 결과 목록에서만 나타나며, 서버가 연결 전에는 출처를 보내지 않는다.

**The Filled-Means-Final Rule.** 채운 주 버튼은 한 화면에 하나, 되돌릴 수 없거나 화면을 대표하는 행동에만 쓴다. 문항마다 반복되는 행동은 테두리 보조 버튼이다.

**The Say-It-In-Words Rule.** 내 답·정답·맞음·틀림은 색만으로 말하지 않는다. "내 답", "정답", "맞았어요", "틀렸어요" 같은 글자가 항상 함께 붙는다.

## Do's and Don'ts

### Do:
- **Do** 새 화면의 문제·자료·개념에는 출처 라벨(흰 스티커, `ink-3` 1px, 위 4px 띠, 이름 위·위치 아래, 각진 모서리)을 붙인다.
- **Do** 보조 글자와 선은 `ink-2`, `ink-3`, `line`, `line-soft`에서 고른다.
- **Do** 시간·배점·점수·진행 수치에는 고정폭 숫자를 쓴다.
- **Do** 분량을 보여주는 띠는 고정 최대 폭(레일 64px, 세트 160px)에 비례로 맞춘다.
- **Do** 상태 면은 hover `tint`, 선택·현재 `tint-strong`으로 나눈다.
- **Do** 880px 이하에서는 사이드 레일을 위쪽 칩 줄로 접는다.

### Don't:
- **Don't** 중립 회색(#888, #ccc 같은 무채색)을 쓰지 않는다.
- **Don't** `errata` 빨강을 틀림·오류·되돌릴 수 없는 제출 확인 밖에서 쓰지 않는다.
- **Don't** 웹폰트나 외부 CDN을 쓰지 않는다. 시스템 고딕 하나, 코드만 시스템 모노.
- **Don't** 문항마다 반복되는 행동을 채운 주 버튼으로 만들지 않는다.
- **Don't** 연결 전 매칭 타일에 출처 라벨을 붙이지 않는다.
- **Don't** 라벨이나 타일을 둥근 카드로 만들거나 그림자로 띄우지 않는다.
- **Don't** 정답·내 답을 색만으로 구분하지 않는다.
