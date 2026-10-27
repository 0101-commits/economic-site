// 자가검사: npm test --prefix app — 계정 모듈(signIn · refreshMe · signOut). sync.ts 는 화면 모듈을 끌고 와 node 에서 못 불러오므로 makeAccount 에 가짜를 꽂는다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { clearMe, keyWasLost, makeAccount, ME_KEY, parseMe } from './account.ts'
import { currentPerson } from './who.ts'

const store = new Map<string, string>()
const mem = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v) }, removeItem: (k: string) => { store.delete(k) } }
Object.assign(globalThis, { localStorage: mem, sessionStorage: mem })

const KEEP = 'econSyncHashKeep_v1'
const HASH = 'a'.repeat(64)
const ME = { uid: 'u1abc', name: '민수', role: 'member', viaBackup: false }

type Calls = { connect: string[]; perm: unknown[]; disable: number; forget: number; drop: number }
function setup(status: number | 'net', body: unknown = ME, connectOk = true) {
  const calls: Calls = { connect: [], perm: [], disable: 0, forget: 0, drop: 0 }
  const seen: { url?: string; hash?: string } = {}
  const g = globalThis as unknown as { fetch: unknown }
  const saved = g.fetch
  g.fetch = async (url: string, init: RequestInit) => {
    seen.url = url; seen.hash = (init.headers as Record<string, string>)['X-Sync-Key-Hash']
    if (status === 'net') throw new TypeError('Failed to fetch')
    return new Response(JSON.stringify(body), { status })
  }
  store.clear(); store.set(KEEP, HASH)
  const hs: { cur: string | null } = { cur: HASH }
  const acct = makeAccount({
    getKeyHash: () => hs.cur,
    connectSync: async (k: string, perm?: Promise<unknown>) => { calls.connect.push(k); calls.perm.push(perm); return connectOk },
    disableSync: () => { calls.disable++; store.delete(KEEP) },
    forgetDevice: async () => { calls.forget++; store.delete(KEEP) },
    dropPush: async () => { calls.drop++ },
  })
  return { acct, calls, seen, hs, restore: () => { g.fetch = saved } }
}

test('signIn: 묻는 단계 없음 — 연결이 끝났는데 해시가 없으면 offline 이고 아무것도 안 남긴다', async () => {
  const t = setup(200)
  try {
    t.hs.cur = null
    assert.equal(await t.acct.signIn('ECOM-7KQ3-PX9M-2HTA'), 'offline')
    assert.equal(store.has(ME_KEY), false)
  } finally { t.restore() }
})

test('signIn: 연결하는 동안 들어오는 사람에 예비 앱키 여부(viaBackup)가 실린다 — 보유 맞춤이 덮어쓰기를 막는 데 쓴다', async () => {
  const t = setup(200, { ...ME, viaBackup: true })
  let seen: unknown = null
  const acct = makeAccount({
    getKeyHash: () => HASH,
    connectSync: async () => { seen = currentPerson(); return true },
    disableSync: () => {}, forgetDevice: async () => {},
  })
  try {
    assert.equal(await acct.signIn('ECOM-7KQ3-PX9M-2HTA'), 'ok')
    assert.deepEqual(seen, { uid: 'u1abc', role: 'member', viaBackup: true })
    assert.equal(currentPerson()?.viaBackup, true)                  // 들어온 뒤엔 저장된 me 가 알려 준다
  } finally { t.restore() }
})

test('refreshMe: 기다리는 사이 다른 키로 들어왔으면 401 · 403 을 무시한다', async () => {
  for (const s of [401, 403] as const) {
    const t = setup(s, { error: 'x' })
    try {
      store.set(ME_KEY, JSON.stringify(ME))
      const g = globalThis as unknown as { fetch: (u: string, i: RequestInit) => Promise<Response> }
      const inner = g.fetch
      g.fetch = async (u, i) => { t.hs.cur = 'b'.repeat(64); return inner(u, i) }   // 응답 오기 전에 다른 키로 로그인
      await t.acct.refreshMe()
      assert.equal(t.calls.disable, 0)
      assert.deepEqual(JSON.parse(store.get(ME_KEY)!), ME)
    } finally { t.restore() }
  }
})

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

test('refreshMe: 401 → disableSync · econSyncHashKeep_v1 · econMe_v1 제거 · 이 브라우저 폰 알림 구독 끊기 · 끊긴 표시', async () => {
  const t = setup(401, { error: 'unauthorized' })
  try {
    store.set(ME_KEY, JSON.stringify(ME))
    await t.acct.refreshMe()
    assert.equal(t.calls.disable, 1)
    assert.equal(t.calls.drop, 1)
    assert.equal(store.has(KEEP), false)
    assert.equal(store.has(ME_KEY), false)
    assert.equal(keyWasLost(), true)
  } finally { t.restore() }
})

test('끊긴 표시: 다시 들어오면(me 저장) 지운다 · 403 은 폰 알림 구독을 건드리지 않는다', async () => {
  const t = setup(200)
  try {
    clearMe()
    assert.equal(keyWasLost(), true)
    assert.equal(await t.acct.signIn('ECOM-7KQ3-PX9M-2HTA'), 'ok')
    assert.equal(keyWasLost(), false)
  } finally { t.restore() }
  const u = setup(403, { error: 'paused' })
  try {
    store.set(ME_KEY, JSON.stringify(ME))
    await u.acct.refreshMe()
    assert.equal(u.calls.drop, 0)
  } finally { u.restore() }
})

test('signIn: 단추를 누른 순간 물은 알림 허락(perm)을 연결에 그대로 넘긴다', async () => {
  const t = setup(200)
  try {
    const perm = Promise.resolve('granted')
    assert.equal(await t.acct.signIn('ECOM-7KQ3-PX9M-2HTA', perm), 'ok')
    assert.equal(t.calls.perm[0], perm)
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
