// Worker 와 주고받는 것 중 순수한 부분 — 주소 · 동기화 키 해시 · /prefs 문서와 이 기기 저장소 모양 사이 변환 · GET/PUT 한 번.
// 저장소(localStorage)·화면을 만지지 않으므로 node --test 로 바로 돌린다(remote.test.ts). 저장소 쪽 흐름은 sync.ts.
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(calc.ts 와 같은 규칙).
import type { AlertCond, Settings } from './store'
import { upgradePrefs } from './prefsV2.ts'
import type { EncBlob } from './e2e'

/** Worker 주소. 배포 화면의 보안 정책(vite.config.ts connect-src)이 이 주소 하나만 열어 두므로 바꿔 끼우는 설정은 두지 않는다. */
export const WORKER = 'https://ecom-dashboard-proxy.e-hcg.workers.dev'

/** 동기화 키 → 서버가 비교하는 해시. 현행 화면(js/app2.js pfSetSyncKey)과 같은 규칙: 앞뒤 공백을 뺀 뒤 SHA-256 hex. */
export async function keyHash(key: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(key.trim()))
  return Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, '0')).join('')
}

// ── /prefs 문서(Worker _sanitizePrefs 가 남기는 모양) ─────────────────
// 화면 모드(theme) · 금액 단위(unit) · 90일 자동 강등(autoQuiet)은 기기마다 따로다(명세 S9) — 문서에 싣지 않고, 받을 때도 이 기기 값을 둔다.
// Worker 는 빠진 theme · unit 을 기본값으로 채워 저장하지만 fromServer 가 읽지 않는다. 등락 색(updown)은 모든 기기가 같다.
export type WatchItem = { id: string; kind: 'indicator' | 'stock'; addedAt: string | null }
export type SyncedSettings = Omit<Settings, 'unit' | 'autoQuiet'>
export type PrefsBody = {
  watch: WatchItem[]
  alerts: AlertCond[]
  settings: SyncedSettings
  scenarios: { name: string; inputs: Record<string, unknown> }[]
}
export type PrefsDoc = PrefsBody & { v: 1 | 2; updatedAt: string | null }

/** 설정에서 기기마다 따로인 칸을 뺀다. */
export function syncedOf(s: Settings): SyncedSettings {
  const { unit: _u, autoQuiet: _a, ...rest } = s
  return rest
}

/** 이 기기 쪽 모양 — 저장소 세 곳을 모은 것. 보유(portfolioV1)·스냅샷·원장은 여기 없으므로 서버로 갈 길이 없다. */
export type Local = {
  watch: string[]                                            // econ_watch_v1 (lib/watch.ts)
  alerts: AlertCond[]                                        // econPrefsV1.alerts
  settings: SyncedSettings                                   // econPrefsV1.settings 가운데 기기마다 따로인 칸을 뺀 것(등락 색 · 조용한 시간 · 꾸러미 · 채널 · 브리핑 …)
  scenarios: ({ name: string } & Record<string, unknown>)[]  // econ_scenarios_v1 (렌즈 「만약에」 저장)
}

/** 관심 id 의 종류: 종목 코드는 숫자로 시작하는 6자리(005930·0035S0), 지표 id 는 영문으로 시작한다(kospi·usdkrw·C2). */
export const watchKind = (id: string): WatchItem['kind'] => (/^\d[0-9A-Z]{5}$/.test(id) ? 'stock' : 'indicator')

/**
 * 이 기기 → 서버 문서. 관심의 담은 때(addedAt)는 직전에 본 서버 문서에서 가져오고, 처음 담은 것만 now.
 * 시나리오는 이름만 따로 두고 나머지 칸(start·dir·depth·at)을 inputs 로 묶는다.
 */
export function toServer(l: Local, prev: PrefsDoc | null, now: string): PrefsBody {
  const added = new Map((prev?.watch ?? []).map(w => [w.id, w.addedAt]))
  return {
    watch: l.watch.map(id => ({ id, kind: watchKind(id), addedAt: added.get(id) ?? now })),
    alerts: l.alerts,
    settings: l.settings,
    scenarios: l.scenarios.map(({ name, ...inputs }) => ({ name, inputs })),
  }
}

/** 서버 문서 → 이 기기. 조건 · 설정은 v2 로 바꿔 읽는다(v1 조건은 사전 사건으로, 모르는 값은 기본값 — prefsV2.ts). 기기마다 따로인 칸은 버린다. */
export function fromServer(d: Partial<PrefsDoc>): Local {
  const arr = <T,>(v: T[] | undefined) => (Array.isArray(v) ? v : [])
  const p = upgradePrefs(d)
  return {
    watch: arr(d.watch).map(w => w.id),
    alerts: p.alerts,
    settings: syncedOf(p.settings),
    scenarios: arr(d.scenarios).map(x => ({ ...x.inputs, name: x.name })),
  }
}

// ── 요청 한 번 ─────────────────────────────────────────
export type Reply = { status: number; doc?: PrefsDoc; error?: string; field?: string }

/**
 * GET(put 없음) · PUT /prefs 한 번. 네트워크 실패는 status 0.
 * If-Match 는 마지막으로 본 updatedAt — 서버에 저장본이 없을 때는 'null'(README 「PUT /prefs」).
 * keepalive = 탭을 숨기거나 닫는 순간 보내기(응답을 못 받을 수 있다).
 */
