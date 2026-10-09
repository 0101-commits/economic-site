// 지표 상세의 벨 — 알림 화면으로 가지 않고 그 자리에서 조건을 만드는 바닥 시트.
// 사건은 그 지표가 가질 수 있는 것만(lib/alerts/v2.ts sheetEvents) → 세기 3단(「지난 1년 N회」) → 등급 → 반복 → 울림 → 저장.
// 저장하면 이 기기 설정(econPrefsV1)에 넣고, 서버에 올라갔는지(동기화) 바로 한 줄로 말한다. 모양 = 계약서 AlertCond.
// 같은 지표 · 같은 사건의 조건이 이미 있으면 새로 만들지 않고 그것을 바꾼다(U1 · U2 는 값마다 따로).
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { loadBundle } from '../../lib/bundle'
import { BottomSheet, SegBar } from '../ui'
import { BTN, Field, INPUT, LV, Row, Switch } from './bits'
import { ALERT_CAP, levelChoices, savedNote, sheetEvents, yearCounts, type Dict } from '../../lib/alerts/v2'
import { loadDaily } from '../../lib/alerts/daily'
import { condId, repeatNote } from '../../lib/personal/alertStatus'
import { watchKind } from '../../lib/personal/remote'
import { KEYS, readPrefs, writePrefs, type AlertCond, type Level, type Strength } from '../../lib/personal/store'
import { useSyncStatus } from '../../lib/personal/sync'
import dictJson from '../../lib/alerts/dict.json'

const dict = dictJson as unknown as Dict
const STRENGTH_OPTS = dict.strengths.filter(s => s.sigma != null).map(s => ({ key: s.id as Strength, label: s.name }))
const REPEAT_OPTS = [{ key: 'each', label: '매번' }, { key: 'once', label: '한 번' }] as const
/** 조건 한도 문구 — 알림 화면 「새 조건」도 같은 글을 쓴다. */
export const CAP_MSG = `조건은 ${ALERT_CAP}건까지 만들 수 있습니다. 알림 화면에서 안 쓰는 조건을 지우세요.`

export function BellSheet({ open, onClose, id, label }: { open: boolean; onClose: () => void; id: string; label: string }) {
  return (
    <BottomSheet open={open} onClose={onClose} title={`${label} 알림 조건`}>
      {open && <BellForm id={id} />}
    </BottomSheet>
  )
}

