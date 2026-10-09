// 보유 「동기화」 시트 — 이 기기와 서버의 보유(평단가·수량·매입 환율)를 비교해 서버 것을 받거나 이 기기 것을 올린다.
// 평소엔 sync.ts syncHoldings 가 묻지 않고 맞춘다. 이 시트는 둘 다 바뀌었을 때(또는 직접 확인할 때) 비교 결과와 단추만 보인다.
// 열쇠는 동기화 키에서 만든 재료(결정 D9 a)라 암호 칸이 없다 — 예전 보유 암호(이전 전)나 바꾸기 전 동기화 키로 잠긴 서버 사본일 때만 그 글자를 한 번 묻는다.
// 내 자산(My.tsx)과 설정 「기기 연결」(DeviceLink.tsx)이 연다 — 둘 다 PinGate 안이다. 예전 암호는 이 시트의 상태에만 있다가 닫으면 비운다.
import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { BottomSheet } from '../ui'
import { BTN, BTN2, Field, INPUT } from './bits'
import { mdHm } from '../../lib/format'
import { checkHoldings, pullHoldings, pushHoldings, useSyncStatus, type HoldCheck, type HoldDone } from '../../lib/personal/sync'
import type { EncBlob } from '../../lib/personal/e2e'

type Checked = Extract<HoldCheck, { ok: true }>

/** 이 기기가 비었는데 올리라는 판정 — 저장소가 깨졌을 수 있다. 서버 사본이 지워지므로 따로 경고하고 받기를 먼저 둔다. */
const wipes = (c: Checked) => c.plan === 'push' && c.localN === 0 && c.server.length > 0

function askText(c: Checked): string {
  if (wipes(c)) return `이 기기에 보유가 없습니다. 올리면 서버 사본 ${c.server.length}종목이 지워집니다.`
  if (c.plan === 'push') return c.enc ? '이 기기가 더 새롭습니다. 올릴까요?' : `서버에 보유 자료 없음. 이 기기 보유 ${c.localN}종목을 올릴까요?`
  if (c.plan === 'pull') return '서버 보유가 더 새롭습니다. 받을까요?'
  if (c.plan === 'conflict') return '이 기기와 서버가 둘 다 바뀌었습니다. 남길 쪽을 고르세요.'
  if (c.plan === 'same') return c.stale ? '서버와 같습니다. 예전 암호로 잠긴 사본이라 새 열쇠로 다시 잠가 올려야 합니다.' : '서버와 같습니다.'
  return '서버에 보유 자료 없음. 이 기기에도 올릴 보유가 없습니다.'
}

