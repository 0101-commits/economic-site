# 미분양·착공 수집기 · KOSIS 호출 정비 · 경제 일정 표 · 해외 휴장 달력 — 설계

작성 2026-10-01. 9/30 데이터 확보 고도화(Claude Docs `6ef93b17`)의 「결정 대기 4건」을 닫는다.
사용자 결정(2026-10-01): 네 갈래 모두 권고안 채택.

## 0. 실측 (설계 근거)

| # | 사실 | 출처 |
|---|---|---|
| F1 | R-ONE 표 목록에 진짜 표 4건이 있다 — `T237973129847263` 미분양주택현황 · `T233033129823134` 주택착공실적 · `T235263129553687` 주택건설인허가실적 · `T237273130004614` 주택준공실적 (+ `T248033134256192` 준공연도별 규모현황은 연간) | 10/1 09:07 일일 런 36794587089 `[R-ONE-probe]` |
| F2 | T 표의 항목(ITM)·지역(CLS) 차원은 미확인. `fetch_rone_nationwide_latest` 는 `CLS_ID=500001` 전국 → 없으면 이름 「전국」 행으로 고르는데, 항목이 여럿이면(총계/민간/공공·규모별) `_rone_pick_nationwide` 가 시점 키로 덮어써 임의 항목이 잡힌다 | `fetch_data.py:3758~3811` |
| F3 | 옛 키 `unsold_kr`·`start_kr` 는 묘비(`data_sla.TOMBSTONED`) — 같은 키로 되살리면 preserve 가 옛 전세가 값을 다시 꺼낸다 | `data_sla.py:333` |
| F4 | `fetch_kosis_series` 는 `statisticsData.do`(자료등록 방식, `userStatsId` 필수)에 `userStatsId=""` 로 보내고 `objL1` 기본값이 `itmId` 다. 공식 통계표선택 방식은 `Param/statisticsParameterData.do`. 호출처는 소매판매 폴백 1곳뿐이고 ECOS 정식 표(901Y100) 복구 뒤 안 탄다 — `sourceStatus` 에 `kosis.kr` 이 한 번도 없다 | `fetch_data.py:158, 4237~4281, 7166` · 9/30 조사 |
| F5 | 통계누리 기준 최신 시점 2026-08: 전체 미분양 69,134호(2080) · 준공후 28,080(5328) · 착공 18,013p(5386) · 준공 15,151p(5372) · 인허가 누계 163,935p(1946, 월분 = 차분) | 9/30 조사 + 리드 직접 확인 |
| F6 | 경제 일정 표는 열 8개(일시·국가·이벤트·중요도·이전·예측`c-opt`·실제·알림). 390 게이트는 통과하나 위젯 안에서 40px 가로 스크롤. 행 클릭 상세 패널(`#calEventDetail`) 있음 → `.c-opt` 사용 조건 충족 | `index.html:4257~4273` · `js/app1.js:9041~9072` |
| F7 | 해외 휴장 판정은 `send_kakao_digest.yahoo_prev_bar_ok()` 한 곳. 해외 대상 = `^GSPC` 하나(`check_swings`). 지금은 「직전 평일」이라 미국 연휴 다음 날 S&P500 속보가 보류된다(연 9일 안팎) | `send_kakao_digest.py:1514~1539` · `check_swings.py:39~45` |
| F8 | NYSE 휴일 ≠ 미국 연방 공휴일(성금요일은 NYSE 만, 콜럼버스·재향군인의 날은 연방만). Nager.Date 미국 달력을 쓰면 연 3일 어긋난다 | NYSE 휴장 규정 |

## 1. 미분양·착공·인허가·준공 수집기 — R-ONE T 표

**원칙**: 새 함수 없이 `extra_stats` 목록에 4행을 더한다. 단 **항목이 둘 이상인 표는 값을 싣지 않고 로그만** 남긴다(F2) —
탐침과 수집을 한 코드로 한다. 첫 일일 런 로그로 `ITM_ID` 를 확정해 목록에 적는 것이 2단계.

```
extra_stats += [
  ("unsold_total_kr",      "전국 미분양주택 (호)",        "T237973129847263", "호",  itm=None→탐침),
  ("housing_start_kr",     "전국 주택 착공실적 (호)",      "T233033129823134", "호",  itm=None→탐침),
  ("housing_permit_kr",    "전국 주택건설 인허가실적 (호)", "T235263129553687", "호",  itm=None→탐침),
  ("housing_complete_kr",  "전국 주택 준공실적 (호)",      "T237273130004614", "호",  itm=None→탐침),
]
```

