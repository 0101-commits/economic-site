// ecom-terminal.pages.dev 넘김 장치 — 옛 GitHub Pages 원본을 그대로 비춰 준다.
// 화면·데이터 갱신은 지금처럼 GitHub Actions → GitHub Pages 가 하고, 이 주소는 읽기 전용 거울이다.
// GET/HEAD 만 받고, 요청 머리는 화이트리스트만 넘기며, 원본의 리다이렉트는 상대 경로로 고쳐 쓴다.
const ORIGIN = 'https://0101-commits.github.io/economic-site';
const PASS = ['accept', 'accept-language', 'if-none-match', 'if-modified-since'];

export default {
  async fetch(request) {
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Method Not Allowed', { status: 405, headers: { allow: 'GET, HEAD' } });
    }
    const u = new URL(request.url);
    const headers = new Headers();
    for (const k of PASS) { const v = request.headers.get(k); if (v) headers.set(k, v); }
    const res = await fetch(ORIGIN + u.pathname + u.search, {
      method: request.method, headers, redirect: 'manual',
    });
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
  },
};
