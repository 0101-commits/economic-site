// 홈 「오늘」 — 기획안 v4 3장. 머리 → 오늘 한 줄 → AI 요약 3줄(+질문칸) → 지표 띠 8 + 관심 칸 → 분위기 5칸 → 격자(PC 12열 / 모바일 1열 같은 순서).
// 금액(내 자산)은 여기서 절대 읽지 않는다. 관심은 이 기기의 id 목록뿐(lib/watch.ts).
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, House } from 'lucide-react'
import { loadHome, loadIndicator, shownUnit, useBundleRev, type HomeBundle, type MoodItem, type Sched, type Stock, type StripItem, type Trigger } from '../lib/bundle'
import { changeDir, dayLabel, fmtChange, fmtNumber, fmtPct, mdHm, safeHref, scaled, scaledPts, shortDate, slicePeriods, PERIODS, type PeriodKey, type Pt } from '../lib/format'
import { useViewParam } from '../lib/useViewParam'
import { useWatch } from '../lib/watch'
import { AsOfBadge, NumBlock, Pill } from '../components/ui'
import { DivergingBars, Heatmap, LineChart } from '../components/charts'
import { More, Panel, RankTable, StripCard, WatchStar, type Col } from '../components/panels'
import { BTN, INPUT, LevelPill } from '../components/personal/bits'
import { hhmm, todayRows } from '../lib/alerts/v2'
import { kstDay } from '../lib/personal/calc'
import { loadRootJson } from '../lib/personal/data'
import { aiAsk, aiErrText } from '../lib/personal/remote'
import { getKeyHash, lastReqAt, noteReq, useSyncStatus } from '../lib/personal/sync'

const MAX_WATCH = 8   // 띠 뒤에 붙는 관심 칸 상한 — 넘으면 「관심 N개 더」
const DIR_TEXT = { up: 'text-up', down: 'text-down', flat: 'text-ink-2' } as const
// 일정에 섞여 오는 종목 공시(kind) → 알약 글자. 이름은 묶음이 「종목 제목」으로 붙여 준다. 순서(날짜·시각)도 묶음이 정한다.
const CORP_KIND: Record<string, string> = { dividend: '배당', earnings: '실적' }
type SchedRow = Sched & { kind?: string | null; code?: string | null }

/** 오늘 한 줄: 숫자 낱말(+1.80% · 4,910억)만 굵게 검정. 묶음에 핵심어 표시가 아직 없어서다. */
const KEY_RE = /([+\-]?\d[\d,.]*(?:%p|%|bp|억|조|원|달러|엔)?)/
function emphasize(text: string): ReactNode {
  return text.split(KEY_RE).map((t, i) => (i % 2 ? <b key={i} className="num font-bold text-ink-1">{t}</b> : t))
}

const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, '') } catch { return '' } }

/** 등락 한 칸: 등락률이 있으면 %, 없으면(금리 등) 변화량. */
function ChangeText({ chg, pct, decimals }: { chg: number | null | undefined; pct: number | null | undefined; decimals: number }) {
  const dir = changeDir(pct ?? chg, pct != null ? 2 : decimals)
  return <span className={`num text-12 ${DIR_TEXT[dir]}`}>{pct != null ? fmtPct(pct) : fmtChange(chg, null, decimals)}</span>
}

