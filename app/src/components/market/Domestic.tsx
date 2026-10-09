// 시장 › 국내 — 범위(m) 코스피·전체·코스닥·ETF × 보기 12. 보기 줄은 목차다(누르면 그 패널로 내려가고 주소 v 에 남는다).
// 패널 차례는 고정 — 큰 차트 옆 첫 자리는 거래대금. 격자 끝에 배당·실적 일정.
import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Flows, Stock, StripItem } from '../../lib/bundle'
import { fmtNumber, fmtPct, mdHm, shortDate } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { Pill, SegBar } from '../ui'
import { DivergingBars, Heatmap } from '../charts'
import { More, Panel, RankTable, type Col } from '../panels'
import { BigChart, ChangeText, counted, Empty, MarketGrid, poolOf, Toc, type Block, type BodyProps } from './parts'
import { column } from './calc'

type Mover = Stock & { volume?: number | null }
type Breadth = { up?: number; down?: number; flat?: number; limitUp?: number; limitDown?: number; as_of?: string }
type Halt = { id: string; type: string; market?: string; stage?: number; direction?: string; reason?: string; triggeredAt?: string; resumeAt?: string | null; endOfDay?: boolean; resolvedAt?: string | null }
type Movers = { kospi?: Mover[]; kosdaq?: Mover[]; state?: string }
/** KRX 순위 한 목록(시가총액·거래량 상위 · 52주 신고가·신저가): 시장별 20행. 52주 둘은 count = 해당 종목 총수(축적이 끝난 시장만). */
type KrxRow = Stock & { volume?: number | null; marketCap?: number | null; high?: number | null; low?: number | null }
type KrxRank = { asOf?: string | null; state?: string; kospi?: KrxRow[]; kosdaq?: KrxRow[]; count?: { kospi?: number; kosdaq?: number } }
/** 배당·실적 공시 한 줄(OpenDART). date = 공시 접수일·결산기준일, rcpNo = 접수번호(원문 주소). */
type CorpEvent = { date: string; code?: string; name?: string; kind?: string; title?: string; detail?: string; rcpNo?: string | null }
export type DomesticBundle = {
  strip: StripItem[]
  views?: {
    amount?: { asOf?: string; state?: string; items: (Stock & { isEtf?: boolean })[] }
    /** 토스 체결 거래대금 상위 20(두 시장이 한 목록에 섞여 온다) */
    tossAmount?: { asOf?: string; state?: string; items: (Stock & { isEtf?: boolean })[] }
    gainers?: Movers
    losers?: Movers
    etf?: { gainers?: Mover[]; losers?: Mover[]; state?: string }
    sectors?: { asOf?: string; state?: string; items: { name: string; chgPct: number | null }[] }
    flows?: Flows
    breadth?: { kospi?: Breadth; kosdaq?: Breadth; state?: string }
    halts?: { active?: Halt[]; recent?: Halt[]; asOf?: string; state?: string }
    marketCap?: KrxRank
    volume?: KrxRank
    high52?: KrxRank
    low52?: KrxRank
    corpEvents?: { asOf?: string | null; from?: string | null; state?: string; items: CorpEvent[] }
  }
}

const SCOPES = [{ key: 'kospi', label: '코스피' }, { key: 'all', label: '전체' }, { key: 'kosdaq', label: '코스닥' }, { key: 'etf', label: 'ETF' }] as const
const VIEWS = [
  { key: 'amount', label: '거래대금' }, { key: 'toss', label: '체결 Top20' }, { key: 'marketCap', label: '시가총액' }, { key: 'volume', label: '거래량' },
  { key: 'gainers', label: '상승' }, { key: 'losers', label: '하락' }, { key: 'high52', label: '52주 신고가' }, { key: 'low52', label: '52주 신저가' },
  { key: 'sectors', label: '업종' }, { key: 'flows', label: '수급' }, { key: 'breadth', label: '시장 폭' }, { key: 'halts', label: '매매중단' },
] as const
type Scope = typeof SCOPES[number]['key']
type View = typeof VIEWS[number]['key']
const MARKET: Partial<Record<Scope, string>> = { kospi: 'KOSPI', kosdaq: 'KOSDAQ' }
const HALT_TYPE: Record<string, string> = { circuit: '서킷브레이커', sidecar: '사이드카' }
const CORP_KIND: Record<string, string> = { dividend: '배당', earnings: '실적' }
const dartUrl = (rcpNo: string) => `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${encodeURIComponent(rcpNo)}`

