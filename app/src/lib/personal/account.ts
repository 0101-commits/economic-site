// 계정 — 앱키로 들어온 사람(Worker GET /me)을 이 기기가 기억하는 층. 저장소 로직은 sync.ts 가 갖고 있으므로 여기서 다시 만들지 않는다.
//   econMe_v1 (localStorage) = { uid, name, role, viaBackup, status? } — 표시용 사본이다. 권한은 언제나 서버가 키 해시로 다시 본다.
//   status:'paused' = 서버가 403(멈춤)으로 답한 뒤 남기는 표시(키·연결은 그대로 둔다 — 다시 풀리면 곧 돌아온다).
// sync.ts 는 화면 모듈(react · push · pin)을 끌고 와 node --test 로 못 불러오므로, 흐름은 makeAccount(deps) 에 두고
// 실제 deps 는 첫 호출 때 import('./sync') 로 가져온다(시험은 가짜를 꽂는다).
import { useSyncExternalStore } from 'react'
import { keyHash, meGet, type Me } from './remote.ts'
import { normalizeEntryKey } from './entryKey.ts'
import { setPendingPerson } from './who.ts'

export type { Me }
export const ME_KEY = 'econMe_v1'
export type SignInResult = 'ok' | 'bad' | 'paused' | 'rate' | 'offline'
export type StoredMe = Me & { status?: 'paused' }

export type Deps = {
  getKeyHash: () => string | null
  connectSync: (key: string, perm?: Promise<unknown>) => Promise<boolean>
  disableSync: (msg?: string) => void
  forgetDevice: () => Promise<void>
  dropPush?: () => Promise<void>   // 401 때 이 브라우저 폰 알림 구독 끊기(push.dropLocalPush)
}

/** 저장된 글 → Me. 모양이 틀리면 null. */
export function parseMe(raw: string | null): StoredMe | null {
  if (!raw) return null
  try {
    const j = JSON.parse(raw)
    if (!j || typeof j.uid !== 'string' || typeof j.name !== 'string' || (j.role !== 'owner' && j.role !== 'member')) return null
    const me: StoredMe = { uid: j.uid, name: j.name, role: j.role, viaBackup: j.viaBackup === true }
    if (j.status === 'paused') me.status = 'paused'
    return me
  } catch { return null }
}

const rawMe = () => { try { return localStorage.getItem(ME_KEY) } catch { return null } }
const listeners = new Set<() => void>()
function notify() {
  listeners.forEach(f => f())
  try { window.dispatchEvent(new StorageEvent('storage', { key: ME_KEY })) } catch { /* window 없음(시험) */ }
}
// 키가 안 맞아(401) 끊겼다는 표시(이 탭) — 입장 관문이 why=lost 로 「키가 바뀌었거나 지워졌습니다」를 띄운다. 다시 들어오거나 나가면 지운다.
const LOST_KEY = 'econKeyLost_v1'
function setLost(on: boolean) {
  try { if (on) sessionStorage.setItem(LOST_KEY, '1'); else sessionStorage.removeItem(LOST_KEY) } catch { /* 막힌 저장소 = 표시 없음 */ }
}
/** 이 탭에서 키가 안 맞아(401) 끊겼나. */
export const keyWasLost = (): boolean => { try { return sessionStorage.getItem(LOST_KEY) === '1' } catch { return false } }
function writeMe(me: StoredMe | null, lost = false) {
  setLost(lost)
  try { if (me) localStorage.setItem(ME_KEY, JSON.stringify(me)); else localStorage.removeItem(ME_KEY) } catch { /* 못 남기면 이번 탭만 */ }
  notify()
}

/** 이 기기가 기억하는 사람 — 없으면 null. */
export const readMe = (): StoredMe | null => parseMe(rawMe())

// useSyncExternalStore 는 같은 값에 같은 객체를 돌려줘야 한다 — 저장된 글이 같으면 이전 파싱 결과를 쓴다.
let snapRaw: string | null | undefined, snapMe: StoredMe | null = null
function snapshot(): StoredMe | null {
  const r = rawMe()
  if (r !== snapRaw) { snapRaw = r; snapMe = parseMe(r) }
  return snapMe
}
function subscribe(f: () => void) {
  listeners.add(f)
  const onStorage = (e: StorageEvent) => { if (!e.key || e.key === ME_KEY) f() }   // 다른 탭에서 바뀐 것
  try { window.addEventListener('storage', onStorage) } catch { /* window 없음 */ }
  return () => { listeners.delete(f); try { window.removeEventListener('storage', onStorage) } catch { /* 같음 */ } }
}
/** 화면용 훅(얇게): 저장된 me 를 구독한다. */
export const useMe = (): StoredMe | null => useSyncExternalStore(subscribe, snapshot, () => null)

