# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Korean economic dashboard: static single-page app (GitHub Pages) + GitHub Actions data pipeline + Cloudflare Worker CORS proxy.

Live site: `https://0101-commits.github.io/economic-site/`

## No Build Step

**No npm, no bundler, no compilation.** The site is a single `index.html` (~22 000 lines) with all CSS and JavaScript inline. Edit `index.html` directly. Changes to `index.html` are live on GitHub Pages immediately after push.

The one exception is the **design-token block**, which is generated — see *Design system* below.

## Design system — SEED (당근)

**Since the SEED 개편 (P0–P4, 2026-09-08) the token source is `@seed-design/css@2.7.0`,
vendored at `css/seed/seed.css`.** The astryx *generator* is gone — its 291-token
block and the navy/contrast skins were deleted in P4. What remains of astryx is
its **naming**: the site's internal API is still `--color-*` / `--font-size-*` /
`--c-*`, and a single bridge block defines those names in terms of `--seed-*`:

```
@seed-design/css (css/seed/seed.css)   ← scripts/vendor_seed_css.py 로 갱신
  → SEED 브리지 (index.html, html:root{})  --color-* / --font-size-* → --seed-*
    → 별칭 --c-* 20종                       사용처 3,500곳이 여기만 본다
      → 인라인 style / 클래스 / SEED recipe
```

`scripts/legacy/astryx/`(`econ.theme.ts` + `build_astryx_tokens.py`) is **no longer part of the
pipeline** — do not regenerate that block. Editing colors means editing the
bridge. Chart series colors (9 hues, light/dark) live in the bridge as hex,
because SEED has no categorical palette and its chromatic ramps collide with
brand/market colors.

Rules that follow from this:

- **Colors, sizes, radii, motion come from `--seed-*` — but reference them through
  the existing `--color-*` / `--c-*` names** unless you are writing a new
  `.econ-*` component or overriding a recipe. Only the bridge and `.econ-*`
  definitions touch `--seed-*` directly.
- **Brand is blue, not carrot.** `:root:root{}` + `:root:root[data-seed-color-mode="dark-only"]{}`
  override the 8 brand tokens (light `blue-800 #135fcd` / dark `blue-700 #41a2f9`).
  Both blocks are required — dropping either loses to base.css's own definitions.
- **Market direction uses the palette directly**, never `fg-positive`/`fg-critical`
  (Korea reads red as *up*). Text = 800 (light) / 700 (dark); shapes and chart
  lines = one step stronger (`--c-up-fill` / `--c-down-fill`, `window.CUPF`/`CDNF`).
  `_UPDN`, `_UPDN_FILL`, and the bridge must agree — `vendor_seed_css.py` diffs them.
- **Theme = two attributes in lockstep**: `html.light` (site) and
  `html[data-seed-color-mode="light-only"|"dark-only"]` (SEED). Any place that sets
  one sets the other (FOUC block, `toggleTheme`, `applyStoredTheme`).
- **Component classes are SEED recipes** (`.seed-badge__root--tone_warning-variant_weak`
  등). Size/layout are compound classes; state is one style hook (`[data-checked]`,
  `[aria-selected]`, `[aria-pressed]`, `[data-current]`) plus the matching ARIA.
  `python scripts/check_seed_classes.py` fails the build on a class the vendored
  CSS doesn't define.
- **UI gate before push**: `python -m http.server 8080` then
  `node tests/ui/shots.mjs --page=<page>` — 16 shots (390/768/1280/1440 × light/dark
  × kr/global) plus console-error, brand-token and theme-sync assertions.
- The astryx generated block and the `navy`/`contrast` skins are **deleted** (P4).
  `econ_skin` is removed from localStorage on read; `settingsSetSkin` is a no-op
  that says so once. Light/dark are the only themes.

The three astryx rules below still hold — they are the reason SEED was adopted:

1. **Semantic tokens, never hardcoded values.** Colors come from `var(--color-*)`
   (or the legacy `var(--c-*)` alias layer). No hex literals in CSS or in
   `style=""` attributes.
2. **Color means data.** Surfaces, borders and text are pure grayscale. Hue is
   reserved for market direction (`--c-up`/`--c-down`), status
   (success/warning/error), and chart series (`--color-series-1…9`).
3. **Dense data renders as rows, not cards.** `.widget`/`.kpi-card` are widget
   containers; lists and tables are edge-to-edge rows with dividers and
   32–40 px row height. Don't wrap list items in cards.
4. **Never set `font-size` or `font-weight` by hand.** Use the scale
   (`--font-size-xs` … `--font-size-5xl`), which the bridge maps onto SEED's
   t-scale (xs→t1 11px · sm→t2 12 · base→t4 14 · lg→t6 18 · xl→t7 20 · 2xl→t9 24),
   or a SEED text recipe (`.seed-text--textStyle_t4Bold`). Two scales must not
   coexist. Weights are 400/500/700 only — SEED has no 600, so `semibold` maps
   to bold. Off-scale values (11, 13, 15, 18, 22 px hardcoded) are what made the
   old UI drift by 1–2 px between screens.
5. **Chart colors come from tokens, never literals.** Categorical series use
   `getThemeColors().series` (9 hues); the interactive blue is
   `getThemeColors().accent`. Market up/down (`window.CUP`/`CDN`) must not be
   mixed into a categorical palette — a slice colored red then reads as
   "down" rather than "category 6".

Token pipeline — **there is no generator any more.**

```
@seed-design/css@2.7.0  →  scripts/vendor_seed_css.py  →  css/seed/seed.css
                              (base.css + recipe 41종, 검사 3종)
index.html  html:root{}      브리지 — 사이트 이름을 --seed-* 로 정의(색 53 + 스케일 30)
            :root:root{}     브랜드 8토큰 blue 재매핑(+ dark-only 블록)
```

Editing a color = editing the bridge. `scripts/legacy/astryx/`(`econ.theme.ts`,
`build_astryx_tokens.py`, `patch_astryx*.py`) are **provenance only** — the block
they produced was deleted in P4 (deletion evidence: no name that only that block
defined is still referenced). Do not run them.

Gates (run before any push that touches UI):

```
python -m http.server 8080 --bind 127.0.0.1          # 또는 npm run ui:serve
python scripts/vendor_seed_css.py --check            # 벤더 CSS ↔ _UPDN 팔레트 동기
python scripts/check_seed_classes.py                 # 미정의 seed-* 클래스 = 0
node tests/ui/shots.mjs --page=<id>                  # 16샷 + 콘솔·브랜드·테마 어서션
node tests/ui/interact.mjs                           # SPA 전환·드로어·레일·그룹 기억
node tests/ui/deadcss.mjs                            # 전환기 셀렉터 잔량(0 이면 규칙 삭제 가능)
node tests/ui/important.mjs                          # !important 가 아직 인라인을 이기는지
node tests/ui/gridcheck.mjs                          # 격자·차트높이 클래스의 폭별 계산값 + 가로 넘침
node tests/ui/readability.mjs                        # 데스크톱 1440 가독성 G1~G6
node tests/ui/mobile-readability.mjs                 # 390 모바일 가독성 M1~M7 (10페이지 × 라이트/다크)
node tests/ui/uxgates.mjs                            # G7~G9·M8 (1440·390, 10페이지)
node tests/ui/interaction.mjs                        # G10·G11 조작·전환(유휴 DOM · 보기 전환의 주소 반영·복원)
node tests/ui/structure.mjs                          # S10~S26 구조 통일(표기·화면 머리·탭/고르기 부품·차트 규격·티커 이름)
node tests/ui/components.mjs                         # S27~S36 컴포넌트 규격(제목·도구 차례·버튼/칩/탭·숫자·표·간격·화면 머리)
node tests/ui/readability2.mjs                       # R1~R8 가독성 골격(결론 줄·첫 판정·화면수·글자색/크기·상태색·이름 반복·빈 차트·말 사전)
node tests/ui/firstload.mjs                          # data.json 을 4초 늦춰 딥링크 첫 도착 뒤 차트가 그려지는지(라이브는 늘 늦다 — 로컬에선 재현 안 됨)
```

**주소가 화면 상태다 (기획 `docs/superpowers/specs/2026-09-21-interaction-ux-plan-design.md`).**
`js/app1.js` 의 **`ECON_VIEW`** 가 화면별 보기 상태를 한 곳에서 정의한다 — `t`(2차 탭) · `v`(보기 전환) ·
`f`(필터·분류) · `r`(기간). 규칙 셋: **화면 이동 = pushState**(showPage) · **보기 전환 = replaceState**
(`econSetViewParam`) · **순간 UI(오버레이·레일·위젯 접기) = 주소에 안 넣는다**. 새 보기 상태를 만들면
레지스트리에 축을 등록하고(`get`/`apply`/`valid`) 상태를 바꾸는 함수에서 `econSetViewParam` 을 부른다.
정렬(`s`)은 일부러 뺀다 — 표가 화면당 11~15개라 안정된 키가 없다.

**화면 머리는 열 화면 모두 한 벌이다** — 본문 첫 줄이 `nav.page-toc`(= `h2.page-toc-h` 화면 이름 +
섹션 바로가기)다. 새 화면을 만들면 `js/app3.js` 의 **`PAGE_TOC`** 에 등록한다. 화면 이름을
`h2.sr-only` 로만 적지 말 것 — 읽기 도구에만 이름이 있는 화면과 눈에도 있는 화면이 섞이면
"여기가 어디인지"를 확인하는 방법이 화면마다 달라진다(2026-09-22 실측: 10화면 중 5:5). 게이트 S19.

**`.tab-btn` 은 두 부품에 붙는다 — 역할이 부품을 정한다.** 화면 내용을 통째로 바꾸는 2차 탭은
`seed-tabs__trigger` + `role=tab` + `aria-selected`, 차트·목록의 대상·기간을 고르는 칩은
`seed-chip__root` + 부모 `role=group` + `aria-pressed`. 접근성 보강기(`js/app1.js`)는 둘을 가려
장식한다 — 예전엔 칩 묶음까지 tablist 로 만들어 기간 칩이 `aria-pressed` 와 `aria-selected` 를
동시에 달고 있었다. **활성 표시는 `.tab-btn.active` 하나가 단일 원천이다** — 인라인 색을 덧칠하면
부품 규격을 인라인이 이겨 같은 탭이 화면마다 다르게 보인다. 게이트 S20.

**차트 범례는 이름 붙은 계열이 2개 이상이면 켠다.** 메르 렌즈 패널 8개가 계열 3~6개(본선 + 임계
점선 + 글 발행일)인데 범례를 숨겨, 그 점선이 무엇인지 화면 어디에도 없었다. 전역 플러그인으로
옵션을 일괄 수정하지 말 것 — Chart 4.4.1 의 옵션 해석기가 scriptable 옵션 차트에서
`t.startsWith is not a function` 으로 죽는다(실측). 규칙은 게이트 S21 이 강제한다.

**안 열린 화면의 캔버스에는 차트를 만들지 않는다.** `econChartLive(canvasId, redraw)` 로 캔버스를
얻고, 없으면(= 다른 화면) 그냥 반환한다 — `showPage` 끝의 `econChartFlush()` 가 화면을 열 때
밀린 것만 그린다. 종전엔 어느 화면을 열든 차트 7개가 생성됐고, 캔버스가 0개인 분석 노트에서도
살아 있었다. 게이트 S22(부팅 중 홈이 잠깐 활성인 동안 만들어지는 2개까지 허용).

**이름→값 2칸 표의 첫 칸은 `th[scope="row"]`** 다. `<table>` 을 머리 없이 배치용으로만 쓰면
두 번째 칸의 값이 무엇인지 마크업에 안 적힌다. 보이는 머리줄을 새로 세울 때는 화면 길이를 같이
본다 — 렌즈 화면은 표 머리 2줄(66px)만으로 G9(1440 ≤5.5화면)를 넘었다.

**위젯 이름 줄은 `h3`, KPI 카드 라벨은 `.econ-stat__label`** 이다. `.widget-title` 은 두 역할을
겸하는 클래스라 태그로 갈라야 한다 — 위젯 이름을 `div`/`span` 으로 적으면 화면 훑기(heading) 목록에서
그 상자가 통째로 빠진다(실측 2026-09-22: 거시 화면 위젯 16개 중 14개가 목록 밖, 사이트 합계 17개).
KPI 카드 라벨을 `h3` 로 올리는 것도 틀렸다 — 그건 제목이 아니라 큰 숫자의 설명이다. 게이트 S23.

