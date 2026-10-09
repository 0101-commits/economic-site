// 자가검사: npm test --prefix app — v1 → v2 변환(서버 subscribe.upgrade_prefs 와 같은 결과) · 꾸러미 전환
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { defaultSettings, normSettings, PACKAGE_PRESET, setPackage, upgradeAlert, upgradePrefs } from './prefsV2.ts'

const V1 = (type: string, cond: Record<string, unknown>, o: Record<string, unknown> = {}) =>
  ({ id: 'p1', target: 'usdkrw', type, cond, repeat: 'once', channels: ['push'], enabled: true, ...o })

test('upgradePrefs 1 · price → U1: op 가 방향, 값 그대로, armedAt 은 조건 밖으로, daily → each', () => {
  assert.deepEqual(upgradeAlert(V1('price', { op: '>=', value: 1400 })),
    { id: 'p1', target: 'usdkrw', repeat: 'once', enabled: true, event: 'U1', ring: true, dir: 'up', value: 1400 })
  assert.deepEqual(upgradeAlert(V1('price', { op: '<=', value: 2500, armedAt: '2026-10-01T00:00:00.000Z' }, { repeat: 'daily', channels: ['discord'] })),
    { id: 'p1', target: 'usdkrw', repeat: 'each', enabled: true, event: 'U1', ring: true, dir: 'down', value: 2500, armedAt: '2026-10-01T00:00:00.000Z' })
})

test('upgradePrefs 2 · pct → U2: 값은 절댓값, 부호가 방향 · 채널이 비면 폰으로 본다', () => {
  assert.deepEqual(upgradeAlert(V1('pct', { op: '<=', value: -3 }, { channels: [] })),
    { id: 'p1', target: 'usdkrw', repeat: 'once', enabled: true, event: 'U2', ring: true, value: 3, dir: 'down' })
  assert.equal(upgradeAlert(V1('pct', { op: '>=', value: 5 }))!.dir, 'up')
})

test('upgradePrefs 3 · high52 → B1: side low 면 아래', () => {
  assert.equal(upgradeAlert(V1('high52', { side: 'low' }))!.dir, 'down')
  assert.deepEqual(upgradeAlert(V1('high52', { side: 'high' })), { id: 'p1', target: 'usdkrw', repeat: 'once', enabled: true, event: 'B1', ring: true, dir: 'up' })
})

test('upgradePrefs 4 · event → E1 · lens → C1 · 모르는 종류는 버림 · 모르는 채널만 있으면 울림 꺼짐', () => {
  assert.equal(upgradeAlert(V1('event', { daysBefore: 1 }))!.event, 'E1')
  assert.deepEqual(upgradeAlert(V1('lens', { state: 'near' }, { channels: ['x'] })), { id: 'p1', target: 'usdkrw', repeat: 'once', enabled: true, event: 'C1', ring: false })
  assert.equal(upgradeAlert(V1('golden', {})), null)
  assert.equal(upgradeAlert('x'), null)
})

test('upgradePrefs 5 · flow → 코스피는 D2, 그 밖(종목)은 D5', () => {
  assert.equal(upgradeAlert(V1('flow', { who: 'foreign' }, { target: 'kospi' }))!.event, 'D2')
  assert.equal(upgradeAlert(V1('flow', { who: 'inst' }, { target: '005930' }))!.event, 'D5')
})

