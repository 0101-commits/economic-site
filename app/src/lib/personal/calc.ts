// 내 자산 계산 — 순수 함수만(저장소·화면 없음). node --test 로 바로 돌린다(calc.test.ts).
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(format.ts 와 같은 규칙).
import { fmtNumber, changeDir, type Pt } from '../format.ts'

/** 보유 한 줄 — 현행 사이트 portfolioV1.items 모양 그대로(code 가 아니라 symbol). 모르는 필드는 건드리지 않고 지나간다. */
export type Holding = {
  id: string
  symbol: string
  market: 'KR' | 'US'
  name?: string
  ccy?: 'KRW' | 'USD'
  qty: number | null
  avg: number | null
  fxBuy?: number | null
  [k: string]: unknown
}
/** 시세 한 칸: 현재가와 전일 대비 등락률(%). */
export type Quote = { price: number; pct: number | null; name?: string }
/** 달러원: 지금과 전일(없으면 null — 환차는 0 으로 본다). */
export type Fx = { now: number; prev: number | null } | null

export type Row = {
  h: Holding
  usd: boolean
  q: Quote | null
  value: number | null     // 원화 평가액
  cost: number | null      // 원화 원금(달러는 매입 환율, 없으면 지금 환율)
  pnl: number | null
  pnlPct: number | null
  today: { price: number; fx: number } | null   // 오늘 손익: 주가 몫 · 환차 몫(원)
}

export type Totals = {
  value: number            // 시세 있는 종목의 평가액 합
  cost: number             // 평가액과 원금이 둘 다 있는 종목의 원금 합
  basisValue: number       // 위 cost 와 같은 종목들의 평가액 합(수익률·스냅샷 기준)
  pnl: number | null
  pnlPct: number | null
  today: { price: number; fx: number; div: number; total: number; pct: number | null }
  domestic: number         // 국내(KR 상장) 평가액
  foreign: number          // 해외(US 상장) 평가액
  usdValue: number         // 달러 자산 평가액 — 환율 what-if 대상
  missing: number          // 수량은 있는데 시세(또는 환율)가 없어 뺀 종목 수
}

export const isUsd = (h: Pick<Holding, 'ccy' | 'market'>) => (h.ccy ?? (h.market === 'US' ? 'USD' : 'KRW')) === 'USD'

/**
 * 보유 평가. 오늘 손익은 정확히 둘로 나뉜다(합 = 어제 평가액에서 오늘 평가액까지의 변화).
 *   주가 몫 = (지금가 − 전일가) × 수량 × 전일 환율,  환차 몫 = 지금가 × 수량 × (지금 환율 − 전일 환율)
 * 전일가 = 지금가 ÷ (1 + 등락률/100). 배당은 원장에서 오늘 날짜로 적은 배당 합(divToday).
 */
export function evaluate(holdings: Holding[], quotes: Map<string, Quote>, fx: Fx, divToday = 0): { rows: Row[]; totals: Totals } {
  const t: Totals = {
    value: 0, cost: 0, basisValue: 0, pnl: null, pnlPct: null,
    today: { price: 0, fx: 0, div: divToday, total: 0, pct: null },
    domestic: 0, foreign: 0, usdValue: 0, missing: 0,
  }
  let prevValue = 0
  const rows = holdings.map((h): Row => {
    const usd = isUsd(h)
    const q = quotes.get(h.symbol) ?? null
    const qty = h.qty != null && h.qty > 0 ? h.qty : null
    const avg = h.avg != null && h.avg > 0 ? h.avg : null
    const fxNow = usd ? fx?.now ?? null : 1
    const costMul = usd ? h.fxBuy || fxNow : 1
    const cost = avg != null && qty != null && costMul != null ? avg * qty * costMul : null
    if (!q || qty == null || fxNow == null) {
      if (qty != null) t.missing++
      return { h, usd, q, value: null, cost, pnl: null, pnlPct: null, today: null }
    }
    const value = q.price * qty * fxNow
    const fxPrev = usd ? fx?.prev ?? fxNow : 1
    const prevPrice = q.pct != null ? q.price / (1 + q.pct / 100) : q.price
    const today = { price: (q.price - prevPrice) * qty * fxPrev, fx: q.price * qty * (fxNow - fxPrev) }
    t.value += value
    if (usd) { t.foreign += value; t.usdValue += value } else t.domestic += value
    if (cost != null) { t.cost += cost; t.basisValue += value }
    t.today.price += today.price
    t.today.fx += today.fx
    prevValue += value - today.price - today.fx
    return { h, usd, q, value, cost, pnl: cost != null ? value - cost : null, pnlPct: cost ? (value / cost - 1) * 100 : null, today }
  })
  if (t.cost > 0) { t.pnl = t.basisValue - t.cost; t.pnlPct = (t.basisValue / t.cost - 1) * 100 }
  t.today.total = t.today.price + t.today.fx + t.today.div
  t.today.pct = prevValue > 0 ? (t.today.total / prevValue) * 100 : null
  return { rows, totals: t }
}

