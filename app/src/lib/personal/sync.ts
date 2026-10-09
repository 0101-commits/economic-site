// 기기 연결 — 동기화 키 하나로 ① 관심 · 알림 조건 · 표시 설정 · 렌즈 시나리오(Worker /prefs)와 ② 보유(/portfolio 의 잠근 덩어리)를 맞춘다.
// ③ 폰 알림 구독은 lib/push.ts 가 같은 키 해시로 한다. 화면은 설정 「기기 연결」(components/personal/DeviceLink.tsx) 한 곳.
// /prefs 문서에 보유(portfolioV1)·스냅샷·원장은 없다. 보내는 문서는 remote.ts toServer 가 아래 저장소 세 곳에서만 만든다.
// 보유는 맨 아래 「보유」 칸이 보유 열쇠 재료로 잠근 덩어리(e2e.ts)로만 /portfolio 에 올린다. 스냅샷·원장은 어디로도 보내지 않는다.
//
// 규칙
//   키      화면에서 받은 동기화 키 원문은 저장하지 않는다. 연결할 때(원문이 손에 있을 때) 두 가지로 바꿔 둔다:
//           SHA-256 해시 → sessionStorage econSyncHash_v1(이 탭) + localStorage econSyncHashKeep_v1(기억 — 새 탭이 PIN 없이 잇는다, 결정 D10),
//           보유 열쇠 재료(e2e.ts holdKeyOf) → localStorage econHoldKey_v1. 기억 해시와 재료는 수명이 같다 —
//           「이 기기 잊기」 · 키가 틀려(401) 끊김 · 이 기기 데이터 지우기(store.ts WIPE_KEYS) · 다른 탭에서 지움(storage 이벤트) 때 함께 지운다.
//   연결    키 → 해시 · 재료 → GET /prefs. 서버에 저장본이 있고 이 기기에도 관심 · 조건 · 시나리오(또는 기본값에서 바꾼 설정)가 있는데 서로 다르면 한 번 묻는다
//           (st.ask — 「서버 것으로 맞추기 / 이 기기 것을 올리기」, answerAsk). 답하기 전엔 아무것도 저장하지 않는다. 한쪽이 비었거나 같으면 묻지 않는다.
//           서버에 못 닿으면 연결하지 않는다(나중에 말없이 덮지 않게 — 다시 「연결」).
//   범위    econSyncScope_v1 = { prefs, hold } (기본 둘 다 켬, 이 기기만). prefs 를 끄면 ① 을 주고받지 않는다(서버 사본은 그대로 —
//           알림은 서버가 마지막으로 본 조건으로 울린다). 다시 켜면 연결 때처럼 맞춘다. hold 를 끄면 보유 자동 맞춤을 멈춘다.
//   보내기  1초마다 이 기기 문서를 비교해, 바뀐 뒤 2초 조용하면 PUT(If-Match = 마지막으로 본 updatedAt).
//           요청 사이는 6초 이상 — Worker AI_LIMITER 가 /ai·/portfolio 와 같은 바구니로 IP 당 분당 10회다.
//           탭을 숨기거나 닫는 순간 못 보낸 것이 있으면 바로 보낸다.
//   409     다른 기기가 먼저 저장했다 → 서버 내용으로 이 기기를 덮고 알린다(방금 바꾼 것은 다시 해야 한다).
//   401     키가 틀렸거나 다른 기기가 키를 바꿨다 → 해시 · 재료를 지우고 끊는다(같은 브라우저의 다른 탭이 바꾼 것이면 새 해시로 잇는다).
//   받기    앱을 열 때와 탭으로 돌아올 때(1분에 한 번까지). 못 보낸 것이 있으면 받기 전에 먼저 보낸다.
//   알리기  서버 내용으로 덮은 뒤 키마다 storage 이벤트를 쏜다 — 다른 탭에서 바뀐 것과 같은 길로 화면이 다시 읽는다.
//   기기만  화면 모드 · 금액 단위 · 90일 자동 강등은 문서에 없다(remote.ts syncedOf) — 받을 때도 이 기기 값을 둔다(명세 S9).
// ponytail: 바뀜 감지는 1초 폴링(저장소 세 곳 읽기). 쓰는 곳(관심 별·알림·설정·렌즈·다른 탭)에 손대지 않으려고 고른 방식이다.
//   쓰는 곳이 늘어 폴링이 무거워지면 저장 함수마다 알림을 쏘는 방식으로 바꾼다.
import { useSyncExternalStore } from 'react'
import { mdHm } from '../format'
import { samePin } from '../pin'
import { pushSubscribed, pushSupported, subscribePush, unsubscribePush } from '../push'
import { applyUpdown, KEYS, newId, readPortfolio, readPrefs, writePortfolio, writePrefs } from './store'
import { blankLocal, defaultSet, fromServer, keyChangeText, keyHash, portfolioGet, portfolioPost, prefsCall, syncedOf, syncKeyChange, toServer, type Local, type PrefsDoc, type Reply } from './remote'
import { applyEntries, autoStep, decide, encrypt, entriesOf, fingerprint, holdKeyOf, openBlob, relockBlob, type EncBlob, type Entry, type Plan } from './e2e'
import type { Holding } from './calc'

