// 사람 표 — 입장 키 · uid · 해석기 · 마이그레이션. (Workers KV: env.ECON_PORTFOLIO)
// KV 칸: user:<uid> · ukey:<keyHash> = uid · users:index = [uid,…]
// 주의: KV .list() 는 쓰지 않는다(무료 한도). worker.js 를 import 하지 않는다(순환 방지).

export const ENTRY_ALPHABET = '23456789ABCDEFGHJKMNPQRSTUVWXYZ'; // 31자
const UID_ALPHABET = 'abcdefghijklmnopqrstuvwxyz0123456789'; // 36자
const ENTRY_RE = /^ECOM[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{12}$/;

export async function sha256Hex(s) {
  const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(s)));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, '0')).join('');
}

export function normalizeEntryKey(raw) {
  const s = String(raw == null ? '' : raw);
  const squeezed = s.replace(/[\s-]+/g, '').toUpperCase();
  if (ENTRY_RE.test(squeezed)) {
    return `ECOM-${squeezed.slice(4, 8)}-${squeezed.slice(8, 12)}-${squeezed.slice(12, 16)}`;
  }
  return s.trim();
}

// 거절 표본: limit(알파벳 길이의 배수) 미만인 바이트만 받아 편향을 없앤다.
function randomChars(alphabet, n) {
  const m = alphabet.length;
  const limit = 256 - (256 % m);
  let out = '';
  while (out.length < n) {
    const buf = new Uint8Array(32);
    crypto.getRandomValues(buf);
    for (const b of buf) {
      if (b < limit) { out += alphabet[b % m]; if (out.length === n) break; }
    }
  }
  return out;
}

export function newEntryKey() {
  const c = randomChars(ENTRY_ALPHABET, 12);
  return `ECOM-${c.slice(0, 4)}-${c.slice(4, 8)}-${c.slice(8, 12)}`;
}
export function newUid() { return randomChars(UID_ALPHABET, 12); }

// ---- 캐시 ----
const CACHE_TTL_MS = 60_000;
const cache = new Map(); // keyHash → {result, at}
export function _clearUserCache() { cache.clear(); }

const kvGet = (env, k) => env.ECON_PORTFOLIO.get(k, 'json');
const kvGetRaw = (env, k) => env.ECON_PORTFOLIO.get(k);
const kvPut = (env, k, v) => env.ECON_PORTFOLIO.put(k, typeof v === 'string' ? v : JSON.stringify(v));
const kvDel = (env, k) => env.ECON_PORTFOLIO.delete(k);

async function readIndex(env) { return await kvGet(env, 'users:index'); }

export async function resolveUser(env, keyHash, legacyHash) {
  const hit = cache.get(keyHash);
  if (hit && Date.now() - hit.at < CACHE_TTL_MS) return hit.result;
  const result = await resolveUncached(env, keyHash, legacyHash);
  cache.set(keyHash, { result, at: Date.now() });
  return result;
}

async function resolveUncached(env, keyHash, legacyHash) {
  const index = await readIndex(env);
  if (!Array.isArray(index)) {
    if (keyHash && legacyHash && keyHash === legacyHash) {
      return { user: { uid: keyHash.slice(0, 16), role: 'owner', status: 'active', name: '마스터', legacy: true } };
    }
    return { status: 401, error: 'unauthorized' };
  }
  const uid = keyHash ? await kvGetRaw(env, `ukey:${keyHash}`) : null;
  if (!uid) return { status: 401, error: 'unauthorized' };
  const rec = await kvGet(env, `user:${uid}`);
  if (!rec) return { status: 401, error: 'unauthorized' };
  if (rec.status === 'paused') return { status: 403, error: 'paused' };
  return { user: { ...rec, viaBackup: !!rec.backupKeyHash && keyHash === rec.backupKeyHash } };
}

async function insertUser(env, { name, role, keyHash }) {
  const uid = newUid();
  const user = {
    uid, name, role, status: 'active', keyHash, createdAt: new Date().toISOString(),
    lastSeenDay: null, aiDay: null, aiCount: 0,
  };
  await kvPut(env, `user:${uid}`, user);
  await kvPut(env, `ukey:${keyHash}`, uid);
  const index = (await readIndex(env)) || [];
  if (!index.includes(uid)) index.push(uid);
  await kvPut(env, 'users:index', index);
  _clearUserCache();
  return user;
}

