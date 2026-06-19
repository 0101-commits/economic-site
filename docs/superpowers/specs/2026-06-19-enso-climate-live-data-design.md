# Spec — Live ENSO (엘니뇨·라니냐) climate data for the impact dashboard

- **Date:** 2026-06-19
- **Branch:** `feat/enso-climate-live-data`
- **Ship:** feature branch → PR (no direct push to `main`)
- **Status:** design approved; pending spec review

## 1. Goal

Upgrade the existing static "엘니뇨·라니냐 기후 영향 분석" card from a hand-curated
scenario-comparison tool into a **data-driven** one: the current ENSO phase, index
values, and headline sentence are derived from live NOAA observations (plus best-effort
JMA), while the existing scenario "typical pattern" library and its investment-reference
disclaimer are retained.

## 2. Current state (as found)

- The dashboard is a single static `index.html`. The ENSO card is **fully hardcoded**:
  - HTML: `index.html` ~line 2128 (title, disclaimer, source links).
  - JS: `const ENSO_SCENARIOS = {...}` at `index.html` 8261–8434 — hardcoded
    엘니뇨 / 라니냐 / 중립 scenarios; the user clicks a tab to compare them.
- **No `data.json` backing** for climate (verified: no enso/nino/oni/climate key exists).
- **No NOAA fetcher** exists in `scripts/`.
- **Premises in the request that were already true / already done:**
  - Source links (NOAA CPC ONI, 기상청 엘니뇨·라니냐) are **already live `<a>` hyperlinks**
    at `index.html` 2139–2140 — not dead text.
  - An explicit disclaimer already exists (line 2138): the card is "과거 ENSO 사이클의
    전형적 패턴이며 실시간 예보가 아닙니다 … 투자 참고용." We **keep and adapt** this; we do
    not delete it.
- `cloudflare-worker` does **not** need changes — the frontend reads `data.json`
  same-origin; climate data rides the existing pipeline.

## 3. Scope

**In scope (this PR):**
- NOAA-driven live ENSO data in the pipeline → `data.json.climate.enso`.
- Best-effort JMA NINO.3 scrape with graceful degradation.
- Frontend binding: auto-select current phase, dynamic headline sentence, live "현재 강도"
  supplementary badge on the ①원자재 / ②주가 sections.
- Graceful degradation for missing/stale/failed sources.
- Source-link completeness + minor font/visibility + lazy-init of the card.

**Out of scope (honest limits):**
- **ECMWF numeric integration** — the chart catalogue exposes no machine-readable Niño 3.4
  value (image charts behind JS; guessed data URL returned 404). ECMWF stays a **reference
  link**, not a scrape.
- "Real-time" means **monthly (ONI) / weekly (SST)** cadence — not live ticks.
- The parked YoY feature (`docs/superpowers/specs/` future) is unrelated and not in this PR.

## 4. Data sources (verified 2026-06-19 against live files)

| Role | Endpoint | Format | Verified latest | Cadence |
|---|---|---|---|---|
| **ONI** (official ±0.5 classifier) | `cpc.ncep.noaa.gov/data/indices/oni.ascii.txt` | `SEAS YR TOTAL ANOM` | `MAM 2026 +0.48` | monthly |
| Monthly Niño3.4 | `…/ersst5.nino.mth.91-20.ascii` | `YR MON … NINO3.4 ANOM` | `2026 5 +0.82` | monthly |
| Weekly Niño3.4 | `…/wksst9120.for` | fixed-width `Week … Nino34 SST SSTA` | `10JUN2026 +1.5` | weekly |
| JMA NINO.3 | TCC El Niño monitoring download | HTML/table | (confirm URL in impl) | monthly |
| ECMWF | chart catalogue | image only | — | link only |

**Stale-endpoint traps avoided (verified):** `detrend.nino34.ascii.txt` is frozen at
2019-07; `wksst8110.for` is frozen ~2021 (NOAA moved to the 1991–2020 base period
`wksst9120.for`). Using either would have published years-old numbers labeled "2026 최신
관측." **Do not use them.**

**Parsing notes:**
- `oni.ascii.txt`: whitespace-split; take last data row → `season`, `year`, `anom`.
- `wksst9120.for`: **fixed-width**, not naive split — negative SSTA glues to SST
  (`26.6-0.2`) while positive has a space (`28.8 1.0`). Parse by column position.
- `ersst5.nino.mth.91-20.ascii`: whitespace-split; NINO3.4 anomaly is the last column.

## 5. Data layer