const HASH_KEY = 'econSyncHash_v1'
const KEEP_KEY = 'econSyncHashKeep_v1'
const SCEN_KEY = 'econ_scenarios_v1'   // components/lens/WhatIf.tsx SAVE_KEY 와 같은 열쇠
const QUIET_MS = 2_000                 // 바뀐 뒤 이만큼 조용하면 보낸다
const GAP_MS = 6_000                   // 요청 사이 최소 간격(분당 10회 아래)
const RETRY_MS = 60_000                // 서버에 못 닿았을 때 다시 해 볼 때까지
const PULL_MS = 60_000                 // 탭으로 돌아올 때 다시 받는 최소 간격
const HEX64 = /^[0-9a-f]{64}$/

function readHex(s: () => Storage, k: string): string | null {
  try { const h = s().getItem(k); return h && HEX64.test(h) ? h : null } catch { return null }
}
/** 동기화 키 해시(64자 hex) — 없으면 null. 웹 푸시(/push/subscribe)도 이것으로 인증한다. */
export const getKeyHash = () => readHex(() => sessionStorage, HASH_KEY)
const keptHash = () => readHex(() => localStorage, KEEP_KEY)
const holdKey = () => readHex(() => localStorage, KEYS.holdKey)
/** 보유 열쇠 재료가 있나 — 이 판 전에 연결한 기기는 없다(키를 한 번 더 받아 restoreHoldKey). */
export const hasHoldKey = () => holdKey() != null

// ── 범위(이 기기만) ─────────────────────────────────────
export type Scope = { prefs: boolean; hold: boolean }
export function readScope(): Scope {
  const r = readJson(KEYS.scope) as Partial<Scope> | null
  return { prefs: r?.prefs !== false, hold: r?.hold !== false }
}
function writeScope(p: Partial<Scope>) {
  try { localStorage.setItem(KEYS.scope, JSON.stringify({ ...readScope(), ...p })) } catch { /* 못 남기면 이번 탭만 */ }
}

// ── 화면에 보이는 상태 ───────────────────────────────────
/** 연결 때 물을 것: 서버 저장본과 이 기기의 셈(settings = 설정을 기본값에서 바꿈) + 서버에 맡긴 때. */
export type Count = { watch: number; alerts: number; scenarios: number; settings: boolean }
export type Ask = { server: Count; local: Count; at: string | null }
/** linked = 이 탭에 키가 있음 · on = ① 을 주고받는 중(linked + 범위 ①) · hold = 보유 맞춤 한 줄(ask = 화면이 물어야 함) · pushAt = 연결이 폰 알림을 켠 때(화면이 구독 상태를 다시 읽는다). */
export type SyncStatus = { linked: boolean; on: boolean; busy: boolean; msg: string; at: number | null; rev: number; ask: Ask | null; hold: { text: string; ask: boolean }; pushAt: number }
let st: SyncStatus = { linked: getKeyHash() != null, on: getKeyHash() != null && readScope().prefs, busy: false, msg: '', at: null, rev: 0, ask: null, hold: { text: '', ask: false }, pushAt: 0 }
const subs = new Set<() => void>()
function set(p: Partial<SyncStatus>) { st = { ...st, ...p }; subs.forEach(f => f()) }
const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f) } }
/** rev 는 서버 내용으로 이 기기를 덮을 때마다 1씩 오른다 — 상태를 들고 있는 화면은 이때 다시 읽는다. */
export const useSyncStatus = () => useSyncExternalStore(subscribe, () => st)
/** 알림 화면의 범위 문구 — 두 벌(명세 S5). on = ① 을 주고받는 중, push = 이 기기 폰 알림 구독. */
export const scopeText = (on: boolean, push: boolean) => (on ? (push ? '연결됨 · 폰 알림 켜짐' : '연결됨') : '이 기기만 — 울리지 않음')

// ── 이 기기 저장소 세 곳 ─────────────────────────────────
function readJson(k: string): unknown { try { return JSON.parse(localStorage.getItem(k) || 'null') } catch { return null } }

function readLocal(): Local {
  const w = readJson(KEYS.watch), sc = readJson(SCEN_KEY), p = readPrefs()
  return {
    watch: Array.isArray(w) ? w.filter((x): x is string => typeof x === 'string') : [],
    alerts: p.alerts, settings: syncedOf(p.settings),
    scenarios: Array.isArray(sc) ? sc.filter(x => x && typeof x.name === 'string') : [],
  }
}

function writeLocal(l: Local) {
  const put = (k: string, v: unknown) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* 저장 못 하면 이번 화면만 그대로 */ } }
  put(KEYS.watch, l.watch)
  put(SCEN_KEY, l.scenarios)
  const cur = readPrefs()
  writePrefs({ ...cur, alerts: l.alerts, settings: { ...cur.settings, ...l.settings } })   // 금액 단위 · 자동 강등은 이 기기 값 그대로
  applyUpdown(l.settings.updown)
  for (const key of [KEYS.watch, KEYS.prefs, SCEN_KEY]) window.dispatchEvent(new StorageEvent('storage', { key }))
}