/** 환율 what-if: 달러원이 pct% 움직이면(주가는 그대로) 총평가가 얼마가 되나. 추정치. */
export function fxWhatIf(total: number, usdValue: number, pct: number): { total: number; delta: number } {
  const delta = (usdValue * pct) / 100
  return { total: total + delta, delta }
}

/** 국민연금 주식 중 국내 비중(%) = 국내주식 ÷ (국내주식 + 해외주식). 자산배분 표(asset·pct)에서 이름으로 찾는다. */
export function npsDomesticShare(allocation: { asset: string; pct: number }[] | null | undefined): number | null {
  const get = (name: string) => allocation?.find(a => a.asset === name)?.pct
  const kr = get('국내주식'), ov = get('해외주식')
  return kr != null && ov != null && kr + ov > 0 ? (kr / (kr + ov)) * 100 : null
}

/** 스냅샷 한 건: 날짜 · 평가액 · 원금(현행 사이트 pfSnapshotsV1 모양). */
export type Snap = { d: string; ev: number; ct: number }

/** 같은 날짜는 바꿔 넣고, 날짜순, 끝에서 730건만(현행 사이트와 같은 상한). */
export function upsertSnap(snaps: Snap[], s: Snap): Snap[] {
  return [...snaps.filter(x => x && x.d && x.d !== s.d), s].sort((a, b) => (a.d < b.d ? -1 : 1)).slice(-730)
}

export const RISK_MIN = 60

/**
 * 위험 지표 — 현행 사이트 pfRiskMetrics 와 같은 셈. R = 평가액 ÷ 원금 이라 추가 매수에 덜 흔들린다.
 * 하루 수익률 = ln(R_t / R_{t-1}), 날짜 간격 1~4일 쌍만. 60건 미만이면 n 만 준다(신뢰 구간 미달).
 * var95 = 오늘 평가액 × 하루 표준편차 × 1.645 — 「20일 중 하루는 이보다 더 잃을 수 있다」(정규분포 가정).
 * 샤프 = 하루 평균 ÷ 하루 표준편차 × √252, 소르티노 = 하루 평균 ÷ 손실 쪽 편차(0 아래만 제곱 평균의 제곱근) × √252.
 * 무위험 수익률은 0 으로 둔다(금리 자료를 끌어오지 않는다 — 화면이 이 가정을 밝힌다). 편차가 0 이면 그 값은 없다.
 */
export function risk(snaps: Snap[], value: number): { n: number; sd?: number; var95?: number; mdd?: number; sharpe?: number; sortino?: number } {
  const seq = snaps.filter(s => s && s.ev > 0 && s.ct > 0).map(s => ({ d: s.d, R: s.ev / s.ct }))
  const rs: number[] = []
  for (let i = 1; i < seq.length; i++) {
    const gap = (Date.parse(seq[i].d) - Date.parse(seq[i - 1].d)) / 86_400_000
    if (gap >= 1 && gap <= 4) rs.push(Math.log(seq[i].R / seq[i - 1].R))
  }
  const n = rs.length
  if (n < RISK_MIN) return { n }
  const mean = rs.reduce((a, b) => a + b, 0) / n
  const sd = Math.sqrt(rs.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1))
  let peak = -Infinity, mdd = 0
  for (const p of seq) { if (p.R > peak) peak = p.R; mdd = Math.min(mdd, p.R / peak - 1) }
  const down = Math.sqrt(rs.reduce((a, r) => a + Math.min(r, 0) ** 2, 0) / n)
  const yr = Math.sqrt(252)
  return { n, sd, var95: value * sd * 1.645, mdd: mdd * 100, sharpe: sd > 0 ? (mean / sd) * yr : undefined, sortino: down > 0 ? (mean / down) * yr : undefined }
}

