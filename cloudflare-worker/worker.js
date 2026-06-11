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
  // 실 제조업 PMI(50기준) 스크래핑 — fetch_data.py 가 GitHub Actions IP 차단 시 이 Worker 경유
  'tradingeconomics.com',
  'www.tradingeconomics.com',
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
        // Gemini 2.5 계열은 'thinking' 모델 → 출력 토큰이 작으면 내부 사고(thinking)에 다 소진해
        // 본문 텍스트가 빈 채 finishReason=MAX_TOKENS 로 끝난다(요약 실패의 주원인). 요약엔 추론이
        // 불필요하므로 2.5 계열은 thinking 을 끄고(thinkingBudget:0) 출력 토큰도 넉넉히 준다.
        // (2.0/1.5 계열은 thinkingConfig 미지원 → 400 방지 위해 미적용.)
        const genCfg = { maxOutputTokens: 2048, temperature: 0.7 };
        if (gm.indexOf('gemini-2.5') === 0) genCfg.thinkingConfig = { thinkingBudget: 0 };
        const resp = await fetch('https://generativelanguage.googleapis.com/v1beta/models/' + gm + ':generateContent', {
          method: 'POST',
          headers: { 'content-type': 'application/json', 'x-goog-api-key': geminiKey },
          body: JSON.stringify({
            system_instruction: { parts: [{ text: system }] },
            contents: [{ role: 'user', parts: [{ text: userMsg }] }],
            generationConfig: genCfg,
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
        body: JSON.stringify({
          contents: [{ role: 'user', parts: [{ text: '"정상"이라고만 한국어로 답하세요.' }] }],
          generationConfig: (function () { const g = { maxOutputTokens: 256 }; if (m.indexOf('gemini-2.5') === 0) g.thinkingConfig = { thinkingBudget: 0 }; return g; })(),
        }),
        signal: AbortSignal.timeout(15000),
      });
      const d = await r.json().catch(() => null);
      // HTTP 200 만으로 성공 처리하지 않는다 — thinking 모델은 200 이어도 본문이 빌 수 있어
      // (운영 경로 handleAiSummary 와 동일하게) '실제 텍스트' 가 있어야 ok 로 본다.
      if (r.ok && d && Array.isArray(d.candidates) && d.candidates[0]) {
        const parts = (d.candidates[0].content && d.candidates[0].content.parts) || [];
        const text = parts.map(p => (p && p.text) || '').join('').trim();
        if (text) return { ok: true, model: m, status: r.status, attempts };
        attempts.push({ model: m, status: r.status, error: 'empty(' + (d.candidates[0].finishReason || '') + ')' });
      } else {
        attempts.push({ model: m, status: r.status, error: ((d && d.error && d.error.message) || '').slice(0, 200) });
      }
    } catch (e) {
      attempts.push({ model: m, error: String((e && e.message) || e).slice(0, 120) });
    }
  }
  return { ok: false, attempts };
}

// ──────────────────────────────────────────────────────────────────
// 📲 투자 현황 알림 설정 동기화 — GET/POST /portfolio
// ──────────────────────────────────────────────────────────────────
// 프론트('투자 현황' 페이지)가 카카오 알림 조건을 POST 하면, GitHub Contents API 로
// 저장소 alerts_config.json 에 커밋한다(브라우저엔 GitHub 토큰을 노출할 수 없어 Worker 가 중계).
// 그 파일을 GitHub Actions(stock-alerts.yml)가 장중 15분마다 평가해 카카오톡으로 발송한다.
//   필요한 시크릿: GH_DISPATCH_TOKEN (Contents: Read and write — kakao cron 과 공용)
//   선택 시크릿: ALERTS_SYNC_KEY — 설정 시 body.key 가 일치해야 저장 허용(임의 쓰기 방지).
//   주의: 평단가/수량은 프론트가 보내지 않는다(공개 저장소) — 알림 조건만 저장.
const ALERTS_CONFIG_PATH = 'alerts_config.json';
const ALERT_TYPES = ['price_above', 'price_below', 'pct_change', 'high52', 'low52',
                     'vol_surge', 'golden_cross', 'dead_cross'];

async function _ghContents(env, method, bodyObj) {
  const url = `https://api.github.com/repos/${GH_REPO}/contents/${ALERTS_CONFIG_PATH}` +
              (method === 'GET' ? '?ref=main' : '');
  const r = await fetch(url, {
    method,
    headers: {
      'Authorization': 'Bearer ' + env.GH_DISPATCH_TOKEN,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'ecom-portfolio-sync',
      ...(bodyObj ? { 'Content-Type': 'application/json' } : {}),
    },
    body: bodyObj ? JSON.stringify(bodyObj) : undefined,
    signal: AbortSignal.timeout(15000),
  });
  const j = await r.json().catch(() => null);
  return { status: r.status, json: j };
}