### 5.1 `scripts/fetch_climate.py` (new, isolated module)
- Exposes `fetch_enso() -> dict | None`. Each source wrapped in its own try/except;
  one source failing never blanks the others (mirrors CLAUDE.md "preserve previous values
  on partial failure").
- Returns the `climate.enso` block (schema below) or `None` on total failure (caller keeps
  prior block).

### 5.2 Integration with `scripts/fetch_data.py`
- Called from `build_data()` (or the daily-run path) and merged under a new top-level
  `climate` key. **Gated to daily runs** (KST 09/16/22), not the every-10-min runs — same
  restraint the project applies to Alpha Vantage; NOAA files are small but there's no value
  in sub-daily polling of monthly/weekly indices.
- **Preserve-on-failure:** if `fetch_enso()` returns `None`, retain the previous
  `data.json.climate` block and set a top-level stale flag.

### 5.3 `data.json.climate` schema
```jsonc
"climate": {
  "enso": {
    "oni":            { "value": 0.48, "season": "MAM", "year": 2026, "asOf": "MAM 2026" },  // season label — ONI is a 3-month running mean, so the season (not a single month) is the correct period
    "nino34_monthly": { "value": 0.82, "year": 2026, "mon": 5 },
    "nino34_weekly":  { "value": 1.5,  "weekEnding": "2026-06-10" },
    "jma_nino3":      { "value": 0.9,  "asOf": "2026-05" } | null,  // null if scrape fails
    "phase":    "neutral",          // "elnino" | "lanina" | "neutral"
    "strength": "neutral",          // weak | moderate | strong | very_strong | neutral
    "trend":    "warming",          // warming | cooling | steady
    "stale":    { "oni": false, "nino34_weekly": false, "jma_nino3": true },
    "sources":  { "oni": "<url>", "nino34_weekly": "<url>", ... },
    "lastUpdated": "2026-06-19T00:00:00+09:00"
  }
}
```

### 5.4 `scripts/validate_data.py`
- **No change required to pass the gate** — `REQUIRED` is a whitelist of must-exist keys;
  unknown extra keys (`climate`) are ignored.
- **Optional:** add a non-blocking `::warning::` staleness check for `climate.enso`
  (e.g. ONI older than ~45 days), matching the existing WARN pattern. Does not block deploy.

## 6. Phase derivation

- **Phase** from latest **ONI** vs the ±0.5°C rule (the official NOAA threshold the request
  cites): `≥ +0.5 → elnino`, `≤ −0.5 → lanina`, else `neutral`.
- **Strength bands** (abs ONI): 0.5–0.9 weak, 1.0–1.4 moderate, 1.5–1.9 strong, ≥2.0 very
  strong; mirror for La Niña; `< 0.5 → neutral`.
- **Trend** from the most recent weekly Niño3.4 change (rising/falling/flat).
- **Honesty:** the formal NOAA El Niño *declaration* requires ONI ≥ +0.5 across 5
  consecutive overlapping seasons. The UI labels its readout "현재 ONI 기준" so a
  single-season value is not overstated as an official declaration. With current data
  (ONI +0.48 neutral, weekly +1.5 warming) the headline honestly reads "중립이나 엘니뇨 쪽으로
  따뜻해지는 추세."

## 7. Frontend (`index.html`)

- **Phase auto-select:** on load read `climate.enso.phase`; activate that tab in the
  existing `ENSO_SCENARIOS` UI. The user can still click other tabs to compare — the
  hardcoded scenarios remain as the "typical pattern" library.
- **Dynamic headline:** replace the hardcoded summary string with a sentence generated from
  live values, e.g. "현재 {YYYY}년 {M}월 관측 기준 ONI는 {oni}℃({phaseLabel}), 최근 주간 Niño 3.4
  는 {weekly}℃로 {trendLabel}." followed by `ENSO_SCENARIOS[phase].summary`.
- **Supplementary badge:** ①원자재 / ②주가 sections get a live "현재 강도: {strength}" badge
  layered onto the existing scenario tables — **informational**, disclaimer retained. No
  new hard "buy/sell" advice beyond the existing scenario effect tags.
- **Graceful degradation (core):** if `data.json.climate` is absent/stale/partial → render
  last-known values with a "갱신 지연" flag, or fall back to the current manual scenario tool.
  **Never blank, never fabricate a number.**
- **Links + polish:** keep existing source links; add NOAA-weekly + JMA links and verify
  each resolves; minor font-visibility tweak; lazy-init the card's chart/render on first
  view (req 3.2 load speed). No new CDN (Tailwind ban / CSP), no `eval`.

## 8. Constraints (from CLAUDE.md)

- `data.json` is **bot-owned** — written only via the pipeline, never hand-edited.
- **CSP:** no Tailwind CDN re-add, no `eval`, pure inline JS.
- API restraint: daily-cadence climate fetch only.

## 9. Verification plan

1. **NOAA parsers — local, against real files** (network confirmed): assert parsed values
   equal ONI +0.48 (MAM 2026), monthly +0.82 (2026-05), weekly +1.5 (2026-06-10).
2. **JMA scrape — local**; if flaky, confirm graceful-degrade path (stale flag, no crash).
3. **`fetch_climate.py` failure modes** — simulate each source raising; assert other sources
   survive and `None`/preserve path works.
4. **Frontend — served locally** (`python -m http.server`): inject a sample `climate` block
   and verify phase auto-select, dynamic sentence, badges, and **every** degrade path
   (missing key, stale flag, partial data).
5. **Gate:** run `python scripts/validate_data.py` on an augmented `data.json` → still passes.

## 10. Files touched

- `scripts/fetch_climate.py` (new)
- `scripts/fetch_data.py` (call + merge `climate`)
- `scripts/validate_data.py` (optional non-blocking WARN)
- `index.html` (binding, dynamic text, badges, degradation, links, polish)
- **Not** `data.json` (bot-owned), **not** `cloudflare-worker`.

## 11. Risks & open items

- **JMA scrape fragility** (accepted): page-structure changes break it → mitigated by
  graceful-degrade + stale flag; never blocks the NOAA-driven core.
- **JMA exact download URL** — to confirm during implementation (TCC monitoring page is a
  nav hub). If no clean file is found, JMA degrades to link-only like ECMWF.
- **Pipeline can't run end-to-end locally** (Actions/secrets) — but the climate fetch is
  fully exercisable locally over the public NOAA files, so the risky parsing logic is
  verifiable before merge. The PR is reviewed before it can deploy.

## 12. Commit / deploy

- Commit message (on merge of the PR): `feat: 미·유럽·일 기상청 실시간 데이터 연동 및 기후 영향
  분석 동적 자산 매칭 기능 추가`
- Deploy is triggered by **merging the PR to `main`** (GitHub Pages), not by a direct push.
