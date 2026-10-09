// 자가검사: npm test --prefix app — 묶음 다시 읽기 판정(장중 5분 · 탭 복귀 30분) · 매매중단 배너 한 줄
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { AWAY_MS, haltLine, inSession, POLL_MS, reloadDue, type Halt } from './refresh.ts'

const at = (s: string) => Date.parse(s)

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

test('reloadDue: 장중에는 5분이 지나야, 장 밖에서는 다시 읽지 않는다', () => {
  const open = at('2026-10-09T10:00:00+09:00'), night = at('2026-10-09T20:00:00+09:00')
  assert.equal(reloadDue(open, open - POLL_MS), true)
  assert.equal(reloadDue(open, open - POLL_MS + 1000), false)
  assert.equal(reloadDue(night, night - 3 * 3600_000), false)
})

test('reloadDue: 탭 복귀는 장과 상관없이 30분 넘게 숨었을 때만', () => {
  const night = at('2026-10-10T20:00:00+09:00'), open = at('2026-10-09T10:00:00+09:00')
  assert.equal(reloadDue(night, night - 3 * 3600_000, AWAY_MS + 1), true)
  assert.equal(reloadDue(night, night - 3 * 3600_000, AWAY_MS), false)
  assert.equal(reloadDue(open, open - POLL_MS * 3, 60_000), false)          // 잠깐 숨은 것은 장중이라도 복귀로는 안 읽는다(장중 주기가 맡는다)
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
