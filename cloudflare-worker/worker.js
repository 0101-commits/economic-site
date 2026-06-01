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
  'rss.daum.net',
  'news.daum.net',
];

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': '*',
  'Access-Control-Max-Age': '86400',
};

// 타깃 호스트별 주입 헤더 — 브라우저가 못 보내는 Referer/Origin/User-Agent 등.
function originHeaders(host) {
  // m.stock.naver.com / api.stock.naver.com → 모바일 JSON API: 모바일 UA + m.stock Referer/Origin
  if (host.endsWith('stock.naver.com')) {
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
  // finance.naver.com → 데스크톱 시세 HTML(sise_rise/sise_fall.naver) 스크래핑용:
  // 데스크톱 UA + finance Referer. (모바일 UA 로 요청하면 모바일/리다이렉트 HTML 이 와서
  // 데스크톱 표 구조(table.type_2)를 못 파싱한다. 서버 fetch_data.py 와 동일한 헤더.)
  if (host === 'finance.naver.com') {
    return {
      'User-Agent':
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
        '(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
      'Referer': 'https://finance.naver.com/',
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
  // 본문 크기 가드 (남용/사고 방지) — 스냅샷은 작아야 한다.
  const raw = await request.text();
  if (raw.length > 60000) return jsonResponse({ error: 'payload_too_large' }, 413);
  let payload;
  try { payload = JSON.parse(raw || '{}'); } catch { return jsonResponse({ error: 'invalid_json' }, 400); }
  const snapshot = payload.snapshot || payload || {};

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

  // 진단 정보 — 어떤 엔진을 왜 못 썼는지 응답에 담아 프론트/사용자가 원인을 알 수 있게 한다.
  const diag = { gemini: !!(env && (env.GEMINI_API_KEY || env.GOOGLE_API_KEY || env.GEMINI_KEY)), aiBinding: !!(env && env.AI), anthropicKey: !!(env && env.ANTHROPIC_API_KEY), tried: [] };

  // ── 1) Google Gemini (무료 API) — env.GEMINI_API_KEY 시크릿이 있으면 최우선 사용 ──
  // 무료 키 발급: https://aistudio.google.com/apikey (Google AI Studio). 키는 Worker 시크릿에만 보관.
  // 모델 가용성/한도가 바뀔 수 있어 여러 모델을 순차 시도한다.
  // 키 이름은 환경마다 다르게 넣는 경우가 많아(별칭) 여러 후보를 허용 → 잘못 명명해도 동작.
  const geminiKey = env && (env.GEMINI_API_KEY || env.GOOGLE_API_KEY || env.GEMINI_KEY);
  if (geminiKey) {
    const gModels = [];
    if (typeof payload.geminiModel === 'string' && payload.geminiModel) gModels.push(payload.geminiModel);
    // 2.5 Pro 는 무료 등급 한도가 매우 작아 429(quota exceeded)가 상시 발생 → 제외하고,
    // '고성능 최신 + 무료 한도 넉넉'한 gemini-2.5-flash 를 1순위로. (실측: 2.5-flash 200 OK)
    // 모델명이 버전업으로 사라져도 견디도록 '-latest' 별칭을 폴백에 섞는다(없으면 404 → 다음 후보 자동 시도).
    // payload.geminiModel 로 강제 지정도 여전히 가능.
    gModels.push('gemini-2.5-flash', 'gemini-flash-latest', 'gemini-2.0-flash', 'gemini-2.5-flash-lite', 'gemini-1.5-flash');
    for (const gm of gModels) {
      try {
        const resp = await fetch('https://generativelanguage.googleapis.com/v1beta/models/' + gm + ':generateContent', {
          method: 'POST',
          headers: { 'content-type': 'application/json', 'x-goog-api-key': geminiKey },
          body: JSON.stringify({
            system_instruction: { parts: [{ text: system }] },
            contents: [{ role: 'user', parts: [{ text: userMsg }] }],
            generationConfig: { maxOutputTokens: 800, temperature: 0.7 },
          }),
          signal: AbortSignal.timeout(25000),
        });
        const data = await resp.json().catch(() => null);
        if (resp.ok && data && Array.isArray(data.candidates) && data.candidates[0]) {
          const parts = (data.candidates[0].content && data.candidates[0].content.parts) || [];
          const text = parts.map(p => (p && p.text) || '').join('').trim();
          if (text) return jsonResponse({ ok: true, summary: text, model: 'gemini/' + gm, engine: 'gemini' });
          diag.tried.push('gemini/' + gm + ':empty(' + (data.candidates[0].finishReason || '') + ')');
        } else {
          const em = (data && data.error && data.error.message) || '';
          diag.tried.push('gemini/' + gm + ':HTTP' + (resp && resp.status) + ':' + String(em).slice(0, 80));
        }
      } catch (e) { diag.tried.push('gemini/' + gm + ':' + String((e && e.message) || e).slice(0, 80)); }
    }
  }

  // ── 2) Cloudflare Workers AI (무료·키 불필요) — env.AI 바인딩이 있으면 사용 ──
  // wrangler.jsonc 의 "ai": {"binding":"AI"} 만 있으면 동작. 무료 플랜 일 10,000 Neurons.
  // 모델 가용성이 계정/리전마다 달라 여러 모델을 순차 시도한다.
  if (env && env.AI) {
    const models = [];
    if (typeof payload.cfModel === 'string' && payload.cfModel) models.push(payload.cfModel);
    models.push(
      '@cf/meta/llama-3.1-8b-instruct',
      '@cf/meta/llama-3-8b-instruct',
      '@cf/qwen/qwen1.5-14b-chat-awq',
      '@cf/mistral/mistral-7b-instruct-v0.1',
    );
    for (const m of models) {
      try {
        const out = await env.AI.run(m, {
          messages: [{ role: 'system', content: system }, { role: 'user', content: userMsg }],
          max_tokens: 800,
        });
        const text = (out && (out.response || (out.result && out.result.response) || '') || '').trim();
        if (text) return jsonResponse({ ok: true, summary: text, model: 'cloudflare/' + m, engine: 'workers-ai' });
        diag.tried.push(m + ':empty');
      } catch (e) {
        diag.tried.push(m + ':' + String((e && e.message) || e).slice(0, 100));
      }
    }
  } else {
    diag.tried.push('no-AI-binding(wrangler.jsonc ai 바인딩/계정 Workers AI 확인)');
  }

  // ── 3) Anthropic Claude (선택) — ANTHROPIC_API_KEY 시크릿이 설정된 경우만 ──
  const apiKey = env && env.ANTHROPIC_API_KEY;
  if (apiKey) {
    const model = (typeof payload.model === 'string' && payload.model) || 'claude-haiku-4-5-20251001';
    try {
      const resp = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-api-key': apiKey,
          'anthropic-version': '2023-06-01',
        },
        body: JSON.stringify({ model, max_tokens: 900, system, messages: [{ role: 'user', content: userMsg }] }),
        signal: AbortSignal.timeout(25000),
      });
      const data = await resp.json().catch(() => null);
      if (resp.ok && data && Array.isArray(data.content)) {
        const text = data.content.filter(b => b && b.type === 'text').map(b => b.text).join('\n').trim();
        if (text) return jsonResponse({ ok: true, summary: text, model: data.model, engine: 'anthropic', usage: data.usage });
      }
      diag.tried.push('anthropic:HTTP' + (resp && resp.status));
    } catch (e) { diag.tried.push('anthropic:' + String((e && e.message) || e).slice(0, 80)); }
  }

  // ── 4) 모두 불가 → 503 (프론트가 자체 룰기반 요약으로 폴백) + 진단 ──
  return jsonResponse({
    error: 'no_ai_available',
    message: 'AI 엔진이 설정되지 않았습니다 — 무료 GEMINI_API_KEY(발급: https://aistudio.google.com/apikey) 시크릿을 Worker 에 추가하거나, Workers AI 바인딩 / ANTHROPIC_API_KEY 중 하나가 필요합니다. 프론트는 룰기반 요약으로 폴백합니다.',
    diag,
  }, 503);
}