**안 보이는 캔버스에는 차트를 만들지 않는다 — 판정은 `offsetParent` 다.** `.page.active` 만 보면
열린 화면 안의 **닫힌 탭·접힌 칸**을 놓친다(실측: market 금리 탭의 `rateHistoryChart`, 홈 접힌 칸의
`compareChart`). `econChartLive(id, redraw)` 가 미뤄 두고, 칸이 열리는 순간은 `ResizeObserver` 가
알려 `econChartFlush()` 를 부른다. **탭 전환 함수마다 flush 를 부르는 길은 쓰지 말 것** — 새 탭을
만들 때 또 빠뜨리는 종류의 규칙이다. 게이트 S24.

**티커에 뜨는 이름은 `ECON_IND.label(id)` 에서 꺼낸다.** `tickerData` 의 `name` 은 갱신 맵·화면별
범위(`TICKER_SCOPE`)가 쓰는 **내부 키**이고 화면에 쓰는 글자가 아니다. 종전엔 그 키가 그대로 떠서
같은 지표가 티커에서만 다른 이름이었다(실측 12종 중 6종: `BRENT`↔브렌트유 · `금(Gold)`↔금 ·
`미 10년물`↔미국 국채 10Y). 링크·클릭도 이름이 아니라 id → `canonicalOf(id)` 다. 띄는 12종은
레지스트리 **tier 1** 집합과 같아야 한다. 게이트 S25.

**하나만 고르는 버튼은 부품으로 말한다 — 인라인 색으로 칠하지 말 것.** 선택은 `.active` +
`aria-pressed`(칩) 또는 `aria-selected`(탭) 한 쌍이 단일 원천이고, 묶음 전체는 `econChipSelect(sel, btn)`
하나를 쓴다. 인라인으로 칠하면 부품 규격을 인라인이 이겨 같은 역할 버튼의 높이가 화면마다
갈리고(실측 23·24·27·30·32·34·36px), 읽기 도구는 무엇이 골라졌는지 모른다. 색에 **뜻이 있는**
묶음(금리 나라 필터 = 차트 선 색)은 색을 유지하되 `aria-pressed` 를 같이 세운다. 게이트 S26.

**화면은 한 벌의 골격으로 말한다 (가독성 개편, 기획 Claude Docs `c5abb330`, 2026-09-29).** 보고서 규칙을 화면에
옮긴 것이다 — 장표 하나 = 메시지 하나 → 화면(위젯) 하나 = 질문 하나. 차례는 **머리(이름 + 기준시점 꼬리표) →
결론 줄 → 숫자 칸 3~4 → 지금 볼 것 3~5 → 도식 하나 → 접힘 묶음 → 출처**. 실측(2026-09-29 라이브 14화면): 첫
900px 안에 말로 된 결론이 있는 화면이 1개였고, 메르 렌즈는 5.5화면·글자색 10종, 엘니뇨 카드는 45%가 차트·외부 이미지였다.
- **결론 줄 `.econ-lead`** — 상태 한 문장(20~90자). 값과 방향어에만 방향색, 화면당 2곳. 기준시점은 머리줄 꼬리표
  (`.econ-stat__unit`)가 맡고 문장에 안 반복한다. 자료 없으면 「자료 없음 — 마지막 값 M/D」. 문장은 새 수집 없이
  있는 사전 문장(`thresholds[].meaning` · `chains[].note` · 국면 요인)을 조합한다.
- **숫자 칸 `.econ-kpis` > `.econ-kpi`** — 한 줄 3~4칸, 칸마다 큰 숫자(`.econ-num--l`) 하나 · 라벨 위 · 설명 한 줄 아래
  (조건 한 곳만 굵게) · 스파크라인 110×30 허용(축 없음).
- **방향 바 `.econ-dir`**(중앙선, 왼쪽 상승 빨강 · 오른쪽 하락 파랑, 길이 `data-lv` 3단) · **범위 바 `.econ-range--th`**
  (52주 바 확장 — 임계 세로선 + 점, 상태색은 점에만) · **볼 것 카드 `.econ-watch__card`**(이름+배지 / 값+기준시점 /
  범위 바 / 「그래서」 한 줄, 카드 전체가 버튼) · **한 줄 사슬 `.econ-chain`**(칸 4~5, 발동 칸만 `.on`).
- **접힘 묶음 `.econ-fold`** — `econFoldSetup(hostId, page, onOpen)` 를 스크립트 로드 시점에, 알약은 `econFoldHTML`,
  패널은 `.econ-fold__panel`(열리면 `.open`). **열기 전엔 패널 내용을 만들지 않는다**(차트·이미지 포함, S22·S24) —
  `onOpen(id, panel)` 이 그린다. 열린 목록은 주소 `v=` 에 쉼표로 싣는다(`econFoldViewAxis`, ECON_VIEW). 렌더가 끝나면
  `econFoldReapply(hostId)` 로 열려 있던 것을 다시 편다. 상태는 렌더보다 먼저 살아야 딥링크의 `v=` 가 자료 도착 전에도 남는다.
- **말 사전** — 상태어 {돌파 · 주시 · 정상 · 자료 없음}(`MER_LABELS.state`) · 방향어 {상방 · 하방 · 혼조}. 이모지 ·
  한자 등급(高中低) · OW/UW · 호재/악재/혼재 는 쓰지 않는다. 상태 배지는 SEED badge tone critical/warning/neutral, 화면당 critical ≤3.
- **딥링크 첫 도착** — `applyRealData` 말미가 보이는 원자재 탭을 다시 그린다(`?p=market&t=commodity` 로 곧장 오면
  차트 6개가 비어 있던 버그). `loadRealData` 의 활성 화면 재렌더는 두 번째 갱신부터만 돈다는 걸 기억할 것.
- **화면 결론 줄은 한 함수가 쓴다** — `econLeadsRefresh()`(js/app1.js 끝, 화면별 `_lead*` 빌더 7개)가 목차 바로 아래
  `p.econ-lead--page` 를 만든다. 부르는 곳은 셋뿐: `showPage` 끝 · `applyRealData` 끝 · `econSetViewParam`(보기 전환).
  문장은 그 화면이 이미 계산한 값(KPI 카드 글자 · `eqData` · `macroData` · `fxPairs` · `currentRates` · `globalBonds` ·
  `comData` · `npsHistory` · `realestate` · `calEvents`)에서만 만든다 — 새 수집 0, 값이 없으면 「자료 없음」.
- **셋째 층은 접힘 뒤로** — 거시 `#macroFolds`(전체 지표·뉴스), 원자재 `#comFolds`(섹터 차트 4·LME·금속·운임),
  시장 지표 `#marketFolds`(매매중단 이력, 탭 아래). 이 셋은 주소에 싣지 않는다(macro.v 는 보기 방식, market.v 는 엘니뇨 접힘이 쓴다).
  닫힌 접힘 안의 차트는 만들지 않는다(`sectorChart` 가 `offsetParent` 를 봄) — 열릴 때 onOpen 이 다시 그린다.
  주식시장 `#eqFolds`(ETF 상승·하락 Top10 · 거래대금·체결 Top20)와 경제 일정 `#calFolds`(관련 뉴스)는 주소에 싣는다
  (`ECON_VIEW.equity.v` · `.calendar.v` — 축이 비어 있어서). 토스 랭킹은 당일분만 있으므로 `buildEquityRankings` 가 자료가 없으면
  알약을 숨긴다(빈 알약 금지). **R3(화면수)는 자료에 따라 움직인다** — 9/29 자료에선 ETF 등락 표가 1~2행뿐(206px)이라 3.43 으로 통과했고,
  9/30 자료에서 10행이 차자 495px 로 3.76 이 됐다(코드는 그대로). 표가 자료로 자라는 위젯은 통과선 바로 밑에 두지 말고 접힘 뒤로 보낼 것.
  경제 일정 「오늘」 표식은 SEED 배지(`seed-badge__root--tone_brand-variant_weak`)다 — 흰 글자 인라인 색은 오늘 일정이 있는 날에만 나타나 R4 글자색을
  한 종 늘렸다 — 날짜에 따라 통과·실패가 갈릴 수 있었다. 표 칸 여백은 인라인 `padding:8px` 가 아니라 `.econ-table` 규격(0 4px)에 맡긴다(390 M4).
- 게이트 `tests/ui/readability2.mjs` R1~R8 — 14화면 × 1440/390 전부 통과선(P2·P3, 2026-09-29). R4 는 내용 글자만
  (버튼·탭·칩·아이콘·배지·콜아웃 제외), R5 는 배지 + 방향색 **말**(숫자 등락은 값), R6 는 라벨로 선 이름만, R7 은 보이는
  덧판만, R8 은 외부 링크 글자 제외. 사이트 안 이모지는 전부 걷어냈다(국기만 남김) — 새 위젯에 이모지 제목을 달지 말 것.

**컴포넌트 규격은 부품이 강제한다 (6차, `docs/superpowers/specs/2026-09-24-component-spec-consistency-design.md` §4).**
규칙만 있고 부품이 없으면 위젯 93개가 각자 만든다 — 그게 6차 실측의 갈림(제목 두 벌·도구 차례 31가지·버튼 높이 21가지)이었다.
- **위젯 제목** = `h3.widget-title` 한 규칙(14px/700/`--c-txt`, 대문자·자간·파랑 없음). 제목 줄은 flex 이고
  **도구(별 → 새로고침 → 접기)는 `econOrderTools(title)`(js/app1.js)** 가 끝에 모은다 — 새 도구를 제목에
  붙이면 이 함수를 부른다(멱등이라 옵저버 루프 없음). 도구 아이콘은 28px.
- **새로고침 버튼은 전용 재요청 핸들러가 있는 위젯에만**(`_refreshHandlerMap`·표 맵·AI 요약). 전체 새로고침은
  사이드바 한 곳. 차트 실패 '다시 시도'는 위젯 버튼이 없으면 전체 새로고침으로 떨어진다.
- **실행 버튼** = `seed-action-button` xsmall 32(기본 neutralWeak, 되돌리기 neutralOutline, 화면 주 행동만
  brandSolid). **고르기** = `seed-chip__root` small 32(템플릿은 `CHIP_CLS`·`chipLabel()`). 인라인 style 로
  버튼·칩을 만들지 말 것. **탭** = `seed-tabs__trigger` 라인탭만(박스·필 탭 없음). 같은 표의 행만 바꾸면 칩이다.
- **선택 표시는 `.active` 하나** — `_econMirrorState` 가 aria-pressed/aria-selected·data-checked 를 따라 세운다.
  핸들러에서 `style.background='var(--c-accent)'` 로 칠하지 말 것(6차에 20여 곳 제거). aria-pressed 만 바꾸면
  SEED 칩은 골라진 것을 그리지 않는다(recipe 는 `[data-checked]` 를 본다 — 메르 렌즈 칩 버그의 원인).
- **숫자 블록** = `.econ-num--l/m/s`(24/18/14) + `.econ-num__chg`(값 **아래**). KPI 라벨 `.econ-stat__label` 13/500/dim.
- **카드 상자는 두 벌** — A `.widget`/`.kpi-card`(16·r12), B `.econ-inner`(위젯 안 값 묶음, 8·10·r6).
- **표 빈칸은 `—` 하나**, 표별 머리 CSS 금지(`.econ-table` 한 벌). **간격** = `--gap-w`(1440 16 · ≤480 12),
  `.g-*` 격자가 gap 을 가진다 — 인라인 `gap:12px` 쓰지 말 것. `.pad-14` 폐지.
- **화면 머리** = 목차 + 탭 한 줄(≤117px). 390 에서도 목차를 숨기지 않는다. 좁은 화면에서 탭이 감기면 한 줄 가로 스크롤.

**`role=group` 은 그 부모가 고르기 묶음 그 자체일 때만 붙인다.** `js/app1.js` 의 접근성 보강기는
칩 묶음의 부모를 장식하는데, 그 부모가 차트 도구줄이면 칩과 실행 버튼(`초기화`·`새로고침`)이 섞인다 —
읽기 도구에 "여기 버튼은 전부 고르기"라고 거짓말이 된다. `_isPureChipParent` 로 거른다.

**52주 범위는 `history` 가 없으면 `—` 다.** 정의부 상수로 도피하지 말 것 — 그 상수는 갱신되지 않아
"실측값처럼 보이는 지어낸 값"이 된다. `fxPairs`/`comData` 의 `h52`/`l52` 필드는 2026-09-22 에
전부 지웠다(읽는 곳 0곳). `index.html` 의 초기 표기도 숫자가 아니라 `—` 로 둔다. 게이트 S16.

