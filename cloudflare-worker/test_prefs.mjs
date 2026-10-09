// /prefs · /push/subscribe 자가 점검 — 1층 사용자 데이터를 KV 에 두는 경로.
// 인증·화이트리스트·2층 필드 거부·크기 상한·If-Match·키 해시별 공간·출처 제한 CORS 가 무너지면 실패한다.
//
// 실행: node cloudflare-worker/test_prefs.mjs   (가짜 키·가짜 구독만 쓴다)
import worker from './worker.js';
import { createHash } from 'crypto';

const sha = s => createHash('sha256').update(s).digest('hex');
const kv = new Map();
const KV = { get: async (k, t) => { const v = kv.get(k); return v == null ? null : (t === 'json' ? JSON.parse(v) : v); },
             put: async (k, v) => { kv.set(k, v); } };
const env = {
  ALERTS_SYNC_KEY: 'fake-secret-for-test',
  ECON_PORTFOLIO: KV,
  AI_LIMITER: { limit: async () => ({ success: true }) },
  VAPID_PUBLIC_KEY: 'BFakePublicKeyForTestOnly',
};
const KEY = sha('fake-secret-for-test');
const call = async (method, path, { hash = KEY, body, headers = {}, e = env, raw } = {}) => {
  const h = { ...headers };
  if (hash) h['X-Sync-Key-Hash'] = hash;
  if (body !== undefined || raw !== undefined) h['content-type'] = 'application/json';
  const r = await worker.fetch(new Request('https://w.test' + path, {
    method, headers: h, body: raw !== undefined ? raw : (body !== undefined ? JSON.stringify(body) : undefined),
  }), e, { waitUntil() {} });
  let j = null;
  try { j = await r.clone().json(); } catch (_) {}
  return { status: r.status, j, h: r.headers };
};

let fails = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) { console.log(`  OK   ${label}`); return; }
  fails++;
  console.log(`  FAIL ${label}: ${JSON.stringify(got)} (기대 ${JSON.stringify(want)})`);
};

console.log('인증');
check('헤더 없음 → 401', (await call('GET', '/prefs', { hash: '' })).status, 401);
check('틀린 키 GET → 401', (await call('GET', '/prefs', { hash: sha('x') })).status, 401);
check('틀린 키 PUT → 401', (await call('PUT', '/prefs', { hash: sha('x'), body: {} })).status, 401);
check('틀린 키 푸시 → 401', (await call('PUT', '/push/subscribe', { hash: sha('x'), body: {} })).status, 401);
check('레이트리밋 바인딩 없음 → 503', (await call('GET', '/prefs', { e: { ...env, AI_LIMITER: undefined } })).status, 503);
check('POST /prefs → 405', (await call('POST', '/prefs', { body: {} })).status, 405);

console.log('GET 빈값');
let r = await call('GET', '/prefs');
check('200', r.status, 200);
const V2_DEFAULTS = { package: 'normal', ringChannel: 'push', dailyCap: 6, quietAlarm: false,
  briefings: { morning: true, close: true, noon: false, evening: false, us: false, weekly: true },
  families: { A: true, B: true, C: true, D: true, E: true, F: true, G: true, H: true },
  rememberKey: false, kakaoFriends: false, kakaoRecipients: [] };
check('빈 기본값', r.j, { v: 2, updatedAt: null, watch: [], alerts: [],
  settings: { theme: 'system', updown: 'kr', unit: 'man', quiet: null, ...V2_DEFAULTS }, scenarios: [] });

console.log('PUT 저장 · 화이트리스트');
const good = {
  v: 1, foo: '버려질 필드', updatedAt: '1999-01-01T00:00:00Z',
  watch: [
    { id: 'kospi', kind: 'indicator', addedAt: '2026-10-01T00:00:00Z', note: '버림' },
    { id: '005930', kind: 'stock' },
    { id: '005930', kind: 'stock' },                 // 중복 → 하나만
    { id: 'x', kind: 'bond' },                       // 모르는 kind → 버림
    { id: '<script>', kind: 'stock' },               // id 형식 밖 → 버림
  ],
  alerts: [
    { id: 'a1', target: '005930', type: 'price', cond: { op: '>=', value: 90000 }, repeat: 'daily',
      channels: ['push', 'sms', 'discord'], enabled: true, extra: 1 },
    { id: 'a2', target: 'kospi', type: 'teleport', cond: {} },   // 모르는 type → 버림
  ],
  settings: { theme: 'dark', updown: 'us', unit: 'won', quiet: { from: '23:00', to: '07:00' }, font: 'x' },
  scenarios: [{ name: ' 금리 +1%p ', inputs: { rateDelta: 1 }, owner: '버림' }, { name: '' }],
};
r = await call('PUT', '/prefs', { body: good });
check('200', r.status, 200);
const saved = r.j;
check('모르는 최상위 필드 버림', 'foo' in saved, false);
check('updatedAt 은 서버가 정함', saved.updatedAt !== '1999-01-01T00:00:00Z', true);
check('watch', saved.watch, [{ id: 'kospi', kind: 'indicator', addedAt: '2026-10-01T00:00:00Z' },
                             { id: '005930', kind: 'stock', addedAt: null }]);
