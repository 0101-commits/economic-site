# 구조 벤치마크 개편 — 구현 계약 (2026-10-14)

기획서: https://claude.ai/artifact/GyqoCcuvAqNAmWRoYUpqmD (「ecom 구조 벤치마크 개편안」 판 2).
근거: 네이버·토스 증권 리버스엔지니어링(`자료/증권4종_리버스엔지니어링/`) + ecom 현행 코드·라이브 화면(2026-10-14 장중).
결정: 기획서 결정 1~6 은 모두 권고안으로 확정(사용자 「기획서대로 작업 진행」, 2026-10-14).

| 결정 | 확정 |
|---|---|
| 1 AI 요약 근거 없는 문장 | 버리고 「뺀 문장 n」만 표시 |
| 2 종목 「왜」 문장 | 규칙이 재료를 고르고 AI 는 다듬기만(새 사실 금지, 실패하면 규칙 문장) |
| 3 종목별 기사 | 네이버 뉴스 검색 API, 최대 30종목, 장중 풀 런(매시) |
| 4 PC 오른쪽 패널 | 1440 이상 펼침, 그 아래는 아이콘 줄 + 누르면 덮개 |
| 5 새 판 알림 | 띠만, 사용자가 누를 때만 새로고침 |
| 6 넥스트레이드 | 표시하지 않음 |

## 과제 → 갈래

| 갈래 | 과제 | 주로 고치는 파일 |
|---|---|---|
| data-a | 1(자료) · 4(자료) · 5(자료) · F1 원인 | `scripts/build_bundles.py`(market · meta) · `scripts/ai_briefing.py` · `scripts/collect_site.mjs` · `.github/workflows/fetch-data.yml`(briefs 커밋) |
| data-b | 2(자료) | 새 `scripts/stock_reasons.py` · `scripts/build_bundles.py`(home.reasons 한 곳) · `.github/workflows/fetch-data.yml`(새 단계) |
| worker | 6(서버) | `cloudflare-worker/worker.js` · 새 `cloudflare-worker/test_quotes.mjs` |
| app-core | 4 · 5 · 9 · 10 · 11 (화면) | `app/src/lib/{bundle,refresh,format}.ts` · `components/{ui,panels}.tsx` · `App.tsx` · `main.tsx` · `vite.config.ts` · `screens/{Market,Detail,My}.tsx` · `Home.tsx` 머리(장 상태 줄)만 |
| app-feat | 1 · 2 · 3 · 6 · 7 · 8 (화면) | `screens/Home.tsx`(AI 요약 · 관심 칸 · 거래대금 표) · `components/detail/{Stock,parts}.tsx` · 새 `components/home/Brief.tsx` · 새 `components/Rail.tsx` · `components/personal/SearchOverlay.tsx` · `lib/personal/{quotes,store}.ts` |

같은 파일을 두 갈래가 고치면(`Home.tsx` · `App.tsx` · `build_bundles.py` · `fetch-data.yml`) 서로 다른 부분만 고친다. 합치기는 팀장이 한다.

## C1. 장 상태 — 묶음 `market` (과제 4, data-a → app-core)

홈과 모든 `market-*` 묶음의 `market`. 기존 칸은 그대로 두고(옛 화면 · 알림 호환) 칸을 더한다.

```jsonc
"market": {
  "state": "open", "label": "정규장", "today": "2026-10-14", "session": "2026-10-14",
  "nextOpen": "2026-10-15T09:00:00+09:00", "calendarKnown": true,          // 기존 그대로
  "openAt":  "2026-10-14T09:00:00+09:00",   // 오늘 개장 시각(장이 서는 날만, 아니면 null)
  "closeAt": "2026-10-14T15:30:00+09:00",   // 오늘 정규장 마감(장이 서는 날만, 아니면 null)
  "us": {
    "state": "pre|open|after|closed|holiday",   // 장 전 04:00~09:30 · 정규 09:30~16:00 · 장 뒤 16:00~20:00 (뉴욕 시각), 그 밖 closed, 거래일 아님 holiday
    "label": "장 전|정규장|장 뒤|마감|휴장",
    "session": "2026-10-13",                     // 마지막(또는 지금) 정규 세션 날짜(뉴욕)
    "openAt":  "2026-10-14T22:30:00+09:00",     // 다음(또는 지금) 정규장 개장 — 한국 시각 ISO
    "closeAt": "2026-10-15T05:00:00+09:00",     // 그 세션 마감 — 한국 시각 ISO
    "nextOpen": "2026-10-14T22:30:00+09:00"
  }
}
```
- 미국은 `nyse_calendar` 로 계산(지금 `us_market` 이 하는 일). 서머타임은 `zoneinfo` 가 맞춘다.
- 넥스트레이드(NXT)는 싣지 않는다(결정 6).

