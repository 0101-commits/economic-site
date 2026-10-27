// 자가검사: npm test --prefix app — 멤버 관리 순수 로직
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { adminErrText, cleanName, kakaoText, lastSeenText, parseMembers } from './members.ts'

test('adminErrText: 코드별 글', () => {
  assert.match(adminErrText({ status: 409, error: 'not_migrated' }), /멤버 칸이 준비되지 않았습니다/)
  assert.match(adminErrText({ status: 403, error: 'owner_only' }), /마스터만/)
  assert.match(adminErrText({ status: 403, error: 'owner_unpausable' }), /멈출 수 없/)
  assert.match(adminErrText({ status: 400, error: 'bad_name' }), /1~20자/)
  assert.match(adminErrText({ status: 400, error: 'bad_patch' }), /맞지 않/)
  assert.match(adminErrText({ status: 404 }), /없습니다/)
  assert.match(adminErrText({ status: 429 }), /1분/)
  assert.match(adminErrText({ status: 0, error: 'network' }), /닿지 못/)
  assert.match(adminErrText({ status: 403, error: 'paused' }), /멈춤/)
  assert.match(adminErrText({ status: 500, error: 'x' }), /\(x\)/)
})

test('lastSeenText: 오늘 · M/D · 없음', () => {
  assert.equal(lastSeenText('2026-10-27', '2026-10-27'), '오늘')
  assert.equal(lastSeenText('2026-10-20', '2026-10-27'), '10/20')
  assert.equal(lastSeenText('2026-01-05', '2026-10-27'), '1/5')
  assert.equal(lastSeenText(null, '2026-10-27'), '없음')
  assert.equal(lastSeenText('', '2026-10-27'), '없음')
  assert.equal(lastSeenText('엉뚱', '2026-10-27'), '없음')
})

test('kakaoText', () => {
  assert.equal(kakaoText('ECOM-AAAA-BBBB-CCCC'), 'ECOM 시장 화면 https://ecom-terminal.pages.dev 에서 이 키로 들어오세요: ECOM-AAAA-BBBB-CCCC\n'
    + '관심 종목·알림 조건은 운영 서버에 저장되며 운영자가 볼 수 있습니다. 보유는 본인 키로 잠겨 운영자도 볼 수 없습니다.')
})

test('parseMembers: 마스터 맨 위 · 틀린 행 버림', () => {
  const r = parseMembers({ users: [{ uid: 'b', name: 'B', role: 'member', status: 'paused', lastSeenDay: null, pushCount: 2 }, null, { name: 'x' }, { uid: 'a', name: 'M', role: 'owner', status: 'active', lastSeenDay: '2026-10-27', pushCount: 0 }] })
  assert.deepEqual(r.map(u => u.uid), ['a', 'b'])
  assert.equal(r[1].status, 'paused')
  assert.deepEqual(parseMembers(undefined), [])
})

test('cleanName: 1~20자', () => {
  assert.equal(cleanName('  멤버 A '), '멤버 A')
  assert.equal(cleanName('   '), '')
  assert.equal(cleanName('가'.repeat(20)), '가'.repeat(20))
  assert.equal(cleanName('가'.repeat(21)), '')
})
