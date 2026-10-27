// 알림 화면 v2 의 순수 계산 — 받은 알림 묶기 · 거르기, 사건 탭 셈, 세기별 「지난 1년 N회」. node --test(v2.test.ts).
// 이름 · 라벨은 사전(dict.json, scripts/alerts_v2/export_dict.py 산출)에서만 — 이 파일은 사전을 인자로 받는다.
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다.
import { mdHm } from '../format.ts'
import { kstDay } from '../personal/calc.ts'
import type { FiredRec, LedgerRow } from '../personal/alertStatus.ts'
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

// ── 멤버의 받은 알림 ─────────────────────────────────────
// 공개 원장(events/latest.json)의 사용자 조건 행 · 상한 묶음은 마스터 것이다(멤버 행은 공개 원장에 쓰지 않는다 — scripts/alerts_v2/run.py).
// 멤버 자기 조건의 울림은 그 사람 칸 GET /fired(Worker fired:<uid>, scripts/alerts_v2/deliver.fired_item — 원장 행과 같은 이름)에만 있다.

/** 공개 원장 행이 사람(마스터) 것인가 — 사용자 조건(cond · U*) · 상한 묶음(BUNDLE). 서버 짝 = scripts/alerts_v2/briefing._personal. */
export const personalRow = (r: { cond?: unknown; event?: unknown } | null | undefined): boolean =>
  !!r && (!!r.cond || /^U/.test(String(r.event ?? '')) || r.event === 'BUNDLE')

/** 멤버가 보는 공개 원장 — 사람 것을 뺀 시장 사건만. 배열이 아니면 그대로(없음 · 불러오는 중). */
export const publicLedger = (rows: unknown): unknown => (Array.isArray(rows) ? rows.filter(r => !personalRow(r)) : rows)

/** /fired 한 건 → 원장 행 모양(sent 는 보류 · 묶임만). 시각 · 제목 · 조건 id 가 없으면 null. */
export function firedRow(x: unknown, i = 0): LedgerRow | null {
  const o = (x && typeof x === 'object' ? x : {}) as Record<string, unknown>
  const s = (k: string) => (typeof o[k] === 'string' ? (o[k] as string) : '')
  if (!s('cond') || !s('title') || Number.isNaN(Date.parse(s('ts')))) return null
  return {
    key: s('id') || `fired:${i}`, event: s('event') || 'U1', target: '', dir: s('dir') || undefined, level: s('level') || 'alert',
    title: s('title'), why: s('why') || undefined, url: s('url') || undefined, ts: s('ts'), cond: s('cond'),
    sent: { held: o.held === true, bundled: o.bundled === true },
  }
}

/**
 * 멤버 화면 재료. rows = 「받은 알림」(공개 원장의 시장 사건 + 내 울림 가운데 from 날짜 이후) · mine = 내 울림 전부(조건 상태 · 다시 켜기) ·
 * fired = 조건 id → 마지막 울림(공개 기록 alerts_state._prefs 대신 — 멤버 공개 기록 키는 HMAC 이라 화면이 못 찾는다).
 * 내 울림 줄은 cond 가 있어 fromLedger 가 「내 조건」으로 표시한다.
 */
export function memberView(ledger: unknown, items: unknown, from = ''): { rows: LedgerRow[]; mine: LedgerRow[]; fired: Record<string, FiredRec> } {
  const mine = (Array.isArray(items) ? items : []).map(firedRow).filter((r): r is LedgerRow => !!r)
  const fired: Record<string, FiredRec> = {}
  for (const r of mine) {
    const ts = Math.floor(Date.parse(r.ts) / 1000)
    if (ts > (fired[r.cond!]?.ts ?? 0)) fired[r.cond!] = { ts, fired: true }
  }
  const pub = Array.isArray(ledger) ? (ledger as LedgerRow[]).filter(r => !personalRow(r)) : []
  return { rows: [...pub, ...mine.filter(r => kstDay(Date.parse(r.ts)) >= from)], mine, fired }
}

/** 오른쪽 패널 「받은 알림」 줄 — 마스터 = 공개 원장 그대로, 멤버 = memberView(시장 사건 + 내 울림). 최근 limit 건. */
export function railFeed(ledger: unknown, firedItems: unknown, member: boolean, from: string, limit = 20): FeedRow[] {
  return fromLedger(member ? memberView(ledger, firedItems, from).rows : ledger, new Map()).slice(0, limit)
}

