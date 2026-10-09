// 자가검사: npm test --prefix app — 보유 → Yahoo 심볼 · 일봉 응답 해석(전일 종가 규칙) · 묶음 우선 · 동시 4개 · 실패는 비워 둠 · 10분 저장본
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { chartUrl, holdingQuotes, parseChart, parseSeries, yahooSymbols } from './quotes.ts'
import type { Holding, Quote } from './calc.ts'

const H = (symbol: string, market: 'KR' | 'US', extra: Partial<Holding> = {}): Holding => ({ id: symbol, symbol, market, qty: 1, avg: 1, ...extra })

test('yahooSymbols: 국내 .KS 다음 .KQ · 미국은 yahoo 칸 또는 티커', () => {
  assert.deepEqual(yahooSymbols(H('005930', 'KR')), ['005930.KS', '005930.KQ'])
  assert.deepEqual(yahooSymbols(H('0035S0', 'KR')), ['0035S0.KS', '0035S0.KQ'])
  assert.deepEqual(yahooSymbols(H('삼성', 'KR')), [])
  assert.deepEqual(yahooSymbols(H('AAPL', 'US')), ['AAPL'])
  assert.deepEqual(yahooSymbols(H('BRKB', 'US', { yahoo: 'BRK-B' })), ['BRK-B'])
  assert.deepEqual(yahooSymbols(H('AAPL', 'US', { yahoo: null })), ['AAPL'])
})

test('chartUrl: Worker 프록시 + range=5d interval=1d', () => {
  const u = new URL(chartUrl('005930.KS'))
  assert.equal(u.origin, 'https://ecom-dashboard-proxy.e-hcg.workers.dev')
  assert.equal(u.searchParams.get('url'), 'https://query1.finance.yahoo.com/v8/finance/chart/005930.KS?range=5d&interval=1d')
})

const chart = (meta: Record<string, unknown>, close: (number | null)[]) => ({ chart: { result: [{ meta, indicators: { quote: [{ close }] } }] } })

test('parseChart: 전일 = 마지막 일봉 바로 앞의 확정 종가', () => {
  // 2026-10-02 실측 모양: 005930.KS — chartPreviousClose(285,500)는 5일 창 앞의 값이라 쓰면 안 된다
  assert.deepEqual(parseChart(chart({ regularMarketPrice: 274000, chartPreviousClose: 285500 }, [270000, 272500, 268500, 276000, 274000])), { price: 274000, prev: 276000 })
  // AAPL — 마지막 일봉 종가가 null. 빈칸을 먼저 빼면 329.40 을 전일로 잡는다(틀림)
  assert.deepEqual(parseChart(chart({ regularMarketPrice: 330.32, chartPreviousClose: 335.92 }, [341.07, 338.4, 329.4, 333.02, null])), { price: 330.32, prev: 333.02 })
  // 앞 일봉이 비면 그 앞, 그것도 없으면 chartPreviousClose
  assert.deepEqual(parseChart(chart({ regularMarketPrice: 10 }, [8, null, 11])), { price: 10, prev: 8 })
  assert.deepEqual(parseChart(chart({ regularMarketPrice: 10, chartPreviousClose: 9 }, [10])), { price: 10, prev: 9 })
  // 현재가가 없으면 마지막 일봉 종가
  assert.deepEqual(parseChart(chart({}, [9, 10])), { price: 10, prev: 9 })
})

test('parseChart: 국내는 거래소 표식이 맞는 응답만(접미사가 틀린 물음의 엉뚱한 값 거르기)', () => {
  const bad = chart({ regularMarketPrice: 194000, exchangeName: 'KOE', instrumentType: 'MUTUALFUND' }, [111300, 106100, 109100, 114700, null])
  assert.equal(parseChart(bad, 'KSC'), null)                                   // 247540.KS 실측
  assert.equal(parseChart(chart({ regularMarketPrice: 84400, exchangeName: 'KOE', instrumentType: 'MUTUALFUND' }, [276000, null]), 'KOE'), null)   // 005930.KQ 실측
  assert.deepEqual(parseChart(chart({ regularMarketPrice: 115700, exchangeName: 'KOE', instrumentType: 'EQUITY' }, [114700, 115700]), 'KOE'), { price: 115700, prev: 114700 })
  assert.deepEqual(parseChart(chart({ regularMarketPrice: 111615, exchangeName: 'KSC', instrumentType: 'ETF' }, [111520, 111615]), 'KSC'), { price: 111615, prev: 111520 })
})

test('parseChart: 종목 없음(result null) · 값 없음 → null', () => {
  assert.equal(parseChart({ chart: { result: null } }), null)
  assert.equal(parseChart(chart({ regularMarketPrice: 0 }, [null])), null)
  assert.equal(parseChart(null), null)
})