export default function Home() {
  const [home, setHome] = useState<HomeBundle | null>(null)
  const [err, setErr] = useState(false)
  // 묶음을 새로 받으면(lib/bundle.ts 다시 읽기) 그 자리에서 바꿔 그린다 — 질문칸의 답 · 입력을 지우지 않게 홈은 다시 만들지 않는다
  // 다시 읽기(이미 그린 홈이 있을 때)는 data.json 폴백을 타지 않고, 실패하면 옛 화면을 그대로 둔다
  const rev = useBundleRev()
  const had = useRef(false)
  useEffect(() => {
    const again = had.current
    loadHome(!again).then(h => { had.current = true; setHome(h); setErr(false) }, () => { if (!again) setErr(true) })
  }, [rev])
  // 알림 원장(events/latest.json) — 「일정·알림」 패널의 「오늘 바뀐 것」. 아직 없으면(배포 전) 패널은 종전 그대로다.
  const [ledger, setLedger] = useState<unknown>(null)
  useEffect(() => { loadRootJson<unknown>('events/latest.json').then(setLedger, () => {}) }, [])
  const changed = useMemo(() => todayRows(ledger, kstDay()), [ledger])
  const [s, setS] = useViewParam<string>('s', 'kospi')
  const [p, setP] = useViewParam<PeriodKey>('p', '3m', PERIODS.map(o => o.key))
  const watch = useWatch()
  const { linked } = useSyncStatus()

  // 관심 칸이 쓸 값: 홈 띠 · 거래대금 상위 종목에 없는 id 는 지표 사전에서 한 번 찾는다
  const [extra, setExtra] = useState<Record<string, StripItem | null>>({})
  const homeStrip = home?.strip || []
  const stocks = useMemo(() => new Map((home?.topAmount?.items || []).map(x => [x.code, x])), [home])
  useEffect(() => {
    if (!home) return
    for (const id of watch.ids) {
      if (home.strip.some(x => x.id === id) || stocks.has(id) || id in extra) continue
      setExtra(m => ({ ...m, [id]: null }))
      loadIndicator(id).then(r => {
        const it = r.item ?? (r.reg ? { id, label: r.reg.label, decimals: r.reg.decimals, value: null, change: null, changePct: null, asOf: null } : null)
        setExtra(m => ({ ...m, [id]: it && { ...it, short: r.reg?.short ?? it.short } }))
      }, () => {})
    }
  }, [home, watch.ids, stocks, extra])

  // 관심(별표) 칸: 홈 띠에 이미 있는 것은 빼고 담은 순서대로. 종목은 거래대금 상위 행으로 칸을 꾸리고, 못 찾은 id 는 이름 자리에 id 그대로.
  const watchItems = watch.ids.flatMap((id): StripItem[] => {
    if (homeStrip.some(x => x.id === id)) return []
    const it = extra[id]
    if (it) return [it]
    const st = stocks.get(id)
    if (st) return [{ id, label: st.name, short: st.short, shortM: st.shortM, decimals: 0, value: st.price, change: null, changePct: st.chgPct, asOf: home?.topAmount?.asOf ?? null, state: home?.topAmount?.state }]
    return id in extra ? [{ id, label: id, decimals: 0, value: null, change: null, changePct: null, asOf: null }] : []
  })
  // 화면에 그리는 칸 = 띠 + 관심 최대 MAX_WATCH. 고를 수 있는 것은 지표(띠 · 지표 사전에서 찾은 관심)뿐 —
  // 관심 종목(종목 코드)은 큰 차트로 받을 시계열이 없어 고르기 단추가 아니다.
  const shown = [...homeStrip, ...watchItems].slice(0, homeStrip.length + MAX_WATCH)
  const canPick = (id: string) => homeStrip.some(x => x.id === id) || !!extra[id]

  // 큰 차트: 고른 카드(s). 코스피는 홈 묶음 kospiChart, 그 밖은 시장 묶음 시계열(처음 고를 때 한 번 받는다)
  const sel = shown.find(x => x.id === s && canPick(x.id)) ?? shown[0]
  const [series, setSeries] = useState<Record<string, Pt[] | null>>({})
  const useKospi = sel?.id === 'kospi' && !!home?.kospiChart
  useEffect(() => {
    if (!sel || useKospi || sel.id in series) return
    const id = sel.id
    setSeries(m => ({ ...m, [id]: null }))
    loadIndicator(id).then(r => setSeries(m => ({ ...m, [id]: r.series ?? [] })), () => setSeries(m => ({ ...m, [id]: [] })))
  }, [sel?.id, useKospi])
  const periods = useMemo(() => {
    if (!sel) return {}
    if (useKospi) return Object.fromEntries(PERIODS.map(o => [o.key, home!.kospiChart![o.key] ?? null]))
    const got = series[sel.id]
    if (got?.length) return slicePeriods(scaledPts(got, sel.scale))
    // 시계열이 없으면 띠의 최근 7거래일(날짜 없음)이라도 1주로 보여 준다
    if (got && sel.spark && sel.spark.length >= 2) return { '1w': scaledPts(sel.spark.map((x): Pt => ['', x]), sel.scale) }
    return {}
  }, [sel, useKospi, home, series])
  const trig = [...(home?.lens?.breach || []), ...(home?.lens?.watch || [])].find(t => t.id === sel?.id && t.level != null)
  const selV = sel ? scaled(sel.value, sel.scale) : null, selC = sel ? scaled(sel.change, sel.scale) : null

  if (err) return <p className="m-0 text-14 text-ink-2">자료를 불러오지 못했습니다.</p>
  if (!home) return <p className="m-0 text-14 text-ink-3">불러오는 중</p>
  const mk = home.market
  const inv = home.investors
  const invCol = (k: string) => (inv?.columns ?? ['date', 'foreign', 'inst', 'retail']).indexOf(k)
  const flow20 = (inv?.rows || []).slice(-20)
  const lens = home.lens
  const brief = home.brief
  const briefOld = !!brief?.asOf && kstDay(Date.parse(brief.asOf)) !== kstDay()

  // 4열 패널(약 350px)에 맞춰 열은 넷: 거래대금은 조원 두 자리, 모바일에선 이름 아래 줄
  const amountCols: Col<Stock>[] = [
    { key: 'name', label: '종목', get: r => r.short || r.name, role: 'name' },
    { key: 'price', label: '현재가', get: r => r.price, num: true, role: 'value' },
    { key: 'pct', label: '등락률', get: r => r.chgPct, num: true, role: 'change', render: r => <ChangeText chg={null} pct={r.chgPct} decimals={2} /> },
    { key: 'amount', label: '거래대금', get: r => (r.amount == null ? null : r.amount / 1e12), num: true, role: 'sub',
      render: r => (r.amount == null ? null : `${fmtNumber(r.amount / 1e12, 2)}조`) },
  ]

  return (
    <div className="flex flex-col gap-4">
      {/* 머리 */}
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h1 className="m-0 inline-flex items-center gap-1.5 text-18 font-bold text-ink-1"><House size={18} aria-hidden />오늘</h1>
        {mk?.today && <span className="text-13 text-ink-2">{dayLabel(mk.today)}</span>}
        {mk && <Pill tone={mk.state === 'open' ? 'g' : 'o'}>{mk.label}</Pill>}
        {mk && mk.state !== 'open' && mk.nextOpen && <span className="text-12 text-ink-3">다음 개장 <span className="num">{mdHm(mk.nextOpen)}</span></span>}
      </header>

      {/* 오늘 한 줄 */}
      <p className="m-0 text-13 text-ink-2 max-w-[44em]">
        {!home.todayLine ? '오늘 한 줄이 아직 없습니다.' : (
          <>
            <span className="hidden pc:inline">{emphasize(home.todayLine.pc)}</span>
            <span className="pc:hidden">{emphasize(home.todayLine.mobile)}</span>
          </>
        )}
      </p>

      {/* AI 요약 3줄 — 접지 않는다. 오늘(KST) 만든 것이 아니면 머리에 날짜. 질문칸은 동기화가 켜진 기기에만(Worker /ai 가 키를 본다) */}
      {(!!brief?.lines.length || linked) && (
        <section aria-labelledby="home-brief" className="-mt-2 max-w-[44em]">
          <h2 id="home-brief" className="m-0 mb-1 flex flex-wrap items-baseline gap-x-2 text-12 font-bold text-ink-2">
            AI 요약{briefOld && <span className="num font-normal text-ink-3">{mdHm(brief!.asOf!)} 기준</span>}
          </h2>
          {brief?.lines.length ? (
            <ul className="m-0 pl-5 list-disc marker:text-ink-3 flex flex-col gap-1 text-13 text-ink-2">
              {brief.lines.map((l, i) => <li key={i}>{emphasize(l)}</li>)}
            </ul>
          ) : <p className="m-0 text-13 text-ink-3">AI 요약이 아직 없습니다.</p>}
          {linked && <AskBox home={home} />}
        </section>
      )}

      {/* 지표 띠 8 + 관심 칸(9번째부터, 최대 8). 모바일 2열이라 짝을 맞추지 않는다 */}
      <div className="grid grid-cols-2 sm:grid-cols-4 pc:grid-cols-8 gap-2">
        {shown.map((it, i) => (
          <StripCard key={it.id} item={it} selected={it.id === sel?.id} onSelect={canPick(it.id) ? () => setS(it.id) : undefined}
            watched={watch.has(it.id)} onWatch={() => watch.toggle(it.id)} tag={i >= homeStrip.length ? <Pill tone="o">관심</Pill> : undefined} />
        ))}
      </div>
      {watchItems.length > MAX_WATCH && (
        <Link to="/alerts?v=cond" className="-mt-2 self-start inline-flex items-center text-12 text-ink-2 no-underline hover:text-ink-1">
          관심 <span className="num">{watchItems.length - MAX_WATCH}</span>개 더<ChevronRight size={14} aria-hidden />
        </Link>
      )}

      {/* 분위기 5칸 — 띠 아래 한 줄(모바일은 3열 두 줄, 자르지 않는다). 등락은 1주 전 대비 */}
      {!!home.mood?.length && (
        <section aria-labelledby="home-mood" className="bg-card border border-line rounded-card px-3 py-2 flex flex-col pc:flex-row pc:items-center gap-x-4 gap-y-2">
          <h2 id="home-mood" className="m-0 shrink-0 text-12 font-bold text-ink-2">분위기 <span className="font-normal text-ink-3">1주 전 대비</span></h2>
          <ul className="m-0 p-0 list-none flex-1 grid grid-cols-3 pc:grid-cols-5 gap-x-3 gap-y-2">
            {home.mood.map(m => <MoodCell key={m.id} m={m} />)}
          </ul>
        </section>
      )}

      <div className="grid grid-cols-1 pc:grid-cols-12 gap-4 items-start">
        {/* 큰 차트 */}
        {sel && (
          <Panel className="pc:col-span-6" title={sel.short || sel.label} asOf={sel.asOf} state={sel.state} liveUntil={sel.liveUntil}
            tools={<Link to={`/i/${sel.id}`} className="inline-flex items-center text-12 text-ink-2 no-underline hover:text-ink-1">자세히<ChevronRight size={14} aria-hidden /></Link>}>
            <div className="mb-2"><NumBlock value={selV} decimals={sel.decimals} chg={selC} pct={sel.changePct} size="L" unit={shownUnit(sel)} /></div>
            <LineChart key={sel.id} label={sel.label} periods={periods} period={p} onPeriod={setP} decimals={sel.decimals}
              base={selV != null && selC != null ? { value: selV - selC, label: '전일' } : null}
              limit={trig ? { value: trig.level!, label: `${trig.stateLabel ?? ''} 기준` } : null}
              empty={!useKospi && series[sel.id] === null ? '불러오는 중' : '시계열 준비 중'} />
          </Panel>
        )}

        {/* 업종 히트맵 — 큰 차트 옆 6칸 */}
        <Panel className="pc:col-span-6" title="업종" asOf={home.sectors?.asOf} state={home.sectors?.state}>
          {home.sectors?.items.length
            ? <Heatmap label="업종 등락률" minCell={56} cells={home.sectors.items.map(x => ({ key: x.name, name: x.name, value: x.chgPct }))} />
            : <p className="m-0 text-13 text-ink-3">업종 자료가 없습니다.</p>}
        </Panel>

        {/* 거래대금 상위 */}
        <Panel className="pc:col-span-4" title="거래대금 상위" asOf={home.topAmount?.asOf} state={home.topAmount?.state}>
          {home.topAmount?.items.length
            ? <RankTable label="거래대금 상위 종목" cols={amountCols} rows={home.topAmount.items.slice(0, 10)} rowKey={r => r.code}
                lead={r => <WatchStar on={watch.has(r.code)} onToggle={() => watch.toggle(r.code)} label={r.name} />} />
            : <p className="m-0 text-13 text-ink-3">거래대금 자료가 없습니다.</p>}
        </Panel>

        {/* 투자자 매매 */}
        <Panel className="pc:col-span-4" title="투자자 매매" fold unit={inv?.unit} source={inv?.market} asOf={inv?.asOf} state={inv?.state}>
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
          ) : <p className="m-0 text-13 text-ink-3">수급 자료가 없습니다.</p>}
        </Panel>

        {/* 일정·알림 */}
        <Panel className="pc:col-span-4" title="일정·알림" fold>
          {changed.rows.length > 0 && (
            <section aria-label="오늘 바뀐 것" className="mb-3">
              <h3 className="m-0 mb-1 text-12 font-bold text-ink-2">오늘 바뀐 것</h3>
              <ul className="m-0 p-0 list-none">
                {changed.rows.map(x => (
                  <li key={x.key} className="border-b border-line last:border-b-0">
                    <Link to={x.to ?? '/alerts'} className="flex items-start gap-3 py-1.5 no-underline">
                      <span className="w-10 shrink-0 num text-12 text-ink-3">{hhmm(x.at)}</span>
                      <span className="min-w-0 flex-1 text-13 text-ink-1 line-clamp-2 [overflow-wrap:anywhere]">{x.title}</span>
                      <LevelPill level={x.level} />
                    </Link>
                  </li>
                ))}
              </ul>
              <Link to="/alerts" className="inline-flex items-center mt-1 text-12 text-ink-2 no-underline hover:text-ink-1">받은 알림 <span className="num ml-1">{changed.total}</span><ChevronRight size={14} aria-hidden /></Link>
            </section>
          )}
          {changed.rows.length > 0 && <h3 className="m-0 mb-1 text-12 font-bold text-ink-2">다가오는 일정</h3>}
          {home.schedule?.length ? <More rows={home.schedule as SchedRow[]}>{shown => (
            <ul className="m-0 p-0 list-none">
              {shown.map((e, i) => (
                <li key={`${e.date}-${e.name}-${i}`} className="flex items-baseline gap-3 py-1.5 border-b border-line last:border-b-0">
                  <span className="w-[5.5rem] shrink-0 num text-12 text-ink-3">{`${e.date === mk?.today ? '오늘' : shortDate(e.date)}${e.time ? ` ${e.time}` : ''}`}</span>
                  <span className="flex-1 min-w-0 text-13 text-ink-1">
                    {e.kind && CORP_KIND[e.kind] && <span className="mr-1.5"><Pill tone="o">{CORP_KIND[e.kind]}</Pill></span>}
                    {e.name}{e.approx ? <span className="text-ink-3"> (추정)</span> : null}
                  </span>
                  {!!e.stars && <span className="shrink-0 text-11 text-ink-3" aria-label={`중요도 ${e.stars}`}>{'★'.repeat(e.stars)}</span>}
                </li>
              ))}
            </ul>
          )}</More> : <p className="m-0 text-13 text-ink-3">다가오는 일정이 없습니다.</p>}
          <Link to="/alerts" className="inline-flex items-center mt-3 text-12 text-ink-2 no-underline hover:text-ink-1">알림 조건 보기<ChevronRight size={14} aria-hidden /></Link>
        </Panel>

        {/* 렌즈 오늘 */}
        <Panel className="pc:col-span-8" title="렌즈 오늘" source={lens?.asOf ? `${shortDate(lens.asOf)} 기준` : undefined}
          tools={<Link to="/lens" className="inline-flex items-center text-12 text-ink-2 no-underline hover:text-ink-1">렌즈로<ChevronRight size={14} aria-hidden /></Link>}>
          {!lens ? <p className="m-0 text-13 text-ink-3">렌즈 자료가 없습니다.</p> : (
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-12 text-ink-2">위험 점수</span>
                <span className="num text-24 font-bold text-ink-1">{fmtNumber(lens.score)}</span>
                {lens.delta30d != null && <span className={`num text-12 ${DIR_TEXT[changeDir(lens.delta30d, 1)]}`}>30일 {fmtChange(lens.delta30d, null, 1)}</span>}
                {lens.hotChains != null && <span className="text-12 text-ink-3">움직이는 사슬 {lens.hotChains}개</span>}
              </div>
              <ul className="m-0 p-0 list-none flex flex-col gap-2">
                {[...lens.breach.map(t => ['x', t] as const), ...lens.watch.map(t => ['n', t] as const)].map(([tone, t]) => <TriggerRow key={`${tone}-${t.id}`} tone={tone} t={t} />)}
                {lens.chain && (
                  <li className="flex flex-wrap items-center gap-x-2 gap-y-1 text-13">
                    <Pill tone="o">사슬</Pill>
                    <span className="font-bold text-ink-1">{lens.chain.label}</span>
                    <span className="inline-flex flex-wrap items-center gap-x-1 text-12 text-ink-2">
                      {lens.chain.steps.map((st, i) => (
                        <span key={i} className="inline-flex items-center gap-x-1">
                          {i > 0 && <ChevronRight size={12} aria-hidden className="text-ink-3" />}
                          <span className={st.id === lens.chain!.hotStep ? 'font-bold text-ink-1' : undefined}>{st.label}</span>
                        </span>
                      ))}
                    </span>
                    {lens.chain.n != null && <span className="text-11 text-ink-3">글 {lens.chain.n}편{lens.chain.lastDate ? ` · 최근 ${shortDate(lens.chain.lastDate)}` : ''}</span>}
                  </li>
                )}
              </ul>
            </div>
          )}
        </Panel>

        {/* 뉴스 — 렌즈 오늘 8 옆 4칸 */}
        <Panel className="pc:col-span-4" title="뉴스" fold>
          {home.news?.length ? (
            <ul className="m-0 p-0 list-none">
              {home.news.slice(0, 5).map(n => {
                const href = safeHref(n.url)
                return (
                  <li key={n.url} className="py-1.5 border-b border-line last:border-b-0">
                    {href ? <a href={href} target="_blank" rel="noopener noreferrer" className="text-13 text-ink-1 no-underline hover:underline">{n.title}</a>
                      : <span className="text-13 text-ink-1">{n.title}</span>}
                    <span className="block text-11 text-ink-3">{host(n.url)}{n.date ? <> · <span className="num">{shortDate(n.date)}</span></> : null}</span>
                  </li>
                )
              })}
            </ul>
          ) : <p className="m-0 text-13 text-ink-3">뉴스가 없습니다.</p>}
        </Panel>
      </div>
    </div>
  )
}

