// 종목 상세 /i/<코드> (C9) — 국내 6자리 · 미국 티커. 머리(이름 · 별 · 지금 값 · 등락 · 기준) · 흐름(Yahoo 1년 일봉, Worker 경유) ·
// 알림(벨 시트 — 종목 대상 사건) · 수급(market-flows 에 그 종목이 있을 때) · 메르 언급(merblog.json, 있을 때) · 함께 볼 지표(대표 지수 2 — 겹쳐 보기).
// 이름 · 값은 묶음 행(lib/bundle.ts loadStocks)이 먼저, 없으면 일봉 끝값. 캔들 · 보조지표 · 펀더멘털은 두지 않는다(D14).
import { Fragment, useEffect, useMemo, useState } from 'react'
import { loadBundle, loadIndicator, loadRegistry, loadStocks, type RegRow, type StripItem } from '../../lib/bundle'
import { isKrStock, merMentions, type Post, type StockRow } from '../../lib/detail'
import { fmtNumber, shortDate } from '../../lib/format'
import { loadRootJson } from '../../lib/personal/data'
import { stockSeries, type StockChart } from '../../lib/personal/quotes'
import { useWatch } from '../../lib/watch'
import { AsOfBadge, NumBlock } from '../ui'
import { DivergingBars } from '../charts'
import { Panel, WatchStar } from '../panels'
import { ChangeText } from '../market/parts'
import { BellPanel, FlowPanel, Related, useCmp } from './parts'

/** 수급 묶음의 종목 한 칸(시장 › 수급 「종목별」과 같은 원천). 단위는 주. flowDates = 공매도 · 대차 · 프로그램 값의 마지막 날. */
type StockFlow = {
  investor: (string | number | null)[][]
  shortVol?: number | null; lending?: number | null; program?: number | null
  flowDates?: Partial<Record<Extra, string | null>>
}
type FlowsBundle = { views?: { stocks?: { state?: string; columns?: string[]; items?: Record<string, StockFlow> } } }
type Extra = 'shortVol' | 'lending' | 'program'
const EXTRA: { key: Extra; label: string }[] = [{ key: 'shortVol', label: '공매도' }, { key: 'lending', label: '대차' }, { key: 'program', label: '프로그램' }]
const MARKET_KO: Record<string, string> = { KOSPI: '코스피', KOSDAQ: '코스닥' }
/** 함께 볼 지표 = 대표 지수 2(국내 종목 = 코스피 · 코스닥, 미국 = S&P 500 · 나스닥). */
const PEERS = { kr: ['kospi', 'kosdaq'], us: ['sp500', 'nasdaq'] }

type Info = { row?: StockRow; flow?: StockFlow; flowState?: string; columns?: string[]; related: { reg: RegRow; item?: StripItem }[] }

