// 내 자산 — 기획안 v4 6장. 첫 블록(총평가·오늘 손익·원금) → 띠 카드 4 → 보기 바 → 고른 보기 패널 → 격자.
// 보유·스냅샷·원장을 읽는 코드는 전부 Holdings 안에 있다 — PinGate 가 열기 전엔 만들어지지 않는다.
// 입력은 이 기기(localStorage)에만 저장한다. 서버 동기화(내 암호로 잠근 뒤 올리기)는 후속.
// 시세: 묶음에 있는 종목은 묶음 값, 없는 종목은 Worker 프록시로 Yahoo(lib/personal/quotes.ts) — 잠금 안에서만 받는다.
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Pencil, Trash2, Wallet } from 'lucide-react'
import { PinGate } from '../components/PinGate'
import { AsOfBadge, Card, SegBar } from '../components/ui'
import { Panel, RankTable, type Col } from '../components/panels'
import { DivergingBars, LineChart } from '../components/charts'
import { WeightMap } from '../components/personal/WeightMap'
import { BTN, BTN2, DIR_TEXT, Field, INPUT, ShareBar, Switch } from '../components/personal/bits'
import { changeDir, fmtNumber, fmtPct, shortDate, slicePeriods, type Pt } from '../lib/format'
import { useViewParam } from '../lib/useViewParam'
import { evaluate, fmtMoney, fmtMoneyChange, fxWhatIf, kstDay, moneyDir, npsDomesticShare, risk, RISK_MIN, type Holding, type Quote, type Row, type Unit } from '../lib/personal/calc'
import type { Sched } from '../lib/bundle'
import { loadMarketData, type MarketData } from '../lib/personal/data'
import { holdingQuotes } from '../lib/personal/quotes'
import { newId, readLedger, readPortfolio, readPrefs, readSnaps, saveTodaySnap, writeLedger, writePortfolio, type Ledger } from '../lib/personal/store'

const VIEWS = [
  { key: 'hold', label: '보유' }, { key: 'pnl', label: '손익 분해' }, { key: 'risk', label: '위험' },
  { key: 'div', label: '배당' }, { key: 'ledger', label: '원장' }, { key: 'sched', label: '내 일정' },
] as const
type View = typeof VIEWS[number]['key']
const KIND = { div: '배당', dep: '입금', wd: '출금' } as const
const SAVE_FAIL = '이 기기에 저장하지 못했습니다. 시크릿 창이거나 저장 공간이 찼습니다.'

const share = (part: number, whole: number) => (whole > 0 ? (part / whole) * 100 : null)
const pctText = (p: number | null) => (p == null ? '—' : `${fmtNumber(p, 1)}%`)

export default function My() {
  return <PinGate><Holdings /></PinGate>
}

