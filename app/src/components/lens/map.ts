// 렌즈 「만약에」 지도 — 점·선·전파 결과를 Cytoscape 요소와 스타일로 바꾸는 순수 함수(node --test 로 검사한다).
// 색은 방향만 말한다: 상방 --c-up · 하방 --c-down · 퍼지지 않은 것 회색. 굵기는 세기 1~3(1.5·2.5·4px), 2단계부터 추정 = 점선.
// 이 파일은 cytoscape 를 불러오지 않는다(타입만) — 지도 조각(LensMap)만 cytoscape 를 싣는다.
import type cytoscape from 'cytoscape'
import { edgeStrength, shortLabel, type Hit, type LensNode, type Link } from './model.ts'

const NAME_MAX = 8
/** 지도 라벨: 묶음의 짧은 이름(없으면 괄호·「·」 뒤를 뗀 이름). 8자를 넘으면 7자 + 「…」, 전체 이름은 full(툴팁). */
export function nodeName(n: LensNode): string {
  const s = n.short || shortLabel(n.label)
  return s.length > NAME_MAX ? `${s.slice(0, NAME_MAX - 1)}…` : s
}

type Tone = 'idle' | 'ink' | 'mute' | 'up' | 'down'
const toneOf = (sign: number): Tone => (sign > 0 ? 'up' : 'down')

/**
 * 요소 변환. 상태 셋:
 * - 아무것도 안 고름: 전부 idle(회색).
 * - 출발점만 고름(방향 전): 출발점에 닿는 선과 이웃 점 = ink(검정), 나머지 mute.
 * - 퍼짐(vis 가 있음): 퍼진 점·선만 up/down, 나머지 mute. 퍼진 선 굵기 = 전파 세기, 그 밖 선 굵기 = 언급 수 세기.
 * 출발점에는 start 를 덧붙인다(검정 테두리 2px).
 */
export function mapElements(nodes: LensNode[], ls: Link[], vis: Hit[], sel: string | null): cytoscape.ElementDefinition[] {
  const ids = new Set(nodes.map(n => n.id))
  const hitOf = new Map(vis.map(h => [h.id, h]))
  const viaOf = new Map(vis.map(h => [`${h.link.from}>${h.link.to}`, h]))
  const pre = !!sel && !vis.length   // 출발점만 고른 상태
  const touches = (l: Link) => l.from === sel || l.to === sel
  const near = new Set(pre ? ls.filter(touches).map(l => (l.from === sel ? l.to : l.from)) : [])
  const rest: Tone = sel || vis.length ? 'mute' : 'idle'
  return [
    ...nodes.map(n => {
      const h = hitOf.get(n.id)
      const tone = h ? toneOf(h.sign) : near.has(n.id) ? 'ink' : rest
      return { data: { id: n.id, name: nodeName(n), full: n.label }, classes: n.id === sel ? `${tone} start` : tone }
    }),
    ...ls.filter(l => ids.has(l.from) && ids.has(l.to)).map(l => {
      const id = `${l.from}>${l.to}`, h = viaOf.get(id)
      const classes = h ? `${toneOf(h.sign)} w${h.strength}${h.step > 1 ? ' guess' : ''}`
        : `${pre && touches(l) ? 'ink' : rest} w${edgeStrength(l.total)}`
      return { data: { id, source: l.from, target: l.to }, classes }
    }),
  ]
}

/** 지도가 읽는 토큰(tokens.css). 캔버스는 var() 를 못 읽어 getComputedStyle 로 한 번 읽어 넘긴다. */
export const COLOR_VARS = {
  ink1: '--c-ink-1', ink2: '--c-ink-2', ink3: '--c-ink-3', line: '--c-line', card: '--c-card', up: '--c-up', down: '--c-down', font: '--font-body',
} as const
export type MapColors = Record<keyof typeof COLOR_VARS, string>

const WIDTH = [0, 1.5, 2.5, 4]   // 세기 1~3 → 선 굵기(px)

/**
 * 스타일. k = 1 / 처음 맞춤 확대율 — 어느 폭에서 열든 처음 보이는 점·선·글자 크기가 같다(손으로 확대하면 같이 커진다).
 * 회색 점 라벨은 모델 크기 12 에 「화면에서 8px 미만이면 숨김」 — 좁은 화면에선 처음에 숨고 두 손가락으로 키우면 나온다.
 * 퍼진 점·출발점·이웃 라벨은 늘 보인다.
 */
export function mapStyle(c: MapColors, k = 1): cytoscape.StylesheetJson {
  const px = (v: number) => v * k
  const shown = { color: c.ink1, 'font-size': px(12), 'min-zoomed-font-size': 0 }
  const lit = (col: string, z: number) => ({ 'line-color': col, 'target-arrow-color': col, opacity: 1, 'z-index': z })
  return [
    { selector: 'node', style: {
      width: px(10), height: px(10), 'background-color': c.ink3, 'border-width': 0,
      label: 'data(name)', color: c.ink2, 'font-family': c.font, 'font-size': 12, 'min-zoomed-font-size': 8,
      'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': px(3),
    } },
    { selector: 'node.mute', style: { 'background-color': c.line, color: c.ink3 } },
    { selector: 'node.ink', style: { ...shown, 'background-color': c.ink1, 'z-index': 2 } },
    { selector: 'node.up', style: { ...shown, 'background-color': c.up, 'z-index': 3 } },
    { selector: 'node.down', style: { ...shown, 'background-color': c.down, 'z-index': 3 } },
    { selector: 'node.start', style: { ...shown, width: px(14), height: px(14), 'background-color': c.card, 'border-width': px(2), 'border-color': c.ink1, 'font-weight': 'bold', 'z-index': 4 } },
    { selector: 'edge', style: {
      width: px(WIDTH[1]), 'curve-style': 'bezier', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.8,
      'line-color': c.ink3, 'target-arrow-color': c.ink3, opacity: 0.5, 'z-index': 1,
    } },
    ...[1, 2, 3].map(s => ({ selector: `edge.w${s}`, style: { width: px(WIDTH[s]) } })),
    { selector: 'edge.mute', style: lit(c.line, 1) },
    { selector: 'edge.ink', style: lit(c.ink1, 2) },
    { selector: 'edge.up', style: lit(c.up, 3) },
    { selector: 'edge.down', style: lit(c.down, 3) },
    { selector: 'edge.guess', style: { 'line-style': 'dashed', 'line-dash-pattern': [px(4), px(3)] } },
  ]
}