**화면은 가만히 있어야 한다.** `js/app4.js` 의 마킹 함수들(`econMarkFavorites` 등)은 **멱등**이어야 한다 —
값이 같아도 `textContent` 를 다시 쓰면 텍스트 노드가 교체되고, 그것이 childList 변경이라
같은 파일의 MutationObserver 가 200ms 뒤 다시 그 함수를 부른다(자기 유발 루프). 이 루프가 유휴 20초
DOM 변경 2,884건 중 97.8% 였고, 멱등화 뒤 64건이 됐다. 게이트 = `tests/ui/interaction.mjs` G10.

**값 갱신 하이라이트** = `.econ-flash-up/dn`(0.8s). `js/app4.js` 막필의 옵저버가 숫자가 실제로
달라졌을 때만 붙인다 — class 만 건드리므로(attributes) 스스로를 다시 깨우지 않는다.

**표 정렬 표식은 리터럴 문자로** 적는다(`⇅`/`▲`/`▼`). 예전엔 CSS 이스케이프 `\2191` 이었는데
8진 이스케이프로 해석돼 제어문자 + "91" 이 열 머리에 찍혔다. 좁은 화면에서는 표식을 절대 위치로
겹쳐 놓는다 — 그냥 작게만 하면 6열 표가 390을 9px 넘는다(M4).

**화면을 옮기는 컨트롤은 `<a href="?p=…">`** 이다(티커·브리핑 칩·사이드바·하단 탭바). 핸들러는 그대로
두고 `onclick` 이 `return false` 로 기본 이동만 막는다 — 새 탭·주소 복사·가운데 클릭이 따라온다.

**데스크톱이 모바일보다 작았다 (기획안 `docs/superpowers/specs/2026-09-19-readability-ux-plan-design.md`).**
9/18 에 모바일만 한 칸 올린 결과 1440 본문이 12px/w400 731곳으로 390(14px)보다 작아져 있었다.
브리지의 데스크톱 스케일을 xs 12→13 · sm 13→14 · md 13→14 로 올려 맞췄다(base 14 는 그대로 —
16 으로 올리면 화면이 길어져 G9 와 충돌한다). 표는 셀 t3·머리 t2 로, 11px 를 직접 물고 있던
배지·단위 recipe 는 t2 로 올렸다. 텍스트 위계는 `--c-txt`(gray-1000) / `--c-txt-dim`(gray-900) /
`--c-txt-muted`(gray-800) 세 단이다 — 전에는 dim 과 muted 가 같은 토큰이라 두 단이었다.
`fg-neutral-subtle`(3.42:1)은 여전히 텍스트 금지.

**홈은 3열이다(§C8).** 글로벌 지수 목록은 `homeSecWatch` 가 아니라 **`homeSecMain` 안**에 있다 —
좌 목록(sp-lg-3) · 중 메인 차트(sp-lg-6) · 우 등락 Top10(sp-lg-3), 우측 개인화는 MY 레일.
목록 행 클릭은 페이지 이동이 아니라 `selectGlobalIndex` 로 **중앙 차트만 바꾼다**. 목록의 현재가·
등락률은 한 칸에 값 위·등락 아래(`.econ-numcell`)다 — 좁은 칼럼에서 두 줄로 깨지던 자리다.

`uxgates.mjs` 의 네 기준: **G7** 토큰을 거치지 않은 글자색 0(브라우저 기본 링크색·계열색 리터럴) ·
**G8** 데이터 위젯의 `data-asof` 각인 100% + 시장 상태 배지(표시는 "정상이면 침묵", 확인 수단은 항상) ·
**G9** 화면수 1440 ≤5.5 · 390 ≤4.0(벤치 실측: Npay PC 홈 5.6 · 토스 홈 5.7) ·
**M8** 첫 데이터까지 420px(첫 화면의 절반). 산문 줄은 `.note-line`/`.econ-prose` 가 44em 에서 접는다.
`.econ-data` 는 표도 차트도 아니지만 값이 들어 있는 블록의 표식이다(캘린더 격자) — 게이트가 '데이터'로 센다.

**모바일은 따로 잰다 (기획안 1xWjJ5MM).** `readability.mjs` 는 1440 에서 두 페이지만 보고,
그 둘이 하필 390 에서도 대비 미달 0 인 페이지였다 — 나머지 8페이지의 36곳이 게이트 밖에 있었다.
`mobile-readability.mjs` 가 390×844 에서 10페이지 × 두 테마를 재고, 기준은 일곱이다:
M1a 13px 미만 글자 0 · M1b 본문 글자 중 14px 미만 ≤35% · M2 대비 미달 0 ·
M3 탭 타깃 24px 미만 0 · M4 표의 390 초과폭 0 · M5 문서 ≤4.0화면 · M6 첫 화면 컨트롤 점유 ≤40% ·
M7 가로 넘침 0. **M1b 가 세는 것은 20자 이상 덩어리**다 — 값·꼬리표(13px 이 제자리)와
읽는 글을 가르는 선이고, 컨트롤 안 글자는 빼고 센다.

**모바일 타이포는 브리지 옆 한 블록이 정한다.** `@media (max-width: 480px)` 안에서
`--font-size-xs/sm/md/base` 를 t3/t4/t4/t5(13/14/14/16px)로 재매핑한다 — 사용처가 html 502 +
js 378 곳이라 개별 수정은 불가능하고, 단일 원천이 있으니 필요도 없다. 같은 블록이
t1·t2 에 직접 박힌 자리(`.econ-meta`·`.econ-stat__unit`·§11 텍스트 위계·SEED 배지/태그 recipe)의
바닥을 t3 로 올리고, `input/select/textarea` 를 16px 로 고정한다(그 아래면 iOS Safari 가
포커스 때 화면을 확대하고 되돌리지 않는다). **셀렉터에 `:root` 를 붙여 (0,1,1)로 올려야 한다** —
이 블록은 시트 앞쪽에 있고 원래 정의는 뒤쪽이라, 미디어쿼리만으로는 진다.

**모바일 전용 클래스 셋.** `.note-line`(문장으로 된 안내·출처 블록 — 데스크톱 xs, 모바일 sm) ·
`.c-opt`(≤480 에서 접는 표 열 — **행을 누르면 상세가 열리는 표에서만** 쓴다. 숨긴 값이 어디서도
되살아나지 않으면 그건 접는 게 아니라 잃는 것이다) · `.ctl-sep`(글자 "|" 대신 선으로 그린 구분자) ·
`.ctl-fold__sum`/`.ctl-fold__body`(`econFoldControls` 가 만드는 접힌 컨트롤 묶음).
`econFoldControls`(js/app4.js)는 **선택된 항목이 실제로 있는 묶음만** 접는다 — 버튼 4개 이상이라는
조건만으로는 동작 버튼 줄·링크 목록·값 카드까지 접히고, 그러면 요약 줄이 「지금 고른 것」 자리에
첫 버튼 글자를 날조하게 된다.

**레이아웃은 유틸 클래스로 — `grid-template-columns`·차트 높이를 인라인에 쓰지 않는다.**
P5 에서 인라인 격자 55곳·차트 높이 34곳·카드 여백 7곳을 클래스로 옮겼다.

| 클래스 | 값 | 좁은 화면 |
|---|---|---|
| `.g-2` `.g-3` `.g-4` `.g-5` `.g-7` `.g-12` | n열 균등 | g-3·g-4 → ≤1024 2열, g-4 → ≤480 1열, g-2 → ≤1024 1열 |
| `.g-side` `.g-side-280` `.g-side-320` | 본문 + 우측 패널 | ≤1024 1열 |
| `.g-side-l` `.g-side-l-300` `.g-side-l-340` | 좌측 패널 + 본문 | g-side-l → ≤1024 1열 |
| `.g-2-1` `.g-1-2` `.g-3-2` | 비대칭 2열 | ≤1024 1열 |
| `.g-auto-120…220` | `auto-fit minmax(Npx,1fr)` | 자동 |
| `.h-200…380` `.mh-280…440` | 차트 래퍼 높이 | ≤1024 에서 축소 |
| `.pad-8` `.pad-8-10` `.pad-14` `.pad-36-20` | 카드 여백 예외 | ≤1024·≤480 에서 축소 |

값이 인라인에 없으니 반응형이 `!important` 없이 이긴다 — 옛
`main div[style*="grid-template-columns:1fr 300px"]` 식 **문자열 매칭 셀렉터 48행은
삭제됐다**. 새 격자를 인라인으로 쓰면 그 화면만 반응형에서 빠진다. 카드 여백 예외는
`.widget.pad-14`(두 클래스)로 뒤에 오는 기본 padding 을 이기고, 반응형은
`.widget.widget`(같은 특이성 + 뒤 순서)으로 그것을 다시 덮는다.

**클릭 요소는 처음부터 `<button>`.** `div`/`span` + `onclick` 은 쓰지 않는다. 기존
것은 P5 에서 전부 전환해 `[role="button"]` = **0**(12페이지 실측)이다.
- 모양 유지 리셋 = `class="btn-plain"`(인라인 자리엔 `btn-inline`, flex 자식엔
  `btn-flex`). `:where(.btn-plain)` 로 특이성 0 이라 컴포넌트 클래스(`.ds-item`,
  `.study-drop` …)가 순서와 무관하게 리셋을 이긴다.
- **표의 행은 버튼이 될 수 없다.** `tr[onclick]` 은 대표 칸 내용을
  `<button class="btn-plain btn-inline">` 으로 감싸고 **핸들러를 달지 않는다** —
  click 이 행으로 버블링돼 기존 onclick 이 돈다(마우스=행 전체, 키보드=Tab+Enter).
- 다른 컨트롤을 품은 컨테이너도 버튼이 될 수 없다(버튼 안의 버튼). 전역 보강기
  (`js/app1.js` 접근성 IIFE)가 이제 표 요소·`aria-hidden`·`stopPropagation` 전용
  핸들러·컨트롤을 품은 요소를 건너뛴다.
- 위젯 접기는 제목이 아니라 전용 `.w-toggle-btn`(`aria-expanded`)이 담당한다.
  제목은 마우스 편의용 클릭 영역이다. 헤더 줄 판정은 제목에서 위로 올라가
  위젯의 직계 자식을 찾는다(깊이 고정이 아니다 — 메인 차트카드가 빠져 있었다).

The `astryx layer` section at the end of `<style>` still holds frame/surface/row
rules and must stay last. `!important` 는 174 → 135 로 줄었고, `important.mjs` 로
재면 **인라인을 이기는 선언은 9개**뿐이다: `prefers-reduced-motion` 의
`transition-duration`(정당한 용법), `.tab-btn.active` 색 4벌, 모달 카드 그림자 2벌,
그리고 JS 가 인라인으로 위치를 잡는 `.data-source-popup` 의 좁은 화면 재배치
(이건 인라인을 이겨야 한다). 남은 `!important` 는 인라인과 싸우지 않는다 —
지우려면 규칙마다 무엇을 이기려 했는지 개별 확인이 필요하다.

## 지표 레지스트리 — 한 지표 = 한 행 (IA 개편 v3 P0)

분류 체계가 코드 안에 7개 따로 있었다(사이드바 그룹 · 비교차트 카탈로그 85 · 거시 카테고리
10×50 · 메르 렌즈 레이어 4×48 · 뉴스 16 · 분석 노트 4 · `sources` 33). 서로 매핑이 없어
KOSPI 가 14곳, USD/KRW 가 12곳에 각각 원본처럼 떴고(`js/app3.js:296` 주석이 그 증상을 이미
기록해 뒀다), 반대로 수집만 하고 화면에 없는 데이터가 남았다. 이제 한 지표는 한 행이다.

```
data.json + js/app1.js(macroIndicators) + mer_signals.json
  → scripts/build_indicators.py   (규칙 + 사람이 내린 결정: tier · canonical · news · 별칭)
    → js/app0.js  window.ECON_IND   ← 화면은 여기만 본다
```

- **`js/app0.js` 는 생성물이다. 손으로 고치지 말 것.** 재생성 `python scripts/build_indicators.py`,
  게이트 `python scripts/build_indicators.py --check`(드리프트 · 죽은 경로 · 죽은 카드 0).
