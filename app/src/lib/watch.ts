// 관심 목록 — 지표 id(종목은 코드) 배열을 localStorage econ_watch_v1 에 둔다.
// 같은 화면의 별(띠 카드 · 표 행 · 관심 패널)이 한 저장소를 보고, 다른 탭에서 바꿔도 따라온다.
// ponytail: 이 기기 안에서만. /prefs 동기화는 후속.
import { useSyncExternalStore } from 'react'

const KEY = 'econ_watch_v1'
const subs = new Set<() => void>()
let cache: string[] | null = null

function read(): string[] {
  if (cache) return cache
  try {
    // 현행 화면(js/app4.js MY 레일)의 즐겨찾기 econ_fav_v1 도 같은 지표 id 배열이다 — 새 화면을 처음 열면 이어받는다(같은 origin 이라 저장소가 같다).
    const raw = localStorage.getItem(KEY) ?? localStorage.getItem('econ_fav_v1') ?? '[]'
    const v = JSON.parse(raw)
    cache = Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
  } catch { cache = [] }
  return cache
}

function write(ids: string[]) {
  cache = ids
  try { localStorage.setItem(KEY, JSON.stringify(ids)) } catch { /* 저장 못 해도 이번 화면엔 남는다 */ }
  subs.forEach(f => f())
}

window.addEventListener('storage', e => { if (e.key === KEY) { cache = null; subs.forEach(f => f()) } })

const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f) } }

export function useWatch() {
  const ids = useSyncExternalStore(subscribe, read)
  return {
    ids,
    has: (id: string) => ids.includes(id),
    toggle: (id: string) => write(ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id]),
  }
}
