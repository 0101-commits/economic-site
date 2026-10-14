// 종목 상세 /i/<코드> (C9 · 구조 개편 과제 2 · 3) — 국내 6자리 · 미국 티커.
// 머리: 「005930 · 코스피 · 거래대금 2위」 / 이름 · 별 / 지금 값 / 「▲4,000원 (1.72%)」 / 「어제보다 · 기준 시각 · 장 상태」(기준 시각은 여기 한 곳).
// 머리 아래 「왜 움직였나」(묶음 home.reasons — 근거가 있을 때만) → 흐름(Yahoo 1년 일봉, Worker 경유) · 알림(벨 시트) · 이 종목 공시(market-domestic corpEvents) ·
// 수급(market-flows 에 그 종목이 있을 때) · 메르 언급(merblog.json — 「메르 글 찾기」를 누를 때만 받는다) · 함께 볼 것(같은 시장 지수 1 + 거래대금 이웃 2 — 지수만 겹쳐 보기).
// 이름 · 값은 묶음 행(lib/bundle.ts loadStocks)이 먼저, 없거나 일봉보다 오래면 일봉 끝값. 등락폭은 전일 종가(묶음 행 → 같은 날 일봉, lib/detail.ts headPrev)로만.
// 묶음을 다시 읽으면(rev) 묶음 쪽 값만 다시 찾는다(일봉은 그대로). 캔들 · 보조지표 · 펀더멘털은 두지 않는다(D14).
import { Fragment, useEffect, useMemo, useState } from 'react'
import { loadBundle, loadHome, loadIndicator, loadRegistry, loadStocks, useBundleRev, type MarketState, type RegRow, type StripItem } from '../../lib/bundle'
import { changeLine, headChange, headPrev, headVolume, isKrStock, merMentions, merNames, rankNeighbors, reasonOf, type Post, type Reason, type StockRow } from '../../lib/detail'
import { changeDir, fmtNumber, fmtShares, shortDate } from '../../lib/format'
import { kstDay } from '../../lib/personal/calc'
import { loadRootJson } from '../../lib/personal/data'
import { chartBasis, stockSeries, type StockChart } from '../../lib/personal/quotes'
import { useWatch } from '../../lib/watch'
import { AsOfBadge, NumBlock, Pill } from '../ui'
import { DivergingBars } from '../charts'
import { Panel, WatchStar } from '../panels'
import { BellPanel, FlowPanel, Related, useCmp } from './parts'
import { BTN2 } from '../personal/bits'

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
const DIR_TEXT = { up: 'text-up', down: 'text-down', flat: 'text-ink-2' } as const
/** 공시(market-domestic views.corpEvents — 시장 › 국내 「배당·실적 일정」과 같은 원천). rcpNo = OpenDART 접수번호. */
type CorpEvent = { date: string; code: string; kind?: string; title?: string; detail?: string; rcpNo?: string }
type DomBundle = { views?: { corpEvents?: { asOf?: string | null; state?: string; items?: CorpEvent[] } } }
const CORP_KIND: Record<string, string> = { dividend: '배당', earnings: '실적' }
const dartUrl = (rcpNo: string) => `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${encodeURIComponent(rcpNo)}`
const CHIP = 'inline-flex items-center gap-1 min-h-7 px-2.5 py-0.5 rounded-chip border border-line text-12 text-ink-2 [overflow-wrap:anywhere]'

type Info = {
  row?: StockRow; flow?: StockFlow; flowState?: string; columns?: string[]; related: { reg: RegRow; item?: StripItem }[]
  rank?: number; reason: Reason | null; events: CorpEvent[]; eventsAt?: { asOf?: string | null; state?: string }; mkLabel?: string
}

