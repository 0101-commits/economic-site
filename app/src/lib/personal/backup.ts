// 내 데이터 파일 — 설정 「내 데이터」 내려받기 · 올리기(사용 패턴 명세 S8). 만들기 · 읽기만 하고 저장소·화면은 만지지 않는다(읽고 쓰기는 store.ts readMyData · writeMyData).
//   평문 파일  { format:'ecom-mydata', version:1, exportedAt, note, portfolio, snapshots, ledger, watch, prefs:{ v:2, alerts, settings:{ …, theme } }, scenarios }
//              theme = 화면 모드(이 기기 값) — 예전 판 내려받기와 같은 자리. scenarios = 렌즈 「만약에」 저장(econ_scenarios_v1).
//              사용 기록(econ_usage_v1)은 이 기기 통계라 싣지 않는다. 비밀(동기화 키 해시 · 보유 열쇠 재료 · PIN)은 읽는 곳이 없어 들어갈 수 없다.
//   잠근 파일  { format, version, locked:true, alg, kdf, iter, salt, iv, ciphertext } — e2e.ts 덩어리와 같은 AES-256-GCM + PBKDF2-SHA256 600,000회.
//              평문 = 위 평문 파일 JSON 전체. 암호 = 파일을 만든 기기의 잠금 PIN(6자리라 파일을 가져간 사람이 오래 시도하면 풀린다 — 화면이 그렇게 적는다).
//   이전 화면 백업(js/app4.js exportAllUserData, schema 'econ-terminal-backup') — 평문이면 열쇠 이름이 같은 둘(portfolioV1 · pfSnapshotsV1)만 가져온다.
//              노트 · 스터디 · 홈 배치 같은 나머지와 암호 백업은 이전 화면에서 복원한다.
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(node --test 로 바로 돈다 — backup.test.ts).
import type { Ledger, Portfolio, Prefs } from './store'
import type { Snap } from './calc'
import type { Theme } from '../theme'
import { ITER, type EncBlob } from './e2e.ts'
import { upgradePrefs } from './prefsV2.ts'

export const FORMAT = 'ecom-mydata'
export const MAX_BYTES = 2 * 1024 * 1024
const NOTE = '이 파일에는 평단가·수량이 들어 있습니다. 남에게 보내지 마세요.'
const PLAIN_KEYS = ['format', 'version', 'exportedAt', 'note', 'portfolio', 'snapshots', 'ledger', 'watch', 'prefs', 'scenarios']
const LOCK_KEYS = ['format', 'version', 'locked', 'alg', 'kdf', 'iter', 'salt', 'iv', 'ciphertext']

export type Scenario = { name?: string; start: string; dir: 1 | -1 } & Record<string, unknown>
export type MyData = {
  portfolio: Portfolio; snapshots: Snap[]; ledger: Ledger[]; watch: string[]
  prefs: Pick<Prefs, 'alerts' | 'settings'>; theme: Theme; scenarios: Scenario[]
}
/** 올린 파일에서 읽은 것. 이전 화면 백업은 보유 · 스냅샷만 있다 — 없는 칸은 이 기기 것을 그대로 둔다. */
export type Loaded = Partial<MyData> & { at: string | null; legacy?: boolean }

const b64 = (u: Uint8Array) => { let s = ''; for (let i = 0; i < u.length; i += 8192) s += String.fromCharCode(...u.subarray(i, i + 8192)); return btoa(s) }
const unb64 = (s: string) => Uint8Array.from(atob(String(s)), c => c.charCodeAt(0))
async function aesKey(pass: string, salt: Uint8Array<ArrayBuffer>) {
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveKey'])
  return crypto.subtle.deriveKey({ name: 'PBKDF2', salt, iterations: ITER, hash: 'SHA-256' }, base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
}

/** 파일 글. pin 을 주면 잠근다(표지와 암호 조건만 평문). */
export async function makeFile(d: MyData, at: string, pin?: string): Promise<string> {
  const doc = {
    format: FORMAT, version: 1, exportedAt: at, note: NOTE,
    portfolio: d.portfolio, snapshots: d.snapshots, ledger: d.ledger, watch: d.watch,
    prefs: { v: 2, alerts: d.prefs.alerts, settings: { ...d.prefs.settings, theme: d.theme } }, scenarios: d.scenarios,
  }
  if (!pin) return JSON.stringify(doc, null, 2)
  const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12))
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await aesKey(pin, salt), new TextEncoder().encode(JSON.stringify(doc)))
  const blob: EncBlob = { alg: 'AES-256-GCM', kdf: 'PBKDF2-SHA256', iter: ITER, salt: b64(salt), iv: b64(iv), ciphertext: b64(new Uint8Array(ct)) }
  return JSON.stringify({ format: FORMAT, version: 1, locked: true, ...blob }, null, 2)
}

const isObj = (v: unknown): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v)
const fail = (msg: string) => new Error(msg)

/**
 * 올린 파일 글 → 내용. 문제는 Error(화면에 그대로 띄울 문구). 잠긴 파일인데 pin 이 없으면 Error('need-pin'),
 * PIN 이 틀리면(GCM 인증 실패) Error('wrong-pin') — 이 둘만 화면이 따로 다룬다.
 */
