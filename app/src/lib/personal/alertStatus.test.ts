// 자가검사: npm test --prefix app — 알림 조건 id · 상태 낱말 · 다시 켜기
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { condId, condStatus, rearm, type FiredRec } from './alertStatus.ts'
import type { AlertCond } from './store'

const PREFS_ID = /^[A-Za-z0-9._:^=\-]{1,64}$/   // cloudflare-worker/worker.js 와 같은 식
const A = (o: Partial<AlertCond> = {}): AlertCond =>
  ({ id: 'p1', target: 'kospi', type: 'price', cond: { op: '>=', value: 2900 }, repeat: 'once', channels: ['push'], enabled: true, ...o })
const TS = Math.floor(Date.parse('2026-10-02T09:05:00+09:00') / 1000)
const TODAY = '2026-10-02'

test('condId: Worker 가 받는 모양이고 겹치지 않는다', () => {
  const ids = new Set(Array.from({ length: 200 }, () => condId()))
  assert.equal(ids.size, 200)
  for (const id of ids) assert.match(id, PREFS_ID)
  assert.equal(condId(0, 0.5), 'p0i')
})

test('condStatus: 꺼짐 · 대기 · 발동됨 · 오늘 발동', () => {
  assert.deepEqual(condStatus(A({ enabled: false }), { fired: true, ts: TS }, TODAY), { kind: 'off', text: '꺼짐' })
  assert.deepEqual(condStatus(A(), undefined, TODAY), { kind: 'wait', text: '대기' })
  assert.deepEqual(condStatus(A(), { fired: true, ts: TS, date: '20261002' }, TODAY), { kind: 'fired', text: '발동됨 10/2 09:05' })
  const lensOnly: FiredRec & { lensState: string } = { lensState: 'below' }   // 기준선만 있는 렌즈 기록(아직 안 울림)
  assert.equal(condStatus(A({ type: 'lens' }), lensOnly, TODAY).kind, 'wait')
  const daily = A({ repeat: 'daily' })
  assert.deepEqual(condStatus(daily, { date: '20261002', ts: TS }, TODAY), { kind: 'today', text: '오늘 발동 10/2' })
  assert.equal(condStatus(daily, { date: '20261001', ts: TS - 86_400 }, TODAY).kind, 'wait')
})

test('rearm: 같은 id 로 대기가 되고, 기기 시계가 늦어도 마지막 발동 뒤로 찍는다', () => {
  const rec = { fired: true, ts: TS }
  const late = rearm(A(), rec, (TS - 3600) * 1000)                      // 시계가 한 시간 늦은 기기
  assert.equal(late.id, 'p1')
  assert.equal(late.cond.op, '>=')
  assert.equal(Date.parse(String(late.cond.armedAt)) / 1000, TS + 1)
  assert.equal(condStatus(late, rec, TODAY).kind, 'wait')
  const now = rearm(A(), rec, (TS + 60) * 1000)
  assert.equal(Date.parse(String(now.cond.armedAt)) / 1000, TS + 60)
  assert.equal(condStatus(now, { fired: true, ts: TS + 120 }, TODAY).kind, 'fired')   // 다시 울린 뒤엔 다시 「발동됨」
})
