// 검색 오버레이 — 기획안 v4 7장. 머리 돋보기(PC 검색창 · `/` 단축키 · 모바일 아이콘)가 연다.
// 결과: 지표(지표 사전 label·short·id 부분 일치) · 화면·보기(고정 목록) · 도구 + 따로 묶은 「메르 글」
// (merblog.json 제목 전체 · 최신 20편 전문 — 전문에서 찾으면 일치한 곳 앞뒤 40자를 보인다).
// 입력이 비었으면 「목적으로 고르기」(묶음에 자료가 있는 것만)와 「최근 본 것」. 금액은 싣지 않는다(내 자산 자료를 읽지 않는다).
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronRight, Search, X } from 'lucide-react'
import { Pill } from '../ui'
import { loadRegistry, type RegRow } from '../../lib/bundle'
import { shortDate } from '../../lib/format'
import { loadMarketData, loadRootJson } from '../../lib/personal/data'
import { pushRecent, readRecent, type Recent } from '../../lib/personal/store'

type Kind = '지표' | '화면' | '글' | '도구'
/** snip = 전문에서 찾은 곳 [앞 40자, 일치, 뒤 40자] */
type Hit = { kind: Kind; label: string; sub?: string; to?: string; href?: string; snip?: [string, string, string] }
type Fixed = Hit & { keys: string }

// 화면·보기 고정 목록 — 시장 자산군 7(screens/Market.tsx ASSETS) · 렌즈 모드 3(screens/Lens.tsx MODES) · 내 자산 · 알림
const SCREENS: Fixed[] = [
  ...([['kr', '국내', 'kospi 코스피 코스닥 주식'], ['global', '해외', '미국 나스닥 s&p 지수'], ['fxrate', '환율금리', '환율 금리 달러 국채'],
    ['commod', '원자재', '유가 금 구리 wti'], ['macro', '거시', 'cpi 물가 gdp 고용'], ['flow', '수급', '외국인 기관 개인 순매수'], ['estate', '부동산', '아파트 주택 전세']] as const)
    .map(([k, l, keys]): Fixed => ({ kind: '화면', label: `시장 · ${l}`, to: `/market?a=${k}`, keys: `시장 ${l} ${keys}` })),
  ...([['whatif', '만약에', '시나리오 what-if'], ['chain', '사슬', '연결 고리'], ['flow', '흐름', '흐름']] as const)
    .map(([k, l, keys]): Fixed => ({ kind: '화면', label: `렌즈 · ${l}`, to: `/lens?m=${k}`, keys: `렌즈 메르 위험 ${l} ${keys}` })),
  { kind: '화면', label: '내 자산', to: '/my', keys: '내 자산 보유 포트폴리오 평가액 손익' },
  { kind: '화면', label: '알림', to: '/alerts', keys: '알림 조건 받은 알림 푸시' },
]
const TOOLS: Fixed[] = [
  { kind: '도구', label: '환율 what-if', sub: '내 자산 · 달러원이 움직이면 총평가는', to: '/my', keys: '환율 달러원 what-if whatif 만약 시나리오 fx' },
]

type Post = { title: string; url: string; date?: string; fullText?: string }
const SNIP = 40

