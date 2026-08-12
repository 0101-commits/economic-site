/* ============================================================================
 * 투자 현황 (가상 포트폴리오 + 카카오 알림 설정)
 * ----------------------------------------------------------------------------
 * - 지정 종목 트래킹: 한국(6자리 코드)은 네이버 모바일 API, 미국 티커는 Yahoo 차트 API.
 *   모두 전용 Cloudflare Worker 프록시(_fetchViaProxies/_fetchJsonWithProxies) 경유 — CORS 안전.
 * - 가상 포트폴리오: 평단가·수량은 localStorage 에만 저장(서버 전송 없음). 해외 종목은
 *   USD/KRW 환율로 원화 환산해 총 평가금액·손익·비중(파이)을 계산한다.
 * - 상세 차트: TradingView Lightweight Charts(오픈소스) 캔들 + 거래량 + MA/RSI/MACD 토글.
 * - 카카오 알림: 조건(가격/등락률/52주/거래량/골든·데드크로스)을 Worker 의 POST /portfolio 로
 *   저장소 alerts_config.json 에 커밋 → GitHub Actions(stock-alerts.yml)가 장중 5분마다
 *   scripts/check_alerts.py 로 평가해 카카오톡 발송. 도배 방지(하루 1회/1시간 쿨다운) 포함.
 * ============================================================================ */

const PF_LS_KEY = 'portfolioV1';
let pfState = null;            // {groups, items, alerts, lastSync}
let pfActiveGroup = 'all';
let pfQuotes = {};             // symbol → {price, pct, prevClose, name, secType, ccy, ts}
let pfPieMode = 'item';
let pfPieChart = null;
let pfPendingAdd = null;       // 조회 성공한 추가 후보
let pfTimer = null;
let _pfInited = false;

function pfEsc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function pfLoad() {
  try {
    const j = JSON.parse(localStorage.getItem(PF_LS_KEY) || 'null');
    if(j && Array.isArray(j.items)) {
      if(!Array.isArray(j.groups) || !j.groups.length) j.groups = [{id:'g_default', name:'기본 그룹'}];
      if(!Array.isArray(j.alerts)) j.alerts = [];
      return j;
    }
  } catch(_) {}
  return { groups:[{id:'g_default', name:'기본 그룹'}], items:[], alerts:[], lastSync:null };
}
// 실패 여부를 남긴다 — 시크릿 모드/quota 초과 시 setItem 이 throw 하는데 무음 처리하면
// pfMarkDirty 가 '✓ 자동 저장됨'을 표시해 수기 입력(평단가·수량)이 소리 없이 사라진다.
function pfSave() {
  try { localStorage.setItem(PF_LS_KEY, JSON.stringify(pfState)); window._pfSaveFailed = false; return true; }
  catch(_) { window._pfSaveFailed = true; return false; }
}

// ── 저장 상태 추적 ('자동 저장됨' 확인 + 서버 미저장 경고) ─────────────────────
// 평단가·수량·종목·그룹 등 수기 입력은 pfSave() 로 이 브라우저(localStorage)에 즉시 자동 저장된다.
// 그 사실을 사용자에게 보여주고(자동 저장됨), 다른 기기 반영(서버 「목록 저장」)을 까먹지 않도록
// 변경이 생기면 _pfDirty 로 표시 → 상태줄 안내 + 페이지 이탈/새로고침 시 경고창을 띄운다.
let _pfDirty = false;
function pfHasSyncKey() {
  try { return !!(localStorage.getItem('pfSyncKeyHash') || localStorage.getItem('pfSyncKey')); } catch(_) { return false; }
}
// (구) pfMarkDirty 정의 삭제 — 아래쪽 정의가 호이스팅으로 항상 이겨 이 코드는 죽은
// 코드였고, 그 바람에 _pfDirty(이탈 경고 플래그)가 어디서도 켜지지 않았다(2026-08 감사).
function pfClearDirty() { _pfDirty = false; }
// 포트폴리오 페이지를 떠나거나 탭을 닫을 때, 서버에 저장하지 않은 변경이 있으면 저장을 물어본다.
function pfWarnUnsavedOnLeave() {
  if(!_pfDirty || !pfHasSyncKey()) return;
  if(confirm('지정 종목 트래킹에 저장하지 않은 변경이 있습니다. 지금 서버에 「목록 저장」할까요?')) {
    try { pfSyncTracking(); } catch(_) {}
  }
  _pfDirty = false;   // 한 번 물었으면(저장/취소 무관) 같은 이동에서 반복해 묻지 않는다
}

// ── 환율 (해외 종목 원화 환산) ──────────────────────────────────────────────
function pfUsdKrw() {
  const r = (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators &&
             _latestDataForIndicators.fx && _latestDataForIndicators.fx.USDKRW) ?
            _latestDataForIndicators.fx.USDKRW.rate : null;
  return (r && isFinite(r) && r > 0) ? +r : (window._pfUsdKrw || null);
}
async function pfEnsureUsdKrw() {
  if(pfUsdKrw()) return;
  try {
    const q = await fetchYahooQuote('KRW=X');
    if(q && q.price > 0) window._pfUsdKrw = q.price;
  } catch(_) {}
}

// ── 시세 조회 ────────────────────────────────────────────────────────────────
// 한국: 네이버 모바일 API(stockName/closePrice/fluctuationsRatio/stockEndType) → 실패 시 Yahoo .KS/.KQ
async function pfFetchQuoteKR(code) {
  try {
    const j = await _fetchViaProxies(`https://m.stock.naver.com/api/stock/${code}/basic`);
    const price = j && parseFloat(String(j.closePrice || '').replace(/,/g, ''));
    if(price && isFinite(price) && price > 0) {
      const pct = parseFloat(String(j.fluctuationsRatio || '').replace(/,/g, '')) || 0;
      const prev = price / (1 + pct / 100);
      return { price, pct, prevClose: prev, name: j.stockName || code,
               secType: (String(j.stockEndType || '').toLowerCase() === 'etf') ? 'etf' : 'stock', ccy: 'KRW' };
    }
  } catch(_) {}
  for(const suf of ['.KS', '.KQ']) {
    const q = await pfFetchQuoteYahoo(code + suf);
    if(q) return Object.assign(q, { ccy: 'KRW' });
  }
  return null;
}
async function pfFetchQuoteYahoo(symbol) {
  try {
    const j = await _fetchJsonWithProxies('https://query1.finance.yahoo.com/v8/finance/chart/' +
                                          encodeURIComponent(symbol) + '?range=1d&interval=5m');
    const meta = j && j.chart && j.chart.result && j.chart.result[0] && j.chart.result[0].meta;
    if(!meta || meta.regularMarketPrice == null) return null;
    const price = +meta.regularMarketPrice;
    const prev  = (meta.chartPreviousClose != null) ? +meta.chartPreviousClose : +meta.previousClose;
    if(!isFinite(price) || price <= 0) return null;
    const pct = (prev && prev > 0) ? ((price - prev) / prev) * 100 : 0;
    return { price, pct, prevClose: prev || null, name: meta.shortName || meta.longName || symbol,
             secType: null, ccy: (meta.currency === 'KRW' ? 'KRW' : 'USD') };
  } catch(_) { return null; }
}
async function pfFetchQuote(item) {
  if(item.market === 'KR') {
    const q = await pfFetchQuoteKR(item.symbol);
    if(q && !q.secType) q.secType = item.secType || 'stock';
    return q;
  }
  const q = await pfFetchQuoteYahoo(item.yahoo || item.symbol);
  if(q) q.secType = item.secType || 'stock';
  return q;
}
async function pfRefreshQuotes(manual) {
  if(!pfState || !pfState.items.length) { pfRenderAll(); return; }
  const el = document.getElementById('pfQuoteTs');
  if(manual && el) { el.textContent = '갱신 중…'; el.style.color = '#7a8099'; }
  await pfEnsureUsdKrw();
  let ok = 0, fail = 0;
  await Promise.all(pfState.items.map(async it => {
    const q = await pfFetchQuote(it).catch(() => null);
    if(q) {
      ok++;
      q.ts = Date.now();
      pfQuotes[it.id] = q;
      // 종목명·유형 보강(최초 추가 시 비어있을 수 있음)
      if(q.name && (!it.name || it.name === it.symbol)) it.name = q.name;
      if(q.secType && !it.secType) it.secType = q.secType;
    } else { fail++; }
  }));
  pfSave();
  if(el) {
    const ts = new Date().toLocaleTimeString('ko-KR', {hour:'2-digit', minute:'2-digit', hour12:false});
    // 전 종목 시세 실패 → 화면의 현재가는 이전 캐시값이므로 '최신'으로 오인하지 않게 오류를 명시한다.
    // (대개 전용 Worker 프록시 장애·네트워크 차단. 일부만 실패하면 실패 종목 수만 덧붙인다.)
    if(ok === 0) { el.textContent = '시세 응답 오류 · ' + ts + ' 기준(이전 값 표시)'; el.style.color = window.CDN; }
    else { el.textContent = '시세 ' + ts + ' 기준' + (fail ? ' · ' + fail + '종목 응답 없음' : ''); el.style.color = fail ? '#f0c75e' : '#7a8099'; }
  }
  pfRenderAll();
}

// ── 종목 검색/추가 ────────────────────────────────────────────────────────────
// 한국 종목명 검색 (네이버 자동완성 — 한글 입력 시). 응답 구조 변화에 견디도록 재귀 파싱.
async function pfSearchKrByName(query) {
  const j = await _fetchViaProxies('https://m.stock.naver.com/front-api/search/autoComplete?query=' +
                                   encodeURIComponent(query) + '&target=stock');
  const out = [], seen = {};
  const walk = node => {
    if(!node || out.length >= 20) return;
    if(Array.isArray(node)) { node.forEach(walk); return; }
    if(typeof node === 'object') {
      const code = node.code || node.itemCode || node.cd;
      const name = node.name || node.itemName || node.nm;
      if(typeof code === 'string' && /^\d[0-9A-Z]{5}$/.test(code) && typeof name === 'string' && !seen[code]) {
        seen[code] = 1; out.push({ code, name });
      } else { Object.keys(node).forEach(k => walk(node[k])); }
    }
  };
  walk(j);
  return out;
}
function pfNormName(s) { return String(s || '').replace(/[\s&＆]/g, '').toUpperCase(); }
function pfBestNameMatch(hits, query) {
  const q = pfNormName(query);
  return hits.find(h => pfNormName(h.name) === q) ||
         hits.find(h => pfNormName(h.name).indexOf(q) === 0) ||
         hits.find(h => pfNormName(h.name).indexOf(q) >= 0) || hits[0] || null;
}
// KR 코드 선택(검색 결과 클릭) → 시세 확인 후 추가 필드 표시
async function pfPickKr(code, name) {
  const out = document.getElementById('pfLookupResult');
  out.textContent = '조회 중…';
  const q = await pfFetchQuoteKR(code);
  if(!q) { out.textContent = '시세를 가져올 수 없습니다: ' + code; return; }
  // 알림 체커(check_alerts.py)·상세차트용 Yahoo 심볼(.KS/.KQ) 사전 해석 (신규 상장은 없을 수 있음)
  let yahoo = null;
  for(const suf of ['.KS', '.KQ']) {
    if(await pfFetchQuoteYahoo(code + suf)) { yahoo = code + suf; break; }
  }
  pfPendingAdd = { symbol: code, market: 'KR', yahoo, name: q.name || name || code, secType: q.secType || 'stock', ccy: 'KRW' };
  out.innerHTML = `✓ <b style="color:var(--c-txt);">${pfEsc(pfPendingAdd.name)}</b> (${code}, ${pfPendingAdd.secType === 'etf' ? 'ETF' : '주식'}) — 현재가 ${q.price.toLocaleString()}원`;
  document.getElementById('pfAddFields').style.display = 'flex';
  pfFillGroupSelect(document.getElementById('pfAddGroup'));
}
async function pfLookupSymbol() {
  const inp = document.getElementById('pfSymbolInput');
  const out = document.getElementById('pfLookupResult');
  const fields = document.getElementById('pfAddFields');
  const rawIn = (inp.value || '').trim();
  const raw = rawIn.toUpperCase();
  pfPendingAdd = null; fields.style.display = 'none';
  if(!raw) { out.textContent = '종목 코드/티커 또는 한글 종목명을 입력하세요.'; return; }
  out.textContent = '조회 중…';
  try {
    if(/^\d[0-9A-Z]{5}$/.test(raw)) {               // 한국 주식/ETF (6자리 코드 — 신형 영문 포함)
      await pfPickKr(raw, null);
    } else if(/[가-힣]/.test(rawIn)) {              // 한글 종목명 검색
      const hits = await pfSearchKrByName(rawIn);
      if(!hits.length) { out.textContent = '검색 결과가 없습니다: ' + rawIn; return; }
      out.innerHTML = '아래에서 종목을 선택하세요:<br>' + hits.slice(0, 6).map(h =>
        `<button onclick="pfPickKr('${h.code}',${JSON.stringify(h.name).replace(/"/g,'&quot;')})" style="margin:3px 4px 0 0;background:var(--c-card);border:1px solid var(--c-border);border-radius:var(--r-xs);color:var(--c-primary);font-size:var(--font-size-sm);padding:3px 8px;cursor:pointer;">${pfEsc(h.name)} <span style="color:var(--c-txt-muted);">${h.code}</span></button>`).join('');
    } else if(/^[A-Z][A-Z0-9.\-^=]{0,11}$/.test(raw)) {   // 미국 티커
      let name = null, secType = 'stock';
      try {
        const s = await _fetchJsonWithProxies('https://query1.finance.yahoo.com/v1/finance/search?q=' +
                                              encodeURIComponent(raw) + '&quotesCount=5&newsCount=0');
        const hit = s && Array.isArray(s.quotes) &&
          (s.quotes.find(x => x.symbol === raw) || s.quotes.find(x => x.quoteType === 'EQUITY' || x.quoteType === 'ETF'));
        if(hit) { name = hit.shortname || hit.longname || null; if(hit.quoteType === 'ETF') secType = 'etf'; }
      } catch(_) {}
      const q = await pfFetchQuoteYahoo(raw);
      if(!q) { out.textContent = '종목을 찾을 수 없습니다: ' + raw; return; }
      pfPendingAdd = { symbol: raw, market: 'US', yahoo: raw, name: name || q.name || raw, secType, ccy: 'USD' };
      out.innerHTML = `✓ <b style="color:var(--c-txt);">${pfEsc(pfPendingAdd.name)}</b> (${raw}, ${secType === 'etf' ? 'ETF' : '주식'}) — 현재가 $${q.price.toLocaleString()}`;
      fields.style.display = 'flex';
      pfFillGroupSelect(document.getElementById('pfAddGroup'));
    } else {
      out.textContent = '형식 오류 — 한국 6자리 코드(005930) / 미국 티커(AAPL) / 한글 종목명으로 입력하세요.';
    }
  } catch(e) { out.textContent = '조회 실패 — 잠시 후 다시 시도하세요.'; }
}