/** 분위기 한 칸: 이름 + 기준 꼬리표 / 값 · 단위 · 1주 전 대비. 누르면 지표 상세. 단위는 %·%p 만 적는다(「지수 (S&P500 …)」 같은 설명은 title 로). */
function MoodCell({ m }: { m: MoodItem }) {
  const u = m.unit?.startsWith('%') ? m.unit.split(' ')[0] : ''
  const d = Math.max(m.decimals, 2)   // 1주 변화는 값보다 작아 값 자릿수로는 0 이 되기 쉽다(묶음도 둘째 자리까지 준다)
  return (
    <li className="min-w-0">
      <Link to={`/i/${m.id}`} title={m.unit ? `${m.label} · ${m.unit}` : m.label} className="block no-underline">
        <span className="flex flex-wrap items-baseline gap-x-1.5 text-12 text-ink-2 [overflow-wrap:anywhere]">
          <span className="hidden pc:inline">{m.short || m.label}</span>
          <span className="pc:hidden">{m.shortM || m.short || m.label}</span>
          <AsOfBadge asOf={m.asOf} state={m.state} />
        </span>
        <span className="flex flex-wrap items-baseline gap-x-1.5">
          <span className="num text-14 font-bold text-ink-1">{fmtNumber(m.value, m.decimals)}{u && <span className="ml-0.5 text-11 font-normal text-ink-3">{u}</span>}</span>
          <span className={`num text-12 ${DIR_TEXT[changeDir(m.change, d)]}`}>{fmtChange(m.change, null, d)}</span>
        </span>
      </Link>
    </li>
  )
}