export async function prefsCall(hash: string, put?: { body: PrefsBody; ifMatch: string | null; keepalive?: boolean }): Promise<Reply> {
  const headers: Record<string, string> = { 'X-Sync-Key-Hash': hash }
  if (put) { headers['content-type'] = 'application/json'; headers['If-Match'] = put.ifMatch ?? 'null' }
  try {
    const r = await fetch(`${WORKER}/prefs`, {
      method: put ? 'PUT' : 'GET', headers, cache: 'no-store',
      body: put ? JSON.stringify(put.body) : undefined,
      keepalive: !!put?.keepalive, signal: put?.keepalive ? undefined : AbortSignal.timeout(15_000),
    })
    const j = await r.json().catch(() => ({}))
    return r.ok ? { status: r.status, doc: j } : { status: r.status, error: j?.error, field: j?.field }
  } catch { return { status: 0, error: 'network' } }
}

/**
 * 동기화 키가 맞는지만 묻는다 — POST /sync-key 에 newKeyHash 를 싣지 않으면 Worker 는 아무것도 바꾸지 않는다(PinGate 「PIN 잊음」).
 * 돌려주는 값 = 맞으면 200, 아니면 HTTP 상태(401 키 틀림 · 429 요청 많음 · 503 서버에 키 없음), 2xx 인데 ok:true 없음 -1, 네트워크 실패 0.
 */
export async function syncKeyCheck(hash: string): Promise<number> {
  try {
    const r = await fetch(`${WORKER}/sync-key`, {
      method: 'POST', headers: { 'content-type': 'application/json', 'X-Sync-Key-Hash': hash }, cache: 'no-store',
      body: '{}', signal: AbortSignal.timeout(15_000),
    })
    if (!r.ok) return r.status
    // 2xx 인데 본문에 ok:true 가 없으면 확인된 것이 아니다(중간 장비 · 다른 응답) — 이때 PIN 을 지우면 안 된다
    const j = await r.json().catch(() => ({}))
    return j?.ok === true ? 200 : -1
  } catch { return 0 }
}

/** 키 바꾸기 결과 — status 200 바뀜 · 400(error weak_new_key · use_new_key) · 401 지금 키 틀림 · 429 · 2xx 인데 ok:true 없음 -1 · 네트워크 실패 0. */
export type KeyChange = { status: number; error?: string }

/**
 * 동기화 키 바꾸기(명세 B5 계약) — 본문 { currentKey, newKey } 에 둘 다 원문을 싣는다(TLS 안, 해시 머리 없음).
 * 서버가 SHA-256(currentKey 앞뒤 공백 뺀 것)을 기대 해시와 견주고, 새 키(공백 뺀 것)가 12자 이상 · 지금 키와 다를 때만
 * SHA-256(새 키)를 저장한다. 해시만 가진 사람은 바꿀 수 없다(옛 계약 newKeyHash 는 400 use_new_key).
 */
export async function syncKeyChange(currentKey: string, newKey: string): Promise<KeyChange> {
  try {
    const r = await fetch(`${WORKER}/sync-key`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, cache: 'no-store',
      body: JSON.stringify({ currentKey, newKey }), signal: AbortSignal.timeout(15_000),
    })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) return { status: r.status, error: j?.error }
    return { status: j?.ok === true ? 200 : -1 }
  } catch { return { status: 0, error: 'network' } }
}

// ── /portfolio — 보유는 암호 덩어리(e2e.ts)로만 오간다 ─────────────────
// GET  헤더 X-Sync-Key-Hash → { ok, alerts, settings, tracking, encHoldings, updatedAt }. encHoldings 는 KV portfolio:encHoldings.
//      alerts = 현행 화면의 알림 조건(공개 저장소 alerts_config.json 의 내용 — 사이트에는 올라가지 않으므로 이 길로만 읽는다). 「현행 조건 가져오기」가 쓴다.
// POST 본문 { keyHash, encHoldings } → KV 에 덩어리만 쓴다. alerts·settings·tracking 은 빼면 Worker 가 저장본을 그대로 두고
//      공개 파일(alerts_config.json)도 건드리지 않는다 — 알림 조건은 /prefs 로만 오가고, 보유 종목 목록(tracking)도 공개 파일에 실리지 않는다.
export type PortfolioReply = { ok: boolean; status: number; enc?: EncBlob | null; alerts?: unknown[]; error?: string }

export async function portfolioGet(hash: string): Promise<PortfolioReply> {
  try {
    const r = await fetch(`${WORKER}/portfolio`, { headers: { 'X-Sync-Key-Hash': hash }, cache: 'no-store', signal: AbortSignal.timeout(20_000) })
    const j = await r.json().catch(() => ({}))
    return r.ok && j?.ok ? { ok: true, status: r.status, enc: j.encHoldings ?? null, alerts: Array.isArray(j.alerts) ? j.alerts : [] } : { ok: false, status: r.status, error: j?.error }
  } catch { return { ok: false, status: 0, error: 'network' } }
}

export async function portfolioPost(hash: string, enc: EncBlob): Promise<PortfolioReply> {
  try {
    const r = await fetch(`${WORKER}/portfolio`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, cache: 'no-store',
      body: JSON.stringify({ keyHash: hash, encHoldings: enc }), signal: AbortSignal.timeout(20_000),
    })
    const j = await r.json().catch(() => ({}))
    return r.ok && j?.ok ? { ok: true, status: r.status } : { ok: false, status: r.status, error: j?.error }
  } catch { return { ok: false, status: 0, error: 'network' } }
}