- 행의 필드: `asset`(자산군 = 1차 네비 축) · `topic`(거시 주제 탭) · **`tier`**(1 대표/홈 · 2 주요 ·
  3 상세표) · **`canonical`**(원본 화면; 다른 화면의 같은 값은 요약이고 원본으로 연결한다) ·
  `news`(`data.json.news` 16주제 중 맥락 한 줄을 뽑을 키) · `data`/`series`/`alsoData` · `merLens` ·
  `aliases`(화면마다 갈리던 옛 표기) · `onScreen:false`(수집만 되고 화면 없음).
- **지표 이름을 화면에 새로 적지 말 것** — `ECON_IND.label(id)` 또는 `ECON_IND.find('옛 이름')`.
  'WTI 유가' vs 'WTI 원유' 같은 갈림이 여기서 끝난다.
- **원본 화면으로 보내는 라우팅은 `gotoCanonical(canonical)` 하나다**(`js/app1.js`). 티커 클릭의
  이름-분기 15줄이 이걸로 대체됐다. 새 진입점도 이름이 아니라 `canonical` 을 넘긴다.
- 파일명이 `app0` 인 이유: 로더(index.html)와 `build-frontend.yml` 의 `js/app[0-9].js` 글롭에
  그대로 걸려 minify·캐시버스팅·로드 순서가 따라온다. 0 이라 app1 보다 먼저 실행된다.
- 기획 원문 `docs/superpowers/specs/2026-09-18-ia-restructure-design.md`.

## Key Files

| File | Role |
|------|------|
| `index.html` | Entire frontend — styles, charts (Chart.js), all page logic |
| `scripts/fetch_data.py` | ~7 000-line data collector; runs in GitHub Actions |
| `scripts/validate_data.py` | Data integrity gate — blocks bad `data.json` from commit |
| `scripts/ai_briefing.py` | LLM macro summary → `data.json.aiBriefing` |
| `scripts/fetch_merblog.py` + `scripts/merblog_lib.py` | 메르 블로그(ranto28) 최근 365일 메타 + 최신 20편 원문 → `merblog.json`. 공개 저장소라 원문 전량 커밋 금지 |
| `scripts/mer_extract.py` | 메르 글 → 구조화 JSON(`mer_extract_cache.jsonl`). 인용은 80자 이하 + **원문 실재 검증 통과분만** 저장(날조 차단), 원문 자체는 저장 안 함(공개 저장소). 키는 `ANTHROPIC_API_KEY` → `GEMINI_API_KEY` 순, 둘 다 없으면 건너뛰고 캐시 보존. `--limit N` 으로 백필을 회차로 쪼갠다 |
| `scripts/mer_aggregate.py` + `scripts/mer_dict.yml` | 추출 캐시 + `data.json` + `mer_series.json` 을 정규화 사전으로 접어 `mer_signals.json` 생성. 사전 없이는 히트맵이 통째로 빈다(자유 서술 from/to 는 810건 중 distinct 766). 트리거 레벨은 단위·범위 게이트를 통과한 것만 차트에 그린다 |
| `scripts/fetch_mer_series.py` | 메르 리스크 렌즈 공백 시계열 → `mer_series.json`(JGB 1/10/30Y 전량 재구축 + NPS·SCFI·LME 자가축적) |
| `mer_signals.json` | 메르 리스크 렌즈 집계 산출 — `?p=merlens` 화면(`js/app7.js`)의 유일한 데이터원 |
| `scripts/send_kakao_digest.py` | KakaoTalk sender. **모든 카카오 발송의 단일 진입점 = `send_card()`**(기획 v3 I1): 카드 PNG → 슬롯 라인 차트 → 텍스트 3단 폴백, 버튼 2개·라벨 8자 (카카오 상한), `png=None` 으로 부르면 경고 + 디스코드 `#시스템` 교차 통보(사진 없는 경로가 생기는 것을 보이게 하는 장치). 피드 이미지 = `discord_card.board(shape="square")` 정사각 카드(디스코드와 **같은 편성표**) → 실패 시 `build_slot_chart_png` → 텍스트. **주간 슬롯도 카드**(`_build_kakao_card(weekly=True)` → `discord_card.weekly(shape="square")`) — 옛 `None if _weekly_mode` 분기는 제거됐다. 장 마감(**16:40**, 2026-09-11 15:40→이동)은 디스코드+카카오 병행. **수급(외국인·기관)은 `investor_flows.verified_latest()` 로 발송 직전 라이브 조회** — 네이버(포털·언론 기준)값을 토스로 교차검증해 통과분만 싣고, 오늘 날짜 행이 없거나 총체적 불일치면 숫자 대신 '집계 중'을 적는다(옛 `investorTrading.daily[-1]` 직참은 날짜 검증이 없어 어제 수급이 오늘 카드로 나갔다). 히어로 인트라데이는 `_session_chain`(Yahoo 5분봉 우선 = 당일 전 구간)이고 급변·마감 카드의 `_intraday_chain`(토스 1분봉 우선 = 최신성)과 **우선순위가 반대다**. 수신은 “나와의 채팅”(`KAKAO_FRIENDS=0`) — **푸시 알림 없음**이 정상 동작이다. **피드 행(`item_content.items`)은 `KAKAO_FEED_ROWS`=5 가 상한이고, 넘으면 뒤 행을 버리지 않고 앞 행에 접는다**(`build_feed_parts`) — 종전엔 블록 8개 → 행 6개가 되어 맨 뒤 '수급'이 매번 잘렸고, 수급 블록은 KRX 확정(18시) 이후 슬롯에만 붙어 **100% 탈락**했다(2026-09-17 실측) · **피드 본문은 카드와 중복을 뺀다**(2026-09-18): 카드가 실제로 렌더된 평시엔 `build_digest_parts(data, drop=_card_tile_labels(...))` 로 그 슬롯 타일 지표를 **조립 단계에서** 제외한다(문자열을 잘라내지 않는다) — 장중 편성에서 표시 슬롯 12개 중 5개가 같은 숫자였다. 카드가 실패해 슬롯 라인 차트로 내려간 경우와 텍스트 폴백은 전체를 싣는다 · **행 표기 창구는 `kakao_item()` 하나**(`KAKAO_ITEM_LABEL`/`KAKAO_ITEM_VALUE`) — 종전엔 다이제스트 무제한·종목 알림 40자로 갈려 있어 무엇이 보일지 예측할 수 없었다. 값 상한은 카카오 실제 표시 한도를 아직 실측하지 않아 넉넉한 안전 레일이다 · **`_pack` 은 한도로 빠진 줄을 '외 N항목'으로 고지한다** — 종전엔 표시 없이 사라져 '블록이 없는 날'과 '잘린 날'을 구별할 수 없었다 |
| `scripts/check_alerts.py` | Stock alert evaluator. 카카오는 카드 한 통(`_alert_card(shape="square")` = 대표 종목 + 나머지 종목 타일 합본) + 항목 행 5줄로 보낸다 — 200자 한도 때문에 여러 통으로 쪼개던 텍스트는 폐기(`_pack_messages` 는 이제 '확정 대상 산정'용). 발동 줄 문구 단일 원천 = `_alert_lines`. **카드로 넘기는 나머지 종목은 구조화 튜플 `(이름, 가격문자열, 등락률, 조건)`**(`_alert_card` + `_cond_short`) — 완성된 문장을 카드가 공백으로 되쪼개던 종전 경로에서 등락률·조건·방향색이 타일 폭에 잘려 사라졌다(2026-09-18 실측: '412,000원(+5…' / '52주'). 히어로 `cond` 도 조건 조각만 넘긴다(이름·가격·등락률은 타일이 이미 들고 있다) |
| `scripts/check_swings.py` | Market swing alert (코스피·S&P500 ±2%, 달러-원 ±1% 즉시 속보; cooldown = `alerts_state.json` `_swings` key) |
| `scripts/investor_flows.py` | 투자자 수급 단일 창구 — 네이버 증권 API(`naver_day`/`naver_daily`, `m.stock.naver.com/api/index/{시장}/trend?bizdate=`) + 토스 어댑터 + `agree()`/`gross_mismatch()`/`verified_latest()`/`week_sum()`. **표시값=네이버(사용자가 대조하는 포털·언론 기준), 토스=교차검증**. 토스와 네이버는 같은 날 수천억 차(2026-09-10 기관 -134 vs +5,744억 — **토스 = KRX + 넥스트레이드 합산, 네이버 = KRX 만**. 2025-03-04 NXT 개장 전엔 차 0)라 단일 소스로는 알림 값이 실제와 어긋났다. 검증 실패 = 숫자 생략(추정 금지). 가드 `python -m pytest scripts/tests/test_investor_flows.py` |
| `scripts/discord_card.py` | 카드 PNG 렌더러(matplotlib) — 디스코드(가로 10×7)와 카카오(정사각 1080², `shape="square"`) 공용. **도안 3형**(기획 v3): 사건형 `stock_alert`·`swing`(타일 + 인트라데이 임계선) / 상태형 `status`(상태 배지 + 타임라인 — 해제·테스트처럼 차트가 의미 없는 통지) / 지표형 `board`·`weekly`·`close_report`. 공통 골격 = `_sq_fig`/`_head`(제목 — 제목과 우측 보조가 한 줄을 **폭으로** 나눠 쓴다) + `_draw_cells`(타일; `_draw_tiles` 는 편성표 키를 셀로 바꿔 같은 함수를 쓴다) + `_sq_panel`(선 그래프) + `_footer`. **카드 내부 텍스트에 이모지 금지**(CI·로컬 폰트에 글리프 없음 — 제목이 담당). 바탕 = 흰색, UP/DN(`#E0443E`/`#3E7BE0`)은 채움색 전용이고 작은 글자는 `UP_TXT`/`DN_TXT`. 편성표는 `_CATALOG` 키만 참조하므로 `_ASSETS` 는 건드리지 말 것. 미리보기 `python scripts/discord_card.py all -o out/ [--square]`, 가드 `python scripts/tests/test_discord_card.py` + `test_kakao_cards.py` + **`test_card_layout.py`(글자 겹침·캔버스 이탈·타일 삐짐 0건)** + **`test_readability.py`(정보 보존·카드↔본문 중복·글자 하한·강도 대비·빈 띠·잘림 고지 6종)**

**판독 규격(2026-09-17 개편, 기획 HdmGyTK4).** 카톡 말풍선은 1080px 카드를 약 **270px**로 줄여 보여준다(축소비 4배). 그래서 판단 기준은 pt 가 아니라 **화면 글자 높이** = `pt ÷ 72 × dpi × (표시폭 ÷ 카드폭)` 이고, 한글 하한은 9px 다. 개편 전에는 카드 글자의 74~90%가 그 아래였다. 규칙 셋:
- 글자수(`[:44]`)로 자르지 않는다 — `_clip`/`_text_w` 가 **실제 렌더 폭**으로 자른다(한글·숫자·비율기호 폭이 제각각).
- 타일은 **2열 6칸**(`PROFILES`, 2026-09-17 사용자 결정으로 닛케이·달러인덱스·금 제외). 칸이 넓어야 글자가 커진다. `_draw_cells(note_inline=True)` 는 값과 등락률을 한 줄에 두고, 폭이 모자라면 자동으로 세 줄로 내려간다(값을 자르지 않는다).
- 차트에는 **세로축이 있다** — `_sq_panel` 이 전일·고가·저가를 값과 함께 패널 안에 적고(픽셀 간격으로 자리 다툼), 채움은 **전일선 기준**으로 위아래 색을 나눈다. 값 없는 격자선은 쓰지 않는다.
- **타일 색은 방향이 아니라 크기를 말한다**(2026-09-18). `_tile_color` 채도 하한은 **0.10**이다 — 0.30 이던 때는 0.16% 움직임도 곧장 뚜렷한 분홍이 되어 상승장에 6칸이 '붉은 벽'이었다(크기 정보가 색에서 사라진 상태). 방향은 `▲/▼` 가 이미 말한다. 등락률은 칸 오른쪽 끝이 아니라 **값 바로 옆**에 붙는다(한 쌍의 숫자를 읽는 데 시선이 칸 폭을 건너지 않게).
- **캔버스 높이는 재료 수가 정한다** — `close_report` 는 수급 바가 없으면 7.4→4.2~7.4 로 줄이고, 인트라데이가 없으면 다이버징 바가 전폭을 쓴다. 디스코드는 이미지를 폭에 맞춰 축소하므로 빈 띠는 그만큼 글자를 작게 만든다.
`SQ_MIN_FS`(13pt)는 하한일 뿐 목표가 아니다 — 카드별 폰트는 호출부 `fs=(라벨, 값, 등락)` 가 정한다. 세 줄로 내려가는 좁은 칸 경로도 이 하한을 다시 건다(종전엔 그 경로만 우회해 11.2pt 가 섞였다). |
| `scripts/notify_discord.py` | Discord webhook parallel channel (secret `DISCORD_WEBHOOK_URL`; digest/alerts/swings 병행 발송, 미설정 시 no-op). 버튼 라벨 방향 이모지 `direction_emoji`/`dir_label` (E2 표준 ±2%). 다이제스트 컴포넌트 = 지표 URL 버튼 1행(`card_links`, 카드와 같은 순서·라벨은 이모지+이름) + 유틸 버튼 1행 2개(2026-09-24 — `시장 지표` 제거). 드롭다운(`goto_link`)은 2026-09-22 에 발송 경로에서 빠졌다(Interactions 왕복 의존). 구 16버튼 타일 미러 그리드는 폐기, 등락 정보는 카드 이미지 단독 담당 |
| `cloudflare-worker/worker.js` | CORS proxy + rate limiting + KakaoTalk cron dispatch |
| `data.json` | Market data artifact — committed by bot, never edit by hand |
| `data_meta.json` | Lightweight `lastUpdated` mirror of `data.json` |
| `alerts_config.json` | Stock alert rules (committed by bot via Worker `/portfolio`) |

