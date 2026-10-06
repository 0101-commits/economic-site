// 「현행 조건 가져오기」 — 현행 화면(js/app2.js)의 알림 조건 → 새 조건(v2). 순수 함수만(node --test, legacy.test.ts).
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다.
//
// 변환(계약서 C2): price_above · price_below → U1(방향 · 값) · pct_change → U2(값 = 절댓값) · high52 · low52 → B1(대상 조정, 울림 켬).
//   golden_cross · dead_cross 는 사전에 없어 가져오지 않는다. 그 밖 종류(z_move · vol_surge …)와 모양이 틀린 줄도 가져오지 않는다.
//   종목 이름은 조건 이름에 넣는다(예: 「삼성전자 80,000 아래로」) — 코드만 있으면 목록에서 무엇인지 알 수 없다.
//   같은 대상 · 사건 · 값이 이미 있거나 이번 묶음 안에서 겹치면 건너뛴다. 52주 신고가 · 신저가는 한 사건(B1)이라 대상당 한 건만 남는다.
//   현행 화면의 조건은 지우지 않는다 — 읽기만 한다.
import { condId, condName, TARGET_RE } from '../personal/alertStatus.ts'
import type { AlertCond } from '../personal/store'
import { ALERT_CAP } from './v2.ts'

export type Imported = {
  add: AlertCond[]
  dup: number     // 이미 있거나 이번 묶음 안에서 겹침
  cross: number   // 골든 · 데드크로스(사전에 없음)
  other: number   // 그 밖 종류 · 모양이 틀린 줄
  over: number    // 한도(ALERT_CAP) 때문에 못 담음
  total: number   // 읽은 줄 수
}

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)

/** 같은 조건인지 가르는 열쇠: 대상 · 사건 · 값(U1 은 방향까지). B1 · 사건 전체 조정은 값이 없어 대상 · 사건만. */
export function condKey(a: AlertCond): string {
  if (a.event === 'U1') return `${a.target}|U1|${a.dir ?? 'up'}|${a.value}`
  if (a.event === 'U2') return `${a.target}|U2|${a.value}`
  return `${a.target}|${a.event}`
}

/**
 * rows = 현행 조건 배열(alerts_config.json 의 alerts), existing = 이 기기의 조건, eventName = 사전의 사건 이름.
 * mk = 새 조건 id 를 만드는 함수(시험에서 바꿔 끼운다).
 */
export function convertLegacy(rows: unknown, existing: AlertCond[], eventName: (id: string) => string | undefined, mk: () => string = condId): Imported {
  const out: Imported = { add: [], dup: 0, cross: 0, other: 0, over: 0, total: 0 }
  const seen = new Set(existing.map(condKey))
  for (const r of Array.isArray(rows) ? rows : []) {
    out.total++
    if (!isObj(r)) { out.other++; continue }
    const type = r.type
    if (type === 'golden_cross' || type === 'dead_cross') { out.cross++; continue }
    const symbol = typeof r.symbol === 'string' ? r.symbol.trim() : ''
    const v = Number(r.value)
    const a: AlertCond = { id: '', event: '', target: symbol, repeat: 'each', ring: true, enabled: r.enabled !== false }
    if (type === 'price_above' || type === 'price_below') {
      if (!(Number.isFinite(v) && v > 0)) { out.other++; continue }
      a.event = 'U1'; a.dir = type === 'price_above' ? 'up' : 'down'; a.value = v
    } else if (type === 'pct_change') {
      if (!(Number.isFinite(v) && v !== 0)) { out.other++; continue }
      a.event = 'U2'; a.dir = v < 0 ? 'down' : 'up'; a.value = Math.abs(v)
    } else if (type === 'high52' || type === 'low52') {
      a.event = 'B1'
    } else { out.other++; continue }
    if (!TARGET_RE.test(symbol)) { out.other++; continue }
    const k = condKey(a)
    if (seen.has(k)) { out.dup++; continue }
    if (existing.length + out.add.length >= ALERT_CAP) { out.over++; continue }
    seen.add(k)
    const label = typeof r.name === 'string' && r.name.trim() ? r.name.trim() : symbol
    out.add.push({ ...a, id: mk(), name: condName(a, label, eventName(a.event)).slice(0, 40) })
  }
  return out
}
