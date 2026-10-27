// 자가검사: npm test --prefix app — 「어느 쪽을 남길까」 규칙(syncRules.ts). 묻지 않고 정한다.
// 새 입장은 서버 우선 · 서버가 비면 기기 것을 올림 · 둘 다 바뀌면 나중에 바뀐 쪽 + 진 쪽은 한 벌 남김 · 기록 없이 빈 기기는 받기.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { prefsStep, settle, type SettleIn } from './syncRules.ts'
import { fromServer, type Local, type PrefsDoc } from './remote.ts'

const base: SettleIn = { serverHas: true, localHas: true, same: false, known: true, localChanged: false, serverChanged: false, localEdited: false, localAt: 0, serverAt: 0 }
const T = (iso: string) => Date.parse(iso)

test('settle: 서버가 비었으면 기기 것을 올리고(있을 때만), 같으면 할 일 없음', () => {
  assert.deepEqual(settle({ ...base, serverHas: false }), { act: 'push', keep: null })
  assert.deepEqual(settle({ ...base, serverHas: false, localHas: false }), { act: 'none', keep: null })
  assert.deepEqual(settle({ ...base, same: true, localChanged: true, serverChanged: true }), { act: 'none', keep: null })
})

test('settle: 새 입장(맞춘 기록 없음)은 서버 것으로 — 기기에 다른 것이 있으면 한 벌 남긴다', () => {
  assert.deepEqual(settle({ ...base, known: false }), { act: 'pull', keep: 'device' })
  assert.deepEqual(settle({ ...base, known: false, localHas: false }), { act: 'pull', keep: null })
  // 기기에서 막 바꾼 기록이 있어도 새 입장은 서버 우선
  assert.deepEqual(settle({ ...base, known: false, localEdited: true, localAt: T('2026-10-27T09:00:00Z'), serverAt: T('2026-10-01T00:00:00Z') }), { act: 'pull', keep: 'device' })
})

test('settle: 한쪽만 바뀌면 그쪽으로 · 아무도 안 바뀌면 할 일 없음', () => {
  assert.deepEqual(settle({ ...base, localChanged: true }), { act: 'push', keep: null })
  assert.deepEqual(settle({ ...base, serverChanged: true }), { act: 'pull', keep: null })
  assert.deepEqual(settle(base), { act: 'none', keep: null })
})

test('settle: 둘 다 바뀌면 나중에 바뀐 쪽이 이기고 진 쪽을 남긴다 · 같거나 모르면 서버(옛 판으로 덮지 않는다)', () => {
  const both = { ...base, localChanged: true, serverChanged: true, localEdited: true }
  assert.deepEqual(settle({ ...both, localAt: T('2026-10-27T03:00:00Z'), serverAt: T('2026-10-27T02:00:00Z') }), { act: 'push', keep: 'server' })
  assert.deepEqual(settle({ ...both, localAt: T('2026-10-27T01:00:00Z'), serverAt: T('2026-10-27T02:00:00Z') }), { act: 'pull', keep: 'device' })
  assert.deepEqual(settle({ ...both, localAt: T('2026-10-27T02:00:00Z'), serverAt: T('2026-10-27T02:00:00Z') }), { act: 'pull', keep: 'device' })
  assert.deepEqual(settle({ ...both, localEdited: false, localAt: 0, serverAt: 0 }), { act: 'pull', keep: 'device' })   // 이 판을 처음 연 기기 — 바꾼 때를 모른다
})

test('settle: 기기가 비었는데 지운 기록이 없으면(저장소가 비워짐) 받는다 — 빈 것을 올려 서버 판을 지우지 않는다', () => {
  assert.deepEqual(settle({ ...base, localHas: false, localChanged: true }), { act: 'pull', keep: null })
  assert.deepEqual(settle({ ...base, localHas: false, localChanged: true, localEdited: true }), { act: 'push', keep: null })   // 이 기기에서 직접 다 지웠다
})

// ── 설정(관심 · 알림 조건 · 설정 · 시나리오) — 서버 문서의 updatedAt 이 서버 쪽 바뀐 시각 ──
const empty = fromServer({})
const local = (watch: string[]): Local => ({ ...empty, watch })
const doc = (watch: string[], updatedAt: string | null): PrefsDoc => ({ v: 2, updatedAt, watch: watch.map(id => ({ id, kind: 'indicator', addedAt: null })), alerts: [], settings: empty.settings, scenarios: [] })
const fp = (l: Local) => JSON.stringify(l)

test('prefsStep: 새 입장 — 서버에 설정이 있으면 서버 것(기기 것은 한 벌), 없으면 기기 것을 올림', () => {
  assert.deepEqual(prefsStep({}, local(['kospi']), fp(local(['kospi'])), doc(['usdkrw'], '2026-10-27T01:00:00.000Z')), { act: 'pull', keep: 'device' })
  assert.deepEqual(prefsStep({}, local(['kospi']), fp(local(['kospi'])), doc([], null)), { act: 'push', keep: null })
  assert.deepEqual(prefsStep({}, local(['kospi']), fp(local(['kospi'])), doc(['kospi'], '2026-10-27T01:00:00.000Z')), { act: 'none', keep: null })
  assert.deepEqual(prefsStep({}, empty, fp(empty), doc(['usdkrw'], '2026-10-27T01:00:00.000Z')), { act: 'pull', keep: null })
})

test('prefsStep: 들어와 있는 동안 — 바뀐 쪽 · 둘 다면 나중 것(서버는 updatedAt, 기기는 바꾼 때)', () => {
  const was = local(['kospi']), rec = { base: fp(was), srvAt: '2026-10-27T01:00:00.000Z' }
  // 기기만 바뀜
  assert.equal(prefsStep({ ...rec, editAt: '2026-10-27T02:00:00.000Z' }, local(['kospi', 'vix']), fp(local(['kospi', 'vix'])), doc(['kospi'], rec.srvAt)).act, 'push')
  // 서버만 바뀜
  assert.equal(prefsStep(rec, was, fp(was), doc(['usdkrw'], '2026-10-27T03:00:00.000Z')).act, 'pull')
  // 둘 다 — 기기가 나중
  assert.deepEqual(prefsStep({ ...rec, editAt: '2026-10-27T04:00:00.000Z' }, local(['vix']), fp(local(['vix'])), doc(['usdkrw'], '2026-10-27T03:00:00.000Z')), { act: 'push', keep: 'server' })
  // 둘 다 — 서버가 나중
  assert.deepEqual(prefsStep({ ...rec, editAt: '2026-10-27T02:00:00.000Z' }, local(['vix']), fp(local(['vix'])), doc(['usdkrw'], '2026-10-27T03:00:00.000Z')), { act: 'pull', keep: 'device' })
})