check('alerts', saved.alerts, [{ id: 'a1', target: '005930', type: 'price', cond: { op: '>=', value: 90000 },
  repeat: 'daily', channels: ['push', 'discord'], enabled: true }]);
check('settings', saved.settings, { theme: 'dark', updown: 'us', unit: 'won', quiet: { from: '23:00', to: '07:00' }, ...V2_DEFAULTS });
check('scenarios', saved.scenarios, [{ name: '금리 +1%p', inputs: { rateDelta: 1 } }]);
check('GET 이 저장본을 돌려줌', (await call('GET', '/prefs')).j, saved);
check('KV 키 = prefs:<키 해시 앞 16자>', kv.has('prefs:' + KEY.slice(0, 16)), true);

console.log('2층 필드 거부');
for (const [label, body] of [
  ['최상위 holdings', { holdings: [] }],
  ['watch 의 qty', { watch: [{ id: '005930', kind: 'stock', qty: 10 }] }],
  ['시나리오 입력의 avg_price', { scenarios: [{ name: 's', inputs: { avg_price: 70000 } }] }],
  ['알림 cond 의 costKrw', { alerts: [{ id: 'a', target: 'kospi', type: 'price', cond: { costKrw: 1 } }] }],
  ['우리말 평단가', { settings: { 평단가: 1 } }],
  ['encHoldings', { encHoldings: { alg: 'AES-256-GCM' } }],
]) {
  r = await call('PUT', '/prefs', { body });
  check(label + ' → 400', [r.status, r.j && r.j.error], [400, 'tier2_field_rejected']);
}
check('거부 뒤 저장본 그대로', (await call('GET', '/prefs')).j, saved);
for (const [label, key] of [['전각 ｑｔｙ', 'ｑｔｙ'], ['보이지 않는 글자 q\\u200Bty', 'q​ty'], ['avgPx', 'avgPx'],
                            ['평균단가', '평균단가'], ['position', 'position'], ['매수금액', '매수금액']]) {
  r = await call('PUT', '/prefs', { body: { scenarios: [{ name: 's', inputs: { [key]: 1 } }] } });
  check(label + ' → 400', r.status, 400);
}
r = await call('PUT', '/prefs', { body: { alerts: [{ id: 'f1', target: 'kospi', type: 'flow', cond: { who: 'foreign', amount: 1000e8 } }],
                                          scenarios: [{ name: 's', inputs: { balance: 1, 금액: 2 } }] } });
check('수급 알림 cond.amount·시나리오 balance 는 정상 저장', [r.status, r.j.alerts.length, r.j.scenarios.length], [200, 1, 1]);
await call('PUT', '/prefs', { body: good });

