// 자가검사: npm test --prefix app — 사용 기록(이 기기 · 횟수만)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { SCREENS, USAGE_KEY, clearUsage, countFold, countUse, localDay, readUsage, screenKey, topCounts } from './usage.ts'

// node 엔 localStorage 가 없다 — 판정에 필요한 만큼만 흉내 낸다
const store = new Map<string, string>()
Object.assign(globalThis, { localStorage: {
  getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v) }, removeItem: (k: string) => { store.delete(k) },
} })

test('screenKey: 시장은 자산군까지, 지표 상세는 id 를 뗀다, 모르는 경로는 「그 밖」', () => {
  assert.equal(screenKey('/', ''), '/')
  assert.equal(screenKey('/market', ''), '/market?a=kr')
  assert.equal(screenKey('/market', '?a=macro&v=price&m=us'), '/market?a=macro')
  assert.equal(screenKey('/i/us10y', '?bell=1'), '/i')
  assert.equal(screenKey('/i/005930', ''), '/i')
  assert.equal(screenKey('/market', '?a=nope'), '그 밖')
  assert.equal(screenKey('/아무거나', ''), '그 밖')
})

test('countUse · countFold: 횟수만 쌓고 시작일을 한 번 적는다', () => {
  store.clear()
  countUse('screens', '/')
  countUse('screens', '/')
  countUse('views', '국내 목차 · 상승')
  countUse('more', 'i/us10y:관련')
  countFold('market:상승', false)
  countFold('market:상승', true)
  countFold('i/005930:흐름', false)
  const u = readUsage()
  assert.equal(u.since, localDay())
  assert.deepEqual(u.screens, { '/': 2 })
  assert.deepEqual(u.views, { '국내 목차 · 상승': 1 })
  assert.deepEqual(u.more, { 'i:관련': 1 })
  assert.deepEqual(u.folds, { 'market:상승': { open: 1, close: 1 }, 'i:흐름': { open: 0, close: 1 } })
  assert.ok(!/005930|us10y/.test(store.get(USAGE_KEY)!), '지표 · 종목 id 가 기록에 남음')
})

test('readUsage: 깨진 기록은 빈 기록, 지우면 시작일도 새로', () => {
  for (const raw of ['{', '[]', 'null', '"x"', '{"screens":[1]}']) {
    store.set(USAGE_KEY, raw)
    const u = readUsage()
    assert.equal(u.since, '')
    assert.deepEqual(u.screens, {})
  }
  store.set(USAGE_KEY, '{"since":"2026-10-01","screens":{"/":"x"}}')
  countUse('screens', '/')
  assert.deepEqual(readUsage(), { since: '2026-10-01', screens: { '/': 1 }, views: {}, folds: {}, more: {} })
  clearUsage()
  assert.equal(store.has(USAGE_KEY), false)
})

test('저장소가 막혀도 던지지 않는다', () => {
  const ls = globalThis.localStorage
  Object.assign(globalThis, { localStorage: { getItem: () => { throw new Error('막힘') }, setItem: () => { throw new Error('막힘') }, removeItem: () => { throw new Error('막힘') } } })
  try {
    countUse('views', 'x')
    countFold('x', true)
    clearUsage()
    assert.equal(readUsage().since, '')
  } finally { Object.assign(globalThis, { localStorage: ls }) }
})

test('topCounts: 많은 순, 같으면 이름 순, 0 은 뺀다', () => {
  assert.deepEqual(topCounts({ b: 2, a: 2, c: 5, d: 0 }, 2), [['c', 5], ['a', 2]])
})

test('SCREENS 의 시장 자산군 이름 = screens/Market.tsx ASSETS', () => {
  const src = readFileSync(new URL('../screens/Market.tsx', import.meta.url), 'utf8')
  const assets = [...src.matchAll(/\{ key: '(\w+)', label: '([^']+)', bundle:/g)].map(m => [`/market?a=${m[1]}`, `시장 · ${m[2]}`])
  assert.equal(assets.length, 7)
  assert.deepEqual(SCREENS.filter(s => s[0].startsWith('/market')), assets)
})
