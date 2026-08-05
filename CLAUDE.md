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
| `cloudflare-worker/worker.js` | CORS proxy + rate limiting + KakaoTalk cron dispatch |
| `data.json` | Market data artifact — committed by bot, never edit by hand |
| `data_meta.json` | Lightweight `lastUpdated` mirror of `data.json` |
| `alerts_config.json` | Stock alert rules (committed by bot via Worker `/portfolio`) |

## GitHub Actions Workflows

| Workflow | Schedule | Secret dependencies |
|----------|----------|---------------------|
| `fetch-data.yml` | Every 10 min (market hours), hourly (off-hours), daily KST 09/16/22 | `KRX_ID`, `KRX_PW`, `FRED_API_KEY`, `ECOS_API_KEY`, `REALESTATE_API_KEY`, `KOSIS_API_KEY`, `ALPHAVANTAGE_API_KEY`, `DATA_GO_KR_API_KEY`, `KIS_APP_KEY`/`KIS_APP_SECRET` (optional), `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET` (optional), `GEMINI_API_KEY`/`OPENAI_API_KEY` (for AI briefing) |
| `kakao-daily.yml` | Weekdays 07–22 KST hourly, weekends 11 & 17 KST (Sunday 17h = weekly report mode) | `KAKAO_REST_API_KEY`, `KAKAO_REFRESH_TOKEN` |
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
