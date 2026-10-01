// 렌즈 — 기획안 v4 5장. 머리(이름 · 기준) → 국면 띠 → 평문 한 줄 → 띠 카드 5 → 모드 3(주소 m=whatif|chain|flow).
// 자료는 bundles/lens.json 하나. 운영 규칙(모드 전체):
//   상태어는 돌파·주시·정상 / 도달·추정·미도달 만. 실측 실선 · 추정 점선. 글은 제목·날짜·링크만, 본문 전재 없음. 금액 계산 없음.
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Telescope } from 'lucide-react'
import { SegBar } from '../components/ui'
import { loadBundle } from '../lib/bundle'
import { changeDir, fmtChange, mdHm, shortDate } from '../lib/format'
import { useViewParam } from '../lib/useViewParam'
import { josaRo, rankChains, type LensBundle, type Regime } from '../components/lens/model'
import { StatCard, postUrl } from '../components/lens/parts'
import WhatIf from '../components/lens/WhatIf'
import ChainView from '../components/lens/ChainView'
import FlowView, { RegimeBand, thisMonth } from '../components/lens/FlowView'

const MODES = [{ key: 'whatif', label: '만약에' }, { key: 'chain', label: '사슬' }, { key: 'flow', label: '흐름' }] as const
type Mode = typeof MODES[number]['key']
const DIR_TEXT = { up: 'text-up', down: 'text-down', flat: 'text-ink-2' } as const
const ymd = (d: string) => d.slice(2, 10).replace(/-0?/g, '.')   // 2025-09-16 → 25.9.16

/** 평문 한 줄: 국면 전환(또는 몇 달째) + 돌파·주시 수. 숫자는 묶음에서 센 것만. */
function regimeLine(r: Regime | undefined, total: number, crossed: number, near: number): string {
  const tail = `지표 ${total}개 중 돌파 ${crossed}개 · 주시 ${near}개입니다.`
  const i = (r?.months.length ?? 0) - 1
  if (!r || i < 0) return tail
  const d = r.dominant
  const m = r.months[i]
  const open = m === thisMonth() ? `(${+m.slice(5, 7)}월은 집계 중, 언급 ${(r.counts[i] || []).reduce((a, x) => a + x, 0)}건)` : ''
  if (i > 0 && d[i] !== d[i - 1]) return `국면이 ${d[i - 1]}에서 ${d[i]}${josaRo(d[i])} 바뀌었습니다${open}. ${tail}`
  let k = 1
  while (i - k >= 0 && d[i - k] === d[i]) k++
  return `국면은 ${k}달째 ${d[i]}입니다${open}. ${tail}`
}

const others = (xs: { label: string }[]) => (xs.length ? `${xs[0].label}${xs.length > 1 ? ` 외 ${xs.length - 1}` : ''}` : '없음')

export default function Lens() {
  const [b, setB] = useState<LensBundle | null>(null)
  const [err, setErr] = useState(false)
  useEffect(() => { loadBundle<LensBundle>('lens').then(setB, () => setErr(true)) }, [])
  const [m] = useViewParam<Mode>('m', 'whatif', MODES.map(o => o.key))
  const [, setParams] = useSearchParams()
  // 모드를 바꾸면 고른 것(s)은 모드마다 뜻이 달라 함께 지운다 — 한 번에 바꿔야 두 갱신이 서로 덮지 않는다
  const setMode = (k: Mode) => setParams(p => {
    const q = new URLSearchParams(p)
    if (k === 'whatif') q.delete('m'); else q.set('m', k)
    q.delete('s')
    return q
  }, { replace: true })
  const best = useMemo(() => (b ? rankChains(b.chains, new Map(b.triggers.map(t => [t.id, t])))[0] : undefined), [b])

  if (err) return <p className="m-0 text-14 text-ink-2">렌즈 자료를 불러오지 못했습니다.</p>
  if (!b) return <p className="m-0 text-14 text-ink-3">불러오는 중</p>

  const crossed = b.triggers.filter(t => t.state === 'crossed')
  const near = b.triggers.filter(t => t.state === 'near')
  const latest = b.posts.reduce<LensBundle['posts'][number] | undefined>((a, p) => (!a || p.date > a.date ? p : a), undefined)
  const score = b.lens?.score ?? b.today?.score ?? null
  const delta = b.today?.delta30d
  const basis = b.coverage?.posts != null ? `메르 글 ${b.coverage.posts}편 기준`
    : b.window ? `메르 글 ${ymd(b.window.from)}~${ymd(b.window.to)} 기준` : '메르 글 기준'

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h1 className="m-0 inline-flex items-center gap-1.5 text-18 font-bold text-ink-1"><Telescope size={18} aria-hidden />렌즈</h1>
        <span className="text-12 text-ink-3">{basis} · 신호 갱신 <span className="num">{mdHm(b.asOf)}</span></span>
      </header>

      {b.regime && <RegimeBand regime={b.regime} />}

      <p className="m-0 text-13 text-ink-2 max-w-[44em]">{regimeLine(b.regime, b.triggers.length, crossed.length, near.length)}</p>

      <div className="grid grid-cols-2 sm:grid-cols-3 pc:grid-cols-5 gap-2">
        <StatCard label="렌즈 점수" value={score ?? '—'}
          sub={delta != null ? <span className={`num ${DIR_TEXT[changeDir(delta, 0)]}`}>30일 {fmtChange(delta, null, 0)}</span> : undefined} />
        <StatCard label="돌파" value={crossed.length} sub={others(crossed)} />
        <StatCard label="주시" value={near.length} sub={others(near)} />
        <StatCard label="가장 진행된 사슬" value={best ? `${best.done}/${best.total}` : '—'} sub={best?.c.label} />
        <StatCard label="최근 글" value={latest ? shortDate(latest.date) : '—'}
          sub={latest?.title ? <a href={postUrl(latest.logNo)} target="_blank" rel="noopener noreferrer" className="text-ink-3 hover:text-ink-1">{latest.title}</a> : undefined} />
      </div>

      <SegBar label="렌즈 모드" options={MODES} value={m} onChange={setMode} />

      {m === 'whatif' ? <WhatIf b={b} /> : m === 'chain' ? <ChainView b={b} /> : <FlowView b={b} />}
    </div>
  )
}
