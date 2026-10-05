import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/** 주소에 남기는 화면 상태 열쇠: 자산군 a · 보기 v · 기간 p · 모드 m · 접힘 f · 고른 지표 s · 알림 조건을 만들 지표 id(한 번 읽고 지운다) */
export type ViewKey = 'a' | 'v' | 'p' | 'm' | 'f' | 's' | 'id'

/**
 * 화면 상태를 주소 쿼리에 기록·복원한다. 바꿀 때는 기록을 쌓지 않고 덮어쓴다(replaceState) —
 * 뒤로 가기가 버튼 누른 횟수만큼 밀리지 않게.
 * 기본값과 같으면 주소에서 지운다(공유 주소를 짧게). allowed 를 주면 그 밖의 값은 기본값으로 읽는다.
 */
export function useViewParam<T extends string>(key: ViewKey, fallback: T, allowed?: readonly T[]): [T, (next: T) => void] {
  const [params, setParams] = useSearchParams()
  const raw = params.get(key) as T | null
  const value = raw != null && (!allowed || allowed.includes(raw)) ? raw : fallback
  const set = useCallback((next: T) => {
    setParams(prev => {
      const p = new URLSearchParams(prev)
      if (next === fallback) p.delete(key); else p.set(key, next)
      return p
    }, { replace: true })
  }, [key, fallback, setParams])
  return [value, set]
}
