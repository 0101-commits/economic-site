// 시장 › 국내 — 범위(m) 코스피·전체·코스닥·ETF × 보기(v) 7. 고른 보기 패널이 큰 차트 옆 첫 자리로 온다.
import { useState, type ReactNode } from 'react'
import type { Flows, Stock, StripItem } from '../../lib/bundle'
import { fmtNumber, fmtPct, mdHm, shortDate } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { SegBar } from '../ui'
import { DivergingBars, Heatmap } from '../charts'
import { Panel, RankTable, type Col } from '../panels'
import { arrange, BigChart, ChangeText, Empty, MarketGrid, poolOf, type BodyProps } from './parts'
import { column } from './calc'

type Mover = Stock & { volume?: number | null }
type Breadth = { up?: number; down?: number; flat?: number; limitUp?: number; limitDown?: number; as_of?: string }
type Halt = { id: string; type: string; market?: string; stage?: number; direction?: string; reason?: string; triggeredAt?: string; resumeAt?: string | null; endOfDay?: boolean; resolvedAt?: string | null }
type Movers = { kospi?: Mover[]; kosdaq?: Mover[]; state?: string }
export type DomesticBundle = {
  strip: StripItem[]
  views?: {
    amount?: { asOf?: string; state?: string; items: Stock[] }
    gainers?: Movers
    losers?: Movers
    etf?: { gainers?: Mover[]; losers?: Mover[]; state?: string }
    sectors?: { asOf?: string; state?: string; items: { name: string; chgPct: number | null }[] }
    flows?: Flows
    breadth?: { kospi?: Breadth; kosdaq?: Breadth; state?: string }
    halts?: { active?: Halt[]; recent?: Halt[]; asOf?: string; state?: string }
  }
}

const SCOPES = [{ key: 'kospi', label: '코스피' }, { key: 'all', label: '전체' }, { key: 'kosdaq', label: '코스닥' }, { key: 'etf', label: 'ETF' }] as const
const VIEWS = [
  { key: 'amount', label: '거래대금' }, { key: 'gainers', label: '상승' }, { key: 'losers', label: '하락' }, { key: 'sectors', label: '업종' },
  { key: 'flows', label: '수급' }, { key: 'breadth', label: '시장 폭' }, { key: 'halts', label: '매매중단' },
] as const
type Scope = typeof SCOPES[number]['key']
type View = typeof VIEWS[number]['key']
const MARKET: Partial<Record<Scope, string>> = { kospi: 'KOSPI', kosdaq: 'KOSDAQ' }
const HALT_TYPE: Record<string, string> = { circuit: '서킷브레이커', sidecar: '사이드카' }

/** 상승·하락 목록. 묶음의 kospi·kosdaq 목록에 두 시장이 섞여 오므로 합친 뒤 종목의 market 으로 다시 거른다. */
function movers(v: DomesticBundle['views'], kind: 'gainers' | 'losers', scope: Scope): Mover[] {
  if (scope === 'etf') return v?.etf?.[kind] ?? []
  const seen = new Set<string>()
  const all = [...(v?.[kind]?.kospi ?? []), ...(v?.[kind]?.kosdaq ?? [])].filter(x => !seen.has(x.code) && !!seen.add(x.code))
  const sign = kind === 'gainers' ? -1 : 1
  return all.filter(x => !MARKET[scope] || x.market === MARKET[scope]).sort((a, b) => sign * ((a.chgPct ?? 0) - (b.chgPct ?? 0)))
}

const nameCol: Col<Stock> = { key: 'name', label: '종목', get: r => r.short || r.name, role: 'name' }
const priceCol: Col<Stock> = { key: 'price', label: '현재가', get: r => r.price, num: true, role: 'value' }
const pctCol: Col<Stock> = { key: 'pct', label: '등락률', get: r => r.chgPct, num: true, role: 'change', render: r => <ChangeText pct={r.chgPct} /> }
const amountCols: Col<Stock>[] = [nameCol, priceCol, pctCol,
  { key: 'amount', label: '거래대금', get: r => (r.amount == null ? null : r.amount / 1e12), num: true, role: 'sub', render: r => (r.amount == null ? null : `${fmtNumber(r.amount / 1e12, 2)}조`) }]
const moverCols: Col<Mover>[] = [nameCol, { key: 'market', label: '시장', get: r => r.market, role: 'sub' }, priceCol, pctCol,
  { key: 'volume', label: '거래량', get: r => r.volume, num: true }]

