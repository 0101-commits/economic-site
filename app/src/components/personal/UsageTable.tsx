// 설정 「내 사용」 — 이 기기의 사용 기록(lib/usage.ts)을 표로 보인다. 횟수만이고 서버로 보내지 않는다.
import { useState, type ReactNode } from 'react'
import { SCREENS, clearUsage, readUsage, topCounts } from '../../lib/usage'
import { BTN2 } from './bits'

const SCREEN_NAME: Record<string, string> = Object.fromEntries(SCREENS)
// 패널 열쇠(foldId)의 화면 자리 → 이름: 'market' → 시장, 'home' → 홈 (SCREENS 에서 끌어온다)
const PANEL_SCREEN: Record<string, string> = {}
for (const [k, n] of SCREENS) PANEL_SCREEN[k.split('?')[0].slice(1) || 'home'] ??= n.split(' · ')[0]
const panelName = (key: string) => { const [s, ...t] = key.split(':'); return `${PANEL_SCREEN[s] ?? s} › ${t.join(':')}` }

function Block({ title, children }: { title: string; children: ReactNode }) {
  return <section className="min-w-0"><h3 className="m-0 mb-1 text-13 font-bold text-ink-1">{title}</h3>{children}</section>
}

function Rows({ rows, empty }: { rows: [string, ReactNode][]; empty: string }) {
  if (!rows.length) return <p className="m-0 text-12 text-ink-3">{empty}</p>
  return (
    <ul className="m-0 p-0 list-none">
      {rows.map(([name, n]) => (
        <li key={name} className="flex items-baseline justify-between gap-3 py-1.5 border-b border-line last:border-b-0 text-13">
          <span className="min-w-0 text-ink-1">{name}</span><span className="shrink-0 num text-ink-2">{n}</span>
        </li>
      ))}
    </ul>
  )
}

/** 내 사용: 기록 시작일 · 화면별 연 횟수 · 많이 누른 보기 5 · 접은 패널 · 한 번도 안 연 화면 · 기록 지우기. 설정 「고급」 안에 둔다. */
export function UsageTable() {
  const [u, setU] = useState(readUsage)
  const screens = topCounts(u.screens, SCREENS.length + 1).map(([k, n]): [string, ReactNode] => [SCREEN_NAME[k] ?? k, `${n}회`])
  const views = topCounts(u.views, 5).map(([k, n]): [string, ReactNode] => [k, `${n}회`])
  const folds = Object.entries(u.folds).filter(([, f]) => f.close > 0).sort((a, b) => b[1].close - a[1].close)
    .map(([k, f]): [string, ReactNode] => [panelName(k), `접음 ${f.close} · 펼침 ${f.open}`])
  const never = SCREENS.filter(([k]) => !u.screens[k]).map(([, n]) => n)
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="m-0 text-12 text-ink-2">
          {u.since ? <>기록 시작 <span className="num">{u.since}</span> · </> : '아직 기록이 없습니다 · '}이 기기에만, 횟수만 남깁니다(값 · 종목 · 시각 없음).
        </p>
        <button type="button" className={BTN2} onClick={() => { clearUsage(); setU(readUsage()) }}>기록 지우기</button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Block title="화면별 연 횟수"><Rows rows={screens} empty="연 화면이 아직 없습니다." /></Block>
        <Block title="많이 누른 보기 5"><Rows rows={views} empty="누른 범위 · 보기 · 목차가 아직 없습니다." /></Block>
        <Block title="접은 패널"><Rows rows={folds} empty="접은 패널이 없습니다." /></Block>
        <Block title="한 번도 안 연 화면">
          {never.length ? <p className="m-0 text-13 text-ink-1">{never.join(', ')}</p> : <p className="m-0 text-12 text-ink-3">모든 화면을 한 번 이상 열었습니다.</p>}
        </Block>
      </div>
    </div>
  )
}
