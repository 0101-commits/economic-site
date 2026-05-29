/**
 * 경제 대시보드용 CORS 프록시 (Cloudflare Worker)
 * ------------------------------------------------------------------
 * 목적: 정적 사이트(GitHub Pages)의 브라우저에서 직접 호출이 막히는(또는 CORS 차단된)
 *       금융 API 를 안전하게 중계한다. 공개 CORS 프록시(allorigins 등)는 가용성이
 *       들쭉날쭉하고, 특히 네이버 모바일 API 는 Referer/Origin/User-Agent 헤더가
 *       없으면 거부하는데 브라우저는 그 헤더를 직접 설정할 수 없다.
 *       이 Worker 는 타깃별로 적절한 헤더를 주입해 안정적으로 가져온 뒤
 *       Access-Control-Allow-Origin: * 로 응답한다.
 *
 * 보안: 오픈 프록시 남용 방지를 위해 ALLOWED_HOSTS 화이트리스트만 통과시킨다.
 *
 * 호출: GET https://<worker>.workers.dev/?url=<encodeURIComponent(타깃 https URL)>
 * 헬스: GET https://<worker>.workers.dev/         → {ok:true} (설정 확인용)
 *
 * 배포: cloudflare-worker/ 에서  npx wrangler deploy   (README.md 참고)
 */

// 허용 호스트 — 대시보드가 실제로 호출하는 금융 데이터 출처만.
const ALLOWED_HOSTS = [
  // 한국 주식/ETF 등락 Top10 (네이버 증권)
  'm.stock.naver.com',
  'api.stock.naver.com',
  'finance.naver.com',
  // 지수/원자재/변동성(VIX·MOVE) 시세 (Yahoo Finance)
  'query1.finance.yahoo.com',
  'query2.finance.yahoo.com',
  // 시계열 (Stooq)
  'stooq.com',
  'stooq.pl',
  // 공포·탐욕 지수 (CNN)
  'production.dataviz.cnn.io',
  // 변동성 지수 보강 (investing.com — VKOSPI 등 최후 폴백 스크래핑)
  'kr.investing.com',
  'www.investing.com',
  // 실시간 환율
  'open.er-api.com',
  // 뉴스 RSS (선택)
  'news.google.com',
  'www.bing.com',
];

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': '*',
  'Access-Control-Max-Age': '86400',
};

// 타깃 호스트별 주입 헤더 — 브라우저가 못 보내는 Referer/Origin/User-Agent 등.
function originHeaders(host) {
  if (host === 'finance.naver.com' || host.endsWith('stock.naver.com')) {
    return {
      'User-Agent':
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 ' +
        '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
      'Accept': 'application/json,text/plain,*/*',
      'Accept-Language': 'ko-KR,ko;q=0.9',
      'Referer': 'https://m.stock.naver.com/',
      'Origin': 'https://m.stock.naver.com',
    };
  }
  return {
    'User-Agent':
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9,ko;q=0.8',
  };
}

function jsonResponse(obj, status) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: { ...CORS, 'content-type': 'application/json; charset=utf-8' },
  });
}

export default {
  async fetch(request) {
    // CORS preflight
    if (request.method === 'OPTIONS') return new Response(null, { headers: CORS });
    if (request.method !== 'GET') return jsonResponse({ error: 'GET only' }, 405);

    const reqUrl = new URL(request.url);
    const target = reqUrl.searchParams.get('url');

    // 헬스체크 — 파라미터 없이 호출 시 (프론트 설정 확인용)
    if (!target) {
      return jsonResponse({ ok: true, service: 'econ-dashboard-proxy', allowed: ALLOWED_HOSTS });
    }

    let t;
    try { t = new URL(target); } catch { return jsonResponse({ error: 'invalid url param' }, 400); }
    if (t.protocol !== 'https:') return jsonResponse({ error: 'https only' }, 400);
    if (!ALLOWED_HOSTS.includes(t.hostname)) {
      return jsonResponse({ error: 'host not allowed', host: t.hostname }, 403);
    }

    // 짧은 캐시(30초) — 동일 요청 폭주 시 origin/무료 한도 보호
    const cache = caches.default;
    const cacheKey = new Request(reqUrl.toString(), { method: 'GET' });
    const cached = await cache.match(cacheKey);
    if (cached) return cached;

    let upstream;
    try {
      upstream = await fetch(t.toString(), {
        method: 'GET',
        headers: originHeaders(t.hostname),
        // Cloudflare edge 캐시 30초
        cf: { cacheTtl: 30, cacheEverything: true },
        // 응답 지연 방지
        signal: AbortSignal.timeout(12000),
      });
    } catch (e) {
      return jsonResponse({ error: 'upstream fetch failed', detail: String(e) }, 502);
    }

    const body = await upstream.arrayBuffer();
    const headers = new Headers(CORS);
    const ct = upstream.headers.get('content-type');
    if (ct) headers.set('content-type', ct);          // 원본 charset 보존(EUC-KR HTML 등)
    headers.set('Cache-Control', 'public, max-age=30');
    headers.set('X-Proxy-Upstream-Status', String(upstream.status));

    const resp = new Response(body, { status: upstream.status, headers });
    // 성공 응답만 edge 캐시에 저장
    if (upstream.ok) {
      try { await cache.put(cacheKey, resp.clone()); } catch (_) { /* ignore */ }
    }
    return resp;
  },
};