const fp = () => JSON.stringify(readLocal())
/** 키 순서와 무관한 비교용 글(서버가 조건 칸 순서를 바꿔 돌려준다). */
const canon = (v: unknown) => JSON.stringify(v, (_k, x) => (x && typeof x === 'object' && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : 1))) : x))
const countOf = (l: Local): Count => ({ watch: l.watch.length, alerts: l.alerts.filter(a => a.target !== '*').length, scenarios: l.scenarios.length, settings: !defaultSet(l.settings) })

// ── 서버와 주고받기 ─────────────────────────────────────
let prev: PrefsDoc | null = null   // 마지막으로 본 서버 문서(updatedAt · 관심 담은 때)
let sent = ''                      // 서버와 같다고 아는 이 기기 문서(지문)
let seen = '', changedAt = 0, lastReq = 0, lastPull = 0, retryAt = 0, busy = false, timer = 0
let pend: { h: string; mat: string | null; doc: PrefsDoc; fresh: boolean } | null = null   // 연결 때 물어 둔 것
let changing = false               // 키 바꾸는 중(changeKey) — 주고받기를 멈춘다
let permAsk: Promise<unknown> | null = null   // 연결 단추를 누른 순간 물어 둔 알림 허락(connectSync)

/** 마지막 요청 시각 — /ai 도 /prefs · /portfolio 와 분당 10회를 나눠 쓴다(GAP_MS). 홈 질문칸이 보내기 직전에 읽고 알린다. */
export const lastReqAt = () => lastReq
export const noteReq = () => { lastReq = Date.now() }

function errText(r: Reply): string {
  if (r.status === 0) return '서버에 닿지 못했습니다. 1분 뒤 다시 맞춥니다.'
  if (r.status === 429) return '요청이 많아 1분 뒤 다시 맞춥니다.'
  if (r.error === 'sync_key_not_configured') return '서버에 동기화 키가 설정되지 않았습니다.'
  if (r.error === 'forbidden_origin') return '이 주소에서 연 화면은 서버가 받지 않습니다.'
  if (r.error === 'tier2_field_rejected') return `보유정보로 보이는 칸(${r.field ?? '?'})이 있어 서버가 받지 않았습니다.`
  if (r.status === 413) return '맡길 내용이 너무 커서 서버가 받지 않았습니다. 관심·알림 조건을 줄여 주세요.'
  if (r.status === 400) return `서버가 받지 않았습니다(${r.error ?? r.status}).`
  return `서버가 받지 않았습니다(${r.error ?? r.status}). 1분 뒤 다시 맞춥니다.`
}
/** 같은 내용을 다시 보내도 또 거절되는 응답 — 이 기기 것이 다시 바뀔 때까지 기다린다. */
const refused = (r: Reply) => r.status === 400 || r.status === 413

const KEY_LOST = '동기화 키가 맞지 않아 연결을 끊었습니다. 키를 다시 넣어 주세요.'
/** 401: 같은 브라우저의 다른 탭이 키를 바꿨으면(기억 해시가 다르면) 그 해시로 잇고, 아니면 끊는다. */
function lost(h: string) {
  if (changing) return   // 키 바꾸는 중 — 옛 해시로 나간 요청의 401 은 바뀐 결과다
  const k = keptHash()
  if (k && k !== h) adopt(k)
  else disableSync(KEY_LOST)
}

/** 요청 한 번 + 공통 처리. 키가 없거나 401 이면(끊는다) null. 받지 못한 응답(409 제외)은 알림 글을 남긴다. */
async function call(put?: Parameters<typeof prefsCall>[1]): Promise<Reply | null> {
  const h = getKeyHash()
  if (!h) return null
  busy = true; set({ busy: true }); lastReq = Date.now()
  const r = await prefsCall(h, put)
  busy = false; set({ busy: false })
  if (r.status === 401) { lost(h); return null }
  if (!r.doc && r.status !== 409) set({ msg: errText(r) })
  return r
}

/** 서버 문서로 이 기기를 덮는다. 안내 글은 실제로 바뀐 것이 있을 때만(같은 브라우저의 다른 탭이 먼저 같은 내용을 올린 409 는 조용히). */
function apply(doc: PrefsDoc, msg = '') {
  const was = fp()
  prev = doc
  writeLocal(fromServer(doc))
  sent = seen = fp()
  set({ msg: sent === was ? '' : msg, at: Date.now(), rev: st.rev + 1 })
}

/** 서버 내용을 받아 이 기기를 맞춘다. 서버가 비었으면(updatedAt 없음) 이 기기 것을 올린다. */
export async function pullPrefs(): Promise<boolean> {
  if (busy) return false
  lastPull = Date.now()
  const r = await call()
  if (!r) return false
  if (!r.doc) { retryAt = Date.now() + RETRY_MS; return false }
  if (!r.doc.updatedAt) { prev = r.doc; return pushPrefs() }
  apply(r.doc)
  return true
}

