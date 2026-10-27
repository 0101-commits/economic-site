// 앱키로 들어온 기기끼리 저절로 맞춤 — ① 관심 · 알림 조건 · 표시 설정 · 렌즈 시나리오(Worker /prefs)와 ② 보유(/portfolio 의 잠근 덩어리, holdSync.ts).
// ③ 폰 알림 구독은 lib/push.ts 가 같은 앱키 해시로 한다. 사람에게 묻지 않는다 — 어느 쪽을 남길지는 syncRules.ts 규칙 하나.
// /prefs 문서에 보유(portfolioV1)·스냅샷·원장은 없다. 보내는 문서는 remote.ts toServer 가 아래 저장소 세 곳에서만 만든다.
// 보유는 앱키에서 만든 재료로 잠근 덩어리(e2e.ts)로만 /portfolio 에 올린다. 스냅샷·원장은 어디로도 보내지 않는다.
//
// 규칙
//   앱키    화면에서 받은 앱키 원문은 저장하지 않는다. 들어올 때(원문이 손에 있을 때) 두 가지로 바꿔 둔다:
//           SHA-256 해시 → sessionStorage econSyncHash_v1(이 탭) + localStorage econSyncHashKeep_v1(기억 — 새 탭이 PIN 없이 잇는다, 결정 D10),
//           보유 재료(e2e.ts holdKeyOf) → localStorage econHoldKey_v1. 기억 해시와 재료는 수명이 같다 —
//           「이 기기에서 나가기」 · 앱키가 틀려(401) 끊김 · 이 기기 데이터 지우기(store.ts wipeKeys) · 다른 탭에서 지움(storage 이벤트) 때 함께 지운다.
//   새 입장 앱키 → 해시 · 재료 → GET /prefs. 맞춘 기록(설정 econPrefsSync_v1 · 보유 econHoldSync_v1)을 지우고 맞춘다 — 서버에 있으면 서버 것,
//           없으면 이 기기 것을 올린다(syncRules 1 · 3). 기기에 다른 것이 있었으면 한 벌(…:prev) 남긴다. 서버에 못 닿으면 들어오지 않는다.
//   보내기  1초마다 이 기기 문서를 비교해, 바뀐 뒤 2초 조용하면 PUT(If-Match = 마지막으로 본 updatedAt). 바뀐 것을 본 때를 editAt 으로 적어 둔다.
//           요청 사이는 6초 이상 — Worker AI_LIMITER 가 /ai·/portfolio 와 같은 바구니로 IP 당 분당 10회다.
//           탭을 숨기거나 닫는 순간 못 보낸 것이 있으면 바로 보낸다.
//   409     다른 기기가 먼저 저장했다 → 서버 문서를 받아 규칙대로(둘 다 바뀜 = 나중 것). 진 쪽은 econPrefsV1:prev 에 한 벌.
//   401     앱키가 틀렸거나 다른 기기가 앱키를 바꿨다 → 해시 · 재료를 지우고 이 기기에서 나간다(같은 브라우저의 다른 탭이 바꾼 것이면 새 해시로 잇는다).
//   받기    앱을 열 때와 탭으로 돌아올 때(1분에 한 번까지). 못 보낸 것이 있으면 받기 전에 먼저 보낸다. 보유도 같은 때 맞춘다.
//   알리기  서버 내용으로 덮은 뒤 키마다 storage 이벤트를 쏜다 — 다른 탭에서 바뀐 것과 같은 길로 화면이 다시 읽는다. 보유를 받으면 holdRev 가 오른다.
//   기기만  화면 모드 · 금액 단위 · 90일 자동 강등은 문서에 없다(remote.ts syncedOf) — 받을 때도 이 기기 값을 둔다(명세 S9).
//   옛 범위 기록 econSyncScope_v1({ prefs, hold })은 읽지 않는다 — 끔이 남아 있어도 모두 맞춘다(사용자 요청). 이름은 지우기 목록에만 남는다.
// ponytail: 바뀜 감지는 1초 폴링(저장소 세 곳 읽기). 쓰는 곳(관심 별·알림·설정·렌즈·다른 탭)에 손대지 않으려고 고른 방식이다.
//   쓰는 곳이 늘어 폴링이 무거워지면 저장 함수마다 알림을 쏘는 방식으로 바꾼다.
import { useSyncExternalStore } from 'react'
import { samePin } from '../pin'
import { dropLocalPush, pushSubscribed, pushSupported, subscribePush, unsubscribePush } from '../push'
import { clearMe, markPaused } from './account'
import { applyUpdown, KEYS, readPrefs, storeKey, writePrefs } from './store'
import { fromServer, keyChangeText, keyHash, portfolioGet, portfolioPost, prefsCall, syncedOf, syncKeyChange, toServer, type Local, type PrefsDoc, type Reply } from './remote'
import { holdKeyOf, relockBlob } from './e2e'
import { prefsStep, type PrefsRec } from './syncRules'
import { makeHoldSync, noteHoldEdit, noteHoldNames, resetHoldRec, type HoldResult, type HoldState } from './holdSync'
import { keepPrev, read, write } from './scoped'
import { currentPerson } from './who'

