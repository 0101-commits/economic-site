// 지표 상세 /i/:id — 지표 사전(registry)으로 이름·단위·자릿수, 홈·시장 묶음에서 값·시계열을 찾는다.
// 사전에 없는 낱말(검색창에서 온 것)이면 이름이 비슷한 지표를 늘어놓는다. 렌즈 지표 48개(렌즈 묶음 triggers)에 들면 「렌즈」 패널을 붙인다.
// 사전 행에 뉴스 주제(news)가 있으면 「관련 뉴스」 3줄(없으면 패널 없음).
// id 가 종목(국내 6자리 코드 · 미국 티커, lib/detail.ts isStockId)이면 종목 상세(components/detail/Stock.tsx)를 그린다.
// 「함께 볼 지표」 카드의 「겹쳐 보기」는 흐름 차트에 그 선을 첫 날 = 100 으로 겹친다(주소 cmp).
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { loadBundle, loadIndicator, loadRegistry, shownUnit, type RegRow, type StripItem, type Trigger } from '../lib/bundle'
import { isStockId } from '../lib/detail'
import { scaled, scaledPts, type Pt } from '../lib/format'
import { useWatch } from '../lib/watch'
import { AsOfBadge, NumBlock } from '../components/ui'
import { Panel, WatchStar } from '../components/panels'
import { TrigPill, asOfText, btn, trigValue } from '../components/lens/parts'
import type { LensBundle, LensChain } from '../components/lens/model'
import { NewsPanel } from '../components/market/parts'
import { BellPanel, FlowPanel, Related, useCmp } from '../components/detail/parts'
import StockDetail from '../components/detail/Stock'

// 사전 자산군 → 시장 화면 자산군 탭(Market.tsx ASSETS 키)
const MARKET_TAB: Record<string, string> = { index: 'global', sentiment: 'global', fx: 'fxrate', rate: 'fxrate', commodity: 'commod', macro: 'macro', realestate: 'realestate' }

/** 렌즈 한 줄: 트리거 + 이 지표가 단계로 든 사슬 + 이 지표를 다룬 글 수(사슬 · 관계 글의 원문 번호를 겹치지 않게 센다). */
type LensFact = { t: Trigger; chains: LensChain[]; posts: number }
type Got = { reg?: RegRow; item?: StripItem; series?: Pt[]; related: { reg: RegRow; item?: StripItem }[]; matches: RegRow[]; lens?: LensFact }

function lensFact(b: LensBundle | null, id: string): LensFact | undefined {
  // 묶음 모양이 어긋나도(칸이 빠짐) 렌즈 패널만 빠지게 — 여기서 던지면 상세 전체가 「못 찾음」이 된다
  const t = b?.triggers?.find(x => x.id === id)
  if (!b || !t) return undefined
  const chains = (b.chains ?? []).filter(c => c.steps?.some(st => st.id === id))
  const nos = new Set([...chains.flatMap(c => c.logNos ?? []), ...(b.edges ?? []).flatMap(e => (e.from === id || e.to === id ? e.logNos ?? [] : []))])
  return { t, chains, posts: nos.size }
}

export default function Detail() {
  const { id = '' } = useParams()
  return isStockId(id) ? <StockDetail key={id} id={id} /> : <IndicatorDetail id={id} />
}

