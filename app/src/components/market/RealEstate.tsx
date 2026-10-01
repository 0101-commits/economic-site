// 시장 › 부동산 — 범위(v) 전국·수도권·시도 17·시군구·미국. 전국에서만 지표 묶음(m) 매매·전세·공급·거래량으로 카드를 거른다.
// 지역(수도권·시도·시군구) 값은 묶음에 「아파트 매매가격지수 전월비」 하나뿐이다.
import { useState, type ReactNode } from 'react'
import type { StripItem } from '../../lib/bundle'
import { fmtChange, fmtNumber, scaled, shortDate } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { AsOfBadge, SegBar } from '../ui'
import { DivergingBars, Heatmap } from '../charts'
import { Panel, RankTable, StripCard, type Col } from '../panels'
import { BigChart, ChangeText, Empty, MarketGrid, poolOf, type BodyProps } from './parts'

type Sub = { name: string; chgPct: number | null }
type Area = { name?: string; period?: string; subs: Sub[] }
export type RealEstateBundle = {
  strip: StripItem[]
  views?: {
    kr?: StripItem[]
    regions?: { state?: string; items: { code: string; name?: string; chgPct: number | null; period?: string }[] }
    regionSub?: { state?: string; items: Record<string, Area> }
    capital?: Record<string, Area>
    us?: StripItem[]
    usStates?: { state?: string; items: Record<string, { value: number | null; chgPct: number | null; period?: string }> }
  }
}

const SCOPES = [{ key: 'national', label: '전국' }, { key: 'capital', label: '수도권' }, { key: 'sido', label: '시도 17' }, { key: 'sigungu', label: '시군구' }, { key: 'us', label: '미국' }] as const
const METRICS = [{ key: 'all', label: '전체' }, { key: 'sale', label: '매매' }, { key: 'jeonse', label: '전세' }, { key: 'supply', label: '공급' }, { key: 'volume', label: '거래량' }] as const
type Scope = typeof SCOPES[number]['key']
type Metric = typeof METRICS[number]['key']
// 지표 묶음 → 묶음 kr 칸 id(묶음에 분류 칸이 없어 id 로 가른다)
const METRIC_IDS: Record<Exclude<Metric, 'all'>, string[]> = {
  sale: ['apt_price_idx_kr'],
  jeonse: ['jns_price_idx_kr', 'avg_jeonse_price_kr', 'semi_jeonse_idx_kr'],
  supply: ['housing_start_kr', 'housing_permit_kr', 'housing_complete_kr', 'unsold_total_kr'],
  volume: ['trade_count_kr_rone_kr', 'trade_count_kr'],
}
const CAPITAL = [{ key: '11', label: '서울' }, { key: '41', label: '경기' }, { key: '28', label: '인천' }] as const
type CapKey = typeof CAPITAL[number]['key']
const REGION_NOTE = '아파트 매매가격지수 전월비(%)'

type SubRow = Sub & { gap: number | null }
const subCols: Col<SubRow>[] = [
  { key: 'name', label: '지역', get: r => r.name, role: 'name' },
  { key: 'pct', label: '전월비', get: r => r.chgPct, num: true, role: 'value', render: r => <ChangeText pct={r.chgPct} /> },
  { key: 'gap', label: '전국 대비', get: r => r.gap, num: true, role: 'change', render: r => (r.gap == null ? null : `${fmtChange(r.gap, null, 2)}%p`) },
]
type StateRow = { st: string; value: number | null; chgPct: number | null; period?: string }
const stateCols: Col<StateRow>[] = [
  { key: 'st', label: '주', get: r => r.st, role: 'name' },
  { key: 'value', label: '지수', get: r => r.value, num: true, decimals: 1, role: 'value' },
  { key: 'pct', label: '전기비', get: r => r.chgPct, num: true, role: 'change', render: r => <ChangeText pct={r.chgPct} /> },
  { key: 'period', label: '기준', get: r => r.period, role: 'sub', render: r => (r.period ? shortDate(r.period) : null) },
]