function _sanitizeAlerts(raw) {
  // 임의 JSON 이 저장소에 커밋되지 않도록 알려진 필드만 골라 담는다.
  const out = [];
  for (const a of (Array.isArray(raw) ? raw.slice(0, 200) : [])) {
    if (!a || typeof a !== 'object') continue;
    const type = String(a.type || '');
    if (!ALERT_TYPES.includes(type)) continue;
    const symbol = String(a.symbol || '').slice(0, 16);
    if (!/^[A-Za-z0-9.\-^=]{1,16}$/.test(symbol)) continue;
    const num = v => (typeof v === 'number' && isFinite(v)) ? v : null;
    out.push({
      id: String(a.id || '').slice(0, 32) || ('a' + Math.random().toString(36).slice(2, 10)),
      symbol,
      market: a.market === 'US' ? 'US' : 'KR',
      yahoo: a.yahoo ? String(a.yahoo).slice(0, 20) : null,
      name: String(a.name || symbol).slice(0, 60),
      type,
      value: num(a.value),
      maShort: num(a.maShort),
      maLong: num(a.maLong),
      limit: a.limit === 'cool60' ? 'cool60' : 'daily',
      enabled: a.enabled !== false,
    });
  }
  return out;
}

async function handlePortfolioGet(env) {
  if (!env || !env.GH_DISPATCH_TOKEN) return jsonResponse({ error: 'no_github_token' }, 503);
  const { status, json } = await _ghContents(env, 'GET');
  if (status === 404) return jsonResponse({ ok: true, alerts: [], updatedAt: null });
  if (status !== 200 || !json || !json.content) {
    return jsonResponse({ error: 'github_read_failed', status }, 502);
  }
  try {
    // GitHub 는 base64 본문을 개행 포함으로 준다. UTF-8(한글 종목명) 안전 디코드.
    const bin = atob(String(json.content).replace(/\n/g, ''));
    const bytes = Uint8Array.from(bin, c => c.charCodeAt(0));
    const cfg = JSON.parse(new TextDecoder().decode(bytes));
    return jsonResponse({ ok: true, alerts: cfg.alerts || [], updatedAt: cfg.updatedAt || null });
  } catch {
    return jsonResponse({ error: 'config_parse_failed' }, 502);
  }
}

// SHA-256 hex — 동기화 키 해시 검증용
async function _sha256Hex(s) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(s)));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}

async function handlePortfolioPost(request, env) {
  if (!env || !env.GH_DISPATCH_TOKEN) return jsonResponse({ error: 'no_github_token' }, 503);
  const raw = await request.text();
  if (raw.length > 120000) return jsonResponse({ error: 'payload_too_large' }, 413);
  let body;
  try { body = JSON.parse(raw || '{}'); } catch { return jsonResponse({ error: 'invalid_json' }, 400); }
  // 동기화 키 검증 — 프론트는 키의 SHA-256 해시(keyHash)만 보낸다 (평문 키는 전송/저장 안 함).
  // 구버전 클라이언트의 평문 body.key 도 당분간 호환 허용.
  if (env.ALERTS_SYNC_KEY) {
    const expected = await _sha256Hex(env.ALERTS_SYNC_KEY);
    const okHash = body.keyHash && String(body.keyHash).toLowerCase() === expected;
    const okLegacy = body.key && String(body.key) === String(env.ALERTS_SYNC_KEY);
    if (!okHash && !okLegacy) return jsonResponse({ error: 'unauthorized' }, 401);
  }
  const alerts = _sanitizeAlerts(body.alerts);
  const cfg = { version: 1, updatedAt: new Date().toISOString(), alerts };
  // 기존 파일 sha 조회(업데이트 시 필수) → PUT 커밋
  const cur = await _ghContents(env, 'GET');
  const sha = (cur.status === 200 && cur.json && cur.json.sha) ? cur.json.sha : undefined;
  const content = JSON.stringify(cfg, null, 2) + '\n';
  // UTF-8 안전 base64 인코딩 (한글 종목명 포함) — 스프레드 인자 한도 회피를 위해 청크 처리
  const bytes = new TextEncoder().encode(content);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 8192) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
  }
  const b64 = btoa(bin);
  const put = await _ghContents(env, 'PUT', {
    message: `alerts: 카카오 알림 설정 동기화 (${alerts.length}개, web)`,
    content: b64,
    branch: 'main',
    ...(sha ? { sha } : {}),
  });
  if (put.status !== 200 && put.status !== 201) {
    return jsonResponse({ error: 'github_write_failed', status: put.status,
                          detail: put.json && put.json.message }, 502);
  }
  return jsonResponse({ ok: true, count: alerts.length });
}

