// 화면 골격: PC(≥980px) 상단 네비 5 + 검색·종·톱니 / 모바일 하단 탭 5.
// 주소는 해시 방식(#/market?a=kr) — GitHub Pages 는 없는 경로를 index.html 로 돌려주지 않아서,
// 경로 방식이면 /next/market 을 새로 고칠 때 404 가 난다.
import { useState, type FormEvent } from 'react'
import { HashRouter, Link, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { Bell, ChartCandlestick, House, Search, Settings as Gear, Telescope, Wallet, type LucideIcon } from 'lucide-react'
import Home from './screens/Home'
import Market from './screens/Market'
import Lens from './screens/Lens'
import My from './screens/My'
import Alerts from './screens/Alerts'
import Detail from './screens/Detail'
import Settings from './screens/Settings'

const TABS: { to: string; label: string; icon: LucideIcon }[] = [
  { to: '/', label: '홈', icon: House },
  { to: '/market', label: '시장', icon: ChartCandlestick },
  { to: '/lens', label: '렌즈', icon: Telescope },
  { to: '/my', label: '내 자산', icon: Wallet },
  { to: '/alerts', label: '알림', icon: Bell },
]

/** 검색창 자리. 지금은 넣은 낱말을 상세 화면 id 로 넘기기만 한다(검색 결과에도 금액은 싣지 않는다). */
function SearchBox({ className = '' }: { className?: string }) {
  const [q, setQ] = useState('')
  const nav = useNavigate()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    const v = q.trim()
    if (v) nav(`/i/${encodeURIComponent(v)}`)
  }
  return (
    <form role="search" onSubmit={submit} className={`relative min-w-0 ${className}`}>
      <Search size={16} aria-hidden className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" />
      <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="종목·지표 검색" aria-label="검색"
        className="w-full h-9 pl-8 pr-3 rounded-btn border border-line bg-bg text-14 text-ink-1 placeholder:text-ink-3" />
    </form>
  )
}

function IconLink({ to, label, icon: Icon }: { to: string; label: string; icon: LucideIcon }) {
  return (
    <Link to={to} aria-label={label} title={label} className="size-9 inline-flex items-center justify-center rounded-btn text-ink-2 hover:text-ink-1">
      <Icon size={20} aria-hidden />
    </Link>
  )
}

function Shell() {
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
            <SearchBox className="w-60 mr-1" />
            <IconLink to="/alerts" label="알림" icon={Bell} />
            <IconLink to="/settings" label="설정" icon={Gear} />
          </div>
        </div>
      </header>

      {/* 모바일 상단: 이름 + 검색 + 톱니 */}
      <header className="pc:hidden bg-card border-b border-line px-4 h-12 flex items-center gap-2">
        <Link to="/" className="text-18 font-bold text-ink-1 no-underline">ecom</Link>
        <SearchBox className="flex-1" />
        <IconLink to="/settings" label="설정" icon={Gear} />
      </header>

      <main className="mx-auto max-w-[1200px] px-4 py-4 pb-24 pc:pb-8">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/market" element={<Market />} />
          <Route path="/lens" element={<Lens />} />
          <Route path="/my" element={<My />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/i/:id" element={<Detail />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<p className="text-14 text-ink-2">없는 화면입니다. <Link to="/">홈으로</Link></p>} />
        </Routes>
      </main>

      {/* 모바일 하단 탭 */}
      <nav aria-label="주 메뉴" className="pc:hidden fixed bottom-0 inset-x-0 bg-card border-t border-line grid grid-cols-5 pb-[env(safe-area-inset-bottom)]">
        {TABS.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === '/'}
            className={({ isActive }) => `h-14 flex flex-col items-center justify-center gap-1 no-underline ${isActive ? 'text-accent font-bold' : 'text-ink-3'}`}>
            <Icon size={20} aria-hidden />
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
