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

console.log('새 경로 — /me · /admin/* · CI 복수 읽기 · /fired');
{
  const hM = sha(newKey); // 멤버 A (키를 바꾼 뒤)
  const RK = { 'X-Push-Read-Key': 'fake-push-read-key' };
  const ownerCall = (method, path, body) => call(method, path, { body });
  const m403 = await call('GET', '/admin/users', { hash: hM });
  check('멤버 /admin/users 403 owner_only', [m403.status, m403.j], [403, { error: 'owner_only' }]);
  check('멤버 /admin/users 생성 403', (await call('POST', '/admin/users', { hash: hM, body: { name: 'x' } })).status, 403);
  check('키 없이 /admin/users 401', (await call('GET', '/admin/users', { hash: null })).status, 401);
  check('주인 /me', (await call('GET', '/me')).j, { uid: U, name: '마스터', role: 'owner', viaBackup: false });
  check('멤버 /me', (await call('GET', '/me', { hash: hM })).j, { uid: A.user.uid, name: '갑', role: 'member', viaBackup: false });
  const cr = await ownerCall('POST', '/admin/users', { name: ' 정 ' });
  check('생성 200 · 이름 다듬음 · key 모양', [cr.status, cr.j.user.name, /^ECOM-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(cr.j.key)], [200, '정', true]);
  check('생성 응답 user 에 keyHash 없음', JSON.stringify(cr.j.user).includes('keyHash'), false);
  check('이름 빈 문자 400', (await ownerCall('POST', '/admin/users', { name: '  ' })).status, 400);
  check('이름 21자 400', (await ownerCall('POST', '/admin/users', { name: 'a'.repeat(21) })).status, 400);
  const lu = await ownerCall('GET', '/admin/users');
  check('목록에 keyHash·key 문자열 없음', /keyHash|backupKeyHash|"key"/.test(JSON.stringify(lu.j)), false);
  const rowJ = lu.j.users.find(u => u.uid === cr.j.user.uid);
  check('목록 행 모양', [Object.keys(rowJ).sort(), rowJ.pushCount, rowJ.role, rowJ.status], [['lastSeenDay', 'name', 'pushCount', 'role', 'status', 'uid'], 0, 'member', 'active']);
  kv.set('seen:' + cr.j.user.uid, kstDay); kv.set('push:' + cr.j.user.uid, JSON.stringify([{ endpoint: 'e1' }, { endpoint: 'e2' }]));
  const row2 = (await ownerCall('GET', '/admin/users')).j.users.find(u => u.uid === cr.j.user.uid);
  check('lastSeenDay 는 seen:<uid>, pushCount 는 push:<uid>', [row2.lastSeenDay, row2.pushCount], [kstDay, 2]);
  const nuid = cr.j.user.uid, nh = sha(normalizeEntryKey(cr.j.key));
  check('PATCH 이름', (await ownerCall('PATCH', '/admin/users/' + nuid, { name: '정2' })).j.user.name, '정2');
  check('PATCH 이름 빈 값 400', (await ownerCall('PATCH', '/admin/users/' + nuid, { name: '' })).status, 400);
  check('PATCH 멈춤 → 그 사람 403', [(await ownerCall('PATCH', '/admin/users/' + nuid, { status: 'paused' })).status, (await call('GET', '/me', { hash: nh })).status], [200, 403]);
  check('없는 uid PATCH 404', (await ownerCall('PATCH', '/admin/users/zzzz', { name: 'q' })).status, 404);
  check('주인 멈춤 금지 403', (await ownerCall('PATCH', '/admin/users/' + U, { status: 'paused' })).status, 403);
  await ownerCall('PATCH', '/admin/users/' + nuid, { status: 'active' });
  const rk = await ownerCall('POST', '/admin/users/' + nuid + '/rekey');
  check('rekey 새 key · 옛 키 401', [/^ECOM-/.test(rk.j.key), (await call('GET', '/me', { hash: nh })).status], [true, 401]);
  check('rekey 는 그 사람 폰 알림 구독(push:<uid>)을 지움', kv.has('push:' + nuid), false);
  kv.set('ukey:' + nh, nuid); _clearUserCache();   // 옛 ukey: 지우기가 실패해 남았다고 치고
  check('남은 옛 ukey: 로 읽기 → 401', [(await call('GET', '/me', { hash: nh })).status, (await call('GET', '/prefs', { hash: nh })).status, (await call('GET', '/fired', { hash: nh })).status], [401, 401, 401]);
  kv.delete('ukey:' + nh); _clearUserCache();
  check('새 키 /me 200', (await call('GET', '/me', { hash: sha(normalizeEntryKey(rk.j.key)) })).status, 200);
  const bk = await ownerCall('POST', '/admin/backup-key');
  check('예비 키로 /me viaBackup', (await call('GET', '/me', { hash: sha(normalizeEntryKey(bk.j.key)) })).j.viaBackup, true);
  check('멤버 DELETE 403', (await call('DELETE', '/admin/users/' + nuid, { hash: hM })).status, 403);
  check('DELETE 200', (await ownerCall('DELETE', '/admin/users/' + nuid)).j, { ok: true });
  check('삭제 뒤 목록에 없음', (await ownerCall('GET', '/admin/users')).j.users.some(u => u.uid === nuid), false);
  check('주인 DELETE 403', (await ownerCall('DELETE', '/admin/users/' + U)).status, 403);

  const pre = await worker.fetch(new Request('https://w.test/admin/users/abc', { method: 'OPTIONS', headers: { Origin: 'https://ecom-terminal.pages.dev', 'Access-Control-Request-Method': 'PATCH' } }), env, {});
  check('OPTIONS /admin/users/abc 204 + PATCH', [pre.status, pre.headers.get('Access-Control-Allow-Methods').includes('PATCH')], [204, true]);
  const pre2 = await worker.fetch(new Request('https://w.test/me', { method: 'OPTIONS', headers: { Origin: 'https://ecom-terminal.pages.dev' } }), env, {});
  check('OPTIONS /me 204', pre2.status, 204);
  const bad = await call('GET', '/me', { headers: { Origin: 'https://evil.test' } });
  check('나쁜 출처 /me 403', bad.status, 403);

  console.log('  마이그레이션 호출 · 복수 읽기');
  const rawPost = (path, headers, body) => call('POST', path, { hash: null, headers, body });
  check('migrate 머리만(본문 keyHash 없음) 401', (await rawPost('/admin/migrate', RK, {})).status, 401);
  check('migrate 본문만(머리 없음) 401', (await rawPost('/admin/migrate', {}, { keyHash: KEY })).status, 401);
  check('migrate 머리 틀림 401', (await rawPost('/admin/migrate', { 'X-Push-Read-Key': 'nope' }, { keyHash: KEY })).status, 401);
  check('migrate 본문 틀림 401', (await rawPost('/admin/migrate', RK, { keyHash: sha('x') })).status, 401);
  check('migrate 둘 다 맞음 → 이미 이전됨', (await rawPost('/admin/migrate', RK, { keyHash: KEY })).j, { uid: U, created: false });

  const pa = await call('GET', '/prefs/all', { hash: null, headers: RK });
  check('/prefs/all active 만 (멈춘 B 제외)', pa.j.users.map(u => u.uid).sort(), [U, A.user.uid, ...(await listUsers(env)).filter(u => u.status === 'active' && ![U, A.user.uid].includes(u.uid)).map(u => u.uid)].sort());
  check('/prefs/all 모양', [pa.j.users.find(u => u.uid === A.user.uid).role, pa.j.users.find(u => u.uid === A.user.uid).prefs.watch.length], ['member', 1]);
  check('/prefs/all 읽기 키 없으면 401', (await call('GET', '/prefs/all', { hash: null })).status, 401);
  check('/prefs/all 틀린 키 401', (await call('GET', '/prefs/all', { hash: null, headers: { 'X-Push-Read-Key': 'bad' } })).status, 401);
  kv.set('push:' + A.user.uid, JSON.stringify([{ endpoint: 'https://p/1', keys: {} }, { endpoint: 'https://p/2', keys: {} }]));
  const ps = await call('GET', '/push/subscriptions/all', { hash: null, headers: RK });
  const psA = ps.j.users.find(u => u.uid === A.user.uid);
  check('/push/subscriptions/all 모양 · 멈춘 B 제외', [psA.role, psA.subs.length, 'quiet' in psA, ps.j.users.some(u => u.uid === B.user.uid)], ['member', 2, true, false]);
  const prune = await call('PUT', '/push/prune', { hash: null, headers: RK, body: { uid: A.user.uid, endpoints: ['https://p/1'] } });
  check('prune uid 지정', [prune.j.removed, prune.j.count, JSON.parse(kv.get('push:' + A.user.uid)).length], [1, 1, 1]);
  check('prune 모르는 uid 404', (await call('PUT', '/push/prune', { hash: null, headers: RK, body: { uid: 'nobody0', endpoints: [] } })).status, 404);
  check('prune uid 없으면 주인 칸(옛 호환)', (await call('PUT', '/push/prune', { hash: null, headers: RK, body: { endpoints: ['x'] } })).j.removed, 0);
  const one = (await call('GET', '/push/subscriptions', { hash: null, headers: RK })).j;
  check('단수 /push/subscriptions 는 주인 칸 · uid = 주인', [Array.isArray(one.subs), one.uid], [true, U]);

  console.log('  /fired');
  const WK = { 'X-Push-Write-Key': 'fake-push-write-key' };
  const fcall = (headers, body) => call('POST', '/fired', { hash: null, headers, body });
  check('PUSH_WRITE_KEY 없으면 503', (await fcall(WK, { uid: U, item: { n: 0 } })).j, { error: 'push_write_not_configured' });
  env.PUSH_WRITE_KEY = 'fake-push-write-key';
  check('잘못된 write key 403', (await fcall({ 'X-Push-Write-Key': 'bad' }, { uid: U, item: { n: 0 } })).status, 403);
  check('write key 없음 403', (await fcall({}, { uid: U, item: { n: 0 } })).status, 403);
  check('모르는 uid 404', (await fcall(WK, { uid: 'nobody0', item: { n: 0 } })).status, 404);
  check('item 객체 아님 400', (await fcall(WK, { uid: U, item: 'x' })).status, 400);
  check('item 2KB 초과 413', (await fcall(WK, { uid: U, item: { t: 'x'.repeat(3000) } })).status, 413);
  for (let i = 1; i <= 51; i++) await fcall(WK, { uid: U, item: { n: i } });
  const fl = await call('GET', '/fired');
  check('51번 쓰면 50건 · 최신이 앞', [fl.j.items.length, fl.j.items[0].n, fl.j.items[49].n], [50, 51, 2]);
  check('멤버 GET /fired 는 자기 칸(비어 있음)', (await call('GET', '/fired', { hash: hM })).j, { items: [] });

  console.log('  보강 — 캐시된 인증으로 쓰기 · 권한 상승 · 잘못된 uid');
  {
    // 사람 표를 날것 KV 로 고쳐 users.js 캐시를 비우지 않는다 = 다른 isolate 의 낡은 캐시를 흉내.
    const D = await createUser(env, { name: '정' }), hD = sha(normalizeEntryKey(D.key));
    const E = await createUser(env, { name: '무' }), hE = sha(normalizeEntryKey(E.key));
    const F = await createUser(env, { name: '기' }), hF = sha(normalizeEntryKey(F.key));
    for (const h of [hD, hE, hF]) await call('GET', '/prefs', { hash: h }); // 캐시 데우기
    const putP = h => call('PUT', '/prefs', { hash: h, body: { watch: [{ id: '005930', kind: 'stock' }] } });
    kv.delete('user:' + D.user.uid);
    const rE = JSON.parse(kv.get('user:' + E.user.uid)); rE.status = 'paused'; kv.set('user:' + E.user.uid, JSON.stringify(rE));
    const rF = JSON.parse(kv.get('user:' + F.user.uid)); rF.keyHash = 'f'.repeat(64); kv.set('user:' + F.user.uid, JSON.stringify(rF));
    const wd = await putP(hD), we = await putP(hE), wf = await putP(hF);
    check('지운 사람 PUT /prefs 401 · 칸 안 생김', [wd.status, kv.has('prefs:' + D.user.uid)], [401, false]);
    check('멈춘 사람 PUT /prefs 403 · 칸 안 생김', [we.status, we.j.error, kv.has('prefs:' + E.user.uid)], [403, 'paused', false]);
    check('키가 바뀐 사람 PUT /prefs 401', [wf.status, kv.has('prefs:' + F.user.uid)], [401, false]);
    check('지운 사람 POST /portfolio 401', (await post('/portfolio', hD, { encHoldings: enc(5) })).status, 401);
    check('멈춘 사람 POST /ai 403 · 모델 안 부름', await (async () => { aiCalls = 0; const r = await post('/ai', hE, { snapshot: {} }); return [r.status, aiCalls]; })(), [403, 0]);
    check('지운 사람 PUT /push/subscribe 401', (await call('PUT', '/push/subscribe', { hash: hD, body: {} })).status, 401);
    check('낡은 캐시여도 읽기는 통과(GET /prefs)', (await call('GET', '/prefs', { hash: hD })).status, 200);
    kv.set('user:' + F.user.uid, JSON.stringify({ ...rF, keyHash: hF })); // 되돌림 — 같은 키면 쓰기 통과
    check('제 키 해시가 기록과 같으면 PUT 통과', (await putP(hF)).status, 200);

    const mem = await createUser(env, { name: '권' });
    const pr = await call('PATCH', '/admin/users/' + mem.user.uid, { body: { role: 'owner', name: 'x' } });
    check('PATCH role 은 무시 — 멤버 그대로', [pr.status, pr.j.user.role, pr.j.user.name, JSON.parse(kv.get('user:' + mem.user.uid)).role], [200, 'member', 'x', 'member']);
    const before = kv.size;
    for (const bad of ['a:b', '..', 'A_B']) {
      const r = await fcall(WK, { uid: bad, item: { n: 1 } });
      check(`/fired uid ${bad} 는 404 · KV 안 씀`, [r.status, kv.size], [404, before]);
    }
    const savedRead = env.PUSH_READ_KEY; delete env.PUSH_READ_KEY;
    check('migrate 는 PUSH_READ_KEY 없으면 503', (await rawPost('/admin/migrate', {}, { keyHash: KEY })).status, 503);
    env.PUSH_READ_KEY = savedRead;
  }

  console.log('  사람 표 이전 전(legacy) 모양');
  const snap = new Map(kv);
  kv.clear(); _clearUserCache();
  await call('PUT', '/prefs', { body: { watch: [{ id: '005930', kind: 'stock' }] } });
  const la = await call('GET', '/prefs/all', { hash: null, headers: RK });
  check('legacy /prefs/all 은 주인 한 명(uid=h16)', [la.j.users.length, la.j.users[0].uid, la.j.users[0].role], [1, h16, 'owner']);
  const lm = await call('GET', '/admin/users');
  check('legacy 목록 한 명', [lm.status, lm.j.users.length], [200, 1]);
  check('legacy 생성 409 not_migrated', (await call('POST', '/admin/users', { body: { name: 'x' } })).j, { error: 'not_migrated' });
  check('legacy rekey 409', (await call('POST', '/admin/users/abc/rekey')).status, 409);
  check('legacy /me', (await call('GET', '/me')).j, { uid: h16, name: '마스터', role: 'owner', viaBackup: false });
  check('legacy /fired 쓰기 uid=h16', (await fcall(WK, { uid: h16, item: { a: 1 } })).status, 200);
  check('legacy /fired 모르는 uid 404', (await fcall(WK, { uid: 'other', item: { a: 1 } })).status, 404);
  check('legacy GET /fired', (await call('GET', '/fired')).j.items.length, 1);
  const mig = await rawPost('/admin/migrate', RK, { keyHash: KEY });
  check('migrate 로 사람 표 생성', [mig.status, mig.j.created, kv.has('users:index')], [200, true, true]);
  check('migrate 가 fired:<h16> → fired:<uid> 복사', JSON.parse(kv.get('fired:' + mig.j.uid)), [{ a: 1 }]);
  kv.clear(); for (const [k, v] of snap) kv.set(k, v); _clearUserCache();
}

console.log('index 가 사라지면 닫힌 채 실패');
kv.delete('users:index');
_clearUserCache();
const gone = await call('GET', '/prefs');
check('503 users_index_missing', [gone.status, gone.j.error], [503, 'users_index_missing']);
{
  const WK = { 'X-Push-Write-Key': 'fake-push-write-key' };
  const f = await call('POST', '/fired', { hash: null, headers: WK, body: { uid: 'whoever1', item: { n: 1 } } });
  check('index 없으면 POST /fired 503 users_index_missing', [f.status, f.j.error], [503, 'users_index_missing']);
  delete env.PUSH_WRITE_KEY; // 이 시험이 켠 시크릿을 되돌림
}

if (fails) { console.log(`\n${fails}건 실패`); process.exit(1); }
console.log('\n전부 통과');
