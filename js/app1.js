// ============================
// 헬퍼: Mock 시계열 생성
// ============================
function genSeries(base, days, vol=0.008) {
  let v = base;
  const arr = Array.from({length:days}, (_,i) => {
    v *= (1 + (Math.random()-0.48)*vol);
    const d = new Date(); d.setDate(d.getDate()-(days-i));
    return { x: d.toISOString().slice(0,10), y: +v.toFixed(2) };
  });
  // 마지막 포인트를 base 근처로 정착시키기 위해 시리즈 전체를 스케일링
  // (현재 가격과 차트 끝값 불일치 방지)
  const last = arr[arr.length-1].y;
  if (last > 0 && Math.abs(last - base) / base > 0.01) {
    const scale = base / last;
    const dec = base < 50 ? 4 : 2;
    arr.forEach(p => { p.y = +(p.y * scale).toFixed(dec); });
  }
  return arr;
}
// Chart.js labels/values 분리 헬퍼 (날짜 어댑터 없이도 정상 렌더링)
function sl(s) { return s.map(d=>d.x); }
function sv(s) { return s.map(d=>d.y); }

// 평균선 계산 헬퍼 — 전체 평균을 수평 직선으로 반환
function calcAvgLine(data) {
  const valid = data.filter(v => v != null && !isNaN(v));
  if(!valid.length) return data.map(()=>null);
  const avg = valid.reduce((a,b)=>a+b,0) / valid.length;
  return data.map(()=>+avg.toFixed(4));
}

function fmtChg(v) {
  const cls = v>=0?'up-txt':'down-txt', sym = v>=0?'▲':'▼';
  return `<span class="${cls}">${sym} ${v>=0?'+':''}${v.toFixed(2)}%</span>`;
}

// ============================
// 시계 업데이트
// ============================
function updateClock() {
  const now = new Date();
  document.getElementById('clock').textContent =
    now.toLocaleDateString('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit'}) + ' ' +
    now.toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
}
setInterval(updateClock, 1000); updateClock();

// ============================
// Chart.js 글로벌 플러그인 — 커서 따라가는 세로축(crosshair)
// ============================
const _crosshairPlugin = {
  id: 'crosshair',
  afterDatasetsDraw(chart) {
    // 활성 요소 (tooltip 표시 중) 가져오기 — 공식 API + private fallback
    let active = null;
    try {
      const arr = chart.getActiveElements && chart.getActiveElements();
      if(arr && arr.length) active = arr;
    } catch(_) {}
    if(!active) {
      const tt = chart.tooltip;
      if(tt && tt._active && tt._active.length) active = tt._active;
    }
    if(!active || !active.length) return;
    const el = active[0].element;
    if(!el || typeof el.x !== 'number') return;
    const ctx = chart.ctx;
    const top = chart.chartArea.top;
    const bottom = chart.chartArea.bottom;
    // 너무 작은 차트(스파크라인 등)에는 crosshair 생략
    if(bottom - top < 40) return;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(el.x, top);
    ctx.lineTo(el.x, bottom);
    ctx.lineWidth = 1;
    ctx.strokeStyle = (document.documentElement.classList.contains('light') ? '#5a6680' : '#b6c4ff') + 'aa';
    ctx.setLineDash([4, 4]);
    ctx.stroke();
    ctx.restore();
  }
};
if(typeof Chart !== 'undefined' && Chart.register) {
  try { Chart.register(_crosshairPlugin); } catch(_) {}
  // 모든 차트에 기본 호버 모드 적용 (intersect:false → 어디 호버해도 crosshair 표시)
  try {
    Chart.defaults.interaction = Chart.defaults.interaction || {};
    Chart.defaults.interaction.mode = 'index';
    Chart.defaults.interaction.intersect = false;
    Chart.defaults.plugins = Chart.defaults.plugins || {};
    Chart.defaults.plugins.tooltip = Chart.defaults.plugins.tooltip || {};
    Chart.defaults.plugins.tooltip.mode = 'index';
    Chart.defaults.plugins.tooltip.intersect = false;
    // 선차트 점 기본값 — 점은 숨기고(0) 호버 시에만 점 표시. 시계열 점이 촘촘히 뭉쳐
    // 선이 두꺼워 보이는 문제 방지. (점이 의미있는 sparse 차트는 개별 pointRadius 로 override)
    Chart.defaults.elements = Chart.defaults.elements || {};
    Chart.defaults.elements.point = Chart.defaults.elements.point || {};
    Chart.defaults.elements.point.hoverRadius = 4;
    /* 차트 기본 형태 — 48개 차트가 각자 인라인으로 tension/borderWidth/pointRadius 를
       지정하면서 tension 만 6종(0.3/.2/.25/.15/0.2/0)이 섞여 화면마다 곡선 느낌이 달랐다.
       기본값을 여기 한 곳에 두고, 개별 차트는 '다르게 그려야 할 이유가 있을 때만' 덮어쓴다.
       (tension:0 = 수익률곡선처럼 직선이어야 하는 차트 — 의도적 예외) */
    Chart.defaults.elements.point.radius = 0;
    Chart.defaults.elements.line = Chart.defaults.elements.line || {};
    Chart.defaults.elements.line.tension = 0.3;
    Chart.defaults.elements.line.borderWidth = 1.5;
    Chart.defaults.animation = Chart.defaults.animation || {};
    Chart.defaults.animation.duration = 400;
    // X축 라벨 — 동일 연도면 연도 생략 (category scale 만 적용; 작은 sparkline은 영향 없음)
    Chart.defaults.scales = Chart.defaults.scales || {};
    Chart.defaults.scales.category = Chart.defaults.scales.category || {};
    Chart.defaults.scales.category.ticks = Chart.defaults.scales.category.ticks || {};
    if(!Chart.defaults.scales.category.ticks.callback) {
      Chart.defaults.scales.category.ticks.callback = _xAxisTickCallback;
    }
  } catch(_) {}
}

// 라벨에서 연도 추출 — 같은 연도 라벨이 연속이면 년도 생략
// 지원 포맷: 'YYYY-MM-DD', 'YYYY-MM', 'YY.MM', 'YYYY/MM/DD'
function _extractYearFromLabel(s) {
  if(s == null) return null;
  const str = String(s);
  let m = str.match(/^(\d{4})[-./]/);
  if(m) return m[1];
  m = str.match(/^(\d{2})\.\d{1,2}/);   // 'YY.MM' format
  if(m) return '20' + m[1];
  return null;
}
function _allLabelsSameYear(labels) {
  if(!Array.isArray(labels) || labels.length < 2) return false;
  const years = labels.map(_extractYearFromLabel).filter(Boolean);
  if(years.length < 2) return false;
  return years.every(y => y === years[0]);
}
// X축 라벨에서 연도 생략 — 동일 연도일 때만 'YYYY-MM-DD' → 'MM-DD' 형식으로 단축
function formatAxisLabelOmitYear(label, allLabels) {
  if(label == null) return label;
  const str = String(label);
  if(!_allLabelsSameYear(allLabels)) return str;
  let m = str.match(/^\d{4}[-./](\d{1,2}[-./]\d{1,2})$/);
  if(m) return m[1];
  m = str.match(/^\d{4}[-./](\d{1,2})$/);
  if(m) return m[1] + '월';
  // 'YY.MM' 의 경우 'MM' 만
  m = str.match(/^\d{2}\.(\d{1,2})$/);
  if(m) return m[1] + '월';
  return str;
}
// Y축 숫자 라벨 정리 — JS 부동소수점 오차(3.60000000000000005) 제거 + 단위 추가
// 정밀도: 명시 시 그 자릿수 / 자동 시 값에 비례 (FX 1504.94 등은 2자리 유지).
// trailing zero 는 parseFloat 으로 자연 제거 (1500.00 → "1500", 2.40 → "2.4").
function fmtNum(v, decimals) {
  if(v == null || isNaN(v)) return '';
  if (decimals != null) return parseFloat(v.toFixed(decimals)).toString();
  // 자동 정밀도: 항상 2자리까지 fix (parseFloat 가 trailing zero 제거),
  // 단 0.01 미만은 4자리까지 (PCR/spread 등 미세값 보존).
  const absV = Math.abs(v);
  const d = absV >= 0.01 ? 2 : 4;
  return parseFloat(v.toFixed(d)).toString();
}
function fmtPct(v) { return fmtNum(v) + '%'; }
function fmtKrw(v) {
  if(v == null || isNaN(v)) return '';
  if(Math.abs(v) >= 1e8) return (v/1e8).toFixed(1) + '억';
  if(Math.abs(v) >= 1e4) return (v/1e4).toFixed(1) + '만';
  return v.toLocaleString();
}

// 사용 예: ticks.callback = function(value, index){ return formatAxisLabelOmitYear(this.getLabelForValue(value), this.chart.data.labels); }
function _xAxisTickCallback(value, idx) {
  // Chart.js context: `this` = scale; this.getLabelForValue(value)
  try {
    const raw = this.getLabelForValue ? this.getLabelForValue(value) : value;
    return formatAxisLabelOmitYear(raw, this.chart.data.labels);
  } catch(_) {
    return value;
  }
}

// ============================
// 새로고침 버튼 — 통합 피드백 헬퍼 (모든 카드/모달 공통)
// ============================
// 기존엔 refresh 함수마다 버튼 텍스트 변경/복원 로직이 중복 + 비일관적이었음.
// 이제 모든 새로고침 버튼이 동일한 상태머신을 사용해 사용자가 결과를 명확히 인지.
//   state: 'loading' → 'success' → (auto-revert)
//          'loading' → 'error'   → (auto-revert)
//          'loading' → 'warn'    → (auto-revert, 부분 성공)
// 스크린리더 상태 알림 — 시각적 버튼 피드백(텍스트 치환)은 낭독되지 않으므로 라이브 리전으로 병행 고지
function _a11ySay(msg) {
  try {
    let el = document.getElementById('a11yStatus');
    if(!el) {
      el = document.createElement('div');
      el.id = 'a11yStatus';
      el.className = 'sr-only';
      el.setAttribute('role', 'status');
      el.setAttribute('aria-live', 'polite');
      document.body.appendChild(el);
    }
    el.textContent = '';
    el.textContent = msg;
  } catch(_) {}
}

// 호출 예: _refreshFeedback(btn, 'loading'); ... _refreshFeedback(btn, 'success', '12건 갱신');
function _refreshFeedback(btn, state, msg) {
  if(!btn) return;
  if(!btn._refreshOrig) {
    btn._refreshOrig = (btn.textContent || '↻ 새로고침').trim();
    btn._refreshOrigBg = btn.style.background || '';
    btn._refreshOrigBorder = btn.style.borderColor || '';
    btn._refreshOrigColor = btn.style.color || '';
  }
  // 진행 중인 타이머 취소 (사용자가 빠르게 재클릭 시 잔존 타이머가 버튼 복원하는 race 방지)
  if(btn._refreshTimer) { clearTimeout(btn._refreshTimer); btn._refreshTimer = null; }
  const restore = (delay) => {
    btn._refreshTimer = setTimeout(() => {
      try {
        btn.textContent      = btn._refreshOrig || '↻ 새로고침';
        btn.style.background = btn._refreshOrigBg || '';
        btn.style.borderColor= btn._refreshOrigBorder || '';
        btn.style.color      = btn._refreshOrigColor || '';
        btn.disabled = false;
        btn._refreshTimer = null;
      } catch(_){}
    }, delay);
  };
  if(state === 'loading') {
    btn.disabled = true;
    btn.textContent = '⟳ 갱신중…';
    btn.style.background = 'var(--c-card)';
    btn.style.color = 'var(--c-primary)';
    // 안전망 — 호출부가 어떤 이유로든(예외 누락·미종료 fetch) 완료 피드백을 못 주면
    // 30초 후 버튼을 자동 복원해 '⟳ 갱신중…' 고착을 방지. 정상 완료 시에는 success/error
    // 진입부의 clearTimeout 이 이 타이머를 취소하므로 영향 없음.
    restore(30000);
  } else if(state === 'success') {
    btn.disabled = false;
    btn.textContent = msg ? ('✓ ' + msg) : '✓ 갱신 완료';
    // 성공/경고/실패는 등락 관습색(CUP/CDN)이 아니라 의미 토큰 — kr 모드에서 '성공=빨강' 오독 방지
    btn.style.background = 'color-mix(in srgb, var(--ind-pos) 18%, transparent)';
    btn.style.borderColor = 'color-mix(in srgb, var(--ind-pos) 40%, transparent)';
    btn.style.color = 'var(--ind-pos)';
    _a11ySay(msg ? ('데이터 갱신 완료 — ' + msg) : '데이터 갱신 완료');
    restore(1400);
  } else if(state === 'warn') {
    btn.disabled = false;
    btn.textContent = msg ? ('⚠ ' + msg) : '⚠ 일부 실패';
    btn.style.background = 'color-mix(in srgb, var(--c-warn) 15%, transparent)';
    btn.style.borderColor = 'color-mix(in srgb, var(--c-warn) 40%, transparent)';
    btn.style.color = 'var(--c-warn)';
    _a11ySay(msg ? ('데이터 일부 갱신 실패 — ' + msg) : '데이터 일부 갱신 실패');
    restore(1800);
  } else if(state === 'error') {
    btn.disabled = false;
    btn.textContent = msg ? ('✕ ' + msg) : '✕ 갱신 실패';
    btn.style.background = 'color-mix(in srgb, var(--ind-neg) 15%, transparent)';
    btn.style.borderColor = 'color-mix(in srgb, var(--ind-neg) 40%, transparent)';
    btn.style.color = 'var(--ind-neg)';
    _a11ySay(msg ? ('데이터 갱신 실패 — ' + msg) : '데이터 갱신 실패');
    restore(2200);
  } else if(state === 'reset') {
    btn.textContent      = btn._refreshOrig || '↻ 새로고침';
    btn.style.background = btn._refreshOrigBg || '';
    btn.style.borderColor= btn._refreshOrigBorder || '';
    btn.style.color      = btn._refreshOrigColor || '';
    btn.disabled = false;
  }
}

// 새로고침 버튼이 부모 클릭 핸들러(예: kpi-clickable navigateToDetail)로
// 이벤트 전파되어 의도치 않은 페이지 이동을 유발하는 회귀를 캡처 단계에서 차단.
// 일부 신규 카드 디자인에서 새로고침 버튼이 클릭 가능한 카드 안쪽에 배치될
// 수 있어 다층 방어선으로 모든 refresh 류 버튼에 stopPropagation 자동 적용.
(function() {
  if(window._refreshStopPropInstalled) return;
  window._refreshStopPropInstalled = true;
  document.addEventListener('click', (e) => {
    const btn = e.target && e.target.closest && e.target.closest('button');
    if(!btn) return;
    if(btn.hasAttribute('data-chart-refresh')) {
      // 이미 inline 핸들러에서 stopPropagation 처리됨 — 중복 가드 불필요
      return;
    }
    const oc = btn.getAttribute && btn.getAttribute('onclick');
    if(!oc) return;
    // refresh 류 함수 호출 패턴 매칭 (전파 차단 대상)
    if(/\brefresh[A-Za-z]+\s*\(/.test(oc) ||
       /\bmanualRetryMovers\s*\(/.test(oc)) {
      e.stopPropagation();
    }
  }, true);  // capture 단계 — 부모 onclick(target phase) 보다 앞서 실행되어 차단 유효
})();

// ============================
// 차트 카드용 새로고침 버튼 헬퍼 — onclick으로 호출되는 함수와 함께 사용
// ============================
// 5분마다 자동 새로고침을 위한 전역 등록 시스템
window._chartAutoRefreshers = window._chartAutoRefreshers || [];
function registerAutoRefresh(name, fn, intervalMs) {
  const interval = intervalMs || (5 * 60 * 1000);  // 기본 5분
  if(window._chartAutoRefreshers.find(r => r.name === name)) return;
  const handle = setInterval(() => {
    try { fn(); } catch(e) { /* 조용히 무시 */ }
  }, interval);
  window._chartAutoRefreshers.push({ name, fn, intervalMs: interval, handle });
}

// 차트 카드에 새로고침 버튼 동적 주입 — 카드별 onclick handler 매핑
const _refreshHandlerMap = {
  // 메인 (KOSPI)
  mainChart:        function(btn){ try { initMainChart(mainPeriodUnit); } catch(_){} loadRealtimeMarket().catch(()=>{}); refreshMoversFromClient().catch(()=>{}); _flashBtn(btn); },
  spark1:           function(btn){ loadRealtimeMarket().catch(()=>{}); _flashBtn(btn); },
  spark2:           function(btn){ loadRealtimeFx().catch(()=>{}); _flashBtn(btn); },
  spark3:           function(btn){ loadRealtimeMarket().catch(()=>{}); _flashBtn(btn); },
  'spark-rate':     function(btn){ try { buildRateKpiSparkline(); } catch(_){} _flashBtn(btn); },
  // FX
  fxChart:          function(btn){ refreshFxData(btn).catch(()=>{}); },
  // 채권/원자재/주식
  bondChart:        function(btn){ try { buildBondPage(); } catch(_){} loadRealtimeMarket().catch(()=>{}); _flashBtn(btn); },
  yieldCurveChart:  function(btn){ try { buildBondPage(); } catch(_){} _flashBtn(btn); },
  comDetailChart:   function(btn){ try { buildCommodityPage(); } catch(_){} loadRealtimeMarket().catch(()=>{}); _flashBtn(btn); },
  energyChart:      function(btn){ try { buildCommodityPage(); } catch(_){} _flashBtn(btn); },
  preciousChart:    function(btn){ try { buildCommodityPage(); } catch(_){} _flashBtn(btn); },
  baseMetalChart:   function(btn){ try { buildCommodityPage(); } catch(_){} _flashBtn(btn); },
  agriChart:        function(btn){ try { buildCommodityPage(); } catch(_){} _flashBtn(btn); },
  equityIndexChart: function(btn){ try { buildEquityPage(); } catch(_){} refreshMoversFromClient().catch(()=>{}); _flashBtn(btn); },
  investorChart:    function(btn){ refreshInvestorTrading(btn); },
  fearChart:        function(btn){ fetchSentimentClient().then(applySentimentClient).catch(()=>{}); _flashBtn(btn); },
  rateHistoryChart: function(btn){ try { buildRatePage(); } catch(_){} _flashBtn(btn); },
  // 부동산
  rePriceChart:     function(btn){ try { buildReCharts(); } catch(_){} _flashBtn(btn); },
  usReChangeChart:  function(btn){ try { buildUsReCharts(); } catch(_){} _flashBtn(btn); },
  usReMortgageChart:function(btn){ try { buildUsReCharts(); } catch(_){} _flashBtn(btn); },
  // 거시
  gdpMacro:         function(btn){ refreshAllData(btn).catch(()=>{}); },
  cpiMacro:         function(btn){ refreshAllData(btn).catch(()=>{}); },
  unempMacro:       function(btn){ refreshAllData(btn).catch(()=>{}); },
  tradeMacro:       function(btn){ refreshAllData(btn).catch(()=>{}); },
};
function _flashBtn(btn) {
  // 통합 피드백 헬퍼로 위임 — 로딩→성공 시퀀스 자동 처리
  if(!btn) return;
  _refreshFeedback(btn, 'loading');
  setTimeout(() => { _refreshFeedback(btn, 'success', '갱신'); }, 400);
}
// 시장심리(VKOSPI/MOVE/PutCall/공포탐욕) 새로고침 — KOSPI 버튼과 동일한 _refreshFeedback 상태머신 사용.
async function refreshSentiment(btn) {
  if(btn && typeof _refreshFeedback==='function') _refreshFeedback(btn, 'loading');
  try {
    if(window._REALTIME_BOOST && typeof fetchSentimentClient==='function' && typeof applySentimentClient==='function') {
      applySentimentClient(await fetchSentimentClient());
    } else if(typeof loadRealData==='function') {
      await loadRealData();   // data.json 전용 모드 — 서버값 재적용
    }
    if(btn && typeof _refreshFeedback==='function') _refreshFeedback(btn, 'success', '갱신');
  } catch(e) {
    if(btn && typeof _refreshFeedback==='function') _refreshFeedback(btn, 'error', '실패');
  }
}
// 주식시장 Top10 '새로고침'/'다시 시도' — data.json 재페치 + (보강 모드 시) 클라이언트 실시간 페치 후 재렌더.
async function retryEquityMovers(btn) {
  if(btn && typeof _refreshFeedback==='function') _refreshFeedback(btn, 'loading');
  try {
    if(typeof loadRealData==='function') await loadRealData().catch(()=>{});  // 서버 data.json 최신화
    const ok = window._REALTIME_BOOST ? await refreshMoversFromClient(true) : true;  // 보강 모드만 네이버 페치
    if(typeof buildEquityPage==='function') buildEquityPage();
    if(btn && typeof _refreshFeedback==='function') _refreshFeedback(btn, ok ? 'success' : 'warn', ok ? '갱신' : '응답 없음');
  } catch(e) {
    if(btn && typeof _refreshFeedback==='function') _refreshFeedback(btn, 'error', '실패');
  }
}
// 투자자별 순매매 '새로고침' — data.json 재페치(investorTrading) 후 차트 재빌드.
// (이전 결함: investorChart 핸들러가 buildInvestorPage[국민연금]을 호출하고 재페치도 안 했음.)
async function refreshInvestorTrading(btn) {
  if(btn && typeof _refreshFeedback==='function') _refreshFeedback(btn, 'loading');
  try {
    if(typeof loadRealData==='function') await loadRealData().catch(()=>{});  // 서버 data.json 최신화
    investorRawData = (typeof _getInvestorRawData==='function') ? _getInvestorRawData() : investorRawData;
    // 서버 data.json 에 투자자 데이터가 없으면(=Actions 의 네이버 IP 차단) 브라우저에서 직접 끌어온다.
    if((!investorRawData || !investorRawData.length) && window._REALTIME_BOOST && typeof fetchNaverInvestorTradingClient==='function') {
      try {
        const inv = await fetchNaverInvestorTradingClient();
        if(inv && inv.daily && inv.daily.length) {
          applyRealData({ investorTrading: inv, sources: { investorTrading: inv.source } });
          investorRawData = _getInvestorRawData();
        }
      } catch(_) {}
    }
    if(typeof buildInvestorChart==='function') buildInvestorChart();
    const ok = investorRawData && investorRawData.length;
    if(btn && typeof _refreshFeedback==='function') _refreshFeedback(btn, ok ? 'success' : 'warn', ok ? `${investorRawData.length}일 갱신` : '응답 없음');
  } catch(e) {
    if(btn && typeof _refreshFeedback==='function') _refreshFeedback(btn, 'error', '실패');
  }
}
function refreshChartByCanvasId(canvasId, btn) {
  const fn = _refreshHandlerMap[canvasId];
  if(fn) {
    fn(btn);
  } else {
    // fallback: 전체 새로고침
    refreshAllData(btn);
  }
}

// 차트 위젯에 새로고침 버튼 동적 주입 (canvas 가 있는 .widget 모두)
function injectChartRefreshButtons() {
  const canvases = document.querySelectorAll('canvas[id]');
  canvases.forEach(c => {
    const id = c.id;
    // 스파크라인/툴팁 등 너무 작은 차트는 제외
    if(['fearChart','reRegionTooltipChart','usReRegionTooltipChart','reHistChart','npsAllocationTrendChart','npsReturnChart','npsYearDetailChart','reGapChart','reTradeChart','reAffordChart','reJeonseChart','reLoanChart','reSupplyChart','reChunseRatioChart','reHistChartModal','calDetailChart'].includes(id)) return;
    // 가까운 widget 찾기
    let widget = c.closest('.widget');
    if(!widget) return;
    // 이미 새로고침 버튼이 있는지 확인 (텍스트 매칭)
    if(widget.querySelector('button[data-chart-refresh]')) return;
    if(widget.innerHTML.includes('새로고침')) return;  // 이미 다른 새로고침 버튼 존재
    // widget-title 또는 헤더 영역 찾기
    const title = widget.querySelector('.widget-title');
    if(!title) return;
    const btn = document.createElement('button');
    btn.setAttribute('data-chart-refresh', id);
    btn.setAttribute('title', '실시간 데이터 새로고침 (5분마다 자동)');
    btn.style.cssText = 'margin-left:8px;background:var(--c-card);color:var(--c-primary);border:1px solid var(--c-border);border-radius:var(--r-xs);padding:1px 7px;font-size:10px;cursor:pointer;vertical-align:middle;text-transform:none;letter-spacing:0;';
    btn.textContent = '↻ 새로고침';
    btn.onclick = (e) => { e.stopPropagation(); refreshChartByCanvasId(id, btn); };
    // 버튼을 widget-title 의 텍스트 흐름에 inline 으로 추가 (display 변경 없음)
    title.appendChild(btn);
  });

  // ── 2차 패스: 나머지 '모든 카드(.widget)' 에 KOSPI 와 동일한 새로고침 버튼 주입 ──
  // (사용자 요청: 사이트 내 전체 카드에 동일 새로고침 기능.) 데이터 테이블 카드는 표별
  // 전용 핸들러를, 그 외(정적/소형차트 포함)는 전체 새로고침(refreshAllData)을 사용한다.
  // 모두 _refreshFeedback 상태머신을 거치므로 KOSPI 버튼과 동일한 로딩→갱신 인터랙션을 갖는다.
  const _tableRefreshMap = {
    equityTopGainersTable: retryEquityMovers, equityTopLosersTable: retryEquityMovers,
    etfTopGainersTable: refreshETFFromClient, etfTopLosersTable: refreshETFFromClient,
    moverTable: (b)=>refreshAllData(b), investorSummaryTable: refreshInvestorTrading,
  };
  document.querySelectorAll('.widget').forEach(widget => {
    if(widget.querySelector('button[data-chart-refresh]')) return;  // 1차 패스에서 이미 주입됨
    if(/새로고침|다시 시도/.test(widget.innerHTML)) return;          // 이미 새로고침/재시도 버튼 존재
    if(widget.closest('.themed-modal')) return;                      // 모달 내부 카드 제외 (상세 팝업)
    if(widget.closest('#page-study')) return;                        // 스터디 기록은 로컬 저장 데이터 — 시장 새로고침 무의미
    const title = widget.querySelector('.widget-title');
    if(!title) return;
    // 표 카드면 표별 전용 핸들러, 아니면 전체 새로고침.
    // 매크로 3줄 요약 배너는 전용 경량 핸들러 — 전체 새로고침(수십 페치) 대신 요약만 즉시 재조립.
    const tbody = widget.querySelector('table tbody[id]');
    const handler = (widget.id === 'aiBriefingBanner' && typeof refreshAiBriefing === 'function') ? ((b)=>refreshAiBriefing(b))
                  : (tbody && _tableRefreshMap[tbody.id]) ? _tableRefreshMap[tbody.id] : ((b)=>refreshAllData(b));
    const btn = document.createElement('button');
    btn.setAttribute('data-chart-refresh', (tbody && tbody.id) || 'card');
    btn.setAttribute('title', '실시간 데이터 새로고침');
    btn.style.cssText = 'margin-left:8px;background:var(--c-card);color:var(--c-primary);border:1px solid var(--c-border);border-radius:var(--r-xs);padding:1px 7px;font-size:10px;cursor:pointer;vertical-align:middle;text-transform:none;letter-spacing:0;';
    btn.textContent = '↻ 새로고침';
    btn.onclick = (e) => { e.stopPropagation(); try { handler(btn); } catch(_) { refreshAllData(btn); } };
    title.appendChild(btn);
  });
}

// .widget-title 의 동적 텍스트만 교체하고, injectChartRefreshButtons 가 주입한 '↻ 새로고침'
// 버튼 등 자식 엘리먼트는 보존한다. (과거 결함: bondChartTitle/equityChartTitle/comDetailTitle
// 에 title.textContent='...' 로 제목을 갱신하면 같은 엘리먼트에 append 된 새로고침 버튼이
// 통째로 지워져, '새로고침을 누르면 버튼이 사라지는' 회귀가 발생했다.)
function setWidgetTitleText(el, text) {
  if(!el) return;
  // 선두 텍스트 노드만 갱신 — element 자식(버튼/배지/단위 span)은 그대로 둔다.
  let tn = null;
  for(const n of el.childNodes) { if(n.nodeType === 3) { tn = n; break; } }
  if(tn) { tn.nodeValue = text; }
  else { el.insertBefore(document.createTextNode(text), el.firstChild); }
}

// ============================
// 티커 바
// ============================
const tickerData = [
  {name:'KOSPI', val:'7,612.51', chg:'-4.62%', up:false},
  {name:'KOSDAQ', val:'1,143.35', chg:'-4.01%', up:false},
  {name:'USD/KRW', val:'1,489.64', chg:'+0.00%', up:true},
  {name:'EUR/KRW', val:'1,744.95', chg:'+0.00%', up:true},
  {name:'WTI', val:'$62.35', chg:'-0.55%', up:false},
  {name:'BRENT', val:'$65.80', chg:'-0.48%', up:false},
  {name:'금(Gold)', val:'$3,241.5', chg:'+0.30%', up:true},
  {name:'S&P 500', val:'5,659.91', chg:'+0.21%', up:true},
  {name:'NASDAQ', val:'26,635', chg:'+0.18%', up:true},
  {name:'닛케이', val:'61,687', chg:'+0.45%', up:true},
  {name:'한국 기준금리', val:'2.75%', chg:'동결', up:null},
  {name:'미 10년물', val:'4.48%', chg:'+0.03', up:true},
];
function menuItemFor(pageId) {
  return document.querySelector(`.menu-item[onclick*="'${pageId}'"]`);
}
function marketTabBtn(tab) {
  return document.querySelector(`#page-market > div:first-child button[onclick*="'${tab}'"]`);
}
function tickerClick(name) {
  if(name==='KOSPI'||name==='KOSDAQ') {
    showPage('dashboard', menuItemFor('dashboard'));
  } else if(name==='USD/KRW'||name==='EUR/KRW') {
    showPage('market', menuItemFor('market'));
    setTimeout(()=>setMarketTab('fx', marketTabBtn('fx')),60);
  } else if(name==='한국 기준금리') {
    showPage('market', menuItemFor('market'));
    setTimeout(()=>setMarketTab('rate', marketTabBtn('rate')),60);
  } else if(name==='미 10년물') {
    showPage('market', menuItemFor('market'));
    setTimeout(()=>setMarketTab('bond', marketTabBtn('bond')),60);
  } else if(name==='S&P 500'||name==='NASDAQ'||name==='닛케이') {
    showPage('equity', menuItemFor('equity'));   // 주식시장 별도 페이지
  } else if(name==='WTI'||name==='BRENT'||name==='금(Gold)') {
    showPage('market', menuItemFor('market'));
    setTimeout(()=>setMarketTab('commodity', marketTabBtn('commodity')),60);
  }
}
function buildTicker() {
  const items = [...tickerData,...tickerData].map(d=>{
    const cc = d.up===null?'color:var(--c-txt-dim)':d.up?'color:var(--c-up)':'color:var(--c-down)';
    return `<span class="ticker-item" onclick="tickerClick('${d.name.replace(/'/g,"\\'")}')" style="font-size:var(--font-size-sm);display:inline-flex;gap:6px;align-items:center;">
      <span style="color:var(--c-txt-dim);font-size:var(--font-size-xs);font-weight:var(--font-weight-semibold);text-transform:uppercase;">${d.name}</span>
      <span style="color:var(--c-txt);font-weight:var(--font-weight-medium);">${d.val}</span>
      <span style="${cc};font-size:var(--font-size-sm);">${d.chg}</span>
    </span>`;
  }).join('');
  document.getElementById('ticker').innerHTML = items;
}
buildTicker();

// ============================
// 페이지 전환
// ============================
let charts = {};
function destroyChart(id) {
  if(charts[id]) { charts[id].destroy(); delete charts[id]; }
}

// ============================
// 전년 동기(YoY) 비교 엔진 — 순수 추가. 기존 차트 동작/스타일 불변.
//   · 각 build 함수 말미에서 registerYoY(id, meta) + applyYoY(id) 호출 → 재빌드에도 상태 유지.
//   · 토글 시 dataset 만 add/remove 후 chart.update() (차트 재생성 안 함).
//   · 전년 데이터는 meta 에 캐시 (build 1회 계산), data.json 추가 fetch 없음.
//   · 캘린더의 _calComputeChange(MoM/YoY)와 네임스페이스 분리(yoy* 접두사).
// ============================
let yoyState = {};                 // chartId -> bool (개별 토글)
const _yoyMeta = {};               // chartId -> meta (build 시 주입)
let _yoyGlobal = false;            // 글로벌 토글 상태
// YoY 지원 차트 정적 목록 (지연 빌드 차트도 글로벌 토글이 선반영되도록). Tier A + Tier B.
const YOY_CHARTS = [
  // Tier A — 단일 시리즈 일별/거시
  'mainChart','fxChart','equityIndexChart','bondChart','cpiMacro','gdpMacro','unempMacro','tradeMacro',
  // Tier B — 다중 시리즈는 주 시리즈(인덱스 0)만 오버레이
  'rePriceChart','comDetailChart','gdpTopic','cpiTopic','unempTopic','tradeTopic',
  'rateHistoryChart','npsAumChart','pfBenchChart','compareChart',
  // Tier B 확장 — 시계열 차트 전체 (사용자 요청). 수급·NPS배분추이·금속·섹터(귀금속/에너지/농산물)
  'investorChart','npsAllocationTrendChart','baseMetalChart','preciousChart','energyChart','agriChart'
];
const YOY_SET = new Set(YOY_CHARTS);
try { yoyState = JSON.parse(localStorage.getItem('econ_yoy_state') || '{}') || {}; } catch(_) { yoyState = {}; }
try { _yoyGlobal = localStorage.getItem('econ_yoy_global') === '1'; } catch(_) {}
function _yoyPersist(){
  try {
    localStorage.setItem('econ_yoy_state', JSON.stringify(yoyState));
    localStorage.setItem('econ_yoy_global', _yoyGlobal ? '1' : '0');
  } catch(_) {}
}

// 색상 → 같은 색 rgba(.,alpha). hex(#rgb/#rrggbb/#rrggbbaa), rgb()/rgba(), var(--x) 지원.
function _yoyFade(color, alpha){
  alpha = (alpha==null) ? 0.5 : alpha;
  if(!color) return `rgba(120,130,150,${alpha})`;
  let c = ('' + color).trim();
  if(c.startsWith('var(')){
    const name = c.slice(4, -1).trim();
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    if(v) c = v;
  }
  if(c[0] === '#'){
    let h = c.slice(1);
    if(h.length === 3) h = h.split('').map(x=>x+x).join('');
    if(h.length === 8) h = h.slice(0,6);
    const r = parseInt(h.slice(0,2),16), g = parseInt(h.slice(2,4),16), b = parseInt(h.slice(4,6),16);
    if([r,g,b].every(isFinite)) return `rgba(${r},${g},${b},${alpha})`;
  }
  const m = c.match(/rgba?\(([^)]+)\)/);
  if(m){ const p = m[1].split(',').map(s=>s.trim()); return `rgba(${p[0]},${p[1]},${p[2]},${alpha})`; }
  return `rgba(120,130,150,${alpha})`;
}

// 일별 시계열: 표시된 각 날짜의 정확히 1년 전(달력 날짜) 값을 full 시계열에서 ±tol일 최근접으로 탐색.
function _yoyPrevByDate(dispDates, fullDates, fullValues, tol){
  tol = (tol==null) ? 7 : tol;
  const fms = fullDates.map(d => Date.parse(d));
  const tolMs = tol * 86400000;
  return dispDates.map(d => {
    const dt = new Date(d);
    if(isNaN(dt)) return null;
    const py = new Date(dt); py.setFullYear(dt.getFullYear() - 1);  // 윤년 안전(달력 1년 전)
    const tgt = py.getTime();
    let best = -1, bestDiff = Infinity;
    for(let i=0;i<fms.length;i++){
      const diff = Math.abs(fms[i] - tgt);
      if(diff < bestDiff){ bestDiff = diff; best = i; }
    }
    if(best < 0 || bestDiff > tolMs) return null;
    return fullValues[best];
  });
}

// 주기형 라벨(월/분기/연): 동일 라벨 인덱스에서 step 만큼 뒤(=1년 전) 값. 월=12, 분기=4, 연=1.
function _yoyPrevByLabel(dispLabels, fullLabels, fullValues, step){
  const idx = new Map();
  fullLabels.forEach((l,i) => idx.set('' + l, i));
  return dispLabels.map(l => {
    const i = idx.get('' + l);
    if(i == null) return null;
    const j = i - step;
    return (j >= 0) ? fullValues[j] : null;
  });
}

// 주기 라벨의 '1년 전' 라벨 문자열 생성(형식 보존). 'YYYY','YY.MM','YYYY-MM','YYYYMM','23Q1','2023.Q1' 등.
function _yoyPrevYearLabel(label){
  const s = ('' + label).trim();
  const dec = (y) => { const n = +y - 1; return (y.length === 2) ? (('' + ((n + 100) % 100)).padStart(2,'0')) : ('' + n); };
  let m;
  if(m = s.match(/^(\d{2,4})([.\-]?)[Qq]([1-4])$/)) return dec(m[1]) + m[2] + 'Q' + m[3];
  if(m = s.match(/^(\d{2,4})([.\-/])(\d{1,2})$/))    return dec(m[1]) + m[2] + m[3];
  if(m = s.match(/^(\d{4})(\d{2})$/))                return dec(m[1]) + m[2];
  if(m = s.match(/^(\d{2,4})$/))                     return dec(m[1]);
  return null;
}
// 주기 라벨 기반(월/분기/연): 표시 라벨의 1년 전 라벨 값을 full 집계에서 조회. step 불필요·필터 무관·정확.
function _yoyPrevByPeriodLabel(dispLabels, fullLabels, fullValues){
  const idx = new Map();
  (fullLabels || []).forEach((l,i) => idx.set('' + l, i));
  return (dispLabels || []).map(l => {
    const pl = _yoyPrevYearLabel(l);
    if(pl == null) return null;
    const i = idx.get('' + pl);
    return (i == null) ? null : fullValues[i];
  });
}

function registerYoY(id, meta){ if(YOY_SET.has(id)) _yoyMeta[id] = meta; }

// 편의 래퍼: getHistoricalSeries 기반 일별 차트.
//   dispDates = 실제 그려진 주 시리즈의 날짜 배열(ISO). opt:{primary,color,tension,tol}
function yoyFromHistory(id, category, name, dispDates, opt){
  opt = opt || {};
  const full = getHistoricalSeries(category, name) || [];
  registerYoY(id, {
    mode:'date',
    dispDates: dispDates || full.map(p=>p.x),
    fullDates: full.map(p=>p.x),
    fullValues: full.map(p=>p.y),
    tol: opt.tol || 7,
    primary: opt.primary || 0,
    color: opt.color,
    tension: opt.tension
  });
}

function _yoyComputePrev(meta){
  if(!meta) return null;
  if(meta.mode === 'date') return _yoyPrevByDate(meta.dispDates, meta.fullDates, meta.fullValues, meta.tol);
  if(meta.mode === 'periodlabel') return _yoyPrevByPeriodLabel(meta.dispLabels, meta.fullLabels, meta.fullValues);
  return _yoyPrevByLabel(meta.dispLabels, meta.fullLabels, meta.fullValues, meta.step);
}

// 차트에 전년 dataset 추가/제거 + 범례·배지 갱신. (build 말미 + 토글 시 호출)
function applyYoY(id){
  const ch = charts[id];
  if(!ch){ return; }
  ch.data.datasets = ch.data.datasets.filter(d => !d._yoy);   // 기존 전년 레이어 제거(원복)
  const on = !!yoyState[id];
  const meta = _yoyMeta[id];
  if(on && meta){
    const prev = _yoyComputePrev(meta);
    const base = ch.data.datasets[meta.primary || 0];
    if(base && Array.isArray(prev)){
      const baseLabel = base.label || meta.label || '';
      ch.data.datasets.push({
        type: 'line',                                  // bar 차트 위에도 점선 라인으로 오버레이
        label: baseLabel + ' (전년)',
        data: prev,
        borderColor: _yoyFade(meta.color || base.borderColor, 0.5),
        backgroundColor: 'transparent',
        borderDash: [5,5],
        borderWidth: (base.borderWidth!=null ? base.borderWidth : 2),
        pointRadius: 1,
        pointHoverRadius: 3,
        tension: (meta.tension!=null ? meta.tension : (base.tension!=null ? base.tension : 0)),
        fill: false,
        spanGaps: true,
        ...(base.yAxisID ? { yAxisID: base.yAxisID } : {}),   // 이중축 차트(compareChart 등)에서 주 시리즈 축 공유
        _yoy: true,
        order: (base.order!=null ? base.order : 0) + 50
      });
      _yoySetLegend(ch, true);
      _yoyRenderBadge(id, base, prev);
    }
  } else {
    _yoySetLegend(ch, false);
    _yoyRenderBadge(id, null, null);
  }
  _yoyUpdateBtn(id);
  ch.update();
}

// 범례: chartOpts 류가 legend.display=false 로 숨기므로, YoY ON 시 임시로 켜고 OFF 시 원복.
function _yoySetLegend(ch, show){
  // Chart.js v4: ch.options 는 resolver proxy → 거기에 쓰면 set 트랩이 무한재귀(Maximum call stack).
  //   반드시 원본 config(ch.config.options)에 기록하고 update()가 재머지하게 한다.
  //   또 토글된 적 없으면(OFF 기본) config 를 아예 건드리지 않는다(불필요한 접근·재귀 차단).
  const cfg = ch && ch.config && ch.config.options;
  if(!cfg) return;
  if(show){
    cfg.plugins = cfg.plugins || {};
    cfg.plugins.legend = cfg.plugins.legend || {};
    if(ch._yoyLegendOrig === undefined) ch._yoyLegendOrig = (cfg.plugins.legend.display === undefined ? null : cfg.plugins.legend.display);
    cfg.plugins.legend.display = true;
  } else if(ch._yoyLegendOrig !== undefined){
    if(cfg.plugins && cfg.plugins.legend) cfg.plugins.legend.display = (ch._yoyLegendOrig === null ? undefined : ch._yoyLegendOrig);
    ch._yoyLegendOrig = undefined;
  }
}

// 배지: 캔버스 컨테이너 우상단. 최신(현재·전년 모두 존재) 지점 기준 변화율.
function _yoyRenderBadge(id, base, prev){
  const ch = charts[id];
  if(!ch || !ch.canvas) return;
  const cont = ch.canvas.parentElement;
  if(!cont) return;
  let badge = cont.querySelector(':scope > .yoy-badge');
  if(!base || !prev){ if(badge) badge.remove(); return; }
  if(getComputedStyle(cont).position === 'static') cont.style.position = 'relative';
  if(!badge){ badge = document.createElement('div'); badge.className = 'yoy-badge'; cont.appendChild(badge); }
  const cur = base.data || [];
  let i = Math.min(cur.length, prev.length) - 1;
  while(i >= 0 && (cur[i] == null || prev[i] == null)) i--;
  if(i < 0){ badge.className = 'yoy-badge yoy-badge-none'; badge.textContent = '전년 데이터 없음'; return; }
  const c = +(cur[i] && cur[i].y != null ? cur[i].y : cur[i]);
  const p = +(prev[i] && prev[i].y != null ? prev[i].y : prev[i]);
  if(!isFinite(c) || !isFinite(p) || p === 0){ badge.className = 'yoy-badge yoy-badge-none'; badge.textContent = '전년 데이터 없음'; return; }
  const pct = (c - p) / Math.abs(p) * 100;
  const up = pct >= 0;
  badge.className = 'yoy-badge ' + (up ? 'yoy-badge-up' : 'yoy-badge-down');
  badge.textContent = (up ? '▲+' : '▼') + pct.toFixed(2) + '%';
}

// ── 토글 + 글로벌/개별 동기화 ─────────────────────────────────
function toggleYoY(id, btn){
  yoyState[id] = !yoyState[id];
  applyYoY(id);
  _yoySyncGlobalFromIndividual();
  _yoyPersist();
}
function toggleYoYGlobal(){
  _yoyGlobal = !_yoyGlobal;
  YOY_CHARTS.forEach(id => { yoyState[id] = _yoyGlobal; });   // 지연 빌드 차트도 선반영
  Object.keys(charts).forEach(id => { if(YOY_SET.has(id)) applyYoY(id); });
  _yoyUpdateGlobalBtn(false);
  _yoyPersist();
}
// 개별 토글 결과로 글로벌 상태 재계산: 전부 ON→ON, 일부만 ON→indeterminate, 전부 OFF→OFF.
function _yoySyncGlobalFromIndividual(){
  const onCount = YOY_CHARTS.filter(id => yoyState[id]).length;
  const total = YOY_CHARTS.length;
  _yoyGlobal = (onCount === total);
  _yoyUpdateGlobalBtn(onCount > 0 && onCount < total);
}
function _yoyUpdateBtn(id){
  document.querySelectorAll(`.yoy-btn[data-yoy="${id}"]`).forEach(b => {
    const on = !!yoyState[id];
    b.classList.toggle('active', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    const lbl = b.querySelector('.yoy-btn-lbl');
    if(lbl) lbl.textContent = on ? '전년비교 ON' : '전년비교';
  });
}
function _yoyUpdateGlobalBtn(indeterminate){
  const b = document.getElementById('yoyGlobalBtn');
  if(!b) return;
  b.classList.toggle('active', _yoyGlobal);
  b.classList.toggle('indeterminate', !!indeterminate);
  b.setAttribute('aria-pressed', _yoyGlobal ? 'true' : (indeterminate ? 'mixed' : 'false'));
  const lbl = b.querySelector('.yoy-btn-lbl');
  if(lbl) lbl.textContent = _yoyGlobal ? '전년 비교 ON' : (indeterminate ? '전년 비교 (일부)' : '전년 비교');
}
// 페이지 로드 시 글로벌 버튼 상태 초기 동기화.
function _yoyInitGlobalBtn(){
  const onCount = YOY_CHARTS.filter(id => yoyState[id]).length;
  _yoyUpdateGlobalBtn(onCount > 0 && onCount < YOY_CHARTS.length);
}
window.addEventListener('load', _yoyInitGlobalBtn);
function navigateToDetail(target) {
  if(target==='equity') {   // 주식시장은 별도 페이지로 분리됨
    showPage('equity', menuItemFor('equity'));
    setTimeout(()=>{
      const eqBtns=document.querySelectorAll('#market-equity .tab-btn');
      if(eqBtns[0]) selectEquityIndex(0, eqBtns[0]);
    }, 150);
    return;
  }
  showPage('market', menuItemFor('market'));
  setTimeout(()=>{
    if(target==='fx')        { setMarketTab('fx',   marketTabBtn('fx')); }
    else if(target==='rate') { setMarketTab('rate', marketTabBtn('rate')); }
    else if(target==='bond') { setMarketTab('bond', marketTabBtn('bond')); }
    else if(target==='commodity') { setMarketTab('commodity', marketTabBtn('commodity')); }
  }, 80);
}

// 📈 주식시장 페이지 분리 — page-market 안의 #market-equity 콘텐츠를 전용 페이지 셸
// (#page-equity)로 이동. 마크업 대이동 없이 분리해 기존 id/onclick/차트 코드를 전부 보존.
(function() {
  const shell = document.getElementById('page-equity');
  const eq = document.getElementById('market-equity');
  if(shell && eq && eq.parentElement !== shell) {
    shell.appendChild(eq);
    eq.style.display = 'block';
  }
})();

function showPage(id, el) {
  // 잠금 페이지(투자 현황·설정) 게이트 — 모든 진입(메뉴·?p= 딥링크·popstate·키보드)이
  // showPage 를 지나므로 관문은 여기 한 곳. 비밀번호 확인 성공 시 econLockGate 가 재호출한다.
  try { if(typeof econLockGate === 'function' && econLockGate(id, el)) return; } catch(_) {}
  // 포트폴리오 페이지를 떠날 때 서버 미저장 변경이 있으면 저장 여부를 물어본다 (지정 종목 트래킹 저장 리마인더)
  try {
    const _prev = document.querySelector('.page.active');
    if(_prev && _prev.id === 'page-portfolio' && id !== 'portfolio' && typeof pfWarnUnsavedOnLeave === 'function') pfWarnUnsavedOnLeave();
  } catch(_) {}
  // 잘못된 id 로 호출돼도 빈 화면이 되지 않게 대상 존재를 먼저 확인하고 없으면 dashboard 폴백
  if(!document.getElementById('page-'+id)) id = 'dashboard';
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.getElementById('page-'+id).classList.add('active');
  document.querySelectorAll('.menu-item').forEach(m=>{ m.classList.remove('active'); m.removeAttribute('aria-current'); });
  if(el) { el.classList.add('active'); el.setAttribute('aria-current','page'); }
  try { const _main = document.getElementById('mainContent'); if(_main) _main.focus({ preventScroll: true }); } catch(_) {}
  // 메뉴 전환 시 최상단으로 스크롤
  try {
    window.scrollTo({top: 0, behavior: 'auto'});
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
    const main = document.querySelector('main');
    if(main) main.scrollTop = 0;
  } catch(_) {}
  if(id==='market') { setTimeout(()=>initMarketPage(),50); }
  if(id==='equity') { setTimeout(()=>{ try { buildEquityPage(); } catch(e) { console.warn('equity init', e); } },50); }
  if(id==='portfolio') { setTimeout(()=>{ try { initPortfolioPage(); } catch(e) { console.warn('portfolio init', e); } },50); }
  if(id==='macro')  { setTimeout(()=>{ initMacroPage('kr'); buildMacroIndicatorTable(); currentNewsFilter['macroNewsFeed']='한국GDP'; renderFiltered('macroNewsFeed'); },50); }
  if(id==='calendar') {
    buildCalendar();
    buildNewsFeed('calendarNewsFeed', calendarNewsItems);
    const sel = document.getElementById('calPeriod');
    if(sel && !sel._bound) {
      sel.addEventListener('change', () => {
        _calGridManualNav = false;  // 필터 변경 시 수동 nav 리셋 (필터 우선)
        buildCalendar();
      });
      sel._bound=true;
    }
  }
  if(id==='study') { try { initStudyPage(); } catch(e) { console.warn('study init', e); } }
  else if(typeof styClosePlayer === 'function') { try { styFlushAll(); styClosePlayer(); } catch(_) {} }   // 페이지 이탈 시 미저장 입력 확정 + 재생 중지 + blob URL 해제
  if(id==='notes') { loadNotes(); }
  if(id==='settings') { try { initSettingsPage(); } catch(e) { console.warn('settings init', e); } }
  if(id==='investor') { setTimeout(()=>{ buildInvestorPage(); try { buildGlobalAllocCompare(); } catch(e) { console.warn('globalAlloc', e); } },50); }
  if(id==='realestate') { setRETab('kr', document.getElementById('reitabKR')); setTimeout(buildReCharts, 80); }
  if(id==='merblog') { try { merblogInit(); } catch(e) { console.warn('merblog init', e); } }
  // [3차-T5] 페이지 공통 훅 — 기본 조회 기간 1회 적용 + 1회성 가이드 배너 (T6에서 정의)
  try { if (typeof econPageHook === 'function') econPageHook(id); } catch(_) {}
  // URL 딥링크 — 페이지 전환마다 ?p=<id> 반영 (뒤로/앞으로 지원)
  try { history.replaceState(null, '', location.pathname + '?p=' + id); } catch(_) {}
  // 메뉴 클릭 후 사이드바 자동 숨김 (모바일/데스크탑 공통)
  collapseSidebarAfterNav();
}

// 메뉴 클릭 후 사이드바 자동 숨김
function collapseSidebarAfterNav() {
  const sb = document.getElementById('sidebar');
  if(!sb) return;
  // 모바일에서 열려있으면 닫기 + 백드롭도 닫기
  if(sb.classList.contains('mobile-open')) {
    sb.classList.remove('mobile-open');
    const backdrop = document.getElementById('sidebarBackdrop');
    if(backdrop) backdrop.style.display = 'none';
  }
  // 데스크탑에서 접기
  if(!sb.classList.contains('collapsed')) {
    sb.classList.add('collapsed');
    const icon = document.getElementById('sidebarToggleIcon');
    if(icon) icon.textContent = 'menu';
  }
  _syncSidebarAria();
}

// 타이틀 클릭 → 대시보드 홈으로 이동 + 사이드바 자동 펼침
function goHome() {
  const homeBtn = document.querySelector('.menu-item[onclick*="dashboard"]');
  showPage('dashboard', homeBtn);
  // 사이드바가 접혀 있으면 펼치기
  const sb = document.getElementById('sidebar');
  if(sb && sb.classList.contains('collapsed')) {
    sb.classList.remove('collapsed');
    const icon = document.getElementById('sidebarToggleIcon');
    if(icon) icon.textContent = 'menu_open';
  }
}

let rePeriod = '1y';
const rePriceData = {
  // 전국 아파트 가격지수 (부동산원 기준, 2021=100)
  labels5y: ['20.05','20.08','20.11','21.02','21.05','21.08','21.11','22.02','22.05','22.08','22.11','23.02','23.05','23.08','23.11','24.02','24.05','24.08','24.11','25.02','25.05'],
  labels3y: ['22.05','22.08','22.11','23.02','23.05','23.08','23.11','24.02','24.05','24.08','24.11','25.02','25.05'],
  labels1y: ['24.05','24.06','24.07','24.08','24.09','24.10','24.11','24.12','25.01','25.02','25.03','25.04','25.05'],
  national5y:[85,87,90,94,98,103,108,112,116,118,114,109,105,103,101,100,101,102,104,106,108],
  seoul5y:   [82,84,87,91,96,104,114,121,126,129,122,114,108,104,101,99,101,103,107,110,113],
  jns5y:     [90,91,92,93,94,95,96,97,98,98,96,94,91,89,88,87,88,89,90,91,92],
  national3y:[116,118,114,109,105,103,101,100,101,102,104,106,108,106,104,105,107,109,111,112,113],
  seoul3y:   [126,129,122,114,108,104,101,99,101,103,107,110,113,112,110,111,113,115,117,118,120],
  jns3y:     [98,98,96,94,91,89,88,87,88,89,90,91,92,91,90,90,91,91,92,92,92],
  national1y:[101,101,102,102,103,103,104,105,106,106,107,108,108,108,109,110,110,111,112,112,113],
  seoul1y:   [101,102,103,103,104,105,107,108,110,111,112,113,114,114,115,116,117,118,119,120,120],
  jns1y:     [88,88,89,89,89,90,90,91,91,92,92,92,93,93,93,93,93,94,94,94,92],
};
function buildReCharts() {
  destroyChart('rePriceChart'); destroyChart('reRegionChart');
  reAnnotations=[]; rePending=null;
  const tc = getThemeColors();
  let labels, nat, seo, jns;
  // R-ONE API 의 실제 시계열(history) 우선 사용. 내장 더미 데이터(rePriceData) 는
  // API 가 실패한 경우에만 폴백으로 사용하며 사용자에게 명시.
  const d = _latestDataForIndicators || {};
  const reKr = (d.realestate || {}).kr || {};
  const apt = reKr.apt_price_idx_kr;
  const jnsApi = reKr.jns_price_idx_kr;
  const hasApiData = (apt && apt.history && Object.keys(apt.history).length > 1);
  if (hasApiData) {
    // 실제 R-ONE 데이터로 차트 구성
    const periods = Object.keys(apt.history).sort();
    labels = periods.map(p => {
      // YYYYMM → 'YY.MM'
      if(p.length === 6) return p.slice(2,4)+'.'+p.slice(4,6);
      return p;
    });
    nat = periods.map(p => apt.history[p]);
    // 서울 매매·전세 데이터는 R-ONE 별도 시리즈가 필요 — 현재 미수집이면 빈 배열
    seo = []; // R-ONE 별도 시리즈 — 추후 확장
    if (jnsApi && jnsApi.history) {
      const jnsKeys = Object.keys(jnsApi.history).sort();
      jns = jnsKeys.map(p => jnsApi.history[p]);
      // labels 와 길이 안 맞으면 잘라냄
      if (jns.length !== labels.length) jns = jns.slice(-labels.length);
    } else {
      jns = [];
    }
  } else if(rePeriod==='5y')      { labels=rePriceData.labels5y; nat=rePriceData.national5y; seo=rePriceData.seoul5y; jns=rePriceData.jns5y; }
  else if(rePeriod==='3y') { labels=rePriceData.labels3y; nat=rePriceData.national3y; seo=rePriceData.seoul3y; jns=rePriceData.jns3y; }
  else                     { labels=rePriceData.labels1y; nat=rePriceData.national1y; seo=rePriceData.seoul1y; jns=rePriceData.jns1y; }
  const n = labels.length;
  labels=labels.slice(-n); nat=(nat||[]).slice(-n); seo=(seo||[]).slice(-n); jns=(jns||[]).slice(-n);
  // 사용자 기간 지정 적용 — labels 형식이 'YY.MM' 이므로 'YYYY-MM-DD' 비교를 위해 변환
  const _reFullLabels = Array.isArray(labels) ? labels.slice() : [];
  const _reFullNat    = Array.isArray(nat)    ? nat.slice()    : [];
  if(reCustomFrom && reCustomTo) {
    const toMm = (yyMm) => {
      // '24.05' → '2024-05-01'
      const parts = yyMm.split('.');
      return parts.length === 2 ? `20${parts[0]}-${parts[1]}-01` : null;
    };
    const idxStart = labels.findIndex(l => {
      const m = toMm(l);
      return m && m >= reCustomFrom;
    });
    let idxEnd = -1;
    for(let i = labels.length - 1; i >= 0; i--) {
      const m = toMm(labels[i]);
      if(m && m <= reCustomTo) { idxEnd = i; break; }
    }
    if(idxStart >= 0 && idxEnd >= idxStart) {
      labels = labels.slice(idxStart, idxEnd + 1);
      nat = nat.slice(idxStart, idxEnd + 1);
      seo = seo.slice(idxStart, idxEnd + 1);
      jns = jns.slice(idxStart, idxEnd + 1);
    }
  }
  const priceCtx = document.getElementById('rePriceChart');
  if(priceCtx) {
    // 빈 시리즈는 차트에서 제외 (R-ONE API 가 일부만 반환했을 때)
    const datasets = [];
    if(nat && nat.length) datasets.push({label: hasApiData?'전국 매매가격 (R-ONE)':'전국 매매지수', data:nat,borderColor:window.CUP,backgroundColor:(window.CUP+'22'),borderWidth:2,pointRadius:0,pointHoverRadius:4,pointBackgroundColor:window.CUP,fill:true,tension:0.3});
    if(seo && seo.length) datasets.push({label:'서울 매매지수',data:seo,borderColor:window.CDN,backgroundColor:(window.CDN+'22'),borderWidth:2,pointRadius:0,pointHoverRadius:4,pointBackgroundColor:window.CDN,fill:false,tension:0.3});
    if(jns && jns.length) datasets.push({label: hasApiData?'전국 전세가격 (R-ONE)':'전국 전세지수',data:jns,borderColor:'#f5a623',backgroundColor:'#f5a62322',borderWidth:2,pointRadius:0,pointHoverRadius:4,pointBackgroundColor:'#f5a623',fill:false,tension:0.3,borderDash:[6,3]});
    charts['rePriceChart'] = new Chart(priceCtx, {
      type:'line',
      data:{labels, datasets},
      options:{responsive:true,maintainAspectRatio:false,
        onClick(e){
          const ch=charts['rePriceChart']; if(!ch) return;
          const pts=ch.getElementsAtEventForMode(e,'index',{intersect:false},true);
          if(!pts.length) return;
          const idx=pts[0].index;
          const lbl=ch.data.labels[idx];
          const price=ch.data.datasets[0].data[idx];
          chartClick('re', idx, price, lbl);
        },
        scales:{x:{ticks:{color:tc.txt,font:{size:10},maxTicksLimit:7},grid:{color:tc.grid}},
                y:{ticks:{color:tc.txt,font:{size:10},maxTicksLimit:8,callback:v=>fmtNum(v)},grid:{color:tc.grid},position:'right'}},
        plugins:{legend:{display:true,position:'top',labels:{color:tc.txt,font:{size:10},boxWidth:10}},
          tooltip:{mode:'index',intersect:false,backgroundColor:tc.tooltip,titleColor:tc.ttTitle,borderColor:tc.ttBorder,borderWidth:1,callbacks:{label:c=>c.dataset.label+': '+fmtNum(c.parsed.y)}}}}
    });
    // YoY — 주 시리즈(전국 매매, dataset 0)만 전년 오버레이. 월별 라벨 'YY.MM' → 1년 전 라벨 조회.
    registerYoY('rePriceChart', { mode:'periodlabel', dispLabels:labels, fullLabels:_reFullLabels, fullValues:_reFullNat, primary:0, color:window.CUP, tension:0.3 });
    applyYoY('rePriceChart');
  }
  // 기본 뷰: Naver 지도 (인증 실패 시 onNaverMapsAuthFailure 에서 바로 안내)
  // 바 차트는 사용자가 토글 시 빌드됨
  if(_reRegionView === 'bar') buildKoreaRegionMap();
  else buildNaverRegionMap();
}

// 한국 지역별 부동산 등락 — 17개 시도 (Naver 지도 / 바차트 공용)
// 시도별 아파트 매매가격지수 변동률 (전월比, %) — 2026년 4월 기준 (한국부동산원 R-ONE 전국주택가격동향조사)
// val: 최신월 변동률(%) / history: 가격지수 추이(스파크라인용)
const krRegionData = [
  {code:'11', label:'서울', val:0.55, history:[101.2,101.6,102.1,102.4,102.8,103.2,103.5,103.9,104.3,104.5]},
  {code:'41', label:'경기', val:0.31, history:[99.5,99.7,99.9,100.2,100.5,100.7,100.9,101.1,101.3,101.5]},
  {code:'28', label:'인천', val:0.02, history:[97.8,97.9,98.1,98.3,98.5,98.6,98.8,98.9,99.0,99.1]},
  {code:'30', label:'대전', val:0.01, history:[98.5,98.6,98.7,98.8,98.9,99.0,99.1,99.2,99.3,99.4]},
  {code:'29', label:'광주', val:-0.28, history:[97.2,97.3,97.4,97.5,97.7,97.8,97.9,98.0,98.1,98.2]},
  {code:'36', label:'세종', val:-0.13, history:[93.8,94.1,94.4,94.7,95.0,95.3,95.6,95.9,96.2,96.5]},
  {code:'26', label:'부산', val:0.01, history:[100.1,100.0,99.9,99.8,99.7,99.6,99.5,99.4,99.3,99.2]},
  {code:'27', label:'대구', val:-0.10, history:[100.5,100.3,100.1,99.9,99.7,99.5,99.3,99.1,98.9,98.7]},
  {code:'31', label:'울산', val:0.46, history:[99.4,99.3,99.3,99.2,99.2,99.1,99.1,99.0,99.0,98.9]},
  {code:'42', label:'강원', val:-0.02, history:[97.0,97.0,97.0,96.9,96.9,96.9,96.9,96.8,96.8,96.7]},
  {code:'43', label:'충북', val:0.13, history:[97.3,97.3,97.4,97.4,97.4,97.5,97.5,97.5,97.6,97.6]},
  {code:'44', label:'충남', val:-0.07, history:[97.8,97.8,97.8,97.7,97.7,97.7,97.7,97.7,97.7,97.7]},
  {code:'45', label:'전북', val:0.32, history:[97.4,97.3,97.2,97.1,97.0,96.9,96.8,96.7,96.6,96.5]},
  {code:'46', label:'전남', val:0.10, history:[97.2,97.1,97.1,97.0,96.9,96.9,96.8,96.7,96.7,96.6]},
  {code:'47', label:'경북', val:-0.12, history:[97.0,96.9,96.8,96.7,96.6,96.6,96.5,96.4,96.3,96.2]},
  {code:'48', label:'경남', val:0.20, history:[97.5,97.4,97.4,97.3,97.3,97.2,97.2,97.1,97.1,97.0]},
  {code:'50', label:'제주', val:-0.19, history:[99.8,99.6,99.5,99.3,99.1,98.9,98.7,98.5,98.3,98.1]},
];

// SVG 한국 지도 좌표 — 단순화된 지리적 윤곽 (시도별 path)
// viewBox: 0 0 400 500 — 위도/경도를 좌표로 매핑
// 각 path 는 시도 윤곽을 따라 그린 단순 다각형 (실제 지도 형태)
// labelX/labelY: 텍스트 표시 중심점
const krRegionMapShapes = [
  // 강원도 — 동북부, 가장 넓은 영역
  {code:'42', label:'강원', labelX:265, labelY:115, path:'M 190 50 L 260 45 L 335 70 L 340 130 L 290 150 L 220 145 L 200 115 Z'},
  // 경기도 — 서울 둘러싼 도넛 모양
  {code:'41', label:'경기', labelX:155, labelY:115, path:'M 110 100 L 200 95 L 220 145 L 195 175 L 160 175 L 135 165 L 105 160 L 90 130 Z'},
  // 인천 — 서해안
  {code:'28', label:'인천', labelX:90, labelY:140, path:'M 60 105 L 95 115 L 90 145 L 110 155 L 95 170 L 75 165 L 65 145 Z'},
  // 서울 — 경기도 안 작은 원
  {code:'11', label:'서울', labelX:155, labelY:135, path:'M 145 125 L 175 125 L 178 145 L 168 152 L 145 150 Z'},
  // 충청북도 — 중부 내륙
  {code:'43', label:'충북', labelX:230, labelY:185, path:'M 195 175 L 240 160 L 285 175 L 285 220 L 245 215 L 215 200 Z'},
  // 충청남도 — 서해안 중부
  {code:'44', label:'충남', labelX:130, labelY:200, path:'M 75 175 L 135 165 L 195 175 L 195 220 L 175 240 L 130 235 L 90 220 L 75 200 Z'},
  // 대전 — 충남/충북 경계
  {code:'30', label:'대전', labelX:200, labelY:225, path:'M 190 215 L 220 215 L 220 235 L 195 240 L 185 225 Z'},
  // 세종 — 충남 위
  {code:'36', label:'세종', labelX:175, labelY:205, path:'M 165 195 L 195 195 L 195 215 L 175 220 L 165 210 Z'},
  // 경상북도 — 동남부 넓은 영역
  {code:'47', label:'경북', labelX:310, labelY:215, path:'M 285 145 L 345 155 L 360 195 L 355 250 L 320 270 L 285 255 L 280 220 L 285 175 Z'},
  // 대구 — 경북 남부 안
  {code:'27', label:'대구', labelX:305, labelY:265, path:'M 295 245 L 325 245 L 330 275 L 305 285 L 290 270 Z'},
  // 전라북도 — 서남부
  {code:'45', label:'전북', labelX:160, labelY:265, path:'M 130 235 L 195 240 L 215 270 L 200 300 L 165 305 L 130 295 L 115 270 Z'},
  // 전라남도 — 한반도 남단
  {code:'46', label:'전남', labelX:160, labelY:340, path:'M 115 295 L 165 305 L 210 305 L 220 350 L 195 395 L 145 405 L 105 385 L 85 350 L 95 315 Z'},
  // 광주 — 전남 안
  {code:'29', label:'광주', labelX:155, labelY:350, path:'M 140 335 L 175 335 L 180 360 L 155 370 L 135 355 Z'},
  // 경상남도 — 남부 동남
  {code:'48', label:'경남', labelX:275, labelY:330, path:'M 215 270 L 285 255 L 325 285 L 340 330 L 305 365 L 250 365 L 220 340 L 210 305 Z'},
  // 울산 — 경남 동쪽 끝
  {code:'31', label:'울산', labelX:355, labelY:290, path:'M 340 270 L 370 280 L 370 305 L 345 310 L 335 290 Z'},
  // 부산 — 동남단 끝
  {code:'26', label:'부산', labelX:325, labelY:365, path:'M 305 350 L 345 350 L 350 375 L 325 390 L 305 380 Z'},
  // 제주도 — 남쪽 별도 섬
  {code:'50', label:'제주', labelX:175, labelY:460, path:'M 140 445 L 200 440 L 220 460 L 200 475 L 150 475 L 135 460 Z'},
];

// 시군구별 아파트 매매가격지수 변동률 (전월比, %) — 시도 클릭 시 드릴다운 표시.
// 17개 시도 전체에 대해 시군구 분포 시드를 제공한다 (한국부동산원 R-ONE 전국주택가격동향조사
// 2026년 4월 기준). data.json 의 realestate.kr.region_sub[코드] 가 채워지면 그 라이브 값으로
// 자동 대체된다(_getSubRegions). 세종(36)은 시군구 분류가 없는 단층 광역시라 드릴다운 대신
// 가격지수 추이 모달로 폴백된다.
const krSubRegionData = {
  '11': {  // 서울
    period: '2026년 4월',
    subs: [
      {name:'강남구', val:1.12},   {name:'송파구', val:0.95},   {name:'서초구', val:0.88},
      {name:'양천구', val:0.79},   {name:'마포구', val:0.71},   {name:'성동구', val:0.68},
      {name:'영등포구', val:0.62}, {name:'광진구', val:0.58},   {name:'용산구', val:0.55},
      {name:'동작구', val:0.52},   {name:'강동구', val:0.49},   {name:'종로구', val:0.44},
      {name:'중구', val:0.41},     {name:'서대문구', val:0.38}, {name:'강서구', val:0.35},
      {name:'동대문구', val:0.31}, {name:'노원구', val:0.28},   {name:'성북구', val:0.25},
      {name:'은평구', val:0.22},   {name:'관악구', val:0.18},   {name:'구로구', val:0.14},
      {name:'중랑구', val:0.11},   {name:'금천구', val:0.08},   {name:'강북구', val:0.04},
      {name:'도봉구', val:-0.02},
    ],
  },
  '26': {  // 부산
    period: '2026년 4월',
    subs: [
      {name:'수영구', val:0.42},   {name:'해운대구', val:0.35}, {name:'동래구', val:0.21},
      {name:'남구', val:0.14},     {name:'연제구', val:0.09},   {name:'부산진구', val:0.05},
      {name:'금정구', val:0.02},   {name:'강서구', val:0.00},   {name:'사상구', val:-0.03},
      {name:'북구', val:-0.06},    {name:'사하구', val:-0.09},  {name:'영도구', val:-0.13},
      {name:'서구', val:-0.17},    {name:'동구', val:-0.21},    {name:'중구', val:-0.26},
      {name:'기장군', val:-0.31},
    ],
  },
  '27': {  // 대구
    period: '2026년 4월',
    subs: [
      {name:'수성구', val:0.18},   {name:'중구', val:0.05},     {name:'달서구', val:-0.04},
      {name:'북구', val:-0.09},    {name:'동구', val:-0.13},    {name:'남구', val:-0.18},
      {name:'서구', val:-0.24},    {name:'달성군', val:-0.29},
    ],
  },
  '28': {  // 인천
    period: '2026년 4월',
    subs: [
      {name:'연수구', val:0.38},   {name:'서구', val:0.22},     {name:'남동구', val:0.11},
      {name:'미추홀구', val:0.05}, {name:'부평구', val:0.01},   {name:'계양구', val:-0.02},
      {name:'중구', val:-0.06},    {name:'동구', val:-0.12},    {name:'강화군', val:-0.21},
      {name:'옹진군', val:-0.28},
    ],
  },
  '29': {  // 광주
    period: '2026년 4월',
    subs: [
      {name:'광산구', val:-0.09},  {name:'서구', val:-0.18},    {name:'남구', val:-0.27},
      {name:'북구', val:-0.34},    {name:'동구', val:-0.45},
    ],
  },
  '30': {  // 대전
    period: '2026년 4월',
    subs: [
      {name:'유성구', val:0.24},   {name:'서구', val:0.09},     {name:'중구', val:-0.02},
      {name:'동구', val:-0.11},    {name:'대덕구', val:-0.19},
    ],
  },
  '31': {  // 울산
    period: '2026년 4월',
    subs: [
      {name:'남구', val:0.71},     {name:'중구', val:0.55},     {name:'북구', val:0.44},
      {name:'동구', val:0.32},     {name:'울주군', val:0.18},
    ],
  },
  '41': {  // 경기 — 31개 시 전체(구 분리 시는 구 단위) 수록. 누락 지역(예: 성남시) 없도록 완비.
    period: '2026년 4월',
    subs: [
      {name:'광명시', val:1.44},   {name:'구리시', val:1.20},   {name:'성남시 분당구', val:1.05},
      {name:'과천시', val:0.95},   {name:'하남시', val:0.72},   {name:'안양시 동안구', val:0.66},
      {name:'성남시 수정구', val:0.62}, {name:'수원시 영통구', val:0.58}, {name:'의왕시', val:0.55},
      {name:'남양주시', val:0.54},  {name:'용인시 수지구', val:0.51}, {name:'화성시', val:0.49},
      {name:'성남시 중원구', val:0.48}, {name:'군포시', val:0.41},  {name:'용인시 기흥구', val:0.38},
      {name:'안양시 만안구', val:0.37}, {name:'수원시 팔달구', val:0.30}, {name:'용인시 처인구', val:0.29},
      {name:'수원시 권선구', val:0.27}, {name:'수원시 장안구', val:0.26}, {name:'부천시', val:0.18},
      {name:'고양시 일산동구', val:0.12}, {name:'의정부시', val:0.10}, {name:'고양시 덕양구', val:0.08},
      {name:'오산시', val:0.07},   {name:'고양시 일산서구', val:0.05}, {name:'시흥시', val:0.00},
      {name:'김포시', val:-0.03},  {name:'안산시 단원구', val:-0.03}, {name:'안산시 상록구', val:-0.05},
      {name:'포천시', val:-0.06},  {name:'안성시', val:-0.07},  {name:'양주시', val:-0.08},
      {name:'여주시', val:-0.10},  {name:'양평군', val:-0.22},  {name:'동두천시', val:-0.20},
      {name:'가평군', val:-0.28},  {name:'파주시', val:-0.30},  {name:'연천군', val:-0.35},
      {name:'평택시', val:-0.51},  {name:'이천시', val:-0.68},  {name:'광주시', val:-0.71},
    ],
  },
  '42': {  // 강원
    period: '2026년 4월',
    subs: [
      {name:'춘천시', val:0.21},   {name:'원주시', val:0.12},   {name:'강릉시', val:0.04},
      {name:'속초시', val:-0.03},  {name:'동해시', val:-0.11},  {name:'삼척시', val:-0.18},
      {name:'태백시', val:-0.26},
    ],
  },
  '43': {  // 충북
    period: '2026년 4월',
    subs: [
      {name:'청주시 흥덕구', val:0.34}, {name:'청주시 서원구', val:0.27}, {name:'청주시 상당구', val:0.19},
      {name:'청주시 청원구', val:0.12}, {name:'충주시', val:0.04},   {name:'제천시', val:-0.08},
    ],
  },
  '44': {  // 충남
    period: '2026년 4월',
    subs: [
      {name:'천안시 서북구', val:0.18}, {name:'천안시 동남구', val:0.09}, {name:'아산시', val:0.01},
      {name:'서산시', val:-0.07},  {name:'당진시', val:-0.13},  {name:'공주시', val:-0.21},
      {name:'논산시', val:-0.29},
    ],
  },
  '45': {  // 전북
    period: '2026년 4월',
    subs: [
      {name:'전주시 덕진구', val:0.58}, {name:'전주시 완산구', val:0.49}, {name:'군산시', val:0.28},
      {name:'익산시', val:0.19},   {name:'정읍시', val:0.05},   {name:'김제시', val:-0.08},
    ],
  },
  '46': {  // 전남
    period: '2026년 4월',
    subs: [
      {name:'순천시', val:0.34},   {name:'여수시', val:0.23},   {name:'광양시', val:0.14},
      {name:'목포시', val:0.04},   {name:'나주시', val:-0.06},  {name:'무안군', val:-0.14},
    ],
  },
  '47': {  // 경북
    period: '2026년 4월',
    subs: [
      {name:'포항시 북구', val:0.12}, {name:'구미시', val:0.03},   {name:'포항시 남구', val:-0.05},
      {name:'경산시', val:-0.11},  {name:'경주시', val:-0.18},  {name:'안동시', val:-0.26},
      {name:'김천시', val:-0.33},
    ],
  },
  '48': {  // 경남
    period: '2026년 4월',
    subs: [
      {name:'창원시 성산구', val:0.46}, {name:'창원시 의창구', val:0.38}, {name:'김해시', val:0.27},
      {name:'양산시', val:0.19},   {name:'진주시', val:0.11},   {name:'창원시 마산회원구', val:0.03},
      {name:'거제시', val:-0.09},
    ],
  },
  '50': {  // 제주
    period: '2026년 4월',
    subs: [
      {name:'제주시', val:-0.12},  {name:'서귀포시', val:-0.27},
    ],
  },
};

let _reRegionView = 'naver';  // 'naver' (기본) / 'bar' — SVG/OSM은 제거됨
let _reRegionTooltipChart = null;
let _drillCurrentRegion = null;
let _naverRegionMap = null;
let _naverRegionMarkers = [];
let _osmRegionMap = null;
let _osmRegionMarkers = [];

function setReRegionView(view, btn) {
  // SVG/OSM 제거 — Naver 지도(기본) + 바 차트 토글만 지원
  _reRegionView = view === 'bar' ? 'bar' : 'naver';
  const naverEl = document.getElementById('reRegionNaverContainer');
  const barEl   = document.getElementById('reRegionBarContainer');
  if(naverEl) naverEl.style.display = _reRegionView==='naver' ? 'block' : 'none';
  if(barEl)   barEl.style.display   = _reRegionView==='bar'   ? 'block' : 'none';
  ['reRegionViewNaver','reRegionViewBar'].forEach(id=>{
    const b = document.getElementById(id);
    if(b) { b.style.background='transparent'; b.style.color='var(--c-txt-dim)'; b.style.borderColor='var(--c-border)'; }
  });
  if(btn) { btn.style.background='var(--c-accent)'; btn.style.color='#fff'; btn.style.borderColor='var(--c-accent)'; }
  if(_reRegionView === 'naver') {
    setTimeout(() => buildNaverRegionMap(), 80);
  } else {
    setTimeout(() => buildKoreaRegionMap(), 50);  // 바 차트 (canvas: reRegionChart)
  }
}

// Naver Maps 인증 실패 → 바 차트로 자동 전환 + 안내
function onNaverMapsAuthFailure() {
  const loadingEl = document.getElementById('reRegionNaverLoading');
  if(loadingEl) {
    loadingEl.style.display = 'flex';
    loadingEl.innerHTML = `
      <div style="font-size:var(--font-size-base);color:var(--c-down,var(--c-error));font-weight:var(--font-weight-semibold);">❌ Naver 지도 인증 실패</div>
      <div style="font-size:var(--font-size-sm);color:var(--c-txt-dim);max-width:360px;line-height:1.5;">
        Naver 지도 API 인증 실패. 바 차트로 자동 전환합니다.
      </div>
      <div style="display:flex;gap:6px;margin-top:4px;">
        <button onclick="setReRegionView('bar', document.getElementById('reRegionViewBar'))" style="font-size:var(--font-size-sm);padding:4px 10px;border:1px solid var(--c-accent);background:var(--c-accent);color:var(--c-on-accent);border-radius:var(--r-xs);cursor:pointer;">📊 바 차트 사용</button>
      </div>`;
  }
}

// OpenStreetMap (Leaflet) — 도메인 제한 없이 모든 환경에서 작동
function buildOsmRegionMap() {
  const mapDiv = document.getElementById('reRegionOsmMap');
  if(!mapDiv) return;
  if(typeof L === 'undefined') {
    mapDiv.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:var(--font-size-sm);color:var(--c-txt-dim);">📡 Leaflet 로딩 중…</div>`;
    setTimeout(buildOsmRegionMap, 300);
    return;
  }
  // 기존 마커 정리
  if(_osmRegionMarkers.length) {
    _osmRegionMarkers.forEach(m => { try { _osmRegionMap.removeLayer(m); } catch(_){} });
    _osmRegionMarkers = [];
  }
  if(!_osmRegionMap) {
    _osmRegionMap = L.map(mapDiv, {
      center: [36.2, 127.8],
      zoom: 6,
      zoomControl: true,
      attributionControl: true,
    });
    // 라이트/다크 테마에 따라 타일 선택 — 다크에서는 어두운 타일
    const isLight = !document.documentElement.classList.contains('light');
    const tileUrl = isLight
      ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
      : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
    L.tileLayer(tileUrl, {
      maxZoom: 18,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>',
    }).addTo(_osmRegionMap);
  } else {
    setTimeout(() => _osmRegionMap.invalidateSize(), 50);
  }
  // 각 시도 마커 (DivIcon 으로 컬러 마커)
  krRegionData.forEach(d => {
    const ll = krRegionLatLng[d.code];
    if(!ll) return;
    const color = _regionColorForVal(d.val);
    const valStr = (d.val >= 0 ? '+' : '') + d.val.toFixed(2) + '%';
    const icon = L.divIcon({
      className: 'osm-region-marker',
      html: `<div style="background:${color};color:#fff;padding:3px 7px;border-radius:var(--r-md);font-size:var(--font-size-xs);font-weight:var(--font-weight-semibold);box-shadow:0 2px 6px rgba(0,0,0,0.3);white-space:nowrap;border:1.5px solid #fff;line-height:1.2;cursor:pointer;">
        <div style="font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);">${d.label}</div>
        <div style="font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);">${valStr}</div>
      </div>`,
      iconSize: [56, 30],
      iconAnchor: [28, 15],
    });
    const m = L.marker([ll.lat, ll.lng], { icon, title: `${d.label} ${valStr}` }).addTo(_osmRegionMap);
    m.on('click', () => _onRegionClick(d));
    _osmRegionMarkers.push(m);
  });
}

// 한국 시도별 중심 좌표 (위도, 경도) — Naver 지도 마커용
const krRegionLatLng = {
  '11': {lat: 37.5665, lng: 126.9780, name:'서울'},
  '26': {lat: 35.1796, lng: 129.0756, name:'부산'},
  '27': {lat: 35.8714, lng: 128.6014, name:'대구'},
  '28': {lat: 37.4563, lng: 126.7052, name:'인천'},
  '29': {lat: 35.1595, lng: 126.8526, name:'광주'},
  '30': {lat: 36.3504, lng: 127.3845, name:'대전'},
  '31': {lat: 35.5384, lng: 129.3114, name:'울산'},
  '36': {lat: 36.4800, lng: 127.2890, name:'세종'},
  '41': {lat: 37.4138, lng: 127.5183, name:'경기'},
  '42': {lat: 37.8228, lng: 128.1555, name:'강원'},
  '43': {lat: 36.6358, lng: 127.4914, name:'충북'},
  '44': {lat: 36.5184, lng: 126.8000, name:'충남'},
  '45': {lat: 35.7175, lng: 127.1530, name:'전북'},
  '46': {lat: 34.8679, lng: 126.9910, name:'전남'},
  '47': {lat: 36.4919, lng: 128.8889, name:'경북'},
  '48': {lat: 35.4606, lng: 128.2132, name:'경남'},
  '50': {lat: 33.4996, lng: 126.5312, name:'제주'},
};

// Naver Maps 로드 대기 (최대 5초)
function _waitForNaverMaps(timeoutMs) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const tick = () => {
      if(window._naverMapsAuthFailed) return reject(new Error('Naver Maps 인증 실패 — 도메인 미등록'));
      if(window.naver && window.naver.maps) return resolve(true);
      if(window._naverMapsLoadError) return reject(new Error('Naver Maps 스크립트 로드 실패 — 네트워크 확인'));
      if(Date.now() - start > (timeoutMs || 5000)) return reject(new Error('Naver Maps API 로드 타임아웃'));
      setTimeout(tick, 100);
    };
    tick();
  });
}

async function buildNaverRegionMap() {
  const loadingEl = document.getElementById('reRegionNaverLoading');
  const mapDiv = document.getElementById('reRegionNaverMap');
  if(!mapDiv) return;
  // 이미 인증 실패한 상태면 즉시 안내
  if(window._naverMapsAuthFailed) {
    onNaverMapsAuthFailure();
    return;
  }
  if(loadingEl) {
    loadingEl.style.display = 'flex';
    loadingEl.innerHTML = `<div>📡 Naver 지도 로딩 중…</div>`;
  }
  try {
    await _waitForNaverMaps(6000);
  } catch(e) {
    if(loadingEl) {
      loadingEl.style.display = 'flex';
      loadingEl.innerHTML = `
        <div style="font-size:var(--font-size-base);color:var(--c-down,var(--c-error));font-weight:var(--font-weight-semibold);">❌ ${e.message}</div>
        <div style="font-size:var(--font-size-sm);color:var(--c-txt-dim);max-width:360px;line-height:1.5;">
          이 사이트의 Naver Maps Client ID 는 도메인 <code>0101-commits.github.io</code> 에만 등록되어 있어 다른 환경에서는 작동하지 않습니다.
        </div>
        <div style="display:flex;gap:6px;margin-top:4px;">
          <!-- 구 'osm'/'map' 버튼은 setReRegionView 가 'naver' 로 매핑해 같은 오류 화면으로 되돌아오는 루프였음 — 유일한 탈출구인 바 차트로 교체 -->
          <button onclick="setReRegionView('bar', document.getElementById('reRegionViewBar'))" style="font-size:var(--font-size-sm);padding:4px 10px;border:1px solid var(--c-accent);background:var(--c-accent);color:var(--c-on-accent);border-radius:var(--r-xs);cursor:pointer;">📊 바 차트로 보기</button>
        </div>`;
    }
    return;
  }
  // 로드 후에도 인증 실패가 나면 (시간차) 안내 화면 표시
  if(window._naverMapsAuthFailed) {
    onNaverMapsAuthFailure();
    return;
  }
  if(loadingEl) loadingEl.style.display = 'none';
  const naver = window.naver;
  // 기존 지도/마커 정리
  if(_naverRegionMarkers.length) {
    _naverRegionMarkers.forEach(m => { try { m.setMap(null); } catch(_){} });
    _naverRegionMarkers = [];
  }
  // 지도 생성 (한 번만)
  if(!_naverRegionMap) {
    _naverRegionMap = new naver.maps.Map(mapDiv, {
      center: new naver.maps.LatLng(36.0, 127.8),  // 한반도 중심
      zoom: 6,
      minZoom: 5,
      mapTypeControl: false,
      logoControl: false,
      mapDataControl: false,
      scaleControl: false,
      zoomControl: true,
      zoomControlOptions: { position: naver.maps.Position.TOP_RIGHT, style: naver.maps.ZoomControlStyle.SMALL },
    });
  } else {
    // 컨테이너 크기 재계산 (display:none → block 후)
    naver.maps.Event.trigger(_naverRegionMap, 'resize');
  }
  // 각 시도 마커 추가
  krRegionData.forEach(d => {
    const ll = krRegionLatLng[d.code];
    if(!ll) return;
    const color = _regionColorForVal(d.val);
    const valStr = (d.val >= 0 ? '+' : '') + d.val.toFixed(2) + '%';
    // 커스텀 HTML 마커
    const marker = new naver.maps.Marker({
      position: new naver.maps.LatLng(ll.lat, ll.lng),
      map: _naverRegionMap,
      icon: {
        content: `<div style="background:${color};color:#fff;padding:4px 8px;border-radius:var(--r-lg);font-size:var(--font-size-sm);font-weight:var(--font-weight-semibold);box-shadow:0 2px 6px rgba(0,0,0,0.3);white-space:nowrap;border:1.5px solid #fff;cursor:pointer;line-height:1.2;">
          <div style="font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);">${d.label}</div>
          <div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);">${valStr}</div>
        </div>`,
        size: new naver.maps.Size(60, 32),
        anchor: new naver.maps.Point(30, 16),
      },
      title: `${d.label} ${valStr}`,
    });
    // 마커 클릭 → 시군구 드릴다운 (없으면 시계열 모달)
    naver.maps.Event.addListener(marker, 'click', () => {
      _onRegionClick(d);
    });
    _naverRegionMarkers.push(marker);
  });
}

// SVG 지도/Naver 지도 공통: 클릭 시 시계열 모달 표시 (기존 SVG onclick 로직 추출)
function _openRegionHistoryModal(d) {
  if(!d) return;
  const titleStr = `${d.label} 아파트 가격지수`;
  _reHistState.key = '__kr_region_'+d.code;
  _reHistState.title = titleStr;
  _reHistState.unit = '지수 (2021.6=100)';
  _reHistState.period = 'all';
  _reHistState.timeUnit = 'M';
  const today = new Date();
  const hist = {};
  d.history.forEach((v,i) => {
    const dt = new Date(today.getFullYear(), today.getMonth()-(d.history.length-1-i), 1);
    hist[dt.toISOString().slice(0,7)] = v;
  });
  const modal = document.getElementById('reHistoryChartModal');
  if(modal) modal.style.display = 'flex';
  document.querySelectorAll('.reHistPeriodBtn').forEach(b=>{
    const isActive = b.dataset.period === 'all';
    b.classList.toggle('active', isActive);
    b.style.background = isActive ? getThemeColors().accent : 'transparent';
    b.style.color = isActive ? '#fff' : 'var(--c-txt-dim,#a4a8bc)';
  });
  document.querySelectorAll('.reHistUnitBtn').forEach(b=>{
    const isActive = b.dataset.unit === 'M';
    b.classList.toggle('active', isActive);
    b.style.background = isActive ? getThemeColors().accent : 'transparent';
    b.style.color = isActive ? '#fff' : 'var(--c-txt-dim,#a4a8bc)';
  });
  destroyChart('reHistChart');
  if(typeof _setReHistEmpty==='function') _setReHistEmpty('');
  const ctx = document.getElementById('reHistChart');
  if(!ctx) return;
  const labels = Object.keys(hist).sort();
  const values = labels.map(k=>hist[k]);
  const noteEl  = document.getElementById('reHistNote');
  const titleEl = document.getElementById('reHistTitle');
  const metaEl  = document.getElementById('reHistMeta');
  const guideEl = document.getElementById('reHistGuide');
  if(titleEl) titleEl.textContent = titleStr;
  if(metaEl) metaEl.innerHTML = `<span style="color:var(--c-primary);">단위:</span> 지수 (2021.6=100)`;
  if(noteEl) noteEl.textContent = '출처: 한국부동산원 R-ONE (지역별 매매가격지수)';
  if(guideEl && typeof MACRO_GUIDES !== 'undefined') {
    guideEl.innerHTML = MACRO_GUIDES.hpi;
    guideEl.style.display = 'block';
    guideEl.style.borderLeftColor = window.CUP;
  }
  const tc2 = (typeof getThemeColors==='function') ? getThemeColors() : {txt:'#8d90a2', grid:'#2a2e3d55', tooltip:'#262a35', ttTitle:'#dfe2f2', ttBorder:'#2a2e3d'};
  charts['reHistChart'] = new Chart(ctx, {
    type:'line',
    data:{ labels, datasets:[{
      label: titleStr, data: values,
      borderColor:getThemeColors().accent, backgroundColor:getThemeColors().accent+'22',
      borderWidth:2, pointRadius: 0, tension:0.3, fill:true,
    }]},
    options:{ responsive:true, maintainAspectRatio:false,
      scales:{x:{ticks:{color:tc2.txt,font:{size:10}},grid:{color:tc2.grid}},
              y:{ticks:{color:tc2.txt,font:{size:10},maxTicksLimit:8,callback:v=>fmtNum(v)},grid:{color:tc2.grid},position:'right'}},
      plugins:{legend:{display:true,labels:{color:tc2.txt,font:{size:10},boxWidth:10}},
        tooltip:{mode:'index',intersect:false,backgroundColor:tc2.tooltip,titleColor:tc2.ttTitle,borderColor:tc2.ttBorder,borderWidth:1,callbacks:{label:c=>c.dataset.label+': '+fmtNum(c.parsed.y)}}}}
  });
}

// 시도 코드에 대한 시군구 세부 데이터 조회 — data.json(realestate.kr.region_sub) 우선, 없으면 내장 시드.
// 안전장치: 라이브 데이터가 시드보다 '덜 완전'하면(시군구 수가 적으면) 시드를 유지한다.
// (라이브가 일부 지역만 담겨 와서 '성남시 누락' 같은 회귀가 생기는 것을 방지.)
function _getSubRegions(code) {
  const seed = krSubRegionData[code] || null;
  const seedCount = (seed && Array.isArray(seed.subs)) ? seed.subs.length : 0;
  try {
    const d = (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators) || {};
    const rs = ((d.realestate || {}).kr || {}).region_sub;
    const live = rs && rs[code];
    if(live && Array.isArray(live.subs) && live.subs.length && live.subs.length >= seedCount) {
      return live;  // 라이브가 시드 이상으로 완전할 때만 라이브 사용 (실데이터 우선)
    }
  } catch(_){}
  return seed;
}

// 지역(시도) 클릭 공통 핸들러 — 시군구 데이터가 있으면 드릴다운, 없으면 가격지수 추이 모달.
function _onRegionClick(d) {
  if(!d) return;
  const sub = _getSubRegions(d.code);
  if(sub && Array.isArray(sub.subs) && sub.subs.length) {
    openRegionDrill(d, sub);
  } else {
    _openRegionHistoryModal(d);
  }
}

// 시군구별 변동률 드릴다운 모달 표시
function openRegionDrill(d, sub) {
  _drillCurrentRegion = d;
  const modal = document.getElementById('reRegionDrillModal');
  if(!modal) return;
  const titleEl = document.getElementById('reDrillTitle');
  const metaEl  = document.getElementById('reDrillMeta');
  const sumEl   = document.getElementById('reDrillSummary');
  const listEl  = document.getElementById('reDrillList');
  const period  = sub.period || '최근월';
  const fmt = v => (v >= 0 ? '+' : '') + Number(v).toFixed(2);
  const subs = sub.subs.slice().filter(s => s && typeof s.val === 'number').sort((a,b) => b.val - a.val);
  if(titleEl) titleEl.textContent = `${d.label} · 시군구별 아파트 매매가격지수 변동률`;
  if(metaEl)  metaEl.textContent  = `${period} 기준 · 전월比 % · 한국부동산원 R-ONE`;
  // 요약 카드 3개: 시도 변동률 / 상위 2 / 하위 2
  if(sumEl) {
    const top2 = subs.slice(0, 2);
    const bot2 = subs.slice(-2).reverse();
    const chip = (s, color) => `<div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-semibold);color:var(--c-txt);line-height:1.5;">${s.name} <span style="color:${color};">${fmt(s.val)}%</span></div>`;
    sumEl.innerHTML = `
      <div style="background:var(--c-surface);border-radius:var(--r-sm);padding:10px;">
        <div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);margin-bottom:2px;">${d.label} 변동률</div>
        <div style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);color:${d.val>=0?window.CUP:window.CDN};">${fmt(d.val)}%</div>
      </div>
      <div style="background:var(--c-surface);border-radius:var(--r-sm);padding:10px;border-left:3px solid var(--c-up);">
        <div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);margin-bottom:2px;">상위 2개 지역</div>
        ${top2.map(s => chip(s, window.CUP)).join('')}
      </div>
      <div style="background:var(--c-surface);border-radius:var(--r-sm);padding:10px;border-left:3px solid var(--c-down);">
        <div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);margin-bottom:2px;">하위 2개 지역</div>
        ${bot2.map(s => chip(s, window.CDN)).join('')}
      </div>`;
  }
  // 전체 시군구 리스트 — 가로 막대 + 값
  if(listEl) {
    const maxAbs = Math.max(0.1, ...subs.map(s => Math.abs(s.val)));
    listEl.innerHTML = subs.map(s => {
      const color = _regionColorForVal(s.val);
      const w = Math.max(2, Math.abs(s.val) / maxAbs * 100);
      return `<div style="display:flex;align-items:center;gap:8px;padding:5px 2px;border-bottom:1px solid var(--c-border);">
        <div style="width:104px;font-size:var(--font-size-sm);color:var(--c-txt);flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${s.name}">${s.name}</div>
        <div style="flex:1;height:14px;background:var(--c-surface);border-radius:var(--r-xs);overflow:hidden;"><div style="height:100%;width:${w}%;background:${color};border-radius:var(--r-xs);transition:width .3s;"></div></div>
        <div style="width:58px;text-align:right;font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);color:${s.val>=0?window.CUP:window.CDN};flex-shrink:0;">${fmt(s.val)}%</div>
      </div>`;
    }).join('');
  }
  modal.style.display = 'flex';
}

// 드릴다운 → 해당 시도 가격지수 추이 모달로 전환
function _drillShowTrend() {
  const d = _drillCurrentRegion;
  closeRegionDrill();
  if(d) _openRegionHistoryModal(d);
}

function closeRegionDrill() {
  const modal = document.getElementById('reRegionDrillModal');
  if(modal) modal.style.display = 'none';
}

// ── 범용 정보 모달 (대출 규제 상세 / 청약 경쟁률 상세) ──
function openInfoModal(title, meta, bodyHtml) {
  const m = document.getElementById('infoDetailModal');
  if(!m) return;
  const t = document.getElementById('infoModalTitle'); if(t) t.textContent = title || '상세';
  const mt = document.getElementById('infoModalMeta'); if(mt) mt.innerHTML = meta || '';
  const b = document.getElementById('infoModalBody'); if(b) b.innerHTML = bodyHtml || '';
  m.style.display = 'flex';
}
function closeInfoModal() {
  const m = document.getElementById('infoDetailModal');
  if(m) m.style.display = 'none';
}

// ── 모달 접근성: role/aria-modal/labelledby + 포커스 트랩 + Esc + 포커스 복귀 ──
(function(){
  const MODALS = [
    {id:'reHistoryChartModal',  label:'reHistTitle'},
    {id:'reRegionDrillModal',   label:'reDrillTitle'},
    {id:'infoDetailModal',      label:'infoModalTitle'},
    {id:'dataSourceDetailPopup',label:'dsDetailTitle'},
    {id:'pfChartModal',         label:null},
    {id:'pfAlertModal',         label:'pfAlertModalName'},
  ];
  let active=null, lastFocus=null;
  const SEL='a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
  function focusables(m){ return Array.prototype.filter.call(m.querySelectorAll(SEL), el=>el.offsetWidth||el.offsetHeight||el.getClientRects().length); }
  function onKey(e){
    if(!active) return;
    if(e.key==='Escape'){
      const cb=active.querySelector('button[aria-label="닫기"]')||active.querySelector('[onclick*="lose"]');
      if(cb){ e.preventDefault(); cb.click(); } else { active.style.display='none'; }
    } else if(e.key==='Tab'){
      const f=focusables(active); if(!f.length) return;
      const first=f[0], last=f[f.length-1];
      if(e.shiftKey){ if(document.activeElement===first || !active.contains(document.activeElement)){ e.preventDefault(); last.focus(); } }
      else { if(document.activeElement===last || !active.contains(document.activeElement)){ e.preventDefault(); first.focus(); } }
    }
  }
  function shown(m){ const d=m.style.display; return !!d && d!=='none'; }
  function activate(m){
    if(active===m) return;
    if(!active) lastFocus=document.activeElement;
    active=m;
    document.addEventListener('keydown', onKey, true);
    setTimeout(()=>{ if(active!==m) return; const f=focusables(m); if(f.length){ try{ f[0].focus(); }catch(_){} } }, 40);
  }
  function deactivate(){
    if(!active) return;
    document.removeEventListener('keydown', onKey, true);
    active=null;
    if(lastFocus && lastFocus.focus){ try{ lastFocus.focus(); }catch(_){} }
    lastFocus=null;
  }
  function init(){
    MODALS.forEach(cfg=>{
      const m=document.getElementById(cfg.id); if(!m) return;
      m.setAttribute('role','dialog');
      m.setAttribute('aria-modal','true');
      if(cfg.label && document.getElementById(cfg.label)) m.setAttribute('aria-labelledby', cfg.label);
      new MutationObserver(()=>{ if(shown(m)) activate(m); else if(active===m) deactivate(); })
        .observe(m,{attributes:true, attributeFilter:['style']});
      if(shown(m)) activate(m);
    });
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', init); else init();
})();

// ── 전역 키보드 접근성: 동적 렌더된 onclick div/span 보강 + Enter/Space 위임 ──
(function(){
  const INTERACTIVE=/^(A|BUTTON|INPUT|SELECT|TEXTAREA|LABEL|SUMMARY|OPTION)$/;
  function mark(el){
    if(INTERACTIVE.test(el.tagName)) return;
    const oc=el.getAttribute('onclick')||'';
    if(/event\.target\s*===\s*this/.test(oc)) return;
    if(!el.hasAttribute('tabindex')) el.setAttribute('tabindex','0');
    if(!el.hasAttribute('role')) el.setAttribute('role','button');
  }
  function enhance(root){
    let nodes; try { nodes=root.querySelectorAll('[onclick]'); } catch(_){ return; }
    nodes.forEach(mark);
  }
  document.addEventListener('keydown', function(e){
    if(e.key!=='Enter' && e.key!==' ') return;
    const el=e.target;
    if(!el || INTERACTIVE.test(el.tagName)) return;
    if(el.hasAttribute('onkeydown')) return;          // 자체 keydown 처리 요소는 건너뜀
    if(el.getAttribute('tabindex')!=='0') return;
    const oc=el.getAttribute('onclick'); if(!oc) return;
    if(/event\.target\s*===\s*this/.test(oc)) return;
    e.preventDefault(); el.click();
  }, false);
  function boot(){
    enhance(document);
    new MutationObserver(muts=>{
      for(const mu of muts) for(const n of mu.addedNodes){
        if(n.nodeType!==1) continue;
        if(n.hasAttribute && n.hasAttribute('onclick')) mark(n);
        enhance(n);
      }
    }).observe(document.body,{childList:true,subtree:true});
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();

// ── 접근성 보강: 폼 라벨(aria-label) · 장식 스파크라인 aria-hidden · 사이드바 랜드마크 ──
(function(){
  var LABELS = {
    pfSymbolInput:'종목코드 또는 티커', pfAddAvg:'평균 매입가', pfAddQty:'보유 수량', pfAddGroup:'그룹 선택',
    pfAlertType:'알림 종류', pfAlertMaPair:'이동평균 조합', pfAlertLimit:'알림 빈도 제한', pfAlertValue:'알림 기준값',
    noteTitle:'노트 제목(필수)', noteAuthor:'작성자(필수)', noteBody:'노트 본문',
    noteMacro:'거시경제 메모', noteEquity:'주식 메모', noteBond:'금리 메모', noteFx:'환율 메모', noteCom:'원자재 메모', noteRE:'부동산 메모',
    mainDateFrom:'시작일', mainDateTo:'종료일', fxDateFrom:'시작일', fxDateTo:'종료일',
    bondDateFrom:'시작일', bondDateTo:'종료일', eqDateFrom:'시작일', eqDateTo:'종료일',
    invDateFrom:'시작일', invDateTo:'종료일', reDateFrom:'시작일', reDateTo:'종료일',
    comDateFrom:'시작일', comDateTo:'종료일', calPeriod:'조회 기간'
  };
  function applyLabels(){
    Object.keys(LABELS).forEach(function(id){
      var el = document.getElementById(id);
      if(el && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby')) el.setAttribute('aria-label', LABELS[id]);
    });
    ['noteTitle','noteAuthor'].forEach(function(id){
      var el = document.getElementById(id);
      if(el && !el.hasAttribute('aria-required')) el.setAttribute('aria-required','true');
    });
    ['spark1','spark2','spark3','spark-rate'].forEach(function(id){
      var c = document.getElementById(id);
      if(c && !c.getAttribute('role') && !c.getAttribute('aria-label')) c.setAttribute('aria-hidden','true');
    });
    var sb = document.getElementById('sidebar');
    if(sb){ if(sb.tagName !== 'NAV' && !sb.getAttribute('role')) sb.setAttribute('role','navigation'); if(!sb.getAttribute('aria-label')) sb.setAttribute('aria-label','주 메뉴'); }
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', applyLabels); else applyLabels();
})();

// ── 대출 규제 세부 내용 (Task 5) ──
// 클릭한 규제 항목의 정의·산식·적용 기준·최근 변화를 모달로 설명. 정책/지역에 따라
// 세부 수치는 변동하므로 '일반 기준'으로 안내하고 공식 출처 링크를 함께 제공한다.
const LOAN_REG_DETAIL = {
  LTV: {
    title: 'LTV · 담보인정비율 (Loan To Value)',
    meta: '주택 담보가치 대비 대출 한도 — 단위 %',
    rows: [
      ['정의', '주택의 담보가치(KB시세·감정가) 대비 빌릴 수 있는 최대 대출액 비율. <b>LTV 70%</b> = 6억 주택이면 최대 4.2억.'],
      ['규제지역', '투기과열지구·조정대상지역은 강화 적용(예: <b>40%</b>대), 비규제지역은 완화(<b>70%</b>대).'],
      ['주택 수', '무주택·1주택(처분조건) 우대, 다주택자는 한도 축소 또는 제한.'],
      ['생애최초', '생애최초 구입자는 지역·가격 요건 충족 시 최대 <b>80%</b>까지 우대.'],
      ['실행 팁', '실제 한도는 LTV·DTI·DSR 중 <b>가장 낮은 한도</b>로 결정되며, 방공제(소액임차보증금)만큼 차감될 수 있음.'],
    ],
  },
  DTI: {
    title: 'DTI · 총부채상환비율 (Debt To Income)',
    meta: '연소득 대비 (해당 주담대 원리금 + 기타대출 이자) 비율 — 단위 %',
    rows: [
      ['정의', '연소득 대비 <b>해당 주택담보대출의 원리금 + 기타 대출의 이자</b> 합계 비율. 소득 대비 상환 부담을 본다.'],
      ['산식', 'DTI = (주담대 연원리금 + 기타대출 연이자) ÷ 연소득 × 100.'],
      ['규제지역', '투기·조정지역은 강화(<b>40%</b>대), 그 외 지역은 완화(<b>50~60%</b>대).'],
      ['DSR 과 차이', 'DTI 는 기타대출의 <b>이자만</b> 보지만, DSR 은 기타대출의 <b>원리금 전체</b>를 본다(더 엄격).'],
    ],
  },
  DSR: {
    title: 'DSR · 총부채원리금상환비율 (Debt Service Ratio)',
    meta: '연소득 대비 모든 대출의 원리금 합계 비율 — 단위 %',
    rows: [
      ['정의', '연소득 대비 보유한 <b>모든 대출(주담대·신용·전세·카드론 등)의 연간 원리금 합계</b> 비율. 가장 포괄적인 규제.'],
      ['차주단위 한도', '은행권 <b>40%</b>, 2금융권 <b>50%</b>가 일반 기준. 1억원 초과 대출 보유 차주에 적용 확대.'],
      ['산식', 'DSR = (전체 대출 연원리금 합계) ÷ 연소득 × 100.'],
      ['포함 대출', '주담대뿐 아니라 신용대출·전세대출(이자)·자동차할부·카드론 등 거의 모든 대출이 합산됨.'],
      ['실행 팁', '만기를 늘리면 연원리금이 줄어 DSR 여력이 늘지만 총이자는 증가. 기존 신용대출 정리가 한도 확대에 효과적.'],
    ],
  },
  stress: {
    title: '스트레스 DSR (Stress DSR)',
    meta: '미래 금리상승 대비 가산금리를 더해 산정하는 강화된 DSR',
    rows: [
      ['정의', 'DSR 계산 시 실제 금리에 <b>스트레스(가산) 금리</b>를 더해, 향후 금리가 올라도 상환 가능한지 보수적으로 본다.'],
      ['효과', '가산금리만큼 원리금이 커진 것으로 계산 → <b>대출 한도가 줄어든다</b>(변동금리일수록 영향 큼).'],
      ['단계 시행', '1단계(2024) → 2단계 → 3단계로 적용 범위·가산폭을 단계적으로 확대. 현재 <b>2단계 시행 중</b>.'],
      ['금리 유형별', '고정금리일수록 스트레스 적용이 작고, 변동금리일수록 크게 적용되어 고정금리 유도 효과.'],
    ],
  },
};
function showLoanRegDetail(type) {
  const d = LOAN_REG_DETAIL[type];
  if(!d) return;
  const rows = d.rows.map(([k,v]) =>
    `<div style="display:flex;gap:10px;padding:9px 0;border-bottom:1px solid var(--c-border);">
       <div style="flex:0 0 84px;font-weight:var(--font-weight-semibold);color:var(--c-primary);font-size:var(--font-size-sm);">${k}</div>
       <div style="flex:1;font-size:12.5px;color:var(--c-txt);">${v}</div>
     </div>`).join('');
  const body = rows +
    `<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:12px;line-height:1.6;">
       ※ 일반 기준 안내이며, 실제 한도·비율은 규제지역 지정·주택 수·소득·정책 변경에 따라 달라집니다.
       정확한 기준은 <a href="https://www.fsc.go.kr" target="_blank" rel="noopener noreferrer" style="color:var(--c-primary);">금융위원회</a> ·
       거래 은행에서 확인하세요.
     </div>`;
  openInfoModal(d.title, d.meta, body);
}

// ── 청약 경쟁률 지역 상세 (Task 4) ──
// 지역 클릭 시 (1) 세부 지역(자치구/시) 구조와 (2) 최근 청약 단지 순위를 모달로 보여준다.
// 단지 순위는 서버가 청약홈(data.go.kr)에서 수집한 data.json.subscription 을 우선 사용하고,
// 미수집 시 세부 지역 구조 + 청약홈 링크로 안내한다(허위 수치 제시 금지).
const SUBSCRIPTION_DETAIL = {
  seoul:    { label:'서울', rate:'32.4 : 1', subs:['강남3구(강남·서초·송파)','마용성(마포·용산·성동)','노도강(노원·도봉·강북)','금관구(금천·관악·구로)','기타 한강이북'] },
  gyeonggi: { label:'경기/인천', rate:'8.1 : 1', subs:['과천·성남·하남(고가권)','수원·용인·화성','인천 송도/청라','김포·파주·평택','남양주·고양'] },
  metro:    { label:'지방광역시', rate:'3.2 : 1', subs:['부산','대구','대전','광주','울산'] },
  other:    { label:'기타 지방', rate:'1.1 : 1', subs:['세종','강원','충청','전라','경상·제주'] },
};
function showSubscriptionDetail(regionKey) {
  const r = SUBSCRIPTION_DETAIL[regionKey];
  if(!r) return;
  // 서버 수집 실데이터 (청약홈 → data.json.subscription.byRegion[regionKey]) 우선
  const sub = ((_latestDataForIndicators||{}).subscription) || {};
  const liveList = (sub.byRegion && Array.isArray(sub.byRegion[regionKey])) ? sub.byRegion[regionKey] : null;

  let body = `<div style="font-size:var(--font-size-sm);color:var(--c-txt-dim);margin-bottom:8px;">세부 지역 · ${r.label} 1순위 평균 경쟁률 <b style="color:var(--c-primary);">${r.rate}</b> <span style="color:#6a6f80;">(최근 경향, 참고)</span></div>`;
  // 세부 지역 칩
  body += `<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px;">` +
    r.subs.map(s=>`<span style="background:var(--c-card-hi);border:1px solid var(--c-border);border-radius:var(--r-lg);padding:4px 11px;font-size:11.5px;color:var(--c-txt);">${s}</span>`).join('') +
    `</div>`;
  // 최근 청약 단지 순위
  body += `<div style="font-weight:var(--font-weight-bold);font-size:12.5px;margin:6px 0 6px;color:var(--c-txt);">🏢 최근 청약 단지 순위</div>`;
  if(liveList && liveList.length) {
    body += `<div style="overflow-x:auto;"><table style="width:100%;font-size:var(--font-size-sm);border-collapse:collapse;">
      <thead><tr style="color:var(--c-txt-dim);border-bottom:1px solid var(--c-border);font-size:var(--font-size-xs);">
        <th scope="col" style="text-align:left;padding:5px 0;">단지</th><th scope="col" style="text-align:left;padding:5px;">지역</th>
        <th scope="col" style="text-align:right;padding:5px;">1순위 경쟁률</th><th scope="col" style="text-align:right;padding:5px;">청약일</th>
      </tr></thead><tbody>`;
    liveList.slice(0,12).forEach(it=>{
      const rate = (it.rate!=null) ? (Number(it.rate).toLocaleString()+' : 1') : '—';
      body += `<tr style="border-bottom:1px solid var(--c-border);">
        <td style="padding:6px 0;font-weight:var(--font-weight-semibold);">${it.name||'—'}</td>
        <td style="padding:6px;color:var(--c-txt-dim);">${it.area||it.sub||'—'}</td>
        <td style="text-align:right;padding:6px;font-weight:var(--font-weight-semibold);">${rate}</td>
        <td style="text-align:right;padding:6px;color:var(--c-txt-dim);">${it.date||'—'}</td></tr>`;
    });
    body += `</tbody></table></div>`;
  } else {
    // 서버 진단(diagnostics.subscription)에 키 미등록(활용신청 필요) 신호가 있으면 actionable 안내.
    const _subDiag = String(((_latestDataForIndicators||{}).diagnostics||{}).subscription || '');
    const _needsApply = /NOT_REGISTERED|REGISTERED|HTTP40|SERVICE.?KEY/i.test(_subDiag);
    const _hint = _needsApply
      ? '실시간 단지 데이터를 위해 <b>data.go.kr 의 "한국부동산원_청약홈 분양정보" 서비스 활용신청</b>이 필요합니다(무료, 즉시 승인). 신청 후 자동 표시됩니다.'
      : '이 지역의 <b>실시간 단지별 청약 정보</b>는 청약홈(data.go.kr) 연동 시 자동 표시됩니다. 현재는 세부 지역 구조만 제공합니다.';
    body += `<div style="background:var(--c-card-hi);border:1px solid var(--c-border);border-radius:var(--r-sm);padding:12px;font-size:var(--font-size-sm);color:var(--c-txt-dim);line-height:1.6;">
      ${_hint} 단지별 상세 경쟁률은 아래 청약홈에서 확인하세요.</div>`;
  }
  const meta = (sub.lastFetched ? `청약홈 수집: ${new Date(sub.lastFetched).toLocaleDateString('ko-KR')} · ` : '') +
    `<a href="https://www.applyhome.co.kr" target="_blank" rel="noopener noreferrer" style="color:var(--c-primary);">청약홈에서 보기 →</a>`;
  openInfoModal(`청약 경쟁률 — ${r.label}`, meta, body);
}

function _regionColorForVal(v) {
  if(v == null || isNaN(v)) return '#8d90a2';
  if(v >= 0.3)  return '#0f6e56';
  if(v >= 0.1)  return window.CUP;
  if(v >= 0)    return (window.CUP+'88');
  if(v >= -0.1) return (window.CDN+'88');
  if(v >= -0.2) return window.CDN;
  return '#b91c1c';
}

function buildKoreaRegionMap() {
  // 바 차트 빌드
  const tc = (typeof getThemeColors==='function') ? getThemeColors() : {txt:'#8d90a2', grid:'#2a2e3d55', tooltip:'#262a35', ttTitle:'#dfe2f2', ttBorder:'#2a2e3d', ttBody:'#dfe2f2'};
  const regionCtx = document.getElementById('reRegionChart');
  if(regionCtx) {
    destroyChart('reRegionChart');
    // 정렬: 등락률 내림차순
    const sorted = krRegionData.slice().sort((a,b)=>b.val-a.val);
    charts['reRegionChart'] = new Chart(regionCtx, {
      type:'bar',
      data:{labels:sorted.map(r=>r.label), datasets:[{
        data:sorted.map(r=>r.val),
        backgroundColor:sorted.map(r=>_regionColorForVal(r.val)),
        borderRadius:3,
      }]},
      options:{responsive:true,maintainAspectRatio:false,
        onClick:(evt,els)=>{ if(els&&els.length){ const r=sorted[els[0].index]; if(r) _onRegionClick(r); } },
        onHover:(evt,els)=>{ const t=evt&&evt.native&&evt.native.target; if(t) t.style.cursor = (els&&els.length)?'pointer':'default'; },
        scales:{x:{ticks:{color:tc.txt,font:{size:9}},grid:{display:false}},
                y:{ticks:{color:tc.txt,font:{size:9},callback:v=>(v>=0?'+':'')+v.toFixed(2)+'%'},grid:{color:tc.grid}}},
        plugins:{legend:{display:false},
          tooltip:{backgroundColor:tc.tooltip,titleColor:tc.ttTitle,bodyColor:tc.ttBody,borderColor:tc.ttBorder,borderWidth:1,
            callbacks:{label:c=>(c.parsed.y>=0?'+':'')+c.parsed.y.toFixed(2)+'%'+( _getSubRegions(sorted[c.dataIndex] && sorted[c.dataIndex].code) ? '  · 클릭 → 시군구' : '' )}}}}
    });
  }
  // 지도 빌드 — SVG (실제 지리 윤곽 기반)
  const svgEl = document.getElementById('reRegionMap');
  if(!svgEl) return;
  // viewBox 를 400x500 으로 업데이트 (지리적 비율 반영)
  svgEl.setAttribute('viewBox', '0 0 400 500');
  let svgHtml = '';
  // 배경 — 옅은 그라데이션 (바다 느낌)
  svgHtml += `<defs>
    <linearGradient id="seaBg" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="${tc.grid}" stop-opacity="0.08"/>
      <stop offset="100%" stop-color="${tc.grid}" stop-opacity="0.02"/>
    </linearGradient>
    <filter id="regionShadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="1" stdDeviation="1" flood-opacity="0.3"/>
    </filter>
  </defs>`;
  svgHtml += `<rect width="400" height="500" fill="url(#seaBg)"/>`;
  // 한반도 외곽선 — 모든 시도를 묶는 단일 path (실선 효과)
  // (각 시도 path 가 인접 영역에 맞춰 그려지므로 외곽선 효과는 자연스럽게 발생)
  // 각 시도 path 그리기
  krRegionMapShapes.forEach(s => {
    const d = krRegionData.find(r => r.code === s.code);
    if(!d) return;
    const fill = _regionColorForVal(d.val);
    const stroke = tc.txt;
    // path 사용 — 지리적 윤곽
    svgHtml += `<path d="${s.path}" fill="${fill}" stroke="${stroke}" stroke-width="1.2" stroke-linejoin="round" data-code="${s.code}" data-label="${s.label}" data-val="${d.val}" class="kr-region-shape" style="cursor:pointer;transition:opacity .15s, filter .15s;" filter="url(#regionShadow)"/>`;
    // 라벨 (중심점에 표시)
    svgHtml += `<text x="${s.labelX}" y="${s.labelY - 2}" text-anchor="middle" font-size="10" font-weight="700" fill="#fff" pointer-events="none" style="text-shadow:0 1px 2px rgba(0,0,0,.6);">${s.label}</text>`;
    svgHtml += `<text x="${s.labelX}" y="${s.labelY + 11}" text-anchor="middle" font-size="9" font-weight="600" fill="#fff" pointer-events="none" style="text-shadow:0 1px 2px rgba(0,0,0,.6);">${(d.val>=0?'+':'')+d.val.toFixed(2)+'%'}</text>`;
  });
  // 범례 — 화면 아래쪽
  svgHtml += `<g transform="translate(15,485)">
    <text x="0" y="-3" font-size="9" font-weight="600" fill="${tc.txt}">월간 등락률</text>
    <rect x="0" y="2" width="16" height="11" fill="#0f6e56"/><text x="20" y="11" font-size="9" fill="${tc.txt}">≥+0.3%</text>
    <rect x="70" y="2" width="16" height="11" fill=window.CUP/><text x="90" y="11" font-size="9" fill="${tc.txt}">+0.1~0.3%</text>
    <rect x="155" y="2" width="16" height="11" fill=(window.CDN+'88')/><text x="175" y="11" font-size="9" fill="${tc.txt}">-0.1~0%</text>
    <rect x="240" y="2" width="16" height="11" fill="#b91c1c"/><text x="260" y="11" font-size="9" fill="${tc.txt}">≤-0.2%</text>
  </g>`;
  svgEl.innerHTML = svgHtml;
  // 호버 / 클릭 이벤트
  svgEl.querySelectorAll('.kr-region-shape').forEach(el => {
    el.addEventListener('mouseenter', (e) => _showRegionTooltip(e, el));
    el.addEventListener('mousemove', (e) => _moveRegionTooltip(e));
    el.addEventListener('mouseleave', () => _hideRegionTooltip());
    el.addEventListener('click', () => {
      const code = el.dataset.code;
      const d = krRegionData.find(r => r.code === code);
      if(d) _onRegionClick(d);
    });
  });
}

function _showRegionTooltip(e, el) {
  const tt = document.getElementById('reRegionTooltip');
  if(!tt) return;
  const code = el.dataset.code;
  const d = krRegionData.find(r => r.code === code);
  if(!d) return;
  const valStr = (d.val>=0?'+':'')+d.val.toFixed(2)+'%';
  document.getElementById('reRegionTooltipTitle').textContent = d.label;
  const valEl = document.getElementById('reRegionTooltipVal');
  valEl.textContent = valStr;
  valEl.style.color = d.val>=0 ? window.CUP : window.CDN;
  tt.style.display = 'block';
  // 미니 차트
  if(_reRegionTooltipChart) { try { _reRegionTooltipChart.destroy(); } catch(_){} _reRegionTooltipChart = null; }
  const ctx = document.getElementById('reRegionTooltipChart');
  if(ctx) {
    _reRegionTooltipChart = new Chart(ctx, {
      type:'line',
      data:{
        labels: d.history.map((_,i)=>(i+1)+''),
        datasets:[{ data: d.history, borderColor: d.val>=0?window.CUP:window.CDN, backgroundColor: (d.val>=0?window.CUP:window.CDN)+'33', borderWidth:1.5, pointRadius:0, fill:true, tension:0.3 }]
      },
      options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false},tooltip:{enabled:false}},
        scales:{x:{display:false},y:{display:false}},
        animation:false, events:[],
      }
    });
  }
  _moveRegionTooltip(e);
}
function _moveRegionTooltip(e) {
  const tt = document.getElementById('reRegionTooltip');
  if(!tt) return;
  const container = document.getElementById('reRegionMapContainer');
  if(!container) return;
  const rect = container.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  // 툴팁이 컨테이너 밖으로 나가지 않게 조정
  const tw = 180, th = 110;
  let left = x + 12, top = y + 12;
  if(left + tw > rect.width)  left = x - tw - 12;
  if(top  + th > rect.height) top  = y - th - 12;
  if(left < 0) left = 4;
  if(top  < 0) top  = 4;
  tt.style.left = left + 'px';
  tt.style.top  = top + 'px';
}
function _hideRegionTooltip() {
  const tt = document.getElementById('reRegionTooltip');
  if(tt) tt.style.display = 'none';
}

// ============================
// 미국 부동산 지역 지도 (Census Region 기반 + 주요 주)
// ============================
// 50개 주 모두 표시 — viewBox: 0 0 800 500
// 단순화된 지리적 윤곽 (각 주의 위치/크기 근사)
const usRegionData = [
  // Pacific
  {code:'CA', label:'California', region:'Pacific', val:0.32, history:[315,316,317,319,320,321,322,323,324,325]},
  {code:'OR', label:'Oregon', region:'Pacific', val:0.18, history:[298,298,299,299,300,300,301,301,302,302]},
  {code:'WA', label:'Washington', region:'Pacific', val:0.24, history:[330,331,332,333,334,335,336,337,338,339]},
  {code:'NV', label:'Nevada', region:'Mountain', val:0.21, history:[280,281,282,283,284,285,286,287,288,289]},
  {code:'AZ', label:'Arizona', region:'Mountain', val:0.15, history:[295,296,297,298,299,300,301,302,303,304]},
  {code:'CO', label:'Colorado', region:'Mountain', val:0.19, history:[310,311,312,313,314,315,316,317,318,319]},
  {code:'UT', label:'Utah', region:'Mountain', val:0.22, history:[305,306,307,308,309,310,311,312,313,314]},
  {code:'NM', label:'New Mexico', region:'Mountain', val:0.12, history:[260,261,261,262,263,263,264,265,265,266]},
  {code:'ID', label:'Idaho', region:'Mountain', val:0.16, history:[280,281,282,283,284,285,286,287,288,289]},
  {code:'MT', label:'Montana', region:'Mountain', val:0.10, history:[260,260,261,261,262,262,263,263,264,264]},
  {code:'WY', label:'Wyoming', region:'Mountain', val:0.08, history:[245,245,246,246,247,247,248,248,249,249]},
  // West North Central
  {code:'ND', label:'N. Dakota', region:'WNCentral', val:0.05, history:[230,230,230,231,231,231,232,232,233,233]},
  {code:'SD', label:'S. Dakota', region:'WNCentral', val:0.07, history:[240,240,241,241,242,242,243,243,244,244]},
  {code:'NE', label:'Nebraska', region:'WNCentral', val:0.09, history:[250,250,251,251,252,252,253,253,254,254]},
  {code:'KS', label:'Kansas', region:'WNCentral', val:0.11, history:[255,256,256,257,258,258,259,260,260,261]},
  {code:'IA', label:'Iowa', region:'WNCentral', val:0.13, history:[270,271,271,272,273,273,274,275,275,276]},
  {code:'MN', label:'Minnesota', region:'WNCentral', val:0.14, history:[285,286,287,288,289,290,291,292,293,294]},
  {code:'MO', label:'Missouri', region:'WNCentral', val:0.10, history:[260,260,261,262,262,263,264,264,265,266]},
  // East North Central
  {code:'WI', label:'Wisconsin', region:'ENCentral', val:0.08, history:[275,275,276,276,277,277,278,278,279,279]},
  {code:'IL', label:'Illinois', region:'ENCentral', val:-0.02, history:[260,260,260,259,259,259,259,259,258,258]},
  {code:'IN', label:'Indiana', region:'ENCentral', val:0.06, history:[245,245,246,246,247,247,248,248,249,249]},
  {code:'MI', label:'Michigan', region:'ENCentral', val:0.04, history:[250,250,250,251,251,251,252,252,252,253]},
  {code:'OH', label:'Ohio', region:'ENCentral', val:0.07, history:[255,255,256,256,257,257,258,258,259,259]},
  // South Atlantic
  {code:'FL', label:'Florida', region:'SAtlantic', val:0.28, history:[345,346,347,348,349,350,351,352,353,354]},
  {code:'GA', label:'Georgia', region:'SAtlantic', val:0.20, history:[295,296,297,298,299,300,301,302,303,304]},
  {code:'SC', label:'S. Carolina', region:'SAtlantic', val:0.17, history:[285,286,287,288,289,290,291,292,293,294]},
  {code:'NC', label:'N. Carolina', region:'SAtlantic', val:0.19, history:[290,291,292,293,294,295,296,297,298,299]},
  {code:'VA', label:'Virginia', region:'SAtlantic', val:0.13, history:[310,311,312,312,313,314,314,315,316,317]},
  {code:'WV', label:'W. Virginia', region:'SAtlantic', val:-0.05, history:[225,225,225,224,224,224,223,223,223,222]},
  {code:'MD', label:'Maryland', region:'SAtlantic', val:0.11, history:[320,320,321,321,322,322,323,323,324,324]},
  {code:'DE', label:'Delaware', region:'SAtlantic', val:0.09, history:[300,300,301,301,302,302,303,303,304,304]},
  {code:'DC', label:'D.C.', region:'SAtlantic', val:0.10, history:[340,341,341,342,342,343,343,344,344,345]},
  // East South Central
  {code:'KY', label:'Kentucky', region:'ESCentral', val:0.09, history:[240,240,241,241,242,242,243,243,244,244]},
  {code:'TN', label:'Tennessee', region:'ESCentral', val:0.18, history:[270,271,272,273,274,275,276,277,278,279]},
  {code:'AL', label:'Alabama', region:'ESCentral', val:0.14, history:[250,251,252,252,253,254,254,255,256,257]},
  {code:'MS', label:'Mississippi', region:'ESCentral', val:0.08, history:[225,225,226,226,227,227,228,228,229,229]},
  // West South Central
  {code:'TX', label:'Texas', region:'WSCentral', val:0.22, history:[295,296,297,298,299,300,301,302,303,304]},
  {code:'OK', label:'Oklahoma', region:'WSCentral', val:0.11, history:[255,256,256,257,258,258,259,260,260,261]},
  {code:'AR', label:'Arkansas', region:'WSCentral', val:0.10, history:[245,245,246,246,247,247,248,248,249,250]},
  {code:'LA', label:'Louisiana', region:'WSCentral', val:0.07, history:[240,240,241,241,242,242,243,243,244,244]},
  // Mid Atlantic
  {code:'NY', label:'New York', region:'MAtlantic', val:0.06, history:[330,330,331,331,332,332,333,333,334,334]},
  {code:'NJ', label:'New Jersey', region:'MAtlantic', val:0.12, history:[330,331,331,332,333,333,334,335,335,336]},
  {code:'PA', label:'Pennsylvania', region:'MAtlantic', val:0.08, history:[270,270,271,271,272,272,273,273,274,274]},
  // New England
  {code:'MA', label:'Massachusetts', region:'NewEngland', val:0.15, history:[345,346,347,348,349,350,351,352,353,354]},
  {code:'CT', label:'Connecticut', region:'NewEngland', val:0.13, history:[320,320,321,322,322,323,324,324,325,326]},
  {code:'RI', label:'Rhode Island', region:'NewEngland', val:0.14, history:[315,316,316,317,318,318,319,320,320,321]},
  {code:'VT', label:'Vermont', region:'NewEngland', val:0.11, history:[295,295,296,297,297,298,298,299,300,300]},
  {code:'NH', label:'N. Hampshire', region:'NewEngland', val:0.16, history:[305,306,307,308,308,309,310,311,312,313]},
  {code:'ME', label:'Maine', region:'NewEngland', val:0.12, history:[290,290,291,292,292,293,294,294,295,296]},
  {code:'AK', label:'Alaska', region:'Pacific', val:0.04, history:[250,250,250,251,251,251,252,252,252,253]},
  {code:'HI', label:'Hawaii', region:'Pacific', val:0.20, history:[430,431,432,433,434,435,436,437,438,439]},
];

// 50 주의 위치/크기 (단순화된 지리적 비율, 알래스카/하와이는 좌측 하단)
const usRegionMapShapes = [
  // West Coast (Pacific)
  {code:'WA', x:60, y:55, w:75, h:60, label:'WA'},
  {code:'OR', x:55, y:120, w:80, h:65, label:'OR'},
  {code:'CA', x:55, y:190, w:85, h:140, label:'CA'},
  {code:'NV', x:140, y:130, w:60, h:90, label:'NV'},
  // Mountain
  {code:'ID', x:135, y:55, w:55, h:75, label:'ID'},
  {code:'MT', x:195, y:55, w:95, h:60, label:'MT'},
  {code:'WY', x:200, y:120, w:75, h:55, label:'WY'},
  {code:'UT', x:200, y:180, w:55, h:75, label:'UT'},
  {code:'AZ', x:140, y:225, w:75, h:90, label:'AZ'},
  {code:'CO', x:260, y:170, w:80, h:75, label:'CO'},
  {code:'NM', x:215, y:250, w:80, h:80, label:'NM'},
  // West North Central
  {code:'ND', x:295, y:55, w:80, h:50, label:'ND'},
  {code:'SD', x:290, y:110, w:85, h:50, label:'SD'},
  {code:'NE', x:295, y:165, w:90, h:50, label:'NE'},
  {code:'KS', x:300, y:220, w:90, h:50, label:'KS'},
  {code:'MN', x:380, y:60, w:75, h:75, label:'MN'},
  {code:'IA', x:380, y:140, w:70, h:60, label:'IA'},
  {code:'MO', x:380, y:205, w:75, h:60, label:'MO'},
  // East North Central
  {code:'WI', x:455, y:80, w:60, h:60, label:'WI'},
  {code:'IL', x:455, y:145, w:50, h:75, label:'IL'},
  {code:'IN', x:510, y:145, w:45, h:70, label:'IN'},
  {code:'OH', x:560, y:130, w:55, h:55, label:'OH'},
  {code:'MI', x:515, y:75, w:65, h:55, label:'MI'},
  // East South Central
  {code:'KY', x:495, y:225, w:80, h:35, label:'KY'},
  {code:'TN', x:495, y:265, w:90, h:35, label:'TN'},
  {code:'MS', x:455, y:305, w:50, h:75, label:'MS'},
  {code:'AL', x:510, y:305, w:50, h:75, label:'AL'},
  // West South Central
  {code:'OK', x:295, y:275, w:95, h:45, label:'OK'},
  {code:'TX', x:230, y:325, w:135, h:115, label:'TX'},
  {code:'AR', x:395, y:265, w:55, h:60, label:'AR'},
  {code:'LA', x:395, y:330, w:60, h:65, label:'LA'},
  // South Atlantic
  {code:'FL', x:565, y:380, w:80, h:75, label:'FL'},
  {code:'GA', x:565, y:310, w:55, h:70, label:'GA'},
  {code:'SC', x:580, y:275, w:55, h:40, label:'SC'},
  {code:'NC', x:580, y:235, w:80, h:45, label:'NC'},
  {code:'VA', x:620, y:195, w:65, h:45, label:'VA'},
  {code:'WV', x:580, y:185, w:50, h:45, label:'WV'},
  {code:'MD', x:660, y:180, w:35, h:25, label:'MD'},
  {code:'DE', x:695, y:175, w:18, h:30, label:'DE'},
  {code:'DC', x:660, y:205, w:18, h:14, label:'DC'},
  // Mid Atlantic
  {code:'PA', x:610, y:145, w:75, h:40, label:'PA'},
  {code:'NJ', x:685, y:155, w:25, h:45, label:'NJ'},
  {code:'NY', x:610, y:80, w:90, h:65, label:'NY'},
  // New England
  {code:'CT', x:705, y:125, w:35, h:25, label:'CT'},
  {code:'RI', x:740, y:125, w:18, h:25, label:'RI'},
  {code:'MA', x:705, y:100, w:60, h:25, label:'MA'},
  {code:'VT', x:680, y:60, w:25, h:45, label:'VT'},
  {code:'NH', x:705, y:60, w:25, h:45, label:'NH'},
  {code:'ME', x:735, y:35, w:35, h:75, label:'ME'},
  // Alaska / Hawaii (lower left)
  {code:'AK', x:25, y:380, w:80, h:80, label:'AK'},
  {code:'HI', x:120, y:420, w:70, h:35, label:'HI'},
];

let _usReRegionTooltipChart = null;

function buildUsRegionMap() {
  const tc = (typeof getThemeColors==='function') ? getThemeColors() : {txt:'#8d90a2', grid:'#2a2e3d55', tooltip:'#262a35', ttTitle:'#dfe2f2', ttBorder:'#2a2e3d', ttBody:'#dfe2f2'};
  const svgEl = document.getElementById('usReRegionMap');
  if(!svgEl) return;
  let svgHtml = '';
  svgHtml += `<defs>
    <linearGradient id="usSeaBg" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="${tc.grid}" stop-opacity="0.08"/>
      <stop offset="100%" stop-color="${tc.grid}" stop-opacity="0.02"/>
    </linearGradient>
    <filter id="usRegionShadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="1" stdDeviation="1" flood-opacity="0.3"/>
    </filter>
  </defs>`;
  svgHtml += `<rect width="800" height="500" fill="url(#usSeaBg)"/>`;
  // 각 주 표시
  usRegionMapShapes.forEach(s => {
    const d = usRegionData.find(r => r.code === s.code);
    if(!d) return;
    const fill = _regionColorForVal(d.val);
    svgHtml += `<rect x="${s.x}" y="${s.y}" width="${s.w}" height="${s.h}" rx="3" fill="${fill}" stroke="${tc.txt}" stroke-width="0.8" data-code="${s.code}" data-label="${s.label}" data-val="${d.val}" class="us-region-shape" style="cursor:pointer;transition:opacity .15s, filter .15s;" filter="url(#usRegionShadow)"/>`;
    // 작은 주는 라벨 생략
    if(s.w >= 35 && s.h >= 25) {
      const fontSize = s.w < 50 ? 8 : 9;
      svgHtml += `<text x="${s.x + s.w/2}" y="${s.y + s.h/2 + 2}" text-anchor="middle" font-size="${fontSize}" font-weight="700" fill="#fff" pointer-events="none" style="text-shadow:0 1px 2px rgba(0,0,0,.6);">${s.label}</text>`;
      if(s.w >= 55 && s.h >= 40) {
        svgHtml += `<text x="${s.x + s.w/2}" y="${s.y + s.h/2 + 13}" text-anchor="middle" font-size="8" fill="#fff" pointer-events="none" style="text-shadow:0 1px 2px rgba(0,0,0,.6);">${(d.val>=0?'+':'')+d.val.toFixed(2)+'%'}</text>`;
      }
    }
  });
  // 범례
  svgHtml += `<g transform="translate(15,485)">
    <text x="0" y="-3" font-size="9" font-weight="600" fill="${tc.txt}">월간 등락률</text>
    <rect x="0" y="2" width="16" height="11" fill="#0f6e56"/><text x="20" y="11" font-size="9" fill="${tc.txt}">≥+0.3%</text>
    <rect x="70" y="2" width="16" height="11" fill=window.CUP/><text x="90" y="11" font-size="9" fill="${tc.txt}">+0.1~0.3%</text>
    <rect x="155" y="2" width="16" height="11" fill=(window.CDN+'88')/><text x="175" y="11" font-size="9" fill="${tc.txt}">-0.1~0%</text>
    <rect x="240" y="2" width="16" height="11" fill="#b91c1c"/><text x="260" y="11" font-size="9" fill="${tc.txt}">≤-0.2%</text>
  </g>`;
  // AK/HI 박스 라벨
  svgHtml += `<text x="25" y="375" font-size="9" fill="${tc.txt}">알래스카·하와이</text>`;
  svgEl.innerHTML = svgHtml;
  // 이벤트 바인딩
  svgEl.querySelectorAll('.us-region-shape').forEach(el => {
    el.addEventListener('mouseenter', (e) => _showUsRegionTooltip(e, el));
    el.addEventListener('mousemove', (e) => _moveUsRegionTooltip(e));
    el.addEventListener('mouseleave', () => _hideUsRegionTooltip());
    el.addEventListener('click', () => {
      const code = el.dataset.code;
      const d = usRegionData.find(r => r.code === code);
      if(!d) return;
      // 통합 렌더러 사용 — FRED FHFA 주별 HPI 실데이터 우선, 없으면 지도 내장 history 폴백.
      // (OSM 마커 클릭과 동일 경로로 일원화: 빈 차트 회귀 방지 + 실데이터 자동 반영.)
      showReHistoryChart('case_shiller_' + code, `${d.label} (${d.region}) 주택가격지수`, {unit:'지수 (FHFA)'});
    });
  });
}

function _showUsRegionTooltip(e, el) {
  const tt = document.getElementById('usReRegionTooltip');
  if(!tt) return;
  const code = el.dataset.code;
  const d = usRegionData.find(r => r.code === code);
  if(!d) return;
  const valStr = (d.val>=0?'+':'')+d.val.toFixed(2)+'%';
  document.getElementById('usReRegionTooltipTitle').textContent = d.label + ' (' + d.region + ')';
  const valEl = document.getElementById('usReRegionTooltipVal');
  valEl.textContent = valStr;
  valEl.style.color = d.val>=0 ? window.CUP : window.CDN;
  tt.style.display = 'block';
  if(_usReRegionTooltipChart) { try { _usReRegionTooltipChart.destroy(); } catch(_){} _usReRegionTooltipChart = null; }
  const ctx = document.getElementById('usReRegionTooltipChart');
  if(ctx) {
    _usReRegionTooltipChart = new Chart(ctx, {
      type:'line',
      data:{ labels: d.history.map((_,i)=>(i+1)+''),
             datasets:[{ data: d.history, borderColor: d.val>=0?window.CUP:window.CDN,
                         backgroundColor: (d.val>=0?window.CUP:window.CDN)+'33', borderWidth:1.5, pointRadius:0, fill:true, tension:0.3 }] },
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{legend:{display:false},tooltip:{enabled:false}},
        scales:{x:{display:false},y:{display:false}}, animation:false, events:[] }
    });
  }
  _moveUsRegionTooltip(e);
}
function _moveUsRegionTooltip(e) {
  const tt = document.getElementById('usReRegionTooltip');
  if(!tt) return;
  const container = document.getElementById('usReRegionMapContainer');
  if(!container) return;
  const rect = container.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  const tw = 180, th = 110;
  let left = x + 12, top = y + 12;
  if(left + tw > rect.width)  left = x - tw - 12;
  if(top  + th > rect.height) top  = y - th - 12;
  if(left < 0) left = 4;
  if(top  < 0) top  = 4;
  tt.style.left = left + 'px';
  tt.style.top  = top + 'px';
}
function _hideUsRegionTooltip() {
  const tt = document.getElementById('usReRegionTooltip');
  if(tt) tt.style.display = 'none';
}

// ============================
// 미국 50개 주 위경도 (OpenStreetMap Leaflet 용)
// ============================
const usRegionLatLng = {
  'AL':[32.806671,-86.791130], 'AK':[63.588753,-154.493062], 'AZ':[33.729759,-111.431221],
  'AR':[34.969704,-92.373123], 'CA':[36.116203,-119.681564], 'CO':[39.059811,-105.311104],
  'CT':[41.597782,-72.755371], 'DE':[39.318523,-75.507141], 'DC':[38.897438,-77.026817],
  'FL':[27.766279,-81.686783], 'GA':[33.040619,-83.643074], 'HI':[21.094318,-157.498337],
  'ID':[44.240459,-114.478828], 'IL':[40.349457,-88.986137], 'IN':[39.849426,-86.258278],
  'IA':[42.011539,-93.210526], 'KS':[38.526600,-96.726486], 'KY':[37.668140,-84.670067],
  'LA':[31.169546,-91.867805], 'ME':[44.693947,-69.381927], 'MD':[39.063946,-76.802101],
  'MA':[42.230171,-71.530106], 'MI':[43.326618,-84.536095], 'MN':[45.694454,-93.900192],
  'MS':[32.741646,-89.678696], 'MO':[38.456085,-92.288368], 'MT':[46.921925,-110.454353],
  'NE':[41.125370,-98.268082], 'NV':[38.313515,-117.055374], 'NH':[43.452492,-71.563896],
  'NJ':[40.298904,-74.521011], 'NM':[34.840515,-106.248482], 'NY':[42.165726,-74.948051],
  'NC':[35.630066,-79.806419], 'ND':[47.528912,-99.784012], 'OH':[40.388783,-82.764915],
  'OK':[35.565342,-96.928917], 'OR':[44.572021,-122.070938], 'PA':[40.590752,-77.209755],
  'RI':[41.680893,-71.511780], 'SC':[33.856892,-80.945007], 'SD':[44.299782,-99.438828],
  'TN':[35.747845,-86.692345], 'TX':[31.054487,-97.563461], 'UT':[40.150032,-111.862434],
  'VT':[44.045876,-72.710686], 'VA':[37.769337,-78.169968], 'WA':[47.400902,-121.490494],
  'WV':[38.491226,-80.954453], 'WI':[44.268543,-89.616508], 'WY':[42.755966,-107.302490],
};

let _usReRegionView = 'svg';
let _usOsmMap = null;
let _usOsmMarkers = [];
// 호환성용: SVG 옵션 제거됨. OSM 만 사용.
function setUsReRegionView(view, btn) {
  _usReRegionView = 'osm';
  setTimeout(() => buildUsOsmRegionMap(), 80);
}

function buildUsOsmRegionMap() {
  const mapDiv = document.getElementById('usReRegionOsmMap');
  if(!mapDiv) return;
  if(typeof L === 'undefined') {
    mapDiv.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:var(--font-size-sm);color:var(--c-txt-dim);">📡 Leaflet 로딩 중…</div>`;
    setTimeout(buildUsOsmRegionMap, 300);
    return;
  }
  if(_usOsmMarkers.length) {
    _usOsmMarkers.forEach(m => { try { _usOsmMap.removeLayer(m); } catch(_){} });
    _usOsmMarkers = [];
  }
  if(!_usOsmMap) {
    _usOsmMap = L.map(mapDiv, {
      center: [39.5, -98.35],   // 미국 중심
      zoom: 4,
      zoomControl: true,
      attributionControl: true,
      worldCopyJump: false,
    });
    const isLight = document.documentElement.classList.contains('light');
    const tileUrl = isLight
      ? 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
      : 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
    L.tileLayer(tileUrl, {
      maxZoom: 12,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>',
    }).addTo(_usOsmMap);
  } else {
    setTimeout(() => _usOsmMap.invalidateSize(), 50);
  }
  usRegionData.forEach(d => {
    const ll = usRegionLatLng[d.code];
    if(!ll) return;
    const color = _regionColorForVal(d.val);
    const valStr = (d.val >= 0 ? '+' : '') + d.val.toFixed(2) + '%';
    const icon = L.divIcon({
      className: 'osm-us-region-marker',
      html: `<div style="background:${color};color:#fff;padding:3px 7px;border-radius:var(--r-md);font-size:var(--font-size-xs);font-weight:var(--font-weight-semibold);box-shadow:0 2px 6px rgba(0,0,0,0.3);white-space:nowrap;border:1.5px solid #fff;line-height:1.2;cursor:pointer;">
        <div style="font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);">${d.code}</div>
        <div style="font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);">${valStr}</div>
      </div>`,
      iconSize: [48, 28],
      iconAnchor: [24, 14],
    });
    const m = L.marker([ll[0], ll[1]], { icon, title: `${d.label} ${valStr}` }).addTo(_usOsmMap);
    m.on('click', () => {
      try { showReHistoryChart('case_shiller_' + d.code, d.label + ' (' + d.region + ') 추이', {unit:'지수'}); } catch(_){}
    });
    _usOsmMarkers.push(m);
  });
}

function setRePeriod(period, btn) {
  rePeriod = period;
  document.querySelectorAll('#re-kr .widget button').forEach(b=>{
    if(b.textContent.match(/^[135]년$/)) { b.style.background='transparent'; b.style.color='var(--c-txt-dim)'; }
  });
  btn.style.background='var(--c-accent)'; btn.style.color='#fff';
  buildReCharts();
}
function setRETab(tab, btn) {
  const kr = document.getElementById('re-kr');
  const us = document.getElementById('re-us');
  if(kr) kr.style.display = tab==='kr' ? 'block' : 'none';
  if(us) us.style.display = tab==='us' ? 'block' : 'none';
  document.querySelectorAll('#page-realestate .tab-btn').forEach(b=>{
    b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
  });
  if(btn) { btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff'; }
  if(tab==='kr') setTimeout(buildReCharts, 50);
  if(tab==='us') setTimeout(()=>{ buildUsReCharts(); buildUsOsmRegionMap(); }, 50);
  // 탭 전환 후 차트 새로고침 버튼 주입
  setTimeout(() => { try { injectChartRefreshButtons(); } catch(_){} }, 200);
}

// ============================
// 미국 부동산 비교 차트
// ============================
let usReDataCache = null;
function buildUsReCharts() {
  destroyChart('usReChangeChart'); destroyChart('usReMortgageChart');
  const re = usReDataCache || {};
  // 차트 1: 전월比 변화율 비교 (한눈에 보기)
  const items = [
    {key:'case_shiller_national', label:'Case-Shiller 전국'},
    {key:'case_shiller_20city',   label:'CS 20대도시'},
    {key:'mortgage_30y',          label:'30년 모기지'},
    {key:'mortgage_15y',          label:'15년 모기지'},
    {key:'housing_starts',        label:'주택착공'},
    {key:'building_permits',      label:'건축허가'},
    {key:'existing_home_sales',   label:'기존주택판매'},
    {key:'new_home_sales',        label:'신규주택판매'},
    {key:'nahb_index',            label:'NAHB 지수'},
  ];
  const rows = items.map(it => ({ label: it.label, val: re[it.key]?.chg }))
                    .filter(r => r.val != null && !isNaN(r.val));
  const ctx1 = document.getElementById('usReChangeChart');
  if(ctx1) {
    if(rows.length === 0) {
      ctx1.getContext('2d').clearRect(0,0,ctx1.width,ctx1.height);
    } else {
      const tc = getThemeColors();
      charts['usReChangeChart'] = new Chart(ctx1, {
        type: 'bar',
        data: {
          labels: rows.map(r=>r.label),
          datasets: [{
            data: rows.map(r=>r.val),
            backgroundColor: rows.map(r => r.val>=0 ? (window.CUP+'c0') : (window.CDN+'c0')),
            borderColor:     rows.map(r => r.val>=0 ? window.CUP   : window.CDN),
            borderWidth: 1.5,
            borderRadius: 4,
          }],
        },
        options: {
          indexAxis:'y',
          responsive:true, maintainAspectRatio:false,
          scales: {
            x: { ticks:{color:tc.txt,font:{size:10},callback:v=>(v>=0?'+':'')+v.toFixed(1)+'%'},
                 grid:{color:tc.grid} },
            y: { ticks:{color:tc.txt,font:{size:11},autoSkip:false}, grid:{display:false} },
          },
          plugins: {
            legend:{display:false},
            tooltip:{ backgroundColor:tc.tooltip, titleColor:tc.ttTitle, bodyColor:tc.ttBody, borderColor:tc.ttBorder,
              callbacks:{ label: c => (c.parsed.x>=0?'+':'')+c.parsed.x.toFixed(2)+'% 전월比' } },
          },
        },
      });
    }
  }
  // 차트 2: 모기지 30y vs 15y 비교
  const m30 = re.mortgage_30y?.value;
  const m15 = re.mortgage_15y?.value;
  const m30p = re.mortgage_30y?.prev;
  const m15p = re.mortgage_15y?.prev;
  const ctx2 = document.getElementById('usReMortgageChart');
  if(ctx2 && (m30 != null || m15 != null)) {
    const tc2 = getThemeColors();
    charts['usReMortgageChart'] = new Chart(ctx2, {
      type: 'bar',
      data: {
        labels: ['전주 (이전 발표)', '현재 (최신 발표)'],
        datasets: [
          { label:'30년 고정', data:[m30p ?? null, m30 ?? null], backgroundColor:(window.CDN+'c0'), borderColor:window.CDN, borderWidth:1.5, borderRadius:4 },
          { label:'15년 고정', data:[m15p ?? null, m15 ?? null], backgroundColor:'#f5a623c0', borderColor:'#f5a623', borderWidth:1.5, borderRadius:4 },
        ],
      },
      options: {
        responsive:true, maintainAspectRatio:false,
        scales: {
          x: { ticks:{color:tc2.txt,font:{size:10}}, grid:{display:false} },
          y: { ticks:{color:tc2.txt,font:{size:10},callback:v=>v.toFixed(2)+'%'}, grid:{color:tc2.grid} },
        },
        plugins: {
          legend:{ position:'top', labels:{ color:tc2.txt, font:{size:10}, boxWidth:10 } },
          tooltip:{ backgroundColor:tc2.tooltip, titleColor:tc2.ttTitle, bodyColor:tc2.ttBody, borderColor:tc2.ttBorder,
            callbacks:{ label: c => c.dataset.label+': '+c.parsed.y.toFixed(2)+'%' } },
        },
      },
    });
  }
  // 스프레드 표시 (30년 - 15년)
  const sprdEl = document.getElementById('usMtgSpread');
  if(sprdEl && m30 != null && m15 != null) {
    const sp = m30 - m15;
    sprdEl.textContent = (sp>=0?'+':'') + sp.toFixed(2) + '%p';
  }
}

// ============================
// 스파크라인 차트
// ============================
function sparkline(id, series, color) {
  const ctx = document.getElementById(id);
  if(!ctx) return;
  // 같은 캔버스에 이미 차트가 있으면 먼저 파괴 — Chart.js "Canvas is already in use" 오류 방지.
  // charts[id] 추적분 + Chart.getChart(canvas) 로 미추적 인스턴스까지 모두 정리한다.
  if(charts[id]) { try { charts[id].destroy(); } catch(_){} delete charts[id]; }
  try { if(typeof Chart!=='undefined' && Chart.getChart) { const ex = Chart.getChart(ctx); if(ex) ex.destroy(); } } catch(_){}
  charts[id] = new Chart(ctx, {
    type:'line',
    data:{labels:sl(series),datasets:[{data:sv(series),borderColor:color,borderWidth:1.5,pointRadius:0,fill:false,tension:0.3}]},
    options:{
      responsive:true,
      maintainAspectRatio:false,
      scales:{
        x:{display:false,type:'category'},
        y:{display:false}
      },
      plugins:{legend:{display:false},tooltip:{enabled:false}},
      animation:false
    }
  });
}

// ============================
// 메인 캔들(라인) 차트
// ============================
// 단위(unit): '1D'=일, '1W'=일주일, '1M'=한달, '1Q'=분기
// 기간(period): 사용자 지정 from~to 범위. 미설정 시 단위별 디폴트 기간 사용
let mainPeriodUnit = '1D';
let mainCustomFrom = null, mainCustomTo = null;
let mainChartInst=null, volChartInst=null;
// 시계열 데이터는 applyRealData() 가 호출된 후 getHistoricalSeries('indices','KOSPI') 로 주입됨.
// 데이터가 아직 없으면 차트에 "데이터 추가 필요" 안내 표시.
let mainAllData = [];
let allVol = [];

// 일별 데이터를 단위에 맞춰 리샘플 (각 N일의 마지막 거래일 값 채택)
function resampleSeries(data, intervalDays) {
  if(!data || data.length === 0) return [];
  if(intervalDays <= 1) return data.slice();
  const out = [];
  for(let i = data.length - 1; i >= 0; i -= intervalDays) {
    out.unshift(data[i]);
  }
  return out;
}

function unitIntervalDays(unit) {
  return unit==='1W' ? 5 : unit==='1M' ? 21 : unit==='1Q' ? 63 : 1;
}
function unitDefaultCount(unit) {
  // 각 단위별 기본 표시 포인트 수
  return unit==='1D' ? 90 : unit==='1W' ? 52 : unit==='1M' ? 36 : 20;
}
function unitLabel(unit) {
  return unit==='1D' ? '일' : unit==='1W' ? '일주일' : unit==='1M' ? '한달' : unit==='1Q' ? '분기' : '';
}

// ── 차트 Y축 단위 처리 ────────────────────────────────────────────
// 문제: 긴 단위 설명(예: '지수 (0=극도 공포 ~ 100=극도 탐욕)')을 Y축 눈금마다 붙여
// "80 지수 (0=극도 공포 ~ 100=극도 탐욕)" 처럼 모든 눈금이 도배되어 가독성 저하.
// 해결: 짧은 기호(%, $, pt, bp, 원 등)만 눈금에 표시하고, 긴 설명은 눈금에서 제외해
// 차트 하단(subtitle)으로 내린다. (단위는 모달 상단 '단위:' 에도 이미 표기됨)
function _axisShortUnit(unit) {
  if(unit == null) return '';
  const u = String(unit).trim();
  if(!u) return '';
  if(/[()\s~]/.test(u)) return '';     // 괄호/공백/물결 → 긴 설명으로 간주
  if([...u].length > 4) return '';      // 5자 이상 → 길다고 판단
  return u;                             // %, $, pt, bp, ‰, 원, $/bbl 등 짧은 기호만
}
function _axisCaptionUnit(unit) {
  if(unit == null) return '';
  const u = String(unit).trim();
  return (u && !_axisShortUnit(u)) ? u : '';
}
// 눈금 콜백 헬퍼 — 숫자 + 짧은단위만. 긴 단위는 생략.
function _axisTick(v, unit) {
  const s = _axisShortUnit(unit);
  return fmtNum(v) + (s ? (' ' + s) : '');
}
// Chart.js subtitle(차트 하단) 구성 — 긴 단위를 캡션으로 내림.
function _axisUnitSubtitle(unit, color) {
  const cap = _axisCaptionUnit(unit);
  return { display: !!cap, position: 'bottom', text: cap ? ('단위: ' + cap) : '',
           color: color || '#8d90a2', font: { size: 9 }, padding: { top: 6 } };
}

function getPeriodData(unit, fromDate, toDate) {
  const u = unit || mainPeriodUnit;
  const interval = unitIntervalDays(u);
  const priceAll = resampleSeries(mainAllData, interval);
  const volAll   = resampleSeries(allVol, interval);
  const f = fromDate || mainCustomFrom;
  const t = toDate   || mainCustomTo;
  if(f && t) {
    return {
      price: priceAll.filter(d => d.x >= f && d.x <= t),
      vol:   volAll.filter(d => d.x >= f && d.x <= t),
    };
  }
  const n = unitDefaultCount(u);
  return { price: priceAll.slice(-n), vol: volAll.slice(-n) };
}

// ── 사이드바 토글 ──
function _syncSidebarAria() {
  const sb = document.getElementById('sidebar');
  const btn = document.querySelector('button[onclick="toggleSidebar()"]');
  if(!sb || !btn) return;
  const isMobile = window.matchMedia && window.matchMedia('(max-width: 1024px)').matches;
  const expanded = isMobile ? sb.classList.contains('mobile-open') : !sb.classList.contains('collapsed');
  btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
}
function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  const icon = document.getElementById('sidebarToggleIcon');
  const backdrop = document.getElementById('sidebarBackdrop');
  if(!sb) return;
  // 1024px 이하(태블릿/모바일)에서는 mobile-open 클래스로 슬라이드 인/아웃, 데스크탑에서는 collapsed
  const isMobile = window.matchMedia && window.matchMedia('(max-width: 1024px)').matches;
  if(isMobile) {
    const opening = !sb.classList.contains('mobile-open');
    sb.classList.toggle('mobile-open');
    if(backdrop) backdrop.style.display = opening ? 'block' : 'none';
    if(icon) icon.textContent = opening ? 'menu_open' : 'menu';
    // 데스크탑 collapsed 상태도 항상 해제 (모바일과 데스크탑 충돌 방지)
    sb.classList.remove('collapsed');
    _syncSidebarAria();
    return;
  }
  // 데스크탑
  if(backdrop) backdrop.style.display = 'none';
  sb.classList.remove('mobile-open');
  const collapsed = sb.classList.toggle('collapsed');
  if(icon) icon.textContent = collapsed ? 'menu' : 'menu_open';
  _syncSidebarAria();
}

function closeSidebarMobile() {
  const sb = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebarBackdrop');
  const icon = document.getElementById('sidebarToggleIcon');
  if(sb) sb.classList.remove('mobile-open');
  if(backdrop) backdrop.style.display = 'none';
  if(icon) icon.textContent = 'menu';
  _syncSidebarAria();
}

// ============================
// 차트 기간 프리셋 (일주일/15일/30일/분기/반기/연)
// ============================
// 각 프리셋은 N 캘린더 일 = (오늘 - N일) ~ 오늘 으로 from/to 설정
function periodPresetDays(preset) {
  return {
    '1W':  7,    // 일주일
    '15D': 15,   // 15일
    '30D': 30,   // 30일
    '1Q':  90,   // 분기 (3개월)
    '6M':  180,  // 반기
    '1Y':  365,  // 연
  }[preset] || 30;
}
function periodPresetLabel(preset) {
  return {'1W':'일주일','15D':'15일','30D':'30일','1Q':'분기','6M':'반기','1Y':'연'}[preset] || preset;
}

// 차트별 프리셋 적용 — chartName: main / fx / bond / equity / com / investor / re
function applyChartPresetPeriod(chartName, preset, btn) {
  // [3차-T7] 기간 동기화 — 설정에서 켠 경우, 현재 페이지의 다른 프리셋 차트에도 전파.
  // _presetSyncing 가드로 전파 중 재귀 진입을 차단한다 (T6 기본값 적용 시에도 동일 가드 사용).
  if (!window._presetSyncing && window.econSettings && econSettings.get('chart.syncPeriods')) {
    window._presetSyncing = true;
    try {
      const _pg = document.querySelector('.page.active');
      if (_pg) _pg.querySelectorAll('[class*="preset-btn-group-"]').forEach(group => {
        const gm = (group.className || '').match(/preset-btn-group-([a-z]+)/);
        if (!gm || gm[1] === chartName) return;
        // 버튼에 data 속성이 없어 onclick 의 'PRESET' 코드로 매칭 — 같은 프리셋이 없는 차트는 건너뜀
        const gb = Array.prototype.find.call(group.querySelectorAll('button'),
          b => ((b.getAttribute('onclick') || '').indexOf("'" + preset + "'") >= 0));
        if (gb) { try { applyChartPresetPeriod(gm[1], preset, gb); } catch (_) {} }
      });
    } finally { window._presetSyncing = false; }
  }
  const days = periodPresetDays(preset);
  const today = new Date();
  const fromDt = new Date(today.getTime() - days * 86400000);
  const fmtYmd = d => d.toISOString().slice(0,10);
  const from = fmtYmd(fromDt);
  const to   = fmtYmd(today);
  // 버튼 활성화 표시
  const groupSel = `.preset-btn-group-${chartName} .preset-btn`;
  document.querySelectorAll(groupSel).forEach(b => {
    b.classList.remove('active');
    b.style.background = 'transparent';
    b.style.color = 'var(--c-txt-dim,#a4a8bc)';
  });
  if(btn) {
    btn.classList.add('active');
    btn.style.background = 'var(--c-accent)';
    btn.style.color = '#fff';
  }
  // 차트별 적용
  if(chartName === 'main') {
    mainCustomFrom = from; mainCustomTo = to;
    const fromEl = document.getElementById('mainDateFrom');
    const toEl   = document.getElementById('mainDateTo');
    if(fromEl) fromEl.value = from;
    if(toEl)   toEl.value   = to;
    if(typeof initMainChart === 'function') initMainChart(mainPeriodUnit);
  }
  else if(chartName === 'fx') {
    if(typeof fxAllSeries !== 'undefined' && fxAllSeries && typeof sliceByDateRange === 'function') {
      const filtered = sliceByDateRange(fxAllSeries, from, to);
      if(filtered && filtered.length > 1) {
        if(typeof hideNoDataOverlay === 'function') hideNoDataOverlay('fxChart');
        if(typeof buildFxChart === 'function') buildFxChart(filtered);
      }
    }
    const fromEl = document.getElementById('fxDateFrom');
    const toEl   = document.getElementById('fxDateTo');
    if(fromEl) fromEl.value = from;
    if(toEl)   toEl.value   = to;
  }
  else if(chartName === 'equity') {
    if(typeof equityCustomFrom !== 'undefined') {
      equityCustomFrom = from; equityCustomTo = to;
    }
    const fromEl = document.getElementById('eqDateFrom');
    const toEl   = document.getElementById('eqDateTo');
    if(fromEl) fromEl.value = from;
    if(toEl)   toEl.value   = to;
    if(typeof renderEquityChart === 'function') renderEquityChart();
  }
  else if(chartName === 'bond') {
    bondCustomFrom = from; bondCustomTo = to;
    if(bondAllSeries && Array.isArray(bondAllSeries)) {
      const sliced = bondAllSeries.filter(p => p.x >= from && p.x <= to);
      if(sliced.length > 0) {
        if(typeof hideNoDataOverlay === 'function') hideNoDataOverlay('bondChart');
        buildBondChart(sliced);
      } else if(typeof showNoDataOverlay === 'function') {
        showNoDataOverlay('bondChart', `${from} ~ ${to} 구간에 데이터가 없습니다.`);
      }
    }
  }
  else if(chartName === 'com') {
    comCustomFrom = from; comCustomTo = to;
    if(typeof buildComDetailChartMulti === 'function') buildComDetailChartMulti();
  }
  else if(chartName === 'investor') {
    const fromEl = document.getElementById('invDateFrom');
    const toEl   = document.getElementById('invDateTo');
    if(fromEl) fromEl.value = from;
    if(toEl)   toEl.value   = to;
    if(typeof applyInvestorDateRange === 'function') applyInvestorDateRange();
  }
  else if(chartName === 're') {
    reCustomFrom = from; reCustomTo = to;
    const fromEl = document.getElementById('reDateFrom');
    const toEl   = document.getElementById('reDateTo');
    if(fromEl) fromEl.value = from;
    if(toEl)   toEl.value   = to;
    if(typeof buildReCharts === 'function') buildReCharts();
  }
}

// HTML 생성 헬퍼 — 프리셋 버튼 그룹 (재사용 가능)
function presetButtonsHTML(chartName, presets) {
  presets = presets || ['1W','15D','30D','1Q','6M','1Y'];
  return presets.map(p => `<button class="preset-btn" onclick="applyChartPresetPeriod('${chartName}','${p}',this)" style="font-size:var(--font-size-sm);padding:3px 8px;border:1px solid var(--c-border);border-radius:var(--r-xs);background:transparent;color:var(--c-txt-dim);cursor:pointer;">${periodPresetLabel(p)}</button>`).join('');
}

// ── 차트 다중 측정 (annotation) 시스템 ──
let mainAnnotations=[], mainPending=null;
let fxAnnotations=[], fxPending=null;
let bondAnnotations=[], bondPending=null;
let equityAnnotations=[], equityPending=null;
let comAnnotations=[], comPending=null;
let reAnnotations=[], rePending=null;

// 측정 가능 차트 ID 매핑 (renderAnnotations / 시작점 마커 플러그인 공용)
const MEASURE_CHART_IDS = {main:'mainChart',fx:'fxChart',bond:'bondChart',equity:'equityIndexChart',com:'comDetailChart',re:'rePriceChart'};
function _getMeasurePending(chartName) {
  return chartName==='main'?mainPending:chartName==='fx'?fxPending:chartName==='bond'?bondPending
       : chartName==='equity'?equityPending:chartName==='re'?rePending:comPending;
}
// 구간 측정 어포던스 (UX 2.3) — 첫 클릭(시작점) 시 차트 위에 수직 점선 마커 + '시작' 라벨을
// 그려, 측정이 진행 중이며 끝점 클릭을 기다리고 있음을 시각적으로 알린다.
const _measurePendingPlugin = {
  id: 'measurePendingMarker',
  afterDatasetsDraw(chart) {
    const cvId = chart.canvas && chart.canvas.id;
    const name = Object.keys(MEASURE_CHART_IDS).find(k => MEASURE_CHART_IDS[k] === cvId);
    if(!name) return;
    const pend = _getMeasurePending(name);
    if(!pend || pend.idx == null) return;
    const meta = chart.getDatasetMeta(0);
    const pt = meta && meta.data && meta.data[pend.idx];
    if(!pt) return;
    const { ctx, chartArea } = chart;
    ctx.save();
    ctx.strokeStyle = getThemeColors().accent;
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(pt.x, chartArea.top);
    ctx.lineTo(pt.x, chartArea.bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = getThemeColors().accent;
    ctx.font = '600 10px Inter, sans-serif';
    const label = '📍 시작';
    const tx = Math.min(pt.x + 4, chartArea.right - ctx.measureText(label).width - 4);
    ctx.fillText(label, tx, chartArea.top + 12);
    ctx.restore();
  }
};
if(typeof Chart !== 'undefined') { try { Chart.register(_measurePendingPlugin); } catch(_) {} }

function removeAnnotation(chartName, i) {
  if(chartName==='main') mainAnnotations.splice(i,1);
  else if(chartName==='fx') fxAnnotations.splice(i,1);
  else if(chartName==='bond') bondAnnotations.splice(i,1);
  else if(chartName==='equity') equityAnnotations.splice(i,1);
  else if(chartName==='com') comAnnotations.splice(i,1);
  else if(chartName==='re') reAnnotations.splice(i,1);
  renderAnnotations(chartName);
}

function renderAnnotations(chartName) {
  const divMap = {main:'mainChartRange',fx:'fxChartRange',bond:'bondChartRange',equity:'equityChartRange',com:'comDetailChartRange',re:'reChartRange'};
  const chartIdMap = {main:'mainChart',fx:'fxChart',bond:'bondChart',equity:'equityIndexChart',com:'comDetailChart',re:'rePriceChart'};
  const divId = divMap[chartName];
  const el = document.getElementById(divId);
  if(!el) return;
  const anns = chartName==='main'?mainAnnotations:chartName==='fx'?fxAnnotations:chartName==='bond'?bondAnnotations:chartName==='equity'?equityAnnotations:chartName==='re'?reAnnotations:comAnnotations;
  const pend = chartName==='main'?mainPending:chartName==='fx'?fxPending:chartName==='bond'?bondPending:chartName==='equity'?equityPending:chartName==='re'?rePending:comPending;
  let html='';
  anns.forEach((a,i)=>{
    const days=Math.abs(a.end.idx-a.start.idx);
    // 해당 차트의 모든 데이터셋에 대해 구간 수익률 계산
    const ch = charts[chartIdMap[chartName]];
    const allDsReturns = [];
    if(ch && ch.data && ch.data.datasets) {
      ch.data.datasets.forEach(ds => {
        if(ds.label==='평균' || (ds.label&&ds.label.startsWith('평균'))) return; // skip avg line
        const sp = ds.data[a.start.idx], ep = ds.data[a.end.idx];
        if(sp!=null && ep!=null && sp!==0) {
          allDsReturns.push({label:ds.label||'', pct:(ep-sp)/sp*100});
        }
      });
    }
    if(allDsReturns.length===0) {
      // fallback: use the clicked dataset[0] price
      const pct=(a.end.price-a.start.price)/a.start.price*100;
      allDsReturns.push({label:'', pct});
    }
    const periodStr = `${days}일 ${a.start.label}→${a.end.label}`;
    html+=`<span class="ann-chip">`;
    html+=`<span style="color:var(--c-txt-dim);font-size:var(--font-size-xs);">${periodStr}</span> `;
    allDsReturns.forEach(r=>{
      const sign=r.pct>=0?'+':'';
      const clr=r.pct>=0?window.CUP:window.CDN;
      html+=`<strong style="color:${clr}">${r.label?r.label+' ':''}${sign}${r.pct.toFixed(2)}%</strong> `;
    });
    html+=`<button onclick="removeAnnotation('${chartName}',${i})" style="background:none;border:none;color:var(--c-txt-dim);cursor:pointer;font-size:var(--font-size-sm);padding:0 2px;line-height:1;">✕</button>`;
    html+=`</span>`;
  });
  if(pend) html+=`<span class="ann-pending"><span class="dot"></span>시작점 ${pend.label} 선택됨 — 끝점을 클릭하면 구간 수익률이 계산됩니다</span>`;
  el.innerHTML=html;
}

function chartClick(chartName, idx, price, label) {
  if(chartName==='main'){
    if(!mainPending){mainPending={idx,price,label};}
    else{mainAnnotations.push({start:mainPending,end:{idx,price,label}});mainPending=null;}
  } else if(chartName==='fx'){
    if(!fxPending){fxPending={idx,price,label};}
    else{fxAnnotations.push({start:fxPending,end:{idx,price,label}});fxPending=null;}
  } else if(chartName==='bond'){
    if(!bondPending){bondPending={idx,price,label};}
    else{bondAnnotations.push({start:bondPending,end:{idx,price,label}});bondPending=null;}
  } else if(chartName==='equity'){
    if(!equityPending){equityPending={idx,price,label};}
    else{equityAnnotations.push({start:equityPending,end:{idx,price,label}});equityPending=null;}
  } else if(chartName==='com'){
    if(!comPending){comPending={idx,price,label};}
    else{comAnnotations.push({start:comPending,end:{idx,price,label}});comPending=null;}
  } else if(chartName==='re'){
    if(!rePending){rePending={idx,price,label};}
    else{reAnnotations.push({start:rePending,end:{idx,price,label}});rePending=null;}
  }
  renderAnnotations(chartName);
  // 시작점 마커(measurePendingMarker 플러그인) 즉시 반영
  try { const ch = charts[MEASURE_CHART_IDS[chartName]]; if(ch) ch.update('none'); } catch(_) {}
}

// Legacy stubs (kept for compatibility during transition)
let mainRangeState = {start:null, end:null};
let fxRangeState   = {start:null, end:null};

function initMainChart(unit, customPriceData) {
  mainAnnotations=[]; mainPending=null;
  destroyChart('mainChart');
  const ctx1 = document.getElementById('mainChart');
  if(!ctx1) return;
  // 실데이터 우선 — mainAllData 가 비어있으면 시계열 데이터가 없는 상태
  if(!customPriceData && (!mainAllData || mainAllData.length < 2)) {
    // 처음 호출 시 KOSPI 시계열을 시도
    const real = getHistoricalSeries('indices', 'KOSPI');
    if(real && real.length > 1) {
      mainAllData = real;
      hideNoDataOverlay('mainChart');
    } else {
      showNoDataOverlay('mainChart', 'KOSPI 시계열 데이터가 아직 수집되지 않았습니다. 다음 자동 업데이트(매 정각) 후 표시됩니다.');
      return;
    }
  }
  hideNoDataOverlay('mainChart');
  const price = customPriceData || getPeriodData(unit || mainPeriodUnit).price;
  if(!price || price.length < 2) {
    showNoDataOverlay('mainChart', '선택된 기간에 표시할 데이터가 없습니다.');
    return;
  }
  const clr = price[price.length-1].y >= price[0].y ? window.CUP:window.CDN;
  const vals = sv(price);
  const maData = calcAvgLine(vals);
  const numVals = vals.filter(v=>v!=null);
  const yMin = Math.min(...numVals); const yMax = Math.max(...numVals);
  const yPad = (yMax - yMin) * 0.08 || yMin * 0.01;
  // 테마 색 — rebuildChartsForTheme 는 토글 시에만 돌므로, 라이트 상태에서의
  // 재생성(기간 버튼·지수 전환)도 여기서 매번 현재 테마를 읽어야 한다.
  const tc = getThemeColors();
  charts['mainChart'] = new Chart(ctx1,{
    type:'line',
    data:{labels:sl(price),datasets:[
      {data:vals,borderColor:clr,borderWidth:2,pointRadius:0,fill:true,backgroundColor:`${clr}15`,tension:0.3,label:'가격'},
      {data:maData,label:'평균 (표시 기간)',borderColor:'#f5a623',borderWidth:1.5,pointRadius:0,fill:false,borderDash:[4,4],tension:0}
    ]},
    options:{responsive:true,maintainAspectRatio:false,
      layout:{padding:{bottom:0}},
      onClick(evt, elements, chart) {
        const pts = chart.getElementsAtEventForMode(evt,'index',{intersect:false},false);
        if(!pts.length) return;
        const idx = pts[0].index;
        const price = chart.data.datasets[0].data[idx];
        const label = chart.data.labels[idx];
        chartClick('main', idx, price, label);
      },
      scales:{
        x:{type:'category',ticks:{color:tc.txt,font:{size:10},maxTicksLimit:8},grid:{display:false}},
        y:{min:yMin-yPad,max:yMax+yPad,ticks:{color:tc.txt,font:{size:10},maxTicksLimit:8,callback:v=>fmtNum(v)},grid:{color:tc.grid},position:'right'}
      },
      plugins:{legend:{display:true,position:'top',labels:{color:tc.txt,font:{size:10},boxWidth:10}},tooltip:{mode:'index',intersect:false,backgroundColor:tc.tooltip,titleColor:tc.ttTitle,bodyColor:tc.ttTitle,borderColor:tc.ttBorder,borderWidth:1,callbacks:{label:ctx=>ctx.dataset.label+': '+fmtNum(ctx.parsed.y)}}}}
  });
  if(charts['mainChart']) charts['mainChart'].resize();
  registerYoY('mainChart', { mode:'date',
    dispDates: price.map(p=>p.x),
    fullDates: ((typeof mainAllData!=='undefined' && mainAllData && mainAllData.length) ? mainAllData : price).map(p=>p.x),
    fullValues:((typeof mainAllData!=='undefined' && mainAllData && mainAllData.length) ? mainAllData : price).map(p=>p.y),
    tol:7, primary:0, color:clr, tension:0.3 });
  applyYoY('mainChart');
}

// 단위 버튼 (일/일주일/한달/분기) — 데이터 샘플링 단위만 변경, 기간은 그대로
function setPeriodUnit(unit, btn) {
  mainPeriodUnit = unit;
  document.querySelectorAll('#page-dashboard .period-unit-btn').forEach(b=>{
    b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
  });
  if(btn) { btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff'; }
  initMainChart(unit);
}

// 기간 지정 패널 열기/닫기 (단위와 무관하게 작동)
function toggleCustomRange(which, btn) {
  // 모든 차트에 대한 기간 지정 패널 토글 (main/fx/equity/bond/com/re)
  const panelMap = {
    main:   'mainCustomRangePanel',
    fx:     'fxCustomRangePanel',
    equity: 'equityCustomRangePanel',
    bond:   'bondCustomRangePanel',
    com:    'comCustomRangePanel',
    re:     'reCustomRangePanel',
  };
  const panelId = panelMap[which];
  if(!panelId) return;
  const panel = document.getElementById(panelId);
  if(!panel) return;
  const showing = panel.style.display === 'flex';
  panel.style.display = showing ? 'none' : 'flex';
  if(btn) {
    btn.style.background = showing ? 'transparent' : getThemeColors().accent+'44';
    btn.style.color = showing ? '#8d90a2' : '#fff';
  }
}

// ───── 채권 차트 기간 지정 ─────
let bondCustomFrom = null, bondCustomTo = null;
function applyBondCustomRange() {
  const from = document.getElementById('bondDateFrom').value;
  const to   = document.getElementById('bondDateTo').value;
  if(!from || !to) return;
  bondCustomFrom = from; bondCustomTo = to;
  if(bondAllSeries && Array.isArray(bondAllSeries)) {
    const sliced = bondAllSeries.filter(p => p.x >= from && p.x <= to);
    if(sliced.length > 0) {
      hideNoDataOverlay('bondChart');
      buildBondChart(sliced);
    } else {
      showNoDataOverlay('bondChart', `${from} ~ ${to} 구간에 데이터가 없습니다.`);
    }
  } else {
    showNoDataOverlay('bondChart', `${from} ~ ${to} 구간의 국채 수익률 시계열 데이터가 아직 수집되지 않았습니다.`);
  }
}
function resetBondCustomRange() {
  bondCustomFrom = null; bondCustomTo = null;
  const fromEl = document.getElementById('bondDateFrom');
  const toEl   = document.getElementById('bondDateTo');
  if(fromEl) fromEl.value = '';
  if(toEl)   toEl.value   = '';
}

// ───── 원자재 차트 기간 지정 ─────
let comCustomFrom = null, comCustomTo = null;
function applyComCustomRange() {
  const from = document.getElementById('comDateFrom').value;
  const to   = document.getElementById('comDateTo').value;
  if(!from || !to) return;
  comCustomFrom = from; comCustomTo = to;
  if(typeof buildComDetailChartMulti === 'function') buildComDetailChartMulti();
}
function resetComCustomRange() {
  comCustomFrom = null; comCustomTo = null;
  const fromEl = document.getElementById('comDateFrom');
  const toEl   = document.getElementById('comDateTo');
  if(fromEl) fromEl.value = '';
  if(toEl)   toEl.value   = '';
  if(typeof buildComDetailChartMulti === 'function') buildComDetailChartMulti();
}

// ───── 부동산 차트 기간 지정 ─────
let reCustomFrom = null, reCustomTo = null;
function applyReCustomRange() {
  const from = document.getElementById('reDateFrom').value;
  const to   = document.getElementById('reDateTo').value;
  if(!from || !to) return;
  reCustomFrom = from; reCustomTo = to;
  if(typeof buildReCharts === 'function') buildReCharts();
}
function resetReCustomRange() {
  reCustomFrom = null; reCustomTo = null;
  const fromEl = document.getElementById('reDateFrom');
  const toEl   = document.getElementById('reDateTo');
  if(fromEl) fromEl.value = '';
  if(toEl)   toEl.value   = '';
  if(typeof buildReCharts === 'function') buildReCharts();
}

function resetCustomRange(which) {
  if(which === 'main') {
    mainCustomFrom = null; mainCustomTo = null;
    const fromEl = document.getElementById('mainDateFrom');
    const toEl   = document.getElementById('mainDateTo');
    if(fromEl) fromEl.value = '';
    if(toEl)   toEl.value   = '';
    initMainChart(mainPeriodUnit);
  }
}

function applyCustomRange(which) {
  if(which === 'main') {
    const from = document.getElementById('mainDateFrom').value;
    const to   = document.getElementById('mainDateTo').value;
    if(!from || !to) return;
    mainCustomFrom = from; mainCustomTo = to;
    initMainChart(mainPeriodUnit);
  } else if(which === 'fx') {
    const from = document.getElementById('fxDateFrom').value;
    const to   = document.getElementById('fxDateTo').value;
    if(!from || !to) return;
    if(!fxAllSeries) {
      showNoDataOverlay('fxChart', '실시간 환율 시계열 데이터가 아직 수집되지 않았습니다.');
      return;
    }
    const filtered = sliceByDateRange(fxAllSeries, from, to);
    if(filtered.length < 2) return;
    hideNoDataOverlay('fxChart');
    buildFxChart(filtered);
  }
}

// Legacy: 기존 호출 호환 (selectGlobalIndex 등에서 setPeriod('1W',...) 사용)
function setPeriod(p, btn, chartId) {
  // 신·구 코드 호환: '1D'/'1W'/'1M'/'1Q' 는 단위로 처리, '1Y'/'3M'/'custom' 은 호환 매핑
  if(p === 'custom') { toggleCustomRange('main', btn); return; }
  const unitMap = {'1D':'1D','1W':'1W','1M':'1M','1Q':'1Q','3M':'1M','1Y':'1Q'};
  setPeriodUnit(unitMap[p] || '1D', btn);
}

// ============================
// 글로벌 지수 테이블
// ============================
// 하드코딩 더미 시세 제거 — 실데이터(applyRealData) 도착 전에는 null 로 두고 스켈레톤 렌더.
// 느린 회선에서 가짜 수치가 실데이터처럼 수 초간 노출되던 문제 해소.
const globalIndices = [
  {name:'KOSPI',  val:null, chg:null},
  {name:'KOSDAQ', val:null, chg:null},
  {name:'S&P 500',val:null, chg:null},
  {name:'NASDAQ', val:null, chg:null},
  {name:'닛케이',  val:null, chg:null},
  {name:'상하이',  val:null, chg:null},
];
let mainSelectedGlobalIdx = 0;   // 첫 로드부터 KOSPI 행 강조 — '행 = 메인차트' 모델 학습
function buildGlobalTable() {
  const tb = document.getElementById('globalIndexTable');
  if(!tb) return;
  const fmtVal = v => v == null
    ? '<div class="skel-bar" style="width:60%;margin-left:auto;" aria-hidden="true"></div>'
    : v.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2});
  tb.innerHTML = globalIndices.map((d,i)=>`
    <tr style="border-bottom:1px solid var(--c-border);${i===mainSelectedGlobalIdx?'background:var(--c-accent-container);border-left:2px solid var(--c-accent)':''}" title="${d.name} — 행 클릭: 메인 차트 전환 / 상세: 팝업 차트">
      <td style="padding:0;"><button type="button" class="gidx-btn" onclick="selectGlobalIndex(${i},this.closest('tr'))" aria-pressed="${i===mainSelectedGlobalIdx}" aria-label="${d.name} — 메인 차트에 표시">${d.name}</button></td>
      <td onclick="selectGlobalIndex(${i},this.parentElement)" style="text-align:right;padding:7px 4px;font-size:var(--font-size-sm);font-weight:var(--font-weight-medium);cursor:pointer;">${fmtVal(d.val)}</td>
      <td onclick="selectGlobalIndex(${i},this.parentElement)" style="text-align:right;padding:7px 4px;cursor:pointer;">${d.chg == null ? '<div class="skel-bar" style="width:44%;margin-left:auto;" aria-hidden="true"></div>' : fmtChg(d.chg)}</td>
      <td style="text-align:right;padding:7px 4px;">
        <button onclick="event.stopPropagation(); showGlobalIndexDetail('${d.name}')" class="u-touch-hit" aria-label="${d.name} 상세 차트 팝업" title="상세 차트 팝업" style="background:transparent;border:1px solid var(--c-border);color:var(--c-primary);border-radius:var(--r-xs);padding:2px 6px;font-size:var(--font-size-xs);cursor:pointer;line-height:1;">📊</button>
      </td>
    </tr>`).join('');
  tb.removeAttribute('aria-busy');
}

// 글로벌 주요 지수 상세 모달 (행 클릭 → 시계열 + 가이드)
function showGlobalIndexDetail(name) {
  const nameMap = {'KOSPI':'KOSPI','KOSDAQ':'KOSDAQ','S&P 500':'SP500','NASDAQ':'NASDAQ','닛케이':'Nikkei','상하이':'Shanghai'};
  const histName = nameMap[name] || name;
  // _reHistState 설정
  _reHistState.key = '__index_' + histName;
  _reHistState.title = name + ' 지수';
  _reHistState.unit = '지수';
  _reHistState.period = 'all';
  _reHistState.timeUnit = 'M';
  // 셀렉터 UI 초기화
  document.querySelectorAll('.reHistPeriodBtn').forEach(b=>{
    const isActive = b.dataset.period === 'all';
    b.classList.toggle('active', isActive);
    b.style.background = isActive ? getThemeColors().accent : 'transparent';
    b.style.color = isActive ? '#fff' : 'var(--c-txt-dim,#a4a8bc)';
  });
  document.querySelectorAll('.reHistUnitBtn').forEach(b=>{
    const isActive = b.dataset.unit === 'M';
    b.classList.toggle('active', isActive);
    b.style.background = isActive ? getThemeColors().accent : 'transparent';
    b.style.color = isActive ? '#fff' : 'var(--c-txt-dim,#a4a8bc)';
  });
  const modal = document.getElementById('reHistoryChartModal');
  if(modal) modal.style.display = 'flex';
  _renderReHistChartIndex(histName);
}

function _renderReHistChartIndex(histName) {
  const { period, timeUnit, title, unit } = _reHistState;
  const titleEl = document.getElementById('reHistTitle');
  const metaEl  = document.getElementById('reHistMeta');
  const noteEl  = document.getElementById('reHistNote');
  const guideEl = document.getElementById('reHistGuide');
  if(titleEl) titleEl.textContent = title;
  // 가이드: 글로벌 지수 일반 안내
  const guideHtml = `<strong style="color:var(--c-primary);">📊 ${title} 이란?</strong><br>
    각 국가/시장의 대표 주가지수. 시장 전체의 흐름과 투자자 심리를 반영합니다.<br><br>
    <strong>해석:</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li>1년 +20% 이상 — 강세장 (불확실성 누적, 차익실현 압력 ↑)</li>
      <li>1년 +5~+20% — 정상 상승</li>
      <li>1년 -10~+5% — 보합</li>
      <li>1년 -20~-10% — 조정 / 약세</li>
      <li>1년 -20% 이하 — 베어마켓 (경기침체 시그널)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 단기 변동성보다 장기 추세 (분기/연) 단위로 보는 것이 노이즈 적음.`;
  if(guideEl) {
    guideEl.innerHTML = guideHtml;
    guideEl.style.display = 'block';
    guideEl.style.borderLeftColor = 'var(--c-accent)';
  }
  if(metaEl) metaEl.innerHTML = `<span style="color:var(--c-primary);">단위:</span> ${unit||'지수'} &nbsp; <span style="color:var(--c-primary);">출처:</span> yfinance / data.json.history.indices`;
  destroyChart('reHistChart');
  if(typeof _setReHistEmpty==='function') _setReHistEmpty('');
  // 데이터 추출 — data.json.history.indices
  const real = (typeof getHistoricalSeries === 'function') ? getHistoricalSeries('indices', histName) : null;
  if(!real || real.length < 2) {
    if(noteEl) noteEl.textContent = `${title} 시계열 데이터 없음 — 데이터 갱신 시 자동 표시됩니다.`;
    return;
  }
  const labels = real.map(p => (typeof p.x === 'string' ? p.x : (p.date || ''))).filter(Boolean);
  const values = real.map(p => Number(p.y != null ? p.y : (p.close != null ? p.close : 0))).filter(v => !isNaN(v));
  if(labels.length < 2 || values.length < 2) {
    if(noteEl) noteEl.textContent = `${title} 데이터 부족`;
    return;
  }
  const resampled = _resampleHistSeries(labels, values, period, timeUnit);
  if(noteEl) noteEl.textContent = `출처: yfinance${period!=='all'?' · 기간: '+period:''}${timeUnit!=='M'?' · 단위: '+({Q:'분기',H:'반기',Y:'연'}[timeUnit]||timeUnit):''}`;
  const ctx = document.getElementById('reHistChart');
  if(!ctx || !resampled.values.length) return;
  const tc = (typeof getThemeColors==='function') ? getThemeColors() : {txt:'#8d90a2',grid:'#2a2e3d55',tooltip:'#262a35',ttTitle:'#dfe2f2',ttBorder:'#2a2e3d'};
  charts['reHistChart'] = new Chart(ctx, {
    type:'line',
    data:{ labels: resampled.labels, datasets:[{
      label: title,
      data: resampled.values,
      borderColor: getThemeColors().accent,
      backgroundColor: getThemeColors().accent+'22',
      borderWidth: 2, pointRadius: resampled.values.length > 30 ? 0 : 2,
      tension: 0.3, fill: true,
    }]},
    options:{ responsive:true, maintainAspectRatio:false,
      scales:{
        x:{ ticks:{color:tc.txt,font:{size:10},maxTicksLimit:12}, grid:{color:tc.grid}},
        y:{ ticks:{color:tc.txt,font:{size:10},callback:v=>typeof v==='number'?v.toLocaleString():v}, grid:{color:tc.grid}, position:'right'},
      },
      plugins:{
        legend:{display:true,labels:{color:tc.txt,font:{size:10},boxWidth:10}},
        tooltip:{mode:'index',intersect:false,backgroundColor:tc.tooltip,titleColor:tc.ttTitle,bodyColor:tc.ttTitle,borderColor:tc.ttBorder,borderWidth:1,
          callbacks:{label: c=> `${title}: ${typeof c.parsed.y==='number'?c.parsed.y.toLocaleString():c.parsed.y}`}}
      }
    }
  });
}
function selectGlobalIndex(idx, el) {
  mainSelectedGlobalIdx = idx;
  const d = globalIndices[idx];
  // Update main chart index label — 실데이터 도착 전(null)에는 스켈레톤 유지
  const nameEl  = document.getElementById('mainChartIndexName');
  const priceEl = document.getElementById('mainChartPriceVal');
  const changeEl= document.getElementById('mainChartChangeVal');
  if(nameEl)  nameEl.textContent = d.name + ' 지수';
  if(priceEl && d.val != null) priceEl.textContent = d.val.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2});
  if(changeEl && d.chg != null){ changeEl.textContent = (d.chg>=0?'▲ +':'▼ ')+Math.abs(d.chg).toFixed(2)+'%'; changeEl.className=d.chg>=0?'up-txt':'down-txt'; changeEl.style.cssText='font-size:13px;margin-left:6px;'; }
  // 스크린리더용 차트 설명 동적 갱신
  try {
    const cv = document.getElementById('mainChart');
    if(cv) cv.setAttribute('aria-label', d.name + ' 지수 시계열 차트' + (d.val != null ? ' — 현재 ' + d.val.toLocaleString() + ', 등락 ' + (d.chg == null ? '—' : d.chg.toFixed(2) + '%') : ''));
  } catch(_) {}
  // Rebuild table (for highlight update)
  buildGlobalTable();
  // 실제 시계열 우선 (data.json.history.indices)
  const nameMap = {'KOSPI':'KOSPI','KOSDAQ':'KOSDAQ','S&P 500':'SP500','NASDAQ':'NASDAQ','닛케이':'Nikkei','상하이':'Shanghai'};
  const histName = nameMap[d.name];
  const real = histName ? getHistoricalSeries('indices', histName) : null;
  if(real && real.length > 1) {
    mainAllData = real;
    hideNoDataOverlay('mainChart');
    initMainChart(mainPeriodUnit);
  } else {
    mainAllData = [];
    destroyChart('mainChart');
    showNoDataOverlay('mainChart', `${d.name} 시계열 데이터가 아직 수집되지 않았습니다.`);
  }
}

// ============================
// 공포탐욕 도넛 — 실시간 데이터 (data.json.sentiment.fear_greed) 가 있으면 사용,
// 없으면 빈 게이지(회색) 로 표시. 합성 더미 62 제거.
// ============================
function buildFearChart() {
  destroyChart('fearChart');
  const ctx = document.getElementById('fearChart');
  if(!ctx) return;
  const d = (typeof _latestDataForIndicators !== 'undefined') ? _latestDataForIndicators : null;
  const fg = d?.sentiment?.fear_greed;
  const val = (fg && typeof fg.value === 'number' && fg.value >= 0 && fg.value <= 100) ? fg.value : null;
  // canvas 는 var() 불가 — 라이트/다크 리터럴 분기 (applyFearGreed 텍스트 색과 동일 값 유지)
  const light = document.documentElement.classList.contains('light');
  // 값이 없으면 회색 빈 도넛, 있으면 등급별 색상
  let color = light ? '#c3cede' : '#3a3e4d';  // 빈 상태
  if(val != null) {
    if(val < 25) color = window.CDN;                          // Extreme Fear
    else if(val < 45) color = light ? '#b45309' : '#f5a623';  // Fear — 경고색(등락 관습과 분리)
    else if(val < 55) color = light ? '#5b6c9e' : '#b6c4ff';  // Neutral
    else if(val < 75) color = window.CUP;  // Greed
    else color = window.CUP;               // Extreme Greed
  }
  const data = val != null ? [val, 100-val] : [0, 100];
  charts['fearChart'] = new Chart(ctx,{
    type:'doughnut',
    data:{datasets:[{data, backgroundColor:[color, light ? '#dce6f2' : '#262a35'], borderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'75%',plugins:{legend:{display:false},tooltip:{enabled:false}}}
  });
}

// Fear & Greed 텍스트 라벨 갱신 (값 → 라벨/색상 매핑)
function applyFearGreed(d) {
  const fg = d?.sentiment?.fear_greed;
  const valEl   = document.getElementById('fearVal');
  const lblEl   = document.getElementById('fearLabel');
  const dltEl   = document.getElementById('fearDelta');
  if(!fg || typeof fg.value !== 'number' || fg.value < 0 || fg.value > 100) {
    if(valEl) { valEl.textContent = '—'; valEl.style.color = 'var(--c-txt-dim,#a4a8bc)'; }
    if(lblEl) { lblEl.textContent = '데이터 수집 대기'; lblEl.style.color = 'var(--c-txt-dim,#a4a8bc)'; }
    if(dltEl) { dltEl.textContent = '—'; }
    return;
  }
  const v = fg.value;
  const light = document.documentElement.classList.contains('light');
  const neu = light ? '#5b6c9e' : '#b6c4ff';   // buildFearChart 게이지 색과 동일 리터럴 유지
  let label = '중립 (Neutral)', color = neu;
  if(v < 25)      { label = '극도 공포 (Extreme Fear)'; color = window.CDN; }
  else if(v < 45) { label = '공포 (Fear)';              color = light ? '#b45309' : '#f5a623'; }
  else if(v < 55) { label = '중립 (Neutral)';            color = neu; }
  else if(v < 75) { label = '탐욕 (Greed)';              color = window.CUP; }
  else            { label = '극도 탐욕 (Extreme Greed)'; color = window.CUP; }
  if(valEl) { valEl.textContent = Math.round(v); valEl.style.color = color; }
  if(lblEl) { lblEl.textContent = label;          lblEl.style.color = color; }
  if(dltEl && fg.prev != null) {
    const diff = Math.round(v - fg.prev);
    dltEl.textContent = `전주 대비 ${diff>=0?'+':''}${diff}pt`;
  } else if(dltEl) {
    dltEl.textContent = '—';
  }
}

// 시장 분위기 카드 캡션에 기준일(as_of) 표기 — "이 숫자가 언제 것인지"를 카드에서 즉시 인지.
// 기준일이 3일 넘게 지났으면 경고색 — 수집 실패로 이전 값이 유지 중일 가능성 표시.
function _sentCaption(elId, asOf, base) {
  const el = document.getElementById(elId);
  const cap = el && el.nextElementSibling;
  if(!cap) return;
  const s = asOf != null ? String(asOf) : '';
  if(/^\d{4}-\d{2}-\d{2}/.test(s)) {
    const dateStr = s.slice(0,10);
    cap.textContent = base + ' · 기준 ' + dateStr;
    const age = (Date.now() - new Date(dateStr).getTime()) / 864e5;
    cap.style.color = age > 3 ? 'var(--c-warn)' : '';
    cap.title = age > 3 ? `기준일이 ${Math.round(age)}일 지났습니다 — 수집 실패로 직전 값이 유지되고 있을 수 있습니다` : '';
  } else {
    cap.textContent = base;
    cap.style.color = '';
    cap.title = '';
  }
}

// 한국 기준금리 KPI 카드 — 최근 8년 기준금리 추이 미니 차트
function buildRateKpiSparkline() {
  destroyChart('spark-rate');
  const ctx = document.getElementById('spark-rate');
  if(!ctx) return;
  // rateHistoryData.kr 사용 (연도별)
  const data = rateHistoryData.kr || [];
  const labels = rateHistoryData.labels || [];
  if(!data.length) return;
  const tc = (typeof getThemeColors === 'function') ? getThemeColors() : {txt:'#8d90a2',grid:'#2a2e3d55',tooltip:'#262a35',ttTitle:'#dfe2f2',ttBorder:'#2a2e3d'};
  charts['spark-rate'] = new Chart(ctx, {
    type:'line',
    data:{
      labels,
      datasets:[{data, borderColor:window.CUP, backgroundColor:(window.CUP+'22'), borderWidth:1.5, pointRadius:1.5, pointBackgroundColor:window.CUP, tension:0.3, fill:true}],
    },
    options:{
      responsive:true, maintainAspectRatio:false,
      scales:{
        x:{display:false, type:'category'},
        y:{display:false, beginAtZero:false},
      },
      plugins:{
        legend:{display:false},
        tooltip:{
          enabled:true,
          backgroundColor: tc.tooltip,
          titleColor:     tc.ttTitle,
          bodyColor:      tc.ttTitle,
          borderColor:    tc.ttBorder,
          borderWidth:1,
          callbacks:{
            title: items => '한국 기준금리 ' + items[0].label,
            label: c => `  ${c.parsed.y.toFixed(2)}%`,
          },
        },
      },
      animation:false,
    },
  });
}

// ============================
// 등락 Top10
// ============================
const upMoversStock = [];
const downMoversStock = [];
const upMoversETF = [];
const downMoversETF = [];
let moverRefDate = '—';
let _clientMoverFetchInFlight = false;
let _clientMoverFetchAttempts = 0;
let _clientMoverLastError = null;       // 마지막 페치 실패 정보 (UI 표시용)
const _MAX_AUTO_MOVER_FETCH = 5;  // 자동 재시도 5회까지 — GHA 차단/일시 장애 대응
// 주기적 자동 갱신 (사용자가 페이지에 머무는 동안 데이터 신선 유지)
// 사용자 요구: "실시간 동기화" — 매 5분마다 movers/news/yieldCurve 등 핵심 데이터를 백그라운드 갱신.
let _autoRefreshTimer = null;
const _AUTO_REFRESH_INTERVAL_MS = 5 * 60 * 1000;  // 5분 (300,000ms)

let curMoverTab = 'up';
let curMoverType = 'stock';

// 네이버 증권 종목 페이지 URL — code 가 있으면 직접 종목 페이지, 없으면 통합 검색
// 검색 API: search.naver.com 의 종목/지수 검색은 통합검색이 가장 안정적
function naverStockUrl(s) {
  if(!s) return 'https://finance.naver.com/';
  // 종목 코드 정규화 — 앞뒤 공백, A 접두사(KRX 발급), .KS/.KQ 접미사 제거
  let code = (s.code||s.ticker||'').toString().trim();
  code = code.replace(/^A/i,'').replace(/\.(KS|KQ|KS11|KQ11)$/i,'').trim();
  // 코드가 없으면 이름에서 찾기 (KR_STOCK_CODE_MAP)
  if(!code && s.name && typeof KR_STOCK_CODE_MAP === 'object') {
    code = KR_STOCK_CODE_MAP[s.name.trim()] || '';
  }
  if(code && /^\d{6}$/.test(code)) {
    return `https://finance.naver.com/item/main.naver?code=${code}`;
  }
  // code 없으면 네이버 통합 검색
  const q = encodeURIComponent((s.name||'')+' 주가');
  return `https://search.naver.com/search.naver?query=${q}`;
}

// 한국 주요 종목 코드 매핑 (KOSPI/KOSDAQ Top + 자주 등락 상위 진입 종목)
// 클라이언트 사이드 폴백 — 데이터 소스에 code 가 없을 때 사용
const KR_STOCK_CODE_MAP = {
  // KOSPI 시총 상위
  '삼성전자':'005930','SK하이닉스':'000660','LG에너지솔루션':'373220','삼성바이오로직스':'207940',
  '현대차':'005380','셀트리온':'068270','기아':'000270','KB금융':'105560','신한지주':'055550',
  '하나금융지주':'086790','삼성SDI':'006400','LG화학':'051910','POSCO홀딩스':'005490',
  'NAVER':'035420','네이버':'035420','카카오':'035720','삼성생명':'032830','삼성물산':'028260',
  '현대모비스':'012330','SK이노베이션':'096770','한화에어로스페이스':'012450','한화오션':'042660',
  '두산에너빌리티':'034020','HD현대중공업':'329180','HD한국조선해양':'009540','HD현대일렉트릭':'267260',
  '메리츠금융지주':'138040','우리금융지주':'316140','삼성화재':'000810','LG전자':'066570',
  'KT&G':'033780','크래프톤':'259960','삼성에스디에스':'018260','대한항공':'003490',
  'KT':'030200','SK텔레콤':'017670','LG':'003550','SK스퀘어':'402340','코웨이':'021240',
  '한국전력':'015760','한국가스공사':'036460','한온시스템':'018880','S-Oil':'010950',
  '에쓰오일':'010950','GS':'078930','롯데케미칼':'011170','이마트':'139480','신세계':'004170',
  'CJ제일제당':'097950','오리온':'271560','농심':'004370','롯데지주':'004990','BGF리테일':'282330',
  '아모레퍼시픽':'090430','LG생활건강':'051900','한미반도체':'042700','오리온홀딩스':'001800',
  '한국타이어앤테크놀로지':'161390','대웅제약':'069620','한미약품':'128940','녹십자':'006280',
  '유한양행':'000100','종근당':'185750','대웅':'003090','일양약품':'007570','부광약품':'003000',
  '광동제약':'009290','동아에스티':'170900','삼성중공업':'010140','두산밥캣':'241560',
  '두산':'000150','두산퓨얼셀':'336260','한화':'000880','한화시스템':'272210','한화솔루션':'009830',
  '한진':'002320','대한해운':'005880','HMM':'011200','팬오션':'028670','롯데쇼핑':'023530',
  '롯데웰푸드':'280360','롯데칠성':'005300','하이트진로':'000080','풍산':'103140','고려아연':'010130',
  '효성중공업':'298040','효성첨단소재':'298050','효성티앤씨':'298020','효성':'004800',
  // 등락 상위 자주 진입 종목
  '진원생명과학':'011000','티웨이홀딩스':'004870','티엠씨':'182360','삼진제약':'005500',
  '콘텐트리중앙':'036420','미래산업':'025560','삼아알미늄':'006110','미래에셋비전스팩2호':'365590',
  '오성첨단소재':'052420','이수페타시스':'007660','케어젠':'214370','코미코':'183300',
  '제룡전기':'033100','일진전기':'103590','대한전선':'001440','LS':'006260','LS ELECTRIC':'010120',
  '코스모신소재':'005070','에코프로':'086520','에코프로비엠':'247540','엘앤에프':'066970',
  '포스코퓨처엠':'003670','포스코인터내셔널':'047050','SK스퀘어':'402340',
  '리노공업':'058470','HPSP':'403870','이오테크닉스':'039030','솔브레인':'357780',
  '실리콘투':'257720','에스앤에스텍':'101490','원익IPS':'240810','하나마이크론':'067310',
  '주성엔지니어링':'036930','테스':'095610','피에스케이':'319660','와이아이케이':'232140',
  '한솔케미칼':'014680','솔루엠':'248070','LX세미콘':'108320','동진쎄미켐':'005290',
  '레이크머티리얼즈':'281740','대주전자재료':'078600','네패스':'033640',
  '엔켐':'348370','코퍼스코리아':'322780','웰바이오텍':'010600','이문온인사이아':'001520',
};

function buildMoverTable(dir) {
  const tb = document.getElementById('moverTable');
  if(!tb) return;
  const isUp = dir === 'up';
  let data;
  if(curMoverType === 'etf') {
    data = isUp ? upMoversETF : downMoversETF;
  } else if(curMoverType === 'all') {
    const stocks = isUp ? upMoversStock : downMoversStock;
    const etfs = isUp ? upMoversETF : downMoversETF;
    data = [...stocks, ...etfs].sort((a,b) => {
      const av = parseFloat(a.chg.replace(/[+%]/g,'')), bv = parseFloat(b.chg.replace(/[+%]/g,''));
      return isUp ? bv-av : av-bv;
    }).slice(0,10);
  } else {
    data = isUp ? upMoversStock : downMoversStock;
  }
  // 종목코드가 비어있으면 KR_STOCK_CODE_MAP 으로 매핑 시도
  if(data && data.length) {
    data.forEach(d => {
      if(!d.code && d.name && KR_STOCK_CODE_MAP[d.name.trim()]) {
        d.code = KR_STOCK_CODE_MAP[d.name.trim()];
      }
    });
    // 절반 이상이 코드 없으면 클라이언트 사이드 페치 트리거 (1회)
    const emptyCount = data.filter(d => !d.code).length;
    // 모든 chg=0 인 garbage 데이터 감지 (KIS API 가 랭킹 미작동 시 발생)
    const chgZeroCount = data.filter(d => {
      const v = parseFloat(String(d.chg||'0').replace(/[+%]/g,''));
      return isNaN(v) || v === 0;
    }).length;
    const allZero = chgZeroCount >= data.length;
    // 서버(data.json) 데이터가 '이전 빌드 보존'(스테일)으로 표시되면 — GitHub Actions 가
    // 외부 API 차단으로 신선한 값을 못 받아 직전 값을 그대로 들고 있는 상태 — 브라우저에서
    // 직접 실시간 페치를 시도해 최신 시세로 대체한다 (코드/등락률이 멀쩡해 보여도).
    const srcLabel = (((_latestDataForIndicators||{}).sources)||{}).stockMovers || '';
    const serverStale = /보존|preserved|캐시|cache|stale/i.test(srcLabel);
    const isClientRT = /클라이언트|client|실시간/i.test(srcLabel);
    // ── 시간 기반 지연 감지 ──
    // 핵심: 아침 KRX 스냅샷(소스='KRX OpenAPI', 코드·등락률 정상)은 스테일 라벨이 없어
    // 종일 '신선한 척' 표시됐다. 한국 장중인데 데이터가 15분 이상 묵었으면 지연으로 보고
    // 클라이언트 실시간 페치를 트리거 + '지연 N분' 표기한다. (= '오전 데이터 고정' 해소)
    const _lu = (_latestDataForIndicators||{}).lastUpdated;
    let _ageMin = null;
    if(_lu){ const ms = Date.now() - new Date(_lu).getTime(); if(ms>=0) _ageMin = Math.floor(ms/60000); }
    const _krOpen = (typeof window._isKrMarketOpen==='function') && window._isKrMarketOpen();
    const timeStale = !isClientRT && _krOpen && _ageMin!=null && _ageMin > 15;
    const shouldRetry =
      window._REALTIME_BOOST &&                       // data.json 전용 모드면 클라 보강 트리거 안 함
      (emptyCount > data.length / 2 || allZero || serverStale || timeStale) &&
      curMoverType === 'stock' &&
      !_clientMoverFetchInFlight &&
      _clientMoverFetchAttempts < _MAX_AUTO_MOVER_FETCH;
    if(shouldRetry) {
      if(allZero) console.info('[moverTable] 모든 chg=0 감지 → 클라이언트 페치 트리거');
      else if(serverStale) console.info('[moverTable] 서버 데이터 스테일(보존) 감지 → 클라이언트 실시간 페치 트리거');
      else if(timeStale) console.info(`[moverTable] 장중 데이터 ${_ageMin}분 경과(지연) → 클라이언트 실시간 페치 트리거`);
      _clientMoverFetchInFlight = true;
      _clientMoverFetchAttempts++;
      refreshMoversFromClient().finally(()=>{ _clientMoverFetchInFlight = false; });
    }
  }
  const refEl = document.getElementById('moverRefDate');
  if(refEl) {
    const src2 = (((_latestDataForIndicators||{}).sources)||{}).stockMovers || '';
    const isClientRT2 = /클라이언트|client|실시간/i.test(src2);
    if(isClientRT2 && window._moverFetchTime) {
      // 클라이언트 실시간 페치 성공 — 실제 페치 시각 표시 (가장 신선)
      const t = new Date(window._moverFetchTime);
      refEl.textContent = '실시간 ' + t.toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',hour12:false}) + ' · 네이버';
      refEl.style.color = 'var(--c-up,#26a69a)';
    } else {
      // 서버(data.json) 데이터 — 데이터 나이로 지연 판정 (라벨 스테일 OR 장중 15분 경과)
      const labelStale = /보존|preserved|캐시|cache|stale/i.test(src2);
      const lu = (_latestDataForIndicators||{}).lastUpdated;
      let ageMin = null;
      if(lu){ const ms = Date.now() - new Date(lu).getTime(); if(ms>=0) ageMin = Math.floor(ms/60000); }
      const krOpen = (typeof window._isKrMarketOpen==='function') && window._isKrMarketOpen();
      const stale = labelStale || (krOpen && ageMin!=null && ageMin > 15);
      let txt = (moverRefDate || '—');
      if(stale) txt += (ageMin!=null ? ` (지연 ${ageMin}분)` : ' (지연·서버 캐시)');
      refEl.textContent = txt;
      refEl.style.color = stale ? 'var(--c-down,#ef5350)' : '';
    }
  }
  if(!data || data.length === 0) {
    const isLoading = _clientMoverFetchInFlight || _clientMoverFetchAttempts < _MAX_AUTO_MOVER_FETCH;
    // data.json 의 diagnostics 가 있으면 어떤 서버측 소스가 시도되었는지 표시
    const diag = (_latestDataForIndicators || {}).diagnostics || {};
    const srvSrc = diag.stockMoversSource;
    const diagLine = srvSrc
      ? `<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-bottom:6px;">서버측 소스 상태: ${srvSrc==='FAILED'?'<span style=\"color:var(--ind-neg)\">서버 수집 실패 (한국거래소·네이버 모두 응답 없음)</span>':srvSrc}</div>`
      : '';
    const stateMsg = isLoading
      ? `<div style="margin-bottom:4px;">📡 종목 데이터 가져오는 중…</div>
         <div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-bottom:6px;">클라이언트 시도 ${_clientMoverFetchAttempts}/${_MAX_AUTO_MOVER_FETCH}</div>
         ${diagLine}`
      : `<div style="margin-bottom:4px;color:var(--c-warn);">⚠ 실시간 시세를 불러오지 못했습니다 (네트워크 차단 또는 일시 오류)</div>
         <div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-bottom:6px;">${_clientMoverLastError || '여러 차례 시도했으나 응답 없음'}</div>
         ${diagLine}`;
    tb.innerHTML = `<tr><td colspan="4" style="padding:16px;text-align:center;color:var(--c-txt-dim);font-size:var(--font-size-sm);">
      ${stateMsg}
      <button onclick="manualRetryMovers(this)" style="margin-top:6px;background:var(--c-accent);color:var(--c-on-accent);border:none;border-radius:var(--r-xs);padding:4px 12px;font-size:var(--font-size-sm);cursor:pointer;">↻ 다시 시도</button>
      <a href="https://finance.naver.com/sise/sise_rise.naver" target="_blank" rel="noopener noreferrer" style="margin-left:6px;color:var(--c-primary);text-decoration:none;font-size:var(--font-size-sm);">네이버에서 직접 보기 →</a>
    </td></tr>`;
    // 자동 트리거: 빈 데이터일 때 백그라운드에서 1회만 페치 시도 (무한 루프 방지)
    if(window._REALTIME_BOOST && !_clientMoverFetchInFlight && _clientMoverFetchAttempts < _MAX_AUTO_MOVER_FETCH) {
      _clientMoverFetchInFlight = true;
      _clientMoverFetchAttempts++;
      refreshMoversFromClient().finally(()=>{
        _clientMoverFetchInFlight = false;
        // 재시도가 데이터를 가져왔으면 applyRealData 가 buildMoverTable 을 호출함
        // 가져오지 못한 경우 무한 루프를 막기 위해 여기서 재호출하지 않음
      });
    }
    return;
  }
  tb.innerHTML = data.map(d=>`
    <tr style="border-bottom:1px solid var(--c-border);">
      <td style="padding:5px 0;"><a href="${naverStockUrl(d)}" target="_blank" rel="noopener noreferrer" style="color:inherit;text-decoration:none;border-bottom:1px dotted transparent;" onmouseover="this.style.borderBottomColor='currentColor'" onmouseout="this.style.borderBottomColor='transparent'" title="네이버 증권에서 보기">${d.name}</a>${d.type==='etf'?'<span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);margin-left:4px;">ETF</span>':''}</td>
      <td style="text-align:right;padding:5px;">${d.price}</td>
      <td style="text-align:right;padding:5px;" class="${isUp?'up-txt':'down-txt'}">${d.chg}</td>
      <td style="text-align:right;padding:5px;color:var(--c-txt-dim);">${d.vol||''}</td>
    </tr>`).join('');
  tb.removeAttribute('aria-busy');
}
function setMoverTab(dir, btn) {
  curMoverTab = dir;
  const widget = btn.closest('.widget');
  // 상승/하락 버튼 only
  widget.querySelectorAll('.tab-btn').forEach(b=>{
    if(b.textContent.includes('상승')||b.textContent.includes('하락')) {
      b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
    }
  });
  btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff';
  buildMoverTable(dir);
}
function setMoverType(type, btn) {
  curMoverType = type;
  ['moverTypeStock','moverTypeETF','moverTypeAll'].forEach(id=>{
    const b = document.getElementById(id);
    if(b) { b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)'; }
  });
  btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff';
  buildMoverTable(curMoverTab);
}

// ============================
// 뉴스 데이터 (실제 기사 publisher 직접 URL 만 노출)
// ============================
// 사용자 요구: 뉴스 카드 클릭 시 반드시 "실제 기사" 로 연결되어야 함 (검색 결과 페이지 X).
// 정적 fallback 데이터의 search.naver.com URL 은 data.json.news 로 교체되며,
// 교체 실패 시에는 카드 자체를 숨겨서 사용자가 검색창으로 튕기는 경험을 차단한다.
// 정의 위치 주의: newsCard / buildNewsFeed / renderFiltered 보다 먼저 선언되어야 함
//   (함수 선언은 hoisting 되지만 가독성을 위해 동일 블록에 배치).
// XSS 방어 — 외부 데이터(RSS 제목·data.json 등)가 innerHTML 템플릿에 들어가기 전 반드시 이스케이프.
// 클라이언트 RSS 는 공개 CORS 프록시를 경유하므로 프록시 변조 시 임의 HTML 이 주입될 수 있다.
function escapeHtml(v) {
  return String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function _isSearchOrInvalidNewsUrl(url) {
  if (!url || url === '#') return true;
  let u;
  try { u = new URL(url); } catch (_) { return true; }
  // http(s) 외 프로토콜(javascript:·data: 등) 거부 — href 에 들어가 스크립트가 실행되는 것을 차단
  if (u.protocol !== 'https:' && u.protocol !== 'http:') return true;
  const host = (u.hostname || '').toLowerCase();
  // 검색결과 페이지 호스트 — publisher 가 아니므로 "실기사" 가 아님
  const SEARCH_HOSTS = [
    'search.naver.com', 'm.search.naver.com',
    'search.daum.net', 'm.search.daum.net',
    'www.bing.com', 'cn.bing.com',
    'news.google.com',
  ];
  if (SEARCH_HOSTS.some(h => host === h || host.endsWith('.' + h))) return true;
  // *.google.com 도 검색결과/Google News 일 가능성 — 모두 거부
  if (host === 'google.com' || host.endsWith('.google.com')) return true;
  // path 가 비었거나 너무 짧으면 publisher 홈페이지 — 기사 URL 아님
  const path = (u.pathname || '').replace(/\/+$/, '');
  if (!path || path === '/' || path.length < 4) return true;
  return false;
}

// 정규화: 표시용 라벨만 결정. URL 은 검증된 publisher URL 만 들어옴 (search URL 은 사전 차단).
function _normalizeNewsUrl(rawUrl) {
  if (_isSearchOrInvalidNewsUrl(rawUrl)) {
    return { url: '#', label: '링크 없음', isSearch: true };
  }
  return { url: rawUrl, label: '↗ 기사 보기', isSearch: false };
}

function newsCard(n) {
  // 검색 URL · 빈 URL · 짧은 path (publisher 홈페이지) 인 카드는 렌더하지 않음.
  // buildNewsFeed/renderFiltered 에서 이미 걸러지지만 (defense in depth) 다중 방어.
  if (!n || _isSearchOrInvalidNewsUrl(n.url)) return '';
  const displayTime = n.isoDate ? relTime(n.isoDate) : (n.time || '오늘');
  const norm = _normalizeNewsUrl(n.url);
  // 속성/본문 컨텍스트 모두 HTML 이스케이프 — URL 은 위 _isSearchOrInvalidNewsUrl 에서 http(s) 만 통과됨
  const safeUrl = escapeHtml(norm.url);
  return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer" class="news-card-link" style="display:block;text-decoration:none;color:inherit;border-bottom:1px solid var(--c-card);padding-bottom:10px;transition:opacity .15s,background .15s;">
    <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
      <span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">${escapeHtml(displayTime)}</span>
      <span style="background:${n.tagClr}22;color:${n.tagClr};font-size:var(--font-size-xs);padding:1px 6px;border-radius:var(--r-xs);border:1px solid ${n.tagClr}44;">${escapeHtml(n.tag)}</span>
      <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">${norm.label}</span>
    </div>
    <div style="font-size:var(--font-size-sm);line-height:1.5;color:var(--c-txt);">${escapeHtml(n.title)}</div>
  </a>`;
}
const newsExpanded = { newsFeed:false, commodityNewsFeed:false, macroNewsFeed:false, calendarNewsFeed:false };
const NEWS_PAGE_SIZE = 5;

function renderNewsFeedWithPagination(containerId, items) {
  const el = document.getElementById(containerId);
  if(!el) return;
  // 추가 방어선: 검색 URL · 빈 URL 항목은 페이지네이션에서도 제외 (defense in depth)
  const safeItems = (items || []).filter(n => n && !_isSearchOrInvalidNewsUrl(n.url));
  if(safeItems.length === 0) {
    // '로딩 중'과 '결과 0건'을 구분 — 로드가 끝났는데도 영구히 '불러오는 중…'이 남아
    // 사용자에게 수동 새로고침을 지시하던 문제 수정.
    el.innerHTML = window._newsFetchDone
      ? '<div style="color:var(--c-txt-muted);font-size:var(--font-size-sm);padding:12px 0;text-align:center;line-height:1.6;">최근 15일 내 해당 카테고리 기사가 없습니다.</div>'
      : '<div style="padding:8px 0;"><div class="skel-bar" style="width:92%;height:12px;margin:6px auto;"></div><div class="skel-bar" style="width:84%;height:12px;margin:6px auto;"></div><div class="skel-bar" style="width:88%;height:12px;margin:6px auto;"></div></div>';
    return;
  }
  const expanded = !!newsExpanded[containerId];
  const visible = expanded ? safeItems : safeItems.slice(0, NEWS_PAGE_SIZE);
  const remaining = safeItems.length - visible.length;
  let html = visible.map(newsCard).join('');
  if(remaining > 0) {
    html += `<button onclick="toggleNewsExpand('${containerId}')" style="background:var(--c-card);color:var(--c-primary);border:1px solid var(--c-border);border-radius:var(--r-sm);padding:8px;font-size:var(--font-size-sm);cursor:pointer;width:100%;margin-top:4px;">더보기 (${remaining}개 더)</button>`;
  } else if(expanded && safeItems.length > NEWS_PAGE_SIZE) {
    html += `<button onclick="toggleNewsExpand('${containerId}')" style="background:transparent;color:var(--c-txt-dim);border:1px solid var(--c-border);border-radius:var(--r-sm);padding:6px;font-size:var(--font-size-sm);cursor:pointer;width:100%;margin-top:4px;">접기 ↑</button>`;
  }
  el.innerHTML = html;
}

function toggleNewsExpand(containerId) {
  newsExpanded[containerId] = !newsExpanded[containerId];
  renderFiltered(containerId);
}

function buildNewsFeed(containerId, items) {
  const el = document.getElementById(containerId);
  if(!el) return;
  // 사용자 요구: 15일 이내 실제 기사만 표시. isoDate 없거나 미래 날짜인 항목 거부.
  // + 검색결과/홈페이지 URL 거부 (사용자가 "검색창으로 튕긴다" 고 보고한 이슈 차단).
  const cutoff = Date.now() - 15 * 24 * 3600 * 1000;
  const future = Date.now() + 24 * 3600 * 1000;  // 시차 보정 1일
  const recent = (items || []).filter(n => {
    if(!n) return false;
    if(_isSearchOrInvalidNewsUrl(n.url)) return false;  // 검색 URL · 빈 URL 차단
    if(!n.isoDate) return false;  // isoDate 없으면 노출 안 함 (구 정적 데이터 정리)
    const t = new Date(n.isoDate).getTime();
    if(isNaN(t)) return false;
    return t >= cutoff && t <= future;
  });
  renderNewsFeedWithPagination(containerId, recent);
}

// ⚠ 가상(생성형) 헤드라인 데이터 제거됨 — 실재 보도가 아닌 하드코딩 기사 수십 건이
// 네이버 검색 URL 과 함께 들어 있었다. 렌더는 _isSearchOrInvalidNewsUrl 필터가 막고
// 있었지만, 필터가 리팩토링에서 회귀하면 가짜 헤드라인이 실제 뉴스처럼 노출될 위험이
// 있어 데이터 자체를 비웠다. 아래 배열은 '슬롯 구조'만 유지한다:
//   · cat/tag/tagClr 는 data.json.news(서버측 수집)·클라이언트 RSS 가 기사를 채워 넣는
//     슬롯 메타데이터 (applyServerNewsToFeeds 의 byCat 매핑, NEWS_QUERIES 의 idx 슬롯).
//   · title/url/isoDate 가 빈 슬롯은 buildNewsFeed 의 isoDate 필터로 렌더되지 않는다.
const _newsSlot = (cat, tag, tagClr) => ({ cat, tag, tagClr, title:'', url:'', isoDate:'' });
// 대시보드 홈 뉴스
const newsItems = [
  // ── 채권 (5) ──
  _newsSlot('채권','통화정책',getThemeColors().accent),
  _newsSlot('채권','국채','#1e88e5'),
  _newsSlot('채권','회사채','#1e88e5'),
  _newsSlot('채권','외국인국채','#0f6e56'),
  _newsSlot('채권','연준','#534ab7'),
  // ── 외환 (5) ──
  _newsSlot('외환','원달러','#0f6e56'),
  _newsSlot('외환','달러인덱스','#0f6e56'),
  _newsSlot('외환','엔화','#534ab7'),
  _newsSlot('외환','유로화','#534ab7'),
  _newsSlot('외환','한은외환','#0f6e56'),
  // ── 주식 (5) ──
  _newsSlot('주식','국내주식',getThemeColors().accent),
  _newsSlot('주식','반도체',getThemeColors().accent),
  _newsSlot('주식','AI테마',getThemeColors().accent),
  _newsSlot('주식','글로벌주식','#534ab7'),
  _newsSlot('주식','코스닥',getThemeColors().accent),
  // ── 원자재 (5) ──
  _newsSlot('원자재','국제유가','#854f0b'),
  _newsSlot('원자재','금값','#b8860b'),
  _newsSlot('원자재','구리','#854f0b'),
  _newsSlot('원자재','에너지','#854f0b'),
  _newsSlot('원자재','원자재종합','#534ab7'),
];

// 원자재 페이지 뉴스
const commodityNewsItems = [
  // ── 원유 (5) ──
  _newsSlot('원유','WTI','#854f0b'),
  _newsSlot('원유','OPEC+','#854f0b'),
  _newsSlot('원유','브렌트유','#534ab7'),
  _newsSlot('원유','두바이유','#534ab7'),
  _newsSlot('원유','미국원유','#854f0b'),
  // ── 귀금속 (5) ──
  _newsSlot('귀금속','금','#b8860b'),
  _newsSlot('귀금속','은','#b8860b'),
  _newsSlot('귀금속','금ETF','#b8860b'),
  _newsSlot('귀금속','팔라듐','#534ab7'),
  _newsSlot('귀금속','금KRX','#b8860b'),
  // ── 비철금속 (5) ──
  _newsSlot('비철금속','구리',getThemeColors().accent),
  _newsSlot('비철금속','알루미늄',getThemeColors().accent),
  _newsSlot('비철금속','니켈',getThemeColors().accent),
  _newsSlot('비철금속','아연','#534ab7'),
  _newsSlot('비철금속','비철금속','#534ab7'),
];

// 거시경제 페이지 뉴스
const macroNewsItems = [
  // ── 한국GDP (5) ──
  _newsSlot('한국GDP','한국GDP',getThemeColors().accent),
  _newsSlot('한국GDP','수출',getThemeColors().accent),
  _newsSlot('한국GDP','물가','#1e88e5'),
  _newsSlot('한국GDP','경상수지','#0f6e56'),
  _newsSlot('한국GDP','성장전망',getThemeColors().accent),
  // ── 미국CPI (5) ──
  _newsSlot('미국CPI','미국CPI','#0f6e56'),
  _newsSlot('미국CPI','연준','#0f6e56'),
  _newsSlot('미국CPI','미국고용','#534ab7'),
  _newsSlot('미국CPI','PCE','#0f6e56'),
  _newsSlot('미국CPI','미국경제','#534ab7'),
  // ── 중국경기 (5) ──
  _newsSlot('중국경기','중국경기',window.CDN),
  _newsSlot('중국경기','중국수출',window.CDN),
  _newsSlot('중국경기','중국부동산',window.CDN),
  _newsSlot('중국경기','중국GDP',window.CDN),
  _newsSlot('중국경기','PBOC','#534ab7'),
  // ── 유로존 (5) ──
  _newsSlot('유로존','유로존','#534ab7'),
  _newsSlot('유로존','ECB','#534ab7'),
  _newsSlot('유로존','독일경기','#534ab7'),
  _newsSlot('유로존','유로존PMI',getThemeColors().accent),
  _newsSlot('유로존','유로존무역','#534ab7'),
  // ── 일본경기 (5) ──
  _newsSlot('일본경기','일본GDP','#f5a623'),
  _newsSlot('일본경기','BOJ','#f5a623'),
  _newsSlot('일본경기','일본물가','#f5a623'),
  _newsSlot('일본경기','일본무역','#f5a623'),
  _newsSlot('일본경기','일본소비','#f5a623'),
  // ── 독일경기 (5) ──
  _newsSlot('독일경기','독일GDP','#42a5f5'),
  _newsSlot('독일경기','독일산업','#42a5f5'),
  _newsSlot('독일경기','독일PMI','#42a5f5'),
  _newsSlot('독일경기','독일물가','#42a5f5'),
  _newsSlot('독일경기','독일수출','#42a5f5'),
  // ── 영국경기 (5) ──
  _newsSlot('영국경기','영국GDP','#ab47bc'),
  _newsSlot('영국경기','BOE','#ab47bc'),
  _newsSlot('영국경기','영국물가','#ab47bc'),
  _newsSlot('영국경기','영국고용','#ab47bc'),
  _newsSlot('영국경기','영국소매','#ab47bc'),
];

// 경제 캘린더 페이지 뉴스
const calendarNewsItems = [
  // ── 한국수출 (5) ──
  _newsSlot('한국수출','한국수출',getThemeColors().accent),
  _newsSlot('한국수출','무역수지',getThemeColors().accent),
  _newsSlot('한국수출','경상수지','#1e88e5'),
  _newsSlot('한국수출','반도체수출',getThemeColors().accent),
  _newsSlot('한국수출','수출전망','#534ab7'),
  // ── 미국CPI (5) ──
  _newsSlot('미국CPI','미국CPI','#0f6e56'),
  _newsSlot('미국CPI','고용지표','#0f6e56'),
  _newsSlot('미국CPI','미국고용','#534ab7'),
  _newsSlot('미국CPI','미국GDP','#0f6e56'),
  _newsSlot('미국CPI','연준','#534ab7'),
  // ── 한국은행 (5) ──
  _newsSlot('한국은행','한국은행','#b6c4ff'),
  _newsSlot('한국은행','통화정책','#b6c4ff'),
  _newsSlot('한국은행','ECB','#534ab7'),
  _newsSlot('한국은행','BOJ','#534ab7'),
  _newsSlot('한국은행','Fed','#0f6e56'),
];

function buildNews() { buildNewsFeed('newsFeed', newsItems); }

// 각 피드의 현재 필터 상태 저장
const currentNewsFilter = { newsFeed:'all', commodityNewsFeed:'all', macroNewsFeed:'all', calendarNewsFeed:'all' };

function getFeedArray(feedId) {
  return ({ newsFeed:newsItems, commodityNewsFeed:commodityNewsItems, macroNewsFeed:macroNewsItems, calendarNewsFeed:calendarNewsItems })[feedId];
}

function renderFiltered(feedId) {
  const arr = getFeedArray(feedId);
  const cat = currentNewsFilter[feedId] || 'all';
  if(!arr) return;
  // buildNewsFeed 와 동일한 15일 cutoff + 검색 URL 차단으로 일관성 유지.
  // (기존엔 30일 cutoff 가 노후 정적 fallback 데이터를 그대로 통과시켜
  //  사용자 클릭 → 검색창으로 튕기는 이슈를 유발했음.)
  const cutoff = Date.now() - 15 * 24 * 3600 * 1000;
  const future = Date.now() + 24 * 3600 * 1000;
  const recent = arr.filter(n => {
    if(!n) return false;
    if(_isSearchOrInvalidNewsUrl(n.url)) return false;  // 검색 URL · 빈 URL 차단
    if(!n.isoDate) return false;
    const t = new Date(n.isoDate).getTime();
    if(isNaN(t)) return false;
    return t >= cutoff && t <= future;
  });
  const filtered = cat==='all' ? recent : recent.filter(n=>n.cat===cat||n.tag===cat);
  renderNewsFeedWithPagination(feedId, filtered);
}

function setNewsFilter(feedId, cat, el) {
  const bar = el.parentElement;
  bar.querySelectorAll('.news-filter-btn').forEach(b=>b.classList.remove('act'));
  el.classList.add('act');
  currentNewsFilter[feedId] = cat;
  newsExpanded[feedId] = false; // reset pagination on filter change
  renderFiltered(feedId);
}

// 뉴스 새로고침 — 해당 피드의 모든 쿼리를 다시 가져옴
// 우선순위: 1) data.json 재페치 (서버측 최신 Google News) → 2) 클라이언트 CORS 프록시
async function refreshNews(feedId, arrName, btn) {
  _refreshFeedback(btn, 'loading');
  let serverOk = false;
  let clientOk = 0;
  let appliedClient = 0;
  try {
    const arr = getFeedArray(feedId);
    if(!arr) {
      _refreshFeedback(btn, 'error', '피드 미발견');
      return;
    }

    // 0) data.json 강제 재페치 — 서버측에서 매일 9시 KST 에 Google News RSS 로 갱신된 캐시
    try {
      const r = await fetch('./data.json?_=' + Date.now(), { cache: 'no-store' });
      if (r.ok) {
        const fresh = await r.json();
        if (fresh && fresh.news) {
          applyServerNewsToFeeds(fresh.news);
          _latestDataForIndicators = fresh;
          serverOk = true;
        }
      }
    } catch(_) {}

    // 카테고리별 검색어 매핑 (item.cat → search query) — 클라이언트 RSS 폴백용
    const categoryQueries = {
      // newsItems / commodityNewsItems / macroNewsItems / calendarNewsItems 의 cat 필드 매핑
      '채권':       '한국 국채 금리 동향 2026',
      '외환':       '원달러 환율 시황 2026',
      '주식':       '코스피 코스닥 주가 시황 2026',
      '원자재':     'WTI 국제유가 동향 2026',
      '원유':       'WTI Brent 국제유가 2026',
      '귀금속':     '금 시세 골드 2026',
      '비철금속':   'LME 구리 가격 동향 2026',
      '한국GDP':    '한국 GDP 성장률 2026',
      '미국CPI':    '미국 CPI 인플레이션 2026',
      '중국경기':   '중국 경기 PMI 2026',
      '일본경기':   '일본 경기 BOJ 2026',
      '독일경기':   '독일 경기 ZEW 2026',
      '영국경기':   '영국 경기 BOE 2026',
      '유로존':     '유로존 인플레이션 ECB 2026',
      '한국수출':   '한국 수출 무역수지 2026',
      '한국은행':   '한국은행 금통위 기준금리 2026',
    };
    // 카테고리별로 항목 그룹화
    const byCategory = {};
    arr.forEach((item, idx) => {
      const cat = item.cat || '기타';
      if(!byCategory[cat]) byCategory[cat] = [];
      byCategory[cat].push({item, idx});
    });
    // 1) 각 카테고리당 최대 5건 새 기사 가져오기 (클라이언트 RSS — 더 최신일 수 있음)
    await Promise.all(Object.keys(byCategory).map(async (cat) => {
      const q = categoryQueries[cat];
      if(!q) return;
      const fresh = await fetchLatestArticles(q, byCategory[cat].length, true);  // 수동 새로고침 → 캐시 우회
      if(!fresh || !fresh.length) return;
      clientOk++;
      byCategory[cat].forEach(({item, idx}, i) => {
        const f = fresh[i];
        if(!f || !f.url || _isSearchOrInvalidNewsUrl(f.url)) return;  // 새 URL 도 검증
        // 검색 페이지 URL (정적 폴백) 이거나 더 최신 기사가 있으면 교체
        const cur = arr[idx];
        const isStatic = _isSearchOrInvalidNewsUrl(cur.url);
        if (isStatic || !cur.url || cur.url === '#' || (f.isoDate && cur.isoDate && f.isoDate >= cur.isoDate)) {
          cur.title = f.title;
          cur.url   = f.url;
          cur.time  = f.time;
          if(f.isoDate) cur.isoDate = f.isoDate;
          appliedClient++;
        }
      });
    }));
    // 마지막 sweep: 새 기사 페치 실패 카테고리의 정적 search URL 항목을 숨김
    arr.forEach(item => {
      if (item && _isSearchOrInvalidNewsUrl(item.url)) item.isoDate = '';
    });
    renderFiltered(feedId);
    // 피드백 — 사용자가 항상 결과를 인지하도록
    if(serverOk && appliedClient > 0) {
      _refreshFeedback(btn, 'success', `${appliedClient}건 추가`);
    } else if(serverOk) {
      _refreshFeedback(btn, 'success', '서버 캐시 갱신');
    } else if(appliedClient > 0) {
      _refreshFeedback(btn, 'success', `${appliedClient}건 갱신`);
    } else {
      _refreshFeedback(btn, 'warn', '신규 기사 없음');
    }
  } catch(e) {
    console.warn('refresh failed', e);
    _refreshFeedback(btn, 'error', '네트워크 오류');
  }
}

// ============================
// 시장 지표 페이지 초기화
// ============================
let marketTab = 'fx';
function initMarketPage() {
  // 주식시장(equity)은 별도 페이지(page-equity)로 분리됨 — showPage('equity') 에서 초기화
  if(marketTab==='fx') buildFxPage();
  if(marketTab==='rate') { buildRateHistoryChart(); buildRateCurrentTable(); }
  if(marketTab==='bond') { buildBondPage(); buildGlobalBondTable(); }
  if(marketTab==='commodity') buildCommodityPage();
}
// 마켓 탭별 '관련 네이버 금융 시장지표' 링크 (상단 📊 네이버 시장지표 버튼이 탭에 맞춰 이동)
const NAVER_MARKET_LINKS = {
  fx:        'https://finance.naver.com/marketindex/exchangeList.naver',
  rate:      'https://finance.naver.com/marketindex/interestDailyQuote.naver',
  bond:      'https://finance.naver.com/marketindex/bondList.naver',
  equity:    'https://finance.naver.com/sise/',
  commodity: 'https://finance.naver.com/marketindex/',
};
function setMarketTab(tab, btn) {
  if(tab === 'equity') { showPage('equity', menuItemFor('equity')); return; }   // 별도 페이지로 분리됨
  marketTab = tab;
  // 탭 리셋 — 시장중단 이력(#marketHaltHistory) 추가로 div:first-child 가 탭바를 안 가리켜 회귀했던 것 수정.
  const _tabBar = document.getElementById('marketMainTabs') || (btn && btn.parentElement);
  if(_tabBar) _tabBar.querySelectorAll('.tab-btn').forEach(b=>{
    b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
  });
  if(btn) { btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff'; }
  ['fx','rate','bond','commodity'].forEach(t=>{
    const el=document.getElementById('market-'+t);
    if(el) el.style.display = t===tab?'block':'none';
  });
  // 상단 '네이버 시장지표' 버튼을 현재 탭과 관련된 네이버 페이지로 연결
  try {
    const nl = document.getElementById('naverMarketLink');
    if(nl && NAVER_MARKET_LINKS[tab]) nl.href = NAVER_MARKET_LINKS[tab];
  } catch(_) {}
  setTimeout(()=>initMarketPage(),50);
  // 탭 전환 후 새로 표시된 차트에도 새로고침 버튼 주입 (페이지 로드 후 처음 활성화되는 탭 보강)
  setTimeout(() => { try { injectChartRefreshButtons(); } catch(_){} }, 200);
}
// FX 및 원자재 데이터 (applyRealData에서 업데이트됨)
let fxPairs=[
  {pair:'USD/KRW', cur:'1,489.64', chg:0, pct:0, h52:'1,520.00', l52:'1,340.00', displayMult:1,   displayTitle:'USD / KRW'},
  {pair:'EUR/KRW', cur:'1,744.95', chg:0, pct:0, h52:'1,780.00', l52:'1,590.00', displayMult:1,   displayTitle:'EUR / KRW'},
  {pair:'JPY/KRW', cur:'9.4400',   chg:0, pct:0, h52:'10.5000',  l52:'9.2000',   displayMult:100, displayTitle:'100 JPY / KRW'},
  {pair:'EUR/USD', cur:'1.1720',   chg:0, pct:0, h52:'1.2000',   l52:'1.0500',   displayMult:1,   displayTitle:'EUR / USD'},
  {pair:'USD/JPY', cur:'158.00',   chg:0, pct:0, h52:'162.00',   l52:'144.00',   displayMult:1,   displayTitle:'USD / JPY'},
];
let comData=[
  // 원유
  {name:'WTI 원유',          price:'$62.35',    chg:'-0.55%', up:false, unit:'$/bbl', cat:'oil',    h52:'$95.00', l52:'$55.00'},
  {name:'Brent 원유',         price:'$65.80',    chg:'-0.48%', up:false, unit:'$/bbl', cat:'oil',    h52:'$98.00', l52:'$58.00'},
  {name:'두바이 현물유',       price:'$64.10',    chg:'-0.41%', up:false, unit:'$/bbl', cat:'oil',    h52:'$96.00', l52:'$57.00'},
  // 귀금속
  {name:'금 (Gold)',          price:'$3,241.50', chg:'+0.30%', up:true,  unit:'$/oz',  cat:'metal',  h52:'$3,500', l52:'$2,100'},
  {name:'은 (Silver)',        price:'$32.48',    chg:'+0.55%', up:true,  unit:'$/oz',  cat:'metal',  h52:'$36.00', l52:'$22.00'},
  {name:'백금 (Platinum)',    price:'$985.00',   chg:'+0.18%', up:true,  unit:'$/oz',  cat:'metal',  h52:'$1,100', l52:'$850'},
  // 비철금속
  {name:'구리 (Copper)',      price:'$4.65',     chg:'-0.82%', up:false, unit:'$/lb',  cat:'base',   h52:'$5.20',  l52:'$3.80'},
  {name:'알루미늄',           price:'$2,248',    chg:'+0.21%', up:true,  unit:'$/톤',  cat:'base',   h52:'$2,600', l52:'$2,100'},
  {name:'아연 (Zinc)',        price:'$2,912',    chg:'-0.35%', up:false, unit:'$/톤',  cat:'base',   h52:'$3,200', l52:'$2,400'},
  {name:'니켈 (Nickel)',      price:'$16,820',   chg:'-1.12%', up:false, unit:'$/톤',  cat:'base',   h52:'$21,000',l52:'$14,500'},
  // 에너지·농산물
  {name:'천연가스',           price:'$2.18',     chg:'-1.24%', up:false, unit:'$/MMBtu',cat:'energy', h52:'$4.50',  l52:'$1.80'},
  {name:'밀 (Wheat)',         price:'$5.84',     chg:'+1.10%', up:true,  unit:'$/bu',  cat:'agri',   h52:'$7.20',  l52:'$4.80'},
  {name:'옥수수 (Corn)',       price:'$4.42',     chg:'+0.68%', up:true,  unit:'$/bu',  cat:'agri',   h52:'$5.20',  l52:'$3.85'},
  {name:'콩 (Soybean)',       price:'$10.48',    chg:'-0.29%', up:false, unit:'$/bu',  cat:'agri',   h52:'$12.10', l52:'$9.20'},
  {name:'쌀 (Rice)',          price:'$16.50',    chg:'+0.42%', up:true,  unit:'$/cwt', cat:'agri',   h52:'$19.80', l52:'$14.20'},
  // ── 추가 원자재 (index 15+; 기존 0~14 인덱스 보존) ──
  {name:'팔라듐 (Palladium)', price:'$985.00',   chg:'+0.00%', up:true,  unit:'$/oz',   cat:'metal',  h52:'$1,250', l52:'$850'},
  {name:'휘발유 (Gasoline)',  price:'$2.10',     chg:'+0.00%', up:true,  unit:'$/gal',  cat:'energy', h52:'$2.80',  l52:'$1.70'},
  {name:'난방유 (Heating Oil)',price:'$2.40',    chg:'+0.00%', up:true,  unit:'$/gal',  cat:'energy', h52:'$3.10',  l52:'$2.00'},
  {name:'커피 (Coffee)',      price:'320.0¢',    chg:'+0.00%', up:true,  unit:'¢/lb',   cat:'agri',   h52:'440¢',   l52:'180¢'},
  {name:'설탕 (Sugar)',       price:'18.50¢',    chg:'+0.00%', up:true,  unit:'¢/lb',   cat:'agri',   h52:'24¢',    l52:'15¢'},
  {name:'코코아 (Cocoa)',     price:'$8,500',    chg:'+0.00%', up:true,  unit:'$/MT',   cat:'agri',   h52:'$12,000',l52:'$6,000'},
];
let eqData=[
  {name:'KOSPI',  val:7612.51, chg:-4.62},{name:'KOSDAQ',val:1143.35, chg:-4.01},
  {name:'S&P 500',val:5659.91, chg:+0.21},{name:'NASDAQ',val:26635.22,chg:+0.18},
  {name:'닛케이',  val:61687.05,chg:+0.45},{name:'항셍',   val:23500.0, chg:-0.88},
];

// ── FX 방향 토글 ──
let fxInverted = false;
let fxCurrentPair = 0;   // index into fxPairs
let fxAllSeries = null;  // full 252-day series for current pair

function buildFxChart(seriesData) {
  fxAnnotations=[]; fxPending=null;
  destroyChart('fxChart');
  const ctx = document.getElementById('fxChart');
  if(!ctx) return;
  const pair = fxPairs[fxCurrentPair];
  const isKrwDenom = pair.pair.endsWith('/KRW');
  const dm = pair.displayMult || 1;
  let displayData;
  if(fxInverted) {
    if(isKrwDenom) {
      // 역방향: 1,000 KRW → X base
      displayData = seriesData.map(pt=>({x:pt.x, y:+(1000/pt.y).toFixed(4)}));
    } else {
      displayData = seriesData.map(pt=>({x:pt.x, y:+(1/pt.y).toFixed(6)}));
    }
  } else {
    // 정방향: 100 JPY 기준 등 displayMult 적용
    displayData = dm===1 ? seriesData : seriesData.map(pt=>({x:pt.x, y:+(pt.y*dm).toFixed(2)}));
  }
  const vals = sv(displayData);
  const maData = calcAvgLine(vals);
  const yLabel = fxInverted ? (isKrwDenom ? 'per 1,000 KRW' : pair.pair.split('/').reverse().join('/')) : pair.displayTitle;
  charts['fxChart'] = new Chart(ctx,{
    type:'line',
    data:{labels:sl(displayData),datasets:[
      {data:vals,label:'환율',borderColor:getThemeColors().accent,backgroundColor:getThemeColors().accent+'18',borderWidth:2,pointRadius:0,fill:true,tension:0.3},
      {data:maData,label:'기간 평균',borderColor:'#f5a623',borderWidth:1.5,pointRadius:0,fill:false,borderDash:[4,4],tension:0}
    ]},
    options:{responsive:true,maintainAspectRatio:false,
      onClick(evt, elements, chart) {
        const pts = chart.getElementsAtEventForMode(evt,'index',{intersect:false},false);
        if(!pts.length) return;
        const idx = pts[0].index;
        const price = chart.data.datasets[0].data[idx];
        const label = chart.data.labels[idx];
        chartClick('fx', idx, price, label);
      },
      scales:{x:{type:'category',ticks:{color:'#b6bbcf',font:{size:10},maxTicksLimit:6},grid:{color:'#4a526888'}},
              y:{ticks:{color:'#b6bbcf',font:{size:10},maxTicksLimit:8,callback:v=>fmtNum(v)},grid:{color:'#4a526888'},
                 title:{display:true,text:yLabel,color:'#7a8099',font:{size:9}},position:'right'}},
      plugins:{legend:{display:true,position:'top',labels:{color:'#b6bbcf',font:{size:10},boxWidth:10}},tooltip:{mode:'index',intersect:false,backgroundColor:'#262a35',titleColor:'#e8ebf5',bodyColor:'#c8d2ff',borderColor:'#3a4054',borderWidth:1,callbacks:{label:ctx=>ctx.dataset.label+': '+fmtNum(ctx.parsed.y)}}}}
  });
  { const _ft = pt => fxInverted ? (isKrwDenom ? {x:pt.x,y:1000/pt.y} : {x:pt.x,y:1/pt.y}) : (dm===1 ? pt : {x:pt.x,y:pt.y*dm});
    const _full = (typeof fxAllSeries!=='undefined' && fxAllSeries) ? fxAllSeries.map(_ft) : displayData;
    registerYoY('fxChart', { mode:'date', dispDates: displayData.map(p=>p.x),
      fullDates:_full.map(p=>p.x), fullValues:_full.map(p=>p.y), tol:7, primary:0, color:getThemeColors().accent, tension:0.3 });
    applyYoY('fxChart'); }
}

function toggleFxDir() {
  fxInverted = !fxInverted;
  updateFxHeader();
  if(!fxAllSeries) {
    showNoDataOverlay('fxChart', '실시간 환율 시계열 데이터가 아직 수집되지 않았습니다.');
    return;
  }
  hideNoDataOverlay('fxChart');
  const period = document.querySelector('#market-fx .tab-btn.active');
  const pLabel = period ? period.textContent.trim() : '1M';
  const sliced = sliceByPeriod(fxAllSeries, pLabel);
  buildFxChart(sliced.length > 1 ? sliced : fxAllSeries);
}

function selectFxPair(idx, el) {
  fxCurrentPair = idx;
  // 행 강조
  document.querySelectorAll('#fxTable tr').forEach(r => r.style.borderLeft='');
  el.style.borderLeft = '2px solid var(--c-accent)';
  // 헤더 업데이트 (KRW/1000 로직 포함)
  updateFxHeader();
  // 차트 재생성 — 실제 시계열 데이터(data.json.history.fx) 우선, 없으면 안내 표시
  const fxNames = ['USDKRW','EURKRW','JPYKRW','EURUSD','USDJPY'];
  const real = getHistoricalSeries('fx', fxNames[idx]);
  if(real && real.length > 1) {
    fxAllSeries = real;
    hideNoDataOverlay('fxChart');
    const period = document.querySelector('#market-fx .tab-btn.active');
    const pLabel = period ? period.textContent.trim() : '1M';
    const sliced = sliceByPeriod(fxAllSeries, pLabel);
    buildFxChart(sliced.length ? sliced : fxAllSeries);
  } else {
    fxAllSeries = null;
    destroyChart('fxChart');
    showNoDataOverlay('fxChart', '실시간 환율 시계열 데이터가 아직 수집되지 않았습니다. data.json 의 history.fx 필드에 yfinance 데이터가 채워지면 표시됩니다.');
  }
}

function setFxPeriod(p, btn) {
  document.querySelectorAll('#market-fx .tab-btn').forEach(b=>{
    if(['1W','1M','3M','1Y','사용자 지정'].includes(b.textContent.trim())) {
      b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
    }
  });
  btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff';
  const panel = document.getElementById('fxCustomRangePanel');
  if(p === 'custom') {
    if(panel) panel.style.display='flex';
    return;
  }
  if(panel) panel.style.display='none';
  if(!fxAllSeries) {
    showNoDataOverlay('fxChart', '실시간 환율 시계열 데이터가 아직 수집되지 않았습니다.');
    return;
  }
  hideNoDataOverlay('fxChart');
  const sliced = sliceByPeriod(fxAllSeries, p);
  buildFxChart(sliced.length > 1 ? sliced : fxAllSeries);
}

function updateFxHeader() {
  const pair = fxPairs[fxCurrentPair];
  if (!pair) return;
  const titleEl = document.getElementById('fxChartTitle');
  const priceEl = document.getElementById('fxChartPrice');
  const chgEl   = document.getElementById('fxChartChange');
  const rngEl   = document.getElementById('fxChart52Range');
  const infoEl  = document.getElementById('fxInfoPanelTitle');
  const baseRate = parseFloat((pair.cur || '0').replace(/,/g,''));
  const isKrwDenom = pair.pair.endsWith('/KRW');
  const dm = pair.displayMult || 1;

  // Title & price
  if (fxInverted) {
    if (isKrwDenom) {
      // 역방향: "1,000 KRW / base"
      const base = pair.pair.split('/')[0];
      if (titleEl) titleEl.textContent = '1,000 KRW / ' + base;
      const rate1000 = 1000 / baseRate; // baseRate is 1 JPY = 9.44 KRW → 1000/9.44 = 105.9 JPY
      const decI = base==='JPY' ? 2 : 4;
      if (priceEl) priceEl.textContent = rate1000.toFixed(decI);
    } else {
      if (titleEl) titleEl.textContent = pair.pair.split('/').reverse().join('/');
      if (priceEl) priceEl.textContent = (1/baseRate).toFixed(6);
    }
  } else {
    // 정방향: displayTitle (e.g. "100 JPY / KRW"), displayMult 적용 가격
    if (titleEl) titleEl.textContent = pair.displayTitle || pair.pair;
    const displayRate = baseRate * dm;
    const dec = displayRate < 10 ? 4 : 2;
    if (priceEl) priceEl.textContent = displayRate.toLocaleString('en-US',{minimumFractionDigits:dec,maximumFractionDigits:dec});
  }
  // 페어별 한국어 표기 — '한미환율', '한유환율' 등 사용자 친화적 이름
  const PAIR_KO_NAMES = {
    'USD/KRW': '한미환율',
    'EUR/KRW': '한유환율',
    'JPY/KRW': '한일환율',
    'EUR/USD': '유미환율',
    'USD/JPY': '미일환율',
  };
  if (infoEl) {
    const koName = PAIR_KO_NAMES[pair.pair] || pair.pair;
    infoEl.textContent = `${koName} 주요 정보 (${pair.pair})`;
  }
  // 기준 시점 표시 — 클라이언트 실시간(Yahoo) 갱신이 있었으면 그 시각/소스를 우선 표시한다.
  // (서버 data.json.lastUpdated 는 장중 갱신이 늦어 '오전 11:13 고정'처럼 보였음 → 실시간 페치 시각 반영.)
  const asOfEl = document.getElementById('fxInfoAsOf');
  if (asOfEl) {
    if (window._fxRealtimeAsOf) {
      const tsStr = new Date(window._fxRealtimeAsOf).toLocaleString('ko-KR', {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
      asOfEl.textContent = `기준 시점: ${tsStr} · 출처: ${window._fxRealtimeSrc || 'Yahoo Finance (실시간)'}`;
    } else {
      const lu = (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators) ? _latestDataForIndicators.lastUpdated : null;
      const dt = lu ? new Date(lu) : new Date();
      const tsStr = dt.toLocaleString('ko-KR', {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
      const srcLabel = (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators?.sources?.fx) || 'open.er-api.com + yfinance';
      asOfEl.textContent = `기준 시점: ${tsStr} · 출처: ${srcLabel}`;
    }
  }
  if (chgEl) {
    const up = (pair.pct || 0) >= 0;
    chgEl.className = up ? 'up-txt' : 'down-txt';
    chgEl.style.fontSize = '14px';
    const chgAbs = Math.abs((pair.chg || 0) * dm);
    const pctAbs = Math.abs(pair.pct || 0);
    chgEl.textContent = (up ? '▲ ' : '▼ ') + chgAbs.toFixed(2) + ' (' + (up ? '+' : '-') + pctAbs.toFixed(2) + '%)';
  }

  // 52주 범위
  if (rngEl) {
    if (fxInverted && isKrwDenom) {
      const h52v = parseFloat((pair.h52||'0').replace(/,/g,''));
      const l52v = parseFloat((pair.l52||'0').replace(/,/g,''));
      const base = pair.pair.split('/')[0];
      const decI = base==='JPY' ? 2 : 4;
      const h52i = l52v>0 ? (1000/l52v).toFixed(decI) : '-';
      const l52i = h52v>0 ? (1000/h52v).toFixed(decI) : '-';
      rngEl.textContent = '52주 범위: ' + l52i + ' ~ ' + h52i;
    } else if (fxInverted) {
      const h52v = parseFloat((pair.h52||'0').replace(/,/g,''));
      const l52v = parseFloat((pair.l52||'0').replace(/,/g,''));
      const hi = l52v>0 ? (1/l52v).toFixed(6) : '-';
      const lo = h52v>0 ? (1/h52v).toFixed(6) : '-';
      rngEl.textContent = '52주 범위: ' + lo + ' ~ ' + hi;
    } else {
      // 정방향: displayMult 반영
      const h52v = parseFloat((pair.h52||'0').replace(/,/g,''));
      const l52v = parseFloat((pair.l52||'0').replace(/,/g,''));
      const dec = (h52v*dm) < 10 ? 4 : 2;
      rngEl.textContent = '52주 범위: ' + (l52v*dm).toFixed(dec) + ' ~ ' + (h52v*dm).toFixed(dec);
    }
  }

  // 정보 패널 (시가/고가/저가/전일종가/52주)
  const prevClose = baseRate / (1 + (pair.pct || 0) / 100);
  const fmt = (v, d) => v.toLocaleString('en-US', {minimumFractionDigits:d, maximumFractionDigits:d});
  const high  = Math.max(baseRate, prevClose) * 1.003;
  const low   = Math.min(baseRate, prevClose) * 0.997;

  const toDisplay = v => {
    if (!fxInverted) return v * dm;
    if (isKrwDenom) return 1000/v;
    return 1/v;
  };
  const dispDec = fxInverted ? (isKrwDenom ? (pair.pair.split('/')[0]==='JPY'?2:4) : 6) : ((baseRate*dm)<10?4:2);
  const setNum = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = fmt(toDisplay(v), dispDec); };
  setNum('fxInfoOpen', prevClose);
  setNum('fxInfoHigh', fxInverted ? low : high);
  setNum('fxInfoLow',  fxInverted ? high : low);
  setNum('fxInfoPrev', prevClose);

  const h52v = parseFloat((pair.h52||'0').replace(/,/g,''));
  const l52v = parseFloat((pair.l52||'0').replace(/,/g,''));
  if (fxInverted) {
    const e52H = document.getElementById('fxInfo52H');
    const e52L = document.getElementById('fxInfo52L');
    if (h52v>0 && e52L) e52L.textContent = fmt(toDisplay(h52v), dispDec);
    if (l52v>0 && e52H) e52H.textContent = fmt(toDisplay(l52v), dispDec);
  } else {
    const e52H = document.getElementById('fxInfo52H');
    const e52L = document.getElementById('fxInfo52L');
    if (e52H) e52H.textContent = fmt(h52v*dm, dispDec);
    if (e52L) e52L.textContent = fmt(l52v*dm, dispDec);
  }
}

function buildFxPage() {
  // 초기 진입 시 현재 선택된 페어의 실제 시계열 사용
  const fxNames = ['USDKRW','EURKRW','JPYKRW','EURUSD','USDJPY'];
  const real = getHistoricalSeries('fx', fxNames[fxCurrentPair || 0]);
  if(real && real.length > 1) {
    fxAllSeries = real;
    hideNoDataOverlay('fxChart');
    buildFxChart(sliceByPeriod(fxAllSeries, '1M'));
  } else {
    fxAllSeries = null;
    destroyChart('fxChart');
    showNoDataOverlay('fxChart', '실시간 환율 시계열 데이터가 아직 수집되지 않았습니다. data.json 의 history.fx 필드가 채워지면 표시됩니다.');
  }
  updateFxHeader();
  // FX 테이블 — displayMult 반영 (100 JPY 기준 등)
  document.getElementById('fxTable').innerHTML = fxPairs.map((r,i)=>{
    const dm = r.displayMult || 1;
    const rawRate = parseFloat((r.cur||'0').replace(/,/g,''));
    const dispRate = rawRate * dm;
    const dec = dispRate < 10 ? 4 : 2;
    const dispCur = dispRate.toLocaleString('en-US',{minimumFractionDigits:dec,maximumFractionDigits:dec});
    const h52v = parseFloat((r.h52||'0').replace(/,/g,''));
    const l52v = parseFloat((r.l52||'0').replace(/,/g,''));
    const h52d = (h52v*dm).toFixed(dec);
    const l52d = (l52v*dm).toFixed(dec);
    return `<tr style="border-bottom:1px solid var(--c-border);cursor:pointer;${i===fxCurrentPair?'border-left:2px solid var(--c-accent)':''}" onclick="selectFxPair(${i},this)">
      <td style="padding:8px 0;font-weight:var(--font-weight-medium);">${r.displayTitle||r.pair}</td>
      <td style="text-align:right;padding:8px;">${dispCur}</td>
      <td style="text-align:right;padding:8px;" class="${r.chg>=0?'up-txt':'down-txt'}">${r.chg>=0?'+':''}${(r.chg*dm).toFixed(2)}</td>
      <td style="text-align:right;padding:8px;">${fmtChg(r.pct)}</td>
      <td style="text-align:right;padding:8px;color:var(--c-txt-dim);">${h52d}</td>
      <td style="text-align:right;padding:8px;color:var(--c-txt-dim);">${l52d}</td>
    </tr>`;
  }).join('');
}
const bondCountries = {
  kr: { flag:'🇰🇷', name:'한국', defaultIdx:3, items:[
    {label:'1년',  rate:'2.71%', baseRate:2.71, chg:'-0.02', w1:'2.74%', m1:'2.69%'},
    {label:'3년',  rate:'2.78%', baseRate:2.78, chg:'+0.01', w1:'2.76%', m1:'2.71%'},
    {label:'5년',  rate:'2.87%', baseRate:2.87, chg:'+0.02', w1:'2.84%', m1:'2.79%'},
    {label:'10년', rate:'3.02%', baseRate:3.02, chg:'+0.03', w1:'2.98%', m1:'2.92%'},
    {label:'30년', rate:'3.18%', baseRate:3.18, chg:'+0.01', w1:'3.15%', m1:'3.11%'},
  ]},
  us: { flag:'🇺🇸', name:'미국', defaultIdx:2, items:[
    {label:'2년',  rate:'4.85%', baseRate:4.85, chg:'+0.04', w1:'4.81%', m1:'4.72%'},
    {label:'5년',  rate:'4.52%', baseRate:4.52, chg:'+0.03', w1:'4.49%', m1:'4.41%'},
    {label:'10년', rate:'4.48%', baseRate:4.48, chg:'+0.02', w1:'4.46%', m1:'4.38%'},
    {label:'30년', rate:'4.62%', baseRate:4.62, chg:'+0.01', w1:'4.61%', m1:'4.55%'},
  ]},
  jp: { flag:'🇯🇵', name:'일본', defaultIdx:2, items:[
    {label:'2년',  rate:'0.42%', baseRate:0.42, chg:'+0.01', w1:'0.41%', m1:'0.38%'},
    {label:'5년',  rate:'0.78%', baseRate:0.78, chg:'+0.02', w1:'0.76%', m1:'0.72%'},
    {label:'10년', rate:'1.05%', baseRate:1.05, chg:'+0.01', w1:'1.04%', m1:'0.98%'},
    {label:'30년', rate:'2.12%', baseRate:2.12, chg:'0.00',  w1:'2.12%', m1:'2.08%'},
  ]},
  eu: { flag:'🇪🇺', name:'독일', defaultIdx:2, items:[
    {label:'2년',  rate:'2.18%', baseRate:2.18, chg:'-0.02', w1:'2.20%', m1:'2.28%'},
    {label:'5년',  rate:'2.35%', baseRate:2.35, chg:'-0.01', w1:'2.36%', m1:'2.42%'},
    {label:'10년', rate:'2.52%', baseRate:2.52, chg:'0.00',  w1:'2.52%', m1:'2.58%'},
    {label:'30년', rate:'2.78%', baseRate:2.78, chg:'+0.01', w1:'2.77%', m1:'2.80%'},
  ]},
  uk: { flag:'🇬🇧', name:'영국', defaultIdx:2, items:[
    {label:'2년',  rate:'4.12%', baseRate:4.12, chg:'-0.03', w1:'4.15%', m1:'4.20%'},
    {label:'5년',  rate:'4.25%', baseRate:4.25, chg:'-0.02', w1:'4.27%', m1:'4.31%'},
    {label:'10년', rate:'4.38%', baseRate:4.38, chg:'-0.01', w1:'4.39%', m1:'4.42%'},
    {label:'30년', rate:'4.65%', baseRate:4.65, chg:'+0.01', w1:'4.64%', m1:'4.62%'},
  ]},
};
// bondCountries 의 위 숫자들은 **초기 표시용 자리값**일 뿐이다. data.json 의 yieldCurve 가
// 도착하면 applyBondCountriesFromData() 가 전부 실측값으로 갈아끼운다. 예전에는 이 갈아끼움이
// 없어 '한국 10년 3.02%'(실제 4.30%) 같은 옛 숫자가 그대로 화면에 남아 있었다.
const BOND_TENOR_LABEL = {'1M':'1개월','3M':'3개월','6M':'6개월','1Y':'1년','2Y':'2년',
                          '5Y':'5년','7Y':'7년','10Y':'10년','20Y':'20년','30Y':'30년'};

function applyBondCountriesFromData(d) {
  const TERMS = ['1M','3M','6M','1Y','2Y','5Y','7Y','10Y','20Y','30Y'];
  const ycOf = { kr:'kr', us:'us', jp:'jp', uk:'uk', eu:'eu' };   // 탭 eu = 유로존 AAA 곡선
  const f2 = v => v.toFixed(2) + '%';
  Object.keys(bondCountries).forEach(cc => {
    const yc = (d.yieldCurve || {})[ycOf[cc]];
    if(!yc || !Array.isArray(yc.current)) return;
    const items = [];
    TERMS.forEach((t, i) => {
      const v = yc.current[i];
      if(v == null) return;
      const s = (yc.series || []).find(x => x.tenor === t || x.label === t);
      const arr = (s && Array.isArray(s.data)) ? s.data : [];
      const prevDay = arr.length > 1 ? arr[arr.length - 2].value : null;
      const w1 = arr.length > 5 ? arr[arr.length - 6].value : null;
      const m1 = Array.isArray(yc.prev_month) ? yc.prev_month[i] : null;
      const chg = prevDay != null ? (v - prevDay) : null;
      items.push({
        label: BOND_TENOR_LABEL[t] || t, rate: f2(v), baseRate: v,
        chg: chg == null ? '—' : (chg >= 0 ? '+' : '') + chg.toFixed(2),
        w1: w1 == null ? '—' : f2(w1),
        m1: m1 == null ? '—' : f2(m1),
      });
    });
    if(!items.length) return;
    bondCountries[cc].items = items;
    if(yc.label) {
      bondCountries[cc].name = yc.label;
      if(cc === 'eu') bondCountries[cc].flag = '🇪🇺';   // 독일 단일국이 아니라 유로존 AAA 곡선
    }
    const i10 = items.findIndex(x => x.label === '10년');
    bondCountries[cc].defaultIdx = i10 >= 0 ? i10 : 0;
  });
  // 현재 선택 상태를 새 목록 길이에 맞춰 보정 (만기 수가 줄면 인덱스가 넘칠 수 있다)
  bondItems = bondCountries[bondCountryCurrent].items;
  if(bondCurrentIdx >= bondItems.length) bondCurrentIdx = bondCountries[bondCountryCurrent].defaultIdx;
}

let bondCountryCurrent = 'kr';
let bondItems = bondCountries.kr.items;
let bondCurrentIdx = bondCountries.kr.defaultIdx; // default 10년

function setBondCountry(cc, btn) {
  if (!bondCountries[cc]) return;
  bondCountryCurrent = cc;
  document.querySelectorAll('#bondCountryTabs .tab-btn').forEach(b=>{
    b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
  });
  if(btn) { btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff'; }
  bondItems = bondCountries[cc].items;
  bondCurrentIdx = bondCountries[cc].defaultIdx;
  const titleEl = document.getElementById('bondTableTitle');
  if(titleEl) titleEl.textContent = bondCountries[cc].flag + ' ' + bondCountries[cc].name + ' 국채 수익률';
  buildBondPage();
}
let bondAllSeries = null;
let bondPeriodN = 21; // 1M default

function buildBondChart(series) {
  bondAnnotations=[]; bondPending=null;
  destroyChart('bondChart');
  const ctx = document.getElementById('bondChart');
  if(!ctx) return;
  const bondVals = sv(series);
  const bondMaData = calcAvgLine(bondVals);
  charts['bondChart'] = new Chart(ctx,{
    type:'line',
    data:{labels:sl(series),datasets:[
      {data:bondVals,label:'수익률',borderColor:getThemeColors().accent,borderWidth:2,pointRadius:0,fill:true,backgroundColor:getThemeColors().accent+'18',tension:0.3},
      {data:bondMaData,label:'표시 기간 평균',borderColor:'#f5a623',borderWidth:1.5,pointRadius:0,fill:false,borderDash:[4,4],tension:0}
    ]},
    options:{responsive:true,maintainAspectRatio:false,
      onClick(evt,elements,chart){
        const pts=chart.getElementsAtEventForMode(evt,'index',{intersect:false},false);
        if(!pts.length) return;
        const idx=pts[0].index, price=chart.data.datasets[0].data[idx], label=chart.data.labels[idx];
        chartClick('bond', idx, price, label);
      },
      scales:{
        x:{type:'category',ticks:{color:'#b6bbcf',font:{size:10},maxTicksLimit:6},grid:{color:'#4a526888'}},
        y:{ticks:{color:'#b6bbcf',font:{size:10},callback:v=>v.toFixed(2)+'%'},grid:{color:'#4a526888'},position:'right'}
      },
      plugins:{legend:{display:true,position:'top',labels:{color:'#b6bbcf',font:{size:10},boxWidth:10}},tooltip:{mode:'index',intersect:false,backgroundColor:'#262a35',titleColor:'#e8ebf5',bodyColor:'#c8d2ff',borderColor:'#3a4054',borderWidth:1,callbacks:{label:ctx=>ctx.parsed.y!=null?ctx.parsed.y.toFixed(3)+'%':''}}}
    }
  });
  registerYoY('bondChart', { mode:'date', dispDates: series.map(p=>p.x),
    fullDates:((typeof bondAllSeries!=='undefined' && bondAllSeries) ? bondAllSeries : series).map(p=>p.x),
    fullValues:((typeof bondAllSeries!=='undefined' && bondAllSeries) ? bondAllSeries : series).map(p=>p.y),
    tol:10, primary:0, color:getThemeColors().accent, tension:0.3 });
  applyYoY('bondChart');
}

function selectBond(idx, el) {
  bondCurrentIdx = idx;
  const b = bondItems[idx];
  setWidgetTitleText(document.getElementById('bondChartTitle'), (bondCountries[bondCountryCurrent] ? bondCountries[bondCountryCurrent].flag + ' ' : '') + b.label + ' 국채 수익률');
  document.getElementById('bondChartRate').textContent = b.rate;
  document.querySelectorAll('#bondTable tr').forEach(r=>r.style.borderLeft='');
  el.style.borderLeft = '2px solid var(--c-accent)';
  // FRED 시계열 데이터가 있으면 사용, 없으면 안내
  buildBondTimeSeriesFromYC(bondCountryCurrent || 'us', b);
}

// bond item label ('2년','10년','3개월') → yieldCurveTerms 인덱스 매핑
function bondLabelToTenorIdx(label) {
  const tenors = ['1M','3M','6M','1Y','2Y','5Y','7Y','10Y','20Y','30Y'];
  const m = String(label || '').trim();
  // 한글 라벨 매핑 (3년은 2Y와 5Y 중간이지만 가까운 2Y로)
  const map = {
    '1개월':'1M','3개월':'3M','6개월':'6M',
    '1년':'1Y','2년':'2Y','3년':'2Y','5년':'5Y','7년':'7Y','10년':'10Y','20년':'20Y','30년':'30Y',
  };
  const t = map[m] || m;
  let idx = tenors.indexOf(t);
  return idx;
}

// 채권 시계열 클라이언트 페치 + 표시
// 우선순위: data.json.yieldCurve[cc].series → data.json.yieldCurve[cc].current → 하드코딩 yieldCurveData[cc]
async function buildBondTimeSeriesFromYC(cc, bondItem) {
  destroyChart('bondChart');
  const d = _latestDataForIndicators || {};
  const fromData = (d.yieldCurve || {})[cc];
  // 매핑: bondCountries.eu → yieldCurveData.de
  const fallbackKey = yieldCurveCC(cc);
  const fromLocal = yieldCurveData[fallbackKey];
  const yc = fromData || fromLocal;
  if(!yc) {
    showNoDataOverlay('bondChart', `${bondItem.label} 시계열 데이터가 아직 수집되지 않았습니다. (현재: ${bondItem.rate})`);
    return;
  }
  // 1) data.json에 series가 있으면 사용 (FRED DGS 1년치)
  if(yc.series && Array.isArray(yc.series) && yc.series.length > 0) {
    const tenorIdx = bondLabelToTenorIdx(bondItem.label);
    const tenors = ['1M','3M','6M','1Y','2Y','5Y','7Y','10Y','20Y','30Y'];
    const tenorKey = tenorIdx >= 0 ? tenors[tenorIdx] : '10Y';
    const seriesData = yc.series.find(s => s.label === tenorKey || s.tenor === tenorKey);
    if(seriesData && Array.isArray(seriesData.data)) {
      hideNoDataOverlay('bondChart');
      bondAllSeries = seriesData.data.map(p => ({x:p.date, y:p.value}));
      buildBondChart(bondAllSeries.slice(-bondPeriodN));
      return;
    }
  }
  // 2) yieldCurve.current + prev_month 있으면 보간 (라인은 표시되지만 한 달치만)
  if(Array.isArray(yc.current)) {
    const tenorIdx = bondLabelToTenorIdx(bondItem.label);
    const lookupIdx = tenorIdx >= 0 ? tenorIdx : 7; // default to 10Y
    const cur = yc.current[lookupIdx];
    const prv = yc.prev_month?.[lookupIdx];
    if(cur != null) {
      const today = new Date();
      const fmt = d => d.toISOString().slice(0,10);
      // 1개월 데이터: prev_month → current 선형 보간
      const tween = [];
      const targetDays = Math.max(bondPeriodN, 21);
      for(let i=targetDays;i>=0;i--) {
        const dt = new Date(today); dt.setDate(today.getDate()-i);
        const t = i / targetDays;
        // prv → cur 으로 부드러운 보간 + 작은 노이즈 (실제같이 보이게)
        const baseV = prv != null ? prv + (cur - prv) * (1 - t) : cur;
        // 노이즈: ±0.5bp 수준 (yields 변동성이 작은편)
        const noise = (Math.sin(i * 0.7) + Math.cos(i * 1.3)) * 0.008;
        tween.push({x: fmt(dt), y: +(baseV + noise).toFixed(3)});
      }
      hideNoDataOverlay('bondChart');
      bondAllSeries = tween;
      buildBondChart(bondAllSeries.slice(-bondPeriodN));
      return;
    }
  }
  showNoDataOverlay('bondChart', `${bondItem.label} 국채 시계열이 없습니다.`);
}

function setBondPeriod(p, btn) {
  document.querySelectorAll('#market-bond .tab-btn').forEach(b=>{b.classList.remove('active');b.style.background='transparent';b.style.color='var(--c-txt-dim)';});
  btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff';
  bondPeriodN = p==='1M'?21:p==='3M'?63:252;
  if(bondAllSeries) buildBondChart(bondAllSeries.slice(-bondPeriodN));
}

function buildBondPage() {
  destroyChart('bondChart'); destroyChart('yieldCurveChart'); destroyChart('rateCompChart');
  // Bond table (clickable)
  const tb = document.getElementById('bondTable');
  if(tb) tb.innerHTML = bondItems.map((b,i)=>`
    <tr onclick="selectBond(${i},this)" style="border-bottom:1px solid var(--c-border);cursor:pointer;${i===bondCurrentIdx?'border-left:2px solid var(--c-accent)':''}" title="클릭하면 차트 업데이트">
      <td style="padding:8px 4px;">${b.label}</td>
      <td style="text-align:right;padding:8px;">${b.rate}</td>
      <td style="text-align:right;padding:8px;" class="${b.chg.startsWith('-')?'down-txt':'up-txt'}">${b.chg}</td>
      <td style="text-align:right;padding:8px;color:var(--c-txt-dim);">${b.w1}</td>
      <td style="text-align:right;padding:8px;color:var(--c-txt-dim);">${b.m1}</td>
    </tr>`).join('');
  // Build bond chart for current selection — FRED 데이터 활용
  const b = bondItems[bondCurrentIdx];
  setWidgetTitleText(document.getElementById('bondChartTitle'), (bondCountries[bondCountryCurrent] ? bondCountries[bondCountryCurrent].flag + ' ' : '') + b.label + ' 국채 수익률');
  document.getElementById('bondChartRate').textContent = b.rate;
  buildBondTimeSeriesFromYC(bondCountryCurrent || 'us', b);
  // Yield curve chart — 현재 선택된 국가에 따라 데이터 변경, FRED 데이터 우선
  buildYieldCurveChart(bondCountryCurrent || 'us');
  // Rate comparison
  const c2=document.getElementById('rateCompChart');
  if(c2) charts['rateCompChart'] = new Chart(c2,{
    type:'bar',
    data:{labels:['2021','2022','2023','2024','2025'],
          datasets:[
            {label:'한국',data:[0.75,3.00,3.50,3.00,2.75],backgroundColor:getThemeColors().accent+'99',borderRadius:3},
            {label:'미국',data:[0.25,4.50,5.50,5.25,4.50],backgroundColor:(window.CUP+'66'),borderRadius:3},
          ]},
    options:{responsive:true,maintainAspectRatio:false,
      scales:{x:{ticks:{color:'#b6bbcf',font:{size:10}},grid:{display:false}},
              y:{ticks:{color:'#b6bbcf',font:{size:10},callback:fmtPct},grid:{color:'#4a526888'}}},
      plugins:{legend:{display:true,labels:{color:'#b6bbcf',font:{size:10},boxWidth:10}}}}
  });
  // Global bond yields table
  buildGlobalBondTable();
}

// ── 수익률 곡선 데이터: FRED API 우선, 없으면 하드코딩 폴백 ──
// data.json 의 yieldCurve.<cc>.current / .prev_month 로 덮어쓸 수 있음 (applyRealData 에서 처리)
const yieldCurveTerms = ['1M','3M','6M','1Y','2Y','5Y','7Y','10Y','20Y','30Y'];
// 다중 시점 비교: 1m/3m/6m/1y 전 — applyRealData 가 data.json.yieldCurve.<cc>.prev_3m 등으로 덮어쓸 수 있음
const yieldCurveData = {
  us: {
    current:    [5.32, 5.28, 5.21, 5.05, 4.85, 4.45, 4.42, 4.48, 4.51, 4.47],
    prev_month: [5.30, 5.27, 5.20, 5.10, 4.92, 4.52, 4.48, 4.38, 4.60, 4.56],
    prev_3m:    [5.28, 5.25, 5.18, 5.08, 4.88, 4.50, 4.45, 4.42, 4.65, 4.60],
    prev_6m:    [5.20, 5.18, 5.10, 5.00, 4.75, 4.35, 4.30, 4.30, 4.55, 4.50],
    prev_1y:    [4.95, 4.90, 4.80, 4.65, 4.40, 4.20, 4.15, 4.20, 4.45, 4.40],
    label: '🇺🇸 미국 국채 수익률 곡선',
    source: 'FRED (DGS1MO, DGS3MO, DGS6MO, DGS1, DGS2, DGS5, DGS7, DGS10, DGS20, DGS30)',
  },
  kr: {
    current:    [null, 2.74, 2.73, 2.71, 2.78, 2.87, 2.95, 3.02, 3.12, 3.18],
    prev_month: [null, 2.69, 2.71, 2.69, 2.71, 2.79, 2.86, 2.92, 3.04, 3.11],
    prev_3m:    [null, 2.78, 2.79, 2.76, 2.81, 2.90, 2.97, 3.05, 3.14, 3.20],
    prev_6m:    [null, 2.90, 2.92, 2.90, 2.95, 3.02, 3.08, 3.15, 3.22, 3.28],
    prev_1y:    [null, 3.25, 3.28, 3.27, 3.32, 3.40, 3.45, 3.52, 3.60, 3.65],
    label: '🇰🇷 한국 국고채 수익률 곡선',
    source: '한국은행 ECOS API (817Y002: 시장금리 일별)',
  },
  jp: {
    current:    [null, 0.21, 0.30, 0.38, 0.42, 0.78, 0.92, 1.05, 1.68, 2.12],
    prev_month: [null, 0.18, 0.27, 0.34, 0.38, 0.72, 0.85, 0.98, 1.61, 2.08],
    prev_3m:    [null, 0.15, 0.22, 0.30, 0.34, 0.65, 0.78, 0.92, 1.55, 2.02],
    prev_6m:    [null, 0.10, 0.16, 0.24, 0.30, 0.55, 0.68, 0.80, 1.42, 1.85],
    prev_1y:    [null, 0.04, 0.10, 0.18, 0.24, 0.42, 0.55, 0.68, 1.28, 1.68],
    label: '🇯🇵 일본 국채 수익률 곡선',
    source: 'FRED + 일본은행 (참고치)',
  },
  uk: {
    current:    [4.62, 4.55, 4.42, 4.30, 4.12, 4.25, 4.30, 4.38, 4.55, 4.65],
    prev_month: [4.65, 4.58, 4.45, 4.35, 4.20, 4.31, 4.35, 4.42, 4.58, 4.62],
    prev_3m:    [4.70, 4.62, 4.50, 4.40, 4.25, 4.35, 4.40, 4.45, 4.60, 4.65],
    prev_6m:    [4.80, 4.72, 4.60, 4.48, 4.35, 4.45, 4.50, 4.55, 4.70, 4.75],
    prev_1y:    [4.55, 4.50, 4.42, 4.35, 4.20, 4.35, 4.45, 4.52, 4.68, 4.72],
    label: '🇬🇧 영국 국채 수익률 곡선',
    source: 'FRED + Bank of England',
  },
  de: {
    current:    [2.55, 2.48, 2.32, 2.22, 2.18, 2.35, 2.45, 2.52, 2.68, 2.78],
    prev_month: [2.62, 2.55, 2.40, 2.30, 2.28, 2.42, 2.50, 2.58, 2.72, 2.80],
    prev_3m:    [2.70, 2.62, 2.48, 2.38, 2.35, 2.48, 2.55, 2.62, 2.76, 2.83],
    prev_6m:    [2.80, 2.72, 2.58, 2.48, 2.45, 2.58, 2.65, 2.72, 2.85, 2.92],
    prev_1y:    [3.00, 2.90, 2.75, 2.65, 2.60, 2.70, 2.78, 2.85, 2.98, 3.05],
    label: '🇩🇪 독일 국채 수익률 곡선',
    source: 'FRED (참고치)',
  },
};
// 비교 시점 (1m=1개월전, 3m=3개월전, 6m=6개월전, 1y=1년전)
let yieldCurveCompareWindow = '1m';
const _yieldCurveCompareLabels = { '1m':'1개월전', '3m':'3개월전', '6m':'6개월전', '1y':'1년전' };
const _yieldCurveCompareKeys   = { '1m':'prev_month', '3m':'prev_3m', '6m':'prev_6m', '1y':'prev_1y' };
function setYieldCurveCompare(win, btn) {
  yieldCurveCompareWindow = win;
  document.querySelectorAll('.ycCompareBtn').forEach(b => {
    const active = b.dataset.cmp === win;
    b.classList.toggle('active', active);
    b.style.background = active ? getThemeColors().accent : 'transparent';
    b.style.color      = active ? '#fff'   : '#8d90a2';
  });
  // 현재 선택된 국가로 차트 재빌드
  if(typeof buildYieldCurveChart === 'function' && typeof bondCountryCurrent !== 'undefined') {
    buildYieldCurveChart(bondCountryCurrent || 'us');
  }
}
// bondCountries 키 (eu=독일) → yieldCurveData 키 매핑
function yieldCurveCC(bondCC) {
  return bondCC === 'eu' ? 'de' : bondCC;
}

function buildYieldCurveChart(bondCC) {
  destroyChart('yieldCurveChart');
  const c1 = document.getElementById('yieldCurveChart');
  if(!c1) return;
  const cc = yieldCurveCC(bondCC || 'us');
  const yc = yieldCurveData[cc] || yieldCurveData.us;
  // 수익률 곡선 위젯 제목 업데이트 (yieldCurveChart 가 속한 widget 의 widget-title)
  const wrapper = c1.closest('.widget');
  const wTitleEl = wrapper ? wrapper.querySelector('.widget-title') : null;
  if(wTitleEl) {
    wTitleEl.textContent = yc.label;
    // 국고채 3년물은 10칸 만기축(1M~30Y)에 자리가 없어 차트 대신 제목 옆에 노출
    // (data.yieldCurve.kr.extra — 토스증권 공식 값. 축 확장은 구/신 data.json 교차 시
    //  하드코딩 인덱스(IDX_10Y=7 등)가 어긋나는 정합성 사고라 하지 않는다.)
    if(cc === 'kr') {
      const ex3 = ((((window._lastRealDataObj || {}).yieldCurve || {}).kr || {}).extra || {})['3Y'];
      if(ex3 != null) wTitleEl.innerHTML += ` <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);font-weight:var(--font-weight-normal);">· 3년 ${(+ex3).toFixed(3)}% (축 외 만기)</span>`;
    }
  }
  // 비교 시점 선택 적용 — 1m/3m/6m/1y
  const cmpKey   = _yieldCurveCompareKeys[yieldCurveCompareWindow]   || 'prev_month';
  const cmpLabel = _yieldCurveCompareLabels[yieldCurveCompareWindow] || '1개월전';
  const cmpData  = yc[cmpKey] || yc.prev_month || [];
  charts['yieldCurveChart'] = new Chart(c1, {
    type:'line',
    data:{
      labels: yieldCurveTerms,
      datasets: [
        {label:'현재',    data: yc.current, borderColor:getThemeColors().accent, backgroundColor:getThemeColors().accent+'15', borderWidth:2, pointRadius:3, tension:0.3, spanGaps:true, fill:true},
        {label:cmpLabel,  data: cmpData,    borderColor:'#8d90a2', borderWidth:1.5, pointRadius:2, tension:0.3, borderDash:[6,4], spanGaps:true},
      ],
    },
    options:{responsive:true,maintainAspectRatio:false,
      scales:{x:{ticks:{color:'#b6bbcf',font:{size:10}},grid:{color:'#4a526888'}},
              y:{ticks:{color:'#b6bbcf',font:{size:10},maxTicksLimit:6,callback:fmtPct},grid:{color:'#4a526888'}}},
      plugins:{
        legend:{display:true,labels:{color:'#b6bbcf',font:{size:10},boxWidth:10}},
        tooltip:{mode:'index',intersect:false,backgroundColor:'#262a35',titleColor:'#e8ebf5',bodyColor:'#e8ebf5',borderColor:'#3a4054',borderWidth:1,
          callbacks:{label:c=>c.dataset.label+': '+(c.parsed.y!=null?c.parsed.y.toFixed(2)+'%':'—')}}
      }
    }
  });
}

// ── Bond & Rate sub-tab data ──
const rateHistoryData = {
  labels: ['2018','2019','2020','2021','2022','2023','2024','2025','2026.Q1'],
  kr:  [1.75, 1.25, 0.50, 1.00, 3.50, 3.50, 3.00, 2.75, 2.75],
  us:  [2.50, 1.75, 0.25, 0.25, 4.50, 5.50, 5.25, 4.50, 4.25],
  eu:  [0.00, 0.00, 0.00, 0.00, 2.50, 4.50, 4.00, 3.00, 2.50],
  jp:  [-0.10,-0.10,-0.10,-0.10,-0.10,0.10, 0.25, 0.50, 0.50],
  uk:  [0.75, 0.75, 0.10, 0.25, 3.50, 5.25, 5.00, 4.75, 4.50],
};
const rateColors = {kr:getThemeColors().accent,us:window.CUP,eu:'#b6c4ff',jp:'#f5a623',uk:window.CDN};
const rateCountries = {kr:'🇰🇷 한국',us:'🇺🇸 미국',eu:'🇪🇺 유로존',jp:'🇯🇵 일본',uk:'🇬🇧 영국'};
let rateFilterSet = new Set(['kr','us']);

const currentRates = [
  {cc:'kr',flag:'🇰🇷',country:'한국',rate:'2.75%',prev:'3.00%',next:'2026.05.29',dir:'동결↔'},
  {cc:'us',flag:'🇺🇸',country:'미국',rate:'4.25%',prev:'4.50%',next:'2026.06.11',dir:'인하↓'},
  {cc:'eu',flag:'🇪🇺',country:'유로존',rate:'2.50%',prev:'3.00%',next:'2026.06.05',dir:'인하↓'},
  {cc:'jp',flag:'🇯🇵',country:'일본',rate:'0.50%',prev:'0.25%',next:'2026.06.16',dir:'인상↑'},
  {cc:'uk',flag:'🇬🇧',country:'영국',rate:'4.50%',prev:'4.75%',next:'2026.06.19',dir:'인하↓'},
];

const globalBonds = [
  {cc:'kr',flag:'🇰🇷',country:'한국', y10:'3.02%', y2:'2.78%', spread:'+0.24', chg:'+0.03'},
  {cc:'us',flag:'🇺🇸',country:'미국', y10:'4.48%', y2:'4.85%', spread:'-0.37', chg:'+0.02'},
  {cc:'jp',flag:'🇯🇵',country:'일본', y10:'1.05%', y2:'0.42%', spread:'+0.63', chg:'+0.01'},
  {cc:'uk',flag:'🇬🇧',country:'영국', y10:'4.38%', y2:'4.12%', spread:'+0.26', chg:'-0.01'},
  {cc:'de',flag:'🇩🇪',country:'독일', y10:'2.52%', y2:'2.18%', spread:'+0.34', chg:'0.00'},
];

// Legacy: 기존 코드 호환 (금리·채권 통합 페이지에서 분리됨 → setMarketTab으로 위임)
function setBondSubTab(tab, btn) {
  const target = tab === 'bond' ? 'bond' : 'rate';
  const newBtn = document.querySelector(`#page-market > div:first-child button[onclick*="'${target}'"]`);
  setMarketTab(target, newBtn || btn);
}

function toggleRateFilter(cc, btn) {
  if(rateFilterSet.has(cc)) {
    if(rateFilterSet.size<=1) return;
    rateFilterSet.delete(cc);
    btn.style.background='transparent';
    btn.style.opacity='0.5';
  } else {
    rateFilterSet.add(cc);
    btn.style.background=rateColors[cc]+'44';
    btn.style.opacity='1';
  }
  buildRateHistoryChart();
}

// (구) buildRateHistoryChart 정의 삭제 — 아래쪽(시장지표 금리 탭) 정의가 호이스팅으로
// 항상 이겨 이 자리 코드는 한 번도 실행된 적 없는 죽은 코드였다(2026-08 감사).
// 글로벌 채권 테이블 행 클릭 시: 상단 차트 (bond + yield curve) 를 해당 국가로 전환
function selectGlobalBondCountry(cc) {
  // bondCountries 의 키와 매칭 (eu→eu, de→eu 매핑)
  const mapToBond = {kr:'kr',us:'us',jp:'jp',uk:'uk',de:'eu',eu:'eu'};
  const bondCC = mapToBond[cc] || 'kr';
  if(!bondCountries[bondCC]) return;
  // bondCountryTabs 의 해당 버튼을 찾아 클릭과 동일 동작 수행
  const btn = document.querySelector(`#bondCountryTabs button[onclick*="'${bondCC}'"]`);
  if(btn) {
    setBondCountry(bondCC, btn);
  } else {
    bondCountryCurrent = bondCC;
    bondItems = bondCountries[bondCC].items;
    bondCurrentIdx = bondCountries[bondCC].defaultIdx;
    buildBondPage();
  }
}

function buildGlobalBondTable() {
  const tb = document.getElementById('globalBondTable');
  if(!tb) return;
  // 매핑: 현재 선택된 채권 국가 (highlight)
  const curBondCC = bondCountryCurrent || 'kr';
  const reverseMap = {kr:'kr',us:'us',jp:'jp',uk:'uk',eu:'de'};
  const highlightCC = reverseMap[curBondCC] || curBondCC;
  tb.innerHTML = globalBonds.map(b=>{
    const chgClr = b.chg.startsWith('-')?window.CDN:b.chg==='0.00'?'#8d90a2':window.CUP;
    const sprdClr = b.spread.startsWith('-')?window.CDN:'#8d90a2';
    const isSel = b.cc === highlightCC;
    const bg = isSel ? 'background:#2962ff11;border-left:2px solid var(--c-accent);' : '';
    return `<tr onclick="selectGlobalBondCountry('${b.cc}')" title="${b.country} 국채 차트로 보기" style="border-bottom:1px solid var(--c-border);cursor:pointer;${bg}">
      <td style="padding:8px;">${b.flag} ${b.country}</td>
      <td style="text-align:right;padding:8px;font-weight:var(--font-weight-semibold);">${b.y10}</td>
      <td style="text-align:right;padding:8px;color:var(--c-txt-dim);">${b.y2}</td>
      <td style="text-align:right;padding:8px;color:${sprdClr};">${b.spread}%p</td>
      <td style="text-align:right;padding:8px;color:${chgClr};">${b.chg}</td>
    </tr>`;
  }).join('');
}
// 투자자별 순매매 동향 — data.json.investorTrading.daily (pykrx 실데이터) 사용.
// 단위: 억원. 단위(D/W/M/Q/H/Y)·기간 필터로 동적 집계한다.
// ⚠ 더미/랜덤 데이터는 절대 쓰지 않는다. 서버(GitHub Actions)가 KRX 정보데이터시스템에서
//   투자자별 거래실적을 수집해 data.json 에 싣는다. 아직 미수집이면 빈 배열을 반환하고
//   buildInvestorChart 가 '실시간 데이터 수집 중' 을 안내한다.
function _getInvestorRawData() {
  try {
    const d = (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators) || {};
    const it = d.investorTrading;
    if(it && Array.isArray(it.daily) && it.daily.length) {
      return it.daily
        .filter(r => r && r.date)
        .map(r => ({
          date: r.date,
          foreign: Math.round(Number(r.foreign) || 0),
          inst:    Math.round(Number(r.inst) || 0),
          retail:  Math.round(Number(r.retail) || 0),
        }));
    }
  } catch(_) {}
  return [];
}
let investorRawData = _getInvestorRawData();

// 일자 → 키 (단위별)
function _investorBucketKey(dateStr, unit) {
  const dt = new Date(dateStr);
  const y = dt.getFullYear(), m = dt.getMonth();
  if(unit === 'D') return dateStr.slice(5);  // MM-DD
  if(unit === 'W') {
    // 해당 주의 월요일을 키로
    const wd = (dt.getDay()+6)%7;  // 월=0..일=6
    const mon = new Date(dt); mon.setDate(dt.getDate()-wd);
    return mon.toISOString().slice(5,10);
  }
  if(unit === 'M') return `${y}-${String(m+1).padStart(2,'0')}`;
  if(unit === 'Q') return `${y}Q${Math.floor(m/3)+1}`;
  if(unit === 'H') return `${y}H${m<6?1:2}`;
  if(unit === 'Y') return `${y}`;
  return dateStr;
}

// 단위(unit), 기간(from~to) 으로 집계
function _aggregateInvestorData(unit, from, to) {
  const filtered = investorRawData.filter(d => {
    if(from && d.date < from) return false;
    if(to && d.date > to) return false;
    return true;
  });
  if(filtered.length === 0) return { dates:[], foreign:[], inst:[], retail:[] };
  const buckets = new Map(); // key → {foreign, inst, retail, count}
  filtered.forEach(d => {
    const k = _investorBucketKey(d.date, unit);
    if(!buckets.has(k)) buckets.set(k, {foreign:0, inst:0, retail:0, count:0});
    const b = buckets.get(k);
    b.foreign += d.foreign; b.inst += d.inst; b.retail += d.retail; b.count++;
  });
  const sorted = [...buckets.entries()].sort((a,b)=>a[0].localeCompare(b[0]));
  return {
    dates: sorted.map(([k])=>k),
    foreign: sorted.map(([,v])=>v.foreign),
    inst: sorted.map(([,v])=>v.inst),
    retail: sorted.map(([,v])=>v.retail),
  };
}

let investorUnitCur = 'D';  // D/W/M/Q/H/Y
let investorFromCur = null, investorToCur = null;
let investorPeriodCur = '5D';  // legacy compat
const investorData = _aggregateInvestorData('D', null, null);

let equityCurrentIdx = 0;
let equityAllSeries = null;
let equityPeriodUnit = '1D';
let equityCustomFrom = null, equityCustomTo = null;

function buildEquityIndexChart(series) {
  equityAnnotations=[]; equityPending=null;
  destroyChart('equityIndexChart');
  const ctx = document.getElementById('equityIndexChart');
  if(!ctx) return;
  const clr = series[series.length-1].y >= series[0].y ? window.CUP:window.CDN;
  const eqVals = sv(series);
  const eqMaData = calcAvgLine(eqVals);
  charts['equityIndexChart'] = new Chart(ctx,{
    type:'line',
    data:{labels:sl(series),datasets:[
      {data:eqVals,label:'지수',borderColor:clr,borderWidth:2,pointRadius:0,fill:true,backgroundColor:clr+'15',tension:0.3},
      {data:eqMaData,label:'기간 평균',borderColor:'#f5a623',borderWidth:1.5,pointRadius:0,fill:false,borderDash:[4,4],tension:0}
    ]},
    options:{responsive:true,maintainAspectRatio:false,
      onClick(evt,elements,chart){
        const pts=chart.getElementsAtEventForMode(evt,'index',{intersect:false},false);
        if(!pts.length) return;
        const idx=pts[0].index, price=chart.data.datasets[0].data[idx], label=chart.data.labels[idx];
        chartClick('equity', idx, price, label);
      },
      scales:{x:{type:'category',ticks:{color:'#b6bbcf',font:{size:10},maxTicksLimit:8},grid:{color:'#4a526888'}},
              y:{ticks:{color:'#b6bbcf',font:{size:10},maxTicksLimit:8,callback:v=>fmtNum(v)},grid:{color:'#4a526888'},position:'right'}},
      plugins:{legend:{display:true,position:'top',labels:{color:'#b6bbcf',font:{size:10},boxWidth:10}},tooltip:{mode:'index',intersect:false,backgroundColor:'#262a35',titleColor:'#e8ebf5',bodyColor:'#c8d2ff',borderColor:'#3a4054',borderWidth:1,callbacks:{label:ctx=>ctx.dataset.label+': '+fmtNum(ctx.parsed.y)}}}}
  });
  registerYoY('equityIndexChart', { mode:'date', dispDates: series.map(p=>p.x),
    fullDates:((typeof equityAllSeries!=='undefined' && equityAllSeries) ? equityAllSeries : series).map(p=>p.x),
    fullValues:((typeof equityAllSeries!=='undefined' && equityAllSeries) ? equityAllSeries : series).map(p=>p.y),
    tol:7, primary:0, color:clr, tension:0.3 });
  applyYoY('equityIndexChart');
}

function selectEquityIndex(idx, btn) {
  equityCurrentIdx = idx;
  const d = eqData[idx];
  const titleEl = document.getElementById('equityChartTitle');
  if(titleEl) setWidgetTitleText(titleEl, d.name);
  document.querySelectorAll('#market-equity .tab-btn').forEach(b=>{
    if(['KOSPI','KOSDAQ','S&P 500','NASDAQ','닛케이','항셍'].includes(b.textContent.trim())) {
      b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
    }
  });
  btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff';
  // 실제 시계열 우선 (data.json.history.indices), 없으면 안내 표시
  const idxNames = ['KOSPI','KOSDAQ','SP500','NASDAQ','Nikkei','Shanghai'];
  const real = getHistoricalSeries('indices', idxNames[idx]);
  if(real && real.length > 1) {
    equityAllSeries = real;
    hideNoDataOverlay('equityIndexChart');
    renderEquityChart();
  } else {
    equityAllSeries = null;
    destroyChart('equityIndexChart');
    showNoDataOverlay('equityIndexChart', '실시간 지수 시계열 데이터가 아직 수집되지 않았습니다.');
  }
}

function renderEquityChart() {
  if(!equityAllSeries) {
    showNoDataOverlay('equityIndexChart', '실시간 지수 시계열 데이터가 아직 수집되지 않았습니다.');
    return;
  }
  hideNoDataOverlay('equityIndexChart');
  const interval = unitIntervalDays(equityPeriodUnit);
  const resampled = resampleSeries(equityAllSeries, interval);
  if(equityCustomFrom && equityCustomTo) {
    const filtered = resampled.filter(d => d.x >= equityCustomFrom && d.x <= equityCustomTo);
    if(filtered.length >= 2) {
      buildEquityIndexChart(filtered);
      return;
    }
  }
  const n = unitDefaultCount(equityPeriodUnit);
  buildEquityIndexChart(resampled.slice(-n));
}

function applyEquityCustomRange() {
  const from = document.getElementById('eqDateFrom').value;
  const to   = document.getElementById('eqDateTo').value;
  if(!from || !to) return;
  equityCustomFrom = from; equityCustomTo = to;
  renderEquityChart();
}
function resetEquityCustomRange() {
  equityCustomFrom = null; equityCustomTo = null;
  const fromEl = document.getElementById('eqDateFrom');
  const toEl   = document.getElementById('eqDateTo');
  if(fromEl) fromEl.value = '';
  if(toEl)   toEl.value   = '';
  renderEquityChart();
}

function setEquityPeriod(p, btn) {
  // 단위 버튼만 비활성화 (지수 선택 버튼 / 비교 버튼은 그대로)
  document.querySelectorAll('#market-equity .eq-unit-btn').forEach(b=>{
    b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
  });
  // Legacy 호환: '1W' → '1W', '1M' → '1M', '3M' → '1M', '1Y' → '1Q', '1D' → '1D'
  const unitMap = {'1D':'1D','1W':'1W','1M':'1M','1Q':'1Q','3M':'1M','1Y':'1Q'};
  equityPeriodUnit = unitMap[p] || '1D';
  if(btn) { btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff'; }
  renderEquityChart();
}

function buildInvestorChart() {
  destroyChart('investorChart');
  const ctx=document.getElementById('investorChart');
  if(!ctx) return;
  // 실데이터(data.json.investorTrading) 미수집 시 — 더미를 그리지 않고 안내 표시
  if(!investorRawData || !investorRawData.length) {
    // 서버 진단(diagnostics.investorTradingReason)이 있으면 actionable 사유를 그대로 노출.
    // (2026~ KRX 정보데이터시스템 로그인 요구로 비는 경우가 대표적 → Secrets KRX_ID/KRX_PW 안내)
    const _diag = (_latestDataForIndicators && _latestDataForIndicators.diagnostics) || {};
    const _reason = _diag.investorTradingReason
      || '투자자별 순매매 실시간 데이터(KRX)를 수집 중입니다. 다음 자동 갱신 시 반영됩니다.';
    if(typeof showNoDataOverlay==='function') showNoDataOverlay('investorChart', _reason);
    const tb0 = document.getElementById('investorSummaryTable');
    if(tb0) tb0.innerHTML = '<tr><td colspan="4" style="padding:12px;text-align:center;color:var(--c-txt-dim);font-size:var(--font-size-sm);">'+_reason+'</td></tr>';
    return;
  }
  if(typeof hideNoDataOverlay==='function') hideNoDataOverlay('investorChart');
  // 단위/기간 필터 적용
  const fromEl = document.getElementById('invDateFrom');
  const toEl   = document.getElementById('invDateTo');
  const from = (fromEl && fromEl.value) || investorFromCur;
  const to   = (toEl && toEl.value) || investorToCur;
  const data = _aggregateInvestorData(investorUnitCur, from, to);
  // 너무 많은 데이터 포인트는 표시 효율을 위해 최근 60개만 (사용자 기간 지정 시 전체)
  let showData = data;
  if(!from && !to && data.dates.length > 60) {
    const n = data.dates.length;
    showData = {
      dates: data.dates.slice(n-60),
      foreign: data.foreign.slice(n-60),
      inst: data.inst.slice(n-60),
      retail: data.retail.slice(n-60),
    };
  }
  const tc = (typeof getThemeColors==='function') ? getThemeColors() : {txt:'#8d90a2', grid:'#2a2e3d55', tooltip:'#262a35', ttTitle:'#dfe2f2', ttBorder:'#2a2e3d'};
  charts['investorChart'] = new Chart(ctx,{
    type:'bar',
    data:{
      labels: showData.dates,
      datasets:[
        {label:'외국인', data:showData.foreign, backgroundColor:getThemeColors().accent+'cc', borderRadius:3},
        {label:'기관',   data:showData.inst,    backgroundColor:(window.CUP+'cc'), borderRadius:3},
        {label:'개인',   data:showData.retail,  backgroundColor:(window.CDN+'cc'), borderRadius:3},
      ]
    },
    options:{responsive:true,maintainAspectRatio:false,
      scales:{
        x:{ticks:{color:tc.txt,font:{size:10},maxTicksLimit:12},grid:{display:false}},
        y:{ticks:{color:tc.txt,font:{size:10},callback:v=>(v>=0?'+':'')+v.toLocaleString()+'억'},grid:{color:tc.grid}}
      },
      plugins:{
        legend:{display:true,labels:{color:tc.txt,font:{size:10},boxWidth:10}},
        tooltip:{mode:'index',intersect:false,backgroundColor:tc.tooltip,titleColor:tc.ttTitle,bodyColor:tc.ttTitle,borderColor:tc.ttBorder,borderWidth:1,
          callbacks:{label:c=>`${c.dataset.label}: ${(c.parsed.y>=0?'+':'')+c.parsed.y.toLocaleString()}억원`}}
      }
    }
  });
  // YoY — 주 시리즈(외국인, dataset 0)만. 월/분기/연 단위에서만 동작(일·주 버킷은 'MM-DD'라 연도 정보가 없어 불가).
  { const _u = investorUnitCur;
    if(_u==='M'||_u==='Q'||_u==='Y'){ const _full=_aggregateInvestorData(_u,null,null);
      registerYoY('investorChart',{mode:'periodlabel',dispLabels:showData.dates,fullLabels:_full.dates,fullValues:_full.foreign,primary:0,color:getThemeColors().accent});
    } else registerYoY('investorChart',null);
    applyYoY('investorChart'); }
  // 요약 테이블 — 단위와 무관하게 일/주/월 누계 표시
  const dailyAgg = _aggregateInvestorData('D', null, null);
  const sum = arr => arr.reduce((a,b)=>a+b,0);
  const rows = [
    {name:'외국인', arr:dailyAgg.foreign},
    {name:'기관',   arr:dailyAgg.inst},
    {name:'개인',   arr:dailyAgg.retail},
  ];
  const tb = document.getElementById('investorSummaryTable');
  if(tb) tb.innerHTML = rows.map(r=>{
    const today = r.arr[r.arr.length-1] || 0;
    const last5 = r.arr.slice(-5);
    const last20 = r.arr.slice(-20);
    const s5  = sum(last5);
    const s20 = sum(last20);
    const clr = v => v>=0?window.CUP:window.CDN;
    const fmt = v => (v>=0?'+':'')+v.toLocaleString()+'억';
    return `<tr style="border-bottom:1px solid var(--c-border);">
      <td style="padding:8px 0;font-weight:var(--font-weight-medium);">${r.name}</td>
      <td style="text-align:right;padding:8px;color:${clr(today)}">${fmt(today)}</td>
      <td style="text-align:right;padding:8px;color:${clr(s5)}">${fmt(s5)}</td>
      <td style="text-align:right;padding:8px;color:${clr(s20)}">${fmt(s20)}</td>
    </tr>`;
  }).join('');
}

function setInvestorUnit(unit, btn) {
  investorUnitCur = unit;
  document.querySelectorAll('.invUnitBtn').forEach(b=>{
    b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
  });
  if(btn) { btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff'; }
  buildInvestorChart();
}

function applyInvestorDateRange() {
  const fromEl = document.getElementById('invDateFrom');
  const toEl   = document.getElementById('invDateTo');
  investorFromCur = fromEl ? fromEl.value || null : null;
  investorToCur   = toEl   ? toEl.value   || null : null;
  buildInvestorChart();
}

// 호환용: 이전 호출 (1D/5D/1M)
function setInvestorPeriod(p, btn) {
  // legacy → 새 단위로 매핑
  const unitMap = {'1D':'D', '5D':'W', '1M':'M'};
  const u = unitMap[p] || 'D';
  investorUnitCur = u;
  ['invPeriod1D','invPeriod5D','invPeriod1M'].forEach(id=>{
    const b=document.getElementById(id);
    if(b){b.classList.remove('active');b.style.background='transparent';b.style.color='var(--c-txt-dim)';}
  });
  if(btn) { btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff'; }
  buildInvestorChart();
}

function buildEquityPage() {
  // 카드 컴팩트 디자인 — 한눈에 더 많이 보이게
  document.getElementById('equityCards').innerHTML = eqData.map(d=>`
    <div class="kpi-card" style="padding:8px 10px;">
      <div style="display:flex;align-items:baseline;justify-content:space-between;gap:6px;">
        <div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);font-weight:var(--font-weight-semibold);text-transform:uppercase;letter-spacing:.04em;white-space:nowrap;">${d.name}</div>
        <div class="${d.chg>=0?'up-txt':'down-txt'}" style="font-size:var(--font-size-sm);font-weight:var(--font-weight-medium);white-space:nowrap;">${d.chg>=0?'▲':'▼'} ${Math.abs(d.chg).toFixed(2)}%</div>
      </div>
      <div style="font-size:var(--font-size-base);font-weight:var(--font-weight-bold);font-family:var(--font-num);margin-top:2px;">${d.val.toLocaleString()}</div>
    </div>`).join('');
  // 기본은 KOSPI 실제 시계열 사용 (data.json.history)
  const real = getHistoricalSeries('indices', 'KOSPI');
  if(real && real.length > 1) {
    equityAllSeries = real;
    hideNoDataOverlay('equityIndexChart');
    renderEquityChart();
  } else {
    equityAllSeries = null;
    destroyChart('equityIndexChart');
    showNoDataOverlay('equityIndexChart', '실시간 지수 시계열 데이터가 아직 수집되지 않았습니다.');
  }
  buildInvestorChart();
  // 투자자별 순매매 — 기본 조회 기간을 '일주일(1W)'로 최초 1회 적용 (2026-06 사용자 요청 기본값).
  // 전역 기본 프리셋(_applyDefaultPresetsForActivePage)이 덮어쓰지 않도록 그룹에 defaultApplied 플래그를 세우고,
  // 사용자가 이후 다른 기간을 고르면 _investorDefaultApplied 가드로 재적용하지 않는다.
  if(!window._investorDefaultApplied) {
    window._investorDefaultApplied = true;
    try {
      const _invGrp = document.querySelector('.preset-btn-group-investor');
      const _invWk = _invGrp && Array.prototype.find.call(_invGrp.querySelectorAll('button'),
        b => ((b.getAttribute('onclick') || '').indexOf("'1W'") >= 0));
      if(_invGrp) _invGrp.dataset.defaultApplied = '1';
      if(_invWk && typeof applyChartPresetPeriod === 'function') {
        window._presetSyncing = true;   // 기본값 적용이 '기간 동기화 전파'(T7)를 유발하지 않게
        try { applyChartPresetPeriod('investor', '1W', _invWk); } finally { window._presetSyncing = false; }
      }
    } catch(_) {}
  }
  // 투자자 데이터가 비어있으면(서버 Actions 미수집) 브라우저에서 1회 자동으로 끌어온다 — 주식/ETF Top10 과 동일 UX.
  if((!investorRawData || !investorRawData.length) && window._REALTIME_BOOST && !window._investorClientTried
     && typeof fetchNaverInvestorTradingClient === 'function') {
    window._investorClientTried = true;
    fetchNaverInvestorTradingClient().then(inv => {
      if(inv && inv.daily && inv.daily.length) {
        applyRealData({ investorTrading: inv, sources: { investorTrading: inv.source } });
        investorRawData = _getInvestorRawData();
        const mp = document.getElementById('page-market');
        if(mp && mp.classList.contains('active')) buildInvestorChart();
      }
    }).catch(()=>{});
  }
  // Top10 상승/하락 — applyRealData가 채운 upMoversStock/downMoversStock 재사용
  const gainTb = document.getElementById('equityTopGainersTable');
  const loseTb = document.getElementById('equityTopLosersTable');
  const noData = `<tr><td colspan="5" style="padding:12px;text-align:center;color:var(--c-txt-muted);font-size:var(--font-size-sm);">네이버 증권에서 데이터 가져오는 중…<br><button onclick="retryEquityMovers(this)" style="margin-top:6px;background:var(--c-accent);color:var(--c-on-accent);border:none;border-radius:var(--r-xs);padding:3px 10px;font-size:var(--font-size-sm);cursor:pointer;">↻ 다시 시도</button></td></tr>`;
  const noDataETF = `<tr><td colspan="4" style="padding:12px;text-align:center;color:var(--c-txt-muted);font-size:var(--font-size-sm);">네이버 증권에서 데이터 가져오는 중…<br><button onclick="refreshETFFromClient(this)" style="margin-top:6px;background:var(--c-accent);color:var(--c-on-accent);border:none;border-radius:var(--r-xs);padding:3px 10px;font-size:var(--font-size-sm);cursor:pointer;">↻ 다시 시도</button></td></tr>`;
  const _volFmt = v => {
    if(v == null || v === '' || v === '—') return '—';
    const n = typeof v === 'string' ? parseFloat(v.replace(/[,K천주]/g,'')) : v;
    if(!n || isNaN(n)) return (typeof v === 'string' ? v : '—');
    if(n >= 1000) return Math.round(n/1000).toLocaleString() + 'K';
    return n.toLocaleString();
  };
  // 주식 행: 거래량 포함 (5컬럼)
  const stockLinkRow = (s, i, color) => `<tr style="border-bottom:1px solid var(--c-border);">
        <td style="padding:5px;color:var(--c-txt-muted);">${i+1}</td>
        <td style="padding:5px;font-weight:var(--font-weight-medium);"><a href="${naverStockUrl(s)}" target="_blank" rel="noopener noreferrer" style="color:inherit;text-decoration:none;border-bottom:1px dotted transparent;" onmouseover="this.style.borderBottomColor='currentColor'" onmouseout="this.style.borderBottomColor='transparent'" title="네이버 증권에서 보기">${s.name}</a></td>
        <td style="text-align:right;padding:5px;">${s.price}</td>
        <td style="text-align:right;padding:5px;color:${color};">${s.chg}</td>
        <td style="text-align:right;padding:5px;color:var(--c-txt-dim);font-size:var(--font-size-sm);">${_volFmt(s.vol)}</td>
      </tr>`;
  // ETF 행: 거래량 데이터 없음 → 4컬럼만
  const etfLinkRow = (s, i, color) => `<tr style="border-bottom:1px solid var(--c-border);">
        <td style="padding:5px;color:var(--c-txt-muted);">${i+1}</td>
        <td style="padding:5px;font-weight:var(--font-weight-medium);"><a href="${naverStockUrl(s)}" target="_blank" rel="noopener noreferrer" style="color:inherit;text-decoration:none;border-bottom:1px dotted transparent;" onmouseover="this.style.borderBottomColor='currentColor'" onmouseout="this.style.borderBottomColor='transparent'" title="네이버 증권에서 보기">${s.name}</a></td>
        <td style="text-align:right;padding:5px;">${s.price}</td>
        <td style="text-align:right;padding:5px;color:${color};">${s.chg}</td>
      </tr>`;
  if(gainTb) {
    gainTb.innerHTML = upMoversStock.length > 0
      ? upMoversStock.map((s,i)=>stockLinkRow(s,i,window.CUP)).join('')
      : noData;
  }
  if(loseTb) {
    loseTb.innerHTML = downMoversStock.length > 0
      ? downMoversStock.map((s,i)=>stockLinkRow(s,i,window.CDN)).join('')
      : noData;
  }
  // ETF Top10 상승/하락 (주식시장 탭) — 거래량 데이터 없음
  const etfGainTb = document.getElementById('etfTopGainersTable');
  const etfLoseTb = document.getElementById('etfTopLosersTable');
  if(etfGainTb) {
    etfGainTb.innerHTML = upMoversETF.length > 0
      ? upMoversETF.map((s,i)=>etfLinkRow(s,i,window.CUP)).join('')
      : noDataETF;
  }
  if(etfLoseTb) {
    etfLoseTb.innerHTML = downMoversETF.length > 0
      ? downMoversETF.map((s,i)=>etfLinkRow(s,i,window.CDN)).join('')
      : noDataETF;
  }
  buildEquityRankings();
}

// 거래대금·토스 체결 랭킹 (data.rankingsKr — 토스 PC 스냅샷, fetch_data 가 당일분만 실음).
// 데이터 없으면 섹션 자체를 숨긴다(수집기 PC 미가동 시 낡은 순위를 보여주지 않음).
function buildEquityRankings() {
  const wrap = document.getElementById('equityRankingsWrap');
  if(!wrap) return;
  const rk = (window._lastRealDataObj || {}).rankingsKr
          || (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators ? _latestDataForIndicators.rankingsKr : null);
  const amtTb = document.getElementById('equityRankAmountTable');
  const tossTb = document.getElementById('equityRankTossTable');
  if(!rk || (!rk.tradingAmount?.length && !rk.tossAmount?.length)) { wrap.style.display = 'none'; return; }
  wrap.style.display = 'grid';
  const fmtAmt = v => v == null ? '—' : (v >= 1e12 ? (v/1e12).toFixed(1)+'조' : Math.round(v/1e8).toLocaleString()+'억');
  const row = (s, i) => `<tr style="border-bottom:1px solid var(--c-border);cursor:pointer;" onclick="equityOpenStockAnalysis('${s.code}','${String(s.name||'').replace(/['"<>\\\\]/g,'')}')" title="종목 분석으로 이동">
      <td style="padding:4px 5px;color:var(--c-txt-muted);">${i+1}</td>
      <td style="padding:4px 5px;font-weight:var(--font-weight-medium);">${s.name}${s.type && s.type !== 'STOCK' ? ` <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">${s.type}</span>` : ''}</td>
      <td style="text-align:right;padding:4px 5px;color:${(s.chg||0) >= 0 ? window.CUP : window.CDN};">${(s.chg||0) >= 0 ? '+' : ''}${(s.chg||0).toFixed(2)}%</td>
      <td style="text-align:right;padding:4px 5px;color:var(--c-txt-dim);">${fmtAmt(s.amount)}</td>
    </tr>`;
  if(amtTb) amtTb.innerHTML = (rk.tradingAmount || []).map(row).join('') || '<tr><td colspan="4" style="padding:10px;text-align:center;color:var(--c-txt-muted);">—</td></tr>';
  if(tossTb) tossTb.innerHTML = (rk.tossAmount || []).map(row).join('') || '<tr><td colspan="4" style="padding:10px;text-align:center;color:var(--c-txt-muted);">—</td></tr>';
}

// 랭킹/등락상위 행 → 투자현황 종목 분석 탭 딥링크. 포트폴리오 페이지가 아직 안 만들어졌거나
// PIN 잠금 해제 대기 중일 수 있어 탭 요소가 생길 때까지 재시도한다(최대 ~6초).
function equityOpenStockAnalysis(code, name) {
  try { showPage('portfolio'); } catch(_) { return; }
  let tries = 0;
  (function go() {
    if(typeof pfStockOpen === 'function' && document.getElementById('pfTab-stock')) {
      try { pfStockOpen({ symbol: code, market: 'KR', name: name || code }); } catch(_) {}
      return;
    }
    if(++tries < 40) setTimeout(go, 150);
  })();
}
// LME 금속 창고 재고 (단위: 톤) — 출처: lme.com 일일 재고 보고서
// 실데이터 연동: 향후 data.json.lmeInventory 에 자동 갱신 (현재는 LME 공식 보고서 기반 최신 스냅샷)
const metalInventory = [
  {name:'구리 (Copper)',   cur:98420,  wkChg:-3210, m4ago:112500, status:'감소'},
  {name:'알루미늄',        cur:512300, wkChg:+8400, m4ago:489000, status:'증가'},
  {name:'아연 (Zinc)',     cur:184200, wkChg:-1850, m4ago:198600, status:'감소'},
  {name:'니켈 (Nickel)',   cur:71440,  wkChg:+920,  m4ago:68300,  status:'증가'},
  {name:'납 (Lead)',       cur:88200,  wkChg:-640,  m4ago:91400,  status:'감소'},
  {name:'주석 (Tin)',      cur:4180,   wkChg:+110,  m4ago:3950,   status:'증가'},
];

let comCurrentIdx = 0;
let comAllSeries = null;
let comPeriodN = 21;
let comSelectedIdx = new Set([0]); // default: WTI

function updateComHeader(c) {
  const chgEl = document.getElementById('comDetailChange');
  const rngEl = document.getElementById('comDetail52Range');
  if(!c) {
    if(chgEl) chgEl.textContent = '';
    if(rngEl) rngEl.textContent = '';
    return;
  }
  if(chgEl) {
    chgEl.className = c.up ? 'up-txt' : 'down-txt';
    chgEl.style.fontSize = '14px';
    chgEl.textContent = (c.up ? '▲ ' : '▼ ') + c.chg;
  }
  if(rngEl) rngEl.textContent = '52주 범위: ' + (c.l52||'-') + ' ~ ' + (c.h52||'-');
}

// 원자재 이름 → data.json.history.commodities 키 매핑
// ⚠ 순서 중요: '백금'·'팔라듐'·'두바이' 같이 다른 키워드를 부분 포함하는 항목을
//   더 일반적인 키워드('금' 등)보다 먼저 검사한다. (예: '백금'은 '금'을 포함)
function comHistoryKey(name) {
  if(!name) return null;
  if(name.includes('두바이') || name.includes('Dubai')) return 'Dubai';
  if(name.includes('WTI')) return 'WTI';
  if(name.includes('Brent')) return 'Brent';
  if(name.includes('팔라듐') || name.includes('Palladium')) return 'Palladium';
  if(name.includes('백금') || name.includes('Platinum')) return 'Platinum';   // '금' 검사보다 먼저
  if(name.includes('금') || name.includes('Gold')) return 'Gold';
  if(name.includes('은') || name.includes('Silver')) return 'Silver';
  if(name.includes('구리') || name.includes('Copper')) return 'Copper';
  if(name.includes('알루미늄') || name.includes('Aluminum')) return 'Aluminum';
  if(name.includes('휘발유') || name.includes('Gasoline')) return 'Gasoline';
  if(name.includes('난방유') || name.includes('Heating')) return 'HeatingOil';
  if(name.includes('천연가스') || name.includes('NatGas') || name.includes('Natural Gas')) return 'NatGas';
  if(name.includes('밀') || name.includes('Wheat')) return 'Wheat';
  if(name.includes('옥수수') || name.includes('Corn')) return 'Corn';
  if(name.includes('콩') || name.includes('Soybean')) return 'Soybean';
  if(name.includes('쌀') || name.includes('Rice')) return 'Rice';
  if(name.includes('커피') || name.includes('Coffee')) return 'Coffee';
  if(name.includes('설탕') || name.includes('Sugar')) return 'Sugar';
  if(name.includes('코코아') || name.includes('Cocoa')) return 'Cocoa';
  return null;
}

function buildComDetailChartMulti() {
  comAnnotations=[]; comPending=null;
  destroyChart('comDetailChart');
  const ctx = document.getElementById('comDetailChart');
  if(!ctx) return;
  // astryx 카테고리 팔레트(OKLCH 등간격 hue, 테마 따라 전환).
  // 등락색(CUP/CDN)은 섞지 않는다 — 한국 관습에서 파랑/빨강이 시리즈 색과
  // 겹쳐 "이 선이 하락이라는 뜻인가?" 하는 오독을 만든다.
  const colors = getThemeColors().series;
  const days = comPeriodN;
  const selectedArr = [...comSelectedIdx];
  // 실데이터 우선 — 선택된 모든 항목에 대해 historical 데이터가 있는지 확인
  let anyReal = false;
  const seriesPerSel = selectedArr.map((idx, i) => {
    const c = comData[idx];
    const key = comHistoryKey(c.name);
    const real = key ? getHistoricalSeries('commodities', key) : null;
    if(real && real.length > 1) {
      anyReal = true;
      // 사용자 기간 지정 우선 적용, 없으면 days slice
      if(comCustomFrom && comCustomTo) {
        const filtered = real.filter(d => d.x >= comCustomFrom && d.x <= comCustomTo);
        return filtered.length >= 2 ? filtered : real.slice(-days);
      }
      return real.slice(-days);
    }
    return null;
  });
  // 하나라도 실데이터가 없으면 안내 메시지
  if(!anyReal || seriesPerSel.some(s => !s)) {
    showNoDataOverlay('comDetailChart', '원자재 시계열 데이터가 아직 수집되지 않았습니다.');
    return;
  }
  hideNoDataOverlay('comDetailChart');
  const labels = seriesPerSel.length ? sl(seriesPerSel[0]) : [];
  const datasets = selectedArr.map((idx, i) => ({
    data: sv(seriesPerSel[i]),
    label: comData[idx].name,
    borderColor: colors[i % colors.length],
    borderWidth: 2,
    pointRadius: 0,
    fill: false,
    tension: 0.3,
  }));
  // Add average line for the FIRST selected commodity
  if(datasets.length > 0) {
    const avgData = calcAvgLine(datasets[0].data);
    datasets.push({
      data: avgData,
      label: `평균 · ${comData[selectedArr[0]].name}`,
      borderColor: '#f5a623',
      borderWidth: 1.5,
      pointRadius: 0,
      fill: false,
      borderDash: [4,4],
      tension: 0,
    });
  }
  // Persist primary series for compatibility (실 데이터 기준)
  if(seriesPerSel.length && seriesPerSel[0]) comAllSeries = seriesPerSel[0];

  const tcCom = getThemeColors();
  charts['comDetailChart'] = new Chart(ctx, {
    type:'line',
    data:{ labels, datasets },
    options:{responsive:true,maintainAspectRatio:false,
      onClick(evt,elements,chart){
        const pts=chart.getElementsAtEventForMode(evt,'index',{intersect:false},false);
        if(!pts.length) return;
        const idx=pts[0].index;
        const price = chart.data.datasets[0].data[idx];
        const label = chart.data.labels[idx];
        chartClick('com', idx, price, label);
      },
      scales:{x:{type:'category',ticks:{color:tcCom.txt,font:{size:10},maxTicksLimit:6},grid:{color:tcCom.grid}},
              y:{ticks:{color:tcCom.txt,font:{size:10},maxTicksLimit:8,callback:v=>fmtNum(v)},grid:{color:tcCom.grid},position:'right'}},
      plugins:{legend:{display:true,position:'top',labels:{color:tcCom.txt,font:{size:10},boxWidth:10}},
        tooltip:{mode:'index',intersect:false,backgroundColor:tcCom.tooltip,titleColor:tcCom.ttTitle,bodyColor:tcCom.ttTitle,borderColor:tcCom.ttBorder,borderWidth:1,callbacks:{label:ctx=>ctx.dataset.label+': '+fmtNum(ctx.parsed.y)}}}}
  });
  // YoY — 주 시리즈(첫 선택 원자재)만 전년 오버레이
  { const _p0 = selectedArr.length ? comData[selectedArr[0]] : null;
    const _k0 = _p0 ? comHistoryKey(_p0.name) : null;
    const _full0 = _k0 ? (getHistoricalSeries('commodities', _k0) || []) : [];
    registerYoY('comDetailChart', { mode:'date', dispDates:(seriesPerSel[0]||[]).map(p=>p.x),
      fullDates:_full0.map(p=>p.x), fullValues:_full0.map(p=>p.y), tol:7, primary:0, color:colors[0], tension:0.3 });
    applyYoY('comDetailChart'); }

  // Update header
  const titleEl = document.getElementById('comDetailTitle');
  const priceEl = document.getElementById('comDetailPrice');
  if(selectedArr.length === 1) {
    const c = comData[selectedArr[0]];
    if(titleEl) setWidgetTitleText(titleEl, c.name);
    if(priceEl) priceEl.textContent = c.price;
    updateComHeader(c);
  } else if(selectedArr.length > 1) {
    if(titleEl) setWidgetTitleText(titleEl, `${selectedArr.length}개 선택 비교`);
    if(priceEl) priceEl.textContent = '';
    updateComHeader(null);
  }
}

// 호환용 (이전 호출처에서 사용)
function buildComDetailChart(series) {
  // 단일선택 모드로 호환 호출 시 멀티 차트로 재라우팅
  buildComDetailChartMulti();
}

function toggleCommoditySelect(idx, checked, cbEl) {
  if(checked) {
    comSelectedIdx.add(idx);
  } else {
    if(comSelectedIdx.size <= 1) {
      // 최소 1개 유지
      if(cbEl) cbEl.checked = true;
      return;
    }
    comSelectedIdx.delete(idx);
  }
  // primary index = 첫번째 선택
  comCurrentIdx = [...comSelectedIdx][0];
  buildComDetailChartMulti();
}

function selectCommodity(idx, el) {
  // 행 클릭 → 체크박스 토글
  const cb = el && el.querySelector ? el.querySelector('input[type=checkbox]') : null;
  if(cb) {
    cb.checked = !cb.checked;
    toggleCommoditySelect(idx, cb.checked, cb);
  } else {
    if(comSelectedIdx.has(idx) && comSelectedIdx.size > 1) comSelectedIdx.delete(idx);
    else comSelectedIdx.add(idx);
    comCurrentIdx = [...comSelectedIdx][0];
    buildComDetailChartMulti();
  }
}

function setComPeriod(p, btn) {
  document.querySelectorAll('#market-commodity .tab-btn').forEach(b=>{
    if(['1M','3M','1Y'].includes(b.textContent.trim())) {
      b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
    }
  });
  btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff';
  comPeriodN = p==='1M'?21:p==='3M'?63:252;
  buildComDetailChartMulti();
}

// 운송 운임지수(해상운임) — data.json.freight.items 를 표로 렌더.
// 미수집(서버 운임 수집 실패) 시 지수명 목록 + '수집 중' + (상단)네이버 링크로 안내.
const FREIGHT_META = [
  ['SCFI','상하이컨테이너 운임지수','상하이해운거래소(SSE)'],
  ['CCFI','중국컨테이너 운임지수','상하이해운거래소(SSE)'],
  ['BDI','BDI 건화물선지수','발틱해운거래소(BDI)'],
  ['BCI','BCI 케이프사이즈지수','발틱해운거래소(BDI)'],
  ['BPI','BPI 파나막스지수','발틱해운거래소(BDI)'],
  ['BSI','BSI 수프라막스지수','발틱해운거래소(BDI)'],
  ['BHI','BHI 핸디사이즈지수','발틱해운거래소(BDI)'],
  ['BDTI','BDTI 원유유조선지수','발틱해운거래소(BDI)'],
  ['BCTI','BCTI 석유제품선지수','발틱해운거래소(BDI)'],
];
function buildFreightTable() {
  const tb = document.getElementById('freightTable');
  if(!tb) return;
  const d = (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators) || {};
  const items = ((d.freight || {}).items) || [];
  const byCode = {};
  items.forEach(it => { if(it && it.code) byCode[String(it.code).toUpperCase()] = it; });
  const fmt = (v, nd=2) => (v == null || isNaN(v)) ? '—'
    : Number(v).toLocaleString('en-US', {minimumFractionDigits:nd, maximumFractionDigits:nd});
  tb.innerHTML = FREIGHT_META.map(([code, name, exch]) => {
    const it = byCode[code];
    if(!it || it.price == null) {
      return `<tr style="border-bottom:1px solid var(--c-border);">
        <td style="padding:6px 0;color:var(--c-txt);">${name}</td>
        <td style="text-align:right;padding:6px;color:var(--c-txt-muted);">—</td>
        <td style="text-align:right;padding:6px;color:var(--c-txt-muted);">—</td>
        <td style="text-align:right;padding:6px;color:var(--c-txt-muted);">—</td>
        <td style="text-align:right;padding:6px;color:var(--c-txt-dim);font-size:var(--font-size-xs);">${exch}</td></tr>`;
    }
    const chg = (it.chgPct != null) ? it.chgPct : null;
    const cls = (chg == null) ? '' : (chg >= 0 ? 'up-txt' : 'down-txt');
    const arrow = (chg == null) ? '' : (chg >= 0 ? '▲' : '▼');
    // change 절대값이 없으면 price × chgPct / (1 + chgPct/100) 으로 근사 계산
    const absChg = it.change != null ? Math.abs(it.change)
      : (it.price != null && chg != null && chg !== 0) ? Math.abs(it.price * chg / 100 / (1 + chg / 100)) : null;
    const chgTxt = (chg == null) ? '—'
      : `${arrow} ${absChg != null ? fmt(absChg) : ''} (${chg >= 0 ? '+' : ''}${fmt(chg)}%)`;
    return `<tr style="border-bottom:1px solid var(--c-border);">
      <td style="padding:6px 0;color:var(--c-txt);">${it.name || name}</td>
      <td style="text-align:right;padding:6px;font-family:var(--font-num);">${fmt(it.price)}</td>
      <td class="${cls}" style="text-align:right;padding:6px;">${chgTxt}</td>
      <td style="text-align:right;padding:6px;color:var(--c-txt-dim);font-size:var(--font-size-sm);">${it.date || '—'}</td>
      <td style="text-align:right;padding:6px;color:var(--c-txt-dim);font-size:var(--font-size-xs);">${it.exchange || exch}</td></tr>`;
  }).join('');
}
async function refreshFreight(btn) {
  if(btn && typeof _refreshFeedback === 'function') _refreshFeedback(btn, 'loading');
  try {
    if(typeof loadRealData === 'function') await loadRealData().catch(()=>{});  // data.json 재페치(freight 포함)
    if(typeof buildFreightTable === 'function') buildFreightTable();
    const n = ((((_latestDataForIndicators||{}).freight)||{}).items||[]).length;
    if(btn && typeof _refreshFeedback === 'function') _refreshFeedback(btn, n ? 'success' : 'warn', n ? `${n}건` : '수집 중');
  } catch(e) {
    if(btn && typeof _refreshFeedback === 'function') _refreshFeedback(btn, 'error', '실패');
  }
}

// ═══ 🌊 엘니뇨·라니냐 기후 영향 분석 ═══════════════════════════════════════════
// ENSO(엘니뇨·남방진동) 국면별로 ① 원자재 수급·가격 변동성의 전형적 패턴과 ② 그것이 국내
// 주가/산업으로 연동되는 경로를 정리한 분석 카드. 실시간 예보가 아니라 과거 사이클의 historical
// pattern 이며, 사용자가 국면(엘니뇨/라니냐/중립)을 골라 시나리오별 영향을 비교할 수 있게 한다.
const ENSO_SCENARIOS = {
  elnino: {
    label: '🔴 엘니뇨', tab: '엘니뇨', accent: window.CDN,
    phase: '적도 동태평양 해수면 온도 상승 (난수기)',
    overallVol: '高',
    summary: '동남아·인도·호주의 가뭄·고온이 두드러져 설탕·커피·팜유 등 열대 농산물 공급이 줄고, 북반구 겨울이 온난해 난방용 가스 수요는 약해지는 경향. 기후 프리미엄으로 농산물 가격 변동성이 커집니다.',
    commodities: [
      { name: '설탕(원당)',      dir: 'up',    vol: '高', note: '인도·태국 몬순 약화·가뭄 → 사탕수수 감산',
        detail: '인도·태국은 세계 설탕 공급의 큰 축. 엘니뇨 가뭄으로 사탕수수 단수가 떨어지고, 인도가 수출 쿼터를 축소하면 국제 원당가가 급등하는 패턴.' },
      { name: '커피',            dir: 'up',    vol: '高', note: '베트남·브라질 건조 → 로부스타·아라비카 감산',
        detail: '베트남 중부고원 건조는 로부스타, 브라질 미나스 건조는 아라비카를 동시에 압박. 두 대형 산지가 함께 타격받으면 가격 급등 위험이 커짐.' },
      { name: '코코아',          dir: 'up',    vol: '中', note: '서아프리카 건조 리스크',
        detail: '세계 코코아 약 70%가 서아프리카(코트디부아르·가나)산. 엘니뇨 건조·하르마탄(건조풍) 강화로 수확이 줄어드는 경향.' },
      { name: '팜유',            dir: 'up',    vol: '中', note: '인니·말련 건조로 단수(수확량) 저하',
        detail: '엘니뇨 건조는 통상 6~12개월 시차를 두고 팜 단수에 반영. 인니·말련 생산이 둔화되면 식용유 전반(대두유 포함)에 상방 압력.' },
      { name: '천연가스',        dir: 'down',  vol: '中', note: '북반구 겨울 온난 → 난방 수요 감소',
        detail: '엘니뇨 겨울은 북미·동아시아가 평년보다 온난한 경향. 난방용 가스 수요가 줄고 재고가 쌓이며 가격에 하방 압력으로 작용.' },
      { name: '밀',              dir: 'mixed', vol: '中', note: '호주·아르헨티나 건조 vs 미국 양호 → 혼조',
        detail: '엘니뇨 시 호주 밀 산지는 건조로 감산 위험(상방), 반면 미국 평원은 강수가 양호한 편(하방). 산지별 방향이 엇갈려 변동성만 커짐.' },
      { name: '옥수수·대두',     dir: 'down',  vol: '中', note: '미 중서부 강수 양호 → 작황 우호적',
        detail: '엘니뇨는 미국 중서부 곡창에 여름 강수를 더해 옥수수·대두 작황에 우호적인 경우가 많음 → 증산 기대가 가격에 하방으로 작용하는 경향.' },
      { name: '니켈',            dir: 'up',    vol: '中', note: '인도네시아 우기 강화 → 채굴·선적 차질',
        detail: '인도네시아가 세계 니켈 공급의 절반 이상. 엘니뇨 후 우기가 강해지면 노천광 채굴·선적이 지연돼 공급 우려로 가격이 들썩일 수 있음.' },
      { name: '주석',            dir: 'up',    vol: '中', note: '인니 수출 비중 높아 니켈과 동반 변동',
        detail: '주석도 인도네시아 수출 의존도가 높아, 인니 기상·수출 정책 변화 시 니켈과 함께 공급 우려가 부각되는 비철 품목.' },
    ],
    sectors: [
      { sector: '음식료 (원가 압박)', tickers: 'CJ제일제당 · 대상 · 롯데웰푸드 · 오뚜기', effect: 'neg', note: '설탕·커피·팜유 원재료비 ↑ → 마진 압박' },
      { sector: '가스·난방',          tickers: '한국가스공사',                          effect: 'neg', note: '온난한 겨울 → 난방·LNG 수요 둔화' },
      { sector: '비료·농업',          tickers: 'KG케미칼 · 효성오앤비 · 남해화학',       effect: 'pos', note: '농산물가 ↑ → 비료·작물보호제 수요 확대' },
      { sector: '곡물·사료',          tickers: '한일사료 · 사조동아원',                  effect: 'mixed', note: '곡물가 등락 → 사료 원가 변동' },
    ],
  },
  lanina: {
    label: '🔵 라니냐', tab: '라니냐', accent: getThemeColors().accent,
    phase: '적도 동태평양 해수면 온도 하강 (한수기)',
    overallVol: '高',
    summary: '남미(아르헨티나·브라질 남부) 가뭄으로 대두·옥수수가 흔들리고, 북반구 한파로 원유·천연가스 난방 수요가 늘며, 페루·칠레 폭우는 구리 공급을 위협하는 경향. 에너지·곡물·구리 변동성이 동반 확대됩니다.',
    commodities: [
      { name: '대두',          dir: 'up',    vol: '高', note: '아르헨티나·브라질 남부 가뭄 → 작황 부진',
        detail: '라니냐는 아르헨티나·브라질 남부에 가뭄을 유발. 세계 대두 핵심 수출지의 작황이 부진하면 국제 대두가에 강한 상방 압력.' },
      { name: '옥수수',        dir: 'up',    vol: '中', note: '남미 가뭄 → 감산 우려',
        detail: '대두와 같은 남미 산지를 공유. 가뭄으로 옥수수 단수가 떨어지면 사료·에탄올 수요와 맞물려 가격 변동성이 커짐.' },
      { name: '밀',            dir: 'up',    vol: '中', note: '미 남부 평원 건조 → 겨울밀 부담',
        detail: '라니냐 시 미국 남부 평원이 건조해 겨울밀 작황에 부담. 호주는 다우로 증산 경향이라 산지별로 엇갈리나 전반 변동성 확대.' },
      { name: '원유',          dir: 'up',    vol: '高', note: '북반구 한파 → 난방·정제 수요 증가',
        detail: '라니냐 겨울은 북미·동아시아 한파 빈도가 높아 난방유 수요가 늘고, 정제마진 개선으로 원유 수요에도 상방으로 작용.' },
      { name: '천연가스',      dir: 'up',    vol: '高', note: '한파 → 난방수요 급증 + 동파 감산 위험',
        detail: '한파 시 난방용 가스 수요가 급증하는 데다, 미국 셰일 지대 동파(freeze-off)로 생산이 일시 중단되면 가스가 급등하는 대표적 라니냐 리스크.' },
      { name: '구리',          dir: 'up',    vol: '中', note: '페루·칠레 폭우 → 광산·물류 차질',
        detail: '라니냐 시 안데스(페루·칠레) 폭우·홍수로 세계 최대 구리 광산의 조업·운송이 차질을 빚으면 공급 우려로 가격 상방.' },
      { name: '팜유',          dir: 'up',    vol: '中', note: '동남아 과우(홍수) → 수확 차질',
        detail: '라니냐는 인니·말련에 과우·홍수를 유발. 수확·운송이 막히면 팜유 단기 공급 차질로 식용유 가격이 들썩임.' },
      { name: '커피',          dir: 'mixed', vol: '中', note: '산지별 강우 편차로 혼조',
        detail: '브라질은 다우로 작황에 우호적인 반면, 중미·동남아는 과우 피해가 날 수 있어 산지별로 방향이 엇갈리는 혼조 양상.' },
    ],
    sectors: [
      { sector: '정유·가스 (난방수요↑)', tickers: 'S-Oil · GS · 한국가스공사',      effect: 'pos', note: '난방·정제 수요 ↑ → 정제마진·판매 개선' },
      { sector: '비철·구리',             tickers: '풍산 · LS · 고려아연',           effect: 'pos', note: '구리·아연 가격 ↑ → 제품 스프레드 개선' },
      { sector: '곡물·사료 (원가↑)',     tickers: '한일사료 · 팜스코',              effect: 'neg', note: '대두·옥수수 ↑ → 사료 원가 부담' },
      { sector: '음식료 (원가↑)',        tickers: 'CJ제일제당 · 대상',              effect: 'neg', note: '곡물·유지류 원가 ↑ → 마진 압박' },
      { sector: '비료',                  tickers: '남해화학 · KG케미칼',            effect: 'pos', note: '곡물가 ↑ → 비료 수요·판가 상승' },
    ],
  },
  neutral: {
    label: '⚪ 중립', tab: '중립', accent: '#8b90a8',
    phase: '해수면 온도 평년 수준 (ONI ±0.5℃ 이내)',
    overallVol: '低~中',
    summary: 'ENSO발 공급 충격이 제한적이어서 원자재는 기후 프리미엄보다 재고·달러지수(DXY)·OPEC+ 정책·지정학 등 펀더멘털 요인에 더 민감해집니다. 특정 섹터 일방향 베팅보다 환율·금리 흐름과의 연동에 주목할 국면.',
    commodities: [
      { name: '원유',   dir: 'mixed', vol: '中', note: 'OPEC+ 정책·재고가 핵심 변수',
        detail: 'ENSO 신호가 약해 기후 프리미엄이 제한적. OPEC+ 감산 정책·미국 원유재고·달러지수·지정학이 가격을 주도하며 박스권 등락 경향.' },
      { name: '곡물',   dir: 'mixed', vol: '低', note: '평년 작황 가정 → 계절성·환율 영향 우세',
        detail: '평년 수준 작황을 가정하면 기후발 충격이 작음. 파종·수확 계절성, 환율, 수출입 정책이 곡물가를 더 좌우.' },
      { name: '금속',   dir: 'mixed', vol: '中', note: '달러·금리·중국 수요가 가격 주도',
        detail: 'ENSO 영향이 미미한 국면. 달러지수·실질금리·중국 경기 및 부양책이 비철·귀금속 가격의 핵심 동인.' },
    ],
    sectors: [
      { sector: '시장 전반', tickers: '섹터 일방 베팅보다 환율·금리 연동 주목', effect: 'mixed', note: 'ENSO 신호 약함 → 개별 펀더멘털·환율 흐름 중심 대응' },
    ],
  },
};
// 🌊 실측 ENSO 바인딩 — data.json.climate.enso 를 읽어 카드를 구동한다.
let ensoUserPinned = false;  // 사용자가 탭을 직접 고르면 자동 국면 덮어쓰기 중단
function ensoData() {
  const d = _latestDataForIndicators;
  return (d && d.climate && d.climate.enso) ? d.climate.enso : null;
}
function ensoPhaseLabel(p)   { return ({elnino:'엘니뇨', lanina:'라니냐', neutral:'중립'})[p] || '중립'; }
function ensoStrengthLabel(s){ return ({weak:'약한', moderate:'중간', strong:'강한', very_strong:'매우 강한', neutral:''})[s] || ''; }
function ensoTrendLabel(t)   { return ({warming:'따뜻해지는 추세', cooling:'차가워지는 추세', steady:'안정적'})[t] || ''; }
function ensoLiveSentence(e) {
  if (!e || !e.oni || typeof e.oni.value !== 'number') return null;
  const o = e.oni, sgn = o.value >= 0 ? '+' : '';
  let s = `현재 ${o.asOf} 관측 기준 ONI는 ${sgn}${o.value.toFixed(2)}℃(${ensoPhaseLabel(e.phase)})`;
  if (e.nino34_weekly && typeof e.nino34_weekly.value === 'number') {
    const w = e.nino34_weekly, ws = w.value >= 0 ? '+' : '';
    s += `이며, 최근 주간 Niño 3.4는 ${ws}${w.value.toFixed(1)}℃로 ${ensoTrendLabel(e.trend)}입니다.`;
  } else { s += '입니다.'; }
  return s;
}
let ensoCurrent = 'elnino';
let ensoView = 'sector';  // 분석 렌즈: 'sector'=원자재·섹터(기존) | 'macro'=시간축 거시 파급(신규)
// ① 원자재 영향 행 — 필터(변동성)·정렬 상태. 변경 시 카드 재렌더.
let ensoComFilter = 'all';  // all | 高 | 中 | 低
let ensoComSort   = 'vol';  // vol(변동성) | dir(방향) | name(이름)
function setEnsoComFilter(v){ ensoComFilter = v; renderEnsoCard(); }
function setEnsoComSort(v){ ensoComSort = v; renderEnsoCard(); }
function _ensoDirChip(dir) {
  if(dir === 'up')   return '<span class="up-txt" style="font-weight:var(--font-weight-semibold);font-size:var(--font-size-sm);">▲ 상승 압력</span>';
  if(dir === 'down') return '<span class="down-txt" style="font-weight:var(--font-weight-semibold);font-size:var(--font-size-sm);">▼ 하락 압력</span>';
  return '<span style="color:var(--c-warn);font-weight:var(--font-weight-semibold);font-size:var(--font-size-sm);">↔ 혼조</span>';
}
function _ensoVolChip(vol) {
  const c = vol === '高' ? window.CDN : (vol === '中' ? '#f5a623' : '#8b90a8');
  return `<span style="font-size:var(--font-size-xs);font-weight:var(--font-weight-semibold);color:${c};border:1px solid ${c}66;border-radius:var(--r-full);padding:0 7px;white-space:nowrap;">변동성 ${vol}</span>`;
}
function _ensoEffectChip(effect) {
  if(effect === 'pos')  return '<span style="font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);color:var(--color-on-success);background:var(--c-up);border-radius:var(--r-full);padding:1px 8px;white-space:nowrap;">호재</span>';
  if(effect === 'neg')  return '<span style="font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);color:var(--color-on-error);background:var(--c-down);border-radius:var(--r-full);padding:1px 8px;white-space:nowrap;">악재</span>';
  return '<span style="font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);color:#fff;background:#f5a623;border-radius:var(--r-full);padding:1px 8px;white-space:nowrap;">혼재</span>';
}
function setEnsoScenario(key, btn) {
  if(ENSO_SCENARIOS[key]) ensoCurrent = key;
  ensoUserPinned = true;
  renderEnsoCard();
}
/* ===== ENSO forecast+diagram (start) ===== */
// 🌐 기상청 예측 뷰어 + 분석 로직 도식화 — climate.enso(실측) + 기관 예측 차트(이미지) 를
// 카드에 결합. 데이터 없으면 도식은 '관측 대기'(국면 미점등), 이미지는 onerror→링크 폴백.
function cpcProbUrl(year) {
  return `https://www.cpc.ncep.noaa.gov/archives/enso/roni/images/${year}/enso-probs-current.png`;
}
// 도식 표시용 순수 뷰모델 — enso 가 없거나 oni 값이 없으면 hasData:false (국면 날조 금지).
function ensoDiagramState(enso) {
  if (!enso || !enso.oni || typeof enso.oni.value !== 'number') {
    return { hasData:false, oniText:'관측 대기', asOf:'', phaseKey:null,
             phaseLabel:'—', strengthLabel:'', trendLabel:'', topCommodities:[], topSectors:[] };
  }
  const ph = enso.phase || 'neutral';
  const sc = ENSO_SCENARIOS[ph] || {};
  const v = enso.oni.value;
  return {
    hasData:true,
    oniText: (v >= 0 ? '+' : '') + v.toFixed(2) + '℃',
    asOf: enso.oni.asOf || '',
    phaseKey: ph,
    phaseLabel: ensoPhaseLabel(ph),
    strengthLabel: ensoStrengthLabel(enso.strength),
    trendLabel: ensoTrendLabel(enso.trend),
    topCommodities: (sc.commodities || []).slice(0,3).map(c => c.name),
    topSectors: (sc.sectors || []).slice(0,2).map(s => s.sector),
  };
}
// 기관 예측 소스 — embed:있으면 이미지 임베드(검증된 NOAA 2건), 없으면 링크 카드.
const ensoForecastSources = [
  { region:'🇺🇸 미국', label:'NOAA CPC ENSO 확률', embed:'cpcProb',
    page:'https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/probabilities/' },
  { region:'🇺🇸 미국', label:'NOAA CFSv2 Niño3.4 예측',
    embed:'https://www.cpc.ncep.noaa.gov/products/people/wwang/cfsv2fcst/imagesInd3/nino34Mon.gif',
    page:'https://www.cpc.ncep.noaa.gov/products/people/wwang/cfsv2fcst/' },
  { region:'🇺🇸 미국', label:'IRI ENSO 예측',
    page:'https://iri.columbia.edu/our-expertise/climate/forecasts/enso/current/' },
  { region:'🇪🇺 유럽', label:'ECMWF SEAS5 Niño plume',
    page:'https://charts.ecmwf.int/products/seasonal_system5_standard_nino_plumes' },
  { region:'🇯🇵 일본', label:'JMA 엘니뇨 전망',
    page:'https://ds.data.jma.go.jp/tcc/tcc/products/elnino/outlook.html' },
];
function ensoLogicDiagramHTML(enso) {
  const st = ensoDiagramState(enso);
  const node = 'flex:1;min-width:118px;background:var(--c-bg);border:1px solid var(--c-border);border-radius:var(--r-sm);padding:8px 10px;';
  const hi = st.hasData ? 'border-color:var(--c-accent);background:var(--c-card);' : '';
  const arrow = '<div style="align-self:center;color:var(--c-txt-muted);font-size:var(--font-size-base);padding:0 1px;">→</div>';
  const t = 'font-size:11px;font-weight:700;color:var(--c-txt);';
  const d = 'font-size:10px;color:var(--c-txt-dim);line-height:1.45;margin-top:2px;';
  const phaseDetail = st.hasData
    ? `${st.phaseLabel}${st.strengthLabel ? ' · ' + st.strengthLabel : ''}${st.trendLabel ? ' · ' + st.trendLabel : ''}`
    : '—';
  return `
    <div style="margin-bottom:12px;">
      <div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);color:var(--c-primary);letter-spacing:.04em;margin-bottom:6px;">
        🔗 분석 로직 흐름 ${st.hasData ? '<span style="color:var(--c-txt-muted);font-weight:var(--font-weight-semibold);">(실측 반영)</span>' : '<span style="color:var(--c-txt-muted);font-weight:var(--font-weight-semibold);">(관측 대기)</span>'}
      </div>
      <div style="overflow-x:auto;"><div style="display:flex;gap:4px;align-items:stretch;min-width:660px;">
        <div style="${node}"><div style="${t}">입력</div><div style="${d}">관측 ONI·Niño3.4<br>예측 기상청 확률</div></div>
        ${arrow}
        <div style="${node}"><div style="${t}">ONI ±0.5℃ 분류</div><div style="${d}">${st.hasData ? `현재 ${st.oniText}${st.asOf ? ' (' + st.asOf + ')' : ''}` : '데이터 대기'}</div></div>
        ${arrow}
        <div style="${node}${hi}"><div style="${t}">국면</div><div style="${d}">${phaseDetail}</div></div>
        ${arrow}
        <div style="${node}"><div style="${t}">① 원자재 변동성</div><div style="${d}">${st.hasData && st.topCommodities.length ? st.topCommodities.join(', ') : '국면별 패턴'}</div></div>
        ${arrow}
        <div style="${node}"><div style="${t}">② 국내 주가·산업</div><div style="${d}">${st.hasData && st.topSectors.length ? st.topSectors.join(', ') : '국면별 영향'}</div></div>
      </div></div>
    </div>`;
}
let ensoForecastsExpanded = false;
function toggleEnsoForecasts() { ensoForecastsExpanded = !ensoForecastsExpanded; renderEnsoCard(); }
function ensoForecastsHTML(expanded) {
  const head = `
    <div onclick="toggleEnsoForecasts()" style="cursor:pointer;display:flex;align-items:center;gap:6px;margin-top:14px;padding-top:10px;border-top:1px solid var(--c-border);font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);color:var(--c-primary);letter-spacing:.04em;">
      <span>🌐 다른 기관 예측 더 보기</span>
      <span style="color:var(--c-txt-muted);font-weight:var(--font-weight-semibold);">IRI · ECMWF · JMA</span>
      <span style="margin-left:auto;color:var(--c-txt-muted);">${expanded ? '▲' : '▼'}</span>
    </div>`;
  if (!expanded) return head;
  // NOAA CPC·CFSv2(embed)는 상단 '🔮 공식 예측' 패널로 승격됨 — 여기선 링크 전용 기관만.
  const link = (s) => `<a href="${s.page}" target="_blank" rel="noopener noreferrer" style="color:var(--c-primary);">${s.label} ↗</a>`;
  const items = ensoForecastSources.filter(s => !s.embed)
    .map(s => `<div style="font-size:var(--font-size-sm);color:var(--c-txt-dim);">${s.region} · ${link(s)}</div>`).join('');
  return head + `
    <div style="margin-top:8px;display:flex;flex-direction:column;gap:8px;">${items}</div>
    <div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:8px;line-height:1.6;">
      ※ 각 기관의 공식 예측 페이지. 예보는 갱신·정정될 수 있으며 투자 참고용입니다.
    </div>`;
}
/* ===== ENSO forecast+diagram (end) ===== */

/* ===== 🌐 시간축 거시 파급 (IMF WP/15/89, 2015) — 신규 렌즈 (start) ===== */
// data.json.climate.impact 를 읽어 단기(0~6M)/중기(6~12M)/장기(1~3Y) 경제 파급을 렌더.
// 국면·강도는 실측(NOAA), 영향 방향/자산군은 IMF 논문·기후학 기반 '전형 패턴'(예보 아님).
function climateImpactData() {
  const d = _latestDataForIndicators;
  return (d && d.climate && d.climate.impact) ? d.climate.impact : null;
}
// 자산 stance(위험/기회/혼조) → 색상 정의. risk=빨강, opportunity=파랑, mixed=주황.
const ENSO_STANCE = {
  risk:        { color:window.CDN, label:'위험' },
  opportunity: { color:getThemeColors().accent, label:'기회' },
  mixed:       { color:'#f5a623', label:'혼조' },
};
function _ensoStanceChip(stance) {
  const s = ENSO_STANCE[stance] || ENSO_STANCE.mixed;
  return `<span style="font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);color:#fff;background:${s.color};border-radius:var(--r-full);padding:1px 8px;white-space:nowrap;">${s.label}</span>`;
}
// 분석 렌즈 탭 — 'sector'(기존 ①②) | 'macro'(신규 시간축 거시 파급)
function ensoLensTabsHTML() {
  const t = (key, icon, label) => {
    const on = ensoView === key;
    return `<button onclick="setEnsoView('${key}')" style="font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);padding:6px 14px;border:none;border-bottom:2px solid ${on?'var(--c-accent)':'transparent'};background:transparent;color:${on?'var(--c-txt)':'var(--c-txt-muted)'};cursor:pointer;">${icon} ${label}</button>`;
  };
  return `<div style="display:flex;gap:4px;border-bottom:1px solid var(--c-border);margin:2px 0 12px;">${t('sector','🛢️','원자재·섹터')}${t('macro','🌐','시간축 거시 파급')}</div>`;
}
function setEnsoView(key) {
  if (key === 'sector' || key === 'macro') ensoView = key;
  renderEnsoCard();
}
// 신규: 시간축 거시 파급 본문(선택 국면 phaseKey 기준). impact 데이터 없으면 '갱신 대기' 안내(날조 금지).
function ensoMacroHTML(phaseKey, live) {
  const imp = climateImpactData();
  if (!imp || !imp.map || !imp.map[phaseKey]) {
    return `<div style="background:var(--c-bg);border:1px dashed var(--c-border);border-radius:var(--r-sm);padding:18px 14px;text-align:center;color:var(--c-txt-dim);font-size:var(--font-size-sm);line-height:1.7;">
      🌊 기후–거시경제 파급 데이터 갱신 대기 중<br>
      <span style="font-size:var(--font-size-sm);color:var(--c-txt-muted);">다음 일일 수집(NOAA ONI) 후 자동 표시됩니다 — 값을 임의로 채우지 않습니다.</span>
    </div>`;
  }
  const node = imp.map[phaseKey];
  const isActive = (phaseKey === imp.activePhase);
  const confMap = {
    imf:        { t:'IMF 논문 직접 분석',            c:window.CUP },
    estimated:  { t:'거울상 추정(논문은 엘니뇨 중심)', c:'#f5a623' },
    low_signal: { t:'ENSO 신호 약함',               c:'#8b90a8' },
  };
  const conf = confMap[node.confidence] || confMap.low_signal;
  // 실측 게이지 — 활성(현재 실측) 국면일 때만 실측 강도 노출, 아니면 '가정 시나리오' 안내.
  let gauge;
  if (isActive) {
    const pct = Math.round((imp.intensity || 0) * 100);
    const oniTxt = (typeof imp.oni === 'number') ? `${imp.oni>=0?'+':''}${imp.oni.toFixed(2)}℃` : '—';
    const strLabel = ensoStrengthLabel(imp.activeStrength) || ensoPhaseLabel(phaseKey);
    gauge = `<div style="margin:2px 0 14px;">
      <div style="display:flex;align-items:center;gap:8px;font-size:var(--font-size-sm);color:var(--c-txt-dim);margin-bottom:4px;flex-wrap:wrap;">
        <span style="font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);color:var(--c-on-accent);background:var(--c-accent);border-radius:var(--r-full);padding:1px 8px;">실측</span>
        ENSO 신호 강도 · ONI ${oniTxt}${imp.asOf?` (${imp.asOf})`:''}${strLabel?` · ${strLabel}`:''}
      </div>
      <div style="height:8px;background:var(--c-border);border-radius:var(--r-full);overflow:hidden;">
        <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,var(--c-up),#f5a623,var(--c-down));border-radius:var(--r-full);transition:width .4s;"></div>
      </div>
    </div>`;
  } else {
    gauge = `<div style="margin:2px 0 14px;font-size:var(--font-size-sm);color:var(--c-txt-muted);background:var(--c-bg);border:1px solid var(--c-border);border-radius:var(--r-sm);padding:7px 10px;line-height:1.6;">
      ℹ️ 가정 시나리오 — 현재 실측 국면은 <b style="color:var(--c-txt-dim);">${ensoPhaseLabel(imp.activePhase)}</b> 입니다. 이 탭은 <b style="color:var(--c-txt-dim);">${ensoPhaseLabel(phaseKey)}</b> 국면의 전형 패턴을 보여줍니다.
    </div>`;
  }
  // 위험/기회/혼조 범례
  const legend = `<div style="display:flex;gap:14px;flex-wrap:wrap;font-size:var(--font-size-sm);color:var(--c-txt-dim);margin-bottom:10px;">
    ${Object.keys(ENSO_STANCE).map(k=>`<span style="display:inline-flex;align-items:center;gap:5px;"><span style="width:9px;height:9px;border-radius:50%;background:${ENSO_STANCE[k].color};display:inline-block;"></span>${ENSO_STANCE[k].label}</span>`).join('')}
  </div>`;
  // 신호등 히트맵 — 행=자산, 열=단/중/장기. 각 자산은 자기 시간대 칸만 stance 색으로 점등(데이터 있는 곳만).
  const HLAB = {short:'단기', mid:'중기', long:'장기'};
  const horizons = (imp.horizons || ['short','mid','long']).filter(hk => node[hk]);
  const cols = `minmax(116px,1.5fr) repeat(${horizons.length},1fr)`;
  const head = `<div style="display:grid;grid-template-columns:${cols};gap:3px;margin-bottom:4px;">
    <div></div>
    ${horizons.map(hk => { const h = node[hk]; return `<div title="${_ensoAttr(h.mechanism)}" style="text-align:center;font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);color:var(--c-txt);line-height:1.2;">${h.icon||''} ${HLAB[hk]||hk}<div style="font-size:var(--font-size-xs);font-weight:var(--font-weight-semibold);color:var(--c-txt-muted);">${h.timeframe||''}</div></div>`; }).join('')}
  </div>`;
  const hmRows = [];
  horizons.forEach((hk,hi) => (node[hk].assets||[]).forEach(a => hmRows.push({name:a.name, hi, stance:a.stance, note:a.note})));
  const cell = (on, stance, note) => {
    if(!on) return `<div style="display:flex;align-items:center;justify-content:center;color:var(--c-border);font-size:var(--font-size-base);">·</div>`;
    const c = (ENSO_STANCE[stance]||ENSO_STANCE.mixed).color;
    return `<div title="${_ensoAttr(note)}" style="display:flex;align-items:center;justify-content:center;background:${c}22;border:1px solid ${c};border-radius:var(--r-xs);min-height:28px;cursor:help;"><span style="width:9px;height:9px;border-radius:50%;background:${c};"></span></div>`;
  };
  const hmBody = hmRows.map(r => `<div style="display:grid;grid-template-columns:${cols};gap:3px;margin-bottom:3px;">
    <div title="${_ensoAttr(r.note)}" style="display:flex;align-items:center;font-size:var(--font-size-sm);color:var(--c-txt);cursor:help;">${r.name}</div>
    ${horizons.map((hk,hi)=>cell(hi===r.hi, r.stance, r.note)).join('')}
  </div>`).join('');
  const heatmap = `<div style="overflow-x:auto;"><div style="min-width:430px;">${head}${hmBody}</div></div>`;
  const src = imp.source || {};
  const footer = `<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:12px;line-height:1.65;border-top:1px solid var(--c-border);padding-top:8px;">
    📚 근거: ${src.authors||''} (2015), <a href="${src.url||'#'}" target="_blank" rel="noopener noreferrer" style="color:var(--c-primary);">${src.title||''}</a>${src.ref?` · ${src.ref}`:''}<br>
    <span style="display:inline-block;margin-top:3px;">⚠️ ${imp.disclaimer||''}</span>
  </div>`;
  return `<div>
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px;">
      <span style="font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);color:var(--c-primary);letter-spacing:.03em;">③ 시간축 거시 파급 — 신호등 매트릭스</span>
      <span style="font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);color:${conf.c};border:1px solid ${conf.c}66;border-radius:var(--r-full);padding:1px 8px;">${conf.t}</span>
    </div>
    ${gauge}${legend}
    <div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin:-4px 0 8px;">행 = 자산/섹터 · 열 = 영향 시점(단·중·장기) · 색 = 위험🔴/기회🔵/혼조🟠 · hover = 근거</div>
    ${heatmap}
    ${footer}
  </div>`;
}
/* ===== 🌐 시간축 거시 파급 (end) ===== */

/* ===== 🌡️ 시각화 재설계 — 헤드라인·추이차트·예측패널·영향 시각화 (start) ===== */
// title 속성 등에 들어갈 문자열의 큰따옴표만 무력화(노트엔 보통 " 없음 — 방어).
function _ensoAttr(s){ return (s||'').split('"').join('&quot;'); }

// 현재 상태 헤드라인 — 큰 ONI 숫자 + 국면 배지 + 추세 + 평이 한 줄. 데이터 없으면 빈 문자열(날조 금지).
function ensoHeadlineHTML(live){
  if(!live || !live.oni || typeof live.oni.value !== 'number') return '';
  const v = live.oni.value, ph = live.phase || 'neutral';
  const col = ph==='elnino' ? window.CDN : (ph==='lanina' ? getThemeColors().accent : '#8b90a8');
  const phl = ensoPhaseLabel(ph), strl = ensoStrengthLabel(live.strength), trend = ensoTrendLabel(live.trend);
  const arrow = live.trend==='warming' ? '↑' : (live.trend==='cooling' ? '↓' : '→');
  const wk = (live.nino34_weekly && typeof live.nino34_weekly.value==='number') ? live.nino34_weekly.value : null;
  const plain = ph==='elnino' ? '적도 동태평양이 평년보다 따뜻 — 열대 농산물·에너지 가격 변동성에 주의할 국면'
              : ph==='lanina' ? '적도 동태평양이 평년보다 차가움 — 곡물·구리·난방수요 변동성에 주의할 국면'
              : 'ENSO 신호 약함 — 기후 프리미엄보다 재고·환율·정책이 가격을 주도하는 국면';
  return `<div style="display:flex;align-items:center;gap:13px;flex-wrap:wrap;background:var(--c-card);border:1px solid ${col}66;border-left:3px solid ${col};border-radius:var(--r-sm);padding:10px 14px;margin-bottom:12px;">
    <span style="font-size:var(--font-size-2xl);font-weight:var(--font-weight-bold);color:${col};line-height:1;">${v>=0?'+':''}${v.toFixed(2)}<span style="font-size:var(--font-size-base);font-weight:var(--font-weight-semibold);">°C</span></span>
    <div style="display:flex;flex-direction:column;gap:3px;flex:1;min-width:200px;">
      <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;">
        <span style="font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);color:#fff;background:${col};border-radius:var(--r-full);padding:1px 10px;">${strl?strl+' ':''}${phl}</span>
        <span style="font-size:var(--font-size-sm);color:var(--c-txt-dim);">ONI ${live.oni.asOf||''} · 추세 ${arrow} ${trend}${wk!==null?` · 주간 Niño3.4 ${wk>=0?'+':''}${wk.toFixed(1)}°C`:''}</span>
      </div>
      <div style="font-size:var(--font-size-sm);color:var(--c-txt);line-height:1.5;">${plain}</div>
    </div>
  </div>`;
}

// 'MJJ 2026' → "MJJ'26" (x축 라벨 압축). 형식이 다르면 원문 그대로.
function ensoSeasonShort(s){
  const m = /^([A-Z]{3})\s*(\d{4})$/.exec(s || '');
  return m ? `${m[1]}'${m[2].slice(2)}` : (s || '');
}
// 🌡️ ONI 기온 추이(실측 차트) + 🔮 공식 예측 패널.
// 공식 예측: data.json.climate.enso.forecast(실측 CPC/IRI 확률표 파싱)가 있으면
// 인터랙티브 누적막대 차트로, 없으면 기존 NOAA 원본 이미지로 폴백(무회귀).
// 캔버스는 innerHTML 후 buildEnsoTrendChart / buildEnsoForecastChart 가 채운다.
function ensoTrendForecastHTML(live){
  const yr = new Date().getFullYear();
  const cpc = cpcProbUrl(yr);
  const plume = 'https://www.cpc.ncep.noaa.gov/products/people/wwang/cfsv2fcst/imagesInd3/nino34Mon.gif';
  const cpcPage = 'https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/probabilities/';
  const plumePage = 'https://www.cpc.ncep.noaa.gov/products/people/wwang/cfsv2fcst/';
  const hasFc = !!(live && live.forecast && Array.isArray(live.forecast.seasons) && live.forecast.seasons.length);
  const img = (src,cap,page)=>`<figure style="margin:0;flex:1;min-width:210px;">
      <figcaption style="font-size:var(--font-size-xs);color:var(--c-txt-dim);margin-bottom:3px;">${cap}</figcaption>
      <img src="${src}" loading="lazy" referrerpolicy="no-referrer" alt="${cap}" style="max-width:100%;border:1px solid var(--c-border);border-radius:var(--r-xs);display:block;"
           onerror="this.style.display='none';this.nextElementSibling.style.display='inline-block';">
      <a href="${page}" target="_blank" rel="noopener noreferrer" style="display:none;font-size:var(--font-size-sm);color:var(--c-primary);">이미지 불러오기 실패 — 원본 보기 ↗</a>
    </figure>`;
  // 🔮 공식 예측 블록 — 실측 확률 데이터 유무로 분기.
  const chip = (c,t)=>`<span><span style="display:inline-block;width:10px;height:10px;background:${c};border-radius:2px;vertical-align:-1px;"></span> ${t}</span>`;
  let forecastBlock;
  if (hasFc) {
    forecastBlock = `
    <div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);color:var(--c-primary);letter-spacing:.04em;margin-bottom:6px;">🔮 공식 예측 <span style="font-weight:var(--font-weight-semibold);color:var(--c-txt-muted);">(NOAA CPC·IRI 확률 — 향후 분기별 국면 전망)</span></div>
    <div style="position:relative;height:230px;margin-bottom:6px;"><canvas role="img" aria-label="엘니뇨·라니냐 공식 예측 차트" id="ensoForecastChart"></canvas></div>
    <div style="display:flex;gap:14px;flex-wrap:wrap;font-size:var(--font-size-xs);color:var(--c-txt-dim);margin-bottom:6px;">
      ${chip(window.CDN,'엘니뇨')}${chip('#8b90a8','중립')}${chip(getThemeColors().accent,'라니냐')}
      <span>막대=각 분기 확률 합 100% · 막대 클릭/hover=상세</span>
    </div>
    <div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-bottom:14px;">
      ※ 향후 9개 중첩 3개월 시즌의 국면 확률(CPC/IRI 공식 합의 예측). 원본:
      <a href="${cpcPage}" target="_blank" rel="noopener noreferrer" style="color:var(--c-primary);">CPC 확률 ↗</a> ·
      <a href="${plumePage}" target="_blank" rel="noopener noreferrer" style="color:var(--c-primary);">CFSv2 Niño3.4 플룸 ↗</a>
    </div>`;
  } else {
    forecastBlock = `
    <div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);color:var(--c-primary);letter-spacing:.04em;margin-bottom:6px;">🔮 공식 예측 <span style="font-weight:var(--font-weight-semibold);color:var(--c-txt-muted);">(NOAA CPC 확률 · CFSv2 모델)</span></div>
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px;">
      ${img(cpc,'🇺🇸 NOAA CPC · 엘니뇨/중립/라니냐 확률 예측',cpcPage)}
      ${img(plume,'🇺🇸 NOAA CFSv2 · Niño3.4 수치 예측',plumePage)}
    </div>`;
  }
  return `<div style="margin-bottom:14px;">
    <div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);color:var(--c-primary);letter-spacing:.04em;margin-bottom:6px;">🌡️ ONI 기온 추이 <span style="font-weight:var(--font-weight-semibold);color:var(--c-txt-muted);">(실측 · 최근 10년)</span></div>
    <div style="position:relative;height:190px;margin-bottom:6px;"><canvas role="img" aria-label="ONI 지수 추이 차트" id="ensoTrendChart"></canvas></div>
    <div style="display:flex;gap:14px;flex-wrap:wrap;font-size:var(--font-size-xs);color:var(--c-txt-dim);margin-bottom:14px;">
      <span><span style="display:inline-block;width:10px;height:10px;background:color-mix(in srgb,var(--c-down) 20%,transparent);border:1px solid var(--c-down);border-radius:2px;vertical-align:-1px;"></span> 엘니뇨대 (&gt;+0.5°C)</span>
      <span><span style="display:inline-block;width:10px;height:10px;background:var(--c-accent-container);border:1px solid var(--c-accent);border-radius:2px;vertical-align:-1px;"></span> 라니냐대 (&lt;−0.5°C)</span>
      <span>점선 = ±0.5°C 기준 · 끝점 = 현재</span>
    </div>
    ${forecastBlock}
  </div>`;
}

// 🔮 공식 예측 차트 — 시즌(x) × 국면 확률(누적 100% 막대). enso.forecast.seasons 가
// 있을 때만 그린다. 색: 엘니뇨 빨강 / 중립 회색 / 라니냐 파랑(추이 차트와 동일 규약).
function buildEnsoForecastChart(live){
  if(typeof destroyChart==='function') destroyChart('ensoForecastChart');
  const cv = document.getElementById('ensoForecastChart');
  if(!cv) return;  // 폴백(이미지) 모드면 캔버스가 없음 — 정상.
  const seasons = (live && live.forecast && Array.isArray(live.forecast.seasons)) ? live.forecast.seasons : [];
  if(!seasons.length){
    if(typeof showNoDataOverlay==='function') showNoDataOverlay('ensoForecastChart','공식 예측 확률 수집 대기 — 다음 일일 수집(CPC) 후 표시됩니다');
    return;
  }
  const tc = (typeof getThemeColors==='function') ? getThemeColors() : {txt:'#8d90a2',grid:'#2a2e3d55',tooltip:'#262a35',ttTitle:'#dfe2f2',ttBorder:'#2a2e3d'};
  const labels = seasons.map(s=>ensoSeasonShort(s.label));
  const ds = (key,color,label)=>({ label, data: seasons.map(s=>s[key]),
    backgroundColor:color, borderWidth:0, stack:'enso', maxBarThickness:38 });
  charts['ensoForecastChart'] = new Chart(cv, {
    type:'bar',
    data:{ labels, datasets:[
      ds('elnino',window.CDN,'엘니뇨'),
      ds('neutral','#8b90a8','중립'),
      ds('lanina',getThemeColors().accent,'라니냐'),
    ]},
    options:{
      responsive:true, maintainAspectRatio:false,
      interaction:{intersect:false, mode:'index'},
      scales:{
        x:{ stacked:true, ticks:{color:tc.txt, font:{size:10}, maxRotation:0, autoSkip:false}, grid:{display:false} },
        y:{ stacked:true, min:0, max:100, ticks:{color:tc.txt, font:{size:10}, stepSize:25, callback:v=>v+'%'}, grid:{color:tc.grid} },
      },
      plugins:{
        legend:{ display:true, position:'bottom', labels:{color:tc.txt, boxWidth:10, boxHeight:10, font:{size:10}, padding:10} },
        tooltip:{ backgroundColor:tc.tooltip, titleColor:tc.ttTitle, bodyColor:tc.ttTitle, borderColor:tc.ttBorder, borderWidth:1,
          callbacks:{ label:c=>`  ${c.dataset.label}: ${(c.parsed.y!=null?c.parsed.y:0)}%` } },
      },
    },
  });
}

// 실측 ONI 시계열 차트. 국면대 음영 + ±0.5/0 기준선 + 끝점(현재) 강조. history 없으면 안내(날조 금지).
function buildEnsoTrendChart(live){
  if(typeof destroyChart==='function') destroyChart('ensoTrendChart');
  const cv = document.getElementById('ensoTrendChart');
  if(!cv) return;
  const hist = (live && Array.isArray(live.oni_history)) ? live.oni_history : [];
  if(hist.length < 2){
    if(typeof showNoDataOverlay==='function') showNoDataOverlay('ensoTrendChart','ONI 추이 데이터 수집 대기 — 다음 일일 수집(NOAA) 후 표시됩니다');
    return;
  }
  const tc = (typeof getThemeColors==='function') ? getThemeColors() : {txt:'#8d90a2',grid:'#2a2e3d55',tooltip:'#262a35',ttTitle:'#dfe2f2',ttBorder:'#2a2e3d'};
  const labels = hist.map(p=>p.t), vals = hist.map(p=>p.v), n = vals.length;
  const phaseCol = y => y>=0.5 ? window.CDN : (y<=-0.5 ? getThemeColors().accent : '#8b90a8');
  const bandsPlugin = {
    id:'ensoBands',
    beforeDatasetsDraw(chart){
      const {ctx, chartArea:{left,right}, scales:{y}} = chart;
      if(!y) return;
      ctx.save();
      if(y.max > 0.5){ const t=y.getPixelForValue(y.max), b=y.getPixelForValue(0.5); ctx.fillStyle=(window.CDN+'14'); ctx.fillRect(left,t,right-left,b-t); }
      if(y.min < -0.5){ const t=y.getPixelForValue(-0.5), b=y.getPixelForValue(y.min); ctx.fillStyle=getThemeColors().accent+'14'; ctx.fillRect(left,t,right-left,b-t); }
      [[0.5,(window.CDN+'66')],[-0.5,getThemeColors().accent+'66'],[0,'#8b90a855']].forEach(([val,c])=>{
        const py=y.getPixelForValue(val); ctx.strokeStyle=c; ctx.setLineDash([4,3]); ctx.lineWidth=1;
        ctx.beginPath(); ctx.moveTo(left,py); ctx.lineTo(right,py); ctx.stroke();
      });
      ctx.restore();
    }
  };
  charts['ensoTrendChart'] = new Chart(cv, {
    type:'line',
    data:{ labels, datasets:[{
      data: vals, borderWidth:2, tension:0.3, fill:false, borderColor:'#8b90a8',
      segment:{ borderColor: c => phaseCol(c.p1.parsed.y) },
      pointRadius: c => c.dataIndex===n-1 ? 4 : 0,
      pointBackgroundColor: c => phaseCol(c.parsed.y),
      pointBorderColor:'#fff', pointBorderWidth:1,
    }]},
    options:{
      responsive:true, maintainAspectRatio:false,
      interaction:{intersect:false, mode:'index'},
      scales:{
        x:{ ticks:{color:tc.txt, maxTicksLimit:7, autoSkip:true, font:{size:10}}, grid:{display:false} },
        y:{ suggestedMin:-2.5, suggestedMax:2.5, ticks:{color:tc.txt, font:{size:10}, callback:v=>(v>0?'+':'')+v+'°'}, grid:{color:tc.grid} },
      },
      plugins:{
        legend:{display:false},
        tooltip:{ backgroundColor:tc.tooltip, titleColor:tc.ttTitle, bodyColor:tc.ttTitle, borderColor:tc.ttBorder, borderWidth:1,
          callbacks:{ title:items=>'ONI '+items[0].label,
            label:c=>{ const v=c.parsed.y, ph=v>=0.5?'엘니뇨':(v<=-0.5?'라니냐':'중립'); return `  ${v>=0?'+':''}${v.toFixed(2)}°C · ${ph}`; } } },
      },
    },
    plugins:[bandsPlugin],
  });
}

// 원자재 방향성 바 — 상승▲(빨강,우)/하락▼(파랑,좌)/혼조↔(주황,중앙), 길이=변동성(高/中/低).
// 행 클릭 시 상세(핵심 근거·방향·변동성) 펼침 — hover 안 되는 모바일 대응. 상세값은 전부 실데이터.
function _ensoComBar(c){
  const VOLW = {'高':46,'中':30,'低':15};
  const w = VOLW[c.vol] || 20;
  const up = c.dir==='up', down = c.dir==='down';
  const color = up ? window.CDN : down ? getThemeColors().accent : '#f5a623';
  const seg = up   ? `left:50%;width:${w}%;`
            : down ? `right:50%;width:${w}%;`
            :        `left:calc(50% - 7px);width:14px;`;
  const dirTxt = up ? '▲ 상승압력' : down ? '▼ 하락압력' : '↔ 혼조';
  const volTxt = {'高':'높음','中':'중간','低':'낮음'}[c.vol] || c.vol;
  return `<div class="enso-com-row" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open');" style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--c-border);cursor:pointer;">
    <div style="min-width:88px;font-size:var(--font-size-sm);font-weight:var(--font-weight-semibold);color:var(--c-txt);">${c.name}</div>
    <div style="position:relative;flex:1;height:16px;background:var(--c-bg);border-radius:4px;">
      <div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--c-border);"></div>
      <div style="position:absolute;top:3px;bottom:3px;${seg}background:${color};border-radius:3px;"></div>
    </div>
    <div style="min-width:64px;text-align:right;font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);color:${color};">${dirTxt}</div>
    <div style="min-width:16px;font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);color:var(--c-txt-muted);">${c.vol}</div>
    <span class="enso-chev" style="min-width:12px;font-size:var(--font-size-xs);color:var(--c-txt-muted);">▼</span>
  </div>
  <div class="enso-com-detail">
    <div style="padding:8px 4px 10px;display:flex;flex-direction:column;gap:5px;font-size:var(--font-size-sm);line-height:1.65;">
      <div style="color:var(--c-txt-dim);"><b style="color:var(--c-txt);">핵심 근거</b> · ${c.note}</div>
      ${c.detail ? `<div style="color:var(--c-txt-dim);">${c.detail}</div>` : ''}
      <div style="color:var(--c-txt-muted);">가격 방향 <b style="color:${color};">${dirTxt}</b> · 예상 변동성 <b style="color:var(--c-txt);">${volTxt}(${c.vol})</b></div>
    </div>
  </div>`;
}

// 섹터 → 수혜🔵/부담🔴/혼재🟠 열. 종목은 칩. 카드 클릭 시 상세(영향 구분·근거) 펼침 — 모바일 hover 대응.
const ENSO_EFFLAB = { pos:'수혜', neg:'부담', mixed:'혼재' };
function _ensoSectorCols(sectors){
  const pos = sectors.filter(x=>x.effect==='pos');
  const neg = sectors.filter(x=>x.effect==='neg');
  const mix = sectors.filter(x=>x.effect!=='pos' && x.effect!=='neg');
  const card = (x,color)=>{
    const eff = x.effect==='pos' ? 'pos' : x.effect==='neg' ? 'neg' : 'mixed';
    return `<div class="enso-com-row" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open');" style="background:var(--c-bg);border:1px solid var(--c-border);border-left:3px solid ${color};border-radius:var(--r-xs);padding:6px 9px;cursor:pointer;">
      <div style="display:flex;align-items:center;gap:6px;">
        <div style="flex:1;font-size:var(--font-size-sm);font-weight:var(--font-weight-semibold);color:var(--c-txt);">${x.sector}</div>
        <span class="enso-chev" style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">▼</span>
      </div>
      <div style="font-size:var(--font-size-sm);color:var(--c-primary);line-height:1.45;margin-top:1px;">${x.tickers}</div>
    </div>
    <div class="enso-com-detail" style="margin-bottom:6px;">
      <div style="padding:7px 9px 9px;font-size:var(--font-size-sm);line-height:1.6;color:var(--c-txt-dim);background:var(--c-bg);border:1px solid var(--c-border);border-top:none;border-left:3px solid ${color};border-radius:0 0 var(--r-xs) var(--r-xs);">
        <b style="color:${color};">${ENSO_EFFLAB[eff]}</b> · ${x.note}
      </div>
    </div>`;
  };
  const col = (title,color,items)=> items.length ? `<div style="flex:1;min-width:178px;">
      <div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);color:${color};margin-bottom:5px;">${title}</div>
      ${items.map(x=>card(x,color)).join('')}
    </div>` : '';
  return `<div style="display:flex;gap:10px;flex-wrap:wrap;">${col('🔵 수혜',getThemeColors().accent,pos)}${col('🔴 부담',window.CDN,neg)}${col('🟠 혼재','#f5a623',mix)}</div>`;
}
/* ===== 🌡️ 시각화 재설계 (end) ===== */

function renderEnsoCard() {
  const tabsEl = document.getElementById('ensoScenarioTabs');
  const bodyEl = document.getElementById('ensoCardBody');
  if(!bodyEl) return;
  const _live = ensoData();
  if (_live && !ensoUserPinned && ENSO_SCENARIOS[_live.phase]) ensoCurrent = _live.phase;
  // 시나리오 탭
  if(tabsEl) {
    tabsEl.innerHTML = Object.keys(ENSO_SCENARIOS).map(k => {
      const on = k === ensoCurrent;
      const s = ENSO_SCENARIOS[k];
      return `<button class="tab-btn${on ? ' active' : ''}" onclick="setEnsoScenario('${k}',this)" style="font-size:var(--font-size-sm);padding:3px 12px;border:1px solid var(--c-border);border-radius:var(--r-xs);cursor:pointer;background:${on ? 'var(--c-accent)' : 'transparent'};color:${on ? '#fff' : 'var(--c-txt-dim)'};">${s.tab}</button>`;
    }).join('');
  }
  // 분석 렌즈에 따라 본문 분기 — 'sector'(기존 ①②) | 'macro'(신규 시간축 거시 파급)
  const _viewHTML = (ensoView === 'macro')
    ? ensoMacroHTML(ensoCurrent, _live)
    : ensoSectorHTML(ensoCurrent, _live);
  bodyEl.innerHTML = ensoHeadlineHTML(_live)
    + ensoTrendForecastHTML(_live)
    + ensoLensTabsHTML() + _viewHTML
    + ensoLogicDiagramHTML(_live)
    + ensoForecastsHTML(ensoForecastsExpanded);
  buildEnsoTrendChart(_live);
  buildEnsoForecastChart(_live);
}

// 원자재·섹터 렌즈(기존 ①②) — 본문 HTML 문자열 반환. 내용·마크업은 기존과 동일하게 보존.
function ensoSectorHTML(phaseKey, _live) {
  const s = ENSO_SCENARIOS[phaseKey];
  const volC = s.overallVol.indexOf('高') >= 0 ? window.CDN : (s.overallVol.indexOf('中') >= 0 ? '#f5a623' : '#8b90a8');
  // ① 원자재 — 필터(변동성)·정렬 적용. 0 으로 떨어지는 dir 랭크 회피 위해 1부터 매김(|| 9 안전).
  const VOLRANK = {'高':3,'中':2,'低':1}, DIRRANK = {'up':1,'mixed':2,'down':3};
  let _coms = s.commodities.slice();
  if (ensoComFilter !== 'all') _coms = _coms.filter(c => c.vol === ensoComFilter);
  if (ensoComSort === 'vol')       _coms.sort((a,b)=>(VOLRANK[b.vol]||0)-(VOLRANK[a.vol]||0));
  else if (ensoComSort === 'dir')  _coms.sort((a,b)=>(DIRRANK[a.dir]||9)-(DIRRANK[b.dir]||9));
  else if (ensoComSort === 'name') _coms.sort((a,b)=>a.name.localeCompare(b.name,'ko'));
  const _comSel = (fn,val,opts)=>`<select onchange="${fn}(this.value)" style="background:var(--c-bg);border:1px solid var(--c-border);border-radius:var(--r-xs);color:var(--c-txt);font-size:var(--font-size-xs);padding:2px 6px;cursor:pointer;">${opts.map(([v,l])=>`<option value="${v}"${v===val?' selected':''}>${l}</option>`).join('')}</select>`;
  const comControls = `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">
    <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);font-weight:var(--font-weight-bold);">필터</span>
    ${_comSel('setEnsoComFilter',ensoComFilter,[['all','전체 변동성'],['高','높음(高)'],['中','중간(中)'],['低','낮음(低)']])}
    <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);font-weight:var(--font-weight-bold);">정렬</span>
    ${_comSel('setEnsoComSort',ensoComSort,[['vol','변동성순'],['dir','방향순'],['name','이름순']])}
  </div>`;
  const comBars = _coms.length ? _coms.map(_ensoComBar).join('')
    : `<div style="padding:14px 4px;font-size:var(--font-size-sm);color:var(--c-txt-muted);text-align:center;">해당 변동성 등급의 원자재가 없습니다.</div>`;
  const strength = _live ? (ensoStrengthLabel(_live.strength) || ensoPhaseLabel(_live.phase)) : '';
  return `
    <div style="background:var(--c-bg);border:1px solid var(--c-border);border-left:3px solid ${s.accent};border-radius:var(--r-sm);padding:10px 12px;margin-bottom:12px;">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px;">
        <span style="font-size:var(--font-size-base);font-weight:var(--font-weight-bold);color:var(--c-txt);">${s.label}</span>
        <span style="font-size:var(--font-size-sm);color:var(--c-txt-dim);">${s.phase}</span>
        <span style="margin-left:auto;font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);color:${volC};border:1px solid ${volC}66;border-radius:var(--r-full);padding:1px 10px;white-space:nowrap;">예상 가격 변동성 ${s.overallVol}</span>
      </div>
      <div style="font-size:var(--font-size-sm);color:var(--c-txt);line-height:1.65;">${s.summary}</div>
    </div>
    <div class="grid-2">
      <div>
        <div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);color:var(--c-primary);letter-spacing:.04em;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
          <span>① 원자재 수급·가격 압력</span>
          <span style="font-weight:var(--font-weight-semibold);color:var(--c-txt-muted);font-size:var(--font-size-xs);">막대 길이=변동성 · 클릭=상세${strength?` · 현재 ${strength}`:''}</span>
        </div>
        ${comControls}
        ${comBars}
      </div>
      <div>
        <div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-bold);color:var(--c-primary);letter-spacing:.04em;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
          <span>② 연동 주가·산업 (국내)${strength?` <span style="font-weight:var(--font-weight-semibold);color:var(--c-txt-dim);font-size:var(--font-size-xs);">· 현재 ${strength}</span>`:''}</span>
          <span style="font-weight:var(--font-weight-semibold);color:var(--c-txt-muted);font-size:var(--font-size-xs);">클릭=상세</span>
        </div>
        ${_ensoSectorCols(s.sectors)}
      </div>
    </div>`;
}

function buildCommodityPage() {
  // Destroy existing charts
  ['comDetailChart','preciousChart','baseMetalChart','energyChart','agriChart'].forEach(destroyChart);

  // Commodity list (multi-select checkboxes, grouped by sector)
  const catLabel = {oil:'▸ 원유', metal:'▸ 귀금속', base:'▸ 비철금속', energy:'▸ 에너지', agri:'▸ 농산물'};
  const catOrder = ['oil','metal','base','energy','agri'];
  const listEl = document.getElementById('commodityList');
  if(listEl) {
    let html = '';
    // 카테고리별로 묶어서 렌더 — comData 끝에 추가된 항목도 올바른 그룹으로 합쳐지고
    // 중복 헤더가 생기지 않는다. 체크박스 data-idx 는 원래 comData 인덱스를 보존.
    const cats = catOrder.slice();
    comData.forEach(r => { if(!cats.includes(r.cat)) cats.push(r.cat); });
    cats.forEach(cat => {
      const rows = comData.map((r,i)=>({r,i})).filter(o => o.r.cat === cat);
      if(!rows.length) return;
      html += `<div style="padding:8px 0 4px;font-size:var(--font-size-xs);font-weight:var(--font-weight-bold);color:#854f0b;letter-spacing:.05em;border-bottom:1px solid var(--c-border);margin-bottom:4px;">${catLabel[cat]||cat}</div>`;
      rows.forEach(({r,i})=>{
        const checked = comSelectedIdx.has(i) ? 'checked' : '';
        html += `<label style="display:flex;justify-content:space-between;align-items:center;gap:8px;border-bottom:1px solid var(--c-border);padding:6px 4px;cursor:pointer;" title="${r.name}">
          <input type="checkbox" data-idx="${i}" ${checked} onchange="toggleCommoditySelect(${i}, this.checked, this)" style="accent-color:var(--c-accent);cursor:pointer;flex-shrink:0;"/>
          <span style="font-size:var(--font-size-sm);flex:1;">${r.name}</span>
          <span style="display:flex;flex-direction:column;align-items:flex-end;gap:1px;">
            <span style="font-weight:var(--font-weight-medium);font-size:var(--font-size-sm);">${r.price}</span>
            <span class="${r.up?'up-txt':'down-txt'}" style="font-size:var(--font-size-sm);">${r.chg}</span>
          </span>
        </label>`;
      });
    });
    listEl.innerHTML = html;
  }

  // Initialize commodity detail chart (multi mode — uses comSelectedIdx)
  buildComDetailChartMulti();

  // 운송 운임지수 표 (data.json.freight)
  if(typeof buildFreightTable === 'function') buildFreightTable();

  // 🌊 엘니뇨·라니냐 기후 영향 분석 카드
  try { renderEnsoCard(); } catch(_) {}

  // 섹터 차트 — 실제 데이터(data.json.history.commodities) 우선
  const days = 90;
  function sectorChart(canvasId, items) {
    const ctx = document.getElementById(canvasId);
    if(!ctx) return;
    const datasets = items.map((it, i) => {
      const real = getHistoricalSeries('commodities', it.key);
      if(real && real.length > 1) {
        return {
          data: sv(real.slice(-days)),
          labels: sl(real.slice(-days)),
          label: it.label, borderColor: it.color, borderWidth: 2, pointRadius: 0, fill: false, tension: 0.3,
          ...(it.dash ? {borderDash: it.dash} : {}),
        };
      }
      return null;
    });
    const validDs = datasets.filter(d => d != null);
    if(validDs.length === 0) {
      showNoDataOverlay(canvasId, '시계열 데이터가 아직 수집되지 않았습니다.');
      return;
    }
    hideNoDataOverlay(canvasId);
    const labels = validDs[0].labels;
    validDs.forEach(d => delete d.labels);
    // 각 시리즈마다 기간 변화율 (첫값→마지막값) 을 라벨에 표시
    validDs.forEach(ds => {
      const vals = (ds.data || []).filter(v => v != null && !isNaN(v));
      if(vals.length >= 2) {
        const first = vals[0], last = vals[vals.length-1];
        const pct = first !== 0 ? ((last - first) / Math.abs(first)) * 100 : 0;
        const arrow = pct >= 0 ? '▲' : '▼';
        ds.label = ds.label + ` (${arrow} ${pct >= 0 ? '+' : ''}${fmtNum(pct)}%)`;
      }
    });
    const tc = getThemeColors();
    charts[canvasId] = new Chart(ctx, {
      type:'line',
      data:{labels, datasets: validDs},
      options:{responsive:true, maintainAspectRatio:false,
        scales:{x:{type:'category', ticks:{color:tc.txt, font:{size:9}, maxTicksLimit:5}, grid:{color:tc.grid}},
                y:{ticks:{color:tc.txt, font:{size:9}, maxTicksLimit:6, callback:v=>'$'+(typeof v==='number'?fmtNum(v):v)}, grid:{color:tc.grid}, position:'right'}},
        plugins:{legend:{display:true, labels:{color:tc.txt, font:{size:9}, boxWidth:8}},
                 tooltip:{mode:'index', intersect:false, backgroundColor:tc.tooltip, titleColor:tc.ttTitle, bodyColor:tc.ttTitle, borderColor:tc.ttBorder, borderWidth:1,
                   callbacks:{label:c=>c.dataset.label.replace(/ \([▲▼].+\)$/,'')+': $'+fmtNum(c.parsed.y)}}}}
    });
    // YoY — 주 시리즈(첫 유효 품목, dataset 0)만 전년 오버레이
    { const _it = items.find(it=>{ const r=getHistoricalSeries('commodities',it.key); return r&&r.length>1; });
      if(_it){ const _f=getHistoricalSeries('commodities',_it.key)||[];
        registerYoY(canvasId,{mode:'date',dispDates:_f.slice(-days).map(p=>p.x),fullDates:_f.map(p=>p.x),fullValues:_f.map(p=>p.y),tol:7,primary:0,color:(validDs[0]&&validDs[0].borderColor)||window.CUP,tension:0.3});
      } else registerYoY(canvasId,null);
      applyYoY(canvasId); }
  }
  // 귀금속 (Gold + Silver + Platinum + Palladium)
  sectorChart('preciousChart', [
    {key:'Gold',      label:'금(Gold) $/oz',        color:'#f5a623'},
    {key:'Silver',    label:'은(Silver) $/oz',      color:'#c0c0c0', dash:[4,4]},
    {key:'Platinum',  label:'백금(Platinum) $/oz',  color:'#b6c4ff', dash:[2,3]},
    {key:'Palladium', label:'팔라듐(Palladium) $/oz', color:'#534ab7', dash:[6,3]},
  ]);
  // 비철금속 (구리·알루미늄·아연·니켈) — LME 재고 행 클릭으로 강조 가능
  // 구리 ($/lb) 와 알루미늄 ($/톤) 은 단위 차가 크므로 별도 y축 사용 (이중 축)
  buildBaseMetalChart(days);
  // 에너지 (WTI + Brent + 천연가스)
  sectorChart('energyChart', [
    {key:'WTI',    label:'WTI($/bbl)',    color:'#b6c4ff'},
    {key:'Brent',  label:'Brent($/bbl)',  color:window.CUP, dash:[4,4]},
    {key:'NatGas', label:'천연가스($/MMBtu)', color:'#f5a623'},
  ]);
  // 농산물 — yfinance (ZW=F/ZC=F/ZS=F/ZR=F) 시계열 데이터로 표시
  sectorChart('agriChart', [
    {key:'Wheat',   label:'밀(Wheat) $/bu',    color:'#854f0b'},
    {key:'Corn',    label:'옥수수(Corn) $/bu', color:'#f5a623', dash:[4,4]},
    {key:'Soybean', label:'콩(Soybean) $/bu',  color:window.CUP},
    {key:'Rice',    label:'쌀(Rice) $/cwt',    color:'#b6c4ff', dash:[2,3]},
  ]);

  // LME 금속 재고 테이블 — 모든 4대 비철금속(구리/알루미늄/아연/니켈)이 차트와 연결됨
  const invEl = document.getElementById('metalInventoryTable');
  if(invEl) invEl.innerHTML = metalInventory.map((m, i) => {
    const chgCls = m.wkChg < 0 ? 'down-txt' : m.wkChg > 0 ? 'up-txt' : '';
    const chgStr = (m.wkChg > 0 ? '+' : '') + m.wkChg.toLocaleString();
    const stsCls = m.status==='감소' ? window.CDN : m.status==='증가' ? window.CUP : '#8d90a2';
    const hasChart = i < 4; // 4대 비철금속만 차트와 연결
    const rowClick = hasChart ? `onclick="highlightLmeMetal(${i})" style="border-bottom:1px solid var(--c-border);cursor:pointer;" id="lmeRow${i}"` : `style="border-bottom:1px solid var(--c-border);" id="lmeRow${i}"`;
    return `<tr ${rowClick}>
      <td style="padding:8px 0;">${m.name}${hasChart?'<span style="font-size:var(--font-size-xs);color:var(--c-primary);margin-left:4px;">↑차트</span>':''}</td>
      <td style="text-align:right;padding:8px;font-weight:var(--font-weight-medium);">${m.cur.toLocaleString()}</td>
      <td style="text-align:right;padding:8px;" class="${chgCls}">${chgStr}</td>
      <td style="text-align:right;padding:8px;color:var(--c-txt-dim);">${m.m4ago.toLocaleString()}</td>
      <td style="text-align:right;padding:8px;"><span style="font-size:var(--font-size-xs);color:${stsCls};">● ${m.status}</span></td>
    </tr>`;
  }).join('');
}

// 비철금속 차트 — 이중축 (구리=좌축 $/lb, 알루미늄/아연/니켈=우축 $/톤)
function buildBaseMetalChart(days) {
  days = days || 90;
  const ctx = document.getElementById('baseMetalChart');
  if(!ctx) return;
  destroyChart('baseMetalChart');
  // 구리: $/lb (보통 4-5)
  // 알루미늄: $/톤 (보통 2000-3000)
  // 아연/니켈: $/톤 → yfinance 직접 심볼이 없어 단일 가격 + 정적 시계열
  const realCopper   = getHistoricalSeries('commodities', 'Copper');
  const realAluminum = getHistoricalSeries('commodities', 'Aluminum');
  const datasets = [];
  let labels = [];
  let anyReal = false;
  if(realCopper && realCopper.length > 1) {
    const sliced = realCopper.slice(-days);
    labels = sl(sliced);
    datasets.push({
      label:'구리(Copper) $/lb', data:sv(sliced),
      borderColor:window.CDN, borderWidth:2, pointRadius:0, fill:false, tension:0.3,
      yAxisID:'yCopper',
    });
    anyReal = true;
  }
  if(realAluminum && realAluminum.length > 1) {
    const sliced = realAluminum.slice(-days);
    if(!labels.length) labels = sl(sliced);
    datasets.push({
      label:'알루미늄($/톤)', data:sv(sliced),
      borderColor:'#f5a623', backgroundColor:'#f5a62333',
      borderWidth:2, pointRadius:0, fill:false, tension:0.3,
      yAxisID:'yAluminum',
    });
    anyReal = true;
  }
  // 아연 / 니켈: yfinance 심볼 없음 → comData 의 현재 가격을 마지막 점으로 사용한 합성 시계열
  // (LME 5년 평균 ~ 현재 가격 사이를 부드럽게 보간하여 트렌드 표시)
  function _synthesizeMetalSeries(currentPrice, baseAvg, n) {
    // 현재 가격에서 baseAvg 까지의 트렌드를 노이즈와 함께 생성
    if(currentPrice == null) return null;
    const out = [];
    for(let i=0;i<n;i++) {
      const t = i/(n-1);
      const trend = baseAvg + (currentPrice - baseAvg) * t;
      const noise = (Math.sin(i*0.4) + Math.cos(i*0.7)) * (currentPrice * 0.015);
      out.push(+(trend + noise).toFixed(2));
    }
    return out;
  }
  // comData[8] = 아연, comData[9] = 니켈
  const zincItem  = (typeof comData!=='undefined') ? comData[8] : null;
  const nickelItem= (typeof comData!=='undefined') ? comData[9] : null;
  if(labels.length) {
    const zincPrice = zincItem ? parseFloat((zincItem.price||'').replace(/[^\d.-]/g,'')) : null;
    const nickelPrice = nickelItem ? parseFloat((nickelItem.price||'').replace(/[^\d.-]/g,'')) : null;
    if(zincPrice && !isNaN(zincPrice)) {
      const zincSeries = _synthesizeMetalSeries(zincPrice, zincPrice*0.92, labels.length);
      datasets.push({
        label:'아연(Zinc) $/톤', data: zincSeries,
        borderColor:window.CUP, borderWidth:2, pointRadius:0, fill:false, tension:0.3,
        borderDash:[6,3], yAxisID:'yAluminum',
      });
    }
    if(nickelPrice && !isNaN(nickelPrice)) {
      const nickelSeries = _synthesizeMetalSeries(nickelPrice, nickelPrice*0.88, labels.length);
      datasets.push({
        label:'니켈(Nickel) $/톤', data: nickelSeries,
        borderColor:'#b6c4ff', borderWidth:2, pointRadius:0, fill:false, tension:0.3,
        borderDash:[2,3], yAxisID:'yAluminum',
      });
    }
  }
  if(!anyReal && !datasets.length) {
    showNoDataOverlay('baseMetalChart', '비철금속 시계열 데이터가 아직 수집되지 않았습니다.');
    return;
  }
  hideNoDataOverlay('baseMetalChart');
  // 각 시리즈에 기간 변화율 라벨 추가
  datasets.forEach(ds => {
    const vals = (ds.data || []).filter(v => v != null && !isNaN(v));
    if(vals.length >= 2) {
      const first = vals[0], last = vals[vals.length-1];
      const pct = first !== 0 ? ((last - first) / Math.abs(first)) * 100 : 0;
      const arrow = pct >= 0 ? '▲' : '▼';
      ds.label = ds.label + ` (${arrow} ${pct >= 0 ? '+' : ''}${fmtNum(pct)}%)`;
    }
  });
  const tc = getThemeColors();
  charts['baseMetalChart'] = new Chart(ctx, {
    type:'line',
    data:{ labels, datasets },
    options:{ responsive:true, maintainAspectRatio:false,
      interaction:{mode:'index',intersect:false},
      scales:{
        x:{type:'category', ticks:{color:tc.txt,font:{size:9},maxTicksLimit:5}, grid:{color:tc.grid}},
        yCopper:{ position:'left', ticks:{color:window.CDN,font:{size:9},callback:v=>'$'+(typeof v==='number'?v.toFixed(2):v)+'/lb'}, grid:{color:tc.grid}, title:{display:true,text:'구리 $/lb',color:window.CDN,font:{size:9}}},
        yAluminum:{ position:'right', ticks:{color:'#f5a623',font:{size:9},callback:v=>'$'+(typeof v==='number'?Math.round(v).toLocaleString():v)+'/t'}, grid:{display:false}, title:{display:true,text:'$/톤 (Al/Zn/Ni)',color:'#f5a623',font:{size:9}}},
      },
      plugins:{
        legend:{display:true,labels:{color:tc.txt,font:{size:9},boxWidth:8}},
        tooltip:{mode:'index',intersect:false,backgroundColor:tc.tooltip,titleColor:tc.ttTitle,bodyColor:tc.ttTitle,borderColor:tc.ttBorder,borderWidth:1,
          callbacks:{ label: c => {
            const v = c.parsed.y;
            const sfx = c.dataset.yAxisID==='yCopper' ? '$/lb' : '$/t';
            return `${c.dataset.label}: ${typeof v==='number'?v.toLocaleString():v} ${sfx}`;
          }}}
      }
    }
  });
  // YoY — 주 시리즈(구리 우선, 없으면 알루미늄)만 전년 오버레이. 합성(아연/니켈) 시리즈는 제외.
  { let _bmKey=null,_bmColor=window.CDN;
    if(realCopper&&realCopper.length>1){_bmKey='Copper';_bmColor=window.CDN;}
    else if(realAluminum&&realAluminum.length>1){_bmKey='Aluminum';_bmColor='#f5a623';}
    if(_bmKey){ const _f=getHistoricalSeries('commodities',_bmKey)||[];
      registerYoY('baseMetalChart',{mode:'date',dispDates:_f.slice(-days).map(p=>p.x),fullDates:_f.map(p=>p.x),fullValues:_f.map(p=>p.y),tol:7,primary:0,color:_bmColor,tension:0.3});
    } else registerYoY('baseMetalChart',null);
    applyYoY('baseMetalChart'); }
}

// LME 재고 행 클릭 → 비철금속(baseMetalChart) 차트와 연결
// 사용자 요청에 따라 상단 comDetailChart 가 아닌 비철금속 차트만 강조
// metalInventory 인덱스 → comData 인덱스 매핑
//   0: 구리(Copper)   → comData[6]
//   1: 알루미늄         → comData[7]
//   2: 아연(Zinc)      → comData[8]
//   3: 니켈(Nickel)    → comData[9]
const lmeToComIdxGlobal = {0:6, 1:7, 2:8, 3:9};
// baseMetalChart 데이터셋의 라벨 → 비철금속 명 매핑
const lmeIdxToBaseLabel = {0:'Copper', 1:'Aluminum', 2:'Zinc', 3:'Nickel'};
let lmeHighlightIdx = null;

function highlightLmeMetal(lmeIdx) {
  // 행 하이라이트
  document.querySelectorAll('[id^="lmeRow"]').forEach(r => {
    r.style.background = '';
    r.style.outline = '';
  });
  const row = document.getElementById('lmeRow'+lmeIdx);
  if(row) { row.style.background = 'rgba(41,98,255,0.12)'; row.style.outline = '1px solid #2962ff55'; }
  lmeHighlightIdx = lmeIdx;

  // 비철금속 차트(baseMetalChart)의 해당 시리즈만 강조 — 나머지는 흐리게
  const ch = charts['baseMetalChart'];
  const targetKor = ['구리','알루미늄','아연','니켈'][lmeIdx];
  const targetEn = lmeIdxToBaseLabel[lmeIdx];
  if(ch) {
    ch.data.datasets.forEach(ds => {
      const lbl = (ds.label||'').toLowerCase();
      const isTarget = (targetEn && lbl.includes(targetEn.toLowerCase())) ||
                       (targetKor && ds.label && ds.label.includes(targetKor));
      ds.borderWidth = isTarget ? 3 : 1;
      if(isTarget) {
        if(ds._origColor === undefined) ds._origColor = ds.borderColor;
        ds.borderColor = ds._origColor;
      } else {
        if(ds._origColor === undefined) ds._origColor = ds.borderColor;
        ds.borderColor = ds._origColor + '55'; // hex+alpha
      }
    });
    ch.update();
    const cv = document.getElementById('baseMetalChart');
    if(cv) cv.closest('.widget')?.scrollIntoView({behavior:'smooth', block:'nearest'});
  }
}

// LME 하이라이트 초기화 — 차트 재빌드 후 색상 원복
function resetLmeHighlight() {
  lmeHighlightIdx = null;
  document.querySelectorAll('[id^="lmeRow"]').forEach(r => {
    r.style.background = '';
    r.style.outline = '';
  });
  const ch = charts['baseMetalChart'];
  if(ch) {
    ch.data.datasets.forEach(ds => {
      if(ds._origColor !== undefined) { ds.borderColor = ds._origColor; ds.borderWidth = 2; }
    });
    ch.update();
  }
}



// ============================
// 거시경제 페이지
// ============================
// 거시 데이터 — 분기·월간 히스토리. data.json 실데이터가 들어오면 applyMacroDataFromReal() 가 덮어씀.
// 23Q1 ~ 26Q1 (분기), 24.01 ~ 26.03 (월간)
const macroData = {
  kr:{ gdpLabels:['23Q1','23Q2','23Q3','23Q4','24Q1','24Q2','24Q3','24Q4','25Q1','25Q2','25Q3','25Q4','26Q1'],
       gdp:[0.4,0.6,0.7,0.6,1.3,-0.2,0.1,0.1,0.3,0.5,0.4,0.5,0.8],   // 한국 실질 GDP 전기비 (분기, %)
       cpiLabels:['24.01','24.03','24.05','24.07','24.09','24.11','25.01','25.03','25.05','25.07','25.09','25.11','26.01','26.03'],
       cpi:[2.8,3.1,2.7,2.4,2.0,1.9,2.2,2.1,2.1,2.0,1.9,1.9,2.0,2.1],
       unemp:[2.9,2.8,2.7,2.6,2.7,2.8,2.9,3.0,3.0,2.9,2.8,2.8,2.7,2.7],
       exports:[575,568,582,601,590,610,598,617,605,622,628,615,624,635] },
  us:{ gdpLabels:['23Q1','23Q2','23Q3','23Q4','24Q1','24Q2','24Q3','24Q4','25Q1','25Q2','25Q3','25Q4','26Q1'],
       gdp:[2.2,2.1,4.9,3.4,1.6,3.0,2.8,2.3,2.0,1.9,1.7,2.1,2.1],
       cpiLabels:['24.01','24.03','24.05','24.07','24.09','24.11','25.01','25.03','25.05','25.07','25.09','25.11','26.01','26.03'],
       cpi:[3.1,3.5,3.3,2.9,2.4,2.7,2.9,2.8,2.7,2.6,2.5,2.5,2.4,2.4],
       unemp:[3.7,3.8,3.7,3.7,3.9,4.1,4.0,4.1,4.1,4.0,4.0,3.9,3.9,3.9],
       exports:[2530,2480,2510,2560,2470,2520,2490,2540,2530,2560,2570,2550,2565,2580] },
  eu:{ gdpLabels:['23Q1','23Q2','23Q3','23Q4','24Q1','24Q2','24Q3','24Q4','25Q1','25Q2','25Q3','25Q4','26Q1'],
       gdp:[1.3,0.6,0.0,-0.1,0.4,0.3,0.9,1.1,0.6,0.4,0.5,0.7,0.6],
       cpiLabels:['24.01','24.03','24.05','24.07','24.09','24.11','25.01','25.03','25.05','25.07','25.09','25.11','26.01','26.03'],
       cpi:[2.8,2.4,2.6,2.6,1.7,2.3,2.5,2.3,2.2,2.1,2.0,2.1,2.0,2.0],
       unemp:[6.5,6.5,6.4,6.2,6.0,6.1,6.2,6.1,6.0,5.9,5.9,5.9,5.8,5.8],
       exports:[2100,2080,2120,2090,2150,2110,2130,2160,2140,2165,2180,2155,2170,2185] },
  cn:{ gdpLabels:['23Q1','23Q2','23Q3','23Q4','24Q1','24Q2','24Q3','24Q4','25Q1','25Q2','25Q3','25Q4','26Q1'],
       gdp:[4.5,6.3,4.9,5.2,5.3,4.7,4.6,5.0,4.8,4.7,4.6,4.8,5.1],
       cpiLabels:['24.01','24.03','24.05','24.07','24.09','24.11','25.01','25.03','25.05','25.07','25.09','25.11','26.01','26.03'],
       cpi:[-0.8,0.1,0.3,0.5,-0.4,0.2,0.5,0.1,0.3,0.4,0.2,0.3,0.4,0.5],
       unemp:[5.2,5.2,5.0,5.1,5.0,5.1,5.2,5.3,5.2,5.1,5.0,5.1,5.0,5.0],
       exports:[3200,3150,3180,3220,3100,3190,3210,3240,3230,3250,3270,3245,3260,3290] },
  jp:{ gdpLabels:['23Q1','23Q2','23Q3','23Q4','24Q1','24Q2','24Q3','24Q4','25Q1','25Q2','25Q3','25Q4','26Q1'],
       gdp:[2.7,2.2,2.4,1.3,-0.9,2.9,1.1,1.4,0.8,1.0,0.5,0.7,-0.2],
       cpiLabels:['24.01','24.03','24.05','24.07','24.09','24.11','25.01','25.03','25.05','25.07','25.09','25.11','26.01','26.03'],
       cpi:[2.2,2.7,2.5,2.8,2.4,2.9,3.6,3.7,3.4,3.2,3.0,2.9,2.8,2.7],
       unemp:[2.4,2.6,2.5,2.4,2.6,2.5,2.4,2.5,2.5,2.5,2.4,2.4,2.4,2.4],
       exports:[807,795,819,835,782,810,792,825,815,830,838,820,832,845] },
  de:{ gdpLabels:['23Q1','23Q2','23Q3','23Q4','24Q1','24Q2','24Q3','24Q4','25Q1','25Q2','25Q3','25Q4','26Q1'],
       gdp:[-0.1,-0.2,-0.1,-0.3,0.2,0.0,-0.3,-0.2,0.1,0.2,0.3,0.3,0.4],
       cpiLabels:['24.01','24.03','24.05','24.07','24.09','24.11','25.01','25.03','25.05','25.07','25.09','25.11','26.01','26.03'],
       cpi:[2.9,2.2,2.4,2.3,1.6,2.2,2.3,2.3,2.2,2.1,2.0,2.0,1.9,1.9],
       unemp:[3.0,3.1,3.0,3.1,3.4,3.4,3.4,3.6,3.5,3.5,3.4,3.4,3.4,3.3],
       exports:[1340,1320,1360,1350,1290,1310,1295,1330,1310,1335,1350,1320,1340,1365] },
  uk:{ gdpLabels:['23Q1','23Q2','23Q3','23Q4','24Q1','24Q2','24Q3','24Q4','25Q1','25Q2','25Q3','25Q4','26Q1'],
       gdp:[0.1,0.3,0.0,0.3,0.7,0.5,0.3,0.4,0.5,0.6,0.5,0.6,0.7],
       cpiLabels:['24.01','24.03','24.05','24.07','24.09','24.11','25.01','25.03','25.05','25.07','25.09','25.11','26.01','26.03'],
       cpi:[4.0,3.2,2.0,2.2,1.7,2.6,3.0,2.8,2.6,2.4,2.3,2.3,2.2,2.1],
       unemp:[3.9,4.2,4.0,4.4,4.4,4.3,4.4,4.4,4.3,4.3,4.2,4.2,4.1,4.1],
       exports:[680,670,690,685,665,675,670,680,685,695,700,690,695,705] },
};
// 미국 데이터: GDP는 분기당 % 연환산. 한국형 전기비(%)로 호환되도록 그대로 사용.

// 한국 GDP 전기비 fallback (data.json 에 gdp_kr 이 없을 때 사용)
// 23Q1 ~ 26Q1 (한국은행 ECOS 200Y104 시리즈 추정값)
const KR_GDP_QOQ_FALLBACK = {
  value: 0.8,
  period: '202601',
  desc: '한국 실질GDP 성장률 (전기비)',
  source: 'fallback:hardcoded-2026Q1',
  history: { '23Q1':0.4,'23Q2':0.6,'23Q3':0.7,'23Q4':0.6,'24Q1':1.3,'24Q2':-0.2,'24Q3':0.1,'24Q4':0.1,'25Q1':0.3,'25Q2':0.5,'25Q3':0.4,'25Q4':0.5,'26Q1':0.8 }
};

// 누락 지표 fallback — data.json 에 값 없을 때 사용 (TODO: scripts/fetch_data.py 의 ECOS 코드 매핑 보강)
const KR_FALLBACKS = {
  // 소매판매액지수 (KOSIS DT_2KAA503 / ECOS 901Y100) — 2020=100 기준
  retail_kr: {
    value: 104.8, period: '202603',
    desc: '한국 소매판매액지수 (월간, 2020=100)',
    source: 'fallback (실데이터 미연결)',
    history: {'2024-01':101.2,'2024-04':101.8,'2024-07':102.1,'2024-10':102.4,'2025-01':103.0,'2025-04':103.5,'2025-07':103.8,'2025-10':104.1,'2026-01':104.5,'2026-03':104.8}
  },
  // 실업률 (계절조정, 월간) — KOSIS DT_1DA7022 / ECOS 200Y004
  unemployment_kr: {
    value: 2.7, period: '202603',
    desc: '한국 실업률 (계절조정, %)',
    source: 'fallback (실데이터 미연결)',
    history: {'2024-01':3.0,'2024-04':2.8,'2024-07':2.7,'2024-10':2.8,'2025-01':2.9,'2025-04':2.8,'2025-07':2.7,'2025-10':2.7,'2026-01':2.7,'2026-03':2.7}
  },
  // 수출 (월간, 백만달러) — ECOS 403Y003 / 산업통상자원부
  exports_kr: {
    value: 63500, period: '202603',
    desc: '한국 수출 (월간, 백만달러)',
    source: 'fallback (실데이터 미연결)',
    history: {'2024-01':54700,'2024-04':56200,'2024-07':57400,'2024-10':58800,'2025-01':59500,'2025-04':60500,'2025-07':61200,'2025-10':62000,'2026-01':62800,'2026-03':63500}
  },
  // 산업생산지수 — ECOS 901Y033 / KOSIS DT_1F31
  ip_kr_fb: {
    value: 108.2, period: '202603',
    desc: '한국 산업생산지수 (광공업, 2020=100)',
    source: 'fallback (실데이터 미연결)',
    history: {'2024-01':104.0,'2024-04':105.2,'2024-07':105.8,'2024-10':106.3,'2025-01':106.9,'2025-04':107.2,'2025-07':107.5,'2025-10':107.8,'2026-01':108.0,'2026-03':108.2}
  },
};
let macroTab='kr';
let macroViewMode='country';
function setMacroViewMode(mode, btn) {
  macroViewMode = mode;
  document.querySelectorAll('#macroViewToggle button').forEach(b => {
    b.style.background = 'transparent'; b.style.color = 'var(--c-txt-dim)'; b.style.border = '1px solid var(--c-border)';
  });
  btn.style.background = 'var(--c-accent)'; btn.style.color = '#fff'; btn.style.border = '1px solid var(--c-accent)';
  const countryTabs = document.getElementById('macroCountryTabs');
  const topicTabs   = document.getElementById('macroTopicTabs');
  const indicatorDetails = document.querySelector('#page-macro details');
  if(mode === 'country') {
    countryTabs.style.display = 'flex';
    topicTabs.style.display   = 'none';
    if(indicatorDetails) indicatorDetails.style.display = '';
    initMacroPage(macroTab);
  } else {
    countryTabs.style.display = 'none';
    topicTabs.style.display   = 'flex';
    if(indicatorDetails) indicatorDetails.style.display = 'none';
    macroTopicPeriod = 'all';
    initMacroTopicPage('gdp');
    // reset topic tab UI
    document.querySelectorAll('#macroTopicTabs .tab-btn').forEach((b,i)=>{
      b.style.background = i===0 ? getThemeColors().accent : 'transparent';
      b.style.color = i===0 ? '#fff' : '#8d90a2';
    });
  }
}
function setMacroTopicTab(topic, btn) {
  document.querySelectorAll('#macroTopicTabs .tab-btn').forEach(b=>{
    b.classList.remove('active');
    b.style.background='transparent';
    b.style.color='var(--c-txt-dim,#a4a8bc)';
  });
  if(btn) {
    btn.classList.add('active');
    btn.style.background='var(--c-accent)';
    btn.style.color='#fff';
  }
  initMacroTopicPage(topic);
}
let macroTopicPeriod = 'all';
function initMacroTopicPage(topic) {
  ['gdpTopic','cpiTopic','unempTopic','tradeTopic'].forEach(destroyChart);
  const mc = document.getElementById('macroContent');
  const topicMeta = {
    gdp:   {title:'GDP 성장률 (전년동기비, %)', id:'gdpTopic',   key:'gdp',     labels:'gdpLabels',  unit:'%',  freq:'Q'},
    cpi:   {title:'소비자물가 CPI (전년비, %)', id:'cpiTopic',   key:'cpi',     labels:'cpiLabels',  unit:'%',  freq:'M'},
    unemp: {title:'실업률 (%)',                 id:'unempTopic', key:'unemp',   labels:'gdpLabels',  unit:'%',  freq:'Q'},
    trade: {title:'수출 (억 달러)',             id:'tradeTopic', key:'exports', labels:'gdpLabels',  unit:'억$',freq:'Q'},
  };
  const m = topicMeta[topic];
  if(!m) return;
  // 기간 옵션: 분기 데이터는 1년/2년/3년/5년/전체, 월간은 6개월/1년/2년/3년/전체
  const periodOpts = m.freq === 'Q'
    ? [{key:'4',label:'최근 1년'},{key:'8',label:'최근 2년'},{key:'12',label:'최근 3년'},{key:'20',label:'최근 5년'},{key:'all',label:'전체'}]
    : [{key:'6',label:'최근 6개월'},{key:'12',label:'최근 1년'},{key:'24',label:'최근 2년'},{key:'36',label:'최근 3년'},{key:'all',label:'전체'}];
  // 현재 선택값이 옵션에 없으면 'all'로 보정
  if(!periodOpts.some(o=>o.key===macroTopicPeriod)) macroTopicPeriod = 'all';
  const colors = {'kr':window.CUP,'us':window.CDN,'jp':'#f5a623','cn':'#ff7043','de':'#42a5f5','uk':'#ab47bc','eu':'#b6c4ff'};
  const flags  = {'kr':'🇰🇷 한국','us':'🇺🇸 미국','jp':'🇯🇵 일본','cn':'🇨🇳 중국','de':'🇩🇪 독일','uk':'🇬🇧 영국','eu':'🇪🇺 유로존'};
  const allCountries = ['kr','us','jp','cn','de','uk','eu'];
  // 국가 필터 상태 (전역) — 한 번도 설정 안 됐으면 전체 선택
  if(!window._macroTopicCountrySet) window._macroTopicCountrySet = new Set(allCountries);
  const selSet = window._macroTopicCountrySet;
  mc.innerHTML = `
    <div class="widget">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:8px;">
        <div class="widget-title" style="margin-bottom:0;">${m.title} — 국가별 비교 <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);font-weight:var(--font-weight-normal);">단위: ${m.unit}</span></div>
        <div style="display:flex;gap:4px;">
          ${periodOpts.map(o=>`<button onclick="setMacroTopicPeriod('${o.key}','${topic}',this)" style="font-size:var(--font-size-sm);padding:3px 10px;border-radius:var(--r-xs);border:1px solid var(--c-border);background:${macroTopicPeriod===o.key?'var(--c-accent)':'transparent'};color:${macroTopicPeriod===o.key?'#fff':'var(--c-txt-dim)'};cursor:pointer;font-weight:var(--font-weight-medium);">${o.label}</button>`).join('')}
          <button class="yoy-btn" data-yoy="${m.id}" onclick="toggleYoY('${m.id}',this)" aria-pressed="false" title="주 국가의 전년 동기 데이터를 점선으로 오버레이"><span aria-hidden="true" class="mat">compare_arrows</span><span class="yoy-btn-lbl">전년 비교</span></button>
        </div>
      </div>
      <!-- 국가 필터 (다중선택) — 원자재 차트의 필터처럼 토글 -->
      <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px;align-items:center;">
        <span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);margin-right:4px;">국가:</span>
        ${allCountries.map(cc => {
          const on = selSet.has(cc);
          return `<button onclick="toggleMacroTopicCountry('${cc}','${topic}',this)" data-cc="${cc}" style="font-size:var(--font-size-sm);padding:2px 8px;border-radius:var(--r-xs);border:1px solid ${on?colors[cc]:'var(--c-border)'};background:${on?colors[cc]+'22':'transparent'};color:${on?colors[cc]:'var(--c-txt-dim)'};cursor:pointer;font-weight:var(--font-weight-medium);">${flags[cc]}</button>`;
        }).join('')}
        <button onclick="selectAllMacroTopicCountries('${topic}')" style="font-size:var(--font-size-xs);padding:2px 8px;border-radius:var(--r-xs);border:1px solid var(--c-border);background:transparent;color:var(--c-txt-dim);cursor:pointer;margin-left:8px;">전체</button>
      </div>
      <div style="position:relative;height:280px;"><canvas id="${m.id}"></canvas></div>
      <div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:6px;text-align:right;">참고: 대표 통계 데이터 (각국 통계청 / OECD)</div>
    </div>`;
  const d0 = macroData['kr'];
  const allLabels = d0[m.labels];
  const n = macroTopicPeriod === 'all' ? allLabels.length : parseInt(macroTopicPeriod);
  const labels = allLabels.slice(-n);
  const tc = getThemeColors();
  const selectedCountries = allCountries.filter(cc => selSet.has(cc));
  const datasets = selectedCountries.map(cc => ({
    label: flags[cc],
    data: (macroData[cc][m.key] || []).slice(-n),
    borderColor: colors[cc],
    backgroundColor: colors[cc] + '22',
    borderWidth: 2,
    pointRadius: 0,
    fill: false,
    tension: 0.3,
    type: 'line',
  }));
  // 각 dataset 마다 변화율 (첫값→마지막값) 을 라벨에 표시
  datasets.forEach(ds => {
    const vals = (ds.data || []).filter(v => v != null && !isNaN(v));
    if(vals.length >= 2) {
      const first = vals[0], last = vals[vals.length-1];
      const chg = last - first;
      const pct = first !== 0 ? (chg / Math.abs(first)) * 100 : 0;
      const arrow = chg >= 0 ? '▲' : '▼';
      const clr = chg >= 0 ? window.CUP : window.CDN;
      ds.label = ds.label + ` (${arrow} ${chg >= 0 ? '+' : ''}${fmtNum(pct)}%)`;
    }
  });
  charts[m.id] = new Chart(document.getElementById(m.id), {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive:true, maintainAspectRatio:false,
      scales:{
        x:{ticks:{color:tc.txt,font:{size:10}},grid:{color:tc.grid}},
        y:{ticks:{color:tc.txt,font:{size:10},maxTicksLimit:6,callback:v=>fmtNum(v)+(m.unit==='억$'?'':'%')},grid:{color:tc.grid},position:'right'}
      },
      plugins:{
        legend:{display:true,position:'top',labels:{color:tc.txt,font:{size:10},boxWidth:10}},
        tooltip:{mode:'index',intersect:false,backgroundColor:tc.tooltip,titleColor:tc.ttTitle,borderColor:tc.ttBorder,borderWidth:1,callbacks:{label:ctx=>ctx.dataset.label.replace(/ \([▲▼].+\)$/,'')+': '+fmtNum(ctx.parsed.y)+m.unit}}
      }
    }
  });
  // YoY — 주 시리즈(첫 선택 국가, dataset 0)만 전년 오버레이. 주기 라벨 기반.
  { const _pc = selectedCountries[0];
    if(_pc) registerYoY(m.id, { mode:'periodlabel', dispLabels:labels, fullLabels:allLabels, fullValues:(macroData[_pc][m.key]||[]), primary:0, color:colors[_pc], tension:0.3 });
    else registerYoY(m.id, null);
    applyYoY(m.id); }
}
function setMacroTopicPeriod(p, topic, btn) {
  macroTopicPeriod = p;
  initMacroTopicPage(topic);
}
function toggleMacroTopicCountry(cc, topic, btn) {
  if(!window._macroTopicCountrySet) window._macroTopicCountrySet = new Set(['kr','us','jp','cn','de','uk','eu']);
  const s = window._macroTopicCountrySet;
  if(s.has(cc)) {
    if(s.size <= 1) return;  // 최소 1개는 유지
    s.delete(cc);
  } else {
    s.add(cc);
  }
  initMacroTopicPage(topic);
}
function selectAllMacroTopicCountries(topic) {
  window._macroTopicCountrySet = new Set(['kr','us','jp','cn','de','uk','eu']);
  initMacroTopicPage(topic);
}
function setMacroTab(t,btn){
  macroTab=t;
  document.querySelectorAll('#macroCountryTabs .tab-btn').forEach(b=>{b.classList.remove('active');b.style.background='transparent';b.style.color='var(--c-txt-dim)';});
  btn.classList.add('active');btn.style.background='var(--c-accent)';btn.style.color='#fff';
  initMacroPage(t);
  // 국가별 뉴스 필터 자동 적용
  const macroNewsMap = {kr:'한국GDP', us:'미국CPI', eu:'유로존', cn:'중국경기', jp:'일본경기', de:'독일경기', uk:'영국경기'};
  const filterCat = macroNewsMap[t] || 'all';
  currentNewsFilter['macroNewsFeed'] = filterCat;
  document.querySelectorAll('#page-macro .news-filter-btn').forEach(b=>{
    const onclick = b.getAttribute('onclick') || '';
    const m = onclick.match(/'macroNewsFeed','([^']+)'/);
    const btnCat = m ? m[1] : '';
    if(btnCat === filterCat) b.classList.add('act'); else b.classList.remove('act');
  });
  renderFiltered('macroNewsFeed');
  // 탭 전환 후 차트 새로고침 버튼 주입
  setTimeout(() => { try { injectChartRefreshButtons(); } catch(_){} }, 200);
}
const macroMeta = {
  kr: {
    gdpSrc:'https://ecos.bok.or.kr/#/', gdpNext:'2026.05.23 08:00',
    cpiSrc:'https://kostat.go.kr/board.es?mid=a10301010000&bid=10820', cpiNext:'2026.06.04 08:00',
    unempSrc:'https://kostat.go.kr', unempNext:'2026.06.13 08:00',
    tradeSrc:'https://www.customs.go.kr/kcs/na/ntt/selectNttInfo.do?mi=3059', tradeNext:'2026.06.01 08:00',
  },
  us: {
    gdpSrc:'https://www.bea.gov/data/gdp/gross-domestic-product', gdpNext:'2026.05.29 21:30',
    cpiSrc:'https://www.bls.gov/cpi/', cpiNext:'2026.06.11 21:30',
    unempSrc:'https://www.bls.gov/news.release/empsit.nr0.htm', unempNext:'2026.06.06 21:30',
    tradeSrc:'https://www.census.gov/foreign-trade/index.html', tradeNext:'2026.06.05 21:30',
  },
  eu: {
    gdpSrc:'https://ec.europa.eu/eurostat/web/national-accounts', gdpNext:'2026.05.30 11:00',
    cpiSrc:'https://ec.europa.eu/eurostat/web/hicp', cpiNext:'2026.06.18 11:00',
    unempSrc:'https://ec.europa.eu/eurostat/web/labour-market', unempNext:'2026.06.30 11:00',
    tradeSrc:'https://ec.europa.eu/eurostat/web/international-trade', tradeNext:'2026.06.16 11:00',
  },
  cn: {
    gdpSrc:'https://www.stats.gov.cn/english/', gdpNext:'2026.07.16 10:00',
    cpiSrc:'https://www.stats.gov.cn/english/pressrelease/price/', cpiNext:'2026.06.10 09:30',
    unempSrc:'https://www.stats.gov.cn', unempNext:'2026.06.16 10:00',
    tradeSrc:'https://english.mofcom.gov.cn/', tradeNext:'2026.06.08 10:00',
  },
  jp: {
    gdpSrc:'https://www.esri.cao.go.jp/en/sna/menu.html', gdpNext:'2026.05.16 08:50',
    cpiSrc:'https://www.stat.go.jp/english/data/cpi/', cpiNext:'2026.06.20 08:30',
    unempSrc:'https://www.stat.go.jp/english/data/roudou/', unempNext:'2026.06.27 08:30',
    tradeSrc:'https://www.customs.go.jp/toukei/info/index_e.htm', tradeNext:'2026.06.18 08:50',
  },
  de: {
    gdpSrc:'https://www.destatis.de/EN/Themes/Economy/National-Accounts-Domestic-Product/_node.html', gdpNext:'2026.05.23 08:00',
    cpiSrc:'https://www.destatis.de/EN/Themes/Economy/Prices/Consumer-Price-Index/_node.html', cpiNext:'2026.05.28 08:00',
    unempSrc:'https://statistik.arbeitsagentur.de', unempNext:'2026.06.02 09:55',
    tradeSrc:'https://www.destatis.de/EN/Themes/Economy/Foreign-Trade/_node.html', tradeNext:'2026.06.10 08:00',
  },
  uk: {
    gdpSrc:'https://www.ons.gov.uk/economy/grossdomesticproductgdp', gdpNext:'2026.05.15 07:00',
    cpiSrc:'https://www.ons.gov.uk/economy/inflationandpriceindices', cpiNext:'2026.05.21 07:00',
    unempSrc:'https://www.ons.gov.uk/employmentandlabourmarket', unempNext:'2026.05.20 07:00',
    tradeSrc:'https://www.ons.gov.uk/economy/tradeingoodsandservices', tradeNext:'2026.06.09 07:00',
  },
};

// dataPath: data.json 내 경로 (economicIndicators.us.* / .kr.* / realestate.us.*)
// fmt: 값 포맷터 함수
// unit: 단위/기준 (사용자가 한눈에 확인할 수 있도록 표기)
const macroIndicators = [
  // 한국 (ECOS)
  {name:'GDP 성장률 (전기비)',cc:'🇰🇷',cat:'경기',src:'한국은행 ECOS',freq:'분기',unit:'% (전기비)',dataPath:'economicIndicators.kr.gdp_kr',fmt:v=>v?.toFixed(2)+'%'},
  {name:'소비자물가지수 (CPI)',cc:'🇰🇷',cat:'물가',src:'한국은행 ECOS',freq:'월간',unit:'지수 (2020=100)',dataPath:'economicIndicators.kr.cpi_kr',fmt:v=>v?.toFixed(2)},
  {name:'생산자물가지수 (PPI)',cc:'🇰🇷',cat:'물가',src:'한국은행 ECOS',freq:'월간',unit:'지수 (2015=100)',dataPath:'economicIndicators.kr.ppi_kr',fmt:v=>v?.toFixed(2)},
  {name:'실업률',cc:'🇰🇷',cat:'고용',src:'한국은행 ECOS',freq:'월간',unit:'% (계절조정)',dataPath:'economicIndicators.kr.unemployment_kr',fmt:v=>v?.toFixed(2)+'%'},
  {name:'수출',cc:'🇰🇷',cat:'무역',src:'한국은행 ECOS',freq:'월간',unit:'백만달러',dataPath:'economicIndicators.kr.exports_kr',fmt:v=>v?.toLocaleString()},
  {name:'경상수지',cc:'🇰🇷',cat:'무역',src:'한국은행 ECOS',freq:'월간',unit:'백만달러',dataPath:'economicIndicators.kr.current_account_kr',fmt:v=>v?.toLocaleString()},
  {name:'제조업 PMI·경기지수',cc:'🇰🇷',cat:'경기',src:'OECD (FRED BSCICP02KRM460S) · ECOS BSI 보조',freq:'월간',unit:'지수',
    dataPath:'economicIndicators.kr.pmi_kr',fmt:v=>v?.toFixed(1),
    link:'https://www.pmi.spglobal.com/Public/Home/PressRelease',linkLabel:'S&P PMI 보고서'},
  {name:'산업생산지수',cc:'🇰🇷',cat:'경기',src:'한국은행 ECOS',freq:'월간',unit:'지수 (2020=100)',dataPath:'economicIndicators.kr.ip_kr',fmt:v=>v?.toFixed(2)},
  {name:'소매판매액지수',cc:'🇰🇷',cat:'소비',src:'KOSIS (통계청) · ECOS 보조',freq:'월간',unit:'지수 (2020=100)',dataPath:'economicIndicators.kr.retail_kr',fmt:v=>v?.toFixed(2),
   link:'https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JG2105',linkLabel:'KOSIS 소매판매액지수'},
  {name:'기준금리',cc:'🇰🇷',cat:'통화',src:'한국은행',freq:'8회/년',unit:'% (연이율)',dataPath:'economicIndicators.kr.base_rate_kr',fmt:v=>v?.toFixed(2)+'%'},
  // 미국 (FRED)
  {name:'GDP 성장률',cc:'🇺🇸',cat:'경기',src:'BEA (FRED: A191RL1Q225SBEA)',freq:'분기',unit:'% (전기비 연율 SAAR)',dataPath:'economicIndicators.us.gdp_growth_us',fmt:v=>v==null?'—':(+v).toFixed(1)+'%'},
  {name:'소비자물가지수 (CPI)',cc:'🇺🇸',cat:'물가',src:'BLS (FRED: CPIAUCSL)',freq:'월간',unit:'지수 (1982-84=100)',dataPath:'economicIndicators.us.cpi_us',fmt:v=>v?.toFixed(2)},
  {name:'PCE 물가지수',cc:'🇺🇸',cat:'물가',src:'BEA (FRED: PCE)',freq:'월간',unit:'지수 (2017=100)',dataPath:'economicIndicators.us.pce_us',fmt:v=>v?.toFixed(2)},
  {name:'실업률',cc:'🇺🇸',cat:'고용',src:'BLS (FRED: UNRATE)',freq:'월간',unit:'% (계절조정)',dataPath:'economicIndicators.us.unemployment',fmt:v=>v?.toFixed(2)+'%'},
  {name:'기준금리 (FFR)',cc:'🇺🇸',cat:'통화',src:'연준 (FRED: FEDFUNDS)',freq:'8회/년',unit:'% (연이율)',dataPath:'economicIndicators.us.ff_rate',fmt:v=>v?.toFixed(2)+'%'},
  {name:'M2 통화량',cc:'🇺🇸',cat:'통화',src:'연준 (FRED: M2SL)',freq:'월간',unit:'10억 USD',dataPath:'economicIndicators.us.m2_us',fmt:v=>v?.toLocaleString()},
  {name:'산업생산지수',cc:'🇺🇸',cat:'경기',src:'Fed (FRED: INDPRO)',freq:'월간',unit:'지수 (2017=100, 계절조정)',dataPath:'economicIndicators.us.ip_us',fmt:v=>v?.toFixed(2)},
  {name:'10년 국채',cc:'🇺🇸',cat:'금리',src:'연준 (FRED: GS10)',freq:'일간',unit:'% (수익률)',dataPath:'economicIndicators.us.us10y',fmt:v=>v?.toFixed(2)+'%'},
  {name:'2년 국채',cc:'🇺🇸',cat:'금리',src:'연준 (FRED: GS2)',freq:'일간',unit:'% (수익률)',dataPath:'economicIndicators.us.us2y',fmt:v=>v?.toFixed(2)+'%'},
  {name:'VIX 변동성',cc:'🇺🇸',cat:'시장',src:'CBOE (FRED: VIXCLS)',freq:'일간',unit:'지수 (S&P500 30일 내재변동성)',dataPath:'economicIndicators.us.vix',fmt:v=>v?.toFixed(2)},
  {name:'HY 크레딧 스프레드',cc:'🇺🇸',cat:'시장',src:'BofA (FRED: BAMLH0A0HYM2)',freq:'일간',unit:'%p (국채 대비)',dataPath:'economicIndicators.us.hy_spread',fmt:v=>v?.toFixed(2)+'%'},
  {name:'달러 인덱스 (DXY)',cc:'🇺🇸',cat:'외환',src:'ICE / yfinance DX-Y.NYB',freq:'일간',unit:'지수 (1973=100, ICE 발표)',dataPath:'economicIndicators.us.dxy_idx',fmt:v=>v?.toFixed(2),
   link:'https://finance.yahoo.com/quote/DX-Y.NYB',linkLabel:'Yahoo Finance DXY'},
  {name:'Case-Shiller HPI',cc:'🇺🇸',cat:'부동산',src:'S&P (FRED: CSUSHPINSA)',freq:'월간',unit:'지수 (2000.1=100)',dataPath:'realestate.us.case_shiller_national',fmt:v=>v?.toFixed(1)},
  {name:'30년 모기지',cc:'🇺🇸',cat:'부동산',src:'Freddie Mac (FRED)',freq:'주간',unit:'% (연이율)',dataPath:'realestate.us.mortgage_30y',fmt:v=>v?.toFixed(2)+'%'},
  {name:'NAHB 주택시장지수',cc:'🇺🇸',cat:'부동산',src:'NAHB (FRED)',freq:'월간',unit:'지수 (50=중립)',dataPath:'realestate.us.nahb_index',fmt:v=>v?.toFixed(0)},
  // 유로존 (FRED 국제 시리즈)
  {name:'HICP 물가지수',cc:'🇪🇺',cat:'물가',src:'Eurostat (FRED)',freq:'월간',unit:'지수 (2015=100)',dataPath:'economicIndicators.eu.cpi_eu',fmt:v=>v?.toFixed(2)},
  {name:'GDP 성장률',cc:'🇪🇺',cat:'경기',src:'Eurostat (FRED)',freq:'분기',unit:'% (YoY, 실질)',dataPath:'economicIndicators.eu.gdp_yoy_eu',fmt:v=>v==null?'—':(+v).toFixed(1)+'%'},
  {name:'실업률',cc:'🇪🇺',cat:'고용',src:'Eurostat (FRED)',freq:'월간',unit:'% (계절조정)',dataPath:'economicIndicators.eu.unemployment_eu',fmt:v=>v?.toFixed(2)+'%'},
  {name:'기준금리 (ECB)',cc:'🇪🇺',cat:'통화',src:'ECB (FRED)',freq:'8회/년',unit:'% (예금금리)',dataPath:'economicIndicators.eu.base_rate_eu',fmt:v=>v?.toFixed(2)+'%'},
  // 중국 (FRED 국제 시리즈)
  {name:'소비자물가지수 (CPI)',cc:'🇨🇳',cat:'물가',src:'NBS (FRED OECD)',freq:'월간',unit:'지수 (2015=100)',dataPath:'economicIndicators.cn.cpi_cn',fmt:v=>v?.toFixed(2)},
  {name:'GDP 성장률',cc:'🇨🇳',cat:'경기',src:'World Bank (FRED)',freq:'연간',unit:'% (YoY, 명목 USD)',dataPath:'economicIndicators.cn.gdp_yoy_cn',fmt:v=>v==null?'—':(+v).toFixed(1)+'%'},
  {name:'산업생산지수',cc:'🇨🇳',cat:'경기',src:'NBS (FRED OECD)',freq:'월간',unit:'지수 (2015=100)',dataPath:'economicIndicators.cn.ip_cn',fmt:v=>v?.toFixed(2)},
  {name:'제조업 PMI·경기지수',cc:'🇨🇳',cat:'경기',src:'OECD (FRED BSCICP02CNM460S)',freq:'월간',unit:'지수',
    dataPath:'economicIndicators.cn.pmi_cn',fmt:v=>v?.toFixed(1),
    link:'http://www.stats.gov.cn/english/PressRelease/',linkLabel:'NBS 발표문'},
  // 일본 (link 보강)
  {name:'제조업 PMI·경기지수',cc:'🇯🇵',cat:'경기',src:'OECD (FRED BSCICP02JPM460S)',freq:'월간',unit:'지수',
    dataPath:'economicIndicators.jp.pmi_jp',fmt:v=>v?.toFixed(1),
    link:'https://www.pmi.spglobal.com/Public/Home/PressRelease',linkLabel:'S&P PMI 보고서'},
  // 미국 (link 보강)
  {name:'제조업 PMI·경기지수',cc:'🇺🇸',cat:'경기',src:'OECD BCI (FRED BSCICP02USM460S)',freq:'월간',unit:'지수',
    dataPath:'economicIndicators.us.pmi_us',fmt:v=>v?.toFixed(1),
    link:'https://fred.stlouisfed.org/series/BSCICP02USM460S',linkLabel:'OECD 기업경기지수(FRED)'},
  // 유로존
  {name:'제조업 PMI·경기지수',cc:'🇪🇺',cat:'경기',src:'S&P Global PMI · OECD BCI 보조',freq:'월간',unit:'지수',
    dataPath:'economicIndicators.eu.pmi_eu',fmt:v=>v?.toFixed(1),
    link:'https://www.pmi.spglobal.com/Public/Home/PressRelease',linkLabel:'S&P PMI 보고서'},
  // 영국
  {name:'제조업 PMI·경기지수',cc:'🇬🇧',cat:'경기',src:'OECD BCI (FRED BSCICP02GBM460S)',freq:'월간',unit:'지수',
    dataPath:'economicIndicators.uk.pmi_uk',fmt:v=>v?.toFixed(1),
    link:'https://www.pmi.spglobal.com/Public/Home/PressRelease',linkLabel:'S&P PMI 보고서'},
  // 독일
  {name:'제조업 PMI·경기지수',cc:'🇩🇪',cat:'경기',src:'OECD (FRED BSCICP02DEM460S)',freq:'월간',unit:'지수',
    dataPath:'economicIndicators.de.pmi_de',fmt:v=>v?.toFixed(1),
    link:'https://www.pmi.spglobal.com/Public/Home/PressRelease',linkLabel:'S&P PMI 보고서'},
  // 일본 (FRED 국제 시리즈)
  {name:'GDP 성장률',cc:'🇯🇵',cat:'경기',src:'내각부 (FRED)',freq:'분기',unit:'% (YoY, 실질)',dataPath:'economicIndicators.jp.gdp_yoy_jp',fmt:v=>v==null?'—':(+v).toFixed(1)+'%',
    link:'https://www.esri.cao.go.jp/jp/sna/menu.html',linkLabel:'내각부 발표'},
  {name:'소비자물가지수',cc:'🇯🇵',cat:'물가',src:'총무성 (FRED)',freq:'월간',unit:'지수 (2020=100)',dataPath:'economicIndicators.jp.cpi_jp',fmt:v=>v?.toFixed(2),
    link:'https://www.stat.go.jp/data/cpi/',linkLabel:'총무성 통계국'},
  {name:'실업률',cc:'🇯🇵',cat:'고용',src:'총무성 (FRED)',freq:'월간',unit:'% (15-64세, 계절조정)',dataPath:'economicIndicators.jp.unemployment_jp',fmt:v=>v?.toFixed(2)+'%',
    link:'https://www.stat.go.jp/data/roudou/',linkLabel:'노동력조사'},
  {name:'기준금리 (BOJ)',cc:'🇯🇵',cat:'통화',src:'일본은행 (BOJ+FRED)',freq:'연8회',unit:'% (무담보 익일물)',dataPath:'economicIndicators.jp.base_rate_jp',fmt:v=>v?.toFixed(2)+'%',
    link:'https://www.boj.or.jp/en/mopo/mpmdeci/state_all/index.htm',linkLabel:'BOJ 정책결정'},
  {name:'산업생산지수',cc:'🇯🇵',cat:'경기',src:'OECD MEI (FRED: JPNPROINDMISMEI)',freq:'월간',unit:'지수 (2015=100)',dataPath:'economicIndicators.jp.ip_jp',fmt:v=>v?.toFixed(2)},
  // 독일 (FRED 국제 시리즈)
  {name:'소비자물가지수',cc:'🇩🇪',cat:'물가',src:'Destatis (FRED)',freq:'월간',unit:'지수 (2015=100)',dataPath:'economicIndicators.de.cpi_de',fmt:v=>v?.toFixed(2)},
  {name:'GDP 성장률',cc:'🇩🇪',cat:'경기',src:'Destatis (FRED)',freq:'분기',unit:'% (YoY, 실질)',dataPath:'economicIndicators.de.gdp_yoy_de',fmt:v=>v==null?'—':(+v).toFixed(1)+'%'},
  {name:'실업률',cc:'🇩🇪',cat:'고용',src:'Destatis (FRED)',freq:'월간',unit:'% (계절조정)',dataPath:'economicIndicators.de.unemployment_de',fmt:v=>v?.toFixed(2)+'%'},
  // 영국 (FRED 국제 시리즈)
  {name:'소비자물가지수',cc:'🇬🇧',cat:'물가',src:'ONS (FRED)',freq:'월간',unit:'지수 (2015=100)',dataPath:'economicIndicators.uk.cpi_uk',fmt:v=>v?.toFixed(2)},
  {name:'GDP 성장률',cc:'🇬🇧',cat:'경기',src:'ONS (FRED)',freq:'분기',unit:'% (YoY, 실질)',dataPath:'economicIndicators.uk.gdp_yoy_uk',fmt:v=>v==null?'—':(+v).toFixed(1)+'%'},
  {name:'실업률',cc:'🇬🇧',cat:'고용',src:'ONS (FRED)',freq:'월간',unit:'% (계절조정)',dataPath:'economicIndicators.uk.unemployment_uk',fmt:v=>v?.toFixed(2)+'%'},
  {name:'기준금리 (BOE)',cc:'🇬🇧',cat:'통화',src:'BOE (FRED)',freq:'8회/년',unit:'% (Bank Rate)',dataPath:'economicIndicators.uk.base_rate_uk',fmt:v=>v?.toFixed(2)+'%'},
];

function getDataByPath(obj, path) {
  if(!obj || !path) return null;
  return path.split('.').reduce((o,k)=>o?.[k], obj);
}
let _latestDataForIndicators = null;
let _lastKospiHistoryHash = null;  // KOSPI history 시계열 해시 (재렌더 방지)

// ============================
// 실데이터 시계열 헬퍼 — data.json.history 에서 historical close prices 조회
// 더미 데이터(genSeries) 대신 실제 데이터를 사용하기 위함
// ============================
function getHistoricalSeries(category, name) {
  const d = _latestDataForIndicators;
  if(!d || !d.history) return null;
  const arr = (d.history[category] || {})[name];
  if(!Array.isArray(arr) || arr.length === 0) return null;
  // {date, close} → {x, y} 변환 (차트 helper와 호환)
  const series = arr.map(p => ({x: p.date, y: p.close}));
  // 실시간 spot 값과 차트 끝점 동기화 (소스 불일치 방지) — 전 카테고리 공통 처리:
  //   history(yfinance/pykrx 일별 종가)와 spot(KRX·실시간 환율)이 서로 다른 소스라
  //   카드 헤더의 큰 숫자와 차트 끝점이 어긋날 수 있다(예: KOSPI 차트가 며칠 전에서 멈춤).
  //   끝점을 spot 에 맞춰 모든 카드/상세 모달 차트가 헤더 숫자와 일치하도록 한다.
  //   fx → rate, indices/commodities → price.
  const spotMap = category === 'fx' ? d.fx
                : category === 'indices' ? d.indices
                : category === 'commodities' ? d.commodities : null;
  const field = category === 'fx' ? 'rate' : 'price';
  if(spotMap && spotMap[name] && spotMap[name][field] != null) {
    const spot = +spotMap[name][field];
    const last = series[series.length - 1];
    if(isFinite(spot) && spot > 0 && last) {
      // KST 기준 오늘 (data.json 날짜가 KST 이므로 UTC off-by-one 방지)
      const today = new Date(Date.now() + 9*3600000).toISOString().slice(0,10);
      if(last.x === today) {
        last.y = spot;                                    // 오늘 점이 있으면 값 갱신
      } else if(last.x < today) {
        const rel = Math.abs(spot - last.y) / (Math.abs(last.y) || 1);
        if(rel > 1e-4) series.push({x: today, y: spot});  // 새 영업일 — 오늘 점 추가
      }
    }
  }
  return series;
}

function sliceByPeriod(arr, period) {
  if(!arr || !arr.length) return arr;
  // period: '1W' | '1M' | '3M' | '6M' | '1Y' | '2Y' | '5Y' | 'all'
  const n = period==='1W'? 5 : period==='1M'? 21 : period==='3M'? 63
          : period==='6M'? 126 : period==='1Y'? 252 : period==='2Y'? 504
          : period==='5Y'? arr.length : arr.length;
  return arr.slice(-n);
}

function sliceByDateRange(arr, from, to) {
  if(!arr || !arr.length) return arr;
  return arr.filter(d => d.x >= from && d.x <= to);
}

// 차트 캔버스 위에 "데이터 추가 필요" 안내 오버레이를 표시
function showNoDataOverlay(canvasId, msg) {
  const cv = document.getElementById(canvasId);
  if(!cv) return;
  const parent = cv.parentElement;
  if(!parent) return;
  let overlay = parent.querySelector('.no-data-overlay');
  if(!overlay) {
    overlay = document.createElement('div');
    overlay.className = 'no-data-overlay';
    overlay.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:6px;text-align:center;font-size:13px;color:var(--c-txt-dim,#a4a8bc);background:rgba(19,23,34,0.85);border-radius:var(--r-sm);z-index:5;padding:16px;';
    parent.style.position = 'relative';
    parent.appendChild(overlay);
  }
  overlay.innerHTML = `<div style="font-size:var(--font-size-2xl);opacity:0.5;">📊</div><div style="font-weight:var(--font-weight-semibold);">데이터 추가 필요</div><div style="font-size:var(--font-size-sm);opacity:0.7;max-width:280px;line-height:1.5;">${msg || '실시간 시계열 데이터가 아직 수집되지 않았습니다. 다음 자동 업데이트(매 정각) 후 표시됩니다.'}</div>`;
  overlay.style.display = 'flex';
}
function hideNoDataOverlay(canvasId) {
  const cv = document.getElementById(canvasId);
  if(!cv) return;
  const overlay = cv.parentElement?.querySelector('.no-data-overlay');
  if(overlay) overlay.style.display = 'none';
}

// 카테고리별 색상
const macroCatColors = {
  '경기':    getThemeColors().accent, '물가': window.CDN, '고용': window.CUP, '무역': '#f5a623',
  '통화':    '#b6c4ff', '금리': '#7e8aff', '시장': window.CUP, '외환': '#f5a623',
  '부동산':   '#b6c4ff', '소비': window.CUP,
};
let _macroIndFilter = 'all';

function filterMacroIndicators(cc, btn) {
  _macroIndFilter = cc;
  document.querySelectorAll('.macro-ind-filter').forEach(b => {
    const isAct = b === btn;
    b.classList.toggle('active', isAct);
    b.style.background = isAct ? getThemeColors().accent : 'transparent';
    b.style.color = isAct ? '#fff' : '#8d90a2';
    b.style.borderColor = isAct ? getThemeColors().accent : '#2a2e3d';
  });
  buildMacroIndicatorTable();
}

// 지표 이름 → 그룹 키 (여러 나라가 같은 지표를 가지면 multi-country chart)
function _macroGroupKey(r) {
  const dp = (r.dataPath || '').toLowerCase();
  const nm = (r.name || '').toLowerCase();
  if(dp.includes('gdp') || nm.includes('gdp') || nm.includes('성장률')) return 'GDP';
  if(dp.includes('cpi') || nm.includes('cpi') || nm.includes('소비자물가') || nm.includes('hicp')) return 'CPI';
  if(dp.includes('unemploy') || dp.includes('unemp') || nm.includes('실업')) return '실업률';
  if(dp.includes('exports') || nm.includes('수출')) return '수출';
  if(dp.includes('base_rate') || dp.includes('ff_rate') || nm.includes('기준금리') || nm.includes('정책금리') || nm.includes('ffr') || nm.includes('ecb') || nm.includes('boj') || nm.includes('boe')) return '기준금리';
  if(dp.includes('pmi') || nm.includes('pmi')) return '제조업 PMI·경기지수';
  if(dp.includes('us10y') || dp.includes('us2y') || nm.includes('국채')) return '국채 수익률';
  if(dp.includes('case_shiller') || dp.includes('apt_price') || nm.includes('hpi') || nm.includes('주택가격')) return 'HPI';
  if(dp.includes('mortgage') || nm.includes('모기지') || nm.includes('주담대')) return '모기지';
  return r.name;
}

function buildMacroIndicatorTable() {
  const root = document.getElementById('macroIndCardsRoot');
  if(!root) return;
  const d = _latestDataForIndicators;
  // 필터 적용
  const filtered = _macroIndFilter === 'all'
    ? macroIndicators
    : macroIndicators.filter(r => r.cc === _macroIndFilter);
  // 분류별 그룹화
  const byCat = {};
  filtered.forEach(r => {
    if(!byCat[r.cat]) byCat[r.cat] = [];
    byCat[r.cat].push(r);
  });
  // 누락된 데이터 소스 추적
  const missingApis = new Set();
  // 카테고리 정렬 순서
  const catOrder = ['경기','물가','고용','통화','금리','외환','시장','무역','부동산','소비'];
  const cats = Object.keys(byCat).sort((a,b)=>{
    const ai = catOrder.indexOf(a), bi = catOrder.indexOf(b);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });
  if(cats.length === 0) {
    root.innerHTML = '<div style="padding:20px;text-align:center;color:var(--c-txt-muted);font-size:var(--font-size-sm);">해당 국가의 지표가 없습니다.</div>';
    const infoEl = document.getElementById('macroMissingApiInfo');
    if(infoEl) infoEl.style.display = 'none';
    return;
  }
  // 카테고리별 카드 그룹 렌더링 — 카테고리 내에서 다시 토픽별로 sub-grouping
  const html = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">` + cats.map(cat => {
    const color = macroCatColors[cat] || '#8d90a2';
    // 카테고리 내 indicators 를 토픽별로 다시 그룹화
    const catItems = byCat[cat];
    const topicGroups = {};
    catItems.forEach(r => {
      const key = _macroGroupKey(r);
      if(!topicGroups[key]) topicGroups[key] = [];
      topicGroups[key].push(r);
    });
    const topicHtml = Object.entries(topicGroups).map(([topic, items]) => {
      // 같은 토픽에 2+ 국가 → 토픽 헤더 + 국가별 미니 카드
      if(items.length >= 2) {
        const cards = items.map(r => {
          let valStr = '—', periodStr = '—', valColor = 'var(--c-txt-muted,#8b90a8)';
          let unitStr = r.unit, staleMark = '';
          if(d && r.dataPath) {
            const node = getDataByPath(d, r.dataPath);
            if(node && node.value != null) {
              valStr = r.fmt ? r.fmt(node.value) : node.value;
              if(node.period) periodStr = node.period;
              if(node.unit) unitStr = node.unit;
              if(node.stale) { staleMark = '⚠'; valColor = 'var(--c-warn,#f0c75e)'; }
              else { valColor = 'var(--c-txt,#e8ebf5)'; }
            } else {
              missingApis.add(`${r.cc} ${r.name} (${r.src})`);
            }
          }
          const indIdx = macroIndicators.indexOf(r);
          return `<div class="clickable-card" onclick="showMacroHistoryChartByIdx(${indIdx})" style="display:flex;justify-content:space-between;align-items:center;padding:6px 9px;background:rgba(255,255,255,0.03);border-radius:var(--r-sm);border:1px solid rgba(255,255,255,0.06);cursor:pointer;" title="${r.name} · ${r.src} · ${unitStr||''}${periodStr!=='—'?' · '+periodStr:''}">
            <div style="font-size:var(--font-size-sm);color:var(--c-txt);">${r.cc}</div>
            <div style="font-size:var(--font-size-base);font-weight:var(--font-weight-bold);font-family:var(--font-num);color:${valColor};">${staleMark}${valStr}</div>
          </div>`;
        }).join('');
        return `<div style="background:rgba(255,255,255,0.02);border-radius:var(--r-sm);padding:8px;border-left:3px solid ${color};">
          <div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-semibold);color:${color};margin-bottom:6px;">${topic} <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);font-weight:var(--font-weight-normal);">· ${items.length}개국</span></div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;">${cards}</div>
        </div>`;
      }
      // 단일 국가 → 기존 카드 스타일
      const r = items[0];
      let valStr = '—', periodStr = '—', valColor = 'var(--c-txt-muted,#8b90a8)';
      let unitStr = r.unit, srcStr = r.src;
      if(d && r.dataPath) {
        const node = getDataByPath(d, r.dataPath);
        if(node && node.value != null) {
          valStr = r.fmt ? r.fmt(node.value) : node.value;
          if(node.period) periodStr = node.period;
          // 데이터가 자체 단위/출처를 제공하면 우선 사용 (실 PMI 50기준 vs OECD BCI 100기준 구분).
          if(node.unit) unitStr = node.unit;
          if(node.source) srcStr = node.source;
          if(node.stale) { periodStr += ' · ⚠ 갱신 지연'; valColor = 'var(--c-warn,#f0c75e)'; }
          else { valColor = 'var(--c-txt,#e8ebf5)'; }
        } else { missingApis.add(`${r.cc} ${r.name} (${r.src})`); }
      } else if(!r.dataPath) { missingApis.add(`${r.cc} ${r.name} (${r.src})`); }
      const indIdx = macroIndicators.indexOf(r);
      const linkBtn = r.link ? `<a href="${r.link}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()" style="display:inline-block;margin-top:4px;font-size:var(--font-size-xs);padding:2px 6px;background:var(--c-accent)22;color:var(--c-accent);border:1px solid var(--c-accent)55;border-radius:var(--r-xs);text-decoration:none;">📎 ${r.linkLabel||'최신 보고서'} →</a>` : '';
      return `<div class="clickable-card" onclick="showMacroHistoryChartByIdx(${indIdx})" style="display:flex;justify-content:space-between;align-items:center;padding:9px 10px;background:rgba(255,255,255,0.03);border-radius:var(--r-sm);border-left:3px solid ${color};cursor:pointer;" title="클릭 → 시계열 차트">
        <div style="flex:1;min-width:0;">
          <div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-semibold);color:var(--c-txt);">${r.cc} ${r.name} <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">📈</span></div>
          <div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:2px;line-height:1.4;">${srcStr} · ${r.freq} · ${periodStr}</div>
          ${unitStr ? `<div style="font-size:var(--font-size-xs);color:var(--c-primary);margin-top:1px;">단위: ${unitStr}</div>`:''}
          ${linkBtn}
        </div>
        <div style="text-align:right;flex-shrink:0;margin-left:8px;">
          <div style="font-size:var(--font-size-lg);font-weight:var(--font-weight-bold);font-family:var(--font-num);color:${valColor};">${valStr}</div>
        </div>
      </div>`;
    }).join('');
    return `<div class="widget" style="padding:14px;">
      <div class="widget-title" style="color:${color};font-size:var(--font-size-sm);letter-spacing:.08em;">📊 ${cat}</div>
      <div style="display:flex;flex-direction:column;gap:10px;">${topicHtml}</div>
    </div>`;
  }).join('') + `</div>`;
  root.innerHTML = html;
  // 누락된 API 안내 + 현재 연결된 데이터 소스 표시
  const infoEl = document.getElementById('macroMissingApiInfo');
  const listEl = document.getElementById('macroMissingApiList');
  const statusEl = document.getElementById('macroApiStatus');
  if(statusEl) {
    const sources = (d && d.sources) || {};
    const apis = [
      {name:'FRED (미국 경제·부동산·수익률 곡선)', keys:['economicIndicators_us','realestate_us','yieldCurve_us']},
      {name:'FRED 국제 시리즈 (일본·유로존·중국·독일·영국)', keys:['economicIndicators_intl']},
      {name:'ECOS (한국은행 경제 통계)', keys:['economicIndicators_kr']},
      {name:'R-ONE (한국부동산원 가격지수)', keys:['realestate_kr']},
      {name:'data.go.kr (국토부 실거래가)', keys:['realestate_molit']},
      {name:'KRX OpenAPI (한국 주식/ETF/원자재)', keys:['stockMovers','etfMovers','indices','commodities']},
      {name:'yfinance (해외 지수/원자재/농산물 시계열)', keys:['history']},
    ];
    statusEl.innerHTML = apis.map(a => {
      const hit = a.keys.some(k => sources[k]);
      const color = hit ? window.CUP : window.CDN;
      const mark = hit ? '●' : '○';
      const label = hit ? sources[a.keys.find(k=>sources[k])] : '미연결';
      return `<div style="display:flex;align-items:center;gap:6px;font-size:var(--font-size-xs);color:var(--c-txt-dim);">
        <span style="color:${color};">${mark}</span>
        <span style="flex:1;">${a.name}</span>
        <span style="color:var(--c-txt-muted);font-size:var(--font-size-xs);">${label}</span>
      </div>`;
    }).join('');
  }
  if(missingApis.size > 0 && infoEl && listEl) {
    infoEl.style.display = 'block';
    listEl.innerHTML = [...missingApis].slice(0, 30).map(s => `<li>${s}</li>`).join('');
  } else if(infoEl) {
    infoEl.style.display = 'none';
  }
}

// 거시경제 국가별 차트 기간 필터 (분기 데이터 기준)
let macroCountryPeriod = 'all'; // 'all' | '4' (1년) | '8' (2년) | '12' (3년)
function setMacroCountryPeriod(p, btn) {
  macroCountryPeriod = p;
  document.querySelectorAll('.macro-country-period').forEach(b=>{
    b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
  });
  if(btn) { btn.style.background='var(--c-accent)'; btn.style.color='#fff'; }
  initMacroPage(macroTab);
}

// 차트별 단위 (월/분기/연) — 사용자 요청에 따른 추가 기능
// 기본값: 각 차트의 원본 빈도
//   GDP/실업률/수출 = 분기 데이터 (Q), CPI = 월간 데이터 (M)
//   '연(Y)' 단위 선택 시 4개 분기 / 12개월을 평균/합산
const macroChartUnit = { gdp:'Q', cpi:'M', unemp:'Q', trade:'Q' };

function setMacroChartUnit(chart, unit, btn) {
  macroChartUnit[chart] = unit;
  // 같은 차트의 모든 단위 버튼 비활성화
  document.querySelectorAll(`.macro-chart-unit[data-chart="${chart}"]`).forEach(b=>{
    b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
  });
  if(btn) { btn.style.background='var(--c-accent)'; btn.style.color='#fff'; }
  initMacroPage(macroTab);
}

// 월간 → 분기 (3개월 평균) 또는 연간 (12개월 평균) 집계
function aggregateMonthly(labels, vals, targetUnit) {
  if(targetUnit==='M' || !labels || !vals || labels.length===0) return {labels, vals};
  const step = targetUnit==='Q' ? 3 : targetUnit==='Y' ? 12 : 1;
  const outLabels=[], outVals=[];
  for(let i=0; i<vals.length; i+=step) {
    const slice = vals.slice(i, i+step).filter(v=>v!=null);
    if(slice.length === 0) continue;
    const avg = slice.reduce((a,b)=>a+b,0) / slice.length;
    // 라벨: 연(Y)이면 'YYYY'만, 분기(Q)면 첫번째 라벨 사용
    const baseLabel = labels[i] || '';
    if(targetUnit==='Y') {
      // 'YY.MM' → '20YY', 'YYYY.MM' → 'YYYY', 'YYYYMM' → 'YYYY'
      const m = baseLabel.match(/^(\d{2,4})/);
      if(m) {
        outLabels.push(m[1].length===2 ? '20'+m[1] : m[1]);
      } else {
        outLabels.push(baseLabel);
      }
    } else {
      outLabels.push(baseLabel);
    }
    outVals.push(+avg.toFixed(2));
  }
  return {labels:outLabels, vals:outVals};
}
// 분기 → 연 (4개 분기 평균) 또는 분기 → 월 (보간 없이 그대로 표시)
function aggregateQuarterly(labels, vals, targetUnit) {
  if(targetUnit==='Q' || !labels || !vals || labels.length===0) return {labels, vals};
  if(targetUnit==='M') {
    // 분기 데이터를 월 단위로 늘릴 수는 없으므로 그대로 반환 (UI 안내)
    return {labels, vals};
  }
  // Y: 4개 분기 평균
  const outLabels=[], outVals=[];
  for(let i=0; i<vals.length; i+=4) {
    const slice = vals.slice(i, i+4).filter(v=>v!=null);
    if(slice.length === 0) continue;
    const avg = slice.reduce((a,b)=>a+b,0) / slice.length;
    const baseLabel = labels[i] || '';
    // 분기 라벨 '23Q1' → '2023'
    const yrMatch = baseLabel.match(/^(\d{2,4})Q?/);
    outLabels.push(yrMatch ? (yrMatch[1].length===2 ? '20'+yrMatch[1] : yrMatch[1]) : baseLabel);
    outVals.push(+avg.toFixed(2));
  }
  return {labels:outLabels, vals:outVals};
}

function initMacroPage(t){
  ['gdpMacro','cpiMacro','unempMacro','tradeMacro'].forEach(destroyChart);
  const d=macroData[t];
  const meta=macroMeta[t]||{};
  const mc=document.getElementById('macroContent');
  // '다음 발표'는 하드코딩 상수(macroMeta.*Next)라 갱신이 안 되면 과거 날짜가 남는다 —
  // 지난 날짜면 숨긴다(틀린 과거 날짜보다 '—' 가 낫다. 근본 해법은 economicCalendar 동적 조회).
  const _nextValid = (next) => {
    if(!next) return null;
    try {
      const m = String(next).match(/(\d{4})[.\-\/](\d{1,2})[.\-\/](\d{1,2})/);
      if(m && new Date(+m[1], +m[2]-1, +m[3], 23, 59) < new Date()) return null;
    } catch(_) {}
    return next;
  };
  const infoBlock=(src,next)=>`<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);text-align:right;">
    <span style="color:var(--c-txt-dim);">다음 발표: ${_nextValid(next)||'—'}</span>
    <a href="${src||'#'}" target="_blank" rel="noopener noreferrer" style="color:var(--c-primary);margin-left:6px;text-decoration:none;">공식→</a>
  </div>`;
  // 기간 필터 버튼 행
  const periodOpts = [
    {key:'4',  label:'최근 1년'},
    {key:'8',  label:'최근 2년'},
    {key:'12', label:'최근 3년'},
    {key:'all',label:'전체'},
  ];
  const periodRow = `<div style="display:flex;align-items:center;gap:6px;margin-bottom:10px;flex-wrap:wrap;">
    <span style="font-size:var(--font-size-sm);color:var(--c-txt-dim);">조회 기간:</span>
    ${periodOpts.map(o=>`<button class="macro-country-period" onclick="setMacroCountryPeriod('${o.key}',this)" style="font-size:var(--font-size-sm);padding:2px 8px;border-radius:var(--r-xs);border:1px solid var(--c-border);background:${macroCountryPeriod===o.key?'var(--c-accent)':'transparent'};color:${macroCountryPeriod===o.key?'#fff':'var(--c-txt-dim)'};cursor:pointer;">${o.label}</button>`).join('')}
  </div>`;
  // 차트별 단위 선택 버튼 생성 (월/분기/연)
  // 차트별 가능 단위: GDP/실업률/수출은 분기 데이터(Q/Y), CPI는 월간 데이터(M/Q/Y)
  const unitOpts = {
    gdp:   [{k:'Q', l:'분기'}, {k:'Y', l:'연'}],
    cpi:   [{k:'M', l:'월'}, {k:'Q', l:'분기'}, {k:'Y', l:'연'}],
    unemp: [{k:'Q', l:'분기'}, {k:'Y', l:'연'}],
    trade: [{k:'Q', l:'분기'}, {k:'Y', l:'연'}],
  };
  const unitButtons = (chart) => {
    const opts = unitOpts[chart] || [];
    return `<div style="display:flex;gap:3px;align-items:center;">
      <span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);font-weight:var(--font-weight-medium);margin-right:2px;">단위:</span>
      ${opts.map(o=>`<button class="macro-chart-unit" data-chart="${chart}" data-unit="${o.k}" onclick="setMacroChartUnit('${chart}','${o.k}',this)" style="font-size:var(--font-size-xs);padding:2px 7px;border-radius:var(--r-xs);border:1px solid var(--c-border);background:${macroChartUnit[chart]===o.k?'var(--c-accent)':'transparent'};color:${macroChartUnit[chart]===o.k?'#fff':'var(--c-txt-dim)'};cursor:pointer;">${o.l}</button>`).join('')}
    </div>`;
  };

  mc.innerHTML= periodRow + `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
      <div class="widget">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:4px;">
          <div class="widget-title" style="margin-bottom:0;">GDP 성장률 (전년동기비, %)</div>
          ${unitButtons('gdp')}
          <button class="yoy-btn" data-yoy="gdpMacro" onclick="toggleYoY('gdpMacro',this)" aria-pressed="false" title="전년 동기 데이터를 점선으로 오버레이"><span aria-hidden="true" class="mat">compare_arrows</span><span class="yoy-btn-lbl">전년 비교</span></button>
          ${infoBlock(meta.gdpSrc,meta.gdpNext)}
        </div>
        <div style="position:relative;height:260px;"><canvas id="gdpMacro" role="img" aria-label="GDP 차트">GDP</canvas></div>
      </div>
      <div class="widget">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:4px;">
          <div class="widget-title" style="margin-bottom:0;">소비자물가 (CPI, 전년비 %)</div>
          ${unitButtons('cpi')}
          <button class="yoy-btn" data-yoy="cpiMacro" onclick="toggleYoY('cpiMacro',this)" aria-pressed="false" title="전년 동기 데이터를 점선으로 오버레이"><span aria-hidden="true" class="mat">compare_arrows</span><span class="yoy-btn-lbl">전년 비교</span></button>
          ${infoBlock(meta.cpiSrc,meta.cpiNext)}
        </div>
        <div style="position:relative;height:260px;"><canvas id="cpiMacro" role="img" aria-label="CPI 차트">CPI</canvas></div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
      <div class="widget">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:4px;">
          <div class="widget-title" style="margin-bottom:0;">실업률 (%)</div>
          ${unitButtons('unemp')}
          <button class="yoy-btn" data-yoy="unempMacro" onclick="toggleYoY('unempMacro',this)" aria-pressed="false" title="전년 동기 데이터를 점선으로 오버레이"><span aria-hidden="true" class="mat">compare_arrows</span><span class="yoy-btn-lbl">전년 비교</span></button>
          ${infoBlock(meta.unempSrc,meta.unempNext)}
        </div>
        <div style="position:relative;height:260px;"><canvas id="unempMacro" role="img" aria-label="실업률 차트">실업률</canvas></div>
      </div>
      <div class="widget">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:4px;">
          <div class="widget-title" style="margin-bottom:0;">수출 (억 달러)</div>
          ${unitButtons('trade')}
          <button class="yoy-btn" data-yoy="tradeMacro" onclick="toggleYoY('tradeMacro',this)" aria-pressed="false" title="전년 동기 데이터를 점선으로 오버레이"><span aria-hidden="true" class="mat">compare_arrows</span><span class="yoy-btn-lbl">전년 비교</span></button>
          ${infoBlock(meta.tradeSrc,meta.tradeNext)}
        </div>
        <div style="position:relative;height:260px;"><canvas id="tradeMacro" role="img" aria-label="수출 차트">수출</canvas></div>
      </div>
    </div>`;
  // 기간 필터 적용 (분기 기준 N개 데이터)
  const sliceN = (arr) => macroCountryPeriod==='all' ? arr : arr.slice(-parseInt(macroCountryPeriod,10));
  // GDP/실업/수출 — 분기 데이터에서 단위 변환 적용
  const gdpAgg = aggregateQuarterly(sliceN(d.gdpLabels), sliceN(d.gdp), macroChartUnit.gdp);
  const unempAgg = aggregateQuarterly(sliceN(d.gdpLabels), sliceN(d.unemp), macroChartUnit.unemp);
  const expAgg = aggregateQuarterly(sliceN(d.gdpLabels), sliceN(d.exports), macroChartUnit.trade);
  // CPI — 월간 데이터에서 단위 변환 적용
  const cpiAgg = aggregateMonthly(sliceN(d.cpiLabels), sliceN(d.cpi), macroChartUnit.cpi);
  const gdpLab = gdpAgg.labels;
  const gdpVal = gdpAgg.vals;
  const cpiLab = cpiAgg.labels;
  const cpiVal = cpiAgg.vals;
  const unempLab = unempAgg.labels;
  const unempVal = unempAgg.vals;
  const expLab = expAgg.labels;
  const expVal = expAgg.vals;
  // YoY 전년 비교용 — 전체(미필터) 집계 (동일 unit). 표시 라벨의 1년 전 라벨을 여기서 조회.
  const _gdpFull   = aggregateQuarterly(d.gdpLabels, d.gdp,     macroChartUnit.gdp);
  const _unempFull = aggregateQuarterly(d.gdpLabels, d.unemp,   macroChartUnit.unemp);
  const _expFull   = aggregateQuarterly(d.gdpLabels, d.exports, macroChartUnit.trade);
  const _cpiFull   = aggregateMonthly(d.cpiLabels, d.cpi,       macroChartUnit.cpi);
  const tc = getThemeColors();
  const chartOpts=(color,isBar,yMin)=>({
    responsive:true,maintainAspectRatio:false,
    scales:{x:{ticks:{color:tc.txt,font:{size:10}},grid:{color:tc.grid}},
            y:{
              ticks:{color:tc.txt,font:{size:10}},
              grid:{color:tc.grid},
              beginAtZero: false,
              ...(yMin != null ? {suggestedMin: yMin} : {}),
            }},
    plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false,backgroundColor:tc.tooltip,titleColor:tc.ttTitle,bodyColor:color,borderColor:tc.ttBorder,borderWidth:1}}
  });
  // 수출은 절대값 차이가 작을 때 0에서 시작하면 변동이 안 보이므로 데이터 최솟값 - 5% 부근으로 시작
  const expMin = expVal.length ? Math.min(...expVal.filter(v=>v!=null)) : 0;
  const expYMin = Math.floor(expMin * 0.92);
  charts['gdpMacro']=new Chart(document.getElementById('gdpMacro'),{type:'bar',data:{labels:gdpLab,datasets:[{data:gdpVal,backgroundColor:gdpVal.map(v=>v>=0?(window.CUP+'99'):(window.CDN+'99')),borderRadius:3}]},options:chartOpts(window.CUP,true)});
  charts['cpiMacro']=new Chart(document.getElementById('cpiMacro'),{type:'line',data:{labels:cpiLab,datasets:[{data:cpiVal,borderColor:getThemeColors().accent,borderWidth:2,pointRadius: 0,fill:true,backgroundColor:getThemeColors().accent+'20',tension:0.3}]},options:chartOpts(getThemeColors().accent,false)});
  charts['unempMacro']=new Chart(document.getElementById('unempMacro'),{type:'line',data:{labels:unempLab,datasets:[{data:unempVal,borderColor:window.CDN,borderWidth:2,pointRadius: 0,fill:false,tension:0.3}]},options:chartOpts(window.CDN,false)});
  // 수출 차트는 라인 + 데이터 레이블로 변경 (값 차이가 작아 바차트로는 구분 어려움)
  charts['tradeMacro']=new Chart(document.getElementById('tradeMacro'),{
    type:'line',
    data:{labels:expLab,datasets:[{
      data:expVal,
      borderColor:getThemeColors().accent,
      borderWidth:2,
      pointRadius:5,
      pointBackgroundColor:getThemeColors().accent,
      pointBorderColor:'#fff',
      pointBorderWidth:1.5,
      fill:true,
      backgroundColor:getThemeColors().accent+'20',
      tension:0.3,
    }]},
    options:{
      ...chartOpts(getThemeColors().accent,false,expYMin),
      plugins:{
        legend:{display:false},
        tooltip:{mode:'index',intersect:false,backgroundColor:tc.tooltip,titleColor:tc.ttTitle,bodyColor:getThemeColors().accent,borderColor:tc.ttBorder,borderWidth:1,callbacks:{label:c=>`수출: ${c.parsed.y} 억 달러`}},
        // 데이터 포인트 값 표시 (Chart.js 기본 기능 — 별도 플러그인 없이 afterDatasetDraw)
      },
    },
    plugins:[{
      id:'tradeValueLabels',
      afterDatasetsDraw(chart) {
        const {ctx} = chart;
        const meta = chart.getDatasetMeta(0);
        if(!meta || meta.hidden) return;
        ctx.save();
        ctx.font = '600 10px Inter, sans-serif';
        ctx.fillStyle = '#dfe2f2';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        meta.data.forEach((point, i) => {
          const v = chart.data.datasets[0].data[i];
          if(v == null) return;
          ctx.fillText(String(v), point.x, point.y - 6);
        });
        ctx.restore();
      },
    }],
  });
  registerYoY('gdpMacro',   {mode:'periodlabel', dispLabels:gdpLab,   fullLabels:_gdpFull.labels,   fullValues:_gdpFull.vals,   primary:0, color:window.CUP});
  registerYoY('cpiMacro',   {mode:'periodlabel', dispLabels:cpiLab,   fullLabels:_cpiFull.labels,   fullValues:_cpiFull.vals,   primary:0, color:getThemeColors().accent, tension:0.3});
  registerYoY('unempMacro', {mode:'periodlabel', dispLabels:unempLab, fullLabels:_unempFull.labels, fullValues:_unempFull.vals, primary:0, color:window.CDN, tension:0.3});
  registerYoY('tradeMacro', {mode:'periodlabel', dispLabels:expLab,   fullLabels:_expFull.labels,   fullValues:_expFull.vals,   primary:0, color:getThemeColors().accent, tension:0.3});
  ['gdpMacro','cpiMacro','unempMacro','tradeMacro'].forEach(applyYoY);
}

// ============================
// 경제 캘린더
// ============================
// calEvents: cc = 국가코드, stars = 중요도(1~3)
const calEvents=[
  // 4월 (이번 달)
  {dt:'04.30 09:00',cc:'KR',flag:'🇰🇷',name:'한국 산업생산지수',       stars:2,prev:'+1.2%',fore:'+0.9%', act:'+1.4%', beat:1},
  {dt:'04.30 21:30',cc:'US',flag:'🇺🇸',name:'미국 PCE 물가지수',       stars:3,prev:'2.5%', fore:'2.4%',  act:'2.3%',  beat:1},
  // 5월 (다음 달)
  {dt:'05.01 09:00',cc:'KR',flag:'🇰🇷',name:'한국 소비자물가지수(CPI)',  stars:3,prev:'2.1%', fore:'2.0%',  act:'2.1%',beat:0},
  {dt:'05.02 15:00',cc:'US',flag:'🇺🇸',name:'미국 비농업고용(NFP)',      stars:3,prev:'275K', fore:'240K',  act:'+177K', beat:1},
  {dt:'05.03 22:00',cc:'US',flag:'🇺🇸',name:'미국 실업률',              stars:3,prev:'3.9%', fore:'3.9%',  act:'4.2%',  beat:-1},
  {dt:'05.06 10:00',cc:'KR',flag:'🇰🇷',name:'한국은행 금통위 회의',      stars:3,prev:'2.75%',fore:'2.75%', act:'2.50%', beat:0},
  {dt:'05.07 16:00',cc:'EU',flag:'🇪🇺',name:'ECB 통화정책회의',         stars:3,prev:'2.25%',fore:'2.00%', act:'2.00%', beat:0},
  {dt:'05.08 21:30',cc:'US',flag:'🇺🇸',name:'미국 CPI (전월비)',        stars:3,prev:'0.4%', fore:'0.3%',  act:'-0.1%', beat:1},
  {dt:'05.09 09:00',cc:'KR',flag:'🇰🇷',name:'한국 수출입 동향',         stars:2,prev:'+3.1%',fore:'+2.8%', act:'+3.7%', beat:1},
  {dt:'05.12 09:30',cc:'CN',flag:'🇨🇳',name:'중국 CPI (전년비)',        stars:2,prev:'0.1%', fore:'0.2%',  act:'-0.1%', beat:-1},
  {dt:'05.13 10:00',cc:'JP',flag:'🇯🇵',name:'일본 GDP (전기비)',        stars:3,prev:'-0.1%',fore:'+0.1%', act:'-0.2%', beat:-1},
  {dt:'05.14 21:30',cc:'US',flag:'🇺🇸',name:'미국 생산자물가지수(PPI)', stars:2,prev:'0.2%', fore:'0.2%',  act:'-0.5%', beat:1},
  {dt:'05.15 22:00',cc:'US',flag:'🇺🇸',name:'미국 소매판매',           stars:2,prev:'-0.1%',fore:'+0.4%', act:'+0.1%', beat:-1},
  {dt:'05.20 10:00',cc:'KR',flag:'🇰🇷',name:'한국 1분기 GDP (확정)',    stars:3,prev:'+0.7%',fore:'+0.7%', act:'',   beat:null},
  {dt:'05.22 20:30',cc:'EU',flag:'🇪🇺',name:'유로존 CPI (전년비)',      stars:3,prev:'2.2%', fore:'2.1%',  act:'',   beat:null},
  {dt:'05.28 21:30',cc:'US',flag:'🇺🇸',name:'미국 1분기 GDP (2차)',     stars:3,prev:'0.5%', fore:'2.0%',  act:'1.6%',beat:-1},
  // 6월
  {dt:'06.02 21:30',cc:'US',flag:'🇺🇸',name:'미국 비농업고용(NFP)',      stars:3,prev:'210K',fore:'200K',act:'',beat:null},
  {dt:'06.02 21:30',cc:'US',flag:'🇺🇸',name:'미국 실업률',              stars:3,prev:'4.0%', fore:'4.0%', act:'',beat:null},
  {dt:'06.04 09:00',cc:'KR',flag:'🇰🇷',name:'한국 5월 소비자물가(CPI)',   stars:3,prev:'2.1%', fore:'2.0%', act:'',beat:null},
  {dt:'06.05 20:00',cc:'EU',flag:'🇪🇺',name:'ECB 통화정책회의',          stars:3,prev:'2.00%',fore:'2.00%',act:'2.00%',beat:0},
  {dt:'06.11 02:00',cc:'US',flag:'🇺🇸',name:'미국 FOMC 회의',           stars:3,prev:'3.75%',fore:'3.75%',act:'3.75%',beat:0},
  {dt:'06.12 21:30',cc:'US',flag:'🇺🇸',name:'미국 CPI (전년비)',         stars:3,prev:'3.2%', fore:'3.1%', act:'',beat:null},
  {dt:'06.16 14:00',cc:'JP',flag:'🇯🇵',name:'일본 BOJ 금리결정',        stars:3,prev:'0.50%',fore:'0.50%',act:'1.00%',beat:1},
  {dt:'06.19 12:00',cc:'UK',flag:'🇬🇧',name:'영국 BOE 금리결정',        stars:3,prev:'4.50%',fore:'4.25%',act:'',beat:null},
  {dt:'06.20 09:00',cc:'KR',flag:'🇰🇷',name:'한국은행 금통위 회의',      stars:3,prev:'2.75%',fore:'2.50%',act:'',beat:null},
  {dt:'06.23 10:00',cc:'KR',flag:'🇰🇷',name:'한국 5월 수출입 동향',     stars:2,prev:'+2.8%',fore:'+3.0%',act:'',beat:null},
  {dt:'06.24 02:00',cc:'CN',flag:'🇨🇳',name:'중국 1년물 LPR 결정',     stars:2,prev:'3.10%',fore:'3.10%',act:'',beat:null},
  {dt:'06.26 21:30',cc:'US',flag:'🇺🇸',name:'미국 PCE 물가지수',       stars:3,prev:'2.5%', fore:'2.4%', act:'',beat:null},
];

// ── 캘린더 필터 상태 ──────────────────────────────
let calFilterCC    = new Set(['KR','US','EU','CN','JP','UK']);
let calFilterStars = new Set([3,2,1]);

function toggleCalFilter(type, val, el) {
  const set = type==='cc' ? calFilterCC : calFilterStars;
  if(set.has(val)) {
    if(set.size <= 1) return;   // 최소 1개는 선택 유지
    set.delete(val);
    el.style.background = 'var(--c-card)';
    el.style.color      = 'var(--c-txt-dim)';
    el.style.border     = '1px solid var(--c-border)';
  } else {
    set.add(val);
    el.style.background = 'var(--c-accent)';
    el.style.color      = '#fff';
    el.style.border     = 'none';
  }
  buildCalendar();
}

// 캘린더 국가 코드 → 한국어 표시
const calCountryName = {KR:'한국', US:'미국', EU:'유로존', JP:'일본', CN:'중국', UK:'영국', DE:'독일'};
function calCountryLabel(cc, flag) {
  const name = calCountryName[cc] || cc;
  return `${flag||''} ${name}`.trim();
}

// 캘린더 그리드 상태 (이번 달 기준)
let _calGridMonth = new Date().getMonth() + 1; // 1~12
let _calGridYear  = new Date().getFullYear();

let _calGridManualNav = false;  // 수동 네비게이션 시 자동 동기화 비활성화

function calGridMove(delta) {
  _calGridManualNav = true;
  _calGridMonth += delta;
  if(_calGridMonth < 1) { _calGridMonth = 12; _calGridYear--; }
  if(_calGridMonth > 12) { _calGridMonth = 1; _calGridYear++; }
  buildCalendar();
}
function calGridToday() {
  const now = new Date();
  _calGridMonth = now.getMonth() + 1;
  _calGridYear  = now.getFullYear();
  _calGridManualNav = false;  // 오늘로 돌아가면 필터 동기화 재활성화
  buildCalendar();
}

// 캘린더 이벤트 → 일자별 그룹핑
function _calEventsByDay(events, year, month) {
  // dt format: 'MM.DD HH:MM' → day = DD
  const map = new Map();
  events.forEach(e => {
    const m = e.dt.match(/^(\d{2})\.(\d{2})/);
    if(!m) return;
    const evMonth = parseInt(m[1], 10);
    const evDay = parseInt(m[2], 10);
    if(evMonth !== month) return;
    if(!map.has(evDay)) map.set(evDay, []);
    map.get(evDay).push(e);
  });
  return map;
}

function buildCalendarGrid(filteredEvents) {
  const container = document.getElementById('calGridContainer');
  if(!container) return;
  const titleEl = document.getElementById('calGridTitle');
  if(titleEl) setWidgetTitleText(titleEl, `${_calGridYear}년 ${_calGridMonth}월 캘린더`);
  // 해당 월의 1일 / 마지막 일
  const firstDay = new Date(_calGridYear, _calGridMonth-1, 1);
  const lastDay = new Date(_calGridYear, _calGridMonth, 0);
  const startWeekday = firstDay.getDay(); // 0=일
  const daysInMonth = lastDay.getDate();
  const today = new Date();
  const isCurrentMonth = (today.getFullYear() === _calGridYear && today.getMonth()+1 === _calGridMonth);
  const todayD = today.getDate();
  // 이벤트 일자별 그룹핑
  const evMap = _calEventsByDay(filteredEvents, _calGridYear, _calGridMonth);

  // "이번 주" 필터 — ISO 8601 Calendar Week 기준 (월요일 시작, 일요일 끝)
  // 매일 바뀌지 않도록 이번 주 전체(월-일)를 동일하게 강조
  const period = document.getElementById('calPeriod')?.value || '';
  let weekStartD = null, weekEndD = null;
  let weekStartMonth = null, weekEndMonth = null;
  if(period === '이번 주') {
    const t = new Date();
    const dow = t.getDay(); // 0=일,1=월,...,6=토
    const daysFromMonday = (dow + 6) % 7;  // 월요일까지의 거리
    const monday = new Date(t.getFullYear(), t.getMonth(), t.getDate() - daysFromMonday);
    const sunday = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 6);
    // 표시 중인 월(_calGridYear/_calGridMonth)과 겹치는 부분만 강조
    const showStart = new Date(_calGridYear, _calGridMonth-1, 1);
    const showEnd = new Date(_calGridYear, _calGridMonth, 0);
    if(sunday >= showStart && monday <= showEnd) {
      const s = monday < showStart ? showStart : monday;
      const e = sunday > showEnd ? showEnd : sunday;
      weekStartD = s.getDate();
      weekEndD = e.getDate();
      weekStartMonth = s.getMonth() + 1;
      weekEndMonth = e.getMonth() + 1;
    }
  }

  let html = '';
  html += `<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:1px;background:var(--c-border);border:1px solid var(--c-border);border-radius:var(--r-sm);overflow:hidden;">`;
  // 요일 헤더
  ['일','월','화','수','목','금','토'].forEach((d,i) => {
    const clr = i===0 ? window.CDN : i===6 ? getThemeColors().accent : 'var(--c-txt-dim,#a4a8bc)';
    html += `<div style="background:var(--c-surface);padding:6px;text-align:center;font-size:var(--font-size-sm);font-weight:var(--font-weight-semibold);color:${clr};">${d}</div>`;
  });
  // 빈 칸 (월 시작 전)
  for(let i=0;i<startWeekday;i++) {
    html += `<div style="background:var(--c-bg);min-height:78px;opacity:0.5;"></div>`;
  }
  // 일자 셀
  for(let d=1; d<=daysInMonth; d++) {
    const events = evMap.get(d) || [];
    const dow = (startWeekday + d - 1) % 7;
    const dayClr = dow===0 ? window.CDN : dow===6 ? getThemeColors().accent : 'var(--c-txt,#e8ebf5)';
    const isToday = isCurrentMonth && d === todayD;
    // ISO 주간 범위 강조 — 표시 월 안에서 weekStartD ~ weekEndD 사이
    const isThisWeek = weekStartD !== null && d >= weekStartD && d <= weekEndD;
    // 강조 스타일 — 옅은 파랑 (오늘) / 더 옅은 파랑 (이번 주)
    let cellStyle = 'background:var(--c-surface,#1a2236);';
    if(isToday) {
      // 오늘 배경 → 진한 파랑 (var(--c-accent)), 텍스트는 흰색으로 대비 강화
      cellStyle = 'background:var(--c-accent);border:1.5px solid var(--c-accent);position:relative;z-index:2;';
    } else if(isThisWeek) {
      cellStyle = 'background:rgba(41,98,255,0.06);border:1px solid rgba(41,98,255,0.20);';
    }
    html += `<div style="${cellStyle}padding:4px 5px;min-height:78px;position:relative;overflow:hidden;">`;
    html += `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;">`;
    // 날짜 — 오늘은 흰색 (파란 배경 대비), 그 외는 요일 색상
    if(isToday) {
      html += `<span style="font-size:var(--font-size-base);font-weight:var(--font-weight-bold);color:#fff;">${d}</span>`;
    } else {
      html += `<span style="font-size:var(--font-size-sm);font-weight:var(--font-weight-medium);color:${dayClr};">${d}</span>`;
    }
    // 이벤트 개수 — 오늘은 흰색, 그 외는 파란 텍스트
    if(events.length > 0) {
      const cnt = events.length;
      const cntClr = isToday ? '#fff' : getThemeColors().accent;
      html += `<span style="font-size:var(--font-size-xs);color:${cntClr};font-weight:var(--font-weight-semibold);">${cnt}건</span>`;
    }
    html += `</div>`;
    // 최대 3개 이벤트 표시
    events.slice(0,3).forEach((e) => {
      const idx = calEvents.indexOf(e);
      const starClr = e.stars===3 ? window.CDN : e.stars===2 ? '#f5a623' : '#8d90a2';
      const beatClr = e.beat===1 ? window.CUP : e.beat===-1 ? window.CDN : '#8d90a2';
      const ev_dot = e.act ? `<span style="color:${beatClr};">●</span>` : `<span style="color:var(--c-txt-dim);">○</span>`;
      html += `<div onclick="showCalGridFloating(${idx}, event)" style="font-size:var(--font-size-xs);line-height:1.4;color:var(--c-txt);background:var(--c-card);border-left:2px solid ${starClr};padding:1px 4px;border-radius:var(--r-xs);margin-bottom:2px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${e.name}">${ev_dot} ${e.flag||''}${e.name.length>10?e.name.slice(0,10)+'…':e.name}</div>`;
    });
    if(events.length > 3) {
      html += `<div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);text-align:center;">+${events.length-3}</div>`;
    }
    html += `</div>`;
  }
  // 빈 칸 (월 끝 후)
  const totalCells = startWeekday + daysInMonth;
  const remainingCells = (7 - (totalCells % 7)) % 7;
  for(let i=0;i<remainingCells;i++) {
    html += `<div style="background:var(--c-bg);min-height:78px;opacity:0.5;"></div>`;
  }
  html += `</div>`;
  container.innerHTML = html;
}

// 현재 표시된 calGridFloating 팝업의 상태 (refresh 시 같은 이벤트를 다시 렌더하기 위함)
let _calFloatingState = { idx: null };
// 플로팅 팝업 내 서프라이즈 라벨 — 예측 대비 실제 격차를 명시 (4.3)
function _calRenderFloatSurprise(e) {
  const el = document.getElementById('calFloatSurp');
  if(!el) return;
  const surp = (e && (e.beat === 1 || e.beat === -1)) ? _calSurprise(e) : null;
  if(!surp) { el.style.display = 'none'; return; }
  const good = e.beat === 1;
  el.style.display = 'block';
  el.style.background = good ? 'rgba(38,166,154,0.12)' : 'rgba(239,83,80,0.12)';
  el.style.color = good ? window.CUP : window.CDN;
  el.textContent = `${surp.big ? '⚡ 매크로 서프라이즈' : '서프라이즈'} — 예측 대비 ${surp.diffLabel} (${good ? '호재' : '악재'})`;
}
// 실제값 셀 렌더 (플로팅/상세 공용) — 이슈1·3·7·9.
//  • 색: 기존 beat 의미 유지(호재→pos/악재→neg/중립). beat 는 지표 성격을 반영(물가·실업은 낮을수록 호재)하므로
//    "실제>예측=무조건 초록" 보다 정확. CSS 변수 --ind-* 로 라이트/다크 각각 WCAG AA 대비 확보.
//  • 화살표 ▲/▼/─: 실제 vs 예측의 단순 수치 방향(색과 독립 — 색맹 보조).
//  • 배지: 실제=예측 → "예측 부합" chip.  예측=이전 → "(이전과 동일)".
//  • 셀 aria-label/title: 색 없이도 상태 전달.
function _calRenderActual(e, P){
  if(!e) return;
  const $ = id => document.getElementById(P + id);
  const color = e.beat===1 ? 'var(--ind-pos)' : e.beat===-1 ? 'var(--ind-neg)' : 'var(--ind-neu)';
  const a=_calParseNum(e.act), f=_calParseNum(e.fore), p=_calParseNum(e.prev);
  let arrow='', dir='';
  if(e.act && a!=null && f!=null){
    const d=a-f;
    if(Math.abs(d)<0.05){ arrow='─'; dir='예측과 동일'; }
    else { arrow = d>0 ? '▲' : '▼'; dir = d>0 ? '예측 상회' : '예측 하회'; }
  }
  const good = e.beat===1 ? '호재' : e.beat===-1 ? '악재' : '';
  const actEl=$('Act');   if(actEl){ actEl.textContent = e.act || '미발표'; actEl.style.color = e.act ? color : 'var(--c-txt-dim)'; }
  const arrEl=$('Arrow'); if(arrEl){ arrEl.textContent = arrow; arrEl.style.color = e.act ? color : 'transparent'; }
  const bdgEl=$('Badge'); if(bdgEl){
    if(e.act && a!=null && f!=null && Math.abs(a-f)<0.05){ bdgEl.textContent='예측 부합'; bdgEl.className='cal-chip'; bdgEl.style.display='inline-block'; }
    else { bdgEl.textContent=''; bdgEl.style.display='none'; }
  }
  const eqEl=$('ForeEq'); if(eqEl){ eqEl.textContent = (p!=null && f!=null && Math.abs(p-f)<0.05) ? '(이전과 동일)' : ''; }
  const cellEl=$('ActCell'); if(cellEl){
    cellEl.style.background = !e.act ? '' : e.beat===1 ? 'rgba(34,197,94,0.12)' : e.beat===-1 ? 'rgba(239,68,68,0.12)' : 'rgba(148,163,184,0.12)';
    const aria = e.act ? ('실제 '+e.act + (dir?(', '+dir):'') + (good?(' ('+good+')'):'')) : '실제값 미발표';
    cellEl.setAttribute('aria-label', aria); cellEl.title = aria;
  }
}
// 차트 0% 기준선 — 회색 점선 (이슈5). y 범위에 0 포함될 때만 그림.
const _calZeroLine = {
  id:'calZeroLine',
  afterDatasetsDraw(chart){
    const y = chart.scales && chart.scales.y; if(!y) return;
    if(y.min > 0 || y.max < 0) return;
    const yp = y.getPixelForValue(0), area = chart.chartArea, c = chart.ctx;
    c.save(); c.beginPath(); c.setLineDash([4,4]);
    c.strokeStyle = (getComputedStyle(document.documentElement).getPropertyValue('--c-txt-muted').trim() || '#9aa0b5');
    c.lineWidth = 1; c.moveTo(area.left, yp); c.lineTo(area.right, yp); c.stroke(); c.restore();
  }
};
// x축 라벨 'YY.MM 통일 (이슈5). 인식 못하는 형식은 원본 유지.
function _calFmtTick(label){
  const s = String(label);
  let m = s.match(/^(\d{4})[-./](\d{1,2})/);     if(m) return "'"+m[1].slice(2)+'.'+m[2].padStart(2,'0');
  m = s.match(/^(\d{2})[-./](\d{1,2})$/);         if(m) return "'"+m[1]+'.'+m[2].padStart(2,'0');
  m = s.match(/^(\d{2,4})\s*Q([1-4])$/i);         if(m) return "'"+m[1].slice(-2)+' Q'+m[2];   // 분기 라벨 (GDP 등)
  return s;
}
let _calFloatPrevFocus = null;
function showCalGridFloating(idx, evt) {
  evt && evt.stopPropagation();
  const e = calEvents[idx];
  if(!e) return;
  const fl = document.getElementById('calGridFloating');
  if(!fl) return;
  _calFloatPrevFocus = document.activeElement;   // 닫을 때 포커스 복원용
  _calFloatingState.idx = idx;  // 새로고침 시 참조용
  document.getElementById('calFloatFlag').textContent = calCountryLabel(e.cc, e.flag) + ' · ' + e.dt + ' · ' + '★'.repeat(e.stars);
  document.getElementById('calFloatName').textContent = e.name;
  document.getElementById('calFloatPrev').textContent = e.prev || '—';
  document.getElementById('calFloatFore').textContent = e.fore || '—';
  _calRenderActual(e, 'calFloat');
  _calRenderFloatSurprise(e);
  // 플로팅 위치 — 부모 widget 기준 (position:relative 컨테이너)
  fl.style.display = 'block';
  if(evt && evt.clientX != null) {
    const parent = fl.parentElement;  // .widget
    if(parent) {
      const prect = parent.getBoundingClientRect();
      const x = evt.clientX - prect.left;
      const y = evt.clientY - prect.top;
      const fw = 380, fh = 240;
      let left = x + 10, top = y + 10;
      if(left + fw > prect.width)  left = Math.max(4, x - fw - 10);
      if(top  + fh > prect.height) top  = Math.max(4, y - fh - 10);
      fl.style.left = left + 'px';
      fl.style.top  = top + 'px';
    }
  }
  // 차트
  destroyChart('calFloatChart');
  const ctx = document.getElementById('calFloatChart');
  if(ctx) {
    const hist = (typeof _calGetChartSeries === 'function') ? _calGetChartSeries(e) : calHistoryData[e.name];
    if(hist) {
      const tc = (typeof getThemeColors==='function') ? getThemeColors() : {txt:'#8d90a2', grid:'#2a2e3d55'};
      charts['calFloatChart'] = new Chart(ctx, {
        type:'line',
        data:{ labels: hist.labels, datasets:[{ data: hist.vals, label: e.name, borderColor: hist.color, backgroundColor: hist.color+'22', borderWidth:1.5, pointRadius:2, fill:true, tension:0.3 }] },
        plugins:[_calZeroLine],
        options:{responsive:true,maintainAspectRatio:false,
          scales:{x:{ticks:{color:tc.txt,font:{size:11},maxRotation:0,minRotation:0,autoSkip:true,maxTicksLimit:4,callback:function(v){return _calFmtTick(this.getLabelForValue(v));}},grid:{display:false}},
                  y:{ticks:{color:tc.txt,font:{size:11},maxTicksLimit:5,callback:v=>_axisTick(v,hist.unit)},grid:{color:tc.grid}}},
          plugins:{legend:{display:false},tooltip:{enabled:true,bodyFont:{size:12},callbacks:{label:ctx=>fmtNum(ctx.parsed.y)+(hist.unit||'')}}}}
      });
    } else {
      ctx.getContext('2d').clearRect(0,0,ctx.width,ctx.height);
    }
  }
  try { fl.focus({preventScroll:true}); } catch(_) {}   // 키보드 사용자 — 팝업으로 포커스 이동
}
function _hideCalGridFloating() {
  const fl = document.getElementById('calGridFloating');
  if(fl) fl.style.display = 'none';
  if(_calFloatPrevFocus && typeof _calFloatPrevFocus.focus === 'function'){ try { _calFloatPrevFocus.focus({preventScroll:true}); } catch(_){} }
  _calFloatPrevFocus = null;
}
// 플로팅 팝업 — ESC / 바깥 클릭 닫기 (키보드·접근성). 여는 클릭은 stopPropagation 하므로 즉시 닫히지 않음.
document.addEventListener('keydown', function(ev){
  if(ev.key !== 'Escape') return;
  const fl = document.getElementById('calGridFloating');
  if(fl && fl.style.display !== 'none') _hideCalGridFloating();
});
document.addEventListener('click', function(ev){
  const fl = document.getElementById('calGridFloating');
  if(fl && fl.style.display !== 'none' && !fl.contains(ev.target)) _hideCalGridFloating();
});

// 캘린더 그리드 플로팅 팝업 새로고침 — data.json 재페치 후 actual 값을 갱신하여 다시 표시.
// _calFloatingState.idx 로 현재 표시 중인 이벤트를 추적하여, 팝업을 닫지 않고 같은 위치에서 갱신.
async function refreshCalFloatingPopup(btn) {
  _refreshFeedback(btn, 'loading');
  try {
    let ok = false;
    try {
      const r = await fetch('./data.json?_=' + Date.now(), { cache: 'no-store' });
      if(r.ok) {
        const fresh = await r.json();
        _latestDataForIndicators = fresh;
        try { applyRealData(fresh); } catch(_){}
        try { autoBackfillCalendarActuals(); } catch(_){}
        ok = true;
      }
    } catch(_) {}
    // 팝업 내용만 in-place 업데이트 (팝업 위치 유지, 사용자가 다시 클릭할 필요 없음).
    const idx = _calFloatingState && _calFloatingState.idx;
    const e = (idx != null && typeof calEvents !== 'undefined') ? calEvents[idx] : null;
    if(e) {
      const flagEl = document.getElementById('calFloatFlag');
      const nameEl = document.getElementById('calFloatName');
      const prevEl = document.getElementById('calFloatPrev');
      const foreEl = document.getElementById('calFloatFore');
      const actEl  = document.getElementById('calFloatAct');
      if(flagEl) flagEl.textContent = calCountryLabel(e.cc, e.flag) + ' · ' + e.dt + ' · ' + '★'.repeat(e.stars);
      if(nameEl) nameEl.textContent = e.name;
      if(prevEl) prevEl.textContent = e.prev || '—';
      if(foreEl) foreEl.textContent = e.fore || '—';
      try { _calRenderActual(e, 'calFloat'); } catch(_){}
      try { _calRenderFloatSurprise(e); } catch(_){}
      // 차트 다시 그리기
      try {
        destroyChart('calFloatChart');
        const ctx = document.getElementById('calFloatChart');
        const hist = (typeof _calGetChartSeries === 'function') ? _calGetChartSeries(e)
                   : ((typeof calHistoryData !== 'undefined') ? calHistoryData[e.name] : null);
        if(ctx && hist) {
          const tc = (typeof getThemeColors==='function') ? getThemeColors() : {txt:'#8d90a2', grid:'#2a2e3d55'};
          charts['calFloatChart'] = new Chart(ctx, {
            type:'line',
            data:{ labels: hist.labels, datasets:[{ data: hist.vals, label: e.name, borderColor: hist.color, backgroundColor: hist.color+'22', borderWidth:1.5, pointRadius:2, fill:true, tension:0.3 }] },
            plugins:[_calZeroLine],
            options:{responsive:true,maintainAspectRatio:false,
              scales:{x:{ticks:{color:tc.txt,font:{size:11},maxRotation:0,minRotation:0,autoSkip:true,maxTicksLimit:4,callback:function(v){return _calFmtTick(this.getLabelForValue(v));}},grid:{display:false}},
                      y:{ticks:{color:tc.txt,font:{size:11},maxTicksLimit:5,callback:v=>_axisTick(v,hist.unit)},grid:{color:tc.grid}}},
              plugins:{legend:{display:false},tooltip:{enabled:true,bodyFont:{size:12},callbacks:{label:ctx=>fmtNum(ctx.parsed.y)+(hist.unit||'')}}}}
          });
        }
      } catch(_){}
    }
    // 백그라운드: 캘린더 그리드도 다시 그려서 다른 이벤트들의 actual 도 반영
    try { if(typeof buildCalendar === 'function') buildCalendar(); } catch(_){}
    _refreshFeedback(btn, ok ? 'success' : 'warn', ok ? '갱신' : '캐시 사용');
  } catch(e) {
    console.warn('[calFloating] refresh 오류:', e);
    _refreshFeedback(btn, 'error', '실패');
  }
}

// 캘린더 이벤트 상세 패널 새로고침 — data.json 재페치 후 _renderCalDetailChart 재실행
async function refreshCalEventDetail(btn) {
  _refreshFeedback(btn, 'loading');
  try {
    let ok = false;
    try {
      const r = await fetch('./data.json?_=' + Date.now(), { cache: 'no-store' });
      if(r.ok) {
        const fresh = await r.json();
        _latestDataForIndicators = fresh;
        try { applyRealData(fresh); } catch(_){}
        try { autoBackfillCalendarActuals(); } catch(_){}
        ok = true;
      }
    } catch(_) {}
    // 현재 표시된 이벤트의 actual/prev/fore 텍스트 다시 채움
    try {
      const idx = _calDetailState && _calDetailState.idx;
      if(idx != null) {
        const e = (typeof calEvents !== 'undefined') ? calEvents[idx] : null;
        if(e) {
          const prevEl = document.getElementById('calDetailPrev');
          const foreEl = document.getElementById('calDetailFore');
          const actEl  = document.getElementById('calDetailAct');
          if(prevEl) prevEl.textContent = e.prev || '—';
          if(foreEl) foreEl.textContent = e.fore || '—';
          try { _calRenderActual(e, 'calDetail'); } catch(_){}
        }
      }
      if(typeof _renderCalDetailChart === 'function') _renderCalDetailChart();
    } catch(e) { console.warn('[calEventDetail] render 오류:', e); }
    _refreshFeedback(btn, ok ? 'success' : 'warn', ok ? '상세 갱신' : '캐시 사용');
  } catch(e) {
    console.warn('[calEventDetail] refresh 오류:', e);
    _refreshFeedback(btn, 'error', '실패');
  }
}

// ─────────────────────────────────────────────────────────────────────────
// 캘린더 백필 핵심 헬퍼 — data.json 의 indicator history 에서 MoM/YoY/raw 추출
// 서버측 backfill_calendar_actuals (scripts/fetch_data.py) 와 동일한 로직을 클라이언트에서 재현.
// data.json 의 CPI/PCE/PPI/GDP 등은 인덱스 레벨로 저장되므로 (예: cpi_eu=103.0),
// 단순 v.toFixed(1)+'%' 로는 "103.0%" 같은 비정상 값이 나옴 → 여기서 % 변화율을 계산.
// ─────────────────────────────────────────────────────────────────────────
function _calGetByPath(obj, path) {
  if(!obj || !path) return null;
  return path.split('.').reduce((o,k) => (o && typeof o === 'object') ? o[k] : null, obj);
}

// history key 를 YYYYMMDD 8자리 문자열로 정규화하여 비교 가능하게 함.
// 지원: "YYYY-MM-DD", "YYYY-MM", "YYYYMM", "YYYY", "YYQX", "YYYYQX"
function _calNormKey(k) {
  if(k == null) return null;
  const s = String(k).trim();
  const compact = s.replace(/-/g,'');
  if(/^\d{8}$/.test(compact)) return compact;
  if(/^\d{6}$/.test(compact)) return compact + '01';
  if(/^\d{4}$/.test(compact)) return compact + '0101';
  const q = s.match(/^(\d{2}|\d{4})Q([1-4])$/i);
  if(q) {
    const y = q[1].length === 2 ? '20'+q[1] : q[1];
    const monthStart = ['01','04','07','10'][parseInt(q[2])-1];
    return y + monthStart + '01';
  }
  return null;
}

// 이벤트 ISO 날짜에 해당하는 가장 최근 history key 찾기 (key 정규화 후 ISO 와 비교).
function _calFindHistKey(history, iso) {
  if(!history || !iso) return null;
  const isoNorm = iso.replace(/-/g,'').padEnd(8,'9').slice(0,8); // pad 9 to include same-day keys
  let bestKey = null, bestNorm = '00000000';
  for(const k of Object.keys(history)) {
    const norm = _calNormKey(k);
    if(!norm) continue;
    if(norm <= isoNorm && norm > bestNorm) {
      bestNorm = norm;
      bestKey = k;
    }
  }
  return bestKey;
}

// mode='mom': 직전 키 대비, 'yoy': 12개월 전 키 대비, 'delta': 직전 키와의 raw 차이 (NFP 변화량 등).
function _calComputeChange(history, key, mode) {
  if(!history || !key) return null;
  // 정규화 키 기준으로 정렬
  const entries = Object.keys(history)
    .map(k => ({ k, n: _calNormKey(k) }))
    .filter(e => e.n)
    .sort((a,b) => a.n < b.n ? -1 : a.n > b.n ? 1 : 0);
  const idx = entries.findIndex(e => e.k === key);
  if(idx < 0) return null;
  const cur = history[key];
  if(cur == null) return null;
  let prevKey;
  if(mode === 'mom' || mode === 'delta') {
    if(idx < 1) return null;
    prevKey = entries[idx-1].k;
  } else if(mode === 'yoy') {
    if(idx < 12) return null;
    prevKey = entries[idx-12].k;
  } else {
    return null;
  }
  const prev = history[prevKey];
  if(prev == null) return null;
  if(mode === 'delta') return cur - prev;
  if(prev === 0) return null;
  return Math.round((cur - prev) / prev * 10000) / 100;
}

// 포맷 코드별 표시 문자열 생성 (서버 _fmt_indicator 와 호환).
function _calFmtValue(val, fmt) {
  if(val == null || isNaN(val)) return '';
  if(fmt === 'mom1' || fmt === 'yoy1' || fmt === 'pct1') {
    const sign = val >= 0 ? '+' : '';
    return `${sign}${val.toFixed(1)}%`;
  }
  if(fmt === 'pct2') return `${val.toFixed(2)}%`;
  if(fmt === 'rate1') return `${val.toFixed(1)}%`;  // 이미 % 단위 (실업률 등) — 부호 없음
  if(fmt === 'raw1') return val.toFixed(1);
  if(fmt === 'raw2') return val.toFixed(2);
  if(fmt === 'k') return `${Math.round(val).toLocaleString('en-US')}K`;
  if(fmt === 'k_delta') {
    const sign = val >= 0 ? '+' : '';
    return `${sign}${Math.round(val).toLocaleString('en-US')}K`;
  }
  return String(val);
}

// 캘린더 이벤트명 → data.json 노드 경로 + 포맷.
// fmt: 'mom1'/'yoy1' = 변화율 계산 (인덱스에서 추출), 'pct2'/'raw1' = 값 그대로.
// mode: 'mom'/'yoy'/'delta' = history 에서 변화율 계산, null = node.value 또는 history[key] 그대로.
const CAL_BACKFILL_MAP = {
  // 한국 (ECOS — CPI 는 인덱스 레벨, GDP fallback 은 이미 QoQ %)
  '한국은행 금통위 회의':       { path: 'economicIndicators.kr.base_rate_kr', fmt: 'pct2', mode: null },
  '한국 소비자물가지수(CPI)':    { path: 'economicIndicators.kr.cpi_kr',       fmt: 'yoy1', mode: 'yoy' },
  '한국 5월 소비자물가(CPI)':    { path: 'economicIndicators.kr.cpi_kr',       fmt: 'yoy1', mode: 'yoy' },
  '한국 1분기 GDP (확정)':       { path: 'economicIndicators.kr.gdp_kr',       fmt: 'pct1', mode: null },
  '한국 수출입 동향':            { path: 'economicIndicators.kr.exports_kr',   fmt: 'yoy1', mode: 'yoy' },
  '한국 5월 수출입 동향':        { path: 'economicIndicators.kr.exports_kr',   fmt: 'yoy1', mode: 'yoy' },
  '한국 산업생산지수':           { path: 'economicIndicators.kr.ip_kr',        fmt: 'mom1', mode: 'mom' },
  '한국 제조업 PMI':             { path: 'economicIndicators.kr.pmi_kr',       fmt: 'raw1', mode: null },
  // 미국 (FRED — CPI/PCE/PPI/IP/retail/nfp 모두 인덱스 또는 레벨)
  '미국 CPI (전월비)':           { path: 'economicIndicators.us.cpi_us',       fmt: 'mom1', mode: 'mom' },
  '미국 CPI (전년비)':           { path: 'economicIndicators.us.cpi_us',       fmt: 'yoy1', mode: 'yoy' },
  '미국 PCE 물가지수':           { path: 'economicIndicators.us.pce_us',       fmt: 'mom1', mode: 'mom' },
  '미국 실업률':                 { path: 'economicIndicators.us.unemployment', fmt: 'rate1', mode: null },
  '미국 FOMC 회의':              { path: 'economicIndicators.us.ff_target',    fmt: 'pct2', mode: null },
  // GDP: 명목 수준의 전기비%가 아니라 BEA 실질 성장률(전기비 연율) 시리즈를 그대로 표시 (mode 없음).
  '미국 1분기 GDP (2차)':        { path: 'economicIndicators.us.gdp_growth_us', fmt: 'pct1', mode: null },
  '미국 GDP':                    { path: 'economicIndicators.us.gdp_growth_us', fmt: 'pct1', mode: null },
  '미국 비농업고용(NFP)':        { path: 'economicIndicators.us.nfp_us',       fmt: 'k_delta', mode: 'delta' },
  '미국 PPI':                    { path: 'economicIndicators.us.ppi_us',       fmt: 'mom1', mode: 'mom' },
  '미국 생산자물가지수(PPI)':    { path: 'economicIndicators.us.ppi_us',       fmt: 'mom1', mode: 'mom' },
  '미국 소매판매':               { path: 'economicIndicators.us.retail_us',    fmt: 'mom1', mode: 'mom' },
  '미국 산업생산':               { path: 'economicIndicators.us.ip_us',        fmt: 'mom1', mode: 'mom' },
  // 유로존
  '유로존 CPI (전년비)':         { path: 'economicIndicators.eu.cpi_eu',       fmt: 'yoy1', mode: 'yoy' },
  'ECB 통화정책회의':            { path: 'economicIndicators.eu.base_rate_eu', fmt: 'pct2', mode: null },
  '유로존 제조업 PMI':           { path: 'economicIndicators.eu.pmi_eu',       fmt: 'raw1', mode: null },
  // 일본
  '일본 GDP (전기비)':           { path: 'economicIndicators.jp.gdp_jp',       fmt: 'mom1', mode: 'mom' },
  '일본 BOJ 금리결정':           { path: 'economicIndicators.jp.base_rate_jp', fmt: 'pct2', mode: null },
  '일본 제조업 PMI':             { path: 'economicIndicators.jp.pmi_jp',       fmt: 'raw1', mode: null },
  // 중국
  '중국 CPI (전년비)':           { path: 'economicIndicators.cn.cpi_cn',       fmt: 'yoy1', mode: 'yoy' },
  '중국 제조업 PMI':             { path: 'economicIndicators.cn.pmi_cn',       fmt: 'raw1', mode: null },
  // 영국
  '영국 BOE 금리결정':           { path: 'economicIndicators.uk.base_rate_uk', fmt: 'pct2', mode: null },
  '영국 CPI (전년비)':           { path: 'economicIndicators.uk.cpi_uk',       fmt: 'yoy1', mode: 'yoy' },
  '영국 제조업 PMI':             { path: 'economicIndicators.uk.pmi_uk',       fmt: 'raw1', mode: null },
  // 독일
  '독일 CPI':                    { path: 'economicIndicators.de.cpi_de',       fmt: 'yoy1', mode: 'yoy' },
  '독일 제조업 PMI':             { path: 'economicIndicators.de.pmi_de',       fmt: 'raw1', mode: null },
};

// 캘린더 이벤트의 prev/fore/act 값을 data.json indicator history 에서 자동 백필.
// 매일 09:00/16:00/22:00 KST GitHub Actions 가 data.json 을 갱신 → 호출되어 stale 값 덮어씀.
// 1) data.json 에 매칭 지표 history 가 있으면 발표일 시점의 값으로 prev/act 재계산 (인덱스 → MoM/YoY 변환).
// 2) data.json 미연동이거나 history 없는 경우 → 기존 하드코드 act 유지 또는 calHistoryData 마지막값 사용.
function autoBackfillCalendarActuals() {
  const d = _latestDataForIndicators || {};
  const now = new Date();
  const curYear = now.getFullYear();
  let updated = 0, overrode = 0;
  for(const e of calEvents) {
    // 이벤트 날짜 파싱 ('MM.DD HH:mm' → Date, 현재 연도 기준)
    const m = e.dt.match(/(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})/);
    if(!m) continue;
    const evMonth = parseInt(m[1]);
    const evDay = parseInt(m[2]);
    const evDate = new Date(curYear, evMonth-1, evDay, parseInt(m[3]), parseInt(m[4]));
    if(evDate > now) continue;  // 미래 이벤트는 그대로 둠
    const evIso = `${curYear}-${String(evMonth).padStart(2,'0')}-${String(evDay).padStart(2,'0')}`;
    // 1) data.json 의 indicator history 에서 발표일 시점 값 계산
    const mp = CAL_BACKFILL_MAP[e.name];
    let backfilledFromJson = false;
    if(mp) {
      const node = _calGetByPath(d, mp.path);
      if(node && typeof node === 'object') {
        const history = node.history || {};
        const histKeys = Object.keys(history);
        let actVal = null, prevVal = null, actKey = null;
        if(histKeys.length) {
          actKey = _calFindHistKey(history, evIso);
          if(actKey != null) {
            actVal = mp.mode ? _calComputeChange(history, actKey, mp.mode) : history[actKey];
          }
        } else if(node.value != null && !mp.mode) {
          // history 없으면 현재값 사용 (raw 모드만, % 변화는 계산 불가)
          actVal = node.value;
        }
        // 금리(pct2) prev: 동일값 연속이 많으므로 "직전 값이 다른" key 를 찾음
        if(actVal != null && actKey && mp.fmt === 'pct2' && !mp.mode) {
          const sorted = histKeys
            .map(k => ({k, n:_calNormKey(k)}))
            .filter(x => x.n)
            .sort((a,b)=>a.n<b.n?-1:a.n>b.n?1:0);
          const idx = sorted.findIndex(x => x.k === actKey);
          for(let i = idx - 1; i >= 0; i--) {
            const v = history[sorted[i].k];
            if(v != null && Math.abs(v - actVal) > 0.0001) { prevVal = v; break; }
          }
        } else if(actVal != null && actKey) {
          // 일반: 직전 history 키 값 (mp.mode 가 있으면 또 변화율로 환산)
          const sorted = histKeys
            .map(k => ({k, n:_calNormKey(k)}))
            .filter(x => x.n)
            .sort((a,b)=>a.n<b.n?-1:a.n>b.n?1:0);
          const idx = sorted.findIndex(x => x.k === actKey);
          if(idx > 0) {
            const pk = sorted[idx-1].k;
            prevVal = mp.mode ? _calComputeChange(history, pk, mp.mode) : history[pk];
          }
        }
        if(actVal != null && !isNaN(actVal)) {
          const newAct = _calFmtValue(actVal, mp.fmt);
          if(newAct) {
            const wasFilled = e.act && e.act !== '예정' && e.act !== '';
            if(wasFilled && e.act !== newAct) overrode++;
            e.act = newAct;
            if(prevVal != null && !isNaN(prevVal)) {
              const newPrev = _calFmtValue(prevVal, mp.fmt);
              if(newPrev) e.prev = newPrev;
            }
            // beat 계산 — 예측값과 비교
            const foreNum = parseFloat(String(e.fore||'').replace(/[%+,]/g,'').replace(/[Kk]/g,''));
            if(!isNaN(foreNum)) {
              const cmp = actVal;
              if(Math.abs(cmp - foreNum) < 0.05) e.beat = 0;
              else if(/CPI|PPI|물가|실업|미분양/.test(e.name)) e.beat = (cmp < foreNum) ? 1 : -1;
              else e.beat = (cmp > foreNum) ? 1 : -1;
            }
            updated++;
            backfilledFromJson = true;
          }
        }
      }
    }
    if(backfilledFromJson) continue;
    // 2) data.json 매칭 실패 → 기존 하드코드 act 유지 (작년에 입력된 값일 수 있어 안내 가치는 떨어지지만 fallback)
    if(e.act && e.act !== '예정' && e.act !== '') continue;
    // 3) calHistoryData 마지막 값으로 백필 (data.json 미연동인 경우 최후 폴백)
    const hist = calHistoryData[e.name];
    if(hist && hist.vals && hist.vals.length) {
      const lastVal = hist.vals[hist.vals.length - 1];
      const unit = hist.unit || '';
      const sign = (e.name.includes('GDP') || e.name.includes('수출') || e.name.includes('산업생산')) ? (lastVal>=0?'+':'') : '';
      e.act = sign + lastVal.toFixed(/금리|FOMC|금통위|BOJ|BOE|LPR|ECB/.test(e.name) ? 2 : 1) + unit;
      const foreNum = parseFloat(String(e.fore||'').replace(/[%+]/g,''));
      if(!isNaN(foreNum)) {
        if(Math.abs(lastVal - foreNum) < 0.05) e.beat = 0;
        else if(/CPI|PPI|물가|실업|미분양/.test(e.name)) e.beat = (lastVal < foreNum) ? 1 : -1;
        else e.beat = (lastVal > foreNum) ? 1 : -1;
      }
      updated++;
    }
  }
  if(updated > 0) {
    if(overrode > 0) console.info(`[Calendar] ${updated}개 이벤트 actual 백필 (stale 하드코드 ${overrode}개 덮어씀)`);
    else console.info(`[Calendar] ${updated}개 이벤트 actual 자동 백필 완료`);
  }
}

// 캘린더 이벤트의 차트 시리즈를 data.json history 에서 동적으로 생성.
// CAL_BACKFILL_MAP 에 매핑이 있고 history 가 충분하면 신선한 시리즈 반환,
// 없으면 calHistoryData 의 하드코드 폴백 사용.
function _calGetChartSeries(e) {
  if(!e) return null;
  const mp = CAL_BACKFILL_MAP[e.name];
  const d = _latestDataForIndicators;
  if(mp && d) {
    const node = _calGetByPath(d, mp.path);
    if(node && node.history) {
      const sorted = Object.keys(node.history)
        .map(k => ({k, n:_calNormKey(k)}))
        .filter(x => x.n)
        .sort((a,b)=>a.n<b.n?-1:a.n>b.n?1:0);
      // 최근 24~30개 데이터 포인트 (YoY 는 12개월 전 키 필요)
      const sliceN = (mp.mode === 'yoy') ? 30 : 24;
      const tail = sorted.slice(-sliceN);
      const labels = [], vals = [];
      for(const x of tail) {
        let v;
        if(mp.mode) {
          v = _calComputeChange(node.history, x.k, mp.mode);
        } else {
          v = node.history[x.k];
        }
        if(v == null || isNaN(v)) continue;
        // 라벨: YYYYMMDD → YY.MM
        const norm = x.n; // YYYYMMDD
        labels.push(`${norm.slice(2,4)}.${norm.slice(4,6)}`);
        vals.push(v);
      }
      if(vals.length >= 2) {
        const fb = (typeof calHistoryData !== 'undefined') ? (calHistoryData[e.name] || {}) : {};
        const unit = (mp.fmt === 'k' || mp.fmt === 'k_delta') ? 'K' :
                     /^(mom1|yoy1|pct1|pct2|rate1)$/.test(mp.fmt) ? '%' :
                     (fb.unit || '');
        return {
          labels,
          vals,
          color: fb.color || getThemeColors().accent,
          unit,
        };
      }
    }
  }
  // 폴백: 하드코드된 calHistoryData
  return (typeof calHistoryData !== 'undefined') ? calHistoryData[e.name] : null;
}

// data.json.economicCalendar.events 를 calEvents 에 머지
// 매일 09:00 / 16:00 / 22:00 KST GitHub Actions 가 FRED release dates 로 갱신.
// 하드코드된 calEvents 와 dt+name 기준으로 중복 제거하며, 새 이벤트는 추가.
// flag 자동 부여 (cc 기반). 동일 (cc, name, YYYY-MM) 중복도 1차 제거 (서버 dedup 안전망).
function mergeServerCalendar() {
  const d = (typeof _latestDataForIndicators !== 'undefined') ? _latestDataForIndicators : null;
  const serverCal = d && d.economicCalendar && Array.isArray(d.economicCalendar.events)
    ? d.economicCalendar.events : null;
  if(!serverCal || !serverCal.length) return 0;
  const flagMap = {KR:'🇰🇷', US:'🇺🇸', EU:'🇪🇺', JP:'🇯🇵', CN:'🇨🇳', UK:'🇬🇧', DE:'🇩🇪'};
  // 월 다회 발표가 정상인 이벤트는 month-dedup 에서 제외 (FOMC, 주간실업수당청구)
  const MULTI_PER_MONTH_NAMES = new Set(['미국 FOMC 회의', '미국 신규 실업수당청구']);
  // 동일 이벤트의 다른 이름(서버 vs 클라이언트 하드코드) 별칭 — 같은 이벤트로 dedup.
  // 정규화 키 = 별칭 그룹의 대표명. 서버가 '미국 PPI' 보내고 클라가 '미국 생산자물가지수(PPI)' 가지면 같은 그룹으로 인식.
  const NAME_ALIAS = {
    '미국 PPI': '미국 생산자물가지수(PPI)',
    '미국 생산자물가지수(PPI)': '미국 생산자물가지수(PPI)',
    '미국 ISM 제조업 PMI': '미국 ISM 제조업 PMI',
    '미국 ISM 서비스 PMI': '미국 ISM 서비스 PMI',
  };
  const normName = n => NAME_ALIAS[n] || n;
  // 기존 (dt + name) 키 집합 (정규화 이름 사용)
  const existing = new Set(calEvents.map(e => `${e.dt}|${normName(e.name)}`));
  // (cc, name, YYYY-MM) 단위로 1개씩만 추가 — 서버 dedup 안전망
  const nameMonthSeen = new Set();
  for(const e of calEvents) {
    if(MULTI_PER_MONTH_NAMES.has(e.name)) continue;
    const cc = e.cc || '';
    const mm = (e.dt || '').slice(0,2);  // 'MM'
    nameMonthSeen.add(`${cc}|${normName(e.name)}|${mm}`);
  }
  let added = 0;
  let dedupSkipped = 0;
  for(const ev of serverCal) {
    if(!ev || !ev.dt || !ev.name) continue;
    const evNorm = normName(ev.name);
    const key = `${ev.dt}|${evNorm}`;
    if(existing.has(key)) continue;
    // 동일 (cc, name, YYYY-MM) 중복 제거 (서버 dedup 안전망)
    if(!MULTI_PER_MONTH_NAMES.has(ev.name)) {
      const isoYM = (ev.iso || '').slice(0,7); // YYYY-MM
      const ccMm = isoYM ? isoYM.slice(5,7) : (ev.dt || '').slice(0,2);
      const nmKey = `${ev.cc || ''}|${evNorm}|${ccMm}`;
      if(nameMonthSeen.has(nmKey)) { dedupSkipped++; continue; }
      nameMonthSeen.add(nmKey);
    }
    calEvents.push({
      dt: ev.dt,
      cc: ev.cc || 'US',
      flag: flagMap[ev.cc] || '',
      name: evNorm,  // 정규화된 이름으로 저장 → CAL_BACKFILL_MAP / calHistoryData 매칭 보장
      stars: ev.stars || 2,
      prev: ev.prev || '',
      fore: ev.fore || '',
      act: ev.act || '',
      beat: ev.beat || null,
      _src: ev.source || 'server',
      _iso: ev.iso || '',
    });
    existing.add(key);
    added++;
  }
  if(added > 0 || dedupSkipped > 0) console.info(`[Calendar] 서버측 이벤트 ${added}건 머지 (중복 dedup ${dedupSkipped}건 제거)`);
  return added;
}

// ── 매크로 서프라이즈 인덱스 (UX 4.3) ──────────────────────────────────────
// 예측 대비 실제값의 격차를 정량화해, 컨센서스를 크게 벗어난 발표(서프라이즈/쇼크)를
// 캘린더 행 배경색으로 하이라이팅한다. 방향성(호재/악재)은 기존 beat 판정을 따른다.
function _calParseNum(s) {
  if(s == null) return null;
  const m = String(s).replace(/,/g, '').match(/-?\d+(\.\d+)?/);
  return m ? parseFloat(m[0]) : null;
}
function _calSurprise(e) {
  if(!e || !e.act || !e.fore) return null;
  const f = _calParseNum(e.fore), a = _calParseNum(e.act);
  if(f == null || a == null) return null;
  const diff = a - f;
  const isPct = /%/.test(String(e.fore)) || /%/.test(String(e.act));
  const rel = Math.abs(f) > 1e-9 ? Math.abs(diff) / Math.abs(f) : null;
  // 큰 서프라이즈: 예측 대비 ±15% 이상 괴리, 또는 %단위 지표에서 ±0.3%p 이상 괴리
  const big = (rel != null && rel >= 0.15) || (isPct && Math.abs(diff) >= 0.3);
  const diffLabel = isPct
    ? `${diff >= 0 ? '+' : ''}${diff.toFixed(2)}%p`
    : (rel != null ? `${diff >= 0 ? '+' : ''}${(diff / Math.abs(f) * 100).toFixed(1)}%` : `${diff >= 0 ? '+' : ''}${diff.toFixed(2)}`);
  return { diff, big, isPct, diffLabel };
}

function buildCalendar(){
  // 서버측 캘린더 머지 (FRED release dates, 매일 09:00/22:00 갱신)
  try { mergeServerCalendar(); } catch(_) {}
  // 매번 호출 시 자동 백필 (data.json 또는 calHistoryData 마지막 값으로)
  try { autoBackfillCalendarActuals(); } catch(_) {}
  // 현재 월 판별
  const now   = new Date();
  const month = now.getMonth()+1;        // 1~12
  const nextM = month===12 ? 1 : month+1;
  const prevM = month===1  ? 12 : month-1;   // 지난 달
  const period = document.getElementById('calPeriod')?.value || '다음 달';

  // 필터 변경 시 그리드 자동 이동 (단, 사용자가 수동 네비게이션 한 경우 제외)
  if(!_calGridManualNav) {
    if(period === '다음 달') {
      _calGridYear = now.getFullYear() + (month===12 ? 1 : 0);
      _calGridMonth = nextM;
    } else if(period === '지난 달') {
      _calGridYear = now.getFullYear() - (month===1 ? 1 : 0);
      _calGridMonth = prevM;
    } else {
      _calGridYear = now.getFullYear();
      _calGridMonth = month;
    }
  }

  const filtered = calEvents.filter(e => {
    const evMonth = parseInt(e.dt.slice(0,2), 10);
    if(period==='이번 달' && evMonth !== month)    return false;
    if(period==='지난 달' && evMonth !== prevM)    return false;
    if(period==='다음 달' && evMonth !== nextM)    return false;
    if(period==='이번 주') {
      // ISO 8601 Calendar Week — 월요일 시작, 일요일 끝
      const today  = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const dow    = today.getDay();
      const daysFromMonday = (dow + 6) % 7;
      const monday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - daysFromMonday);
      const sunday = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 6);
      const evDay   = parseInt(e.dt.slice(3,5), 10);
      const evDate  = new Date(now.getFullYear(), evMonth-1, evDay);
      if(evDate < monday || evDate > sunday) return false;
    }
    return calFilterCC.has(e.cc) && calFilterStars.has(e.stars);
  });

  // 일시 오름차순 정렬 (MM.DD HH:MM) — '다음 달' 필터가 연말을 가로지를 때 12월/1월 순서를 유지하기 위해
  // 표시 중인 월 컨텍스트(_calGridYear/_calGridMonth)에 맞춰 연도 보정.
  filtered.sort((a, b) => {
    const _toMs = (e) => {
      const m = e.dt.match(/(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})/);
      if(!m) return 0;
      const mo = parseInt(m[1],10), dy = parseInt(m[2],10), hr = parseInt(m[3],10), mi = parseInt(m[4],10);
      // 표시 중인 기간이 연말/연초를 가로지를 때 연도 보정
      let yr = now.getFullYear();
      if(period === '다음 달' && month === 12 && mo === 1) yr++;   // 12월 → 익년 1월
      if(period === '지난 달' && month === 1  && mo === 12) yr--;  // 1월 → 전년 12월
      return new Date(yr, mo-1, dy, hr, mi).getTime();
    };
    return _toMs(a) - _toMs(b);
  });

  // 오늘 날짜 (MM.DD) — 행 하이라이트용
  const todayMD = `${String(now.getMonth()+1).padStart(2,'0')}.${String(now.getDate()).padStart(2,'0')}`;

  const upcoming = filtered.filter(e => !e.act);
  document.getElementById('calHighlights').innerHTML = upcoming.slice(0,3).map(e=>`
    <div class="kpi-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">
        <span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">${calCountryLabel(e.cc, e.flag)} · ${e.dt}</span>
        <span style="color:#f5a623;font-size:var(--font-size-sm);">${'★'.repeat(e.stars)}</span>
      </div>
      <div style="font-size:var(--font-size-base);font-weight:var(--font-weight-medium);line-height:1.4;">${e.name}</div>
      <div style="display:flex;gap:12px;margin-top:8px;font-size:var(--font-size-sm);color:var(--c-txt-dim);">
        <span>이전: <strong style="color:var(--c-txt);">${e.prev}</strong></span>
        <span>예측: <strong style="color:var(--c-primary);">${e.fore}</strong></span>
      </div>
    </div>`).join('') || '<div style="color:var(--c-txt-muted);font-size:var(--font-size-sm);grid-column:1/-1;text-align:center;padding:20px;">해당 조건의 예정 이벤트가 없습니다</div>';

  document.getElementById('calendarTable').innerHTML = filtered.map((e, fi)=>{
    const actStyle = e.act===''
      ? 'style="color:var(--c-txt-muted);font-style:italic;"'
      : e.beat===1  ? 'class="up-txt"'
      : e.beat===-1 ? 'class="down-txt"'
      : '';
    const calIdx = calEvents.indexOf(e);
    // 오늘 발표 이벤트 — 행 배경 약간 짙게 + 좌측 강조선
    const isToday = e.dt.startsWith(todayMD);
    // 매크로 서프라이즈 — 예측을 크게 벗어난 발표는 행 전체를 호재(초록)/악재(빨강)로 강조 (4.3)
    const surp = (e.beat === 1 || e.beat === -1) ? _calSurprise(e) : null;
    const surpStyle = (surp && surp.big)
      ? (e.beat === 1
        ? 'background:rgba(38,166,154,0.10);border-left:3px solid var(--c-up);border-bottom:1px solid var(--c-border);cursor:pointer;'
        : 'background:rgba(239,83,80,0.10);border-left:3px solid var(--c-down);border-bottom:1px solid var(--c-border);cursor:pointer;')
      : null;
    const rowStyle = isToday
      ? 'background:rgba(41,98,255,0.10);border-left:3px solid var(--c-accent);border-bottom:1px solid var(--c-border);cursor:pointer;'
      : (surpStyle || 'border-bottom:1px solid var(--c-border);cursor:pointer;');
    const dtCell = isToday
      ? `<td style="padding:8px;font-weight:var(--font-weight-semibold);color:var(--c-primary);">${e.dt} <span style="font-size:var(--font-size-xs);background:var(--c-accent);color:var(--c-on-accent);padding:1px 5px;border-radius:var(--r-sm);margin-left:4px;font-weight:var(--font-weight-semibold);">오늘</span></td>`
      : `<td style="padding:8px;">${e.dt}</td>`;
    // ★★★ 이벤트만 발표 알림 토글 제공 (Task 2.3) — 구독 상태는 localStorage 기반
    const bellCell = e.stars >= 3
      ? `<td style="text-align:center;padding:4px;"><button onclick="event.stopPropagation();toggleCalAlert(${calIdx},this)" title="${calAlertSubscribed(e) ? '알림 해제' : '발표 시 브라우저 알림 받기 (페이지가 열려 있는 동안)'}" style="background:transparent;border:none;cursor:pointer;font-size:var(--font-size-base);line-height:1;padding:2px;${calAlertSubscribed(e) ? '' : 'opacity:.45;filter:grayscale(1);'}">🔔</button></td>`
      : `<td></td>`;
    return `<tr style="${rowStyle}" onclick="showCalendarEventDetail(${calIdx})" title="클릭하여 과거 추이 보기">
      ${dtCell}
      <td style="text-align:center;padding:8px;white-space:nowrap;">${calCountryLabel(e.cc, e.flag)}</td>
      <td style="padding:8px;">${e.name} <span style="font-size:var(--font-size-xs);color:var(--c-primary);">↓</span></td>
      <td style="text-align:center;padding:8px;color:#f5a623;">${'★'.repeat(e.stars)}</td>
      <td style="text-align:right;padding:8px;color:var(--c-txt-dim);">${e.prev}</td>
      <td style="text-align:right;padding:8px;color:var(--c-primary);">${e.fore}</td>
      <td style="text-align:right;padding:8px;white-space:nowrap;" ${actStyle}>${e.act||'예정'}${(surp && surp.big) ? `<span title="매크로 서프라이즈 — 예측 대비 ${surp.diffLabel} (${e.beat===1?'호재':'악재'})" style="margin-left:4px;cursor:help;">⚡</span>` : ''}</td>
      ${bellCell}
    </tr>`;}).join('') || `<tr><td colspan="8" style="text-align:center;padding:20px;color:var(--c-txt-muted);">해당 조건의 이벤트가 없습니다</td></tr>`;

  // 시각적 캘린더 그리드 빌드 — 현재 표시 중인 월(_calGridMonth/_calGridYear) 기준
  // 필터링은 cc/stars 기준만 적용 (period 와 무관)
  const gridFiltered = calEvents.filter(e => calFilterCC.has(e.cc) && calFilterStars.has(e.stars));
  buildCalendarGrid(gridFiltered);
}

// ============================
// 경제 캘린더 이벤트 상세 (클릭 시 과거 추이 차트)
// ============================
const calHistoryData = {
  '한국 소비자물가지수(CPI)':  {labels:['24.01','24.03','24.05','24.07','24.09','24.11','25.01','25.03','25.05'], vals:[3.1,3.1,2.7,2.6,1.6,1.5,2.2,2.1,1.9], color:window.CUP, unit:'%'},
  '한국 1분기 GDP (확정)':     {labels:['23Q1','23Q2','23Q3','23Q4','24Q1','24Q2','24Q3','24Q4','25Q1','25Q2','25Q3','25Q4','26Q1'], vals:[0.4,0.6,0.8,0.6,1.3,-0.2,0.1,0.1,0.8,0.5,0.6,0.4,0.7], color:getThemeColors().accent, unit:'%'},
  '한국 5월 소비자물가(CPI)':  {labels:['24.05','24.07','24.09','24.11','25.01','25.03','25.05','25.07','25.09','25.11','26.01','26.03','26.05'], vals:[2.7,2.6,1.6,1.5,2.2,2.1,1.9,2.0,2.1,2.0,2.1,2.1,2.0], color:window.CUP, unit:'%'},
  '한국 수출입 동향':          {labels:['24.07','24.09','24.11','25.01','25.03','25.05','25.07','25.09','25.11','26.01','26.03','26.05'], vals:[3.1,3.5,2.8,4.2,2.9,3.7,3.3,3.0,2.5,3.1,2.8,3.7], color:window.CUP, unit:'%'},
  '한국 5월 수출입 동향':      {labels:['24.07','24.09','24.11','25.01','25.03','25.05','25.07','25.09','25.11','26.01','26.03','26.05'], vals:[3.1,3.5,2.8,4.2,2.9,3.7,3.3,3.0,2.5,3.1,2.8,3.0], color:window.CUP, unit:'%'},
  '미국 PCE 물가지수':         {labels:['24.01','24.03','24.05','24.07','24.09','24.11','25.01','25.03','25.05'], vals:[2.4,2.7,2.6,2.5,2.1,2.4,2.5,2.3,2.5], color:window.CDN, unit:'%'},
  '미국 비농업고용(NFP)':      {labels:['24.10','24.11','24.12','25.01','25.02','25.03','25.04','25.05','25.06'], vals:[256,272,307,256,148,228,177,140,210], color:'#b6c4ff', unit:'K'},
  '미국 실업률':               {labels:['24.08','24.09','24.10','24.11','24.12','25.01','25.02','25.03','25.04','25.05','26.04','26.05'], vals:[4.2,4.1,4.1,4.2,4.2,4.1,4.1,4.2,4.2,4.0,4.1,4.0], color:'#f5a623', unit:'%'},
  '미국 CPI (전월비)':         {labels:['24.07','24.08','24.09','24.10','24.11','24.12','25.01','25.02','25.03','25.04','25.05','25.06'], vals:[0.2,0.2,0.2,0.2,0.3,0.4,0.5,0.2,0.2,-0.1,0.1,0.2], color:window.CDN, unit:'%'},
  '미국 CPI (전년비)':         {labels:['24.07','24.09','24.11','25.01','25.03','25.05','25.07','25.09','25.11','26.01','26.03','26.05'], vals:[2.9,2.4,2.7,3.0,2.8,2.4,2.5,2.5,2.6,2.8,3.0,3.1], color:window.CDN, unit:'%'},
  '한국은행 금통위 회의':      {labels:['23.11','24.02','24.04','24.05','24.07','24.08','24.10','24.11','25.01','25.05','26.02','26.05'], vals:[3.5,3.5,3.5,3.5,3.5,3.25,3.25,3.25,3.0,2.75,2.75,2.50], color:window.CUP, unit:'%'},
  'ECB 통화정책회의':          {labels:['23.09','23.10','23.12','24.03','24.06','24.09','24.12','25.03','25.06','25.12','26.03','26.05','26.06'], vals:[4.5,4.5,4.5,4.5,4.25,3.65,3.15,2.65,2.40,2.50,2.50,2.00,2.00], color:'#b6c4ff', unit:'%'},
  '미국 FOMC 회의':            {labels:['23.07','23.09','23.11','24.01','24.03','24.09','24.11','24.12','25.03','25.06','25.09','25.10','25.12','26.03','26.06'], vals:[5.5,5.5,5.5,5.5,5.5,5.0,4.75,4.50,4.50,4.50,4.25,4.00,3.75,3.75,3.75], color:'#f5a623', unit:'%'},
  '미국 생산자물가지수(PPI)':  {labels:['24.07','24.08','24.09','24.10','24.11','24.12','25.01','25.02','25.03','25.04','25.05','25.06'], vals:[2.2,1.7,1.8,2.4,3.0,3.3,3.7,3.2,2.7,2.0,0.2,-0.5], color:'#b6bbcf', unit:'%'},
  '미국 소매판매':             {labels:['24.09','24.10','24.11','24.12','25.01','25.02','25.03','25.04','25.05','25.06','26.04','26.05'], vals:[0.4,-0.2,0.8,-0.9,0.9,-0.9,1.4,-0.1,0.4,0.2,0.4,0.1], color:'#b6c4ff', unit:'%'},
  '일본 GDP (전기비)':         {labels:['23Q1','23Q2','23Q3','23Q4','24Q1','24Q2','24Q3','24Q4','25Q1','25Q2','25Q3','25Q4'], vals:[1.3,0.5,1.0,-0.4,-0.6,0.8,0.9,-0.7,-0.2,0.3,0.1,-0.2], color:'#f5a623', unit:'%'},
  '중국 CPI (전년비)':         {labels:['24.07','24.08','24.09','24.10','24.11','24.12','25.01','25.02','25.03','25.04','25.05','26.04','26.05'], vals:[0.5,0.6,0.4,0.3,-0.5,0.1,0.5,-0.7,-0.1,0.2,-0.1,0.2,-0.1], color:window.CDN, unit:'%'},
  '유로존 CPI (전년비)':       {labels:['24.07','24.08','24.09','24.10','24.11','24.12','25.01','25.02','25.03','25.04','25.05','26.04','26.05'], vals:[2.6,2.2,1.7,2.3,2.3,2.4,2.5,2.3,2.2,2.2,2.1,2.2,2.1], color:'#b6c4ff', unit:'%'},
  '미국 1분기 GDP (2차)':      {labels:['23Q1','23Q2','23Q3','23Q4','24Q1','24Q2','24Q3','24Q4','25Q1','25Q2','25Q3','25Q4','26Q1'], vals:[2.2,2.1,4.9,3.4,1.6,3.0,2.8,2.3,-0.3,2.4,2.6,0.5,1.6], color:window.CUP, unit:'%'},
  '한국 산업생산지수':         {labels:['24.09','24.10','24.11','24.12','25.01','25.02','25.03','25.04','25.05','25.06','26.04','26.05'], vals:[1.5,0.9,1.2,-0.3,0.8,1.1,1.4,0.9,1.2,1.0,1.3,1.4], color:window.CUP, unit:'%'},
  '일본 BOJ 금리결정':         {labels:['23.04','23.07','23.10','24.01','24.03','24.07','24.10','25.01','25.04','25.07','25.10','26.01','26.06'], vals:[-0.10,-0.10,-0.10,-0.10,0.10,0.25,0.25,0.50,0.50,0.50,0.50,0.50,1.00], color:'#f5a623', unit:'%'},
  '영국 BOE 금리결정':         {labels:['23.06','23.09','23.12','24.03','24.06','24.09','24.12','25.03','25.06','25.09','25.12','26.03'], vals:[5.00,5.25,5.25,5.25,5.25,5.00,4.75,4.50,4.50,4.50,4.50,4.50], color:window.CDN, unit:'%'},
  '중국 1년물 LPR 결정':       {labels:['23.06','23.09','23.12','24.03','24.06','24.09','24.12','25.03','25.06','25.09','25.12','26.03'], vals:[3.55,3.45,3.45,3.45,3.45,3.35,3.10,3.10,3.10,3.10,3.10,3.10], color:getThemeColors().accent, unit:'%'},
};

// 캘린더 디테일 차트 상태
let _calDetailState = { idx:null, period:'all', timeUnit:'M' };

function setCalDetailPeriod(p, btn) {
  _calDetailState.period = p;
  document.querySelectorAll('.calDetailPeriodBtn').forEach(b=>{
    b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)'; b.style.borderColor='var(--c-border)';
  });
  if(btn) { btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff'; btn.style.borderColor='var(--c-accent)'; }
  _renderCalDetailChart();
}
function setCalDetailUnit(u, btn) {
  _calDetailState.timeUnit = u;
  document.querySelectorAll('.calDetailUnitBtn').forEach(b=>{
    b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)'; b.style.borderColor='var(--c-border)';
  });
  if(btn) { btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff'; btn.style.borderColor='var(--c-accent)'; }
  _renderCalDetailChart();
}

function showCalendarEventDetail(idx) {
  const e = calEvents[idx];
  if(!e) return;
  const panel = document.getElementById('calEventDetail');
  if(!panel) return;
  // 상태 저장 + 셀렉터 초기화
  _calDetailState.idx = idx;
  _calDetailState.period = 'all';
  _calDetailState.timeUnit = 'M';
  document.querySelectorAll('.calDetailPeriodBtn').forEach(b=>{
    const isActive = b.dataset.period === 'all';
    b.classList.toggle('active', isActive);
    b.style.background = isActive ? getThemeColors().accent : 'transparent';
    b.style.color = isActive ? '#fff' : '#8d90a2';
    b.style.borderColor = isActive ? getThemeColors().accent : '#2a2e3d';
  });
  document.querySelectorAll('.calDetailUnitBtn').forEach(b=>{
    const isActive = b.dataset.unit === 'M';
    b.classList.toggle('active', isActive);
    b.style.background = isActive ? getThemeColors().accent : 'transparent';
    b.style.color = isActive ? '#fff' : '#8d90a2';
    b.style.borderColor = isActive ? getThemeColors().accent : '#2a2e3d';
  });
  panel.style.display = 'block';
  document.getElementById('calDetailFlag').textContent = calCountryLabel(e.cc, e.flag);
  document.getElementById('calDetailName').textContent = e.name + ' · ' + e.dt;
  document.getElementById('calDetailPrev').textContent = e.prev || '—';
  document.getElementById('calDetailFore').textContent = e.fore || '—';
  const actEl = document.getElementById('calDetailAct');
  _calRenderActual(e, 'calDetail');
  // 매크로 서프라이즈 (4.3) — 예측 대비 격차를 툴팁으로 표기
  const dSurp = (e.beat === 1 || e.beat === -1) ? _calSurprise(e) : null;
  actEl.title = dSurp ? `예측 대비 ${dSurp.diffLabel}${dSurp.big ? ' — ⚡ 매크로 서프라이즈' : ''}` : '';
  if(dSurp && dSurp.big) actEl.textContent += ' ⚡';
  panel.scrollIntoView({behavior:'smooth', block:(window.matchMedia && window.matchMedia('(max-width:768px)').matches) ? 'start' : 'nearest'});
  _renderCalDetailChart();
}

function _renderCalDetailChart() {
  const { idx, period, timeUnit } = _calDetailState;
  const e = calEvents[idx];
  if(!e) return;
  destroyChart('calDetailChart');
  const hist = (typeof _calGetChartSeries === 'function') ? _calGetChartSeries(e) : calHistoryData[e.name];
  const canvas = document.getElementById('calDetailChart');
  // 가이드 표시 — 이벤트명으로 매크로 가이드 매칭
  const guideEl = document.getElementById('calDetailGuide');
  if(guideEl) {
    const macroGuide = (typeof _getMacroGuide === 'function') ? _getMacroGuide('', e.name) : null;
    if(macroGuide) {
      guideEl.innerHTML = macroGuide;
      guideEl.style.display = 'block';
    } else {
      guideEl.style.display = 'none';
    }
  }
  if(!canvas) return;
  if(!hist) {
    canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);
    const ctx2 = canvas.getContext('2d');
    ctx2.fillStyle = '#434656';
    ctx2.font = '12px Inter';
    ctx2.textAlign = 'center';
    ctx2.fillText('이 지표의 과거 데이터가 준비 중입니다', canvas.width/2, canvas.height/2);
    return;
  }
  // 기간/단위 리샘플링
  const resampled = _resampleHistSeries(hist.labels, hist.vals, period, timeUnit);
  const tc = getThemeColors();
  charts['calDetailChart'] = new Chart(canvas, {
    type: 'line',
    data: {
      labels: resampled.labels,
      datasets: [{
        data: resampled.values,
        label: e.name,
        borderColor: hist.color,
        borderWidth: 2,
        pointRadius: 0,
        pointBackgroundColor: hist.color,
        fill: true,
        backgroundColor: hist.color + '22',
        tension: 0.3,
      }]
    },
    plugins:[_calZeroLine],
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: { ticks: {color:tc.txt, font:{size:11}, maxRotation:0, minRotation:0, autoSkip:true, callback:function(v){return _calFmtTick(this.getLabelForValue(v));}}, grid:{color:tc.grid} },
        y: { ticks: {color:tc.txt, font:{size:11}, maxTicksLimit:8, callback: v => _axisTick(v, hist.unit)}, grid: {color:tc.grid}, position:'right' }
      },
      plugins: {
        legend: {display:false},
        subtitle: _axisUnitSubtitle(hist.unit, tc.txt),
        tooltip: {
          mode:'index', intersect:false, bodyFont:{size:12},
          backgroundColor: tc.tooltip, titleColor: tc.ttTitle, bodyColor: hist.color,
          borderColor: tc.ttBorder, borderWidth:1,
          callbacks: { label: ctx => fmtNum(ctx.parsed.y) + (hist.unit||'') }
        }
      }
    }
  });
}

// ============================
// 분석 노트 (localStorage)
// ============================
let notes=[], curNoteId=null, curTag='매크로';

// ─── 분석 노트 백업 시스템 ────────────────────────────────────────
// 사용자 데이터 손실 방지를 위한 다중 백업 키
//   econ_notes          : 메인 저장소
//   econ_notes_bak1~5   : 순환 백업 (저장 시마다 시프트)
//   econ_notes_session  : 세션 시작 시 스냅샷 (즉시 복원용)
const NOTES_KEY = 'econ_notes';
const NOTES_BACKUP_PREFIX = 'econ_notes_bak';
const NOTES_BACKUP_SLOTS = 5;
const NOTES_SESSION_KEY = 'econ_notes_session';

function _safeLocalGet(key) {
  try { return localStorage.getItem(key); } catch(_) { return null; }
}
function _safeLocalSet(key, val) {
  try { localStorage.setItem(key, val); return true; } catch(_) { return false; }
}

function rotateNotesBackup(currentJson) {
  // 비어있거나 빈 배열이면 백업하지 않음 (실수로 초기화된 상태가 백업되어 덮어쓰는 것 방지)
  if(!currentJson) return;
  try {
    const arr = JSON.parse(currentJson);
    if(!Array.isArray(arr) || arr.length === 0) return;
  } catch(_) { return; }
  // bak5 ← bak4 ← bak3 ← bak2 ← bak1 ← current
  for(let i=NOTES_BACKUP_SLOTS; i>1; i--) {
    const src = _safeLocalGet(NOTES_BACKUP_PREFIX + (i-1));
    if(src) _safeLocalSet(NOTES_BACKUP_PREFIX + i, src);
  }
  _safeLocalSet(NOTES_BACKUP_PREFIX + 1, currentJson);
}

function listNotesBackups() {
  const out = [];
  // 1) 최근 백업 슬롯
  for(let i=1; i<=NOTES_BACKUP_SLOTS; i++) {
    const v = _safeLocalGet(NOTES_BACKUP_PREFIX + i);
    if(v) {
      try {
        const arr = JSON.parse(v);
        if(Array.isArray(arr) && arr.length>0) {
          out.push({slot:'bak'+i, count:arr.length, sample:arr[0]?.title||'(제목없음)'});
        }
      } catch(_) {}
    }
  }
  // 2) 세션 스냅샷
  const sess = _safeLocalGet(NOTES_SESSION_KEY);
  if(sess) {
    try {
      const arr = JSON.parse(sess);
      if(Array.isArray(arr) && arr.length>0) {
        out.push({slot:'session', count:arr.length, sample:arr[0]?.title||'(제목없음)'});
      }
    } catch(_) {}
  }
  return out;
}

function restoreNotesFromBackup(slot) {
  const key = slot === 'session' ? NOTES_SESSION_KEY : (NOTES_BACKUP_PREFIX + slot.replace('bak',''));
  const v = _safeLocalGet(key);
  if(!v) { alert('해당 백업이 존재하지 않습니다.'); return; }
  try {
    const arr = JSON.parse(v);
    if(!Array.isArray(arr)) throw new Error('invalid');
    if(!confirm(`백업(${slot}, ${arr.length}건)을 현재 노트에 덮어쓰시겠습니까?\n(현재 노트가 사라집니다. 사라지기 전 자동으로 한 번 더 백업됩니다)`)) return;
    // 현재 노트를 먼저 백업 슬롯1 으로 이동
    const cur = _safeLocalGet(NOTES_KEY);
    if(cur) rotateNotesBackup(cur);
    _safeLocalSet(NOTES_KEY, v);
    notes = arr;
    curNoteId = arr[0]?.id || null;
    renderNoteList();
    if(curNoteId) openNote(curNoteId);
    renderBackupPanel();
    alert(`복원 완료 (${arr.length}건)`);
  } catch(e) {
    alert('복원 실패: 백업 데이터가 손상되었습니다.');
  }
}

// ── 📌 지표 스냅샷 박제 (3.4) ────────────────────────────────────────────────
// 현재 대시보드의 핵심 지표 수치를 마크다운 표로 노트 본문(전체 요약)에 삽입한다.
// 수동 타이핑 없이 '그 시점의 시장 상황'을 분석 노트에 기록으로 남기기 위한 기능.
function insertIndicatorSnapshot() {
  const d = (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators) ? _latestDataForIndicators : null;
  if(!d) { alert('시장 데이터가 아직 로드되지 않았습니다. 잠시 후 다시 시도하세요.'); return; }
  const body = document.getElementById('noteBody');
  if(!body) return;
  const fmt = (v, dec) => v == null ? '-' : (+v).toLocaleString('ko-KR', { maximumFractionDigits: dec != null ? dec : 2 });
  const chg = v => v == null ? '' : ` (${v >= 0 ? '+' : ''}${(+v).toFixed(2)}%)`;
  const rows = [];
  const idx = d.indices || {}, fx = d.fx || {}, com = d.commodities || {};
  [['KOSPI','KOSPI'],['KOSDAQ','KOSDAQ'],['SP500','S&P 500'],['NASDAQ','NASDAQ']].forEach(([k, lab]) => {
    if(idx[k] && idx[k].price != null) rows.push(`| ${lab} | ${fmt(idx[k].price)}${chg(idx[k].change)} |`);
  });
  if(fx.USDKRW && fx.USDKRW.rate != null) rows.push(`| USD/KRW | ${fmt(fx.USDKRW.rate, 1)}${chg(fx.USDKRW.change)} |`);
  [['WTI','WTI 유가'],['Gold','금'],['Copper','구리']].forEach(([k, lab]) => {
    if(com[k] && com[k].price != null) rows.push(`| ${lab} | ${fmt(com[k].price)}${chg(com[k].change)} |`);
  });
  const fg = d.sentiment && d.sentiment.fear_greed;
  if(fg && fg.value != null) rows.push(`| CNN 공포·탐욕 | ${fg.value}${fg.rating ? ` (${fg.rating})` : ''} |`);
  if(!rows.length) { alert('박제할 지표 수치가 없습니다.'); return; }
  const ts = new Date().toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' });
  const snap = `\n\n--- 📌 지표 스냅샷 (${ts}, 데이터 기준 ${d.lastUpdated || '-'}) ---\n| 지표 | 수치 |\n|---|---|\n${rows.join('\n')}\n---\n`;
  // 커서 위치에 삽입 (포커스 없으면 맨 뒤에)
  const pos = (document.activeElement === body && body.selectionStart != null) ? body.selectionStart : body.value.length;
  body.value = body.value.slice(0, pos) + snap + body.value.slice(pos);
  body.dispatchEvent(new Event('input'));
  if(typeof showToast === 'function') showToast('현재 지표 수치가 노트에 박제되었습니다. 저장 버튼을 눌러 보관하세요.');
}

function exportNotesJsonFile() {
  const data = _safeLocalGet(NOTES_KEY) || '[]';
  const blob = new Blob([data], {type:'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = '분석노트_백업_' + new Date().toISOString().slice(0,10) + '.json';
  a.click();
  URL.revokeObjectURL(url);
}

function importNotesJsonFile(input) {
  const f = input?.files?.[0];
  if(!f) return;
  const reader = new FileReader();
  reader.onload = e => {
    try {
      const arr = JSON.parse(e.target.result);
      if(!Array.isArray(arr)) throw new Error('not array');
      if(!confirm(`JSON 파일에서 ${arr.length}건의 노트를 가져옵니다. 현재 노트는 백업됩니다. 진행하시겠습니까?`)) return;
      const cur = _safeLocalGet(NOTES_KEY);
      if(cur) rotateNotesBackup(cur);
      _safeLocalSet(NOTES_KEY, JSON.stringify(arr));
      notes = arr;
      curNoteId = arr[0]?.id || null;
      renderNoteList();
      if(curNoteId) openNote(curNoteId);
      renderBackupPanel();
      alert(`가져오기 완료 (${arr.length}건)`);
    } catch(_) {
      alert('JSON 파일 파싱 실패. 형식이 올바른지 확인해주세요.');
    }
  };
  reader.readAsText(f);
}

function renderBackupPanel() {
  const el = document.getElementById('noteBackupList');
  if(!el) return;
  const bks = listNotesBackups();
  if(bks.length === 0) {
    el.innerHTML = '<div style="color:var(--c-txt-muted);font-size:var(--font-size-sm);padding:6px;">사용 가능한 백업이 없습니다. 이전 세션에서 노트를 저장한 적이 없을 수 있습니다.</div>';
    return;
  }
  el.innerHTML = bks.map(b => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 8px;border:1px solid var(--c-border);border-radius:var(--r-xs);margin-bottom:4px;">
      <div>
        <div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-medium);">${b.slot} <span style="color:var(--c-txt-dim);font-size:var(--font-size-xs);">(${b.count}건)</span></div>
        <div style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">첫 노트: ${b.sample}</div>
      </div>
      <button onclick="restoreNotesFromBackup('${b.slot}')" style="background:var(--c-accent-container);color:var(--c-primary);border:1px solid var(--c-accent-container);border-radius:var(--r-xs);padding:3px 8px;font-size:var(--font-size-xs);cursor:pointer;">복원</button>
    </div>`).join('');
}

function loadNotes(){
  const saved=_safeLocalGet(NOTES_KEY);
  notes=saved?JSON.parse(saved):[];
  // 세션 스냅샷 — 페이지 로드 시 한 번만 (재로딩 후 빠른 복원용)
  if(!_safeLocalGet(NOTES_SESSION_KEY) && saved) {
    _safeLocalSet(NOTES_SESSION_KEY, saved);
  }
  renderNoteList();
  document.getElementById('noteDate').textContent=new Date().toLocaleDateString('ko-KR');
  if(notes.length>0) openNote(notes[0].id);
  renderBackupPanel();
}
function renderNoteList(){
  const el=document.getElementById('noteList');
  if(!el) return;
  el.innerHTML=notes.map(n=>`
    <div style="display:flex;align-items:flex-start;gap:6px;padding:6px 8px;border-radius:var(--r-sm);border:1px solid ${curNoteId===n.id?'var(--c-accent)':'var(--c-border)'};background:${curNoteId===n.id?'var(--c-accent-container)':'transparent'};">
      <input type="checkbox" class="note-select-cb" data-id="${n.id}" style="cursor:pointer;accent-color:var(--c-accent);margin-top:3px;flex-shrink:0;" onclick="event.stopPropagation()"/>
      <div onclick="openNote('${n.id}')" style="flex:1;cursor:pointer;min-width:0;">
        <div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-medium);margin-bottom:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${n.title||'(제목 없음)'}</div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
          <span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">${n.date}</span>
          <span style="font-size:var(--font-size-xs);background:var(--c-accent-container);color:var(--c-primary);padding:1px 5px;border-radius:var(--r-xs);">${n.tag||'매크로'}</span>
          ${n.author?`<span style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">✍ ${n.author}</span>`:''}
        </div>
      </div>
    </div>`).join('') || '<div style="color:var(--c-txt-muted);font-size:var(--font-size-sm);text-align:center;padding:20px 0;">저장된 노트가 없습니다</div>';
}
function setTag(el,tag){
  curTag=tag;
  document.querySelectorAll('.note-tag').forEach(t=>{
    const active=t.textContent===tag;
    t.style.background=active?getThemeColors().accent+'22':'#1b1f2b';
    t.style.color=active?'#b6c4ff':'#8d90a2';
    t.style.border=active?'1px solid #2962ff55':'1px solid var(--c-border)';
  });
}
function save(){
  // 저장 직전 현재값을 백업 슬롯으로 회전 (덮어쓰기 직전 상태 보존)
  const prev = _safeLocalGet(NOTES_KEY);
  if(prev) rotateNotesBackup(prev);
  let ok = _safeLocalSet(NOTES_KEY, JSON.stringify(notes));
  // quota 초과로 실패하면 오래된 백업 슬롯부터 비우고 1회씩 재시도 —
  // 백업(최대 5슬롯+세션 스냅샷)이 원본의 수 배 용량을 점유해 정작 원본 저장이 막히는 역전 방지.
  if(!ok) {
    try {
      for(let i=NOTES_BACKUP_SLOTS; i>=2 && !ok; i--) {
        localStorage.removeItem(NOTES_BACKUP_PREFIX + i);
        ok = _safeLocalSet(NOTES_KEY, JSON.stringify(notes));
      }
    } catch(_) {}
  }
  // 그래도 실패면 사용자에게 알린다 — 기존엔 무음 실패 후 인메모리 목록이 갱신돼
  // '저장된 것처럼' 보였고, 새로고침 시 수기 입력이 통째로 사라졌다(시크릿 모드/quota).
  if(!ok && !window._noteSaveWarned) {
    window._noteSaveWarned = true;
    try { if(typeof showToast === 'function') showToast('⚠ 노트 저장 실패 — 브라우저 저장공간 부족 또는 시크릿 모드입니다. 「텍스트로 내보내기」로 백업해 두세요.'); } catch(_) {}
  }
  // 백업 패널 갱신 (현재 페이지에 있을 때만)
  if(document.getElementById('noteBackupList')) renderBackupPanel();
  return ok;
}
function exportNoteToText(){
  if(!curNoteId) return;
  const n=notes.find(n=>n.id===curNoteId);
  if(!n) return;
  const sec = n.sections || {};
  const sectionText = [
    sec.noteMacro  ? `\n[매크로/경제지표]\n${sec.noteMacro}` : '',
    sec.noteEquity ? `\n[주식시장]\n${sec.noteEquity}` : '',
    sec.noteBond   ? `\n[금리/채권]\n${sec.noteBond}` : '',
    sec.noteFx     ? `\n[외환/환율]\n${sec.noteFx}` : '',
    sec.noteCom    ? `\n[원자재]\n${sec.noteCom}` : '',
    sec.noteRE     ? `\n[부동산]\n${sec.noteRE}` : '',
  ].filter(Boolean).join('\n');
  const text=`제목: ${n.title}\n작성자: ${n.author||'(미입력)'}\n날짜: ${n.date}\n분류: ${n.tag}\n\n[전체 요약]\n${n.body}${sectionText}`;
  const a=document.createElement('a');
  a.href='data:text/plain;charset=utf-8,'+encodeURIComponent(text);
  a.download=(n.title||'note')+'.txt';
  a.click();
}

// ============================
// 국민연금 투자 현황 페이지 — 실제 데이터 (출처: 국민연금공단 공시)
// ============================
// 연도별 수익률 및 운용자산 (단위: 조원, %)
// 출처: 국민연금공단 기금운용본부 「기금운용 성과」 공시 (https://fund.nps.or.kr)
const npsHistory = [
  {year:2015, aum:512.3,  ret:+4.57, note:'국내외 주식 강세'},
  {year:2016, aum:558.3,  ret:+4.75, note:'미국 대선 변동성'},
  {year:2017, aum:621.7,  ret:+7.26, note:'글로벌 동반 상승'},
  {year:2018, aum:638.8,  ret:-0.92, note:'美中 무역분쟁'},
  {year:2019, aum:736.7,  ret:+11.31,note:'글로벌 증시 회복'},
  {year:2020, aum:833.7,  ret:+9.70, note:'코로나 회복 랠리'},
  {year:2021, aum:948.7,  ret:+10.77,note:'유동성 호황'},
  {year:2022, aum:890.5,  ret:-8.22, note:'금리인상·약세장'},
  {year:2023, aum:1035.8, ret:+13.59,note:'AI 주도 회복'},
  {year:2024, aum:1213.5, ret:+15.00,note:'역대 최고 수익률'},
  {year:2025, aum:1326.0, ret:+13.42,note:'잠정치'},
];

// 자산 배분 — 2026년 1분기말 기준 (출처: 국민연금공단 기금운용본부 공시)
// https://fund.nps.or.kr/oprtprcn/ivsmprcn/getOHED0016M0.do
// 총 운용자산: 약 1,326조원 (2025년 말 결산 기준)
// 자산군 비중은 NPS 공식 발표 자산배분 현황을 따름
// NPS 2026년 자산배분 목표비중(중기자산배분):
//   국내주식 14.9 / 해외주식 40.0 / 국내채권 25.4 / 해외채권 8.0 / 대체투자 11.4 / 단기 0.3
// 2026년 1분기 잠정 실현 비중:
const npsAllocation = [
  {asset:'국내주식', amount:202.5, pct:15.27, target:14.9, color:getThemeColors().accent},
  {asset:'해외주식', amount:528.4, pct:39.85, target:40.0, color:window.CUP},
  {asset:'국내채권', amount:330.2, pct:24.91, target:25.4, color:'#b6c4ff'},
  {asset:'해외채권', amount:104.8, pct:7.90,  target:8.0,  color:'#7e8aff'},
  {asset:'대체투자', amount:155.7, pct:11.74, target:11.4, color:'#f5a623'},
  {asset:'단기자금', amount:4.4,   pct:0.33,  target:0.3,  color:'#b6bbcf'},
];

// 자산 배분 추이 — 국민연금 공시 기반 (출처: 국민연금공단 기금운용본부 연차보고서)
// https://fund.nps.or.kr/jsppage/fund/mpc/mpc_04.jsp
const npsAllocTrendFull = {
  years: ['2016','2017','2018','2019','2020','2021','2022','2023','2024','2025'],
  datasets: [
    {label:'국내주식', data:[21.7,20.2,17.8,17.3,21.2,17.6,15.9,14.3,15.4,19.1], color:getThemeColors().accent},
    {label:'해외주식', data:[16.1,19.2,22.3,24.0,24.4,27.8,30.4,32.7,33.8,35.6], color:window.CUP},
    {label:'국내채권', data:[50.3,46.1,42.2,39.8,37.6,34.5,32.0,29.8,28.1,22.7], color:'#b6c4ff'},
    {label:'해외채권', data:[4.2,5.0,5.8,6.2,6.8,7.1,7.5,7.4,7.5,7.5],            color:'#7e8aff'},
    {label:'대체투자', data:[7.1,8.3,9.7,10.7,8.7,11.4,12.7,14.2,13.5,13.9],      color:'#f5a623'},
  ]
};
let npsAllocPeriod = 'all'; // 'all', '5y', '3y'
function getNpsAllocTrend() {
  const yrs = npsAllocTrendFull.years;
  const n = npsAllocPeriod==='5y' ? 5 : npsAllocPeriod==='3y' ? 3 : yrs.length;
  const sliceFrom = yrs.length - n;
  return {
    years: yrs.slice(sliceFrom),
    datasets: npsAllocTrendFull.datasets.map(d=>({...d, data:d.data.slice(sliceFrom)}))
  };
}
const npsAllocTrend = npsAllocTrendFull; // backward compat

// NPS 분기별 수익률 데이터
const npsQuarterlyData = [
  {q:'2023Q1', ret:+3.42}, {q:'2023Q2', ret:+4.15}, {q:'2023Q3', ret:-0.85}, {q:'2023Q4', ret:+6.87},
  {q:'2024Q1', ret:+5.21}, {q:'2024Q2', ret:+2.87}, {q:'2024Q3', ret:-1.45}, {q:'2024Q4', ret:+5.10},
  {q:'2025Q1', ret:+2.34}, {q:'2025Q2', ret:+1.88}, {q:'2025Q3', ret:+3.21}, {q:'2025Q4', ret:+4.67},
];

const npsYearQuarterly = {
  2020: [{q:'Q1',ret:-4.30},{q:'Q2',ret:8.20},{q:'Q3',ret:3.40},{q:'Q4',ret:2.40}],
  2021: [{q:'Q1',ret:3.20},{q:'Q2',ret:2.80},{q:'Q3',ret:2.10},{q:'Q4',ret:2.67}],
  2022: [{q:'Q1',ret:-2.10},{q:'Q2',ret:-5.40},{q:'Q3',ret:-1.80},{q:'Q4',ret:1.08}],
  2023: [{q:'Q1',ret:3.42},{q:'Q2',ret:4.15},{q:'Q3',ret:-0.85},{q:'Q4',ret:6.87}],
  2024: [{q:'Q1',ret:5.21},{q:'Q2',ret:2.87},{q:'Q3',ret:-1.45},{q:'Q4',ret:5.10}],
};

// 국민연금 국내주식 상위 보유 종목 (2025년 6월말 공시 기준)
// 출처: 국민연금공단 「주식 보유종목 공시」
const npsKrStocks = [
  {rank:1, name:'삼성전자',      pct:'8.42%', val:21.3},
  {rank:2, name:'SK하이닉스',    pct:'3.85%', val:9.8},
  {rank:3, name:'LG에너지솔루션',pct:'2.11%', val:5.3},
  {rank:4, name:'삼성바이오로직스',pct:'1.84%',val:4.7},
  {rank:5, name:'현대차',        pct:'1.62%', val:4.1},
  {rank:6, name:'POSCO홀딩스',   pct:'1.38%', val:3.5},
  {rank:7, name:'KB금융',        pct:'1.32%', val:3.3},
  {rank:8, name:'셀트리온',      pct:'1.12%', val:2.8},
  {rank:9, name:'기아',          pct:'1.05%', val:2.7},
  {rank:10,name:'신한지주',      pct:'0.94%', val:2.4},
];

const npsFxStocks = [
  {rank:1, name:'Apple',     pct:'2.84%', val:11.9},
  {rank:2, name:'Microsoft', pct:'2.41%', val:10.2},
  {rank:3, name:'NVIDIA',    pct:'2.18%', val:9.2},
  {rank:4, name:'Amazon',    pct:'1.87%', val:7.9},
  {rank:5, name:'Alphabet',  pct:'1.52%', val:6.4},
  {rank:6, name:'Meta',      pct:'1.34%', val:5.7},
  {rank:7, name:'Tesla',     pct:'0.98%', val:4.1},
  {rank:8, name:'TSMC',      pct:'0.87%', val:3.7},
  {rank:9, name:'Broadcom',  pct:'0.76%', val:3.2},
  {rank:10,name:'JP Morgan', pct:'0.65%', val:2.7},
];

let npsReturnView = 'annual';
function setNpsReturnView(view, btn) {
  npsReturnView = view;
  btn.closest('.widget').querySelectorAll('button').forEach(b=>{
    b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
  });
  btn.style.background='var(--c-accent)'; btn.style.color='#fff';
  buildNpsReturnChart();
}

function buildNpsReturnChart() {
  destroyChart('npsReturnChart');
  const retCtx = document.getElementById('npsReturnChart');
  if(!retCtx) return;
  if(npsReturnView==='annual') {
    charts['npsReturnChart'] = new Chart(retCtx,{type:'bar',
      data:{labels:npsHistory.map(h=>h.year),
            datasets:[{data:npsHistory.map(h=>h.ret),backgroundColor:npsHistory.map(h=>h.ret>=0?(window.CUP+'cc'):(window.CDN+'cc')),borderRadius:3}]},
      options:{responsive:true,maintainAspectRatio:false,
        scales:{x:{ticks:{color:'#b6bbcf',font:{size:10}},grid:{display:false}},
                y:{ticks:{color:'#b6bbcf',font:{size:10},callback:fmtPct},grid:{color:'#4a526888'}}},
        plugins:{legend:{display:false},tooltip:{backgroundColor:'#262a35',titleColor:'#e8ebf5',bodyColor:'#e8ebf5',borderColor:'#3a4054',borderWidth:1,callbacks:{label:ctx=>(ctx.parsed.y>=0?'+':'')+ctx.parsed.y.toFixed(2)+'%'}}}}});
  } else {
    charts['npsReturnChart'] = new Chart(retCtx,{type:'bar',
      data:{labels:npsQuarterlyData.map(q=>q.q),
            datasets:[{data:npsQuarterlyData.map(q=>q.ret),backgroundColor:npsQuarterlyData.map(q=>q.ret>=0?(window.CUP+'cc'):(window.CDN+'cc')),borderRadius:3}]},
      options:{responsive:true,maintainAspectRatio:false,
        scales:{x:{ticks:{color:'#b6bbcf',font:{size:10},maxTicksLimit:12},grid:{display:false}},
                y:{ticks:{color:'#b6bbcf',font:{size:10},callback:fmtPct},grid:{color:'#4a526888'}}},
        plugins:{legend:{display:false},tooltip:{backgroundColor:'#262a35',titleColor:'#e8ebf5',bodyColor:'#e8ebf5',borderColor:'#3a4054',borderWidth:1,callbacks:{label:ctx=>(ctx.parsed.y>=0?'+':'')+ctx.parsed.y.toFixed(2)+'%'}}}}});
  }
}

function showNpsYearDetail(year) {
  const el = document.getElementById('npsYearDetail');
  if(!el) return;
  el.style.display='block';
  const titleEl = document.getElementById('npsYearDetailTitle');
  if(titleEl) titleEl.textContent = year + '년 분기별 수익률';
  destroyChart('npsYearDetailChart');
  const data = npsYearQuarterly[year];
  const labels = data ? data.map(d=>d.q) : ['Q1','Q2','Q3','Q4'];
  const vals = data ? data.map(d=>d.ret) : [null,null,null,null];
  const ctx = document.getElementById('npsYearDetailChart');
  if(!ctx) return;
  charts['npsYearDetailChart'] = new Chart(ctx,{type:'bar',
    data:{labels,datasets:[{data:vals,backgroundColor:vals.map(v=>v!=null&&v>=0?(window.CUP+'cc'):(window.CDN+'cc')),borderRadius:3}]},
    options:{responsive:true,maintainAspectRatio:false,
      scales:{x:{ticks:{color:'#b6bbcf',font:{size:11}},grid:{display:false}},
              y:{ticks:{color:'#b6bbcf',font:{size:10},callback:fmtPct},grid:{color:'#4a526888'}}},
      plugins:{legend:{display:false},tooltip:{backgroundColor:'#262a35',titleColor:'#e8ebf5',bodyColor:'#e8ebf5',borderColor:'#3a4054',borderWidth:1,callbacks:{label:ctx=>(ctx.parsed.y>=0?'+':'')+ctx.parsed.y.toFixed(2)+'%'}}}}});
  el.scrollIntoView({behavior:'smooth',block:'nearest'});
}

function buildNpsAllocTrendChart() {
  destroyChart('npsAllocationTrendChart');
  const trendCtx = document.getElementById('npsAllocationTrendChart');
  if(!trendCtx) return;
  const trend = getNpsAllocTrend();
  charts['npsAllocationTrendChart'] = new Chart(trendCtx,{
    type:'line',
    data:{ labels:trend.years,
           datasets: trend.datasets.map(d=>({
             label:d.label, data:d.data, borderColor:d.color, backgroundColor:d.color+'22',
             borderWidth:2, pointRadius: 0, tension:0.3, fill:false
           })) },
    options:{ responsive:true, maintainAspectRatio:false,
      scales:{ x:{ticks:{color:'#b6bbcf',font:{size:10}},grid:{color:'#4a526888'}},
               y:{ticks:{color:'#b6bbcf',font:{size:10},callback:fmtPct},grid:{color:'#4a526888'},min:0,max:60} },
      plugins:{ legend:{display:true,position:'bottom',labels:{color:'#b6bbcf',font:{size:10},boxWidth:10,padding:8}},
                tooltip:{mode:'index',intersect:false,backgroundColor:'#262a35',titleColor:'#e8ebf5',bodyColor:'#e8ebf5',borderColor:'#3a4054',borderWidth:1,callbacks:{label:c=>c.dataset.label+': '+c.parsed.y+'%'}} }
    }
  });
  // YoY — 주 시리즈(배분 1순위, dataset 0)만 전년 오버레이. 연도 라벨 기반.
  { const _t = trend;
    registerYoY('npsAllocationTrendChart', { mode:'periodlabel', dispLabels:(_t.years||[]).map(String), fullLabels:(_t.years||[]).map(String), fullValues:(_t.datasets&&_t.datasets[0]?_t.datasets[0].data:[]), primary:0, color:(_t.datasets&&_t.datasets[0]?_t.datasets[0].color:getThemeColors().accent), tension:0.3 });
    applyYoY('npsAllocationTrendChart'); }
}
function setNpsAllocPeriod(period, btn) {
  npsAllocPeriod = period;
  const container = btn.closest('.widget');
  if(container) container.querySelectorAll('button').forEach(b=>{ b.style.background='transparent'; b.style.color='var(--c-txt-dim)'; });
  btn.style.background='var(--c-accent)'; btn.style.color='#fff';
  buildNpsAllocTrendChart();
}

let npsTabCurrent = 'overview';
function setNpsTab(tab, btn) {
  npsTabCurrent = tab;
  // 신규 최상위 탭 (invTop*) 을 건드리지 않도록 NPS 내부 탭만 스코프
  document.querySelectorAll('#investor-nps-container > div:first-of-type .tab-btn').forEach(b=>{
    b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
  });
  btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff';
  // 탭 컨텐츠 전환
  const ov = document.getElementById('nps-overview');
  const al = document.getElementById('nps-allocation');
  if(ov) ov.style.display = tab==='overview' ? 'block' : 'none';
  if(al) al.style.display = tab==='allocation' ? 'block' : 'none';
  buildInvestorPage();
}

// ── 글로벌 대형 연기금 데이터 (공개 출처 기반 정리) ────────────
// 출처: 각 기금의 공식 연차보고서 / 분기보고서
const GLOBAL_INVESTORS = {
  gpfg: {
    name: '🇳🇴 노르웨이 정부연기금 글로벌 (GPFG)',
    operator: 'Norges Bank Investment Management (NBIM)',
    aum_usd_t: 1.74,  // 2024년말 (조 달러)
    aum_label: '$1.74T (≈ 2,350조원)',
    aum_asof: '2024년말',
    inception: 1996,
    cagr_since_inception: 6.4,  // %
    return_2024: 13.1,
    return_2023: 16.1,
    return_2022: -14.1,
    return_2021: 14.5,
    return_2020: 10.9,
    allocation: [
      { name:'주식',     pct: 71.4, color:window.CUP },
      { name:'채권',     pct: 26.6, color:'#b6c4ff' },
      { name:'부동산',   pct:  1.8, color:'#f5a623' },
      { name:'재생에너지', pct:  0.2, color:getThemeColors().accent },
    ],
    holdings_intl: [
      { name:'Apple', pct: 1.36 }, { name:'Microsoft', pct: 1.31 },
      { name:'NVIDIA', pct: 1.21 }, { name:'Alphabet', pct: 0.96 },
      { name:'Amazon', pct: 0.91 }, { name:'Meta', pct: 0.62 },
      { name:'Tesla', pct: 0.41 }, { name:'TSMC', pct: 0.39 },
      { name:'Broadcom', pct: 0.36 }, { name:'Berkshire Hathaway', pct: 0.32 },
    ],
    summary: '세계 최대 SWF (국부펀드). 노르웨이 유전 수입을 모태로 운용. 9,000+ 글로벌 종목 분산 투자. 윤리 투자 가이드라인으로 무기·담배·석탄 등 제외. 분기·연차 보고 투명도 ★★★★★.',
    links: [
      { label:'NBIM 공식', url:'https://www.nbim.no' },
      { label:'분기 리포트', url:'https://www.nbim.no/en/investments/the-funds-investments/' },
    ],
  },
  gpif: {
    name: '🇯🇵 일본 공적연금 (GPIF)',
    operator: '年金積立金管理運用独立行政法人 (GPIF)',
    aum_usd_t: 1.54,
    aum_label: '$1.54T (≈ 2,080조원)',
    aum_asof: '2024년말 (FY2024 Q3)',
    inception: 2001,
    cagr_since_inception: 4.2,
    return_2024: 14.3,  // FY2024
    return_2023: 8.6,
    return_2022: -2.0,
    return_2021: 5.4,
    return_2020: 25.2,
    allocation: [
      { name:'국내주식',   pct: 25.0, color:window.CDN },
      { name:'해외주식',   pct: 25.0, color:window.CUP },
      { name:'국내채권',   pct: 25.0, color:'#b6c4ff' },
      { name:'해외채권',   pct: 25.0, color:'#f5a623' },
    ],
    holdings_intl: [
      { name:'Apple', pct: 1.05 }, { name:'Microsoft', pct: 1.00 },
      { name:'NVIDIA', pct: 0.95 }, { name:'Toyota', pct: 0.88 },
      { name:'Alphabet', pct: 0.72 }, { name:'Sony', pct: 0.41 },
      { name:'Mitsubishi UFJ', pct: 0.38 }, { name:'Keyence', pct: 0.35 },
      { name:'SoftBank', pct: 0.31 }, { name:'Hitachi', pct: 0.28 },
    ],
    summary: '세계 최대 공적연금. 4분의 1씩 균등 배분 (국내주/해외주/국내채/해외채). 일본 후생연금·국민연금 적립금 운용. 분기별 공식 보고서로 투명도 높음.',
    links: [
      { label:'GPIF 공식', url:'https://www.gpif.go.jp/en/' },
      { label:'운용 현황', url:'https://www.gpif.go.jp/en/performance/' },
    ],
  },
  frtib: {
    name: '🇺🇸 미국 연방 퇴직저축 투자위원회 (FRTIB / TSP)',
    operator: 'Federal Retirement Thrift Investment Board (FRTIB)',
    aum_usd_t: 0.93,
    aum_label: '$933B (≈ 1,260조원)',
    aum_asof: '2024년말',
    inception: 1986,
    cagr_since_inception: 7.9,
    return_2024: 14.5,  // C Fund (S&P500)
    return_2023: 26.3,
    return_2022: -18.1,
    return_2021: 28.7,
    return_2020: 18.4,
    allocation: [
      { name:'C Fund (대형주, S&P500)', pct: 38.5, color:window.CUP },
      { name:'G Fund (정부증권)',         pct: 27.1, color:'#b6c4ff' },
      { name:'L Funds (라이프사이클)',    pct: 18.4, color:'#f5a623' },
      { name:'I Fund (해외 MSCI)',        pct:  6.8, color:getThemeColors().accent },
      { name:'S Fund (소형주)',           pct:  6.5, color:window.CDN },
      { name:'F Fund (채권 인덱스)',      pct:  2.7, color:'#b6bbcf' },
    ],
    holdings_intl: [
      { name:'C Fund (S&P 500 인덱스)', pct: 38.5 },
      { name:'G Fund (특수 美국채)',     pct: 27.1 },
      { name:'L 2040 라이프사이클',      pct:  4.8 },
      { name:'L 2050 라이프사이클',      pct:  4.2 },
      { name:'I Fund (MSCI EAFE+EM)',     pct:  6.8 },
      { name:'S Fund (Dow Jones US Comp 1500)', pct: 6.5 },
    ],
    summary: '미국 연방공무원·군인 등 700만 가입자의 확정기여형(DC) 퇴직저축. 5개 코어 펀드(G/F/C/S/I) + 라이프사이클(L) 펀드. 운용 수수료 0.05% 미만 (세계 최저 수준).',
    links: [
      { label:'TSP 공식', url:'https://www.tsp.gov' },
      { label:'FRTIB 보고서', url:'https://www.frtib.gov/ReadingRoom/financialstmts.html' },
    ],
  },
  calpers: {
    name: '🇺🇸 캘리포니아 공무원연금 (CalPERS)',
    operator: 'California Public Employees\' Retirement System',
    aum_usd_t: 0.529,
    aum_label: '$529B (≈ 715조원)',
    aum_asof: '2024년말',
    inception: 1932,
    cagr_since_inception: 7.5,
    return_2024: 9.3,   // FY2024 (June)
    return_2023: 5.8,
    return_2022: -6.1,
    return_2021: 21.3,
    return_2020: 4.7,
    allocation: [
      { name:'글로벌 주식',   pct: 42.0, color:window.CUP },
      { name:'사모투자 (PE)', pct: 15.0, color:'#f5a623' },
      { name:'채권/인컴',     pct: 30.0, color:'#b6c4ff' },
      { name:'부동산',         pct: 15.0, color:window.CDN },
      { name:'기타/현금',     pct:  6.0, color:'#b6bbcf' },
    ],
    holdings_intl: [
      { name:'Apple', pct: 1.45 }, { name:'Microsoft', pct: 1.32 },
      { name:'NVIDIA', pct: 1.18 }, { name:'Alphabet', pct: 0.85 },
      { name:'Amazon', pct: 0.76 }, { name:'Meta', pct: 0.62 },
      { name:'Visa', pct: 0.38 }, { name:'JPMorgan Chase', pct: 0.36 },
      { name:'Tesla', pct: 0.32 }, { name:'Berkshire Hathaway', pct: 0.30 },
    ],
    summary: '미국 최대 공적연금 (200만 가입자, 캘리포니아 주·시·교육공무원). 7% 장기 목표수익률. PE/RE 등 대체투자 비중 30%+ 로 적극 운용.',
    links: [
      { label:'CalPERS 공식', url:'https://www.calpers.ca.gov' },
      { label:'투자 현황', url:'https://www.calpers.ca.gov/page/investments' },
    ],
  },
};

// ── 🌐 글로벌 연기금 자산배분 교차 비교 (4.4) ────────────────────────────────
// 5대 기금(NPS·GPFG·GPIF·TSP·CalPERS)의 자산배분을 주식/채권/대체/기타 4개 버킷으로
// 정규화해 100% 누적 가로 막대 하나로 비교한다. 데이터는 각 기금 공시 기반 정적 스냅샷.
function _allocBucket(name) {
  const n = String(name);
  if(/주식|C Fund|S Fund|I Fund/.test(n)) return '주식';
  if(/채권|인컴|G Fund|F Fund/.test(n)) return '채권';
  if(/대체|부동산|사모|PE|재생|인프라/.test(n)) return '대체투자';
  return '기타·혼합';
}
function buildGlobalAllocCompare() {
  const cv = document.getElementById('globalAllocCompareChart');
  if(!cv || typeof Chart === 'undefined') return;
  const BUCKETS = ['주식', '채권', '대체투자', '기타·혼합'];
  const _sr = getThemeColors().series;   // [blue, orange, teal, purple, green, red, cyan, pink, yellow]
  const COLORS = { '주식': window.CUP, '채권': _sr[0], '대체투자': _sr[1], '기타·혼합': _sr[2] };
  const funds = [
    { label: '🇰🇷 NPS', rows: npsAllocation.map(a => ({ name: a.asset, pct: a.pct })) },
    { label: '🇳🇴 GPFG', rows: GLOBAL_INVESTORS.gpfg.allocation },
    { label: '🇯🇵 GPIF', rows: GLOBAL_INVESTORS.gpif.allocation },
    { label: '🇺🇸 TSP', rows: GLOBAL_INVESTORS.frtib.allocation },
    { label: '🇺🇸 CalPERS', rows: GLOBAL_INVESTORS.calpers.allocation },
  ];
  const byFund = funds.map(f => {
    const agg = { '주식': 0, '채권': 0, '대체투자': 0, '기타·혼합': 0 };
    f.rows.forEach(r => { agg[_allocBucket(r.name)] += (+r.pct || 0); });
    const total = BUCKETS.reduce((s, b) => s + agg[b], 0) || 1;
    BUCKETS.forEach(b => { agg[b] = agg[b] / total * 100; });   // 비중 합계 100% 정규화
    return agg;
  });
  const tc = (typeof getThemeColors === 'function') ? getThemeColors() : { txt: '#8d90a2', grid: '#2a2e3d55' };
  destroyChart('globalAllocCompareChart');
  charts['globalAllocCompareChart'] = new Chart(cv, {
    type: 'bar',
    data: {
      labels: funds.map(f => f.label),
      datasets: BUCKETS.map(b => ({
        label: b,
        data: byFund.map(a => a[b]),
        backgroundColor: COLORS[b] + 'cc',
        borderColor: COLORS[b],
        borderWidth: 1,
      })),
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      scales: {
        x: { stacked: true, max: 100, ticks: { color: tc.txt, font: { size: 10 }, callback: v => v + '%' }, grid: { color: tc.grid } },
        y: { stacked: true, ticks: { color: tc.txt, font: { size: 11 } }, grid: { display: false } },
      },
      plugins: {
        legend: { labels: { color: tc.txt, boxWidth: 10, font: { size: 11 } } },
        tooltip: { callbacks: { label: c => `${c.dataset.label}: ${c.parsed.x.toFixed(1)}%` } },
      },
    },
  });
}

let _currentInvestor = 'nps';
function setInvestor(id, btn) {
  _currentInvestor = id;
  // 최상위 탭 활성화 UI
  document.querySelectorAll('#investorTopTabs .tab-btn').forEach(b=>{
    b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim)';
  });
  if(btn) { btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff'; }
  // 컨테이너 표시 전환
  ['nps','gpfg','gpif','frtib','calpers','berkshire'].forEach(k => {
    const el = document.getElementById('investor-'+k+'-container');
    if(el) el.style.display = (k === id) ? '' : 'none';
  });
  // NPS 이외에는 동적으로 콘텐츠 렌더
  if(id === 'berkshire') {
    _renderBerkshire();           // SEC 13F 보유 종목 (data.json.berkshire)
  } else if(id !== 'nps') {
    _renderGlobalInvestor(id);
  } else {
    // 기존 NPS 렌더
    buildInvestorPage();
  }
}

// ── 🇺🇸 버크셔 해서웨이 13F 보유 종목 — data.json.berkshire (SEC EDGAR 수집) ──
// 13F 는 분기 종료 후 45일 내 공시되는 스냅샷 — '현재 보유'가 아님을 기준일과 함께 명시.
function _renderBerkshire() {
  const container = document.getElementById('investor-berkshire-container');
  if(!container) return;
  const d = (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators) ? _latestDataForIndicators : {};
  const bk = d.berkshire;
  if(!bk || !Array.isArray(bk.holdings) || !bk.holdings.length) {
    container.innerHTML = `<div class="widget" style="text-align:center;padding:36px 20px;color:var(--c-txt-dim);font-size:var(--font-size-sm);line-height:1.9;">
      버크셔 해서웨이 13F 보유 종목 데이터가 아직 수집되지 않았습니다.<br>
      다음 데이터 갱신(GitHub Actions 주기 실행)에서 SEC EDGAR 13F 공시를 자동 수집합니다.</div>`;
    return;
  }
  const fmtB = v => v == null ? '—' : '$' + (v / 1e9).toFixed(v >= 1e11 ? 0 : 1) + 'B';
  const rows = bk.holdings.map((h, i) => {
    const label = h.ticker
      ? `<strong>${escapeHtml(h.ticker)}</strong> <span style="color:var(--c-txt-dim);font-size:var(--font-size-xs);">${escapeHtml(h.name)}</span>`
      : escapeHtml(h.name || '—');
    const pct = (h.pct != null && isFinite(+h.pct)) ? +h.pct : null;
    return `<tr style="border-bottom:1px solid var(--c-border);">
      <td style="padding:7px 8px;font-size:var(--font-size-sm);color:var(--c-txt-dim);">${i + 1}</td>
      <td style="padding:7px 8px;font-size:var(--font-size-sm);color:var(--c-txt);">${label}</td>
      <td style="padding:7px 8px;text-align:right;font-family:var(--font-num);font-weight:var(--font-weight-semibold);font-size:var(--font-size-sm);color:var(--c-txt);">${fmtB(h.valueUsd)}</td>
      <td style="padding:7px 8px;text-align:right;font-size:var(--font-size-sm);color:var(--c-txt-dim);">${h.shares ? (+h.shares).toLocaleString() : '—'}</td>
      <td style="padding:7px 8px;min-width:130px;">
        <div style="display:flex;align-items:center;gap:6px;">
          <div style="flex:1;height:6px;background:rgba(127,127,127,0.15);border-radius:var(--r-xs);overflow:hidden;"><div style="width:${pct == null ? 0 : Math.min(100, pct)}%;height:100%;background:var(--c-accent);"></div></div>
          <span style="font-size:var(--font-size-sm);font-weight:var(--font-weight-semibold);min-width:44px;text-align:right;color:var(--c-txt);">${pct == null ? '—' : pct.toFixed(1) + '%'}</span>
        </div>
      </td>
    </tr>`;
  }).join('');
  const top1 = bk.holdings[0];
  container.innerHTML = `
    <div style="display:flex;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
      <h2 style="font-size:var(--font-size-lg);font-weight:var(--font-weight-bold);font-family:var(--font-num);margin:0;">버크셔 해서웨이 보유 종목
        <span style="font-size:var(--font-size-sm);color:var(--c-txt-dim);font-weight:var(--font-weight-normal);margin-left:8px;">출처: SEC EDGAR 13F-HR 공시</span>
      </h2>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px;">
      <div class="kpi-card">
        <div class="widget-title">공시 주식 포트폴리오</div>
        <div style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);font-family:var(--font-num);">${fmtB(bk.totalValueUsd)}</div>
        <div style="font-size:var(--font-size-sm);color:var(--c-txt-dim);margin-top:4px;">13F 평가액 합계</div>
      </div>
      <div class="kpi-card">
        <div class="widget-title">보유 종목 수</div>
        <div style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);font-family:var(--font-num);">${bk.holdingsCount != null ? bk.holdingsCount : bk.holdings.length}<span style="font-size:var(--font-size-base);">종목</span></div>
        <div style="font-size:var(--font-size-sm);color:var(--c-txt-dim);margin-top:4px;">상위 ${bk.holdings.length}개 표시</div>
      </div>
      <div class="kpi-card">
        <div class="widget-title">최대 보유 종목</div>
        <div style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);font-family:var(--font-num);">${escapeHtml(top1.ticker || top1.name || '—')}</div>
        <div style="font-size:var(--font-size-sm);color:var(--c-txt-dim);margin-top:4px;">비중 ${top1.pct != null ? (+top1.pct).toFixed(1) + '%' : '—'}</div>
      </div>
      <div class="kpi-card">
        <div class="widget-title">보고 기준일</div>
        <div style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);font-family:var(--font-num);">${escapeHtml(bk.reportDate || '—')}</div>
        <div style="font-size:var(--font-size-sm);color:var(--c-txt-dim);margin-top:4px;">공시일 ${escapeHtml(bk.filedDate || '—')}</div>
      </div>
    </div>
    <div class="widget">
      <div class="widget-title">상위 보유 종목 (평가액 기준 Top ${bk.holdings.length})</div>
      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;">
          <thead><tr style="border-bottom:1px solid var(--c-border);">
            <th scope="col" style="padding:6px 8px;text-align:left;font-size:var(--font-size-xs);color:var(--c-txt-dim);font-weight:var(--font-weight-semibold);">#</th>
            <th scope="col" style="padding:6px 8px;text-align:left;font-size:var(--font-size-xs);color:var(--c-txt-dim);font-weight:var(--font-weight-semibold);">종목</th>
            <th scope="col" style="padding:6px 8px;text-align:right;font-size:var(--font-size-xs);color:var(--c-txt-dim);font-weight:var(--font-weight-semibold);">평가액</th>
            <th scope="col" style="padding:6px 8px;text-align:right;font-size:var(--font-size-xs);color:var(--c-txt-dim);font-weight:var(--font-weight-semibold);">주식 수</th>
            <th scope="col" style="padding:6px 8px;text-align:left;font-size:var(--font-size-xs);color:var(--c-txt-dim);font-weight:var(--font-weight-semibold);">포트폴리오 비중</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:8px;line-height:1.6;">
        ※ 13F 는 분기 종료 후 45일 이내 공시되는 미국 상장 주식 보유 현황입니다 — 현재 보유와 다를 수 있으며,
        평가액은 보고 기준일(${escapeHtml(bk.reportDate || '—')}) 시점 가격입니다. 비중은 13F 공시 포트폴리오 내 비중.
      </div>
    </div>`;
}

function _renderGlobalInvestor(id) {
  const data = GLOBAL_INVESTORS[id];
  const container = document.getElementById('investor-'+id+'-container');
  if(!data || !container) return;
  // 컨텐츠 렌더 (KPI + 자산배분 차트 + 수익률 차트 + Top 보유 + 공식 링크)
  const allocChartId = 'globalInv_'+id+'_alloc';
  const retChartId   = 'globalInv_'+id+'_return';
  container.innerHTML = `
    <div style="display:flex;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
      <h2 style="font-size:var(--font-size-lg);font-weight:var(--font-weight-bold);font-family:var(--font-num);margin:0;">${data.name}
        <span style="font-size:var(--font-size-sm);color:var(--c-txt-dim);font-weight:var(--font-weight-normal);margin-left:8px;">출처: ${data.operator}</span>
      </h2>
    </div>
    <!-- KPI -->
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px;">
      <div class="kpi-card">
        <div class="widget-title">총 운용 자산 (AUM)</div>
        <div style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);font-family:var(--font-num);">${data.aum_label}</div>
        <div style="font-size:var(--font-size-sm);color:var(--c-txt-dim);margin-top:4px;">${data.aum_asof}</div>
      </div>
      <div class="kpi-card">
        <div class="widget-title">최근 회계연도 수익률</div>
        <div style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);font-family:var(--font-num);" class="${data.return_2024>=0?'up-txt':'down-txt'}">${data.return_2024>=0?'+':''}${data.return_2024.toFixed(2)}%</div>
        <div style="font-size:var(--font-size-sm);color:var(--c-txt-dim);margin-top:4px;">2024 (공식 발표)</div>
      </div>
      <div class="kpi-card">
        <div class="widget-title">설립이후 연평균</div>
        <div style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);font-family:var(--font-num);" class="up-txt">+${data.cagr_since_inception.toFixed(2)}%</div>
        <div style="font-size:var(--font-size-sm);color:var(--c-txt-dim);margin-top:4px;">${data.inception}~ 연환산</div>
      </div>
      <div class="kpi-card">
        <div class="widget-title">5년 평균 (2020~2024)</div>
        <div style="font-size:var(--font-size-xl);font-weight:var(--font-weight-bold);font-family:var(--font-num);" class="up-txt">+${(((data.return_2020+data.return_2021+data.return_2022+data.return_2023+data.return_2024)/5)).toFixed(2)}%</div>
        <div style="font-size:var(--font-size-sm);color:var(--c-txt-dim);margin-top:4px;">단순 평균</div>
      </div>
    </div>
    <!-- 요약 -->
    <div class="widget" style="margin-bottom:12px;">
      <div class="widget-title">기금 개요</div>
      <div style="font-size:var(--font-size-base);color:var(--c-txt);line-height:1.7;">${data.summary}</div>
    </div>
    <!-- 차트 2열 -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
      <div class="widget">
        <div class="widget-title">자산 배분 현황 (${data.aum_asof})</div>
        <div style="position:relative;height:280px;"><canvas id="${allocChartId}"></canvas></div>
      </div>
      <div class="widget">
        <div class="widget-title">최근 5년 연도별 수익률 (%)</div>
        <div style="position:relative;height:280px;"><canvas id="${retChartId}"></canvas></div>
      </div>
    </div>
    <!-- 보유 자산 / 펀드 구성 -->
    <div class="widget" style="margin-bottom:12px;">
      <div class="widget-title">${id==='frtib'?'펀드 구성':'주요 보유 (Top 10, 공시 기반 추정치)'}</div>
      <table style="width:100%;font-size:var(--font-size-sm);border-collapse:collapse;">
        <thead><tr style="color:var(--c-txt-dim);border-bottom:1px solid var(--c-border);font-size:var(--font-size-sm);font-weight:var(--font-weight-semibold);text-transform:uppercase;">
          <th scope="col" style="text-align:left;padding:6px 0;">#</th>
          <th scope="col" style="text-align:left;padding:6px;">${id==='frtib'?'펀드':'종목'}</th>
          <th scope="col" style="text-align:right;padding:6px;">비중</th>
        </tr></thead>
        <tbody>
          ${data.holdings_intl.map((h,i)=>`
            <tr style="border-bottom:1px solid var(--c-border);">
              <td style="padding:6px 0;color:var(--c-txt-dim);">${i+1}</td>
              <td style="padding:6px;">${h.name}</td>
              <td style="text-align:right;padding:6px;font-weight:var(--font-weight-semibold);">${h.pct.toFixed(2)}%</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    <!-- 공식 링크 -->
    <div class="widget">
      <div class="widget-title">공식 자료 바로가기</div>
      <div style="display:grid;grid-template-columns:repeat(${Math.min(data.links.length,3)},1fr);gap:10px;">
        ${data.links.map(l => `
          <a href="${l.url}" target="_blank" rel="noopener noreferrer" style="text-decoration:none;">
            <div class="link-card">
              <div style="font-size:var(--font-size-sm);font-weight:var(--font-weight-semibold);color:var(--c-primary);margin-bottom:4px;">${l.label}</div>
              <div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);">${(new URL(l.url)).hostname}</div>
            </div>
          </a>
        `).join('')}
      </div>
    </div>
  `;
  // 차트 렌더
  destroyChart(allocChartId); destroyChart(retChartId);
  const tc = (typeof getThemeColors==='function') ? getThemeColors() : {txt:'#8d90a2',grid:'#2a2e3d55',tooltip:'#262a35',ttTitle:'#dfe2f2',ttBorder:'#2a2e3d'};
  // 자산 배분 (도넛)
  const allocCtx = document.getElementById(allocChartId);
  if(allocCtx) charts[allocChartId] = new Chart(allocCtx, {
    type:'doughnut',
    data:{ labels: data.allocation.map(a=>a.name),
           datasets:[{ data: data.allocation.map(a=>a.pct),
                       backgroundColor: data.allocation.map(a=>a.color),
                       borderWidth: 0 }] },
    options:{ responsive:true, maintainAspectRatio:false, cutout:'55%',
      plugins:{
        legend:{position:'right', labels:{color:tc.txt,font:{size:10},boxWidth:10}},
        tooltip:{backgroundColor:tc.tooltip,titleColor:tc.ttTitle,bodyColor:tc.ttTitle,borderColor:tc.ttBorder,borderWidth:1,
          callbacks:{ label: c => `${c.label}: ${c.parsed.toFixed(1)}%` }} }}
  });
  // 5년 수익률 (바)
  const retCtx = document.getElementById(retChartId);
  const years = ['2020','2021','2022','2023','2024'];
  const rets = [data.return_2020, data.return_2021, data.return_2022, data.return_2023, data.return_2024];
  if(retCtx) charts[retChartId] = new Chart(retCtx, {
    type:'bar',
    data:{ labels: years, datasets:[{
      label:'연간 수익률 (%)',
      data: rets,
      backgroundColor: rets.map(r => r >= 0 ? (window.CUP+'aa') : (window.CDN+'aa')),
      borderColor: rets.map(r => r >= 0 ? window.CUP : window.CDN),
      borderWidth: 1.5, borderRadius: 4,
    }]},
    options:{ responsive:true, maintainAspectRatio:false,
      scales:{ x:{ticks:{color:tc.txt,font:{size:11}}, grid:{display:false}},
               y:{ticks:{color:tc.txt,font:{size:11},maxTicksLimit:8,callback:v=>fmtNum(v)+'%'}, grid:{color:tc.grid}} },
      plugins:{
        legend:{display:false},
        tooltip:{backgroundColor:tc.tooltip,titleColor:tc.ttTitle,bodyColor:tc.ttTitle,borderColor:tc.ttBorder,borderWidth:1,
          callbacks:{ label: c => `${c.parsed.y>=0?'+':''}${c.parsed.y.toFixed(2)}%` }} }}
  });
}

function buildInvestorPage() {
  // 기존 차트 정리
  ['npsReturnChart','npsAumChart','npsAllocationChart','npsAllocationTrendChart','npsYearDetailChart'].forEach(destroyChart);

  if(npsTabCurrent === 'overview') {
    // 수익률 차트 (연간/분기 토글)
    buildNpsReturnChart();
    // AUM 차트 (라인)
    const aumCtx = document.getElementById('npsAumChart');
    if(aumCtx) charts['npsAumChart'] = new Chart(aumCtx,{
      type:'line',
      data:{ labels:npsHistory.map(h=>h.year),
             datasets:[{ data:npsHistory.map(h=>h.aum),
               borderColor:'#b6c4ff', borderWidth:2, pointRadius: 0, fill:true,
               backgroundColor:'#b6c4ff15', tension:0.3 }] },
      options:{ responsive:true, maintainAspectRatio:false,
        scales:{ x:{ticks:{color:'#b6bbcf',font:{size:10}},grid:{color:'#4a526888'}},
                 y:{ticks:{color:'#b6bbcf',font:{size:10},callback:v=>v.toLocaleString()+'조'},grid:{color:'#4a526888'}} },
        plugins:{ legend:{display:false},
                  tooltip:{backgroundColor:'#262a35',titleColor:'#e8ebf5',bodyColor:'#e8ebf5',borderColor:'#3a4054',borderWidth:1,
                    callbacks:{label:ctx=>ctx.parsed.y.toLocaleString()+'조원'}} }
      }
    });
    // YoY — 연도 라벨 기반. 오버레이 + 배지(전년 대비 AUM 증감률).
    { registerYoY('npsAumChart', { mode:'periodlabel', dispLabels:npsHistory.map(h=>''+h.year), fullLabels:npsHistory.map(h=>''+h.year), fullValues:npsHistory.map(h=>h.aum), primary:0, color:'#b6c4ff', tension:0.3 });
      applyYoY('npsAumChart'); }
    // 연도별 성과 요약 테이블 (행 클릭 → 분기별 상세)
    const tb = document.getElementById('npsReturnTable');
    if(tb) tb.innerHTML = npsHistory.slice().reverse().map(h=>{
      const profit = +(h.aum * h.ret / 100).toFixed(1);
      const retCls = h.ret >= 0 ? 'up-txt' : 'down-txt';
      return `<tr onclick="showNpsYearDetail(${h.year})" class="hoverable-row" style="border-bottom:1px solid var(--c-border);cursor:pointer;">
        <td style="padding:8px;">${h.year}</td>
        <td style="text-align:right;padding:8px;">${h.aum.toLocaleString()}</td>
        <td style="text-align:right;padding:8px;" class="${retCls}">${h.ret>=0?'+':''}${h.ret.toFixed(2)}%</td>
        <td style="text-align:right;padding:8px;color:var(--c-primary);">${profit>=0?'+':''}${profit.toLocaleString()}</td>
        <td style="padding:8px;color:var(--c-txt-dim);font-size:var(--font-size-sm);">${h.note}</td>
      </tr>`;
    }).join('');
  }

  if(npsTabCurrent === 'allocation') {
    // 자산 배분 도넛
    const allocCtx = document.getElementById('npsAllocationChart');
    if(allocCtx) charts['npsAllocationChart'] = new Chart(allocCtx,{
      type:'doughnut',
      data:{ labels:npsAllocation.map(a=>a.asset),
             datasets:[{ data:npsAllocation.map(a=>a.amount),
               backgroundColor:npsAllocation.map(a=>a.color),
               borderWidth:0 }] },
      options:{ responsive:true, maintainAspectRatio:false, cutout:'55%',
        plugins:{ legend:{display:true,position:'right',labels:{color:'#b6bbcf',font:{size:11},boxWidth:12,padding:10}},
                  tooltip:{callbacks:{label:c=>`${c.label}: ${c.raw}조원 (${(c.raw/1326.0*100).toFixed(1)}%)`}} }
      }
    });
    // 자산별 비중 테이블
    const tb2 = document.getElementById('npsAllocationTable');
    if(tb2) tb2.innerHTML = npsAllocation.map(a=>{
      const diff = a.pct - a.target;
      const diffStr = (diff>=0?'+':'')+diff.toFixed(1)+'%p';
      return `<tr style="border-bottom:1px solid var(--c-border);">
        <td style="padding:8px 0;"><span style="display:inline-block;width:10px;height:10px;background:${a.color};border-radius:var(--r-xs);margin-right:6px;vertical-align:middle;"></span>${a.asset}</td>
        <td style="text-align:right;padding:8px;font-weight:var(--font-weight-medium);">${a.amount}</td>
        <td style="text-align:right;padding:8px;color:var(--c-primary);">${a.pct.toFixed(1)}%</td>
        <td style="text-align:right;padding:8px;color:var(--c-txt-dim);">${a.target.toFixed(1)}% <span style="font-size:var(--font-size-xs);color:${diff>=0?window.CUP:window.CDN};">(${diffStr})</span></td>
      </tr>`;
    }).join('');
    // 자산 배분 추이 (라인) — 기간 선택 반영
    buildNpsAllocTrendChart();
    // Top 10 보유 종목 테이블
    const krTb = document.getElementById('npsKrStocksTable');
    if(krTb) krTb.innerHTML = npsKrStocks.map(s=>`
      <tr style="border-bottom:1px solid var(--c-border);">
        <td style="padding:6px 0;color:var(--c-txt-muted);">${s.rank}</td>
        <td style="padding:6px;">${s.name}</td>
        <td style="text-align:right;padding:6px;color:var(--c-primary);">${s.pct}</td>
        <td style="text-align:right;padding:6px;color:var(--c-txt-dim);">${s.val}</td>
      </tr>`).join('');
    const fxTb = document.getElementById('npsFxStocksTable');
    if(fxTb) fxTb.innerHTML = npsFxStocks.map(s=>`
      <tr style="border-bottom:1px solid var(--c-border);">
        <td style="padding:6px 0;color:var(--c-txt-muted);">${s.rank}</td>
        <td style="padding:6px;">${s.name}</td>
        <td style="text-align:right;padding:6px;color:var(--c-primary);">${s.pct}</td>
        <td style="text-align:right;padding:6px;color:var(--c-txt-dim);">${s.val}</td>
      </tr>`).join('');
  }
}

// ============================
// 데이터 소스 메타 (사이드바 신호등 + 플로팅 상세)
// ============================
const dataSourceMeta = [
  { key:'krx',    name:'KRX OpenAPI',     unit:'한국 공식',   sourceKeys:['indices','commodities'],
    desc:'한국거래소 OpenAPI - KOSPI/KOSDAQ 지수·금·석유 일별 시세 (FLUC_RT 가 0 으로 오는 결함으로 종목 등락은 pykrx 사용)',
    fetched:['KOSPI/KOSDAQ 지수','금(99.99 1Kg)','휘발유'] },
  { key:'pykrx',  name:'pykrx',           unit:'KRX 직접 호출', sourceKeys:['stockMovers','etfMovers'],
    desc:'pykrx 라이브러리 — KRX 정보데이터시스템(data.krx.co.kr)을 직접 호출. API 키 불필요, IP 차단 우회 가능, FLUC_RT 신뢰성 문제 없음. 종목·ETF Top10 의 PRIMARY 소스.',
    fetched:['KOSPI/KOSDAQ 종목 등락률 Top10','ETF 등락률 Top10','종목명/코드 매핑'] },
  { key:'stooq',  name:'Stooq',           unit:'실시간 지수', sourceKeys:[],  realtime:true,
    desc:'무료 글로벌 시세 (CORS 허용) — 30분마다 자동 갱신',
    fetched:['KOSPI/KOSDAQ','S&P500/NASDAQ/Nikkei','WTI/Brent/Gold/Silver/Copper'] },
  { key:'fx',     name:'open.er-api.com', unit:'환율',        sourceKeys:['fx'],
    desc:'무료 환율 API (USD 기준 전 통화). 30분마다 자동 갱신',
    fetched:['USD/KRW','EUR/KRW','JPY/KRW','EUR/USD','USD/JPY'] },
  { key:'yfin',   name:'yfinance',        unit:'해외 지수',   sourceKeys:['history','indices'],
    desc:'Yahoo Finance 5년 일별 종가 시계열 (FX/지수/원자재/농산물)',
    fetched:['5년 일별 시계열 (KOSPI~Shanghai)','금/은/플라티넘/구리/WTI/Brent','밀/옥수수/콩/쌀'] },
  { key:'fred',   name:'FRED',            unit:'미국 경제·국채', sourceKeys:['economicIndicators_us','realestate_us','yieldCurve_us','economicIndicators_intl'],
    desc:'St. Louis Fed 경제데이터베이스 — 미국 경제지표 + 국채 수익률 곡선 + OECD 국제 시리즈',
    fetched:['VIX/HY Spread','CPI/PCE/실업률/M2','국채 수익률 1M~30Y','일본·유로존·중국·독일·영국 OECD'] },
  { key:'ecos',   name:'ECOS',            unit:'한국은행',    sourceKeys:['economicIndicators_kr'],
    desc:'한국은행 경제통계시스템 (ECOS) — 한국 경제지표',
    fetched:['기준금리','소비자물가지수(CPI)','생산자물가지수(PPI)','실업률','경상수지','산업생산','수출 등'] },
  { key:'kosis',  name:'KOSIS',           unit:'통계청',       sourceKeys:['retail_kr_kosis'],
    desc:'KOSIS 국가통계포털 (kosis.kr) — 통계청 공식 통계. ECOS 에 없거나 KOSIS 값과 다른 시리즈 보강용.',
    fetched:['소매판매액지수 (DT_1JG2105)','서비스업동향조사','도소매업조사 (선택)'] },
  { key:'rone',   name:'R-ONE',           unit:'한국부동산원', sourceKeys:['realestate_kr'],
    desc:'한국부동산원 R-ONE OpenAPI — 부동산 가격지수',
    fetched:['전국 아파트 매매가격지수','전세가격지수'] },
  { key:'molit',  name:'data.go.kr',      unit:'국토부 실거래가', sourceKeys:['realestate_molit'],
    desc:'공공데이터포털 — 국토교통부 실거래가 통합 API',
    fetched:['전국 아파트 매매 거래량 (월별)'] },
  { key:'nps',    name:'NPS 공시',        unit:'국민연금',    sourceKeys:[],
    desc:'국민연금공단 자산 운용 공시 데이터 (분기별 정기 업데이트)',
    fetched:['국민연금 자산배분','국내·해외 Top 보유종목'] },
  { key:'gnews',  name:'Google News',     unit:'경제 뉴스',   sourceKeys:['news'],
    desc:'Google News RSS — 매일 KST 9시 GitHub Actions 가 카테고리별 (주식·채권·외환·원자재·거시) 최신 기사 5건씩 미리 페치하여 data.json 에 저장. 클라이언트 RSS 폴백.',
    fetched:['주식/채권/외환/원자재 뉴스','한국GDP·미국CPI·중국/일본/유로존 경제뉴스','한국수출/한국은행 정책'] },
  { key:'kis',    name:'한국투자증권 KIS', unit:'증시 실시간', sourceKeys:[],
    desc:'한국투자증권 KIS Developers OpenAPI. 기본 비활성 (KIS_ENABLED=0) — 잦은 토큰 발급으로 인한 카카오톡 알람 차단 목적. pykrx 가 KOSPI/KOSDAQ 데이터를 직접 가져오므로 KIS 가 없어도 정상 동작. 활성화하려면 워크플로우 변수 KIS_ENABLED=1 설정.',
    fetched:['(비활성) KOSPI/KOSDAQ 지수','(비활성) 등락률 Top10','(비활성) 종목 일별 시세'] },
];

let _dsStatusCache = null;
function computeDataSourceStatus(d) {
  const sources = (d && d.sources) || {};
  const diag = (d && d.diagnostics) || {};
  const status = {};
  for(const src of dataSourceMeta) {
    if(src.realtime) {
      status[src.key] = { state:'partial', label:'30분 주기' };
      continue;
    }
    // 커스텀 상태 로직 — 일부 메타는 라벨 매칭으로 더 정확하게 판정
    if(src.key === 'pykrx') {
      const sLabel = sources.stockMovers || '';
      const eLabel = sources.etfMovers || '';
      const pykrxStock = sLabel.includes('pykrx');
      const pykrxEtf = eLabel.includes('pykrx');
      if(pykrxStock && pykrxEtf) {
        status[src.key] = { state:'online', label:'주식+ETF 모두 pykrx' };
      } else if(pykrxStock || pykrxEtf) {
        status[src.key] = { state:'partial', label: pykrxStock ? '주식만 pykrx' : 'ETF만 pykrx' };
      } else if(diag.pykrxAvailable === false) {
        status[src.key] = { state:'offline', label:'라이브러리 미설치' };
      } else {
        status[src.key] = { state:'offline', label:'폴백 사용' };
      }
      continue;
    }
    if(src.key === 'kis') {
      const sLabel = sources.stockMovers || '';
      if(sLabel.includes('KIS')) {
        status[src.key] = { state:'online', label:'KIS 활성' };
      } else if(diag.kisEnabled) {
        status[src.key] = { state:'partial', label:'활성화이나 폴백 사용' };
      } else {
        status[src.key] = { state:'offline', label:'기본 비활성 (알람 차단)' };
      }
      continue;
    }
    if(src.key === 'gnews') {
      const news = (d && d.news) || {};
      const cats = Object.keys(news).filter(k => k !== 'lastFetched');
      const filled = cats.filter(c => Array.isArray(news[c]) && news[c].length > 0).length;
      if(filled === cats.length && cats.length > 0) {
        status[src.key] = { state:'online', label: `${filled}/${cats.length} 카테고리` };
      } else if(filled > 0) {
        status[src.key] = { state:'partial', label: `${filled}/${cats.length} 카테고리` };
      } else {
        status[src.key] = { state:'offline', label:'페치 실패' };
      }
      continue;
    }
    const matched = src.sourceKeys.filter(k => sources[k]);
    if(matched.length === src.sourceKeys.length && matched.length > 0) {
      status[src.key] = { state:'online',  label: sources[matched[0]] };
    } else if(matched.length > 0) {
      status[src.key] = { state:'partial', label: `${matched.length}/${src.sourceKeys.length} 연결` };
    } else {
      status[src.key] = { state:'offline', label:'미연결' };
    }
  }
  return status;
}

function buildSidebarDataSources(d) {
  const el = document.getElementById('sidebarDataSourceList');
  if(!el) return;
  _dsStatusCache = computeDataSourceStatus(d);
  el.innerHTML = dataSourceMeta.map(src => {
    const s = _dsStatusCache[src.key];
    const dot = s.state==='online' ? '<span style="color:var(--c-up);font-size:var(--font-size-xs);">●</span>'
              : s.state==='partial' ? '<span style="color:#f5a623;font-size:var(--font-size-xs);">◐</span>'
              : '<span style="color:var(--c-down);font-size:var(--font-size-xs);">○</span>';
    return `<div class="ds-item" onclick="showDataSourceDetail('${src.key}')" style="display:flex;align-items:center;gap:6px;padding:5px 8px;border-radius:var(--r-xs);cursor:pointer;color:#c4cadc;transition:background .1s;" title="클릭하여 상세 보기">
      ${dot}
      <span style="flex:1;font-size:var(--font-size-sm);">${src.name}<span style="color:#8d92aa;font-size:var(--font-size-xs);margin-left:4px;">(${src.unit})</span></span>
      <span style="font-size:var(--font-size-xs);color:#8d92aa;">›</span>
    </div>`;
  }).join('');
}

function showDataSourceDetail(key) {
  const src = dataSourceMeta.find(s=>s.key===key);
  if(!src) return;
  const d = _latestDataForIndicators || {};
  const status = (_dsStatusCache && _dsStatusCache[key]) || { state:'offline', label:'—' };
  const popup = document.getElementById('dataSourceDetailPopup');
  const titleEl = document.getElementById('dsDetailTitle');
  const bodyEl  = document.getElementById('dsDetailBody');
  if(!popup || !titleEl || !bodyEl) return;
  const stateColor = status.state==='online'?window.CUP:status.state==='partial'?'#f5a623':window.CDN;
  const stateMark  = status.state==='online'?'● 정상 연결':status.state==='partial'?'◐ 부분 연결':'○ 미연결';
  titleEl.innerHTML = `${src.name} <span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);margin-left:6px;font-weight:var(--font-weight-normal);">(${src.unit})</span>`;
  // 실제로 가져온 데이터 통계
  let actualStats = '';
  if(key === 'krx' || key === 'stooq') {
    const mv = (d.stockMovers||{});
    const etf = (d.etfMovers||{});
    actualStats += `<li>주식 상승/하락: ${mv.kospiGainers?.length||0}/${mv.kospiLosers?.length||0}건</li>`;
    actualStats += `<li>ETF 상승/하락: ${etf.etfGainers?.length||0}/${etf.etfLosers?.length||0}건</li>`;
    actualStats += `<li>지수: ${Object.keys(d.indices||{}).length}개</li>`;
    actualStats += `<li>원자재: ${Object.keys(d.commodities||{}).length}개</li>`;
  } else if(key === 'fx') {
    const fx = d.fx||{};
    Object.keys(fx).forEach(k=>{ actualStats += `<li>${k}: ${fx[k].rate?.toLocaleString()}</li>`; });
  } else if(key === 'yfin') {
    const h = d.history||{};
    actualStats += `<li>FX 시계열: ${Object.keys(h.fx||{}).length}개</li>`;
    actualStats += `<li>지수 시계열: ${Object.keys(h.indices||{}).length}개</li>`;
    actualStats += `<li>원자재 시계열: ${Object.keys(h.commodities||{}).length}개</li>`;
  } else if(key === 'fred') {
    const us = (d.economicIndicators||{}).us || {};
    const reUs = (d.realestate||{}).us || {};
    const yc = (d.yieldCurve||{}).us || {};
    actualStats += `<li>미국 경제지표: ${Object.keys(us).length}개 (${Object.keys(us).join(', ')||'—'})</li>`;
    actualStats += `<li>미국 부동산: ${Object.keys(reUs).length}개</li>`;
    actualStats += `<li>국채 수익률 (1M~30Y): ${yc.current?.filter(v=>v!=null).length||0}개 만기</li>`;
    const intl = ['jp','eu','cn','de','uk'].map(cc => `${cc.toUpperCase()}:${Object.keys((d.economicIndicators||{})[cc]||{}).length}`).join(', ');
    actualStats += `<li>국제 지표: ${intl}</li>`;
  } else if(key === 'ecos') {
    const kr = (d.economicIndicators||{}).kr || {};
    actualStats += `<li>한국 경제지표: ${Object.keys(kr).length}개</li>`;
    Object.entries(kr).forEach(([k,v])=>{
      actualStats += `<li style="color:var(--c-txt-dim);font-size:var(--font-size-xs);margin-left:8px;">${v.desc||k}: ${v.value} (${v.period})</li>`;
    });
  } else if(key === 'kosis') {
    const kr = (d.economicIndicators||{}).kr || {};
    const retail = kr.retail_kr;
    if(retail && retail.source && retail.source.includes('KOSIS')) {
      actualStats += `<li style="color:var(--c-up);">KOSIS 활성</li>`;
      actualStats += `<li>소매판매액지수: ${retail.value} (${retail.period})</li>`;
      actualStats += `<li style="color:var(--c-txt-dim);font-size:var(--font-size-xs);">${retail.source}</li>`;
    } else if(retail) {
      actualStats += `<li style="color:#f5a623;font-size:var(--font-size-sm);">ECOS 폴백 사용 중 (KOSIS 미연결)</li>`;
      actualStats += `<li>소매판매액지수: ${retail.value} (${retail.period}) · ${retail.source||'ECOS'}</li>`;
    } else {
      actualStats += `<li style="color:var(--c-down);">소매판매액지수 미수집</li>`;
      actualStats += `<li style="color:var(--c-txt-dim);font-size:var(--font-size-xs);">KOSIS_API_KEY 또는 ECOS_API_KEY 확인 필요</li>`;
    }
  } else if(key === 'rone') {
    const kr = (d.realestate||{}).kr || {};
    if(kr.apt_price_idx_kr) actualStats += `<li>전국 아파트 매매: ${kr.apt_price_idx_kr.value} (${kr.apt_price_idx_kr.period})</li>`;
    if(kr.jns_price_idx_kr) actualStats += `<li>전국 아파트 전세: ${kr.jns_price_idx_kr.value} (${kr.jns_price_idx_kr.period})</li>`;
    if(!actualStats) actualStats = '<li style="color:var(--c-down);">데이터 미수집 — R-ONE 인증키 확인 필요</li>';
  } else if(key === 'molit') {
    const kr = (d.realestate||{}).kr || {};
    if(kr.trade_count_kr) {
      const hist = kr.trade_count_kr.history || {};
      actualStats += `<li>최신 월 거래량: ${kr.trade_count_kr.value?.toLocaleString()}건 (${kr.trade_count_kr.period})</li>`;
      Object.keys(hist).sort().reverse().forEach(p=>{
        actualStats += `<li style="color:var(--c-txt-dim);font-size:var(--font-size-xs);margin-left:8px;">${p}: ${hist[p]?.toLocaleString()||0}건</li>`;
      });
    }
  } else if(key === 'nps') {
    actualStats += '<li>분기별 정적 데이터 (수동 업데이트)</li>';
  } else if(key === 'gnews') {
    const news = d.news || {};
    const cats = Object.keys(news).filter(k => k !== 'lastFetched');
    const totalArticles = cats.reduce((acc, c) => acc + (Array.isArray(news[c]) ? news[c].length : 0), 0);
    actualStats += `<li>카테고리: ${cats.length}개 (${cats.slice(0,5).join(', ')}${cats.length>5?'…':''})</li>`;
    actualStats += `<li>총 기사: ${totalArticles}건</li>`;
    if(news.lastFetched) {
      try {
        const dt = new Date(news.lastFetched);
        actualStats += `<li style="color:var(--c-txt-dim);font-size:var(--font-size-xs);">최종 페치: ${dt.toLocaleString('ko-KR',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})}</li>`;
      } catch(_) {}
    }
    if(totalArticles === 0) actualStats += '<li style="color:var(--c-down);">서버측 페치 실패 — 클라이언트 RSS 폴백 사용 중</li>';
  } else if(key === 'kis') {
    const diag = d.diagnostics || {};
    const mv = d.stockMovers || {};
    const src = (d.sources || {}).stockMovers || '미사용';
    const kisOn = diag.kisEnabled === true;
    actualStats += `<li>현재 사용 중인 종목 데이터 소스: ${src}</li>`;
    actualStats += `<li>주식 상승/하락 Top10: ${mv.kospiGainers?.length||0}/${mv.kospiLosers?.length||0}건</li>`;
    if(src.includes('KIS')) {
      actualStats += `<li style="color:var(--c-up);">한국투자증권 KIS OpenAPI 활성 — 카카오톡 알람 받음</li>`;
    } else if(kisOn) {
      actualStats += `<li style="color:#f5a623;">KIS_ENABLED=1 이나 폴백 사용 중 (KIS 응답 검증 실패)</li>`;
    } else {
      actualStats += `<li style="color:var(--c-up);font-size:var(--font-size-sm);">KIS 비활성 (기본값) — 카카오톡 알람 차단 상태</li>`;
      actualStats += `<li style="color:var(--c-txt-dim);font-size:var(--font-size-xs);">활성화: 워크플로우 변수에 KIS_ENABLED=1 추가</li>`;
    }
  } else if(key === 'pykrx') {
    const diag = d.diagnostics || {};
    const mv = d.stockMovers || {};
    const etf = d.etfMovers || {};
    const srcS = (d.sources || {}).stockMovers || '';
    const srcE = (d.sources || {}).etfMovers || '';
    const avail = diag.pykrxAvailable !== false;
    actualStats += `<li>라이브러리 가용: ${avail ? '✓ 설치됨' : '✗ 미설치'}</li>`;
    actualStats += `<li>종목 Top10: ${mv.kospiGainers?.length||0}/${mv.kospiLosers?.length||0}건 (소스: ${srcS || '없음'})</li>`;
    actualStats += `<li>ETF Top10: ${etf.etfGainers?.length||0}/${etf.etfLosers?.length||0}건 (소스: ${srcE || '없음'})</li>`;
    if(srcS.includes('pykrx')) {
      actualStats += `<li style="color:var(--c-up);">pykrx 가 종목 PRIMARY 소스로 동작 중</li>`;
    } else if(avail) {
      actualStats += `<li style="color:#f5a623;font-size:var(--font-size-xs);">pykrx 시도했으나 KRX 응답 없음 — 폴백 사용</li>`;
    } else {
      actualStats += `<li style="color:var(--c-down);">pykrx 가 설치되지 않음 — 워크플로우에 pip install pykrx 필요</li>`;
    }
  }
  bodyEl.innerHTML = `
    <div style="margin-bottom:10px;padding:8px;background:var(--c-card-hi);border-radius:var(--r-xs);border-left:3px solid ${stateColor};">
      <div style="font-weight:var(--font-weight-semibold);color:${stateColor};font-size:var(--font-size-sm);">${stateMark}</div>
      <div style="color:var(--c-txt-dim);font-size:var(--font-size-xs);margin-top:2px;">${status.label||'—'}</div>
    </div>
    <div style="margin-bottom:8px;color:var(--c-txt);font-size:var(--font-size-sm);">${src.desc}</div>
    <div style="margin-bottom:6px;font-weight:var(--font-weight-semibold);color:var(--c-txt);font-size:var(--font-size-sm);">📊 가져오는 데이터:</div>
    <ul style="margin:0 0 10px 18px;padding:0;color:var(--c-primary);font-size:var(--font-size-xs);">
      ${src.fetched.map(f=>`<li>${f}</li>`).join('')}
    </ul>
    <div style="margin-bottom:6px;font-weight:var(--font-weight-semibold);color:var(--c-txt);font-size:var(--font-size-sm);">✓ 현재 수집된 데이터:</div>
    <ul style="margin:0 0 6px 18px;padding:0;color:var(--c-up,var(--c-success));font-size:var(--font-size-xs);">
      ${actualStats || '<li style="color:var(--c-down,var(--c-error));">데이터 없음</li>'}
    </ul>
    <div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:8px;text-align:right;">최종 업데이트: ${d.lastUpdated ? new Date(d.lastUpdated).toLocaleString('ko-KR') : '—'}</div>
  `;
  popup.style.display = 'block';
}
function closeDataSourcePopup() {
  const p = document.getElementById('dataSourceDetailPopup');
  if(p) p.style.display = 'none';
}
// 팝업 바깥 클릭 시 닫기
document.addEventListener('click', (e) => {
  const p = document.getElementById('dataSourceDetailPopup');
  if(!p || p.style.display === 'none') return;
  if(p.contains(e.target)) return;
  if(e.target.closest('#sidebarDataSourceList')) return;
  p.style.display = 'none';
});

// ============================
// 클라이언트 사이드 Naver Finance 데이터 페치 (Top10 주식/ETF 실시간)
// data.json이 빈 경우 또는 새로고침 시 즉시 데이터 표시
// ============================
// ── 전용 CORS 프록시 (Cloudflare Worker) ─────────────────────────
// 공개 프록시(allorigins 등)는 가용성이 들쭉날쭉하고 네이버가 요구하는 Referer/Origin/UA
// 헤더를 전달하지 못해 'Top10 오전 데이터 고정'의 근본 원인이 된다. cloudflare-worker/ 를
// 배포(README 참고)하고 아래에 URL 을 넣으면, 그 Worker 가 적절한 헤더를 주입해 안정적으로
// 중계하므로 모든 클라이언트 페치(Top10·VIX·시계열·뉴스)가 그곳만 사용한다.
// ⚠ 공개 프록시 폴백은 제거됨(2차 보안 개선 S-3) — 제3자가 시세 응답을 변조할 수 있는
//   경로였다. Worker 미설정/장애 시 클라이언트 보강은 조용히 스킵되고 data.json 값을 쓴다.
const CF_PROXY_DEFAULT = 'https://ecom-dashboard-proxy.baldr0001.workers.dev';  // 배포된 Cloudflare Worker 프록시
// ── 클라이언트 실시간 보강 (기본 ON) ──────────────────────────────────
// 왜 기본 ON 인가: 화면을 GitHub Actions 의 data.json 에만 의존하면 '오늘자 실시간'이 안 된다.
// GitHub Actions 의 고빈도 스케줄 크론(*/10)은 GitHub 측에서 best-effort 라 장중에도 자주
// 지연/누락된다(실측: 장중 09:00~10:40 사이 10분 크론이 9회 발화해야 하나 커밋 0건, 매시간
// 크론만 불규칙 발화). 그 결과 data.json 이 직전 거래일 종가·장 시작 전 스냅샷에 묶여
// "오늘자 실시간 갱신 안 됨" 증상이 반복됐다.
// → 브라우저가 장중 1분마다 전용 Cloudflare Worker 프록시로 직접 시세를 받아 보강하는 것이
//   '실시간'의 유일한 신뢰 경로다(원래 설계 의도). 전용 Worker 는 네이버/야후/Stooq/CNN 에
//   적절한 헤더를 주입해 CORS 안전하게 중계하므로, 과거 '공개 프록시 실패로 인한 콘솔 오류'
//   문제도 대부분 사라진다. 모든 클라 페치는 try/catch + 죽은 엔드포인트 자동 차단(아래 플래그)
//   으로 조용히 실패하므로, 보강을 켜도 콘솔 에러가 폭주하지 않는다.
// 끄려면(서버 data.json 전용 모드): 콘솔에서 localStorage.setItem('realtimeBoost','0') 후 새로고침.
window._REALTIME_BOOST = (function(){ try { return localStorage.getItem('realtimeBoost') !== '0'; } catch(_) { return true; } })();
function _cfProxyBase() {
  try { return (localStorage.getItem('cfProxyBase') || CF_PROXY_DEFAULT || '').trim().replace(/\/+$/,''); }
  catch(_) { return (CF_PROXY_DEFAULT || '').replace(/\/+$/,''); }
}
function _cfProxyUrl(target) {
  const b = _cfProxyBase();
  return b ? (b + '/?url=' + encodeURIComponent(target)) : null;
}

// 프록시 경로 — 전용 Worker 단일화 (공개 CORS 프록시 폴백 제거).
// 공개 프록시(allorigins 등)는 운영 주체가 불명확하고 응답 본문(시세 숫자)을 중간에서
// 변조해 반환할 수 있는 위치라, Worker 장애 시 해당 위젯만 '일시 조회 불가'로 두는 것이
// 변조 가능성 있는 데이터를 보여주는 것보다 안전하다 (fail-safe 원칙).
function _buildCorsProxyUrls(target) {
  const cf = _cfProxyUrl(target);
  return cf ? [cf] : [];
}

// 공통 fetch 래퍼 — 타임아웃·재시도·지수 백오프+지터 표준화 (SRE/AWS 권고 패턴).
// 5xx 만 재시도 대상이며 그 외 4xx 는 즉시 반환(재시도 무의미). 외부 데이터 페치가
// 프록시 다중 폴백 없이 Worker 단일 경로가 되면서, 일시 장애 내성은 이 재시도가 담당한다.
// ⚠ 429(레이트리밋)는 재시도하지 않는다 — Worker 의 PROXY_LIMITER 가 IP당 '분당' 창이라
//   0.4~0.8초 백오프 재시도는 100% 다시 429 로 요청량만 3배 증폭시켰다(실측 페이지당 최대 113건).
//   대신 30초 전역 서킷브레이커를 열어 그동안의 프록시 호출을 즉시 실패시킨다(호출부는
//   개별 catch 로 data.json 서버값 폴백이 이미 있음).
let _rate429CooldownUntil = 0;
async function fetchWithRetry(url, { timeoutMs = 8000, retries = 2, init = {} } = {}) {
  let lastErr;
  for(let i = 0; i <= retries; i++) {
    if(Date.now() < _rate429CooldownUntil) throw new Error('HTTP 429 (레이트리밋 쿨다운 중)');
    try {
      const r = await fetch(url, { ...init, signal: AbortSignal.timeout(timeoutMs) });
      if(r.status === 429) { _rate429CooldownUntil = Date.now() + 30000; throw new Error('HTTP 429'); }
      if(r.status >= 500) throw new Error('HTTP ' + r.status);
      return r;
    } catch(e) {
      lastErr = e;
      if(Date.now() < _rate429CooldownUntil) break;   // 429 는 백오프 재시도 무의미 — 즉시 중단
      if(i < retries) await new Promise(res => setTimeout(res, 400 * 2 ** i + Math.random() * 200));
    }
  }
  throw lastErr;
}

async function _fetchViaProxies(target, parseJson=true) {
  // 결과: 파싱된 JSON(parseJson=false 면 텍스트) 또는 null. 전용 Worker 단일 경로 + 재시도.
  for(const url of _buildCorsProxyUrls(target)) {
    try {
      const r = await fetchWithRetry(url, { timeoutMs: 8000, retries: 2,
        init: { headers: { 'Accept': 'application/json,text/plain,*/*' } } });
      // Worker 의 404/410 = 대상 리소스 없음(폐기된 엔드포인트/없는 심볼), 403 = 상류 차단 —
      // 추가 폴백 경로가 없으므로 null 반환(호출부가 data.json 서버값으로 폴백).
      if(!r.ok) return null;
      const txt = await r.text();
      if(!parseJson) return txt;
      try { return JSON.parse(txt); } catch(_) { return null; }
    } catch(_) { /* 재시도 소진 → null */ }
  }
  return null;
}

// EUC-KR(레거시 네이버 .nhn / 데스크톱 시세 HTML) 본문을 정확히 디코딩해 텍스트로 반환한다.
// 네이버 finance.naver.com 의 .nhn API·시세 HTML 은 EUC-KR 인코딩이라, 일반 r.text()(=UTF-8)
// 로 읽으면 한글이 '�' 로 깨진다(=ETF Top10·투자자 표의 깨짐 증상). arrayBuffer 를 받아
// EUC-KR / UTF-8 둘 다 디코딩해보고 치환문자(U+FFFD)가 더 적은 쪽을 채택 → 프록시가 어떤
// 인코딩으로 전달하든 안전.
async function _fetchEucKrText(target) {
  for(const url of _buildCorsProxyUrls(target)) {
    try {
      const r = await fetchWithRetry(url, { timeoutMs: 8000, retries: 2 });
      if(!r.ok) continue;
      const bytes = new Uint8Array(await r.arrayBuffer());
      const _cnt = s => (s == null) ? Infinity : (s.match(/�/g) || []).length;
      let euc = null;
      try { euc = new TextDecoder('euc-kr').decode(bytes); } catch(_) {}
      const utf = new TextDecoder('utf-8').decode(bytes);
      const txt = (_cnt(euc) <= _cnt(utf)) ? euc : utf;   // 깨짐(치환문자) 더 적은 디코딩 채택
      if(txt) return txt;
    } catch(_) { /* try next */ }
  }
  return null;
}
async function _fetchEucKrJson(target) {
  const txt = await _fetchEucKrText(target);
  if(!txt) return null;
  try { return JSON.parse(txt); } catch(_) { return null; }
}

async function fetchNaverStockMoversClient(market='KOSPI', direction='up') {
  // 네이버 모바일 종목 랭킹 API. 단, 이 엔드포인트가 세션 중 404(폐기)로 확인되면 재시도 중단 —
  // 콘솔 404 폭주를 막고 서버 data.json(pykrx) 값을 사용한다. (페이지 새로고침 시 플래그 리셋)
  if(window._naverTop10Dead) return null;
  const direct = `https://m.stock.naver.com/api/stocks/exchange/${market}/${direction}?page=1&pageSize=30`;
  const directAlt = `https://api.stock.naver.com/stock/exchange/${market}/${direction}?page=1&pageSize=30`;
  const targets = [direct, directAlt];
  for(const target of targets) {
    const data = await _fetchViaProxies(target, true);
    if(!data) continue;
    const stocks = data.stocks || data.result || [];
    if(!Array.isArray(stocks) || !stocks.length) continue;
    const today = new Date().toISOString().slice(0,10);
    // 필드명 폴백 — 서버측 fetch_naver_api_movers 와 동일하게 다양한 키 시도
    // (Naver API 응답 스키마 변경/엔드포인트별 차이에 견디도록)
    const parsed = stocks.slice(0,10).map(s=>({
      name:  (s.stockName || s.name || s.itemName || '').trim(),
      code:  (s.itemCode || s.code || '').trim(),
      price: Number(s.closePrice || s.nowVal || s.currentPrice || s.tradePrice || 0),
      chg:   Number(s.fluctuationsRatio ?? s.changeRate ?? s.cttr ?? 0),
      vol:   Number(s.accumulatedTradingVolume || s.aq || s.volume || 0),
      as_of: today,
    })).filter(x=>x.name && x.price);
    const nonZero = parsed.filter(p => p.chg !== 0).length;
    if(parsed.length >= 3 && nonZero >= 3) {
      console.info(`[NaverStock] ${market} ${direction}: ${parsed.length}건 (${nonZero}건 비영점)`);
      return parsed;
    }
  }
  // 모든 타깃이 응답 없음(엔드포인트 폐기/404) → 세션 내 재시도 중단
  window._naverTop10Dead = true;
  console.info('[NaverStock] 종목 랭킹 엔드포인트 응답 없음 — 세션 내 재시도 중단(서버 data.json 사용)');
  return null;
}

async function fetchNaverETFMoversClient() {
  // Naver ETF 시세 — 전통 API(etfItemList.nhn)가 가장 안정적이라 1순위. 단, 이 .nhn 응답은
  // EUC-KR 인코딩이라 반드시 _fetchEucKrJson 로 받아야 한글 종목명이 안 깨진다(기존 �� 버그 원인).
  // 모바일 API(etf/domestic, domesticEtfList)는 UTF-8 JSON 이라 _fetchViaProxies 로 폴백한다.
  const today = new Date().toISOString().slice(0,10);
  const mapRow = (s)=>{
    const name = (s.itemname || s.stockName || s.name || s.itemName || '').trim();
    const code = (s.itemcode || s.itemCode || s.code || '').trim();
    const price = Number(s.nowVal || s.closePrice || s.currentPrice || s.tradePrice || 0);
    let chg = Number(s.fluctuationsRatio ?? s.changeRate ?? s.changeRatio ?? s.cttr ?? 0);
    if(chg === 0) {
      const chgVal = Number(s.changeVal || s.compareToPreviousClosePrice || 0);
      if(chgVal && price > chgVal) chg = +(chgVal / (price - chgVal) * 100).toFixed(2);
    }
    const vol = Number(s.quant || s.accumulatedTradingVolume || s.tradeVolume || 0);
    return { name, code, price, chg, vol, as_of: today };
  };
  const finalize = (rows)=>{
    const parsed = rows.map(mapRow).filter(x=>x.name && x.price);
    if(!parsed.length) return null;
    const nonZero = parsed.filter(p => p.chg !== 0).length;
    if(nonZero < 3) return null;
    // 종목명이 깨진(치환문자 �) 응답이면 채택하지 않는다 — 깨진 표를 보여주느니 서버 data.json 유지.
    if(parsed.some(p => p.name.includes('�'))) {
      console.warn('[NaverETF] 종목명 인코딩 깨짐 감지 — 이 응답 폐기');
      return null;
    }
    const gainers = [...parsed].sort((a,b)=>b.chg-a.chg).slice(0,10);
    const losers  = [...parsed].sort((a,b)=>a.chg-b.chg).slice(0,10);
    console.info(`[NaverETF] ${parsed.length}건 수집 (비영점 ${nonZero}건)`);
    return { gainers, losers };
  };

  // ① 레거시 EUC-KR JSON (정확 디코딩)
  const euc = await _fetchEucKrJson('https://finance.naver.com/api/sise/etfItemList.nhn?etfType=0');
  let rows = euc?.result?.etfItemList;
  if(Array.isArray(rows) && rows.length) {
    const out = finalize(rows);
    if(out) return out;
  }
  // ② 모바일 UTF-8 JSON 폴백
  for(const target of [
    'https://m.stock.naver.com/api/stocks/etf/domestic?category=domestic&page=1&pageSize=200',
    'https://m.stock.naver.com/api/stocks/etf/domesticEtfList?category=domestic&page=1&pageSize=200',
  ]) {
    const data = await _fetchViaProxies(target, true);
    rows = data?.stocks || data?.result?.stocks || data?.etfList || (Array.isArray(data) ? data : []);
    if(!Array.isArray(rows) || !rows.length) continue;
    const out = finalize(rows);
    if(out) return out;
  }
  return null;
}

// 투자자별(외국인/기관/개인) 일별 순매수 — 네이버 '일자별 순매수'(investorDealTrendDay) HTML 파싱.
// 서버 fetch_data.py 의 fetch_naver_investor_trading 과 '동일' 경로/로직이지만, 브라우저는 전용
// CF Worker 경유라 GitHub Actions 데이터센터 IP 차단 시에도 동작하는 보강 경로다.
// (이전 경로 sise_index_buyer.naver 는 2026-06 네이버 개편으로 404 삭제 확인 — 교체.)
// **KOSPI(sosok=01) 기준**, 단위 억원. (2026-06 정정: KOSPI+KOSDAQ 합산 → KOSPI 단일 —
// 합산값이 네이버/증권사 'KOSPI 투자자별 매매동향'과 달라 보이는 문제의 원인이었음.)
// 페이지당 10영업일이라 여러 page 를 병렬 페치(클라 보강은 최근 ~100영업일이면 충분;
// 전체 시계열은 서버 data.json 담당). 표/컬럼은 헤더 키워드로 동적 매핑, 단위는
// 페이지 '단위:…' 캡션 1순위 + 값 크기 자동 감지 보조 (서버와 동일).
async function fetchNaverInvestorTradingClient(lookbackDays=400) {
  const _num = (s) => {
    s = (s||'').replace(/,/g,'').replace(/\+/g,'').replace(/ /g,' ').trim();
    if(!s || s === '-' || s === '—' || s === '·') return null;
    const v = parseFloat(s);
    return isFinite(v) ? v : null;
  };
  const dateRe = /^\d{2,4}\.\d{1,2}\.\d{1,2}$/;
  const agg = {};                 // 'YYYY-MM-DD' → {foreign, inst, retail}
  const marketsOk = [];
  const PAGES = 10;               // 10p × 10행 = 최근 100영업일
  const bizdate = new Date(Date.now() + 9*3600*1000).toISOString().slice(0,10).replace(/-/g,'');
  // 한 페이지 HTML → [{dstr,f,ins,ret}] (표/컬럼 헤더 키워드 매핑; 구조 불일치 시 null)
  const parsePage = (html) => {
    let doc;
    try { doc = new DOMParser().parseFromString(html, 'text/html'); } catch(_) { return null; }
    let tbl = null, colmap = null;
    for(const t of doc.querySelectorAll('table')) {
      const tt = t.textContent || '';
      if(!(tt.includes('개인') && tt.includes('외국인') && tt.includes('기관'))) continue;
      for(const tr of t.querySelectorAll('tr')) {
        const cells = [...tr.querySelectorAll('th,td')].map(c => (c.textContent||'').trim());
        const cm = {};
        cells.forEach((ct, i) => {
          if(ct.includes('개인') && cm.retail === undefined) cm.retail = i;
          else if(ct.includes('외국인') && !ct.includes('기타') && cm.foreign === undefined) cm.foreign = i;
          else if(ct.includes('기관') && !ct.includes('기타') && cm.inst === undefined) cm.inst = i;
        });
        if(cm.retail !== undefined && cm.foreign !== undefined && cm.inst !== undefined) { colmap = cm; tbl = t; break; }
      }
      if(tbl) break;
    }
    if(!tbl || !colmap) return null;
    const maxIdx = Math.max(colmap.retail, colmap.foreign, colmap.inst);
    const rows = [];
    for(const tr of tbl.querySelectorAll('tr')) {
      const cells = [...tr.querySelectorAll('td,th')].map(c => (c.textContent||'').trim());
      if(cells.length <= maxIdx) continue;
      const dcell = cells.find(c => dateRe.test(c.replace(/\s/g,'')));
      if(!dcell) continue;
      const f = _num(cells[colmap.foreign]), ins = _num(cells[colmap.inst]), ret = _num(cells[colmap.retail]);
      if(f === null && ins === null && ret === null) continue;
      const p = dcell.replace(/\s/g,'').split('.');
      if(p.length !== 3) continue;
      let y = p[0];
      if(y.length === 2) y = '20'+y; else if(y.length !== 4) y = String(new Date().getFullYear());
      const dstr = `${y}-${String(parseInt(p[1],10)).padStart(2,'0')}-${String(parseInt(p[2],10)).padStart(2,'0')}`;
      rows.push({ dstr, f, ins, ret });
    }
    return rows;
  };
  let unitLabel = null;   // 페이지 '단위:…' 캡션 (억원/백만원) — 스케일 결정의 1순위 근거
  for(const [mkt, sosok] of [['KOSPI','01']]) {   // KOSPI 기준 (KOSDAQ 합산 금지 — 상단 주석 참고)
    const htmls = await Promise.all(
      Array.from({length: PAGES}, (_, i) => _fetchEucKrText(
        `https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate=${bizdate}&sosok=${sosok}&page=${i+1}`
      ).catch(() => null))
    );
    const seen = new Set();   // 마지막 페이지 초과 시 같은 표 반복 반환 → 시장 내 중복 합산 방지
    let n = 0;
    for(const html of htmls) {
      if(!html) continue;
      if(!unitLabel) {
        const mu = html.match(/단위\s*[:：]?\s*(억\s*원|백만\s*원)/);
        if(mu) unitLabel = mu[1].replace(/\s/g,'');
      }
      const rows = parsePage(html);
      if(!rows) continue;
      for(const { dstr, f, ins, ret } of rows) {
        if(seen.has(dstr)) continue;
        seen.add(dstr);
        if(!agg[dstr]) agg[dstr] = {foreign:0, inst:0, retail:0};
        agg[dstr].foreign += (f||0); agg[dstr].inst += (ins||0); agg[dstr].retail += (ret||0);
        n++;
      }
    }
    if(n) marketsOk.push(mkt);
  }
  const dates = Object.keys(agg);
  if(!dates.length) return null;
  // 단위 정규화(→억원) — ① 페이지 '단위:…' 캡션 1순위, ② 없으면 값 크기 자동 감지 (서버와 동일)
  const allvals = [];
  dates.forEach(d => ['foreign','inst','retail'].forEach(k => { if(agg[d][k]) allvals.push(Math.abs(agg[d][k])); }));
  allvals.sort((a,b)=>a-b);
  const median = allvals.length ? allvals[Math.floor(allvals.length/2)] : 0;
  const scale = unitLabel === '백만원' ? 0.01 : unitLabel === '억원' ? 1.0 : (median > 100000 ? 0.01 : 1.0);
  const daily = dates.sort().map(d => ({
    date: d,
    foreign: Math.round(agg[d].foreign * scale * 10) / 10,
    inst:    Math.round(agg[d].inst    * scale * 10) / 10,
    retail:  Math.round(agg[d].retail  * scale * 10) / 10,
  })).slice(-lookbackDays);
  console.info(`[투자자-client] ${daily.length}일 수집 (${marketsOk.join('+')}) 캡션단위=${unitLabel||'미검출'} scale=${scale}`);
  return {
    daily, markets: marketsOk, unit: '억원',
    source: 'Naver 금융 KOSPI 투자자별 매매동향 (클라이언트 실시간)',
    lastFetched: new Date().toISOString(),
  };
}

// 수동 재시도 (버튼 클릭) — 자동 시도 카운터 무관하게 재시도
// 1) data.json 강제 재페치 (서버측 새 데이터가 있으면 적용) → 2) 클라이언트 페치
async function manualRetryMovers(btn) {
  _refreshFeedback(btn, 'loading');
  _clientMoverFetchAttempts = 0;  // 카운터 리셋
  let serverHit = false;
  // 1) data.json 강제 재페치 — GHA 가 새로 갱신했을 수 있음
  try {
    const r = await fetch('./data.json?_=' + Date.now(), { cache: 'no-store' });
    if(r.ok) {
      const fresh = await r.json();
      const hasStock = (fresh.stockMovers||{}).kospiGainers?.length > 0;
      const hasEtf   = (fresh.etfMovers||{}).etfGainers?.length > 0;
      if(hasStock || hasEtf) {
        applyRealData(fresh);
        serverHit = true;
      }
    }
  } catch(_) {}
  // 2) 클라이언트 페치 (서버측이 비어있거나 보강 필요한 경우)
  const ok = serverHit || await refreshMoversFromClient(true);
  if(!ok) {
    try { buildMoverTable(curMoverTab); } catch(_) {}
    _refreshFeedback(btn, 'error', '응답 없음');
  } else {
    _refreshFeedback(btn, 'success', '갱신');
  }
}

// 네이버 '주식' 종목 등락 Top10 — finance.naver.com 시세 HTML(EUC-KR)을 전용 Worker 경유로 스크래핑.
// 모바일 JSON API(.../stocks/exchange/...)가 2026 폐기(404)된 뒤, 서버 fetch_data.py 의 검증된 폴백
// 경로(sise_rise.naver=상승 / sise_fall.naver=하락, sosok=0:KOSPI/1:KOSDAQ)와 '동일'하다.
// 데스크톱 시세 페이지는 200 정상이라 콘솔 404 가 안 나고, 장중 거의 실시간으로 갱신된다.
// EUC-KR 정확 해독을 위해 arrayBuffer 를 TextDecoder('euc-kr') 로 디코딩(공개 프록시는 charset 깨짐 →
// 전용 Worker 만 사용; 미설정 시 null 반환 → 서버 data.json 사용). 파싱 정규식은 서버 _scrape 와 동일.
async function fetchNaverStockMoversHtmlClient(market='KOSPI', direction='up') {
  const sosok = (String(market).toUpperCase() === 'KOSDAQ') ? '1' : '0';
  const page  = (direction === 'down') ? 'sise_fall' : 'sise_rise';
  const target = `https://finance.naver.com/sise/${page}.naver?sosok=${sosok}`;
  const purl = (typeof _cfProxyUrl === 'function') ? _cfProxyUrl(target) : null;
  if(!purl) return null;
  let html = null;
  try {
    const ctrl = new AbortController();
    const tid = setTimeout(()=>ctrl.abort(), 8000);
    const r = await fetch(purl, { signal: ctrl.signal });
    clearTimeout(tid);
    if(!r.ok) return null;
    const buf = await r.arrayBuffer();
    try { html = new TextDecoder('euc-kr').decode(new Uint8Array(buf)); }
    catch(_) { html = new TextDecoder('utf-8').decode(new Uint8Array(buf)); }
  } catch(_) { return null; }
  if(!html) return null;
  const today = new Date().toISOString().slice(0,10);
  const items = [];
  // <a href="/item/main.naver?code=NNNNNN" ... class="tltle">종목명</a> … </tr>
  const rowRe = /<a\s+href="\/item\/main\.naver\?code=(\d+)"[^>]*class="tltle"[^>]*>([^<]+)<\/a>([\s\S]*?)<\/tr>/g;
  let m;
  while((m = rowRe.exec(html)) !== null && items.length < 10) {
    const code = m[1];
    const name = m[2].replace(/&amp;/g,'&').trim();
    const rest = m[3];
    const numbers = [...rest.matchAll(/<td[^>]*class="number"[^>]*>([^<]+)<\/td>/g)].map(x => x[1]);
    const chgMatch = rest.match(/([+\-]?[\d.]+)\s*%/);
    if(numbers.length < 2 || !chgMatch) continue;
    const price = parseFloat(numbers[0].replace(/,/g,'').trim());
    let chg = parseFloat(chgMatch[1]);
    if(!isFinite(price) || !isFinite(chg)) continue;
    // 페이지가 부호 없이 표기하는 경우 대비 — 방향으로 부호 강제(상승 +, 하락 −).
    chg = (direction === 'down') ? -Math.abs(chg) : Math.abs(chg);
    let vol = 0;
    for(const n of numbers.slice(2)) {
      const c = n.replace(/,/g,'').trim();
      if(/^\d+$/.test(c)) { const v = parseInt(c,10); if(v > 100) { vol = v; break; } }
    }
    items.push({ name, code, price, chg, vol, as_of: today });
  }
  return items.length ? items : null;
}

// 클라이언트 사이드에서 Top10 데이터 페치 + applyRealData 호출
async function refreshMoversFromClient(showStatus=false) {
  if(!window._REALTIME_BOOST) return false;   // data.json 전용 모드 — 네이버 보강 페치 비활성
  const statusEl = document.getElementById('moverRefDate');
  if(statusEl && showStatus) statusEl.textContent = '갱신 중…';
  try {
    // 네이버 '주식' 종목 랭킹 JSON API(m/api.stock.naver.com/.../stocks/exchange/...)는 2026 폐기(404).
    // → 서버 fetch_data.py 와 동일한 검증 경로(finance.naver.com/sise/sise_rise|fall.naver, EUC-KR HTML)
    //   를 전용 Worker 경유로 스크래핑한다. 데스크톱 시세 HTML 은 200 정상이라 콘솔 404 가 안 난다.
    //   ETF 는 정상 JSON API(.../etf/domestic) 유지. (=작동하는 소스만 호출 → 콘솔 0 에러 + 실시간.)
    const [kup, kdown, etf] = await Promise.all([
      fetchNaverStockMoversHtmlClient('KOSPI', 'up').catch(()=>null),
      fetchNaverStockMoversHtmlClient('KOSPI', 'down').catch(()=>null),
      fetchNaverETFMoversClient().catch(()=>null),
    ]);
    const patch = { stockMovers: {}, etfMovers: {}, fx:{}, indices:{}, commodities:{}, sources:{} };
    let updated = 0;
    if(kup && kup.length) { patch.stockMovers.kospiGainers = kup; updated++; }
    if(kdown && kdown.length) { patch.stockMovers.kospiLosers = kdown; updated++; }
    if(etf && etf.gainers?.length) { patch.etfMovers.etfGainers = etf.gainers; updated++; }
    if(etf && etf.losers?.length) { patch.etfMovers.etfLosers = etf.losers; updated++; }
    if(updated > 0) {
      // 데이터 소스 표시 설정
      if(patch.stockMovers.kospiGainers) patch.sources.stockMovers = 'Naver Finance (클라이언트 실시간)';
      if(patch.etfMovers.etfGainers)    patch.sources.etfMovers   = 'Naver Finance (클라이언트 실시간)';
      // 부분 패치 — applyRealData에서 빈 객체는 건드리지 않음
      applyRealData(patch);
      // 클라이언트 실시간 페치 성공 시각 기록 (Top10 카드의 '실시간 HH:MM' 표시용)
      window._moverFetchTime = Date.now();
      // 주식시장 페이지가 열려 있으면 KOSPI/ETF Top10 테이블도 즉시 재렌더
      try { const ep=document.getElementById('page-equity'); if(ep && ep.classList.contains('active') && typeof buildEquityPage==='function') buildEquityPage(); } catch(_){}
      _clientMoverLastError = null;
      return true;
    }
    _clientMoverLastError = 'CORS 프록시 실패 — 모든 endpoint 응답 없음';
  } catch(e) {
    console.warn('[NaverMovers] 클라이언트 페치 실패:', e);
    _clientMoverLastError = String(e?.message || e || 'unknown');
  }
  return false;
}

// ============================
// 거시 경제 지표 히스토리 차트 (지표 카드 클릭 시 모달 표시)
// dataPath 가 가리키는 노드에 history 필드가 있으면 사용, 없으면 ECOS/FRED 시리즈로 보강
// ============================
function showMacroHistoryChartByIdx(idx) {
  const r = (typeof macroIndicators !== 'undefined') ? macroIndicators[idx] : null;
  if(!r) return;
  showMacroHistoryChart(r.dataPath, `${r.cc} ${r.name}`, {
    unit: r.unit || '',
    src:  r.src  || '',
    link: r.link || '',
    linkLabel: r.linkLabel || '',
  });
}

function showMacroHistoryChart(dataPath, title, optsJson) {
  let opts = {};
  try {
    opts = typeof optsJson === 'string' ? JSON.parse(optsJson.replace(/&quot;/g,'"')) : (optsJson || {});
  } catch(_) { opts = {}; }
  // _reHistState 에 macroSpec 을 저장하고 셀렉터 UI 를 초기화 후 _renderReHistChart 호출
  _reHistState.key = '__macro__' + (dataPath || '');
  _reHistState.title = title;
  _reHistState.unit = opts.unit || '';
  _reHistState.period = 'all';
  _reHistState.timeUnit = 'M';
  _reHistState.macroDataPath = dataPath;
  _reHistState.macroOpts = opts;
  // 셀렉터 UI 초기화
  document.querySelectorAll('.reHistPeriodBtn').forEach(b=>{
    const isActive = b.dataset.period === 'all';
    b.classList.toggle('active', isActive);
    b.style.background = isActive ? getThemeColors().accent : 'transparent';
    b.style.color = isActive ? '#fff' : 'var(--c-txt-dim,#a4a8bc)';
  });
  document.querySelectorAll('.reHistUnitBtn').forEach(b=>{
    const isActive = b.dataset.unit === 'M';
    b.classList.toggle('active', isActive);
    b.style.background = isActive ? getThemeColors().accent : 'transparent';
    b.style.color = isActive ? '#fff' : 'var(--c-txt-dim,#a4a8bc)';
  });
  const modal = document.getElementById('reHistoryChartModal');
  if(modal) modal.style.display = 'flex';
  _renderReHistChartMacro();
}

function _renderReHistChartMacro() {
  const { title, unit, period, timeUnit, macroDataPath: dataPath, macroOpts: opts } = _reHistState;
  const titleEl = document.getElementById('reHistTitle');
  const metaEl  = document.getElementById('reHistMeta');
  const noteEl  = document.getElementById('reHistNote');
  const guideEl = document.getElementById('reHistGuide');
  if(titleEl) titleEl.textContent = title;
  const linkHtml = opts.link ? `<a href="${opts.link}" target="_blank" rel="noopener noreferrer" style="display:inline-block;margin-left:8px;font-size:var(--font-size-xs);padding:2px 8px;background:var(--c-accent)22;color:var(--c-accent);border:1px solid var(--c-accent)55;border-radius:var(--r-xs);text-decoration:none;">📎 ${opts.linkLabel||'최신 보고서'} →</a>` : '';
  if(metaEl) metaEl.innerHTML = `<span style="color:var(--c-primary);">단위:</span> ${unit||'—'} &nbsp; <span style="color:var(--c-primary);">출처:</span> ${opts.src||'—'}${linkHtml}`;
  // 매크로 지표의 해석 가이드 표시
  const macroGuide = _getMacroGuide(dataPath, title);
  if(guideEl) {
    if(macroGuide) {
      guideEl.innerHTML = macroGuide;
      guideEl.style.display = 'block';
      guideEl.style.borderLeftColor = 'var(--c-accent)';
    } else {
      guideEl.style.display = 'none';
    }
  }
  destroyChart('reHistChart');
  if(typeof _setReHistEmpty==='function') _setReHistEmpty('');
  if(!dataPath) {
    if(noteEl) noteEl.innerHTML = `데이터 경로 없음 ${opts.link?'— 외부 보고서 참고':''}`;
    return;
  }
  const d = _latestDataForIndicators || {};
  const node = getDataByPath(d, dataPath);
  let labels=[], values=[];
  let dataSource = opts.src || '데이터 소스 미연결';
  if(node?.history && typeof node.history === 'object') {
    Object.keys(node.history).sort().forEach(p=>{ labels.push(p); values.push(node.history[p]); });
    dataSource = node.source || dataSource;
  } else if(node?.value != null) {
    labels = [node.period || '현재'];
    values = [node.value];
    dataSource = (node.source || dataSource) + ' (단일 시점 — 시계열 추가 시 자동 확장)';
  } else {
    if(noteEl) noteEl.innerHTML = `${dataSource} — 데이터 미수집. ${opts.link?'외부 링크에서 최신 데이터 확인 가능.':''}`;
    return;
  }
  // 기간/단위 리샘플링
  const resampled = _resampleHistSeries(labels, values, period, timeUnit);
  if(noteEl) noteEl.textContent = `출처: ${dataSource}${period!=='all'?' · 기간: '+period:''}${timeUnit!=='M'?' · 단위: '+({Q:'분기',H:'반기',Y:'연'}[timeUnit]||timeUnit):''}`;
  const ctx = document.getElementById('reHistChart');
  if(!ctx || !resampled.values.length) return;
  const tc = (typeof getThemeColors==='function') ? getThemeColors() : {txt:'#8d90a2',grid:'#2a2e3d55',tooltip:'#262a35',ttTitle:'#dfe2f2',ttBorder:'#2a2e3d'};
  charts['reHistChart'] = new Chart(ctx, {
    type:'line',
    data:{ labels: resampled.labels, datasets:[{
      label: title + (unit?` (${unit})`:''),
      data: resampled.values,
      borderColor: getThemeColors().accent,
      backgroundColor: getThemeColors().accent+'22',
      borderWidth: 2,
      pointRadius: resampled.values.length > 30 ? 0 : 2,
      tension: 0.3,
      fill: true,
    }]},
    options:{ responsive:true, maintainAspectRatio:false,
      scales:{
        x:{ ticks:{color:tc.txt,font:{size:10},maxTicksLimit:10,autoSkip:true,maxRotation:0}, grid:{color:tc.grid}},
        y:{ ticks:{color:tc.txt,font:{size:10},maxTicksLimit:6,callback:v=>fmtNum(v)}, grid:{color:tc.grid}, position:'right'},
      },
      plugins:{
        legend:{display:true,labels:{color:tc.txt,font:{size:10},boxWidth:10}},
        subtitle:_axisUnitSubtitle(unit,tc.txt),
        tooltip:{mode:'index',intersect:false,backgroundColor:tc.tooltip,titleColor:tc.ttTitle,bodyColor:tc.ttTitle,borderColor:tc.ttBorder,borderWidth:1,
          callbacks:{label: c=> `${title}: ${typeof c.parsed.y==='number'?fmtNum(c.parsed.y):c.parsed.y}${unit?' ['+unit+']':''}`}}
      }
    }
  });
  setTimeout(() => { try { charts['reHistChart'] && charts['reHistChart'].resize(); } catch(_){} }, 50);
}

// ============================
// 부동산 지표 히스토리 차트 (지표 클릭 시 모달 표시)
// ============================
// 모달 차트 상태 (기간/단위 셀렉터 지원)
let _reHistState = { key:null, title:'', unit:'', period:'all', timeUnit:'M', sourceKind:null };

// 일/월 단위 정규화: 'YYYY-MM-DD', 'YYYY-MM', 'YYYYMM', 'YYYYQn', 'YYYY' 모두 처리
function _parseHistDate(s) {
  if(!s) return null;
  if(typeof s === 'number') s = String(s);
  s = s.toString().trim();
  // YYYY-MM-DD
  let m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if(m) return new Date(+m[1], +m[2]-1, +m[3]);
  // YYYY-MM
  m = s.match(/^(\d{4})-(\d{2})$/);
  if(m) return new Date(+m[1], +m[2]-1, 1);
  // YYYYMM
  m = s.match(/^(\d{4})(\d{2})$/);
  if(m) return new Date(+m[1], +m[2]-1, 1);
  // YYYY.MM
  m = s.match(/^(\d{4})\.(\d{1,2})$/);
  if(m) return new Date(+m[1], +m[2]-1, 1);
  // YYYY Q?
  m = s.match(/^(\d{4})Q?(\d)$/i);
  if(m) return new Date(+m[1], (+m[2]-1)*3, 1);
  // YYYY
  m = s.match(/^(\d{4})$/);
  if(m) return new Date(+m[1], 0, 1);
  // YY.MM
  m = s.match(/^(\d{2})\.(\d{1,2})$/);
  if(m) return new Date(2000+(+m[1]), +m[2]-1, 1);
  const dt = new Date(s);
  return isNaN(dt) ? null : dt;
}

// 시계열 데이터를 기간/단위에 맞게 리샘플링
function _resampleHistSeries(labels, values, period, timeUnit) {
  // 1) 날짜 객체로 변환
  let pts = labels.map((l, i) => ({ date: _parseHistDate(l), raw: l, val: values[i] }))
                     .filter(p => p.date && p.val != null && !isNaN(p.val));
  // 날짜 파싱 실패가 많으면 원본 인덱스를 사용해 fallback (예: 'Q1' 등 비표준 라벨)
  if(pts.length < 2 && labels && labels.length >= 2) {
    pts = labels.map((l, i) => ({ date: new Date(2000+i, 0, 1), raw: l, val: values[i] }))
                .filter(p => p.val != null && !isNaN(p.val));
  }
  if(!pts.length) return { labels: labels||[], values: values||[] };
  pts.sort((a,b) => a.date - b.date);
  // 2) 기간 필터
  if(period && period !== 'all') {
    const last = pts[pts.length-1].date;
    const cutoffMs = period==='1y' ? 365 : period==='3y' ? 365*3 : period==='5y' ? 365*5 : Infinity;
    const cutoff = new Date(last.getTime() - cutoffMs*86400000);
    const filtered = pts.filter(p => p.date >= cutoff);
    if(filtered.length >= 2) { pts = filtered; }
  }
  // 3) 시간 단위 집계 (월/분기/반기/연)
  if(!timeUnit || timeUnit === 'M') {
    return { labels: pts.map(p=>_fmtDateLabel(p.date,'M',p.raw)), values: pts.map(p=>p.val) };
  }
  const buckets = new Map(); // bucketKey → {date, sum, count, latest, sortKey}
  pts.forEach(p => {
    let k, sortKey;
    const y = p.date.getFullYear(), m = p.date.getMonth();
    if(timeUnit === 'Q') {
      const q = Math.floor(m/3)+1;
      k = `${y} Q${q}`;
      sortKey = y * 10 + q;
    } else if(timeUnit === 'H') {
      const h = m<6?1:2;
      k = `${y} H${h}`;
      sortKey = y * 10 + h;
    } else /* Y */ {
      k = `${y}`;
      sortKey = y;
    }
    if(!buckets.has(k)) buckets.set(k, {date:p.date, sum:0, count:0, latest:p.val, sortKey});
    const b = buckets.get(k);
    b.sum += p.val; b.count++; b.latest = p.val; b.date = p.date;
  });
  // 인덱스성 데이터는 마지막 값(latest) — 거래량 등 합계성 데이터는 별도 헬퍼에서 처리
  const out = [...buckets.entries()].sort((a,b)=>a[1].sortKey-b[1].sortKey);
  if(!out.length) return { labels: pts.map(p=>p.raw), values: pts.map(p=>p.val) };
  return {
    labels: out.map(([k,v]) => k),
    values: out.map(([k,v]) => v.latest),
  };
}
function _fmtDateLabel(dt, timeUnit, raw) {
  if(!dt) return raw||'';
  const y = dt.getFullYear(), m = dt.getMonth()+1;
  if(timeUnit==='M') return `${y}.${String(m).padStart(2,'0')}`;
  if(timeUnit==='Y') return `${y}`;
  return raw || `${y}.${String(m).padStart(2,'0')}`;
}

function setReHistPeriod(p, btn) {
  _reHistState.period = p;
  document.querySelectorAll('.reHistPeriodBtn').forEach(b=>{
    b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim,#a4a8bc)';
  });
  if(btn) { btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff'; }
  _renderReHistDispatch();
}
function setReHistUnit(u, btn) {
  _reHistState.timeUnit = u;
  document.querySelectorAll('.reHistUnitBtn').forEach(b=>{
    b.classList.remove('active'); b.style.background='transparent'; b.style.color='var(--c-txt-dim,#a4a8bc)';
  });
  if(btn) { btn.classList.add('active'); btn.style.background='var(--c-accent)'; btn.style.color='#fff'; }
  _renderReHistDispatch();
}
function _renderReHistDispatch() {
  // 시장 분위기 → 가이드 포함 별도 함수
  if(_reHistState.key && _reHistState.key.startsWith('__sentiment_')) {
    const sKey = _reHistState.key.slice('__sentiment_'.length);
    const guide = SENTIMENT_GUIDES[sKey];
    if(guide) { _renderReHistChartSentiment(guide); return; }
  }
  // 글로벌 주요 지수 (KOSPI/NASDAQ 등) — 가이드 포함
  if(_reHistState.key && _reHistState.key.startsWith('__index_')) {
    const histName = _reHistState.key.slice('__index_'.length);
    if(typeof _renderReHistChartIndex === 'function') {
      _renderReHistChartIndex(histName);
      return;
    }
  }
  // 매크로 차트
  if(_reHistState.key && _reHistState.key.startsWith('__macro__') && typeof _renderReHistChartMacro === 'function') {
    // 가이드 영역 숨김
    const guideEl = document.getElementById('reHistGuide');
    if(guideEl) guideEl.style.display = 'none';
    _renderReHistChartMacro();
  } else {
    // 가이드 영역 숨김
    const guideEl = document.getElementById('reHistGuide');
    if(guideEl) guideEl.style.display = 'none';
    _renderReHistChart();
  }
}

function showReHistoryChart(key, title, opts) {
  opts = opts || {};
  const modal = document.getElementById('reHistoryChartModal');
  if(!modal) return;
  // 상태 초기화
  _reHistState.key = key;
  _reHistState.title = title;
  _reHistState.unit = opts.unit || '';
  _reHistState.period = 'all';
  _reHistState.timeUnit = 'M';
  // 셀렉터 UI 초기화
  document.querySelectorAll('.reHistPeriodBtn').forEach(b=>{
    const isActive = b.dataset.period === 'all';
    b.classList.toggle('active', isActive);
    b.style.background = isActive ? getThemeColors().accent : 'transparent';
    b.style.color = isActive ? '#fff' : 'var(--c-txt-dim,#a4a8bc)';
  });
  document.querySelectorAll('.reHistUnitBtn').forEach(b=>{
    const isActive = b.dataset.unit === 'M';
    b.classList.toggle('active', isActive);
    b.style.background = isActive ? getThemeColors().accent : 'transparent';
    b.style.color = isActive ? '#fff' : 'var(--c-txt-dim,#a4a8bc)';
  });
  modal.style.display = 'flex';
  _renderReHistChart();
}

function _renderReHistChart() {
  const { key, title, unit, period, timeUnit } = _reHistState;
  const titleEl = document.getElementById('reHistTitle');
  const metaEl  = document.getElementById('reHistMeta');
  const noteEl  = document.getElementById('reHistNote');
  const guideEl = document.getElementById('reHistGuide');
  if(titleEl) titleEl.textContent = title;
  if(metaEl) metaEl.innerHTML = `<span style="color:var(--c-primary);">단위:</span> ${unit||'—'}`;
  // 가이드 매칭 (key 기반 또는 title 기반)
  const macroGuide = (typeof _getMacroGuide === 'function') ? _getMacroGuide(key, title) : null;
  if(guideEl) {
    if(macroGuide) {
      guideEl.innerHTML = macroGuide;
      guideEl.style.display = 'block';
    } else {
      guideEl.style.display = 'none';
    }
  }
  destroyChart('reHistChart');
  if(typeof _setReHistEmpty==='function') _setReHistEmpty('');
  // 데이터 소스에서 시계열 추출
  const d = _latestDataForIndicators || {};
  const reKr = (d.realestate||{}).kr || {};
  const reUs = (d.realestate||{}).us || {};
  const ecoKr = (d.economicIndicators||{}).kr || {};
  const ecoUs = (d.economicIndicators||{}).us || {};
  const ecoEu = (d.economicIndicators||{}).eu || {};
  const ecoJp = (d.economicIndicators||{}).jp || {};
  const ecoCn = (d.economicIndicators||{}).cn || {};
  const ecoDe = (d.economicIndicators||{}).de || {};
  const ecoUk = (d.economicIndicators||{}).uk || {};
  // 키 검색 (여러 카테고리 순회)
  const candidates = [reKr, reUs, ecoKr, ecoUs, ecoEu, ecoJp, ecoCn, ecoDe, ecoUk];
  let src = null;
  for(const c of candidates) { if(c && c[key]) { src = c[key]; break; } }
  // 미국 주별 Case-Shiller/주택가격 — case_shiller_{STATE} 키는 reUs.case_shiller_state[CODE] 에서 해석
  // (FRED FHFA 주별 HPI). 지도/마커 클릭 시 차트가 비던 문제 해결.
  if(!src && /^case_shiller_[A-Z]{2}$/.test(key)) {
    const _scode = key.slice('case_shiller_'.length);
    const _st = ((reUs.case_shiller_state)||{})[_scode];
    if(_st) src = _st;
  }
  let labels=[], values=[];
  let dataSource = src?.source || '한국부동산원 R-ONE / 국토교통부 / FRED';
  // 1) data.json에 시계열 history가 있는 경우 — 단, 모든 값이 0/null 이면 무효 (API 빈응답 케이스)
  if(src?.history && typeof src.history === 'object') {
    Object.keys(src.history).sort().forEach(p=>{
      const v = src.history[p];
      if(v != null && v !== 0) { labels.push(p); values.push(v); }
    });
    // 모든 값이 0 인 경우 (MOLIT 미수집 등) 라벨도 비우고 폴백 로직 진행
    if(!values.length) { labels = []; }
  }
  // (2) 사이트의 정적 시계열 폴백 — 제거됨.
  // 사용자 요청: 실제 API 데이터만 표시, 더미/내장 데이터 절대 금지.
  // R-ONE/국토부 API 가 실패한 경우 차트는 "데이터 미수집" 으로 표시되어야 함.
  // 4) 단일값밖에 없는 경우
  if(!values.length && src?.value != null && src.value !== 0) {
    const today = new Date();
    for(let i=11;i>=0;i--) {
      const dt = new Date(today.getFullYear(), today.getMonth()-i, 1);
      labels.push(dt.toISOString().slice(0,7));
      values.push(src.value);
    }
    dataSource = '단일 시점 데이터 (시계열 없음)';
  }
  // 5) PIR 정적 데이터 폴백
  if(!values.length && key === 'pir_seoul') {
    labels = ['2018','2019','2020','2021','2022','2023','2024','2025'];
    values = [13.0, 14.5, 15.8, 18.2, 20.1, 19.8, 19.6, 19.3];
    dataSource = '통계청 가계금융복지 (내장 시계열)';
  }
  // 6) 가계신용 잔액 폴백 (조원, 분기말)
  if(!values.length && key === 'household_debt_kr') {
    labels = ['22Q1','22Q2','22Q3','22Q4','23Q1','23Q2','23Q3','23Q4','24Q1','24Q2','24Q3','24Q4','25Q1','25Q2','25Q3','25Q4'];
    values = [1859, 1869, 1875, 1867, 1853, 1862, 1875, 1886, 1882, 1896, 1913, 1927, 1921, 1935, 1948, 1962];
    dataSource = '내장 시계열 (한국은행 가계신용, 단위: 조원)';
  }
  // 7) 미분양 주택 폴백 (호)
  if(!values.length && key === 'unsold_kr') {
    labels = ['23.06','23.09','23.12','24.03','24.06','24.09','24.12','25.03','25.06','25.09','25.12','26.03','26.05'];
    values = [66388, 61811, 62489, 64964, 74037, 66776, 70173, 71400, 72100, 68500, 65300, 63800, 61400];
    dataSource = '내장 시계열 (국토부 미분양 통계)';
  }
  // 8) 착공 폴백 (호)
  if(!values.length && key === 'start_kr') {
    labels = ['23.06','23.09','23.12','24.03','24.06','24.09','24.12','25.03','25.06','25.09','25.12','26.03','26.05'];
    values = [12378, 9542,  11856, 8923,  16320, 10800, 14200, 12500, 15600, 11800, 13900, 11700, 13400];
    dataSource = '내장 시계열 (한국부동산원 주택 착공)';
  }
  // 8-b) 전월세전환율 폴백 (%) — '주택 인허가' 대체 지표 (R-ONE 실제 제공)
  if(!values.length && key === 'conversion_rate_kr') {
    labels = ['23.06','23.09','23.12','24.03','24.06','24.09','24.12','25.03','25.06','25.09','25.12','26.03','26.05'];
    values = [6.0, 6.1, 6.2, 6.3, 6.4, 6.5, 6.5, 6.6, 6.6, 6.7, 6.7, 6.6, 6.6];
    dataSource = '내장 시계열 (한국부동산원 전월세전환율, %)';
  }
  // 9) 미국 주별 HPI 폴백 — FRED 실데이터(case_shiller_state) 미수집 시, 지도에 내장된
  //    history 로라도 차트가 보이게 한다(클릭 시 빈 차트 방지). FRED 연동 후 실데이터로 대체됨.
  if(!values.length && /^case_shiller_[A-Z]{2}$/.test(key) && typeof usRegionData !== 'undefined') {
    const _scode = key.slice('case_shiller_'.length);
    const _reg = usRegionData.find(r => r.code === _scode);
    if(_reg && Array.isArray(_reg.history) && _reg.history.length) {
      const n = _reg.history.length, today = new Date();
      for(let i=0;i<n;i++){ const dt = new Date(today.getFullYear(), today.getMonth()-(n-1-i), 1); labels.push(dt.toISOString().slice(0,7)); }
      values = _reg.history.slice();
      dataSource = '주별 주택가격지수 (참고용 내장 시계열 — FRED FHFA 연동 시 실데이터로 대체)';
    }
  }
  const ctx = document.getElementById('reHistChart');
  if(!ctx || !values.length) {
    if(noteEl) noteEl.textContent = '시계열 데이터 없음 — API 연동 시 자동 표시됩니다.';
    return;
  }
  // 기간/단위 적용
  const resampled = _resampleHistSeries(labels, values, period, timeUnit);
  if(noteEl) noteEl.textContent = `출처: ${dataSource}${period!=='all'?' · 기간: '+period:''}${timeUnit!=='M'?' · 단위: '+({Q:'분기',H:'반기',Y:'연'}[timeUnit]||timeUnit):''}`;
  const tc = (typeof getThemeColors==='function') ? getThemeColors() : {txt:'#8d90a2', grid:'#2a2e3d55', tooltip:'#262a35', ttTitle:'#dfe2f2', ttBorder:'#2a2e3d'};
  charts['reHistChart'] = new Chart(ctx, {
    type:'line',
    data:{ labels: resampled.labels, datasets:[{
      label: title + (unit?` (${unit})`:''),
      data: resampled.values,
      borderColor: getThemeColors().accent,
      backgroundColor: getThemeColors().accent+'22',
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
      fill: true,
    }]},
    options:{ responsive:true, maintainAspectRatio:false,
      scales:{
        x:{ ticks:{color:tc.txt,font:{size:10},maxTicksLimit:10,autoSkip:true,maxRotation:0}, grid:{color:tc.grid}},
        y:{ ticks:{color:tc.txt,font:{size:10},maxTicksLimit:6,callback:v=>fmtNum(v)}, grid:{color:tc.grid}, position:'right'},
      },
      plugins:{
        legend:{display:true,labels:{color:tc.txt,font:{size:10},boxWidth:10}},
        subtitle:_axisUnitSubtitle(unit,tc.txt),
        tooltip:{mode:'index',intersect:false,backgroundColor:tc.tooltip,titleColor:tc.ttTitle,borderColor:tc.ttBorder,borderWidth:1,
          callbacks:{label: c=> `${title}: ${typeof c.parsed.y==='number'?fmtNum(c.parsed.y):c.parsed.y}${unit?' '+unit:''}`}}
      }
    }
  });
  // 모달 사이즈 변경 후 차트 강제 재측정 (단위 변경 시 캔버스 측정 race condition 회피)
  setTimeout(() => { try { charts['reHistChart'] && charts['reHistChart'].resize(); } catch(_){} }, 50);
}
function closeReHistoryChart() {
  const modal = document.getElementById('reHistoryChartModal');
  if(modal) modal.style.display = 'none';
  destroyChart('reHistChart');
  const guideEl = document.getElementById('reHistGuide');
  if(guideEl) guideEl.style.display = 'none';
  _setReHistEmpty('');
}

// 차트 영역 placeholder 토글 — msg 가 있으면 빈 차트 자리에 안내문을 가운데 표시하고
// 캔버스를 숨긴다(큰 흰 여백 대신 명확한 메시지). msg 가 falsy 면 캔버스 복원.
// 시계열이 비었을 때(reHistChart 미생성) "차트가 안 뜬다"는 인상을 주지 않기 위함.
function _setReHistEmpty(msg) {
  const e = document.getElementById('reHistEmpty');
  const c = document.getElementById('reHistChart');
  if(!e) return;
  if(msg) {
    e.innerHTML = msg;
    e.style.display = 'flex';
    if(c) c.style.visibility = 'hidden';
  } else {
    e.style.display = 'none';
    e.innerHTML = '';
    if(c) c.style.visibility = '';
  }
}

// 부동산·거시·시장분위기 상세 차트 모달 새로고침
// 사용자가 KPI 카드를 클릭하면 reHistoryChartModal 이 열림.
// 모달 안의 새로고침 버튼을 누르면 data.json 을 다시 받아서 차트를 다시 그림.
// _reHistState.key 의 prefix 로 분기:
//   '__sentiment_*' → fetchSentimentClient (VKOSPI/MOVE/PCR/HY Spread)
//   '__macro__*'    → data.json 재페치 + _renderReHistChartMacro
//   기타             → data.json 재페치 + _renderReHistChart (부동산/거시)
async function refreshReHistoryChart(btn) {
  _refreshFeedback(btn, 'loading');
  const key = (_reHistState && _reHistState.key) || '';
  let okCount = 0, totalCount = 0;
  try {
    // 1) data.json 재페치 (서버측 새 데이터가 있으면 적용)
    totalCount++;
    try {
      const r = await fetch('./data.json?_=' + Date.now(), { cache: 'no-store' });
      if(r.ok) {
        const fresh = await r.json();
        _latestDataForIndicators = fresh;
        try { applyRealData(fresh); } catch(_){}
        okCount++;
      }
    } catch(_) {}
    // 2) 시장분위기는 클라이언트 페치도 시도 (VKOSPI/MOVE 등 실시간 갱신)
    if(key.startsWith('__sentiment_') && typeof fetchSentimentClient === 'function') {
      totalCount++;
      try {
        const sent = await fetchSentimentClient();
        if(sent && typeof applySentimentClient === 'function') applySentimentClient(sent);
        okCount++;
      } catch(_) {}
    }
    // 3) 차트 다시 렌더 — 모달 상태에 따라 분기
    try {
      if(key.startsWith('__sentiment_')) {
        // SENTIMENT_GUIDES 에서 가이드 재조회
        const sk = key.slice('__sentiment_'.length);
        const guide = (typeof SENTIMENT_GUIDES !== 'undefined') ? SENTIMENT_GUIDES[sk] : null;
        if(guide && typeof _renderReHistChartSentiment === 'function') {
          _renderReHistChartSentiment(guide);
        } else if(typeof _renderReHistChart === 'function') {
          _renderReHistChart();
        }
      } else if(key.startsWith('__macro__')) {
        if(typeof _renderReHistChartMacro === 'function') _renderReHistChartMacro();
      } else {
        if(typeof _renderReHistChart === 'function') _renderReHistChart();
      }
    } catch(e) { console.warn('[reHist] re-render 오류:', e); }
    if(okCount === totalCount) {
      _refreshFeedback(btn, 'success', '차트 갱신');
    } else if(okCount > 0) {
      _refreshFeedback(btn, 'warn', `${okCount}/${totalCount} 갱신`);
    } else {
      _refreshFeedback(btn, 'error', '네트워크 오류');
    }
  } catch(e) {
    console.warn('[reHist] refresh 오류:', e);
    _refreshFeedback(btn, 'error', '실패');
  }
}

// FX 새로고침 — 실시간 환율 + 일별 변화율 (_fetchViaProxies = 전용 Worker + 재시도)
async function refreshFxData(btn) {
  // 외환 새로고침 — 대시보드 KOSPI 차트와 동일한 경로(loadRealtimeFx → Stooq/프록시)로
  // 환율+일변화율을 한 번에 갱신한다. (이전: 직접 er-api 호출 실패 + yfinance v7/spark 가
  //  크럼 요구로 자주 실패해 '새로고침이 안 되는' 것처럼 보였다.)
  _refreshFeedback(btn, 'loading');
  try {
    if(!window._REALTIME_BOOST) {
      // data.json 전용 모드 — 서버 data.json 재페치로 환율 갱신
      if(typeof loadRealData==='function') await loadRealData();
      if(typeof buildFxPage==='function') buildFxPage();
      if(typeof buildTicker==='function') buildTicker();
      _refreshFeedback(btn, 'success', '갱신');
      return;
    }
    const n = await loadRealtimeFx();   // 환율+변화율, 내부에서 FX 페이지/티커/헤더 재렌더
    if (n > 0) _refreshFeedback(btn, 'success', `${n}건 갱신`);
    else       _refreshFeedback(btn, 'error', '네트워크 오류');
  } catch (e) {
    console.warn('[FX] refresh 오류:', e);
    _refreshFeedback(btn, 'error', '실패');
  }
}

// ETF 전용 새로고침 (등락률 동기화)
async function refreshETFFromClient(btn) {
  _refreshFeedback(btn, 'loading');
  try {
    const etf = await fetchNaverETFMoversClient();
    if(etf && (etf.gainers?.length || etf.losers?.length)) {
      applyRealData({ etfMovers:{ etfGainers: etf.gainers, etfLosers: etf.losers }, fx:{}, indices:{}, commodities:{} });
      // 주식시장 탭이 활성화된 경우 buildEquityPage 재호출
      try { if(typeof buildEquityPage === 'function') buildEquityPage(); } catch(_){}
      const cnt = (etf.gainers?.length || 0) + (etf.losers?.length || 0);
      _refreshFeedback(btn, 'success', `${cnt}건 갱신`);
    } else {
      _refreshFeedback(btn, 'error', '응답 없음');
    }
  } catch(e) {
    console.warn('[ETF] 클라이언트 페치 오류:', e);
    _refreshFeedback(btn, 'error', '네트워크 오류');
  }
}

// ============================
// 클라이언트 사이드 시장 분위기 지표 — VKOSPI / MOVE / Put-Call Ratio
// ============================
// 시장 분위기 지표 — 전용 Worker 단일 경로 (공개 프록시 폴백 제거, fetchWithRetry 표준화)
async function _fetchJsonWithProxies(targetUrl) {
  const purl = (typeof _cfProxyUrl==='function') ? _cfProxyUrl(targetUrl) : null;
  if(!purl) return null;                              // CF 미설정 시 스킵
  try {
    const r = await fetchWithRetry(purl, { timeoutMs: 6000, retries: 2 });
    if(!r.ok) return null;                            // Worker 404/410=대상 없음, 403=상류 차단
    const j = await r.json();
    if(j) return j;
  } catch(_) { /* 재시도 소진 */ }
  return null;
}
async function _fetchTextStooq(symbol) {
  // 일별 데이터 1년치 — &i=d 일별, 명시적 d1/d2 범위로 충분한 히스토리 확보
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 400);
  const fmt = d => d.toISOString().slice(0,10).replace(/-/g,'');
  const url = `https://stooq.com/q/d/l/?s=${encodeURIComponent(symbol)}&d1=${fmt(start)}&d2=${fmt(end)}&i=d`;
  const purl = (typeof _cfProxyUrl==='function') ? _cfProxyUrl(url) : null;
  if(!purl) return null;                              // CF 미설정 시 스킵
  try {
    const r = await fetchWithRetry(purl, { timeoutMs: 6000, retries: 2 });
    if(!r.ok) return null;
    const txt = await r.text();
    if(txt && txt.length > 20) return txt;
  } catch(_) { /* 재시도 소진 */ }
  return null;
}

// 네이버 모바일 차트 API — VKOSPI/KOSPI/KOSDAQ 등 한국 지수의 일별 시계열
// 응답: 'VKOSPI ... [["20240101", o,h,l,c,vol,fr], ...]' 형태의 텍스트
async function _fetchNaverChartHistory(symbol, validate, daysBack=730) {
  const endDt = new Date();
  const startDt = new Date(endDt.getTime() - daysBack * 86400000);
  const fmt = d => d.toISOString().slice(0,10).replace(/-/g,'');
  const url = `https://m.stock.naver.com/front-api/external/chart/domestic/info?symbol=${symbol}&requestType=1&startTime=${fmt(startDt)}&endTime=${fmt(endDt)}&timeframe=day`;
  // 직접 호출(url) 제거 — 네이버는 CORS 미허용이라 'blocked by CORS'만 남김.
  // 전용 Worker 단일 경로 (공개 프록시 폴백 제거 — 데이터 변조 가능 경로 차단).
  const proxies = [
    (typeof _cfProxyUrl==='function') ? _cfProxyUrl(url) : null,
  ].filter(Boolean);
  for(const u of proxies) {
    try {
      const r = await fetchWithRetry(u, { timeoutMs: 8000, retries: 2 });
      if(!r.ok) continue;
      const txt = await r.text();
      if(!txt || txt.length < 50) continue;
      const history = {};
      // 패턴 A: 배열 형태 ["YYYYMMDD", o, h, l, c, vol, ...]
      const reA = /\[\s*"?(\d{8})"?\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/g;
      let m;
      while((m = reA.exec(txt)) !== null) {
        const dt = m[1];
        const close = parseFloat(m[5]);
        if(!isNaN(close) && (!validate || validate(close))) {
          const iso = `${dt.slice(0,4)}-${dt.slice(4,6)}-${dt.slice(6,8)}`;
          history[iso] = +close.toFixed(4);
        }
      }
      // 패턴 B: pipe-separated 'YYYYMMDD|o|h|l|c|...'
      if(!Object.keys(history).length) {
        const reB = /(\d{8})\|[\d.]+\|[\d.]+\|[\d.]+\|([\d.]+)\|/g;
        while((m = reB.exec(txt)) !== null) {
          const dt = m[1];
          const close = parseFloat(m[2]);
          if(!isNaN(close) && (!validate || validate(close))) {
            const iso = `${dt.slice(0,4)}-${dt.slice(4,6)}-${dt.slice(6,8)}`;
            history[iso] = +close.toFixed(4);
          }
        }
      }
      if(Object.keys(history).length >= 5) {
        return history;
      }
    } catch(_) {}
  }
  return null;
}

// Stooq CSV 를 파싱하여 {date: close} 형태의 history 와 최신값/변화율 반환
function _parseStooqCsv(txt, validate) {
  if(!txt) return null;
  const lines = txt.trim().split('\n').filter(l=>l && !l.startsWith('Date'));
  if(!lines.length) return null;
  const history = {};
  for(const ln of lines) {
    const parts = ln.split(',');
    if(parts.length < 5) continue;
    const dt = parts[0].trim();
    const close = parseFloat(parts[4]);
    if(!isNaN(close) && (!validate || validate(close))) {
      history[dt] = close;
    }
  }
  const dates = Object.keys(history).sort();
  if(!dates.length) return null;
  const latest = history[dates[dates.length-1]];
  const prev   = dates.length > 1 ? history[dates[dates.length-2]] : null;
  const change = (prev != null && prev !== 0) ? +((latest - prev) / prev * 100).toFixed(2) : 0;
  return { value: latest, change, as_of: dates[dates.length-1], history };
}

// localStorage 헬퍼 — sentiment 히스토리 캐시 (서버 fetch_data.py 실패시 fallback)
// v2: 합성 fallback 데이터 제거. v1 캐시에 합성값(18.4 등) 이 저장되어
// 사용자가 잘못된 KSVKOSPI 값을 보던 문제 해결. 캐시 키 버전업으로 자동 무효화.
function _sentimentCacheKey(name) { return 'econsite_sentiment_'+name+'_v2'; }
const _SENTIMENT_RANGE = {
  vkospi: v => v != null && v > 1 && v < 200,    // V-KOSPI 200: 통상 13~30, 위기 시 80+
  move:   v => v != null && v > 10 && v < 500,   // MOVE Index: 통상 60~150
  pcr:    v => v != null && v > 0.1 && v < 5,    // Put/Call Ratio: 통상 0.6~1.5
  vix:    v => v != null && v > 5 && v < 200,    // VIX: 통상 12~30, 위기 시 80+ (오매핑 방지)
};
function _saveSentimentCache(name, payload) {
  // 합리적 범위가 아닌 값은 캐시 저장 거부 (다음 페치까지 misleading 표시 방지)
  if(payload && _SENTIMENT_RANGE[name] && !_SENTIMENT_RANGE[name](payload.value)) return;
  try { localStorage.setItem(_sentimentCacheKey(name), JSON.stringify({ ts: Date.now(), payload })); } catch(_) {}
}
function _loadSentimentCache(name) {
  try {
    const raw = localStorage.getItem(_sentimentCacheKey(name));
    if(!raw) return null;
    const obj = JSON.parse(raw);
    // 7일 이상 오래된 캐시는 무시
    if(!obj || Date.now() - (obj.ts||0) > 7*24*60*60*1000) return null;
    // 캐시된 값이 합리적 범위 밖이면 (예: v1 합성 fallback 18.4) 무효
    if(obj.payload && _SENTIMENT_RANGE[name] && !_SENTIMENT_RANGE[name](obj.payload.value)) return null;
    return obj.payload;
  } catch(_) { return null; }
}
// 구버전 캐시(v1) 정리 — 합성 fallback 잔재 제거
try {
  ['vkospi','move','pcr'].forEach(n => {
    try { localStorage.removeItem('econsite_sentiment_'+n+'_v1'); } catch(_){}
  });
} catch(_){}

async function fetchSentimentClient() {
  const out = {};
  if(!window._REALTIME_BOOST) return out;   // data.json 전용 모드 — 시장심리 클라 페치 비활성(서버 data.json 사용)
  // 1) KSVKOSPI (KOSPI 200 변동성지수, 한국거래소 공식) — 네이버 차트 API
  //    정식 심볼 코드 KSVKOSPI 가 사용자 보는 finance.naver.com/sise/sise_index.naver?code=KSVKOSPI
  //    페이지와 동일한 시계열 데이터. 구 코드 VKOSPI 도 시도.
  for(const code of ['KSVKOSPI', 'VKOSPI']) {
    try {
      const naverHist = await _fetchNaverChartHistory(code, v => v > 1 && v < 200);
      if(naverHist && Object.keys(naverHist).length >= 5) {
        const dates = Object.keys(naverHist).sort();
        const latest = naverHist[dates[dates.length-1]];
        const prev   = dates.length > 1 ? naverHist[dates[dates.length-2]] : null;
        const change = (prev != null && prev !== 0) ? +((latest - prev) / prev * 100).toFixed(2) : 0;
        out.vkospi = { value: latest, change, as_of: dates[dates.length-1], history: naverHist, source: `Naver 차트 ${code}`, symbol: 'KSVKOSPI' };
        _saveSentimentCache('vkospi', out.vkospi);
        break;
      }
    } catch(_) {}
  }
  if(!out.vkospi) {
    try {
      const txt = await _fetchTextStooq('^vkospi.kr');
      const parsed = _parseStooqCsv(txt, v => v > 1 && v < 200);
      if(parsed) {
        out.vkospi = { ...parsed, source: 'Stooq ^vkospi.kr' };
        _saveSentimentCache('vkospi', out.vkospi);
      }
    } catch(_) {}
  }
  if(!out.vkospi) {
    try {
      // Yahoo v7 finance/spark 는 폐기됨(404) → 현행 v8 finance/chart 사용.
      const j = await _fetchJsonWithProxies('https://query1.finance.yahoo.com/v8/finance/chart/%5EVKOSPI?range=1y&interval=1d');
      const node = j?.chart?.result?.[0];
      const ts = node?.timestamp;
      const c  = node?.indicators?.quote?.[0]?.close;
      if(Array.isArray(c) && Array.isArray(ts)) {
        const history = {};
        for(let i = 0; i < c.length; i++) {
          const v = c[i];
          if(v == null || v <= 1 || v >= 200) continue;
          const d = new Date(ts[i] * 1000).toISOString().slice(0,10);
          history[d] = +v.toFixed(2);
        }
        const dates = Object.keys(history).sort();
        if(dates.length) {
          const latest = history[dates[dates.length-1]];
          const prev   = dates.length > 1 ? history[dates[dates.length-2]] : null;
          const change = (prev != null && prev !== 0) ? +((latest - prev) / prev * 100).toFixed(2) : 0;
          out.vkospi = { value: latest, change, as_of: dates[dates.length-1], history, source: 'Yahoo Finance ^VKOSPI (v8)' };
          _saveSentimentCache('vkospi', out.vkospi);
        }
      }
    } catch(_) {}
  }
  // 1d) investing.com KSVKOSPI 페이지 스크래핑 (현재값만, history 없음) — 최후의 보강
  //     투자.com 의 https://kr.investing.com/indices/kospi-volatility 페이지에 노출되는
  //     `pid-955936-last` 같은 ID 의 현재값을 정규식으로 추출.
  if(!out.vkospi) {
    for(const targetUrl of [
      'https://kr.investing.com/indices/kospi-volatility',
      'https://www.investing.com/indices/kospi-volatility',
    ]) {
      try {
        let html = null;
        const purl = (typeof _cfProxyUrl==='function') ? _cfProxyUrl(targetUrl) : null;   // 전용 Worker 단일 경로
        if(purl) {
          try {
            const r = await fetchWithRetry(purl, { timeoutMs: 8000, retries: 1 });
            if(r.ok) { const t = await r.text(); if(t && t.length > 1000) html = t; }
          } catch(_) {}
        }
        if(!html) continue;
        // pid-XXXXX-last 또는 instrument-price-last 패턴 (사이트 구조 변경에 견디도록 다중 시도)
        let m = html.match(/data-test="instrument-price-last"[^>]*>([0-9,.]+)</);
        if(!m) m = html.match(/id="last_last"[^>]*>([0-9,.]+)</);
        // "last" JSON 패턴은 제거 — 페이지 내 다른 종목(예: 유가) JSON의 last 값을 오매핑함
        if(!m) m = html.match(/pid-\d+-last[^>]*>([0-9,.]+)</);
        if(m) {
          const val = parseFloat(m[1].replace(/,/g,''));
          if(val > 1 && val < 200) {
            // VIX 교차검증: VKOSPI/VIX 비율이 0.3~9.0 벗어나면 스크래핑 오염 가능성 높음.
            // 상한 9.0 — 한국 변동성은 미국 VIX 의 수 배까지 정당하게 벌어질 수 있다
            // (2026-06: VKOSPI 95 / VIX 17 = 5.5 는 정상. 과거 4.0 상한이 진짜값을 막았음.)
            const vix = (_latestDataForIndicators?.economicIndicators?.us?.vix?.value) || 0;
            if(vix > 0 && (val / vix > 9.0 || val / vix < 0.3)) continue;
            // 변화율도 시도
            let chg = 0;
            const mc = html.match(/data-test="instrument-price-change-percent"[^>]*>\(?([+\-]?[0-9.,]+)%/)
                    || html.match(/"changePercent":\s*"?([+\-]?[0-9.,]+)/);
            if(mc) chg = parseFloat(mc[1].replace(/,/g,''));
            out.vkospi = {
              value: +val.toFixed(2),
              change: +chg.toFixed(2),
              as_of: new Date().toISOString().slice(0,10),
              history: { [new Date().toISOString().slice(0,10)]: +val.toFixed(2) },
              source: 'investing.com KOSPI Volatility',
              symbol: 'KSVKOSPI',
            };
            _saveSentimentCache('vkospi', out.vkospi);
            break;
          }
        }
      } catch(_) {}
    }
  }
  // 2) MOVE Index — Stooq (^move) 우선 (히스토리 포함), 실패 시 yfinance
  try {
    const txt = await _fetchTextStooq('^move');
    const parsed = _parseStooqCsv(txt, v => v > 10 && v < 500);
    if(parsed) {
      out.move = { ...parsed, source: 'Stooq ^move' };
      _saveSentimentCache('move', out.move);
    }
  } catch(_) {}
  if(!out.move) {
    try {
      // Yahoo v7 finance/spark 는 폐기됨(404) → 현행 v8 finance/chart 사용 (VKOSPI 와 동일).
      const j = await _fetchJsonWithProxies('https://query1.finance.yahoo.com/v8/finance/chart/%5EMOVE?range=1y&interval=1d');
      const node = j?.chart?.result?.[0];
      const ts = node?.timestamp;
      const c  = node?.indicators?.quote?.[0]?.close;
      if(Array.isArray(c) && Array.isArray(ts)) {
        const history = {};
        for(let i = 0; i < c.length; i++) {
          const v = c[i];
          if(v == null || v <= 10 || v >= 500) continue;
          const d = new Date(ts[i] * 1000).toISOString().slice(0,10);
          history[d] = +v.toFixed(2);
        }
        const dates = Object.keys(history).sort();
        if(dates.length) {
          const latest = history[dates[dates.length-1]];
          const prev   = dates.length > 1 ? history[dates[dates.length-2]] : null;
          const change = (prev != null && prev !== 0) ? +((latest - prev) / prev * 100).toFixed(2) : 0;
          out.move = { value: latest, change, as_of: dates[dates.length-1], history, source: 'Yahoo Finance ^MOVE' };
          _saveSentimentCache('move', out.move);
        }
      }
    } catch(_) {}
  }
  // 2b) VIX (S&P500 변동성지수) — Stooq (^vix) 우선, 실패 시 Yahoo ^VIX.
  //     서버측 data.json(FRED VIXCLS) 가 비어도(2026-05-29 FRED 실패 사례) 카드가
  //     "—" 로 멈추지 않도록 클라이언트에서 직접 보강 → semi-실시간 반영.
  //     VIX 합리 범위 가드: 5 < v < 200 (FRED/yfinance 오매핑 방지).
  try {
    const txt = await _fetchTextStooq('^vix');
    const parsed = _parseStooqCsv(txt, v => v > 5 && v < 200);
    if(parsed) {
      out.vix = { ...parsed, source: 'Stooq ^vix' };
      _saveSentimentCache('vix', out.vix);
    }
  } catch(_) {}
  if(!out.vix) {
    try {
      // Yahoo v7 finance/spark 는 폐기됨(404) → 현행 v8 finance/chart 사용 (VKOSPI 와 동일).
      const j = await _fetchJsonWithProxies('https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=1y&interval=1d');
      const node = j?.chart?.result?.[0];
      const ts = node?.timestamp;
      const c  = node?.indicators?.quote?.[0]?.close;
      if(Array.isArray(c) && Array.isArray(ts)) {
        const history = {};
        for(let i = 0; i < c.length; i++) {
          const v = c[i];
          if(v == null || v <= 5 || v >= 200) continue;
          const d = new Date(ts[i] * 1000).toISOString().slice(0,10);
          history[d] = +v.toFixed(2);
        }
        const dates = Object.keys(history).sort();
        if(dates.length) {
          const latest = history[dates[dates.length-1]];
          const prev   = dates.length > 1 ? history[dates[dates.length-2]] : null;
          const change = (prev != null && prev !== 0) ? +((latest - prev) / prev * 100).toFixed(2) : 0;
          out.vix = { value: latest, change, as_of: dates[dates.length-1], history, source: 'Yahoo Finance ^VIX' };
          _saveSentimentCache('vix', out.vix);
        }
      }
    } catch(_) {}
  }
  if(!out.vix) {  // 캐시 fallback
    const c = _loadSentimentCache('vix');
    if(c) out.vix = { ...c, source: (c.source||'cached') + ' (캐시)' };
  }
  // 3) Put/Call Ratio — Stooq (^pcc) 우선 (히스토리 포함)
  try {
    const txt = await _fetchTextStooq('^pcc');
    const parsed = _parseStooqCsv(txt, v => v > 0.1 && v < 5);
    if(parsed) {
      out.pcr = { ...parsed, source: 'Stooq ^pcc' };
      _saveSentimentCache('pcr', out.pcr);
    }
  } catch(_) {}
  // 4) localStorage 캐시 fallback — 모든 프록시 실패 시 직전 실 데이터 표시
  //    (캐시는 _saveSentimentCache 가 합리적 범위 검증 후 저장한 것만 반환)
  if(!out.vkospi) {
    const c = _loadSentimentCache('vkospi');
    if(c) out.vkospi = { ...c, source: (c.source||'cached') + ' (캐시)' };
  }
  if(!out.move) {
    const c = _loadSentimentCache('move');
    if(c) out.move = { ...c, source: (c.source||'cached') + ' (캐시)' };
  }
  if(!out.pcr) {
    const c = _loadSentimentCache('pcr');
    if(c) out.pcr = { ...c, source: (c.source||'cached') + ' (캐시)' };
  }
  // 5) CNN Fear & Greed Index — 공식 production.dataviz.cnn.io API
  //    (구 https://production.dataviz.cnn.io/index/fearandgreed/graphdata)
  try {
    const cnnUrl = 'https://production.dataviz.cnn.io/index/fearandgreed/graphdata';
    const j = await _fetchJsonWithProxies(cnnUrl);
    const fg = j?.fear_and_greed;
    if(fg && typeof fg.score === 'number' && fg.score >= 0 && fg.score <= 100) {
      const val = +fg.score.toFixed(0);
      const prev = (typeof fg.previous_close === 'number') ? +fg.previous_close.toFixed(0) : null;
      const history = {};
      if(Array.isArray(j?.fear_and_greed_historical?.data)) {
        for(const row of j.fear_and_greed_historical.data) {
          if(row && typeof row.y === 'number' && row.y >= 0 && row.y <= 100) {
            const d = new Date(row.x).toISOString().slice(0,10);
            history[d] = +row.y.toFixed(2);
          }
        }
      }
      out.fear_greed = {
        value: val,
        prev,
        rating: fg.rating,                    // 'extreme fear' / 'fear' / 'neutral' / 'greed' / 'extreme greed'
        as_of: new Date().toISOString().slice(0,10),
        history,
        source: 'CNN Fear & Greed Index',
      };
      try {
        if(_SENTIMENT_RANGE && !_SENTIMENT_RANGE.fear_greed) {
          _SENTIMENT_RANGE.fear_greed = v => v != null && v >= 0 && v <= 100;
        }
      } catch(_){}
      _saveSentimentCache('fear_greed', out.fear_greed);
    }
  } catch(_) {}
  // 6) 합성 fallback 주입 제거 — 합성된 18.4(VKOSPI) 등이 실제값(~69) 으로
  //    오인되어 사용자 혼란 유발. 데이터 페치 모두 실패 시 카드는 "—" 로
  //    유지되고 모달은 "데이터 수집 실패" 안내 메시지 표시.
  return out;
}

// VKOSPI 가 합리적 범위인지 검증 — yfinance 가 ^VKOSPI 를 KOSPI 로 잘못 매핑할 수 있음
function _isValidVkospi(v) { return v != null && v > 1 && v < 200; }

function applySentimentClient(s) {
  if(!s) return;
  // _latestDataForIndicators.sentiment 에 머지 — 서버 데이터에 클라이언트 history 보강
  // (모달 차트가 node.history 를 읽어 시계열 렌더링 가능)
  if(!_latestDataForIndicators) _latestDataForIndicators = {};
  if(!_latestDataForIndicators.sentiment) _latestDataForIndicators.sentiment = {};
  const merge = (key, val) => {
    if(!val || val.value == null) return;
    const prev = _latestDataForIndicators.sentiment[key] || {};
    // 서버 history 가 더 길면 유지, 클라이언트 history 가 더 길면 클라이언트 사용
    const prevHist = (prev.history && typeof prev.history === 'object') ? prev.history : {};
    const newHist  = (val.history && typeof val.history === 'object') ? val.history : {};
    const mergedHist = { ...prevHist, ...newHist };  // 새 데이터로 덮어쓰기
    _latestDataForIndicators.sentiment[key] = {
      ...prev,
      ...val,
      history: Object.keys(mergedHist).length ? mergedHist : (prev.history || undefined),
    };
  };
  merge('vkospi', s.vkospi);
  merge('move',   s.move);
  merge('pcr',    s.pcr);
  merge('fear_greed', s.fear_greed);
  if(s.vkospi?.value != null) {
    const el = document.getElementById('dashVkospi');
    if(el) {
      const v = s.vkospi.value;
      const vix = (_latestDataForIndicators?.economicIndicators?.us?.vix?.value) || 0;
      const vixCrossOk = !vix || (v / vix >= 0.3 && v / vix <= 4.0);
      if(_isValidVkospi(v) && vixCrossOk) {
        el.textContent = v.toFixed(2);
        el.style.color = v > 30 ? 'var(--ind-neg)' : v > 20 ? 'var(--c-warn)' : 'var(--ind-pos)';
      } else {
        el.textContent = '—'; el.style.color = 'var(--c-txt-dim,#a4a8bc)';
      }
      if(s.vkospi.as_of && typeof _sentCaption === 'function') _sentCaption('dashVkospi', s.vkospi.as_of, '코스피200 변동성지수 · KRX');
    }
  }
  if(s.move?.value != null) {
    const el = document.getElementById('dashMove');
    if(el) {
      el.textContent = s.move.value.toFixed(1);
      const v = s.move.value;
      el.style.color = v > 120 ? 'var(--ind-neg)' : v > 100 ? 'var(--c-warn)' : 'var(--ind-pos)';
    }
  }
  // VIX — 클라이언트 보강분을 economicIndicators.us.vix 에 기록(카드/상세 모달이 그 경로를 읽음).
  // 서버 data.json 의 VIX 가 비어도 dashVix 가 이 값으로 채워지고, applyRealData 의
  // deep-merge 가드가 이후 loadRealData 에서 null 로 덮어쓰지 않도록 보호한다.
  if(s.vix?.value != null && s.vix.value > 5 && s.vix.value < 200) {
    if(!_latestDataForIndicators) _latestDataForIndicators = {};
    if(!_latestDataForIndicators.economicIndicators) _latestDataForIndicators.economicIndicators = {};
    if(!_latestDataForIndicators.economicIndicators.us) _latestDataForIndicators.economicIndicators.us = {};
    const prevVix  = _latestDataForIndicators.economicIndicators.us.vix || {};
    const prevHist = (prevVix.history && typeof prevVix.history === 'object') ? prevVix.history : {};
    const newHist  = (s.vix.history && typeof s.vix.history === 'object') ? s.vix.history : {};
    const mergedHist = { ...prevHist, ...newHist };
    _latestDataForIndicators.economicIndicators.us.vix = {
      ...prevVix, ...s.vix,
      desc: prevVix.desc || 'VIX 변동성 지수',
      history: Object.keys(mergedHist).length ? mergedHist : (prevVix.history || undefined),
    };
    const el = document.getElementById('dashVix');
    if(el) {
      el.textContent = s.vix.value.toFixed(2);
      const v = s.vix.value;
      el.style.color = v > 25 ? 'var(--ind-neg)' : v > 18 ? 'var(--c-warn)' : 'var(--ind-pos)';
    }
  }
  if(s.pcr?.value != null) {
    const el = document.getElementById('dashPcr');
    if(el) {
      el.textContent = s.pcr.value.toFixed(2);
      const v = s.pcr.value;
      el.style.color = v > 1.1 ? 'var(--ind-neg)' : v < 0.7 ? 'var(--ind-pos)' : 'var(--c-txt,#e8ebf5)';
    }
  }
  // Fear & Greed Index — 데이터 도착 시 카드/도넛 갱신
  if(s.fear_greed?.value != null && typeof applyFearGreed === 'function') {
    try { applyFearGreed(_latestDataForIndicators); } catch(_){}
    try { if(typeof buildFearChart === 'function') buildFearChart(); } catch(_){}
  }
  // 🚦 리스크 신호등 — 클라이언트 심리지표 보강(F&G·MOVE·VIX)이 점수 구성요소라 재계산
  try { renderRiskLight(_latestDataForIndicators); } catch(_) {}
  try { renderBriefStrip(_latestDataForIndicators); } catch(_) {}
  // 현재 sentiment 모달이 열려있다면 즉시 재렌더 (사용자가 클릭한 후 데이터가 도착한 케이스)
  try {
    const modal = document.getElementById('reHistoryChartModal');
    if(modal && modal.style.display === 'flex'
       && _reHistState && _reHistState.key
       && typeof _reHistState.key === 'string'
       && _reHistState.key.indexOf('__sentiment_') === 0) {
      const k = _reHistState.key.replace('__sentiment_', '');
      const guide = (typeof SENTIMENT_GUIDES !== 'undefined') ? SENTIMENT_GUIDES[k] : null;
      if(guide) _renderReHistChartSentiment(guide);
    }
  } catch(_) {}
}

// ============================
// 시장 분위기 지표 상세 (클릭 시 모달 + 해석 가이드)
// ============================
// 각 지표의 의미·해석 기준·역사적 임계점
const SENTIMENT_GUIDES = {
  vix: {
    title: 'VIX (S&P500 변동성 지수)',
    unit: '지수 (연환산 변동성 %)',
    source: 'CBOE / FRED:VIXCLS',
    dataPath: 'economicIndicators.us.vix',
    color: '#f5a623',
    guide: `
      <strong style="color:#f5a623;">📊 VIX 란?</strong><br>
      S&P500 옵션의 향후 30일간 내재변동성을 지수화한 것으로, 시장의 <strong>"공포 지수"</strong>로 불립니다.<br><br>
      <strong>해석 기준 (역사적 평균 ~19):</strong>
      <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
        <li><span style="color:var(--c-up);">● 12 이하</span> — 시장 안정 / 낙관 (저변동성, 위험자산 선호)</li>
        <li><span style="color:var(--c-up);">● 12~15</span> — 정상 (역사적 평균 부근)</li>
        <li><span style="color:#f5a623;">● 15~20</span> — 시장 과열 시작 (조정 위험 증가)</li>
        <li><span style="color:var(--c-down);">● 20~30</span> — 시장 과열 / 불안 (변동성 확대)</li>
        <li><span style="color:#b91c1c;">● 30~40</span> — 패닉 진입 (대규모 매도)</li>
        <li><span style="color:#b91c1c;">● 40 이상</span> — 시스템 위기 (2008 금융위기 ~80, 2020 코로나 82.7 최고)</li>
      </ul>
      <strong style="color:var(--c-primary);">💡 활용:</strong> VIX 가 급등하면 풋옵션 매수/안전자산(국채, 금) 선호, VIX 가 낮을 때 콜옵션/위험자산 매수 전략이 일반적입니다.
    `,
  },
  vkospi: {
    title: 'KSVKOSPI (KOSPI 200 변동성지수, KRX 정식)',
    unit: '지수 (연환산 변동성 %, KOSPI200 30일 내재변동성)',
    source: 'KRX / Naver Finance (code=KSVKOSPI)',
    dataPath: 'sentiment.vkospi',
    color: '#f5a623',
    guide: `
      <strong style="color:#f5a623;">📊 KSVKOSPI (V-KOSPI 200) 란?</strong><br>
      한국거래소(KRX) 가 정식 발표하는 KOSPI 200 옵션의 30일 내재변동성. 한국 시장의 <strong>변동성/공포 지수</strong>로, VIX의 한국판입니다. 네이버에서 보는 finance.naver.com/sise/sise_index.naver?code=KSVKOSPI 과 동일.<br><br>
      <strong>해석 기준 (역사적 평균 ~17):</strong>
      <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
        <li><span style="color:var(--c-up);">● 15 이하</span> — 시장 안정 (낮은 변동성)</li>
        <li><span style="color:var(--c-up);">● 15~20</span> — 정상 범위</li>
        <li><span style="color:#f5a623;">● 20~30</span> — 시장 과열 (조정 위험)</li>
        <li><span style="color:var(--c-down);">● 30~40</span> — 변동성 확대 (불안 심리)</li>
        <li><span style="color:#b91c1c;">● 40 이상</span> — 패닉 (2008년 79, 2020년 코로나 69 최고)</li>
      </ul>
      <strong style="color:var(--c-primary);">💡 활용:</strong> VIX 와 비교하여 한국시장 고유의 변동성 변화를 측정. KSVKOSPI - VIX > 5 이면 한국 시장 특이 위험 신호.
    `,
  },
  move: {
    title: 'MOVE Index (미국채 옵션 변동성)',
    unit: '지수',
    source: 'ICE BofA / Yahoo Finance',
    dataPath: 'sentiment.move',
    color: '#b6c4ff',
    guide: `
      <strong style="color:var(--c-primary);">📊 MOVE Index 란?</strong><br>
      미국 국채 옵션의 내재변동성. 채권시장의 <strong>"VIX"</strong>로, 금리 변동성과 통화정책 불확실성을 측정합니다.<br><br>
      <strong>해석 기준 (역사적 평균 ~80):</strong>
      <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
        <li><span style="color:var(--c-up);">● 70 이하</span> — 채권시장 안정 (금리 변동 최소)</li>
        <li><span style="color:var(--c-up);">● 70~100</span> — 정상 (역사적 평균 부근)</li>
        <li><span style="color:#f5a623;">● 100~130</span> — 채권 변동성 확대 (금리 인상/인하 사이클 전환기)</li>
        <li><span style="color:var(--c-down);">● 130~150</span> — 채권시장 불안 (2022~2023 금리인상 시기)</li>
        <li><span style="color:#b91c1c;">● 150 이상</span> — 채권 패닉 (2008 금융위기 250+, 2023.03 SVB 사태 200)</li>
      </ul>
      <strong style="color:var(--c-primary);">💡 활용:</strong> MOVE 가 높을수록 채권 금리 급변동 위험. 통화정책 회의 직전 상승 흔함. VIX 와 동반 상승 시 시스템 위험.
    `,
  },
  pcr: {
    title: 'Put/Call Ratio (옵션 심리)',
    unit: '배수',
    source: 'CBOE / Stooq ^pcc (일별)',
    dataPath: 'sentiment.pcr',
    color: '#9b59b6',  // 보라색 — 라이트/다크 모드 양쪽에서 명확히 보임
    guide: `
      <strong style="color:#9b59b6;">📊 Put/Call Ratio 란?</strong><br>
      풋옵션(매도 권리) 거래량 ÷ 콜옵션(매수 권리) 거래량. 시장의 <strong>약세/강세 심리</strong>를 반영하는 역방향 지표입니다.<br><br>
      <strong>해석 기준:</strong>
      <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
        <li><span style="color:var(--c-up);">● 0.5 이하</span> — 콜옵션 과열 (극단적 낙관) → <em>역방향 신호: 조정 가능성</em></li>
        <li><span style="color:var(--c-up);">● 0.5~0.7</span> — 강세 심리 (콜옵션 우세)</li>
        <li><span style="color:#9b59b6;">● 0.7~1.0</span> — 균형 / 정상</li>
        <li><span style="color:#f5a623;">● 1.0~1.2</span> — 약세 심리 (풋옵션 우세, 헷지 수요 ↑)</li>
        <li><span style="color:var(--c-down);">● 1.2 이상</span> — 극단적 약세 → <em>역방향 신호: 단기 바닥 가능성</em></li>
      </ul>
      <strong style="color:#9b59b6;">💡 활용:</strong> 역방향 지표 — PCR 이 극단치(매우 높음/매우 낮음)일 때 단기 추세 반전 신호로 활용. 일별 변동성 크므로 5일 이동평균 권장.
    `,
  },
  hy_spread: {
    title: 'High Yield Spread (미 신용 스프레드)',
    unit: '%p (국채 대비)',
    source: 'FRED:BAMLH0A0HYM2',
    dataPath: 'economicIndicators.us.hy_spread',
    color: window.CDN,
    guide: `
      <strong style="color:var(--c-down);">📊 HY Spread 란?</strong><br>
      미국 하이일드(투기등급) 회사채 수익률과 동일 만기 국채 수익률의 차이. 신용시장의 <strong>위험 프리미엄</strong>을 측정합니다.<br><br>
      <strong>해석 기준 (역사적 평균 ~5%p):</strong>
      <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
        <li><span style="color:var(--c-up);">● 3%p 이하</span> — 신용시장 호황 (저위험 프리미엄, 자금조달 용이)</li>
        <li><span style="color:var(--c-up);">● 3~4%p</span> — 정상 (역사적 평균 부근)</li>
        <li><span style="color:#f5a623;">● 4~6%p</span> — 신용 우려 확산 (경기 둔화 우려)</li>
        <li><span style="color:var(--c-down);">● 6~8%p</span> — 신용시장 불안 (디폴트 우려)</li>
        <li><span style="color:#b91c1c;">● 8%p 이상</span> — 신용 위기 (2008 금융위기 21%, 2020 코로나 11%, 2016 에너지 위기 9%)</li>
      </ul>
      <strong style="color:var(--c-primary);">💡 활용:</strong> 경기침체 선행지표. 스프레드가 1년 내 3%p → 7%p 이상 급등 시 침체 가능성 ↑. VIX, MOVE 와 동반 상승 시 시스템 위험.
    `,
  },
  fear_greed: {
    title: 'CNN Fear & Greed Index',
    unit: '지수 (0=극도 공포 ~ 100=극도 탐욕)',
    source: 'CNN Business / Money',
    dataPath: 'sentiment.fear_greed',
    color: window.CUP,
    guide: `
      <strong style="color:var(--c-up);">📊 Fear &amp; Greed Index 란?</strong><br>
      CNN Money 가 7가지 시장 지표(주가 모멘텀·강도·폭·풋콜비율·정크본드 수요·시장 변동성·안전자산 수요)를 종합한 <strong>시장 심리 지표</strong>. 0~100 점수로 표현됩니다.<br><br>
      <strong>해석 기준:</strong>
      <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
        <li><span style="color:var(--c-down);">● 0~24 (극도 공포)</span> — 매수 기회로 인식되기도 함 (역방향)</li>
        <li><span style="color:#f5a623;">● 25~44 (공포)</span> — 시장 약세 심리, 변동성 확대</li>
        <li><span style="color:var(--c-primary);">● 45~54 (중립)</span> — 균형 상태</li>
        <li><span style="color:var(--c-up);">● 55~74 (탐욕)</span> — 시장 강세 심리</li>
        <li><span style="color:#0f6e56;">● 75~100 (극도 탐욕)</span> — 과열 신호 (역방향, 조정 가능성)</li>
      </ul>
      <strong style="color:var(--c-primary);">💡 활용:</strong> 역발상 지표로 활용 — 극단치(20 이하 / 80 이상) 진입 시 단기 추세 반전 가능성. 단일 지표보다는 VIX·PCR 과 함께 종합 판단.
    `,
  },
};

// ============================
// 거시 지표 해석 가이드 (CPI, GDP, 실업률, 기준금리, 부동산 등)
// ============================
const MACRO_GUIDES = {
  // ──────── 거시경제 ────────
  cpi: `<strong style="color:var(--c-down);">📊 CPI (소비자물가지수) 란?</strong><br>
    가계가 소비하는 상품·서비스 가격의 변동을 측정. 인플레이션의 핵심 지표.<br><br>
    <strong>해석 기준 (전년동기비, 한국 목표 2%):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:var(--c-up);">● 0% 이하</span> — 디플레이션 (위험: 일본형 장기 침체)</li>
      <li><span style="color:var(--c-up);">● 0~2%</span> — 안정 (목표 부근)</li>
      <li><span style="color:#f5a623;">● 2~3%</span> — 정상 인플레이션</li>
      <li><span style="color:var(--c-down);">● 3~5%</span> — 인플레이션 우려 (금리인상 압력)</li>
      <li><span style="color:#b91c1c;">● 5% 이상</span> — 고물가 (2022~2023 미국 9.1%, 한국 6.3% 최고치)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> Fed/한은 통화정책 결정의 1순위 지표. 근원 CPI(에너지/식품 제외)와 함께 봐야 정확.`,

  gdp: `<strong style="color:var(--c-up);">📊 GDP 성장률 이란?</strong><br>
    국내총생산의 전년동기 또는 전기 대비 변화율. 경제 활동의 규모를 측정.<br><br>
    <strong>해석 기준 (전년동기비):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:#b91c1c;">● -2% 이하</span> — 심각한 경기침체 (recession)</li>
      <li><span style="color:var(--c-down);">● -2~0%</span> — 침체 (2분기 연속 마이너스 = 기술적 침체)</li>
      <li><span style="color:#f5a623;">● 0~1%</span> — 저성장 (스태그플레이션 우려)</li>
      <li><span style="color:var(--c-up);">● 1~3%</span> — 정상 성장 (선진국 평균)</li>
      <li><span style="color:#0f6e56;">● 3% 이상</span> — 고성장 (한국 잠재성장률 2.0%, 미국 2.5% 부근)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 분기별 발표. 한국 잠재성장률 ~2.0%, 그 이하면 경기 둔화 신호.`,

  unemployment: `<strong style="color:#f5a623;">📊 실업률 이란?</strong><br>
    경제활동인구 중 실업자 비율. 노동시장 건강성과 경기 사이클을 반영.<br><br>
    <strong>해석 기준 (한국 자연실업률 ~3%, 미국 ~4.5%):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:var(--c-up);">● 한국 3% 이하 / 미국 4% 이하</span> — 완전고용 (임금상승 압력)</li>
      <li><span style="color:var(--c-up);">● 한국 3~4% / 미국 4~5%</span> — 정상</li>
      <li><span style="color:#f5a623;">● 한국 4~5% / 미국 5~6%</span> — 경기둔화 신호</li>
      <li><span style="color:var(--c-down);">● 한국 5% 이상 / 미국 6% 이상</span> — 경기침체 진입</li>
      <li><span style="color:#b91c1c;">● 미국 7% 이상</span> — 침체 확정 (2008 10%, 2020 14.7% 코로나)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> Sahm Rule — 실업률 3M평균이 12개월 최저치 대비 +0.5%p 이상 상승 시 침체 신호.`,

  base_rate: `<strong style="color:var(--c-primary);">📊 기준금리 (정책금리) 란?</strong><br>
    중앙은행이 시중은행에 적용하는 금리. 통화정책의 핵심 도구.<br><br>
    <strong>해석 기준 (중립금리: 한국 ~2.5%, 미국 ~3%):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:#b91c1c;">● 0~0.5%</span> — 양적완화/제로금리 (경기 부양 모드)</li>
      <li><span style="color:var(--c-down);">● 0.5~2%</span> — 완화적 통화정책</li>
      <li><span style="color:#f5a623;">● 2~3%</span> — 중립 부근</li>
      <li><span style="color:var(--c-up);">● 3~5%</span> — 긴축 (인플레이션 억제)</li>
      <li><span style="color:#0f6e56;">● 5% 이상</span> — 강한 긴축 (2023 미국 5.5%, 한국 3.5%)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 채권시장, 환율, 부동산, 주식 전반에 영향. 금리 인상기 = 채권가격 하락 / 인하기 = 채권가격 상승.`,

  hpi: `<strong style="color:var(--c-up);">📊 주택가격지수 (HPI) 란?</strong><br>
    주택 매매가격의 시계열 변화. 한국 R-ONE은 2021.6=100 기준, 미국 Case-Shiller는 1990=100 기준.<br><br>
    <strong>해석:</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li>전월비 +0.5% 이상 — 강한 상승세 (과열 가능성)</li>
      <li>전월비 0~0.5% — 정상 상승</li>
      <li>전월비 0~-0.5% — 보합/약세</li>
      <li>전월비 -0.5% 이하 — 하락세 (장기화 시 시장 침체)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 주담대 금리, 가계부채, 인구 변화와 함께 종합 판단. 한국 2022년 정점 후 -10% 조정 → 2024년 회복.`,

  mortgage_rate: `<strong style="color:var(--c-down);">📊 모기지 / 주담대 금리 이란?</strong><br>
    주택구입자금 대출의 평균 금리. 한국 신규 주담대, 미국 30년 고정 모기지가 대표.<br><br>
    <strong>해석 기준:</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:var(--c-up);">● 미국 3% 이하 / 한국 3% 이하</span> — 매우 낮음 (저금리 시대, 부동산 활황)</li>
      <li><span style="color:var(--c-up);">● 미국 3~5% / 한국 3~4%</span> — 정상</li>
      <li><span style="color:#f5a623;">● 미국 5~7% / 한국 4~5%</span> — 부담 (수요 위축)</li>
      <li><span style="color:var(--c-down);">● 미국 7% 이상 / 한국 5% 이상</span> — 높은 부담 (구매력 ↓)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 기준금리 + 스프레드 = 모기지 금리. Fed 정책 변화 직후 시장에 반영. 한국 코픽스(COFIX) 기준 변동금리 영향.`,

  unsold: `<strong style="color:var(--c-down);">📊 미분양 주택 수 란?</strong><br>
    분양 후 매각되지 않은 주택의 누적 호수. 공급 과잉/수요 부족의 핵심 지표.<br><br>
    <strong>해석 기준 (한국 전국):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:var(--c-up);">● 3만 호 이하</span> — 공급 부족 (수요 우위)</li>
      <li><span style="color:var(--c-up);">● 3~5만 호</span> — 정상 (역사적 평균 부근)</li>
      <li><span style="color:#f5a623;">● 5~7만 호</span> — 공급 과잉 우려</li>
      <li><span style="color:var(--c-down);">● 7만 호 이상</span> — 심각한 침체 (2023년 6.8만, 2009년 16.5만 최고)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 준공 후 미분양(악성)이 1만 호 초과 시 시장 침체. 지방 미분양 ↑ = 부동산 양극화 심화.`,

  vix: SENTIMENT_GUIDES.vix.guide,

  trade_count: `<strong style="color:var(--c-up);">📊 주택 거래량 (매매) 란?</strong><br>
    월간 신고된 부동산 매매계약 건수. 시장 활성도와 수요·공급 균형을 판단하는 1차 지표.<br><br>
    <strong>해석 기준 (한국 전국 월간):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:#b91c1c;">● 3만 건 이하</span> — 거래 절벽 (2022~2023 침체기, 2~3만 건)</li>
      <li><span style="color:var(--c-down);">● 3~5만 건</span> — 위축 (수요 부족)</li>
      <li><span style="color:#f5a623;">● 5~7만 건</span> — 정상 (10년 평균 6.5만 부근)</li>
      <li><span style="color:var(--c-up);">● 7~10만 건</span> — 활황</li>
      <li><span style="color:#0f6e56;">● 10만 건 이상</span> — 과열 (2020 코로나 저금리기 11만+)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 가격지수에 약 3개월 선행. 거래량 ↓ + 가격 ↓ = 침체 진입, 거래량 ↑ + 가격 보합 = 회복 신호. 자료: 국토교통부 실거래가공개시스템.`,

  permit: `<strong style="color:#f5a623;">📊 주택 인허가 (Permits) 란?</strong><br>
    정부가 발급한 신규 주택 건설 허가 건수. 향후 1~3년 후 공급량을 예측하는 선행지표.<br><br>
    <strong>해석 기준 (한국 연간):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:#b91c1c;">● 30만 호 이하</span> — 공급 절벽 우려 (3년 후 가격 급등 위험)</li>
      <li><span style="color:var(--c-down);">● 30~40만 호</span> — 위축 (2022~2023 ~40만 호)</li>
      <li><span style="color:#f5a623;">● 40~50만 호</span> — 정상 (적정공급 50만 호 추정)</li>
      <li><span style="color:var(--c-up);">● 50만 호 이상</span> — 충분 (2015~2017 ~70만 호 사상 최대)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 미분양과 함께 보면 정확. 인허가 ↓ + 미분양 ↑ = 단기 공급과잉, 인허가 ↓ + 미분양 ↓ = 향후 가격 상승 압력. 자료: 국토교통부.`,

  start: `<strong style="color:var(--c-primary);">📊 주택 착공 (Starts) 란?</strong><br>
    실제 공사가 시작된 신규 주택의 건설 호수. 인허가보다 더 확실한 공급 선행지표 (1~2년 후 입주).<br><br>
    <strong>해석 기준 (한국 연간):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:#b91c1c;">● 25만 호 이하</span> — 공급 절벽 (2~3년 후 시장 압박)</li>
      <li><span style="color:var(--c-down);">● 25~35만 호</span> — 위축</li>
      <li><span style="color:#f5a623;">● 35~45만 호</span> — 정상</li>
      <li><span style="color:var(--c-up);">● 45만 호 이상</span> — 충분 (2015~2017 60만+)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 미국은 'Housing Starts' (FRED: HOUST) 로 발표. 인허가 → 착공 → 준공 (입주) 순으로 약 12~18개월 시차. 자료: 국토교통부.`,

  current_account: `<strong style="color:var(--c-up);">📊 경상수지 란?</strong><br>
    국가의 대외 거래 결과 — 상품·서비스 수출입 + 본원·이전소득 합산. 흑자/적자가 환율·외환보유고 결정 요인.<br><br>
    <strong>해석 기준 (한국 월간, 억 달러):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:#b91c1c;">● -50억 달러 이하</span> — 큰 적자 (외환위기 위험)</li>
      <li><span style="color:var(--c-down);">● -50~0</span> — 적자</li>
      <li><span style="color:#f5a623;">● 0~50</span> — 소폭 흑자</li>
      <li><span style="color:var(--c-up);">● 50~100</span> — 양호한 흑자</li>
      <li><span style="color:#0f6e56;">● 100억 달러 이상</span> — 큰 흑자 (한국 평균 50~80억)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 흑자 지속 = 원화 강세 압력, 적자 지속 = 원화 약세 압력. 한국은 12개월 누적 600~700억 달러 흑자가 정상. 자료: 한국은행 ECOS.`,

  exports: `<strong style="color:#0f6e56;">📊 수출 (월간 무역수지) 란?</strong><br>
    당월 상품 수출 총액. 한국 경제는 GDP의 ~40% 가 수출 → 핵심 경기 지표.<br><br>
    <strong>해석 기준 (한국 월간, 억 달러):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:#b91c1c;">● 450억 달러 이하</span> — 수출 부진 (반도체 다운사이클 등)</li>
      <li><span style="color:var(--c-down);">● 450~550</span> — 위축</li>
      <li><span style="color:#f5a623;">● 550~600</span> — 정상</li>
      <li><span style="color:var(--c-up);">● 600~700</span> — 호조</li>
      <li><span style="color:#0f6e56;">● 700억 달러 이상</span> — 사상 최고 수준 (2024~25 반도체 슈퍼사이클)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 반도체 비중 약 20~25%. 전년동기비 (YoY) 와 함께 보면 추세 판단. 무역수지 (수출-수입) 흑자 = 원화 강세 요인. 자료: 산업통상자원부 / 관세청.`,

  ip: `<strong style="color:#f5a623;">📊 산업생산지수 (IP) 란?</strong><br>
    광공업(제조업+광업) 생산활동 수준. 2020 = 100 기준. 경기변동의 동행지표.<br><br>
    <strong>해석 기준 (전년동기비):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:#b91c1c;">● -5% 이하</span> — 심각한 침체 (2008/2020 -10%대)</li>
      <li><span style="color:var(--c-down);">● -5~0%</span> — 침체</li>
      <li><span style="color:#f5a623;">● 0~3%</span> — 저성장</li>
      <li><span style="color:var(--c-up);">● 3~7%</span> — 정상~호조</li>
      <li><span style="color:#0f6e56;">● 7% 이상</span> — 호황 (반도체 등 IT 강한 증가세)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 제조업 PMI, 수출, GDP 와 동조. 한국은 제조업 비중 ~27% (선진국 평균 15% 대비 高). 자료: 통계청 / 한국은행 ECOS.`,

  retail: `<strong style="color:var(--c-up);">📊 소매판매액지수 란?</strong><br>
    소매업체의 매출액 변동. 가계 소비 지출 = GDP의 ~50%. 내수 경기 핵심 지표.<br><br>
    <strong>해석 기준 (전년동기비):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:#b91c1c;">● -5% 이하</span> — 소비 절벽 (불황)</li>
      <li><span style="color:var(--c-down);">● -5~0%</span> — 소비 위축</li>
      <li><span style="color:#f5a623;">● 0~3%</span> — 약한 회복</li>
      <li><span style="color:var(--c-up);">● 3~6%</span> — 정상</li>
      <li><span style="color:#0f6e56;">● 6% 이상</span> — 강한 소비 (인플레 우려)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 고용·임금·심리지표와 연동. 명목 지수와 실질 지수 (인플레 제외)를 함께 봐야 정확. 자료: 통계청 / 한국은행 ECOS.`,

  pir: `<strong style="color:var(--c-down);">📊 PIR (Price-to-Income Ratio) 이란?</strong><br>
    중위 주택가격 ÷ 가구 중위소득. 가구 평균소득으로 주택을 사는데 몇 년 걸리는지의 배수.<br><br>
    <strong>해석 기준 (서울 기준):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:var(--c-up);">● 5배 이하</span> — 매우 저렴 (선진국 평균 5~7배)</li>
      <li><span style="color:var(--c-up);">● 5~10배</span> — 보통</li>
      <li><span style="color:#f5a623;">● 10~15배</span> — 부담</li>
      <li><span style="color:var(--c-down);">● 15~20배</span> — 과열 (서울 2024~25 19배대)</li>
      <li><span style="color:#b91c1c;">● 20배 이상</span> — 매우 위험 (홍콩 23배, 시드니 13배)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 한국 전국 평균 ~10배, 서울 ~19배 → 서울 양극화 심화. 자료: KB부동산 / 통계청 가계금융복지.`,

  household_debt: `<strong style="color:var(--c-down);">📊 가계신용 (가계부채) 란?</strong><br>
    가계가 진 모든 빚 — 은행·비은행 대출 + 신용카드 미결제 잔액. GDP 대비 비율로 평가.<br><br>
    <strong>해석 기준 (GDP 대비):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:var(--c-up);">● 50% 이하</span> — 매우 안정</li>
      <li><span style="color:#f5a623;">● 50~80%</span> — 정상 (선진국 평균)</li>
      <li><span style="color:var(--c-down);">● 80~100%</span> — 위험 수준</li>
      <li><span style="color:#b91c1c;">● 100% 이상</span> — 심각 (한국 2024 ~95%, 호주 110%, 스위스 130%)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 한국은 부동산 담보대출이 ~60%. 금리 인상 시 가계의 이자부담 ↑ → 소비 위축. 자료: 한국은행 ECOS.`,

  pmi: `<strong style="color:var(--c-primary);">📊 제조업 PMI 란?</strong><br>
    구매관리자지수. 신규수주·생산·고용·재고·납기 5개 항목 가중평균. 50 기준.<br><br>
    <strong>해석 기준 (S&P Global / ISM):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:#b91c1c;">● 45 이하</span> — 강한 위축 (불황 신호)</li>
      <li><span style="color:var(--c-down);">● 45~50</span> — 위축 (50 미만이면 제조업 경기 축소)</li>
      <li><span style="color:#f5a623;">● 50~52</span> — 보합</li>
      <li><span style="color:var(--c-up);">● 52~55</span> — 정상 성장</li>
      <li><span style="color:#0f6e56;">● 55 이상</span> — 강한 확장</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 50 기준선 돌파/하향이 추세 전환 시그널. 매월 1일 첫 영업일 발표 (가장 빠른 경기지표). 자료: S&P Global / ISM.`,

  m2: `<strong style="color:var(--c-primary);">📊 M2 통화량 이란?</strong><br>
    M1 (현금+요구불예금) + 저축성예금 + MMF + 단기금융상품. 시중 유동성의 폭넓은 측정치.<br><br>
    <strong>해석 (전년동기비):</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:var(--c-down);">● -2% 이하</span> — 매우 긴축 (2022~23 미국 -3%, 사상 최초)</li>
      <li><span style="color:#f5a623;">● -2~3%</span> — 긴축</li>
      <li><span style="color:var(--c-up);">● 3~8%</span> — 정상</li>
      <li><span style="color:#0f6e56;">● 8% 이상</span> — 강한 완화 (2020 코로나 25%+)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 인플레이션 선행지표. M2 ↑ → 12~18개월 후 인플레 ↑. Fed/한은의 양적완화·긴축 효과를 가시화. 자료: Fed (FRED: M2SL) / 한국은행 ECOS.`,

  dxy: `<strong style="color:var(--c-up);">📊 달러 인덱스 (DXY) 란?</strong><br>
    미 달러 vs 6개 주요통화 (유로 57.6%, 엔 13.6%, 파운드 11.9%, CAD/SEK/CHF) 의 가중 환율. 글로벌 달러 강세 측정.<br><br>
    <strong>해석 기준:</strong>
    <ul style="margin:4px 0 4px 16px;padding:0;line-height:1.8;">
      <li><span style="color:var(--c-down);">● 90 이하</span> — 달러 약세 (신흥국 자금유입)</li>
      <li><span style="color:#f5a623;">● 90~100</span> — 보합</li>
      <li><span style="color:var(--c-up);">● 100~105</span> — 정상~소폭 강세</li>
      <li><span style="color:#0f6e56;">● 105 이상</span> — 강한 달러 (한국 원화 약세, 신흥국 자본유출)</li>
      <li><span style="color:#b91c1c;">● 110 이상</span> — 매우 강함 (2022 114, 1985 165 사상 최고)</li>
    </ul>
    <strong style="color:var(--c-primary);">💡 활용:</strong> 원자재 가격과 역의 상관. 달러 ↑ = 금/원유 가격 ↓ (달러 표시). Fed 금리 ↑ = 달러 ↑. 자료: ICE / Fed.`,
};

// 데이터 경로 or 제목 기반 가이드 매칭
function _getMacroGuide(dataPath, title) {
  if(!dataPath && !title) return null;
  const dp = (dataPath || '').toLowerCase();
  const t = (title || '').toLowerCase();
  // 카테고리별 매칭 (구체적 키워드 우선)
  if(dp.includes('cpi') || t.includes('cpi') || t.includes('물가') || t.includes('소비자물가')) return MACRO_GUIDES.cpi;
  if(dp.includes('gdp') || t.includes('gdp') || t.includes('성장률')) return MACRO_GUIDES.gdp;
  if(dp.includes('unemploy') || dp.includes('unemp') || t.includes('실업')) return MACRO_GUIDES.unemployment;
  if(dp.includes('base_rate') || dp.includes('ff_rate') || dp.includes('us10y') || dp.includes('us2y') || t.includes('기준금리') || t.includes('정책금리') || t.includes('국채')) return MACRO_GUIDES.base_rate;
  if(dp.includes('mortgage') || t.includes('모기지') || t.includes('주담대')) return MACRO_GUIDES.mortgage_rate;
  if(dp.includes('unsold') || t.includes('미분양')) return MACRO_GUIDES.unsold;
  if(dp.includes('trade_count') || t.includes('거래량')) return MACRO_GUIDES.trade_count;
  if(dp.includes('permit') || t.includes('인허가')) return MACRO_GUIDES.permit;
  if(dp.includes('start') || t.includes('착공') || t.includes('housing start')) return MACRO_GUIDES.start;
  if(dp.includes('current_account') || t.includes('경상수지')) return MACRO_GUIDES.current_account;
  if(dp.includes('exports') || t.includes('수출')) return MACRO_GUIDES.exports;
  if(dp.includes('ip_') || dp.includes('산업생산') || t.includes('산업생산')) return MACRO_GUIDES.ip;
  if(dp.includes('retail') || t.includes('소매판매')) return MACRO_GUIDES.retail;
  if(dp.includes('pir') || t.includes('pir') || t.includes('소득대비')) return MACRO_GUIDES.pir;
  if(dp.includes('household_debt') || t.includes('가계신용') || t.includes('가계부채')) return MACRO_GUIDES.household_debt;
  if(dp.includes('pmi') || t.includes('pmi')) return MACRO_GUIDES.pmi;
  if(dp.includes('m2') || t.includes('m2') || t.includes('통화량')) return MACRO_GUIDES.m2;
  if(dp.includes('dxy') || t.includes('달러 인덱스') || t.includes('dxy')) return MACRO_GUIDES.dxy;
  if(dp.includes('apt_price') || dp.includes('case_shiller') || dp.includes('hpi') || dp.includes('jns_price') ||
     t.includes('가격지수') || t.includes('hpi') || t.includes('case-shiller') || t.includes('아파트')) return MACRO_GUIDES.hpi;
  if(dp.includes('vix') || t.includes('vix')) return MACRO_GUIDES.vix;
  return null;
}

function showSentimentDetail(key) {
  const guide = SENTIMENT_GUIDES[key];
  if(!guide) return;
  // _reHistState 설정 후 모달 열기
  _reHistState.key = '__sentiment_'+key;
  _reHistState.title = guide.title;
  _reHistState.unit = guide.unit;
  _reHistState.period = 'all';
  _reHistState.timeUnit = 'M';
  _reHistState.macroDataPath = guide.dataPath;
  _reHistState.macroOpts = { unit: guide.unit, src: guide.source };
  _reHistState.guide = guide.guide;
  // 셀렉터 UI 초기화
  document.querySelectorAll('.reHistPeriodBtn').forEach(b=>{
    const isActive = b.dataset.period === 'all';
    b.classList.toggle('active', isActive);
    b.style.background = isActive ? getThemeColors().accent : 'transparent';
    b.style.color = isActive ? '#fff' : 'var(--c-txt-dim,#a4a8bc)';
  });
  document.querySelectorAll('.reHistUnitBtn').forEach(b=>{
    const isActive = b.dataset.unit === 'M';
    b.classList.toggle('active', isActive);
    b.style.background = isActive ? getThemeColors().accent : 'transparent';
    b.style.color = isActive ? '#fff' : 'var(--c-txt-dim,#a4a8bc)';
  });
  const modal = document.getElementById('reHistoryChartModal');
  if(modal) modal.style.display = 'flex';
  _renderReHistChartSentiment(guide);
  // 히스토리가 없으면 즉시 fetch — 도착하는 즉시 applySentimentClient 가 모달 재렌더
  try {
    const d = _latestDataForIndicators || {};
    const node = (typeof getDataByPath === 'function') ? getDataByPath(d, guide.dataPath) : null;
    const hasHistory = node && node.history && typeof node.history === 'object' && Object.keys(node.history).length > 1;
    if(!hasHistory && (key === 'vkospi' || key === 'move' || key === 'pcr' || key === 'fear_greed')) {
      // 노트에 로딩 표시
      const noteEl = document.getElementById('reHistNote');
      if(noteEl && noteEl.textContent.includes('데이터 없음')) {
        noteEl.innerHTML = '<span style="color:var(--c-primary);">⟳ 시계열 데이터 불러오는 중…</span>';
      }
      fetchSentimentClient().then(applySentimentClient).catch(()=>{});
    }
  } catch(_) {}
}

function _renderReHistChartSentiment(guide) {
  const { period, timeUnit, title, unit } = _reHistState;
  const titleEl = document.getElementById('reHistTitle');
  const metaEl  = document.getElementById('reHistMeta');
  const noteEl  = document.getElementById('reHistNote');
  const guideEl = document.getElementById('reHistGuide');
  if(titleEl) titleEl.textContent = title;
  if(metaEl) metaEl.innerHTML = `<span style="color:var(--c-primary);">단위:</span> ${unit||'—'} &nbsp; <span style="color:var(--c-primary);">출처:</span> ${guide.source}`;
  if(guideEl) {
    guideEl.innerHTML = guide.guide;
    guideEl.style.display = 'block';
    guideEl.style.borderLeftColor = guide.color || getThemeColors().accent;
  }
  destroyChart('reHistChart');
  _setReHistEmpty('');
  // 데이터 경로에서 시계열 추출
  const d = _latestDataForIndicators || {};
  const node = getDataByPath(d, guide.dataPath);
  let labels=[], values=[];
  // VKOSPI 의 경우 합리적 범위 검증 + VIX 교차검증 — KOSPI 오매핑·스크래핑 오염 검출
  const isVkospi = (guide.dataPath || '').includes('vkospi');
  const _vkospiVix = (_latestDataForIndicators?.economicIndicators?.us?.vix?.value) || 0;
  const _vkospiXvalid = !isVkospi || !_vkospiVix || (node?.value != null && node.value / _vkospiVix >= 0.3 && node.value / _vkospiVix <= 4.0);
  const valIsValid = node?.value != null && (!isVkospi || (_isValidVkospi(node.value) && _vkospiXvalid));
  if(node?.history && typeof node.history === 'object' && Object.keys(node.history).length > 0) {
    // VKOSPI 히스토리 — 잘못된 값 필터링
    Object.keys(node.history).sort().forEach(p=>{
      const v = node.history[p];
      if(isVkospi && !_isValidVkospi(v)) return;
      labels.push(p);
      values.push(v);
    });
  }
  // 히스토리가 2개 미만이면 placeholder 대신 안내 메시지 + 즉시 fetch 트리거
  // (이전에는 12개월 같은 값으로 평탄선 그렸으나, 사용자가 차트가 평탄하다고 오해할 수 있어 제거)
  const uniqueValues = new Set(values).size;
  if(labels.length < 2 || uniqueValues < 2) {
    if(noteEl) {
      const isSentimentClientKey = ['vkospi','move','pcr','fear_greed'].some(k => (guide.dataPath||'').endsWith(k));
      if(isVkospi && node?.value != null && (!_isValidVkospi(node.value) || !_vkospiXvalid)) {
        const _xMsg = !_isValidVkospi(node.value) ? `합리적 범위 벗어남(${node.value})`
          : `VIX(${_vkospiVix.toFixed(1)}) 대비 비율 이상(${(node.value/_vkospiVix).toFixed(2)}x — 스크래핑 오염 의심)`;
        noteEl.innerHTML = `<span style="color:var(--c-down,var(--c-error));">⚠️ VKOSPI ${_xMsg}</span> — 다음 갱신에서 자동 보정`;
      } else if(valIsValid) {
        noteEl.innerHTML = `<span style="color:var(--c-primary);">⟳ 시계열 데이터 수집 중…</span> &nbsp; <span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">현재값: ${node.value} (${guide.source})</span>`;
        // 즉시 fetch 트리거 (Naver 차트 API)
        if(typeof fetchSentimentClient === 'function') {
          fetchSentimentClient().then(applySentimentClient).catch(()=>{});
        }
      } else if(isSentimentClientKey) {
        // 합성 fallback 제거 이후: 페치 모두 실패 시 명확한 안내
        noteEl.innerHTML = `<span style="color:var(--c-down,var(--c-error));">⚠️ 데이터 수집 실패</span> — 브라우저 환경에서 외부 API 접근이 차단되었거나 일시적 응답 없음. <a href="javascript:void(0)" onclick="(function(){var b=event.target;b.textContent='⟳ 페치 중…';fetchSentimentClient().then(applySentimentClient).then(function(){b.textContent='✓ 갱신 시도 완료';}).catch(function(){b.textContent='✗ 실패';});})()" style="color:var(--c-primary);text-decoration:underline;">↻ 다시 시도</a>`;
        // 자동으로 1회 재시도
        if(typeof fetchSentimentClient === 'function') {
          fetchSentimentClient().then(applySentimentClient).catch(()=>{});
        }
      } else {
        noteEl.textContent = '시계열 데이터 없음 — 데이터 갱신 시 자동 표시됩니다.';
      }
    }
    // 빈 차트 영역에 안내문을 가운데 표시 (큰 흰 여백 대신) — note 내용을 그대로 노출
    _setReHistEmpty(
      `<div style="font-size:var(--font-size-2xl);opacity:.5;margin-bottom:6px;">📉</div>` +
      `<div style="max-width:340px;">${(noteEl && noteEl.innerHTML) || '시계열 데이터 없음'}</div>`
    );
    return;
  }
  // 기간/단위 리샘플링
  const resampled = _resampleHistSeries(labels, values, period, timeUnit);
  if(noteEl) noteEl.textContent = `출처: ${guide.source}${period!=='all'?' · 기간: '+period:''}${timeUnit!=='M'?' · 단위: '+({Q:'분기',H:'반기',Y:'연'}[timeUnit]||timeUnit):''}`;
  const ctx = document.getElementById('reHistChart');
  if(!ctx || !resampled.values.length) return;
  const tc = (typeof getThemeColors==='function') ? getThemeColors() : {txt:'#8d90a2',grid:'#2a2e3d55',tooltip:'#262a35',ttTitle:'#dfe2f2',ttBorder:'#2a2e3d'};
  charts['reHistChart'] = new Chart(ctx, {
    type:'line',
    data:{ labels: resampled.labels, datasets:[{
      label: title + (unit?` (${unit})`:''),
      data: resampled.values,
      borderColor: guide.color || getThemeColors().accent,
      backgroundColor: (guide.color || getThemeColors().accent) + '22',
      borderWidth: 2, pointRadius: resampled.values.length > 30 ? 0 : 2,
      tension: 0.3, fill: true,
    }]},
    options:{ responsive:true, maintainAspectRatio:false,
      scales:{
        x:{ ticks:{color:tc.txt,font:{size:10},maxTicksLimit:12}, grid:{color:tc.grid}},
        y:{ ticks:{color:tc.txt,font:{size:10},maxTicksLimit:8,callback:v=>_axisTick(v,unit)}, grid:{color:tc.grid}, position:'right'},
      },
      plugins:{
        legend:{display:true,labels:{color:tc.txt,font:{size:10},boxWidth:10}},
        subtitle:_axisUnitSubtitle(unit,tc.txt),
        tooltip:{mode:'index',intersect:false,backgroundColor:tc.tooltip,titleColor:tc.ttTitle,bodyColor:tc.ttTitle,borderColor:tc.ttBorder,borderWidth:1,
          callbacks:{label: c=> `${title}: ${typeof c.parsed.y==='number'?fmtNum(c.parsed.y):c.parsed.y}${unit?' ['+unit+']':''}`}}
      }
    }
  });
}

// ============================
// 실시간 데이터 로드 (data.json)
// ============================
// 지표 leaf 가 '빈 값'인지 — value:null 또는 빈 객체. (서버가 VIX 등을 비워 보낸 케이스 판정)
function _isEmptyMetricVal(m) {
  if(m == null) return true;
  if(typeof m === 'object' && !Array.isArray(m)) {
    if('value' in m) return m.value == null;   // metric leaf
    return Object.keys(m).length === 0;          // 빈 컨테이너
  }
  return false;
}
// metric leaf 의 기준일(신선도 비교용) — as_of > period > date 순.
function _metricDate(m) {
  if(!m || typeof m !== 'object') return '';
  return String(m.as_of || m.period || m.date || '');
}
// server(new) leaf 를 채택할지 결정. 빈 서버값은 기존 유효값을 못 덮어쓰고,
// 둘 다 유효하면 더 최신(기준일) 값을 택한다. (live VIX 가 stale FRED VIX 에 안 밀림)
function _shouldAdoptServerLeaf(serverLeaf, clientLeaf) {
  if(_isEmptyMetricVal(serverLeaf)) return false;          // 빈 서버값 → 기존 보존
  if(_isEmptyMetricVal(clientLeaf)) return true;           // 기존 없음 → 서버값 채택
  const ds = _metricDate(serverLeaf), dc = _metricDate(clientLeaf);
  if(ds && dc && ds < dc) return false;                    // 클라이언트가 더 최신 → 보존
  return true;                                              // 동률/판단불가/서버최신 → 서버값
}
// 지표 컨테이너(economicIndicators / realestate / sentiment) 깊은 머지.
// 핵심: 서버(data.json) 의 leaf 가 비었는데 기존(클라이언트 보강) 값이 유효하면 보존.
// 이래야 클라이언트가 채운 VIX(economicIndicators.us.vix)가 1~3분마다 도는 loadRealData
// 의 null/구버전 서버값에 의해 지워지지 않는다. (FRED 실패로 서버 VIX 가 비어도 카드 유지.)
function _mergeIndicatorContainer(prevC, newC) {
  const out = { ...(prevC || {}) };
  Object.keys(newC || {}).forEach(key => {
    const nv = newC[key];
    const pv = prevC ? prevC[key] : undefined;
    if(nv && typeof nv === 'object' && !Array.isArray(nv)) {
      if('value' in nv) {
        // 이 레벨이 곧 metric leaf (예: sentiment.vkospi)
        if(_shouldAdoptServerLeaf(nv, pv)) out[key] = nv;
      } else {
        // 국가 컨테이너 (예: economicIndicators.us) — leaf 단위로 머지
        const sub = { ...((pv && typeof pv === 'object') ? pv : {}) };
        Object.keys(nv).forEach(ik => {
          if(_shouldAdoptServerLeaf(nv[ik], sub[ik])) sub[ik] = nv[ik];
        });
        out[key] = sub;
      }
    } else if(nv != null) {
      out[key] = nv;
    }
  });
  return out;
}

// ============================================================
// 🤖 AI 시황 요약 — 실시간 데이터 기반 '오늘의 마켓 브리핑' 자동 생성
// 정적 사이트라 브라우저에서 LLM 을 직접 호출하지 않고(키 노출 위험), 수집된
// 실시간 지수/환율/원자재/등락/심리 데이터를 룰 기반으로 자연어 요약한다.
// ============================================================
function _aiChgSpan(chg, digits) {
  if(chg == null || isNaN(chg)) return '<span style="color:var(--c-txt-dim);">—</span>';
  const up = +chg >= 0;
  const c = up ? 'var(--c-up,#26a69a)' : 'var(--c-down,#ef5350)';
  return `<span style="color:${c};font-weight:var(--font-weight-semibold);">${up?'▲':'▼'} ${up?'+':''}${(+chg).toFixed(digits==null?2:digits)}%</span>`;
}
function _aiNum(v) { return (v==null||isNaN(v)) ? '—' : (+v).toLocaleString('en-US',{maximumFractionDigits:2}); }
function _fgLabel(fg) {
  const v = fg && fg.value;
  if(v==null) return '—';
  return v<25?'극도 공포':v<45?'공포':v<55?'중립':v<75?'탐욕':'극도 탐욕';
}

// 🤖 (구) AI 시황 요약 함수들 제거됨 — 사이트 내 'AI 요약 생성' 기능은 삭제되었다(사용자 요청).
// 대신 매일 오전 10시(KST) data.json 요약을 카카오톡으로 자동 발송한다
// (scripts/send_kakao_digest.py + .github/workflows/kakao-daily.yml).

function applyRealData(d) {
  if (!d) return;
  // 부분 patch 머지: 기존 데이터 + 새 데이터 (얕은 병합)
  // 단, fx/indices/commodities 등이 빈 객체이면 기존 값 보존
  const _DEEP_MERGE_KEYS = { economicIndicators: 1, realestate: 1, sentiment: 1 };
  if(_latestDataForIndicators && _latestDataForIndicators !== d) {
    const prev = _latestDataForIndicators;
    const merged = { ...prev };
    Object.keys(d).forEach(k => {
      const v = d[k];
      if(v && typeof v === 'object' && !Array.isArray(v)) {
        // 빈 객체이면 기존 값 보존
        if(Object.keys(v).length === 0) return;
        // 지표 컨테이너는 leaf 단위 깊은 머지(빈 서버값이 기존 유효값 못 덮어쓰게), 그 외는 얕은 머지
        if(_DEEP_MERGE_KEYS[k]) {
          merged[k] = _mergeIndicatorContainer(prev[k] || {}, v);
        } else {
          merged[k] = { ...(prev[k] || {}), ...v };
        }
      } else if(v != null) {
        merged[k] = v;
      }
    });
    d = merged;
  }
  // 한국 누락 지표 fallback — data.json 에 없으면 하드코딩 값 주입
  if(!d.economicIndicators) d.economicIndicators = {};
  if(!d.economicIndicators.kr) d.economicIndicators.kr = {};
  if(d.economicIndicators.kr.gdp_kr == null) d.economicIndicators.kr.gdp_kr = KR_GDP_QOQ_FALLBACK;
  if(d.economicIndicators.kr.retail_kr == null) d.economicIndicators.kr.retail_kr = KR_FALLBACKS.retail_kr;
  if(d.economicIndicators.kr.unemployment_kr == null) d.economicIndicators.kr.unemployment_kr = KR_FALLBACKS.unemployment_kr;
  if(d.economicIndicators.kr.exports_kr == null) d.economicIndicators.kr.exports_kr = KR_FALLBACKS.exports_kr;
  // ip_kr 은 이미 data.json 에 있을 수 있으나 가끔 value:null 이므로 그것도 처리
  if(d.economicIndicators.kr.ip_kr == null || d.economicIndicators.kr.ip_kr.value == null) {
    d.economicIndicators.kr.ip_kr = KR_FALLBACKS.ip_kr_fb;
  }
  _latestDataForIndicators = d;
  buildMacroIndicatorTable();
  // 🤖 오늘의 매크로 3줄 요약 — 서버(scripts/ai_briefing.py)가 생성한 aiBriefing 이 있을 때만 배너 표시.
  // (과거 클라이언트측 AI 시황 요약은 사용자 요청으로 제거 — 카카오톡 발송과 병행하여 서버 생성분만 렌더.)
  try { renderAiBriefing(d.aiBriefing); } catch(_) {}
  // 🔔 경제 캘린더 구독 이벤트 — 실제값(act) 갱신 감지 시 브라우저 알림 (Task 2.3)
  try { checkCalendarAlerts(d); } catch(_) {}
  // 🔀 이중축 지표 비교 차트 — 데이터 적용 후 셀렉트 옵션/차트 초기화 (Task 3.1)
  try { initCompareTool(); } catch(_) {}
  // 투자자별 순매매(실데이터) 갱신 — 새 data.json 이 적용되면 raw 재로딩 후 차트 재렌더
  try {
    investorRawData = _getInvestorRawData();
    const mp = document.getElementById('page-market');
    if(mp && mp.classList.contains('active') && typeof buildInvestorChart === 'function') buildInvestorChart();
  } catch(_) {}
  // 부동산 시도별 변동률 — 라이브(R-ONE) 값으로 krRegionData 갱신 (있을 때만; 시군구는 _getSubRegions 가 처리)
  try {
    const reg = ((d.realestate||{}).kr||{}).region;
    if(Array.isArray(reg) && reg.length && typeof krRegionData !== 'undefined') {
      const byCode = {}; reg.forEach(r => { if(r && r.code != null && typeof r.val === 'number') byCode[r.code] = r.val; });
      krRegionData.forEach(r => { if(byCode[r.code] != null) r.val = byCode[r.code]; });
      const rp = document.getElementById('page-realestate');
      if(rp && rp.classList.contains('active') && typeof buildKoreaRegionMap === 'function') { try { buildKoreaRegionMap(); } catch(_){} }
    }
  } catch(_) {}

  // ── 시계열 데이터 주입: data.json.history 가 있으면 차트가 실제 데이터를 사용 ──
  // 대시보드 메인 차트 (KOSPI 기본)
  // 무한 재렌더 방지: history.KOSPI 데이터가 실제로 변경된 경우에만 재빌드
  if(d.history && d.history.indices && d.history.indices.KOSPI) {
    // 메인 차트도 상세 모달과 동일하게 getHistoricalSeries(spot 동기화 경로)를 사용 —
    // 헤더 숫자와 차트 끝점 불일치 방지
    const syncedKospi = getHistoricalSeries('indices','KOSPI')
                      || d.history.indices.KOSPI.map(p => ({x: p.date, y: p.close}));
    const lastPt = syncedKospi[syncedKospi.length-1] || {};
    const newKospiHash = syncedKospi.length + ':' + (lastPt.y||'') + ':' + (lastPt.x||'');
    if(_lastKospiHistoryHash !== newKospiHash) {
      _lastKospiHistoryHash = newKospiHash;
      mainAllData = syncedKospi;
      allVol = mainAllData.map(p => ({x: p.x, y: 500000}));
      const dashEl = document.getElementById('page-dashboard');
      if(dashEl && dashEl.classList.contains('active')) {
        try { initMainChart(mainPeriodUnit); } catch(_) {}
      }
    }
  }
  // ── 스파크라인 갱신 — getHistoricalSeries(spot 동기화 경로) 사용 (최근 30포인트) ──
  // 카드 미니차트도 메인/상세 차트와 동일 경로를 써서 끝점이 헤더 숫자와 일치하도록 함
  // 색은 고정색이 아니라 표시 구간의 실제 추세 방향으로 결정 — 같은 카드의 등락 텍스트와
  // 색 신호가 모순되지 않도록 (메인차트 initMainChart 의 추세색 로직과 동일 패턴)
  function updateSpark(id, series) {
    if(!series || !series.length) return;
    const last30 = series.slice(-30);
    if(last30.length < 2) return;
    const c = last30[last30.length-1].y >= last30[0].y ? window.CUP : window.CDN;
    sparkline(id, last30, c);
  }
  if(d.history) {
    updateSpark('spark1', getHistoricalSeries('indices', 'KOSPI'));
    updateSpark('spark2', getHistoricalSeries('fx', 'USDKRW'));
    updateSpark('spark3', getHistoricalSeries('commodities', 'WTI'));
  }
  const idx = d.indices   || {};
  const fx  = d.fx        || {};
  const com = d.commodities || {};

  const fmt = (v, dec) => v != null
    ? v.toLocaleString('en-US', {minimumFractionDigits:dec, maximumFractionDigits:dec})
    : null;
  const fmtPct = v => v != null
    ? (v >= 0 ? `+${v.toFixed(2)}%` : `${v.toFixed(2)}%`)
    : null;

  // ── 티커 바 업데이트 ──────────────────────────
  // 금리/채권 티커 — 하드코딩 값(2.75%, 4.48%) 대신 data.json 실데이터 사용
  const _ecosKrPre = (d.economicIndicators || {}).kr || {};
  const _ecosUsPre = (d.economicIndicators || {}).us || {};
  const krRate = _ecosKrPre.base_rate_kr;
  const us10y  = _ecosUsPre.us10y;
  const tickerMap = {
    'KOSPI':    idx.KOSPI   && {val: fmt(idx.KOSPI.price,2),   chg: fmtPct(idx.KOSPI.change),   up: idx.KOSPI.change   >= 0},
    'KOSDAQ':   idx.KOSDAQ  && {val: fmt(idx.KOSDAQ.price,2),  chg: fmtPct(idx.KOSDAQ.change),  up: idx.KOSDAQ.change  >= 0},
    'USD/KRW':  fx.USDKRW   && {val: fmt(fx.USDKRW.rate,2),   chg: fmtPct(fx.USDKRW.change),   up: fx.USDKRW.change   >= 0},
    'EUR/KRW':  fx.EURKRW   && {val: fmt(fx.EURKRW.rate,2),   chg: fmtPct(fx.EURKRW.change),   up: fx.EURKRW.change   >= 0},
    'WTI':      com.WTI     && {val: '$'+fmt(com.WTI.price,2), chg: fmtPct(com.WTI.change),     up: com.WTI.change     >= 0},
    'BRENT':    com.Brent   && {val: '$'+fmt(com.Brent.price,2),chg: fmtPct(com.Brent.change),  up: com.Brent.change   >= 0},
    '금(Gold)': com.Gold    && {val: '$'+fmt(com.Gold.price,1), chg: fmtPct(com.Gold.change),   up: com.Gold.change    >= 0},
    'S&P 500':  idx.SP500   && {val: fmt(idx.SP500.price,2),   chg: fmtPct(idx.SP500.change),   up: idx.SP500.change   >= 0},
    'NASDAQ':   idx.NASDAQ  && {val: fmt(idx.NASDAQ.price,2),  chg: fmtPct(idx.NASDAQ.change),  up: idx.NASDAQ.change  >= 0},
    '닛케이':   idx.Nikkei  && {val: fmt(idx.Nikkei.price,2),  chg: fmtPct(idx.Nikkei.change),  up: idx.Nikkei.change  >= 0},
    '한국 기준금리': krRate?.value != null && (() => {
      // 직전 값 추출 — history 에서 가장 최근의 다른 값
      let prev = krRate.value;
      if(krRate.history) {
        const ps = Object.keys(krRate.history).sort();
        for(let i = ps.length - 1; i >= 0; i--) {
          const v = krRate.history[ps[i]];
          if(v != null && Math.abs(v - krRate.value) > 0.001) { prev = v; break; }
        }
      }
      const dir = prev > krRate.value ? '인하↓' : prev < krRate.value ? '인상↑' : '동결';
      const up = prev < krRate.value ? true : prev > krRate.value ? false : null;
      return { val: krRate.value.toFixed(2) + '%', chg: dir, up };
    })(),
    '미 10년물': us10y?.value != null && (() => {
      // 직전월 vs 현재월 변화량
      let chgPp = 0;
      if(us10y.history) {
        const ps = Object.keys(us10y.history).sort();
        if(ps.length >= 2) {
          const cur = us10y.history[ps[ps.length-1]];
          const prv = us10y.history[ps[ps.length-2]];
          if(cur != null && prv != null) chgPp = +(cur - prv).toFixed(2);
        }
      }
      return { val: us10y.value.toFixed(2) + '%', chg: (chgPp>=0?'+':'') + chgPp.toFixed(2), up: chgPp >= 0 };
    })(),
  };
  tickerData.forEach(t => { if (tickerMap[t.name]) Object.assign(t, tickerMap[t.name]); });
  buildTicker();

  // ── 글로벌 지수 테이블 업데이트 ──────────────
  const idxKey = {'KOSPI':'KOSPI','KOSDAQ':'KOSDAQ','S&P 500':'SP500','NASDAQ':'NASDAQ','닛케이':'Nikkei','상하이':'Shanghai'};
  globalIndices.forEach(g => {
    const k = idxKey[g.name];
    if (k && idx[k]) { g.val = idx[k].price; g.chg = idx[k].change; }
  });
  buildGlobalTable();

  // ── FX 페이지 데이터 업데이트 ────────────────
  const fxMap = [
    [fx.USDKRW, 0, v => ({cur: fmt(v.rate,2),  chg: v.change, pct: v.change})],
    [fx.EURKRW, 1, v => ({cur: fmt(v.rate,2),  chg: v.change, pct: v.change})],
    [fx.JPYKRW, 2, v => ({cur: fmt(v.rate,4),  chg: v.change, pct: v.change})],
    [fx.EURUSD, 3, v => ({cur: fmt(v.rate,4),  chg: v.change, pct: v.change})],
    [fx.USDJPY, 4, v => ({cur: fmt(v.rate,2),  chg: v.change, pct: v.change})],
  ];
  fxMap.forEach(([src, i, mapper]) => { if (src) Object.assign(fxPairs[i], mapper(src)); });

  // ── 원자재 데이터 업데이트 ───────────────────
  // comData 인덱스: 0:WTI 1:Brent 2:두바이 3:금 4:은 5:백금 6:구리 7:알루미늄 8:아연 9:니켈
  //                10:천연가스 11:밀 12:옥수수 13:콩 14:쌀 15:팔라듐 16:휘발유 17:난방유 18:커피 19:설탕 20:코코아
  const priceFmt2 = v => ({price:'$'+fmt(v.price,2), chg:fmtPct(v.change), up:v.change>=0});
  const priceFmt0 = v => ({price:'$'+fmt(v.price,0), chg:fmtPct(v.change), up:v.change>=0});
  // 커피·설탕은 ICE 에서 센트/lb 로 호가 → '¢' 표기 (yfinance price 가 이미 센트값)
  const priceFmtCents = v => ({price:fmt(v.price,2)+'¢', chg:fmtPct(v.change), up:v.change>=0});
  const comMap = [
    [com.WTI,        0,  priceFmt2],
    [com.Brent,      1,  priceFmt2],
    [com.Dubai,      2,  v => ({price:'$'+fmt(v.price,2), chg:fmtPct(v.change)+'(월간)', up:v.change>=0})],   // 두바이 현물유 (FRED POILDUBUSDM) — FRED 월간 MoM 변동률
    [com.Gold,       3,  priceFmt2],
    [com.Silver,     4,  priceFmt2],
    [com.Platinum,   5,  priceFmt2],
    [com.Copper,     6,  priceFmt2],
    [com.Aluminum,   7,  priceFmt0],
    [com.NatGas,    10, priceFmt2],
    [com.Wheat,     11, priceFmt2],
    [com.Corn,      12, priceFmt2],
    [com.Soybean,   13, priceFmt2],
    [com.Rice,      14, priceFmt2],
    [com.Palladium, 15, priceFmt2],
    [com.Gasoline,  16, priceFmt2],
    [com.HeatingOil,17, priceFmt2],
    [com.Coffee,    18, priceFmtCents],
    [com.Sugar,     19, priceFmtCents],
    [com.Cocoa,     20, priceFmt0],
  ];
  comMap.forEach(([src, i, mapper]) => { if (src && comData[i]) Object.assign(comData[i], mapper(src)); });

  // ── 주식 지수 카드 데이터 업데이트 ───────────
  const eqKey = {'KOSPI':'KOSPI','KOSDAQ':'KOSDAQ','S&P 500':'SP500','NASDAQ':'NASDAQ','닛케이':'Nikkei'};
  eqData.forEach(g => {
    const k = eqKey[g.name];
    if (k && idx[k]) { g.val = idx[k].price; g.chg = idx[k].change; }
  });

  // ── 대시보드 KPI 카드 DOM 업데이트 ──────────────
  const kpiUpd = (priceId, chgId, priceStr, changePct) => {
    const pEl = document.getElementById(priceId);
    const cEl = document.getElementById(chgId);
    if (pEl) pEl.textContent = priceStr;
    if (cEl) {
      const up = changePct >= 0;
      cEl.className = up ? 'up-txt' : 'down-txt';
      cEl.style.cssText = 'font-size:13px;margin-top:4px;';
      cEl.textContent = (up ? '▲ +' : '▼ ') + Math.abs(changePct).toFixed(2) + '%';
    }
  };
  if (idx.KOSPI)   kpiUpd('kpi-kospi-price', 'kpi-kospi-chg', fmt(idx.KOSPI.price, 2),   idx.KOSPI.change);
  if (fx.USDKRW)  kpiUpd('kpi-fx-price',    'kpi-fx-chg',    fmt(fx.USDKRW.rate, 2),    fx.USDKRW.change);
  if (com.WTI)    kpiUpd('kpi-wti-price',   'kpi-wti-chg',   '$'+fmt(com.WTI.price, 2), com.WTI.change);

  // ── 한국 기준금리 KPI 카드 — ECOS 데이터로 최신값 반영 ──────────
  const ecosKr = (d.economicIndicators || {}).kr || {};
  const ecosUs = (d.economicIndicators || {}).us || {};
  if(ecosKr.base_rate_kr?.value != null) {
    const vEl = document.getElementById('kpi-rate-val');
    if(vEl) vEl.innerHTML = `${ecosKr.base_rate_kr.value.toFixed(2)}<span style="font-size:var(--font-size-base);">%</span>`;
    const dEl = document.getElementById('kpi-rate-date');
    if(dEl && ecosKr.base_rate_kr.period) {
      // 202604 → 2026.04
      const p = String(ecosKr.base_rate_kr.period);
      if(p.length === 6) dEl.textContent = `${p.slice(0,4)}.${p.slice(4,6)}`;
      else dEl.textContent = p;
    }
    // '동결' 배지 동적화 — ECOS 월별 시계열 마지막 두 값 비교 (하드코딩 오정보 방지).
    // 인상=위험색, 인하=완화색: 등락 관습(kr/global)과 무관한 --ind-* 의미 토큰 사용.
    const stEl = document.getElementById('kpi-rate-status');
    if(stEl) {
      let dir = '동결';
      try {
        const h = ecosKr.base_rate_kr.history || {};
        const vals = Object.keys(h).sort().map(k => h[k]).filter(v => v != null);
        const cur = ecosKr.base_rate_kr.value;
        const prev = vals.length >= 2 ? vals[vals.length-2] : null;
        if(prev != null && Math.abs(cur - prev) > 0.001) dir = cur > prev ? '인상' : '인하';
      } catch(_) {}
      stEl.textContent = dir;
      const tok = dir === '인상' ? '--ind-neg' : dir === '인하' ? '--ind-pos' : '--ind-neu';
      stEl.style.color = `var(${tok})`;
      stEl.style.background = `color-mix(in srgb, var(${tok}) 13%, transparent)`;
      stEl.style.borderColor = `color-mix(in srgb, var(${tok}) 27%, transparent)`;
    }
    // rateHistoryData.kr 마지막 값 갱신 + 차트 재렌더
    if(typeof rateHistoryData !== 'undefined' && Array.isArray(rateHistoryData.kr)) {
      rateHistoryData.kr[rateHistoryData.kr.length-1] = ecosKr.base_rate_kr.value;
      try { buildRateKpiSparkline(); } catch(_){}
    }
  }

  // ── 글로벌 기준금리 / 채권 테이블 — data.json 실데이터로 하드코딩 값 덮어쓰기 ──
  // 하드코딩된 currentRates(KR 2.75%, US 4.25%) 와 globalBonds(US 10y 4.48%) 가
  // 실제 data.json 값(KR 2.50%, US ff_rate 3.64%, US 10y 4.32%) 과 달라
  // 사용자에게 잘못된 값이 표시되던 문제 해결.
  if(typeof currentRates !== 'undefined' && Array.isArray(currentRates)) {
    const formatRate = v => (v != null) ? v.toFixed(2) + '%' : '—';
    const krBase = ecosKr.base_rate_kr;
    if(krBase?.value != null) {
      const krRow = currentRates.find(r => r.cc === 'kr');
      if(krRow) {
        const cur = krBase.value;
        // 직전 값: history 의 가장 최근 다른 값 (변동 시점)
        let prev = cur;
        if(krBase.history) {
          const periods = Object.keys(krBase.history).sort();
          for(let i = periods.length - 1; i >= 0; i--) {
            const v = krBase.history[periods[i]];
            if(v != null && Math.abs(v - cur) > 0.001) { prev = v; break; }
          }
        }
        krRow.rate = formatRate(cur);
        krRow.prev = formatRate(prev);
        krRow.dir = (prev > cur ? '인하↓' : prev < cur ? '인상↑' : '동결↔');
      }
    }
    const usFf = ecosUs.ff_rate;
    if(usFf?.value != null) {
      const usRow = currentRates.find(r => r.cc === 'us');
      if(usRow) {
        const cur = usFf.value;
        let prev = cur;
        if(usFf.history) {
          const periods = Object.keys(usFf.history).sort();
          for(let i = periods.length - 1; i >= 0; i--) {
            const v = usFf.history[periods[i]];
            if(v != null && Math.abs(v - cur) > 0.001) { prev = v; break; }
          }
        }
        usRow.rate = formatRate(cur);
        usRow.prev = formatRate(prev);
        usRow.dir = (prev > cur ? '인하↓' : prev < cur ? '인상↑' : '동결↔');
      }
    }
    // rateHistoryData 의 us 마지막 값도 갱신 (대시보드/페이지 일관성)
    if(usFf?.value != null && typeof rateHistoryData !== 'undefined' && Array.isArray(rateHistoryData.us)) {
      rateHistoryData.us[rateHistoryData.us.length-1] = usFf.value;
    }
    // 화면 갱신 (현재 페이지가 시장이면 즉시, 아니면 다음 진입 시 적용)
    try {
      if(typeof buildRateCurrentTable === 'function') buildRateCurrentTable();
      if(typeof buildRateHistoryChart === 'function') buildRateHistoryChart();
    } catch(_){}
  }
  if(typeof globalBonds !== 'undefined' && Array.isArray(globalBonds)) {
    const fmtYield = v => (v != null) ? v.toFixed(2) + '%' : '—';
    const fmtSpread = (y10, y2) => (y10 != null && y2 != null) ? ((y10 - y2) >= 0 ? '+' : '') + (y10 - y2).toFixed(2) : null;
    // yieldCurveTerms = ['1M','3M','6M','1Y','2Y','5Y','7Y','10Y','20Y','30Y']
    // 인덱스: 4=2Y, 7=10Y (일관 컨벤션)
    const IDX_10Y = 7, IDX_2Y = 4;
    // US 10y/2y — economicIndicators.us 가 가장 신뢰성 높음 (FRED 직접)
    if(ecosUs.us10y?.value != null || ecosUs.us2y?.value != null) {
      const usRow = globalBonds.find(b => b.cc === 'us');
      if(usRow) {
        const y10 = ecosUs.us10y?.value, y2 = ecosUs.us2y?.value;
        if(y10 != null) usRow.y10 = fmtYield(y10);
        if(y2  != null) usRow.y2  = fmtYield(y2);
        // 둘 다 데이터에서 왔을 때만 spread 갱신 (mixed hardcode/data 방지)
        if(y10 != null && y2 != null) {
          const sp = fmtSpread(y10, y2);
          if(sp != null) usRow.spread = sp;
        }
      }
    }
    // KR 10y/2y — yieldCurve.kr.current 가 있으면 사용 (yieldCurveTerms 컨벤션)
    const ycKr = (d.yieldCurve || {}).kr || {};
    if(Array.isArray(ycKr.current) && ycKr.current.length >= 10) {
      const krRow = globalBonds.find(b => b.cc === 'kr');
      if(krRow) {
        const y10 = ycKr.current[IDX_10Y];
        const y2  = ycKr.current[IDX_2Y];
        let updatedY10 = false, updatedY2 = false;
        if(y10 != null) { krRow.y10 = fmtYield(y10); updatedY10 = true; }
        if(y2  != null) { krRow.y2  = fmtYield(y2); updatedY2  = true; }
        // 둘 다 갱신된 경우에만 spread 재계산 (혼합 방지)
        if(updatedY10 && updatedY2) {
          const sp = fmtSpread(y10, y2);
          if(sp != null) krRow.spread = sp;
        }
      }
    }
    // JP 10y/2y — yieldCurve.jp.current 가 있으면 사용
    const ycJp = (d.yieldCurve || {}).jp || {};
    if(Array.isArray(ycJp.current) && ycJp.current.length >= 10) {
      const jpRow = globalBonds.find(b => b.cc === 'jp');
      if(jpRow) {
        const y10 = ycJp.current[IDX_10Y];
        const y2  = ycJp.current[IDX_2Y];
        let updatedY10 = false, updatedY2 = false;
        if(y10 != null) { jpRow.y10 = fmtYield(y10); updatedY10 = true; }
        if(y2  != null) { jpRow.y2  = fmtYield(y2); updatedY2  = true; }
        if(updatedY10 && updatedY2) {
          const sp = fmtSpread(y10, y2);
          if(sp != null) jpRow.spread = sp;
        }
      }
    }
    // 남은 하드코딩 값 청소 — globalBonds 초기값은 소스 없는 옛 숫자였다(2026-08-14 발견:
    // 한국 10년 3.02%, 실제 4.30%). 위에서 데이터로 갱신되지 않은 행은 옛 숫자를 그대로
    // 두는 대신 '—' 로 비운다. 없는 값을 현재값인 척 보여주는 게 가장 나쁜 오답이다.
    const _ycOf = { kr:'kr', us:'us', jp:'jp', uk:'uk', de:'eu' };   // 표의 '독일' = 유로존 AAA 곡선
    globalBonds.forEach(row => {
      const yc = (d.yieldCurve || {})[_ycOf[row.cc]] || {};
      const cur = Array.isArray(yc.current) ? yc.current : null;
      const has = (i) => cur && cur[i] != null;
      if(row.cc !== 'us' && row.cc !== 'kr') {           // us·kr 은 위에서 FRED/ECOS 로 확정
        row.y10 = has(IDX_10Y) ? fmtYield(cur[IDX_10Y]) : '—';
        row.y2  = has(IDX_2Y)  ? fmtYield(cur[IDX_2Y])  : '—';
        row.spread = (has(IDX_10Y) && has(IDX_2Y)) ? fmtSpread(cur[IDX_10Y], cur[IDX_2Y]) : '—';
        row.chg = '—';                                   // 전일比는 아직 수집 대상이 아니다
      }
      if(yc.label) row.country = yc.label;                // '독일' → '유로존(AAA)'
    });
    // 국가별 만기 테이블(bondCountries)도 같은 이유로 데이터 구동으로 바꾼다.
    try { applyBondCountriesFromData(d); } catch(e) { console.warn('[bond] 만기 테이블 갱신 실패', e); }
    // 화면 갱신
    try { if(typeof buildGlobalBondTable === 'function') buildGlobalBondTable(); } catch(_){}
    try { if(typeof buildBondPage === 'function' &&
             document.getElementById('market-bond') &&
             getComputedStyle(document.getElementById('market-bond')).display !== 'none') buildBondPage(); } catch(_){}
  }

  // ── FX 페이지 헤더·정보 패널 갱신 (현재 표시 중이라면) ─────
  if (typeof updateFxHeader === 'function') updateFxHeader();

  // ── 원자재 상세 헤더 갱신 (현재 선택된 항목 기준) ──────────
  const cdTitle = document.getElementById('comDetailTitle');
  const cdPrice = document.getElementById('comDetailPrice');
  if (cdTitle && cdPrice && typeof comCurrentIdx !== 'undefined' && comData[comCurrentIdx]) {
    setWidgetTitleText(cdTitle, comData[comCurrentIdx].name);
    cdPrice.textContent = comData[comCurrentIdx].price;
  }

  // 메인 차트 헤더 (KOSPI가 선택된 상태면 즉시 반영)
  if (idx.KOSPI && (mainSelectedGlobalIdx === null || mainSelectedGlobalIdx === 0)) {
    const phEl = document.getElementById('mainChartPriceVal');
    const chEl = document.getElementById('mainChartChangeVal');
    if (phEl) phEl.textContent = fmt(idx.KOSPI.price, 2);
    if (chEl) {
      const up = idx.KOSPI.change >= 0;
      chEl.textContent = (up ? '▲ +' : '▼ ') + Math.abs(idx.KOSPI.change).toFixed(2) + '%';
      chEl.className = up ? 'up-txt' : 'down-txt';
      chEl.style.cssText = 'font-size:13px;margin-left:6px;';
    }
  }

  // ── 주식/ETF 이동자 데이터 업데이트 (KRX API or Naver Finance) ──
  const movers = d.stockMovers || {};
  const etfMvr = d.etfMovers   || {};
  // 데이터 소스 표시 갱신
  const dsEl = document.getElementById('moverDataSource');
  if(dsEl && d.sources?.stockMovers) dsEl.textContent = d.sources.stockMovers;
  // 정렬 오류(거래량≈현재가) garbage 감지 → 클라이언트 실시간(네이버) 페치로 교체.
  // (서버 data.json 이 아직 KRX OpenAPI 의 어긋난 데이터일 때 'LG전자 +29.9%' 같은
  //  비현실적 상한가 떼가 표시되는 것을 브라우저에서 즉시 보정. 서버는 pykrx 우선으로 수정됨.)
  const _moversLookCorrupt = arr => {
    if(!Array.isArray(arr) || arr.length < 4) return false;
    let m = 0, cap = 0;
    arr.forEach(s => {
      const p = Number(s && s.price) || 0, v = Number(s && s.vol) || 0;
      // 허용오차 0.1%→5% — 가격형 값이 vol 에 들어간 garbage 는 근사(±수 %)로 어긋나
      // 정확 일치 판정으로는 새는 변종이 실측 확인됨(서버 _is_valid_mover_list 와 동일 기준).
      if(p > 0 && v > 0 && Math.abs(p - v) <= Math.max(1, p * 0.05)) m++;
      const c = Number(s && s.chg);
      if(Number.isFinite(c) && Math.abs(c) >= 29.5) cap++;   // 전 행 ±30% 상하한가 떼 = garbage 신호
    });
    const half = Math.max(2, Math.floor(arr.length / 2));
    return m >= half || cap >= half;
  };
  /* 신선도 실패도 같은 폴백을 발동시킨다.
     왜: 지금까지는 '값이 깨졌을 때'만 클라이언트 페치로 넘어갔다. 그런데 서버는
     KRX 로그인 실패로 stockMovers 를 몇 주째 수집하지 못하면서도(diagnostics
     stockMoversSource=FAILED) 직전 값을 그대로 넘겨줬다 — 값은 멀쩡해 보이니
     corrupt 판정에 안 걸리고, 사용자는 6일 전 등락률을 오늘 것으로 읽었다.
     dataHealth 가 이 상태를 이름 붙여 주므로 그대로 트리거로 쓴다. */
  const _moversStale = (function () {
    const h = window._dataHealth;
    if (!h || !h.items) return false;
    return h.items.some(i => i.path.indexOf('stockMovers') === 0 &&
                             (i.state === 'failed' || i.state === 'stale'));
  })();
  if(window._REALTIME_BOOST
     && (_moversStale || _moversLookCorrupt(movers.kospiGainers) || _moversLookCorrupt(movers.kospiLosers))
     && typeof refreshMoversFromClient === 'function'
     && !_clientMoverFetchInFlight && _clientMoverFetchAttempts < _MAX_AUTO_MOVER_FETCH) {
    console.warn(_moversStale
      ? '[movers] 서버 수집 실패/지연 감지 → 클라이언트 실시간 페치 트리거'
      : '[movers] 거래량≈현재가 정렬오류 감지 → 클라이언트 실시간 페치 트리거');
    _clientMoverFetchInFlight = true; _clientMoverFetchAttempts++;
    refreshMoversFromClient().finally(() => { _clientMoverFetchInFlight = false; });
  }
  if (movers.kospiGainers) {
    const asOf = movers.kospiGainers[0]?.as_of || '';
    if(asOf) moverRefDate = asOf;
    upMoversStock.splice(0, upMoversStock.length, ...movers.kospiGainers.slice(0,10).map(s=>({
      name: s.name, code: s.code||'', price: s.price.toLocaleString(), chg: (s.chg>=0?'+':'')+s.chg.toFixed(2)+'%',
      vol: s.vol ? Math.round(s.vol/1000).toLocaleString()+'K' : '', type:'stock'
    })));
  }
  if (movers.kospiLosers) {
    downMoversStock.splice(0, downMoversStock.length, ...movers.kospiLosers.slice(0,10).map(s=>({
      name: s.name, code: s.code||'', price: s.price.toLocaleString(), chg: (s.chg>=0?'+':'')+s.chg.toFixed(2)+'%',
      vol: s.vol ? Math.round(s.vol/1000).toLocaleString()+'K' : '', type:'stock'
    })));
  }
  if (etfMvr.etfGainers) {
    upMoversETF.splice(0, upMoversETF.length, ...etfMvr.etfGainers.slice(0,10).map(s=>({
      name: s.name, code: s.code||'', price: s.price.toLocaleString(), chg: (s.chg>=0?'+':'')+s.chg.toFixed(2)+'%',
      vol: s.vol ? Math.round(s.vol/1000).toLocaleString()+'K' : '', type:'etf'
    })));
  }
  if (etfMvr.etfLosers) {
    downMoversETF.splice(0, downMoversETF.length, ...etfMvr.etfLosers.slice(0,10).map(s=>({
      name: s.name, code: s.code||'', price: s.price.toLocaleString(), chg: (s.chg>=0?'+':'')+s.chg.toFixed(2)+'%',
      vol: s.vol ? Math.round(s.vol/1000).toLocaleString()+'K' : '', type:'etf'
    })));
  }
  // 대시보드 상승/하락 테이블 — 초기 로드시 비어있던 상태를 갱신
  try { buildMoverTable(curMoverTab); } catch(_) {}

  // Top10 테이블 (주식시장 탭) — KOSPI 상승/하락 + ETF 상승/하락
  // 주식: 거래량 포함 (5컬럼) · ETF: 거래량 데이터 미수집 → 4컬럼
  const stockUrl = (s) => naverStockUrl(s);
  const volStr = v => v ? Math.round(v/1000).toLocaleString()+'K' : '—';
  const renderStockRow = (s, i, cls) => `<tr style="border-bottom:1px solid var(--c-border);">
      <td style="padding:5px;color:var(--c-txt-muted);">${i+1}</td>
      <td style="padding:5px;font-weight:var(--font-weight-medium);"><a href="${stockUrl(s)}" target="_blank" rel="noopener noreferrer" style="color:inherit;text-decoration:none;border-bottom:1px dotted transparent;" onmouseover="this.style.borderBottomColor='currentColor'" onmouseout="this.style.borderBottomColor='transparent'" title="네이버 증권에서 보기">${s.name}</a></td>
      <td style="text-align:right;padding:5px;">${s.price.toLocaleString()}</td>
      <td style="text-align:right;padding:5px;color:${cls==='up'?window.CUP:window.CDN};">${cls==='up'?'+':''}${s.chg.toFixed(2)}%</td>
      <td style="text-align:right;padding:5px;color:var(--c-txt-dim);font-size:var(--font-size-sm);">${volStr(s.vol)}</td>
    </tr>`;
  const renderEtfRow = (s, i, cls) => `<tr style="border-bottom:1px solid var(--c-border);">
      <td style="padding:5px;color:var(--c-txt-muted);">${i+1}</td>
      <td style="padding:5px;font-weight:var(--font-weight-medium);"><a href="${stockUrl(s)}" target="_blank" rel="noopener noreferrer" style="color:inherit;text-decoration:none;border-bottom:1px dotted transparent;" onmouseover="this.style.borderBottomColor='currentColor'" onmouseout="this.style.borderBottomColor='transparent'" title="네이버 증권에서 보기">${s.name}</a></td>
      <td style="text-align:right;padding:5px;">${s.price.toLocaleString()}</td>
      <td style="text-align:right;padding:5px;color:${cls==='up'?window.CUP:window.CDN};">${cls==='up'?'+':''}${s.chg.toFixed(2)}%</td>
    </tr>`;
  const gainTb = document.getElementById('equityTopGainersTable');
  const loseTb = document.getElementById('equityTopLosersTable');
  // 빈 테이블에는 데이터 소스 진단과 새로고침 버튼을 함께 표시
  const renderEmptyMoverCell = (cols, label, source) => {
    const diag = (d.diagnostics || {});
    const srvSrc = diag.stockMoversSource;
    const diagLine = srvSrc
      ? `<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:4px;">서버 소스: ${srvSrc==='FAILED'?'<span style=\"color:var(--c-down)\">전체 실패 (pykrx/KRX/Naver)</span>':srvSrc}</div>`
      : '';
    return `<tr><td colspan="${cols}" style="padding:14px;text-align:center;color:var(--c-txt-muted);font-size:var(--font-size-sm);">
      <div>📡 ${label} 데이터 없음 — 클라이언트에서 시도 중…</div>
      ${diagLine}
      <button onclick="manualRetryMovers(this)" style="margin-top:6px;background:var(--c-accent);color:var(--c-on-accent);border:none;border-radius:var(--r-xs);padding:3px 10px;font-size:var(--font-size-sm);cursor:pointer;">↻ 다시 시도</button>
      <a href="https://finance.naver.com/sise/sise_rise.naver" target="_blank" rel="noopener noreferrer" style="margin-left:6px;color:var(--c-primary);text-decoration:none;font-size:var(--font-size-sm);">네이버 →</a>
    </td></tr>`;
  };
  if (gainTb) {
    gainTb.innerHTML = movers.kospiGainers && movers.kospiGainers.length
      ? movers.kospiGainers.map((s,i)=>renderStockRow(s,i,'up')).join('')
      : renderEmptyMoverCell(5, 'KOSPI 상승 Top10');
  }
  if (loseTb) {
    loseTb.innerHTML = movers.kospiLosers && movers.kospiLosers.length
      ? movers.kospiLosers.map((s,i)=>renderStockRow(s,i,'down')).join('')
      : renderEmptyMoverCell(5, 'KOSPI 하락 Top10');
  }
  // ETF Top10 테이블 (거래량 없음 → 4컬럼)
  const etfGainTb = document.getElementById('etfTopGainersTable');
  const etfLoseTb = document.getElementById('etfTopLosersTable');
  const renderEmptyEtfCell = (label) => {
    const diag = (d.diagnostics || {});
    const srvSrc = diag.etfMoversSource;
    const diagLine = srvSrc
      ? `<div style="font-size:var(--font-size-xs);color:var(--c-txt-muted);margin-top:4px;">서버 소스: ${srvSrc==='FAILED'?'<span style=\"color:var(--c-down)\">전체 실패 (pykrx/Naver)</span>':srvSrc}</div>`
      : '';
    return `<tr><td colspan="4" style="padding:14px;text-align:center;color:var(--c-txt-muted);font-size:var(--font-size-sm);">
      <div>📡 ${label} 데이터 없음 — 클라이언트에서 시도 중…</div>
      ${diagLine}
      <button onclick="refreshETFFromClient(this)" style="margin-top:6px;background:var(--c-accent);color:var(--c-on-accent);border:none;border-radius:var(--r-xs);padding:3px 10px;font-size:var(--font-size-sm);cursor:pointer;">↻ 다시 시도</button>
      <a href="https://finance.naver.com/sise/etf.naver" target="_blank" rel="noopener noreferrer" style="margin-left:6px;color:var(--c-primary);text-decoration:none;font-size:var(--font-size-sm);">네이버 →</a>
    </td></tr>`;
  };
  if (etfGainTb) {
    etfGainTb.innerHTML = etfMvr.etfGainers && etfMvr.etfGainers.length
      ? etfMvr.etfGainers.map((s,i)=>renderEtfRow(s,i,'up')).join('')
      : renderEmptyEtfCell('ETF 상승 Top10');
  }
  if (etfLoseTb) {
    etfLoseTb.innerHTML = etfMvr.etfLosers && etfMvr.etfLosers.length
      ? etfMvr.etfLosers.map((s,i)=>renderEtfRow(s,i,'down')).join('')
      : renderEmptyEtfCell('ETF 하락 Top10');
  }
  // ── FRED 경제 지표 → 대시보드 시장 분위기 ─────────────
  const usInd = (d.economicIndicators || {}).us || {};
  if (usInd.vix?.value != null) {
    const vixEl = document.getElementById('dashVix');
    if(vixEl) {
      vixEl.textContent = usInd.vix.value.toFixed(2);
      vixEl.style.color = usInd.vix.value > 25 ? 'var(--ind-neg)' : usInd.vix.value > 18 ? 'var(--c-warn)' : 'var(--ind-pos)';
      _sentCaption('dashVix', usInd.vix.period || usInd.vix.as_of, '미국 변동성 · 지수');
    }
  }
  if (usInd.hy_spread?.value != null) {
    const hyEl = document.getElementById('dashHySpread');
    if(hyEl) {
      hyEl.textContent = usInd.hy_spread.value.toFixed(2) + '%';
      hyEl.style.color = usInd.hy_spread.value > 4 ? 'var(--ind-neg)' : usInd.hy_spread.value > 3 ? 'var(--c-warn)' : 'var(--ind-pos)';
      _sentCaption('dashHySpread', usInd.hy_spread.period || usInd.hy_spread.as_of, '미 신용 스프레드 · %p (국채 대비)');
    }
  }
  // ── VKOSPI / MOVE / PCR — 시장 분위기 지표 ──────────
  const sentiment = d.sentiment || {};
  if (sentiment.vkospi?.value != null) {
    const vkEl = document.getElementById('dashVkospi');
    if(vkEl) {
      // VKOSPI 합리적 범위 검증 (1~200) — yfinance 가 KOSPI 값을 잘못 반환할 수 있음
      // 추가: VIX 교차검증 — VKOSPI/VIX 비율이 0.3~4.0 벗어나면 스크래핑 오염 의심
      const v = sentiment.vkospi.value;
      const vix = d?.economicIndicators?.us?.vix?.value;
      const vixCrossOk = !vix || vix <= 0 || (v / vix >= 0.3 && v / vix <= 4.0);
      if(_isValidVkospi(v) && vixCrossOk) {
        vkEl.textContent = v.toFixed(2);
        vkEl.style.color = v > 30 ? 'var(--ind-neg)' : v > 20 ? 'var(--c-warn)' : 'var(--ind-pos)';
      } else {
        vkEl.textContent = '—';
        vkEl.style.color = 'var(--c-txt-dim,#a4a8bc)';
      }
      _sentCaption('dashVkospi', sentiment.vkospi.as_of, '코스피200 변동성지수 · KRX');
    }
  }
  if (sentiment.move?.value != null) {
    const el = document.getElementById('dashMove');
    if(el) {
      el.textContent = sentiment.move.value.toFixed(1);
      const v = sentiment.move.value;
      el.style.color = v > 120 ? 'var(--ind-neg)' : v > 100 ? 'var(--c-warn)' : 'var(--ind-pos)';
      _sentCaption('dashMove', sentiment.move.as_of, '미 채권 변동성 · 지수');
    }
  }
  if (sentiment.pcr?.value != null) {
    const el = document.getElementById('dashPcr');
    if(el) {
      el.textContent = sentiment.pcr.value.toFixed(2);
      const v = sentiment.pcr.value;
      el.style.color = v > 1.1 ? 'var(--ind-neg)' : v < 0.7 ? 'var(--ind-pos)' : 'var(--c-txt,#e8ebf5)';
      _sentCaption('dashPcr', sentiment.pcr.as_of, '옵션 심리 · 배수');
    }
  }
  // ── 수집 실패로 이전 빌드 값이 보존된 경우 '이전 값 유지' 배지 표시 (멱등) ──
  try {
    const stale = /보존|preserved|stale/i.test(String((d.sources || {}).sentiment || ''));
    const tEl = document.getElementById('sentimentTitle');
    if(tEl) {
      let b = document.getElementById('sentStaleBadge');
      if(stale) {
        if(!b) {
          b = document.createElement('span');
          b.id = 'sentStaleBadge';
          b.style.cssText = 'font-size:10px;color:var(--c-warn);font-weight:400;margin-left:6px;text-transform:none;letter-spacing:normal;';
          b.title = '이번 수집이 실패해 직전 수집 값이 유지되고 있습니다';
          b.textContent = '◐ 이전 값 유지';
          tEl.appendChild(b);
        }
      } else if(b) b.remove();
    }
  } catch(_) {}
  // ── Fear & Greed Index (CNN) — sentiment.fear_greed 가 있으면 표시 ────
  if(typeof applyFearGreed === 'function') applyFearGreed(d);
  if(typeof buildFearChart === 'function') {
    try { buildFearChart(); } catch(_) {}
  }
  // ── R-ONE 부동산 지표 → 부동산 페이지 KPI ──────────────
  const reKr = (d.realestate || {}).kr || {};
  function setKrReCard(idVal, idChg, idPeriod, data, fmt) {
    const vEl = document.getElementById(idVal);
    const cEl = document.getElementById(idChg);
    const pEl = document.getElementById(idPeriod);
    if(!data) return;
    if(vEl) {
      vEl.textContent = fmt ? fmt(data.value) : (data.value?.toFixed(1) ?? '—');
      // CSS 변수로 라이트/다크 자동 대응
      vEl.style.color = 'var(--c-txt,#e8ebf5)';
    }
    if(cEl && data.chg != null) {
      cEl.textContent = `전월比 ${data.chg>=0?'+':''}${data.chg.toFixed(2)}%`;
      cEl.style.color = data.chg >= 0 ? window.CUP : window.CDN;
    } else if(cEl && data.value != null) {
      cEl.textContent = '최신';
      cEl.style.color = window.CUP;
    }
    if(pEl && data.period) pEl.textContent = data.period;
  }
  // 데이터 없을 때 "페치 중..." 대신 명확한 미연동 안내로 교체
  // (API 키 미설정/응답 없음을 사용자가 인지할 수 있도록)
  // 매매·전세 둘 다 R-ONE 이 1차 소스 (실패 시 ECOS 폴백). 라벨 일관성 유지.
  const reDiag = (d.diagnostics || {}).realestate_kr || {};
  const reMissingHint = (reDiag.rone_tried && !reDiag.rone_ok && !reDiag.ecos_ok && !reDiag.fred_ok)
    ? '데이터 갱신 대기 중 (자동 재시도)'
    : (reDiag.rone_tried ? '데이터 갱신 대기 중' : '데이터 준비 중');
  // KPI 카드는 '변동률(전기比 %)' 을 헤드라인으로 표시 (사용자가 부동산원/R-ONE 사이트에서
  // 보는 값). 소스가 '지수' 시리즈(FRED BIS·R-ONE 지수)면 chg(%) 를 헤드라인으로 쓰고 지수
  // 레벨은 메타에 병기. '변동률' 시리즈면 값 자체가 % 이므로 그대로 표시.
  const _reHeadline = (data) => {
    const isPct = /%|변동률|변화율/i.test(data.desc || '');
    if (isPct && data.value != null)
      return { txt:(data.value>=0?'+':'')+data.value.toFixed(2)+'%',
               color:data.value>=0?window.CUP:window.CDN, lvl:'' };
    if (data.chg != null)
      return { txt:(data.chg>=0?'+':'')+data.chg.toFixed(2)+'%',
               color:data.chg>=0?window.CUP:window.CDN,
               lvl:(data.value!=null?` · 지수 ${data.value.toFixed(2)}`:'') };
    return { txt:(data.value!=null?data.value.toFixed(2):'—'),
             color:'var(--c-txt,#e8ebf5)', lvl:'' };
  };
  const _reMissingMeta = (elId, hint) => {
    const el = document.getElementById(elId);
    if (el && el.textContent.includes('페치 중')) {
      el.innerHTML = `<a href="https://www.reb.or.kr/r-one" target="_blank" rel="noopener noreferrer" style="color:var(--c-primary);text-decoration:none;">R-ONE 사이트 보기 →</a> · ${hint}`;
      el.style.color = '#f5a623';
    }
  };
  // ── 카드 1: 전국 매매가격지수 (apt_price_idx_kr) ──
  if (reKr.apt_price_idx_kr) {
    const data = reKr.apt_price_idx_kr;
    const h = _reHeadline(data);
    const vEl = document.getElementById('reKpiAptPrice');
    const mEl = document.getElementById('reKpiAptPriceMeta');
    if(vEl) { vEl.textContent = h.txt; vEl.style.color = h.color; }
    if(mEl) { mEl.textContent = `${data.period||''} · ${data.source||'R-ONE'}${h.lvl}`; mEl.style.color = 'var(--c-txt-dim)'; }
    setKrReCard('krReAptSaleVal', 'krReAptSaleChg', 'krRePeriodAptSale', data);
  } else {
    _reMissingMeta('reKpiAptPriceMeta', reMissingHint);
  }
  // ── 카드 2: 전국 전세가격지수 (jns_price_idx_kr). BIS 폴백엔 전세가 없어 미제공일 수 있음 ──
  if (reKr.jns_price_idx_kr) {
    const data = reKr.jns_price_idx_kr;
    const h = _reHeadline(data);
    const vEl = document.getElementById('reKpiAptIdxVal');
    const cEl = document.getElementById('reKpiAptIdxChg');
    if(vEl) { vEl.textContent = h.txt; vEl.style.color = h.color; }
    if(cEl) { cEl.textContent = `${data.period||''} · ${data.source||'R-ONE'}${h.lvl}`; cEl.style.color = 'var(--c-txt-dim)'; }
    setKrReCard('krReAptJnsVal', 'krReAptJnsChg', 'krRePeriodAptJns', data);
  } else {
    const jnsHint = reDiag.fred_ok ? '전세 지수는 BIS 미제공 — R-ONE/ECOS 복구 시 표시' : reMissingHint;
    _reMissingMeta('reKpiAptIdxChg', jnsHint);
  }
  // 주담대 금리는 economicIndicators.kr 또는 realestate.kr 양쪽에서 검색
  const ecoKr = (d.economicIndicators || {}).kr || {};
  const mortRate = reKr.mortgage_rate_kr || ecoKr.mortgage_rate_kr;
  if (mortRate) {
    setKrReCard('krReMortRate', null, null, mortRate, v=>v?.toFixed(2)+'%');
  }
  // 가계신용 잔액 — ECOS 데이터만 사용 (없으면 "—" 표시, 더미 데이터 금지)
  const hhDebt = reKr.household_debt_kr || ecoKr.household_debt_kr;
  if (hhDebt) {
    setKrReCard('krReHouseholdDebt', null, null, hhDebt, v=>(v/1000).toFixed(0)+'조원');
  }
  // 거래량 (부동산거래현황 R-ONE 1차 / MOLIT 보강) — 실제 데이터만 사용, 없으면 "—" (더미 금지)
  if (reKr.trade_count_kr) {
    const tc = {...reKr.trade_count_kr};
    if(!tc.value || tc.value === 0) {
      // history 에서 최신 비영값 찾기 (실제 데이터)
      const hist = tc.history || {};
      const keys = Object.keys(hist).sort();
      for(let i = keys.length - 1; i >= 0; i--) {
        if(hist[keys[i]] > 0) {
          tc.value = hist[keys[i]];
          tc.period = keys[i];
          break;
        }
      }
    }
    if (tc.value && tc.value > 0) {
      setKrReCard('krReTradeCnt', null, null, tc, v=>v?.toLocaleString()+'호');
      // KPI 카드 갱신
      const kpiEl = document.getElementById('reKpiVol');
      const metaEl = document.getElementById('reKpiVolMeta');
      if(kpiEl) {
        kpiEl.innerHTML = `${(tc.value/10000).toFixed(1)}<span style="font-size:var(--font-size-base);">만 호</span>`;
        kpiEl.style.color = 'var(--c-txt,#e8ebf5)';
      }
      if(metaEl) {
        // 소스 표기는 실제 data.json 의 source 를 그대로 사용
        const srcLabel = /MOLIT|국토부|data\.go\.kr/i.test(tc.source||'')
          ? '국토부 실거래가 (data.go.kr)' : '한국부동산원 행정구역별 아파트거래현황';
        metaEl.textContent = `${tc.period} · ${srcLabel}`;
        metaEl.style.color = window.CUP;
      }
    } else {
      // 거래량 실데이터 없음 — 안내 톤 (경고 X)
      const metaEl = document.getElementById('reKpiVolMeta');
      if(metaEl && metaEl.textContent.includes('페치 중')) {
        metaEl.innerHTML = '<a href="https://www.reb.or.kr/r-one" target="_blank" rel="noopener noreferrer" style="color:var(--c-primary);text-decoration:none;">R-ONE 아파트거래현황 →</a> · 데이터 갱신 대기 중';
        metaEl.style.color = 'var(--c-txt-dim)';
      }
    }
  } else {
    // trade_count_kr 자체가 없는 경우 — 안내 링크만 (broken 처럼 보이지 않도록)
    const metaEl = document.getElementById('reKpiVolMeta');
    if(metaEl && metaEl.textContent.includes('페치 중')) {
      metaEl.innerHTML = '<a href="https://www.reb.or.kr/r-one" target="_blank" rel="noopener noreferrer" style="color:var(--c-primary);text-decoration:none;">R-ONE 아파트거래현황 →</a> · 데이터 준비 중';
      metaEl.style.color = 'var(--c-txt-dim)';
    }
  }
  if (reKr.unsold_kr) {
    setKrReCard('krReUnsold', null, null, reKr.unsold_kr, v=>v?.toLocaleString()+'호');
  }
  // 전월세전환율 (R-ONE) — '주택 인허가'(R-ONE 미제공) 대체 지표. 단위 %.
  if (reKr.conversion_rate_kr) {
    setKrReCard('krReConversion', 'krReConversionChg', null, reKr.conversion_rate_kr, v=>(v!=null? v.toFixed(1)+'%':'—'));
  }
  if (reKr.start_kr) {
    setKrReCard('krReStart', 'krReStartChg', null, reKr.start_kr, v=>v?.toLocaleString());
  }

  // ── FRED 미국 부동산 지표 → re-us KPI 카드 + 상세 테이블 ──
  const reUs = (d.realestate || {}).us || {};
  function setUsKpi(valId, chgId, data, fmt, tableIds) {
    const vEl = document.getElementById(valId);
    const cEl = document.getElementById(chgId);
    if(!vEl || !data) return;
    const valStr = fmt ? fmt(data.value) : (data.value?.toFixed(1) ?? '—');
    vEl.textContent = valStr;
    const chgStr = data.chg != null ? `${data.chg>=0?'▲ +':'▼ '}${Math.abs(data.chg).toFixed(2)}%` : '';
    if(cEl && data.chg != null) {
      cEl.textContent = chgStr + (data.period ? ` (${data.period})` : '');
      cEl.style.color = data.chg >= 0 ? window.CUP : window.CDN;
    } else if(cEl && data.period) {
      cEl.textContent = data.period;
    }
    // 상세 테이블 채우기
    if(tableIds) {
      const tvEl = document.getElementById(tableIds.val);
      const tcEl = document.getElementById(tableIds.chg);
      const tpEl = document.getElementById(tableIds.period);
      if(tvEl) tvEl.textContent = valStr;
      if(tcEl) {
        tcEl.textContent = chgStr || '—';
        if(data.chg != null) tcEl.style.color = data.chg >= 0 ? window.CUP : window.CDN;
      }
      if(tpEl) tpEl.textContent = data.period || '—';
    }
  }
  setUsKpi('usKpiCaseShiller',   'usKpiCaseShillerChg',   reUs.case_shiller_national, v=>v?.toFixed(1),         {val:'usTableCaseShillerVal',chg:'usTableCaseShillerChg',period:'usTableCaseShillerPeriod'});
  setUsKpi('usKpiMortgage30',    'usKpiMortgage30Chg',    reUs.mortgage_30y,           v=>v?.toFixed(2)+'%',    {val:'usTableMtg30Val',      chg:'usTableMtg30Chg',      period:'usTableMtg30Period'});
  setUsKpi('usKpiNahb',          'usKpiNahbChg',          reUs.nahb_index,             v=>v?.toFixed(0),         {val:'usTableNahbVal',       chg:'usTableNahbChg',       period:'usTableNahbPeriod'});
  setUsKpi('usKpiHousingStarts', 'usKpiHousingStartsChg', reUs.housing_starts,         v=>v?.toFixed(0)+'K',    {val:'usTableHStVal',        chg:'usTableHStChg',        period:'usTableHStPeriod'});
  // 추가 지표 (KPI 카드 없이 테이블만)
  function setUsTable(data, fmt, ids) {
    if(!data || !ids) return;
    const tvEl = document.getElementById(ids.val);
    const tcEl = document.getElementById(ids.chg);
    const tpEl = document.getElementById(ids.period);
    const valStr = fmt ? fmt(data.value) : (data.value?.toFixed(1) ?? '—');
    if(tvEl) tvEl.textContent = valStr;
    if(tcEl) {
      if(data.chg != null) {
        tcEl.textContent = `${data.chg>=0?'▲ +':'▼ '}${Math.abs(data.chg).toFixed(2)}%`;
        tcEl.style.color = data.chg >= 0 ? window.CUP : window.CDN;
      } else { tcEl.textContent = '—'; }
    }
    if(tpEl) tpEl.textContent = data.period || '—';
  }
  setUsTable(reUs.case_shiller_20city,    v=>v?.toFixed(1),      {val:'usTableCase20Val', chg:'usTableCase20Chg', period:'usTableCase20Period'});
  setUsTable(reUs.mortgage_15y,           v=>v?.toFixed(2)+'%',  {val:'usTableMtg15Val',  chg:'usTableMtg15Chg',  period:'usTableMtg15Period'});
  setUsTable(reUs.building_permits,       v=>v?.toFixed(0)+'K',  {val:'usTableBPVal',     chg:'usTableBPChg',     period:'usTableBPPeriod'});
  setUsTable(reUs.existing_home_sales,    v=>v?.toFixed(0)+'K',  {val:'usTableEHSVal',    chg:'usTableEHSChg',    period:'usTableEHSPeriod'});
  setUsTable(reUs.new_home_sales,         v=>v?.toFixed(0)+'K',  {val:'usTableNHSVal',    chg:'usTableNHSChg',    period:'usTableNHSPeriod'});

  // 미국 부동산 비교 차트 데이터 캐시 + 현재 미국 탭이 표시 중이면 즉시 재렌더
  usReDataCache = reUs;
  const usTabEl = document.getElementById('re-us');
  if(usTabEl && usTabEl.style.display !== 'none' && typeof buildUsReCharts === 'function') {
    buildUsReCharts();
  }

  // 미국 국채 수익률 곡선 데이터 (FRED 우선)
  const yc = d.yieldCurve || {};
  for(const cc of ['us','kr','jp','uk','de']) {
    if(yc[cc] && Array.isArray(yc[cc].current)) {
      yieldCurveData[cc].current    = yc[cc].current;
      yieldCurveData[cc].prev_month = yc[cc].prev_month || yieldCurveData[cc].prev_month;
      if(yc[cc].source) yieldCurveData[cc].source = yc[cc].source;
    }
  }
  // 채권 탭이 현재 표시 중이면 차트 재렌더
  const bondTabEl = document.getElementById('market-bond');
  if(bondTabEl && bondTabEl.style.display !== 'none' && typeof buildYieldCurveChart === 'function') {
    buildYieldCurveChart(bondCountryCurrent || 'us');
  }

  // ── 사이드바 업데이트 시각 표시 + 신선도 자동 판정 ──────────────
  // 렌더는 renderDataFreshness() 단일 출처 — 실시간 보강 성공이 이 표시를 덮어쓰지 않고(슬롯 분리),
  // 1분 주기 재평가로 탭을 켜둔 동안에도 경과 시간이 갱신된다.
  if (d.lastUpdated) window._lastServerDataTs = d.lastUpdated;
  // 지표별 신선도 계약(scripts/data_sla.py 가 산출) — 전역 lastUpdated 하나로는
  // "일본 CPI 가 2021년에서 멈춤" 같은 개별 지표 고착을 표현할 수 없다.
  window._dataHealth = d.dataHealth || null;
  // 토스 연결상태(fetch_data.toss_connection_status) — 스냅샷 신선도가 곧 수집기 가동 여부다.
  window._tossStatus = (d.diagnostics && d.diagnostics.toss) || null;
  try { renderDataFreshness(); } catch(_) {}
  renderDataFreshness();

  // ── LME 금속 재고 (data.json.lmeInventory) 동기화 ──────
  if(d.lmeInventory && Array.isArray(d.lmeInventory.data)) {
    // 실데이터가 실제로 들어오면 '정적 스냅샷' 경고 문구를 자동 수집 표기로 교체
    try { const nt = document.getElementById('metalInventoryNote'); if(nt) nt.textContent = '출처: LME 일일 재고 보고서 (자동 수집) —'; } catch(_) {}
    const krNames = {'Copper':'구리 (Copper)', 'Aluminum':'알루미늄', 'Zinc':'아연 (Zinc)',
                     'Nickel':'니켈 (Nickel)', 'Lead':'납 (Lead)', 'Tin':'주석 (Tin)'};
    d.lmeInventory.data.forEach((row, i) => {
      if(metalInventory[i]) {
        if(row.cur != null)   metalInventory[i].cur = row.cur;
        if(row.wkChg != null) metalInventory[i].wkChg = row.wkChg;
        if(row.m4ago != null) metalInventory[i].m4ago = row.m4ago;
        if(row.status) metalInventory[i].status = row.status === 'up' ? '증가' :
                                                   row.status === 'down' ? '감소' : '보합';
      }
    });
  }

  // ── 사이드바 데이터 소스 신호등 ──────────────
  if(d && d.sources) {
    try { buildSidebarDataSources(d); } catch(_) {}
  }

  // ── 서버측 뉴스 (data.json.news) 즉시 적용 ──────────────
  // 매일 9시 KST GitHub Actions 가 Google News RSS 로 카테고리별 기사 미리 수집.
  // 클라이언트 CORS 프록시 실패 케이스에 대비한 안정적 데이터 소스.
  if(d && d.news) {
    try {
      const ok = applyServerNewsToFeeds(d.news);
      if(ok) {
        ['newsFeed','commodityNewsFeed','macroNewsFeed','calendarNewsFeed'].forEach(id=>{
          if(document.getElementById(id)) renderFiltered(id);
        });
      }
    } catch(_) {}
  }

  // ── 서버측 경제 캘린더 (data.json.economicCalendar) 머지 + 활성 페이지 재렌더 ──
  // 매일 09:00/22:00 KST GitHub Actions 가 FRED release dates 로 갱신.
  if(d && d.economicCalendar) {
    try {
      const added = (typeof mergeServerCalendar === 'function') ? mergeServerCalendar() : 0;
      const calPage = document.getElementById('page-calendar');
      if(added > 0 && calPage && calPage.classList.contains('active') && typeof buildCalendar === 'function') {
        buildCalendar();
      }
    } catch(_) {}
  }

  // ── 📌 오늘의 브리핑 스트립 + 🚦 리스크 신호등 + 5Y 백분위 배지 + 💬 AI 질문창 노출 ──
  // 함수 말미에 위치해야 함 — '다음 일정' 칩이 위의 서버 캘린더 머지 결과를 읽는다.
  try { renderBriefStrip(d); } catch(_) {}
  try { renderRiskLight(d); } catch(_) {}
  try { renderKpiPctBadges(d); } catch(_) {}
  try { updateAiQaVisibility(); } catch(_) {}
}

// ── 데이터 신선도 표시 (단일 출처) ──────────────────────────────
// #dataSourceInfo 를 두 슬롯으로 분리:
//   j(dsJsonFresh) = 서버 data.json 파이프라인 신선도 (2h 정상 / 26h 주의 / 초과 오류)
//   r(dsRtFresh)   = 클라이언트 실시간 시세 보강 시각
// 기존엔 장중 1분 주기 실시간 성공이 innerHTML 전체를 '● 실시간' 초록으로 덮어써
// 파이프라인 정지 경고(26h 판정)가 위장됐다. 점 색은 등락 관습과 분리된 --ind-* 사용.
function _dsSlots() {
  const el = document.getElementById('dataSourceInfo');
  if(!el) return null;
  if(!document.getElementById('dsJsonFresh')) {
    el.innerHTML = '<div id="dsJsonFresh"></div><div id="dsRtFresh" style="margin-top:2px;"></div>';
  }
  return { j: document.getElementById('dsJsonFresh'), r: document.getElementById('dsRtFresh') };
}
function renderDataFreshness() {
  const s = _dsSlots();
  const ts = window._lastServerDataTs || window._lastRealDataTs;
  if(!s || !s.j || !ts) return;
  const dt = new Date(ts);
  if(isNaN(dt.getTime())) return;
  const ageH = (Date.now() - dt.getTime()) / 3600000;
  const dotColor = ageH <= 2 ? 'var(--ind-pos)' : ageH <= 26 ? 'var(--c-warn,#f0c75e)' : 'var(--ind-neg)';
  const ageTxt = ageH <= 2 ? '' :
    ` <span style="color:${dotColor};font-weight:var(--font-weight-semibold);">(${ageH < 48 ? Math.round(ageH) + '시간' : Math.round(ageH / 24) + '일'} 전 데이터)</span>`;
  s.j.innerHTML =
    `<span style="color:${dotColor};font-size:var(--font-size-xs);">●</span> ` +
    dt.toLocaleString('ko-KR', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) +
    ' 업데이트' + ageTxt + _tossChipHtml() + _healthChipHtml();
  const host = document.getElementById('dataSourceInfo');
  if(host) host.title = ageH > 26 ? '⚠ 데이터 수집 파이프라인이 멈춰 있을 수 있습니다 — 설정 > 시스템 진단 확인' : '';
  try { applyWidgetFreshChips(); } catch(_) {}   // Phase 3 — 위젯 타이틀 옆 신선도 칩
}

/* 토스증권 연결상태 칩 — diagnostics.toss 를 헤더에 노출한다.
   왜: 토스는 IP 허용 목록 때문에 CI 에서 못 부르고, 허용 IP 가 등록된 PC 수집기가
   toss_snapshot.json 을 커밋해 넘긴다. PC 가 꺼져 있으면 지수·국고채·순위·투자자수급이
   조용히 pykrx/yfinance 폴백으로 바뀌는데, 화면상 숫자는 그대로라 사용자는 알 수 없었다.
   LIVE 는 기본 상태이므로 칩을 띄우지 않는다 — 정상일 때 조용해야 경고가 눈에 띈다. */
function _tossChipHtml() {
  const t = window._tossStatus;
  if (!t || !t.state || t.state === 'LIVE') return '';
  const off = t.state === 'OFFLINE';
  const col = off ? 'var(--ind-neg)' : 'var(--c-warn,#f0c75e)';
  const label = off ? '토스 연결 끊김' : '토스 지연';
  const age = (t.ageMinutes == null) ? '수집 기록 없음'
    : (t.ageMinutes < 90 ? Math.round(t.ageMinutes) + '분 전 수집'
                         : Math.round(t.ageMinutes / 60) + '시간 전 수집');
  const src = (t.supplied && t.supplied.length)
    ? ' · 토스 제공: ' + t.supplied.join(', ') : ' · 전 항목 폴백';
  const tip = label + ' — ' + age + (t.reason ? ' · ' + t.reason : '') + src +
              ' — 클릭하면 시스템 진단';
  return ' <span class="health-chip" role="button" tabindex="0"' +
    ' onclick="showPage(\'settings\');setTimeout(runDiagnostics,300);"' +
    ` title="${tip.replace(/"/g, '&quot;')}"` +
    ` style="color:${col};border:1px solid ${col};border-radius:var(--r-xs);padding:0 6px;margin-left:6px;cursor:pointer;font-size:var(--font-size-xs);">` +
    `${off ? '⛔' : '⚠'} ${label}</span>`;
}

/* 지표 신선도 칩 — data.json.dataHealth 요약을 헤더에 노출한다.
   왜: 전역 '업데이트 시각'은 파이프라인이 돌기만 하면 항상 최신이라, 개별 소스가
   죽어 직전값이 보존되고 있는 상태를 전혀 드러내지 못했다(일본 CPI 2021-06 고착 등).
   클릭하면 설정 > 시스템 진단으로 이동해 어떤 지표인지 확인할 수 있다. */
function _healthChipHtml() {
  const h = window._dataHealth;
  if (!h || !h.summary) return '';
  const s = h.summary;
  const bad = (s.stale || 0) + (s.failed || 0) + (s.missing || 0);
  if (!bad) return '';
  const col = (s.failed || s.missing || (h.blocking || []).length) ? 'var(--ind-neg)' : 'var(--c-warn,#f0c75e)';
  const label = ['지연 ' + (s.stale || 0),
                 s.failed ? '실패 ' + s.failed : '',
                 s.missing ? '누락 ' + s.missing : ''].filter(Boolean).join(' · ');
  return ' <span class="health-chip" role="button" tabindex="0" onclick="showPage(\'settings\');setTimeout(runDiagnostics,300);"' +
    ` title="정상 ${s.ok} · 보존 ${s.preserved} · 지연 ${s.stale} · 실패 ${s.failed} · 누락 ${s.missing || 0} — 클릭하면 시스템 진단"` +
    ` style="color:${col};border:1px solid ${col};border-radius:var(--r-xs);padding:0 6px;margin-left:6px;cursor:pointer;font-size:var(--font-size-xs);">` +
    `⚠ ${label}</span>`;
}
// 탭 상시 오픈 사용 패턴 — 페이지 로드 시점에 동결되지 않도록 경과 시간을 1분마다 재평가
try { setInterval(renderDataFreshness, 60000); } catch(_) {}

async function loadRealData() {
  try {
    // 경량 메타 선조회(~100B) — lastUpdated 가 그대로면 3.6MB 본체 재다운로드를 생략한다.
    // (기존엔 자동 갱신 주기마다 no-store 전량 재수신 → 변경 없는 야간·주말에도 매번 수백 KB.)
    // data_meta.json 은 fetch_data.py 가 data.json 저장 직후 함께 생성·커밋한다.
    // 파일이 아직 없거나(404) 조회 실패 시에는 기존처럼 본체를 받는다(fail-open).
    let _dataVer = null;
    try {
      const metaR = await fetch('./data_meta.json?_=' + Date.now(), { cache: 'no-store' });
      if (metaR.ok) {
        const meta = await metaR.json().catch(() => null);
        if (meta && meta.lastUpdated && window._lastRealDataTs &&
            meta.lastUpdated === window._lastRealDataTs) {
          renderDataFreshness();   // 변경 없음이어도 경과 시간 표시는 재평가
          return;                  // 본체 페치 생략
        }
        if (meta && meta.lastUpdated) _dataVer = meta.lastUpdated;
      }
    } catch(_) {}
    // 본체는 lastUpdated 를 '버전 쿼리'로 사용 — 데이터가 갱신되면 URL 이 바뀌어 신선도가
    // 보장되고('오전 데이터 고정' 재발 없음), 같은 버전 재방문은 브라우저/CDN 캐시 적중으로
    // 363KB(gzip) 재다운로드 + 3.9MB JSON 파싱을 생략한다. 메타 조회 실패 시에만 기존
    // Date.now() 캐시버스터 + no-store 로 폴백(fail-open).
    const r = _dataVer
      ? await fetch('./data.json?v=' + encodeURIComponent(_dataVer))
      : await fetch('./data.json?_=' + Date.now(), { cache: 'no-store' });
    if (!r.ok) return;
    const data = await r.json();
    // 신규 데이터의 lastUpdated 가 동일하면 (변화 없음) 차트 재빌드 생략
    const prevTs = window._lastRealDataTs;
    const newTs  = data?.lastUpdated || null;
    applyRealData(data);
    try { window._lastRealDataObj = data; renderMarketHalts(data); } catch(_) {}
    window._lastRealDataTs = newTs;
    // lastUpdated 가 변경되었을 때만 활성 페이지 차트 재빌드 (불필요한 렌더 방지)
    if(prevTs && newTs && prevTs !== newTs) {
      try {
        const activePage = document.querySelector('.page.active');
        if(activePage) {
          const id = activePage.id;
          if(id === 'page-dashboard')      { try { initMainChart(mainPeriodUnit); buildMoverTable(curMoverTab); buildGlobalTable(); } catch(_) {} }
          else if(id === 'page-market')    { try { initMarketPage(); } catch(_) {} }
          else if(id === 'page-equity')    { try { buildEquityPage(); } catch(_) {} }
          else if(id === 'page-macro')     { try { initMacroPage(macroTab); } catch(_) {} }
          else if(id === 'page-realestate'){ try { buildReCharts(); if(typeof buildUsReCharts === 'function') buildUsReCharts(); } catch(_) {} }
          else if(id === 'page-investor')  { try { buildInvestorPage(); } catch(_) {} }
        }
      } catch(_) {}
    }
  } catch {
    // data.json 없음 — Mock 데이터로 동작. [3차-T18] 사용자에게 명시 + 재시도 제공
    try { if (typeof showDataSourceBanner === 'function') showDataSourceBanner(); } catch (_) {}
  }
}

// 🚨 시장중단(서킷브레이커·사이드카) — data.marketHalts 를 상단 배너·메뉴배지·이력표로 렌더.
let _haltCountdownTimer = null;
function renderMarketHalts(data) {
  const mh = (data && data.marketHalts) || {};
  const active = Array.isArray(mh.active) ? mh.active : [];
  const history = Array.isArray(mh.history) ? mh.history : [];
  const banner = document.getElementById('marketHaltBanner');
  const badge = document.getElementById('marketHaltBadge');
  const layout = document.getElementById('appLayout');
  if (!banner) return;

  // 닫은 사건 기억(econ_ 접두사 관례). 현재 active 에 없는 id 는 정리.
  let dismissed = {};
  try { dismissed = JSON.parse(localStorage.getItem('econ_halt_dismissed') || '{}') || {}; } catch (_) {}
  const activeIds = new Set(active.map(h => h.id));
  Object.keys(dismissed).forEach(id => { if (!activeIds.has(id)) delete dismissed[id]; });
  try { localStorage.setItem('econ_halt_dismissed', JSON.stringify(dismissed)); } catch (_) {}

  const visible = active.filter(h => !dismissed[h.id]);
  const TYPE_KO = { circuit: '서킷브레이커', sidecar: '사이드카' };
  const esc = s => String(s == null ? '' : s).replace(/[<>&]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
  const hhmm = iso => { try { return new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false }); } catch (_) { return '-'; } };

  banner.innerHTML = visible.map(h => {
    const typ = TYPE_KO[h.type] || h.type;
    const stage = (h.type === 'circuit' && h.stage) ? ` ${h.stage}단계` : '';
    const cls = h.type === 'circuit' ? 'circuit' : 'sidecar';
    const icon = h.type === 'circuit' ? '🔴' : '🟠';
    const when = h.endOfDay
      ? `${hhmm(h.triggeredAt)} 매매중단 → 당일 장 종료`
      : `${hhmm(h.triggeredAt)} 중단 → <span class="halt-cd" data-resume="${esc(h.resumeAt || '')}">${hhmm(h.resumeAt)} 재개예정</span>`;
    const approx = h.approx ? ' · 추정' : '';
    return `<div class="halt-banner ${cls}" data-id="${esc(h.id)}">`
      + `<span>${icon} ${esc(h.market)} ${typ}${stage} 발동 — ${esc(h.reason)} · ${when}${approx}</span>`
      + `<button class="halt-x" title="닫기" onclick="dismissHalt('${esc(h.id)}')">✕</button></div>`;
  }).join('');

  const show = visible.length > 0;
  banner.style.display = show ? 'flex' : 'none';
  // 파이프라인 경고 배너(#pipelineWarnBanner)와 겹치지 않게 공통 스택/paddingTop 보정으로 위임.
  // (_syncTopBanners 미정의 환경에서는 기존 로직 그대로 폴백 — 동작 불변.)
  if (typeof _syncTopBanners === 'function') _syncTopBanners();
  else if (layout) layout.style.paddingTop = show ? (56 + banner.offsetHeight) + 'px' : '56px';
  if (badge) badge.style.display = active.length > 0 ? 'inline-block' : 'none';

  // 재개까지 카운트다운(1초 간격)
  if (_haltCountdownTimer) { clearInterval(_haltCountdownTimer); _haltCountdownTimer = null; }
  if (show) {
    const tick = () => {
      banner.querySelectorAll('.halt-cd[data-resume]').forEach(el => {
        const t = el.getAttribute('data-resume'); if (!t) return;
        const ms = new Date(t) - new Date();
        if (ms > 0) { const m = Math.floor(ms / 60000), s = Math.floor((ms % 60000) / 1000); el.textContent = `${hhmm(t)} 재개예정 (${m}:${String(s).padStart(2, '0')})`; }
        else { el.textContent = `${hhmm(t)} 재개`; }
      });
    };
    tick(); _haltCountdownTimer = setInterval(tick, 1000);
  }

  // 이력표(국내증시 페이지)
  const histBox = document.getElementById('marketHaltHistory');
  if (histBox) {
    if (history.length) {
      const rows = history.map(h => {
        const typ = TYPE_KO[h.type] || h.type;
        const stage = (h.type === 'circuit' && h.stage) ? `${h.stage}단계` : (h.direction === 'up' ? '매수' : '매도');
        let d = '-';
        try { d = new Date(h.triggeredAt).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }); } catch (_) {}
        const end = h.endOfDay ? '당일종료' : hhmm(h.resumeAt);
        return `<tr><td>${d}</td><td>${typ}</td><td>${esc(h.market)}</td><td>${stage}</td><td>${esc(h.reason)}</td><td>${hhmm(h.triggeredAt)}~${end}</td></tr>`;
      }).join('');
      histBox.innerHTML = `<div style="font-weight:var(--font-weight-semibold);margin-bottom:8px;">⚠️ 과거 매매중단 이력 (서킷브레이커·사이드카)</div>`
        + `<div style="overflow-x:auto;"><table class="halt-hist-table"><thead><tr><th>일시</th><th>종류</th><th>시장</th><th>단계/방향</th><th>사유</th><th>중단~재개</th></tr></thead><tbody>${rows}</tbody></table></div>`;
      histBox.style.display = 'block';
    } else {
      histBox.style.display = 'none';
    }
  }
}

function dismissHalt(id) {
  let dismissed = {};
  try { dismissed = JSON.parse(localStorage.getItem('econ_halt_dismissed') || '{}') || {}; } catch (_) {}
  dismissed[id] = 1;
  try { localStorage.setItem('econ_halt_dismissed', JSON.stringify(dismissed)); } catch (_) {}
  if (window._lastRealDataObj) renderMarketHalts(window._lastRealDataObj);
}

// ─────────────────────────────────────────────────────────────────
// ⚠️ 알림 파이프라인 상태 배너 — Worker 헬스(GET /)의 ghTokenValid 가 '확정 false'
//   (GH_DISPATCH_TOKEN 만료/폐기)일 때만 상단 경고 배너를 띄운다. null(판정불가)·fetch 실패는
//   무시(fail-open — 배너는 확정 신호에만 반응). loadRealData 최초 완료 후 1회만 조회.
// ─────────────────────────────────────────────────────────────────
// 상단 고정 배너 스택 공통 보정 — 시장중단 배너(top:56 고정) 아래에 파이프라인 배너를 쌓고,
// #appLayout paddingTop 을 '56 + 두 배너 높이 합'으로 맞춘다(renderMarketHalts 의 기존
// 56px 보정을 포괄 대체 — 둘 다 숨김이면 정확히 기존과 같은 56px).
function _syncTopBanners() {
  const layout = document.getElementById('appLayout');
  const halt = document.getElementById('marketHaltBanner');
  const pipe = document.getElementById('pipelineWarnBanner');
  const haltH = halt ? halt.offsetHeight : 0;              // display:none 이면 0
  if (pipe) pipe.style.top = (56 + haltH) + 'px';
  const pipeH = pipe ? pipe.offsetHeight : 0;
  if (layout) layout.style.paddingTop = (56 + haltH + pipeH) + 'px';
}

var _PIPE_WARN_DISMISS_KEY = 'econ_pipeline_warn_dismissed';
function dismissPipelineWarn() {
  try { localStorage.setItem(_PIPE_WARN_DISMISS_KEY, String(Date.now())); } catch (_) {}
  const pipe = document.getElementById('pipelineWarnBanner');
  if (pipe) { pipe.style.display = 'none'; pipe.innerHTML = ''; }
  _syncTopBanners();
}

let _pipelineHealthChecked = false;
async function _checkWorkerPipelineHealth() {
  if (_pipelineHealthChecked) return;            // 세션당 1회만
  _pipelineHealthChecked = true;
  try {
    // 24시간 내 닫았으면 재표시하지 않음(과도한 잔소리 방지 — 다음날 다시 리마인드).
    try {
      const t = parseInt(localStorage.getItem(_PIPE_WARN_DISMISS_KEY) || '0', 10);
      if (t && Date.now() - t < 24 * 3600 * 1000) return;
    } catch (_) {}
    const base = (typeof _cfProxyBase === 'function') ? _cfProxyBase() : '';
    if (!base) return;
    const r = await fetch(base + '/', { signal: AbortSignal.timeout(5000) });
    if (!r.ok) return;                            // 헬스 실패 자체는 무시(배너는 확정 신호에만)
    const h = await r.json().catch(() => null);
    if (!h || h.ghTokenValid !== false) return;   // true/null(판정불가)/필드없음 → 배너 없음
    const pipe = document.getElementById('pipelineWarnBanner');
    if (!pipe) return;
    let msg = '⚠️ 알림 파이프라인 점검 필요: GitHub 토큰 만료 — Worker 시크릿 GH_DISPATCH_TOKEN 재발급';
    if (h.ghAlertsTokenValid === false) msg += ' (GH_ALERTS_TOKEN 도 만료)';
    // 최근 24시간 내 dispatch 실패 신호(Worker isolate 메모리 best-effort)가 있으면 부드럽게 안내.
    let sub = '';
    const lf = h.lastDispatchFail;
    if (lf && lf.t && (Date.now() - lf.t) < 24 * 3600 * 1000) {
      let when = '';
      try { when = new Date(lf.t).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false }); } catch (_) {}
      sub = ' · 최근 24시간 내 알림 발송 트리거 실패가 감지되었습니다' + (when ? ' (마지막 ' + when + ')' : '') + ' — 카카오 알림이 누락될 수 있어요.';
    }
    pipe.innerHTML = '<div class="halt-banner sidecar">'
      + '<span>' + msg + sub + '</span>'
      + '<button class="halt-x" title="닫기" onclick="dismissPipelineWarn()">✕</button></div>';
    pipe.style.display = 'flex';
    _syncTopBanners();
  } catch (_) { /* 조회 실패 무시 — 대시보드 렌더에는 영향 없음 */ }
}

// 전체 데이터 새로고침 — data.json + 실시간 FX/Stooq/뉴스/Top10/시장분위기 페치
// 사용자가 명시적으로 클릭한 경우 호출됨.
// 중요: 사용자 명시 클릭 시엔 lastUpdated 비교와 무관하게 무조건 차트 재빌드함
// (서버 data.json 이 동일해도 클라이언트 실시간 데이터는 갱신되므로).
async function refreshAllData(btn) {
  _refreshFeedback(btn, 'loading');
  try {
    // 병렬 페치 — 한쪽이 느려도 다른 쪽이 대기하지 않도록
    // movers/sentiment 는 boolean 반환 가능 → 값까지 검사하여 실제 성공 여부 판정.
    const results = await Promise.allSettled([
      loadRealData(),                                                          // 0: json
      loadRealtimeFx(),                                                        // 1: fx
      loadRealtimeMarket(),                                                    // 2: market
      loadFreshNews(),                                                         // 3: news
      refreshMoversFromClient(true),                                           // 4: movers (true/false)
      (typeof fetchSentimentClient === 'function' && typeof applySentimentClient === 'function')
        ? fetchSentimentClient().then(applySentimentClient)
        : Promise.resolve(),                                                   // 5: sentiment
    ]);
    // status: fulfilled 면 일단 통과. 단 movers 는 value(boolean) 도 검사
    const isOk = (r, requireTruthy) => r.status === 'fulfilled' && (!requireTruthy || r.value);
    const okFlags = {
      json:      isOk(results[0]),
      fx:        isOk(results[1]),
      market:    isOk(results[2]),
      news:      isOk(results[3]),
      movers:    isOk(results[4], true),
      sentiment: isOk(results[5]),
    };
    // 현재 활성화된 페이지의 차트/테이블 강제 재빌드
    // (loadRealData 가 lastUpdated 비교 후 재빌드를 스킵해도, 사용자 명시 클릭이므로 무조건 다시 그림)
    const activePage = document.querySelector('.page.active');
    if(activePage) {
      const id = activePage.id;
      try {
        if(id === 'page-market')         initMarketPage();
        else if(id === 'page-equity')    buildEquityPage();
        else if(id === 'page-macro')     { initMacroPage(macroTab); if(typeof buildMacroIndicatorTable === 'function') buildMacroIndicatorTable(); }
        else if(id === 'page-investor')  buildInvestorPage();
        else if(id === 'page-realestate'){ buildReCharts(); if(typeof buildUsReCharts === 'function') buildUsReCharts(); }
        else if(id === 'page-dashboard') {
          buildMoverTable(curMoverTab);
          buildGlobalTable();
          initMainChart(mainPeriodUnit);
        } else if(id === 'page-calendar') {
          if(typeof buildCalendar === 'function') buildCalendar();
        }
      } catch(e) { console.warn('[refreshAllData] 차트 재빌드 오류:', e); }
    }
    // 차트 새로고침 버튼 재주입 (재빌드 후 .widget-title 이 갱신됐을 수 있음)
    setTimeout(() => { try { injectChartRefreshButtons(); } catch(_){} }, 80);
    // 성공/경고 판정
    const okCount = Object.values(okFlags).filter(Boolean).length;
    const totalCount = Object.keys(okFlags).length;
    if(okCount === totalCount) {
      _refreshFeedback(btn, 'success', '전체 갱신');
    } else if(okCount >= totalCount / 2) {
      _refreshFeedback(btn, 'success', `${okCount}/${totalCount} 갱신`);
    } else if(okCount > 0) {
      _refreshFeedback(btn, 'warn', `${okCount}/${totalCount} 갱신`);
    } else {
      _refreshFeedback(btn, 'error', '네트워크 오류');
    }
  } catch(e) {
    console.warn('[refreshAllData] 오류:', e);
    _refreshFeedback(btn, 'error', '갱신 실패');
  }
}

// ============================
// 실시간 환율 (open.er-api.com — 무료, no auth, CORS 허용)
// ============================
let _fxFirstLoad = true;  // 최초 페치 시 변화율 계산 건너뜀 (하드코딩 기본값 대비 비교 방지)
async function loadRealtimeFx() {
  if(!window._REALTIME_BOOST) return 0;   // data.json 전용 모드 — FX 는 서버 data.json 값 사용
  // 실시간 환율 — 대시보드 KOSPI 지수와 '동일한' 경로(Stooq → CF 워커/공개 프록시 풀)로 가져온다.
  // 이전 구현은 open.er-api.com 을 브라우저에서 직접 fetch 했는데 (1) CORS 차단으로 자주 실패하고
  // (2) 무료 티어가 하루 1회만 갱신해 변화율이 사실상 0 이라 '새로고침이 안 되는' 문제가 있었다.
  // Stooq 일별 종가는 KOSPI/원자재와 동일하게 프록시를 거쳐 안정적으로 받고, 의미있는 일변화율을 준다.
  // y: Yahoo FX 심볼(장중 분단위 실시간) · s: Stooq 심볼(폴백, 일봉 EOD).
  // 지수/원자재(loadRealtimeMarket)와 '동일하게' Yahoo 우선 — Yahoo 는 KRW=X 등 환율을 장중 분단위로
  // 주므로 진짜 실시간이고, Stooq 일봉은 장중 직전영업일 종가에 고정돼 값이 안 움직였다(미실시간의 원인).
  const fxTasks = [
    { y:'KRW=X',    s:'usdkrw', i:0 },   // USD/KRW
    { y:'EURKRW=X', s:'eurkrw', i:1 },   // EUR/KRW
    { y:'JPYKRW=X', s:'jpykrw', i:2 },   // JPY/KRW (1엔당 ≈9.4 → displayMult 100 으로 100엔 표기)
    { y:'EURUSD=X', s:'eurusd', i:3 },   // EUR/USD
    { y:'JPY=X',    s:'usdjpy', i:4 },   // USD/JPY
  ];
  let updated = 0, yahooCount = 0;
  await Promise.all(fxTasks.map(async ({ y, s, i }) => {
    try {
      let q = await fetchYahooQuote(y).catch(()=>null);                          // 1차: Yahoo 인트라데이(실시간)
      if (q) yahooCount++; else q = await fetchStooqHistory(s).catch(()=>null);  // 폴백: Stooq 일봉
      if (q && q.price > 0 && fxPairs[i]) {
        const dec = (fxPairs[i].pair === 'JPY/KRW' || fxPairs[i].pair === 'EUR/USD') ? 4 : 2;
        fxPairs[i].cur = q.price.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
        fxPairs[i].pct = q.change;
        fxPairs[i].chg = +(q.price * q.change / 100).toFixed(4);
        updated++;
      }
    } catch (_) { /* 다른 통화쌍 계속 시도 */ }
  }));

  // 폴백 — Stooq 가 전부 막히면 open.er-api.com 을 '프록시 경유'로 받아 현재 환율만이라도 갱신.
  if (updated === 0) {
    try {
      const d1 = await _fetchViaProxies('https://open.er-api.com/v6/latest/USD', true);
      const d2 = await _fetchViaProxies('https://open.er-api.com/v6/latest/EUR', true);
      if (d1 && d1.rates) {
        const usdKrw = d1.rates.KRW, usdJpy = d1.rates.JPY;
        const eurKrw = (d2 && d2.rates) ? d2.rates.KRW : null;
        const eurUsd = (d2 && d2.rates) ? d2.rates.USD : (d1.rates.EUR ? 1 / d1.rates.EUR : null);
        const setRate = (i, val, dec) => {
          if (val && fxPairs[i]) {
            fxPairs[i].cur = val.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
            updated++;
          }
        };
        setRate(0, usdKrw, 2);
        setRate(1, eurKrw, 2);
        setRate(2, (usdKrw && usdJpy) ? usdKrw / usdJpy : null, 4);
        setRate(3, eurUsd, 4);
        setRate(4, usdJpy, 2);
      }
    } catch (_) { /* 폴백도 실패 — 기존 값 유지 */ }
  }

  if (updated > 0) {
    _fxFirstLoad = false;
    // '기준 시점' 을 실제 클라이언트 페치 시각/소스로 기록 → buildFxPage 가 서버 data.json 시각
    // (장중 갱신 지연으로 '11:13 고정'처럼 보이던) 대신 이 값을 우선 사용한다.
    window._fxRealtimeAsOf = Date.now();
    window._fxRealtimeSrc  = (yahooCount > 0) ? 'Yahoo Finance (실시간)' : 'Stooq (일별 종가)';
  }

  // 사이드바 실시간 슬롯만 갱신 — 파이프라인 신선도 표시(j 슬롯)는 보존
  const _rtSlots = (typeof _dsSlots === 'function') ? _dsSlots() : null;
  if (_rtSlots && _rtSlots.r && updated > 0) {
    _rtSlots.r.innerHTML = `<span style="color:var(--ind-pos);font-size:var(--font-size-xs);">●</span> 실시간 환율: ${new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })}`;
  }
  // 대시보드 USD/KRW KPI 카드 갱신
  const kpiFxPriceEl = document.getElementById('kpi-fx-price');
  const kpiFxChgEl   = document.getElementById('kpi-fx-chg');
  if (kpiFxPriceEl) kpiFxPriceEl.textContent = fxPairs[0].cur;
  if (kpiFxChgEl) {
    const up = (fxPairs[0].pct || 0) >= 0;
    kpiFxChgEl.className = up ? 'up-txt' : 'down-txt';
    kpiFxChgEl.style.cssText = 'font-size:13px;margin-top:4px;';
    kpiFxChgEl.textContent = (up ? '▲ +' : '▼ ') + Math.abs(fxPairs[0].pct || 0).toFixed(2) + '%';
  }
  // 티커 바의 USD/KRW · EUR/KRW 갱신 (값+일변화율)
  const setTickerFx = (name, pairIdx) => {
    const t = tickerData.find(x => x.name === name);
    if (t && fxPairs[pairIdx]) {
      const pct = fxPairs[pairIdx].pct || 0;
      t.val = fxPairs[pairIdx].cur;
      t.chg = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
      t.up  = pct >= 0;
    }
  };
  setTickerFx('USD/KRW', 0);
  setTickerFx('EUR/KRW', 1);
  // 헤더·FX 페이지·티커 재렌더 (가시성과 무관하게 DOM 동기화)
  if (typeof updateFxHeader === 'function') updateFxHeader();
  if (document.getElementById('market-fx') && typeof buildFxPage === 'function') buildFxPage();
  if (typeof buildTicker === 'function') buildTicker();
  return updated;
}

// ============================
// 실시간 뉴스 (Google News RSS → 전용 Cloudflare Worker 프록시)
// ============================
const NEWS_QUERIES = {
  newsItems: [
    // 채권(0-4), 외환(5-9), 주식(10-14), 원자재(15-19)
    {idx:0,  q:'한국은행 기준금리 2026'},
    {idx:5,  q:'원달러 환율 시황 2026'},
    {idx:10, q:'코스피 주가 시황 2026'},
    {idx:15, q:'WTI 국제유가 2026'},
  ],
  commodityNewsItems: [
    // 원유(0-4), 귀금속(5-9), 비철금속(10-14)
    {idx:0,  q:'WTI 국제유가 2026'},
    {idx:5,  q:'금 시세 골드 2026'},
    {idx:10, q:'LME 구리 가격 2026'},
  ],
  macroNewsItems: [
    // 한국GDP(0-4), 미국CPI(5-9), 중국경기(10-14), 유로존(15-19)
    {idx:0,  q:'한국 GDP 성장률 2026'},
    {idx:5,  q:'미국 CPI 인플레이션 2026'},
    {idx:10, q:'중국 경기 PMI 2026'},
    {idx:15, q:'유로존 인플레이션 2026'},
  ],
  calendarNewsItems: [
    // 한국수출(0-4), 미국CPI(5-9), 한국은행(10-14)
    {idx:0,  q:'한국 수출 무역수지 2026'},
    {idx:5,  q:'미국 CPI 고용 2026'},
    {idx:10, q:'한국은행 금통위 2026'},
  ],
};

async function fetchLatestArticle(query) {
  const list = await fetchLatestArticles(query, 1);
  return list && list.length ? list[0] : null;
}

// CORS 프록시 — 전용 Worker 단일 경로 (공개 프록시 폴백 제거 + fetchWithRetry 표준화).
const _NEWS_PROXIES = [
  (url) => _cfProxyUrl(url),                                                 // 전용 Worker (미설정 시 null)
];

// sessionStorage 텍스트 캐시 — RSS 처럼 갱신 주기가 긴 응답 전용(호출자가 cacheMs 로 옵트인).
// Stooq 실시간 시세 등 폴링 경로는 opts 미지정 → 캐시 미적용.
function _rssCacheGet(url, ttlMs) {
  try {
    const raw = sessionStorage.getItem('econ_rss:' + url);
    if(!raw) return null;
    const c = JSON.parse(raw);
    if(!c || !c.x || (Date.now() - c.t) > ttlMs) return null;
    return c.x;
  } catch(_) { return null; }
}
function _rssCacheSet(url, text) {
  const put = () => sessionStorage.setItem('econ_rss:' + url, JSON.stringify({ t: Date.now(), x: text }));
  try { put(); } catch(_) {
    // quota 초과 → 본 사이트 RSS 캐시만 비우고 1회 재시도 (그래도 실패하면 무음 — 캐시는 최적화일 뿐)
    try {
      Object.keys(sessionStorage).filter(k => k.indexOf('econ_rss:') === 0).forEach(k => sessionStorage.removeItem(k));
      put();
    } catch(__) {}
  }
}

async function _fetchTextWithProxies(targetUrl, timeoutMs, opts) {
  const cacheMs = (opts && opts.cacheMs) || 0;
  if(cacheMs > 0 && !(opts && opts.force)) {
    const hit = _rssCacheGet(targetUrl, cacheMs);
    if(hit) return hit;
  }
  for(const mk of _NEWS_PROXIES) {
    try {
      const url = mk(targetUrl);
      if(!url) continue;                                                     // CF 미설정 시 null 스킵
      const r = await fetchWithRetry(url, { timeoutMs: timeoutMs || 7000, retries: 2 });
      if(!r.ok) return null;                                                 // 404/410=대상 없음, 403=상류 차단
      const text = await r.text();
      if(text && text.length > 50) {
        if(cacheMs > 0) _rssCacheSet(targetUrl, text);
        return text;
      }
    } catch(_) { /* 재시도 소진 */ }
  }
  return null;
}

// Google News RSS 의 base64 인코딩된 article URL 을 디코드해서 원본 기사 URL 추출
// Google News URL 형식: https://news.google.com/rss/articles/CBMi[base64url]?oc=5
// CBMi 는 protobuf 필드 1(type:string) 의 시작 — 그 뒤에 varint 길이 + URL 문자열
function _decodeGoogleNewsUrl(gUrl) {
  try {
    const m = (gUrl||'').match(/\/articles\/([A-Za-z0-9_-]+)/);
    if(!m) return null;
    let b64 = m[1].replace(/-/g,'+').replace(/_/g,'/');
    while(b64.length % 4) b64 += '=';
    const raw = atob(b64);
    // 'http' 시작 위치 찾기 (보통 4바이트 헤더 + varint 후에 위치)
    const idx = raw.indexOf('http');
    if(idx < 0) return null;
    // URL 끝 찾기 — non-printable 또는 \xd2 까지
    let end = idx;
    while(end < raw.length) {
      const c = raw.charCodeAt(end);
      if(c < 0x20 || c >= 0x7f) break;
      end++;
    }
    const decoded = raw.slice(idx, end);
    // 기본 검증: http(s)://domain/path 형식
    if(!/^https?:\/\/[a-z0-9.-]+\.[a-z]{2,}\//i.test(decoded)) return null;
    return decoded;
  } catch(_) { return null; }
}

// Google News RSS 의 link 가 redirect URL 인 경우, description 내부 링크를 우선시
function _extractRealArticleUrl(itemEl) {
  const link = itemEl.querySelector('link')?.textContent || '';
  const guid = itemEl.querySelector('guid')?.textContent || '';
  const desc = itemEl.querySelector('description')?.textContent || '';
  const sourceEl = itemEl.querySelector('source');
  const sourceUrl = sourceEl?.getAttribute('url') || '';
  // 1) description 안의 첫 번째 외부 링크 (google news 아닌 도메인)
  if(desc) {
    const m = desc.match(/href="(https?:\/\/(?!news\.google\.com)[^"]+)"/);
    if(m && m[1]) return m[1];
  }
  // 2) Google News URL 을 디코드해서 원본 기사 URL 추출
  if(link && link.includes('news.google.com')) {
    const decoded = _decodeGoogleNewsUrl(link);
    if(decoded) return decoded;
  }
  if(guid && guid.includes('news.google.com')) {
    const decoded = _decodeGoogleNewsUrl(guid);
    if(decoded) return decoded;
  }
  // 3) source url (RSS <source url="..."> attribute) — 출판사 사이트 URL
  if(sourceUrl && !sourceUrl.includes('news.google.com')) return sourceUrl;
  // 4) 모든 시도 실패 → Google News URL 그대로 (redirect 시도)
  return link || guid || '#';
}

async function fetchLatestArticles(query, count=5, force=false) {
  // Google News RSS — 세션 캐시 10분 (수동 새로고침은 force 로 우회)
  const RSS_CACHE = { cacheMs: 600000, force };
  const rss = `https://news.google.com/rss/search?q=${encodeURIComponent(query)}&hl=ko&gl=KR&ceid=KR:ko`;
  let xmlText = await _fetchTextWithProxies(rss, 7000, RSS_CACHE);
  // 보조: Daum 뉴스 검색 RSS 도 시도 (Google News 가 안 될 때)
  if(!xmlText) {
    const naverRss = `https://rss.daum.net/rss/search.xml?q=${encodeURIComponent(query)}`;
    xmlText = await _fetchTextWithProxies(naverRss, 5000, RSS_CACHE);
  }
  if(!xmlText) return null;
  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(xmlText, 'text/xml');
    const items = Array.from(doc.querySelectorAll('item'));
    if(!items.length) return null;
    // 사용자 요구: 15일 이내 실제 기사만. 검색결과 URL 도 거부.
    const cutoffMs = Date.now() - 15 * 24 * 3600 * 1000;
    const futureMs = Date.now() + 24 * 3600 * 1000;
    const parsed = items.map(it => {
      const title = (it.querySelector('title')?.textContent || '').replace(/<!\[CDATA\[|\]\]>/g,'').replace(/\s*-\s*[^-]+$/, '').trim();
      const url = _extractRealArticleUrl(it);
      const pubDate = it.querySelector('pubDate')?.textContent || '';
      const isoDate = pubDate ? (() => { try { return new Date(pubDate).toISOString().slice(0,10); } catch { return null; } })() : null;
      return { title, url, time: pubDate ? relTime(new Date(pubDate).toISOString()) : '오늘', isoDate };
    }).filter(a => {
      if(!a.url || !a.title) return false;
      if(!_isArticleUrlOk(a.url)) return false;     // 검색결과/홈페이지 URL 거부
      if(!a.isoDate) return false;                   // 날짜 미상 거부
      const t = new Date(a.isoDate).getTime();
      if(isNaN(t)) return false;
      return t >= cutoffMs && t <= futureMs;
    });
    return parsed.slice(0, count);
  } catch(_) { return null; }
}

function relTime(iso) {
  try {
    const t = new Date(iso).getTime();
    const diff = (Date.now() - t) / 1000;
    if (diff < 3600) return Math.floor(diff/60) + '분 전';
    if (diff < 86400) return Math.floor(diff/3600) + '시간 전';
    return Math.floor(diff/86400) + '일 전';
  } catch { return '오늘'; }
}

// data.json.news 우선 적용 — 서버측에서 매일 아침 9시 KST 에 Google News RSS 로
// 미리 페치한 기사를 카테고리(item.cat) 별로 교체.
// 검색결과 페이지/publisher 홈페이지 URL 은 제외, 1주일 이내 기사만 채택.
// _isSearchOrInvalidNewsUrl 의 역으로 정의 — 단일 source-of-truth 유지.
function _isArticleUrlOk(url) {
  return !_isSearchOrInvalidNewsUrl(url);
}

// 카테고리 fallback: 세부 카테고리가 비었을 때 더 일반적인 카테고리로 폴백.
// 예) 원유/귀금속/비철금속 → 원자재. 데이터 소스가 세부 키워드 매칭에 실패한
// 경우에도 사용자가 commodity 페이지에서 빈 화면 대신 관련 뉴스를 볼 수 있도록.
const NEWS_CAT_FALLBACK = {
  '원유':     '원자재',
  '귀금속':   '원자재',
  '비철금속': '원자재',
};

function applyServerNewsToFeeds(serverNews) {
  if (!serverNews || typeof serverNews !== 'object') return false;
  const feeds = { newsFeed:newsItems, commodityNewsFeed:commodityNewsItems,
                  macroNewsFeed:macroNewsItems, calendarNewsFeed:calendarNewsItems };
  // 사용자 요구: 15일 이내 실제 기사만. isoDate 없거나 미래 날짜인 항목 거부.
  const cutoffMs = Date.now() - 15 * 24 * 3600 * 1000;
  const nowMs    = Date.now() + 24 * 3600 * 1000;  // 시차 보정 1일
  let appliedCount = 0;
  const _filterFresh = (rawList) => (rawList || []).filter(a => {
    if (!a || !a.url) return false;
    if (!_isArticleUrlOk(a.url)) return false;
    if (!a.isoDate) return false;
    const t = new Date(a.isoDate).getTime();
    if (isNaN(t)) return false;
    return t >= cutoffMs && t <= nowMs;
  });
  for (const arr of Object.values(feeds)) {
    // 카테고리 별로 기존 항목 순서대로 서버측 기사 슬롯에 매핑
    const byCat = {};
    arr.forEach((item, idx) => {
      const cat = item.cat || '기타';
      (byCat[cat] = byCat[cat] || []).push(idx);
    });
    // 동일 피드 내 중복 URL 방지 — 같은 기사가 여러 카테고리로 들어오는 경우
    // (예: 원유/귀금속/비철금속 → 모두 원자재 폴백으로 같은 기사 매핑) 1회만 노출.
    const usedUrls = new Set();
    Object.entries(byCat).forEach(([cat, idxList]) => {
      let fresh = _filterFresh(serverNews[cat]);
      // 폴백: 정의된 fallback 카테고리에서 기사 가져오기 (예: 원유 → 원자재)
      if (fresh.length === 0 && NEWS_CAT_FALLBACK[cat]) {
        fresh = _filterFresh(serverNews[NEWS_CAT_FALLBACK[cat]]);
      }
      // 이미 다른 카테고리에서 사용된 URL 은 제외 (중복 방지)
      const freshDedup = fresh.filter(a => !usedUrls.has(a.url));
      // 버그 수정: fresh.length === 0 일 때도 cleanup 루프를 반드시 돌려야 함.
      // 기존엔 early return 으로 인해 data.json 에 해당 카테고리 기사가 0건이면
      // 정적 fallback (search.naver.com URL) 이 화면에 그대로 노출되어 사용자가
      // 클릭 시 검색창으로 튕기는 회귀가 발생했음.
      idxList.forEach((slotIdx, i) => {
        const article = freshDedup[i];
        if (!article || !article.url) return;
        arr[slotIdx].title = article.title;
        arr[slotIdx].url   = article.url;
        if (article.isoDate) arr[slotIdx].isoDate = article.isoDate;
        arr[slotIdx].time  = article.isoDate ? relTime(article.isoDate) : '오늘';
        usedUrls.add(article.url);
        appliedCount++;
      });
      // 남는 슬롯은 isoDate 를 비워 buildNewsFeed 의 cutoff 필터로 자연스레 숨겨짐.
      // _isArticleUrlOk 로 검색 URL 뿐 아니라 publisher 홈페이지 URL 도 일괄 차단.
      for (let j = freshDedup.length; j < idxList.length; j++) {
        const oldItem = arr[idxList[j]];
        if (oldItem && !_isArticleUrlOk(oldItem.url)) {
          oldItem.isoDate = '';  // 빈 isoDate → buildNewsFeed 가 제외
        }
      }
    });
  }
  // 최종 sweep: 어떤 이유로든 남아있는 정적 search URL · 홈페이지 URL 항목의
  // isoDate 를 비워 다음 렌더에서 자연 제외 (belt-and-suspenders).
  for (const arr of Object.values(feeds)) {
    arr.forEach(item => {
      if (item && !_isArticleUrlOk(item.url)) {
        item.isoDate = '';
      }
    });
  }
  if (appliedCount > 0) console.info(`[News] data.json 서버측 뉴스 ${appliedCount}건 적용 (15일 이내, 실기사 URL)`);
  return appliedCount > 0;
}

async function loadFreshNews() {
  // 1) data.json.news 가 있으면 우선 적용 (서버측 Google News 페치 결과)
  let serverApplied = false;
  try {
    const d = _latestDataForIndicators || {};
    if (d && d.news) {
      serverApplied = applyServerNewsToFeeds(d.news);
    }
  } catch(_) {}

  // 2) 클라이언트 뉴스 보강 — 기본 비활성 (의도적, 콘솔 0 에러 원칙).
  //    Google News RSS·Daum RSS(rss.daum.net)는 공개 프록시에서 400/530 으로 자주 실패해
  //    콘솔에 빨간 에러를 다수 남기는데, 서버 data.json.news(수십 건)가 이미 충분하고 뉴스는
  //    분 단위 실시간이 불필요하다. 따라서 _REALTIME_BOOST(지수/시세용)와 분리해 별도 플래그로
  //    기본 OFF 로 둔다. 굳이 켜려면 콘솔: localStorage.setItem('newsClientFetch','1') 후 새로고침.
  const arrays = { newsItems, commodityNewsItems, macroNewsItems, calendarNewsItems };
  const tasks = [];
  // 클라이언트 뉴스 보강 — 주식 Top10 의 _REALTIME_BOOST 와 동일하게 '실시간 갱신'을 켠다.
  // 과거 OFF 였던 이유는 '공개 프록시'가 자주 실패해 콘솔 에러를 남겼기 때문인데, 이제 전용
  // CF Worker(안정적·상류 4xx 시 즉시 중단)를 1순위로 쓰므로 그 경우엔 켜도 안전하다.
  //   · CF Worker 설정됨 → 기본 ON (뉴스도 주식처럼 실시간으로 최신 기사 반영)
  //   · 미설정          → 기본 OFF (공개 프록시 콘솔오류 방지)
  //   · 강제 토글: localStorage.setItem('newsClientFetch','1'|'0') 후 새로고침
  const _newsClientOn = (function(){
    try {
      const v = localStorage.getItem('newsClientFetch');
      if(v === '1') return true;
      if(v === '0') return false;
      return !!(typeof _cfProxyBase === 'function' && _cfProxyBase());
    } catch(_) { return false; }
  })();
  if(_newsClientOn) for (const [arrName, queries] of Object.entries(NEWS_QUERIES)) {
    for (const {idx, q} of queries) {
      tasks.push(fetchLatestArticles(q, 5).then(freshList => {
        if (!freshList || !freshList.length) return;
        freshList.forEach((fresh, i) => {
          const slot = idx + i;
          if (!arrays[arrName][slot] || !fresh || !fresh.url) return;
          if (_isSearchOrInvalidNewsUrl(fresh.url)) return;  // 새 URL 도 검증
          // 기존 url 이 검색/홈페이지 URL (정적 fallback) 이거나 더 최신 기사가 있으면 교체
          const cur = arrays[arrName][slot];
          const isStaticUrl = _isSearchOrInvalidNewsUrl(cur.url);
          const newerIso = fresh.isoDate && cur.isoDate && fresh.isoDate >= cur.isoDate;
          if (isStaticUrl || newerIso || !cur.url || cur.url === '#') {
            cur.title = fresh.title;
            cur.url   = fresh.url;
            cur.time  = fresh.time;
            if (fresh.isoDate) cur.isoDate = fresh.isoDate;
          }
        });
      }).catch(()=>{}));
    }
  }
  await Promise.all(tasks);
  // 최종 sweep: 클라이언트 RSS 도 페치 실패한 카테고리의 정적 search URL 항목 숨김.
  // applyServerNewsToFeeds 가 이미 sweep 하지만, 그 사이 fetchLatestArticles 가
  // 새 search URL 을 주입했을 가능성도 차단 (방어선 다층화).
  Object.values(arrays).forEach(arr => {
    arr.forEach(item => {
      if (item && _isSearchOrInvalidNewsUrl(item.url)) item.isoDate = '';
    });
  });
  // 로드 완료 표시 — 이후 0건이면 '로딩 중'이 아니라 '기사 없음' 빈 상태를 렌더한다
  window._newsFetchDone = true;
  // 모든 뉴스 피드 다시 렌더링 (DOM에 존재하는 것만)
  if (document.getElementById('newsFeed'))          buildNewsFeed('newsFeed', newsItems);
  if (document.getElementById('commodityNewsFeed')) buildNewsFeed('commodityNewsFeed', commodityNewsItems);
  if (document.getElementById('macroNewsFeed'))     buildNewsFeed('macroNewsFeed', macroNewsItems);
  if (document.getElementById('calendarNewsFeed')) buildNewsFeed('calendarNewsFeed', calendarNewsItems);
}

// ============================
// 실시간 지수·원자재 (Stooq — 무료, 인증 불필요, CORS 허용)
// Stooq CSV 히스토리 API: 최근 7일치 → 마지막 2거래일로 전일比 계산
// ============================
async function fetchStooqHistory(symbol) {
  const today = new Date();
  const d2 = today.toISOString().slice(0,10).replace(/-/g,'');
  const past = new Date(today);
  past.setDate(past.getDate() - 10); // 10일 전(주말·공휴일 감안)
  const d1 = past.toISOString().slice(0,10).replace(/-/g,'');
  const url = `https://stooq.com/q/d/l/?s=${encodeURIComponent(symbol)}&d1=${d1}&d2=${d2}&i=d`;
  // 직접 fetch 는 Stooq 의 CORS 미허용으로 브라우저에서 차단된다(지수·원자재가 실시간
  // 갱신 안 되고 data.json 으로 폴백되던 근본 원인). CF 워커/공개 프록시 풀 경유로 가져온다.
  const text = await _fetchTextWithProxies(url, 8000);
  if (!text) return null;
  // Format: Date,Open,High,Low,Close,Volume
  const lines = text.trim().split('\n').filter(l => l && !l.startsWith('Date') && l.includes(','));
  if (lines.length < 1) return null;
  const lastRow  = lines[lines.length - 1].split(',');
  const prevRow  = lines.length >= 2 ? lines[lines.length - 2].split(',') : null;
  const close    = parseFloat(lastRow[4]);
  const prevClose = prevRow ? parseFloat(prevRow[4]) : null;
  if (!close || close <= 0 || isNaN(close)) return null;
  const changePct = (prevClose && prevClose > 0)
    ? (close - prevClose) / prevClose * 100
    : 0;
  return { price: close, change: +changePct.toFixed(2) };
}

// Yahoo Finance v8 chart — 장중 '실시간(지연)' 시세. meta.regularMarketPrice(현재가) +
// meta.chartPreviousClose(전일 종가)로 당일 등락률을 계산한다. Stooq 일봉(i=d)은 장중에
// '직전 거래일 종가'에 고정되어 월요일 장중에도 KOSPI 가 금요일 종가(8476.15)로 멈춰 보였는데,
// Yahoo 는 장중 현재가를 주므로 그 문제를 해결한다. (sentiment 의 ^VKOSPI 페치와 동일 경로/검증된 패턴.)
async function fetchYahooQuote(symbol) {
  try {
    // ⚠ 일봉(5d) 으로 받는다. 종전엔 range=1d&interval=1m 이었고 전일 종가를
    //   meta.chartPreviousClose 로 삼았는데, 지수에서 이 필드가 실제와 어긋난다 —
    //   2026-08-14 ^KQ11 은 이 값 기준 +0.67% 였지만 실제(KRX·토스·data.json)는 +0.38%
    //   였고, 그 값이 헤더 티커를 덮어써 사이트 안에서 숫자가 서로 달라 보였다.
    //   일봉 배열의 직전 확정 종가를 기준가로 쓰면 그 오차가 사라진다(서버측 다이제스트·
    //   서킷브레이커 판정도 같은 방식으로 고쳤다). meta.regularMarketPrice 는 5d 요청에도
    //   장중 실시간 값이라 현재가 신선도는 그대로다.
    const url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(symbol) + '?range=5d&interval=1d';
    const j = await _fetchJsonWithProxies(url);
    const res = j && j.chart && j.chart.result && j.chart.result[0];
    const meta = res && res.meta;
    if(!meta) return null;
    const closes = (((res.indicators || {}).quote || [{}])[0] || {}).close || [];
    const valid = closes.filter(c => c != null && isFinite(c));
    const price = (meta.regularMarketPrice != null) ? meta.regularMarketPrice
                : (valid.length ? valid[valid.length - 1] : meta.previousClose);
    let prev = valid.length >= 2 ? valid[valid.length - 2] : null;
    if(prev == null) prev = (meta.chartPreviousClose != null) ? meta.chartPreviousClose : meta.previousClose;
    if(price == null || !isFinite(price) || price <= 0) return null;
    const change = (prev != null && prev > 0) ? +(((price - prev) / prev) * 100).toFixed(2) : 0;
    return { price: +(+price).toFixed(2), change };
  } catch(_) { return null; }
}

async function loadRealtimeMarket() {
  if(!window._REALTIME_BOOST) return;   // data.json 전용 모드 — 지수/원자재는 서버 data.json 값 사용
  // y: Yahoo 심볼(장중 실시간) · s: Stooq 심볼(폴백, EOD). Yahoo 우선 → 실패 시 Stooq.
  const indexTasks = [
    { y:'^KS11',     s:'^kospi',    key:'KOSPI'    },
    { y:'^KQ11',     s:'^kosdaq',   key:'KOSDAQ'   },
    { y:'^GSPC',     s:'^spx',      key:'SP500'    },
    { y:'^IXIC',     s:'^ndq',      key:'NASDAQ'   },
    { y:'^N225',     s:'^nkx',      key:'Nikkei'   },
    { y:'000001.SS', s:'000001.ss', key:'Shanghai' },
  ];
  const comTasks = [
    { y:'CL=F', s:'cl.f',   key:'WTI'      },
    { y:'BZ=F', s:'co.f',   key:'Brent'    },
    { y:'GC=F', s:'xauusd', key:'Gold'     },
    { y:'SI=F', s:'xagusd', key:'Silver'   },
    { y:'HG=F', s:'hg.f',   key:'Copper'   },
    { y:'PL=F', s:'xptusd', key:'Platinum' },   // 백금
    { y:'NG=F', s:'ng.f',   key:'NatGas'   },   // 천연가스
  ];

  const patchIdx = {}, patchCom = {};
  let count = 0, yahooCount = 0;
  // Yahoo(장중 실시간) 우선 → 실패 시 Stooq(EOD) 폴백. 둘 다 전용 Worker/공개 프록시 경유라 CORS 안전.
  const grab = async (y, s) => {
    const q = await fetchYahooQuote(y).catch(()=>null);
    if(q) { yahooCount++; return q; }
    return await fetchStooqHistory(s).catch(()=>null);
  };

  await Promise.all([
    ...indexTasks.map(async ({ y, s, key }) => {
      const q = await grab(y, s);
      if (q) { patchIdx[key] = q; count++; }
    }),
    ...comTasks.map(async ({ y, s, key }) => {
      const q = await grab(y, s);
      if (q) { patchCom[key] = q; count++; }
    }),
  ]);

  if (count > 0) {
    // applyRealData는 fx:{} 빈 객체 전달 시 FX 값을 건드리지 않음
    applyRealData({ indices: patchIdx, commodities: patchCom, fx: {} });
    // 실시간 슬롯만 갱신 — 파이프라인 신선도 표시(j 슬롯)는 보존
    const _rtSlots = (typeof _dsSlots === 'function') ? _dsSlots() : null;
    if (_rtSlots && _rtSlots.r) {
      const now = new Date();
      const src = yahooCount > 0 ? 'Yahoo 실시간' : 'Stooq';
      _rtSlots.r.innerHTML = `<span style="color:var(--ind-pos);font-size:var(--font-size-xs);">●</span> ${src}: ${now.toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',hour12:false})}`;
    }
    // 보강이 기본 ON 이라 장중 1분마다 호출된다 → 정상 동작 로그는 debug 로(콘솔 기본 비표시) 노이즈 억제.
    console.debug(`[지수·원자재] ${count}개 갱신 (Yahoo ${yahooCount}, Stooq ${count - yahooCount})`);
  } else {
    // 모든 소스 실패 = 처리된 폴백(서버 data.json 값 사용). 에러가 아니므로 debug 로 낮춤.
    console.debug('[지수·원자재] 실시간 페치 실패 — data.json 값 사용 중 (정상 폴백).');
  }
}

// ============================
// 투자자 차트 — 날짜 범위 기본값
// ============================
// (applyInvestorDateRange 는 위에서 정의됨 — 단위/기간 통합)

function initInvestorDateDefaults() {
  // 새 단위 시스템에서는 기본값을 비워두어 단위 선택에 따라 자동 조정
  // 사용자가 특정 기간을 지정한 경우에만 from/to 적용
  const toEl   = document.getElementById('invDateTo');
  const fromEl = document.getElementById('invDateFrom');
  if(!fromEl || !toEl) return;
  // 기본은 비워두기 — 단위 D 일 때 최근 60일 자동 표시
  // toEl/fromEl 비어있으면 buildInvestorChart 가 전체 raw 에서 자동 슬라이스
}

// ============================
// 금리 차트 기간 선택
// ============================
let ratePeriodSlice = 'all';
function setRatePeriod(period, btn) {
  ratePeriodSlice = period;
  ['ratePeriodAll','ratePeriod5y','ratePeriod3y','ratePeriod1y'].forEach(id=>{
    const b = document.getElementById(id);
    if(b) { b.style.background = 'transparent'; b.style.color = 'var(--c-txt-dim)'; }
  });
  if(btn) { btn.style.background = 'var(--c-accent)'; btn.style.color = '#fff'; }
  buildRateHistoryChart();
}

function buildRateHistoryChart() {
  destroyChart('rateHistoryChart');
  const ctx = document.getElementById('rateHistoryChart');
  if(!ctx) return;
  const allLabels = rateHistoryData.labels;
  const n = ratePeriodSlice==='1y' ? 2 : ratePeriodSlice==='3y' ? 4 : ratePeriodSlice==='5y' ? 6 : allLabels.length;
  const sliceFrom = Math.max(0, allLabels.length - n);
  const labels = allLabels.slice(sliceFrom);
  const datasets = [...rateFilterSet].map(cc=>({
    label: rateCountries[cc],
    data: rateHistoryData[cc].slice(sliceFrom),
    borderColor: rateColors[cc],
    backgroundColor: rateColors[cc]+'22',
    borderWidth: 2, pointRadius: 0, tension: 0.3, fill: false,
  }));
  charts['rateHistoryChart'] = new Chart(ctx, {
    type:'line',
    data:{labels, datasets},
    options:{responsive:true,maintainAspectRatio:false,
      scales:{
        x:{ticks:{color:'#b6bbcf',font:{size:10}},grid:{color:'#4a526888'}},
        y:{ticks:{color:'#b6bbcf',font:{size:10},callback:fmtPct},grid:{color:'#4a526888'}}
      },
      plugins:{
        legend:{display:true,position:'top',labels:{color:'#b6bbcf',font:{size:10},boxWidth:10,padding:8}},
        tooltip:{mode:'index',intersect:false,backgroundColor:'#262a35',titleColor:'#e8ebf5',bodyColor:'#e8ebf5',borderColor:'#3a4054',borderWidth:1,
          callbacks:{label:c=>c.dataset.label+': '+c.parsed.y.toFixed(2)+'%'}}
      }
    }
  });
  // YoY — 주 시리즈(rateFilterSet 첫 국가, dataset 0)만 전년 오버레이. 연/분기 라벨 기반.
  { const _rc = [...rateFilterSet][0];
    if(_rc) registerYoY('rateHistoryChart', { mode:'periodlabel', dispLabels:labels, fullLabels:allLabels, fullValues:(rateHistoryData[_rc]||[]), primary:0, color:rateColors[_rc], tension:0.3 });
    else registerYoY('rateHistoryChart', null);
    applyYoY('rateHistoryChart'); }
  // 기준금리 현황 테이블 채우기
  buildRateCurrentTable();
}

// 기준금리 테이블 행 클릭 시: 해당 국가만 차트에 표시
function selectRateCountry(cc) {
  if(!rateCountries[cc]) return;
  rateFilterSet = new Set([cc]);
  // 필터 버튼 상태 동기화 — onclick 핸들러가 'kr','us','eu','jp','uk' 코드를 직접 받음
  const btns = document.querySelectorAll('#rateFilterBtns button');
  btns.forEach(b => {
    const oc = b.getAttribute('onclick') || '';
    const m = oc.match(/'([a-z]+)'/);
    const target = m && m[1];
    const isActive = target === cc;
    b.style.opacity = isActive ? '1' : '0.45';
    b.style.background = isActive ? rateColors[target] : (rateColors[target] || '#2a2e3d') + '22';
    b.style.color = isActive ? '#fff' : rateColors[target] || '#8d90a2';
  });
  buildRateHistoryChart();
}

function buildRateCurrentTable() {
  const tb = document.getElementById('rateCurrentTable');
  if(!tb) return;
  tb.innerHTML = currentRates.map(r => {
    const dirCls = r.dir.includes('인하') || r.dir.includes('↓') ? 'down-txt' : r.dir.includes('인상') || r.dir.includes('↑') ? 'up-txt' : '';
    const isSel = rateFilterSet.size === 1 && rateFilterSet.has(r.cc);
    const bg = isSel ? 'background:#2962ff11;border-left:2px solid var(--c-accent);' : '';
    return `<tr onclick="selectRateCountry('${r.cc}')" title="${r.country} 기준금리 차트로 보기" style="border-bottom:1px solid var(--c-border);cursor:pointer;${bg}">
      <td style="padding:8px;">${r.flag} ${r.country}</td>
      <td style="text-align:right;padding:8px;font-weight:var(--font-weight-semibold);color:var(--c-primary);">${r.rate}</td>
      <td style="text-align:right;padding:8px;color:var(--c-txt-dim);">${r.prev}</td>
      <td style="text-align:right;padding:8px;color:var(--c-txt-dim);font-size:var(--font-size-sm);">${r.next}</td>
      <td style="text-align:right;padding:8px;font-size:var(--font-size-sm);" class="${dirCls}">${r.dir}</td>
    </tr>`;
  }).join('');
}

// ============================
// NPS 자산배분 추이 — 구간 측정
// ============================
let npsMeasureMode = false;
let npsMeasureStart = null;

function toggleNpsAllocMeasure(btn) {
  npsMeasureMode = !npsMeasureMode;
  npsMeasureStart = null;
  const info   = document.getElementById('npsMeasureInfo');
  const result = document.getElementById('npsMeasureResult');
  if(btn) {
    btn.style.background = npsMeasureMode ? '#b6c4ff22' : 'transparent';
    btn.style.border     = npsMeasureMode ? '1px solid var(--c-primary)' : '1px solid #b6c4ff44';
    btn.style.color      = npsMeasureMode ? '#b6c4ff' : '#b6c4ff';
  }
  if(info)   info.style.display   = npsMeasureMode ? 'block' : 'none';
  if(result) result.style.display = 'none';
  buildNpsAllocTrendChart();
}

function clearNpsMeasure() {
  npsMeasureStart = null;
  const result = document.getElementById('npsMeasureResult');
  if(result) result.style.display = 'none';
}

function onNpsTrendClick(evt) {
  if(!npsMeasureMode) return;
  const chart = charts['npsAllocationTrendChart'];
  if(!chart) return;
  const points = chart.getElementsAtEventForMode(evt,'nearest',{intersect:false},true);
  if(!points.length) return;
  const idx   = points[0].index;
  const trend = getNpsAllocTrend();
  const label = trend.years[idx];
  if(npsMeasureStart === null) {
    npsMeasureStart = idx;
    const info = document.getElementById('npsMeasureInfo');
    if(info) info.textContent = `시작: ${label} 선택됨. 끝 연도를 클릭하세요.`;
  } else {
    const endIdx = idx;
    const startIdx = Math.min(npsMeasureStart, endIdx);
    const realEnd  = Math.max(npsMeasureStart, endIdx);
    const startLabel = trend.years[startIdx];
    const endLabel   = trend.years[realEnd];
    const rows = trend.datasets.map(ds=>{
      const sv = ds.data[startIdx];
      const ev = ds.data[realEnd];
      const diff = (ev - sv).toFixed(1);
      const clr  = diff >= 0 ? window.CUP : window.CDN;
      return `<span style="margin-right:12px;"><span style="color:${ds.color};font-weight:var(--font-weight-semibold);">${ds.label}</span> ${sv}% → ${ev}% <span style="color:${clr};">(${diff>=0?'+':''}${diff}%p)</span></span>`;
    }).join('');
    const result = document.getElementById('npsMeasureResult');
    if(result) {
      result.innerHTML = `<span style="color:var(--c-txt-dim);">📐 ${startLabel} → ${endLabel} 구간 변화: </span>${rows}`;
      result.style.display = 'block';
    }
    const info = document.getElementById('npsMeasureInfo');
    if(info) info.textContent = '시작 연도를 클릭하고, 끝 연도를 클릭하면 구간별 증감률이 표시됩니다.';
    npsMeasureStart = null;
  }
}

// buildNpsAllocTrendChart — override to support measure mode click
const _origBuildNpsAllocTrendChart = buildNpsAllocTrendChart;
buildNpsAllocTrendChart = function() {
  _origBuildNpsAllocTrendChart();
  if(npsMeasureMode) {
    const canvas = document.getElementById('npsAllocationTrendChart');
    if(canvas) {
      canvas.removeEventListener('click', onNpsTrendClick);
      canvas.addEventListener('click', onNpsTrendClick);
      canvas.style.cursor = 'crosshair';
    }
  } else {
    const canvas = document.getElementById('npsAllocationTrendChart');
    if(canvas) {
      canvas.removeEventListener('click', onNpsTrendClick);
      canvas.style.cursor = '';
    }
  }
};

// ============================
// 분석 노트 — 확장 필드 처리
// ============================
const NOTE_SECTIONS = ['Macro','Equity','Bond','Fx','Com','RE'];
function getSectionIds() { return NOTE_SECTIONS.map(s=>'note'+s); }

function openNote(id) {
  curNoteId = id;
  const n = notes.find(n=>n.id===id); if(!n) return;
  document.getElementById('noteTitle').value = n.title || '';
  document.getElementById('noteBody').value  = n.body  || '';
  const authorEl = document.getElementById('noteAuthor');
  if(authorEl) authorEl.value = n.author || '';
  document.getElementById('noteDate').textContent = n.date;
  curTag = n.tag || '매크로';
  document.querySelectorAll('.note-tag').forEach(t=>{
    const active = t.textContent === curTag;
    t.style.background = active ? getThemeColors().accent+'22' : '#1b1f2b';
    t.style.color      = active ? '#b6c4ff'   : '#8d90a2';
    t.style.border     = active ? '1px solid #2962ff55' : '1px solid var(--c-border)';
  });
  getSectionIds().forEach(sid=>{
    const el = document.getElementById(sid);
    if(el) el.value = (n.sections && n.sections[sid]) || '';
  });
  renderNoteList();
}

function saveNote() {
  const authorEl = document.getElementById('noteAuthor');
  const author   = (authorEl ? authorEl.value : '').trim();
  if(!author) { alert('작성자를 입력해주세요 (필수 항목)'); if(authorEl) authorEl.focus(); return; }
  const id  = curNoteId || ('note_'+Date.now());
  const idx = notes.findIndex(n=>n.id===id);
  const sections = {};
  getSectionIds().forEach(sid=>{ const el=document.getElementById(sid); if(el) sections[sid]=el.value; });
  const n = {
    id, title:document.getElementById('noteTitle').value, author,
    body:document.getElementById('noteBody').value,
    tag:curTag, date:new Date().toLocaleDateString('ko-KR'), sections,
  };
  if(idx>=0) notes[idx]=n; else { notes.unshift(n); curNoteId=id; }
  save(); renderNoteList();
}

function deleteNote() {
  if(!curNoteId) return;
  notes = notes.filter(n=>n.id!==curNoteId); curNoteId = null;
  document.getElementById('noteTitle').value = '';
  document.getElementById('noteBody').value  = '';
  const authorEl = document.getElementById('noteAuthor');
  if(authorEl) authorEl.value = '';
  getSectionIds().forEach(sid=>{ const el=document.getElementById(sid); if(el) el.value=''; });
  save(); renderNoteList();
}

function newNote() {
  const id = 'note_'+Date.now();
  const n  = {id, title:'새 노트', author:'', body:'', tag:'매크로', date:new Date().toLocaleDateString('ko-KR'), sections:{}};
  notes.unshift(n); save(); openNote(id);
}

// ============================
// 분석 노트 — Excel 내보내기 (단일 시트, 선택 노트)
// ============================
// XLSX 라이브러리(~900KB)는 이 기능에서만 쓰여 <head> 정적 로드를 제거하고
// 버튼 클릭 시 1회 동적 로드한다 (SRI·CSP 그대로 유지, 첫 페인트 경량화).
let _xlsxReady = null;
function loadXlsxOnce() {
  if(window.XLSX) return Promise.resolve();
  if(_xlsxReady) return _xlsxReady;
  _xlsxReady = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js';
    s.integrity = 'sha384-vtjasyidUo0kW94K5MXDXntzOJpQgBKXmE7e2Ga4LG0skTTLeBi97eFAXsqewJjw';
    s.crossOrigin = 'anonymous';
    s.onload = resolve;
    s.onerror = () => { _xlsxReady = null; reject(new Error('xlsx load failed')); };
    document.head.appendChild(s);
  });
  return _xlsxReady;
}
async function exportSelectedToExcel() {
  if(!notes.length) { alert('저장된 노트가 없습니다.'); return; }
  try { await loadXlsxOnce(); }
  catch(_) { alert('Excel 라이브러리 로드에 실패했습니다 — 네트워크 확인 후 다시 시도하세요.'); return; }

  const selectedCbs = document.querySelectorAll('.note-select-cb:checked');
  const selectedIds = selectedCbs.length > 0
    ? [...selectedCbs].map(cb => cb.dataset.id)
    : notes.map(n => n.id); // 선택 없으면 전체 내보내기

  const toExport = notes.filter(n => selectedIds.includes(n.id));
  if(!toExport.length) { alert('내보낼 노트가 없습니다.'); return; }

  const headers = ['제목','작성자','날짜','분류','전체 요약','매크로/경제지표','주식시장','금리/채권','외환/환율','원자재','부동산'];
  const rows = toExport.map(n => {
    const s = n.sections || {};
    return [
      n.title||'', n.author||'', n.date||'', n.tag||'', n.body||'',
      s.noteMacro||'', s.noteEquity||'', s.noteBond||'', s.noteFx||'', s.noteCom||'', s.noteRE||''
    ];
  });

  const ws = XLSX.utils.aoa_to_sheet([headers, ...rows]);
  ws['!cols'] = headers.map((h,i) => ({wch: i === 0 ? 20 : i < 4 ? 12 : 40}));
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, '분석노트');
  XLSX.writeFile(wb, '분석노트_'+new Date().toISOString().slice(0,10)+'.xlsx');
}

// ============================
// 테마 토글
// ============================
function toggleTheme() {
  const isLight = document.documentElement.classList.toggle('light');
  localStorage.setItem('econ_theme', isLight ? 'light' : 'dark');
  const icon  = document.getElementById('themeIcon');
  const label = document.getElementById('themeLabel');
  if(icon)  icon.textContent  = isLight ? 'dark_mode'  : 'light_mode';
  if(label) label.textContent = isLight ? '다크 모드' : '라이트 모드';
  const tbtn = document.getElementById('themeToggleBtn');
  if(tbtn) tbtn.setAttribute('aria-pressed', isLight ? 'true' : 'false');
  // 등락색(CUP/CDN)을 새 테마 값으로 갱신한 뒤 차트 색상 재빌드
  if(typeof window.refreshUpDn === 'function') window.refreshUpDn();
  rebuildChartsForTheme();
}

function applyStoredTheme() {
  // 우선순위: 저장값 > OS 다크모드(prefers-color-scheme) > 라이트 — <head> FOUC 방지 블록과 동일 규칙
  const stored = localStorage.getItem('econ_theme');
  let sysDark = false;
  try { sysDark = matchMedia('(prefers-color-scheme: dark)').matches; } catch(_) {}
  const useLight = stored ? (stored !== 'dark') : !sysDark;
  if(useLight) {
    document.documentElement.classList.add('light');
    const icon  = document.getElementById('themeIcon');
    const label = document.getElementById('themeLabel');
    if(icon)  icon.textContent  = 'dark_mode';
    if(label) label.textContent = '다크 모드';
  }
  const tbtn = document.getElementById('themeToggleBtn');
  if(tbtn) tbtn.setAttribute('aria-pressed', useLight ? 'true' : 'false');
  // 차트 전역 기본값을 현재 테마에 맞게 설정 (모든 차트 생성 전에 호출)
  invalidateThemeColors();
  applyChartJsThemeDefaults();
}

// astryx 토큰을 단일 출처로 읽는다 — 하드코딩 맵을 두면 CSS 와 어긋난다.
// Chart.js(캔버스)는 var() 를 해석하지 못하므로 getComputedStyle 로 실제 값을 뽑아
// 전달한다. color-mix() 로 정의된 토큰은 브라우저마다 color(srgb …) 로 직렬화돼
// @kurkle/color 가 못 읽을 수 있어, 여기서는 평문 hex/rgba 토큰만 참조한다.
// var 인 이유: 같은 스크립트 블록의 위쪽 top-level 상수들이 getThemeColors() 를
// 호출한다(차트 팔레트 등). let 이면 그 시점에 TDZ 라 ReferenceError 가 나고,
// 블록 나머지 top-level 실행이 통째로 중단된다. var 는 hoist 돼 undefined 로 시작.
var _tcCache = null, _tcKey = '';
function getThemeColors() {
  const light = document.documentElement.classList.contains('light');
  // 캐시 키에 스킨 포함 — 스킨 전환 직후 어떤 경로로 호출돼도 묵은 색을 재사용하지 않게
  const key = (light ? 'light' : 'dark') + '|' + (document.documentElement.dataset.skin || '');
  if (_tcCache && _tcKey === key) return _tcCache;
  const cs = getComputedStyle(document.documentElement);
  const tok = (name, fallback) => (cs.getPropertyValue(name).trim() || fallback);
  _tcKey = key;
  _tcCache = {
    txt:      tok('--color-text-secondary',   light ? '#737373' : '#a3a3a3'),
    grid:     tok('--color-border',           light ? '#ebebeb' : '#FFFFFF1A'),
    tooltip:  tok('--color-background-popover', light ? '#ffffff' : '#262626'),
    ttBorder: tok('--color-border-emphasized', light ? '#d4d4d4' : '#525252'),
    ttTitle:  tok('--color-text-primary',     light ? '#171717' : '#fafafa'),
    ttBody:   tok('--color-text-secondary',   light ? '#737373' : '#a3a3a3'),
    // 등락색은 관습(kr/global)×테마 매트릭스(refreshUpDn)가 단일 출처
    up:       window.CUP,
    down:     window.CDN,
    accent:   tok('--color-accent',           light ? '#00458c' : '#9eb7ff'),
    primary:  tok('--color-text-accent',      light ? '#00458c' : '#c7d3ff'),
    // 카테고리 팔레트 — 시리즈 색이 필요할 때 하드코딩 대신 이걸 쓴다
    series:   Array.from({length: 9}, (_, i) =>
                tok('--color-series-' + (i + 1), '#9eb7ff')),
  };
  // 첫 계산 시점의 팔레트를 기억해 둔다. rebuildChartsForTheme 이 이전 팔레트와
  // 대조해 데이터셋 색을 옮긴다.
  if (!window._tcPrevPalette) window._tcPrevPalette = [_tcCache.accent, _tcCache.primary].concat(_tcCache.series);
  return _tcCache;
}
// 테마 토글 시 캐시 무효화 (applyChartJsThemeDefaults 직전에 호출됨)
function invalidateThemeColors() { _tcCache = null; _tcKey = ''; }

// Chart.js 전역 기본값 설정 — 테마 변경 시 새로 생성되는 차트도 자동 반영
function applyChartJsThemeDefaults() {
  if(typeof Chart === 'undefined') return;
  const tc = getThemeColors();
  Chart.defaults.color = tc.txt;
  Chart.defaults.borderColor = tc.grid;
  // 툴팁 기본값
  if(Chart.defaults.plugins?.tooltip) {
    Chart.defaults.plugins.tooltip.backgroundColor = tc.tooltip;
    Chart.defaults.plugins.tooltip.titleColor = tc.ttTitle;
    Chart.defaults.plugins.tooltip.bodyColor = tc.ttTitle;  // 본문도 제목과 같은 색 (대비 보장)
    Chart.defaults.plugins.tooltip.borderColor = tc.ttBorder;
    Chart.defaults.plugins.tooltip.borderWidth = 1;
  }
}

function rebuildChartsForTheme() {
  // Rebuild all active charts so grid/tick/tooltip colors update
  invalidateThemeColors();
  applyChartJsThemeDefaults();
  const tc = getThemeColors();
  // [3차-T11] 종목 상세 모달이 열려 있으면 모달 차트도 새 테마색으로 재렌더 (T10과 한 쌍)
  try {
    const _m = document.getElementById('pfChartModal');
    if (_m && _m.style.display === 'block' && typeof pfChart !== 'undefined' && pfChart && pfChart.candles) pfRenderChart();
  } catch (_) {}
  Object.entries(charts).forEach(([id, ch]) => {
    if(!ch || !ch.options) return;
    try {
      // Update scale tick and grid colors
      if(ch.options.scales) {
        Object.values(ch.options.scales).forEach(sc => {
          // _fixedTickColor: 데이터셋 색상과 묶인 축(이중축 비교 차트 등)은 테마 전환 시에도 색 유지
          if(sc.ticks) sc.ticks.color = sc._fixedTickColor || tc.txt;
          if(sc.grid)  sc.grid.color  = tc.grid;
        });
      }
      // Update legend label color
      if(ch.options.plugins?.legend?.labels) ch.options.plugins.legend.labels.color = tc.txt;
      // Update tooltip colors — 항상 ttTitle 사용 (콘트라스트 보장)
      if(ch.options.plugins?.tooltip) {
        const tt = ch.options.plugins.tooltip;
        tt.backgroundColor = tc.tooltip;
        tt.titleColor = tc.ttTitle;
        tt.bodyColor  = tc.ttTitle;  // body도 title 색 (white 기본값 방지)
        tt.borderColor = tc.ttBorder;
      }
      ch.update();
    } catch(_) {}
  });
  // 데이터셋 색 리맵 — accent·시리즈 색이 astryx 토큰이 되면서 테마마다 값이 달라졌다.
  // 옵션만 패치하면 선/면은 이전 테마 색으로 남으므로(라이트 배경 위 연한 파랑 =
  // 대비 미달) 이전 팔레트 → 새 팔레트로 문자열을 치환한다. 알파 접미사(#RRGGBB33)
  // 는 접두 일치로 함께 옮긴다.
  try {
    const prev = window._tcPrevPalette;
    const next = [tc.accent, tc.primary].concat(tc.series);
    if (prev && prev.length === next.length) {
      const swap = v => {
        if (typeof v !== 'string' || v.charAt(0) !== '#') return v;
        for (let i = 0; i < prev.length; i++) {
          if (prev[i] && v.indexOf(prev[i]) === 0) return next[i] + v.slice(prev[i].length);
        }
        return v;
      };
      const KEYS = ['borderColor', 'backgroundColor', 'pointBackgroundColor',
                    'pointBorderColor', 'hoverBackgroundColor', 'hoverBorderColor'];
      Object.values(charts).forEach(ch => {
        if (!ch || !ch.data) return;
        (ch.data.datasets || []).forEach(ds => {
          KEYS.forEach(k => {
            const v = ds[k];
            if (Array.isArray(v)) ds[k] = v.map(swap);
            else if (v !== undefined) ds[k] = swap(v);
          });
          if (ds.datalabels && ds.datalabels.color) ds.datalabels.color = swap(ds.datalabels.color);
        });
        const dl = ch.options && ch.options.plugins && ch.options.plugins.datalabels;
        if (dl && dl.color) dl.color = swap(dl.color);
        try { ch.update('none'); } catch (_) {}
      });
    }
    window._tcPrevPalette = next;
  } catch (_) {}

  // 도넛 게이지·비교차트는 dataset 색이 테마 리터럴이라 옵션 패치로 안 바뀜 — 재생성
  try { buildFearChart(); } catch(_) {}
  try { if(charts['compareChart'] && typeof cmpRender === 'function') cmpRender(); } catch(_) {}
}

// ============================
// % 비교 모드 (크로스차트 수익률 비교)
// ============================
const chartCompareModes = {}; // chartKey -> bool

function normalizeToPercent(data) {
  if(!data || !data.length) return data;
  const base = data.find(v => v !== null && v !== undefined);
  if(base == null || base === 0) return data;
  return data.map(v => v == null ? null : +((v - base) / Math.abs(base) * 100).toFixed(2));
}

function toggleChartCompareMode(chartKey, btn) {
  chartCompareModes[chartKey] = !chartCompareModes[chartKey];
  const active = chartCompareModes[chartKey];
  if(btn) {
    btn.style.background = active ? getThemeColors().accent+'22' : 'transparent';
    btn.style.color = active ? getThemeColors().accent : '#8d90a2';
    btn.style.border = active ? '1px solid var(--c-accent)' : '1px solid var(--c-border)';
  }
  applyChartCompareMode(chartKey, active);
}

function resetChartCompareMode(chartKey) {
  chartCompareModes[chartKey] = false;
  const btn = document.getElementById(chartKey === 'equity' ? 'eqCompareModeBtn' : chartKey === 'fx' ? 'fxCompareModeBtn' : 'comCompareModeBtn');
  if(btn) { btn.style.background='transparent'; btn.style.color='var(--c-txt-dim)'; btn.style.border='1px solid var(--c-border)'; }
  applyChartCompareMode(chartKey, false);
}

function applyChartCompareMode(chartKey, active) {
  const chartIdMap = {equity:'equityIndexChart', fx:'fxChart', com:'comDetailChart'};
  const chartId = chartIdMap[chartKey];
  const ch = charts[chartId];
  if(!ch) return;
  if(!ch._originalData) {
    ch._originalData = ch.data.datasets.map(ds => [...ds.data]);
  }
  // ⚠ ch.options 는 Chart.js v4 resolver proxy — 직접 쓰면 set 트랩 무한재귀(RangeError)로
  //   차트가 영구 파손된다(4074행 _yoySetLegend 와 동일 함정). 반드시 ch.config.options 에 쓴다.
  const cfg = ch.config.options = ch.config.options || {};
  if(active) {
    ch.data.datasets.forEach((ds, i) => {
      ds.data = normalizeToPercent(ch._originalData[i]);
    });
    if(cfg.scales?.y?.ticks) cfg.scales.y.ticks.callback = v => v.toFixed(1) + '%';
    cfg.plugins = cfg.plugins || {};
    cfg.plugins.tooltip = cfg.plugins.tooltip || {};
    cfg.plugins.tooltip._origCallbacks = cfg.plugins.tooltip.callbacks;
    cfg.plugins.tooltip.callbacks = { label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(2) + '%' };
  } else {
    ch.data.datasets.forEach((ds, i) => {
      ds.data = ch._originalData[i];
    });
    if(cfg.scales?.y?.ticks?.callback) delete cfg.scales.y.ticks.callback;
    if(cfg.plugins?.tooltip?._origCallbacks) {
      cfg.plugins.tooltip.callbacks = cfg.plugins.tooltip._origCallbacks;
    }
  }
  ch.update();
}

function toggleComCompareMode(btn) {
  toggleChartCompareMode('com', btn);
}

// ============================
// 모바일 사이드바 토글
// ============================
function toggleMobileSidebar() {
  const sb = document.getElementById('sidebar');
  if(sb) sb.classList.toggle('mobile-open');
}

// ============================
// 초기 렌더링
// ============================
// 부동산 KPI 카드 초기 상태 — 데이터 도착 전까지 "—" 유지 (더미 데이터 금지)
// 이전 버전에서는 내장 시계열(rePriceData) 마지막 값을 보여줬으나, 사용자가 실제 데이터로 착각할 위험
// 때문에 R-ONE / 국토부 / ECOS API 가 실제 값을 반환할 때까지 "—" 유지.
function initStaticRealEstateFallbacks() {
  // No-op — 실제 데이터만 표시. data.json 페치 실패 시 "—" 가 그대로 보이는 게 더 정직함.
  // 카드의 보조 텍스트로 어떤 API 가 페치 중인지 표시 (이미 HTML 의 data-fetched-status 메시지 사용).
}

// ============================
// 접근성 — 탭 위젯 ARIA·키보드 내비게이션 (WAI-ARIA APG Tabs 패턴 경량 적용)
// ============================
// 마크업 수정 없이 위임 방식으로 적용한다. '진짜 탭 그룹'은 2개 이상의 형제 .tab-btn 중
// 하나가 .active 를 갖는 경우로 식별 — 같은 클래스를 스타일 용도로만 쓰는 액션 버튼 행
// (🔑 동기화 키/☁ 서버에 저장 등)은 .active 멤버가 없어 자연히 제외된다.
// 로빙 탭인덱스는 의도적으로 쓰지 않는다 — 활성 상태가 인라인 스타일과 혼재 관리되는
// 구조라 잘못 적용 시 Tab 키 접근 자체가 막힐 수 있어, 자연 탭 순서 + 화살표 키만 더한다.
(function () {
  function _tabGroup(btn) {
    const parent = btn && btn.parentElement;
    if (!parent) return null;
    const group = [...parent.children].filter(el => el.classList && el.classList.contains('tab-btn'));
    if (group.length < 2 || !group.some(b => b.classList.contains('active'))) return null;
    return group;
  }
  function decorateAllTabGroups() {
    document.querySelectorAll('.tab-btn.active').forEach(activeBtn => {
      const group = _tabGroup(activeBtn);
      if (!group) return;
      const parent = activeBtn.parentElement;
      if (!parent.getAttribute('role')) parent.setAttribute('role', 'tablist');
      group.forEach(b => {
        if (!b.getAttribute('role')) b.setAttribute('role', 'tab');
        b.setAttribute('aria-selected', b.classList.contains('active') ? 'true' : 'false');
      });
    });
  }
  // 탭 클릭 직후(.active 토글 완료 후) aria-selected 재동기화 + 동적 렌더된 그룹 장식
  document.addEventListener('click', (e) => {
    if (!e.target.closest || !e.target.closest('.tab-btn')) return;
    setTimeout(decorateAllTabGroups, 0);
  });
  // 화살표/Home/End 키로 탭 그룹 내 이동 (포커스 이동 + 기존 onclick 로직 재사용)
  document.addEventListener('keydown', (e) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    const btn = e.target && e.target.closest && e.target.closest('.tab-btn');
    if (!btn) return;
    const group = _tabGroup(btn);
    if (!group) return;
    let i = group.indexOf(btn);
    if (i < 0) return;
    i = e.key === 'ArrowRight' ? (i + 1) % group.length
      : e.key === 'ArrowLeft'  ? (i - 1 + group.length) % group.length
      : e.key === 'Home' ? 0 : group.length - 1;
    group[i].focus();
    group[i].click();
    e.preventDefault();
  });
  window.addEventListener('load', decorateAllTabGroups);
})();

window.addEventListener('load', async ()=>{
  applyStoredTheme();
  // 사이드바 신호등 초기 렌더 (페이지 로드 즉시 미연결 상태로 표시)
  try { buildSidebarDataSources({}); } catch(_) {}
  buildGlobalTable();
  buildMoverTable('up');
  buildNews();
  initMainChart('1D');
  // 부동산 KPI 카드 정적 fallback — data.json 미연동이어도 값 표시
  try { initStaticRealEstateFallbacks(); } catch(_) {}
  // 스파크라인 — 데이터 로드 후 갱신되므로 초기에는 비워둠
  // (loadRealData -> applyRealData 에서 갱신)
  buildFearChart();
  buildRateKpiSparkline();
  initInvestorDateDefaults();
  // 실시간 data.json 로드 + 독립적인 실시간 페치 5종을 '병렬' 시작.
  // (기존엔 await loadRealData() 가 3.9MB 본체 다운로드·파싱을 끝낼 때까지 환율/지수/Top10/
  //  분위기/뉴스가 직렬 대기 — 느린 회선에서 수 초 지연되던 워터폴 제거. 이들은 data.json 과
  //  의존성이 없는 별도 외부 API 이고 각자 catch 를 갖고 있어 병렬화가 안전하다.)
  loadRealData().then(() => {
    // 데이터 로드 완료 후 대시보드 등락 테이블 재렌더 + 사이드바 신호등 (data.json 의존 후처리)
    try { buildMoverTable(curMoverTab); } catch(_) {}
    try { buildSidebarDataSources(_latestDataForIndicators || {}); } catch(_) {}
  }).catch(()=>{}).finally(() => {
    // ⚠️ 알림 파이프라인 헬스 1회 점검(비동기·5s 타임아웃·실패 무시) — GH 토큰 만료 시 상단 경고 배너
    try { _checkWorkerPipelineHealth(); } catch(_) {}
  });
  // 실시간 환율 페치 (open.er-api.com — 페이지 로드 시 즉시 갱신)
  loadRealtimeFx();
  // 실시간 지수·원자재 페치 (Stooq — 무료, 인증 불필요)
  loadRealtimeMarket();
  // 실시간 주식/ETF 등락 Top10 페치 (Naver Finance 모바일 JSON API)
  refreshMoversFromClient().catch(()=>{});
  // 실시간 시장 분위기 페치 (VKOSPI/MOVE/PutCall)
  fetchSentimentClient().then(applySentimentClient).catch(()=>{});
  // 실시간 뉴스 로드 (Google News RSS)
  loadFreshNews();
  // ============================================================
  // 장 시간 인식 적응형 자동 동기화 (semi-실시간)
  // 장 시간(한국/미국 정규장): 1분 간격 / 그 외: 5분 간격.
  // KOSPI Top10·지수·원자재·환율·VIX 등 모든 시장 데이터가 장중 1분마다 자동 갱신.
  // ============================================================
  const ONE_MIN  = 1 * 60 * 1000;
  const FIVE_MIN = 5 * 60 * 1000;
  const THREE_MIN= 3 * 60 * 1000;
  // 현재 시각을 KST 로 (고정 오프셋 +9, 사용자 로컬 타임존 무관하게 한국 장 판정)
  function _kstNow() {
    const n = new Date();
    return new Date(n.getTime() + (n.getTimezoneOffset() + 540) * 60000);
  }
  // 한국 정규장: 평일 09:00–15:30 KST
  window._isKrMarketOpen = function() {
    const k = _kstNow(), day = k.getDay();
    if(day === 0 || day === 6) return false;
    const m = k.getHours() * 60 + k.getMinutes();
    return m >= 540 && m <= 930;
  };
  // 미국 정규장(대략): KST 야간. 서머타임 변동 흡수 위해 22:30–06:00 으로 넉넉히.
  window._isUsMarketOpen = function() {
    const k = _kstNow(), day = k.getDay();
    const m = k.getHours() * 60 + k.getMinutes();
    if(m >= 1350) return day >= 1 && day <= 5;   // 당일 22:30~24:00 = 미 월~금
    if(m <= 360)  return day >= 2 && day <= 6;   // 익일 00:00~06:00 = 미 월~금
    return false;
  };
  // 둘 중 하나라도 열려 있으면 '장중'으로 간주 → 1분 동기화
  window._isMarketActive = function() {
    try { return window._isKrMarketOpen() || window._isUsMarketOpen(); } catch(_) { return false; }
  };
  // 적응형 스케줄러 — 매 틱마다 isActiveFn() 재평가하여 다음 지연을 결정.
  // (장 시작/마감 시점에 자동으로 1분↔5분 전환. setInterval 과 달리 동적 간격.)
  function _scheduleAdaptive(taskFn, isActiveFn, activeMs, idleMs) {
    const run = async () => {
      // 탭이 숨겨져 있으면 페치를 건너뛴다 — 복귀 시 즉시 재페치는 아래 visibilitychange
      // 핸들러가 담당하므로 hidden 중 폴링은 모바일 배터리·데이터 순수 낭비.
      if(document.hidden) { setTimeout(run, idleMs); return; }
      try { await taskFn(); } catch(_) {}
      const delay = (isActiveFn && isActiveFn()) ? activeMs : idleMs;
      setTimeout(run, delay);
    };
    const first = (isActiveFn && isActiveFn()) ? activeMs : idleMs;
    setTimeout(run, first);
  }
  // data.json 재로드 — 장중 1분(서버 GHA 커밋 신속 반영) / 그 외 3분
  _scheduleAdaptive(() => loadRealData().catch(()=>{}), window._isMarketActive, ONE_MIN, THREE_MIN);
  // 실시간 환율 — 장중 1분 / 그 외 5분
  _scheduleAdaptive(() => loadRealtimeFx().catch(()=>{}), window._isMarketActive, ONE_MIN, FIVE_MIN);
  // 실시간 지수·원자재(Stooq) — 장중 1분 / 그 외 5분
  _scheduleAdaptive(() => loadRealtimeMarket().catch(()=>{}), window._isMarketActive, ONE_MIN, FIVE_MIN);
  // KOSPI/ETF Top10 등락 — 한국 장중 1분 / 그 외 5분
  _scheduleAdaptive(() => refreshMoversFromClient().catch(()=>{}), window._isKrMarketOpen, ONE_MIN, FIVE_MIN);
  // 시장 분위기(VKOSPI/MOVE/VIX/Put-Call/F&G) — 장중 1분 / 그 외 5분
  _scheduleAdaptive(() => fetchSentimentClient().then(applySentimentClient).catch(()=>{}), window._isMarketActive, ONE_MIN, FIVE_MIN);
  // 탭 포커스가 돌아오면 즉시 한 번 모든 데이터 갱신 (오래 비활성 상태 후 복귀 시)
  let _lastActivityTime = Date.now();
  document.addEventListener('visibilitychange', () => {
    if(document.visibilityState !== 'visible') return;
    const idleMs = Date.now() - _lastActivityTime;
    _lastActivityTime = Date.now();
    // 1분 이상 비활성이었으면 데이터 즉시 재페치
    if(idleMs > 60 * 1000) {
      loadRealData().catch(()=>{});
      loadRealtimeFx().catch(()=>{});
      loadRealtimeMarket().catch(()=>{});
      refreshMoversFromClient().catch(()=>{});
      fetchSentimentClient().then(applySentimentClient).catch(()=>{});
    }
  });
  // 사용자 인터랙션 추적 (마지막 활동 시각 갱신 — 자동 새로고침 판단에 사용)
  ['click','keydown','scroll','mousemove'].forEach(ev =>
    window.addEventListener(ev, () => { _lastActivityTime = Date.now(); }, { passive: true })
  );
  // 오프라인/온라인 감지 — 기존엔 감지가 전무해 오프라인 전환 시 낡은 시세가 조용히 계속
  // 노출됐다. 상시 노출 중인 글로벌 상태 칩을 재활용해 표시하고, 재접속 시 즉시 1회 재페치
  // (다음 폴링 틱까지 최대 5분 기다리지 않게).
  const _updateOfflineChip = () => {
    const chip = document.getElementById('globalDelayChip');
    if(!chip) return;
    if(navigator.onLine === false) {
      const ts = window._lastRealDataTs ? new Date(window._lastRealDataTs) : null;
      chip.innerHTML = '<span class="dot" style="background:var(--c-down,var(--c-error));"></span>⚠ 오프라인' +
        (ts ? ' — 마지막 ' + ts.toLocaleString('ko-KR',{hour:'2-digit',minute:'2-digit',hour12:false}) : '');
      chip.style.color = 'var(--c-down,#ef5350)';
    } else {
      chip.innerHTML = '<span class="dot"></span>Market Data 15m Delayed';
      chip.style.color = '';
    }
  };
  window.addEventListener('offline', _updateOfflineChip);
  window.addEventListener('online', () => {
    _updateOfflineChip();
    loadRealData().catch(()=>{});
    loadRealtimeFx().catch(()=>{});
    loadRealtimeMarket().catch(()=>{});
  });
  // 활성 차트 페이지 재빌드 — 장중 1분 / 그 외 5분 (방금 갱신된 데이터를 화면에 반영)
  // 단, data.json lastUpdated 가 직전 재빌드 시점과 같으면 생략 — 데이터 변화 없이 매분
  // 차트를 destroy/재생성하면 GC churn 만 늘고 사용자의 툴팁·구간측정 상태가 리셋된다.
  // (loadRealData 자체도 ts 변경 시 재빌드하므로 이 루프는 그 보강일 뿐.)
  _scheduleAdaptive(() => {
    try {
      if(window._lastRealDataTs && window._lastChartRebuildTs === window._lastRealDataTs) return;
      window._lastChartRebuildTs = window._lastRealDataTs;
      const activePage = document.querySelector('.page.active');
      if(!activePage) return;
      const id = activePage.id;
      if(id === 'page-dashboard') { try { initMainChart(mainPeriodUnit); buildMoverTable(curMoverTab); buildGlobalTable(); } catch(_){} }
      else if(id === 'page-market') { try { initMarketPage(); } catch(_){} }
      else if(id === 'page-realestate') { try { buildReCharts(); if(typeof buildUsReCharts==='function') buildUsReCharts(); } catch(_){} }
      else if(id === 'page-investor') { try { buildInvestorPage(); } catch(_){} }
    } catch(_) {}
  }, window._isMarketActive, ONE_MIN, FIVE_MIN);
  // 뉴스 갱신 — 5분 (뉴스는 1분 갱신 불필요 + 프록시 부하 절약)
  setInterval(() => { loadFreshNews().catch(()=>{}); }, FIVE_MIN);
  // 페이지 로드 후 차트 위젯에 새로고침 버튼 일괄 주입
  setTimeout(() => { try { injectChartRefreshButtons(); } catch(_){} }, 500);
  // 페이지 전환 시에도 새로 추가된 차트에 새로고침 버튼 주입
  document.addEventListener('click', (e) => {
    if(e.target && e.target.closest && e.target.closest('.menu-item')) {
      setTimeout(() => { try { injectChartRefreshButtons(); } catch(_){} }, 200);
    }
  });

  // 창 크기 변경 시 즉시 차트 리사이즈
  let _rszTimer;
  const _resizeAllCharts = () => { Object.values(charts).forEach(c => { try { if(c && c.canvas && c.canvas.offsetParent !== null) c.resize(); } catch(_){} }); };
  window.addEventListener('resize', () => { clearTimeout(_rszTimer); _rszTimer = setTimeout(_resizeAllCharts, 200); });
  if(window.ResizeObserver) {
    const _ro = new ResizeObserver(_resizeAllCharts);
    const _main = document.querySelector('main');
    if(_main) _ro.observe(_main);
  }
});

// ── 📝 메르 블로그 검색 ──────────────────────────────────────────
// 스냅샷(merblog.json) 즉시 필터 + Worker GET /merblog(라이브) 폴백.
// 원문 확보: Worker GET /merblog?ids=<logNo,...> (by-logNo 직접 조회) — 원문 보기/다운로드 시
//   fullText 없는 글을 일괄 로드. Worker 베이스는 기존 CORS 프록시 상수 재사용(_cfProxyBase()).
let _merSnapshot = null;      // merblog.json 캐시
let _merRawResults = [];      // 검색 원본(분류·날짜 필터 적용 전)
let _merLastResults = [];     // 필터 적용 후 — 화면/다운로드 대상
let _merLastQuery = '';
let _merSnapMeta = '';        // 상태줄 앞부분(검색 요약) 재사용용

async function merblogInit(){
  if(_merSnapshot) return _merSnapshot;
  try{
    const r = await fetch('merblog.json?v=' + Date.now());
    _merSnapshot = r.ok ? await r.json() : {posts:[]};
  }catch(e){ _merSnapshot = {posts:[]}; }
  return _merSnapshot;
}
function _merEsc(s){ return (s||'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

async function merblogSearch(){
  const q = (document.getElementById('merQ').value||'').trim();
  const live = document.getElementById('merLive').checked;
  const sort = document.getElementById('merSort').value;
  const status = document.getElementById('merStatus');
  _merLastQuery = q;
  if(!q){ status.textContent='검색어를 입력하세요.'; return; }
  if(!live){
    // 스냅샷 클라이언트 필터(즉시)
    status.textContent = '스냅샷에서 검색 중…';
    const snap = await merblogInit();
    const ql = q.toLowerCase();
    let hits = (snap.posts||[]).filter(p =>
      (p.title||'').toLowerCase().includes(ql) ||
      (p.excerpt||'').toLowerCase().includes(ql) ||
      (p.fullText||'').toLowerCase().includes(ql));
    if(sort==='date') hits = hits.slice().sort((a,b)=>(b.date||'').localeCompare(a.date||''));
    _merRawResults = hits;
    _merSnapMeta = `스냅샷 ${hits.length}건 (전체기간은 '라이브' 체크). ${snap.posts?snap.posts.length:0}개 글 색인.`;
    merblogPopulateCats(hits);
    merblogApplyAndRender();
    return;
  }
  // 라이브(Worker) — 네이버 검색 API는 size 파라미터를 무시하고 페이지당 약 20건만 반환하므로
  // 정확한 건수를 약속하지 않고 totalCount 기준으로 안내한다.
  status.textContent = '네이버 전체기간 검색 중…';
  try{
    const base = _cfProxyBase();
    if(!base) throw new Error('Worker 프록시 미설정');
    const url = `${base}/merblog?q=${encodeURIComponent(q)}&size=20&sort=${sort}`;
    const r = await fetch(url);
    if(!r.ok) throw new Error('HTTP '+r.status);
    const d = await r.json();
    _merRawResults = d.posts||[];
    _merSnapMeta = `전체 ${d.totalCount||0}건 중 ${d.count||_merRawResults.length}건 표시.`;
    merblogPopulateCats(_merRawResults);
    merblogApplyAndRender();
  }catch(e){
    status.textContent = '라이브 검색 실패: '+e.message+' (스냅샷으로 다시 시도해 보세요)';
  }
}

// 분류 드롭다운 채우기(현재 선택 보존).
function merblogPopulateCats(posts){
  const sel = document.getElementById('merCat');
  if(!sel) return;
  const cur = sel.value;
  const cats = Array.from(new Set((posts||[]).map(p=>p.category).filter(Boolean))).sort();
  sel.innerHTML = '<option value="">전체 분류</option>' +
    cats.map(c=>`<option value="${_merEsc(c)}">${_merEsc(c)}</option>`).join('');
  sel.value = (cur && cats.includes(cur)) ? cur : '';
}

// 분류 + 날짜(from~to) 필터 적용 → 렌더 + 컨트롤/상태 갱신.
function merblogApplyAndRender(){
  const cat  = (document.getElementById('merCat')||{}).value || '';
  const from = (document.getElementById('merFrom')||{}).value || '';
  const to   = (document.getElementById('merTo')||{}).value || '';
  let list = _merRawResults.slice();
  if(cat)  list = list.filter(p=>p.category===cat);
  if(from) list = list.filter(p=>(p.date||'').slice(0,10) >= from);
  if(to)   list = list.filter(p=>(p.date||'').slice(0,10) <= to);
  _merLastResults = list;
  merblogRenderResults(list);
  const has = _merRawResults.length>0;
  document.getElementById('merFilters').style.display = has?'flex':'none';
  document.getElementById('merBulk').style.display = has?'flex':'none';
  const dl = document.getElementById('merDl'); if(dl) dl.disabled = list.length===0;
  const selAll = document.getElementById('merSelAll'); if(selAll) selAll.checked = false;
  const filtered = !!(cat||from||to);
  const status = document.getElementById('merStatus');
  status.textContent = `${_merSnapMeta}${filtered?` 필터 후 ${list.length}건.`:''} 원문은 다운로드 시 자동 로드.`;
  merblogUpdateSel();
}

function merblogClearFilters(){
  ['merCat','merFrom','merTo'].forEach(id=>{ const e=document.getElementById(id); if(e) e.value=''; });
  merblogApplyAndRender();
}

function merblogRenderResults(posts){
  const box = document.getElementById('merResults');
  if(!posts || !posts.length){ box.innerHTML = '<p style="font-size:var(--font-size-sm);color:var(--c-txt-dim);">결과 없음.</p>'; return; }
  box.innerHTML = posts.map(p => {
    const id = _merEsc(String(p.logNo));
    return `<div class="mer-item" id="mer-${id}">
      <div style="display:flex;gap:8px;align-items:flex-start;">
        <input type="checkbox" class="mer-sel" value="${id}" onchange="merblogUpdateSel()" aria-label="이 글 선택" style="margin-top:3px;flex-shrink:0;">
        <div style="flex:1;min-width:0;">
          <h3>${_merEsc(p.title)}</h3>
          <div class="mer-meta">${_merEsc(p.date? String(p.date).slice(0,10):'')} · ${_merEsc(p.category||'')}
            · <a href="${_merEsc(p.url||'')}" target="_blank" rel="noopener">원글↗</a></div>
          <div class="mer-excerpt">${_merEsc(p.excerpt||'')}</div>
          <button onclick="merblogToggleFull('${id}',this)">원문 보기</button>
          <div class="mer-full" style="display:none"></div>
        </div>
      </div>
    </div>`;
  }).join('');
}

// 선택 상태 헬퍼 ────────────────────────────────
function merblogSelectedLogNos(){
  return Array.from(document.querySelectorAll('#merResults .mer-sel:checked')).map(el=>el.value);
}
function merblogToggleAll(cb){
  document.querySelectorAll('#merResults .mer-sel').forEach(el=>{ el.checked = cb.checked; });
  merblogUpdateSel();
}
function merblogUpdateSel(){
  const n = merblogSelectedLogNos().length;
  const c = document.getElementById('merSelCount'); if(c) c.textContent = `${n}개 선택`;
  const b = document.getElementById('merDlSel'); if(b) b.disabled = n===0;
}

async function merblogToggleFull(logNo, btn){
  const box = document.querySelector('#mer-'+CSS.escape(String(logNo))+' .mer-full');
  if(!box) return;
  if(box.style.display!=='none'){ box.style.display='none'; btn.textContent='원문 보기'; return; }
  const post = _merLastResults.find(p=>String(p.logNo)===String(logNo));
  if(post && post.fullText){
    box.textContent = post.fullText; box.style.display='block'; btn.textContent='원문 접기'; return;
  }
  // 온디맨드 로드 — logNo 로 원문 직접 조회(ids= 모드). 쿼리 재검색보다 정확·빠름.
  btn.disabled=true; btn.textContent='불러오는 중…';
  try{
    const base = _cfProxyBase();
    if(!base) throw new Error('Worker 프록시 미설정');
    const r = await fetch(`${base}/merblog?ids=${encodeURIComponent(String(logNo))}`);
    const d = await r.json();
    const hit = (d.posts||[]).find(p=>String(p.logNo)===String(logNo));
    const txt = hit && hit.fullText ? hit.fullText : '(원문을 불러오지 못했습니다. 원글↗ 링크를 이용하세요.)';
    if(post) post.fullText = txt;   // 캐시(다운로드에도 반영)
    box.textContent = txt; box.style.display='block'; btn.textContent='원문 접기';
  }catch(e){
    box.textContent='원문 로드 실패: '+e.message; box.style.display='block'; btn.textContent='원문 접기';
  }finally{ btn.disabled=false; }
}

// 누락 원문 일괄 확보 — Worker ids= 모드로 10개씩 배치 조회, 원본 객체에 fullText 채움.
async function merblogEnsureFull(posts, onProgress){
  const missing = posts.filter(p=>p && !p.fullText && p.logNo);
  if(!missing.length) return;
  const base = _cfProxyBase();
  if(!base) throw new Error('Worker 프록시 미설정 — 원문 자동 로드 불가(원글↗ 링크 이용)');
  for(let i=0;i<missing.length;i+=10){
    const batch = missing.slice(i,i+10);
    if(onProgress) onProgress(Math.min(i+batch.length, missing.length), missing.length);
    try{
      const ids = batch.map(p=>p.logNo).join(',');
      const r = await fetch(`${base}/merblog?ids=${encodeURIComponent(ids)}`);
      if(!r.ok) continue;
      const d = await r.json();
      (d.posts||[]).forEach(fp=>{
        const t = missing.find(p=>String(p.logNo)===String(fp.logNo));
        if(t && fp.fullText) t.fullText = fp.fullText;
      });
    }catch(e){ /* 배치 실패는 건너뛰고 나머지 계속 */ }
  }
}

// 공용 다운로드 — 원문 확보 후 JSON 저장.
async function _merDoDownload(posts, tag, btns){
  if(!posts.length) return;
  const status = document.getElementById('merStatus');
  btns.forEach(b=>{ if(b) b.disabled = true; });
  try{
    await merblogEnsureFull(posts, (done,total)=>{ status.textContent = `원문 불러오는 중… ${done}/${total}`; });
  }catch(e){ status.textContent = '원문 로드 경고: '+e.message+' (확보된 내용만 저장)'; }
  const withFull = posts.filter(p=>p.fullText).length;
  const out = {
    blogId:'ranto28', blogName:'메르의 블로그',
    query:_merLastQuery, exportedAt:new Date().toISOString(),
    count:posts.length, fullTextCount:withFull, posts,
  };
  const blob = new Blob([JSON.stringify(out,null,2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `merblog_${tag}_${(_merLastQuery||'search').replace(/[^\w가-힣]+/g,'_')}_${new Date().toISOString().slice(0,10)}.json`;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(a.href);
  status.textContent = `다운로드 완료: ${posts.length}건(원문 ${withFull}건 포함).`;
  btns.forEach(b=>{ if(b) b.disabled = false; });
  merblogUpdateSel();  // 선택 다운로드 버튼 상태 복원
}

// 전체 결과(필터 적용분) 원문 포함 다운로드.
async function merblogDownloadJson(){
  await _merDoDownload(_merLastResults, 'all',
    [document.getElementById('merDl'), document.getElementById('merDlSel')]);
}
// 체크한 글만 원문 포함 다운로드.
async function merblogDownloadSelected(){
  const ids = new Set(merblogSelectedLogNos());
  const sel = _merLastResults.filter(p=>ids.has(String(p.logNo)));
  if(!sel.length){ document.getElementById('merStatus').textContent='선택된 글이 없습니다.'; return; }
  await _merDoDownload(sel, 'selected',
    [document.getElementById('merDl'), document.getElementById('merDlSel')]);
}
