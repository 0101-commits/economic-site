// 첫 그림 접힘 0 게이트 — 사용 패턴 개선 명세 P0 I1. 패널은 늘 펼친 채 시작하고, 사용자가 접은 것만 이 기기에 기억한다.
// 실행: node tests/ui/foldzero.mjs [--url http://127.0.0.1:5173/next/] [--paths "#/,#/market"] [--widths 390,1440] [--wait 2500]
// 검사(폭 × 경로마다, 빈 저장소로 연 첫 그림): Panel 의 접힘 details[data-panel-fold]:not([open]) 0개.
//   접을 수 있는 패널 수도 같이 찍는다 — 0 이면 게이트가 아무것도 안 본 것이다.
// 경로: _lib.mjs 의 NEXT_PATHS 전부, 단 #/my 는 PIN 관문 뒤라 뺀다. 종료 코드: 접힘 또는 실행 오류가 있으면 1.
import { chromium } from 'playwright';
import { opt, baseUrl, newCtx, fullUrl, NEXT_PATHS, WAIT } from './_lib.mjs';

const widths = String(opt('widths', '390,1440')).split(',').map(Number);
const given = opt('paths', '');
const list = given && given !== true ? given.split(',').map(s => s.trim()).filter(Boolean) : NEXT_PATHS.filter(p => p !== '#/my');
const base = baseUrl();

const browser = await chromium.launch();
let bad = 0, errs = 0;
console.log(`[foldzero] 기준 주소 ${base}`);
for (const w of widths) {
  const ctx = await newCtx(browser, w, 'light');
  for (const p of list) {
    const page = await ctx.newPage();
    try {
      await page.goto(fullUrl(base, p), { waitUntil: 'load', timeout: 60000 });
      await page.waitForTimeout(WAIT);
      const r = await page.evaluate(() => {
        const all = [...document.querySelectorAll('details[data-panel-fold]')];
        return { total: all.length, closed: all.filter(d => !d.open).map(d => (d.querySelector('h2')?.textContent || '').trim()) };
      });
      bad += r.closed.length;
      console.log(`  ${r.closed.length ? '위반' : '통과'}  ${String(w).padStart(4)} ${p} — 접힘 ${r.closed.length} / 접을 수 있는 패널 ${r.total}${r.closed.length ? ` 「${r.closed.join('」 「')}」` : ''}`);
    } catch (e) {
      errs++;
      console.log(`  오류  ${String(w).padStart(4)} ${p} — ${String(e.message || e).split('\n')[0]}`);
    }
    await page.close();
  }
  await ctx.close();
}
await browser.close();
console.log(`합계 접힘 ${bad}개, 실행 오류 ${errs}건 → ${bad || errs ? '실패(종료 코드 1)' : '통과'}`);
process.exit(bad || errs ? 1 : 0);
