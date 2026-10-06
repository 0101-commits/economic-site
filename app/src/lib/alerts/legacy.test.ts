// 자가검사: npm test --prefix app — 현행 조건 가져오기: 변환 6종 · 겹침 건너뜀 · 한도 · 모양이 틀린 줄
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { condKey, convertLegacy } from './legacy.ts'
import { TARGET_RE } from '../personal/alertStatus.ts'
import { ALERT_CAP, type Dict } from './v2.ts'
import type { AlertCond } from '../personal/store'

const dict: Dict = JSON.parse(readFileSync(new URL('./dict.json', import.meta.url), 'utf8'))
const evName = (id: string) => dict.events.find(e => e.id === id)?.name
const seq = () => { let n = 0; return () => `p${++n}` }
const L = (type: string, o: Record<string, unknown> = {}) =>
  ({ id: 'x', symbol: '005930', market: 'KR', name: '삼성전자', type, value: 80000, enabled: true, limit: 'cool60', refire: false, ...o })
const U1 = (o: Partial<AlertCond> = {}): AlertCond => ({ id: 'e1', event: 'U1', target: '005930', dir: 'up', value: 80000, repeat: 'each', ring: true, enabled: true, ...o })

test('변환 6종: 가격 위 · 아래 → U1, 등락률 → U2(절댓값), 52주 신고가 · 신저가 → B1, 골든 · 데드크로스는 제외', () => {
  const rows = [
    L('price_above', { symbol: 'A00001', name: 'AAA', value: 90000 }),
    L('price_below', { symbol: 'B00001', name: 'BBB', value: 70000.5 }),
    L('pct_change', { symbol: 'C00001', name: 'CCC', value: -10 }),
    L('high52', { symbol: 'D00001', name: 'DDD', value: null }),
    L('low52', { symbol: 'E00001', name: 'EEE', value: null }),
    L('golden_cross', { symbol: 'F00001', name: 'FFF', value: null }),
    L('dead_cross', { symbol: 'G00001', name: 'GGG', value: null }),
  ]
  const r = convertLegacy(rows, [], evName, seq())
  assert.deepEqual({ dup: r.dup, cross: r.cross, other: r.other, over: r.over, total: r.total }, { dup: 0, cross: 2, other: 0, over: 0, total: 7 })
  assert.deepEqual(r.add.map(a => [a.event, a.target, a.dir, a.value]), [
    ['U1', 'A00001', 'up', 90000], ['U1', 'B00001', 'down', 70000.5], ['U2', 'C00001', 'down', 10], ['B1', 'D00001', undefined, undefined], ['B1', 'E00001', undefined, undefined],
  ])
  assert.ok(r.add.every(a => a.repeat === 'each' && a.ring === true && a.enabled === true))
  // 종목 이름이 조건 이름에 든다 — 값 · 방향까지 읽힌다
  assert.deepEqual(r.add.map(a => a.name), ['AAA 90,000 위로', 'BBB 70,000.50 아래로', 'CCC 등락 ±10%', 'DDD 52주 신고저', 'EEE 52주 신고저'])
  assert.deepEqual(r.add.map(a => a.id), ['p1', 'p2', 'p3', 'p4', 'p5'])
})

test('겹침: 이미 있는 대상 · 사건 · 값은 건너뛴다(방향이 다르거나 값이 다르면 다른 조건) · 이번 묶음 안의 겹침도', () => {
  const rows = [
    L('price_above'),                                   // 기존과 같음 → 건너뜀
    L('price_above', { value: 85000 }),                 // 값이 다름 → 가져옴
    L('price_below'),                                   // 방향이 다름 → 가져옴
    L('price_below'),                                   // 방금 가져올 것과 같음 → 건너뜀
    L('pct_change', { value: 5 }), L('pct_change', { value: -5 }),   // 같은 ±5% → 하나
    L('high52', { value: null }), L('low52', { value: null }),       // 신고가 · 신저가는 한 사건 → 하나
  ]
  const r = convertLegacy(rows, [U1()], evName, seq())
  assert.deepEqual(r.add.map(condKey), ['005930|U1|up|85000', '005930|U1|down|80000', '005930|U2|5', '005930|B1'])
  assert.equal(r.dup, 4)
  assert.equal(r.total, 8)
  // 두 번째로 가져오면 모두 겹친다
  const again = convertLegacy(rows, [U1(), ...r.add], evName, seq())
  assert.equal(again.add.length, 0)
  assert.equal(again.dup, 8)
})

test('이 기기에 방향 없는 등락률 조건이 이미 있어도 같은 값이면 겹친다', () => {
  const have = { id: 'e2', event: 'U2', target: '005930', value: 3, repeat: 'each', ring: true, enabled: true } as AlertCond
  const r = convertLegacy([L('pct_change', { value: 3 }), L('pct_change', { value: -3 })], [have], evName, seq())
  assert.equal(r.add.length, 0)
  assert.equal(r.dup, 2)
})

test('가져오지 않는 줄: 그 밖 종류 · 값이 틀림 · 대상 모양이 틀림 · 읽을 수 없는 줄 · 꺼 둔 조건은 꺼진 채', () => {
  const rows = [
    L('z_move', { value: 2 }), L('vol_surge', { value: 300 }),
    L('price_below', { value: 0 }), L('price_above', { value: 'x' }), L('pct_change', { value: 0 }),
    L('high52', { symbol: 'AB C' }), L('high52', { symbol: '' }),
    null, 'text', [],
    L('price_below', { symbol: '000660', name: 'SK하이닉스', value: 200000, enabled: false }),
  ]
  const r = convertLegacy(rows, [], evName, seq())
  assert.equal(r.other, 10)
  assert.equal(r.add.length, 1)
  assert.deepEqual([r.add[0].target, r.add[0].enabled, r.add[0].name], ['000660', false, 'SK하이닉스 200,000 아래로'])
  assert.deepEqual(convertLegacy({ error: 404 }, [], evName), { add: [], dup: 0, cross: 0, other: 0, over: 0, total: 0 })
})

test('Worker 가 받는 모양: 대상 · 이름(≤40자) · 조건 수 한도(100)', () => {
  const long = 'ㄱ'.repeat(60)
  const r = convertLegacy([L('price_below', { name: long })], [], evName, seq())
  assert.equal(r.add[0].name!.length, 40)
  for (const a of r.add) assert.match(a.target, TARGET_RE)
  // 이미 98건이 있으면 2건만 담고 나머지는 한도로 센다
  const have = Array.from({ length: ALERT_CAP - 2 }, (_, i) => U1({ id: `h${i}`, value: i + 1 }))
  const rows = [10, 20, 30, 40].map(v => L('price_below', { value: v }))
  const c = convertLegacy(rows, have, evName, seq())
  assert.equal(c.add.length, 2)
  assert.equal(c.over, 2)
  assert.equal(c.dup, 0)
})
