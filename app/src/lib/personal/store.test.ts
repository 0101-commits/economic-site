// 자가검사: npm test --prefix app — 사람별 기기 저장 이름(who.ts). store.ts 는 화면 모듈을 끌고 와 node 에서 못 불러오므로,
// store.ts 와 같은 방식(storeKey 로 이름을 정해 읽고 쓰기)을 여기서 그대로 흉내 낸다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { currentPerson, storeKey, type ScopedBase } from './who.ts'

const store = new Map<string, string>()
Object.assign(globalThis, { localStorage: { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v) }, removeItem: (k: string) => { store.delete(k) } } })

const as = (p: { uid: string; role: 'owner' | 'member' } | null) => { if (p) store.set('econMe_v1', JSON.stringify({ ...p, name: 'x', viaBackup: false })); else store.delete('econMe_v1') }
const put = (b: ScopedBase, v: unknown) => localStorage.setItem(storeKey(b), JSON.stringify(v))
const get = (b: ScopedBase) => JSON.parse(localStorage.getItem(storeKey(b)) || 'null')
const OWNER = { uid: 'u0', role: 'owner' as const }, X = { uid: 'uX1', role: 'member' as const }

test('storeKey: 없음 · owner = 옛 이름 그대로, member = 이름:uid', () => {
  store.clear()
  assert.equal(currentPerson(), null)
  assert.equal(storeKey('portfolioV1'), 'portfolioV1')
  as(OWNER); assert.equal(storeKey('pfLedgerV1'), 'pfLedgerV1')
  as(X); assert.equal(storeKey('econ_watch_v1'), 'econ_watch_v1:uX1')
  store.set('econMe_v1', '{깨짐'); assert.equal(storeKey('econPrefsV1'), 'econPrefsV1')
})

for (const base of ['portfolioV1', 'pfLedgerV1', 'pfSnapshotsV1', 'econ_watch_v1', 'econPrefsV1', 'econ_scenarios_v1'] as const) {
  test(`바꿔 써도 안 섞인다: ${base}`, () => {
    store.clear()
    as(OWNER); put(base, ['A'])
    as(X); assert.equal(get(base), null); put(base, ['B'])
    as(OWNER); assert.deepEqual(get(base), ['A'])
    as(X); assert.deepEqual(get(base), ['B'])
    as(null); assert.deepEqual(get(base), ['A'])   // 나간 뒤는 옛 이름(마스터 쪽)
    assert.deepEqual(JSON.parse(store.get(`${base}:uX1`)!), ['B'])
  })
}
