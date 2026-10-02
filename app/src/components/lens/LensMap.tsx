// 렌즈 「만약에」 지도 그리는 층 — cytoscape 를 싣는 유일한 파일. WhatIf 가 lazy 로 불러 메인 번들과 따로 받는다.
// 배치: 층 4열(원인 → 시장 → 경로 → 자산) 자리에서 출발해 cose 로 다듬는다. 무작위가 없어 열 때마다 같은 지도다.
// 조작: 마우스 = 점 끌기 · 배경 끌기 · 휠 확대. 터치 = 한 손가락은 페이지 스크롤(지도가 가로채지 않는다), 두 손가락 = 확대·이동.
import { useEffect, useMemo, useRef } from 'react'
import cytoscape from 'cytoscape'
import { LAYERS, type Hit, type LensNode, type Link } from './model'
import { COLOR_VARS, mapElements, mapStyle, type MapColors } from './map'
import { MAP_BOX } from './parts'

const PAD = 12
const MIN_W = 640   // 배치 계산 폭 하한 — 좁은 화면은 이 폭으로 배치하고 줄여 맞춘다(점끼리 덜 겹친다)

function readColors(): MapColors {
  const cs = getComputedStyle(document.documentElement)
  return Object.fromEntries(Object.entries(COLOR_VARS).map(([k, v]) => [k, cs.getPropertyValue(v).trim()])) as MapColors
}

type Props = { nodes: LensNode[]; ls: Link[]; vis: Hit[]; sel: string | null; onPick: (id: string) => void }

export default function LensMap({ nodes, ls, vis, sel, onPick }: Props) {
  const gate = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)
  const pickRef = useRef(onPick)
  pickRef.current = onPick
  const els = useMemo(() => mapElements(nodes, ls, vis, sel), [nodes, ls, vis, sel])
  const elsRef = useRef(els)
  elsRef.current = els

  useEffect(() => {
    const g = gate.current!, el = box.current!
    const cw = el.clientWidth || MIN_W, ch = el.clientHeight || 320
    const W = Math.max(cw, MIN_W), H = (W * ch) / cw
    const seed = new Map<string, { x: number; y: number }>()
    LAYERS.forEach((L, ci) => {
      const col = nodes.filter(n => n.layer === L.key)
      col.forEach((n, ri) => seed.set(n.id, { x: ((ci + 0.5) * W) / LAYERS.length, y: ((ri + 0.5) * H) / col.length }))
    })
    let k = 1
    const cy = cytoscape({
      container: el,
      elements: elsRef.current.map(e => (seed.has(String(e.data.id)) ? { ...e, position: seed.get(String(e.data.id)) } : e)),
      style: mapStyle(readColors()),
      layout: { name: 'preset' },
      boxSelectionEnabled: false,
      autounselectify: true,
      minZoom: 0.2,
      maxZoom: 3,
    })
    cyRef.current = cy
    // 처음 맞춤 확대율로 크기 보정 — 어느 폭에서 열든 점·선·글자가 같은 크기로 보인다
    const fit = () => {
      cy.resize()
      cy.fit(undefined, PAD)
      k = 1 / (cy.zoom() || 1)
      cy.style(mapStyle(readColors(), k))
    }
    const layout = cy.layout({
      name: 'cose', randomize: false, animate: false, fit: false, boundingBox: { x1: 0, y1: 0, w: W, h: H },
      nodeDimensionsIncludeLabels: true, idealEdgeLength: () => 80, nodeRepulsion: () => 40000, gravity: 0.5, numIter: 2000, componentSpacing: 40, nodeOverlap: 20,
    })
    layout.one('layoutstop', fit)
    layout.run()

    cy.on('tap', 'node', e => pickRef.current(e.target.id()))
    // 캔버스 점에는 title 을 달 수 없어 지도 칸에 단다(전체 이름 툴팁)
    cy.on('mouseover', 'node', e => { el.title = e.target.data('full'); el.style.cursor = 'pointer' })
    cy.on('mouseout', 'node', () => { el.removeAttribute('title'); el.style.cursor = '' })

    // 터치: 손가락이 하나뿐인 동안은 cytoscape 에 넘기지 않는다 — 그래야 브라우저가 페이지를 스크롤한다.
    // cytoscape 는 점 위에서 시작한 한 손가락 이동과 배경 이동을 모두 preventDefault 로 막는다(이동 끄기로는 점 위 시작을 못 푼다).
    // 짧게 누른 탭은 브라우저가 마우스 이벤트로 바꿔 보내므로 점 고르기는 그대로 된다. 두 손가락이 닿은 순간부터 끝까지는 넘긴다.
    let multi = false
    const onTouch = (e: TouchEvent) => {
      if (e.type === 'touchstart' && e.touches.length > 1) multi = true
      if (!multi) e.stopPropagation()
      if ((e.type === 'touchend' || e.type === 'touchcancel') && e.touches.length === 0) multi = false
    }
    const TOUCH = ['touchstart', 'touchmove', 'touchend', 'touchcancel'] as const
    TOUCH.forEach(t => g.addEventListener(t, onTouch, { capture: true, passive: true }))

    const ro = new ResizeObserver(fit)
    ro.observe(el)
    // 테마: html[data-theme] 가 바뀌거나 기기 설정이 바뀌면 토큰을 다시 읽는다
    const restyle = () => cy.style(mapStyle(readColors(), k))
    const mo = new MutationObserver(restyle)
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const mq = matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', restyle)

    return () => {
      TOUCH.forEach(t => g.removeEventListener(t, onTouch, { capture: true }))
      ro.disconnect()
      mo.disconnect()
      mq.removeEventListener('change', restyle)
      cy.destroy()
      cyRef.current = null
    }
  }, [nodes, ls])

  // 고른 점·전파 단계가 바뀌면 클래스만 갈아 끼운다(배치는 그대로)
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.batch(() => { for (const e of els) cy.getElementById(String(e.data.id)).classes(e.classes as string) })
  }, [els])

  return (
    <div ref={gate} className={`relative touch-pan-y ${MAP_BOX}`}>
      {/* cytoscape 가 컨테이너에 position:relative 를 인라인으로 박아 absolute+inset 은 높이가 0 이 된다(실측) — 높이는 h-full 로 */}
      <div ref={box} aria-hidden className="h-full w-full" />
    </div>
  )
}