/** 이 기기 문서를 올린다(전체 교체). 409 면 서버 내용을 받아 덮고 알린다. */
export async function pushPrefs(keepalive = false): Promise<boolean> {
  if (busy && !keepalive) return false
  const local = readLocal(), f = JSON.stringify(local)
  const r = await call({ body: toServer(local, prev, new Date().toISOString()), ifMatch: prev?.updatedAt ?? null, keepalive })
  if (!r) return false
  if (r.status === 409) {
    const g = await call()
    if (g?.doc) apply(g.doc, '다른 기기가 먼저 저장해서 이 기기를 서버 내용으로 맞췄습니다. 방금 바꾼 것이 빠졌다면 다시 해 주세요.')
    else if (g) retryAt = Date.now() + RETRY_MS
    return false
  }
  if (!r.doc) {
    if (refused(r)) sent = f
    else retryAt = Date.now() + RETRY_MS
    return false
  }
  prev = r.doc
  sent = f
  set({ msg: '', at: Date.now() })
  return true
}

async function tick() {
  if (!getKeyHash()) { stop(); if (st.linked) set({ linked: false, on: false }); return }
  const now = Date.now()
  if (!st.on || pend || changing || busy || now < retryAt) return
  if (!prev) { await pullPrefs(); return }   // 서버 문서를 이 탭에서 아직 못 봤으면 받는 것부터
  const f = fp()
  if (f !== seen) { seen = f; changedAt = now; return }
  if (f !== sent && now - changedAt >= QUIET_MS && now - lastReq >= GAP_MS) await pushPrefs()
}

function begin() { if (!timer) timer = window.setInterval(() => void tick(), 1000); set({ linked: true, on: readScope().prefs }) }
function stop() { if (timer) clearInterval(timer); timer = 0 }

/** 같은 브라우저의 다른 탭이 연결하거나 키를 바꾼 해시로 이 탭도 잇는다. */
function adopt(h: string) {
  try { sessionStorage.setItem(HASH_KEY, h) } catch { disableSync(KEY_LOST); return }
  prev = null; sent = ''; retryAt = 0; pend = null
  set({ msg: '', ask: null })
  begin()
}

function onVisibility() {
  if (!getKeyHash() || !st.on || pend || !prev) return
  const unsent = fp() !== sent
  if (document.visibilityState === 'hidden') { if (unsent) void pushPrefs(true); return }
  if (busy || Date.now() < retryAt) return
  if (unsent) void pushPrefs()
  else if (Date.now() - lastPull > PULL_MS) void pullPrefs()
}

/**
 * 다른 탭의 일을 따라간다.
 *   기억 해시가 새 값으로 바뀜 → 그 탭이 연결했거나 키를 바꿨다 → 이 탭도 그 해시로 잇는다(옛 해시로 401 을 받아 새 기억까지 지우지 않게).
 *   기억 해시 · 설정 문서가 지워짐 → 「이 기기 잊기」나 「이 기기 데이터 지우기」 → 이 탭도 끊는다 — 그대로 두면 이 탭이 비워진 저장소를
 *   기본값 문서로 읽어 서버에 올리고, 서버의 알림 조건이 사라진다.
 *   범위가 바뀜 → ① 주고받기를 따라 켜고 끈다.
 * 같은 탭 안에서 이 앱이 쏘는 storage 이벤트(writeLocal · tidyAlerts · 알림 시트)는 storageArea 가 없어 걸리지 않는다.
 */
function onStorage(e: StorageEvent) {
  if (e.storageArea !== localStorage) return
  if (e.key === KEEP_KEY && e.newValue && HEX64.test(e.newValue)) { if (e.newValue !== getKeyHash()) adopt(e.newValue); return }
  if (e.key === KEYS.scope) { if (st.linked) set({ on: readScope().prefs }); return }
  if (e.newValue !== null || (e.key !== KEEP_KEY && e.key !== KEYS.prefs)) return
  if (getKeyHash()) disableSync('다른 탭에서 이 기기를 잊거나 데이터를 지워 이 탭도 끊었습니다.')
}

/** 앱이 뜰 때 한 번(main.tsx). 이 탭에 키 해시가 없으면 기억한 해시를 옮겨 오고(PIN 없이), 있으면 서버 내용을 받고 감시를 시작한다. */
export function startSync() {
  // 옛 화면이 예전에 localStorage 에 남긴 비밀(동기화 키 해시 · 보유 암호 원문)은 새 화면이 쓰지 않는다 — 열자마자 지운다(B3).
  for (const k of ['pfSyncKeyHash', 'pfHoldingsPass']) { try { localStorage.removeItem(k) } catch { /* 막힌 저장소 */ } }
  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener('storage', onStorage)
  const kept = keptHash()
  if (!getKeyHash() && kept) { try { sessionStorage.setItem(HASH_KEY, kept) } catch { /* 막힌 저장소 = 잇지 않음 */ } }
  if (getKeyHash()) begin()
}

// ── 연결 · 범위 · 잊기 · 키 바꾸기(설정 「기기 연결」 — PIN 뒤) ─────────────
function fail(msg: string) { set({ busy: false, msg }); return false }

