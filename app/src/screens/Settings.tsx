// 설정 — 기획안 v4 7장 · 사용 패턴 명세 S2. 차례: 기기 연결 → 보안 → 표시 → 내 데이터 → 데이터 상태(접힘) → 고급(접힘).
// 화면 전체가 PIN 뒤다(App.tsx PinGate). 화면 모드만은 머리의 단추로 PIN 없이 바꾼다.
// 보호 수준은 있는 그대로 적는다: PIN 은 화면 잠금(열람 방지)이고, 기기 안의 자료를 암호화하지 않는다.
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, Settings as Gear } from 'lucide-react'
import { Card, Pill, SegBar } from '../components/ui'
import { BTN, BTN2, Field, INPUT, Switch } from '../components/personal/bits'
import { DeviceLink } from '../components/personal/DeviceLink'
import { UsageTable } from '../components/personal/UsageTable'
import { applyTheme, readTheme, useTheme } from '../lib/theme'
import { checkPin, hasPin, IDLE_MS, isUnlocked, setPin, waitMs } from '../lib/pin'
import { loadBundle, ROOT } from '../lib/bundle'
import { mdHm } from '../lib/format'
import { kakaoToday, type Dict } from '../lib/alerts/v2'
import { kstDay } from '../lib/personal/calc'
import { loadRootJson } from '../lib/personal/data'
import { applyUpdown, KEYS, readLedger, readPortfolio, readPrefs, readSnaps, wipeDevice, writePrefs, type Prefs, type Settings as S } from '../lib/personal/store'
import { disableSync, getKeyHash, useSyncStatus } from '../lib/personal/sync'
import dictJson from '../lib/alerts/dict.json'

const THEMES = [{ key: 'system', label: '기기 설정' }, { key: 'light', label: '밝게' }, { key: 'dark', label: '어둡게' }] as const
const UPDOWN = [{ key: 'kr', label: '한국식 · 오름 빨강' }, { key: 'us', label: '서양식 · 오름 초록' }] as const
const UNITS = [{ key: 'man', label: '만원' }, { key: 'won', label: '원' }] as const
const QUIET_PKG = (dictJson as unknown as Dict).packages.find(p => p.id === 'quiet')?.name ?? ''

export default function Settings() {
  const [prefs, setPrefs] = useState<Prefs>(readPrefs)
  const t = useTheme()
  const [msg, setMsg] = useState('')
  const { rev } = useSyncStatus()
  useEffect(() => { if (rev) setPrefs(readPrefs()) }, [rev])   // 동기화가 이 기기를 서버 내용으로 덮은 뒤
  const save = (p: Prefs) => { setPrefs(p); setMsg(writePrefs(p) ? '' : '이 기기에 저장하지 못했습니다.') }
  const setS = (k: Partial<S>) => save({ ...prefs, settings: { ...prefs.settings, ...k } })

  return (
    <div className="flex flex-col gap-4">
      <header><h1 className="m-0 inline-flex items-center gap-1.5 text-18 font-bold text-ink-1"><Gear size={18} aria-hidden />설정</h1></header>
      {msg && <p role="alert" className="m-0 text-12 text-warn">{msg}</p>}
      <div className="grid grid-cols-1 pc:grid-cols-2 gap-4 items-start">
        <DeviceLink />
        <Security />
        <Card title={<>표시 <span className="text-12 font-normal text-ink-3">화면 모드 · 금액 단위는 이 기기만</span></>}>
          <div className="flex flex-col gap-3">
            <div><p className="m-0 mb-1 text-12 text-ink-2">등락 색 · 모든 기기</p><SegBar label="등락 색" options={UPDOWN} value={prefs.settings.updown} onChange={u => { setS({ updown: u }); applyUpdown(u) }} /></div>
            <div><p className="m-0 mb-1 text-12 text-ink-2">화면 모드</p><SegBar label="화면 모드" options={THEMES} value={t} onChange={applyTheme} /></div>
            <div><p className="m-0 mb-1 text-12 text-ink-2">금액 단위(내 자산)</p><SegBar label="금액 단위" options={UNITS} value={prefs.settings.unit} onChange={u => setS({ unit: u })} /></div>
          </div>
        </Card>
        <MyData />
        <Fold title="데이터 상태"><DataStatus /></Fold>
        <Fold title="고급"><Advanced s={prefs.settings} setS={setS} /></Fold>
      </div>
      {/* 전환 단계 A(공존): 현행 화면으로 가는 길 하나. 같은 origin 이라 PIN·보유·관심이 그대로다. */}
      <p className="m-0 text-12 text-ink-3"><a href={new URL('legacy.html', ROOT).href} className="text-ink-3 hover:text-ink-1">이전 화면으로</a> · 폰 알림은 이 화면을 홈 화면에 추가한 기기로만 옵니다.</p>
    </div>
  )
}

