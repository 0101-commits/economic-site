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
const fn = new Function(...Object.keys(scope), block + '\n;return {cpcProbUrl, ensoDiagramState, ensoForecastSources, ensoLogicDiagramHTML, ensoForecastsHTML};');
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
