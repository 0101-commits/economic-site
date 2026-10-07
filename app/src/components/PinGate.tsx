// 설정 · 내 자산 관문. 열리기 전에는 children 을 아예 만들지 않는다 — 그래서 자산 자료를 읽는 코드는
// children 안에만 두면 PIN 없이는 한 번도 돌지 않는다(홈·검색·알림에 금액이 새지 않는 이유).
// 틀리면 기다리게 한다(lib/pin.ts 실패 대기). PIN 을 잊으면 이 안에서: 동기화 키 확인 → PIN 만 지우기,
// 키가 없으면 이 기기 데이터를 지운 뒤 새로 정하기.
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { canHash, checkPin, clearPin, hasPin, isUnlocked, lock, readFail, setPin, touch, waitMs } from '../lib/pin'
import { keyHash, syncKeyCheck } from '../lib/personal/remote'
import { wipeDevice } from '../lib/personal/store'
import { disableSync, getKeyHash } from '../lib/personal/sync'
import { BTN, BTN2, Field, INPUT } from './personal/bits'
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

type Mode = 'unlock' | 'setup' | 'confirm' | 'open' | 'forgot'

export function PinGate({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>(() => (isUnlocked() ? 'open' : hasPin() ? 'unlock' : 'setup'))
  const [pin, setPinText] = useState('')
  const [first, setFirst] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [left, setLeft] = useState(() => waitMs())   // 실패 대기 남은 ms
  const waiting = mode === 'unlock' && left > 0

  // 기다리는 동안 1초마다 남은 시간을 다시 읽는다(다른 탭에서 틀려도 같은 기록을 본다).
  useEffect(() => {
    if (!waiting) return
    const id = window.setInterval(() => setLeft(waitMs()), 1000)
    return () => window.clearInterval(id)
  }, [waiting])

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
        else { setPinText(''); setLeft(waitMs()); setMsg('PIN 이 맞지 않습니다.') }
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
    unlock: ['잠긴 화면', '설정과 내 자산은 이 기기 PIN 으로 엽니다.'],
    setup: ['이 기기 PIN 정하기', '숫자 6자리. 설정과 내 자산을 이 PIN 으로 엽니다. 기기마다 따로 정하고, 현행 화면의 잠금과 같은 PIN 을 씁니다.'],
    confirm: ['한 번 더', '같은 PIN 을 한 번 더 넣으세요.'],
    forgot: ['PIN 잊음', '동기화 키가 맞는지 서버에 묻고, 맞으면 이 기기 PIN 만 지운 뒤 새로 정합니다. 키는 어디에도 남기지 않습니다.'],
  }[mode]
  const note = busy ? '확인 중' : waiting ? `PIN 을 ${readFail().n}번 틀렸습니다 · ${Math.ceil(left / 1000)}초 뒤 다시` : msg

  return (
    <Card className="max-w-[420px] mx-auto">
      <h2 className="m-0 text-18 font-bold">{head[0]}</h2>
      <p className="mt-1 mb-4 text-13 text-ink-2">{head[1]}</p>
      {!canHash() ? (
        <p role="alert" className="text-13 text-warn m-0">이 환경(https 아님)에서는 잠금을 쓸 수 없습니다. https 주소로 접속하세요.</p>
      ) : mode === 'forgot' ? (
        <Forgot onBack={() => { setMsg(''); setMode('unlock') }}
          onCleared={() => { setPinText(''); setFirst(''); setLeft(0); setMsg('동기화 키가 맞습니다. 새 PIN 을 정하세요.'); setMode('setup') }} />
      ) : (
        <PinInput value={pin} onChange={setPinText} onSubmit={submit} disabled={busy || waiting} label={head[0]} />
      )}
      {mode !== 'forgot' && <p role="alert" className="min-h-5 mt-2 mb-0 text-12 text-warn">{note}</p>}
      {mode === 'unlock' && canHash() && (
        <button type="button" className={`${BTN2} mt-3`} onClick={() => { setMsg(''); setMode('forgot') }}>PIN 잊음</button>
      )}
    </Card>
  )
}

