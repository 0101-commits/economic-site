// Compare traced SVGs with the source alpha. exit 1 if any mismatch >= 1%.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const png = fs.readFileSync(path.join(here, 'ecom-logo-source.png')).toString('base64');
const brand = path.join(here, '..', '..', 'app', 'public', 'brand');
// regions in source coords: [x0,y0,x1,y1]
const cases = {
  mark: ['ecom-mark.svg', [61, 159, 61 + 102, 307]],
  word: ['ecom-word.svg', [61 + 129, 159, 442, 159 + 64]],
  logo: ['ecom-logo.svg', [61, 159, 442, 307]],
};

const browser = await chromium.launch();
let bad = false;
const out = [];
try {
  const page = await browser.newPage();
  await page.setContent('<canvas id=c></canvas>');
  for (const [name, [file, box]] of Object.entries(cases)) {
    const svg = fs.readFileSync(path.join(brand, file), 'utf8').replaceAll('currentColor', '#000');
    const ratio = await page.evaluate(async ({ png, svg, box }) => {
      const load = (src) => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = src; });
      const [x0, y0, x1, y1] = box, w = x1 - x0, h = y1 - y0;
      const cv = document.createElement('canvas'); cv.width = w; cv.height = h;
      const ctx = cv.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(await load('data:image/png;base64,' + png), x0, y0, w, h, 0, 0, w, h);
      const a = ctx.getImageData(0, 0, w, h).data;
      ctx.clearRect(0, 0, w, h);
      const si = await load('data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg));
      ctx.drawImage(si, 0, 0, w, h);
      const b = ctx.getImageData(0, 0, w, h).data;
      let diff = 0;
      for (let i = 3; i < a.length; i += 4) if ((a[i] > 128) !== (b[i] > 128)) diff++;
      return diff / (w * h);
    }, { png, svg, box });
    out.push(`${name} ${(ratio * 100).toFixed(3)}%`);
    if (ratio >= 0.01) bad = true;
  }
} finally { await browser.close(); }
console.log(out.join(' · '));
process.exit(bad ? 1 : 0);