function Holdings() {
  const [pf, setPf] = useState(readPortfolio)
  const [ledger, setLedger] = useState(readLedger)
  const [snaps, setSnaps] = useState(readSnaps)
  const [unit] = useState<Unit>(() => readPrefs().settings.unit)
  const [md, setMd] = useState<MarketData | null>(null)
  const [qs, setQs] = useState<Map<string, Quote> | null>(null)   // 묶음 시세 + 묶음에 없는 보유 종목의 Yahoo 시세
  const [v, setV] = useViewParam<View>('v', 'hold', VIEWS.map(o => o.key))
  const [edit, setEdit] = useState<Holding | null>(null)
  const [msg, setMsg] = useState('')
  const [snapNote, setSnapNote] = useState('')
  useEffect(() => {
    loadMarketData().then(setMd, () => setMd({ home: null, quotes: new Map(), fx: null, nps: null, gainers: false, losers: false, halts: [] }))
  }, [])
  useEffect(() => {
    if (!md) return
    let live = true
    holdingQuotes(pf.items, md.quotes).then(m => { if (live) setQs(m) }, () => { if (live) setQs(md.quotes) })
    return () => { live = false }
  }, [md, pf.items])

  const today = kstDay()
  const month = today.slice(0, 7)
  const divs = ledger.filter(l => l.kind === 'div')
  const divToday = divs.filter(l => l.d === today).reduce((a, l) => a + l.amt, 0)
  const divMonth = divs.filter(l => l.d.startsWith(month)).reduce((a, l) => a + l.amt, 0)
  const { rows, totals } = useMemo(() => evaluate(pf.items, qs ?? md?.quotes ?? new Map(), md?.fx ?? null, divToday), [pf.items, qs, md, divToday])
  const yahooN = qs && md ? pf.items.filter(it => !md.quotes.has(it.symbol) && qs.has(it.symbol)).length : 0
  const rk = useMemo(() => risk(snaps, totals.value), [snaps, totals.value])

  // 스냅샷: 시세(묶음 + Yahoo)가 다 들어온 뒤. 시세 없는 종목이 하나라도 있으면 건너뛴다 — 일부 종목만 담긴 날이 끼면
  // 평가액 ÷ 원금 흐름이 끊겨 위험 지표가 망가지고, 같은 날 현행 화면이 쓴 온전한 스냅샷을 덮게 된다.
  // ponytail: 오늘 칸이 이미 있으면(현행 화면이 썼을 수 있다) 덮지 않는다 — 하루 첫 저장이 남는다.
  useEffect(() => {
    if (!qs || !pf.items.length) return
    if (totals.missing > 0) { setSnapNote(`시세 없는 종목이 ${totals.missing}개라 오늘 스냅샷은 건너뛰었습니다.`); return }
    if (!(totals.basisValue > 0 && totals.cost > 0)) return
    const d = new Date().toISOString().slice(0, 10)
    if (!readSnaps().some(s => s.d === d)) setSnaps(saveTodaySnap(totals.basisValue, totals.cost))
  }, [qs])   // 시세가 들어온 순간(종목을 바꿔 다시 받으면 또 — 오늘 칸이 있으면 덮지 않는다)

  const savePf = (items: Holding[]) => {
    const next = { ...readPortfolio(), items }   // 다른 탭(현행 화면)이 바꾼 그룹·알림을 덮지 않게 저장 직전에 다시 읽는다
    setMsg(writePortfolio(next) ? '' : SAVE_FAIL)
    setPf(next)
  }
  const saveHolding = (f: HoldingInput, id?: string): string => {
    const items = readPortfolio().items
    const market = f.ccy === 'USD' ? 'US' : 'KR'
    if (items.some(it => it.symbol === f.symbol && it.market === market && it.id !== id)) return '이미 담은 종목입니다.'
    const fxNow = md?.fx?.now ?? null
    const name = f.name || md?.quotes.get(f.symbol)?.name || f.symbol
    if (id) {
      savePf(items.map(it => it.id !== id ? it : {
        ...it, symbol: f.symbol, market, ccy: f.ccy, name, qty: f.qty, avg: f.avg,
        yahoo: market === 'US' ? (it.yahoo ?? f.symbol) : null,
        fxBuy: market === 'US' && f.avg != null ? (it.fxBuy || fxNow) : null,
      }))
    } else {
      savePf([...items, {
        id: newId('i'), symbol: f.symbol, market, yahoo: market === 'US' ? f.symbol : null, name, secType: 'stock', ccy: f.ccy,
        avg: f.avg, qty: f.qty, group: readPortfolio().groups[0].id,
        fxBuy: market === 'US' && f.avg != null ? fxNow : null,   // 매입 환율 = 넣는 순간의 달러원(현행 화면과 같다)
      }])
    }
    setEdit(null)
    return ''
  }
  const removeHolding = (id: string) => { savePf(readPortfolio().items.filter(it => it.id !== id)); setEdit(null) }
  const saveLedger = (a: Ledger[]) => { setMsg(writeLedger(a) ? '' : SAVE_FAIL); setLedger(readLedger()) }

  const schedule = useMemo(() => {
    const cc = new Set<string>(pf.items.map(it => (it.market === 'US' ? 'US' : 'KR')))
    return (md?.home?.schedule || []).filter(e => !cc.size || !e.cc || cc.has(e.cc))
  }, [md, pf.items])

  const div = unit === 'man' ? 1e4 : 1
  const unitLabel = unit === 'man' ? '만원' : '원'
  const trend = useMemo(() => slicePeriods(snaps.filter(s => s.ev > 0).map((s): Pt => [s.d, s.ev / div])), [snaps, div])
  const npsShare = npsDomesticShare(md?.nps?.allocation)
  const has = pf.items.length > 0
  const t = totals

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h1 className="m-0 inline-flex items-center gap-1.5 text-18 font-bold text-ink-1"><Wallet size={18} aria-hidden />내 자산</h1>
        {md?.quotesAsOf && <span className="inline-flex items-center gap-1 text-12 text-ink-3">시세 <AsOfBadge asOf={md.quotesAsOf} state={md.home?.topAmount?.state} /></span>}
        {!qs && <span className="text-12 text-ink-3">시세 불러오는 중</span>}
        {yahooN > 0 && <span className="text-12 text-ink-3">{`${yahooN}종목은 Yahoo 지연 시세`}</span>}
      </header>

      {/* 첫 블록 */}
      <Card>
        <p className="m-0 text-12 text-ink-2">총평가</p>
        <p className="m-0 num text-30 font-bold leading-tight text-ink-1">{has ? fmtMoney(t.value, unit) : '—'}</p>
        <p className={`mt-1 mb-0 num text-14 ${DIR_TEXT[moneyDir(t.today.total, unit)]}`}>
          <span className="text-12 text-ink-2">오늘 </span>{has ? fmtMoneyChange(t.today.total, t.today.pct, unit) : '—'}
        </p>
        <p className="mt-2 mb-0 text-13 text-ink-2">
          원금 <span className="num text-ink-1">{fmtMoney(t.cost || null, unit)}</span> · 총 수익률{' '}
          <span className={`num ${DIR_TEXT[changeDir(t.pnlPct, 2)]}`}>{fmtPct(t.pnlPct)}</span>
        </p>
        {!has && <p className="mt-2 mb-0 text-13 text-ink-3">아직 담은 종목이 없습니다. 아래 보유 패널에서 종목을 넣으세요.</p>}
        {qs && t.missing > 0 && <p className="mt-2 mb-0 text-12 text-ink-3">시세 없는 {t.missing}종목은 총평가에서 뺐습니다. 묶음에도 없고 Yahoo 시세도 받지 못한 종목입니다.</p>}
        {msg && <p role="alert" className="mt-2 mb-0 text-12 text-warn">{msg}</p>}
      </Card>

      {/* 띠 카드 4 */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Stat label="국내 비중" value={pctText(share(t.domestic, t.value))} sub="상장 시장 기준" />
        <Stat label="해외 비중" value={pctText(share(t.foreign, t.value))} sub="상장 시장 기준" />
        <Stat label="하루 최대 손실" value={rk.var95 != null ? fmtMoney(rk.var95, unit) : `스냅샷 쌓는 중 ${rk.n}/${RISK_MIN}`}
          sub={rk.var95 != null ? '95% · 20일 중 하루는 이보다 더 잃을 수 있음' : '60건이 모이면 보입니다'} small={rk.var95 == null} />
        <Stat label="배당 이달" value={divs.length ? fmtMoney(divMonth, unit) : '기록 없음'} sub={divs.length ? '원장 기준' : '원장에 배당을 적으면 보입니다'} small={!divs.length} />
      </div>

      <SegBar label="내 자산 보기" options={VIEWS} value={v} onChange={setV} />

      {v === 'hold' && (
        <Panel title="보유" unit={unitLabel}>
          <HoldTable rows={rows} unit={unit} onEdit={setEdit} />
          <HoldingForm key={edit?.id ?? 'new'} edit={edit} onSave={saveHolding} onDelete={removeHolding} onCancel={() => setEdit(null)} />
          <div className="mt-4 pt-3 border-t border-line">
            <Switch on={false} disabled label="평단가·수량 동기화(내 암호)" />
            <p className="mt-1 mb-0 text-12 text-ink-3">다음 단계에서 연결합니다. 켜면 내 암호로 잠근 뒤 올리므로 서버는 내용을 못 읽습니다. 지금은 이 기기에만 저장됩니다.</p>
          </div>
        </Panel>
      )}
      {v === 'pnl' && (
        <Panel title="손익 분해" unit={unitLabel}>
          <PnlTable rows={rows} unit={unit} />
          <p className="mt-2 mb-0 text-12 text-ink-3">오늘 몫은 전일가 = 지금가 ÷ (1 + 등락률)로 거꾸로 구했습니다. 달러 종목의 환차는 지금가 × 수량 × 환율 변화입니다.</p>
        </Panel>
      )}
      {v === 'risk' && <RiskPanel rk={rk} unit={unit} />}
      {v === 'div' && <DividendPanel divs={divs} month={month} unit={unit} />}
      {v === 'ledger' && <LedgerPanel ledger={ledger} today={today} unit={unit} onSave={saveLedger} />}
      {v === 'sched' && <SchedulePanel items={schedule} today={md?.home?.market?.today} all className="" />}

      <div className="grid grid-cols-1 pc:grid-cols-12 gap-4 items-start">
        <Panel className="pc:col-span-6" title="보유 지도" source="넓이 = 비중 · 색 = 오늘 등락">
          {rows.some(r => r.value) ? (
            <WeightMap label="보유 종목 비중과 오늘 등락률"
              cells={rows.filter(r => r.value).sort((a, b) => b.value! - a.value!).map(r => ({ key: r.h.id, name: r.h.name || r.h.symbol, value: r.q?.pct ?? null, weight: r.value! }))} />
          ) : <p className="m-0 text-13 text-ink-3">시세 있는 보유 종목이 없습니다.</p>}
          {t.missing > 0 && <p className="mt-2 mb-0 text-12 text-ink-3">시세 없는 {t.missing}종목은 지도에 없습니다.</p>}
        </Panel>

        <Panel className="pc:col-span-6" title="평가액 추이" unit={unitLabel} source={`스냅샷 ${snaps.length}건`}>
          <LineChart label="평가액" periods={trend} decimals={0} empty="스냅샷이 2건 이상 쌓이면 그립니다(하루 1건)" />
          {snapNote && <p className="mt-2 mb-0 text-12 text-ink-3">{snapNote}</p>}
        </Panel>

        <Panel className="pc:col-span-4" title="오늘 손익 분해" unit={unitLabel}>
          {t.value > 0 || t.today.div ? (
            <DivergingBars label={`오늘 손익 분해(${unitLabel})`} decimals={unit === 'man' ? 1 : 0} bars={[
              { key: 'price', label: '주가', value: t.today.price / div },
              { key: 'fx', label: '환차', value: t.today.fx / div },
              { key: 'div', label: '배당', value: t.today.div / div },
            ]} />
          ) : <p className="m-0 text-13 text-ink-3">시세 있는 보유 종목이 없습니다.</p>}
        </Panel>

        <Panel className="pc:col-span-4" title="국내 편중" source={md?.nps?.asOf ? `국민연금 ${shortDate(md.nps.asOf)}` : undefined}>
          <ul className="m-0 p-0 list-none flex flex-col gap-2">
            <ShareBar label="나" pct={has && t.value > 0 ? share(t.domestic, t.value) : null} />
            <ShareBar label="국민연금" pct={npsShare} tone="ink-3" />
          </ul>
          <p className="mt-2 mb-0 text-12 text-ink-3">
            주식 가운데 국내 비중입니다. 국민연금은 국내주식 ÷ (국내주식 + 해외주식)으로 셌고{npsShare == null ? ' 자료가 없습니다' : ''}, 나는 상장 시장 기준입니다.
          </p>
        </Panel>

        <Panel className="pc:col-span-4" title="환율 what-if" source="추정">
          <FxWhatIf value={t.value} usdValue={t.usdValue} usdMissing={rows.filter(r => r.usd && r.value == null && r.h.qty).length} fxNow={md?.fx?.now ?? null} unit={unit} />
        </Panel>

        {v !== 'sched' && <SchedulePanel items={schedule.slice(0, 5)} today={md?.home?.market?.today} className="pc:col-span-12" />}
      </div>
    </div>
  )
}

