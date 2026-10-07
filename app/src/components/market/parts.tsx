// 시장 화면 공용 조각 — 큰 차트 · 등락 글자 · 수익률 곡선 · 일정 목록 · 격자 칸.
// 공유 부품(components/ui·charts·panels)은 고치지 않고 그 위에 얹는다.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { loadIndicator, shownUnit, type MarketState, type Sched, type StripItem } from '../../lib/bundle'
import { changeDir, fmtChange, fmtNumber, fmtPct, range52, scaled, scaledPts, shortDate, slicePeriods, PERIODS, type PeriodKey, type Pt } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { countUse } from '../../lib/usage'
import { NumBlock } from '../ui'
import { LineChart, Range52 } from '../charts'
import { More, Panel } from '../panels'
import { spans } from './calc'

/** 자산군 본문이 받는 것: 묶음 하나 + 고른 띠 지표(s). */
export type BodyProps<B> = { b: B; selId: string; setS: (id: string) => void }
/** 시장 묶음 공통 겉모양. views 는 자산군마다 다르다. */
export type MarketBundle = { market?: MarketState; strip: StripItem[]; views?: unknown }

export const DIR_TEXT = { up: 'text-up', down: 'text-down', flat: 'text-ink-2' } as const

/** 등락 한 칸: 등락률이 있으면 %, 없으면(금리 등) 변화량. */
export function ChangeText({ chg, pct, decimals = 2, suffix = '' }: { chg?: number | null; pct?: number | null; decimals?: number; suffix?: string }) {
  const dir = changeDir(pct ?? chg, pct != null ? 2 : decimals)
  const text = pct != null ? fmtPct(pct) : chg == null ? '—' : `${fmtChange(chg, null, decimals)}${suffix}`
  return <span className={`num text-12 ${DIR_TEXT[dir]}`}>{text}</span>
}

export const Empty = ({ children }: { children: ReactNode }) => <p className="m-0 text-13 text-ink-3">{children}</p>

export function MoreLink({ to, children }: { to: string; children: ReactNode }) {
  return <Link to={to} className="inline-flex items-center text-12 text-ink-2 no-underline hover:text-ink-1">{children}<ChevronRight size={14} aria-hidden /></Link>
}

/** 띠 + 보기 칸을 id 로 합친다. 같은 id 면 뒤 목록 칸(시계열 있음)을 앞 칸(작은 차트·이유) 위에 덮는다. */
export function poolOf(...lists: (StripItem[] | undefined)[]): Map<string, StripItem> {
  const m = new Map<string, StripItem>()
  for (const l of lists) for (const it of l || []) m.set(it.id, { ...m.get(it.id), ...it })
  return m
}

// 칸에 시계열이 없을 때 지표 사전으로 한 번 찾는다(국내 띠의 코스피처럼 다른 묶음에 시계열이 있는 칸). 화면을 옮겨도 다시 받지 않는다.
const borrowed = new Map<string, Promise<Pt[]>>()
function borrow(id: string): Promise<Pt[]> {
  let p = borrowed.get(id)
  if (!p) { p = loadIndicator(id).then(r => r.series ?? [], () => []); borrowed.set(id, p) }
  return p
}

/** 칸의 시계열(원본 단위). 칸에 있으면 그것, 없으면 빌려 온다 — 받는 동안 null. */
function useSeries(item?: StripItem): Pt[] | null {
  const own = item?.series?.length ? item.series : undefined
  const [got, setGot] = useState<Record<string, Pt[]>>({})
  useEffect(() => {
    if (!item || own || item.id in got) return
    const id = item.id
    borrow(id).then(s => setGot(m => ({ ...m, [id]: s })))
  }, [item?.id, own])
  if (!item) return []
  return own ?? got[item.id] ?? null
}

/**
 * 칸 하나를 기간 칩 시계열로(화면 단위). 월별처럼 성긴 시계열의 칩 고르기는 format.ts slicePeriods 가 한다(1년 · 2년 · 전체).
 * 시계열이 없으면 띠의 최근 7거래일(날짜 없음)이라도 1주로.
 */
export function periodsOf(item: StripItem, series: Pt[] | null): Partial<Record<PeriodKey, Pt[]>> {
  if (series?.length) return slicePeriods(scaledPts(series, item.scale))
  if (series && item.spark && item.spark.length >= 2) return { '1w': scaledPts(item.spark.map((x): Pt => ['', x]), item.scale) }
  return {}
}

