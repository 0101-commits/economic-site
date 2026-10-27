// 자가검사: npm test --prefix app — 입장 뒤 돌아갈 곳(앱 안 경로만)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { safeNext } from './welcome.ts'

test('safeNext: 앱 경로만 통과', () => {
  assert.equal(safeNext('/my'), '/my')
  assert.equal(safeNext('/market?a=kr&v=halts'), '/market?a=kr&v=halts')
  assert.equal(safeNext('/'), '/')
})
test('safeNext: 바깥 주소 · 빈 값은 /', () => {
  assert.equal(safeNext('https://evil.example'), '/')
  assert.equal(safeNext('//x'), '/')
  assert.equal(safeNext('/\\x'), '/')
  assert.equal(safeNext('javascript:alert(1)'), '/')
  assert.equal(safeNext(null), '/')
  assert.equal(safeNext(''), '/')
})
test('safeNext: 입장 화면으로 되돌리지 않는다', () => {
  assert.equal(safeNext('/welcome'), '/')
  assert.equal(safeNext('/welcome?next=/my'), '/')
})
