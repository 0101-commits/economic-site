// 상세(/i/:id) 공통 부품 — 지표 상세(screens/Detail.tsx)와 종목 상세(detail/Stock.tsx)가 같이 쓴다.
// 흐름 패널(기간 차트 + 52주 범위 + 겹침) · 알림 패널(벨 시트) · 함께 볼 지표(카드 + 「겹쳐 보기」).
import { useEffect, useState } from 'react'
import { BellPlus } from 'lucide-react'
import { loadIndicator, type RegRow, type StripItem } from '../../lib/bundle'
import { overlay } from '../../lib/detail'
import { range52, slicePeriods, PERIODS, type PeriodKey, type Pt } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { useWatch } from '../../lib/watch'
import { LineChart, Range52 } from '../charts'
import { Panel, StripCard } from '../panels'
import { BellSheet } from '../personal/BellSheet'

type Ref = { value: number; label: string } | null
/** 겹칠 선: 이름(범례 · 선 끝) + 시계열(아직 못 받았으면 없음 — 그동안은 겹치지 않은 차트). */
export type Cmp = { name: string; short?: string; pts?: Pt[] }

/** 주소 cmp(겹칠 지표 id — 허용 목록 없이 받는다, 공유 · 새로고침에도 남는다)와 그 시계열. 자기 자신 · 시계열이 없는 id 는 겹치지 않는다. */
export function useCmp(id: string): [string, (next: string) => void, Cmp | null] {
  const [cmp, setCmp] = useViewParam<string>('cmp', '')
  const [got, setGot] = useState<Cmp | null>(null)
  useEffect(() => {
    setGot(null)
    if (!cmp || cmp === id) return
    let live = true
    loadIndicator(cmp).then(x => { if (live && x.series) setGot({ name: x.reg?.label ?? x.item?.label ?? cmp, short: x.reg?.short ?? x.item?.short, pts: x.series }) }, () => {})
    return () => { live = false }
  }, [cmp, id])
  return [cmp, setCmp, got]
}

/**
 * 흐름 패널: 기간 차트(주소 p) + 52주 범위. cmp 가 오면 두 선을 그 기간 첫 날 = 100 으로 바꿔 겹치고(전일선 · 기준선은 빼고),
 * 머리에 두 선 이름 범례와 「겹침 끄기」. fail = 시계열을 못 받았을 때 차트 대신 한 줄.
 */
export function FlowPanel({ name, short, pts, decimals, value, base, limit, cmp, onCmpOff, fail, className }: {
  name: string; short?: string; pts?: Pt[]; decimals: number; value: number | null; base?: Ref; limit?: Ref
  cmp?: Cmp | null; onCmpOff: () => void; fail?: string; className?: string
}) {
  const [p, setP] = useViewParam<PeriodKey>('p', '3m', PERIODS.map(o => o.key))
  const periods = slicePeriods(pts)
  const ov = cmp?.pts?.length ? overlay(periods, cmp.pts) : null
  const r52 = range52(pts)
  return (
    <Panel className={className} title="흐름">
      {fail ? <p className="m-0 text-13 text-ink-3">{fail}</p> : ov ? (
        <>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-2 text-12">
            <span className="inline-flex items-center gap-1.5 text-ink-1"><span aria-hidden className="w-4 h-0.5 bg-ink-1" />{name}</span>
            <span className="inline-flex items-center gap-1.5 text-ink-2"><span aria-hidden className="w-4 h-0.5 bg-ink-3" />{cmp!.name}</span>
            <span className="text-11 text-ink-3">첫 날 = 100</span>
            <button type="button" onClick={onCmpOff} className="ml-auto h-8 px-2 rounded-btn border border-line bg-card text-12 text-ink-2 hover:text-ink-1 cursor-pointer whitespace-nowrap">겹침 끄기</button>
          </div>
          <LineChart label={`${name} · ${cmp!.name} 겹침`} name={short ?? name} periods={ov.main} compare={[{ name: cmp!.short ?? cmp!.name, periods: ov.other }]}
            period={p} onPeriod={setP} decimals={1} />
        </>
      ) : (
        <LineChart label={name} periods={periods} period={p} onPeriod={setP} decimals={decimals} base={base} limit={limit} empty={pts ? undefined : '불러오는 중'} />
      )}
      {r52 && <div className="mt-4"><Range52 low={r52.low} high={r52.high} value={value} decimals={decimals} /></div>}
    </Panel>
  )
}

/** 알림 패널 + 벨 시트. 주소에 bell=1 이 있으면 시트가 열린 채로 온다(넘침 게이트 · 공유용). what = 문장의 주어(「이 지표가」「이 종목이」). cur = 지금 값(축척 전, U1 armSide 용). */
export function BellPanel({ id, name, what, cur }: { id: string; name: string; what: string; cur?: number | null }) {
  const [bell] = useViewParam<string>('bell', '')
  const [open, setOpen] = useState(bell === '1')
  return (
    <Panel title="알림">
      <p className="m-0 mb-3 text-13 text-ink-2">{what} 정한 값을 넘거나 크게 움직이면 알려 드립니다.</p>
      <button type="button" onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 h-9 px-3 rounded-btn bg-accent text-on-accent text-13 font-bold border-0 cursor-pointer">
        <BellPlus size={16} aria-hidden />알림 조건 추가
      </button>
      <BellSheet open={open} onClose={() => setOpen(false)} id={id} label={name} cur={cur} />
    </Panel>
  )
}

/**
 * 함께 볼 지표: 카드(누르면 그 지표 상세) + 카드 아래 「겹쳐 보기」(누르면 흐름 차트에 그 선을 겹친다 · 다시 누르면 끈다).
 * 겹칠 수 없는 화면(시계열이 0 이하로 시작 — 지수로 못 바꾼다)이면 단추를 두지 않는다.
 */
export function Related({ items, cmp, onCmp, canOverlay }: {
  items: { reg: RegRow; item?: StripItem }[]; cmp: string; onCmp: (id: string) => void; canOverlay: boolean
}) {
  const watch = useWatch()
  if (!items.length) return null
  return (
    <section className="pc:col-span-12 flex flex-col gap-2" aria-label="함께 볼 지표">
      <h2 className="m-0 text-14 font-bold text-ink-1">함께 볼 지표</h2>
      <div className="grid grid-cols-2 pc:grid-cols-4 gap-2">
        {items.map(({ reg: r, item: it }) => {
          const on = cmp === r.id
          return (
            <div key={r.id} className="flex flex-col gap-1 min-w-0">
              <div className="flex-1">
                <StripCard to={`/i/${r.id}`} watched={watch.has(r.id)} onWatch={() => watch.toggle(r.id)}
                  item={{ ...(it ?? { value: null, change: null, changePct: null, asOf: null }), id: r.id, label: r.label, short: r.short, shortM: r.shortM, decimals: r.decimals, unit: it?.unit ?? r.unit, scale: it?.scale ?? r.scale }} />
              </div>
              {canOverlay && !!it?.series?.length && (
                <button type="button" onClick={() => onCmp(on ? '' : r.id)} aria-pressed={on}
                  className={`h-8 rounded-btn border text-12 cursor-pointer whitespace-nowrap ${on ? 'border-accent bg-accent text-on-accent font-bold' : 'border-line bg-card text-ink-2 hover:text-ink-1'}`}>
                  {on ? '겹치는 중' : '겹쳐 보기'}
                </button>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
