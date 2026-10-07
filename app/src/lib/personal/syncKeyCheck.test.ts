// 자가검사: npm test --prefix app — 「PIN 잊음」의 동기화 키 확인은 검사만 한다(본문에 newKeyHash 가 실리면 서버 키가 바뀐다)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { WORKER, syncKeyCheck } from './remote.ts'

test('syncKeyCheck: 해시는 머리에만 · 본문은 빈 객체 · 맞으면 200 · 틀리면 401 · 네트워크 실패 0', async () => {
  const hash = 'a'.repeat(64)
  const sent: { url: string; init: RequestInit }[] = []
  const real = globalThis.fetch
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    sent.push({ url, init })
    return (init.headers as Record<string, string>)['X-Sync-Key-Hash'] === hash
      ? new Response(JSON.stringify({ ok: true, changed: false }), { status: 200 })
      : new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401 })
  }) as unknown as typeof fetch
  try {
    assert.equal(await syncKeyCheck(hash), 200)
    assert.equal(await syncKeyCheck('0'.repeat(64)), 401)
    assert.equal(sent[0].url, `${WORKER}/sync-key`)
    assert.equal(sent[0].init.method, 'POST')
    assert.deepEqual(JSON.parse(String(sent[0].init.body)), {})
    // 2xx 인데 ok:true 가 없으면(중간 장비의 빈 200 등) 맞은 것으로 보지 않는다 — PinGate 는 200 일 때만 PIN 을 지운다
    globalThis.fetch = (async () => new Response('<html></html>', { status: 200 })) as unknown as typeof fetch
    assert.equal(await syncKeyCheck(hash), -1)
    globalThis.fetch = (async () => new Response(JSON.stringify({ ok: 'yes' }), { status: 200 })) as unknown as typeof fetch
    assert.equal(await syncKeyCheck(hash), -1)
    globalThis.fetch = (async () => { throw new TypeError('Failed to fetch') }) as unknown as typeof fetch
    assert.equal(await syncKeyCheck(hash), 0)
  } finally { globalThis.fetch = real }
})
