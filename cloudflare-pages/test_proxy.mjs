// 넘김 장치(_worker.js) 자가 점검 — 원본 주소 조립 · 리다이렉트 고쳐 쓰기 · 메서드 제한 · noindex.
// 실행: node cloudflare-pages/test_proxy.mjs   (전역 fetch 를 가짜로 바꾼다)
import worker from './_worker.js';

let fail = 0;
const ok = (c, m) => { if (c) console.log('OK  ', m); else { fail++; console.log('FAIL', m); } };

let seen = null;
let reply = () => new Response('hi', { status: 200, headers: { 'content-type': 'text/html' } });
globalThis.fetch = async (url, init) => { seen = { url: String(url), init }; return reply(); };
const get = (path, method = 'GET', headers = {}) =>
  worker.fetch(new Request('https://ecom-terminal.pages.dev' + path, { method, headers }));

let r = await get('/');
ok(seen.url === 'https://0101-commits.github.io/economic-site/', 'GET / -> 원본 루트');
ok(r.status === 200 && (await r.text()) === 'hi', '본문 그대로');
ok(r.headers.get('x-robots-tag') === 'noindex', 'X-Robots-Tag: noindex');

await get('/data.json?v=1');
ok(seen.url === 'https://0101-commits.github.io/economic-site/data.json?v=1', '경로·쿼리 유지');

await get('/', 'GET', { accept: 'text/html', cookie: 'a=b', authorization: 'x', 'if-none-match': '"e"' });
const h = new Headers(seen.init.headers);
ok(h.get('accept') === 'text/html' && h.get('if-none-match') === '"e"', 'accept·if-none-match 전달');
ok(!h.has('cookie') && !h.has('authorization'), '쿠키·인증 머리는 전달하지 않음');
ok(seen.init.redirect === 'manual', "redirect:'manual'");

reply = () => new Response(null, { status: 301, headers: { location: 'https://0101-commits.github.io/economic-site/next/' } });
r = await get('/next');
ok(r.status === 301 && r.headers.get('location') === '/next/', '원본 301 Location -> /next/');

reply = () => new Response('x', { status: 200 });
r = await get('/', 'POST');
ok(r.status === 405, 'POST -> 405');
r = await get('/', 'HEAD');
ok(r.status === 200, 'HEAD 허용');

process.exit(fail ? 1 : 0);
