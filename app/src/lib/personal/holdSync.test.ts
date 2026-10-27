// 자가검사: npm test --prefix app — 보유 저절로 맞춤(holdSync.ts). 가짜 서버 · 가짜 저장소, 암호는 진짜(e2e.ts).
// 새 입장 서버 우선 · 서버 비면 올림 · 둘 다 바뀌면 나중 것 + 진 쪽 portfolioV1:prev · 옛 hold:false 무시 · 예비 앱키는 덮어쓰지 않음
// · 이름을 고치면 한 번 올림 · 이미 들어와 있던 기기(옛 기록)가 옛 판으로 새 판을 덮지 않음 · 옛 형식 덩어리.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { decrypt, encrypt, entriesOf, fingerprint, type EncBlob, type Entry } from './e2e.ts'
import { HOLD_TEXT, makeHoldSync, noteHoldEdit, noteHoldNames, readHoldRec, resetHoldRec, type HoldDeps } from './holdSync.ts'
import { read, readPortfolio, writePortfolio } from './scoped.ts'
import { setPendingPerson } from './who.ts'
import type { Holding } from './calc.ts'

const store = new Map<string, string>(), sess = new Map<string, string>()
const fakeStorage = (m: Map<string, string>) => ({ getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v) }, removeItem: (k: string) => { m.delete(k) },
  get length() { return m.size }, key: (i: number) => [...m.keys()][i] ?? null })
Object.assign(globalThis, { localStorage: fakeStorage(store), sessionStorage: fakeStorage(sess) })

const MAT = 'a'.repeat(64)        // 마스터 앱키에서 만든 재료(시험용 값)
const BACKUP = 'b'.repeat(64)     // 예비 앱키에서 만든 재료
const HASH = 'c'.repeat(64)

const row = (symbol: string, qty: number | null, name = symbol): Holding =>
  ({ id: `i_${symbol}`, symbol, market: 'KR', yahoo: null, name, secType: 'stock', ccy: 'KRW', avg: qty == null ? null : 1000, qty, fxBuy: null, group: 'g' } as Holding)
const setLocal = (items: Holding[]) => writePortfolio({ groups: [{ id: 'g', name: '기본' }], items, alerts: [] })
const ent = (s: string, q: number, n?: string): Entry => ({ s, m: 'KR', a: 1000, q, fx: null, ...(n ? { n } : {}) })
const qtyOf = (s: string) => readPortfolio().items.find(i => i.symbol === s)?.qty ?? null

function fresh(viaBackup = false) {
  store.clear(); sess.clear(); setPendingPerson(null)
  store.set('econMe_v1', JSON.stringify({ uid: 'u0', name: '나', role: 'owner', viaBackup }))
}

function fakeServer(init: EncBlob | null, opt: { mat?: string; backup?: boolean } = {}) {
  const srv = { enc: init, posts: [] as EncBlob[] }
  const deps: HoldDeps = {
    hash: () => HASH, mat: () => opt.mat ?? MAT, backup: () => !!opt.backup,
    get: async () => ({ ok: true, status: 200, enc: srv.enc }),
    post: async (_h, e) => { srv.posts.push(e); srv.enc = e; return { ok: true, status: 200 } },
  }
  return { srv, sync: makeHoldSync(deps) }
}

test('새 입장: 서버 판이 있으면 받는다 — 기기에 있던 것은 portfolioV1:prev 에 한 벌, 아무것도 올리지 않는다', async () => {
  fresh()
  setLocal([row('005930', 1)])
  resetHoldRec()
  const { srv, sync } = fakeServer(await encrypt([ent('000660', 2, '하이닉스')], MAT, '2026-10-27T01:00:00.000Z'))
  const r = await sync.run()
  assert.equal(r.pulled, true)
  assert.equal(srv.posts.length, 0)
  assert.equal(qtyOf('000660'), 2)
  assert.equal(qtyOf('005930'), null)                                    // 서버에 없는 종목은 값만 비운다(줄은 남김)
  assert.equal(readPortfolio().items.find(i => i.symbol === '000660')?.name, '하이닉스')
  const prev = read<{ side: string; data: { items: Holding[] } } | null>('portfolioV1:prev', null)
  assert.equal(prev?.side, 'device')
  assert.equal(prev?.data.items[0].qty, 1)
  assert.equal(readHoldRec().base, await fingerprint([ent('000660', 2)]))
})

