// 보유 종목 이름 찾기 · 고치기 — 순수 함수만(저장소·네트워크 없음). node --test 로 바로 돈다(names.test.ts).
// 실제 출처(loadStocks · US_KO · Yahoo 이름)를 묶는 곳은 nameLookup.ts.
// 이 파일은 타입 표기 외의 TypeScript 전용 문법을 쓰지 않는다(calc.ts 와 같은 규칙).

export type NameSource = (symbol: string, market: 'KR' | 'US') => string | undefined | null | Promise<string | undefined | null>

/** 코드 비교용: 대문자 · 앞뒤 공백 · 국내 접미사(.KS/.KQ) 뺌. */
export const codeKey = (s: unknown): string => String(s ?? '').trim().toUpperCase().replace(/\.(KS|KQ)$/, '')

/** 이름이 비었거나 코드와 같다(= 코드가 이름 자리에 들어간 것). 직접 지은 이름은 false. */
export function needsName(h: { symbol: string; name?: unknown }): boolean {
  const n = typeof h.name === 'string' ? h.name.trim() : ''
  return !n || codeKey(n) === codeKey(h.symbol)
}

/** 출처를 차례로 물어 처음 나온 이름(코드와 같은 것은 이름이 아니다). 출처가 던지면 다음 출처로. */
export async function resolveNameWith(symbol: string, market: 'KR' | 'US', sources: NameSource[]): Promise<string | undefined> {
  for (const src of sources) {
    try {
      const n = await src(symbol, market)
      const t = typeof n === 'string' ? n.trim() : ''
      if (t && codeKey(t) !== codeKey(symbol)) return t.slice(0, 40)
    } catch { /* 다음 출처 */ }
  }
  return undefined
}

/** 이름 없는 줄만 찾아 채운다. 직접 지은 이름은 그대로. changed = 하나라도 바뀜. */
export async function fixNames<T extends { symbol: string; market: 'KR' | 'US'; name?: unknown }>(
  items: T[], resolve: (symbol: string, market: 'KR' | 'US') => Promise<string | undefined>,
): Promise<{ items: T[]; changed: boolean }> {
  let changed = false
  const out = await Promise.all(items.map(async it => {
    if (!needsName(it)) return it
    const n = await resolve(it.symbol, it.market).catch(() => undefined)
    if (!n) return it
    changed = true
    return { ...it, name: n }
  }))
  return { items: out, changed }
}
