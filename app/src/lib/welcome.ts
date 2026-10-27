// 입장 화면(screens/Welcome.tsx)이 쓰는 순수 함수 — node --test 로 시험하려고 .ts 로 둔다.

/** 입장 뒤 돌아갈 곳. `/` 로 시작하는 앱 안 경로만 받고(//x · /\x · 바깥 주소 · 입장 화면 자신은 `/`). */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return '/'
  if (/^\/welcome(?:[?#/]|$)/.test(next)) return '/'
  return next
}
