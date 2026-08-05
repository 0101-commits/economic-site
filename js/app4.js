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
    b.style.color = on ? '#fff' : '#8d90a2';
  });
  var st = document.querySelector('input[name="setPfStyle"][value="' + (s.chart.pfStyle || 'candle') + '"]');
  if (st) st.checked = true;
  var cc = window.econColorConv || 'kr';
  var ccEl = document.querySelector('input[name="setColorConv"][value="' + cc + '"]');
  if (ccEl) ccEl.checked = true;
  var sk = 'neutral';
  try { sk = localStorage.getItem('econ_skin') || 'neutral'; } catch (_) {}
  var skEl = document.querySelector('input[name="setSkin"][value="' + sk + '"]');
  if (skEl) skEl.checked = true;
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
  if (v === (window.econColorConv || 'kr')) return;
  try { localStorage.setItem('econ_color_conv', v); } catch (_) {}
  try { if (typeof showToast === 'function') showToast('색상 방향 적용 중… 새로고침', 'ok'); } catch (_) {}
  setTimeout(function () { location.reload(); }, 400);
};
window.settingsSetSkin = function (v) {
  // 화면 스킨(색감 프리셋) — 토큰 오버라이드 레이어(index.html skin presets)를 켠다.
  // 색상 방향(settingsSetColorConv)과 달리 reload 불필요: 스킨은 CUP/CDN(등락색)을 안
  // 건드리므로 테마 토글과 같은 rebuildChartsForTheme 경로로 차트만 다시 칠하면 된다.
  v = (v === 'navy' || v === 'contrast') ? v : 'neutral';
  try { localStorage.setItem('econ_skin', v); } catch (_) {}
  if (v === 'neutral') delete document.documentElement.dataset.skin;
  else document.documentElement.dataset.skin = v;
  try { rebuildChartsForTheme(); } catch (_) {}
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
    b.style.color = on ? '#fff' : '#8d90a2';
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
  div.innerHTML = '<span>💡</span><span>' + html + '</span><span class="guide-x" onclick="dismissGuide(\'' + key + '\',this)" title="다시 보지 않기">✕</span>';
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
window.econPageHook = function (id) {
  // 페이지별 init 이 setTimeout(…, 50) 으로 늦게 도는 구조 → 한 박자(400ms) 뒤 실행
  setTimeout(function () {
    try { _applyDefaultPresetsForActivePage(); } catch (_) {}
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
  var btn = opts.retry ? '<button onclick="' + String(opts.retry).replace(/"/g, '&quot;') + '">↻ 재시도</button>' : '';
  var block = '<div class="widget-err"><div>⚠ ' + _escT6(opts.title || '데이터를 불러오지 못했습니다') + '</div>' +
              (opts.detail ? '<div style="font-size:var(--font-size-xs);max-width:92%;">' + _escT6(String(opts.detail).slice(0, 160)) + '</div>' : '') +
              btn + '</div>';
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
    '<button onclick="retryLoadRealData(this)" style="font-size:var(--font-size-sm);padding:2px 10px;border:1px solid var(--c-warn);border-radius:var(--r-xs);background:transparent;color:var(--c-warn);cursor:pointer;">↻ 재시도</button>' +
    '<span style="cursor:pointer;font-weight:var(--font-weight-bold);padding:0 2px;" onclick="this.parentNode.remove()" title="닫기">✕</span>';
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
    if (btn) { btn.disabled = false; btn.textContent = '↻ 재시도'; }
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
      '<div class="pf-card-head" onclick="pfOpenChart(\'' + it.id + '\')">' +
        '<span><span class="pf-card-name">' + pfEsc(it.name || it.symbol) + '</span><span class="pf-card-sym">' + pfEsc(it.symbol) + '</span></span>' +
        '<span style="text-align:right;"><span style="font-family:\'Public Sans\';color:var(--c-txt);font-size:var(--font-size-base);">' + (q ? pfFmtPrice(q.price, q.ccy) : '로딩…') + '</span><br>' + (q ? pfChgHtml(q.pct) : '-') + '</span>' +
      '</div>' +
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
    var _VALID = ['dashboard','portfolio','equity','macro','market','investor','realestate','calendar','study','notes','merblog','settings'];
    var p = new URLSearchParams(location.search).get('p');
    if(p && _VALID.indexOf(p) >= 0 && p !== 'dashboard') {
      var mEl = Array.from(document.querySelectorAll('.menu-item')).find(function(m) {
        return (m.getAttribute('onclick') || '').indexOf("'" + p + "'") >= 0;
      });
      showPage(p, mEl || null);
    }
    window.addEventListener('popstate', function() {
      try {
        var pg = new URLSearchParams(location.search).get('p') || 'dashboard';
        if(_VALID.indexOf(pg) >= 0) {
          var el = Array.from(document.querySelectorAll('.menu-item')).find(function(m) {
            return (m.getAttribute('onclick') || '').indexOf("'" + pg + "'") >= 0;
          });
          showPage(pg, el || null);
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
  var PAGE_MAP = {'1':'dashboard','2':'portfolio','3':'equity','4':'macro','5':'market','6':'investor','7':'realestate','8':'calendar','9':'notes','0':'settings','s':'study','S':'study'};
  var id = PAGE_MAP[e.key];
  if(id) {
    e.preventDefault();
    var menuEl = Array.from(document.querySelectorAll('.menu-item')).find(function(m) {
      return (m.getAttribute('onclick') || '').indexOf("'" + id + "'") >= 0;
    });
    showPage(id, menuEl || null);
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