export default function StockDetail({ id }: { id: string }) {
  const kr = isKrStock(id)
  const watch = useWatch()
  const rev = useBundleRev()
  const [info, setInfo] = useState<Info | null>(null)
  const [chart, setChart] = useState<StockChart | null | undefined>(undefined)   // undefined = 받는 중 · null = 못 받음
  const [posts, setPosts] = useState<Post[] | null>(null)
  // merblog.json(1.5MB)은 단추를 눌렀을 때만 받는다 — 칸이 보일 때 받기는 PC · 모바일 모두 첫 그림에 칸이 들어와(일봉이 오기 전) 첫 열기마다 받았다
  const [mer, setMer] = useState<'idle' | 'want' | 'fail'>('idle')
  const [cmp, setCmp, cmpGot] = useCmp(id)

  useEffect(() => {
    let live = true
    ;(async () => {
      const [rows, flows, regs, home, dom] = await Promise.all([
        loadStocks().catch(() => new Map<string, StockRow>()),
        loadBundle<FlowsBundle>('market-flows').catch(() => null),
        loadRegistry().catch(() => [] as RegRow[]),
        loadHome(false).catch(() => null),
        loadBundle<DomBundle>('market-domestic').catch(() => null),
      ])
      const row = rows.get(id)
      // 함께 볼 것: 같은 시장 지수 1(국내 = 코스피 · 코스닥, 미국 = S&P 500) + 거래대금 순위 이웃 2(값은 그 목록 것 — 겹쳐 볼 시계열은 없다)
      const idx = regs.find(r => r.id === (kr ? (row?.market === 'KOSDAQ' ? 'kosdaq' : 'kospi') : 'sp500'))
      const index = idx ? [await loadIndicator(idx.id).then(x => ({ reg: idx, item: x.item }), () => ({ reg: idx }))] : []
      const ta = home?.topAmount
      const amount = ta?.items ?? []
      const near = rankNeighbors(amount, id).map(s => ({
        reg: { id: s.code, label: s.name, short: s.short, shortM: s.shortM, decimals: 0, asset: 'stock' } as RegRow,
        item: { id: s.code, label: s.name, decimals: 0, value: s.price, change: null, changePct: s.chgPct, asOf: ta?.asOf ?? null, state: ta?.state, liveUntil: ta?.liveUntil },
      }))
      const rank = amount.findIndex(x => x.code === id)
      const ce = dom?.views?.corpEvents
      const events = (ce?.items ?? []).filter(e => e.code === id).sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0)).slice(0, 5)
      // 장 상태: 국내 = 묶음 market.label, 미국 = market.us.label(묶음에 있을 때만 — C1)
      const mk = home?.market as (MarketState & { us?: { label?: string } }) | undefined
      const st = flows?.views?.stocks
      if (live) setInfo({
        row, flow: st?.items?.[id], flowState: st?.state, columns: st?.columns, related: [...index, ...near],
        rank: rank >= 0 ? rank + 1 : undefined, reason: reasonOf((home as { reasons?: unknown } | null)?.reasons, id, kstDay()),
        events, eventsAt: ce ? { asOf: ce.asOf, state: ce.state } : undefined, mkLabel: kr ? mk?.label : mk?.us?.label,
      })
    })().catch(() => { if (live) setInfo(i => i ?? { related: [], reason: null, events: [] }) })   // 다시 읽기 실패는 그린 것을 그대로 둔다
    return () => { live = false }
  }, [id, kr, rev])
  useEffect(() => {
    let live = true
    stockSeries(id, kr).then(s => { if (live) setChart(s) }, () => { if (live) setChart(null) })
    return () => { live = false }
  }, [id, kr])
  useEffect(() => {
    if (mer !== 'want' || posts) return
    let live = true
    loadRootJson<{ posts?: Post[] }>('merblog.json').then(m => { if (live) setPosts(m.posts ?? []) }, () => { if (live) setMer('fail') })
    return () => { live = false }
  }, [mer, posts])

  const row = info?.row
  const name = row?.name ?? (kr ? id : chart?.name ?? id)
  const mentions = useMemo(() => (posts ? merMentions(posts, merNames(kr, id, kr ? row?.name : row?.name ?? chart?.name, row?.short)) : []), [posts, kr, row, chart?.name, id])
  if (!info) return <p className="m-0 text-14 text-ink-3">불러오는 중</p>

  // 지금 값: 묶음 행이 있으면 그것(화면 다른 곳과 같은 값), 없으면 일봉 끝값.
  // 일봉이 있는데 행에 기준 시각이 없거나 행 날짜가 일봉 마지막 체결 날짜보다 앞이면(이어 쓴 지난 목록) 일봉 쪽. 행 기준 시각은 묶음 보기의 asOf(상승 · 하락 · ETF 포함).
  // 등락: 묶음 행은 등락률, 원 단위 등락폭은 전일 종가가 있을 때만(headPrev — 등락률로 거꾸로 구하지 않는다).
  const decimals = kr ? 0 : 2
  const chartDay = chart?.asOf ? kstDay(new Date(chart.asOf)) : null
  const fromRow = row?.price != null && !(chart && (!row.asOf || (chartDay != null && row.asOf.slice(0, 10) < chartDay)))
  const price = fromRow ? row!.price : chart?.price ?? null
  const { chg, pct } = headChange(price, headPrev(row, fromRow, chart), fromRow ? row!.chgPct : null)
  const dir = chg != null ? changeDir(chg, decimals) : changeDir(pct, 2)
  const basis = fromRow ? { asOf: row!.asOf, state: row!.state, liveUntil: row!.liveUntil } : chart ? chartBasis(chart) : null
  const market = row?.market ? MARKET_KO[row.market] ?? row.market : kr ? '국내' : '미국'
  const vol = headVolume(row, fromRow, chart?.vol)   // 묶음 행에 없으면 머리 값과 같은 날의 일봉 거래량
  const amt = fromRow && row?.amount != null ? row.amount : null
  const why = info.reason

  const f = info.flow
  const col = (k: string) => (info.columns ?? ['date', 'foreign', 'inst', 'retail', 'fholdRate']).indexOf(k)
  const sum = (k: string) => (f?.investor ?? []).reduce((a, r) => a + ((r[col(k)] as number | null) ?? 0), 0)
  const flowLast = f?.investor[f.investor.length - 1]?.[col('date')] as string | undefined

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <p className="m-0 text-12 text-ink-3">
          <span className="num">{id}</span> · {market}{info.rank != null && <> · 거래대금 <span className="num">{info.rank}</span>위</>}
        </p>
        <div className="flex items-center gap-2">
          <h1 className="m-0 text-24 font-bold text-ink-1 [overflow-wrap:anywhere]">{name}</h1>
          <WatchStar on={watch.has(id)} onToggle={() => watch.toggle(id)} label={name} />
        </div>
        <NumBlock value={price} decimals={decimals} size="L" />
        {price != null && <p className={`m-0 num text-14 ${DIR_TEXT[dir]}`}>{changeLine(chg, pct, decimals, kr ? '원' : '달러')}</p>}
        <p className="m-0 text-12 text-ink-3">
          어제보다{basis?.asOf && <> · <AsOfBadge {...basis} /></>}{info.mkLabel && <> · {info.mkLabel}</>}
        </p>
        {(amt != null || vol) && (
          <p className="m-0 text-12 text-ink-3">
            {amt != null && <>거래대금 <span className="num">{amt >= 1e12 ? `${fmtNumber(amt / 1e12, 2)}조` : `${fmtNumber(amt / 1e8, 0)}억`}</span>{row!.amountAt && <> <AsOfBadge asOf={row!.amountAt.asOf} state={row!.amountAt.state} liveUntil={row!.amountAt.liveUntil} /></>}</>}
            {amt != null && vol && ' · '}
            {vol && <>거래량 <span className="num">{fmtShares(vol.value)}</span>
              {vol.at ? <> <AsOfBadge asOf={vol.at.asOf} state={vol.at.state} liveUntil={vol.at.liveUntil} /></> : vol.fromChart && fromRow && chart && <> <AsOfBadge {...chartBasis(chart)} /></>}</>}
          </p>
        )}
      </header>

      {/* 왜 움직였나 — 규칙이 고른 재료(지수 · 공시 · 기사 · 52주)로 쓴 추정 한 줄. 근거 칩은 원문으로(주소가 없으면 글자만). 근거 0 이면 칸이 없다 */}
      {why && (
        <Panel title="왜 움직였나" source={<>추정{why.hm && <> · <span className="num">{why.hm}</span> 작성</>}</>}>
          <p className="m-0 text-13 text-ink-1">{why.line}</p>
          <ul aria-label="근거" className="m-0 mt-2 p-0 list-none flex flex-wrap gap-1.5">
            {why.refs.map((r, i) => {
              const body = <>{r.kind && <span className="text-ink-3">{r.kind}</span>}{r.label}</>
              return <li key={i}>{r.url ? <a href={r.url} target="_blank" rel="noopener noreferrer" className={`${CHIP} no-underline hover:text-ink-1`}>{body}</a> : <span className={CHIP}>{body}</span>}</li>
            })}
          </ul>
        </Panel>
      )}

      <div className="grid grid-cols-1 pc:grid-cols-12 gap-4 items-start">
        <FlowPanel className="pc:col-span-8" name={name} short={row?.short ?? (kr ? undefined : id)} pts={chart?.pts} decimals={decimals} value={price}
          base={chart?.prev != null ? { value: chart.prev, label: '전일' } : null}
          cmp={cmpGot} onCmpOff={() => setCmp('')} fail={chart === null ? '시세 흐름을 받지 못했습니다' : undefined} />

        <div className="pc:col-span-4 flex flex-col gap-4">
          <BellPanel id={id} name={name} what="이 종목이" cur={price} unit={kr ? '원' : '달러'} />

          {info.events.length > 0 && (
            <Panel title="이 종목 공시" source="OpenDART" asOf={info.eventsAt?.asOf} state={info.eventsAt?.state}>
              <ul className="m-0 p-0 list-none">
                {info.events.map((e, i) => (
                  <li key={`${e.rcpNo ?? e.date}-${i}`} className="py-1.5 border-b border-line last:border-b-0">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-13">
                      <Pill tone="o">{CORP_KIND[e.kind ?? ''] ?? '공시'}</Pill>
                      <span className="num text-12 text-ink-3">{shortDate(e.date)}</span>
                      {e.title && <span className="text-ink-1">{e.title}</span>}
                    </div>
                    {(e.detail || e.rcpNo) && (
                      <p className="m-0 mt-0.5 text-12 text-ink-3 [overflow-wrap:anywhere]">
                        {e.detail}{e.detail && e.rcpNo ? ' · ' : ''}
                        {e.rcpNo && <a href={dartUrl(e.rcpNo)} target="_blank" rel="noopener noreferrer" className="text-ink-2 hover:text-ink-1">원문</a>}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </Panel>
          )}

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

          <Panel title="메르 언급" source="메르 블로그 최근 글">
            {!posts ? (
              mer === 'fail' ? <p className="m-0 text-13 text-ink-3">메르 글을 받지 못했습니다.</p>
                : mer === 'want' ? <p className="m-0 text-13 text-ink-3">메르 글 찾는 중</p>
                  : <button type="button" className={BTN2} onClick={() => setMer('want')}>메르 글 찾기</button>
            ) : !mentions.length ? <p className="m-0 text-13 text-ink-3">최근 메르 글에 이 종목 이야기가 없습니다.</p> : (
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
            )}
          </Panel>
        </div>

        <Related title="함께 볼 것" items={info.related} cmp={cmp} onCmp={setCmp} canOverlay={!!chart} />
      </div>
    </div>
  )
}
