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
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
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

// ──────────────────────────────────────────────────────────────────
// AI 시황 요약 핸들러 (Anthropic Claude 중계)
// ──────────────────────────────────────────────────────────────────
// 프론트에서 POST /ai 로 { snapshot: {...} } 를 보내면, Worker 시크릿의 ANTHROPIC_API_KEY
// 로 Claude 를 호출해 한국어 시황 브리핑 텍스트를 돌려준다. 키 미설정 시 503 → 프론트는
// 자체 룰기반 요약으로 폴백한다. 비용 보호를 위해 max_tokens 제한 + 본문 크기 제한.
async function handleAiSummary(request, env) {
  const apiKey = env && env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    // 키 미설정 — 프론트가 룰기반 요약으로 폴백하도록 503 + 사유 반환.
    return jsonResponse({ error: 'no_api_key', message: 'ANTHROPIC_API_KEY (Worker secret) 미설정' }, 503);
  }
  // 본문 크기 가드 (남용/사고 방지) — 스냅샷은 작아야 한다.
  const raw = await request.text();
  if (raw.length > 60000) return jsonResponse({ error: 'payload_too_large' }, 413);
  let payload;
  try { payload = JSON.parse(raw || '{}'); } catch { return jsonResponse({ error: 'invalid_json' }, 400); }
  const snapshot = payload.snapshot || payload || {};
  const model = (typeof payload.model === 'string' && payload.model) || 'claude-haiku-4-5-20251001';

  const system =
    '당신은 한국 개인투자자를 위한 금융시장 애널리스트입니다. 제공된 실시간 시장 데이터(JSON)만 ' +
    '근거로, 군더더기 없이 신뢰할 수 있는 "오늘의 마켓 브리핑"을 한국어로 작성하세요. 데이터에 없는 ' +
    '수치는 추정/날조하지 말고 생략합니다. 출력은 간결한 마크다운으로:\n' +
    '1) 한 줄 종합 판단(위험선호/위험회피/중립 + 핵심 근거)\n' +
    '2) 국내 증시 / 해외 증시 / 환율·원자재 / 시장심리 를 각각 1~2문장 불릿\n' +
    '3) 마지막에 "※ 투자 참고용" 한 줄. 총 250자~500자 내외, 과장·매수매도 권유 금지.';
  const userMsg =
    '아래는 현재 시각의 실시간 시장 데이터 스냅샷입니다. 이것만 근거로 브리핑을 작성하세요.\n\n' +
    '```json\n' + JSON.stringify(snapshot).slice(0, 50000) + '\n```';

  try {
    const resp = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model,
        max_tokens: 900,
        system,
        messages: [{ role: 'user', content: userMsg }],
      }),
      signal: AbortSignal.timeout(25000),
    });
    const data = await resp.json().catch(() => null);
    if (!resp.ok || !data) {
      return jsonResponse({ error: 'anthropic_error', status: resp.status, detail: data }, 502);
    }
    const text = Array.isArray(data.content)
      ? data.content.filter(b => b && b.type === 'text').map(b => b.text).join('\n').trim()
      : '';
    if (!text) return jsonResponse({ error: 'empty_response', detail: data }, 502);
    return jsonResponse({ ok: true, summary: text, model: data.model, usage: data.usage });
  } catch (e) {
    return jsonResponse({ error: 'upstream_failed', detail: String(e) }, 502);
  }
}

export default {
  async fetch(request, env) {
    // CORS preflight
    if (request.method === 'OPTIONS') return new Response(null, { headers: CORS });

    // 🤖 AI 시황 요약 — POST /ai : 프론트가 보낸 '그 순간의 시장 스냅샷'을 Anthropic(Claude)
    // 로 중계해 자연어 브리핑을 생성한다. 키는 Worker 시크릿 ANTHROPIC_API_KEY 로만 보관해
    // 브라우저에 노출되지 않는다. (정적 사이트에서 안전하게 LLM 을 쓰기 위한 경로.)
    if (request.method === 'POST') {
      const purl = new URL(request.url);
      if (purl.pathname === '/ai' || purl.searchParams.get('ai') === '1') {
        return handleAiSummary(request, env);
      }
      return jsonResponse({ error: 'POST is only supported at /ai' }, 404);
    }
    if (request.method !== 'GET') return jsonResponse({ error: 'GET only' }, 405);

    const reqUrl = new URL(request.url);
    const target = reqUrl.searchParams.get('url');

    // 헬스체크 — 파라미터 없이 호출 시 (프론트 설정 확인용)
    if (!target) {
      return jsonResponse({ ok: true, service: 'ecom-dashboard-proxy', allowed: ALLOWED_HOSTS });
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
