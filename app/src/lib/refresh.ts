// 묶음 다시 읽기 · 매매중단 배너 — 순수 함수만(화면 · 저장소 · fetch 없음). 부르는 길은 bundle.ts watchBundles 와 App.tsx 배너.
// 자가검사: npm test --prefix app (refresh.test.ts)

export const POLL_MS = 5 * 60_000    // 장중 다시 읽기 간격
export const AWAY_MS = 30 * 60_000   // 탭을 이보다 오래 숨겼다 돌아오면 장과 상관없이 다시 읽는다

const WD_HM = (tz: string) => new Intl.DateTimeFormat('en-US', { timeZone: tz, weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const SEOUL = WD_HM('Asia/Seoul'), NEW_YORK = WD_HM('America/New_York')
/** 그 시간대의 (평일인가, 0시부터 분). 서머타임은 Intl 이 맞춘다. */
function local(f: Intl.DateTimeFormat, t: Date): [boolean, number] {
  const p = Object.fromEntries(f.formatToParts(t).map(x => [x.type, x.value]))
  return [p.weekday !== 'Sat' && p.weekday !== 'Sun', +p.hour * 60 + +p.minute]
}

/**
 * 장중인가: 한국 정규장(평일 09:00~15:30 KST) 또는 미국 정규장(평일 뉴욕 09:30~16:00).
 * ponytail: 휴장일(설 · 추석 · 미국 공휴일)은 모른다 — 그날은 묶음이 새로 안 나와 meta 만 5분마다 받고(1KB) 화면은 그대로다.
 */
export function inSession(t: Date): boolean {
  const [krDay, kr] = local(SEOUL, t), [usDay, us] = local(NEW_YORK, t)
  return (krDay && kr >= 9 * 60 && kr < 15 * 60 + 30) || (usDay && us >= 9 * 60 + 30 && us < 16 * 60)
}

/**
 * 지금 묶음을 다시 읽을지. now · last(마지막으로 읽은 때) = ms.
 * hiddenFor = 탭이 숨어 있던 길이 — 탭으로 돌아온 순간에만 넘긴다(그때는 장과 상관없이 30분 넘게 숨었는지만 본다).
 */
export function reloadDue(now: number, last: number, hiddenFor?: number): boolean {
  if (hiddenFor != null) return hiddenFor > AWAY_MS
  return now - last >= POLL_MS && inSession(new Date(now))
}

/** 국내 묶음 매매중단 한 건(views.halts.active · recent). */
export type Halt = { id?: string; type: string; market?: string; stage?: number | null; reason?: string; triggeredAt?: string | null; resumeAt?: string | null; endOfDay?: boolean; resolvedAt?: string | null }

const KIND: Record<string, string> = { circuit: '서킷브레이커', sidecar: '사이드카' }
const MARKET: Record<string, string> = { KOSPI: '코스피', KOSDAQ: '코스닥' }
const KST_DAY = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul' })
const KST_HM = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })

/**
 * 머리 아래 배너 한 줄 — 지금 발동 중인 서킷브레이커 · 사이드카. 없으면 null.
 * 묶음의 active 는 묶음을 만든 순간 기준이라 늦게 읽으면 이미 풀린 것이 남는다 → 오늘(KST) 발동했고, 풀린 기록이 없고,
 * 재개 시각이 아직 안 왔거나(그날 거래 종료면 하루 내내) 재개 시각이 없는 것만.
 */
export function haltLine(active: Halt[] | null | undefined, now: number): string | null {
  const today = KST_DAY.format(now)
  const on = (active || []).filter(h => {
    const t = h.triggeredAt ? Date.parse(h.triggeredAt) : NaN
    if (Number.isNaN(t) || KST_DAY.format(t) !== today || h.resolvedAt) return false
    return h.endOfDay || !h.resumeAt || Date.parse(h.resumeAt) > now
  })
  if (!on.length) return null
  return on.map(h => {
    const name = `${MARKET[h.market ?? ''] ?? h.market ?? ''} ${KIND[h.type] ?? h.type}${h.stage ? ` ${h.stage}단계` : ''}`.trim()
    const tail = h.endOfDay ? '오늘 거래 끝' : h.resumeAt ? `${KST_HM.format(Date.parse(h.resumeAt))} 재개` : ''
    return `${name} 발동 중${tail ? ` · ${tail}` : ''}`
  }).join(' · ')
}
