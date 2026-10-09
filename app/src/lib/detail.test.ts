// 자가검사: npm test --prefix app — 종목 판정 · 묶음 종목 행 모으기(우선순위 · 기준 시각 물려받기) · 메르 글 언급 · 겹침 지수화
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { isStockId, merMentions, overlay, stockRows } from './detail.ts'
import type { Pt } from './format.ts'

test('isStockId: 국내 6자리 · 미국 티커만 종목, 지표 id 는 아님', () => {
  assert.deepEqual(['005930', '0035S0', 'AAPL', 'BRK-B', 'BRK.B', 'T'].map(isStockId), [true, true, true, true, true, true])
  assert.deepEqual(['kospi', 'us10y', 'cpi_kr_yoy', '12345', 'aapl', 'TOOLONGNAME', ''].map(isStockId), [false, false, false, false, false, false, false])
})

test('stockRows: 먼저 본 행이 이기되 값 없는 행은 값 있는 행에 자리를 내준다 · 위쪽 asOf 를 물려받는다', () => {
  const flows = [{ code: '360750', name: 'TIGER 미국S&P500' }]
  const dom = { views: {
    amount: { asOf: '2026-10-09', state: 'prev', items: [{ code: '005930', name: '삼성전자', price: 262500, chgPct: -2.23, market: 'KOSPI' }] },
    gainers: { kospi: [{ code: '005930', name: '삼성전자', price: 1, chgPct: 9 }, { code: '360750', name: 'TIGER 미국S&P500', price: 24000, chgPct: 0.5 }] },
    corpEvents: { asOf: '2026-10-09', items: [{ code: '373220', name: 'LG에너지솔루션', kind: 'earnings' }] },
  } }
  const m = stockRows([flows, dom])
  assert.deepEqual(m.get('005930'), { code: '005930', name: '삼성전자', short: undefined, market: 'KOSPI', price: 262500, chgPct: -2.23, asOf: '2026-10-09', state: 'prev' })
  assert.equal(m.get('360750')!.price, 24000)          // 수급 행(값 없음) → 상승 행이 채운다
  assert.equal(m.get('360750')!.asOf, undefined)       // 상승 목록엔 기준 시각이 없다 — 지어내지 않는다
  assert.equal(m.get('373220')!.price, null)           // 이름만 있는 행도 검색 목록엔 든다
  assert.equal(m.size, 3)
})

test('merMentions: 최신순 n 편 · 전문 일치 앞뒤 40자 · 제목만 일치 · 바깥 링크 검사', () => {
  const long = '가'.repeat(50)
  const posts = [
    { title: '오늘 시장', url: 'https://blog.naver.com/1', date: '2026-10-09', fullText: `${long}삼성전자 실적${long}` },
    { title: '반도체와 삼성전자', url: 'javascript:alert(1)', date: '2026-10-08' },
    { title: '무관한 글', url: 'https://blog.naver.com/3', fullText: '하이닉스' },
    { title: '삼성전자 다시', url: 'https://blog.naver.com/4' },
  ]
  const got = merMentions(posts, ['삼성전자', '삼', undefined], 2)
  assert.equal(got.length, 2)
  assert.deepEqual(got[0].snip, [`…${'가'.repeat(40)}`, '삼성전자', ` 실적${'가'.repeat(37)}…`])
  assert.equal(got[1].href, null)
  assert.equal(got[1].snip, undefined)
  assert.deepEqual(merMentions(posts, ['']), [])
})

test('overlay: 기간마다 첫 점 = 100, 비교 선은 주 선의 날짜 범위 안만 · 0 이하로 시작하면 비운다', () => {
  const main: Pt[] = [['2026-10-01', 200], ['2026-10-02', 210], ['2026-10-05', 190]]
  const other: Pt[] = [['2026-09-30', 1], ['2026-10-01', 50], ['2026-10-02', 55], ['2026-10-05', 60], ['2026-10-06', 99]]
  const o = overlay({ '1w': main }, other)
  assert.deepEqual(o.main['1w']!.map(p => p[1]), [100, 105, 95])
  assert.deepEqual(o.other['1w']!.map(p => [p[0], Math.round(p[1] * 1e6) / 1e6]), [['2026-10-01', 100], ['2026-10-02', 110], ['2026-10-05', 120]])
  assert.deepEqual(overlay({ '1w': [['2026-10-01', -1], ['2026-10-02', 1]] }, other).main['1w'], [])
})

test('stockRows: 거래대금 · 거래량은 다른 목록에서 빈 칸만 채운다', () => {
  const m = stockRows([{ items: [{ code: '005930', name: '삼성전자', price: 100, chgPct: 1, amount: 5e12 }] }, { kospi: [{ code: '005930', name: '삼성전자', price: 99, chgPct: 0.5, volume: 1.2e7 }] }])
  const r = m.get('005930')!
  assert.equal(r.price, 100)
  assert.equal(r.amount, 5e12)
  assert.equal(r.volume, 1.2e7)
})
