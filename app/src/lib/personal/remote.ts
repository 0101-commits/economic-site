// Worker 와 주고받는 것 중 순수한 부분 — 주소 · 동기화 키 해시 · /prefs 문서와 이 기기 저장소 모양 사이 변환 · GET/PUT 한 번.
// 저장소(localStorage)·화면을 만지지 않으므로 node --test 로 바로 돌린다(remote.test.ts). 저장소 쪽 흐름은 sync.ts.
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(calc.ts 와 같은 규칙).
import type { AlertCond, Settings } from './store'
import type { Theme } from '../theme'
import type { EncBlob } from './e2e'

/** Worker 주소. 배포 화면의 보안 정책(vite.config.ts connect-src)이 이 주소 하나만 열어 두므로 바꿔 끼우는 설정은 두지 않는다. */
export const WORKER = 'https://ecom-dashboard-proxy.e-hcg.workers.dev'

/** 동기화 키 → 서버가 비교하는 해시. 현행 화면(js/app2.js pfSetSyncKey)과 같은 규칙: 앞뒤 공백을 뺀 뒤 SHA-256 hex. */
export async function keyHash(key: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(key.trim()))
  return Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, '0')).join('')
}

// ── /prefs 문서(Worker _sanitizePrefs 가 남기는 모양) ─────────────────
export type WatchItem = { id: string; kind: 'indicator' | 'stock'; addedAt: string | null }
export type PrefsBody = {
  watch: WatchItem[]
  alerts: AlertCond[]
  settings: Settings & { theme: Theme }
  scenarios: { name: string; inputs: Record<string, unknown> }[]
}
export type PrefsDoc = PrefsBody & { v: 1; updatedAt: string | null }

/** 이 기기 쪽 모양 — 저장소 네 곳을 모은 것. 보유(portfolioV1)·스냅샷·원장은 여기 없으므로 서버로 갈 길이 없다. */
export type Local = {
  watch: string[]                                            // econ_watch_v1 (lib/watch.ts)
  alerts: AlertCond[]                                        // econPrefsV1.alerts
  settings: Settings                                         // econPrefsV1.settings (등락 색 updown · 금액 단위 · 방해 금지)
  theme: Theme                                               // econNextTheme_v1 (lib/theme.ts)
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
    settings: { theme: l.theme, updown: l.settings.updown, unit: l.settings.unit, quiet: l.settings.quiet },
    scenarios: l.scenarios.map(({ name, ...inputs }) => ({ name, inputs })),
  }
}

/** 서버 문서 → 이 기기. 모르는 값은 서버 기본값과 같은 첫 값(system·kr·man)으로. */
export function fromServer(d: Partial<PrefsDoc>): Local {
  const s: Partial<PrefsBody['settings']> = d.settings ?? {}
  const arr = <T,>(v: T[] | undefined) => (Array.isArray(v) ? v : [])
  return {
    watch: arr(d.watch).map(w => w.id),
    alerts: arr(d.alerts),
    settings: { updown: s.updown === 'us' ? 'us' : 'kr', unit: s.unit === 'won' ? 'won' : 'man', quiet: s.quiet ?? null },
    theme: s.theme === 'light' || s.theme === 'dark' ? s.theme : 'system',
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

// ── /portfolio — 보유는 암호 덩어리(e2e.ts)로만 오간다 ─────────────────
// GET  헤더 X-Sync-Key-Hash → { ok, alerts, settings, tracking, encHoldings, updatedAt }. encHoldings 는 KV portfolio:encHoldings.
// POST 본문 { keyHash, alerts, encHoldings } → KV 에 덩어리를 쓰고, alerts_config.json(공개 파일)을 다시 커밋한다.
//      Worker 는 POST 마다 그 파일의 alerts 를 본문 값으로 바꿔 쓴다(빼면 지워진다). 그래서 방금 GET 으로 받은 alerts 를 그대로 돌려준다.
//      tracking·settings 는 빼면 서버가 그대로 둔다 — 보유 종목 목록(tracking)이 공개 파일에 실리지 않도록 보내지 않는다.
export type PortfolioReply = { ok: boolean; status: number; enc?: EncBlob | null; alerts?: unknown[]; error?: string }

export async function portfolioGet(hash: string): Promise<PortfolioReply> {
  try {
    const r = await fetch(`${WORKER}/portfolio`, { headers: { 'X-Sync-Key-Hash': hash }, cache: 'no-store', signal: AbortSignal.timeout(20_000) })
    const j = await r.json().catch(() => ({}))
    return r.ok && j?.ok ? { ok: true, status: r.status, enc: j.encHoldings ?? null, alerts: Array.isArray(j.alerts) ? j.alerts : [] } : { ok: false, status: r.status, error: j?.error }
  } catch { return { ok: false, status: 0, error: 'network' } }
}

export async function portfolioPost(hash: string, enc: EncBlob, alerts: unknown[]): Promise<PortfolioReply> {
  try {
    const r = await fetch(`${WORKER}/portfolio`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, cache: 'no-store',
      body: JSON.stringify({ keyHash: hash, alerts, encHoldings: enc }), signal: AbortSignal.timeout(20_000),
    })
    const j = await r.json().catch(() => ({}))
    return r.ok && j?.ok ? { ok: true, status: r.status } : { ok: false, status: r.status, error: j?.error }
  } catch { return { ok: false, status: 0, error: 'network' } }
}
