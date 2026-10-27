// users.js 자가 점검 — 입장 키·uid·사람 표·해석기·마이그레이션.
// 실행: node cloudflare-worker/test_users.mjs   (가짜 키만 쓴다)
import {
  normalizeEntryKey, newEntryKey, newUid, sha256Hex, resolveUser, createUser, listUsers,
  patchUser, rekeyUser, deleteUser, issueBackupKey, touchSeen, migrateOwner, _clearUserCache,
} from './users.js';

const kv = new Map();
let puts = 0;
const KV = {
  get: async (k, t) => { const v = kv.get(k); return v == null ? null : (t === 'json' ? JSON.parse(v) : v); },
  put: async (k, v) => { puts++; kv.set(k, v); },
  delete: async k => { kv.delete(k); },
};
const env = { ECON_PORTFOLIO: KV };

let fails = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) { console.log(`  OK   ${label}`); return; }
  fails++;
  console.log(`  FAIL ${label}: ${JSON.stringify(got)} (기대 ${JSON.stringify(want)})`);
};

console.log('normalizeEntryKey');
check('공백·소문자 정리', normalizeEntryKey(' ecom-7kq3 px9m-2hta '), 'ECOM-7KQ3-PX9M-2HTA');
check('옛 키 그대로', normalizeEntryKey('My-Key 2026 Pass'), 'My-Key 2026 Pass');
check('11자 → trim', normalizeEntryKey('ECOM-7KQ3-PX9M-2HT '), 'ECOM-7KQ3-PX9M-2HT');
check('O 포함 → trim', normalizeEntryKey(' ECOM-OKQ3-PX9M-2HTA'), 'ECOM-OKQ3-PX9M-2HTA');

console.log('newEntryKey / newUid');
{
  const re = /^ECOM-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}$/;
  const set = new Set(); let allOk = true;
  for (let i = 0; i < 1000; i++) { const k = newEntryKey(); set.add(k); if (!re.test(k) || normalizeEntryKey(k) !== k) allOk = false; }
  check('1000개 형식·정규화 일치', allOk, true);
  check('중복 0', set.size, 1000);
  check('uid 형식', /^[a-z0-9]{12}$/.test(newUid()), true);
  check('sha256Hex 빈 문자열', await sha256Hex(''), 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
}

console.log('legacy');
const LEG = await sha256Hex('fake-legacy-secret');
{
  const r = await resolveUser(env, LEG, LEG);
  check('legacy 성공', [r.user?.legacy, r.user?.uid, r.user?.role], [true, LEG.slice(0, 16), 'owner']);
  const w = await resolveUser(env, 'f'.repeat(64), LEG);
  check('틀린 해시 401', [w.status, w.error], [401, 'unauthorized']);
}

console.log('migrateOwner');
{
  const h16 = LEG.slice(0, 16);
  kv.set(`prefs:${h16}`, '{"a":1}');
  kv.set(`push:${h16}`, '{"sub":1}');
  kv.set('portfolio:encHoldings', 'ENC-NOW');
  const kstNow = new Date(Date.now() + 9 * 3600 * 1000);
  const day = n => new Date(kstNow.getTime() - n * 86400000).toISOString().slice(0, 10);
  kv.set(`portfolio:encHoldings:prev:${day(0)}`, 'ENC-P0');
  kv.set(`portfolio:encHoldings:prev:${day(29)}`, 'ENC-P29');
  kv.set(`portfolio:encHoldings:prev:${day(30)}`, 'ENC-P30');
  const m = await migrateOwner(env, LEG);
  check('처음 created:true', m.created, true);
  const uid = m.uid;
  check('prefs 복사', kv.get(`prefs:${uid}`), '{"a":1}');
  check('push 복사', kv.get(`push:${uid}`), '{"sub":1}');
  check('hold 복사', kv.get(`hold:${uid}`), 'ENC-NOW');
  check('prev 오늘', kv.get(`hold:${uid}:prev:${day(0)}`), 'ENC-P0');
  check('prev 29일 전', kv.get(`hold:${uid}:prev:${day(29)}`), 'ENC-P29');
  check('prev 30일 전은 안 옮김', kv.get(`hold:${uid}:prev:${day(30)}`), undefined);
  check('옛 칸 유지', [kv.get(`prefs:${h16}`), kv.get('portfolio:encHoldings')], ['{"a":1}', 'ENC-NOW']);
  const before = puts;
  const m2 = await migrateOwner(env, LEG);
  check('두 번째 created:false 같은 uid', [m2.created, m2.uid], [false, uid]);
  check('두 번째 쓰기 0', puts - before, 0);
  _clearUserCache();
  const r = await resolveUser(env, LEG, LEG);
  check('이전 뒤 owner 해석(legacy 아님)', [r.user?.role, r.user?.uid, !!r.user?.legacy], ['owner', uid, false]);
}