/**
 * 연결: 키 원문은 여기서 해시 · 재료로만 바꾸고 어디에도 남기지 않는다. 물어야 하면 st.ask 를 세우고 answerAsk 를 기다린다.
 * perm = 연결 단추를 누른 그 순간에 물은 알림 허락(아이폰 · 사파리는 사용자 동작 안에서만 묻는다) — 범위 ③ 은 기본 켬이라 이어지면 이 기기를 구독한다.
 */
export async function connectSync(key: string, perm?: Promise<unknown>): Promise<boolean> {
  permAsk = perm ?? null
  if (!key.trim()) return fail('동기화 키를 넣어 주세요.')
  set({ busy: true, msg: '' })
  let h: string, mat: string
  try { [h, mat] = await Promise.all([keyHash(key), holdKeyOf(key)]) } catch { return fail('이 환경(https 아님)에서는 연결할 수 없습니다.') }
  return matchPrefs(h, mat, readScope().prefs, true)
}

/** 서버 문서를 받아 묻거나 바로 잇는다. fresh = 새로 연결(재료를 새로 두고 보유도 맞춘다) · 아니면 ① 을 다시 켜는 중. */
async function matchPrefs(h: string, mat: string | null, prefsOn: boolean, fresh: boolean): Promise<boolean> {
  set({ busy: true, msg: '' })
  const r = await prefsCall(h)
  if (r.status === 401) { if (fresh) return fail('동기화 키가 맞지 않습니다.'); set({ busy: false }); lost(h); return false }
  if (!r.doc) return fail(r.status === 0 ? '서버에 닿지 못했습니다. 잠시 뒤 다시 하세요.' : r.status === 429 ? '요청이 많습니다. 1분 뒤 다시 하세요.' : errText(r))
  set({ busy: false })
  const local = readLocal(), server = fromServer(r.doc)
  if (prefsOn && r.doc.updatedAt && !blankLocal(local) && canon(toServer(local, null, '')) !== canon(toServer(server, null, ''))) {
    pend = { h, mat, doc: r.doc, fresh }
    set({ ask: { server: countOf(server), local: countOf(local), at: r.doc.updatedAt } })
    return true
  }
  return link(h, mat, r.doc, r.doc.updatedAt ? 'server' : 'local', prefsOn, fresh)
}

async function link(h: string, mat: string | null, doc: PrefsDoc, side: 'server' | 'local', prefsOn: boolean, fresh: boolean): Promise<boolean> {
  try { sessionStorage.setItem(HASH_KEY, h) } catch { return fail('이 탭에 키를 기억할 수 없어 연결할 수 없습니다.') }
  try { localStorage.setItem(KEEP_KEY, h); if (mat) localStorage.setItem(KEYS.holdKey, mat) } catch { /* 기억 못 하면 이 탭에서만 잇는다 */ }
  writeScope({ prefs: prefsOn })
  pend = null; prev = doc; sent = ''; retryAt = 0
  set({ ask: null, msg: '' })
  begin()
  if (prefsOn) { if (side === 'server') apply(doc); else await pushPrefs() }
  if (fresh) { void syncHoldings(); void autoPush() }
  return true
}

/** 새로 연결하면 폰 알림도 켠다(범위 ③ 기본 켬). 허락을 못 받았으면 그대로 둔다 — 「기기 연결」의 스위치로 켠다. */
async function autoPush() {
  const p = permAsk
  permAsk = null
  if (!pushSupported() || ((await p) ?? Notification.permission) !== 'granted') return
  await subscribePush(getKeyHash).catch(() => {})
  set({ pushAt: Date.now() })
}

/** 연결 때 물은 것에 답한다. null = 그만두기(아무것도 저장하지 않는다 — ① 을 다시 켜던 중이었으면 꺼진 채로 둔다). */
export async function answerAsk(side: 'server' | 'local' | null): Promise<boolean> {
  const p = pend
  if (!p) return false
  if (!side) { pend = null; set({ ask: null }); return false }
  return link(p.h, p.mat, p.doc, side, true, p.fresh)
}

/** 범위 켜고 끄기. ① 을 켜면 연결 때처럼 서버 것과 맞추고(다르면 묻는다), ② 를 켜면 보유를 맞춘다. */
export async function setScope(p: Partial<Scope>): Promise<void> {
  if (p.hold !== undefined) { writeScope({ hold: p.hold }); if (p.hold) void syncHoldings(); else set({ hold: { text: '', ask: false } }) }
  if (p.prefs === false) { writeScope({ prefs: false }); set({ on: false, ask: null }); pend = null }
  const h = getKeyHash()
  if (p.prefs && h) await matchPrefs(h, null, true, false)
}

/** 「이 기기 잊기」: 이 기기 폰 알림 구독을 끊고(해시가 필요하니 먼저) 해시 · 기억 · 보유 열쇠 재료를 지운다. 이 기기 자료와 서버에 맡긴 것은 그대로. */
export async function forgetDevice() {
  await unsubscribePush(getKeyHash).catch(() => {})
  disableSync()
}

