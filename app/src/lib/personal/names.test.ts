// 자가검사: npm test --prefix app — 종목 이름 찾기 순서 · 고치기 규칙(코드면 고침, 지은 이름은 둠) · 암호 덩어리 항목 n 왕복 · n 없는 옛 항목 읽기
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { codeKey, fixNames, needsName, resolveNameWith, type NameSource } from './names.ts'
import { applyEntries, decrypt, encrypt, entriesOf, fingerprint, parsePlain, type Entry } from './e2e.ts'

test('resolveNameWith: 출처 순서대로, 처음 나온 이름', async () => {
  const calls: string[] = []
  const a: NameSource = () => { calls.push('a'); return undefined }
  const b: NameSource = () => { calls.push('b'); return '엔비디아' }
  const c: NameSource = () => { calls.push('c'); return 'NVIDIA Corp' }
  assert.equal(await resolveNameWith('NVDA', 'US', [a, b, c]), '엔비디아')
  assert.deepEqual(calls, ['a', 'b'])
})

test('resolveNameWith: 코드와 같은 값 · 빈 값 · 던진 출처는 건너뛴다', async () => {
  const same: NameSource = (s) => s
  const empty: NameSource = () => '  '
  const boom: NameSource = () => { throw new Error('x') }
  const late: NameSource = async () => 'Apple Inc.'
  assert.equal(await resolveNameWith('AAPL', 'US', [same, empty, boom, late]), 'Apple Inc.')
  assert.equal(await resolveNameWith('AAPL', 'US', [same, empty]), undefined)
  assert.equal(await resolveNameWith('005930', 'KR', [() => '005930.KS']), undefined)
})

test('needsName: 비었거나 코드와 같을 때만(대소문자 · .KS/.KQ 무시)', () => {
  assert.equal(needsName({ symbol: '005930', name: '005930' }), true)
  assert.equal(needsName({ symbol: '005930', name: '005930.KS' }), true)
  assert.equal(needsName({ symbol: 'AAPL', name: 'aapl' }), true)
  assert.equal(needsName({ symbol: 'AAPL', name: '' }), true)
  assert.equal(needsName({ symbol: 'AAPL' }), true)
  assert.equal(needsName({ symbol: 'AAPL', name: '내 애플' }), false)
  assert.equal(codeKey(' 000660.kq '), '000660')
})

test('fixNames: 코드 이름은 고치고, 지은 이름은 그대로, 빈 이름은 채운다', async () => {
  const items = [
    { id: '1', symbol: '005930', market: 'KR' as const, name: '005930' },
    { id: '2', symbol: 'AAPL', market: 'US' as const, name: '내 사과' },
    { id: '3', symbol: '000660', market: 'KR' as const },
    { id: '4', symbol: 'ZZZZ', market: 'US' as const, name: 'ZZZZ' },
  ]
  const asked: string[] = []
  const r = await fixNames(items, async (s) => { asked.push(s); return s === 'ZZZZ' ? undefined : `이름-${s}` })
  assert.deepEqual(r.items.map(i => i.name), ['이름-005930', '내 사과', '이름-000660', 'ZZZZ'])
  assert.deepEqual(asked.sort(), ['000660', '005930', 'ZZZZ'])   // 지은 이름 줄은 묻지도 않는다
  assert.equal(r.changed, true)
  const none = await fixNames([items[1]], async () => '덮어쓰기')
  assert.equal(none.changed, false)
  assert.equal(none.items[0].name, '내 사과')
})

test('e2e: 항목 n 왕복(코드 이름은 싣지 않는다)', async () => {
  const es = entriesOf([
    { symbol: 'AAPL', market: 'US', name: '애플', avg: 1, qty: 2, fxBuy: 1300 },
    { symbol: '005930', market: 'KR', name: '005930', avg: 3, qty: 4 },
    { symbol: '000660', market: 'KR', avg: 5, qty: 6 },
  ] as Parameters<typeof entriesOf>[0])
  assert.equal(es[0].n, '애플')
  assert.equal('n' in es[1], false)
  assert.equal('n' in es[2], false)
  const blob = await encrypt(es, 'pw-test-1', '2026-10-27T00:00:00Z')
  const back = await decrypt(blob, 'pw-test-1')
  assert.deepEqual(back.entries, es)
  assert.equal(back.entries[0].n, '애플')
})

test('e2e: n 없는 옛 항목도 읽힌다 · 이상한 n 은 버린다', () => {
  const p = parsePlain([{ s: '005930', m: 'KR', a: 1, q: 2, fx: null }, { s: 'AAPL', m: 'US', a: 1, q: 1, fx: null, n: 7 }, { s: 'X', m: 'US', a: 1, q: 1, n: '  ' }, { t: 'x' }])
  assert.equal(p.entries.length, 3)
  assert.equal('n' in p.entries[0], false)
  assert.equal('n' in p.entries[1], false)
  assert.equal('n' in p.entries[2], false)
})

test('e2e: 지문은 이름과 무관, 받기는 이름 없는 줄에만 이름을 채운다', async () => {
  const a: Entry[] = [{ s: 'AAPL', m: 'US', a: 1, q: 1, fx: null }]
  const b: Entry[] = [{ s: 'AAPL', m: 'US', a: 1, q: 1, fx: null, n: '애플' }]
  assert.equal(await fingerprint(a), await fingerprint(b))
  type H = { id: string; symbol: string; market: string; name?: string; avg?: number | null; qty?: number | null }
  const make = (e: Entry): H => ({ id: 'n', symbol: e.s, market: e.m, name: e.n ?? e.s, avg: e.a, qty: e.q })
  const es: Entry[] = [{ s: 'AAPL', m: 'US', a: 2, q: 2, fx: null, n: '애플' }, { s: '005930', m: 'KR', a: 3, q: 3, fx: null, n: '삼성전자' }, { s: 'NEW', m: 'US', a: 1, q: 1, fx: null, n: '새 회사' }]
  const out = applyEntries<H>([
    { id: '1', symbol: 'AAPL', market: 'US', name: 'AAPL', avg: 1, qty: 1 },
    { id: '2', symbol: '005930', market: 'KR', name: '내 삼전', avg: 1, qty: 1 },
  ], es, make)
  assert.equal(out[0].name, '애플')      // 코드였던 이름은 채움
  assert.equal(out[1].name, '내 삼전')   // 지은 이름은 둠
  assert.equal(out[2].name, '새 회사')   // 새 줄은 n 으로
})