function Stat({ label, value, sub, small }: { label: string; value: string; sub: string; small?: boolean }) {
  return (
    <Card dense>
      <p className="m-0 text-12 text-ink-2">{label}</p>
      <p className={`mt-1 mb-0 font-bold leading-tight text-ink-1 ${small ? 'text-14' : 'num text-18'}`}>{value}</p>
      <p className="mt-1 mb-0 text-11 leading-snug text-ink-3">{sub}</p>
    </Card>
  )
}

const money = (unit: Unit) => (v: number | null | undefined) => (v == null ? null : fmtMoney(v, unit))
const pctCell = (p: number | null | undefined) => <span className={`num ${DIR_TEXT[changeDir(p, 2)]}`}>{fmtPct(p)}</span>

function HoldTable({ rows, unit, onEdit }: { rows: Row[]; unit: Unit; onEdit: (h: Holding) => void }) {
  if (!rows.length) return <p className="m-0 text-13 text-ink-3">담은 종목이 없습니다.</p>
  const m = money(unit)
  const cols: Col<Row>[] = [
    { key: 'name', label: '종목', get: r => r.h.name || r.h.symbol, role: 'name' },
    { key: 'qty', label: '수량', get: r => r.h.qty, num: true, role: 'sub', render: r => `${r.h.symbol} · ${fmtNumber(r.h.qty, r.h.qty != null && r.h.qty % 1 ? 2 : 0)}주` },
    { key: 'value', label: '평가액', get: r => r.value, num: true, role: 'value', render: r => m(r.value) ?? <span className="text-ink-3">시세 없음</span> },
    { key: 'pnlPct', label: '수익률', get: r => r.pnlPct, num: true, role: 'change', render: r => pctCell(r.pnlPct) },
    { key: 'today', label: '오늘', get: r => r.q?.pct, num: true, render: r => pctCell(r.q?.pct) },
    { key: 'avg', label: '평단가', get: r => r.h.avg, num: true, render: r => (r.h.avg == null ? null : `${fmtNumber(r.h.avg, r.usd ? 2 : 0)}${r.usd ? '달러' : '원'}`) },
    { key: 'cost', label: '원금', get: r => r.cost, num: true, render: r => m(r.cost) },
    { key: 'pnl', label: '평가손익', get: r => r.pnl, num: true, render: r => (r.pnl == null ? null : <span className={`num ${DIR_TEXT[moneyDir(r.pnl, unit)]}`}>{fmtMoneyChange(r.pnl, null, unit)}</span>) },
  ]
  return (
    <RankTable label="보유 종목" cols={cols} rows={rows} rowKey={r => r.h.id}
      lead={r => (
        <button type="button" onClick={e => { e.stopPropagation(); onEdit(r.h) }} aria-label={`${r.h.name || r.h.symbol} 고치기`} title="고치기"
          className="size-8 shrink-0 inline-flex items-center justify-center rounded-btn border-0 bg-transparent text-ink-3 hover:text-ink-1 cursor-pointer">
          <Pencil size={14} aria-hidden />
        </button>
      )} />
  )
}

