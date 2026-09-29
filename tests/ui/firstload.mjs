// 첫 도착 게이트 — data.json 을 4초 늦춰 '딥링크로 곧장 연 화면이 자료 도착 뒤 차트를 그리는가'를 잰다.
//
//   node tests/ui/firstload.mjs                 # 7화면 · 1440
//   node tests/ui/firstload.mjs --delay=6000
//
// 전제: python -m http.server 8080 --bind 127.0.0.1
//
// 왜 — 로컬은 data.json(3.6MB)이 빌더(showPage +50ms)보다 먼저 와서 재현되지 않고, 라이브(GitHub Pages)는
// 늦게 온다. 2026-09-29 라이브 실측: ?p=equity 두 차트가 20초 뒤에도 '데이터 추가 필요', 원자재 탭 차트 6개도 같은 뿌리.
// loadRealData 의 활성 화면 재렌더가 두 번째 갱신부터만 돌았던 것이 원인이었다. 이 게이트는 그 경로를 느린 망으로 고정한다.
import { chromium } from 'playwright';

const arg = (k, d) => { const hit = process.argv.find(a => a.startsWith(`--${k}=`)); return hit ? hit.slice(k.length + 3) : d; };
const BASE = arg('base', 'http://127.0.0.1:8080');
const DELAY = +arg('delay', 4000);
const SCREENS = ['p=dashboard', 'p=equity', 'p=macro', 'p=market&t=fx', 'p=market&t=commodity', 'p=investor', 'p=realestate'];

const browser = await chromium.launch();
let failed = 0;
for (const q of SCREENS) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ko-KR', timezoneId: 'Asia/Seoul' });
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', e => { if (!/oapi\.map\.naver|maps\.js/.test(e.stack || '')) errs.push(String(e.message).slice(0, 100)); });
  await page.route('**/data.json*', async route => { await new Promise(r => setTimeout(r, DELAY)); await route.continue(); });
  await page.goto(`${BASE}/?${q}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(DELAY + 6000);
  const r = await page.evaluate(() => {
    const vis = e => !!e.offsetParent;
    const pg = document.querySelector('.page.active');
    const cs = [...pg.querySelectorAll('canvas')].filter(vis);
    const empty = cs.filter(c => { const o = c.parentElement && c.parentElement.querySelector('.no-data-overlay'); return !c.getAttribute('width') || (o && vis(o) && o.getBoundingClientRect().height > 0); }).map(c => c.id);
    const lead = pg.querySelector('.econ-lead');
    return { canv: cs.length, empty, lead: !!lead && !/자료 없음/.test(lead.innerText) };
  });
  const bad = [];
  if (r.empty.length) bad.push('빈 차트 ' + r.empty.join(','));
  if (!r.lead) bad.push('결론 줄 없음/자료 없음');
  if (errs.length) bad.push('콘솔 오류 ' + errs[0]);
  if (bad.length) failed++;
  console.log(`${bad.length ? 'FAIL' : 'PASS'} ${q.padEnd(24)} 캔버스 ${r.canv}  ${bad.join(' · ')}`);
  await ctx.close();
}
await browser.close();
console.log(failed ? `\nFAIL — ${failed}화면` : '\nPASS — 첫 도착(느린 자료) 7화면 통과');
process.exit(failed ? 1 : 0);
