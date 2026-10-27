// 입장 화면 — 키 없는 기기는 여기서 시작한다(App.tsx Shell 이 /welcome?next=… 로 보낸다).
// 흐름은 lib/personal/account.ts signIn → ok(환영 줄 0.8초 뒤 next) · ask(서버 설정과 다름: 기기 연결과 같은 물음) · 오류 넷.
// 키 원문은 입력 칸 상태에만 있다가 보내는 순간 비운다(저장하지 않는다).
// why=paused(멈춘 키) · why=lost(401 로 끊김)이면 첫 줄로 알린다(lib/welcome.ts whyText). 이미 들어와 있는 기기는 홈으로 보낸다(welcomeAway).
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { BrandLogo } from '../components/Brand'
import { Card } from '../components/ui'
import { AskBox } from '../components/personal/DeviceLink'
import { BTN } from '../components/personal/bits'
import { cancelSignIn, finishSignIn, readMe, signIn } from '../lib/personal/account'
import { getKeyHash, useSyncStatus } from '../lib/personal/sync'
import { pushSupported } from '../lib/push'
import { STORAGE_NOTE } from '../lib/personal/members'
import { safeNext, welcomeAway, whyText } from '../lib/welcome'

const ERRORS = {
  bad: '키가 맞지 않습니다. 하이픈과 대소문자는 신경 쓰지 않아도 됩니다.',
  paused: '멈춘 키입니다. 모임 운영자에게 문의해 주세요.',
  rate: '시도가 많아 1분 뒤에 다시 넣을 수 있습니다.',
  offline: '연결되지 않았습니다. 잠시 뒤 다시 눌러 주세요.',
} as const

export default function Welcome() {
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const navigate = useNavigate()
  const s = useSyncStatus()
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [asking, setAsking] = useState(false)
  const [hello, setHello] = useState('')
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])
  // 열 때 한 번만 본다 — 여기서 들어오는 중(해시가 막 생김)에는 보내지 않는다
  const [away] = useState(() => welcomeAway({ hash: !!getKeyHash(), paused: readMe()?.status === 'paused' }))
  const why = whyText(params.get('why'))
  if (away) return <Navigate to="/" replace />

  const enter = () => {
    setHello(`${readMe()?.name ?? ''}님, 어서 오세요`)
    timer.current = setTimeout(() => navigate(safeNext(next), { replace: true }), 800)
  }
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const raw = key
    if (busy || !raw.trim()) return
    // 폰 알림 허락은 누른 그 순간에 묻는다(아이폰 · 사파리는 사용자 동작 안에서만 묻는다 — 기기 연결과 같은 방식). 들어가면 이 기기를 구독한다.
    const perm = pushSupported() && Notification.permission === 'default' ? Notification.requestPermission().catch(() => 'default') : undefined
    setKey('')
    setErr('')
    setBusy(true)
    try {
      const r = await signIn(raw, perm)
      if (r === 'ok') enter()
      else if (r === 'ask') setAsking(true)
      else setErr(ERRORS[r])
    } catch { setErr(ERRORS.offline) } finally { setBusy(false) }
  }
  const answered = (side: 'server' | 'local' | null) => {
    setAsking(false)
    if (!side) { cancelSignIn(); return }
    if (finishSignIn()) enter(); else { cancelSignIn(); setErr(ERRORS.offline) }
  }

  return (
    <div className="min-h-dvh grid grid-cols-1 md:grid-cols-2">
      <section className="bg-brand text-on-brand flex flex-col justify-center gap-4 px-6 py-8 md:px-12 md:py-16">
        <BrandLogo tagline className="h-20 md:h-28 w-auto self-start" />
        <p className="m-0 max-w-[28rem] text-14 md:text-16 leading-relaxed">ECOM 모임 멤버를 위한 시장 화면입니다. 자산과 관심 종목은 사람마다 따로 저장됩니다.</p>
      </section>
      <section className="flex items-center justify-center px-4 py-8">
        <Card className="w-full max-w-sm">
          <h1 className="m-0 mb-3 text-18 font-bold text-ink-1">들어가기</h1>
          {hello ? <p role="status" className="m-0 text-14 text-ink-1">{hello}</p>
            : s.ask && asking ? <AskBox ask={s.ask} busy={s.busy} onAnswered={answered} /> : (
              <form onSubmit={submit} className="flex flex-col gap-3" aria-label="입장 키로 들어가기">
                {why && !err && <p role="status" className="m-0 text-13 text-warn">{why}</p>}
                <label className="flex flex-col gap-1 min-w-0">
                  <span className="text-12 text-ink-2">입장 키</span>
                  <input type="text" autoComplete="off" autoCapitalize="characters" spellCheck={false} autoFocus
                    aria-invalid={!!err} aria-describedby={err ? 'welcome-err' : undefined}
                    className="h-11 w-full min-w-0 px-3 rounded-btn border border-line bg-bg text-[16px] text-ink-1 disabled:opacity-60"
                    value={key} disabled={busy} onChange={e => setKey(e.target.value)} />
                </label>
                {err && <p id="welcome-err" role="alert" className="m-0 text-12 text-warn">{err}</p>}
                <button type="submit" disabled={busy || !key.trim()} className={`${BTN} h-11 text-14 font-bold`}>{busy ? '확인 중' : '들어가기'}</button>
                <p className="m-0 text-12 text-ink-3">키는 모임 운영자에게 받습니다. 한 번 들어가면 이 기기는 다음부터 바로 열립니다. 키는 기기에 저장하지 않습니다.</p>
                <p className="m-0 text-12 text-ink-3">{STORAGE_NOTE}</p>
              </form>
            )}
        </Card>
      </section>
    </div>
  )
}
