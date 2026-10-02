// 기기 간 동기화 — 관심 · 알림 조건 · 표시 설정 · 렌즈 시나리오를 Worker /prefs 에 맡긴다(기획안 v4 보안 위험 3).
// /prefs 문서에 보유(portfolioV1)·스냅샷·원장은 없다. 보내는 문서는 remote.ts toServer 가 아래 저장소 네 곳에서만 만든다.
// 보유는 맨 아래 「보유」 칸이 내 암호로 잠근 덩어리(e2e.ts)로만 /portfolio 에 올린다. 스냅샷·원장은 어디로도 보내지 않는다.
//
// 규칙
//   키      화면에서 받은 동기화 키는 저장하지 않는다. SHA-256 해시만 sessionStorage econSyncHash_v1 — 탭을 닫으면 사라진다.
//           (기기에 오래 두는 것은 D1 계정·지문/얼굴 단계로 미룬다.)
//   켜기    키 → 해시 → GET. 서버에 저장본이 있으면 그 내용으로 이 기기를 맞추고, 없으면 이 기기 것을 올린다.
//   보내기  1초마다 이 기기 문서를 비교해, 바뀐 뒤 2초 조용하면 PUT(If-Match = 마지막으로 본 updatedAt).
//           요청 사이는 6초 이상 — Worker AI_LIMITER 가 /ai·/portfolio 와 같은 바구니로 IP 당 분당 10회다.
//           탭을 숨기거나 닫는 순간 못 보낸 것이 있으면 바로 보낸다.
//   409     다른 기기가 먼저 저장했다 → 서버 내용으로 이 기기를 덮고 알린다(방금 바꾼 것은 다시 해야 한다).
//   401     키가 틀렸거나 바뀌었다 → 해시를 지우고 끈다.
//   받기    앱을 열 때와 탭으로 돌아올 때(1분에 한 번까지). 못 보낸 것이 있으면 받기 전에 먼저 보낸다.
//   알리기  서버 내용으로 덮은 뒤 키마다 storage 이벤트를 쏜다 — 다른 탭에서 바뀐 것과 같은 길로 화면이 다시 읽는다.
// ponytail: 바뀜 감지는 1초 폴링(저장소 네 곳 읽기). 쓰는 곳(관심 별·알림·설정·렌즈·다른 탭)에 손대지 않으려고 고른 방식이다.
//   쓰는 곳이 늘어 폴링이 무거워지면 저장 함수마다 알림을 쏘는 방식으로 바꾼다.
import { useSyncExternalStore } from 'react'
import { mdHm } from '../format'
import { applyTheme, readTheme } from '../theme'
import { checkPin, hasPin } from '../pin'
import { applyUpdown, KEYS, newId, readPortfolio, readPrefs, writePortfolio, writePrefs } from './store'
import { fromServer, keyHash, portfolioGet, portfolioPost, prefsCall, toServer, type Local, type PrefsDoc, type Reply } from './remote'
import { applyEntries, decide, decryptAs, encrypt, entriesOf, fingerprint, passProblem, type EncBlob, type Entry, type Plan } from './e2e'
import type { Holding } from './calc'

const HASH_KEY = 'econSyncHash_v1'
const SCEN_KEY = 'econ_scenarios_v1'   // components/lens/WhatIf.tsx SAVE_KEY 와 같은 열쇠
const QUIET_MS = 2_000                 // 바뀐 뒤 이만큼 조용하면 보낸다
const GAP_MS = 6_000                   // 요청 사이 최소 간격(분당 10회 아래)
const RETRY_MS = 60_000                // 서버에 못 닿았을 때 다시 해 볼 때까지
const PULL_MS = 60_000                 // 탭으로 돌아올 때 다시 받는 최소 간격

/** 동기화 키 해시(64자 hex) — 없으면 null. 웹 푸시(/push/subscribe)도 이것으로 인증한다. */
export function getKeyHash(): string | null {
  try { const h = sessionStorage.getItem(HASH_KEY); return h && /^[0-9a-f]{64}$/.test(h) ? h : null } catch { return null }
}

