// 보유(평단가·수량·매입 환율)의 종단간 암호화 — 현행 화면(js/app2.js pfBuildEncHoldings · pfApplyEncHoldings)과 같은 형식.
//   덩어리  { alg:'AES-256-GCM', kdf:'PBKDF2-SHA256', iter:600000, salt, iv, ciphertext }  표준 base64 · salt 16바이트 · iv 12바이트, 올릴 때마다 새로 뽑는다.
//   열쇠    「암호」 → PBKDF2-HMAC-SHA256 600,000회 → AES-GCM 256비트. 현행 화면처럼 반복 수는 덩어리의 iter 가 아니라 고정값으로 푼다.
//           새 화면의 「암호」 = 보유 열쇠 재료(holdKeyOf — 동기화 키에서 만든 hex, 결정 D9 a). 서버 인증 해시(SHA-256)와는 다른 재료다.
//           예전 판은 사람이 정한 보유 암호(현행 화면의 「평단가 동기화 암호」)로 잠갔다 — 그 사본은 openBlob 이 예전 암호로 한 번 푼다(이전).
//   평문    JSON 배열 [{ s:종목 코드, m:'KR'|'US', a:평단가, q:수량, fx:매입 환율 }] — 평단가나 수량이 있는 종목만.
//           새 화면은 끝에 { t:올린 시각 } 한 칸을 붙인다. 현행 화면은 s 가 없는 칸을 건너뛰므로 그대로 읽는다.
//           Worker 는 덩어리의 모르는 필드를 지우므로(_sanitizeEncHoldings) 시각은 암호문 안에만 둘 수 있다.
// 저장소·화면·네트워크를 만지지 않는다 — node --test 로 바로 돈다(e2e.test.ts). 흐름은 sync.ts 「보유」 칸.
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(calc.ts 와 같은 규칙).

export const ITER = 600_000

export type EncBlob = { alg: 'AES-256-GCM'; kdf: 'PBKDF2-SHA256'; iter: number; salt: string; iv: string; ciphertext: string }
export type Entry = { s: string; m: 'KR' | 'US'; a: number | null; q: number | null; fx: number | null }
type Item = { symbol: string; market: string; avg?: number | null; qty?: number | null; fxBuy?: number | null }

const b64 = (u: Uint8Array) => { let s = ''; for (let i = 0; i < u.length; i += 8192) s += String.fromCharCode(...u.subarray(i, i + 8192)); return btoa(s) }
const unb64 = (s: string) => Uint8Array.from(atob(String(s)), c => c.charCodeAt(0))
const hex = (b: ArrayBuffer) => Array.from(new Uint8Array(b), x => x.toString(16).padStart(2, '0')).join('')

async function aesKey(pass: string, salt: Uint8Array<ArrayBuffer>) {
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveKey'])
  return crypto.subtle.deriveKey({ name: 'PBKDF2', salt, iterations: ITER, hash: 'SHA-256' }, base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
}

/** 보유 줄(portfolioV1.items) → 덩어리에 넣을 칸. 평단가나 수량이 있는 종목만(현행과 같다). */
export function entriesOf(items: Item[]): Entry[] {
  return items.filter(it => it.avg != null || it.qty != null)
    .map((it): Entry => ({ s: it.symbol, m: it.market === 'US' ? 'US' : 'KR', a: it.avg ?? null, q: it.qty ?? null, fx: it.fxBuy ?? null }))
}

const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/** 풀어낸 평문 → 칸 + 올린 시각(현행 화면이 올린 것은 null). 서버에서 온 값이라 모양이 틀린 칸은 버린다. */
export function parsePlain(v: unknown): { entries: Entry[]; at: string | null } {
  if (!Array.isArray(v)) throw new Error('shape')
  const entries: Entry[] = []
  let at: string | null = null
  for (const h of v) {
    if (!h || typeof h !== 'object') continue
    if (typeof h.s !== 'string' || !h.s) { if (typeof h.t === 'string') at = h.t; continue }
    const e: Entry = { s: h.s.slice(0, 40), m: h.m === 'US' ? 'US' : 'KR', a: num(h.a), q: num(h.q), fx: num(h.fx) }
    if (e.a != null || e.q != null) entries.push(e)
  }
  return { entries, at }
}

/** 칸 → 덩어리(올리기). at = 올린 시각(ISO). */
export async function encrypt(entries: Entry[], pass: string, at: string): Promise<EncBlob> {
  const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12))
  const key = await aesKey(pass, salt)
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(JSON.stringify([...entries, { t: at }])))
  return { alg: 'AES-256-GCM', kdf: 'PBKDF2-SHA256', iter: ITER, salt: b64(salt), iv: b64(iv), ciphertext: b64(new Uint8Array(ct)) }
}

