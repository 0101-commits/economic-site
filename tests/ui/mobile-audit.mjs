// 모바일 화면 감사 — 깨짐·빈 공간·넘침을 숫자로 잡는다.
// 실행: node tests/ui/mobile-audit.mjs [--url=http://127.0.0.1:8080] [--w=390] [--shots]
//
// 무엇을 세는가
//  1) 가로 넘침: 문서·요소가 뷰포트를 넘는가(모바일에서 화면이 '깨져' 보이는 1순위 원인)
//  2) 빈 띠: 본문 세로축을 스캔해 아무 것도 그려지지 않은 구간(연속 200px 이상)
//  3) 잘린 글자: overflow 로 안 보이는 텍스트
//  4) 겹침: 형제 블록끼리 세로로 겹치는 경우
//  5) 화면 길이: 390 기준 몇 화면인지
import { chromium } from 'playwright';

const arg = (k, d) => (process.argv.find(a => a.startsWith(`--${k}=`)) || `=${d}`).split('=').slice(1).join('=');
const BASE = arg('url', 'http://127.0.0.1:8080');
const W = Number(arg('w', 390));
const H = Number(arg('h', 844));
const SHOTS = process.argv.includes('--shots');
const PAGES = (arg('pages', 'dashboard,equity,market,macro,calendar,realestate,investor,notes,study,merlens')).split(',');

const audit = async (page) => page.evaluate((vw) => {
  const out = { overflowX: [], gaps: [], clipped: [], overlap: [], docH: document.documentElement.scrollHeight };
  const vis = (el) => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const active = document.querySelector('.page.active');
  out.page = active ? active.id : null;

  // 1) 가로 넘침
  out.docOverflow = Math.max(0, document.documentElement.scrollWidth - vw);
  document.querySelectorAll('.page.active *').forEach((el) => {
    if (!vis(el)) return;
    const r = el.getBoundingClientRect();
    if (r.width > vw + 2 || r.right > vw + 2) {
      const s = getComputedStyle(el);
      if (s.overflowX === 'auto' || s.overflowX === 'scroll') return;   // 의도된 가로 스크롤 영역
      if (el.closest('[style*="overflow-x:auto"],[style*="overflow-x: auto"],.g-scroll')) return;
      out.overflowX.push({
        sel: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : ''),
        w: Math.round(r.width), right: Math.round(r.right),
        text: (el.textContent || '').trim().slice(0, 24)
      });
    }
  });
  out.overflowX = out.overflowX.slice(0, 12);

  // 2) 빈 띠 — 본문 세로축을 20px 간격으로 훑어 아무 요소도 없는 구간을 찾는다
  if (active) {
    const top = active.getBoundingClientRect().top + window.scrollY;
    const bottom = top + active.getBoundingClientRect().height;
    const step = 20;
    const rows = [];
    const boxes = [];
    active.querySelectorAll('*').forEach((el) => {
      if (!vis(el)) return;
      if (el.children.length && !(el.textContent || '').trim() && !el.querySelector('canvas,svg,img,input,button')) return;
      const r = el.getBoundingClientRect();
      if (r.height < 2) return;
      boxes.push([r.top + window.scrollY, r.bottom + window.scrollY]);
    });
    for (let y = top; y < bottom; y += step) {
      rows.push(boxes.some(([a, b]) => y >= a && y <= b));
    }
    let run = 0, start = 0;
    rows.forEach((filled, i) => {
      if (!filled) { if (run === 0) start = i; run++; return; }
      if (run * step >= 200) out.gaps.push({ atY: Math.round(top + start * step), h: run * step });
      run = 0;
    });
    if (run * step >= 200) out.gaps.push({ atY: Math.round(top + start * step), h: run * step });
  }

  // 3) 잘린 글자
  document.querySelectorAll('.page.active *').forEach((el) => {
    if (!vis(el) || el.children.length) return;
    const t = (el.textContent || '').trim();
    if (!t) return;
    if (el.closest('.sr-only, .econ-sr') || el.classList.contains('sr-only') || el.classList.contains('econ-sr')) return;   // 낭독 전용 텍스트는 오탐
    if (el.classList.contains('econ-why')) return;                            // 한 줄 맥락은 말줄임이 의도
    var cs = getComputedStyle(el);
    if (cs.textOverflow === 'ellipsis') return;   // 말줄임은 '잘림'이 아니라 의도된 축약
    if (el.scrollWidth > el.clientWidth + 4 && cs.overflow !== 'visible') {
      out.clipped.push({ text: t.slice(0, 20), sw: el.scrollWidth, cw: el.clientWidth });
    }
  });
  out.clipped = out.clipped.slice(0, 8);

  // 4) 겹침 — 위젯끼리 세로로 겹치면 레이아웃이 깨진 것이다
  const widgets = [...document.querySelectorAll('.page.active .widget')].filter(vis);
  for (let i = 0; i < widgets.length - 1; i++) {
    const a = widgets[i].getBoundingClientRect(), b = widgets[i + 1].getBoundingClientRect();
    if (a.bottom > b.top + 4 && a.left < b.right && b.left < a.right) {
      out.overlap.push({ a: widgets[i].id || i, b: widgets[i + 1].id || (i + 1), by: Math.round(a.bottom - b.top) });
    }
  }
  out.overlap = out.overlap.slice(0, 6);
  return out;
}, W);

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const page = await ctx.newPage();
const errs = [];
page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text().slice(0, 100)); });
page.on('pageerror', (e) => errs.push('pageerror: ' + String(e).slice(0, 100)));

let bad = 0;
for (const p of PAGES) {
  await page.goto(`${BASE}/index.html?p=${p}`, { waitUntil: 'load', timeout: 60000 });
  await page.waitForTimeout(3500);
  const r = await audit(page);
  const screens = (r.docH / H).toFixed(1);
  const flags = [];
  if (r.docOverflow > 0) flags.push(`가로넘침 ${r.docOverflow}px`);
  if (r.overflowX.length) flags.push(`넘치는 요소 ${r.overflowX.length}`);
  if (r.gaps.length) flags.push(`빈 띠 ${r.gaps.map(g => g.h + 'px@' + g.atY).join(',')}`);
  if (r.overlap.length) flags.push(`겹침 ${r.overlap.length}`);
  if (r.clipped.length) flags.push(`잘린 글자 ${r.clipped.length}`);
  if (flags.length) bad++;
  console.log(`${p.padEnd(11)} ${String(r.docH).padStart(6)}px (${screens}화면)  ${flags.join(' · ') || 'OK'}`);
  if (r.overflowX.length) r.overflowX.slice(0, 4).forEach(o => console.log(`    ↔ ${o.sel} w=${o.w} right=${o.right} "${o.text}"`));
  if (r.clipped.length) r.clipped.slice(0, 3).forEach(c => console.log(`    ✂ "${c.text}" ${c.cw}→${c.sw}`));
  if (SHOTS) await page.screenshot({ path: `tests/ui/out/mobile-${p}.png`, fullPage: true });
}
if (errs.length) { console.log('\n콘솔 에러:'); errs.slice(0, 8).forEach(e => console.log('  ' + e)); }
console.log(`\n문제 있는 화면 ${bad}/${PAGES.length} · 콘솔 에러 ${errs.length}`);
await browser.close();
