// 자가검사: npm test --prefix app — 계정 모듈(signIn · refreshMe · signOut). sync.ts 는 화면 모듈을 끌고 와 node 에서 못 불러오므로 makeAccount 에 가짜를 꽂는다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { makeAccount, ME_KEY, parseMe } from './account.ts'

const store = new Map<string, string>()
const mem = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v) }, removeItem: (k: string) => { store.delete(k) } }
Object.assign(globalThis, { localStorage: mem, sessionStorage: mem })

const KEEP = 'econSyncHashKeep_v1'
const HASH = 'a'.repeat(64)
const ME = { uid: 'u1abc', name: '민수', role: 'member', viaBackup: false }

type Calls = { connect: string[]; disable: number; forget: number }
function setup(status: number | 'net', body: unknown = ME, connectOk = true) {
  const calls: Calls = { connect: [], disable: 0, forget: 0 }
  const seen: { url?: string; hash?: string } = {}
  const g = globalThis as unknown as { fetch: unknown }
  const saved = g.fetch
  g.fetch = async (url: string, init: RequestInit) => {
    seen.url = url; seen.hash = (init.headers as Record<string, string>)['X-Sync-Key-Hash']
    if (status === 'net') throw new TypeError('Failed to fetch')
    return new Response(JSON.stringify(body), { status })
  }
  store.clear(); store.set(KEEP, HASH)
  const acct = makeAccount({
    getKeyHash: () => HASH,
    connectSync: async (k: string) => { calls.connect.push(k); return connectOk },
    disableSync: () => { calls.disable++; store.delete(KEEP) },
    forgetDevice: async () => { calls.forget++; store.delete(KEEP) },
  })
  return { acct, calls, seen, restore: () => { g.fetch = saved } }
}

test('signIn: 200 → ok, econMe_v1 저장 · connectSync(원문) · 해시는 정규화한 키', async () => {
  const t = setup(200)
  try {
    assert.equal(await t.acct.signIn(' ecom-7kq3 px9m-2hta '), 'ok')
    assert.deepEqual(JSON.parse(store.get(ME_KEY)!), ME)
    assert.deepEqual(t.calls.connect, [' ecom-7kq3 px9m-2hta '])
    assert.match(t.seen.url!, /\/me$/)
    assert.match(t.seen.hash!, /^[0-9a-f]{64}$/)
  } finally { t.restore() }
})

test('signIn: 대소문자 · 공백이 달라도 같은 해시', async () => {
  const t1 = setup(200); await t1.acct.signIn('ecom-7kq3-px9m-2hta'); const h1 = t1.seen.hash; t1.restore()
  const t2 = setup(200); await t2.acct.signIn('ECOM 7KQ3 PX9M 2HTA'); const h2 = t2.seen.hash; t2.restore()
  assert.equal(h1, h2)
})

test('signIn: 401 bad · 403 paused · 429 rate · 네트워크 offline — 저장도 연결도 없음', async () => {
  for (const [status, want] of [[401, 'bad'], [403, 'paused'], [429, 'rate'], ['net', 'offline']] as const) {
    const t = setup(status, { error: 'x' })
    try {
      assert.equal(await t.acct.signIn('ECOM-7KQ3-PX9M-2HTA'), want, String(status))
      assert.equal(store.has(ME_KEY), false)
      assert.equal(t.calls.connect.length, 0)
    } finally { t.restore() }
  }
})

test('signIn: me 는 맞는데 연결이 안 되면 offline 이고 econMe_v1 을 남기지 않는다', async () => {
  const t = setup(200, ME, false)
  try { assert.equal(await t.acct.signIn('ECOM-7KQ3-PX9M-2HTA'), 'offline'); assert.equal(store.has(ME_KEY), false) } finally { t.restore() }
})

test('refreshMe: 401 → disableSync · econSyncHashKeep_v1 · econMe_v1 제거', async () => {
  const t = setup(401, { error: 'unauthorized' })
  try {
    store.set(ME_KEY, JSON.stringify(ME))
    await t.acct.refreshMe()
    assert.equal(t.calls.disable, 1)
    assert.equal(store.has(KEEP), false)
    assert.equal(store.has(ME_KEY), false)
  } finally { t.restore() }
})

test('refreshMe: 403 → 아무 키도 안 지우고 status 만 표시', async () => {
  const t = setup(403, { error: 'paused' })
  try {
    store.set(ME_KEY, JSON.stringify(ME))
    await t.acct.refreshMe()
    assert.equal(t.calls.disable, 0)
    assert.equal(store.get(KEEP), HASH)
    assert.deepEqual(JSON.parse(store.get(ME_KEY)!), { ...ME, status: 'paused' })
  } finally { t.restore() }
})

test('refreshMe: 200 → 최신 값으로 갱신(멈춤 표시 해제) · 429/네트워크 → 그대로', async () => {
  const t = setup(200, { ...ME, name: '민수2' })
  try {
    store.set(ME_KEY, JSON.stringify({ ...ME, status: 'paused' }))
    await t.acct.refreshMe()
    assert.deepEqual(JSON.parse(store.get(ME_KEY)!), { ...ME, name: '민수2' })
  } finally { t.restore() }
  for (const s of [429, 'net'] as const) {
    const u = setup(s, {})
    try {
      store.set(ME_KEY, JSON.stringify(ME)); await u.acct.refreshMe()
      assert.deepEqual(JSON.parse(store.get(ME_KEY)!), ME); assert.equal(u.calls.disable, 0)
    } finally { u.restore() }
  }
})

test('signOut: forgetDevice + econMe_v1 삭제', async () => {
  const t = setup(200)
  try {
    store.set(ME_KEY, JSON.stringify(ME))
    await t.acct.signOut()
    assert.equal(t.calls.forget, 1)
    assert.equal(store.has(ME_KEY), false)
  } finally { t.restore() }
})

test('parseMe: 모양이 틀리면 null', () => {
  assert.equal(parseMe('not json'), null)
  assert.equal(parseMe(JSON.stringify({ uid: 1 })), null)
  assert.equal(parseMe(JSON.stringify({ uid: 'a', name: 'b', role: 'x', viaBackup: false })), null)
  assert.deepEqual(parseMe(JSON.stringify(ME)), ME)
})
