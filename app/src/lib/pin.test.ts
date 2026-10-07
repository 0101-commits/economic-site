// 자가검사: npm test --prefix app — PIN 실패 대기(5~9번째 30초 · 10번째부터 5분) · 맞히면 초기화 · PIN 잊음
import { test, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { checkPin, clearPin, failDelay, hasPin, isUnlocked, readFail, samePin, setPin, waitMs } from './pin.ts'

/** localStorage · sessionStorage 모의 — 시험마다 비운다. */
function fakeStorage() {
  const m = new Map<string, string>()
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, String(v)) }, removeItem: (k: string) => { m.delete(k) } }
}
const g = globalThis as Record<string, unknown>
beforeEach(() => { g.localStorage = fakeStorage(); g.sessionStorage = fakeStorage() })

const PIN = String(Math.floor(Math.random() * 900_000) + 100_000)   // 시험마다 다른 6자리 — 고정 PIN 을 코드에 남기지 않는다
const WRONG = PIN === '000000' ? '111111' : '000000'

/** 반복 1,000회짜리 PIN 기록 — 저장된 iter 를 그대로 쓰므로 판정은 같고, 600,000회로 시험마다 걸던 수 초를 던다. */
async function fastPin(pin: string) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(pin), 'PBKDF2', false, ['deriveBits'])
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', salt: new Uint8Array(16), iterations: 1000, hash: 'SHA-256' }, key, 256)
  localStorage.setItem('econLockPin_v2', JSON.stringify({ salt: '00'.repeat(16), iter: 1000, hash: Buffer.from(bits).toString('hex') }))
}

test('failDelay: 1~4번 0 · 5~9번 30초 · 10번부터 5분', () => {
  assert.deepEqual([1, 4, 5, 9, 10, 11, 25].map(failDelay), [0, 0, 30_000, 30_000, 300_000, 300_000, 300_000])
})

test('checkPin: 5번 틀리면 30초 동안 맞는 PIN 도 받지 않고, 지나면 맞혀서 초기화', async () => {
  await fastPin(PIN)
  const t0 = 1_000_000
  for (let i = 1; i <= 4; i++) { assert.equal(await checkPin(WRONG, t0), false); assert.equal(waitMs(t0), 0) }
  assert.equal(await checkPin(WRONG, t0), false)
  assert.deepEqual(readFail(), { n: 5, until: t0 + 30_000 })
  assert.equal(waitMs(t0 + 1_000), 29_000)
  sessionStorage.removeItem('econLockOk_v1')
  assert.equal(await checkPin(PIN, t0 + 29_999), false, '기다리는 중엔 맞아도 안 열린다')
  assert.equal(readFail().n, 5, '기다리는 중의 시도는 셈하지 않는다')
  assert.equal(await checkPin(PIN, t0 + 30_000), true)
  assert.deepEqual(readFail(), { n: 0, until: 0 })
  assert.equal(isUnlocked(), true)
})

test('checkPin: 10번째부터는 실패마다 5분', async () => {
  await fastPin(PIN)
  let t = 0
  for (let i = 1; i <= 12; i++) {
    t += 10 * 60_000   // 앞 대기는 지난 뒤
    assert.equal(await checkPin(WRONG, t), false)
    assert.equal(waitMs(t), failDelay(i), `${i}번째`)
  }
})

test('samePin: 견주기만 — 틀려도 셈하지 않고 맞아도 열지 않는다(보유 암호 검사용)', async () => {
  await fastPin(PIN)
  sessionStorage.removeItem('econLockOk_v1')
  for (let i = 0; i < 6; i++) assert.equal(await samePin(WRONG), false)
  assert.equal(readFail().n, 0)
  assert.equal(await samePin(PIN), true)
  assert.equal(isUnlocked(), false)
})

test('clearPin: PIN · 실패 셈 · 해제 표시를 지운다', async () => {
  await setPin(PIN)
  for (let i = 0; i < 5; i++) await checkPin(WRONG, 0)
  clearPin()
  assert.equal(hasPin(), false)
  assert.deepEqual(readFail(), { n: 0, until: 0 })
  assert.equal(isUnlocked(), false)
})

test('readFail: 깨진 값 · 저장소 막힘 = 실패 없음', () => {
  localStorage.setItem('econLockFail_v1', '{깨짐')
  assert.deepEqual(readFail(), { n: 0, until: 0 })
  g.localStorage = { getItem: () => { throw new Error('blocked') } }
  assert.deepEqual(readFail(), { n: 0, until: 0 })
})