export default function StockDetail({ id }: { id: string }) {
  const kr = isKrStock(id)
  const watch = useWatch()
  const [info, setInfo] = useState<Info | null>(null)
  const [chart, setChart] = useState<StockChart | null | undefined>(undefined)   // undefined = 받는 중 · null = 못 받음
  const [posts, setPosts] = useState<Post[] | null>(null)
  const [cmp, setCmp, cmpGot] = useCmp(id)

  useEffect(() => {
    let live = true
    ;(async () => {
      const [rows, flows, regs] = await Promise.all([
        loadStocks().catch(() => new Map<string, StockRow>()),
        loadBundle<FlowsBundle>('market-flows').catch(() => null),
        loadRegistry().catch(() => [] as RegRow[]),
      ])
      const peers = (kr ? PEERS.kr : PEERS.us).flatMap(p => regs.filter(r => r.id === p))
      const related = await Promise.all(peers.map(r => loadIndicator(r.id).then(x => ({ reg: r, item: x.item }), () => ({ reg: r }))))
      const st = flows?.views?.stocks
      if (live) setInfo({ row: rows.get(id), flow: st?.items?.[id], flowState: st?.state, columns: st?.columns, related })
    })().catch(() => { if (live) setInfo({ related: [] }) })
    stockSeries(id, kr).then(s => { if (live) setChart(s) }, () => { if (live) setChart(null) })
    loadRootJson<{ posts?: Post[] }>('merblog.json').then(m => { if (live) setPosts(m.posts ?? []) }, () => {})
    return () => { live = false }
  }, [id, kr])

  const row = info?.row
  const name = row?.name ?? (kr ? id : chart?.name ?? id)
  const mentions = useMemo(() => (posts ? merMentions(posts, kr ? [row?.name, row?.short] : [row?.name ?? chart?.name, id]) : []), [posts, kr, row, chart?.name, id])
  if (!info) return <p className="m-0 text-14 text-ink-3">불러오는 중</p>

  // 지금 값 · 등락: 묶음 행이 있으면 그것(화면 다른 곳과 같은 값 — 등락률만 있어 등락폭은 적지 않는다), 없으면 일봉 끝값과 그 앞 종가
  const decimals = kr ? 0 : 2
  const fromRow = row?.price != null
  const price = fromRow ? row!.price : chart?.price ?? null
  const pct = fromRow ? row!.chgPct : chart?.prev ? (chart.price / chart.prev - 1) * 100 : null
  const chg = !fromRow && chart?.prev ? chart.price - chart.prev : null
  const market = row?.market ? MARKET_KO[row.market] ?? row.market : kr ? '국내' : '미국'

  const f = info.flow
  const col = (k: string) => (info.columns ?? ['date', 'foreign', 'inst', 'retail', 'fholdRate']).indexOf(k)
  const sum = (k: string) => (f?.investor ?? []).reduce((a, r) => a + ((r[col(k)] as number | null) ?? 0), 0)
  const flowLast = f?.investor[f.investor.length - 1]?.[col('date')] as string | undefined

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <h1 className="m-0 text-24 font-bold text-ink-1 [overflow-wrap:anywhere]">{name}</h1>
          <WatchStar on={watch.has(id)} onToggle={() => watch.toggle(id)} label={name} />
        </div>
        <div className="flex flex-wrap items-end gap-x-3 gap-y-1">
          <div className="min-w-0">
            <NumBlock value={price} decimals={decimals} chg={fromRow || price == null ? undefined : chg} pct={pct} size="L" />
            {fromRow && <div className="mt-1"><ChangeText pct={pct} /></div>}
          </div>
          <AsOfBadge asOf={fromRow ? row!.asOf : chart?.asOf} state={fromRow ? row!.state : undefined} />
        </div>
        <p className="m-0 text-12 text-ink-3">
          <span className="num">{id}</span> · {market}
          {row?.amount != null && <> · 거래대금 <span className="num">{row.amount >= 1e12 ? `${fmtNumber(row.amount / 1e12, 2)}조` : `${fmtNumber(row.amount / 1e8, 0)}억`}</span></>}
          {row?.volume != null && <> · 거래량 <span className="num">{`${fmtNumber(row.volume / 1e4, row.volume < 1e5 ? 1 : 0)}만주`}</span></>}
        </p>
      </header>

      <div className="grid grid-cols-1 pc:grid-cols-12 gap-4 items-start">
        <FlowPanel className="pc:col-span-8" name={name} short={row?.short ?? (kr ? undefined : id)} pts={chart?.pts} decimals={decimals} value={price}
          base={chart?.prev != null ? { value: chart.prev, label: '전일' } : null}
          cmp={cmpGot} onCmpOff={() => setCmp('')} fail={chart === null ? '시세 흐름을 받지 못했습니다' : undefined} />

        <div className="pc:col-span-4 flex flex-col gap-4">
          <BellPanel id={id} name={name} what="이 종목이" />

          {f && f.investor.length > 0 && (
            <Panel title="수급" unit={`주 · 최근 ${f.investor.length}거래일 합`} asOf={flowLast} state={info.flowState}>
              <DivergingBars label={`${name} 투자자 순매수`} bars={[{ key: 'f', label: '외국인', value: sum('foreign') }, { key: 'i', label: '기관', value: sum('inst') }, { key: 'r', label: '개인', value: sum('retail') }]} />
              <dl className="m-0 mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-13">
                {EXTRA.map(({ key, label }) => {
                  const d = f.flowDates?.[key]
                  return (
                    <Fragment key={key}>
                      <dt className="text-ink-3">{label}</dt>
                      <dd className="m-0 text-right num text-ink-1">
                        {f[key] == null ? '—' : `${key === 'program' && f[key]! > 0 ? '+' : ''}${fmtNumber(f[key])}주`}
                        {d && <span className="ml-1 text-11 text-ink-3">{shortDate(d)}</span>}
                      </dd>
                    </Fragment>
                  )
                })}
              </dl>
            </Panel>
          )}

          {mentions.length > 0 && (
            <Panel title="메르 언급" source="메르 블로그 최근 글">
              <ul className="m-0 p-0 list-none">
                {mentions.map(m => (
                  <li key={`${m.title}-${m.date}`} className="py-1.5 border-b border-line last:border-b-0">
                    {m.href ? <a href={m.href} target="_blank" rel="noopener noreferrer" className="block text-13 text-ink-1 no-underline hover:underline [overflow-wrap:anywhere]">{m.title}</a>
                      : <span className="block text-13 text-ink-1 [overflow-wrap:anywhere]">{m.title}</span>}
                    {m.date && <span className="num text-11 text-ink-3">{shortDate(m.date)}</span>}
                    {m.snip && <p className="m-0 mt-0.5 text-12 text-ink-2 [overflow-wrap:anywhere]">{m.snip[0]}<b className="text-ink-1">{m.snip[1]}</b>{m.snip[2]}</p>}
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>

        <Related items={info.related} cmp={cmp} onCmp={setCmp} canOverlay={!!chart} />
      </div>
    </div>
  )
}
