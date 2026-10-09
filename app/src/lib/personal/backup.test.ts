// 자가검사: npm test --prefix app — 내 데이터 파일 왕복 · 파일 암호 검사 · 잠근 파일 왕복과 틀린 암호 · 비밀이 파일에 없음 · 깨진 파일 거절 · 시나리오 출처 · 이전 화면 백업
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { countOf, FORMAT, makeFile, MAX_BYTES, passIssue, readFile, type MyData } from './backup.ts'
import { defaultSettings } from './prefsV2.ts'

const AT = '2026-10-09T01:02:03.000Z'
const PASS = 'fake-file-pass-2026'   // 가짜 파일 암호(테스트 전용)
const PIN = '135790'                  // 가짜 잠금 PIN(테스트 전용)
const data = (): MyData => ({
  portfolio: { groups: [{ id: 'g_default', name: '기본 그룹' }], items: [{ id: 'i1', symbol: '005930', market: 'KR', name: '가짜 A', avg: 70000, qty: 10 } as any], alerts: [], lastSync: null },
  snapshots: [{ d: '2026-10-08', ev: 700000, ct: 650000 }],
  ledger: [{ id: 'l1', d: '2026-10-01', kind: 'div', amt: 1200, memo: '가짜' }],
  watch: ['kospi', 'usdkrw'],
  prefs: { alerts: [{ id: 'c1', event: 'U1', target: 'usdkrw', dir: 'up', value: 1400, repeat: 'once', enabled: true }, { id: 'c2', event: 'A1', target: '*', repeat: 'each', enabled: true }], settings: { ...defaultSettings(), unit: 'won', updown: 'us' } },
  theme: 'dark',
  scenarios: [{ name: '시나리오 1', start: 'oil', dir: 1, depth: 2, at: AT }],
})

test('왕복: 만들기 → 읽기 → 같은 내용 · 미리보기 숫자', async () => {
  const d = data()
  const got = await readFile(await makeFile(d, AT))
  assert.equal(got.at, AT)
  assert.equal(got.legacy, undefined)
  for (const k of ['portfolio', 'snapshots', 'ledger', 'watch', 'prefs', 'theme', 'scenarios'] as const) assert.deepEqual(got[k], d[k], k)
  assert.deepEqual(countOf(got), { holdings: 1, ledger: 1, snapshots: 1, watch: 2, alerts: 1, scenarios: 1 })
})

test('파일 암호 검사: 10자 미만 · 두 칸 다름 · 잠금 PIN 과 같음(공백 뺀 값 포함)은 거절', async () => {
  const isPin = async (p: string) => p === PIN
  assert.match(await passIssue('short-9ch', 'short-9ch', isPin), /10자 이상/)
  assert.match(await passIssue('          x', '          x', isPin), /10자 이상/)
  assert.match(await passIssue(PASS, PASS + '!', isPin), /두 칸이 다릅니다/)
  const pinLike = PIN + '0000'
  assert.match(await passIssue(pinLike, pinLike, async p => p === pinLike), /PIN 과 다른/)
  assert.match(await passIssue(` ${pinLike} `, ` ${pinLike} `, async p => p === pinLike), /PIN 과 다른/)
  assert.equal(await passIssue(PASS, PASS, isPin), '')
})

test('잠근 파일: 암호 없으면 need-pass · 틀리면 wrong-pass · 맞으면 같은 내용, 평문은 표지와 암호 조건만', async () => {
  const d = data()
  const text = await makeFile(d, AT, PASS)
  const doc = JSON.parse(text)
  assert.deepEqual(Object.keys(doc).sort(), ['alg', 'ciphertext', 'format', 'iter', 'iv', 'kdf', 'locked', 'salt', 'version'])
  assert.equal(doc.format, FORMAT); assert.equal(doc.locked, true)
  for (const s of ['005930', '70000', 'usdkrw', AT, PASS]) assert.ok(!text.includes(s), s)
  await assert.rejects(readFile(text), /need-pass/)
  await assert.rejects(readFile(text, PASS + 'x'), /wrong-pass/)
  const got = await readFile(text, PASS)
  assert.equal(got.at, AT)
  for (const k of ['portfolio', 'snapshots', 'ledger', 'watch', 'prefs', 'theme', 'scenarios'] as const) assert.deepEqual(got[k], d[k], k)
})

test('비밀이 파일에 없음: 칸은 정해진 열 개뿐, 키 해시 · 보유 열쇠 · PIN · 사용 기록 이름이 없다', async () => {
  const text = await makeFile(data(), AT)
  assert.deepEqual(Object.keys(JSON.parse(text)).sort(), ['exportedAt', 'format', 'ledger', 'note', 'portfolio', 'prefs', 'scenarios', 'snapshots', 'version', 'watch'])
  for (const s of ['econHoldKey_v1', 'econSyncHash', 'econLockPin_v2', 'pfSyncKey', 'pfHoldingsPass', 'econ_usage_v1', PASS]) assert.ok(!text.includes(s), s)
  // 저장소에서 읽는 곳(store.readMyData)도 비밀 열쇠를 부르지 않는다
  const src = readFileSync(new URL('./store.ts', import.meta.url), 'utf8')
  const body = src.slice(src.indexOf('export function readMyData'), src.indexOf('export function writeMyData'))
  for (const s of ['holdKey', 'econSync', 'Lock', 'usage', 'sessionStorage']) assert.ok(!body.includes(s), s)
})

