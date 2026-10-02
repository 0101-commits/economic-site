// 묶음 로더 — 화면은 묶음(bundles/<이름>.json)만 읽는다. 데이터 층은 손대지 않는다.
// 주소 기준: 이 앱은 사이트의 next/ 아래에 있으므로 자료는 한 단계 위에 있다.
//   배포  /economic-site/next/ → /economic-site/data.json · /economic-site/bundles/
//   개발  /next/              → /data.json · /bundles/   (vite.config 의 개발 서버가 저장소 루트에서 내준다)
import { changeFromPct, type PeriodKey, type Pt } from './format'

const ROOT = new URL('../', document.baseURI)

async function fetchJson<T>(rel: string): Promise<T> {
  const r = await fetch(new URL(rel, ROOT), { cache: 'no-cache' })
  if (!r.ok) throw new Error(`${rel}: HTTP ${r.status}`)
  return r.json() as Promise<T>
}

// 한 화면 안에서 같은 묶음을 두 번 받지 않는다(홈 띠 보기 · 큰 차트 · 상세가 같은 묶음을 나눠 쓴다). 실패는 기억하지 않는다.
const bundles = new Map<string, Promise<unknown>>()
export function loadBundle<T = unknown>(name: string): Promise<T> {
  if (!/^[\w-]+$/.test(name)) return Promise.reject(new Error(`묶음 이름이 올바르지 않음: ${name}`))
  let p = bundles.get(name)
  if (!p) {
    p = fetchJson<T>(`bundles/${name}.json`)
    p.catch(() => bundles.delete(name))
    bundles.set(name, p)
  }
  return p as Promise<T>
}

/**
 * 지표 한 칸 — 묶음(scripts/build_bundles.py)의 칸 모양. 홈 strip[] 과 시장 묶음이 같은 모양을 쓴다.
 * - value·change 는 원본 단위 그대로. scale 이 있으면 화면 값 = 원본 ÷ scale, 그 단위가 unit(format.ts scaled).
 * - changePct 는 %. 금리·성장률 같은 % 지표는 changePct 가 null 이고 change(%p)만 있다.
 * - state 는 묶음을 만든 순간의 신선도(live·prev·stale·kept·missing). live 는 liveUntil 을 지나면 prev 로 본다.
 * - asOf 는 kept·missing 이면 null 일 수 있다. kept 는 keptSince(처음 못 받은 시각)를 단다.
 * - short = PC 이름, shortM = 모바일 8칸 이름, reason/reasonShort = 이유 한 줄(PC/모바일).
 * - 파생 칸(시장 띠): breadth_kospi 는 value = 상승 종목 수이고 up·down·flat 이 따로 온다 → 「352/513」(up/down)으로 적는다.
 *   foreign_hold_ratio 는 늘 value null · state missing 이다.
 * - 띠 순서의 단일 원천은 scripts/build_bundles.py 의 STRIPS 표다. 화면에서 순서를 다시 정하지 말 것.
 * data.json 폴백에는 state 이하가 없다.
 */
export type StripItem = {
  id: string
  label: string
  short?: string
  shortM?: string
  decimals: number
  value: number | null
  change: number | null
  changePct: number | null
  scale?: number | null
  unit?: string
  asOf: string | null
  state?: string
  liveUntil?: string | null
  keptSince?: string | null
  reason?: string
  reasonShort?: string
  up?: number
  down?: number
  flat?: number
  /** 띠 카드 작은 차트: 최근 7거래일 값(날짜 없음) */
  spark?: number[] | null
  /** 시장 묶음 views 칸에만: [날짜, 값] 일별(월별) 시계열 */
  series?: Pt[] | null
}

/**
 * 값 옆에 단위를 붙일지. scale 로 바꾼 값(26.8조원 · 100엔당 원)과 % 지표(금 프리미엄 · 전년비 · 금리)는 단위 없이는
 * 못 읽으므로 붙이고, $·원 같은 통화 기호는 이름이 이미 말하므로 뺀다.
 */