## GitHub Actions Workflows

| Workflow | Schedule | Secret dependencies |
|----------|----------|---------------------|
| `fetch-data.yml` | Every 10 min (market hours), hourly (off-hours), daily KST 09/16/22 | `KRX_ID`, `KRX_PW`, `FRED_API_KEY`, `ECOS_API_KEY`, `REALESTATE_API_KEY`, `KOSIS_API_KEY`, `DATA_GO_KR_API_KEY`, `TWELVEDATA_API_KEY` (optional, 해외지수 2순위), `KIS_APP_KEY`/`KIS_APP_SECRET` (optional), `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET` (optional), `GEMINI_API_KEY`/`OPENAI_API_KEY` (for AI briefing) |
| `kakao-daily.yml` | Weekdays 07–22 KST hourly, weekends **and KR public holidays** 11 & 17 KST (Sunday 17h = weekly report mode; holiday detection = gate step via Nager.Date API, fail-open to weekday, `KR_HOLIDAY` env → script) | `KAKAO_REST_API_KEY`, `KAKAO_REFRESH_TOKEN` |
| `stock-alerts.yml` | Every 5 min during KR/US market hours | same Kakao secrets |
| `link-check.yml` | Periodic | none |
| `notice-check.yml` (Notice Check) | Mon 09:20 KST | `DISCORD_WEBHOOK_SYSTEM`, `GEMINI_API_KEY`(없으면 키워드만) — 제공기관 공지판 새 글 중 주소·종료·한도 관련만 #시스템 |
| `health-report.yml` (Health Report) | 1일 09:30 KST | `DISCORD_WEBHOOK_SYSTEM` — 지표 146 상태·원천별 실패·교차검증·전월 대비 한 통 |

Trigger `fetch-data` or `kakao-daily` manually via **Actions → workflow_dispatch** for testing.

## Data Pipeline Architecture

```
GitHub Actions (fetch_data.py)
  → data.json + data_meta.json committed to main
    → pages.yml (workflow_run) deploys the allowlist to GitHub Pages
      → index.html fetches data.json on load
        → Cloudflare Worker proxies browser→API calls blocked by CORS
```

`fetch_data.py` data source priority:
0. **Toss Securities Open API** (`scripts/toss_api.py`, secrets `TOSS_CLIENT_ID`/`TOSS_CLIENT_SECRET`) —
   official OAuth2 source for KOSPI/KOSDAQ indices, KTB yield curve (2/3/5/10/20/30Y),
   gainer/loser rankings, and KOSPI investor flows. Every function returns `None`/`{}`
   when the keys are absent, so the legacy chain below runs unchanged.
   **Caveat: Toss stock candles are an *integrated* session** (pre + regular + after-hours),
   so their close is not the regular-session close that 등락률 is measured against
   (2026-08-14: 005930 08-13 Toss 263 000 vs regular 268 000). Use `rankings()`'s
   `changeRate` (base-price derived) for per-stock moves; never `snapshot()`.
   Indices have no after-hours print, so `snapshot('^KS11'/'^KQ11')` is safe and is what
   `check_alerts`/`check_halts`/`send_kakao_digest` now use.
   **Toss cannot be called from CI.** Each client is bound to an IP allowlist with no
   CIDR or wildcard form, and both GitHub Actions runners and Cloudflare Workers egress
   from dynamic addresses (measured: runner 403, Worker 401 `unidentified-client`).
   `scripts/fetch_toss_snapshot.py` therefore runs on the allowlisted PC, writes
   `toss_snapshot.json` and pushes it; `fetch_data.py` reads that file through
   `_toss_snapshot()` with per-item freshness guards (movers same-day only, yield curve
   96 h, investor series any age since it carries dates). PC off → guards drop the stale
   parts and the chain below runs. See *Local Toss collector* at the end of this file.
   Workflows therefore **do not pass** `TOSS_CLIENT_ID`/`TOSS_CLIENT_SECRET` (2026-09-28) —
   `toss_api.enabled()` is False in CI and every Toss call falls straight through to the
   snapshot/Yahoo chain. The Worker `/toss` relay was deleted the same day (it only ever
   returned 503). Do not re-add either: order-capable credentials in CI buy nothing.
1. **pykrx** (`pykrx==1.2.8` pinned) — KRX official (KOSPI/KOSDAQ/Top10/investor flows)
2. **yfinance** — overseas indices, commodities, FX fallback
3. **FRED API** — US macro indicators
4. **ECOS API** — Bank of Korea data
5. **R-ONE API** — Korean real estate indices
6. **KOSIS API** — Korean statistics
7. **DBnomics** (keyless) — 일본 CPI(`STATJP/CPIm`, 총무성 원본; FRED OECD 계열은 2021 종료). 일본 IIP 는 대체 없음(묘비)
8. **Twelve Data** (optional key) — 해외지수 6종 2순위·대조(`scripts/twelvedata.py`, 풀 런 1회, 일 800 크레딧)
9. **Naver/yfinance fallbacks** — when primary sources fail

(Alpha Vantage 는 2026-09-30 제거 — 키를 한 번도 등록하지 않았고 일 25건이라 가치가 없었다. `AV_FETCH_FULL` env 는 「일일 런」 표식으로만 남아 있다.)

The script **preserves previous values** on partial failure — individual API errors don't blank the data.

**데이터 신선도 규칙 (2026-09-24 개편, 기획 "데이터 전수 검사·신선도 고도화").**
- **값을 지어내지 않는다.** 하드코딩 폴백 상수(`FALLBACK` 표·프런트 `KR_FALLBACKS`·수익률곡선 상수·
  보간+노이즈 시계열·환율 시가/고가/저가·아연/니켈 합성선)는 전부 삭제됐다. 현재가 수집이 실패하면
  `_prev_spot` 이 직전 값을 `stale:true`·`change:null`·`staleSince` 로 되살리고(4일 상한), 판정표가
  `preserved` 로 드러낸다. 다시 넣지 말 것.
- **as-of 는 소스가 준 날짜만.** 토스 랭킹·등락상위의 `as_of` 는 수집일이 아니라 거래일이고
  (`_kr_session_date`: 캘린더가 휴장이라면 직전 영업일), 스냅샷 소비 가드도 '오늘'이 아니라 '최근 거래일'이다.
- **판정표(`scripts/data_sla.py`)는 주기에서 SLA 를 도출한다** — 경로 규칙의 일수가 `None` 이면
  `infer_cadence`(노드 `cadence` → history 간격 → period 형식)로 월간·분기·연간을 알아내고 **기간
  종료일부터** `CADENCE_SLA` 로 잰다. 새 저빈도 지표에 경로별 일수를 손으로 맞추지 말 것.
  프런트가 읽는데 키째 사라질 수 있는 경로는 `_EXPECTED_TOPS`(점 경로)에 넣어야 missing 으로 잡힌다.
- **호스트 서킷브레이커** — `fetch_data.py` 의 모듈 `requests` 는 `_HostBreaker` 다. 같은 호스트에서
  ConnectTimeout 3회 연속이면 그 런의 나머지 호출은 즉시 실패(ECOS·R-ONE·data.go.kr 동시 장애로
  70분 timeout 이 나던 경로). 차단 호스트는 `diagnostics.deadHosts`.
- **풀 런도 Worker 가 깨운다** — Worker 매분 cron 이 매시 :07(:08 보강) `fetch-data` 를
  `client_payload.mode='full'`, UTC 0·7·13시엔 `'daily'`(AV·ENSO·메르 추출·펀더멘털)로 dispatch 한다.
  GHA schedule 은 7일 실측 의도의 10~20%만 발화해 백업으로만 남겼고, 일일 cron 3개는 중복을 막으려고
  지웠다. 풀·일일 런은 `run-name` 에 `[full]` 이 붙고, Worker 의 경량 과밀 판정(`_isLightRun`)은 그
  표식이 없는 dispatch 런만 센다(풀 런이 경량 5분 런을 굶기지 않게).
- **실패는 산출물에 남긴다(2026-09-30).** `_HostBreaker` 가 호스트별 calls/fails/lastError/lastOkAt 을 세어
  `diagnostics.sourceStatus` 에 쓴다(4xx·5xx 응답도 실패, 이번 런에 안 부른 호스트는 직전 값 유지, `consecutiveFailRuns`
  이월). 100런 연속 전부 실패면 #시스템에 「제외 후보」 1회 알림(`_alert_dead_sources`). 로그에 키 글자를 찍지 않는다.
- **직전 값으로 되살린 잎엔 `preserved: true`·`preservedAt`(처음 못 받은 시각)** 이 붙고, 판정표는 이것을 as-of 나이와
  무관하게 `preserved` 로 센다(종전엔 건강표가 직전 값 12개를 정상으로 셌다). 수집 주기 묶음(아래)이 일부러 건너뛴
  잎은 `preserved_reason: "lane"` 만 붙고 `preserved` 는 아니다 — 화면 칩은 `preserved === true` 만 본다.
- **합리 범위표(`RANGE_RULES`, data_sla.py)** — 범위 밖 값은 `state: suspect`(검증 필요, `reason`)로 두고 저장은 한다.
  validate 는 경고만. 첫 포착 = 「미분양 300,828호·착공 100.44」 — 실측 결과 R-ONE 표 오인(A_2024_00064 는 아파트 평균
  전세가격(천원), A_2024_00057 은 준전세가격지수)이라 `avg_jeonse_price_kr`·`semi_jeonse_idx_kr` 로 개명·정상 판정. 진짜 미분양·착공
  표는 R-ONE 에 없을 수 있다(`[R-ONE-probe]` 일일 로그로 탐색 중, 대체 후보 = 국토부 통계누리 hRsId=32, API 없음). 새 지표는 여기에 하한·상한을 함께 넣는다.
- **수집 주기 묶음(lane).** 매시 풀 런(`mode=full`)은 `FETCH_MACRO=0` 으로 거시·부동산 5묶음(`MACRO_SECTIONS`:
  intl·pmi·ecos·rone·fredre)을 건너뛰고 직전 값을 잇는다. 일일 런 3회(`mode=daily`, `FETCH_MACRO=1`)가 매일 재시도.
  직전 런에서 `preserved: true` 로 남은 잎이 있는 묶음만 매시 다시 받는다. `diagnostics.macroLane={fetched,carried}`.
  왜: 월간 표를 매시 다시 묻다가 ECOS·R-ONE 이 6런 중 3런 통째 차단됐다(2026-09-30 실측).
- **KRX Open API 401 은 승인 문제다** — 키(`KRX_API_KEY`)는 등록돼 있고 서비스별 이용신청(KOSPI 지수·파생상품지수·
  일반상품·ETF)이 승인돼야 한다. 이용신청이 서비스별이므로 401 을 받은 **엔드포인트만** 그 런에 다시 부르지 않는다(`_KRX_DENIED`
  집합 — 전역 플래그로 두면 미승인 /sto/ 401 하나가 /idx/·/gen/·VKOSPI 까지 막는다, 2026-09-30 리뷰).
  ETF 경로는 `/etp/etf_bydd_trd`(`/eto/` 는 404).
