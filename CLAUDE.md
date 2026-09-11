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
```

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

## Key Files

| File | Role |
|------|------|
| `index.html` | Entire frontend — styles, charts (Chart.js), all page logic |
| `scripts/fetch_data.py` | ~7 000-line data collector; runs in GitHub Actions |
| `scripts/validate_data.py` | Data integrity gate — blocks bad `data.json` from commit |
| `scripts/ai_briefing.py` | LLM macro summary → `data.json.aiBriefing` |
| `scripts/send_kakao_digest.py` | KakaoTalk sender. **모든 카카오 발송의 단일 진입점 = `send_card()`**(기획 v3 I1): 카드 PNG → 슬롯 라인 차트 → 텍스트 3단 폴백, 버튼 2개·라벨 8자 (카카오 상한), `png=None` 으로 부르면 경고 + 디스코드 `#시스템` 교차 통보(사진 없는 경로가 생기는 것을 보이게 하는 장치). 피드 이미지 = `discord_card.board(shape="square")` 정사각 카드(디스코드와 **같은 편성표**) → 실패 시 `build_slot_chart_png` → 텍스트. **주간 슬롯도 카드**(`_build_kakao_card(weekly=True)` → `discord_card.weekly(shape="square")`) — 옛 `None if _weekly_mode` 분기는 제거됐다. 장 마감(**16:40**, 2026-09-11 15:40→이동)은 디스코드+카카오 병행. **수급(외국인·기관)은 `investor_flows.verified_latest()` 로 발송 직전 라이브 조회** — 네이버(포털·언론 기준)값을 토스로 교차검증해 통과분만 싣고, 오늘 날짜 행이 없거나 총체적 불일치면 숫자 대신 '집계 중'을 적는다(옛 `investorTrading.daily[-1]` 직참은 날짜 검증이 없어 어제 수급이 오늘 카드로 나갔다). 히어로 인트라데이는 `_session_chain`(Yahoo 5분봉 우선 = 당일 전 구간)이고 급변·마감 카드의 `_intraday_chain`(토스 1분봉 우선 = 최신성)과 **우선순위가 반대다**. 수신은 “나와의 채팅”(`KAKAO_FRIENDS=0`) — **푸시 알림 없음**이 정상 동작이다 |
| `scripts/check_alerts.py` | Stock alert evaluator. 카카오는 카드 한 통(`_alert_card(shape="square")` = 대표 종목 + 나머지 종목 타일 합본) + 항목 행 5줄로 보낸다 — 200자 한도 때문에 여러 통으로 쪼개던 텍스트는 폐기(`_pack_messages` 는 이제 '확정 대상 산정'용). 발동 줄 문구 단일 원천 = `_alert_lines` |
| `scripts/check_swings.py` | Market swing alert (코스피·S&P500 ±2%, 달러-원 ±1% 즉시 속보; cooldown = `alerts_state.json` `_swings` key) |
| `scripts/investor_flows.py` | 투자자 수급 단일 창구 — 네이버 일별 표 파서 + 토스 어댑터 + `agree()`/`gross_mismatch()`/`verified_latest()`/`week_sum()`. **표시값=네이버(사용자가 대조하는 포털·언론 기준), 토스=교차검증**. 토스와 네이버는 같은 날 수천억 차(2026-09-10 기관 -134 vs +5,744억 — 집계 유니버스 차이)라 단일 소스로는 알림 값이 실제와 어긋났다. 검증 실패 = 숫자 생략(추정 금지). 가드 `python -m pytest scripts/tests/test_investor_flows.py` |
| `scripts/discord_card.py` | 카드 PNG 렌더러(matplotlib) — 디스코드(가로 10×7)와 카카오(정사각 1080², `shape="square"`) 공용. **도안 3형**(기획 v3): 사건형 `stock_alert`·`swing`(타일 + 인트라데이 임계선) / 상태형 `status`(상태 배지 + 타임라인 — 해제·테스트처럼 차트가 의미 없는 통지) / 지표형 `board`·`weekly`·`close_report`. 공통 골격 = `_sq_fig`(제목) + `_draw_cells`(타일; `_draw_tiles` 는 편성표 키를 셀로 바꿔 같은 함수를 쓴다) + `_sq_panel`(선 그래프) + `_footer`. **정사각 글자는 `SQ_MIN_FS`(11.5pt = 단변 2.2%) 하한** — 말풍선이 카드를 400px 안팎으로 축소하기 때문(`_fs`). **카드 내부 텍스트에 이모지 금지**(CI·로컬 폰트에 글리프 없음 — 제목이 담당). 바탕 = 흰색, UP/DN(`#E0443E`/`#3E7BE0`)은 채움색 전용이고 작은 글자는 `UP_TXT`/`DN_TXT`. 카드 A(`board`)는 슬롯별 편성 `PROFILES` 6종, `profile_for(slot, weekend, now)`가 슬롯→편성을 정한다. 편성표는 `_CATALOG` 키만 참조하므로 `_ASSETS` 는 건드리지 말 것. 미리보기 `python scripts/discord_card.py all -o out/ [--square]`, 가드 `python scripts/tests/test_discord_card.py` + `python scripts/tests/test_kakao_cards.py` |
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
| `scripts/verify_pipeline_fix.py` + `run_verify_fix.cmd` + `register_verify_task.ps1` | Post-fix observation for the 2026-09-08 change (task `EconSite-FixVerify`: today 16:45 once, then daily 09:10). Measures `data.json` commit gaps against the *slot-time* threshold, counts `fetch-data` `workflow_dispatch` runs (the only proxy for ⚙️ warnings — Discord is not readable and actor cannot separate bot from human), counts off-hours `:35` top-ups, and reads the Toss task's exit codes; reports to Discord `#시스템`. Delete when the observation is done: `register_verify_task.ps1 -Remove` |
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