/** 접힌 채 시작하는 칸(데이터 상태 · 고급). 패널 접기 기억(lib/fold.ts)과 다르다 — 늘 접혀서 열리고, 연 뒤에만 안을 만든다. */
function Fold({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <Card>
      <details open={open} onToggle={e => setOpen(e.currentTarget.open)}>
        <summary className="list-none cursor-pointer [&::-webkit-details-marker]:hidden flex items-center gap-2">
          <h3 className="m-0 text-14 font-bold text-ink-1">{title}</h3>
          <ChevronDown size={16} aria-hidden className={`ml-auto text-ink-3 ${open ? 'rotate-180' : ''}`} />
        </summary>
        {open && <div className="mt-3">{children}</div>}
      </details>
    </Card>
  )
}

/** 보안: PIN 켜기·바꾸기(lib/pin.ts — 현행 화면과 같은 PIN) · 자동 잠금. 지문·얼굴은 2026-10-02 사용자 결정으로 뺐다(PIN 만). */
function Security() {
  const [has, setHas] = useState(hasPin)
  const [cur, setCur] = useState('')
  const [p1, setP1] = useState('')
  const [p2, setP2] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!/^\d{6}$/.test(p1)) { setNote('새 PIN 은 숫자 6자리입니다.'); return }
    if (p1 !== p2) { setNote('새 PIN 두 칸이 다릅니다.'); return }
    setBusy(true)
    try {
      if (has && !(await checkPin(cur))) { const w = waitMs(); setNote(w ? `PIN 을 여러 번 틀렸습니다 · ${Math.ceil(w / 1000)}초 뒤 다시` : '지금 PIN 이 맞지 않습니다.'); return }
      await setPin(p1)
      setHas(true); setCur(''); setP1(''); setP2(''); setNote(has ? 'PIN 을 바꿨습니다.' : 'PIN 을 켰습니다. 내 자산은 이 PIN 으로 엽니다.')
    } catch { setNote('이 환경(https 아님)에서는 잠금을 쓸 수 없습니다.') } finally { setBusy(false) }
  }
  const pinInput = (v: string, set: (s: string) => void, label: string) => (
    <Field label={label}><input type="password" inputMode="numeric" autoComplete="off" maxLength={6} className={INPUT} value={v} onChange={e => set(e.target.value.replace(/\D/g, ''))} /></Field>
  )
  return (
    <Card title="보안">
      <p className="m-0 text-13 text-ink-2">화면 잠금 · 열람 방지용입니다. 어깨너머로 내 자산을 보는 것을 막고, 기기 안의 자료를 암호화하지는 않습니다.</p>
      <form onSubmit={submit} className="mt-3 flex flex-col gap-2" aria-label={has ? 'PIN 바꾸기' : 'PIN 켜기'}>
        <p className="m-0 text-13 font-bold text-ink-1">{has ? 'PIN 바꾸기' : 'PIN 켜기'}</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {has && pinInput(cur, setCur, '지금 PIN')}
          {pinInput(p1, setP1, '새 PIN 6자리')}
          {pinInput(p2, setP2, '한 번 더')}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="submit" disabled={busy} className={BTN}>{busy ? '확인 중' : has ? '바꾸기' : '켜기'}</button>
          <span role="alert" className="text-12 text-ink-2">{note}</span>
        </div>
      </form>
      <dl className="mt-3 mb-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-13">
        <dt className="text-ink-3">자동 잠금</dt>
        <dd className="m-0 text-ink-1"><span className="num">{IDLE_MS / 60_000}</span>분 동안 조작이 없으면 다시 잠급니다 · 탭을 닫아도 잠깁니다</dd>
      </dl>
    </Card>
  )
}

