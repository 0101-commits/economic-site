/* ============================================================
   app7.js — 메르 리스크 렌즈 (P3-1: 블록 ①③③b + 출처 패널)
   블록 ②전이경로·④매트릭스·⑤뷰 타임라인·⑥이벤트 는 2부 — 컨테이너만 여기 존재, 손대지 말 것.
   의존(로드 순서상 앞): app1(getThemeColors/_cfProxyBase/_latestDataForIndicators/_merEsc/
        charts/destroyChart), app3(computeRiskScore), app6(_pfSpark)
   데이터 원본: mer_signals.json (P2 산출, 읽기 전용) — 신규 수집 없음.
   ============================================================ */

// §6.0 대조표 — JSON 키·enum 은 그대로, 화면 글자만 여기서 정한다.
var MER_LABELS = {
  state: { below: '정상', near: '주시', crossed: '돌파', unknown: 'N/A' },
  view:  { '-2': '강한 UW', '-1': 'UW', '0': 'N', '1': 'OW', '2': '강한 OW' },
  layer: { cause: '원인', market: '시장 변수', channel: '창구', asset: '자산' },
  kind:  { level: '레벨', calendar: '캘린더', counter: '재고 일수', qualitative: '정성' },
};
var MER_STATE_TONE = { below: 'positive', near: 'warning', crossed: 'critical', unknown: 'neutral' };
var MER_STATE_PRIORITY = { crossed: 0, near: 1, below: 2, unknown: 3 };

var _merSignalsData = null;
var _merSignalsPromise = null;
var _merMonitorFilter = 'all';
var _merLastFocusEl = null;

// ── 탭: 보드 / 글 찾기(P5-1, 구 page-merblog 이식) — pfShowTab(app6.js) 과 동일 패턴 ──
var MER_TABS = ['board', 'search'];
var _merActiveTab = 'board';
function _merShowTab(name, noUrl) {
  if (MER_TABS.indexOf(name) < 0) name = 'board';
  _merActiveTab = name;
  MER_TABS.forEach(function (t) {
    var pane = document.getElementById('merlensTab-' + t);
    if (pane) pane.style.display = (t === name) ? '' : 'none';
    var btn = document.getElementById('merlensTabBtn-' + t);
    if (btn) {
      var on = (t === name);
      btn.style.background = on ? 'var(--c-accent)' : 'transparent';
      btn.style.color = on ? 'var(--c-on-accent)' : 'var(--c-txt-dim)';
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    }
  });
  // 보드 탭 렌더는 여기서만 트리거한다 — "글 찾기"만 볼 때 전이경로 SVG 등 무거운 블록
  // 6개를 전부 그리지 않는다(gridcheck 의 role="button" 0 어서션이 merblog 별칭 경유로
  // 우연히 보드까지 렌더시키는 걸 잡아냄 — 손대지 말라던 그래프 SVG 자체는 그대로 둔다).
  if (name === 'board') { try { merlensInit(); } catch (e) { console.warn('merlens init', e); } }
  if (!noUrl) {
    try {
      var u = new URL(location.href);
      u.searchParams.set('p', 'merlens'); u.searchParams.set('t', name);
      history.replaceState(null, '', u.pathname + u.search);
    } catch (_) {}
  }
}

function _merFetchSignals() {
  if (_merSignalsPromise) return _merSignalsPromise;
  _merSignalsPromise = fetch('mer_signals.json?v=' + Date.now())
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function (d) { _merSignalsData = d; return d; })
    .catch(function (e) { _merSignalsPromise = null; throw e; });
  return _merSignalsPromise;
}

function merlensInit() {
  var errEl = document.getElementById('merlensError');
  _merFetchSignals().then(function (d) {
    if (errEl) errEl.style.display = 'none';
    _merRenderAll(d);
  }).catch(function (e) {
    console.warn('merlens signals fetch', e);
    if (errEl) errEl.style.display = '';
  });
}

function _merRenderAll(d) {
  _merRenderFresh(d);
  _merRenderGauges(d);
  _merRenderRegime(d);
  _merRenderComment(d);
  _merRenderMonitor(d);
  _merRenderPanels(d);
  // P3 2부
  _merRenderGraph(d);
  _merRenderMatrix(d);
  _merRenderStanceTimeline(d);
  _merRenderFactorCard(d);
  _merRenderEvents(d);
}
// ── 홈 L1-b 리스크 신호등 옆 MRI 칩(P4-2) — app3.js renderRiskLight() 말미가 매번 부른다.
// 시장 실측 신호등과는 별개 층(기획안 §1 원칙 3) — 합산하지 않고 병렬 표기만 한다.
// mer_signals.json 을 못 읽으면(파일 없음/네트워크 실패) 칩을 아예 숨긴다 — 빈 칩·0 표시 금지.
function _merRenderMriChip() {
  var chip = document.getElementById('merMriChip'), val = document.getElementById('merMriChipVal');
  if (!chip || !val) return;
  _merFetchSignals().then(function (d) {
    var lens = d.lens || {};
    if (lens.score == null) { chip.style.display = 'none'; return; }
    // lens.components.thresholdsCrossed 는 **점수 성분(0~40)**이지 지표 개수가 아니다.
    // 그걸 그대로 쓰면 "돌파 40" 이라고 뜬다(실측 오탐). 개수는 indicators 에서 센다.
    var crossed = (d.indicators || []).filter(function (i) { return i.state === 'crossed'; }).length;
    val.textContent = Math.round(lens.score) + ' · 돌파 ' + crossed;
    chip.style.display = '';
  }).catch(function () { chip.style.display = 'none'; });
}

// data.json 은 별도 파이프라인이라 ?p=merlens 딥링크로 곧장 들어오면 loadRealData 의 적용 함수가
// 아직 안 끝났을 수 있다 — 그 적용 함수 말미(app1.js, renderRiskLight 옆)가 매번 이걸 부른다.
// 페이지가 이미 렌더돼 있고(= merlensInit 통과) 지금 활성일 때만 시세 의존 블록만 다시 그린다.
function merlensOnMarketData() {
  var page = document.getElementById('page-merlens');
  if (!page || !page.classList.contains('active') || !_merSignalsData) return;
  _merRenderFresh(_merSignalsData);
  _merRenderGauges(_merSignalsData);
}

// ── 헤더 · 기준시점 (§6.4) ──────────────────────────────────────────
function _merRenderFresh(d) {
  var el = document.getElementById('merlensFresh');
  if (!el) return;
  var mkt = (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators) || {};
  var mktTs = mkt.lastUpdated ? new Date(mkt.lastUpdated).toLocaleString('ko-KR') : '—';
  var posts = d.posts || [];
  var lastPost = posts[posts.length - 1];
  var postTxt = lastPost ? (lastPost.date + ' (logNo ' + lastPost.logNo + ')') : '—';
  var stale = false;
  try { stale = (Date.now() - new Date(d.asOf).getTime()) / 86400000 > 7; } catch (_) {}
  var badge = stale
    ? '<span class="seed-badge__root seed-badge__root--size_medium seed-badge__root--tone_warning-variant_weak">오래됨</span>'
    : '';
  el.innerHTML =
    '<span>시세 기준 ' + _merEsc(mktTs) + '</span>' +
    '<span>글 기준 ' + _merEsc(postTxt) + '</span>' +
    '<span>표본 ' + ((d.coverage && (d.coverage.posts + '건 (추출 ' + d.coverage.extracted + ')')) || '—') + '</span>' +
    '<span>집계 ' + _merEsc(d.asOf ? d.asOf.slice(0, 16).replace('T', ' ') : '—') + '</span>' +
    '<span>사전 ' + _merEsc(d.dictVersion || '—') + '</span>' + badge;
}

