// 내 자산 관문. 열리기 전에는 children 을 아예 만들지 않는다 — 그래서 자산 자료를 읽는 코드는
// children 안에만 두면 PIN 없이는 한 번도 돌지 않는다(홈·검색·알림에 금액이 새지 않는 이유).
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { canHash, checkPin, hasPin, isUnlocked, lock, setPin, touch } from '../lib/pin'
import { ROOT } from '../lib/bundle'
import { Card } from './ui'

const CELLS = 6

/** 6칸 PIN 입력. 실제 입력은 투명한 input 하나가 받고 칸은 그림일 뿐이다(붙여넣기·지우기·모바일 자판이 그대로 된다). */
function PinInput({ value, onChange, onSubmit, disabled, label }: {
  value: string; onChange: (v: string) => void; onSubmit: (v: string) => void; disabled?: boolean; label: string
}) {
  const ref = useRef<HTMLInputElement>(null)
  const [focused, setFocused] = useState(false)
  useEffect(() => { if (!disabled) ref.current?.focus() }, [disabled])
  return (
    <div className="relative inline-flex gap-2">
      {Array.from({ length: CELLS }, (_, i) => (
        <div key={i} aria-hidden
          className={`size-11 rounded-inner border bg-card flex items-center justify-center ${focused && i === Math.min(value.length, CELLS - 1) ? 'border-accent' : 'border-line'}`}>
          {value[i] && <span className="size-2.5 rounded-chip bg-ink-1" />}
        </div>
      ))}
      <input ref={ref} type="password" inputMode="numeric" autoComplete="off" maxLength={CELLS} aria-label={label}
        value={value} disabled={disabled}
        onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
        onChange={e => {
          const v = e.target.value.replace(/\s/g, '').slice(0, CELLS)
          onChange(v)
          if (v.length === CELLS) onSubmit(v)
        }}
        // 현행 사이트에서 4~5자로 정한 PIN 도 Enter 로 넣을 수 있다
        onKeyDown={e => { if (e.key === 'Enter' && value.length >= 4) onSubmit(value) }}
        className="absolute inset-0 size-full opacity-0 cursor-pointer" />
    </div>
  )
}

type Mode = 'unlock' | 'setup' | 'confirm' | 'open'

export function PinGate({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>(() => (isUnlocked() ? 'open' : hasPin() ? 'unlock' : 'setup'))
  const [pin, setPinText] = useState('')
  const [first, setFirst] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  // 열린 동안: 조작하면 시각을 갱신하고, 5분 무조작이면 다시 잠근다.
  useEffect(() => {
    if (mode !== 'open') return
    let last = 0
    const onAct = () => { const t = Date.now(); if (t - last > 5000) { last = t; touch() } }
    const check = () => { if (!isUnlocked()) { lock(); setMode('unlock'); setMsg('5분 동안 조작이 없어 다시 잠갔습니다.') } }
    const evs = ['pointerdown', 'keydown', 'touchstart', 'wheel'] as const
    evs.forEach(e => window.addEventListener(e, onAct, { passive: true }))
    document.addEventListener('visibilitychange', check)
    const id = window.setInterval(check, 10_000)
    return () => {
      evs.forEach(e => window.removeEventListener(e, onAct))
      document.removeEventListener('visibilitychange', check)
      window.clearInterval(id)
    }
  }, [mode])

  if (mode === 'open') {
    return (
      <>
        <div className="flex justify-end mb-2">
          <button type="button" onClick={() => { lock(); setMode('unlock'); setMsg('') }}
            className="h-8 px-3 rounded-btn text-13 border border-line bg-card text-ink-2">잠그기</button>
        </div>
        {children}
      </>
    )
  }

  const run = async (job: () => Promise<void>) => {
    setBusy(true)
    try { await job() } catch { setMsg('이 환경에서는 잠금을 쓸 수 없습니다. https 주소로 접속하세요.') }
    setBusy(false)
  }

  const submit = (v: string) => {
    if (busy) return
    if (mode === 'unlock') {
      run(async () => {
        if (await checkPin(v)) { setPinText(''); setMsg(''); setMode('open') }
        else { setPinText(''); setMsg('PIN 이 맞지 않습니다.') }
      })
    } else if (mode === 'setup') {
      if (!/^\d{6}$/.test(v)) { setPinText(''); setMsg('숫자 6자리로 정하세요.'); return }
      setFirst(v); setPinText(''); setMsg(''); setMode('confirm')
    } else {
      if (v !== first) { setPinText(''); setFirst(''); setMsg('두 번 넣은 PIN 이 다릅니다. 처음부터 다시 정하세요.'); setMode('setup'); return }
      run(async () => { await setPin(v); setPinText(''); setMsg(''); setMode('open') })
    }
  }

  const head = {
    unlock: ['잠긴 화면', '내 자산은 이 기기 PIN 으로 엽니다.'],
    setup: ['이 기기 PIN 정하기', '숫자 6자리. 기기마다 따로 정하고, 현행 화면의 잠금과 같은 PIN 을 씁니다.'],
    confirm: ['한 번 더', '같은 PIN 을 한 번 더 넣으세요.'],
  }[mode]

  return (
    <Card className="max-w-[420px] mx-auto">
      <h2 className="m-0 text-18 font-bold">{head[0]}</h2>
      <p className="mt-1 mb-4 text-13 text-ink-2">{head[1]}</p>
      {!canHash() ? (
        <p role="alert" className="text-13 text-warn m-0">이 환경(https 아님)에서는 잠금을 쓸 수 없습니다. https 주소로 접속하세요.</p>
      ) : (
        <PinInput value={pin} onChange={setPinText} onSubmit={submit} disabled={busy} label={head[0]} />
      )}
      <p role="alert" className="min-h-5 mt-2 mb-0 text-12 text-warn">{busy ? '확인 중' : msg}</p>
      {mode === 'unlock' && (
        <div className="mt-3 flex flex-col items-start gap-2">
          <p className="m-0 text-12 text-ink-3">PIN 을 잊었으면 <a href={new URL('legacy.html?p=portfolio', ROOT).href}>이전 화면 투자 현황</a>의 잠금 창에서 「PIN 잊음」으로 다시 정하세요.</p>
        </div>
      )}
    </Card>
  )
}
