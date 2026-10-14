// 묶음 다시 읽기 · 첫 화면 보관 · 새 판 · 매매중단 배너 — 순수 함수만(화면 · 저장소 · fetch 없음).
// 부르는 길은 bundle.ts(watchBundles · 첫 화면 보관 · 새 판 확인)와 App.tsx 배너.
// 자가검사: npm test --prefix app (refresh.test.ts)
import type { Market, Session } from './format'

export const POLL_MS = 5 * 60_000    // 장중 다시 읽기 간격(meta 에 nextAt 이 없거나 이미 지났을 때)
export const AWAY_MS = 30 * 60_000   // nextAt 이 없는 옛 meta: 탭을 이보다 오래 숨겼다 돌아오면 장과 상관없이 다시 읽는다
export const LAG_MS = 30_000         // nextAt(다음 묶음이 사이트에 올라올 때) 뒤 이만큼 있다가 읽는다
export const GRACE_MS = 10 * 60_000  // 마감 뒤 이만큼은 장중으로 본다 — 국내 15:30 마감 직후 15:35 종가 묶음까지 받게
export const TICK_MS = 60_000        // 다시 볼 때까지 가장 오래 기다리는 길이(장 시작 · 5분 규칙을 놓치지 않게)

const WD_HM = (tz: string) => new Intl.DateTimeFormat('en-US', { timeZone: tz, weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const SEOUL = WD_HM('Asia/Seoul'), NEW_YORK = WD_HM('America/New_York')
/** 그 시간대의 (평일인가, 0시부터 분). 서머타임은 Intl 이 맞춘다. */
function local(f: Intl.DateTimeFormat, t: Date): [boolean, number] {
  const p = Object.fromEntries(f.formatToParts(t).map(x => [x.type, x.value]))
  return [p.weekday !== 'Sat' && p.weekday !== 'Sun', +p.hour * 60 + +p.minute]
}

/** 묶음 개장 · 마감 칸으로 본 장중(마감 뒤 GRACE_MS 까지). 칸이 null 이면(장이 안 서는 날) false. */
function within(s: Session, t: number): boolean {
  const o = s.openAt ? Date.parse(s.openAt) : NaN, c = s.closeAt ? Date.parse(s.closeAt) : NaN
  return o <= t && t < c + GRACE_MS
}

/**
 * 장중인가: 한국 정규장 또는 미국 정규장.
 * 묶음 market 이 있으면 그 칸으로 판정한다 — 국내 openAt · closeAt(칸이 있고 null 이면 휴장일), 미국 market.us 의 openAt · closeAt
 * (시각 칸이 없으면 state)에 마감 뒤 10분을 더해서. 없을 때만(옛 묶음 · 아직 못 받음) 시계로: 평일 09:00~15:30 KST · 뉴욕 09:30~16:00
 * — 시계 판정은 휴장일(설 · 추석 · 미국 공휴일)을 모른다.
 */
export function inSession(t: Date, m?: Market | null): boolean {
  const ms = t.getTime()
  const [krDay, kr] = local(SEOUL, t), [usDay, us] = local(NEW_YORK, t)
  const krOn = m && 'closeAt' in m ? within(m, ms) : krDay && kr >= 9 * 60 && kr < 15 * 60 + 30
  const u = m?.us
  const usOn = u ? ('closeAt' in u ? within(u, ms) : u.state === 'open') : usDay && us >= 9 * 60 + 30 && us < 16 * 60
  return krOn || usOn
}

/** 다시 읽기 판정에 넘기는 것: nextAt = meta.nextAt, market = 묶음 market, hiddenFor = 탭으로 돌아온 순간 숨어 있던 길이. */
export type Due = { nextAt?: string | null; market?: Market | null; hiddenFor?: number }
const readAt = (nextAt: string | null | undefined) => (nextAt ? Date.parse(nextAt) + LAG_MS : NaN)

/**
 * 지금 meta 를 다시 읽을지. now · last(마지막으로 읽은 때) = ms.
 * - nextAt + 30초가 마지막으로 읽은 뒤면 → 그 시각이 되면 읽는다(숨었다 돌아왔을 때도 지났으면 곧바로).
 * - 그 시각에 읽었는데 새 묶음이 안 왔으면(nextAt 이 그대로 지남) → 5분마다(장과 상관없이 — 나올 묶음이 늦을 뿐이다).
 * - nextAt 이 없는 옛 meta → 종전대로: 장중 5분, 탭 복귀는 30분 넘게 숨었을 때 장과 상관없이.
 */
export function reloadDue(now: number, last: number, o: Due = {}): boolean {
  const at = readAt(o.nextAt)
  if (Number.isFinite(at)) return at > last ? now >= at : now - last >= POLL_MS
  if (o.hiddenFor != null && o.hiddenFor > AWAY_MS) return true
  return now - last >= POLL_MS && inSession(new Date(now), o.market)
}

/** 다음 판정까지 기다릴 길이(ms): nextAt + 30초가 1분 안이면 딱 그때, 아니면 1분 뒤 다시 본다. */
export function waitMs(now: number, nextAt: string | null | undefined): number {
  const at = readAt(nextAt)
  return at > now ? Math.min(at - now, TICK_MS) : TICK_MS
}

/** 바꿔 받을 묶음: 기억하는 이름 중 지문(meta.hashes)이 그대로인 것을 뺀다. 어느 쪽이든 지문이 없으면 전부. */
export function changedBundles(names: string[], old: Record<string, string> | null | undefined, cur: Record<string, string> | null | undefined): string[] {
  return names.filter(n => !(old?.[n] && cur?.[n] && old[n] === cur[n]))
}

// ── 첫 화면(과제 11) ───────────────────────────────
export const HOME_CACHE_KEY = 'econ_home_cache_v1'
export const HOME_CACHE_MS = 24 * 3600_000
/** 보관한 홈 한 벌: at = 넣은 때(ms), home = 홈 묶음, dataUpdated = 그때 meta.dataUpdated(값 시각). */
export type HomeCache<H> = { at: number; home: H; dataUpdated?: string | null; build?: string }

/**
 * 보관 글(localStorage 값) → 쓸 수 있는 홈 한 벌, 못 쓰면 null.
 * 값 시각(dataUpdated, 없으면 홈 asOf, 그것도 없으면 넣은 때)이 24시간을 넘었거나 · 깨졌거나 · 띠가 비었으면 쓰지 않는다.
 */
export function homeCacheFrom<H extends { asOf?: string; strip?: unknown }>(raw: string | null, now: number, build?: string): HomeCache<H> | null {
  try {
    const c = JSON.parse(raw ?? 'null') as HomeCache<H> | null
    if (!c || typeof c !== 'object' || !c.home || !Array.isArray(c.home.strip) || !c.home.strip.length) return null
    if (build && c.build && c.build !== build) return null   // 다른 판이 둔 값 — 묶음 모양이 바뀌었을 수 있다(PR #170 검토)
    const t = [c.dataUpdated, c.home.asOf].map(x => (typeof x === 'string' ? Date.parse(x) : NaN)).find(Number.isFinite) ?? c.at
    return typeof t === 'number' && now - t < HOME_CACHE_MS ? c : null
  } catch { return null }
}

// ── 새 판(과제 9) ─────────────────────────────────
/** 판 이름 = 진입 JS 파일 이름(내용 지문이 들어 있다). 화면은 자기 진입 모듈 주소(main.tsx import.meta.url), vite.config 는 dist/version.json 에 같은 값을 쓴다. */
export const buildOf = (url: string): string => {
  try { return decodeURIComponent(new URL(url).pathname.split('/').pop() || '') } catch { return '' }
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
