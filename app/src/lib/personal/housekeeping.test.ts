// 자가검사: npm test --prefix app — 알림 자동 정리(180일 조용 「한 번」 → 꺼짐 · 90일 미열람 → 조용히)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createdAt, DAY, housekeep } from './housekeeping.ts'
import { defaultSettings } from './prefsV2.ts'
import { condId } from './alertStatus.ts'
import type { AlertCond, Prefs } from './store'

const T0 = Date.parse('2026-01-01T00:00:00Z')
const P = (alerts: AlertCond[], pkg: Prefs['settings']['package'] = 'normal'): Prefs =>
  ({ v: 2, alerts, settings: { ...defaultSettings(), package: pkg }, scenarios: [] })
const C = (o: Partial<AlertCond>): AlertCond => ({ id: condId(T0), event: 'U1', target: 'usdkrw', value: 1400, dir: 'up', repeat: 'once', ring: true, enabled: true, ...o })

test('180일 동안 안 울린 「한 번」 조건은 꺼짐 + off 표시, 매번 · 최근 울림 · 다시 켠 것은 그대로', () => {
  const quiet = C({ id: condId(T0, 0.1) })
  const each = C({ id: condId(T0, 0.2), repeat: 'each' })
  const rang = C({ id: condId(T0, 0.3) })
  const armed = C({ id: condId(T0, 0.4), armedAt: new Date(T0 + 100 * DAY).toISOString() })
  assert.equal(createdAt(quiet.id), T0)
  const hk0 = { since: T0 }
  // 원장에서 rang 이 울린 것을 본다(7일치) → ring 에 쌓인다
  const r1 = housekeep(P([quiet, each, rang, armed]), hk0, T0 + 10 * DAY, T0 + 10 * DAY, [{ cond: rang.id, ts: new Date(T0 + 9 * DAY).toISOString() }])
  assert.equal(r1.changed, false)
  assert.equal(r1.hk.ring![rang.id], T0 + 9 * DAY)
  const r2 = housekeep(r1.prefs, r1.hk, T0 + 181 * DAY, T0 + 181 * DAY, [])
  assert.equal(r2.changed, true)
  assert.deepEqual(r2.prefs.alerts.map(a => a.enabled), [false, true, true, true])
  assert.deepEqual(r2.hk.off, [quiet.id])
  assert.equal(r2.prefs.settings.package, 'normal')
  // 처음 정리하는 기기(since 없음)는 그날부터 센다 — 옛 조건이 첫날 한꺼번에 꺼지지 않는다
  assert.equal(housekeep(P([quiet]), {}, T0 + 400 * DAY, T0 + 400 * DAY, []).changed, false)
})

test('90일 동안 알림 화면을 안 열면 꾸러미를 조용히로(상한 · 브리핑 같이) + demoted, 이미 조용히면 그대로', () => {
  const p = P([])
  assert.equal(housekeep(p, { since: T0 }, T0 + 89 * DAY, T0, []).changed, false)
  const r = housekeep(p, { since: T0 }, T0 + 91 * DAY, T0, [])
  assert.equal(r.changed, true)
  assert.equal(r.prefs.settings.package, 'quiet')
  assert.equal(r.prefs.settings.dailyCap, 3)
  assert.equal(r.hk.demoted, T0 + 91 * DAY)
  assert.equal(housekeep(r.prefs, r.hk, T0 + 200 * DAY, T0, []).changed, false)
  assert.equal(housekeep(p, { since: T0 }, T0 + 91 * DAY, T0 + 30 * DAY, []).changed, false)   // 30일째에 열었다
  // 설정 › 고급에서 끄면(autoQuiet false) 내리지 않는다
  const off = { ...p, settings: { ...p.settings, autoQuiet: false } }
  assert.equal(housekeep(off, { since: T0 }, T0 + 91 * DAY, T0, []).changed, false)
})
