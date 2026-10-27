// Build favicon / app icons / share image from the traced SVGs. Run: node scripts/brand/build_icons.mjs
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const pub = path.join(root, 'app', 'public');
const brand = path.join(pub, 'brand');
const DEEP = '#005034', LOGO_GREEN = '#006F3A', SECOND = '#00744C', SAGE = '#B5C9BA';

const read = (f) => fs.readFileSync(path.join(brand, f), 'utf8');
const colored = (f, color, style = '') =>
  read(f).replace('<svg ', `<svg style="color:${color};${style}" `);

// favicon.svg: fixed-colour copy of the mark
fs.writeFileSync(path.join(pub, 'favicon.svg'), read('ecom-mark.svg').replaceAll('currentColor', LOGO_GREEN));

const MARK_RATIO = 102 / 148; // w/h
// square tile with centred white mark; markH = mark height as fraction of tile
const tile = (size, bg, radiusPct, markFrac) => {
  const mh = size * markFrac, mw = mh * MARK_RATIO;
  return `<body style="margin:0;background:transparent"><div style="width:${size}px;height:${size}px;background:${bg};border-radius:${radiusPct}%;position:relative">
  ${colored('ecom-mark.svg', '#fff', `position:absolute;height:${mh}px;width:${mw}px;left:${(size - mw) / 2}px;top:${(size - mh) / 2}px`)}</div></body>`;
};

const og = `<body style="margin:0;width:1200px;height:630px;background:${DEEP};position:relative;overflow:hidden;font-family:'Malgun Gothic','Noto Sans KR',sans-serif">
  ${colored('ecom-logo.svg', '#fff', 'position:absolute;left:80px;top:150px;width:520px')}
  <div style="position:absolute;left:80px;top:400px;color:#fff;font-size:34px;font-weight:700;letter-spacing:-0.5px">ECOM 멤버 시장 화면</div>
  <div style="position:absolute;left:80px;top:452px;color:${SAGE};font-size:24px">ecom-terminal.pages.dev</div>
  <div style="position:absolute;left:760px;top:110px;width:260px;height:260px;border-radius:40px;background:${SECOND}"></div>
  <div style="position:absolute;left:900px;top:300px;width:220px;height:220px;border-radius:40px;background:${SAGE}"></div>
</body>`;

const jobs = [
  ['icon-192.png', 192, 192, tile(192, DEEP, 22, 0.56)],
  ['icon-512.png', 512, 512, tile(512, DEEP, 22, 0.56)],
  ['icon-maskable-512.png', 512, 512, tile(512, DEEP, 0, 0.44)],
  ['apple-touch-icon.png', 180, 180, tile(180, DEEP, 0, 0.56)],
  ['badge-96.png', 96, 96, tile(96, 'transparent', 0, 0.8)],
  ['og-cover.png', 1200, 630, og],
];

const browser = await chromium.launch();
try {
  for (const [name, w, h, html] of jobs) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    await page.setContent(html);
    await page.screenshot({ path: path.join(pub, name), omitBackground: true, clip: { x: 0, y: 0, width: w, height: h } });
    await page.close();
    console.log('wrote', name);
  }
} finally { await browser.close(); }
fs.copyFileSync(path.join(pub, 'og-cover.png'), path.join(root, 'og-cover.png'));
console.log('wrote root og-cover.png');
