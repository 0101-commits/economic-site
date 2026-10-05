// 알림 — 기획안 v4 7장. 첫 블록(오늘 받은 알림) → 탭(받은 알림·조건·채널).
// 받은 알림의 원천 셋: 공개 발송 이력 alerts_state.json(조건 id·날짜·시각뿐) · 홈 묶음 렌즈 돌파 · 국내 시장 매매중단.
// 금액·보유 종목명은 싣지 않는다. 이 화면은 PinGate 밖이라 portfolioV1 을 읽지 않는다 — 발동 이력의 조건 이름은
// 이 기기에서 만든 조건(econPrefsV1.alerts)과 지표 사전에서만 찾는다. 새 화면 조건(_prefs)인데 이 기기에 없으면 「다른 기기의 조건」.
// 조건 행의 상태(대기·발동됨·꺼짐)와 다시 켜기 규칙은 lib/personal/alertStatus.ts — 발동 판정은 서버 기록만 읽는다.
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Bell, ChevronRight, Trash2 } from 'lucide-react'
import { Card, Pill, SegBar } from '../components/ui'
import { Panel } from '../components/panels'
import { BTN, BTN2, Field, INPUT, Switch } from '../components/personal/bits'
import { loadRegistry, ROOT, type RegRow } from '../lib/bundle'
import { fmtNumber, fmtPct, mdHm, shortDate } from '../lib/format'
import { useViewParam } from '../lib/useViewParam'
import { kstDay } from '../lib/personal/calc'
import { loadMarketData, loadRootJson, type MarketData } from '../lib/personal/data'
import { KEYS, readPrefs, writePrefs, type AlertCond, type AlertType, type Prefs } from '../lib/personal/store'
import { condId, condStatus, prefillTarget, rearm, TARGET_RE, type FiredRec } from '../lib/personal/alertStatus'
import { getKeyHash, useSyncStatus } from '../lib/personal/sync'
import { pushSubscribed, pushSupported, subscribePush, unsubscribePush } from '../lib/push'

const TABS = [{ key: 'inbox', label: '받은 알림' }, { key: 'cond', label: '조건' }, { key: 'chan', label: '채널' }] as const
type Tab = typeof TABS[number]['key']
const CATS = [{ key: 'all', label: '전체' }, { key: 'swing', label: '급변' }, { key: 'mine', label: '내 조건' }, { key: 'lens', label: '렌즈' }, { key: 'market', label: '시황' }] as const
type Cat = Exclude<typeof CATS[number]['key'], 'all'>
const CAT_LABEL: Record<Cat, string> = { swing: '급변', mine: '내 조건', lens: '렌즈', market: '시황' }
const CAT_TONE: Record<Cat, 'x' | 'n' | 'o' | 'g'> = { swing: 'x', mine: 'o', lens: 'n', market: 'x' }
const SAVE_FAIL = '이 기기에 저장하지 못했습니다. 시크릿 창이거나 저장 공간이 찼습니다.'

type Item = { key: string; cat: Cat; what: string; value?: string; dist?: string; at: number; timed: boolean; day: string; to?: string }
type StateRec = { met?: boolean; date?: string; ts?: number; hist?: string[]; type?: string }

