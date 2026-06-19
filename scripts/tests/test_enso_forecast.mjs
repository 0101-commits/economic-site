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
