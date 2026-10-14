// 오른쪽 패널(C6 · 과제 7) — 관심 · 최근 본 · 알림 · 일정. PC(980 이상)에만 있다.
// 1440 이상: 펼친 칸(300px)이 화면 오른쪽에 붙고 본문은 그만큼 좁아진다(App 이 useRail().open 으로 오른쪽 여백을 둔다 — 가로 넘침 0).
//   접으면 아이콘 줄(48px). 980~1439: 아이콘 줄만 두고, 누르면 덮개(바깥 누르기 · Esc · 화면 이동에 닫힘).
// 펼침 · 고른 탭은 이 기기에(localStorage, 못 쓰면 이번 화면만). 보유(금액)는 싣지 않는다 — 내 자산은 PIN 뒤다.
// 값: useItems 하나(지표 = 지표 사전 · 묶음, 종목 = 묶음 행 → /quotes) — 홈 관심 칸 · 검색 행도 같은 것을 쓴다.
// 알림 = 원장 최신판(events/latest.json — 알림 화면이 읽는 것과 같은 자료), 일정 = 홈 묶음 schedule.
import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Bell, CalendarDays, ChevronRight, History, PanelRightClose, Star, type LucideIcon } from 'lucide-react'
import { loadHome, loadIndicator, loadStocks, useBundleRev, type HomeBundle, type Sched, type StripItem } from '../lib/bundle'
import { isStockId, type StockRow } from '../lib/detail'
import { changeDir, fmtChange, fmtNumber, fmtPct, mdHm, safeHref, scaled, shortDate } from '../lib/format'
import { fromLedger, hhmm, type FeedRow } from '../lib/alerts/v2'
import { kstDay } from '../lib/personal/calc'
import { loadRootJson } from '../lib/personal/data'
import { batchQuotes, quoteItem, rowItem } from '../lib/personal/quotes'
import { KEYS, readRecent, type Recent } from '../lib/personal/store'
import { useWatch } from '../lib/watch'
import { AsOfBadge, Pill } from './ui'
import { LevelPill } from './personal/bits'

const DIR_TEXT = { up: 'text-up', down: 'text-down', flat: 'text-ink-2' } as const

/**
 * id(지표 · 종목) 목록의 값 칸. 지표 = loadIndicator(홈 띠 → 시장 묶음, 이름은 지표 사전),
 * 종목 = 묶음 행(홈 거래대금과 같은 날 값만 — 지난 상승 · 하락 목록 값을 오늘 값처럼 두지 않는다) → 없으면 /quotes(batchQuotes), 이름은 묶음 행.
 * 묶음을 다시 읽으면(rev) 다시 찾는다. 검색은 글자마다 목록이 바뀌므로 250ms 모아서 한 번. 못 찾은 id 는 결과에 없다.
 */
export function useItems(ids: string[]): Map<string, StripItem> {
  const rev = useBundleRev()
  const key = [...new Set(ids)].join(',')
  const [got, setGot] = useState(() => new Map<string, StripItem>())
  useEffect(() => {
    if (!key) return
    let live = true
    const t = setTimeout(async () => {
      const [home, rows] = await Promise.all([loadHome(false).catch(() => null), loadStocks().catch(() => new Map<string, StockRow>())])
      const day = home?.topAmount?.asOf?.slice(0, 10)
      const out = new Map<string, StripItem>()
      const ask: string[] = []
      await Promise.all(key.split(',').map(async id => {
        if (isStockId(id)) {
          const row = rows.get(id)
          if (row?.price != null && (!day || row.asOf?.slice(0, 10) === day)) out.set(id, rowItem(row))
          else ask.push(id)
          return
        }
        const r = await loadIndicator(id).catch(() => null)
        const base: StripItem | null = r?.item ?? (r?.reg ? { id, label: r.reg.label, decimals: r.reg.decimals, value: null, change: null, changePct: null, asOf: null } : null)
        if (base) out.set(id, { ...base, label: r?.reg?.label ?? base.label, short: r?.reg?.short ?? base.short })
      }))
      const q = ask.length ? await batchQuotes(ask) : null
      for (const id of ask) {
        const row = rows.get(id)
        if (q?.has(id) || row) out.set(id, quoteItem(id, row?.short || row?.name, q?.get(id)))
      }
      if (live) setGot(out)
    }, 250)
    return () => { live = false; clearTimeout(t) }
  }, [key, rev])
  return got
}

