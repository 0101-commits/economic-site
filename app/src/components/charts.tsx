// 공통 차트 — 외부 라이브러리 없이 SVG 로 그린다. 색은 토큰 클래스·변수만, 그림자·그라데이션 0.
// 시장·렌즈·상세 화면이 같이 쓴다. 쓰는 법은 각 부품 위 주석.
import { useLayoutEffect, useRef, useState, type PointerEvent } from 'react'
import { SegBar } from './ui'
import { changeDir, fmtNumber, fmtPct, heatStep, shortDate, PERIODS, type Dir, type PeriodKey, type Pt } from '../lib/format'

const STROKE: Record<Dir, string> = { up: 'stroke-up', down: 'stroke-down', flat: 'stroke-ink-2' }
const FILL: Record<Dir, string> = { up: 'fill-up', down: 'fill-down', flat: 'fill-ink-2' }
const TEXT: Record<Dir, string> = { up: 'text-up', down: 'text-down', flat: 'text-ink-2' }
// 비교 모드 선: 검정 → 회색 → (3·4번째는 점선으로 구별)
const CMP = [
  { s: 'stroke-ink-1', f: 'fill-ink-1', dash: undefined },
  { s: 'stroke-ink-3', f: 'fill-ink-3', dash: undefined },
  { s: 'stroke-ink-2', f: 'fill-ink-2', dash: '4 3' },
  { s: 'stroke-ink-3', f: 'fill-ink-3', dash: '2 3' },
]

/** 상자 크기 재기(px, 반올림) — 차트는 실제 픽셀로 그려야 글자·선 굵기가 늘어나지 않는다. 렌즈 지도도 같이 쓴다. */
export function useBox<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => {
      const w = Math.round(e.contentRect.width), h = Math.round(e.contentRect.height)
      setBox(b => (b.w === w && b.h === h ? b : { w, h }))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, box] as const
}

type Ref = { value: number; label: string }
type Periods = Partial<Record<PeriodKey, Pt[] | null>>

/**
 * 선 차트. periods = 기간별 [날짜, 값](점 2개 이상인 기간만 칩이 생긴다 — format.ts slicePeriods 로 만들면 된다).
 * 한 줄이면 선 색 = 그 기간 등락 방향, compare 를 주면 비교 모드(검정·회색 + 선 끝 이름).
 * base = 전일선(1일·1주에서만 그린다), limit = 임계선(주황). period/onPeriod 를 주면 바깥(주소)이 기간을 쥔다.
 * 높이 PC 150 / 모바일 110. 누르거나 마우스를 올리면 세로선 + 값 풍선.
 */
