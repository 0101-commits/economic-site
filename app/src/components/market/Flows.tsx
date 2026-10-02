// 시장 › 수급 — 보기 일별·주별·월별(투자자 400행 집계)·종목별·국민연금·vs 환율. 단위는 묶음 그대로(시장 = 억원, 종목 = 주).
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { loadIndicator, type Flows as FlowsBlock, type StripItem } from '../../lib/bundle'
import { fmtNumber, shortDate, slicePeriods, PERIODS, type PeriodKey, type Pt } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { SegBar } from '../ui'
import { DivergingBars, LineChart } from '../charts'
import { Panel, RankTable, type Col } from '../panels'
import { BigChart, Empty, MarketGrid, poolOf, type BodyProps } from './parts'
import { column, cumsum, groupFlows, rollSum, type FlowRow } from './calc'

type StockFlow = { name: string; short?: string; market?: string; secType?: string; investor: (string | number | null)[][] }
export type FlowsBundle = {
  strip: StripItem[]
  views?: {
    investors?: FlowsBlock
    stocks?: { asOf?: string; state?: string; columns?: string[]; items: Record<string, StockFlow> }
    nps?: { asOf?: string; state?: string; source?: string; allocation: { asset: string; pct: number | null }[] }
  }
}

const VIEWS = [
  { key: 'daily', label: '일별' }, { key: 'weekly', label: '주별' }, { key: 'monthly', label: '월별' },
  { key: 'stocks', label: '종목별' }, { key: 'nps', label: '국민연금' }, { key: 'fx', label: 'vs 환율' },
] as const
type View = typeof VIEWS[number]['key']
type Grain = 'daily' | 'weekly' | 'monthly'
const GRAIN: Record<Grain, { label: string; bars: number }> = { daily: { label: '거래일', bars: 60 }, weekly: { label: '주', bars: 26 }, monthly: { label: '달', bars: 24 } }
const WHO = [{ key: 1, label: '외국인' }, { key: 2, label: '기관' }, { key: 3, label: '개인' }] as const

const signed = (v: number | null | undefined) => (v == null ? '—' : `${v > 0 ? '+' : ''}${fmtNumber(v)}`)
const flowCols: Col<FlowRow>[] = [
  { key: 'd', label: '기간', get: r => shortDate(r[0]), role: 'name' },
  { key: 'f', label: '외국인', get: r => r[1], num: true, role: 'value', render: r => signed(r[1]) },
  { key: 'i', label: '기관', get: r => r[2], num: true, render: r => signed(r[2]) },
  { key: 'r', label: '개인', get: r => r[3], num: true, render: r => signed(r[3]) },
]
type StockRow = { code: string; name: string; f: number; i: number; r: number; hold: number | null; days: number }
const stockCols: Col<StockRow>[] = [
  { key: 'name', label: '종목', get: r => r.name, role: 'name' },
  { key: 'f', label: '외국인', get: r => r.f, num: true, role: 'value', render: r => signed(r.f) },
  { key: 'i', label: '기관', get: r => r.i, num: true, render: r => signed(r.i) },
  { key: 'r', label: '개인', get: r => r.r, num: true, render: r => signed(r.r) },
  { key: 'hold', label: '외국인 보유', get: r => r.hold, num: true, role: 'sub', render: r => (r.hold == null ? null : `${fmtNumber(r.hold * 100, 2)}%`) },
]

