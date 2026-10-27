// 연결 · 범위 부품 — 설정 「내 계정」(MyAccount)과 입장 화면(Welcome)이 쓴다. 키 입력은 입장 화면(Welcome) 한 곳뿐이다.
// 흐름은 lib/personal/sync.ts(범위 · 키 바꾸기 · 보유 자동 맞춤), 폰 알림은 lib/push.ts. 키 칸은 autocomplete="new-password"(B13).
import { useEffect, useState, type FormEvent } from 'react'
import { BTN, BTN2, Field, INPUT, Switch } from './bits'
import { HoldSyncSheet } from './HoldSyncSheet'
import { mdHm } from '../../lib/format'
import { pushCount, pushSubscribed, pushSupported, subscribePush, unsubscribePush } from '../../lib/push'
import {
  answerAsk, changeKey, getKeyHash, hasHoldKey, readHoldRec, readScope, restoreHoldKey, setScope, useSyncStatus,
  type Ask, type Count,
} from '../../lib/personal/sync'

const PUSH_MAX = 5   // Worker PUSH_MAX 와 같은 값 — 넘으면 가장 먼저 켠 기기가 빠진다
export const NOTE = 'mt-1 mb-0 text-12 text-ink-3'

const countText = (c: Count) => `관심 ${c.watch} · 조건 ${c.alerts} · 시나리오 ${c.scenarios}${c.settings ? ' · 설정 바꿈' : ''}`

/** 연결할 때 서버 저장본과 이 기기가 다르면 한 번 묻는다(그 전엔 아무것도 저장하지 않았다). */
export function AskBox({ ask, busy, onAnswered }: { ask: Ask; busy: boolean; onAnswered?: (side: 'server' | 'local' | null, ok: boolean) => void }) {
  const answer = async (side: 'server' | 'local' | null) => { const ok = await answerAsk(side); onAnswered?.(side, ok) }
  return (
    <div role="group" aria-label="어느 쪽으로 맞출지" className="flex flex-col gap-2">
      <p className="m-0 text-13 text-ink-1">서버에 맡겨 둔 설정이 있습니다. 어느 쪽으로 맞출까요?</p>
      <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-13">
        <dt className="text-ink-3">서버</dt>
        <dd className="m-0 num text-ink-1">{countText(ask.server)}{ask.at ? ` · ${mdHm(ask.at)} 맡김` : ''}</dd>
        <dt className="text-ink-3">이 기기</dt>
        <dd className="m-0 num text-ink-1">{countText(ask.local)}</dd>
      </dl>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={busy} className={BTN} onClick={() => void answer('server')}>서버 것으로 맞추기</button>
        <button type="button" disabled={busy} className={BTN2} onClick={() => void answer('local')}>이 기기 것을 올리기</button>
        <button type="button" disabled={busy} className={BTN2} onClick={() => void answer(null)}>그만두기</button>
      </div>
      <p className="m-0 text-12 text-ink-3">고르지 않은 쪽의 관심 · 조건 · 시나리오는 사라집니다. 보유는 따로 맞춥니다.</p>
    </div>
  )
}

/** 키 바꾸기: 지금 키 · 새 키 두 번. 검사(12자 · 다름 · PIN 과 다름)와 요청은 sync.ts changeKey. */
export function KeyChange({ onDone }: { onDone: (msg: string) => void }) {
  const s = useSyncStatus()
  const [cur, setCur] = useState('')
  const [n1, setN1] = useState('')
  const [n2, setN2] = useState('')
  const [err, setErr] = useState('')
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (n1 !== n2) { setErr('새 키 두 칸이 다릅니다.'); return }
    const r = await changeKey(cur, n1)
    if (r) { setErr(r); return }
    setCur(''); setN1(''); setN2('')
    onDone('키를 바꿨습니다. 다른 기기는 새 키로 다시 연결하면 폰 알림도 다시 켜집니다.')
  }
  const box = (label: string, v: string, set: (v: string) => void) => (
    <Field label={label}><input type="password" autoComplete="new-password" className={INPUT} value={v} onChange={e => set(e.target.value)} /></Field>
  )
  return (
    <form onSubmit={submit} className="flex flex-col gap-2 pt-3 border-t border-line" aria-label="동기화 키 바꾸기">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {box('지금 키', cur, setCur)}
        {box('새 키 · 12자 이상', n1, setN1)}
        {box('한 번 더', n2, setN2)}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="submit" disabled={s.busy || !cur || !n1} className={BTN}>{s.busy ? '바꾸는 중' : '바꾸기'}</button>
        <button type="button" className={BTN2} onClick={() => onDone('')}>그만두기</button>
        <span role="alert" className="text-12 text-warn">{err}</span>
      </div>
      <p className="m-0 text-12 text-ink-3">잠금 PIN 과 다른 키를 쓰세요. 바꾸면 보유를 새 키로 다시 잠가 올리고 이 기기 폰 알림도 옮깁니다. 다른 기기는 새 키로 다시 연결해야 합니다.</p>
    </form>
  )
}