// 진단용 — 실제 Gemini 호출을 최소 프롬프트로 시도해 정확한 상태/오류 메시지를 돌려준다.
// GET /ai?test=1 에서 호출. (키가 거부되는지 / API 미활성 / 모델 문제인지 즉시 식별)
async function _testGemini(key) {
  // 운영 경로(handleAiSummary)와 동일하게 flash 계열만 점검한다. gemini-2.5-pro 는 무료 한도가
  // 매우 작아 429 가 상시 떠 진단을 '실패처럼' 오해하게 만들고, 실제 요약에서도 쓰지 않으므로 제외.
  // 첫 성공에서 즉시 반환하므로 정상 키라면 attempts 가 비거나 거의 비어 보인다.
  const models = ['gemini-2.5-flash', 'gemini-flash-latest', 'gemini-2.0-flash', 'gemini-1.5-flash'];
  const attempts = [];
  for (const m of models) {
    try {
      const r = await fetch('https://generativelanguage.googleapis.com/v1beta/models/' + m + ':generateContent', {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-goog-api-key': key },
        body: JSON.stringify({ contents: [{ role: 'user', parts: [{ text: 'OK' }] }], generationConfig: { maxOutputTokens: 5 } }),
        signal: AbortSignal.timeout(15000),
      });
      const d = await r.json().catch(() => null);
      if (r.ok) return { ok: true, model: m, status: r.status, attempts };
      attempts.push({ model: m, status: r.status, error: ((d && d.error && d.error.message) || '').slice(0, 200) });
    } catch (e) {
      attempts.push({ model: m, error: String((e && e.message) || e).slice(0, 120) });
    }
  }
  return { ok: false, attempts };
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
    // AI 헬스체크 (GET /ai) — Workers AI 바인딩/Anthropic 키 설정 여부를 즉시 확인.
    // 브라우저에서 https://<worker>/ai 를 열어 {aiBinding:true} 가 보이면 무료 AI 사용 가능.
    if (reqUrl.pathname === '/ai') {
      const geminiKey = env && (env.GEMINI_API_KEY || env.GOOGLE_API_KEY || env.GEMINI_KEY);
      const hasGemini = !!geminiKey;
      const out = {
        ok: true, service: 'ai-health',
        geminiKey: hasGemini,
        aiBinding: !!(env && env.AI),
        anthropicKey: !!(env && env.ANTHROPIC_API_KEY),
        engine: hasGemini ? 'gemini' : (env && env.AI ? 'workers-ai' : (env && env.ANTHROPIC_API_KEY ? 'anthropic' : 'none(rule-based)')),
        hint: hasGemini ? 'Google Gemini 무료 API 사용 가능'
            : (env && env.AI) ? 'Workers AI 사용 가능'
            : 'GEMINI_API_KEY 시크릿을 추가하면 무료 Gemini 사용 가능 (aistudio.google.com/apikey)',
      };
      // GET /ai?test=1 — 실제 Gemini 호출을 시도해 정확한 성공/오류를 함께 반환(진단용).
      if (reqUrl.searchParams.get('test') === '1' && hasGemini) {
        out.geminiTest = await _testGemini(geminiKey);
      }
      return jsonResponse(out);
    }
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
