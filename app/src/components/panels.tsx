// 공통 패널 — 패널 머리 · 지표 띠 카드 · 순위 표 · 더 보기. ui.tsx 의 Card·AsOfBadge·BottomSheet 위에 얹는다.
import { Fragment, useMemo, useState, useSyncExternalStore, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ChevronDown, Star, type LucideIcon } from 'lucide-react'
import { AsOfBadge, BottomSheet, Card } from './ui'
import { Sparkline } from './charts'
import { changeDir, fmtChange, fmtNumber, fmtPct, scaled } from '../lib/format'
import { shownUnit, type StripItem } from '../lib/bundle'
import { foldId, hiddenRows, isFolded, setFolded } from '../lib/fold'
import { countFold, countUse } from '../lib/usage'

const PC_MQ = '(min-width: 61.25rem)'   // app.css --breakpoint-pc 와 같은 값
const DIR_TEXT = { up: 'text-up', down: 'text-down', flat: 'text-ink-2' } as const

/**
 * 패널: 머리(아이콘·제목 | 단위·출처·기준 시각 | 도구) + 본문.
 * fold = 접을 수 있음(머리 끝 화살표). 늘 펼친 채 시작하고, 사용자가 접은 것만 이 기기에 기억한다(lib/fold.ts).
 * 접기는 브라우저 기본 details 다(data-panel-fold = 첫 그림 접힘 0 게이트 tests/ui/foldzero.mjs 의 표식).
 */
export function Panel({ title, icon: Icon, unit, source, asOf, state, liveUntil, tools, fold, className = '', children }: {
  title: ReactNode
  icon?: LucideIcon
  unit?: string
  source?: string
  asOf?: string | null
  state?: string
  liveUntil?: string | null
  tools?: ReactNode
  fold?: boolean
  className?: string
  children: ReactNode
}) {
  const id = foldId(useLocation().pathname, typeof title === 'string' ? title : '')
  const [open, setOpen] = useState(() => !fold || !isFolded(id))
  const head = (
    <div className={`flex flex-wrap items-center gap-x-3 gap-y-1 ${open ? 'mb-3' : ''}`}>
      <h2 className="m-0 inline-flex items-center gap-1.5 text-14 font-bold text-ink-1">{Icon && <Icon size={16} aria-hidden />}{title}</h2>
      {(unit || source || asOf || state) && (
        <span className="flex flex-wrap items-center gap-x-2 text-11 text-ink-3">
          {unit && <span>{unit}</span>}
          {source && <span>{source}</span>}
          <AsOfBadge asOf={asOf} state={state} liveUntil={liveUntil} />
        </span>
      )}
      {tools && <div className="ml-auto flex items-center gap-1">{tools}</div>}
      {fold && <ChevronDown size={16} aria-hidden className={`${tools ? '' : 'ml-auto'} text-ink-3 ${open ? 'rotate-180' : ''}`} />}
    </div>
  )
  if (!fold) return <Card className={className}>{head}{children}</Card>
  return (
    <Card className={className}>
      <details data-panel-fold open={open} onToggle={e => { const o = e.currentTarget.open; if (o !== open) { setOpen(o); setFolded(id, !o); countFold(id, o) } }}>
        <summary className="list-none cursor-pointer [&::-webkit-details-marker]:hidden">{head}</summary>
        {children}
      </details>
    </Card>
  )
}

const onPcChange = (f: () => void) => { const m = matchMedia(PC_MQ); m.addEventListener('change', f); return () => m.removeEventListener('change', f) }
const isPc = () => matchMedia(PC_MQ).matches

/**
 * 더 보기: 긴 표 · 목록은 모바일(<980) 5행 · PC 10행까지, 끝에 「N행 더 보기」 — 누르면 그 자리에서 전부. children 이 보일 행으로 그린다.
 * name = 사용 기록(lib/usage.ts)에 남는 목록 이름, unit = 단추의 셈 단위(카드 격자는 「개」).
 */
