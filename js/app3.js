// ════════════════════════════════════════════════════════════════════════════
// 대시보드 확장 기능 모음
//  · 🤖 오늘의 매크로 3줄 요약 배너 (Task 4.2 — scripts/ai_briefing.py 산출물 렌더)
//  · 🔔 경제 캘린더 ★★★ 이벤트 발표 알림 (Task 2.3 — Notification API)
//  · 🔀 이중축 지표 비교 차트 (Task 3.1)
//  · ↕ 대시보드 홈 위젯 드래그 정렬 (Task 2.2 — localStorage 저장)
// ════════════════════════════════════════════════════════════════════════════

// ── 공통: 인페이지 토스트 (알림 권한 거부/미지원 폴백) ──────────────────────
function showToast(msg, ms = 6000) {
  let host = document.getElementById('econToastHost');
  if(!host) {
    host = document.createElement('div');
    host.id = 'econToastHost';
    // 라이브 리전 — 자식 토스트 추가가 스크린리더에 자동 낭독됨 (헤드 window.showToast 와 동급 보장)
    host.setAttribute('role', 'status');
    host.setAttribute('aria-live', 'polite');
    host.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:500;display:flex;flex-direction:column;gap:8px;max-width:340px;';
    document.body.appendChild(host);
  }
  const t = document.createElement('div');
  t.style.cssText = 'background:var(--c-card,#1f2945);border:1px solid var(--c-accent);border-radius:var(--r-sm);padding:10px 14px;font-size:12px;color:var(--c-txt,#e8ebf5);box-shadow:0 8px 24px rgba(0,0,0,.4);line-height:1.5;';
  t.textContent = msg;
  host.appendChild(t);
  setTimeout(() => { try { t.remove(); } catch(_) {} }, ms);
}

// ── 🤖 오늘의 매크로 3줄 요약 배너 ─────────────────────────────────────────
function renderAiBriefing(b) {
  const box = document.getElementById('aiBriefingBanner');
  if(!box) return;
  const lines = (b && Array.isArray(b.lines)) ? b.lines.filter(s => s && String(s).trim()) : [];
  if(!lines.length) { box.style.display = 'none'; return; }
  document.getElementById('aiBriefingLines').innerHTML = lines.slice(0, 3).map((s, i) =>
    `<div class="ai-brief-line" style="display:flex;gap:8px;align-items:flex-start;"><span style="color:var(--c-primary);font-weight:var(--font-weight-bold);flex-shrink:0;">${i + 1}.</span><span style="min-width:0;">${escapeHtml(String(s))}</span></div>`).join('');
  const srcLabel = b.source === 'rule' ? '규칙 기반 요약'
                 : b.source === 'client-rule' ? '실시간 규칙 요약'
                 : (b.source === 'gemini' ? 'Gemini' : b.source === 'openai' ? 'OpenAI' : 'AI');
  // 면책 상시 노출 + 생성일이 오늘(KST)이 아니면 스테일 경고 — 파이프라인이 며칠 멈춰도
  // 이전 날짜 요약이 '오늘의' 제목으로 최신처럼 보이는 문제 방지.
  const _kstToday = new Date(Date.now() + 9*36e5).toISOString().slice(0,10);
  const _isOld = typeof b.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(b.date) && b.date < _kstToday;
  // 생성 시각까지 표기 — 요약 속 수치는 이 시점의 스냅샷이라 실시간 KPI 와 다를 수 있다.
  // (첫 화면에서 KOSPI 가 요약/칩/티커 세 값으로 다르게 보이던 혼란의 표기 해소 — 감사 A3)
  let _asofTxt = String(b.date || '');
  if(typeof b.generatedAt === 'string' && b.generatedAt.length >= 16) {
    const _t = b.generatedAt.slice(11, 16);
    if(/^\d{2}:\d{2}$/.test(_t)) _asofTxt += ` ${_t}`;
  }
  document.getElementById('aiBriefingMeta').innerHTML =
    (_isOld ? `<span style="color:var(--c-warn);font-weight:var(--font-weight-semibold);">⚠ ${escapeHtml(_asofTxt)} 생성 (오늘 아님)</span>` : escapeHtml(_asofTxt))
    + ` 기준 스냅샷 · ${srcLabel} · 참고용, 투자 조언 아님`;
  box.style.borderLeftColor = _isOld ? 'var(--c-warn)' : '';
  box.style.display = 'block';
}

// 3줄 요약을 '지금 화면의 최신 값'으로 직접 조립 — scripts/ai_briefing.py 의 규칙 기반
// 라인과 동일한 구성. 서버 요약은 GitHub Actions 주기에만 갱신되어, 새로고침을 눌러도
// 수치가 그대로인 문제(클라이언트 실시간 보강값 미반영)를 해소한다.
function composeClientBriefingLines() {
  const d = (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators) ? _latestDataForIndicators : {};
  const idx = d.indices || {}, fx = d.fx || {}, com = d.commodities || {};
  const eiUs = (d.economicIndicators || {}).us || {};
  const num = (v, nd) => (v == null || isNaN(+v)) ? '—' : (+v).toLocaleString('ko-KR', { maximumFractionDigits: nd != null ? nd : 2 });
  const chg = v => (v == null || isNaN(+v)) ? '—' : `${+v >= 0 ? '▲' : '▼'}${Math.abs(+v).toFixed(2)}%`;
  const k = idx.KOSPI || {}, s = idx.SP500 || {}, n = idx.NASDAQ || {};
  const line1 = `증시 — KOSPI ${num(k.price)} (${chg(k.change)}), S&P500 ${num(s.price)} (${chg(s.change)}), 나스닥 ${num(n.price)} (${chg(n.change)})`;
  const u = fx.USDKRW || {};
  let line2 = `환율·금리 — 원/달러 ${num(u.rate)}원 (${chg(u.change)})`;
  const ff = eiUs.ff_rate && eiUs.ff_rate.value;
  const vix = eiUs.vix && eiUs.vix.value;
  if(ff != null) line2 += `, 미국 기준금리 ${num(ff)}%`;
  if(vix != null) line2 += `, VIX ${num(vix)}`;
  const w = com.WTI || {}, g = com.Gold || {};
  let line3 = `원자재·심리 — WTI $${num(w.price)} (${chg(w.change)}), 금 $${num(g.price)} (${chg(g.change)})`;
  const fg = (d.sentiment || {}).fear_greed || {};
  if(fg.value != null) line3 += `, 공포탐욕 ${num(fg.value, 0)}(${fg.rating || '—'})`;
  return [line1, line2, line3];
}

// 3줄 요약 전용 새로고침 — data.json 재페치(최대 10초 대기) 후 클라이언트에서 즉시 재조립.
// 항상 짧게 종료되므로 '⟳ 갱신중…' 고착이 없다.
async function refreshAiBriefing(btn) {
  _refreshFeedback(btn, 'loading');
  try {
    await Promise.race([
      (typeof loadRealData === 'function' ? loadRealData() : Promise.resolve()).catch(() => {}),
      new Promise(res => setTimeout(res, 10000)),
    ]);
    const lines = composeClientBriefingLines();
    renderAiBriefing({ date: new Date().toISOString().slice(0, 10), lines, source: 'client-rule' });
    _refreshFeedback(btn, 'success', '요약 갱신');
  } catch(_) {
    _refreshFeedback(btn, 'error', '갱신 실패');
  }
}

// ── 🚦 시장 리스크 신호등 + 📌 오늘의 브리핑 스트립 ─────────────────────────
// 8개 구성 지표를 0~100 위험 점수로 합성 — 고정 임계값 대신 각 지표의 자기 이력
// 백분위(가용 창 기준)를 사용해 수집 소스의 척도 변화에 강건하다. 결측 지표는
// 가중치 재정규화로 제외 (VKOSPI 는 이력 30일·척도 비표준이라 산식에서 의도적 제외).
let _riskLast = null;

function _pctRank(vals, cur) {
  const v = vals.filter(Number.isFinite);
  if(!v.length || !Number.isFinite(cur)) return null;
  return 100 * v.filter(x => x <= cur).length / v.length;
}
// 20일 실현변동성(연율화 %) 롤링 시계열 — 마지막 원소가 현재 값
function _rollingVol20(closes) {
  const c = closes.filter(Number.isFinite);
  if(c.length < 60) return null;
  const rets = [];
  for(let i = 1; i < c.length; i++) { if(c[i] > 0 && c[i-1] > 0) rets.push(Math.log(c[i] / c[i-1])); }
  const win = 20, out = [];
  for(let i = win; i <= rets.length; i++) {
    const w = rets.slice(i - win, i), m = w.reduce((a, b) => a + b, 0) / win;
    const sd = Math.sqrt(w.reduce((a, r) => a + (r - m) ** 2, 0) / (win - 1));
    out.push(sd * Math.sqrt(252) * 100);
  }
  return out.length ? out : null;
}
function _histVals(h) { return Object.values(h || {}).map(Number).filter(Number.isFinite); }

function computeRiskScore(d) {
  if(!d) return null;
  const clamp = x => Math.max(0, Math.min(100, x));
  const comps = [];
  const add = (name, raw, fmt, score, w, win) => {
    if(score != null && Number.isFinite(score)) comps.push({ name, raw, fmt, score: clamp(score), w, win });
  };
  const eiUs = (d.economicIndicators || {}).us || {};
  const sent = d.sentiment || {};
  try { const v = eiUs.vix;
        if(v && v.value != null) add('VIX (미국 주식 변동성)', +v.value, (+v.value).toFixed(1), _pctRank(_histVals(v.history), +v.value), 0.15, '5년 백분위'); } catch(_) {}
  try { const rv = _rollingVol20(((d.history || {}).indices || {}).KOSPI ? d.history.indices.KOSPI.map(p => +p.close) : []);
        if(rv) add('KOSPI 20일 실현변동성', rv[rv.length-1], rv[rv.length-1].toFixed(1) + '%', _pctRank(rv, rv[rv.length-1]), 0.20, '5년 백분위'); } catch(_) {}
  try { const fg = sent.fear_greed;
        if(fg && fg.value != null) add('공포탐욕지수 (역방향)', +fg.value, (+fg.value).toFixed(0) + ' (' + (fg.rating || '—') + ')', 100 - (+fg.value), 0.15, '0~100 원척도'); } catch(_) {}
  try { const m = sent.move;
        if(m && m.value != null) add('MOVE (미 채권 변동성)', +m.value, (+m.value).toFixed(1), _pctRank(_histVals(m.history), +m.value), 0.10, '2년 백분위'); } catch(_) {}
  try { const yk = d.yieldCurve && d.yieldCurve.kr;
        const aa = yk && yk.corp && yk.corp.corp3yAA && yk.corp.corp3yAA.current;
        const ktb3 = yk && Array.isArray(yk.current) ? yk.current[4] : null;   // slot4 = 국고 3Y
        const sp = (aa != null && ktb3 != null) ? (+aa - +ktb3) : null;
        if(sp != null && Number.isFinite(sp)) add('한국 신용스프레드 (회사채AA- − 국고3Y)', sp, sp.toFixed(2) + '%p', (sp - 0.3) / 1.5 * 100, 0.15, '고정구간 0.3~1.8%p'); } catch(_) {}
  try { const yu = d.yieldCurve && d.yieldCurve.us;
        const slope = (yu && Array.isArray(yu.current) && yu.current[7] != null && yu.current[4] != null) ? (+yu.current[7] - +yu.current[4]) : null;
        if(slope != null && Number.isFinite(slope)) add('미국채 10Y−2Y 기울기', slope, (slope >= 0 ? '+' : '') + slope.toFixed(2) + '%p', (1.0 - slope) / 2.0 * 100, 0.10, '고정구간 ±1.0%p'); } catch(_) {}
  try { const rv = _rollingVol20(((d.history || {}).fx || {}).USDKRW ? d.history.fx.USDKRW.map(p => +p.close) : []);
        if(rv) add('원/달러 20일 실현변동성', rv[rv.length-1], rv[rv.length-1].toFixed(1) + '%', _pctRank(rv, rv[rv.length-1]), 0.10, '5년 백분위'); } catch(_) {}
  try { const hy = eiUs.hy_spread;
        if(hy && hy.value != null) add('미 하이일드 스프레드', +hy.value, (+hy.value).toFixed(2) + '%p', _pctRank(_histVals(hy.history), +hy.value), 0.05, '3년 백분위'); } catch(_) {}
  if(!comps.length) return null;
  const wSum = comps.reduce((a, c) => a + c.w, 0);
  const score = Math.round(comps.reduce((a, c) => a + c.score * c.w, 0) / wSum * 10) / 10;
  const light = score < 35 ? 'g' : score <= 65 ? 'y' : 'r';
  return { score, light, comps };
}

const _RISK_LABELS = { g: '안정', y: '주의', r: '경계' };
const _RISK_DESC = {
  g: '시장 안정 — 위험선호 국면', y: '중립·주의 — 일부 위험 신호 감지', r: '경계 — 복수 지표가 위험 신호',
};

function renderRiskLight(d) {
  const dot = document.getElementById('riskDot'), lbl = document.getElementById('riskLabel'), chip = document.getElementById('riskLightChip');
  if(!dot || !lbl) return;
  const r = computeRiskScore(d);
  _riskLast = r;
  if(!r) { dot.className = 'risk-dot'; lbl.textContent = '—'; return; }
  dot.className = 'risk-dot ' + r.light;
  lbl.textContent = `${_RISK_LABELS[r.light]} ${Math.round(r.score)}`;
  if(chip) {
    chip.title = `${_RISK_DESC[r.light]} · 종합 ${r.score}점 (0 안정 ~ 100 위험) — 클릭: 산출 근거`;
    chip.setAttribute('aria-label', `시장 리스크 신호등: 현재 ${_RISK_LABELS[r.light]}, 종합 ${Math.round(r.score)}점. 클릭하면 산출 근거를 표시합니다`);
  }
}

function showRiskDetail() {
  if(!_riskLast || !_riskLast.comps || !_riskLast.comps.length) {
    showToast('리스크 점수를 계산할 데이터가 아직 없습니다.', 4000);
    return;
  }
  const r = _riskLast;
  // 점 색은 .risk-dot CSS 클래스 재사용 — 색상관습 토글과 무관한 고정 의미색 유지
  const dot = (st, sz) => `<span class="risk-dot ${st}" style="display:inline-block;width:${sz}px;height:${sz}px;margin-right:5px;"></span>`;
  const td = 'padding:5px 8px;border-bottom:1px solid var(--c-border-weak,var(--c-border));font-size:11.5px;';
  const rows = r.comps.map(c => {
    const st = c.score < 35 ? 'g' : c.score <= 65 ? 'y' : 'r';
    return `<tr>
      <td style="${td}">${c.name}</td>
      <td style="${td}text-align:right;font-family:var(--font-num);">${c.fmt}</td>
      <td style="${td}text-align:right;">${dot(st, 8)}${Math.round(c.score)}</td>
      <td style="${td}color:var(--c-txt-dim);">${c.win}</td>
      <td style="${td}text-align:right;color:var(--c-txt-dim);">${Math.round(c.w * 100)}%</td>
    </tr>`;
  }).join('');
  openInfoModal('🚦 시장 리스크 신호등',
    `${dot(r.light, 9)}종합 <b>${r.score}점</b> · ${_RISK_DESC[r.light]}`,
    `<table style="width:100%;border-collapse:collapse;margin-bottom:10px;">
       <thead><tr>
         <th style="${td}text-align:left;color:var(--c-txt-dim);font-weight:var(--font-weight-semibold);">구성 지표</th>
         <th style="${td}text-align:right;color:var(--c-txt-dim);font-weight:var(--font-weight-semibold);">현재값</th>
         <th style="${td}text-align:right;color:var(--c-txt-dim);font-weight:var(--font-weight-semibold);">위험점수</th>
         <th style="${td}text-align:left;color:var(--c-txt-dim);font-weight:var(--font-weight-semibold);">정규화 기준</th>
         <th style="${td}text-align:right;color:var(--c-txt-dim);font-weight:var(--font-weight-semibold);">가중치</th>
       </tr></thead><tbody>${rows}</tbody></table>
     <div style="font-size:10.5px;color:var(--c-txt-dim);line-height:1.6;">
       각 지표를 자기 이력 백분위(또는 고정구간)로 0~100 위험점수화한 뒤 가중 평균합니다.
       결측 지표는 가중치를 재정규화해 제외합니다. 판정: 35 미만 🟢 안정 · 35~65 🟡 주의 · 65 초과 🔴 경계.<br>
       ※ VKOSPI 는 수집 이력이 짧아(30일) 산식에서 제외 — 시장 분위기 카드에서 참고용으로 확인하세요. 본 점수는 투자 조언이 아닙니다.
     </div>`);
}

