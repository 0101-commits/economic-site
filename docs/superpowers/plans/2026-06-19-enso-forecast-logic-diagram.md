# ENSO Forecast Viewer + Logic Diagram — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the ENSO card with a forecast viewer (embed 2 verified NOAA charts + IRI/ECMWF/JMA links) and a live-highlighted logic flow diagram, frontend-only.

**Architecture:** Pure string-builder functions (`ensoDiagramState`, `cpcProbUrl`, `ensoLogicDiagramHTML`, `ensoForecastsHTML`) reusing the existing `climate.enso` view (`ensoData()`) + `ENSO_SCENARIOS` + label helpers. `renderEnsoCard()` concatenates the diagram (after the live banner) and the forecast panel (after the ①/② grid) into `bodyEl.innerHTML`. No pipeline / data.json / worker change.

**Tech Stack:** Vanilla inline JS + CSS in `index.html` (Chart.js already present, not needed here). Node only for local unit-testing the pure builders. No new dependency, no CDN.

## Global Constraints

- **`index.html` only.** No `scripts/`, no `data.json`, no `cloudflare-worker`, no workflows.
- **CSP (verified, index.html:14–24):** `img-src 'self' data: blob: https:` → external chart **images** allowed. `script-src 'self' 'unsafe-inline' …` → inline `onerror`/`onclick` handlers allowed. `connect-src` excludes agency hosts → **no** browser fetch/XHR to them (images only). No CDN, no `eval`.
- **Never fabricate:** when `climate.enso` is absent, the diagram renders an **unhighlighted "관측 대기"** state — never an invented phase. Forecast panel shows the agencies' own images, never derived numbers.
- **Embed fallback:** every `<img>` has an inline `onerror` that hides the image and reveals an always-present (display:none) source link. No broken-image icon.
- **CPC probability URL year is dynamic:** built from `new Date().getFullYear()`, never hardcoded.
- **Reuse, don't duplicate:** `ensoData()`, `ensoPhaseLabel`/`ensoStrengthLabel`/`ensoTrendLabel`, `ENSO_SCENARIOS`. Keep the existing investment-reference disclaimer.
- **Verified embed URLs (2026-06-19, 200 + image):** CPC probability `https://www.cpc.ncep.noaa.gov/archives/enso/roni/images/{YEAR}/enso-probs-current.png`; CFSv2 plume `https://www.cpc.ncep.noaa.gov/products/people/wwang/cfsv2fcst/imagesInd3/nino34Mon.gif`.
- **No JS unit harness** (static site) — pure builders are node-tested; DOM/visual is browser-verified (plan-accepted).
- **Commits:** Conventional Commits + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Branch:** `feat/enso-forecast-logic-diagram` (off `feat/enso-climate-live-data`). Ship via its own PR.

---

### Task 1: Pure core — `cpcProbUrl`, `ensoDiagramState`, `ensoForecastSources`

**Files:**
- Modify: `index.html` (insert a new block immediately ABOVE `function renderEnsoCard()` — currently line 8364; locate it by the string `function renderEnsoCard() {`)
- Test: `scripts/tests/test_enso_forecast.mjs` (new — node test for the pure builders)

**Interfaces:**
- Consumes: existing globals `ENSO_SCENARIOS`, `ensoPhaseLabel`, `ensoStrengthLabel`, `ensoTrendLabel`.
- Produces: `cpcProbUrl(year) -> string`; `ensoDiagramState(enso) -> {hasData, oniText, asOf, phaseKey, phaseLabel, strengthLabel, trendLabel, topCommodities[], topSectors[]}`; const `ensoForecastSources` (array of `{region,label,page,embed?}`).

- [ ] **Step 1: Write the failing test**