// ── 블록 ① 리스크 게이지 ────────────────────────────────────────────
function _merGaugeSvg(value) {
  var w = 160, h = 100, cx = w / 2, cy = h - 8, r = w / 2 - 14;
  var toXY = function (deg) {
    var rad = deg * Math.PI / 180;
    return [cx + r * Math.cos(rad), cy - r * Math.sin(rad)];
  };
  var bands = [
    { from: 0, to: 35, color: 'var(--color-success)' },
    { from: 35, to: 65, color: 'var(--color-warning)' },
    { from: 65, to: 100, color: 'var(--color-error)' },
  ];
  var arcs = bands.map(function (b) {
    var a1 = 180 - b.from / 100 * 180, a2 = 180 - b.to / 100 * 180;
    var p1 = toXY(a1), p2 = toXY(a2);
    return '<path d="M ' + p1[0].toFixed(1) + ' ' + p1[1].toFixed(1) +
      ' A ' + r + ' ' + r + ' 0 0 1 ' + p2[0].toFixed(1) + ' ' + p2[1].toFixed(1) +
      '" fill="none" stroke="' + b.color + '" stroke-width="14"/>';
  }).join('');
  var hasVal = value != null && isFinite(value);
  var v = hasVal ? Math.max(0, Math.min(100, value)) : 0;
  var needleDeg = 180 - v / 100 * 180;
  var nxy = toXY(needleDeg);
  var needle = hasVal
    ? '<line x1="' + cx + '" y1="' + cy + '" x2="' + nxy[0].toFixed(1) + '" y2="' + nxy[1].toFixed(1) +
      '" stroke="var(--c-txt)" stroke-width="2.5" stroke-linecap="round"/>' +
      '<circle cx="' + cx + '" cy="' + cy + '" r="4" fill="var(--c-txt)"/>'
    : '';
  return '<svg viewBox="0 0 ' + w + ' ' + h + '" width="' + w + '" height="' + h +
    '" role="img" aria-label="게이지 값 ' + (hasVal ? Math.round(v) : 'N/A') + '">' + arcs + needle + '</svg>' +
    '<div class="mer-gauge-val">' + (hasVal ? Math.round(v) : 'N/A') + '</div>';
}

function _merRenderGauges(d) {
  var mktBox = document.getElementById('merlensGaugeMarket');
  var mriBox = document.getElementById('merlensGaugeMri');
  var mktData = (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators) || null;
  var mktScore = null;
  try { var r = (typeof computeRiskScore === 'function') ? computeRiskScore(mktData) : null; mktScore = r ? r.score : null; } catch (_) {}
  var lens = d.lens || {};
  if (mktBox) mktBox.innerHTML = _merGaugeSvg(mktScore);
  if (mriBox) mriBox.innerHTML = _merGaugeSvg(lens.score);

  var trendBox = document.getElementById('merlensMriTrend');
  if (trendBox) {
    var tc = (typeof getThemeColors === 'function') ? getThemeColors() : null;
    var series = (lens.history30d || []).map(function (p) { return p.score; });
    var svg = (typeof _pfSpark === 'function') ? _pfSpark(series, tc ? tc.accent : 'var(--c-accent)') : '';
    trendBox.innerHTML = svg ? '<div class="mer-panel-title">MRI 30일 추이</div>' + svg : '';
  }

  var chipsBox = document.getElementById('merlensMriChips');
  if (chipsBox) {
    var comps = lens.components || {};
    var CHIP_LABEL = { thresholdsCrossed: '임계 돌파', negativeStance30d: '부정 스탠스(30일)', riskFlags30d: '리스크 플래그(30일)' };
    chipsBox.innerHTML = Object.keys(CHIP_LABEL).map(function (k) {
      if (comps[k] == null) return '';
      return '<span class="seed-badge__root seed-badge__root--size_medium seed-badge__root--tone_neutral-variant_weak">' +
        _merEsc(CHIP_LABEL[k]) + ' ' + comps[k] + '</span>';
    }).join('');
  }
}

// ── 국면 스트립 ──────────────────────────────────────────────────────
// months 는 코퍼스를 정독한 구간만큼만 채워진다(전체 기간 중 일부일 수 있음) — 빈 달을
// 지어내지 않고, 옆에 "정독 구간 N개월(전체 M개월 중)" 으로 표본 실태를 그대로 밝힌다.
function _merMonthSpan(fromStr, toStr) {
  try {
    var f = new Date(fromStr), t = new Date(toStr);
    return (t.getFullYear() - f.getFullYear()) * 12 + (t.getMonth() - f.getMonth()) + 1;
  } catch (_) { return null; }
}
function _merRenderRegime(d) {
  var box = document.getElementById('merlensRegime');
  var note = document.getElementById('merlensRegimeNote');
  if (!box) return;
  var regime = d.regime || {};
  var months = regime.months || [], dominant = regime.dominant || [], factors = regime.factors || [];
  if (note) {
    var total = d.window ? _merMonthSpan(d.window.from, d.window.to) : null;
    note.textContent = total
      ? '정독 구간 ' + months.length + '개월(전체 ' + total + '개월 중)'
      : '정독 구간 ' + months.length + '개월';
  }
  box.innerHTML = months.map(function (m, i) {
    var f = dominant[i] || '—';
    var idx = factors.indexOf(f);
    var colorVar = 'var(--color-series-' + (((idx >= 0 ? idx : 0) % 4) + 1) + ')';
    return '<div class="mer-regime-cell" style="background:' + colorVar + '">' +
      '<span class="mer-regime-m">' + _merEsc(m) + '</span>' +
      '<span class="mer-regime-f">' + _merEsc(f) + '</span></div>';
  }).join('');
}

// ── 최근 한줄 코멘트 ─────────────────────────────────────────────────
function _merRenderComment(d) {
  var box = document.getElementById('merlensComment');
  if (!box) return;
  var posts = d.posts || [];
  var last = posts[posts.length - 1];
  if (!last) { box.textContent = '표시할 글이 없습니다.'; return; }
  var txt = (last.one_liner || '').slice(0, 120);
  var url = 'https://blog.naver.com/ranto28/' + encodeURIComponent(String(last.logNo));
  box.innerHTML = _merEsc(txt) + (txt.length >= 120 ? '…' : '') +
    ' <a href="' + url + '" target="_blank" rel="noopener">원문 ↗</a>';
}

