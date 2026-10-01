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
 * - live: 오늘 값이고 liveMin 분 이내
 * - delayed(지연): 오늘 값이지만 liveMin 분보다 오래됨
 */
export function asOfKind(asOf: string | number | Date, now: Date = new Date(), opts: { filled?: boolean; liveMin?: number } = {}): AsOfKind {
  if (opts.filled) return 'filled'
  const t = parseAsOf(asOf)
  if (Number.isNaN(t.getTime())) return 'filled'
  if (KST_DAY.format(t) < KST_DAY.format(now)) return 'prev'
  return now.getTime() - t.getTime() <= (opts.liveMin ?? 20) * 60_000 ? 'live' : 'delayed'
}

/**
 * 묶음(scripts/build_bundles.py)이 이미 판정한 상태 → 배지 갈래. 묶음에 state 가 있으면 그것이 단일 원천이고
 * asOfKind 는 data.json 폴백에서만 쓴다. missing(자료 없음)은 배지 대신 값 자리의 '—' 가 말한다.
 */
export type BundleState = 'live' | 'prev' | 'stale' | 'kept' | 'missing'
const STATE_KIND: Record<BundleState, AsOfKind | null> = { live: 'live', prev: 'prev', stale: 'delayed', kept: 'filled', missing: null }
export function kindFromState(state: string | undefined): AsOfKind | null | undefined {
  return state && state in STATE_KIND ? STATE_KIND[state as BundleState] : undefined
}

/** 배지 문구: LIVE 는 시각만 · 오늘 종가는 「종가 15:30」 · 앞선 날은 「전일 9/30」 · 지연은 시각 · 보강은 낱말만. */
export function asOfLabel(kind: AsOfKind, asOf: string | number | Date, now: Date = new Date()): string {
  const t = parseAsOf(asOf)
  if (kind === 'filled' || Number.isNaN(t.getTime())) return '보강'
  const hm = KST_HM.format(t)
  if (kind === 'prev') {
    if (KST_DAY.format(t) === KST_DAY.format(now) && !/^\d{4}-\d{2}-\d{2}$/.test(String(asOf))) return `종가 ${hm}`
    return `전일 ${KST_MD.format(t).replace(/\.\s?/g, '/').replace(/\/$/, '')}`
  }
  return kind === 'delayed' ? `지연 ${hm}` : hm
}
