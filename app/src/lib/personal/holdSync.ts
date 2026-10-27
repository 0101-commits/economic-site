// 보유(평단가 · 수량 · 매입 환율) 저절로 맞춤 — 앱키로 들어온 기기끼리 묻지 않고 같게 한다. 규칙은 syncRules.settle 하나.
// 저장소는 scoped.ts(사람별 이름), 네트워크는 deps(sync.ts 가 Worker /portfolio 로 꽂는다) — node --test 로 돈다(holdSync.test.ts).
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(calc.ts 와 같은 규칙).
//
// 언제   들어올 때(새 입장 — 맞춘 기록을 지우고 서버 우선) · 앱을 열 때 · 탭으로 돌아올 때(1분에 한 번까지) · 내 자산을 열 때 · 보유 저장 2초 뒤.
// 기록   econHoldSync_v1(사람별) = { base: 마지막으로 서버와 같았던 보유 지문, srv: 그때 서버 암호문의 SHA-256, srvAt: 그 판을 바꾼 때,
//        editAt: 그 뒤 이 기기에서 바꾼 마지막 때(올리면 지움), names: 이름만 고쳐 아직 못 올림, upAt · downAt } — 보유 값은 없다.
//        예전 판이 남긴 { base, upAt, downAt, server, checkedAt } 도 그대로 읽는다(srv 가 없으면 서버 판을 풀어 지문으로 견준다).
// 시각   덩어리 안의 t = 「그 판을 바꾼 때」(e2e.ts encrypt 의 at) — 암호문 안이라 Worker(_sanitizeEncHoldings)는 그대로 둔다.
//        올릴 때 t = 이 기기에서 바꾼 때(editAt, 모르면 지금). 이름만 고쳐 올릴 때 · 다시 잠글 때는 서버 판의 t 를 그대로 둔다.
// 막음   예비 앱키로 들어온 기기는 올리지 않는다(마스터가 못 여는 판 · 빈 판으로 덮지 않게) — 못 열면 한 줄(HOLD_TEXT.backup).
//        못 여는 서버 판(옛 형식 — 예전 평단가 암호나 바꾸기 전 앱키로 잠금)은 덮지 않고 내 자산에 한 줄 + 예전 암호 칸(run({ old })).
//        예전 암호를 모르면 run({ drop: true })로 이 기기 보유를 새로 잠근다(서버에 있던 덩어리는 이 기기 portfolioV1:prev 에 그대로).
import { applyEntries, encrypt, entriesOf, fingerprint, openBlob, type EncBlob, type Entry } from './e2e.ts'
import { needsName } from './names.ts'
import { keepPrev, read, readPortfolio, write, writePortfolio, type Portfolio } from './scoped.ts'
import { storeKey } from './who.ts'
import { settle } from './syncRules.ts'
import type { PortfolioReply } from './remote.ts'
import type { Holding } from './calc.ts'

export type HoldRec = { base?: string; srv?: string | null; srvAt?: string | null; editAt?: string; names?: boolean; upAt?: string; downAt?: string; server?: boolean; checkedAt?: string }
export function readHoldRec(): HoldRec {
  const r = read<unknown>(storeKey('econHoldSync_v1'), {})
  return r && typeof r === 'object' && !Array.isArray(r) ? (r as HoldRec) : {}
}
const noteRec = (p: Partial<HoldRec>) => write(storeKey('econHoldSync_v1'), { ...readHoldRec(), ...p })
/** 이 기기에서 보유를 바꿨다(내 자산 저장 · 파일 올리기). 둘 다 바뀌었을 때 「나중」을 가리는 데 쓴다. */
export function noteHoldEdit(at = new Date().toISOString()): void { noteRec({ editAt: at }) }
/** 이름만 고쳤다(지문은 그대로) — 다음 맞춤에서 한 번 올려 이름(n)이 다른 기기로 가게 한다. */
export function noteHoldNames(): void { noteRec({ names: true }) }
/** 새 입장: 맞춘 기록을 지운다 — 다음 맞춤은 서버 판을 우선한다(syncRules 3). */
export function resetHoldRec(): void { write(storeKey('econHoldSync_v1'), {}) }

