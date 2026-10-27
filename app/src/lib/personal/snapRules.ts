// 스냅샷(하루 한 번 평가액 기록) 순수 규칙 — 한국 날짜 · 합치기 · 올릴지 정하기 · 서버 평문 모양. 저장소 · 네트워크를 만지지 않는다(snapRules.test.ts).
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(calc.ts 와 같은 규칙).
//
// 서버 평문(보유와 같은 열쇠로 잠근다 — Worker /snaps, 마스터 작업 scripts/master_snapshot.py 와 같은 모양)
//   { v:1, at:<ISO>, snaps:[{ d:'YYYY-MM-DD'(한국 날짜), ev:정수, ct:정수, src?:'close'|'app' }] }  날짜순 · 날짜당 한 칸 · 마지막 730건.
//   src 'close' = 마스터 작업이 남긴 그날 종가 기준 값, 'app' = 앱이 앱을 연 때의 시세로 남긴 값. 없으면(옛 화면 · 옛 판) app 과 같이 본다.
//
// 합치기(mergeSnaps): 날짜로 합친다. 같은 날짜는 close 가 이긴다 — close 끼리거나 close 가 없으면 앞 인자(이 기기 · 있던 것)를 남긴다. 날짜순, 끝에서 730건.
// 올릴지(decideSnaps): 합친 것이 서버 것과 다르면 올린다(서버에 없는 날짜가 있거나, close 아닌 날짜가 이 기기 값으로 남았을 때). 이 기기와 다르면 이 기기에 쓴다.
import type { Snap } from './calc.ts'

export type { Snap }
export const SNAP_MAX = 730

const KST = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' })
/** 한국 날짜 'YYYY-MM-DD' — 스냅샷 날짜는 이것으로 센다(UTC 로 세면 한국 오전 9시 전이 어제 칸에 들어간다). */
export const kstDate = (t: Date | number = new Date()): string => KST.format(t)

const DATE = /^\d{4}-\d{2}-\d{2}$/
const money = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v) : null)

/** 칸 하나를 다듬는다(모르는 칸 · 깨진 값은 버린다). 못 쓰는 칸이면 null. */
function clean(x: unknown): Snap | null {
  if (!x || typeof x !== 'object') return null
  const o = x as Record<string, unknown>
  const ev = money(o.ev), ct = money(o.ct)
  if (typeof o.d !== 'string' || !DATE.test(o.d) || ev == null || ct == null) return null
  return { d: o.d, ev, ct, ...(o.src === 'close' || o.src === 'app' ? { src: o.src } : {}) }
}

/** 합치기: 날짜별 하나 · close 우선(같으면 a = 있던 것) · 날짜순 · 끝에서 730건. */
export function mergeSnaps(a: Snap[], b: Snap[]): Snap[] {
  const m = new Map<string, Snap>()
  for (const x of [...a, ...b]) {
    const c = clean(x)
    if (!c) continue
    const cur = m.get(c.d)
    if (!cur || (c.src === 'close' && cur.src !== 'close')) m.set(c.d, c)
  }
  return [...m.values()].sort((p, q) => (p.d < q.d ? -1 : 1)).slice(-SNAP_MAX)
}

const norm = (a: Snap[]) => mergeSnaps(a, [])
/** 같은 목록인가(순서 · 칸 순서와 무관). */
export const snapsKey = (a: Snap[]): string => JSON.stringify(norm(a).map(s => [s.d, s.ev, s.ct, s.src ?? '']))
export const snapsEqual = (a: Snap[], b: Snap[]): boolean => snapsKey(a) === snapsKey(b)

/** 서버 평문으로 만들 문서. */
export const snapPlain = (snaps: Snap[], at: string): { v: 1; at: string; snaps: Snap[] } => ({ v: 1, at, snaps: norm(snaps) })

/** 서버에서 푼 평문 → 칸 목록(모양이 틀리면 Error('shape')). */
export function parseSnapPlain(v: unknown): Snap[] {
  const o = v as { snaps?: unknown } | null
  if (!o || typeof o !== 'object' || Array.isArray(o) || !Array.isArray(o.snaps)) throw new Error('shape')
  return norm(o.snaps as Snap[])
}

/** 이 기기 것(local)과 서버 것(server, 없으면 null)을 합쳐: 이 기기에 쓸지 · 서버에 올릴지. 올릴 것이 아무것도 없으면(합친 것이 비면) 올리지 않는다. */
export function decideSnaps(local: Snap[], server: Snap[] | null): { merged: Snap[]; writeLocal: boolean; push: boolean } {
  const merged = mergeSnaps(local, server ?? [])
  return { merged, writeLocal: !snapsEqual(merged, local), push: merged.length > 0 && !snapsEqual(merged, server ?? []) }
}