function PnlTable({ rows, unit }: { rows: Row[]; unit: Unit }) {
  const live = rows.filter(r => r.value != null)
  if (!live.length) return <p className="m-0 text-13 text-ink-3">시세 있는 보유 종목이 없습니다.</p>
  const chg = (v: number | null | undefined) => (v == null ? null : <span className={`num ${DIR_TEXT[moneyDir(v, unit)]}`}>{fmtMoneyChange(v, null, unit)}</span>)
  const cols: Col<Row>[] = [
    { key: 'name', label: '종목', get: r => r.h.name || r.h.symbol, role: 'name' },
    { key: 'tsum', label: '오늘 합', get: r => (r.today ? r.today.price + r.today.fx : null), num: true, role: 'sub', render: r => chg(r.today ? r.today.price + r.today.fx : null) },
    { key: 'pnl', label: '평가손익', get: r => r.pnl, num: true, role: 'value', render: r => chg(r.pnl) },
    { key: 'pnlPct', label: '수익률', get: r => r.pnlPct, num: true, role: 'change', render: r => pctCell(r.pnlPct) },
    { key: 'tprice', label: '오늘 주가 몫', get: r => r.today?.price, num: true, render: r => chg(r.today?.price) },
    { key: 'tfx', label: '오늘 환차 몫', get: r => (r.usd ? r.today?.fx : null), num: true, render: r => (r.usd ? chg(r.today?.fx) : null) },
  ]
  return <RankTable label="종목별 손익 분해" cols={cols} rows={live} rowKey={r => r.h.id} />
}

