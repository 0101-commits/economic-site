// 렌즈 「만약에」(m=whatif) — 점 48 · 관계 79 의 노드 지도(Cytoscape, LensMap 이 그린다) + 시뮬레이션.
// 점을 고르고 ▲▼ 를 누르면 선을 따라 방향이 퍼진다(규칙은 model.ts propagate). 금액은 계산하지 않는다.
// 운영 규칙: 상태어는 돌파·주시·정상 / 도달·추정·미도달 만. 실측 실선 · 추정 점선. 글은 제목·날짜·링크만.
// 고른 점은 주소 s 에 남기고(공유 가능), 방향·깊이·애니메이션은 화면 안 상태다.
import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { Link as RLink } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { Card, SegBar } from '../ui'
import { heatBg, heatInk } from '../charts'
import { shortDate } from '../../lib/format'
import { useViewParam } from '../../lib/useViewParam'
import { LAYERS, links, propagate, shortLabel, type LensBundle, type Sign } from './model'
import { MAP_BOX, StepNum, TrigPill, asOfText, btn, postUrl, trigValue } from './parts'

// 지도는 보일 때만 받는다(cytoscape 는 별도 조각). 받지 못하면 그 칸만 알린다 — 화면 전체가 죽지 않게.
const MapNote = ({ text }: { text: string }) => <div className={`${MAP_BOX} flex items-center justify-center text-13 text-ink-3`}>{text}</div>
const LensMap = lazy(() => import('./LensMap').catch(() => ({ default: () => <MapNote text="지도를 불러오지 못했습니다" /> })))

const PC_MQ = '(min-width: 61.25rem)'   // app.css --breakpoint-pc 와 같은 값
const DEPTHS = [{ key: '1', label: '1단계' }, { key: '2', label: '2단계' }, { key: '3', label: '3단계' }] as const
type Depth = typeof DEPTHS[number]['key']
const LAYER_LABEL: Record<string, string> = Object.fromEntries(LAYERS.map(l => [l.key, l.label]))

// 저장: 이 기기 localStorage 만(이름 입력 없이 「시나리오 N」). 못 읽으면 빈 목록.
const SAVE_KEY = 'econ_scenarios_v1'
type Saved = { name: string; start: string; dir: Sign; depth: number; at: string }
function readSaved(): Saved[] {
  try {
    const v = JSON.parse(localStorage.getItem(SAVE_KEY) || '[]')
    return Array.isArray(v) ? v.filter(x => x && typeof x.start === 'string' && (x.dir === 1 || x.dir === -1)) : []
  } catch { return [] }
}

const HEAT_AT = [0, 0.5, 1, 2.5]       // 세기 → heatStep 경계값(1 → 1단 · 2 → 2단 · 3 → 3단)

const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches

