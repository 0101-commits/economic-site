// 이 기기 저장소(localStorage) 한 곳. 키와 모양:
//   portfolioV1   = { groups, items: Holding[], alerts, lastSync, ... }  현행 사이트(js/app2.js)와 같은 문서. 모르는 필드는 그대로 둔다.
//   pfSnapshotsV1 = [{ d:'YYYY-MM-DD', ev, ct, src? }]                   현행과 같음 + src('app' 앱이 낸 값 · 'close' 마스터 작업 종가 값). 날짜는 한국 날짜(옛 판의 UTC 날짜 칸은 그대로 둔다).
//                   앱을 열 때 하루 한 번(snapDaily.ts) 남기고, 서버(/snaps — 보유와 같은 열쇠로 잠금)와 날짜별로 합친다(snapSync.ts · snapRules.ts).
//   pfLedgerV1    = [{ id, d, kind:'div'|'dep'|'wd', amt, memo }]         현행과 같음. 서버로 보내지 않는다.
//   econPrefsV1   = { v:2, alerts, settings, scenarios }                  새 화면 전용. 모양은 Worker /prefs 문서와 같다(올리고 받는 것은 sync.ts).
//                   열쇠 이름은 v1 그대로 — 읽을 때 v1 문서를 v2 로 바꾼다(prefsV2.ts).
//   econAlertsHk_v1 = { since, ring, off, demoted }                       알림 자동 정리(housekeeping.ts). 이 기기에만.
//   econHoldKey_v1 = 보유 재료 hex(sync.ts — 앱키에서 만든 것, 기억 해시와 같은 수명). 맞춘 기록은 econPrefsSync_v1(sync.ts) · econHoldSync_v1(holdSync.ts),
//                   둘 다 바뀌어 진 쪽 한 벌은 econPrefsV1:prev · portfolioV1:prev(scoped.ts keepPrev). 옛 범위 기록 econSyncScope_v1 은 읽지 않는다.
//   econSearchRecentV1 = [{ label, to, kind }]                            「최근 본 것」(검색 · 오른쪽 패널) — 검색에서 고른 것 + 상세를 연 것(recent.ts).
//   econRail_v1   = { open, tab }                                         오른쪽 패널(components/Rail.tsx) 펼침 · 고른 탭.
// 보유 금액이 든 읽기(readPortfolio·readSnaps·readLedger)는 PinGate 안의 화면과, 잠금이 열린 뒤의 내려받기에서만 부른다.
import { upsertSnap, type Holding, type Snap, type Unit } from './calc'
import { upgradePrefs } from './prefsV2'
import { housekeep, type Hk } from './housekeeping'
import { addRecent, recentList, type Recent } from './recent'
import { watchKind } from './remote'
import { unsubscribePush, type GetKeyHash } from '../push'
import { applyTheme, readTheme } from '../theme'
import type { MyData } from './backup'
import { storeKey } from './who'
import { kstDate } from './snapRules'
import { noteHoldEdit } from './holdSync'
import { read, write, readPortfolio, writePortfolio, readSnaps, writeSnaps, readLedger, writeLedger, scopedWipeNames, wipeAllPeople } from './scoped'
export { readPortfolio, writePortfolio, readSnaps, readLedger, writeLedger }
export type { Portfolio, Ledger } from './scoped'
import type { Portfolio } from './scoped'
import '../../components/personal/updown.css'
export { storeKey }

export const KEYS = {
  // 보유 · 스냅샷 · 원장 · 설정 · 관심 · 시나리오는 사람마다 이름이 갈린다 → who.ts storeKey(). 여기엔 두지 않는다.
  // recent(와 quotes.ts 시세 캐시 · 맞춘 기록)도 사람마다 갈린다 — 쓰는 곳은 이 이름을 storeKey() 로 감싸 쓴다(마스터는 이 이름 그대로).
  recent: 'econSearchRecentV1', theme: 'econNextTheme_v1',
  hk: 'econAlertsHk_v1',         // 알림 자동 정리 기록(housekeeping.ts) — 조건 id · 시각만
  holdKey: 'econHoldKey_v1',     // 보유 재료(sync.ts) — 앱키에서 만든 hex
  rail: 'econRail_v1',           // 오른쪽 패널 펼침 · 탭(components/Rail.tsx)
} as const

