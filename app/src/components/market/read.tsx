// 읽는 값(lib/read.ts) 부품 — 거시 카드 · 큰 차트 머리 · 지표 상세 머리 · 발표값과 컨센서스 차트.
// 카드 줄 차례(기획서 3qh6Z7rw 5절): 나라 · 이름 · 기준 기간 · 발표일 / 큰 숫자 + 기준 말 / 함께 보는 값 · 지난 값 / 컨센서스 / 작은 막대.
import type { StripItem } from '../../lib/bundle'
import { COUNTRY, cellAt, consText, fmtRead, prevWord, refLabel, releasedLabel, type Read, type ReadCell } from '../../lib/read'
import { Pill } from '../ui'

/** 「계산」 꼬리표 — 공식 발표값이 아니라 지수로 계산한 값. */
export const CalcTag = () => (
  <span className="inline-flex items-center h-4 px-1.5 rounded-chip border border-line text-10 text-ink-3 whitespace-nowrap" title="공식 발표값이 아니라 지수로 계산한 값">계산</span>
)

/** 큰 숫자 + 기준 말(「전월 대비」) + 계산 꼬리표. size L = 큰 차트 · 상세 머리, M = 카드. */
export function ReadBig({ r, size = 'M' }: { r: Read; size?: 'M' | 'L' }) {
  const m = r.main
  return (
    <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <span className={`num font-bold leading-tight text-ink-1 ${size === 'L' ? 'text-24' : 'text-18'}`}>{fmtRead(m)}</span>
      {m.word && <span className="text-12 text-ink-3">{m.word}</span>}
      {m.src === 'calc' && <CalcTag />}
    </span>
  )
}

/** 함께 보는 값 한 칸: 「전년 대비 +3.6%」 · 값이 없으면 「전년 대비 — 1년 전 값 미발표」. */
function SubCell({ c }: { c: ReadCell }) {
  return (
    <span className="inline-flex items-center gap-1">
      {c.word || '수준'} <b className="num font-bold text-ink-1">{fmtRead(c)}</b>
      {c.ref && <span className="text-ink-3">({refLabel(c.ref)})</span>}
      {c.value == null && c.why && <span className="text-ink-3">{c.why}</span>}
      {c.src === 'calc' && <CalcTag />}
    </span>
  )
}

/** 둘째 · 셋째 줄 — 함께 보는 값 · 지난 값 / 컨센서스 대비. */
export function ReadLines({ r }: { r: Read }) {
  const cons = consText(r)
  const prev = r.prev != null ? fmtRead(cellAt(r.main, r.prev)) : null
  return (
    <>
      {(r.subs.length > 0 || prev) && (
        <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-12 text-ink-2">
          {r.subs.map((c, i) => <SubCell key={i} c={c} />)}
          {prev && <span>{prevWord(r.freq)} <b className="num font-bold text-ink-1">{prev}</b></span>}
        </span>
      )}
      {cons && (
        <span className="flex flex-wrap items-center gap-x-2 text-12 text-ink-2">
          컨센서스 <b className="num font-bold text-ink-1">{fmtRead(cellAt(r.main, r.cons))}</b>
          <span>·</span><b className="font-bold text-ink-1">{cons}</b>
          {r.size && <Pill tone="n">평소보다 {r.size === '매우 큼' ? '매우 큰' : '큰'} 차이</Pill>}
        </span>
      )}
    </>
  )
}

/** 작은 막대(최근 12기간, 마지막 막대 진하게, 0 기준선). */
export function ReadBars({ values }: { values: (number | null)[] }) {
  const vs = values.filter((v): v is number => v != null)
  if (vs.length < 3) return null
  const W = 200, H = 36, lo = Math.min(0, ...vs), hi = Math.max(0, ...vs), span = hi - lo || 1
  const bw = W / vs.length, y0 = (hi / span) * H
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" aria-hidden className="block mt-1">
      {vs.map((v, i) => {
        const h = Math.max((Math.abs(v) / span) * H, 0.8)
        return <rect key={i} x={i * bw + bw * 0.18} y={v >= 0 ? y0 - h : y0} width={bw * 0.64} height={h} rx={1}
          className={i === vs.length - 1 ? 'fill-ink-2' : 'fill-line'} />
      })}
      {lo < 0 && <line x1={0} x2={W} y1={y0} y2={y0} className="stroke-line" strokeWidth={1} />}
    </svg>
  )
}

