// 일봉 한 계열 — 새 조건 폼(Alerts.tsx)과 상세 벨 시트(BellSheet.tsx)가 세기별 「지난 1년 N회」를 셀 때 같이 쓴다.
// 지표 묶음의 1년 시계열이 먼저, 없을 때만 원장 이력(events/history/<id>.json). 둘 다 없으면 null.
// 원장 이력은 시계열 없는 1점 지표(VKOSPI · 금 김프 · 운임 · LME 재고 · 시장 폭 · 업종 — scripts/alerts_v2/history_sink.py)에만 있다 —
// 이력부터 물으면 엔/원처럼 시계열이 있는 지표마다 404 가 났다(2026-10-12). 종목은 이력도 지표 시계열도 없어 아무것도 받지 않는다
// (loadIndicator 가 종목 id 로 시장 묶음을 전부 받던 것을 막는다).
import { loadIndicator, ROOT } from '../bundle'
import { isStockId } from '../detail'

export async function loadDaily(id: string): Promise<[string, number][] | null> {
  if (isStockId(id)) return null
  const series = (await loadIndicator(id).catch(() => null))?.series
  if (series?.length) return series
  try {
    const r = await fetch(new URL(`events/history/${encodeURIComponent(id)}.json`, ROOT), { cache: 'no-cache' })
    if (r.ok) {
      const a = await r.json()
      if (Array.isArray(a) && a.length) return a.map((p: { date: string; value: number }) => [p.date, p.value])
    }
  } catch { /* 이력도 없다 */ }
  return null
}