- **ECOS 한국 4종의 정식 표** = GDP `200Y102/10111`(실질·계절조정·전기비), 소매 `901Y100/G0/T3`, 실업률
  `901Y027/I61BC/I28A`(원계열), 가계신용 `151Y001/1000000`. ITEM_CODE2 축이 있는 표는 `"G0/T3"` 처럼 두 코드를 붙여
  보내야 같은 시점 행이 섞이지 않는다. 종전 코드는 전부 INFO-200(자료 없음)이라 KeyStatisticList 폴백(최신값 1개)만 타
  history 가 1점이었다.
- **R-ONE 은 날짜 범위(FROM/TO)를 무시한다** — `WRTTIME_IDTFR_ID` 단일 월로 물어야 한다(범위로 물으면 2003년부터 오래된
  순 56,148행). `CLS_FULLNM` 은 `>` 구분자(`서울>강북지역>…`).
- **T 표(국토부 주택 공급 통계)는 분류 코드가 5자리 정수이고 표마다 달라 `CLS_ID=500001` 이 안 먹는다** — 전국 코드는 표별로 적어
  두고(착공·준공 `50019`·인허가 `50023`) 무필터 전체 행은 잘려 쓸 수 없다. R-ONE 은 통계누리보다 1개월 늦다.
  **미분양은 R-ONE 표(T237973129847263)에 2007년 이후 전국 행이 없다**(10/1 일일 런 탐침 202607 90행·전국 0) → KOSIS
  `116/DT_MLTM_2080`(규모별 미분양) 전국 `13102792722A.0001`·부문 총합 `…B.0001`·규모 총합 `…C.0001`·항목 `13103792722T1`
  이 본선(`fetch_kosis_unsold`, 같은 시점 다중행이면 안 싣는다). 착공·준공·인허가 2순위용 KOSIS 코드는 `[KOSIS-probe]` 로그에 있다.
- **수출입은행 API 주소는 `oapi.koreaexim.go.kr`** (옛 www 주소 2026-04-30 종료 — 5개월간 연결 실패로만 남았던 원인).
- **푸시 재시도는 `scripts/merge_newer.py` 로 병합한다** — reset 뒤 풀 런 산출물을 통째로 덮으면 그사이 경량 런이 올린
  최신 시세가 되돌아간다(2026-09-30 실측). 시세 3블록·토스 4블록·history 를 시각 기준으로 합치고 `data_meta.json` 도
  맞춘다. 재시도 백업·재적용은 이번 런이 실제로 바꾼 산출물(`CHANGED`)만.
- **이력은 `history.json` 으로 분리(A14).** `data.json.history` 는 계열마다 끝 400점(`HISTORY_TAIL` — σ 251종가·52주
  365일·BTC 매일봉이 요구하는 최소), 전체는 `history.json`(일일 런에서만 다시 씀, `historyVersion` 으로 캐시 버스팅).
  프런트는 첫 화면을 data.json 만으로 그리고 `loadHistoryData()` 가 나중에 이어 붙인다. data.json 을 쓰는 다섯 곳
  (fetch_data 2·merge_newer·validate_data·ai_briefing)은 전부 `separators=(",", ":")` — 하나만 `indent=2` 로 돌아가면
  파일이 다시 4.8MB 가 된다(`scripts/tests/test_history_split.py` 가 지킨다). 일일 런은 그날 data.json 을 gzip 으로
  Release `snapshots` 에 올린다(400일 보관).
- **토스 수집기는 둘(집 PC + 고정 IP 서버, `scripts/server/`, `docs/TOSS_SERVER.md`)** 이지만 토스는 클라이언트당 토큰이
  1개라 동시에 돌면 서로 끊는다 → 서버 `TOSS_SNAPSHOT_ROLE=primary`, PC 는 `standby`(origin 스냅샷 `host` 가 다르고
  40분 이내면 건너뜀). 스냅샷 `host` 필드는 해시에서 제외.
- **지표 제외(2026-09-30 사용자 결정 D1)**: 풋콜비율·전월세전환율·엘니뇨 공식 예측 확률표는 화면·판정표에서 뺐다(무료 공식
  경로 없음). 버크셔 13F 는 미확보로 유지(고정 IP 서버에서 재시험 예정). NAHB 주택시장지수도 제거(FRED 종료, 그 자리에
  MSACSR 이 잘못 표시되고 있었다). 전월세전환율은 수집(R-ONE 카탈로그 검색)도 지웠다 — 옛 data.json·lane·preserve 로
  되살아나지 않게 **묘비 표 `data_sla.TOMBSTONED`**(단일 원천) 에 올렸고, 같은 표를 `fetch_data`(모든 preserve 뒤
  `drop_tombstoned`)·판정표(`_walk_paths`)·지표 레지스트리(`build_indicators`)가 본다. 지표를 뺄 때는 수집 블록 삭제 +
  이 표에 한 줄이다(`scripts/tests/test_tombstone.py`).
- 수급 포털 기준 = 네이버 증권 API(PC 표 `investorDealTrendDay` 는 2026-09-21 410). `_investor_align_portal` 이
  토스 바탕 시계열의 **모든 날짜**를 네이버값으로 바꾸고 `src: "naver"` 를 단다 — 이 행은 다음 런의 토스
  병합이 덮지 못하게 직전 빌드에서 복원한다(종전엔 최근 10일만 바꿔 창을 벗어나면 토스값으로 되돌아갔다).
  최근 10영업일은 매 런 재조회, 남은 토스 행은 런마다 40개씩 백필. 네이버 실패 시 KRX(pykrx) 확정치(`src: "krx"`,
  `investorTrading.krxDaily`) — 알림의 `investor_flows.portal_daily()` 도 같은 순서다.
- **KOSIS 는 통계표선택 방식(`Param/statisticsParameterData.do`)** — `statisticsData.do` 는 사전등록(`userStatsId`) 전용이라
  orgId/tblId 호출이 늘 실패했고 로그에도 안 남았다(2026-10-01). 새 표는 `[KOSIS-probe]` getMeta 로 분류·항목 코드를 먼저 확인한 뒤 붙인다.
- **시도 17 매매·전세 시계열 `realestate.kr.regionSeries`(2026-10)** — R-ONE 표준 지역분류 CLS_ID 500008~500024(`RONE_SIDO_CLS`, 무키 탐침 실측)로 시도마다 한 번 질의해 끝 36개월(아파트 매매 A_2024_00045·아파트 전세 A_2024_00050). 일일 런에서 전국 매매지수 기간보다 뒤처진 시도만 다시 묻는다(새 달 34콜, 평소 0콜). 못 받은 시도엔 preserved 를 달지 않는다(칸 날짜가 낡음을 말한다) — 달면 lane 계획이 R-ONE 묶음을 매시 다시 부르는데 매시 런은 이 시계열을 안 물어 표식이 안 지워진다. 묶음 = `market-realestate` 의 `regions.items[].series`·`capital.*.series`.
- **KRX 보기 확장 `rankingsKr.marketCap·volume·high52·low52`** — A19 와 같은 일별매매정보 두 표(런 캐시라 추가 호출 0), `{as_of, kospi:[20], kosdaq:[20]}`. 52주 고저는 일별 표에 없어 종목별 주간 고저를 `.krx_hilo_cache.json`(GHA cache, 커밋 안 함)에 쌓고 일일 런마다 시장별 30평일씩 되짚는다 — 그 시장 창 안 235거래일 미만이면 52주 목록을 싣지 않고 옛 목록도 잇지 않는다. 분할·병합·큰 증자(상장주식수 1.2배)·상장 1년 미만은 뺀다. 판단은 시장 단위(한 표 401 이 다른 시장 축적·목록을 막지 않는다, 못 받은 시장만 직전 행을 preserved 로). `fetch_krx` 는 결과 칸(OutBlock) 없는 200 응답을 휴장일로 담지 않는다. 401 엔드포인트는 `sourceStatus["data-dbg.krx.co.kr"].denied`. `merge_newer` 는 KRX 4목록을 토스 칸과 따로 각자 as_of 로 고른다. 묶음 = `market-domestic.views.marketCap…low52`.
- **배당·실적 일정 `corpEvents`** — OpenDART 공시검색(거래소공시 I, 90일)의 「잠정」실적·「배당결정」 + 배당에 관한 사항(직전 사업보고서 보통주 주당 현금배당). 대상 = 관심목록(ETF 제외) + 거래대금 상위, 30종목 이하. 공시검색은 일일 런(09·16·22시)마다, 배당 표는 KST 하루 1회(`OPENDART_API_KEY` 는 fetch 단계에도 넘긴다). 기업코드 0건·전 종목 실패면 직전 블록을 preserved 로 잇는다. 날짜는 공시 접수일·결산기준일이다 — 앞으로의 실적 발표일은 OpenDART 목록에 없다. 묶음 = `home.schedule`(오늘~7일, `kind`)·`market-domestic.views.corpEvents`.

## Cloudflare Worker

Deployed from `cloudflare-worker/`. Acts as:
- **CORS proxy** for `ALLOWED_HOSTS` whitelist only (no open proxy)
- **POST /portfolio** — writes `alerts_config.json` to GitHub via dispatch (requires SHA-256 sync key)
- **POST /ai** — proxies AI API calls with rate limiting
- **POST /sync-key** — verifies or changes the sync key (KV `auth:syncKeyHash`). 검사만 = 헤더 `X-Sync-Key-Hash`, 본문에 `newKey` 없음 · 바꾸기 = 본문 `{currentKey, newKey}` 원문(`SHA-256(currentKey.trim())` 비교, 새 키 12자 이상 · 지금 키와 다름, 아니면 400 `weak_new_key`) · 옛 `newKeyHash` = 400 `use_new_key`(해시만으로 못 바꾸게). 키 바꾸기는 새 화면 설정 › 기기 연결에서만 — 옛 화면(`js/app2.js`)은 안내만 한다(보유를 새 열쇠로 다시 잠가야 해서)
- **Cron triggers** → `repository_dispatch(kakao-send)` to GitHub, which fires `kakao-daily.yml`
- **KR 휴장일은 `worker.js` `KR_HOLIDAYS`(KST 날짜)** — 이 날 KR 장중 창(UTC 00~06시)엔 alerts·fetch 를 매분 깨우지 않는다(2026-10-05 대체공휴일에 300런이 「휴장 추정」만 찍었다). 음력 명절·대체공휴일은 해마다 다음 해 목록을 미리 넣는다. 검사 `node cloudflare-worker/test_offhours_tick.mjs`.

Deploy: `npx wrangler deploy` (config = repo-root `wrangler.jsonc`). Pushes to main are also auto-deployed by Workers Builds (deploy times track bot commits ~1 min later, 2026-09-29 실측), so a manual deploy of unpushed code is overwritten by the next bot commit.

## Important Constraints

- **Never hardcode API keys** — this is a public repository. All keys via GitHub Secrets only. The guard pattern is `if not API_KEY: skip/return`.
  커밋 전 비밀값 검사: 클론 후 한 번 `python scripts/install_hooks.py` 로 pre-commit 훅을 설치한다(`scripts/check_secrets.py`, 전체 점검은 `--all`, 오탐은 줄 끝 `# secret-ok`).
  비밀 파일(키·토큰·동기화키·`.env`)은 저장소 밖 `C:/Users/cgpar/.secrets/econ/` 에만 둔다.