```javascript
// scripts/tests/test_enso_forecast.mjs — run with: node scripts/tests/test_enso_forecast.mjs
import assert from 'node:assert';
import fs from 'node:fs';

// Extract the ENSO forecast/diagram block from index.html and eval it in a stubbed scope.
const html = fs.readFileSync(new URL('../../index.html', import.meta.url), 'utf8');
function slice(marker, endMarker) {
  const i = html.indexOf(marker); const j = html.indexOf(endMarker, i);
  if (i < 0 || j < 0) throw new Error('markers not found: ' + marker);
  return html.slice(i, j);
}
// The new block is delimited by these comment markers (added in implementation).
const block = slice('/* ===== ENSO forecast+diagram (start) ===== */',
                    '/* ===== ENSO forecast+diagram (end) ===== */');
// Minimal stubs for what the block consumes:
const ENSO_SCENARIOS = {
  elnino:  { commodities:[{name:'설탕'},{name:'커피'},{name:'코코아'},{name:'팜유'}], sectors:[{sector:'음식료'},{sector:'가스'},{sector:'비료'}] },
  lanina:  { commodities:[{name:'대두'},{name:'원유'}], sectors:[{sector:'정유'}] },
  neutral: { commodities:[{name:'원유'}], sectors:[{sector:'시장 전반'}] },
};
const ensoPhaseLabel    = p => ({elnino:'엘니뇨',lanina:'라니냐',neutral:'중립'})[p] || '중립';
const ensoStrengthLabel = s => ({weak:'약한',moderate:'중간',strong:'강한',very_strong:'매우 강한',neutral:''})[s] || '';
const ensoTrendLabel    = t => ({warming:'따뜻해지는 추세',cooling:'차가워지는 추세',steady:'안정적'})[t] || '';
const scope = { ENSO_SCENARIOS, ensoPhaseLabel, ensoStrengthLabel, ensoTrendLabel, Date };
const fn = new Function(...Object.keys(scope), block + '\n;return {cpcProbUrl, ensoDiagramState, ensoForecastSources};');
const M = fn(...Object.values(scope));

// cpcProbUrl
assert.strictEqual(M.cpcProbUrl(2026),
  'https://www.cpc.ncep.noaa.gov/archives/enso/roni/images/2026/enso-probs-current.png');

// ensoDiagramState — live
const live = M.ensoDiagramState({oni:{value:0.48, asOf:'MAM 2026'}, phase:'neutral', strength:'neutral', trend:'warming'});
assert.strictEqual(live.hasData, true);
assert.strictEqual(live.oniText, '+0.48℃');
assert.strictEqual(live.phaseLabel, '중립');
assert.strictEqual(live.trendLabel, '따뜻해지는 추세');
assert.ok(live.topCommodities.length <= 3);

// ensoDiagramState — no data (never fabricate)
const none = M.ensoDiagramState(null);
assert.strictEqual(none.hasData, false);
assert.strictEqual(none.phaseKey, null);

// sources config covers all three regions
const regions = M.ensoForecastSources.map(s => s.region).join(' ');
assert.ok(/미국/.test(regions) && /유럽/.test(regions) && /일본/.test(regions));
console.log('Task1 OK');
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node scripts/tests/test_enso_forecast.mjs`
Expected: FAIL — `Error: markers not found` (the block doesn't exist yet).

- [ ] **Step 3: Write minimal implementation**

Insert immediately above `function renderEnsoCard() {` (locate that string; currently line 8364) in `index.html`:

```javascript
/* ===== ENSO forecast+diagram (start) ===== */
// 🌐 기상청 예측 뷰어 + 분석 로직 도식화 — climate.enso(실측) + 기관 예측 차트(이미지) 를
// 카드에 결합. 데이터 없으면 도식은 '관측 대기'(국면 미점등), 이미지는 onerror→링크 폴백.
function cpcProbUrl(year) {
  return `https://www.cpc.ncep.noaa.gov/archives/enso/roni/images/${year}/enso-probs-current.png`;
}
// 도식 표시용 순수 뷰모델 — enso 가 없거나 oni 값이 없으면 hasData:false (국면 날조 금지).
function ensoDiagramState(enso) {
  if (!enso || !enso.oni || typeof enso.oni.value !== 'number') {
    return { hasData:false, oniText:'관측 대기', asOf:'', phaseKey:null,
             phaseLabel:'—', strengthLabel:'', trendLabel:'', topCommodities:[], topSectors:[] };
  }
  const ph = enso.phase || 'neutral';
  const sc = ENSO_SCENARIOS[ph] || {};
  const v = enso.oni.value;
  return {
    hasData:true,
    oniText: (v >= 0 ? '+' : '') + v.toFixed(2) + '℃',
    asOf: enso.oni.asOf || '',
    phaseKey: ph,
    phaseLabel: ensoPhaseLabel(ph),
    strengthLabel: ensoStrengthLabel(enso.strength),
    trendLabel: ensoTrendLabel(enso.trend),
    topCommodities: (sc.commodities || []).slice(0,3).map(c => c.name),
    topSectors: (sc.sectors || []).slice(0,2).map(s => s.sector),
  };
}
// 기관 예측 소스 — embed:있으면 이미지 임베드(검증된 NOAA 2건), 없으면 링크 카드.
const ensoForecastSources = [
  { region:'🇺🇸 미국', label:'NOAA CPC ENSO 확률', embed:'cpcProb',
    page:'https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/probabilities/' },
  { region:'🇺🇸 미국', label:'NOAA CFSv2 Niño3.4 예측',
    embed:'https://www.cpc.ncep.noaa.gov/products/people/wwang/cfsv2fcst/imagesInd3/nino34Mon.gif',
    page:'https://www.cpc.ncep.noaa.gov/products/people/wwang/cfsv2fcst/' },
  { region:'🇺🇸 미국', label:'IRI ENSO 예측',
    page:'https://iri.columbia.edu/our-expertise/climate/forecasts/enso/current/' },
  { region:'🇪🇺 유럽', label:'ECMWF SEAS5 Niño plume',
    page:'https://charts.ecmwf.int/products/seasonal_system5_standard_nino_plumes' },
  { region:'🇯🇵 일본', label:'JMA 엘니뇨 전망',
    page:'https://ds.data.jma.go.jp/tcc/tcc/products/elnino/outlook.html' },
];
/* ===== ENSO forecast+diagram (end) ===== */
```

> Note: the closing `(end)` marker must stay at the very end of the block after ALL functions this feature adds — Tasks 2 and 3 insert their functions BEFORE the `(end)` marker line.

- [ ] **Step 4: Run test to verify it passes**

Run: `node scripts/tests/test_enso_forecast.mjs`
Expected: `Task1 OK`

- [ ] **Step 5: Commit**

```bash
git add index.html scripts/tests/test_enso_forecast.mjs
git commit -m "feat: add ENSO forecast sources + diagram view-model

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `ensoLogicDiagramHTML(enso)` — the logic flow