/**
 * 큰 차트: 고른 칸의 값·등락 + 52주 위치 + 기간 칩 선 차트(기간은 주소 p). 홈 큰 차트와 같은 모양이다.
 * 기간 칩은 일별이면 1주·3달·1년, 월별(거시·부동산)이면 1년·2년(24개월)이다.
 */
export function BigChart({ item, className = '' }: { item?: StripItem; className?: string }) {
  const [p, setP] = useViewParam<PeriodKey>('p', '3m', PERIODS.map(o => o.key))
  const series = useSeries(item)
  const periods = useMemo(() => (item ? periodsOf(item, series) : {}), [item, series])
  if (!item) return <Panel className={className} title="차트"><Empty>고를 지표가 없습니다.</Empty></Panel>
  const v = scaled(item.value, item.scale), c = scaled(item.change, item.scale)
  const r52 = series?.length ? range52(scaledPts(series, item.scale)) : null
  return (
    <Panel className={className} title={item.short || item.label} asOf={item.asOf} state={item.state} liveUntil={item.liveUntil}
      tools={<MoreLink to={`/i/${item.id}`}>자세히</MoreLink>}>
      <div className="mb-2 flex flex-wrap items-end gap-x-6 gap-y-2">
        <NumBlock value={v} decimals={item.decimals} chg={c} pct={item.changePct} size="L" unit={shownUnit(item)} />
        {r52 && <div className="w-64 max-w-full"><Range52 low={r52.low} high={r52.high} value={v} decimals={item.decimals} /></div>}
      </div>
      <LineChart key={item.id} label={item.label} periods={periods} period={p} onPeriod={setP} decimals={item.decimals}
        base={v != null && c != null ? { value: v - c, label: '전일' } : null}
        empty={series === null ? '불러오는 중' : '시계열 준비 중'} />
    </Panel>
  )
}

/** 격자 칸 클래스(Tailwind 가 찾을 수 있게 통째로 적는다). */
const SPAN: Record<number, string> = { 4: 'pc:col-span-4', 6: 'pc:col-span-6', 12: 'pc:col-span-12' }

/** 격자 칸 하나: (패널에 덧붙일 클래스, 큰 차트 옆 넓은 둘째 칸인지) → 패널. 칸 폭은 MarketGrid 가 감싼 칸이 정한다. */
export type Block = (cls: string, primary: boolean) => ReactNode

/**
 * 시장 격자: 첫 칸 = 큰 차트(또는 그 자리 부품), 그다음은 blocks 순서 그대로(보기를 골라도 차례가 바뀌지 않는다 — 목차가 그 칸으로 데려간다).
 * blocks 는 [패널 고유 키, 칸 → 패널]. 키는 목차가 찾는 표식(data-toc)이다. PC 12열, 모바일 1열 같은 순서.
 */
export function MarketGrid({ blocks, per = 3 }: { blocks: [string, Block][]; per?: 2 | 3 }) {
  const sp = spans(blocks.length, per)
  return (
    <div className="grid grid-cols-1 pc:grid-cols-12 gap-4 items-start">
      {blocks.map(([k, f], i) => <div key={k} data-toc={k} className={`${SPAN[sp[i]]} scroll-mt-14`}>{f('', i === 1)}</div>)}
    </div>
  )
}

/** 고르기 줄(범위 · 주제 따위) 누르기를 사용 기록에 센다 — 줄 이름과 칸 이름만(lib/usage.ts). */
export const counted = <K extends string>(where: string, opts: readonly { key: K; label: string }[], set: (k: K) => void) =>
  (k: K) => { countUse('views', `${where} · ${opts.find(o => o.key === k)?.label ?? k}`); set(k) }