console.log('크기·형식');
r = await call('PUT', '/prefs', { body: { scenarios: [{ name: 'big', inputs: { pad: 'x'.repeat(33000) } }] } });
check('32KB 초과 → 413', r.status, 413);
r = await call('PUT', '/prefs', { body: { scenarios: [{ name: 'k', inputs: { pad: '가'.repeat(11000) } }] } });
check('한글 3바이트 기준으로 셈(11000자 = 33KB) → 413', r.status, 413);
r = await call('PUT', '/prefs', { body: { alerts: [{ id: 'a', target: 'kospi', type: 'pct', cond: { s: 'x'.repeat(600) } }] } });
check('cond 512자 초과 → 400', [r.status, r.j && r.j.error], [400, 'cond_too_large']);
check('JSON 아님 → 400', (await call('PUT', '/prefs', { raw: '{' })).status, 400);
// 서버가 기본값을 채워 입력보다 커지는 문서 — 저장 문서에도 상한을 걸어 GET→PUT 왕복이 막히지 않게 한다.
const thin = n => Array.from({ length: n }, (_, i) => ({ id: 'a' + i, target: 'kospi', type: 'pct' }));
const pad = n => [{ name: 'p', inputs: { pad: 'x'.repeat(n) } }];
r = await call('PUT', '/prefs', { body: { alerts: thin(100), scenarios: pad(28000) } });
check('입력은 32KB 안이지만 정리 뒤 넘으면 → 413 prefs_too_large', [r.status, r.j && r.j.error], [413, 'prefs_too_large']);
r = await call('PUT', '/prefs', { body: { alerts: thin(100), scenarios: pad(20000) } });
check('상한 근처 저장 → 200', r.status, 200);
const near = (await call('GET', '/prefs')).j;
check('받은 문서를 그대로 다시 저장 → 200', (await call('PUT', '/prefs', { body: near })).status, 200);
for (const [label, quiet] of [['객체', { from: { toString: 1 }, to: '07:00' }], ['배열', { from: ['23:00'], to: ['07:00'] }]]) {
  r = await call('PUT', '/prefs', { body: { settings: { quiet } } });
  check(`방해 금지 시간이 ${label}면 null(500 아님)`, [r.status, r.j && r.j.settings.quiet], [200, null]);
}
check('너무 깊음 → 400', (await call('PUT', '/prefs', { body: { scenarios: [{ name: 'd', inputs: { a: { b: { c: { d: 1 } } } } }] } })).status, 400);

console.log('If-Match');
const base = (await call('PUT', '/prefs', { body: good })).j;   // 앞 절들이 저장본을 바꿨으므로 기준을 새로 잡는다
r = await call('PUT', '/prefs', { body: good, headers: { 'If-Match': base.updatedAt } });
check('맞는 updatedAt → 200', r.status, 200);
const second = r.j.updatedAt;
check('같은 밀리초여도 updatedAt 이 커짐', second > base.updatedAt, true);
r = await call('PUT', '/prefs', { body: good, headers: { 'If-Match': base.updatedAt } });
check('낡은 updatedAt → 409', [r.status, r.j && r.j.updatedAt], [409, second]);
check('따옴표 붙은 값도 비교', (await call('PUT', '/prefs', { body: good, headers: { 'If-Match': `"${second}"` } })).status, 200);
check('If-Match 없으면 덮어씀', (await call('PUT', '/prefs', { body: good })).status, 200);

console.log('키 해시별 공간');
const NEW = sha('a new long passphrase');
kv.set('auth:syncKeyHash', NEW);                     // 사이트에서 「키 바꾸기」를 한 상태
check('옛 키 → 401', (await call('GET', '/prefs')).status, 401);
r = await call('GET', '/prefs', { hash: NEW });
check('새 키 → 빈 새 공간', [r.status, r.j.watch.length, r.j.updatedAt], [200, 0, null]);
check('새 공간: If-Match "null" 은 저장본 없음과 같음', (await call('PUT', '/prefs', { hash: NEW, body: {}, headers: { 'If-Match': 'null' } })).status, 200);
check('옛 공간은 KV 에 남음', kv.has('prefs:' + KEY.slice(0, 16)) && kv.has('prefs:' + NEW.slice(0, 16)), true);
kv.delete('auth:syncKeyHash');

console.log('출처 제한 CORS');
const pre = async (origin, e = env) => (await worker.fetch(new Request('https://w.test/prefs', {
  method: 'OPTIONS', headers: { Origin: origin, 'Access-Control-Request-Method': 'PUT' } }), e, {})).headers;
