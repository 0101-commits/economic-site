// 내 자산 「동기화」 시트 — 보유(평단가·수량·매입 환율)를 내 암호로 잠가 올리거나, 서버 것을 받는다.
// PinGate 안(My.tsx)에서만 연다. 덮기 전에 한 번 묻고, 자동 병합은 하지 않는다(lib/personal/sync.ts 「보유」).
// 보유 암호는 이 시트의 상태에만 있다. 시트를 닫거나 일을 마치면 비운다.
// 「확인」 뒤에는 칸을 잠그고, 확인 때 서버 것을 푼 바로 그 문자열(chk.pass)로 올린다.
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { BottomSheet } from '../ui'
import { BTN, BTN2, Field, INPUT } from './bits'
import { mdHm } from '../../lib/format'
import { checkHoldings, pullHoldings, pushHoldings, useSyncStatus, type HoldCheck, type HoldDone } from '../../lib/personal/sync'

type Checked = Extract<HoldCheck, { ok: true }>

/** 이 기기가 비었는데 올리라는 판정 — 저장소가 깨졌을 수 있다. 서버 사본이 지워지므로 따로 경고하고 받기를 먼저 둔다. */
const wipes = (c: Checked) => c.plan === 'push' && c.localN === 0 && c.server.length > 0

function askText(c: Checked): string {
  if (wipes(c)) return `이 기기에 보유가 없습니다. 올리면 서버 사본 ${c.server.length}종목이 지워집니다.`
  if (c.plan === 'push') return c.enc ? '이 기기가 더 새롭습니다. 올릴까요?' : `서버에 보유 자료 없음. 이 기기 보유 ${c.localN}종목을 올릴까요?`
  if (c.plan === 'pull') return '서버 보유가 더 새롭습니다. 받을까요?'
  if (c.plan === 'conflict') return '이 기기와 서버가 둘 다 바뀌었습니다. 남길 쪽을 고르세요.'
  if (c.plan === 'same') return '서버와 같습니다.'
  return '서버에 보유 자료 없음. 이 기기에도 올릴 보유가 없습니다.'
}

export function HoldSyncSheet({ open, onClose, onPulled }: { open: boolean; onClose: () => void; onPulled: () => void }) {
  const { on } = useSyncStatus()
  const [pass, setPass] = useState('')
  const [busy, setBusy] = useState(false)
  const [chk, setChk] = useState<Checked | null>(null)
  const [note, setNote] = useState<HoldDone | null>(null)
  const close = () => { setPass(''); setChk(null); setNote(null); onClose() }
  const run = async (f: () => Promise<void>) => { setBusy(true); try { await f() } finally { setBusy(false) } }
  const finish = (r: HoldDone) => { setNote(r); if (r.ok) { setChk(null); setPass('') } }

  const check = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      setChk(null); setNote(null)
      const r = await checkHoldings(pass)
      if (r.ok) setChk(r)
      else setNote(r)
    })
  }
  const push = (c: Checked) => run(async () => finish(await pushHoldings(c.pass, c.enc)))
  const pull = (c: Checked) => run(async () => { const r = await pullHoldings(c.server); if (r.ok) onPulled(); finish(r) })

  const acts = chk && (chk.plan === 'push' || chk.plan === 'pull' || chk.plan === 'conflict')
  const both = chk?.plan === 'conflict'
  const wipe = !!chk && wipes(chk)
  return (
    <BottomSheet open={open} onClose={close} title="보유 동기화">
      {!on ? (
        <p className="m-0 text-13 text-ink-2">기기 간 동기화가 꺼져 있습니다. <Link to="/settings">설정</Link>에서 동기화 키를 넣은 뒤 다시 여세요.</p>
      ) : (
        <div className="flex flex-col gap-3">
          <form onSubmit={check} className="flex flex-wrap items-end gap-2" aria-label="보유 암호 넣기">
            <Field label="보유 암호" className="flex-1 min-w-48">
              <input type="password" autoComplete="off" className={INPUT} value={pass} readOnly={!!chk} onChange={e => setPass(e.target.value)} />
            </Field>
            <button type="submit" disabled={busy || !pass.trim()} className={BTN}>{busy && !chk ? '확인 중' : '확인'}</button>
          </form>
          <p className="m-0 text-12 text-ink-3">이전 화면의 「평단가 동기화 암호」와 같은 암호입니다. 잠금 PIN·동기화 키와 다르게 정하세요. 이 화면은 암호를 저장하지 않고, 서버는 잠긴 덩어리만 받습니다.</p>

          {chk && (
            <div className="flex flex-col gap-2 pt-3 border-t border-line">
              <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-13">
                <dt className="text-ink-3">이 기기</dt>
                <dd className="m-0 text-ink-1"><span className="num">{chk.localN}</span>종목</dd>
                <dt className="text-ink-3">서버</dt>
                <dd className="m-0 text-ink-1">
                  {chk.enc ? <><span className="num">{chk.server.length}</span>종목 · {chk.serverAt ? `${mdHm(chk.serverAt)} 올림` : '올린 때 모름(이전 화면이 올림)'}</> : '없음'}
                </dd>
              </dl>
              <p role={wipe ? 'alert' : undefined} className={`m-0 text-13 ${wipe ? 'text-warn' : 'text-ink-1'}`}>{askText(chk)}</p>
              {acts && (
                <div className="flex flex-wrap gap-2">
                  {(chk.plan !== 'push' || wipe) && <button type="button" disabled={busy} className={both ? BTN2 : BTN} onClick={() => pull(chk)}>{both ? '서버 것 받기' : '받기'}</button>}
                  {chk.plan !== 'pull' && <button type="button" disabled={busy} className={both || wipe ? BTN2 : BTN} onClick={() => push(chk)}>{both ? '이 기기 것 올리기' : wipe ? '그래도 올리기' : busy ? '올리는 중' : '올리기'}</button>}
                  <button type="button" disabled={busy} className={BTN2} onClick={() => setChk(null)}>그만두기</button>
                </div>
              )}
              {acts && (chk.plan !== 'push' || wipe) && <p className="m-0 text-12 text-ink-3">받으면 이 기기의 평단가·수량·매입 환율이 서버 값으로 바뀝니다. 서버에 없는 종목은 값만 비우고 줄은 남깁니다.</p>}
            </div>
          )}
          {note && <p role={note.ok ? 'status' : 'alert'} className={`m-0 text-12 ${note.ok ? 'text-ink-2' : 'text-warn'}`}>{note.msg}</p>}
        </div>
      )}
    </BottomSheet>
  )
}