// ──────────────────────────────────────────────────────────────────
// ⏰ Cron Trigger 핸들러 — 카카오 시황 자동 발송 (정시성 보강)
// ──────────────────────────────────────────────────────────────────
// wrangler.jsonc 의 triggers.crons(각 슬롯 :02 UTC = KST 07~17시 매시간·20·22시 :03 발송)에 따라 호출된다.
// GitHub Actions 의 schedule 은 best-effort 라 며칠씩 누락되지만, Cloudflare cron 은 정시성이 좋고
// on-demand 로 GitHub 워크플로를 깨우면 그 실행은 스케줄 드롭 영향을 받지 않아 즉시 돈다.
// 여기서는 직접 카카오로 보내지 않고(차트 이미지는 matplotlib=Python 이라 GitHub Actions 가 생성),
// GitHub repository_dispatch 로 kakao-daily 워크플로를 트리거만 한다.
//   필요한 시크릿: GH_DISPATCH_TOKEN — 저장소 dispatch 권한 PAT
//     (fine-grained: 0101-commits/economic-site 의 Contents=Read and write).
//   미설정 시: 아무 것도 안 하고 경고만 남긴다(배포는 안전).
const GH_REPO = '0101-commits/economic-site';
async function triggerKakaoDispatch(env, cron) {
  const token = env && env.GH_DISPATCH_TOKEN;
  if (!token) {
    console.log('[kakao-cron] GH_DISPATCH_TOKEN 미설정 — dispatch 생략. (README 참고: Worker 시크릿 추가 필요)');
    return;
  }
  try {
    const r = await fetch(`https://api.github.com/repos/${GH_REPO}/dispatches`, {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'ecom-kakao-cron',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ event_type: 'kakao-send', client_payload: { cron: cron || '' } }),
      signal: AbortSignal.timeout(15000),
    });
    // 성공 시 204 No Content. 실패 시 본문에 사유.
    console.log('[kakao-cron] dispatch HTTP', r.status, r.ok ? '(요청 성공)' : await r.text().catch(() => ''));
  } catch (e) {
    console.log('[kakao-cron] dispatch 오류:', String((e && e.message) || e));
  }
}

export default {
  // Cloudflare Cron Trigger 진입점
  async scheduled(event, env, ctx) {
    ctx.waitUntil(triggerKakaoDispatch(env, event && event.cron));
  },

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
      // 📲 투자 현황 — 카카오 알림 설정 저장 (저장소 alerts_config.json 커밋)
      if (purl.pathname === '/portfolio') {
        return handlePortfolioPost(request, env);
      }
      return jsonResponse({ error: 'POST is only supported at /ai or /portfolio' }, 404);
    }
    if (request.method !== 'GET') return jsonResponse({ error: 'GET only' }, 405);

    const reqUrl = new URL(request.url);
    // 📲 투자 현황 — 저장된 카카오 알림 설정 조회 (GET /portfolio)
    if (reqUrl.pathname === '/portfolio') {
      return handlePortfolioGet(env);
    }
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

    // Yahoo Finance 차트 API 는 '없는 심볼/폐기 경로' 에 4xx(주로 404)를 주지만 body 는 정상 JSON
    // ({chart:{result:null,error:{...}}})이고, 모든 소비자(_fetchJsonWithProxies·fetchYahooQuote 등)가
    // result==null 을 graceful 폴백 처리한다. 4xx 를 그대로 통과시키면 브라우저 콘솔에 '빨간 404' 만
    // 쌓인다(JS 가 try/catch·null 체크로 처리해도 네트워크 레벨 로그는 못 막음). 따라서 Yahoo 의 4xx 는
    // 200 으로 클램프해 콘솔 에러를 없앤다 — 원래 상태는 위 X-Proxy-Upstream-Status 헤더로 보존하므로
    // 디버깅/동작에는 영향 없음.
    const isYahoo = t.hostname.endsWith('finance.yahoo.com');
    const outStatus = (isYahoo && upstream.status >= 400 && upstream.status < 500) ? 200 : upstream.status;

    const resp = new Response(body, { status: outStatus, headers });
    // 성공 응답만 edge 캐시에 저장
    if (upstream.ok) {
      try { await cache.put(cacheKey, resp.clone()); } catch (_) { /* ignore */ }
    }
    return resp;
  },
};
