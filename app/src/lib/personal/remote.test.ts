// 자가검사: npm test --prefix app — 동기화 키 해시 · 관심 종류 · 서버 문서 ↔ 이 기기 변환 왕복 · GET/PUT 왕복(가짜 서버)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { WORKER, fromServer, keyHash, prefsCall, toServer, watchKind, type Local, type PrefsDoc } from './remote.ts'

const local: Local = {
  watch: ['kospi', '005930', 'usdkrw', '0035S0', 'C2'],
  alerts: [{ id: 'a1', target: '005930', type: 'price', cond: { op: '>=', value: 90000 }, repeat: 'once', channels: ['push'], enabled: true }],
  settings: { updown: 'us', unit: 'won', quiet: { from: '23:00', to: '07:00' } },
  theme: 'dark',
  scenarios: [{ name: '시나리오 1', start: 'us10y', dir: 1, depth: 2, at: '2026-10-01T00:00:00.000Z' }],
}

test('keyHash: 앞뒤 공백을 뺀 SHA-256 hex(현행 화면과 같은 규칙)', async () => {
  assert.equal(await keyHash('abc'), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
  assert.equal(await keyHash('  abc \n'), await keyHash('abc'))
})

test('watchKind: 숫자로 시작하는 6자리만 종목', () => {
  assert.deepEqual(['005930', '0035S0', 'kospi', 'usdkrw', 'C2', 'circuit-KOSPI-20260729', '12345'].map(watchKind),
    ['stock', 'stock', 'indicator', 'indicator', 'indicator', 'indicator', 'indicator'])
})

test('toServer: 서버 모양 · 보유 칸 없음 · 담은 때는 직전 서버 문서에서', () => {
  const prev = { watch: [{ id: 'kospi', kind: 'indicator', addedAt: '2026-09-01T00:00:00.000Z' }] } as unknown as PrefsDoc
  const b = toServer(local, prev, '2026-10-02T00:00:00.000Z')
  assert.deepEqual(Object.keys(b).sort(), ['alerts', 'scenarios', 'settings', 'watch'])
  assert.deepEqual(b.watch.slice(0, 2), [
    { id: 'kospi', kind: 'indicator', addedAt: '2026-09-01T00:00:00.000Z' },
    { id: '005930', kind: 'stock', addedAt: '2026-10-02T00:00:00.000Z' },
  ])
  assert.deepEqual(b.settings, { theme: 'dark', updown: 'us', unit: 'won', quiet: { from: '23:00', to: '07:00' } })
  assert.deepEqual(b.scenarios, [{ name: '시나리오 1', inputs: { start: 'us10y', dir: 1, depth: 2, at: '2026-10-01T00:00:00.000Z' } }])
  assert.doesNotMatch(JSON.stringify(b), /"(avg|qty|fxBuy|holdings|items|portfolio)"/)
})

test('fromServer(toServer(x)) = x · 빈 문서는 서버 기본값', () => {
  assert.deepEqual(fromServer({ v: 1, updatedAt: 't', ...toServer(local, null, 'now') }), local)
  assert.deepEqual(fromServer({}), { watch: [], alerts: [], settings: { updown: 'kr', unit: 'man', quiet: null }, theme: 'system', scenarios: [] })
})

/** Worker handlePrefs 의 If-Match 규칙만 흉내 낸 가짜 서버. 요청 머리·주소도 기록한다. */
function fakeWorker(hash: string) {
  let doc: PrefsDoc | null = null
  let n = 0
  const log: { url: string; method: string; headers: Record<string, string> }[] = []
  const fetch = async (url: string, init: RequestInit = {}) => {
    const headers = init.headers as Record<string, string>
    log.push({ url, method: init.method ?? 'GET', headers })
    const res = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
    if (headers['X-Sync-Key-Hash'] !== hash) return res(401, { error: 'unauthorized' })
    if (init.method !== 'PUT') return res(200, doc ?? { v: 1, updatedAt: null, ...toServer(fromServer({}), null, '') })
    const have = doc?.updatedAt ?? ''
    const want = headers['If-Match'] === 'null' ? '' : headers['If-Match']
    if (want !== have) return res(409, { error: 'conflict', updatedAt: have || null })
    doc = { v: 1, updatedAt: `2026-10-02T00:00:0${++n}.000Z`, ...JSON.parse(String(init.body)) }
    return res(200, doc)
  }
  return { fetch, log }
}

test('prefsCall 왕복: 빈 서버 → 올리기 → 다른 기기가 받기 · 낡은 If-Match 는 409 · 틀린 키는 401', async () => {
  const hash = await keyHash('my-key')
  const w = fakeWorker(hash)
  const real = globalThis.fetch
  globalThis.fetch = w.fetch as typeof fetch
  try {
    const empty = await prefsCall(hash)
    assert.equal(empty.status, 200)
    assert.equal(empty.doc!.updatedAt, null)

    const put = await prefsCall(hash, { body: toServer(local, empty.doc!, 'now'), ifMatch: empty.doc!.updatedAt })
    assert.equal(put.status, 200)
    assert.ok(put.doc!.updatedAt)
    assert.equal(w.log[1].url, `${WORKER}/prefs`)
    assert.equal(w.log[1].headers['If-Match'], 'null')

    const other = await prefsCall(hash)                  // 다른 기기
    assert.deepEqual(fromServer(other.doc!), local)

    const stale = await prefsCall(hash, { body: toServer(local, null, 'now'), ifMatch: null })
    assert.equal(stale.status, 409)
    assert.equal(stale.error, 'conflict')

    const next = await prefsCall(hash, { body: toServer({ ...local, watch: ['kospi'] }, put.doc!, 'now'), ifMatch: put.doc!.updatedAt })
    assert.equal(next.status, 200)
    assert.deepEqual(next.doc!.watch.map(x => x.id), ['kospi'])

    assert.equal((await prefsCall('0'.repeat(64))).status, 401)
  } finally { globalThis.fetch = real }
})

test('prefsCall: 네트워크 실패는 status 0', async () => {
  const real = globalThis.fetch
  globalThis.fetch = (async () => { throw new TypeError('Failed to fetch') }) as typeof fetch
  try { assert.deepEqual(await prefsCall('x'), { status: 0, error: 'network' }) } finally { globalThis.fetch = real }
})
