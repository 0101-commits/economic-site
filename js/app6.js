/* ============================================================
   app6.js — 투자 현황 4탭 재구성 (2026-08-11 기획안 v2 "메르 렌즈")
   탭: 브리핑(brief) · 포트폴리오(holdings=기존 화면) · 종목 분석(stock) · 시장 신호(signal)
   + 포트폴리오 탭 하단 "메르 위험 패널"(VaR·샤프×소르티노·MDD·자국편향·워터폴·환노출 what-if)

   의존(로드 순서상 앞): app1(_latestDataForIndicators, _fetchJsonWithProxies, getThemeColors),
   app2(pfState/pfQuotes/pfUsdKrw/pfFmtKrw/pfChgHtml/pfSMA/pfRSI/pfMACD/
        pfFetchQuote/pfFetchNaverDaily/pfMkChart/_pfLoadSnaps/initPortfolioPage/pfRefreshQuotes)
   신규 데이터 수집 없음 — data.json + merblog.json + localStorage 만 소비 (P1 원칙).
   ============================================================ */

var PF_TABS = ['brief', 'holdings', 'stock', 'signal'];
var PF_TAB_KEY = 'pfActiveTab';
var _pfActiveTab = 'brief';
var _pfTabWrapped = false;
var _pfBriefChart = null;          // Chart.js (오늘의 차트)
var _pfStockLw = null;             // LWC 인라인 차트 (종목 분석)
var _pfStockCur = null;            // 현재 열린 종목 spec
var _pfMerCache = null;            // merblog.json 캐시 (Promise)
var _pfFundaCache = null;          // fundamentals.json 캐시 (Promise, P2)

/* ── 공용 헬퍼 ─────────────────────────────────────────── */
function _pfData() { return (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators) ? _latestDataForIndicators : null; }
var _pfDataRetry = 0;
function _pfWaitData(rerender) {
  // 딥링크로 곧장 진입하면 data.json 로드 전에 렌더가 돈다 — 도착까지 1.2s 간격 재시도(최대 8회).
  if (_pfData() || _pfDataRetry >= 8) return false;
  _pfDataRetry++;
  setTimeout(function () { try { rerender(); } catch (_) {} }, 1200);
  return true;
}
function _pfNum(v, nd) { return (v == null || !isFinite(v)) ? '-' : (+v).toLocaleString('ko-KR', { maximumFractionDigits: nd == null ? 1 : nd }); }
function _pfTone(v) { return v > 0 ? 'up-txt' : (v < 0 ? 'down-txt' : ''); }
function _pfSpark(series, colorVar, w, h) {
  // 소형 SVG 스파크라인 — series: number[] (null 섞여도 됨)
  var xs = (series || []).filter(function (v) { return v != null && isFinite(v); });
  if (xs.length < 3) return '';
  var min = Math.min.apply(null, xs), max = Math.max.apply(null, xs);
  var span = (max - min) || 1; w = w || 100; h = h || 24;
  var pts = xs.map(function (v, i) {
    return (i * (w / (xs.length - 1))).toFixed(1) + ',' + (h - 2 - (v - min) / span * (h - 4)).toFixed(1);
  }).join(' ');
  var last = pts.split(' ').pop();
  return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" aria-hidden="true" style="display:block;width:100%;height:' + h + 'px;margin-top:6px;">' +
    '<polyline points="' + pts + '" fill="none" stroke="' + colorVar + '" stroke-width="1.6"/>' +
    '<circle cx="' + last.split(',')[0] + '" cy="' + last.split(',')[1] + '" r="2" fill="' + colorVar + '"/></svg>';
}
function _pfHistTail(histObjOrArr, n) {
  // {date:value} dict 또는 [{date,close}] 배열 → 최근 n개 값 배열
  if (!histObjOrArr) return [];
  if (Array.isArray(histObjOrArr)) return histObjOrArr.slice(-n).map(function (r) { return r && (r.close != null ? +r.close : (r.v != null ? +r.v : null)); });
  var ks = Object.keys(histObjOrArr).sort();
  return ks.slice(-n).map(function (k) { return +histObjOrArr[k]; });
}
function _pfCard(title, bodyHtml, extra) {
  return '<div class="widget" style="margin-bottom:12px;' + (extra || '') + '">' +
    (title ? '<div class="widget-title">' + title + '</div>' : '') + bodyHtml + '</div>';
}

/* ── 포트폴리오 집계 (pfRenderSummary 로직의 읽기전용 사본) ── */
function _pfAggregate() {
  var fx = pfUsdKrw();
  var out = { evalKrw: 0, costKrw: 0, fxPnlKrw: 0, hasFxSplit: false, dayPnlKrw: 0, hasDay: false,
              krEval: 0, usdEval: 0, counted: 0, fx: fx, tiles: [] };
  (pfState && pfState.items || []).forEach(function (it) {
    var q = pfQuotes[it.id];
    if (!q) { out.tiles.push({ name: it.name || it.symbol, pct: null, it: it }); return; }
    out.tiles.push({ name: it.name || it.symbol, pct: (q.pct != null ? +q.pct : null), it: it });
    if (!it.qty) return;
    var mul = (q.ccy === 'USD') ? fx : 1;
    if (q.ccy === 'USD' && !fx) return;
    var ev = q.price * it.qty * mul;
    out.evalKrw += ev;
    out.tiles[out.tiles.length - 1].ev = ev;   // P3: 히트맵 평가액 가중용
    if (q.ccy === 'USD') out.usdEval += ev; else out.krEval += ev;
    if (q.prevClose != null && isFinite(q.prevClose)) { out.dayPnlKrw += (q.price - q.prevClose) * it.qty * mul; out.hasDay = true; }
    if (it.avg) {
      var costMul = (q.ccy === 'USD') ? (it.fxBuy || fx) : 1;
      out.costKrw += it.avg * it.qty * costMul;
      if (q.ccy === 'USD' && it.fxBuy) { out.fxPnlKrw += it.avg * it.qty * (fx - it.fxBuy); out.hasFxSplit = true; }
    }
    out.counted++;
  });
  return out;
}

/* ── 탭 전환 ───────────────────────────────────────────── */
function pfShowTab(name, noUrl) {
  if (PF_TABS.indexOf(name) < 0) name = 'brief';
  _pfActiveTab = name;
  try { localStorage.setItem(PF_TAB_KEY, name); } catch (_) {}
  PF_TABS.forEach(function (t) {
    var pane = document.getElementById('pfTab-' + t);
    if (pane) pane.style.display = (t === name) ? '' : 'none';
    var btn = document.getElementById('pfTabBtn-' + t);
    if (btn) {
      var on = (t === name);
      btn.style.background = on ? 'var(--c-accent)' : 'transparent';
      btn.style.color = on ? 'var(--c-on-accent)' : 'var(--c-txt-dim)';
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    }
  });
  if (!noUrl) {
    try {
      var u = new URL(location.href);
      u.searchParams.set('p', 'portfolio'); u.searchParams.set('t', name);
      history.replaceState(null, '', u.pathname + u.search);
    } catch (_) {}
  }
  if (name === 'brief') pfBriefRender();
  else if (name === 'signal') pfSignalRender();
  else if (name === 'stock') pfStockRender();
  else if (name === 'holdings') {
    // hidden 상태에서 그려진 Chart.js/LWC 캔버스는 크기 0 — 표시 후 재렌더로 복구
    requestAnimationFrame(function () {
      try { pfRenderPie(); pfRenderBench(); } catch (_) {}
      try { pfRiskRender(); } catch (_) {}
    });
  }
}

/* initPortfolioPage / pfRefreshQuotes 래핑 — app2 로드 이후(로더 순서 보장) */
(function () {
  if (_pfTabWrapped) return; _pfTabWrapped = true;
  // 딥링크 ?t= 는 스크립트 로드 시점에 캡처해 1회 소비 — app4 의 ?p= 라우터가
  // initPortfolioPage(50ms 지연) 실행 전에 replaceState 로 쿼리를 정리해 t 가 사라진다.
  var _pfDeepT = null;
  try { _pfDeepT = new URLSearchParams(location.search).get('t'); } catch (_) {}
  var _origInit = window.initPortfolioPage;
  window.initPortfolioPage = function () {
    _origInit();
    var t = _pfDeepT; _pfDeepT = null;
    if (!t) { try { t = new URLSearchParams(location.search).get('t'); } catch (_) {} }
    if (!t) { try { t = localStorage.getItem(PF_TAB_KEY); } catch (_) {} }
    pfShowTab(t || 'brief', true);
  };
  var _origRefresh = window.pfRefreshQuotes;
  window.pfRefreshQuotes = async function (manual) {
    await _origRefresh(manual);
    try {
      if (_pfActiveTab === 'brief') pfBriefRender();
      else if (_pfActiveTab === 'holdings') pfRiskRender();
    } catch (_) {}
  };
})();