let h = await pre('https://0101-commits.github.io');
check('운영 출처 preflight → ACAO echo', h.get('access-control-allow-origin'), 'https://0101-commits.github.io');
check('PUT·DELETE 허용', /PUT/.test(h.get('access-control-allow-methods')) && /DELETE/.test(h.get('access-control-allow-methods')), true);
check('If-Match 헤더 허용', /if-match/.test(h.get('access-control-allow-headers')), true);
check('localhost:5173 기본 불허', (await pre('http://localhost:5173')).get('access-control-allow-origin'), null);
const dev = { ...env, DEV_CORS: '1' };
check('DEV_CORS=1 이면 localhost:5173 허용', (await pre('http://localhost:5173', dev)).get('access-control-allow-origin'), 'http://localhost:5173');
check('DEV_CORS=1 이면 127.0.0.1:5173 허용', (await pre('http://127.0.0.1:5173', dev)).get('access-control-allow-origin'), 'http://127.0.0.1:5173');
check('DEV_CORS 시크릿의 후행 개행도 켜짐', (await pre('http://localhost:5173', { ...env, DEV_CORS: '1\n' })).get('access-control-allow-origin'), 'http://localhost:5173');
check('DEV_CORS=1 이어도 다른 포트는 불허', (await pre('http://localhost:3000', dev)).get('access-control-allow-origin'), null);
check('localhost:5173 GET (플래그 없음) → 403', (await call('GET', '/prefs', { headers: { Origin: 'http://localhost:5173' } })).status, 403);
check('남의 출처 PUT → 403', (await call('PUT', '/prefs', { body: {}, headers: { Origin: 'https://evil.example' } })).status, 403);
r = await call('GET', '/prefs', { headers: { Origin: 'https://0101-commits.github.io' } });
check('운영 출처 GET → 200 + ACAO echo(별표 아님)', [r.status, r.h.get('access-control-allow-origin')], [200, 'https://0101-commits.github.io']);
check('인증 응답은 캐시 금지', r.h.get('cache-control'), 'no-store');
const boom = { ...env, ECON_PORTFOLIO: { ...KV, get: async () => ({ get updatedAt() { throw new Error('boom'); } }) } };
r = await call('PUT', '/prefs', { body: {}, e: boom, headers: { Origin: 'https://0101-commits.github.io' } });
check('예상 못 한 예외 → CORS 붙은 500', [r.status, r.h.get('access-control-allow-origin')], [500, 'https://0101-commits.github.io']);

console.log('웹 푸시 구독');
const sub = n => ({ endpoint: `https://fcm.googleapis.com/fcm/send/fake-${n}`, expirationTime: null,
                    keys: { p256dh: 'BFakeP256dhKey_' + n, auth: 'fakeAuth' + n } });
check('VAPID 없음 → 503', (await call('PUT', '/push/subscribe', { body: sub(0), e: { ...env, VAPID_PUBLIC_KEY: '' } })).status, 503);
r = await call('GET', '/push/subscribe');
check('GET → 공개키·개수', r.j, { vapidPublicKey: 'BFakePublicKeyForTestOnly', count: 0 });
check('구독 → 1개', (await call('PUT', '/push/subscribe', { body: { ...sub(1), extra: 'x' } })).j.count, 1);
const stored = JSON.parse(kv.get('push:' + KEY.slice(0, 16)));
check('구독 객체 표준 필드만 보관', stored, [sub(1)]);
check('같은 기기 재구독 → 그대로 1개', (await call('PUT', '/push/subscribe', { body: sub(1) })).j.count, 1);
for (let i = 2; i <= 6; i++) await call('PUT', '/push/subscribe', { body: sub(i) });
const five = JSON.parse(kv.get('push:' + KEY.slice(0, 16)));
check('최대 5개, 가장 오래된 것부터 버림', five.map(s => s.endpoint.slice(-1)), ['2', '3', '4', '5', '6']);
check('모르는 푸시 서비스 주소 → 400', (await call('PUT', '/push/subscribe', { body: { ...sub(9), endpoint: 'https://evil.example/hook' } })).status, 400);
check('사용자 정보 붙은 주소 → 400', (await call('PUT', '/push/subscribe', { body: { ...sub(9), endpoint: 'https://u:p@fcm.googleapis.com/x' } })).status, 400);
check('포트 붙은 주소 → 400', (await call('PUT', '/push/subscribe', { body: { ...sub(9), endpoint: 'https://fcm.googleapis.com:444/x' } })).status, 400);
check('http 주소 → 400', (await call('PUT', '/push/subscribe', { body: { ...sub(9), endpoint: 'http://fcm.googleapis.com/x' } })).status, 400);
check('키 빠짐 → 400', (await call('PUT', '/push/subscribe', { body: { endpoint: sub(9).endpoint } })).status, 400);
check('해지 → 4개', (await call('DELETE', '/push/subscribe', { body: { endpoint: sub(4).endpoint } })).j.count, 4);
check('endpoint 없이 해지 → 400', (await call('DELETE', '/push/subscribe', { body: {} })).status, 400);

