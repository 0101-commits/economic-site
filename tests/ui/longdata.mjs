// T3 최장 데이터 주입 게이트 — 실제 데이터가 짧아서 안 드러나는 넘침·잘림을 잡는다.
// 실행: node tests/ui/longdata.mjs [overflow.mjs 와 같은 인자]
// 동작: data.json · bundles/*.json 응답을 page.route 로 가로채, 필드 이름이 이름류이면
//       longdata.json 의 같은 분류 최장값으로, 숫자 필드는 최대 자릿수 값으로 바꿔치기한 뒤
//       overflow.mjs 와 같은 검사를 한다.
// 치환 규칙(단순): 키 이름 → 분류. 식별자·주소·날짜류 키와 현재 값보다 짧아지는 치환은 건너뛴다.
//   업종 sector|industry|업종 · 지역 region|area|sido|sigungu|district|지역 · 일정 event|schedule|일정
//   지표 label|title|indicator|metric|short · 종목 name|nm|stock|corp  (위에서부터 먼저 맞는 분류)
//   숫자: cap|amount|volume|turnover → 2,798,759,616,000 · price|close|last|px → 1,809,000 ·
//         value|val|idx|index → 26,861.06 (시계열 배열 안의 숫자는 건드리지 않는다)
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { sweep, report } from './_lib.mjs';

const SET = JSON.parse(readFileSync(join(dirname(new URL(import.meta.url).pathname.slice(1)), 'longdata.json'), 'utf8'));
const SKIP = /(^|_)(id|code|symbol|ticker|url|link|href|src|date|time|ts|at|key|type|color|icon|unit|class)$/i;
const STR_RULES = [
  ['sector', /sector|industry|업종/i], ['region', /region|area|sido|sigungu|district|지역/i],
  ['event', /event|schedule|일정/i], ['indicator', /label|title|indicator|metric|short/i],
  ['stock', /(^|_)(name|nm)$|stock|corp|종목/i],
];
const NUM_RULES = [['cap', /cap|amount|volume|turnover/i], ['price', /price|close|last|px/i], ['index', /value|val$|idx|index/i]];
const turn = {};
const pick = cat => { const a = SET[cat]; turn[cat] = (turn[cat] || 0) + 1; return a[turn[cat] % a.length]; };
let replaced = 0;

function walk(v, key, inSeries) {
  if (Array.isArray(v)) return v.map(x => walk(x, key, true));
  if (v && typeof v === 'object') { const o = {}; for (const k of Object.keys(v)) o[k] = walk(v[k], k, false); return o; }
  if (!key || SKIP.test(key)) return v;
  if (typeof v === 'string' && v.length > 0 && !/^(https?:|\d{4}-\d\d-\d\d)/.test(v)) {
    const r = STR_RULES.find(([, re]) => re.test(key));
    if (r) { const n = pick(r[0]); if (n.length >= v.length) { replaced++; return n; } }
  } else if (typeof v === 'number' && !inSeries) {
    const r = NUM_RULES.find(([, re]) => re.test(key));
    if (r && SET.number[r[0]] > Math.abs(v)) { replaced++; return SET.number[r[0]]; }
  }
  return v;
}

const rows = await sweep({
  setup: ctx => ctx.route(/\/(data\.json|bundles\/[^/?]+\.json)(\?.*)?$/, async route => {
    try {
      const res = await route.fetch();
      const body = await res.json();
      await route.fulfill({ response: res, json: walk(body, '', false) });
    } catch (_) { await route.continue(); }
  }),
});
console.log(`[longdata] 치환한 필드 ${replaced}개(조합마다 누적)`);
if (!replaced) console.log('  경고: 치환된 값이 없다. 이 주소가 data.json 또는 bundles/*.json 을 쓰는지 확인할 것.');
process.exit(report(rows, 'longdata'));