/** 질문에 실어 보내는 시장 값 — 홈 묶음에 있는 것만(서버는 이것만 근거로 답한다). 금액(내 자산)은 싣지 않는다. */
function snapshotOf(h: HomeBundle) {
  return {
    기준: h.asOf,
    장: h.market?.label,
    오늘한줄: h.todayLine?.pc,
    지표: h.strip.map(x => ({ 이름: x.label, 값: x.value, 변화: x.change, 등락률: x.changePct, 기준: x.asOf })),
    분위기_1주변화: h.mood?.map(x => ({ 이름: x.label, 값: x.value, 변화: x.change, 기준: x.asOf })),
    AI요약: h.brief?.lines,
    일정: h.schedule?.slice(0, 8).map(e => ({ 날짜: e.date, 이름: e.name })),
    뉴스: h.news?.slice(0, 8).map(n => n.title),
  }
}

const ASK_GAP_MS = 6_000   // /ai 는 /prefs · /portfolio 와 IP 당 분당 10회를 나눠 쓴다(lib/personal/sync.ts GAP_MS 와 같은 값)
const NOT_ADVICE = /\n?\s*※?\s*(AI 답변은 참고용이며 )?투자\s*조언이?\s*아닙니다\.?\s*$/

/** 질문칸 — 답은 그 자리에 하나(대화 기록은 남기지 않는다). 서버가 붙이는 고지는 떼고 화면 꼬리표 하나로. 실패 · 기다림 글은 답을 지우지 않는다. */
function AskBox({ home }: { home: HomeBundle }) {
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [answer, setAnswer] = useState('')
  const [note, setNote] = useState('')
  const ask = async (e: FormEvent) => {
    e.preventDefault()
    const question = q.trim(), hash = getKeyHash()
    if (!question || busy) return
    if (!hash) { setNote('동기화가 꺼졌습니다. 설정 「기기 연결」에서 다시 연결하세요.'); return }
    // 간격은 기기 연결(sync.ts)의 마지막 요청 시각과 같이 센다 — 화면을 다시 열어도 남는다
    const wait = lastReqAt() + ASK_GAP_MS - Date.now()
    if (wait > 0) { setNote(`${Math.ceil(wait / 1000)}초 뒤에 다시 물어보세요.`); return }
    noteReq()
    setBusy(true)
    setNote('')
    const r = await aiAsk(hash, question, snapshotOf(home))
    setBusy(false)
    if (r.text) setAnswer(r.text.replace(NOT_ADVICE, '').trim())
    else setNote(aiErrText(r))
  }
  return (
    <form onSubmit={ask} className="mt-2 flex flex-col gap-2">
      <div className="flex gap-2">
        <input className={INPUT} value={q} onChange={e => setQ(e.target.value)} maxLength={300} enterKeyHint="send"
          placeholder="오늘 시장에 대해 묻기" aria-label="AI 에게 묻기" />
        <button type="submit" disabled={busy || !q.trim()} className={BTN}>{busy ? '묻는 중' : '묻기'}</button>
      </div>
      <div aria-live="polite" className="flex flex-col gap-1 text-13">
        {note && <p className="m-0 text-ink-2">{note}</p>}
        {answer && (
          <div>
            <p className="m-0 whitespace-pre-line text-ink-1">{answer}</p>
            <p className="m-0 mt-1 text-11 text-ink-3">참고용 · 투자 조언 아님</p>
          </div>
        )}
      </div>
    </form>
  )
}

/** 렌즈 트리거 한 줄: 알약(돌파 x · 주시 n) + 이름 + 지금 값 + 기준과 거리. */
function TriggerRow({ tone, t }: { tone: 'x' | 'n'; t: Trigger }) {
  const u = t.unit === '%' || t.unit === '엔' ? t.unit : ''
  return (
    <li className="flex flex-wrap items-center gap-x-2 gap-y-1 text-13">
      <Pill tone={tone}>{t.stateLabel ?? (tone === 'x' ? '돌파' : '주시')}</Pill>
      <span className="text-ink-1">{t.label}</span>
      <span className="num font-bold text-ink-1">{`${fmtNumber(t.value, 2)}${u}`}</span>
      <span className="text-12 text-ink-3">기준 <span className="num">{`${fmtNumber(t.level, 2)}${u}`}</span>{t.distancePct != null && <> · <span className="num">{fmtPct(t.distancePct)}</span></>}</span>
    </li>
  )
}
