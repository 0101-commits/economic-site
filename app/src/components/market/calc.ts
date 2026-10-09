// 시장 화면 계산 — 묶음 값에서 화면용 시계열·집계를 만든다. 화면 부품과 떼어 두어 node --test 로 바로 돈다.
//   node --test src/components/market/calc.test.ts
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(node 가 타입만 지우고 실행한다).
import type { Pt } from '../../lib/format'

/** 날짜 → 달 번호(연×12+월). 'YYYY-MM' · 'YYYY-MM-DD' · 'YYYYQn'(분기 첫 달). 못 읽으면 null. */
export function monthIndex(d: string): number | null {
  let m = /^(\d{4})-(\d{2})/.exec(d)
  if (m) return +m[1] * 12 + (+m[2] - 1)
  m = /^(\d{4})Q([1-4])$/.exec(d)
  return m ? +m[1] * 12 + (+m[2] - 1) * 3 : null
}

/** 끝 점에서 정확히 12달 앞 값. 그 달이 시계열에 없으면 null(가까운 달로 대신하지 않는다). */
export function yearAgo(series: Pt[] | null | undefined): number | null {
  if (!series?.length) return null
  const want = monthIndex(series[series.length - 1][0])
  if (want == null) return null
  const hit = series.find(p => monthIndex(p[0]) === want - 12)
  return hit ? hit[1] : null
}

/** 지수 시계열 → 전년비(%) 시계열. 12달 앞 점이 있는 달만 남는다. */
export function yoySeries(series: Pt[] | null | undefined): Pt[] {
  if (!series?.length) return []
  const at = new Map<number, number>()
  for (const [d, v] of series) { const k = monthIndex(d); if (k != null) at.set(k, v) }
  const out: Pt[] = []
  for (const [d, v] of series) {
    const k = monthIndex(d), base = k == null ? undefined : at.get(k - 12)
    if (base) out.push([d, (v / base - 1) * 100])
  }
  return out
}

/** 첫 점 = base 로 다시 맞춘다(비교 차트는 기간마다 시작을 100 으로). 첫 값이 0 이면 그대로. */
export function rebase(pts: Pt[], base = 100): Pt[] {
  const first = pts[0]?.[1]
  return first ? pts.map(([d, v]): Pt => [d, (v / first) * base]) : pts
}

/** 여러 시계열에서 모두에 있는 날짜만 남긴다 — 비교 차트는 같은 비율 자리를 같은 날짜로 보므로 길이·시작이 달라선 안 된다. */
export function alignDates(list: Pt[][]): Pt[][] {
  if (!list.length) return []
  const common = list.slice(1).reduce((s, l) => { const d = new Set(l.map(p => p[0])); return new Set([...s].filter(x => d.has(x))) }, new Set(list[0].map(p => p[0])))
  return list.map(l => l.filter(p => common.has(p[0])))
}

/** 누적 합(기간 시작 = 첫 날 값). */
export function cumsum(pts: Pt[]): Pt[] {
  let s = 0
  return pts.map(([d, v]): Pt => [d, (s += v)])
}

/** 끝에서 n 개씩 더한 합(첫 n−1 점은 버린다). 외국인 5일 누적 같은 칸. */
export function rollSum(pts: Pt[], n: number): Pt[] {
  const out: Pt[] = []
  let s = 0
  pts.forEach(([d, v], i) => {
    s += v
    if (i >= n) s -= pts[i - n][1]
    if (i >= n - 1) out.push([d, s])
  })
  return out
}

/** 그 날이 든 주의 월요일('YYYY-MM-DD'). */
export function weekKey(d: string): string {
  const t = new Date(d.slice(0, 10) + 'T00:00:00Z')
  t.setUTCDate(t.getUTCDate() - ((t.getUTCDay() + 6) % 7))
  return t.toISOString().slice(0, 10)
}

export type FlowRow = [string, number | null, number | null, number | null]

/** 투자자 일별 행 [날짜, 외국인, 기관, 개인] → 주(월요일 날짜)·월('YYYY-MM') 합계. 빈 값은 더하지 않고, 셋 다 비면 null. */
export function groupFlows(rows: FlowRow[], by: 'week' | 'month'): FlowRow[] {
  const out = new Map<string, FlowRow>()
  for (const [d, ...vals] of rows) {
    const k = by === 'week' ? weekKey(d) : d.slice(0, 7)
    const acc = out.get(k) ?? [k, null, null, null]
    vals.forEach((v, i) => { if (v != null) acc[i + 1] = ((acc[i + 1] as number | null) ?? 0) + v })
    out.set(k, acc)
  }
  return [...out.values()]
}

/** 행 [날짜, 값…] 의 col 번째 열 → 시계열(빈 값은 뺀다). */
export function column(rows: (string | number | null)[][], col: number): Pt[] {
  return rows.flatMap((r): Pt[] => (typeof r[col] === 'number' ? [[String(r[0]), r[col] as number]] : []))
}

/** 달력 한 달(일요일 시작 7열): 'YYYY-MM' → 첫 주 앞 빈칸(null) + 그 달 날짜('YYYY-MM-DD'). 끝 주 뒤 빈칸은 격자가 남긴다. */
export function monthCells(ym: string): (string | null)[] {
  const [y, m] = ym.split('-').map(Number)
  const lead = new Date(Date.UTC(y, m - 1, 1)).getUTCDay()
  const days = new Date(Date.UTC(y, m, 0)).getUTCDate()
  return [...Array<null>(lead).fill(null), ...Array.from({ length: days }, (_, i) => `${ym}-${String(i + 1).padStart(2, '0')}`)]
}

/** 'YYYY-MM' 에 k 달을 더한다(빼기는 음수). */
export function addMonth(ym: string, k: number): string {
  const [y, m] = ym.split('-').map(Number)
  const t = new Date(Date.UTC(y, m - 1 + k, 1))
  return `${t.getUTCFullYear()}-${String(t.getUTCMonth() + 1).padStart(2, '0')}`
}

/**
 * 12열 격자 칸 나누기: 처음 둘은 6+6(큰 차트 + 고른 보기), 그다음은 한 줄에 per 개씩.
 * 끝 줄이 덜 차면 그 줄 패널끼리 12칸을 나눠 오른쪽 끝선이 어긋나지 않게 한다.
 */
export function spans(n: number, per: 2 | 3): number[] {
  const out: number[] = []
  for (let i = 0; i < Math.min(n, 2); i++) out.push(n === 1 ? 12 : 6)
  const rest = Math.max(0, n - 2), tail = rest % per
  for (let i = 0; i < rest; i++) out.push(i >= rest - tail ? 12 / tail : 12 / per)
  return out
}
