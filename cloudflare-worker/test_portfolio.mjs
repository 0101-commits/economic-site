// POST /portfolio 보존 규칙 검사 — GitHub 파일 API 는 가짜(fetch 가로채기), KV 도 가짜.
// 실행: node cloudflare-worker/test_portfolio.mjs
//   ① 보유 암호문만 온 요청 → KV 에만 쓰고 GitHub 커밋 0회(committed:false)
//   ② alerts 미동봉 + settings 동봉 → 기존 파일의 alerts 를 보존해 커밋
//   ③ alerts 동봉 → 그 목록으로 커밋(종전 동작 유지)
//   ④ 보유 암호문을 덮을 때 덮기 전 판을 portfolio:encHoldings:prev:<한국 날짜> 에 그날 첫 판만 남김(30일, B5)
import worker from './worker.js';
import { createHash } from 'crypto';

const sha = s => createHash('sha256').update(s).digest('hex');
const kv = new Map();
const kvOpts = new Map();
const KV = { get: async (k, t) => { const v = kv.get(k); return v == null ? null : (t === 'json' ? JSON.parse(v) : v); },
             put: async (k, v, o) => { kv.set(k, v); kvOpts.set(k, o); } };
const env = { ALERTS_SYNC_KEY: 'fake-secret-for-test', ECON_PORTFOLIO: KV, GH_DISPATCH_TOKEN: 'fake-token',
              AI_LIMITER: { limit: async () => ({ success: true }) } };
const KEY = sha('fake-secret-for-test');

// 가짜 GitHub: 현재 파일 = 알림 1개(KOSPI 2,900 이상)·관심 1종목·전역 ON
const prev = { version: 1, updatedAt: '2026-10-01T00:00:00Z', settings: { enabled: true, frequency: 'daily' },
               alerts: [{ id: 'a1', type: 'price_above', symbol: '^KS11', name: 'KOSPI', market: 'KR', value: 2900, enabled: true }],
               tracking: { items: [{ symbol: '005930', name: '삼성전자', market: 'KR' }] } };
const b64 = s => Buffer.from(s, 'utf8').toString('base64');
const puts = [];
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, init = {}) => {
  const u = String(url);
  if (u.startsWith('https://api.github.com/repos/') && u.includes('/contents/')) {
    if ((init.method || 'GET') === 'GET') return new Response(JSON.stringify({ sha: 'abc', content: b64(JSON.stringify(prev)) }), { status: 200 });
    puts.push(JSON.parse(init.body));
    return new Response(JSON.stringify({ content: { sha: 'def' } }), { status: 200 });
  }
  return realFetch(url, init);
};

const post = async body => {
  const r = await worker.fetch(new Request('https://w.test/portfolio', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ keyHash: KEY, ...body }),
  }), env, { waitUntil() {} });
  return { status: r.status, j: await r.json() };
};
const decodePut = p => JSON.parse(Buffer.from(p.content, 'base64').toString('utf8'));

let fails = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${label}${ok ? '' : `: ${JSON.stringify(got)} (기대 ${JSON.stringify(want)})`}`);
  if (!ok) fails++;
};

const enc = { alg: 'AES-256-GCM', kdf: 'PBKDF2-SHA256', iter: 600000, salt: 'c2FsdA==', iv: 'aXZpdml2aXZpdg==', ciphertext: 'Y2lwaGVy' };

console.log('① 보유 암호문만');
let r = await post({ encHoldings: enc });
check('200', r.status, 200);
check('committed:false', r.j.committed, false);
check('GitHub PUT 0회', puts.length, 0);
check('KV 에 저장됨', !!kv.get('portfolio:encHoldings'), true);
check('처음 올림엔 이전 판 없음', [...kv.keys()].some(k => k.startsWith('portfolio:encHoldings:prev')), false);

console.log('② alerts 미동봉 + settings 동봉');
r = await post({ settings: { enabled: false, frequency: 'daily' } });
check('200', r.status, 200);
check('PUT 1회', puts.length, 1);
let cfg = decodePut(puts[0]);
check('기존 alerts 보존(1개·KOSPI)', [cfg.alerts.length, cfg.alerts[0] && cfg.alerts[0].name], [1, 'KOSPI']);
check('기존 tracking 보존', cfg.tracking && cfg.tracking.items.length, 1);
check('settings 는 새 값(OFF)', cfg.settings.enabled, false);

console.log('③ alerts 동봉(빈 배열) → 비우기는 명시했을 때만');
r = await post({ alerts: [] });
check('PUT 2회', puts.length, 2);
cfg = decodePut(puts[1]);
check('alerts 0개', cfg.alerts.length, 0);
check('tracking 은 보존', cfg.tracking && cfg.tracking.items.length, 1);

console.log('④ 보유 덮어쓰기 → 날짜별 이전 판(그날 첫 판만)');
const realNow = Date.now;
Date.now = () => Date.parse('2026-10-07T15:30:00Z');   // 한국 10/8 00:30 — 날짜는 한국 기준
const DAY1 = 'portfolio:encHoldings:prev:2026-10-08';
const first = kv.get('portfolio:encHoldings');
const enc2 = { ...enc, iv: 'aXZpdml2aXZpdjI=', ciphertext: 'Y2lwaGVyMg==' };
r = await post({ encHoldings: enc2 });
check('200', r.status, 200);
check('그날 이전 판 = 덮기 전 값', kv.get(DAY1), first);
check('이전 판 30일 뒤 사라짐', kvOpts.get(DAY1), { expirationTtl: 30 * 86400 });
check('지금 판 = 새 값', JSON.parse(kv.get('portfolio:encHoldings')).ciphertext, 'Y2lwaGVyMg==');
const enc3 = { ...enc, iv: 'aXZpdml2aXZpdjM=', ciphertext: 'Y2lwaGVyMw==' };
r = await post({ encHoldings: enc3 });
check('같은 날 두 번째 덮기 → 그날 첫 판 그대로(좋은 판을 밀어내지 못함)', [r.status, kv.get(DAY1)], [200, first]);
r = await post({ keyHash: sha('x'), encHoldings: enc });
check('틀린 키 → 401 · 이전 판 그대로', [r.status, kv.get(DAY1)], [401, first]);
Date.now = () => Date.parse('2026-10-08T15:30:00Z');
const before = kv.get('portfolio:encHoldings');
r = await post({ encHoldings: enc2 });
check('다음 날엔 새 칸에 그날 첫 판', [kv.get('portfolio:encHoldings:prev:2026-10-09'), kv.get(DAY1)], [before, first]);
Date.now = realNow;

globalThis.fetch = realFetch;
console.log(fails ? `\n실패 ${fails}건` : '\n전부 통과');
process.exit(fails ? 1 : 0);
