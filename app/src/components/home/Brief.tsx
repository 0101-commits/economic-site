// 홈 AI 요약(C6 · 과제 1). 머리(작성 시각 · 회차 넘김) → 문장(끝에 근거 번호) → 접힘 단추(모바일) → 대조 한 줄 · 근거 목록 → 꼬리말 → 질문칸(children).
// 문장 · 근거 · 대조는 묶음 home.brief(계약 C3)에서만 — 묶음에 items 가 없으면(옛 묶음) 지금처럼 lines 만 그린다.
// 회차 넘김: 그날 파일 briefs/<day>.json(사이트 루트, 풀 런마다 한 회차) — 못 받으면 넘김 단추 없이 지금 회차 하나.
// 모바일(980 미만)은 2줄 + 「외 n줄 · 근거 n」 접힘, PC 는 다 편다(접힘은 CSS 로만 가른다 — PC 에선 접힘 상태가 뜻이 없다).
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react'
import { ROOT, type HomeBundle } from '../../lib/bundle'
import { mdHm, shortDate } from '../../lib/format'
import { kstDay } from '../../lib/personal/calc'
import { briefItems, briefRuns, briefSources, checkLine } from './model'

/** 오늘 한 줄 · AI 요약: 숫자 낱말(+1.80% · 4,910억)만 굵게 검정. 묶음에 핵심어 표시가 아직 없어서다. */
const KEY_RE = /([+\-]?\d[\d,.]*(?:%p|%|bp|억|조|원|달러|엔)?)/
export function emphasize(text: string): ReactNode {
  return text.split(KEY_RE).map((t, i) => (i % 2 ? <b key={i} className="num font-bold text-ink-1">{t}</b> : t))
}

/** 묶음 brief + 근거 칸(C3 — 아직 없는 묶음도 있다). */
type BriefData = NonNullable<HomeBundle['brief']> & { day?: string; items?: unknown; sources?: unknown; dropped?: unknown; check?: unknown }
const NAV = 'inline-flex items-center gap-0.5 h-8 px-1.5 rounded-btn border-0 bg-transparent cursor-pointer text-12 font-normal text-ink-2 hover:text-ink-1'