// ── 블록 ③ 트리거 모니터 ────────────────────────────────────────────
function _merLatestThreshold(ind) {
  var arr = (ind.thresholds || []).slice().sort(function (a, b) { return (b.date || '').localeCompare(a.date || ''); });
  return arr[0] || null;
}
function _merLadderSvg(ind) {
  var W = 150, H = 22;
  var levels = (ind.thresholds || []).filter(function (t) { return t.kind === 'level' && t.level != null; });
  var cur = ind.current ? ind.current.value : null;
  if (!levels.length) return '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" aria-hidden="true"></svg>';
  var vals = levels.map(function (t) { return t.level; });
  if (cur != null) vals = vals.concat([cur]);
  var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
  var pad = (hi - lo) * 0.2 || 1;
  lo -= pad; hi += pad;
  var span = (hi - lo) || 1;
  var x = function (v) { return ((v - lo) / span * (W - 10) + 5).toFixed(1); };
  var line = '<line x1="5" y1="11" x2="' + (W - 5) + '" y2="11" stroke="var(--c-border)" stroke-width="1"/>';
  var ticks = levels.map(function (t) {
    var passed = cur != null && (t.dir === 'down' ? cur <= t.level : cur >= t.level);
    var xx = x(t.level);
    return '<line x1="' + xx + '" y1="4" x2="' + xx + '" y2="18" stroke="var(--c-txt-dim)" stroke-width="2"' +
      (passed ? ' opacity=".35"' : '') + '><title>' + _merEsc(t.levelText || String(t.level)) + '</title></line>';
  }).join('');
  var dot = cur != null
    ? '<circle cx="' + x(cur) + '" cy="11" r="4" fill="var(--c-accent)"><title>현재값 ' + cur + '</title></circle>'
    : '';
  return '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H +
    '" role="img" aria-label="트리거 래더">' + line + ticks + dot + '</svg>';
}
function _merStateBadge(state) {
  var tone = MER_STATE_TONE[state] || 'neutral';
  return '<span class="seed-badge__root seed-badge__root--size_medium seed-badge__root--tone_' + tone + '-variant_weak">' +
    (MER_LABELS.state[state] || state) + '</span>';
}
function _merMonitorRowHtml(ind) {
  var t = _merLatestThreshold(ind);
  var stale6m = false;
  if (t && t.date) { try { stale6m = (Date.now() - new Date(t.date).getTime()) / 86400000 > 182; } catch (_) {} }
  var dim = stale6m ? ' mer-dim' : '';
  var cur = ind.current ? (ind.current.value + (ind.unit || '')) : '—';
  var nearestTxt = (ind.nearest && ind.nearest.level != null)
    ? (ind.nearest.level + (ind.unit || '') + ' <span class="econ-stat__unit">(' +
       (ind.nearest.distancePct != null ? ind.nearest.distancePct.toFixed(1) + '%)</span>' : '—)</span>'))
    : '—';
  var srcTxt = t ? (_merEsc(t.date || '') + ' · ' + _merEsc((t.quote || '').slice(0, 40)) +
    (t.logNo ? ' <a href="https://blog.naver.com/ranto28/' + encodeURIComponent(String(t.logNo)) + '" target="_blank" rel="noopener">↗</a>' : '')) : '—';
  return '<tr onclick="_merOpenSource(\'' + ind.id + '\',this)" style="cursor:pointer;" data-mer-state="' + ind.state + '" class="' + dim.trim() + '">' +
    '<td><button type="button" class="btn-plain btn-inline">' + _merEsc(ind.label) + '</button></td>' +
    '<td class="econ-table--num">' + _merEsc(cur) + '</td>' +
    '<td class="mer-ladder-cell">' + _merLadderSvg(ind) + '</td>' +
    '<td>' + nearestTxt + '</td>' +
    '<td>' + _merStateBadge(ind.state) + '</td>' +
    '<td style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">' + srcTxt + '</td>' +
    '</tr>';
}
var _merMonitorIndicators = [];
function _merRenderMonitor(d) {
  _merMonitorIndicators = (d.indicators || []).slice().sort(function (a, b) {
    var da = (a.nearest && a.nearest.distancePct != null) ? a.nearest.distancePct : Infinity;
    var db = (b.nearest && b.nearest.distancePct != null) ? b.nearest.distancePct : Infinity;
    return da - db;
  });
  var filtBox = document.getElementById('merlensMonitorFilters');
  if (filtBox && !filtBox.dataset.built) {
    var opts = [['all', '전체'], ['crossed', '돌파'], ['near', '주시'], ['below', '정상'], ['unknown', 'N/A']];
    filtBox.innerHTML = opts.map(function (o) {
      return '<button type="button" class="seed-chip__root seed-chip__root--variant_outlineWeak seed-chip__root--size_small seed-chip__root--size_small-layout_withText" ' +
        'data-mer-filter="' + o[0] + '" aria-pressed="' + (o[0] === 'all' ? 'true' : 'false') + '" onclick="_merSetMonitorFilter(\'' + o[0] + '\',this)">' +
        '<span class="seed-chip__label seed-chip__label--size_small seed-chip__label--variant_outlineWeak">' + o[1] + '</span></button>';
    }).join('');
    filtBox.dataset.built = '1';
  }
  _merRenderMonitorBody();
}
function _merRenderMonitorBody() {
  var body = document.getElementById('merlensMonitorBody');
  if (!body) return;
  var list = _merMonitorIndicators.filter(function (ind) { return _merMonitorFilter === 'all' || ind.state === _merMonitorFilter; });
  body.innerHTML = list.map(_merMonitorRowHtml).join('') || '<tr><td colspan="6" style="color:var(--c-txt-dim);">해당 상태의 지표가 없습니다.</td></tr>';
}
function _merSetMonitorFilter(state, btn) {
  _merMonitorFilter = state;
  var box = document.getElementById('merlensMonitorFilters');
  if (box) box.querySelectorAll('[data-mer-filter]').forEach(function (b) { b.setAttribute('aria-pressed', b === btn ? 'true' : 'false'); });
  _merRenderMonitorBody();
}

// ── 블록 ③-b 소형 다중 차트 ─────────────────────────────────────────
var _merPanelChartIds = [];
function _merPickPanelIndicators(d) {
  var arr = (d.indicators || []).filter(function (i) { return i.history1y && i.history1y.length > 1; });
  arr = arr.slice().sort(function (a, b) {
    var pa = MER_STATE_PRIORITY[a.state] != null ? MER_STATE_PRIORITY[a.state] : 9;
    var pb = MER_STATE_PRIORITY[b.state] != null ? MER_STATE_PRIORITY[b.state] : 9;
    return pa - pb;
  });
  return arr.slice(0, 8);
}
function _merRenderPanels(d) {
  var grid = document.getElementById('merlensPanelsGrid');
  if (!grid || typeof Chart === 'undefined') return;
  _merPanelChartIds.forEach(function (id) { destroyChart(id); });
  _merPanelChartIds = [];
  var picks = _merPickPanelIndicators(d);
  grid.innerHTML = picks.map(function (ind) {
    return '<div><div class="mer-panel-title">' + _merEsc(ind.label) + '</div><div class="h-200"><canvas id="merlensPanel_' + ind.id + '"></canvas></div></div>';
  }).join('') || '<p class="mer-stub">표시할 지표가 없습니다.</p>';
  var tc = (typeof getThemeColors === 'function') ? getThemeColors() : { accent: '#41a2f9', series: [], txt: '#8d90a2', grid: '#2a2e3d55' };
  picks.forEach(function (ind) {
    var canvasId = 'merlensPanel_' + ind.id;
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    var labels = ind.history1y.map(function (p) { return p.date; });
    var values = ind.history1y.map(function (p) { return p.value; });
    var datasets = [{
      label: ind.label, data: values, borderColor: tc.accent, backgroundColor: 'transparent',
      borderWidth: 1.6, pointRadius: 0, tension: 0.15,
    }];
    var seenLv = {};
    (ind.thresholds || []).filter(function (t) { return t.kind === 'level' && t.level != null; }).forEach(function (t) {
      if (seenLv[t.level]) return; seenLv[t.level] = true;
      datasets.push({
        label: t.levelText || String(t.level), data: labels.map(function () { return t.level; }),
        borderColor: tc.series[1] || tc.accent, borderDash: [4, 4], borderWidth: 1, pointRadius: 0, tension: 0,
      });
    });
    var finiteVals = values.filter(function (v) { return v != null && isFinite(v); });
    if (ind.postDates && ind.postDates.length && finiteVals.length) {
      var minV = Math.min.apply(null, finiteVals);
      var postSet = {};
      ind.postDates.forEach(function (pd) { postSet[pd] = true; });
      datasets.push({
        label: '글 발행일', data: labels.map(function (lb) { return postSet[lb] ? minV : null; }),
        borderColor: 'transparent', backgroundColor: tc.series[3] || tc.accent,
        pointRadius: 3, pointStyle: 'triangle', showLine: false,
      });
    }
    charts[canvasId] = new Chart(canvas, {
      type: 'line',
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { maxTicksLimit: 6, color: tc.txt }, grid: { color: tc.grid } },
          y: { ticks: { color: tc.txt }, grid: { color: tc.grid } },
        },
      },
    });
    _merPanelChartIds.push(canvasId);
  });
}