// ── 초기 보유 종목 시드 — 사용자 보유 ETF 9종을 첫 방문 시 자동 등록 ──
// (코드는 신규 상장 ETF 라 하드코딩 대신 네이버 검색으로 런타임 해석 — 코드 변경/오타 위험 제거)
const PF_SEED_NAMES = [
  'RISE 미국양자컴퓨팅', 'SOL 미국원자력SMR', 'RISE AI반도체TOP10',
  'TIGER 미국S&P500', 'PLUS 글로벌희토류&전략자원생산기업', 'SOL 조선TOP3플러스',
  'RISE 버크셔포트폴리오TOP10', 'SOL 미국AI전력인프라', 'SOL K방산',
];
async function pfSeedDefaults() {
  pfState.seeded = true;
  pfState.groups[0].name = '내 보유 ETF';
  const out = document.getElementById('pfLookupResult');
  if(out) out.textContent = '보유 ETF 자동 등록 중… (' + PF_SEED_NAMES.length + '종목)';
  for(const nm of PF_SEED_NAMES) {
    try {
      const hit = pfBestNameMatch(await pfSearchKrByName(nm), nm);
      if(!hit || pfState.items.some(it => it.symbol === hit.code && it.market === 'KR')) continue;
      pfState.items.push({
        id: 'i' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
        symbol: hit.code, market: 'KR', yahoo: null, name: hit.name,
        secType: 'etf', ccy: 'KRW', avg: null, qty: null, group: pfState.groups[0].id,
      });
    } catch(_) { /* 미등록 종목은 직접 검색으로 추가 가능 */ }
  }
  pfSave();
  if(out) out.textContent = pfState.items.length ?
    `보유 ETF ${pfState.items.length}종목 자동 등록 완료 — 평단가·수량을 입력하세요.` :
    '자동 등록 실패 — 종목명으로 직접 검색해 추가하세요.';
  pfRenderAll();
  pfRefreshQuotes();
}
function pfAddItem() {
  if(!pfPendingAdd) return;
  if(pfState.items.some(it => it.symbol === pfPendingAdd.symbol && it.market === pfPendingAdd.market)) {
    document.getElementById('pfLookupResult').textContent = '이미 추가된 종목입니다.';
    return;
  }
  // 인라인 유효성 검사 (3.2) — 음수/문자 입력 시 해당 칸을 표시하고 추가 중단
  const avgEl = document.getElementById('pfAddAvg'), qtyEl = document.getElementById('pfAddQty');
  let invalid = false;
  [avgEl, qtyEl].forEach(el => {
    el.classList.remove('pf-input-err');
    const raw = (el.value || '').trim();
    if(raw !== '' && (!isFinite(parseFloat(raw)) || parseFloat(raw) < 0)) {
      el.classList.add('pf-input-err'); invalid = true;
    }
  });
  if(invalid) {
    document.getElementById('pfLookupResult').textContent = '평단가/수량에는 0 이상의 숫자만 입력할 수 있습니다.';
    return;
  }
  const avg = parseFloat(avgEl.value);
  const qty = parseFloat(qtyEl.value);
  const grp = document.getElementById('pfAddGroup').value || pfState.groups[0].id;
  const avgVal = (isFinite(avg) && avg > 0) ? avg : null;
  pfState.items.push(Object.assign({}, pfPendingAdd, {
    id: 'i' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    avg: avgVal,
    qty: (isFinite(qty) && qty > 0) ? qty : null,
    group: grp,
    // 미국(USD) 종목은 추가 시점 환율을 매입환율로 캡처 (환차손익 분리 기준)
    fxBuy: (pfPendingAdd.ccy === 'USD' && avgVal != null) ? (pfUsdKrw() || null) : null,
  }));
  pfPendingAdd = null;
  document.getElementById('pfSymbolInput').value = '';
  document.getElementById('pfAddAvg').value = '';
  document.getElementById('pfAddQty').value = '';
  document.getElementById('pfAddFields').style.display = 'none';
  document.getElementById('pfLookupResult').textContent = '추가되었습니다.';
  pfSave();
  pfMarkDirty();
  pfRefreshQuotes();
}
function pfDeleteItem(id) {
  const it = pfState.items.find(x => x.id === id);
  if(!it) return;
  if(!confirm(`'${it.name || it.symbol}' 종목을 삭제할까요? 이 종목의 알림 조건도 함께 삭제됩니다.`)) return;
  pfState.items = pfState.items.filter(x => x.id !== id);
  pfState.alerts = pfState.alerts.filter(a => !(a.symbol === it.symbol && a.market === it.market));
  delete pfQuotes[id];
  pfSave(); pfMarkDirty(); pfRenderAll();
}
function pfUpdateItemField(id, field, value, inputEl) {
  const it = pfState.items.find(x => x.id === id);
  if(!it) return;
  if(field === 'group') { it.group = value; }
  else {
    const raw = String(value == null ? '' : value).trim();
    if(raw !== '') {
      const v = parseFloat(raw.replace(/,/g, ''));
      // 인라인 유효성 검사 (3.2) — 문자열/음수 등 비정상 입력은 저장하지 않고 즉시 표시해
      // localStorage 데이터 꼬임을 방지한다.
      if(!isFinite(v) || v < 0 || !/^[\d.,]+$/.test(raw.replace(/\s/g, ''))) {
        if(inputEl) {
          inputEl.classList.add('pf-input-err');
          inputEl.title = '0 이상의 숫자만 입력할 수 있습니다.';
          inputEl.value = it[field] != null ? it[field] : '';
          setTimeout(() => { try { inputEl.classList.remove('pf-input-err'); inputEl.title = ''; } catch(_) {} }, 2500);
        }
        if(typeof showToast === 'function') showToast(`${field === 'avg' ? '평단가' : '수량'}에는 0 이상의 숫자만 입력할 수 있습니다. 변경이 저장되지 않았습니다.`, 4000);
        return;
      }
      it[field] = v > 0 ? v : null;
    } else {
      it[field] = null;
    }
    if(inputEl) { inputEl.classList.remove('pf-input-err'); inputEl.title = ''; }
    // 미국(USD) 종목 평단가 입력 시 현재 환율을 '매입환율'로 캡처 — 환차손익/주가손익 분리 기준
    if(field === 'avg') {
      const usd = it.market === 'US' || (pfQuotes[it.id] && pfQuotes[it.id].ccy === 'USD');
      if(usd) it.fxBuy = (it.avg != null) ? (it.fxBuy || pfUsdKrw() || null) : null;
    }
  }
  pfSave(); pfMarkDirty(); pfRenderSummary(); pfRenderPie();
  // 그룹 변경 → 표 재렌더(표가 카드까지 동기화). 평단가/수량 변경 → 모바일 카드(평가손익) 갱신.
  // 데스크탑에선 pfRenderCards 가 즉시 return 하므로 입력 포커스에 영향 없음.
  if(field === 'group') pfRenderTable();
  else if (typeof pfRenderCards === 'function') pfRenderCards();
}

// ── 그룹(폴더) 관리 ──────────────────────────────────────────────────────────
function pfAddGroup() {
  const name = (prompt('새 그룹 이름을 입력하세요. (예: 배당주, 채권 ETF)') || '').trim();
  if(!name) return;
  pfState.groups.push({ id: 'g' + Date.now().toString(36), name: name.slice(0, 20) });
  pfSave(); pfMarkDirty(); pfRenderGroups();
}
function pfRenameGroup(id) {
  const g = pfState.groups.find(x => x.id === id);
  if(!g) return;
  const name = (prompt('그룹 이름 변경:', g.name) || '').trim();
  if(!name) return;
  g.name = name.slice(0, 20);
  pfSave(); pfMarkDirty(); pfRenderGroups(); pfRenderTable();
}
function pfDeleteGroup(id) {
  if(pfState.groups.length <= 1) { alert('그룹은 최소 1개가 필요합니다.'); return; }
  const g = pfState.groups.find(x => x.id === id);
  if(!g || !confirm(`'${g.name}' 그룹을 삭제할까요? 소속 종목은 첫 번째 그룹으로 이동합니다.`)) return;
  pfState.groups = pfState.groups.filter(x => x.id !== id);
  const fallback = pfState.groups[0].id;
  pfState.items.forEach(it => { if(it.group === id) it.group = fallback; });
  if(pfActiveGroup === id) pfActiveGroup = 'all';
  pfSave(); pfMarkDirty(); pfRenderGroups(); pfRenderTable(); pfRenderSummary(); pfRenderPie();
}
function pfSetActiveGroup(id) { pfActiveGroup = id; pfRenderGroups(); pfRenderTable(); pfRenderSummary(); pfRenderPie(); }
function pfFillGroupSelect(sel, selected) {
  if(!sel) return;
  sel.innerHTML = pfState.groups.map(g =>
    `<option value="${g.id}"${g.id === selected ? ' selected' : ''}>${pfEsc(g.name)}</option>`).join('');
}
function pfRenderGroups() {
  const el = document.getElementById('pfGroupTabs');
  if(!el) return;
  const btn = (id, label, extra) => {
    const on = pfActiveGroup === id;
    return `<button class="tab-btn" onclick="pfSetActiveGroup('${id}')" style="font-size:var(--font-size-sm);padding:3px 10px;border:1px solid var(--c-border);border-radius:var(--r-xs);cursor:pointer;background:${on ? 'var(--c-accent)' : 'transparent'};color:${on ? '#fff' : 'var(--c-txt-dim)'};">${label}</button>${extra || ''}`;
  };
  let html = btn('all', '전체');
  pfState.groups.forEach(g => {
    const n = pfState.items.filter(it => it.group === g.id).length;
    let extra = '';
    if(pfActiveGroup === g.id) {
      extra = `<button onclick="pfRenameGroup('${g.id}')" title="이름 변경" style="background:transparent;border:none;color:var(--c-txt-dim);cursor:pointer;font-size:var(--font-size-sm);padding:2px;">✎</button>` +
              `<button onclick="pfDeleteGroup('${g.id}')" title="그룹 삭제" style="background:transparent;border:none;color:var(--c-txt-dim);cursor:pointer;font-size:var(--font-size-sm);padding:2px;">🗑</button>`;
    }
    html += btn(g.id, `${pfEsc(g.name)} <span style="opacity:.7;">${n}</span>`, extra);
  });
  html += `<button onclick="pfAddGroup()" title="그룹 추가" style="font-size:var(--font-size-sm);padding:3px 10px;border:1px dashed var(--c-border);border-radius:var(--r-xs);background:transparent;color:var(--c-txt-dim);cursor:pointer;">＋ 그룹</button>`;
  el.innerHTML = html;
}

