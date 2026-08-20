# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Korean economic dashboard: static single-page app (GitHub Pages) + GitHub Actions data pipeline + Cloudflare Worker CORS proxy.

Live site: `https://0101-commits.github.io/economic-site/`

## No Build Step

**No npm, no bundler, no compilation.** The site is a single `index.html` (~22 000 lines) with all CSS and JavaScript inline. Edit `index.html` directly. Changes to `index.html` are live on GitHub Pages immediately after push.

The one exception is the **design-token block**, which is generated — see *Design system* below.

## Design system — astryx (neutral)

The UI follows the astryx design system (`@astryxdesign/*`; local copy at
`C:\Users\cgpar\astryx`). Three rules carry most of it:

1. **Semantic tokens, never hardcoded values.** Colors come from `var(--color-*)`
   (or the legacy `var(--c-*)` alias layer). No hex literals in CSS or in
   `style=""` attributes.
2. **Color means data.** Surfaces, borders and text are pure grayscale. Hue is
   reserved for market direction (`--c-up`/`--c-down`), status
   (success/warning/error), and chart series (`--color-series-1…9`).
3. **Dense data renders as rows, not cards.** `.widget`/`.kpi-card` are widget
   containers; lists and tables are edge-to-edge rows with dividers and
   32–40 px row height. Don't wrap list items in cards.
4. **Never set `font-size` or `font-weight` by hand.** Use the geometric scale
   (`--font-size-xs` … `--font-size-5xl`, base 14 × ratio 1.2) or a semantic
   type style (`--text-body-*`, `--text-supporting-*`, `--text-heading-N-*`).
   Off-scale values (11, 13, 15, 18, 22 px) are what made the old UI drift by
   1–2 px between screens.
5. **Chart colors come from tokens, never literals.** Categorical series use
   `getThemeColors().series` (9 hues); the interactive blue is
   `getThemeColors().accent`. Market up/down (`window.CUP`/`CDN`) must not be
   mixed into a categorical palette — a slice colored red then reads as
   "down" rather than "category 6".

Token pipeline (the only generated artifact in the repo):

```
scripts/econ.theme.ts                        # source of truth — edit this
  → copy to C:\Users\cgpar\astryx\ (the CLI needs @astryxdesign deps installed there)
  → node node_modules/@astryxdesign/cli/bin/astryx.mjs theme build econ.theme.ts --out dist/econ.css
  → python scripts/build_astryx_tokens.py > scripts/_astryx_tokens.css
  → paste over the `astryx econ tokens` block in index.html
```

`scripts/econ.theme.ts` is vendored here so the theme is versioned with the site;
the build itself runs from the astryx workspace because that is where the
`@astryxdesign/*` packages live. Keep the two copies in sync.

`build_astryx_tokens.py` merges `theme-neutral` defaults with the `econ`
overrides and flattens `light-dark()` / `@scope` into plain
`:root {…}` + `html.light {…}` blocks, because the site has no build step and
must run on older mobile webviews.

The `astryx layer` section at the end of `<style>` holds frame/surface/row/
control rules and must stay last — it overrides the older legacy CSS above it.

`scripts/patch_astryx.py` and `scripts/patch_astryx_layer.py` are the one-shot
migration scripts that produced the current state; they are kept for provenance
and are **not** idempotent — do not re-run them.

## Key Files

| File | Role |
|------|------|
| `index.html` | Entire frontend — styles, charts (Chart.js), all page logic |
| `scripts/fetch_data.py` | ~7 000-line data collector; runs in GitHub Actions |
| `scripts/validate_data.py` | Data integrity gate — blocks bad `data.json` from commit |
| `scripts/ai_briefing.py` | LLM macro summary → `data.json.aiBriefing` |
| `scripts/send_kakao_digest.py` | KakaoTalk digest sender |
| `scripts/check_alerts.py` | Stock alert evaluator |
| `scripts/check_swings.py` | Market swing alert (코스피·S&P500 ±2%, 달러-원 ±1% 즉시 속보; cooldown = `alerts_state.json` `_swings` key) |
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
  change in `econ.theme.ts`, update `_UPDN` in the same commit.
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
- Charts use `matplotlib`; slot determines which two tickers to chart (see `kakao-daily.yml` header comments)

## Local Toss collector (this PC, not CI)

Toss Open API binds every client to an **IP allowlist** (WTS → 설정 → Open API → 허용 IP 관리).
There is no CIDR or wildcard entry, so CI can never be allowlisted. The collector runs here
instead and hands its result to the cloud pipeline through the repo.

| Piece | What it does |
|-------|--------------|
| `scripts/fetch_toss_snapshot.py` | Fetches indices, the KTB curve, gainer/loser rankings (stocks **and** ETFs, KOSPI+KOSDAQ), trading-amount + Toss-retail rankings, KOSPI investor flows, **per-stock flows for the tracked watchlist** (investor/short-selling/credit/lending/program/warnings — `stockData`), the KR market calendar and the USD/KRW quote; writes `toss_snapshot.json`; `--push` commits and pushes it |
| `scripts/run_toss_snapshot.cmd` | Task Scheduler entry point. **ASCII only** — cmd.exe parses batch files in the OEM code page, so UTF-8 Korean comments get executed as commands (seen as exit 9009) |
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
