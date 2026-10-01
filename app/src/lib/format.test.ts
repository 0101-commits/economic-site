// 자가검사: npm test --prefix app  (node --test, 추가 도구 없음)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fmtNumber, fmtChange, changeDir, changeFromPct, asOfKind, asOfLabel, kindFromState } from './format.ts'

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
  assert.equal(asOfKind('2026-10-01T14:00:00+09:00', now), 'delayed')
  assert.equal(asOfLabel('delayed', '2026-10-01T14:00:00+09:00'), '지연 14:00')
  assert.equal(asOfKind('2026-09-30', now), 'prev')
  assert.equal(asOfLabel('prev', '2026-09-30', now), '전일 9/30')
  assert.equal(asOfLabel('prev', '2026-10-01T15:30:03+09:00', now), '종가 15:30')   // 오늘 장 마감 값
  // 미국 날짜 9/30 23:00(UTC) = 한국 10/1 08:00 → 오늘 값이지만 오래됨
  assert.equal(asOfKind('2026-09-30T23:00:00Z', now), 'delayed')
  assert.equal(asOfKind('2026-10-01T15:41:45+09:00', now, { filled: true }), 'filled')
  assert.equal(asOfLabel('filled', 'x'), '보강')
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
})
