// 멤버 관리 — 마스터(owner)만. 추가(입장 키를 한 번만 보여 줌) · 이름 바꾸기 · 멈추기/다시 열기 · 키 다시 만들기 · 지우기 · 마스터 예비 키.
// 확인 · 이름 입력은 모두 그 자리에서(window.confirm/prompt 는 앱 안 브라우저에서 막힌다). 오류는 하는 일 가까이에 짧은 글로.
// 순수한 부분(오류 글 · 마지막 접속 · 카톡 글)은 lib/personal/members.ts.
import { useCallback, useEffect, useRef, useState } from 'react'
import { Users } from 'lucide-react'
import { Card, Pill } from '../components/ui'
import { BTN, BTN2, INPUT } from '../components/personal/bits'
import { useMe } from '../lib/personal/account'
import { getKeyHash } from '../lib/personal/sync'
import { adminBackupKey, adminCreate, adminDelete, adminList, adminPatch, adminRekey, type MemberReply } from '../lib/personal/remote'
import { adminErrText, cleanName, kakaoText, lastSeenText, parseMembers, type Member } from '../lib/personal/members'
import { kstDay } from '../lib/personal/calc'

type Step = { uid: string; kind: 'menu' | 'rename' | 'rekey' | 'delete' }
type Issued = { title: string; key: string; note: string; kakao: boolean }

const ROW_BTN = 'h-8 px-2.5 rounded-btn text-12 border border-line bg-card text-ink-2 hover:text-ink-1 cursor-pointer disabled:opacity-60 whitespace-nowrap'

