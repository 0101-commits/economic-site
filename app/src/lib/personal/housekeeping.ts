// 알림 자동 정리 — 순수 함수만(node --test, housekeeping.test.ts). 저장·호출은 store.ts tidyAlerts(앱이 뜰 때 한 번).
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다.
//
// 규칙(기획서 7장 「동기화 · 자동 정리」). 지우지는 않는다.
//   180일 조용 「한 번」 조건이 180일 동안 울리지 않으면 꺼짐으로 내리고, 행에 「180일 조용 · 꺼짐」.
//               마지막 = 만든 때(id 'p'+시각) · 다시 켠 때(armedAt) · 원장에서 본 마지막 울림 · 이 기록을 처음 쓴 때 중 가장 늦은 것.
//               원장 최신판은 7일치뿐이라 본 울림을 ring 에 쌓아 둔다.
//   90일 미열람 알림 화면을 90일 동안 안 열면 꾸러미를 「조용히」로 내리고 demoted 를 찍는다 — 알림 화면이 다음에 열릴 때 한 줄로 알리고 지운다.
//               설정 › 고급에서 끌 수 있다(settings.autoQuiet = false — 이 기기만).
import type { Prefs } from './store'
import { setPackage } from './prefsV2.ts'

/** 이 기기 기록. since = 처음 정리한 때(ms) · ring = 조건 id → 마지막으로 본 울림(ms) · off = 자동으로 끈 조건 id · demoted = 꾸러미를 내린 때(ms, 알린 뒤 지움). */
export type Hk = { since?: number; ring?: Record<string, number>; off?: string[]; demoted?: number }

export const DAY = 86_400_000
const ms = (iso: unknown) => { const t = Date.parse(String(iso ?? '')); return Number.isNaN(t) ? 0 : t }
/** condId 가 만든 id('p' + 만든 시각 36진 + 임의 6자)의 만든 시각. 모양이 다르면 0. */
export const createdAt = (id: string) => (/^p[0-9a-z]+$/.test(id) && id.length > 7 ? parseInt(id.slice(1, -6), 36) || 0 : 0)

export function housekeep(p: Prefs, hk: Hk, now: number, seen: number, rows: { cond?: unknown; ts?: unknown }[]) {
  const since = hk.since ?? now
  const ring: Record<string, number> = { ...hk.ring }
  for (const r of rows) if (typeof r?.cond === 'string') ring[r.cond] = Math.max(ring[r.cond] ?? 0, ms(r.ts))
  const off = new Set(hk.off ?? [])
  let changed = false
  const alerts = p.alerts.map(a => {
    if (a.repeat !== 'once' || !a.enabled) return a
    const last = Math.max(createdAt(a.id), ms(a.armedAt), ring[a.id] ?? 0, since)
    if (now - last < 180 * DAY) return a
    changed = true
    off.add(a.id)
    return { ...a, enabled: false }
  })
  let settings = p.settings
  let demoted = hk.demoted
  if (settings.autoQuiet !== false && now - Math.max(seen, since) >= 90 * DAY && settings.package !== 'quiet') {
    settings = setPackage(settings, 'quiet')
    demoted = now
    changed = true
  }
  const ids = new Set(alerts.map(a => a.id))
  const keep = Object.fromEntries(Object.entries(ring).filter(([id]) => ids.has(id)))
  return {
    prefs: changed ? { ...p, alerts, settings } : p,
    hk: { since, ring: keep, off: [...off].filter(id => ids.has(id)), ...(demoted ? { demoted } : {}) } as Hk,
    changed,
  }
}