/** 상승·하락 목록. 묶음의 kospi·kosdaq 목록에 두 시장이 섞여 오므로 합친 뒤 종목의 market 으로 다시 거른다. */
function movers(v: DomesticBundle['views'], kind: 'gainers' | 'losers', scope: Scope): Mover[] {
  if (scope === 'etf') return v?.etf?.[kind] ?? []
  const seen = new Set<string>()
  const all = [...(v?.[kind]?.kospi ?? []), ...(v?.[kind]?.kosdaq ?? [])].filter(x => !seen.has(x.code) && !!seen.add(x.code))
  const sign = kind === 'gainers' ? -1 : 1
  return all.filter(x => !MARKET[scope] || x.market === MARKET[scope]).sort((a, b) => sign * ((a.chgPct ?? 0) - (b.chgPct ?? 0)))
}

const nameCol: Col<Stock> = { key: 'name', label: '종목', get: r => r.short || r.name, role: 'name' }
// 범위가 전체일 때: 종목 이름 아래 작은 글씨로 시장(코스피·코스닥)을 단다 — 열을 늘리지 않는다
const MARKET_KO: Record<string, string> = { KOSPI: '코스피', KOSDAQ: '코스닥' }
const nameMarketCol: Col<Mover> = { ...nameCol, render: r => <>{r.short || r.name}{r.market && <span className="block text-11 font-normal text-ink-3">{MARKET_KO[r.market] ?? r.market}</span>}</> }
const priceCol: Col<Stock> = { key: 'price', label: '현재가', get: r => r.price, num: true, role: 'value' }
const pctCol: Col<Stock> = { key: 'pct', label: '등락률', get: r => r.chgPct, num: true, role: 'change', render: r => <ChangeText pct={r.chgPct} /> }
const amountCols: Col<Stock>[] = [nameCol, priceCol, pctCol,
  { key: 'amount', label: '거래대금', get: r => (r.amount == null ? null : r.amount / 1e12), num: true, role: 'sub', render: r => (r.amount == null ? null : `${fmtNumber(r.amount / 1e12, 2)}조`) }]
// 토스 체결액은 억 단위(상위 20 이 수백억~수천억이다)
const tossCols: Col<Stock>[] = [nameCol, priceCol, pctCol,
  { key: 'amount', label: '체결액', get: r => r.amount, num: true, role: 'sub', render: r => (r.amount == null ? null : `${fmtNumber(r.amount / 1e8)}억`) }]
// 상승·하락: 종목 · 현재가 · 등락률 · 거래량(만주) 넷 — PC 둘째 줄 4칸(약 350px)에 맞춘다. 범위가 전체면 시장은 종목 이름 아래에 단다.
const moverCols = (all: boolean): Col<Mover>[] => [all ? nameMarketCol : nameCol, priceCol, pctCol, volCol]

/** KRX 순위 목록을 범위대로. 전체 = 두 시장을 합쳐 by 큰 순, ETF = 없음(KRX 주식 일별표라 ETF 가 들어 있지 않다). */
function krxRows(r: KrxRank | undefined, scope: Scope, by: (x: KrxRow) => number | null | undefined): KrxRow[] {
  if (scope === 'etf') return []
  if (scope !== 'all') return r?.[scope] ?? []
  return [...(r?.kospi ?? []), ...(r?.kosdaq ?? [])].sort((a, b) => (by(b) ?? -Infinity) - (by(a) ?? -Infinity))
}
/** 52주 해당 종목 수. 전체는 두 시장 다 축적이 끝났을 때만 합친다(한쪽만 더하면 적게 센다). */
function krxCount(c: KrxRank['count'], scope: Scope): number | undefined {
  if (scope === 'etf') return undefined
  if (scope !== 'all') return c?.[scope]
  return c?.kospi != null && c?.kosdaq != null ? c.kospi + c.kosdaq : undefined
}