/** 상승/하락/보합 종목 수 막대 한 줄 + 상·하한. */
function BreadthRow({ name, b }: { name: string; b?: Breadth }) {
  if (!b || b.up == null || b.down == null) return <li className="text-13 text-ink-3">{name} 자료 없음</li>
  const total = b.up + b.down + (b.flat ?? 0) || 1
  const w = (x = 0) => `${(x / total) * 100}%`
  return (
    <li className="flex flex-col gap-1">
      <div className="flex flex-wrap items-baseline gap-x-2 text-13">
        <span className="font-bold text-ink-1">{name}</span>
        <span className="num text-up">상승 {fmtNumber(b.up)}</span>
        <span className="num text-down">하락 {fmtNumber(b.down)}</span>
        <span className="num text-ink-3">보합 {fmtNumber(b.flat)}</span>
        {(b.limitUp != null || b.limitDown != null) && <span className="num text-11 text-ink-3">상한 {b.limitUp ?? '—'} · 하한 {b.limitDown ?? '—'}</span>}
      </div>
      <div role="img" aria-label={`${name} 상승 ${b.up}, 보합 ${b.flat ?? 0}, 하락 ${b.down}`} className="flex h-3 rounded-chip overflow-hidden bg-line">
        <span className="bg-up-fill" style={{ width: w(b.up) }} />
        <span style={{ width: w(b.flat) }} />
        <span className="bg-down-fill" style={{ width: w(b.down) }} />
      </div>
    </li>
  )
}

