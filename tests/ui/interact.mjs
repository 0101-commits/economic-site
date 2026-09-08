// SEED 개편 상호작용 게이트 — 스크린샷이 못 잡는 '동작'을 검사한다.
//
// 왜: 내비게이션이 <a href="?p=…"> 로 바뀌면서 "클릭 시 전체 재로드"라는 조용한
// 회귀가 가능해졌고, 드로어·레일·그룹 기억은 정적 샷으로 확인할 수 없다.
//
// 실행:  node tests/ui/interact.mjs [--url=http://127.0.0.1:8080]
import { chromium } from 'playwright';

const arg = (k, d) => (process.argv.find(a => a.startsWith(`--${k}=`)) || `=${d}`).split('=').slice(1).join('=');
const BASE = arg('url', 'http://127.0.0.1:8080');

const fails = [];
const ok = (cond, msg) => { if (!cond) fails.push(msg); };
const browser = await chromium.launch();

async function open(width, height = 900) {
  const ctx = await browser.newContext({ viewport: { width, height } });
  await ctx.addInitScript(() => { try { localStorage.setItem('econ_theme', 'dark'); } catch (_) {} });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e).slice(0, 160)));
  await page.goto(`${BASE}/index.html?p=dashboard`, { waitUntil: 'load', timeout: 60000 });
  await page.waitForTimeout(1200);
  // 전체 재로드 감지용 표식 — 살아 있으면 SPA 전환, 사라지면 문서가 다시 로드됐다
  await page.evaluate(() => { window.__spaMarker = 1; });
  return { ctx, page, errors };
}
const activePage = page => page.evaluate(() => (document.querySelector('.page.active') || {}).id || '');
const spaAlive = page => page.evaluate(() => window.__spaMarker === 1);

// ── 1) 데스크톱(1440): 사이드바 항목 클릭 = SPA 전환 + data-current 이동 ─────
{
  const { ctx, page, errors } = await open(1440);
  await page.click('#sidebar [data-nav="realestate"]');
  await page.waitForTimeout(600);
  ok(await spaAlive(page), '1440: 사이드바 클릭이 전체 재로드를 일으켰다(<a> 기본동작 미차단)');
  ok((await activePage(page)) === 'page-realestate', '1440: 부동산 페이지로 전환되지 않았다');
  const st = await page.evaluate(() => {
    const cur = document.querySelectorAll('#sidebar [data-nav][data-current]');
    const a = document.querySelector('#sidebar [data-nav="realestate"]');
    return {
      count: cur.length,
      isRe: cur.length === 1 && cur[0].getAttribute('data-nav') === 'realestate',
      aria: a && a.getAttribute('aria-current'),
      parts: a ? a.querySelectorAll('[data-current]').length : 0,
      url: location.search,
    };
  });
  ok(st.isRe, `1440: data-current 가 하나여야 하고 realestate 여야 한다 (count=${st.count})`);
  ok(st.aria === 'page', '1440: aria-current="page" 누락');
  ok(st.parts === 2, `1440: prefixIcon·label 의 data-current 2개가 아니다 (${st.parts})`);
  ok(st.url.includes('p=realestate'), `1440: URL 딥링크 미반영 (${st.url})`);
  ok(errors.length === 0, `1440: pageerror ${errors[0] || ''}`);
  await ctx.close();
}

// ── 2) 태블릿(1024): 아이콘 레일 + 햄버거로 펼침 ─────────────────────────────
{
  const { ctx, page, errors } = await open(1024);
  const railed = await page.evaluate(() =>
    document.getElementById('sidebar').getAttribute('data-side-navigation-state') === 'collapsed'
    && document.querySelectorAll('#sidebar [data-side-navigation-state="collapsed"]').length > 10);
  ok(railed, '1024: 768~1279 구간에서 아이콘 레일(collapsed)이 아니다');
  await page.click('button[onclick="toggleSidebar()"]');
  await page.waitForTimeout(400);
  const expanded = await page.evaluate(() =>
    !document.getElementById('sidebar').hasAttribute('data-side-navigation-state'));
  ok(expanded, '1024: 햄버거로 펼쳐지지 않는다');
  ok(errors.length === 0, `1024: pageerror ${errors[0] || ''}`);
  await ctx.close();
}

