// 알림 조건 한 줄의 상태 — 순수 함수만. node --test 로 바로 돈다(alertStatus.test.ts).
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(calc.ts 와 같은 규칙).
//
// 사용자 조건의 단일 원천 규칙 — 서버 짝은 scripts/alerts_v2/subscribe.py user_hits · _fired_after_arm.
//   조건 id   화면이 만들 때 한 번 정한다(condId). 조건 객체에 실려 Worker /prefs 로 가고, 서버는 울린 원장 행에
//             cond = id 로 적는다(임계값은 안 적는다). 어느 쪽도 id 를 다시 계산하지 않는다.
//   울림 기록 서버만 쓴다 — 원장 events/latest.json 의 행(cond · ts · sent{held,bundled}). 현행 서버의 공개 기록
//             alerts_state.json._prefs[id] = { ts:초, fired?:true } 도 읽는다(원장이 생기기 전 울린 것).
//             화면은 울림을 판정하지 않고 이 기록만 읽는다.
//   멈춤      「한 번」 조건이 armedAt 뒤에 울린 것. 서버는 그 조건을 더 보지 않는다.
//   다시 켜기 armedAt(ISO)을 마지막 울림보다 뒤로 찍는다(rearm). 서버는 armedAt 뒤의 울림만 센다.
//             /prefs 로 올라가야 서버가 보므로 화면은 동기화가 켜져 있을 때만 단추를 보인다.
//             id 를 바꾸지 않으므로 지난 울림이 받은 알림에 그대로 남는다. armedAt 은 비공개 /prefs 에만 있다.
//   상태 7    대기 · 울림 M/D HH:mm · 멈춤(→ 다시 켜기) · 묶임 · 보류(→ 07:30) · 꺼짐 · 이 기기만.
import { fmtNumber, mdHm } from '../format.ts'
import type { AlertCond } from './store'

/** 새 조건 id — Worker PREFS_ID(/^[A-Za-z0-9._:^=-]{1,64}$/)를 통과하는 'p' + 만든 시각 + 임의 6자.
 *  임의 부분은 늘 6자로 채운다 — Math.random().toString(36) 은 자릿수가 들쭉날쭉해(0.5 → "0.i") 전엔 1~4자가 되어
 *  같은 밀리초 안에서 겹쳤고, 그 간헐 검사 실패가 Pages 배포를 5번 막았다(2026-10-02~04 실측). */
export const condId = (now = Date.now(), rnd = Math.random()) => 'p' + now.toString(36) + (rnd.toString(36).slice(2) + '000000').slice(0, 6)

/** alerts_state.json._prefs[id] 가운데 화면이 읽는 칸. */
export type FiredRec = { date?: string; ts?: number; fired?: boolean }
/** 원장 행(계약서 「원장 행」) 가운데 화면이 읽는 칸. */
export type LedgerRow = {
  key: string; event: string; target: string; dir?: string; level: string; value?: number | string | null; unit?: string
  asOf?: string; title: string; why?: string; next?: string; url?: string; ts: string; cond?: string
  sent?: { push?: number; kakao?: boolean; discord?: boolean; bundled?: boolean; held?: boolean }
}
export type CondKind = 'off' | 'local' | 'wait' | 'rang' | 'stopped' | 'bundled' | 'held'
export type CondStatus = { kind: CondKind; text: string }

const sec = (v: unknown) => { const t = Date.parse(String(v ?? '')); return Number.isNaN(t) ? 0 : Math.floor(t / 1000) }
const HELD_MS = 12 * 3_600_000   // 보류는 그날 밤 → 아침 07:30 까지만 「보류」. 그 뒤엔 울림으로 본다

/**
 * 조건 행의 상태. rows = 원장 행(이 조건 것만 골라 쓴다) · fired = 현행 서버 공개 기록 · synced = 이 탭의 동기화가 켜짐 ·
 * autoOff = 자동 정리가 끈 조건(housekeeping). 동기화가 꺼져 있으면 서버가 이 조건을 못 봤을 수 있으니 「대기」 대신 「이 기기에만」.
 */
export function condStatus(a: AlertCond, rows: LedgerRow[], fired: FiredRec | undefined, synced = true, autoOff = false, now = Date.now()): CondStatus {
  if (!a.enabled) return { kind: 'off', text: autoOff ? '180일 조용 · 꺼짐' : '꺼짐' }
  const armed = sec(a.armedAt)
  const last = rows.reduce<LedgerRow | null>((m, r) => (r.cond === a.id && (!m || sec(r.ts) > sec(m.ts)) ? r : m), null)
  const lastSec = Math.max(last ? sec(last.ts) : 0, fired?.ts ?? 0)
  if (a.repeat === 'once' && lastSec > armed && (last || fired?.fired)) return { kind: 'stopped', text: '멈춤' }
  if (last) {
    if (last.sent?.held && now - sec(last.ts) * 1000 < HELD_MS) return { kind: 'held', text: '보류 → 07:30' }
    if (last.sent?.bundled) return { kind: 'bundled', text: '묶임' }
  }
  if (lastSec) return { kind: 'rang', text: `울림 ${mdHm(new Date(lastSec * 1000))}` }
  return synced ? { kind: 'wait', text: '대기' } : { kind: 'local', text: '이 기기만 — 울리지 않음' }
}

/** 다시 켜기: 같은 id 에 armedAt 을 찍는다. 기기 시계가 늦어도 마지막 울림보다는 뒤가 되게 한다. */
export function rearm(a: AlertCond, rows: LedgerRow[], fired: FiredRec | undefined, now = Date.now()): AlertCond {
  const last = Math.max(fired?.ts ?? 0, ...rows.filter(r => r.cond === a.id).map(r => sec(r.ts)))
  return { ...a, armedAt: new Date(Math.max(now, (last + 1) * 1000)).toISOString() }
}

/** 조건 이름: 사용자가 붙인 이름, 없으면 「대상 조건」(달러원 1,400 위로 · KODEX 200 등락 ±3% · 금 52주 신고저). */
export function condName(a: AlertCond, label: string, eventName?: string): string {
  if (a.name?.trim()) return a.name.trim()
  if (a.event === 'U1' && a.value != null) return `${label} ${fmtNumber(a.value, a.value % 1 ? 2 : 0)} ${a.dir === 'down' ? '아래로' : '위로'}`
  if (a.event === 'U2' && a.value != null) return `${label} 등락 ±${a.value}%`
  return `${label} ${eventName ?? a.event}`
}

/** Worker /prefs 의 target 형식 — 지표 id · 종목 코드. */
export const TARGET_RE = /^[A-Za-z0-9._:^=-]{1,64}$/

/** 주소의 `?id=` 로 새 조건 폼의 대상을 미리 채운다. 사전에 있으면 이름, 없으면 id 그대로. 형식이 틀리면 null. */
export function prefillTarget(id: string, rows: { id: string; label: string; short?: string }[]): { id: string; label: string } | null {
  if (!TARGET_RE.test(id)) return null
  const r = rows.find(x => x.id === id)
  return { id, label: r ? r.short || r.label : id }
}