type HoldingInput = { symbol: string; name: string; qty: number | null; avg: number | null; ccy: 'KRW' | 'USD' }
const num = (s: string) => (s.trim() === '' ? null : Number(s.replace(/,/g, '')))

/** 종목 추가·수정 폼: 코드·이름·수량·평단가·통화. 숫자는 0 이상만, 빈칸은 「아직 모름」. */
function HoldingForm({ edit, onSave, onDelete, onCancel }: {
  edit: Holding | null; onSave: (f: HoldingInput, id?: string) => string; onDelete: (id: string) => void; onCancel: () => void
}) {
  const [symbol, setSymbol] = useState(edit?.symbol ?? '')
  const [name, setName] = useState(edit?.name ?? '')
  const [qty, setQty] = useState(edit?.qty != null ? String(edit.qty) : '')
  const [avg, setAvg] = useState(edit?.avg != null ? String(edit.avg) : '')
  const [ccy, setCcy] = useState<'KRW' | 'USD'>(edit ? (edit.ccy ?? (edit.market === 'US' ? 'USD' : 'KRW')) : 'KRW')
  const [err, setErr] = useState('')
  const submit = (e: FormEvent) => {
    e.preventDefault()
    const sym = symbol.trim().toUpperCase()
    const okSym = ccy === 'KRW' ? /^[0-9A-Z]{6}$/.test(sym) : /^[A-Z][A-Z0-9.-]{0,9}$/.test(sym)
    if (!okSym) { setErr(ccy === 'KRW' ? '국내 종목 코드는 6자리입니다(예: 005930).' : '미국 종목은 티커를 넣으세요(예: AAPL).'); return }
    const q = num(qty), a = num(avg)
    if ([q, a].some(x => x != null && !(Number.isFinite(x) && x >= 0))) { setErr('수량·평단가에는 0 이상의 숫자만 넣을 수 있습니다.'); return }
    const r = onSave({ symbol: sym, name: name.trim().slice(0, 40), qty: q || null, avg: a || null, ccy }, edit?.id)
    setErr(r)
    if (!r && !edit) { setSymbol(''); setName(''); setQty(''); setAvg('') }
  }
  return (
    <form onSubmit={submit} className="mt-4 pt-3 border-t border-line" aria-label={edit ? '보유 종목 고치기' : '종목 추가'}>
      <h3 className="m-0 mb-2 text-13 font-bold text-ink-1">{edit ? `${edit.name || edit.symbol} 고치기` : '종목 추가'}</h3>
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        <Field label="코드"><input className={INPUT} value={symbol} onChange={e => setSymbol(e.target.value)} placeholder="005930 · AAPL" autoComplete="off" /></Field>
        <Field label="이름"><input className={INPUT} value={name} onChange={e => setName(e.target.value)} placeholder="비우면 코드" maxLength={40} /></Field>
        <Field label="수량"><input className={INPUT} value={qty} onChange={e => setQty(e.target.value)} inputMode="decimal" placeholder="0" /></Field>
        <Field label="평단가"><input className={INPUT} value={avg} onChange={e => setAvg(e.target.value)} inputMode="decimal" placeholder={ccy === 'USD' ? '달러' : '원'} /></Field>
        <Field label="통화">
          <select className={INPUT} value={ccy} onChange={e => setCcy(e.target.value as 'KRW' | 'USD')}>
            <option value="KRW">원(국내)</option><option value="USD">달러(미국)</option>
          </select>
        </Field>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button type="submit" className={BTN}>{edit ? '고친 내용 저장' : '추가'}</button>
        {edit && <button type="button" className={BTN2} onClick={onCancel}>취소</button>}
        {edit && (
          <button type="button" className={`${BTN2} inline-flex items-center gap-1`}
            onClick={() => { if (confirm(`${edit.name || edit.symbol} 을(를) 보유에서 뺄까요?`)) onDelete(edit.id) }}>
            <Trash2 size={14} aria-hidden /> 빼기
          </button>
        )}
        <span role="alert" className="text-12 text-warn">{err}</span>
      </div>
      <p className="mt-2 mb-0 text-12 text-ink-3">달러 종목은 평단가를 넣는 순간의 달러원을 매입 환율로 적어 두고, 환차를 그 값으로 가릅니다.</p>
    </form>
  )
}

