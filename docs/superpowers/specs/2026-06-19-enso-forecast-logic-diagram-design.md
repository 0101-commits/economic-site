# Spec — ENSO forecast viewer + logic diagram

- **Date:** 2026-06-19
- **Branch:** `feat/enso-forecast-logic-diagram` (off `feat/enso-climate-live-data`)
- **Ship:** feature branch → its own PR (after / alongside the ENSO-live-data PR)
- **Status:** design approved; pending spec review

## 1. Goal

Extend the 엘니뇨·라니냐 card with (A) a viewer for the US/EU/JP agencies' ENSO
**forecasts** (charts + links), and (B) a **logic diagram** ("도식화") that shows how a
forecast/observation flows through the classification into the asset-impact analysis,
with the current state highlighted from live data.

## 2. Background / dependency

- Builds directly on the ENSO-live-data feature (branch `feat/enso-climate-live-data`,
  PR pending). That feature added `data.json.climate.enso` (phase/strength/trend + ONI /
  Niño3.4) and the frontend `ensoData()`, `ensoPhaseLabel/StrengthLabel/TrendLabel`,
  `ensoLiveSentence`, and `renderEnsoCard()`. This feature reuses all of them.
- Therefore this branch is cut **from** `feat/enso-climate-live-data`, not `main`.

## 3. Scope

**In scope (this PR) — `index.html` only:**
- Part A: forecast viewer (embed 2 verified NOAA charts + links to IRI/ECMWF/JMA), in a
  collapsible panel inside the ENSO card, lazy-rendered, with per-image link-fallback.
- Part B: a live-highlighted logic flow diagram (HTML/CSS, no external lib).

**Out of scope:**
- No pipeline / `data.json` / worker / workflow change. Part A embeds external images
  (allowed by CSP `img-src https:`); Part B uses the existing `climate.enso` block.
- **Parsing** agency forecast numbers (the user chose embed+link, not parse). Note for the
  record: NOAA CPC's probabilities page *does* expose a machine-readable HTML table, but
  the browser's `connect-src` CSP blocks fetching it; parsing would require a pipeline
  change — explicitly deferred.

## 4. Verified assets (2026-06-19, direct probe)

| Region | Asset | URL | Mode |
|---|---|---|---|
| US | CPC official ENSO probability chart | `https://www.cpc.ncep.noaa.gov/archives/enso/roni/images/{YEAR}/enso-probs-current.png` | **embed** (200, PNG) |
| US | CFSv2 Niño3.4 forecast plume | `https://www.cpc.ncep.noaa.gov/products/people/wwang/cfsv2fcst/imagesInd3/nino34Mon.gif` | **embed** (200, img) |
| US | IRI ENSO forecast page | `https://iri.columbia.edu/our-expertise/climate/forecasts/enso/current/` | link |
| EU | ECMWF SEAS5 Niño plumes | `https://charts.ecmwf.int/products/seasonal_system5_standard_nino_plumes` | link |
| JP | JMA El Niño outlook | `https://ds.data.jma.go.jp/tcc/tcc/products/elnino/outlook.html` | link |

- The CPC probability URL embeds a **year** in the path. The frontend builds `{YEAR}` from
  `new Date().getFullYear()` so it auto-rolls; if a new year's file is not yet posted, the
  `onerror` fallback renders the link instead.
- IRI/ECMWF/JMA are link-only: IRI stopped publishing forecast data and its figure URLs
  moved to a CMS (not discoverable this session — WebFetch is org-spend-limited); ECMWF
  charts are a dynamic catalogue (not reliably hotlinkable); JMA's outlook is an HTML page.

## 5. Part A — Forecast viewer

- **Placement:** a collapsible panel in the ENSO card titled e.g. "🌐 기상청 예측 (미·유럽·일)",
  collapsed by default; expands on click.
- **Render fn:** `renderEnsoForecasts()` builds the panel; called from `renderEnsoCard()`.
  Charts/images are injected **only on first expand** (lazy) to avoid loading ~150KB+ on
  initial card paint (load-speed).
- **Embeds:** `<img loading="lazy" alt referrerpolicy="no-referrer"
  onerror="…replace with link…">`. The CPC year is interpolated from
  `new Date().getFullYear()`.
- **Link cards:** labeled anchors (`target="_blank" rel="noopener noreferrer"`) for
  IRI / ECMWF / JMA and the two NOAA source pages.
