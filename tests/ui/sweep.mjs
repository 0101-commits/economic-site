// 전수 실측(T6): 새 화면의 모든 경로를 열고 안전한 버튼을 전부 눌러 콘솔 오류·실패 요청·가로 넘침·빈 상태 문구를 센다.
// 실행: node tests/ui/sweep.mjs <base> [width]   예) node tests/ui/sweep.mjs https://0101-commits.github.io/economic-site/ 390
// 「!!」 줄이 하나라도 있으면 결함이다(지우기·올리기 같은 상태 바꾸는 버튼은 누르지 않는다).
import { chromium } from 'playwright';
const base = process.argv[2] || 'https://0101-commits.github.io/economic-site/';
const width = Number(process.argv[3] || 1440);
const PATHS = ['#/', '#/?v=kr', '#/?v=global', '#/?v=fxrate', '#/?v=commod', '#/?v=watch',
  '#/market?a=kr', '#/market?a=global', '#/market?a=fxrate', '#/market?a=commod', '#/market?a=macro', '#/market?a=flow', '#/market?a=realestate',
  '#/lens', '#/lens?m=chain', '#/lens?m=flow', '#/alerts', '#/settings', '#/my',
  '#/i/kospi', '#/i/sp500', '#/i/usdkrw', '#/i/gold', '#/i/cpi_kr_yoy', '#/i/apt_price_idx_kr', '#/i/gdp_growth_us'];
const UNSAFE = /지우|삭제|지워|초기화|올리|받기|보내|저장|추가|끄기|켜기|잠그|잠금|PIN|확인|시작|내려받|테스트|구독|해제|그만|다시 켜기|동기화/;
const EMPTY_RE = /(자료 없음|없습니다|수집 대기|축적 중|불러오지|오류|실패|찾을 수 없)/g;
const br = await chromium.launch();
const ctx = await br.newContext({ viewport: { width, height: width < 500 ? 844 : 900 } });
const pg = await ctx.newPage();
const report = [];
let errs = [];
pg.on('pageerror', e => errs.push('pageerror: ' + e.message.slice(0, 160)));
pg.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
pg.on('response', r => { if (r.status() >= 400) errs.push(`${r.status()} ${r.url().replace(base, '')}`); });
for (const p of PATHS) {
  errs = [];
  await pg.goto(base + p, { waitUntil: 'networkidle' }).catch(e => errs.push('goto: ' + e.message.slice(0, 100)));
  await pg.waitForTimeout(1200);
  const before = await pg.evaluate(() => document.body.innerText);
  const loadErrs = [...new Set(errs)]; errs = [];
  // 안전한 버튼 전부 누르기(화면 안 버튼만, 같은 글자는 한 번)
  const seen = new Set(); const clicked = []; const clickErrs = {};
  for (let round = 0; round < 3; round++) {
    const btns = await pg.$$('main button, main [role="tab"], main a[href^="#/"]');
    let any = false;
    for (const b of btns) {
      const label = ((await b.getAttribute('aria-label')) || (await b.innerText().catch(() => '')) || '').trim().replace(/\s+/g, ' ').slice(0, 40);
      if (!label || seen.has(label) || UNSAFE.test(label)) continue;
      const vis = await b.isVisible().catch(() => false); if (!vis) continue;
      seen.add(label); any = true;
      const tag = await b.evaluate(e => e.tagName);
      if (tag === 'A') continue;   // 링크는 이동 — 경로 목록이 대신 본다
      errs = [];
      await b.click({ timeout: 2000 }).catch(e => errs.push('click: ' + e.message.slice(0, 80)));
      await pg.waitForTimeout(350);
      if (errs.length) clickErrs[label] = [...new Set(errs)];
      clicked.push(label);
      if (pg.url().replace(base, '') !== p && !pg.url().includes(p.split('?')[0])) { await pg.goto(base + p, { waitUntil: 'networkidle' }); await pg.waitForTimeout(600); }
    }
    if (!any) break;
  }
  const after = await pg.evaluate(() => document.body.innerText);
  const empties = [...new Set((before + '\n' + after).split('\n').filter(l => EMPTY_RE.test(l)))].slice(0, 10);
  const dashes = (after.match(/(^|\s)—(\s|$)/g) || []).length;
  const overflow = await pg.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  report.push({ p, textLen: before.length, loadErrs, clicked: clicked.length, clickErrs, empties, dashes, overflow });
}
await br.close();
for (const r of report) {
  const flag = (r.loadErrs.length || Object.keys(r.clickErrs).length || r.overflow) ? '!!' : 'ok';
  console.log(`${flag} ${r.p}  글자 ${r.textLen}  버튼 ${r.clicked}  — ${r.dashes}  빈상태 ${r.empties.length}${r.overflow ? '  가로넘침' : ''}`);
  for (const e of r.loadErrs) console.log('     load:', e);
  for (const [k, v] of Object.entries(r.clickErrs)) console.log('     click[' + k + ']:', v.join(' | '));
  for (const e of r.empties) console.log('     빈:', e.slice(0, 90));
}
