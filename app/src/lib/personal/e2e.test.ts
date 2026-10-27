// 자가검사: npm test --prefix app — 보유 암호 덩어리 왕복 · 현행 화면(js/app2.js)과 양방향 호환 · 어느 쪽을 쓸지 · 받기 뒤 지문
// · 보유 열쇠 재료(D9 a) 결정성 · 예전 암호 사본 이전 판정. 어느 쪽을 남길지는 syncRules.test.ts · holdSync.test.ts.
// 현행 쪽 코드는 js/app2.js pfBuildEncHoldings · pfApplyEncHoldings 를 줄여 옮긴 것이다(가짜 자료만 쓴다).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { pbkdf2Sync } from 'node:crypto'
import { applyEntries, decrypt, decryptAs, encrypt, entriesOf, fingerprint, holdKeyOf, ITER, openBlob, relockBlob, type EncBlob, type Entry } from './e2e.ts'

const PASS = 'test-pass-1234'
const noName = (es: Entry[]): Entry[] => es.map(({ n: _n, ...e }) => e)
type Row = { id: string; symbol: string; market: string; name: string; avg: number | null; qty: number | null; fxBuy?: number | null }
const items: Row[] = [
  { id: 'i1', symbol: '005930', market: 'KR', name: '가짜 A', avg: 70000, qty: 10, fxBuy: null },
  { id: 'i2', symbol: 'AAPL', market: 'US', name: '가짜 B', avg: 180.5, qty: 2.5, fxBuy: 1350 },
  { id: 'i3', symbol: '000660', market: 'KR', name: '관심만', avg: null, qty: null },
]

// ── 현행 화면 방식(그대로 옮김) ──
const b64 = (u: Uint8Array) => btoa(String.fromCharCode(...u))
const unb64 = (s: string) => Uint8Array.from(atob(s), c => c.charCodeAt(0))
async function legacyKey(pass: string, salt: Uint8Array<ArrayBuffer>) {
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveKey'])
  return crypto.subtle.deriveKey({ name: 'PBKDF2', salt, iterations: 600000, hash: 'SHA-256' }, base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
}
async function legacyBuild(its: typeof items, pass: string) {
  const map = its.filter(it => it.avg != null || it.qty != null)
    .map(it => ({ s: it.symbol, m: it.market === 'US' ? 'US' : 'KR', a: it.avg ?? null, q: it.qty ?? null, fx: it.fxBuy ?? null }))
  const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12))
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await legacyKey(pass, salt), new TextEncoder().encode(JSON.stringify(map)))
  return { alg: 'AES-256-GCM', kdf: 'PBKDF2-SHA256', iter: 600000, salt: b64(salt), iv: b64(iv), ciphertext: b64(new Uint8Array(ct)) } as EncBlob
}
/** 현행 pfApplyEncHoldings 의 풀기 + 적용 개수 세기(s 없는 칸은 건너뛴다). */
async function legacyApply(blob: EncBlob, pass: string, its: typeof items) {
  const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64(blob.iv) }, await legacyKey(pass, unb64(blob.salt)), unb64(blob.ciphertext))
  const map = JSON.parse(new TextDecoder().decode(pt))
  assert.ok(Array.isArray(map))
  let applied = 0
  map.forEach((h: { s?: string; m?: string }) => {
    if (!h || !h.s) return
    if (its.find(it => it.symbol === h.s && it.market === (h.m === 'US' ? 'US' : 'KR'))) applied++
  })
  return applied
}
/** Worker _sanitizeEncHoldings 가 받는 모양인지. */
const workerAccepts = (b: EncBlob) => b.alg === 'AES-256-GCM' && b.kdf === 'PBKDF2-SHA256' && Number.isInteger(b.iter) && b.iter >= 1 && b.iter <= 2000000 &&
  [b.salt, b.iv, b.ciphertext].every(s => typeof s === 'string' && s.length >= 1 && s.length <= 60000 && /^[A-Za-z0-9+/=]+$/.test(s))

test('왕복: 올린 칸과 시각이 그대로 · 다른 암호는 wrong-pass', async () => {
  const es = entriesOf(items)
  assert.equal(es.length, 2)
  const blob = await encrypt(es, PASS, '2026-10-02T05:00:00.000Z')
  assert.equal(blob.iter, ITER)
  assert.deepEqual(await decrypt(blob, PASS), { entries: es, at: '2026-10-02T05:00:00.000Z' })
  await assert.rejects(decrypt(blob, PASS + 'x'), /wrong-pass/)
  const again = await encrypt(es, PASS, '2026-10-02T05:00:00.000Z')
  assert.notEqual(again.salt, blob.salt)   // 올릴 때마다 salt·iv 새로
  assert.notEqual(again.iv, blob.iv)
})

test('현행 화면이 만든 덩어리를 새 화면이 푼다(올린 시각은 모름)', async () => {
  const blob = await legacyBuild(items, PASS)
  const { entries, at } = await decrypt(blob, PASS)
  assert.equal(at, null)
  assert.deepEqual(entries, noName(entriesOf(items)))   // 현행 화면 덩어리엔 이름(n)이 없다
})

test('새 화면이 만든 덩어리를 현행 방식으로 푼다 · Worker 가 받는 모양', async () => {
  const blob = await encrypt(entriesOf(items), PASS, '2026-10-02T05:00:00.000Z')
  assert.ok(workerAccepts(blob))
  assert.deepEqual(Object.keys(blob).sort(), ['alg', 'ciphertext', 'iter', 'iv', 'kdf', 'salt'])
  assert.equal(await legacyApply(blob, PASS, items), 2)   // 시각 칸 { t } 는 현행이 건너뛴다
})