const smooth = (): ScrollBehavior => (matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth')
/** 그 칸으로 간다. 접어 둔 패널이면 먼저 편다 — details 를 열면 Panel 의 onToggle 이 상태 · 접기 기억을 같이 바꾼다. */
const goTo = (to: string, behavior = smooth()) => {
  const el = document.querySelector(`[data-toc="${to}"]`)
  el?.querySelectorAll<HTMLDetailsElement>('details[data-panel-fold]:not([open])').forEach(d => { d.open = true })
  el?.scrollIntoView({ behavior, block: 'start' })
}

/**
 * 목차: 칩을 누르면 그 격자 칸으로 부드럽게 내려간다(주소 v 에 남겨 공유 · 새로 고침이 같은 자리로 온다).
 * 화면에 보이는 칸의 칩은 테두리로 표시한다(여럿일 수 있다). 화면 위에 붙는다 — 부모가 화면 세로 줄이어야 끝까지 붙는다.
 * items[].to = 칩이 가리키는 칸 키(MarketGrid blocks 의 키, 없으면 칩 키). 여러 칩이 한 칸을 가리키면(수급 일별·주별·월별)
 * onPick 이 그 칸의 내용을 바꾸고 on 이 지금 내용인 칩만 고른다. 주소에 v 가 있으면 첫 진입 때 한 번 그 칸으로 간다.
 */
export function Toc<K extends string>({ where, items, onPick, on }: {
  where: string
  items: readonly { key: K; label: string; to?: string }[]
  onPick: (k: K) => void
  on?: (k: K) => boolean
}) {
  const [params] = useSearchParams()
  const bar = useRef<HTMLElement>(null)
  const [seen, setSeen] = useState<ReadonlySet<string>>(new Set())
  const target = (k: K) => items.find(o => o.key === k)?.to ?? k
  const targets = items.map(o => o.to ?? o.key).join(',')
  useEffect(() => {
    // 목차 띠 아래로 조금이라도 보이는 칸
    const io = new IntersectionObserver(es => setSeen(prev => {
      const next = new Set(prev)
      for (const e of es) { const k = (e.target as HTMLElement).dataset.toc ?? ''; if (e.isIntersecting) next.add(k); else next.delete(k) }
      return next
    }), { rootMargin: `-${bar.current?.offsetHeight ?? 0}px 0px 0px 0px` })
    document.querySelectorAll('[data-toc]').forEach(el => io.observe(el))
    return () => io.disconnect()
  }, [targets])
  useEffect(() => {
    const v = params.get('v') as K | null
    // 단번에 간다 — 부드럽게 가는 동안 위 칸(큰 차트 시계열)이 자라면 자리가 어긋나고, 단번에 간 뒤엔 브라우저 스크롤 고정이 자리를 지킨다
    if (v && items.some(o => o.key === v)) goTo(target(v), 'auto')
  }, [])   // 첫 진입 때 한 번만 — 그 뒤 v 는 칩을 누를 때 바뀐다
  const marked = (k: K) => seen.has(target(k)) && (on?.(k) ?? true)
  const first = items.find(o => marked(o.key))?.key
  // 좁은 화면: 표시된 첫 칩이 목차 줄 안에 보이게 줄만 가로로 민다
  useEffect(() => {
    const el = bar.current, b = el?.querySelector<HTMLElement>('[aria-current=true]')
    if (el && b && el.scrollWidth > el.clientWidth) el.scrollTo({ left: b.offsetLeft - 8 })
  }, [first])
  return (
    <nav ref={bar} aria-label="목차" className="sticky top-[env(safe-area-inset-top,0px)] z-10 py-2 -my-2 bg-bg flex flex-nowrap gap-1 overflow-x-auto [scrollbar-width:thin]">
      {items.map(o => {
        const m = marked(o.key)
        return (
          <button key={o.key} type="button" aria-current={m || undefined}
            onClick={() => { countUse('views', `${where} 목차 · ${o.label}`); onPick(o.key); goTo(target(o.key)) }}
            className={`shrink-0 h-8 px-3 rounded-btn text-13 whitespace-nowrap border bg-card cursor-pointer ${m ? 'border-ink-1 text-ink-1 font-bold' : 'border-line text-ink-2 hover:text-ink-1'}`}>
            {o.label}
          </button>
        )
      })}
    </nav>
  )
}

type Ev = Sched & { prev?: unknown; fore?: unknown; act?: unknown }
/** 경제 일정 목록(홈 일정과 같은 모양). 이전·예측·실제가 있으면 오른쪽에 붙인다. 길면 「더 보기」. tag = 이름 앞 꼬리표(거시의 나라). */
export function EventList({ events, today, tag }: { events: Ev[]; today?: string; tag?: (e: Ev) => ReactNode }) {
  if (!events.length) return <Empty>다가오는 일정이 없습니다.</Empty>
  const s = (x: unknown) => (x == null || x === '' ? null : String(x))
  return <More rows={events} name="일정">{shown => (
    <ul className="m-0 p-0 list-none">
      {shown.map((e, i) => {
        const nums = [['이전', s(e.prev)], ['예측', s(e.fore)], ['실제', s(e.act)]].filter(([, x]) => x)
        return (
          <li key={`${e.date}-${e.name}-${i}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5 border-b border-line last:border-b-0">
            <span className="w-[5.5rem] shrink-0 num text-12 text-ink-3">{`${e.date === today ? '오늘' : shortDate(e.date)}${e.time ? ` ${e.time}` : ''}`}</span>
            <span className="flex-1 min-w-[8rem] text-13 text-ink-1">{tag && <span className="mr-1.5 inline-flex align-middle">{tag(e)}</span>}{e.name}{e.approx ? <span className="text-ink-3"> (추정)</span> : null}</span>
            {!!e.stars && <span className="shrink-0 text-11 text-ink-3" aria-label={`중요도 ${e.stars}`}>{'★'.repeat(e.stars)}</span>}
            {nums.length > 0 && (
              <span className="basis-full pl-[6.25rem] text-11 text-ink-3">
                {nums.map(([k, x]) => <span key={k} className="mr-3">{k} <span className="num text-ink-2">{x}</span></span>)}
              </span>
            )}
          </li>
        )
      })}
    </ul>
  )}</More>
}

export type Curve = { label?: string | null; tenors: string[]; asOf?: string; state?: string; current: (number | null)[]; prev_month?: (number | null)[]; prev_3m?: (number | null)[]; prev_6m?: (number | null)[]; prev_1y?: (number | null)[] }

/**
 * 수익률 곡선: 만기를 가로(같은 간격)로, 현재(검정) · 1년 전(회색 점선). 빈 만기는 건너뛰고 잇는다.
 * 선은 늘어나도 굵기가 같게(non-scaling-stroke), 글자는 SVG 밖 HTML 로 둔다.
 */
export function CurveChart({ curve, label }: { curve: Curve; label: string }) {
  const lines = [
    { name: '현재', vals: curve.current, cls: 'stroke-ink-1', dash: undefined },
    { name: '1년 전', vals: curve.prev_1y ?? [], cls: 'stroke-ink-3', dash: '4 3' },
  ]
  const all = lines.flatMap(l => l.vals.filter((x): x is number => x != null))
  if (all.length < 2) return null
  let lo = Math.min(...all), hi = Math.max(...all)
  if (!(hi > lo)) { hi = lo + 1; lo -= 1 }
  const n = curve.tenors.length, W = 100, H = 40
  const path = (vals: (number | null)[]) => vals.map((v, i) => (v == null ? '' : `${i / (n - 1) * W},${H - ((v - lo) / (hi - lo)) * H}`)).filter(Boolean).join(' ')
  return (
    <figure className="m-0" aria-label={label}>
      <div className="flex gap-2">
        <div className="flex flex-col justify-between text-11 text-ink-3 num"><span>{fmtNumber(hi, 2)}</span><span>{fmtNumber(lo, 2)}</span></div>
        <svg viewBox={`0 -2 ${W} ${H + 4}`} preserveAspectRatio="none" className="block flex-1 min-w-0 h-20" aria-hidden>
          {lines.map(l => l.vals.some(x => x != null) && (
            <polyline key={l.name} points={path(l.vals)} fill="none" className={l.cls} strokeWidth={1.5} strokeDasharray={l.dash} vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
      </div>
      <div className="flex justify-between pl-9 mt-1 text-11 text-ink-3 num">{curve.tenors.map(t => <span key={t}>{t}</span>)}</div>
      <figcaption className="mt-1 flex gap-3 text-11 text-ink-3">
        <span><span aria-hidden className="inline-block w-4 h-px align-middle bg-ink-1 mr-1" />현재</span>
        <span><span aria-hidden className="inline-block w-4 align-middle border-t border-dashed border-ink-3 mr-1" />1년 전</span>
      </figcaption>
    </figure>
  )
}

/** 만기별 표: 만기 | 현재 | 전월 | 1년 전. 세 값이 다 빈 만기는 뺀다. */
export function CurveTable({ curve }: { curve: Curve }) {
  const rows = curve.tenors.map((t, i) => [t, curve.current[i], curve.prev_month?.[i], curve.prev_1y?.[i]] as const)
    .filter(([, ...v]) => v.some(x => x != null))
  return (
    <div className="table-box">
      <table className="w-full border-collapse text-13">
        <thead><tr className="h-8 border-b border-line text-12 text-ink-3">
          <th scope="col" className="px-2 font-normal text-left">만기</th>
          {['현재', '전월', '1년 전'].map(h => <th key={h} scope="col" className="px-2 font-normal text-right">{h}</th>)}
        </tr></thead>
        <tbody>
          {rows.map(([t, ...v]) => (
            <tr key={t} className="h-8 border-b border-line last:border-b-0">
              <th scope="row" className="px-2 font-normal text-left text-ink-2">{t}</th>
              {v.map((x, i) => <td key={i} className={`px-2 text-right num ${i ? 'text-ink-2' : 'text-ink-1 font-bold'}`}>{x == null ? '—' : `${fmtNumber(x, 2)}%`}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
