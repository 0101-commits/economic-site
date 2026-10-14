// 「최근 본 것」 목록 다루기 — 순수 함수만(저장은 store.ts). 검색 · 오른쪽 패널이 읽고, 검색 고르기 · 상세 열기(Detail.tsx)가 적는다.
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다. node --test 로 바로 돌린다(recent.test.ts).

/** 한 줄: 이름 · 갈 곳(앱 안 주소 /i/<id> · 바깥 글 주소) · 갈래(지표 · 종목 · 화면 · 글 · 도구). */
export type Recent = { label: string; to: string; kind: string }
export const RECENT_MAX = 8

/** 저장본 → 목록. 깨진 칸(글자 아닌 to · label)은 빼고 앞 8개. */
export function recentList(a: unknown): Recent[] {
  if (!Array.isArray(a)) return []
  return a.filter((x): x is Recent => !!x && typeof x.to === 'string' && !!x.to && typeof x.label === 'string').slice(0, RECENT_MAX)
}

/**
 * r 를 맨 앞에 넣는다 — 같은 곳(to)은 하나만(앞으로 옮긴다), 8개 상한.
 * keepLabel = 이미 있던 줄의 이름을 남긴다(상세 열기는 id 만 알고 적는다 — 검색에서 고를 때 적힌 이름이 더 낫다).
 */
export function addRecent(list: unknown, r: Recent, keepLabel = false): Recent[] {
  const old = recentList(list)
  const had = old.find(x => x.to === r.to)
  return [keepLabel && had ? { ...r, label: had.label } : r, ...old.filter(x => x.to !== r.to)].slice(0, RECENT_MAX)
}