/** 끊기: 이 탭의 키 해시 · 기억 해시 · 보유 열쇠 재료를 지운다. 이 기기 자료와 서버에 맡긴 것은 그대로 둔다. */
export function disableSync(msg = '') {
  try { sessionStorage.removeItem(HASH_KEY) } catch { /* 막힌 저장소 = 원래 없음 */ }
  for (const k of [KEEP_KEY, KEYS.holdKey]) { try { localStorage.removeItem(k) } catch { /* 같음 */ } }
  stop()
  prev = null; sent = ''; retryAt = 0; pend = null
  set({ linked: false, on: false, busy: false, msg, ask: null, hold: { text: '', ask: false } })
}

/**
 * 키 바꾸기(명세 B5). '' = 바뀜. 새 키는 12자 이상 · 지금 키와 다름 · 잠금 PIN 과 다름(앞의 둘은 서버도 다시 본다).
 * 지금 키는 이 탭 해시와 먼저 견준다(틀린 키로 서버를 두드리지 않게). 서버 보유를 확인하지 못하면 바꾸지 않는다.
 * 바뀌면 이 탭 해시 · 기억 해시 · 보유 열쇠 재료를 새 키로 바꾸고, 서버 보유 사본을 새 재료로 다시 잠가 올리고, 이 기기 폰 알림 구독을 새 키 공간으로 옮긴다.
 * /prefs 는 서버가 옛 공간 문서를 새 공간으로 옮겨 두므로 다음 맞춤이 그것을 받는다(옮기지 못해 비어 있으면 이 기기 것을 올린다).
 * 다른 기기는 새 키로 다시 연결해야 한다(옛 해시는 401).
 */
export async function changeKey(cur: string, next: string): Promise<string> {
  const h = getKeyHash()
  if (!h) return '먼저 연결하세요.'
  const n = next.trim()
  if (n.length < 12) return '새 키는 12자 이상이어야 합니다.'
  if (n === cur.trim()) return '지금 키와 다른 키를 쓰세요.'
  set({ busy: true, msg: '' })
  changing = true
  try {
    // PIN 과 같은지는 samePin 으로 견준다 — checkPin 이면 실패로 세어 잠금 대기가 걸린다. 옛 화면 PIN 은 아무 글자일 수 있다.
    for (const p of new Set([next, n])) if (await samePin(p)) return '잠금 PIN 과 다른 키를 쓰세요.'
    if ((await keyHash(cur)) !== h) return keyChangeText({ status: 401 })
    // 옛 재료는 지금 키 원문에서 만든다 — 재료를 기억하지 않은 기기(이 판 전에 연결)도 서버 사본을 옮긴다.
    const [nh, mat, old] = await Promise.all([keyHash(n), holdKeyOf(n), holdKeyOf(cur)])
    // 보유: 서버 사본을 옛 재료로 풀어 새 재료로 미리 잠가 둔다. 올리기는 키가 바뀐 뒤(새 해시로).
    const relock = await relockBlob(await portfolioGet(h), old, mat)
    if (relock === false) return '서버 보유를 확인하지 못해 키를 바꾸지 않았습니다 — 잠시 뒤 다시 하세요.'
    const r = await syncKeyChange(cur, next)
    if (r.status !== 200) return keyChangeText(r)
    try { sessionStorage.setItem(HASH_KEY, nh); localStorage.setItem(KEEP_KEY, nh); localStorage.setItem(KEYS.holdKey, mat) } catch { /* 막힌 저장소 — 다음 연결 때 다시 */ }
    prev = null; sent = ''; retryAt = 0   // 다음 맞춤이 새 키 공간을 받는다(서버가 옮겨 둔 문서 — 비어 있으면 이 기기 것을 올린다)
    if (relock) {
      const p = await portfolioPost(nh, relock)
      if (p.ok) noteHold({ upAt: new Date().toISOString(), server: true })
      else set({ hold: { text: '보유 사본을 새 키로 다시 잠그지 못했습니다 — 내 자산 「동기화」에서 예전 키를 한 번 넣으면 옮깁니다.', ask: true } })
    }
    if (await pushSubscribed().catch(() => false)) await subscribePush(getKeyHash).catch(() => {})
    return ''
  } finally { changing = false; set({ busy: false }) }
}

// ── 보유(평단가·수량·매입 환율) — 보유 열쇠 재료로 잠근 덩어리만 /portfolio 로 ─────────
// 형식은 e2e.ts(현행 화면과 같다). 보유를 읽는 함수는 PinGate 안의 화면(내 자산 · 설정)만 부른다.
// 자동(syncHoldings): 범위 ② 가 켜져 있으면 연결할 때 · 내 자산을 열 때 · 보유 저장 2초 뒤 — 한쪽만 바뀌었으면 묻지 않고 올리거나 받는다.
// 둘 다 바뀌었거나 예전 암호 사본이면 st.hold 에 적고, 내 자산 「동기화」 시트(HoldSyncSheet)가 비교 결과를 보여 주고 묻는다.
// econHoldSync_v1 = { base: 마지막으로 맞췄을 때의 보유 지문, upAt: 마지막 올림, downAt: 마지막 받음, server: 서버에 있음, checkedAt } — 보유 값은 없다.
export type HoldRec = { base?: string; upAt?: string; downAt?: string; server?: boolean; checkedAt?: string }
export function readHoldRec(): HoldRec {
  const r = readJson(KEYS.holdSync)
  return r && typeof r === 'object' ? (r as HoldRec) : {}
}
function noteHold(p: HoldRec) {
  try { localStorage.setItem(KEYS.holdSync, JSON.stringify({ ...readHoldRec(), ...p })) } catch { /* 못 남기면 다음 확인이 둘 중 고르라고 묻는다 */ }
}

