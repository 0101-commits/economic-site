// 계정 — 입장 키로 들어온 사람(Worker GET /me)을 이 기기가 기억하는 층. 저장소 로직은 sync.ts 가 갖고 있으므로 여기서 다시 만들지 않는다.
//   econMe_v1 (localStorage) = { uid, name, role, viaBackup, status? } — 표시용 사본이다. 권한은 언제나 서버가 키 해시로 다시 본다.
//   status:'paused' = 서버가 403(멈춤)으로 답한 뒤 남기는 표시(키·연결은 그대로 둔다 — 다시 풀리면 곧 돌아온다).
// sync.ts 는 화면 모듈(react · push · pin)을 끌고 와 node --test 로 못 불러오므로, 흐름은 makeAccount(deps) 에 두고
// 실제 deps 는 첫 호출 때 import('./sync') 로 가져온다(시험은 가짜를 꽂는다).
import { useSyncExternalStore } from 'react'
import { keyHash, meGet, type Me } from './remote.ts'
import { normalizeEntryKey } from './entryKey.ts'

export type { Me }
export const ME_KEY = 'econMe_v1'
export type SignInResult = 'ok' | 'ask' | 'bad' | 'paused' | 'rate' | 'offline'
export type StoredMe = Me & { status?: 'paused' }

export type Deps = {
  getKeyHash: () => string | null
  connectSync: (key: string) => Promise<boolean>
  disableSync: (msg?: string) => void
  forgetDevice: () => Promise<void>
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
function writeMe(me: StoredMe | null) {
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

export function makeAccount(deps: Deps) {
  /** 입장 키로 들어오기: 정규화 → 해시 → GET /me → ok 면 me 를 저장하고 기존 연결(connectSync)을 이어 한다. */
  async function signIn(raw: string): Promise<SignInResult> {
    let h: string
    try { h = await keyHash(normalizeEntryKey(raw)) } catch { return 'offline' }
    const r = await meGet(h)
    if (r.status === 401) return 'bad'
    if (r.status === 403) return 'paused'
    if (r.status === 429) return 'rate'
    if (r.status !== 200 || !r.me) return 'offline'   // 0 네트워크 · 503 서버 · 모양 틀림
    pending = null
    if (!(await deps.connectSync(raw))) return 'offline'
    // connectSync 는 이 기기 것과 서버 것이 달라 묻는 중에도 true 를 돌려준다(해시는 답한 뒤에 저장) — 해시가 없으면 아직 들어온 것이 아니다.
    if (deps.getKeyHash()) { writeMe(r.me); return 'ok' }
    pending = r.me
    return 'ask'
  }
  let pending: Me | null = null

  /** 'ask' 에 답한 뒤 부른다: 해시가 저장됐으면 기다리던 me 를 남기고 true, 아니면 false(아무것도 안 남긴다). */
  function finishSignIn(): boolean {
    const me = pending
    if (!me || !deps.getKeyHash()) return false
    pending = null
    writeMe(me)
    return true
  }
  /** 'ask' 에서 그만두기: 기다리던 me 를 버린다. */
  function cancelSignIn(): void { pending = null }

  /** 앱을 열 때 서버에 다시 묻는다. 401 = 키가 더는 안 맞음 → 끊고 me 삭제 · 403 = 표시만 · 200 = 최신으로 갱신 · 그 밖(429 · 503 · 네트워크)은 그대로. */
  async function refreshMe(): Promise<void> {
    const h = deps.getKeyHash()
    if (!h) return
    const r = await meGet(h)
    // 기다리는 사이 다른 키로 들어왔으면(해시가 바뀜) 옛 키의 답으로 새 로그인을 지우지 않는다.
    if ((r.status === 401 || r.status === 403) && deps.getKeyHash() !== h) return
    if (r.status === 401) { deps.disableSync(); writeMe(null) }
    else if (r.status === 403) { const cur = readMe(); if (cur) writeMe({ ...cur, status: 'paused' }) }
    else if (r.status === 200 && r.me) writeMe(r.me)
  }

  /** 나가기: 이 기기 연결을 잊고(폰 알림 구독 해제 · 해시 · 보유 열쇠 재료) me 를 지운다. */
  async function signOut(): Promise<void> {
    await deps.forgetDevice()
    writeMe(null)
  }
  return { signIn, finishSignIn, cancelSignIn, refreshMe, signOut }
}

// 실제 deps — sync.ts 는 첫 호출 때 불러온다(node 시험이 화면 모듈을 끌고 오지 않게).
let instance: ReturnType<typeof makeAccount> | null = null   // 'ask' 로 기다리는 me 가 한 곳에 남도록 하나만 둔다
const lazy = async () => {
  if (instance) return instance
  const s = await import('./sync')
  return (instance ??= makeAccount({ getKeyHash: s.getKeyHash, connectSync: k => s.connectSync(k), disableSync: s.disableSync, forgetDevice: s.forgetDevice }))
}
export const signIn = async (raw: string): Promise<SignInResult> => (await lazy()).signIn(raw)
/** signIn 이 'ask' 를 돌려준 뒤 사용자가 연결 질문에 답하면 부른다. 해시가 저장됐을 때만 true. */
export const finishSignIn = (): boolean => instance?.finishSignIn() ?? false
/** signIn 이 'ask' 를 돌려준 뒤 사용자가 그만두면 부른다. */
export const cancelSignIn = (): void => { instance?.cancelSignIn() }
export const refreshMe = async (): Promise<void> => (await lazy()).refreshMe()
export const signOut = async (): Promise<void> => (await lazy()).signOut()
