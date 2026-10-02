// 시장 — 기획안 v4 4장. 머리 → 자산군 버튼 7(a=) → 지표 띠(s=) → 자산군별 보기 바(v=, 범위·나라 m=) → 격자(PC 12열 / 모바일 1열).
// 자산군마다 묶음 하나(bundles/market-<이름>.json)만 받는다. 한 번 받은 묶음은 bundle.ts 가 기억해 다시 고르면 그 자리에서 바뀐다.
import { useEffect, useState, type ComponentType } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ChartCandlestick } from 'lucide-react'
import { loadBundle } from '../lib/bundle'
import { mdHm } from '../lib/format'
import { useViewParam } from '../lib/useViewParam'
import { useWatch } from '../lib/watch'
import { Pill, SegBar } from '../components/ui'
import { StripCard } from '../components/panels'
import type { BodyProps, MarketBundle } from '../components/market/parts'
import Domestic from '../components/market/Domestic'
import Global from '../components/market/Global'
import FxRates from '../components/market/FxRates'
import Commodities from '../components/market/Commodities'
import Macro from '../components/market/Macro'
import Flows from '../components/market/Flows'
import RealEstate from '../components/market/RealEstate'

const ASSETS = [
  { key: 'kr', label: '국내', bundle: 'market-domestic', Body: Domestic },
  { key: 'global', label: '해외', bundle: 'market-global', Body: Global },
  { key: 'fxrate', label: '환율금리', bundle: 'market-fxrates', Body: FxRates },
  { key: 'commod', label: '원자재', bundle: 'market-commodities', Body: Commodities },
  { key: 'macro', label: '거시', bundle: 'market-macro', Body: Macro },
  { key: 'flow', label: '수급', bundle: 'market-flows', Body: Flows },
  { key: 'realestate', label: '부동산', bundle: 'market-realestate', Body: RealEstate },
] as const
type Asset = typeof ASSETS[number]['key']
// 띠 칸 수(묶음이 정한다: 대부분 6, 원자재 7) → PC 한 줄 열 수
const STRIP_COLS: Record<number, string> = { 6: 'pc:grid-cols-6', 7: 'pc:grid-cols-7' }

export default function Market() {
  const [, setParams] = useSearchParams()
  const [a] = useViewParam<Asset>('a', 'kr', ASSETS.map(o => o.key))
  const [s, setS] = useViewParam<string>('s', '')
  const watch = useWatch()
  const def = ASSETS.find(o => o.key === a)!
  const [got, setGot] = useState<Partial<Record<Asset, MarketBundle | 'err'>>>({})
  useEffect(() => {
    loadBundle<MarketBundle>(def.bundle).then(b => setGot(m => ({ ...m, [a]: b })), () => setGot(m => ({ ...m, [a]: 'err' })))
  }, [a])

  // 자산군을 바꾸면 그 자산군의 보기·범위·고른 지표는 처음으로(앞 자산군 값이 뒤 자산군에서 엉뚱한 칸을 고르지 않게). 기간 p 는 둔다.
  const pickAsset = (k: Asset) => setParams(prev => {
    const p = new URLSearchParams(prev)
    if (k === 'kr') p.delete('a'); else p.set('a', k)
    for (const x of ['v', 's', 'm']) p.delete(x)
    return p
  }, { replace: true })

  const b = got[a]
  const ok = b && b !== 'err' && Array.isArray(b.strip) ? b : null
  const mk = ok?.market
  const selId = s || ok?.strip[0]?.id || ''
  const Body = def.Body as ComponentType<BodyProps<never>>

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h1 className="m-0 inline-flex items-center gap-1.5 text-18 font-bold text-ink-1"><ChartCandlestick size={18} aria-hidden />시장</h1>
        <span className="text-14 font-bold text-ink-2">{def.label}</span>
        {mk && <Pill tone={mk.state === 'open' ? 'g' : 'o'}>{mk.label}</Pill>}
        {mk && mk.state !== 'open' && mk.nextOpen && <span className="text-12 text-ink-3">다음 개장 <span className="num">{mdHm(mk.nextOpen)}</span></span>}
      </header>

      {/* 자산군 7 — 좁은 화면은 한 줄 가로 스크롤 */}
      <SegBar scroll label="자산군" options={ASSETS} value={a} onChange={pickAsset} />

      {b === 'err' ? <p className="m-0 text-14 text-ink-2">자료를 불러오지 못했습니다.</p>
        : !ok ? <p className="m-0 text-14 text-ink-3">불러오는 중</p> : (
          <>
            <div className={`grid grid-cols-2 sm:grid-cols-3 ${STRIP_COLS[ok.strip.length] ?? 'pc:grid-cols-6'} gap-2`}>
              {ok.strip.map(it => (
                <StripCard key={it.id} item={it} selected={it.id === selId} onSelect={() => setS(it.id)}
                  watched={watch.has(it.id)} onWatch={() => watch.toggle(it.id)} />
              ))}
            </div>
            <Body key={a} b={ok as never} selId={selId} setS={setS} />
          </>
        )}
    </div>
  )
}
