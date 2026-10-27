// 설정 「내 계정」 — 이름 · 앱키 바꾸기 · 이 기기 폰 알림 · 이 기기에서 나가기.
// 앱키 입력은 입장 화면(Welcome)뿐이고, 여기는 이미 들어온 사람의 계정이다. 관심 · 알림 조건 · 설정 · 보유는 같은 앱키로 들어온 기기끼리
// 저절로 맞춘다(lib/personal/sync.ts) — 고를 범위도 맞추는 단추도 없다. 부품(KeyChange · PushScope)은 DeviceLink.tsx.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Pill } from '../ui'
import { BTN, BTN2 } from './bits'
import { KeyChange, PushScope } from './DeviceLink'
import { hhmm } from '../../lib/alerts/v2'
import { signOut, useMe } from '../../lib/personal/account'
import { useSyncStatus } from '../../lib/personal/sync'

export function MyAccount() {
  const me = useMe()
  const s = useSyncStatus()
  const nav = useNavigate()
  const [changing, setChanging] = useState(false)
  const [done, setDone] = useState('')
  const [sure, setSure] = useState(false)
  const [busy, setBusy] = useState(false)
  if (!me) return null
  const leave = async () => {
    setBusy(true)
    try { await signOut() } finally { setBusy(false) }
    nav('/welcome', { replace: true })
  }
  return (
    <Card title="내 계정">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-14 font-bold text-ink-1 [overflow-wrap:anywhere]">{me.name}</span>
          <Pill tone="o">{me.role === 'owner' ? '마스터' : '멤버'}</Pill>
          {s.linked && s.at && <Pill tone="g">{`자동 저장됨 · ${hhmm(s.at)}`}</Pill>}
          <button type="button" aria-expanded={changing} className={`${BTN2} ml-auto`} onClick={() => { setChanging(!changing); setDone('') }}>앱키 바꾸기</button>
        </div>
        {me.viaBackup && <p role="status" className="m-0 text-12 text-warn">예비 앱키로 들어왔습니다. 보유는 마스터 앱키로만 열립니다. 「앱키 바꾸기」로 새 마스터 앱키를 만들어 주세요.</p>}
        {me.status === 'paused' && <p role="status" className="m-0 text-12 text-warn">이 앱키는 멈춘 상태입니다. 모임 운영자에게 문의해 주세요.</p>}
        {changing && <KeyChange onDone={msg => { setChanging(false); setDone(msg) }} />}
        {done && <p role="status" className="m-0 text-12 text-ink-2">{done}</p>}
        <ul className="m-0 p-0 list-none" aria-label="이 기기 폰 알림">
          <PushScope />
        </ul>
        <p className="m-0 text-12 text-ink-3">같은 앱키로 들어온 기기끼리 관심 · 알림 조건 · 설정 · 보유가 저절로 같아집니다. 화면 모드 · 금액 단위는 기기마다 따로입니다. 앱키는 기기에 저장하지 않고, 보유는 앱키로 잠가 두어 운영자도 열 수 없습니다.</p>
        <div className="pt-3 border-t border-line">
          {!sure ? <button type="button" className={BTN2} onClick={() => setSure(true)}>이 기기에서 나가기</button> : (
            <div className="flex flex-col gap-2">
              <p role="alert" className="m-0 text-13 text-ink-1">이 기기에서 나가면 앱키를 다시 넣어야 합니다. 기기 안 기록은 남습니다.</p>
              <div className="flex flex-wrap gap-2">
                <button type="button" disabled={busy} className={BTN} onClick={() => void leave()}>{busy ? '나가는 중' : '나가기'}</button>
                <button type="button" disabled={busy} className={BTN2} onClick={() => setSure(false)}>그만두기</button>
              </div>
            </div>
          )}
        </div>
      </div>
      {s.msg && <p role="alert" className="mt-2 mb-0 text-12 text-warn">{s.msg}</p>}
    </Card>
  )
}
