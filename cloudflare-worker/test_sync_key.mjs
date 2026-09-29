// 동기화 키 자가 점검 — 기대 해시는 KV(사이트에서 바꾼 키) 우선, 없으면 시크릿.
// 바꾼 뒤 옛 키가 계속 통하거나, KV 오류 때 옛 시크릿으로 되돌아가면 실패한다.
//
// 실행: node cloudflare-worker/test_sync_key.mjs   (가짜 키만 쓴다)
import worker from './worker.js';
import { createHash } from 'crypto';

const sha = s => createHash('sha256').update(s).digest('hex');
const kv = new Map();
const env = {
  ALERTS_SYNC_KEY: 'fake-secret-for-test\n',   // 후행 개행 = wrangler secret put 붙여넣기 흔적
  ECON_PORTFOLIO: { get: async k => kv.get(k) ?? null, put: async (k, v) => { kv.set(k, v); } },
  AI_LIMITER: { limit: async () => ({ success: true }) },
};
const post = async (hash, body, e = env) => {
  const r = await worker.fetch(new Request('https://w.test/sync-key', {
    method: 'POST', headers: { 'content-type': 'application/json', 'X-Sync-Key-Hash': hash }, body: JSON.stringify(body),
  }), e, { waitUntil() {} });
  return r.status;
};

let fails = 0;
const check = (label, got, want) => {
  if (got === want) { console.log(`  OK   ${label}`); return; }
  fails++;
  console.log(`  FAIL ${label}: ${got} (기대 ${want})`);
};

const OLD = sha('fake-secret-for-test'), NEW = sha('a new long passphrase');
check('시크릿 해시로 확인', await post(OLD, {}), 200);
check('틀린 키', await post(sha('x'), {}), 401);
check('틀린 지금 키로 변경', await post(sha('x'), { newKeyHash: NEW }), 401);
check('빈 암호 해시 거부', await post(OLD, { newKeyHash: sha('') }), 400);
check('변경', await post(OLD, { newKeyHash: NEW }), 200);
check('변경 뒤 옛 키', await post(OLD, {}), 401);
check('변경 뒤 새 키', await post(NEW, {}), 200);
const broken = { ...env, ECON_PORTFOLIO: { get: async () => { throw new Error('kv down'); } } };
check('KV 오류 → 옛 시크릿으로 안 돌아감', await post(OLD, {}, broken), 503);
kv.clear();
check('KV 키 삭제 → 시크릿 복귀', await post(OLD, {}), 200);

if (fails) { console.log(`\n${fails}건 실패`); process.exit(1); }
console.log('\n전부 통과');
