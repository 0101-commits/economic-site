// scripts/tests/test_enso_forecast.mjs — run with: node scripts/tests/test_enso_forecast.mjs
import assert from 'node:assert';
import fs from 'node:fs';

// Extract the ENSO forecast/diagram block from js/app1.js (moved out of index.html by the js/ split) and eval it in a stubbed scope.
const html = fs.readFileSync(new URL('../../js/app1.js', import.meta.url), 'utf8');
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
const fn = new Function(...Object.keys(scope), block + '\n;return {cpcProbUrl, ensoForecastSources};');
const M = fn(...Object.values(scope));

// 2026-09-29 가독성 개편(8d46e21a)이 도식(ensoDiagramState·ensoLogicDiagramHTML)과 접이식 예측 패널
// (ensoForecastsHTML)을 지우고 결론 줄·숫자 칸·기관 링크 부품으로 바꿨다. 지키던 성질은 그대로 옮긴다:
// 실측 국면·ONI 표시 / 자료 없으면 국면을 지어내지 않음 / 외부 링크 안전 / 기관 3지역 / CPC·CFSv2 소스.
const card = slice('// ── 카드 본문(기획 2026-09-29 §5.1)', 'function ensoCompareHTML');
const cardScope = { ...scope, ensoCurrent: 'lanina', ensoForecastSources: M.ensoForecastSources };
const C = new Function(...Object.keys(cardScope), card +
  '\n;return {ensoLeadHTML, ensoKpisHTML, ensoAgencyLinksHTML};')(...Object.values(cardScope));
const S = { commodities: [{ name: '대두', dir: 'up', vol: '高', note: '' }, { name: '원유', dir: 'down', vol: '中', note: '' }],
            sectors: [], overallVol: '中' };

// sources / CPC
assert.strictEqual(M.cpcProbUrl(2026),
  'https://www.cpc.ncep.noaa.gov/archives/enso/roni/images/2026/enso-probs-current.png');
const regions = M.ensoForecastSources.map(s => s.region).join(' ');
assert.ok(/미국/.test(regions) && /유럽/.test(regions) && /일본/.test(regions), 'sources cover US/EU/JP');
assert.ok(M.ensoForecastSources.some(s => (s.embed || '').includes('cfsv2fcst/imagesInd3/nino34Mon.gif')), 'CFSv2 plume source kept');
console.log('sources OK');

// live — 실측 국면과 ONI 를 말한다
const live = { oni: { value: -1.1, asOf: 'MAM 2026' }, phase: 'lanina', strength: 'moderate', trend: 'cooling' };
const kLive = C.ensoKpisHTML(S, live);
assert.ok(kLive.includes('라니냐'), 'kpi shows live phase');
assert.ok(kLive.includes('-1.10'), 'kpi shows live ONI');
assert.ok(C.ensoLeadHTML(S, live).includes('라니냐</b>가 진행 중'), 'lead states the live phase');
console.log('live OK');

// no data — 국면을 지어내지 않는다
const lNone = C.ensoLeadHTML(S, null);
assert.ok(lNone.startsWith('<p class="econ-lead"><b>자료 없음</b>'), 'lead opens with 자료 없음');
const kNone = C.ensoKpisHTML(S, null);
assert.ok(kNone.includes('<div class="econ-kpi__l">국면</div><div class="econ-kpi__v">자료 없음</div>'), 'phase cell says 자료 없음');
assert.ok(!/econ-kpi__v">(엘니뇨|라니냐|중립)/.test(kNone), 'no-data kpi asserts no phase');
console.log('no-data OK');

// agency links — 링크 전용, 외부 링크 안전
const links = C.ensoAgencyLinksHTML();
assert.ok(links.includes('iri.columbia.edu') && links.includes('charts.ecmwf.int') && links.includes('jma.go.jp'), 'links IRI/ECMWF/JMA');
assert.ok(!links.includes('<img'), 'link-only panel embeds no images');
const anchors = links.match(/<a [^>]*>/g) || [];
assert.ok(anchors.length >= 3 && anchors.every(a => a.includes('rel="noopener noreferrer"')), 'every external link is safe');
console.log('links OK');
