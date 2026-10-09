// 자가검사: npm test --prefix app — 동기화 키 해시 · 관심 종류 · 서버 문서 ↔ 이 기기 변환 왕복 · GET/PUT 왕복(가짜 서버) · 키 바꾸기 요청 모양
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { WORKER, blankLocal, fromServer, keyChangeText, keyHash, portfolioGet, portfolioPost, prefsCall, syncedOf, syncKeyChange, toServer, watchKind, type Local, type PrefsDoc } from './remote.ts'
import { defaultSettings } from './prefsV2.ts'

const local: Local = {
  watch: ['kospi', '005930', 'usdkrw', '0035S0', 'C2'],
  alerts: [{ id: 'a1', event: 'U1', target: '005930', value: 90000, dir: 'up', repeat: 'once', ring: true, enabled: true },
    { id: 'a2', event: 'A1', target: '*', strength: 'huge', level: 'alarm', repeat: 'each', enabled: true }],
  settings: syncedOf({ ...defaultSettings(), updown: 'us', unit: 'won', quiet: null, package: 'many', ringChannel: 'both', dailyCap: 12,
    kakaoFriends: true, kakaoRecipients: [{ uuid: '', name: '나', briefOnly: true }], autoQuiet: false }),
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
  assert.deepEqual(b.settings, local.settings)   // v2 설정(Worker _sanitizePrefs 가 받는 칸)
  // 화면 모드 · 금액 단위 · 90일 자동 강등은 이 기기만(명세 S9) — 문서에 없다
  for (const k of ['theme', 'unit', 'autoQuiet']) assert.ok(!(k in b.settings), k)
  assert.deepEqual(b.scenarios, [{ name: '시나리오 1', inputs: { start: 'us10y', dir: 1, depth: 2, at: '2026-10-01T00:00:00.000Z' } }])
  assert.doesNotMatch(JSON.stringify(b), /"(avg|qty|fxBuy|holdings|items|portfolio)"/)
})

test('fromServer(toServer(x)) = x · 빈 문서는 기본값 · v1 서버 문서의 조건은 v2 로', () => {
  assert.deepEqual(fromServer({ v: 2, updatedAt: 't', ...toServer(local, null, 'now') }), local)
  assert.deepEqual(fromServer({}), { watch: [], alerts: [], settings: syncedOf(defaultSettings()), scenarios: [] })
  // Worker 가 채워 둔 theme · unit 은 읽지 않는다(받을 때도 이 기기 값을 둔다)
  const withDevice = { v: 2, updatedAt: 't', ...toServer(local, null, 'now'), settings: { ...local.settings, theme: 'dark', unit: 'man' } } as unknown as PrefsDoc
  assert.deepEqual(fromServer(withDevice).settings, local.settings)
  const v1 = { v: 1, alerts: [{ id: 'a1', target: 'kospi', type: 'price', cond: { op: '<=', value: 2500 }, repeat: 'once', channels: ['push'], enabled: true }] }
  assert.deepEqual(fromServer(v1 as unknown as PrefsDoc).alerts, [{ id: 'a1', target: 'kospi', event: 'U1', dir: 'down', value: 2500, repeat: 'once', ring: true, enabled: true }])
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

test('portfolioPost: 보유 덩어리만 보낸다 — alerts 를 실으면 안 된다(Worker 는 빠진 칸을 저장본 그대로 두고 공개 파일도 건드리지 않는다)', async () => {
  let sent: { url: string; body: Record<string, unknown> } | null = null
  const real = globalThis.fetch
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    sent = { url, body: JSON.parse(String(init.body)) }
    return new Response(JSON.stringify({ ok: true, committed: false }), { status: 200 })
  }) as unknown as typeof fetch
  try {
    const enc = { v: 1, ciphertext: 'c' } as unknown as Parameters<typeof portfolioPost>[1]
    assert.deepEqual(await portfolioPost('h'.repeat(64), enc), { ok: true, status: 200 })
    assert.equal(sent!.url, `${WORKER}/portfolio`)
    assert.deepEqual(Object.keys(sent!.body).sort(), ['encHoldings', 'keyHash'])
  } finally { globalThis.fetch = real }
})

