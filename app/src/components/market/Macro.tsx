// 시장 › 거시 — 보기 = 주제 6(묶음 topics 키) + 달력. 고른 주제의 카드를 일곱 나라 한 격자에(카드마다 나라 꼬리표).
// 카드를 누르면 그 지표의 24개월 차트(주소 s). 옛 나라 칩 주소(m=us)로 와도 m 은 읽지 않고 넘긴다.
import type { ReactNode } from 'react'
import type { Sched, StripItem } from '../../lib/bundle'
import { fmtNumber, scaled } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { AsOfBadge, Pill, SegBar } from '../ui'
import { More, Panel } from '../panels'
import { BigChart, counted, EventList, MarketGrid, poolOf, type Block, type BodyProps } from './parts'
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
// 나라 차례: 한국 · 미국 먼저, 그다음 유로 · 영국 · 독일 · 일본 · 중국. 카드 · 일정의 꼬리표 이름도 여기서.
const COUNTRIES = [['kr', '한국'], ['us', '미국'], ['eu', '유로'], ['uk', '영국'], ['de', '독일'], ['jp', '일본'], ['cn', '중국']] as const
const CNAME: Record<string, string> = Object.fromEntries(COUNTRIES)
const RANK: Record<string, number> = Object.fromEntries(COUNTRIES.map(([k], i) => [k, i]))
type View = typeof VIEWS[number]['key']

/** 거시 카드: 나라 꼬리표 · 이름 · 기준 달 → 값(+단위) → 전월 · 전년. 이름 앞의 나라 이름은 꼬리표가 말하므로 뗀다. 누르면 큰 차트. */
function MacroCard({ it, on, onPick }: { it: MacroItem; on: boolean; onPick: () => void }) {
  const v = scaled(it.value, it.scale), prev = v != null && it.change != null ? v - (scaled(it.change, it.scale) ?? 0) : null
  const ya = scaled(yearAgo(it.series), it.scale)
  const cn = CNAME[it.country ?? '']
  const name = it.short || it.label
  return (
    <button type="button" onClick={onPick} aria-pressed={on}
      className={`w-full h-full flex flex-col gap-1 p-3 text-left bg-card border rounded-card cursor-pointer ${on ? 'border-accent' : 'border-line'}`}>
      <span className="flex items-baseline justify-between gap-2">
        <span className="text-12 text-ink-2">{cn && <span className="mr-1 inline-flex align-middle"><Pill tone="o">{cn}</Pill></span>}{cn ? name.replace(`${cn} `, '') : name}</span>
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
  const all = Object.values(b.views?.topics ?? {}).flat()
  const byId = new Map(all.map(x => [x.id, x]))
  // 띠의 「전년비」 칸은 원지수(source)에서 만든 파생값이라 시계열이 없다 → 원지수 24개월로 전년비 시계열을 만든다
  const derived = b.strip.flatMap(x => (x.id.endsWith('_yoy') && x.source && byId.get(x.source)?.series?.length ? [{ ...x, series: yoySeries(byId.get(x.source)!.series) }] : []))
  const pool = poolOf(b.strip, all, derived)
  const sel = pool.get(selId) ?? b.strip[0]
  // 나라 차례대로(같은 나라 안은 묶음 차례). 차례표에 없는 나라는 뒤로.
  const cards = (b.views?.topics?.[v] ?? []).map((x, i) => [x, i] as const)
    .sort(([x, i], [y, j]) => (RANK[x.country ?? ''] ?? 99) - (RANK[y.country ?? ''] ?? 99) || i - j).map(([x]) => x)
  const nations = new Set(cards.map(x => x.country)).size
  const cname = (cc?: string) => CNAME[(cc ?? '').toLowerCase()]
  // 일정 이름 앞의 나라 이름(「미국 소매판매」)도 꼬리표가 말하므로 뗀다
  const events = (b.views?.calendar ?? []).map(e => { const n = cname(e.cc); return n && e.name.startsWith(`${n} `) ? { ...e, name: e.name.slice(n.length + 1) } : e })

  const cardPanel = (cls: string) => (
    <Panel className={cls} title={`${VIEWS.find(o => o.key === v)!.label} · 나라 ${nations} · 지표 ${cards.length}`}>
      <More key={v} rows={cards} name="거시 카드" unit="개">{shown => (
        <ul className="m-0 p-0 list-none grid grid-cols-1 sm:grid-cols-2 gap-2">
          {shown.map(it => <li key={it.id}><MacroCard it={it} on={sel?.id === it.id} onPick={() => setS(it.id)} /></li>)}
        </ul>
      )}</More>
    </Panel>
  )
  const big: [string, Block] = ['big', cls => <BigChart className={cls} item={sel} />]
  const calPanel = (cls: string, primary: boolean): ReactNode => (
    <Panel className={cls} title="경제 일정" fold={!primary}>
      <EventList events={events} today={b.market?.today} tag={e => cname(e.cc) && <Pill tone="o">{cname(e.cc)}</Pill>} />
    </Panel>
  )

  return (
    <>
      <SegBar label="주제" options={VIEWS} value={v} onChange={counted('거시 주제', VIEWS, setV)} />
      <MarketGrid blocks={v === 'calendar' ? [big, ['cal', calPanel]] : [big, ['card', cardPanel], ['cal', calPanel]]} />
    </>
  )
}
