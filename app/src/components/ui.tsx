// 공통 부품 — 화면은 이 부품과 토큰 클래스만 쓴다. 색 띠 상자·그림자·그라데이션 금지.
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type KeyboardEvent } from 'react'
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
 * state·liveUntil = 묶음이 판정한 값(있으면 그것을 따른다). 없으면 asOf 시각으로 직접 판정한다.
 * asOf 는 null 일 수 있다(묶음의 kept·missing) — kept 는 「보강」만, missing 은 배지 없이 값 자리 '—' 가 말한다.
 */
export function AsOfBadge({ asOf, state, liveUntil, filled, now }: {
  asOf: string | null | undefined; state?: string; liveUntil?: string | null; filled?: boolean; now?: Date
}) {
  const fromState = kindFromState(state, liveUntil, now)
  if (fromState === null) return null
  const kind = fromState ?? (asOf ? asOfKind(asOf, now, { filled }) : filled ? 'filled' : null)
  if (!kind || (kind !== 'filled' && !asOf)) return null
  const tone = kind === 'delayed' ? 'text-warn' : 'text-ink-3'
  return <span className={`num text-11 ${tone}`} title={kind === 'filled' ? '이번에 못 받아 직전 값을 이어 쓴 값' : undefined}>{asOfLabel(kind, asOf || '', now)}</span>
}

/**
 * 고르기 버튼 줄. 한 줄에 7개까지만 둔다(넘치면 줄이 바뀐다 — 8개 이상이면 묶음을 나눌 것).
 * scroll = 줄을 바꾸지 않고 한 줄 가로 스크롤(좁은 화면의 자산군 줄). 가려진 쪽 끝을 흐리게 하고, 고른 버튼을 줄 가운데로 민다.
 * 선택 = 검정 바탕·700. 왼쪽·오른쪽 화살표로 옮긴다(라디오 묶음과 같은 키보드 규칙).
 */
export function SegBar<T extends string>({ options, value, onChange, label, scroll }: {
  options: readonly { key: T; label: string }[]; value: T; onChange: (key: T) => void; label: string; scroll?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  // 스크롤 줄: 왼쪽·오른쪽에 가려진 버튼이 있는지(그쪽 끝만 흐린다)
  const [edge, setEdge] = useState({ l: false, r: false })
  useLayoutEffect(() => {
    const el = ref.current
    if (!scroll || !el) return
    const check = () => {
      const l = el.scrollLeft > 1, r = el.scrollLeft + el.clientWidth < el.scrollWidth - 1
      setEdge(e => (e.l === l && e.r === r ? e : { l, r }))
    }
    check()
    el.addEventListener('scroll', check, { passive: true })
    const ro = new ResizeObserver(check)
    ro.observe(el)
    return () => { el.removeEventListener('scroll', check); ro.disconnect() }
  }, [scroll])
  // 고른 버튼을 줄 가운데로. scrollIntoView 는 페이지까지 세로로 움직일 수 있어 줄의 가로 위치만 바꾼다.
  useEffect(() => {
    const el = ref.current, b = el?.querySelector<HTMLElement>('[aria-checked=true]')
    if (scroll && el && b) el.scrollTo({ left: b.offsetLeft - (el.clientWidth - b.offsetWidth) / 2 })
  }, [scroll, value])
  const fade = (on: boolean) => (on ? '1.5rem' : '0px')
  const mask = scroll && (edge.l || edge.r)
    ? { maskImage: `linear-gradient(to right, transparent, black ${fade(edge.l)}, black calc(100% - ${fade(edge.r)}), transparent)` }
    : undefined
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
    <div ref={ref} role="radiogroup" aria-label={label} onKeyDown={onKey} style={mask}
      className={scroll ? 'relative -my-1 p-1 flex flex-nowrap gap-1 overflow-x-auto [scrollbar-width:thin]' : 'flex flex-wrap gap-1'}>
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