const HASH_KEY = 'econSyncHash_v1'
const KEEP_KEY = 'econSyncHashKeep_v1'
const QUIET_MS = 2_000                 // 바뀐 뒤 이만큼 조용하면 보낸다
const GAP_MS = 6_000                   // 요청 사이 최소 간격(분당 10회 아래)
const RETRY_MS = 60_000                // 서버에 못 닿았을 때 다시 해 볼 때까지
const PULL_MS = 60_000                 // 탭으로 돌아올 때 다시 받는 최소 간격
const HEX64 = /^[0-9a-f]{64}$/

function readHex(s: () => Storage, k: string): string | null {
  try { const h = s().getItem(k); return h && HEX64.test(h) ? h : null } catch { return null }
}
/** 앱키 해시(64자 hex) — 없으면 null. 웹 푸시(/push/subscribe)도 이것으로 인증한다. */
export const getKeyHash = () => readHex(() => sessionStorage, HASH_KEY)
const keptHash = () => readHex(() => localStorage, KEEP_KEY)
const holdKey = () => readHex(() => localStorage, KEYS.holdKey)

// ── 설정 맞춘 기록(사람별, 값 없음 — syncRules.PrefsRec) ─────────
const readPrefsRec = (): PrefsRec => { const r = read<unknown>(storeKey('econPrefsSync_v1'), {}); return r && typeof r === 'object' && !Array.isArray(r) ? (r as PrefsRec) : {} }
const writePrefsRec = (r: PrefsRec) => write(storeKey('econPrefsSync_v1'), r)

// ── 화면에 보이는 상태 ───────────────────────────────────
/**
 * linked = 이 탭에 앱키 해시가 있음 · on = 설정을 주고받는 중(= linked — 범위 스위치는 없어졌다) · at = 마지막으로 맞춘 때(설정 · 보유)
 * · hold = 보유 맞춤 한 줄(holdSync.HoldState — 예전 암호 칸 · 예비 앱키 · 안내) · holdRev = 보유를 받을 때마다 1씩(내 자산이 다시 읽는다)
 * · pushAt = 들어오며 폰 알림을 켠 때(화면이 구독 상태를 다시 읽는다).
 */
export type SyncStatus = { linked: boolean; on: boolean; busy: boolean; msg: string; at: number | null; rev: number; hold: HoldState; holdRev: number; pushAt: number }
let st: SyncStatus = { linked: getKeyHash() != null, on: getKeyHash() != null, busy: false, msg: '', at: null, rev: 0, hold: { kind: '', text: '' }, holdRev: 0, pushAt: 0 }
const subs = new Set<() => void>()
function set(p: Partial<SyncStatus>) { st = { ...st, ...p }; subs.forEach(f => f()) }
const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f) } }
/** rev 는 서버 내용으로 이 기기를 덮을 때마다 1씩 오른다 — 상태를 들고 있는 화면은 이때 다시 읽는다. */
export const useSyncStatus = () => useSyncExternalStore(subscribe, () => st)
/** 입장 관문(App.tsx)용: 이 탭에 앱키 해시가 있나 — 들어옴 · 끊김(401 포함) 때 바로 다시 그린다(값이 같으면 그리지 않는다). */
export const useHasKey = () => useSyncExternalStore(subscribe, () => getKeyHash() != null)
/** 알림 화면의 범위 문구 — on = 조건을 서버가 봄, push = 이 기기 폰 알림 구독. */
export const scopeText = (on: boolean, push: boolean) => (on ? (push ? '폰 알림 켜짐' : '이 기기 폰 알림 꺼짐') : '이 기기만 — 울리지 않음')