test('upgradePrefs 6 · 문서 한 벌이 서버 upgrade_prefs 출력과 같다(2026-10-05 실행 결과) · v2 조건은 그대로', () => {
  const doc = { v: 1, alerts: [
    V1('price', { op: '>=', value: 1400 }),
    V1('price', { op: '<=', value: 2500, armedAt: '2026-10-01T00:00:00.000Z' }, { id: 'p2', target: 'kospi', repeat: 'daily', channels: ['discord'], enabled: false }),
    V1('pct', { op: '<=', value: -3 }, { id: 'p3', target: '069500', repeat: 'daily', channels: [] }),
    V1('high52', { side: 'low' }, { id: 'p4', target: 'gold', channels: ['push', 'discord'] }),
    V1('event', { daysBefore: 1 }, { id: 'p5', target: 'us10y' }),
    V1('flow', { who: 'foreign' }, { id: 'p6', target: 'kospi', repeat: 'daily' }),
    V1('flow', { who: 'inst' }, { id: 'p7', target: '005930', repeat: 'daily' }),
    V1('lens', { state: 'near' }, { id: 'p8', target: 'us30y', channels: ['x'] }),
    V1('golden', {}, { id: 'p9', target: 'x' }),
    { id: 'p10', event: 'A1', target: '*', strength: 'huge', repeat: 'each', enabled: true },
  ], settings: { updown: 'us', unit: 'won', quiet: null }, scenarios: [] }
  // python -c "from alerts_v2.subscribe import upgrade_prefs; ..." 그대로 옮긴 것
  const server = [
    { id: 'p1', target: 'usdkrw', repeat: 'once', enabled: true, event: 'U1', ring: true, dir: 'up', value: 1400 },
    { id: 'p2', target: 'kospi', repeat: 'each', enabled: false, event: 'U1', ring: true, dir: 'down', value: 2500, armedAt: '2026-10-01T00:00:00.000Z' },
    { id: 'p3', target: '069500', repeat: 'each', enabled: true, event: 'U2', ring: true, value: 3.0, dir: 'down' },
    { id: 'p4', target: 'gold', repeat: 'once', enabled: true, event: 'B1', ring: true, dir: 'down' },
    { id: 'p5', target: 'us10y', repeat: 'once', enabled: true, event: 'E1', ring: true },
    { id: 'p6', target: 'kospi', repeat: 'each', enabled: true, event: 'D2', ring: true },
    { id: 'p7', target: '005930', repeat: 'each', enabled: true, event: 'D5', ring: true },
    { id: 'p8', target: 'us30y', repeat: 'once', enabled: true, event: 'C1', ring: false },
    { id: 'p10', event: 'A1', target: '*', strength: 'huge', repeat: 'each', enabled: true },
  ]
  const p = upgradePrefs(doc)
  assert.equal(p.v, 2)
  assert.deepEqual(p.alerts, server)
  const { kakaoBundleAt: _b, kakaoQuota: _q, ...srv } = {
    briefings: { close: true, evening: false, morning: true, noon: false, us: false, weekly: true }, dailyCap: 6,
    families: { A: true, B: true, C: true, D: true, E: true, F: true, G: true, H: true }, kakaoBundleAt: 18, kakaoQuota: 20,
    package: 'normal', quiet: { from: '23:00', to: '07:00' }, quietAlarm: false, ringChannel: 'push', unit: 'won', updown: 'us',
  }
  assert.deepEqual(p.settings, { ...srv, rememberKey: false, kakaoFriends: false, kakaoRecipients: [], autoQuiet: true })   // v1 의 quiet:null → 서버처럼 기본값
  assert.deepEqual(upgradePrefs(p), p)                                                                    // 두 번 바꿔도 같다
  assert.equal(normSettings({ ...p.settings, quiet: null }).quiet, null)                                  // v2 의 quiet:null = 끔 그대로
  assert.deepEqual(upgradePrefs(null), { v: 2, alerts: [], settings: defaultSettings(), scenarios: [] })
})

test('꾸러미 전환: 상한 · 브리핑이 따라가고 다른 설정은 그대로', () => {
  const s = { ...defaultSettings(), ringChannel: 'kakao' as const, quietAlarm: true }
  const q = setPackage(s, 'quiet')
  assert.equal(q.package, 'quiet')
  assert.equal(q.dailyCap, 3)
  assert.deepEqual(Object.entries(q.briefings).filter(([, v]) => v).map(([k]) => k), ['morning'])
  assert.equal(q.ringChannel, 'kakao')
  assert.equal(q.quietAlarm, true)
  const m = setPackage(q, 'many')
  assert.equal(m.dailyCap, 12)
  assert.ok(Object.values(m.briefings).every(Boolean))
  assert.deepEqual(setPackage(m, 'normal').briefings, defaultSettings().briefings)
  m.briefings.noon = false
  assert.equal(PACKAGE_PRESET.many.briefings.noon, true)   // 바꾼 설정이 꾸러미 원본을 건드리지 않는다
})
