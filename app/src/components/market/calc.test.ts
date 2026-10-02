// 자가검사: node --test src/components/market/calc.test.ts (app 폴더에서)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { monthIndex, yearAgo, yoySeries, rebase, alignDates, cumsum, rollSum, weekKey, groupFlows, column, spans, type FlowRow } from './calc.ts'
import type { Pt } from '../../lib/format.ts'

test('monthIndex: 월·일·분기', () => {
  assert.equal(monthIndex('2026-08'), 2026 * 12 + 7)
  assert.equal(monthIndex('2026-08-01'), 2026 * 12 + 7)
  assert.equal(monthIndex('2026Q2'), 2026 * 12 + 3)
  assert.equal(monthIndex('JJA 2026'), null)
})

test('yearAgo · yoySeries: 정확히 12달 앞만 쓴다(빠진 달은 건너뜀)', () => {
  const s: Pt[] = [['2025-08', 116.45], ['2025-09', 117.06], ['2026-08', 120.05]]
  assert.equal(yearAgo(s), 116.45)
  assert.equal(yearAgo([['2026-08', 1], ['2025-07', 2]]), null)
  const y = yoySeries(s)
  assert.equal(y.length, 1)
  assert.equal(y[0][0], '2026-08')
  assert.equal(y[0][1].toFixed(2), '3.09')   // 묶음 cpi_kr_yoy 3.09 와 같은 값
  assert.deepEqual(yoySeries([['2026Q2', 110], ['2025Q2', 100]]).map(p => p[0]), ['2026Q2'])
})

test('rebase · cumsum · rollSum', () => {
  assert.deepEqual(rebase([['a', 50], ['b', 75]]), [['a', 100], ['b', 150]])
  assert.deepEqual(rebase([['a', 0], ['b', 5]]), [['a', 0], ['b', 5]])
  assert.deepEqual(cumsum([['a', 1], ['b', -3], ['c', 5]]), [['a', 1], ['b', -2], ['c', 3]])
  assert.deepEqual(rollSum([['a', 1], ['b', 2], ['c', 3], ['d', 4]], 3), [['c', 6], ['d', 9]])
})

test('weekKey · groupFlows: 월요일로 묶고 빈 값은 더하지 않는다', () => {
  assert.equal(weekKey('2026-10-01'), '2026-09-28')   // 목 → 그 주 월
  assert.equal(weekKey('2026-09-28'), '2026-09-28')
  assert.equal(weekKey('2026-10-04'), '2026-09-28')   // 일요일은 앞 주
  const rows: FlowRow[] = [['2026-09-29', 10, -5, null], ['2026-10-01', 2, 1, null], ['2026-10-05', 1, 1, 1]]
  assert.deepEqual(groupFlows(rows, 'week'), [['2026-09-28', 12, -4, null], ['2026-10-05', 1, 1, 1]])
  assert.deepEqual(groupFlows(rows, 'month'), [['2026-09', 10, -5, null], ['2026-10', 3, 2, 1]])
})

test('column: 숫자 칸만 시계열로', () => {
  assert.deepEqual(column([['d1', 1, null], ['d2', null, 2]], 1), [['d1', 1]])
})

test('spans: 6+6 다음 끝 줄은 남은 칸을 채운다', () => {
  assert.deepEqual(spans(1, 3), [12])
  assert.deepEqual(spans(2, 3), [6, 6])
  assert.deepEqual(spans(5, 3), [6, 6, 4, 4, 4])
  assert.deepEqual(spans(6, 3), [6, 6, 4, 4, 4, 12])
  assert.deepEqual(spans(7, 3), [6, 6, 4, 4, 4, 6, 6])
  assert.deepEqual(spans(5, 2), [6, 6, 6, 6, 12])
  for (const n of [3, 4, 8, 9]) for (const per of [2, 3] as const) {
    const s = spans(n, per).slice(2)
    let row = 0
    for (const x of s) { row += x; if (row === 12) row = 0 }
    assert.equal(row, 0, `n=${n} per=${per}`)
  }
})

// 성긴 시계열(월별·분기) 판정은 format.ts slicePeriods 로 옮겼다 — 검사도 format.test.ts 에 있다.

test('alignDates: 모두에 있는 날짜만 남긴다(길이·시작이 다른 시도·전국 시계열)', () => {
  const a: Pt[] = [['2023-09', 1], ['2024-09', 2], ['2025-09', 3]]
  const b: Pt[] = [['2024-09', 20], ['2025-09', 30]]
  assert.deepEqual(alignDates([a, b]), [[['2024-09', 2], ['2025-09', 3]], [['2024-09', 20], ['2025-09', 30]]])
  assert.deepEqual(alignDates([a, []]), [[], []])
  assert.deepEqual(alignDates([]), [])
})
