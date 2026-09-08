// P4 근거 — astryx 레이어의 !important 가 아직 '인라인을 이기는 일'을 하는지 센다.
//
// 이 레이어는 인라인 스타일(2,803곳)을 덮으려고 !important 로 쓰였다. 인라인이
// 사라진 자리에서는 순전히 recipe 와 싸우는 부작용만 남는다. 무엇이 남았는지
// 세고 나서 지운다.
//
// 실행: node tests/ui/important.mjs
import { chromium } from 'playwright';

const arg = (k, d) => (process.argv.find(a => a.startsWith(`--${k}=`)) || `=${d}`).split('=').slice(1).join('=');
const BASE = arg('url', 'http://127.0.0.1:8080');
const PAGES = ['dashboard', 'market', 'equity', 'macro', 'investor', 'calendar', 'portfolio',
               'realestate', 'study', 'notes', 'settings', 'merblog'];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.addInitScript(() => { try { sessionStorage.setItem('econLockOk_v1', '1'); } catch (_) {} });
const page = await ctx.newPage();
await page.goto(`${BASE}/index.html?p=dashboard`, { waitUntil: 'load', timeout: 60000 });
await page.waitForTimeout(2500);
for (const p of PAGES) {
  await page.evaluate(id => { try { showPage(id, null); } catch (_) {} }, p);
  await page.waitForTimeout(600);
}
const res = await page.evaluate(() => {
  // 사이트 스타일시트에서 !important 선언을 모으고, 그 셀렉터에 해당하는 요소가
  // 같은 속성을 인라인으로 갖고 있는지 본다.
  const rows = [];
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (_) { continue; }
    if ((sheet.href || '').includes('seed.css')) continue;   // 벤더 CSS 는 대상 아님
    const walk = list => {
      for (const r of list) {
        // ⚠ CSS Nesting 지원 이후 CSSStyleRule 도 cssRules(빈 목록)를 갖는다 —
        // "cssRules 가 있으면 컨테이너"로 판단하면 모든 규칙을 건너뛴다(실측 버그).
        if (r.cssRules && r.cssRules.length) walk(r.cssRules);
        if (!r.style || !r.selectorText) continue;
        for (let i = 0; i < r.style.length; i++) {
          const prop = r.style[i];
          if (r.style.getPropertyPriority(prop) !== 'important') continue;
          let els = [];
          try { els = [...document.querySelectorAll(r.selectorText)]; } catch (_) { continue; }
          const inline = els.filter(el => el.style && el.style.getPropertyValue(prop)).length;
          rows.push({ sel: r.selectorText.slice(0, 70), prop, matched: els.length, inline });
        }
      }
    };
    walk(rules);
  }
  return rows;
});
const dead = res.filter(r => r.matched === 0);
const noInline = res.filter(r => r.matched > 0 && r.inline === 0);
const working = res.filter(r => r.inline > 0);
console.log(`!important 선언 ${res.length}개 — 매칭 0: ${dead.length} · 매칭되지만 인라인 없음: ${noInline.length} · 실제로 인라인을 이기는 중: ${working.length}`);
const group = rows => {
  const m = new Map();
  rows.forEach(r => m.set(r.sel, (m.get(r.sel) || 0) + 1));
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
};
console.log('\n[매칭 0 — 지워도 되는 셀렉터]');
group(dead).forEach(([s, n]) => console.log(String(n).padStart(3), s));
console.log('\n[인라인을 이기는 중 — 남겨야 하는 셀렉터]');
group(working).forEach(([s, n]) => console.log(String(n).padStart(3), s));
console.log('\n[매칭되지만 인라인 없음 — recipe 와만 싸운다]');
group(noInline).slice(0, 25).forEach(([s, n]) => console.log(String(n).padStart(3), s));
await browser.close();