## C2. 다시 읽기 — `bundles/meta.json` (과제 5, data-a → app-core)

```jsonc
"nextAt": "2026-10-14T14:41:30+09:00",   // 다음 묶음이 사이트에 올라올 것으로 보는 시각(다음 수집 + 배포 여유 90초)
"hashes": { "home": "a1b2c3d4", "market-domestic": "…", … }   // 묶음별 내용 지문(sha1 앞 8자) — 화면은 바뀐 묶음만 받는다
```
- `nextAt` 규칙: 국내 정규장 창(장 서는 날 09:00~15:59 KST)과 미국 창(미국 거래일 UTC 13~21시)에는 다음 5분 칸(:00 :05 …) + 90초.
  그 밖에는 Worker 크론의 다음 런(매시 :07 풀 · :35 경량 중 먼저) + 120초. 국내 장 마감 뒤 15:35 칸은 반드시 포함된다(창이 15:59 까지).
- `generatedAt` 은 그대로 둔다(옛 화면 호환). 지문은 `generatedAt` 이 아니라 묶음 내용으로 만든다.

## C3. AI 요약 근거 — `home.brief` + `briefs/YYYY-MM-DD.json` (과제 1, data-a → app-feat)

```jsonc
"brief": {
  "asOf": "2026-10-14T14:22:00+09:00", "source": "gemini|openai|rule", "day": "2026-10-14",
  "lines": ["…", "…"],                                    // 기존 호환(글자만)
  "items": [{ "text": "코스피가 …줄었습니다.", "refs": [1, 2, 3] }],
  "sources": [
    { "n": 1, "kind": "지표", "label": "KOSPI 6,077.57 ▲1.19%", "at": "14:35" },
    { "n": 2, "kind": "수급", "label": "외국인 −4,907억 · 12일 연속 순매도", "at": "14:15" },
    { "n": 3, "kind": "기사", "label": "코스피, 외국인 7일째 '팔자'에 …", "src": "뉴스1", "url": "https://…", "at": "13:51" },
    { "n": 5, "kind": "일정", "label": "미국 CPI (전월비) · 21:30 · ★★★" }
  ],
  "dropped": 1,                     // 대조에서 버린 문장 수
  "check": { "numbers": 3, "schedule": 1 }   // 대조를 통과한 숫자 · 일정 언급 수
}
```
- `briefs/2026-10-14.json` = `{ "date": "2026-10-14", "runs": [ { "at": "14:22", …brief 와 같은 칸(asOf 제외) } ] }`.
  풀 런마다 끝에 하나 더한다(같은 `at` 이면 바꿔 끼움). 30일 지난 파일은 지운다. Pages 허용 목록에 `briefs/` 를 넣는다.
- 근거 목록은 요약 **전에** 스냅샷에서 번호를 매겨 만들고 AI 에 준다. 문장 끝 `[1][2]` 를 읽어 `refs` 로 뺀다.
- 대조(문장 하나라도 걸리면 그 문장을 버림):
  1. 문장 속 숫자가 근거 칸 숫자에 있음(반올림 차 허용, 날짜·시각·순서 숫자 제외)
  2. 일정 언급이 일정표와 맞음(기존 `_calendar_conflict`) + 「발표 없」류 문장인데 근거에 오늘 일정이 있으면 버림
  3. 금지 낱말: 스냅샷 · 묶음 · 데이터셋 · JSON · 상대 시점어(기존 `SLOT_LINE_BANNED`)
  4. `refs` 가 없는 문장
  남은 문장이 2줄 미만이면 규칙 요약(`rule_based_lines`)으로 — 그때 `items` 의 refs 는 규칙이 쓴 근거 번호.