/** ② 보유: 같은 키로 잠가 올림. 열쇠 재료가 없으면(이 판 전에 연결) 키를 한 번 더 받는다. 「맞추기」 = 내 자산과 같은 동기화 시트. */
export function HoldScope() {
  const s = useSyncStatus()
  const [on, setOn] = useState(() => readScope().hold)
  const [open, setOpen] = useState(false)
  const [rec, setRec] = useState(readHoldRec)
  useEffect(() => setRec(readHoldRec()), [s.hold])
  const keyed = hasHoldKey()
  return (
    <li className="py-2 border-t border-line">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Switch on={on} onChange={v => { setOn(v); void setScope({ hold: v }) }} label="보유(평단가 · 수량 · 매입 환율)" />
        {on && keyed && <button type="button" className={`${BTN2} ml-auto`} onClick={() => setOpen(true)}>맞추기</button>}
      </div>
      <p className={NOTE}>같은 키로 잠가 올립니다 · 서버는 못 읽습니다 · 마지막 올림 <span className="num">{rec.upAt ? mdHm(rec.upAt) : '없음'}</span></p>
      {on && !keyed && <RestoreKey />}
      {on && keyed && s.hold.text && <p role={s.hold.ask ? 'alert' : 'status'} className={`mt-1 mb-0 text-12 ${s.hold.ask ? 'text-warn' : 'text-ink-2'}`}>{s.hold.text}</p>}
      <HoldSyncSheet open={open} onClose={() => setOpen(false)} onPulled={() => setRec(readHoldRec())} />
    </li>
  )
}

function RestoreKey() {
  const s = useSyncStatus()
  const [key, setKey] = useState('')
  const [err, setErr] = useState('')
  const submit = async (e: FormEvent) => { e.preventDefault(); const k = key; setKey(''); setErr(await restoreHoldKey(k)) }
  return (
    <form onSubmit={submit} className="mt-2 flex flex-wrap items-end gap-2" aria-label="보유 열쇠 만들기">
      <Field label="동기화 키 한 번 더(보유 열쇠를 만듭니다)" className="flex-1 min-w-48">
        <input type="password" autoComplete="new-password" className={INPUT} value={key} onChange={e => setKey(e.target.value)} />
      </Field>
      <button type="submit" disabled={s.busy || !key.trim()} className={BTN}>확인</button>
      {err && <p role="alert" className="basis-full m-0 text-12 text-warn">{err}</p>}
    </form>
  )
}

/** ③ 이 기기 폰 알림(웹 푸시 구독) · 받는 기기 N/5(GET /push/subscribe 의 count). */
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
        : <p className="m-0 text-13 text-ink-2">이 브라우저는 웹 푸시를 지원하지 않습니다. 아이폰은 Safari 공유 메뉴의 「홈 화면에 추가」로 연 앱에서만 켤 수 있습니다.</p>}
      <p className={NOTE}>받는 기기 <span className="num">{n ?? '—'}/{PUSH_MAX}</span> · {PUSH_MAX}대를 넘으면 가장 먼저 켠 기기가 빠집니다.</p>
      {msg && <p role="status" className="mt-1 mb-0 text-12 text-ink-2">{msg}</p>}
    </li>
  )
}