// ── 이 기기 저장소 세 곳 ─────────────────────────────────
function readJson(k: string): unknown { try { return JSON.parse(localStorage.getItem(k) || 'null') } catch { return null } }

function readLocal(): Local {
  const w = readJson(storeKey('econ_watch_v1')), sc = readJson(storeKey('econ_scenarios_v1')), p = readPrefs()
  return {
    watch: Array.isArray(w) ? w.filter((x): x is string => typeof x === 'string') : [],
    alerts: p.alerts, settings: syncedOf(p.settings),
    scenarios: Array.isArray(sc) ? sc.filter(x => x && typeof x.name === 'string') : [],
  }
}

function writeLocal(l: Local) {
  const put = (k: string, v: unknown) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* 저장 못 하면 이번 화면만 그대로 */ } }
  put(storeKey('econ_watch_v1'), l.watch)
  put(storeKey('econ_scenarios_v1'), l.scenarios)
  const cur = readPrefs()
  writePrefs({ ...cur, alerts: l.alerts, settings: { ...cur.settings, ...l.settings } })   // 금액 단위 · 자동 강등은 이 기기 값 그대로
  applyUpdown(l.settings.updown)
  for (const key of [storeKey('econ_watch_v1'), storeKey('econPrefsV1'), storeKey('econ_scenarios_v1')]) window.dispatchEvent(new StorageEvent('storage', { key }))
}

const fp = () => JSON.stringify(readLocal())

// ── 서버와 주고받기 ─────────────────────────────────────
let prev: PrefsDoc | null = null   // 마지막으로 본 서버 문서(updatedAt · 관심 담은 때)
let sent = ''                      // 서버와 같다고 아는 이 기기 문서(지문)
let seen = '', changedAt = 0, lastReq = 0, lastPull = 0, retryAt = 0, busy = false, timer = 0
let changing = false               // 앱키 바꾸는 중(changeKey) — 주고받기를 멈춘다
let permAsk: Promise<unknown> | null = null   // 들어가기 단추를 누른 순간 물어 둔 알림 허락(connectSync)

/** 마지막 요청 시각 — /ai 도 /prefs · /portfolio 와 분당 10회를 나눠 쓴다(GAP_MS). 홈 질문칸이 보내기 직전에 읽고 알린다. */
export const lastReqAt = () => lastReq
export const noteReq = () => { lastReq = Date.now() }

function errText(r: Reply): string {
  if (r.status === 0) return '서버에 닿지 못했습니다. 1분 뒤 다시 해 봅니다.'
  if (r.status === 429) return '요청이 많아 1분 뒤 다시 해 봅니다.'
  if (r.error === 'sync_key_not_configured') return '앱키가 아직 설정되지 않았습니다. 모임 운영자에게 문의해 주세요.'
  if (r.error === 'forbidden_origin') return '이 주소에서 연 화면은 서버가 받지 않습니다.'
  if (r.error === 'tier2_field_rejected') return `보유정보로 보이는 칸(${r.field ?? '?'})이 있어 서버가 받지 않았습니다.`
  if (r.status === 413) return '맡길 내용이 너무 커서 서버가 받지 않았습니다. 관심·알림 조건을 줄여 주세요.'
  if (r.status === 400) return `서버가 받지 않았습니다(${r.error ?? r.status}).`
  return `서버가 받지 않았습니다(${r.error ?? r.status}). 1분 뒤 다시 해 봅니다.`
}
/** 같은 내용을 다시 보내도 또 거절되는 응답 — 이 기기 것이 다시 바뀔 때까지 기다린다. */
const refused = (r: Reply) => r.status === 400 || r.status === 413