// ── 출처 패널 ────────────────────────────────────────────────────────
function _merOpenSource(indId, triggerEl) {
  if (!_merSignalsData) return;
  var ind = (_merSignalsData.indicators || []).find(function (i) { return i.id === indId; });
  if (!ind) return;
  var t = _merLatestThreshold(ind);
  _merLastFocusEl = triggerEl || document.activeElement;
  var q = document.getElementById('merlensSourceQuote');
  var meta = document.getElementById('merlensSourceMeta');
  var full = document.getElementById('merlensSourceFull');
  if (full) { full.style.display = 'none'; full.textContent = ''; }
  if (!t) {
    if (q) q.textContent = ind.label + ' — 아직 연결된 인용이 없습니다.';
    if (meta) meta.innerHTML = '';
    return;
  }
  if (q) q.textContent = t.quote || '';
  var url = 'https://blog.naver.com/ranto28/' + encodeURIComponent(String(t.logNo));
  if (meta) meta.innerHTML =
    '<div style="font-weight:700;color:var(--c-txt);">' + _merEsc(ind.label) + '</div>' +
    '<div>' + _merEsc(t.date || '') + (t.levelText ? ' · ' + _merEsc(t.levelText) : '') + '</div>' +
    '<div><a href="' + url + '" target="_blank" rel="noopener">원문 ↗</a></div>' +
    '<button type="button" class="btn-plain" style="border:1px solid var(--c-border);border-radius:var(--r-xs);padding:4px 10px;" ' +
    'onclick="_merLoadFullText(\'' + _merEsc(String(t.logNo)) + '\',this)">원문 보기</button>';
  var panel = document.getElementById('merlensSource');
  if (panel) { panel.setAttribute('tabindex', '-1'); try { panel.focus({ preventScroll: true }); } catch (_) {} }
}
function _merCloseSource() {
  var q = document.getElementById('merlensSourceQuote');
  var meta = document.getElementById('merlensSourceMeta');
  var full = document.getElementById('merlensSourceFull');
  if (q) q.textContent = '표에서 지표를 선택하면 관련 인용이 여기 표시됩니다.';
  if (meta) meta.innerHTML = '';
  if (full) { full.style.display = 'none'; full.textContent = ''; }
  if (_merLastFocusEl && _merLastFocusEl.focus) { try { _merLastFocusEl.focus(); } catch (_) {} }
  _merLastFocusEl = null;
}
async function _merLoadFullText(logNo, btn) {
  var full = document.getElementById('merlensSourceFull');
  if (!full) return;
  if (full.style.display !== 'none') { full.style.display = 'none'; if (btn) btn.textContent = '원문 보기'; return; }
  if (btn) { btn.disabled = true; btn.textContent = '불러오는 중…'; }
  try {
    var base = (typeof _cfProxyBase === 'function') ? _cfProxyBase() : '';
    if (!base) throw new Error('Worker 프록시 미설정');
    var r = await fetch(base + '/merblog?ids=' + encodeURIComponent(String(logNo)));
    var d = await r.json();
    var hit = (d.posts || []).find(function (p) { return String(p.logNo) === String(logNo); });
    full.textContent = (hit && hit.fullText) ? hit.fullText : '(원문을 불러오지 못했습니다. 원글↗ 링크를 이용하세요.)';
  } catch (e) {
    full.textContent = '원문을 불러오지 못했습니다. 원글↗ 링크를 이용하세요. (' + e.message + ')';
  }
  full.style.display = 'block';
  if (btn) { btn.disabled = false; btn.textContent = '원문 접기'; }
}
document.addEventListener('keydown', function (ev) {
  if (ev.key !== 'Escape') return;
  var page = document.getElementById('page-merlens');
  if (!page || !page.classList.contains('active')) return;
  var meta = document.getElementById('merlensSourceMeta');
  if (meta && meta.innerHTML.trim()) _merCloseSource();
});

/* ============================================================
   P3 2부 — ②전이경로맵 ④매트릭스 ⑤뷰타임라인+⑤-b팩터스코어카드 ⑥이벤트+⑥-b재고일수
   ============================================================ */

// ── 공용: 다중 인용 출처 패널 (블록①③③b 의 _merOpenSource 는 단일-인용 전용이라 건드리지 않고
//    별도 함수로 둔다. 같은 DOM(#merlensSource*)을 쓰므로 열린 패널은 서로 대체된다.) ──
function _merOpenQuotes(label, quotes, triggerEl) {
  _merLastFocusEl = triggerEl || document.activeElement;
  var q = document.getElementById('merlensSourceQuote');
  var meta = document.getElementById('merlensSourceMeta');
  var full = document.getElementById('merlensSourceFull');
  if (full) { full.style.display = 'none'; full.textContent = ''; }
  var list = (quotes || []).slice().sort(function (a, b) { return (a.date || '').localeCompare(b.date || ''); });
  if (!list.length) {
    if (q) q.textContent = label + ' — 아직 연결된 인용이 없습니다.';
    if (meta) meta.innerHTML = '';
  } else {
    if (q) q.textContent = label;
    if (meta) meta.innerHTML = '<div style="font-weight:700;color:var(--c-txt);">' + _merEsc(label) + '</div>' +
      list.map(function (item) {
        var url = 'https://blog.naver.com/ranto28/' + encodeURIComponent(String(item.logNo));
        return '<div style="border-top:1px dashed var(--c-border);padding-top:6px;">' +
          '<div style="color:var(--c-txt-dim);">' + _merEsc(item.date || '') + (item.ctx ? ' · ' + _merEsc(item.ctx) : '') + '</div>' +
          '<div style="color:var(--c-txt);">' + _merEsc(item.q || '') + '</div>' +
          (item.logNo != null ? '<div><a href="' + url + '" target="_blank" rel="noopener">원문 ↗</a></div>' : '') +
          '</div>';
      }).join('');
  }
  var panel = document.getElementById('merlensSource');
  if (panel) { panel.setAttribute('tabindex', '-1'); try { panel.focus({ preventScroll: true }); } catch (_) {} }
}

function _merNodeLabelMap(d) {
  var m = {};
  (d.graph && d.graph.nodes || []).forEach(function (n) { m[n.id] = n.label; });
  return m;
}

// 시계(단기/중기/장기) 필터 칩 — 그래프·매트릭스가 공유하는 빌더.
function _merBuildHorizonChips(containerId, setterFnName) {
  var box = document.getElementById(containerId);
  if (!box || box.dataset.built) return;
  var opts = [['all', '전체'], ['단기', '단기'], ['중기', '중기'], ['장기', '장기']];
  box.innerHTML = opts.map(function (o) {
    return '<button type="button" class="seed-chip__root seed-chip__root--variant_outlineWeak seed-chip__root--size_small seed-chip__root--size_small-layout_withText" ' +
      'data-mer-hz="' + o[0] + '" aria-pressed="' + (o[0] === 'all' ? 'true' : 'false') + '" onclick="' + setterFnName + '(\'' + o[0] + '\',this)">' +
      '<span class="seed-chip__label seed-chip__label--size_small seed-chip__label--variant_outlineWeak">' + o[1] + '</span></button>';
  }).join('');
  box.dataset.built = '1';
}
function _merChipPress(containerId, btn) {
  var box = document.getElementById(containerId);
  if (box) box.querySelectorAll('[data-mer-hz]').forEach(function (b) { b.setAttribute('aria-pressed', b === btn ? 'true' : 'false'); });
}

/* ── ② 전이 경로 맵 ─────────────────────────────────────────────── */
var GRAPH_LAYERS = ['cause', 'market', 'channel', 'asset'];
var GRAPH_NODE_W = 196, GRAPH_NODE_H = 44, GRAPH_ROW_GAP = 10, GRAPH_COL_GAP = 230, GRAPH_MARGIN = 24;
var GRAPH_BADGE_W = 46; // 뷰 배지가 노드 사각형 안쪽 우측에 차지하는 예약 폭
var _merGraphNodesById = {};
var _merGraphEdges = [];
var _merGraphChainsById = {};
var _merGraphHorizon = 'all';
var _merGraphPresetId = '';

function _merWrapLabel(label) {
  label = label || '';
  if (label.length <= 7) return [label];
  var mid = Math.ceil(label.length / 2);
  var sp = label.lastIndexOf(' ', mid);
  if (sp <= 0) sp = label.indexOf(' ', mid);
  if (sp > 0) return [label.slice(0, sp), label.slice(sp + 1)];
  return [label.slice(0, mid), label.slice(mid)];
}