export default function Domestic({ b, selId, setS }: BodyProps<DomesticBundle>) {
  const [m, setM] = useViewParam<Scope>('m', 'kospi', SCOPES.map(o => o.key))
  const [v, setV] = useViewParam<View>('v', 'amount', VIEWS.map(o => o.key))
  const [sector, setSector] = useState<{ name: string; value: number | null } | null>(null)
  const vw = b.views
  const inv = vw?.flows
  const invCol = (k: string) => (inv?.columns ?? ['date', 'foreign', 'inst', 'retail']).indexOf(k)
  // 띠의 외국인 칸은 시계열이 없으니 투자자 매매 20거래일로 채운다
  const ff = b.strip.find(x => x.id === 'flow_foreign')
  const pool = poolOf(b.strip, ff && [{ ...ff, series: column(inv?.rows ?? [], invCol('foreign')) }])
  const sel = pool.get(selId) ?? b.strip[0]
  const scopeName = SCOPES.find(o => o.key === m)!.label
  const flow20 = (inv?.rows || []).slice(-20)

  const panels: Record<View, (cls: string, primary: boolean) => ReactNode> = {
    amount: (cls, primary) => {
      const rows = (vw?.amount?.items ?? []).filter(x => !MARKET[m] || x.market === MARKET[m])
      return (
        <Panel className={cls} title={`거래대금 상위 · ${scopeName}`} asOf={vw?.amount?.asOf} state={vw?.amount?.state} fold={primary ? undefined : 'mobile'}>
          {m === 'etf' ? <Empty>거래대금 상위 자료에는 ETF 구분이 없습니다.</Empty>
            : rows.length ? <RankTable label="거래대금 상위 종목" cols={amountCols} rows={rows.slice(0, primary ? 20 : 10)} rowKey={r => r.code} />
              : <Empty>거래대금 자료가 없습니다.</Empty>}
        </Panel>
      )
    },
    gainers: (cls, primary) => <MoverPanel cls={cls} primary={primary} title={`상승 · ${scopeName}`} rows={movers(vw, 'gainers', m)} state={m === 'etf' ? vw?.etf?.state : vw?.gainers?.state} />,
    losers: (cls, primary) => <MoverPanel cls={cls} primary={primary} title={`하락 · ${scopeName}`} rows={movers(vw, 'losers', m)} state={m === 'etf' ? vw?.etf?.state : vw?.losers?.state} />,
    sectors: (cls, primary) => (
      <Panel className={cls} title={`업종 ${vw?.sectors?.items.length ?? ''}`} asOf={vw?.sectors?.asOf} state={vw?.sectors?.state} fold={primary ? undefined : 'mobile'}>
        {vw?.sectors?.items.length ? (
          <>
            <Heatmap label="업종 등락률" minCell={primary ? 72 : 56} cells={vw.sectors.items.map(x => ({ key: x.name, name: x.name, value: x.chgPct }))}
              onPick={c => setSector(s => (s?.name === c.name ? null : { name: c.name, value: c.value }))} />
            {sector && (
              <p className="m-0 mt-2 text-13 text-ink-2">
                <b className="text-ink-1">{sector.name}</b> <span className="num">{fmtPct(sector.value)}</span> · 업종별 종목 목록은 아직 묶음에 없습니다.
              </p>
            )}
          </>
        ) : <Empty>업종 자료가 없습니다.</Empty>}
      </Panel>
    ),
    flows: (cls, primary) => (
      <Panel className={cls} title="투자자 매매" unit={inv?.unit} source={inv?.market} asOf={inv?.asOf} state={inv?.state} fold={primary ? undefined : 'mobile'}>
        {inv?.today ? (
          <div className="flex flex-col gap-4">
            <DivergingBars label={`오늘 ${inv.market ?? ''} 투자자별 순매수(${inv.unit ?? ''})`} bars={[
              { key: 'foreign', label: '외국인', value: inv.today.foreign },
              { key: 'inst', label: '기관', value: inv.today.inst },
              { key: 'retail', label: '개인', value: inv.today.retail },
            ]} />
            {flow20.length > 1 && (
              <div>
                <p className="m-0 mb-1 text-12 text-ink-2">외국인 {flow20.length}거래일</p>
                <DivergingBars vertical label={`외국인 ${flow20.length}거래일 순매수`}
                  bars={flow20.map(r => ({ key: String(r[0]), label: shortDate(String(r[0])), value: r[invCol('foreign')] as number | null }))} />
                <div className="flex justify-between mt-1 text-11 text-ink-3 num">
                  <span>{shortDate(String(flow20[0][0]))}</span><span>{shortDate(String(flow20[flow20.length - 1][0]))}</span>
                </div>
              </div>
            )}
          </div>
        ) : <Empty>수급 자료가 없습니다.</Empty>}
      </Panel>
    ),
    breadth: (cls, primary) => {
      const br = vw?.breadth
      return (
        <Panel className={cls} title="시장 폭" asOf={br?.kospi?.as_of ?? br?.kosdaq?.as_of} state={br?.state} fold={primary ? undefined : 'mobile'}>
          <ul className="m-0 p-0 list-none flex flex-col gap-3">
            {m !== 'kosdaq' && <BreadthRow name="코스피" b={br?.kospi} />}
            {m !== 'kospi' && <BreadthRow name="코스닥" b={br?.kosdaq} />}
          </ul>
        </Panel>
      )
    },
    halts: (cls, primary) => {
      const h = vw?.halts
      return (
        <Panel className={cls} title="매매중단" asOf={h?.asOf} state={h?.state} fold={primary ? undefined : 'always'}>
          <p className="m-0 mb-2 text-13 text-ink-2">{h?.active?.length ? `지금 발동 ${h.active.length}건` : '지금 발동 중인 매매중단은 없습니다.'}</p>
          {[...(h?.active ?? []), ...(h?.recent ?? [])].length ? (
            <ul className="m-0 p-0 list-none">
              {[...(h?.active ?? []), ...(h?.recent ?? [])].map((x, i) => (
                <li key={`${x.id}-${i}`} className="flex flex-wrap items-baseline gap-x-2 py-1.5 border-b border-line last:border-b-0 text-13">
                  <span className="num text-12 text-ink-3">{x.triggeredAt ? mdHm(x.triggeredAt) : '—'}</span>
                  <span className="text-ink-1">{x.market} {HALT_TYPE[x.type] ?? x.type}{x.stage ? ` ${x.stage}단계` : ''}</span>
                  {x.reason && <span className="text-12 text-ink-2">{x.reason}</span>}
                </li>
              ))}
            </ul>
          ) : null}
        </Panel>
      )
    },
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <SegBar label="범위" options={SCOPES} value={m} onChange={setM} />
        <SegBar label="보기" options={VIEWS} value={v} onChange={setV} />
      </div>
      <MarketGrid blocks={[cls => <BigChart className={cls} item={sel} />, ...arrange(v, VIEWS.map(o => o.key)).map(k => panels[k])]} />
    </>
  )
}

function MoverPanel({ cls, primary, title, rows, state }: { cls: string; primary: boolean; title: string; rows: Mover[]; state?: string }) {
  return (
    <Panel className={cls} title={title} state={state} fold={primary ? undefined : 'mobile'}>
      {rows.length ? <RankTable label={title} cols={moverCols} rows={rows.slice(0, 10)} rowKey={r => r.code} />
        : <Empty>이 범위의 종목이 목록에 없습니다.</Empty>}
    </Panel>
  )
}
