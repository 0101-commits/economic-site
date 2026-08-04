/* ═══ [3차-T28] 시스템 진단 — 링크·라우팅·데이터 정확성 자가 점검 ═════════════
   설계: 브라우저에서 확정 판정 가능한 것은 즉시 검사하고, CORS 로 판정 불가한
   외부 링크 상태는 CI 산출물 link_status.json(T29~T30)을 읽어 표시한다.
   시계열 정합성 규칙은 scripts/validate_data.py(T31)와 동일 기준을 사용한다. */
(function () {
'use strict';
function _esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
function _row(level, title, detail) {
  var ic = { ok: '✅', warn: '⚠️', err: '❌', info: 'ℹ️' }[level] || 'ℹ️';
  return '<div class="diag-row"><span class="diag-ic">' + ic + '</span><span class="diag-t">' + _esc(title) + '</span><span class="diag-d">' + detail + '</span></div>';
}

window.runDiagnostics = async function () {
  var out = document.getElementById('diagResult');
  var btn = document.getElementById('diagRunBtn');
  if (!out) return;
  if (btn) { btn.disabled = true; btn.textContent = '진단 중…'; }
  out.innerHTML = '<div class="skel-bar" style="width:60%;"></div>';
  var rows = [];

  /* 1) 차트 라이브러리 로드 */
  rows.push(_row(typeof Chart !== 'undefined' ? 'ok' : 'err', '차트 라이브러리',
    'Chart.js ' + (typeof Chart !== 'undefined' ? _esc(Chart.version || '로드됨') : '미로드 — CDN 차단 여부 확인')));
  rows.push(_row(typeof LightweightCharts !== 'undefined' ? 'ok' : 'warn', '차트 라이브러리',
    'Lightweight Charts ' + (typeof LightweightCharts !== 'undefined' ? '로드됨' : '미로드 — 종목 상세 차트만 영향')));

  /* 2) 메뉴 라우팅 무결성 — 사이드바의 모든 showPage 대상 페이지 존재 확인 */
  try {
    var items = document.querySelectorAll('#sidebar .menu-item[onclick]');
    var missing = [];
    items.forEach(function (mi) {
      var m = (mi.getAttribute('onclick') || '').match(/showPage\('([^']+)'/);
      if (m && !document.getElementById('page-' + m[1])) missing.push(m[1]);
    });
    rows.push(missing.length
      ? _row('err', '메뉴 라우팅', '대상 페이지 누락: ' + _esc(missing.join(', ')))
      : _row('ok', '메뉴 라우팅', items.length + '개 메뉴 → 페이지 매핑 정상'));
  } catch (e) { rows.push(_row('err', '메뉴 라우팅', '검사 실패: ' + _esc(e.message))); }

  /* 3) 클릭 핸들러 무결성 — onclick 이 참조하는 전역 함수의 정의 여부 (깨진 버튼 사전 탐지) */
  try {
    var fns = {};
    var _kw = { 'if': 1, 'for': 1, 'while': 1, 'switch': 1, 'return': 1, 'typeof': 1, 'void': 1, 'new': 1 };
    document.querySelectorAll('[onclick]').forEach(function (el) {
      var m = (el.getAttribute('onclick') || '').match(/^\s*(?:window\.)?([A-Za-z_$][\w$]*)\s*\(/);
      if (m && !_kw[m[1]]) fns[m[1]] = 1;   // 'if(event.target===this)…' 류 인라인 구문은 함수 참조가 아님
    });
    var names = Object.keys(fns);
    var broken = names.filter(function (f) { return typeof window[f] !== 'function'; });
    rows.push(broken.length
      ? _row('err', '클릭 핸들러', '미정의 함수 ' + broken.length + '개: ' + _esc(broken.slice(0, 10).join(', ')))
      : _row('ok', '클릭 핸들러', names.length + '개 참조 함수 모두 정의됨'));
  } catch (e) { rows.push(_row('err', '클릭 핸들러', '검사 실패: ' + _esc(e.message))); }

  /* 4) 데이터 신선도 — data_meta.json(약 70B 경량 프로브) 기준.
        수집 워크플로가 장중 10분 주기이므로 2시간 내=정상, 26시간 내=주의, 초과=오류 */
  var meta = null;
  try {
    meta = await (await fetch('./data_meta.json?t=' + Date.now(), { cache: 'no-store' })).json();
    var ageH = (Date.now() - new Date(meta.lastUpdated).getTime()) / 36e5;
    var lvl = ageH < 2 ? 'ok' : ageH < 26 ? 'warn' : 'err';
    rows.push(_row(lvl, '데이터 신선도', '서버 data.json 생성 ' + ageH.toFixed(1) + '시간 전 (' + _esc(new Date(meta.lastUpdated).toLocaleString('ko-KR')) + ')' + (lvl !== 'ok' ? ' — 수집 워크플로(fetch-data) 실행 상태 확인 권장' : '')));
  } catch (_) {
    rows.push(_row('err', '데이터 신선도', 'data_meta.json 조회 실패 — Mock 모드이거나 네트워크/배포 문제'));
  }
  if (meta) {
    if (window._lastRealDataTs && window._lastRealDataTs === meta.lastUpdated)
      rows.push(_row('ok', '화면 데이터', '화면에 로드된 데이터 = 서버 최신본 일치'));
    else if (window._lastRealDataTs)
      rows.push(_row('warn', '화면 데이터', '화면 데이터가 서버 최신본과 다릅니다 — 새로고침(↻) 권장'));
    else
      rows.push(_row('warn', '화면 데이터', '실데이터 미로드 — 예시(Mock) 데이터 표시 중'));
  }

  /* 5) 수집 파이프라인 상태 — fetch_data.py 가 data.json 에 기록한 diagnostics 키 노출 */
  try {
    var d = (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators) ? _latestDataForIndicators : null;
    var dg = d && d.diagnostics;
    if (dg) {
      var notes = [];
      if (dg.pykrxAvailable === false) notes.push('pykrx 사용 불가 — 국내 시세가 폴백 소스로 수집됨');
      if (dg.krxLoginAvailable === false) notes.push('KRX 로그인 미설정 — 투자자별 매매동향이 제한될 수 있음');
      if (dg.realestate_kr && dg.realestate_kr.rone_ok === false) notes.push('R-ONE(부동산 통계) 수집 실패');
      rows.push(_row(notes.length ? 'warn' : 'ok', '수집 파이프라인',
        notes.length ? _esc(notes.join(' · ')) : '주요 수집 소스 정상 (KRX·부동산·청약 OK)'));
    } else {
      rows.push(_row('info', '수집 파이프라인', '진단 정보 없음 — 실데이터 로드 후 다시 실행'));
    }
  } catch (_) {}

  /* 6) 핵심 시계열 정합성 — 신선도·결측·급변·절대 범위 (validate_data.py 와 동일 규칙) */
  try {
    var d2 = (typeof _latestDataForIndicators !== 'undefined' && _latestDataForIndicators) ? _latestDataForIndicators : null;
    if (!d2) {
      rows.push(_row('warn', '시계열 정합성', '실데이터 미로드 — 검사 생략'));
    } else {
      var issues = [];
      var checkSeries = function (label, seq, maxStaleDays, jumpPct) {
        if (!Array.isArray(seq) || !seq.length) { issues.push(label + ': 시계열 없음'); return; }
        var last = seq[seq.length - 1] || {};
        var staleD = (Date.now() - new Date(last.date).getTime()) / 864e5;
        if (isFinite(staleD) && staleD > maxStaleDays) issues.push(label + ': 마지막 데이터 ' + Math.floor(staleD) + '일 전(' + _esc(last.date) + ')');
        var closes = seq.slice(-10).map(function (p) { return p && p.close; }).filter(function (v) { return typeof v === 'number' && isFinite(v); });
        for (var i = 1; i < closes.length; i++) {
          var chg = Math.abs(closes[i] / closes[i - 1] - 1) * 100;
          if (chg > jumpPct) { issues.push(label + ': 일간 ' + chg.toFixed(1) + '% 급변 — 수집 오류 의심'); break; }
        }
        var nulls = seq.slice(-30).filter(function (p) { return !(p && typeof p.close === 'number' && isFinite(p.close)); }).length;
        if (nulls) issues.push(label + ': 최근 30포인트 중 결측 ' + nulls + '건');
      };
      var hist = d2.history || {};
      checkSeries('KOSPI', (hist.indices || {}).KOSPI, 5, 12);
      checkSeries('S&P500', (hist.indices || {}).SP500, 5, 12);
      checkSeries('USD/KRW', (hist.fx || {}).USDKRW, 5, 6);
      var rate = ((d2.fx || {}).USDKRW || {}).rate;
      if (typeof rate === 'number' && !(rate >= 800 && rate <= 2500)) issues.push('USD/KRW 현재가 ' + rate + ' — 정상 범위(800~2,500) 이탈(단위 오류 의심)');
      /* 신선도 계약 위반 목록 — 서버(scripts/data_sla.py)가 판정한 결과를 그대로 읽는다.
         브라우저에서 재판정하지 않는 이유: 기준이 두 벌이 되면 반드시 어긋난다. */
      var _h = d2.dataHealth;
      if (_h && _h.items) {
        var bad = _h.items.filter(function (i) { return i.state === 'stale' || i.state === 'failed' || i.state === 'missing'; });
        bad.slice(0, 25).forEach(function (i) {
          issues.push((i.state === 'failed' ? '수집 실패' : i.state === 'missing' ? '데이터 없음(키 실종)' : '갱신 지연') + ': ' + i.path +
            (i.state === 'missing' ? '' :
             ' (기준일 ' + (i.asOf || '알 수 없음') + ', ' + i.ageDays + '일 경과 / 허용 ' + i.sla + '일)'));
        });
        if (bad.length > 25) issues.push('… 외 ' + (bad.length - 25) + '건');
      }
      rows.push(issues.length
        ? _row('warn', '시계열 정합성', _esc(issues.join(' · ')))
        : _row('ok', '시계열 정합성', 'KOSPI·S&P500·USD/KRW — 신선도/결측/급변/범위 이상 없음'));
    }
  } catch (e) { rows.push(_row('err', '시계열 정합성', '검사 실패: ' + _esc(e.message))); }

  /* 7) 알림 서버(Worker) 도달 — 응답 자체(HTTP 상태)만 확인. [이슈1] GET /portfolio 는 이제 인증 필요라
        keyHash 없이 호출하면 401 이 정상(도달 확인엔 충분 — 5xx 만 오류로 본다). */
  try {
    var base = (typeof _cfProxyBase === 'function') ? _cfProxyBase() : '';
    if (!base) rows.push(_row('warn', '알림 서버', 'Worker 프록시 미설정'));
    else {
      var wr = await fetch(base + '/portfolio', { signal: AbortSignal.timeout(8000) });
      rows.push(_row(wr.status < 500 ? 'ok' : 'warn', '알림 서버',
        _esc(base.replace(/^https?:\/\//, '')) + ' 응답 HTTP ' + wr.status + (wr.status < 500 ? ' — 도달 정상' : ' — 서버 오류')));
    }
  } catch (_) { rows.push(_row('err', '알림 서버', 'Worker 도달 실패 — 네트워크/배포 상태 확인')); }

  /* 8) 외부 링크 상태 — CI 주간 점검 결과(link_status.json) 표시. 없으면 인벤토리만.
        (브라우저 직접 검사는 CORS 의 opaque 응답으로 상태코드 판정이 불가능 — §0.3 #3) */
  try {
    var links = [];
    document.querySelectorAll('a[href^="http"]').forEach(function (a) { links.push(a.href); });
    var uniq = links.filter(function (v, i) { return links.indexOf(v) === i; });
    var st = null;
    try { st = await (await fetch('./link_status.json?t=' + Date.now(), { cache: 'no-store' })).json(); } catch (_) {}
    if (st && Array.isArray(st.results)) {
      var bad = st.results.filter(function (r) { return r.status === 'broken'; });
      var man = st.results.filter(function (r) { return r.status === 'manual'; });
      rows.push(_row(bad.length ? 'err' : 'ok', '외부 링크',
        '검사 ' + st.results.length + '개 — 정상 ' + (st.results.length - bad.length - man.length) + ' · 수동확인 ' + man.length + ' · 끊김 ' + bad.length +
        ' <span style="color:var(--c-txt-muted);">(점검일 ' + _esc(String(st.checkedAt || '').slice(0, 10)) + ', 주 1회 자동)</span>'));
      bad.slice(0, 6).forEach(function (b) { rows.push(_row('err', '· 끊긴 링크', _esc(b.url) + ' → ' + _esc(b.code) + ' (링크 교체 필요)')); });
      man.slice(0, 4).forEach(function (b) { rows.push(_row('warn', '· 수동 확인', _esc(b.url) + ' → ' + _esc(b.code) + ' (봇 차단/일시 장애 가능 — 브라우저로 직접 확인)')); });
    } else {
      rows.push(_row('info', '외부 링크', '본문 링크 ' + uniq.length + '개 발견 — 상태 파일(link_status.json) 없음. 링크 점검 워크플로(Actions → Link Check)를 1회 수동 실행하면 이후 자동 표시됩니다.'));
    }
  } catch (e) { rows.push(_row('err', '외부 링크', '검사 실패: ' + _esc(e.message))); }

  out.innerHTML = rows.join('');
  if (btn) { btn.disabled = false; btn.textContent = '▶ 진단 실행'; }
};
})();
