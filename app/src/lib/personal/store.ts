// 이 기기 저장소(localStorage) 한 곳. 키와 모양:
//   portfolioV1   = { groups, items: Holding[], alerts, lastSync, ... }  현행 사이트(js/app2.js)와 같은 문서. 모르는 필드는 그대로 둔다.
//   pfSnapshotsV1 = [{ d:'YYYY-MM-DD', ev, ct }]                          현행과 같음. 날짜는 현행처럼 UTC 기준(두 화면이 같은 날을 같은 칸에 쓴다).
//   pfLedgerV1    = [{ id, d, kind:'div'|'dep'|'wd', amt, memo }]         현행과 같음. 서버로 보내지 않는다.
//   econPrefsV1   = { v:2, alerts, settings, scenarios }                  새 화면 전용. 모양은 Worker /prefs 문서와 같다(올리고 받는 것은 sync.ts).
//                   열쇠 이름은 v1 그대로 — 읽을 때 v1 문서를 v2 로 바꾼다(prefsV2.ts).
//   econAlertsHk_v1 = { since, ring, off, demoted }                       알림 자동 정리(housekeeping.ts). 이 기기에만.
//   econHoldKey_v1 = 보유 열쇠 재료 hex(sync.ts — 동기화 키에서 만든 것, 기억 해시와 같은 수명) · econSyncScope_v1 = 기기 연결 범위 { prefs, hold }.
//   econSearchRecentV1 = [{ label, to, kind }]                            검색 「최근 본 것」.
// 보유 금액이 든 읽기(readPortfolio·readSnaps·readLedger)는 PinGate 안의 화면과, 잠금이 열린 뒤의 내려받기에서만 부른다.
import { upsertSnap, type Holding, type Snap, type Unit } from './calc'
import { upgradePrefs } from './prefsV2'
import { housekeep, type Hk } from './housekeeping'
import { unsubscribePush, type GetKeyHash } from '../push'
import '../../components/personal/updown.css'

