// 스냅샷 · 마스터 암호 덩어리 경로 자가 점검 — GET/PUT /snaps, GET /hold/owner, GET·PUT /snaps/owner.
// 가짜 KV · 가짜 키만 쓴다. 실행: node cloudflare-worker/test_snaps.mjs
import worker from './worker.js';
import { createHash } from 'crypto';
import { migrateOwner, createUser, normalizeEntryKey, deleteUser } from './users.js';

const sha = s => createHash('sha256').update(s).digest('hex');
const kv = new Map();
const KV = { get: async (k, t) => { const v = kv.get(k); return v == null ? null : (t === 'json' ? JSON.parse(v) : v); },
             put: async (k, v) => { kv.set(k, v); }, delete: async k => { kv.delete(k); } };
const env = { ALERTS_SYNC_KEY: 'fake-secret-for-test', ECON_PORTFOLIO: KV, AI_LIMITER: { limit: async () => ({ success: true }) },
  PUSH_READ_KEY: 'fake-read', PUSH_WRITE_KEY: 'fake-write' };
const KEY = sha('fake-secret-for-test');
const RK = { 'X-Push-Read-Key': 'fake-read' }, WK = { 'X-Push-Write-Key': 'fake-write' };
const call = async (method, path, { hash = KEY, body, headers = {}, raw } = {}) => {
  const h = { ...headers };
  if (hash) h['X-Sync-Key-Hash'] = hash;
  if (body !== undefined || raw !== undefined) h['content-type'] = 'application/json';
  const r = await worker.fetch(new Request('https://w.test' + path, { method, headers: h,
    body: raw !== undefined ? raw : (body !== undefined ? JSON.stringify(body) : undefined) }), env, { waitUntil() {} });
  let j = null; try { j = await r.clone().json(); } catch (_) {}
  return { status: r.status, j, r };
};
const enc = n => ({ alg: 'AES-256-GCM', kdf: 'PBKDF2-SHA256', iter: 1000, salt: 'c2FsdA==', iv: 'aXY=', ciphertext: 'Y3Q' + n });
let fails = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${label}${ok ? '' : `: ${JSON.stringify(got)} (기대 ${JSON.stringify(want)})`}`);
  if (!ok) fails++;
};

console.log('legacy(사람 표 없음) — 주인 옛 칸');
kv.set('portfolio:encHoldings', JSON.stringify(enc('H0')));
check('GET /hold/owner 옛 칸', (await call('GET', '/hold/owner', { hash: null, headers: RK })).j, { ok: true, encHoldings: enc('H0') });
check('PUT /snaps 200', (await call('PUT', '/snaps', { body: { encSnaps: enc('S0') } })).status, 200);
check('snaps:<h16> 에 저장', kv.has('snaps:' + KEY.slice(0, 16)), true);
check('GET /snaps/owner 같은 칸', (await call('GET', '/snaps/owner', { hash: null, headers: RK })).j.encSnaps.ciphertext, 'Y3QS0');
check('legacy PUT /snaps/owner', (await call('PUT', '/snaps/owner', { hash: null, headers: WK, body: { encSnaps: enc('S1') } })).status, 200);
check('legacy GET /snaps 로 보임', (await call('GET', '/snaps')).j.encSnaps.ciphertext, 'Y3QS1');

console.log('마이그레이션 뒤 — 공간 = uid');
const U = (await migrateOwner(env, KEY)).uid;
kv.set('hold:' + U, JSON.stringify(enc('H1')));
check('GET /hold/owner = hold:<uid>', (await call('GET', '/hold/owner', { hash: null, headers: RK })).j.encHoldings.ciphertext, 'Y3QH1');
check('빈 snaps:<uid> → null', (await call('GET', '/snaps')).j, { ok: true, encSnaps: null });
check('PUT /snaps → snaps:<uid>', (await call('PUT', '/snaps', { body: { encSnaps: enc('S2') } })).status, 200);
check('snaps:<uid> 내용', JSON.parse(kv.get('snaps:' + U)).ciphertext, 'Y3QS2');
check('덩어리만 보내도 받음', (await call('PUT', '/snaps', { body: enc('S3') })).status, 200);
check('GET /snaps/owner', (await call('GET', '/snaps/owner', { hash: null, headers: RK })).j.encSnaps.ciphertext, 'Y3QS3');
check('PUT /snaps/owner → snaps:<uid>', [(await call('PUT', '/snaps/owner', { hash: null, headers: WK, body: { encSnaps: enc('S4') } })).status, JSON.parse(kv.get('snaps:' + U)).ciphertext], [200, 'Y3QS4']);

console.log('권한');
check('읽기 키로 PUT /snaps/owner 403', (await call('PUT', '/snaps/owner', { hash: null, headers: RK, body: { encSnaps: enc('X') } })).status, 403);
check('키 없이 PUT /snaps/owner 403', (await call('PUT', '/snaps/owner', { hash: null, body: { encSnaps: enc('X') } })).status, 403);
check('틀린 쓰기 키 403', (await call('PUT', '/snaps/owner', { hash: null, headers: { 'X-Push-Write-Key': 'nope' }, body: { encSnaps: enc('X') } })).status, 403);
check('쓰기 키로는 GET 못 함 401', (await call('GET', '/snaps/owner', { hash: null, headers: WK })).status, 401);
check('틀린 읽기 키 401', [(await call('GET', '/hold/owner', { hash: null, headers: { 'X-Push-Read-Key': 'nope' } })).status, (await call('GET', '/snaps/owner', { hash: null })).status], [401, 401]);
check('동기화 키 해시로 /snaps/owner 안 됨', (await call('GET', '/snaps/owner')).status, 401);
check('/hold/owner PUT 405', (await call('PUT', '/hold/owner', { hash: null, headers: WK, body: { encSnaps: enc('X') } })).status, 405);
check('/snaps/owner 가 바뀌지 않음', JSON.parse(kv.get('snaps:' + U)).ciphertext, 'Y3QS4');
const saveW = env.PUSH_WRITE_KEY; delete env.PUSH_WRITE_KEY;
check('쓰기 시크릿 없으면 503', (await call('PUT', '/snaps/owner', { hash: null, headers: WK, body: { encSnaps: enc('X') } })).status, 503);
env.PUSH_WRITE_KEY = saveW;
check('브라우저 /snaps 키 없음 401', (await call('GET', '/snaps', { hash: null })).status, 401);
check('브라우저 /snaps 틀린 키 401', (await call('GET', '/snaps', { hash: sha('x') })).status, 401);

console.log('멤버 공간 분리');
const A = await createUser(env, { name: '갑' }), B = await createUser(env, { name: '을' });
const hA = sha(normalizeEntryKey(A.key)), hB = sha(normalizeEntryKey(B.key));
check('A PUT /snaps', (await call('PUT', '/snaps', { hash: hA, body: { encSnaps: enc('SA') } })).status, 200);
check('A 는 자기 것을 읽음', (await call('GET', '/snaps', { hash: hA })).j.encSnaps.ciphertext, 'Y3QSA');
check('B 는 A 것을 못 봄', (await call('GET', '/snaps', { hash: hB })).j.encSnaps, null);
check('주인 것도 안 섞임', (await call('GET', '/snaps')).j.encSnaps.ciphertext, 'Y3QS4');
check('/snaps/owner 는 주인 것', (await call('GET', '/snaps/owner', { hash: null, headers: RK })).j.encSnaps.ciphertext, 'Y3QS4');
check('멤버가 /snaps/owner 에 자기 키로 PUT 못 함', (await call('PUT', '/snaps/owner', { hash: hA, body: { encSnaps: enc('X') } })).status, 403);
check('멤버가 /hold/owner 못 읽음', (await call('GET', '/hold/owner', { hash: hA })).status, 401);

console.log('찌꺼기 거절');
const bad = async b => (await call('PUT', '/snaps', { body: b })).status;
check('빈 본문', await bad({}), 400);
check('알고리즘 틀림', await bad({ encSnaps: { ...enc(1), alg: 'AES-128-CBC' } }), 400);
check('kdf 틀림', await bad({ encSnaps: { ...enc(1), kdf: 'none' } }), 400);
check('iter 범위 밖', [await bad({ encSnaps: { ...enc(1), iter: 0 } }), await bad({ encSnaps: { ...enc(1), iter: 3000000 } })], [400, 400]);
check('base64 아님', await bad({ encSnaps: { ...enc(1), ciphertext: '<script>' } }), 400);
check('필드 빠짐', await bad({ encSnaps: { alg: 'AES-256-GCM', kdf: 'PBKDF2-SHA256', iter: 10, salt: 'YQ==' } }), 400);
check('문자열 덩어리', await bad({ encSnaps: 'plain' }), 400);
check('깨진 JSON', (await call('PUT', '/snaps', { raw: '{nope' })).status, 400);
check('너무 큼 413', (await call('PUT', '/snaps', { body: { encSnaps: { ...enc(1), ciphertext: 'A'.repeat(140000) } } })).status, 413);
check('owner PUT 도 거절', (await call('PUT', '/snaps/owner', { hash: null, headers: WK, body: { encSnaps: { ...enc(1), iv: '' } } })).status, 400);
const dirty = await call('PUT', '/snaps', { hash: hA, body: { encSnaps: { ...enc('SA2'), extra: '<b>x</b>', note: 'amount 1000' } } });
check('여분 필드는 버리고 저장', [dirty.status, Object.keys(JSON.parse(kv.get('snaps:' + A.user.uid))).sort()], [200, ['alg', 'ciphertext', 'iter', 'iv', 'kdf', 'salt']]);
check('거절된 뒤에도 주인 칸 그대로', JSON.parse(kv.get('snaps:' + U)).ciphertext, 'Y3QS4');

console.log('CORS · 메서드');
const op = await worker.fetch(new Request('https://w.test/snaps', { method: 'OPTIONS', headers: { Origin: 'https://0101-commits.github.io' } }), env, {});
check('OPTIONS /snaps 204 + PUT 허용', [op.status, /PUT/.test(op.headers.get('Access-Control-Allow-Methods') || '')], [204, true]);
check('POST /snaps 405', (await call('POST', '/snaps', { body: {} })).status, 405);
check('owner 경로엔 CORS 헤더 없음', (await call('GET', '/snaps/owner', { hash: null, headers: RK })).r.headers.get('Access-Control-Allow-Origin'), null);

console.log('사람 삭제');
kv.set('hold:' + A.user.uid, JSON.stringify(enc('HA')));
check('삭제 전 snaps:<uidA> 있음', kv.has('snaps:' + A.user.uid), true);
check('deleteUser', (await deleteUser(env, A.user.uid)).ok, true);
check('snaps:<uidA> · hold:<uidA> 지워짐', [kv.has('snaps:' + A.user.uid), kv.has('hold:' + A.user.uid)], [false, false]);
check('남의 snaps 는 그대로', [kv.has('snaps:' + U), JSON.parse(kv.get('snaps:' + U)).ciphertext], [true, 'Y3QS4']);

console.log('730건 크기 덩어리');
const big = { ...enc('BIG'), ciphertext: 'A'.repeat(62000) };   // ~46KB 평문의 base64 ≈ 61K — 보유 한도(60000) 초과
check('PUT /snaps 62000자 200', (await call('PUT', '/snaps', { body: { encSnaps: big } })).status, 200);
check('GET /snaps 그대로 돌려줌', (await call('GET', '/snaps')).j.encSnaps.ciphertext.length, 62000);
check('PUT /snaps/owner 62000자 200', (await call('PUT', '/snaps/owner', { hash: null, headers: WK, body: { encSnaps: big } })).status, 200);
check('GET /snaps/owner 그대로', (await call('GET', '/snaps/owner', { hash: null, headers: RK })).j.encSnaps.ciphertext.length, 62000);
kv.set('hold:' + U, JSON.stringify(big));
check('GET /hold/owner 도 60000자 한도', (await call('GET', '/hold/owner', { hash: null, headers: RK })).j.encHoldings, null);
check('상한 120000자는 통과', (await call('PUT', '/snaps', { body: { encSnaps: { ...enc(1), ciphertext: 'A'.repeat(120000) } } })).status, 200);
check('120001자는 400', (await call('PUT', '/snaps', { body: { encSnaps: { ...enc(1), ciphertext: 'A'.repeat(120001) } } })).status, 400);


if (fails) { console.log(`\n${fails}건 실패`); process.exit(1); }
console.log('\n전부 통과');