// barycenter 1회 — 왼쪽에서 오른쪽으로, 이미 배치된(왼쪽) 열들의 y-순서 평균으로 각 열을 한 번만 정렬.
function _merGraphLayout(nodes, edges) {
  var byLayer = {};
  GRAPH_LAYERS.forEach(function (l) { byLayer[l] = []; });
  nodes.forEach(function (n) { (byLayer[n.layer] || (byLayer[n.layer] = [])).push(n); });
  var yIndex = {}, placedCol = {};
  GRAPH_LAYERS.forEach(function (layerName, colIdx) {
    var colNodes = byLayer[layerName] || [];
    if (colIdx === 0) {
      colNodes.forEach(function (n, i) { yIndex[n.id] = i; placedCol[n.id] = colIdx; });
      return;
    }
    // 각 노드의 y = 그 노드로 "들어오는" 엣지의 출발 노드들(이미 배치된 왼쪽 열) 평균 y.
    var scored = colNodes.map(function (n, origIdx) {
      var sum = 0, cnt = 0;
      edges.forEach(function (e) {
        if (e.to !== n.id) return;
        if (placedCol[e.from] != null && placedCol[e.from] < colIdx && yIndex[e.from] != null) { sum += yIndex[e.from]; cnt++; }
      });
      return { n: n, score: cnt ? sum / cnt : (1000 + origIdx) };
    });
    scored.sort(function (a, b) { return a.score - b.score; });
    scored.forEach(function (s, i) { yIndex[s.n.id] = i; placedCol[s.n.id] = colIdx; });
  });
  var maxCount = 0;
  GRAPH_LAYERS.forEach(function (l) { maxCount = Math.max(maxCount, (byLayer[l] || []).length); });
  var layoutNodes = {};
  GRAPH_LAYERS.forEach(function (layerName, colIdx) {
    var x = GRAPH_MARGIN + colIdx * GRAPH_COL_GAP;
    (byLayer[layerName] || []).forEach(function (n) {
      var i = yIndex[n.id] || 0;
      var y = GRAPH_MARGIN + i * (GRAPH_NODE_H + GRAPH_ROW_GAP);
      layoutNodes[n.id] = { id: n.id, label: n.label, layer: n.layer, state: n.state, view: n.view,
        col: colIdx, x: x, y: y, w: GRAPH_NODE_W, h: GRAPH_NODE_H, cx: x + GRAPH_NODE_W / 2, cy: y + GRAPH_NODE_H / 2 };
    });
  });
  var width = GRAPH_MARGIN * 2 + (GRAPH_LAYERS.length - 1) * GRAPH_COL_GAP + GRAPH_NODE_W;
  var height = GRAPH_MARGIN * 2 + maxCount * (GRAPH_NODE_H + GRAPH_ROW_GAP) - GRAPH_ROW_GAP;
  return { nodes: layoutNodes, width: width, height: height };
}
// 출발=노드 오른쪽 변, 도착=노드 왼쪽 변 고정. dx 는 두 변 사이 거리의 45% — 정확히 50% 를 쓰면
// 제어점 c1x·c2x 가 같은 x(중점)에 겹쳐 곡선 중간이 수직으로 꺾인다(여러 엣지가 같은 두 열을
// 잇는 경우 그 수직 구간에서 전부 겹쳐 세로 뭉치로 보였다 — 45%로 어긋나게 해 해소).
function _merGraphEdgePath(sx, sy, tx, ty) {
  var raw = (tx - sx) * 0.45;
  var dx = Math.abs(raw) < 24 ? (raw < 0 ? -24 : 24) : raw;
  var c1x = sx + dx, c2x = tx - dx;
  return 'M ' + sx.toFixed(1) + ' ' + sy.toFixed(1) + ' C ' + c1x.toFixed(1) + ' ' + sy.toFixed(1) + ' ' +
    c2x.toFixed(1) + ' ' + ty.toFixed(1) + ' ' + tx.toFixed(1) + ' ' + ty.toFixed(1);
}
// 같은 노드에서 여러 선이 나가거나(출발) 들어오면(도착) 노드 높이 안에서 y 를 나눠 겹치지 않게.
function _merGraphAnchorY(node, idxInGroup, groupLen) {
  if (groupLen <= 1) return node.cy;
  var pad = Math.min(node.h / 2 - 3, 14);
  var t = idxInGroup / (groupLen - 1);
  return (node.y + pad) + t * (node.h - 2 * pad);
}
var GRAPH_STATE_COLOR = { below: 'var(--color-success)', near: 'var(--color-warning)', crossed: 'var(--color-error)', unknown: 'var(--c-border)' };
function _merGraphSvgMarkup(layout, edges, nodesById) {
  var maxN = 2, minN = 2;
  edges.forEach(function (e) { if (e.n > maxN) maxN = e.n; });
  var outMap = {}, inMap = {};
  edges.forEach(function (e, idx) {
    if (!layout.nodes[e.from] || !layout.nodes[e.to]) return;
    (outMap[e.from] = outMap[e.from] || []).push(idx);
    (inMap[e.to] = inMap[e.to] || []).push(idx);
  });
  var edgesSvg = edges.map(function (e, idx) {
    var a = layout.nodes[e.from], b = layout.nodes[e.to];
    if (!a || !b) return '';
    var outArr = outMap[e.from] || [idx], inArr = inMap[e.to] || [idx];
    var sy = _merGraphAnchorY(a, outArr.indexOf(idx), outArr.length);
    var ty = _merGraphAnchorY(b, inArr.indexOf(idx), inArr.length);
    var sx = a.x + a.w, tx = b.x;
    var sw = (1 + Math.min(1, (e.n - minN) / Math.max(1, maxN - minN)) * 2).toFixed(2);
    var color = e.dir === '+' ? 'var(--c-up)' : e.dir === '-' ? 'var(--c-down)' : 'var(--c-txt-dim)';
    var d = _merGraphEdgePath(sx, sy, tx, ty);
    var lbl = (nodesById[e.from] || {}).label || e.from, lbl2 = (nodesById[e.to] || {}).label || e.to;
    return '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="' + sw + '" class="mer-graph-edge" ' +
      'data-mer-idx="' + idx + '" data-mer-horizon="' + _merEsc(e.horizon || '') + '" ' +
      'role="button" tabindex="0" aria-label="' + _merEsc(lbl + ' → ' + lbl2 + ' 근거 보기') + '" style="cursor:pointer;" ' +
      'onclick="_merGraphOpenEdge(' + idx + ',this)" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();_merGraphOpenEdge(' + idx + ',this);}"/>';
  }).join('');
  // 엣지보다 나중에 그려야 노드·배지가 선 위에 온다(겹침 방지).
  var nodesSvg = Object.keys(layout.nodes).map(function (id) {
    var n = layout.nodes[id];
    var toneColor = GRAPH_STATE_COLOR[n.state] || GRAPH_STATE_COLOR.unknown;
    var dash = n.state === 'unknown' ? ' stroke-dasharray="4,3"' : '';
    var labelCx = n.x + (n.w - GRAPH_BADGE_W) / 2;
    var lines = _merWrapLabel(n.label);
    var textY0 = n.cy - (lines.length - 1) * 7;
    var textSvg = lines.map(function (ln, i) {
      return '<text x="' + labelCx + '" y="' + (textY0 + i * 14).toFixed(1) + '" text-anchor="middle" font-size="var(--font-size-base)" fill="var(--c-txt)">' + _merEsc(ln) + '</text>';
    }).join('');
    var badge = '';
    if (n.view != null) {
      var vc = n.view > 0 ? 'var(--c-up)' : n.view < 0 ? 'var(--c-down)' : 'var(--c-txt-dim)';
      // 노드 사각형 안쪽 우측에 배지 — viewBox 밖으로 잘리지 않고, 카드 배경이 선을 가려준다.
      badge = '<text x="' + (n.x + n.w - 8) + '" y="' + (n.cy + 4).toFixed(1) + '" text-anchor="end" font-size="var(--font-size-xs)" font-weight="700" fill="' + vc + '">' +
        _merEsc(MER_LABELS.view[String(n.view)] || '') + '</text>';
    }
    return '<g class="mer-graph-node" data-mer-node="' + id + '" role="button" tabindex="0" aria-label="' + _merEsc(n.label + ' 근거 보기') + '" style="cursor:pointer;" ' +
      'onclick="_merGraphOpenNode(\'' + id + '\',this)" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();_merGraphOpenNode(\'' + id + '\',this);}">' +
      '<rect class="mer-node-box" x="' + n.x + '" y="' + n.y + '" width="' + n.w + '" height="' + n.h + '" rx="8" fill="var(--c-card)" stroke="' + toneColor + '" stroke-width="1.6"' + dash + '/>' +
      textSvg + badge + '</g>';
  }).join('');
  return '<svg viewBox="0 0 ' + layout.width + ' ' + layout.height + '" class="mer-graph-svg" role="img" aria-label="메르 리스크 렌즈 전이 경로 맵">' + edgesSvg + nodesSvg + '</svg>';
}
function _merChainStepHtml(label, hot) {
  return '<div class="mer-chain-step' + (hot ? ' mer-chain-step--hot' : '') + '">' + _merEsc(label) + '</div>';
}
function _merGraphMobileHtml(chains) {
  return chains.map(function (c) {
    var stepsHtml = c.steps.map(function (s, i) {
      var hot = c.hotStep === s.id;
      return (i > 0 ? '<div class="mer-chain-arrow">↓</div>' : '') + _merChainStepHtml(s.label, hot);
    }).join('');
    return '<div class="mer-chain-group"><div class="mer-chain-title">' + _merEsc(c.id + ' ' + c.label) +
      ' <span class="econ-stat__unit">n=' + c.n + '</span></div>' + stepsHtml + '</div>';
  }).join('');
}
function _merRenderGraph(d) {
  var svgWrap = document.getElementById('merGraphSvgWrap');
  var mobileWrap = document.getElementById('merGraphMobile');
  var presetSel = document.getElementById('merGraphPreset');
  if (!svgWrap || !mobileWrap) return;
  var nodes = (d.graph && d.graph.nodes) || [];
  var edges = (d.graph && d.graph.edges) || [];
  _merGraphNodesById = {}; nodes.forEach(function (n) { _merGraphNodesById[n.id] = n; });
  _merGraphEdges = edges;
  _merGraphChainsById = {}; (d.chains || []).forEach(function (c) { _merGraphChainsById[c.id] = c; });
  var layout = _merGraphLayout(nodes, edges);
  svgWrap.innerHTML = _merGraphSvgMarkup(layout, edges, _merGraphNodesById);
  mobileWrap.innerHTML = _merGraphMobileHtml(d.chains || []);
  if (presetSel && !presetSel.dataset.built) {
    presetSel.innerHTML = '<option value="">경로 프리셋 — 전체</option>' + (d.chains || []).map(function (c) {
      return '<option value="' + c.id + '">' + _merEsc(c.id + ' ' + c.label) + ' (n=' + c.n + ')</option>';
    }).join('');
    presetSel.dataset.built = '1';
  }
  _merBuildHorizonChips('merGraphHorizonChips', '_merGraphSetHorizon');
  _merGraphApplyFilters();
}
function _merGraphSetHorizon(hz, btn) {
  _merGraphHorizon = hz;
  _merChipPress('merGraphHorizonChips', btn);
  _merGraphApplyFilters();
}
function _merGraphSetPreset(id) {
  _merGraphPresetId = id || '';
  _merGraphApplyFilters();
}
function _merGraphApplyFilters() {
  var svg = document.querySelector('#merGraphSvgWrap svg');
  if (!svg) return;
  var chain = _merGraphPresetId ? _merGraphChainsById[_merGraphPresetId] : null;
  var chainNodeIds = {}, chainEdgeKeys = {};
  if (chain) {
    chain.steps.forEach(function (s) { chainNodeIds[s.id] = true; });
    for (var i = 0; i < chain.steps.length - 1; i++) {
      chainEdgeKeys[chain.steps[i].id + '>' + chain.steps[i + 1].id] = true;
      chainEdgeKeys[chain.steps[i + 1].id + '>' + chain.steps[i].id] = true;
    }
  }
  svg.querySelectorAll('.mer-graph-node').forEach(function (g) {
    var id = g.getAttribute('data-mer-node');
    g.classList.toggle('mer-graph-dim', !!(chain && !chainNodeIds[id]));
    g.classList.toggle('mer-graph-hot', !!(chain && chain.hotStep === id));
  });
  svg.querySelectorAll('.mer-graph-edge').forEach(function (g) {
    var idx = +g.getAttribute('data-mer-idx');
    var e = _merGraphEdges[idx];
    if (!e) return;
    var dimChain = chain && !chainEdgeKeys[e.from + '>' + e.to];
    var dimHz = _merGraphHorizon !== 'all' && e.horizon !== _merGraphHorizon;
    g.classList.toggle('mer-graph-dim', !!(dimChain || dimHz));
  });
}
function _merGraphOpenNode(id, triggerEl) {
  if (!_merSignalsData) return;
  var label = (_merGraphNodesById[id] || {}).label || id;
  var impacts = (_merSignalsData.impacts || []).filter(function (im) { return im.from === id || im.to === id; });
  var quotes = [];
  impacts.forEach(function (im) {
    var fromLbl = (_merGraphNodesById[im.from] || {}).label || im.from;
    var toLbl = (_merGraphNodesById[im.to] || {}).label || im.to;
    (im.quotes || []).forEach(function (q) { quotes.push({ logNo: q.logNo, date: q.date, q: q.q, ctx: fromLbl + ' → ' + toLbl }); });
  });
  _merOpenQuotes(label, quotes, triggerEl);
}
function _merGraphOpenEdge(idx, triggerEl) {
  if (!_merSignalsData) return;
  var im = (_merSignalsData.impacts || [])[idx];
  if (!im) return;
  var fromLbl = (_merGraphNodesById[im.from] || {}).label || im.from;
  var toLbl = (_merGraphNodesById[im.to] || {}).label || im.to;
  var quotes = (im.quotes || []).map(function (q) { return { logNo: q.logNo, date: q.date, q: q.q }; });
  _merOpenQuotes(fromLbl + ' → ' + toLbl, quotes, triggerEl);
  var svg = document.querySelector('#merGraphSvgWrap svg');
  if (svg) {
    svg.querySelectorAll('.mer-graph-edge').forEach(function (g) { g.classList.remove('mer-graph-edge--selected'); });
    if (triggerEl && triggerEl.classList) triggerEl.classList.add('mer-graph-edge--selected');
  }
}

