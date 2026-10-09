// 자가검사: npm test --prefix app — 알림 조건 id · 상태 7 · 다시 켜기 · 이름
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { armU1, condId, condName, condStatus, prefillTarget, rearm, repeatNote, TARGET_RE, type LedgerRow } from './alertStatus.ts'
import type { AlertCond } from './store'

const PREFS_ID = /^[A-Za-z0-9._:^=\-]{1,64}$/   // cloudflare-worker/worker.js 와 같은 식
const A = (o: Partial<AlertCond> = {}): AlertCond =>
  ({ id: 'p1', event: 'U1', target: 'usdkrw', value: 1400, dir: 'up', repeat: 'each', ring: true, enabled: true, ...o })
const TS = Math.floor(Date.parse('2026-10-02T09:05:00+09:00') / 1000)
const NOW = (TS + 3600) * 1000
const row = (o: Partial<LedgerRow> = {}): LedgerRow => ({
  key: 'U1:usdkrw:up:abc', event: 'U1', target: 'usdkrw', level: 'alert', title: 't', ts: '2026-10-02T09:05:00+09:00', cond: 'p1',
  sent: { push: 1, kakao: false, discord: true, bundled: false, held: false }, ...o,
})

test('condId: Worker 가 받는 모양이고 겹치지 않는다', () => {
  // 서로 다른 밀리초 → 겹치지 않음(보장). 난수만으로 2000개를 같은 순간에 뽑으면 36^6 공간에서 생일 충돌이
  // 런당 ~0.1% 라 Pages 배포가 가끔 이 줄에서 죽었다(2026-10-08 13:24Z, 1999 !== 2000).
  const ids = new Set(Array.from({ length: 2000 }, (_, i) => condId(TS * 1000 + i)))
  assert.equal(ids.size, 2000)
  assert.match(condId(), PREFS_ID)
  for (const id of ids) assert.match(id, PREFS_ID)
  assert.equal(condId(0, 0.5), 'p0i00000')          // 임의 부분은 늘 6자(짧은 난수도 채운다)
  assert.equal(condId(0, 0.123456789).length, 1 + 1 + 6)
  assert.notEqual(condId(1, 0.5), condId(1, 0.25))   // 같은 밀리초, 다른 난수
})

test('상태 7: 대기 · 울림 · 멈춤 · 묶임 · 보류 · 꺼짐 · 이 기기에만', () => {
  assert.deepEqual(condStatus(A(), [], undefined, true, false, NOW), { kind: 'wait', text: '대기' })
  assert.deepEqual(condStatus(A(), [row()], undefined, true, false, NOW), { kind: 'rang', text: '울림 10/2 09:05' })
  assert.deepEqual(condStatus(A({ repeat: 'once' }), [row()], undefined, true, false, NOW), { kind: 'stopped', text: '멈춤' })
  assert.deepEqual(condStatus(A(), [row({ sent: { bundled: true } })], undefined, true, false, NOW), { kind: 'bundled', text: '묶임' })
  assert.deepEqual(condStatus(A(), [row({ sent: { held: true } })], undefined, true, false, NOW), { kind: 'held', text: '보류 → 07:30' })
  assert.deepEqual(condStatus(A({ enabled: false }), [row()], undefined, true, false, NOW), { kind: 'off', text: '꺼짐' })
  assert.deepEqual(condStatus(A(), [], undefined, false, false, NOW), { kind: 'local', text: '이 기기만 — 울리지 않음' })
})

test('상태: 다른 조건의 행은 안 본다 · 가장 늦은 행이 기준 · 보류는 12시간 뒤 울림 · 자동 정리 꺼짐', () => {
  assert.equal(condStatus(A(), [row({ cond: 'p2' })], undefined, true, false, NOW).kind, 'wait')
  const late = row({ ts: '2026-10-02T10:00:00+09:00', sent: { bundled: true } })
  assert.equal(condStatus(A(), [row(), late], undefined, true, false, NOW).kind, 'bundled')
  assert.equal(condStatus(A(), [row({ sent: { held: true } })], undefined, true, false, NOW + 86_400_000).kind, 'rang')
  assert.equal(condStatus(A({ enabled: false }), [], undefined, true, true, NOW).text, '180일 조용 · 꺼짐')
})

test('상태: 현행 서버 공개 기록(alerts_state._prefs)도 읽는다 — 동기화가 꺼져도 지난 울림은 그대로', () => {
  assert.equal(condStatus(A({ repeat: 'once' }), [], { fired: true, ts: TS }, true, false, NOW).kind, 'stopped')
  assert.deepEqual(condStatus(A(), [], { date: '20261002', ts: TS }, false, false, NOW), { kind: 'rang', text: '울림 10/2 09:05' })
  assert.equal(condStatus(A({ repeat: 'once' }), [], { fired: true, ts: TS }, false, false, NOW).kind, 'stopped')
})