console.log('createUser / patch / rekey / delete');
{
  const { user, key } = await createUser(env, { name: '민수' });
  const hash = async k => sha256Hex(normalizeEntryKey(k));
  let r = await resolveUser(env, await hash(key), LEG);
  check('새 키 해석 member', [r.user?.role, r.user?.name, r.user?.viaBackup], ['member', '민수', false]);
  check('목록에 포함', (await listUsers(env)).some(u => u.uid === user.uid), true);

  await patchUser(env, user.uid, { status: 'paused' });
  _clearUserCache();
  r = await resolveUser(env, await hash(key), LEG);
  check('정지 → 403', [r.status, r.error], [403, 'paused']);
  await patchUser(env, user.uid, { status: 'active', name: '민수2' });
  r = await resolveUser(env, await hash(key), LEG);
  check('patch 뒤 즉시 반영', [r.user?.status, r.user?.name], ['active', '민수2']);

  const { key: k2 } = await rekeyUser(env, user.uid);
  r = await resolveUser(env, await hash(key), LEG);
  check('옛 키 401', r.status, 401);
  r = await resolveUser(env, await hash(k2), LEG);
  check('새 키 성공', r.user?.uid, user.uid);

  const d = await deleteUser(env, user.uid);
  check('삭제 ok', !!d && !d.error, true);
  r = await resolveUser(env, await hash(k2), LEG);
  check('삭제 후 401', r.status, 401);
  check('칸 4종 없음', ['prefs', 'push', 'hold', 'fired'].map(p => kv.has(`${p}:${user.uid}`)), [false, false, false, false]);
  check('user 칸 없음', kv.has(`user:${user.uid}`), false);
  check('index 에서 빠짐', (await listUsers(env)).some(u => u.uid === user.uid), false);

  const owner = (await listUsers(env)).find(u => u.role === 'owner');
  const od = await deleteUser(env, owner.uid);
  check('owner 삭제 거절', !!(od && od.error), true);
  check('owner 그대로', kv.has(`user:${owner.uid}`), true);
}

console.log('issueBackupKey / touchSeen');
{
  const owner = (await listUsers(env)).find(u => u.role === 'owner');
  const { key } = await issueBackupKey(env, owner.uid);
  const r = await resolveUser(env, await sha256Hex(normalizeEntryKey(key)), LEG);
  check('예비 키로 owner + viaBackup', [r.user?.role, r.user?.viaBackup], ['owner', true]);
  const r0 = await resolveUser(env, LEG, LEG);
  check('주 키는 viaBackup false', [r0.user?.role, r0.user?.viaBackup], ['owner', false]);
  await touchSeen(env, r0.user, '2026-10-27');
  const b = puts;
  await touchSeen(env, { ...r0.user, lastSeenDay: '2026-10-27' }, '2026-10-27');
  check('같은 날 touchSeen 쓰기 0', puts - b, 0);
  check('lastSeenDay 기록', (await KV.get(`user:${owner.uid}`, 'json')).lastSeenDay, '2026-10-27');
}

if (fails) { console.log(`\n${fails}건 실패`); process.exit(1); }
console.log('\n전부 통과');
