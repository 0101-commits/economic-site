// 자가검사: npm test --prefix app — 원장 묶기(오늘 · 어제 · 그 전) · 거르기 · 사건 탭 셈 · 세기별 1년 횟수
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { eventsFor, familyCount, fromLedger, groupDays, kakaoToday, levelChoices, listEvents, passes, yearCounts, type Dict } from './v2.ts'

const dict: Dict = JSON.parse(readFileSync(new URL('./dict.json', import.meta.url), 'utf8'))
const row = (key: string, ts: string, o: Record<string, unknown> = {}) =>
  ({ key, event: 'A1', target: 'kospi', dir: 'up', level: 'alert', title: `제목 ${key}`, why: '왜', next: '', url: '#/i/kospi', ts, sent: { push: 1, kakao: false }, ...o })

test('원장 묶기: 오늘 · 어제 · 그 전(한국 날짜), 새것이 위, 기록은 빼고, 내 조건은 이 기기 이름으로', () => {
  const rows = [
    row('a', '2026-10-05T09:10:00+09:00'),
    row('b', '2026-10-05T00:30:00+09:00', { level: 'notice' }),
    row('c', '2026-10-04T23:59:00+09:00', { cond: 'p1', event: 'U1', title: '서버 제목' }),
    row('d', '2026-10-04T14:59:59Z'),                                          // = 10/4 23:59:59 KST → 어제
    row('e', '2026-10-01T18:05:12+09:00', { level: 'alarm' }),
    row('f', '2026-10-05T10:00:00+09:00', { level: 'record' }),
    { key: 'bad', ts: '언제' }, null,
  ]
  const feed = fromLedger(rows, new Map([['p1', '달러원 1,400 위로']]))
  assert.deepEqual(feed.map(x => x.key), ['a', 'b', 'd', 'c', 'e'])
  const g = groupDays(feed, '2026-10-05', '2026-10-04')
  assert.deepEqual(g.today.map(x => x.key), ['a', 'b'])
  assert.deepEqual(g.yesterday.map(x => x.key), ['d', 'c'])
  assert.deepEqual(g.older.map(x => x.key), ['e'])
  const c = feed.find(x => x.key === 'c')!
  assert.equal(c.title, '달러원 1,400 위로')
  assert.equal(c.mine, true)
  assert.equal(feed[0].to, '/i/kospi')                                        // 원장 url(#/…) → 화면 주소
  assert.equal(feed[0].next, undefined)                                       // 빈 칸은 안 그린다
  assert.equal(fromLedger(rows, new Map()).find(x => x.key === 'c')!.title, '서버 제목')   // 다른 기기 조건
  assert.deepEqual(fromLedger({ error: 404 }, new Map()), [])
})

test('거르기: 경보 · 알림 · 안내 · 시황 · 내 조건', () => {
  const feed = fromLedger([
    row('a', '2026-10-05T09:00:00+09:00', { level: 'alarm' }), row('b', '2026-10-05T09:01:00+09:00'),
    row('c', '2026-10-05T09:02:00+09:00', { level: 'notice' }), row('d', '2026-10-05T07:30:00+09:00', { level: 'brief' }),
    row('e', '2026-10-05T09:03:00+09:00', { event: 'U2' }),
  ], new Map())
  const keys = (f: Parameters<typeof passes>[1]) => feed.filter(x => passes(x, f)).map(x => x.key).sort().join('')
  assert.equal(keys('all'), 'abcde')
  assert.equal(keys('alarm'), 'a')
  assert.equal(keys('alert'), 'be')
  assert.equal(keys('notice'), 'c')
  assert.equal(keys('brief'), 'd')
  assert.equal(keys('mine'), 'e')
  assert.equal(kakaoToday([row('k', '2026-10-05T09:00:00+09:00', { sent: { kakao: true } }), row('y', '2026-10-04T09:00:00+09:00', { sent: { kakao: true } })], '2026-10-05'), 1)
})

test('사건 탭: 갈래 셈 · 사건 전체 조정으로 끈 것 빼기 · 등급 한 단계 · 폼의 사건 고르기', () => {
  assert.ok(listEvents(dict).every(e => !e.userValue && e.enabled))
  const a = familyCount(dict, 'A', [])
  assert.deepEqual(a, { on: 3, watch: 2 })                                      // A1 · A2 · A5 켜짐, A3 · A4 관심
  assert.deepEqual(familyCount(dict, 'A', [{ id: 'x', event: 'A1', target: '*', repeat: 'each', enabled: false }]), { on: 2, watch: 2 })
  assert.deepEqual(levelChoices('alert'), ['notice', 'alert', 'alarm'])
  assert.deepEqual(levelChoices('alarm'), ['alert', 'alarm'])
  assert.deepEqual(levelChoices('record'), ['record', 'notice'])
  const ids = (t: string, s = false) => eventsFor(dict, t, s).map(e => e.id).join(' ')
  assert.equal(ids('kospi'), 'A1 A5 B1 B2 U1 U2')
  assert.equal(ids('usdkrw'), 'A2 B1 B2 C1 U1 U2')                            // 렌즈 선은 C1 기본 켜짐 목록으로
  assert.equal(ids('vix'), 'C3 U1 U2')
  assert.equal(ids('005930', true), 'D5 F1 F2 U1 U2')
})

test('yearCounts: 세기별 문턱(min(max(kσ,0.5%),5%)) 이상인 날 수, 점이 모자라면 null', () => {
  const sig = dict.strengths
  assert.equal(yearCounts([['2026-01-01', 100]], sig), null)
  // 평소 ±0.1% 로 오가다 +3% 하루, −6% 하루 → 세기마다 그 둘만 걸린다(σ 가 작아 문턱이 하한 0.5%)
  const s: [string, number][] = []
  let v = 100
  for (let i = 0; i < 260; i++) {
    v *= i === 100 ? 1.03 : i === 200 ? 0.94 : i % 2 ? 1.001 : 0.999
    s.push([`d${i}`, v])
  }
  const c = yearCounts(s, sig)!
  assert.deepEqual(Object.keys(c), ['normal', 'big', 'huge'])               // 「값 직접」(sigma null)은 셀 것이 없다
  assert.ok(c.normal >= c.big && c.big >= c.huge)
  assert.equal(c.huge, 2)
})
