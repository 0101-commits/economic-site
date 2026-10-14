// 자가검사: npm test --prefix app — 묶음 다시 읽기 판정(nextAt 일정 · 장중 5분 · 탭 복귀) · 바뀐 묶음 고르기 · 첫 화면 보관 만료 · 판 이름 · 매매중단 배너 한 줄
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { AWAY_MS, buildOf, changedBundles, haltLine, homeCacheFrom, inSession, HOME_CACHE_MS, POLL_MS, reloadDue, TICK_MS, waitMs, type Halt } from './refresh.ts'
import type { Market } from './format.ts'

const at = (s: string) => Date.parse(s)

// 계약 C1 의 장 상태 — 10/14(수) 국내 정규장 · 미국은 그날 밤 22:30 개장
const MK: Market = {
  state: 'open', label: '정규장', today: '2026-10-14', session: '2026-10-14', nextOpen: '2026-10-15T09:00:00+09:00',
  openAt: '2026-10-14T09:00:00+09:00', closeAt: '2026-10-14T15:30:00+09:00',
  us: { state: 'closed', label: '마감', session: '2026-10-13', openAt: '2026-10-14T22:30:00+09:00', closeAt: '2026-10-15T05:00:00+09:00', nextOpen: '2026-10-14T22:30:00+09:00' },
}
const HOLIDAY: Market = { state: 'holiday', label: '휴장', openAt: null, closeAt: null, us: { state: 'holiday', openAt: null, closeAt: null } }

test('inSession: 묶음 market 이 있으면 그 개장 · 마감 칸으로, 마감 뒤 10분까지(15:35 종가 묶음)', () => {
  const on = (s: string, m: Market = MK) => inSession(new Date(s), m)
  assert.equal(on('2026-10-14T08:59:00+09:00'), false)
  assert.equal(on('2026-10-14T09:00:00+09:00'), true)
  assert.equal(on('2026-10-14T15:39:59+09:00'), true)    // 마감 15:30 + 10분 안 — 시계 판정은 15:30 에 멈췄다(F2)
  assert.equal(on('2026-10-14T15:40:00+09:00'), false)
  assert.equal(on('2026-10-14T23:00:00+09:00'), true)    // 미국 정규장(묶음 us 칸)
  assert.equal(on('2026-10-15T05:10:00+09:00'), false)
  // 휴장일: 국내 시각 칸이 null 이면 평일 낮이어도 장 밖 — 시계 판정은 휴장일을 몰랐다
  assert.equal(on('2026-10-09T10:00:00+09:00', HOLIDAY), false)
  assert.equal(inSession(new Date('2026-10-09T10:00:00+09:00')), true)
  // 옛 묶음(시각 칸 · 미국 칸 없음)은 시계로, 미국 칸에 시각이 없으면 state 로
  assert.equal(on('2026-10-09T10:00:00+09:00', { state: 'open', label: '정규장' }), true)
  assert.equal(on('2026-10-09T20:00:00+09:00', { state: 'closed', label: '장마감', us: { state: 'open' } }), true)
})

test('reloadDue: nextAt + 30초에 읽고, 그 뒤에도 새 묶음이 없으면 5분마다', () => {
  const last = at('2026-10-14T14:36:00+09:00'), nextAt = '2026-10-14T14:41:30+09:00'
  assert.equal(reloadDue(at('2026-10-14T14:41:59+09:00'), last, { nextAt, market: MK }), false)
  assert.equal(reloadDue(at('2026-10-14T14:42:00+09:00'), last, { nextAt, market: MK }), true)
  // 14:42 에 읽었는데 meta 가 그대로(nextAt 이 지남) — 5분 규칙. 나올 묶음이 늦을 뿐이라 장 밖에서도 센다
  const read = at('2026-10-14T14:42:00+09:00')
  assert.equal(reloadDue(read + POLL_MS - 1000, read, { nextAt, market: MK }), false)
  assert.equal(reloadDue(read + POLL_MS, read, { nextAt, market: MK }), true)
  // 장 밖: 다음 크론 런(:07 + 2분)을 nextAt 이 알려 준다 — 장중 판정과 상관없이 그때 읽는다
  const night = at('2026-10-14T20:10:00+09:00')
  assert.equal(reloadDue(at('2026-10-14T21:09:29+09:00'), night, { nextAt: '2026-10-14T21:09:00+09:00', market: MK }), false)
  assert.equal(reloadDue(at('2026-10-14T21:09:30+09:00'), night, { nextAt: '2026-10-14T21:09:00+09:00', market: MK }), true)
})

