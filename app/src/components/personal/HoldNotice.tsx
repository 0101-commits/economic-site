// 내 자산 보유 한 줄 — 저절로 맞추다 생긴 일 가운데 사람이 알아야 할 것만(lib/personal/sync.ts st.hold · holdSync.HoldState).
//   old     옛 형식 판(예전 평단가 암호나 바꾸기 전 앱키로 잠금)이 있을 때만: 그 자리에서 예전 암호를 한 번 넣는다(남은 유일한 수동 단계).
//           예전 암호를 모르면 「이 기기 보유로 새로 잠그기」(확인 한 번) — 앱키를 다시 받은 멤버가 막히지 않게. 있던 판은 이 기기에 잠긴 채 한 벌.
//   broken  읽지 못하는 판 — 새로 잠그기만.
//   backup · nokey · error · info  한 줄.
// 예전 암호는 이 칸의 상태에만 있다가 보내는 순간 비운다(저장하지 않는다). PinGate 안(내 자산)에서만 쓴다.
import { useState, type FormEvent } from 'react'
import { BTN, BTN2, Field, INPUT } from './bits'
import { replaceHoldings, unlockHoldings, useSyncStatus } from '../../lib/personal/sync'

export function HoldNotice({ onPulled }: { onPulled: () => void }) {
  const { hold } = useSyncStatus()
  const [old, setOld] = useState('')
  const [busy, setBusy] = useState(false)
  const [sure, setSure] = useState(false)
  if (!hold.text) return null
  const run = async (f: () => Promise<{ pulled: boolean }>) => {
    setBusy(true)
    try { if ((await f()).pulled) onPulled() } finally { setBusy(false); setSure(false) }
  }
  const unlock = (e: FormEvent) => { e.preventDefault(); const o = old; setOld(''); void run(() => unlockHoldings(o)) }
  const warn = hold.kind !== 'info'
  const fixable = hold.kind === 'old' || hold.kind === 'broken'
  return (
    <div className="flex flex-col gap-2">
      <p role={warn ? 'alert' : 'status'} className={`m-0 text-12 ${warn ? 'text-warn' : 'text-ink-3'}`}>{hold.text}</p>
      {hold.kind === 'old' && (
        <form onSubmit={unlock} className="flex flex-wrap items-end gap-2" aria-label="예전 암호로 보유 열기">
          <Field label="예전 평단가 암호 또는 바꾸기 전 앱키" className="flex-1 min-w-48">
            <input type="password" autoComplete="off" className={INPUT} value={old} onChange={e => setOld(e.target.value)} />
          </Field>
          <button type="submit" disabled={busy || !old.trim()} className={BTN}>{busy ? '여는 중' : '열기'}</button>
        </form>
      )}
      {fixable && !sure && (
        <button type="button" disabled={busy} onClick={() => setSure(true)}
          className="self-start p-0 border-0 bg-transparent text-12 text-ink-2 underline underline-offset-2 cursor-pointer disabled:opacity-60">
          {hold.kind === 'old' ? '예전 암호를 모르면: 이 기기 보유로 새로 잠그기' : '이 기기 보유로 새로 잠그기'}
        </button>
      )}
      {fixable && sure && (
        <div className="flex flex-col gap-2">
          <p role="alert" className="m-0 text-12 text-ink-1">저장돼 있던 보유 대신 이 기기 보유를 지금 앱키로 잠가 둡니다. 저장돼 있던 것은 이 기기에 잠긴 채 한 벌 남습니다.</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy} className={BTN} onClick={() => void run(replaceHoldings)}>{busy ? '잠그는 중' : '새로 잠그기'}</button>
            <button type="button" disabled={busy} className={BTN2} onClick={() => setSure(false)}>그만두기</button>
          </div>
        </div>
      )}
    </div>
  )
}