const KEY_LOST = '앱키가 맞지 않아 이 기기에서 나갔습니다. 앱키로 다시 들어와 주세요.'
const PREFS_KEPT = '다른 기기에서 나중에 바꾼 설정을 받았습니다. 이 기기에서 바꾼 것은 한 벌 남겨 두었습니다.'
/** 401: 같은 브라우저의 다른 탭이 앱키를 바꿨으면(기억 해시가 다르면) 그 해시로 잇고, 아니면 끊는다. */
function lost(h: string) {
  if (changing) return   // 앱키 바꾸는 중 — 옛 해시로 나간 요청의 401 은 바뀐 결과다
  const k = keptHash()
  if (k && k !== h) adopt(k)
  else { clearMe(); disableSync(KEY_LOST); void dropLocalPush() }   // account.refreshMe 의 401 과 같은 뒷정리(끊긴 표시를 먼저 · 이 브라우저 폰 알림 구독도 끊는다)
}

/** 요청 한 번 + 공통 처리. 해시가 없거나 401 이면(끊는다) null. 받지 못한 응답(409 제외)은 알림 글을 남긴다. */
async function call(put?: Parameters<typeof prefsCall>[1]): Promise<Reply | null> {
  const h = getKeyHash()
  if (!h) return null
  busy = true; set({ busy: true }); lastReq = Date.now()
  const r = await prefsCall(h, put)
  busy = false; set({ busy: false })
  if (r.status === 401) { lost(h); return null }
  if (r.status === 403 && getKeyHash() === h) markPaused()   // 멈춤 — 앱키 · 연결은 그대로, 표시만(account.refreshMe 의 403 과 같다)
  if (!r.doc && r.status !== 409) set({ msg: errText(r) })
  return r
}

/** 서버 문서와 같아졌다(f = 이 기기 지문) — 맞춘 기록을 새로 둔다. 그사이 이 기기에서 또 바꿨으면 바꾼 때는 남긴다. */
function agree(f: string, srvAt: string | null) {
  const r = readPrefsRec()
  writePrefsRec({ base: f, srvAt, ...(r.editAt && fp() !== f ? { editAt: r.editAt } : {}) })
}

/** 서버 문서로 이 기기를 덮는다. 안내 글은 실제로 바뀐 것이 있을 때만. */
function apply(doc: PrefsDoc, msg = '') {
  const was = fp()
  prev = doc
  writeLocal(fromServer(doc))
  sent = seen = fp()
  writePrefsRec({ base: sent, srvAt: doc.updatedAt })
  set({ msg: sent === was ? '' : msg, at: Date.now(), rev: st.rev + 1 })
}

/**
 * 서버 문서를 받은 뒤 규칙대로(syncRules.prefsStep): 서버 것으로 덮거나 · 이 기기 것을 올리거나 · 기록만 새로.
 * 둘 다 바뀌었으면 나중 것이 이기고 진 쪽은 econPrefsV1:prev 에 한 벌. quiet = 새 입장(안내 글 없음). depth = 409 를 따라온 횟수.
 */
async function settlePrefs(doc: PrefsDoc, quiet = false, depth = 0): Promise<boolean> {
  const rec = readPrefsRec(), local = readLocal(), f = JSON.stringify(local)
  const s = prefsStep(rec, local, f, doc)
  prev = doc
  seen = f
  if (s.keep === 'device') keepPrev('econPrefsV1', { side: 'device', at: rec.editAt ?? null, data: local })
  if (s.keep === 'server') keepPrev('econPrefsV1', { side: 'server', at: doc.updatedAt, data: fromServer(doc) })
  if (s.act === 'pull') { apply(doc, s.keep === 'device' && !quiet ? PREFS_KEPT : ''); return true }
  if (s.act === 'push') return pushPrefs(false, depth)
  sent = f
  agree(f, doc.updatedAt)
  set({ at: Date.now() })
  return true
}

