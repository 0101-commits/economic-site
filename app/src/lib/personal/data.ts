// 내 자산·알림·검색이 읽는 공개 자료. 묶음(bundles/)은 bundle.ts 로, 사이트 루트 파일(alerts_state.json·merblog.json)은 여기서.
import { findItem, loadBundle, loadHome, ROOT, type HomeBundle, type StripItem } from '../bundle'
import { collectDomestic, collectStocks, type Fx, type Quote } from './calc'
import type { Pt } from '../format'

const rootFiles = new Map<string, Promise<unknown>>()

/** 사이트 루트의 공개 파일 하나(배포 허용 목록 scripts/collect_site.mjs 에 있는 것만). 한 번 받은 것은 다시 받지 않는다.
 *  alerts_config.json 은 배포 목록에 없다(로컬 개발 서버에서만 읽힌다) — 운영에서는 Worker /portfolio 로 읽는다(remote.ts portfolioGet). */
export function loadRootJson<T>(name: 'alerts_state.json' | 'merblog.json' | 'events/latest.json' | 'alerts_config.json'): Promise<T> {
  let p = rootFiles.get(name)
  if (!p) {
    p = fetch(new URL(name, ROOT), { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`); return r.json() })
    p.catch(() => rootFiles.delete(name))
    rootFiles.set(name, p)
  }
  return p as Promise<T>
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
 * 시세는 묶음에 있는 것만 — 홈 거래대금 상위 → 국내 묶음 보기 순(거래대금 · 체결 상위 · 상승·하락 · ETF …, 같은 종목은 먼저 본 것).
 * KRX 순위 4목록(전일 확정값)은 쓰지 않는다 — 거기에만 있는 종목은 Yahoo 시세(quotes.ts)로 간다.
 * 그 밖의 종목은 「시세 없음」(지어내지 않는다).
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
  collectDomestic(dom?.views, quotes)
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

/** 내 자산 「시장 대비」의 지수 둘 — 세계 묶음 views.indices 의 일별 종가 1년(홈 kospiChart 는 3달뿐). 시계열이 없는 지수는 뺀다. */
export async function loadBench(): Promise<{ name: string; pts: Pt[] }[]> {
  const g = await loadBundle('market-global').catch(() => null)
  return ['kospi', 'sp500'].flatMap(id => { const it = findItem(g, id); return it?.series?.length ? [{ name: it.label, pts: it.series }] : [] })
}
