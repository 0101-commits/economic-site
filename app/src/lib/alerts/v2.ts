// 알림 화면 v2 의 순수 계산 — 받은 알림 묶기 · 거르기, 사건 탭 셈, 세기별 「지난 1년 N회」. node --test(v2.test.ts).
// 이름 · 라벨은 사전(dict.json, scripts/alerts_v2/export_dict.py 산출)에서만 — 이 파일은 사전을 인자로 받는다.
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다.
import { kstDay } from '../personal/calc.ts'
import type { LedgerRow } from '../personal/alertStatus.ts'
import type { AlertCond, Level } from '../personal/store'

export type DictEvent = {
  id: string; name: string; family: string; level: Level; targets: string[]; defaultOn: string[]
  enabled: boolean; strength: boolean; userValue: boolean
}
export type Dict = { families: { id: string; name: string }[]; levels: { id: string; name: string }[]; packages: { id: string; name: string }[]; strengths: { id: string; name: string; sigma: number | null }[]; events: DictEvent[] }

// ── 받은 알림 ─────────────────────────────────────────
export type FeedLevel = Level | 'brief'
/** 화면 한 줄. 원장 행 · 현행 발송 이력(alerts_state.json) 둘 다 이 모양으로 바꿔 그린다. */
export type FeedRow = { key: string; level: FeedLevel; title: string; why?: string; next?: string; at: number; timed: boolean; day: string; to?: string; mine: boolean }
export const FILTERS = ['all', 'alarm', 'alert', 'notice', 'brief', 'mine'] as const
export type Filter = typeof FILTERS[number]

/** 원장 행 → 화면 줄. 기록(record)은 보내지 않은 것이라 뺀다. 사용자 조건 줄(cond)은 이 기기 이름(names)이 있으면 그것을 제목으로. */
export function fromLedger(rows: unknown, names: Map<string, string>): FeedRow[] {
  if (!Array.isArray(rows)) return []
  const out: FeedRow[] = []
  for (const r of rows as LedgerRow[]) {
    const at = Date.parse(r?.ts ?? '')
    if (!r || Number.isNaN(at) || r.level === 'record' || typeof r.title !== 'string') continue
    const mine = !!r.cond || /^U\d/.test(r.event ?? '')
    out.push({
      key: r.key, level: (r.level as FeedLevel) ?? 'notice', title: (r.cond && names.get(r.cond)) || r.title,
      why: r.why || undefined, next: r.next || undefined, at, timed: true, day: kstDay(at),
      to: r.url?.startsWith('#/') ? r.url.slice(1) : undefined, mine,
    })
  }
  return out.sort((a, b) => b.at - a.at)
}

export const passes = (x: FeedRow, f: Filter) => f === 'all' || (f === 'mine' ? x.mine : x.level === f)

/** 오늘 · 어제 · 그 전(최근 7일, 새것이 위). today·yesterday = 한국 날짜 'YYYY-MM-DD'. */
export function groupDays(items: FeedRow[], today: string, yesterday: string) {
  return {
    today: items.filter(x => x.day === today),
    yesterday: items.filter(x => x.day === yesterday),
    older: items.filter(x => x.day < yesterday),
  }
}

/** 오늘 카카오로 나간 통 수(쌍당 하루 20 한도). */
export const kakaoToday = (rows: unknown, today: string) =>
  Array.isArray(rows) ? (rows as LedgerRow[]).filter(r => r?.sent?.kakao && kstDay(Date.parse(r.ts)) === today).length : 0

// ── 사건 탭 ─────────────────────────────────────────
/** 사전 사건 가운데 화면에 보일 것(사용자 사건 U · 사전에서 꺼 둔 사건 제외). */
export const listEvents = (d: Dict, family?: string) => d.events.filter(e => e.enabled && !e.userValue && (!family || e.family === family))

/** 사건 전체 조정(대상 '*'). 없으면 undefined. */
export const adjustOf = (alerts: AlertCond[], event: string) => alerts.find(a => a.event === event && a.target === '*')

/** 갈래 한 줄의 셈: 켜짐 = 처음부터 켜진 사건 · 관심 = 별표한 대상에만 울리는 사건. 사건 전체 조정으로 끈 것은 뺀다. */
export function familyCount(d: Dict, family: string, alerts: AlertCond[]) {
  let on = 0, watch = 0
  for (const e of listEvents(d, family)) {
    if (adjustOf(alerts, e.id)?.enabled === false || e.level === 'record') continue
    if (e.defaultOn.length) on++; else watch++
  }
  return { on, watch }
}

const ORDER: Level[] = ['record', 'notice', 'alert', 'alarm']
/** 등급 한 단계 조정의 고르기: 사전 기본 · 한 단계 아래 · 한 단계 위. */
export function levelChoices(base: Level): Level[] {
  const i = ORDER.indexOf(base)
  return ORDER.slice(Math.max(0, i - 1), i + 2)
}

/** 새 조건 폼의 사건: 지표 = 갈래 A·B·C 중 그 대상을 가진 것 + U1 · U2, 종목 = D5 · F1 · F2 + U1 · U2. */
export function eventsFor(d: Dict, target: string, stock: boolean): DictEvent[] {
  const user = d.events.filter(e => e.userValue)
  if (stock) return [...d.events.filter(e => e.enabled && ['D5', 'F1', 'F2'].includes(e.id)), ...user]
  const own = d.events.filter(e => e.enabled && 'ABC'.includes(e.family) && !e.userValue &&
    (e.targets.includes(target) || (e.targets.includes('lens') && e.defaultOn.includes(target))))
  return [...own, ...user]
}

// ── 세기별 「지난 1년 N회」 ─────────────────────────────
/**
 * 일봉 [날짜, 값] → 세기 3단 각각 지난 1년(끝 250거래일) 하루 등락이 문턱 이상이었던 날 수.
 * 문턱 = min(max(kσ, 0.5%), 5%) — 계약서 「세기」 정의. 점이 120개 미만이면 null(화면은 숨긴다).
 * ponytail: σ 는 같은 1년 등락의 표준편차 한 값이다(서버 check_swings 는 날마다 직전 250일로 다시 잰다). 화면은 1년치만 있어
 *   어림이다 — 서버와 맞춰야 하면 events/history 에 400점이 쌓인 뒤 날마다 굴리는 셈으로 바꾼다.
 */
export function yearCounts(series: [string, number][], sigmas: { id: string; sigma: number | null }[]): Record<string, number> | null {
  const v = series.map(p => p[1]).filter(x => typeof x === 'number' && Number.isFinite(x) && x > 0)
  if (v.length < 121) return null
  const ret = v.slice(1).map((x, i) => (x / v[i] - 1) * 100).slice(-250)
  const mean = ret.reduce((s, x) => s + x, 0) / ret.length
  const sd = Math.sqrt(ret.reduce((s, x) => s + (x - mean) ** 2, 0) / (ret.length - 1))
  const out: Record<string, number> = {}
  for (const s of sigmas) {
    if (s.sigma == null) continue
    const thr = Math.min(Math.max(s.sigma * sd, 0.5), 5)
    out[s.id] = ret.filter(x => Math.abs(x) >= thr).length
  }
  return out
}
