// 자가검사: npm test --prefix app — 사람별 기기 저장 이름(who.ts · scoped.ts · account.signIn).
// store.ts 는 화면 모듈을 끌고 와 node 에서 못 불러오므로, 읽고 쓰는 함수는 store.ts 가 다시 내보내는 scoped.ts 것을 그대로 쓴다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { currentPerson, setPendingPerson, storeKey, type ScopedBase } from './who.ts'
import { read, readLedger, readPortfolio, readSnaps, scopedWipeNames, write, writeLedger, writePortfolio, writeSnaps, type Portfolio } from './scoped.ts'
import { makeAccount, ME_KEY } from './account.ts'

const store = new Map<string, string>()
Object.assign(globalThis, { localStorage: { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v) }, removeItem: (k: string) => { store.delete(k) } } })

const as = (p: { uid: string; role: 'owner' | 'member' } | null) => { setPendingPerson(null); if (p) store.set(ME_KEY, JSON.stringify({ ...p, name: 'x', viaBackup: false })); else store.delete(ME_KEY) }
const OWNER = { uid: 'u0', role: 'owner' as const }, X = { uid: 'uX1', role: 'member' as const }
const pf = (sym: string): Portfolio => ({ groups: [{ id: 'g', name: 'g' }], items: [{ symbol: sym } as never], alerts: [] })

test('storeKey: 없음 · owner = 옛 이름 그대로, member = 이름:uid, 깨진 저장은 없음 취급', () => {
  store.clear(); as(null)
  assert.equal(currentPerson(), null)
  assert.equal(storeKey('portfolioV1'), 'portfolioV1')
  as(OWNER); assert.equal(storeKey('pfLedgerV1'), 'pfLedgerV1')
  as(X); assert.equal(storeKey('econ_watch_v1'), 'econ_watch_v1:uX1')
  store.set(ME_KEY, '{깨짐'); assert.equal(storeKey('econPrefsV1'), 'econPrefsV1')
})

test('들어오는 사람(pending)이 저장된 사람보다 먼저', () => {
  store.clear(); as(OWNER)
  setPendingPerson(X); assert.equal(storeKey('pfLedgerV1'), 'pfLedgerV1:uX1')
  setPendingPerson(null); assert.equal(storeKey('pfLedgerV1'), 'pfLedgerV1')
})

test('실제 읽기 · 쓰기 함수: 보유 · 스냅샷 · 원장이 사람 바꿔도 안 섞인다', () => {
  store.clear()
  as(OWNER); writePortfolio(pf('A')); writeSnaps([{ d: '2026-10-01', ev: 1, ct: 1 }]); writeLedger([{ id: 'l1', d: '2026-10-01', kind: 'dep', amt: 1 }])
  as(X)
  assert.equal(readPortfolio().items.length, 0); assert.deepEqual(readSnaps(), []); assert.deepEqual(readLedger(), [])
  writePortfolio(pf('B')); writeSnaps([{ d: '2026-10-02', ev: 2, ct: 2 }]); writeLedger([{ id: 'l2', d: '2026-10-02', kind: 'wd', amt: 2 }])
  as(OWNER)
  assert.equal(readPortfolio().items[0].symbol, 'A'); assert.equal(readSnaps()[0].ev, 1); assert.equal(readLedger()[0].id, 'l1')
  as(X)
  assert.equal(readPortfolio().items[0].symbol, 'B'); assert.equal(readSnaps()[0].ev, 2); assert.equal(readLedger()[0].id, 'l2')
  assert.ok(store.has('portfolioV1:uX1') && store.has('pfLedgerV1:uX1') && store.has('pfSnapshotsV1:uX1'))
})

for (const base of ['econ_watch_v1', 'econPrefsV1', 'econ_scenarios_v1'] as const) {
  test(`바꿔 써도 안 섞인다: ${base}`, () => {
    store.clear()
    const put = (b: ScopedBase, v: unknown) => write(storeKey(b), v)
    as(OWNER); put(base, ['A'])
    as(X); assert.equal(read(storeKey(base), null), null); put(base, ['B'])
    as(OWNER); assert.deepEqual(read(storeKey(base), null), ['A'])
    as(X); assert.deepEqual(read(storeKey(base), null), ['B'])
    as(null); assert.deepEqual(read(storeKey(base), null), ['A'])
  })
}

