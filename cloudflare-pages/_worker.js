// ecom-terminal.pages.dev 앞단 — 화면(코드)은 GitHub Pages 원본을 비추고, 숫자 파일은 배포 없이 저장소에서 바로 내준다.
// GET/HEAD 만 받고, 요청 머리는 화이트리스트만 넘기며, 원본의 리다이렉트는 상대 경로로 고쳐 쓴다.
//
// 숫자 파일(2026-11-07) — 배포가 하루 411번이었고 그중 404번이 데이터 커밋 때문이었다. 배포는 GitHub 쪽 일시 장애로
// 가끔 실패해 실패 알림이 쌓였다. 그래서 숫자 파일은 배포를 거치지 않는다:
//   ① main 최신 커밋 번호 = git 공개 주소 info/refs(토큰 없음, 20초 재사용)
//   ② raw.githubusercontent.com/<번호>/<경로> — 번호가 박힌 주소는 내용이 안 바뀌어 오래 캐시해도 된다
//   ③ ①·② 가 안 되면 raw 의 main 주소(GitHub CDN 이 최대 5분 붙잡는다 — 질의 꼬리도 무시, 2026-11-07 실측)
//   ④ 그것도 안 되면 GitHub Pages 원본(코드 배포 · 6시간마다 배포분이라 늦을 수 있다)
// 어느 길로 나갔는지는 머리 x-ecom-src 에 적는다 — watchdog 이 사이트 숫자가 저장소보다 늦은지 본다.
// 내주는 경로는 scripts/collect_site.mjs 의 허용 목록 중 .json 과 같아야 한다(test_proxy.mjs 가 맞춰 본다).
const ORIGIN = 'https://0101-commits.github.io/economic-site';
const REPO = '0101-commits/economic-site';
const PASS = ['accept', 'accept-language', 'if-none-match', 'if-modified-since'];
const UA = 'ecom-terminal-pages';
const SHA_TTL_MS = 20000;

export const DATA_FILES = [
  'data.json', 'data_meta.json', 'merblog.json', 'mer_signals.json',
  'fundamentals.json', 'link_status.json', 'alerts_state.json', 'history.json',
];
export const DATA_DIRS = ['bundles', 'events', 'briefs'];
const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
export const DATA = new RegExp(
  `^/(?:${DATA_FILES.map(esc).join('|')}|(?:${DATA_DIRS.join('|')})(?:/[\\w.-]+)+\\.json)$`);

let memo = { sha: null, at: 0 };   // 같은 isolate 안에서 20초 재사용(Cache API 와 이중)

async function headSha() {
  const now = Date.now();
  if (memo.sha && now - memo.at < SHA_TTL_MS) return memo.sha;
  const key = new Request('https://ecom-terminal.internal/head-sha');
  try {
    const hit = await caches.default.match(key);
    if (hit) { memo = { sha: await hit.text(), at: now }; return memo.sha; }
  } catch (_) { /* 캐시 없이 간다 */ }
  const r = await fetch(`https://github.com/${REPO}.git/info/refs?service=git-upload-pack`, { headers: { 'user-agent': UA } });
  if (!r.ok) throw new Error(`refs ${r.status}`);
  const m = (await r.text()).match(/([0-9a-f]{40}) refs\/heads\/main\b/);
  if (!m) throw new Error('refs: main 없음');
  memo = { sha: m[1], at: now };
  try { await caches.default.put(key, new Response(m[1], { headers: { 'cache-control': `max-age=${SHA_TTL_MS / 1000}` } })); }
  catch (_) { /* 메모만으로 충분 */ }
  return m[1];
}

async function raw(ref, path, request, cacheTtl, src) {
  const r = await fetch(`https://raw.githubusercontent.com/${REPO}/${ref}${path}`, {
    method: request.method, headers: { 'user-agent': UA }, cf: { cacheEverything: true, cacheTtl },
  });
  if (!r.ok) throw new Error(`raw ${r.status}`);
  const h = new Headers({
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'max-age=15',
    'access-control-allow-origin': '*',
    'x-robots-tag': 'noindex',
    'x-ecom-src': src,
  });
  const etag = r.headers.get('etag');
  if (etag) {
    h.set('etag', etag);
    if (request.headers.get('if-none-match') === etag) return new Response(null, { status: 304, headers: h });
  }
  return new Response(request.method === 'HEAD' ? null : r.body, { status: 200, headers: h });
}

async function fromRepo(request, path) {
  let why;
  try { const sha = await headSha(); return await raw(sha, path, request, 86400, `repo@${sha.slice(0, 7)}`); }
  catch (e) { why = String(e.message || e).slice(0, 40); }
  try { return await raw('main', path, request, 60, `repo-main (${why})`); }
  catch (e) { why += ` · ${String(e.message || e).slice(0, 40)}`; }
  const res = await mirror(request, new URL(request.url));
  const h = new Headers(res.headers);
  h.set('x-ecom-src', `pages (${why})`);
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
}

async function mirror(request, u) {
  const headers = new Headers();
  for (const k of PASS) { const v = request.headers.get(k); if (v) headers.set(k, v); }
  const res = await fetch(ORIGIN + u.pathname + u.search, { method: request.method, headers, redirect: 'manual' });
  const out = new Headers(res.headers);
  const loc = out.get('location');
  if (loc) {
    try {
      const l = new URL(loc, ORIGIN + u.pathname);
      const base = new URL(ORIGIN + '/');
      if (l.origin === base.origin && l.pathname.startsWith(base.pathname)) {
        out.set('location', '/' + l.pathname.slice(base.pathname.length) + l.search + l.hash);
      }
    } catch (_) { /* 그대로 둔다 */ }
  }
  out.set('x-robots-tag', 'noindex');
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers: out });
}

export default {
  async fetch(request) {
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Method Not Allowed', { status: 405, headers: { allow: 'GET, HEAD' } });
    }
    const u = new URL(request.url);
    if (DATA.test(u.pathname)) return fromRepo(request, u.pathname);
    return mirror(request, u);
  },
};
