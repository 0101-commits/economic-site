// 자가검사: npm test --prefix app — 손익 계산 · 환차 분해 · what-if · 위험 · 금액 표기
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { evaluate, fxWhatIf, npsDomesticShare, upsertSnap, risk, fmtMoney, fmtMoneyChange, type Holding, type Quote } from './calc.ts'

const near = (a: number | null | undefined, b: number, eps = 1e-6) => assert.ok(a != null && Math.abs(a - b) < eps, `${a} ≈ ${b}`)

const kr: Holding = { id: 'a', symbol: '005930', market: 'KR', ccy: 'KRW', qty: 10, avg: 50_000 }
const us: Holding = { id: 'b', symbol: 'AAPL', market: 'US', ccy: 'USD', qty: 2, avg: 100, fxBuy: 1_300 }

test('evaluate: 원화 평가·원금·수익률', () => {
  const q = new Map<string, Quote>([['005930', { price: 55_000, pct: 10 }]])
  const { rows, totals } = evaluate([kr], q, null)
  assert.equal(rows[0].value, 550_000)
  assert.equal(totals.cost, 500_000)
  assert.equal(totals.pnl, 50_000)
  near(totals.pnlPct, 10)
  near(totals.today.price, 50_000)          // 전일가 50,000 → 55,000
  near(totals.today.pct, 10)
  assert.equal(totals.domestic, 550_000)
})

test('evaluate: 달러 종목 오늘 손익 = 주가 몫 + 환차 몫(합이 정확히 맞는다)', () => {
  const q = new Map<string, Quote>([['AAPL', { price: 110, pct: 10 }]])   // 전일 100 → 110
  const { totals } = evaluate([us], q, { now: 1_400, prev: 1_350 })
  near(totals.value, 110 * 2 * 1_400)
  near(totals.cost, 100 * 2 * 1_300)        // 원금은 매입 환율
  near(totals.today.price, 10 * 2 * 1_350)  // 주가 몫은 전일 환율로
  near(totals.today.fx, 110 * 2 * 50)       // 환차 몫은 지금가 × 환율 변화
  const yesterday = 100 * 2 * 1_350
  near(totals.today.price + totals.today.fx, totals.value - yesterday)
  near(totals.usdValue, totals.value)
  near(totals.foreign, totals.value)
})

test('evaluate: 시세·환율 없으면 뺀다, 평단 없으면 수익률 기준에서 뺀다', () => {
  const q = new Map<string, Quote>([['005930', { price: 55_000, pct: null }], ['AAPL', { price: 110, pct: 0 }]])
  const noAvg: Holding = { ...kr, id: 'c', symbol: '000660', avg: null }
  const { totals } = evaluate([kr, us, noAvg], q, null)   // 환율 없음 → AAPL 빠짐, 000660 시세 없음
  assert.equal(totals.missing, 2)
  assert.equal(totals.value, 550_000)
  assert.equal(totals.today.total, 0)       // 등락률 없음 = 오늘 0
  const two = evaluate([kr, { ...noAvg, symbol: '005930' }], q, null).totals
  assert.equal(two.value, 1_100_000)
  assert.equal(two.basisValue, 550_000)     // 평단 없는 줄은 수익률 기준에서 빠진다
  near(two.pnlPct, 10)
})

test('evaluate: 배당은 오늘 손익 합에 더한다', () => {
  const q = new Map<string, Quote>([['005930', { price: 50_000, pct: 0 }]])
  const { totals } = evaluate([kr], q, null, 3_000)
  assert.equal(totals.today.total, 3_000)
  near(totals.today.pct, 0.6)
})

test('fxWhatIf · npsDomesticShare', () => {
  assert.deepEqual(fxWhatIf(1_000, 400, 10), { total: 1_040, delta: 40 })
  assert.deepEqual(fxWhatIf(1_000, 400, -5), { total: 980, delta: -20 })
  near(npsDomesticShare([{ asset: '국내주식', pct: 24.9 }, { asset: '해외주식', pct: 37.0 }]), (24.9 / 61.9) * 100)
  assert.equal(npsDomesticShare([]), null)
})

test('upsertSnap: 같은 날은 바꾸고 날짜순', () => {
  const s = upsertSnap([{ d: '2026-09-30', ev: 1, ct: 1 }, { d: '2026-10-01', ev: 2, ct: 1 }], { d: '2026-10-01', ev: 3, ct: 1 })
  assert.deepEqual(s.map(x => x.ev), [1, 3])
  assert.deepEqual(upsertSnap([{ d: '2026-10-02', ev: 1, ct: 1 }], { d: '2026-10-01', ev: 2, ct: 1 }).map(x => x.d), ['2026-10-01', '2026-10-02'])
})

test('risk: 60건 미만은 n 만, 이상이면 VaR·최대 낙폭', () => {
  const day = (i: number) => new Date(Date.UTC(2026, 0, 1 + i)).toISOString().slice(0, 10)
  assert.deepEqual(risk([{ d: day(0), ev: 100, ct: 100 }, { d: day(1), ev: 101, ct: 100 }], 101), { n: 1 })
  const snaps = Array.from({ length: 61 }, (_, i) => ({ d: day(i), ev: i % 2 ? 110 : 100, ct: 100 }))
  const r = risk(snaps, 1_000_000)
  assert.equal(r.n, 60)
  assert.ok(r.var95! > 0 && r.sd! > 0)
  near(r.mdd, (100 / 110 - 1) * 100)
})

test('fmtMoney · fmtMoneyChange', () => {
  assert.equal(fmtMoney(12_345_678, 'won'), '12,345,678원')
  assert.equal(fmtMoney(12_345_678, 'man'), '1,235만원')
  assert.equal(fmtMoney(123_456, 'man'), '12.3만원')
  assert.equal(fmtMoney(null), '—')
  assert.equal(fmtMoneyChange(-50_000, -1.234, 'won'), '▼ 50,000원 (1.23%)')
  assert.equal(fmtMoneyChange(120_000, 2, 'man'), '▲ 12.0만원 (2.00%)')
  assert.equal(fmtMoneyChange(0, 0, 'won'), '0원 (0.00%)')
  assert.equal(fmtMoneyChange(400, 0.01, 'man'), '0.0만원 (0.01%)')   // 만원으로 0.0 이면 보합
})