**Files:**
- Modify: `index.html` (insert this function just BEFORE the `/* ===== ENSO forecast+diagram (end) ===== */` marker)
- Test: `scripts/tests/test_enso_forecast.mjs` (extend)

**Interfaces:**
- Consumes: `ensoDiagramState` (Task 1).
- Produces: `ensoLogicDiagramHTML(enso) -> string` (an HTML fragment; horizontal flow with `overflow-x:auto`, theme-aware via CSS vars, active phase node highlighted only when `hasData`).

- [ ] **Step 1: Write the failing test** (append before the final `console.log`)

```javascript
// --- Task 2: logic diagram ---
const M2 = fn(...Object.values(scope));  // re-eval after impl includes ensoLogicDiagramHTML
const dHtml = M2.ensoLogicDiagramHTML({oni:{value:-1.1,asOf:'MAM 2026'}, phase:'lanina', strength:'moderate', trend:'cooling'});
assert.ok(dHtml.includes('라니냐'), 'diagram shows live phase label');
assert.ok(dHtml.includes('-1.10℃'), 'diagram shows live ONI');
assert.ok(dHtml.includes('overflow-x:auto'), 'diagram horizontally scrollable, never forces page hscroll');
assert.ok(dHtml.includes('var(--c-accent)'), 'active phase node highlighted when hasData');
const dNone = M2.ensoLogicDiagramHTML(null);
assert.ok(dNone.includes('관측 대기'), 'no-data diagram shows 관측 대기, not a fabricated phase');
assert.ok(!dNone.includes('엘니뇨') && !dNone.includes('라니냐'), 'no-data diagram does not assert a phase');
console.log('Task2 OK');
```
Also update the return list: change the `return {cpcProbUrl, ensoDiagramState, ensoForecastSources};` in the `new Function(...)` to `return {cpcProbUrl, ensoDiagramState, ensoForecastSources, ensoLogicDiagramHTML};`.

