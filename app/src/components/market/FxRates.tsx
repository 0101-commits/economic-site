// 시장 › 환율금리 — 보기 환율·금리·수익률 곡선·중앙은행. 큰 차트 = 띠에서 고른 칸(기본 달러/원).
import { useMemo, useState, type ReactNode } from 'react'
import { shownUnit, type Sched, type StripItem } from '../../lib/bundle'
import { fmtNumber, mdHm, range52, scaled, scaledPts } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { AsOfBadge, SegBar } from '../ui'
import { Range52 } from '../charts'
import { Panel, RankTable, type Col } from '../panels'
import { arrange, BigChart, ChangeText, CurveChart, CurveTable, Empty, MarketGrid, poolOf, type Block, type BodyProps, type Curve } from './parts'

type Bank = StripItem & { country?: string; nextMeeting?: Sched | null }
export type FxRatesBundle = {
  strip: StripItem[]
  views?: { fx?: StripItem[]; rates?: StripItem[]; curves?: Record<string, Curve>; centralBanks?: Bank[] }
}

const VIEWS = [{ key: 'fx', label: '환율' }, { key: 'rates', label: '금리' }, { key: 'curves', label: '수익률 곡선' }, { key: 'banks', label: '중앙은행' }] as const
type View = typeof VIEWS[number]['key']
const COUNTRY: Record<string, string> = { us: '미국', kr: '한국', eu: '유로', uk: '영국', jp: '일본' }

type FxRow = StripItem & { r52: ReturnType<typeof range52> }
const fxCols: Col<FxRow>[] = [
  { key: 'name', label: '통화', get: r => r.short || r.label, role: 'name' },
  { key: 'value', label: '현재', get: r => scaled(r.value, r.scale), num: true, role: 'value',
    render: r => `${fmtNumber(scaled(r.value, r.scale), r.decimals)}${shownUnit(r) ?? ''}` },
  { key: 'pct', label: '등락률', get: r => r.changePct, num: true, role: 'change', render: r => <ChangeText chg={r.change} pct={r.changePct} /> },
  { key: 'r52', label: '52주', get: r => r.r52?.high,
    render: r => (r.r52 ? <div className="w-44"><Range52 low={r.r52.low} high={r.r52.high} value={scaled(r.value, r.scale)} decimals={r.decimals} /></div> : null) },
]
const rateCols: Col<StripItem>[] = [
  { key: 'name', label: '금리', get: r => r.short || r.label, role: 'name' },
  { key: 'value', label: '현재', get: r => r.value, num: true, role: 'value', render: r => `${fmtNumber(r.value, r.decimals)}%` },
  { key: 'chg', label: '전일 대비', get: r => r.change, num: true, role: 'change', render: r => <ChangeText chg={r.change} decimals={2} suffix="%p" /> },
  { key: 'asOf', label: '기준', get: r => r.asOf, role: 'sub', render: r => <AsOfBadge asOf={r.asOf} state={r.state} /> },
]

export default function FxRates({ b, selId, setS }: BodyProps<FxRatesBundle>) {
  const [v, setV] = useViewParam<View>('v', 'fx', VIEWS.map(o => o.key))
  const vw = b.views
  const pool = poolOf(b.strip, vw?.fx, vw?.rates)
  const sel = pool.get(selId) ?? b.strip[0]
  const fx = useMemo(() => (vw?.fx ?? []).map(x => ({ ...x, r52: range52(scaledPts(x.series ?? [], x.scale)) })), [vw?.fx])
  const curveKeys = Object.keys(vw?.curves ?? {}).filter(k => vw!.curves![k].current.some(x => x != null))
  const [cc, setCc] = useState(curveKeys[0] ?? 'us')
  const curve = vw?.curves?.[cc]
  const curveOpts = curveKeys.map(k => ({ key: k, label: COUNTRY[k] ?? vw!.curves![k].label ?? k }))

  const panels: Record<View, (cls: string, primary: boolean) => ReactNode> = {
    fx: (cls, primary) => (
      <Panel className={cls} title={`환율 ${fx.length}`} fold={!primary}>
        {fx.length ? <RankTable label="환율" cols={fxCols} rows={fx} rowKey={r => r.id} onPick={r => setS(r.id)} selectedKey={sel?.id} /> : <Empty>환율 자료가 없습니다.</Empty>}
      </Panel>
    ),
    rates: (cls, primary) => (
      <Panel className={cls} title={`금리 ${vw?.rates?.length ?? ''}`} fold={!primary}>
        {vw?.rates?.length ? <RankTable label="국채 금리" cols={rateCols} rows={vw.rates} rowKey={r => r.id} onPick={r => setS(r.id)} selectedKey={sel?.id} /> : <Empty>금리 자료가 없습니다.</Empty>}
      </Panel>
    ),
    curves: (cls, primary) => (
      <Panel className={cls} title="수익률 곡선" source={curve?.label ?? undefined} asOf={curve?.asOf} state={curve?.state} fold={!primary}>
        {curve ? (
          <div className="flex flex-col gap-3">
            {curveOpts.length > 1 && <SegBar label="나라" options={curveOpts} value={cc} onChange={setCc} />}
            <CurveChart curve={curve} label={`${COUNTRY[cc] ?? cc} 수익률 곡선`} />
            <CurveTable curve={curve} />
          </div>
        ) : <Empty>수익률 곡선 자료가 없습니다.</Empty>}
      </Panel>
    ),
    banks: (cls, primary) => (
      <Panel className={cls} title="중앙은행" fold={!primary}>
        {vw?.centralBanks?.length ? (
          <ul className="m-0 p-0 list-none">
            {vw.centralBanks.map(x => (
              <li key={x.id} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-2 border-b border-line last:border-b-0">
                <span className="text-13 text-ink-1">{x.short || x.label}</span>
                <span className="num text-14 font-bold text-ink-1">{fmtNumber(x.value, 2)}%</span>
                <span className="basis-full flex flex-wrap gap-x-3 text-11 text-ink-3">
                  <span>변경 <ChangeText chg={x.change} decimals={2} suffix="%p" /></span>
                  <AsOfBadge asOf={x.asOf} state={x.state} />
                  <span>다음 회의 {x.nextMeeting?.date ? <span className="num text-ink-2">{mdHm(x.nextMeeting.date)}{x.nextMeeting.time ? ` ${x.nextMeeting.time}` : ''}{x.nextMeeting.approx ? ' (추정)' : ''}</span> : '—'}</span>
                </span>
              </li>
            ))}
          </ul>
        ) : <Empty>중앙은행 자료가 없습니다.</Empty>}
      </Panel>
    ),
  }

  return (
    <>
      <SegBar label="보기" options={VIEWS} value={v} onChange={setV} />
      <MarketGrid blocks={[['big', cls => <BigChart className={cls} item={sel} />], ...arrange(v, VIEWS.map(o => o.key)).map((k): [string, Block] => [k, panels[k]])]} />
    </>
  )
}
