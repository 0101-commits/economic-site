// 시장 › 해외 — 큰 차트 = 띠에서 고른 지수의 자기 차트(기본 S&P 500). 보기 줄은 목차(주소 v), 시작=100 겹침 차트는 맨 아래 넓은 칸.
import { useMemo, useState, type ReactNode } from 'react'
import type { Sched, StripItem } from '../../lib/bundle'
import { fmtNumber, fmtPct, range52, slicePeriods, PERIODS, type PeriodKey, type Pt } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { LineChart, Range52 } from '../charts'
import { Panel, RankTable, type Col } from '../panels'
import { BigChart, ChangeText, CurveChart, CurveTable, Empty, EventList, MarketGrid, poolOf, Toc, type Block, type BodyProps, type Curve } from './parts'
import { rebase } from './calc'

type Compare = { from?: string; base?: number; series: Record<string, Pt[]> }
export type GlobalBundle = {
  market?: { today?: string }
  strip: StripItem[]
  views?: {
    indices?: StripItem[]
    compare?: Compare
    fearGreed?: StripItem & { rating?: string }
    vix?: StripItem
    move?: StripItem
    usCurve?: Curve
    usCalendar?: Sched[]
  }
}

// 차례 = 격자 차례. 비교(겹침 차트)를 끝에 둬 한 줄을 다 쓴다.
const VIEWS = [
  { key: 'indices', label: '지수' }, { key: 'fear', label: '공포·변동성' },
  { key: 'curve', label: '미 국채' }, { key: 'calendar', label: '미국 일정' }, { key: 'compare', label: '비교' },
] as const
type View = typeof VIEWS[number]['key']
// CNN 공포·탐욕 등급(묶음 rating 원문) → 우리말
const RATING: Record<string, string> = { 'extreme fear': '극단적 공포', fear: '공포', neutral: '중립', greed: '탐욕', 'extreme greed': '극단적 탐욕' }
const MAX_CMP = 4   // 겹침 선은 넷까지(LineChart 비교 모드 상한)

const idxCols: Col<StripItem & { r52: ReturnType<typeof range52> }>[] = [
  { key: 'name', label: '지수', get: r => r.short || r.label, role: 'name' },
  { key: 'value', label: '현재', get: r => r.value, num: true, decimals: 2, role: 'value' },
  { key: 'pct', label: '등락률', get: r => r.changePct, num: true, role: 'change', render: r => <ChangeText chg={r.change} pct={r.changePct} /> },
  { key: 'r52', label: '52주', get: r => r.r52?.high, render: r => (r.r52 ? <div className="w-44"><Range52 low={r.r52.low} high={r.r52.high} value={r.value} decimals={0} /></div> : null) },
]

