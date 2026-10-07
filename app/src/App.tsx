// 화면 골격: PC(≥980px) 상단 네비 5 + 검색·종·톱니 / 모바일 하단 탭 5.
// 주소는 해시 방식(#/market?a=kr) — GitHub Pages 는 없는 경로를 index.html 로 돌려주지 않아서,
// 경로 방식이면 /next/market 을 새로 고칠 때 404 가 난다.
import { useEffect, useState } from 'react'
import { HashRouter, Link, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { Bell, ChartCandlestick, House, Moon, Search, Settings as Gear, Sun, SunMoon, Telescope, Wallet, type LucideIcon } from 'lucide-react'
import Home from './screens/Home'
import Market from './screens/Market'
import Lens from './screens/Lens'
import My from './screens/My'
import Alerts from './screens/Alerts'
import Detail from './screens/Detail'
import Settings from './screens/Settings'
import { PinGate } from './components/PinGate'
import { SearchOverlay } from './components/personal/SearchOverlay'
import { applyUpdown, readPrefs, tidyAlerts } from './lib/personal/store'
import { loadRootJson } from './lib/personal/data'
import { hasUnseen, markSeen, readSeen } from './lib/alertsSeen'
import { legacyToHash } from './lib/legacyUrl'
import { applyTheme, useTheme, type Theme } from './lib/theme'
import { countUse, screenKey } from './lib/usage'

// 등락 색(한국식·서양식)은 테마처럼 첫 그림 전에 정한다
applyUpdown(readPrefs().settings.updown)
// 현행 화면 주소(/next/?p=market&t=commodity)로 들어오면 첫 그림 전에 해시 주소로 바꾼다 — 북마크·알림 버튼 호환
{
  const to = legacyToHash(location.search)
  if (to) history.replaceState(null, '', location.pathname + '#' + to)
}

const TABS: { to: string; label: string; icon: LucideIcon }[] = [
  { to: '/', label: '홈', icon: House },
  { to: '/market', label: '시장', icon: ChartCandlestick },
  { to: '/lens', label: '렌즈', icon: Telescope },
  { to: '/my', label: '내 자산', icon: Wallet },
  { to: '/alerts', label: '알림', icon: Bell },
]

/** 검색 여는 단추. PC = 검색창 모양(`/` 단축키 안내), 모바일 = 돋보기 아이콘. 결과는 오버레이(components/personal/SearchOverlay). */
function SearchButton({ onOpen, compact }: { onOpen: () => void; compact?: boolean }) {
  if (compact) {
    return (
      <button type="button" onClick={onOpen} aria-label="검색" title="검색"
        className="size-9 inline-flex items-center justify-center rounded-btn border-0 bg-transparent text-ink-2 hover:text-ink-1 cursor-pointer">
        <Search size={20} aria-hidden />
      </button>
    )
  }
  return (
    <button type="button" onClick={onOpen} aria-label="검색 (단축키 /)"
      className="relative w-60 mr-1 h-9 pl-8 pr-3 rounded-btn border border-line bg-bg text-14 text-ink-3 text-left cursor-pointer inline-flex items-center justify-between">
      <Search size={16} aria-hidden className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" />
      종목·지표 검색<kbd className="num text-11 text-ink-3 border border-line rounded-inner px-1.5">/</kbd>
    </button>
  )
}

/** 안 읽은 알림이 있다는 작은 점(아이콘 오른쪽 위). 뜻은 링크의 aria-label 이 말한다. */
function Dot({ at }: { at: string }) {
  return <span aria-hidden className={`absolute ${at} size-2 rounded-chip bg-warn`} />
}

function IconLink({ to, label, icon: Icon, dot }: { to: string; label: string; icon: LucideIcon; dot?: boolean }) {
  const name = dot ? `${label} · 안 읽은 알림 있음` : label
  return (
    <Link to={to} aria-label={name} title={name} className="relative size-9 inline-flex items-center justify-center rounded-btn text-ink-2 hover:text-ink-1">
      <Icon size={20} aria-hidden />{dot && <Dot at="top-1.5 right-1.5" />}
    </Link>
  )
}

// 화면 모드는 PIN 없이 바꾼다(설정은 PIN 뒤라서) — 누를 때마다 기기 설정 → 밝게 → 어둡게.
const THEME_STEP: Record<Theme, { next: Theme; name: string; icon: LucideIcon }> = {
  system: { next: 'light', name: '기기 설정', icon: SunMoon },
  light: { next: 'dark', name: '밝게', icon: Sun },
  dark: { next: 'system', name: '어둡게', icon: Moon },
}
function ThemeButton() {
  const t = useTheme()
  const { next, name, icon: Icon } = THEME_STEP[t]
  const label = `화면 모드 ${name} · 누르면 ${THEME_STEP[next].name}`
  return (
    <button type="button" onClick={() => applyTheme(next)} aria-label={label} title={label}
      className="size-9 inline-flex items-center justify-center rounded-btn border-0 bg-transparent text-ink-2 hover:text-ink-1 cursor-pointer">
      <Icon size={20} aria-hidden />
    </button>
  )
}

function Shell() {
  const [search, setSearch] = useState(false)
  // 안 읽음 점: 원장 최신판(events/latest.json)을 열 때 한 번 받아 마지막으로 알림 화면을 연 때와 견준다.
  // 아직 배포 전이거나 못 받으면 점 없이 조용히 넘어간다. 알림 화면에 들어가면 그때를 「본 때」로 적는다.
  const { pathname, search: query } = useLocation()
  // 사용 기록(이 기기 · 횟수만): 화면을 열 때마다 한 번 — 시장은 자산군을 바꿀 때도(lib/usage.ts screenKey)
  const screen = screenKey(pathname, query)
  useEffect(() => { countUse('screens', screen) }, [screen])
  const [rows, setRows] = useState<unknown>(null)
  const [seen, setSeen] = useState(readSeen)
  // 알림 자동 정리(housekeeping.ts)도 여기서 한 번 — prior = 아래 markSeen 이 「본 때」를 적기 전 값(90일 미열람 판정용)
  useEffect(() => {
    const prior = readSeen()
    loadRootJson<unknown>('events/latest.json').then(r => { setRows(r); tidyAlerts(r, prior) }, () => tidyAlerts([], prior))
  }, [])
  useEffect(() => { if (pathname === '/alerts') setSeen(markSeen()) }, [pathname])
  const unseen = hasUnseen(rows, seen)
  // `/` = 검색 열기(입력 칸에서 치는 / 는 그대로 둔다)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey || t?.closest('input, textarea, select, [contenteditable="true"]')) return
      e.preventDefault()
      setSearch(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  return (
    <div className="min-h-dvh">
      {/* PC 상단 */}
      <header className="hidden pc:block bg-card border-b border-line">
        <div className="mx-auto max-w-[1200px] px-4 h-14 flex items-stretch gap-6">
          <Link to="/" className="self-center text-18 font-bold text-ink-1 no-underline">ecom</Link>
          <nav aria-label="주 메뉴" className="flex gap-5">
            {TABS.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} end={to === '/'}
                className={({ isActive }) => `inline-flex items-center gap-1.5 text-14 no-underline border-b-2 ${isActive ? 'border-accent text-ink-1 font-bold' : 'border-transparent text-ink-2 hover:text-ink-1'}`}>
                <Icon size={18} aria-hidden /> {label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto self-center flex items-center gap-1">
            <SearchButton onOpen={() => setSearch(true)} />
            <IconLink to="/alerts" label="알림" icon={Bell} dot={unseen} />
            <IconLink to="/settings" label="설정" icon={Gear} />
            <ThemeButton />
          </div>
        </div>
      </header>

      {/* 모바일 상단: 이름 + 검색 + 톱니 */}
      <header className="pc:hidden bg-card border-b border-line px-4 h-12 flex items-center gap-2">
        <Link to="/" className="mr-auto text-18 font-bold text-ink-1 no-underline">ecom</Link>
        <SearchButton compact onOpen={() => setSearch(true)} />
        <IconLink to="/settings" label="설정" icon={Gear} />
        <ThemeButton />
      </header>

      <main className="mx-auto max-w-[1200px] px-4 py-4 pb-24 pc:pb-8">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/market" element={<Market />} />
          <Route path="/lens" element={<Lens />} />
          <Route path="/my" element={<My />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/i/:id" element={<Detail />} />
          <Route path="/settings" element={<PinGate><Settings /></PinGate>} />
          <Route path="*" element={<p className="text-14 text-ink-2">없는 화면입니다. <Link to="/">홈으로</Link></p>} />
        </Routes>
      </main>

      <SearchOverlay open={search} onClose={() => setSearch(false)} />

      {/* 모바일 하단 탭 */}
      <nav aria-label="주 메뉴" className="pc:hidden fixed bottom-0 inset-x-0 bg-card border-t border-line grid grid-cols-5 pb-[env(safe-area-inset-bottom)]">
        {TABS.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === '/'}
            aria-label={to === '/alerts' && unseen ? `${label} · 안 읽은 알림 있음` : undefined}
            className={({ isActive }) => `h-14 flex flex-col items-center justify-center gap-1 no-underline ${isActive ? 'text-accent font-bold' : 'text-ink-3'}`}>
            <span className="relative inline-flex"><Icon size={20} aria-hidden />{to === '/alerts' && unseen && <Dot at="-top-0.5 right-0" />}</span>
            <span className="text-10 leading-none">{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

export default function App() {
  return <HashRouter><Shell /></HashRouter>
}
