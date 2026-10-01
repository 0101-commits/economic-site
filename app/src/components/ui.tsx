// 공통 부품 — 화면은 이 부품과 토큰 클래스만 쓴다. 색 띠 상자·그림자·그라데이션 금지.
import { useEffect, useRef, type ReactNode, type KeyboardEvent } from 'react'
import { fmtNumber, fmtChange, changeDir, asOfKind, asOfLabel, kindFromState } from '../lib/format'

const DIR_TEXT = { up: 'text-up', down: 'text-down', flat: 'text-ink-2' } as const

/** 카드 상자. dense = 안쪽 여백 12(띠 카드처럼 좁은 칸), 기본 16. */
export function Card({ title, children, dense, className = '' }: { title?: ReactNode; children: ReactNode; dense?: boolean; className?: string }) {
  return (
    <section className={`bg-card border border-line rounded-card ${dense ? 'p-3' : 'p-4'} ${className}`}>
      {title != null && <h3 className="m-0 mb-3 text-14 font-bold text-ink-1">{title}</h3>}
      {children}
    </section>
  )
}

/** 큰 숫자 한 덩어리: L 24 · M 18 · S 14, 등락은 그 아래 한 줄. */
const NUM_SIZE = { L: 'text-24', M: 'text-18', S: 'text-14' } as const
export function NumBlock({ value, decimals = 0, chg, pct, size = 'M', unit }: {
  value: number | null | undefined; decimals?: number; chg?: number | null; pct?: number | null; size?: keyof typeof NUM_SIZE; unit?: string
}) {
  return (
    <div className="min-w-0">
      <div className={`num font-bold leading-tight text-ink-1 ${NUM_SIZE[size]}`}>
        {fmtNumber(value, decimals)}{unit && <span className="ml-0.5 text-12 font-normal text-ink-3">{unit}</span>}
      </div>
      {chg !== undefined && (
        <div className={`num text-12 mt-1 ${DIR_TEXT[changeDir(chg, decimals)]}`}>{fmtChange(chg, pct, decimals)}</div>
      )}
    </div>
  )
}

/**
 * 기준 시각 배지: LIVE(시각만) · 전일/종가 · 지연(주황) · 보강(회색).
 * state = 묶음이 판정한 상태(있으면 그것을 따른다). 없으면 asOf 시각으로 직접 판정한다.
 */
export function AsOfBadge({ asOf, state, filled, now }: { asOf: string; state?: string; filled?: boolean; now?: Date }) {
  const fromState = kindFromState(state)
  if (fromState === null || (!asOf && !filled)) return null
  const kind = fromState ?? asOfKind(asOf, now, { filled })
  const tone = kind === 'delayed' ? 'text-warn' : 'text-ink-3'
  return <span className={`num text-11 ${tone}`} title={kind === 'filled' ? '이번에 못 받아 직전 값을 이어 쓴 값' : undefined}>{asOfLabel(kind, asOf, now)}</span>
}

/**
 * 고르기 버튼 줄. 한 줄에 7개까지만 둔다(넘치면 줄이 바뀐다 — 8개 이상이면 묶음을 나눌 것).
 * 선택 = 검정 바탕·700. 왼쪽·오른쪽 화살표로 옮긴다(라디오 묶음과 같은 키보드 규칙).
 */
export function SegBar<T extends string>({ options, value, onChange, label }: {
  options: readonly { key: T; label: string }[]; value: T; onChange: (key: T) => void; label: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const onKey = (e: KeyboardEvent) => {
    const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
    if (!step) return
    e.preventDefault()
    const i = Math.max(0, options.findIndex(o => o.key === value))
    const next = (i + step + options.length) % options.length
    onChange(options[next].key)
    ref.current?.querySelectorAll<HTMLButtonElement>('[role=radio]')[next]?.focus()
  }
  return (
    <div ref={ref} role="radiogroup" aria-label={label} onKeyDown={onKey} className="flex flex-wrap gap-1">
      {options.map(o => {
        const on = o.key === value
        return (
          <button key={o.key} type="button" role="radio" aria-checked={on} tabIndex={on ? 0 : -1}
            onClick={() => onChange(o.key)}
            className={`h-8 px-3 rounded-btn text-13 whitespace-nowrap border ${on ? 'bg-accent text-on-accent border-accent font-bold' : 'bg-card text-ink-2 border-line hover:text-ink-1'}`}>
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

/** 상태 표시 알약: x 돌파(빨강) · n 주시(주황) · o 해당 없음(회색) · g 정상(초록). 테두리만 칠한다. */
const PILL = { x: 'text-up', n: 'text-warn', o: 'text-ink-3', g: 'text-ok' } as const
export function Pill({ tone, children }: { tone: keyof typeof PILL; children: ReactNode }) {
  return <span className={`inline-flex items-center h-5 px-2 rounded-chip border border-current text-11 whitespace-nowrap ${PILL[tone]}`}>{children}</span>
}

/** 아래에서 올라오는 시트 자리. 브라우저 기본 dialog 를 써서 Esc·초점 가두기를 그대로 얻는다. */
export function BottomSheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])
  return (
    <dialog ref={ref} onClose={onClose} aria-label={title}
      className="m-0 mt-auto w-full max-w-none max-h-[80dvh] bg-card text-ink-1 border border-line rounded-t-card p-4 backdrop:bg-ink-1/40">
      <div className="flex items-center justify-between mb-3">
        <h2 className="m-0 text-14 font-bold">{title}</h2>
        <button type="button" onClick={onClose} className="h-8 px-3 rounded-btn text-13 border border-line bg-card text-ink-2">닫기</button>
      </div>
      {children}
    </dialog>
  )
}