/** 서버 내용을 받아 규칙대로 맞춘다(앱을 열 때 · 돌아올 때). */
export async function pullPrefs(): Promise<boolean> {
  if (busy) return false
  lastPull = Date.now()
  const r = await call()
  if (!r) return false
  if (!r.doc) { retryAt = Date.now() + RETRY_MS; return false }
  return settlePrefs(r.doc)
}

/** 이 기기 문서를 올린다(전체 교체). 409 면 서버 문서를 받아 규칙대로(두 번까지). */
export async function pushPrefs(keepalive = false, depth = 0): Promise<boolean> {
  if (busy && !keepalive) return false
  const local = readLocal(), f = JSON.stringify(local)
  const r = await call({ body: toServer(local, prev, new Date().toISOString()), ifMatch: prev?.updatedAt ?? null, keepalive })
  if (!r) return false
  if (r.status === 409) {
    const g = await call()
    if (g?.doc && depth < 2) return settlePrefs(g.doc, false, depth + 1)
    if (g) retryAt = Date.now() + RETRY_MS
    return false
  }
  if (!r.doc) {
    if (refused(r)) sent = f
    else retryAt = Date.now() + RETRY_MS
    return false
  }
  prev = r.doc
  sent = f
  agree(f, r.doc.updatedAt)
  set({ msg: '', at: Date.now() })
  return true
}

async function tick() {
  if (!getKeyHash()) { stop(); if (st.linked) set({ linked: false, on: false }); return }
  const now = Date.now()
  if (changing || busy || now < retryAt) return
  if (!prev) { await pullPrefs(); return }   // 서버 문서를 이 탭에서 아직 못 봤으면 받는 것부터
  const f = fp()
  if (f !== seen) {
    seen = f; changedAt = now
    // 이 기기에서 바꿨다 — 바꾼 때를 남긴다(둘 다 바뀌었을 때 「나중」을 가린다, syncRules 6)
    if (f !== sent) writePrefsRec({ ...readPrefsRec(), editAt: new Date(now).toISOString() })
    return
  }
  if (f !== sent && now - changedAt >= QUIET_MS && now - lastReq >= GAP_MS) await pushPrefs()
}

function begin() { if (!timer) timer = window.setInterval(() => void tick(), 1000); set({ linked: true, on: true }) }
function stop() { if (timer) clearInterval(timer); timer = 0 }

/** 같은 브라우저의 다른 탭이 들어오거나 앱키를 바꾼 해시로 이 탭도 잇는다. */
function adopt(h: string) {
  try { sessionStorage.setItem(HASH_KEY, h) } catch { disableSync(KEY_LOST); return }
  prev = null; sent = ''; retryAt = 0
  set({ msg: '' })
  begin()
}

function onVisibility() {
  if (!getKeyHash()) return
  if (document.visibilityState === 'hidden') { if (prev && fp() !== sent) void pushPrefs(true); return }
  if (Date.now() - lastHold > PULL_MS) void syncHoldings()
  if (!prev || busy || Date.now() < retryAt) return
  if (fp() !== sent) void pushPrefs()
  else if (Date.now() - lastPull > PULL_MS) void pullPrefs()
}

/**
 * 다른 탭의 일을 따라간다.
 *   기억 해시가 새 값으로 바뀜 → 그 탭이 들어왔거나 앱키를 바꿨다 → 이 탭도 그 해시로 잇는다(옛 해시로 401 을 받아 새 기억까지 지우지 않게).
 *   기억 해시 · 설정 문서가 지워짐 → 「이 기기에서 나가기」나 「이 기기 데이터 지우기」 → 이 탭도 끊는다 — 그대로 두면 이 탭이 비워진 저장소를
 *   기본값 문서로 읽어 서버에 올리고, 서버의 알림 조건이 사라진다.
 * 같은 탭 안에서 이 앱이 쏘는 storage 이벤트(writeLocal · tidyAlerts · 알림 시트)는 storageArea 가 없어 걸리지 않는다.
 */
