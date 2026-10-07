// scripts/tests/test_pf_apply_enc.mjs — run with: node scripts/tests/test_pf_apply_enc.mjs
// 현행 화면 js/app2.js pfApplyEncHoldings 가 새 화면(app/src/lib/personal/e2e.ts encrypt)이 만든 보유 덩어리를
// 받았을 때, 이 기기 목록에 없는 종목을 버리지 않고 새 행으로 추가하는지. 이름은 다음 시세 갱신이 채운다.
// 브라우저 코드라 해당 구간만 잘라 가짜 전역으로 돌린다(test_enso_forecast.mjs 와 같은 방식). 망·Playwright 없음.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { encrypt } from '../../app/src/lib/personal/e2e.ts';

const src = fs.readFileSync(new URL('../../js/app2.js', import.meta.url), 'utf8');
function slice(marker, endMarker) {
  const i = src.indexOf(marker); const j = src.indexOf(endMarker, i);
  if (i < 0 || j < 0) throw new Error('markers not found: ' + marker);
  return src.slice(i, j);
}
const encBlock = slice('const PF_KDF_ITER', '// ── 페이지 초기화');
const refreshBlock = slice('async function pfRefreshQuotes(manual) {', '// ── 종목 검색/추가');
const addBlock = slice('function pfAddItem() {', 'function pfDeleteItem(');
const trackBlock = slice('function pfBuildTrackingPayload() {', 'async function pfSyncAlerts(');
const el = { textContent: '', value: '', style: {}, classList: { add() {}, remove() {} } };

const PASS = 'test-pass-1234';
const store = { pfHoldingsPass: PASS };
const pfState = {
  groups: [{ id: 'g1', name: '내 목록' }],
  items: [{ id: 'i1', symbol: '005930', market: 'KR', yahoo: null, name: '삼성전자', secType: 'stock', ccy: 'KRW', avg: null, qty: null, group: 'g1' }],
};
const calls = { save: 0, render: 0, refresh: 0 };
const scope = {
  pfState, pfQuotes: {},
  localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; }, removeItem: k => { delete store[k]; } },
  // 보유 암호 읽기(app2.js _pfSecret)는 잘라 낸 구간 밖 — 지금 판은 sessionStorage 에 두지만 여기선 같은 가짜 저장소에서 읽는다
  _pfSecret: k => store[k] || '',
  pfSave: () => { calls.save++; }, pfRenderAll: () => { calls.render++; },
  pfAskText: async () => null, showToast: () => {}, document: { getElementById: () => el }, window: {},
  pfEnsureUsdKrw: async () => {}, pfMarkDirty: () => {}, pfUsdKrw: () => 1380,
  // 현행 화면 검색으로 고른 추가 후보 — 암호본으로 이미 들어온 국내 ETF
  pfPendingAdd: { symbol: '069500', market: 'KR', yahoo: null, name: 'KODEX 200', secType: 'etf', ccy: 'KRW' },
  // 시세 응답: 코드 → 이름·유형(국내 ETF 하나 포함)
  pfFetchQuote: async it => ({ '005930': { price: 1, name: '삼성전자', secType: 'stock' },
                               '069500': { price: 1, name: 'KODEX 200', secType: 'etf' },
                               'AAPL': { price: 1, name: 'Apple Inc.', secType: 'stock' } })[it.symbol] || null,
};
const fn = new Function(...Object.keys(scope),
  encBlock + '\n' + refreshBlock + '\n' + addBlock + '\n' + trackBlock +
  '\n;return { pfApplyEncHoldings, pfRefreshQuotes, pfAddItem, pfBuildTrackingPayload };');
const M = fn(...Object.values(scope));

// 새 화면이 올린 덩어리: 기존 1 + 이 기기에 없는 국내 ETF·미국 주식 2 + 끝의 { t } 시각 칸
const blob = await encrypt([
  { s: '005930', m: 'KR', a: 70000, q: 10, fx: null },
  { s: '069500', m: 'KR', a: 35000, q: 3, fx: null },
  { s: 'AAPL', m: 'US', a: 190.5, q: 2, fx: 1380 },
], PASS, '2026-10-02T05:00:00.000Z');

const applied = await M.pfApplyEncHoldings(blob, { silent: true });
assert.equal(applied, 3, '세 종목 모두 적용 — { t } 칸은 건너뛴다');
assert.equal(pfState.items.length, 3, '목록에 없던 두 종목이 새 행으로 추가');
const by = s => pfState.items.find(it => it.symbol === s);
assert.deepEqual([by('005930').avg, by('005930').qty, by('005930').name], [70000, 10, '삼성전자']);
const etf = by('069500'), us = by('AAPL');
assert.deepEqual([etf.market, etf.avg, etf.qty, etf.ccy, etf.yahoo, etf.group], ['KR', 35000, 3, 'KRW', null, 'g1']);
assert.deepEqual([us.market, us.avg, us.qty, us.fxBuy, us.ccy, us.yahoo], ['US', 190.5, 2, 1380, 'USD', 'AAPL']);
assert.ok(etf.id && etf.id !== us.id && etf.id !== 'i1', '행 id 가 서로 다르다');
assert.ok(calls.save >= 1 && calls.render >= 1);

// 다음 시세 갱신이 코드로 둔 이름과 비어 있는 유형을 채운다(pfApplyEncHoldings 도 끝에서 부르지만 기다리지 않아 여기서 한 번 더)
await M.pfRefreshQuotes();
assert.deepEqual([etf.name, etf.secType], ['KODEX 200', 'etf']);
assert.deepEqual([us.name, us.secType], ['Apple Inc.', 'stock']);

// 같은 덩어리를 다시 받아도 행이 늘지 않는다(코드+시장으로 찾는다)
assert.equal(await M.pfApplyEncHoldings(blob, { silent: true }), 3);
assert.equal(pfState.items.length, 3);

// 암호가 틀리면 -1, 목록은 그대로
store.pfHoldingsPass = 'wrong-pass-0000';
assert.equal(await M.pfApplyEncHoldings(blob, { silent: true }), -1);
assert.equal(pfState.items.length, 3);

// 암호본으로 만든 행은 표식(fromEnc)을 달고, 공개 목록(tracking payload)에 실리지 않는다 — 표식 자체도 서버로 안 간다
assert.deepEqual([etf.fromEnc, us.fromEnc, by('005930').fromEnc], [true, true, undefined]);
const pub = M.pfBuildTrackingPayload();
assert.deepEqual(pub.items.map(x => x.symbol), ['005930']);
assert.ok(pub.items.every(x => !('fromEnc' in x)));

// 사용자가 현행 화면에서 그 종목을 직접 추가하면 표식이 지워져 공개 목록에 실린다(행은 늘지 않는다)
M.pfAddItem();
assert.equal(etf.fromEnc, undefined);
assert.equal(pfState.items.length, 3);
assert.deepEqual(M.pfBuildTrackingPayload().items.map(x => x.symbol), ['005930', '069500']);

console.log('ok  pfApplyEncHoldings: 목록에 없는 종목은 새 행 · 이름은 시세 갱신이 채움 · 암호본 행은 공개 목록 제외');
