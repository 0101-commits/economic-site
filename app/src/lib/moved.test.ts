import test from 'node:test'
import assert from 'node:assert/strict'
import { movedInfo, OLD_HOST, NEW_URL } from './moved.ts'

test('옛 주소에서만 띠를 보인다', () => {
  assert.equal(movedInfo(OLD_HOST, '').show, true)
  assert.equal(movedInfo('ecom-terminal.pages.dev', '').show, false)
  assert.equal(movedInfo('localhost', '#/market').show, false)
})

test('새 주소 링크는 해시를 유지한다', () => {
  assert.equal(movedInfo(OLD_HOST, '#/market?a=kr').newUrl, 'https://ecom-terminal.pages.dev/#/market?a=kr')
  assert.equal(movedInfo(OLD_HOST, '').newUrl, NEW_URL)
})