/** 한국 시각 HH:mm. */
export const hhmm = (t: number) => mdHm(new Date(t)).split(' ')[1] ?? ''

export const passes = (x: FeedRow, f: Filter) => f === 'all' || (f === 'mine' ? x.mine : x.level === f)

/** 오늘 · 어제 · 그 전(최근 7일, 새것이 위). today·yesterday = 한국 날짜 'YYYY-MM-DD'. */
export function groupDays(items: FeedRow[], today: string, yesterday: string) {
  return {
    today: items.filter(x => x.day === today),
    yesterday: items.filter(x => x.day === yesterday),
    older: items.filter(x => x.day < yesterday),
  }
}

/** 홈 「오늘 바뀐 것」: 오늘(한국 날짜) 원장 행 가운데 새것 순 limit 건 + 오늘 전체 건수. 기록(record)은 빼고 안내(notice)는 넣는다. */
export function todayRows(rows: unknown, today: string, limit = 5): { rows: FeedRow[]; total: number } {
  const all = fromLedger(rows, new Map()).filter(x => x.day === today)
  return { rows: all.slice(0, limit), total: all.length }
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

/** 새 조건 폼의 사건: 지표 = 갈래 A·B·C 중 그 대상을 가진 것 + U1 · U2, 국내 종목 = D5 · F1 · F2 + U1 · U2, 미국 종목 = U1 · U2(수급 · 공시 · 거래소 경보는 국내 자료뿐). */
export function eventsFor(d: Dict, target: string, stock: boolean): DictEvent[] {
  const user = d.events.filter(e => e.userValue)
  if (stock) return [...(/^\d[0-9A-Z]{5}$/.test(target) ? d.events.filter(e => e.enabled && ['D5', 'F1', 'F2'].includes(e.id)) : []), ...user]
  const own = d.events.filter(e => e.enabled && 'ABC'.includes(e.family) && !e.userValue &&
    (e.targets.includes(target) || (e.targets.includes('lens') && e.defaultOn.includes(target))))
  return [...own, ...user]
}

/** Worker _sanitizePrefs 가 한 문서에 받는 조건 수. 넘치면 서버가 뒤를 버린다. */
export const ALERT_CAP = 100

const SHEET = ['A1', 'A2', 'A3', 'B1', 'B2', 'C1', 'C2', 'C7', 'D5', 'F1', 'F2', 'U1', 'U2']
/**
 * 상세 벨 시트의 사건 — eventsFor 에서 시트가 다루는 것만(지표 = A1~A3 · B1 · B2 · C1 · C2 · C7 · U1 · U2 중 그 대상이 가진 것,
 * 종목 = D5 · F1 · F2 · U1 · U2). 렌즈 사건 C1 · C2 는 그 지표가 렌즈 묶음에 들었을 때만(lens = 렌즈 지표 id 모음 — 모르면 빈 모음).
 */
export function sheetEvents(d: Dict, target: string, stock: boolean, lens: ReadonlySet<string>): DictEvent[] {
  const lensIds = ['C1', 'C2']
  const base = eventsFor(d, target, stock).filter(e => SHEET.includes(e.id) && !lensIds.includes(e.id))
  const extra = !stock && lens.has(target) ? d.events.filter(e => e.enabled && lensIds.includes(e.id)) : []
  const at = new Map(d.events.map((e, i) => [e.id, i]))
  return [...base, ...extra].sort((a, b) => at.get(a.id)! - at.get(b.id)!)
}

/** 조건을 저장한 직후의 한 줄(head = 첫머리 말): 동기화가 꺼져 있으면 「이 기기에만」, 켜져 있으면 서버에 올라갔는지. savedAt 0 = 아직 저장하지 않음(빈 글). */
export function savedNote(sync: { on: boolean; at: number | null }, savedAt: number, head = '저장했습니다'): string {
  if (!savedAt) return ''
  if (!sync.on) return `${head} · 이 기기만 — 울리지 않음(설정 › 내 계정에서 연결을 켜야 서버가 봅니다)`
  return sync.at && sync.at >= savedAt ? `${head} · 서버에 올라감 ${hhmm(sync.at)}` : `${head} · 서버로 올리는 중`
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
