// 자가검사: npm test --prefix app — 지도 요소 변환(방향 → 색 클래스, 세기 → 굵기, 퍼지지 않은 것 회색).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { links, propagate, type LensEdge, type LensNode } from './model.ts'
import { mapElements, mapStyle, nodeName } from './map.ts'

const N = (id: string, short?: string): LensNode => ({ id, label: `${id} 전체 이름`, layer: 'market', short })
const E = (from: string, to: string, dir: string, n: number): LensEdge => ({ from, to, dir, n, logNos: [`${from}${to}`] })
const cls = (els: ReturnType<typeof mapElements>) => new Map(els.map(e => [String(e.data.id), String(e.classes)]))

const nodes = ['a', 'b', 'c', 'x', 'q'].map(id => N(id))
const edges = [E('a', 'b', '+', 6), E('b', 'c', '-', 9), E('a', 'x', '-', 2), E('q', 'c', '±', 1)]
const ls = links(edges)

test('mapElements: 전파 방향 → up/down, 세기 → w1~3, 2단계 → guess, 나머지 회색', () => {
  const c = cls(mapElements(nodes, ls, propagate(edges, 'a', 1, 2), 'a'))
  assert.equal(c.get('a>b'), 'up w3')            // 1단계 ▲, 언급 6 → 세기 3
  assert.equal(c.get('a>x'), 'down w2')          // 1단계 ▼, 언급 2 → 세기 2
  assert.equal(c.get('b>c'), 'down w2 guess')    // 2단계: min(3,3)−1 = 2, 부호 뒤집힘, 추정
  assert.equal(c.get('q>c'), 'mute w1')          // 방향 미정(±) 선은 회색, 굵기는 언급 수
  assert.deepEqual(['b', 'x', 'c', 'q'].map(id => c.get(id)), ['up', 'down', 'down', 'mute'])
  assert.equal(c.get('a'), 'mute start')         // 출발점은 검정 테두리 표식
  // ▼ 로 밀면 색만 뒤집힌다
  assert.equal(cls(mapElements(nodes, ls, propagate(edges, 'a', -1, 2), 'a')).get('a>b'), 'down w3')
})

test('mapElements: 고르기 전은 전부 idle, 출발점만 고르면 닿은 선·이웃만 ink', () => {
  const idle = cls(mapElements(nodes, ls, [], null))
  assert.ok([...idle.values()].every(v => /^idle( w\d)?$/.test(v)))
  const pre = cls(mapElements(nodes, ls, [], 'b'))
  assert.deepEqual(['a>b', 'b>c', 'a>x'].map(id => pre.get(id)), ['ink w3', 'ink w3', 'mute w2'])
  assert.deepEqual(['a', 'c', 'x', 'b'].map(id => pre.get(id)), ['ink', 'ink', 'mute', 'mute start'])
})

test('mapStyle · nodeName: 굵기 1.5·2.5·4px(맞춤 보정 k 곱), 긴 이름 자르기', () => {
  const st = mapStyle({ ink1: '#1', ink2: '#2', ink3: '#3', line: '#4', card: '#5', up: '#u', down: '#d', font: 'f' }, 2)
  const w = (s: number) => (st.find(b => 'selector' in b && b.selector === `edge.w${s}`) as { style: { width: number } }).style.width
  assert.deepEqual([1, 2, 3].map(w), [3, 5, 8])
  assert.equal(nodeName(N('p', '미 GDP 성장률')), '미 GDP 성…')
  assert.equal(nodeName(N('p', '금')), '금')
  assert.equal(nodeName({ id: 'r', label: '부동산(전국 주택가격지수)', layer: 'asset' }), '부동산')
})
