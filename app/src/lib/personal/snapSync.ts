// 스냅샷 서버 맞춤 — Worker GET · PUT /snaps(사람 칸 snaps:<uid>)와 이 기기 pfSnapshotsV1 을 날짜별로 합친다. 규칙은 snapRules.ts(close 우선 · 730건).
// 보유(holdSync.ts)와 같은 길을 탄다: 들어올 때 · 앱을 열 때 · 탭으로 돌아올 때(sync.ts 가 보유 맞춤 뒤에 이어 부른다) — 따로 도는 감시는 없다.
// 저장소 · 네트워크는 deps(sync.ts 가 꽂는다) — node --test 로 돈다(snapSync.test.ts). 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다.
//
// 열쇠   보유와 같은 재료(앱키에서 만든 hex — e2e.holdKeyOf)로 잠근다. 재료가 없으면(이 기기에서 열 수 없음) 받지도 올리지도 않는다.
// 막음   예비 앱키로 들어온 기기는 받지도 올리지도 않는다 — 마스터 재료가 아니라 풀 수 없고, 올리면 마스터가 못 여는 판이 서버 판을 덮는다.
//        서버 판을 못 풀면(다른 재료 · 깨짐) 덮지 않는다.
// 기록   econSnapSync_v1(사람별) = { srv: 마지막으로 맞춘 서버 암호문의 SHA-256, fp: 그때 이 기기 목록의 지문 } — 값은 없다. 둘 다 그대로면 풀지 않는다(PBKDF2 60만 번).
// 덮어쓰기 경쟁  PUT 에 If-Match 가 없다 — 그사이 다른 기기가 올렸어도 합친 것은 합집합이라, 사라진 날짜는 그 기기가 다음 맞춤에서 다시 올린다.
import { decryptJson, encryptJson, type EncBlob } from './e2e.ts'
import { decideSnaps, parseSnapPlain, snapPlain, snapsKey, type Snap } from './snapRules.ts'

export type SnapRec = { srv?: string | null; fp?: string }
export type SnapReply = { ok: boolean; status: number; enc?: EncBlob | null; error?: string }
export type SnapDeps = {
  hash: () => string | null                  // 앱키 해시(없으면 들어오지 않음)
  mat: () => string | null                   // 보유를 여는 재료(없으면 이 기기에서 열 수 없음)
  backup: () => boolean                      // 예비 앱키로 들어옴
  get: (hash: string) => Promise<SnapReply>
  put: (hash: string, enc: EncBlob) => Promise<SnapReply>
  read: () => Snap[]                         // 이 기기 스냅샷
  write: (a: Snap[]) => boolean              // 이 기기에 쓴다(못 쓰면 false)
  readRec: () => SnapRec
  writeRec: (r: SnapRec) => void
  lost?: (hash: string) => void              // 401 — 앱키가 더는 안 맞음
  now?: () => number
}
export type SnapResult = { pulled: boolean; pushed: boolean }

const hex = (b: ArrayBuffer) => Array.from(new Uint8Array(b), x => x.toString(16).padStart(2, '0')).join('')
const sha = async (s: string) => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)))

export function makeSnapSync(d: SnapDeps) {
  const none: SnapResult = { pulled: false, pushed: false }

  /** 맞춤 한 번. pulled = 이 기기 스냅샷이 바뀌었다 · pushed = 서버에 올렸다. 못 닿거나 못 풀면 말없이 none(다음에 다시). */
  async function run(): Promise<SnapResult> {
    const h = d.hash()
    if (!h || d.backup()) return none
    const mat = d.mat()
    if (!mat) return none
    const g = await d.get(h)
    if (!g.ok) { if (g.status === 401) d.lost?.(h); return none }

    const local = d.read()
    const rec = d.readRec()
    const ct = g.enc ? await sha(g.enc.ciphertext) : null
    if (ct && rec.srv === ct && rec.fp === snapsKey(local)) return none   // 맞춘 뒤 서버도 이 기기도 그대로

    let server: Snap[] | null = null
    if (g.enc) {
      try { server = parseSnapPlain(await decryptJson(g.enc, mat)) } catch { return none }   // 못 풀면 덮지 않는다
    }
    const x = decideSnaps(local, server)
    let pulled = false
    if (x.writeLocal) { if (!d.write(x.merged)) return none; pulled = true }
    if (!x.push) {
      if (ct) d.writeRec({ srv: ct, fp: snapsKey(x.merged) })
      return { pulled, pushed: false }
    }
    const enc = await encryptJson(snapPlain(x.merged, new Date(d.now?.() ?? Date.now()).toISOString()), mat)
    const r = await d.put(h, enc)
    if (!r.ok) { if (r.status === 401) d.lost?.(h); return { pulled, pushed: false } }
    d.writeRec({ srv: await sha(enc.ciphertext), fp: snapsKey(x.merged) })
    return { pulled, pushed: true }
  }

  return { run }
}
