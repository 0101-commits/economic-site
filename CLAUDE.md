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

`scripts/econ.theme.ts` + `build_astryx_tokens.py` are **no longer part of the
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

Editing a color = editing the bridge. `scripts/econ.theme.ts`,
`build_astryx_tokens.py`, `patch_astryx*.py` are **provenance only** — the block
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
| `scripts/investor_flows.py` | 투자자 수급 단일 창구 — 네이버 일별 표 파서 + 토스 어댑터 + `agree()`/`gross_mismatch()`/`verified_latest()`/`week_sum()`. **표시값=네이버(사용자가 대조하는 포털·언론 기준), 토스=교차검증**. 토스와 네이버는 같은 날 수천억 차(2026-09-10 기관 -134 vs +5,744억 — 집계 유니버스 차이)라 단일 소스로는 알림 값이 실제와 어긋났다. 검증 실패 = 숫자 생략(추정 금지). 가드 `python -m pytest scripts/tests/test_investor_flows.py` |
| `scripts/discord_card.py` | 카드 PNG 렌더러(matplotlib) — 디스코드(가로 10×7)와 카카오(정사각 1080², `shape="square"`) 공용. **도안 3형**(기획 v3): 사건형 `stock_alert`·`swing`(타일 + 인트라데이 임계선) / 상태형 `status`(상태 배지 + 타임라인 — 해제·테스트처럼 차트가 의미 없는 통지) / 지표형 `board`·`weekly`·`close_report`. 공통 골격 = `_sq_fig`/`_head`(제목 — 제목과 우측 보조가 한 줄을 **폭으로** 나눠 쓴다) + `_draw_cells`(타일; `_draw_tiles` 는 편성표 키를 셀로 바꿔 같은 함수를 쓴다) + `_sq_panel`(선 그래프) + `_footer`. **카드 내부 텍스트에 이모지 금지**(CI·로컬 폰트에 글리프 없음 — 제목이 담당). 바탕 = 흰색, UP/DN(`#E0443E`/`#3E7BE0`)은 채움색 전용이고 작은 글자는 `UP_TXT`/`DN_TXT`. 편성표는 `_CATALOG` 키만 참조하므로 `_ASSETS` 는 건드리지 말 것. 미리보기 `python scripts/discord_card.py all -o out/ [--square]`, 가드 `python scripts/tests/test_discord_card.py` + `test_kakao_cards.py` + **`test_card_layout.py`(글자 겹침·캔버스 이탈·타일 삐짐 0건)** + **`test_readability.py`(정보 보존·카드↔본문 중복·글자 하한·강도 대비·빈 띠·잘림 고지 6종)**