/** 값 · 등락 두 줄(오른쪽 정렬) — 관심 · 최근 본 · 검색 행. 값이 없으면 그리지 않는다. 등락률이 없는 칸(금리)은 변화량. */
export function ValueCell({ item }: { item?: StripItem }) {
  if (!item || item.value == null) return null
  const v = scaled(item.value, item.scale), chg = scaled(item.change, item.scale)
  const dir = item.changePct != null ? changeDir(item.changePct, 2) : changeDir(chg, item.decimals)
  return (
    <span className="shrink-0 text-right">
      <span className="block num text-13 text-ink-1">{fmtNumber(v, item.decimals)}</span>
      <span className={`block num text-11 ${DIR_TEXT[dir]}`}>{item.changePct != null ? fmtPct(item.changePct) : fmtChange(chg, null, item.decimals)}</span>
    </span>
  )
}

// ── 펼침 · 탭(이 기기) ──────────────────────────────────
const TABS: readonly { key: string; label: string; icon: LucideIcon }[] = [
  { key: 'watch', label: '관심', icon: Star }, { key: 'recent', label: '최근 본', icon: History },
  { key: 'alerts', label: '알림', icon: Bell }, { key: 'sched', label: '일정', icon: CalendarDays },
]
type RailState = { open: boolean; tab: string }
function readRail(): RailState {
  try {
    const v = JSON.parse(localStorage.getItem(KEYS.rail) || 'null')
    if (v && typeof v === 'object') return { open: v.open !== false, tab: TABS.some(t => t.key === v.tab) ? v.tab : 'watch' }
  } catch { /* 처음이거나 저장소가 막혔다 — 펼친 채 관심부터 */ }
  return { open: true, tab: 'watch' }
}
let rail = readRail()
const railSubs = new Set<() => void>()
function setRail(next: Partial<RailState>) {
  rail = { ...rail, ...next }
  try { localStorage.setItem(KEYS.rail, JSON.stringify(rail)) } catch { /* 저장 못 해도 이번 화면엔 남는다 */ }
  railSubs.forEach(f => f())
}
const onRail = (f: () => void) => { railSubs.add(f); return () => { railSubs.delete(f) } }
/** 오른쪽 패널 펼침 · 탭. App 이 open 을 보고 1440 이상에서 본문 오른쪽 여백(300px)을 둔다. */
export const useRail = () => useSyncExternalStore(onRail, () => rail)

const WIDE_MQ = '(min-width: 90rem)'   // 1440px — App 의 min-[90rem]: 과 같은 값
const onWide = (f: () => void) => { const m = matchMedia(WIDE_MQ); m.addEventListener('change', f); return () => m.removeEventListener('change', f) }
const isWide = () => matchMedia(WIDE_MQ).matches

