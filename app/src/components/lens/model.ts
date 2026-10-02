// 렌즈 계산 — 화면 없이 도는 순수 함수(node --test 로 바로 검사한다). 타입 표기 외의 TypeScript 전용 문법은 쓰지 않는다.
// 운영 규칙(렌즈 화면 전체):
//   상태어는 돌파·주시·정상(지표) / 도달·추정·미도달(사슬 단계) 만 쓴다.
//   실측은 실선, 추정은 점선. 글은 제목·날짜·링크만(본문 전재 없음). 금액은 계산하지 않는다 — 방향(▲▼)과 세기(1~3)만.
import type { Chain, HomeLens, Trigger } from '../../lib/bundle'

export type Layer = 'cause' | 'market' | 'channel' | 'asset'
export const LAYERS: readonly { key: Layer; label: string }[] = [
  { key: 'cause', label: '원인' }, { key: 'market', label: '시장' }, { key: 'channel', label: '경로' }, { key: 'asset', label: '자산' },
]

export type LensNode = { id: string; label: string; layer: Layer; state?: string; view?: number | null; /** 지도 라벨용 짧은 이름(묶음에 있으면) */ short?: string }
/** 글에서 「from 이 to 를 움직인다」고 쓴 관계. dir + 같은 방향 · - 반대 방향 · ± 방향 미정. n = 언급 수. */
export type LensEdge = {
  from: string; to: string; dir: string; n: number; horizon?: string; logNos?: string[]
  /** 인용(80자 이하) — 묶음에 아직 없다(원천 mer_signals.json impacts[].quotes 와 같은 모양). 있으면 패널에 한 줄. */
  quotes?: { logNo: string; date?: string; q: string }[]
}
/** 사슬 — logNos 는 묶음에 아직 없다(있으면 원문 목록을 보인다). */
export type LensChain = Chain & { logNos?: string[] }
export type Regime = { months: string[]; factors: string[]; counts: number[][]; dominant: string[] }
export type Post = { logNo: string; date: string; title?: string }
export type LensBundle = {
  asOf: string
  window?: { from: string; to: string }
  /** 묶음에 아직 없다(원천 mer_signals.json 에는 coverage.posts 가 있다). */
  coverage?: { posts?: number }
  nodes: LensNode[]
  edges: LensEdge[]
  chains: LensChain[]
  regime?: Regime
  lens?: { score: number | null; asOf?: string; history30d?: { date: string; score: number }[] }
  triggers: Trigger[]
  today?: HomeLens
  posts: Post[]
}

/** 이름 줄이기: 괄호 풀이와 「·」 뒤를 뗀다(「부동산(전국 주택가격지수)」 → 「부동산」). 묶음 nodes 에 short 가 없어서다. */
export const shortLabel = (label: string) => label.replace(/\(.*?\)/g, '').split('·')[0].trim() || label

/** 선 세기: 언급 5회 이상 3 · 2~4회 2 · 그 밖 1. 지도 선 굵기와 전파 세기가 같은 규칙을 쓴다. */
export const edgeStrength = (n: number): 1 | 2 | 3 => (n >= 5 ? 3 : n >= 2 ? 2 : 1)

/**
 * 같은 두 점 사이의 관계를 선 하나로 합친다.
 * net = 부호 있는 언급 수의 합(+ 는 더하고 - 는 뺀다, ± 는 방향이 없어 0). total = 모든 언급 수(지도 선 굵기).
 * 예: 지정학 → 원유가 「+8」「-3」 이면 net +5 — 반대 방향 글이 섞이면 많이 쓴 쪽으로 기운다.
 */
export type Link = { from: string; to: string; net: number; total: number; horizon: string; logNos: string[] }
export function links(edges: LensEdge[]): Link[] {
  const m = new Map<string, Link>()
  for (const e of edges) {
    const k = `${e.from}>${e.to}`
    let l = m.get(k)
    if (!l) m.set(k, (l = { from: e.from, to: e.to, net: 0, total: 0, horizon: '', logNos: [] }))
    l.net += e.dir === '+' ? e.n : e.dir === '-' ? -e.n : 0
    l.total += e.n
    if (e.horizon && !l.horizon.split('·').includes(e.horizon)) l.horizon = l.horizon ? `${l.horizon}·${e.horizon}` : e.horizon
    for (const x of e.logNos || []) if (!l.logNos.includes(x)) l.logNos.push(x)
  }
  return [...m.values()]
}

export type Sign = 1 | -1
/** 전파 결과 한 점: from 에서 link 를 타고 step 단계에 닿았다. sign = 그 점이 움직이는 방향. */
export type Hit = { id: string; from: string; sign: Sign; strength: 1 | 2 | 3; step: number; link: Link }

