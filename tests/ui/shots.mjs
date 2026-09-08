// SEED 개편 시각·계측 게이트 — 16샷(뷰포트 4 × 테마 2 × 등락 관습 2) + 계측.
//
// 왜 스크립트인가: 단계마다 같은 조건을 손으로 재현할 수 없다. 여기서 통과하지 못한
// 커밋은 push 하지 않는다(기획안 §11·§13).
//
// 실행:  node tests/ui/shots.mjs [--url=http://127.0.0.1:8080] [--page=dashboard]
//        결과 = tests/ui/out/<page>/<w>-<theme>-<conv>.png + report.json (gitignore)
//
// 계측 항목(§13 성공 지표)
//   · 콘솔 에러 0
//   · 터치 타깃 <44px 개수(390 폭)
//   · font-size 종수
//   · --seed-color-fg-brand 실효값(라이트/다크 blue 여야 한다 — 위험 R1 어서션)
//   · 홈 scrollHeight
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { chromium } from 'playwright';

const arg = (k, d) => (process.argv.find(a => a.startsWith(`--${k}=`)) || `=${d}`).split('=').slice(1).join('=');
const BASE = arg('url', 'http://127.0.0.1:8080');
const PAGE = arg('page', 'dashboard');
const OUT = join(dirname(new URL(import.meta.url).pathname.slice(1)), 'out', PAGE);
const WIDTHS = [390, 768, 1280, 1440];
const THEMES = ['dark', 'light'];
const CONVS = ['kr', 'global'];

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const report = [];

for (const w of WIDTHS) {
  for (const theme of THEMES) {
    for (const conv of CONVS) {
      const ctx = await browser.newContext({
        viewport: { width: w, height: w < 500 ? 844 : 900 },
        deviceScaleFactor: 1,
        isMobile: false,
      });
      // localStorage 를 첫 페인트 전에 심는다 — FOUC 블록이 이 값을 읽는다
      await ctx.addInitScript(([t, c]) => {
        try {
          localStorage.setItem('econ_theme', t);
          localStorage.setItem('econ_color_conv', c);
        } catch (_) {}
      }, [theme, conv]);
      const page = await ctx.newPage();
      const errors = [];
      page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 200)); });
      page.on('pageerror', e => errors.push('pageerror: ' + String(e).slice(0, 200)));
      await page.goto(`${BASE}/index.html?p=${PAGE}`, { waitUntil: 'load', timeout: 60000 });
      await page.waitForTimeout(3500);  // 데이터 페치 + 차트 렌더

      const m = await page.evaluate(() => {
        const cs = getComputedStyle(document.documentElement);
        const small = [...document.querySelectorAll('a,button,input,select,textarea,[role="button"],[onclick]')]
          .filter(el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && (r.height < 44 || r.width < 44);
          }).length;
        const sizes = new Set();
        document.querySelectorAll('body *').forEach(el => {
          const r = el.getBoundingClientRect();
          if (r.width && r.height && el.textContent && el.children.length === 0) {
            sizes.add(getComputedStyle(el).fontSize);
          }
        });
        return {
          brand: cs.getPropertyValue('--seed-color-fg-brand').trim(),
          up: cs.getPropertyValue('--c-up').trim(),
          down: cs.getPropertyValue('--c-down').trim(),
          bodyBg: getComputedStyle(document.body).backgroundColor,
          seedMode: document.documentElement.dataset.seedColorMode || '',
          lightClass: document.documentElement.classList.contains('light'),
          smallTargets: small,
          fontSizes: [...sizes].sort(),
          scrollHeight: document.documentElement.scrollHeight,
          seedLoaded: [...document.styleSheets].some(s => (s.href || '').includes('seed.css')),
        };
      });
      const file = join(OUT, `${w}-${theme}-${conv}.png`);
      await page.screenshot({ path: file, fullPage: false });
      report.push({ w, theme, conv, errors, ...m });
      console.log(`${w}-${theme}-${conv}  brand=${m.brand} up=${m.up} mode=${m.seedMode} ` +
                  `seedCss=${m.seedLoaded} <44px=${m.smallTargets} fs=${m.fontSizes.length} ` +
                  `h=${m.scrollHeight} err=${errors.length}`);
      if (errors.length) console.log('   ! ' + errors.slice(0, 3).join('\n   ! '));
      await ctx.close();
    }
  }
}
await browser.close();
writeFileSync(join(OUT, 'report.json'), JSON.stringify(report, null, 2));

// ── 게이트 판정 ──
const fails = [];
const isBlue = h => /^rgb\(19,\s*95,\s*205\)$|^#135fcd$|^rgb\(65,\s*162,\s*249\)$|^#41a2f9$/i.test(h);
for (const r of report) {
  const id = `${r.w}-${r.theme}-${r.conv}`;
  if (r.errors.length) fails.push(`${id}: 콘솔 에러 ${r.errors.length}건 — ${r.errors[0]}`);
  if (!r.seedLoaded) fails.push(`${id}: seed.css 미로드`);
  if (!isBlue(r.brand)) fails.push(`${id}: fg-brand 가 blue 가 아니다 (${r.brand})`);
  const wantMode = r.theme === 'light' ? 'light-only' : 'dark-only';
  if (r.seedMode !== wantMode) fails.push(`${id}: seedColorMode=${r.seedMode} (기대 ${wantMode})`);
  if (r.lightClass !== (r.theme === 'light')) fails.push(`${id}: html.light 와 테마 불일치`);
}
console.log(fails.length ? '\nFAIL\n - ' + fails.join('\n - ') : '\nPASS — 16샷 게이트 통과');
process.exit(fails.length ? 1 : 0);