// ── 보유 ──────────────────────────────────────────────
export const newId = (prefix: string) => prefix + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)

/**
 * 오늘(한국 날짜) 스냅샷 한 건을 앱이 낸 값(src:'app')으로 넣는다. 하루 1건 — 오늘 칸이 이미 있으면(다른 기기 · 마스터 작업의 종가 값 포함) 덮지 않는다.
 * 서버로 올리는 것은 sync.ts syncSnaps.
 */
export function saveTodaySnap(ev: number, ct: number): Snap[] {
  const cur = readSnaps(), d = kstDate()
  if (cur.some(s => s.d === d)) return cur
  const next = upsertSnap(cur, { d, ev: Math.round(ev), ct: Math.round(ct), src: 'app' })
  writeSnaps(next)
  return next
}

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
  armSide?: 'u' | 'd'                                            // U1 의 켠 순간 쪽(alertStatus.sideOf) — 비공개 /prefs 에만
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

export const readPrefs = (): Prefs => upgradePrefs(read<unknown>(storeKey('econPrefsV1'), null))
export const writePrefs = (p: Prefs) => write(storeKey('econPrefsV1'), p)

/** 자동 정리 기록(housekeeping.ts) — 이 기기에만. */
export const readHk = (): Hk => { const h = read<unknown>(KEYS.hk, {}); return h && typeof h === 'object' ? (h as Hk) : {} }
export const writeHk = (h: Hk) => write(KEYS.hk, h)

/** 앱이 뜰 때 한 번(App.tsx): 원장 최신판으로 자동 정리를 돌리고, 바뀌면 저장 + 다른 화면에 알린다. seen = 알림 화면을 마지막으로 연 때(이번 열기 전). */
export function tidyAlerts(rows: unknown, seen: string | null, now = Date.now()) {
  const r = housekeep(readPrefs(), readHk(), now, Date.parse(seen ?? '') || 0, Array.isArray(rows) ? rows : [])
  writeHk(r.hk)
  if (r.changed && writePrefs(r.prefs)) window.dispatchEvent(new StorageEvent('storage', { key: storeKey('econPrefsV1') }))
}

/** 등락 색: 'kr' = 상승 빨강(기본, 속성 없음) · 'us' = 상승 초록(updown.css). 앱이 뜰 때 App.tsx 가 한 번 부른다. */
export function applyUpdown(u: Updown) {
  if (u === 'us') document.documentElement.dataset.updown = 'us'
  else document.documentElement.removeAttribute('data-updown')
}

// ── 내 데이터 파일(backup.ts — 설정 「내 데이터」) ──────────────
/** 내려받기 재료. 비밀(키 해시 · 보유 열쇠 재료 · PIN)과 사용 기록은 읽지 않는다. 관심은 watch.ts 처럼 현행 화면 즐겨찾기를 이어받는다. */
export function readMyData(): MyData {
  const wk = storeKey('econ_watch_v1')
  // 옛 즐겨찾기(econ_fav_v1)는 마스터(옛 이름) 것이다 — 멤버는 잇지 않는다.
  const p = readPrefs(), w = read<unknown>(wk, null) ?? (wk === 'econ_watch_v1' ? read<unknown>('econ_fav_v1', []) : []), sc = read<unknown>(storeKey('econ_scenarios_v1'), [])
  return {
    portfolio: readPortfolio(), snapshots: readSnaps(), ledger: readLedger(),
    watch: Array.isArray(w) ? w.filter((x): x is string => typeof x === 'string') : [],
    prefs: { alerts: p.alerts, settings: p.settings }, theme: readTheme(),
    scenarios: Array.isArray(sc) ? sc : [],
  }
}
/**
 * 올리기: 파일에 있는 칸만 이 기기에 쓴다(이전 화면 백업은 보유 · 스냅샷만). 실패가 하나라도 있으면 false.
 * 다른 화면은 storage 이벤트로 다시 읽는다(sync.ts writeLocal 과 같은 길). 설정은 sync.ts 감시가 바뀐 것을 올리고,
 * 보유는 「이 기기에서 바꿈」으로 적어 두어(noteHoldEdit) 다음 맞춤이 이 파일 것을 나중 것으로 올린다.
 */
