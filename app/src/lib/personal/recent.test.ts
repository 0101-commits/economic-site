// 자가검사: npm test --prefix app — 최근 본 것: 같은 곳 하나만 · 맨 앞으로 · 8개 상한 · 상세 열기는 이름을 남김 · 깨진 저장본
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { addRecent, recentList, RECENT_MAX } from './recent.ts'

const R = (to: string, label = to, kind = '지표') => ({ label, to, kind })

test('addRecent: 맨 앞에 넣고 같은 곳은 하나만(앞으로 옮김)', () => {
  const a = addRecent(addRecent(addRecent([], R('/i/kospi')), R('/i/005930', '삼성전자', '종목')), R('/i/kospi'))
  assert.deepEqual(a.map(x => x.to), ['/i/kospi', '/i/005930'])
})

test('addRecent: 8개 상한 — 오래된 것부터 밀려난다', () => {
  let a: unknown = []
  for (let i = 0; i < 10; i++) a = addRecent(a, R(`/i/x${i}`))
  const l = a as { to: string }[]
  assert.equal(l.length, RECENT_MAX)
  assert.equal(l[0].to, '/i/x9')
  assert.equal(l[7].to, '/i/x2')
})

test('addRecent: keepLabel — 상세 열기(id 만)는 검색이 적은 이름을 남기고, 처음이면 id 그대로', () => {
  const a = addRecent([R('/i/005930', '삼성전자', '종목')], R('/i/005930', '005930', '종목'), true)
  assert.deepEqual(a, [R('/i/005930', '삼성전자', '종목')])
  assert.deepEqual(addRecent([], R('/i/005930', '005930', '종목'), true), [R('/i/005930', '005930', '종목')])
  assert.equal(addRecent([R('/i/a', '옛 이름')], R('/i/a', '새 이름'))[0].label, '새 이름')   // 검색 고르기는 새 이름으로
})

test('recentList: 깨진 저장본은 빼고 앞 8개', () => {
  assert.deepEqual(recentList(null), [])
  assert.deepEqual(recentList({}), [])
  assert.deepEqual(recentList([null, { to: 1, label: 'x' }, { to: '', label: 'x' }, R('/i/a')]), [R('/i/a')])
})