export function LineChart({ periods, period, onPeriod, name, compare = [], decimals = 2, base, limit, label, empty = '시계열 준비 중' }: {
  periods: Periods
  period?: PeriodKey
  onPeriod?: (p: PeriodKey) => void
  name?: string
  compare?: { name: string; periods: Periods }[]
  decimals?: number
  base?: Ref | null
  limit?: Ref | null
  label: string
  empty?: string
}) {
  const avail = PERIODS.filter(o => (periods[o.key]?.length ?? 0) >= 2)
  const [own, setOwn] = useState<PeriodKey>('3m')
  const want = period ?? own
  const cur = (avail.find(o => o.key === want) ?? avail.find(o => o.key === '3m') ?? avail[avail.length - 1])?.key
  const pick = (k: PeriodKey) => { setOwn(k); onPeriod?.(k) }
  const [ref, { w, h }] = useBox<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)

  const main = (cur && periods[cur]) || []
  const cmp = compare.length > 0
  const lines = [main, ...compare.slice(0, 3).map(c => (cur && c.periods[cur]) || [])]
  const names = [name ?? '', ...compare.map(c => c.name)]
  const showBase = base != null && (cur === '1d' || cur === '1w')

  // 축: 모든 선 + 전일선 + 임계선이 들어오게, 위아래 8% 여유
  const padT = 8, padB = 18, padR = cmp ? 56 : 6
  const vals = lines.flatMap(l => l.map(p => p[1]))
  if (showBase) vals.push(base.value)
  if (limit) vals.push(limit.value)
  let lo = Math.min(...vals), hi = Math.max(...vals)
  if (!(hi > lo)) { hi = lo + 1; lo -= 1 }
  const room = (hi - lo) * 0.08
  lo -= room; hi += room
  const iw = Math.max(1, w - padR), ih = Math.max(1, h - padT - padB)
  const X = (i: number, n: number) => (n <= 1 ? iw : (i / (n - 1)) * iw)
  const Y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * ih
  const d = (l: Pt[]) => l.map((p, i) => `${i ? 'L' : 'M'}${X(i, l.length).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('')
  const dir: Dir = main.length >= 2 ? changeDir(main[main.length - 1][1] - main[0][1], decimals) : 'flat'
  const style = (j: number) => (cmp ? CMP[j] : { s: STROKE[dir], f: FILL[dir], dash: undefined })
  // 비교선은 길이가 달라도 같은 비율 자리의 점을 쓴다(날짜가 맞는다고 본다)
  const at = (l: Pt[], i: number) => l[Math.round((i / Math.max(1, main.length - 1)) * (l.length - 1))]

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const x = e.clientX - e.currentTarget.getBoundingClientRect().left
    setHover(Math.max(0, Math.min(main.length - 1, Math.round((x / iw) * (main.length - 1)))))
  }
  const hx = hover != null ? X(hover, main.length) : 0
  // 비교 모드 선 끝 이름 자리: 앞 선 이름과 11px 안으로 붙으면 그 반대쪽으로 민다(겹침 차트는 끝값이 비슷한 일이 잦다)
  const ends: number[] = [], taken: number[] = []
  lines.forEach((l, j) => {
    if (l.length < 2) return
    let y = Y(l[l.length - 1][1]) + 4
    for (const e of taken) if (Math.abs(y - e) < 11) y = e + (y >= e ? 11 : -11)
    taken.push(ends[j] = y)
  })

  return (
    <div className="min-w-0">
      <div ref={ref} className="relative h-[110px] pc:h-[150px]">
        {!cur ? (
          <p className="m-0 h-full flex items-center justify-center text-13 text-ink-3">{empty}</p>
        ) : w > 0 && (
          <svg width={w} height={h} role="img" aria-label={`${label} ${PERIODS.find(o => o.key === cur)!.label} 차트`}
            className="block touch-pan-y select-none"
            onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={e => { if (e.pointerType === 'mouse') setHover(null) }}>
            {showBase && (
              <g>
                <line x1={0} x2={iw} y1={Y(base.value)} y2={Y(base.value)} className="stroke-ink-3" strokeDasharray="3 3" />
                <text x={2} y={Y(base.value) - 4} className="fill-ink-3 text-11 num">{base.label} {fmtNumber(base.value, decimals)}</text>
              </g>
            )}
            {limit && (
              <g>
                <line x1={0} x2={iw} y1={Y(limit.value)} y2={Y(limit.value)} className="stroke-warn" strokeDasharray="4 3" />
                {/* 선 끝(오른쪽)은 끝점 자리라 라벨은 왼쪽. 전일선과 같이 있으면 선 아래로 내려 겹치지 않게 */}
                <text x={2} y={Y(limit.value) + (showBase ? 12 : -4)} className="fill-warn text-11 num">{limit.label} {fmtNumber(limit.value, decimals)}</text>
              </g>
            )}
            {lines.map((l, j) => l.length >= 2 && (
              <g key={j}>
                <path d={d(l)} fill="none" className={style(j).s} strokeWidth={j ? 1.5 : 2} strokeDasharray={style(j).dash} strokeLinejoin="round" />
                <circle cx={X(l.length - 1, l.length)} cy={Y(l[l.length - 1][1])} r={3} className={style(j).f} />
                {cmp && <text x={iw + 6} y={ends[j]} className={`${style(j).f} text-11`}>{names[j]}</text>}
              </g>
            ))}
            <text x={0} y={h - 4} className="fill-ink-3 text-11 num">{shortDate(main[0][0])}</text>
            <text x={iw} y={h - 4} textAnchor="end" className="fill-ink-3 text-11 num">{shortDate(main[main.length - 1][0])}</text>
            {hover != null && <line x1={hx} x2={hx} y1={padT} y2={padT + ih} className="stroke-ink-3" />}
          </svg>
        )}
        {cur && hover != null && main[hover] && (
          <div className="absolute top-0 pointer-events-none bg-card border border-line rounded-inner px-2 py-1 text-11"
            style={hx > w / 2 ? { right: w - hx + 8 } : { left: hx + 8 }}>
            {main[hover][0] && <div className="num text-ink-3">{main[hover][0]}</div>}
            {lines.map((l, j) => l.length >= 2 && (
              <div key={j} className="num text-ink-1">{cmp && <span className="text-ink-3">{names[j]} </span>}{fmtNumber(at(l, hover)?.[1], decimals)}</div>
            ))}
          </div>
        )}
      </div>
      {cur && <div className="mt-2"><SegBar label="기간" options={avail} value={cur} onChange={pick} /></div>}
    </div>
  )
}

/** 띠 카드용 작은 선 44×16 + 끝점. dir 를 주면 그 색(카드 등락과 맞출 때), 없으면 처음→끝 방향. */
export function Sparkline({ values, dir }: { values?: number[] | null; dir?: Dir }) {
  if (!values || values.length < 2) return null
  const W = 44, H = 16
  const lo = Math.min(...values), span = Math.max(...values) - lo || 1
  const pts = values.map((v, i) => [1 + (i / (values.length - 1)) * (W - 4), H - 2 - ((v - lo) / span) * (H - 4)])
  const c = dir ?? changeDir(values[values.length - 1] - values[0])
  const [ex, ey] = pts[pts.length - 1]
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden className="block shrink-0">
      <polyline points={pts.map(p => p.join(',')).join(' ')} fill="none" className={STROKE[c]} strokeWidth={1.25} strokeLinejoin="round" />
      <circle cx={ex} cy={ey} r={1.75} className={FILL[c]} />
    </svg>
  )
}

/** 52주 위치 바: 최저·최고 라벨 + 현재 점. 셋 중 하나라도 없거나 최고 ≤ 최저면 그리지 않는다(값은 format.ts range52). */
export function Range52({ low, high, value, decimals = 2 }: { low?: number | null; high?: number | null; value?: number | null; decimals?: number }) {
  if (low == null || high == null || value == null || !(high > low)) return null
  const pos = Math.max(0, Math.min(1, (value - low) / (high - low))) * 100
  return (
    <div className="min-w-0" role="img" aria-label={`52주 최저 ${fmtNumber(low, decimals)}, 최고 ${fmtNumber(high, decimals)}, 지금은 아래에서 ${Math.round(pos)}% 자리`}>
      {/* 점은 바깥 상자 기준으로 놓고, 선은 양끝에 점 반지름(5px)만큼 여백 — 0%·100% 에서 점이 어떤 요소 밖으로도 나가지 않는다(넘침 게이트 T1) */}
      <div className="relative h-2.5 my-1">
        <div className="absolute inset-x-1.5 top-1/2 h-1 -translate-y-1/2 rounded-chip bg-line" />
        <span className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-chip bg-ink-1" style={{ left: `calc(5px + ${pos / 100} * (100% - 10px))` }} />
      </div>
      <div className="flex justify-between gap-2 text-11 text-ink-3">
        <span>52주 최저 <span className="num text-ink-2">{fmtNumber(low, decimals)}</span></span>
        <span>최고 <span className="num text-ink-2">{fmtNumber(high, decimals)}</span></span>
      </div>
    </div>
  )
}

export type HeatCell = { key: string; name: string; value: number | null; weight?: number }
const HEAT_MIX = [0, 22, 50, 88]   // 단계 1·2·3 의 채움 농도(%) — 카드 바탕과 섞는다
/** 히트맵 칸 채움: 값(%)의 heatStep 단계만큼 상승·하락색을 카드 바탕과 섞는다. 0·빈 값 = 옅은 회색. 렌즈 자산 격자도 이것을 쓴다. */
export function heatBg(value: number | null | undefined): string {
  const step = heatStep(value)
  return step
    ? `color-mix(in srgb, var(${step > 0 ? '--c-up-fill' : '--c-down-fill'}) ${HEAT_MIX[Math.abs(step)]}%, var(--c-card))`
    : 'color-mix(in srgb, var(--c-ink-3) 14%, var(--c-card))'
}
/** 히트맵 칸 글자색: 채움 명도를 따른다 — 진한 3단만 흰 글자. */
export const heatInk = (value: number | null | undefined) => (Math.abs(heatStep(value)) === 3 ? 'text-on-fill' : 'text-ink-1')

/**
 * 히트맵 격자: 칸 = 이름 + 글자(text, 기본 등락률 fmtPct). 색 단계는 format.ts heatStep(경계 ±2.5 · ±1 · 0).
 * weight 가 평균의 2배 이상이면 2칸. 칸 폭 < 40px 이면 이름만, < 28px 이면 색만(컨테이너 쿼리).
 * 글자색은 채움 명도를 따른다(heatInk). onPick 을 주면 칸이 버튼이 된다.
 */
export function Heatmap({ cells, onPick, minCell = 56, label, text = c => fmtPct(c.value) }: {
  cells: HeatCell[]; onPick?: (c: HeatCell) => void; minCell?: number; label: string; text?: (c: HeatCell) => string
}) {
  const mean = cells.reduce((a, c) => a + (c.weight ?? 0), 0) / (cells.length || 1)
  return (
    <ul aria-label={label} className="m-0 p-0 list-none grid grid-flow-dense gap-1"
      style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${minCell}px, 1fr))` }}>
      {cells.map(c => {
        const wide = mean > 0 && (c.weight ?? 0) >= 2 * mean
        const cls = `@container w-full h-10 rounded-inner border-0 p-0 flex flex-col items-center justify-center text-center ${heatInk(c.value)}`
        const t = text(c)
        const tip = `${c.name} ${t}`
        const body = (
          <>
            <span className="block w-full px-0.5 text-11 leading-tight ellipsis-ok @max-[28px]:hidden">{c.name}</span>
            <span className="block num text-11 font-bold @max-[40px]:hidden">{t}</span>
          </>
        )
        return (
          <li key={c.key} className={wide ? 'col-span-2' : undefined}>
            {onPick
              ? <button type="button" onClick={() => onPick(c)} aria-label={tip} title={tip} className={`${cls} cursor-pointer`} style={{ background: heatBg(c.value) }}>{body}</button>
              : <div title={tip} className={cls} style={{ background: heatBg(c.value) }}>{body}</div>}
          </li>
        )
      })}
    </ul>
  )
}