/** 키가 안 맞음(401)을 어디서 받았든 같은 뒷정리 — me 삭제 + 끊긴 표시(연결 끊기 · 폰 알림 구독 끊기는 부른 쪽이 한다). 기기 기록은 그대로. */
export const clearMe = (): void => writeMe(null, true)
/** 멈춤(403)을 어디서 받았든 같은 뒷정리 — 표시만 남기고 키 · 연결은 그대로. */
export function markPaused(): void { const cur = readMe(); if (cur && cur.status !== 'paused') writeMe({ ...cur, status: 'paused' }, keyWasLost()) }

export function makeAccount(deps: Deps) {
  /**
   * 앱키로 들어오기: 정규화 → 해시 → GET /me → ok 면 연결(connectSync — 설정 · 보유를 묻지 않고 맞춘다, 서버 우선)을 하고 me 를 저장한다.
   * perm = 들어가기 단추를 누른 그 순간 물은 폰 알림 허락(아이폰 · 사파리는 사용자 동작 안에서만 묻는다) — 연결이 이어지면 이 기기를 구독한다.
   */
  async function signIn(raw: string, perm?: Promise<unknown>): Promise<SignInResult> {
    let h: string
    try { h = await keyHash(normalizeEntryKey(raw)) } catch { return 'offline' }
    const r = await meGet(h)
    if (r.status === 401) return 'bad'
    if (r.status === 403) return 'paused'
    if (r.status === 429) return 'rate'
    if (r.status !== 200 || !r.me) return 'offline'   // 0 네트워크 · 503 서버 · 모양 틀림
    // 연결(connectSync)이 읽고 쓰는 기기 저장 이름이 이 사람 것이 되게, me 를 남기기 전에 들어오는 사람으로 알려 둔다(who.ts).
    // viaBackup(예비 앱키)도 같이 — 보유 맞춤이 이것을 보고 덮어쓰기를 막는다(holdSync.ts).
    setPendingPerson({ uid: r.me.uid, role: r.me.role, viaBackup: r.me.viaBackup })
    let linked = false
    try { linked = await deps.connectSync(raw, perm) } catch { linked = false }
    // 연결이 끝났는데 해시가 없으면 들어온 것이 아니다(묻는 단계는 없다 — 맞춤은 규칙대로 저절로).
    if (!linked || !deps.getKeyHash()) { setPendingPerson(null); return 'offline' }
    writeMe(r.me)
    setPendingPerson(null)
    return 'ok'
  }

  /** 앱을 열 때 서버에 다시 묻는다. 401 = 키가 더는 안 맞음 → 끊고 me 삭제 · 403 = 표시만 · 200 = 최신으로 갱신 · 그 밖(429 · 503 · 네트워크)은 그대로. */
  async function refreshMe(): Promise<void> {
    const h = deps.getKeyHash()
    if (!h) return
    const r = await meGet(h)
    // 기다리는 사이 다른 키로 들어왔으면(해시가 바뀜) 옛 키의 답으로 새 로그인을 지우지 않는다.
    if ((r.status === 401 || r.status === 403) && deps.getKeyHash() !== h) return
    if (r.status === 401) { clearMe(); deps.disableSync(); await deps.dropPush?.().catch(() => {}) }   // 끊긴 표시를 먼저(관문이 why=lost 로 보낸다)
    else if (r.status === 403) markPaused()
    else if (r.status === 200 && r.me) writeMe(r.me)
  }

  /** 나가기: 이 기기 연결을 잊고(폰 알림 구독 해제 · 해시 · 보유 열쇠 재료) me 를 지운다. */
  async function signOut(): Promise<void> {
    await deps.forgetDevice()
    writeMe(null)
  }
  return { signIn, refreshMe, signOut }
}

// 실제 deps — sync.ts 는 첫 호출 때 불러온다(node 시험이 화면 모듈을 끌고 오지 않게).
let instance: ReturnType<typeof makeAccount> | null = null
const lazy = async () => {
  if (instance) return instance
  const [s, p] = await Promise.all([import('./sync'), import('../push')])
  return (instance ??= makeAccount({ getKeyHash: s.getKeyHash, connectSync: (k, perm) => s.connectSync(k, perm), disableSync: s.disableSync, forgetDevice: s.forgetDevice, dropPush: p.dropLocalPush }))
}
export const signIn = async (raw: string, perm?: Promise<unknown>): Promise<SignInResult> => (await lazy()).signIn(raw, perm)
export const refreshMe = async (): Promise<void> => (await lazy()).refreshMe()
export const signOut = async (): Promise<void> => (await lazy()).signOut()
