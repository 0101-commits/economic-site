// 넘김 장치(_worker.js) 자가 점검 — 원본 주소 조립 · 리다이렉트 고쳐 쓰기 · 메서드 제한 · noindex
// · 숫자 파일은 저장소에서(번호 → raw → raw main → 원본 차례) · 허용 목록이 collect_site.mjs 와 같은지.
// 실행: node cloudflare-pages/test_proxy.mjs   (전역 fetch 를 가짜로 바꾼다)
import fs from 'node:fs';
import worker, { DATA, DATA_FILES, DATA_DIRS } from './_worker.js';

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

await get('/js/app1.min.js?v=1');
ok(seen.url === 'https://0101-commits.github.io/economic-site/js/app1.min.js?v=1', '경로·쿼리 유지');

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

// ── 숫자 파일: 배포 없이 저장소에서 ──────────────────────────────────────────
// 허용 목록 = scripts/collect_site.mjs 의 .json (두 곳에 손으로 적은 목록은 어긋난다 — 글자로 맞춰 본다)
const site = fs.readFileSync(new URL('../scripts/collect_site.mjs', import.meta.url), 'utf8');
const files = [...site.match(/const FILES = \[([\s\S]*?)\];/)[1].matchAll(/'([^']+)'/g)].map(m => m[1]).filter(f => f.endsWith('.json'));
const dirs = [...site.match(/const DIRS = \{([\s\S]*?)\};/)[1].matchAll(/(\w+): \[([^\]]*)\]/g)]
  .filter(m => m[2].includes("'.json'")).map(m => m[1]);
ok(JSON.stringify([...files].sort()) === JSON.stringify([...DATA_FILES].sort()), `DATA_FILES = collect_site FILES 의 .json (${files.length})`);
ok(JSON.stringify([...dirs].sort()) === JSON.stringify([...DATA_DIRS].sort()), `DATA_DIRS = collect_site DIRS 의 .json 폴더 (${dirs.join(',')})`);
for (const p of ['/data.json', '/bundles/home.json', '/events/latest.json', '/events/history/a-1.json', '/briefs/2026-11-07.json'])
  ok(DATA.test(p), `숫자 파일: ${p}`);
for (const p of ['/alerts_config.json', '/toss_snapshot.json', '/bundles/x.js', '/js/app1.js', '/next/bundles/home.json', '/bundles/', '/legacy.html', '/data.json/x'])
  ok(!DATA.test(p), `숫자 파일 아님: ${p}`);

const SHA = 'a'.repeat(40);
let calls = [];
let refs = () => new Response(`001e# service=git-upload-pack\n${'b'.repeat(40)} refs/heads/mainx\n${SHA} refs/heads/main\n`, { status: 200 });
let rawRes = () => new Response('{"x":1}', { status: 200, headers: { etag: '"e1"', 'content-type': 'text/plain' } });
reply = () => new Response('old', { status: 200, headers: { 'content-type': 'application/json' } });
globalThis.fetch = async (url, init) => {
  const u = String(url); calls.push(u); seen = { url: u, init };
  if (u.includes('/info/refs')) return refs();
  if (u.startsWith('https://raw.githubusercontent.com/')) return rawRes(u);
  return reply();
};

// ① 번호 조회 실패 → raw 의 main 주소
refs = () => new Response('no', { status: 500 });
calls = []; r = await get('/data_meta.json');
ok(calls[1] === 'https://raw.githubusercontent.com/0101-commits/economic-site/main/data_meta.json', '번호 실패 → raw main');
ok(r.status === 200 && r.headers.get('x-ecom-src').startsWith('repo-main (refs 500'), `x-ecom-src = ${r.headers.get('x-ecom-src')}`);

// ② raw 도 실패 → GitHub Pages 원본(경로·쿼리 그대로)
rawRes = () => new Response('', { status: 503 });
calls = []; r = await get('/data.json?v=2');
ok(calls.at(-1) === 'https://0101-commits.github.io/economic-site/data.json?v=2', 'raw 도 실패 → Pages 원본');
ok(r.status === 200 && (await r.text()) === 'old' && r.headers.get('x-ecom-src').startsWith('pages (refs 500'), `x-ecom-src = ${r.headers.get('x-ecom-src')}`);

// ③ 정상 — main 줄만 정확히 고른다(mainx 아님) · 번호 주소 · json 머리 · 원본은 안 부른다
refs = () => new Response(`${'b'.repeat(40)} refs/heads/mainx\n${SHA} refs/heads/main\n`, { status: 200 });
rawRes = () => new Response('{"x":1}', { status: 200, headers: { etag: '"e1"', 'content-type': 'text/plain' } });
calls = []; r = await get('/bundles/home.json?t=9');
ok(calls[0].includes('/info/refs') && calls[1] === `https://raw.githubusercontent.com/0101-commits/economic-site/${SHA}/bundles/home.json`, '번호 → raw/<번호>/경로');
ok(seen.init.cf && seen.init.cf.cacheTtl === 86400, '번호 주소는 오래 캐시');
ok(r.status === 200 && (await r.text()) === '{"x":1}', '본문 그대로');
ok(r.headers.get('x-ecom-src') === `repo@${SHA.slice(0, 7)}`, 'x-ecom-src = repo@번호');
ok(r.headers.get('content-type').startsWith('application/json') && r.headers.get('etag') === '"e1"', 'json 머리 · etag');
ok(!calls.some(u => u.includes('github.io')), '원본은 안 부른다');

// ④ 20초 안의 다음 요청은 번호를 다시 묻지 않는다 · 같은 etag 면 304
calls = []; r = await get('/data.json', 'GET', { 'if-none-match': '"e1"' });
ok(!calls.some(u => u.includes('/info/refs')), '번호 재사용(20초)');
ok(r.status === 304 && (await r.text()) === '', 'if-none-match 일치 → 304');
r = await get('/data.json', 'HEAD');
ok(r.status === 200 && (await r.text()) === '', 'HEAD → 본문 없음');

// ⑤ 허용 목록 밖은 저장소로 안 간다
calls = []; await get('/alerts_config.json');
ok(calls.length === 1 && calls[0] === 'https://0101-commits.github.io/economic-site/alerts_config.json', 'alerts_config.json 은 원본(404)으로만');

process.exit(fail ? 1 : 0);
