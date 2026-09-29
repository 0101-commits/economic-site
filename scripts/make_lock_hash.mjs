// 페이지 잠금(투자 현황·설정) PIN → js/app4.js 의 LOCK 줄 생성기.
//   node scripts/make_lock_hash.mjs            (입력은 화면에 안 보인다, 두 번 묻는다)
//   echo 새PIN | node scripts/make_lock_hash.mjs   (파이프 입력도 된다 — 셸 기록에 남으니 비권장)
// 출력된 `var LOCK = {...};` 줄로 js/app4.js 의 `var LOCK = null;` 줄을 바꾸고 커밋·푸시한다.
// 결과는 공개 파일에 실리므로 PIN 을 다른 곳(평단가 동기화 암호 등)에 쓰지 말 것.
import { pbkdf2Sync, randomBytes } from 'node:crypto';
import { createInterface } from 'node:readline';

const ITER = 600000;   // js/app4.js 는 LOCK.iter 를 읽으므로 올려도 프런트 수정 불필요

const rl = createInterface({ input: process.stdin, output: process.stdout, terminal: !!process.stdin.isTTY });
rl._writeToOutput = () => {};   // 입력 에코 끄기(질문은 output 에 직접 쓴다)
const lines = rl[Symbol.asyncIterator]();
async function ask(q) {
  if (process.stdin.isTTY) rl.output.write(q);
  const { value } = await lines.next();
  if (process.stdin.isTTY) rl.output.write('\n');
  return (value || '').trim();
}

const pin = await ask('새 잠금 PIN: ');
if (process.stdin.isTTY && pin !== await ask('한 번 더: ')) { console.error('두 입력이 다릅니다.'); process.exit(1); }
rl.close();
if (pin.length < 4) { console.error('PIN 이 너무 짧습니다(4자 미만).'); process.exit(1); }
if (/^\d+$/.test(pin) && pin.length < 10) {
  console.error('※ 숫자만 ' + pin.length + '자리 PIN 은 공개된 해시로부터 GPU 로 수 분 안에 풀립니다(화면 가림막 용도로만 쓰세요).');
}
const salt = randomBytes(16).toString('hex');
const hash = pbkdf2Sync(pin, Buffer.from(salt, 'hex'), ITER, 32, 'sha256').toString('hex');
console.log(`var LOCK = { salt: '${salt}', iter: ${ITER}, hash: '${hash}' };`);
