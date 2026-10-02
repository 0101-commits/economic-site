// 보유 지도 — 칸 넓이 = 평가액 비중, 색 = 오늘 등락(format.ts heatStep 단계).
// 공유 Heatmap(charts.tsx)은 평균의 2배 이상만 두 칸으로 키워 넓이가 비중을 따르지 않는다. 그래서 따로 둔다.
// ponytail: 한 줄 비례(flex-grow = 비중). 칸이 56px 밑으로 줄면 줄이 바뀌어 그 줄만 비례한다 — 종목이 많아지면 squarified treemap 으로.
import { fmtNumber, fmtPct, heatStep } from '../../lib/format'

// 채움 농도는 charts.tsx Heatmap 의 HEAT_MIX 와 같은 값이다 — 바꾸면 둘 다 바꾼다(공유 부품으로 옮기는 것이 후속).
const MIX = [0, 22, 50, 88]
const bg = (step: number) => step
  ? `color-mix(in srgb, var(${step > 0 ? '--c-up-fill' : '--c-down-fill'}) ${MIX[Math.abs(step)]}%, var(--c-card))`
  : 'color-mix(in srgb, var(--c-ink-3) 14%, var(--c-card))'

export function WeightMap({ cells, label }: { cells: { key: string; name: string; value: number | null; weight: number }[]; label: string }) {
  const total = cells.reduce((a, c) => a + c.weight, 0) || 1
  return (
    <ul aria-label={label} className="m-0 p-0 list-none flex flex-wrap gap-1">
      {cells.map(c => {
        const step = heatStep(c.value)
        const share = (c.weight / total) * 100
        const tip = `${c.name} 비중 ${fmtNumber(share, 1)}% · 오늘 ${fmtPct(c.value)}`
        return (
          <li key={c.key} title={tip} aria-label={tip} style={{ flex: `${c.weight} 1 0`, minWidth: 56, background: bg(step) }}
            className={`h-16 min-w-0 rounded-inner px-1 flex flex-col items-center justify-center text-center ${Math.abs(step) === 3 ? 'text-on-fill' : 'text-ink-1'}`}>
            <span className="block w-full text-11 leading-tight ellipsis-ok">{c.name}</span>
            <span className="block num text-11 font-bold">{fmtPct(c.value)}</span>
            <span className="block num text-11">{`비중 ${fmtNumber(share, 0)}%`}</span>
          </li>
        )
      })}
    </ul>
  )
}
