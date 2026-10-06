// 자가검사: npm test --prefix app — 헤더 벨 안 읽음 점 판정
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { hasUnseen, latestTs } from './alertsSeen.ts'

const row = (ts: unknown) => ({ key: 'x', ts })
const SEEN = '2026-10-05T09:00:00.000Z'

test('hasUnseen: 가장 늦은 ts 가 마지막으로 본 때보다 뒤일 때만 점', () => {
  assert.equal(hasUnseen([row('2026-10-05T09:00:01.000Z')], SEEN), true)
  assert.equal(hasUnseen([row('2026-10-05T09:00:00.000Z')], SEEN), false)             // 같은 때 = 본 것
  assert.equal(hasUnseen([row('2026-10-05T08:59:59.000Z'), row('2026-10-01T00:00:00+09:00')], SEEN), false)
  assert.equal(hasUnseen([row('2026-10-01T00:00:00+09:00'), row('2026-10-05T18:05:12+09:00')], SEEN), true)   // 가장 늦은 행이 기준
})

test('hasUnseen: 한국 시각(+09:00)과 UTC 를 같은 시각으로 견준다', () => {
  assert.equal(hasUnseen([row('2026-10-05T18:00:00+09:00')], SEEN), false)   // = 09:00Z
  assert.equal(hasUnseen([row('2026-10-05T18:00:01+09:00')], SEEN), true)
})

test('hasUnseen: 본 적 없으면(없음·깨짐) 행이 있을 때만 점', () => {
  assert.equal(hasUnseen([row('2026-10-05T09:00:00Z')], null), true)
  assert.equal(hasUnseen([row('2026-10-05T09:00:00Z')], '깨진 값'), true)
  assert.equal(hasUnseen([], null), false)
})

test('hasUnseen: 못 받았거나 모양이 다르면 점 없음(조용히)', () => {
  for (const rows of [null, undefined, {}, 'x', 404, [], [null], [{}], [row('언제')], [row(null)]]) assert.equal(hasUnseen(rows, null), false)
})

test('latestTs: 밀리초 숫자도 받는다', () => {
  assert.equal(latestTs([row(1000), row(5000), row(3000)]), 5000)
  assert.equal(latestTs('x'), 0)
})
