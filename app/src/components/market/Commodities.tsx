// 시장 › 원자재 — 보기 전체·에너지·금속·농산물·운임. 히트맵 칸을 누르면 그 품목이 큰 차트(주소 s)로 온다.
import type { ReactNode } from 'react'
import type { StripItem } from '../../lib/bundle'
import { fmtNumber, shortDate } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { SegBar } from '../ui'
import { Heatmap } from '../charts'
import { Panel, RankTable, type Col } from '../panels'
import { BigChart, ChangeText, Empty, MarketGrid, poolOf, type Block, type BodyProps } from './parts'

type Freight = { code: string; name: string; price: number | null; chgPct: number | null; date?: string }
type Premium = { pct: number | null; basis?: string; krwPerG?: number | null; usdPerOz?: number | null; usdkrw?: number | null; asOf?: Record<string, string | null>; state?: string; formula?: string }
export type CommoditiesBundle = {
  strip: StripItem[]
  views?: {
    items?: StripItem[]
    freight?: { state?: string; items: Freight[] }
    enso?: { line?: string; asOf?: string; state?: string }
    goldPremium?: Premium
  }
}

const VIEWS = [{ key: 'all', label: '전체' }, { key: 'energy', label: '에너지' }, { key: 'metal', label: '금속' }, { key: 'agri', label: '농산물' }, { key: 'freight', label: '운임' }] as const
type View = typeof VIEWS[number]['key']
// ponytail: 묶음 items 에 분류 칸이 없어 id 로 가른다. 묶음이 group 을 실으면 이 표를 지우고 그것을 쓴다.
const GROUP: Record<string, 'energy' | 'metal' | 'agri'> = {
  wti: 'energy', brent: 'energy', dubai: 'energy', natgas: 'energy', gasoline: 'energy', heatingoil: 'energy',
  gold: 'metal', goldkrw: 'metal', silver: 'metal', platinum: 'metal', palladium: 'metal', copper: 'metal', aluminum: 'metal',
  wheat: 'agri', corn: 'agri', soybean: 'agri', rice: 'agri', coffee: 'agri', sugar: 'agri', cocoa: 'agri',
}
const BASIS: Record<string, string> = { sameDay: '국내 기준일과 같은 날 국제 종가로 계산', spot: '기준일이 없어 지금 값끼리 계산' }

const freightCols: Col<Freight>[] = [
  { key: 'name', label: '지수', get: r => r.name, role: 'name' },
  { key: 'price', label: '값', get: r => r.price, num: true, decimals: 1, role: 'value' },
  { key: 'pct', label: '등락률', get: r => r.chgPct, num: true, role: 'change', render: r => <ChangeText pct={r.chgPct} /> },
  { key: 'date', label: '기준', get: r => r.date, role: 'sub', render: r => (r.date ? shortDate(r.date) : null) },
]

export default function Commodities({ b, selId, setS }: BodyProps<CommoditiesBundle>) {
  const [v, setV] = useViewParam<View>('v', 'all', VIEWS.map(o => o.key))
  const vw = b.views
  const pool = poolOf(b.strip, vw?.items)
  const sel = pool.get(selId) ?? b.strip[0]
  const group = v === 'all' || v === 'freight' ? null : v
  const items = (vw?.items ?? []).filter(x => !group || GROUP[x.id] === group)
  const gp = vw?.goldPremium

  const heat = (cls: string, primary: boolean) => (
    <Panel className={cls} title={`${group ? VIEWS.find(o => o.key === group)!.label : '원자재'} ${items.length}`} fold={!primary}>
      {items.length
        ? <Heatmap label="원자재 등락률" minCell={72} cells={items.map(x => ({ key: x.id, name: x.short || x.label, value: x.changePct }))} onPick={c => setS(c.key)} />
        : <Empty>원자재 자료가 없습니다.</Empty>}
    </Panel>
  )
  const freight = (cls: string, primary: boolean) => (
    <Panel className={cls} title="운임" state={vw?.freight?.state} fold={!primary}>
      {vw?.freight?.items.length ? <RankTable label="해운 운임 지수" cols={freightCols} rows={vw.freight.items} rowKey={r => r.code} /> : <Empty>운임 자료가 없습니다.</Empty>}
    </Panel>
  )
  const premium = (cls: string) => (
    <Panel className={cls} title="금 김치프리미엄" state={gp?.state} fold>
      {gp?.pct != null ? (
        <div className="flex flex-col gap-2">
          <div className="flex items-baseline gap-2">
            <span className="num text-24 font-bold text-ink-1">{`${gp.pct > 0 ? '+' : ''}${fmtNumber(gp.pct, 2)}%`}</span>
            <span className="text-12 text-ink-2">국내 금이 국제 금보다 {gp.pct >= 0 ? '비쌈' : '쌈'}</span>
          </div>
          <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-12">
            <dt className="text-ink-3">국내 금</dt><dd className="m-0 num text-ink-1">{fmtNumber(gp.krwPerG)}원/g</dd>
            <dt className="text-ink-3">국제 금</dt><dd className="m-0 num text-ink-1">{fmtNumber(gp.usdPerOz, 1)}$/oz</dd>
            <dt className="text-ink-3">달러/원</dt><dd className="m-0 num text-ink-1">{fmtNumber(gp.usdkrw, 2)}</dd>
            <dt className="text-ink-3">기준</dt><dd className="m-0 text-ink-2">{BASIS[gp.basis ?? ''] ?? gp.basis ?? '—'}</dd>
          </dl>
          {gp.formula && <p className="m-0 text-11 text-ink-3">{gp.formula}</p>}
        </div>
      ) : <Empty>금 프리미엄 자료가 없습니다.</Empty>}
    </Panel>
  )
  const enso = (cls: string) => (
    <Panel className={cls} title="엘니뇨" asOf={vw?.enso?.asOf} state={vw?.enso?.state} fold>
      {vw?.enso?.line ? <p className="m-0 text-13 text-ink-2">{vw.enso.line}</p> : <Empty>엘니뇨 자료가 없습니다.</Empty>}
    </Panel>
  )

  const blocks: [string, Block][] = v === 'freight'
    ? [['freight', freight], ['heat', heat], ['premium', premium], ['enso', enso]]
    : [['heat', heat], ['freight', freight], ['premium', premium], ['enso', enso]]
  return (
    <>
      <SegBar label="보기" options={VIEWS} value={v} onChange={setV} />
      <MarketGrid blocks={[['big', cls => <BigChart className={cls} item={sel} />], ...blocks]} />
    </>
  )
}
