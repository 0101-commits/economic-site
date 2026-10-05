// 알림 조건 한 줄의 상태 — 순수 함수만. node --test 로 바로 돈다(alertStatus.test.ts).
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(calc.ts 와 같은 규칙).
//
// 새 화면 조건의 단일 원천 규칙 — 서버 짝은 scripts/check_alerts.py _check_prefs · _rearmed.
//   조건 id   화면이 만들 때 한 번 정한다(condId). 조건 객체에 실려 Worker /prefs 로 가고, 서버는 그 문자열을 그대로
//             공개 기록 alerts_state.json._prefs 의 키로 쓴다. 어느 쪽도 id 를 다시 계산하지 않는다.
//   발동 기록 서버만 쓴다 — _prefs[id] = { date:'YYYYMMDD'(KST), ts:초, fired?:true, hist, keys(해시) … }. 조건 내용은 없다.
//             화면은 발동을 판정하지 않고 이 기록만 읽는다.
//   끝남      fired = 「한 번」인 price·pct·high52·lens 가 울린 뒤. 서버는 그 조건을 더 보지 않는다.
//   다시 켜기 cond.armedAt(ISO)을 마지막 발동(ts)보다 뒤로 찍는다(rearm). 서버는 ts < armedAt ≤ 지금이면 다시 본다.
//             끝남 관문만 열린다 — 같은 발생(같은 기준일 값)은 다시 안 보내고 새 값이 들어오면 한 번 울린다.
//             /prefs 로 올라가야 서버가 보므로 화면은 동기화가 켜져 있을 때만 단추를 보인다.
//             id 를 바꾸지 않으므로 지난 발동이 받은 알림에 그대로 남는다. armedAt 은 비공개 /prefs 에만 있다.
import { mdHm, shortDate } from '../format.ts'
import type { AlertCond } from './store'

/** 새 조건 id — Worker PREFS_ID(/^[A-Za-z0-9._:^=-]{1,64}$/)를 통과하는 'p' + 만든 시각 + 임의 6자.
 *  임의 부분은 늘 6자로 채운다 — Math.random().toString(36) 은 자릿수가 들쭉날쭉해(0.5 → "0.i") 전엔 1~4자가 되어
 *  같은 밀리초 안에서 겹쳤고, 그 간헐 검사 실패가 Pages 배포를 5번 막았다(2026-10-02~04 실측). */
export const condId = (now = Date.now(), rnd = Math.random()) => 'p' + now.toString(36) + (rnd.toString(36).slice(2) + '000000').slice(0, 6)

/** alerts_state.json._prefs[id] 가운데 화면이 읽는 칸. */
export type FiredRec = { date?: string; ts?: number; fired?: boolean }
export type CondStatus = { kind: 'off' | 'local' | 'wait' | 'fired' | 'today'; text: string }

const armedSec = (a: AlertCond) => {
  const t = Date.parse(String(a.cond?.armedAt ?? ''))
  return Number.isNaN(t) ? 0 : Math.floor(t / 1000)
}

/** 조건 행의 상태 낱말. today = 한국 날짜 'YYYY-MM-DD'(calc.ts kstDay). 「다시 켜기」는 kind 'fired' 에만.
 *  synced = 이 탭의 동기화가 켜져 있음. 꺼져 있으면 서버가 이 조건을 못 봤을 수 있으니 「대기」 대신 「이 기기에만」(kind 'local')이라 말한다. */
export function condStatus(a: AlertCond, rec: FiredRec | undefined, today: string, synced = true): CondStatus {
  if (!a.enabled) return { kind: 'off', text: '꺼짐' }
  const ts = rec?.ts ?? 0
  if (rec?.fired && !(armedSec(a) > ts)) return { kind: 'fired', text: ts ? `발동됨 ${mdHm(new Date(ts * 1000))}` : '발동됨' }
  if (a.repeat === 'daily' && rec?.date === today.replace(/-/g, '')) return { kind: 'today', text: `오늘 발동 ${shortDate(today)}` }
  return synced ? { kind: 'wait', text: '대기' } : { kind: 'local', text: '이 기기에만 · 울리지 않음' }
}

/** 다시 켜기: 같은 id 에 armedAt 을 찍는다. 기기 시계가 늦어도 마지막 발동보다는 뒤가 되게 한다. */
export function rearm(a: AlertCond, rec: FiredRec | undefined, now = Date.now()): AlertCond {
  return { ...a, cond: { ...a.cond, armedAt: new Date(Math.max(now, ((rec?.ts ?? 0) + 1) * 1000)).toISOString() } }
}

/** Worker /prefs 의 target 형식 — 지표 id · 종목 코드. */
export const TARGET_RE = /^[A-Za-z0-9._:^=-]{1,64}$/

/** 주소의 `?id=` 로 새 조건 폼의 대상을 미리 채운다. 사전에 있으면 이름, 없으면 id 그대로. 형식이 틀리면 null. */
export function prefillTarget(id: string, rows: { id: string; label: string; short?: string }[]): { id: string; label: string } | null {
  if (!TARGET_RE.test(id)) return null
  const r = rows.find(x => x.id === id)
  return { id, label: r ? r.short || r.label : id }
}
