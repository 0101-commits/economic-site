// 내 자산·알림·설정이 같이 쓰는 입력 조각. 토큰 클래스만 쓴다.
import type { ReactNode } from 'react'
import dictJson from '../../lib/alerts/dict.json'
import type { Level } from '../../lib/personal/store'

export const INPUT = 'h-9 w-full min-w-0 px-2 rounded-btn border border-line bg-bg text-14 text-ink-1 placeholder:text-ink-3 disabled:opacity-60'
export const BTN = 'h-9 px-3 rounded-btn text-13 bg-accent text-on-accent border border-accent cursor-pointer disabled:opacity-60 whitespace-nowrap'
export const BTN2 = 'h-9 px-3 rounded-btn text-13 border border-line bg-card text-ink-2 hover:text-ink-1 cursor-pointer disabled:opacity-60 whitespace-nowrap'
export const DIR_TEXT = { up: 'text-up', down: 'text-down', flat: 'text-ink-2' } as const

/** 이름표가 위에 붙은 입력 칸 한 개. */
export function Field({ label, children, className = '' }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={`flex flex-col gap-1 min-w-0 ${className}`}>
      <span className="text-12 text-ink-2">{label}</span>
      {children}
    </label>
  )
}

/** 켜고 끄는 스위치(브라우저 기본 checkbox 에 role=switch). */
export function Switch({ on, onChange, label, disabled }: { on: boolean; onChange?: (v: boolean) => void; label: ReactNode; disabled?: boolean }) {
  return (
    <label className={`inline-flex items-center gap-2 text-13 ${disabled ? 'text-ink-3' : 'text-ink-1'}`}>
      <input type="checkbox" role="switch" checked={on} disabled={disabled} onChange={e => onChange?.(e.target.checked)} className="size-4 accent-accent" />
      {label}
    </label>
  )
}

/** 0~100% 가로 막대 한 줄: 이름 | 막대 | 값. tone 은 막대 채움(검정 = 나, 회색 = 비교). */
export function ShareBar({ label, pct, tone = 'ink-1' }: { label: string; pct: number | null; tone?: 'ink-1' | 'ink-3' }) {
  const w = pct == null ? 0 : Math.max(0, Math.min(100, pct))
  return (
    <li className="grid grid-cols-[4.5rem_minmax(0,1fr)_3.5rem] items-center gap-2 text-12">
      <span className="text-ink-2 whitespace-nowrap">{label}</span>
      <span className="relative h-3 rounded-chip bg-line overflow-hidden">
        <span aria-hidden className={`absolute inset-y-0 left-0 ${tone === 'ink-1' ? 'bg-ink-1' : 'bg-ink-3'}`} style={{ width: `${w}%` }} />
      </span>
      <span className="num text-right text-ink-1">{pct == null ? '—' : `${pct.toFixed(1)}%`}</span>
    </li>
  )
}

/** 등급 이름(사전 dict.json — 이름은 사전에서만). */
export const LV = Object.fromEntries(dictJson.levels.map(l => [l.id, l.name])) as Record<Level, string>

/** 등급 알약: 경보만 검정 채움, 알림은 진한 테두리, 안내 · 시황은 옅은 테두리. 글자는 사전 이름(시황 = 브리핑). */
export function LevelPill({ level }: { level: Level | 'brief' }) {
  const tone = level === 'alarm' ? 'bg-accent text-on-accent border-accent' : level === 'alert' ? 'border-ink-1 text-ink-1' : 'border-line text-ink-3'
  return <span className={`inline-flex shrink-0 items-center h-5 px-2 rounded-chip border text-11 whitespace-nowrap ${tone}`}>{level === 'brief' ? '시황' : LV[level]}</span>
}

/** 이름표가 위에 붙은 한 묶음(고르기 줄 · 스위치 따위를 담는다). */
export function Row({ label, children }: { label: string; children: ReactNode }) {
  return <div className="min-w-0"><p className="m-0 mb-1 text-12 text-ink-2">{label}</p>{children}</div>
}
