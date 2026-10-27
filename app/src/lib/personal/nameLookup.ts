// 종목 이름 찾기의 실제 출처 — 그날 종목 목록(loadStocks) → 미국 한글 이름표(US_KO) → Yahoo 회사 이름(stockSeries).
// Worker /quotes 는 이름을 주지 않으므로(Worker 는 이 일에서 건드리지 않는다) 세 번째는 종목 상세가 쓰는 일봉 응답의 이름이다.
import { loadStocks } from '../bundle'
import { US_KO } from '../detail'
import { stockSeries } from './quotes'
import { resolveNameWith, fixNames, needsName, codeKey, type NameSource } from './names'
import { readPortfolio, writePortfolio } from './scoped'

const bundleName: NameSource = async (symbol) => {
  const m = await loadStocks()
  return (m.get(symbol) ?? m.get(codeKey(symbol)))?.name
}
const usKo: NameSource = (symbol, market) => (market === 'US' ? US_KO[codeKey(symbol)] ?? US_KO[symbol] : undefined)
const yahooName: NameSource = async (symbol, market) => (await stockSeries(symbol, market === 'KR'))?.name

/** 종목 이름 하나(없으면 undefined). 순서: 종목 목록 → US_KO → Yahoo 이름. */
export const resolveName = (symbol: string, market: 'KR' | 'US'): Promise<string | undefined> =>
  resolveNameWith(symbol, market, [bundleName, usKo, yahooName])

/** 보유를 불러올 때: 이름 없는 줄만 채워 저장한다. 바뀌었으면 true. */
export async function fixHoldingNames(): Promise<boolean> {
  const r = await fixNames(readPortfolio().items, resolveName)
  if (!r.changed) return false
  // 찾는 동안 다른 곳이 바꿨을 수 있다 — 저장 직전에 다시 읽고, 아직 이름 없는 줄에만 채운다
  const cur = readPortfolio()
  const found = new Map(r.items.map(i => [i.id, i.name]))
  const items = cur.items.map(i => (needsName(i) && found.has(i.id) && typeof found.get(i.id) === 'string' ? { ...i, name: found.get(i.id) as string } : i))
  return writePortfolio({ ...cur, items })
}
