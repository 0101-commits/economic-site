// 숫자·등락·기준 시각 표기 — 모든 화면이 이 한 벌만 쓴다.
// 이 파일은 node --test 로 바로 돌릴 수 있게 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다.

const nfCache = new Map<number, Intl.NumberFormat>()

/** 천 단위 쉼표 + 고정 소수 자릿수. 값이 없거나 숫자가 아니면 '—'(현행 사이트 표 빈칸 규칙과 같다). */
export function fmtNumber(value: number | null | undefined, decimals = 0): string {
  if (value == null || !Number.isFinite(value)) return '—'
  let nf = nfCache.get(decimals)
  if (!nf) {
    nf = new Intl.NumberFormat('ko-KR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    nfCache.set(decimals, nf)
  }
  const s = nf.format(value)
  return s === '-0' || /^-0[.,]?0*$/.test(s) ? s.slice(1) : s   // -0.00 은 0.00 으로
}

export type Dir = 'up' | 'down' | 'flat'

/** 방향. decimals 를 주면 그 자릿수로 반올림한 값으로 판정한다(글자는 0.00 인데 빨강인 일을 막는다). */
export function changeDir(chg: number | null | undefined, decimals?: number): Dir {
  if (chg == null || !Number.isFinite(chg)) return 'flat'
  const v = decimals == null ? chg : Number(chg.toFixed(decimals))
  return v > 0 ? 'up' : v < 0 ? 'down' : 'flat'
}

/** 등락 한 벌: ▲ 44.6 (0.65%) / ▼ 44.6 (0.65%) / 0.0 (0.00%). 부호는 화살표로만 나타낸다. */
export function fmtChange(chg: number | null | undefined, pct: number | null | undefined, decimals = 2): string {
  if (chg == null || !Number.isFinite(chg)) return '—'
  // 표시 자릿수로 반올림해 0 이 되면 보합으로 본다(▲ 0.00 같은 표기를 막는다)
  const dir = changeDir(chg, decimals)
  const arrow = dir === 'up' ? '▲ ' : dir === 'down' ? '▼ ' : ''
  const p = pct == null || !Number.isFinite(pct) ? '' : ` (${fmtNumber(Math.abs(pct), 2)}%)`
  return `${arrow}${fmtNumber(Math.abs(chg), decimals)}${p}`
}

/** 묶음의 scale 적용: 화면 값 = 원본 ÷ scale (예: 수출 scale 1e8 → 억달러, 엔/원 scale 0.01 → 100엔당 원). change 도 같은 수로 나눈다. */
export function scaled(v: number | null | undefined, scale?: number | null): number | null {
  if (v == null || !Number.isFinite(v)) return null
  return scale ? v / scale : v
}

/** 시계열에 scale 적용(값만 ÷ scale). 차트도 카드와 같은 단위로 그린다. */
export function scaledPts<T extends [string, number]>(pts: T[], scale?: number | null): T[] {
  return scale ? pts.map(([d, v]) => [d, v / scale] as T) : pts
}

/** 등락률(%)과 현재값에서 전일 대비 변화량을 거꾸로 구한다. 자료에 등락률만 있을 때 쓴다. */
export function changeFromPct(value: number, pct: number): number {
  return (value * pct) / (100 + pct)
}

export type AsOfKind = 'live' | 'prev' | 'delayed' | 'filled'

const KST_DAY = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' })
const KST_HM = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false })
const KST_MD = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric' })

/** 'YYYY-MM-DD' 만 있으면 한국 시각 자정으로 읽는다. */
export function parseAsOf(asOf: string | number | Date): Date {
  if (asOf instanceof Date) return asOf
  if (typeof asOf === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(asOf)) return new Date(asOf + 'T00:00:00+09:00')
  return new Date(asOf)
}

/**
 * 기준 시각 판정.
 * - filled(보강): 원래 출처가 아닌 대체 자료로 채웠다고 자료가 밝힌 경우
 * - prev(전일): 한국 날짜로 오늘보다 앞선 값
 * - live: 오늘 값이고 liveMin 분(기본 15) 이내
 * - delayed(지연): 오늘 값이지만 liveMin 분보다 오래됨
 */
export function asOfKind(asOf: string | number | Date, now: Date = new Date(), opts: { filled?: boolean; liveMin?: number } = {}): AsOfKind {
  if (opts.filled) return 'filled'
  const t = parseAsOf(asOf)
  if (Number.isNaN(t.getTime())) return 'filled'
  if (KST_DAY.format(t) < KST_DAY.format(now)) return 'prev'
  // 15분 = 묶음 meta.json freshnessRules.liveMin 과 같은 값
  return now.getTime() - t.getTime() <= (opts.liveMin ?? 15) * 60_000 ? 'live' : 'delayed'
}