function RiskPanel({ rk, unit }: { rk: ReturnType<typeof risk>; unit: Unit }) {
  return (
    <Panel title="위험">
      {rk.var95 == null ? (
        <p className="m-0 text-13 text-ink-2">
          스냅샷 쌓는 중 <span className="num font-bold text-ink-1">{`${rk.n}/${RISK_MIN}`}</span>. 시세가 모두 있는 날 내 자산을 열 때마다 하루 1건씩 쌓입니다.
          60건이 안 되면 믿을 만한 범위가 아니어서 수치를 보이지 않습니다.
        </p>
      ) : (
        <>
          <dl className="m-0 grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div><dt className="text-12 text-ink-2">하루 최대 손실(95%)</dt><dd className="m-0 num text-18 font-bold text-down">{fmtMoney(rk.var95, unit)}</dd></div>
            <div><dt className="text-12 text-ink-2">하루 변동성</dt><dd className="m-0 num text-18 font-bold text-ink-1">{`${fmtNumber(rk.sd! * 100, 2)}%`}</dd></div>
            <div><dt className="text-12 text-ink-2">최대 낙폭</dt><dd className="m-0 num text-18 font-bold text-down">{`${fmtNumber(rk.mdd, 1)}%`}</dd></div>
          </dl>
          <p className="mt-2 mb-0 text-12 text-ink-3">하루 수익률 {rk.n}건 기준 · 평가액 × 하루 변동성 × 1.645 · 정규분포를 가정한 추정이며 최악을 보증하지 않습니다.</p>
        </>
      )}
    </Panel>
  )
}

