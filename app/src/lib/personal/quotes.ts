// 보유 종목 시세 — 묶음(data.ts loadMarketData 의 home·market-domestic)에 있으면 그것, 없으면 Worker 프록시로 Yahoo 일봉.
// 현행 화면(js/app1.js fetchYahooQuote)과 같은 경로: `<Worker>/?url=` + query1.finance.yahoo.com/v8/finance/chart/<심볼>?range=5d&interval=1d.
// market-global 묶음은 지수뿐이라(종목 칸 없음) 여기서 따로 보지 않는다.
// 받은 값은 sessionStorage 에 10분 둔다(탭을 닫으면 사라진다). 한 번에 4개까지 동시에. 못 받은 종목은 「시세 없음」 그대로 둔다.
// 보유 목록을 읽는 화면(내 자산 Holdings — PinGate 안)에서만 부른다.
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(calc.ts 와 같은 규칙). node --test 로 바로 돌린다(quotes.test.ts).
import type { Holding, Quote } from './calc'
import { WORKER } from './remote.ts'

const CACHE_KEY = 'econHoldQuotes_v1'
const TTL_MS = 10 * 60_000
const PARALLEL = 4

/** 보유 한 줄 → Yahoo 심볼 후보(앞에서부터 시도). 국내 6자리 = .KS 다음 .KQ, 미국 = 현행 화면이 적어 둔 yahoo 칸 또는 티커 그대로. */
export function yahooSymbols(h: Pick<Holding, 'symbol' | 'market'> & { yahoo?: unknown }): string[] {
  if (h.market === 'KR') return /^[0-9A-Z]{6}$/.test(h.symbol) ? [`${h.symbol}.KS`, `${h.symbol}.KQ`] : []
  const y = typeof h.yahoo === 'string' && h.yahoo.trim() ? h.yahoo.trim() : h.symbol
  return y ? [y] : []
}

export const chartUrl = (sym: string) =>
  `${WORKER}/?url=${encodeURIComponent(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=5d&interval=1d`)}`

type Chart = { chart?: { result?: { meta?: Record<string, unknown>; indicators?: { quote?: { close?: (number | null)[] }[] } }[] | null } }
const pos = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null)

/**
 * 일봉 응답 → 현재가 · 전일 종가. 현재가 = meta.regularMarketPrice(없으면 마지막 일봉 종가).
 * 전일 종가 = 마지막 일봉 「바로 앞」 일봉들 중 가장 최근의 확정 종가(현행 closes[-2] 규칙).
 * 빈칸(null)을 먼저 빼고 끝에서 두 번째를 고르면 안 된다 — 미국 종목은 마지막 일봉 종가가 null 로 오는 일이 있어
 * (2026-10-02 AAPL 실측) 그러면 하루 더 앞 종가를 전일로 잡는다. 앞 일봉이 없을 때만 meta.chartPreviousClose.
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
  for (let i = closes.length - 2; i >= 0 && prev == null; i--) prev = pos(closes[i])
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

async function fetchOne(h: Holding): Promise<{ price: number; prev: number | null } | null> {
  for (const sym of yahooSymbols(h)) {
    try {
      const r = await fetch(chartUrl(sym), { signal: AbortSignal.timeout(8_000) })
      const p = r.ok ? parseChart(await r.json(), KR_EXCHANGE[sym.slice(-3)]) : null
      if (p) return p
    } catch { /* 다음 후보 */ }
  }
  return null
}

/**
 * 보유 종목 시세 지도(키 = symbol, calc.ts evaluate 가 읽는 모양). have(묶음 시세)를 그대로 담고,
 * 묶음에 없는 보유 종목만 10분 저장본 → Yahoo 순서로 채운다.
 */
export async function holdingQuotes(items: Holding[], have: Map<string, Quote>, now = Date.now()): Promise<Map<string, Quote>> {
  const out = new Map(have)
  const cache = readCache()
  const need: Holding[] = []
  const seen = new Set<string>()
  for (const h of items) {
    const k = `${h.market}:${h.symbol}`
    if (out.has(h.symbol) || seen.has(k)) continue
    seen.add(k)
    const c = cache[k]
    if (c && now - c.t < TTL_MS && pos(c.price)) out.set(h.symbol, toQuote(c))
    else need.push(h)
  }
  let i = 0
  const worker = async () => {
    while (i < need.length) {
      const h = need[i++]
      const p = await fetchOne(h)
      if (!p) continue
      cache[`${h.market}:${h.symbol}`] = { t: now, ...p }
      out.set(h.symbol, toQuote(p))
    }
  }
  await Promise.all(Array.from({ length: Math.min(PARALLEL, need.length) }, worker))
  if (need.length) writeCache(cache)
  return out
}
