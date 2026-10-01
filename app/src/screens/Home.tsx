import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { loadHome, shownUnit, type HomeBundle } from '../lib/bundle'
import { AsOfBadge, Card, NumBlock } from '../components/ui'
import { scaled } from '../lib/format'

// 홈 첫 블록: 오늘 한 줄(평문) + 지표 카드 띠 8. 금액(내 자산)은 여기서 절대 읽지 않는다.
export default function Home() {
  const [home, setHome] = useState<HomeBundle | null>(null)
  const [err, setErr] = useState(false)
  useEffect(() => { loadHome().then(setHome, () => setErr(true)) }, [])

  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 text-14 text-ink-1 max-w-[44em]">
        {err ? '자료를 불러오지 못했습니다.' : !home ? '불러오는 중' : !home.todayLine ? '오늘 한 줄이 아직 없습니다.' : (
          <>
            <span className="hidden pc:inline">{home.todayLine.pc}</span>
            <span className="pc:hidden">{home.todayLine.mobile}</span>
          </>
        )}
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-4 pc:grid-cols-8 gap-2">
        {(home?.strip || []).map(it => (
          <Link key={it.id} to={`/i/${it.id}`} className="no-underline text-ink-1">
            <Card dense className="h-full">
              <div className="flex items-center justify-between gap-1 mb-1">
                <span className="hidden pc:inline text-12 text-ink-2 ellipsis-ok">{it.short || it.label}</span>
                <span className="pc:hidden text-12 text-ink-2 ellipsis-ok">{it.shortM || it.short || it.label}</span>
                <AsOfBadge asOf={it.asOf} state={it.state} liveUntil={it.liveUntil} />
              </div>
              <NumBlock value={scaled(it.value, it.scale)} decimals={it.decimals} chg={scaled(it.change, it.scale)} pct={it.changePct}
                unit={shownUnit(it)} size="M" />
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