/* ── 개념 ⓘ 레이어 — 메르식 비유 사전 ───────────────────── */
var PF_DICT = {
  var:      { t: 'VaR (Value at Risk)', d: '"내일 95% 확률로 강수량 10mm를 넘지 않는다"는 일기예보처럼, 위험을 한 장의 숫자로 요약. 1일 95% VaR 100만원 = 20일 중 1일은 100만원 이상 잃을 수 있다는 뜻.', q: '외국인들이 국장을 던지는 비밀 1' },
  cvar:     { t: 'cVaR', d: 'VaR가 "열이 38.5도 넘는 날이 생긴다"라면, cVaR는 "그날 평균 체온이 40도"라는 것 — 최악의 날들의 평균 손실.', q: '외국인들이 국장을 던지는 비밀 1' },
  varlimit: { t: 'VaR 한도 (위험예산)', d: '항공사 수하물 20kg 제한과 비슷함. 짐(변동성)이 무거워지면 개수(보유금액)를 줄여야 함 — 필요 없어서가 아니라 한도를 맞추려고 파는 것.', q: '외국인들이 국장을 던지는 비밀 1' },
  sharpe:   { t: '샤프지수', d: '수익률이 같아도 난폭운전 택시보다 안전운전 택시가 낫다 — "위험 1단위당 수익". (수익률−무위험수익률)÷변동성. 오르내림 전부를 위험으로 봄.', q: '외국인들이 국장을 던지는 비밀 2' },
  sortino:  { t: '소르티노지수', d: '샤프와 달리 하락만 위험으로 보고 위로 튄 것은 빼줌 — "주가가 위로 튄 건 돈을 벌었다는 말". 연기금들이 주로 쓰는 지표.', q: '외국인들이 국장을 던지는 비밀 외전' },
  vkospi:   { t: 'VKOSPI', d: 'KOSPI200 옵션 가격에서 뽑은 향후 변동성 기대치(연율 %). 일간 변동성 근사 ≈ VKOSPI÷16. 50 이상이면 극단적 공포 구간으로 봄.', q: '외국인들이 국장을 던지는 비밀 1' },
  realized: { t: '실현변동성', d: '실제 지나간 20일의 종가 움직임에서 계산한 변동성(자체 계산). VKOSPI(기대치)와 달리 "실제로 이만큼 흔들렸다"는 실측치.', q: null },
  homebias: { t: '자국편향', d: '다니는 회사 주식에 전 재산을 몰빵하는 것과 비슷함 — 경제가 흔들리면 월급(소득)과 주식(자산)이 한꺼번에 무너짐. 노르웨이 국부펀드는 자국주식 거의 0%.', q: '외국인들이 국장을 던지는 비밀 외전' },
  smoothing:{ t: '스무딩 오퍼레이션', d: '"울퉁불퉁한 걸 매끄럽게" — 환율이 급하게 움직이면 외환당국이 직접 달러를 사고팔아 속도를 늦추는 것.', q: '원화는 왜 강해지고 있을까?' },
  fxexpo:   { t: '환노출', d: '환헤지 없이 해외자산을 들고 있는 상태. 원화가 강해지면 해외자산의 원화 평가액이 깎이고, 약해지면 이중으로 번다.', q: '원화는 왜 강해지고 있을까?' }
};
function pfDictShow(ev, key) {
  ev.stopPropagation();
  var e = PF_DICT[key]; if (!e) return;
  var pop = document.getElementById('pfDictPop');
  if (!pop) {
    pop = document.createElement('div'); pop.id = 'pfDictPop';
    pop.style.cssText = 'position:fixed;z-index:400;max-width:300px;background:var(--c-card);border:1px solid var(--c-border);border-radius:var(--r-sm);padding:10px 12px;box-shadow:0 6px 24px rgba(0,0,0,.25);font-size:var(--font-size-sm);line-height:1.6;';
    document.body.appendChild(pop);
    document.addEventListener('click', function () { pop.style.display = 'none'; });
  }
  pop.innerHTML = '<div style="font-weight:var(--font-weight-bold);color:var(--c-txt);margin-bottom:4px;">' + e.t + '</div>' +
    '<div style="color:var(--c-txt-dim);">' + e.d + '</div>' +
    (e.q ? '<div style="margin-top:6px;font-size:var(--font-size-xs);color:var(--c-txt-muted);">출처: 메르 「' + e.q + '」 · <a href="?p=merblog" onclick="event.stopPropagation()" style="color:var(--c-primary);">블로그 검색 →</a></div>' : '<div style="margin-top:6px;font-size:var(--font-size-xs);color:var(--c-txt-muted);">사이트 자체 계산 지표</div>');
  pop.style.display = 'block';
  var x = Math.min(ev.clientX, window.innerWidth - 320), y = Math.min(ev.clientY + 12, window.innerHeight - 180);
  pop.style.left = Math.max(8, x) + 'px'; pop.style.top = Math.max(8, y) + 'px';
}
function _pfI(key) { return '<button onclick="pfDictShow(event,\'' + key + '\')" aria-label="용어 설명" style="background:transparent;border:none;color:var(--c-txt-muted);cursor:pointer;font-size:var(--font-size-xs);padding:0 2px;vertical-align:1px;">ⓘ</button>'; }

/* ── merblog 연동 (lazy 1회 로드) ───────────────────────── */
function pfMerLoad() {
  if (_pfMerCache) return _pfMerCache;
  _pfMerCache = fetch('merblog.json?v=' + Date.now(), { signal: AbortSignal.timeout(12000) })
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; });
  return _pfMerCache;
}
function pfMerOneLiner(mer) {
  // 최신 글에서 「한줄 코멘트.」 마커 뒤 문장 추출 (fullText 보유분 우선)
  var posts = (mer && mer.posts) || [];
  for (var i = 0; i < posts.length; i++) {
    var p = posts[i], txt = p.fullText || '';
    var m = txt.match(/한줄\s*코멘트\.?\s*([\s\S]{20,400}?)(?:\s*PS\)|$)/);
    if (m) {
      var s = m[1].replace(/\s+/g, ' ').trim();
      if (s.length > 220) s = s.slice(0, 220) + '…';
      return { text: s, title: p.title, date: (p.date || '').slice(0, 10), url: p.url };
    }
  }
  return null;
}
function pfFundaLoad() {
  // fundamentals.json — 일일 풀런이 생성(P2). 파일이 아직 없으면 null.
  if (_pfFundaCache) return _pfFundaCache;
  _pfFundaCache = fetch('fundamentals.json?v=' + Date.now(), { signal: AbortSignal.timeout(10000) })
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; });
  return _pfFundaCache;
}
var PF_ALIAS = { 'SK하이닉스': ['하이닉스'], '삼성전자': ['삼전'] };
function pfMerMentions(mer, name, symbol) {
  var posts = (mer && mer.posts) || [];
  var keys = [name].concat(PF_ALIAS[name] || []).filter(Boolean);
  if (symbol && /^[A-Z]{1,5}$/.test(symbol)) keys.push(symbol);
  var hits = [];
  posts.forEach(function (p) {
    var hay = (p.title || '') + ' ' + (p.excerpt || '') + ' ' + (p.fullText || '');
    for (var i = 0; i < keys.length; i++) {
      if (keys[i] && hay.indexOf(keys[i]) >= 0) { hits.push(p); return; }
    }
  });
  return hits.slice(0, 5);
}

/* ══════════════════════════════════════════════════════════
   탭 ① 브리핑
   ══════════════════════════════════════════════════════════ */
