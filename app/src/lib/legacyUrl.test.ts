import { test } from 'node:test'
import assert from 'node:assert/strict'
import { legacyToHash } from './legacyUrl.ts'

test('legacyToHash: 현행 주소 → 새 화면 해시', () => {
  assert.equal(legacyToHash(''), null)
  assert.equal(legacyToHash('?x=1'), null)
  assert.equal(legacyToHash('?p=dashboard'), '/')
  assert.equal(legacyToHash('?p=market&t=commodity'), '/market?a=commod')
  assert.equal(legacyToHash('?p=market&t=rate'), '/market?a=fxrate')
  assert.equal(legacyToHash('?p=market'), '/market?a=kr')
  assert.equal(legacyToHash('?p=macro&t=prices'), '/market?a=macro&v=prices')
  assert.equal(legacyToHash('?p=investor'), '/market?a=kr&v=flows')
  assert.equal(legacyToHash('?p=merlens'), '/lens')
  assert.equal(legacyToHash('?p=portfolio'), '/my')
  assert.equal(legacyToHash('?p=notes'), '/')   // 이관하지 않는 화면은 홈
})
