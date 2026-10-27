// 사람별 이름으로 읽고 쓰는 기기 저장 함수 — store.ts 가 다시 내보낸다. 화면 모듈을 끌어오지 않아 node 시험이 불러올 수 있다.
// 이름은 부를 때마다 storeKey() 로 정한다(사람이 바뀌어도 낡은 이름이 남지 않게).
import { currentPerson, setPendingPerson, storeKey, type ScopedBase } from './who.ts'
import type { Holding, Snap } from './calc.ts'

export function read<T>(key: string, fallback: T): T {
  try { const v = JSON.parse(localStorage.getItem(key) || 'null'); return v ?? fallback } catch { return fallback }
}
/** 저장 실패(시크릿 창·용량 초과)는 false — 화면이 「저장 못 함」을 말해야 입력이 소리 없이 사라지지 않는다. */
export function write(key: string, v: unknown): boolean {
  try { localStorage.setItem(key, JSON.stringify(v)); return true } catch { return false }
}

export type Portfolio = { groups: { id: string; name: string }[]; items: Holding[]; alerts: unknown[]; [k: string]: unknown }
export function readPortfolio(): Portfolio {
  const p = read<Partial<Portfolio> | null>(storeKey('portfolioV1'), null)
  const items = Array.isArray(p?.items) ? p!.items.filter(x => x && typeof x.symbol === 'string') : []
  const groups = Array.isArray(p?.groups) && p!.groups.length ? p!.groups : [{ id: 'g_default', name: '기본 그룹' }]
  return { lastSync: null, ...p, groups, items, alerts: Array.isArray(p?.alerts) ? p!.alerts : [] }
}
export const writePortfolio = (p: Portfolio) => write(storeKey('portfolioV1'), p)

/** 스냅샷 목록. 깨진 칸(null · 날짜 없는 것)은 뺀다 — 다른 기기 · 옛 화면이 쓴 배열을 그대로 읽으므로. */
export const readSnaps = (): Snap[] => { const a = read<unknown>(storeKey('pfSnapshotsV1'), []); return Array.isArray(a) ? a.filter((s): s is Snap => !!s && typeof s.d === 'string') : [] }
export const writeSnaps = (a: Snap[]) => write(storeKey('pfSnapshotsV1'), a)

export type Ledger = { id: string; d: string; kind: 'div' | 'dep' | 'wd'; amt: number; memo?: string }
export const readLedger = (): Ledger[] => { const a = read<unknown>(storeKey('pfLedgerV1'), []); return Array.isArray(a) ? a : [] }
export const writeLedger = (a: Ledger[]) => write(storeKey('pfLedgerV1'), [...a].sort((x, y) => (x.d < y.d ? -1 : 1)).slice(-500))

const SCOPED_BASES: readonly ScopedBase[] = ['portfolioV1', 'pfSnapshotsV1', 'pfLedgerV1', 'econ_watch_v1', 'econPrefsV1', 'econ_scenarios_v1',
  'econHoldSync_v1', 'econSyncScope_v1', 'econPrefsSync_v1', 'econSearchRecentV1', 'econHoldQuotes_v1']

// ── 진 쪽 한 벌(…:prev) ─────────────────────────────────
// 이 기기와 다른 기기가 둘 다 바꿔 한쪽을 골랐을 때(syncRules.settle) 진 쪽을 이 기기에 한 벌 남긴다. 한 칸 — 다음 진 쪽이 덮는다.
// 모양 { side: 'device' | 'server', at: 진 쪽이 바뀐 때(모르면 null), savedAt, data | enc } — 보유는 portfolioV1 모양 그대로(data), 열 수 없는 덩어리는 enc.
export type PrevBase = 'portfolioV1' | 'econPrefsV1'
const PREV_BASES: readonly PrevBase[] = ['portfolioV1', 'econPrefsV1']
export const prevKey = (base: PrevBase) => `${storeKey(base)}:prev`
export function keepPrev(base: PrevBase, v: { side: 'device' | 'server'; at: string | null; data?: unknown; enc?: unknown }): boolean {
  return write(prevKey(base), { ...v, savedAt: new Date().toISOString() })
}

/**
 * 이 기기 데이터 지우기 가운데 사람별 이름. 지금 사람의 것만 — 다른 사람 것은 그대로.
 * econ_fav_v1(옛 화면 즐겨찾기)은 마스터 것이라 마스터 · 나간 상태에서만 넣는다.
 */
export function scopedWipeNames(): string[] {
  const p = currentPerson()
  const names = [...SCOPED_BASES.map(storeKey), ...PREV_BASES.map(prevKey)]
  return !p || p.role === 'owner' ? [...names, 'econ_fav_v1'] : names
}

/**
 * PIN 잊음에서 쓰는 전체 지우기 — 잠금 PIN 은 이 기기의 모든 사람 자료를 지켰으므로 한 사람 것이 아니라 전부 지운다.
 * 들어오는 중인 사람을 먼저 비우고, 사람별 이름들과 `<이름>:<uid>` 로 시작하는 모든 키(localStorage · sessionStorage 를 훑어 찾는다 —
 * 보유 시세 캐시는 sessionStorage 에 있다) · 옛 화면 즐겨찾기 · econMe_v1 · extra(사람과 무관한 지우기 키, store.wipeKeys 쪽)를 둘 다에서 지운다.
 * 하나라도 못 지우면 false.
 */
export function wipeAllPeople(extra: string[] = []): boolean {
  setPendingPerson(null)
  try {
    const names = new Set<string>([...SCOPED_BASES, 'econ_fav_v1', 'econMe_v1', ...extra])
    for (const s of [localStorage, sessionStorage]) {
      for (let i = 0; i < (s.length ?? 0); i++) {
        const k = s.key(i)
        if (k && SCOPED_BASES.some(b => k.startsWith(`${b}:`))) names.add(k)
      }
    }
    for (const s of [localStorage, sessionStorage]) names.forEach(k => s.removeItem(k))
    return true
  } catch { return false }
}