**판독 규격(2026-09-17 개편, 기획 HdmGyTK4).** 카톡 말풍선은 1080px 카드를 약 **270px**로 줄여 보여준다(축소비 4배). 그래서 판단 기준은 pt 가 아니라 **화면 글자 높이** = `pt ÷ 72 × dpi × (표시폭 ÷ 카드폭)` 이고, 한글 하한은 9px 다. 개편 전에는 카드 글자의 74~90%가 그 아래였다. 규칙 셋:
- 글자수(`[:44]`)로 자르지 않는다 — `_clip`/`_text_w` 가 **실제 렌더 폭**으로 자른다(한글·숫자·비율기호 폭이 제각각).
- 타일은 **2열 6칸**(`PROFILES`, 2026-09-17 사용자 결정으로 닛케이·달러인덱스·금 제외). 칸이 넓어야 글자가 커진다. `_draw_cells(note_inline=True)` 는 값과 등락률을 한 줄에 두고, 폭이 모자라면 자동으로 세 줄로 내려간다(값을 자르지 않는다).
- 차트에는 **세로축이 있다** — `_sq_panel` 이 전일·고가·저가를 값과 함께 패널 안에 적고(픽셀 간격으로 자리 다툼), 채움은 **전일선 기준**으로 위아래 색을 나눈다. 값 없는 격자선은 쓰지 않는다.
- **타일 색은 방향이 아니라 크기를 말한다**(2026-09-18). `_tile_color` 채도 하한은 **0.10**이다 — 0.30 이던 때는 0.16% 움직임도 곧장 뚜렷한 분홍이 되어 상승장에 6칸이 '붉은 벽'이었다(크기 정보가 색에서 사라진 상태). 방향은 `▲/▼` 가 이미 말한다. 등락률은 칸 오른쪽 끝이 아니라 **값 바로 옆**에 붙는다(한 쌍의 숫자를 읽는 데 시선이 칸 폭을 건너지 않게).
- **캔버스 높이는 재료 수가 정한다** — `close_report` 는 수급 바가 없으면 7.4→4.2~7.4 로 줄이고, 인트라데이가 없으면 다이버징 바가 전폭을 쓴다. 디스코드는 이미지를 폭에 맞춰 축소하므로 빈 띠는 그만큼 글자를 작게 만든다.
`SQ_MIN_FS`(13pt)는 하한일 뿐 목표가 아니다 — 카드별 폰트는 호출부 `fs=(라벨, 값, 등락)` 가 정한다. 세 줄로 내려가는 좁은 칸 경로도 이 하한을 다시 건다(종전엔 그 경로만 우회해 11.2pt 가 섞였다). |
| `scripts/notify_discord.py` | Discord webhook parallel channel (secret `DISCORD_WEBHOOK_URL`; digest/alerts/swings 병행 발송, 미설정 시 no-op). 버튼 라벨 방향 이모지 `direction_emoji`/`dir_label` (E2 표준 ±2%). v4 버튼 다이어트(기획 ed0e5496): 다이제스트 컴포넌트 = 유틸 버튼 1행(3개) + 지표 드롭다운 `select`(값=NAVER_LINKS 키, Worker `/discord` `goto_link` 가 에페메랄 링크 응답) — 구 16버튼 타일 미러 그리드는 폐기, 등락 정보는 카드 이미지 단독 담당 |
| `cloudflare-worker/worker.js` | CORS proxy + rate limiting + KakaoTalk cron dispatch |
| `data.json` | Market data artifact — committed by bot, never edit by hand |
| `data_meta.json` | Lightweight `lastUpdated` mirror of `data.json` |
| `alerts_config.json` | Stock alert rules (committed by bot via Worker `/portfolio`) |

## GitHub Actions Workflows

| Workflow | Schedule | Secret dependencies |
|----------|----------|---------------------|
| `fetch-data.yml` | Every 10 min (market hours), hourly (off-hours), daily KST 09/16/22 | `KRX_ID`, `KRX_PW`, `FRED_API_KEY`, `ECOS_API_KEY`, `REALESTATE_API_KEY`, `KOSIS_API_KEY`, `ALPHAVANTAGE_API_KEY`, `DATA_GO_KR_API_KEY`, `KIS_APP_KEY`/`KIS_APP_SECRET` (optional), `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET` (optional), `GEMINI_API_KEY`/`OPENAI_API_KEY` (for AI briefing) |
| `kakao-daily.yml` | Weekdays 07–22 KST hourly, weekends **and KR public holidays** 11 & 17 KST (Sunday 17h = weekly report mode; holiday detection = gate step via Nager.Date API, fail-open to weekday, `KR_HOLIDAY` env → script) | `KAKAO_REST_API_KEY`, `KAKAO_REFRESH_TOKEN` |
| `stock-alerts.yml` | Every 5 min during KR/US market hours | same Kakao secrets |
| `link-check.yml` | Periodic | none |

Trigger `fetch-data` or `kakao-daily` manually via **Actions → workflow_dispatch** for testing.

## Data Pipeline Architecture