/**
 * 묶음(scripts/build_bundles.py)이 이미 판정한 상태 → 배지 갈래. 묶음에 state 가 있으면 그것이 단일 원천이고
 * asOfKind 는 data.json 폴백에서만 쓴다. missing(자료 없음)은 배지 대신 값 자리의 '—' 가 말한다.
 */
export type BundleState = 'live' | 'prev' | 'stale' | 'kept' | 'missing'
const STATE_KIND: Record<BundleState, AsOfKind | null> = { live: 'live', prev: 'prev', stale: 'delayed', kept: 'filled', missing: null }
/**
 * state 는 묶음을 만든 순간의 판정이다. live 칸에는 liveUntil 이 붙고, 지금이 그 시각을 지났으면
 * 실시간이 아니므로 prev(직전 종가)로 내린다 — 묶음이 늦게 갱신돼도 「실시간」이 남지 않게.
 */
export function kindFromState(state: string | undefined, liveUntil?: string | null, now: Date = new Date()): AsOfKind | null | undefined {
  if (!state || !(state in STATE_KIND)) return undefined
  if (state === 'live' && liveUntil) {
    const until = parseAsOf(liveUntil).getTime()
    if (!Number.isNaN(until) && now.getTime() > until) return 'prev'
  }
  return STATE_KIND[state as BundleState]
}

/** 배지 문구: LIVE 는 시각만 · 오늘 값은 「종가 15:30」(날짜만 있으면 「종가 10/1」) · 앞선 날은 「전일 9/30」 · 지연은 시각 · 보강은 낱말만. */
export function asOfLabel(kind: AsOfKind, asOf: string | number | Date, now: Date = new Date()): string {
  if (kind === 'filled') return '보강'
  // 월간(YYYY-MM)은 날짜가 아니라 그 달이다 — 「전일 9/1」이 아니라 「9월」(올해가 아니면 「25.12」)
  const mon = /^(\d{4})-(\d{2})$/.exec(String(asOf))
  if (mon) return mon[1] === KST_DAY.format(now).slice(0, 4) ? `${+mon[2]}월` : `${mon[1].slice(2)}.${mon[2]}`
  // 「JJA 2026」·「2026-Q2」 같은 기간 표기는 그대로(V8 은 「JJA 2026」 도 1월 1일로 읽어 버린다)
  if (typeof asOf === 'string' && !/^\d{4}-\d{2}-\d{2}/.test(asOf)) return asOf
  const t = parseAsOf(asOf)
  if (Number.isNaN(t.getTime())) return String(asOf)
  const hm = KST_HM.format(t)
  const md = KST_MD.format(t).replace(/\.\s?/g, '/').replace(/\/$/, '')
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(String(asOf))   // 시각이 없는 값에 「00:00」을 적지 않는다
  if (kind === 'prev') {
    if (KST_DAY.format(t) !== KST_DAY.format(now)) return `전일 ${md}`
    return dateOnly ? `종가 ${md}` : `종가 ${hm}`
  }
  return kind === 'delayed' ? `지연 ${dateOnly ? md : hm}` : hm
}

/** 등락률 한 벌: ▲ 3.04% / ▼ 0.25% / 0.00%. 값이 없으면 '—'. */
export function fmtPct(pct: number | null | undefined, decimals = 2): string {
  if (pct == null || !Number.isFinite(pct)) return '—'
  return `${fmtChange(pct, null, decimals)}%`
}

const KST_DAYNAME = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', weekday: 'short' })

/** 머리 날짜: 「10월 1일 (목)」. */
export function dayLabel(asOf: string | number | Date): string {
  const t = parseAsOf(asOf)
  return Number.isNaN(t.getTime()) ? '' : KST_DAYNAME.format(t)
}

/** 짧은 시각: 「10/2 09:00」. 날짜만 있으면 「10/2」. */
export function mdHm(asOf: string | number | Date): string {
  const t = parseAsOf(asOf)
  if (Number.isNaN(t.getTime())) return ''
  const md = KST_MD.format(t).replace(/\.\s?/g, '/').replace(/\/$/, '')
  return /^\d{4}-\d{2}-\d{2}$/.test(String(asOf)) ? md : `${md} ${KST_HM.format(t)}`
}

/** 차트 축 날짜: 일별 「9/30」 · 월별 「26.07」 · 그 밖은 그대로. */
export function shortDate(d: string): string {
  let m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d)
  if (m) return `${+m[2]}/${+m[3]}`
  m = /^\d{2}(\d{2})-(\d{2})$/.exec(d)
  return m ? `${m[1]}.${m[2]}` : d
}