export function shownUnit(it: Pick<StripItem, 'scale' | 'unit'>): string | undefined {
  return it.scale || it.unit === '%' ? it.unit : undefined
}
/** 장 상태(묶음 market): state = open·closed·holiday 등, label = 「정규장」「장마감」「휴장」. */
export type MarketState = { state: string; label: string; today?: string; session?: string; nextOpen?: string | null; calendarKnown?: boolean }
export type Stock = { name: string; short?: string; shortM?: string; code: string; market?: string; price: number | null; chgPct: number | null; amount?: number | null }
/** 투자자 매매: rows 는 columns 순서의 배열(날짜, 외국인, 기관, 개인). 단위 unit(억원). */
export type Flows = {
  market?: string; unit?: string; source?: string; asOf?: string; state?: string
  today?: { date: string; foreign: number | null; inst: number | null; retail: number | null }
  rows?: (string | number | null)[][]; columns?: string[]
}
/** 경제 일정 한 줄. 이전·예측·실제는 단위가 붙은 글자다(「+0.4%」 · 「1275.0」 — 거시 달력), 없으면 null. beat = 실제가 예측보다 좋음 1 · 나쁨 -1. */
export type Sched = { date: string; time?: string | null; cc?: string; name: string; stars?: number; prev?: string | null; fore?: string | null; act?: string | null; beat?: number | null; approx?: boolean }
export type News = { title: string; url: string; date?: string; topic?: string }
/** 렌즈 트리거 한 줄: state crossed(돌파)·near(주시), level = 가장 가까운 임계값, distancePct = 임계까지 거리(%). unit 은 없으면 null 로 온다. */
export type Trigger = { id: string; label: string; layer?: string; unit?: string | null; state: string; stateLabel?: string; value: number | null; asOf?: string | null; level: number | null; distancePct?: number | null }
/** 렌즈 사슬: n = 이 사슬을 짚은 글 수, hotStep = 지금 발동한 고리 id(발동한 고리가 없으면 null — 렌즈 묶음 chains 에 실제로 온다). */
export type Chain = { id: string; label: string; note?: string; n?: number; lastDate?: string; hotStep?: string | null; steps: { id: string; label: string }[] }
export type HomeLens = { score: number | null; delta30d?: number | null; asOf?: string; breach: Trigger[]; watch: Trigger[]; chain: Chain | null; hotChains?: number }

export type HomeBundle = {
  asOf: string
  market?: MarketState
  todayLine: { pc: string; mobile: string; source?: unknown } | null
  strip: StripItem[]
  /** 코스피 큰 차트: 기간별 [날짜, 값]. 없는 기간은 null 이고 missing 에 이유가 있다. */
  kospiChart?: Partial<Record<PeriodKey, Pt[] | null>> & { missing?: Record<string, string> }
  sectors?: { asOf?: string; state?: string; items: { name: string; close?: number | null; chgPct: number | null }[] }
  topAmount?: { asOf?: string; state?: string; items: Stock[] }
  investors?: Flows
  schedule?: Sched[]
  news?: News[]
  lens?: HomeLens
}

/** 지표 사전 한 줄(bundles/registry.json). asset = index·fx·rate·commodity·macro·realestate·sentiment. */
export type RegRow = { id: string; label: string; short?: string; shortM?: string; decimals: number; unit?: string; scale?: number; asset: string; tier?: number; country?: string; canonical?: string }
export const loadRegistry = () => loadBundle<{ count: number; rows: RegRow[] }>('registry').then(r => r.rows)

/** 자산군 → 시계열이 든 시장 묶음(앞에서부터 찾는다). */
const ASSET_BUNDLES: Record<string, string[]> = {
  index: ['market-global'], sentiment: ['market-global'], fx: ['market-fxrates'], rate: ['market-fxrates'],
  commodity: ['market-commodities'], macro: ['market-macro', 'market-global'], realestate: ['market-realestate'],
}

