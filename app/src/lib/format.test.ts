// 자가검사: npm test --prefix app  (node --test, 추가 도구 없음)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fmtNumber, fmtChange, changeDir, changeFromPct, scaled, asOfKind, asOfLabel, kindFromState, fmtPct, dayLabel, mdHm, shortDate, heatStep, slicePeriods, range52, safeHref, type Pt } from './format.ts'

test('fmtNumber: 천 단위·자릿수·빈 값·음의 0', () => {
  assert.equal(fmtNumber(6961.32, 2), '6,961.32')
  assert.equal(fmtNumber(1359.6, 1), '1,359.6')
  assert.equal(fmtNumber(182940), '182,940')
  assert.equal(fmtNumber(5.264, 2), '5.26')
  assert.equal(fmtNumber(-0.001, 2), '0.00')
  assert.equal(fmtNumber(-12.5, 1), '-12.5')
  assert.equal(fmtNumber(null), '—')
  assert.equal(fmtNumber(NaN, 2), '—')
})

test('fmtChange: 화살표 한 벌, 반올림 0 은 보합', () => {
  assert.equal(fmtChange(44.6, 0.65, 1), '▲ 44.6 (0.65%)')
  assert.equal(fmtChange(-44.6, -0.65, 1), '▼ 44.6 (0.65%)')
  assert.equal(fmtChange(0.004, 0.01, 2), '0.00 (0.01%)')
  assert.equal(fmtChange(1234.5, null, 1), '▲ 1,234.5')
  assert.equal(fmtChange(undefined, 1), '—')
  assert.equal(changeDir(0.004, 2), 'flat')   // 글자 0.00 이면 색도 보합
  assert.equal(changeDir(-0.006, 2), 'down')
})

test('changeFromPct: 등락률에서 변화량 복원', () => {
  // 전일 100 → 오늘 110 이면 등락률 10%, 변화량 10
  assert.ok(Math.abs(changeFromPct(110, 10) - 10) < 1e-9)
  assert.ok(Math.abs(changeFromPct(90, -10) + 10) < 1e-9)
})

test('asOfKind / asOfLabel: 네 갈래 판정', () => {
  const now = new Date('2026-10-01T15:50:00+09:00')
  assert.equal(asOfKind('2026-10-01T15:41:45+09:00', now), 'live')
  assert.equal(asOfLabel('live', '2026-10-01T15:41:45+09:00'), '15:41')
  assert.equal(asOfKind('2026-10-01T15:34:00+09:00', now), 'delayed')   // 16분 지남 — 기준 15분(묶음 liveMin)
  assert.equal(asOfKind('2026-10-01T14:00:00+09:00', now), 'delayed')
  assert.equal(asOfLabel('delayed', '2026-10-01T14:00:00+09:00'), '지연 14:00')
  assert.equal(asOfLabel('delayed', '2026-10-01', now), '지연 10/1')   // 묶음 stale + 날짜만 → 「지연 00:00」 이 아니다
  assert.equal(asOfKind('2026-09-30', now), 'prev')
  assert.equal(asOfLabel('prev', '2026-09-30', now), '전일 9/30')
  assert.equal(asOfLabel('prev', '2026-10-01T15:30:03+09:00', now), '종가 15:30')   // 오늘 장 마감 값
  assert.equal(asOfLabel('prev', '2026-10-01', now), '종가 10/1')                    // 오늘 날짜만 있는 값은 「전일」이 아니다
  assert.equal(asOfLabel('prev', '2026-Q2', now), '2분기')                            // 분기(GDP) — 「전일 4/1」이 아니다
  assert.equal(asOfLabel('prev', '2025-Q4', now), '25.4분기')
  assert.equal(asOfLabel('prev', '2025', now), '2025년')                              // 연간(중국 GDP)
  // 미국 날짜 9/30 23:00(UTC) = 한국 10/1 08:00 → 오늘 값이지만 오래됨
  assert.equal(asOfKind('2026-09-30T23:00:00Z', now), 'delayed')
  assert.equal(asOfKind('2026-10-01T15:41:45+09:00', now, { filled: true }), 'filled')
  assert.equal(asOfLabel('filled', 'x'), '보강')
  assert.equal(asOfLabel('prev', '2026-09', now), '9월')        // 월간 지표: 「전일 9/1」 이 아니다
  assert.equal(asOfLabel('prev', '2025-12', now), '25.12')
  assert.equal(asOfLabel('prev', 'JJA 2026', now), 'JJA 2026')  // 날짜가 아닌 기간 표기는 그대로
  assert.equal(asOfKind('엉터리', now), 'filled')
})

