// 렌즈 「흐름」(m=flow) — 달 12칸 국면 격자 + 고른 달(주소 s=YYYY-MM)의 요인 점수와 글.
// RegimeBand 는 렌즈 머리의 작은 국면 띠(같은 색 규칙). 국면 = regime.dominant(그 달 가장 많이 언급된 요인).
import { Link } from 'react-router-dom'
import { Panel } from '../panels'
import { DivergingBars } from '../charts'
import { shortDate } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import type { LensBundle, Regime } from './model'
import { postUrl } from './parts'

// 지배 요인 색: 정책 회색 · 지정학 상승색 · 유동성 검정. 이번 달(집계 중)은 옅게.
const FACTOR_VAR: Record<string, string> = { 정책: '--c-ink-3', 지정학: '--c-up', 유동성: '--c-ink-1' }
// ponytail: 셋 밖 요인은 한 색(하락색)으로 묶는다 — 지배 요인으로 셋 밖이 둘 이상 나오면 색을 더 나눈다
const OTHER_VAR = '--c-down'
// 옅게만 하면 검정(유동성)이 회색(정책)과 같아 보여서 같은 색 점선 테두리를 더한다
const factorStyle = (f: string, faint = false) => {
  const v = `var(${FACTOR_VAR[f] ?? OTHER_VAR})`
  return faint ? { background: `color-mix(in srgb, ${v} 40%, var(--c-card))`, outline: `1.5px dashed ${v}`, outlineOffset: -1.5 } : { background: v }
}
/** 한국 시각 이번 달 「YYYY-MM」. */
export const thisMonth = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit' }).format(new Date()).slice(0, 7)
const monthWord = (m: string) => `${m.slice(0, 4)}년 ${+m.slice(5, 7)}월`

function Legend({ regime }: { regime: Regime }) {
  const seen = [...new Set(regime.dominant)]
  return (
    <p className="m-0 flex flex-wrap items-center gap-x-3 gap-y-1 text-11 text-ink-3">
      {seen.map(f => (
        <span key={f} className="inline-flex items-center gap-1">
          <span aria-hidden className="size-2.5 rounded-chip" style={factorStyle(f)} />{f}
        </span>
      ))}
      <span>옅은 점선 칸 = 이번 달(집계 중)</span>
    </p>
  )
}

/** 머리의 국면 띠: 달 12칸, 칸을 누르면 「흐름」에서 그 달을 연다. */
export function RegimeBand({ regime }: { regime: Regime }) {
  const now = thisMonth()
  const ms = regime.months
  return (
    <div className="min-w-0 flex flex-col gap-1">
      <ol aria-label="달별 국면" className="m-0 p-0 list-none grid gap-0.5" style={{ gridTemplateColumns: `repeat(${ms.length}, minmax(0, 1fr))` }}>
        {ms.map((m, i) => (
          <li key={m}>
            <Link to={`/lens?m=flow&s=${m}`} title={`${shortDate(m)} ${regime.dominant[i]}`} aria-label={`${monthWord(m)} 국면 ${regime.dominant[i]}`}
              className="block h-6 rounded-inner" style={factorStyle(regime.dominant[i], m === now)} />
          </li>
        ))}
      </ol>
      <div className="flex justify-between text-11 text-ink-3 num"><span>{shortDate(ms[0])}</span><span>{shortDate(ms[ms.length - 1])}</span></div>
      <Legend regime={regime} />
    </div>
  )
}

export default function FlowView({ b }: { b: LensBundle }) {
  const r = b.regime
  const now = thisMonth()
  const [s, setS] = useViewParam<string>('s', '')
  if (!r?.months.length) return <p className="m-0 text-13 text-ink-3">국면 자료가 없습니다.</p>
  const def = r.months.includes(now) ? now : r.months[r.months.length - 1]   // 기본 = 이번 달
  const sel = r.months.includes(s) ? s : def
  const i = r.months.indexOf(sel)
  const dom = r.dominant[i], prev = i > 0 ? r.dominant[i - 1] : null
  const total = (r.counts[i] || []).reduce((a, x) => a + x, 0)
  const bars = r.factors.map((f, j) => ({ key: f, label: f, value: r.counts[i]?.[j] ?? null })).sort((x, y) => (y.value ?? 0) - (x.value ?? 0))
  const posts = b.posts.filter(p => p.date.startsWith(sel))
  const oldest = b.posts.reduce((a, p) => (p.date < a ? p.date : a), b.posts[0]?.date ?? '')

  return (
    <div className="flex flex-col gap-3">
      <ol aria-label="달 고르기" className="m-0 p-0 list-none grid grid-cols-4 sm:grid-cols-6 pc:grid-cols-12 gap-1">
        {r.months.map((m, k) => (
          <li key={m}>
            <button type="button" aria-pressed={m === sel} onClick={() => setS(m)} aria-label={`${monthWord(m)} 국면 ${r.dominant[k]}`}
              className={`w-full p-1 rounded-inner border bg-card cursor-pointer text-center ${m === sel ? 'border-accent' : 'border-transparent hover:border-line'}`}>
              <span aria-hidden className="block h-8 rounded-inner" style={factorStyle(r.dominant[k], m === now)} />
              <span className={`block mt-1 num text-12 ${m === sel ? 'font-bold text-ink-1' : 'text-ink-2'}`}>{shortDate(m)}</span>
              <span className="block text-11 text-ink-3">{r.dominant[k]}</span>
            </button>
          </li>
        ))}
      </ol>
      <Legend regime={r} />

      <div className="grid grid-cols-1 pc:grid-cols-12 gap-4 items-start">
        <Panel className="pc:col-span-6" title={`${monthWord(sel)} 요인 점수`} unit="언급 수">
          <p className="m-0 mb-3 text-12 text-ink-2">
            지배 요인 <b className="text-ink-1">{dom}</b>
            {prev && (prev === dom ? ' · 지난달과 같음' : ` · 지난달 ${prev}에서 바뀜`)}
            {sel === now && <> · 이번 달은 집계 중(언급 <span className="num">{total}</span>건)</>}
          </p>
          <DivergingBars label={`${monthWord(sel)} 요인별 언급 수`} bars={bars} />
        </Panel>

        <Panel className="pc:col-span-6" title={`${monthWord(sel)} 글·사건`}>
          {posts.length ? (
            <ul className="m-0 p-0 list-none">
              {posts.map(p => (
                <li key={p.logNo} className="py-1.5 border-b border-line last:border-b-0">
                  <a href={postUrl(p.logNo)} target="_blank" rel="noopener noreferrer" className="text-13 text-ink-1 no-underline hover:underline">{p.title || '원문 열기'}</a>
                  <span className="block num text-11 text-ink-3">{shortDate(p.date)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="m-0 text-13 text-ink-3">
              이 달의 글 목록은 아직 없습니다. 지금은 최근 글 {b.posts.length}편{oldest ? <>(<span className="num">{shortDate(oldest)}</span> 이후)</> : null}만 받습니다.
            </p>
          )}
        </Panel>
      </div>
    </div>
  )
}