- **전국 코드는 표마다 다르다**(2026-10-01 키 없이 실측): T 표 분류 코드는 5자리 정수 — 착공·준공 전국>총계 `50019`,
  인허가 전국>합계(동수기준) `50023`, 미분양은 2000~2006년 `50266` 전국>계만 확인(2007년 이후 미확인, 같은 `50019` 가
  미분양 표에선 서울>종로구). `CLS_ID=500001` 은 T 표에서 INFO-200 이고, 무필터로 넘어가면 서버가 오래된 순 전체(착공 66,957행)를
  줘 1,000행에서 잘린다. 그래서 `extra_stats` 행마다 전국 코드(`cls`)를 적고 `fetch_rone_nationwide_latest(..., cls_id=)` 로
  그 코드 한 번만 묻는다(strict 는 500001·무필터 재시도 없음). 전국 코드면 전체 이력이 1,000행 안에 든다(착공 187·준공 193·인허가 235).
- **검사(`_rone_strict_pick`)** — 항목(ITM)만 세면 10001 하나라 헛통과한다. 전국 하위 행(전국>총계·전국>공공부문>소계·…)이
  시점마다 여럿이라 시점 키로 덮으면 마지막 행이 잡힌다 → `CLS_FULLNM` 이 「전국」으로 시작하는 행을 (CLS_ID, ITM_ID) **조합**으로 센다.
  (a) 시점당 조합 2종 이상 (b) 행 수 ≥ limit(잘림 — 오래된 순이라 최신이 빠진다) (c) 전국 행 0 → `None` + 조합 목록 로그.
- **전국 코드 미확인(cls=None, 미분양)** = 값 대신 탐침: 지난달부터 4개월을 거슬러 단일 월(`WRTTIME_IDTFR_ID`) 무필터 질의로 그 달 전체 행을
  받아 「전국」 행의 (CLS_ID, CLS_FULLNM, ITM_ID, ITM_NM, DTA_VAL) 을 `[R-ONE] T…: 전국 후보` 로 로그. 그 로그로 코드를 확정해 적는다.
- **R-ONE 은 통계누리보다 1개월 늦다** — 착공 최신 202607(20,378 = 통계누리 7월값), 202608 은 INFO-200.
- 인허가는 **연간 누계**(2007년 1~5월 12,038→29,789→49,827→69,013→99,606) — `cumulative=True` 로 월분 = 당월 − 전월(1월은 그대로,
  전월이 없으면 그 달은 뺀다), value·prev·chg 도 월분 기준. desc 에 「(월분, 연간 누계 차분)」.
  (현행 `_rone_pick_nationwide` 는 거래현황(A_2024_00549)처럼 `itm_id` 를 명시해 부르는 비 strict 경로에선 영향 없음.)
- 준공후 미분양(5328 상당)은 T 표 안에 항목으로 있으면 `unsold_completed_kr` 로 2단계에 추가, 없으면 범위 밖.
- 옛 키는 묘비 유지(F3). 새 키만 쓴다.
- **판정표** `RANGE_RULES` 4행: 미분양 10,000~200,000 · 착공 3,000~100,000 · 인허가 3,000~150,000 · 준공 3,000~100,000(호, 전국 월).
  주기는 `infer_cadence` 가 월간으로 알아낸다(손으로 일수 안 적음).
- **레지스트리**: `build_indicators.LABEL` 4행(「미분양주택 (전국)」·「주택 착공 (전국)」·「주택 인허가 (전국)」·「주택 준공 (전국)」),
  미분양·착공 tier 2, 인허가·준공 tier 3. `realestate.kr` 잎은 자동 등록(F: app0.js 에 avg_jeonse 가 자동으로 섰다) — 재생성 + `--check`.
- **화면**: 부동산 화면 전세 2행(`index.html:4797`) 옆에 같은 부품(`seed-list-item__root econ-row` + `showReHistoryChart`)으로 4행,
  `js/app3.js` 경로 맵 4키, `js/app1.js` `setKrReCard` 4줄. 값 서식 = 호(천 단위 쉼표). 결론 줄은 손대지 않는다.
- **lane**: `rone` 묶음에 자동 포함(`realestate.kr` 전부) — 일일 3회, 매시는 preserved 잎 있을 때만.
- 2순위 폴백 = §2 의 KOSIS Param(`DT_MLTM_2080/5386/5372/1946`). R-ONE 이 두 일일 런 연속 실패일 때만.

## 2. KOSIS 호출 정비

- `KOSIS_PARAM_BASE = "https://kosis.kr/openapi/Param/statisticsParameterData.do"`. `fetch_kosis_series` 가 이 주소로
  `method=getList · apiKey · orgId · tblId · itmId · objL1..objL8(준 것만) · prdSe · startPrdDe/endPrdDe · format=json · jsonVD=Y` 를 보낸다.
  `userStatsId` 제거. `obj_l1` 기본값 `itmId` → `"ALL"`.
