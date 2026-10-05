// 내 자산·알림·검색이 읽는 공개 자료. 묶음(bundles/)은 bundle.ts 로, 사이트 루트 파일(alerts_state.json·merblog.json)은 여기서.
import { findItem, loadBundle, loadHome, ROOT, type HomeBundle, type StripItem } from '../bundle'
import type { Fx, Quote } from './calc'

const rootFiles = new Map<string, Promise<unknown>>()

/** 사이트 루트의 공개 파일 하나(배포 허용 목록 scripts/collect_site.mjs 에 있는 것만). 한 번 받은 것은 다시 받지 않는다. */
export function loadRootJson<T>(name: 'alerts_state.json' | 'merblog.json' | 'events/latest.json'): Promise<T> {
  let p = rootFiles.get(name)
  if (!p) {
    p = fetch(new URL(name, ROOT), { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`); return r.json() })
    p.catch(() => rootFiles.delete(name))
    rootFiles.set(name, p)
  }
  return p as Promise<T>
}

/** 묶음 아무 깊이의 종목 칸(code·price·chgPct)을 모은다. 먼저 본 것이 이긴다(홈 → 국내 시장 순). */
function collectStocks(root: unknown, out: Map<string, Quote>) {
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

export type HaltEvent = { id: string; type: string; market?: string; stage?: number; direction?: string; reason?: string; triggeredAt?: string }
export type MarketData = {
  home: HomeBundle | null
  quotes: Map<string, Quote>
  fx: Fx
  fxItem?: StripItem
  quotesAsOf?: string
  nps: { asOf?: string; allocation: { asset: string; pct: number }[]; source?: string } | null
  gainers: boolean
  losers: boolean
  halts: HaltEvent[]
}

/**
 * 시세는 묶음에 있는 것만 — 거래대금 상위 20 · 국내 상승·하락·ETF 표. 그 밖의 종목은 「시세 없음」(지어내지 않는다).
 * 달러원은 홈 띠(없으면 환율 묶음)의 usdkrw: 전일 = 지금 − 변화량.
 */
export async function loadMarketData(): Promise<MarketData> {
  const [home, dom, flows, fxb] = await Promise.all([
    loadHome().catch(() => null),
    loadBundle<{ views?: Record<string, unknown> }>('market-domestic').catch(() => null),
    loadBundle<{ views?: { nps?: MarketData['nps'] } }>('market-flows').catch(() => null),
    loadBundle('market-fxrates').catch(() => null),
  ])
  const quotes = new Map<string, Quote>()
  collectStocks(home?.topAmount, quotes)
  collectStocks(dom?.views, quotes)
  const it = (home && findItem(home.strip, 'usdkrw')) || (fxb ? findItem(fxb, 'usdkrw') : undefined)
  const fx: Fx = it?.value ? { now: it.value, prev: it.change != null ? it.value - it.change : null } : null
  const views = (dom?.views || {}) as Record<string, Record<string, unknown[]> | undefined>
  const any = (v?: Record<string, unknown[]>) => !!v && Object.values(v).some(a => Array.isArray(a) && a.length > 0)
  const halts = (dom?.views?.halts || {}) as { active?: HaltEvent[]; recent?: HaltEvent[] }
  return {
    home, quotes, fx, fxItem: it, quotesAsOf: home?.topAmount?.asOf,
    nps: flows?.views?.nps?.allocation?.length ? flows.views.nps : null,
    gainers: any(views.gainers), losers: any(views.losers),
    halts: [...(halts.active || []), ...(halts.recent || [])],
  }
}
