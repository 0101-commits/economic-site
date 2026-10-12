// 자가검사: npm test --prefix app — 종목 판정 · 묶음 종목 행 모으기(우선순위 · 기준 시각 물려받기) · 메르 글 언급 · 겹침 지수화
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { headVolume, isStockId, merMentions, merNames, overlay, searchRows, stockHits, stockRows, US_KO } from './detail.ts'
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

test('stockRows: 시장별 기준(byMarket)은 그 시장 칸 아래 행에 · liveUntil 도 물려받는다', () => {
  const dom = { views: {
    amount: { asOf: '2026-10-12T10:40:00+09:00', state: 'live', liveUntil: '2026-10-12T10:55:00+09:00', items: [{ code: '000660', name: 'SK하이닉스', price: 1, chgPct: 1 }] },
    gainers: {
      asOf: '2026-10-08', state: 'prev',
      byMarket: { kospi: { asOf: '2026-10-12T10:40:00+09:00', state: 'live', liveUntil: '2026-10-12T10:55:00+09:00' } },
      kospi: [{ code: '001210', name: '금호전기', price: 11070, chgPct: 29.92 }],
      kosdaq: [{ code: '278650', name: 'HLB바이오스텝', price: 6310, chgPct: 29.97 }],
    },
  } }
  const m = stockRows([dom])
  assert.equal(m.get('000660')!.liveUntil, '2026-10-12T10:55:00+09:00')
  assert.deepEqual([m.get('001210')!.asOf, m.get('001210')!.state, m.get('001210')!.liveUntil], ['2026-10-12T10:40:00+09:00', 'live', '2026-10-12T10:55:00+09:00'])
  assert.deepEqual([m.get('278650')!.asOf, m.get('278650')!.state, m.get('278650')!.liveUntil], ['2026-10-08', 'prev', undefined])   // byMarket 에 없는 시장은 보기 기준
})

test('headVolume: 묶음 행 거래량 먼저 · 없으면 머리 값과 같은 날의 일봉 거래량 · 다른 날이면 없음', () => {
  const row = { code: '005930', name: '삼성전자', price: 255500, chgPct: -2.48, asOf: '2026-10-12', state: 'prev' }
  const vol = { day: '2026-10-12', value: 12_345_678 }
  assert.deepEqual(headVolume({ ...row, volume: 1 }, true, vol), { value: 1, fromChart: false })
  assert.deepEqual(headVolume(row, true, vol), { value: 12_345_678, fromChart: true })                       // 2026-10-12 실측: 거래량 줄이 없었다
  assert.equal(headVolume({ ...row, asOf: '2026-10-08' }, true, vol), null)                                   // 지난 목록 값 옆에 오늘 거래량을 적지 않는다
  assert.deepEqual(headVolume(undefined, false, { day: '2026-10-09', value: 5 }), { value: 5, fromChart: true })   // 머리가 일봉(AAPL)
  assert.equal(headVolume(undefined, false, undefined), null)
})

