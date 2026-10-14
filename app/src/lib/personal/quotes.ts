// 보유 종목 시세 — 묶음(data.ts loadMarketData 의 home·market-domestic)에 있으면 그것, 없으면 Worker /quotes 한 번(batchQuotes, 계약 C5).
// /quotes 가 없거나(404 — Worker 배포 전) 실패하면 종전 길: Worker 프록시로 Yahoo 일봉을 하나씩.
// 현행 화면(js/app1.js fetchYahooQuote)과 같은 경로: `<Worker>/?url=` + query1.finance.yahoo.com/v8/finance/chart/<심볼>?range=5d&interval=1d.
// market-global 묶음은 지수뿐이라(종목 칸 없음) 여기서 따로 보지 않는다.
// 받은 값은 sessionStorage 에 10분 둔다(탭을 닫으면 사라진다). 한 번에 4개까지 동시에. 못 받은 종목은 「시세 없음」 그대로 둔다.
// holdingQuotes 는 보유 목록을 읽는 화면(내 자산 Holdings — PinGate 안)에서만 부른다. stockSeries(1년 일봉)는 종목 상세가 부른다(보유를 읽지 않는다).
// batchQuotes 는 관심(홈 관심 칸 · 오른쪽 패널) · 검색 행 · 보유가 같이 쓴다 — 종목 코드만 보내고 금액은 싣지 않는다.
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(calc.ts 와 같은 규칙). node --test 로 바로 돌린다(quotes.test.ts).
import type { Holding, Quote } from './calc'
import type { Pt } from '../format'
import type { StripItem } from '../bundle'
import type { StockRow } from '../detail'
import { WORKER, watchKind } from './remote.ts'

const CACHE_KEY = 'econHoldQuotes_v1'
const TTL_MS = 10 * 60_000
const PARALLEL = 4

/** 보유 한 줄 → Yahoo 심볼 후보(앞에서부터 시도). 국내 6자리 = .KS 다음 .KQ, 미국 = 현행 화면이 적어 둔 yahoo 칸 또는 티커 — 점은 줄표로(Yahoo 는 BRK.B 를 BRK-B 로 받는다). */
export function yahooSymbols(h: Pick<Holding, 'symbol' | 'market'> & { yahoo?: unknown }): string[] {
  if (h.market === 'KR') return /^[0-9A-Z]{6}$/.test(h.symbol) ? [`${h.symbol}.KS`, `${h.symbol}.KQ`] : []
  const y = (typeof h.yahoo === 'string' && h.yahoo.trim() ? h.yahoo.trim() : h.symbol).replace(/\./g, '-')
  return y ? [y] : []
}