// ── 표 렌더링 ────────────────────────────────────────────────────────────────
function pfFmtPrice(v, ccy, nd) {
  if(v == null || !isFinite(v)) return '-';
  if(ccy === 'USD') return '$' + (+v).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
  const d = (nd != null) ? nd : (v < 1000 ? 1 : 0);
  return (+v).toLocaleString('ko-KR', {minimumFractionDigits:d, maximumFractionDigits:d}) + '원';
}
function pfFmtKrw(v) {
  if(v == null || !isFinite(v)) return '-';
  return (v < 0 ? '-' : '') + '₩' + Math.abs(Math.round(v)).toLocaleString('ko-KR');
}
function pfChgHtml(pct) {
  if(pct == null || !isFinite(pct)) return '<span style="color:var(--c-txt-muted);">-</span>';
  const cls = pct >= 0 ? 'up-txt' : 'down-txt';
  return `<span class="${cls}">${pct >= 0 ? '▲' : '▼'} ${Math.abs(pct).toFixed(2)}%</span>`;
}
function pfItemKrwValue(it) {
  // 평가 금액(원화 환산) — 시세 없으면 null
  const q = pfQuotes[it.id];
  if(!q || !it.qty) return null;
  let v = q.price * it.qty;
  if(q.ccy === 'USD') {
    const fx = pfUsdKrw();
    if(!fx) return null;
    v *= fx;
  }
  return v;
}
function pfVisibleItems() {
  return pfState.items.filter(it => pfActiveGroup === 'all' || it.group === pfActiveGroup);
}
function pfRenderTable() {
  const body = document.getElementById('pfTableBody');
  if(!body) return;
  const items = pfVisibleItems();
  if(!items.length) {
    body.innerHTML = '<tr><td colspan="9" style="padding:18px;text-align:center;color:var(--c-txt-muted);">' +
      (pfState.items.length ? '이 그룹에 종목이 없습니다.' : '종목 코드를 조회해 추가하세요. (한국 6자리 코드 / 미국 티커)') + '</td></tr>';
    if (typeof pfRenderCards === 'function') pfRenderCards();  // 모바일 카드 뷰도 빈 상태로 동기화
    return;
  }
  const fx = pfUsdKrw();
  body.innerHTML = items.map(it => {
    const q = pfQuotes[it.id];
    const alerts = pfState.alerts.filter(a => a.symbol === it.symbol && a.market === it.market);
    const evalNative = (q && it.qty) ? q.price * it.qty : null;
    const evalKrw = pfItemKrwValue(it);
    let pnlHtml = '<span style="color:var(--c-txt-muted);">-</span>';
    if(q && it.avg && it.qty) {
      const pnlNative = (q.price - it.avg) * it.qty;
      const pnlPct = (q.price / it.avg - 1) * 100;
      const pnlKrw = (q.ccy === 'USD') ? (fx ? pnlNative * fx : null) : pnlNative;
      const cls = pnlNative >= 0 ? 'up-txt' : 'down-txt';
      // 미국 종목 — 주가손익/환차손익 분리 (3.2). 매입환율(fxBuy)이 기록된 경우에만 가능.
      let splitTitle = '';
      if(q.ccy === 'USD' && fx && it.fxBuy) {
        const fxPnl = it.avg * it.qty * (fx - it.fxBuy);
        splitTitle = ` title="주가손익 ${pfFmtKrw(pnlNative * fx)} · 환차손익 ${pfFmtKrw(fxPnl)} (매입환율 ${it.fxBuy.toFixed(1)} → 현재 ${fx.toFixed(1)})"`;
      }
      pnlHtml = `<span class="${cls}"${splitTitle}>${pnlKrw != null ? (pnlNative >= 0 ? '+' : '') + pfFmtKrw(pnlKrw).replace('₩', '₩') : '-'}<br>` +
                `${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%${splitTitle ? ' <span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">⇄FX</span>' : ''}</span>`;
    }
    const groupSel = `<select onchange="pfUpdateItemField('${it.id}','group',this.value)" onclick="event.stopPropagation()" style="background:var(--c-bg);border:1px solid var(--c-border);border-radius:var(--r-xs);color:var(--c-txt-dim);padding:2px 4px;font-size:var(--font-size-sm);max-width:90px;">` +
      pfState.groups.map(g => `<option value="${g.id}"${g.id === it.group ? ' selected' : ''}>${pfEsc(g.name)}</option>`).join('') + '</select>';
    return `<tr class="hoverable-row" onclick="pfOpenChart('${it.id}')" style="border-bottom:1px solid #1f2430;cursor:pointer;text-align:right;">
      <td style="text-align:left;padding:7px 4px;">
        <span style="color:var(--c-txt);font-weight:var(--font-weight-semibold);">${pfEsc(it.name || it.symbol)}</span>
        <span style="color:var(--c-txt-muted);font-size:var(--font-size-xs);margin-left:4px;">${pfEsc(it.symbol)} · ${it.market === 'KR' ? (it.secType === 'etf' ? 'ETF' : '주식') : (it.secType === 'etf' ? '미국 ETF' : '미국 주식')}</span>
      </td>
      <td style="padding:7px 4px;font-family:var(--font-num);color:var(--c-txt);">${q ? pfFmtPrice(q.price, q.ccy) : '<span style="color:var(--c-txt-muted);">로딩…</span>'}</td>
      <td style="padding:7px 4px;">${q ? pfChgHtml(q.pct) : '-'}</td>
      <td style="padding:7px 4px;" onclick="event.stopPropagation()"><input type="number" step="any" min="0" value="${it.avg != null ? it.avg : ''}" placeholder="-" onchange="pfUpdateItemField('${it.id}','avg',this.value,this)" style="width:90px;background:var(--c-bg);border:1px solid var(--c-border);border-radius:var(--r-xs);color:var(--c-txt);padding:3px 5px;font-size:var(--font-size-sm);text-align:right;"></td>
      <td style="padding:7px 4px;" onclick="event.stopPropagation()"><input type="number" step="any" min="0" value="${it.qty != null ? it.qty : ''}" placeholder="-" onchange="pfUpdateItemField('${it.id}','qty',this.value,this)" style="width:70px;background:var(--c-bg);border:1px solid var(--c-border);border-radius:var(--r-xs);color:var(--c-txt);padding:3px 5px;font-size:var(--font-size-sm);text-align:right;"></td>
      <td style="padding:7px 4px;font-family:var(--font-num);color:var(--c-txt);">${evalNative != null ? pfFmtPrice(evalNative, q.ccy) : '-'}${(evalKrw != null && q && q.ccy === 'USD') ? `<br><span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">${pfFmtKrw(evalKrw)}</span>` : ''}</td>
      <td style="padding:7px 4px;font-size:var(--font-size-sm);">${pnlHtml}</td>
      <td style="padding:7px 4px;text-align:center;">${groupSel}</td>
      <td style="padding:7px 4px;text-align:center;white-space:nowrap;" onclick="event.stopPropagation()">
        <button onclick="pfOpenAlerts('${it.id}')" title="카카오 알림 설정" style="background:transparent;border:none;cursor:pointer;font-size:var(--font-size-base);">${alerts.length ? '🔔' : '🕭'}</button><span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">${alerts.length || ''}</span>
        <button onclick="pfDeleteItem('${it.id}')" title="삭제" style="background:transparent;border:none;cursor:pointer;font-size:var(--font-size-base);color:var(--c-txt-dim);">🗑</button>
      </td>
    </tr>`;
  }).join('');
  // 모바일 카드 뷰(#pfCardList)도 같은 데이터로 항상 동기화 — 표만 갱신되고 카드는 stale 되던 버그 차단.
  if (typeof pfRenderCards === 'function') pfRenderCards();
}

// ── 요약 KPI + 파이 차트 ────────────────────────────────────────────────────
function pfRenderSummary() {
  const items = pfVisibleItems().filter(it => it.qty && pfQuotes[it.id]);
  const fx = pfUsdKrw();
  let evalKrw = 0, costKrw = 0, missingFx = false, counted = 0;
  let fxPnlKrw = 0, hasFxSplit = false;   // 환차손익 분리 (3.2) — 매입환율 기록된 USD 종목
  items.forEach(it => {
    const q = pfQuotes[it.id];
    const mul = (q.ccy === 'USD') ? fx : 1;
    if(q.ccy === 'USD' && !fx) { missingFx = true; return; }
    evalKrw += q.price * it.qty * mul;
    if(it.avg) {
      // 매입환율(fxBuy)이 있으면 매입 원가를 매입 시점 환율로 환산 → 평가손익에 환차가 포함되고,
      // 그 환차분(fxPnl)을 분리 표기한다. 없으면(과거 데이터) 현재 환율 폴백.
      const costMul = (q.ccy === 'USD') ? (it.fxBuy || fx) : 1;
      costKrw += it.avg * it.qty * costMul;
      if(q.ccy === 'USD' && it.fxBuy) { fxPnlKrw += it.avg * it.qty * (fx - it.fxBuy); hasFxSplit = true; }
    }
    counted++;
  });
  const set = (id, txt, cls) => {
    const el = document.getElementById(id);
    if(el) { el.textContent = txt; el.className = cls || ''; }
  };
  if(!counted) {
    set('pfKpiEval', '-'); set('pfKpiCost', '-'); set('pfKpiPnl', '-'); set('pfKpiPct', '-');
    const sub = document.getElementById('pfKpiEvalSub');
    if(sub) sub.textContent = '평단가·수량 입력 시 자동 계산';
    return;
  }
  set('pfKpiEval', pfFmtKrw(evalKrw));
  const sub = document.getElementById('pfKpiEvalSub');
  if(sub) sub.textContent = `${counted}개 종목` + (missingFx ? ' · 환율 로딩 중(달러 종목 제외)' : (fx ? ` · 환율 ${fx.toFixed(1)}원` : ''));
  set('pfKpiCost', costKrw ? pfFmtKrw(costKrw) : '-');
  if(costKrw > 0) {
    const pnl = evalKrw - costKrw, pct = (evalKrw / costKrw - 1) * 100;
    const cls = pnl >= 0 ? 'up-txt' : 'down-txt';
    const elP = document.getElementById('pfKpiPnl');
    if(elP) { elP.textContent = (pnl >= 0 ? '+' : '') + pfFmtKrw(pnl).replace('₩', '₩'); elP.classList.remove('up-txt','down-txt'); elP.classList.add(cls); }
    const elQ = document.getElementById('pfKpiPct');
    if(elQ) { elQ.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%'; elQ.classList.remove('up-txt','down-txt'); elQ.classList.add(cls); }
    const subP = document.getElementById('pfKpiPnlSub');
    if(subP) subP.textContent = hasFxSplit
      ? `주가 ${pfFmtKrw(pnl - fxPnlKrw)} · 환차 ${pfFmtKrw(fxPnlKrw)}`
      : '평단가 입력 종목 기준';
  } else {
    set('pfKpiPnl', '-'); set('pfKpiPct', '-');
  }
}
// 포트폴리오 파이 팔레트 — astryx 카테고리 9색.
// getter 인 이유: 상수로 굳히면 테마를 바꿔도 옛 테마 색이 남는다
// (기존 정의가 window.CUP 을 로드 시점에 캡처하던 게 정확히 그 버그였다).
// 등락색은 넣지 않는다 — 조각 색이 상승/하락을 뜻하는 것처럼 읽힌다.
Object.defineProperty(window, 'PF_PIE_COLORS', {
  configurable: true,
  get() { return getThemeColors().series; },
});
function pfSetPieMode(mode, btn) {
  pfPieMode = mode;
  document.querySelectorAll('#pfPieModeItem,#pfPieModeType').forEach(b => {
    const on = b === btn;
    b.style.background = on ? getThemeColors().accent : 'transparent';
    b.style.color = on ? '#fff' : '#8d90a2';
  });
  pfRenderPie();
}
function pfRenderPie() {
  const cv = document.getElementById('pfPieCanvas');
  const empty = document.getElementById('pfPieEmpty');
  if(!cv) return;
  const rows = [];
  pfVisibleItems().forEach(it => {
    const v = pfItemKrwValue(it);
    if(v && v > 0) rows.push({ label: it.name || it.symbol, type: it.secType === 'etf' ? 'ETF' : '주식', v });
  });
  if(!rows.length) {
    cv.style.display = 'none';
    if(empty) empty.style.display = 'block';
    if(pfPieChart) { pfPieChart.destroy(); pfPieChart = null; }
    return;
  }
  cv.style.display = 'block';
  if(empty) empty.style.display = 'none';
  let labels, values;
  if(pfPieMode === 'type') {
    const agg = {};
    rows.forEach(r => { agg[r.type] = (agg[r.type] || 0) + r.v; });
    labels = Object.keys(agg); values = labels.map(k => agg[k]);
  } else {
    rows.sort((a, b) => b.v - a.v);
    labels = rows.map(r => r.label); values = rows.map(r => r.v);
  }
  const total = values.reduce((s, x) => s + x, 0);
  if(pfPieChart) pfPieChart.destroy();
  pfPieChart = new Chart(cv.getContext('2d'), {
    type: 'doughnut',
    data: { labels, datasets: [{ data: values, backgroundColor: labels.map((_, i) => PF_PIE_COLORS[i % PF_PIE_COLORS.length]), borderWidth: 0 }] },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '55%',
      plugins: {
        legend: { position: 'bottom', labels: { color: '#a4a8bc', font: { size: 10 }, boxWidth: 10,
          generateLabels: c => c.data.labels.map((l, i) => ({
            text: `${l} ${(c.data.datasets[0].data[i] / total * 100).toFixed(1)}%`,
            fillStyle: c.data.datasets[0].backgroundColor[i], strokeStyle: 'transparent', index: i,
          })) } },
        tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${pfFmtKrw(ctx.parsed)} (${(ctx.parsed / total * 100).toFixed(1)}%)` } },
      },
    },
  });
}
// ── 📈 수익률 추이 vs 벤치마크 (3.2) ────────────────────────────────────────
// 방문일마다 (평가금액, 매입금액) 스냅샷을 localStorage 에 적립하고, 누적 수익률 추이를
// KOSPI·S&P500(data.json history) 등락률과 같은 차트에 겹쳐 시장 대비 초과수익을 보여준다.
const PF_SNAP_KEY = 'pfSnapshotsV1';
function _pfLoadSnaps() {
  try { const a = JSON.parse(localStorage.getItem(PF_SNAP_KEY) || '[]'); return Array.isArray(a) ? a : []; } catch(_) { return []; }
}
function pfRecordSnapshot() {
  if(!pfState || !pfState.items.length) return;
  const fx = pfUsdKrw();
  let ev = 0, ct = 0;
  pfState.items.forEach(it => {
    const q = pfQuotes[it.id];
    if(!q || !it.qty || !it.avg) return;
    if(q.ccy === 'USD' && !fx) return;
    const mul = q.ccy === 'USD' ? fx : 1;
    ev += q.price * it.qty * mul;
    ct += it.avg * it.qty * (q.ccy === 'USD' ? (it.fxBuy || fx) : 1);
  });
  if(!(ev > 0) || !(ct > 0)) return;
  const today = new Date().toISOString().slice(0, 10);
  const snaps = _pfLoadSnaps().filter(s => s && s.d && s.d !== today);
  snaps.push({ d: today, ev: Math.round(ev), ct: Math.round(ct) });
  snaps.sort((a, b) => a.d < b.d ? -1 : 1);
  try { localStorage.setItem(PF_SNAP_KEY, JSON.stringify(snaps.slice(-730))); } catch(_) {}
}
// 벤치마크 지수 — 각 스냅샷 날짜의 (직전) 종가를 첫 스냅샷일 대비 등락률(%)로 환산
// 지수 일별 정규화 시계열 — startDate 종가를 기준(0%)으로 axis(일별 날짜 배열) 위에 forward-fill.
// 스냅샷일에만 샘플링하면 해외 지수(S&P500)가 한국 휴장·데이터 지연 구간에서 같은 종가로 collapse →
// 0% 평탄선이 되는 문제가 있어, 일별 축으로 실제 추이를 그린다(미국 거래일이 쌓이면 자동으로 채워짐).
function _pfBenchSeriesDaily(symbol, axis, startDate) {
  const d = (typeof _latestDataForIndicators !== 'undefined') ? _latestDataForIndicators : null;
  const arr = ((((d || {}).history || {}).indices || {})[symbol]) || [];
  const pts = arr.filter(p => p && p.date && p.close != null)
                 .map(p => ({ d: p.date, v: +p.close }))
                 .sort((a, b) => a.d < b.d ? -1 : 1);
  if(!pts.length) return null;
  const closeOnOrBefore = dt => { let last = null; for(const p of pts) { if(p.d <= dt) last = p.v; else break; } return last; };
  const baseV = closeOnOrBefore(startDate);
  if(baseV == null) return null;
  return axis.map(dt => { const v = closeOnOrBefore(dt); return v != null ? (v / baseV - 1) * 100 : null; });
}
function pfRenderBench() {
  const wrap = document.getElementById('pfBenchWrap');
  const empty = document.getElementById('pfBenchEmpty');
  const note = document.getElementById('pfBenchNote');
  if(!wrap || !empty) return;
  const snaps = _pfLoadSnaps();
  if(snaps.length < 2) {
    wrap.style.display = 'none'; empty.style.display = 'block';
    if(note) note.style.display = 'none';
    if(snaps.length === 1) empty.innerHTML = `첫 스냅샷(${snaps[0].d})이 기록되었습니다.<br>내일 다시 방문하면 KOSPI·S&amp;P 500 과의 비교 차트가 표시됩니다.`;
    return;
  }
  wrap.style.display = 'block'; empty.style.display = 'none';
  if(note) note.style.display = 'block';
  // 일별 축: 첫 스냅샷일 ~ 오늘(또는 마지막 스냅샷일).
  const startDate = snaps[0].d;
  const today = new Date().toISOString().slice(0, 10);
  const lastSnap = snaps[snaps.length - 1].d;
  const endDate = today > lastSnap ? today : lastSnap;
  const axis = [];
  for(let cur = startDate, guard = 0; cur <= endDate && guard < 1100; guard++) {
    axis.push(cur);
    const dt = new Date(cur + 'T00:00:00Z'); dt.setUTCDate(dt.getUTCDate() + 1);
    cur = dt.toISOString().slice(0, 10);
  }
  // 내 포트폴리오 — 스냅샷 (평가/매입) 비율을 첫 스냅샷=0% 로 재기준해 축 위에 forward-fill
  const base = snaps[0].ev / snaps[0].ct;
  const snapMap = new Map(snaps.map(s => [s.d, ((s.ev / s.ct) / base - 1) * 100]));
  let lastMine = null;
  const mine = axis.map(dt => { if(snapMap.has(dt)) lastMine = snapMap.get(dt); return lastMine; });
  const kospi = _pfBenchSeriesDaily('KOSPI', axis, startDate);
  const sp = _pfBenchSeriesDaily('SP500', axis, startDate);
  const tc = (typeof getThemeColors === 'function') ? getThemeColors() : { txt: '#8d90a2', grid: '#2a2e3d55' };
  const ds = [{ label: '내 포트폴리오', data: mine, borderColor: window.CUP, backgroundColor: (window.CUP+'22'),
                borderWidth: 2, pointRadius: 0, tension: 0.3, spanGaps: true }];
  if(kospi) ds.push({ label: 'KOSPI', data: kospi, borderColor: getThemeColors().accent, borderWidth: 1.5, borderDash: [5, 3], pointRadius: 0, tension: 0.3, spanGaps: true });
  if(sp) ds.push({ label: 'S&P 500', data: sp, borderColor: '#f5a623', borderWidth: 1.5, borderDash: [5, 3], pointRadius: 0, tension: 0.3, spanGaps: true });
  // 해외 지수가 추적 구간 내 변동이 없으면(미국 증시가 한국 대비 ~1거래일 지연 → 같은 종가) 그 이유를 안내
  if(note) {
    const isFlat = a => a && a.filter(v => v != null).length > 0 && a.every(v => v == null || Math.abs(v) < 0.005);
    const baseNote = '내 포트폴리오 = (평가금액/매입금액 − 1), 벤치마크 = 첫 스냅샷일 종가 대비 등락률. 입금/매수로 매입금액이 변하면 단순 비교에 왜곡이 있을 수 있습니다.';
    note.innerHTML = baseNote + (isFlat(sp)
      ? '<br><span style="color:#f5a623;">※ S&amp;P 500 등 해외 지수는 한국보다 약 1거래일 늦게 갱신됩니다 — 추적 기간이 짧으면 미국 증시 종가 변동이 없어 0%(평탄)로 보일 수 있고, 미국 거래일이 쌓이면 자동으로 채워집니다.</span>'
      : '');
  }
  if(charts['pfBenchChart']) { try { charts['pfBenchChart'].destroy(); } catch(_) {} }
  const cv = document.getElementById('pfBenchChart');
  if(!cv || typeof Chart === 'undefined') return;
  charts['pfBenchChart'] = new Chart(cv, {
    type: 'line',
    data: { labels: axis, datasets: ds },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: tc.txt, usePointStyle: true, pointStyle: 'line', font: { size: 11 } } },
        tooltip: { callbacks: { label: c => `${c.dataset.label}: ${c.parsed.y == null ? '-' : (c.parsed.y >= 0 ? '+' : '') + c.parsed.y.toFixed(2) + '%'}` } },
      },
      scales: {
        x: { ticks: { color: tc.txt, maxTicksLimit: 8, font: { size: 10 } }, grid: { color: tc.grid } },
        y: { ticks: { color: tc.txt, font: { size: 10 }, callback: v => (v >= 0 ? '+' : '') + v + '%' }, grid: { color: tc.grid } },
      },
    },
  });
  // YoY — 주 시리즈('내 포트폴리오', dataset 0)만 전년 오버레이. 추적 기간이 1년 미만이면 '전년 데이터 없음'.
  registerYoY('pfBenchChart', { mode:'date', dispDates:axis, fullDates:axis, fullValues:mine, tol:7, primary:0, color:window.CUP, tension:0.3 });
  applyYoY('pfBenchChart');
}

