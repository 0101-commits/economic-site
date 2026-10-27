// 사람별 이름으로 읽고 쓰는 기기 저장 함수 — store.ts 가 다시 내보낸다. 화면 모듈을 끌어오지 않아 node 시험이 불러올 수 있다.
// 이름은 부를 때마다 storeKey() 로 정한다(사람이 바뀌어도 낡은 이름이 남지 않게).
import { currentPerson, setPendingPerson, storeKey } from './who.ts'
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

/**
 * 이 기기 데이터 지우기 가운데 사람별 이름. 지금 사람의 것만 — 다른 사람 것은 그대로.
 * econ_fav_v1(옛 화면 즐겨찾기)은 마스터 것이라 마스터 · 나간 상태에서만 넣는다.
 */
export function scopedWipeNames(): string[] {
  const p = currentPerson()
  const names = [storeKey('portfolioV1'), storeKey('pfSnapshotsV1'), storeKey('pfLedgerV1'), storeKey('econ_watch_v1'), storeKey('econPrefsV1'), storeKey('econ_scenarios_v1')]
  return !p || p.role === 'owner' ? [...names, 'econ_fav_v1'] : names
}

const SCOPED_BASES = ['portfolioV1', 'pfSnapshotsV1', 'pfLedgerV1', 'econ_watch_v1', 'econPrefsV1', 'econ_scenarios_v1'] as const

/**
 * PIN 잊음에서 쓰는 전체 지우기 — 잠금 PIN 은 이 기기의 모든 사람 자료를 지켰으므로 한 사람 것이 아니라 전부 지운다.
 * 들어오는 중인 사람을 먼저 비우고, 여섯 이름과 `<이름>:<uid>` 로 시작하는 모든 키(localStorage 를 훑어 찾는다) ·
 * 옛 화면 즐겨찾기 · econMe_v1 · extra(사람과 무관한 지우기 키, store.wipeKeys 쪽)를 localStorage · sessionStorage 에서 지운다.
 * 하나라도 못 지우면 false.
 */
export function wipeAllPeople(extra: string[] = []): boolean {
  setPendingPerson(null)
  try {
    const names = new Set<string>([...SCOPED_BASES, 'econ_fav_v1', 'econMe_v1', ...extra])
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && SCOPED_BASES.some(b => k.startsWith(`${b}:`))) names.add(k)
    }
    for (const s of [localStorage, sessionStorage]) names.forEach(k => s.removeItem(k))
    return true
  } catch { return false }
}