function DividendPanel({ divs, month, unit }: { divs: Ledger[]; month: string; unit: Unit }) {
  const mine = divs.filter(l => l.d.startsWith(month))
  const [y, m] = month.split('-').map(Number)
  const from = `${y - 1}-${String(m).padStart(2, '0')}`
  const year = divs.filter(l => l.d.slice(0, 7) > from).reduce((a, l) => a + l.amt, 0)
  return (
    <Panel title="배당" unit={unit === 'man' ? '만원' : '원'}>
      {!divs.length ? <p className="m-0 text-13 text-ink-3">원장에 배당 기록이 없습니다. 원장 보기에서 배당을 적으세요.</p> : (
        <>
          <p className="m-0 text-13 text-ink-2">최근 12개월 합 <span className="num font-bold text-ink-1">{fmtMoney(year, unit)}</span></p>
          {mine.length ? <LedgerList items={mine} unit={unit} /> : <p className="mt-2 mb-0 text-13 text-ink-3">이달 배당 기록은 없습니다.</p>}
        </>
      )}
    </Panel>
  )
}

function LedgerList({ items, unit, onDelete }: { items: Ledger[]; unit: Unit; onDelete?: (id: string) => void }) {
  return (
    <ul className="m-0 mt-2 p-0 list-none">
      {[...items].reverse().map(l => (
        <li key={l.id} className="flex items-center gap-3 py-1.5 border-b border-line last:border-b-0 text-13">
          <span className="w-[4.5rem] shrink-0 num text-12 text-ink-3">{shortDate(l.d)}</span>
          <span className="w-10 shrink-0 text-ink-2">{KIND[l.kind] ?? l.kind}</span>
          <span className="flex-1 min-w-0 text-ink-3">{l.memo}</span>
          <span className="shrink-0 num text-ink-1">{fmtMoney(l.amt, unit)}</span>
          {onDelete && (
            <button type="button" onClick={() => onDelete(l.id)} aria-label={`${shortDate(l.d)} ${KIND[l.kind] ?? ''} 기록 지우기`} title="지우기"
              className="size-8 shrink-0 inline-flex items-center justify-center rounded-btn border-0 bg-transparent text-ink-3 hover:text-ink-1 cursor-pointer">
              <Trash2 size={14} aria-hidden />
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}

/** 배당·입출금 원장 — 현행 pfLedgerV1 과 같은 모양. 서버로 보내지 않는다. */
function LedgerPanel({ ledger, today, unit, onSave }: { ledger: Ledger[]; today: string; unit: Unit; onSave: (a: Ledger[]) => void }) {
  const [d, setD] = useState(today)
  const [kind, setKind] = useState<Ledger['kind']>('div')
  const [amt, setAmt] = useState('')
  const [memo, setMemo] = useState('')
  const [err, setErr] = useState('')
  const add = (e: FormEvent) => {
    e.preventDefault()
    const a = num(amt)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d) || a == null || !(a > 0)) { setErr('날짜와 0보다 큰 금액(원)을 넣으세요.'); return }
    onSave([...ledger, { id: newId('L'), d, kind, amt: a, memo: memo.trim().slice(0, 40) }])
    setAmt(''); setMemo(''); setErr('')
  }
  return (
    <Panel title="원장" source={`이 기기에만 저장 · ${ledger.length}건`}>
      <form onSubmit={add} className="grid grid-cols-2 sm:grid-cols-5 gap-2 items-end" aria-label="원장 기록 추가">
        <Field label="날짜"><input type="date" className={INPUT} value={d} onChange={e => setD(e.target.value)} /></Field>
        <Field label="종류">
          <select className={INPUT} value={kind} onChange={e => setKind(e.target.value as Ledger['kind'])}>
            <option value="div">배당</option><option value="dep">입금</option><option value="wd">출금</option>
          </select>
        </Field>
        <Field label="금액(원)"><input className={INPUT} value={amt} onChange={e => setAmt(e.target.value)} inputMode="decimal" placeholder="0" /></Field>
        <Field label="메모"><input className={INPUT} value={memo} onChange={e => setMemo(e.target.value)} maxLength={40} placeholder="선택" /></Field>
        <button type="submit" className={BTN}>기록</button>
      </form>
      <p role="alert" className="min-h-5 mt-1 mb-0 text-12 text-warn">{err}</p>
      {ledger.length ? <LedgerList items={ledger} unit={unit} onDelete={id => onSave(ledger.filter(l => l.id !== id))} /> : <p className="m-0 text-13 text-ink-3">기록이 없습니다. 배당을 적으면 오늘 손익 분해와 배당 칸에 들어갑니다.</p>}
    </Panel>
  )
}

function SchedulePanel({ items, today, all, className }: { items: Sched[]; today?: string; all?: boolean; className: string }) {
  return (
    <Panel className={className} title="내 종목 일정" source="보유 종목 나라의 지표 일정">
      {items.length ? (
        <ul className="m-0 p-0 list-none">
          {items.map((e, i) => (
            <li key={`${e.date}-${e.name}-${i}`} className="flex items-baseline gap-3 py-1.5 border-b border-line last:border-b-0">
              <span className="w-[5.5rem] shrink-0 num text-12 text-ink-3">{`${e.date === today ? '오늘' : shortDate(e.date)}${e.time ? ` ${e.time}` : ''}`}</span>
              <span className="flex-1 min-w-0 text-13 text-ink-1">{e.name}{e.approx ? <span className="text-ink-3"> (추정)</span> : null}</span>
              {!!e.stars && <span className="shrink-0 text-11 text-ink-3" aria-label={`중요도 ${e.stars}`}>{'★'.repeat(e.stars)}</span>}
            </li>
          ))}
        </ul>
      ) : <p className="m-0 text-13 text-ink-3">다가오는 일정이 없습니다.</p>}
      {all && <p className="mt-2 mb-0 text-12 text-ink-3">종목별 일정(실적 발표·배당락)은 자료에 없어 나라별 지표 일정만 보입니다.</p>}
    </Panel>
  )
}

function FxWhatIf({ value, usdValue, usdMissing, fxNow, unit }: { value: number; usdValue: number; usdMissing: number; fxNow: number | null; unit: Unit }) {
  const [p, setP] = useState(0)
  if (!(usdValue > 0)) {
    return <p className="m-0 text-13 text-ink-3">{usdMissing ? `달러 종목 ${usdMissing}개의 시세가 없어 셈할 수 없습니다.` : '달러 자산이 없어 환율이 움직여도 총평가는 같습니다.'}</p>
  }
  const r = fxWhatIf(value, usdValue, p)
  return (
    <div className="flex flex-col gap-2">
      <label className="flex flex-col gap-1">
        <span className="text-12 text-ink-2">달러원 <span className="num text-ink-1">{`${p > 0 ? '+' : ''}${p}%`}</span>
          {fxNow != null && <> · <span className="num">{`${fmtNumber(fxNow * (1 + p / 100), 1)}원`}</span></>}</span>
        <input type="range" min={-10} max={10} step={1} value={p} onChange={e => setP(Number(e.target.value))} className="w-full accent-accent" aria-label="달러원 변화율" />
      </label>
      <p className="m-0 text-13 text-ink-2">
        총평가 <span className="num font-bold text-ink-1">{fmtMoney(r.total, unit)}</span>{' '}
        <span className={`num ${DIR_TEXT[moneyDir(r.delta, unit)]}`}>{fmtMoneyChange(r.delta, null, unit)}</span>
      </p>
      <p className="m-0 text-12 text-ink-3">추정입니다. 주가는 그대로 두고 달러 자산 {fmtMoney(usdValue, unit)}의 원화 값만 움직였습니다.</p>
    </div>
  )
}
