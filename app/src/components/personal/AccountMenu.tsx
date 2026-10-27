// 머리줄 오른쪽 끝 이름 단추 — 이름 첫 글자 동그라미를 누르면 작은 메뉴: 이름 · 역할 / 내 계정 / 멤버 관리(마스터만) / 이 기기에서 나가기(확인 한 단계).
// 바깥을 누르거나 Esc 로 닫는다. 나가기는 signOut(기기 연결 잊기 · me 지움) 뒤 입장 화면으로.
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { signOut, useMe } from '../../lib/personal/account'
import { BTN, BTN2 } from './bits'

const ITEM = 'block w-full px-3 py-2 text-left text-13 text-ink-1 no-underline bg-transparent border-0 hover:bg-bg cursor-pointer'

export function AccountMenu() {
  const me = useMe()
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [sure, setSure] = useState(false)
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const close = () => { setOpen(false); setSure(false) }
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent | TouchEvent) => { if (box.current && !box.current.contains(e.target as Node)) close() }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('touchstart', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('touchstart', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])
  if (!me) return null
  const leave = async () => {
    setBusy(true)
    try { await signOut() } finally { setBusy(false); close() }
    nav('/welcome', { replace: true })
  }
  return (
    <div ref={box} className="relative">
      <button type="button" onClick={() => (open ? close() : setOpen(true))} aria-haspopup="menu" aria-expanded={open} aria-label={`${me.name} 메뉴`} title={me.name}
        className="size-8 ml-1 inline-flex items-center justify-center rounded-chip border border-line bg-bg text-13 font-bold text-ink-1 cursor-pointer">
        {[...me.name][0] ?? '?'}
      </button>
      {open && (
        <div role="menu" aria-label="내 메뉴" className="absolute right-0 top-full mt-2 z-50 w-64 max-w-[calc(100vw-2rem)] py-1 rounded-card border border-line bg-card shadow-lg">
          <p className="m-0 px-3 py-2 text-13 text-ink-1 border-b border-line [overflow-wrap:anywhere]">
            <b>{me.name}</b> <span className="text-12 text-ink-3">{me.role === 'owner' ? '마스터' : '멤버'}</span>
          </p>
          <Link to="/settings" role="menuitem" onClick={close} className={ITEM}>내 계정</Link>
          {me.role === 'owner' && <Link to="/members" role="menuitem" onClick={close} className={ITEM}>멤버 관리</Link>}
          {!sure ? (
            <button type="button" role="menuitem" onClick={() => setSure(true)} className={`${ITEM} border-t border-line`}>이 기기에서 나가기</button>
          ) : (
            <div className="px-3 py-2 border-t border-line flex flex-col gap-2">
              <p role="alert" className="m-0 text-12 text-ink-2">이 기기에서 나가면 앱키를 다시 넣어야 합니다. 기기 안 기록은 남습니다.</p>
              <div className="flex gap-2">
                <button type="button" disabled={busy} onClick={() => void leave()} className={BTN}>{busy ? '나가는 중' : '나가기'}</button>
                <button type="button" disabled={busy} onClick={() => setSure(false)} className={BTN2}>그만두기</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