export default function Brief({ brief, children }: { brief?: BriefData | null; children?: ReactNode }) {
  const today = kstDay()
  const day = brief?.day ?? (brief?.asOf ? kstDay(Date.parse(brief.asOf)) : '')
  const fresh = briefItems(brief)
  // 그날 회차 파일 — 새 모양(items 가 있는 묶음)일 때만, 새 회차(asOf)가 오면 다시 받는다
  const [file, setFile] = useState<unknown>(null)
  useEffect(() => {
    if (!fresh || !/^\d{4}-\d{2}-\d{2}$/.test(day)) return
    let live = true
    fetch(new URL(`briefs/${day}.json`, ROOT), { cache: 'no-cache' }).then(r => (r.ok ? r.json() : null)).then(j => { if (live) setFile(j) }, () => {})
    return () => { live = false }
  }, [day, brief?.asOf, !!fresh])
  const { runs, cur } = useMemo(() => briefRuns(file, { ...(brief ?? { lines: [] }), day }), [file, brief, day])
  const [pick, setPick] = useState<string | null>(null)   // 고른 회차 시각(없으면 지금 회차) — 다시 읽기로 회차가 늘어도 고른 것을 지킨다
  const [open, setOpen] = useState(false)
  const at = pick ? runs.findIndex(r => r.at === pick) : -1
  const i = at >= 0 ? at : cur
  const run = runs[i]
  const items = i === cur ? fresh : briefItems(run)
  const srcs = items ? briefSources(run) : []
  const chk = items ? checkLine(run) : null
  const lines = run?.lines ?? []

  // 작성 시각: 지금 회차는 오늘(KST) 것이면 시각만(「10:11」), 지난 것은 날짜까지 — 숫자 문장이 지금 값과 달라도 언제 쓴 글인지 보이게
  const head = i === cur
    ? (brief?.asOf ? (kstDay(Date.parse(brief.asOf)) !== today ? mdHm(brief.asOf) : run?.at) : '')
    : (day && day !== today ? `${shortDate(day)} ${run?.at}` : run?.at)
  const prev = runs[i - 1], next = runs[i + 1]
  const rest = items ? Math.max(0, items.length - 2) : 0

  return (
    <section aria-labelledby="home-brief" className="-mt-2 max-w-[44em]">
      <div className="mb-1 flex flex-wrap items-center gap-x-2">
        <h2 id="home-brief" className="m-0 flex flex-wrap items-baseline gap-x-2 text-12 font-bold text-ink-2">
          AI 요약{head && <span className="num font-normal text-ink-3">{head} 작성</span>}
        </h2>
        {runs.length > 1 && (
          <span className="ml-auto inline-flex items-center">
            {prev && <button type="button" className={NAV} onClick={() => setPick(prev.at)} aria-label={`이전 회차 ${prev.at}`}><ChevronLeft size={14} aria-hidden /><span className="num">{prev.at}</span></button>}
            {next && <button type="button" className={NAV} onClick={() => setPick(next.at)} aria-label={`다음 회차 ${next.at}`}><span className="num">{next.at}</span><ChevronRight size={14} aria-hidden /></button>}
          </span>
        )}
      </div>
      {items ? (
        <>
          <ul className="m-0 pl-5 list-disc marker:text-ink-3 flex flex-col gap-1 text-13 text-ink-2">
            {items.map((it, k) => (
              <li key={k} className={k >= 2 && !open ? 'hidden pc:list-item' : undefined}>
                {emphasize(it.text)}
                {it.refs.length > 0 && <span className="num ml-1 text-11 text-ink-3">{it.refs.map(n => `[${n}]`).join('')}</span>}
              </li>
            ))}
          </ul>
          {(rest > 0 || srcs.length > 0 || chk) && (
            <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
              className="pc:hidden inline-flex items-center gap-1 h-8 mt-1 px-0 border-0 bg-transparent cursor-pointer text-12 text-ink-2 hover:text-ink-1">
              {open ? '접기' : <>{rest > 0 && <>외 <span className="num">{rest}</span>줄 · </>}근거 <span className="num">{srcs.length}</span></>}
              <ChevronDown size={14} aria-hidden className={open ? 'rotate-180' : ''} />
            </button>
          )}
          {(chk || srcs.length > 0) && (
            <div className={`${open ? '' : 'hidden pc:block'} mt-2 flex flex-col gap-1`}>
              {chk && <p className="m-0 text-12 text-ink-3">{chk}</p>}
              {srcs.length > 0 && (
                <ol aria-label="근거" className="m-0 p-0 list-none flex flex-col gap-1 text-12">
                  {srcs.map(s => (
                    <li key={s.n} className="flex items-baseline gap-2 min-w-0">
                      <span className="num w-7 shrink-0 text-ink-3">[{s.n}]</span>
                      {s.kind && <span className="shrink-0 text-ink-3">{s.kind}</span>}
                      <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                        {s.url ? <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-ink-1 no-underline hover:underline">{s.label}</a>
                          : <span className="text-ink-1">{s.label}</span>}
                        {(s.src || s.at) && <span className="text-ink-3"> · {[s.src, s.at].filter(Boolean).join(' · ')}</span>}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
          <p className="m-0 mt-2 text-11 text-ink-3">AI 요약은 참고용이며 숫자는 근거 값이 기준입니다</p>
        </>
      ) : lines.length ? (
        <ul className="m-0 pl-5 list-disc marker:text-ink-3 flex flex-col gap-1 text-13 text-ink-2">
          {lines.map((l, k) => <li key={k}>{emphasize(l)}</li>)}
        </ul>
      ) : <p className="m-0 text-13 text-ink-3">AI 요약이 아직 없습니다.</p>}
      {children}
    </section>
  )
}