const CHECK_ERR: Record<number, string> = {
  401: '동기화 키가 맞지 않습니다.',
  429: '요청이 많습니다. 1분 뒤 다시 하세요.',
  503: '서버에 동기화 키가 설정되지 않았습니다.',
  403: '이 주소에서 연 화면은 서버가 받지 않습니다.',
  0: '서버에 닿지 못했습니다. 잠시 뒤 다시 하세요.',
}

/** PIN 잊음: 동기화 키가 맞으면 PIN 만 지운다. 키가 없으면 이 기기 데이터를 지우고(확인 2번) PIN 도 지운 뒤 새로 정한다. */
function Forgot({ onCleared, onBack }: { onCleared: () => void; onBack: () => void }) {
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [step, setStep] = useState(0)
  const check = async (e: FormEvent) => {
    e.preventDefault()
    const k = key
    setKey(''); setBusy(true); setMsg('')
    const st = await keyHash(k).then(syncKeyCheck, () => 0)
    setBusy(false)
    if (st === 200) { clearPin(); onCleared() }
    else setMsg(CHECK_ERR[st] ?? `서버가 받지 않았습니다(${st}).`)
  }
  const wipe = async () => {
    setBusy(true)
    // 푸시 구독 해지가 동기화 키 해시를 쓰므로 동기화를 끄기 전에 지운다(wipeDevice 안에서 해지)
    if (!(await wipeDevice(getKeyHash))) { setBusy(false); setStep(0); setMsg('이 기기 데이터를 지우지 못했습니다.'); return }
    disableSync(); clearPin(); location.reload()
  }
  return (
    <div>
      <form onSubmit={check} className="flex flex-wrap items-end gap-2" aria-label="동기화 키로 PIN 지우기">
        <Field label="동기화 키" className="flex-1 min-w-48">
          <input type="password" autoComplete="off" className={INPUT} value={key} onChange={e => setKey(e.target.value)} />
        </Field>
        <button type="submit" disabled={busy || !key.trim()} className={BTN}>{busy && !step ? '확인 중' : '확인'}</button>
      </form>
      <p role="alert" className="min-h-5 mt-2 mb-0 text-12 text-warn">{msg}</p>
      <div className="mt-3 pt-3 border-t border-line flex flex-col items-start gap-2">
        <p className="m-0 text-12 text-ink-2">동기화 키가 없으면 이 기기 데이터를 지운 뒤 새로 정해야 합니다.</p>
        {step === 0 && <button type="button" className={BTN2} onClick={() => setStep(1)}>이 기기 데이터 지우기</button>}
        {step === 1 && <>
          <p className="m-0 text-13 text-ink-1">지울 것: 보유 · 스냅샷 · 원장 · 관심 · 알림 조건 · 설정 · 렌즈 시나리오, 그리고 이 기기 PIN. 동기화를 끄고 이 기기의 폰 알림 구독도 끊습니다. 서버에 맡긴 것은 남습니다.</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={BTN2} onClick={() => setStep(2)}>계속</button>
            <button type="button" className={BTN2} onClick={() => setStep(0)}>그만두기</button>
          </div>
        </>}
        {step === 2 && <>
          <p role="alert" className="m-0 text-13 font-bold text-warn">되돌릴 수 없습니다. 정말 지울까요?</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy} className={BTN} onClick={() => void wipe()}>{busy ? '지우는 중' : '지우기'}</button>
            <button type="button" disabled={busy} className={BTN2} onClick={() => setStep(0)}>그만두기</button>
          </div>
        </>}
      </div>
      <button type="button" className={`${BTN2} mt-3`} onClick={onBack}>PIN 넣기로 돌아가기</button>
    </div>
  )
}