/* ── ④ 민감도 매트릭스 ──────────────────────────────────────────── */
var _merMatrixHorizon = 'all';
var _merMatrixCellHorizons = {};
function _merMatrixCellHtml(cell) {
  if (!cell) return '<td class="mer-matrix-cell"></td>';
  var up = cell.dir === '+', down = cell.dir === '-';
  var color = up ? 'var(--c-up)' : down ? 'var(--c-down)' : 'var(--c-txt-dim)';
  var alpha = cell.strength >= 3 ? 55 : cell.strength === 2 ? 35 : 15;
  var arrow = up ? '▲' : down ? '▼' : '±';
  return '<td class="mer-matrix-cell"><button type="button" class="btn-plain btn-inline mer-matrix-btn" ' +
    'data-mer-row="' + _merEsc(cell.row) + '" data-mer-col="' + _merEsc(cell.col) + '" ' +
    'style="background:color-mix(in srgb, ' + color + ' ' + alpha + '%, transparent);color:' + color + ';" ' +
    'title="' + _merEsc(cell.row + ' → ' + cell.col + ' · n=' + cell.n) + '" ' +
    'onclick="_merMatrixOpenCell(\'' + _merEsc(cell.row) + '\',\'' + _merEsc(cell.col) + '\',this)">' + arrow + ' ' + cell.n + '</button></td>';
}
function _merRenderMatrix(d) {
  var wrap = document.getElementById('merMatrixTableWrap');
  if (!wrap) return;
  var rows = d.matrix.rows, cols = d.matrix.cols;
  var cellMap = {};
  (d.matrix.cells || []).forEach(function (c) { cellMap[c.row + '|' + c.col] = c; });
  _merMatrixCellHorizons = {};
  (d.impacts || []).forEach(function (im) {
    var k = im.from + '|' + im.to;
    if (!cellMap[k]) return;
    (_merMatrixCellHorizons[k] = _merMatrixCellHorizons[k] || {})[im.horizon] = true;
  });
  var labels = _merNodeLabelMap(d);
  var rowSums = d.matrix.rowSums || {}, colSums = d.matrix.colSums || {};
  var maxSum = 1;
  Object.keys(rowSums).forEach(function (k) { if (rowSums[k] > maxSum) maxSum = rowSums[k]; });
  Object.keys(colSums).forEach(function (k) { if (colSums[k] > maxSum) maxSum = colSums[k]; });
  var theadCols = cols.map(function (c) { return '<th scope="col" title="' + _merEsc(labels[c] || c) + '">' + _merEsc(labels[c] || c) + '</th>'; }).join('');
  var bodyRows = rows.map(function (r) {
    var rowCells = cols.map(function (c) { return _merMatrixCellHtml(cellMap[r + '|' + c]); }).join('');
    var v = rowSums[r] || 0;
    return '<tr><th scope="row" title="' + _merEsc(labels[r] || r) + '">' + _merEsc(labels[r] || r) + '</th>' + rowCells +
      '<td class="mer-matrix-sum"><div class="mer-matrix-bar" style="width:' + Math.round(v / maxSum * 100) + '%"></div><span>' + v + '</span></td></tr>';
  }).join('');
  var colSumCells = cols.map(function (c) {
    var v = colSums[c] || 0;
    return '<td class="mer-matrix-sum"><div class="mer-matrix-bar" style="width:' + Math.round(v / maxSum * 100) + '%"></div><span>' + v + '</span></td>';
  }).join('');
  wrap.innerHTML = '<table class="econ-table mer-matrix-table"><caption class="econ-sr">시장 변수·원인·창구(행) × 자산(열) 민감도. 빈 칸은 언급 없음.</caption>' +
    '<thead><tr><th scope="col"></th>' + theadCols + '<th scope="col">파급력</th></tr></thead><tbody>' + bodyRows +
    '<tr class="mer-matrix-footrow"><th scope="row">노출도</th>' + colSumCells + '<td></td></tr></tbody></table>';
  _merBuildHorizonChips('merMatrixHorizonChips', '_merMatrixSetHorizon');
  _merMatrixApplyFilters();
}
function _merMatrixSetHorizon(hz, btn) {
  _merMatrixHorizon = hz;
  _merChipPress('merMatrixHorizonChips', btn);
  _merMatrixApplyFilters();
}
function _merMatrixApplyFilters() {
  var wrap = document.getElementById('merMatrixTableWrap');
  if (!wrap) return;
  wrap.querySelectorAll('.mer-matrix-btn').forEach(function (btn) {
    if (_merMatrixHorizon === 'all') { btn.classList.remove('mer-dim'); return; }
    var k = btn.getAttribute('data-mer-row') + '|' + btn.getAttribute('data-mer-col');
    var hzSet = _merMatrixCellHorizons[k];
    btn.classList.toggle('mer-dim', !(hzSet && hzSet[_merMatrixHorizon]));
  });
}
function _merMatrixOpenCell(row, col, triggerEl) {
  if (!_merSignalsData) return;
  var labels = _merNodeLabelMap(_merSignalsData);
  var impacts = (_merSignalsData.impacts || []).filter(function (im) { return im.from === row && im.to === col; });
  var quotes = [];
  impacts.forEach(function (im) { (im.quotes || []).forEach(function (q) { quotes.push({ logNo: q.logNo, date: q.date, q: q.q }); }); });
  _merOpenQuotes((labels[row] || row) + ' → ' + (labels[col] || col), quotes, triggerEl);
}