// ── 화면에 보이는 상태 ───────────────────────────────────
export type SyncStatus = { on: boolean; busy: boolean; msg: string; at: number | null; rev: number }
let st: SyncStatus = { on: getKeyHash() != null, busy: false, msg: '', at: null, rev: 0 }
const subs = new Set<() => void>()
function set(p: Partial<SyncStatus>) { st = { ...st, ...p }; subs.forEach(f => f()) }
const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f) } }
/** rev 는 서버 내용으로 이 기기를 덮을 때마다 1씩 오른다 — 상태를 들고 있는 화면은 이때 다시 읽는다. */
export const useSyncStatus = () => useSyncExternalStore(subscribe, () => st)
/** 상태 한 줄(설정 화면). */
export const statusText = (s: SyncStatus) => s.msg || (s.busy ? '맞추는 중' : s.at ? `켜짐 · 마지막으로 맞춘 때 ${mdHm(s.at)}` : '켜짐')

// ── 이 기기 저장소 네 곳 ─────────────────────────────────
function readJson(k: string): unknown { try { return JSON.parse(localStorage.getItem(k) || 'null') } catch { return null } }

function readLocal(): Local {
  const w = readJson(KEYS.watch), sc = readJson(SCEN_KEY), p = readPrefs()
  return {
    watch: Array.isArray(w) ? w.filter((x): x is string => typeof x === 'string') : [],
    alerts: p.alerts, settings: p.settings, theme: readTheme(),
    scenarios: Array.isArray(sc) ? sc.filter(x => x && typeof x.name === 'string') : [],
  }
}

function writeLocal(l: Local) {
  const put = (k: string, v: unknown) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* 저장 못 하면 이번 화면만 그대로 */ } }
  put(KEYS.watch, l.watch)
  put(SCEN_KEY, l.scenarios)
  writePrefs({ ...readPrefs(), alerts: l.alerts, settings: l.settings })
  applyTheme(l.theme)
  applyUpdown(l.settings.updown)
  for (const key of [KEYS.watch, KEYS.prefs, KEYS.theme, SCEN_KEY]) window.dispatchEvent(new StorageEvent('storage', { key }))
}

const fp = () => JSON.stringify(readLocal())

// ── 서버와 주고받기 ─────────────────────────────────────
let prev: PrefsDoc | null = null   // 마지막으로 본 서버 문서(updatedAt · 관심 담은 때)
let sent = ''                      // 서버와 같다고 아는 이 기기 문서(지문)
let seen = '', changedAt = 0, lastReq = 0, lastPull = 0, retryAt = 0, busy = false, timer = 0

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

/** 요청 한 번 + 공통 처리. 키가 없거나 401 이면(끈다) null. 받지 못한 응답(409 제외)은 알림 글을 남긴다. */
async function call(put?: Parameters<typeof prefsCall>[1]): Promise<Reply | null> {
  const h = getKeyHash()
  if (!h) return null
  busy = true; set({ busy: true }); lastReq = Date.now()
  const r = await prefsCall(h, put)
  busy = false; set({ busy: false })
  if (r.status === 401) { disableSync('동기화 키가 맞지 않아 껐습니다. 키를 다시 넣어 주세요.'); return null }
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
  if (!getKeyHash()) { stop(); if (st.on) set({ on: false }); return }
  const now = Date.now()
  if (busy || now < retryAt) return
  if (!prev) { await pullPrefs(); return }   // 서버 문서를 이 탭에서 아직 못 봤으면 받는 것부터
  const f = fp()
  if (f !== seen) { seen = f; changedAt = now; return }
  if (f !== sent && now - changedAt >= QUIET_MS && now - lastReq >= GAP_MS) await pushPrefs()
}

function begin() { if (!timer) timer = window.setInterval(() => void tick(), 1000); set({ on: true }) }
function stop() { if (timer) clearInterval(timer); timer = 0 }

function onVisibility() {
  if (!getKeyHash() || !prev) return
  const unsent = fp() !== sent
  if (document.visibilityState === 'hidden') { if (unsent) void pushPrefs(true); return }
  if (busy || Date.now() < retryAt) return
  if (unsent) void pushPrefs()
  else if (Date.now() - lastPull > PULL_MS) void pullPrefs()
}

/** 앱이 뜰 때 한 번(main.tsx). 이 탭에 키 해시가 있으면 서버 내용을 받고 감시를 시작한다. */
export function startSync() {
  document.addEventListener('visibilitychange', onVisibility)
  if (getKeyHash()) begin()
}

