// 현행 화면 주소(?p=화면&t=탭) → 새 화면 해시 주소. 별칭표의 단일 원천 — 문서 docs/superpowers/specs/2026-10-02-next-cutover-design.md §3 과 같다.
// 현행 북마크·알림 버튼이 /next/?p=… 로 들어오면 App 이 이 함수로 바꿔 연다. 모르는 화면은 홈.
const MARKET_TAB: Record<string, string> = { kr: 'kr', global: 'global', fx: 'fxrate', rate: 'fxrate', commodity: 'commod' }
const PAGE: Record<string, string> = {
  dashboard: '/', equity: '/market?a=kr', investor: '/market?a=kr&v=flows', realestate: '/market?a=realestate',
  merlens: '/lens', merblog: '/lens', lede: '/lens', portfolio: '/my', calendar: '/', settings: '/settings',
}

/** `?p=market&t=commodity` → `/market?a=commod`. p 가 없으면 null(현행 주소가 아니다). */
export function legacyToHash(search: string): string | null {
  const q = new URLSearchParams(search)
  const p = q.get('p')
  if (!p) return null
  const t = q.get('t')
  if (p === 'market') return `/market?a=${MARKET_TAB[t ?? ''] ?? 'kr'}`
  if (p === 'macro') return `/market?a=macro${t ? `&v=${encodeURIComponent(t)}` : ''}`
  return PAGE[p] ?? '/'
}
