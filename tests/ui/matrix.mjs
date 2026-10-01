// T5 자동 촬영 — 폭 4 × 테마 2 × 경로 목록을 찍어 out/matrix/<폭>-<테마>-<경로>.png 로 저장.
// 실행: node tests/ui/matrix.mjs [--url ...] [--paths ...] [--baseline <이전 촬영 폴더>] [--max-diff 1.0]
//   --baseline 이 있으면 같은 이름 파일과 픽셀 차이율(%)을 표로 보고한다.
//   --max-diff 를 주면 그 값(%)을 넘는 파일이 있을 때 종료 코드 1.
// 차이율은 브라우저 canvas 로 비교한다(추가 의존성 없음). 크기가 다르면 큰 쪽 면적 기준으로 센다.
// 폭·테마·경로 인자와 주소는 overflow.mjs 와 같다. 기존 shots.mjs 는 한 화면 16컷 계측용이라 별개.
import { mkdirSync, readdirSync, readFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { chromium } from 'playwright';
import { opt, sweep, slug } from './_lib.mjs';

const OUT = resolve(dirname(new URL(import.meta.url).pathname.slice(1)), 'out', 'matrix');
mkdirSync(OUT, { recursive: true });
const written = [];
await sweep({ onShot: async (page, { w, theme, p }) => {
  const name = `${w}-${theme}-${slug(p)}.png`;
  await page.screenshot({ path: join(OUT, name), fullPage: true });
  written.push(name);
} });
console.log(`[matrix] ${written.length}컷 저장 → ${OUT}`);

const base = opt('baseline', '');
if (!base || base === true) process.exit(0);
if (!existsSync(base)) { console.log(`기준 폴더 없음: ${base}`); process.exit(1); }
const browser = await chromium.launch();
const pg = await browser.newPage();
const b64 = f => 'data:image/png;base64,' + readFileSync(f).toString('base64');
const diff = (a, b) => pg.evaluate(async ([a, b]) => {
  const load = s => new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = s; });
  const [A, B] = await Promise.all([load(a), load(b)]);
  const W = Math.max(A.width, B.width), H = Math.max(A.height, B.height);
  const px = i => {
    const c = document.createElement('canvas'); c.width = W; c.height = H;
    const x = c.getContext('2d', { willReadFrequently: true }); x.drawImage(i, 0, 0);
    return x.getImageData(0, 0, W, H).data;
  };
  const da = px(A), db = px(B);
  let n = 0;
  for (let k = 0; k < da.length; k += 4)
    if (Math.abs(da[k] - db[k]) + Math.abs(da[k + 1] - db[k + 1]) + Math.abs(da[k + 2] - db[k + 2]) + Math.abs(da[k + 3] - db[k + 3]) > 24) n++;
  return { pct: n / (W * H) * 100, size: A.width === B.width && A.height === B.height ? '' : `${A.width}x${A.height} 대 ${B.width}x${B.height}` };
}, [a, b]);
const rows = [];
for (const f of readdirSync(base).filter(f => f.endsWith('.png'))) {
  if (!written.includes(f)) { rows.push([f, null, '이번 촬영에 없음']); continue; }
  const d = await diff(b64(join(OUT, f)), b64(join(base, f)));
  rows.push([f, d.pct, d.size]);
}
await browser.close();
const lim = opt('max-diff', null);
console.log('\n' + '파일'.padEnd(44) + '차이율(%)  비고');
for (const [f, pct, note] of rows) console.log(f.padEnd(44), (pct == null ? '-' : pct.toFixed(2)).padStart(8), ' ', note);
process.exit(lim && lim !== true && rows.some(r => r[1] > Number(lim)) ? 1 : 0);
