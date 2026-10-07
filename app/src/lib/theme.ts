// 밝음·어둠 선택. 'system' 이면 html[data-theme] 를 지워 기기 설정(prefers-color-scheme)을 따른다.
// 바꾸는 곳은 셋(머리 단추 · 설정 「표시」 · 동기화) — 모두 applyTheme 을 지나므로 useTheme 이 한 값을 본다.
import { useSyncExternalStore } from 'react'

export type Theme = 'system' | 'light' | 'dark'
const KEY = 'econNextTheme_v1'
const subs = new Set<() => void>()

export function readTheme(): Theme {
  try { const t = localStorage.getItem(KEY); return t === 'light' || t === 'dark' ? t : 'system' } catch { return 'system' }
}

export function applyTheme(t: Theme) {
  if (t === 'system') document.documentElement.removeAttribute('data-theme')
  else document.documentElement.dataset.theme = t
  try { if (t === 'system') localStorage.removeItem(KEY); else localStorage.setItem(KEY, t) } catch { /* 저장 못 해도 이번 화면엔 적용 */ }
  subs.forEach(f => f())
}

/** 지금 화면 모드. 이 탭에서 applyTheme 이 불리면 다시 그린다(다른 탭의 변경은 화면도 이 값도 따라가지 않는다 — 다음에 열 때). */
export const useTheme = (): Theme => useSyncExternalStore(f => { subs.add(f); return () => { subs.delete(f) } }, readTheme)