/** wait = 잠깐 못 닿음(앞서 보이던 한 줄을 그대로 둔다) · 그 밖은 내 자산 한 줄의 종류. */
export type HoldKind = '' | 'wait' | 'info' | 'old' | 'broken' | 'backup' | 'nokey' | 'error'
export type HoldState = { kind: HoldKind; text: string }
export type HoldResult = { pulled: boolean; pushed: boolean; state: HoldState }
export const HOLD_TEXT = {
  backup: '예비 앱키로는 보유를 열 수 없습니다. 마스터 앱키로 들어와 주세요',
  backupPush: '예비 앱키로 들어온 기기는 보유를 올리지 않습니다. 마스터 앱키로 들어와 주세요',
  old: '예전 평단가 암호나 바꾸기 전 앱키로 잠긴 보유가 있습니다. 한 번 넣으면 지금 앱키로 다시 잠급니다.',
  oldWrong: '넣은 암호로는 열리지 않습니다. 예전 평단가 암호나 바꾸기 전 앱키를 넣어 주세요.',
  broken: '저장된 보유를 읽지 못했습니다.',
  nokey: '이 기기에서는 보유를 열 수 없습니다. 설정 › 내 계정에서 「이 기기에서 나가기」를 누른 뒤 앱키로 다시 들어와 주세요.',
  dropEmpty: '이 기기에 보유가 없어 새로 잠글 수 없습니다. 저장된 보유를 열 수 있는 예전 암호를 넣어 주세요.',
  tooBig: '보유 종목이 너무 많아 저장할 수 없습니다.',
  saveFail: '이 기기에 저장하지 못했습니다. 시크릿 창이거나 저장 공간이 찼습니다.',
  keptDevice: '저장된 보유로 바꿨습니다. 이 기기에 있던 것은 한 벌 남겨 두었습니다.',
  keptServer: '이 기기에서 나중에 바꾼 보유로 저장했습니다. 다른 기기에서 바꾼 것은 이 기기에 한 벌 남겨 두었습니다.',
} as const
const st = (kind: HoldKind, text = ''): HoldState => ({ kind, text })
const OK = st('')

export type HoldDeps = {
  hash: () => string | null              // 앱키 해시(없으면 들어오지 않음)
  mat: () => string | null               // 보유를 여는 재료(e2e.holdKeyOf — 앱키에서 만든 것)
  backup: () => boolean                  // 예비 앱키로 들어옴
  get: (hash: string) => Promise<PortfolioReply>
  post: (hash: string, enc: EncBlob) => Promise<PortfolioReply>
  lost?: (hash: string) => void          // 401 — 앱키가 더는 안 맞음(sync.ts 가 이 기기에서 내보낸다)
  now?: () => number
}

const hex = (b: ArrayBuffer) => Array.from(new Uint8Array(b), x => x.toString(16).padStart(2, '0')).join('')
const sha = async (s: string) => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)))
const keyOf = (e: { m: string; s: string }) => `${e.m}:${e.s}`
const rowId = () => 'i' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)   // store.newId('i') 와 같은 꼴

/** 서버 판에만 있는 종목의 새 줄. */
const makeRow = (group: string) => (e: Entry): Holding => ({
  id: rowId(), symbol: e.s, market: e.m, yahoo: e.m === 'US' ? e.s : null, name: e.n ?? e.s, secType: 'stock',
  ccy: e.m === 'US' ? 'USD' : 'KRW', avg: e.a, qty: e.q, fxBuy: e.fx, group,
})
const withServer = (p: Portfolio, es: Entry[]): Portfolio => ({ ...p, items: applyEntries(p.items, es, makeRow(p.groups[0].id)) })

type Opened = { entries: Entry[]; at: string | null; stale: boolean } | { err: 'old' | 'wrong' | 'broken' }
async function open(enc: EncBlob, mat: string, old?: string): Promise<Opened> {
  try { return await openBlob(enc, mat, old) } catch (e) {
    const m = (e as Error).message
    return { err: m === 'old-pass' ? 'old' : m === 'wrong-pass' ? 'wrong' : 'broken' }
  }
}

