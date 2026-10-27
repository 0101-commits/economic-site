// 사람 표 인증 자가 점검 — 공간 = uid, 멤버 AI 하루 30회, 멈춘 멤버 403, 멤버 키 바꾸기.
// 사람 표가 없으면 옛 방식(legacy) 그대로 — 같은 키 같은 칸. 가짜 키·가짜 AI·가짜 GitHub 만 쓴다.
// 실행: node cloudflare-worker/test_members.mjs
import worker from './worker.js';
import { createHash } from 'crypto';
import { migrateOwner, createUser, patchUser, normalizeEntryKey, listUsers, resolveUser, touchSeen, readSeen, _clearUserCache } from './users.js';

const sha = s => createHash('sha256').update(s).digest('hex');
const kv = new Map();
const KV = { get: async (k, t) => { const v = kv.get(k); return v == null ? null : (t === 'json' ? JSON.parse(v) : v); },
             put: async (k, v) => { kv.set(k, v); }, delete: async k => { kv.delete(k); } };
let aiCalls = 0;
const env = {
  ALERTS_SYNC_KEY: 'fake-secret-for-test', ECON_PORTFOLIO: KV, GH_DISPATCH_TOKEN: 'fake-token',
  AI_LIMITER: { limit: async () => ({ success: true }) },
  AI: { run: async () => { aiCalls++; return { response: '가짜 요약' }; } },
  VAPID_PUBLIC_KEY: 'BFakePublicKeyForTestOnly', PUSH_READ_KEY: 'fake-push-read-key',
};
const KEY = sha('fake-secret-for-test');
const h16 = KEY.slice(0, 16);

let ghPuts = 0, ghGets = 0;
const realFetch = globalThis.fetch;
const ghFile = { version: 1, updatedAt: '2026-10-01T00:00:00Z', settings: { enabled: true, frequency: 'daily' },
  alerts: [{ id: 'a1', type: 'price_above', symbol: '^KS11', name: 'KOSPI', market: 'KR', value: 2900, enabled: true }], tracking: null };
globalThis.fetch = async (url, init = {}) => {
  const u = String(url);
  if (u.startsWith('https://api.github.com/repos/') && u.includes('/contents/')) {
    if ((init.method || 'GET') === 'GET') ghGets++;
    if ((init.method || 'GET') === 'GET') return new Response(JSON.stringify({ sha: 'abc', content: Buffer.from(JSON.stringify(ghFile)).toString('base64') }), { status: 200 });
    ghPuts++;
    return new Response(JSON.stringify({ content: { sha: 'def' } }), { status: 200 });
  }
  return realFetch(url, init);
};

const call = async (method, path, { hash = KEY, body, headers = {} } = {}) => {
  const h = { ...headers };
  if (hash) h['X-Sync-Key-Hash'] = hash;
  if (body !== undefined) h['content-type'] = 'application/json';
  const r = await worker.fetch(new Request('https://w.test' + path, {
    method, headers: h, body: body !== undefined ? JSON.stringify(body) : undefined,
  }), env, { waitUntil() {} });
  let j = null;
  try { j = await r.clone().json(); } catch (_) {}
  return { status: r.status, j };
};
const post = (path, hash, body) => call('POST', path, { hash: null, body: { keyHash: hash, ...body } });
const enc = n => ({ alg: 'AES-256-GCM', kdf: 'PBKDF2-SHA256', iter: 1000, salt: 'c2FsdA==', iv: 'aXY=', ciphertext: 'Y3Q' + n });
const kstDay = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);