/**
 * 「만약에」 전파. startId 를 dir(▲ 1 · ▼ -1)로 밀었을 때 선을 따라 depth 단계까지 방향을 퍼뜨린다.
 * - 1단계: 선 부호대로 방향을 정하고 세기 = edgeStrength(|net|).
 * - 2단계부터: 세기 = (앞 점 세기와 그 선 세기 중 작은 쪽) − 1, 최소 1. 화면은 점선(추정)으로 그린다.
 * - 한 점은 처음 닿은 단계에서만 정한다(출발점으로 되돌아오지 않는다).
 *   같은 단계에 여러 선이 닿으면 세기가 큰 쪽, 같은 세기로 방향이 엇갈리면 방향을 정하지 않고 거기서 멈춘다.
 * - net 이 0 인 선(± 만 있거나 반대 글이 같은 수)은 방향이 없어 타지 않는다.
 */
export function propagate(edges: LensEdge[], startId: string, dir: Sign, depth = 3): Hit[] {
  const ls = links(edges).filter(l => l.net !== 0)
  const seen = new Set([startId])
  const out: Hit[] = []
  let front: { id: string; sign: Sign; strength: number }[] = [{ id: startId, sign: dir, strength: 3 }]
  for (let step = 1; step <= depth && front.length; step++) {
    const cand = new Map<string, Hit[]>()
    for (const f of front) {
      for (const l of ls) {
        if (l.from !== f.id || seen.has(l.to)) continue
        const s = edgeStrength(Math.abs(l.net))
        const strength = (step === 1 ? s : Math.max(1, Math.min(f.strength, s) - 1)) as 1 | 2 | 3
        const h: Hit = { id: l.to, from: f.id, sign: (f.sign * Math.sign(l.net)) as Sign, strength, step, link: l }
        cand.set(l.to, [...(cand.get(l.to) || []), h])
      }
    }
    front = []
    for (const [id, hs] of cand) {
      seen.add(id)
      const top = Math.max(...hs.map(h => h.strength))
      const best = hs.filter(h => h.strength === top)
      if (best.some(h => h.sign !== best[0].sign)) continue
      out.push(best[0])
      front.push(best[0])
    }
  }
  return out
}

export type StepState = 'reached' | 'guess' | 'not'
export const STEP_WORD: Record<StepState, string> = { reached: '도달', guess: '추정', not: '미도달' }
export type ChainStep = { id: string; label: string; state: StepState; repeat: boolean; t?: Trigger }

// 임계값과 현재값이 둘 다 있어야 「실측」이다(자료 없음 상태는 잴 수 없다)
const measured = (t?: Trigger) => !!t && t.state !== 'unknown' && t.level != null && t.value != null

/**
 * 사슬 단계 판정(앞에서부터).
 * - 도달: 그 지표가 돌파. 잴 지표가 없으면 사슬의 발동 칸(hotStep)일 때.
 * - 추정: 잴 수 없는 단계인데 앞 단계가 이미 도달.
 * - 미도달: 그 밖(재 봤는데 돌파 아님, 또는 앞에 도달이 없음).
 * 사슬이 처음 칸으로 되돌아오면(C1·C2) 그 칸은 repeat 로 표시하고 처음 판정을 따른다.
 */
export function chainSteps(c: Chain, trig: Map<string, Trigger>): ChainStep[] {
  const first = new Map<string, StepState>()
  let hit = false
  return c.steps.map(s => {
    const t = trig.get(s.id)
    const prev = first.get(s.id)
    if (prev) return { id: s.id, label: s.label, state: prev, repeat: true, t }
    // 돌파도 잰 것만 믿는다 — 값·임계 없는 crossed(옛 묶음·원천 오기)는 「잴 수 없음」으로 본다
    const state: StepState = (measured(t) && t!.state === 'crossed') || (!measured(t) && s.id === c.hotStep) ? 'reached' : !measured(t) && hit ? 'guess' : 'not'
    if (state === 'reached') hit = true
    first.set(s.id, state)
    return { id: s.id, label: s.label, state, repeat: false, t }
  })
}

/** 사슬 진행 n/N(도달 단계 수 / 서로 다른 단계 수) 순서 — 비율 → 도달 수 → 글 수. */
export function rankChains<C extends Chain>(chains: C[], trig: Map<string, Trigger>): { c: C; done: number; total: number }[] {
  return chains
    .map(c => {
      const st = chainSteps(c, trig).filter(s => !s.repeat)
      return { c, done: st.filter(s => s.state === 'reached').length, total: st.length }
    })
    .sort((a, b) => b.done / (b.total || 1) - a.done / (a.total || 1) || b.done - a.done || (b.c.n ?? 0) - (a.c.n ?? 0))
}

/** 받침에 따라 「으로/로」. 받침 없음이나 ㄹ 받침이면 「로」. */
export function josaRo(w: string): string {
  const c = w.charCodeAt(w.length - 1) - 0xac00
  return c >= 0 && c <= 11171 && c % 28 && c % 28 !== 8 ? '으로' : '로'
}
