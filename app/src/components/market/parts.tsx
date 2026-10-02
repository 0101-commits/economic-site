// 시장 화면 공용 조각 — 큰 차트 · 등락 글자 · 수익률 곡선 · 일정 목록 · 렌즈 자리 · 격자 칸.
// 공유 부품(components/ui·charts·panels)은 고치지 않고 그 위에 얹는다.
import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { loadIndicator, shownUnit, type MarketState, type Sched, type StripItem } from '../../lib/bundle'
import { changeDir, fmtChange, fmtNumber, fmtPct, range52, scaled, scaledPts, shortDate, slicePeriods, PERIODS, type PeriodKey, type Pt } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { NumBlock } from '../ui'
import { LineChart, Range52 } from '../charts'
import { Panel } from '../panels'
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

/**
 * 시장 격자: 첫 칸 = 큰 차트(또는 그 자리 부품), 둘째 = 고른 보기 패널, 나머지는 원래 순서.
 * blocks 는 (칸 클래스, 첫 보기인지) → 패널. PC 12열, 모바일 1열 같은 순서. 맨 끝은 렌즈 자리.
 */
export function MarketGrid({ blocks, per = 3 }: { blocks: ((cls: string, primary: boolean) => ReactNode)[]; per?: 2 | 3 }) {
  const sp = spans(blocks.length, per)
  return (
    <div className="grid grid-cols-1 pc:grid-cols-12 gap-4 items-start">
      {blocks.map((f, i) => <Fragment key={i}>{f(SPAN[sp[i]], i === 1)}</Fragment>)}
      <Panel className="pc:col-span-12" title="렌즈" fold="always">
        <MoreLink to="/lens">렌즈 전체 보기</MoreLink>
      </Panel>
    </div>
  )
}

/** 보기 v 를 맨 앞으로, 나머지는 원래 순서. */
export const arrange = <K extends string>(first: K, order: readonly K[]): K[] => [first, ...order.filter(k => k !== first)]

/** 경제 일정 목록(홈 일정과 같은 모양). 이전·예측·실제가 있으면 오른쪽에 붙인다. */
export function EventList({ events, today }: { events: (Sched & { prev?: unknown; fore?: unknown; act?: unknown })[]; today?: string }) {
  if (!events.length) return <Empty>다가오는 일정이 없습니다.</Empty>
  const s = (x: unknown) => (x == null || x === '' ? null : String(x))
  return (
    <ul className="m-0 p-0 list-none">
      {events.map((e, i) => {
        const nums = [['이전', s(e.prev)], ['예측', s(e.fore)], ['실제', s(e.act)]].filter(([, x]) => x)
        return (
          <li key={`${e.date}-${e.name}-${i}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5 border-b border-line last:border-b-0">
            <span className="w-[5.5rem] shrink-0 num text-12 text-ink-3">{`${e.date === today ? '오늘' : shortDate(e.date)}${e.time ? ` ${e.time}` : ''}`}</span>
            <span className="flex-1 min-w-[8rem] text-13 text-ink-1">{e.name}{e.approx ? <span className="text-ink-3"> (추정)</span> : null}</span>
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
  )
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
