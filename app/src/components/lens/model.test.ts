// 자가검사: npm test --prefix app — 렌즈 전파·사슬 판정 순수 함수.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import type { Trigger } from '../../lib/bundle'
import { chainSteps, edgeStrength, josaRo, links, propagate, rankChains, shortLabel, type LensEdge } from './model.ts'

const E = (from: string, to: string, dir: string, n: number): LensEdge => ({ from, to, dir, n, logNos: [`${from}${to}${n}`] })

test('edgeStrength: 5회 이상 3 · 2~4회 2 · 그 밖 1', () => {
  assert.deepEqual([1, 2, 4, 5, 9].map(edgeStrength), [1, 2, 2, 3, 3])
})

test('links: 같은 두 점은 하나로, 부호 있는 언급 수를 더한다', () => {
  const ls = links([E('a', 'b', '+', 8), E('a', 'b', '-', 3), E('a', 'b', '±', 2), E('b', 'c', '+', 2)])
  assert.equal(ls.length, 2)
  assert.deepEqual({ net: ls[0].net, total: ls[0].total, posts: ls[0].logNos.length }, { net: 5, total: 13, posts: 3 })
})

test('propagate: 1단계 부호·세기, 2단계부터 한 단 낮춤, 깊이 제한', () => {
  const edges = [E('a', 'b', '+', 6), E('b', 'c', '-', 9), E('c', 'd', '+', 2), E('a', 'x', '-', 2)]
  const up = propagate(edges, 'a', 1, 3)
  const by = new Map(up.map(h => [h.id, h]))
  assert.deepEqual([...by.keys()].sort(), ['b', 'c', 'd', 'x'])
  assert.deepEqual({ sign: by.get('b')!.sign, strength: by.get('b')!.strength, step: by.get('b')!.step }, { sign: 1, strength: 3, step: 1 })
  assert.deepEqual({ sign: by.get('x')!.sign, strength: by.get('x')!.strength }, { sign: -1, strength: 2 })
  // b(3) → c: min(3, 3) − 1 = 2, 부호 뒤집힘
  assert.deepEqual({ sign: by.get('c')!.sign, strength: by.get('c')!.strength, step: by.get('c')!.step }, { sign: -1, strength: 2, step: 2 })
  // c(2) → d: min(2, 2) − 1 = 1 (최소 1)
  assert.deepEqual({ sign: by.get('d')!.sign, strength: by.get('d')!.strength, step: by.get('d')!.step }, { sign: -1, strength: 1, step: 3 })
  // ▼ 로 밀면 방향만 모두 뒤집힌다
  assert.deepEqual(propagate(edges, 'a', -1, 3).map(h => h.sign), up.map(h => -h.sign))
  // 깊이 1 이면 이웃만
  assert.deepEqual(propagate(edges, 'a', 1, 1).map(h => h.id).sort(), ['b', 'x'])
})

test('propagate: 되돌아오지 않고, 방향 없는 선은 타지 않고, 엇갈리면 멈춘다', () => {
  // 고리 a → b → a 는 출발점으로 돌아오지 않는다
  assert.deepEqual(propagate([E('a', 'b', '+', 2), E('b', 'a', '+', 2)], 'a', 1).map(h => h.id), ['b'])
  // ± 만 있거나 반대 글이 같은 수면 net 0 → 타지 않는다
  assert.deepEqual(propagate([E('a', 'b', '±', 5), E('a', 'c', '+', 3), E('a', 'c', '-', 3)], 'a', 1), [])
  // 같은 단계에서 세기가 큰 쪽이 이긴다: b(3) 는 d 를 ▲, c(2) 는 d 를 ▼ → ▲
  const strong = propagate([E('a', 'b', '+', 5), E('a', 'c', '+', 2), E('b', 'd', '+', 9), E('c', 'd', '-', 9)], 'a', 1)
  assert.equal(strong.find(h => h.id === 'd')!.sign, 1)
  // 같은 세기로 엇갈리면 d 는 정하지 않고, d 너머(e)로도 퍼지지 않는다
  const tie = propagate([E('a', 'b', '+', 5), E('a', 'c', '+', 5), E('b', 'd', '+', 9), E('c', 'd', '-', 9), E('d', 'e', '+', 9)], 'a', 1)
  assert.deepEqual(tie.map(h => h.id).sort(), ['b', 'c'])
  // 나가는 선이 없으면 빈 결과
  assert.deepEqual(propagate([E('a', 'b', '+', 5)], 'b', 1), [])
})

test('propagate: 실제 묶음에서도 규칙을 지킨다', () => {
  const b = JSON.parse(readFileSync(new URL('../../../../bundles/lens.json', import.meta.url), 'utf8'))
  for (const n of b.nodes) {
    for (const depth of [1, 2, 3]) {
      const hs = propagate(b.edges, n.id, 1, depth)
      assert.equal(new Set(hs.map(h => h.id)).size, hs.length, `${n.id} 중복`)
      assert.ok(hs.every(h => h.id !== n.id && h.step >= 1 && h.step <= depth && h.strength >= 1 && h.strength <= 3), `${n.id} 깊이 ${depth}`)
    }
  }
})

test('chainSteps · rankChains: 도달·추정·미도달과 진행 순서', () => {
  const t = (id: string, state: string, level: number | null = 1): Trigger => ({ id, label: id, state, value: 1, level })
  const trig = new Map([t('x', 'crossed'), t('y', 'below'), t('z', 'near')].map(v => [v.id, v]))
  const c1 = { id: 'C1', label: '고리', steps: [{ id: 'x', label: 'X' }, { id: 'p', label: 'P' }, { id: 'y', label: 'Y' }, { id: 'x', label: 'X' }] }
  assert.deepEqual(chainSteps(c1, trig).map(s => [s.state, s.repeat]), [['reached', false], ['guess', false], ['not', false], ['reached', true]])
  // 앞에 도달이 없으면 잴 수 없는 단계는 미도달, 잴 지표가 없어도 발동 칸이면 도달
  const c2 = { id: 'C2', label: '둘', hotStep: 'q', steps: [{ id: 'p', label: 'P' }, { id: 'z', label: 'Z' }, { id: 'q', label: 'Q' }, { id: 'r', label: 'R' }] }
  assert.deepEqual(chainSteps(c2, trig).map(s => s.state), ['not', 'not', 'reached', 'guess'])
  const r = rankChains([c2, c1], trig)
  assert.deepEqual(r.map(x => [x.c.id, x.done, x.total]), [['C1', 1, 3], ['C2', 1, 4]])
})

test('shortLabel · josaRo', () => {
  assert.equal(shortLabel('부동산(전국 주택가격지수)'), '부동산')
  assert.equal(shortLabel('AI 캐펙스·데이터센터'), 'AI 캐펙스')
  assert.equal(shortLabel('금'), '금')
  assert.deepEqual(['유동성', '정책', '지정학', '관세', '금리발작', '엔캐리 청산', '물'].map(josaRo), ['으로', '으로', '으로', '로', '으로', '으로', '로'])
})