/**
 * 히트맵 색 단계: 경계 ±2.5 · ±1 · 0. 부호 × (|v|<1 → 1 · <2.5 → 2 · 이상 → 3), 소수 둘째 자리로 반올림해 0 이면 0(보합).
 * 값이 없어도 0 이다(칸은 회색, 글자는 '—').
 */
export function heatStep(pct: number | null | undefined): number {
  if (pct == null || !Number.isFinite(pct)) return 0
  const v = Number(pct.toFixed(2))
  if (v === 0) return 0
  const a = Math.abs(v)
  const s = a >= 2.5 ? 3 : a >= 1 ? 2 : 1
  return v > 0 ? s : -s
}

/** 시계열 한 점: [날짜, 값]. 날짜는 'YYYY-MM-DD' · 'YYYY-MM' 등 묶음 그대로. */
export type Pt = [string, number]
export type PeriodKey = '1d' | '1w' | '3m' | '1y' | '2y' | 'all'
export const PERIODS: readonly { key: PeriodKey; label: string }[] = [
  { key: '1d', label: '1일' }, { key: '1w', label: '1주' }, { key: '3m', label: '3달' }, { key: '1y', label: '1년' },
  { key: '2y', label: '2년' }, { key: 'all', label: '전체' },
]

// 'YYYY-MM' · 'YYYY' · 분기('2026Q2' · '2026-Q2' = 그 분기 첫 달)도 문자열 비교가 되게 'YYYY-MM-DD' 로 늘린다
const dayKey = (d: string) => {
  const q = /^(\d{4})-?Q([1-4])$/.exec(d)
  if (q) return `${q[1]}-${String(+q[2] * 3 - 2).padStart(2, '0')}-01`
  const s = d.slice(0, 10)
  return s.length === 7 ? s + '-01' : s.length === 4 ? s + '-01-01' : s
}
const dayMs = (d: string) => new Date(dayKey(d) + 'T00:00:00Z').getTime()

/**
 * 일별·월별·분기 시계열을 기간 칩으로 자른다 — 끝 날짜에서 7일 · 3달 · 1년 · 2년 거꾸로, 그리고 전체.
 * 점이 2개 미만이거나 바로 앞 칩보다 점이 20% 넘게 많지 않으면 그 칩은 뺀다(칩은 있는데 그림이 거의 같은 일을 막는다 —
 * 1년치 일별 366점에 「2년」 366점 · 「1년」 365점이 따로 서지 않게).
 * 점 간격이 평균 24일 이상인 성긴 시계열(월별·분기)은 1주·3달을 만들지 않는다 — 3달 칩이 점 3개다.
 * 1일(분봉)은 묶음이 따로 줄 때만 있다 — 여기서는 만들지 않는다. 날짜를 못 읽으면 「전체」 하나.
 */
export function slicePeriods(series: Pt[] | null | undefined): Partial<Record<PeriodKey, Pt[]>> {
  const out: Partial<Record<PeriodKey, Pt[]>> = {}
  if (!series || series.length < 2) return out
  const endMs = dayMs(series[series.length - 1][0])
  if (Number.isNaN(endMs)) { out.all = series; return out }
  const coarse = (endMs - dayMs(series[0][0])) / (series.length - 1) >= 24 * 86_400_000
  const cut = (days: number, months: number) => {
    const d = new Date(endMs)
    d.setUTCDate(d.getUTCDate() - days)
    d.setUTCMonth(d.getUTCMonth() - months)
    return d.toISOString().slice(0, 10)
  }
  const plan: [PeriodKey, string | null][] = [['1w', cut(7, 0)], ['3m', cut(0, 3)], ['1y', cut(0, 12)], ['2y', cut(0, 24)], ['all', null]]
  let prev = 0
  for (const [k, c] of plan) {
    if (coarse && (k === '1w' || k === '3m')) continue
    const pts = c ? series.filter(p => dayKey(p[0]) > c) : series
    if (pts.length >= 2 && pts.length > prev * 1.2) { out[k] = pts; prev = pts.length }
  }
  return out
}

/** 52주 최저·최고(끝에서 1년 안). 시계열이 350일보다 짧으면 null — 52주라고 부를 수 없다. */
export function range52(series: Pt[] | null | undefined): { low: number; high: number } | null {
  if (!series || series.length < 2) return null
  if (!(dayMs(series[series.length - 1][0]) - dayMs(series[0][0]) >= 350 * 86_400_000)) return null
  const pts = slicePeriods(series)['1y'] ?? series
  let low = Infinity, high = -Infinity
  for (const [, v] of pts) { if (v < low) low = v; if (v > high) high = v }
  return high > low ? { low, high } : null
}