/** 덩어리 → 칸. 암호가 다르면(GCM 인증 실패) Error('wrong-pass'). */
export async function decrypt(blob: EncBlob, pass: string): Promise<{ entries: Entry[]; at: string | null }> {
  let pt: ArrayBuffer
  try {
    const key = await aesKey(pass, unb64(blob.salt))
    pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64(blob.iv) }, key, unb64(blob.ciphertext))
  } catch { throw new Error('wrong-pass') }
  return parsePlain(JSON.parse(new TextDecoder().decode(pt)))
}

/**
 * 덩어리 → 칸 + 실제로 풀린 암호 문자열. 현행 화면은 설정한 암호를 친 그대로 저장해 쓰고(js/app2.js pfSetHoldingsPass),
 * 물어서 받을 때만 앞뒤 공백을 뺀다 — 그래서 원문으로 먼저 풀고, 안 되면 공백 뺀 값으로 한 번 더 푼다.
 * 올릴 때는 여기서 돌려준 pass 를 그대로 써야 다른 기기가 같은 글자로 푼다.
 */
export async function decryptAs(blob: EncBlob, pass: string): Promise<{ entries: Entry[]; at: string | null; pass: string }> {
  try { return { ...(await decrypt(blob, pass)), pass } } catch (e) {
    const t = pass.trim()
    if ((e as Error).message !== 'wrong-pass' || t === pass) throw e
    return { ...(await decrypt(blob, t)), pass: t }
  }
}

// ── 보유 열쇠 재료(결정 D9 a) — 동기화 키 하나로 보유도 잠근다 ─────────────
/** 연결할 때(키 원문이 손에 있을 때) 한 번: PBKDF2-SHA256(앞뒤 공백 뺀 키, salt "ecom-holdings-v1", 600,000회) → 32바이트 hex.
 *  서버는 SHA-256(키)만 알므로 이 재료를 만들 수 없다. 이 hex 가 덩어리 형식의 「암호」 자리에 들어간다. */
export const HOLD_SALT = 'ecom-holdings-v1'
export async function holdKeyOf(key: string): Promise<string> {
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(key.trim()), 'PBKDF2', false, ['deriveBits'])
  return hex(await crypto.subtle.deriveBits({ name: 'PBKDF2', salt: new TextEncoder().encode(HOLD_SALT), iterations: ITER, hash: 'SHA-256' }, base, 256))
}

/**
 * 서버 덩어리를 보유 열쇠 재료로 푼다. 안 풀리면 예전 보유 암호로 잠긴 사본이다 — old 가 없으면 Error('old-pass').
 * old 는 친 그대로 · 공백 뺀 값(decryptAs)으로 풀고, 그래도 안 되면 그 글자를 예전 동기화 키로 보고 만든 재료로 한 번 더 푼다
 * (키를 바꾼 직후 다시 잠가 올리기가 실패해 예전 키 재료로 남은 사본). old 도 틀리면 Error('wrong-pass').
 * stale = 지금 재료가 아닌 것으로 풀렸다 → 지금 재료로 다시 잠가 올려야 한다.
 */
export async function openBlob(blob: EncBlob, mat: string, old?: string): Promise<{ entries: Entry[]; at: string | null; stale: boolean }> {
  try { return { ...(await decrypt(blob, mat)), stale: false } } catch (e) { if ((e as Error).message !== 'wrong-pass') throw e }
  if (!old?.trim()) throw new Error('old-pass')
  try { const d = await decryptAs(blob, old); return { entries: d.entries, at: d.at, stale: true } } catch (e) { if ((e as Error).message !== 'wrong-pass') throw e }
  return { ...(await decrypt(blob, await holdKeyOf(old))), stale: true }
}