- [ ] **Step 2: Run test to verify it fails**

Run: `node scripts/tests/test_enso_forecast.mjs`
Expected: FAIL — `ensoLogicDiagramHTML is not defined` (or assertion fails).

- [ ] **Step 3: Write minimal implementation** (insert before the `(end)` marker)

```javascript
function ensoLogicDiagramHTML(enso) {
  const st = ensoDiagramState(enso);
  const node = 'flex:1;min-width:118px;background:var(--c-bg);border:1px solid var(--c-border);border-radius:var(--r-sm);padding:8px 10px;';
  const hi = st.hasData ? 'border-color:var(--c-accent);background:var(--c-card);' : '';
  const arrow = '<div style="align-self:center;color:var(--c-txt-muted);font-size:15px;padding:0 1px;">→</div>';
  const t = 'font-size:11px;font-weight:700;color:var(--c-txt);';
  const d = 'font-size:10px;color:var(--c-txt-dim);line-height:1.45;margin-top:2px;';
  const phaseDetail = st.hasData
    ? `${st.phaseLabel}${st.strengthLabel ? ' · ' + st.strengthLabel : ''}${st.trendLabel ? ' · ' + st.trendLabel : ''}`
    : '—';
  return `
    <div style="margin-bottom:12px;">
      <div style="font-size:11px;font-weight:700;color:var(--c-primary);letter-spacing:.04em;margin-bottom:6px;">
        🔗 분석 로직 흐름 ${st.hasData ? '<span style="color:var(--c-txt-muted);font-weight:600;">(실측 반영)</span>' : '<span style="color:var(--c-txt-muted);font-weight:600;">(관측 대기)</span>'}
      </div>
      <div style="overflow-x:auto;"><div style="display:flex;gap:4px;align-items:stretch;min-width:660px;">
        <div style="${node}"><div style="${t}">입력</div><div style="${d}">관측 ONI·Niño3.4<br>예측 기상청 확률</div></div>
        ${arrow}
        <div style="${node}"><div style="${t}">ONI ±0.5℃ 분류</div><div style="${d}">${st.hasData ? `현재 ${st.oniText}${st.asOf ? ' (' + st.asOf + ')' : ''}` : '데이터 대기'}</div></div>
        ${arrow}
        <div style="${node}${hi}"><div style="${t}">국면</div><div style="${d}">${phaseDetail}</div></div>
        ${arrow}
        <div style="${node}"><div style="${t}">① 원자재 변동성</div><div style="${d}">${st.hasData && st.topCommodities.length ? st.topCommodities.join(', ') : '국면별 패턴'}</div></div>
        ${arrow}
        <div style="${node}"><div style="${t}">② 국내 주가·산업</div><div style="${d}">${st.hasData && st.topSectors.length ? st.topSectors.join(', ') : '국면별 영향'}</div></div>
      </div></div>
    </div>`;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node scripts/tests/test_enso_forecast.mjs`
Expected: `Task2 OK`

- [ ] **Step 5: Commit**