// ── 📌 오늘의 브리핑 스트립 ────────────────────────────────────────────────
function _bsNum(v, nd) { return (v == null || isNaN(+v)) ? '—' : (+v).toLocaleString('ko-KR', { maximumFractionDigits: nd != null ? nd : 2 }); }
function _bsChgHtml(v) {
  if(v == null || isNaN(+v)) return '';
  const up = +v >= 0;
  return `<span class="${up ? 'up-txt' : 'down-txt'}" style="font-size:var(--font-size-sm);">${up ? '▲' : '▼'} ${up ? '+' : '-'}${Math.abs(+v).toFixed(2)}%</span>`;
}
// 다음 예정 이벤트 — 서버 병합 포함 calEvents 에서 실적(act) 없는 미래 이벤트 중 가장 임박한 것.
// 동일 날짜에 여러 건이면 중요도(★) 높은 쪽 우선.
function _bsNextEvent() {
  if(typeof calEvents === 'undefined' || !Array.isArray(calEvents)) return null;
  const now = new Date();
  const cands = [];
  calEvents.forEach(e => {
    if(!e || !e.name || (e.act && String(e.act).trim())) return;
    let ms = null;
    const m = String(e.dt || '').match(/(\d{2})\.(\d{2})(?:\s+(\d{2}):(\d{2}))?/);
    if(e.iso && /^\d{4}-\d{2}-\d{2}$/.test(e.iso)) {
      ms = new Date(e.iso + 'T' + (m && m[3] ? `${m[3]}:${m[4]}` : '23:59') + ':00').getTime();
    } else if(m) {
      const yr = now.getFullYear(), mo = parseInt(m[1], 10);
      // 연말 경계: 현재 11~12월인데 이벤트가 1~2월이면 익년으로 해석
      const y2 = (now.getMonth() + 1 >= 11 && mo <= 2) ? yr + 1 : yr;
      ms = new Date(y2, mo - 1, parseInt(m[2], 10), m[3] ? parseInt(m[3], 10) : 23, m[4] ? parseInt(m[4], 10) : 59).getTime();
    }
    if(ms != null && ms >= now.getTime() - 6 * 3600 * 1000) cands.push({ e, ms });
  });
  if(!cands.length) return null;
  cands.sort((a, b) => a.ms - b.ms);
  const firstDay = new Date(cands[0].ms).toDateString();
  const sameDay = cands.filter(c => new Date(c.ms).toDateString() === firstDay);
  sameDay.sort((a, b) => (b.e.stars || 0) - (a.e.stars || 0) || a.ms - b.ms);
  return sameDay[0];
}

function renderBriefStrip(d) {
  const host = document.getElementById('briefChips');
  if(!host || !d) return;
  const chips = [];
  const chip = (onclick, lbl, valHtml, title, aria) =>
    chips.push(`<button type="button" class="brief-chip u-touch-hit" onclick="${onclick}" title="${escapeHtml(title || '')}" aria-label="${escapeHtml(aria || title || lbl)}"><span class="brief-lbl">${lbl}</span>${valHtml}</button>`);
  // 데이터 신선도 칩 — 사이드바가 오프캔버스인 모바일에서도 "이 숫자가 언제 것인지" 노출
  try {
    const ts = window._lastServerDataTs || d.lastUpdated || window._lastRealDataTs;
    if(ts) {
      const ageH = (Date.now() - new Date(ts).getTime()) / 36e5;
      if(isFinite(ageH) && ageH >= 0) {
        const dot = ageH <= 2 ? 'var(--ind-pos)' : ageH <= 26 ? 'var(--c-warn)' : 'var(--ind-neg)';
        const rel = ageH < 1 ? Math.max(1, Math.round(ageH * 60)) + '분 전' : ageH < 48 ? Math.round(ageH) + '시간 전' : Math.round(ageH / 24) + '일 전';
        chips.push(`<span class="brief-chip" title="${escapeHtml('서버 데이터 기준: ' + new Date(ts).toLocaleString('ko-KR') + ' · 시세 최대 15분 지연')}" aria-label="데이터 ${rel} 갱신"><span aria-hidden="true" style="width:6px;height:6px;border-radius:50%;background:${dot};display:inline-block;flex-shrink:0;"></span><span class="brief-lbl">데이터</span><span class="brief-val" style="font-weight:var(--font-weight-medium);">${ageH > 26 ? '⚠ ' : ''}${rel}</span></span>`);
      }
    }
  } catch(_) {}
  const idx = d.indices || {}, fx = d.fx || {}, sent = d.sentiment || {};
  const k = idx.KOSPI;
  if(k && k.price != null) chip("navigateToDetail('equity')", 'KOSPI',
    `<span class="brief-val">${_bsNum(k.price)}</span>${_bsChgHtml(k.change)}`,
    'KOSPI — 클릭: 주식시장 상세', `KOSPI ${_bsNum(k.price)}, 등락 ${_bsNum(k.change)}%`);
  const u = fx.USDKRW;
  if(u && u.rate != null) chip("navigateToDetail('fx')", 'USD/KRW',
    `<span class="brief-val">${_bsNum(u.rate)}</span>${_bsChgHtml(u.change)}`,
    '원/달러 환율 — 클릭: 환율 상세', `원 달러 환율 ${_bsNum(u.rate)}원, 등락 ${_bsNum(u.change)}%`);
  const s = idx.SP500;
  if(s && s.price != null) chip("navigateToDetail('equity')", 'S&P500',
    `<span class="brief-val">${_bsNum(s.price)}</span>${_bsChgHtml(s.change)}`,
    'S&P 500 — 클릭: 주식시장 상세', `S&P500 ${_bsNum(s.price)}, 등락 ${_bsNum(s.change)}%`);
  const fg = sent.fear_greed;
  if(fg && fg.value != null) chip("showSentimentDetail('fear_greed')", '공포탐욕',
    `<span class="brief-val">${_bsNum(fg.value, 0)}</span><span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">${escapeHtml(String(fg.rating || ''))}</span>`,
    'CNN Fear & Greed — 클릭: 상세', `공포탐욕지수 ${_bsNum(fg.value, 0)} ${String(fg.rating || '')}`);
  try {
    const daily = (d.investorTrading || {}).daily || [];
    const last = daily[daily.length - 1];
    if(last && last.foreign != null) {
      const f = +last.foreign;
      const fmt = Math.abs(f) >= 10000 ? (f / 10000).toFixed(1) + '조' : _bsNum(f, 0) + '억';
      chip("showPage('investor', menuItemFor('investor'))", '외국인',
        `<span class="brief-val ${f >= 0 ? 'up-txt' : 'down-txt'}">${f >= 0 ? '+' : ''}${fmt}</span>`,
        `외국인 KOSPI 순매매 ${last.date || ''} (원) — 클릭: 주요 투자자`, `외국인 순매매 ${f >= 0 ? '순매수' : '순매도'} ${fmt}원`);
    }
  } catch(_) {}
  const nx = _bsNextEvent();
  if(nx) {
    const dLeft = Math.max(0, Math.round((new Date(nx.ms).setHours(0,0,0,0) - new Date().setHours(0,0,0,0)) / 86400000));
    const dTxt = dLeft === 0 ? '오늘' : dLeft === 1 ? '내일' : `D-${dLeft}`;
    chip("showPage('calendar', menuItemFor('calendar'))", '다음 일정',
      `<span class="brief-val" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(`${nx.e.flag || ''} ${dTxt} · ${nx.e.name}`)}</span>`,
      `${nx.e.dt} ${nx.e.name} ${'★'.repeat(nx.e.stars || 0)} — 클릭: 경제 캘린더`, `다음 경제 일정: ${dTxt} ${nx.e.name}`);
  }
  if(chips.length) host.innerHTML = chips.join('');
}

// ── 📐 KPI 5년 백분위 배지 — 현재 값이 최근 5년 일별 분포에서 차지하는 위치 ──
function renderKpiPctBadges(d) {
  if(!d || !d.history) return;
  const defs = [
    { card: 'kpi-kospi', hist: (d.history.indices || {}).KOSPI, cur: d.indices && d.indices.KOSPI && d.indices.KOSPI.price },
    { card: 'kpi-fx',    hist: (d.history.fx || {}).USDKRW,     cur: d.fx && d.fx.USDKRW && d.fx.USDKRW.rate },
    { card: 'kpi-wti',   hist: (d.history.commodities || {}).WTI, cur: d.commodities && d.commodities.WTI && d.commodities.WTI.price },
  ];
  defs.forEach(def => {
    try {
      const arr = (def.hist || []).map(p => +p.close).filter(Number.isFinite);
      if(arr.length < 250 || def.cur == null || !Number.isFinite(+def.cur)) return;
      const pct = Math.round(_pctRank(arr, +def.cur));
      const title = document.querySelector(`#${def.card} .widget-title`);
      if(!title) return;
      let badge = title.querySelector('.kpi-pct-badge');
      if(!badge) { badge = document.createElement('span'); badge.className = 'kpi-pct-badge'; title.appendChild(badge); }
      badge.textContent = `5Y ${pct}%`;
      const yrs = Math.round(arr.length / 252 * 10) / 10;
      badge.title = `최근 ${yrs}년 일별 분포에서 현재 값의 백분위 ${pct}% — 100%에 가까울수록 5년 내 고점권`;
    } catch(_) {}
  });
}

// ── 💬 AI 브리핑 대화형 질문 — Worker /ai question 모드 (동기화 키 보유 기기 전용) ──
let _aiQaBusy = false, _aiQaLastTs = 0;

function updateAiQaVisibility() {
  const box = document.getElementById('aiQaBox');
  if(!box) return;
  let has = '';
  try { has = localStorage.getItem('pfSyncKeyHash') || localStorage.getItem('pfSyncKey') || ''; } catch(_) {}
  box.style.display = has ? 'block' : 'none';
}