export default function WhatIf({ b }: { b: LensBundle }) {
  const byId = useMemo(() => new Map(b.nodes.map(n => [n.id, n])), [b])
  const trig = useMemo(() => new Map(b.triggers.map(t => [t.id, t])), [b])
  const ls = useMemo(() => links(b.edges), [b])
  const short = (id: string) => shortLabel(byId.get(id)?.label ?? id)
  const [s, setS] = useViewParam<string>('s', '')
  const sel = byId.has(s) ? s : null
  const [dir, setDir] = useState<Sign | null>(null)
  const [depth, setDepth] = useState<Depth>('2')
  const [shown, setShown] = useState(0)
  const [saved, setSaved] = useState(readSaved)
  const [note, setNote] = useState('')
  const panel = useRef<HTMLDivElement>(null)

  // 전파 + 0.4초 단계 애니메이션(움직임 줄이기 설정이면 한 번에)
  const hits = useMemo(() => (sel && dir ? propagate(b.edges, sel, dir, +depth) : []), [b, sel, dir, depth])
  const maxStep = hits.length ? hits[hits.length - 1].step : 0
  useEffect(() => {
    if (!maxStep) { setShown(0); return }
    if (reduced()) { setShown(maxStep); return }
    let k = 1
    setShown(1)
    if (maxStep === 1) return
    const t = setInterval(() => { k += 1; setShown(k); if (k >= maxStep) clearInterval(t) }, 400)
    return () => clearInterval(t)
  }, [hits, maxStep])
  const vis = useMemo(() => hits.filter(h => h.step <= shown), [hits, shown])   // 지도와 목록이 같은 단계를 본다
  const hitOf = new Map(vis.map(h => [h.id, h]))

  const pick = (id: string) => {
    setS(id === sel ? '' : id)
    setDir(null)
    setNote('')
    // 모바일은 패널이 지도 아래라 고른 결과가 화면 밖이다 — 패널로 내려 준다
    if (id !== sel && !matchMedia(PC_MQ).matches) requestAnimationFrame(() => panel.current?.scrollIntoView({ block: 'start', behavior: reduced() ? 'auto' : 'smooth' }))
  }
  const save = () => {
    if (!sel || !dir) return
    const name = `시나리오 ${saved.length + 1}`
    const next = [...saved, { name, start: sel, dir, depth: +depth, at: new Date().toISOString() }]
    try { localStorage.setItem(SAVE_KEY, JSON.stringify(next)); setNote(`${name} 저장`) } catch { setNote('이 기기에 저장하지 못했습니다') }
    setSaved(next)
  }
  const reset = () => { setDir(null); setS(''); setNote('') }
  const restore = (x: Saved) => { if (!byId.has(x.start)) return; setS(x.start); setDir(x.dir); setDepth(String(Math.min(3, Math.max(1, x.depth))) as Depth); setNote('') }

  // 고른 점 패널
  const node = sel ? byId.get(sel)! : null
  const t = sel ? trig.get(sel) : undefined
  const inc = sel ? b.edges.filter(e => e.to === sel) : []
  const out = sel ? b.edges.filter(e => e.from === sel) : []
  const postN = new Set([...inc, ...out].flatMap(e => e.logNos || [])).size
  const quote = [...out, ...inc].flatMap(e => e.quotes || [])[0]
  const inChains = sel ? b.chains.filter(c => c.steps.some(st => st.id === sel)) : []
  const canPush = !!sel && ls.some(l => l.from === sel && l.net !== 0)
  const assets = b.nodes.filter(n => n.layer === 'asset')
  const changed = assets.filter(n => hitOf.has(n.id)).length

  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 text-13 text-ink-2 max-w-[44em]">
        점 = 메르 글에 나오는 지표·자산 {b.nodes.length}개 · 선 = 글에서 「A 가 B 를 움직인다」고 쓴 관계 {b.edges.length}개(굵을수록 여러 번 언급).
        점을 누르고 ▲▼ 를 밀면 선을 따라 방향이 퍼집니다. 방향과 세기만, 금액은 계산하지 않습니다.
      </p>

      <div className="grid grid-cols-1 pc:grid-cols-12 gap-4 items-start">
        <Card className="pc:col-span-8">
          {/* 지도는 캔버스라 키보드·읽기 도구가 점을 못 고른다 — 같은 고르기를 이 목록이 맡는다(좁은 화면에서 점 찾기에도 쓴다) */}
          <label className="mb-2 flex items-center gap-2 text-12 text-ink-3">
            <span className="shrink-0">출발점</span>
            <select value={sel ?? ''} onChange={e => (e.target.value ? pick(e.target.value) : reset())}
              className="h-8 min-w-0 max-w-full px-2 rounded-btn border border-line bg-card text-13 text-ink-1">
              <option value="">고르지 않음</option>
              {LAYERS.map(L => (
                <optgroup key={L.key} label={L.label}>
                  {b.nodes.filter(n => n.layer === L.key).map(n => <option key={n.id} value={n.id}>{n.label}</option>)}
                </optgroup>
              ))}
            </select>
          </label>
          <Suspense fallback={<MapNote text="지도 불러오는 중" />}>
            <LensMap nodes={b.nodes} ls={ls} vis={vis} sel={sel} onPick={pick} />
          </Suspense>
          <p className="m-0 mt-3 text-11 text-ink-3">
            선 색 = 방향(빨강 ▲ 상방 · 파랑 ▼ 하방 · 회색은 퍼지지 않음). 굵기 = 세기 1~3, 2단계부터는 점선(추정)입니다.
            점은 끌어 옮기고, 확대는 휠이나 두 손가락으로 합니다.
          </p>
        </Card>

        <div ref={panel} className="pc:col-span-4 flex flex-col gap-3 scroll-mt-4">
          <Card title={node ? node.label : '점을 고르세요'}>
            {!node ? (
              <p className="m-0 text-13 text-ink-3">지도에서 점을 누르면 근거와 연결이 나옵니다. 그다음 ▲ 또는 ▼ 를 누르면 선을 따라 방향이 퍼집니다.</p>
            ) : (
              <div className="flex flex-col gap-3">
                <p className="m-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-12 text-ink-2">
                  <span>{LAYER_LABEL[node.layer]}</span>
                  {trigValue(t) ? <span className="num text-13 font-bold text-ink-1">{trigValue(t)}</span> : t && <span className="text-ink-3">자료 없음</span>}
                  <TrigPill t={t} />
                  {t?.level != null && <span className="text-ink-3">기준 <span className="num">{trigValue({ ...t, value: t.level })}</span></span>}
                  {t?.asOf && <span className="num text-ink-3">{asOfText(t.asOf)}</span>}
                </p>
                {quote && (
                  <p className="m-0 text-12 text-ink-2">
                    「{quote.q}」 <a href={postUrl(quote.logNo)} target="_blank" rel="noopener noreferrer" className="num text-11">{quote.date ? shortDate(quote.date) : '원문'}</a>
                  </p>
                )}
                <dl className="m-0 grid grid-cols-3 gap-2 text-center">
                  {([['근거 글', postN], ['들어오는 선', inc.length], ['나가는 선', out.length]] as const).map(([k, n]) => (
                    <div key={k} className="rounded-inner border border-line py-1.5">
                      <dt className="text-11 text-ink-3">{k}</dt>
                      <dd className="m-0 num text-14 font-bold text-ink-1">{n}</dd>
                    </div>
                  ))}
                </dl>
                {inChains.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1 text-12">
                    <span className="mr-1 text-ink-3">속한 사슬</span>
                    {inChains.map(c => (
                      <RLink key={c.id} to={`/lens?m=chain&s=${c.id}`} className="h-6 px-2 inline-flex items-center rounded-chip border border-line text-12 text-ink-2 no-underline hover:text-ink-1">{c.label}</RLink>
                    ))}
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <button type="button" aria-pressed={dir === 1} disabled={!canPush} onClick={() => setDir(1)} className={btn(dir === 1)}>▲ 오르면</button>
                  <button type="button" aria-pressed={dir === -1} disabled={!canPush} onClick={() => setDir(-1)} className={btn(dir === -1)}>▼ 내리면</button>
                </div>
                {canPush
                  ? <div className="flex flex-wrap items-center gap-2"><span className="text-12 text-ink-3">깊이</span><SegBar label="퍼지는 깊이" options={DEPTHS} value={depth} onChange={setDepth} /></div>
                  : <p className="m-0 text-12 text-ink-3">이 점에서 나가는 선이 없어 방향이 퍼지지 않습니다.</p>}
              </div>
            )}
          </Card>

          {sel && dir && (
            <>
              <Card title="퍼진 경로">
                <p className="m-0 mb-2 text-12 text-ink-2">
                  <b className="text-ink-1">{short(sel)}</b> {dir > 0 ? <span className="text-up">▲ 오르면</span> : <span className="text-down">▼ 내리면</span>} · {depth}단계까지
                </p>
                {!hits.length ? <p className="m-0 text-13 text-ink-3">방향이 정해지는 이웃이 없습니다.</p> : (
                  <ol className="m-0 p-0 list-none flex flex-col gap-2">
                    {vis.map(h => (
                      <li key={h.id} className="flex items-start gap-2">
                        <StepNum n={h.step} kind={h.step === 1 ? 'solid' : 'guess'} />
                        <span className="min-w-0 text-13">
                          <span className="sr-only">{h.step}단계 </span>
                          <span className="inline-flex flex-wrap items-center gap-x-1">
                            <span className="text-ink-2">{short(h.from)}</span>
                            <ChevronRight size={12} aria-hidden className="text-ink-3" />
                            <b className="text-ink-1">{short(h.id)}</b>
                            <span className={h.sign > 0 ? 'text-up' : 'text-down'}>{h.sign > 0 ? '▲ 오름' : '▼ 내림'}</span>
                          </span>
                          <span className="block text-11 text-ink-3">
                            세기 {h.strength} · 글 {h.link.logNos.length}편{h.link.horizon ? ` · ${h.link.horizon}` : ''}{h.step > 1 ? ' · 추정' : ''}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
              </Card>

              <Card title={<>자산 {assets.length} 중 바뀐 것 <span className="num">{changed}</span></>}>
                <p className="m-0 mb-2 text-11 text-ink-3">칸의 숫자 = 세기(1~3). 점선 칸은 2단계부터의 추정입니다.</p>
                <ul aria-label="자산별 퍼진 방향" className="m-0 p-0 list-none grid grid-cols-3 gap-1">
                  {assets.map(n => {
                    const h = hitOf.get(n.id), start = n.id === sel
                    const heat = h ? h.sign * HEAT_AT[h.strength] : start ? dir * HEAT_AT[3] : 0   // 히트맵 채움 규칙에 넣을 값
                    const mark = start ? `${dir > 0 ? '▲' : '▼'} 출발` : h ? `${h.sign > 0 ? '▲' : '▼'} ${h.strength}` : '—'
                    return (
                      <li key={n.id} title={n.label}
                        className={`h-10 rounded-inner flex flex-col items-center justify-center text-center ${heatInk(heat)} ${h && h.step > 1 ? 'border border-dashed border-ink-3' : ''}`}
                        style={{ background: heatBg(heat) }}>
                        <span className="block w-full px-0.5 text-11 leading-tight ellipsis-ok">{shortLabel(n.label)}</span>
                        <span className="block num text-11 font-bold">{mark}</span>
                      </li>
                    )
                  })}
                </ul>
              </Card>

              <div className="flex flex-wrap items-center gap-2">
                <RLink to="/my" className={btn()}>내 보유에는? (비밀번호)</RLink>
                <button type="button" onClick={save} className={btn()}>저장</button>
                <button type="button" onClick={reset} className={btn()}>초기화</button>
              </div>
            </>
          )}
          {note && <p role="status" className="m-0 text-12 text-ink-2">{note}</p>}
          {saved.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 text-12">
              <span className="mr-1 text-ink-3">저장한 시나리오</span>
              {saved.map(x => (
                <button key={x.at + x.name} type="button" onClick={() => restore(x)}
                  className="h-6 px-2 inline-flex items-center rounded-chip border border-line bg-card text-12 text-ink-2 cursor-pointer hover:text-ink-1">
                  {x.name} · {short(x.start)} {x.dir > 0 ? '▲' : '▼'}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <p className="m-0 text-11 text-ink-3">메르 글의 인과 방향만 따른 추정 · 투자 조언 아님</p>
    </div>
  )
}