export function More<R>({ rows, children, name = '목록', unit = '행' }: { rows: R[]; children: (shown: R[]) => ReactNode; name?: string; unit?: string }) {
  const pc = useSyncExternalStore(onPcChange, isPc)
  const [all, setAll] = useState(false)
  const { pathname } = useLocation()
  const rest = all ? 0 : hiddenRows(rows.length, pc)
  return (
    <>
      {children(rest ? rows.slice(0, rows.length - rest) : rows)}
      {rest > 0 && (
        <button type="button" onClick={() => { setAll(true); countUse('more', foldId(pathname, name)) }}
          className="inline-flex items-center gap-1 h-8 mt-1 px-0 border-0 bg-transparent cursor-pointer text-12 text-ink-2 hover:text-ink-1">
          <span className="num">{rest}</span>{unit} 더 보기<ChevronDown size={14} aria-hidden />
        </button>
      )}
    </>
  )
}

/**
 * 지표 띠 카드: 이름·기준 시각 → 값 → 등락 → 이유 한 줄 + 작은 차트. 이름은 PC short · 모바일 shortM(8자 상한, 줄바꿈 없음).
 * onSelect 를 주면 카드가 고르기 버튼(selected = 검정 테두리), to 를 주면 링크. onWatch 를 주면 오른쪽 위에 별.
 * tag = 이름 옆 알약(홈 띠의 「관심」 칸). 알약이 붙은 이름은 PC 에서도 줄을 바꾼다(카드 폭을 넘지 않게).
 * 파생 칸: up·down 이 있으면 값 자리에 「상승/하락」 종목 수를 적는다.
 */
export function StripCard({ item, selected, onSelect, to, watched, onWatch, tag }: {
  item: StripItem; selected?: boolean; onSelect?: () => void; to?: string; watched?: boolean; onWatch?: () => void; tag?: ReactNode
}) {
  const v = scaled(item.value, item.scale), chg = scaled(item.change, item.scale)
  const unit = shownUnit(item)
  const breadth = item.up != null && item.down != null
  const pctOnly = chg == null && !breadth && item.changePct != null   // 등락률만 있는 칸(홈 띠의 관심 종목)
  const dir = pctOnly ? changeDir(item.changePct, 2) : changeDir(chg, item.decimals)
  const name = item.short || item.label
  // 카드마다 같은 줄 구성: 이름 / 기준 시각 + 작은 차트 / 값 / 등락 / 이유. 좁은 PC 8열에서도 줄이 섞이지 않게 고정한다.
  const body = (
    <>
      {/* PC 는 줄 고정(8열 정렬), 모바일 2열 격자(약 150px)에선 긴 이름을 자르지 않고 줄을 바꾼다(최장 데이터 게이트 360) */}
      <span className={`block text-12 text-ink-2 ${tag ? '' : 'pc:whitespace-nowrap'} [overflow-wrap:anywhere] ${onWatch ? 'pr-7' : ''}`}>
        <span className="hidden pc:inline">{name}</span>
        <span className="pc:hidden">{item.shortM || name}</span>
        {tag && <span className="ml-1 inline-flex align-middle">{tag}</span>}
      </span>
      <span className="flex items-center justify-between gap-2 h-4 mt-0.5 mb-1">
        <AsOfBadge asOf={item.asOf} state={item.state} liveUntil={item.liveUntil} />
        <Sparkline values={item.spark} dir={dir} />
      </span>
      <span className="block num text-18 font-bold leading-tight text-ink-1">
        {breadth ? `${item.up}/${item.down}` : fmtNumber(v, item.decimals)}
        {unit && <span className="ml-0.5 text-12 font-normal text-ink-3">{unit}</span>}
      </span>
      <span className={`block num text-12 mt-1 ${DIR_TEXT[dir]}`}>
        {chg != null ? fmtChange(chg, item.changePct, item.decimals) : pctOnly ? fmtPct(item.changePct) : breadth ? `보합 ${item.flat ?? '—'}` : ' '}
      </span>
      {/* 이유는 한 줄이 목표지만 PC 8열 카드(약 115px)엔 안 들어간다 — 자르지 않고 줄을 바꾼다 */}
      {(item.reason || item.reasonShort) && (
        <span className="block mt-1 text-11 leading-snug text-ink-3">
          <span className="hidden pc:inline">{item.reason || item.reasonShort}</span>
          <span className="pc:hidden">{item.reasonShort || item.reason}</span>
        </span>
      )}
    </>
  )
  const pad = 'flex flex-col justify-start w-full h-full p-3 text-left'   // 버튼은 내용을 세로 가운데에 두므로 위로 붙인다
  return (
    <div className={`relative h-full min-w-0 bg-card border rounded-card ${selected ? 'border-accent' : 'border-line'}`}>
      {onSelect
        ? <button type="button" onClick={onSelect} aria-pressed={!!selected} className={`${pad} bg-transparent border-0 rounded-card text-ink-1 cursor-pointer`}>{body}</button>
        : to ? <Link to={to} className={`${pad} no-underline text-ink-1 rounded-card`}>{body}</Link>
          : <div className={pad}>{body}</div>}
      {onWatch && <WatchStar on={!!watched} onToggle={onWatch} label={name} className="absolute top-1.5 right-1.5" />}
    </div>
  )
}