export function HoldSyncSheet({ open, onClose, onPulled }: { open: boolean; onClose: () => void; onPulled: () => void }) {
  const { linked } = useSyncStatus()
  const [old, setOld] = useState('')
  const [busy, setBusy] = useState(false)
  const [chk, setChk] = useState<HoldCheck | null>(null)
  const [note, setNote] = useState<HoldDone | null>(null)
  const run = async (f: () => Promise<void>) => { setBusy(true); try { await f() } finally { setBusy(false) } }
  const check = (pass?: string) => run(async () => { setNote(null); setChk(await checkHoldings(pass)) })
  useEffect(() => { if (open && linked) void check() }, [open, linked])
  const close = () => { setOld(''); setChk(null); setNote(null); onClose() }
  const finish = (r: HoldDone) => { setNote(r); if (r.ok) { setChk(null); setOld('') } }
  const push = (seen: EncBlob | null) => run(async () => finish(await pushHoldings(seen)))
  const pull = (c: Checked) => run(async () => { const r = await pullHoldings(c); if (r.ok) onPulled(); finish(r) })
  const unlockOld = (e: FormEvent) => { e.preventDefault(); void check(old) }

  const c = chk?.ok ? chk : null
  const acts = !!c && (c.plan === 'push' || c.plan === 'pull' || c.plan === 'conflict' || (c.plan === 'same' && c.stale))
  const both = c?.plan === 'conflict'
  const wipe = !!c && wipes(c)
  return (
    <BottomSheet open={open} onClose={close} title="보유 동기화">
      {!linked ? (
        <p className="m-0 text-13 text-ink-2">연결돼 있지 않습니다. <Link to="/settings">설정 › 기기 연결</Link>에서 동기화 키를 넣은 뒤 다시 여세요.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {busy && !chk && <p role="status" className="m-0 text-13 text-ink-3">확인 중</p>}

          {chk && !chk.ok && (
            <div className="flex flex-col gap-2">
              <p role="alert" className="m-0 text-13 text-warn">{chk.msg}</p>
              {chk.migrate && (
                <>
                  <form onSubmit={unlockOld} className="flex flex-wrap items-end gap-2" aria-label="예전 보유 암호 또는 바꾸기 전 동기화 키 넣기">
                    <Field label="예전 보유 암호 또는 바꾸기 전 동기화 키" className="flex-1 min-w-48">
                      <input type="password" autoComplete="off" className={INPUT} value={old} onChange={e => setOld(e.target.value)} />
                    </Field>
                    <button type="submit" disabled={busy || !old.trim()} className={BTN}>{busy ? '푸는 중' : '풀기'}</button>
                  </form>
                  <p className="m-0 text-12 text-ink-3">이전 화면의 「평단가 동기화 암호」, 또는 키를 바꿨는데 사본이 옛 키로 남았다면 바꾸기 전 동기화 키입니다. 한 번 풀면 지금 동기화 키로 잠가 다시 올리므로 더 묻지 않습니다.</p>
                  <button type="button" disabled={busy} className={`${BTN2} self-start`} onClick={() => push(chk.migrate!)}>서버 사본 버리고 이 기기 것 올리기</button>
                </>
              )}
              {chk.needKey && <Link to="/settings" className="text-12 text-ink-2">설정 › 기기 연결로</Link>}
              {!chk.migrate && !chk.needKey && (
                <div className="flex flex-wrap gap-2">
                  <button type="button" disabled={busy} className={BTN2} onClick={() => void check()}>다시 확인</button>
                  {chk.broken && <button type="button" disabled={busy} className={BTN2} onClick={() => push(chk.broken!)}>서버 사본 버리고 이 기기 것 올리기</button>}
                </div>
              )}
            </div>
          )}

          {c && (
            <div className="flex flex-col gap-2">
              <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-13">
                <dt className="text-ink-3">이 기기</dt>
                <dd className="m-0 text-ink-1"><span className="num">{c.localN}</span>종목</dd>
                <dt className="text-ink-3">서버</dt>
                <dd className="m-0 text-ink-1">
                  {c.enc ? <><span className="num">{c.server.length}</span>종목 · {c.serverAt ? `${mdHm(c.serverAt)} 올림` : '올린 때 모름(이전 화면이 올림)'}</> : '없음'}
                </dd>
              </dl>
              <p role={wipe ? 'alert' : undefined} className={`m-0 text-13 ${wipe ? 'text-warn' : 'text-ink-1'}`}>{askText(c)}</p>
              {acts && (
                <div className="flex flex-wrap gap-2">
                  {(c.plan === 'pull' || both || wipe) && <button type="button" disabled={busy} className={both ? BTN2 : BTN} onClick={() => pull(c)}>{both ? '서버 것 받기' : '받기'}</button>}
                  {c.plan !== 'pull' && <button type="button" disabled={busy} className={both || wipe ? BTN2 : BTN} onClick={() => push(c.enc)}>{both ? '이 기기 것 올리기' : wipe ? '그래도 올리기' : busy ? '올리는 중' : c.plan === 'same' ? '새 열쇠로 다시 올리기' : '올리기'}</button>}
                  <button type="button" disabled={busy} className={BTN2} onClick={() => setChk(null)}>그만두기</button>
                </div>
              )}
              {acts && (c.plan === 'pull' || both || wipe) && <p className="m-0 text-12 text-ink-3">받으면 이 기기의 평단가·수량·매입 환율이 서버 값으로 바뀝니다. 서버에 없는 종목은 값만 비우고 줄은 남깁니다.</p>}
            </div>
          )}
          {note && <p role={note.ok ? 'status' : 'alert'} className={`m-0 text-12 ${note.ok ? 'text-ink-2' : 'text-warn'}`}>{note.msg}</p>}
          <p className="m-0 text-12 text-ink-3">동기화 키에서 만든 열쇠로 잠근 덩어리만 서버에 둡니다. 서버는 내용을 읽지 못합니다.</p>
        </div>
      )}
    </BottomSheet>
  )
}
