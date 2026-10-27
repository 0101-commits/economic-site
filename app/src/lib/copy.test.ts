// 자가검사: npm test --prefix app — 비밀 하나 = 「앱키」, 따로 맞추는 단계 없음(멤버 2차 Task 4).
// 화면에 보이는 글(주석을 뺀 코드 안의 우리말)에 옛 이름 · 맞춤 말이 남지 않았는지 app/src 전체(시험 파일 제외)를 훑는다.
// 파일 · 함수 · 저장 이름(econSyncScope_v1 같은 것)은 영어라 걸리지 않는다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { kakaoText, STORAGE_NOTE, adminErrText } from './personal/members.ts'
import { keyChangeText, aiErrText } from './personal/remote.ts'
import { whyText } from './welcome.ts'
import { savedNote } from './alerts/v2.ts'

const SRC = fileURLToPath(new URL('..', import.meta.url))
const BANNED = ['입장 키', '보유 열쇠', '보유 암호', '평단가 동기화 암호', '마스터 키', '동기화 키', '예비 키', '동기화', '맞추기', '연결됨']

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap(d => {
    const p = join(dir, d.name)
    if (d.isDirectory()) return files(p)
    return /\.(ts|tsx)$/.test(d.name) && !/\.test\.ts$/.test(d.name) ? [p] : []
  })
}
/** 주석을 뺀 글 — 블록 주석(JSX 의 {/* *\/} 포함)과 줄 주석(앞이 공백 · 줄 처음인 // — https:// 는 남는다). */
const code = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/.*$/gm, '$1')

test('화면 글에 옛 이름 · 맞춤 말이 없다(입장 키 · 보유 열쇠 · 보유 암호 · 마스터 키 · 동기화 키 · 예비 키 · 동기화 · 맞추기 · 연결됨)', () => {
  const hits: string[] = []
  for (const f of files(SRC)) {
    const lines = code(readFileSync(f, 'utf8')).split('\n')
    lines.forEach((l, i) => { for (const w of BANNED) if (l.includes(w)) hits.push(`${f.slice(SRC.length)}:${i + 1} 「${w}」 ${l.trim().slice(0, 80)}`) })
  }
  assert.deepEqual(hits, [])
})

test('모듈이 내보내는 글(카톡 글 · 저장 안내 · 오류 글)도 「앱키」', () => {
  const texts = [
    kakaoText('ECOM-AAAA-BBBB-CCCC'), STORAGE_NOTE, adminErrText({ status: 401 }), adminErrText({ status: 403 }),
    keyChangeText({ status: 0 }), keyChangeText({ status: 401 }), keyChangeText({ status: 503 }), keyChangeText({ status: 400, error: 'weak_new_key' }),
    aiErrText({ status: 401, error: 'unauthorized' }), aiErrText({ status: 403, error: 'paused' }), aiErrText({ status: 503, error: 'sync_key_not_configured' }),
    whyText('paused'), whyText('lost'), savedNote({ on: false, at: null }, 1),
  ]
  for (const t of texts) for (const w of BANNED) assert.ok(!t.includes(w), `${w} — ${t}`)
  assert.match(kakaoText('ECOM-AAAA-BBBB-CCCC'), /앱키로 들어오세요: ECOM-AAAA-BBBB-CCCC/)
  assert.match(STORAGE_NOTE, /앱키/)
})

test('화면 자리: 입장 「앱키」 · 멤버 관리 「앱키 발급 · 앱키 다시 만들기 · 예비 앱키」 · 내 계정 「앱키 바꾸기」 — 보유 동기화 시트 · 범위 스위치는 없다', () => {
  const src = (p: string) => readFileSync(join(SRC, p), 'utf8')
  assert.match(src('screens/Welcome.tsx'), />앱키</)
  assert.match(src('screens/Welcome.tsx'), /앱키는 모임 운영자에게 받습니다/)
  for (const w of ['앱키 발급', '앱키 다시 만들기', '예비 앱키']) assert.ok(src('screens/Members.tsx').includes(w), w)
  assert.ok(src('components/personal/MyAccount.tsx').includes('앱키 바꾸기'))
  assert.equal(existsSync(join(SRC, 'components/personal/HoldSyncSheet.tsx')), false)
  for (const p of ['screens/My.tsx', 'components/personal/MyAccount.tsx', 'components/personal/DeviceLink.tsx', 'screens/Welcome.tsx', 'lib/personal/sync.ts']) {
    const s = code(src(p))
    for (const w of ['HoldSyncSheet', 'HoldScope', 'RestoreKey', 'AskBox', 'setScope', 'readScope', 'answerAsk']) assert.ok(!s.includes(w), `${p}: ${w}`)
  }
})
