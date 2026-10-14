// GET /quotes 자가 점검 — 코드 검사 · .KS→.KQ 순서 · 미국 점→줄표 · 30개 상한 · 60초 보관 · CORS 머리.
// 가짜 fetch 만 쓴다(Yahoo 를 부르지 않는다).
//
// 실행: node cloudflare-worker/test_quotes.mjs
import worker from './worker.js';

const env = { PROXY_LIMITER: { limit: async () => ({ success: true }) } };
const call = async (qs, e = env) => {
  const r = await worker.fetch(new Request('https://w.test/quotes' + qs, { headers: { Origin: 'https://0101-commits.github.io' } }), e, { waitUntil() {} });
  let j = null;
  try { j = await r.clone().json(); } catch (_) {}
  return { status: r.status, j, h: r.headers };
};

// 일봉 응답 — 마지막 일봉(10/14) 앞에 10/13 종가 100, 같은 날 일봉이 둘 오는 장중 모양
const chart = (exchangeName, price, extra = {}) => ({
  chart: { result: [{
    meta: { exchangeName, regularMarketPrice: price, regularMarketTime: 1760418000, gmtoffset: 32400, ...extra },
    timestamp: [1760227200, 1760313600, 1760400000, 1760403600].map(t => t + 0),
    indicators: { quote: [{ close: [90, 100, 105, price] }] },
  }] },
});
const urls = [];
// 심볼 → 응답(없으면 빈 result: Yahoo 의 「종목 없음」)
let table = {};
globalThis.fetch = async (u) => {
  const sym = decodeURIComponent(String(u).split('/chart/')[1].split('?')[0]);
  urls.push(sym);
  const body = table[sym] || { chart: { result: null } };
  return new Response(JSON.stringify(body), { status: 200 });
};

let fails = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) { console.log(`  OK   ${label}`); return; }
  fails++;
  console.log(`  FAIL ${label}: ${JSON.stringify(got)} (기대 ${JSON.stringify(want)})`);
};

console.log('코드 검사');
check('codes 없음 → 400', (await call('')).status, 400);
check('형식 틀림 → 400', (await call('?codes=12345')).status, 400);
check('한글 → 400', (await call('?codes=삼성전자')).status, 400);
check('미국 11자 → 400', (await call('?codes=ABCDEFGHIJK')).status, 400);
check('틀린 코드 하나라도 있으면 → 400, fetch 0', urls.length, 0);
const many = Array.from({ length: 31 }, (_, i) => String(100000 + i)).join(',');
check('31개 → 400', (await call('?codes=' + many)).status, 400);
check('30개 상한 거절에도 fetch 0', urls.length, 0);

console.log('국내 .KS 성공');
table = { '111111.KS': chart('KSC', 110) };
let r = await call('?codes=111111');
check('상태 200', r.status, 200);
check('시세 값', r.j.items['111111'] && [r.j.items['111111'].price, r.j.items['111111'].prev, r.j.items['111111'].exchange], [110, 100, 'KSC']);
check('pct = (110/100-1)*100', Math.abs(r.j.items['111111'].pct - (110 / 100 - 1) * 100) < 1e-9, true);
check('마지막 일봉과 같은 날 일봉(105)은 전일로 안 본다 → 전일 = 10/13 종가', r.j.items['111111'].prev, 100);
check('.KS 한 번만 부름', urls, ['111111.KS']);
check('asOf 있음', typeof r.j.asOf, 'string');
check('at = regularMarketTime', r.j.items['111111'].at, new Date(1760418000 * 1000).toISOString());