export async function readFile(text: string, pin?: string): Promise<Loaded> {
  if (new TextEncoder().encode(text).length > MAX_BYTES) throw fail('파일이 너무 큽니다(2MB 넘음). 이 화면에서 내려받은 파일이 아닙니다.')
  let doc: any
  try { doc = JSON.parse(text) } catch { throw fail('JSON 파일이 아니거나 깨졌습니다.') }
  if (!isObj(doc)) throw fail('JSON 파일이 아니거나 깨졌습니다.')
  if (doc.schema === 'econ-terminal-backup') return legacy(doc)
  // format 이 없는 것은 이 판 전에 새 화면에서 내려받은 파일이다(모양은 같다)
  if (doc.format !== FORMAT && !(doc.format === undefined && 'portfolio' in doc && 'prefs' in doc)) throw fail('이 화면에서 내려받은 파일이 아닙니다.')
  if (doc.version !== undefined && doc.version !== 1) throw fail('이 화면이 모르는 판의 파일입니다.')
  if (doc.locked === true) {
    unknownKeys(doc, LOCK_KEYS)
    if (!pin) throw fail('need-pin')
    let pt: ArrayBuffer
    try { pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64(doc.iv) }, await aesKey(pin, unb64(doc.salt)), unb64(doc.ciphertext)) } catch { throw fail('wrong-pin') }
    try { doc = JSON.parse(new TextDecoder().decode(pt)) } catch { doc = null }
    if (!isObj(doc) || doc.format !== FORMAT || doc.locked) throw fail('잠긴 내용이 깨졌습니다.')
  }
  unknownKeys(doc, PLAIN_KEYS)
  const list = (k: string): any[] => {
    const v = doc[k]
    if (v == null) return []
    if (!Array.isArray(v)) throw fail(`「${k}」 칸이 깨졌습니다.`)
    return v
  }
  if (!isObj(doc.portfolio) || !Array.isArray(doc.portfolio.items)) throw fail('「portfolio」 칸이 깨졌습니다.')
  if (doc.prefs != null && !isObj(doc.prefs)) throw fail('「prefs」 칸이 깨졌습니다.')
  const p = upgradePrefs(doc.prefs), th = doc.prefs?.settings?.theme
  return {
    at: typeof doc.exportedAt === 'string' && !Number.isNaN(Date.parse(doc.exportedAt)) ? doc.exportedAt : null,
    portfolio: doc.portfolio as Portfolio,
    snapshots: list('snapshots').filter(x => isObj(x) && typeof x.d === 'string'),
    ledger: list('ledger').filter(x => isObj(x) && typeof x.d === 'string' && typeof x.amt === 'number'),
    watch: list('watch').filter((x): x is string => typeof x === 'string'),
    prefs: { alerts: p.alerts, settings: p.settings },
    theme: th === 'light' || th === 'dark' ? th : 'system',
    // 렌즈 「만약에」가 읽는 모양만(WhatIf.tsx readSaved 와 같은 거르기)
    scenarios: list('scenarios').filter(x => isObj(x) && typeof x.start === 'string' && (x.dir === 1 || x.dir === -1)),
  }
}

function unknownKeys(doc: Record<string, unknown>, known: string[]) {
  const extra = Object.keys(doc).filter(k => !known.includes(k))
  if (extra.length) throw fail(`이 화면이 모르는 칸이 있습니다: ${extra.slice(0, 5).join(', ')}`)
}

function legacy(doc: Record<string, any>): Loaded {
  if (doc.enc || doc.ciphertext) throw fail('이전 화면의 암호 백업입니다. 이전 화면 「설정 › 데이터 백업·복구」에서 복원하세요.')
  const json = (v: unknown) => { try { return typeof v === 'string' ? JSON.parse(v) : null } catch { return null } }
  const pf = json(doc.data?.portfolioV1), sn = json(doc.data?.pfSnapshotsV1)
  const out: Loaded = { at: typeof doc.exportedAt === 'string' && !Number.isNaN(Date.parse(doc.exportedAt)) ? doc.exportedAt : null, legacy: true }
  if (isObj(pf) && Array.isArray(pf.items)) out.portfolio = pf as Portfolio
  if (Array.isArray(sn)) out.snapshots = sn.filter(x => isObj(x) && typeof x.d === 'string')
  if (!out.portfolio && !out.snapshots) throw fail('이전 화면 백업에 보유 · 스냅샷이 없습니다. 이전 화면에서 복원하세요.')
  return out
}

/** 미리보기 숫자. 조건은 「사건 전체 조정」('*')을 빼고 센다(sync.ts countOf 와 같다). 없는 칸은 null. */
export function countOf(l: Loaded) {
  return {
    holdings: l.portfolio ? l.portfolio.items.length : null, ledger: l.ledger?.length ?? null, snapshots: l.snapshots?.length ?? null,
    watch: l.watch?.length ?? null, alerts: l.prefs ? l.prefs.alerts.filter(a => a.target !== '*').length : null, scenarios: l.scenarios?.length ?? null,
  }
}
