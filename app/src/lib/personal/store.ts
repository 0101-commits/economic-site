// 이 기기 저장소(localStorage) 한 곳. 키와 모양:
//   portfolioV1   = { groups, items: Holding[], alerts, lastSync, ... }  현행 사이트(js/app2.js)와 같은 문서. 모르는 필드는 그대로 둔다.
//   pfSnapshotsV1 = [{ d:'YYYY-MM-DD', ev, ct }]                          현행과 같음. 날짜는 현행처럼 UTC 기준(두 화면이 같은 날을 같은 칸에 쓴다).
//   pfLedgerV1    = [{ id, d, kind:'div'|'dep'|'wd', amt, memo }]         현행과 같음. 서버로 보내지 않는다.
//   econPrefsV1   = { v:1, alerts, settings, scenarios }                  새 화면 전용. 모양은 Worker /prefs 문서와 같다(동기화는 후속).
//   econSearchRecentV1 = [{ label, to, kind }]                            검색 「최근 본 것」.
// 보유 금액이 든 읽기(readPortfolio·readSnaps·readLedger)는 PinGate 안의 화면과, 잠금이 열린 뒤의 내려받기에서만 부른다.
import { upsertSnap, type Holding, type Snap, type Unit } from './calc'
import '../../components/personal/updown.css'

export const KEYS = {
  portfolio: 'portfolioV1', snaps: 'pfSnapshotsV1', ledger: 'pfLedgerV1',
  prefs: 'econPrefsV1', recent: 'econSearchRecentV1', watch: 'econ_watch_v1', theme: 'econNextTheme_v1',
} as const

function read<T>(key: string, fallback: T): T {
  try { const v = JSON.parse(localStorage.getItem(key) || 'null'); return v ?? fallback } catch { return fallback }
}
/** 저장 실패(시크릿 창·용량 초과)는 false — 화면이 「저장 못 함」을 말해야 입력이 소리 없이 사라지지 않는다. */
function write(key: string, v: unknown): boolean {
  try { localStorage.setItem(key, JSON.stringify(v)); return true } catch { return false }
}

// ── 보유 ──────────────────────────────────────────────
export type Portfolio = { groups: { id: string; name: string }[]; items: Holding[]; alerts: unknown[]; [k: string]: unknown }

export function readPortfolio(): Portfolio {
  const p = read<Partial<Portfolio> | null>(KEYS.portfolio, null)
  const items = Array.isArray(p?.items) ? p!.items.filter(x => x && typeof x.symbol === 'string') : []
  const groups = Array.isArray(p?.groups) && p!.groups.length ? p!.groups : [{ id: 'g_default', name: '기본 그룹' }]
  return { lastSync: null, ...p, groups, items, alerts: Array.isArray(p?.alerts) ? p!.alerts : [] }
}
export const writePortfolio = (p: Portfolio) => write(KEYS.portfolio, p)
export const newId = (prefix: string) => prefix + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)

export const readSnaps = (): Snap[] => { const a = read<unknown>(KEYS.snaps, []); return Array.isArray(a) ? a : [] }
/** 오늘(UTC 날짜) 스냅샷 한 건을 넣는다. 같은 날은 바꿔 넣으므로 하루 1건. */
export function saveTodaySnap(ev: number, ct: number): Snap[] {
  const next = upsertSnap(readSnaps(), { d: new Date().toISOString().slice(0, 10), ev: Math.round(ev), ct: Math.round(ct) })
  write(KEYS.snaps, next)
  return next
}

export type Ledger = { id: string; d: string; kind: 'div' | 'dep' | 'wd'; amt: number; memo?: string }
export const readLedger = (): Ledger[] => { const a = read<unknown>(KEYS.ledger, []); return Array.isArray(a) ? a : [] }
export const writeLedger = (a: Ledger[]) => write(KEYS.ledger, [...a].sort((x, y) => (x.d < y.d ? -1 : 1)).slice(-500))

// ── 설정·알림 조건(Worker /prefs 와 같은 모양) ────────────────
export type AlertType = 'price' | 'pct' | 'high52' | 'event' | 'flow' | 'lens'
export type AlertCond = {
  id: string; target: string; type: AlertType; cond: Record<string, string | number>
  repeat: 'once' | 'daily'; channels: ('push' | 'discord')[]; enabled: boolean
}
export type Updown = 'kr' | 'us'
export type Settings = { updown: Updown; unit: Unit; quiet: { from: string; to: string } | null }
export type Prefs = { v: 1; alerts: AlertCond[]; settings: Settings; scenarios: { name: string; inputs: Record<string, unknown> }[] }

export function readPrefs(): Prefs {
  const p = read<Partial<Prefs> | null>(KEYS.prefs, null)
  const s: Partial<Settings> = p?.settings ?? {}
  return {
    v: 1,
    alerts: Array.isArray(p?.alerts) ? p!.alerts : [],
    settings: { updown: s.updown === 'us' ? 'us' : 'kr', unit: s.unit === 'won' ? 'won' : 'man', quiet: s.quiet?.from && s.quiet?.to ? s.quiet : null },
    scenarios: Array.isArray(p?.scenarios) ? p!.scenarios : [],
  }
}
export const writePrefs = (p: Prefs) => write(KEYS.prefs, p)

/** 등락 색: 'kr' = 상승 빨강(기본, 속성 없음) · 'us' = 상승 초록(updown.css). 앱이 뜰 때 App.tsx 가 한 번 부른다. */
export function applyUpdown(u: Updown) {
  if (u === 'us') document.documentElement.dataset.updown = 'us'
  else document.documentElement.removeAttribute('data-updown')
}

// ── 검색 최근 ───────────────────────────────────────────
export type Recent = { label: string; to: string; kind: string }
export const readRecent = (): Recent[] => { const a = read<unknown>(KEYS.recent, []); return Array.isArray(a) ? a.slice(0, 8) : [] }
export function pushRecent(r: Recent) {
  write(KEYS.recent, [r, ...readRecent().filter(x => x.to !== r.to)].slice(0, 8))
}

/** 이 기기 데이터 지우기 대상. 잠금 PIN·현행 화면 동기화 키는 남긴다(설정 화면이 그렇다고 적는다). */
export const WIPE_KEYS = [KEYS.portfolio, KEYS.snaps, KEYS.ledger, KEYS.watch, KEYS.prefs, KEYS.recent, KEYS.theme]
export function wipeDevice(): boolean {
  try { WIPE_KEYS.forEach(k => localStorage.removeItem(k)); return true } catch { return false }
}