test('서버가 비었으면 기기 것을 올린다 — 바뀐 시각(t)이 암호문 안에 실리고, Worker 가 받는 바깥 모양 그대로', async () => {
  fresh()
  setLocal([row('005930', 3)])
  resetHoldRec()
  noteHoldEdit('2026-10-27T05:06:07.000Z')
  const { srv, sync } = fakeServer(null)
  await sync.run()
  assert.equal(srv.posts.length, 1)
  const blob = srv.posts[0]
  assert.deepEqual(Object.keys(blob).sort(), ['alg', 'ciphertext', 'iter', 'iv', 'kdf', 'salt'])   // Worker _sanitizeEncHoldings 가 남기는 칸만
  assert.deepEqual(await decrypt(blob, MAT), { entries: entriesOf(readPortfolio().items), at: '2026-10-27T05:06:07.000Z' })
  assert.equal(readHoldRec().editAt, undefined)
  await sync.run()                                                        // 이제 같다 — 다시 올리지 않는다
  assert.equal(srv.posts.length, 1)
})

/** 서버와 한 번 맞춘 상태를 만든다(같은 판 → 기록만). */
async function agreed(items: Holding[], at = '2026-10-27T00:00:00.000Z') {
  setLocal(items)
  resetHoldRec()
  const s = fakeServer(await encrypt(entriesOf(items), MAT, at))
  await s.sync.run()
  assert.equal(s.srv.posts.length, 0)
  return s
}

test('둘 다 바뀌면 나중에 바꾼 쪽: 기기가 나중이면 올리고 서버 판을 portfolioV1:prev 에 남긴다', async () => {
  fresh()
  const { srv, sync } = await agreed([row('005930', 1)])
  setLocal([row('005930', 5)]); noteHoldEdit('2026-10-27T03:00:00.000Z')
  srv.enc = await encrypt([ent('005930', 9)], MAT, '2026-10-27T02:00:00.000Z')   // 다른 기기가 02시에 바꿈
  await sync.run()
  assert.equal(srv.posts.length, 1)
  assert.deepEqual((await decrypt(srv.posts[0], MAT)).entries.map(e => e.q), [5])
  assert.equal(qtyOf('005930'), 5)
  const prev = read<{ side: string; at: string; data: { items: Holding[] } } | null>('portfolioV1:prev', null)
  assert.equal(prev?.side, 'server')
  assert.equal(prev?.at, '2026-10-27T02:00:00.000Z')
  assert.equal(prev?.data.items[0].qty, 9)
})

test('둘 다 바뀌면 나중에 바꾼 쪽: 서버가 나중이면 받고 기기 판을 portfolioV1:prev 에 남긴다(올리지 않음)', async () => {
  fresh()
  const { srv, sync } = await agreed([row('005930', 1)])
  setLocal([row('005930', 5)]); noteHoldEdit('2026-10-27T03:00:00.000Z')
  srv.enc = await encrypt([ent('005930', 9)], MAT, '2026-10-27T04:00:00.000Z')
  const r = await sync.run()
  assert.equal(r.pulled, true)
  assert.equal(srv.posts.length, 0)
  assert.equal(qtyOf('005930'), 9)
  const prev = read<{ side: string; data: { items: Holding[] } } | null>('portfolioV1:prev', null)
  assert.equal(prev?.side, 'device')
  assert.equal(prev?.data.items[0].qty, 5)
})