/** 설정의 「기기 간 동기화」를 켤 때: 키를 해시로만 이 탭에 기억하고 서버 내용을 받는다. 입력값은 어디에도 남기지 않는다. */
export async function enableSync(key: string): Promise<boolean> {
  if (!key.trim()) { set({ msg: '동기화 키를 넣어 주세요.' }); return false }
  let h: string
  try { h = await keyHash(key) } catch { set({ msg: '이 환경(https 아님)에서는 동기화를 쓸 수 없습니다.' }); return false }
  try { sessionStorage.setItem(HASH_KEY, h) } catch { set({ msg: '이 탭에 키를 기억할 수 없어 동기화를 켤 수 없습니다.' }); return false }
  prev = null; sent = ''; retryAt = 0
  set({ on: true, msg: '' })
  const ok = await pullPrefs()
  if (getKeyHash()) begin()
  return ok
}

/** 끄기: 이 탭의 키 해시를 지운다. 이 기기 자료와 서버에 맡긴 것은 그대로 둔다. */
export function disableSync(msg = '') {
  try { sessionStorage.removeItem(HASH_KEY) } catch { /* 막힌 저장소 = 원래 없음 */ }
  stop()
  prev = null; sent = ''; retryAt = 0
  set({ on: false, busy: false, msg })
}

// ── 보유(평단가·수량·매입 환율) — 내 암호로 잠근 덩어리만 /portfolio 로 ─────────
// 형식은 e2e.ts(현행 화면과 같다). 보유를 읽는 checkHoldings·pushHoldings·pullHoldings 는 내 자산(PinGate 안)의 「동기화」만 부른다.
// 설정 화면은 probeHoldings(서버에 있는지만, 풀지 않음)만 부른다.
// 보유 암호는 저장하지 않는다 — 부를 때마다 인자로 받고, 어디에도(콘솔 포함) 남기지 않는다.
// checkHoldings 는 실제로 풀린 암호 문자열을 HoldCheck.pass 로 돌려준다. 화면은 그것을 들고 있다가 올릴 때 그대로 넘긴다.
// 자동으로 덮지 않는다: checkHoldings 가 어느 쪽을 쓸지 고르면 화면이 한 번 묻고, 답을 들은 뒤에 pushHoldings · pullHoldings.
// econHoldSync_v1 = { base: 마지막으로 맞췄을 때의 보유 지문, upAt: 마지막 올림, downAt: 마지막 받음, server: 서버에 있음, checkedAt } — 보유 값은 없다.
export type HoldRec = { base?: string; upAt?: string; downAt?: string; server?: boolean; checkedAt?: string }
export function readHoldRec(): HoldRec {
  const r = readJson(KEYS.holdSync)
  return r && typeof r === 'object' ? (r as HoldRec) : {}
}
function noteHold(p: HoldRec) {
  try { localStorage.setItem(KEYS.holdSync, JSON.stringify({ ...readHoldRec(), ...p })) } catch { /* 못 남기면 다음 확인이 둘 중 고르라고 묻는다 */ }
}

export type HoldCheck =
  | { ok: false; msg: string }
  | { ok: true; plan: Plan; enc: EncBlob | null; server: Entry[]; serverAt: string | null; localN: number; pass: string }
export type HoldDone = { ok: boolean; msg: string }

const NO_SYNC = '설정에서 기기 간 동기화를 먼저 켜세요.'
function holdErr(r: { status: number; error?: string }): string {
  if (r.status === 401) { disableSync('동기화 키가 맞지 않아 껐습니다. 키를 다시 넣어 주세요.'); return '동기화 키가 맞지 않아 동기화를 껐습니다.' }
  if (r.status === 0) return '서버에 닿지 못했습니다.'
  if (r.status === 429) return '요청이 많습니다. 1분 뒤 다시 해 주세요.'
  if (r.status === 413) return '보낼 내용이 너무 커서 서버가 받지 않았습니다.'
  return `서버가 받지 않았습니다(${r.error ?? r.status}).`
}

/** 설정 화면: 서버에 보유 덩어리가 있는지만 본다. '' = 기록을 새로 남겼다. */
export async function probeHoldings(): Promise<string> {
  const h = getKeyHash()
  if (!h) return NO_SYNC
  const g = await portfolioGet(h)
  if (!g.ok) return holdErr(g)
  noteHold({ server: !!g.enc, checkedAt: new Date().toISOString() })
  return ''
}