- F1 원인: 스냅샷 `upcoming` 이 `not e.get("act")` 로 고르는데, 미국 CPI 처럼 발표 전에 `act` 칸이 차 있는 일정이 빠졌다
  (10/14 14:35 묶음 CPI act +0.4%, 21:30 발표). 발표 여부는 `check_releases.release_due` 같은 시각 판정으로 고르고,
  `act` 가 발표 전에 차는 원인(수집기)은 찾아서 고치거나 이유를 남긴다.
- 수급 근거의 연속 일수는 묶음 값(`investor_rows`)으로 센다 — 기사 제목 숫자(「7일째」)를 쓰지 않는다.

## C4. 종목 「왜 움직였나」 — `data.json.stockNews` · `stockReasons` → `home.reasons` (과제 2, data-b → app-feat)

- 대상: 거래대금 상위 20 + 관심 목록(`corpEvents` 대상 고르기와 같은 함수 재사용), ETF 빼고 최대 30종목.
- `scripts/stock_reasons.py`(풀 런, 장 서는 날 08~20시 KST): 네이버 뉴스 검색(`NAVER_CLIENT_ID/SECRET`, `sort=date`, 종목 이름 + 「주가」 등)으로
  종목별 오늘 기사 제목 → `data.stockNews = {asOf, items:{code:[{title,url,src,at}]}}`(제목에 종목 이름이 든 것만, 24시간 안).
- 재료(있을 때만): ① 지수 동행(같은 방향, 종목 등락과 시장 지수 등락 차이 1%p 안) ② 최근 10일 공시(`corpEvents`) ③ 오늘 기사 제목
  ④ 52주 신고가 · 신저가(`rankingsKr.high52/low52`). 재료 0 = 그 종목은 싣지 않는다.
- 규칙 문장 → Gemini 다듬기(입력 문장·재료만, 60자 안, 새 숫자 금지 — 출력 숫자 ⊆ 입력 숫자, 금지 낱말) → 실패하면 규칙 문장.
- `data.stockReasons = {asOf, items:{code:{line, rule, source:"rule|gemini", at, refs:[{kind:"지수|공시|기사|신고가|신저가", label, url?, at?}]}}}`
- 묶음: `home.reasons = {asOf, items:{…같은 모양}}` — `at` 이 오늘이 아니면 싣지 않는다.

## C5. Worker `/quotes` (과제 6, worker → app-feat)

```
GET /quotes?codes=466920,000660,AAPL      (최대 30, 쉼표)
200 { "asOf": "2026-10-14T05:22:00Z", "items": { "466920": { "price": 23380, "prev": 23035, "pct": 1.4977, "exchange": "KSC", "at": "2026-10-14T05:22:32Z" }, … } }
```
- 국내 6자리: `.KS`(거래소 KSC) → 안 되면 `.KQ`(KOE), `instrumentType` MUTUALFUND 는 버림 — `app/src/lib/personal/quotes.ts` `parseChart` 와 같은 규칙.
- 미국: 티커 그대로(점 → 줄표). 못 받은 코드는 `items` 에서 뺀다.
- 코드마다 60초 보관(Cache API 또는 모듈 Map). 동시 요청 6개까지. 남용 방지는 기존 제한기 방식.
- 공개 시세라 인증 없음. 관심 목록을 어디에도 저장하지 않는다.

## C6. 화면 (app-core · app-feat)

- **장 상태 줄**(app-core, `ui.tsx` `MarketLine`): 「국내 정규장 · 15:30 마감까지 55분」 「미국 장 닫힘 · 오늘 22:30 개장」, 마감 뒤 「국내 마감 · 내일 09:00」,
  휴장 「국내 휴장 · 다음 개장 M/D 09:00」. 홈 · 시장 머리에. 화면 안 자체 판정(`refresh.inSession` · `format.lastWeekday` · `CLOSE_HM`)은 묶음 `market` 으로 바꾼다
  (묶음이 없을 때만 지금 판정을 대신 쓴다).
