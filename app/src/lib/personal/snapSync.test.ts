// 자가검사: npm test --prefix app — 스냅샷 서버 맞춤(snapSync.ts). 가짜 서버 · 가짜 저장소, 암호는 진짜(e2e.ts).
// 받아 합침 · 기기에만 있는 날짜 올림 · 이미 같으면 올리지 않음 · 예비 앱키 · 보유 열쇠 없음은 받지도 올리지도 않음 · 못 푸는 서버 판은 덮지 않음.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { decryptJson, encryptJson, type EncBlob } from './e2e.ts'
import { makeSnapSync, type SnapDeps, type SnapRec } from './snapSync.ts'
import { snapPlain, type Snap } from './snapRules.ts'

const MAT = 'a'.repeat(64), OTHER = 'b'.repeat(64), HASH = 'c'.repeat(64)
const s = (d: string, ev: number, src?: 'close' | 'app'): Snap => ({ d, ev, ct: 1000, ...(src ? { src } : {}) })

function rig(local: Snap[], server: EncBlob | null, o: { mat?: string | null; backup?: boolean; hash?: string | null } = {}) {
  const st = { local, rec: {} as SnapRec, enc: server, gets: 0, puts: [] as EncBlob[], writes: 0 }
  const deps: SnapDeps = {
    hash: () => (o.hash === undefined ? HASH : o.hash), mat: () => (o.mat === undefined ? MAT : o.mat), backup: () => !!o.backup,
    get: async () => { st.gets++; return { ok: true, status: 200, enc: st.enc } },
    put: async (_h, e) => { st.puts.push(e); st.enc = e; return { ok: true, status: 200 } },
    read: () => st.local, write: a => { st.local = a; st.writes++; return true },
    readRec: () => st.rec, writeRec: r => { st.rec = r },
    now: () => Date.parse('2026-10-28T00:00:00Z'),
  }
  return { st, sync: makeSnapSync(deps) }
}
const lock = (snaps: Snap[], mat = MAT) => encryptJson(snapPlain(snaps, '2026-10-27T00:00:00.000Z'), mat)

test('서버에 없으면 이 기기 것을 올린다 — Part A 평문 모양으로 보유 열쇠로 잠가', async () => {
  const { st, sync } = rig([s('2026-10-01', 1, 'app')], null)
  const r = await sync.run()
  assert.equal(r.pushed, true)
  assert.equal(st.puts.length, 1)
  assert.deepEqual(Object.keys(st.puts[0]).sort(), ['alg', 'ciphertext', 'iter', 'iv', 'kdf', 'salt'])
  const plain = await decryptJson(st.puts[0], MAT) as { v: number; at: string; snaps: Snap[] }
  assert.equal(plain.v, 1)
  assert.deepEqual(plain.snaps, [s('2026-10-01', 1, 'app')])
})

test('서버에만 있는 날짜는 받아 합친다(작업 close 가 이 기기 app 을 이김) — 올릴 것이 없으면 올리지 않는다', async () => {
  const { st, sync } = rig([s('2026-10-01', 1, 'app')], await lock([s('2026-10-01', 9, 'close'), s('2026-10-02', 2, 'close')]))
  const r = await sync.run()
  assert.equal(r.pulled, true)
  assert.equal(r.pushed, false)
  assert.equal(st.puts.length, 0)
  assert.deepEqual(st.local, [s('2026-10-01', 9, 'close'), s('2026-10-02', 2, 'close')])
})

test('양쪽에 서로 없는 날짜가 있으면 합쳐 이 기기에 쓰고 합친 것을 올린다', async () => {
  const { st, sync } = rig([s('2026-10-03', 3, 'app')], await lock([s('2026-10-01', 1, 'close')]))
  const r = await sync.run()
  assert.equal(r.pulled, true)
  assert.equal(r.pushed, true)
  const plain = await decryptJson(st.puts[0], MAT) as { snaps: Snap[] }
  assert.deepEqual(plain.snaps.map(x => x.d), ['2026-10-01', '2026-10-03'])
  assert.deepEqual(st.local.map(x => x.d), ['2026-10-01', '2026-10-03'])
})

test('이미 같으면 올리지 않는다 · 맞춘 뒤 같은 판이면 풀지 않고 받기만 한다', async () => {
  const { st, sync } = rig([s('2026-10-01', 1, 'close')], await lock([s('2026-10-01', 1, 'close')]))
  const a = await sync.run()
  assert.equal(a.pushed, false)
  assert.equal(a.pulled, false)
  assert.equal(st.puts.length, 0)
  const gets = st.gets
  const b = await sync.run()                                       // 같은 암호문 + 같은 기기 값 → 풀지 않고 끝
  assert.equal(st.gets, gets + 1)
  assert.equal(b.pushed, false)
  assert.equal(st.puts.length, 0)
})

test('예비 앱키 세션: 받지도 올리지도 않는다(요청 자체가 없다)', async () => {
  const { st, sync } = rig([s('2026-10-01', 1, 'app')], null, { backup: true })
  const r = await sync.run()
  assert.equal(st.gets, 0)
  assert.equal(st.puts.length, 0)
  assert.equal(r.pushed, false)
  assert.equal(r.pulled, false)
})

test('보유 열쇠가 없거나 앱키 해시가 없으면 요청 없음', async () => {
  const a = rig([s('2026-10-01', 1, 'app')], null, { mat: null })
  await a.sync.run()
  assert.equal(a.st.gets, 0)
  assert.equal(a.st.puts.length, 0)
  const b = rig([s('2026-10-01', 1, 'app')], null, { hash: null })
  await b.sync.run()
  assert.equal(b.st.gets, 0)
  assert.equal(b.st.puts.length, 0)
})

test('서버 판을 못 풀면(다른 열쇠) 덮지 않는다 — 올리지 않고 이 기기 것도 그대로', async () => {
  const other = await lock([s('2026-10-01', 7, 'close')], OTHER)
  const { st, sync } = rig([s('2026-10-02', 2, 'app')], other)
  const r = await sync.run()
  assert.equal(st.puts.length, 0)
  assert.equal(r.pushed, false)
  assert.equal(st.enc, other)
  assert.deepEqual(st.local, [s('2026-10-02', 2, 'app')])
})

test('이 기기도 서버도 비었으면 아무것도 하지 않는다', async () => {
  const { st, sync } = rig([], null)
  await sync.run()
  assert.equal(st.puts.length, 0)
  assert.equal(st.writes, 0)
})