/* ── ⑤ 뷰 타임라인 + ⑤-b 팩터 스코어카드 ───────────────────────── */
function _merStanceMonths(d) {
  var maxDate = null;
  (d.stance.assets || []).forEach(function (a) { (a.series || []).forEach(function (s) { if (!maxDate || s.date > maxDate) maxDate = s.date; }); });
  var end = maxDate ? new Date(maxDate) : new Date();
  var months = [];
  for (var i = 11; i >= 0; i--) {
    var dt = new Date(end.getFullYear(), end.getMonth() - i, 1);
    months.push(dt.getFullYear() + '-' + String(dt.getMonth() + 1).padStart(2, '0'));
  }
  return months;
}
function _merMonthCell(asset, ym) {
  var last = null;
  (asset.series || []).forEach(function (s) { if ((s.date || '').indexOf(ym) === 0 && (!last || s.date >= last.date)) last = s; });
  var reversal = (asset.reversals || []).some(function (rd) { return (rd || '').indexOf(ym) === 0; });
  if (!last) return '<td class="mer-stance-cell mer-stance-cell--empty">–</td>';
  var v = last.view;
  var color = v > 0 ? 'var(--c-up)' : v < 0 ? 'var(--c-down)' : 'var(--c-txt-dim)';
  var bold = Math.abs(v) === 2;
  var label = MER_LABELS.view[String(v)] != null ? MER_LABELS.view[String(v)] : v;
  return '<td class="mer-stance-cell"><button type="button" class="btn-plain btn-inline" style="color:' + color + ';font-weight:' + (bold ? 700 : 500) + ';" ' +
    'title="' + _merEsc(ym + ' · ' + label + (last.why ? ' · ' + last.why : '')) + '" onclick="_merStanceOpenMonth(\'' + _merEsc(asset.asset) + '\',\'' + ym + '\',this)">' +
    (reversal ? '◆ ' : '') + _merEsc(String(label)) + '</button></td>';
}
function _merRenderStanceTimeline(d) {
  var wrap = document.getElementById('merStanceTableWrap');
  if (!wrap) return;
  var months = _merStanceMonths(d);
  var assets = (d.stance.assets || []).slice().sort(function (a, b) { return (b.n || 0) - (a.n || 0); }).slice(0, 12);
  var head = '<tr><th scope="col">자산</th>' + months.map(function (m) { return '<th scope="col">' + m.slice(5) + '</th>'; }).join('') +
    '<th scope="col">12개월 평균</th><th scope="col">최근</th></tr>';
  var body = assets.map(function (a) {
    var cells = months.map(function (m) { return _merMonthCell(a, m); }).join('');
    var avgColor = (a.avg12m || 0) > 0 ? 'var(--c-up)' : (a.avg12m || 0) < 0 ? 'var(--c-down)' : 'var(--c-txt-dim)';
    var lastColor = (a.last || 0) > 0 ? 'var(--c-up)' : (a.last || 0) < 0 ? 'var(--c-down)' : 'var(--c-txt-dim)';
    var lastLabel = MER_LABELS.view[String(a.last)] != null ? MER_LABELS.view[String(a.last)] : a.last;
    return '<tr><th scope="row">' + _merEsc(a.label || a.asset) + '</th>' + cells +
      '<td class="econ-table--num" style="color:' + avgColor + ';">' + (a.avg12m != null ? a.avg12m.toFixed(2) : '—') + '</td>' +
      '<td class="econ-table--num" style="color:' + lastColor + ';font-weight:700;">' + (a.last != null ? _merEsc(String(lastLabel)) : '—') + '</td></tr>';
  }).join('');
  wrap.innerHTML = '<table class="econ-table mer-stance-table"><caption class="econ-sr">자산별 최근 12개월 뷰 타임라인. ◆=반전 시점, n 상위 12개 자산만 표시.</caption>' +
    '<thead>' + head + '</thead><tbody>' + body + '</tbody></table>';
}
function _merStanceOpenMonth(assetId, ym, triggerEl) {
  if (!_merSignalsData) return;
  var a = (_merSignalsData.stance.assets || []).find(function (x) { return x.asset === assetId; });
  if (!a) return;
  var items = (a.series || []).filter(function (s) { return (s.date || '').indexOf(ym) === 0; });
  var quotes = items.map(function (s) {
    var label = MER_LABELS.view[String(s.view)] != null ? MER_LABELS.view[String(s.view)] : s.view;
    return { logNo: s.logNo, date: s.date, q: label + ' — ' + (s.why || '') };
  });
  _merOpenQuotes((a.label || assetId) + ' · ' + ym, quotes, triggerEl);
}