/** 확인: 서버 덩어리를 받아 풀고, 이 기기와 비교해 어느 쪽을 쓸지 고른다. 아무것도 덮지 않는다. */
export async function checkHoldings(pass: string): Promise<HoldCheck> {
  const h = getKeyHash()
  if (!h) return { ok: false, msg: NO_SYNC }
  if (!pass.trim()) return { ok: false, msg: '보유 암호를 넣어 주세요.' }
  const g = await portfolioGet(h)
  if (!g.ok) return { ok: false, msg: holdErr(g) }
  noteHold({ server: !!g.enc, checkedAt: new Date().toISOString() })
  const local = entriesOf(readPortfolio().items)
  const lf = { fp: await fingerprint(local), n: local.length }
  const base = readHoldRec().base ?? null
  // 서버에 없으면 새로 정하는 암호다 — 앞뒤 공백을 뺀다(현행 화면이 물어서 풀 때 빼므로 어느 길로든 풀린다).
  if (!g.enc) return { ok: true, plan: decide(lf, null, base), enc: null, server: [], serverAt: null, localN: lf.n, pass: pass.trim() }
  let d: Awaited<ReturnType<typeof decryptAs>>
  try { d = await decryptAs(g.enc, pass) } catch (e) {
    return { ok: false, msg: (e as Error).message === 'wrong-pass' ? '보유 암호가 다릅니다.' : '서버 보유 자료를 읽지 못했습니다.' }
  }
  const plan = decide(lf, { fp: await fingerprint(d.entries), n: d.entries.length }, base)
  if (plan === 'same') noteHold({ base: lf.fp })
  return { ok: true, plan, enc: g.enc, server: d.entries, serverAt: d.at, localN: lf.n, pass: d.pass }
}

/**
 * 올리기: 확인 때 본 서버 덩어리(seen)가 그사이 바뀌지 않았을 때만 이 기기 보유를 잠가 올린다.
 * pass 는 checkHoldings 가 돌려준 HoldCheck.pass(서버 것을 푼 바로 그 문자열)다 — 여기서 다시 다듬지 않는다.
 */
export async function pushHoldings(pass: string, seen: EncBlob | null): Promise<HoldDone> {
  const h = getKeyHash()
  if (!h) return { ok: false, msg: NO_SYNC }
  const bad = await passProblem(pass, async p => (await keyHash(p)) === h, p => (hasPin() ? checkPin(p) : Promise.resolve(false)))
  if (bad) return { ok: false, msg: bad }
  const local = entriesOf(readPortfolio().items)
  const at = new Date().toISOString()
  // 잠그기(PBKDF2 600k, 폰에서 1~3초)는 GET 앞에서 한다 — GET 과 POST 사이를 요청 한 번 길이로 줄인다.
  const enc = await encrypt(local, pass, at)
  if (enc.ciphertext.length > 60_000) return { ok: false, msg: '보유 종목이 너무 많아 올릴 수 없습니다.' }   // Worker _sanitizeEncHoldings 한도
  const g = await portfolioGet(h)
  if (!g.ok) return { ok: false, msg: holdErr(g) }
  if ((g.enc?.ciphertext ?? null) !== (seen?.ciphertext ?? null)) return { ok: false, msg: '그사이 서버 보유가 바뀌었습니다. 다시 확인해 주세요.' }
  // ponytail: GET 과 POST 사이(요청 한 번 길이)에 다른 기기가 알림 조건을 바꾸면 그 변경은 이 POST 가 덮는다. Worker 가 alerts 없는 POST 를 보존하게 되면 alerts 를 뺀다.
  const r = await portfolioPost(h, enc, g.alerts ?? [])
  if (!r.ok) return { ok: false, msg: holdErr(r) }
  noteHold({ base: await fingerprint(local), upAt: at, server: true, checkedAt: at })
  return { ok: true, msg: `올렸습니다 · ${local.length}종목 · ${mdHm(at)}` }
}

/** 받기: 확인 때 풀어 본 서버 칸으로 이 기기 보유를 바꾼다(그 내용을 화면에서 보고 고른 것이다). */
export async function pullHoldings(server: Entry[]): Promise<HoldDone> {
  const p = readPortfolio()
  const group = p.groups[0].id
  const items = applyEntries(p.items, server, (e): Holding => ({
    id: newId('i'), symbol: e.s, market: e.m, yahoo: e.m === 'US' ? e.s : null, name: e.s, secType: 'stock',
    ccy: e.m === 'US' ? 'USD' : 'KRW', avg: e.a, qty: e.q, fxBuy: e.fx, group,
  }))
  if (!writePortfolio({ ...p, items })) return { ok: false, msg: '이 기기에 저장하지 못했습니다. 시크릿 창이거나 저장 공간이 찼습니다.' }
  const at = new Date().toISOString()
  noteHold({ base: await fingerprint(server), downAt: at })
  return { ok: true, msg: `받았습니다 · ${server.length}종목 · ${mdHm(at)}` }
}
