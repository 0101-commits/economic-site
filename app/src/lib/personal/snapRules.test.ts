// 자가검사: npm test --prefix app — 스냅샷 한국 날짜 · 합치기 규칙 · 올릴지 정하기(snapRules.ts). 저장소 · 네트워크 없이 돈다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { decideSnaps, mergeSnaps, parseSnapPlain, snapPlain, snapsEqual, kstDate, type Snap } from './snapRules.ts'

const s = (d: string, ev: number, src?: 'close' | 'app'): Snap => ({ d, ev, ct: 1000, ...(src ? { src } : {}) })

test('kstDate: UTC 16:30 은 이미 한국 다음 날 — 경계 앞뒤', () => {
  assert.equal(kstDate(Date.parse('2026-10-27T16:30:00Z')), '2026-10-28')
  assert.equal(kstDate(Date.parse('2026-10-27T14:59:59Z')), '2026-10-27')
  assert.equal(kstDate(Date.parse('2026-10-27T15:00:00Z')), '2026-10-28')
  assert.equal(kstDate(Date.parse('2026-12-31T20:00:00Z')), '2027-01-01')
})

test('mergeSnaps: 날짜별로 합치고 날짜순 — 한쪽에만 있는 날짜는 그대로', () => {
  const m = mergeSnaps([s('2026-10-02', 2), s('2026-10-01', 1)], [s('2026-10-03', 3)])
  assert.deepEqual(m.map(x => x.d), ['2026-10-01', '2026-10-02', '2026-10-03'])
})

test('mergeSnaps: 같은 날짜는 close 가 app 을 이긴다 — 어느 쪽에 있든', () => {
  assert.deepEqual(mergeSnaps([s('2026-10-01', 1, 'app')], [s('2026-10-01', 9, 'close')]), [s('2026-10-01', 9, 'close')])
  assert.deepEqual(mergeSnaps([s('2026-10-01', 9, 'close')], [s('2026-10-01', 1, 'app')]), [s('2026-10-01', 9, 'close')])
  assert.deepEqual(mergeSnaps([s('2026-10-01', 1)], [s('2026-10-01', 9, 'close')]), [s('2026-10-01', 9, 'close')])   // 표식 없는 옛 칸도 close 가 이긴다
})

test('mergeSnaps: close 가 아니면 있던 것(앞 인자 — 이 기기)을 남긴다 · 둘 다 close 여도 있던 것', () => {
  assert.deepEqual(mergeSnaps([s('2026-10-01', 1, 'app')], [s('2026-10-01', 2, 'app')]), [s('2026-10-01', 1, 'app')])
  assert.deepEqual(mergeSnaps([s('2026-10-01', 1)], [s('2026-10-01', 2, 'app')]), [s('2026-10-01', 1)])
  assert.deepEqual(mergeSnaps([s('2026-10-01', 1, 'close')], [s('2026-10-01', 2, 'close')]), [s('2026-10-01', 1, 'close')])
})

test('mergeSnaps: 730건 상한 — 가장 새 것을 남긴다 · 깨진 칸은 버린다', () => {
  const day = (i: number) => new Date(Date.UTC(2024, 0, 1 + i)).toISOString().slice(0, 10)
  const a = Array.from({ length: 800 }, (_, i) => s(day(i), i))
  const m = mergeSnaps(a, [{ d: 'x' } as unknown as Snap, null as unknown as Snap, s('bad', 1)])
  assert.equal(m.length, 730)
  assert.equal(m[m.length - 1].d, day(799))
  assert.equal(m[0].d, day(70))
})

test('snapPlain · parseSnapPlain: Part A 평문 {v:1, at, snaps} 그대로 — 모르는 칸은 버린다', () => {
  const p = snapPlain([s('2026-10-01', 1, 'close'), s('2026-10-02', 2)], '2026-10-27T00:00:00.000Z')
  assert.deepEqual(p, { v: 1, at: '2026-10-27T00:00:00.000Z', snaps: [{ d: '2026-10-01', ev: 1, ct: 1000, src: 'close' }, { d: '2026-10-02', ev: 2, ct: 1000 }] })
  assert.deepEqual(parseSnapPlain({ v: 1, snaps: [{ d: '2026-10-01', ev: 1.4, ct: 2, src: 'zzz', extra: 1 }, { d: 5 }, null, { d: '2026-10-02', ev: 'x', ct: 1 }] }), [{ d: '2026-10-01', ev: 1, ct: 2 }])
  assert.throws(() => parseSnapPlain([1, 2]))
})

test('decideSnaps: 서버에 없는 날짜가 이 기기에 있으면 올린다 · 같으면 올리지 않는다', () => {
  const local = [s('2026-10-01', 1, 'app'), s('2026-10-02', 2, 'app')]
  const d = decideSnaps(local, [s('2026-10-01', 1, 'app')])
  assert.equal(d.push, true); assert.equal(d.writeLocal, false); assert.equal(d.merged.length, 2)
  const same = decideSnaps(local, local)
  assert.equal(same.push, false); assert.equal(same.writeLocal, false)
})

test('decideSnaps: 서버에만 있는 날짜는 받기만(올리지 않는다) · 서버 close 가 이 기기 app 을 이기면 받기만', () => {
  const d = decideSnaps([s('2026-10-01', 1, 'app')], [s('2026-10-01', 9, 'close'), s('2026-10-02', 2, 'close')])
  assert.equal(d.writeLocal, true); assert.equal(d.push, false)
  assert.deepEqual(d.merged.map(x => x.ev), [9, 2])
})

test('decideSnaps: 같은 날짜가 close 아닌 값으로 다르면 이 기기 것을 남기고 올린다(app 이 서버보다 새 값) · 둘 다 비면 아무것도 안 함', () => {
  const d = decideSnaps([s('2026-10-01', 5, 'app')], [s('2026-10-01', 1, 'app')])
  assert.equal(d.push, true); assert.equal(d.merged[0].ev, 5)
  const none = decideSnaps([], null)
  assert.equal(none.push, false); assert.equal(none.writeLocal, false)
  const fromNull = decideSnaps([s('2026-10-01', 1, 'app')], null)
  assert.equal(fromNull.push, true)
})

test('snapsEqual: 칸 순서와 무관', () => {
  assert.equal(snapsEqual([s('2026-10-01', 1, 'app')], [{ src: 'app', ct: 1000, ev: 1, d: '2026-10-01' }]), true)
  assert.equal(snapsEqual([s('2026-10-01', 1, 'app')], [s('2026-10-01', 1)]), false)
})