export function makeHoldSync(d: HoldDeps) {
  const iso = () => new Date(d.now?.() ?? Date.now()).toISOString()
  const res = (pulled: boolean, pushed: boolean, state: HoldState = OK): HoldResult => ({ pulled, pushed, state })
  /** 잠깐 못 닿음(0 · 429 · 5xx)은 말없이(wait) — 다음에 열 때 · 돌아올 때 다시 한다. */
  function failed(r: { status: number; error?: string }, h: string): HoldState {
    if (r.status === 401) { d.lost?.(h); return OK }
    if (r.status === 0 || r.status === 429 || r.status >= 500) return st('wait')
    if (r.status === 413) return st('error', HOLD_TEXT.tooBig)
    return st('error', `보유를 저장하지 못했습니다(${r.error ?? r.status}).`)
  }

  /**
   * 맞춤 한 번. old = 옛 형식 판을 풀 예전 암호(내 자산 한 줄 칸) · drop = 못 여는 서버 판 대신 이 기기 보유로 새로 잠금.
   * 할 일은 syncRules.settle 이 정하고, 진 쪽은 portfolioV1:prev 에 한 벌 남긴다.
   */
  async function run(o: { old?: string; drop?: boolean } = {}): Promise<HoldResult> {
    const h = d.hash()
    if (!h) return res(false, false)
    const mat = d.mat()
    if (!mat) return res(false, false, st('nokey', HOLD_TEXT.nokey))
    const g = await d.get(h)
    if (!g.ok) return res(false, false, failed(g, h))
    return step(h, mat, g.enc ?? null, o, 0)
  }

  async function step(h: string, mat: string, enc: EncBlob | null, o: { old?: string; drop?: boolean }, again: number): Promise<HoldResult> {
    const backup = d.backup()
    const rec = readHoldRec()
    const p = readPortfolio()
    const local = entriesOf(p.items)
    const lfp = await fingerprint(local)
    const ct = enc ? await sha(enc.ciphertext) : null

    // 서버 판: 맞춘 뒤 그대로면(암호문이 같으면) 풀지 않는다 — 풀기는 PBKDF2 60만 번이라 폰에서 1~3초.
    let srv: { entries: Entry[] | null; at: string | null; fp: string; stale: boolean } | null = null
    if (enc) {
      if (!o.old && rec.base && rec.srv && ct === rec.srv) srv = { entries: null, at: rec.srvAt ?? null, fp: rec.base, stale: false }
      else {
        const x = await open(enc, mat, o.old)
        if ('err' in x) {
          if (backup) return res(false, false, st('backup', HOLD_TEXT.backup))
          if (o.drop) {
            // 이 기기에 보유가 없으면 빈 판으로 서버 판을 덮게 된다 — 올리지 않고 이유만 말한다
            if (!local.length) return res(false, false, st('error', HOLD_TEXT.dropEmpty))
            keepPrev('portfolioV1', { side: 'server', at: null, enc })
            return upload(h, mat, local, rec.editAt ?? iso(), ct, rec, o, again, OK)
          }
          return res(false, false, x.err === 'broken' ? st('broken', HOLD_TEXT.broken) : st('old', x.err === 'wrong' ? HOLD_TEXT.oldWrong : HOLD_TEXT.old))
        }
        srv = { entries: x.entries, at: x.at, fp: await fingerprint(x.entries), stale: x.stale }
      }
    }

    const known = typeof rec.base === 'string'
    const s = settle({
      serverHas: !!srv, localHas: local.length > 0, same: !!srv && srv.fp === lfp,
      known, localChanged: known && lfp !== rec.base, serverChanged: known && !!srv && srv.fp !== rec.base,
      localEdited: !!rec.editAt, localAt: Date.parse(rec.editAt ?? '') || 0, serverAt: Date.parse(srv?.at ?? '') || 0,
    })
    // 받거나 진 서버 판을 남기려면 칸이 있어야 한다 — 풀지 않고 넘어온 판이면 이제 푼다
    if (srv && !srv.entries && (s.act === 'pull' || s.keep === 'server')) {
      const x = await open(enc!, mat)
      if ('err' in x) return res(false, false, backup ? st('backup', HOLD_TEXT.backup) : st('broken', HOLD_TEXT.broken))
      srv = { ...srv, entries: x.entries, at: x.at }
    }

    if (s.act === 'pull' && srv?.entries) {
      // 푸는 동안 이 기기에서 바꿨으면 덮지 않는다 — 저장 2초 뒤 맞춤이 다시 온다
      if (await fingerprint(entriesOf(readPortfolio().items)) !== lfp) return res(false, false)
      if (s.keep === 'device') keepPrev('portfolioV1', { side: 'device', at: rec.editAt ?? null, data: p })
      if (!writePortfolio(withServer(readPortfolio(), srv.entries))) return res(false, false, st('error', HOLD_TEXT.saveFail))
      noteRec({ base: srv.fp, srv: ct, srvAt: srv.at, editAt: undefined, downAt: iso() })
      const note = s.keep === 'device' ? st('info', HOLD_TEXT.keptDevice) : OK
      // 옛 형식 판을 예전 암호로 풀어 받았으면 지금 앱키로 다시 잠가 둔다(바뀐 때는 그 판 그대로)
      if (srv.stale && !backup) { const r = await upload(h, mat, entriesOf(readPortfolio().items), srv.at ?? iso(), ct, readHoldRec(), {}, again, note); return { ...r, pulled: true } }
      return res(true, false, note)
    }

    if (s.act === 'push') {
      if (backup) return res(false, false, st('backup', HOLD_TEXT.backupPush))
      if (s.keep === 'server' && srv?.entries) keepPrev('portfolioV1', { side: 'server', at: srv.at, data: withServer(p, srv.entries) })
      return upload(h, mat, local, rec.editAt ?? iso(), ct, rec, o, again, s.keep === 'server' ? st('info', HOLD_TEXT.keptServer) : OK)
    }

    // 할 일 없음 — 맞춘 기록을 새로 두고, 이름만 다르면 채우거나(받기) 한 번 올린다(이름 n 이 다른 기기로 가게)
    if (!srv) { noteRec({ base: lfp, srv: null, srvAt: null }); return res(false, false) }
    let pulled = false
    if (srv.entries) {
      const names = new Map(srv.entries.filter(e => e.n).map(e => [keyOf(e), e.n!]))
      const cur = readPortfolio()
      const fill = (it: Holding) => (needsName(it) ? names.get(keyOf({ m: it.market === 'US' ? 'US' : 'KR', s: it.symbol })) : undefined)
      if (cur.items.some(fill) && writePortfolio({ ...cur, items: cur.items.map(it => { const n = fill(it); return n ? { ...it, name: n } : it }) })) pulled = true
    }
    // 같아졌다 — 아직 못 올린 「바꾼 때」도 풀린 것이다(그사이 또 바꿨으면 남긴다)
    if (rec.base !== lfp || rec.srv !== ct || rec.editAt) {
      const now = readHoldRec()
      noteRec({ base: lfp, srv: ct, srvAt: srv.at, editAt: now.editAt === rec.editAt ? undefined : now.editAt })
    }
    const missing = !!srv.entries && local.some(e => e.n && !srv!.entries!.some(x => keyOf(x) === keyOf(e) && x.n))
    if ((rec.names || missing || srv.stale) && !backup) {
      const r = await upload(h, mat, entriesOf(readPortfolio().items), srv.at ?? iso(), ct, readHoldRec(), {}, again, OK)
      return { ...r, pulled: pulled || r.pulled }
    }
    return res(pulled, false)
  }

  /** 잠가 올리기. 잠그는 동안(1~3초) 다른 기기가 올렸으면 덮지 않고 처음부터 한 번 더 본다. */
  async function upload(h: string, mat: string, es: Entry[], t: string, seenCt: string | null, rec: HoldRec, o: { old?: string; drop?: boolean }, again: number, done: HoldState): Promise<HoldResult> {
    const enc = await encrypt(es, mat, t)
    if (enc.ciphertext.length > 60_000) return res(false, false, st('error', HOLD_TEXT.tooBig))   // Worker _sanitizeEncHoldings 한도
    const g = await d.get(h)
    if (!g.ok) return res(false, false, failed(g, h))
    if ((g.enc ? await sha(g.enc.ciphertext) : null) !== seenCt) return again < 1 ? step(h, mat, g.enc ?? null, { old: o.old }, again + 1) : res(false, false)
    const r = await d.post(h, enc)
    if (!r.ok) return res(false, false, failed(r, h))
    const now = readHoldRec()
    noteRec({ base: await fingerprint(es), srv: await sha(enc.ciphertext), srvAt: t, editAt: now.editAt === rec.editAt ? undefined : now.editAt, names: false, upAt: iso(), server: true })
    return res(false, true, done)
  }

  /** 앱키를 바꾸며 다시 잠가 올린 판(sync.changeKey) — 내용 · 바뀐 때는 그대로이니 암호문 지문만 새로 둔다. */
  async function noteUploaded(enc: EncBlob): Promise<void> {
    noteRec({ srv: await sha(enc.ciphertext), upAt: iso(), server: true })
  }

  return { run, noteUploaded }
}
