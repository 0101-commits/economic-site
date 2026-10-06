// 일봉 한 계열 — 새 조건 폼(Alerts.tsx)과 상세 벨 시트(BellSheet.tsx)가 세기별 「지난 1년 N회」를 셀 때 같이 쓴다.
// 원장 이력(events/history/<id>.json)이 있으면 그것, 없으면 지표 묶음의 1년 시계열. 둘 다 없으면 null.
import { loadIndicator, ROOT } from '../bundle'

export async function loadDaily(id: string): Promise<[string, number][] | null> {
  try {
    const r = await fetch(new URL(`events/history/${encodeURIComponent(id)}.json`, ROOT), { cache: 'no-cache' })
    if (r.ok) {
      const a = await r.json()
      if (Array.isArray(a) && a.length) return a.map((p: { date: string; value: number }) => [p.date, p.value])
    }
  } catch { /* 없으면 아래로 */ }
  return (await loadIndicator(id).catch(() => null))?.series ?? null
}