export async function createUser(env, { name, role = 'member' }) {
  const key = newEntryKey();
  const keyHash = await sha256Hex(normalizeEntryKey(key));
  const user = await insertUser(env, { name, role, keyHash });
  return { user, key };
}

export async function listUsers(env) {
  const index = (await readIndex(env)) || [];
  const out = [];
  for (const uid of index) { const u = await kvGet(env, `user:${uid}`); if (u) out.push(u); }
  return out;
}

export async function patchUser(env, uid, { name, status } = {}) {
  const u = await kvGet(env, `user:${uid}`);
  if (!u) return { status: 404, error: 'not_found' };
  if (name !== undefined) u.name = name;
  if (status !== undefined) u.status = status;
  await kvPut(env, `user:${uid}`, u);
  _clearUserCache();
  return { user: u };
}

export async function rekeyUser(env, uid) {
  const u = await kvGet(env, `user:${uid}`);
  if (!u) return { status: 404, error: 'not_found' };
  const key = newEntryKey();
  const keyHash = await sha256Hex(normalizeEntryKey(key));
  await kvDel(env, `ukey:${u.keyHash}`);
  u.keyHash = keyHash;
  await kvPut(env, `user:${uid}`, u);
  await kvPut(env, `ukey:${keyHash}`, uid);
  _clearUserCache();
  return { key };
}

export async function deleteUser(env, uid) {
  const u = await kvGet(env, `user:${uid}`);
  if (!u) return { status: 404, error: 'not_found' };
  if (u.role === 'owner') return { status: 403, error: 'owner_undeletable' };
  await kvDel(env, `ukey:${u.keyHash}`);
  if (u.backupKeyHash) await kvDel(env, `ukey:${u.backupKeyHash}`);
  for (const p of ['prefs', 'push', 'hold', 'fired']) await kvDel(env, `${p}:${uid}`);
  await kvDel(env, `user:${uid}`);
  const index = ((await readIndex(env)) || []).filter(x => x !== uid);
  await kvPut(env, 'users:index', index);
  _clearUserCache();
  return { ok: true };
}

export async function issueBackupKey(env, ownerUid) {
  const u = await kvGet(env, `user:${ownerUid}`);
  if (!u || u.role !== 'owner') return { status: 404, error: 'not_found' };
  const key = newEntryKey();
  const keyHash = await sha256Hex(normalizeEntryKey(key));
  if (u.backupKeyHash) await kvDel(env, `ukey:${u.backupKeyHash}`);
  u.backupKeyHash = keyHash;
  await kvPut(env, `user:${ownerUid}`, u);
  await kvPut(env, `ukey:${keyHash}`, ownerUid);
  _clearUserCache();
  return { key };
}

export async function touchSeen(env, user, kstDay) {
  if (!user || user.legacy || user.lastSeenDay === kstDay) return;
  const rec = await kvGet(env, `user:${user.uid}`);
  if (!rec) return;
  user.lastSeenDay = kstDay;
  if (rec.lastSeenDay === kstDay) return;
  rec.lastSeenDay = kstDay;
  await kvPut(env, `user:${user.uid}`, rec);
}

async function copyKey(env, from, to) {
  const v = await kvGetRaw(env, from);
  if (v != null) await env.ECON_PORTFOLIO.put(to, v);
}

export async function migrateOwner(env, legacyHash) {
  const existing = await kvGetRaw(env, `ukey:${legacyHash}`);
  if (existing) return { uid: existing, created: false };
  const user = await insertUser(env, { name: '마스터', role: 'owner', keyHash: legacyHash });
  const uid = user.uid;
  const h16 = legacyHash.slice(0, 16);
  await copyKey(env, `prefs:${h16}`, `prefs:${uid}`);
  await copyKey(env, `push:${h16}`, `push:${uid}`);
  await copyKey(env, 'portfolio:encHoldings', `hold:${uid}`);
  const kstNow = Date.now() + 9 * 3600 * 1000;
  for (let i = 0; i < 30; i++) {
    const day = new Date(kstNow - i * 86400000).toISOString().slice(0, 10);
    await copyKey(env, `portfolio:encHoldings:prev:${day}`, `hold:${uid}:prev:${day}`);
  }
  return { uid, created: true };
}
