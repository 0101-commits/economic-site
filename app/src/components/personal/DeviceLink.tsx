// 내 계정 부품 — 설정 「내 계정」(MyAccount)이 쓴다: 앱키 바꾸기 · 이 기기 폰 알림. 앱키를 넣어 들어오는 곳은 입장 화면(Welcome) 한 곳뿐이다.
// 설정 · 보유는 앱키로 들어온 기기끼리 저절로 맞춘다(lib/personal/sync.ts — 고를 범위도 맞추는 단추도 없다). 폰 알림은 lib/push.ts. 앱키 칸은 autocomplete="new-password"(B13).
import { useEffect, useState, type FormEvent } from 'react'
import { BTN, BTN2, Field, INPUT, Switch } from './bits'
import { pushCount, pushSubscribed, pushSupported, subscribePush, unsubscribePush } from '../../lib/push'
import { changeKey, getKeyHash, useSyncStatus } from '../../lib/personal/sync'

const PUSH_MAX = 5   // Worker PUSH_MAX 와 같은 값 — 넘으면 가장 먼저 켠 기기가 빠진다
export const NOTE = 'mt-1 mb-0 text-12 text-ink-3'

/** 앱키 바꾸기: 지금 앱키 · 새 앱키 두 번. 검사(12자 · 다름 · PIN 과 다름)와 요청은 sync.ts changeKey. */
export function KeyChange({ onDone }: { onDone: (msg: string) => void }) {
  const s = useSyncStatus()
  const [cur, setCur] = useState('')
  const [n1, setN1] = useState('')
  const [n2, setN2] = useState('')
  const [err, setErr] = useState('')
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (n1 !== n2) { setErr('새 앱키 두 번 입력이 서로 다릅니다.'); return }
    const r = await changeKey(cur, n1)
    if (r) { setErr(r); return }
    setCur(''); setN1(''); setN2('')
    onDone('앱키를 바꿨습니다. 다른 기기는 새 앱키로 다시 들어오면 폰 알림도 다시 켜집니다.')
  }
  const box = (label: string, v: string, set: (v: string) => void) => (
    <Field label={label}><input type="password" autoComplete="new-password" className={INPUT} value={v} onChange={e => set(e.target.value)} /></Field>
  )
  return (
    <form onSubmit={submit} className="flex flex-col gap-2 pt-3 border-t border-line" aria-label="앱키 바꾸기">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {box('지금 앱키', cur, setCur)}
        {box('새 앱키 · 12자 이상', n1, setN1)}
        {box('한 번 더', n2, setN2)}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="submit" disabled={s.busy || !cur || !n1} className={BTN}>{s.busy ? '바꾸는 중' : '바꾸기'}</button>
        <button type="button" className={BTN2} onClick={() => onDone('')}>그만두기</button>
        <span role="alert" className="text-12 text-warn">{err}</span>
      </div>
      <p className="m-0 text-12 text-ink-3">잠금 PIN 과 다른 앱키를 쓰세요. 바꾸면 보유를 새 앱키로 다시 잠그고 이 기기 폰 알림도 옮깁니다. 다른 기기는 새 앱키로 다시 들어와야 합니다.</p>
    </form>
  )
}

/** 이 기기 폰 알림(웹 푸시 구독) · 받는 기기 N/5(GET /push/subscribe 의 count). */
export function PushScope() {
  const supported = pushSupported()
  const { pushAt } = useSyncStatus()
  const [on, setOn] = useState(false)
  const [n, setN] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  useEffect(() => {
    if (supported && Notification.permission === 'denied') setMsg('알림이 막혀 있습니다. 브라우저 사이트 설정에서 풀어야 합니다.')
    pushSubscribed().then(setOn, () => {})
    pushCount(getKeyHash).then(setN, () => {})
  }, [pushAt, supported])
  const toggle = async (want: boolean) => {
    setBusy(true); setMsg('')
    try {
      await (want ? subscribePush(getKeyHash) : unsubscribePush(getKeyHash))
      setOn(want)
      setMsg(want ? '이 기기로 알림을 받습니다.' : '이 기기 알림을 껐습니다.')
      setN(await pushCount(getKeyHash))
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  return (
    <li className="py-2 border-t border-line">
      {supported
        ? <Switch on={on} onChange={v => void toggle(v)} disabled={busy} label="이 기기로 폰 알림 받기" />
        : <p className="m-0 text-13 text-ink-2">이 브라우저는 폰 알림을 지원하지 않습니다. 아이폰은 Safari 공유 메뉴의 「홈 화면에 추가」로 연 앱에서만 켤 수 있습니다.</p>}
      <p className={NOTE}>받는 기기 <span className="num">{n ?? '—'}/{PUSH_MAX}</span> · {PUSH_MAX}대를 넘으면 가장 먼저 켠 기기가 빠집니다.</p>
      {msg && <p role="status" className="mt-1 mb-0 text-12 text-ink-2">{msg}</p>}
    </li>
  )
}