function onStorage(e: StorageEvent) {
  if (e.storageArea !== localStorage) return
  if (e.key === KEEP_KEY && e.newValue && HEX64.test(e.newValue)) { if (e.newValue !== getKeyHash()) adopt(e.newValue); return }
  if (e.newValue !== null || (e.key !== KEEP_KEY && e.key !== storeKey('econPrefsV1'))) return
  if (getKeyHash()) disableSync('다른 탭에서 나가거나 이 기기 데이터를 지워 이 탭도 나갔습니다.')
}

/** 앱이 뜰 때 한 번(main.tsx). 이 탭에 해시가 없으면 기억한 해시를 옮겨 오고(PIN 없이), 있으면 설정 · 보유를 맞추고 감시를 시작한다. */
export function startSync() {
  // 옛 화면이 예전에 localStorage 에 남긴 비밀(앱키 해시 · 평단가 암호 원문)은 새 화면이 쓰지 않는다 — 열자마자 지운다(B3).
  for (const k of ['pfSyncKeyHash', 'pfHoldingsPass']) { try { localStorage.removeItem(k) } catch { /* 막힌 저장소 */ } }
  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener('storage', onStorage)
  const kept = keptHash()
  if (!getKeyHash() && kept) { try { sessionStorage.setItem(HASH_KEY, kept) } catch { /* 막힌 저장소 = 잇지 않음 */ } }
  if (getKeyHash()) { begin(); void syncHoldings() }
}

// ── 들어오기 · 나가기 · 앱키 바꾸기 ─────────────
function fail(msg: string) { set({ busy: false, msg }); return false }

/**
 * 들어오기(account.signIn 이 부른다): 앱키 원문은 여기서 해시 · 재료로만 바꾸고 어디에도 남기지 않는다. 묻지 않는다 — 서버 우선으로 맞춘다.
 * perm = 들어가기 단추를 누른 그 순간에 물은 알림 허락(아이폰 · 사파리는 사용자 동작 안에서만 묻는다) — 허락이 있으면 이 기기를 구독한다.
 */
export async function connectSync(key: string, perm?: Promise<unknown>): Promise<boolean> {
  permAsk = perm ?? null
  if (!key.trim()) return fail('앱키를 넣어 주세요.')
  set({ busy: true, msg: '' })
  let h: string, mat: string
  try { [h, mat] = await Promise.all([keyHash(key), holdKeyOf(key)]) } catch { return fail('이 환경(https 아님)에서는 들어갈 수 없습니다.') }
  const r = await prefsCall(h)
  if (r.status === 401) return fail('앱키가 맞지 않습니다.')
  if (!r.doc) return fail(r.status === 0 ? '서버에 닿지 못했습니다. 잠시 뒤 다시 하세요.' : r.status === 429 ? '요청이 많습니다. 1분 뒤 다시 하세요.' : errText(r))
  set({ busy: false })
  try { sessionStorage.setItem(HASH_KEY, h) } catch { return fail('이 탭에 앱키 확인 기록을 남길 수 없어 들어갈 수 없습니다.') }
  try { localStorage.setItem(KEEP_KEY, h); localStorage.setItem(KEYS.holdKey, mat) } catch { /* 기억 못 하면 이 탭에서만 잇는다 */ }
  // 새 입장: 맞춘 기록을 지워 서버 우선으로(syncRules 3)
  writePrefsRec({}); resetHoldRec()
  prev = null; sent = ''; retryAt = 0
  set({ msg: '' })
  begin()
  await settlePrefs(r.doc, true)
  void syncHoldings()
  void autoPush()
  return true
}

/** 들어오면 폰 알림도 켠다. 허락을 못 받았으면 그대로 둔다 — 설정 › 내 계정의 스위치로 켠다. */
async function autoPush() {
  const p = permAsk
  permAsk = null
  if (!pushSupported() || ((await p) ?? Notification.permission) !== 'granted') return
  await subscribePush(getKeyHash).catch(() => {})
  set({ pushAt: Date.now() })
}

