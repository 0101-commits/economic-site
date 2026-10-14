// 자가검사: npm test --prefix app — AI 요약(model.ts) 근거 번호 떼기 · 문장 · 근거 목록 · 대조 문구 · 회차 합치기(계약 C3)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { briefItems, briefRuns, briefSources, checkLine, splitRefs } from './model.ts'

test('splitRefs: 문장 끝 [1][2] 를 떼어 refs 로 — 묶음 refs 와 합치고 작은 순 · 겹침 없음', () => {
  assert.deepEqual(splitRefs('코스피가 1.19% 올랐습니다.[1][2]', []), { text: '코스피가 1.19% 올랐습니다.', refs: [1, 2] })
  assert.deepEqual(splitRefs('외국인이 팔았습니다. [3] [1]', [2, 3]), { text: '외국인이 팔았습니다.', refs: [1, 2, 3] })
  assert.deepEqual(splitRefs('번호 없음', [5, 1]), { text: '번호 없음', refs: [1, 5] })
  assert.deepEqual(splitRefs('가운데 [1] 번호는 글이다', null), { text: '가운데 [1] 번호는 글이다', refs: [] })   // 끝에 붙은 것만 근거 번호
  assert.deepEqual(splitRefs('잘못된 번호', [0, -1, 1.5, 'x', 2]), { text: '잘못된 번호', refs: [2] })
})

test('briefItems: items 가 없거나 비면 null(lines 만 그린다) · 빈 문장은 뺀다', () => {
  assert.equal(briefItems({}), null)
  assert.equal(briefItems(null), null)
  assert.equal(briefItems({ items: [] }), null)
  assert.equal(briefItems({ items: [{ text: '[1]' }, { refs: [1] }] }), null)
  assert.deepEqual(briefItems({ items: [{ text: '코스피가 …줄었습니다.', refs: [1, 2, 3] }, null, { text: ' ' }] }), [{ text: '코스피가 …줄었습니다.', refs: [1, 2, 3] }])
})

test('briefSources: 번호 순 · 기사 주소는 http(s) 만 · 번호 · 글 없는 칸은 뺀다', () => {
  const s = briefSources({ sources: [
    { n: 3, kind: '기사', label: '코스피, 외국인 7일째', src: '뉴스1', url: 'https://news1.kr/a', at: '13:51' },
    { n: 1, kind: '지표', label: 'KOSPI 6,077.57 ▲1.19%', at: '14:35' },
    { n: 5, kind: '일정', label: '미국 CPI', url: 'javascript:alert(1)' },
    { n: 0, label: 'x' }, { n: 2, kind: '수급' }, null,
  ] })
  assert.deepEqual(s.map(x => x.n), [1, 3, 5])
  assert.deepEqual(s[1], { n: 3, kind: '기사', label: '코스피, 외국인 7일째', src: '뉴스1', url: 'https://news1.kr/a', at: '13:51' })
  assert.equal(s[2].url, null)
  assert.deepEqual(briefSources({}), [])
})

test('checkLine: 「대조 통과 — 숫자 n · 일정 n · 근거 없는 문장 n 뺌」 · 칸이 없으면 null', () => {
  assert.equal(checkLine({ check: { numbers: 3, schedule: 1 }, dropped: 1 }), '대조 통과 — 숫자 3 · 일정 1 · 근거 없는 문장 1 뺌')
  assert.equal(checkLine({ check: { numbers: 2, schedule: 0 }, dropped: 0 }), '대조 통과 — 숫자 2 · 일정 0')   // 뺀 문장 0 은 적지 않는다
  assert.equal(checkLine({ dropped: 2 }), '대조 통과 — 근거 없는 문장 2 뺌')
  assert.equal(checkLine({ check: { numbers: 'x' } }), null)
  assert.equal(checkLine({}), null)
  assert.equal(checkLine(undefined), null)
})

test('briefRuns: 그날 파일 회차 + 지금 묶음(같은 시각이면 묶음이 이김) · 시각 순 · 날이 다르면 지금 것만', () => {
  const cur = { asOf: '2026-10-14T14:22:00+09:00', day: '2026-10-14', lines: ['지금'], items: [{ text: '지금', refs: [1] }] }
  const file = { date: '2026-10-14', runs: [
    { at: '14:22', lines: ['파일 속 같은 회차'] }, { at: '09:22', lines: ['아침'] }, { at: '12:22', lines: ['점심'] },
    { at: '15:22', lines: ['나중'] }, { at: '9:5', lines: ['깨짐'] }, { at: '13:22' },
  ] }
  const r = briefRuns(file, cur)
  assert.deepEqual(r.runs.map(x => x.at), ['09:22', '12:22', '14:22', '15:22'])
  assert.equal(r.cur, 2)
  assert.deepEqual(r.runs[2].lines, ['지금'])
  assert.equal('asOf' in r.runs[2], false)
  assert.deepEqual(briefRuns({ ...file, date: '2026-10-13' }, cur).runs.map(x => x.at), ['14:22'])
  assert.deepEqual(briefRuns(null, cur), { runs: [{ at: '14:22', lines: ['지금'], items: [{ text: '지금', refs: [1] }] }], cur: 0 })
  assert.deepEqual(briefRuns(file, { ...cur, asOf: null }).runs.length, 1)   // 작성 시각을 모르면 회차를 섞지 않는다
})