/** 확인 결과. migrate = 예전 보유 암호 사본 · broken = 열쇠로는 풀리는데 모양이 깨진 사본(둘 다 그 덩어리 — 「서버 사본 버리고 올리기」가 seen 으로 쓴다) · needKey = 보유 열쇠 재료 없음. */
export type HoldCheck =
  | { ok: false; msg: string; migrate?: EncBlob; broken?: EncBlob; needKey?: boolean }
  | { ok: true; plan: Plan; enc: EncBlob | null; server: Entry[]; serverAt: string | null; localN: number; stale: boolean }
export type HoldDone = { ok: boolean; msg: string }

const NO_SYNC = '설정 › 기기 연결에서 동기화 키를 먼저 넣으세요.'
const NO_HOLD_KEY = '보유 열쇠가 없습니다. 설정 › 기기 연결에서 동기화 키를 한 번 다시 넣어 주세요.'
const MIGRATE = '예전 보유 암호(또는 바꾸기 전 동기화 키)로 잠긴 서버 사본이 있습니다 — 한 번 넣으면 새 열쇠로 다시 잠가 올립니다.'
function holdErr(r: { status: number; error?: string }, h: string): string {
  if (r.status === 401) { lost(h); return KEY_LOST }
  if (r.status === 0) return '서버에 닿지 못했습니다.'
  if (r.status === 429) return '요청이 많습니다. 1분 뒤 다시 해 주세요.'
  if (r.status === 413) return '보낼 내용이 너무 커서 서버가 받지 않았습니다.'
  return `서버가 받지 않았습니다(${r.error ?? r.status}).`
}

/** 확인: 서버 덩어리를 받아 풀고, 이 기기와 비교해 어느 쪽을 쓸지 고른다. 아무것도 덮지 않는다. old = 이전 때 받은 예전 보유 암호. */
export async function checkHoldings(old?: string): Promise<HoldCheck> {
  const h = getKeyHash()
  if (!h) return { ok: false, msg: NO_SYNC }
  const mat = holdKey()
  if (!mat) return { ok: false, msg: NO_HOLD_KEY, needKey: true }
  const g = await portfolioGet(h)
  if (!g.ok) return { ok: false, msg: holdErr(g, h) }
  noteHold({ server: !!g.enc, checkedAt: new Date().toISOString() })
  const local = entriesOf(readPortfolio().items)
  const lf = { fp: await fingerprint(local), n: local.length }
  const base = readHoldRec().base ?? null
  if (!g.enc) return { ok: true, plan: decide(lf, null, base), enc: null, server: [], serverAt: null, localN: lf.n, stale: false }
  let d: Awaited<ReturnType<typeof openBlob>>
  try { d = await openBlob(g.enc, mat, old) } catch (e) {
    const m = (e as Error).message
    if (m === 'old-pass') return { ok: false, msg: MIGRATE, migrate: g.enc }
    if (m === 'wrong-pass') return { ok: false, msg: '예전 보유 암호(또는 바꾸기 전 동기화 키)가 다릅니다.', migrate: g.enc }
    return { ok: false, msg: '서버 보유 사본이 깨져 읽지 못했습니다 — 이 기기 것을 올려 덮을 수 있습니다.', broken: g.enc }
  }
  const plan = decide(lf, { fp: await fingerprint(d.entries), n: d.entries.length }, base)
  if (plan === 'same' && !d.stale) noteHold({ base: lf.fp })
  return { ok: true, plan, enc: g.enc, server: d.entries, serverAt: d.at, localN: lf.n, stale: d.stale }
}

/** 올리기: 확인 때 본 서버 덩어리(seen)가 그사이 바뀌지 않았을 때만 이 기기 보유를 보유 열쇠 재료로 잠가 올린다. */
export async function pushHoldings(seen: EncBlob | null): Promise<HoldDone> {
  const h = getKeyHash()
  if (!h) return { ok: false, msg: NO_SYNC }
  const mat = holdKey()
  if (!mat) return { ok: false, msg: NO_HOLD_KEY }
  const local = entriesOf(readPortfolio().items)
  const at = new Date().toISOString()
  // 잠그기(PBKDF2 600k, 폰에서 1~3초)는 GET 앞에서 한다 — GET 과 POST 사이를 요청 한 번 길이로 줄인다.
  const enc = await encrypt(local, mat, at)
  if (enc.ciphertext.length > 60_000) return { ok: false, msg: '보유 종목이 너무 많아 올릴 수 없습니다.' }   // Worker _sanitizeEncHoldings 한도
  const g = await portfolioGet(h)
  if (!g.ok) return { ok: false, msg: holdErr(g, h) }
  if ((g.enc?.ciphertext ?? null) !== (seen?.ciphertext ?? null)) return { ok: false, msg: '그사이 서버 보유가 바뀌었습니다. 다시 확인해 주세요.' }
  const r = await portfolioPost(h, enc)
  if (!r.ok) return { ok: false, msg: holdErr(r, h) }
  noteHold({ base: await fingerprint(local), upAt: at, server: true, checkedAt: at })
  setHold('', false)   // 물어 둔 것이 풀렸다(자동 맞춤은 이 뒤에 제 글을 적는다)
  return { ok: true, msg: `올렸습니다 · ${local.length}종목 · ${mdHm(at)}` }
}

