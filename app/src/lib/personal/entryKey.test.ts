// 자가검사: npm test --prefix app — 입장 키 정규화(Worker test_users.mjs 의 normalizeEntryKey 행과 같은 입력 · 기대)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { normalizeEntryKey } from './entryKey.ts'

const rows: [string, string, string][] = [
  ['공백·소문자 정리', ' ecom-7kq3 px9m-2hta ', 'ECOM-7KQ3-PX9M-2HTA'],
  ['옛 키 그대로', 'My-Key 2026 Pass', 'My-Key 2026 Pass'],
  ['11자 → trim', 'ECOM-7KQ3-PX9M-2HT ', 'ECOM-7KQ3-PX9M-2HT'],
  ['O 포함 → trim', ' ECOM-OKQ3-PX9M-2HTA', 'ECOM-OKQ3-PX9M-2HTA'],
]

for (const [label, input, want] of rows) {
  test(`normalizeEntryKey: ${label}`, () => assert.equal(normalizeEntryKey(input), want))
}