/** 내 데이터: 내려받기(잠금을 연 뒤에만) · 이 기기 데이터 지우기(확인 2번). 기기 간 맞춤은 「기기 연결」. */
function MyData() {
  const [note, setNote] = useState('')
  const [step, setStep] = useState(0)
  const download = () => {
    // 보유 금액이 든 파일이라 내 자산 잠금이 열려 있을 때만 만든다(PinGate 와 같은 판정)
    if (!isUnlocked()) { setNote('locked'); return }
    let watch: unknown = []
    try { watch = JSON.parse(localStorage.getItem(KEYS.watch) || '[]') } catch { /* 빈 목록 */ }
    const prefs = readPrefs()
    const doc = {
      exportedAt: new Date().toISOString(), note: '이 파일에는 평단가·수량이 들어 있습니다. 남에게 보내지 마세요.',
      portfolio: readPortfolio(), snapshots: readSnaps(), ledger: readLedger(), watch, prefs: { ...prefs, settings: { ...prefs.settings, theme: readTheme() } }, scenarios: prefs.scenarios,
    }
    const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' }))
    const a = Object.assign(document.createElement('a'), { href: url, download: `ecom-내데이터-${new Date().toISOString().slice(0, 10)}.json` })
    document.body.appendChild(a); a.click(); a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    setNote('saved')
  }
  return (
    <Card title="내 데이터">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className={BTN2} onClick={download}>내 데이터 내려받기</button>
          <span className="text-12 text-ink-3">보유 · 스냅샷 · 원장 · 관심 · 알림 조건 · 설정</span>
        </div>
        {note === 'locked' && <p role="alert" className="m-0 text-12 text-warn">평단가·수량이 든 파일이라 <Link to="/my">내 자산</Link>을 PIN 으로 연 뒤 5분 안에 내려받을 수 있습니다.</p>}
        {note === 'saved' && <p className="m-0 text-12 text-ink-3">파일을 저장했습니다. 평단가·수량이 들어 있으니 남에게 보내지 마세요.</p>}
      </div>

      <div className="mt-4 pt-3 border-t border-line">
        {step === 0 && <button type="button" className={BTN2} onClick={() => setStep(1)}>이 기기 데이터 지우기</button>}
        {step === 1 && (
          <div className="flex flex-col gap-2">
            <p className="m-0 text-13 text-ink-1">지울 것: 보유 종목 · 평가액 스냅샷 · 배당·입출금 원장 · 관심 · 알림 조건 · 표시 설정 · 렌즈 시나리오 · 최근 검색 · 기기 연결(키 해시 · 보유 열쇠) · 현행 화면 동기화 키와 보유 암호.</p>
            <p className="m-0 text-12 text-ink-3">현행 화면도 같은 보유·스냅샷·원장을 쓰므로 거기서도 사라집니다. 잠금 PIN 은 남깁니다. 기기 연결을 끊고 이 기기의 폰 알림 구독도 끊습니다(서버에 맡긴 것은 남습니다).</p>
            <div className="flex flex-wrap gap-2">
              <button type="button" className={BTN2} onClick={() => setStep(2)}>계속</button>
              <button type="button" className={BTN2} onClick={() => setStep(0)}>그만두기</button>
            </div>
          </div>
        )}
        {step === 2 && (
          <div className="flex flex-col gap-2">
            <p role="alert" className="m-0 text-13 font-bold text-warn">되돌릴 수 없습니다. 정말 지울까요?</p>
            <div className="flex flex-wrap gap-2">
              <button type="button" className={BTN} onClick={async () => { if (await wipeDevice(getKeyHash)) { disableSync(); location.reload() } else setStep(0) }}>지우기</button>
              <button type="button" className={BTN2} onClick={() => setStep(0)}>그만두기</button>
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}

type Meta = {
  generatedAt?: string; dataUpdated?: string
  health?: { checkedAt?: string; summary?: Record<string, number>; issues?: { path: string; state: string; asOf?: string | null; ageDays?: number | null }[] }
}
const HEALTH: { key: string; label: string; tone: 'g' | 'n' | 'x' | 'o' }[] = [
  { key: 'ok', label: '정상', tone: 'g' }, { key: 'preserved', label: '직전 값', tone: 'n' }, { key: 'stale', label: '지연', tone: 'n' },
  { key: 'suspect', label: '검증 필요', tone: 'n' }, { key: 'missing', label: '자료 없음', tone: 'o' }, { key: 'failed', label: '실패', tone: 'x' },
]

/** 데이터 상태: bundles/meta.json 의 판정 요약 + 마지막 수집 시각. */
function DataStatus() {
  const [m, setM] = useState<Meta | null | undefined>(undefined)
  useEffect(() => { loadBundle<Meta>('meta').then(setM, () => setM(null)) }, [])
  const s = m?.health?.summary
  return m === undefined ? <p className="m-0 text-13 text-ink-3">불러오는 중</p> : !m ? <p className="m-0 text-13 text-ink-3">상태 파일을 불러오지 못했습니다.</p> : (
    <div className="flex flex-col gap-3">
      <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-13">
        <dt className="text-ink-3">마지막 수집</dt><dd className="m-0 num text-ink-1">{m.dataUpdated ? mdHm(m.dataUpdated) : '—'}</dd>
        <dt className="text-ink-3">화면 묶음 생성</dt><dd className="m-0 num text-ink-1">{m.generatedAt ? mdHm(m.generatedAt) : '—'}</dd>
        <dt className="text-ink-3">상태 점검</dt><dd className="m-0 num text-ink-1">{m.health?.checkedAt ? mdHm(m.health.checkedAt) : '—'}</dd>
      </dl>
      {s && (
        <ul className="m-0 p-0 list-none flex flex-wrap gap-x-3 gap-y-2" aria-label={`지표 ${s.total ?? ''}개 상태`}>
          {HEALTH.filter(h => (s[h.key] ?? 0) > 0 || h.key === 'ok').map(h => (
            <li key={h.key} className="inline-flex items-center gap-1.5 text-13"><Pill tone={h.tone}>{h.label}</Pill><span className="num text-ink-1">{s[h.key] ?? 0}</span></li>
          ))}
          <li className="text-12 text-ink-3 self-center">전체 <span className="num">{s.total ?? '—'}</span>개</li>
        </ul>
      )}
      {!!m.health?.issues?.length && (
        <ul className="m-0 p-0 list-none">
          {m.health.issues.slice(0, 6).map(i => (
            <li key={i.path} className="flex items-baseline gap-2 py-1 border-b border-line last:border-b-0 text-12">
              <span className="min-w-0 flex-1 text-ink-2">{i.path}</span>
              <span className="text-ink-3">{HEALTH.find(h => h.key === i.state)?.label ?? i.state}{i.ageDays != null ? ` · ${i.ageDays}일` : ''}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** 고급: 카톡(명세 S7 — 알림 › 채널에서 옮김) · 90일 자동 강등 끄기(S10). 사용 기록 「내 사용」 표(I8)도 이 칸 끝에 들어온다. */
function Advanced({ s, setS }: { s: S; setS: (k: Partial<S>) => void }) {
  return (
    <div className="flex flex-col gap-4">
      <Kakao s={s} setS={setS} />
      <div className="pt-3 border-t border-line">
        <Switch on={s.autoQuiet} onChange={v => setS({ autoQuiet: v })} label={`90일 동안 알림 화면을 안 열면 꾸러미를 「${QUIET_PKG}」로 내리기`} />
        <p className="mt-1 mb-0 text-12 text-ink-3">이 기기만. 내려가면 알림 화면 맨 위에 한 줄로 알립니다. 끄면 꾸러미를 그대로 둡니다.</p>
      </div>
      <div className="pt-3 border-t border-line"><UsageTable /></div>
    </div>
  )
}

/** 카톡: 친구 모드 · 받는 사람(≤5). 오늘 몇 통은 원장(events/latest.json)에서 센다. */
function Kakao({ s, setS }: { s: S; setS: (k: Partial<S>) => void }) {
  const [today, setToday] = useState<number | null>(null)
  useEffect(() => { loadRootJson<unknown>('events/latest.json').then(r => setToday(kakaoToday(r, kstDay())), () => {}) }, [])
  const rcp = s.kakaoRecipients
  const setRcp = (i: number, p: Partial<S['kakaoRecipients'][number]>) => setS({ kakaoRecipients: rcp.map((r, j) => (j === i ? { ...r, ...p } : r)) })
  return (
    <div>
      <p className="m-0 mb-2 text-13 font-bold text-ink-1">카톡 <span className="font-normal text-12 text-ink-3">오늘 <span className="num">{today ?? '—'}/20</span>통</span></p>
      <Switch on={s.kakaoFriends} onChange={v => setS({ kakaoFriends: v })} label="친구 모드로 받기" />
      <p className="mt-1 mb-0 text-12 text-ink-3">보조 계정이 친구인 나에게 사진 카드로 보냅니다. 운영 쪽에서 친구 모드를 켜야 실제로 갑니다 — 그 전에는 카톡이 나가지 않고 폰 · 디스코드만 갑니다. 카카오 한도는 받는 사람마다 하루 20통입니다.</p>
      {s.kakaoFriends && (
        <div className="mt-3 flex flex-col gap-2">
          <p className="m-0 text-12 text-ink-2">받는 사람 <span className="num">{rcp.length}</span>/5</p>
          {rcp.map((r, i) => (
            <div key={i} className="flex flex-wrap items-end gap-2">
              <Field label="이름(카톡 친구 이름 그대로)" className="flex-1 min-w-40"><input className={INPUT} value={r.name} maxLength={20} onChange={e => setRcp(i, { name: e.target.value })} /></Field>
              <Switch on={r.briefOnly} onChange={v => setRcp(i, { briefOnly: v })} label="브리핑만" />
              <button type="button" className={BTN2} onClick={() => setS({ kakaoRecipients: rcp.filter((_, j) => j !== i) })}>빼기</button>
            </div>
          ))}
          {rcp.length < 5 && <button type="button" className={`${BTN2} self-start`} onClick={() => setS({ kakaoRecipients: [...rcp, { uuid: '', name: '', briefOnly: false }] })}>받는 사람 더하기</button>}
        </div>
      )}
    </div>
  )
}
