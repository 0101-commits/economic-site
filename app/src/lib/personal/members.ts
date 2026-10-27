// 멤버 관리 화면(Members.tsx)의 순수한 부분 — Worker 오류 → 짧은 우리말 · 마지막 접속 글 · 카톡에 보낼 글. node --test 로 바로 돈다(members.test.ts).
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(calc.ts 와 같은 규칙).

export type Member = { uid: string; name: string; role: 'owner' | 'member'; status: 'active' | 'paused'; lastSeenDay: string | null; pushCount: number }

const SITE = 'https://ecom-terminal.pages.dev'

/** 오류 답 → 화면 글. error 가 있으면 그것을 먼저 보고, 없으면 상태로 고른다. */
export function adminErrText(r: { status: number; error?: string }): string {
  switch (r.error) {
    case 'owner_only': return '마스터만 할 수 있습니다.'
    case 'not_migrated': return '멤버 기능이 아직 준비되지 않았습니다.'
    case 'bad_name': return '이름은 1~20자로 적어 주세요.'
    case 'bad_patch': return '바꿀 내용이 맞지 않습니다.'
    case 'owner_unpausable': return '마스터는 멈출 수 없습니다.'
  }
  if (r.status === 0) return 'ecom에 닿지 못했습니다. 잠시 뒤 다시 해 보세요.'
  if (r.status === 404) return '그런 멤버가 없습니다. 목록을 다시 불러옵니다.'
  if (r.status === 429) return '요청이 많습니다. 1분 뒤 다시 하세요.'
  if (r.status === 401) return '앱키가 맞지 않습니다. 앱키로 다시 들어와 주세요.'
  if (r.status === 403) return '이 앱키로는 할 수 없습니다(멈춤 상태이거나 마스터가 아닙니다).'
  return `ecom이 받지 않았습니다(${r.error ?? r.status}).`
}

/** 마지막 접속 — 오늘이면 「오늘」, 아니면 「M/D」, 값이 없으면 「없음」. day 는 'YYYY-MM-DD'(한국 날짜), today 도 같은 모양. */
export function lastSeenText(day: string | null | undefined, today: string): string {
  if (typeof day !== 'string') return '없음'
  const m = /^\d{4}-(\d{2})-(\d{2})$/.exec(day)
  if (!m) return '없음'
  if (day === today) return '오늘'
  return `${Number(m[1])}/${Number(m[2])}`
}

/** 어디에 무엇이 저장되는지(명세 8절) — 카톡에 보낼 글과 입장 화면이 같이 쓴다. */
export const STORAGE_NOTE = '관심 종목·알림 조건은 ecom에 저장되며 운영자가 볼 수 있습니다. 보유는 본인 앱키로 잠겨 운영자도 볼 수 없습니다.'

/** 카톡에 보낼 글 — 들어오는 길이 먼저, 저장 안내가 뒤에. */
export const kakaoText = (key: string): string => `ECOM 시장 화면 ${SITE} 에서 이 앱키로 들어오세요: ${key}\n${STORAGE_NOTE}`

/** 서버 목록 답 → Member[] (모양이 틀린 행은 버린다). 마스터를 맨 위로, 나머지는 받은 차례. */
export function parseMembers(doc: any): Member[] {   // eslint-disable-line @typescript-eslint/no-explicit-any
  const rows: any[] = Array.isArray(doc?.users) ? doc.users : []   // eslint-disable-line @typescript-eslint/no-explicit-any
  const out: Member[] = []
  for (const u of rows) {
    if (!u || typeof u.uid !== 'string' || typeof u.name !== 'string') continue
    out.push({
      uid: u.uid, name: u.name, role: u.role === 'owner' ? 'owner' : 'member', status: u.status === 'paused' ? 'paused' : 'active',
      lastSeenDay: typeof u.lastSeenDay === 'string' ? u.lastSeenDay : null, pushCount: Number.isFinite(u.pushCount) ? u.pushCount : 0,
    })
  }
  return out.sort((a, b) => (a.role === 'owner' ? 0 : 1) - (b.role === 'owner' ? 0 : 1))
}

/** 이름 다듬기 — 앞뒤 공백을 빼고 1~20자(글자 수)면 그 이름, 아니면 ''. */
export function cleanName(s: unknown): string {
  const t = String(s ?? '').trim()
  const n = [...t].length
  return n >= 1 && n <= 20 ? t : ''
}
