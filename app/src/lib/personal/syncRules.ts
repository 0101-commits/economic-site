// 「어느 쪽을 남길까」 규칙 하나 — 설정(관심 · 알림 조건 · 설정 · 시나리오, sync.ts)과 보유(holdSync.ts)가 같이 쓴다. 사람에게 묻지 않는다.
// 저장소·화면·네트워크를 만지지 않는다 — node --test 로 바로 돈다(syncRules.test.ts).
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(calc.ts 와 같은 규칙).
//
// 규칙(차례대로 처음 맞는 줄)
//   1 서버에 없음           기기에 있으면 올림, 없으면 할 일 없음
//   2 내용이 같음           할 일 없음(맞춘 기록만 새로)
//   3 맞춘 기록 없음        서버 것으로(새 입장 · 기록 없는 기기). 기기에 다른 것이 있었으면 한 벌 남긴다(keep device)
//   4 기기가 비었는데 지운 기록 없음   받기 — 저장소가 비워진 것을 「다 지움」으로 올려 서버 판을 지우지 않는다
//   5 기기만 바뀜 → 올림 · 서버만 바뀜 → 받기 · 둘 다 안 바뀜 → 할 일 없음
//   6 둘 다 바뀜            나중에 바뀐 쪽이 이긴다. 진 쪽은 이 기기에 한 벌(keep) — 서버 쪽 진 판은 Worker 의 날짜별 이전 판에도 남는다.
//                           시각이 같거나 기기 쪽 시각을 모르면 서버(올리지 않는 쪽 — 옛 판으로 새 판을 덮지 않는다).
// 바뀐 시각: 설정은 서버 문서의 updatedAt(Worker 가 저장한 때) ↔ 이 기기에서 바꾼 때(econPrefsSync_v1.editAt),
//           보유는 암호문 안의 t(그 판을 바꾼 때) ↔ 이 기기에서 바꾼 때(econHoldSync_v1.editAt).
import { blankLocal, fromServer, toServer, type Local, type PrefsDoc } from './remote.ts'

export type SettleIn = {
  serverHas: boolean; localHas: boolean; same: boolean
  known: boolean                                    // 이 기기에 「마지막으로 같았던 때」 기록이 있다
  localChanged: boolean; serverChanged: boolean     // 그 기록 뒤로 바뀌었나(known 일 때만 뜻이 있다)
  localEdited: boolean                              // 이 기기에서 사람이 바꾼 기록이 있다(아직 못 올린 것)
  localAt: number; serverAt: number                 // 바뀐 시각 ms(모르면 0)
}
export type Step = { act: 'push' | 'pull' | 'none'; keep: 'device' | 'server' | null }

export function settle(x: SettleIn): Step {
  if (!x.serverHas) return { act: x.localHas ? 'push' : 'none', keep: null }
  if (x.same) return { act: 'none', keep: null }
  if (!x.known) return { act: 'pull', keep: x.localHas ? 'device' : null }
  if (!x.localHas && !x.localEdited) return { act: 'pull', keep: null }
  if (!x.localChanged) return { act: x.serverChanged ? 'pull' : 'none', keep: null }
  if (!x.serverChanged) return { act: 'push', keep: null }
  return x.localAt > x.serverAt ? { act: 'push', keep: 'server' } : { act: 'pull', keep: 'device' }
}

/** 키 순서와 무관한 비교용 글(서버가 조건 칸 순서를 바꿔 돌려준다). */
export const canon = (v: unknown) => JSON.stringify(v, (_k, x) => (x && typeof x === 'object' && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : 1))) : x))

/**
 * 설정 맞춘 기록(econPrefsSync_v1 — 사람별). 값은 없고 지문 · 시각만.
 *   base   마지막으로 서버와 같았을 때 이 기기 문서의 지문(sync.ts fp — 이 기기 모양 그대로라 서버가 다듬은 차이에 흔들리지 않는다)
 *   srvAt  그때 서버 문서의 updatedAt(서버가 그 뒤 바뀌었는지는 이것과 견준다)
 *   editAt 그 뒤 이 기기에서 바꾼 마지막 때(올리면 지운다)
 */
export type PrefsRec = { base?: string; srvAt?: string | null; editAt?: string }

/** 설정: 기록 · 이 기기 문서(local, 지문 localFp) · 서버 문서 → 할 일. */
export function prefsStep(rec: PrefsRec, local: Local, localFp: string, doc: PrefsDoc): Step {
  const known = typeof rec.base === 'string'
  return settle({
    serverHas: !!doc.updatedAt,
    localHas: !blankLocal(local),
    same: canon(toServer(local, null, '')) === canon(toServer(fromServer(doc), null, '')),
    known,
    localChanged: known && localFp !== rec.base,
    serverChanged: known && (doc.updatedAt ?? null) !== (rec.srvAt ?? null),
    localEdited: !!rec.editAt,
    localAt: Date.parse(rec.editAt ?? '') || 0,
    serverAt: Date.parse(doc.updatedAt ?? '') || 0,
  })
}