export function SearchOverlay({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [reg, setReg] = useState<RegRow[]>([])
  const [posts, setPosts] = useState<Post[] | null>(null)
  const [purpose, setPurpose] = useState<Hit[]>([])
  const [recent, setRecent] = useState<Recent[]>([])

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) { d.showModal(); setQ(''); setRecent(readRecent()) }
    if (!open && d.open) d.close()
  }, [open])

  // 처음 열 때 한 번: 지표 사전 + 목적 칩(묶음에 자료가 있는 것만)
  useEffect(() => {
    if (!open || reg.length) return
    loadRegistry().then(setReg, () => {})
    loadMarketData().then(md => {
      const p: Hit[] = []
      // 시장 주소는 market-screen 이 정한 보기(v)·범위(m) — m=all 이 없으면 코스피만이라 상승·하락이 1~2행으로 줄어든다
      if (md.home?.topAmount?.items.length) p.push({ kind: '화면', label: '거래대금 상위', to: '/market?a=kr&v=amount&m=all' })
      if (md.gainers) p.push({ kind: '화면', label: '오른 종목', to: '/market?a=kr&v=gainers&m=all' })
      if (md.losers) p.push({ kind: '화면', label: '내린 종목', to: '/market?a=kr&v=losers&m=all' })
      const breach = md.home?.lens?.breach[0]
      if (breach) p.push({ kind: '화면', label: '렌즈 돌파', to: `/lens?s=${encodeURIComponent(breach.id)}` })
      if (md.home?.investors?.today) p.push({ kind: '화면', label: '외국인 수급', to: '/market?a=flow' })
      setPurpose(p)
    }, () => {})
  }, [open, reg.length])

  // 메르 글(1MB 넘는 파일)은 검색을 처음 열 때 한 번 받는다
  const s = q.trim().toLowerCase()
  useEffect(() => {
    if (!open || posts) return
    loadRootJson<{ posts?: Post[] }>('merblog.json').then(m => setPosts((m.posts || []).map(p => ({ title: p.title, url: p.url, date: p.date, fullText: p.fullText }))), () => setPosts([]))
  }, [open, posts])

  const hits = useMemo((): Hit[] => {
    if (!s) return []
    const has = (...xs: (string | undefined)[]) => xs.some(x => x?.toLowerCase().includes(s))
    return [
      ...reg.filter(r => has(r.label, r.short, r.shortM, r.id)).slice(0, 8).map((r): Hit => ({ kind: '지표', label: r.short || r.label, sub: r.short && r.short !== r.label ? r.label : r.id, to: `/i/${r.id}` })),
      ...SCREENS.filter(x => has(x.label, x.keys)),
      ...TOOLS.filter(x => has(x.label, x.keys)),
    ]
  }, [s, reg])

  // 메르 글: 제목이나 전문에 든 글 8편까지(묶음 차례 = 최신순)
  const postHits = useMemo((): Hit[] => {
    if (!s || !posts) return []
    const out: Hit[] = []
    for (const p of posts) {
      const ft = p.fullText ?? '', i = ft.toLowerCase().indexOf(s)
      if (i < 0 && !p.title.toLowerCase().includes(s)) continue
      const e = i + s.length
      out.push({
        kind: '글', label: p.title, sub: p.date ? `메르 블로그 · ${shortDate(p.date)}` : '메르 블로그', href: p.url,
        snip: i < 0 ? undefined : [`${i > SNIP ? '…' : ''}${ft.slice(Math.max(0, i - SNIP), i)}`, ft.slice(i, e), `${ft.slice(e, e + SNIP)}${e + SNIP < ft.length ? '…' : ''}`],
      })
      if (out.length >= 8) break
    }
    return out
  }, [s, posts])

  const pick = (h: Hit) => {
    pushRecent({ label: h.label, to: h.to ?? h.href ?? '', kind: h.kind })
    onClose()
    if (h.to) nav(h.to)
  }

  return (
    <dialog ref={ref} onClose={onClose} aria-label="검색"
      className="m-0 p-0 border-0 w-full h-full max-w-none max-h-none bg-bg text-ink-1 backdrop:bg-ink-1/40">
      <div className="mx-auto max-w-[720px] px-4 py-3 flex flex-col gap-4">
        <form role="search" onSubmit={e => { e.preventDefault(); const h = hits[0] ?? postHits[0]; if (h) { if (h.href) window.open(h.href, '_blank', 'noopener'); pick(h) } }}
          className="flex items-center gap-2">
          <div className="relative flex-1 min-w-0">
            <Search size={16} aria-hidden className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" />
            {/* 글자가 든 search 칸의 Esc 는 브라우저가 칸 비우기에 써서 창이 안 닫힌다 — 여기서 바로 닫는다 */}
            <input type="search" autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="지표 · 화면 · 글 검색" aria-label="검색어"
              onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); onClose() } }}
              className="w-full h-11 pl-8 pr-3 rounded-btn border border-line bg-card text-14 text-ink-1 placeholder:text-ink-3" />
          </div>
          <button type="button" onClick={onClose} aria-label="검색 닫기" title="닫기 (Esc)"
            className="size-11 shrink-0 inline-flex items-center justify-center rounded-btn border border-line bg-card text-ink-2 cursor-pointer"><X size={18} aria-hidden /></button>
        </form>

        {s ? (
          hits.length || postHits.length ? (
            <>
              {hits.length > 0 && <HitList hits={hits} onPick={pick} label="검색 결과" />}
              {postHits.length > 0 && (
                <section>
                  <h2 className="m-0 mb-2 text-13 font-bold text-ink-1">메르 글 <span className="num text-ink-3">{postHits.length}</span></h2>
                  <HitList hits={postHits} onPick={pick} label="메르 글" />
                </section>
              )}
            </>
          ) : (
            <p className="m-0 text-13 text-ink-3">{posts ? '찾은 것이 없습니다. 지표 이름이나 코드(예: kospi, 달러)로 찾아보세요.' : '찾는 중'}</p>
          )
        ) : (
          <>
            {purpose.length > 0 && (
              <section>
                <h2 className="m-0 mb-2 text-13 font-bold text-ink-1">목적으로 고르기</h2>
                <ul className="m-0 p-0 list-none flex flex-wrap gap-2">
                  {purpose.map(h => (
                    <li key={h.label}>
                      <button type="button" onClick={() => pick(h)}
                        className="h-8 px-3 rounded-chip border border-line bg-card text-13 text-ink-1 cursor-pointer hover:border-accent whitespace-nowrap">{h.label}</button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <section>
              <h2 className="m-0 mb-2 text-13 font-bold text-ink-1">최근 본 것</h2>
              {recent.length
                ? <HitList label="최근 본 것" onPick={pick} hits={recent.map((r): Hit => ({ kind: (r.kind as Kind) || '화면', label: r.label, ...(r.to.startsWith('/') ? { to: r.to } : { href: r.to }) }))} />
                : <p className="m-0 text-13 text-ink-3">검색해서 연 것이 여기에 남습니다(이 기기에만).</p>}
            </section>
          </>
        )}
      </div>
    </dialog>
  )
}

function HitList({ hits, onPick, label }: { hits: Hit[]; onPick: (h: Hit) => void; label: string }) {
  return (
    <ul aria-label={label} className="m-0 p-0 list-none bg-card border border-line rounded-card">
      {hits.map((h, i) => {
        const body = (
          <>
            <Pill tone="o">{h.kind}</Pill>
            <span className="flex-1 min-w-0">
              <span className="block text-14 text-ink-1">{h.label}</span>
              {h.sub && <span className="block text-12 text-ink-3">{h.sub}</span>}
              {h.snip && <span className="block mt-0.5 text-12 text-ink-2 [overflow-wrap:anywhere]">{h.snip[0]}<b className="text-ink-1">{h.snip[1]}</b>{h.snip[2]}</span>}
            </span>
            <ChevronRight size={14} aria-hidden className="shrink-0 text-ink-3" />
          </>
        )
        const cls = 'w-full flex items-center gap-3 px-3 py-2.5 text-left no-underline bg-transparent border-0 cursor-pointer'
        return (
          <li key={`${h.kind}-${h.to ?? h.href}-${i}`} className="border-b border-line last:border-b-0">
            {h.href
              ? <a href={h.href} target="_blank" rel="noopener noreferrer" className={cls} onClick={() => onPick(h)}>{body}</a>
              : <button type="button" className={cls} onClick={() => onPick(h)}>{body}</button>}
          </li>
        )
      })}
    </ul>
  )
}
