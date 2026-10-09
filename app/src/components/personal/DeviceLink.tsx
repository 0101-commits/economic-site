// 설정 「기기 연결」 — 동기화 키 하나로 ① 관심 · 알림 조건 · 표시 · 렌즈 시나리오 ② 보유 ③ 이 기기 폰 알림을 한 칸에서(명세 S2 · S3 · S5).
// 흐름은 lib/personal/sync.ts(연결 · 범위 · 잊기 · 키 바꾸기 · 보유 자동 맞춤), 폰 알림은 lib/push.ts. 설정(PinGate 안)에서만 연다.
// 키 원문은 입력 칸 상태에만 있다가 보내는 순간 비운다. 키 칸은 autocomplete="new-password"(B13 — 브라우저가 저장한 값을 채우지 않게).
import { useEffect, useState, type FormEvent } from 'react'
import { Card, Pill } from '../ui'
import { BTN, BTN2, Field, INPUT, Switch } from './bits'
import { HoldSyncSheet } from './HoldSyncSheet'
import { hhmm } from '../../lib/alerts/v2'
import { mdHm } from '../../lib/format'
import { pushCount, pushSubscribed, pushSupported, subscribePush, unsubscribePush } from '../../lib/push'
import {
  answerAsk, changeKey, connectSync, forgetDevice, getKeyHash, hasHoldKey, readHoldRec, readScope, restoreHoldKey, setScope, useSyncStatus,
  type Ask, type Count,
} from '../../lib/personal/sync'

const PUSH_MAX = 5   // Worker PUSH_MAX 와 같은 값 — 넘으면 가장 먼저 켠 기기가 빠진다
const NOTE = 'mt-1 mb-0 text-12 text-ink-3'

export function DeviceLink() {
  const s = useSyncStatus()
  const [key, setKey] = useState('')
  const connect = (e: FormEvent) => {
    e.preventDefault()
    const k = key
    setKey('')
    // 폰 알림(범위 ③)은 기본 켬 — 허락은 누른 이 순간에만 물을 수 있어 연결을 기다리지 않고 먼저 묻는다
    const perm = pushSupported() && Notification.permission === 'default' ? Notification.requestPermission().catch(() => 'default') : undefined
    void connectSync(k, perm)
  }
  return (
    <Card title="기기 연결">
      {s.ask ? <AskBox ask={s.ask} busy={s.busy} /> : s.linked ? <Linked /> : (
        <>
          <p className="m-0 text-13 text-ink-2">동기화 키 하나로 관심 · 알림 조건 · 보유를 다른 기기와 맞추고, 이 기기로 폰 알림을 받습니다.</p>
          <form onSubmit={connect} className="mt-3 flex flex-wrap items-end gap-2" aria-label="동기화 키로 연결">
            <Field label="동기화 키" className="flex-1 min-w-48">
              <input type="password" autoComplete="new-password" className={INPUT} value={key} onChange={e => setKey(e.target.value)} />
            </Field>
            <button type="submit" disabled={s.busy || !key.trim()} className={BTN}>{s.busy ? '연결 중' : '연결'}</button>
          </form>
          <p className={NOTE}>키는 저장하지 않습니다. 이 기기에는 키에서 만든 해시와 보유 열쇠만 남고, 「이 기기 잊기」로 지웁니다.</p>
        </>
      )}
      {s.msg && <p role="alert" className="mt-2 mb-0 text-12 text-warn">{s.msg}</p>}
    </Card>
  )
}

const countText = (c: Count) => `관심 ${c.watch} · 조건 ${c.alerts} · 시나리오 ${c.scenarios}${c.settings ? ' · 설정 바꿈' : ''}`

/** 연결할 때 서버 저장본과 이 기기가 다르면 한 번 묻는다(그 전엔 아무것도 저장하지 않았다). */
function AskBox({ ask, busy }: { ask: Ask; busy: boolean }) {
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
        <button type="button" disabled={busy} className={BTN} onClick={() => void answerAsk('server')}>서버 것으로 맞추기</button>
        <button type="button" disabled={busy} className={BTN2} onClick={() => void answerAsk('local')}>이 기기 것을 올리기</button>
        <button type="button" disabled={busy} className={BTN2} onClick={() => void answerAsk(null)}>그만두기</button>
      </div>
      <p className="m-0 text-12 text-ink-3">고르지 않은 쪽의 관심 · 조건 · 시나리오는 사라집니다. 보유는 따로 맞춥니다.</p>
    </div>
  )
}

/** 연결 후: 상태 알약 · 가린 키 · 키 바꾸기 · 이 기기 잊기 · 범위 셋. */
function Linked() {
  const s = useSyncStatus()
  const [changing, setChanging] = useState(false)
  const [done, setDone] = useState('')
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone="g">{s.busy ? '맞추는 중' : s.on && s.at ? `연결됨 · ${hhmm(s.at)} 맞춤` : '연결됨'}</Pill>
        <span className="text-13 text-ink-2">키 <span aria-label="가림">●●●●</span></span>
        <span className="ml-auto flex flex-wrap gap-2">
          <button type="button" aria-expanded={changing} className={BTN2} onClick={() => { setChanging(!changing); setDone('') }}>키 바꾸기</button>
          <button type="button" disabled={s.busy} className={BTN2} onClick={() => void forgetDevice()}>이 기기 잊기</button>
        </span>
      </div>
      {changing && <KeyChange onDone={msg => { setChanging(false); setDone(msg) }} />}
      {done && <p role="status" className="m-0 text-12 text-ink-2">{done}</p>}
      <ul className="m-0 p-0 list-none" aria-label="맞추는 범위">
        <li className="py-2 border-t border-line">
          <Switch on={s.on} disabled={s.busy} onChange={v => void setScope({ prefs: v })} label="관심 · 알림 조건 · 표시 · 렌즈 시나리오" />
          <p className={NOTE}>알림이 울리려면 켜져 있어야 합니다. 화면 모드 · 금액 단위는 기기마다 따로입니다.</p>
        </li>
        <HoldScope />
        <PushScope />
      </ul>
    </div>
  )
}

/** 키 바꾸기: 지금 키 · 새 키 두 번. 검사(12자 · 다름 · PIN 과 다름)와 요청은 sync.ts changeKey. */
function KeyChange({ onDone }: { onDone: (msg: string) => void }) {
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
function HoldScope() {
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
function PushScope() {
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