/** 받기: 확인 때 풀어 본 서버 칸으로 이 기기 보유를 바꾼다. 예전 암호 사본이었으면(stale) 받은 것을 새 열쇠로 다시 잠가 올린다. */
export async function pullHoldings(c: { server: Entry[]; stale: boolean; enc: EncBlob | null }): Promise<HoldDone> {
  const p = readPortfolio()
  const group = p.groups[0].id
  const items = applyEntries(p.items, c.server, (e): Holding => ({
    id: newId('i'), symbol: e.s, market: e.m, yahoo: e.m === 'US' ? e.s : null, name: e.s, secType: 'stock',
    ccy: e.m === 'US' ? 'USD' : 'KRW', avg: e.a, qty: e.q, fxBuy: e.fx, group,
  }))
  if (!writePortfolio({ ...p, items })) return { ok: false, msg: '이 기기에 저장하지 못했습니다. 시크릿 창이거나 저장 공간이 찼습니다.' }
  const at = new Date().toISOString()
  noteHold({ base: await fingerprint(c.server), downAt: at })
  const done = `받았습니다 · ${c.server.length}종목 · ${mdHm(at)}`
  if (!c.stale) { setHold('', false); return { ok: true, msg: done } }
  const r = await pushHoldings(c.enc)
  return r.ok ? { ok: true, msg: `${done} · 새 열쇠로 다시 잠가 올렸습니다` } : { ok: false, msg: `${done}. 새 열쇠로 다시 잠가 올리지는 못했습니다 — ${r.msg}` }
}

let holdBusy = false, holdAgain = false, holdTimer = 0
const setHold = (text: string, ask: boolean) => set({ hold: { text, ask } })

/**
 * 묻지 않고 하는 보유 맞춤(범위 ② 가 켜져 있을 때). 한쪽만 바뀌었으면 올리거나 받고(e2e.ts autoStep),
 * 둘 다 바뀌었거나 · 빈 기기로 서버 사본을 지우게 되거나 · 예전 암호 사본이면 st.hold 에 적어 두고 화면이 묻게 한다. 받았으면 true.
 */
export async function syncHoldings(): Promise<boolean> {
  if (!getKeyHash() || !readScope().hold) return false
  if (holdBusy) { holdAgain = true; return false }
  holdBusy = true
  try {
    const c = await checkHoldings()
    if (!c.ok) { setHold(c.msg, true); return false }
    const step = autoStep(c.plan, c.localN, c.server.length)
    if (step === 'ask') {
      setHold(c.plan === 'conflict' ? '이 기기와 서버 보유가 둘 다 바뀌었습니다 — 「동기화」에서 남길 쪽을 고르세요.' : '이 기기에 보유가 없어 서버 사본을 지우지 않고 멈췄습니다 — 「동기화」에서 고르세요.', true)
      return false
    }
    if (step === 'pull') { const r = await pullHoldings(c); setHold(r.msg, !r.ok); return r.ok }
    if (step === 'push') { const r = await pushHoldings(c.enc); setHold(r.ok ? `자동으로 ${r.msg}` : r.msg, !r.ok); return false }
    setHold('', false)
    return false
  } finally {
    holdBusy = false
    if (holdAgain) { holdAgain = false; void syncHoldings() }
  }
}

/** 보유 저장(내 자산) 뒤 2초 조용하면 syncHoldings. 받았으면 onPulled. */
export function queueHoldSync(onPulled: () => void) {
  clearTimeout(holdTimer)
  holdTimer = window.setTimeout(() => { void syncHoldings().then(p => { if (p) onPulled() }) }, QUIET_MS)
}

/** 보유 열쇠 재료가 없는 연결(이 판 전에 연결한 기기)에서 키를 한 번 더 받아 재료만 만든다. '' = 됐다. */
export async function restoreHoldKey(key: string): Promise<string> {
  const h = getKeyHash()
  if (!h) return NO_SYNC
  set({ busy: true })
  try {
    if ((await keyHash(key)) !== h) return '지금 연결한 키와 다릅니다.'
    try { localStorage.setItem(KEYS.holdKey, await holdKeyOf(key)) } catch { return '이 기기에 저장하지 못했습니다.' }
  } finally { set({ busy: false }) }
  void syncHoldings()
  return ''
}
