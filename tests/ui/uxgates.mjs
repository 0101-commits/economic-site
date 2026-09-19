// UX 게이트 G7~G9 · M8 — 2026-09-19 가독성/UX 개편(기획안 spec 2026-09-19)의 통과선.
// readability.mjs(G1~G6, 1440)·mobile-readability.mjs(M1~M7, 390) 와 겹치지 않는 축만 잰다.
//
//   G7  토큰을 거치지 않은 글자색 0      — 브라우저 기본 링크색·차트 계열색을 글자에 쓴 자리
//   G8  데이터 위젯 as-of 각인 100%      — 화면 표기는 "정상이면 침묵", 확인 수단은 항상
//   G9  화면수 1440 ≤5.5 · 390 ≤4.0     — 벤치마크 실측(Npay PC 홈 5.6 · 토스 홈 5.7 · 390 기준 4.0)
//   M8  첫 데이터까지 420px 이내(양쪽)  — 첫 화면의 절반. 벤치 네이버 m 142 · PC 145 · 토스 157
//
// usage: node tests/ui/uxgates.mjs [--page=a,b] [--base=http://127.0.0.1:8080/index.html]
import { chromium } from 'playwright';

const arg = (k, d) => {
  const hit = process.argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};
const BASE = arg('base', 'http://127.0.0.1:8080/index.html');
const PAGES = arg('page', 'dashboard,equity,market,macro,calendar,realestate,investor,notes,study,merlens')
  .split(',').map(s => s.trim()).filter(Boolean);

const LIMITS = {
  screensDesktop: 5.5,
  screensMobile: 4.0,
  // 첫 화면의 절반 안에 첫 숫자가 들어온다 — 1440(900)·390(844) 모두 420px.
  // 벤치(네이버 m 142 · PC 145 · 토스 157)보다 느슨한 이유: 우리 화면은 페이지 목차와
  // 탭 셸을 머리에 둔다(벤치는 전역 GNB 하나로 끝낸다). 그 층을 없애는 것은 IA 결정이라
  // 이 게이트의 범위가 아니다 — 여기서는 "첫 화면에 숫자가 있다"를 지킨다.
  firstDataDesktop: 420,
  firstDataMobile: 420,
  rawColors: 0,
};

// 토큰을 거치지 않은 색 — 브라우저 기본 링크색과 차트 계열색 리터럴.
// (인라인 color 전체는 900~1,150곳이라 2차 과제다. 여기서는 '틀린 색'만 센다.)
const RAW = ['rgb(0, 0, 238)', 'rgb(0, 0, 255)', 'rgb(85, 26, 139)',   // 브라우저 기본 링크색
             'rgb(182, 196, 255)', 'rgb(126, 138, 255)',               // 차트 계열색을 글자에 쓴 자리
             'rgb(185, 28, 28)', 'rgb(15, 110, 86)',                   // 설명 모달의 위험/탐욕 하드코딩
             'rgb(155, 89, 182)', 'rgb(133, 79, 11)',                  // PCR 보라 · 카테고리 갈색
             'rgb(107, 114, 128)', 'rgb(239, 83, 80)'];                // 캡션 회색 · 오류 빨강

const MEASURE = (rawList) => {
  const vis = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && +s.opacity > 0.05;
  };
  const active = document.querySelector('.page.active') || document.body;

  // G7
  const raw = [];
  active.querySelectorAll('*').forEach(el => {
    if (!vis(el) || el.childElementCount || !el.textContent.trim()) return;
    const c = getComputedStyle(el).color;
    if (rawList.indexOf(c) >= 0) {
      raw.push(c + ' — ' + el.textContent.replace(/\s+/g, ' ').trim().slice(0, 24));
    }
  });

  // G8
  const dataWidgets = [...active.querySelectorAll('.widget')]
    .filter(w => w.querySelector('.econ-table, canvas, .econ-stat, .kpi-card, .econ-data') && w.offsetHeight > 40);
  const titled = dataWidgets.filter(w => w.querySelector('.widget-title'));
  const stamped = titled.filter(w => (w.querySelector('.widget-title').dataset.asof || '') !== '');
  const mkt = document.getElementById('mktStatus');

  // G9 · M8
  const y = e => Math.round(e.getBoundingClientRect().top + window.scrollY);
  const dataEls = [...active.querySelectorAll('canvas,table,.econ-row,svg,.kpi-card,.econ-stat,.econ-num,.econ-data')]
    .filter(vis).map(y);

  return {
    rawColors: raw.length, rawWorst: raw.slice(0, 5),
    dataWidgets: dataWidgets.length, titled: titled.length, stamped: stamped.length,
    asofMissing: titled.filter(w => !(w.querySelector('.widget-title').dataset.asof || ''))
      .map(w => w.querySelector('.widget-title').textContent.trim().slice(0, 18)).slice(0, 4),
    marketBadge: mkt && !mkt.hidden ? (mkt.textContent || '').trim() : null,
    docH: document.documentElement.scrollHeight,
    screens: +(document.documentElement.scrollHeight / window.innerHeight).toFixed(2),
    firstData: dataEls.length ? Math.min(...dataEls) : null,
  };
};

const browser = await chromium.launch();
let failed = 0;

for (const [view, w, h] of [['1440', 1440, 900], ['390', 390, 844]]) {
  const ctx = await browser.newContext({
    viewport: { width: w, height: h }, locale: 'ko-KR', timezoneId: 'Asia/Seoul',
    isMobile: w === 390, hasTouch: w === 390,
  });
  await ctx.addInitScript(() => {
    try {
      localStorage.setItem('econ_theme', 'light');
      localStorage.setItem('econ_color_conv', 'kr');
      sessionStorage.setItem('econLockOk_v1', '1');
    } catch (_) { }
  });
  const page = await ctx.newPage();
  for (const p of PAGES) {
    await page.goto(`${BASE}?p=${p}`, { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => { });
    await page.waitForTimeout(5200);
    const r = await page.evaluate(MEASURE, RAW);
    const bad = [];
    if (r.rawColors > LIMITS.rawColors) bad.push(`G7 토큰 우회 색 ${r.rawColors}곳 (${r.rawWorst[0] || ''})`);
    if (r.titled && r.stamped < r.titled) bad.push(`G8 as-of 누락 ${r.titled - r.stamped}곳 (${r.asofMissing.join(' / ')})`);
    if (view === '1440' && !r.marketBadge) bad.push('G8 시장 상태 배지 없음');
    const capS = view === '1440' ? LIMITS.screensDesktop : LIMITS.screensMobile;
    if (r.screens > capS) bad.push(`G9 화면수 ${r.screens} (상한 ${capS})`);
    const capF = view === '1440' ? LIMITS.firstDataDesktop : LIMITS.firstDataMobile;
    if (r.firstData != null && r.firstData > capF) bad.push(`M8 첫 데이터 ${r.firstData}px (상한 ${capF})`);
    if (bad.length) failed++;
    console.log(`${bad.length ? '[FAIL]' : '[PASS]'} ${view.padEnd(5)} ${p.padEnd(11)} ` +
      `화면 ${String(r.screens).padEnd(5)} 첫데이터 ${String(r.firstData ?? '—').padEnd(5)} ` +
      `as-of ${r.stamped}/${r.titled} 우회색 ${r.rawColors}` +
      (bad.length ? '\n        → ' + bad.join(' · ') : ''));
  }
  await ctx.close();
}
await browser.close();
console.log(failed ? `\nFAIL — ${failed}건` : '\nPASS — UX 게이트(G7~G9·M8) 통과');
process.exit(failed ? 1 : 0);