export default function Rail() {
  const { open, tab } = useRail()
  const wide = useSyncExternalStore(onWide, isWide)
  const [peek, setPeek] = useState(false)   // 1440 미만의 덮개
  const { pathname } = useLocation()
  useEffect(() => { setPeek(false) }, [pathname, wide])
  useEffect(() => {
    if (!peek) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setPeek(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [peek])
  // 아이콘: 1440 이상이면 그 탭으로 펼치고, 아래면 덮개를 연다(같은 탭을 다시 누르면 닫는다)
  const choose = (t: string) => {
    if (wide) { setRail({ open: true, tab: t }); return }
    setPeek(!(peek && tab === t))
    setRail({ tab: t })
  }
  const panel = (onClose: () => void, closeLabel: string, at: string) => (
    <aside aria-label="오른쪽 패널" className={`hidden pc:flex fixed inset-y-0 ${at} z-30 w-75 flex-col bg-card border-l border-line`}>
      <div className="shrink-0 flex items-stretch border-b border-line">
        <div role="tablist" aria-label="오른쪽 패널" className="flex-1 grid grid-cols-4">
          {TABS.map(({ key, label }) => {
            const on = key === tab
            return (
              <button key={key} type="button" role="tab" aria-selected={on} onClick={() => setRail({ tab: key })}
                className={`h-14 px-1 border-0 border-b-2 bg-transparent cursor-pointer text-13 whitespace-nowrap ${on ? 'border-accent text-ink-1 font-bold' : 'border-transparent text-ink-2 hover:text-ink-1'}`}>{label}</button>
            )
          })}
        </div>
        <button type="button" onClick={onClose} aria-label={closeLabel} title={closeLabel}
          className="w-10 inline-flex items-center justify-center border-0 bg-transparent cursor-pointer text-ink-3 hover:text-ink-1"><PanelRightClose size={18} aria-hidden /></button>
      </div>
      <div role="tabpanel" aria-label={TABS.find(t => t.key === tab)?.label} className="flex-1 min-h-0 overflow-y-auto p-3">
        {tab === 'recent' ? <RecentTab /> : tab === 'alerts' ? <AlertsTab /> : tab === 'sched' ? <SchedTab /> : <WatchTab />}
      </div>
    </aside>
  )

  if (wide && open) return panel(() => setRail({ open: false }), '오른쪽 패널 접기', 'right-0')
  return (
    <>
      <nav aria-label="오른쪽 패널" className="hidden pc:flex fixed inset-y-0 right-0 z-30 w-12 flex-col items-center gap-1 pt-2.5 bg-card border-l border-line">
        {TABS.map(({ key, label, icon: Icon }) => {
          const on = peek && key === tab
          return (
            <button key={key} type="button" onClick={() => choose(key)} aria-pressed={on} aria-label={label} title={label}
              className={`size-9 inline-flex items-center justify-center rounded-btn border-0 cursor-pointer ${on ? 'bg-accent text-on-accent' : 'bg-transparent text-ink-2 hover:text-ink-1'}`}>
              <Icon size={18} aria-hidden />
            </button>
          )
        })}
      </nav>
      {peek && !wide && (
        <>
          <div aria-hidden className="hidden pc:block fixed inset-0 z-20 bg-ink-1/20" onClick={() => setPeek(false)} />
          {panel(() => setPeek(false), '닫기 (Esc)', 'right-12')}
        </>
      )}
    </>
  )
}

const Empty = ({ children }: { children: ReactNode }) => <p className="m-0 text-13 text-ink-3">{children}</p>
const MoreLink = ({ to, children }: { to: string; children: ReactNode }) => (
  <Link to={to} className="inline-flex items-center mt-2 text-12 text-ink-2 no-underline hover:text-ink-1">{children}<ChevronRight size={14} aria-hidden /></Link>
)

/** 값 줄 목록: 이름(+ 기준 시각) | 값 · 등락. 누르면 그 상세(바깥 글은 새 탭). */
function ItemList({ rows }: { rows: { key: string; label: string; to?: string; href?: string; item?: StripItem }[] }) {
  return (
    <ul className="m-0 p-0 list-none">
      {rows.map(r => {
        const body = (
          <>
            <span className="min-w-0 flex-1">
              <span className="block text-13 text-ink-1 [overflow-wrap:anywhere]">{r.label}</span>
              {r.item?.asOf && <span className="block leading-tight"><AsOfBadge asOf={r.item.asOf} state={r.item.state} liveUntil={r.item.liveUntil} /></span>}
            </span>
            <ValueCell item={r.item} />
          </>
        )
        const cls = 'flex items-center gap-3 py-2 no-underline'
        const href = r.href ? safeHref(r.href) : null   // 적을 때도 거르지만 그리는 곳에서 한 번 더(javascript: 등)
        return (
          <li key={r.key} className="border-b border-line last:border-b-0">
            {href ? <a href={href} target="_blank" rel="noopener noreferrer" className={cls}>{body}</a> : <Link to={r.to ?? '/'} className={cls}>{body}</Link>}
          </li>
        )
      })}
    </ul>
  )
}

function WatchTab() {
  const watch = useWatch()
  const items = useItems(watch.ids)
  if (!watch.ids.length) return <Empty>별을 누른 지표 · 종목이 여기에 모입니다.</Empty>
  return <ItemList rows={watch.ids.map(id => ({ key: id, to: `/i/${id}`, label: items.get(id)?.short || items.get(id)?.label || id, item: items.get(id) }))} />
}

/** 최근 본: 상세를 연 것(Detail.tsx) + 검색에서 고른 것. 화면을 옮길 때마다 다시 읽는다. */
function RecentTab() {
  const { pathname } = useLocation()
  const [list, setList] = useState<Recent[]>(readRecent)
  useEffect(() => { setList(readRecent()) }, [pathname])
  const idOf = (r: Recent) => (r.to.startsWith('/i/') ? decodeURIComponent(r.to.slice(3)) : '')
  const items = useItems(list.map(idOf).filter(Boolean))
  if (!list.length) return <Empty>상세를 연 지표 · 종목이 여기에 남습니다(이 기기에만).</Empty>
  return (
    <ItemList rows={list.map(r => {
      const it = items.get(idOf(r))
      return { key: r.to, label: it?.short || it?.label || r.label, item: it, ...(r.to.startsWith('/') ? { to: r.to } : { href: r.to }) }
    })} />
  )
}

/** 받은 알림 최근 20 — 알림 화면과 같은 원장 · 같은 줄 모양(fromLedger). */
function AlertsTab() {
  const [rows, setRows] = useState<FeedRow[] | null | undefined>(undefined)
  useEffect(() => { loadRootJson<unknown>('events/latest.json').then(r => setRows(fromLedger(r, new Map()).slice(0, 20)), () => setRows(null)) }, [])
  if (rows === undefined) return <Empty>불러오는 중</Empty>
  const today = kstDay()
  return (
    <>
      {rows?.length ? (
        <ul className="m-0 p-0 list-none">
          {rows.map(x => (
            <li key={x.key} className="border-b border-line last:border-b-0">
              <Link to={x.to ?? '/alerts'} className="flex items-start gap-2 py-2 no-underline">
                <span className="w-16 shrink-0 num text-12 text-ink-3">{x.day === today ? hhmm(x.at) : mdHm(new Date(x.at))}</span>
                <span className="min-w-0 flex-1 text-13 text-ink-1 [overflow-wrap:anywhere]">{x.title}</span>
                <LevelPill level={x.level} />
              </Link>
            </li>
          ))}
        </ul>
      ) : <Empty>{rows ? '최근 7일 받은 알림이 없습니다.' : '받은 알림을 불러오지 못했습니다.'}</Empty>}
      <MoreLink to="/alerts">알림 화면</MoreLink>
    </>
  )
}

// 일정에 섞여 오는 종목 공시(kind) → 알약 글자(홈 일정 패널과 같은 표)
const CORP_KIND: Record<string, string> = { dividend: '배당', earnings: '실적' }

function SchedTab() {
  const rev = useBundleRev()
  const [home, setHome] = useState<HomeBundle | null | undefined>(undefined)
  useEffect(() => { loadHome(false).then(setHome, () => setHome(null)) }, [rev])
  if (home === undefined) return <Empty>불러오는 중</Empty>
  const today = home?.market?.today ?? kstDay()
  const rows = (home?.schedule ?? []) as (Sched & { kind?: string | null })[]
  if (!rows.length) return <Empty>다가오는 일정이 없습니다.</Empty>
  return (
    <ul className="m-0 p-0 list-none">
      {rows.map((e, i) => (
        <li key={`${e.date}-${e.name}-${i}`} className="flex items-baseline gap-2 py-2 border-b border-line last:border-b-0">
          <span className="w-[4.5rem] shrink-0 num text-12 text-ink-3">{`${e.date === today ? '오늘' : shortDate(e.date)}${e.time ? ` ${e.time}` : ''}`}</span>
          <span className="min-w-0 flex-1 text-13 text-ink-1 [overflow-wrap:anywhere]">
            {e.kind && CORP_KIND[e.kind] && <span className="mr-1.5"><Pill tone="o">{CORP_KIND[e.kind]}</Pill></span>}
            {e.name}{e.approx ? <span className="text-ink-3"> (추정)</span> : null}
          </span>
          {!!e.stars && <span className="shrink-0 text-11 text-ink-3" aria-label={`중요도 ${e.stars}`}>{'★'.repeat(e.stars)}</span>}
        </li>
      ))}
    </ul>
  )
}