// 당일 시장 컨텍스트 스냅샷 — scripts/ai_briefing.py build_snapshot 과 동일 구성 원칙:
// 값 없는 키는 아예 생략(환각 억제), 외부 텍스트(뉴스 제목·종목명)는 백틱/제어문자 제거 + 길이 캡.
function buildQaSnapshot() {
  const d = (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators) ? _latestDataForIndicators : {};
  const clean = s => String(s == null ? '' : s).replace(/[`\u0000-\u001f]/g, ' ').slice(0, 120);
  const px = o => (o && o.price != null) ? { price: +o.price, change: o.change != null ? +o.change : undefined } : undefined;
  const snap = { asOf: d.lastUpdated };
  const b = d.aiBriefing;
  if(b && Array.isArray(b.lines) && b.lines.length) snap.briefing = b.lines.map(clean);
  const idx = d.indices || {};
  const idxOut = {};
  ['KOSPI','KOSDAQ','SP500','NASDAQ','Nikkei','SOX'].forEach(kk => { const v = px(idx[kk]); if(v) idxOut[kk] = v; });
  if(Object.keys(idxOut).length) snap.indices = idxOut;
  const u = (d.fx || {}).USDKRW;
  if(u && u.rate != null) snap.fx = { USDKRW: { rate: +u.rate, change: u.change != null ? +u.change : undefined } };
  const com = d.commodities || {};
  const comOut = {};
  ['WTI','Gold'].forEach(kk => { const v = px(com[kk]); if(v) comOut[kk] = v; });
  if(Object.keys(comOut).length) snap.commodities = comOut;
  const eiUs = (d.economicIndicators || {}).us || {}, eiKr = (d.economicIndicators || {}).kr || {};
  const rates = {};
  if(eiUs.ff_rate && eiUs.ff_rate.value != null) rates['미국기준금리'] = +eiUs.ff_rate.value;
  if(eiKr.base_rate_kr && eiKr.base_rate_kr.value != null) rates['한국기준금리'] = +eiKr.base_rate_kr.value;
  if(eiUs.vix && eiUs.vix.value != null) rates['VIX'] = +eiUs.vix.value;
  if(eiUs.hy_spread && eiUs.hy_spread.value != null) rates['하이일드스프레드'] = +eiUs.hy_spread.value;
  if(eiUs.us10y && eiUs.us10y.value != null) rates['미국채10년'] = +eiUs.us10y.value;
  if(Object.keys(rates).length) snap.rates = rates;
  const fg = (d.sentiment || {}).fear_greed;
  if(fg && fg.value != null) snap.sentiment = { 공포탐욕: +fg.value, 등급: clean(fg.rating), 전일: fg.prev != null ? +fg.prev : undefined };
  try {
    const daily = (d.investorTrading || {}).daily || [];
    if(daily.length) snap['외국인순매매_최근5일_억원'] = daily.slice(-5).reduce((a, r) => a + (+r.foreign || 0), 0);
  } catch(_) {}
  try {
    const mv = d.stockMovers || {};
    const top3 = arr => (arr || []).slice(0, 3).map(m => ({ name: clean(m.name), chg: m.chg != null ? +m.chg : undefined }));
    const up3 = top3(mv.kospiGainers), dn3 = top3(mv.kospiLosers);
    if(up3.length || dn3.length) snap.movers = { 상승: up3, 하락: dn3 };
  } catch(_) {}
  try {
    const all = [];
    Object.values(d.news || {}).forEach(list => { if(Array.isArray(list)) list.forEach(a => { if(a && a.title) all.push(a); }); });
    all.sort((a, b) => String(b.isoDate || '').localeCompare(String(a.isoDate || '')));
    if(all.length) snap.news = all.slice(0, 8).map(a => clean(a.title));
  } catch(_) {}
  try {
    const evs = ((d.economicCalendar || {}).events || []);
    const today = new Date(); const lo = new Date(today.getTime() - 7 * 86400000), hi = new Date(today.getTime() + 3 * 86400000);
    const sel = evs.filter(e => e && e.iso && (e.stars || 0) >= 2 && new Date(e.iso) >= lo && new Date(e.iso) <= hi)
      .slice(0, 10).map(e => ({ name: clean(e.name), iso: e.iso, stars: e.stars, 예상: clean(e.fore), 실제: clean(e.act), 이전: clean(e.prev) }));
    if(sel.length) snap.calendar = sel;
  } catch(_) {}
  if(_riskLast && _riskLast.score != null) snap['리스크점수_0안정_100위험'] = _riskLast.score;
  return JSON.parse(JSON.stringify(snap));   // undefined 필드 제거
}

async function aiQaAsk() {
  const input = document.getElementById('aiQaInput'), btn = document.getElementById('aiQaSendBtn'),
        out = document.getElementById('aiQaAnswer'), meta = document.getElementById('aiQaMeta');
  if(!input || !out || _aiQaBusy) return;
  const q = (input.value || '').trim();
  if(!q) { input.focus(); return; }
  const now = Date.now();
  if(now - _aiQaLastTs < 6000) {   // /ai 는 /portfolio 저장과 분당 10회 IP 레이트리밋을 공유 — 과소비 방지
    if(meta) meta.textContent = '⏳ 전송 간격 6초 — 잠시 후 질문해 주세요 · ※ 투자 조언이 아닙니다';
    return;
  }
  const keyHash = await pfGetSyncKeyHash();
  if(!keyHash) {
    out.style.display = 'block';
    out.textContent = '🔑 동기화 키가 필요합니다 — 투자 현황 페이지의 [🔑 동기화 키] 버튼으로 등록하세요.';
    return;
  }
  _aiQaBusy = true; _aiQaLastTs = now;
  btn.disabled = true; input.disabled = true;
  const prevTxt = btn.textContent; btn.textContent = '⟳';
  out.style.display = 'block'; out.textContent = '⟳ 답변 생성 중…';
  try {
    const r = await fetch(_cfProxyBase() + '/ai', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ keyHash, question: q.slice(0, 300), snapshot: buildQaSnapshot() }),
      signal: AbortSignal.timeout(30000),
    });
    const j = await r.json().catch(() => ({}));
    if(r.ok && j && j.ok && j.summary) {
      let a = String(j.summary).trim();
      if(!/투자\s*조언이?\s*아닙니다/.test(a)) a += '\n※ 투자 조언이 아닙니다';
      out.textContent = a;
      if(meta) meta.textContent = `엔진 ${j.engine || 'AI'}${j.model ? ' · ' + j.model : ''} · ※ AI 답변은 참고용이며 투자 조언이 아닙니다`;
    } else {
      const code = j && j.error;
      const msgMap = {
        rate_limited: '요청이 많습니다 — 1분 후 질문해 주세요.',
        unauthorized: '동기화 키가 서버와 일치하지 않습니다 — 키를 확인하세요.',
        sync_key_not_configured: 'Worker 에 ALERTS_SYNC_KEY 시크릿이 설정되지 않아 사용할 수 없습니다.',
        no_ai_available: 'Worker 에 AI 엔진(GEMINI_API_KEY 등)이 설정되지 않았습니다.',
        forbidden_origin: '이 도메인에서는 사용할 수 없습니다 (GitHub Pages 원본에서 이용).',
      };
      out.textContent = '⚠ ' + (msgMap[code] || '일시적으로 사용할 수 없습니다 — 잠시 후 질문해 주세요.');
    }
  } catch(_) {
    out.textContent = '⚠ 네트워크 오류 — 잠시 후 질문해 주세요.';
  } finally {
    _aiQaBusy = false;
    btn.disabled = false; input.disabled = false; btn.textContent = prevTxt;
    input.focus();
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// 📚 스터디 기록 (page-study)
//   설계: 메타데이터(제목·참석자·회의록·액션아이템)는 localStorage,
//         업로드 파일(영상·음성·문서) 실체는 IndexedDB blob 으로 분리 저장한다.
//         localStorage 는 5MB 한도라 미디어를 담을 수 없고, IndexedDB 는 수 GB 까지
//         가능하지만 JSON 직렬화가 번거로워 메타만 LS 에 두는 하이브리드 구조.
//   외부 전송 없음 — 모든 파일은 이 브라우저에만 남는다(내보내기로 이관).
// ═══════════════════════════════════════════════════════════════════════════
const STUDY_LS_KEY  = 'econ_study_v1';
const STUDY_DB_NAME = 'econStudyDB';
const STUDY_DB_STORE = 'files';
const STUDY_FILE_WARN = 300 * 1024 * 1024;   // 단일 파일 300MB 초과 시 경고(브라우저 쿼터 보호)

var _styState = {
  year: 0, month: 0,        // 캘린더가 보고 있는 연/월
  selDate: '',              // 선택된 날짜 YYYY-MM-DD
  curId: '',                // 열려 있는 세션 id
  objUrl: '',               // 재생 중 blob URL (해제 대상)
  playFid: '',              // 재생 중 파일 id
  saveTimer: null, pending: null,          // 필드 편집 디바운스 — 여러 필드를 한 패치로 병합
  actionTimer: null, pendingActions: null, // 액션아이템 편집 디바운스 (필드와 분리)
  inited: false,
};

/* ── 날짜 유틸 (KST 기준) ── */
function _styTodayStr() {
  try { return new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10); }
  catch(_) { return new Date().toISOString().slice(0, 10); }
}
function _styUid(p) { return (p || 'x') + Date.now().toString(36) + Math.random().toString(36).slice(2, 7); }
function _styFmtSize(b) {
  if(b == null) return '';
  if(b < 1024) return b + ' B';
  if(b < 1048576) return (b / 1024).toFixed(0) + ' KB';
  if(b < 1073741824) return (b / 1048576).toFixed(1) + ' MB';
  return (b / 1073741824).toFixed(2) + ' GB';
}
function _styKind(type, name) {
  const t = String(type || '').toLowerCase(), n = String(name || '').toLowerCase();
  if(t.startsWith('video/') || /\.(mp4|webm|mov|mkv|avi)$/.test(n)) return 'video';
  if(t.startsWith('audio/') || /\.(mp3|m4a|wav|ogg|aac|flac)$/.test(n)) return 'audio';
  if(t.startsWith('image/') || /\.(png|jpe?g|gif|webp|svg|bmp)$/.test(n)) return 'image';
  return 'doc';
}
function _styKindIcon(k) { return k === 'video' ? '🎬' : k === 'audio' ? '🎧' : k === 'image' ? '🖼' : '📄'; }

/* ── IndexedDB (파일 blob) ───────────────────────────────────────────────── */
function _styIdb() {
  return new Promise(function(resolve, reject) {
    let req;
    try { req = indexedDB.open(STUDY_DB_NAME, 1); }
    catch(e) { reject(e); return; }
    req.onupgradeneeded = function() {
      const db = req.result;
      if(!db.objectStoreNames.contains(STUDY_DB_STORE)) {
        const os = db.createObjectStore(STUDY_DB_STORE, { keyPath: 'fid' });
        os.createIndex('sessionId', 'sessionId', { unique: false });
      }
    };
    req.onsuccess = function() { resolve(req.result); };
    req.onerror = function() { reject(req.error); };
  });
}
function _styIdbTx(mode, fn) {
  return _styIdb().then(function(db) {
    return new Promise(function(resolve, reject) {
      const tx = db.transaction(STUDY_DB_STORE, mode);
      const store = tx.objectStore(STUDY_DB_STORE);
      let out;
      try { out = fn(store); } catch(e) { reject(e); return; }
      // IDBRequest 는 결과를 result 로 돌려준다. 없는 키의 get 은 result === undefined 이므로
      // '값이 없음'을 undefined 로 정확히 전달해야 한다 — 예전엔 이때 request 객체 자체를
      // 돌려줘서 호출부의 `if(rec)` 가 항상 참이 되는 함정이 있었다.
      tx.oncomplete = function() { db.close(); resolve((out instanceof IDBRequest) ? out.result : out); };
      tx.onerror = function() { db.close(); reject(tx.error); };
      tx.onabort = function() { db.close(); reject(tx.error); };
    });
  });
}
function styIdbPut(rec)  { return _styIdbTx('readwrite', function(s) { return s.put(rec); }); }
function styIdbGet(fid)  { return _styIdbTx('readonly',  function(s) { return s.get(fid); }); }
function styIdbDel(fid)  { return _styIdbTx('readwrite', function(s) { return s.delete(fid); }); }

/* ── 저장소 (메타) ───────────────────────────────────────────────────────── */
function styLoad() {
  try {
    const raw = localStorage.getItem(STUDY_LS_KEY);
    if(!raw) return { v: 1, sessions: [] };
    const o = JSON.parse(raw);
    if(!o || !Array.isArray(o.sessions)) return { v: 1, sessions: [] };
    return o;
  } catch(_) { return { v: 1, sessions: [] }; }
}
function stySave(store, quiet) {
  try {
    localStorage.setItem(STUDY_LS_KEY, JSON.stringify(store));
    if(!quiet) _stySaveState('저장됨 · ' + new Date().toLocaleTimeString('ko-KR'));
    return true;
  } catch(e) {
    _stySaveState('⚠ 저장 실패 — 브라우저 저장 공간이 부족할 수 있습니다');
    if(typeof showToast === 'function') showToast('스터디 기록 저장 실패 — 저장 공간을 확인하세요.');
    return false;
  }
}
function _stySaveState(msg) {
  const el = document.getElementById('stySaveState');
  if(el) el.textContent = msg;
}
function styCur() {
  if(!_styState.curId) return null;
  return styLoad().sessions.find(function(s) { return s.id === _styState.curId; }) || null;
}
function styUpdate(id, patch, quiet) {
  const store = styLoad();
  const i = store.sessions.findIndex(function(s) { return s.id === id; });
  if(i < 0) return null;
  Object.assign(store.sessions[i], patch, { updatedAt: Date.now() });
  stySave(store, quiet);
  return store.sessions[i];
}

/* ── 렌더: 캘린더 ────────────────────────────────────────────────────────── */
function styRenderCalendar() {
  const grid = document.getElementById('styCalGrid'), title = document.getElementById('styCalTitle');
  if(!grid) return;
  const y = _styState.year, m = _styState.month;
  if(title) title.textContent = y + '년 ' + m + '월';

  const sessions = styLoad().sessions;
  const byDate = {};
  sessions.forEach(function(s) { if(s.date) byDate[s.date] = (byDate[s.date] || 0) + 1; });

  const first = new Date(y, m - 1, 1).getDay();
  const days = new Date(y, m, 0).getDate();
  const today = _styTodayStr();

  let html = ['일','월','화','수','목','금','토'].map(function(d, i) {
    const c = i === 0 ? 'var(--c-down)' : i === 6 ? 'var(--c-accent)' : 'var(--c-txt-muted)';
    return '<div class="study-dow" style="color:' + c + '">' + d + '</div>';
  }).join('');
  for(let i = 0; i < first; i++) html += '<div class="study-day is-empty" aria-hidden="true"></div>';
  for(let d = 1; d <= days; d++) {
    const ds = y + '-' + String(m).padStart(2, '0') + '-' + String(d).padStart(2, '0');
    const n = byDate[ds] || 0;
    const cls = ['study-day'];
    if(ds === today) cls.push('is-today');
    if(ds === _styState.selDate) cls.push('is-selected');
    if(n) cls.push('has-log');
    html += '<div class="' + cls.join(' ') + '" role="gridcell" tabindex="0"' +
            ' onclick="stySelectDate(\'' + ds + '\')"' +
            ' onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();this.click();}"' +
            ' aria-label="' + ds + (n ? (' 스터디 ' + n + '건') : '') + '" title="' + ds + (n ? (' · ' + n + '건') : '') + '">' +
            '<span class="study-daynum">' + d + '</span></div>';
  }
  grid.innerHTML = html;
}

/* ── 렌더: 통계 ──────────────────────────────────────────────────────────── */
function styRenderStats() {
  const el = document.getElementById('styStats');
  if(!el) return;
  const ss = styLoad().sessions;
  let mins = 0, openActions = 0;
  ss.forEach(function(s) {
    if(s.start && s.end) {
      const a = s.start.split(':'), b = s.end.split(':');
      const d = (+b[0] * 60 + +b[1]) - (+a[0] * 60 + +a[1]);
      if(d > 0) mins += d;
    }
    (s.actions || []).forEach(function(x) { if(!x.done) openActions++; });
  });
  // 연속 주차 — 이번 주부터 거슬러 올라가며 스터디가 있는 주가 몇 주 이어지는지
  const weekKeys = {};
  ss.forEach(function(s) {
    if(!s.date) return;
    const dt = new Date(s.date + 'T00:00:00');
    if(isNaN(dt)) return;
    const th = new Date(dt); th.setDate(th.getDate() - ((th.getDay() + 6) % 7));   // 월요일 기준
    weekKeys[th.toISOString().slice(0, 10)] = 1;
  });
  let streak = 0;
  const cur = new Date(_styTodayStr() + 'T00:00:00');
  cur.setDate(cur.getDate() - ((cur.getDay() + 6) % 7));
  while(weekKeys[cur.toISOString().slice(0, 10)]) { streak++; cur.setDate(cur.getDate() - 7); }

  const chips = [
    ['총 ' + ss.length + '회', ''],
    ['누적 ' + (mins >= 60 ? (mins / 60).toFixed(1) + 'h' : mins + '분'), ''],
    ['연속 ' + streak + '주', ''],
  ];
  if(openActions) chips.push(['미완료 액션 ' + openActions, 'warn']);
  el.innerHTML = chips.map(function(c) {
    const st = c[1] === 'warn' ? ' style="background:color-mix(in srgb,var(--c-warn) 22%,transparent);color:var(--c-warn);"' : '';
    return '<span class="study-badge"' + st + '>' + escapeHtml(c[0]) + '</span>';
  }).join('');
}

/* ── 렌더: 목록 ──────────────────────────────────────────────────────────── */
function styRenderList() {
  const el = document.getElementById('styList');
  if(!el) return;
  const q = ((document.getElementById('stySearch') || {}).value || '').trim().toLowerCase();
  let ss = styLoad().sessions.slice().sort(function(a, b) { return String(b.date).localeCompare(String(a.date)); });
  if(q) {
    ss = ss.filter(function(s) {
      const hay = [s.title, s.place, s.notes, (s.tags || []).join(' '), (s.members || []).join(' '), s.date].join(' ').toLowerCase();
      return hay.indexOf(q) >= 0;
    });
  }
  if(!ss.length) {
    el.innerHTML = '<div class="study-empty" style="padding:12px;">' + (q ? '검색 결과가 없습니다.' : '아직 기록이 없습니다.') + '</div>';
    return;
  }
  el.innerHTML = ss.map(function(s) {
    const nFile = (s.files || []).length + (s.links || []).length;
    const open = (s.actions || []).filter(function(a) { return !a.done; }).length;
    return '<div class="study-list-item' + (s.id === _styState.curId ? ' active' : '') + '"' +
      ' role="button" tabindex="0" onclick="styOpen(\'' + s.id + '\')"' +
      ' onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();this.click();}">' +
      '<div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-semibold);color:var(--c-txt);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' +
        escapeHtml(s.title || '(제목 없음)') + '</div>' +
      '<div style="display:flex;gap:5px;flex-wrap:wrap;align-items:center;">' +
        '<span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">' + escapeHtml(s.date || '') + '</span>' +
        (nFile ? '<span class="study-badge">📎 ' + nFile + '</span>' : '') +
        (open ? '<span class="study-badge" style="background:color-mix(in srgb,var(--c-warn) 22%,transparent);color:var(--c-warn);">☐ ' + open + '</span>' : '') +
        (s.tags || []).slice(0, 2).map(function(t) { return '<span class="study-badge">#' + escapeHtml(t) + '</span>'; }).join('') +
      '</div></div>';
  }).join('');
}

/* ── 렌더: 상세 ──────────────────────────────────────────────────────────── */
function styRenderDetail() {
  const empty = document.getElementById('styEmpty'), body = document.getElementById('styBody');
  const s = styCur();
  if(!s) {
    if(empty) empty.style.display = '';
    if(body) body.style.display = 'none';
    return;
  }
  if(empty) empty.style.display = 'none';
  if(body) body.style.display = 'flex';

  const all = styLoad().sessions.slice().sort(function(a, b) { return String(a.date).localeCompare(String(b.date)); });
  const round = all.findIndex(function(x) { return x.id === s.id; }) + 1;
  const rb = document.getElementById('styRoundBadge');
  if(rb) rb.textContent = round > 0 ? (round + '회차') : '—';

  const setv = function(id, v) { const e = document.getElementById(id); if(e && e.value !== v) e.value = v; };
  setv('styTitle', s.title || '');
  setv('styDate', s.date || '');
  setv('styStart', s.start || '');
  setv('styEnd', s.end || '');
  setv('styPlace', s.place || '');
  setv('styMembers', (s.members || []).join(', '));
  setv('styTags', (s.tags || []).join(', '));
  setv('styNotes', s.notes || '');

  styRenderFiles();
  styRenderActions();
  if(((document.getElementById('styNotesView') || {}).style || {}).display !== 'none') styNoteTab('view');
}

function styRenderFiles() {
  const el = document.getElementById('styFileList');
  const s = styCur();
  if(!el || !s) return;
  const files = s.files || [], links = s.links || [];
  if(!files.length && !links.length) {
    el.innerHTML = '<div class="study-empty" style="padding:10px;">등록된 자료가 없습니다.</div>';
    return;
  }
  let html = files.map(function(f) {
    const playable = f.kind === 'video' || f.kind === 'audio';
    return '<div class="study-file' + (_styState.playFid === f.fid ? ' playing' : '') + '">' +
      '<span aria-hidden="true">' + _styKindIcon(f.kind) + '</span>' +
      '<span class="study-file-name" title="' + escapeHtml(f.name) + '">' + escapeHtml(f.name) + '</span>' +
      '<span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);white-space:nowrap;">' + _styFmtSize(f.size) + '</span>' +
      (playable ? '<button class="study-btn" onclick="styPlayFile(\'' + f.fid + '\')" title="재생">▶</button>' : '') +
      (f.kind === 'image' ? '<button class="study-btn" onclick="styPreviewImage(\'' + f.fid + '\')" title="미리보기">👁</button>' : '') +
      '<button class="study-btn" onclick="styDownloadFile(\'' + f.fid + '\')" title="다운로드">↓</button>' +
      '<button class="study-btn danger" onclick="styRemoveFile(\'' + f.fid + '\')" title="삭제">×</button>' +
      '</div>';
  }).join('');
  html += links.map(function(l) {
    return '<div class="study-file">' +
      '<span aria-hidden="true">🔗</span>' +
      '<a class="study-file-name" href="' + escapeHtml(l.url) + '" target="_blank" rel="noopener noreferrer"' +
      ' title="' + escapeHtml(l.url) + '" style="color:var(--c-accent);">' + escapeHtml(l.label || l.url) + '</a>' +
      '<button class="study-btn danger" onclick="styRemoveLink(\'' + l.lid + '\')" title="삭제">×</button>' +
      '</div>';
  }).join('');
  el.innerHTML = html;
}

function styRenderActions() {
  const el = document.getElementById('styActions');
  const s = styCur();
  if(!el || !s) return;
  const acts = s.actions || [];
  if(!acts.length) {
    el.innerHTML = '<div class="study-empty" style="padding:10px;">액션 아이템이 없습니다. 다음 스터디까지 할 일을 적어두세요.</div>';
    return;
  }
  el.innerHTML = acts.map(function(a) {
    return '<div class="study-action-row' + (a.done ? ' done' : '') + '">' +
      '<input type="checkbox" ' + (a.done ? 'checked' : '') + ' onchange="styToggleAction(\'' + a.aid + '\',this.checked)"' +
      ' aria-label="완료 표시" style="margin-top:6px;"/>' +
      '<input class="study-field study-action-text" style="flex:2;min-width:120px;" value="' + escapeHtml(a.text || '') + '"' +
      ' placeholder="할 일" oninput="styPatchAction(\'' + a.aid + '\',\'text\',this.value)"/>' +
      '<input class="study-field" style="width:88px;" value="' + escapeHtml(a.owner || '') + '"' +
      ' placeholder="담당" oninput="styPatchAction(\'' + a.aid + '\',\'owner\',this.value)"/>' +
      '<input class="study-field" style="width:132px;" type="date" value="' + escapeHtml(a.due || '') + '"' +
      ' onchange="styPatchAction(\'' + a.aid + '\',\'due\',this.value)" aria-label="기한"/>' +
      '<button class="study-btn danger" onclick="styDelAction(\'' + a.aid + '\')" title="삭제">×</button>' +
      '</div>';
  }).join('');
}

function styRenderQuota() {
  const el = document.getElementById('styQuota');
  if(!el) return;
  const nFiles = styLoad().sessions.reduce(function(n, s) { return n + (s.files || []).length; }, 0);
  if(navigator.storage && navigator.storage.estimate) {
    navigator.storage.estimate().then(function(e) {
      const used = _styFmtSize(e.usage || 0), quota = _styFmtSize(e.quota || 0);
      el.textContent = '업로드 파일 ' + nFiles + '개 · 사용 ' + used + ' / 가용 ' + quota;
    }).catch(function() { el.textContent = '업로드 파일 ' + nFiles + '개'; });
  } else {
    el.textContent = '업로드 파일 ' + nFiles + '개';
  }
}

function styRenderAll() { styRenderCalendar(); styRenderStats(); styRenderList(); styRenderDetail(); styRenderQuota(); }

/* ── 캘린더 조작 ─────────────────────────────────────────────────────────── */
function styMonthMove(d) {
  _styState.month += d;
  if(_styState.month < 1) { _styState.month = 12; _styState.year--; }
  if(_styState.month > 12) { _styState.month = 1; _styState.year++; }
  styRenderCalendar();
}
function styMonthToday() {
  const t = _styTodayStr();
  _styState.year = +t.slice(0, 4); _styState.month = +t.slice(5, 7);
  _styState.selDate = t;
  styRenderCalendar();
}
function stySelectDate(ds) {
  styFlushAll();
  _styState.selDate = ds;
  // 그 날짜의 기록이 있으면 바로 연다 (없으면 선택만)
  const hit = styLoad().sessions.filter(function(s) { return s.date === ds; })
    .sort(function(a, b) { return (a.start || '').localeCompare(b.start || ''); })[0];
  if(hit) { styOpen(hit.id); return; }
  styRenderCalendar(); styRenderList();
}

/* ── 세션 CRUD ───────────────────────────────────────────────────────────── */
function styCreateForSelected() {
  styFlushAll();
  const date = _styState.selDate || _styTodayStr();
  const store = styLoad();
  const s = {
    id: _styUid('s'), date: date, title: '', start: '', end: '', place: '',
    members: [], tags: [], files: [], links: [], notes: '', actions: [],
    createdAt: Date.now(), updatedAt: Date.now(),
  };
  store.sessions.push(s);
  if(!stySave(store)) return;
  _styState.curId = s.id;
  styRenderAll();
  const t = document.getElementById('styTitle'); if(t) t.focus();
  if(typeof showToast === 'function') showToast(date + ' 스터디 기록을 만들었습니다.', 2500);
}
function styOpen(id) {
  styFlushAll();          // 편집 중이던 내용을 잃지 않도록 먼저 확정
  styClosePlayer();
  _styState.curId = id;
  const s = styCur();
  if(s && s.date) {
    _styState.selDate = s.date;
    _styState.year = +s.date.slice(0, 4); _styState.month = +s.date.slice(5, 7);
  }
  styRenderAll();
}
function styDelete() {
  styFlushAll();
  const s = styCur();
  if(!s) return;
  if(!confirm('이 스터디 기록과 업로드한 파일을 모두 삭제합니다. 되돌릴 수 없습니다.\n\n' + (s.title || '(제목 없음)') + ' · ' + (s.date || ''))) return;
  const fids = (s.files || []).map(function(f) { return f.fid; });
  Promise.all(fids.map(function(fid) { return styIdbDel(fid).catch(function() {}); })).then(function() {
    const store = styLoad();
    store.sessions = store.sessions.filter(function(x) { return x.id !== s.id; });
    stySave(store, true);
    styClosePlayer();
    _styState.curId = '';
    styRenderAll();
    if(typeof showToast === 'function') showToast('삭제했습니다.', 2000);
  });
}
function styDuplicate() {
  styFlushAll();
  const s = styCur();
  if(!s) return;
  const store = styLoad();
  const c = JSON.parse(JSON.stringify(s));
  c.id = _styUid('s');
  c.title = (s.title || '(제목 없음)') + ' (복제)';
  c.date = _styState.selDate || _styTodayStr();
  c.files = [];                       // 파일 blob 은 공유하지 않는다 (중복 저장 방지)
  c.actions = (c.actions || []).map(function(a) { return Object.assign({}, a, { aid: _styUid('a'), done: false }); });
  c.createdAt = c.updatedAt = Date.now();
  store.sessions.push(c);
  stySave(store);
  _styState.curId = c.id;
  styRenderAll();
  if(typeof showToast === 'function') showToast('복제했습니다 (업로드 파일 제외).', 2500);
}

/* ── 필드 편집 (디바운스 자동저장) ───────────────────────────────────────── */
//   여러 입력칸을 연달아 고칠 때 타이머 하나를 공유하면 마지막 필드만 저장되므로,
//   대기 중인 변경을 하나의 patch 로 병합했다가 한 번에 flush 한다.
function styPatchField(field, value) {
  const id = _styState.curId;
  if(!id) return;
  let v = value;
  if(field === 'members' || field === 'tags') {
    v = String(value).split(',').map(function(x) { return x.trim(); }).filter(Boolean);
  }
  if(!_styState.pending || _styState.pending.id !== id) _styState.pending = { id: id, patch: {} };
  _styState.pending.patch[field] = v;
  _stySaveState('입력 중…');
  clearTimeout(_styState.saveTimer);
  _styState.saveTimer = setTimeout(styFlushPatch, 500);
}
function styFlushPatch() {
  clearTimeout(_styState.saveTimer);
  const p = _styState.pending;
  if(!p) return;
  _styState.pending = null;
  const dateChanged = Object.prototype.hasOwnProperty.call(p.patch, 'date');
  styUpdate(p.id, p.patch);
  if(dateChanged) styOpen(p.id);
  else { styRenderList(); styRenderStats(); }
}
function styFlushAll() { styFlushPatch(); styFlushActions(); }

/* ── 파일 업로드 / 링크 ──────────────────────────────────────────────────── */
function styAddFiles(fileList) {
  styFlushAll();
  const s = styCur();
  if(!s) { if(typeof showToast === 'function') showToast('먼저 스터디 기록을 선택하거나 만들어 주세요.'); return; }
  const arr = Array.from(fileList || []);
  if(!arr.length) return;
  const big = arr.filter(function(f) { return f.size > STUDY_FILE_WARN; });
  if(big.length && !confirm('300MB 가 넘는 파일이 ' + big.length + '개 있습니다. 브라우저 저장 공간을 많이 쓰고 느려질 수 있습니다. 계속할까요?')) return;

  let done = 0;
  const metas = [];
  Promise.all(arr.map(function(f) {
    const rec = { fid: _styUid('f'), sessionId: s.id, name: f.name, type: f.type || '', size: f.size, blob: f };
    return styIdbPut(rec).then(function() {
      done++;
      metas.push({ fid: rec.fid, name: rec.name, type: rec.type, size: rec.size, kind: _styKind(rec.type, rec.name), addedAt: Date.now() });
    }).catch(function(e) {
      console.warn('study file save', e);
      if(typeof showToast === 'function') showToast('“' + f.name + '” 저장 실패 — 저장 공간이 부족할 수 있습니다.');
    });
  })).then(function() {
    if(!metas.length) return;
    const cur = styCur();
    styUpdate(s.id, { files: (cur.files || []).concat(metas) });
    styRenderFiles(); styRenderList(); styRenderQuota();
    if(typeof showToast === 'function') showToast(done + '개 파일을 저장했습니다 (이 브라우저에만 보관).', 2500);
  });
}
function styAddLink() {
  styFlushAll();
  const s = styCur();
  if(!s) { if(typeof showToast === 'function') showToast('먼저 스터디 기록을 선택하거나 만들어 주세요.'); return; }
  const uEl = document.getElementById('styLinkUrl'), lEl = document.getElementById('styLinkLabel');
  let url = ((uEl || {}).value || '').trim();
  if(!url) { if(uEl) uEl.focus(); return; }
  if(!/^https?:\/\//i.test(url)) url = 'https://' + url;
  try { new URL(url); } catch(_) { if(typeof showToast === 'function') showToast('올바른 URL 이 아닙니다.'); return; }
  const link = { lid: _styUid('l'), url: url, label: ((lEl || {}).value || '').trim(), addedAt: Date.now() };
  styUpdate(s.id, { links: (s.links || []).concat([link]) });
  if(uEl) uEl.value = ''; if(lEl) lEl.value = '';
  styRenderFiles(); styRenderList();
}
function styRemoveFile(fid) {
  const s = styCur();
  if(!s) return;
  const f = (s.files || []).find(function(x) { return x.fid === fid; });
  if(!confirm('“' + ((f && f.name) || '파일') + '” 을(를) 삭제합니다.')) return;
  if(_styState.playFid === fid) styClosePlayer();
  styIdbDel(fid).catch(function() {}).then(function() {
    const cur = styCur();
    styUpdate(s.id, { files: (cur.files || []).filter(function(x) { return x.fid !== fid; }) });
    styRenderFiles(); styRenderList(); styRenderQuota();
  });
}
function styRemoveLink(lid) {
  const s = styCur();
  if(!s) return;
  styUpdate(s.id, { links: (s.links || []).filter(function(x) { return x.lid !== lid; }) });
  styRenderFiles(); styRenderList();
}
function styDownloadFile(fid) {
  styIdbGet(fid).then(function(rec) {
    if(!rec || !rec.blob) { if(typeof showToast === 'function') showToast('파일을 찾을 수 없습니다.'); return; }
    const url = URL.createObjectURL(rec.blob);
    const a = document.createElement('a');
    a.href = url; a.download = rec.name || 'file';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function() { URL.revokeObjectURL(url); }, 4000);
  });
}
function styPreviewImage(fid) {
  styIdbGet(fid).then(function(rec) {
    if(!rec || !rec.blob) return;
    const url = URL.createObjectURL(rec.blob);
    if(typeof openInfoModal === 'function') {
      openInfoModal(rec.name || '이미지', _styFmtSize(rec.size),
        '<img src="' + url + '" alt="' + escapeHtml(rec.name || '') + '" style="max-width:100%;border-radius:var(--r-sm);"/>');
      setTimeout(function() { URL.revokeObjectURL(url); }, 60000);
    }
  });
}

/* ── 미디어 플레이어 + 타임스탬프 ────────────────────────────────────────── */
function _styMediaEl() {
  const v = document.getElementById('styVideo'), a = document.getElementById('styAudio');
  if(v && v.style.display !== 'none' && v.src) return v;
  if(a && a.style.display !== 'none' && a.src) return a;
  return null;
}
function styPlayFile(fid) {
  const s = styCur();
  if(!s) return;
  const meta = (s.files || []).find(function(x) { return x.fid === fid; });
  if(!meta) return;
  styIdbGet(fid).then(function(rec) {
    if(!rec || !rec.blob) { if(typeof showToast === 'function') showToast('파일을 찾을 수 없습니다.'); return; }
    styClosePlayer();
    const url = URL.createObjectURL(rec.blob);
    _styState.objUrl = url; _styState.playFid = fid;
    const wrap = document.getElementById('styPlayerWrap'),
          v = document.getElementById('styVideo'), a = document.getElementById('styAudio'),
          nm = document.getElementById('styPlayerName');
    if(nm) nm.textContent = _styKindIcon(meta.kind) + ' ' + meta.name;
    if(meta.kind === 'video') { v.src = url; v.style.display = ''; a.style.display = 'none'; a.removeAttribute('src'); }
    else { a.src = url; a.style.display = ''; v.style.display = 'none'; v.removeAttribute('src'); }
    if(wrap) wrap.style.display = '';
    stySetRate((document.getElementById('styRate') || {}).value || '1');
    styRenderFiles();
    const el = _styMediaEl(); if(el) el.play().catch(function() {});
  });
}
function styClosePlayer() {
  const v = document.getElementById('styVideo'), a = document.getElementById('styAudio'),
        wrap = document.getElementById('styPlayerWrap');
  try { if(v) { v.pause(); v.removeAttribute('src'); v.load(); v.style.display = 'none'; } } catch(_) {}
  try { if(a) { a.pause(); a.removeAttribute('src'); a.load(); a.style.display = 'none'; } } catch(_) {}
  if(wrap) wrap.style.display = 'none';
  if(_styState.objUrl) { try { URL.revokeObjectURL(_styState.objUrl); } catch(_) {} _styState.objUrl = ''; }
  _styState.playFid = '';
  styRenderFiles();
}
function stySetRate(r) { const el = _styMediaEl(); if(el) el.playbackRate = parseFloat(r) || 1; }
function _styFmtTs(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return (h ? h + ':' + String(m).padStart(2, '0') : String(m)) + ':' + String(s).padStart(2, '0');
}
function styStampNote() {
  const el = _styMediaEl();
  if(!el) { if(typeof showToast === 'function') showToast('먼저 녹화/녹음 파일을 재생하세요.'); return; }
  const ta = document.getElementById('styNotes');
  if(!ta) return;
  const stamp = '[' + _styFmtTs(el.currentTime) + '] ';
  const pos = ta.selectionStart != null ? ta.selectionStart : ta.value.length;
  const before = ta.value.slice(0, pos), after = ta.value.slice(pos);
  const nl = (before && !/\n$/.test(before)) ? '\n' : '';
  ta.value = before + nl + stamp + after;
  const np = (before + nl + stamp).length;
  ta.focus(); ta.setSelectionRange(np, np);
  styPatchField('notes', ta.value);
}
function stySeek(sec) {
  const el = _styMediaEl();
  if(!el) { if(typeof showToast === 'function') showToast('해당 녹화/녹음 파일을 먼저 재생하세요.'); return; }
  try { el.currentTime = +sec || 0; el.play().catch(function() {}); } catch(_) {}
}

/* ── 회의록 (마크다운 lite + 타임스탬프 링크) ────────────────────────────── */
const STUDY_TEMPLATE = [
  '# 안건',
  '- ',
  '',
  '# 핵심 논의',
  '- ',
  '',
  '# 결론',
  '- ',
  '',
  '# 다음 스터디',
  '- 일시: ',
  '- 준비물: ',
  '',
].join('\n');

function styInsertTemplate() {
  const ta = document.getElementById('styNotes');
  if(!ta) return;
  if(ta.value.trim() && !confirm('현재 작성 내용 위에 템플릿을 덧붙입니다. 계속할까요?')) return;
  ta.value = (ta.value.trim() ? ta.value.replace(/\s+$/, '') + '\n\n' : '') + STUDY_TEMPLATE;
  styPatchField('notes', ta.value);
  ta.focus();
}
function styNoteTab(mode) {
  const ta = document.getElementById('styNotes'), view = document.getElementById('styNotesView'),
        bw = document.getElementById('styTabWrite'), bv = document.getElementById('styTabView');
  if(!ta || !view) return;
  if(mode === 'view') {
    view.innerHTML = _styRenderNotes(ta.value);
    view.style.display = ''; ta.style.display = 'none';
    if(bw) bw.classList.remove('active'); if(bv) bv.classList.add('active');
  } else {
    view.style.display = 'none'; ta.style.display = '';
    if(bv) bv.classList.remove('active'); if(bw) bw.classList.add('active');
  }
}
function _styRenderNotes(txt) {
  const lines = String(txt || '').split('\n');
  let html = '', inList = false;
  const close = function() { if(inList) { html += '</ul>'; inList = false; } };
  lines.forEach(function(ln) {
    // AI/규칙 요약이 남기는 출처 태그 `<!-- … -->` — 원문(textarea·내보내기)에는 그대로 두고
    // 보기 탭에서만 배지로 렌더한다(주석 기호가 본문처럼 보이던 문제).
    const tag = /^\s*<!--\s*([\s\S]*?)\s*-->\s*$/.exec(ln);
    if(tag) {
      close();
      html += '<div style="margin:14px 0 6px;"><span class="study-badge" style="background:var(--c-card-hi);' +
              'color:var(--c-txt-muted);border:1px solid var(--c-border);">' + escapeHtml(tag[1]) + '</span></div>';
      return;
    }
    let e = escapeHtml(ln);
    // [mm:ss] / [h:mm:ss] → 클릭 시 해당 시점으로 이동
    e = e.replace(/\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]/g, function(_m, a, b, c) {
      const sec = c != null ? (+a * 3600 + (+b) * 60 + (+c)) : ((+a) * 60 + (+b));
      const lbl = c != null ? (a + ':' + b + ':' + c) : (a + ':' + b);
      return '<span class="study-ts" role="button" tabindex="0" onclick="stySeek(' + sec + ')"' +
             ' onkeydown="if(event.key===\'Enter\'){stySeek(' + sec + ');}" title="이 시점으로 이동">[' + lbl + ']</span>';
    });
    e = e.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
    if(/^#{2}\s+/.test(ln))      { close(); html += '<div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);margin:10px 0 4px;color:var(--c-txt-dim);">' + e.replace(/^##\s+/, '') + '</div>'; }
    else if(/^#\s+/.test(ln))    { close(); html += '<div style="font-size:var(--font-size-base);font-weight:var(--font-weight-bold);margin:14px 0 6px;color:var(--c-txt);border-left:3px solid var(--c-accent);padding-left:8px;">' + e.replace(/^#\s+/, '') + '</div>'; }
    else if(/^\s*[-•*]\s+/.test(ln)) { if(!inList) { html += '<ul style="margin:4px 0 4px 18px;padding:0;">'; inList = true; } html += '<li style="margin:2px 0;">' + e.replace(/^\s*[-•*]\s+/, '') + '</li>'; }
    else if(!ln.trim())          { close(); html += '<div style="height:8px;"></div>'; }
    else                         { close(); html += '<div>' + e + '</div>'; }
  });
  close();
  return html || '<div class="study-empty">작성된 내용이 없습니다.</div>';
}

/* ── 액션 아이템 ─────────────────────────────────────────────────────────── */
function styAddAction() {
  styFlushAll();
  const s = styCur();
  if(!s) return;
  styUpdate(s.id, { actions: (s.actions || []).concat([{ aid: _styUid('a'), text: '', owner: '', due: '', done: false }]) });
  styRenderActions(); styRenderStats(); styRenderList();
}
function styToggleAction(aid, done) {
  styFlushAll();
  const s = styCur();
  if(!s) return;
  styUpdate(s.id, { actions: (s.actions || []).map(function(a) { return a.aid === aid ? Object.assign({}, a, { done: !!done }) : a; }) });
  styRenderActions(); styRenderStats(); styRenderList();
}
function styPatchAction(aid, field, value) {
  const s = styCur();
  if(!s) return;
  if(!_styState.pendingActions || _styState.pendingActions.id !== s.id) _styState.pendingActions = { id: s.id, map: {} };
  const m = _styState.pendingActions.map;
  if(!m[aid]) m[aid] = {};
  m[aid][field] = value;
  clearTimeout(_styState.actionTimer);
  _styState.actionTimer = setTimeout(styFlushActions, 500);
}
function styFlushActions() {
  clearTimeout(_styState.actionTimer);
  const p = _styState.pendingActions;
  if(!p) return;
  _styState.pendingActions = null;
  const store = styLoad();
  const s = store.sessions.find(function(x) { return x.id === p.id; });
  if(!s) return;
  s.actions = (s.actions || []).map(function(a) { return p.map[a.aid] ? Object.assign({}, a, p.map[a.aid]) : a; });
  s.updatedAt = Date.now();
  stySave(store);
  styRenderStats(); styRenderList();
}
function styDelAction(aid) {
  styFlushAll();
  const s = styCur();
  if(!s) return;
  styUpdate(s.id, { actions: (s.actions || []).filter(function(a) { return a.aid !== aid; }) });
  styRenderActions(); styRenderStats(); styRenderList();
}

/* ── AI 요약 초안 (Worker /ai, 실패 시 로컬 규칙 요약 폴백) ──────────────── */
var _styAiBusy = false, _styAiLastTs = 0;

function _styLocalSummary(s) {
  const bullets = String(s.notes || '').split('\n')
    .map(function(l) { return l.replace(/^\s*[-•*]\s+/, '').trim(); })
    .filter(function(l) { return l && !/^#/.test(l); });
  const acts = (s.actions || []).filter(function(a) { return a.text; });
  const mats = (s.files || []).map(function(f) { return f.name; })
    .concat((s.links || []).map(function(l) { return l.label || l.url; }));
  const out = ['# 요약 (자동 정리 · 규칙 기반)'];
  out.push('- 일시: ' + (s.date || '') + (s.start ? ' ' + s.start : '') + (s.end ? '~' + s.end : ''));
  if((s.members || []).length) out.push('- 참석: ' + s.members.join(', '));
  if(mats.length) out.push('- 자료: ' + mats.slice(0, 8).join(' · '));
  out.push('');
  out.push('# 핵심 논의');
  if(bullets.length) bullets.slice(0, 12).forEach(function(b) { out.push('- ' + b); });
  else out.push('- (메모가 비어 있어 정리할 내용이 없습니다)');
  out.push('');
  out.push('# 액션 아이템');
  if(acts.length) acts.forEach(function(a) { out.push('- ' + (a.done ? '[완료] ' : '') + a.text + (a.owner ? ' (' + a.owner + ')' : '') + (a.due ? ' ~' + a.due : '')); });
  else out.push('- (등록된 액션 아이템 없음)');
  return out.join('\n');
}

async function styAiSummarize() {
  styFlushAll();
  const s = styCur();
  if(!s) return;
  const btn = document.getElementById('styAiBtn'), ta = document.getElementById('styNotes');
  if(!ta || _styAiBusy) return;
  const now = Date.now();
  if(now - _styAiLastTs < 6000) { if(typeof showToast === 'function') showToast('요청 간격 6초 — 잠시 후 다시 시도하세요.'); return; }

  const src = String(ta.value || '').trim();
  if(!src) { if(typeof showToast === 'function') showToast('먼저 메모를 조금이라도 작성하면 더 좋은 요약이 나옵니다.'); }

  const apply = function(text, tag) {
    const body = String(text || '').trim();
    if(!body) return;
    ta.value = (ta.value.replace(/\s+$/, '') + '\n\n' + '<!-- ' + tag + ' -->\n' + body + '\n').replace(/^\n+/, '');
    styPatchField('notes', ta.value);
    styNoteTab('view');
  };

  _styAiBusy = true; _styAiLastTs = now;
  if(btn) { btn.disabled = true; btn.textContent = '⟳ 생성 중…'; }
  try {
    let keyHash = null;
    try { keyHash = (typeof pfGetSyncKeyHash === 'function') ? await pfGetSyncKeyHash() : null; } catch(_) {}
    if(!keyHash) {
      apply(_styLocalSummary(s), 'AI 미사용 · 규칙 기반 자동 정리');
      if(typeof showToast === 'function') showToast('동기화 키가 없어 규칙 기반으로 정리했습니다. (투자 현황 → 🔑 동기화 키 등록 시 AI 사용)', 5000);
      return;
    }
    const snapshot = {
      유형: '스터디_회의록_요약_요청',
      제목: s.title || '', 일시: (s.date || '') + ' ' + (s.start || '') + '~' + (s.end || ''),
      장소: s.place || '', 참석자: s.members || [], 태그: s.tags || [],
      자료: (s.files || []).map(function(f) { return f.name; }).slice(0, 20)
        .concat((s.links || []).map(function(l) { return l.label || l.url; }).slice(0, 20)),
      메모원문: src.slice(0, 12000),
      기존_액션아이템: (s.actions || []).map(function(a) { return a.text; }).filter(Boolean).slice(0, 20),
    };
    // mode:'study' → Worker 가 회의록 전용 서버 고정 프롬프트를 쓴다(권장 경로).
    // question 은 mode 를 모르는 구버전 Worker 폴백용 — 신버전은 mode 를 우선해 이 문장을 무시한다.
    const question = '아래 snapshot 은 시장 데이터가 아니라 스터디 모임 메모입니다. 메모원문만 근거로 ' +
      '한국어 회의록을 작성하세요. 형식: "# 안건", "# 핵심 논의", "# 결론", "# 액션 아이템"(담당자/기한 포함) ' +
      '네 개 섹션의 불릿(-) 목록. 메모에 없는 내용은 만들어내지 마세요.';
    const r = await fetch(_cfProxyBase() + '/ai', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ keyHash: keyHash, mode: 'study', question: question, snapshot: snapshot }),
      signal: AbortSignal.timeout(45000),
    });
    const j = await r.json().catch(function() { return {}; });
    if(r.ok && j && j.ok && j.summary) {
      apply(String(j.summary).replace(/※\s*투자\s*조언이?\s*아닙니다\.?/g, '').trim(),
            'AI 초안 · ' + (j.engine || 'AI') + (j.model ? ' / ' + j.model : '') + ' · 사실 확인 필요');
      if(typeof showToast === 'function') showToast('AI 초안을 회의록 아래에 추가했습니다. 내용을 검토·수정하세요.', 4000);
    } else {
      apply(_styLocalSummary(s), 'AI 호출 실패 · 규칙 기반 자동 정리');
      if(typeof showToast === 'function') showToast('AI 를 사용할 수 없어 규칙 기반으로 정리했습니다.', 4000);
    }
  } catch(_) {
    apply(_styLocalSummary(s), 'AI 호출 실패 · 규칙 기반 자동 정리');
    if(typeof showToast === 'function') showToast('네트워크 오류 — 규칙 기반으로 정리했습니다.', 4000);
  } finally {
    _styAiBusy = false;
    if(btn) { btn.disabled = false; btn.textContent = '✨ AI 요약 초안'; }
  }
}

/* ── 내보내기 / 가져오기 ─────────────────────────────────────────────────── */
function _styBlobToDataUrl(blob) {
  return new Promise(function(resolve) {
    const fr = new FileReader();
    fr.onload = function() { resolve(String(fr.result || '')); };
    fr.onerror = function() { resolve(''); };
    fr.readAsDataURL(blob);
  });
}
async function styExport(withFiles) {
  styFlushAll();
  const store = styLoad();
  const payload = { schema: 'econ-study-backup', v: 1, exportedAt: new Date().toISOString(), withFiles: !!withFiles, sessions: store.sessions };
  if(withFiles) {
    const total = store.sessions.reduce(function(n, s) { return n + (s.files || []).reduce(function(m, f) { return m + (f.size || 0); }, 0); }, 0);
    if(total > 500 * 1024 * 1024 && !confirm('첨부 파일 총 ' + _styFmtSize(total) + ' 를 포함합니다. 파일이 매우 커지고 시간이 걸립니다. 계속할까요?')) return;
    if(typeof showToast === 'function') showToast('파일을 인코딩하는 중… 잠시 기다려 주세요.', 6000);
    payload.blobs = {};
    for(const s of store.sessions) {
      for(const f of (s.files || [])) {
        try {
          const rec = await styIdbGet(f.fid);
          if(rec && rec.blob) payload.blobs[f.fid] = await _styBlobToDataUrl(rec.blob);
        } catch(_) {}
      }
    }
  }
  const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'study-log-' + _styTodayStr() + (withFiles ? '-full' : '') + '.json';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(function() { URL.revokeObjectURL(url); }, 4000);
  if(typeof showToast === 'function') showToast('내보내기 완료.', 2500);
}
// data:<mime>;base64,<payload> → Blob.
//   fetch(dataUrl) 로 복원하면 CSP 의 connect-src 가 data: 스킴을 차단해(“Refused to connect”)
//   파일 포함 백업의 가져오기가 항상 실패한다. media-src 만 열어둔 정책을 넓히지 않기 위해
//   여기서 직접 디코드한다. 실패 시 null → 호출부가 건수를 세어 사용자에게 알린다.
function _styDataUrlToBlob(durl) {
  const m = /^data:([^;,]*)(;base64)?,([\s\S]*)$/.exec(String(durl || ''));
  if(!m) return null;
  const mime = m[1] || 'application/octet-stream', body = m[3] || '';
  try {
    if(!m[2]) return new Blob([decodeURIComponent(body)], { type: mime });
    const bin = atob(body), buf = new Uint8Array(bin.length);
    for(let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return new Blob([buf], { type: mime });
  } catch(_) { return null; }
}
function styImport(input) {
  const file = (input && input.files && input.files[0]) || null;
  if(!file) return;
  const fr = new FileReader();
  fr.onload = async function() {
    input.value = '';
    let p;
    try { p = JSON.parse(String(fr.result || '')); } catch(_) { alert('JSON 을 읽을 수 없습니다.'); return; }
    if(!p || p.schema !== 'econ-study-backup' || !Array.isArray(p.sessions)) { alert('스터디 기록 백업 파일이 아닙니다.'); return; }
    if(!confirm('기록 ' + p.sessions.length + '건을 가져옵니다. 같은 id 는 덮어쓰고 나머지는 추가합니다. 계속할까요?')) return;
    const store = styLoad();
    const idx = {};
    store.sessions.forEach(function(s, i) { idx[s.id] = i; });
    p.sessions.forEach(function(s) {
      if(idx[s.id] != null) store.sessions[idx[s.id]] = s; else store.sessions.push(s);
    });
    let fileOk = 0, fileFail = 0;
    if(p.blobs) {
      for(const s of p.sessions) {
        for(const f of (s.files || [])) {
          const durl = p.blobs[f.fid];
          if(!durl) { fileFail++; continue; }        // 텍스트만 내보낸 백업을 되살릴 때도 여기로 온다
          const b = _styDataUrlToBlob(durl);
          if(!b) { fileFail++; continue; }
          try {
            await styIdbPut({ fid: f.fid, sessionId: s.id, name: f.name, type: f.type, size: f.size, blob: b });
            fileOk++;
          } catch(e) { fileFail++; console.warn('study import blob', f.name, e); }
        }
      }
    } else {
      fileFail = p.sessions.reduce(function(n, s) { return n + (s.files || []).length; }, 0);
    }
    stySave(store, true);
    styRenderAll();
    if(typeof showToast === 'function') {
      // 파일 복원 실패를 조용히 넘기면 사용자는 기기 이관 후 첨부가 사라진 것을 뒤늦게 발견한다.
      showToast('가져오기 완료 — 기록 ' + p.sessions.length + '건' +
                (fileOk ? ' · 파일 ' + fileOk + '개' : '') +
                (fileFail ? ' · ⚠ 파일 ' + fileFail + '개 복원 실패(백업에 파일이 없거나 손상)' : '') + '.',
                fileFail ? 6000 : 3000);
    }
  };
  fr.readAsText(file);
}

/* ── 초기화 ──────────────────────────────────────────────────────────────── */
function initStudyPage() {
  if(!_styState.year) {
    const t = _styTodayStr();
    _styState.year = +t.slice(0, 4); _styState.month = +t.slice(5, 7); _styState.selDate = t;
  }
  if(!_styState.inited) {
    _styState.inited = true;
    const drop = document.getElementById('styDrop');
    if(drop) {
      ['dragenter', 'dragover'].forEach(function(ev) {
        drop.addEventListener(ev, function(e) { e.preventDefault(); e.stopPropagation(); drop.classList.add('dragover'); });
      });
      ['dragleave', 'drop'].forEach(function(ev) {
        drop.addEventListener(ev, function(e) { e.preventDefault(); e.stopPropagation(); drop.classList.remove('dragover'); });
      });
      drop.addEventListener('drop', function(e) {
        if(e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) styAddFiles(e.dataTransfer.files);
      });
    }
    const linkUrl = document.getElementById('styLinkUrl');
    if(linkUrl) linkUrl.addEventListener('keydown', function(e) { if(e.key === 'Enter') { e.preventDefault(); styAddLink(); } });
    // 다른 페이지로 이동하면 재생 중인 미디어를 정리해 blob URL 누수를 막는다
    window.addEventListener('beforeunload', function() { try { styFlushAll(); } catch(_) {} styClosePlayer(); });
  }
  styRenderAll();
}

// ── 🔔 경제 캘린더 ★★★ 이벤트 발표 알림 ──────────────────────────────────
const CAL_ALERTS_LS_KEY = 'econ_cal_alerts_v1';

function _calAlertsLoad() {
  try { return JSON.parse(localStorage.getItem(CAL_ALERTS_LS_KEY) || '{}') || {}; } catch(_) { return {}; }
}
function _calAlertsSave(subs) {
  try { localStorage.setItem(CAL_ALERTS_LS_KEY, JSON.stringify(subs)); } catch(_) {}
}
// 구독 키 — 정적 calEvents 에는 iso 가 없고 data.json 이벤트에는 있어, 양쪽에 공통인
// dt 의 'MM.DD' 접두사 + 이벤트명으로 매칭한다.
function _calAlertKey(e) { return `${String(e.dt || e.iso || '').slice(0, 5)}|${e.name}`; }

function calAlertSubscribed(e) {
  return !!_calAlertsLoad()[_calAlertKey(e)];
}

function toggleCalAlert(calIdx, btn) {
  const e = (typeof calEvents !== 'undefined') ? calEvents[calIdx] : null;
  if(!e) return;
  const subs = _calAlertsLoad();
  const key = _calAlertKey(e);
  if(subs[key]) {
    delete subs[key];
    _calAlertsSave(subs);
    showToast(`🔕 '${e.name}' 알림을 해제했습니다.`, 3000);
  } else {
    subs[key] = { name: e.name, iso: e.iso || '', lastAct: e.act || '', addedAt: Date.now() };
    _calAlertsSave(subs);
    // 브라우저 알림 권한 — 최초 구독 시 요청. 거부/미지원 시 인페이지 토스트로 폴백.
    if(typeof Notification !== 'undefined') {
      if(Notification.permission === 'default') {
        Notification.requestPermission().then(p => {
          if(p !== 'granted') showToast('브라우저 알림이 차단되어 페이지 내 토스트로 알려드립니다.');
        }).catch(() => {});
      } else if(Notification.permission === 'denied') {
        showToast('브라우저 알림이 차단되어 페이지 내 토스트로 알려드립니다.');
      }
    }
    showToast(`🔔 '${e.name}' 발표 시 알림을 보냅니다. (페이지가 열려 있는 동안)`, 4000);
  }
  // 벨 상태 갱신 — 캘린더 페이지가 활성일 때만 재렌더
  try {
    const pg = document.getElementById('page-calendar');
    if(pg && pg.classList.contains('active') && typeof buildCalendar === 'function') buildCalendar();
  } catch(_) {}
}

function _calNotify(title, body) {
  if(typeof Notification !== 'undefined' && Notification.permission === 'granted') {
    try { new Notification(title, { body, tag: title }); return; } catch(_) {}
  }
  showToast(`${title} — ${body}`, 10000);
}

// data.json 적용 시마다 호출 — 구독 이벤트의 실제값(act)이 새로 채워지거나 바뀌면 알림
function checkCalendarAlerts(d) {
  const subs = _calAlertsLoad();
  const keys = Object.keys(subs);
  if(!keys.length) return;
  const events = (d && d.economicCalendar && Array.isArray(d.economicCalendar.events)) ? d.economicCalendar.events : [];
  let changed = false;
  const now = Date.now();
  keys.forEach(key => {
    const sub = subs[key];
    // 90일 지난 구독은 자동 정리
    if(sub.addedAt && now - sub.addedAt > 90 * 24 * 3600 * 1000) { delete subs[key]; changed = true; return; }
    const ev = events.find(e => _calAlertKey(e) === key);
    if(!ev || !ev.act) return;
    if(ev.act !== sub.lastAct) {
      const beat = ev.beat === 1 ? ' (예측 상회 ▲)' : ev.beat === -1 ? ' (예측 하회 ▼)' : '';
      _calNotify(`📢 ${ev.name} 발표`, `실제 ${ev.act} · 예측 ${ev.fore || '—'} · 이전 ${ev.prev || '—'}${beat}`);
      sub.lastAct = ev.act;
      changed = true;
    }
  });
  if(changed) _calAlertsSave(subs);
}

// ── 🔀 이중축 지표 비교 차트 ───────────────────────────────────────────────
const CMP_LS_KEY = 'econ_cmp_sel_v1';
const CMP_COLOR_A = getThemeColors().accent, CMP_COLOR_B = '#f5a623';
// B 시리즈 색 테마 getter — CMP_COLOR_B(#f5a623)는 라이트 흰 배경에서 2.0:1 로 판독 불가.
// 반드시 hex 리터럴 반환 (CB+'22' 알파 결합 때문에 var() 사용 금지).
function cmpColorB() { return document.documentElement.classList.contains('light') ? '#b45309' : CMP_COLOR_B; }
// 기본 b 를 ei.us.ff_rate(월간·희소 시계열)로 두면 일간 축에 null 이 대부분이라
// 첫 화면 비교차트가 사실상 빈 선이었다(감사 A2) — 밀도가 같은 일간 지수로.
let _cmpState = { a: 'idx.KOSPI', b: 'idx.SP500', period: '1Y', norm: true };
let _cmpInited = false, _cmpLastTs = null;

const _CMP_LABELS = {
  KOSPI:'KOSPI', KOSDAQ:'KOSDAQ', SP500:'S&P 500', NASDAQ:'NASDAQ', Nikkei:'닛케이 225', Shanghai:'상하이종합', SOX:'필라델피아 반도체',
  USDKRW:'USD/KRW', EURKRW:'EUR/KRW', JPYKRW:'JPY(100)/KRW', EURUSD:'EUR/USD', USDJPY:'USD/JPY',
  Gold:'금', Silver:'은', Copper:'구리', WTI:'WTI 유가', Brent:'브렌트유', NatGas:'천연가스',
  Wheat:'밀', Corn:'옥수수', Soybean:'대두', Coffee:'커피', Sugar:'설탕',
};

// 선택 가능한 지표 카탈로그 — data.json 의 일별 시계열 + 경제지표 history 맵
function _cmpCatalog() {
  const d = _latestDataForIndicators;
  if(!d) return [];
  const out = [];
  const hist = d.history || {};
  Object.keys(hist.indices || {}).forEach(k => out.push({ key: 'idx.' + k, label: _CMP_LABELS[k] || k, group: '주가지수' }));
  Object.keys(hist.fx || {}).forEach(k => out.push({ key: 'fx.' + k, label: _CMP_LABELS[k] || k, group: '환율' }));
  Object.keys(hist.commodities || {}).forEach(k => out.push({ key: 'com.' + k, label: _CMP_LABELS[k] || k, group: '원자재' }));
  const ei = d.economicIndicators || {};
  const ccName = { us: '🇺🇸', kr: '🇰🇷', jp: '🇯🇵', eu: '🇪🇺', cn: '🇨🇳', de: '🇩🇪', uk: '🇬🇧' };
  Object.keys(ei).forEach(cc => {
    Object.keys(ei[cc] || {}).forEach(k => {
      const ind = ei[cc][k];
      if(ind && ind.history && typeof ind.history === 'object' && Object.keys(ind.history).length >= 6) {
        out.push({ key: `ei.${cc}.${k}`, label: `${ccName[cc] || cc} ${ind.desc || k}`, group: '경제지표' });
      }
    });
  });
  return out;
}

// 키로 [{d:'YYYY-MM-DD', v:number}] 시계열 추출 (날짜 오름차순)
function _cmpSeries(key) {
  const d = _latestDataForIndicators;
  if(!d || !key) return [];
  const [type, ...rest] = key.split('.');
  if(type === 'idx' || type === 'fx' || type === 'com') {
    const grp = type === 'idx' ? 'indices' : type === 'fx' ? 'fx' : 'commodities';
    const arr = ((d.history || {})[grp] || {})[rest[0]] || [];
    return arr.filter(p => p && p.date && p.close != null).map(p => ({ d: p.date, v: +p.close }));
  }
  if(type === 'ei') {
    const ind = ((d.economicIndicators || {})[rest[0]] || {})[rest[1]];
    if(!ind || !ind.history) return [];
    return Object.entries(ind.history)
      .filter(([, v]) => v != null && isFinite(+v))
      .map(([dt, v]) => ({ d: dt, v: +v }))
      .sort((a, b) => a.d < b.d ? -1 : 1);
  }
  return [];
}

function _cmpLabelOf(key) {
  const c = _cmpCatalog().find(m => m.key === key);
  return c ? c.label : key;
}

function _cmpFillSelect(sel, catalog, value) {
  const groups = {};
  catalog.forEach(m => { (groups[m.group] = groups[m.group] || []).push(m); });
  sel.innerHTML = Object.keys(groups).map(g =>
    `<optgroup label="${g}">` + groups[g].map(m => `<option value="${m.key}">${escapeHtml(m.label)}</option>`).join('') + '</optgroup>').join('');
  if(catalog.some(m => m.key === value)) sel.value = value;
}

function initCompareTool() {
  const selA = document.getElementById('cmpSelA');
  if(!selA || !_latestDataForIndicators) return;
  const ts = _latestDataForIndicators.lastUpdated || null;
  if(_cmpInited && ts === _cmpLastTs) return;   // 데이터 변동 없으면 재렌더 생략 (1~3분 폴링 플리커 방지)
  _cmpLastTs = ts;
  const catalog = _cmpCatalog();
  if(!catalog.length) return;
  if(!_cmpInited) {
    try {
      const saved = JSON.parse(localStorage.getItem(CMP_LS_KEY) || 'null');
      if(saved && saved.a && saved.b) _cmpState = { ..._cmpState, ...saved };
    } catch(_) {}
    _cmpInited = true;
    // 저장된 기간 버튼 상태 복원
    document.querySelectorAll('#cmpPeriodBtns .tab-btn').forEach(b => {
      const act = b.dataset.p === _cmpState.period;
      b.classList.toggle('active', act);
      b.style.background = act ? getThemeColors().accent : 'transparent';
      b.style.color = act ? '#fff' : '#8d90a2';
    });
    _cmpSyncNormBtn();
  }
  // 상태값 검증 후 채우기 — 종전에는 '옵션을 채운 뒤 select.value 를 상태로 되읽어',
  // 카탈로그가 아직 부분(실시간 전용 1차 로드)일 때 첫 옵션(KOSPI)으로 떨어진 값이
  // 상태·저장까지 오염돼 'KOSPI vs KOSPI'가 나왔다(감사 A2). 이제 상태가 기준이고,
  // 무효하면 밀도 있는 기본 쌍(a≠b 보장)으로 교정한다.
  const _has = k => catalog.some(m => m.key === k);
  const _dense = k => { try { return _cmpSeries(k).length >= 30; } catch(_) { return false; } };
  if(!_has(_cmpState.a)) _cmpState.a = ['idx.KOSPI', 'idx.SP500'].find(k => _has(k) && _dense(k)) || catalog[0].key;
  if(!_has(_cmpState.b) || _cmpState.b === _cmpState.a) {
    _cmpState.b = ['idx.SP500', 'fx.USDKRW', 'idx.KOSDAQ'].find(k => _has(k) && _dense(k) && k !== _cmpState.a)
      || (catalog.find(m => m.key !== _cmpState.a && _dense(m.key)) || catalog.find(m => m.key !== _cmpState.a) || catalog[0]).key;
  }
  _cmpFillSelect(selA, catalog, _cmpState.a);
  _cmpFillSelect(document.getElementById('cmpSelB'), catalog, _cmpState.b);
  cmpRender();
}

function cmpOnSelectChange() {
  _cmpState.a = document.getElementById('cmpSelA').value;
  _cmpState.b = document.getElementById('cmpSelB').value;
  try { localStorage.setItem(CMP_LS_KEY, JSON.stringify(_cmpState)); } catch(_) {}
  cmpRender();
}

function cmpSwap() {
  [_cmpState.a, _cmpState.b] = [_cmpState.b, _cmpState.a];
  const sa = document.getElementById('cmpSelA'), sb = document.getElementById('cmpSelB');
  if(sa) sa.value = _cmpState.a;
  if(sb) sb.value = _cmpState.b;
  try { localStorage.setItem(CMP_LS_KEY, JSON.stringify(_cmpState)); } catch(_) {}
  cmpRender();
}

// 추천 조합 프리셋 — 카탈로그에 실존하는 키 쌍만 적용 (데이터 미수집 시 무시)
function cmpApplyPreset(a, b) {
  const cat = _cmpCatalog();
  if(!cat.some(m => m.key === a) || !cat.some(m => m.key === b)) return;
  _cmpState.a = a; _cmpState.b = b;
  const sa = document.getElementById('cmpSelA'), sb = document.getElementById('cmpSelB');
  if(sa) sa.value = a;
  if(sb) sb.value = b;
  try { localStorage.setItem(CMP_LS_KEY, JSON.stringify(_cmpState)); } catch(_) {}
  cmpRender();
}

function cmpSetPeriod(p, btn) {
  _cmpState.period = p;
  try { localStorage.setItem(CMP_LS_KEY, JSON.stringify(_cmpState)); } catch(_) {}
  document.querySelectorAll('#cmpPeriodBtns .tab-btn').forEach(b => {
    b.classList.remove('active');
    b.style.background = 'transparent'; b.style.color = 'var(--c-txt-dim)';
  });
  if(btn) { btn.classList.add('active'); btn.style.background = 'var(--c-accent)'; btn.style.color = '#fff'; }
  cmpRender();
}

// 지수화 토글 (UX 4.1) — 두 지표의 시작점을 100으로 환산해 단일 축으로 등락률만 비교.
// 이중축은 시작 스케일 차이로 기울기 착시가 생기기 쉬워, 순수 변화율 비교 모드를 제공한다.
function _cmpSyncNormBtn() {
  const btn = document.getElementById('cmpNormBtn');
  if(!btn) return;
  const on = !!_cmpState.norm;
  // 토글 활성은 accent — 상승색(CUP) 오용은 '상승'으로 오독되고 다크 하드코딩은 라이트에서 깨짐
  btn.style.background = on ? 'var(--c-accent)' : 'transparent';
  btn.style.borderColor = on ? 'var(--c-accent)' : 'var(--c-border)';
  btn.style.color = on ? 'var(--c-on-accent,#fff)' : 'var(--c-txt-dim)';
  btn.setAttribute('aria-pressed', on ? 'true' : 'false');
}
function cmpToggleNorm() {
  _cmpState.norm = !_cmpState.norm;
  try { localStorage.setItem(CMP_LS_KEY, JSON.stringify(_cmpState)); } catch(_) {}
  _cmpSyncNormBtn();
  cmpRender();
}

function _cmpCutoff(period) {
  if(period === 'ALL') return null;
  const months = { '3M': 3, '6M': 6, '1Y': 12, '3Y': 36 }[period] || 12;
  const dt = new Date();
  dt.setMonth(dt.getMonth() - months);
  return dt.toISOString().slice(0, 10);
}

function cmpRender() {
  const canvas = document.getElementById('compareChart');
  if(!canvas || typeof Chart === 'undefined') return;
  const cutoff = _cmpCutoff(_cmpState.period);
  const filt = s => cutoff ? s.filter(p => p.d >= cutoff) : s;
  const A = filt(_cmpSeries(_cmpState.a)), B = filt(_cmpSeries(_cmpState.b));
  const labels = [...new Set([...A.map(p => p.d), ...B.map(p => p.d)])].sort();
  const mapA = Object.fromEntries(A.map(p => [p.d, p.v]));
  const mapB = Object.fromEntries(B.map(p => [p.d, p.v]));
  const labA = _cmpLabelOf(_cmpState.a), labB = _cmpLabelOf(_cmpState.b);
  const tc = (typeof getThemeColors === 'function') ? getThemeColors() : { txt: '#8d90a2', grid: '#2a2e3d55' };
  // 지수화 모드 — 표시 구간 내 첫 유효값을 100으로 환산 (단일 축, 순수 변화율 비교)
  const norm = !!_cmpState.norm;
  const rebase = map => {
    const base = labels.map(d => map[d]).find(v => v != null && isFinite(v) && v !== 0);
    if(base == null) return labels.map(() => null);
    return labels.map(d => map[d] != null ? map[d] / base * 100 : null);
  };
  const dataA = norm ? rebase(mapA) : labels.map(d => mapA[d] ?? null);
  const dataB = norm ? rebase(mapB) : labels.map(d => mapB[d] ?? null);
  const CB = cmpColorB();   // 테마별 B 색 — 라이트에서 판독 가능한 갈색으로
  if(charts['compareChart']) { try { charts['compareChart'].destroy(); } catch(_) {} }
  charts['compareChart'] = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: labA, data: dataA, yAxisID: 'yA',
          borderColor: CMP_COLOR_A, backgroundColor: CMP_COLOR_A + '22',
          borderWidth: 2, pointRadius: 0, pointHitRadius: 6, tension: 0.3, spanGaps: true },
        { label: labB, data: dataB, yAxisID: norm ? 'yA' : 'yB',
          borderColor: CB, backgroundColor: CB + '22',
          borderWidth: 2, pointRadius: 0, pointHitRadius: 6, tension: 0.3, spanGaps: true },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, labels: { color: tc.txt, usePointStyle: true, pointStyle: 'line', font: { size: 11 } } },
        ...(norm ? { tooltip: { callbacks: { label: c =>
          `${c.dataset.label}: ${c.parsed.y == null ? '-' : c.parsed.y.toFixed(2)} (시작=100, ${(c.parsed.y - 100) >= 0 ? '+' : ''}${(c.parsed.y - 100).toFixed(2)}%)` } } } : {}),
      },
      // 축 타이틀에 지표명 명기 — 축-시리즈 매칭이 색상 단독 의존에서 벗어남 (색각 이상·인쇄 대응)
      scales: norm ? {
        x: { ticks: { color: tc.txt, maxTicksLimit: 10, font: { size: 10 } }, grid: { color: tc.grid } },
        yA: { position: 'left', ticks: { color: tc.txt, font: { size: 10 } }, grid: { color: tc.grid },
              title: { display: true, text: '지수화 (시작=100)', color: tc.txt, font: { size: 10 } } },
      } : {
        x: { ticks: { color: tc.txt, maxTicksLimit: 10, font: { size: 10 } }, grid: { color: tc.grid } },
        // _fixedTickColor — 테마 전환(rebuildChartsForTheme) 시에도 데이터셋과 같은 색 유지
        yA: { position: 'left',  ticks: { color: CMP_COLOR_A, font: { size: 10 } }, grid: { color: tc.grid }, _fixedTickColor: CMP_COLOR_A,
              title: { display: true, text: labA, color: CMP_COLOR_A, font: { size: 10 } } },
        yB: { position: 'right', ticks: { color: CB, font: { size: 10 } }, grid: { drawOnChartArea: false }, _fixedTickColor: CB,
              title: { display: true, text: labB, color: CB, font: { size: 10 } } },
      },
    },
  });
  try { canvas.setAttribute('aria-label', `${labA} · ${labB} 지표 비교 차트${norm ? ' (지수화, 시작=100)' : ' (이중축)'}`); } catch(_) {}
  // YoY — 주 시리즈 A(dataset 0)만 전년 오버레이. 지수화(norm) 모드에서는 스케일이 달라 비활성.
  { if(!norm){ const _fa = _cmpSeries(_cmpState.a) || [];
      registerYoY('compareChart', { mode:'date', dispDates:labels, fullDates:_fa.map(p=>p.d), fullValues:_fa.map(p=>p.v), tol:10, primary:0, color:CMP_COLOR_A, tension:0.3 });
    } else registerYoY('compareChart', null);
    applyYoY('compareChart'); }
  const last = s => s.length ? s[s.length - 1] : null;
  const la = last(A), lb = last(B), fmt = v => (+v).toLocaleString('ko-KR', { maximumFractionDigits: 2 });
  const info = document.getElementById('cmpInfo');
  if(info) {
    if(!(la && lb)) info.textContent = '선택한 지표의 시계열 데이터가 아직 없습니다.';
    else if(norm) {
      const lastIdx = arr => { for(let i = arr.length - 1; i >= 0; i--) if(arr[i] != null) return arr[i]; return null; };
      const na = lastIdx(dataA), nb = lastIdx(dataB);
      const chg = v => v == null ? '-' : `${(v - 100) >= 0 ? '+' : ''}${(v - 100).toFixed(2)}%`;
      info.innerHTML = `⚖ 지수화 모드 (구간 시작=100) — <span style="color:${CMP_COLOR_A};">● ${escapeHtml(labA)}</span> ${chg(na)} &nbsp;·&nbsp; <span style="color:${CB};">● ${escapeHtml(labB)}</span> ${chg(nb)}`;
    } else {
      info.innerHTML = `<span style="color:${CMP_COLOR_A};">● ${escapeHtml(labA)}</span> ${fmt(la.v)} (${la.d}) &nbsp;·&nbsp; <span style="color:${CB};">● ${escapeHtml(labB)}</span> ${fmt(lb.v)} (${lb.d})`;
    }
  }
}

// ── ↕ 대시보드 홈 위젯 드래그 정렬 + 표시/숨김 (UX 2.1) ─────────────────────
const DND_KPI_LS_KEY = 'econ_home_kpi_order_v1';
const DND_SEC_LS_KEY = 'econ_home_sec_order_v1';
const SEC_HIDDEN_LS_KEY = 'econ_home_hidden_v1';
const SEC_NAMES = { brief: '오늘의 브리핑', kpi: '핵심 지표 KPI', main: '메인 차트', compare: '지표 비교 차트', bottom: '등락 Top10 · 뉴스' };
let _dndEl = null, _dndType = null;

function _getHiddenSecs() {
  try { const a = JSON.parse(localStorage.getItem(SEC_HIDDEN_LS_KEY) || '[]'); return Array.isArray(a) ? a : []; } catch(_) { return []; }
}
function _setHiddenSecs(arr) { try { localStorage.setItem(SEC_HIDDEN_LS_KEY, JSON.stringify(arr)); } catch(_) {} }

function hideHomeSec(key) {
  const el = document.querySelector(`#page-dashboard .home-sec[data-sec="${key}"]`);
  if(el) el.style.display = 'none';
  const hidden = _getHiddenSecs();
  if(!hidden.includes(key)) { hidden.push(key); _setHiddenSecs(hidden); }
  renderHiddenSecBar();
}
function restoreHomeSec(key) {
  const el = document.querySelector(`#page-dashboard .home-sec[data-sec="${key}"]`);
  if(el) el.style.display = '';
  _setHiddenSecs(_getHiddenSecs().filter(k => k !== key));
  renderHiddenSecBar();
  // 다시 보이게 된 캔버스 차트가 0px 로 그려져 있을 수 있어 리사이즈 트리거
  try { window.dispatchEvent(new Event('resize')); } catch(_) {}
}
// 숨긴 위젯 복원 바 — 숨긴 섹션이 있을 때만 대시보드 상단에 표시
function renderHiddenSecBar() {
  const page = document.getElementById('page-dashboard');
  if(!page) return;
  let bar = document.getElementById('hiddenSecBar');
  const hidden = _getHiddenSecs();
  if(!hidden.length) { if(bar) bar.remove(); return; }
  if(!bar) {
    bar = document.createElement('div');
    bar.id = 'hiddenSecBar';
    bar.style.cssText = 'display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:11px;color:var(--c-txt-dim,#a4a8bc);margin-bottom:10px;';
    page.insertBefore(bar, page.firstChild);
  }
  bar.innerHTML = '<span>숨긴 위젯:</span>' + hidden.map(k =>
    `<button onclick="restoreHomeSec('${k}')" title="위젯 다시 표시" style="font-size:var(--font-size-sm);padding:2px 10px;border:1px dashed var(--c-border);border-radius:var(--r-full);background:transparent;color:var(--c-primary);cursor:pointer;">👁 ${SEC_NAMES[k] || k}</button>`).join('');
}

function applyHomeLayout() {
  try {
    const secOrder = JSON.parse(localStorage.getItem(DND_SEC_LS_KEY) || 'null');
    if(Array.isArray(secOrder) && secOrder.length) {
      const page = document.getElementById('page-dashboard');
      secOrder.forEach(k => {
        const el = page.querySelector(`.home-sec[data-sec="${k}"]`);
        if(el) page.appendChild(el);
      });
    }
  } catch(_) {}
  try {
    const kpiOrder = JSON.parse(localStorage.getItem(DND_KPI_LS_KEY) || 'null');
    if(Array.isArray(kpiOrder) && kpiOrder.length) {
      const grid = document.getElementById('homeKpiGrid');
      kpiOrder.forEach(id => {
        const el = document.getElementById(id);
        if(el && grid && el.parentNode === grid) grid.appendChild(el);
      });
    }
  } catch(_) {}
  // 숨긴 섹션 적용 (2.1)
  try {
    _getHiddenSecs().forEach(k => {
      const el = document.querySelector(`#page-dashboard .home-sec[data-sec="${k}"]`);
      if(el) el.style.display = 'none';
    });
    renderHiddenSecBar();
  } catch(_) {}
}

function _dndSaveOrders() {
  try {
    localStorage.setItem(DND_SEC_LS_KEY, JSON.stringify(
      [...document.querySelectorAll('#page-dashboard .home-sec')].map(s => s.dataset.sec)));
    localStorage.setItem(DND_KPI_LS_KEY, JSON.stringify(
      [...document.querySelectorAll('#homeKpiGrid .kpi-card')].map(c => c.id)));
  } catch(_) {}
}

function initHomeDnd() {
  // 섹션 드래그 — 우상단 ⠿ 핸들을 잡았을 때만 draggable 활성화 (내부 버튼/차트 조작과 충돌 방지)
  document.querySelectorAll('#page-dashboard .home-sec').forEach(sec => {
    const h = document.createElement('div');
    h.className = 'sec-drag-handle';
    h.title = '드래그하여 섹션 순서 변경';
    h.textContent = '⠿';
    h.addEventListener('mousedown', () => { sec.draggable = true; });
    h.addEventListener('mouseup',   () => { sec.draggable = false; });
    sec.appendChild(h);
    // 위젯 숨김 토글 (2.1) — 안 보는 섹션은 숨겨 정보 밀도를 낮춘다 (상단 복원 바로 되돌리기)
    const hide = document.createElement('button');
    hide.className = 'sec-hide-btn';
    hide.title = `'${SEC_NAMES[sec.dataset.sec] || '이 위젯'}' 숨기기 (상단 복원 바에서 다시 표시)`;
    hide.textContent = '✕';
    hide.addEventListener('click', ev => { ev.stopPropagation(); hideHomeSec(sec.dataset.sec); });
    sec.appendChild(hide);
    sec.addEventListener('dragstart', ev => {
      if(!sec.draggable) { ev.preventDefault(); return; }
      _dndEl = sec; _dndType = 'sec';
      sec.classList.add('dnd-dragging');
      ev.dataTransfer.effectAllowed = 'move';
      try { ev.dataTransfer.setData('text/plain', 'sec'); } catch(_) {}
    });
    sec.addEventListener('dragend', () => {
      sec.classList.remove('dnd-dragging');
      sec.draggable = false;
      _dndEl = null; _dndType = null;
      _dndSaveOrders();
    });
    sec.addEventListener('dragover', ev => {
      if(_dndType !== 'sec' || !_dndEl || _dndEl === sec) return;
      ev.preventDefault();
      const r = sec.getBoundingClientRect();
      sec.parentNode.insertBefore(_dndEl, ev.clientY < r.top + r.height / 2 ? sec : sec.nextSibling);
    });
  });
  // KPI 카드 드래그 — 카드 전체를 잡아 좌우 재배열
  document.querySelectorAll('#homeKpiGrid .kpi-card').forEach(card => {
    card.draggable = true;
    card.addEventListener('dragstart', ev => {
      _dndEl = card; _dndType = 'kpi';
      card.classList.add('dnd-dragging');
      ev.dataTransfer.effectAllowed = 'move';
      try { ev.dataTransfer.setData('text/plain', 'kpi'); } catch(_) {}
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('dnd-dragging');
      _dndEl = null; _dndType = null;
      _dndSaveOrders();
    });
    card.addEventListener('dragover', ev => {
      if(_dndType !== 'kpi' || !_dndEl || _dndEl === card) return;
      ev.preventDefault();
      const r = card.getBoundingClientRect();
      card.parentNode.insertBefore(_dndEl, ev.clientX < r.left + r.width / 2 ? card : card.nextSibling);
    });
  });
}

// ── ● 지연 데이터 글로벌 상태 칩 (UX 2.4) ──────────────────────────────────
// 카드마다 흩어져 있던 '15분 지연' 경고문을 단일 상시 표시 칩으로 일원화.
// 좌하단 플로팅이 본문을 가린다는 피드백으로 사이드바 정적 마크업으로 이전됨 —
// 이 함수는 마크업 누락 시에만 사이드바에 보강 삽입하는 안전망.
function initGlobalDelayChip() {
  if(document.getElementById('globalDelayChip')) return;
  const sb = document.getElementById('sidebar');
  if(!sb) return;
  const chip = document.createElement('div');
  chip.id = 'globalDelayChip';
  chip.title = '본 정보는 최대 15분 지연된 데이터 기준입니다.\n무료 시세 API 특성상 페이지의 현재가는 최대 15분가량 지연될 수 있습니다.\n(카카오톡 종목 알림은 장중 매분 실시간급 시세로 별도 평가 — 보통 1~2분 내 도착)';
  chip.innerHTML = '<span class="dot"></span>Market Data 15m Delayed';
  sb.appendChild(chip);
}

/* ═══ Phase 3 (2026-08) — 위젯 접기 · 페이지 목차 칩 · 위젯 신선도 칩 ═══
   원칙: 홈 home-sec 시스템(숨김/정렬)의 완성된 패턴을 재사용한다 — 상태는 localStorage,
   다시 보일 때 resize 디스패치로 0px 캔버스 소생(restoreHomeSec 와 동일). */

// ── 1) 위젯 접기 — .widget-title 클릭으로 본문만 접힘/펼침 ──────────────
var WCOLLAPSE_LS = 'econ_widget_collapse_v1';
function _wcLoad(){ try { return new Set(JSON.parse(localStorage.getItem(WCOLLAPSE_LS) || '[]')); } catch(_) { return new Set(); } }
function _wcSave(s){ try { localStorage.setItem(WCOLLAPSE_LS, JSON.stringify([...s])); } catch(_) {} }
function _wcSetState(w, t, collapsed){
  w.classList.toggle('w-collapsed', collapsed);
  t.setAttribute('aria-expanded', String(!collapsed));
  // 접혀 있던 동안 0px 로 그려진 Chart.js 캔버스 소생 — restoreHomeSec 패턴
  if(!collapsed){ try { window.dispatchEvent(new Event('resize')); } catch(_) {} }
}
function initWidgetCollapse(){
  var saved = _wcLoad();
  document.querySelectorAll('#mainContent .widget').forEach(function(w){
    // 제외: 클릭 내비게이션 카드, <details> 위젯(네이티브 토글 보유)
    if(w.hasAttribute('onclick') || w.tagName === 'DETAILS') return;
    var t = w.querySelector('.widget-title');
    if(!t || t.closest('.widget') !== w) return;
    // 타이틀이 위젯 직계(단순형)거나 직계 헤더 줄 안(헤더형)인 경우만 — 그 외 구조는 제외
    var head = (t.parentElement === w) ? t : (t.parentElement.parentElement === w ? t.parentElement : null);
    if(!head) return;
    head.classList.add('w-head');
    t.classList.add('w-toggle');
    t.setAttribute('role', 'button'); t.setAttribute('tabindex', '0');
    var key = (w.closest('.page') ? w.closest('.page').id : 'x') + '|' + (t.textContent || '').trim().slice(0, 40);
    _wcSetState(w, t, saved.has(key));
    function onToggle(ev){
      // 타이틀 안의 인터랙티브 요소(신선도 칩·링크·버튼)는 통과
      if(ev.target.closest('button,a,select,input,label,.w-fresh-chip')) return;
      var willCollapse = !w.classList.contains('w-collapsed');
      _wcSetState(w, t, willCollapse);
      var s = _wcLoad(); willCollapse ? s.add(key) : s.delete(key); _wcSave(s);
    }
    t.addEventListener('click', onToggle);
    t.addEventListener('keydown', function(ev){
      if(ev.key === 'Enter' || ev.key === ' '){ ev.preventDefault(); onToggle(ev); }
    });
  });
}

// ── 2) 페이지 목차 칩 — 긴 페이지 상단에 섹션 바로가기 (h2 로 문서 아웃라인 복구) ──
// 대상은 title 텍스트 부분일치로 찾는다 — id 하드코딩보다 마크업 변경에 강하다.
var PAGE_TOC = {
  'page-market':     { title: '시장 지표', items: [
    { label: 'LME 재고',   m: 'LME 금속 창고 재고', tabText: '원자재' },
    { label: '금속 심층',  m: 'Heavy Metal Stats',  tabText: '원자재' },
    { label: '해상운임',   m: '운송 운임지수',       tabText: '원자재' },
    { label: '기후 ENSO',  sel: '#ensoCard',        tabText: '원자재' } ] },
  'page-macro':      { title: '거시경제', items: [
    { label: '국가·주제 차트', sel: '#macroContent' },
    { label: '전체 지표',      m: '주요 경제 지표 전체' } ] },
  'page-realestate': { title: '부동산', items: [
    { label: '가격지수',    m: '아파트 가격지수 추이' },
    { label: '지역 등락',   m: '지역별 등락률' },
    { label: '대출 규제',   m: '대출 규제 현황' },
    { label: '청약 경쟁률', m: '청약 경쟁률' },
    { label: '🇺🇸 미국',     m: '미국 지역별 Case-Shiller', tabText: '미국' } ] },
  'page-investor':   { title: '주요 투자자', items: [
    { label: '교차 비교',  m: '글로벌 연기금 자산배분' },
    { label: '수익률',     m: '연도별 수익률' },
    { label: '자산 배분',  m: '자산 배분 현황' },
    { label: '보유 종목',  m: '국내주식 Top 10' } ] },
};
function _tocTarget(page, it){
  if(it.sel) return page.querySelector(it.sel);
  var ts = page.querySelectorAll('.widget-title');
  for(var i = 0; i < ts.length; i++){
    if((ts[i].textContent || '').indexOf(it.m) !== -1) return ts[i].closest('.widget') || ts[i];
  }
  return null;
}
function _tocClickTab(page, txt){
  var btns = page.querySelectorAll('.tab-btn');
  for(var i = 0; i < btns.length; i++){
    if((btns[i].textContent || '').indexOf(txt) !== -1){ btns[i].click(); return; }
  }
}
function buildPageTocs(){
  Object.keys(PAGE_TOC).forEach(function(pid){
    var page = document.getElementById(pid);
    if(!page || page.querySelector('.page-toc')) return;
    var cfg = PAGE_TOC[pid];
    var bar = document.createElement('nav');
    bar.className = 'page-toc';
    bar.setAttribute('aria-label', cfg.title + ' 섹션 바로가기');
    var h = document.createElement('h2');
    h.className = 'page-toc-h'; h.textContent = cfg.title;
    bar.appendChild(h);
    cfg.items.forEach(function(it){
      var a = document.createElement('a');
      a.textContent = it.label; a.href = '#';
      a.addEventListener('click', function(ev){
        ev.preventDefault();
        try {
          if(it.tabText) _tocClickTab(page, it.tabText);   // 숨은 탭 안이면 먼저 활성화
          requestAnimationFrame(function(){
            var el = _tocTarget(page, it);
            if(!el) return;
            // 접힌 위젯이면 펼치고 이동
            if(el.classList && el.classList.contains('w-collapsed')){
              var tg = el.querySelector('.w-toggle'); if(tg) tg.click();
            }
            el.classList.add('w-anchor-target');
            el.scrollIntoView({ behavior: 'smooth', block: 'start' });
          });
        } catch(_) {}
      });
      bar.appendChild(a);
    });
    page.insertBefore(bar, page.firstElementChild);
  });
}

// ── 3) 위젯 신선도 칩 — dataHealth(stale/failed/missing)를 대표 위젯 타이틀에 노출 ──
var WIDGET_FRESH_MAP = [
  { pid: 'page-dashboard',  m: '시장 분위기',        pre: ['sentiment.'] },
  { pid: 'page-dashboard',  m: 'Top10',              pre: ['stockMovers.', 'etfMovers.'] },
  { pid: 'page-market',     m: '운송 운임지수',       pre: ['freight'] },
  { pid: 'page-macro',      m: '주요 경제 지표 전체', pre: ['economicIndicators.'] },
  { pid: 'page-investor',   m: '자산 배분 현황',      pre: ['nps'] },
  { pid: 'page-investor',   m: '글로벌 연기금',       pre: ['berkshire'] },
  { pid: 'page-realestate', m: '아파트 가격지수',     pre: ['realestate.kr.'] },
];
function applyWidgetFreshChips(){
  var h = window._dataHealth;
  // 방어: 구버전 dataHealth(4건짜리 — 판정 시점 버그 시절 산출물)로는 위젯 판정을 하지 않는다
  if(!h || !Array.isArray(h.items) || h.items.length < 5) return;
  WIDGET_FRESH_MAP.forEach(function(cfg){
    var page = document.getElementById(cfg.pid);
    if(!page) return;
    var t = null, ts = page.querySelectorAll('.widget-title');
    for(var i = 0; i < ts.length; i++){
      if((ts[i].textContent || '').indexOf(cfg.m) !== -1){ t = ts[i]; break; }
    }
    if(!t) return;
    var worst = null;
    h.items.forEach(function(it){
      if(it.state !== 'stale' && it.state !== 'failed' && it.state !== 'missing') return;
      if(!cfg.pre.some(function(p){ return it.path === p || it.path.indexOf(p) === 0; })) return;
      if(!worst || (it.ageDays || 9999) > (worst.ageDays || 9999)) worst = it;
    });
    var old = t.querySelector('.w-fresh-chip');
    if(old) old.remove();
    if(!worst) return;
    var chip = document.createElement('span');
    chip.className = 'w-fresh-chip';
    chip.style.color = worst.state === 'stale' ? 'var(--c-warn,#f0c75e)' : 'var(--ind-neg)';
    chip.textContent = worst.state === 'stale' ? ('지연 ' + worst.ageDays + '일')
                     : worst.state === 'failed' ? '수집 실패' : '데이터 없음';
    chip.title = worst.path + ' — 기준일 ' + (worst.asOf || '미상') + ' · 클릭하면 시스템 진단';
    chip.setAttribute('role', 'button'); chip.setAttribute('tabindex', '0');
    chip.addEventListener('click', function(ev){
      ev.stopPropagation();
      try { showPage('settings'); setTimeout(runDiagnostics, 300); } catch(_) {}
    });
    t.appendChild(chip);
  });
}


// ── 4) 홈 메인차트 저빈도 컨트롤 서랍(⋯) 토글 ──────────────────────────
function toggleMainChartMore(btn){
  var row = document.getElementById('mainChartMoreRow');
  if(!row) return;
  var open = row.style.display === 'none';
  row.style.display = open ? 'flex' : 'none';
  btn.setAttribute('aria-expanded', String(open));
}

window.addEventListener('load', () => {
  try { applyHomeLayout(); } catch(_) {}
  try { initHomeDnd(); } catch(_) {}
  try { initWidgetCollapse(); } catch(_) {}   // Phase 3 — 위젯 접기
  try { buildPageTocs(); } catch(_) {}        // Phase 3 — 페이지 목차 칩
  try { initGlobalDelayChip(); } catch(_) {}
  // data.json 이 이미 적용된 경우(applyRealData 가 먼저 돈 경우) 비교 차트 즉시 초기화
  try { initCompareTool(); } catch(_) {}
  // 📌 브리핑 스트립 — 데이터 도착 전에도 '다음 일정' 칩은 정적 calEvents 로 선표시
  try { renderBriefStrip(_latestDataForIndicators || {}); } catch(_) {}
  try { renderRiskLight(_latestDataForIndicators); } catch(_) {}
  try { updateAiQaVisibility(); } catch(_) {}
});
