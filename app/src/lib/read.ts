// 읽는 값(read) — 거시 지표의 지수 · 금액 원값 대신 사람이 읽는 값(전년비 · 전월비 · 증감)을 화면에 쓴다.
// 값은 수집 단계(scripts/read_values.py)가 한 번 만들고 묶음 칸 read 로 온다 — 화면은 다시 계산하지 않는다(일정 · 카드 · 상세가 같은 숫자).
// 공식 발표값이 있으면 src = official, 지수로 계산했으면 calc(「계산」 꼬리표), 값이 없으면 why(「1년 전 값 미발표」).
import type { Pt } from './format'
import type { StripItem } from './bundle'

export type ReadCell = {
  b: string; word: string; short: string; value: number | null; unit: string; dec: number; sign: boolean
  src: 'official' | 'calc' | 'none'; lo?: number; ref?: string; why?: string
}
export type Read = {
  name?: string; ref: string; freq: 'M' | 'Q' | 'D'; released?: string; main: ReadCell; subs: ReadCell[]
  prev?: number | null; cons?: number | null; diff?: number | null; size?: string | null
  series?: [string, number | null][]; rel?: [string, number | null, number | null][]; calc?: number
}

export const COUNTRY: Record<string, string> = { kr: '한국', us: '미국', eu: '유로', uk: '영국', de: '독일', jp: '일본', cn: '중국' }

/** 읽는 값 글: 부호(변화율 · 증감) · 자리수 · 단위. 범위면 「3.75~4.00%」. */
export function fmtRead(c: Pick<ReadCell, 'value' | 'dec' | 'sign' | 'unit' | 'b' | 'lo'>, withUnit = true): string {
  if (c.value == null || !Number.isFinite(c.value)) return '—'
  const n = (x: number) => x.toLocaleString('ko-KR', { minimumFractionDigits: c.dec, maximumFractionDigits: c.dec })
  const body = c.b === 'range' && c.lo != null ? `${n(c.lo)}~${n(c.value)}` : `${c.sign && c.value > 0 ? '+' : ''}${n(c.value)}`
  return withUnit && c.unit ? body + c.unit : body
}

/** 같은 기준 · 단위로 다른 값(지난 값 · 컨센서스)을 적을 칸 — 범위면 하단도 그 값에 맞춰 옮긴다(상단 4.25 → 4.00~4.25). */
export function cellAt(c: ReadCell, value: number | null | undefined): ReadCell {
  const v = value ?? null
  return { ...c, value: v, lo: c.b === 'range' && v != null && c.value != null && c.lo != null ? v - (c.value - c.lo) : c.lo }
}

/** 기준 기간 말: 2026-10 → 「10월분」 · 2026-Q3 → 「3분기」 · 2026-11-14 → 「11/14」. */
export function refLabel(ref?: string | null): string {
  if (!ref) return ''
  const q = /^(\d{4})-Q([1-4])$/.exec(ref)
  if (q) return `${q[2]}분기`
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ref)
  if (d) return `${+d[2]}/${+d[3]}`
  const m = /^(\d{4})-(\d{2})$/.exec(ref)
  return m ? `${+m[2]}월분` : ref
}

/** 발표일 말: 2026-11-10 → 「11/10 발표」. */
export const releasedLabel = (iso?: string) => (iso ? `${+iso.slice(5, 7)}/${+iso.slice(8, 10)} 발표` : '')

/** 지난 값 이름: 월 = 지난달 · 분기 = 지난 분기 · 일 = 직전. */
export const prevWord = (freq: Read['freq']) => (freq === 'Q' ? '지난 분기' : freq === 'D' ? '직전' : '지난달')

/** 컨센서스 대비 말: 「같음」 · 「0.1%p 높음」 · 「10.0만 명 많음」(+ 평소보다 크게 어긋나면 크기). 컨센서스가 없으면 null. */
export function consText(r: Read): string | null {
  if (r.cons == null || r.diff == null) return null
  if (Math.abs(r.diff) < 1e-9) return '같음'
  const pct = r.main.unit === '%'
  const amt = Math.abs(r.diff).toLocaleString('ko-KR', { minimumFractionDigits: r.main.dec, maximumFractionDigits: r.main.dec })
  const word = r.diff > 0 ? (pct ? '높음' : '많음') : (pct ? '낮음' : '적음')
  return `${amt}${pct ? '%p' : r.main.unit} ${word}`
}

/** 기간 열쇠 → 차트 날짜: 2026-10 → 2026-10-01 · 2026-Q3 → 2026-07-01. */
export function refDate(ref: string): string {
  const q = /^(\d{4})-Q([1-4])$/.exec(ref)
  if (q) return `${q[1]}-${String((+q[2] - 1) * 3 + 1).padStart(2, '0')}-01`
  return /^\d{4}-\d{2}$/.test(ref) ? `${ref}-01` : ref
}

export const readPts = (r?: Read): Pt[] => (r?.series ?? []).filter((p): p is [string, number] => p[1] != null).map(([k, v]): Pt => [refDate(k), v])

/** 나라 + 읽는 이름(「미국 소비자물가」). 나라를 모르면 이름만. */
export function readName(it: Pick<StripItem, 'label' | 'short'> & { country?: string; read?: Read }): string {
  const cn = COUNTRY[it.country ?? '']
  const nm = it.read?.name ?? it.short ?? it.label
  return cn && !nm.startsWith(cn) ? `${cn} ${nm}` : nm
}

/**
 * 읽는 값이 있는 칸을 화면 칸 모양으로(값 = 읽는 값 · 단위 · 자리수 · 시계열 = 읽는 값 시계열 · 등락 = 지난 값과의 차).
 * 띠 카드 · 큰 차트 · 부동산 카드가 이것을 그대로 그린다. read 가 없으면 그대로 돌려준다.
 */
export function asRead(it: StripItem): StripItem {
  const r = it.read
  if (!r || r.main.value == null) return it
  const pts = readPts(r)
  const name = readName(it)
  const d = r.main.dec
  return {
    ...it, label: name, short: name, shortM: name, value: r.main.value, scale: null, unit: r.main.unit || undefined, decimals: d,
    change: r.prev != null ? Math.round((r.main.value - r.prev) * 10 ** d) / 10 ** d : null, changePct: null,
    asOf: r.ref, series: pts.length ? pts : null, spark: pts.length ? pts.slice(-12).map(p => p[1]) : null,
  }
}