test('둘 다 같은 값으로 바뀌었으면 할 일 없음 — 「바꾼 때」 기록도 푼다(다음 판정에 낡은 시각이 끼지 않게)', async () => {
  fresh()
  const { srv, sync } = await agreed([row('005930', 1)])
  setLocal([row('005930', 5)]); noteHoldEdit('2026-10-27T03:00:00.000Z')
  srv.enc = await encrypt([ent('005930', 5)], MAT, '2026-10-27T02:00:00.000Z')
  await sync.run()
  assert.equal(srv.posts.length, 0)
  assert.equal(readHoldRec().editAt, undefined)
  assert.equal(read('portfolioV1:prev', null), null)
})

test('옛 범위 기록 hold:false 는 보지 않는다 — 그래도 맞춘다', async () => {
  fresh()
  const { srv, sync } = await agreed([row('005930', 1)])
  store.set('econSyncScope_v1', JSON.stringify({ prefs: false, hold: false }))
  srv.enc = await encrypt([ent('005930', 7)], MAT, '2026-10-27T02:00:00.000Z')
  const r = await sync.run()
  assert.equal(r.pulled, true)
  assert.equal(qtyOf('005930'), 7)
})

test('예비 앱키로 들어와 보유를 못 열면: 올리지 않고(덮어쓰기 금지) 한 줄만 — 버리고 올리기도 막는다', async () => {
  fresh(true)
  setLocal([row('005930', 4)]); noteHoldEdit('2026-10-27T09:00:00.000Z')
  const master = await encrypt([ent('005930', 1), ent('000660', 2)], MAT, '2026-10-27T01:00:00.000Z')
  const { srv, sync } = fakeServer(master, { mat: BACKUP, backup: true })
  const r = await sync.run()
  assert.equal(srv.posts.length, 0)
  assert.equal(r.state.kind, 'backup')
  assert.equal(r.state.text, '예비 앱키로는 보유를 열 수 없습니다. 마스터 앱키로 들어와 주세요')
  assert.equal(HOLD_TEXT.backup, r.state.text)
  assert.equal(qtyOf('005930'), 4)                                        // 이 기기 것도 그대로
  await sync.run({ drop: true })
  assert.equal(srv.posts.length, 0)
  assert.equal(srv.enc, master)
})

test('예비 앱키 기기는 서버가 비어 있어도 올리지 않는다(마스터가 못 여는 판을 만들지 않게)', async () => {
  fresh(true)
  setLocal([row('005930', 4)]); noteHoldEdit('2026-10-27T09:00:00.000Z')
  const { srv, sync } = fakeServer(null, { mat: BACKUP, backup: true })
  const r = await sync.run()
  assert.equal(srv.posts.length, 0)
  assert.equal(r.state.kind, 'backup')
})

test('이름을 고치면(지문은 그대로) 한 번 올려 이름(n)이 다른 기기로 간다 — 바뀐 시각은 서버 판 그대로', async () => {
  fresh()
  const { srv, sync } = await agreed([row('005930', 1, '005930')], '2026-10-20T00:00:00.000Z')
  setLocal([row('005930', 1, '삼성전자')]); noteHoldNames()
  await sync.run()
  assert.equal(srv.posts.length, 1)
  const d = await decrypt(srv.posts[0], MAT)
  assert.equal(d.entries[0].n, '삼성전자')
  assert.equal(d.at, '2026-10-20T00:00:00.000Z')                        // 이름만 고친 판이 「더 새 판」인 척하지 않는다
  await sync.run()
  assert.equal(srv.posts.length, 1)                                       // 한 번만
})

