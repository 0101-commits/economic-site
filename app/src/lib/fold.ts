// 패널 접기 기억 · 「더 보기」 행 수. 패널은 늘 펼친 채 시작하고, 사용자가 접은 것만 이 기기에 기억한다.
// 기억은 localStorage econ_fold_v1 = { "<화면>:<패널 제목>": true }. 펼치면 그 열쇠를 지운다. 저장소가 막혀 있으면 기억 없이 늘 펼침.
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(node --test 로 바로 돈다 — fold.test.ts).

export const FOLD_KEY = 'econ_fold_v1'

/**
 * 접기 기억 열쇠. 제목 끝의 범위 · 개수(「상승 · 코스피」 「업종 31」)는 떼어 같은 패널이 범위 · 자료 수와 무관하게 같은 열쇠를 갖게 한다.
 * 화면 = 경로(앞 / 없이, 홈은 home).
 */
export function foldId(path: string, title: string): string {
  const screen = path.replace(/^\/+/, '') || 'home'
  return `${screen}:${title.split(' · ')[0].replace(/\s*\d+$/, '').trim()}`
}

function readAll(): Record<string, true> {
  try {
    const v = JSON.parse(localStorage.getItem(FOLD_KEY) ?? '{}')
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {}
  } catch { return {} }
}

export const isFolded = (id: string): boolean => readAll()[id] === true

export function setFolded(id: string, folded: boolean): void {
  const all = readAll()
  if (folded) all[id] = true; else delete all[id]
  try { localStorage.setItem(FOLD_KEY, JSON.stringify(all)) } catch { /* 저장 못 해도 이번 화면엔 접힌 채 남는다 */ }
}

/** 「더 보기」 뒤로 숨는 행 수: 모바일(<980) 5행 · PC 10행까지 보인다. */
export const hiddenRows = (n: number, pc: boolean): number => Math.max(0, n - (pc ? 10 : 5))