export default function Members() {
  const me = useMe()
  const hash = getKeyHash()
  const [list, setList] = useState<Member[] | null>(null)
  const [listErr, setListErr] = useState('')
  const [step, setStep] = useState<Step | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<{ uid: string; text: string } | null>(null)   // uid '' = 목록 위 · 추가 · 예비 키 쪽 오류
  const [issued, setIssued] = useState<Issued | null>(null)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [hasBackup, setHasBackup] = useState(false)

  const owner = me?.role === 'owner'
  const load = useCallback(async () => {
    if (!hash) return
    const r = await adminList(hash)
    if (r.status === 200) { setList(parseMembers(r.doc)); setListErr('') } else { setListErr(adminErrText(r)); setList(l => l ?? []) }
  }, [hash])
  useEffect(() => { if (owner) void load() }, [owner, load])

  if (me && !owner) return <p className="m-0 text-14 text-ink-2">마스터만 쓸 수 있는 화면입니다</p>

  /** 한 가지 일을 하고: 성공이면 then(r), 실패면 그 자리(uid)에 짧은 글. 404 는 목록을 다시 받는다. */
  const run = async (uid: string, job: () => Promise<MemberReply>, then: (r: MemberReply) => void) => {
    if (!hash || busy) return
    setBusy(true); setErr(null)
    try {
      const r = await job()
      if (r.status >= 200 && r.status < 300) { then(r); await load() } else { setErr({ uid, text: adminErrText(r) }); if (r.status === 404) await load() }
    } finally { setBusy(false) }
  }

  const add = () => {
    const n = cleanName(name)
    if (!n) { setErr({ uid: '', text: adminErrText({ status: 400, error: 'bad_name' }) }); return }
    void run('', () => adminCreate(hash!, n), r => {
      const key = r.doc?.key
      if (typeof key !== 'string') { setErr({ uid: '', text: '서버 답에 키가 없습니다. 목록을 확인하세요.' }); return }
      setIssued({ title: `${r.doc?.user?.name ?? n} 님의 입장 키`, key, note: '이 화면을 닫으면 다시 볼 수 없습니다. 잃어버리면 「키 다시 만들기」로 새 키를 줍니다.', kakao: true })
      setAdding(false); setName('')
    })
  }
  const rename = (m: Member) => {
    const n = cleanName(name)
    if (!n) { setErr({ uid: m.uid, text: adminErrText({ status: 400, error: 'bad_name' }) }); return }
    void run(m.uid, () => adminPatch(hash!, m.uid, { name: n }), () => { setStep(null); setName('') })
  }
  const toggle = (m: Member) => void run(m.uid, () => adminPatch(hash!, m.uid, { status: m.status === 'paused' ? 'active' : 'paused' }), () => setStep(null))
  const rekey = (m: Member) => void run(m.uid, () => adminRekey(hash!, m.uid), r => {
    const key = r.doc?.key
    if (typeof key !== 'string') { setErr({ uid: m.uid, text: '서버 답에 키가 없습니다.' }); return }
    setIssued({ title: `${m.name} 님의 새 입장 키`, key, note: '이 화면을 닫으면 다시 볼 수 없습니다. 옛 키는 이미 막혔습니다.', kakao: true }); setStep(null)
  })
  const del = (m: Member) => void run(m.uid, () => adminDelete(hash!, m.uid), () => setStep(null))
  const backup = () => void run('', () => adminBackupKey(hash!), r => {
    const key = r.doc?.key
    if (typeof key !== 'string') { setErr({ uid: '', text: '서버 답에 키가 없습니다.' }); return }
    setIssued({ title: '마스터 예비 키', key, note: '마스터 키를 잃었을 때 이 키로 들어와 새 키를 만듭니다. 따로 적어 두세요.', kakao: false }); setHasBackup(true)
  })

  const today = kstDay()
  return (
    <div className="flex flex-col gap-4">
      <header><h1 className="m-0 inline-flex items-center gap-1.5 text-18 font-bold text-ink-1"><Users size={18} aria-hidden />멤버 관리</h1></header>

      {issued && <KeyCard issued={issued} onClose={() => setIssued(null)} />}

      <Card title="멤버">
        <div className="flex flex-col gap-3">
          {listErr && <p role="alert" className="m-0 text-12 text-warn">{listErr}</p>}
          {list == null && !listErr && <p className="m-0 text-13 text-ink-3">불러오는 중</p>}
          {list && list.length > 0 && (
            <ul className="m-0 p-0 list-none flex flex-col divide-y divide-line">
              {list.map(m => {
                const s = step?.uid === m.uid ? step.kind : null
                return (
                  <li key={m.uid} className="py-2.5 flex flex-col gap-2 min-w-0">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 min-w-0">
                      <b className="text-14 text-ink-1 min-w-0 [overflow-wrap:anywhere]">{m.name}</b>
                      <span className="text-12 text-ink-3">{m.role === 'owner' ? '마스터' : '멤버'}</span>
                      <Pill tone={m.status === 'paused' ? 'n' : 'g'}>{m.status === 'paused' ? '멈춤' : '사용 중'}</Pill>
                      <span className="text-12 text-ink-2 ml-auto whitespace-nowrap">마지막 접속 {lastSeenText(m.lastSeenDay, today)} · 폰 알림 {m.pushCount}대</span>
                    </div>
                    {s === null && (
                      <div>
                        <button type="button" className={ROW_BTN} aria-expanded={false} onClick={() => { setStep({ uid: m.uid, kind: 'menu' }); setErr(null) }}>관리</button>
                      </div>
                    )}
                    {s === 'menu' && (
                      <div className="flex flex-wrap gap-2">
                        <button type="button" className={ROW_BTN} onClick={() => { setName(m.name); setStep({ uid: m.uid, kind: 'rename' }) }}>이름 바꾸기</button>
                        {m.role !== 'owner' && <>
                          <button type="button" disabled={busy} className={ROW_BTN} onClick={() => toggle(m)}>{m.status === 'paused' ? '다시 열기' : '멈추기'}</button>
                          <button type="button" className={ROW_BTN} onClick={() => setStep({ uid: m.uid, kind: 'rekey' })}>키 다시 만들기</button>
                          <button type="button" className={ROW_BTN} onClick={() => setStep({ uid: m.uid, kind: 'delete' })}>지우기</button>
                        </>}
                        <button type="button" className={ROW_BTN} onClick={() => setStep(null)}>닫기</button>
                      </div>
                    )}
                    {s === 'rename' && (
                      <form className="flex flex-wrap gap-2" onSubmit={e => { e.preventDefault(); rename(m) }}>
                        <input value={name} onChange={e => setName(e.target.value)} maxLength={20} aria-label="새 이름" className={`${INPUT} flex-1 basis-40`} />
                        <button type="submit" disabled={busy} className={BTN}>바꾸기</button>
                        <button type="button" disabled={busy} className={BTN2} onClick={() => { setStep(null); setName('') }}>그만두기</button>
                      </form>
                    )}
                    {(s === 'rekey' || s === 'delete') && (
                      <div className="flex flex-col gap-2">
                        <p role="alert" className="m-0 text-12 text-ink-2">
                          {s === 'rekey' ? '옛 키는 바로 막힙니다. 보유는 옛 키로 잠겨 있어 새 키로는 열 수 없습니다 — 옛 키가 남은 기기에서 다시 잠가 올리거나 보유를 다시 입력해야 합니다.' : `${m.name}의 관심 · 알림 조건 · 보유 · 폰 알림이 모두 지워집니다.`}
                        </p>
                        <div className="flex gap-2">
                          <button type="button" disabled={busy} className={BTN} onClick={() => (s === 'rekey' ? rekey(m) : del(m))}>{busy ? '처리 중' : s === 'rekey' ? '새 키 만들기' : '지우기'}</button>
                          <button type="button" disabled={busy} className={BTN2} onClick={() => setStep(null)}>그만두기</button>
                        </div>
                      </div>
                    )}
                    {err?.uid === m.uid && <p role="alert" className="m-0 text-12 text-warn">{err.text}</p>}
                  </li>
                )
              })}
            </ul>
          )}
          {list && list.length === 0 && !listErr && <p className="m-0 text-13 text-ink-3">아직 멤버가 없습니다.</p>}

          {!adding ? (
            <div><button type="button" className={BTN} onClick={() => { setAdding(true); setName(''); setErr(null) }}>멤버 추가</button></div>
          ) : (
            <form className="flex flex-wrap gap-2" onSubmit={e => { e.preventDefault(); add() }}>
              <input value={name} onChange={e => setName(e.target.value)} maxLength={20} placeholder="이름(1~20자)" aria-label="새 멤버 이름" autoFocus className={`${INPUT} flex-1 basis-40`} />
              <button type="submit" disabled={busy} className={BTN}>{busy ? '만드는 중' : '키 만들기'}</button>
              <button type="button" disabled={busy} className={BTN2} onClick={() => { setAdding(false); setName('') }}>그만두기</button>
            </form>
          )}
          {err?.uid === '' && <p role="alert" className="m-0 text-12 text-warn">{err.text}</p>}
        </div>
      </Card>

      <Card title="마스터 예비 키">
        <div className="flex flex-col gap-2">
          <p className="m-0 text-12 text-ink-2">마스터 키를 잃었을 때 들어올 수 있는 두 번째 키입니다. 만들면 따로 적어 두세요.</p>
          <div><button type="button" disabled={busy} className={BTN2} onClick={backup}>{hasBackup ? '다시 만들기' : '마스터 예비 키 만들기'}</button></div>
        </div>
      </Card>
    </div>
  )
}