/** 관심 별(토글). 담김 = 검정 채움. 띠 카드·표 행이 같이 쓴다. */
export function WatchStar({ on, onToggle, label, className = '' }: { on: boolean; onToggle: () => void; label: string; className?: string }) {
  return (
    <button type="button" onClick={e => { e.stopPropagation(); onToggle() }} aria-pressed={on} aria-label={`${label} 관심 ${on ? '빼기' : '담기'}`}
      title={on ? '관심에서 빼기' : '관심에 담기'}
      className={`size-8 shrink-0 inline-flex items-center justify-center rounded-btn border-0 bg-transparent cursor-pointer ${on ? 'text-ink-1' : 'text-ink-3 hover:text-ink-1'} ${className}`}>
      <Star size={15} aria-hidden fill={on ? 'currentColor' : 'none'} />
    </button>
  )
}

/**
 * 순위 표 열 정의. get = 정렬·기본 표시 값(숫자면 fmtNumber(decimals)), render = 칸 모양(없으면 get).
 * role = 모바일(<768) 2열 자리: name·sub 는 왼쪽 두 줄, value·change 는 오른쪽 두 줄. role 없는 열은 행을 누르면 시트에 나온다.
 */
export type Col<R> = {
  key: string
  label: string
  get: (r: R) => number | string | null | undefined
  render?: (r: R) => ReactNode
  num?: boolean
  decimals?: number
  role?: 'name' | 'sub' | 'value' | 'change'
}

// 빈 값은 뒤로(정렬 방향과 무관)
function cmp(a: unknown, b: unknown): number | null {
  const na = a == null || a === '', nb = b == null || b === ''
  if (na || nb) return na && nb ? 0 : null
  return typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b), 'ko')
}

/**
 * 순위 표: 머리 32px, 숫자 열 오른쪽 정렬·고정폭, 빈칸 「—」, 머리 누르면 정렬(⇅ → ▼ → ▲ → 원래 순서).
 * lead = 행 앞 칸(관심 별 등 버튼 자리). 모바일은 2열로 접고 행을 누르면 BottomSheet 에 나머지 열.
 * onPick 을 주면 행 누르기 = 그 행 고르기(selectedKey 와 rowKey 가 같은 행이 옅은 바탕). 모바일도 시트 대신 onPick 이다.
 * 행이 많으면 More(모바일 5 · PC 10행 + 「N행 더 보기」) — 정렬은 전체 행에 먼저 건다.
 * 행 전체가 마우스 자리이고, 키보드·읽기 도구용으로 이름 칸 내용을 버튼으로 감싼다(핸들러 없이 행으로 버블링).
 */