- **`alerts_config.json` is intentionally public** — it stores only alert *conditions* (symbol/name/market/target) and the watchlist. It contains **no personal holdings** (no average cost, quantity, or purchase FX); the frontend never sends those and the Worker commits whitelisted fields only. Both `GET`/`POST /portfolio` require the `ALERTS_SYNC_KEY` (SHA-256) auth — `GET` takes it **only** from the `X-Sync-Key-Hash` header (the `?keyHash=` query form was removed 2026-09-29).
  **The E2E-encrypted holdings blob (`encHoldings`) lives in Worker KV (`ECON_PORTFOLIO`, key `portfolio:encHoldings`), never in this file** — until 2026-09-29 it was committed here, and a public ciphertext is offline brute-force material (the audit decrypted it with the lock PIN). Do not re-add it to the file or to the Worker's merge-with-previous logic. The page lock (`js/app4.js`, 투자 현황·설정) is a **device-level UI curtain only**: each browser sets its own PIN on the site (`localStorage.econLockPin_v2` = PBKDF2-SHA256 600k + random salt; unlock flag `sessionStorage.econLockOk_v1`, which the UI gates pre-set). Nothing about it is in a public file. "PIN 잊음" clears it only after the sync key verifies (`POST /sync-key` without `newKey` = check only).
  **Sync key auth has one resolver** — `_verifySyncKey` → `_expectedSyncKeyHash` (worker.js): KV `auth:syncKeyHash` (set from the site by 「키 바꾸기」 → `POST /sync-key` body `{currentKey, newKey}` raw — 해시만으로는 못 바꾼다, old `newKeyHash` = 400 `use_new_key`) wins, else SHA-256 of the secret `ALERTS_SYNC_KEY`. Every authenticated route (`/portfolio` GET·POST, `/portfolio/test`, `/ai`, `/sync-key`) goes through it and `AI_LIMITER` (10/min, incl. GET `/portfolio` — the key can now be a human passphrase). The sender path is separate: header `X-Push-Read-Key` = secret `PUSH_READ_KEY` reads `GET /prefs`(읽기 전용, 다른 메서드 403 `read_only`) and `/push/subscriptions` of the currently valid key's space — CI 는 이것만 받고 동기화 키를 갖지 않는다(GitHub 시크릿 `ALERTS_SYNC_KEY` 는 2026-10-09 삭제, `prefs_client` 의 폴백도 지웠다 — 다시 넣지 말 것. Worker 시크릿 `ALERTS_SYNC_KEY` 는 KV 해시가 없을 때 인증에 쓰이므로 그대로다). `POST /portfolio` 는 `encHoldings` 를 덮기 전 판을 날짜별 `portfolio:encHoldings:prev:<KST 날짜>`(그날 첫 판만, 30일)에 남긴다 — 보유 덮어쓰기는 해시만으로 되기 때문(자동 올림은 키 원문이 없다). Forgotten passphrase → `cloudflare-worker/README.md` 「동기화 키」.
- **`alerts_state.json` 의 `_prefs`(새 화면 조건 발동 기록)는 공개 파일이다** — 조건 id·종류·발동 시각·발생 키 해시만 싣고, 발생 키는 GitHub 시크릿 **`ALERTS_STATE_SALT`** 로 HMAC 한다(`check_alerts._kh`). 이 값은 동기화 키(Worker 시크릿 `ALERTS_SYNC_KEY`)와 **반드시 달라야 한다** — 원문(날짜·asOf·일정 이름)은 누구나 아니까 동기화 키로 HMAC 하면 공개 해시가 그 키의 오프라인 대입 창구가 된다. 미설정이면 `/prefs` 조건 평가를 통째로 건너뛴다(평문 해시로 되돌아가지 않는다). 조건 id·「다시 켜기」(`cond.armedAt`) 규칙은 `app/src/lib/personal/alertStatus.ts` 머리 주석 한 곳.
- **Pages = allowlist deploy (`.github/workflows/pages.yml`, since 2026-09-29)** — only the files listed in `scripts/collect_site.mjs` are public; everything else (this file, `docs/`, `scripts/`, `tests/`, `alerts_config.json`) 404s. **A new file the page fetches must be added to that list** or it 404s in production (local `http.server` still serves it). Bot commits (GITHUB_TOKEN) do not fire `on: push`, so deploys follow `workflow_run` of Market Data Fetch / Build Frontend / Link Check — renaming those workflows breaks deploys silently (`scripts/tests/test_watchdog.py` guards the names). Rollback: `gh api -X PUT repos/0101-commits/economic-site/pages -f build_type=legacy -f "source[branch]=main" -f "source[path]=/"`.
- **`data.json` is bot-owned** — only `fetch_data.py` writes it. The commit step uses a 5-retry push loop with `reset --hard origin/main` + re-apply to survive concurrent bot pushes.
- **`concurrency: group:`** in all three data workflows prevents simultaneous pushes that would cause non-fast-forward rejections.
- **`validate_data.py` is a hard gate** — it runs before the commit step. If it exits non-zero, `data.json` is not committed and the previous good version is preserved.
- **pykrx pinned at `1.2.8`** — KRX requires login since 2026; `KRX_ID`/`KRX_PW` secrets enable it. Do not unpin without testing KRX login behavior.
- **KIS API disabled by default** (`KIS_ENABLED=0`) — frequent token requests trigger KakaoTalk alerts from Korea Investment Corp. Enable via repo variable `KIS_ENABLED=1` only if needed.
- **Study-log data is browser-local only** — the 스터디 기록 page (`page-study`) keeps session metadata in
  `localStorage['econ_study_v1']` and uploaded media blobs in `IndexedDB(econStudyDB/files)`. Never route these
  through `data.json`, the Worker, or the repo; media files would blow up repo size and leak private recordings.
  Cross-device transfer is by explicit JSON export/import only. CSP carries `media-src 'self' data: blob:` solely
  so those local blobs can play — do not widen it further.
- **Chart.js colors must come from `getThemeColors()`** — the canvas cannot resolve
  `var()`, so that helper reads the astryx tokens via `getComputedStyle` and hands
  Chart.js concrete values. It caches per theme; `invalidateThemeColors()` runs
  before `applyChartJsThemeDefaults()` on theme switch. Don't reintroduce a
  hardcoded color map, and don't reference `color-mix()` tokens from it —
  browsers serialize those as `color(srgb …)`, which `@kurkle/color` can't parse.
- **`getThemeColors()`'s cache vars are `var`, not `let`** — top-level constants
  earlier in the same script block call it (chart palettes), so a `let`
  declaration puts them in the temporal dead zone and the whole block's
  top-level execution aborts with `Cannot access '_tcCache' before
  initialization`. This regressed once; keep `var`.
- **Theme switch remaps dataset colors** — `rebuildChartsForTheme()` diffs
  `window._tcPrevPalette` against the new palette and rewrites `borderColor`,
  `backgroundColor`, datalabels, etc. (alpha suffixes are carried over by
  prefix match). Any new theme-dependent chart color must be part of that
  palette array or it will stay stuck on the previous theme's value.
- **`window._UPDN` mirrors `--color-market-*`** — hex literals are required there
  because the code does `CUP + '22'` alpha concatenation. If the market colors
  change in the bridge, update `_UPDN`/`_UPDN_FILL` in the same commit —
  `scripts/vendor_seed_css.py` diffs them against base.css and exits 1 on drift.
- **Tailwind CDN must not be re-added** — removed intentionally because its runtime JIT uses `eval()`, which violates the site's CSP.

## Local Development

There is no dev server or build process. Open `index.html` directly in a browser, or serve it:

```bash
python -m http.server 8000
# then open http://localhost:127.0.0.1:8000
```

The browser will fetch `data.json` from the same origin. For local testing with a live data pipeline, manually trigger `fetch-data` via Actions → workflow_dispatch.

To run data scripts locally (requires secrets as env vars):

```bash
pip install requests yfinance "pykrx==1.2.8" beautifulsoup4 lxml matplotlib
KRX_ID=... KRX_PW=... FRED_API_KEY=... python scripts/fetch_data.py
python scripts/validate_data.py   # verify output
```

## 알림 v2 — 사건 사전 · 원장 · 등급 (2026-10-05, 기획서 93GornDyzLc6rfrZcu4QXV · 계약서 `docs/superpowers/plans/2026-10-05-alerts-v2.md` · 운영서 `docs/ALERTS_V2.md`)

- **「언제 울릴지」는 `scripts/alerts_v2/events.yml` 한 파일이 정한다**(사건 37 + 사용자 2, 갈래 A~H, 등급 alarm/alert/notice/record, 평가 런 light/full/settle/daily/eve, 쿨다운, 문구 틀). 사건 이름 · 임계 · 등급을 코드나 화면에 글자로 적지 말 것 — 화면 사전은 `python scripts/alerts_v2/export_dict.py` 가 `app/src/lib/alerts/dict.json` 으로 내보내고 `test_v2_parity.py` 가 사전 ↔ 판정 함수(`events.JUDGES`) ↔ dict.json ↔ 틀 변수를 맞춘다.
- **판정은 `judges_market.py`(A · B · C · H1) · `judges_flow_cal.py`(D · E · F · G · H2~H4)** 의 `@judge("이름")` 함수. 값 · 등락 · 신선도는 `context.Context` 의 `value/change_pct/fresh/as_of`(번들 = 화면과 같은 값)에서만, 과거는 `series`. σ 는 `volatility.sigma`(check_swings 와 같은 식), 임계 = `min(max(kσ, 0.5%), 5%)`. **종목 대상(국내 6자리 · 미국 티커)은 `Context.stock`** 이 옛 종목 알림의 시세 길(`check_alerts.get_snapshot`, 장 시간 · 휴장 · 오염 규칙 그대로, 한 런 종목당 한 번)로 값을 대고, 오늘 live 인 묶음 행이 있으면 그 값을 먼저 쓴다 — 이게 없던 10/6~10/9 동안 사용자 조건 36건(전부 종목)이 한 번도 안 울렸다. 종목 B1 사용자 조건은 `subscribe._stock_b1` 이 사전 `high52` 를 그 종목에 그대로 쓴다. **U1 은 넘는 순간만 울린다**(2026-10-09 사용자 결정) — 직전 쪽은 공개 `alerts_state.json._prefs[조건 id].side`(u/d 한 글자, 임계 · 값 없음)이고 그 파일을 커밋하는 light 런(stock-alerts)만 U1 을 본다. 처음 보는 조건은 쪽만 남기고 울리지 않는다.
- **원장 `events/YYYY-MM-DD.json`(추가만) + `events/latest.json`(7일)** — `ledger.Ledger.append` 는 같은 key(`사건:대상:방향:기준일`)를 40일 안에서 두 번 넣지 않는다(재시도 런 · 중복 dispatch 가 두 번 울리지 않는 장치). 사용자 조건 행은 `cond`(조건 id)만, 임계값은 없다. Pages 허용 목록(`collect_site.mjs`)에 `events/` 가 들어 있다.
- **발송 사슬 = `run.py --mode …` → 추출(extract) → (ALERTS_V2=1) 구독(subscribe: 꾸러미 · 기본 켜짐 · 별표 · 사용자 조건 U1/U2 HMAC) → 편성(schedule: 조용한 시간 보류 · 하루 상한 묶음 · 쿨다운 · 카톡 쿼터 18/20) → 발송(deliver: 푸시 큐 · 카톡 `send_card` · 디스코드 `notify_discord.send_level`)**. 세 채널은 독립이고 결과는 원장 행 `sent` 에 남는다.
- **채널 역할**: 푸시 = 울림(`requireInteraction` 은 경보만), 카톡 = 친구 모드면 울림 + 사진, 아니면(`KAKAO_FRIENDS=0` · 친구 0명) **메모로 디스코드에 가는 것을 전부 따라 보냄**(소리 없음, `deliver.memo_mode`), 디스코드 = 전부 울림(`alarm`→SWINGS @everyone · `alert`/`notice`→ALERTS · `brief`→URL · `ops`→SYSTEM). **2026-10-07: 안내·브리핑에 무음 플래그(4096)를 달고 카톡을 통째로 껐더니 하루 디스코드 10통 중 소리 1통·카톡 0통이 되어 「알림 안 옴」 — 둘 다 되돌렸다. 무음 플래그를 다시 달지 말 것.** 같은 사건의 두 채널 제목은 같다(compose 가 한 번 만든다).
- **전환 변수 `ALERTS_V2`**: 0 = 원장만 쓰고 발송 없음(기본), 1 = v2 발송 + 현행 발송 단계 건너뜀(stock-alerts 의 종목 · 서킷 · 급변, fetch-data 의 발표 · 메르 임계, kakao-daily 자동 슬롯). 되돌리기는 0. 시크릿 6종 · 친구 모드는 `docs/ALERTS_V2.md`.
- **브리핑 카드는 `alerts_v2/cards.brief_card_png`**(기획서 5장 목업 — 아침 목록 · 마감 칸+하루 흐름+수급 · 주간 칸+행, 값은 `cards.quote` = 번들 띠). 옛 `_build_kakao_card`·`close_report` 는 현행(ALERTS_V2=0) 경로 전용이다. 카톡 업로드(`kakao_upload_image`)는 PNG bytes · 경로 둘 다 받는다 — 경로만 받던 때 v2 카톡이 전부 텍스트로 떨어졌다(2026-10-08).
- **워크플로**: light = `stock-alerts.yml`(매분, 테스트 통과 마커 캐시 `pytest-ok-<hash>`), full/daily = `fetch-data.yml` 끝, settle 18:05 · eve 21:00 = `alerts-v2.yml`, 브리핑 = `briefing.yml`. 원장은 각 워크플로의 커밋 단계가 `events/` 를 함께 올린다.
- **게이트**: `test_v2_*.py`(사전 · 원장 · 문구 · 구독 · 편성 · 발송 · 카드 · 판정 · 파리티 · 재생). `python scripts/alerts_v2/replay.py --days 400 --watch …` 가 400일 재생 표(`docs/alerts_v2_replay.md`)를 만든다 — 사전 임계를 바꾸면 다시 돌려 하루 평균 ≤4 를 확인할 것.
- **함정**: 격리 워크트리 에이전트는 main 에서 시작하므로 `alerts-v2` 로 올리지 못하면 커밋을 cherry-pick 한다 · 테스트는 `mer_signals.json` 을 더럽히므로 `git checkout -- mer_signals.json` · Windows 콘솔은 `PYTHONIOENCODING=utf-8`.