export default function Flows({ b, selId }: BodyProps<FlowsBundle>) {
  const [v, setV] = useViewParam<View>('v', 'daily', VIEWS.map(o => o.key))
  const inv = b.views?.investors
  const col = (k: string) => (inv?.columns ?? ['date', 'foreign', 'inst', 'retail']).indexOf(k)
  const daily = useMemo((): FlowRow[] => (inv?.rows ?? []).map(r => [String(r[0]), r[col('foreign')] as number | null, r[col('inst')] as number | null, r[col('retail')] as number | null]), [inv])
  // 띠 칸에 시계열이 없으니 투자자 400행으로 채운다(5일 누적은 끝에서 5개씩 합)
  const fSeries = column(daily, 1)
  const pool = poolOf(b.strip, b.strip.flatMap(x => {
    const s = x.id === 'flow_foreign' ? fSeries : x.id === 'flow_inst' ? column(daily, 2) : x.id === 'flow_retail' ? column(daily, 3) : x.id === 'flow_foreign_5d' ? rollSum(fSeries, 5) : null
    return s ? [{ ...x, series: s }] : []
  }))
  const sel = pool.get(selId) ?? b.strip[0]
  const grain: Grain = v === 'weekly' || v === 'monthly' ? v : 'daily'

  const period = (cls: string, primary: boolean) => {
    const rows = grain === 'daily' ? daily : groupFlows(daily, grain === 'weekly' ? 'week' : 'month')
    const tail = rows.slice(-GRAIN[grain].bars)
    return (
      <Panel className={cls} title={`투자자 순매수 · ${VIEWS.find(o => o.key === grain)!.label}`} unit={inv?.unit} source={inv?.market} asOf={inv?.asOf} state={inv?.state} fold={primary ? undefined : 'mobile'}>
        {tail.length > 1 ? (
          <div className="flex flex-col gap-4">
            {WHO.map(w => (
              <div key={w.key}>
                <p className="m-0 mb-1 text-12 text-ink-2">{w.label} {tail.length}{GRAIN[grain].label}</p>
                <DivergingBars vertical label={`${w.label} ${tail.length}${GRAIN[grain].label} 순매수`}
                  bars={tail.map(r => ({ key: r[0], label: r[0], value: r[w.key] }))} />
              </div>
            ))}
            <div className="flex justify-between -mt-3 text-11 text-ink-3 num"><span>{shortDate(tail[0][0])}</span><span>{shortDate(tail[tail.length - 1][0])}</span></div>
            <p className="md:hidden m-0 -mb-2 text-11 text-ink-3">숫자는 외국인 · 행을 누르면 기관·개인</p>
            <RankTable label={`투자자 순매수 ${VIEWS.find(o => o.key === grain)!.label}`} cols={flowCols} rows={[...rows].reverse().slice(0, 20)} rowKey={r => r[0]} />
          </div>
        ) : <Empty>수급 자료가 없습니다.</Empty>}
      </Panel>
    )
  }
  const stocks = (cls: string, primary: boolean) => {
    const st = b.views?.stocks
    const c = (k: string) => (st?.columns ?? ['date', 'foreign', 'inst', 'retail', 'fholdRate']).indexOf(k)
    const sum = (rs: (string | number | null)[][], k: string) => rs.reduce((a, r) => a + ((r[c(k)] as number | null) ?? 0), 0)
    const rows: StockRow[] = Object.entries(st?.items ?? {}).map(([code, s]) => ({
      code, name: s.short || s.name, f: sum(s.investor, 'foreign'), i: sum(s.investor, 'inst'), r: sum(s.investor, 'retail'),
      hold: (s.investor[s.investor.length - 1]?.[c('fholdRate')] as number | null) ?? null, days: s.investor.length,
    }))
    const days = Math.max(0, ...rows.map(r => r.days))
    return (
      <Panel className={cls} title="종목별 순매수" unit={`주 · 최근 ${days}거래일 합`} asOf={st?.asOf} state={st?.state} fold={primary ? undefined : 'mobile'}>
        {rows.length ? (
          <>
            <p className="md:hidden m-0 mb-1 text-11 text-ink-3">숫자는 외국인 · 행을 누르면 기관·개인</p>
            <RankTable label="종목별 투자자 순매수" cols={stockCols} rows={rows} rowKey={r => r.code} />
          </>
        ) : <Empty>종목별 수급 자료가 없습니다.</Empty>}
      </Panel>
    )
  }
  const nps = (cls: string, primary: boolean) => {
    const n = b.views?.nps
    return (
      <Panel className={cls} title="국민연금 자산배분" source={n?.source} asOf={n?.asOf?.slice(0, 7)} state={n?.state} fold={primary ? undefined : 'mobile'}>
        {n?.allocation.length ? (
          <ul className="m-0 p-0 list-none flex flex-col gap-2">
            {n.allocation.map(a => (
              <li key={a.asset} className="grid grid-cols-[4.5rem_minmax(0,1fr)_3.5rem] items-center gap-2 text-12">
                <span className="text-ink-2">{a.asset}</span>
                <span className="relative h-3 bg-line rounded-chip"><span className="absolute inset-y-0 left-0 bg-ink-2 rounded-chip" style={{ width: `${Math.min(100, a.pct ?? 0)}%` }} /></span>
                <span className="num text-right text-ink-1">{a.pct == null ? '—' : `${fmtNumber(a.pct, 1)}%`}</span>
              </li>
            ))}
          </ul>
        ) : <Empty>국민연금 자료가 없습니다.</Empty>}
      </Panel>
    )
  }
  const fx = (cls: string) => <FxPanel className={cls} foreign={fSeries} unit={inv?.unit} />

  const order: ((cls: string, primary: boolean) => ReactNode)[] =
    v === 'stocks' ? [stocks, period, nps] : v === 'nps' ? [nps, period, stocks] : v === 'fx' ? [fx, period, stocks, nps] : [period, stocks, nps]
  return (
    <>
      <SegBar label="보기" options={VIEWS} value={v} onChange={setV} />
      <MarketGrid blocks={[cls => <BigChart className={cls} item={sel} />, ...order]} />
    </>
  )
}

/** 외국인 누적 순매수(기간 시작 = 0) 와 달러/원을 같은 기간으로 위아래에. 두 값은 단위가 달라 한 축에 겹치지 않는다. */
function FxPanel({ foreign, unit, className }: { foreign: Pt[]; unit?: string; className: string }) {
  const [p, setP] = useViewParam<PeriodKey>('p', '3m', PERIODS.map(o => o.key))
  const [usd, setUsd] = useState<Pt[] | null>(null)
  useEffect(() => { loadIndicator('usdkrw').then(r => setUsd(r.series ?? []), () => setUsd([])) }, [])
  const fPeriods = useMemo(() => Object.fromEntries(Object.entries(slicePeriods(foreign)).map(([k, s]) => [k, cumsum(s!)])), [foreign])
  return (
    <Panel className={className} title="외국인 vs 환율" source="같은 기간">
      <div className="flex flex-col gap-4">
        <div>
          <p className="m-0 mb-1 text-12 text-ink-2">외국인 누적 순매수({unit ?? '억원'}, 기간 시작 = 0)</p>
          <LineChart label="외국인 누적 순매수" periods={fPeriods} period={p} onPeriod={setP} decimals={0} />
        </div>
        <div>
          <p className="m-0 mb-1 text-12 text-ink-2">달러/원</p>
          <LineChart label="달러/원" periods={slicePeriods(usd)} period={p} onPeriod={setP} decimals={1} empty={usd === null ? '불러오는 중' : '시계열 준비 중'} />
        </div>
      </div>
    </Panel>
  )
}