/** 키를 한 번만 보여 주는 카드 — 복사는 누를 때 바로(클립보드 권한은 누른 순간에만 열린다). 실패하면 키 글자를 선택해 둔다. */
function KeyCard({ issued, onClose }: { issued: Issued; onClose: () => void }) {
  const code = useRef<HTMLElement>(null)
  const [done, setDone] = useState('')
  const copy = (text: string, ok: string) => {
    const pick = () => {
      const el = code.current
      if (el) { const r = document.createRange(); r.selectNodeContents(el); const sel = getSelection(); sel?.removeAllRanges(); sel?.addRange(r) }
      setDone('복사하지 못했습니다. 키 글자를 선택해 두었으니 길게 눌러 복사하세요.')
    }
    try { navigator.clipboard.writeText(text).then(() => setDone(ok), pick) } catch { pick() }
  }
  return (
    <Card title={issued.title}>
      <div className="flex flex-col gap-3">
        <code ref={code} className="num block p-3 rounded-card border border-line bg-bg text-24 font-bold text-ink-1 text-center break-all select-all">{issued.key}</code>
        <p role="status" className="m-0 text-12 text-ink-2">{issued.note}</p>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={BTN} onClick={() => copy(issued.key, '키를 복사했습니다.')}>키 복사</button>
          {issued.kakao && <button type="button" className={BTN2} onClick={() => copy(kakaoText(issued.key), '카톡에 보낼 글을 복사했습니다.')}>카톡에 보낼 글 복사</button>}
          <button type="button" className={BTN2} onClick={onClose}>닫기</button>
        </div>
        {done && <p role="status" className="m-0 text-12 text-ink-2">{done}</p>}
      </div>
    </Card>
  )
}
