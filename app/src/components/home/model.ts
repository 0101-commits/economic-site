// 홈 AI 요약(Brief.tsx)의 순수 계산 — 문장 · 근거 번호 · 근거 목록 · 대조 한 줄 · 회차(briefs/<day>.json). 계약 C3.
// 묶음 home.brief 에 items 가 없으면(옛 묶음) 화면은 lines 만 그린다 — 여기 함수는 그때 null · 빈 목록을 준다.
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다. node --test 로 바로 돌린다(model.test.ts).
import { mdHm, safeHref } from '../../lib/format.ts'

/** 문장 하나 + 끝에 붙는 근거 번호. */
export type BriefItem = { text: string; refs: number[] }
/** 근거 한 줄: 번호 · 종류(지표 · 수급 · 기사 · 일정) · 글 · 출처 · 시각. url 은 http(s) 만(아니면 null — 글자만). */
export type BriefSource = { n: number; kind: string; label: string; src?: string; url: string | null; at?: string }
/** 회차 하나(briefs/<day>.json runs[] 한 칸 · 지금 묶음 brief). at = 작성 시각 HH:MM. */
export type BriefRun = { at: string; lines: string[]; source?: string; items?: unknown; sources?: unknown; dropped?: unknown; check?: unknown }

const nat = (v: unknown): number | null => (typeof v === 'number' && Number.isInteger(v) && v >= 0 ? v : null)
const REF_TAIL = /\s*\[(\d+)\]\s*$/

/** 문장 끝의 [1][2] 를 떼어 refs 에 더한다(묶음이 이미 뗐으면 그대로). 번호는 작은 순, 겹침 없음. */
export function splitRefs(text: string, refs: unknown): BriefItem {
  const got = new Set((Array.isArray(refs) ? refs : []).map(nat).filter((n): n is number => n != null && n > 0))
  let t = text, m: RegExpExecArray | null
  while ((m = REF_TAIL.exec(t))) { got.add(+m[1]); t = t.slice(0, m.index) }
  return { text: t.trim(), refs: [...got].sort((a, b) => a - b) }
}

/** 문장 목록. items 가 없거나 비었으면 null(화면은 lines 만). 글이 빈 문장은 뺀다. */
export function briefItems(b: { items?: unknown } | null | undefined): BriefItem[] | null {
  if (!Array.isArray(b?.items)) return null
  const out = (b!.items as unknown[]).flatMap((x): BriefItem[] => {
    const r = x as { text?: unknown; refs?: unknown } | null
    if (typeof r?.text !== 'string') return []
    const it = splitRefs(r.text, r.refs)
    return it.text ? [it] : []
  })
  return out.length ? out : null
}

/** 근거 목록(번호 순). 번호 · 글이 없는 칸은 뺀다. */
export function briefSources(b: { sources?: unknown } | null | undefined): BriefSource[] {
  if (!Array.isArray(b?.sources)) return []
  return (b!.sources as unknown[]).flatMap((x): BriefSource[] => {
    const r = x as Record<string, unknown> | null
    const n = nat(r?.n)
    if (!r || !n || typeof r.label !== 'string' || !r.label) return []
    return [{
      n, kind: typeof r.kind === 'string' ? r.kind : '', label: r.label, url: safeHref(r.url),
      ...(typeof r.src === 'string' && r.src ? { src: r.src } : {}), ...(typeof r.at === 'string' && r.at ? { at: r.at } : {}),
    }]
  }).sort((a, b) => a.n - b.n)
}

/** 대조 한 줄: 「대조 통과 — 숫자 3 · 일정 1 · 근거 없는 문장 1 뺌」. 대조 칸이 없으면(규칙 요약 · 옛 묶음) null. 없는 셈은 적지 않는다. */
export function checkLine(b: { check?: unknown; dropped?: unknown } | null | undefined): string | null {
  const c = (b?.check ?? null) as { numbers?: unknown; schedule?: unknown } | null
  const parts = [
    nat(c?.numbers) != null ? `숫자 ${c!.numbers}` : '',
    nat(c?.schedule) != null ? `일정 ${c!.schedule}` : '',
    (nat(b?.dropped) ?? 0) > 0 ? `근거 없는 문장 ${b!.dropped} 뺌` : '',   // 0 이면 적지 않는다
  ].filter(Boolean)
  return parts.length ? `대조 통과 — ${parts.join(' · ')}` : null
}

/** 작성 시각(ISO) → 「HH:MM」. 못 읽으면 ''. */
export const runAt = (asOf: string | null | undefined) => (asOf ? mdHm(asOf).split(' ')[1] ?? '' : '')

/**
 * 회차 목록(시각 순): 그날 파일(briefs/<day>.json)의 runs + 지금 묶음 brief. 같은 시각이면 묶음 것(더 새로 읽은 것)이 이긴다.
 * 파일 날짜가 brief 의 날(day)과 다르거나 파일이 없으면 지금 것 하나. cur = 지금 묶음 brief 의 자리.
 */
export function briefRuns(file: unknown, cur: { asOf?: string | null; day?: string } & Omit<BriefRun, 'at'>): { runs: BriefRun[]; cur: number } {
  const at = runAt(cur.asOf)
  const f = file as { date?: unknown; runs?: unknown } | null
  const same = !!at && !!cur.day && f?.date === cur.day && Array.isArray(f?.runs)
  const others = same ? (f!.runs as unknown[]).filter((r): r is BriefRun => {
    const x = r as Partial<BriefRun> | null
    return !!x && typeof x.at === 'string' && /^\d{2}:\d{2}$/.test(x.at) && x.at !== at && Array.isArray(x.lines)
  }) : []
  const { asOf: _a, day: _d, ...rest } = cur
  const runs = [...others, { ...rest, at }].sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0))
  return { runs, cur: runs.findIndex(r => r.at === at) }
}