test('portfolioGet: 보유 덩어리와 함께 현행 알림 조건(alerts)을 돌려준다 — 현행 조건 가져오기가 읽는다 · 키가 틀리면 못 읽음', async () => {
  const hash = 'h'.repeat(64)
  let seen: { url: string; headers: Record<string, string> } | null = null
  const real = globalThis.fetch
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    seen = { url, headers: init.headers as Record<string, string> }
    return (init.headers as Record<string, string>)['X-Sync-Key-Hash'] === hash
      ? new Response(JSON.stringify({ ok: true, alerts: [{ id: 'a', type: 'price_below', symbol: '005930', value: 7 }], encHoldings: null }), { status: 200 })
      : new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401 })
  }) as unknown as typeof fetch
  try {
    assert.deepEqual(await portfolioGet(hash), { ok: true, status: 200, enc: null, alerts: [{ id: 'a', type: 'price_below', symbol: '005930', value: 7 }] })
    assert.equal(seen!.url, `${WORKER}/portfolio`)
    assert.deepEqual(await portfolioGet('0'.repeat(64)), { ok: false, status: 401, error: 'unauthorized' })
  } finally { globalThis.fetch = real }
})

test('prefsCall: 네트워크 실패는 status 0', async () => {
  const real = globalThis.fetch
  globalThis.fetch = (async () => { throw new TypeError('Failed to fetch') }) as typeof fetch
  try { assert.deepEqual(await prefsCall('x'), { status: 0, error: 'network' }) } finally { globalThis.fetch = real }
})

test('syncKeyChange: 본문 { currentKey, newKey } 원문 그대로 · 해시 머리 · newKeyHash 없음 · 응답 200 / 400 weak_new_key / 401 / -1 / 0', async () => {
  const sent: { url: string; init: RequestInit }[] = []
  const real = globalThis.fetch
  const reply = (status: number, body: unknown) => (async (url: string, init: RequestInit) => {
    sent.push({ url, init })
    return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status })
  }) as unknown as typeof fetch
  try {
    globalThis.fetch = reply(200, { ok: true })
    assert.deepEqual(await syncKeyChange(' old-key ', 'new-key-123456 '), { status: 200 })
    assert.equal(sent[0].url, `${WORKER}/sync-key`)
    assert.equal(sent[0].init.method, 'POST')
    assert.deepEqual(JSON.parse(String(sent[0].init.body)), { currentKey: ' old-key ', newKey: 'new-key-123456 ' })   // 다듬기는 서버가 한다
    assert.deepEqual(Object.keys(sent[0].init.headers as Record<string, string>), ['content-type'])                     // X-Sync-Key-Hash 없음
    globalThis.fetch = reply(400, { error: 'weak_new_key' })
    assert.deepEqual(await syncKeyChange('a', 'b'), { status: 400, error: 'weak_new_key' })
    globalThis.fetch = reply(401, { error: 'unauthorized' })
    assert.equal((await syncKeyChange('a', 'b')).status, 401)
    globalThis.fetch = reply(200, '<html></html>')   // 2xx 인데 ok:true 없음 — 바뀐 것으로 보지 않는다
    assert.equal((await syncKeyChange('a', 'b')).status, -1)
    globalThis.fetch = (async () => { throw new TypeError('Failed to fetch') }) as unknown as typeof fetch
    assert.deepEqual(await syncKeyChange('a', 'b'), { status: 0, error: 'network' })
  } finally { globalThis.fetch = real }
})

test('keyChangeText: 바뀜은 빈 글 · 답을 잃은 0 · -1 은 새 키로 다시 연결해 보라고', () => {
  assert.equal(keyChangeText({ status: 200 }), '')
  assert.match(keyChangeText({ status: 0, error: 'network' }), /새 키로 다시 연결/)
  assert.equal(keyChangeText({ status: 0 }), keyChangeText({ status: -1 }))
  assert.match(keyChangeText({ status: 400, error: 'weak_new_key' }), /12자 이상/)
  assert.equal(keyChangeText({ status: 401 }), '지금 키가 맞지 않습니다.')
  assert.equal(keyChangeText({ status: 502, error: 'kv_write_failed' }), '서버가 받지 않았습니다(kv_write_failed).')
})

test('blankLocal: 관심 · 조건 · 시나리오가 없고 설정도 기본값일 때만 빈 기기(칸 순서 무관)', () => {
  const empty = fromServer({})
  assert.equal(blankLocal(empty), true)
  const reordered = Object.fromEntries(Object.entries(empty.settings).reverse()) as Local['settings']
  assert.equal(blankLocal({ ...empty, settings: reordered }), true)
  assert.equal(blankLocal({ ...empty, settings: { ...empty.settings, quiet: null } }), false)     // 조용한 시간만 끈 기기도 묻는다
  assert.equal(blankLocal({ ...empty, settings: { ...empty.settings, package: 'many' } }), false)
  assert.equal(blankLocal({ ...empty, watch: ['kospi'] }), false)
  assert.equal(blankLocal(local), false)
})