const capCol: Col<KrxRow> = { key: 'cap', label: '시가총액', get: r => (r.marketCap == null ? null : r.marketCap / 1e12), num: true, role: 'sub', render: r => (r.marketCap == null ? null : `${fmtNumber(r.marketCap / 1e12, 1)}조`) }
// 거래량은 만주 4자리 안(10만주 밑은 소수 한 자리 — 8,343주가 「1만주」로 반올림되지 않게)
const volCol: Col<KrxRow> = { key: 'vol', label: '거래량', get: r => r.volume, num: true, role: 'sub', render: r => (r.volume == null ? null : `${fmtNumber(r.volume / 1e4, r.volume < 1e5 ? 1 : 0)}만주`) }
const KRX_VIEWS: Record<'marketCap' | 'volume' | 'high52' | 'low52', { title: string; cols: Col<KrxRow>[]; by: (r: KrxRow) => number | null | undefined }> = {
  marketCap: { title: '시가총액 상위', cols: [nameCol, priceCol, pctCol, capCol], by: r => r.marketCap },
  volume: { title: '거래량 상위', cols: [nameCol, priceCol, pctCol, volCol], by: r => r.volume },
  high52: { title: '52주 신고가', cols: [nameCol, priceCol, pctCol, { key: 'high', label: '52주 최고', get: r => r.high, num: true }], by: r => r.marketCap },
  low52: { title: '52주 신저가', cols: [nameCol, priceCol, pctCol, { key: 'low', label: '52주 최저', get: r => r.low, num: true }], by: r => r.marketCap },
}
type KrxView = keyof typeof KRX_VIEWS

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
  const [, setV] = useViewParam<View>('v', 'amount', VIEWS.map(o => o.key))
  const [sector, setSector] = useState<{ name: string; value: number | null } | null>(null)
  const toStock = useToStock()
  const vw = b.views
  const inv = vw?.flows
  const invCol = (k: string) => (inv?.columns ?? ['date', 'foreign', 'inst', 'retail']).indexOf(k)
  // 띠의 외국인 칸은 시계열이 없으니 투자자 매매 20거래일로 채운다
  const ff = b.strip.find(x => x.id === 'flow_foreign')
  const pool = poolOf(b.strip, ff && [{ ...ff, series: column(inv?.rows ?? [], invCol('foreign')) }])
  const sel = pool.get(selId) ?? b.strip[0]
  const scopeName = SCOPES.find(o => o.key === m)!.label
  const flow20 = (inv?.rows || []).slice(-20)
  // KRX 순위가 하나라도 들어왔는지 — 52주가 비었을 때 「축적 중」인지 「KRX 자체가 아직」인지 가른다
  const krxOn = (['marketCap', 'volume'] as const).some(k => vw?.[k]?.kospi?.length || vw?.[k]?.kosdaq?.length)
  const krxPanel = (k: KrxView) => (cls: string, primary: boolean) => {
    const { title, cols, by } = KRX_VIEWS[k]
    const r = vw?.[k]
    const rows = krxRows(r, m, by)
    const is52 = k === 'high52' || k === 'low52'
    const cnt = is52 ? krxCount(r?.count, m) : undefined
    const empty = m === 'etf' ? `${title} 자료에는 ETF 가 없습니다.`
      : !is52 ? `${title} 자료가 없습니다.`
        : cnt != null ? `오늘 ${title} 종목이 없습니다.`
          : krxOn ? '52주 고저 축적 중(약 3일 뒤 게재)' : 'KRX 자료 수집 대기 · 들어온 뒤 약 3일이면 52주 목록이 실립니다.'
    return (
      <Panel className={cls} title={`${title} · ${scopeName}`} source={cnt != null ? `해당 ${fmtNumber(cnt)}종목` : undefined}
        asOf={r?.asOf} state={r?.state} fold={!primary}>
        {rows.length ? <RankTable label={`${title} 종목`} cols={cols} rows={rows.slice(0, primary ? 20 : 10)} rowKey={x => x.code} onPick={toStock} />
          : <Empty>{empty}</Empty>}
      </Panel>
    )
  }
  const ce = vw?.corpEvents
  const corpPanel = (cls: string) => (
    <Panel className={cls} title="배당·실적 일정" source={ce?.from ? `${shortDate(ce.from)}부터` : undefined} asOf={ce?.asOf} state={ce?.state} fold>
      {ce?.items.length ? <More rows={ce.items.slice(0, 10)} name="배당·실적 일정">{shown => (
        <ul className="m-0 p-0 list-none">
          {shown.map((e, i) => (
            <li key={`${e.code}-${e.date}-${e.kind}-${i}`} className="py-1.5 border-b border-line last:border-b-0">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-13">
                <Pill tone="o">{CORP_KIND[e.kind ?? ''] ?? '공시'}</Pill>
                <span className="num text-12 text-ink-3">{shortDate(e.date)}</span>
                <span className="font-bold text-ink-1">{e.name ?? e.code}</span>
                {e.title && <span className="text-ink-2">{e.title}</span>}
              </div>
              {(e.detail || e.rcpNo) && (
                <p className="m-0 mt-0.5 text-12 text-ink-3">
                  {e.detail}{e.detail && e.rcpNo ? ' · ' : ''}
                  {e.rcpNo && <a href={dartUrl(e.rcpNo)} target="_blank" rel="noopener noreferrer" className="text-ink-2 hover:text-ink-1">원문</a>}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}</More> : <Empty>관심 종목 공시 없음</Empty>}
      {ce && ce.items.length > 10 && <p className="m-0 mt-2 text-11 text-ink-3">최근 10건 · 전체 {ce.items.length}건</p>}
    </Panel>
  )

  const panels: Record<View, (cls: string, primary: boolean) => ReactNode> = {
    amount: (cls, primary) => {
      const items = vw?.amount?.items ?? []
      const rows = items.filter(x => (m === 'etf' ? x.isEtf : !MARKET[m] || x.market === MARKET[m]))
      return (
        <Panel className={cls} title={`거래대금 상위 · ${scopeName}`} asOf={vw?.amount?.asOf} state={vw?.amount?.state} fold={!primary}>
          {rows.length ? <RankTable label="거래대금 상위 종목" cols={amountCols} rows={rows.slice(0, primary ? 20 : 10)} rowKey={r => r.code} onPick={toStock} />
            : <Empty>{items.length ? '이 범위의 종목이 거래대금 상위 20에 없습니다.' : '거래대금 자료가 없습니다.'}</Empty>}
        </Panel>
      )
    },
    toss: (cls, primary) => {
      const t = vw?.tossAmount
      const rows = (t?.items ?? []).filter(x => (m === 'etf' ? x.isEtf : !MARKET[m] || x.market === MARKET[m]))
      return (
        <Panel className={cls} title={`체결 Top20 · ${scopeName}`} source="토스증권 체결 기준" asOf={t?.asOf} state={t?.state} fold={!primary}>
          {rows.length ? <RankTable label="토스 체결 상위 종목" cols={tossCols} rows={rows} rowKey={r => r.code} onPick={toStock} />
            : <Empty>{t?.items.length ? '이 범위의 종목이 체결 상위 20에 없습니다.' : '체결 상위 자료가 없습니다.'}</Empty>}
        </Panel>
      )
    },
    marketCap: krxPanel('marketCap'),
    volume: krxPanel('volume'),
    high52: krxPanel('high52'),
    low52: krxPanel('low52'),
    gainers: (cls, primary) => <MoverPanel cls={cls} primary={primary} all={m === 'all'} title={`상승 · ${scopeName}`} rows={movers(vw, 'gainers', m)} state={m === 'etf' ? vw?.etf?.state : vw?.gainers?.state} />,
    losers: (cls, primary) => <MoverPanel cls={cls} primary={primary} all={m === 'all'} title={`하락 · ${scopeName}`} rows={movers(vw, 'losers', m)} state={m === 'etf' ? vw?.etf?.state : vw?.losers?.state} />,
    sectors: (cls, primary) => (
      <Panel className={cls} title={`업종 ${vw?.sectors?.items.length ?? ''}`} asOf={vw?.sectors?.asOf} state={vw?.sectors?.state} fold={!primary}>
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
      <Panel className={cls} title="투자자 매매" unit={inv?.unit} source={inv?.market} asOf={inv?.asOf} state={inv?.state} fold={!primary}>
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
        <Panel className={cls} title="시장 폭" asOf={br?.kospi?.as_of ?? br?.kosdaq?.as_of} state={br?.state} fold={!primary}>
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
        <Panel className={cls} title="매매중단" asOf={h?.asOf} state={h?.state} fold={!primary}>
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
      <SegBar label="범위" options={SCOPES} value={m} onChange={counted('국내 범위', SCOPES, setM)} />
      <Toc where="국내" items={VIEWS} onPick={setV} />
      <MarketGrid blocks={[['big', cls => <BigChart className={cls} item={sel} />], ...VIEWS.map((o): [string, Block] => [o.key, panels[o.key]]), ['corp', corpPanel]]} />
    </>
  )
}

/** 순위 표 행 → 종목 상세(#/i/<코드>). 모바일 시트 대신 상세로 간다. */
function useToStock() {
  const nav = useNavigate()
  return (r: { code: string }) => nav(`/i/${r.code}`)
}

function MoverPanel({ cls, primary, all, title, rows, state }: { cls: string; primary: boolean; all: boolean; title: string; rows: Mover[]; state?: string }) {
  const toStock = useToStock()
  return (
    <Panel className={cls} title={title} state={state} fold={!primary}>
      {rows.length ? <RankTable label={title} cols={moverCols(all)} rows={rows.slice(0, 10)} rowKey={r => r.code} onPick={toStock} />
        : <Empty>이 범위의 종목이 목록에 없습니다.</Empty>}
    </Panel>
  )
}