```bash
git add index.html scripts/tests/test_enso_forecast.mjs
git commit -m "feat: add ENSO logic flow diagram (live-highlighted)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `ensoForecastsHTML(expanded)` + `toggleEnsoForecasts()` + expand flag

**Files:**
- Modify: `index.html` (insert the flag + functions just BEFORE the `(end)` marker)
- Test: `scripts/tests/test_enso_forecast.mjs` (extend)

**Interfaces:**
- Consumes: `cpcProbUrl`, `ensoForecastSources` (Task 1).
- Produces: global `let ensoForecastsExpanded` (declared once, near the other ENSO state); `ensoForecastsHTML(expanded) -> string`; `toggleEnsoForecasts()` (flips the flag, calls `renderEnsoCard()`).

- [ ] **Step 1: Write the failing test** (append before the final `console.log`; update the `new Function` return to also expose `ensoForecastsHTML`)

```javascript
// --- Task 3: forecast panel ---
const M3 = fn(...Object.values(scope));
const collapsed = M3.ensoForecastsHTML(false);
assert.ok(collapsed.includes('기상청 예측'), 'panel header present when collapsed');
assert.ok(!collapsed.includes('<img'), 'no images rendered when collapsed (lazy)');
const open = M3.ensoForecastsHTML(true);
assert.ok(open.includes('cfsv2fcst/imagesInd3/nino34Mon.gif'), 'embeds verified CFSv2 plume');
assert.ok(open.includes('/archives/enso/roni/images/'), 'embeds CPC probability (year-built)');
assert.ok(open.includes('iri.columbia.edu') && open.includes('charts.ecmwf.int') && open.includes('jma.go.jp'), 'links IRI/ECMWF/JMA');
assert.ok(open.includes('onerror='), 'images have onerror fallback');
assert.ok(open.includes('rel="noopener noreferrer"'), 'external links are safe');
console.log('Task3 OK');
```
Update the `new Function(...)` return to: `return {cpcProbUrl, ensoDiagramState, ensoForecastSources, ensoLogicDiagramHTML, ensoForecastsHTML};`

- [ ] **Step 2: Run test to verify it fails**

Run: `node scripts/tests/test_enso_forecast.mjs`
Expected: FAIL — `ensoForecastsHTML is not defined`.

- [ ] **Step 3: Write minimal implementation** (insert before the `(end)` marker)

```javascript
let ensoForecastsExpanded = false;
function toggleEnsoForecasts() { ensoForecastsExpanded = !ensoForecastsExpanded; renderEnsoCard(); }
function ensoForecastsHTML(expanded) {
  const head = `
    <div onclick="toggleEnsoForecasts()" style="cursor:pointer;display:flex;align-items:center;gap:6px;margin-top:14px;padding-top:10px;border-top:1px solid var(--c-border);font-size:11px;font-weight:700;color:var(--c-primary);letter-spacing:.04em;">
      <span>🌐 기상청 예측 (미·유럽·일)</span>
      <span style="color:var(--c-txt-muted);font-weight:600;">예측(forecast)</span>
      <span style="margin-left:auto;color:var(--c-txt-muted);">${expanded ? '▲' : '▼'}</span>
    </div>`;
  if (!expanded) return head;
  const yr = new Date().getFullYear();
  const link = (s) => `<a href="${s.page}" target="_blank" rel="noopener noreferrer" style="color:var(--c-primary);">${s.label} ↗</a>`;
  const items = ensoForecastSources.map(s => {
    if (s.embed) {
      const url = s.embed === 'cpcProb' ? cpcProbUrl(yr) : s.embed;
      // onerror: hide the broken image and reveal the always-present fallback link sibling.
      return `
        <figure style="margin:0;">
          <figcaption style="font-size:11px;color:var(--c-txt-dim);margin-bottom:3px;">${s.region} · ${s.label}</figcaption>
          <img src="${url}" loading="lazy" referrerpolicy="no-referrer" alt="${s.label}"
               style="max-width:100%;border:1px solid var(--c-border);border-radius:var(--r-xs);"
               onerror="this.style.display='none';this.nextElementSibling.style.display='inline-block';">
          <a href="${s.page}" target="_blank" rel="noopener noreferrer" style="display:none;font-size:11px;color:var(--c-primary);">${s.label} ↗ (이미지 불러오기 실패 — 원본 보기)</a>
        </figure>`;
    }
    return `<div style="font-size:11px;color:var(--c-txt-dim);">${s.region} · ${link(s)}</div>`;
  }).join('');
  return head + `
    <div style="margin-top:8px;display:flex;flex-direction:column;gap:12px;">${items}</div>
    <div style="font-size:10px;color:var(--c-txt-muted);margin-top:8px;line-height:1.6;">
      ※ 각 기관의 공식 예측 차트/페이지. 예보는 갱신·정정될 수 있으며 투자 참고용입니다.
    </div>`;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node scripts/tests/test_enso_forecast.mjs`
Expected: `Task3 OK` (and Task1/Task2 lines still print).

> Note: the block now declares its own `let ensoForecastsExpanded`. The test scope does NOT pass it as a `new Function` parameter (Task 1's functions never referenced it), so there is no parameter-vs-`let` redeclaration conflict. `toggleEnsoForecasts` references `renderEnsoCard` (a global not in the test scope), but the test never calls `toggleEnsoForecasts`, so that function is defined-but-not-invoked and eval succeeds.

- [ ] **Step 5: Commit**

```bash
git add index.html scripts/tests/test_enso_forecast.mjs
git commit -m "feat: add ENSO agency-forecast panel (embed + link, lazy)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Integrate into `renderEnsoCard()` + full verification

**Files:**
- Modify: `index.html` (two concatenation edits inside `renderEnsoCard`, currently lines 8403 and 8421)

**Interfaces:**
- Consumes: `ensoLogicDiagramHTML` (Task 2), `ensoForecastsHTML` + `ensoForecastsExpanded` (Task 3), existing `_live`.

- [ ] **Step 1: Read the target** — read `index.html` around `bodyEl.innerHTML = _liveBanner` (currently 8403) and the template close `</div>\`;` (currently 8421) to confirm exact text before editing.

- [ ] **Step 2: Insert the diagram after the live banner**

Find (line ~8403):
```javascript
  bodyEl.innerHTML = _liveBanner + `
```
Replace with:
```javascript
  bodyEl.innerHTML = _liveBanner + ensoLogicDiagramHTML(_live) + `
```

- [ ] **Step 3: Append the forecast panel after the ①/② grid**

Find the template close (line ~8421):
```javascript
    </div>`;
```
Replace with:
```javascript
    </div>` + ensoForecastsHTML(ensoForecastsExpanded);
```

(This is the `</div>` that closes `<div class="grid-2">` at the very end of `renderEnsoCard`'s `bodyEl.innerHTML` assignment. If more than one `    </div>\`;` exists, match the one immediately following the `${secRows}` block / `grid-2` — it is the last line before the function's closing `}`.)

- [ ] **Step 4: JS syntax safety — `node --check` all inline scripts**

Run (from repo root):
```bash
python - <<'PY'
import re,os,subprocess,sys
html=open("index.html",encoding="utf-8").read()
blocks=re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>',html,re.DOTALL)
os.makedirs(".git/tmpjs",exist_ok=True); bad=0
for i,b in enumerate(blocks):
    p=f".git/tmpjs/b{i}.js"; open(p,"w",encoding="utf-8").write(b)
    r=subprocess.run(["node","--check",p],capture_output=True,text=True)
    if r.returncode!=0: bad+=1; print("FAIL",p,r.stderr[:200])
print("blocks",len(blocks),"bad",bad); sys.exit(1 if bad else 0)
PY
```
Expected: `blocks <N> bad 0` (exit 0). A non-zero `bad` means a template edit broke the inline script — fix before continuing.

- [ ] **Step 5: Re-run the unit tests + re-verify the 2 embed URLs are live**

```bash
node scripts/tests/test_enso_forecast.mjs
python -c "import urllib.request as u; [print(x, u.urlopen(u.Request(x,headers={'User-Agent':'Mozilla/5.0'}),timeout=20).status) for x in ['https://www.cpc.ncep.noaa.gov/products/people/wwang/cfsv2fcst/imagesInd3/nino34Mon.gif', 'https://www.cpc.ncep.noaa.gov/archives/enso/roni/images/%d/enso-probs-current.png' % __import__('datetime').date.today().year]]"
```
Expected: `Task1/2/3 OK`; both URLs print `200`. (If the CPC year URL ≠ 200 — e.g. early January before the new file is posted — that's the documented `onerror`→link case, not a blocker; note it.)

- [ ] **Step 6: Browser verification (record results; cannot be automated here)**

Serve: `python -m http.server 8000` → open `http://localhost:8000/` → market page → 원자재 (commodity) tab → ENSO card. Confirm:
1. Logic diagram renders between the live banner and the scenario block; the 국면 node is highlighted and shows the live ONI; on narrow widths it scrolls horizontally inside its box (page does not scroll sideways).
2. "🌐 기상청 예측" panel header shows at the card bottom; clicking it expands → the 2 NOAA charts load, IRI/ECMWF/JMA appear as links; collapsing hides them.
3. In console, `_latestDataForIndicators.climate = {enso:{phase:'elnino',strength:'strong',trend:'warming',oni:{value:1.6,asOf:'MAM 2026'}}}; ensoUserPinned=false; renderEnsoCard();` → diagram highlights 엘니뇨; `delete _latestDataForIndicators.climate; renderEnsoCard();` → diagram shows "관측 대기", no fabricated phase, no errors.
4. Force an image error (e.g. temporarily edit a src) → the fallback link appears, no broken-image icon.

- [ ] **Step 7: Commit**

```bash
git add index.html
git commit -m "feat: wire ENSO logic diagram + forecast panel into the card

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Push + PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/enso-forecast-logic-diagram
```

- [ ] **Step 2: Open the PR** (gh may be absent — if so, use the printed compare URL)

```bash
gh pr create --base feat/enso-climate-live-data --head feat/enso-forecast-logic-diagram \
  --title "feat: ENSO 기상청 예측 뷰어 + 분석 로직 도식화" \
  --body "Spec: docs/superpowers/specs/2026-06-19-enso-forecast-logic-diagram-design.md

Frontend-only. Embeds 2 verified NOAA forecast charts (CPC probability + CFSv2 plume; dynamic year, onerror→link), links IRI/ECMWF/JMA, and adds a live-highlighted logic flow diagram (obs/forecast → ±0.5 classify → phase → ①commodity/②equity). Reuses climate.enso. No pipeline/data.json change. Stacks on the ENSO PR.

🤖 Generated with [Claude Code](https://claude.com/claude-code)" || echo "gh absent — open: https://github.com/0101-commits/economic-site/compare/feat/enso-climate-live-data...feat/enso-forecast-logic-diagram?expand=1"
```

- [ ] **Step 3: Report** the PR (or compare) URL. Base = `feat/enso-climate-live-data` so this PR's diff shows ONLY this feature. Deploy on merge (after the ENSO PR merges).

---

## Self-Review

**Spec coverage:** Part A forecast viewer (embed 2 NOAA + link IRI/ECMWF/JMA, lazy, onerror→link, dynamic year) → Tasks 1,3,4 ✓. Part B logic diagram (live-highlight, no-data state, overflow-x) → Tasks 1,2,4 ✓. Card-body order (banner→diagram→grid→panel) → Task 4 Steps 2–3 ✓. CSP (img https / inline onerror / no fetch) → Global Constraints + Task 3 ✓. Never-fabricate (no-data unhighlighted) → Task 1 `ensoDiagramState(null)` + Task 2 test ✓. index.html-only → all tasks ✓. Disclaimer kept → Task 3 panel footer + existing card disclaimer untouched ✓.

**Placeholder scan:** No TBD/TODO. `{YEAR}`/`yr` is a real computed value (`new Date().getFullYear()`), not a placeholder. Integration uses exact find/replace strings with line anchors + a disambiguation note for the `</div>` match.

**Type consistency:** `ensoDiagramState` keys (`hasData,oniText,asOf,phaseKey,phaseLabel,strengthLabel,trendLabel,topCommodities,topSectors`) are produced in Task 1 and consumed in Task 2's `ensoLogicDiagramHTML`. `ensoForecastSources` item shape (`region,label,page,embed?`) produced in Task 1, consumed in Task 3. `ensoForecastsExpanded` declared once (Task 3) and read in Task 4. `cpcProbUrl(year)` signature consistent across Tasks 1/3. `toggleEnsoForecasts` calls `renderEnsoCard` (exists). Diagram inserted via `ensoLogicDiagramHTML(_live)` and panel via `ensoForecastsHTML(ensoForecastsExpanded)` — both names match their definitions.