- KOSIS 는 오류도 HTTP 200 + `{"err": …}` 로 준다 → dict 응답이면 실패로 로그하고 `None`.
- 호출은 모듈 `requests`(= `_HostBreaker`)를 그대로 타므로 `sourceStatus["kosis.kr"]` 가 저절로 생긴다 — 정비 뒤 첫 런에서 이 키가 생기는지가 검증.
- 소매판매 폴백 후보는 그대로(`DT_1JG2105`·`DT_1KI2017`), `objL1=ALL`.
- 미분양 2순위용 `fetch_kosis_housing()` 는 **메타 탐침 뒤**에만 붙인다 — 일일 런에서 `getMeta type=ITM` 4표를 로그(`[KOSIS-probe]`),
  코드가 확정되면 `objL1`(지역=전국 코드)·`itmId` 를 적어 넣는다. 탐침 전에 `ALL/ALL` 로 값을 싣지 않는다(F2 와 같은 이유).
- 테스트: `requests.get` 을 가짜로 바꿔 URL 이 Param 주소이고 `userStatsId` 가 없고 `objL1=ALL` 인지, `{"err"}` 응답이 `None` 인지.

## 3. 경제 일정 표 — 390 넘침

- `<th>중요도</th>`·`<th>알림</th>` 과 해당 `<td>` 에 `c-opt`(≤480 접힘). 이벤트 칸에 `<span class="cal-stars-m">★★★</span>` 를 넣고
  CSS `.cal-stars-m{display:none}` · `@media (max-width:480px){.cal-stars-m{display:inline}}` — 별이 모바일에서 이름 밑으로 간다.
- 접힌 「알림」은 상세 패널(`#calEventDetail`) 머리줄에 같은 `toggleCalAlert(idx, btn)` 버튼으로 되살린다(★★★ 만). 숨긴 값이 어디서도
  안 보이면 그건 접는 게 아니라 잃는 것 — CLAUDE.md `.c-opt` 규칙.
- 데스크톱 불변. 게이트: `shots.mjs --page=calendar` · `mobile-readability`(M4·M7) · `structure` · `readability2`.
  추가 확인 = 390 에서 `#calendarTable` 의 `scrollWidth ≤ clientWidth`(위젯 안 가로 스크롤 0).

## 4. 해외 휴장 달력 — NYSE 규칙 계산

- 새 모듈 `scripts/nyse_calendar.py`(stdlib 만): `holidays(year) -> set[date]` · `prev_trading_day(d) -> date`.
  휴일 10종: 신정(토요일이면 관측 없음·일요일→월) · 마틴루터킹(1월 셋째 월) · 대통령의 날(2월 셋째 월) · 성금요일(부활절−2, 계산식) ·
  현충일(5월 마지막 월) · 준틴스(6/19 관측) · 독립기념일(7/4 관측) · 노동절(9월 첫째 월) · 추수감사절(11월 넷째 목) · 성탄절(12/25 관측).
  관측 규칙 = 토→금, 일→월(신정 토요일 예외). 조기 폐장은 무관. **임시 휴장(국장일 등)은 못 본다** — 그날은 종전처럼 보류(안전 쪽).
- `yahoo_prev_bar_ok`: 국내가 아니면 `want = nyse_calendar.prev_trading_day(days[-1])`. 다른 변경 없음.
- 테스트(`test_nyse_calendar.py`): 2026-04-06(월, 성금요일 다음) → 04-02 · 2026-07-06 → 07-02(7/3 관측) · 2026-11-27 → 11-25 ·
  2026-05-26 → 05-22 · 2022-01-03 → 2021-12-31(신정 토요일 미관측) · 2026-10-13(콜럼버스 다음 날, NYSE 개장) → 10-12.

## 5. 순서·검증

| 단계 | 일 | 검증 |
|---|---|---|
| P0 | §4 NYSE 달력 + §3 일정 표 (각각 반나절 미만, 독립) | 테스트 6건 · UI 게이트 4종 exit 0 |
| P1 | §1 R-ONE 4행 + 모호성 가드 + 판정표·라벨 + 화면 4행 → 푸시 → **일일 런 1회**(수동 dispatch mode=daily) 로그 확인 | 로그에 값 3건(착공·준공·인허가) + 미분양 `전국 후보` 탐침 줄 |
| P1′ | 탐침 결과로 미분양 전국 `cls` 확정 → 두 번째 런에서 값 4건, 건강표 ok | `data.json.realestate.kr` 4키 · suspect 0 · 통계누리 **한 달 전** 값과 일치(R-ONE 이 1개월 늦다 — 착공 202607 = 20,378) |
| P2 | §2 KOSIS Param 정비 + `[KOSIS-probe]` getMeta 로그 | 테스트 · 다음 런 `sourceStatus["kosis.kr"]` 생성 |
| P3 | KOSIS 2순위 `fetch_kosis_housing()`(탐침 코드 확정 뒤) | R-ONE 을 끄고 돌린 런에서 같은 값 |

## 6. 범위 밖

- 국토부 발표일을 경제 일정에 싣는 것(보도계획 페이지 파싱) — 발표일이 「익월 말」로만 공시돼 고정 날짜가 없다. 후속.
- 시도별 미분양(2082·시군구) — 전국 집계만. 지도 드릴다운은 가격지수 것을 그대로.
- 통계누리 무키 `data.do` — 비공식 경로라 폴백에서도 뺀다.
