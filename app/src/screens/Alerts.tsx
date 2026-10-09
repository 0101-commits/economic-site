// 알림 — 기획서 v2 7장. 탭 셋: 받은 알림(원장) · 사건(꾸러미 → 갈래 → 사건 낱개 → 내 조건 → 새 조건) · 채널.
// 폰 알림 · 동기화 키 · 받는 기기는 설정 「기기 연결」, 카톡은 설정 「고급」(명세 S5 · S7). 범위 문구는 sync.ts scopeText 두 벌.
// 받은 알림 = events/latest.json(원장 최근 7일). 원장이 아직 없으면(배포 전) 현행 발송 이력 alerts_state.json · 홈 묶음 렌즈 돌파 ·
// 국내 시장 매매중단으로 그린다. 금액 · 보유 종목명은 싣지 않는다. 이 화면은 PinGate 밖이라 portfolioV1 을 읽지 않는다 —
// 사용자 조건 줄의 이름은 이 기기 econPrefsV1.alerts 와 지표 사전에서만 찾는다(원장에는 조건 id 만 있다).
// 사건 이름 · 등급 · 갈래 · 꾸러미 · 세기 이름은 사전 lib/alerts/dict.json(scripts/alerts_v2/export_dict.py 산출)에서만 읽는다.
// 조건 행의 상태 7과 다시 켜기 규칙은 lib/personal/alertStatus.ts, 자동 정리는 lib/personal/housekeeping.ts.
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Bell, ChevronRight, Trash2 } from 'lucide-react'
import { SegBar } from '../components/ui'
import { Panel } from '../components/panels'
import { BTN, BTN2, Field, INPUT, LevelPill, LV, Row, Switch } from '../components/personal/bits'
import { loadRegistry, ROOT, type RegRow } from '../lib/bundle'
import { fmtNumber, fmtPct, mdHm, shortDate } from '../lib/format'
import { useViewParam } from '../lib/useViewParam'
import { kstDay } from '../lib/personal/calc'
import { loadMarketData, loadRootJson, type MarketData } from '../lib/personal/data'
import { KEYS, readHk, readPrefs, writeHk, writePrefs, type AlertCond, type Level, type Pkg, type Prefs, type Settings, type Strength } from '../lib/personal/store'
import { PACKAGE_PRESET, setPackage } from '../lib/personal/prefsV2'
import { condId, condName, condStatus, prefillTarget, rearm, repeatNote, TARGET_RE, type FiredRec, type LedgerRow } from '../lib/personal/alertStatus'
import type { Hk } from '../lib/personal/housekeeping'
import { portfolioGet, watchKind } from '../lib/personal/remote'
import { getKeyHash, scopeText, useSyncStatus, type SyncStatus } from '../lib/personal/sync'
import { pushSubscribed } from '../lib/push'
import { CAP_MSG } from '../components/personal/BellSheet'
import { adjustOf, ALERT_CAP, eventsFor, familyCount, FILTERS, fromLedger, groupDays, hhmm, levelChoices, listEvents, passes, savedNote, yearCounts, type Dict, type DictEvent, type FeedRow, type Filter } from '../lib/alerts/v2'
import { loadDaily } from '../lib/alerts/daily'
import { convertLegacy, type Imported } from '../lib/alerts/legacy'
import dictJson from '../lib/alerts/dict.json'

const dict = dictJson as unknown as Dict
const EV = new Map(dict.events.map(e => [e.id, e]))
const TABS = [{ key: 'inbox', label: '받은 알림' }, { key: 'cond', label: '사건' }, { key: 'chan', label: '채널' }] as const
type Tab = typeof TABS[number]['key']
const FILTER_LABEL: Record<Filter, string> = { all: '전체', alarm: LV.alarm, alert: LV.alert, notice: LV.notice, brief: '시황', mine: '내 조건' }
const FILTER_OPTS = FILTERS.map(k => ({ key: k, label: FILTER_LABEL[k] }))
const PKG_OPTS = dict.packages.map(p => ({ key: p.id as Pkg, label: p.name }))
// 평일 몇 통 = 기획서 7장 꾸러미 표(400일 재생 docs/alerts_v2_replay.md 의 울림 하루 평균 + 브리핑 수)
const PKG_NOTE: Record<Pkg, string> = {
  quiet: '경보와 내 조건만 울립니다 · 아침 브리핑 · 하루 상한 3 · 평일 1~2통',
  normal: '경보와 알림이 울리고 안내는 마감 브리핑에 모입니다 · 아침 · 마감 · 주간 브리핑 · 하루 상한 6 · 평일 3~4통',
  many: '안내까지 울립니다 · 브리핑 6통 · 하루 상한 12 · 평일 8~10통',
}
const STRENGTH_OPTS = dict.strengths.filter(s => s.sigma != null).map(s => ({ key: s.id as Strength, label: s.name }))
const REPEAT_OPTS = [{ key: 'each', label: '매번' }, { key: 'once', label: '한 번' }] as const
const SAVE_FAIL = '이 기기에 저장하지 못했습니다. 시크릿 창이거나 저장 공간이 찼습니다.'
const WD = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', weekday: 'short' })
const dayHead = (day: string) => `${shortDate(day)}(${WD.format(Date.parse(`${day}T12:00:00+09:00`))})`
const hm = hhmm

