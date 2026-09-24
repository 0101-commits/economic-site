/* ═══ [3차-T6] 설정 페이지 로직 · 통합 백업 · 가이드 · 오류 처리 ═══════════════
   의존: econSettings(T1), 설정 페이지 마크업(T3), 공통 CSS(T4), showPage 훅(T5) */
(function () {
'use strict';

/* ── 6.1 설정 페이지 초기화 ─────────────────────────────────────────────── */
window.initSettingsPage = function () {
  // 설정 페이지를 포트폴리오보다 먼저 열어도 알림 요약이 나오도록 상태를 선로드
  try { if (typeof pfState !== 'undefined' && !pfState && typeof pfLoad === 'function') pfState = pfLoad(); } catch (_) {}
  var s = econSettings.get();
  var el;
  if ((el = document.getElementById('setNotifEnabled'))) el.checked = !!s.notif.globalEnabled;
  if ((el = document.getElementById('setNotifLimit')))   el.value   = s.notif.defaultLimit || 'daily';
  if ((el = document.getElementById('setSyncPeriods')))  el.checked = !!s.chart.syncPeriods;
  document.querySelectorAll('#setPresetGroup .tab-btn').forEach(function (b) {
    var on = (b.dataset.preset || '') === (s.chart.defaultPreset || '');
    b.style.background = on ? getThemeColors().accent : 'transparent';
    b.style.color = on ? 'var(--c-on-accent)' : 'var(--c-txt-dim)';
  });
  var st = document.querySelector('input[name="setPfStyle"][value="' + (s.chart.pfStyle || 'candle') + '"]');
  if (st) st.checked = true;
  var cc = window.econColorConv || 'kr';
  // segmented-control 상태 동기 — recipe 는 [data-checked] 와 --segment-index 를 읽는다.
  // (:has() 는 구형 웹뷰 지원 대상이 아니라 상태를 JS 가 세운다)
  window.econSyncSegmented = function (rootId) {
    var root = document.getElementById(rootId);
    if (!root) return;
    var items = root.querySelectorAll('.seed-segmented-control__item');
    items.forEach(function (it, i) {
      var input = it.querySelector('input[type="radio"]');
      if (input && input.checked) { it.setAttribute('data-checked', ''); root.style.setProperty('--segment-index', i); }
      else it.removeAttribute('data-checked');
    });
  };
  var ccEl = document.querySelector('input[name="setColorConv"][value="' + cc + '"]');
  if (ccEl) ccEl.checked = true;
  try { econSyncSegmented('setColorConvGroup'); } catch (_) {}
  try { econSyncAllSwitches(document.getElementById('page-settings')); } catch (_) {}
  // 스킨 라디오는 폐기됐다(결정 D2) — 남은 저장값만 청소한다
  try { if (localStorage.getItem('econ_skin')) localStorage.removeItem('econ_skin'); } catch (_) {}
  var ind = { ma: true, rsi: false, macd: false };
  try { ind = JSON.parse(localStorage.getItem('pfIndicators')) || ind; } catch (_) {}
  ['ma', 'rsi', 'macd'].forEach(function (k) {
    var c = document.getElementById('setInd_' + k);
    if (c) c.checked = !!ind[k];
  });
  try { if (typeof pfRenderAlertSummary === 'function' && pfState) pfRenderAlertSummary(); } catch (_) {}
  try { if (typeof pfUpdateSyncKeyBtn === 'function') pfUpdateSyncKeyBtn(); } catch (_) {}
  try { if (typeof loadAlertHistory === 'function') loadAlertHistory(); } catch (_) {}
  _renderBackupCount();
};

// 📜 최근 발동 이력 — 서버(check_alerts.py)가 매 런 커밋하는 alerts_state.json 을 읽어
// 실제 '발송된' 알림(ts 존재)을 시간 역순으로 표시. 알림 이름은 로컬 pfState.alerts 와 id 조인.
// 서버 변경 없이 프론트 fetch 하나로 구현 — 카카오 무음 환경에서 알림 동작 여부를 확인하는 유일한 창.
async function loadAlertHistory(manual) {
  const el = document.getElementById('alertHistoryList');
  if(!el) return;
  if(manual) el.textContent = '불러오는 중…';
  try {
    const r = await fetch('./alerts_state.json?_=' + Date.now(), { cache: 'no-store' });
    if(!r.ok) { el.textContent = '이력 파일 없음 — 아직 서버 평가가 실행되지 않았습니다.'; return; }
    const st = await r.json();
    const byId = {};
    try { ((pfState && pfState.alerts) || []).forEach(a => { if(a && a.id) byId[a.id] = a; }); } catch(_) {}
    const TYPE_TXT = { price_above:'목표가 이상', price_below:'지정가 이하', pct_change:'등락률 도달',
                       high52:'52주 신고가', low52:'52주 신저가', vol_surge:'거래량 폭증',
                       golden_cross:'골든크로스', dead_cross:'데드크로스' };
    const rows = Object.entries(st)
      .filter(([, v]) => v && v.ts)
      .sort((a, b) => (b[1].ts || 0) - (a[1].ts || 0))
      .slice(0, 10)
      .map(([id, v]) => {
        const a = byId[id];
        const name = a ? (a.name || a.symbol || id) : '(이 기기에 없는 알림)';
        const cond = a ? (TYPE_TXT[a.type] || a.type || '') : '';
        const when = new Date((v.ts || 0) * 1000).toLocaleString('ko-KR',
          { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false });
        return '<div>🔔 <b>' + escapeHtml(String(name)) + '</b> ' + escapeHtml(cond) +
               ' — <span style="color:var(--c-txt-muted);">' + when + ' 카카오 발송</span></div>';
      });
    el.innerHTML = rows.length ? rows.join('')
      : '최근 발송된 알림이 없습니다. (조건 미충족 상태 — 평가는 장중 매분 실행 중)';
  } catch(_) { el.textContent = '이력 조회 실패 — 네트워크를 확인하세요.'; }
}

function _settingsMarkDirty() {
  var st = document.getElementById('settingsSyncStatus');
  if (st) { st.textContent = '변경됨 — ☁ 서버에 저장 필요'; st.style.color = '#f0c75e'; }
}
window.settingsToggleNotif = function (on) {
  econSettings.patch({ notif: { globalEnabled: !!on } });
  _settingsMarkDirty();
};
window.settingsSetDefaultLimit = function (v) {
  econSettings.patch({ notif: { defaultLimit: v === 'cool60' ? 'cool60' : 'daily' } });
  _settingsMarkDirty();
};
window.settingsToggleSync = function (on) { econSettings.patch({ chart: { syncPeriods: !!on } }); };
window.settingsSetPfStyle = function (v) { econSettings.patch({ chart: { pfStyle: v === 'line' ? 'line' : 'candle' } }); };
window.settingsSetColorConv = function (v) {
  v = (v === 'global') ? 'global' : 'kr';
  try { econSyncSegmented('setColorConvGroup'); } catch (_) {}
  if (v === (window.econColorConv || 'kr')) return;
  try { localStorage.setItem('econ_color_conv', v); } catch (_) {}
  try { if (typeof showToast === 'function') showToast('색상 방향 적용 중… 새로고침', 'ok'); } catch (_) {}
  setTimeout(function () { location.reload(); }, 400);
};
// 스킨은 폐기됐다(결정 D2). 함수는 옛 링크·북마크·외부 호출을 위해 남기되
// 아무 것도 켜지 않고 한 번만 알린다 — 조용히 무시하면 "왜 안 바뀌지"가 된다.
window.settingsSetSkin = function (v) {
  try { localStorage.removeItem('econ_skin'); } catch (_) {}
  delete document.documentElement.dataset.skin;
  if (!window._econSkinNoticed) {
    window._econSkinNoticed = true;
    try { if (typeof showToast === 'function') showToast('화면 스킨은 없어졌어요. 다크·라이트 테마만 씁니다', 'ok'); } catch (_) {}
  }
};
window.settingsToggleInd = function (k, on) {
  // 보조지표 SSOT 는 기존 'pfIndicators' — 설정 페이지는 같은 키를 읽고 쓴다
  var ind = { ma: true, rsi: false, macd: false };
  try { ind = JSON.parse(localStorage.getItem('pfIndicators')) || ind; } catch (_) {}
  ind[k] = !!on;
  try { localStorage.setItem('pfIndicators', JSON.stringify(ind)); } catch (_) {}
  try { if (typeof pfInd !== 'undefined' && pfInd) pfInd[k] = !!on; } catch (_) {}  // 열린 모달 즉시 반영용 전역
};
window.settingsSetPreset = function (p, btn) {
  econSettings.patch({ chart: { defaultPreset: p || '' } });
  document.querySelectorAll('#setPresetGroup .tab-btn').forEach(function (b) {
    var on = b === btn;
    b.style.background = on ? getThemeColors().accent : 'transparent';
    b.style.color = on ? 'var(--c-on-accent)' : 'var(--c-txt-dim)';
  });
  // 페이지별 '1회 적용' 플래그 리셋 → 다음 진입 시 새 기본 기간이 다시 적용되게
  document.querySelectorAll('[data-default-applied]').forEach(function (el) { delete el.dataset.defaultApplied; });
  try { if (pfChart) pfChart._defaultApplied = false; } catch (_) {}
  if (typeof showToast === 'function') showToast(p ? '각 페이지를 다시 열면 기본 기간이 적용됩니다.' : '페이지별 기본 기간을 사용합니다.');
};

/* ── 6.2 페이지 훅 — 기본 기간 1회 적용 + 1회성 가이드 ──────────────────── */
var GUIDES_LS_KEY = 'econ_guides_v1';
function _guideSeen(key) { try { return !!(JSON.parse(localStorage.getItem(GUIDES_LS_KEY) || '{}'))[key]; } catch (_) { return false; } }
window.dismissGuide = function (key, el) {
  try {
    var g = JSON.parse(localStorage.getItem(GUIDES_LS_KEY) || '{}');
    g[key] = 1;
    localStorage.setItem(GUIDES_LS_KEY, JSON.stringify(g));
  } catch (_) {}
  var b = el && el.closest ? el.closest('.guide-banner') : null;
  if (b) b.remove();
};
function mountGuideBanner(anchorEl, key, html, position) {
  if (!anchorEl || _guideSeen(key) || document.getElementById('guide-' + key)) return;
  var div = document.createElement('div');
  div.className = 'guide-banner';
  div.id = 'guide-' + key;
  div.innerHTML = '<span>💡</span><span>' + html + '</span><button type="button" class="guide-x btn-plain btn-inline" onclick="dismissGuide(\'' + key + '\',this)" title="다시 보지 않기">✕</button>';
  anchorEl.insertAdjacentElement(position || 'beforebegin', div);
}
function _applyDefaultPresetsForActivePage() {
  var preset = econSettings.get('chart.defaultPreset');
  if (!preset || typeof applyChartPresetPeriod !== 'function') return;
  var page = document.querySelector('.page.active');
  if (!page) return;
  page.querySelectorAll('[class*="preset-btn-group-"]').forEach(function (group) {
    if (group.dataset.defaultApplied) return;
    var m = (group.className || '').match(/preset-btn-group-([a-z]+)/);
    if (!m) return;
    // 버튼에 data 속성이 없으므로 onclick 의 'PRESET' 코드 문자열로 매칭 (예: applyChartPresetPeriod('main','30D',this))
    var btn = Array.prototype.find.call(group.querySelectorAll('button'), function (b) {
      return ((b.getAttribute('onclick') || '').indexOf("'" + preset + "'") >= 0);
    });
    if (!btn) return;                  // 해당 차트에 같은 프리셋이 없으면 건너뜀
    group.dataset.defaultApplied = '1';
    window._presetSyncing = true;      // 기본값 적용이 '기간 동기화 전파'(T7)를 재귀 유발하지 않게
    try { applyChartPresetPeriod(m[1], preset, btn); } catch (_) {}
    window._presetSyncing = false;
  });
}
// 동적으로 그려지는 위젯 제목에도 heading 구실을 준다(IA v3 P1).
// 정적 마크업은 h3 로 올렸지만, JS 템플릿이 만드는 제목은 문자열이라 태그를 바꾸기
// 어렵다 — 같은 뜻을 role/aria-level 로 준다. KPI 숫자 카드의 라벨은 제외한다.
// 제목에서 '지표 이름'만 뽑는다 — 단위칩·신선도칩·백분위 배지·새로고침 버튼처럼
// 나중에 덧붙는 것들을 빼야 레지스트리와 이름이 맞는다(IA v3 P1~P3 공통).
window.econTitleText = function (el) {
  try {
    var out = '';
    el.childNodes.forEach(function (n) { if (n.nodeType === 3) out += n.nodeValue; });
    out = out.trim();
    if (out) return out;
    var clone = el.cloneNode(true);
    clone.querySelectorAll('button,a,select,input,.econ-stat__unit,.w-fresh-chip,.econ-src').forEach(function (x) { x.remove(); });
    return (clone.textContent || '').trim();
  } catch (_) { return (el.textContent || '').trim(); }
};
// data.json 은 app1 의 최상위 var 로만 있고 window 에 붙지 않는다 — 안전하게 집어온다.
window.econData = function () {
  try { return (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators) || null; }
  catch (_) { return null; }
};

window.econMarkHeadings = function (root) {
  try {
    var scope = root || document;
    scope.querySelectorAll('.widget-title').forEach(function (el) {
      if (/^H[1-6]$/.test(el.tagName)) return;
      if (el.getAttribute('role') === 'heading') return;
      if (el.classList.contains('econ-stat__label')) return;
      if (el.closest('.kpi-card')) return;
      el.setAttribute('role', 'heading');
      el.setAttribute('aria-level', '3');
    });
  } catch (_) {}
};

// 화면은 데이터가 늦게 도착한 뒤에도 제목을 새로 그린다 — 한 번의 훅으로는 놓친다.
// 본문에 붙는 노드를 지켜보다가 새 위젯 제목에만 heading 구실을 준다(디바운스 200ms).
(function observeHeadings() {
  try {
    var pending = null;
    var mo = new MutationObserver(function () {
      if (pending) return;
      pending = setTimeout(function () {
        pending = null;
        try { econMarkHeadings(document.getElementById('mainContent')); } catch (_) {}
        try { econMarkSources(document.getElementById('mainContent')); } catch (_) {}
        try { econMarkContext(document.getElementById('mainContent')); } catch (_) {}
        try { econMarkFavorites(document.getElementById('mainContent')); } catch (_) {}
        try { econMakeTablesSortable(document.getElementById('mainContent')); } catch (_) {}
        try { econMarkScrollables(document.getElementById('mainContent')); } catch (_) {}
        try { econFoldControls(document.getElementById('mainContent')); } catch (_) {}
      }, 200);
    });
    var start = function () {
      var root = document.getElementById('mainContent');
      if (!root) return;
      mo.observe(root, { childList: true, subtree: true });
      try { econMarkHeadings(root); econMarkSources(root); } catch (_) {}
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
  } catch (_) {}
})();

// 같은 지표가 여러 화면에 뜬다 — 어느 쪽이 원본인지 화면이 말하게 한다(IA v3 P2).
// 제목이 레지스트리의 라벨/옛 이름과 정확히 일치하고 지금 화면이 그 지표의 원본이
// 아니면 제목 옆에 '<원본 화면 이름> ›' 을 단다. 원본 화면에서는 아무 것도 안 붙는다.
window.econMarkSources = function (root) {
  try {
    if (!window.ECON_IND) return;
    var scope = root || document;
    var activePage = (document.querySelector('.page.active') || {}).id || '';
    activePage = activePage.replace(/^page-/, '');
    scope.querySelectorAll('.widget-title').forEach(function (el) {
      if (el.querySelector('.econ-src')) return;
      // 제목의 순수 텍스트만 — 안에 든 단위칩·버튼 글자는 뺀다
      var name = econTitleText(el);
      if (!name || name.length > 24) return;
      var row = window.ECON_IND.find(name);
      if (!row || !row.canonical) return;
      // 이미 클릭 가능한 카드(홈 KPI 버튼 등) 안에는 넣지 않는다 — 버튼 안의 버튼이 된다.
      // 그런 카드는 클릭 자체가 원본으로 가므로 링크가 없어도 길이 있다.
      if (el.closest('button, a, [onclick], .clickable-card, .kpi-clickable')) return;
      var target = econCanonicalPage(row.canonical);
      if (!target || target === activePage) return;
      var a = document.createElement('a');
      a.className = 'econ-src';
      a.href = '?p=' + target;
      a.textContent = econPageLabel(target) + ' ›';
      a.title = name + ' 의 원본 화면으로 이동';
      a.addEventListener('click', function (ev) {
        ev.preventDefault(); ev.stopPropagation();
        try { gotoCanonical(row.canonical); } catch (_) {}
      });
      el.appendChild(a);
    });
  } catch (_) {}
};

// 숫자 옆에 '왜' 한 줄 — 레지스트리의 news 키로 data.json.news 에서 최신 기사 제목을
// 가져와 KPI 카드 아래에 붙인다(IA v3 P3). 규칙 기반이라 인과를 지어내지 않는다:
// 문구는 '관련 뉴스'이고, 7일보다 오래된 기사면 아예 붙이지 않는다(침묵 > 낡은 맥락).
window.econNewsLineFor = function (row) {
  try {
    if (!row || !row.news) return null;
    var d = econData() || {};
    var list = (d.news || {})[row.news];
    if (!Array.isArray(list) || !list.length) return null;
    var top = list[0];
    if (!top || !top.title) return null;
    if (top.isoDate) {
      var age = (Date.now() - new Date(top.isoDate + 'T00:00:00+09:00').getTime()) / 86400000;
      if (!(age >= 0) || age > 7) return null;
    }
    return top;
  } catch (_) { return null; }
};
window.econMarkContext = function (root) {
  try {
    if (!window.ECON_IND) return;
    var scope = root || document;
    scope.querySelectorAll('.kpi-card .econ-stat__label').forEach(function (label) {
      var card = label.closest('.kpi-card');
      if (!card) return;
      var row = window.ECON_IND.find(econTitleText(label));
      var news = row && econNewsLineFor(row);
      var slot = card.querySelector('.econ-why');
      if (!news) { if (slot) slot.remove(); return; }
      if (!slot) {
        slot = document.createElement('span');
        slot.className = 'econ-why';
        var spark = card.querySelector('.econ-stat__spark');
        card.insertBefore(slot, spark || null);
      }
      if (slot.dataset.title === news.title) return;
      slot.dataset.title = news.title;
      slot.textContent = news.title;
      slot.title = '관련 뉴스 · ' + (news.isoDate || '') + ' — ' + news.title;
    });
  } catch (_) {}
};

window.econPageHook = function (id) {
  // 페이지별 init 이 setTimeout(…, 50) 으로 늦게 도는 구조 → 한 박자(400ms) 뒤 실행
  setTimeout(function () {
    try { _applyDefaultPresetsForActivePage(); } catch (_) {}
    try { econMarkHeadings(document.querySelector('.page.active')); } catch (_) {}
    try { econMarkSources(document.querySelector('.page.active')); } catch (_) {}
    try { econMarkContext(document.querySelector('.page.active')); } catch (_) {}
    try { applyWidgetFreshChips(document.querySelector('.page.active')); } catch (_) {}   // §C4 as-of 각인
    try { econMarkFavorites(document.querySelector('.page.active')); } catch (_) {}
    try { econMakeTablesSortable(document.querySelector('.page.active')); } catch (_) {}
    try { econMarkScrollables(document.querySelector('.page.active')); } catch (_) {}
    try { econFoldControls(document.querySelector('.page.active')); } catch (_) {}
    try {
      if (id === 'dashboard') {
        mountGuideBanner(document.getElementById('cmpInfo'), 'cmp_dualaxis',
          '<b>지표 비교 차트 사용법</b> — 두 지표를 고르면 좌(파랑)/우(주황) 이중 Y축으로 겹쳐 봅니다. 축 스케일 차이로 기울기가 과장될 수 있으니, 등락률만 비교하려면 <b>「⚖ 지수화 =100」</b> 버튼을 켜세요.', 'beforebegin');
      }
      if (id === 'realestate') {
        var page = document.getElementById('page-realestate');
        mountGuideBanner(page ? page.querySelector('.widget') : null, 're_range',
          '<b>구간 수익률 측정</b> — 부동산 가격 차트 위에서 <b>시작점을 클릭</b>하고 <b>끝점을 다시 클릭</b>하면 두 시점 사이 변동률이 자동 계산됩니다.', 'beforebegin');
      }
    } catch (_) {}
  }, 400);
};

/* ── 6.3 위젯 오류 표시 · 실데이터 미로드 배너 ─────────────────────────── */
function _escT6(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
window.showWidgetError = function (targetId, opts) {
  opts = opts || {};
  var el = document.getElementById(targetId);
  if (!el) return;
  var lastOk = '';
  try {
    var lu = (window._latestDataForIndicators || {}).lastUpdated || window._lastServerDataTs;
    if (lu) lastOk = ' · 마지막 성공 ' + new Date(lu).toLocaleTimeString('ko-KR',
      { hour: '2-digit', minute: '2-digit', hour12: false });
  } catch (_) {}
  var title = _escT6(opts.title || '데이터를 못 받았어요') + lastOk;
  var detail = opts.detail ? _escT6(String(opts.detail).slice(0, 160)) : '';
  // 컨테이너가 곧 '다시 받기' 버튼 — recipe 가 :is(button,a) 에서 pressed 를 준다.
  var tag = opts.retry ? 'button' : 'div';
  var act = opts.retry ? ' type="button" onclick="' + String(opts.retry).replace(/"/g, '&quot;') + '"' : '';
  var block = '<' + tag + act + ' class="seed-callout__root seed-callout__root--tone_warning econ-callout widget-err">'
            + '<span class="seed-callout__content">'
            + '<span class="seed-callout__title seed-callout__title--tone_warning">' + title + '</span>'
            + (detail ? '<span class="seed-callout__description seed-callout__description--tone_warning">' + detail + '</span>' : '')
            + (opts.retry ? '<span class="seed-callout__description seed-callout__description--tone_warning">눌러서 다시 받기</span>' : '')
            + '</span>'
            + (opts.retry ? '<span class="seed-suffix-icon mat" aria-hidden="true">refresh</span>' : '')
            + '</' + tag + '>';
  if (el.tagName === 'TBODY') {
    var cols = 4;
    try { cols = el.closest('table').querySelectorAll('thead th').length || 4; } catch (_) {}
    el.innerHTML = '<tr><td colspan="' + cols + '">' + block + '</td></tr>';
  } else {
    el.innerHTML = block;
  }
};
window.showDataSourceBanner = function () {
  if (document.getElementById('dataSrcBanner')) return;
  var div = document.createElement('div');
  div.id = 'dataSrcBanner';
  div.innerHTML = '⚠ 서버 데이터(data.json)를 불러오지 못해 <b>예시(Mock) 데이터</b>로 표시 중입니다.' +
    '<button onclick="retryLoadRealData(this)" class="seed-action-button seed-action-button--variant_neutralWeak seed-action-button--size_xsmall seed-action-button--size_xsmall-layout_withText">재시도</button>' +
    '<button type="button" class="btn-plain btn-inline" style="cursor:pointer;font-weight:var(--font-weight-bold);padding:0 2px;" onclick="this.parentNode.remove()" title="닫기">✕</button>';
  document.body.appendChild(div);
};
window.retryLoadRealData = async function (btn) {
  if (btn) { btn.disabled = true; btn.textContent = '확인 중…'; }
  try {
    // 경량 프로브(data_meta.json, ~70B)로 도달성 먼저 확인 → 본체 로드
    var r = await fetch('./data_meta.json?t=' + Date.now(), { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    await loadRealData();
    var b = document.getElementById('dataSrcBanner');
    if (b) b.remove();
    if (typeof showToast === 'function') showToast('서버 데이터 연결 복구 — 실데이터로 전환되었습니다.');
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = '재시도'; }
    if (typeof showToast === 'function') showToast('아직 연결 불가 — 잠시 후 다시 시도하세요.');
  }
};

/* ── 6.4 통합 백업·복구 (암호화 옵션) ───────────────────────────────────── */
var ECON_BACKUP_KEYS = [
  'econ_settings_v1', 'econ_theme',
  'portfolioV1', 'pfSnapshotsV1', 'pfIndicators', 'pfSyncKeyHash',
  'econ_notes', 'econ_notes_session',
  'econ_cal_alerts_v1', 'econ_cmp_sel_v1', 'econ_study_v1',
  'econ_home_kpi_order_v1', 'econ_home_sec_order_v1', 'econ_home_hidden_v1',
  'cfProxyBase', 'realtimeBoost', 'newsClientFetch', 'econ_guides_v1'
];
var ECON_BACKUP_PREFIXES = ['econ_notes_bak'];   // 분석 노트 자동백업 세대 포함
function _collectBackupKeys() {
  var keys = [];
  try {
    for (var i = 0; i < localStorage.length; i++) {
      var k = localStorage.key(i);
      if (ECON_BACKUP_KEYS.indexOf(k) >= 0 ||
          ECON_BACKUP_PREFIXES.some(function (p) { return k.indexOf(p) === 0; })) keys.push(k);
    }
  } catch (_) {}
  return keys;
}
function _renderBackupCount() {
  var el = document.getElementById('setBackupCount');
  if (el) el.textContent = String(_collectBackupKeys().length);
}
function _b64FromBytes(bytes) {
  var bin = '';
  for (var i = 0; i < bytes.length; i += 8192) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
  return btoa(bin);
}
function _bytesFromB64(b64) {
  var bin = atob(b64);
  var out = new Uint8Array(bin.length);
  for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
var PBKDF2_ITER = 600000;   // OWASP Password Storage Cheat Sheet 의 PBKDF2-HMAC-SHA256 권장 반복수
async function _deriveKey(pass, salt) {
  var base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey({ name: 'PBKDF2', salt: salt, iterations: PBKDF2_ITER, hash: 'SHA-256' },
    base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
}
window.exportAllUserData = async function (encrypt) {
  var st = document.getElementById('setBackupStatus');
  try {
    var data = {};
    _collectBackupKeys().forEach(function (k) { data[k] = localStorage.getItem(k); });
    var payload = { schema: 'econ-terminal-backup', version: 1, exportedAt: new Date().toISOString(), origin: location.origin, data: data };
    var fileObj, fname;
    var stamp = new Date().toISOString().slice(0, 10);
    if (encrypt) {
      var p1 = prompt('백업 암호를 입력하세요 (복구 시 동일 암호 필요 — 분실 시 복구 불가):');
      if (!p1) return;
      var p2 = prompt('암호를 한 번 더 입력하세요:');
      if (p1 !== p2) { alert('암호가 일치하지 않습니다.'); return; }
      if (st) { st.textContent = '암호화 중… (키 유도에 수 초가 걸릴 수 있습니다)'; st.style.color = 'var(--c-txt-dim)'; }
      var salt = crypto.getRandomValues(new Uint8Array(16));
      var iv = crypto.getRandomValues(new Uint8Array(12));
      var key = await _deriveKey(p1, salt);
      var ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: iv }, key, new TextEncoder().encode(JSON.stringify(payload)));
      fileObj = {
        schema: 'econ-terminal-backup', version: 1,
        enc: { alg: 'AES-256-GCM', kdf: 'PBKDF2-SHA256', iter: PBKDF2_ITER, salt: _b64FromBytes(salt), iv: _b64FromBytes(iv) },
        ciphertext: _b64FromBytes(new Uint8Array(ct))
      };
      fname = 'econ-terminal-backup-' + stamp + '.enc.json';
    } else {
      fileObj = payload;
      fname = 'econ-terminal-backup-' + stamp + '.json';
    }
    var blob = new Blob([JSON.stringify(fileObj, null, 2)], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = fname;
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
    if (st) { st.textContent = (encrypt ? '암호화 ' : '') + '백업 파일 생성 완료 — ' + Object.keys(payload.data).length + '개 항목'; st.style.color = window.CUP; }
  } catch (e) {
    if (st) { st.textContent = '백업 실패: ' + (e && e.message); st.style.color = window.CDN; }
  }
};
window.importAllUserData = function (input) {
  var file = input && input.files && input.files[0];
  if (!file) return;
  var st = document.getElementById('setBackupStatus');
  var fr = new FileReader();
  fr.onload = async function () {
    try {
      var obj = JSON.parse(fr.result);
      var payload = obj;
      if (obj && obj.enc && obj.ciphertext) {
        var pass = prompt('이 백업은 암호화되어 있습니다. 백업 암호를 입력하세요:');
        if (!pass) { input.value = ''; return; }
        if (st) { st.textContent = '복호화 중…'; st.style.color = 'var(--c-txt-dim)'; }
        var key = await _deriveKey(pass, _bytesFromB64(obj.enc.salt));
        var pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: _bytesFromB64(obj.enc.iv) }, key, _bytesFromB64(obj.ciphertext));
        payload = JSON.parse(new TextDecoder().decode(pt));
      }
      if (!payload || payload.schema !== 'econ-terminal-backup' || !payload.data) throw new Error('형식이 다른 파일입니다 (econ-terminal-backup 아님)');
      var keys = Object.keys(payload.data);
      var pf = null;
      try { pf = JSON.parse(payload.data.portfolioV1 || 'null'); } catch (_) {}
      var summary = '백업 시점: ' + (payload.exportedAt || '?') + '\n항목 ' + keys.length + '개' +
        (pf ? ' · 종목 ' + ((pf.items || []).length) + '개 · 알림 ' + ((pf.alerts || []).length) + '개' : '');
      if (!confirm(summary + '\n\n현재 브라우저 데이터를 이 백업으로 덮어쓸까요? (적용 후 페이지가 새로고침됩니다)')) { input.value = ''; return; }
      keys.forEach(function (k) {
        var v = payload.data[k];
        if (typeof v === 'string') { try { localStorage.setItem(k, v); } catch (_) {} }
      });
      location.reload();
    } catch (e) {
      if (st) { st.textContent = '복구 실패: ' + (e && e.message ? e.message : '암호 불일치 또는 손상된 파일'); st.style.color = window.CDN; }
      input.value = '';
    }
  };
  fr.readAsText(file);
};
/* (위험 구역 '전체 초기화' UI/함수 제거됨 — 백업·복구(_collectBackupKeys/exportAllUserData)는 공유 로직이라 유지) */

/* ── 6.5 포트폴리오 모바일 카드 뷰 (표의 1:1 대응 렌더) ─────────────────── */
window.pfRenderCards = function () {
  var wrap = document.getElementById('pfCardList');
  if (!wrap) return;
  if (window.matchMedia && !window.matchMedia('(max-width: 768px)').matches) { wrap.innerHTML = ''; return; }  // 데스크탑은 표 사용
  if (typeof pfState === 'undefined' || !pfState) return;
  var items = pfVisibleItems();
  if (!items.length) {
    wrap.innerHTML = '<div style="padding:16px;text-align:center;color:var(--c-txt-muted);font-size:var(--font-size-sm);">' +
      (pfState.items.length ? '이 그룹에 종목이 없습니다.' : '종목 코드를 조회해 추가하세요. (한국 6자리 코드 / 미국 티커)') + '</div>';
    return;
  }
  var fx = pfUsdKrw();
  wrap.innerHTML = items.map(function (it) {
    var q = pfQuotes[it.id];
    var alerts = pfState.alerts.filter(function (a) { return a.symbol === it.symbol && a.market === it.market; });
    var pnl = '<span style="color:var(--c-txt-muted);">-</span>';
    if (q && it.avg && it.qty) {
      var pnlNative = (q.price - it.avg) * it.qty;
      var pnlPct = (q.price / it.avg - 1) * 100;
      var pnlKrw = (q.ccy === 'USD') ? (fx ? pnlNative * fx : null) : pnlNative;
      var cls = pnlNative >= 0 ? 'up-txt' : 'down-txt';
      pnl = '<span class="' + cls + '">' + (pnlKrw != null ? (pnlNative >= 0 ? '+' : '') + pfFmtKrw(pnlKrw) : '-') +
            ' (' + (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(2) + '%)</span>';
    }
    return '<div class="pf-card">' +
      '<button type="button" class="pf-card-head btn-plain" onclick="pfOpenChart(\'' + it.id + '\')">' +
        '<span><span class="pf-card-name">' + pfEsc(it.name || it.symbol) + '</span><span class="pf-card-sym">' + pfEsc(it.symbol) + '</span></span>' +
        '<span style="text-align:right;"><span style="font-family:\'Public Sans\';color:var(--c-txt);font-size:var(--font-size-base);">' + (q ? pfFmtPrice(q.price, q.ccy) : '로딩…') + '</span><br>' + (q ? pfChgHtml(q.pct) : '-') + '</span>' +
      '</button>' +
      '<div class="pf-card-grid">' +
        '<div><label>평단가</label><input type="number" step="any" min="0" value="' + (it.avg != null ? it.avg : '') + '" placeholder="-" onchange="pfUpdateItemField(\'' + it.id + '\',\'avg\',this.value,this)"></div>' +
        '<div><label>수량</label><input type="number" step="any" min="0" value="' + (it.qty != null ? it.qty : '') + '" placeholder="-" onchange="pfUpdateItemField(\'' + it.id + '\',\'qty\',this.value,this)"></div>' +
      '</div>' +
      '<div class="pf-card-foot">' +
        '<span>평가손익: ' + pnl + '</span>' +
        '<span style="white-space:nowrap;">' +
          '<button onclick="pfOpenAlerts(\'' + it.id + '\')" title="카카오 알림 설정" style="background:transparent;border:none;cursor:pointer;font-size:var(--font-size-base);">' + (alerts.length ? '🔔' : '🕭') + '</button><span style="font-size:var(--font-size-xs);color:var(--c-txt-dim);">' + (alerts.length || '') + '</span> ' +
          '<button onclick="pfDeleteItem(\'' + it.id + '\')" title="삭제" style="background:transparent;border:none;cursor:pointer;font-size:var(--font-size-base);color:var(--c-txt-dim);">🗑</button>' +
        '</span>' +
      '</div>' +
    '</div>';
  }).join('');
};
// 화면 폭 변경(회전 등) 시 카드/표 전환 반영 — 250ms 디바운스
window.addEventListener('resize', (function () {
  var t = null;
  return function () {
    clearTimeout(t);
    t = setTimeout(function () { try { if (typeof pfState !== 'undefined' && pfState) pfRenderCards(); } catch (_) {} }, 250);
  };
})());

/* ── 6.6 초기 진입(대시보드) 훅 — 가이드·기본 기간 1회 적용 ─────────────── */
document.addEventListener('DOMContentLoaded', function () {
  setTimeout(function () { try { econPageHook('dashboard'); } catch (_) {} }, 900);
});
})();

// ═══ 수동 새로고침 버튼 ══════════════════════════════════════════════════════
(function() {
  var _refreshCooldown = false;
  window.manualRefreshData = function() {
    if(_refreshCooldown) return;
    _refreshCooldown = true;
    var btn  = document.getElementById('globalRefreshBtn');
    var icon = document.getElementById('globalRefreshIcon');
    var lbl  = document.getElementById('globalRefreshLabel');
    if(icon) icon.classList.add('spin-anim');
    if(lbl)  lbl.textContent = '새로고침 중…';
    if(btn)  { btn.disabled = true; btn.style.opacity = '.5'; }
    // 오프라인이면 페치 시도 없이 즉시 안내 (기내모드·지하철에서 '완료' 오표시 방지)
    if(typeof navigator !== 'undefined' && navigator.onLine === false) {
      if(icon) icon.classList.remove('spin-anim');
      if(lbl)  { lbl.textContent = '오프라인 — 연결 확인'; lbl.style.color = 'var(--c-down,#ef5350)'; }
      setTimeout(function() { if(lbl) { lbl.textContent = '새로고침'; lbl.style.color = ''; } }, 3000);
      setTimeout(function() { _refreshCooldown = false; if(btn) { btn.disabled = false; btn.style.opacity = ''; } }, 3000);
      return;
    }
    // 각 페치가 성공(true)/실패(false)를 반환하게 해 결과를 집계 — 전부 실패한 오프라인/장애
    // 상황이 '새로고침 완료'로 위장되던 문제 수정.
    var _ok = function(p){ return p.then(function(){ return true; }, function(){ return false; }); };
    Promise.all([
      _ok(loadRealData()),
      _ok(loadRealtimeFx()),
      _ok(loadRealtimeMarket()),
      _ok(typeof refreshMoversFromClient === 'function' ? refreshMoversFromClient() : Promise.resolve()),
      _ok(typeof fetchSentimentClient === 'function' && typeof applySentimentClient === 'function'
        ? fetchSentimentClient().then(applySentimentClient) : Promise.resolve()),
      _ok(typeof loadFreshNews === 'function' ? loadFreshNews() : Promise.resolve()),
    ]).then(function(results) {
      var okCount = results.filter(Boolean).length;
      // 현재 활성 페이지 차트 재빌드 (실시간 패치 반영)
      try {
        var activePage = document.querySelector('.page.active');
        if(activePage) {
          var id = activePage.id;
          if(id === 'page-dashboard')      { try { initMainChart(mainPeriodUnit); buildMoverTable(curMoverTab); buildGlobalTable(); } catch(_){} }
          else if(id === 'page-market')    { try { initMarketPage(); } catch(_){} }
          else if(id === 'page-equity')    { try { buildEquityPage(); } catch(_){} }
          else if(id === 'page-macro')     { try { initMacroPage(macroTab); } catch(_){} }
          else if(id === 'page-investor')  { try { buildInvestorPage(); } catch(_){} }
          else if(id === 'page-realestate'){ try { buildReCharts(); if(typeof buildUsReCharts==='function') buildUsReCharts(); } catch(_){} }
        }
      } catch(_) {}
      if(icon) icon.classList.remove('spin-anim');
      if(lbl) {
        if(okCount === 0)                { lbl.textContent = '갱신 실패 — 네트워크 확인'; lbl.style.color = 'var(--c-down,#ef5350)'; }
        else if(okCount < results.length){ lbl.textContent = okCount + '/' + results.length + ' 갱신됨'; lbl.style.color = 'var(--c-warn,#f0c75e)'; }
        else                             { lbl.textContent = '새로고침 완료'; }
      }
      setTimeout(function() { if(lbl) { lbl.textContent = '새로고침'; lbl.style.color = ''; } }, 3000);
    });
    setTimeout(function() {
      _refreshCooldown = false;
      if(btn) { btn.disabled = false; btn.style.opacity = ''; }
    }, 30000);
  };
})();

// ═══ URL 딥링크 + popstate ════════════════════════════════════════════════════
window.addEventListener('load', function() {
  try {
    var _VALID = ['dashboard','portfolio','equity','macro','market','investor','realestate','calendar','study','notes','merblog','merlens','settings'];
    var p = new URLSearchParams(location.search).get('p');
    if(p && _VALID.indexOf(p) >= 0 && p !== 'dashboard') {
      showPage(p, (typeof menuItemFor === 'function' ? menuItemFor(p) : null) || null);
    } else if(p && _VALID.indexOf(p) < 0) {
      // 화이트리스트 밖 주소는 showPage 까지 가지도 않는다 — 여기서도 안내해야 조용한 폴백이 없다(C7).
      if(typeof econNoticeUnknownPage === 'function') econNoticeUnknownPage(p);
    }
    // 2차 탭(&t=)도 복원한다 — 첫 진입과 뒤로가기 양쪽(IA v3 P0.5)
    if(typeof econApplyTabFromUrl === 'function') econApplyTabFromUrl(p || 'dashboard');
    window.addEventListener('popstate', function() {
      try {
        var pg = new URLSearchParams(location.search).get('p') || 'dashboard';
        if(_VALID.indexOf(pg) >= 0) {
          showPage(pg, (typeof menuItemFor === 'function' ? menuItemFor(pg) : null) || null);
          if(typeof econApplyTabFromUrl === 'function') econApplyTabFromUrl(pg);
        }
      } catch(_) {}
    });
  } catch(_) {}
});

// ═══ 키보드 단축키 ════════════════════════════════════════════════════════════
document.addEventListener('keydown', function(e) {
  var tag = (document.activeElement || {}).tagName || '';
  if(tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  if((document.activeElement || {}).isContentEditable) return;
  if(e.ctrlKey || e.altKey || e.metaKey) return;
  var PAGE_MAP = {'1':'dashboard','2':'portfolio','3':'equity','4':'macro','5':'market','6':'investor','7':'realestate','8':'calendar','9':'notes','0':'settings','s':'study','S':'study','m':'merlens','M':'merlens'};
  var id = PAGE_MAP[e.key];
  if(id) {
    e.preventDefault();
    showPage(id, (typeof menuItemFor === 'function' ? menuItemFor(id) : null) || null);
    return;
  }
  if(e.key === 'r' || e.key === 'R') {
    e.preventDefault();
    loadRealData().catch(function(){});
    loadRealtimeFx().catch(function(){});
    loadRealtimeMarket().catch(function(){});
    return;
  }
  if(e.key === '?') {
    e.preventDefault();
    var modal = document.getElementById('kbShortcutModal');
    if(modal) modal.style.display = (modal.style.display === 'flex') ? 'none' : 'flex';
    return;
  }
  if(e.key === 'Escape') {
    var kb = document.getElementById('kbShortcutModal');
    if(kb && kb.style.display !== 'none') { kb.style.display = 'none'; }
  }
});

// ═══ 포트폴리오 CSV 내보내기 ══════════════════════════════════════════════════
function pfExportCsv() {
  if(!pfState || !pfState.items || !pfState.items.length) {
    if(typeof showToast === 'function') showToast('내보낼 종목이 없습니다.', 3000);
    return;
  }
  var fx = pfUsdKrw();
  var today = new Date().toISOString().slice(0, 10);
  var groupMap = {};
  (pfState.groups || []).forEach(function(g) { groupMap[g.id] = g.name; });
  var rows = [['종목코드','종목명','시장','유형','통화','평단가','보유수량','현재가','평가금액(원)','매입금액(원)','평가손익(원)','수익률(%)','그룹']];
  pfState.items.forEach(function(it) {
    var q = pfQuotes[it.id] || {};
    var price = q.price || '';
    var mul = (q.ccy === 'USD' && fx) ? fx : 1;
    var evalKrw = (q.price && it.qty) ? q.price * it.qty * mul : '';
    var costKrw = (it.avg != null && it.qty) ? it.avg * it.qty * (q.ccy === 'USD' ? (it.fxBuy || fx || 1) : 1) : '';
    var pnl = (evalKrw !== '' && costKrw !== '') ? evalKrw - costKrw : '';
    var pct = (pnl !== '' && costKrw) ? (pnl / costKrw * 100).toFixed(2) : '';
    rows.push([
      it.symbol || '', it.name || '', it.market || '',
      it.secType === 'etf' ? 'ETF' : '주식',
      it.ccy || '', it.avg != null ? it.avg : '', it.qty != null ? it.qty : '',
      price,
      evalKrw !== '' ? Math.round(evalKrw) : '',
      costKrw !== '' ? Math.round(costKrw) : '',
      pnl !== '' ? Math.round(pnl) : '', pct,
      groupMap[it.group] || '',
    ]);
  });
  var csv = rows.map(function(r) {
    return r.map(function(v) { return '"' + String(v).replace(/"/g, '""') + '"'; }).join(',');
  }).join('\n');
  var blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url; a.download = 'portfolio_' + today + '.csv';
  document.body.appendChild(a); a.click();
  document.body.removeChild(a);
  setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
}

// ═══ 페이지 잠금 (투자 현황·설정) ═══════════════════════════════════════════════
// 열람 방지용 클라이언트 게이트. 비밀번호는 SHA-256 해시로만 보관(공개 저장소 — 평문 금지).
// 해제 상태는 sessionStorage 에만 유지 → 탭을 닫으면 다시 잠긴다.
// 모든 진입이 showPage() 를 지나므로(메뉴·?p= 딥링크·popstate·키보드 단축키) 관문은 app1.js
// showPage 상단의 econLockGate 호출 한 곳이다. 개발자도구로 우회는 가능하나, 민감 데이터
// (평단가·수량)는 각 브라우저 localStorage 에만 있어 '어깨너머 열람 방지' 목적에는 충분.
(function() {
  var LOCKED = ['portfolio', 'settings'];
  var HASH = '54bb6a0d2ea7d49744e886aa20859d70b6fc4ee0b9f144353ecb4b39195767f3';
  var SS_KEY = 'econLockOk_v1';

  function unlocked() { try { return sessionStorage.getItem(SS_KEY) === '1'; } catch(_) { return false; } }

  // showPage 에서 호출 — true 반환 시 전환 중단(모달이 성공하면 showPage 재호출)
  window.econLockGate = function(id, el) {
    if(LOCKED.indexOf(id) < 0 || unlocked()) return false;
    openModal(id, el);
    return true;
  };

  function sha256Hex(s) {
    if(!(window.crypto && crypto.subtle)) return Promise.reject(new Error('insecure context'));
    return crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)).then(function(buf) {
      return Array.prototype.map.call(new Uint8Array(buf), function(b) {
        return ('0' + b.toString(16)).slice(-2);
      }).join('');
    });
  }

  var _overlay = null;
  function closeModal() {
    if(_overlay) { _overlay.remove(); _overlay = null; }
    document.removeEventListener('keydown', onEsc, true);
  }
  function onEsc(e) { if(e.key === 'Escape') { e.stopPropagation(); closeModal(); } }

  function openModal(id, el) {
    if(_overlay) { var i0 = _overlay.querySelector('input'); if(i0) i0.focus(); return; }
    _overlay = document.createElement('div');
    _overlay.setAttribute('role', 'dialog');
    _overlay.setAttribute('aria-modal', 'true');
    _overlay.setAttribute('aria-label', '잠금 해제');
    _overlay.style.cssText = 'position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;';
    var card = document.createElement('div');
    card.style.cssText = 'background:var(--modal-bg,var(--c-card));border:1px solid var(--modal-border,var(--c-border));border-radius:var(--r-sm);padding:22px 24px;width:min(320px,90vw);box-shadow:0 8px 32px rgba(0,0,0,.4);';
    card.innerHTML =
      '<div style="font-size:var(--font-size-md);font-weight:var(--font-weight-semibold);color:var(--c-txt);margin-bottom:6px;">잠긴 페이지</div>' +
      '<div style="font-size:var(--font-size-sm);color:var(--c-txt-muted);margin-bottom:14px;">' + (id === 'settings' ? '설정' : '투자 현황') + ' 페이지는 비밀번호가 필요합니다.</div>' +
      '<input type="password" inputmode="numeric" autocomplete="off" aria-label="비밀번호" style="width:100%;box-sizing:border-box;background:var(--c-surface);border:1px solid var(--c-border);border-radius:var(--r-xs);padding:8px 10px;font-size:var(--font-size-md);">' +
      '<div data-lock-err style="display:none;color:var(--c-down,#e05555);font-size:var(--font-size-xs);margin-top:6px;">비밀번호가 올바르지 않습니다.</div>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px;">' +
        '<button data-lock-cancel class="seed-action-button seed-action-button--variant_neutralOutline seed-action-button--size_small seed-action-button--size_small-layout_withText">취소</button>' +
        '<button data-lock-ok class="seed-action-button seed-action-button--variant_brandSolid seed-action-button--size_small seed-action-button--size_small-layout_withText">확인</button>' +
      '</div>';
    _overlay.appendChild(card);
    document.body.appendChild(_overlay);

    var input = card.querySelector('input');
    var err = card.querySelector('[data-lock-err]');
    function submit() {
      var v = input.value || '';
      sha256Hex(v).then(function(h) {
        if(h === HASH) {
          try { sessionStorage.setItem(SS_KEY, '1'); } catch(_) {}
          closeModal();
          showPage(id, el);
        } else {
          err.style.display = 'block';
          input.value = '';
          input.focus();
        }
      }).catch(function() {
        err.textContent = '이 환경(비보안 컨텍스트)에서는 잠금 해제를 지원하지 않습니다. https 로 접속하세요.';
        err.style.display = 'block';
      });
    }
    card.querySelector('[data-lock-ok]').addEventListener('click', submit);
    card.querySelector('[data-lock-cancel]').addEventListener('click', closeModal);
    input.addEventListener('keydown', function(e) { if(e.key === 'Enter') submit(); });
    _overlay.addEventListener('mousedown', function(e) { if(e.target === _overlay) closeModal(); });
    document.addEventListener('keydown', onEsc, true);
    setTimeout(function() { input.focus(); }, 30);
  }

  // 메뉴에 잠금 표시 — 어떤 메뉴가 보호되는지 시각적 안내
  window.addEventListener('load', function() {
    try {
      document.querySelectorAll('.menu-item').forEach(function(m) {
        var nav = m.getAttribute('data-nav') || m.getAttribute('onclick') || '';
        if(LOCKED.some(function(p) { return nav === p || nav.indexOf("'" + p + "'") >= 0; })) {
          var s = document.createElement('span');
          s.className = 'mat';
          s.textContent = 'lock';
          s.setAttribute('aria-hidden', 'true');
          m.setAttribute('title', '비밀번호 잠금');
          s.style.cssText = 'font-size:var(--font-size-xs);opacity:.55;';
          m.appendChild(s);
        }
      });
    } catch(_) {}
  });
})();

/* ── MY 레일 (IA v3 P4) ───────────────────────────────────────────────────
   개인 영역이 페이지로 갇혀 있었다(투자 현황·캘린더·노트가 각각 별도 화면).
   레일은 아이콘 56px 만 자리를 차지하고, 패널 312px 는 본문 위에 얹힌다.
   상태는 전부 localStorage — 서버로 나가는 것은 없다. */
(function econRail() {
  var FAV_KEY = 'econ_fav_v1';
  var RECENT_KEY = 'econ_recent_v1';
  var _open = null;

  function favs() {
    try { return JSON.parse(localStorage.getItem(FAV_KEY) || '[]') || []; } catch (_) { return []; }
  }
  function saveFavs(list) {
    try { localStorage.setItem(FAV_KEY, JSON.stringify(list.slice(0, 40))); } catch (_) {}
  }
  window.econToggleFav = function (id) {
    var list = favs();
    var i = list.indexOf(id);
    if (i >= 0) list.splice(i, 1); else list.unshift(id);
    saveFavs(list);
    if (_open === 'fav') render('fav');
    return favs().indexOf(id) >= 0;
  };
  window.econRecentPush = function (pageId) {
    try {
      var list = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]') || [];
      list = list.filter(function (x) { return x !== pageId; });
      list.unshift(pageId);
      localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 8)));
    } catch (_) {}
  };

  // 별 하나를 지금 상태로 칠한다 — **값이 다를 때만 쓴다**.
  // textContent 를 무조건 다시 쓰면 텍스트 노드가 교체되고, 그게 childList 변경이라
  // observeHeadings 의 옵저버가 깨어나 200ms 뒤 이 함수를 다시 부른다 = 자기 유발 루프.
  // 그 루프가 유휴 20초 DOM 변경 2,884건 중 2,820건(97.8%)이었다(기획 2026-09-21 D1).
  function paintFav(btn, on, label) {
    var mark = on ? '★' : '☆';
    var tip = (on ? '관심에서 빼기: ' : '관심에 담기: ') + label;
    if (btn.getAttribute('aria-pressed') !== String(on)) btn.setAttribute('aria-pressed', String(on));
    if (btn.getAttribute('title') !== tip) btn.setAttribute('title', tip);
    if (btn.textContent !== mark) btn.textContent = mark;
  }

  // 위젯 제목 옆 별 — 레지스트리가 아는 지표에만 붙는다(이름 매칭은 econTitleText 공통 규칙)
  window.econMarkFavorites = function (root) {
    try {
      if (!window.ECON_IND) return;
      var set = favs();
      (root || document).querySelectorAll('.widget-title').forEach(function (t) {
        if (t.closest('button, a, [onclick], .clickable-card, .kpi-clickable')) return;
        var row = window.ECON_IND.find(econTitleText(t));
        var btn = t.querySelector('.econ-fav');
        if (!row) { if (btn) btn.remove(); return; }
        if (!btn) {
          btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'econ-fav';
          btn.addEventListener('click', function (ev) {
            ev.stopPropagation(); ev.preventDefault();
            paintFav(btn, econToggleFav(row.id), row.label);
          });
          t.appendChild(btn);
          if (window.econOrderTools) window.econOrderTools(t);
        }
        paintFav(btn, set.indexOf(row.id) >= 0, row.label);
      });
    } catch (_) {}
  };

  var TITLES = { fav: '관심 지표', recent: '최근 본 화면', cal: '오늘 일정', pf: '투자 현황' };
  var PAGE_LABEL = {
    dashboard: '대시보드 홈', equity: '주식시장', market: '시장 지표', macro: '거시경제',
    calendar: '경제 일정', realestate: '부동산', investor: '주요 투자자', notes: '분석 노트',
    study: '스터디 기록', merlens: '메르 렌즈', portfolio: '투자 현황', settings: '설정'
  };

  function esc(v) { return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }

  function valueOf(row) {
    try {
      var d = econData();
      if (!d || !row || !row.data) return '';
      var node = d, parts = String(row.data).split(':')[0].split('.');
      for (var i = 0; i < parts.length; i++) { node = node && node[parts[i]]; }
      if (node == null) return '';
      var v = (typeof node === 'object') ? (node.value != null ? node.value : node.price) : node;
      return (v == null) ? '' : (typeof v === 'number' ? v.toLocaleString() : String(v).slice(0, 14));
    } catch (_) { return ''; }
  }

  function render(kind) {
    var body = document.getElementById('econRailBody');
    var title = document.getElementById('econRailTitle');
    if (!body || !title) return;
    title.textContent = TITLES[kind] || '';
    if (kind === 'fav') {
      var list = favs();
      if (!list.length) {
        body.innerHTML = '<div class="rail-empty">관심 지표가 없습니다.<br>지표 제목 옆의 별을 누르면 여기에 모입니다.</div>';
        return;
      }
      body.innerHTML = list.map(function (id) {
        var row = window.ECON_IND && window.ECON_IND.get(id);
        if (!row) return '';
        return '<div class="rail-row"><button type="button" class="btn-plain" data-goto="' + esc(row.canonical) + '"' +
               ' style="text-align:left;flex:1;cursor:pointer;color:var(--c-txt);">' + esc(row.label) + '</button>' +
               '<span style="font-family:var(--font-num);color:var(--c-txt-dim);">' + esc(valueOf(row)) + '</span></div>';
      }).join('');
      return;
    }
    if (kind === 'recent') {
      var r = [];
      try { r = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]') || []; } catch (_) {}
      if (!r.length) { body.innerHTML = '<div class="rail-empty">아직 둘러본 화면이 없습니다.</div>'; return; }
      body.innerHTML = r.map(function (p) {
        return '<div class="rail-row"><button type="button" class="btn-plain" data-page="' + esc(p) + '"' +
               ' style="text-align:left;flex:1;cursor:pointer;color:var(--c-txt);">' + esc(PAGE_LABEL[p] || p) + '</button></div>';
      }).join('');
      return;
    }
    if (kind === 'cal') {
      var d = econData();
      var ev = (d && d.economicCalendar && d.economicCalendar.events) || [];
      var today = new Date().toISOString().slice(0, 10);
      var next = ev.filter(function (e) { return String(e.iso || e.date || '').slice(0, 10) >= today; })
                   .sort(function (a, b) { return String(a.iso || a.date).localeCompare(String(b.iso || b.date)); })
                   .slice(0, 6);
      if (!next.length) { body.innerHTML = '<div class="rail-empty">예정된 일정이 없습니다.</div>'; return; }
      body.innerHTML = '<div class="rail-empty" style="margin-bottom:8px;">앞으로 ' + next.length + '건</div>' +
        next.map(function (e) {
          var stars = '★'.repeat(Math.max(0, Math.min(3, e.stars || 0)));
          return '<div class="rail-row"><span style="flex:1;">' + esc(e.name || e.title || '') +
                 (stars ? ' <span style="color:var(--c-warn,#f0c75e);">' + stars + '</span>' : '') + '</span>' +
                 '<span style="color:var(--c-txt-dim);white-space:nowrap;">' + esc(e.dt || e.iso || '') + '</span></div>';
        }).join('') +
        '<button type="button" class="btn-plain" data-page="calendar" style="margin-top:10px;color:var(--c-primary);cursor:pointer;">전체 일정 보기 &rsaquo;</button>';
      return;
    }
    body.innerHTML = '<div class="rail-empty">가상 포트폴리오와 종목 알림은 잠금 화면에 있습니다.</div>' +
      '<button type="button" class="btn-plain" data-page="portfolio" style="margin-top:10px;color:var(--c-primary);cursor:pointer;">투자 현황 열기 &rsaquo;</button>';
  }

  function toggle(kind) {
    var panel = document.getElementById('econRailPanel');
    if (!panel) return;
    if (_open === kind) { panel.hidden = true; _open = null; }
    else { render(kind); panel.hidden = false; _open = kind; }
    document.querySelectorAll('#econRail .econ-rail__btn').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.rail === _open));
    });
  }

  function start() {
    var rail = document.getElementById('econRail');
    if (!rail) return;
    document.body.classList.add('has-rail');
    rail.addEventListener('click', function (ev) {
      var b = ev.target.closest('.econ-rail__btn');
      if (b) toggle(b.dataset.rail);
    });
    var close = document.getElementById('econRailClose');
    if (close) close.addEventListener('click', function () { toggle(_open); });
    var panel = document.getElementById('econRailPanel');
    if (panel) panel.addEventListener('click', function (ev) {
      var goto = ev.target.closest('[data-goto]');
      if (goto) { try { gotoCanonical(goto.dataset.goto); } catch (_) {} return; }
      var page = ev.target.closest('[data-page]');
      if (page) { try { showPage(page.dataset.page, menuItemFor(page.dataset.page)); } catch (_) {} }
    });
    try { econMarkFavorites(document.getElementById('mainContent')); } catch (_) {}
    try {
      var cur = (document.querySelector('.page.active') || {}).id || '';
      if (cur) econRecentPush(cur.replace(/^page-/, ''));
    } catch (_) {}
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();

/* ── 전역 검색 · 목적 프리셋 · 표 정렬 (IA v3 P5) ─────────────────────────
   찾을 방법이 없었다(D12): 전역 검색 0 · 정렬 가능한 표 0 · 지표 즐겨찾기 0.
   셋 다 지표 레지스트리 위에서 한 번에 선다. */
(function econFind() {
  // 목적 프리셋 — 지표를 찾아다니지 않고 질문을 고른다. 각 질문은 그 답이 있는
  // 화면(+탭·필터)으로 데려간다. 조건은 사람 말로 적는다.
  var PRESETS = [
    { q: '오늘 뭐가 움직였나', cond: '등락률 · 오늘', go: function () { gotoCanonical('market#equity'); } },
    { q: '금리는 어디로',     cond: '국고·미국채 · 곡선', go: function () { gotoCanonical('market#bond'); } },
    { q: '환율 부담',         cond: 'USD/KRW · 최근 추이', go: function () { gotoCanonical('market#fx'); } },
    { q: '원자재 충격',       cond: '에너지·금속 · 재고', go: function () { gotoCanonical('market#commodity'); } },
    { q: '물가 온도',         cond: 'CPI·PPI · 전년비', go: function () { showPage('macro', menuItemFor('macro')); setTimeout(function () { try { setMacroCatFilter('물가'); } catch (_) {} }, 400); } },
    { q: '고용은 버티나',     cond: '실업률·고용 지표', go: function () { showPage('macro', menuItemFor('macro')); setTimeout(function () { try { setMacroCatFilter('고용'); } catch (_) {} }, 400); } },
    { q: '외국인은 사는가',   cond: '투자자별 순매매', go: function () { gotoCanonical('flow'); } },
    { q: '부동산 온도',       cond: '가격지수·거래·대출', go: function () { showPage('realestate', menuItemFor('realestate')); } }
  ];

  var overlay, input, results, items = [], cursor = -1;

  function rowsFor(q) {
    var out = [];
    if (!window.ECON_IND) return out;
    var needle = String(q || '').trim().toLowerCase();
    if (!needle) {
      PRESETS.forEach(function (p) { out.push({ kind: 'preset', preset: p }); });
      return out;
    }
    window.ECON_IND.rows.concat(window.ECON_IND.datasets).forEach(function (r) {
      var hay = [r.label, r.id].concat(r.aliases || [], r.keywords || []).join(' ').toLowerCase();
      if (hay.indexOf(needle) >= 0) out.push({ kind: 'ind', row: r });
    });
    PRESETS.forEach(function (p) {
      if ((p.q + ' ' + p.cond).toLowerCase().indexOf(needle) >= 0) out.push({ kind: 'preset', preset: p });
    });
    out.sort(function (a, b) {
      var at = a.kind === 'ind' ? (a.row.tier || 9) : 0;
      var bt = b.kind === 'ind' ? (b.row.tier || 9) : 0;
      return at - bt;
    });
    return out.slice(0, 12);
  }

  function esc(v) { return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }

  function paint(q) {
    items = rowsFor(q);
    cursor = items.length ? 0 : -1;
    if (!items.length) {
      results.innerHTML = '<div class="econ-search__hint">맞는 지표가 없습니다. 이름 일부만 적어도 됩니다(예: 금리).</div>';
      return;
    }
    var head = q ? '' : '<div class="econ-search__hint">질문으로 찾기 — 무엇이 궁금한지 고르세요</div>';
    results.innerHTML = head + items.map(function (it, i) {
      if (it.kind === 'preset') {
        return '<button type="button" role="option" data-i="' + i + '" aria-selected="' + (i === cursor) + '">' +
               '<span>' + esc(it.preset.q) + '</span>' +
               '<span style="color:var(--c-txt-dim);font-size:var(--font-size-xs);">' + esc(it.preset.cond) + '</span></button>';
      }
      var r = it.row;
      var where = (typeof econCanonicalPage === 'function') ? econCanonicalPage(r.canonical) : null;
      return '<button type="button" role="option" data-i="' + i + '" aria-selected="' + (i === cursor) + '">' +
             '<span>' + esc(r.label) + (r.unit ? ' <span style="color:var(--c-txt-dim);font-size:var(--font-size-xs);">' + esc(r.unit) + '</span>' : '') + '</span>' +
             '<span style="color:var(--c-txt-dim);font-size:var(--font-size-xs);">' +
             esc(where && typeof econPageLabel === 'function' ? econPageLabel(where) : '') + '</span></button>';
    }).join('');
  }

  function pick(i) {
    var it = items[i];
    if (!it) return;
    close();
    if (it.kind === 'preset') { try { it.preset.go(); } catch (_) {} return; }
    try { gotoCanonical(it.row.canonical); } catch (_) {}
  }

  function open() {
    if (!overlay) return;
    overlay.hidden = false;
    input.value = '';
    paint('');
    setTimeout(function () { try { input.focus(); } catch (_) {} }, 20);
  }
  function close() { if (overlay) overlay.hidden = true; }
  window.econOpenSearch = open;

  function start() {
    overlay = document.getElementById('econSearchOverlay');
    input = document.getElementById('econSearchInput');
    results = document.getElementById('econSearchResults');
    if (!overlay || !input || !results) return;
    var btn = document.getElementById('econSearchBtn');
    if (btn) btn.addEventListener('click', open);
    overlay.addEventListener('click', function (ev) { if (ev.target === overlay) close(); });
    input.addEventListener('input', function () { paint(input.value); });
    input.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') { close(); return; }
      if (ev.key === 'Enter') { ev.preventDefault(); pick(cursor); return; }
      if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
        ev.preventDefault();
        if (!items.length) return;
        cursor = (cursor + (ev.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
        results.querySelectorAll('[role="option"]').forEach(function (b) {
          b.setAttribute('aria-selected', String(Number(b.dataset.i) === cursor));
        });
      }
    });
    results.addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-i]');
      if (b) pick(Number(b.dataset.i));
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.key !== '/' || ev.ctrlKey || ev.altKey || ev.metaKey) return;
      var tag = (document.activeElement || {}).tagName || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if ((document.activeElement || {}).isContentEditable) return;
      ev.preventDefault();
      open();
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();

  /* 표 정렬 — 정렬 가능한 표가 하나도 없었다. 머리글을 누르면 그 열로 정렬한다.
     숫자는 숫자로(부호·쉼표·%·원 제거), 나머지는 문자열로 비교한다.
     colspan 이 있는 표, 4행 미만, 이미 자체 정렬을 가진 표는 건드리지 않는다. */
  function cellNum(td) {
    var t = (td.textContent || '').replace(/[,\s%원$]/g, '').replace(/[()]/g, '');
    if (/^[+\-]?\d+(\.\d+)?$/.test(t)) return parseFloat(t);
    return null;
  }
  // 가로로 넘치는 표에 '밀어서 볼 수 있다'는 표시를 단다(모바일 감사 2026-09-18).
// 넘치는 표는 오른쪽 열이 그냥 잘려 보여서, 값이 없는 것과 구분되지 않았다.
window.econMarkScrollables = function (root) {
  try {
    var narrow = (window.innerWidth || 1024) < 768;
    (root || document).querySelectorAll('table').forEach(function (tb) {
      var wrap = tb.parentElement;
      if (!wrap) return;
      var st = getComputedStyle(wrap);
      if (st.overflowX !== 'auto' && st.overflowX !== 'scroll') return;
      var over = wrap.scrollWidth > wrap.clientWidth + 4;
      wrap.classList.toggle('econ-scrollhint', over && narrow);
      var tag = wrap.querySelector('.econ-scrollhint__tag');
      if (over && narrow) {
        if (!tag) {
          tag = document.createElement('span');
          tag.className = 'econ-scrollhint__tag';
          tag.textContent = '← 밀어서 보기';
          wrap.appendChild(tag);
        }
      } else if (tag) { tag.remove(); }
    });
  } catch (_) {}
};

/* ── 좁은 화면 컨트롤 접기 (기획안 1xWjJ5MM P4) ──────────────────────────
   390 에서 첫 화면의 38~62%를 버튼이 먹고 있었다(realestate 430/699px). 지표를 보려면
   컨트롤 한 화면을 먼저 지나야 한다는 뜻이다. 데스크톱은 그대로 두고, ≤480 에서만
   「선택지 묶음」을 「지금 고른 것 ▾」 한 줄로 접는다. 누르면 원래 묶음이 그대로
   펼쳐진다 — DOM 도 핸들러도 건드리지 않고 표시만 바꾼다(hidden 토글).

   접는 대상을 좁게 잡는 이유: 버튼 4개 이상이라는 조건만으로는 「저장/불러오기」 같은
   동작 버튼 줄, 링크 목록, 지표 값 카드까지 접힌다(첫 판에서 35개 중 23개가 그랬다).
   접힌 값이 무엇인지 말할 수 없으면 접으면 안 된다 — 그래서 **선택된 항목이 실제로
   있는 묶음**만 접는다. 선택 표시(active/aria-pressed/data-checked/aria-selected)가
   그 묶음이 선택지라는 유일한 증거다.

   MutationObserver 재진입 주의: 이 함수는 #mainContent 의 childList 를 보는 관찰자가
   부른다. 여기서 DOM 을 건드리면 관찰자가 다시 깨어나 무한 회전한다(첫 판은 5Hz 로
   계속 돌았다). 그래서 ① 값이 바뀔 때만 쓰고 ② 실제로 고칠 게 있을 때만 DOM 을
   만지며 ③ 관찰자는 econFoldControls 가 만든 변경을 무시하도록 _foldBusy 로 잠근다. */
window._foldBusy = false;
window.econFoldControls = function (root) {
  if (window._foldBusy) return;
  try {
    var narrow = window.matchMedia && window.matchMedia('(max-width: 480px)').matches;
    var isActive = function (b) {
      return b.classList.contains('active') || b.getAttribute('aria-pressed') === 'true' ||
             b.hasAttribute('data-checked') || b.getAttribute('aria-selected') === 'true';
    };
    var labelOf = function (btns) {
      return btns.filter(isActive).slice(0, 3)
        .map(function (b) { return (b.textContent || '').trim().replace(/\s+/g, ' '); })
        .filter(Boolean).join(' · ').slice(0, 28);
    };
    // 후보는 버튼의 부모뿐이다 — 위젯 안 모든 div·span 을 훑으면 22,000줄 DOM 에서
    // 변경마다 수만 개를 읽는다.
    var groups = new Set();
    (root || document).querySelectorAll('.widget button, .widget [role="tab"]').forEach(function (b0) {
      if (b0.parentElement) groups.add(b0.parentElement);
    });
    // 바깥 묶음이 이미 후보면 안쪽은 접지 않는다 — 한 번에 걸러야 한다. 처리 순서에
    // 기대면(이번 판에서 실제로 그랬다) 안쪽이 먼저 잡혀 이중으로 접힌다:
    // 「KOSPI ▾」 를 펼쳤더니 그 안에 또 「일 ▾」 가 있는 상태가 된다.
    // 요약 줄 자신도 button 이다 — 세면 부모의 버튼 개수가 부풀어 부모까지 후보가 되고,
    // 그 결과 접힌 줄 안에 또 접힌 줄이 생긴다(실측: 홈의 econ-head__tools).
    var btnsOf = function (g) {
      return Array.prototype.filter.call(g.children, function (c) {
        if (c.classList && c.classList.contains('ctl-fold__sum')) return false;
        return c.tagName === 'BUTTON' || c.getAttribute('role') === 'tab';
      });
    };
    // 접을 자격이 있는 묶음만 먼저 추린 뒤, 그 안쪽에 있는 것은 뺀다. 자격 없는 조상을
    // 기준으로 빼면 안쪽까지 같이 빠져 아무것도 접히지 않는다.
    var cands = [];
    groups.forEach(function (g) {
      if (g.classList.contains('ctl-fold__sum')) return;
      var bs = btnsOf(g);
      if (bs.length >= 4 && (bs.some(isActive) || g.previousElementSibling &&
          g.previousElementSibling.classList &&
          g.previousElementSibling.classList.contains('ctl-fold__sum'))) cands.push(g);
    });
    var outer = cands.filter(function (g) {
      return !cands.some(function (o) { return o !== g && o.contains(g); });
    });
    var work = [];
    outer.forEach(function (grp) {
      var btns = btnsOf(grp);
      var sum = grp.previousElementSibling;
      var made = sum && sum.classList && sum.classList.contains('ctl-fold__sum') ? sum : null;
      if (!narrow || !btns.some(isActive)) {         // 넓어졌거나 선택지 묶음이 아니다
        if (made) work.push({ grp: grp, made: made, op: 'undo' });
        return;
      }
      var label = labelOf(btns);
      if (made) {
        var now = made.querySelector('.ctl-fold__now');
        if (now && now.textContent !== label) work.push({ made: made, label: label, op: 'relabel' });
        return;
      }
      work.push({ grp: grp, btns: btns, label: label, op: 'fold' });
    });
    if (!work.length) return;

    window._foldBusy = true;
    work.forEach(function (w) {
      if (w.op === 'undo') {
        w.made.remove(); w.grp.hidden = false; w.grp.classList.remove('ctl-fold__body');
        return;
      }
      if (w.op === 'relabel') { w.made.querySelector('.ctl-fold__now').textContent = w.label; return; }
      var grp = w.grp;
      // 안쪽에 먼저 접힌 줄이 남아 있으면 지운다 — 바깥이 나중에 자격을 얻는 순서
      // (차트가 그려지며 active 가 붙는다)에서 이중 접기가 생긴다.
      grp.querySelectorAll('.ctl-fold__sum').forEach(function (o) {
        var body = o.nextElementSibling;
        if (body && body.classList.contains('ctl-fold__body')) {
          body.hidden = false; body.classList.remove('ctl-fold__body');
        }
        o.remove();
      });
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ctl-fold__sum btn-plain';
      b.setAttribute('aria-expanded', 'false');
      // 낭독기에는 값만 읽히면 무엇의 요약인지 알 수 없다 — 이름을 따로 준다.
      b.setAttribute('aria-label', '컨트롤 펼치기 — 현재 ' + (w.label || '선택 없음'));
      grp.id = grp.id || ('ctlfold-' + Math.random().toString(36).slice(2, 8));
      b.setAttribute('aria-controls', grp.id);
      b.innerHTML = '<span class="ctl-fold__now"></span><span aria-hidden="true">▾</span>';
      b.querySelector('.ctl-fold__now').textContent = w.label;
      b.addEventListener('click', function () {
        var open = grp.hidden;
        window._foldBusy = true;
        grp.hidden = !open;
        b.setAttribute('aria-expanded', String(open));
        // 접는 순간 라벨을 다시 계산한다 — 펼친 채 다른 값을 고르면 핸들러가
        // class/style 만 바꾸는 경우가 많아 관찰자(childList)가 깨지 않는다.
        if (!open) {
          var nl = labelOf(Array.prototype.filter.call(grp.children, function (c) {
            if (c.classList && c.classList.contains('ctl-fold__sum')) return false;
            return c.tagName === 'BUTTON' || c.getAttribute('role') === 'tab';
          }));
          var now = b.querySelector('.ctl-fold__now');
          if (now.textContent !== nl) now.textContent = nl;
          b.setAttribute('aria-label', '컨트롤 펼치기 — 현재 ' + (nl || '선택 없음'));
        }
        setTimeout(function () { window._foldBusy = false; }, 0);
      });
      grp.classList.add('ctl-fold__body');
      grp.hidden = true;
      grp.parentNode.insertBefore(b, grp);
    });
    setTimeout(function () { window._foldBusy = false; }, 0);
  } catch (_) { window._foldBusy = false; }
};

// 폭이 바뀌면 관찰자를 기다리지 않고 직접 되돌린다(가로 회전·창 확대).
if (window.matchMedia) {
  try {
    window.matchMedia('(max-width: 480px)').addEventListener('change', function () {
      try { econFoldControls(document.getElementById('mainContent')); } catch (_) {}
    });
  } catch (_) {}
}

window.econMakeTablesSortable = function (root) {
    try {
      (root || document).querySelectorAll('table').forEach(function (tb) {
        if (tb.dataset.econSort) return;
        var head = tb.tHead && tb.tHead.rows[0];
        var body = tb.tBodies && tb.tBodies[0];
        if (!head || !body || body.rows.length < 4) return;
        if (head.querySelector('[colspan]') || body.querySelector('[colspan]')) return;
        tb.dataset.econSort = '1';
        Array.prototype.forEach.call(head.cells, function (th, idx) {
          th.setAttribute('aria-sort', 'none');
          th.tabIndex = 0;
          var run = function () {
            var dir = th.getAttribute('aria-sort') === 'ascending' ? -1 : 1;
            Array.prototype.forEach.call(head.cells, function (o) { o.setAttribute('aria-sort', 'none'); });
            th.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');
            var rows = Array.prototype.slice.call(body.rows);
            rows.sort(function (a, b) {
              var ca = a.cells[idx], cb = b.cells[idx];
              if (!ca || !cb) return 0;
              var na = cellNum(ca), nb = cellNum(cb);
              if (na != null && nb != null) return (na - nb) * dir;
              return String(ca.textContent).localeCompare(String(cb.textContent), 'ko') * dir;
            });
            rows.forEach(function (r) { body.appendChild(r); });
          };
          th.addEventListener('click', run);
          th.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); run(); }
          });
        });
      });
    } catch (_) {}
  };
})();

