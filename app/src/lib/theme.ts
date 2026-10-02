// 밝음·어둠 선택. 'system' 이면 html[data-theme] 를 지워 기기 설정(prefers-color-scheme)을 따른다.
export type Theme = 'system' | 'light' | 'dark'
const KEY = 'econNextTheme_v1'

export function readTheme(): Theme {
  try { const t = localStorage.getItem(KEY); return t === 'light' || t === 'dark' ? t : 'system' } catch { return 'system' }
}

export function applyTheme(t: Theme) {
  if (t === 'system') document.documentElement.removeAttribute('data-theme')
  else document.documentElement.dataset.theme = t
  try { if (t === 'system') localStorage.removeItem(KEY); else localStorage.setItem(KEY, t) } catch { /* 저장 못 해도 이번 화면엔 적용 */ }
}