// ── 3) 모바일(390): 바텀내비 · 드로어 · Esc · 그룹 기억 ─────────────────────
{
  const { ctx, page, errors } = await open(390, 844);
  const navVisible = await page.evaluate(() => {
    const n = document.getElementById('econBottomNav');
    return !!n && getComputedStyle(n).display !== 'none';
  });
  ok(navVisible, '390: 바텀 내비가 보이지 않는다');
  const homeCurrent = await page.evaluate(() =>
    !!document.querySelector('#econBottomNav [data-navgroup="home"][data-current]'));
  ok(homeCurrent, '390: 최초 진입에서 홈 탭이 활성 표시되지 않는다');

  // 시장 탭 → 그룹 기본값(equity)
  await page.click('#econBottomNav [data-navgroup="market"]');
  await page.waitForTimeout(700);
  ok(await spaAlive(page), '390: 바텀내비 탭이 전체 재로드를 일으켰다');
  ok((await activePage(page)) === 'page-equity', '390: 시장 탭이 주식시장으로 가지 않는다');

  // 시장 그룹 안에서 시장지표로 이동 후, 홈 → 시장 탭 = 마지막 방문(market) 복귀
  // (모바일에서 사이드바는 닫힌 드로어이므로 먼저 열어야 클릭이 닿는다)
  await page.click('#econMoreTab');
  await page.waitForTimeout(300);
  await page.click('#sidebar [data-nav="market"]');
  await page.waitForTimeout(600);
  await page.click('#econBottomNav [data-navgroup="home"]');
  await page.waitForTimeout(500);
  await page.click('#econBottomNav [data-navgroup="market"]');
  await page.waitForTimeout(600);
  ok((await activePage(page)) === 'page-market',
     `390: 그룹 마지막 방문(econ_nav_last) 복귀 실패 (${await activePage(page)})`);

  // 드로어 — 더보기 → 열림, Esc → 닫힘
  await page.click('#econMoreTab');
  await page.waitForTimeout(400);
  let drawer = await page.evaluate(() => {
    const sb = document.getElementById('sidebar');
    return {
      open: sb.hasAttribute('data-drawer-open'),
      visible: getComputedStyle(sb).visibility === 'visible',
      backdrop: !document.getElementById('sidebarBackdrop').hidden,
      expanded: document.getElementById('econMoreTab').getAttribute('aria-expanded'),
    };
  });
  ok(drawer.open && drawer.visible, '390: 더보기로 드로어가 열리지 않는다');
  ok(drawer.backdrop, '390: 드로어 백드롭이 표시되지 않는다');
  ok(drawer.expanded === 'true', '390: 더보기 aria-expanded 미갱신');
  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);
  drawer = await page.evaluate(() => {
    const sb = document.getElementById('sidebar');
    return { open: sb.hasAttribute('data-drawer-open'), backdrop: !document.getElementById('sidebarBackdrop').hidden };
  });
  ok(!drawer.open, '390: Esc 로 드로어가 닫히지 않는다(econOverlay 미등록)');
  ok(!drawer.backdrop, '390: Esc 후 백드롭이 남아 배경 클릭을 막는다');

  // 드로어에서 항목을 고르면 닫혀야 한다
  await page.click('#econMoreTab');
  await page.waitForTimeout(300);
  await page.click('#sidebar [data-nav="notes"]');
  await page.waitForTimeout(600);
  const afterNav = await page.evaluate(() => ({
    open: document.getElementById('sidebar').hasAttribute('data-drawer-open'),
    page: (document.querySelector('.page.active') || {}).id,
  }));
  ok(!afterNav.open && afterNav.page === 'page-notes', '390: 드로어에서 이동 후 닫히지 않는다');
  ok(errors.length === 0, `390: pageerror ${errors[0] || ''}`);
  await ctx.close();
}

// ── 4) 티커 정지 버튼 · 테마 토글 두 속성 동기 ───────────────────────────────
{
  const { ctx, page, errors } = await open(1440);
  await page.click('#tickerPauseBtn');
  await page.waitForTimeout(200);
  const paused = await page.evaluate(() => ({
    motion: document.getElementById('econTicker').getAttribute('data-motion'),
    pressed: document.getElementById('tickerPauseBtn').getAttribute('aria-pressed'),
  }));
  ok(paused.motion === 'paused' && paused.pressed === 'true', '티커 정지 버튼이 상태를 세우지 않는다');

  await page.click('#themeToggleBtn');
  await page.waitForTimeout(400);
  const theme = await page.evaluate(() => ({
    light: document.documentElement.classList.contains('light'),
    mode: document.documentElement.dataset.seedColorMode,
    brand: getComputedStyle(document.documentElement).getPropertyValue('--seed-color-fg-brand').trim(),
  }));
  ok(theme.light && theme.mode === 'light-only',
     `테마 토글이 html.light 와 data-seed-color-mode 를 함께 세우지 않는다 (${theme.light}/${theme.mode})`);
  ok(/135fcd/i.test(theme.brand), `라이트 전환 후 brand 가 blue-800 이 아니다 (${theme.brand})`);
  ok(errors.length === 0, `테마/티커: pageerror ${errors[0] || ''}`);
  await ctx.close();
}

// ── 5) 설정 — 색상 관습 segmented 상태 ──────────────────────────────────────
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.addInitScript(() => { try { sessionStorage.setItem('econLockOk_v1', '1'); } catch (_) {} });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/index.html?p=settings`, { waitUntil: 'load', timeout: 60000 });
  await page.waitForTimeout(1800);
  const seg = await page.evaluate(() => {
    const root = document.getElementById('setColorConvGroup');
    if (!root) return null;
    return {
      checked: root.querySelectorAll('.seed-segmented-control__item[data-checked]').length,
      index: root.style.getPropertyValue('--segment-index'),
      indicator: !!root.querySelector('.seed-segmented-control__indicator'),
    };
  });
  ok(seg && seg.checked === 1 && seg.indicator,
     `설정: segmented 상태가 하나로 세워지지 않는다 (${JSON.stringify(seg)})`);
  await ctx.close();
}

await browser.close();
console.log(fails.length ? 'FAIL\n - ' + fails.join('\n - ') : 'PASS — 상호작용 게이트 통과');
process.exit(fails.length ? 1 : 0);