```
GitHub Actions (fetch_data.py)
  → data.json + data_meta.json committed to main
    → GitHub Pages serves static files
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
1. **pykrx** (`pykrx==1.2.8` pinned) — KRX official (KOSPI/KOSDAQ/Top10/investor flows)
2. **yfinance** — overseas indices, commodities, FX fallback
3. **FRED API** — US macro indicators
4. **ECOS API** — Bank of Korea data
5. **R-ONE API** — Korean real estate indices
6. **KOSIS API** — Korean statistics
7. **Alpha Vantage** — US macro/commodity/FX supplement (25/day limit; only on daily runs via `AV_FETCH_FULL=1`)
8. **Naver/yfinance fallbacks** — when primary sources fail

The script **preserves previous values** on partial failure — individual API errors don't blank the data.

## Cloudflare Worker

Deployed from `cloudflare-worker/`. Acts as:
- **CORS proxy** for `ALLOWED_HOSTS` whitelist only (no open proxy)
- **POST /portfolio** — writes `alerts_config.json` to GitHub via dispatch (requires SHA-256 sync key)
- **POST /ai** — proxies AI API calls with rate limiting
- **Cron triggers** → `repository_dispatch(kakao-send)` to GitHub, which fires `kakao-daily.yml`

Deploy: `cd cloudflare-worker && npx wrangler deploy`

## Important Constraints

- **Never hardcode API keys** — this is a public repository. All keys via GitHub Secrets only. The guard pattern is `if not API_KEY: skip/return`.
- **`alerts_config.json` is intentionally public** — it stores only alert *conditions* (symbol/name/market/target) and the watchlist. It contains **no personal holdings** (no average cost, quantity, or purchase FX); the frontend never sends those and the Worker commits whitelisted fields only. Both `GET`/`POST /portfolio` require the `ALERTS_SYNC_KEY` (SHA-256) auth.
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
- **Alpha Vantage** has a 25 calls/day free limit — only fetch on daily triggers (`AV_FETCH_FULL=1`), not on every-hour runs.

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

## KakaoTalk Integration

- `KAKAO_REST_API_KEY` + `KAKAO_REFRESH_TOKEN` secrets required
- Cloudflare Worker cron (`:02 UTC` each slot) fires `repository_dispatch(kakao-send)` → `kakao-daily.yml`
- Duplicate-send guard: GHA cache marker keyed by `date + slot`; manual `workflow_dispatch` always bypasses
- Charts use `matplotlib`. 피드 이미지는 슬롯 편성(`discord_card.PROFILES`) 기반 정사각 카드가 1순위이고, `SLOT_CHARTS_WEEKDAY`(슬롯별 2티커 라인 차트)는 그 폴백으로 남아 있다 — 카드가 안정될 때까지 삭제하지 말 것
- **카카오 발송은 전부 카드(사진)가 본문이다**(기획 v3 — 정기 시황·주간·종목·급변·서킷 발동/해제·테스트·장 마감). 새 발송을 추가할 때는 `kakao.send_card()` 를 쓰고 정사각 카드를 함께 만들 것 — `send_memo` 직접 호출은 `scripts/tests/test_kakao_cards.py` 가 실패시킨다
- 수신 모드는 “나와의 채팅”으로 유지한다(변수 `KAKAO_FRIENDS=0`). 푸시가 필요하면 `KAKAO_SETUP.md ⑤`(보조 계정 + `friends` 재동의)를 따라야 하고, 그때까지 **카톡 무음은 버그가 아니다**. 실시간 알림은 디스코드가 담당

## Local Toss collector (this PC, not CI)

Toss Open API binds every client to an **IP allowlist** (WTS → 설정 → Open API → 허용 IP 관리).
There is no CIDR or wildcard entry, so CI can never be allowlisted. The collector runs here
instead and hands its result to the cloud pipeline through the repo.

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
`state` is `LIVE` (≤2 h, one scheduler tick of slack), `STALE` (≤96 h — the same bound as the
yield-curve guard), or `OFFLINE` (missing / unparsable / older). `supplied` is read back out of
`data["sources"]`, so a block only counts as Toss-provided when the label says it actually was.

`_tossChipHtml()` (`js/app1.js`) renders it next to the header timestamp and **stays silent on
`LIVE`** — a chip that is always present stops being a warning. Without this the fallback was
invisible: when the collector PC is off, indices/KTB/rankings/investor flows quietly switch to
pykrx/yfinance while the numbers on screen look unchanged.

Regression test: `python scripts/tests/test_toss_status.py` (8 cases — boundaries, missing
snapshot, unparsable timestamp, and clock skew producing a negative age).

**Toss daily candles are an integrated session** (pre-market + regular + after-hours), so
their close is not the base price percentage moves are quoted against. Use `rankings()`'s
`changeRate` for per-stock moves. Indices have no after-hours print and are safe.