let fails = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${label}${ok ? '' : `: ${JSON.stringify(got)} (기대 ${JSON.stringify(want)})`}`);
  if (!ok) fails++;
};

console.log('legacy — 사람 표 없음');
check('PUT /prefs', (await call('PUT', '/prefs', { body: { watch: [{ id: '005930', kind: 'stock' }] } })).status, 200);
check('prefs:<h16> 에 저장', kv.has('prefs:' + h16), true);
check('틀린 키 401', (await call('GET', '/prefs', { hash: sha('x') })).status, 401);
check('POST /portfolio 보유', (await post('/portfolio', KEY, { encHoldings: enc(1) })).status, 200);
check('portfolio:encHoldings 에 저장', kv.has('portfolio:encHoldings'), true);
check('GET /portfolio 보유', (await call('GET', '/portfolio')).j.encHoldings.ciphertext, 'Y3Q1');
check('legacy /ai 200', (await post('/ai', KEY, { snapshot: { a: 1 } })).status, 200);
check('legacy 에는 user: 칸 없음', [...kv.keys()].some(k => k.startsWith('user:')), false);

console.log('마이그레이션 뒤 — 공간 = uid');
const m = await migrateOwner(env, KEY);
const U = m.uid;
check('옛 prefs 가 복사됨', kv.has('prefs:' + U), true);
check('GET /prefs 같은 내용', (await call('GET', '/prefs')).j.watch.length, 1);
check('PUT /prefs → prefs:<uid>', (await call('PUT', '/prefs', { body: { watch: [] } })).status, 200);
check('prefs:<uid> 갱신', JSON.parse(kv.get('prefs:' + U)).watch.length, 0);
check('옛 prefs:<h16> 는 그대로', JSON.parse(kv.get('prefs:' + h16)).watch.length, 1);
check('POST /portfolio 새 보유', (await post('/portfolio', KEY, { encHoldings: enc(2) })).status, 200);
check('hold:<uid> 에 저장', JSON.parse(kv.get('hold:' + U)).ciphertext, 'Y3Q2');
check('옛 portfolio:encHoldings 는 그대로', JSON.parse(kv.get('portfolio:encHoldings')).ciphertext, 'Y3Q1');
check('이전 판 hold:<uid>:prev:<날짜>', kv.has(`hold:${U}:prev:${kstDay}`), true);
check('GET /portfolio hold:<uid> 읽음', (await call('GET', '/portfolio')).j.encHoldings.ciphertext, 'Y3Q2');
check('틀린 키 401', (await call('GET', '/prefs', { hash: sha('x') })).status, 401);
check('CI 읽기 = 주인 공간', (await call('GET', '/prefs', { hash: null, headers: { 'X-Push-Read-Key': 'fake-push-read-key' } })).j.watch.length, 0);

console.log('멤버 A · B — 공간 분리');
const A = await createUser(env, { name: '갑' }), B = await createUser(env, { name: '을' });
const hA = sha(normalizeEntryKey(A.key)), hB = sha(normalizeEntryKey(B.key));
await call('PUT', '/prefs', { hash: hA, body: { watch: [{ id: '000660', kind: 'stock' }] } });
check('A 는 자기 것을 읽음', (await call('GET', '/prefs', { hash: hA })).j.watch.length, 1);
check('B 에겐 A 의 것이 안 보임', (await call('GET', '/prefs', { hash: hB })).j.watch.length, 0);
check('주인에게도 안 섞임', (await call('GET', '/prefs')).j.watch.length, 0);
check('A 보유 → hold:<uidA>', (await post('/portfolio', hA, { encHoldings: enc(9) })).status, 200);
check('hold:<uidA>', JSON.parse(kv.get('hold:' + A.user.uid)).ciphertext, 'Y3Q9');
const ga = await call('GET', '/portfolio', { hash: hA });
check('멤버 GET /portfolio 는 주인 알림을 안 받음', [ga.status, ga.j.alerts, ga.j.encHoldings.ciphertext], [200, [], 'Y3Q9']);
ghPuts = 0; ghGets = 0;
const gp = await post('/portfolio', hA, { encHoldings: enc(9), alerts: [{ id: 'z', type: 'price_above', symbol: 'X', name: 'X', market: 'KR', value: 1, enabled: true }], settings: { enabled: false }, tracking: { items: [] } });
check('멤버 POST 에 alerts·settings·tracking 이 와도 committed:false', [gp.status, gp.j.committed], [200, false]);
check('GitHub PUT 0회', ghPuts, 0);
const ga2 = await call('GET', '/portfolio', { hash: hA });
check('멤버 GET /portfolio alerts []', ga2.j.alerts, []);
check('멤버 GET 은 GitHub 읽기도 안 함', ghGets, 0);
check('주인 GET 은 GitHub 읽음', [(await call('GET', '/portfolio')).j.alerts.length, ghGets], [1, 1]);
check('형식 틀린 해시 401', (await call('GET', '/prefs', { hash: 'zz' })).status, 401);
check('멤버 /portfolio/test 403', (await post('/portfolio/test', hA, {})).status, 403);
check('멤버 푸시 공간 분리', (await call('GET', '/push/subscribe', { hash: hB })).j.count, 0);

console.log('멈춘 멤버');
await patchUser(env, B.user.uid, { status: 'paused' });
const pb = await call('GET', '/prefs', { hash: hB });
check('B 403 paused', [pb.status, pb.j], [403, { error: 'paused' }]);
check('멈춘 B /ai 403', (await post('/ai', hB, { snapshot: {} })).status, 403);
{
  // 주인이 멈춘 뒤에도 멤버의 뜨거운 경로(/ai · touchSeen)가 user 기록을 되살리지 않는다.
  const C = await createUser(env, { name: '병' }), hC = sha(normalizeEntryKey(C.key));
  _clearUserCache();
  const r1 = await resolveUser(env, hC, KEY);
  await patchUser(env, C.user.uid, { status: 'paused' });
  await touchSeen(env, r1.user, kstDay);
  const stale = { ...C.user };
  await touchSeen(env, stale, kstDay);
  check('멈춘 뒤 touchSeen 해도 paused 유지', (await KV.get('user:' + C.user.uid, 'json')).status, 'paused');
  check('seen:<uid> 에 접속일', await readSeen(env, C.user.uid), kstDay);
  const h = await call('GET', '/prefs', { hash: hC });
  check('멈춘 C 는 403', h.status, 403);
  await patchUser(env, C.user.uid, { status: 'active' });
  await post('/ai', hC, { snapshot: {} });
  await patchUser(env, C.user.uid, { status: 'paused' });
  await post('/ai', hC, { snapshot: {} });
  const rc = await KV.get('user:' + C.user.uid, 'json');
  check('/ai 를 거쳐도 user 기록은 paused · aiDay/aiCount 없음', [rc.status, 'aiDay' in rc, 'aiCount' in rc, 'lastSeenDay' in rc], ['paused', false, false, false]);
}

console.log('AI 하루 30회');
aiCalls = 0;
let last;
for (let i = 0; i < 30; i++) last = await post('/ai', hA, { snapshot: { n: i } });
check('멤버 30번째 200', last.status, 200);
const over = await post('/ai', hA, { snapshot: { n: 31 } });
check('멤버 31번째 429 ai_quota', [over.status, over.j.error], [429, 'ai_quota']);
check('31번째엔 모델을 안 부름', aiCalls, 30);
check('aiq:<uid> 에 세어 둠', JSON.parse(kv.get('aiq:' + A.user.uid)), { day: kstDay, count: 30 });
check('user 기록엔 안 씀', (await listUsers(env)).find(u => u.uid === A.user.uid).aiCount, undefined);
let own; for (let i = 0; i < 31; i++) own = await post('/ai', KEY, { snapshot: { n: i } });
check('주인 31번째 통과', own.status, 200);

console.log('멤버 키 바꾸기');
check('확인만 200', (await call('POST', '/sync-key', { hash: hA })).status, 200);
const newKey = 'my-new-pass-1234';
check('짧은 새 키 400', (await call('POST', '/sync-key', { hash: null, body: { currentKey: A.key, newKey: 'short' } })).j.error, 'weak_new_key');
check('틀린 현재 키 401', (await call('POST', '/sync-key', { hash: null, body: { currentKey: 'ECOM-AAAA-AAAA-AAAA', newKey } })).status, 401);
check('키 바꾸기 200', (await call('POST', '/sync-key', { hash: null, body: { currentKey: ' ' + A.key.toLowerCase() + ' ', newKey } })).j, { ok: true, changed: true });
check('옛 키 401', (await call('GET', '/prefs', { hash: hA })).status, 401);
check('새 키로 같은 prefs', (await call('GET', '/prefs', { hash: sha(newKey) })).j.watch.length, 1);
check('ukey 교체', [kv.has('ukey:' + hA), kv.get('ukey:' + sha(newKey)) === A.user.uid], [false, true]);

console.log('index 가 사라지면 닫힌 채 실패');
kv.delete('users:index');
_clearUserCache();
const gone = await call('GET', '/prefs');
check('503 users_index_missing', [gone.status, gone.j.error], [503, 'users_index_missing']);

if (fails) { console.log(`\n${fails}건 실패`); process.exit(1); }
console.log('\n전부 통과');