test('rearm: 같은 id 로 대기가 되고, 기기 시계가 늦어도 마지막 울림 뒤로 찍는다', () => {
  const once = A({ repeat: 'once' })
  const late = rearm(once, [row()], undefined, (TS - 3600) * 1000)                // 시계가 한 시간 늦은 기기
  assert.equal(late.id, 'p1')
  assert.equal(Date.parse(late.armedAt!) / 1000, TS + 1)
  assert.equal(condStatus(late, [row()], undefined, true, false, NOW).kind, 'rang')   // 멈춤이 풀린다(지난 울림은 그대로 보임)
  const now = rearm(once, [], { fired: true, ts: TS }, (TS + 60) * 1000)
  assert.equal(Date.parse(now.armedAt!) / 1000, TS + 60)
  assert.equal(condStatus(now, [row({ ts: '2026-10-02T09:07:00+09:00' })], undefined, true, false, NOW).kind, 'stopped')   // 다시 울린 뒤엔 다시 멈춤
})

test('armSide: 저장 · 켜기 때 그 순간 쪽을 싣는다(서버 user_hits 와 같은 규칙, 값 모르면 뺀다)', () => {
  const at = (TS + 60) * 1000
  assert.equal(armU1(A(), 1410, [], undefined, at).armSide, 'u')                       // 위로 조건 · 이미 위
  assert.equal(armU1(A(), 1400, [], undefined, at).armSide, 'u')                       // 같은 값 = 넘은 쪽
  assert.equal(armU1(A({ dir: 'down' }), 1400, [], undefined, at).armSide, 'd')
  assert.equal(armU1(A({ dir: 'down' }), 1401, [], undefined, at).armSide, 'u')
  const off = armU1(A({ armSide: 'd' }), null, [], undefined, at)                      // 값 모름 — 예전 쪽도 지운다
  assert.equal('armSide' in off, false)
  assert.equal(Date.parse(off.armedAt!) / 1000, TS + 60)
  const u2 = A({ event: 'U2', value: 3 })
  assert.equal(armU1(u2, 1410, [], undefined, at), u2)                                 // U1 밖은 그대로
  assert.equal(rearm(A({ repeat: 'once' }), [row()], undefined, (TS - 3600) * 1000, 1390).armSide, 'd')   // 다시 켜기도
})

test('condName: 사용자 이름 · 수준 · 급변 값 · 사전 사건', () => {
  assert.equal(condName(A(), '달러원'), '달러원 1,400 위로')
  assert.equal(condName(A({ dir: 'down', value: 2500.5 }), '코스피'), '코스피 2,500.50 아래로')
  assert.equal(condName(A({ event: 'U2', value: 3 }), 'KODEX 200'), 'KODEX 200 등락 ±3%')
  assert.equal(condName(A({ event: 'B1', value: undefined }), '금', '52주 신고저'), '금 52주 신고저')
  assert.equal(condName(A({ name: '  내 선 ' }), '달러원'), '내 선')
})

test('prefillTarget: 주소의 id 로 새 조건 폼 대상을 채운다 — 사전에 있으면 이름, 없으면 id, 형식이 틀리면 비움', () => {
  const rows = [{ id: 'kospi', label: '코스피 지수', short: '코스피' }, { id: 'usdkrw', label: '원/달러 환율' }]
  assert.deepEqual(prefillTarget('kospi', rows), { id: 'kospi', label: '코스피' })      // 짧은 이름이 먼저
  assert.deepEqual(prefillTarget('usdkrw', rows), { id: 'usdkrw', label: '원/달러 환율' })
  assert.deepEqual(prefillTarget('005930', rows), { id: '005930', label: '005930' })    // 사전에 없는 종목 코드는 그대로
  assert.deepEqual(prefillTarget('kospi', []), { id: 'kospi', label: 'kospi' })         // 사전이 아직 안 왔다 — 이름은 나중에 따라온다
  for (const bad of ['', 'a b', '코스피', 'x'.repeat(65), '<script>']) assert.equal(prefillTarget(bad, rows), null)
  assert.ok(TARGET_RE.test('^KS11') && TARGET_RE.test('KRW=X'))
})

test('U1 은 넘는 순간 — 반복 설명과 쪽 기록(side)만 있는 공개 기록은 「대기」', () => {
  assert.match(repeatNote('U1', 'each'), /넘는 순간.*다시 넘으면 또/)
  assert.match(repeatNote('U1', 'once'), /처음 넘는 순간 한 번/)
  assert.match(repeatNote('U1', 'each'), /이미 넘어 있으면/)
  assert.equal(repeatNote('U2', 'each'), '방향마다 하루 한 번까지 울립니다.')
  assert.equal(repeatNote('U2', 'once'), '한 번 울리면 멈춥니다.')
  assert.deepEqual(condStatus(A(), [], { side: 'u' }, true, false, NOW), { kind: 'wait', text: '대기' })
})
