// 입장 키 정규화 — Worker(cloudflare-worker/users.js normalizeEntryKey)와 같은 규칙. 두 곳의 시험 행도 문자 그대로 같다.
// 공백 · 하이픈을 빼고 대문자로 바꿔 ECOM + 12자(헷갈리는 0 O 1 I L 제외)이면 ECOM-XXXX-XXXX-XXXX, 아니면 앞뒤 공백만 뺀 원문(옛 동기화 키).
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(remote.ts · e2e.ts 가 가져다 쓴다).
const ENTRY_RE = /^ECOM[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{12}$/

export function normalizeEntryKey(raw: string): string {
  const s = String(raw == null ? '' : raw)
  const squeezed = s.replace(/[\s-]+/g, '').toUpperCase()
  if (ENTRY_RE.test(squeezed)) return `ECOM-${squeezed.slice(4, 8)}-${squeezed.slice(8, 12)}-${squeezed.slice(12, 16)}`
  return s.trim()
}