test('kindFromState: 묶음 상태 5종 → 배지 4갈래', () => {
  assert.equal(kindFromState('live'), 'live')
  assert.equal(kindFromState('prev'), 'prev')
  assert.equal(kindFromState('stale'), 'delayed')
  assert.equal(kindFromState('kept'), 'filled')
  assert.equal(kindFromState('missing'), null)
  assert.equal(kindFromState(undefined), undefined)   // 상태 없음 → 시각으로 직접 판정
  assert.equal(kindFromState('엉뚱'), undefined)
  // live 는 liveUntil 을 지나면 prev 로 내려간다
  const now = new Date('2026-10-01T10:20:00+09:00')
  assert.equal(kindFromState('live', '2026-10-01T10:30:00+09:00', now), 'live')
  assert.equal(kindFromState('live', '2026-10-01T10:15:00+09:00', now), 'prev')
  assert.equal(kindFromState('live', null, now), 'live')
  assert.equal(kindFromState('stale', '2026-10-01T10:15:00+09:00', now), 'delayed')   // liveUntil 은 live 에만
})

test('scaled: 화면 값 = 원본 ÷ scale', () => {
  assert.equal(scaled(65_400_000_000, 1e8), 654)          // 수출 → 억달러
  assert.equal(fmtNumber(scaled(9.1055, 0.01), 2), '910.55')  // 엔/원 → 100엔당 원
  assert.equal(scaled(5.26, undefined), 5.26)
  assert.equal(scaled(null, 1e8), null)
})

test('fmtPct · dayLabel · mdHm · shortDate: 표기 한 벌', () => {
  assert.equal(fmtPct(3.04), '▲ 3.04%')
  assert.equal(fmtPct(-0.254), '▼ 0.25%')
  assert.equal(fmtPct(-0.001), '0.00%')
  assert.equal(fmtPct(null), '—')
  assert.equal(dayLabel('2026-10-01'), '10월 1일 (목)')
  assert.equal(mdHm('2026-10-02T09:00:00+09:00'), '10/2 09:00')
  assert.equal(mdHm('2026-10-02'), '10/2')
  assert.equal(shortDate('2026-09-30'), '9/30')
  assert.equal(shortDate('2026-07'), '26.07')
  assert.equal(shortDate('JJA 2026'), 'JJA 2026')
})

test('heatStep: 경계 ±2.5 · ±1 · 0', () => {
  const cases: [number | null, number][] = [
    [3.27, 3], [2.5, 3], [2.49, 2], [1, 2], [0.99, 1], [0.004, 0], [0, 0], [-0.004, 0],
    [-0.06, -1], [-1, -2], [-2.49, -2], [-2.5, -3], [-3.27, -3], [null, 0], [NaN, 0],
  ]
  for (const [v, s] of cases) assert.equal(heatStep(v), s, `heatStep(${v})`)
})

test('slicePeriods · range52: 기간 칩과 52주 범위', () => {
  // 2025-10-01 ~ 2026-10-01 하루 한 점
  const daily: Pt[] = []
  for (let t = Date.UTC(2025, 9, 1); t <= Date.UTC(2026, 9, 1); t += 86_400_000) daily.push([new Date(t).toISOString().slice(0, 10), daily.length])
  const p = slicePeriods(daily)
  assert.deepEqual(Object.keys(p), ['1w', '3m', '1y'])
  assert.equal(p['1w']!.length, 7)                 // 9/25 ~ 10/1
  assert.equal(p['1w']![0][0], '2026-09-25')
  assert.equal(p['3m']![0][0], '2026-07-02')
  assert.equal(p['1y']![0][0], '2025-10-02')
  assert.deepEqual(range52(daily), { low: 1, high: 365 })
  // 3달짜리(원자재 65점)는 1년 칩이 3달과 같아 빠지고, 52주 범위도 없다
  const short = daily.slice(-65)
  assert.deepEqual(Object.keys(slicePeriods(short)), ['1w', '3m'])
  assert.equal(range52(short), null)
  // 월별 24점(성긴 시계열): 1주·3달은 만들지 않고 1년 12점 · 2년 24점. 전체는 2년과 같아 빠진다
  const monthly: Pt[] = []
  for (let i = 0; i < 24; i++) monthly.push([`${2024 + Math.floor((i + 9) / 12)}-${String((i + 9) % 12 + 1).padStart(2, '0')}`, i])
  assert.equal(monthly[monthly.length - 1][0], '2026-09')
  const mp = slicePeriods(monthly)
  assert.deepEqual(Object.keys(mp), ['1y', '2y'])
  assert.equal(mp['1y']!.length, 12)
  assert.equal(mp['2y']!.length, 24)
  // 월별 36점이면 「전체」가 2년 뒤에 선다
  const m36: Pt[] = []
  for (let i = 0; i < 36; i++) m36.push([`${2023 + Math.floor((i + 9) / 12)}-${String((i + 9) % 12 + 1).padStart(2, '0')}`, i])
  assert.deepEqual(Object.keys(slicePeriods(m36)), ['1y', '2y', 'all'])
  // 주별은 성긴 시계열이 아니다 — 3달 칩이 남는다
  assert.deepEqual(Object.keys(slicePeriods([['2026-09-01', 1], ['2026-09-08', 1], ['2026-09-15', 1], ['2026-09-22', 1]])), ['3m'])
  assert.deepEqual(slicePeriods([['2026-10-01', 1]]), {})
  assert.deepEqual(Object.keys(slicePeriods([['가', 1], ['나', 2]])), ['all'])   // 날짜를 못 읽으면 전체 하나
})

