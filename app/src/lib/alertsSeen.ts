// 헤더 벨의 안 읽음 점 — 원장 최신판(events/latest.json)의 가장 늦은 ts 가 마지막으로 알림 화면을 연 때보다 뒤면 켠다.
// 마지막으로 연 때는 localStorage econAlertsSeen_v1(ISO 문자열). 저장소가 막혀 있으면 「본 적 없음」으로 읽고 쓰기는 조용히 건너뛴다.
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(node --test 로 바로 돈다 — alertsSeen.test.ts).

export const SEEN_KEY = 'econAlertsSeen_v1'

const ms = (v: unknown): number => {
  const t = typeof v === 'number' ? v : Date.parse(String(v ?? ''))
  return Number.isNaN(t) ? 0 : t
}

/** 원장 행들 가운데 가장 늦은 ts(ms). 배열이 아니거나 ts 가 하나도 없으면 0. */
export function latestTs(rows: unknown): number {
  return Array.isArray(rows) ? rows.reduce<number>((m, r) => Math.max(m, ms((r as { ts?: unknown } | null)?.ts)), 0) : 0
}

/** 안 읽은 알림이 있나: 가장 늦은 ts > 마지막으로 본 때. seen 이 없거나 읽을 수 없으면 본 적 없음(0)이다. */
export const hasUnseen = (rows: unknown, seen: unknown): boolean => latestTs(rows) > ms(seen)

export function readSeen(): string | null {
  try { return localStorage.getItem(SEEN_KEY) } catch { return null }
}

/** 지금을 「마지막으로 본 때」로 적는다. 돌려주는 값은 화면 상태용(저장이 막혀도 이번 화면에선 읽은 것이 된다). */
export function markSeen(now = Date.now()): string {
  const iso = new Date(now).toISOString()
  try { localStorage.setItem(SEEN_KEY, iso) } catch { /* 저장 못 하면 다음에 열 때 점이 다시 보일 뿐 */ }
  return iso
}