/** 묶음 아무 깊이에서 id 가 같은 값 칸을 찾는다. 시계열이 있는 칸을 먼저 고른다. */
export function findItem(root: unknown, id: string): StripItem | undefined {
  let best: StripItem | undefined
  const walk = (o: unknown): void => {
    if (!o || typeof o !== 'object') return
    if (Array.isArray(o)) { o.forEach(walk); return }
    const r = o as Record<string, unknown>
    if (r.id === id && 'value' in r && (!best || (!best.series?.length && Array.isArray(r.series) && r.series.length))) best = r as StripItem
    Object.values(r).forEach(walk)
  }
  walk(root)
  return best
}

/** 지표 하나: 사전 줄 + 값 칸(시장 묶음 우선, 없으면 홈) + 시계열. 어디에도 없으면 빈 칸들. */
export async function loadIndicator(id: string): Promise<{ reg?: RegRow; item?: StripItem; series?: Pt[] }> {
  const [rows, home] = await Promise.all([loadRegistry().catch(() => [] as RegRow[]), loadHome().catch(() => null)])
  const reg = rows.find(r => r.id === id)
  let item = home ? findItem(home, id) : undefined
  for (const name of (reg && ASSET_BUNDLES[reg.asset]) || []) {
    const m = findItem(await loadBundle(name).catch(() => null), id)
    if (m) { item = m; if (m.series?.length) break }
  }
  return { reg, item, series: item?.series?.length ? item.series : undefined }
}

/** 홈 묶음. 아직 묶음이 없거나 모양이 다르면 data.json 에서 띠 8장을 직접 만든다. */
export async function loadHome(): Promise<HomeBundle> {
  try {
    const b = await loadBundle<HomeBundle>('home')
    if (b && Array.isArray(b.strip) && b.strip.length) return b
  } catch { /* 묶음 없음 → 아래 폴백 */ }
  return homeFromData(await fetchJson<DataJson>('data.json'))
}

type Quote = { price?: number; rate?: number; change?: number }
type DataJson = {
  lastUpdated?: string
  indices?: Record<string, Quote>
  fx?: Record<string, Quote>
  commodities?: Record<string, Quote>
  yieldCurve?: { us?: { series?: { tenor: string; data: { date: string; value: number }[] }[] } }
  aiBriefing?: { lines?: string[] }
}

export function homeFromData(d: DataJson): HomeBundle {
  const at = d.lastUpdated || ''
  // data.json 의 change 는 등락률(%)이다 → 변화량은 거꾸로 구한다
  const q = (id: string, label: string, o: Quote | undefined, decimals: number): StripItem => {
    const value = o?.price ?? o?.rate ?? null
    const changePct = o?.change ?? null
    return { id, label, value, decimals, changePct, change: value != null && changePct != null ? changeFromPct(value, changePct) : null, asOf: at }
  }
  const s10 = d.yieldCurve?.us?.series?.find(s => s.tenor === '10Y')?.data || []
  const last = s10[s10.length - 1], prev = s10[s10.length - 2]
  const us10: StripItem = {
    id: 'us10y', label: '미 10년', decimals: 2, asOf: last?.date || at,
    value: last?.value ?? null,
    change: last && prev ? last.value - prev.value : null,
    changePct: null,   // 금리는 등락률을 쓰지 않는다(묶음과 같다)
  }
  const line = d.aiBriefing?.lines?.[0] || ''
  return {
    asOf: at,
    todayLine: line ? { pc: line, mobile: line } : null,
    strip: [
      q('kospi', '코스피', d.indices?.KOSPI, 2),
      q('kosdaq', '코스닥', d.indices?.KOSDAQ, 2),
      q('sp500', 'S&P 500', d.indices?.SP500, 2),
      q('nasdaq', '나스닥', d.indices?.NASDAQ, 2),
      q('usdkrw', '달러원', d.fx?.USDKRW, 1),
      us10,
      q('wti', 'WTI', d.commodities?.WTI, 2),
      q('gold', '금', d.commodities?.Gold, 1),
    ],
  }
}