- **칸 시각**(app-core, `StripCard`): 장 상태와 같으면 시각을 숨김, 다르면 「10/13 종가」 「10/9 값」. 바뀐 값 1초 옅은 바탕(`prefers-reduced-motion` 이면 끔).
- **다시 읽기**(app-core, `bundle.ts`): `nextAt`+30초에 meta → 지문이 바뀐 묶음만. `nextAt` 이 없거나 지났으면 5분 규칙. 숨은 탭은 읽지 않고 돌아오면 `nextAt` 이 지났을 때 즉시.
  종목 상세 · 내 자산도 rev 를 구독.
- **새 판 알림**(app-core): 빌드 때 `version.json`(`{build}`)을 dist 에 쓰고 앱에 같은 값을 넣는다. 다시 읽기 때 비교, 다르면 머리 아래 띠 「새 화면이 나왔습니다 [새로고침] [닫기]」.
- **칸막이**(app-core): `Panel` 안과 화면(라우트) 단위에 오류 칸막이. 칸 안 「이 칸을 그리지 못했습니다 · 다시 시도」. 사용 기록에 횟수만(`usage.ts`).
- **첫 화면**(app-core): 마지막 홈 묶음 + meta 를 localStorage 에 두고(24시간), 다음 열기 때 먼저 그린 뒤 머리에 「HH:MM 값 · 새 값 받는 중」.
- **AI 요약**(app-feat, `components/home/Brief.tsx`): 문장 끝 근거 번호 · 근거 목록 · 대조 한 줄 · 「참고용」 꼬리말 · 회차 넘김(`briefs/<day>.json`). 모바일은 2줄 + 접힘.
  `items` 가 없으면 지금처럼 `lines` 만.
- **종목 상세**(app-feat): 머리 「005930 · 코스피 · 거래대금 2위」 / 값 / 「▲4,000원 (1.72%)」 / 꼬리 「어제보다 · 14:30 · 정규장」(기준 시각 한 곳),
  「왜 움직였나」(추정 · 작성 시각 · 근거 칩, 근거 0 이면 칸 없음), 「이 종목 공시」(`market-domestic.views.corpEvents` 의 그 종목), 「함께 볼 것」(같은 시장 지수 + 거래대금 이웃 2).
- **관심 값**(app-feat): 묶음에 없는 관심 · 보유 종목 코드를 모아 `/quotes` 한 번. 홈 관심 칸 · 오른쪽 패널 · 내 자산이 같은 함수.
- **오른쪽 패널**(app-feat, `components/Rail.tsx`): 관심 · 최근 본 · 알림 · 일정. 1440 이상 펼침, 980~1439 아이콘 줄 + 덮개, 모바일 없음. 열림 · 탭은 localStorage.
- **검색**(app-feat): 최근 본 = 상세를 연 것 전부(최대 8), 행마다 값 · 등락, 방향키 이동, 메르 글은 2자 이상 입력할 때 받음, 부동산 주소 `realestate`.
- **거래대금 표**(app-feat): PC 에서 `home.reasons` 가 있는 행만 이름 아래 회색 한 줄.

## 지킬 것

- 지어내지 않는다 — 값이 없으면 칸을 그리지 않거나 「—」. 근거 없는 이유 줄 금지.
- 새 글자는 우리말, 장식 금지(색 띠 · 그라데이션 · 그림자 · 이모지) — `app/src/styles/tokens.css` 머리 주석.
- 검사: `npm test --prefix app` · `python -m pytest scripts/tests -q` · Worker `node cloudflare-worker/test_*.mjs`. Playwright 화면 게이트는 팀장이 합친 뒤 한 번에.
- 커밋 메시지에 배포 명령 글자(wrangler deploy 등) 쓰지 않는다. 비밀값 출력 금지.