function IndicatorDetail({ id }: { id: string }) {
  const watch = useWatch()
  const [got, setGot] = useState<Got | null>(null)
  const [cmp, setCmp, cmpGot] = useCmp(id)
  useEffect(() => {
    let live = true
    setGot(null)
    ;(async () => {
      const [one, rows, lb] = await Promise.all([loadIndicator(id), loadRegistry().catch(() => [] as RegRow[]), loadBundle<LensBundle>('lens').catch(() => null)])
      const reg = one.reg
      // 함께 볼 지표: 같은 자산군에서 4개(사전 순서 = tier 순)
      const peers = reg ? rows.filter(r => r.asset === reg.asset && r.id !== reg.id).sort((a, b) => (a.tier ?? 9) - (b.tier ?? 9)).slice(0, 4) : []
      const related = await Promise.all(peers.map(r => loadIndicator(r.id).then(x => ({ reg: r, item: x.item }), () => ({ reg: r }))))
      const q = id.toLowerCase()
      const matches = reg || one.item ? [] : rows.filter(r => [r.id, r.label, r.short].some(t => t?.toLowerCase().includes(q))).slice(0, 12)
      if (live) setGot({ ...one, related, matches, lens: lensFact(lb, id) })
    })().catch(() => { if (live) setGot({ related: [], matches: [] }) })
    return () => { live = false }
  }, [id])

  if (!got) return <p className="m-0 text-14 text-ink-3">불러오는 중</p>
  const { reg, item, series } = got
  if (!reg && !item) {
    return (
      <div className="flex flex-col gap-3">
        <h1 className="m-0 text-18 font-bold text-ink-1">「{id}」 지표를 찾지 못했습니다</h1>
        {got.matches.length ? (
          <ul className="m-0 p-0 list-none flex flex-col gap-1">
            {got.matches.map(r => <li key={r.id}><Link to={`/i/${r.id}`} className="text-14">{r.label}</Link></li>)}
          </ul>
        ) : <p className="m-0 text-14 text-ink-2">비슷한 이름도 없습니다. <Link to="/">홈으로</Link></p>}
      </div>
    )
  }

  const name = reg?.label ?? item!.label
  const decimals = reg?.decimals ?? item?.decimals ?? 2
  const scale = item?.scale ?? reg?.scale
  const unitShown = shownUnit({ scale, unit: item?.unit ?? reg?.unit })
  const v = scaled(item?.value, scale), c = scaled(item?.change, scale)
  const pts = series ? scaledPts(series, scale) : undefined
  const lens = got.lens, t = lens?.t
  // 흐름 차트 기준선: 트리거 값이 화면 값과 같은 잣대일 때만(물가는 트리거 = 전년비 %, 화면 = 지수라 그리지 않는다)
  // ponytail: 5% 근접으로 잣대를 가늠한다 — 트리거에 화면 단위가 실리면 그것으로 바꾼다
  const known = t?.value != null && v != null, same = known && Math.abs(t!.value! - v!) <= Math.abs(v!) * 0.05
  const limit = t?.level != null && same ? { value: t.level, label: '기준' } : null
  // 잣대가 다르면(기준선을 안 그리는 같은 판정) 렌즈 줄 앞에 잣대 이름 — 트리거 이름 괄호(「한국 CPI(전년비)」 → 전년비), 없으면 트리거 이름.
  // 묶음 트리거엔 변환 칸이 없고 단위는 '%' 뿐이라 이름이 유일한 원천이다(2026-10-09 실측: 잣대가 다른 것 = cpi_kr · pce_us, 둘 다 괄호 있음).
  const scaleName = t && known && !same ? /\(([^)]+)\)\s*$/.exec(t.label)?.[1] ?? t.label : null

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <h1 className="m-0 text-24 font-bold text-ink-1">{name}</h1>
          <WatchStar on={watch.has(id)} onToggle={() => watch.toggle(id)} label={name} />
        </div>
        <div className="flex flex-wrap items-end gap-x-3 gap-y-1">
          <NumBlock value={v} decimals={decimals} chg={item?.change !== undefined ? c : undefined} pct={item?.changePct} size="L" unit={unitShown} />
          <AsOfBadge asOf={item?.asOf} state={item?.state} liveUntil={item?.liveUntil} />
        </div>
        {reg?.unit && !unitShown && <p className="m-0 text-12 text-ink-3">단위 {reg.unit}</p>}
      </header>

      <div className="grid grid-cols-1 pc:grid-cols-12 gap-4 items-start">
        <FlowPanel className="pc:col-span-8" name={name} short={reg?.short} pts={pts ?? []} decimals={decimals} value={v}
          base={v != null && c != null ? { value: v - c, label: '전일' } : null} limit={limit} cmp={cmpGot} onCmpOff={() => setCmp('')} />

        <div className="pc:col-span-4 flex flex-col gap-4">
          <BellPanel id={id} name={name} what="이 지표가" />

          {lens && t && (
            <Panel title="렌즈" source="메르 글 기준">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-13">
                <TrigPill t={t} />
                {scaleName && <span className="text-ink-2">{scaleName}</span>}
                <span className="text-ink-3">기준 <span className="num text-ink-1">{trigValue({ ...t, value: t.level }) ?? '—'}</span></span>
                <span className="text-ink-3">지금 <span className="num text-ink-1">{trigValue(t) ?? '—'}</span></span>
                {t.asOf && <span className="num text-11 text-ink-3">{asOfText(t.asOf)}</span>}
              </div>
              <p className="m-0 mt-2 text-12 text-ink-2">
                {lens.chains.length ? <>사슬 {lens.chains.map(c => c.label).join(' · ')}</> : '걸린 사슬 없음'}
                {lens.posts > 0 && <> · 글 <span className="num">{lens.posts}</span>편</>}
              </p>
              <Link to={lens.chains.length ? `/lens?m=chain&s=${lens.chains[0].id}` : '/lens'} className={`${btn()} mt-3`}>
                렌즈에서 보기<ChevronRight size={14} aria-hidden />
              </Link>
            </Panel>
          )}

          <NewsPanel topic={reg?.news} n={3} title="관련 뉴스" />
        </div>

        <Related items={got.related} cmp={cmp} onCmp={setCmp} canOverlay={!!pts?.length && pts.every(q => q[1] > 0)} />
      </div>

      {reg && MARKET_TAB[reg.asset] && (
        <Link to={`/market?a=${MARKET_TAB[reg.asset]}`} className="inline-flex items-center self-start text-12 text-ink-2 no-underline hover:text-ink-1">시장 화면에서 보기<ChevronRight size={14} aria-hidden /></Link>
      )}
    </div>
  )
}
