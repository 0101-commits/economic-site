// 상세 화면(/i/:id) 읽기 도우미 — 종목 판정 · 묶음의 종목 행 모으기 · 메르 글 언급 · 겹침(첫 날 = 100).
// 묶음 · 파일을 직접 받지 않는다(받는 쪽은 Detail · 검색). 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다 — node --test 로 바로 돌린다(detail.test.ts).
import { safeHref, type PeriodKey, type Pt } from './format.ts'
import { watchKind } from './personal/remote.ts'

/** 국내 종목 코드인가(숫자로 시작하는 6자리). */
export const isKrStock = (id: string) => /^\d[0-9A-Z]{5}$/.test(id)
/** 종목 id 인가: 국내 코드 또는 미국 티커 — 관심 목록과 같은 판정(remote.ts watchKind). 지표 사전 id 는 모두 소문자로 시작한다. */
export const isStockId = (id: string) => watchKind(id) === 'stock'

/** 묶음의 종목 한 줄. asOf · state 는 그 행이 든 위쪽 칸의 것(없으면 없음). */
export type StockRow = { code: string; name: string; short?: string; market?: string | null; price: number | null; chgPct: number | null; asOf?: string | null; state?: string; amount?: number | null; volume?: number | null }

/**
 * 묶음 아무 깊이의 종목 행(code · name 이 글자인 칸)을 코드별로 모은다. 위쪽 칸의 asOf · state 를 물려받는다.
 * 먼저 본 행이 이기고, 값(price)이 없는 행만 뒤에 온 값 있는 행에 자리를 내준다 — roots 차례가 곧 우선순위다.
 */
export function stockRows(roots: unknown[]): Map<string, StockRow> {
  const out = new Map<string, StockRow>()
  const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
  const walk = (o: unknown, asOf: string | null | undefined, state: string | undefined): void => {
    if (!o || typeof o !== 'object') return
    if (Array.isArray(o)) { o.forEach(x => walk(x, asOf, state)); return }
    const r = o as Record<string, unknown>
    if (typeof r.asOf === 'string') { asOf = r.asOf; state = typeof r.state === 'string' ? r.state : state }
    if (typeof r.code === 'string' && typeof r.name === 'string' && r.name) {
      const price = num(r.price), old = out.get(r.code)
      if (!old || (old.price == null && price != null)) {
        const amount = num(r.amount) ?? old?.amount, volume = num(r.volume) ?? old?.volume
        out.set(r.code, { code: r.code, name: r.name, short: typeof r.short === 'string' ? r.short : undefined, market: typeof r.market === 'string' ? r.market : null, price, chgPct: num(r.chgPct), asOf, state, ...(amount != null && { amount }), ...(volume != null && { volume }) })
      } else {
        // 거래대금 · 거래량은 목록마다 한쪽만 있다(거래대금 상위 = amount, 상승 · 하락 = volume) — 먼저 본 행에 없는 칸만 채운다
        if (old.amount == null && num(r.amount) != null) old.amount = num(r.amount)
        if (old.volume == null && num(r.volume) != null) old.volume = num(r.volume)
      }
    }
    Object.values(r).forEach(x => walk(x, asOf, state))
  }
  roots.forEach(x => walk(x, undefined, undefined))
  return out
}

export type Post = { title: string; url: string; date?: string; fullText?: string }
export type Mention = { title: string; href: string | null; date?: string; snip?: [string, string, string] }
const SNIP = 40

/** 메르 글 중 제목 · 전문에 names 가운데 하나가 든 글 n 편(글 차례 = 최신순). 전문에서 찾으면 일치한 곳 앞뒤 40자. 두 글자 미만 이름은 보지 않는다. */
export function merMentions(posts: Post[], names: (string | undefined)[], n = 3): Mention[] {
  const keys = [...new Set(names.filter((x): x is string => !!x && x.length >= 2))]
  const out: Mention[] = []
  for (const p of posts) {
    if (out.length >= n || !keys.length) break
    const ft = p.fullText ?? ''
    const k = keys.find(x => ft.includes(x))
    if (!k && !keys.some(x => p.title.includes(x))) continue
    const i = k ? ft.indexOf(k) : -1, e = i + (k?.length ?? 0)
    out.push({
      title: p.title, href: safeHref(p.url), date: p.date,
      snip: i < 0 ? undefined : [`${i > SNIP ? '…' : ''}${ft.slice(Math.max(0, i - SNIP), i)}`, ft.slice(i, e), `${ft.slice(e, e + SNIP)}${e + SNIP < ft.length ? '…' : ''}`],
    })
  }
  return out
}

type Periods = Partial<Record<PeriodKey, Pt[]>>
/**
 * 겹침(C10): 기간마다 주 선과 비교 선을 그 기간 첫 점 = 100 으로 바꾼다. 비교 선은 주 선의 그 기간 날짜 범위 안 점만 쓴다.
 * 첫 값이 0 이하인 선은 지수로 못 바꾸므로 비운다(차트가 그 선을 그리지 않는다).
 * ponytail: 날짜는 앞 10자 글자 비교 — 월간('YYYY-MM') 주 선에 일간 비교 선이면 마지막 달 안의 날은 빠진다. 섞어 쓸 일이 생기면 달 끝으로 맞춘다.
 */
export function overlay(main: Periods, other: Pt[]): { main: Periods; other: Periods } {
  const idx = (l: Pt[]): Pt[] => (l.length && l[0][1] > 0 ? l.map(([d, v]): Pt => [d, (v / l[0][1]) * 100]) : [])
  const a: Periods = {}, b: Periods = {}
  for (const k of Object.keys(main) as PeriodKey[]) {
    const l = main[k]
    if (!l?.length) continue
    const lo = l[0][0].slice(0, 10), hi = l[l.length - 1][0].slice(0, 10)
    a[k] = idx(l)
    b[k] = idx(other.filter(([d]) => d.slice(0, 10) >= lo && d.slice(0, 10) <= hi))
  }
  return { main: a, other: b }
}