var _merFactorsByAsset = {}, _merFactorLabels = {};
var MER_FACTOR_STATUS_TONE = { active: 'positive', expired: 'neutral', neutral: 'warning' };
var MER_FACTOR_STATUS_LABEL = { active: '활성', expired: '종료', neutral: '중립' };
function _merRenderFactorCard(d) {
  var sel = document.getElementById('merFactorAssetSel');
  if (!sel) return;
  var byAsset = {};
  (d.factors || []).forEach(function (f) { (byAsset[f.asset] = byAsset[f.asset] || []).push(f); });
  var labels = _merNodeLabelMap(d);
  var assetIds = Object.keys(byAsset).sort(function (a, b) { return byAsset[b].length - byAsset[a].length; });
  _merFactorsByAsset = byAsset;
  _merFactorLabels = labels;
  if (!sel.dataset.built) {
    sel.innerHTML = assetIds.map(function (id) { return '<option value="' + _merEsc(id) + '">' + _merEsc(labels[id] || id) + ' (' + byAsset[id].length + ')</option>'; }).join('');
    sel.dataset.built = '1';
    sel.addEventListener('change', function () { _merRenderFactorCardBody(sel.value); });
  }
  _merRenderFactorCardBody(sel.value || assetIds[0]);
}
function _merFactorRowHtml(assetId, f, idx) {
  var tone = MER_FACTOR_STATUS_TONE[f.status] || 'neutral';
  return '<tr onclick="_merFactorOpen(\'' + _merEsc(assetId) + '\',' + idx + ',this)" style="cursor:pointer;">' +
    '<td><button type="button" class="btn-plain btn-inline">' + _merEsc(f.factor) + '</button></td>' +
    '<td><span class="seed-badge__root seed-badge__root--size_medium seed-badge__root--tone_' + tone + '-variant_weak">' +
    (MER_FACTOR_STATUS_LABEL[f.status] || f.status) + '</span></td></tr>';
}
function _merRenderFactorCardBody(assetId) {
  var box = document.getElementById('merFactorCardBody');
  if (!box) return;
  var list = _merFactorsByAsset[assetId] || [];
  var bulls = [], bears = [];
  list.forEach(function (f, idx) { (f.side === 'bull' ? bulls : bears).push([f, idx]); });
  function section(title, arr) {
    return '<div class="mer-panel-title" style="margin-top:10px;">' + title + '</div><table class="econ-table"><tbody>' +
      (arr.map(function (pair) { return _merFactorRowHtml(assetId, pair[0], pair[1]); }).join('') ||
        '<tr><td colspan="2" style="color:var(--c-txt-dim);">없음</td></tr>') + '</tbody></table>';
  }
  box.innerHTML = section('강세 요인', bulls) + section('약세 요인', bears);
}
function _merFactorOpen(assetId, idx, triggerEl) {
  var f = (_merFactorsByAsset[assetId] || [])[idx];
  if (!f) return;
  _merOpenQuotes((_merFactorLabels[assetId] || assetId) + ' · ' + (f.side === 'bull' ? '강세' : '약세'),
    [{ logNo: f.logNo, date: f.date, q: f.factor }], triggerEl);
}

/* ── ⑥ 이벤트 캘린더 + ⑥-b 재고 일수 ──────────────────────────── */
var _merEventsSorted = [];
function _merEventsCalHtml(events) {
  var now = Date.now();
  var sorted = events.slice().sort(function (a, b) { return (a.date || '').localeCompare(b.date || ''); });
  _merEventsSorted = sorted;
  var rows = sorted.map(function (ev, idx) {
    var days = null;
    try { days = Math.round((new Date(ev.date).getTime() - now) / 86400000); } catch (_) {}
    if (ev.precision === 'day' && days != null && days < -30) return '';
    var dim = (ev.precision === 'day' && days != null && days < 0) ? ' mer-dim' : '';
    var ddayTxt = ev.precision === 'day' && days != null
      ? (days === 0 ? 'D-Day' : (days > 0 ? 'D-' + days : 'D+' + (-days)))
      : (ev.date ? ev.date.slice(0, 4) + '년' : '—');
    var revChip = ev.revocable ? '<span class="seed-badge__root seed-badge__root--size_medium seed-badge__root--tone_neutral-variant_weak">철회 가능</span>' : '';
    return '<tr class="' + dim.trim() + '" onclick="_merEventOpen(' + idx + ',this)" style="cursor:pointer;">' +
      '<td><button type="button" class="btn-plain btn-inline">' + _merEsc(ev.label) + '</button></td>' +
      '<td class="econ-table--num">' + _merEsc(ddayTxt) + '</td>' +
      '<td>' + revChip + '</td></tr>';
  }).join('');
  return '<div class="econ-table__scroll"><table class="econ-table"><caption class="econ-sr">이벤트 캘린더, 날짜 오름차순.</caption>' +
    '<thead><tr><th scope="col">이벤트</th><th scope="col" class="econ-table--num">D-day</th><th scope="col"></th></tr></thead><tbody>' +
    (rows || '<tr><td colspan="3" style="color:var(--c-txt-dim);">표시할 이벤트가 없습니다.</td></tr>') + '</tbody></table></div>';
}
function _merEventOpen(idx, triggerEl) {
  var ev = _merEventsSorted[idx];
  if (!ev) return;
  _merOpenQuotes(ev.label, [{ logNo: ev.logNo, date: ev.date, q: ev.label }], triggerEl);
}

var _merCountersData = [];
var _merCounterAlt = {};
function _merCountersHtml(counters) {
  _merCountersData = counters;
  var now = Date.now();
  var rows = counters.map(function (c, idx) {
    var useAlt = !!_merCounterAlt[idx];
    var days = (useAlt && c.daysAlt != null) ? c.daysAlt : c.days;
    var pct = Math.min(100, Math.max(0, days || 0));
    var old6m = false;
    try { old6m = (now - new Date(c.asOfPost).getTime()) / 86400000 > 182; } catch (_) {}
    var toggleBtn = c.daysAlt != null
      ? '<button type="button" class="seed-chip__root seed-chip__root--variant_outlineWeak seed-chip__root--size_small seed-chip__root--size_small-layout_withText" ' +
        'aria-pressed="' + useAlt + '" onclick="event.stopPropagation();_merCounterToggle(' + idx + ')">' +
        '<span class="seed-chip__label seed-chip__label--size_small seed-chip__label--variant_outlineWeak">가정 전환(' + c.days + '↔' + c.daysAlt + ')</span></button>'
      : '';
    return '<div class="mer-counter-row' + (old6m ? ' mer-dim' : '') + '" onclick="_merCounterOpen(' + idx + ',this)" style="cursor:pointer;">' +
      '<div class="mer-counter-head"><button type="button" class="btn-plain btn-inline">' + _merEsc(c.label) + '</button>' +
      '<span class="econ-stat__unit">글 시점 값 · ' + _merEsc(c.asOfPost || '') + '</span>' + toggleBtn + '</div>' +
      '<div class="mer-counter-bar-wrap"><div class="mer-counter-bar" style="width:' + pct + '%"></div></div>' +
      '<div class="mer-counter-days">' + days + '일<span class="econ-stat__unit"> · ' + _merEsc(c.assumption || '') + '</span></div></div>';
  }).join('');
  return rows || '<p class="mer-stub">표시할 재고 데이터가 없습니다.</p>';
}
function _merCounterToggle(idx) {
  _merCounterAlt[idx] = !_merCounterAlt[idx];
  var box = document.getElementById('merCountersBox');
  if (box) box.innerHTML = _merCountersHtml(_merCountersData);
}
function _merCounterOpen(idx, triggerEl) {
  var c = _merCountersData[idx];
  if (!c) return;
  _merOpenQuotes(c.label, [{ logNo: c.logNo, date: c.asOfPost, q: c.assumption }], triggerEl);
}
function _merRenderEvents(d) {
  var calBox = document.getElementById('merEventsCal');
  var cntBox = document.getElementById('merCountersBox');
  if (calBox) calBox.innerHTML = _merEventsCalHtml(d.events || []);
  if (cntBox) cntBox.innerHTML = _merCountersHtml(d.counters || []);
}
