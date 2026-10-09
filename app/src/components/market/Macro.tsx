// 시장 › 거시 — 보기 = 주제 6(묶음 topics 키) + 달력. 고른 주제의 카드를 일곱 나라 한 격자에(카드마다 나라 꼬리표).
// 카드를 누르면 그 지표의 24개월 차트(주소 s). 옛 나라 칩 주소(m=us)로 와도 m 은 읽지 않고 넘긴다.
// 「달력」(v=calendar)은 월 격자 + 그 달 목록(이전 · 예측 · 실제). 나라 칩은 일정 자료에 있는 나라만.
import { useState, type ReactNode } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { Sched, StripItem } from '../../lib/bundle'
import { fmtNumber, scaled, shortDate } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { AsOfBadge, Pill, SegBar } from '../ui'
import { More, Panel, RankTable, type Col } from '../panels'
import { BigChart, counted, Empty, EventList, MarketGrid, poolOf, type Block, type BodyProps } from './parts'
import { addMonth, monthCells, yearAgo, yoySeries } from './calc'
import { kstDay } from '../../lib/personal/calc'

type MacroItem = StripItem & { country?: string; topic?: string; source?: string }
export type MacroBundle = {
  market?: { today?: string }
  strip: MacroItem[]
  views?: { topics?: Record<string, MacroItem[]>; calendar?: Sched[] }
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

/** 달력 한 줄: name = 나라 이름을 뗀 이름(꼬리표가 나라를 말한다), full = 원래 이름(모바일 목록 · 정렬). */
type CalEv = Sched & { full: string }
const WEEK = ['일', '월', '화', '수', '목', '금', '토']
// 실제가 예측보다 좋음 = 상승색 · 나쁨 = 하락색(현행 화면 달력과 같은 뜻)
const BEAT: Record<string, string> = { '1': 'text-up', '-1': 'text-down' }
const calCols: Col<CalEv>[] = [
  { key: 'date', label: '날짜', get: e => `${e.date} ${e.time ?? ''}`, role: 'sub', render: e => <span className="num">{shortDate(e.date)}{e.time ? ` ${e.time}` : ''}</span> },
  { key: 'name', label: '일정', get: e => e.full, role: 'name', render: e => (
    <>
      {CNAME[(e.cc ?? '').toLowerCase()] && <span className="mr-1.5 inline-flex align-middle"><Pill tone="o">{CNAME[(e.cc ?? '').toLowerCase()]}</Pill></span>}
      {e.name}{!!e.stars && <span className="ml-1.5 text-11 text-ink-3" aria-label={`중요도 ${e.stars}`}>{'★'.repeat(e.stars)}</span>}
    </>
  ) },
  { key: 'prev', label: '이전', get: e => e.prev, num: true },
  { key: 'fore', label: '예측', get: e => e.fore, num: true, role: 'change', render: e => (e.fore == null ? null : <><span className="md:hidden text-ink-3">예측 </span>{e.fore}</>) },
  { key: 'act', label: '실제', get: e => e.act, num: true, role: 'value', render: e => (e.act == null ? null : <span className={`font-bold ${BEAT[String(e.beat)] ?? 'text-ink-1'}`}>{e.act}</span>) },
]

/** 거시 「달력」: 나라 칩 · 월 격자(7열, 날짜 칸에 건수 · 별 3 점 = 그날 가장 높은 중요도, 오늘 테두리) · 그 달(누른 날) 목록. */
function CalendarPanel({ className, events, today }: { className: string; events: CalEv[]; today?: string }) {
  const [cc, setCc] = useState('all')
  const [day, setDay] = useState<string | null>(null)
  const dates = events.map(e => e.date).sort()
  const lo = dates[0]?.slice(0, 7) ?? '', hi = dates[dates.length - 1]?.slice(0, 7) ?? ''
  const [ym, setYm] = useState(() => { const t = (today ?? '').slice(0, 7); return t >= lo && t <= hi ? t : lo })
  if (!events.length) return <Panel className={className} title="경제 일정"><Empty>일정 자료가 없습니다.</Empty></Panel>

  const nations = [{ key: 'all', label: '전체' }, ...COUNTRIES.filter(([k]) => events.some(e => e.cc?.toLowerCase() === k)).map(([key, label]) => ({ key, label }))]
  const shown = events.filter(e => cc === 'all' || e.cc?.toLowerCase() === cc)
  const byDay = new Map<string, CalEv[]>()
  for (const e of shown) byDay.set(e.date, [...(byDay.get(e.date) ?? []), e])
  const rows = shown.filter(e => (day ? e.date === day : e.date.startsWith(ym)))
  const move = (k: number) => { setYm(addMonth(ym, k)); setDay(null) }
  const navBtn = 'size-8 inline-flex items-center justify-center rounded-btn border border-line bg-card text-ink-2 cursor-pointer disabled:cursor-default disabled:opacity-40'
  return (
    <Panel className={className} title="경제 일정">
      <div className="flex flex-col gap-3">
        <SegBar label="나라" options={nations} value={cc} onChange={k => { setCc(k); setDay(null) }} />
        <div className="flex items-center justify-between">
          <button type="button" className={navBtn} aria-label="이전 달" disabled={ym <= lo} onClick={() => move(-1)}><ChevronLeft size={16} aria-hidden /></button>
          <span className="num text-14 font-bold text-ink-1">{ym.slice(0, 4)}년 {+ym.slice(5)}월</span>
          <button type="button" className={navBtn} aria-label="다음 달" disabled={ym >= hi} onClick={() => move(1)}><ChevronRight size={16} aria-hidden /></button>
        </div>
        <div>
          <div aria-hidden className="grid grid-cols-7 gap-1 mb-1 text-center text-11 text-ink-3">{WEEK.map(w => <span key={w}>{w}</span>)}</div>
          <ol className="m-0 p-0 list-none grid grid-cols-7 gap-1" aria-label={`${+ym.slice(5)}월 달력`}>
            {monthCells(ym).map((d, i) => {
              if (!d) return <li key={`x${i}`} aria-hidden />
              const evs = byDay.get(d) ?? [], n = evs.length, top = Math.max(0, ...evs.map(e => e.stars ?? 0))
              const isToday = d === today, on = d === day
              const inner = (
                <>
                  <span className={`num text-12 ${isToday ? 'font-bold text-ink-1' : 'text-ink-2'}`}>{+d.slice(8)}</span>
                  {n > 0 && <span className="num text-11 text-ink-1">{n}건</span>}
                  {n > 0 && <span aria-hidden className="flex gap-0.5">{[1, 2, 3].map(k => <span key={k} className={`size-1.5 rounded-chip ${k <= top ? 'bg-ink-1' : 'bg-line'}`} />)}</span>}
                </>
              )
              const box = `w-full h-16 flex flex-col items-center gap-0.5 pt-1 rounded-inner border ${on ? 'border-accent' : isToday ? 'border-ink-1' : 'border-transparent'}`
              return (
                <li key={d} aria-current={isToday ? 'date' : undefined}>
                  {n ? (
                    <button type="button" aria-pressed={on} onClick={() => setDay(on ? null : d)}
                      aria-label={`${shortDate(d)} 일정 ${n}건 · 중요도 ${top}${isToday ? ' · 오늘' : ''}`}
                      className={`${box} bg-transparent cursor-pointer hover:bg-ink-3/5`}>{inner}</button>
                  ) : <div className={box}>{inner}</div>}
                </li>
              )
            })}
          </ol>
          {ym === lo && <p className="m-0 mt-1 text-11 text-ink-3">이 달은 <span className="num">{shortDate(dates[0])}</span>부터 실려 있습니다.</p>}
        </div>
        <div className="flex items-center gap-2 text-12 text-ink-2">
          <span>{day ? `${shortDate(day)} 일정` : `${+ym.slice(5)}월 일정`} <span className="num">{rows.length}</span>건</span>
          {day && <button type="button" onClick={() => setDay(null)} className="h-8 px-0 border-0 bg-transparent cursor-pointer text-12 text-ink-2 hover:text-ink-1 underline">이 달 전체</button>}
        </div>
        {rows.length ? <RankTable key={`${ym}-${day}-${cc}`} label="경제 일정" cols={calCols} rows={rows} rowKey={e => `${e.date}-${e.time}-${e.full}`} />
          : <Empty>이 달에 실린 일정이 없습니다.</Empty>}
      </div>
    </Panel>
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
  const events = (b.views?.calendar ?? []).map((e): CalEv => { const n = cname(e.cc); return { ...e, full: e.name, name: n && e.name.startsWith(`${n} `) ? e.name.slice(n.length + 1) : e.name } })

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
  // 「오늘」은 지금의 KST 날짜(묶음의 market.today 는 묶음을 만든 날이라 자정을 넘기거나 묶음이 묵으면 어제다)
  const today = kstDay()
  const calendar = (cls: string) => <CalendarPanel className={cls} events={events} today={today} />
  const calPanel = (cls: string, primary: boolean): ReactNode => (
    <Panel className={cls} title="경제 일정" fold={!primary}>
      <EventList events={events} today={today} tag={e => cname(e.cc) && <Pill tone="o">{cname(e.cc)}</Pill>} />
    </Panel>
  )

  return (
    <>
      <SegBar label="주제" options={VIEWS} value={v} onChange={counted('거시 주제', VIEWS, setV)} />
      <MarketGrid blocks={v === 'calendar' ? [big, ['cal', calendar]] : [big, ['card', cardPanel], ['cal', calPanel]]} />
    </>
  )
}