// 급변 감시(scripts/check_swings.py SWING_RULES)의 기호 → 지표 id·이름·기준
const SWING: Record<string, [string, string, string]> = {
  '^KS11': ['kospi', '코스피', '±2%'], '^GSPC': ['sp500', 'S&P 500', '±2%'], 'KRW=X': ['usdkrw', '달러원', '±1%'],
}
const ymd = (s: string) => (/^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}` : s.slice(0, 10))
const noonKst = (day: string) => Date.parse(`${day}T12:00:00+09:00`)

/** 받은 알림 목록(최근 7일, 새것이 위). */
function buildFeed(state: Record<string, unknown> | null, md: MarketData | null, mine: Map<string, AlertCond>, regName: Map<string, string>, from: string): Item[] {
  const out: Item[] = []
  // 최상위 기록(현행 조건) + state._prefs(새 화면 조건) — 두 곳 모두 같은 모양. 이름은 이 기기 econPrefsV1 에서 id 로 찾는다.
  const pr = (state?._prefs ?? {}) as Record<string, unknown>
  for (const [id, raw] of [...Object.entries(state || {}), ...Object.entries(pr)]) {
    if (id.startsWith('_') || !raw || typeof raw !== 'object') continue
    const fromPrefs = Object.hasOwn(pr, id)   // 새 화면 조건 id('p…')와 현행 조건 id 는 겹치지 않는다
    const r = raw as StateRec
    const lastDay = r.ts ? kstDay(r.ts * 1000) : null
    for (const day of new Set([...(r.hist || []), ...(r.date ? [r.date] : [])].map(ymd))) {
      if (day < from) continue
      const a = mine.get(id)
      const kind = TYPES.find(t => t.key === r.type)?.label
      const cur = a ? md?.quotes.get(a.target)?.price ?? md?.home?.strip.find(x => x.id === a.target)?.value ?? null : null
      const lvl = a?.type === 'price' ? Number(a.cond.value) : NaN
      const timed = day === lastDay
      out.push({
        key: `${id}-${day}`, cat: 'mine', day, timed, at: timed ? r.ts! * 1000 : noonKst(day),
        what: a ? `${regName.get(a.target) ?? a.target} ${TYPES.find(t => t.key === a.type)?.label ?? a.type}`
          : fromPrefs ? `다른 기기의 조건${kind ? ` · ${kind}` : ''}` : `조건 ${id}`,
        value: a ? condText(a) : undefined,
        dist: cur != null && lvl > 0 ? `지금 ${fmtNumber(cur, cur % 1 ? 2 : 0)} · 기준까지 ${fmtPct((lvl / cur - 1) * 100)}` : undefined,
        to: a ? (regName.has(a.target) ? `/i/${a.target}` : '/market?a=kr&m=all') : undefined,
      })
    }
  }
  const swings = (state?._swings || {}) as Record<string, string>
  for (const [k, iso] of Object.entries(swings)) {
    const [sym, dir] = k.split(':')
    const t = Date.parse(iso)
    if (Number.isNaN(t) || kstDay(t) < from) continue
    const [ind, name, rule] = SWING[sym] ?? [undefined, sym, '']
    const cur = ind ? md?.home?.strip.find(x => x.id === ind) : undefined
    out.push({
      key: k, cat: 'swing', day: kstDay(t), timed: true, at: t,
      what: `${name} 급${dir === 'up' ? '등' : '락'}`, value: rule ? `하루 ${rule} 이상` : undefined,
      dist: cur?.value != null ? `지금 ${fmtNumber(cur.value, cur.decimals)}` : undefined, to: ind ? `/i/${ind}` : undefined,
    })
  }
  for (const t of md?.home?.lens?.breach || []) {
    const day = (t.asOf || md?.home?.lens?.asOf || '').slice(0, 10)
    if (!day || day < from) continue
    const u = t.unit === '%' || t.unit === '엔' ? t.unit : ''
    out.push({
      key: `lens-${t.id}`, cat: 'lens', day, timed: false, at: noonKst(day), what: `렌즈 ${t.stateLabel ?? '돌파'} · ${t.label}`,
      value: `${fmtNumber(t.value, 2)}${u}`, dist: `기준 ${fmtNumber(t.level, 2)}${u}${t.distancePct != null ? ` · ${fmtPct(t.distancePct)}` : ''}`, to: `/lens?s=${encodeURIComponent(t.id)}`,
    })
  }
  for (const h of md?.halts || []) {
    const t = h.triggeredAt ? Date.parse(h.triggeredAt) : NaN
    if (Number.isNaN(t) || kstDay(t) < from) continue
    const kind = h.type === 'circuit' ? '서킷브레이커' : h.type === 'sidecar' ? '사이드카' : h.type
    out.push({ key: h.id, cat: 'market', day: kstDay(t), timed: true, at: t, what: `${h.market ?? ''} ${kind}${h.stage ? ` ${h.stage}단계` : ''}`.trim(), value: h.reason, to: '/market?a=kr&v=halts&m=all' })
  }
  return out.sort((a, b) => b.at - a.at)
}

export default function Alerts() {
  const [tab, setTab] = useViewParam<Tab>('v', 'inbox', TABS.map(o => o.key))
  // 상세의 「알림 조건 추가」는 ?v=cond&id=지표 로 온다. id 만 있어도 조건 탭을 연다 — 폼의 대상 채우기·주소 지우기는 NewCondition 이 한다.
  const [wantId] = useViewParam<string>('id', '')
  useEffect(() => { if (wantId && tab !== 'cond') setTab('cond') }, [wantId, tab, setTab])
  const [cat, setCat] = useState<typeof CATS[number]['key']>('all')
  const [state, setState] = useState<Record<string, unknown> | null | undefined>(undefined)
  const [md, setMd] = useState<MarketData | null>(null)
  const [prefs, setPrefs] = useState<Prefs>(readPrefs)
  const sync = useSyncStatus()
  const [msg, setMsg] = useState('')
  const [reg, setReg] = useState<RegRow[]>([])
  const regName = useMemo(() => new Map(reg.map(r => [r.id, r.short || r.label])), [reg])
  const mine = useMemo(() => new Map(prefs.alerts.map(a => [a.id, a])), [prefs.alerts])
  useEffect(() => {
    loadRootJson<Record<string, unknown>>('alerts_state.json').then(setState, () => setState(null))
    loadMarketData().then(setMd, () => {})
    loadRegistry().then(setReg, () => {})
  }, [])
  // 동기화(sync.ts)가 서버 내용으로 덮거나 다른 탭이 바꾸면 다시 읽는다 — 낡은 사본으로 저장해 다른 기기의 조건을 지우지 않게.
  useEffect(() => {
    const f = (e: StorageEvent) => { if (e.key === KEYS.prefs) setPrefs(readPrefs()) }
    window.addEventListener('storage', f)
    return () => window.removeEventListener('storage', f)
  }, [])

  const today = kstDay()
  const yesterday = kstDay(Date.now() - 86_400_000)
  const from = kstDay(Date.now() - 6 * 86_400_000)
  const feed = useMemo(() => buildFeed(state ?? null, md, mine, regName, from), [state, md, mine, regName, from])
  const fired = (state?._prefs ?? {}) as Record<string, FiredRec>
  const todays = feed.filter(x => x.day === today)
  const rest = feed.filter(x => x.day !== today && (cat === 'all' || x.cat === cat))
  const save = (p: Prefs) => { setPrefs(p); setMsg(writePrefs(p) ? '' : SAVE_FAIL) }

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h1 className="m-0 inline-flex items-center gap-1.5 text-18 font-bold text-ink-1"><Bell size={18} aria-hidden />알림</h1>
        {state === undefined && <span className="text-12 text-ink-3">불러오는 중</span>}
        {state === null && <span className="text-12 text-warn">발송 이력을 불러오지 못했습니다</span>}
      </header>

      {/* 첫 블록: 오늘 받은 알림 */}
      <Card title="오늘 받은 알림">
        {todays.length ? <FeedList items={todays} /> : (
          <p className="m-0 text-13 text-ink-3">
            오늘 받은 알림이 없습니다.{feed[0] ? <> 마지막은 <span className="num">{shortDate(feed[0].day)}</span> {feed[0].what}입니다.</> : null}
          </p>
        )}
      </Card>

      <SegBar label="알림 보기" options={TABS} value={tab} onChange={setTab} />
      {msg && <p role="alert" className="m-0 text-12 text-warn">{msg}</p>}

      {tab === 'inbox' && (
        <Panel title="지난 7일" source="발송 이력 · 장중 5분마다 갱신">
          <div className="mb-3"><SegBar label="알림 거르기" options={CATS} value={cat} onChange={setCat} /></div>
          {!rest.length ? <p className="m-0 text-13 text-ink-3">{cat === 'all' ? '어제부터 지난 7일 사이 받은 알림이 없습니다.' : `이 기간에 받은 ${CAT_LABEL[cat as Cat]} 알림이 없습니다.`}</p> : (
            <div className="flex flex-col gap-3">
              {[['어제', rest.filter(x => x.day === yesterday)], ['그 전', rest.filter(x => x.day < yesterday)]].map(([label, items]) => (items as Item[]).length ? (
                <section key={label as string}>
                  <h3 className="m-0 mb-1 text-12 font-bold text-ink-2">{label as string}</h3>
                  <FeedList items={items as Item[]} showDay={label === '그 전'} />
                </section>
              ) : null)}
            </div>
          )}
          <p className="mt-3 mb-0 text-12 text-ink-3">조건 이름은 이 기기에서 만든 조건에서 찾습니다. 다른 기기에서 만든 조건은 종류만, 현행 화면 조건은 번호로만 보입니다.</p>
        </Panel>
      )}

      {tab === 'cond' && (
        <>
          <NewCondition rows={reg} onAdd={a => save({ ...prefs, alerts: [...prefs.alerts, a] })} />
          <Panel title="내 조건" source={`이 기기에만 저장 · ${prefs.alerts.length}개`}>
            {prefs.alerts.length ? (
              <ul className="m-0 p-0 list-none">
                {prefs.alerts.map(a => {
                  const st = condStatus(a, fired[a.id], today, sync.on)
                  const name = `${regName.get(a.target) ?? a.target} ${condText(a)}`
                  return (
                  <li key={a.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 border-b border-line last:border-b-0">
                    <Switch on={a.enabled} label={<span className="sr-only">{a.target} 켜기</span>}
                      onChange={on => save({ ...prefs, alerts: prefs.alerts.map(x => (x.id === a.id ? { ...x, enabled: on } : x)) })} />
                    <span className="min-w-0 flex-1 text-13 text-ink-1">{regName.get(a.target) ?? a.target} <span className="text-ink-2">{condText(a)}</span></span>
                    <span className="text-12 text-ink-3">{a.repeat === 'once' ? '한 번' : '매일'} · {a.channels.map(c => (c === 'push' ? '폰' : '디스코드')).join('·')}</span>
                    {/* 이력을 못 읽었으면 「대기」라고 말하지 않는다 — 꺼짐과 「이 기기에만」은 이 기기가 안다 */}
                    {(state || st.kind === 'off' || st.kind === 'local') && <span className={`num text-12 whitespace-nowrap ${st.kind === 'fired' || st.kind === 'today' ? 'text-ink-1' : 'text-ink-3'}`}>{st.text}</span>}
                    {/* 다시 켠 것은 /prefs 로 올라가야 서버가 본다 — 동기화가 꺼져 있으면 눌러도 소용없다 */}
                    {st.kind === 'fired' && (sync.on ? (
                      <button type="button" className={BTN} aria-label={`${name} 다시 켜기`}
                        onClick={() => save({ ...prefs, alerts: prefs.alerts.map(x => (x.id === a.id ? rearm(x, fired[a.id]) : x)) })}>다시 켜기</button>
                    ) : <span className="text-12 text-ink-3">동기화를 켜면 다시 켤 수 있습니다</span>)}
                    <button type="button" onClick={() => save({ ...prefs, alerts: prefs.alerts.filter(x => x.id !== a.id) })} aria-label={`${a.target} 조건 지우기`} title="지우기"
                      className="size-8 inline-flex items-center justify-center rounded-btn border-0 bg-transparent text-ink-3 hover:text-ink-1 cursor-pointer">
                      <Trash2 size={14} aria-hidden />
                    </button>
                  </li>
                  )
                })}
              </ul>
            ) : <p className="m-0 text-13 text-ink-3">아직 만든 조건이 없습니다.</p>}
            <p className="mt-2 mb-0 text-12 text-ink-3">동기화를 켜면 서버가 이 조건을 보고 보냅니다. 장중에는 몇 분마다, 그 밖에는 매일 21:05 에 한 번 봅니다. 「한 번」 조건은 울리면 멈추고, 「다시 켜기」를 누르면 새 값이 들어온 뒤 다시 울립니다.</p>
          </Panel>
          <p className="m-0 text-12 text-ink-3">
            현행 화면에서 만든 조건은 <a href={new URL('legacy.html?p=portfolio', ROOT).href} className="text-ink-2">현행 화면</a>에서 보고 고칩니다.
          </p>
        </>
      )}

      {tab === 'chan' && <Channels prefs={prefs} onSave={save} />}
    </div>
  )
}

/** 알림 행: 무엇 · 값 · 거리 · 시각 · 원인 화면 링크. */
function FeedList({ items, showDay }: { items: Item[]; showDay?: boolean }) {
  return (
    <ul className="m-0 p-0 list-none">
      {items.map(x => {
        // 시각: 발송 이력은 마지막 발동 시각만 남긴다 — 그 앞 날짜들은 날짜만 안다
        const when = x.timed ? (showDay ? mdHm(new Date(x.at)) : mdHm(new Date(x.at)).split(' ')[1]) : showDay ? shortDate(x.day) : '시각 모름'
        const body = (
          <>
            <span className="w-[4.5rem] shrink-0 num text-12 text-ink-3">{when}</span>
            <span className="flex-1 min-w-0">
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <Pill tone={CAT_TONE[x.cat]}>{CAT_LABEL[x.cat]}</Pill>
                <span className="text-13 text-ink-1">{x.what}</span>
                {x.value && <span className="text-12 text-ink-2">{x.value}</span>}
              </span>
              {x.dist && <span className="block mt-0.5 text-12 text-ink-3">{x.dist}</span>}
            </span>
            {x.to && <ChevronRight size={14} aria-hidden className="shrink-0 text-ink-3" />}
          </>
        )
        const row = 'flex items-start gap-3 py-2'
        return (
          <li key={x.key} className="border-b border-line last:border-b-0">
            {x.to ? <Link to={x.to} className={`${row} no-underline`} aria-label={`${x.what} 원인 화면으로`}>{body}</Link> : <div className={row}>{body}</div>}
          </li>
        )
      })}
    </ul>
  )
}

const TYPES: { key: AlertType; label: string }[] = [
  { key: 'price', label: '가격 도달' }, { key: 'pct', label: '등락률' }, { key: 'high52', label: '52주 최고·최저' },
  { key: 'event', label: '일정 전날' }, { key: 'flow', label: '수급 전환' }, { key: 'lens', label: '렌즈 트리거' },
]
const WHO: Record<string, string> = { foreign: '외국인', inst: '기관', retail: '개인' }

function condText(a: AlertCond): string {
  const c = a.cond
  switch (a.type) {
    case 'price': return `${fmtNumber(Number(c.value), Number(c.value) % 1 ? 2 : 0)} ${c.op === '<=' ? '이하' : '이상'}`
    case 'pct': return `하루 ${Number(c.value) > 0 ? '+' : ''}${c.value}% 도달`
    case 'high52': return c.side === 'low' ? '52주 최저 이탈' : '52주 최고 돌파'
    case 'event': return '일정 하루 전'
    case 'flow': return `${WHO[String(c.who)] ?? c.who} 순매수·순매도 전환`
    case 'lens': return c.state === 'near' ? '렌즈 주시 진입' : '렌즈 돌파'
  }
}

/** 새 조건 만들기: 종류 6 · 대상(지표 사전 검색, 종목 코드는 그대로) · 조건 · 반복 · 채널. 저장 모양 = Worker /prefs alerts[]. */
function NewCondition({ rows, onAdd }: { rows: RegRow[]; onAdd: (a: AlertCond) => void }) {
  const [type, setType] = useState<AlertType>('price')
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState<{ id: string; label: string } | null>(null)
  // 상세가 주소(?id=)로 넘긴 지표: 한 번 읽고 주소에서 지운다. 사전이 늦게 와도 이름이 따라오도록 id 로 들고 있다가, 대상 칸을 고르거나 지우면 놓는다.
  const [urlId, setUrlId] = useViewParam<string>('id', '')
  const [pre, setPre] = useState(urlId)
  useEffect(() => { if (urlId) setUrlId('') }, [urlId, setUrlId])
  const target = picked ?? prefillTarget(pre, rows)
  const setTarget = (t: { id: string; label: string } | null) => { setPicked(t); setPre('') }
  const [op, setOp] = useState<'>=' | '<='>('>=')
  const [value, setValue] = useState('')
  const [side, setSide] = useState<'high' | 'low'>('high')
  const [who, setWho] = useState('foreign')
  const [lensState, setLensState] = useState<'crossed' | 'near'>('crossed')
  const [repeat, setRepeat] = useState<'once' | 'daily'>('once')
  const [push, setPush] = useState(true)
  const [discord, setDiscord] = useState(false)
  const [err, setErr] = useState('')

  const s = q.trim().toLowerCase()
  const hits = s ? rows.filter(r => [r.id, r.label, r.short, r.shortM].some(x => x?.toLowerCase().includes(s))).slice(0, 6) : []
  const raw = q.trim()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    const t = target ?? (TARGET_RE.test(raw) ? { id: raw, label: raw } : null)
    if (!t) { setErr('대상을 고르세요. 목록에 없으면 종목 코드(예: 005930)를 그대로 넣습니다.'); return }
    const v = Number(value)
    let cond: Record<string, string | number>
    if (type === 'price') { if (!(v > 0)) { setErr('가격을 넣으세요.'); return } cond = { op, value: v } }
    else if (type === 'pct') { if (!v) { setErr('등락률(%)을 넣으세요. 오름은 양수, 내림은 음수입니다.'); return } cond = { op: v > 0 ? '>=' : '<=', value: v } }
    else if (type === 'high52') cond = { side }
    else if (type === 'event') cond = { daysBefore: 1 }
    else if (type === 'flow') cond = { who }
    else cond = { state: lensState }
    const channels = [...(push ? ['push' as const] : []), ...(discord ? ['discord' as const] : [])]
    if (!channels.length) { setErr('받을 채널을 하나 이상 고르세요.'); return }
    onAdd({ id: condId(), target: t.id, type, cond, repeat, channels, enabled: true })
    setErr(''); setQ(''); setTarget(null); setValue('')
  }

  return (
    <Panel title="새 조건 만들기">
      <form onSubmit={submit} className="flex flex-col gap-3" aria-label="새 알림 조건">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <Field label="종류">
            <select className={INPUT} value={type} onChange={e => setType(e.target.value as AlertType)}>
              {TYPES.map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
          </Field>
          <Field label="대상 지표">
            <input className={INPUT} value={target ? target.label : q} placeholder="이름·코드로 찾기"
              onChange={e => { setTarget(null); setQ(e.target.value) }} autoComplete="off" />
          </Field>
        </div>
        {!target && hits.length > 0 && (
          <ul className="m-0 p-0 list-none flex flex-wrap gap-1" aria-label="찾은 지표">
            {hits.map(r => (
              <li key={r.id}><button type="button" className={BTN2} onClick={() => setTarget({ id: r.id, label: r.short || r.label })}>{r.short || r.label}</button></li>
            ))}
          </ul>
        )}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {type === 'price' && <>
            <Field label="방향"><select className={INPUT} value={op} onChange={e => setOp(e.target.value as '>=' | '<=')}><option value=">=">이상</option><option value="<=">이하</option></select></Field>
            <Field label="가격"><input className={INPUT} value={value} onChange={e => setValue(e.target.value)} inputMode="decimal" /></Field>
          </>}
          {type === 'pct' && <Field label="하루 등락률(%)"><input className={INPUT} value={value} onChange={e => setValue(e.target.value)} inputMode="decimal" placeholder="5 · -3" /></Field>}
          {type === 'high52' && <Field label="어느 쪽"><select className={INPUT} value={side} onChange={e => setSide(e.target.value as 'high' | 'low')}><option value="high">최고 돌파</option><option value="low">최저 이탈</option></select></Field>}
          {type === 'event' && <p className="m-0 col-span-2 self-end text-12 text-ink-3">이 지표의 발표 일정 하루 전에 알립니다.</p>}
          {type === 'flow' && <Field label="누구"><select className={INPUT} value={who} onChange={e => setWho(e.target.value)}>{Object.entries(WHO).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>}
          {type === 'lens' && <Field label="언제"><select className={INPUT} value={lensState} onChange={e => setLensState(e.target.value as 'crossed' | 'near')}><option value="crossed">돌파</option><option value="near">주시 진입</option></select></Field>}
          <Field label="반복"><select className={INPUT} value={repeat} onChange={e => setRepeat(e.target.value as 'once' | 'daily')}><option value="once">한 번</option><option value="daily">하루 한 번</option></select></Field>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="text-12 text-ink-2">채널</span>
          <Switch on={push} onChange={setPush} label="폰 알림" />
          <Switch on={discord} onChange={setDiscord} label="디스코드" />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="submit" className={BTN}>조건 저장</button>
          <span role="alert" className="text-12 text-warn">{err}</span>
        </div>
      </form>
    </Panel>
  )
}

/** 폰 알림: 이 기기 웹 푸시 구독 켜기·끄기(lib/push.ts). 동기화 키 해시는 sync.ts 에서 그때그때 받고 저장하지 않는다. */
function PhonePush() {
  const supported = pushSupported()
  const [on, setOn] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(supported && Notification.permission === 'denied' ? '알림이 막혀 있습니다. 브라우저 사이트 설정에서 풀어야 합니다.' : '')
  useEffect(() => { pushSubscribed().then(setOn, () => {}) }, [])
  const toggle = async (want: boolean) => {
    setBusy(true); setMsg('')
    try {
      await (want ? subscribePush(getKeyHash) : unsubscribePush(getKeyHash))
      setOn(want)
      setMsg(want ? '이 기기로 알림을 받습니다.' : '이 기기 알림을 껐습니다.')
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  return (
    <Panel title="폰 알림">
      {supported
        ? <Switch on={on} onChange={toggle} disabled={busy} label="이 기기로 받기" />
        : <p className="m-0 text-13 text-ink-2">이 브라우저는 웹 푸시를 지원하지 않습니다. 아이폰은 Safari 공유 메뉴의 「홈 화면에 추가」로 연 앱에서만 켤 수 있습니다.</p>}
      <p role="status" className="mt-2 mb-0 text-12 text-ink-2">{msg}</p>
      <p className="mt-3 mb-0 text-12 text-ink-3">켜 두면 알림이 이 기기로도 옵니다. 설정에서 동기화 키를 먼저 넣어야 켤 수 있습니다.</p>
    </Panel>
  )
}

/** 채널: 폰 알림(웹 푸시 구독) · 디스코드(안내) · 조용한 시간. */
function Channels({ prefs, onSave }: { prefs: Prefs; onSave: (p: Prefs) => void }) {
  const quiet = prefs.settings.quiet
  const setQuiet = (q: Prefs['settings']['quiet']) => onSave({ ...prefs, settings: { ...prefs.settings, quiet: q } })
  return (
    <div className="grid grid-cols-1 pc:grid-cols-3 gap-4 items-start">
      <PhonePush />
      <Panel title="디스코드">
        <p className="m-0 text-13 text-ink-2">급변·시황 알림은 지금도 운영 디스코드 채널로 나갑니다.</p>
        <p className="mt-2 mb-0 text-12 text-ink-3">조건에서 디스코드를 고르면 #종목-알림 채널로 나갑니다. 운영 쪽에 그 채널 연결이 등록돼 있지 않으면 나가지 않습니다.</p>
      </Panel>
      <Panel title="조용한 시간">
        <Switch on={!!quiet} onChange={on => setQuiet(on ? { from: '22:00', to: '07:00' } : null)} label="이 시간엔 폰 알림을 보내지 않기" />
        {quiet && (
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Field label="부터"><input type="time" className={INPUT} value={quiet.from} onChange={e => e.target.value && setQuiet({ ...quiet, from: e.target.value })} /></Field>
            <Field label="까지"><input type="time" className={INPUT} value={quiet.to} onChange={e => e.target.value && setQuiet({ ...quiet, to: e.target.value })} /></Field>
          </div>
        )}
        <p className="mt-3 mb-0 text-12 text-ink-3">한국 시각 기준입니다. 서버가 보내는 폰 알림도 이 시간을 따릅니다. 디스코드는 따르지 않습니다.</p>
      </Panel>
    </div>
  )
}