console.log('웹 푸시 공개키 · 발송기 경로');
r = await call('GET', '/push/key', { hash: '' });
check('공개키 — 인증 없이 200', [r.status, r.j], [200, { vapidPublicKey: 'BFakePublicKeyForTestOnly' }]);
check('공개키 없음 → 503', (await call('GET', '/push/key', { hash: '', e: { ...env, VAPID_PUBLIC_KEY: ' ' } })).status, 503);
check('공개키 PUT → 405', (await call('PUT', '/push/key', { hash: '', body: {} })).status, 405);
const READ = 'fake-push-read-key';
const senv = { ...env, PUSH_READ_KEY: READ + '\n' };   // 시크릿 후행 개행도 통과해야 한다
const scall = (method, path, { key = READ, body, e = senv } = {}) =>
  call(method, path, { hash: '', body, e, headers: key ? { 'X-Push-Read-Key': key } : {} });
check('발송기 시크릿 없음 → 503', (await scall('GET', '/push/subscriptions', { e: env })).status, 503);
check('발송기 헤더 없음 → 401', (await scall('GET', '/push/subscriptions', { key: '' })).status, 401);
check('발송기 틀린 키 → 401', (await scall('GET', '/push/subscriptions', { key: 'wrong' })).status, 401);
check('동기화 키 해시로는 못 읽음 → 401', (await call('GET', '/push/subscriptions', { e: senv })).status, 401);
r = await scall('GET', '/push/subscriptions');
check('구독 목록 200 · 4개', [r.status, r.j.subs.length], [200, 4]);
check('조용한 시간 = 저장된 /prefs 값', r.j.quiet, (await call('GET', '/prefs')).j.settings.quiet);
check('발송기 응답에 CORS 없음 · 캐시 금지', [r.h.get('access-control-allow-origin'), r.h.get('cache-control')], [null, 'no-store']);
check('구독 목록 POST → 405', (await scall('POST', '/push/subscriptions', { body: {} })).status, 405);
kv.set('push:' + NEW.slice(0, 16), JSON.stringify([sub(7)]));   // 옛 키로 남은 공간
kv.set('auth:syncKeyHash', NEW);
r = await scall('GET', '/push/subscriptions');
check('지금 유효한 키 공간만 내준다', r.j.subs.map(s => s.endpoint.slice(-1)), ['7']);
kv.delete('auth:syncKeyHash');
check('prune 틀린 키 → 401', (await scall('PUT', '/push/prune', { key: 'wrong', body: { endpoints: [sub(2).endpoint] } })).status, 401);
check('prune endpoints 없음 → 400', (await scall('PUT', '/push/prune', { body: {} })).status, 400);
r = await scall('PUT', '/push/prune', { body: { endpoints: [sub(2).endpoint, sub(5).endpoint, 'https://fcm.googleapis.com/fcm/send/none'] } });
check('prune → 2개 지움 · 2개 남음', [r.status, r.j.removed, r.j.count], [200, 2, 2]);
check('prune 뒤 KV', JSON.parse(kv.get('push:' + KEY.slice(0, 16))).map(s => s.endpoint.slice(-1)), ['3', '6']);
check('prune GET → 405', (await scall('GET', '/push/prune')).status, 405);

console.log('발송기 GET /prefs — 읽기 전용(B6, CI 가 동기화 키 없이 읽는다)');
check('읽기 키 시크릿 없음 → 503', (await scall('GET', '/prefs', { e: env })).status, 503);
check('틀린 읽기 키 → 401', (await scall('GET', '/prefs', { key: 'wrong' })).status, 401);
check('빈 읽기 키 헤더 → 401', (await call('GET', '/prefs', { hash: '', e: senv, headers: { 'X-Push-Read-Key': '' } })).status, 401);
r = await scall('GET', '/prefs');
check('읽기 키로 200 · 동기화 키로 읽은 문서와 같다', [r.status, r.j], [200, (await call('GET', '/prefs')).j]);
check('서버 간 호출(출처 없음) — ACAO 없음 · 캐시 금지', [r.h.get('access-control-allow-origin'), r.h.get('cache-control')], [null, 'no-store']);
check('읽기 키로 PUT → 403', (await scall('PUT', '/prefs', { body: {} })).status, 403);
check('읽기 키 + 맞는 동기화 키여도 PUT → 403', (await call('PUT', '/prefs', { body: {}, e: senv, headers: { 'X-Push-Read-Key': READ } })).status, 403);
check('읽기 키 길도 레이트리밋(바인딩 없음 → 503)', (await scall('GET', '/prefs', { e: { ...senv, AI_LIMITER: undefined } })).status, 503);
check('남의 출처 → 403', (await call('GET', '/prefs', { hash: '', e: senv, headers: { 'X-Push-Read-Key': READ, Origin: 'https://evil.example' } })).status, 403);
kv.set('prefs:' + NEW.slice(0, 16), JSON.stringify({ v: 2, updatedAt: '2026-10-07T00:00:00.000Z', watch: [], alerts: [] }));
kv.set('auth:syncKeyHash', NEW);
check('키를 바꾸면 새 키 공간을 읽는다', (await scall('GET', '/prefs')).j.updatedAt, '2026-10-07T00:00:00.000Z');
kv.delete('auth:syncKeyHash');