test('받기: 서버 값으로 바꾸고 · 없는 종목은 비우고 · 새 종목은 더한다 → 지문이 서버와 같다', async () => {
  const server: Entry[] = [{ s: 'AAPL', m: 'US', a: 190, q: 3, fx: 1380 }, { s: '035420', m: 'KR', a: 200000, q: 1, fx: null }]
  const out = applyEntries(items, server, e => ({ id: 'n', symbol: e.s, market: e.m, name: e.s, avg: e.a, qty: e.q, fxBuy: e.fx }))
  assert.deepEqual(out.map(it => [it.symbol, it.avg, it.qty]), [['005930', null, null], ['AAPL', 190, 3], ['000660', null, null], ['035420', 200000, 1]])
  assert.equal(out[0].name, '가짜 A')   // 줄과 다른 칸은 그대로
  assert.equal(await fingerprint(entriesOf(out)), await fingerprint(server))
  assert.equal(await fingerprint([...server].reverse()), await fingerprint(server))
})

test('끝 공백 암호: 현행이 친 그대로 잠근 덩어리는 원문으로 · 공백 없이 잠근 덩어리는 공백 뺀 값으로 푼다', async () => {
  const raw = await legacyBuild(items, 'pass-1234 ')   // 현행 설정 경로는 공백을 빼지 않고 저장한다
  const a = await decryptAs(raw, 'pass-1234 ')
  assert.equal(a.pass, 'pass-1234 ')                  // 올릴 때 이 문자열을 그대로 써야 다른 기기가 푼다
  assert.deepEqual(a.entries, noName(entriesOf(items)))
  const trimmed = await legacyBuild(items, 'pass-1234')
  assert.equal((await decryptAs(trimmed, ' pass-1234 ')).pass, 'pass-1234')
  await assert.rejects(decryptAs(trimmed, 'other-pass '), /wrong-pass/)
})

test('holdKeyOf: 앱키는 대소문자 · 공백 · 하이픈이 달라도 같은 재료', async () => {
  assert.equal(await holdKeyOf('ecom-7kq3-px9m-2hta'), await holdKeyOf('ECOM-7KQ3-PX9M-2HTA'))
  assert.equal(await holdKeyOf(' ecom 7kq3 px9m 2hta '), await holdKeyOf('ECOM-7KQ3-PX9M-2HTA'))
})

test('holdKeyOf: 같은 키 → 같은 재료(앞뒤 공백 무시) · 다른 키 → 다름 · 명세 그대로 PBKDF2-SHA256(키, "ecom-holdings-v1", 600000) 32바이트 hex', async () => {
  const a = await holdKeyOf('my-sync-key-123')
  assert.match(a, /^[0-9a-f]{64}$/)
  assert.equal(await holdKeyOf('  my-sync-key-123\n'), a)
  assert.notEqual(await holdKeyOf('my-sync-key-124'), a)
  assert.equal(a, pbkdf2Sync('my-sync-key-123', 'ecom-holdings-v1', 600000, 32, 'sha256').toString('hex'))
})

test('openBlob: 재료로 잠근 것은 그대로 · 예전 암호 사본은 old-pass → 예전 암호 · 예전 키 재료로 풀리면 stale · 틀리면 wrong-pass', async () => {
  const mat = await holdKeyOf('new-sync-key-123')
  const es = entriesOf(items)
  const fresh = await encrypt(es, mat, '2026-10-07T01:00:00.000Z')
  assert.deepEqual(await openBlob(fresh, mat), { entries: es, at: '2026-10-07T01:00:00.000Z', stale: false })
  const legacy = await legacyBuild(items, PASS)                       // 이전 전: 사람이 정한 보유 암호로 잠근 사본
  await assert.rejects(openBlob(legacy, mat), /old-pass/)
  await assert.rejects(openBlob(legacy, mat, '   '), /old-pass/)      // 빈 칸은 물은 것으로 치지 않는다
  assert.deepEqual(await openBlob(legacy, mat, ` ${PASS} `), { entries: noName(es), at: null, stale: true })
  await assert.rejects(openBlob(legacy, mat, 'other-pass'), /wrong-pass/)
  const oldKeyed = await encrypt(es, await holdKeyOf('old-sync-key-99'), 't')   // 키를 바꾼 뒤 다시 잠그기가 실패해 남은 사본
  assert.equal((await openBlob(oldKeyed, mat, 'old-sync-key-99')).stale, true)
})

test('relockBlob: 서버를 확인 못 하면 false(키 바꾸기 멈춤) · 사본 없음 null · 옛 재료 사본은 새 재료로 · 안 풀리면 null', async () => {
  const [old, mat] = await Promise.all([holdKeyOf('old-sync-key-99'), holdKeyOf('new-sync-key-123')])
  const es = entriesOf(items)
  assert.equal(await relockBlob({ ok: false }, old, mat), false)                 // 429 · 네트워크 실패
  assert.equal(await relockBlob({ ok: true, enc: null }, old, mat), null)
  const moved = await relockBlob({ ok: true, enc: await encrypt(es, old, '2026-10-07T01:00:00.000Z') }, old, mat)
  assert.ok(moved)
  assert.deepEqual(await decrypt(moved, mat), { entries: es, at: '2026-10-07T01:00:00.000Z' })
  assert.equal(await relockBlob({ ok: true, enc: await legacyBuild(items, PASS) }, old, mat), null)   // 예전 암호 사본은 이전이 맡는다
})
