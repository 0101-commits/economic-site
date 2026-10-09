// 알림 설정 v2 — 모양 정리 · v1 변환 · 꾸러미 전환. 순수 함수만(node --test, prefsV2.test.ts).
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(calc.ts 와 같은 규칙).
//
// v1 → v2 규칙은 서버 scripts/alerts_v2/subscribe.py upgrade_prefs 와 같다(같은 입력 → 같은 alerts · settings):
//   price→U1(dir = op '<=' 면 down) · pct→U2(value = |값|, dir = 부호) · high52→B1(dir = side low 면 down) · event→E1
//   flow→D2(코스피) / D5(그 밖 대상) · lens→C1. 모르는 type 은 버린다. repeat daily→each.
//   ring = channels 에 push 나 discord 가 있으면 참(channels 가 비면 push 로 본다). cond.armedAt → armedAt.
//   settings 는 서버 기본값(model.DEFAULT_SETTINGS) 위에 덮는다 — v1 문서의 quiet:null 은 서버처럼 기본 23:00~07:00 이 된다.
//   v2 문서(package 가 있는 설정)의 quiet:null 은 「조용한 시간 끔」 그대로 둔다.
import type { AlertCond, Pkg, Prefs, Settings } from './store'

export const FAMILIES = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'] as const
const PKGS = ['quiet', 'normal', 'many']
const BRIEF_KEYS = ['morning', 'close', 'noon', 'evening', 'us', 'weekly'] as const
const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/
const V1_EVENT: Record<string, string> = { price: 'U1', pct: 'U2', high52: 'B1', event: 'E1', flow: 'D2', lens: 'C1' }

const brief = (on: string[]) => Object.fromEntries(BRIEF_KEYS.map(k => [k, on.includes(k)])) as Settings['briefings']
/** 꾸러미 = 하루 울림 상한 + 브리핑 묶음(기획서 7장 표). 바꾸면 이 둘을 같이 바꾸고, 사건별 조정은 그대로 둔다. */
export const PACKAGE_PRESET: Record<Pkg, { cap: number; briefings: Settings['briefings'] }> = {
  quiet: { cap: 3, briefings: brief(['morning']) },
  normal: { cap: 6, briefings: brief(['morning', 'close', 'weekly']) },
  many: { cap: 12, briefings: brief([...BRIEF_KEYS]) },
}

export function defaultSettings(): Settings {
  return {
    updown: 'kr', unit: 'man', quiet: { from: '23:00', to: '07:00' },
    package: 'normal', ringChannel: 'push', dailyCap: 6, quietAlarm: false,
    briefings: { ...PACKAGE_PRESET.normal.briefings },
    families: Object.fromEntries(FAMILIES.map(f => [f, true])) as Settings['families'],
    rememberKey: false, kakaoFriends: false, kakaoRecipients: [], autoQuiet: true,
  }
}

const isObj = (v: unknown): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v)
const arr = (v: unknown): any[] => (Array.isArray(v) ? v : [])

/** 설정 한 벌을 아는 값만으로. 모르는 값은 기본값. */
export function normSettings(raw: unknown): Settings {
  const d = defaultSettings()
  const s = isObj(raw) ? raw : {}
  const q = s.quiet
  const v2 = 'package' in s
  return {
    updown: s.updown === 'us' ? 'us' : 'kr',
    unit: s.unit === 'won' ? 'won' : 'man',
    quiet: isObj(q) && HHMM.test(q.from) && HHMM.test(q.to) ? { from: q.from, to: q.to } : q === null && v2 ? null : d.quiet,
    package: PKGS.includes(s.package) ? s.package : 'normal',
    ringChannel: s.ringChannel === 'kakao' || s.ringChannel === 'both' ? s.ringChannel : 'push',
    dailyCap: Number.isInteger(s.dailyCap) && s.dailyCap > 0 && s.dailyCap <= 50 ? s.dailyCap : d.dailyCap,
    quietAlarm: s.quietAlarm === true,
    briefings: brief(BRIEF_KEYS.filter(k => (isObj(s.briefings) && typeof s.briefings[k] === 'boolean' ? s.briefings[k] : d.briefings[k]))),
    families: Object.fromEntries(FAMILIES.map(f => [f, !(isObj(s.families) && s.families[f] === false)])) as Settings['families'],
    rememberKey: s.rememberKey === true,
    kakaoFriends: s.kakaoFriends === true,
    kakaoRecipients: arr(s.kakaoRecipients).filter(r => isObj(r) && typeof r.name === 'string').slice(0, 5)
      .map(r => ({ uuid: typeof r.uuid === 'string' ? r.uuid : '', name: r.name.slice(0, 20), briefOnly: r.briefOnly === true })),
    autoQuiet: s.autoQuiet !== false,
  }
}

/** 조건 한 건: v2(event 있음)는 그대로, v1(type)은 사전 사건으로. 바꿀 수 없으면 null. */
export function upgradeAlert(raw: unknown): AlertCond | null {
  if (!isObj(raw)) return null
  if (raw.event) return raw as AlertCond
  const ev = V1_EVENT[raw.type]
  if (!ev) return null
  const { type: _t, cond: c0, channels, ...rest } = raw
  const cond = isObj(c0) ? c0 : {}
  const ch = arr(channels).length ? arr(channels) : ['push']
  const a: Record<string, any> = { ...rest, event: ev, repeat: rest.repeat === 'once' ? 'once' : 'each', ring: ch.includes('push') || ch.includes('discord') }
  if (ev === 'U1') { a.dir = cond.op === '<=' ? 'down' : 'up'; a.value = cond.value }
  else if (ev === 'U2') { const v = Number(cond.value || 0); a.value = Math.abs(v); a.dir = v < 0 ? 'down' : 'up' }
  else if (ev === 'B1') a.dir = cond.side === 'low' ? 'down' : 'up'
  else if (ev === 'D2' && a.target && a.target !== 'kospi') a.event = 'D5'
  if (cond.armedAt) a.armedAt = cond.armedAt
  return a as AlertCond
}

/** 저장 문서(v1 · v2 · 서버 문서) → v2. */
export function upgradePrefs(doc: unknown): Prefs {
  const d = isObj(doc) ? doc : {}
  return {
    v: 2,
    alerts: arr(d.alerts).map(upgradeAlert).filter((a): a is AlertCond => a != null),
    settings: normSettings(d.settings),
    scenarios: arr(d.scenarios),
  }
}

/** 꾸러미 전환: 상한 · 브리핑을 그 꾸러미 값으로. 사건별 조정(alerts)은 건드리지 않는다. */
export function setPackage(s: Settings, pkg: Pkg): Settings {
  const p = PACKAGE_PRESET[pkg]
  return { ...s, package: pkg, dailyCap: p.cap, briefings: { ...p.briefings } }
}
