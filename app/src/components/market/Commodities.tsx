// 시장 › 원자재 — 목차 전체·에너지·금속·농산물(히트맵 칸의 분류) · 운임 · LME 재고(주소 v). 히트맵 칸을 누르면 그 품목이 큰 차트(주소 s)로 온다.
import { useState } from 'react'
import type { StripItem } from '../../lib/bundle'
import { changeDir, fmtNumber, shortDate } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { Heatmap } from '../charts'
import { Panel, RankTable, type Col } from '../panels'
import { BigChart, ChangeText, DIR_TEXT, Empty, MarketGrid, poolOf, Toc, type Block, type BodyProps } from './parts'

type Freight = { code: string; name: string; price: number | null; chgPct: number | null; date?: string }
/** LME 창고 재고(톤): cur = 지금, wkChg = 한 주 변화, m4ago = 4개월 전, status = 주간 방향 up·down. */
type Lme = { name: string; cur: number | null; wkChg: number | null; m4ago: number | null; status?: string }
type Premium = { pct: number | null; basis?: string; krwPerG?: number | null; usdPerOz?: number | null; usdkrw?: number | null; asOf?: Record<string, string | null>; state?: string; formula?: string }
export type CommoditiesBundle = {
  strip: StripItem[]
  views?: {
    items?: StripItem[]
    freight?: { state?: string; items: Freight[] }
    lme?: { asOf?: string; state?: string; items: Lme[] }
    enso?: { line?: string; asOf?: string; state?: string }
    goldPremium?: Premium
  }
}

const VIEWS = [{ key: 'all', label: '전체' }, { key: 'energy', label: '에너지' }, { key: 'metal', label: '금속' }, { key: 'agri', label: '농산물' }, { key: 'freight', label: '운임' }, { key: 'lme', label: 'LME 재고' }] as const
type View = typeof VIEWS[number]['key']
type Group = Exclude<View, 'freight' | 'lme'>
const isGroup = (k: View): k is Group => k !== 'freight' && k !== 'lme'
// 목차: 분류 넷은 히트맵 칸으로 데려가며 그 칸의 분류를 바꾸고, 운임 · LME 재고는 제 칸으로
const TOC = VIEWS.map(o => (isGroup(o.key) ? { ...o, to: 'heat' } : o))
// ponytail: 묶음 items 에 분류 칸이 없어 id 로 가른다. 묶음이 group 을 실으면 이 표를 지우고 그것을 쓴다.
const GROUP: Record<string, 'energy' | 'metal' | 'agri'> = {
  wti: 'energy', brent: 'energy', dubai: 'energy', natgas: 'energy', gasoline: 'energy', heatingoil: 'energy',
  gold: 'metal', goldkrw: 'metal', silver: 'metal', platinum: 'metal', palladium: 'metal', copper: 'metal', aluminum: 'metal',
  wheat: 'agri', corn: 'agri', soybean: 'agri', rice: 'agri', coffee: 'agri', sugar: 'agri', cocoa: 'agri',
}
// 묶음 이름은 LME 영문 그대로 온다
const LME_KO: Record<string, string> = { Copper: '구리', Aluminum: '알루미늄', Zinc: '아연', Nickel: '니켈', Lead: '납', Tin: '주석' }
const LME_DIR: Record<string, string> = { up: '증가', down: '감소' }
const BASIS: Record<string, string> = { sameDay: '국내 기준일과 같은 날 국제 종가로 계산', spot: '기준일이 없어 지금 값끼리 계산' }

const freightCols: Col<Freight>[] = [
  { key: 'name', label: '지수', get: r => r.name, role: 'name' },
  { key: 'price', label: '값', get: r => r.price, num: true, decimals: 1, role: 'value' },
  { key: 'pct', label: '등락률', get: r => r.chgPct, num: true, role: 'change', render: r => <ChangeText pct={r.chgPct} /> },
  { key: 'date', label: '기준', get: r => r.date, role: 'sub', render: r => (r.date ? shortDate(r.date) : null) },
]

const signedNum = (v: number | null) => (v == null ? null : `${v > 0 ? '+' : ''}${fmtNumber(v)}`)
const lmeCols: Col<Lme>[] = [
  { key: 'name', label: '품목', get: r => LME_KO[r.name] ?? r.name, role: 'name' },
  { key: 'cur', label: '현재', get: r => r.cur, num: true, role: 'value' },
  { key: 'wk', label: '주간 변화', get: r => r.wkChg, num: true, role: 'change',
    render: r => <span className={`num ${DIR_TEXT[changeDir(r.wkChg, 0)]}`}>{signedNum(r.wkChg) ?? '—'}</span> },
  { key: 'm4', label: '4개월 전', get: r => r.m4ago, num: true },
  { key: 'status', label: '상태', get: r => (r.status ? LME_DIR[r.status] ?? r.status : null), role: 'sub' },
]

export default function Commodities({ b, selId, setS }: BodyProps<CommoditiesBundle>) {
  const [v, setV] = useViewParam<View>('v', 'all', VIEWS.map(o => o.key))
  const [grp, setGrp] = useState<Group>(isGroup(v) ? v : 'all')
  const vw = b.views
  const pool = poolOf(b.strip, vw?.items)
  const sel = pool.get(selId) ?? b.strip[0]
  const group = grp === 'all' ? null : grp
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

  // PC 는 8칸 폭까지만(12열 격자 gap 1rem 기준 8열 = (전체 − 11rem) × 2/3 + 7rem) — 다섯 열이 12칸에 퍼지면 열 사이가 너무 멀다
  const lme = (cls: string, primary: boolean) => (
    <Panel className={`${cls} pc:max-w-[calc((100%-11rem)*2/3+7rem)]`} title="LME 재고" unit="톤" asOf={vw?.lme?.asOf} state={vw?.lme?.state} fold={!primary}>
      {vw?.lme?.items.length ? <RankTable label="LME 창고 재고" cols={lmeCols} rows={vw.lme.items} rowKey={r => r.name} /> : <Empty>LME 재고 자료가 없습니다.</Empty>}
    </Panel>
  )

  // LME 재고는 맨 끝 — 표 다섯 열이 PC 4칸 자리(약 345px)에 안 들어가 끝 줄을 혼자 쓴다(패널은 8칸 폭까지)
  const blocks: [string, Block][] = [['heat', heat], ['freight', freight], ['premium', premium], ['enso', enso], ['lme', lme]]
  return (
    <>
      <Toc where="원자재" items={TOC} onPick={k => { if (isGroup(k)) setGrp(k); setV(k) }} on={k => !isGroup(k) || k === grp} />
      <MarketGrid blocks={[['big', cls => <BigChart className={cls} item={sel} />], ...blocks]} />
    </>
  )
}
