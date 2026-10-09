// 사용 기록 — 이 기기에만, 횟수만. 어느 화면을 열고 어느 보기를 누르고 어느 패널을 접는지 세어 2주 뒤 화면 정리(P3)의 근거로 쓴다.
// localStorage econ_usage_v1 = { since, screens:{화면:n}, views:{키:n}, folds:{키:{open, close}}, more:{키:n} }.
// 값 · 종목 · 시각은 적지 않는다(시작일만). 서버로 보내지 않는다. 저장소가 막혀 있으면 조용히 건너뛴다.
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(node --test 로 바로 돈다 — usage.test.ts).

export const USAGE_KEY = 'econ_usage_v1'

export type Usage = {
  since: string
  screens: Record<string, number>
  views: Record<string, number>
  folds: Record<string, { open: number; close: number }>
  more: Record<string, number>
}

/** 화면 열쇠 → 이름. 이 목록 밖의 경로(없는 화면)는 「그 밖」 하나로 센다. 시장 자산군 이름은 screens/Market.tsx ASSETS 와 같다(usage.test.ts 가 대조). */
export const SCREENS: readonly (readonly [string, string])[] = [
  ['/', '홈'],
  ['/market?a=kr', '시장 · 국내'], ['/market?a=global', '시장 · 해외'], ['/market?a=fxrate', '시장 · 환율금리'], ['/market?a=commod', '시장 · 원자재'],
  ['/market?a=macro', '시장 · 거시'], ['/market?a=flow', '시장 · 수급'], ['/market?a=realestate', '시장 · 부동산'],
  ['/lens', '렌즈'], ['/my', '내 자산'], ['/alerts', '알림'], ['/i', '지표 상세'], ['/settings', '설정'],
]
const KNOWN = new Set(SCREENS.map(s => s[0]))

/** 화면 열쇠: 경로, 시장은 자산군까지(a 가 없으면 국내), 지표 상세는 지표 id 를 떼어 /i 하나로(무엇을 봤는지는 적지 않는다). */
export function screenKey(pathname: string, search: string): string {
  const k = pathname.startsWith('/i/') ? '/i'
    : pathname === '/market' ? `/market?a=${new URLSearchParams(search).get('a') || 'kr'}`
      : pathname
  return KNOWN.has(k) ? k : '그 밖'
}

// 패널 열쇠(lib/fold.ts foldId)의 화면 자리에 지표 상세의 id 가 들어오면(i/us10y:흐름) 떼어 낸다
const scrub = (key: string) => key.replace(/^i\/[^:]*/, 'i')

const obj = (x: unknown) => (x && typeof x === 'object' && !Array.isArray(x) ? x : {})

/** 기록 전부. 없거나 깨졌으면 빈 기록(since = ''). */
export function readUsage(): Usage {
  try {
    const v = JSON.parse(localStorage.getItem(USAGE_KEY) ?? 'null')
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      return { since: typeof v.since === 'string' ? v.since : '', screens: obj(v.screens), views: obj(v.views), folds: obj(v.folds), more: obj(v.more) } as Usage
    }
  } catch { /* 깨진 기록은 새로 시작한다 */ }
  return { since: '', screens: {}, views: {}, folds: {}, more: {} }
}

/** 이 기기 날짜(YYYY-MM-DD). */
export function localDay(d = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function bump(edit: (u: Usage) => void): void {
  const u = readUsage()
  if (!u.since) u.since = localDay()
  edit(u)
  try { localStorage.setItem(USAGE_KEY, JSON.stringify(u)) } catch { /* 못 쓰면 이번 것은 세지 않는다 */ }
}

/** 한 번 센다 — screens = 화면 열기, views = 범위 · 보기 · 목차 누르기, more = 「더 보기」. */
export function countUse(kind: 'screens' | 'views' | 'more', key: string): void {
  bump(u => { const k = scrub(key); u[kind][k] = (Number(u[kind][k]) || 0) + 1 })
}

/** 패널 접기(open=false) · 펼치기(open=true)를 센다. key = lib/fold.ts foldId. */
export function countFold(key: string, open: boolean): void {
  bump(u => {
    const k = scrub(key), f = obj(u.folds[k]) as { open?: unknown; close?: unknown }
    u.folds[k] = { open: (Number(f.open) || 0) + (open ? 1 : 0), close: (Number(f.close) || 0) + (open ? 0 : 1) }
  })
}

export function clearUsage(): void {
  try { localStorage.removeItem(USAGE_KEY) } catch { /* 저장소가 막혀 있으면 지울 것도 없다 */ }
}

/** 횟수 많은 순 상위 n(같으면 이름 순). */
export const topCounts = (m: Record<string, number>, n: number): [string, number][] =>
  Object.entries(m).filter(([, c]) => Number(c) > 0).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'ko')).slice(0, n)