export default function Global({ b, selId, setS }: BodyProps<GlobalBundle>) {
  const [, setV] = useViewParam<View>('v', 'indices', VIEWS.map(o => o.key))
  const vw = b.views
  const sense = [vw?.fearGreed, vw?.vix, vw?.move].filter((x): x is StripItem & { rating?: string } => !!x)
  const pool = poolOf(b.strip, vw?.indices, sense)
  const sel = pool.get(selId) ?? b.strip[0]
  const indices = useMemo(() => (vw?.indices ?? []).map(x => ({ ...x, r52: range52(x.series) })), [vw?.indices])
  const name = (id: string) => { const it = pool.get(id); return it ? it.short || it.label : id }

  const panels: Record<View, (cls: string, primary: boolean) => ReactNode> = {
    indices: (cls, primary) => (
      <Panel className={cls} title="세계 지수" fold={!primary}>
        {indices.length ? <RankTable label="세계 지수" cols={idxCols} rows={indices} rowKey={r => r.id} /> : <Empty>지수 자료가 없습니다.</Empty>}
      </Panel>
    ),
    compare: cls => <CompareChart className={cls} compare={vw?.compare} lead={sel?.id} name={name} ids={Object.keys(vw?.compare?.series ?? {})} />,
    fear: (cls, primary) => (
      <Panel className={cls} title="공포·변동성" fold={!primary}>
        {sense.length ? (
          <ul className="m-0 p-0 list-none">
            {sense.map(it => (
              <li key={it.id} className="border-b border-line last:border-b-0">
                <button type="button" onClick={() => setS(it.id)} aria-pressed={sel?.id === it.id}
                  className={`w-full flex items-baseline justify-between gap-3 py-2 border-0 bg-transparent text-left cursor-pointer ${sel?.id === it.id ? 'font-bold' : ''}`}>
                  <span className="text-13 text-ink-1">{it.short || it.label}</span>
                  <span className="shrink-0 text-right">
                    <span className="num text-14 text-ink-1">{fmtNumber(it.value, it.decimals)}</span>
                    {it.rating && <span className="ml-2 text-12 text-ink-2">{RATING[it.rating.replace('_', ' ')] ?? it.rating}</span>}
                    <span className="block"><ChangeText chg={it.change} pct={it.changePct} decimals={it.decimals} /></span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : <Empty>심리 지표 자료가 없습니다.</Empty>}
      </Panel>
    ),
    curve: (cls, primary) => (
      <Panel className={cls} title="미 국채 수익률" asOf={vw?.usCurve?.asOf} state={vw?.usCurve?.state} fold={!primary}>
        {vw?.usCurve?.current.some(x => x != null) ? (
          <div className="flex flex-col gap-3"><CurveChart curve={vw.usCurve} label="미 국채 수익률 곡선" /><CurveTable curve={vw.usCurve} /></div>
        ) : <Empty>수익률 곡선 자료가 없습니다.</Empty>}
      </Panel>
    ),
    calendar: (cls, primary) => (
      <Panel className={cls} title="미국 일정" fold={!primary}>
        <EventList events={vw?.usCalendar ?? []} today={b.market?.today} />
      </Panel>
    ),
  }

  return (
    <>
      <Toc where="해외" items={VIEWS} onPick={setV} />
      <MarketGrid blocks={[['big', cls => <BigChart className={cls} item={sel} />], ...VIEWS.map((o): [string, Block] => [o.key, panels[o.key]])]} />
    </>
  )
}

/** 시작=100 겹침 차트. 기간을 바꿀 때마다 그 기간 첫날을 100 으로 다시 맞춘다. 처음 고른 것 = 띠에서 고른 지수 + 기본 셋, 넷까지. */
function CompareChart({ compare, lead, ids, name, className }: {
  compare?: Compare; lead?: string; ids: string[]; name: (id: string) => string; className: string
}) {
  const [p, setP] = useViewParam<PeriodKey>('p', '3m', PERIODS.map(o => o.key))
  const [picked, setPicked] = useState<string[]>(() => [...new Set([lead, 'kospi', 'sp500', 'nasdaq'].filter((x): x is string => !!x && ids.includes(x)))].slice(0, MAX_CMP))
  const periods = (id: string) => {
    const cut = slicePeriods(compare?.series[id])
    return Object.fromEntries(Object.entries(cut).map(([k, pts]) => [k, rebase(pts!)])) as Partial<Record<PeriodKey, Pt[]>>
  }
  const toggle = (id: string) => setPicked(s => (s.includes(id) ? s.filter(x => x !== id) : s.length < MAX_CMP ? [...s, id] : s))
  const [main, ...others] = picked
  return (
    <Panel className={className} title="지수 비교" source="기간 시작 = 100">
      <div className="flex flex-wrap gap-1 mb-3" role="group" aria-label={`비교할 지수(최대 ${MAX_CMP}개)`}>
        {ids.map(id => {
          const on = picked.includes(id)
          return (
            <button key={id} type="button" aria-pressed={on} onClick={() => toggle(id)} disabled={!on && picked.length >= MAX_CMP}
              className={`h-8 px-3 rounded-btn text-13 whitespace-nowrap border ${on ? 'bg-accent text-on-accent border-accent font-bold' : 'bg-card text-ink-2 border-line hover:text-ink-1 disabled:opacity-50'}`}>
              {name(id)}
            </button>
          )
        })}
      </div>
      {main ? (
        <>
          <LineChart label="지수 비교(시작=100)" name={name(main)} periods={periods(main)} period={p} onPeriod={setP} decimals={1}
            compare={others.map(id => ({ name: name(id), periods: periods(id) }))} />
          <p className="m-0 mt-2 text-12 text-ink-3">기간 끝 값: {picked.map(id => {
            const pts = periods(id)[p] ?? periods(id)['3m']
            const last = pts?.[pts.length - 1]?.[1]
            return <span key={id} className="mr-3">{name(id)} <span className="num text-ink-2">{last == null ? '—' : fmtPct(last - 100)}</span></span>
          })}</p>
        </>
      ) : <Empty>비교할 지수를 고르세요.</Empty>}
    </Panel>
  )
}
