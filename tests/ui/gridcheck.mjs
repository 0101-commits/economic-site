// P5 근거 — 격자·높이 유틸 클래스가 폭 구간마다 의도한 값으로 계산되는지 본다.
//
// 인라인 문자열 매칭 규칙을 클래스로 갈아탄 뒤, "실제 계산값"이 옛 동작과 같은지는
// 눈으로 볼 수 없다. 폭별 열 개수와 가로 넘침을 세어 회귀를 잡는다.
//
// 같이 고정하는 것: 컨트롤 중첩(버튼 안의 버튼)과 `[role="button"]` = 0.
// P5 에서 div/span+onclick 을 전부 실제 <button> 으로 옮겼고, 표의 행은 대표 칸에
// 버튼을 넣는 방식으로 갔다 — 되돌아가면 여기서 실패한다.
//
// 실행: node tests/ui/gridcheck.mjs [--url=…]   (실패 시 exit 1)
import { chromium } from 'playwright';

const arg = (k, d) => (process.argv.find(a => a.startsWith(`--${k}=`)) || `=${d}`).split('=').slice(1).join('=');
const BASE = arg('url', 'http://127.0.0.1:8080');
const WIDTHS = [1440, 1280, 1024, 768, 390];
const PAGES = ['dashboard', 'market', 'equity', 'macro', 'investor', 'calendar',
               'portfolio', 'realestate', 'study', 'notes', 'settings', 'merblog'];

const browser = await chromium.launch();
let bad = 0;
for (const w of WIDTHS) {
  const ctx = await browser.newContext({ viewport: { width: w, height: w < 500 ? 844 : 900 } });
  await ctx.addInitScript(() => { try { sessionStorage.setItem('econLockOk_v1', '1'); } catch (_) {} });
  const page = await ctx.newPage();
  // 네트워크·CSP 잡음(프록시 429/503, 네이버 SDK)은 레이아웃 회귀가 아니다 —
  // shots.mjs 와 같은 기준으로 갈라 센다.
  const errs = [], net = [];
  const isNet = s => /Failed to load resource|net::|Content Security Policy|status of \d/.test(s);
  const push = s => (isNet(s) ? net : errs).push(s);
  page.on('pageerror', e => push(String(e.message || e)));
  page.on('console', m => { if (m.type() === 'error') push(m.text()); });
  await page.goto(`${BASE}/index.html?p=dashboard`, { waitUntil: 'load', timeout: 60000 });
  await page.waitForTimeout(2200);
  const seen = new Map();
  let overflow = [];
  for (const p of PAGES) {
    await page.evaluate(id => { try { showPage(id, null); } catch (_) {} }, p);
    await page.waitForTimeout(450);
    const res = await page.evaluate(() => {
      const out = { cols: {}, over: [] };
      const main = document.querySelector('main');
      const vw = main ? main.clientWidth : window.innerWidth;
      document.querySelectorAll('main [class*="g-"], main [class*="h-"], main [class*="mh-"]').forEach(el => {
        if (!el.offsetParent && el.offsetHeight === 0) return;
        const cs = getComputedStyle(el);
        const cls = [...el.classList].filter(c => /^(g|h|mh)-/.test(c)).join('+');
        if (!cls) return;
        const key = cls + ' → ' + (cs.display === 'grid'
          ? cs.gridTemplateColumns.split(' ').length + '열'
          : cs.display) + (cs.height !== 'auto' ? ' h=' + Math.round(parseFloat(cs.height)) : '');
        out.cols[key] = (out.cols[key] || 0) + 1;
        if (el.scrollWidth > vw + 2) out.over.push(cls + ' scrollW=' + el.scrollWidth + ' vs ' + vw);
      });
      return out;
    });
    for (const [k, v] of Object.entries(res.cols)) seen.set(k, (seen.get(k) || 0) + v);
    overflow = overflow.concat(res.over);
  }
  // 컨트롤 중첩·잘못된 역할 — P5 에서 div/span+onclick 을 실제 버튼으로 옮긴 뒤
  // 다시 생기지 않도록 고정한다(버튼 안의 버튼은 접근성 트리가 깨진다).
  const bad2 = await page.evaluate(() => ({
    nested: [...document.querySelectorAll('button button, button a[href], a[href] button')]
      .map(el => el.outerHTML.slice(0, 60).replace(/\s+/g, ' ')),
    roleBtn: [...document.querySelectorAll('[role="button"]')]
      .map(el => el.tagName.toLowerCase() + '.' + ((el.className || '').toString().split(/\s+/)[0] || '-')),
    tableRole: [...document.querySelectorAll('tr[role="button"], td[role="button"], th[role="button"]')].length,
  }));
  console.log(`\n══ ${w}px ══  (콘솔 에러 ${errs.length} · 네트워크 잡음 ${net.length})`);
  if (bad2.nested.length) { bad += bad2.nested.length; console.log('  ⚠ 컨트롤 중첩 ' + bad2.nested.length + '건: ' + bad2.nested.slice(0, 3).join(' | ')); }
  if (bad2.roleBtn.length) { bad += bad2.roleBtn.length; console.log('  ⚠ role="button" ' + bad2.roleBtn.length + '건(실제 <button> 을 쓴다): ' + [...new Set(bad2.roleBtn)].slice(0, 5).join(', ')); }
  if (bad2.tableRole) { bad += bad2.tableRole; console.log('  ⚠ 표 요소에 role="button" ' + bad2.tableRole + '건'); }
  [...seen.entries()].sort().forEach(([k, v]) => console.log('  ' + String(v).padStart(3) + '  ' + k));
  if (overflow.length) {
    bad += overflow.length;
    console.log('  ⚠ 가로 넘침 ' + overflow.length + '건: ' + [...new Set(overflow)].slice(0, 6).join(' | '));
  }
  if (errs.length) { bad += errs.length; console.log('  ⚠ 에러: ' + errs.slice(0, 4).join(' | ')); }
  await ctx.close();
}
await browser.close();
console.log(bad ? `\n실패 신호 ${bad}건` : '\n넘침·에러 0');
process.exit(bad ? 1 : 0);
