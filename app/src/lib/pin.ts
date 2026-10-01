// 내 자산 잠금 — 현행 사이트(js/app4.js 「페이지 잠금」)와 같은 저장 형식을 그대로 쓴다.
//   localStorage econLockPin_v2 = { salt: 16바이트 hex, iter: 600000, hash: PBKDF2-SHA256 256비트 hex }
//   sessionStorage econLockOk_v1 = '1'  (탭을 닫으면 다시 잠긴다)
// 그래서 한쪽에서 정한 PIN 으로 다른 쪽도 열린다. 이 잠금은 어깨너머 열람을 막는 가림막이지
// 보안 경계가 아니다(서버 자료는 동기화 키가 지킨다).
// 새 앱만 쓰는 열쇠 하나: econLockAt_v1 = 마지막 조작 시각 — 5분 무조작이면 다시 잠근다.

const PIN_KEY = 'econLockPin_v2'
const OK_KEY = 'econLockOk_v1'
const AT_KEY = 'econLockAt_v1'
const ITER = 600_000
export const IDLE_MS = 5 * 60_000

type Stored = { salt: string; iter: number; hash: string }

const toHex = (u8: Uint8Array) => Array.from(u8, b => b.toString(16).padStart(2, '0')).join('')

export function canHash(): boolean {
  return !!(globalThis.crypto && crypto.subtle)
}

async function pbkdf2Hex(pin: string, saltHex: string, iter: number): Promise<string> {
  const salt = new Uint8Array(saltHex.match(/../g)!.map(h => parseInt(h, 16)))
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(pin), 'PBKDF2', false, ['deriveBits'])
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', salt, iterations: iter, hash: 'SHA-256' }, key, 256)
  return toHex(new Uint8Array(bits))
}

function loadPin(): Stored | null {
  try {
    const p = JSON.parse(localStorage.getItem(PIN_KEY) || 'null')
    return p && p.salt && p.hash && p.iter ? p : null
  } catch { return null }
}

export const hasPin = () => loadPin() != null

export async function setPin(pin: string): Promise<void> {
  const salt = toHex(crypto.getRandomValues(new Uint8Array(16)))
  const hash = await pbkdf2Hex(pin, salt, ITER)
  localStorage.setItem(PIN_KEY, JSON.stringify({ salt, iter: ITER, hash }))
  markUnlocked()
}

/** 맞으면 해제 표시까지 하고 true. */
export async function checkPin(pin: string): Promise<boolean> {
  const p = loadPin()
  if (!p) return false
  const ok = (await pbkdf2Hex(pin, p.salt, p.iter)) === p.hash
  if (ok) markUnlocked()
  return ok
}

function ss(fn: () => void) { try { fn() } catch { /* 저장소 막힘 = 잠긴 채로 둔다 */ } }

function markUnlocked() {
  ss(() => { sessionStorage.setItem(OK_KEY, '1'); sessionStorage.setItem(AT_KEY, String(Date.now())) })
}

/** 해제 표시가 있고 마지막 조작이 5분 안이어야 열린 것으로 본다. 현행 사이트가 연 표시만 있으면 다시 묻는다. */
export function isUnlocked(now = Date.now()): boolean {
  try {
    return sessionStorage.getItem(OK_KEY) === '1' && now - Number(sessionStorage.getItem(AT_KEY) || 0) < IDLE_MS
  } catch { return false }
}

export function touch() {
  if (isUnlocked()) ss(() => sessionStorage.setItem(AT_KEY, String(Date.now())))
}

export function lock() {
  ss(() => { sessionStorage.removeItem(OK_KEY); sessionStorage.removeItem(AT_KEY) })
}