export const KEYS = {
  portfolio: 'portfolioV1', snaps: 'pfSnapshotsV1', ledger: 'pfLedgerV1',
  prefs: 'econPrefsV1', recent: 'econSearchRecentV1', watch: 'econ_watch_v1', theme: 'econNextTheme_v1',
  holdSync: 'econHoldSync_v1',   // 보유 동기화 기록(sync.ts) — 지문·시각만, 보유 값 없음
  hk: 'econAlertsHk_v1',         // 알림 자동 정리 기록(housekeeping.ts) — 조건 id · 시각만
  holdKey: 'econHoldKey_v1',     // 보유 열쇠 재료(sync.ts) — 동기화 키에서 만든 hex
  scope: 'econSyncScope_v1',     // 기기 연결 범위(sync.ts)
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

// ── 설정·알림 조건 v2(Worker /prefs 와 같은 모양 — 계약서 docs/superpowers/plans/2026-10-05-alerts-v2.md 「설정 /prefs v2」) ──
// 조건 한 건 = 사건(사전 A1~H4 · 사용자 U1 수준 도달 · U2 급변 값) + 대상 + 세기 · 등급 · 반복 · 울림.
// 대상 '*' 는 사건 탭의 「사건 전체 조정」(세기 · 등급)이다 — ring 을 비워 둔다(서버 subscribe._override 는 ring 이 있으면 모든 대상을 켜고 끈다).
// 읽을 때 v1(type 6종)은 prefsV2.upgradePrefs 가 바꾼다(서버 subscribe.upgrade_prefs 와 같은 규칙).
export type Level = 'alarm' | 'alert' | 'notice' | 'record'
export type Strength = 'normal' | 'big' | 'huge' | 'value'
export type Pkg = 'quiet' | 'normal' | 'many'
export type AlertCond = {
  id: string; event: string; target: string; strength?: Strength; value?: number; dir?: 'up' | 'down'
  level?: Level; repeat: 'each' | 'once'; ring?: boolean; enabled: boolean; armedAt?: string; name?: string
}
export type Updown = 'kr' | 'us'
export type Settings = {
  updown: Updown; unit: Unit; quiet: { from: string; to: string } | null
  package: Pkg; ringChannel: 'kakao' | 'push' | 'both'; dailyCap: number; quietAlarm: boolean
  briefings: { morning: boolean; close: boolean; noon: boolean; evening: boolean; us: boolean; weekly: boolean }
  families: Record<'A' | 'B' | 'C' | 'D' | 'E' | 'F' | 'G' | 'H', boolean>; rememberKey: boolean
  kakaoFriends: boolean                                           // 카톡 친구 모드로 받기(운영 변수 KAKAO_FRIENDS 와 짝)
  kakaoRecipients: { uuid: string; name: string; briefOnly: boolean }[]   // ≤5. uuid 는 서버가 친구 목록 이름으로 채운다
  autoQuiet: boolean                                              // 90일 미열람 자동 강등(housekeeping.ts). 이 기기만 — /prefs 에 싣지 않는다(remote.ts syncedOf)
}
export type Prefs = { v: 2; alerts: AlertCond[]; settings: Settings; scenarios: { name: string; inputs: Record<string, unknown> }[] }

export const readPrefs = (): Prefs => upgradePrefs(read<unknown>(KEYS.prefs, null))
export const writePrefs = (p: Prefs) => write(KEYS.prefs, p)

/** 자동 정리 기록(housekeeping.ts) — 이 기기에만. */
export const readHk = (): Hk => { const h = read<unknown>(KEYS.hk, {}); return h && typeof h === 'object' ? (h as Hk) : {} }
export const writeHk = (h: Hk) => write(KEYS.hk, h)

/** 앱이 뜰 때 한 번(App.tsx): 원장 최신판으로 자동 정리를 돌리고, 바뀌면 저장 + 다른 화면에 알린다. seen = 알림 화면을 마지막으로 연 때(이번 열기 전). */
export function tidyAlerts(rows: unknown, seen: string | null, now = Date.now()) {
  const r = housekeep(readPrefs(), readHk(), now, Date.parse(seen ?? '') || 0, Array.isArray(rows) ? rows : [])
  writeHk(r.hk)
  if (r.changed && writePrefs(r.prefs)) window.dispatchEvent(new StorageEvent('storage', { key: KEYS.prefs }))
}

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

/**
 * 이 기기 데이터 지우기 대상. 잠금 PIN 은 남긴다(설정 화면이 그렇다고 적는다 — PIN 잊음에서 지울 때는 PinGate 가 따로 지운다).
 * 현행 화면(js/app2.js)의 동기화 키 해시 · 보유 암호(pfSyncKey* · pfHoldingsPass)도 지운다 — 예전 판은 localStorage 에, 지금 판은 이 탭 sessionStorage 에 둔다.
 * econHoldQuotes_v1 = 보유 종목 시세 캐시(quotes.ts, sessionStorage) — 종목 목록이 드러나므로 같이 지운다.
 */
export const WIPE_KEYS = [KEYS.portfolio, KEYS.snaps, KEYS.ledger, KEYS.watch, KEYS.prefs, KEYS.recent, KEYS.theme, KEYS.holdSync, KEYS.hk,
  KEYS.holdKey, KEYS.scope,
  'pfHoldingsPass', 'pfSyncKeyHash', 'pfSyncKey', 'econ_scenarios_v1', 'econAlertsSeen_v1', 'econ_fav_v1', 'econ_fold_v1', 'econHoldQuotes_v1']
/** 지우기 전에 이 기기 폰 알림 구독을 끊는다(서버 쪽 해지에 동기화 키 해시가 쓰인다 — 그래서 동기화는 이 뒤에 끈다). 못 끊어도 지우기는 계속. */
export async function wipeDevice(getKeyHash: GetKeyHash): Promise<boolean> {
  await unsubscribePush(getKeyHash).catch(() => {})
  try { for (const s of [localStorage, sessionStorage]) WIPE_KEYS.forEach(k => s.removeItem(k)); return true } catch { return false }
}
