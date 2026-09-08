// P4 근거 수집 — 전환기 셀렉터가 아직 실제로 매칭되는지 센다.
//
// 왜: astryx 레이어의 !important 규칙은 "인라인 스타일을 이기기 위해" 만들어졌다.
// 인라인을 걷어낸 뒤에도 규칙을 남기면 recipe 와 싸우고, 반대로 남은 요소가
// 있는데 지우면 그 화면만 스타일을 잃는다. 세어 보고 결정한다.
//
// 실행: node tests/ui/deadcss.mjs [--url=…]
import { chromium } from 'playwright';

const arg = (k, d) => (process.argv.find(a => a.startsWith(`--${k}=`)) || `=${d}`).split('=').slice(1).join('=');
const BASE = arg('url', 'http://127.0.0.1:8080');

const SELECTORS = [
  '.tab-btn:not([class*="seed-"])',
  '.preset-btn:not([class*="seed-"])',
  '.news-filter-btn:not([class*="seed-"])',
  '.invUnitBtn:not([class*="seed-"])',
  '.reHistPeriodBtn:not([class*="seed-"])',
  '.reHistUnitBtn:not([class*="seed-"])',
  '.yoy-btn:not([class*="seed-"])',
  '.brief-chip:not([class*="seed-"])',
  '.menu-item:not([class*="seed-"])',
  '.toast:not([class*="seed-"])',
  '.widget-title:not([class*="seed-"])',
  '.sentiment-card',
  '.skel-bar',
  '.set-slider:not([class*="seed-"])',
  '[role="button"]',
  'div[style*="grid-template-columns"]',
  '[style*="font-size:1"]',
];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.addInitScript(() => {
  try { sessionStorage.setItem('econLockOk_v1', '1'); } catch (_) {}
});
const page = await ctx.newPage();
await page.goto(`${BASE}/index.html?p=dashboard`, { waitUntil: 'load', timeout: 60000 });
await page.waitForTimeout(2500);
// 모든 페이지를 한 번씩 렌더해 JS 생성 마크업까지 DOM 에 올린다
const PAGES = ['market', 'equity', 'macro', 'investor', 'calendar', 'portfolio',
               'realestate', 'study', 'notes', 'settings', 'merblog', 'dashboard'];
for (const p of PAGES) {
  await page.evaluate(id => { try { showPage(id, null); } catch (_) {} }, p);
  await page.waitForTimeout(700);
}
const counts = await page.evaluate(sels => {
  const out = {};
  for (const s of sels) {
    try { out[s] = document.querySelectorAll(s).length; } catch (e) { out[s] = 'ERR'; }
  }
  // astryx 이름이 아직 참조되는지 — 계산값이 비면 미정의
  const cs = getComputedStyle(document.documentElement);
  const probe = {};
  ['--color-series-1', '--color-series-9', '--color-text-gray', '--color-background-teal',
   '--color-icon-purple', '--font-size-4xs', '--radius-page', '--duration-slow',
   '--shadow-inset-hover', '--color-manner-temp-l1-bg'].forEach(n => {
    probe[n] = cs.getPropertyValue(n).trim() || '(미정의)';
  });
  return { out, probe };
}, SELECTORS);
console.log('— 전환기 셀렉터 매칭 수 (12페이지 모두 렌더 후) —');
for (const [k, v] of Object.entries(counts.out)) console.log(String(v).padStart(5), k);
console.log('\n— 토큰 계산값 —');
for (const [k, v] of Object.entries(counts.probe)) console.log(k.padEnd(30), v);
await browser.close();