test('이미 들어와 있던 기기(옛 기록 — 서버 판 지문만 있음)가 새 판을 처음 열 때: 서버만 바뀌었으면 받는다', async () => {
  fresh()
  setLocal([row('005930', 1)])
  store.set('econHoldSync_v1', JSON.stringify({ base: await fingerprint([ent('005930', 1)]), upAt: '2026-10-26T00:00:00.000Z', server: true }))
  store.set('econSyncScope_v1', JSON.stringify({ prefs: true, hold: false }))
  const { srv, sync } = fakeServer(await encrypt([ent('005930', 3)], MAT, '2026-10-27T01:00:00.000Z'))
  await sync.run()
  assert.equal(srv.posts.length, 0)
  assert.equal(qtyOf('005930'), 3)
})

test('이미 들어와 있던 기기: 둘 다 바뀌었는데 기기 쪽 바꾼 때를 모르면 서버 판을 받고 기기 판은 남긴다 — 옛 판으로 덮지 않는다', async () => {
  fresh()
  setLocal([row('005930', 2)])
  store.set('econHoldSync_v1', JSON.stringify({ base: await fingerprint([ent('005930', 1)]), upAt: '2026-10-26T00:00:00.000Z', server: true }))
  const { srv, sync } = fakeServer(await encrypt([ent('005930', 3)], MAT, '2026-10-27T01:00:00.000Z'))
  await sync.run()
  assert.equal(srv.posts.length, 0)
  assert.equal(qtyOf('005930'), 3)
  assert.equal(read<{ side: string; data: { items: Holding[] } } | null>('portfolioV1:prev', null)?.data.items[0].qty, 2)
})

test('기기가 비었는데 지운 기록이 없으면(저장소가 비워짐) 받는다 — 빈 판을 올리지 않는다', async () => {
  fresh()
  const { srv, sync } = await agreed([row('005930', 1)])
  setLocal([])
  const r = await sync.run()
  assert.equal(r.pulled, true)
  assert.equal(srv.posts.length, 0)
  assert.equal(qtyOf('005930'), 1)
})

test('옛 형식 덩어리(예전 암호로 잠금): 한 줄 안내만 · 올리지 않음 → 예전 암호를 넣으면 받아서 지금 앱키로 다시 잠근다', async () => {
  fresh()
  setLocal([row('005930', 1)])
  resetHoldRec()
  const { srv, sync } = fakeServer(await encrypt([ent('005930', 4)], 'old-pass-123', '2026-10-01T00:00:00.000Z'))
  const r = await sync.run()
  assert.equal(r.state.kind, 'old')
  assert.equal(srv.posts.length, 0)
  const bad = await sync.run({ old: 'wrong-pass' })
  assert.equal(bad.state.kind, 'old')
  assert.equal(srv.posts.length, 0)
  const ok = await sync.run({ old: ' old-pass-123 ' })
  assert.equal(ok.state.kind, 'info')                                     // 안내 칸은 닫히고 「받았고 한 벌 남김」 한 줄
  assert.equal(qtyOf('005930'), 4)                                        // 새 입장 규칙 그대로 — 서버 판 우선
  assert.equal(srv.posts.length, 1)
  assert.deepEqual((await decrypt(srv.posts[0], MAT)).entries.map(e => e.q), [4])   // 이제 지금 앱키로 열린다
  await sync.run()
  assert.equal(srv.posts.length, 1)
})

test('옛 형식 덩어리에서 「이 기기 보유로 새로 잠그기」: 기기 것을 올리고 서버에 있던 덩어리는 portfolioV1:prev 에 그대로 남긴다', async () => {
  fresh()
  setLocal([row('005930', 6)])
  resetHoldRec()
  const old = await encrypt([ent('005930', 4)], 'old-pass-123', '2026-10-01T00:00:00.000Z')
  const { srv, sync } = fakeServer(old)
  await sync.run({ drop: true })
  assert.equal(srv.posts.length, 1)
  assert.deepEqual((await decrypt(srv.posts[0], MAT)).entries.map(e => e.q), [6])
  assert.deepEqual(read<{ side: string; enc: EncBlob } | null>('portfolioV1:prev', null)?.enc, old)
})