/**
 * 묻지 않고 해도 되는 보유 맞춤(저장 2초 뒤 · 연결할 때 · 내 자산을 열 때). decide 의 판정 → 할 일.
 *   push 이 기기만 바뀜 · pull 서버만 바뀜 · ask 둘 다 바뀜, 또는 빈 이 기기로 서버 사본을 지우게 됨(저장소가 깨졌을 수 있다) · null 할 일 없음.
 */
export function autoStep(plan: Plan, localN: number, serverN: number): 'push' | 'pull' | 'ask' | null {
  if (plan === 'push') return localN === 0 && serverN > 0 ? 'ask' : 'push'
  return plan === 'pull' ? 'pull' : plan === 'conflict' ? 'ask' : null
}

/**
 * 올릴 암호 검사. '' = 통과. 잠금 PIN 으로 잠근 암호문이 감사에서 풀린 적이 있어(2026-09-29) PIN 과 같은 암호는 받지 않는다.
 * 현행 잠금은 4자 이상 아무 글자나 PIN 으로 받으므로(js/app4.js) 모양을 보지 않고 늘 견준다. 공백 뺀 값도 견준다.
 */
export async function passProblem(pass: string, sameAsSyncKey: (p: string) => Promise<boolean>, isPin: (p: string) => Promise<boolean>): Promise<string> {
  if (pass.trim().length < 6) return '보유 암호는 6자 이상이어야 합니다. 12자 이상을 권합니다.'
  if (await sameAsSyncKey(pass)) return '동기화 키와 다른 암호를 쓰세요.'
  for (const p of new Set([pass, pass.trim()])) if (await isPin(p)) return '잠금 PIN 과 다른 암호를 쓰세요.'
  return ''
}

/** 보유 지문(SHA-256 hex) — 종목 순서와 무관. 마지막으로 맞춘 때와 비교하는 데만 쓴다. */
export async function fingerprint(es: Entry[]): Promise<string> {
  const c = JSON.stringify(es.filter(e => e.a != null || e.q != null).map(e => [e.m, e.s, e.a, e.q, e.fx]).sort())
  return hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(c)))
}

export type Plan = 'same' | 'push' | 'pull' | 'conflict' | 'none'
type Side = { fp: string; n: number }

/**
 * 어느 쪽을 쓸지 고른다(화면이 덮기 전에 한 번 묻는다). base = 마지막으로 이 기기와 서버를 맞췄을 때의 지문.
 * 시각 대신 지문을 비교한다 — 현행 화면은 보유를 고친 시각을 남기지 않고, 기기 시계는 서로 다를 수 있다.
 *   서버에 없음 → 이 기기에 보유가 있으면 push, 없으면 none
 *   같음 → same
 *   이 기기가 base 그대로 → 서버가 바뀌었다 → pull
 *   서버가 base 그대로 → 이 기기가 바뀌었다 → push
 *   base 를 모르는데 이 기기가 비었음 → pull
 *   그 밖(둘 다 바뀜 · 처음 맞추는데 둘 다 있음) → conflict
 */
export function decide(local: Side, server: Side | null, base: string | null): Plan {
  if (!server) return local.n ? 'push' : 'none'
  if (local.fp === server.fp) return 'same'
  if (base === local.fp) return 'pull'
  if (base === server.fp) return 'push'
  if (!local.n) return 'pull'
  return 'conflict'
}

/**
 * 받기: 서버 칸으로 이 기기 보유를 바꾼다. 목록에 있는 종목은 평단가·수량·매입 환율을 서버 값으로,
 * 서버에 없는 종목은 비우고(줄은 남긴다), 이 기기에 없는 종목은 make 로 새 줄을 만든다.
 */
export function applyEntries<T extends Item>(items: T[], es: Entry[], make: (e: Entry) => T): T[] {
  const left = new Map(es.map(e => [`${e.m}:${e.s}`, e]))
  const out = items.map(it => {
    const k = `${it.market === 'US' ? 'US' : 'KR'}:${it.symbol}`
    const e = left.get(k)
    left.delete(k)
    return { ...it, avg: e ? e.a : null, qty: e ? e.q : null, fxBuy: e ? e.fx : null }
  })
  return [...out, ...[...left.values()].map(make)]
}