export default function RealEstate({ b, selId, setS }: BodyProps<RealEstateBundle>) {
  const [v, setV] = useViewParam<Scope>('v', 'national', SCOPES.map(o => o.key))
  const [m, setM] = useViewParam<Metric>('m', 'all', METRICS.map(o => o.key))
  const [cap, setCap] = useState<CapKey>('11')
  const vw = b.views
  const subKeys = Object.keys(vw?.regionSub?.items ?? {})
  const [sido, setSido] = useState(subKeys[0] ?? '11')
  const pool = poolOf(b.strip, vw?.kr, vw?.us)
  const sel = pool.get(selId) ?? b.strip[0]
  const kr = (id: string) => pool.get(id)
  const nat = kr('apt_price_idx_kr')?.changePct ?? null
  const gapRows = (subs: Sub[]): SubRow[] => subs.map(x => ({ ...x, gap: x.chgPct != null && nat != null ? x.chgPct - nat : null }))
  const cards = (items: StripItem[] | undefined) => (
    <ul className="m-0 p-0 list-none grid grid-cols-2 gap-2">
      {(items ?? []).map(it => <li key={it.id}><StripCard item={it} selected={sel?.id === it.id} onSelect={() => setS(it.id)} /></li>)}
    </ul>
  )

  const blocks: Record<Scope, ((cls: string, primary: boolean) => ReactNode)[]> = {
    national: [
      cls => (
        <Panel className={cls} title={`전국 ${m === 'all' ? '지표' : METRICS.find(o => o.key === m)!.label}`}>
          {cards(m === 'all' ? vw?.kr : vw?.kr?.filter(x => METRIC_IDS[m].includes(x.id)))}
        </Panel>
      ),
      cls => (
        <Panel className={cls} title="공급 4종">
          <ul className="m-0 p-0 list-none">
            {METRIC_IDS.supply.map(id => kr(id)).filter((x): x is StripItem => !!x).map(it => (
              <li key={it.id} className="flex flex-wrap items-baseline justify-between gap-x-3 py-1.5 border-b border-line last:border-b-0">
                <span className="text-13 text-ink-1">{it.short || it.label}</span>
                <span className="flex items-baseline gap-2">
                  <span className="num text-14 font-bold text-ink-1">{fmtNumber(scaled(it.value, it.scale), 0)}</span>
                  <ChangeText chg={it.change} pct={it.changePct} />
                  <AsOfBadge asOf={it.asOf} state={it.state} />
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      ),
    ],
    capital: [
      cls => {
        const area = vw?.capital?.[cap]
        return (
          <Panel className={cls} title={`${CAPITAL.find(o => o.key === cap)!.label} 구별`} source={REGION_NOTE} asOf={area?.period} state={vw?.regionSub?.state}>
            <div className="mb-3"><SegBar label="수도권 시도" options={CAPITAL} value={cap} onChange={setCap} /></div>
            {area?.subs.length ? <RankTable label={`${area.name ?? ''} 구별 매매가격지수 전월비`} cols={subCols} rows={gapRows(area.subs)} rowKey={r => r.name} /> : <Empty>구별 자료가 없습니다.</Empty>}
          </Panel>
        )
      },
      cls => {
        const reg = new Map((vw?.regions?.items ?? []).map(x => [x.code, x.chgPct]))
        return (
          <Panel className={cls} title="전국 대비" source={REGION_NOTE} state={vw?.regions?.state}>
            <DivergingBars decimals={2} label="전국과 수도권 시도 매매가격지수 전월비(%)" bars={[
              { key: 'nat', label: '전국', value: nat },
              ...CAPITAL.map(c => ({ key: c.key, label: c.label, value: reg.get(c.key) ?? null })),
            ]} />
            <p className="m-0 mt-2 text-11 text-ink-3">전국 = 아파트 매매지수 전월비(묶음 kr), 시도 = 지역별 표</p>
          </Panel>
        )
      },
    ],
    sido: [
      cls => (
        <Panel className={cls} title="시도 17" source={REGION_NOTE} asOf={vw?.regions?.items[0]?.period} state={vw?.regions?.state}>
          {vw?.regions?.items.length ? (
            <>
              <Heatmap label="시도별 매매가격지수 전월비" minCell={72} cells={vw.regions.items.map(x => ({ key: x.code, name: x.name ?? x.code, value: x.chgPct }))}
                onPick={c => { if (vw.regionSub?.items[c.key]) { setSido(c.key); setV('sigungu') } }} />
              <p className="m-0 mt-2 text-11 text-ink-3">칸을 누르면 그 시도의 시군구 표로 갑니다(시군구 자료가 있는 시도만).</p>
            </>
          ) : <Empty>시도 자료가 없습니다.</Empty>}
        </Panel>
      ),
    ],
    sigungu: [
      cls => {
        const area = vw?.regionSub?.items[sido]
        return (
          <Panel className={cls} title={`${area?.name ?? ''} 시군구`} source={REGION_NOTE} asOf={area?.period} state={vw?.regionSub?.state}>
            <label className="flex items-center gap-2 mb-3 text-12 text-ink-2">시도
              <select value={sido} onChange={e => setSido(e.target.value)} className="h-8 px-2 rounded-btn border border-line bg-card text-13 text-ink-1">
                {subKeys.map(k => <option key={k} value={k}>{vw!.regionSub!.items[k].name ?? k}</option>)}
              </select>
            </label>
            {area?.subs.length ? <RankTable label={`${area.name ?? ''} 시군구 매매가격지수 전월비`} cols={subCols} rows={gapRows(area.subs)} rowKey={r => r.name} /> : <Empty>시군구 자료가 없습니다.</Empty>}
          </Panel>
        )
      },
    ],
    us: [
      cls => <Panel className={cls} title="미국 주택">{cards(vw?.us)}</Panel>,
      cls => {
        const us = (id: string) => pool.get(id)
        const pair = (k: string, label: string, krV: number | null | undefined, usV: number | null | undefined) => (
          <div key={k}>
            <p className="m-0 mb-1 text-12 text-ink-2">{label}</p>
            <DivergingBars decimals={2} label={`한·미 ${label}`} bars={[{ key: 'kr', label: '한국', value: krV ?? null }, { key: 'us', label: '미국', value: usV ?? null }]} />
          </div>
        )
        return (
          <Panel className={cls} title="한·미 나란히" source="최신 달">
            <div className="flex flex-col gap-4">
              {pair('price', '집값 전월비(%)', nat, us('case_shiller_national_us')?.changePct)}
              {/* 한국 주담대 금리는 부동산 묶음에 없다(거시 묶음 mortgage_rate_kr) — 빈칸 「—」 */}
              {pair('rate', '주담대 금리(%)', kr('mortgage_rate_kr')?.value, us('mortgage_30y_us')?.value)}
              {pair('start', '착공 전월비(%)', kr('housing_start_kr')?.changePct, us('housing_starts_us')?.changePct)}
            </div>
          </Panel>
        )
      },
      cls => {
        const rows = Object.entries(vw?.usStates?.items ?? {}).map(([st, x]): StateRow => ({ st, ...x }))
        return (
          <Panel className={cls} title={`주별 집값 ${rows.length}`} source="케이스실러 주별" state={vw?.usStates?.state} fold="always">
            {rows.length ? <RankTable label="미국 주별 집값" cols={stateCols} rows={rows} rowKey={r => r.st} /> : <Empty>주별 자료가 없습니다.</Empty>}
          </Panel>
        )
      },
    ],
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <SegBar label="범위" options={SCOPES} value={v} onChange={setV} />
        {v === 'national' && <SegBar label="지표" options={METRICS} value={m} onChange={setM} />}
      </div>
      <MarketGrid blocks={[cls => <BigChart className={cls} item={sel} />, ...blocks[v]]} />
    </>
  )
}