console.log('.KS 가 KOE 거나 MUTUALFUND 면 .KQ');
urls.length = 0;
table = { '222222.KS': chart('KOE', 194000, { instrumentType: 'MUTUALFUND' }), '222222.KQ': chart('KOE', 115700) };
r = await call('?codes=222222');
check('.KQ 채택', r.j.items['222222'] && [r.j.items['222222'].price, r.j.items['222222'].exchange], [115700, 'KOE']);
check('.KS → .KQ 순서', urls, ['222222.KS', '222222.KQ']);
urls.length = 0;
table = { '333333.KS': chart('KSC', 500, { instrumentType: 'MUTUALFUND' }), '333333.KQ': chart('KOE', 700) };
r = await call('?codes=333333');
check('KSC 여도 MUTUALFUND 면 버리고 .KQ', r.j.items['333333'] && r.j.items['333333'].price, 700);
urls.length = 0;
table = { '444444.KS': chart('KSC', 10), '444444.KQ': chart('KOE', 20) };
r = await call('?codes=444444');
check('.KS 가 맞으면 .KQ 안 부름', urls, ['444444.KS']);
table = { '555555.KQ': chart('KSC', 10) };
r = await call('?codes=555555');
check('.KQ 응답이 KSC 면 버림(표식 불일치)', r.j.items, {});

console.log('둘 다 실패면 빠진다');
urls.length = 0;
table = { '666666.KS': chart('KOE', 1), '666666.KQ': chart('KSC', 2), '777777.KS': chart('KSC', 50) };
r = await call('?codes=666666,777777');
check('못 받은 코드는 items 에서 빠짐', Object.keys(r.j.items), ['777777']);
check('200 으로 응답', r.status, 200);

console.log('미국 점 → 줄표');
urls.length = 0;
table = { 'BRK-B': chart('NYQ', 500), 'AAPL': chart('NMS', 200) };
r = await call('?codes=BRK.B,AAPL');
check('BRK-B 로 부름', urls.sort(), ['AAPL', 'BRK-B']);
check('응답 키는 요청한 코드 그대로', Object.keys(r.j.items).sort(), ['AAPL', 'BRK.B']);
check('미국 거래소 표식 그대로', r.j.items['AAPL'].exchange, 'NMS');

console.log('60초 보관');
urls.length = 0;
r = await call('?codes=BRK.B,AAPL');
check('두 번째 요청은 fetch 0', urls.length, 0);
check('값은 같다', Object.keys(r.j.items).sort(), ['AAPL', 'BRK.B']);
urls.length = 0;
r = await call('?codes=999999');
r = await call('?codes=999999');
check('못 받은 코드는 보관하지 않는다(요청마다 .KS·.KQ 다시 시도)', urls.length, 4);

console.log('동시 6개');
let live = 0, peak = 0;
const eight = Array.from({ length: 12 }, (_, i) => String(300000 + i));
table = Object.fromEntries(eight.map(c => [c + '.KS', chart('KSC', 10)]));
globalThis.fetch = async (u) => {
  live++; peak = Math.max(peak, live);
  await new Promise(res => setTimeout(res, 5));
  live--;
  const sym = decodeURIComponent(String(u).split('/chart/')[1].split('?')[0]);
  return new Response(JSON.stringify(table[sym] || { chart: { result: null } }), { status: 200 });
};
r = await call('?codes=' + eight.join(','));
check('12개 모두 받음', Object.keys(r.j.items).length, 12);
check('동시 요청 ≤ 6', peak <= 6 && peak > 1, true);

console.log('CORS · 제한기');
check('ACAO *', r.h.get('access-control-allow-origin'), '*');
const pre = await worker.fetch(new Request('https://w.test/quotes', { method: 'OPTIONS', headers: { Origin: 'https://x.test' } }), env, { waitUntil() {} });
check('preflight ACAO *', pre.headers.get('access-control-allow-origin'), '*');
check('인증 헤더 없이 200(공개)', r.status, 200);
const lim = { PROXY_LIMITER: { limit: async () => ({ success: false }) } };
check('제한기 초과 → 429', (await call('?codes=111111', lim)).status, 429);
check('제한기 바인딩 없으면 통과(fail-open)', (await call('?codes=111111', {})).status, 200);

console.log(fails ? `\n실패 ${fails}건` : '\n전부 통과');
process.exit(fails ? 1 : 0);
