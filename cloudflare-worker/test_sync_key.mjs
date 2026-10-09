// 동기화 키 자가 점검 — 기대 해시는 KV(사이트에서 바꾼 키) 우선, 없으면 시크릿.
// 바꾼 뒤 옛 키가 계속 통하거나, KV 오류 때 옛 시크릿으로 되돌아가거나, 해시만으로 키가 바뀌면 실패한다(B5).
// 바꾸면 옛 공간의 /prefs 문서를 새 공간으로 옮긴다(새 쪽이 비어 있을 때만) — 발송기가 기본 설정으로 돌지 않게.
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
  const headers = { 'content-type': 'application/json' };
  if (hash) headers['X-Sync-Key-Hash'] = hash;
  const r = await worker.fetch(new Request('https://w.test/sync-key', {
    method: 'POST', headers, body: JSON.stringify(body),
  }), e, { waitUntil() {} });
  let j = null;
  try { j = await r.json(); } catch (_) {}
  return [r.status, j && (j.error || (j.changed ? 'changed' : 'ok'))];
};

let fails = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) { console.log(`  OK   ${label}`); return; }
  fails++;
  console.log(`  FAIL ${label}: ${JSON.stringify(got)} (기대 ${JSON.stringify(want)})`);
};

const CUR = 'fake-secret-for-test', NEWK = 'a new long passphrase';
const OLD = sha(CUR), NEW = sha(NEWK);
console.log('확인만(헤더 해시)');
check('시크릿 해시로 확인', await post(OLD, {}), [200, 'ok']);
check('틀린 키', await post(sha('x'), {}), [401, 'unauthorized']);
check('헤더 없음', await post('', {}), [401, 'unauthorized']);
check('currentKey 만 있으면 확인만(헤더로)', await post(OLD, { currentKey: 'x' }), [200, 'ok']);

console.log('옛 계약(newKeyHash) 거부');
check('맞는 헤더 + newKeyHash → use_new_key', await post(OLD, { newKeyHash: NEW }), [400, 'use_new_key']);
check('newKeyHash 와 원문을 같이 보내도 거부', await post(OLD, { newKeyHash: NEW, currentKey: CUR, newKey: NEWK }), [400, 'use_new_key']);
check('옛 계약으로 KV 안 바뀜', kv.has('auth:syncKeyHash'), false);

console.log('바꾸기(원문)');
check('해시만으로는 못 바꿈(헤더 맞아도 currentKey 없음)', await post(OLD, { newKey: NEWK }), [401, 'unauthorized']);
check('currentKey 에 해시를 넣어도 못 바꿈', await post('', { currentKey: OLD, newKey: NEWK }), [401, 'unauthorized']);
check('틀린 currentKey', await post('', { currentKey: 'wrong key', newKey: NEWK }), [401, 'unauthorized']);
check('12자 미만 새 키', await post('', { currentKey: CUR, newKey: ' short key  ' }), [400, 'weak_new_key']);
check('지금 키와 같은 새 키', await post('', { currentKey: CUR, newKey: '  ' + CUR + ' ' }), [400, 'weak_new_key']);
check('문자열 아닌 newKey', await post('', { currentKey: CUR, newKey: 123456789012345 }), [400, 'weak_new_key']);
check('거부된 시도로 KV 안 바뀜', kv.has('auth:syncKeyHash'), false);
const DOC = JSON.stringify({ v: 2, updatedAt: '2026-10-07T00:00:00.000Z', watch: [{ id: 'kospi' }] });
kv.set('prefs:' + OLD.slice(0, 16), DOC);
kv.set('push:' + OLD.slice(0, 16), '[{"endpoint":"https://fcm.googleapis.com/x"}]');
check('변경(앞뒤 공백은 잘라 해시)', await post('', { currentKey: ' ' + CUR + '\n', newKey: ' ' + NEWK + ' ' }), [200, 'changed']);
check('KV = SHA-256(newKey.trim())', kv.get('auth:syncKeyHash'), NEW);
check('/prefs 문서가 새 공간으로 옮겨짐 · 옛 공간은 그대로', [kv.get('prefs:' + NEW.slice(0, 16)), kv.get('prefs:' + OLD.slice(0, 16))], [DOC, DOC]);
check('구독은 옮기지 않음', kv.has('push:' + NEW.slice(0, 16)), false);
check('변경 뒤 옛 키', await post(OLD, {}), [401, 'unauthorized']);
check('변경 뒤 새 키', await post(NEW, {}), [200, 'ok']);
check('변경 뒤 옛 원문으로 다시 바꾸기', await post('', { currentKey: CUR, newKey: 'yet another passphrase' }), [401, 'unauthorized']);
const THIRD = 'third long passphrase', MINE = JSON.stringify({ v: 2, updatedAt: 'x' });
kv.set('prefs:' + sha(THIRD).slice(0, 16), MINE);
check('새 공간에 문서가 있으면', await post('', { currentKey: NEWK, newKey: THIRD }), [200, 'changed']);
check('덮지 않음', kv.get('prefs:' + sha(THIRD).slice(0, 16)), MINE);
kv.set('auth:syncKeyHash', NEW);

console.log('KV');
const broken = { ...env, ECON_PORTFOLIO: { get: async () => { throw new Error('kv down'); } } };
check('KV 오류 → 옛 시크릿으로 안 돌아감', await post(OLD, {}, broken), [503, 'kv_read_failed']);
kv.clear();
check('KV 키 삭제 → 시크릿 복귀', await post(OLD, {}), [200, 'ok']);

if (fails) { console.log(`\n${fails}건 실패`); process.exit(1); }
console.log('\n전부 통과');