// ═══ 값 갱신 하이라이트 (기획 2026-09-21 C3) ══════════════════════════════════
// 숫자가 **실제로 달라졌을 때만** 그 자리를 0.8초 빛낸다. 네이버가 값마다 붙이는
// highlight-fade-up/down 과 같은 장치이고, 우리는 측정 당시 값 갱신에 붙은 애니가 0건이었다.
//
// 주의 — 이 옵저버는 childList·characterData 만 본다. 하이라이트는 class 를 건드리므로
// (attributes) 스스로를 다시 깨우지 않는다. D1 의 자기 유발 루프를 되풀이하지 않기 위한 조건이다.
(function econFlashOnChange() {
  try {
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    // 값이 사는 자리만 — 표 전체를 대상으로 하면 정렬 한 번에 화면이 통째로 번쩍인다.
    var SEL = '.kpi-card .econ-stat__value, .econ-numcell, .econ-row__val, .ticker-item,'
            + ' #mainChartPriceVal, #mainChartChangeVal, .econ-stat__delta';
    var last = new WeakMap();
    var num = function (el) {
      var t = (el.textContent || '').replace(/[,\s]/g, '');
      var m = t.match(/-?\d+(\.\d+)?/);
      return m ? parseFloat(m[0]) : null;
    };
    var flash = function (el, up) {
      var cls = up ? 'econ-flash-up' : 'econ-flash-dn';
      el.classList.remove('econ-flash-up', 'econ-flash-dn');
      void el.offsetWidth;                       // 같은 값이 연속으로 와도 애니를 다시 튼다
      el.classList.add(cls);
      setTimeout(function () { el.classList.remove(cls); }, 850);
    };
    var scan = function (root) {
      var list = (root || document).querySelectorAll(SEL);
      Array.prototype.forEach.call(list, function (el) {
        var v = num(el);
        if (v === null) return;
        var prev = last.get(el);
        last.set(el, v);
        if (prev === undefined || prev === v) return;
        flash(el, v > prev);
      });
    };
    var pending = null;
    var mo = new MutationObserver(function () {
      if (pending) return;
      pending = setTimeout(function () { pending = null; scan(document); }, 120);
    });
    var start = function () {
      scan(document);                            // 첫 값을 기준으로 삼는다(첫 렌더는 빛나지 않는다)
      mo.observe(document.body, { childList: true, subtree: true, characterData: true });
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
  } catch (_) {}
})();

// ═══ 끝내 오지 않는 차트 자리 (기획 2026-09-21 C3) ═════════════════════════════
// 차트 스켈레톤(canvas:not([width]))은 그려지는 순간 저절로 풀린다. 문제는 영영 안 오는 경우 —
// 그 자리는 계속 반짝이기만 한다. 화면에 들어온 canvas 만 지켜보다가 8초가 지나도 비어 있으면
// 반짝임을 멈추고 무슨 일이 났는지 적는다. '다시 시도'는 그 위젯이 이미 가진 새로고침 버튼을 누른다.
(function econChartTimeout() {
  try {
    var WAIT = 8000;
    var seen = new WeakSet();
    var mark = function (cv) {
      if (cv.getAttribute('width') || !cv.isConnected) return;     // 그 사이 그려졌다
      var box = cv.getBoundingClientRect();
      if (box.width < 40 || box.height < 24) return;               // 스파크라인 같은 작은 자리는 제외
      var host = cv.parentElement;
      if (!host || host.querySelector('.econ-failed')) return;
      var note = document.createElement('div');
      note.className = 'econ-failed';
      note.setAttribute('role', 'status');
      var msg = document.createElement('span');
      msg.textContent = '차트를 불러오지 못했습니다.';
      note.appendChild(msg);
      var widget = cv.closest('.widget');
      var refresh = widget && widget.querySelector('[aria-label*="새로고침"], [title*="새로고침"]');
      // 위젯 새로고침이 없으면(6차 D2 이후 전용 핸들러 있는 위젯만 가진다) 전체 새로고침으로 다시 시도.
      if (!refresh && typeof window.refreshAllData === 'function') refresh = { click: function () { window.refreshAllData(); } };
      if (refresh) {
        var again = document.createElement('button');
        again.type = 'button';
        again.className = 'btn-plain econ-failed__act';
        again.textContent = '다시 시도';
        again.addEventListener('click', function () {
          note.remove();
          try { refresh.click(); } catch (_) {}
        });
        note.appendChild(again);
      }
      cv.classList.add('econ-await-off');                          // 반짝임만 끈다(자리는 유지)
      host.appendChild(note);
    };
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting || seen.has(e.target)) return;
        seen.add(e.target);
        var cv = e.target;
        setTimeout(function () { try { mark(cv); } catch (_) {} }, WAIT);
      });
    }, { rootMargin: '0px' });
    var watch = function () {
      document.querySelectorAll('canvas:not([width])').forEach(function (cv) {
        if (!seen.has(cv)) io.observe(cv);
      });
    };
    var start = function () {
      watch();
      // 화면을 옮기거나 위젯을 펼치면 새 canvas 가 생긴다 — 그때마다 감시 목록을 넓힌다.
      var pending = null;
      new MutationObserver(function () {
        if (pending) return;
        pending = setTimeout(function () { pending = null; watch(); }, 500);
      }).observe(document.body, { childList: true, subtree: true });
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
  } catch (_) {}
})();
