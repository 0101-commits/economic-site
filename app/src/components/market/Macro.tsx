// 시장 › 거시 — 보기 = 주제 6(묶음 topics 키) + 달력, 나라 칩 7(주소 m). 카드를 누르면 그 지표의 24개월 차트(주소 s).
import type { ReactNode } from 'react'
import type { Sched, StripItem } from '../../lib/bundle'
import { fmtNumber, scaled } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { AsOfBadge, SegBar } from '../ui'
import { Panel } from '../panels'
import { BigChart, Empty, EventList, MarketGrid, poolOf, type BodyProps } from './parts'
import { yearAgo, yoySeries } from './calc'

type MacroItem = StripItem & { country?: string; topic?: string; source?: string }
export type MacroBundle = {
  market?: { today?: string }
  strip: MacroItem[]
  views?: { topics?: Record<string, MacroItem[]>; calendar?: (Sched & { prev?: string | null; fore?: string | null; act?: string | null })[] }
}

const VIEWS = [
  { key: 'price', label: '물가' }, { key: 'growth', label: '경기' }, { key: 'labor', label: '고용' }, { key: 'money', label: '금리·통화' },
  { key: 'trade', label: '무역' }, { key: 'demand', label: '소비' }, { key: 'calendar', label: '달력' },
] as const
const COUNTRIES = [
  { key: 'kr', label: '한국' }, { key: 'us', label: '미국' }, { key: 'jp', label: '일본' }, { key: 'eu', label: '유로' },
  { key: 'uk', label: '영국' }, { key: 'de', label: '독일' }, { key: 'cn', label: '중국' },
] as const
type View = typeof VIEWS[number]['key']
type Country = typeof COUNTRIES[number]['key']

/** 거시 카드: 이름 · 기준 달 → 값(+단위) → 전월 · 전년. 누르면 큰 차트. */
function MacroCard({ it, on, onPick }: { it: MacroItem; on: boolean; onPick: () => void }) {
  const v = scaled(it.value, it.scale), prev = v != null && it.change != null ? v - (scaled(it.change, it.scale) ?? 0) : null
  const ya = scaled(yearAgo(it.series), it.scale)
  return (
    <button type="button" onClick={onPick} aria-pressed={on}
      className={`w-full h-full flex flex-col gap-1 p-3 text-left bg-card border rounded-card cursor-pointer ${on ? 'border-accent' : 'border-line'}`}>
      <span className="flex items-baseline justify-between gap-2">
        <span className="text-12 text-ink-2">{it.short || it.label}</span>
        <AsOfBadge asOf={it.asOf} state={it.state} />
      </span>
      <span className="num text-18 font-bold leading-tight text-ink-1">{fmtNumber(v, it.decimals)}</span>
      {it.unit && <span className="text-11 text-ink-3">{it.unit}</span>}
      <span className="flex flex-wrap gap-x-3 text-11 text-ink-3">
        <span>전월 <span className="num text-ink-2">{fmtNumber(prev, it.decimals)}</span></span>
        <span>전년 <span className="num text-ink-2">{fmtNumber(ya, it.decimals)}</span></span>
      </span>
    </button>
  )
}

export default function Macro({ b, selId, setS }: BodyProps<MacroBundle>) {
  const [v, setV] = useViewParam<View>('v', 'price', VIEWS.map(o => o.key))
  const [m, setM] = useViewParam<Country>('m', 'kr', COUNTRIES.map(o => o.key))
  const all = Object.values(b.views?.topics ?? {}).flat()
  const byId = new Map(all.map(x => [x.id, x]))
  // 띠의 「전년비」 칸은 원지수(source)에서 만든 파생값이라 시계열이 없다 → 원지수 24개월로 전년비 시계열을 만든다
  const derived = b.strip.flatMap(x => (x.id.endsWith('_yoy') && x.source && byId.get(x.source)?.series?.length ? [{ ...x, series: yoySeries(byId.get(x.source)!.series) }] : []))
  const pool = poolOf(b.strip, all, derived)
  const sel = pool.get(selId) ?? b.strip[0]
  const cname = COUNTRIES.find(o => o.key === m)!.label
  const cards = (b.views?.topics?.[v] ?? []).filter(x => x.country === m)
  const events = (b.views?.calendar ?? []).filter(e => (e.cc ?? '').toLowerCase() === m)

  const cardPanel = (cls: string) => (
    <Panel className={cls} title={`${cname} ${VIEWS.find(o => o.key === v)!.label}`}>
      {cards.length ? (
        <ul className="m-0 p-0 list-none grid grid-cols-1 sm:grid-cols-2 gap-2">
          {cards.map(it => <li key={it.id}><MacroCard it={it} on={sel?.id === it.id} onPick={() => setS(it.id)} /></li>)}
        </ul>
      ) : <Empty>{cname}의 이 주제 지표가 묶음에 없습니다.</Empty>}
    </Panel>
  )
  const calPanel = (cls: string, primary: boolean): ReactNode => (
    <Panel className={cls} title={`${cname} 경제 일정`} fold={!primary}>
      <EventList events={events} today={b.market?.today} />
    </Panel>
  )

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <SegBar label="주제" options={VIEWS} value={v} onChange={setV} />
        <SegBar label="나라" options={COUNTRIES} value={m} onChange={setM} />
      </div>
      <MarketGrid blocks={[cls => <BigChart className={cls} item={sel} />, ...(v === 'calendar' ? [calPanel] : [cardPanel, calPanel])]} />
    </>
  )
}