## KakaoTalk Integration

- `KAKAO_REST_API_KEY` + `KAKAO_REFRESH_TOKEN` secrets required
- Cloudflare Worker cron (`:02 UTC` each slot) fires `repository_dispatch(kakao-send)` → `kakao-daily.yml`
- Duplicate-send guard: GHA cache marker keyed by `date + slot`; manual `workflow_dispatch` always bypasses
- Charts use `matplotlib`. 피드 이미지는 슬롯 편성(`discord_card.PROFILES`) 기반 정사각 카드가 1순위이고, `SLOT_CHARTS_WEEKDAY`(슬롯별 2티커 라인 차트)는 그 폴백으로 남아 있다 — 카드가 안정될 때까지 삭제하지 말 것
- **카카오 발송은 전부 카드(사진)가 본문이다**(기획 v3 — 정기 시황·주간·종목·급변·서킷 발동/해제·테스트·장 마감). 새 발송을 추가할 때는 `kakao.send_card()` 를 쓰고 정사각 카드를 함께 만들 것 — `send_memo` 직접 호출은 `scripts/tests/test_kakao_cards.py` 가 실패시킨다
- 수신 모드는 “나와의 채팅”으로 유지한다(변수 `KAKAO_FRIENDS=0`). 푸시가 필요하면 `docs/KAKAO_SETUP.md ⑤`(보조 계정 + `friends` 재동의)를 따라야 하고, 그때까지 **카톡 무음은 버그가 아니다**. 실시간 알림은 디스코드가 담당
- **알림 글의 역할 분담(2026-09-24 개편, 게이트 `scripts/tests/test_alert_redesign.py`)** — 카드 = 얼마나 움직였나, 글 = 카드가 못 하는 말. 규칙:
  - **제목은 `send_kakao_digest.headline()` 하나**(정기·마감, 두 채널 공통): `M/D 슬롯이름 · 이례 1건 · 주인공 · 두 번째 움직임`, `TITLE_MAX`=48자. 제목에 시각(`18시 시황`)을 쓰지 않는다. 이례는 `discord_card.market_anomalies()`(카드 키 + MOVE·VKOSPI·미/한 10Y) — 주인공 후보(`anomalies()`, 인트라데이 가능한 키만)보다 넓다. 같은 날 같은 이례는 `repeat_hit()` 로 한 번만(`.kakao_focus.json` 에 제목 이례도 기록)
  - **카톡 사진 아래 두 줄 = `slot_ai_line()`(그 카드 숫자로 Gemini 한 문장, `kakao-daily.yml` 에 `GEMINI_API_KEY`) + 이유(메르 사슬) 또는 슬롯 주제 뉴스(`slot_news`)**. 지표 블록은 전부 행으로. AI 문장은 `ai_briefing.slot_line_ok` 가 상대 시점어(내일·연휴·다음 주)·권유를 거른다 — 실패하면 문장 없이 보낸다
  - **표기 단일 원천은 `discord_card`**: `stale_tag`(기준일 꼬리표 — 본문 `_stale_tag` 도 이걸 부른다) · `period_label`/`week_period`(기간) · `kr_closed`(휴장 = `marketCalendarKr.today.open is False`) · `tile_asof`(금리 FRED 지연·휴장 지수 타일에 `·9/22` 꼬리표). 묵은 값의 변화는 제목에 올리지 않는다(`■0bp` 방지)
  - 디스코드 지표 버튼 라벨은 **방향 이모지 + 이름만**(등락률은 카드가 한 번만 말한다), 유틸 버튼 2개(대시보드·지금 시세). 카톡 버튼 라벨은 `quote_btn_title()`(8자 — 급변 경로 포함)
  - 수급은 12시 슬롯만 잠정으로 싣는다(`PROVISIONAL_FLOW_SLOTS`, 꼬리표는 `investor_flows` 판정 그대로). 교차검증 실패는 종전대로 생략. 마감 특징주는 `_kospi_movers()`(±30% 초과 = 상장 첫날·코스닥 제외)

## Local Toss collector (this PC, not CI)

Toss Open API binds every client to an **IP allowlist** (WTS → 설정 → Open API → 허용 IP 관리).
There is no CIDR or wildcard entry, so CI can never be allowlisted. The collector runs here
instead and hands its result to the cloud pipeline through the repo.

**2026-09-30 부터 수집기는 둘이다.** 주(primary) = Oracle Cloud 무료 등급 Ubuntu 서버(고정 IP, systemd 타이머
15분, `scripts/server/`, 설치·운영 안내 `docs/TOSS_SERVER.md`, 접속키는 사용자 PC `Downloads\ssh-key-2026-09-30.key`,
`ubuntu@` 계정). 대기(standby) = 이 PC(`TOSS_SNAPSHOT_ROLE=standby` 사용자 환경변수): origin 스냅샷의 `host` 가
자기와 다르고 40분 이내면 수집을 건너뛴다. 왜 둘을 동시에 돌리지 않는가 — 토스는 클라이언트당 토큰 1개라 재발급이
상대 토큰을 즉시 무효화한다(`token-revoked` 실측). 서버 쪽 함정: 저장소는 `--depth 1` 로만 복제(전체 14,500커밋은
1vCPU 에서 index-pack 10분+), 실행 스크립트는 매번 `origin/main` 으로 강제 복귀(rebase 충돌을 방치하면 detached
HEAD 로 매 실행 실패). 서버 비밀값은 `/etc/economic-site/toss.env`(600) 한 곳.

| Piece | What it does |
|-------|--------------|
| `scripts/fetch_toss_snapshot.py` | Fetches indices, the KTB curve, gainer/loser rankings (stocks **and** ETFs, KOSPI+KOSDAQ), trading-amount + Toss-retail rankings, KOSPI investor flows, **per-stock flows for the tracked watchlist** (investor/short-selling/credit/lending/program/warnings — `stockData`), the KR market calendar and the USD/KRW quote; writes `toss_snapshot.json`; `--push` commits and pushes it |
| `scripts/run_toss_snapshot.cmd` | The actual runner. **ASCII only** — cmd.exe parses batch files in the OEM code page, so UTF-8 Korean comments get executed as commands (seen as exit 9009) |
| `scripts/run_hidden.vbs` | Task Scheduler entry point for every local task (`wscript.exe //B //Nologo run_hidden.vbs <name>.cmd`). Runs the named `.cmd` in the same folder with no window and returns its exit code, so `RestartOnFailure` still works. **`<Hidden>` in the task XML does not hide the console** — it only hides the task in the scheduler UI, so a `.cmd` action under `InteractiveToken` flashed a window 45×/weekday (2026-09-08). Run the `.cmd` directly when you want to watch it |
| `scripts/verify_pipeline_fix.py` + `run_verify_fix.cmd` + `register_verify_task.ps1` | **관측 종료 — 예약 작업 `EconSite-FixVerify` 는 2026-09-22 삭제했다**(1주 실측에서 최대 간격 101분, 스테일 경고 0건·자동 디스패치 0건). 스크립트는 남겨 둔다: 같은 종류의 관측이 다시 필요하면 `register_verify_task.ps1` 로 되살린다. Post-fix observation for the 2026-09-08 change. Measures `data.json` commit gaps against the *slot-time* threshold, counts `fetch-data` `workflow_dispatch` runs (the only proxy for ⚙️ warnings — Discord is not readable and actor cannot separate bot from human), counts off-hours `:35` top-ups, and reads the Toss task's exit codes; reports to Discord `#시스템`. |
| `scripts/register_toss_task.ps1` | Registers the `EconSite-TossSnapshot` task from XML (PowerShell 5.1's `New-ScheduledTaskTrigger` cannot set a logon `Delay` or a repetition) |

The machine is not on 24/7, so four things cover the gaps: a logon trigger with a 3-minute
delay, **15-minute** runs on weekdays 09:00–20:00 (2026-08-20, was hourly), a 15:45 run right
after the close, and `StartWhenAvailable` to catch up on anything missed while the PC was off.

Downstream of the snapshot (2026-08-20 full-adoption plan, artifact bf927a4a):
- `fetch_data.py` consumes `indices` (same-day only), `etfMovers`, `rankings` →
  `data.json.rankingsKr` (same-day only), `stockData` → `data.json.stockFlows`
  (records carry dates, any age), `marketCalendarKr`, and cross-checks `usdkrw`
  (`diagnostics.fxTossCross`, never overrides). Per-stock flow units are **shares**,
  not KRW — the Toss endpoints have no amount fields.
- The frontend renders `stockFlows` in the 종목분석 tab (`_pfFlowsRender` in app6.js:
  investor bars + short/credit/lending/program chips + warning badges + market cap
  from `shares × price`) and `rankingsKr` on the equity page (`buildEquityRankings`,
  rows deep-link to 종목분석). Widgets hide when data is absent — no fallback source.
- `check_alerts._check_toss_warnings` diffs per-stock `warnings` against
  `alerts_state.json`'s `_tossWarnings` key and posts designation changes
  (투자경고/단기과열/…) to the alerts Discord channel. First observation is
  baseline-only (no spam on reintroduction).
- The `kakao-daily.yml` holiday gate trusts `marketCalendarKr` first (KRX-accurate)
  when its `today.date` matches, falling back to Nager.Date otherwise.
- `_is_valid_mover_list(allow_extreme=True)` is used for Toss rankings: the
  "limit-up majority = garbage" rule false-positives on real KOSDAQ-inclusive
  top-10 lists (measured 6/10 on 2026-08-20); official `changeRate` can't have
  the column-misalignment garbage that rule was built for.
- Toss issues **one valid token per client** — a re-issue kills the previous token.
  `toss_api.py` shares tokens across processes via `%TEMP%\toss_token_cache.json`
  and re-issues once on 401.

Because it runs often, the script hashes only the fields `fetch_data.py` consumes and skips
rewriting the file when nothing moved — otherwise every run would be a commit. `usdkrw` is
deliberately outside that hash: it drifts around the clock and nothing reads it. A no-change
run never bumps `generatedAt`; a fresh timestamp on stale data would defeat the consumer's
freshness guard. Whether to push is decided by `git status`, not the hash, so a file left
dirty by a failed push is retried on the next run.

Credentials are the user env vars `TOSS_CLIENT_ID` / `TOSS_CLIENT_SECRET`. If they are
missing the script exits 1 with a log line and the pipeline just falls back.

### Connection status surfaced to the UI

`fetch_data.toss_connection_status()` turns the snapshot's `generatedAt` into
`data.json.diagnostics.toss` = `{state, generatedAt, ageMinutes, supplied, reason}`.
`state` is `LIVE` (≤2 h, one scheduler tick of slack), `IDLE` (older, but it is a KR holiday /
weekend / outside 09:10–16:00 — the collector does not rewrite an unchanged file, so an aging snapshot
is normal; 2026-09-24), `STALE` (≤96 h during business-day market hours — the collector PC is likely
off), or `OFFLINE` (missing / unparsable / older). `IDLE` is silent in the UI like `LIVE`. `supplied` is read back out of
`data["sources"]`, so a block only counts as Toss-provided when the label says it actually was.

`_tossChipHtml()` (`js/app1.js`) renders it next to the header timestamp and **stays silent on
`LIVE`** — a chip that is always present stops being a warning. Without this the fallback was
invisible: when the collector PC is off, indices/KTB/rankings/investor flows quietly switch to
pykrx/yfinance while the numbers on screen look unchanged.

Regression test: `python scripts/tests/test_toss_status.py` (12 cases — boundaries, missing
snapshot, unparsable timestamp, clock skew, weekend/holiday IDLE via today or yesterday's calendar).

**Toss daily candles are an integrated session** (pre-market + regular + after-hours), so
their close is not the base price percentage moves are quoted against. Use `rankings()`'s
`changeRate` for per-stock moves. Indices have no after-hours print and are safe.