/** 「이 기기에서 나가기」: 이 기기 폰 알림 구독을 끊고(해시가 필요하니 먼저) 해시 · 기억 · 보유 재료를 지운다. 이 기기 자료와 서버에 맡긴 것은 그대로. */
export async function forgetDevice() {
  await unsubscribePush(getKeyHash).catch(() => {})
  disableSync()
}

/** 끊기: 이 탭의 해시 · 기억 해시 · 보유 재료를 지운다. 이 기기 자료와 서버에 맡긴 것은 그대로 둔다. */
export function disableSync(msg = '') {
  try { sessionStorage.removeItem(HASH_KEY) } catch { /* 막힌 저장소 = 원래 없음 */ }
  for (const k of [KEEP_KEY, KEYS.holdKey]) { try { localStorage.removeItem(k) } catch { /* 같음 */ } }
  stop()
  prev = null; sent = ''; retryAt = 0
  set({ linked: false, on: false, busy: false, msg, hold: { kind: '', text: '' } })
}

/**
 * 앱키 바꾸기(명세 B5). '' = 바뀜. 새 앱키는 12자 이상 · 지금 앱키와 다름 · 잠금 PIN 과 다름(앞의 둘은 서버도 다시 본다).
 * 지금 앱키는 이 탭 해시와 먼저 견준다(틀린 앱키로 서버를 두드리지 않게). 서버 보유를 확인하지 못하면 바꾸지 않는다.
 * 바뀌면 이 탭 해시 · 기억 해시 · 보유 재료를 새 앱키로 바꾸고, 서버 보유를 새 재료로 다시 잠가 올리고, 이 기기 폰 알림 구독을 새 공간으로 옮긴다.
 * /prefs 는 서버가 옛 공간 문서를 새 공간으로 옮겨 두므로 다음 맞춤이 그것을 받는다(옮기지 못해 비어 있으면 이 기기 것을 올린다).
 * 다른 기기는 새 앱키로 다시 들어와야 한다(옛 해시는 401).
 */
export async function changeKey(cur: string, next: string): Promise<string> {
  const h = getKeyHash()
  if (!h) return '먼저 앱키로 들어와 주세요.'
  const n = next.trim()
  if (n.length < 12) return '새 앱키는 12자 이상이어야 합니다.'
  if (n === cur.trim()) return '지금 앱키와 다른 앱키를 쓰세요.'
  set({ busy: true, msg: '' })
  changing = true
  try {
    // PIN 과 같은지는 samePin 으로 견준다 — checkPin 이면 실패로 세어 잠금 대기가 걸린다. 옛 화면 PIN 은 아무 글자일 수 있다.
    for (const p of new Set([next, n])) if (await samePin(p)) return '잠금 PIN 과 다른 앱키를 쓰세요.'
    if ((await keyHash(cur)) !== h) return keyChangeText({ status: 401 })
    // 옛 재료는 지금 앱키 원문에서 만든다 — 재료를 기억하지 않은 기기도 서버 판을 옮긴다.
    const [nh, mat, old] = await Promise.all([keyHash(n), holdKeyOf(n), holdKeyOf(cur)])
    // 보유: 서버 판을 옛 재료로 풀어 새 재료로 미리 잠가 둔다. 올리기는 앱키가 바뀐 뒤(새 해시로).
    const relock = await relockBlob(await portfolioGet(h), old, mat)
    if (relock === false) return '보유를 확인하지 못해 앱키를 바꾸지 않았습니다. 잠시 뒤 다시 해 주세요.'
    const r = await syncKeyChange(cur, next)
    if (r.status !== 200) return keyChangeText(r)
    try { sessionStorage.setItem(HASH_KEY, nh); localStorage.setItem(KEEP_KEY, nh); localStorage.setItem(KEYS.holdKey, mat) } catch { /* 막힌 저장소 — 다음에 들어올 때 다시 */ }
    prev = null; sent = ''; retryAt = 0   // 다음 맞춤이 새 공간을 받는다(서버가 옮겨 둔 문서 — 비어 있으면 이 기기 것을 올린다)
    if (relock) {
      const p = await portfolioPost(nh, relock)
      if (p.ok) await hold.noteUploaded(relock)
      else set({ hold: { kind: 'error', text: '보유를 새 앱키로 다시 잠그지 못했습니다. 내 자산에서 바꾸기 전 앱키를 한 번 넣으면 옮겨집니다.' } })
    }
    if (await pushSubscribed().catch(() => false)) await subscribePush(getKeyHash).catch(() => {})
    return ''
  } finally { changing = false; set({ busy: false }) }
}