export type Bar = { key: string; label: string; value: number | null }
const signed = (v: number | null, decimals: number) => (v == null ? '—' : `${v > 0 ? '+' : ''}${fmtNumber(v, decimals)}`)

/**
 * 양·음 막대(가운데 0선). 기본 = 가로 줄(이름 | 막대 | 값) — 3주체 순매수.
 * vertical = 세로 기둥 한 줄(값 많은 시계열, 예: 20거래일). 양수 = 상승색, 음수 = 하락색, 길이는 |값| 최대 기준.
 * signed={false} = 부호·방향색 없는 크기 막대(언급 수 같은 0 이상 값): 0선 없이 왼쪽(세로는 아래)에서 검정으로 자라고 값에 + 를 안 붙인다.
 */
export function DivergingBars({ bars, decimals = 0, vertical, label, signed: sign = true }: {
  bars: Bar[]; decimals?: number; vertical?: boolean; label: string; signed?: boolean
}) {
  const max = Math.max(0, ...bars.map(b => Math.abs(b.value ?? 0))) || 1
  const len = (v: number) => `${(Math.abs(v) / max) * (sign ? 50 : 100)}%`
  const shown = (v: number | null) => (sign ? signed(v, decimals) : fmtNumber(v, decimals))
  if (vertical) {
    return (
      <div role="img" aria-label={label} className="relative flex items-stretch gap-px h-16">
        {sign && <span aria-hidden className="absolute inset-x-0 top-1/2 h-px bg-line" />}
        {bars.map(b => (
          <span key={b.key} title={`${b.label} ${shown(b.value)}`} className="relative flex-1 min-w-0">
            {!!b.value && <span className={`absolute inset-x-0 ${!sign ? 'bottom-0 bg-ink-1' : b.value > 0 ? 'bottom-1/2 bg-up-fill' : 'top-1/2 bg-down-fill'}`} style={{ height: len(b.value) }} />}
          </span>
        ))}
      </div>
    )
  }
  return (
    <ul aria-label={label} className="m-0 p-0 list-none flex flex-col gap-2">
      {bars.map(b => (
        <li key={b.key} className="grid grid-cols-[3.5rem_minmax(0,1fr)_5.5rem] items-center gap-2 text-12">
          <span className="text-ink-2 whitespace-nowrap">{b.label}</span>
          <span className="relative h-3">
            {sign && <span aria-hidden className="absolute inset-y-0 left-1/2 w-px bg-line" />}
            {!!b.value && <span className={`absolute inset-y-0 ${!sign ? 'left-0 bg-ink-1' : b.value > 0 ? 'left-1/2 bg-up-fill' : 'right-1/2 bg-down-fill'}`} style={{ width: len(b.value) }} />}
          </span>
          <span className={`num text-right ${sign ? TEXT[changeDir(b.value)] : 'text-ink-1'}`}>{shown(b.value)}</span>
        </li>
      ))}
    </ul>
  )
}
