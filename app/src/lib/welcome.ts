// 입장 화면(screens/Welcome.tsx)과 입장 관문(App.tsx Shell)이 쓰는 순수 함수 — node --test 로 시험하려고 .ts 로 둔다.

/** 입장 뒤 돌아갈 곳. `/` 로 시작하는 앱 안 경로만 받고(//x · /\x · 바깥 주소 · 입장 화면 자신은 `/`). */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return '/'
  if (/^\/welcome(?:[?#/]|$)/.test(next)) return '/'
  return next
}

/** 입장 화면으로 보낸 까닭 — paused = 서버가 멈춤(403)으로 답함 · lost = 키가 안 맞아(401) 끊김(재발급 · 삭제). */
export type Why = 'paused' | 'lost'
const WHY_TEXT: Record<Why, string> = {
  paused: '멈춘 키입니다. 모임 운영자에게 문의해 주세요.',
  lost: '키가 바뀌었거나 지워졌습니다. 운영자에게 새 키를 받으세요',
}
/** 주소의 why → 입장 화면 첫 줄. 모르는 값 · 없음은 ''. */
export function whyText(why: string | null): string {
  return why === 'paused' || why === 'lost' ? WHY_TEXT[why] : ''
}

/**
 * 입장 관문: 지금 화면에서 보낼 곳(그대로 두면 null). 입장 화면 자신은 막지 않는다.
 * 키 해시가 없으면 입장 화면(401 로 끊겼으면 why=lost), 멈춘 사람이면 why=paused — 기기 기록은 건드리지 않고 보내기만 한다.
 */
export function gateRedirect(s: { path: string; query: string; hash: boolean; paused: boolean; lost: boolean }): string | null {
  if (s.path === '/welcome') return null
  const why: Why | null = !s.hash ? (s.lost ? 'lost' : null) : s.paused ? 'paused' : null
  if (s.hash && !why) return null
  return `/welcome?${why ? `why=${why}&` : ''}next=${encodeURIComponent(s.path + s.query)}`
}

/** 입장 화면을 열 때: 이미 들어와 있는(키 해시가 있고 멈추지 않은) 기기는 홈으로 — 나가기 없이 다른 사람으로 덮어 들어가지 않게. */
export const welcomeAway = (s: { hash: boolean; paused: boolean }): boolean => s.hash && !s.paused
