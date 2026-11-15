// 읽는 값 표기(lib/read.ts) — 부호 · 단위 · 범위 · 기준 기간 말 · 컨센서스 대비 말 · 칸 바꾸기.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { asRead, consText, fmtRead, refDate, refLabel, releasedLabel, type Read } from './read.ts'
import type { StripItem } from './bundle.ts'

const cell = (o: Partial<Read['main']>): Read['main'] => ({ b: 'mom', word: '전월 대비', short: '전월비', value: 0.4, unit: '%', dec: 1, sign: true, src: 'official', ...o })

test('fmtRead: 변화율은 부호, 수준은 부호 없음, 범위는 하단~상단, 단위는 붙여 쓴다', () => {
  assert.equal(fmtRead(cell({})), '+0.4%')
  assert.equal(fmtRead(cell({ value: -0.1 })), '-0.1%')
  assert.equal(fmtRead(cell({ value: 0 })), '0.0%')
  assert.equal(fmtRead(cell({ b: 'level', sign: false, value: 4.1 })), '4.1%')
  assert.equal(fmtRead(cell({ b: 'dmom', unit: '만 명', value: 16.5 })), '+16.5만 명')
  assert.equal(fmtRead(cell({ b: 'range', sign: false, value: 4, lo: 3.75, dec: 2 })), '3.75~4.00%')
  assert.equal(fmtRead(cell({ b: 'level', sign: false, unit: '억 달러', value: 1210.5 })), '1,210.5억 달러')
  assert.equal(fmtRead(cell({ value: null })), '—')
})

test('refLabel · releasedLabel · refDate', () => {
  assert.equal(refLabel('2026-10'), '10월분')
  assert.equal(refLabel('2026-Q3'), '3분기')
  assert.equal(refLabel('2026-11-14'), '11/14')
  assert.equal(releasedLabel('2026-11-10'), '11/10 발표')
  assert.equal(refDate('2026-Q3'), '2026-07-01')
  assert.equal(refDate('2026-10'), '2026-10-01')
})

test('consText: 같음 · %p 높음/낮음 · 인원은 많음/적음 · 컨센서스 없으면 null', () => {
  const r = (o: Partial<Read>): Read => ({ ref: '2026-10', freq: 'M', main: cell({}), subs: [], ...o })
  assert.equal(consText(r({ cons: 0.3, diff: 0 })), '같음')
  assert.equal(consText(r({ cons: 0.3, diff: 0.1 })), '0.1%p 높음')
  assert.equal(consText(r({ cons: 2.9, diff: -0.1 })), '0.1%p 낮음')
  assert.equal(consText(r({ main: cell({ b: 'dmom', unit: '만 명' }), cons: 6.5, diff: 10 })), '10.0만 명 많음')
  assert.equal(consText(r({})), null)
})

test('asRead: 큰 숫자 = 읽는 값, 이름 = 나라 + 읽는 이름, 시계열 = 읽는 값(지수 아님)', () => {
  const it: StripItem = {
    id: 'cpi_us', label: '소비자물가지수 (CPI)', short: '미국 소비자물가지수', decimals: 1, value: 337.476, change: 1.18, changePct: 0.35,
    unit: '지수 (1982-84=100)', asOf: '2026-10', country: 'us',
    read: { name: '소비자물가', ref: '2026-10', freq: 'M', main: cell({}), subs: [], prev: 0.6, series: [['2026-09', 0.6], ['2026-10', 0.4]] },
  }
  const r = asRead(it)
  assert.equal(r.value, 0.4)
  assert.equal(r.label, '미국 소비자물가')
  assert.equal(r.unit, '%')
  assert.equal(r.change, -0.2)
  assert.equal(r.changePct, null)
  assert.deepEqual(r.series, [['2026-09-01', 0.6], ['2026-10-01', 0.4]])
  const plain = { ...it, read: undefined }
  assert.equal(asRead(plain), plain)      // read 없으면 그대로
})