test('wipe 이름: 지금 사람 것만 — econ_fav_v1 은 마스터 · 나간 상태에서만', () => {
  as(X)
  assert.deepEqual(scopedWipeNames(), ['portfolioV1', 'pfSnapshotsV1', 'pfLedgerV1', 'econ_watch_v1', 'econPrefsV1', 'econ_scenarios_v1'].map(b => `${b}:uX1`))
  assert.equal(scopedWipeNames().includes('econ_fav_v1'), false)
  as(OWNER); assert.ok(scopedWipeNames().includes('econ_fav_v1')); assert.ok(scopedWipeNames().includes('portfolioV1'))
  as(null); assert.ok(scopedWipeNames().includes('econ_fav_v1'))
})

// ── signIn 이 연결(connectSync)을 하는 동안의 저장 이름 ──
const HASH = 'a'.repeat(64)
async function signInWith(me: { uid: string; name: string; role: 'owner' | 'member' }, answer: 'ok' | 'ask' | 'fail') {
  store.clear(); as(OWNER_PREV)
  const used: string[] = []
  const g = globalThis as unknown as { fetch: unknown }, saved = g.fetch
  g.fetch = async () => new Response(JSON.stringify({ ...me, viaBackup: false }), { status: 200 })
  let hash: string | null = null
  const acct = makeAccount({
    getKeyHash: () => hash,
    connectSync: async () => {
      // 연결이 하는 일 흉내: 이 기기 문서를 읽고(matchPrefs/readLocal) 서버 것으로 쓰기(apply/writeLocal)
      for (const b of ['econ_watch_v1', 'econPrefsV1', 'econ_scenarios_v1', 'portfolioV1'] as const) used.push(storeKey(b))
      if (answer === 'ok') hash = HASH
      return answer !== 'fail'
    },
    disableSync: () => {}, forgetDevice: async () => {},
  })
  try { const r = await acct.signIn('ECOM-7KQ3-PX9M-2HTA'); return { r, used, acct, setHash: () => { hash = HASH } } } finally { g.fetch = saved }
}
const OWNER_PREV = OWNER   // 이 기기에 먼저 들어와 있던 사람 = 마스터

test('signIn(멤버): 연결 중 읽고 쓰는 이름이 모두 멤버 uid 꼬리, 기본 이름 없음 · 끝나면 pending 풀림', async () => {
  const t = await signInWith({ uid: 'uM9', name: '민수', role: 'member' }, 'ok')
  assert.equal(t.r, 'ok')
  assert.deepEqual(t.used, ['econ_watch_v1:uM9', 'econPrefsV1:uM9', 'econ_scenarios_v1:uM9', 'portfolioV1:uM9'])
  assert.equal(JSON.parse(store.get(ME_KEY)!).uid, 'uM9')
  assert.equal(storeKey('portfolioV1'), 'portfolioV1:uM9')   // 이제는 저장된 me 가 정한다
})

test('signIn(마스터): 기본 이름', async () => {
  const t = await signInWith({ uid: 'u0', name: '나', role: 'owner' }, 'ok')
  assert.equal(t.r, 'ok')
  assert.deepEqual(t.used, ['econ_watch_v1', 'econPrefsV1', 'econ_scenarios_v1', 'portfolioV1'])
})

test('signIn 실패(offline)면 pending 을 풀어 이전 사람 이름으로 돌아온다', async () => {
  const t = await signInWith({ uid: 'uM9', name: '민수', role: 'member' }, 'fail')
  assert.equal(t.r, 'offline')
  assert.deepEqual(t.used, ['econ_watch_v1:uM9', 'econPrefsV1:uM9', 'econ_scenarios_v1:uM9', 'portfolioV1:uM9'])
  assert.equal(storeKey('portfolioV1'), 'portfolioV1')        // 마스터 그대로
  assert.equal(JSON.parse(store.get(ME_KEY)!).uid, 'u0')
})

test('signIn ask: 답할 때까지 멤버 이름 · finish 면 me 저장 · cancel 이면 풀림', async () => {
  const t = await signInWith({ uid: 'uM9', name: '민수', role: 'member' }, 'ask')
  assert.equal(t.r, 'ask')
  assert.equal(storeKey('portfolioV1'), 'portfolioV1:uM9')    // 아직 me 는 마스터지만 들어오는 중
  t.setHash(); assert.equal(t.acct.finishSignIn(), true)
  assert.equal(JSON.parse(store.get(ME_KEY)!).uid, 'uM9'); assert.equal(storeKey('portfolioV1'), 'portfolioV1:uM9')
  const c = await signInWith({ uid: 'uM9', name: '민수', role: 'member' }, 'ask')
  c.acct.cancelSignIn()
  assert.equal(storeKey('portfolioV1'), 'portfolioV1')        // 마스터로 복귀
})