test('reloadDue: 숨었다 돌아오면 읽을 때가 지났을 때 곧바로(nextAt 이 있으면 30분 규칙 대신)', () => {
  const last = at('2026-10-14T14:36:00+09:00'), nextAt = '2026-10-14T14:41:30+09:00'
  assert.equal(reloadDue(at('2026-10-14T14:45:00+09:00'), last, { nextAt, hiddenFor: 8 * 60_000 }), true)
  assert.equal(reloadDue(at('2026-10-14T14:40:00+09:00'), last, { nextAt, hiddenFor: 3 * 60_000 }), false)   // 아직 그때가 아니다
})

test('inSession: 한국 정규장 09:00~15:30 KST 평일', () => {
  assert.equal(inSession(new Date('2026-10-09T09:00:00+09:00')), true)    // 금 개장
  assert.equal(inSession(new Date('2026-10-09T15:29:00+09:00')), true)
  assert.equal(inSession(new Date('2026-10-09T15:30:00+09:00')), false)   // 마감 = 닫힘
  assert.equal(inSession(new Date('2026-10-09T08:59:00+09:00')), false)
  assert.equal(inSession(new Date('2026-10-10T10:00:00+09:00')), false)   // 토
})

test('inSession: 미국 정규장 09:30~16:00 뉴욕 — 서머타임은 시간대가 맞춘다', () => {
  assert.equal(inSession(new Date('2026-10-08T22:30:00+09:00')), true)    // 목 09:30 EDT
  assert.equal(inSession(new Date('2026-10-08T22:29:00+09:00')), false)
  assert.equal(inSession(new Date('2026-10-09T04:59:00+09:00')), true)    // 목 15:59 EDT
  assert.equal(inSession(new Date('2026-10-09T05:00:00+09:00')), false)
  assert.equal(inSession(new Date('2026-01-15T23:29:00+09:00')), false)   // 겨울: 09:29 EST
  assert.equal(inSession(new Date('2026-01-15T23:30:00+09:00')), true)
  assert.equal(inSession(new Date('2026-10-10T23:30:00+09:00')), false)   // 토 10:30 EDT
})

test('reloadDue: nextAt 이 없는 옛 meta 는 종전대로 — 장중 5분, 탭 복귀는 30분 넘게 숨었을 때 장과 상관없이', () => {
  const open = at('2026-10-09T10:00:00+09:00'), night = at('2026-10-09T20:00:00+09:00'), sat = at('2026-10-10T20:00:00+09:00')
  assert.equal(reloadDue(open, open - POLL_MS), true)
  assert.equal(reloadDue(open, open - POLL_MS + 1000), false)
  assert.equal(reloadDue(night, night - 3 * 3600_000), false)
  assert.equal(reloadDue(sat, sat - 3 * 3600_000, { hiddenFor: AWAY_MS + 1 }), true)
  assert.equal(reloadDue(sat, sat - 3 * 3600_000, { hiddenFor: AWAY_MS }), false)
  assert.equal(reloadDue(open, open - POLL_MS * 3, { hiddenFor: 60_000 }), true)   // 장중이면 돌아온 순간 5분 규칙으로 곧바로
  assert.equal(reloadDue(open, open - POLL_MS, { market: HOLIDAY }), false)        // 묶음이 휴장이라 하면 평일 낮이어도 읽지 않는다
})

test('waitMs: nextAt + 30초가 1분 안이면 딱 그때, 아니면 1분 뒤 다시 본다', () => {
  const nextAt = '2026-10-14T14:41:30+09:00'
  assert.equal(waitMs(at('2026-10-14T14:41:45+09:00'), nextAt), 15_000)
  assert.equal(waitMs(at('2026-10-14T14:38:00+09:00'), nextAt), TICK_MS)
  assert.equal(waitMs(at('2026-10-14T14:43:00+09:00'), nextAt), TICK_MS)   // 지났다
  assert.equal(waitMs(at('2026-10-14T14:43:00+09:00'), undefined), TICK_MS)
})