export function RankTable<R>({ cols, rows, rowKey, lead, label, onPick, selectedKey }: {
  cols: Col<R>[]; rows: R[]; rowKey: (r: R) => string; lead?: (r: R) => ReactNode; label: string
  onPick?: (r: R) => void; selectedKey?: string | null
}) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null)
  const [sheet, setSheet] = useState<R | null>(null)
  const shown = useMemo(() => {
    const c = sort && cols.find(x => x.key === sort.key)
    if (!sort || !c) return rows
    return [...rows].sort((a, b) => {
      const va = c.get(a), vb = c.get(b), r = cmp(va, vb)
      return r == null ? (va == null || va === '' ? 1 : -1) : r * sort.dir
    })
  }, [rows, cols, sort])
  const cycle = (k: string) => setSort(s => (!s || s.key !== k ? { key: k, dir: -1 } : s.dir === -1 ? { key: k, dir: 1 } : null))
  const cell = (c: Col<R>, r: R): ReactNode => {
    if (c.render) return c.render(r) ?? '—'
    const v = c.get(r)
    return v == null || v === '' ? '—' : typeof v === 'number' ? fmtNumber(v, c.decimals ?? 0) : v
  }
  const text = (c: Col<R> | undefined, r: R) => { const v = c?.get(r); return v == null || v === '' ? '—' : typeof v === 'number' ? fmtNumber(v, c!.decimals ?? 0) : v }
  const by = (role: Col<R>['role']) => cols.find(c => c.role === role)
  const [nameC, subC, valueC, changeC] = [by('name'), by('sub'), by('value'), by('change')]
  const rest = cols.filter(c => !c.role)
  const pickC = nameC ?? cols[0]
  const isOn = (r: R) => selectedKey != null && rowKey(r) === selectedKey

  return <More rows={shown} name={label}>{vis => (
    <div className="min-w-0">
      <div className="table-box hidden md:block">
        <table className="w-full border-collapse text-13">
          <caption className="sr-only">{label}</caption>
          <thead>
            <tr className="h-8 border-b border-line">
              {lead && <th scope="col" className="w-8 p-0"><span className="sr-only">관심</span></th>}
              {cols.map(c => {
                const on = sort?.key === c.key
                return (
                  <th key={c.key} scope="col" aria-sort={on ? (sort!.dir === 1 ? 'ascending' : 'descending') : 'none'}
                    className={`px-2 py-0 font-normal text-12 text-ink-3 whitespace-nowrap ${c.num ? 'text-right' : 'text-left'}`}>
                    <button type="button" onClick={() => cycle(c.key)}
                      className={`h-8 inline-flex items-center gap-1 p-0 border-0 bg-transparent cursor-pointer text-12 ${on ? 'text-ink-1 font-bold' : 'text-ink-3 hover:text-ink-1'}`}>
                      {c.label}<span aria-hidden className="text-11">{on ? (sort!.dir === 1 ? '▲' : '▼') : '⇅'}</span>
                    </button>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {vis.map(r => {
              const on = isOn(r)
              return (
                <tr key={rowKey(r)} onClick={onPick && (() => onPick(r))}
                  className={`h-10 border-b border-line last:border-b-0 ${onPick ? 'cursor-pointer hover:bg-ink-3/5' : ''} ${on ? 'bg-ink-3/10' : ''}`}>
                  {lead && <td className="w-8 p-0">{lead(r)}</td>}
                  {cols.map(c => (
                    <td key={c.key} className={`px-2 py-1 ${c.num ? 'text-right num' : ''}`}>
                      {onPick && c === pickC
                        ? <button type="button" aria-pressed={on} className={`p-0 border-0 bg-transparent text-left cursor-pointer ${on ? 'font-bold' : ''}`}>{cell(c, r)}</button>
                        : cell(c, r)}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <ul className="md:hidden m-0 p-0 list-none" aria-label={label}>
        {vis.map(r => {
          const inner = (
            <>
              <span className="min-w-0">
                <span className="block text-13 font-bold text-ink-1">{text(nameC, r)}</span>
                {subC && <span className="block num text-12 text-ink-3">{cell(subC, r)}</span>}
              </span>
              <span className="shrink-0 text-right">
                {valueC && <span className="block num text-13 text-ink-1">{cell(valueC, r)}</span>}
                {changeC && <span className="block num text-12">{cell(changeC, r)}</span>}
              </span>
            </>
          )
          const row = 'flex-1 min-w-0 flex items-center justify-between gap-3 py-2 text-left'
          const on = isOn(r)
          return (
            <li key={rowKey(r)} className={`flex items-center gap-1 border-b border-line last:border-b-0 ${on ? 'bg-ink-3/10' : ''}`}>
              {lead?.(r)}
              {onPick || rest.length
                ? <button type="button" onClick={() => (onPick ? onPick(r) : setSheet(r))} aria-pressed={onPick ? on : undefined}
                  className={`${row} bg-transparent border-0 cursor-pointer`}>{inner}</button>
                : <div className={row}>{inner}</div>}
            </li>
          )
        })}
      </ul>
      <BottomSheet open={sheet != null} onClose={() => setSheet(null)} title={sheet != null ? String(text(nameC, sheet)) : label}>
        {sheet != null && (
          <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-13">
            {rest.map(c => (
              <Fragment key={c.key}>
                <dt className="text-ink-3">{c.label}</dt>
                <dd className={`m-0 ${c.num ? 'text-right num' : ''}`}>{cell(c, sheet)}</dd>
              </Fragment>
            ))}
          </dl>
        )}
      </BottomSheet>
    </div>
  )}</More>
}