console.log('v2 조건 · 설정(알림 v2)');
// v2 조건 · 설정 — event 조건은 value(임계) · strength · level · dir 을 받고, 모르는 값은 기본으로
r = await call('PUT', '/prefs', { body: { alerts: [
  { id: 'c1', event: 'U1', target: 'usdkrw', dir: 'up', value: 1400, repeat: 'once', ring: true, enabled: true, name: '달러원 1400 위로', armSide: 'u', foo: 1 },
  { id: 'c2', event: 'A1', target: '*', strength: 'huge', level: 'alarm' },
  { id: 'c3', event: 'Z9', target: 'kospi' },
  { id: 'c4', event: 'U2', target: 'kospi', value: 'x', strength: 'odd', armSide: 'x' } ],
  settings: { package: 'many', ringChannel: 'kakao', dailyCap: 99, quietAlarm: true, briefings: { noon: true },
    families: { B: false }, rememberKey: true, kakaoFriends: true,
    kakaoRecipients: [{ uuid: 'abc', name: '가족 한 명', briefOnly: true }, { name: 'x'.repeat(30) }, { uuid: 'bad uuid!', name: 'y' }] } },
  headers: { 'If-Match': (await call('GET', '/prefs')).j.updatedAt } });
check('v2 PUT 200', r.status, 200);
const v2 = r.j;
check('v2 조건 2건(Z9 버림, 값 아닌 value 버림)', v2.alerts.map(a => a.id), ['c1', 'c2', 'c4']);
check('v2 U1 보존 필드(armSide 포함)', v2.alerts[0], { id: 'c1', event: 'U1', target: 'usdkrw', repeat: 'once', enabled: true, ring: true, value: 1400, dir: 'up', armSide: 'u', name: '달러원 1400 위로' });
check('v2 전체 조정(*)', v2.alerts[1], { id: 'c2', event: 'A1', target: '*', repeat: 'each', enabled: true, strength: 'huge', level: 'alarm' });
check('v2 value 아닌 값 · 모르는 세기 · 모르는 armSide 버림', v2.alerts[2], { id: 'c4', event: 'U2', target: 'kospi', repeat: 'each', enabled: true });
check('v2 settings', { package: v2.settings.package, ringChannel: v2.settings.ringChannel, dailyCap: v2.settings.dailyCap, quietAlarm: v2.settings.quietAlarm,
  noon: v2.settings.briefings.noon, close: v2.settings.briefings.close, B: v2.settings.families.B, A: v2.settings.families.A,
  rememberKey: v2.settings.rememberKey, kakaoFriends: v2.settings.kakaoFriends, n: v2.settings.kakaoRecipients.length,
  r0: v2.settings.kakaoRecipients[0], r1name: v2.settings.kakaoRecipients[1].name.length, r2uuid: v2.settings.kakaoRecipients[2].uuid },
  { package: 'many', ringChannel: 'kakao', dailyCap: 6, quietAlarm: true, noon: true, close: true, B: false, A: true, rememberKey: true, kakaoFriends: true,
    n: 3, r0: { uuid: 'abc', name: '가족 한 명', briefOnly: true }, r1name: 20, r2uuid: '' });
check('v2 문서 v', v2.v, 2);

if (fails) { console.log(`\n${fails}건 실패`); process.exit(1); }
console.log('\n전부 통과');
