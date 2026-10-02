// 렌즈 화면 작은 부품 — 세 모드가 같이 쓴다. 공통 부품(ui·charts·panels)은 고치지 않고 그 위에 얹는다.
import type { ReactNode } from 'react'
import { Pill } from '../ui'
import { fmtNumber, shortDate } from '../../lib/format'
import type { Trigger } from '../../lib/bundle'

/** 버튼 한 벌(32px) — on = 고른 상태(검정 바탕, SegBar 와 같은 모양). 링크에도 같이 쓴다. */
export const btn = (on = false) => `h-8 px-3 inline-flex items-center gap-1.5 rounded-btn text-13 whitespace-nowrap border no-underline cursor-pointer disabled:cursor-default disabled:opacity-50 ${
  on ? 'bg-accent text-on-accent border-accent font-bold' : 'bg-card text-ink-2 border-line hover:text-ink-1'}`

/** 트리거 현재값: 크기에 따라 자릿수(1000 이상 0 · 100 이상 1 · 그 밖 2), % 계열만 단위를 붙인다. */
export function trigValue(t?: Trigger): string | null {
  if (!t || t.value == null) return null
  const a = Math.abs(t.value)
  return fmtNumber(t.value, a >= 1000 ? 0 : a >= 100 ? 1 : 2) + (t.unit === '%' || t.unit === '%p' ? t.unit : '')
}

/** 기준일 표기: 「202608」(월간) → 「26.08」, 날짜는 「9/29」. */
export const asOfText = (s?: string | null) => (s ? shortDate(/^\d{6}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4)}` : s) : '')

/** 지표 상태 알약 — 돌파·주시·정상만. 자료 없음(unknown)은 알약을 달지 않는다(값 자리가 말한다). */
const TONE = { crossed: ['x', '돌파'], near: ['n', '주시'], below: ['g', '정상'] } as const
export function TrigPill({ t }: { t?: Trigger }) {
  const k = t?.state as keyof typeof TONE | undefined
  if (!k || !(k in TONE)) return null
  return <Pill tone={TONE[k][0]}>{TONE[k][1]}</Pill>
}

/** 띠 카드: 라벨 위 · 큰 숫자 · 설명 한 줄 아래. */
export function StatCard({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0 bg-card border border-line rounded-card p-3">
      <span className="block text-12 text-ink-2">{label}</span>
      <span className="block mt-1 num text-18 font-bold leading-tight text-ink-1">{value}</span>
      {sub != null && <span className="block mt-1 text-11 leading-snug text-ink-3">{sub}</span>}
    </div>
  )
}

/** 단계 번호 원: 실측(채움 검정) · 추정(점선 주황) · 미도달(회색 테두리). */
export function StepNum({ n, kind }: { n: number; kind: 'solid' | 'guess' | 'off' }) {
  const cls = kind === 'solid' ? 'bg-accent text-on-accent border-accent' : kind === 'guess' ? 'border-dashed border-warn text-warn' : 'border-line text-ink-3'
  return <span aria-hidden className={`size-6 shrink-0 inline-flex items-center justify-center rounded-chip border num text-11 font-bold ${cls}`}>{n}</span>
}

/** 「만약에」 지도 칸 높이: 390 폭 320px · 768 이상 420px · 1440 이상 480px. 불러오는 중 빈 칸도 같은 값을 쓴다.
 *  map.ts 가 아니라 여기 두는 까닭: map.ts 를 지도 조각에만 싣기 위해서다(메인 번들이 안 커진다). */
export const MAP_BOX = 'h-[320px] md:h-[420px] min-[90rem]:h-[480px]'

export const postUrl = (logNo: string) => `https://blog.naver.com/ranto28/${logNo}`
