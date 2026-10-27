// 앱을 열 때 하루 한 번(한국 날짜) 오늘 스냅샷을 남긴다 — 「내 자산」을 열지 않아도. 화면에 보유 금액을 보이지 않고 이 기기 저장소에만 쓴다.
// 조건: 오늘 칸이 아직 없고 · 보유가 있고 · 보유 종목 시세가 다 있을 때(하나라도 없으면 건너뛴다 — 일부만 담긴 날은 위험 지표를 망친다).
// 남긴 값은 src:'app'. 마스터 작업의 종가 값(src:'close')이 서버에서 오면 합치기가 그쪽을 남긴다(snapRules.mergeSnaps).
// 앱을 연 직후의 서버 맞춤(보유 → 스냅샷)이 끝난 뒤에 남겨, 다른 기기가 오늘 칸을 이미 올렸으면 그것을 받고 건너뛴다.
import { evaluate } from './calc'
import { loadMarketData } from './data'
import { holdingQuotes } from './quotes'
import { readPortfolio, readSnaps, saveTodaySnap, storeKey } from './store'
import { kstDate } from './snapRules'
import { getKeyHash, openSyncDone, syncSnaps } from './sync'

let doneDay = '', running = false

/** 오늘 칸을 남겼으면 true. 이미 있거나 조건이 안 되면 false(다음 기회에 다시 본다). */
export async function ensureTodaySnap(): Promise<boolean> {
  const day = kstDate()
  if (running || doneDay === day || !getKeyHash()) return false
  running = true
  try {
    await openSyncDone()
    if (readSnaps().some(s => s.d === day)) { doneDay = day; return false }
    const items = readPortfolio().items
    if (!items.length) return false
    const md = await loadMarketData()
    const qs = await holdingQuotes(items, md.quotes)
    const { totals } = evaluate(items, qs, md.fx)
    if (totals.missing > 0 || !(totals.basisValue > 0 && totals.cost > 0)) return false
    if (kstDate() !== day || readSnaps().some(s => s.d === day)) return false   // 기다리는 사이 날이 바뀌었거나 다른 곳이 남겼다
    saveTodaySnap(totals.basisValue, totals.cost)
    doneDay = day
    window.dispatchEvent(new StorageEvent('storage', { key: storeKey('pfSnapshotsV1') }))
    void syncSnaps()
    return true
  } catch { return false } finally { running = false }
}