type StateRec = { met?: boolean; date?: string; ts?: number; hist?: string[]; type?: string }
// 급변 감시(scripts/check_swings.py SWING_RULES)의 기호 → 지표 id·이름·기준 — 원장이 없을 때의 현행 이력용
const SWING: Record<string, [string, string, string]> = {
  '^KS11': ['kospi', '코스피', '±2%'], '^GSPC': ['sp500', 'S&P 500', '±2%'], 'KRW=X': ['usdkrw', '달러원', '±1%'],
}
const ymd = (s: string) => (/^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}` : s.slice(0, 10))
const noonKst = (day: string) => Date.parse(`${day}T12:00:00+09:00`)

/** 원장이 없을 때: 현행 발송 이력 · 렌즈 돌파 · 매매중단 → 같은 줄 모양(최근 7일). */
function legacyFeed(state: Record<string, unknown> | null, md: MarketData | null, mine: Map<string, AlertCond>, names: Map<string, string>, toOf: (id: string) => string, from: string): FeedRow[] {
  const out: FeedRow[] = []
  const pr = (state?._prefs ?? {}) as Record<string, unknown>
  for (const [id, raw] of [...Object.entries(state || {}), ...Object.entries(pr)]) {
    if (id.startsWith('_') || !raw || typeof raw !== 'object') continue
    const r = raw as StateRec
    const a = mine.get(id)
    const lastDay = r.ts ? kstDay(r.ts * 1000) : null
    for (const day of new Set([...(r.hist || []), ...(r.date ? [r.date] : [])].map(ymd))) {
      if (day < from) continue
      const cur = a?.event === 'U1' ? md?.quotes.get(a.target)?.price ?? md?.home?.strip.find(x => x.id === a.target)?.value ?? null : null
      const timed = day === lastDay
      out.push({
        key: `${id}-${day}`, level: 'alert', mine: true, day, timed, at: timed ? r.ts! * 1000 : noonKst(day),
        title: names.get(id) ?? (Object.hasOwn(pr, id) ? '다른 기기의 조건' : `현행 화면 조건 ${id}`),
        why: cur != null && a?.value ? `지금 ${fmtNumber(cur, cur % 1 ? 2 : 0)} · 기준까지 ${fmtPct((a.value / cur - 1) * 100)}` : undefined,
        to: a ? toOf(a.target) : undefined,
      })
    }
  }
  for (const [k, iso] of Object.entries((state?._swings || {}) as Record<string, string>)) {
    const [sym, dir] = k.split(':')
    const t = Date.parse(iso)
    if (Number.isNaN(t) || kstDay(t) < from) continue
    const [ind, name, rule] = SWING[sym] ?? [undefined, sym, '']
    const cur = ind ? md?.home?.strip.find(x => x.id === ind) : undefined
    out.push({
      key: k, level: 'alert', mine: false, day: kstDay(t), timed: true, at: t, title: `${name} 급${dir === 'up' ? '등' : '락'}`,
      why: rule ? `하루 ${rule} 이상` : undefined, next: cur?.value != null ? `지금 ${fmtNumber(cur.value, cur.decimals)}` : undefined, to: ind ? `/i/${ind}` : undefined,
    })
  }
  for (const t of md?.home?.lens?.breach || []) {
    const day = (t.asOf || md?.home?.lens?.asOf || '').slice(0, 10)
    if (!day || day < from) continue
    const u = t.unit === '%' || t.unit === '엔' ? t.unit : ''
    out.push({
      key: `lens-${t.id}`, level: 'alert', mine: false, day, timed: false, at: noonKst(day), title: `렌즈 ${t.stateLabel ?? '돌파'} · ${t.label}`,
      why: `${fmtNumber(t.value, 2)}${u}`, next: `기준 ${fmtNumber(t.level, 2)}${u}${t.distancePct != null ? ` · ${fmtPct(t.distancePct)}` : ''}`, to: `/lens?s=${encodeURIComponent(t.id)}`,
    })
  }
  for (const h of md?.halts || []) {
    const t = h.triggeredAt ? Date.parse(h.triggeredAt) : NaN
    if (Number.isNaN(t) || kstDay(t) < from) continue
    const kind = h.type === 'circuit' ? '서킷브레이커' : h.type === 'sidecar' ? '사이드카' : h.type
    out.push({ key: h.id, level: 'alarm', mine: false, day: kstDay(t), timed: true, at: t, title: `${h.market ?? ''} ${kind}${h.stage ? ` ${h.stage}단계` : ''}`.trim(), why: h.reason, to: '/market?a=kr&v=halts&m=all' })
  }
  return out.sort((a, b) => b.at - a.at)
}

export default function Alerts() {
  const [tab, setTab] = useViewParam<Tab>('v', 'inbox', TABS.map(o => o.key))
  // 상세의 「알림 조건 추가」는 ?v=cond&id=지표 로 온다. id 만 있어도 사건 탭을 연다 — 폼의 대상 채우기·주소 지우기는 NewCondition 이 한다.
  const [wantId] = useViewParam<string>('id', '')
  useEffect(() => { if (wantId && tab !== 'cond') setTab('cond') }, [wantId, tab, setTab])
  const [ledger, setLedger] = useState<LedgerRow[] | null | undefined>(undefined)   // undefined 불러오는 중 · null 아직 없음
  const [state, setState] = useState<Record<string, unknown> | null | undefined>(undefined)
  const [md, setMd] = useState<MarketData | null>(null)
  const [prefs, setPrefs] = useState<Prefs>(readPrefs)
  const [hk, setHk] = useState<Hk>(readHk)
  const [demoted, setDemoted] = useState(0)
  const sync = useSyncStatus()
  const [pushOn, setPushOn] = useState(false)
  const [msg, setMsg] = useState('')
  const [reg, setReg] = useState<RegRow[]>([])
  useEffect(() => {
    loadRootJson<unknown>('events/latest.json').then(r => setLedger(Array.isArray(r) ? (r as LedgerRow[]) : null), () => setLedger(null))
    loadRootJson<Record<string, unknown>>('alerts_state.json').then(setState, () => setState(null))
    loadMarketData().then(setMd, () => {})
    loadRegistry().then(setReg, () => {})
    pushSubscribed().then(setPushOn, () => {})
  }, [])
  // 동기화(sync.ts)·자동 정리(store.tidyAlerts)·다른 탭이 바꾸면 다시 읽는다 — 낡은 사본으로 저장해 다른 기기의 조건을 지우지 않게.
  useEffect(() => {
    const f = (e: StorageEvent) => { if (e.key === KEYS.prefs) { setPrefs(readPrefs()); setHk(readHk()) } }
    window.addEventListener('storage', f)
    return () => window.removeEventListener('storage', f)
  }, [])
  // 90일 미열람으로 꾸러미를 내렸으면 한 번 알리고 기록에서 지운다
  useEffect(() => {
    if (!hk.demoted) return
    setDemoted(hk.demoted)
    const { demoted: _d, ...rest } = hk
    writeHk(rest); setHk(rest)
  }, [hk])

  const regName = useMemo(() => new Map(reg.map(r => [r.id, r.short || r.label])), [reg])
  const labelOf = (id: string) => regName.get(id) ?? md?.quotes.get(id)?.name ?? id
  const toOf = (id: string) => (regName.has(id) ? `/i/${id}` : '/market?a=kr&m=all')
  const names = useMemo(() => new Map(prefs.alerts.map(a => [a.id, condName(a, regName.get(a.target) ?? md?.quotes.get(a.target)?.name ?? a.target, EV.get(a.event)?.name)])), [prefs.alerts, regName, md])
  const today = kstDay()
  const yesterday = kstDay(Date.now() - 86_400_000)
  const from = kstDay(Date.now() - 6 * 86_400_000)
  const feed = useMemo(() => (ledger ? fromLedger(ledger, names)
    : legacyFeed(state ?? null, md, new Map(prefs.alerts.map(a => [a.id, a])), names, toOf, from)), [ledger, state, md, prefs.alerts, names, from])   // toOf 는 regName 을 따르고 regName 이 바뀌면 names 도 바뀐다
  const todays = feed.filter(x => x.day === today)
  const save = (p: Prefs) => { setPrefs(p); setMsg(writePrefs(p) ? '' : SAVE_FAIL) }
  const setS = (k: Partial<Settings>) => save({ ...prefs, settings: { ...prefs.settings, ...k } })

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h1 className="m-0 inline-flex items-center gap-1.5 text-18 font-bold text-ink-1"><Bell size={18} aria-hidden />알림</h1>
        <span className="text-12 text-ink-2">
          오늘 울림 <span className="num">{todays.filter(x => x.level !== 'notice').length}</span> · 안내 <span className="num">{todays.filter(x => x.level === 'notice').length}</span>
          {' · '}꾸러미 {PKG_OPTS.find(o => o.key === prefs.settings.package)?.label} · {scopeText(sync.on, pushOn)}
        </span>
      </header>
      {demoted > 0 && <p role="status" className="m-0 text-13 text-ink-1">90일 동안 알림 화면을 열지 않아 꾸러미를 「{PKG_OPTS[0].label}」로 내렸습니다({mdHm(new Date(demoted))}). 사건 탭에서 바꿀 수 있고, 저절로 내리지 않게 하려면 설정 › 고급에서 끕니다.</p>}

      <SegBar label="알림 보기" options={TABS} value={tab} onChange={setTab} />
      {msg && <p role="alert" className="m-0 text-12 text-warn">{msg}</p>}

      {tab === 'inbox' && <Inbox feed={feed} ledger={ledger} state={state} today={today} yesterday={yesterday} />}
      {tab === 'cond' && (
        <EventsTab prefs={prefs} save={save} sync={sync} pushOn={pushOn} ledger={ledger ?? []} known={Array.isArray(ledger) || !!state} state={state} hk={hk} setHk={setHk}
          names={names} rows={reg} labelOf={labelOf} />
      )}
      {tab === 'chan' && <Channels prefs={prefs} setS={setS} />}
    </div>
  )
}

// ── 받은 알림 ─────────────────────────────────────────

function Inbox({ feed, ledger, state, today, yesterday }: { feed: FeedRow[]; ledger: unknown; state: unknown; today: string; yesterday: string }) {
  const [f, setF] = useState<Filter>('all')
  const g = groupDays(feed, today, yesterday)
  const any = feed.some(x => passes(x, f))
  return (
    <Panel title="지난 7일" source={ledger ? '사건 원장 · 생길 때마다 갱신' : '현행 발송 이력'}>
      {ledger === null && <p className="m-0 mb-2 text-12 text-ink-3">원장이 아직 없습니다. 현행 발송 이력으로 보여 줍니다.</p>}
      {ledger === null && state === null && <p className="m-0 mb-2 text-12 text-warn">발송 이력도 불러오지 못했습니다.</p>}
      <div className="mb-3"><SegBar label="알림 거르기" options={FILTER_OPTS} value={f} onChange={setF} /></div>
      {ledger === undefined ? <p className="m-0 text-13 text-ink-3">불러오는 중</p> : !any ? (
        <p className="m-0 text-13 text-ink-3">{f === 'all' ? '지난 7일 사이 받은 알림이 없습니다.' : `이 기간에 받은 ${FILTER_LABEL[f]} 알림이 없습니다.`}</p>
      ) : (
        <div className="flex flex-col gap-4">
          <DayGroup head={`오늘 ${dayHead(today)}`} items={g.today} f={f} />
          <DayGroup head={`어제 ${dayHead(yesterday)}`} items={g.yesterday} f={f} />
          <DayGroup head="그 전" items={g.older} f={f} showDay />
        </div>
      )}
      <p className="mt-3 mb-0 text-12 text-ink-3">내 조건 이름은 이 기기에 있는 조건에서 찾습니다. 다른 기기에서 만든 조건은 서버가 붙인 제목으로 보입니다.</p>
    </Panel>
  )
}

/** 하루 묶음: 머리(날짜 · 울림 N · 안내 M) + 줄. 안내는 「안내 N건 더」 뒤로 접는다(안내만 거를 때는 펼친 채). */
function DayGroup({ head, items, f, showDay }: { head: string; items: FeedRow[]; f: Filter; showDay?: boolean }) {
  const [open, setOpen] = useState(false)
  const shown = items.filter(x => passes(x, f))
  if (!shown.length) return null
  const fold = f !== 'notice'
  const main = fold ? shown.filter(x => x.level !== 'notice') : shown
  const notes = fold ? shown.filter(x => x.level === 'notice') : []
  const rang = items.filter(x => x.level !== 'notice').length
  return (
    <section>
      <h3 className="m-0 mb-1 text-12 font-bold text-ink-2">
        {head}{!showDay && <span className="font-normal text-ink-3"> · 울림 <span className="num">{rang}</span> · 안내 <span className="num">{items.length - rang}</span></span>}
      </h3>
      <FeedList items={open ? [...main, ...notes].sort((a, b) => b.at - a.at) : main} showDay={showDay} />
      {notes.length > 0 && (
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="mt-1 h-8 px-0 bg-transparent border-0 text-12 text-ink-2 hover:text-ink-1 cursor-pointer">
          {open ? '안내 접기' : `안내 ${notes.length}건 더`}
        </button>
      )}
    </section>
  )
}

/** 알림 줄: 시각 · 제목(두 줄까지, 390 폭에서 30자가 두 줄에 들게 등급은 아랫줄 앞에) · 등급 + 왜 · 다음 · 화면 링크. */
function FeedList({ items, showDay }: { items: FeedRow[]; showDay?: boolean }) {
  if (!items.length) return null
  return (
    <ul className="m-0 p-0 list-none">
      {items.map(x => {
        // 시각: 현행 발송 이력은 마지막 발동 시각만 남긴다 — 그 앞 날짜들은 날짜만 안다(「—」)
        const when = x.timed ? (showDay ? mdHm(new Date(x.at)) : hm(x.at)) : showDay ? shortDate(x.day) : '—'
        const sub = [x.why, x.next].filter(Boolean).join(' · ')
        const body = (
          <>
            <span className={`${showDay ? 'w-[4.5rem]' : 'w-10'} shrink-0 num text-12 text-ink-3`}>{when}</span>
            <span className="flex-1 min-w-0">
              <span className="block text-13 text-ink-1 line-clamp-2 [overflow-wrap:anywhere]">{x.title}</span>
              <span className="mt-0.5 flex items-start gap-2">
                <LevelPill level={x.level} />
                {sub && <span className="min-w-0 flex-1 text-12 text-ink-3 line-clamp-2 [overflow-wrap:anywhere]">{sub}</span>}
              </span>
            </span>
            {x.to && <ChevronRight size={14} aria-hidden className="shrink-0 mt-0.5 text-ink-3" />}
          </>
        )
        const row = 'flex items-start gap-3 py-2'
        return (
          <li key={x.key} className="border-b border-line last:border-b-0">
            {x.to ? <Link to={x.to} className={`${row} no-underline`} aria-label={`${x.title} 화면으로`}>{body}</Link> : <div className={row}>{body}</div>}
          </li>
        )
      })}
    </ul>
  )
}

// ── 사건 ───────────────────────────────────────────

type EventsProps = {
  prefs: Prefs; save: (p: Prefs) => void; sync: SyncStatus; pushOn: boolean; ledger: LedgerRow[]; known: boolean; state: Record<string, unknown> | null | undefined
  hk: Hk; setHk: (h: Hk) => void; names: Map<string, string>; rows: RegRow[]; labelOf: (id: string) => string
}

// known = 울림 기록(원장 · 현행 이력)을 하나라도 읽었나 — 못 읽었으면 「대기」라고 말하지 않는다
function EventsTab({ prefs, save, sync, pushOn, ledger, known, state, hk, setHk, names, rows, labelOf }: EventsProps) {
  const fired = (state?._prefs ?? {}) as Record<string, FiredRec>
  const mine = prefs.alerts.filter(a => a.target !== '*')
  const off = new Set(hk.off ?? [])
  const put = (alerts: AlertCond[]) => save({ ...prefs, alerts })
  const setAlert = (id: string, f: (a: AlertCond) => AlertCond) => put(prefs.alerts.map(a => (a.id === id ? f(a) : a)))
  /** 사건 전체 조정(대상 '*') — 세기 · 등급이 사전 기본과 같으면 줄을 지운다. */
  const adjust = (e: DictEvent, patch: Partial<AlertCond>) => {
    const cur = adjustOf(prefs.alerts, e.id)
    const next: AlertCond = { id: cur?.id ?? condId(), event: e.id, target: '*', repeat: 'each', enabled: true, ...cur, ...patch }
    if (next.strength === 'big') delete next.strength
    if (next.level === e.level) delete next.level
    const keep = next.strength || next.level || next.enabled === false
    put([...prefs.alerts.filter(a => a !== cur), ...(keep ? [next] : [])])
  }
  const toggle = (a: AlertCond, on: boolean) => {
    if (on && off.has(a.id)) { const h = { ...hk, off: [...off].filter(x => x !== a.id) }; writeHk(h); setHk(h) }
    setAlert(a.id, x => ({ ...x, enabled: on }))
  }
  const pkg = prefs.settings.package
  // 꾸러미는 하루 상한 · 브리핑을 같이 바꾸므로(명세 S10) 고르면 바뀔 값을 한 줄로 보이고 「바꾸기」를 눌러야 저장한다
  const [want, setWant] = useState<Pkg | null>(null)
  const briefN = (b: Settings['briefings']) => Object.values(b).filter(Boolean).length
  const next = want ? PACKAGE_PRESET[want] : null
  return (
    <>
      <Panel title="꾸러미">
        <SegBar label="꾸러미" options={PKG_OPTS} value={want ?? pkg} onChange={k => setWant(k === pkg ? null : k)} />
        <p className="mt-2 mb-0 text-12 text-ink-2">{PKG_NOTE[want ?? pkg]}</p>
        {want && next ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-13 text-ink-1">하루 상한 <span className="num">{prefs.settings.dailyCap}→{next.cap}</span> · 브리핑 <span className="num">{briefN(prefs.settings.briefings)}→{briefN(next.briefings)}</span> 로 바뀝니다</span>
            <button type="button" className={BTN} onClick={() => { save({ ...prefs, settings: setPackage(prefs.settings, want) }); setWant(null) }}>바꾸기</button>
            <button type="button" className={BTN2} onClick={() => setWant(null)}>그만두기</button>
          </div>
        ) : <p className="mt-1 mb-0 text-12 text-ink-3">꾸러미를 바꾸면 하루 상한과 브리핑이 따라 바뀝니다. 아래 사건마다 고친 세기 · 등급은 그대로 둡니다.</p>}
      </Panel>

      <Panel title="사건 갈래" source="갈래를 누르면 사건마다 세기 · 등급">
        <ul className="m-0 p-0 list-none">
          {dict.families.map(f => <FamilyRow key={f.id} fam={f} prefs={prefs} save={save} adjust={adjust} />)}
        </ul>
      </Panel>

      <Panel title="내 조건" source={`${mine.length}개 · ${scopeText(sync.on, pushOn)}`}>
        {mine.length ? (
          <ul className="m-0 p-0 list-none">
            {mine.map(a => {
              const st = condStatus(a, ledger, fired[a.id], sync.on, off.has(a.id))
              const name = names.get(a.id) ?? a.id
              const show = known || st.kind === 'off' || st.kind === 'local'
              return (
                <li key={a.id} className="flex items-center gap-x-3 gap-y-1 py-2 border-b border-line last:border-b-0">
                  <Switch on={a.enabled} label={<span className="sr-only">{name} 켜고 끄기</span>} onChange={on => toggle(a, on)} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-13 text-ink-1 line-clamp-2 [overflow-wrap:anywhere]">{name}</span>
                    <span className="block text-12 text-ink-3 [overflow-wrap:anywhere]">
                      {EV.get(a.event)?.name ?? a.event} · {a.repeat === 'once' ? '한 번' : '매번'}{a.ring === false ? ' · 울림 꺼짐' : ''}
                      {show && <> · <span className={`num ${st.kind === 'rang' || st.kind === 'stopped' ? 'text-ink-1' : ''}`}>{st.text}</span></>}
                    </span>
                    {/* 다시 켠 것은 /prefs 로 올라가야 서버가 본다 — 동기화가 꺼져 있으면 눌러도 소용없다 */}
                    {st.kind === 'stopped' && (sync.on ? (
                      <button type="button" className={`${BTN2} mt-1`} aria-label={`${name} 다시 켜기`} onClick={() => setAlert(a.id, x => rearm(x, ledger, fired[a.id]))}>다시 켜기</button>
                    ) : <span className="block text-12 text-ink-3">설정 › 기기 연결에서 연결하면 다시 켤 수 있습니다</span>)}
                  </span>
                  <button type="button" onClick={() => put(prefs.alerts.filter(x => x.id !== a.id))} aria-label={`${name} 지우기`} title="지우기"
                    className="size-8 shrink-0 inline-flex items-center justify-center rounded-btn border-0 bg-transparent text-ink-3 hover:text-ink-1 cursor-pointer">
                    <Trash2 size={14} aria-hidden />
                  </button>
                </li>
              )
            })}
          </ul>
        ) : <p className="m-0 text-13 text-ink-3">아직 만든 조건이 없습니다. 지표 · 종목 상세의 벨이나 아래 「새 조건」에서 만듭니다.</p>}
        <p className="mt-2 mb-0 text-12 text-ink-3">연결돼 있어야(설정 › 기기 연결) 서버가 이 조건을 보고 보냅니다. 「한 번」 조건은 울리면 멈추고, 「다시 켜기」를 누르면 새 값이 들어온 뒤 다시 울립니다. 180일 동안 울리지 않은 「한 번」 조건은 저절로 꺼집니다(지우지는 않음).</p>
        <LegacyImport alerts={prefs.alerts} sync={sync} onAdd={add => put([...prefs.alerts, ...add])} />
      </Panel>

      <NewCondition rows={rows} labelOf={labelOf} sync={sync} full={prefs.alerts.length >= ALERT_CAP} onAdd={a => put([...prefs.alerts, a])} />
      <p className="m-0 text-12 text-ink-3">
        현행 화면에서 만든 조건은 <a href={new URL('legacy.html?p=portfolio', ROOT).href} className="text-ink-2">현행 화면</a>에서 보고 고칩니다.
      </p>
    </>
  )
}

/** 현행 화면(공개 저장소 alerts_config.json)의 조건을 읽는다. 운영 사이트에는 그 파일이 올라가지 않으므로 동기화 키가 있으면 Worker /portfolio 로 읽고,
 *  키가 없으면 같은 출처의 파일을 시도한다(로컬 개발 서버에서만 읽힌다). */
async function readLegacy(): Promise<{ rows: unknown[] } | { error: string }> {
  const h = getKeyHash()
  let why = ''
  if (h) {
    const g = await portfolioGet(h)
    if (g.ok) return { rows: g.alerts ?? [] }
    why = g.status === 401 ? '동기화 키가 맞지 않습니다.' : '서버에 닿지 못했습니다.'
  }
  try { return { rows: (await loadRootJson<{ alerts?: unknown[] }>('alerts_config.json')).alerts ?? [] } } catch { /* 운영 사이트에는 없다 */ }
  return { error: why || '현행 조건을 읽으려면 설정 › 기기 연결에서 연결해야 합니다.' }
}

/** 「현행 조건 가져오기」: 읽기 → 미리보기(가져올 N · 건너뛸 M) → 확인하면 이 기기 조건에 더한다. 현행 화면의 조건은 그대로 둔다. */
function LegacyImport({ alerts, sync, onAdd }: { alerts: AlertCond[]; sync: SyncStatus; onAdd: (a: AlertCond[]) => void }) {
  const [rows, setRows] = useState<unknown[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [done, setDone] = useState<{ n: number; at: number } | null>(null)
  const pre: Imported | null = useMemo(() => (rows ? convertLegacy(rows, alerts, id => EV.get(id)?.name) : null), [rows, alerts])
  const read = async () => {
    setBusy(true); setErr(''); setDone(null)
    const r = await readLegacy()
    setBusy(false)
    if ('error' in r) setErr(r.error); else setRows(r.rows)
  }
  const confirm = () => {
    if (!pre) return
    onAdd(pre.add)
    setDone({ n: pre.add.length, at: Date.now() }); setRows(null)
  }
  const skipped = pre ? pre.total - pre.add.length : 0
  return (
    <div className="mt-3 pt-3 border-t border-line">
      {!pre && <button type="button" className={BTN2} disabled={busy} onClick={() => void read()}>{busy ? '읽는 중' : '현행 조건 가져오기'}</button>}
      {pre && (
        <div className="flex flex-col gap-2" role="group" aria-label="현행 조건 가져오기 미리보기">
          <p className="m-0 text-13 text-ink-1">가져올 조건 <span className="num">{pre.add.length}</span>건 · 건너뜀 <span className="num">{skipped}</span>건 <span className="text-ink-3">(읽은 <span className="num">{pre.total}</span>건)</span></p>
          <ul className="m-0 pl-4 text-12 text-ink-2">
            {pre.dup > 0 && <li>이미 있거나 겹치는 조건 {pre.dup}건은 건너뜀(52주 신고가 · 신저가는 한 사건이라 대상당 한 건)</li>}
            {pre.cross > 0 && <li>골든/데드크로스 {pre.cross}건은 사전에 없어 가져오지 않음</li>}
            {pre.other > 0 && <li>그 밖의 종류 {pre.other}건은 가져오지 않음</li>}
            {pre.over > 0 && <li>조건은 100건까지라 {pre.over}건을 못 담음</li>}
            {pre.add.some(a => a.event === 'U2') && <li>등락률 조건은 오름 · 내림 모두 봅니다(현행의 내림 전용은 ± 로 바뀜)</li>}
            <li>현행 화면의 조건은 그대로 남습니다</li>
          </ul>
          <div className="flex flex-wrap gap-2">
            {pre.add.length > 0 && <button type="button" className={BTN} onClick={confirm}>{pre.add.length}건 가져오기</button>}
            <button type="button" className={BTN2} onClick={() => setRows(null)}>{pre.add.length > 0 ? '취소' : '닫기'}</button>
          </div>
        </div>
      )}
      {err && <p role="alert" className="m-0 mt-2 text-12 text-warn">{err}</p>}
      {done && <p role="status" className="m-0 mt-2 text-12 text-ink-2">{savedNote(sync, done.at, `${done.n}건 가져왔습니다`)}</p>}
    </div>
  )
}

/** 갈래 한 줄: 이름 · 켜짐/관심 셈 · 켜고 끄기. 누르면 사건 낱개(이름 · 등급 · 기본 켜짐/관심 · 세기 · 등급 조정). */
function FamilyRow({ fam, prefs, save, adjust }: { fam: { id: string; name: string }; prefs: Prefs; save: (p: Prefs) => void; adjust: (e: DictEvent, p: Partial<AlertCond>) => void }) {
  const [open, setOpen] = useState(false)
  const on = prefs.settings.families[fam.id as keyof Settings['families']] !== false
  const c = familyCount(dict, fam.id, prefs.alerts)
  const evs = listEvents(dict, fam.id)
  return (
    <li className="border-b border-line last:border-b-0">
      <div className="flex items-center gap-2 py-2">
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
          className="min-w-0 flex-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 p-0 bg-transparent border-0 text-left cursor-pointer">
          <ChevronRight size={14} aria-hidden className={`shrink-0 text-ink-3 ${open ? 'rotate-90' : ''}`} />
          <span className="text-13 font-bold text-ink-1">{fam.name}</span>
          <span className="text-12 text-ink-3">켜짐 <span className="num">{c.on}</span> · 관심 <span className="num">{c.watch}</span></span>
        </button>
        <Switch on={on} label={<span className="sr-only">{fam.name} 켜고 끄기</span>}
          onChange={v => save({ ...prefs, settings: { ...prefs.settings, families: { ...prefs.settings.families, [fam.id]: v } } })} />
      </div>
      {open && (
        <ul className={`m-0 mb-2 p-0 pl-5 list-none ${on ? '' : 'opacity-60'}`} aria-label={`${fam.name} 사건`}>
          {evs.map(e => {
            const adj = adjustOf(prefs.alerts, e.id)
            const level = adj?.level ?? e.level
            return (
              <li key={e.id} className="flex flex-col gap-2 py-2 border-t border-line">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="min-w-0 flex-1 text-13 text-ink-1 [overflow-wrap:anywhere]">{e.name}</span>
                  <LevelPill level={level} />
                  <span className="text-12 text-ink-3">{e.defaultOn.length ? '기본 켜짐' : '관심 대상만'}</span>
                </div>
                {e.strength && <SegBar label={`${e.name} 세기`} options={STRENGTH_OPTS} value={adj?.strength ?? 'big'} onChange={s => adjust(e, { strength: s })} />}
                {e.level !== 'record' && (
                  <SegBar label={`${e.name} 등급`} options={levelChoices(e.level).map(l => ({ key: l, label: LV[l] }))} value={level} onChange={l => adjust(e, { level: l })} />
                )}
              </li>
            )
          })}
        </ul>
      )}
    </li>
  )
}

/** 새 조건: 대상 → 그 대상이 가진 사건(사전) → 세기 3단(「지난 1년 N회」) 또는 값 → 등급 · 반복 · 울림 · 이름. 저장 모양 = 계약서 AlertCond. */
function NewCondition({ rows, labelOf, sync, full, onAdd }: { rows: RegRow[]; labelOf: (id: string) => string; sync: SyncStatus; full: boolean; onAdd: (a: AlertCond) => void }) {
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState<{ id: string; label: string } | null>(null)
  // 상세가 주소(?id=)로 넘긴 지표: 한 번 읽고 주소에서 지운다. 사전이 늦게 와도 이름이 따라오도록 id 로 들고 있다가, 대상 칸을 고르거나 지우면 놓는다.
  const [urlId, setUrlId] = useViewParam<string>('id', '')
  const [pre, setPre] = useState(urlId)
  useEffect(() => { if (urlId) setUrlId('') }, [urlId, setUrlId])
  const target = picked ?? prefillTarget(pre, rows)
  const setTarget = (t: { id: string; label: string } | null) => { setPicked(t); setPre('') }
  const [event, setEvent] = useState('U1')
  const [dir, setDir] = useState<'up' | 'down'>('up')
  const [value, setValue] = useState('')
  const [strength, setStrength] = useState<Strength>('big')
  const [level, setLevel] = useState<Level | ''>('')
  const [repeat, setRepeat] = useState<'each' | 'once'>('each')
  const [ring, setRing] = useState(true)
  const [name, setName] = useState('')
  const [err, setErr] = useState('')
  const [savedAt, setSavedAt] = useState(0)
  const [counts, setCounts] = useState<Record<string, number> | null>(null)

  const s = q.trim().toLowerCase()
  const hits = s ? rows.filter(r => [r.id, r.label, r.short, r.shortM].some(x => x?.toLowerCase().includes(s))).slice(0, 6) : []
  const raw = q.trim()
  const t = target ?? (TARGET_RE.test(raw) ? { id: raw, label: labelOf(raw) } : null)
  const stock = !!t && watchKind(t.id) === 'stock'
  const evs = t ? eventsFor(dict, t.id, stock) : dict.events.filter(e => e.userValue)
  const ev = evs.find(e => e.id === event) ?? evs[0]
  const base = ev?.level ?? 'alert'
  useEffect(() => {
    setCounts(null)
    if (!t || !ev?.strength) return
    let live = true
    loadDaily(t.id).then(sr => { if (live && sr) setCounts(yearCounts(sr, dict.strengths)) }, () => {})
    return () => { live = false }
  }, [t?.id, ev?.id, ev?.strength])   // t 는 렌더마다 새 객체라 id 로만 본다

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (full) { setErr(CAP_MSG); return }
    if (!t) { setErr('대상을 고르세요. 목록에 없으면 종목 코드(예: 005930)를 그대로 넣습니다.'); return }
    if (!ev) return
    const v = Number(value)
    const a: AlertCond = { id: condId(), event: ev.id, target: t.id, repeat, ring, enabled: true }
    if (ev.id === 'U1') { if (value.trim() === '' || !Number.isFinite(v)) { setErr('값을 넣으세요.'); return } a.value = v; a.dir = dir }
    else if (ev.id === 'U2') { if (!(Math.abs(v) > 0)) { setErr('하루 등락률(%)을 넣으세요. 오름 · 내림 모두 봅니다.'); return } a.value = Math.abs(v) }
    if (ev.strength && strength !== 'big') a.strength = strength
    if (level && level !== base) a.level = level
    if (name.trim()) a.name = name.trim().slice(0, 40)
    onAdd(a)
    setErr(''); setQ(''); setTarget(null); setValue(''); setName(''); setSavedAt(Date.now())
  }
  const note = savedNote(sync, savedAt)

  return (
    <Panel title="새 조건">
      <form onSubmit={submit} className="flex flex-col gap-3" aria-label="새 알림 조건">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <Field label="대상">
            <input className={INPUT} value={target ? target.label : q} placeholder="지표 이름 · 종목 코드"
              onChange={e => { setTarget(null); setQ(e.target.value) }} autoComplete="off" />
          </Field>
          <Field label="사건">
            <select className={INPUT} value={ev?.id ?? ''} onChange={e => { setEvent(e.target.value); setLevel('') }}>
              {evs.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </Field>
        </div>
        {!target && hits.length > 0 && (
          <ul className="m-0 p-0 list-none flex flex-wrap gap-1" aria-label="찾은 지표">
            {hits.map(r => (
              <li key={r.id} className="min-w-0"><button type="button" className={`${BTN2} max-w-full truncate`} onClick={() => setTarget({ id: r.id, label: r.short || r.label })}>{r.short || r.label}</button></li>
            ))}
          </ul>
        )}
        {ev?.id === 'U1' && (
          <div className="grid grid-cols-2 gap-2">
            <Field label="방향"><select className={INPUT} value={dir} onChange={e => setDir(e.target.value as 'up' | 'down')}><option value="up">위로 넘으면</option><option value="down">아래로 내려가면</option></select></Field>
            <Field label="값"><input className={INPUT} value={value} onChange={e => setValue(e.target.value)} inputMode="decimal" /></Field>
          </div>
        )}
        {ev?.id === 'U2' && <Field label="하루 등락률(%) · 오름 · 내림 모두" className="sm:max-w-60"><input className={INPUT} value={value} onChange={e => setValue(e.target.value)} inputMode="decimal" placeholder="3" /></Field>}
        {ev?.strength && (
          <Row label="세기">
            <SegBar label="세기" value={strength} onChange={setStrength}
              options={STRENGTH_OPTS.map(o => ({ ...o, label: counts?.[o.key] != null ? `${o.label} · 1년 ${counts[o.key]}회` : o.label }))} />
            {counts && <p className="m-0 mt-1 text-12 text-ink-3">지난 1년 하루 등락이 그 세기를 넘은 날 수입니다.</p>}
          </Row>
        )}
        <Row label="등급"><SegBar label="등급" options={levelChoices(base).map(l => ({ key: l, label: LV[l] }))} value={(level || base) as Level} onChange={setLevel} /></Row>
        <Row label="반복">
          <SegBar label="반복" options={REPEAT_OPTS} value={repeat} onChange={setRepeat} />
          <p className="m-0 mt-1 text-12 text-ink-3">{repeatNote(ev?.id ?? '', repeat)}{repeat === 'once' ? ' 「다시 켜기」로 다시 켭니다.' : ''}</p>
        </Row>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 items-end">
          <Field label="이름(비우면 「대상 조건」)"><input className={INPUT} value={name} maxLength={40} onChange={e => setName(e.target.value)} autoComplete="off" /></Field>
          <Switch on={ring} onChange={setRing} label="울림(끄면 받은 알림에만 남음)" />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="submit" className={BTN}>조건 저장</button>
          <span role="alert" className="text-12 text-warn">{err}</span>
          {!err && note && <span role="status" className="text-12 text-ink-2">{note}</span>}
        </div>
      </form>
    </Panel>
  )
}

// ── 채널 ───────────────────────────────────────────

const BRIEFS: { key: keyof Settings['briefings']; label: string }[] = [
  { key: 'morning', label: '아침 07:30' }, { key: 'close', label: '마감 16:30 · 안내 묶음 포함' }, { key: 'noon', label: '점심 12:00' },
  { key: 'evening', label: '저녁 확정 18:30' }, { key: 'us', label: '미국 개장 22:40' }, { key: 'weekly', label: '주간 토 09:00' },
]
const RING_OPTS = [{ key: 'kakao', label: '카톡' }, { key: 'push', label: '폰' }, { key: 'both', label: '둘 다' }] as const
const CAP_OPTS = [{ key: '3', label: '3' }, { key: '6', label: '6' }, { key: '12', label: '12' }] as const

/** 채널: 울림 채널 · 하루 상한 · 조용한 시간 · 브리핑 · 디스코드. 폰 알림 · 동기화 키 · 받는 기기는 설정 「기기 연결」, 카톡은 설정 「고급」. */
function Channels({ prefs, setS }: { prefs: Prefs; setS: (k: Partial<Settings>) => void }) {
  const s = prefs.settings
  const quiet = s.quiet
  const setQuiet = (q: Settings['quiet']) => setS({ quiet: q })
  return (
    <>
      <p className="m-0 text-12 text-ink-2">폰 알림 · 동기화 키 · 받는 기기는 <Link to="/settings" className="text-ink-1">설정 › 기기 연결</Link>에서</p>
      <div className="grid grid-cols-1 pc:grid-cols-2 gap-4 items-start">
        <Panel title="울림 채널 · 하루 상한">
          <SegBar label="울림 채널" options={RING_OPTS} value={s.ringChannel} onChange={v => setS({ ringChannel: v })} />
          <p className="mt-1 mb-3 text-12 text-ink-3">경보 · 알림 · 내 조건이 이 채널로 울립니다. 안내는 울리지 않고 받은 알림에 쌓입니다.</p>
          <div className="flex flex-wrap items-end gap-2">
            <SegBar label="하루 울림 상한" options={CAP_OPTS} value={String(s.dailyCap) as '3'} onChange={v => setS({ dailyCap: Number(v) })} />
            <Field label="직접" className="w-20"><input type="number" min={1} max={50} className={INPUT} value={s.dailyCap}
              onChange={e => { const n = Math.round(Number(e.target.value)); if (n >= 1 && n <= 50) setS({ dailyCap: n }) }} /></Field>
          </div>
          <p className="mt-1 mb-0 text-12 text-ink-3">하루에 이만큼 울린 뒤의 알림은 「알림 N건 더」 한 통으로 묶습니다. 경보는 상한과 상관없이 울립니다.</p>
        </Panel>
        <Panel title="조용한 시간">
          <Switch on={!!quiet} onChange={on => setQuiet(on ? { from: '23:00', to: '07:00' } : null)} label="이 시간엔 울리지 않기" />
          {quiet && (
            <div className="mt-3 grid grid-cols-2 gap-2">
              <Field label="부터"><input type="time" className={INPUT} value={quiet.from} onChange={e => e.target.value && setQuiet({ ...quiet, from: e.target.value })} /></Field>
              <Field label="까지"><input type="time" className={INPUT} value={quiet.to} onChange={e => e.target.value && setQuiet({ ...quiet, to: e.target.value })} /></Field>
            </div>
          )}
          <div className="mt-3"><Switch on={s.quietAlarm} onChange={v => setS({ quietAlarm: v })} label="경보는 조용한 시간에도 울리기" /></div>
          <p className="mt-2 mb-0 text-12 text-ink-3">한국 시각 기준입니다. 이 시간에 생긴 알림은 아침 07:30 브리핑에 모아 보냅니다. 경보 = 서킷브레이커 · 정책금리 변경 · 렌즈 새 돌파 같은 것.</p>
        </Panel>
        <Panel title="브리핑">
          <ul className="m-0 p-0 list-none flex flex-col gap-2">
            {BRIEFS.map(b => (
              <li key={b.key}><Switch on={s.briefings[b.key]} onChange={v => setS({ briefings: { ...s.briefings, [b.key]: v } })} label={b.label} /></li>
            ))}
          </ul>
          <p className="mt-2 mb-0 text-12 text-ink-3">꾸러미를 바꾸면 이 묶음도 그 꾸러미 값으로 바뀝니다.</p>
        </Panel>
        <Panel title="디스코드">
          <p className="m-0 text-13 text-ink-2">모든 알림이 디스코드에 보관됩니다. 이 화면에서 바꾸는 것은 없습니다.</p>
          <p className="mt-2 mb-0 text-12 text-ink-3">경보는 #급변-속보에 멘션과 함께, 알림 · 안내는 #종목-알림에, 브리핑은 #시황-다이제스트에 쌓입니다.</p>
        </Panel>
      </div>
    </>
  )
}
