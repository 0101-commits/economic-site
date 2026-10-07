// 내 자산 잠금 — 현행 사이트(js/app4.js 「페이지 잠금」)와 같은 저장 형식을 그대로 쓴다.
//   localStorage econLockPin_v2 = { salt: 16바이트 hex, iter: 600000, hash: PBKDF2-SHA256 256비트 hex }
//   sessionStorage econLockOk_v1 = '1'  (탭을 닫으면 다시 잠긴다)
// 그래서 한쪽에서 정한 PIN 으로 다른 쪽도 열린다. 이 잠금은 어깨너머 열람을 막는 가림막이지
// 보안 경계가 아니다(서버 자료는 동기화 키가 지킨다).
// 새 앱만 쓰는 열쇠 둘: econLockAt_v1 = 마지막 조작 시각 — 5분 무조작이면 다시 잠근다.
//   localStorage econLockFail_v1 = { n: 연속 실패 수, until: 이때까지 PIN 을 받지 않음(ms) } — 맞히면 지운다.
//   5~9번째 실패 = 30초, 10번째부터는 실패마다 5분. 탭을 새로 열어도 이어진다(그래서 sessionStorage 가 아니다).
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(node --test 로 바로 돈다 — pin.test.ts).

const PIN_KEY = 'econLockPin_v2'
const OK_KEY = 'econLockOk_v1'
const AT_KEY = 'econLockAt_v1'
const FAIL_KEY = 'econLockFail_v1'
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

/** 이 PIN 이 맞는지만 본다 — 해제 표시도 실패 셈도 하지 않는다(보유 암호가 PIN 과 같은지 견줄 때). */
export async function samePin(pin: string): Promise<boolean> {
  const p = loadPin()
  return !!p && (await pbkdf2Hex(pin, p.salt, p.iter)) === p.hash
}

/**
 * 잠금 풀기 시도. 기다리는 중이면 견주지 않고 false. 견주기(PBKDF2 수백 ms) 전에 실패 한 번을 먼저 적고 맞으면 지운다 —
 * 뒤에 적으면 그 사이에 넣은 시도들이 같은 셈을 읽어 덜 세어진다.
 */
export async function checkPin(pin: string, now = Date.now()): Promise<boolean> {
  if (waitMs(now) > 0) return false
  const n = readFail().n + 1
  writeFail({ n, until: now + failDelay(n) })
  const ok = await samePin(pin)
  if (ok) { markUnlocked(); writeFail(null) }
  return ok
}

/** PIN 잊음: 이 기기 PIN 과 실패 셈을 지운다(동기화 키를 확인했거나 이 기기 데이터를 지운 뒤에만 — PinGate). */
export function clearPin() {
  lock()
  ss(() => localStorage.removeItem(PIN_KEY))
  writeFail(null)
}

// ── 실패 대기 ────────────────────────────────────────────
export type Fail = { n: number; until: number }
/** n 번째로 틀린 뒤 기다릴 시간(ms). */
export const failDelay = (n: number) => (n >= 10 ? 5 * 60_000 : n >= 5 ? 30_000 : 0)
let memFail: Fail | null = null   // localStorage 에 못 쓸 때(시크릿 창 · 막힘)만 이 탭 안에서 센다
export function readFail(): Fail {
  if (memFail) return memFail
  try {
    const f = JSON.parse(localStorage.getItem(FAIL_KEY) || 'null')
    return f && Number.isFinite(f.n) && Number.isFinite(f.until) ? { n: f.n, until: f.until } : { n: 0, until: 0 }
  } catch { return { n: 0, until: 0 } }
}
/** null = 지우기. 저장소에 못 쓰면 모듈 메모리에 둔다 — 셈이 사라져 대기가 풀리지 않게. */
function writeFail(f: Fail | null) {
  try { if (f) localStorage.setItem(FAIL_KEY, JSON.stringify(f)); else localStorage.removeItem(FAIL_KEY); memFail = null }
  catch { memFail = f }
}
/** 기다리는 중이면 남은 ms, 아니면 0. 시계를 되돌려도 그 회차 대기보다 길게 남지 않는다. */
export const waitMs = (now = Date.now()) => { const f = readFail(); return Math.max(0, Math.min(f.until - now, failDelay(f.n))) }

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
