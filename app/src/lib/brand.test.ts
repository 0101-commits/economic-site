// 자가검사: npm test --prefix app — 로고 경로 자료(색 하드코딩 없음 · 보기 상자)
// 도형이 보기 상자를 넘지 않는지는 계산이 어려워 scripts/brand/check_logo.mjs(원본 겹침 1% 미만)가 본다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { BRAND } from './brand.ts'

const VB = { mark: '0 0 102 148', word: '0 0 250 66', logo: '0 0 381 148', lockup: '0 0 376 132' } as const

for (const k of ['mark', 'word', 'logo', 'lockup'] as const) {
  test(`BRAND.${k}: 보기 상자 · 경로`, () => {
    assert.equal(BRAND[k].viewBox, VB[k])
    assert.ok(BRAND[k].d.length > 100)
  })
}
test('BRAND: 하드코딩 색 없음', () => {
  assert.doesNotMatch(JSON.stringify(BRAND), /#[0-9a-f]{6}/i)
})
test('BRAND.lockup · word: 점 좌표가 보기 상자 안(여백 허용 3)', () => {
  for (const k of ['lockup', 'word'] as const) {
    const [, , w, h] = BRAND[k].viewBox.split(' ').map(Number)
    const n = (BRAND[k].d.match(/-?\d+\.?\d*/g) ?? []).map(Number)
    for (let i = 0; i < n.length; i += 2) {
      assert.ok(n[i] >= -3 && n[i] <= w + 3, `${k} x ${n[i]}`)
      assert.ok(n[i + 1] >= -3 && n[i + 1] <= h + 3, `${k} y ${n[i + 1]}`)
    }
  }
})
test('BRAND.lockup: 도형 수(마크 1 + 글자 4 + 구멍 1) 와 태그라인 없음', () => {
  assert.equal((BRAND.lockup.d.match(/M/g) ?? []).length, 6)
  assert.equal((BRAND.word.d.match(/M/g) ?? []).length, 5)
})