/** sessionStorage · fetch 모의. 응답은 심볼별 [현재가, 전일]. 동시 요청 수의 최댓값을 잰다. */
function stubs(table: Record<string, [number, number] | 'fail' | 'bogus'>) {
  const store = new Map<string, string>()
  const calls: string[] = []
  let live = 0, peak = 0
  const g = globalThis as Record<string, unknown>
  const saved = { fetch: g.fetch, sessionStorage: g.sessionStorage }
  g.sessionStorage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v) } }
  g.fetch = async (url: string) => {
    const sym = decodeURIComponent(new URL(new URL(url).searchParams.get('url')!).pathname.split('/').pop()!)
    calls.push(sym)
    live++; peak = Math.max(peak, live)
    await new Promise(r => setTimeout(r, 5))
    live--
    const v = table[sym]
    if (v === 'fail') throw new TypeError('Failed to fetch')
    const exchangeName = sym.endsWith('.KS') ? 'KSC' : sym.endsWith('.KQ') ? 'KOE' : 'NMS'
    const body = v === 'bogus' ? chart({ regularMarketPrice: 194000, exchangeName: 'KOE', instrumentType: 'MUTUALFUND' }, [1, null])
      : v ? chart({ regularMarketPrice: v[0], exchangeName, instrumentType: 'EQUITY' }, [v[1], v[0]]) : { chart: { result: null } }
    return new Response(JSON.stringify(body), { status: 200 })
  }
  return { calls, store, peak: () => peak, restore: () => Object.assign(g, saved) }
}

test('holdingQuotes: 묶음 우선 · .KQ 로 넘어가기 · 실패는 비워 둠 · 동시 4개까지 · 10분 저장본', async () => {
  const s = stubs({ '000660.KS': 'bogus', '000660.KQ': [200, 190], 'AAPL': [110, 100], 'MSFT': [50, 40], 'NVDA': [30, 30], 'TSLA': [21, 20], 'META': 'fail' })
  try {
    const items = [H('005930', 'KR'), H('000660', 'KR'), H('AAPL', 'US'), H('MSFT', 'US'), H('NVDA', 'US'), H('TSLA', 'US'), H('META', 'US'), H('AAPL', 'US', { id: 'dup' })]
    const have = new Map<string, Quote>([['005930', { price: 70000, pct: 1.5, name: '삼성전자' }]])
    const t0 = Date.parse('2026-10-02T01:00:00Z')
    const q = await holdingQuotes(items, have, t0)
    assert.deepEqual(q.get('005930'), { price: 70000, pct: 1.5, name: '삼성전자' })   // 묶음 그대로, 요청 없음
    assert.ok(!s.calls.some(c => c.startsWith('005930')))
    assert.ok(Math.abs(q.get('000660')!.pct! - (200 / 190 - 1) * 100) < 1e-9)
    assert.deepEqual(s.calls.filter(c => c.startsWith('000660')), ['000660.KS', '000660.KQ'])
    assert.equal(q.get('AAPL')!.price, 110)
    assert.equal(q.get('NVDA')!.pct, 0)
    assert.equal(q.has('META'), false)                                              // 지어내지 않는다
    assert.equal(s.calls.filter(c => c === 'AAPL').length, 1)                        // 같은 종목 두 줄은 한 번만
    assert.ok(s.peak() <= 4, `동시 요청 ${s.peak()}개`)

    const before = s.calls.length
    const again = await holdingQuotes(items, have, t0 + 9 * 60_000)                  // 10분 안: 저장본(실패한 META 만 다시)
    assert.deepEqual(s.calls.slice(before), ['META'])
    assert.equal(again.get('MSFT')!.price, 50)
    await holdingQuotes(items, have, t0 + 11 * 60_000)                               // 10분 뒤: 다시 받는다
    assert.ok(s.calls.slice(before + 1).includes('MSFT'))
  } finally { s.restore() }
})

test('parseSeries: 거래소 현지 날짜 · 빈 종가 빼기 · 1년 주소 · 거래소 검사', () => {
  // 2026-10-09 실측 모양: AAPL 미국 동부(gmtoffset -14400) — 장 시작 13:30Z 는 그날 날짜
  const j = { chart: { result: [{ meta: { regularMarketPrice: 340.42, gmtoffset: -14400, longName: 'Apple Inc.', regularMarketTime: 1791489600 }, timestamp: [1791293400, 1791379800, 1791466200], indicators: { quote: [{ close: [333.63, null, 340.42] }] } }] } }
  assert.deepEqual(parseSeries(j), { pts: [['2026-10-06', 333.63], ['2026-10-08', 340.42]], price: 340.42, prev: 333.63, name: 'Apple Inc.', asOf: '2026-10-08T20:00:00.000Z' })
  assert.equal(parseSeries(j, 'KSC'), null)                                        // 거래소 표식이 다르면 버린다
  assert.equal(parseSeries({ chart: { result: [{ meta: { regularMarketPrice: 1 }, timestamp: [1], indicators: { quote: [{ close: [1] }] } }] } }), null)   // 점 1개
  assert.equal(new URL(chartUrl('AAPL', '1y')).searchParams.get('url'), 'https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1y&interval=1d')
})