test('검색: 미국 종목을 한글 이름으로 찾는다 · 묶음 행이 있으면 그것이 이긴다', () => {
  const bundle = stockRows([{ items: [{ code: '005930', name: '삼성전자', price: 1, chgPct: 0 }, { code: 'AAPL', name: 'Apple', price: 2, chgPct: 0 }] }])
  const rows = searchRows(bundle)
  assert.deepEqual(stockHits(rows, '엔비디아').map(x => [x.code, x.market]), [['NVDA', 'US']])   // 2026-10-12 실측: 0건이었다
  assert.deepEqual(stockHits(rows, 'nvda').map(x => x.code), ['NVDA'])
  assert.deepEqual(stockHits(rows, '구글').map(x => x.code), ['GOOGL'])
  assert.deepEqual(stockHits(rows, '삼성').map(x => x.code), ['005930'])
  assert.equal(rows.filter(x => x.code === 'AAPL').length, 1)                                    // 묶음 행 하나만(값 있는 쪽)
  assert.equal(rows.find(x => x.code === 'AAPL')!.price, 2)
  assert.ok(Object.keys(US_KO).every(isStockId))                                                 // 표의 열쇠는 전부 종목 id(상세로 간다)
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

test('merMentions: 미국 티커는 낱말로만 · 국내 두 글자 줄임말은 쓰지 않는다', () => {
  const posts = [
    { title: 'MUSIC 산업', url: 'https://blog.naver.com/1', fullText: 'COMMUTE 와 MUX 이야기' },
    { title: '오늘', url: 'https://blog.naver.com/2', fullText: '마이크론(MU)이 올랐다. BRK.B 도' },
    { title: 'LG전자 실적', url: 'https://blog.naver.com/3', fullText: 'LG화학' },
  ]
  const mu = merMentions(posts, merNames(false, 'MU', 'Micron Technology'))
  assert.deepEqual(mu.map(m => m.title), ['오늘'])                           // MUSIC · COMMUTE · MUX 는 아니다
  assert.deepEqual(mu[0].snip![1], 'MU')
  assert.deepEqual(merMentions(posts, merNames(false, 'BRK.B')).map(m => m.title), ['오늘'])
  assert.deepEqual(merNames(true, '003550', 'LG', 'LG'), ['LG', undefined])  // 줄임말 「LG」는 버린다(이름이면 남는다)
  assert.deepEqual(merNames(true, '066570', 'LG전자', 'LG전자'), ['LG전자', 'LG전자'])
  assert.deepEqual(merMentions(posts, merNames(true, '066570', 'LG전자', 'LG')).map(m => m.title), ['LG전자 실적'])
})

test('overlay: 기간마다 첫 점 = 100, 비교 선은 주 선의 날짜 범위 안만 · 0 이하로 시작하면 비운다', () => {
  const main: Pt[] = [['2026-10-01', 200], ['2026-10-02', 210], ['2026-10-05', 190]]
  const other: Pt[] = [['2026-09-30', 1], ['2026-10-01', 50], ['2026-10-02', 55], ['2026-10-05', 60], ['2026-10-06', 99]]
  const o = overlay({ '1w': main }, other)
  assert.deepEqual(o.main['1w']!.map(p => p[1]), [100, 105, 95])
  assert.deepEqual(o.other['1w']!.map(p => [p[0], Math.round(p[1] * 1e6) / 1e6]), [['2026-10-01', 100], ['2026-10-02', 110], ['2026-10-05', 120]])
  assert.deepEqual(overlay({ '1w': [['2026-10-01', -1], ['2026-10-02', 1]] }, other).main['1w'], [])
})

test('stockRows: 거래대금은 거래대금 상위 목록에서만 · 거래대금 · 거래량은 머리 값과 기준 시각이 같은 행에서만', () => {
  const views = {
    amount: { asOf: '2026-10-09', items: [{ code: '005930', name: '삼성전자', price: 100, chgPct: 1, amount: 5e12 }] },
    tossAmount: { asOf: '2026-10-09', items: [{ code: '000660', name: 'SK하이닉스', price: 50, chgPct: 1, amount: 3e11 }] },
    gainers: { asOf: '2026-10-09', kospi: [{ code: '005930', name: '삼성전자', price: 99, chgPct: 0.5, volume: 1.2e7 }] },
    volume: { asOf: '2026-10-08', kospi: [{ code: '000660', name: 'SK하이닉스', price: 48, chgPct: -1, volume: 9e6 }] },
  }
  const m = stockRows([views])
  assert.equal(m.get('005930')!.price, 100)
  assert.equal(m.get('005930')!.amount, 5e12)
  assert.equal(m.get('005930')!.volume, 1.2e7)                     // 같은 날(10/9) 상승 목록의 거래량
  assert.equal(m.get('000660')!.amount, undefined)                // 토스 체결 거래대금은 붙이지 않는다
  assert.equal(m.get('000660')!.volume, undefined)                // 머리(10/9 토스)와 다른 날(10/8 KRX)의 거래량은 붙이지 않는다
  // 홈 거래대금 행은 loadStocks 가 'amount' 칸으로 감싸 넘긴다 — 감싸지 않은 목록의 amount 는 거래대금 상위가 아니다
  assert.equal(stockRows([{ items: [{ code: '005930', name: '삼성전자', price: 1, amount: 9 }] }]).get('005930')!.amount, undefined)
})

test('stockRows: KRX 순위 4목록(전일 확정)은 이름만 — 값 · 등락은 머리 후보에서 뺀다', () => {
  const krx = (code: string) => ({ asOf: '2026-10-08', kospi: [{ code, name: `종목${code}`, market: 'KOSPI', price: 100, chgPct: 1, volume: 5 }] })
  const m = stockRows([{ marketCap: krx('000001'), volume: krx('000002'), high52: krx('000003'), low52: krx('000004') }])
  for (const c of ['000001', '000002', '000003', '000004']) {
    const r = m.get(c)!
    assert.equal(r.name, `종목${c}`)
    assert.equal(r.market, 'KOSPI')
    assert.equal(r.price, null)
    assert.equal(r.chgPct, null)
  }
  // 오늘 목록에 값이 있으면 그것이 머리 — 뒤에 온 KRX 행이 덮지 않는다
  const both = stockRows([{ amount: { asOf: '2026-10-09', items: [{ code: '005930', name: '삼성전자', price: 262500, chgPct: -2 }] } }, { marketCap: krx('005930') }])
  assert.equal(both.get('005930')!.price, 262500)
})
