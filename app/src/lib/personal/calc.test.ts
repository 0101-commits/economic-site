// 자가검사: npm test --prefix app — 손익 계산 · 환차 분해 · what-if · 위험 · 금액 표기
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { evaluate, fxWhatIf, npsDomesticShare, upsertSnap, risk, benchmark, collectStocks, collectDomestic, fmtMoney, fmtMoneyChange, type Holding, type Quote } from './calc.ts'

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
  near(r.sharpe, 0)                         // 오르내림이 같아 하루 평균 0
})

test('risk: 샤프 · 소르티노 — 하루 로그 수익률 +2% · -1% 를 30번씩(무위험 0, √252 연환산)', () => {
  const day = (i: number) => new Date(Date.UTC(2026, 0, 1 + i)).toISOString().slice(0, 10)
  let R = 1
  const snaps = Array.from({ length: 61 }, (_, i) => {
    if (i) R *= Math.exp(i % 2 ? 0.02 : -0.01)
    return { d: day(i), ev: 1_000_000 * R, ct: 1_000_000 }
  })
  const r = risk(snaps, 1)
  assert.equal(r.n, 60)
  // 평균 0.005, 표본 표준편차 √(60 × 0.015² / 59), 손실 쪽 편차 √(30 × 0.01² / 60)
  near(r.sharpe, (0.005 / Math.sqrt((60 * 0.015 ** 2) / 59)) * Math.sqrt(252), 1e-9)
  near(r.sortino, (0.005 / Math.sqrt((30 * 0.01 ** 2) / 60)) * Math.sqrt(252), 1e-9)
  near(r.sharpe, 5.2473, 1e-4)
  near(r.sortino, 11.2250, 1e-4)
  const up = risk(Array.from({ length: 61 }, (_, i) => ({ d: day(i), ev: 100 + i, ct: 100 })), 1)
  assert.equal(up.sortino, undefined)       // 손실 날이 없으면 소르티노는 없다(무한대를 적지 않는다)
  // 원금이 늘어도(추가 매수) 평가액 ÷ 원금이 같으면 수익률 0
  assert.equal(risk(Array.from({ length: 61 }, (_, i) => ({ d: day(i), ev: 100 * (i + 1), ct: 100 * (i + 1) })), 1).sharpe, undefined)
})

test('benchmark: 첫 날 = 100, 원금 보정, 지수는 그날 또는 7일 안 직전 값', () => {
  const snaps = [
    { d: '2026-10-01', ev: 1_000, ct: 1_000 },
    { d: '2026-10-03', ev: 2_200, ct: 2_000 },   // 원금 2배(추가 매수) · 평가액 ÷ 원금 1.1
    { d: '2026-10-05', ev: 0, ct: 2_000 },       // 평가액 없는 날은 뺀다
    { d: '2026-10-06', ev: 2_400, ct: 2_000 },
  ]
  const kospi: [string, number][] = [['2026-09-30', 50], ['2026-10-01', 100], ['2026-10-02', 110], ['2026-10-06', 90]]
  const spx: [string, number][] = [['2026-09-30', 200], ['2026-10-03', 210]]
  const b = benchmark(snaps, [{ name: 'KOSPI', pts: kospi }, { name: 'S&P 500', pts: spx }])!
  assert.deepEqual(b.mine.map(p => p[0]), ['2026-10-01', '2026-10-03', '2026-10-06'])
  b.mine.forEach((p, i) => near(p[1], [100, 110, 120][i]))
  b.idx[0].pts.forEach((p, i) => near(p[1], [100, 110, 90][i]))           // 10-03 은 10-02 종가
  b.idx[1].pts.forEach((p, i) => near(p[1], [100, 105, 105][i]))          // 10-01 은 9-30 종가
  assert.equal(b.idx[1].name, 'S&P 500')
  // 지수 값이 7일보다 오래되면 그날은 뺀다 → 맞춘 날 2일 미만이면 null
  assert.equal(benchmark(snaps, [{ name: 'KOSPI', pts: [['2026-09-01', 1]] }]), null)
  assert.equal(benchmark(snaps.slice(0, 1), [{ name: 'KOSPI', pts: kospi }]), null)
})

test('collectStocks: 같은 코드는 먼저 본 목록 하나만, 시세 없는 칸은 건너뛴다', () => {
  const out = new Map<string, Quote>()
  collectStocks({
    amount: { items: [{ code: '005930', name: '삼성전자', price: 262_500, chgPct: -2.23 }] },
    tossAmount: { items: [{ code: '005930', name: '삼성전자', price: 999, chgPct: 9 }, { code: '000660', price: 1_686_000, chgPct: null }, { code: '035720', price: null }] },
  }, out)
  assert.deepEqual([...out.keys()], ['005930', '000660'])
  assert.deepEqual(out.get('005930'), { price: 262_500, pct: -2.23, name: '삼성전자' })
  assert.deepEqual(out.get('000660'), { price: 1_686_000, pct: null, name: undefined })
  collectStocks({ items: [{ code: '000660', price: 1 }] }, out)            // 나중 묶음도 앞의 값을 덮지 않는다
  assert.equal(out.get('000660')!.price, 1_686_000)
})

test('collectDomestic: KRX 순위 4목록(전일 값)은 시세로 쓰지 않는다', () => {
  const krx = (code: string) => ({ asOf: '2026-10-08', kospi: [{ code, price: 100, chgPct: 1 }] })
  const out = new Map<string, Quote>()
  collectDomestic({
    marketCap: krx('000001'), volume: krx('000002'), high52: krx('000003'), low52: krx('000004'),
    amount: { asOf: '2026-10-09', items: [{ code: '005930', price: 262_500, chgPct: -2.23 }] },
    gainers: { kospi: [{ code: '000005', price: 50, chgPct: 30 }] },
  }, out)
  assert.deepEqual([...out.keys()], ['005930', '000005'])
  collectDomestic(null, out)                                                 // 묶음이 없어도 던지지 않는다
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
