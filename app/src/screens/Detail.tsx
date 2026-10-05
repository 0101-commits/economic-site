// 지표 상세 /i/:id — 지표 사전(registry)으로 이름·단위·자릿수, 홈·시장 묶음에서 값·시계열을 찾는다.
// 사전에 없는 낱말(검색창에서 온 것)이면 이름이 비슷한 지표를 늘어놓는다.
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { BellPlus, ChevronRight } from 'lucide-react'
import { loadIndicator, loadRegistry, shownUnit, type RegRow, type StripItem } from '../lib/bundle'
import { range52, scaled, scaledPts, slicePeriods, PERIODS, type PeriodKey, type Pt } from '../lib/format'
import { useViewParam } from '../lib/useViewParam'
import { useWatch } from '../lib/watch'
import { AsOfBadge, NumBlock } from '../components/ui'
import { LineChart, Range52 } from '../components/charts'
import { Panel, StripCard, WatchStar } from '../components/panels'

// 사전 자산군 → 시장 화면 자산군 탭(Market.tsx ASSETS 키)
const MARKET_TAB: Record<string, string> = { index: 'global', sentiment: 'global', fx: 'fxrate', rate: 'fxrate', commodity: 'commod', macro: 'macro', realestate: 'realestate' }

type Got = { reg?: RegRow; item?: StripItem; series?: Pt[]; related: { reg: RegRow; item?: StripItem }[]; matches: RegRow[] }

export default function Detail() {
  const { id = '' } = useParams()
  const [p, setP] = useViewParam<PeriodKey>('p', '3m', PERIODS.map(o => o.key))
  const watch = useWatch()
  const [got, setGot] = useState<Got | null>(null)
  useEffect(() => {
    let live = true
    setGot(null)
    ;(async () => {
      const [one, rows] = await Promise.all([loadIndicator(id), loadRegistry().catch(() => [] as RegRow[])])
      const reg = one.reg
      // 함께 볼 지표: 같은 자산군에서 4개(사전 순서 = tier 순)
      const peers = reg ? rows.filter(r => r.asset === reg.asset && r.id !== reg.id).sort((a, b) => (a.tier ?? 9) - (b.tier ?? 9)).slice(0, 4) : []
      const related = await Promise.all(peers.map(r => loadIndicator(r.id).then(x => ({ reg: r, item: x.item }), () => ({ reg: r }))))
      const q = id.toLowerCase()
      const matches = reg || one.item ? [] : rows.filter(r => [r.id, r.label, r.short].some(t => t?.toLowerCase().includes(q))).slice(0, 12)
      if (live) setGot({ ...one, related, matches })
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
  const r52 = range52(pts)

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
        <Panel className="pc:col-span-8" title="흐름">
          <LineChart label={name} periods={slicePeriods(pts)} period={p} onPeriod={setP} decimals={decimals}
            base={v != null && c != null ? { value: v - c, label: '전일' } : null} />
          {r52 && <div className="mt-4"><Range52 low={r52.low} high={r52.high} value={v} decimals={decimals} /></div>}
        </Panel>

        <Panel className="pc:col-span-4" title="알림">
          <p className="m-0 mb-3 text-13 text-ink-2">이 지표가 정한 값을 넘거나 크게 움직이면 알려 드립니다.</p>
          <Link to={`/alerts?v=cond&id=${encodeURIComponent(id)}`}
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-btn bg-accent text-on-accent text-13 font-bold no-underline">
            <BellPlus size={16} aria-hidden />알림 조건 추가
          </Link>
        </Panel>

        {got.related.length > 0 && (
          <section className="pc:col-span-12 flex flex-col gap-2" aria-label="함께 볼 지표">
            <h2 className="m-0 text-14 font-bold text-ink-1">함께 볼 지표</h2>
            <div className="grid grid-cols-2 pc:grid-cols-4 gap-2">
              {got.related.map(({ reg: r, item: it }) => (
                <StripCard key={r.id} to={`/i/${r.id}`} watched={watch.has(r.id)} onWatch={() => watch.toggle(r.id)}
                  item={{ ...(it ?? { value: null, change: null, changePct: null, asOf: null }), id: r.id, label: r.label, short: r.short, shortM: r.shortM, decimals: r.decimals, unit: it?.unit ?? r.unit, scale: it?.scale ?? r.scale }} />
              ))}
            </div>
          </section>
        )}
      </div>

      {reg && MARKET_TAB[reg.asset] && (
        <Link to={`/market?a=${MARKET_TAB[reg.asset]}`} className="inline-flex items-center self-start text-12 text-ink-2 no-underline hover:text-ink-1">시장 화면에서 보기<ChevronRight size={14} aria-hidden /></Link>
      )}
    </div>
  )
}
