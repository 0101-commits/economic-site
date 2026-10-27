// 지금 이 기기를 쓰는 사람 — account.ts 가 남기는 econMe_v1 을 읽기만 한다(순환 import 를 피하려고 따로 둔 얇은 층).
// 사람마다 기기 저장 이름이 갈린다: 마스터(owner) · 로그아웃 상태는 옛 이름 그대로(옛 화면이 직접 읽는다), 멤버는 이름 + ':' + uid.
const ME_KEY = 'econMe_v1'

export type ScopedBase = 'portfolioV1' | 'pfSnapshotsV1' | 'pfLedgerV1' | 'econ_watch_v1' | 'econPrefsV1' | 'econ_scenarios_v1'

type Person = { uid: string; role: 'owner' | 'member' }

// 들어오는 중인 사람(account.signIn) — econMe_v1 을 쓰기 전에도 연결(connectSync)이 이 사람의 이름으로 읽고 쓰게 한다. 같은 모듈 상태라 1초 감시도 본다.
let pending: Person | null = null
export const setPendingPerson = (p: Person | null): void => { pending = p }

/** 지금 사람 — 들어오는 중인 사람 > 저장된 사람 > 없음(null). */
export function currentPerson(): Person | null {
  if (pending) return pending
  try {
    const j = JSON.parse(localStorage.getItem(ME_KEY) || 'null')
    if (!j || typeof j.uid !== 'string' || !j.uid || (j.role !== 'owner' && j.role !== 'member')) return null
    return { uid: j.uid, role: j.role }
  } catch { return null }
}

/** 이 사람의 기기 저장 이름. owner · 없음 = base 그대로, member = base:uid. */
export function storeKey(base: ScopedBase): string {
  const p = currentPerson()
  return p && p.role === 'member' ? `${base}:${p.uid}` : base
}