// ── 보유 — holdSync.ts(규칙 · 기록 · 진 쪽 한 벌). 여기는 언제 돌릴지와 화면 상태만 ─────────
// 돌리는 때: 들어올 때 · 앱을 열 때 · 탭으로 돌아올 때(1분에 한 번까지) · 내 자산을 열 때 · 보유 저장 2초 뒤.
// 화면엔 보유 값을 보이지 않으므로 PIN 잠금 앞(앱을 열 때)에서 돌아도 된다 — 보유를 보이는 곳은 PinGate 안의 내 자산뿐이다.
const hold = makeHoldSync({
  hash: getKeyHash, mat: holdKey, backup: () => currentPerson()?.viaBackup === true,
  get: h => { lastReq = Date.now(); return portfolioGet(h) },
  post: (h, e) => { lastReq = Date.now(); return portfolioPost(h, e) },
  lost,
})
let holdTail: Promise<unknown> = Promise.resolve(), holdQueued: Promise<HoldResult> | null = null, holdTimer = 0, lastHold = 0

/** 맞춤 한 번(차례대로 — 겹치지 않게). 자동 맞춤은 기다리는 것이 있으면 그것 하나로 합친다. */
function runHold(o: { old?: string; drop?: boolean } = {}): Promise<HoldResult> {
  const auto = !o.old && !o.drop
  if (auto && holdQueued) return holdQueued
  const p = holdTail.then(() => { if (auto) holdQueued = null; lastHold = Date.now(); return hold.run(o) })
    .then(r => {
      set({ hold: r.state.kind === 'wait' ? st.hold : r.state, ...(r.pulled ? { holdRev: st.holdRev + 1 } : {}), ...(r.pulled || r.pushed ? { at: Date.now() } : {}) })
      return r
    }, () => ({ pulled: false, pushed: false, state: st.hold }))
  if (auto) holdQueued = p
  holdTail = p
  return p
}
/** 묻지 않고 하는 보유 맞춤. 받았으면 true. */
export const syncHoldings = async (): Promise<boolean> => (getKeyHash() ? (await runHold()).pulled : false)
/** 옛 형식 판을 예전 암호(예전 평단가 암호 · 바꾸기 전 앱키)로 풀어 맞추고 지금 앱키로 다시 잠근다(내 자산 한 줄 칸). */
export const unlockHoldings = (old: string) => runHold({ old })
/** 예전 암호를 모를 때: 못 여는 서버 판 대신 이 기기 보유를 지금 앱키로 잠가 둔다(서버 판은 이 기기 portfolioV1:prev 에 그대로). */
export const replaceHoldings = () => runHold({ drop: true })

/** 보유 저장 뒤 2초 조용하면 맞춘다. 받았으면 onPulled. */
export function queueHoldSync(onPulled?: () => void) {
  clearTimeout(holdTimer)
  holdTimer = window.setTimeout(() => { void syncHoldings().then(p => { if (p) onPulled?.() }) }, QUIET_MS)
}
/** 이 기기에서 보유를 바꿨다(내 자산 저장 · 파일 올리기) — 바꾼 때를 남기고 2초 뒤 맞춘다. */
export function holdEdited(onPulled?: () => void) { noteHoldEdit(); queueHoldSync(onPulled) }
/** 이름만 고쳤다 — 다음 맞춤에서 한 번 올려 이름이 다른 기기로 간다. */
export function holdNamesFixed() { noteHoldNames(); queueHoldSync() }
