// 자가검사: npm test --prefix app — 로고 경로 자료(색 하드코딩 없음 · 보기 상자)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { BRAND } from './brand.ts'

const VB = { mark: '0 0 102 148', word: '0 0 252 64', logo: '0 0 381 148' } as const

for (const k of ['mark', 'word', 'logo'] as const) {
  test(`BRAND.${k}: 보기 상자 · 경로`, () => {
    assert.equal(BRAND[k].viewBox, VB[k])
    assert.ok(BRAND[k].d.length > 100)
  })
}
test('BRAND: 하드코딩 색 없음', () => {
  assert.doesNotMatch(JSON.stringify(BRAND), /#[0-9a-f]{6}/i)
})