function BellForm({ id }: { id: string }) {
  const sync = useSyncStatus()
  const stock = watchKind(id) === 'stock'
  // 렌즈 묶음에 든 지표인지: 렌즈 사건(C1 · C2)은 그때만 낸다. 묶음을 못 받으면 없는 것으로 본다.
  const [lens, setLens] = useState<ReadonlySet<string>>(new Set())
  useEffect(() => { loadBundle<{ triggers?: { id: string }[] }>('lens').then(b => setLens(new Set((b.triggers ?? []).map(t => t.id))), () => {}) }, [])
  const evs = useMemo(() => sheetEvents(dict, id, stock, lens), [id, stock, lens])
  const [event, setEvent] = useState('')
  const ev = evs.find(e => e.id === event) ?? evs[0]
  const [dir, setDir] = useState<'up' | 'down'>('up')
  const [value, setValue] = useState('')
  const [strength, setStrength] = useState<Strength>('big')
  const [level, setLevel] = useState<Level | ''>('')
  const [repeat, setRepeat] = useState<'each' | 'once'>('each')
  const [ring, setRing] = useState(true)
  const [err, setErr] = useState('')
  const [savedAt, setSavedAt] = useState(0)
  const [counts, setCounts] = useState<Record<string, number> | null>(null)
  const swing = !!ev?.strength
  useEffect(() => {
    setCounts(null)
    if (!swing) return
    let live = true
    loadDaily(id).then(sr => { if (live && sr) setCounts(yearCounts(sr, dict.strengths)) }, () => {})
    return () => { live = false }
  }, [id, swing])
  const base = ev.level
  const had = useMemo(() => (ev.userValue ? undefined : readPrefs().alerts.find(x => x.event === ev.id && x.target === id)), [ev, id, savedAt])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const v = Number(value)
    const a: AlertCond = { id: condId(), event: ev.id, target: id, repeat, ring, enabled: true }
    if (ev.id === 'U1') { if (value.trim() === '' || !Number.isFinite(v)) { setErr('값을 넣으세요.'); return } a.value = v; a.dir = dir }
    else if (ev.id === 'U2') { if (!(Math.abs(v) > 0)) { setErr('하루 등락률(%)을 넣으세요. 오름 · 내림 모두 봅니다.'); return } a.value = Math.abs(v) }
    if (swing && strength !== 'big') a.strength = strength
    if (level && level !== base) a.level = level
    const p = readPrefs()
    const old = ev.userValue ? undefined : p.alerts.find(x => x.event === ev.id && x.target === id)
    if (!old && p.alerts.length >= ALERT_CAP) { setErr(CAP_MSG); return }
    const next = old ? p.alerts.map(x => (x === old ? { ...a, id: old.id, ...(old.armedAt ? { armedAt: old.armedAt } : {}) } : x)) : [...p.alerts, a]
    if (!writePrefs({ ...p, alerts: next })) { setErr('이 기기에 저장하지 못했습니다. 시크릿 창이거나 저장 공간이 찼습니다.'); return }
    window.dispatchEvent(new StorageEvent('storage', { key: KEYS.prefs }))
    setErr(''); setValue(''); setSavedAt(Date.now())
  }
  const note = savedNote(sync, savedAt)

  return (
    <form onSubmit={submit} className="flex flex-col gap-3" aria-label="알림 조건 만들기">
      <Row label="사건"><SegBar label="사건" options={evs.map(e => ({ key: e.id, label: e.name }))} value={ev.id} onChange={k => { setEvent(k); setLevel(''); setErr('') }} /></Row>
      {ev.id === 'U1' && (
        <div className="grid grid-cols-2 gap-2">
          <Field label="방향"><select className={INPUT} value={dir} onChange={e => setDir(e.target.value as 'up' | 'down')}><option value="up">위로 넘으면</option><option value="down">아래로 내려가면</option></select></Field>
          <Field label="값"><input className={INPUT} value={value} onChange={e => setValue(e.target.value)} inputMode="decimal" /></Field>
        </div>
      )}
      {ev.id === 'U2' && <Field label="하루 등락률(%) · 오름 · 내림 모두" className="sm:max-w-60"><input className={INPUT} value={value} onChange={e => setValue(e.target.value)} inputMode="decimal" placeholder="3" /></Field>}
      {swing && (
        <Row label="세기">
          <SegBar label="세기" value={strength} onChange={setStrength}
            options={STRENGTH_OPTS.map(o => ({ ...o, label: counts?.[o.key] != null ? `${o.label} · 1년 ${counts[o.key]}회` : o.label }))} />
          {counts && <p className="m-0 mt-1 text-12 text-ink-3">{new Set(Object.values(counts)).size === 1
            ? '지난 1년 하루 등락이 그 세기를 넘은 날 수입니다. 이 지표는 변동이 커서 세 세기 모두 상한 5%에서 걸립니다 — 세기를 바꿔도 횟수가 같습니다.'
            : '지난 1년 하루 등락이 그 세기를 넘은 날 수입니다.'}</p>}
        </Row>
      )}
      <Row label="등급"><SegBar label="등급" options={levelChoices(base).map(l => ({ key: l, label: LV[l] }))} value={(level || base) as Level} onChange={setLevel} /></Row>
      <Row label="반복">
        <SegBar label="반복" options={REPEAT_OPTS} value={repeat} onChange={setRepeat} />
        <p className="m-0 mt-1 text-12 text-ink-3">{repeatNote(ev.id, repeat)}{repeat === 'once' ? ' 알림 화면에서 「다시 켜기」로 다시 켭니다.' : ''}</p>
      </Row>
      <Switch on={ring} onChange={setRing} label="울림(끄면 받은 알림에만 남음)" />
      {had && <p className="m-0 text-12 text-ink-3">이 사건의 조건이 이미 있어 저장하면 그것을 바꿉니다.</p>}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <button type="submit" className={BTN}>조건 저장</button>
        <span role="alert" className="text-12 text-warn">{err}</span>
        {!err && note && <span role="status" className="text-12 text-ink-2">{note}</span>}
      </div>
      <Link to={`/alerts?v=cond&id=${encodeURIComponent(id)}`} className="self-start text-12 text-ink-2 no-underline hover:text-ink-1">알림 화면에서 이름 붙여 만들기</Link>
    </form>
  )
}
