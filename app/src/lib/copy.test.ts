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

// 멤버 2차 Task 6 — 용어 정리: 화면에 보이는 글에 개발 · 영어식 말이 남지 않았는지(표는 task-6-brief.md · CLAUDE.md 「말 사전」).
const BANNED_TERMS = ['서버', '사본', '맡김', '맡겨', '덩어리', '해시', '구독', '웹 푸시', 'Yahoo', 'what-if', '스냅샷', '원장', '현행', '이전 화면', '옛 키', '꾸러미',
  '기준선 없음', '연환산', '무위험', '시간가중', '내 데이터', '데이터 상태', '이 기기 데이터']
/**
 * 한 줄에서 화면에 보이는 글만 남긴다 — console 호출 자체(괄호 한 겹 안까지)와, 검색 열쇠 묶음(SearchOverlay 의
 * ['kr', '국내', '찾기 열쇠 글'] 꼴의 셋째 칸 — 사람이 보지 않는 검색용 낱말)을 뺀다. 같은 줄의 나머지 글은 그대로 검사한다.
 */
export function visibleLine(l: string, searchKeys = false): string {
  let v = l.replace(/console\.(warn|error|log)\((?:[^()]|\([^()]*\))*\)/g, '')
  if (searchKeys) v = v.replace(/(\['[a-z]+', '[^']*', )'[^']*'\]/g, '$1]')
  return v
}
/** 한 줄에 걸린 금지 낱말들. */
export const termHits = (l: string, searchKeys = false) => BANNED_TERMS.filter(w => visibleLine(l, searchKeys).includes(w))

test('화면 글에 개발 · 영어식 말이 없다(서버 · 스냅샷 · 원장 · 현행 · 구독 · what-if · 꾸러미 · 연환산 …)', () => {
  const hits: string[] = []
  for (const f of files(SRC)) {
    const lines = code(readFileSync(f, 'utf8')).split('\n')
    const sk = /SearchOverlay\.tsx$/.test(f)
    lines.forEach((l, i) => { for (const w of termHits(l, sk)) hits.push(`${f.slice(SRC.length)}:${i + 1} 「${w}」 ${l.trim().slice(0, 80)}`) })
  }
  assert.deepEqual(hits, [])
})

test('용어 검사 자체: 배열 끝 글 · console 과 같은 줄의 화면 글도 잡고, console 글 · 검색 열쇠만 뺀다', () => {
  assert.deepEqual(termHits(`const msgs = ['정상', '서버 점검 중']`), ['서버'])
  assert.deepEqual(termHits(`console.warn(e); setMsg('서버 오류')`), ['서버'])
  assert.deepEqual(termHits(`console.warn('서버 응답', f(x))`), [])
  assert.deepEqual(termHits(`['whatif', '만약에', '시나리오 whatif what-if'], ['chain', '사슬', '연결 고리']`, true), [])
  assert.deepEqual(termHits(`['whatif', '만약에', '시나리오 whatif what-if']`), ['what-if'])
})

test('금융 용어는 쉬운 이름 + 괄호 원어 · 풀이(title)가 붙는다', () => {
  const my = readFileSync(join(SRC, 'screens/My.tsx'), 'utf8')
  assert.match(my, /위험 대비 수익\(샤프\)/)
  assert.match(my, /손실 대비 수익\(소르티노\)/)
  assert.match(my, /title="1년 기준으로 환산한 값입니다/)
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