/** 거시 카드(읽는 값): 나라 꼬리표 · 이름 · 기준 기간 · 발표일 → 큰 숫자 → 함께 보는 값 · 지난 값 → 컨센서스 → 막대. 누르면 큰 차트. */
export function ReadCard({ it, on, onPick }: { it: StripItem & { read: Read }; on: boolean; onPick: () => void }) {
  const r = it.read
  const cn = COUNTRY[it.country ?? '']
  return (
    <button type="button" onClick={onPick} aria-pressed={on}
      className={`w-full h-full flex flex-col gap-1 p-3 text-left bg-card border rounded-card cursor-pointer ${on ? 'border-accent' : 'border-line'}`}>
      <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-12 text-ink-2">
        {cn && <Pill tone="o">{cn}</Pill>}
        <span>{r.name ?? it.short ?? it.label}</span>
        <span className="num font-bold text-ink-1">{refLabel(r.ref)}</span>
        {r.released && <span className="ml-auto num text-11 text-ink-3">{releasedLabel(r.released)}</span>}
      </span>
      <ReadBig r={r} />
      <ReadLines r={r} />
      <ReadBars values={(r.series ?? []).slice(-12).map(p => p[1])} />
    </button>
  )
}

/** 발표값(막대)과 컨센서스(점) — 최근 12회. 컨센서스가 하나도 없으면 그리지 않는다. */
export function ReleasesChart({ r }: { r: Read }) {
  const rel = (r.rel ?? []).filter(x => x[1] != null)
  if (!rel.some(x => x[2] != null)) return null
  const W = 640, H = 220, L = 44, R = 10, T = 14, B = 30
  const vals = rel.flatMap(x => [x[1], x[2]]).filter((v): v is number => v != null)
  const step = r.main.unit === '%' ? 0.2 : 5
  let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals)
  lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step
  if (hi - lo > step * 8) { const s2 = Math.ceil((hi - lo) / 8 / step) * step; lo = Math.floor(lo / s2) * s2; hi = Math.ceil(hi / s2) * s2 }
  if (!(hi > lo)) hi = lo + step          // 발표값 · 컨센서스가 모두 0 이면 눈금 폭이 0 → 무한 반복(검토 2026-11-15)
  const tick = (hi - lo) / Math.max(1, Math.round((hi - lo) / step) > 8 ? 4 : Math.round((hi - lo) / step))
  if (!(tick > 0)) return null
  const sy = (v: number) => T + ((hi - v) / (hi - lo || 1)) * (H - T - B)
  const cw = (W - L - R) / rel.length
  const ticks: number[] = []
  for (let t = lo; t <= hi + 1e-9; t += tick) ticks.push(Math.round(t * 1000) / 1000)
  const fmt = (v: number) => fmtRead({ ...r.main, value: v }, false)
  return (
    <figure className="m-0">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mb-1 text-12 text-ink-2">
        <span className="inline-flex items-center gap-1.5"><span aria-hidden className="inline-block w-2.5 h-2.5 rounded-[2px] bg-ink-3" />발표값</span>
        <span className="inline-flex items-center gap-1.5"><span aria-hidden className="inline-block w-2.5 h-2.5 rounded-full border-2 border-up-fill" />컨센서스</span>
        <span className="text-ink-3">{r.main.word} · 최근 {rel.length}회</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`발표값과 컨센서스 최근 ${rel.length}회`}>
        {ticks.map(t => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={sy(t)} y2={sy(t)} className="stroke-line" strokeWidth={Math.abs(t) < 1e-9 ? 1.4 : 0.7} />
            <text x={L - 6} y={sy(t) + 4} textAnchor="end" className="fill-ink-3 text-11">{fmt(t)}</text>
          </g>
        ))}
        {rel.map(([ref, a, c], i) => {
          const cx = L + i * cw + cw / 2, ya = sy(a as number), y0 = sy(0)
          const top = Math.min(ya, y0), h = Math.max(Math.abs(y0 - ya), 1)
          const last = i === rel.length - 1
          return (
            <g key={ref}>
              <rect x={cx - cw * 0.28} y={top} width={cw * 0.56} height={h} rx={2} className={last ? 'fill-ink-1' : 'fill-ink-3'} opacity={last ? 1 : 0.45} />
              {c != null && <circle cx={cx} cy={sy(c)} r={4} className="fill-card stroke-up-fill" strokeWidth={2} />}
              <text x={cx} y={H - B + 16} textAnchor="middle" className="fill-ink-3 text-11">{refLabel(ref).replace(/월분$/, '월')}</text>
              {last && <text x={cx} y={top - 6} textAnchor="middle" className="fill-ink-1 text-12 font-bold">{fmt(a as number)}</text>}
            </g>
          )
        })}
      </svg>
    </figure>
  )
}