test('깨진 파일 거절', async () => {
  const ok = JSON.parse(await makeFile(data(), AT))
  const bad = async (t: string, re: RegExp) => assert.rejects(readFile(t), re)
  await bad('{ 깨짐', /깨졌습니다/)
  await bad('[1,2]', /깨졌습니다/)
  await bad(JSON.stringify({ ...ok, extra: 1 }), /모르는 칸.*extra/)
  await bad(JSON.stringify({ ...ok, version: 2 }), /모르는 판/)
  await bad(JSON.stringify({ ...ok, format: 'other' }), /내려받은 파일이 아닙니다/)
  await bad(JSON.stringify({ hello: 1 }), /내려받은 파일이 아닙니다/)
  await bad(JSON.stringify({ ...ok, portfolio: { items: 'x' } }), /portfolio/)
  await bad(JSON.stringify({ ...ok, snapshots: {} }), /snapshots/)
  await bad(JSON.stringify({ ...ok, note: 'x'.repeat(MAX_BYTES) }), /너무 큽니다/)
  // 잠근 파일의 표지에 모르는 칸
  await bad(JSON.stringify({ ...JSON.parse(await makeFile(data(), AT, PASS)), hint: 'x' }), /모르는 칸.*hint/)
})

test('시나리오 출처: 파일의 scenarios 는 렌즈 저장(econ_scenarios_v1) 그대로, prefs 에는 없다 · 렌즈가 못 읽는 모양은 거른다', async () => {
  const doc = JSON.parse(await makeFile(data(), AT))
  assert.deepEqual(doc.scenarios, data().scenarios)
  assert.equal('scenarios' in doc.prefs, false)
  // 예전 판(prefs.scenarios 의 { name, inputs } 모양)은 렌즈가 못 읽는다 — 빈 목록으로 이 기기 저장을 지우지 않게 칸 없음(undefined)
  const old = { ...doc, scenarios: [{ name: 'x', inputs: {} }] }
  assert.equal((await readFile(JSON.stringify(old))).scenarios, undefined)
  // 열쇠가 렌즈 화면과 같다
  const whatIf = readFileSync(new URL('../../components/lens/WhatIf.tsx', import.meta.url), 'utf8')
  const store = readFileSync(new URL('./store.ts', import.meta.url), 'utf8')
  assert.match(whatIf, /SAVE_KEY = 'econ_scenarios_v1'/)
  assert.match(store, /scenarios: 'econ_scenarios_v1'/)
  assert.match(store, /read<unknown>\(KEYS\.scenarios, \[\]\)/)
})

test('파일에 없는 칸 · 못 읽는 칸은 undefined(이 기기 것을 그대로 둔다), 원래 빈 목록은 빈 목록', async () => {
  const { prefs: _p, ledger: _l, watch: _w, ...rest } = JSON.parse(await makeFile(data(), AT))
  const got = await readFile(JSON.stringify({ ...rest, snapshots: [{ x: 1 }], scenarios: [] }))
  for (const k of ['prefs', 'theme', 'ledger', 'watch', 'snapshots'] as const) assert.equal(got[k], undefined, k)
  assert.deepEqual(got.scenarios, [])
  assert.deepEqual(countOf(got), { holdings: 1, ledger: null, snapshots: null, watch: null, alerts: null, scenarios: 0 })
  // prefs 는 있는데 화면 모드가 없으면 화면 모드만 그대로
  const noTheme = JSON.parse(await makeFile(data(), AT)); delete noTheme.prefs.settings.theme
  const g2 = await readFile(JSON.stringify(noTheme))
  assert.equal(g2.theme, undefined); assert.equal(g2.prefs!.alerts.length, 2)
})

test('표지 없는 예전 판(이 판 전 새 화면 내려받기)도 받는다', async () => {
  const { format: _f, version: _v, ...old } = JSON.parse(await makeFile(data(), AT))
  const got = await readFile(JSON.stringify(old))
  assert.equal(got.portfolio!.items.length, 1)
  assert.equal(got.theme, 'dark')
})

test('이전 화면 백업: 평문은 보유 · 스냅샷만, 암호 백업과 둘 다 없는 백업은 이전 화면으로', async () => {
  const d = data()
  const legacy = { schema: 'econ-terminal-backup', version: 1, exportedAt: AT, origin: 'x', data: { portfolioV1: JSON.stringify(d.portfolio), pfSnapshotsV1: JSON.stringify(d.snapshots), econ_notes: '노트' } }
  const got = await readFile(JSON.stringify(legacy))
  assert.equal(got.legacy, true)
  assert.deepEqual(got.portfolio, d.portfolio)
  assert.deepEqual(got.snapshots, d.snapshots)
  assert.equal(got.prefs, undefined)
  assert.deepEqual(countOf(got), { holdings: 1, ledger: null, snapshots: 1, watch: null, alerts: null, scenarios: null })
  await assert.rejects(readFile(JSON.stringify({ schema: 'econ-terminal-backup', version: 1, enc: {}, ciphertext: 'x' })), /이전 화면/)
  await assert.rejects(readFile(JSON.stringify({ ...legacy, data: { econ_notes: '노트' } })), /이전 화면에서 복원/)
})
