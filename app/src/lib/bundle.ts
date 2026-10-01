// 묶음 로더 — 화면은 묶음(bundles/<이름>.json)만 읽는다. 데이터 층은 손대지 않는다.
// 주소 기준: 이 앱은 사이트의 next/ 아래에 있으므로 자료는 한 단계 위에 있다.
//   배포  /economic-site/next/ → /economic-site/data.json · /economic-site/bundles/
//   개발  /next/              → /data.json · /bundles/   (vite.config 의 개발 서버가 저장소 루트에서 내준다)
import { changeFromPct } from './format'

const ROOT = new URL('../', document.baseURI)

async function fetchJson<T>(rel: string): Promise<T> {
  const r = await fetch(new URL(rel, ROOT), { cache: 'no-cache' })
  if (!r.ok) throw new Error(`${rel}: HTTP ${r.status}`)
  return r.json() as Promise<T>
}

export function loadBundle<T = unknown>(name: string): Promise<T> {
  if (!/^[\w-]+$/.test(name)) return Promise.reject(new Error(`묶음 이름이 올바르지 않음: ${name}`))
  return fetchJson<T>(`bundles/${name}.json`)
}

/**
 * 홈 지표 띠 한 칸 — bundles/home.json 의 strip[] 모양(scripts/build_bundles.py 가 정한다).
 * value·change 는 원래 단위, changePct 는 %. asOf 는 ISO 시각 또는 YYYY-MM-DD.
 * state 는 묶음이 판정한 신선도(live·prev·stale·kept·missing) — data.json 폴백에는 없다.
 */
export type StripItem = {
  id: string
  label: string
  short?: string
  decimals: number
  value: number | null
  change: number | null
  changePct: number | null
  asOf: string
  state?: string
}
export type HomeBundle = { asOf: string; todayLine: { pc: string; mobile: string } | null; strip: StripItem[] }

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
