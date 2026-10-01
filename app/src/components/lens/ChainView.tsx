// 렌즈 「사슬」(m=chain) — 메르 글이 짚은 전이 경로 10개. 고른 사슬은 주소 s(사슬 id)에 남는다.
// 단계 판정(도달·추정·미도달)은 model.ts chainSteps 한 곳. 운영 규칙: 상태어는 돌파·주시·정상 / 도달·추정·미도달 만,
// 실측 실선 · 추정 점선, 글은 제목·날짜·링크만.
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Panel } from '../panels'
import { shortDate } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { STEP_WORD, chainSteps, rankChains, shortLabel, type LensBundle } from './model'
import { StepNum, TrigPill, asOfText, btn, postUrl, trigValue } from './parts'

export default function ChainView({ b }: { b: LensBundle }) {
  const trig = useMemo(() => new Map(b.triggers.map(t => [t.id, t])), [b])
  const ranked = useMemo(() => rankChains(b.chains, trig), [b, trig])
  const [s, setS] = useViewParam<string>('s', '')
  const cur = ranked.find(r => r.c.id === s) ?? ranked[0]   // 기본 = 가장 진행된 사슬
  if (!cur) return <p className="m-0 text-13 text-ink-3">사슬 자료가 없습니다.</p>

  const steps = chainSteps(cur.c, trig)
  const nodeIds = new Set(b.nodes.map(n => n.id))
  const first = cur.c.steps.find(st => nodeIds.has(st.id))?.id   // 「만약에」 지도에 있는 첫 점
  const posts = new Map(b.posts.map(p => [p.logNo, p]))
  const logNos = cur.c.logNos ?? []
  const meta = `글 ${cur.c.n ?? logNos.length}편${cur.c.lastDate ? ` · 최근 ${shortDate(cur.c.lastDate)}` : ''}`

  return (
    <div className="flex flex-col gap-3">
      {/* 사슬 칩 10 — 모바일은 한 줄 가로 밀기, PC 는 줄바꿈 */}
      <div role="group" aria-label="사슬 고르기" className="flex gap-1 overflow-x-auto pb-1 pc:flex-wrap pc:overflow-visible pc:pb-0">
        {ranked.map(r => (
          <button key={r.c.id} type="button" aria-pressed={r.c.id === cur.c.id} onClick={() => setS(r.c.id)} className={`${btn(r.c.id === cur.c.id)} shrink-0`}>
            {r.c.label}<span className="num text-11">{r.done}/{r.total}</span>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 pc:grid-cols-12 gap-4 items-start">
        <Panel className="pc:col-span-8" title={cur.c.label} source={meta}>
          {cur.c.note && <p className="m-0 mb-3 text-13 text-ink-2 max-w-[44em]">{cur.c.note}</p>}
          <ol aria-label={`${cur.c.label} 단계`} className="m-0 p-0 list-none">
            {steps.map((st, i) => {
              const v = trigValue(st.t)
              const next = steps[i + 1]
              return (
                <li key={i} className="flex gap-3">
                  <span className="flex flex-col items-center">
                    <StepNum n={i + 1} kind={st.state === 'reached' ? 'solid' : st.state === 'guess' ? 'guess' : 'off'} />
                    {next && <span aria-hidden className={`flex-1 w-0 min-h-3 border-l ${next.state === 'guess' ? 'border-dashed border-warn' : 'border-line'}`} />}
                  </span>
                  <div className="min-w-0 flex-1 pb-3 flex flex-wrap items-center gap-x-2 gap-y-1 min-h-6">
                    <span className="text-13 font-bold text-ink-1">{shortLabel(st.label)}</span>
                    {v && <span className="num text-13 text-ink-1">{v}</span>}
                    {st.t?.asOf && <span className="num text-11 text-ink-3">{asOfText(st.t.asOf)}</span>}
                    <TrigPill t={st.t} />
                    <span className="text-11 text-ink-3">{STEP_WORD[st.state]}{st.repeat ? ' · 처음 칸으로 되돌아옴' : ''}</span>
                  </div>
                </li>
              )
            })}
          </ol>
          <p className="m-0 mb-3 text-11 text-ink-3">채운 번호 = 도달(지표가 기준을 넘음) · 점선 번호 = 추정(잴 지표가 없고 앞 단계가 도달) · 회색 = 미도달.</p>
          <div className="flex flex-wrap items-center gap-2">
            {logNos.length ? (
              <details className="w-full">
                <summary className={`${btn()} w-fit list-none [&::-webkit-details-marker]:hidden`}>글 {logNos.length}편</summary>
                <ul className="m-0 mt-2 p-0 list-none">
                  {logNos.map(no => {
                    const p = posts.get(no)
                    return (
                      <li key={no} className="py-1.5 border-b border-line last:border-b-0 text-13">
                        <a href={postUrl(no)} target="_blank" rel="noopener noreferrer" className="text-ink-1 no-underline hover:underline">{p?.title || '원문 열기'}</a>
                        {p?.date && <span className="ml-2 num text-11 text-ink-3">{shortDate(p.date)}</span>}
                      </li>
                    )
                  })}
                </ul>
              </details>
            ) : <span className="text-12 text-ink-3">글 {cur.c.n ?? 0}편 · 원문 목록 준비 중</span>}
            {first && <Link to={`/lens?m=whatif&s=${first}`} className={btn()}>만약에에서 열기</Link>}
          </div>
        </Panel>

        <Panel className="pc:col-span-4" title="다른 사슬">
          <ul className="m-0 p-0 list-none">
            {ranked.filter(r => r !== cur).map(r => (
              <li key={r.c.id} className="border-b border-line last:border-b-0">
                <button type="button" onClick={() => setS(r.c.id)} className="w-full py-2 flex items-center justify-between gap-3 bg-transparent border-0 text-left cursor-pointer">
                  <span className="min-w-0">
                    <span className="block text-13 text-ink-1">{r.c.label}</span>
                    <span className="block text-11 text-ink-3">글 {r.c.n ?? 0}편{r.c.lastDate ? <> · 최근 <span className="num">{shortDate(r.c.lastDate)}</span></> : null}</span>
                  </span>
                  <span className="shrink-0 num text-13 text-ink-2" aria-label={`도달 ${r.done} / ${r.total}`}>{r.done}/{r.total}</span>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  )
}