test('changedBundles: 지문이 그대로인 묶음은 빼고, 어느 쪽이든 지문이 없으면 전부', () => {
  const names = ['home', 'market-global', 'news']
  assert.deepEqual(changedBundles(names, { home: 'a1', 'market-global': 'b1' }, { home: 'a1', 'market-global': 'b2', news: 'c1' }), ['market-global', 'news'])
  assert.deepEqual(changedBundles(names, undefined, { home: 'a1' }), names)
  assert.deepEqual(changedBundles(names, { home: 'a1' }, undefined), names)
})

test('homeCacheFrom: 값 시각이 24시간 안인 홈만, 깨졌거나 띠가 비었으면 null', () => {
  const home = { asOf: '2026-10-14T17:07:41+09:00', strip: [{ id: 'kospi' }] }
  const raw = (o: object) => JSON.stringify({ at: at('2026-10-14T17:11:00+09:00'), home, dataUpdated: '2026-10-14T17:07:41+09:00', ...o })
  const t = at('2026-10-14T17:07:41+09:00')
  assert.equal(homeCacheFrom(raw({}), t + HOME_CACHE_MS - 1000)?.home.asOf, home.asOf)
  assert.equal(homeCacheFrom(raw({}), t + HOME_CACHE_MS), null)                                   // 하루 넘은 값은 쓰지 않는다
  assert.equal(homeCacheFrom(raw({ dataUpdated: null }), t + HOME_CACHE_MS), null)                // 값 시각이 없으면 홈 asOf
  assert.ok(homeCacheFrom(raw({ dataUpdated: null, home: { strip: [1] } }), t + HOME_CACHE_MS))  // 그것도 없으면 넣은 때(17:11)
  assert.equal(homeCacheFrom(raw({ home: { asOf: home.asOf, strip: [] } }), t), null)
  for (const bad of [null, '{', '[]', '"x"', '{"at":1}']) assert.equal(homeCacheFrom(bad, t), null)
})

test('buildOf: 판 이름 = 진입 JS 파일 이름(vite.config version.json 과 같은 값)', () => {
  assert.equal(buildOf('https://0101-commits.github.io/economic-site/assets/index-Ab12_c-D.js'), 'index-Ab12_c-D.js')
  assert.equal(buildOf('https://0101-commits.github.io/economic-site/next/assets/index-Ab12_c-D.js'), 'index-Ab12_c-D.js')   // 옛 주소 사본도 같은 판
  assert.equal(buildOf('엉터리'), '')
})

test('haltLine: 오늘 발동 · 안 풀림 · 재개 전인 것만 한 줄로', () => {
  const now = at('2026-10-09T14:50:00+09:00')
  const cb: Halt = { type: 'circuit', market: 'KOSPI', stage: 1, triggeredAt: '2026-10-09T14:41:00+09:00', resumeAt: '2026-10-09T15:11:00+09:00' }
  assert.equal(haltLine([cb], now), '코스피 서킷브레이커 1단계 발동 중 · 15:11 재개')
  assert.equal(haltLine([cb], at('2026-10-09T15:12:00+09:00')), null)                              // 재개 시각이 지났다
  assert.equal(haltLine([{ ...cb, resolvedAt: '2026-10-09T14:49:00+09:00' }], now), null)          // 풀린 기록
  assert.equal(haltLine([{ ...cb, triggeredAt: '2026-10-08T14:41:00+09:00' }], now), null)         // 어제 발동
  assert.equal(haltLine([{ ...cb, stage: 3, endOfDay: true, resumeAt: null }], at('2026-10-09T15:20:00+09:00')), '코스피 서킷브레이커 3단계 발동 중 · 오늘 거래 끝')
  const sc: Halt = { type: 'sidecar', market: 'KOSDAQ', triggeredAt: '2026-10-09T14:45:00+09:00', resumeAt: null }
  assert.equal(haltLine([cb, sc], now), '코스피 서킷브레이커 1단계 발동 중 · 15:11 재개 · 코스닥 사이드카 발동 중')
  assert.equal(haltLine([], now), null)
  assert.equal(haltLine(undefined, now), null)
})
