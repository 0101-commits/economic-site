// 자가검사: npm test --prefix app — 입장 뒤 돌아갈 곳(앱 안 경로만) · 입장 관문(멈춤 · 끊김) · 입장 화면 첫 줄
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { gateRedirect, safeNext, welcomeAway, whyText } from './welcome.ts'

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

test('whyText: why → 입장 화면 첫 줄', () => {
  assert.equal(whyText('paused'), '멈춘 앱키입니다. 모임 운영자에게 문의해 주세요.')
  assert.equal(whyText('lost'), '앱키가 바뀌었거나 지워졌습니다. 운영자에게 새 앱키를 받으세요')
  assert.equal(whyText(null), '')
  assert.equal(whyText('x'), '')
})

test('gateRedirect: 키 없음 → 입장 화면(401 로 끊겼으면 why=lost) · 멈춤 → why=paused · 들어와 있음 → 그대로', () => {
  const base = { path: '/my', query: '?v=1', hash: true, paused: false, lost: false }
  assert.equal(gateRedirect(base), null)
  assert.equal(gateRedirect({ ...base, hash: false }), '/welcome?next=%2Fmy%3Fv%3D1')
  assert.equal(gateRedirect({ ...base, hash: false, lost: true }), '/welcome?why=lost&next=%2Fmy%3Fv%3D1')
  assert.equal(gateRedirect({ ...base, paused: true }), '/welcome?why=paused&next=%2Fmy%3Fv%3D1')
  assert.equal(gateRedirect({ ...base, path: '/welcome', hash: false, lost: true }), null, '입장 화면 자신은 막지 않는다')
  assert.equal(gateRedirect({ ...base, path: '/welcome', paused: true }), null)
})

test('welcomeAway: 들어와 있는 기기는 입장 화면 대신 홈 — 멈춘 사람은 입장 화면에 남는다', () => {
  assert.equal(welcomeAway({ hash: true, paused: false }), true)
  assert.equal(welcomeAway({ hash: true, paused: true }), false)
  assert.equal(welcomeAway({ hash: false, paused: false }), false)
})