test('slicePeriods: 분기 라벨(2026Q2 · 2026-Q2)도 날짜로 읽는다', () => {
  const q: Pt[] = ['2025Q1', '2025Q2', '2025Q3', '2025Q4', '2026Q1', '2026Q2'].map((d, i): Pt => [d, i])
  const p = slicePeriods(q)
  assert.deepEqual(Object.keys(p), ['1y', '2y'])
  assert.deepEqual(p['1y']!.map(x => x[0]), ['2025Q3', '2025Q4', '2026Q1', '2026Q2'])   // 끝 분기 첫 달 4/1 에서 1년 거꾸로
  assert.equal(p['2y']!.length, 6)
  assert.deepEqual(slicePeriods([['2025-Q4', 1], ['2026-Q1', 2], ['2026-Q2', 3]])['1y']!.length, 3)
})

test('range52: 점 개수가 아니라 마지막 날짜에서 365일(월간 12개월)', () => {
  // 최근 3달만 촘촘하고 그 앞은 성긴 계열 — 1년 칩이 3달 칩보다 20% 많지 않아 빠지던 경우.
  // 종전엔 시계열 전체로 넘어가 3년 전 값(1000)이 52주 최고가 됐다.
  const pts: Pt[] = [['2023-01-02', 1000], ['2023-06-01', -500]]
  for (let m = 11; m <= 17; m++) pts.push([`${2025 + Math.floor((m - 1) / 12)}-${String((m - 1) % 12 + 1).padStart(2, '0')}-15`, 50])
  for (let t = Date.UTC(2026, 6, 1); t <= Date.UTC(2026, 9, 1); t += 86_400_000) pts.push([new Date(t).toISOString().slice(0, 10), pts.length])
  assert.equal(slicePeriods(pts)['1y'], undefined)
  const r = range52(pts)!
  assert.ok(r.high < 1000 && r.low > -500, JSON.stringify(r))
  // 월간 24점 → 끝 12개월(2025-10 ~ 2026-09)
  const monthly: Pt[] = []
  for (let i = 0; i < 24; i++) monthly.push([`${2024 + Math.floor((i + 9) / 12)}-${String((i + 9) % 12 + 1).padStart(2, '0')}`, i])
  assert.deepEqual(range52(monthly), { low: 12, high: 23 })
  // 결측이 많은 월간(두 달에 한 점) — 끝 12점은 2년이다. 12개월 안의 6점만 본다
  const gappy = monthly.filter((_, i) => i % 2 === 1)
  assert.equal(gappy.length, 12)
  assert.deepEqual(range52(gappy), { low: 13, high: 23 })
  // 윤년 끼인 일별: 끝 2024-03-01 에서 365일 전(2023-03-02)까지는 빼고 그다음 날부터
  const leap: Pt[] = [['2023-03-01', 99], ['2023-03-02', 98], ['2023-03-03', 5], ['2024-03-01', 7]]
  assert.deepEqual(range52(leap), { low: 5, high: 7 })
  // 윤년 끼인 월간: 2023-03 ~ 2024-03 13점이면 2023-03 은 빠지고 12개월
  const lm: Pt[] = Array.from({ length: 13 }, (_, i): Pt => [`${2023 + Math.floor((i + 2) / 12)}-${String((i + 2) % 12 + 1).padStart(2, '0')}`, i === 0 ? 99 : i])
  assert.equal(lm[12][0], '2024-03')
  assert.deepEqual(range52(lm), { low: 1, high: 12 })
})

test('safeHref: http/https 만 링크, 나머지는 null(글자만)', () => {
  assert.equal(safeHref('https://www.x.co.kr/a?b=1'), 'https://www.x.co.kr/a?b=1')
  assert.equal(safeHref(' HTTP://X.CO.KR/a '), 'http://x.co.kr/a')
  for (const bad of ['javascript:alert(1)', ' JavaScript:alert(1)', 'java	script:alert(1)', 'data:text/html,x', 'vbscript:x', '//x.co.kr/a', '/a', 'ftp://x/a', '', null, undefined, 3])
    assert.equal(safeHref(bad), null, String(bad))
})