- **Labeling:** each item tagged "예측 (forecast)" and visually distinct from the live
  observation banner; the existing "투자 참고용 / 실시간 예보 아님" disclaimer stays.

## 6. Part B — Logic diagram (도식화)

- **Render fn:** `renderEnsoLogicDiagram()` builds an HTML/CSS flow (no external lib; CSP
  forbids CDN/eval). Theme-aware via existing CSS vars / `getThemeColors()`.
- **Nodes / flow:**
  ```
  [관측: NOAA ONI · Niño3.4]┐
                            ├─→ [ONI ±0.5 분류] → [국면 + 강도 + 추세] → [① 원자재 수급·가격 변동성] → [② 국내 주가·산업]
  [예측: 기상청 확률]       ┘
  ```
- **Live highlight (the point of the feature):** read `ensoData()`:
  - classify node shows the live ONI value + the ±0.5 rule;
  - the active 국면 node (엘니뇨/중립/라니냐) is highlighted with its accent color, plus
    strength + trend labels;
  - the ① and ② nodes surface the current `ENSO_SCENARIOS[phase]` headline mappings
    (e.g. top commodity directions / sector effects), tying the diagram to the live state.
- **Connectors:** CSS borders/flex + small inline-SVG arrowheads (self-contained).
- **Responsive:** stacks vertically on narrow widths (the card is in a grid); horizontal
  flow on wide. Wrap in an `overflow-x:auto` container so it never forces page-horizontal
  scroll.

## 7. Componentization

- New: `renderEnsoForecasts()`, `renderEnsoLogicDiagram()`, plus a small `ensoForecastsExpanded`
  state flag and an `ensoForecastSources` config array (label, region, url, embed?).
- Reuse: `ensoData()`, `ensoPhaseLabel/StrengthLabel/TrendLabel`, `ENSO_SCENARIOS`,
  `getThemeColors()`.
- Integration: both are invoked from `renderEnsoCard()`. **Card body order** (unambiguous):
  1) existing live "실측" banner → 2) **logic diagram** (new) → 3) existing ①/② detail grid
  → 4) **forecast panel** (new, collapsible). The diagram introduces/visualizes the flow that
  the ①/② grid then details; the forecast panel sits last (heaviest, lazy). The forecast
  panel renders its header always and its body on expand.

## 8. Constraints

- **CSP:** `img-src 'self' data: blob: https:` → external chart **images** allowed.
  `connect-src` does NOT include agency hosts → no browser fetch/XHR to them (images only).
  No CDN, no `eval` (inline vanilla JS).
- **Never fabricate:** the diagram's live-highlight degrades when `climate.enso` is absent
  (see §9) — it must not invent a phase. Forecast charts show the agencies' own images, not
  derived numbers.
- Keep the existing investment-reference disclaimer.

## 9. Degradation

- **Image fails / hotlink blocked / year not yet posted:** `onerror` swaps the `<img>` for
  its labeled source link. No broken-image icon.
- **No `climate.enso` (feature loaded before data, or ENSO PR not yet merged in this env):**
  the logic diagram renders in a neutral, **unhighlighted** state (structure visible, no
  phase lit, classify node shows "관측 대기"); the forecast panel still works (it's
  independent of live data). Never blank, never a fabricated phase.

## 10. Verification

- `node --check` on all inline `<script>` blocks after the edit (catch template breakage).
- `node` run of any pure helper (e.g. a URL-builder for the CPC year).
- Re-confirm the 2 embed URLs return 200 image (direct probe).
- Browser (headless limit — flag for human): panel expand/lazy-load, image `onerror`→link,
  diagram highlight across phases (inject `climate.enso` with elnino/lanina/neutral), and the
  no-data neutral state. No automated DOM test (static site, plan-accepted).

## 11. Files touched

- `index.html` only. No `scripts/`, no `data.json`, no `cloudflare-worker`, no workflows.

## 12. Risks / open items

- **External image hotlink stability:** NOAA URLs verified today; the `onerror`→link
  fallback bounds the blast radius if they change. The year-pathed CPC URL is the most
  likely to rotate — handled by dynamic year + fallback.
- **WebFetch/WebSearch unavailable this session** (org spend limit) — does not block this
  frontend build (direct Bash URL probing works); only limits discovering more EU/JP image
  URLs, which stay as links anyway.

## 13. Commit / deploy

- Conventional Commits; trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Ships via its own PR; deploy on merge (GitHub Pages). Depends on / stacks atop the ENSO
  PR — merge order: ENSO first, then this (or this PR targets the ENSO branch).