function pfBriefRender() {
  var el = document.getElementById('pfTab-brief'); if (!el || _pfActiveTab !== 'brief') return;
  _pfWaitData(pfBriefRender);
  var d = _pfData() || {};
  var agg = _pfAggregate();
  var vk = (d.sentiment || {}).vkospi || {};
  var fxObj = (d.fx || {}).USDKRW || {};
  var snaps = (typeof _pfLoadSnaps === 'function') ? _pfLoadSnaps() : [];
  var asof = new Date();
  var pnl = agg.costKrw > 0 ? agg.evalKrw - agg.costKrw : null;

  /* 타일 4 */
  var evSpark = _pfSpark(snaps.slice(-20).map(function (s) { return s.ev; }), 'var(--c-accent)');
  var vkHistVals = _pfHistTail(vk.history, 20);
  var fxHistVals = _pfHistTail(((d.history || {}).fx || {}).USDKRW, 20);
  var dayCls = _pfTone(agg.dayPnlKrw);
  var vkNote = vk.value != null
    ? ('일간변동성 ≈ ' + (vk.value / 16).toFixed(1) + '%' + (vk.stale ? ' · <span style="color:var(--color-warning,#c98500);">⏸ ' + (vk.as_of || '') + ' 지연</span>' : ''))
    : '수집 지연';
  /* P3 — 내 포트폴리오 한 줄 (클라 규칙 기반: 보유 정보는 서버·AI 로 전송하지 않는다) */
  var withPct = agg.tiles.filter(function (t) { return t.pct != null; });
  var oneLine = '';
  if (withPct.length) {
    var upN = withPct.filter(function (t) { return t.pct > 0; }).length;
    var sortedT = withPct.slice().sort(function (a, b) { return b.pct - a.pct; });
    var best = sortedT[0], worst = sortedT[sortedT.length - 1];
    var regime = vk.value == null ? '' : (vk.value >= 80 ? ' · 변동성 극단권' : (vk.value >= 50 ? ' · 변동성 공포권' : (vk.value >= 30 ? ' · 변동성 주의권' : '')));
    oneLine = '<div style="font-size:var(--font-size-sm);color:var(--c-txt-dim);margin-bottom:10px;line-height:1.6;">📌 보유 ' + withPct.length + '종 중 <b class="up-txt">' + upN + '종 상승</b>' +
      (best ? ' — 최고 ' + pfEsc(best.name) + ' <b class="' + _pfTone(best.pct) + '">' + (best.pct >= 0 ? '+' : '') + best.pct.toFixed(1) + '%</b>' : '') +
      (worst && worst !== best ? ', 최저 ' + pfEsc(worst.name) + ' <b class="' + _pfTone(worst.pct) + '">' + (worst.pct >= 0 ? '+' : '') + worst.pct.toFixed(1) + '%</b>' : '') +
      regime + ' <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">(기기 내 규칙 생성 — 보유 정보 외부 전송 없음)</span></div>';
  }

  var tiles = oneLine +
    '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:12px;">' +
    '<div class="kpi-card"><div class="widget-title">총 평가액</div><div style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);font-family:var(--font-num);">' + (agg.counted ? pfFmtKrw(agg.evalKrw) : '-') + '</div>' +
      '<div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">' + (pnl != null ? ('누적 ' + (pnl >= 0 ? '+' : '') + pfFmtKrw(pnl)) : '평단가·수량 입력 시 계산') + '</div>' + evSpark + '</div>' +
    '<div class="kpi-card"><div class="widget-title">오늘 손익 (주가)</div><div class="' + dayCls + '" style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);font-family:var(--font-num);">' + (agg.hasDay ? ((agg.dayPnlKrw >= 0 ? '+' : '') + pfFmtKrw(agg.dayPnlKrw)) : '-') + '</div>' +
      '<div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">전일 종가 대비 · 시세 기준</div></div>' +
    '<div class="kpi-card"><div class="widget-title">환율 USDKRW ' + _pfI('fxexpo') + '</div><div style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);font-family:var(--font-num);">' + (fxObj.rate != null ? (+fxObj.rate).toFixed(1) : '-') + '</div>' +
      '<div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">내 USD 노출 ' + (agg.evalKrw > 0 ? Math.round(agg.usdEval / agg.evalKrw * 100) + '%' : '-') + '</div>' + _pfSpark(fxHistVals, 'var(--c-txt-muted)') + '</div>' +
    '<div class="kpi-card"><div class="widget-title">VKOSPI ' + _pfI('vkospi') + '</div><div style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);font-family:var(--font-num);">' + (vk.value != null ? vk.value : '-') + '</div>' +
      '<div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">' + vkNote + '</div>' + _pfSpark(vkHistVals, 'var(--color-warning,#c98500)') + '</div>' +
    '</div>';

  /* 보유 종목 히트맵 — 색=방향, 농도=강도(±1%/±2.5% 3단계), 크기=평가액 가중(P3: 비중 22%+ → 2칸) */
  var hm = agg.tiles.map(function (t) {
    var p = t.pct, bg, fg;
    if (p == null) { bg = 'var(--c-surface)'; fg = 'var(--c-txt-muted)'; }
    else {
      var up = p >= 0, a = Math.abs(p);
      var alpha = a >= 2.5 ? '' : (a >= 1 ? '55' : '22');
      var base = up ? (window.CUP || '#d13c3c') : (window.CDN || '#2a78d6');
      bg = base + alpha; fg = a >= 2.5 ? '#fff' : base;
    }
    var big = (t.ev && agg.evalKrw > 0 && t.ev / agg.evalKrw >= 0.22) ? 'grid-column:span 2;' : '';
    return '<div role="button" tabindex="0" onclick="pfStockOpenFromTile(\'' + (t.it ? t.it.id : '') + '\')" onkeydown="if(event.key===\'Enter\')this.click()" style="cursor:pointer;border-radius:var(--r-sm);padding:8px 10px;min-height:52px;' + big + 'background:' + bg + ';color:' + fg + ';">' +
      '<div style="font-size:var(--font-size-xs);font-weight:var(--font-weight-semibold);opacity:.9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + pfEsc(t.name) + '</div>' +
      '<div style="font-size:var(--font-size-base);font-weight:var(--font-weight-bold);font-family:var(--font-num);">' + (p == null ? '—' : (p >= 0 ? '+' : '') + p.toFixed(2) + '%') + '</div></div>';
  }).join('');
  var heat = _pfCard('보유 종목 오늘 <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);font-weight:var(--font-weight-normal);">색=방향 · 농도=강도(±1/±2.5%) · 탭=종목 분석</span>',
    agg.tiles.length ? '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:6px;">' + hm + '</div>'
                     : '<div style="color:var(--c-txt-muted);font-size:var(--font-size-sm);padding:12px 0;">포트폴리오 탭에서 종목을 추가하세요.</div>');

  /* 오늘의 차트 (P3: 변화량 스코어링으로 VKOSPI vs 환율 자동 선정) + 이번 주 일정 */
  var chartMode = _pfBriefChartMode(d);
  var chart = _pfCard('오늘의 차트 — ' + chartMode.title + ' × 외국인 순매매 (30거래일) ' + _pfI(chartMode.key === 'fx' ? 'fxexpo' : 'varlimit'),
    '<div style="position:relative;height:220px;"><canvas id="pfBriefChartCanvas" role="img" aria-label="' + chartMode.title + '와 외국인 순매매 30일 비교 차트"></canvas></div>' +
    '<div id="pfBriefChartNote" style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:6px;"></div>');
  var cal = _pfBriefCalendarHtml(d, agg);
  var merBox = '<div class="widget" style="margin-bottom:12px;"><div class="widget-title">오늘의 메르 한 줄</div><div id="pfMerOneLine" style="font-size:var(--font-size-sm);color:var(--c-txt-dim);line-height:1.7;">불러오는 중…</div></div>';

  el.innerHTML = tiles + heat +
    '<div style="display:grid;grid-template-columns:1.4fr 1fr;gap:12px;" class="pf-brief-2col">' + chart + cal + '</div>' + merBox +
    '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">기준: 시세=무료 소스(지연 가능) · 지표=' + ((d.lastUpdated || '').slice(0, 16).replace('T', ' ') || '-') + ' 빌드 · ' + asof.getHours() + ':' + String(asof.getMinutes()).padStart(2, '0') + ' 렌더</div>';

  _pfBriefChartRender(d, chartMode);
  /* 개별 종목 실적 발표일 병합 (P2 — fundamentals.json us[].earningsDate) */
  pfFundaLoad().then(function (fd) {
    if (_pfActiveTab !== 'brief' || !fd || !fd.us) return;
    var ul = el.querySelector('ul'); if (!ul) return;
    var today = new Date().toISOString().slice(0, 10);
    var lim = new Date(Date.now() + 8 * 86400000).toISOString().slice(0, 10);
    Object.keys(fd.us).forEach(function (sym) {
      var ed = fd.us[sym].earningsDate;
      if (!ed || ed < today || ed > lim) return;
      var wd = '일월화수목금토'[new Date(ed + 'T00:00:00').getDay()];
      ul.insertAdjacentHTML('beforeend',
        '<li style="padding:6px 0;border-bottom:1px dashed var(--c-border);font-size:var(--font-size-sm);"><b>' + ed.slice(5).replace('-', '/') + ' (' + wd + ')</b> 🇺🇸 ' + pfEsc(sym) + ' 실적 발표 <span style="color:var(--c-txt-muted);font-size:var(--font-size-xs);">보유·관심 종목</span></li>');
    });
  });
  pfMerLoad().then(function (mer) {
    var box = document.getElementById('pfMerOneLine'); if (!box) return;
    var one = pfMerOneLiner(mer);
    box.innerHTML = one
      ? '"' + pfEsc(one.text) + '" <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">— ' + pfEsc(one.title) + ' · ' + one.date + ' · <a href="' + pfEsc(one.url) + '" target="_blank" rel="noopener" style="color:var(--c-primary);">원문 ↗</a></span>'
      : '최근 글에서 한줄 코멘트를 찾지 못했습니다. <a href="?p=merblog" style="color:var(--c-primary);">메르 블로그 검색 →</a>';
  });
}
function _pfBriefCalendarHtml(d, agg) {
  var evs = ((d.economicCalendar || {}).events || []);
  var today = new Date().toISOString().slice(0, 10);
  var lim = new Date(Date.now() + 8 * 86400000).toISOString().slice(0, 10);
  var hasUS = agg.usdEval > 0 || (pfState && pfState.items.some(function (i) { return i.market === 'US'; }));
  var hasKR = agg.krEval > 0 || (pfState && pfState.items.some(function (i) { return i.market === 'KR'; }));
  var rows = evs.filter(function (e) {
    if (!e.iso || e.iso < today || e.iso > lim) return false;
    if ((e.stars || 0) >= 3) return true;
    if ((e.stars || 0) < 2) return false;
    return (e.cc === 'US' && hasUS) || (e.cc === 'KR' && hasKR);
  }).slice(0, 7).map(function (e) {
    var wd = '일월화수목금토'[new Date(e.iso + 'T00:00:00').getDay()];
    return '<li style="padding:6px 0;border-bottom:1px dashed var(--c-border);font-size:var(--font-size-sm);">' +
      '<b>' + e.iso.slice(5).replace('-', '/') + ' (' + wd + ')</b> ' + (e.cc === 'US' ? '🇺🇸' : (e.cc === 'KR' ? '🇰🇷' : e.cc)) + ' ' + pfEsc(e.name) +
      ' <span style="color:var(--c-txt-muted);font-size:var(--font-size-xs);">' + '★'.repeat(e.stars || 0) + (e.fore ? ' · 예상 ' + pfEsc(e.fore) : '') + '</span></li>';
  }).join('');
  return _pfCard('이번 주 · 내 시장 관련 일정',
    rows ? '<ul style="list-style:none;margin:0;padding:0;">' + rows + '</ul>' : '<div style="color:var(--c-txt-muted);font-size:var(--font-size-sm);padding:10px 0;">향후 8일 내 주요 일정이 없습니다.</div>');
}
function _pfBriefChartMode(d) {
  // P3 킬러 차트 자동 선정 — 최근 5거래일 변화율 스코어: VKOSPI vs 환율(가중 ×3,
  // 환율 1% 는 변동성 5% 급의 사건이라 스케일 보정). 큰 쪽이 "오늘 더 중요한 축".
  function chg5(vals) {
    var xs = (vals || []).filter(function (v) { return v != null && isFinite(v); });
    if (xs.length < 6) return 0;
    var a = xs[xs.length - 6], b = xs[xs.length - 1];
    return a ? Math.abs(b / a - 1) * 100 : 0;
  }
  var vkScore = chg5(_pfHistTail(((d.sentiment || {}).vkospi || {}).history, 10));
  var fxScore = chg5(_pfHistTail(((d.history || {}).fx || {}).USDKRW, 10)) * 3;
  return fxScore > vkScore ? { key: 'fx', title: '달러원 환율' } : { key: 'vk', title: 'VKOSPI' };
}
function _pfBriefChartRender(d, mode) {
  var cv = document.getElementById('pfBriefChartCanvas'); if (!cv || typeof Chart === 'undefined') return;
  mode = mode || { key: 'vk', title: 'VKOSPI' };
  var daily = ((d.investorTrading || {}).daily || []);
  var fMap = {};
  daily.forEach(function (r) { if (r && r.date) fMap[r.date] = +r.foreign; });
  // 축 = 외국인 데이터의 최근 30거래일 (라인 시계열은 구멍이 있어 forward-fill)
  var axis = daily.slice(-30).map(function (r) { return r.date; });
  if (!axis.length) { cv.parentElement.innerHTML = '<div style="color:var(--c-txt-muted);font-size:var(--font-size-sm);padding:20px;">투자자 수급 데이터 없음</div>'; return; }
  var hist = {};
  if (mode.key === 'fx') {
    (((d.history || {}).fx || {}).USDKRW || []).forEach(function (r) { if (r && r.date && r.close != null) hist[r.date] = +r.close; });
  } else {
    hist = ((d.sentiment || {}).vkospi || {}).history || {};
  }
  var vkLine = [], last = null;
  axis.forEach(function (dt) { if (hist[dt] != null) last = hist[dt]; vkLine.push(last); });
  var bars = axis.map(function (dt) { return fMap[dt] != null ? fMap[dt] : null; });
  var tc = (typeof getThemeColors === 'function') ? getThemeColors() : { accent: '#3987e5', series: [] };
  if (_pfBriefChart) { try { _pfBriefChart.destroy(); } catch (_) {} _pfBriefChart = null; }
  _pfBriefChart = new Chart(cv.getContext('2d'), {
    data: {
      labels: axis.map(function (s) { return s.slice(5); }),
      datasets: [
        { type: 'bar', label: '외국인 순매매(억원)', data: bars, yAxisID: 'y1',
          backgroundColor: bars.map(function (v) { return (v != null && v >= 0 ? (window.CUP || '#d13c3c') : (window.CDN || '#2a78d6')) + '99'; }) },
        { type: 'line', label: mode.title, data: vkLine, yAxisID: 'y2', borderColor: tc.accent, borderWidth: 2, pointRadius: 0, tension: 0.2 }
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      plugins: { legend: { labels: { boxWidth: 10, font: { size: 10 } } } },
      scales: { x: { ticks: { maxTicksLimit: 8, font: { size: 9 } } },
        y1: { position: 'left', ticks: { font: { size: 9 } }, grid: { drawOnChartArea: false } },
        y2: { position: 'right', ticks: { font: { size: 9 } } } } }
  });
  var f20 = daily.slice(-20).reduce(function (s, r) { return s + (+r.foreign || 0); }, 0);
  var note = document.getElementById('pfBriefChartNote');
  if (note) note.textContent = (mode.key === 'fx'
    ? '읽는 법 · 외국인 매도 달러가 빠져나가면 환율이 오른다(4편) — 매도세와 환율 방향을 같이 본다.'
    : '읽는 법 · 변동성(선)이 꺾이는 구간에서 외국인 매도(파란 막대)가 멈추는지 본다 — VaR 한도 논리.') +
    ' 최근 20거래일 외국인 순매매 ' + (f20 >= 0 ? '+' : '') + _pfNum(f20, 0) + '억원. (차트 축은 최근 5일 변화량 스코어로 자동 선정)';
  // 참고: y1(수급)·y2(라인)는 단위가 달라 이중축이 불가피한 조합 — 각 축을 범례 라벨에 명시해 오독을 막는다.
}
function pfStockOpenFromTile(itemId) {
  var it = (pfState && pfState.items || []).find(function (i) { return i.id === itemId; });
  pfShowTab('stock');
  if (it) pfStockOpen({ symbol: it.symbol, market: it.market, name: it.name || it.symbol, yahoo: it.yahoo, secType: it.secType, id: it.id });
}

/* ══════════════════════════════════════════════════════════
   탭 ④ 시장 신호 — 메르 렌즈
   ══════════════════════════════════════════════════════════ */
function pfSignalRender() {
  var el = document.getElementById('pfTab-signal'); if (!el || _pfActiveTab !== 'signal') return;
  _pfWaitData(pfSignalRender);
  var d = _pfData() || {};
  var vk = (d.sentiment || {}).vkospi || {};
  var daily = ((d.investorTrading || {}).daily || []);
  var agg = _pfAggregate();

  /* VaR 체인 보드 */
  var vkNow = vk.value, dailyVol = vkNow != null ? vkNow / 16 : null;
  var hist = vk.history || {};
  var year = new Date().getFullYear();
  var ysKeys = Object.keys(hist).filter(function (k) { return k.slice(0, 4) === String(year); }).sort();
  var vkStart = ysKeys.length ? hist[ysKeys[0]] : null;
  var ratio = (vkNow != null && vkStart) ? vkNow / vkStart : null;
  var capPct = ratio ? Math.round((1 / ratio - 1) * 100) : null;
  var f20 = daily.slice(-20).reduce(function (s, r) { return s + (+r.foreign || 0); }, 0);
  function chainNode(step, val, sub, hot) {
    return '<div style="border:1.5px solid ' + (hot ? 'var(--color-warning,#c98500)' : 'var(--c-border)') + ';border-radius:var(--r-sm);padding:8px 6px;text-align:center;' + (hot ? 'background:color-mix(in srgb, var(--color-warning,#c98500) 12%, transparent);' : '') + '">' +
      '<div style="font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);">' + step + '</div>' +
      '<div style="font-size:var(--font-size-lg);font-weight:var(--font-weight-bold);font-family:var(--font-num);margin:2px 0;">' + val + '</div>' +
      '<div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);line-height:1.4;">' + sub + '</div></div>';
  }
  var hot = vkNow != null && vkNow >= 50;
  var chain = _pfCard('외국인은 왜 파는가 — 변동성의 기계적 사슬 ' + _pfI('varlimit'),
    '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-top:4px;">' +
    chainNode('① 변동성', vkNow != null ? vkNow.toFixed(1) : '-', 'VKOSPI' + (dailyVol ? ' · 일간 ≈ ' + dailyVol.toFixed(1) + '%' : '') + (vk.stale ? ' · ⏸지연' : ''), hot) +
    chainNode('② VaR 부풀음', ratio ? '×' + ratio.toFixed(1) : '—', ratio ? '연초(' + vkStart.toFixed(0) + ') 대비 위험 계산치 배율 (추정)' : '연초 데이터 없음', hot && ratio != null && ratio > 1.3) +
    chainNode('③ 한도 압박', capPct != null ? (capPct > 0 ? '+' : '') + capPct + '%' : '—', '같은 위험예산으로 담을 수 있는 금액 변화 (추정)', hot && capPct != null && capPct < -20) +
    chainNode('④ 수급', (f20 >= 0 ? '+' : '') + _pfNum(f20, 0) + '억', '외국인 20거래일 순매매' + (f20 >= 0 ? ' · 매도 멈춤' : ' · 순매도 지속'), false) +
    '</div>' +
    '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:8px;line-height:1.6;">읽는 법 · ①이 오르면 ②③은 기계적으로 따라온다. ④가 반전되는 시점 = ①이 꺾이는 시점. ②③은 메르 1편 산식(담을 수 있는 금액 = 위험예산 ÷ (일간변동성 × 1.645))의 배율 환산 <b>추정치</b>이며 시장 전체 예측이 아니다.</div>');

  /* 변동성 카드 — 내재 vs 실현 + 미터 */
  var meterPos = vkNow != null ? Math.min(97, Math.max(2, vkNow)) : null;
  var vol = _pfCard('변동성 — 내재 vs 실현 ' + _pfI('vkospi'),
    (meterPos != null
      ? '<div style="position:relative;height:12px;border-radius:6px;background:linear-gradient(90deg,color-mix(in srgb,var(--c-down) 25%,transparent),var(--c-surface) 38%,color-mix(in srgb,var(--color-warning,#c98500) 30%,transparent) 60%,color-mix(in srgb,var(--c-up) 30%,transparent));margin:8px 0 4px;">' +
        '<div style="position:absolute;left:' + meterPos + '%;top:-4px;width:3px;height:20px;border-radius:2px;background:var(--c-txt);"></div></div>' +
        '<div style="display:flex;justify-content:space-between;font-size:var(--font-size-xs);color:var(--c-txt-muted);"><span>안정 &lt;30</span><span>주의 30–50</span><span>공포 50–80</span><span>극단 &gt;80</span></div>'
      : '<div style="color:var(--c-txt-muted);font-size:var(--font-size-sm);">VKOSPI 수집 지연</div>') +
    '<div style="display:flex;gap:18px;margin-top:10px;font-family:var(--font-num);font-size:var(--font-size-sm);flex-wrap:wrap;">' +
    '<span><b style="font-size:var(--font-size-lg);">' + (vkNow != null ? vkNow.toFixed(1) : '-') + '</b> <span style="color:var(--c-txt-dim);">VKOSPI(내재)' + (vk.as_of ? ' · ' + vk.as_of.slice(5) : '') + (vk.stale ? ' <span style="color:var(--color-warning,#c98500);">⏸지연</span>' : '') + '</span></span>' +
    '<span><b style="font-size:var(--font-size-lg);">' + (vk.realized20d != null ? (+vk.realized20d).toFixed(1) + '%' : '-') + '</b> <span style="color:var(--c-txt-dim);">KOSPI 실현(20D, 자체계산)' + (vk.realized_asof ? ' · ' + vk.realized_asof.slice(5) : '') + '</span> ' + _pfI('realized') + '</span></div>' +
    '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:8px;line-height:1.6;">읽는 법 · 내재(시장의 기대)와 실현(실제 움직임)의 괴리가 신호. VKOSPI 소스 지연 시 실현변동성이 대체 계기판.</div>');

  /* 외국인 순매매 — 월별 다이버징 바 */
  var byMonth = {};
  daily.forEach(function (r) { if (!r || !r.date) return; var m = r.date.slice(0, 7); byMonth[m] = (byMonth[m] || 0) + (+r.foreign || 0); });
  var months = Object.keys(byMonth).sort().slice(-6);
  var maxAbs = Math.max.apply(null, months.map(function (m) { return Math.abs(byMonth[m]); }).concat([1]));
  var dvRows = months.map(function (m) {
    var v = byMonth[m], w = Math.min(48, Math.abs(v) / maxAbs * 48);
    var bar = v >= 0
      ? '<div style="position:absolute;left:50%;top:0;height:13px;width:' + w + '%;background:var(--c-up);border-radius:0 4px 4px 0;"></div>'
      : '<div style="position:absolute;right:50%;top:0;height:13px;width:' + w + '%;background:var(--c-down);border-radius:4px 0 0 4px;"></div>';
    return '<div style="display:grid;grid-template-columns:46px 1fr 88px;align-items:center;gap:8px;font-size:var(--font-size-xs);margin:6px 0;font-family:var(--font-num);">' +
      '<span>' + m.slice(2).replace('-', '.') + '</span>' +
      '<div style="position:relative;height:13px;"><div style="position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:var(--c-border);"></div>' + bar + '</div>' +
      '<span class="' + _pfTone(v) + '" style="text-align:right;font-weight:var(--font-weight-bold);">' + (v >= 0 ? '+' : '') + _pfNum(v / 10000, 2) + '조</span></div>';
  }).join('');
  var inv = _pfCard('외국인 순매매 (KOSPI · 월별)',
    (dvRows || '<div style="color:var(--c-txt-muted);font-size:var(--font-size-sm);">데이터 없음</div>') +
    '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:6px;">읽는 법 · 매도세가 멈추는 시점이 환율·지수의 변곡. 단위: 조원(억원 합산 환산) · 당월은 진행 중 합계.</div>');

  /* 환율 요인 보드 */
  var fxObj = (d.fx || {}).USDKRW || {};
  var ei = d.economicIndicators || {};
  var krRate = ((ei.kr || {}).base_rate_kr || {}).value;
  var usKeys = Object.keys(ei.us || {});
  var usRateKey = null;
  for (var ui = 0; ui < usKeys.length; ui++) { if (/base_rate|fed|ffr/.test(usKeys[ui])) { usRateKey = usKeys[ui]; break; } }
  var usRate = usRateKey ? ((ei.us || {})[usRateKey] || {}).value : null;
  function chip(dot, label) {
    var c = dot === 'g' ? 'var(--color-success,#0ca30c)' : (dot === 'r' ? 'var(--c-up)' : 'var(--color-warning,#c98500)');
    return '<span style="display:inline-flex;align-items:center;gap:6px;background:var(--c-surface);border-radius:20px;padding:3px 12px 3px 8px;font-size:var(--font-size-xs);font-weight:var(--font-weight-semibold);margin:3px 4px 3px 0;"><span style="width:8px;height:8px;border-radius:50%;background:' + c + ';"></span>' + label + '</span>';
  }
  var chips = chip(f20 >= 0 ? 'g' : 'r', '외국인 주식자금 ' + (f20 >= 0 ? '유출 완화' : '유출 지속'));
  if (krRate != null && usRate != null) chips += chip(usRate - krRate <= 1.0 ? 'g' : 'y', '한미 금리차 ' + (usRate - krRate).toFixed(2) + '%p');
  chips += chip('y', 'WGBI·당국 개입: 뉴스 참고');
  var fxCard = _pfCard('환율 요인 보드 — USDKRW ' + (fxObj.rate != null ? (+fxObj.rate).toFixed(1) : '-') + ' ' + _pfI('smoothing'),
    '<div>' + chips + '</div>' +
    '<div style="font-size:var(--font-size-sm);margin-top:8px;">내 포트폴리오 환노출 <b style="font-family:var(--font-num);">' + (agg.evalKrw > 0 ? Math.round(agg.usdEval / agg.evalKrw * 100) + '%' : '-') + '</b>' + (agg.usdEval ? ' (' + pfFmtKrw(agg.usdEval) + ')' : '') + ' — 포트폴리오 탭 what-if로 시나리오 확인</div>' +
    '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:6px;line-height:1.6;">읽는 법 · 메르 4편의 요인 분해(수급·금리차·정책). 칩은 데이터 기반 규칙 판정, WGBI·개입은 데이터가 없어 참고 표기.</div>');

  /* NPS 카드 */
  var npsAlloc = ((d.nps || {}).allocation || []);
  var npsKrRow = null;
  for (var ni = 0; ni < npsAlloc.length; ni++) { if (npsAlloc[ni].asset === '국내주식') { npsKrRow = npsAlloc[ni]; break; } }
  var npsCard = _pfCard('국민연금 국내주식 비중 ' + _pfI('homebias'),
    '<div style="font-size:var(--font-size-sm);font-family:var(--font-num);">실제 <b style="font-size:var(--font-size-lg);">' + (npsKrRow ? npsKrRow.pct + '%' : '-') + '</b> vs 목표 <b>20.8%</b> <span style="color:var(--c-txt-muted);font-size:var(--font-size-xs);">(2026 상향 후 · SAA±6%p)</span></div>' +
    '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:6px;line-height:1.6;">읽는 법 · 목표 대비 초과분은 잠재 매도 압력. 내 자국편향 진단(포트폴리오 탭)과 같은 논리 축. 목표치는 기금운용위 발표 기준(수동 상수).</div>');

  /* 샤프 시장 비교 (P2) — "코스피가 수익률이 높아도 위험을 감안하면…" (2편 23~25항) */
  function mktSharpe(sym, rfPct) {
    var arr = (((d.history || {}).indices || {})[sym] || []).slice(-260);
    var closes = arr.map(function (r) { return r && +r.close; }).filter(function (v) { return v > 0; });
    if (closes.length < 120) return null;
    var rs2 = [];
    for (var i = 1; i < closes.length; i++) rs2.push(Math.log(closes[i] / closes[i - 1]));
    var mean = rs2.reduce(function (a, b) { return a + b; }, 0) / rs2.length;
    var sd = Math.sqrt(rs2.reduce(function (a, b) { return a + (b - mean) * (b - mean); }, 0) / (rs2.length - 1));
    var annR = mean * 252 * 100, annV = sd * Math.sqrt(252) * 100;
    return annV > 0 ? { sharpe: (annR - rfPct) / annV, ret: annR, vol: annV } : null;
  }
  var rfK = (((d.economicIndicators || {}).kr || {}).base_rate_kr || {}).value; if (rfK == null) rfK = 2.75;
  var shK = mktSharpe('KOSPI', rfK), shS = mktSharpe('SP500', rfK);
  function shCell(label, s) {
    return '<div style="text-align:center;"><div style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);font-family:var(--font-num);">' + (s ? s.sharpe.toFixed(2) : '-') + '</div>' +
      '<div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">' + label + (s ? '<br>수익 ' + s.ret.toFixed(0) + '% · 변동 ' + s.vol.toFixed(0) + '%' : '') + '</div></div>';
  }
  var shCard = (shK || shS) ? _pfCard('시장 샤프 비교 (최근 1년) ' + _pfI('sharpe'),
    '<div style="display:flex;gap:26px;justify-content:center;padding:4px 0;">' + shCell('KOSPI', shK) + shCell('S&amp;P500', shS) + '</div>' +
    '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:6px;line-height:1.6;">읽는 법 · 명목 수익률이 높아도 변동성이 크면 위험조정 점수는 낮다 — 외국인이 국장 비중을 정하는 눈. 동일 무위험수익률(' + rfK + '%) 기준 단순 비교.</div>') : '';

  /* 위험예산 시뮬레이터 (P2) — 메르 1편 32~43항 계산기 */
  var simCard = _pfCard('위험예산 시뮬레이터 — 변동성이 바뀌면 기관은 얼마나 팔아야 하나 ' + _pfI('varlimit'),
    '<div style="font-size:var(--font-size-sm);">일간변동성 가정 <b id="pfSimVol" style="font-family:var(--font-num);">1.9</b>% ' +
    '<input type="range" min="0.5" max="6" step="0.1" value="1.9" oninput="pfSimUpdate(this.value)" style="vertical-align:middle;width:200px;accent-color:var(--c-accent);" aria-label="일간변동성 가정 슬라이더">' +
    (dailyVol ? ' <button onclick="pfSimUpdate(' + dailyVol.toFixed(1) + ');document.querySelector(\'#pfTab-signal input[type=range]\').value=' + dailyVol.toFixed(1) + '" style="font-size:var(--font-size-xs);padding:2px 8px;border:1px solid var(--c-border);border-radius:var(--r-xs);background:transparent;color:var(--c-primary);cursor:pointer;">현재 VKOSPI 수준(' + dailyVol.toFixed(1) + '%)로</button>' : '') + '</div>' +
    '<div id="pfSimOut" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-top:10px;font-family:var(--font-num);font-size:var(--font-size-sm);"></div>' +
    '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:8px;line-height:1.6;">가상 기관(위험예산 100억)의 교육용 계산 — 담을 수 있는 금액 = 예산 ÷ (일간변동성 × 1.645). 시장 전체 매도 물량 예측이 아닙니다.</div>');

  el.innerHTML = chain +
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;" class="pf-sig-2col">' + vol + inv + fxCard + npsCard + '</div>' +
    shCard + simCard +
    '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">지표 기준: ' + ((d.lastUpdated || '').slice(0, 16).replace('T', ' ') || '-') + ' 빌드 · ⓘ = 메르식 설명 · 매수/매도 판단은 표기하지 않습니다</div>';
  pfSimUpdate(1.9);
  _pfSignalMerBadges();
}
function pfSimUpdate(v) {
  var out = document.getElementById('pfSimOut'); if (!out) return;
  var vol = +v;
  var elV = document.getElementById('pfSimVol'); if (elV) elV.textContent = vol.toFixed(1);
  var BASE_VOL = 1.9, BUDGET = 100;                       // 억원 — 메르 1편 예시 그대로
  var cap = BUDGET / (vol / 100 * 1.645);                 // 담을 수 있는 금액(억)
  var capBase = BUDGET / (BASE_VOL / 100 * 1.645);
  var delta = cap - capBase, pct = (cap / capBase - 1) * 100;
  function cell(k, val, cls) {
    return '<div style="background:var(--c-surface);border-radius:var(--r-sm);padding:8px 10px;text-align:center;"><div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">' + k + '</div><div class="' + (cls || '') + '" style="font-size:var(--font-size-base);font-weight:var(--font-weight-bold);">' + val + '</div></div>';
  }
  out.innerHTML =
    cell('보유 한도', Math.round(cap).toLocaleString('ko-KR') + '억') +
    cell('기준(1.9%) 대비', (pct >= 0 ? '+' : '') + pct.toFixed(0) + '%', _pfTone(pct)) +
    cell(pct < 0 ? '기계적 매도 압력' : '추가 편입 여력', (delta >= 0 ? '+' : '') + Math.round(delta).toLocaleString('ko-KR') + '억', _pfTone(delta));
}
function _pfSignalMerBadges() {
  // 글→지표 자동 태깅 (P2): 최신 원문 20건에서 지표 키워드 검출 → 카드 제목 옆 배지
  pfMerLoad().then(function (mer) {
    if (_pfActiveTab !== 'signal' || !mer) return;
    var posts = (mer.posts || []).filter(function (p) { return p.fullText; });
    var rules = [
      { re: /VKOSPI|변동성지수|변동성이/, sel: 'vkospi' },
      { re: /환율|원화|원\/달러|달러원/, sel: 'fx' },
      { re: /국민연금|연기금/, sel: 'nps' }
    ];
    var counts = { vkospi: 0, fx: 0, nps: 0 };
    posts.forEach(function (p) {
      rules.forEach(function (r) { if (r.re.test(p.fullText)) counts[r.sel]++; });
    });
    var titles = document.querySelectorAll('#pfTab-signal .widget-title');
    titles.forEach(function (t) {
      var key = t.textContent.indexOf('변동성') === 0 ? 'vkospi'
              : t.textContent.indexOf('환율') === 0 ? 'fx'
              : t.textContent.indexOf('국민연금') === 0 ? 'nps' : null;
      if (key && counts[key] && !t.querySelector('.pf-mer-badge')) {
        t.insertAdjacentHTML('beforeend',
          ' <a class="pf-mer-badge" href="?p=merblog" style="font-size:var(--font-size-xs);font-weight:var(--font-weight-normal);color:var(--c-primary);text-decoration:none;">📝 관련 메르 글 ' + counts[key] + '건</a>');
      }
    });
  });
}

/* ══════════════════════════════════════════════════════════
   메르 위험 패널 (포트폴리오 탭 하단, #pfRiskPanel)
   ══════════════════════════════════════════════════════════ */
function pfRiskMetrics(snaps) {
  // pfSnapshotsV1: [{d:'YYYY-MM-DD', ev, ct}] — R=ev/ct(1+누적수익률) 기준으로
  // 입금·추가매수(ct 변동)에 덜 오염되는 일간 수익률을 뽑는다. 갭 4일 초과 쌍은 제외.
  var rs = [];
  var Rseq = [];
  for (var i = 0; i < snaps.length; i++) {
    var s = snaps[i];
    if (!s || !(s.ev > 0) || !(s.ct > 0)) continue;
    Rseq.push({ d: s.d, R: s.ev / s.ct });
  }
  for (var j = 1; j < Rseq.length; j++) {
    var gap = (new Date(Rseq[j].d) - new Date(Rseq[j - 1].d)) / 86400000;
    if (gap >= 1 && gap <= 4) rs.push(Math.log(Rseq[j].R / Rseq[j - 1].R));
  }
  var n = rs.length;
  if (n < 60) return { n: n };
  var mean = rs.reduce(function (a, b) { return a + b; }, 0) / n;
  var varc = rs.reduce(function (a, b) { return a + (b - mean) * (b - mean); }, 0) / (n - 1);
  var sd = Math.sqrt(varc);
  var downs = rs.filter(function (r) { return r < 0; });
  var dvar = downs.length > 1 ? downs.reduce(function (a, b) { return a + b * b; }, 0) / downs.length : 0;
  var dsd = Math.sqrt(dvar);
  // MDD — R 시계열 기준
  var peak = -Infinity, mdd = 0;
  Rseq.forEach(function (p) { if (p.R > peak) peak = p.R; var dd = p.R / peak - 1; if (dd < mdd) mdd = dd; });
  // cVaR — 하위 5% 평균 수익률
  var sorted = rs.slice().sort(function (a, b) { return a - b; });
  var tail = sorted.slice(0, Math.max(1, Math.floor(n * 0.05)));
  var cvarR = tail.reduce(function (a, b) { return a + b; }, 0) / tail.length;
  return { n: n, mean: mean, sd: sd, dsd: dsd, mdd: mdd, cvarR: cvarR };
}
function pfRiskRender() {
  var el = document.getElementById('pfRiskPanel'); if (!el) return;
  var d = _pfData() || {};
  var agg = _pfAggregate();
  var snaps = (typeof _pfLoadSnaps === 'function') ? _pfLoadSnaps() : [];
  var m = pfRiskMetrics(snaps);
  var rf = (((d.economicIndicators || {}).kr || {}).base_rate_kr || {}).value;
  if (rf == null) rf = 2.75;

  var riskCards;
  if (m.n < 60) {
    riskCards = '<div style="color:var(--c-txt-muted);font-size:var(--font-size-sm);padding:8px 0;">위험 지표 데이터 축적 중 (' + m.n + '/60일) — 평단가·수량이 입력된 상태로 방문한 날마다 1건씩 쌓입니다. 60일 미만의 수치는 신뢰 구간 미달이라 표시하지 않습니다.</div>';
  } else {
    var annRet = m.mean * 252 * 100;
    var annVol = m.sd * Math.sqrt(252) * 100;
    var sharpe = annVol > 0 ? (annRet - rf) / annVol : null;
    var sortino = m.dsd > 0 ? (annRet - rf) / (m.dsd * Math.sqrt(252) * 100) : null;
    var varAmt = agg.evalKrw * m.sd * 1.645;
    var cvarAmt = agg.evalKrw * Math.abs(m.cvarR);
    riskCards =
      '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;">' +
      '<div class="kpi-card"><div class="widget-title">내 1일 95% VaR ' + _pfI('var') + '</div>' +
        '<div class="down-txt" style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);font-family:var(--font-num);">−' + pfFmtKrw(varAmt) + '</div>' +
        '<div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">"20일 중 1일은 이 이상 잃을 수 있다" · cVaR ' + _pfI('cvar') + ' <b>−' + pfFmtKrw(cvarAmt) + '</b></div>' +
        '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:4px;">= 평가액 × 일간변동성 ' + (m.sd * 100).toFixed(2) + '% × 1.645 · 스냅샷 ' + m.n + '일 · 정규분포 가정, 최악을 보증하지 않음</div></div>' +
      '<div class="kpi-card"><div class="widget-title">위험조정수익률 — 두 렌즈</div>' +
        '<div style="display:flex;gap:16px;font-family:var(--font-num);">' +
        '<span><b style="font-size:var(--font-size-xl);">' + (sharpe != null ? sharpe.toFixed(2) : '-') + '</b><br><span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">샤프 ' + _pfI('sharpe') + '<br>국민연금 방식</span></span>' +
        '<span><b style="font-size:var(--font-size-xl);">' + (sortino != null ? sortino.toFixed(2) : '-') + '</b><br><span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">소르티노 ' + _pfI('sortino') + '<br>연기금 방식</span></span>' +
        '<span><b style="font-size:var(--font-size-xl);">' + (m.mdd * 100).toFixed(1) + '%</b><br><span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">MDD<br>최대 낙폭</span></span></div>' +
        '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:4px;">' + (sortino != null && sharpe != null ? (sortino > sharpe ? '소르티노 > 샤프 — 변동은 컸지만 하락보다 상승 쪽' : '샤프 ≥ 소르티노 — 하락 변동의 비중이 큼') : '') + ' · 무위험수익률 ' + rf + '% 기준</div></div>' +
      '</div>';
  }

  /* 자국편향 진단 */
  var krPct = agg.evalKrw > 0 ? Math.round(agg.krEval / agg.evalKrw * 100) : null;
  function biasRow(label, pct, hi) {
    return '<div style="display:grid;grid-template-columns:110px 1fr 46px;gap:10px;align-items:center;margin:6px 0;font-size:var(--font-size-xs);font-family:var(--font-num);">' +
      '<span' + (hi ? ' style="font-weight:var(--font-weight-bold);"' : '') + '>' + label + '</span>' +
      '<div style="height:12px;border-radius:4px;background:var(--c-surface);"><div style="width:' + Math.max(1, Math.min(100, pct)) + '%;height:12px;border-radius:4px;background:' + (hi ? 'var(--c-accent)' : 'var(--c-txt-muted)') + ';"></div></div>' +
      '<b style="text-align:right;">' + pct + '%</b></div>';
  }
  var npsAlloc2 = ((d.nps || {}).allocation || []);
  var npsKr2 = null;
  for (var nj = 0; nj < npsAlloc2.length; nj++) { if (npsAlloc2[nj].asset === '국내주식') { npsKr2 = npsAlloc2[nj]; break; } }
  var bias = krPct == null ? '' : _pfCard('자국편향 진단 — 내 국장 비중 ' + _pfI('homebias'),
    biasRow('내 포트폴리오', krPct, true) + biasRow('국민연금 목표', 20.8) + (npsKr2 ? biasRow('국민연금 실제', npsKr2.pct) : '') + biasRow('캐나다 CPP', 12) + biasRow('노르웨이 GPFG', 0.5) +
    '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:6px;line-height:1.6;">한국에서 일하며 한국 주식 ' + krPct + '% — 급여·연금·자산이 같은 충격에 노출된다는 진단(메르 외전). 진단만 표기하며 리밸런싱 권고는 하지 않습니다.</div>');

  /* 손익 분해 워터폴 (P3: 배당 원장 반영) + 환노출 what-if */
  var ledger = pfLedgerLoad();
  var divSum = ledger.filter(function (r) { return r.kind === 'div'; }).reduce(function (s, r) { return s + (+r.amt || 0); }, 0);
  var wf = '';
  if (agg.costKrw > 0) {
    var pnl = agg.evalKrw - agg.costKrw;
    var pricePnl = pnl - agg.fxPnlKrw;
    var total = pnl + divSum;
    var maxV = Math.max(Math.abs(pricePnl), Math.abs(agg.fxPnlKrw), Math.abs(divSum), Math.abs(total), 1);
    var wfCol = function (label, v, color) {
      var h = Math.max(4, Math.abs(v) / maxV * 90);
      return '<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:4px;height:100%;">' +
        '<div class="' + _pfTone(v) + '" style="font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);font-family:var(--font-num);">' + (v >= 0 ? '+' : '') + pfFmtKrw(v) + '</div>' +
        '<div style="width:70%;height:' + h + 'px;border-radius:4px 4px 0 0;background:' + color + ';"></div>' +
        '<div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">' + label + '</div></div>';
    };
    wf = _pfCard('평가 손익 구성 (원화 환산)' + (agg.hasFxSplit ? '' : ' <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);font-weight:var(--font-weight-normal);">매입환율(fxBuy) 기록 종목이 없어 환차 분리 불가</span>'),
      '<div style="display:flex;align-items:flex-end;gap:12px;height:140px;padding-top:8px;">' +
      wfCol('주가 손익', pricePnl, 'var(--c-up)') +
      (agg.hasFxSplit ? wfCol('환차 손익', agg.fxPnlKrw, 'var(--c-down)') : '') +
      (divSum ? wfCol('배당(기록)', divSum, 'var(--c-txt-muted)') : '') +
      wfCol('합계', total, 'var(--c-accent)') + '</div>' +
      (divSum ? '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:4px;">배당은 아래 원장에 직접 기록한 금액 합계(평가액과 별도 현금).</div>' : ''));
  }
  var whatif = agg.usdEval > 0 ? _pfCard('환노출 what-if ' + _pfI('fxexpo'),
    '<div style="font-size:var(--font-size-sm);">원화가 <b id="pfWhatIfPct" style="font-family:var(--font-num);">0</b>% ' +
    '<input type="range" min="-10" max="10" step="1" value="0" oninput="pfWhatIf(this.value)" style="vertical-align:middle;width:180px;accent-color:var(--c-accent);" aria-label="환율 시나리오 슬라이더"> 움직이면' +
    ' → 총 평가액 <b id="pfWhatIfOut" style="font-family:var(--font-num);">' + pfFmtKrw(agg.evalKrw) + '</b> <span id="pfWhatIfDelta" style="font-size:var(--font-size-xs);"></span></div>' +
    '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:6px;">＋ = 원화 약세(달러 강세) 가정. USD 노출 ' + Math.round(agg.usdEval / agg.evalKrw * 100) + '% 기준 단순 환산(가정 시나리오).</div>') : '';

  /* P3 — 배당·입출금 원장 (브라우저 로컬 전용, 서버 미전송) */
  var ledRows = ledger.slice(-6).reverse().map(function (r) {
    var kindLbl = { div: '배당', dep: '입금', wd: '출금' }[r.kind] || r.kind;
    return '<div style="display:flex;justify-content:space-between;gap:8px;font-size:var(--font-size-xs);padding:4px 0;border-bottom:1px dashed var(--c-border);font-family:var(--font-num);">' +
      '<span>' + r.d + ' · ' + kindLbl + (r.memo ? ' · ' + pfEsc(r.memo) : '') + '</span>' +
      '<span><b>' + pfFmtKrw(+r.amt || 0) + '</b> <button onclick="pfLedgerDel(\'' + r.id + '\')" aria-label="기록 삭제" style="background:transparent;border:none;color:var(--c-txt-muted);cursor:pointer;">🗑</button></span></div>';
  }).join('');
  var ledCard = _pfCard('배당·입출금 원장 <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);font-weight:var(--font-weight-normal);">이 브라우저에만 저장 · 총 ' + ledger.length + '건</span>',
    '<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:8px;">' +
    '<input id="pfLedDate" type="date" value="' + new Date().toISOString().slice(0, 10) + '" style="background:var(--c-bg);border:1px solid var(--c-border);border-radius:var(--r-xs);color:var(--c-txt);padding:4px 6px;font-size:var(--font-size-xs);" aria-label="기록 날짜">' +
    '<select id="pfLedKind" style="background:var(--c-bg);border:1px solid var(--c-border);border-radius:var(--r-xs);color:var(--c-txt);padding:4px 6px;font-size:var(--font-size-xs);" aria-label="기록 종류"><option value="div">배당</option><option value="dep">입금</option><option value="wd">출금</option></select>' +
    '<input id="pfLedAmt" type="number" min="0" step="any" placeholder="금액(원)" style="width:110px;background:var(--c-bg);border:1px solid var(--c-border);border-radius:var(--r-xs);color:var(--c-txt);padding:4px 6px;font-size:var(--font-size-xs);" aria-label="금액">' +
    '<input id="pfLedMemo" placeholder="메모(선택)" style="width:110px;background:var(--c-bg);border:1px solid var(--c-border);border-radius:var(--r-xs);color:var(--c-txt);padding:4px 6px;font-size:var(--font-size-xs);" aria-label="메모">' +
    '<button onclick="pfLedgerAdd()" style="font-size:var(--font-size-xs);padding:4px 12px;border:1px solid var(--c-accent);border-radius:var(--r-xs);background:var(--c-accent);color:var(--c-on-accent);cursor:pointer;">＋ 기록</button></div>' +
    (ledRows || '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">기록 없음 — 배당을 기록하면 손익 워터폴에 반영됩니다.</div>') +
    '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:6px;line-height:1.6;">입출금 기록은 참고용 — 위 위험 지표는 평가/매입 비율 기반이라 추가매수에는 원래 강건하며, 대규모 입출금 시 벤치마크 비교 왜곡 고지는 기존과 동일.</div>');

  el.innerHTML = '<div class="widget-title" style="margin:4px 0 10px;">🧭 메르 위험 패널 <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);font-weight:var(--font-weight-normal);">— 내 계좌를 연기금처럼 본다 · ⓘ = 메르식 설명</span></div>' +
    riskCards + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px;" class="pf-risk-2col">' + (wf || '') + (bias || '') + '</div>' + whatif + ledCard;
  window._pfWhatIfBase = { ev: agg.evalKrw, usd: agg.usdEval };
}
/* 원장 저장소 — localStorage 전용(프라이버시: 서버·동기화 페이로드에 절대 미포함) */
function pfLedgerLoad() {
  try { var a = JSON.parse(localStorage.getItem('pfLedgerV1') || '[]'); return Array.isArray(a) ? a : []; } catch (_) { return []; }
}
function pfLedgerSave(a) { try { localStorage.setItem('pfLedgerV1', JSON.stringify(a.slice(-500))); } catch (_) {} }
function pfLedgerAdd() {
  var d = (document.getElementById('pfLedDate') || {}).value;
  var kind = (document.getElementById('pfLedKind') || {}).value;
  var amt = parseFloat((document.getElementById('pfLedAmt') || {}).value);
  var memo = ((document.getElementById('pfLedMemo') || {}).value || '').slice(0, 40);
  if (!d || !kind || !(amt > 0)) { alert('날짜·종류·금액을 확인하세요.'); return; }
  var a = pfLedgerLoad();
  a.push({ id: 'L' + Date.now().toString(36), d: d, kind: kind, amt: amt, memo: memo });
  a.sort(function (x, y) { return x.d < y.d ? -1 : 1; });
  pfLedgerSave(a);
  pfRiskRender();
}
function pfLedgerDel(id) {
  pfLedgerSave(pfLedgerLoad().filter(function (r) { return r.id !== id; }));
  pfRiskRender();
}
function pfWhatIf(v) {
  var b = window._pfWhatIfBase || {};
  var pct = +v;
  var newEv = (b.ev - b.usd) + b.usd * (1 + pct / 100);   // ＋pct% = 원화 약세 = 달러자산 원화 평가액 +pct%
  var delta = newEv - b.ev;
  var elP = document.getElementById('pfWhatIfPct'), elO = document.getElementById('pfWhatIfOut'), elD = document.getElementById('pfWhatIfDelta');
  if (elP) elP.textContent = (pct > 0 ? '+' : '') + pct;
  if (elO) elO.textContent = pfFmtKrw(newEv);
  if (elD) { elD.textContent = '(' + (delta >= 0 ? '+' : '') + pfFmtKrw(delta) + ')'; elD.className = _pfTone(delta); }
}

/* ══════════════════════════════════════════════════════════
   탭 ③ 종목 분석
   ══════════════════════════════════════════════════════════ */
function pfStockRender() {
  var el = document.getElementById('pfTab-stock'); if (!el || _pfActiveTab !== 'stock') return;
  if (!el.dataset.inited) {
    el.dataset.inited = '1';
    var chips = (pfState && pfState.items || []).map(function (it) {
      return '<button onclick="pfStockOpenFromTile(\'' + it.id + '\')" style="font-size:var(--font-size-xs);padding:3px 10px;border:1px solid var(--c-border);border-radius:20px;background:transparent;color:var(--c-txt-dim);cursor:pointer;">' + pfEsc(it.name || it.symbol) + '</button>';
    }).join(' ');
    el.innerHTML =
      '<div class="widget" style="margin-bottom:12px;">' +
      '<div class="widget-title">종목 검색</div>' +
      '<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">' +
      '<input id="pfStockQ" placeholder="종목코드/티커/한글명 (예: 005930, AAPL, 삼성전자)" onkeydown="if(event.key===\'Enter\')pfStockSearch()" style="flex:1;min-width:200px;background:var(--c-bg);border:1px solid var(--c-border);border-radius:var(--r-xs);color:var(--c-txt);padding:6px 9px;font-size:var(--font-size-sm);" aria-label="분석할 종목 검색">' +
      '<button onclick="pfStockSearch()" style="font-size:var(--font-size-sm);padding:6px 14px;border:1px solid var(--c-accent);border-radius:var(--r-xs);background:var(--c-accent);color:var(--c-on-accent);cursor:pointer;">분석</button></div>' +
      '<div id="pfStockCandidates" style="margin-top:6px;"></div>' +
      (chips ? '<div style="margin-top:8px;font-size:var(--font-size-xs);color:var(--c-txt-muted);">보유·관심: ' + chips + '</div>' : '') +
      '</div>' +
      '<div id="pfStockBody"><div style="color:var(--c-txt-muted);font-size:var(--font-size-sm);padding:16px 4px;">종목을 검색하거나 위 칩·브리핑 히트맵에서 선택하세요. 매수/매도 판단은 제공하지 않습니다.</div></div>';
  }
  if (_pfStockCur) pfStockOpen(_pfStockCur, true);
}
async function pfStockSearch() {
  var qEl = document.getElementById('pfStockQ');
  var q = (qEl && qEl.value || '').trim(); if (!q) return;
  var cand = document.getElementById('pfStockCandidates');
  if (/^\d{6}$/.test(q)) { pfStockOpen({ symbol: q, market: 'KR', name: q }); return; }
  if (/^[A-Za-z.\-]{1,6}$/.test(q)) { pfStockOpen({ symbol: q.toUpperCase(), market: 'US', name: q.toUpperCase(), yahoo: q.toUpperCase() }); return; }
  if (cand) cand.innerHTML = '<span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">한글명 검색 중…</span>';
  try {
    var hits = await pfSearchKrByName(q);
    if (!hits || !hits.length) { if (cand) cand.innerHTML = '<span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">검색 결과 없음</span>'; return; }
    if (cand) cand.innerHTML = hits.slice(0, 6).map(function (h) {
      var nm = String(h.name || '').replace(/['"<>]/g, '');
      return '<button onclick="pfStockOpen({symbol:\'' + h.code + '\',market:\'KR\',name:\'' + nm + '\'})" style="font-size:var(--font-size-xs);padding:3px 10px;margin:2px;border:1px solid var(--c-border);border-radius:var(--r-xs);background:transparent;color:var(--c-primary);cursor:pointer;">' + pfEsc(h.name) + ' <span style="color:var(--c-txt-muted);">' + h.code + '</span></button>';
    }).join('');
  } catch (_) { if (cand) cand.innerHTML = '<span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">검색 실패 — 코드를 직접 입력하세요</span>'; }
}
async function pfStockOpen(spec, keep) {
  _pfStockCur = spec;
  if (_pfActiveTab !== 'stock') pfShowTab('stock');
  var body = document.getElementById('pfStockBody'); if (!body) return;
  if (!keep) body.innerHTML = '<div style="color:var(--c-txt-muted);font-size:var(--font-size-sm);padding:16px 4px;">' + pfEsc(spec.name || spec.symbol) + ' 데이터 로딩 중…</div>';
  var held = null;
  (pfState && pfState.items || []).forEach(function (i) { if (i.symbol === spec.symbol && i.market === spec.market) held = i; });
  // 시세 + 일봉 병렬
  var qP = pfFetchQuote({ symbol: spec.symbol, market: spec.market, yahoo: spec.yahoo || (held && held.yahoo) });
  var candles = null;
  var sym = spec.yahoo || (held && held.yahoo) || (spec.market === 'US' ? spec.symbol : null);
  if (sym) {
    try {
      var j = await _fetchJsonWithProxies('https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(sym) + '?range=1y&interval=1d');
      var res = j && j.chart && j.chart.result && j.chart.result[0];
      if (res && res.timestamp) {
        var qd = res.indicators.quote[0], off = (res.meta && res.meta.gmtoffset) || 0;
        candles = [];
        for (var i = 0; i < res.timestamp.length; i++) {
          if (qd.close[i] == null) continue;
          candles.push({ time: new Date((res.timestamp[i] + off) * 1000).toISOString().slice(0, 10),
                         open: +qd.open[i], high: +qd.high[i], low: +qd.low[i], close: +qd.close[i], volume: +(qd.volume[i] || 0) });
        }
      }
    } catch (_) {}
  }
  if ((!candles || candles.length < 30) && spec.market === 'KR') {
    candles = await pfFetchNaverDaily(spec.symbol, 420);
  }
  var q = await qP;
  if (_pfStockCur !== spec) return;  // 로딩 중 다른 종목으로 전환됨
  var name = (q && q.name) || spec.name || spec.symbol;

  /* 신호등 — 기존 지표 함수 재사용 (판단 아님, 상태 요약) */
  var sigs = [];
  if (candles && candles.length >= 60) {
    var closes = candles.map(function (c) { return c.close; });
    var s5 = pfSMA(closes, 5), s20 = pfSMA(closes, 20), s60 = pfSMA(closes, 60);
    var L = closes.length - 1;
    if (s5[L] != null && s20[L] != null && s60[L] != null) {
      var aligned = s5[L] > s20[L] && s20[L] > s60[L];
      var reversed = s5[L] < s20[L] && s20[L] < s60[L];
      sigs.push({ c: aligned ? 'g' : (reversed ? 'r' : 'y'), t: 'MA ' + (aligned ? '정배열' : (reversed ? '역배열' : '혼조')) });
    }
    var rsi = pfRSI(closes, 14); var rL = rsi[rsi.length - 1];
    if (rL != null) sigs.push({ c: rL >= 70 ? 'r' : (rL <= 30 ? 'r' : (rL >= 60 || rL <= 40 ? 'y' : 'g')), t: 'RSI ' + rL.toFixed(0) + (rL >= 70 ? ' 과열권' : (rL <= 30 ? ' 침체권' : '')) });
    var mac = pfMACD(closes, 12, 26, 9);
    if (mac && mac.hist && mac.hist.length > 6) {
      var h = mac.hist, hL = h.length - 1, cross = null;
      for (var k = hL; k > hL - 5 && k > 0; k--) {
        if (h[k] != null && h[k - 1] != null && (h[k] >= 0) !== (h[k - 1] >= 0)) { cross = h[k] >= 0 ? 'golden' : 'dead'; break; }
      }
      sigs.push(cross ? { c: cross === 'golden' ? 'g' : 'r', t: 'MACD ' + (cross === 'golden' ? '골든크로스(5일 내)' : '데드크로스(5일 내)') } : { c: h[hL] >= 0 ? 'g' : 'y', t: 'MACD ' + (h[hL] >= 0 ? '양의 모멘텀' : '음의 모멘텀') });
    }
    var hi52 = Math.max.apply(null, closes.slice(-252)), lo52 = Math.min.apply(null, closes.slice(-252));
    var cur = closes[L];
    sigs.push({ c: 'y', t: '52주 고점 −' + ((1 - cur / hi52) * 100).toFixed(1) + '% · 저점 +' + ((cur / lo52 - 1) * 100).toFixed(1) + '%' });
  }
  var sigHtml = sigs.map(function (s) {
    var col = s.c === 'g' ? 'var(--color-success,#0ca30c)' : (s.c === 'r' ? 'var(--c-up)' : 'var(--color-warning,#c98500)');
    return '<span style="display:inline-flex;align-items:center;gap:6px;background:var(--c-surface);border-radius:20px;padding:3px 12px 3px 8px;font-size:var(--font-size-xs);font-weight:var(--font-weight-semibold);margin:3px 4px 3px 0;"><span style="width:8px;height:8px;border-radius:50%;background:' + col + ';"></span>' + s.t + '</span>';
  }).join('');

  body.innerHTML =
    '<div class="widget" style="margin-bottom:12px;">' +
    '<div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px;">' +
    '<div><span style="font-size:var(--font-size-lg);font-weight:var(--font-weight-bold);">' + pfEsc(name) + '</span> <span style="color:var(--c-txt-muted);font-size:var(--font-size-xs);font-family:var(--font-num);">' + pfEsc(spec.symbol) + ' · ' + (spec.market === 'KR' ? '국내' : '미국') + '</span>' +
    (held && held.qty ? ' <span style="font-size:var(--font-size-xs);background:var(--c-surface);border-radius:20px;padding:2px 10px;color:var(--c-txt-dim);">보유 ' + held.qty + (spec.market === 'KR' ? '주' : ' sh') + '</span>' : '') + '</div>' +
    '<div style="font-family:var(--font-num);font-size:var(--font-size-lg);font-weight:var(--font-weight-bold);">' + (q ? pfFmtPrice(q.price, q.ccy) : '-') + ' ' + (q ? pfChgHtml(q.pct) : '') + '</div></div>' +
    '<div id="pfStockWarnBadges"></div>' +
    (sigHtml ? '<div style="margin-top:8px;">' + sigHtml + '</div>' : '') +
    '<div id="pfStockLwWrap" style="height:300px;margin-top:10px;"></div>' +
    '<div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px;margin-top:6px;">' +
    '<span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">일봉 1년 · 신호등은 지표 상태 요약이며 매수/매도 판단이 아닙니다</span>' +
    (held ? '<button onclick="pfOpenChart(\'' + held.id + '\')" style="font-size:var(--font-size-xs);padding:3px 10px;border:1px solid var(--c-border);border-radius:var(--r-xs);background:transparent;color:var(--c-primary);cursor:pointer;">🔍 상세 차트(MA·RSI·MACD) →</button>' : '') + '</div>' +
    '</div>' +
    '<div id="pfStockFlows"></div>' +
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;" class="pf-stock-2col">' +
    _pfCard('펀더멘털', '<div id="pfStockFunda" style="font-size:var(--font-size-sm);color:var(--c-txt-muted);">불러오는 중…</div>') +
    _pfCard('메르 블로그 언급', '<div id="pfStockMer" style="font-size:var(--font-size-sm);color:var(--c-txt-muted);">검색 중…</div>') +
    '</div>';

  /* 수급 패널 + 경보 배지 + 시가총액 (토스 PC 스냅샷 — 트래킹 종목만 커버) */
  try { _pfFlowsRender(spec, q); } catch (_) {}

  /* LWC 인라인 차트 */
  var wrap = document.getElementById('pfStockLwWrap');
  if (_pfStockLw) { try { _pfStockLw.remove(); } catch (_) {} _pfStockLw = null; }
  if (wrap && candles && candles.length >= 2 && typeof LightweightCharts !== 'undefined') {
    _pfStockLw = pfMkChart(wrap, 300);
    var cs = _pfStockLw.addCandlestickSeries({ upColor: (window.CUP || '#d13c3c'), downColor: (window.CDN || '#2a78d6'), borderVisible: false, wickUpColor: (window.CUP || '#d13c3c'), wickDownColor: (window.CDN || '#2a78d6') });
    cs.setData(candles.map(function (c) { return { time: c.time, open: c.open, high: c.high, low: c.low, close: c.close }; }));
    var vs = _pfStockLw.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' } });
    _pfStockLw.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vs.setData(candles.map(function (c) { return { time: c.time, value: c.volume || 0, color: (c.close >= c.open ? (window.CUP || '#d13c3c') : (window.CDN || '#2a78d6')) + '55' }; }));
    _pfStockLw.timeScale().fitContent();
  } else if (wrap) {
    wrap.innerHTML = '<div style="color:var(--c-txt-muted);font-size:var(--font-size-sm);padding:30px;text-align:center;">차트 데이터를 불러오지 못했습니다.</div>';
  }

  /* 펀더멘털 (P2 — fundamentals.json) */
  pfFundaLoad().then(function (fd) {
    var box = document.getElementById('pfStockFunda'); if (!box || _pfStockCur !== spec) return;
    var price = q && q.price;
    var row = null, isKr = spec.market === 'KR';
    if (fd) row = isKr ? (fd.kr || {})[spec.symbol] : (fd.us || {})[spec.symbol];
    if (!row) {
      box.innerHTML = (spec.secType === 'etf' || (held && held.secType === 'etf'))
        ? 'ETF 는 개별 기업 재무가 없어 펀더멘털을 제공하지 않습니다.'
        : (isKr
          ? '데이터 없음 — <code>OPENDART_API_KEY</code> 시크릿 등록 후 일일 런부터 수집됩니다.'
          : '데이터 없음 — 다음 일일 런에서 수집됩니다(관심목록 등록 종목 대상).');
      return;
    }
    // PER/PBR 은 저장 EPS/BPS × 현재가로 재계산(신선도). 실패 시 저장값 폴백.
    var per = (price && row.eps > 0) ? price / row.eps : row.per;
    var pbr = (price && row.bps > 0) ? price / row.bps : row.pbr;
    var dy = row.divYield != null ? row.divYield : ((price && row.dps) ? row.dps / price * 100 : null);
    function fv(v, suf, nd) { return v == null || !isFinite(v) ? '-' : (+v).toFixed(nd == null ? 1 : nd) + (suf || ''); }
    box.innerHTML =
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 14px;font-family:var(--font-num);color:var(--c-txt);">' +
      '<div>PER <b>' + fv(per) + '</b></div>' +
      '<div>PBR <b>' + fv(pbr, '', 2) + '</b></div>' +
      '<div>ROE <b>' + fv(row.roe, '%') + '</b></div>' +
      '<div>배당수익률 <b>' + fv(dy, '%', 2) + '</b></div>' +
      '<div>영업이익률 <b>' + fv(row.opMargin, '%') + '</b></div>' +
      (isKr ? '<div>부채비율 <b>' + fv(row.debtRatio, '%', 0) + '</b></div>' : '<div>실적 발표 <b style="font-size:var(--font-size-xs);">' + (row.earningsDate || '-') + '</b></div>') +
      '</div>' +
      '<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:8px;">' +
      (isKr ? row.year + '년 사업보고서(OpenDART) 기준 · PER/PBR 은 현재가로 재계산' : 'yfinance 기준 · ' + (row.fetchedAt || '')) + '</div>';
  });

  /* 메르 언급 */
  pfMerLoad().then(function (mer) {
    var box = document.getElementById('pfStockMer'); if (!box || _pfStockCur !== spec) return;
    var hits = pfMerMentions(mer, name, spec.symbol);
    box.innerHTML = hits.length
      ? '<ul style="list-style:none;margin:0;padding:0;">' + hits.map(function (p) {
          return '<li style="padding:5px 0;border-bottom:1px dashed var(--c-border);"><a href="' + pfEsc(p.url) + '" target="_blank" rel="noopener" style="color:var(--c-primary);text-decoration:none;">' + pfEsc(p.title) + '</a> <span style="color:var(--c-txt-muted);font-size:var(--font-size-xs);">' + (p.date || '').slice(5, 10) + '</span></li>';
        }).join('') + '</ul><div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:6px;">최근 150건 로컬 검색 · <a href="?p=merblog" style="color:var(--c-primary);">전체기간 검색 →</a></div>'
      : '최근 150건에서 언급 없음 · <a href="?p=merblog" style="color:var(--c-primary);">전체기간 검색 →</a>';
  });
}

/* ── 종목 수급 패널 (data.stockFlows — 토스 PC 스냅샷, 트래킹 종목만) ──
   단위 주의: 토스 종목별 수급은 전부 **주수**(거래대금 아님). 없는 항목은 칸을
   숨긴다(ETF 는 대차·프로그램이 비어 오는 게 정상 — 날조 금지). */
var _pfFlowsChart = null;
function _pfMcapFmt(v) {
  if (!v || !isFinite(v)) return null;
  return v >= 1e12 ? (v / 1e12).toFixed(1) + '조' : Math.round(v / 1e8).toLocaleString() + '억';
}
function _pfShFmt(v) {
  if (v == null || !isFinite(v)) return '-';
  var a = Math.abs(v), s = v < 0 ? '-' : '+';
  if (a >= 1e8) return s + (a / 1e8).toFixed(1) + '억주';
  if (a >= 1e4) return s + (a / 1e4).toFixed(1) + '만주';
  return s + Math.round(a).toLocaleString() + '주';
}
function _pfFlowsRender(spec, q) {
  var box = document.getElementById('pfStockFlows'); if (!box) return;
  var sf = (_pfData() || {}).stockFlows || {};
  var e = spec.market === 'KR' ? (sf.items || {})[spec.symbol] : null;
  var badges = document.getElementById('pfStockWarnBadges');

  /* 헤더 보강: 시가총액 + 외국인 보유율 + 경보 배지 */
  if (e && badges) {
    var chips = [];
    var mcap = (q && q.price && e.shares) ? _pfMcapFmt(q.price * e.shares) : null;
    if (mcap) chips.push('<span style="font-size:var(--font-size-xs);background:var(--c-surface);border-radius:20px;padding:2px 10px;color:var(--c-txt-dim);">시가총액 ' + mcap + ' <span style="color:var(--c-txt-muted);">(상장주식수×현재가)</span></span>');
    var inv = e.investor || [];
    var hold = null;
    for (var i = inv.length - 1; i >= 0; i--) { if (inv[i].fholdRate != null) { hold = inv[i]; break; } }
    if (hold) chips.push('<span style="font-size:var(--font-size-xs);background:var(--c-surface);border-radius:20px;padding:2px 10px;color:var(--c-txt-dim);">외국인 보유율 ' + (hold.fholdRate * 100).toFixed(2) + '%</span>');
    (e.warnings || []).forEach(function (w) {
      var t = (w && (w.name || w.type || w.title)) || (typeof w === 'string' ? w : '');
      if (t) chips.push('<span style="font-size:var(--font-size-xs);background:var(--warn-bg,rgba(200,133,0,.15));border-radius:20px;padding:2px 10px;color:var(--color-warning,#c98500);font-weight:var(--font-weight-semibold);">⚠ ' + pfEsc(String(t)) + '</span>');
    });
    if (chips.length) badges.innerHTML = '<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;">' + chips.join('') + '</div>';
  }

  if (!e || !(e.investor || []).length) { box.innerHTML = ''; return; }
  var gen = ((sf.generatedAt || '').slice(5, 16)).replace('T', ' ');

  /* 보조 통계 칩: 공매도 비중 · 신용잔고율 · 대차잔고 (있는 것만) */
  var stat = [];
  var sh = (e.short || [])[ (e.short || []).length - 1 ];
  if (sh && sh.volumeRate != null) stat.push('공매도 비중 <b>' + (sh.volumeRate * 100).toFixed(2) + '%</b> <span style="color:var(--c-txt-muted);">(' + (sh.date || '').slice(5) + ')</span>');
  var cr = (e.credit || [])[ (e.credit || []).length - 1 ];
  if (cr && cr.marginRate != null && cr.marginBal > 0) stat.push('신용융자 잔고율 <b>' + (cr.marginRate * 100).toFixed(2) + '%</b> <span style="color:var(--c-txt-muted);">(' + (cr.date || '').slice(5) + ')</span>');
  var ld = (e.lending || [])[ (e.lending || []).length - 1 ];
  if (ld && ld.bal != null) stat.push('대차잔고 <b>' + _pfShFmt(ld.bal).replace('+', '') + '</b> <span style="color:var(--c-txt-muted);">(' + (ld.date || '').slice(5) + ')</span>');
  var pg = (e.program || [])[ (e.program || []).length - 1 ];
  if (pg && (pg.arb != null || pg.nonArb != null)) stat.push('프로그램 순매수 <b>' + _pfShFmt((pg.arb || 0) + (pg.nonArb || 0)) + '</b> <span style="color:var(--c-txt-muted);">(' + (pg.date || '').slice(5) + ')</span>');

  box.innerHTML =
    '<div class="widget" style="margin-bottom:12px;">' +
    '<div class="widget-title">수급 — 투자자별 순매수 <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);font-weight:var(--font-weight-normal);">단위: 주 · 토스증권 Open API · 수집 ' + pfEsc(gen) + '</span></div>' +
    '<div style="height:190px;"><canvas id="pfFlowsCanvas"></canvas></div>' +
    (stat.length ? '<div style="display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:8px;font-size:var(--font-size-xs);color:var(--c-txt);font-family:var(--font-num);">' + stat.map(function (s) { return '<span>' + s + '</span>'; }).join('') + '</div>' : '') +
    '</div>';

  if (typeof Chart === 'undefined') return;
  if (_pfFlowsChart) { try { _pfFlowsChart.destroy(); } catch (_) {} _pfFlowsChart = null; }
  var cv = document.getElementById('pfFlowsCanvas'); if (!cv) return;
  var rows = (e.investor || []).slice(-20);
  var tc = (typeof getThemeColors === 'function') ? getThemeColors() : {};
  var series = tc.series || [];
  var mkBar = function (label, key, color) {
    return { label: label, data: rows.map(function (r) { return r[key]; }),
             backgroundColor: color, borderWidth: 0, maxBarThickness: 10 };
  };
  _pfFlowsChart = new Chart(cv.getContext('2d'), {
    type: 'bar',
    data: { labels: rows.map(function (r) { return (r.date || '').slice(5); }),
            datasets: [mkBar('외국인', 'foreign', series[0] || '#4d78cc'),
                       mkBar('기관', 'inst', series[1] || '#9a6dd7'),
                       mkBar('개인', 'retail', series[2] || '#5aa26e')] },
    options: { responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, font: { size: 10 } } },
                 tooltip: { callbacks: { label: function (c) { return c.dataset.label + ' ' + _pfShFmt(c.raw); } } } },
      scales: { x: { grid: { display: false }, ticks: { font: { size: 9 }, maxTicksLimit: 10 } },
                y: { ticks: { font: { size: 9 }, callback: function (v) { return _pfShFmt(v); } } } } }
  });
}