export function writeMyData(d: Partial<MyData>): boolean {
  const puts: [string, unknown][] = [[storeKey('portfolioV1'), d.portfolio], [storeKey('pfSnapshotsV1'), d.snapshots], [storeKey('econ_watch_v1'), d.watch], [storeKey('econ_scenarios_v1'), d.scenarios],
    [storeKey('econPrefsV1'), d.prefs && { ...readPrefs(), ...d.prefs }]]
  const done = puts.filter(([, v]) => v !== undefined)
  let ok = done.map(([k, v]) => write(k, v)).every(Boolean)
  if (d.ledger) { ok = writeLedger(d.ledger) && ok; done.push([storeKey('pfLedgerV1'), d.ledger]) }
  if (d.portfolio) noteHoldEdit()
  if (d.theme) applyTheme(d.theme)
  if (d.prefs) applyUpdown(d.prefs.settings.updown)
  for (const [key] of done) window.dispatchEvent(new StorageEvent('storage', { key }))
  return ok
}

// ── 최근 본 것(검색 · 오른쪽 패널) ─────────────────────────
export type { Recent }
export const readRecent = (): Recent[] => recentList(read<unknown>(storeKey(KEYS.recent), []))
export function pushRecent(r: Recent) {
  write(storeKey(KEYS.recent), addRecent(readRecent(), r))
}
/** 상세(/i/<id>)를 열 때 한 번 — 지표 · 종목 모두. 이름은 모르므로 id 를 적고, 전에 적힌 이름이 있으면 남긴다(보이는 이름은 읽는 쪽이 사전 · 묶음에서 찾는다). */
export function noteRecent(id: string) {
  if (id) write(storeKey(KEYS.recent), addRecent(readRecent(), { label: id, to: `/i/${id}`, kind: watchKind(id) === 'stock' ? '종목' : '지표' }, true))
}

/**
 * 이 기기 데이터 지우기 대상. 잠금 PIN 은 남긴다(설정 화면이 그렇다고 적는다 — PIN 잊음에서 지울 때는 PinGate 가 따로 지운다).
 * 옛 화면(js/app2.js)의 앱키 해시 · 평단가 암호(pfSyncKey* · pfHoldingsPass)도 지운다 — 예전 판은 localStorage 에, 지금 판은 이 탭 sessionStorage 에 둔다.
 * 최근 본 것 · 맞춘 기록 · 옛 범위 기록 · 진 쪽 한 벌 · 보유 시세 캐시(quotes.ts, sessionStorage — 종목 목록이 드러난다)는 사람별 이름이라 scopedWipeNames 에 든다.
 */
export const wipeKeys = () => [...scopedWipeNames(), KEYS.theme, KEYS.hk, KEYS.holdKey, KEYS.rail,
  'pfHoldingsPass', 'pfSyncKeyHash', 'pfSyncKey', 'econAlertsSeen_v1', 'econ_fold_v1', 'econ_usage_v1', 'econ_home_cache_v1']
/** PIN 잊음 전용: 잠금 PIN 은 이 기기 모든 사람의 자료를 지켰으므로 모든 사람 것을 지운다(scoped.wipeAllPeople). 설정의 「이 기기 데이터 지우기」는 그대로 wipeDevice(지금 사람만). */
export async function wipeDeviceAll(getKeyHash: GetKeyHash): Promise<boolean> {
  await unsubscribePush(getKeyHash).catch(() => {})
  const mine = new Set(scopedWipeNames())
  return wipeAllPeople(wipeKeys().filter(k => !mine.has(k)))
}
/** 지우기 전에 이 기기 폰 알림 구독을 끊는다(서버 쪽 해지에 동기화 키 해시가 쓰인다 — 그래서 동기화는 이 뒤에 끈다). 못 끊어도 지우기는 계속. */
export async function wipeDevice(getKeyHash: GetKeyHash): Promise<boolean> {
  await unsubscribePush(getKeyHash).catch(() => {})
  const keys = wipeKeys()   // 지금 사람의 이름뿐 — 다른 사람 것은 그대로
  try { for (const s of [localStorage, sessionStorage]) keys.forEach(k => s.removeItem(k)); return true } catch { return false }
}
