// 자가검사: npm test --prefix app — 패널 접기 기억 · 「더 보기」 행 수
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { FOLD_KEY, foldId, hiddenRows, isFolded, setFolded } from './fold.ts'

// node 엔 localStorage 가 없다 — 판정에 필요한 만큼만 흉내 낸다
const store = new Map<string, string>()
Object.assign(globalThis, { localStorage: { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v) } } })

test('foldId: 화면 + 제목, 범위 · 개수 꼬리는 뗀다', () => {
  assert.equal(foldId('/', '뉴스'), 'home:뉴스')
  assert.equal(foldId('/market', '상승 · 코스피'), 'market:상승')
  assert.equal(foldId('/market', '업종 31'), 'market:업종')
  assert.equal(foldId('/market', '거래대금 상위 · 전체'), foldId('/market', '거래대금 상위 · 코스닥'))
})

test('setFolded · isFolded: 접으면 기억, 펼치면 지운다', () => {
  assert.equal(isFolded('home:뉴스'), false)
  setFolded('home:뉴스', true)
  setFolded('market:상승', true)
  assert.equal(isFolded('home:뉴스'), true)
  setFolded('home:뉴스', false)
  assert.equal(isFolded('home:뉴스'), false)
  assert.deepEqual(JSON.parse(store.get(FOLD_KEY)!), { 'market:상승': true })
})

test('isFolded: 깨진 기억은 늘 펼침', () => {
  for (const raw of ['{', '[]', 'null', '"x"']) { store.set(FOLD_KEY, raw); assert.equal(isFolded('market:상승'), false) }
})

test('hiddenRows: 모바일 5행 · PC 10행 넘는 만큼', () => {
  assert.equal(hiddenRows(5, false), 0)
  assert.equal(hiddenRows(12, false), 7)
  assert.equal(hiddenRows(10, true), 0)
  assert.equal(hiddenRows(20, true), 10)
  assert.equal(hiddenRows(0, true), 0)
})