function pfRenderAll() { pfRenderGroups(); pfRenderTable(); pfRenderSummary(); pfRenderPie(); pfRenderAlertSummary(); try { pfRecordSnapshot(); pfRenderBench(); } catch(_) {} }  // pfRenderTable 이 카드까지 동기화하므로 별도 pfRenderCards 호출 불필요(중복 렌더·깜빡임 제거)

// ── 상세 차트 (TradingView Lightweight Charts) ───────────────────────────────
let pfChart = { item: null, period: '1Y', main: null, rsi: null, macd: null, syncing: false, candles: null };
let pfInd = (function(){ try { return JSON.parse(localStorage.getItem('pfIndicators')) || { ma: true, rsi: false, macd: false }; } catch(_) { return { ma: true, rsi: false, macd: false }; } })();
const PF_PERIODS = { '1D': ['1d', '5m'], '1W': ['5d', '30m'], '3M': ['3mo', '1d'], '1Y': ['1y', '1d'], '3Y': ['3y', '1d'] };

function pfOpenChart(itemId) {
  const it = pfState.items.find(x => x.id === itemId);
  if(!it) return;
  pfChart.item = it;
  // [3차-T8] 설정의 기본 조회 기간을 모달 최초 1회 적용 (모달 기간 체계로 근사 매핑: 30D/1Q→3M, 6M/1Y→1Y)
  if (!pfChart._defaultApplied && window.econSettings) {
    const _dp = econSettings.get('chart.defaultPreset');
    const _map = { '30D': '3M', '1Q': '3M', '6M': '1Y', '1Y': '1Y' };
    if (_dp && _map[_dp]) {
      pfChart.period = _map[_dp];
      try {
        document.querySelectorAll('#pfChartPeriods .tab-btn').forEach(b => {
          const on = b.dataset.p === pfChart.period;
          b.style.background = on ? getThemeColors().accent : 'transparent';
          b.style.color = on ? '#fff' : '#8d90a2';
        });
      } catch (_) {}
    }
    pfChart._defaultApplied = true;   // 사용자가 모달에서 직접 고른 기간을 이후 덮어쓰지 않음
  }
  document.getElementById('pfChartModal').style.display = 'block';
  document.getElementById('pfChartTitle').textContent = (it.name || it.symbol) + ' (' + it.symbol + ')';
  const q = pfQuotes[it.id];
  document.getElementById('pfChartPrice').textContent = q ? pfFmtPrice(q.price, q.ccy) : '';
  document.getElementById('pfChartChg').innerHTML = q ? pfChgHtml(q.pct) : '';
  pfLoadChart();
}
function pfCloseChart() {
  document.getElementById('pfChartModal').style.display = 'none';
  pfDisposeCharts();
}
function pfDisposeCharts() {
  ['main', 'rsi', 'macd'].forEach(k => { try { if(pfChart[k]) pfChart[k].remove(); } catch(_) {} pfChart[k] = null; });
}
function pfSetChartPeriod(p, btn) {
  pfChart.period = p;
  document.querySelectorAll('#pfChartPeriods .tab-btn').forEach(b => {
    const on = b === btn;
    b.style.background = on ? getThemeColors().accent : 'transparent';
    b.style.color = on ? '#fff' : '#8d90a2';
  });
  pfLoadChart();
}
function pfToggleInd(name, btn) {
  pfInd[name] = !pfInd[name];
  try { localStorage.setItem('pfIndicators', JSON.stringify(pfInd)); } catch(_) {}
  pfApplyIndButtons();
  pfRenderChart();   // 데이터 재요청 없이 다시 그림
}
function pfApplyIndButtons() {
  [['ma','pfIndMaBtn'], ['rsi','pfIndRsiBtn'], ['macd','pfIndMacdBtn']].forEach(([k, id]) => {
    const b = document.getElementById(id);
    if(!b) return;
    b.style.background = pfInd[k] ? getThemeColors().accent : 'transparent';
    b.style.color = pfInd[k] ? '#fff' : '#8d90a2';
  });
}
// 네이버 국내 일봉 OHLCV — 신규 상장 ETF 등 Yahoo 에 없는 한국 종목의 차트 폴백
async function pfFetchNaverDaily(code, daysBack) {
  const fmt = d => d.toISOString().slice(0, 10).replace(/-/g, '');
  const end = new Date(), start = new Date(end.getTime() - daysBack * 86400000);
  const url = `https://m.stock.naver.com/front-api/external/chart/domestic/info?symbol=${code}&requestType=1&startTime=${fmt(start)}&endTime=${fmt(end)}&timeframe=day`;
  for(const u of _buildCorsProxyUrls(url)) {
    try {
      const r = await fetch(u, { signal: AbortSignal.timeout(8000) });
      if(!r.ok) continue;
      const txt = await r.text();
      if(!txt || txt.length < 50) continue;
      const candles = [];
      // 행 형식: ["YYYYMMDD", 시가, 고가, 저가, 종가, 거래량, ...]
      const re = /\[\s*"?(\d{8})"?\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/g;
      let m;
      while((m = re.exec(txt)) !== null) {
        candles.push({ time: `${m[1].slice(0,4)}-${m[1].slice(4,6)}-${m[1].slice(6,8)}`,
                       open: +m[2], high: +m[3], low: +m[4], close: +m[5], volume: +m[6] });
      }
      if(candles.length >= 2) return candles;
    } catch(_) { /* next proxy */ }
  }
  return null;
}
async function pfLoadChart() {
  const it = pfChart.item;
  if(!it) return;
  const msg = document.getElementById('pfChartMsg');
  msg.textContent = '차트 데이터 로딩 중…';
  pfDisposeCharts();
  // KR 종목인데 Yahoo 심볼 미해석 상태면 1회 시도 (.KS → .KQ)
  if(it.market === 'KR' && !it.yahoo && !it._yahooTried) {
    it._yahooTried = true;
    for(const suf of ['.KS', '.KQ']) {
      if(await pfFetchQuoteYahoo(it.symbol + suf)) { it.yahoo = it.symbol + suf; pfSave(); break; }
    }
  }
  const sym = it.yahoo || it.symbol;
  const [rng, itv] = PF_PERIODS[pfChart.period] || PF_PERIODS['1Y'];
  const daily = itv === '1d';
  let candles = [];
  const j = await _fetchJsonWithProxies(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=${rng}&interval=${itv}`);
  const res = j && j.chart && j.chart.result && j.chart.result[0];
  const ts = res && res.timestamp;
  const qd = res && res.indicators && res.indicators.quote && res.indicators.quote[0];
  if(ts && qd) {
    const gmtoff = (res.meta && res.meta.gmtoffset) || 0;
    for(let i = 0; i < ts.length; i++) {
      const o = qd.open[i], h = qd.high[i], l = qd.low[i], c = qd.close[i];
      if(o == null || h == null || l == null || c == null) continue;
      const time = daily ? new Date((ts[i] + gmtoff) * 1000).toISOString().slice(0, 10) : ts[i];
      candles.push({ time, open: +o, high: +h, low: +l, close: +c, volume: +((qd.volume && qd.volume[i]) || 0) });
    }
  }
  // Yahoo 실패 시 — 한국 종목은 네이버 일봉으로 폴백 (일봉 기간만 지원)
  if(candles.length < 2 && it.market === 'KR') {
    const days = { '1D': 10, '1W': 10, '3M': 130, '1Y': 500, '3Y': 1200 }[pfChart.period] || 500;
    const nv = await pfFetchNaverDaily(it.symbol, Math.max(days, 90));
    if(nv) {
      candles = nv;
      if(!daily) msg.textContent = '분봉 미지원 종목 — 일봉으로 표시합니다.';
    }
  }
  if(candles.length < 2) {
    // [3차-T17] 실패 시 재시도 버튼 — 일시적 네트워크 오류를 모달 재오픈 없이 복구
    msg.innerHTML = '차트 데이터를 불러오지 못했습니다. (심볼: ' + pfEsc(sym) + ') ' +
      '<button onclick="pfLoadChart()" style="font-size:var(--font-size-sm);padding:2px 10px;margin-left:6px;border:1px solid var(--c-accent);border-radius:var(--r-xs);background:transparent;color:var(--c-primary);cursor:pointer;">↻ 재시도</button>';
    pfChart.candles = null;
    return;
  }
  pfChart.candles = candles;
  if(msg.textContent === '차트 데이터 로딩 중…') msg.textContent = '';
  pfRenderChart();
}
function pfMkChart(el, height, opts) {
  // [3차-T10] 라이트/다크 테마 인지 — 모달 차트도 현재 테마 색을 따른다 (기존엔 다크색 하드코딩)
  const light = document.documentElement.classList.contains('light');
  const txt = light ? 'rgb(89,89,89)' : '#a4a8bc';
  const grid = light ? '#dbe6f4' : '#1f2430';
  const border = light ? '#aac4e6' : '#2a2e3d';
  return LightweightCharts.createChart(el, Object.assign({
    width: el.clientWidth, height,
    layout: { background: { color: 'transparent' }, textColor: txt, fontSize: 10 },
    grid: { vertLines: { color: grid }, horzLines: { color: grid } },
    rightPriceScale: { borderColor: border },
    timeScale: { borderColor: border, timeVisible: true, secondsVisible: false },
    crosshair: { mode: 0 },
  }, opts || {}));
}
function pfSyncRanges(from) {
  if(pfChart.syncing) return;
  pfChart.syncing = true;
  try {
    const r = from.timeScale().getVisibleLogicalRange();
    if(r) ['main', 'rsi', 'macd'].forEach(k => {
      const c = pfChart[k];
      if(c && c !== from) c.timeScale().setVisibleLogicalRange(r);
    });
  } catch(_) {}
  pfChart.syncing = false;
}
function pfRenderChart() {
  const candles = pfChart.candles;
  pfDisposeCharts();
  const rsiWrap = document.getElementById('pfTvRsiWrap');
  const macdWrap = document.getElementById('pfTvMacdWrap');
  const maLegend = document.getElementById('pfMaLegend');
  if(!candles) { rsiWrap.style.display = 'none'; macdWrap.style.display = 'none'; return; }
  if(typeof LightweightCharts === 'undefined') {
    document.getElementById('pfChartMsg').textContent = '차트 라이브러리(Lightweight Charts) 로드 실패 — 네트워크 차단 여부를 확인하세요.';
    return;
  }
  pfApplyIndButtons();
  maLegend.style.display = pfInd.ma ? 'block' : 'none';
  rsiWrap.style.display = pfInd.rsi ? 'block' : 'none';
  macdWrap.style.display = pfInd.macd ? 'block' : 'none';

  const closes = candles.map(c => c.close);
  const times = candles.map(c => c.time);

  // 메인: 캔들 + 거래량 + (토글) 이동평균선
  const elMain = document.getElementById('pfTvMain');
  elMain.innerHTML = '';
  const main = pfMkChart(elMain, 360);
  pfChart.main = main;
  // [3차-T9] 차트 스타일(캔들/라인) + 테마색 — 설정·라이트 모드 연동
  const tcPf = (typeof getThemeColors === 'function') ? getThemeColors() : { up: window.CUP, down: window.CDN, accent: getThemeColors().accent };
  const pfStyle = (window.econSettings && econSettings.get('chart.pfStyle')) || 'candle';
  let cs;
  if (pfStyle === 'line') {
    cs = main.addLineSeries({ color: tcPf.accent || getThemeColors().accent, lineWidth: 2, priceLineVisible: true });
    cs.setData(candles.map(c => ({ time: c.time, value: c.close })));
  } else {
    cs = main.addCandlestickSeries({ upColor: tcPf.up, downColor: tcPf.down, borderUpColor: tcPf.up, borderDownColor: tcPf.down, wickUpColor: tcPf.up, wickDownColor: tcPf.down });
    cs.setData(candles);
  }
  const vol = main.addHistogramSeries({ priceScaleId: '', priceFormat: { type: 'volume' }, color: '#2a2e3d' });
  main.priceScale('').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  vol.setData(candles.map(c => ({ time: c.time, value: c.volume, color: c.close >= c.open ? (window.CUP+'55') : (window.CDN+'55') })));
  if(pfInd.ma) {
    [[5, '#f6c026'], [20, '#e040fb'], [60, '#26c6da']].forEach(([n, color]) => {
      const ma = pfSMA(closes, n);
      const data = [];
      for(let i = 0; i < times.length; i++) if(ma[i] != null) data.push({ time: times[i], value: ma[i] });
      if(data.length) main.addLineSeries({ color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }).setData(data);
    });
  }
  main.timeScale().fitContent();
  main.timeScale().subscribeVisibleLogicalRangeChange(() => pfSyncRanges(main));

  // RSI 패널
  if(pfInd.rsi) {
    const elR = document.getElementById('pfTvRsi');
    elR.innerHTML = '';
    const rsiC = pfMkChart(elR, 110);
    pfChart.rsi = rsiC;
    const rsi = pfRSI(closes, 14);
    const data = [];
    for(let i = 0; i < times.length; i++) if(rsi[i] != null) data.push({ time: times[i], value: rsi[i] });
    const s = rsiC.addLineSeries({ color: '#b6c4ff', lineWidth: 1, priceLineVisible: false });
    s.setData(data);
    [[70, (window.CDN+'88')], [30, (window.CUP+'88')]].forEach(([lv, color]) =>
      s.createPriceLine({ price: lv, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true }));
    rsiC.timeScale().fitContent();
    rsiC.timeScale().subscribeVisibleLogicalRangeChange(() => pfSyncRanges(rsiC));
  }
  // MACD 패널
  if(pfInd.macd) {
    const elM = document.getElementById('pfTvMacd');
    elM.innerHTML = '';
    const macdC = pfMkChart(elM, 130);
    pfChart.macd = macdC;
    const { macd, signal, hist } = pfMACD(closes, 12, 26, 9);
    const hData = [], mData = [], sData = [];
    for(let i = 0; i < times.length; i++) {
      if(hist[i] != null) hData.push({ time: times[i], value: hist[i], color: hist[i] >= 0 ? (window.CUP+'88') : (window.CDN+'88') });
      if(macd[i] != null) mData.push({ time: times[i], value: macd[i] });
      if(signal[i] != null) sData.push({ time: times[i], value: signal[i] });
    }
    macdC.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false }).setData(hData);
    macdC.addLineSeries({ color: getThemeColors().accent, lineWidth: 1, priceLineVisible: false }).setData(mData);
    macdC.addLineSeries({ color: '#f6c026', lineWidth: 1, priceLineVisible: false }).setData(sData);
    macdC.timeScale().fitContent();
    macdC.timeScale().subscribeVisibleLogicalRangeChange(() => pfSyncRanges(macdC));
  }
  // 초기 가시범위 동기화
  pfSyncRanges(main);
}
// 보조지표 계산
function pfSMA(arr, n) {
  const out = new Array(arr.length).fill(null);
  let sum = 0;
  for(let i = 0; i < arr.length; i++) {
    sum += arr[i];
    if(i >= n) sum -= arr[i - n];
    if(i >= n - 1) out[i] = sum / n;
  }
  return out;
}
function pfEMA(arr, n) {
  const out = new Array(arr.length).fill(null);
  const k = 2 / (n + 1);
  let ema = null;
  for(let i = 0; i < arr.length; i++) {
    const v = arr[i];
    if(v == null) { out[i] = ema; continue; }
    ema = (ema == null) ? v : v * k + ema * (1 - k);
    out[i] = ema;
  }
  return out;
}
function pfRSI(closes, n) {
  const out = new Array(closes.length).fill(null);
  let avgG = 0, avgL = 0;
  for(let i = 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    const g = Math.max(d, 0), l = Math.max(-d, 0);
    if(i <= n) {
      avgG += g / n; avgL += l / n;
      if(i === n) out[i] = avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL);
    } else {
      avgG = (avgG * (n - 1) + g) / n;
      avgL = (avgL * (n - 1) + l) / n;
      out[i] = avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL);
    }
  }
  return out;
}
function pfMACD(closes, fast, slow, sig) {
  const ef = pfEMA(closes, fast), es = pfEMA(closes, slow);
  const macd = closes.map((_, i) => (i >= slow - 1 && ef[i] != null && es[i] != null) ? ef[i] - es[i] : null);
  const signal = pfEMA(macd, sig).map((v, i) => macd[i] == null ? null : v);
  const hist = macd.map((v, i) => (v != null && signal[i] != null) ? v - signal[i] : null);
  return { macd, signal, hist };
}

// ── 카카오 알림 조건 설정 ────────────────────────────────────────────────────
const PF_ALERT_LABEL = {
  price_above: v => `가격 ≥ ${(+v).toLocaleString()}`,
  price_below: v => `가격 ≤ ${(+v).toLocaleString()}`,
  pct_change:  v => `등락률 ${v > 0 ? '+' : ''}${v}% 도달`,
  high52:      () => '52주 신고가',
  low52:       () => '52주 신저가',
  vol_surge:   v => `거래량 전일比 ${v || 300}%↑`,
  golden_cross:(v, a) => `골든크로스 MA${a.maShort}/${a.maLong}`,
  dead_cross:  (v, a) => `데드크로스 MA${a.maShort}/${a.maLong}`,
};
function pfAlertLabel(a) {
  const fn = PF_ALERT_LABEL[a.type];
  const period = a.limit === 'cool60' ? '1시간 쿨다운' : '하루 1회';
  // 가격 지정 알림은 백엔드가 '교차 시 1회 + 재무장'으로 동작한다(도배방지 주기는 이벤트형 전용).
  // refire 를 켠 알림만 충족 지속 중 주기 재알림 — 라벨이 실제 동작을 정확히 말하게 한다(2026-07 감사).
  const isPrice = (a.type === 'price_above' || a.type === 'price_below');
  const suffix = isPrice ? (a.refire ? ` · 재알림(${period})` : ' · 돌파 시 1회') : ` · ${period}`;
  return (fn ? fn(a.value, a) : a.type) + suffix;
}
let pfAlertItem = null;
function pfOpenAlerts(itemId) {
  const it = pfState.items.find(x => x.id === itemId);
  if(!it) return;
  pfAlertItem = it;
  document.getElementById('pfAlertModalName').textContent = (it.name || it.symbol) + ' (' + it.symbol + ')';
  document.getElementById('pfAlertModal').style.display = 'block';
  pfAlertTypeChanged();
  pfRenderAlertList();
}
function pfCloseAlerts() {
  document.getElementById('pfAlertModal').style.display = 'none';
  pfAlertItem = null;
  pfRenderAll();
}
function pfAlertTypeChanged() {
  const t = document.getElementById('pfAlertType').value;
  const val = document.getElementById('pfAlertValue');
  const ma = document.getElementById('pfAlertMaPair');
  const hint = document.getElementById('pfAlertHint');
  const needVal = (t === 'price_above' || t === 'price_below' || t === 'pct_change' || t === 'vol_surge');
  val.style.display = needVal ? 'inline-block' : 'none';
  ma.style.display = (t === 'golden_cross' || t === 'dead_cross') ? 'inline-block' : 'none';
  // [재알림 옵션] 가격 유형에서만 체크박스 노출 — 이벤트형은 도배방지 주기가 이미 반복을 관장한다.
  const refireWrap = document.getElementById('pfAlertRefireWrap');
  if (refireWrap) refireWrap.style.display = (t === 'price_above' || t === 'price_below') ? 'inline-flex' : 'none';
  const hints = {
    price_above: '현재가가 입력한 가격 이상이 되면 발송됩니다. 기본은 돌파 시 1회(회복 후 재돌파 시 재발송) — 「지속 재알림」을 켜면 충족 지속 중에도 선택한 주기로 반복 알림.',
    price_below: '현재가가 입력한 가격 이하가 되면 발송됩니다. 기본은 돌파 시 1회(회복 후 재돌파 시 재발송) — 「지속 재알림」을 켜면 충족 지속 중에도 선택한 주기로 반복 알림.',
    pct_change: '전일 종가 대비 등락률이 입력값에 도달하면 발송. 양수=상승(예: 5), 음수=하락(예: -3).',
    high52: '현재가가 최근 52주 최고가를 넘으면 발송됩니다.',
    low52: '현재가가 최근 52주 최저가를 밑돌면 발송됩니다.',
    vol_surge: '당일 거래량이 전일 거래량의 입력%(기본 300=3배) 이상이면 발송됩니다.',
    golden_cross: '단기 이동평균선이 장기선을 상향 돌파(골든크로스)한 날 발송됩니다.',
    dead_cross: '단기 이동평균선이 장기선을 하향 돌파(데드크로스)한 날 발송됩니다.',
  };
  hint.textContent = hints[t] || '';
  if(t === 'vol_surge' && !val.value) val.placeholder = '300';
  else val.placeholder = '값';
}
function pfAddAlert() {
  if(!pfAlertItem) return;
  const t = document.getElementById('pfAlertType').value;
  const rawV = document.getElementById('pfAlertValue').value;
  let value = parseFloat(rawV);
  if(t === 'vol_surge' && !isFinite(value)) value = 300;
  if((t === 'price_above' || t === 'price_below') && (!isFinite(value) || value <= 0)) { alert('가격을 입력하세요.'); return; }
  if(t === 'pct_change' && (!isFinite(value) || value === 0)) { alert('등락률(%)을 입력하세요. 양수=상승, 음수=하락.'); return; }
  if(t === 'vol_surge' && (!isFinite(value) || value <= 100)) { alert('100보다 큰 %를 입력하세요. (예: 300 = 3배)'); return; }
  const [maS, maL] = (document.getElementById('pfAlertMaPair').value || '20/60').split('/').map(Number);
  const it = pfAlertItem;
  pfState.alerts.push({
    id: 'a' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    symbol: it.symbol, market: it.market, yahoo: it.yahoo || null, name: it.name || it.symbol,
    type: t,
    value: isFinite(value) ? value : null,
    maShort: (t === 'golden_cross' || t === 'dead_cross') ? maS : null,
    maLong:  (t === 'golden_cross' || t === 'dead_cross') ? maL : null,
    limit: document.getElementById('pfAlertLimit').value || 'daily',
    // [재알림 옵션] 가격 유형 전용 — 체크 시 충족 지속 중에도 limit 주기로 반복 알림(백엔드 refire).
    refire: (t === 'price_above' || t === 'price_below')
      ? !!(document.getElementById('pfAlertRefire') && document.getElementById('pfAlertRefire').checked)
      : false,
    enabled: true,
  });
  document.getElementById('pfAlertValue').value = '';
  pfSave(); pfRenderAlertList(); pfMarkDirty();
}
function pfDeleteAlert(id) {
  pfState.alerts = pfState.alerts.filter(a => a.id !== id);
  pfSave(); pfRenderAlertList(); pfMarkDirty();
}
function pfToggleAlert(id) {
  const a = pfState.alerts.find(x => x.id === id);
  if(a) { a.enabled = !a.enabled; pfSave(); pfRenderAlertList(); pfMarkDirty(); }
}
function pfRenderAlertList() {
  const el = document.getElementById('pfAlertList');
  if(!el || !pfAlertItem) return;
  const list = pfState.alerts.filter(a => a.symbol === pfAlertItem.symbol && a.market === pfAlertItem.market);
  if(!list.length) { el.innerHTML = '<div style="font-size:var(--font-size-sm);color:var(--c-txt-muted);padding:6px 0;">설정된 알림이 없습니다.</div>'; return; }
  el.innerHTML = list.map(a => `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;background:var(--c-card);border:1px solid var(--c-border);border-radius:var(--r-sm);padding:7px 10px;margin-bottom:6px;${a.enabled ? '' : 'opacity:.45;'}">
      <span style="font-size:var(--font-size-sm);color:var(--c-txt);">${pfEsc(pfAlertLabel(a))}</span>
      <span style="white-space:nowrap;">
        <button onclick="pfToggleAlert('${a.id}')" style="background:transparent;border:1px solid var(--c-border);border-radius:var(--r-xs);color:${a.enabled ? window.CUP : 'var(--c-txt-dim)'};font-size:var(--font-size-xs);padding:2px 8px;cursor:pointer;">${a.enabled ? 'ON' : 'OFF'}</button>
        <button onclick="pfDeleteAlert('${a.id}')" style="background:transparent;border:none;color:var(--c-txt-dim);cursor:pointer;font-size:var(--font-size-base);">🗑</button>
      </span>
    </div>`).join('');
}
function pfRenderAlertSummary() {
  // [3차-T14] 다중 타깃 — 포트폴리오 위젯과 설정 페이지에 같은 요약을 동시 렌더
  const els = ['pfAlertSummary', 'settingsAlertSummary']
    .map(id => document.getElementById(id)).filter(Boolean);
  if(!els.length) return;
  if(!pfState.alerts.length) {
    els.forEach(el => { el.textContent = '설정된 알림이 없습니다. 「투자 현황」 종목 행의 🔔 버튼으로 추가하세요.'; });
    return;
  }
  const bySym = {};
  pfState.alerts.forEach(a => {
    const k = a.name || a.symbol;
    (bySym[k] = bySym[k] || []).push(pfAlertLabel(a) + (a.enabled ? '' : ' (OFF)'));
  });
  const html = Object.keys(bySym).map(k =>
    `<div style="margin-bottom:4px;"><b style="color:var(--c-txt);">${pfEsc(k)}</b> — ${pfEsc(bySym[k].join(' · '))}</div>`).join('');
  els.forEach(el => { el.innerHTML = html; });
}
function pfMarkDirty() {
  _pfDirty = true;   // 페이지 이탈/새로고침 경고 플래그 — 죽은 첫 정의에만 있어 유실됐던 동작 복원
  const el = _pfSyncStatusEl();
  if(el) { el.textContent = '변경됨 — 서버 저장 필요'; el.style.color = '#f0c75e'; }
  pfRenderAlertSummary();
}

// ── 서버 동기화 (Cloudflare Worker → 저장소 alerts_config.json) ───────────────
// 보안 (1.2): 동기화 키는 평문 저장/전송하지 않는다. 입력 즉시 SHA-256 해시로 변환해
// 해시만 localStorage 에 보관·전송하고, Worker 는 자기 시크릿의 해시와 비교 검증한다.
// → localStorage 가 유출돼도 원본 키는 복원 불가, 네트워크 캡처에도 평문 키가 남지 않는다.
async function pfSha256Hex(s) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(s)));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}
// 저장된 해시 반환 — 구버전 평문 키(pfSyncKey)가 남아 있으면 해시로 1회 마이그레이션
async function pfGetSyncKeyHash() {
  let h = '';
  try { h = localStorage.getItem('pfSyncKeyHash') || ''; } catch(_) {}
  if(h) return h;
  let legacy = '';
  try { legacy = localStorage.getItem('pfSyncKey') || ''; } catch(_) {}
  if(!legacy) return '';
  try {
    h = await pfSha256Hex(legacy);
    localStorage.setItem('pfSyncKeyHash', h);
    localStorage.removeItem('pfSyncKey');
  } catch(_) { return ''; }
  return h;
}
// 🔑 버튼에 키 저장 여부를 표시 — 해시로만 보관해 값은 못 보여주므로 '저장됨' 상태라도 명시해
// 사용자가 "키를 넣는 곳이 없다/안 읽힌다"고 오해하지 않게 한다.
function pfUpdateSyncKeyBtn() {
  const b = document.getElementById('pfSyncKeyBtn');
  if(!b) return;
  const has = (typeof pfHasSyncKey === 'function') ? pfHasSyncKey() : false;
  b.textContent = has ? '🔑 동기화 키 ✓' : '🔑 동기화 키';
  b.style.color = has ? window.CUP : 'var(--c-txt-dim)';
  b.title = has ? '동기화 키 저장됨 (해시로만 보관) — 변경하려면 클릭'
                : 'Worker 시크릿 ALERTS_SYNC_KEY 를 설정한 경우 동일한 키 입력';
}
async function pfSetSyncKey() {
  const has = !!(localStorage.getItem('pfSyncKeyHash') || localStorage.getItem('pfSyncKey'));
  const k = prompt(`동기화 키 (Worker 시크릿 ALERTS_SYNC_KEY 와 동일하게 — 미설정 시 비워두기)${has ? '\n※ 현재 키가 저장되어 있습니다 (보안을 위해 해시로만 보관되어 표시 불가)' : ''}:`, '');
  if(k === null) return;
  try {
    localStorage.removeItem('pfSyncKey');   // 평문 잔존 제거
    if(!k.trim()) { localStorage.removeItem('pfSyncKeyHash'); pfUpdateSyncKeyBtn(); return; }
    localStorage.setItem('pfSyncKeyHash', await pfSha256Hex(k.trim()));
    pfUpdateSyncKeyBtn();
    if(typeof showToast === 'function') showToast('동기화 키가 SHA-256 해시로 안전하게 저장되었습니다.');
  } catch(_) {}
}
// [3차-T13] 동기화 상태 표시 대상 선택 — 설정 페이지가 활성일 땐 그쪽 상태줄을 우선 사용.
// 같은 함수(pfSyncAlerts 등)를 포트폴리오·설정 두 화면에서 공유하기 위한 어댑터.
function _pfSyncStatusEl() {
  const pg = document.getElementById('page-settings');
  if (pg && pg.classList.contains('active')) {
    return document.getElementById('settingsSyncStatus') || document.getElementById('pfSyncStatus');
  }
  return document.getElementById('pfSyncStatus') || document.getElementById('settingsSyncStatus');
}
// 📋 관심목록(지정 종목 트래킹) 서버 동기화 페이로드 — 기기 간 동일한 목록 표시용.
// ⚠ 프라이버시(사용자 선택='관심목록만 공개 동기화'): 평단가/수량/매입환율은 절대 보내지 않는다.
//   종목(코드·이름·시장·구분)과 그룹(폴더) 정의만 담아 공개 저장소에 커밋한다.
function pfBuildTrackingPayload() {
  if(!pfState) return undefined;
  return {
    groups: (pfState.groups || []).slice(0, 50).map(g => ({ id: String(g.id || ''), name: String(g.name || '그룹') })),
    items: (pfState.items || []).slice(0, 300).map(it => ({
      symbol: it.symbol, market: it.market, yahoo: it.yahoo || null,
      name: it.name || it.symbol, secType: it.secType === 'etf' ? 'etf' : 'stock', group: it.group || ''
    })),
  };
}
async function pfSyncAlerts(stOverride) {
  const st = stOverride || _pfSyncStatusEl();
  const base = (typeof _cfProxyBase === 'function') ? _cfProxyBase() : '';
  if(!base) { if(st) { st.textContent = 'Worker 프록시 미설정'; st.style.color = window.CDN; } return; }
  if(st) { st.textContent = '저장 중…'; st.style.color = 'var(--c-txt-dim)'; }
  try {
    const r = await fetch(base + '/portfolio', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        keyHash: await pfGetSyncKeyHash(),
        alerts: pfState.alerts,
        // 📋 지정 종목 트래킹(관심목록) 동봉 — 다른 기기/플랫폼에서도 같은 목록을 보기 위함.
        tracking: pfBuildTrackingPayload(),
        // 🔐 평단가·수량(암호화 블록) — 암호 설정 시에만 동봉. 미설정이면 undefined → 서버 기존본 보존.
        encHoldings: await pfBuildEncHoldings(),
        // [3차-T15] 전역 알림 설정 동봉 — Worker 가 화이트리스트 검증 후 alerts_config.json 에 커밋.
        // ⚠ '이 기기에서 명시 설정(저장/불러오기)한 적이 있을 때만' 동봉한다 — 기본값(ON)만 들고 있는
        //   기기가 저장할 때마다 다른 기기에서 꺼 둔 전역 OFF 를 소리 없이 되돌리던 문제 방지
        //   (미동봉 시 Worker 가 기존 저장본의 settings 를 보존한다 — 2026-07 감사).
        settings: (function () {
          try {
            var raw = JSON.parse(localStorage.getItem('econ_settings_v1') || '{}');
            if (raw && raw.notif && window.econSettings) {
              return {
                enabled: !!econSettings.get('notif.globalEnabled'),
                defaultLimit: econSettings.get('notif.defaultLimit') || 'daily'
              };
            }
          } catch (_) {}
          return undefined;
        })()
      }),
      signal: AbortSignal.timeout(20000),
    });
    const j = await r.json().catch(() => ({}));
    if(r.ok && j.ok) {
      pfState.lastSync = new Date().toISOString();
      pfSave();
      if(typeof pfClearDirty === 'function') pfClearDirty();   // 서버 저장 완료 → 미저장 경고 해제
      const _tc = (j.trackingCount != null) ? `관심종목 ${j.trackingCount}개·` : '';
      if(st) { st.textContent = `저장 완료 (${_tc}알림 ${j.count}개, ${new Date().toLocaleTimeString('ko-KR', {hour:'2-digit',minute:'2-digit',hour12:false})})`; st.style.color = window.CUP; }
      try { if(typeof showToast === 'function') showToast('☁ 서버에 저장됨', 'ok'); } catch(_){}
    } else {
      const why = j.error === 'unauthorized' ? '동기화 키 불일치 (🔑 버튼으로 설정)' :
                  j.error === 'no_github_token' ? 'Worker 에 GH_DISPATCH_TOKEN 시크릿 필요' : (j.error || ('HTTP ' + r.status));
      if(st) { st.textContent = '저장 실패: ' + why; st.style.color = window.CDN; }
      try { if(typeof showToast === 'function') showToast('저장 실패: ' + why, 'err', 3200); } catch(_){}
    }
  } catch(e) {
    if(st) { st.textContent = '저장 실패 — 네트워크 오류'; st.style.color = window.CDN; }
  }
}
// 🔔 알림 테스트 발송 — Worker POST /portfolio/test 가 repository_dispatch(alerts-test)로
// stock-alerts 워크플로를 즉시 1회 깨운다. 설정 검증에 다음 5분 cron 을 기다릴 필요 없음.
// 테스트 런은 장중/쿨다운 가드를 무시하고 평가하며, 메시지에 "[테스트]" 프리픽스가 붙는다.
async function pfTestAlerts() {
  const st = _pfSyncStatusEl();
  const base = (typeof _cfProxyBase === 'function') ? _cfProxyBase() : '';
  if(!base) { if(st) { st.textContent = 'Worker 프록시 미설정'; st.style.color = window.CDN; } return; }
  if(st) { st.textContent = '테스트 발송 요청 중…'; st.style.color = 'var(--c-txt-dim)'; }
  try {
    const r = await fetch(base + '/portfolio/test', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ keyHash: await pfGetSyncKeyHash() }),
      signal: AbortSignal.timeout(20000),
    });
    const j = await r.json().catch(() => ({}));
    if(r.ok && j.ok) {
      if(st) { st.textContent = '테스트 실행 요청됨 — 1~2분 내 카카오톡으로 결과가 도착합니다.'; st.style.color = window.CUP; }
    } else {
      const why = j.error === 'unauthorized' ? '동기화 키 불일치 (🔑 버튼으로 설정)' :
                  j.error === 'sync_key_not_configured' ? 'Worker 에 ALERTS_SYNC_KEY 시크릿 필요' :
                  j.error === 'no_github_token' ? 'Worker 에 GH_DISPATCH_TOKEN 시크릿 필요' : (j.error || ('HTTP ' + r.status));
      if(st) { st.textContent = '테스트 실패: ' + why; st.style.color = window.CDN; }
    }
  } catch(_) {
    if(st) { st.textContent = '테스트 실패 — 네트워크 오류'; st.style.color = window.CDN; }
  }
}
async function pfPullAlerts() {
  const st = _pfSyncStatusEl();
  const base = (typeof _cfProxyBase === 'function') ? _cfProxyBase() : '';
  if(!base) { if(st) { st.textContent = 'Worker 프록시 미설정'; st.style.color = window.CDN; } return; }
  if(st) { st.textContent = '불러오는 중…'; st.style.color = 'var(--c-txt-dim)'; }
  try {
    // [이슈1] GET /portfolio 가 ALERTS_SYNC_KEY 인증을 요구 → keyHash 쿼리 동봉(키 없으면 빈 값→401 graceful).
    const _kh = (typeof pfGetSyncKeyHash === 'function') ? await pfGetSyncKeyHash() : '';
    if(!_kh) { if(st) { st.textContent = '이 기기에 동기화 키가 없습니다 — ⚙ 설정에서 키 입력 후 다시 시도'; st.style.color = '#f0c75e'; } return; }
    // 키 해시는 커스텀 헤더로만 전송 — URL 쿼리는 접근 로그·히스토리에 남아 재사용 가능한
    // 베어러가 유출된다. (X-Sync-Key-Hash 수용 Worker ver e01d9f0f 배포 확인 후 쿼리 제거 완료.)
    const r = await fetch(base + '/portfolio', { headers: { 'X-Sync-Key-Hash': _kh }, signal: AbortSignal.timeout(15000) });
    if(r.status === 401 || r.status === 403) { if(st) { st.textContent = '동기화 키 불일치 — ⚙ 설정에서 키를 확인하세요'; st.style.color = window.CDN; } return; }
    if(r.status === 503) { if(st) { st.textContent = '서버에 동기화 키가 설정되지 않았습니다(관리자 설정 필요)'; st.style.color = window.CDN; } return; }
    const j = await r.json().catch(() => null);
    if(!r.ok || !j || !Array.isArray(j.alerts)) { if(st) { st.textContent = '서버에 저장된 설정이 없습니다.'; st.style.color = 'var(--c-txt-dim)'; } return; }
    if(pfState.alerts.length && !confirm(`서버의 알림 ${j.alerts.length}개로 현재 설정(${pfState.alerts.length}개)을 덮어쓸까요?`)) return;
    pfState.alerts = j.alerts;
    pfSave(); pfRenderAll();
    // [3차-T15] 서버에 저장된 전역 알림 설정도 함께 반영
    if (j.settings && window.econSettings) {
      econSettings.patch({ notif: {
        globalEnabled: j.settings.enabled !== false,
        defaultLimit: j.settings.defaultLimit === 'cool60' ? 'cool60' : 'daily'
      } });
      try { const pg = document.getElementById('page-settings'); if (pg && pg.classList.contains('active')) initSettingsPage(); } catch (_) {}
    }
    if(st) { st.textContent = `서버 설정 ${j.alerts.length}개 불러옴`; st.style.color = window.CUP; }
  } catch(_) {
    if(st) { st.textContent = '불러오기 실패 — 네트워크 오류'; st.style.color = window.CDN; }
  }
}

// ── 📋 지정 종목 트래킹(관심목록) 서버 동기화 ──────────────────────────────────
// 다른 기기/플랫폼에서도 같은 목록을 보기 위해 관심종목·그룹을 서버에 저장/복원한다.
// (평단가·수량은 이 브라우저에만 남는다 — 사용자 선택 '관심목록만 공개 동기화'.)
function _pfTrackStatusEl() { return document.getElementById('pfTrackSyncStatus'); }

// 저장 — 알림·전역설정과 함께 한 번에 커밋(부분 저장으로 알림이 지워지지 않도록).
async function pfSyncTracking() {
  const st = _pfTrackStatusEl();
  if(!pfState || !pfState.items.length) {
    if(st) { st.textContent = '저장할 종목이 없습니다.'; st.style.color = 'var(--c-txt-dim)'; }
    return;
  }
  await pfSyncAlerts(st);
}

// 복원 — 서버 관심목록을 현재 목록에 병합한다. 평단가/수량은 종목코드 기준으로 로컬 값을 유지.
//   auto=true(초기 자동): 누락 종목/그룹만 '추가'(비파괴). auto=false(수동 버튼): 그룹 소속·이름도 서버 기준으로 갱신.
async function pfPullTracking(auto) {
  const st = _pfTrackStatusEl();
  const base = (typeof _cfProxyBase === 'function') ? _cfProxyBase() : '';
  if(!base) { if(!auto && st) { st.textContent = 'Worker 프록시 미설정'; st.style.color = window.CDN; } return; }
  if(!auto && st) { st.textContent = '불러오는 중…'; st.style.color = 'var(--c-txt-dim)'; }
  let j = null;
  try {
    // [이슈1] GET /portfolio 인증(keyHash) 동봉 — 자동(auto) 복원은 키 존재 시에만 호출되므로 정상 동작.
    const _kh = (typeof pfGetSyncKeyHash === 'function') ? await pfGetSyncKeyHash() : '';
    // 이 기기에 동기화 키가 없으면 서버는 401 을 준다 → 원인을 명확히 안내(다른 기기에서 저장한 목록을
    // 새 기기에서 불러오려면 ⚙ 설정에서 동일한 동기화 키를 먼저 입력해야 한다).
    if(!_kh && !auto) { if(st) { st.textContent = '이 기기에 동기화 키가 없습니다 — ⚙ 설정에서 키 입력 후 다시 시도'; st.style.color = '#f0c75e'; } return; }
    // 키 해시는 헤더로만 전송 (위 pfPullAlerts 와 동일 — URL 로그 유출 방지, Worker 배포 확인됨)
    const r = await fetch(base + '/portfolio', { headers: { 'X-Sync-Key-Hash': _kh }, signal: AbortSignal.timeout(15000) });
    if(r.status === 401 || r.status === 403) { if(!auto && st) { st.textContent = '동기화 키 불일치 — ⚙ 설정에서 키를 확인하세요'; st.style.color = window.CDN; } return; }
    if(r.status === 503) { if(!auto && st) { st.textContent = '서버에 동기화 키가 설정되지 않았습니다(관리자 설정 필요)'; st.style.color = window.CDN; } return; }
    j = await r.json().catch(() => null);
    if(!r.ok || !j) {
      // 5xx 의 실제 원인을 노출 — Worker 가 본문에 담아주는 error/detail(예: github_read_failed)을
      // 'HTTP 5xx' 뒤에 숨기지 않고 보여줘 즉시 진단 가능하게 한다.
      const _why = (j && j.error === 'github_read_failed') ? 'GitHub 읽기 실패 — Worker 재배포 + GH_DISPATCH_TOKEN 갱신 필요'
                 : (j && j.error === 'no_github_token') ? 'Worker GH_DISPATCH_TOKEN 시크릿 미설정'
                 : (j && (j.error || j.detail)) ? (j.error || j.detail)
                 : ('HTTP ' + r.status);
      if(!auto && st) { st.textContent = '서버 응답 오류: ' + _why + ' (HTTP ' + r.status + ')'; st.style.color = window.CDN; }
      return;
    }
  } catch(_) {
    if(!auto && st) { st.textContent = '불러오기 실패 — 네트워크/프록시 오류(잠시 후 재시도)'; st.style.color = window.CDN; }
    return;
  }
  const tr = j.tracking;
  if(!tr || !Array.isArray(tr.items) || !tr.items.length) {
    if(!auto && st) { st.textContent = '서버에 저장된 관심목록이 없습니다.'; st.style.color = 'var(--c-txt-dim)'; }
    return;
  }
  if(!auto) {
    const adds = tr.items.filter(s => !pfState.items.some(it => it.symbol === s.symbol && it.market === s.market)).length;
    if(!confirm(`서버 관심목록 ${tr.items.length}개를 불러옵니다.\n· 새 종목 ${adds}개 추가\n· 그룹 소속·이름은 서버 기준으로 맞춥니다\n· 평단가·수량: 암호화 동기화를 켜둔 경우 서버 암호본을 복호화해 채우고, 아니면 이 기기 값 유지\n진행할까요?`)) {
      if(st) { st.textContent = ''; }
      return;
    }
  }
  // 1) 그룹 병합 — 서버 그룹 id 를 보존해 종목의 group 참조가 끊기지 않게 한다.
  (tr.groups || []).forEach(g => {
    if(!g || !g.id) return;
    const ex = pfState.groups.find(x => x.id === g.id);
    if(!ex) pfState.groups.push({ id: g.id, name: String(g.name || '그룹').slice(0, 30) });
    else if(!auto && g.name) ex.name = String(g.name).slice(0, 30);
  });
  const groupIds = new Set(pfState.groups.map(g => g.id));
  const fallbackGroup = pfState.groups[0] ? pfState.groups[0].id : 'g_default';
  // 2) 종목 병합 — 코드+시장 기준. 기존은 평단가/수량 유지, 신규는 평단가/수량 없이 추가.
  let added = 0;
  tr.items.forEach(s => {
    const grp = groupIds.has(s.group) ? s.group : fallbackGroup;
    const ex = pfState.items.find(it => it.symbol === s.symbol && it.market === s.market);
    if(ex) {
      if(!auto) { ex.group = grp; if(s.name) ex.name = s.name; if(s.secType) ex.secType = s.secType; }
    } else {
      pfState.items.push({
        id: 'i' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
        symbol: s.symbol, market: s.market === 'US' ? 'US' : 'KR',
        yahoo: s.yahoo || (s.market === 'US' ? s.symbol : null),
        name: s.name || s.symbol, secType: s.secType === 'etf' ? 'etf' : 'stock',
        ccy: s.market === 'US' ? 'USD' : 'KRW',
        avg: null, qty: null, group: grp,
      });
      added++;
    }
  });
  pfState.seeded = true;   // 서버 목록을 받았으면 기본 시드 자동등록은 더 이상 불필요
  pfSave();
  if(typeof pfClearDirty === 'function') pfClearDirty();   // 서버 목록을 막 받음 → 관심목록은 서버와 동기 상태
  pfRenderAll();
  pfRefreshQuotes();
  // 🔐 암호화된 평단가/수량이 서버에 있으면 복호화해 병합(자동 복원은 암호 저장된 기기에서만 조용히).
  let _encApplied = 0;
  if (j.encHoldings) { try { _encApplied = await pfApplyEncHoldings(j.encHoldings, { silent: auto }); } catch(_) {} }
  if(st) {
    // 평단가/수량 복원 결과를 명시: 복원됨 / (서버에 암호본은 있으나) 암호 미설정·불일치로 복원 안 됨.
    const _enc = _encApplied > 0 ? ` · 평단가 ${_encApplied}개 복원`
               : (j.encHoldings && !auto ? ' · 평단가 복원 안 됨(🔐 평단가 동기화 암호 필요)' : '');
    st.textContent = (auto ? `서버 목록 동기화됨 (신규 ${added}개` : `불러옴 — 신규 ${added}개 추가 (총 ${pfState.items.length}개`) + _enc + ')';
    st.style.color = (j.encHoldings && _encApplied <= 0 && !auto) ? '#f0c75e' : window.CUP;
  }
}

// ── 🔐 평단가·수량 E2E 암호화 동기화 ──────────────────────────────────────────
// 평단가/수량/매입환율은 공개 저장소(alerts_config.json)에 평문으로 올리지 않는다.
// 사용자 암호로 이 기기에서 AES-GCM 암호화한 '불투명 블록'만 서버에 저장하고, 다른 기기에서
// 같은 암호로 복호화한다. 암호는 이 기기 localStorage 에만 둔다(이 기기엔 이미 평문 보유정보가
// 있으므로 위협이 늘지 않음 — E2E 의 보호 대상은 서버/공개 repo 사본이다).
// 자체 크립토 헬퍼(전역) — exportAllUserData 쪽 _deriveKey/_b64 는 IIFE 안이라 여기선 접근 불가.
const PF_KDF_ITER = 600000;  // OWASP 권장 PBKDF2-HMAC-SHA256 반복수
function _pfB64(bytes) { const u = new Uint8Array(bytes); let b = ''; for (let i = 0; i < u.length; i += 8192) b += String.fromCharCode.apply(null, u.subarray(i, i + 8192)); return btoa(b); }
function _pfUnB64(s) { const bin = atob(String(s)); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return u; }
async function _pfDeriveKey(pass, salt) {
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey({ name: 'PBKDF2', salt, iterations: PF_KDF_ITER, hash: 'SHA-256' }, base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
}
function pfGetHoldingsPass() { try { return localStorage.getItem('pfHoldingsPass') || ''; } catch(_) { return ''; } }
function pfUpdateHoldingsSyncUI() {
  const b = document.getElementById('pfHoldingsPassBtn');
  if (!b) return;
  const on = !!pfGetHoldingsPass();
  b.textContent = on ? '🔐 평단가 동기화 ON' : '🔐 평단가 동기화';
  b.style.borderColor = on ? window.CUP : 'var(--c-border)';
  b.style.color = on ? window.CUP : 'var(--c-primary)';
}
function pfSetHoldingsPass() {
  const on = !!pfGetHoldingsPass();
  const p = prompt('평단가·수량 동기화 암호 (12자 이상 권장)\n\n· 다른 기기에서 같은 암호를 입력해야 복호화됩니다.\n· 서버엔 암호문만 저장됩니다(평문 자산 노출 없음).\n· ⚠ 암호문은 공개 저장소에 올라가므로, 짧거나 흔한 암호는\n  오프라인 무차별 대입으로 평단가·수량이 복원될 수 있습니다.\n· 암호를 잊으면 서버 사본은 복구 불가.\n· 비워두면 동기화 해제.' + (on ? '\n\n※ 현재 이 기기에 암호가 설정되어 있습니다.' : ''), '');
  if (p === null) return;
  try {
    if (!p.trim()) { localStorage.removeItem('pfHoldingsPass'); if(typeof showToast==='function') showToast('평단가 동기화 해제 — 이후 「☁ 목록 저장」에서 평단가/수량은 서버에 올라가지 않습니다.', 4000); }
    else {
      // 암호문이 공개 repo 에 커밋되는 구조라 최소 길이를 강제한다 — PBKDF2 600k 라도
      // 사전 단어/짧은 암호는 오프라인 대입에 뚫린다(감사 확인 사항).
      // 하한 6자 = 사이트 잠금 PIN 과 같은 암호를 쓰려는 사용자 결정(2026-08-12). 짧을수록 대입에 약함.
      if (p.trim().length < 6) { if(typeof showToast==='function') showToast('⚠ 암호가 너무 짧습니다(6자 미만) — 설정되지 않았습니다. 12자 이상을 권장합니다.', 5000); return; }
      if (p.trim().length < 12 && typeof showToast==='function') showToast('ℹ 12자 미만 암호는 권장하지 않습니다 — 길수록 안전합니다.', 4000);
      localStorage.setItem('pfHoldingsPass', p); if(typeof showToast==='function') showToast('평단가 동기화 암호 설정 완료 — 「☁ 목록 저장」 시 평단가/수량이 암호화돼 함께 저장됩니다.', 4000);
    }
  } catch(_) {}
  pfUpdateHoldingsSyncUI();
}
// 보유정보 → 암호문 블록(서버 전송용). 암호 미설정/대상 없음이면 undefined(전송 안 함 → 서버는 기존 보존).
async function pfBuildEncHoldings() {
  const pass = pfGetHoldingsPass();
  if (!pass || !pfState || !Array.isArray(pfState.items)) return undefined;
  const map = pfState.items
    .filter(it => it.avg != null || it.qty != null)
    .map(it => ({ s: it.symbol, m: it.market === 'US' ? 'US' : 'KR',
                  a: (it.avg != null ? it.avg : null), q: (it.qty != null ? it.qty : null), fx: (it.fxBuy != null ? it.fxBuy : null) }));
  if (!map.length) return undefined;
  try {
    const salt = crypto.getRandomValues(new Uint8Array(16));
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const key = await _pfDeriveKey(pass, salt);
    const ct = await crypto.subtle.encrypt({ name:'AES-GCM', iv }, key, new TextEncoder().encode(JSON.stringify(map)));
    return { alg:'AES-256-GCM', kdf:'PBKDF2-SHA256', iter: PF_KDF_ITER,
             salt: _pfB64(salt), iv: _pfB64(iv), ciphertext: _pfB64(new Uint8Array(ct)) };
  } catch(_) { return undefined; }
}
// 서버 암호문 블록 → 복호화 → 현재 종목에 평단가/수량/매입환율 병합. 반환: 적용 개수(복호화 실패 시 -1).
async function pfApplyEncHoldings(blob, opts) {
  opts = opts || {};
  if (!blob || typeof blob !== 'object' || !blob.ciphertext) return 0;
  let pass = pfGetHoldingsPass();
  if (!pass) {
    if (opts.silent) return 0;   // 자동 복원인데 암호 없음 → 조용히 건너뜀(수동 불러오기 때 입력 받음)
    pass = prompt('서버에 암호화된 평단가·수량이 있습니다.\n복호화 암호를 입력하세요(성공 시 이 기기에 저장됩니다):', '');
    if (pass === null || !pass.trim()) return 0;
    pass = pass.trim();
  }
  let map;
  try {
    const key = await _pfDeriveKey(pass, _pfUnB64(blob.salt));
    const pt = await crypto.subtle.decrypt({ name:'AES-GCM', iv: _pfUnB64(blob.iv) }, key, _pfUnB64(blob.ciphertext));
    map = JSON.parse(new TextDecoder().decode(pt));
  } catch(_) {
    if (!opts.silent && typeof showToast==='function') showToast('평단가 복호화 실패 — 암호가 일치하지 않습니다.', 4000);
    return -1;
  }
  if (!Array.isArray(map)) return 0;
  try { localStorage.setItem('pfHoldingsPass', pass); } catch(_) {}   // 복호화 성공 → 암호 기기에 저장
  let applied = 0;
  map.forEach(h => {
    if (!h || !h.s) return;
    const mk = h.m === 'US' ? 'US' : 'KR';
    const ex = pfState.items.find(it => it.symbol === h.s && it.market === mk);
    if (!ex) return;
    if (h.a != null) ex.avg = h.a;
    if (h.q != null) ex.qty = h.q;
    if (h.fx != null) ex.fxBuy = h.fx;
    applied++;
  });
  if (applied) { pfSave(); pfRenderAll(); }
  return applied;
}

// ── 페이지 초기화 ────────────────────────────────────────────────────────────
function initPortfolioPage() {
  let isFresh = false;
  if(!pfState) {
    try { isFresh = !localStorage.getItem(PF_LS_KEY); } catch(_) {}
    pfState = pfLoad();
  }
  if(!_pfInited) {
    _pfInited = true;
    pfFillGroupSelect(document.getElementById('pfAddGroup'));
    // 첫 방문(저장된 포트폴리오 없음) → 보유 ETF 9종 자동 등록
    if(isFresh && !pfState.seeded && !pfState.items.length) setTimeout(() => pfSeedDefaults(), 100);
    // 동기화 키가 설정된 기기에서는 서버 관심목록을 1회 자동 병합(비파괴)해 기기 간 목록을 맞춘다.
    // (첫 방문/시드 등록 중인 기기는 제외 — 시드 후 사용자가 직접 「☁ 목록 저장」으로 올린다.)
    else if(!isFresh) setTimeout(async () => {
      try { if(typeof pfGetSyncKeyHash === 'function' && await pfGetSyncKeyHash()) pfPullTracking(true); } catch(_) {}
    }, 600);
    // 적응형 자동 갱신: 한국/미국 장중 1분, 그 외 5분 (페이지가 활성일 때만)
    (function _pfSchedule() {
      const delay = (typeof window._isMarketActive === 'function' && window._isMarketActive()) ? 60000 : 300000;
      pfTimer = setTimeout(function() {
        const pg = document.getElementById('page-portfolio');
        if(pg && pg.classList.contains('active') && pfState.items.length) pfRefreshQuotes();
        _pfSchedule();
      }, delay);
    })();
    // ESC 로 모달 닫기
    document.addEventListener('keydown', e => {
      if(e.key === 'Escape') { pfCloseChart(); pfCloseAlerts(); }
    });
    // 탭 닫기/새로고침 시 서버 미저장 변경이 있으면 브라우저 기본 경고로 한 번 더 상기 (item 3)
    window.addEventListener('beforeunload', e => {
      if(_pfDirty && pfHasSyncKey()) { e.preventDefault(); e.returnValue = ''; return ''; }
    });
  }
  pfRenderAll();
  pfRefreshQuotes();
  if(typeof pfUpdateHoldingsSyncUI === 'function') pfUpdateHoldingsSyncUI();
}