export const chartUrl = (sym: string, range = '5d') =>
  `${WORKER}/?url=${encodeURIComponent(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=${range}&interval=1d`)}`

type Chart = { chart?: { result?: { meta?: Record<string, unknown>; timestamp?: number[]; indicators?: { quote?: { close?: (number | null)[]; volume?: (number | null)[] }[] } }[] | null } }
const pos = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null)
type ChartRes = NonNullable<NonNullable<Chart['chart']>['result']>[number]
/** i 번째 일봉의 거래소 현지 날짜(타임스탬프가 없으면 null). */
function candleDay(res: ChartRes, i: number): string | null {
  const t = res.timestamp?.[i], off = res.meta?.gmtoffset
  return typeof t === 'number' ? new Date((t + (typeof off === 'number' ? off : 0)) * 1000).toISOString().slice(0, 10) : null
}

/**
 * 일봉 응답 → 현재가 · 전일 종가. 현재가 = meta.regularMarketPrice(없으면 마지막 일봉 종가).
 * 전일 종가 = 마지막 일봉 「바로 앞」 일봉들 중 가장 최근의 확정 종가(현행 closes[-2] 규칙).
 * 빈칸(null)을 먼저 빼고 끝에서 두 번째를 고르면 안 된다 — 미국 종목은 마지막 일봉 종가가 null 로 오는 일이 있어
 * (2026-10-02 AAPL 실측) 그러면 하루 더 앞 종가를 전일로 잡는다. 앞 일봉이 없을 때만 meta.chartPreviousClose.
 * 장중엔 오늘 일봉이 둘(같은 날짜) 오는 일이 있어 마지막 일봉과 같은 날짜인 일봉은 전일로 보지 않는다.
 * 종목이 없으면 Yahoo 는 200 에 result: null 을 준다 → null.
 * exchange(국내만): 접미사가 틀린 물음에도 Yahoo 는 빈 응답 대신 엉뚱한 값을 준다 — 2026-10-02 실측 247540(코스닥).KS 가
 * 194,000원(실제 115,700원, exchangeName KOE · instrumentType MUTUALFUND), 005930.KQ 가 84,400원(KOE · MUTUALFUND).
 * 그래서 거래소 표식(.KS = KSC · .KQ = KOE)이 맞고 MUTUALFUND 가 아닌 응답만 받는다.
 */
export function parseChart(j: Chart | null | undefined, exchange?: string): { price: number; prev: number | null } | null {
  const res = j?.chart?.result?.[0]
  const meta = res?.meta
  if (!meta) return null
  if (exchange && (meta.exchangeName !== exchange || meta.instrumentType === 'MUTUALFUND')) return null
  const closes = res.indicators?.quote?.[0]?.close ?? []
  const price = pos(meta.regularMarketPrice) ?? pos(closes[closes.length - 1])
  if (price == null) return null
  let prev: number | null = null
  const last = candleDay(res, closes.length - 1)
  for (let i = closes.length - 2; i >= 0 && prev == null; i--) if (last == null || candleDay(res, i) !== last) prev = pos(closes[i])
  return { price, prev: prev ?? pos(meta.chartPreviousClose) ?? pos(meta.previousClose) }
}

const toQuote = (p: { price: number; prev: number | null }): Quote => ({ price: p.price, pct: p.prev ? (p.price / p.prev - 1) * 100 : null })

type Cache = Record<string, { t: number; price: number; prev: number | null }>
function readCache(): Cache {
  try { const c = JSON.parse(sessionStorage.getItem(CACHE_KEY) || '{}'); return c && typeof c === 'object' ? c : {} } catch { return {} }
}
function writeCache(c: Cache) { try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(c)) } catch { /* 못 두면 다음에 다시 받는다 */ } }

/** 국내 접미사 → Yahoo 거래소 표식(parseChart 의 exchange). */
const KR_EXCHANGE: Record<string, string> = { '.KS': 'KSC', '.KQ': 'KOE' }

/** at = 마지막 체결 시각(Yahoo meta.regularMarketTime, ISO) — 없으면 없다. */
async function fetchOne(h: Pick<Holding, 'symbol' | 'market'> & { yahoo?: unknown }): Promise<{ price: number; prev: number | null; at?: string } | null> {
  for (const sym of yahooSymbols(h)) {
    try {
      const r = await fetch(chartUrl(sym), { signal: AbortSignal.timeout(8_000) })
      const j: Chart | null = r.ok ? await r.json() : null
      const p = parseChart(j, KR_EXCHANGE[sym.slice(-3)])
      const t = j?.chart?.result?.[0]?.meta?.regularMarketTime
      if (p) return typeof t === 'number' ? { ...p, at: new Date(t * 1000).toISOString() } : p
    } catch { /* 다음 후보 */ }
  }
  return null
}

// ── 관심 · 보유 값 한 번에(Worker /quotes, 계약 C5) ─────────────
/** 종목 하나의 지금 값. prev = 전일 종가(없으면 null), pct = 등락률(%), at = 마지막 체결 시각(ISO, 없으면 없음). */
export type LiveQuote = { price: number; prev: number | null; pct: number | null; at?: string }

const BATCH_MAX = 30          // Worker /quotes 한 번에 받는 코드 수(C5)
const BATCH_TTL = 60_000      // 같은 코드는 60초 안에 다시 묻지 않는다(Worker 보관과 같은 값) — 홈 관심 칸 · 오른쪽 패널이 같은 때 부른다
const batchMemo = new Map<string, { t: number; q: LiveQuote | null }>()
let noBatch = false           // 이 탭에서 /quotes 가 404 였다(Worker 배포 전) — 다시 묻지 않고 하나씩 받는다
const inflight = new Map<string, Promise<LiveQuote | null>>()   // 받는 중인 코드 → 그 결과(같은 순간 여러 곳이 부를 때 한 번만)

/** /quotes 응답 → 코드별 값. 값이 0 이하 · 숫자가 아닌 칸은 버린다. 등락률이 없으면 전일 종가로 구한다. */
export function parseBatch(j: unknown): Map<string, LiveQuote> {
  const out = new Map<string, LiveQuote>()
  const items = (j as { items?: unknown } | null)?.items
  if (!items || typeof items !== 'object') return out
  for (const [code, v] of Object.entries(items as Record<string, Record<string, unknown> | null>)) {
    const price = pos(v?.price)
    if (price == null) continue
    const prev = pos(v?.prev)
    const pct = typeof v?.pct === 'number' && Number.isFinite(v.pct) ? v.pct : prev ? (price / prev - 1) * 100 : null
    out.set(code, { price, prev, pct, ...(typeof v?.at === 'string' ? { at: v.at } : {}) })
  }
  return out
}

/**
 * /quotes 한 번 → 코드별 값. 하나씩 받는 길(fetchEach)로 물러서는 것은 404(Worker 가 아직 이 길을 모름)일 때뿐이다 —
 * 429(제한 초과) · 400 · 5xx · 시간 초과에 코드마다 프록시를 다시 부르면 같은 제한기에 최대 60번을 더 쏜다(PR #170 검토).
 * 그때는 빈 결과(못 받음)를 돌려주고, 60초 뒤 다시 묻는다.
 */
async function fetchBatch(codes: string[]): Promise<Map<string, LiveQuote> | 'fallback'> {
  try {
    const r = await fetch(`${WORKER}/quotes?codes=${codes.map(encodeURIComponent).join(',')}`, { signal: AbortSignal.timeout(8_000) })
    if (r.status === 404) { noBatch = true; return 'fallback' }
    return r.ok ? parseBatch(await r.json()) : new Map()
  } catch { return new Map() }
}

/** 종전 길: 코드마다 Yahoo 일봉(국내 .KS 다음 .KQ) — 동시 4개까지. */
async function fetchEach(codes: string[]): Promise<Map<string, LiveQuote>> {
  const out = new Map<string, LiveQuote>()
  let i = 0
  const worker = async () => {
    while (i < codes.length) {
      const c = codes[i++]
      const p = await fetchOne({ symbol: c, market: /^\d/.test(c) ? 'KR' : 'US' })
      if (p) out.set(c, { ...p, pct: p.prev ? (p.price / p.prev - 1) * 100 : null })
    }
  }
  await Promise.all(Array.from({ length: Math.min(PARALLEL, codes.length) }, worker))
  return out
}

/**
 * 종목 코드(국내 6자리 · 미국 티커)들의 지금 값 — Worker /quotes 에 30개씩 한 번, 그게 안 되면(404 · 실패) 코드마다 Yahoo 일봉.
 * 종목 코드가 아닌 id(지표)는 묻지 않는다. 못 받은 코드는 결과에 없다(지어내지 않는다). 같은 코드는 60초 안에 다시 묻지 않는다.
 */
export async function batchQuotes(codes: string[], now = Date.now()): Promise<Map<string, LiveQuote>> {
  const out = new Map<string, LiveQuote>()
  const wait: [string, Promise<LiveQuote | null>][] = []
  const fresh: string[] = []
  for (const c of new Set(codes)) {
    if (watchKind(c) !== 'stock') continue
    const m = batchMemo.get(c)
    const going = inflight.get(c)
    if (m && now - m.t < BATCH_TTL) { if (m.q) out.set(c, m.q) } else if (going) { wait.push([c, going]) } else { fresh.push(c) }
  }
  // 홈 관심 칸 · 오른쪽 패널 · 검색이 같은 순간에 부른다 — 이미 받는 중인 코드는 그 요청을 같이 기다린다
  for (let i = 0; i < fresh.length; i += BATCH_MAX) {
    const part = fresh.slice(i, i + BATCH_MAX)
    const got = (async () => {
      const r = noBatch ? 'fallback' as const : await fetchBatch(part)
      return r === 'fallback' ? fetchEach(part) : r
    })()
    for (const c of part) {
      const one = got.then(m => m.get(c) ?? null, () => null)
      inflight.set(c, one)
      void one.finally(() => { if (inflight.get(c) === one) inflight.delete(c) })
      wait.push([c, one])
    }
  }
  for (const [c, p] of wait) {
    const q = await p
    batchMemo.set(c, { t: now, q })
    if (q) out.set(c, q)
  }
  return out
}

/** /quotes 값 → 띠 칸 모양(홈 관심 칸 · 오른쪽 패널 · 검색 행). 체결 시각이 있으면 15분 실시간(지나면 「HH:MM 기준」 — chartBasis 와 같은 규칙). */
export function quoteItem(code: string, name: string | undefined, q: LiveQuote | undefined): StripItem {
  const at = q?.at ? Date.parse(q.at) : NaN
  return {
    id: code, label: name || code, decimals: /^\d/.test(code) ? 0 : 2,
    value: q?.price ?? null, change: q?.prev ? q.price - q.prev : null, changePct: q?.pct ?? null, asOf: q?.at ?? null,
    ...(Number.isNaN(at) ? {} : { state: 'live', liveUntil: new Date(at + 15 * 60_000).toISOString() }),
  }
}

/** 묶음 종목 행 → 띠 칸 모양. 묶음 행엔 등락률만 있어 등락폭은 비운다. */
export const rowItem = (r: StockRow): StripItem => ({
  id: r.code, label: r.short || r.name, decimals: /^\d/.test(r.code) ? 0 : 2,
  value: r.price, change: null, changePct: r.chgPct, asOf: r.asOf ?? null, state: r.state, liveUntil: r.liveUntil,
})

/**
 * 보유 종목 시세 지도(키 = symbol, calc.ts evaluate 가 읽는 모양). have(묶음 시세)를 그대로 담고,
 * 묶음에 없는 보유 종목만 10분 저장본 → batchQuotes(/quotes, 안 되면 Yahoo 하나씩) 순서로 채운다.
 * 미국 종목은 현행 화면이 적어 둔 yahoo 칸이 있으면 그 심볼로 묻는다(yahooSymbols 와 같은 규칙).
 */
export async function holdingQuotes(items: Holding[], have: Map<string, Quote>, now = Date.now()): Promise<Map<string, Quote>> {
  const out = new Map(have)
  const cache = readCache()
  const need = new Map<string, Holding[]>()   // 물을 코드 → 보유 줄(심볼은 달라도 같은 코드로 묻는 줄이 있다 — BRKB · BRK.B)
  const seen = new Set<string>()
  for (const h of items) {
    const k = `${h.market}:${h.symbol}`
    if (out.has(h.symbol) || seen.has(k)) continue
    seen.add(k)
    const c = cache[k], code = h.market === 'KR' ? h.symbol : yahooSymbols(h)[0]
    if (c && now - c.t < TTL_MS && pos(c.price)) out.set(h.symbol, toQuote(c))
    else if (code) need.set(code, [...(need.get(code) ?? []), h])
  }
  // 종목 코드 꼴(watchKind)만 /quotes 로 — 그 밖의 보유 심볼(BTC-USD 등)은 종전처럼 하나씩(PR #170 검토)
  const codes = [...need.keys()], odd = codes.filter(c => watchKind(c) !== 'stock')
  const got = new Map<string, LiveQuote>([
    ...(codes.length > odd.length ? await batchQuotes(codes.filter(c => watchKind(c) === 'stock'), now) : []),
    ...(odd.length ? await fetchEach(odd) : []),
  ])
  for (const [code, q] of got) {
    for (const h of need.get(code) ?? []) {
      cache[`${h.market}:${h.symbol}`] = { t: now, price: q.price, prev: q.prev }
      out.set(h.symbol, { price: q.price, pct: q.pct })
    }
  }
  if (need.size) writeCache(cache)
  return out
}

// ── 종목 상세(/i/<코드>)의 흐름 차트 ─────────────────────
/**
 * 종목 1년 일봉: pts = [거래소 현지 날짜, 종가](빈 종가는 뺀다 · 같은 날이 둘이면 뒤 것), 지금 값 · 전일은 parseChart 규칙, name = Yahoo 이름, asOf = 마지막 체결 시각.
 * vol = 마지막 일봉(pts 끝 날짜)의 거래량(주) — 그 봉에 거래량이 없으면 없다(앞 날 거래량을 끌어오지 않는다).
 * session = 지금 정규장 시작 · 끝(ms, Yahoo meta.currentTradingPeriod.regular) — 기준 표기(chartBasis)가 장 중인지 가른다.
 */
export type StockChart = { pts: Pt[]; price: number; prev: number | null; name?: string; asOf?: string; vol?: { day: string; value: number }; session?: { start: number; end: number } }

/**
 * 일봉 값의 기준 시각(배지에 넘길 asOf · state). 정규장 중이면 마지막 체결 시각 + 실시간 기한 15분(지나면 「HH:MM 기준」 — 주황 「지연」은 묶음 stale 만 쓴다),
 * 아니면 마지막 봉 날짜(거래소 날짜 — 미국은 미국 거래일) + prev = 그날 종가. 체결 시각(한국 시각)을 쓰면 미국 10/9 마감이
 * 「전일 10/10」 · 한국 오전엔 주황 「지연 05:00」으로 나왔다(2026-10-12 화면 리뷰). 장 시간을 모르면 장 밖으로 본다.
 */
export function chartBasis(c: StockChart, now = Date.now()): { asOf: string | undefined; state?: string; liveUntil?: string } {
  const s = c.session
  // 장 중: 묶음 칸과 같은 규칙 — 체결 15분 안은 실시간, 지나면 「HH:MM 기준」. 국내 Yahoo 시세는 늘 ~20분 늦어 거래량이 주황
  // 「지연 09:59」로 떠 옆 가격 「10:00 기준」과 갈렸다(2026-10-13 장중 점검). 15분 = asOfKind 기본 · 묶음 liveMin.
  if (s && now >= s.start && now < s.end) {
    const t = c.asOf ? Date.parse(c.asOf) : NaN
    return Number.isNaN(t) ? { asOf: c.asOf } : { asOf: c.asOf, state: 'live', liveUntil: new Date(t + 15 * 60_000).toISOString() }
  }
  return { asOf: c.pts[c.pts.length - 1][0], state: 'prev' }
}

/** 일봉 응답 → StockChart. parseChart 와 같은 거래소 검사를 거친다. 종가가 2개 미만이면 null. */
export function parseSeries(j: Chart | null | undefined, exchange?: string): StockChart | null {
  const p = parseChart(j, exchange)
  const res = j?.chart?.result?.[0]
  if (!p || !res) return null
  const meta = res.meta ?? {}
  const closes = res.indicators?.quote?.[0]?.close ?? []
  const vols = res.indicators?.quote?.[0]?.volume ?? []
  const pts: Pt[] = []
  let vol: StockChart['vol']
  // 장중엔 오늘 일봉이 하나 더 붙어 같은 날짜가 둘 오는 일이 있다 — 날짜마다 마지막 값만(차트 끝에 같은 날 점이 겹치지 않게)
  ;(res.timestamp ?? []).forEach((_, i) => {
    const c = pos(closes[i]), d = candleDay(res, i)
    if (c == null || d == null) return
    if (pts.length && pts[pts.length - 1][0] === d) pts[pts.length - 1] = [d, c]
    else pts.push([d, c])
    const v = pos(vols[i])
    vol = v == null ? undefined : { day: d, value: v }
  })
  if (pts.length < 2) return null
  const name = typeof meta.longName === 'string' ? meta.longName : typeof meta.shortName === 'string' ? meta.shortName : undefined
  const asOf = typeof meta.regularMarketTime === 'number' ? new Date(meta.regularMarketTime * 1000).toISOString() : undefined
  const reg = (meta.currentTradingPeriod as { regular?: { start?: unknown; end?: unknown } } | undefined)?.regular
  const session = typeof reg?.start === 'number' && typeof reg?.end === 'number' ? { start: reg.start * 1000, end: reg.end * 1000 } : undefined
  return { pts, ...p, name, asOf, ...(vol ? { vol } : {}), ...(session ? { session } : {}) }
}

const SERIES_KEY = 'econStockSeries_v1'
/** 종목 1년 일봉(국내 .KS 다음 .KQ). 받은 것은 sessionStorage 에 10분(보유 시세와 같은 방식). 못 받으면 null. */
export async function stockSeries(code: string, kr: boolean, now = Date.now()): Promise<StockChart | null> {
  let cache: Record<string, StockChart & { t: number }> = {}
  try { cache = JSON.parse(sessionStorage.getItem(SERIES_KEY) || '{}') || {} } catch { /* 없는 것으로 */ }
  const c = cache[code]
  if (c && now - c.t < TTL_MS && c.pts?.length) return c
  for (const sym of yahooSymbols({ symbol: code, market: kr ? 'KR' : 'US' })) {
    try {
      const r = await fetch(chartUrl(sym, '1y'), { signal: AbortSignal.timeout(8_000) })
      const s = r.ok ? parseSeries(await r.json(), KR_EXCHANGE[sym.slice(-3)]) : null
      if (!s) continue
      // 지난 저장본은 버리고 이번 것만 더한다(탭 안에서 본 종목 수만큼만 남는다)
      const keep = Object.fromEntries(Object.entries(cache).filter(([, v]) => now - v.t < TTL_MS))
      try { sessionStorage.setItem(SERIES_KEY, JSON.stringify({ ...keep, [code]: { t: now, ...s } })) } catch { /* 못 두면 다음에 다시 받는다 */ }
      return s
    } catch { /* 다음 후보 */ }
  }
  return null
}