/**
 * 시장 대비 — 스냅샷 날짜마다 지수 종가(그날, 없으면 7일 안의 직전 값)를 맞춰 첫 날 = 100 으로 편다.
 * 나 = 평가액 ÷ 원금(risk 의 R — 추가 매수로 원금이 늘어도 수익률만 남는다). 지수 하나라도 값이 없는 날은 뺀다.
 * pts 는 날짜순. 맞춘 날이 2일 미만이면 null.
 */
export function benchmark(snaps: Snap[], idx: { name: string; pts: Pt[] }[]): { mine: Pt[]; idx: { name: string; pts: Pt[] }[] } | null {
  const at = (pts: Pt[], d: string) => {
    let hit: Pt | undefined
    for (const p of pts) { if (p[0] > d) break; hit = p }
    return hit && Date.parse(d) - Date.parse(hit[0]) <= 7 * 86_400_000 && hit[1] > 0 ? hit[1] : null
  }
  const rows = snaps.filter(s => s && s.ev > 0 && s.ct > 0).flatMap(s => {
    const v = idx.map(i => at(i.pts, s.d))
    return v.every(x => x != null) ? [{ d: s.d, R: s.ev / s.ct, v: v as number[] }] : []
  })
  if (rows.length < 2) return null
  const [b] = rows
  return {
    mine: rows.map((r): Pt => [r.d, (r.R / b.R) * 100]),
    idx: idx.map((i, j) => ({ name: i.name, pts: rows.map((r): Pt => [r.d, (r.v[j] / b.v[j]) * 100]) })),
  }
}

/** 묶음 아무 깊이의 종목 칸(code · price · chgPct)을 시세로 모은다. 같은 코드가 여러 목록(거래대금 · 체결 상위 …)에 있으면 먼저 본 것 하나만. */
export function collectStocks(root: unknown, out: Map<string, Quote>) {
  const walk = (o: unknown): void => {
    if (!o || typeof o !== 'object') return
    if (Array.isArray(o)) { o.forEach(walk); return }
    const r = o as Record<string, unknown>
    if (typeof r.code === 'string' && typeof r.price === 'number' && r.price > 0 && !out.has(r.code)) {
      out.set(r.code, { price: r.price, pct: typeof r.chgPct === 'number' ? r.chgPct : null, name: typeof r.name === 'string' ? r.name : undefined })
    }
    Object.values(r).forEach(walk)
  }
  walk(root)
}

export type Unit = 'man' | 'won'

/** 금액: 원 = 「1,234,567원」, 만원 = 「1,235만원」(100만원 미만은 소수 한 자리). */
export function fmtMoney(v: number | null | undefined, unit: Unit = 'man'): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (unit === 'won') return `${fmtNumber(v, 0)}원`
  return `${fmtNumber(v / 1e4, Math.abs(v) < 1e6 ? 1 : 0)}만원`
}

/** 금액 방향: 표시 자릿수(원 0 · 만원 소수 1)로 반올림해 0 이면 보합 — 글자와 색이 어긋나지 않게. */
export const moneyDir = (v: number | null | undefined, unit: Unit = 'man') =>
  v == null ? 'flat' : changeDir(unit === 'won' ? v : v / 1e4, unit === 'won' ? 0 : 1)

/** 금액 등락: 「▲ 12만원 (1.23%)」. 부호는 화살표로만(format.ts fmtChange 와 같은 규칙). */
export function fmtMoneyChange(v: number | null | undefined, pct: number | null | undefined, unit: Unit = 'man'): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const dir = moneyDir(v, unit)
  const arrow = dir === 'up' ? '▲ ' : dir === 'down' ? '▼ ' : ''
  const p = pct == null || !Number.isFinite(pct) ? '' : ` (${fmtNumber(Math.abs(pct), 2)}%)`
  return `${arrow}${fmtMoney(Math.abs(v), unit)}${p}`
}

const KST = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' })
/** 한국 날짜 'YYYY-MM-DD'. */
export const kstDay = (t: Date | number = new Date()) => KST.format(t)
