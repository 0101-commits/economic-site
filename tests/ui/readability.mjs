// 가독성 게이트 — 기획안(artifact e4466492) G1~G6 을 그대로 잰다.
//
//   node tests/ui/readability.mjs                 # 홈 + 메르렌즈 × 라이트/다크
//   node tests/ui/readability.mjs --page=merlens  # 한 페이지만
//   node tests/ui/readability.mjs --base=http://127.0.0.1:8080
//
// 전제: python -m http.server 8080 --bind 127.0.0.1 (npm run ui:serve)
//
// 왜 이 여섯인가 — 세 가지가 가독성을 깎고 있었다(2026-09-18 실측):
//   ① 한글 웹폰트가 없어 한글만 방문자 OS 폰트로 떨어졌다(영문·숫자는 Figtree).
//   ② 라이트 테마에서 WCAG AA 미달이 60곳이었다(다크는 6곳).
//   ③ 홈 텍스트 요소의 65%가 11~12px 이었다.
// 눈으로 보면 되돌아가므로 숫자로 고정한다.

import { chromium } from 'playwright';

const arg = (k, d) => {
  const hit = process.argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};

const BASE  = arg('base', 'http://127.0.0.1:8080');
const PAGES = arg('page', 'dashboard,merlens').split(',').map(s => s.trim()).filter(Boolean);

// 기준값 — 현재 통과선. 내리려면 근거를 같이 적을 것.
const LIMITS = {
  contrastFails:   0,     // G1  라이트·다크 각각
  smallTextRatio:  0.10,  // G2  12px 미만 비율
  maxCharsPerLine: 50,    // G4  산문 블록
};

// ── 페이지 안에서 도는 측정기 ────────────────────────────────────────────────
function collect() {
  const lum = (r, g, b) => {
    const f = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  // color-mix() 는 브라우저가 `color(srgb 0.07 0.37 0.80)` 로 직렬화한다 — 0~1 스케일이라
  // 그대로 읽으면 거의 검정으로 잡혀 대비가 1.2:1 처럼 나온다(첫 판의 오탐 10건).
  const nums = s => {
    const v = (String(s).match(/-?\d+(\.\d+)?/g) || []).map(Number);
    return /^color\(/i.test(String(s).trim()) ? v.slice(0, 3).map(x => x * 255).concat(v.slice(3)) : v;
  };
  const ratio = (fg, bg) => {
    const a = Math.max(lum(...fg.slice(0, 3)), lum(...bg.slice(0, 3)));
    const b = Math.min(lum(...fg.slice(0, 3)), lum(...bg.slice(0, 3)));
    return (a + 0.05) / (b + 0.05);
  };
  // 배경은 투명을 거슬러 올라가 처음 만나는 불투명 면으로 본다.
  const bgOf = el => {
    for (let e = el; e; e = e.parentElement) {
      const p = nums(getComputedStyle(e).backgroundColor);
      if (p.length >= 3 && (p[3] === undefined || p[3] > 0.5)) return p;
    }
    return [255, 255, 255];
  };
  // 눈에 보이는 것만 — opacity:0 은 hover 전용 컨트롤이라 합성 배경이 실제와 다르다.
  const visible = el => {
    for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
    }
    return true;
  };

  const els = [...document.querySelectorAll('body *')].filter(e => {
    const r = e.getBoundingClientRect();
    if (!r.width || !r.height) return false;
    if (!visible(e)) return false;
    return [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  });

  const fails = [], sizes = {};
  let small = 0;
  for (const e of els) {
    const cs = getComputedStyle(e);
    const fs = parseFloat(cs.fontSize);
    sizes[cs.fontSize] = (sizes[cs.fontSize] || 0) + 1;
    if (fs < 12) small++;
    const bg = bgOf(e), fg = nums(cs.color);
    const cr = ratio(fg, bg);
    const large = fs >= 24 || (fs >= 18.66 && parseInt(cs.fontWeight) >= 700);
    const need = large ? 3 : 4.5;
    if (cr < need) fails.push({
      text: e.textContent.trim().slice(0, 24), cls: (e.className || '').toString().slice(0, 40),
      color: cs.color, bg: `rgb(${bg.slice(0, 3).join(',')})`, fontSize: cs.fontSize,
      ratio: +cr.toFixed(2), need,
    });
  }

  // G3 — 한글이 웹폰트로 그려지는가. 폴백과 폭이 같으면 그 폰트에 한글 글리프가 없다는 뜻.
  const ctx = document.createElement('canvas').getContext('2d');
  const w = (t, f) => { ctx.font = f; return +ctx.measureText(t).width.toFixed(2); };
  const KO = '경제현황터미널가나다';
  const stack = getComputedStyle(document.body).fontFamily;
  const hangul = { withStack: w(KO, `16px ${stack}`), fallback: w(KO, '16px serif') };
  const koreanWebfont = [...document.fonts].some(f => f.status === 'loaded' && /pretendard/i.test(f.family))
    && hangul.withStack !== hangul.fallback;

  // G4 — 산문 한 줄의 글자 수. 한글은 30~45자가 적정이고 그 두 배면 줄을 놓친다.
  let maxChars = 0, widest = null;
  for (const e of document.querySelectorAll('p, li, div')) {
    const own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
    if (own.length < 60) continue;
    const r = e.getBoundingClientRect();
    if (r.width < 100 || !visible(e)) continue;
    const fs = parseFloat(getComputedStyle(e).fontSize);
    const chars = Math.round(r.width / (fs * 0.98));   // 한글 1자 ≈ 글자 크기
    if (chars > maxChars) {
      maxChars = chars;
      widest = `${e.tagName.toLowerCase()}.${(e.className || '').toString().trim().split(/\s+/)[0] || '(무클래스)'} ` +
               `${Math.round(r.width)}px/${fs}px — "${own.slice(0, 30)}"`;
    }
  }

  // G5 — 인라인 색. 토큰을 우회하면 테마 전환에서 빠진다(라이트 실패 60곳의 원인이었다).
  const inlineColor = [...document.querySelectorAll('[style]')]
    .filter(e => /(^|;)\s*color\s*:/i.test(e.getAttribute('style'))).length;

  // G6 — 같은 지표가 화면 두 곳에서 다른 자릿수로 나오는가.
  // 천단위 쉼표가 붙은 값만 본다. 쉼표 없는 정수는 개수·연도·순위·날짜 조각이 섞여
  // 들어와 "10: 0/2자리" 같은 오탐만 남긴다(첫 판에서 8건 전부 그것이었다).
  const seen = {};
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = walk.nextNode());) {
    for (const m of n.textContent.match(/\d{1,3}(,\d{3})+(\.\d+)?/g) || []) {
      const body = m.replace(/,/g, '');
      const dec  = (body.split('.')[1] || '').length;
      const key  = String(Math.trunc(parseFloat(body)));   // 정수부가 같은 값끼리 비교
      (seen[key] = seen[key] || new Set()).add(dec);
    }
  }
  const decimalClashes = Object.entries(seen).filter(([, s]) => s.size > 1).map(([k, s]) => `${k}: ${[...s].sort().join('/')}자리`);

  return {
    textEls: els.length,
    contrastFails: fails.length, worst: fails.sort((a, b) => a.ratio - b.ratio).slice(0, 8),
    smallTextRatio: +(small / (els.length || 1)).toFixed(3), smallCount: small,
    sizes: Object.entries(sizes).sort((a, b) => b[1] - a[1]),
    koreanWebfont, hangul,
    maxCharsPerLine: maxChars, widestSample: widest,
    inlineColor,
    decimalClashes: decimalClashes.slice(0, 8),
  };
}

// ── 러너 ────────────────────────────────────────────────────────────────────
const browser = await chromium.launch();
const results = [];
let failed = 0;

for (const page of PAGES) {
  for (const theme of ['light', 'dark']) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const p = await ctx.newPage();
    // 테마는 로드 전에 심는다 — 전환 직후는 JS 가 인라인으로 칠한 색이 아직 옛 테마다.
    await p.addInitScript(t => { try { localStorage.setItem('econ_theme', t); } catch {} }, theme);
    await p.goto(`${BASE}/index.html?p=${page}`, { waitUntil: 'networkidle' });
    await p.waitForTimeout(3500);

    const got = await p.evaluate(collect);
    const actualTheme = await p.evaluate(() => document.documentElement.classList.contains('light') ? 'light' : 'dark');
    const bad = [];
    if (got.contrastFails > LIMITS.contrastFails)   bad.push(`G1 대비 미달 ${got.contrastFails}곳`);
    if (got.smallTextRatio > LIMITS.smallTextRatio) bad.push(`G2 12px 미만 ${(got.smallTextRatio * 100).toFixed(1)}%`);
    if (!got.koreanWebfont)                          bad.push('G3 한글 웹폰트 미로드');
    if (got.maxCharsPerLine > LIMITS.maxCharsPerLine) bad.push(`G4 줄길이 ${got.maxCharsPerLine}자`);
    // G6 은 아직 경고다 — 원인(js/app1.js:154 fmtNum 이 trailing zero 를 지운다)은
    // 밝혀졌지만 지표별 자릿수 테이블로 호출처를 모으는 P1-3 이 남아 있다.
    // 그 작업이 끝나면 아래 한 줄을 bad.push 로 올린다.
    const warn = got.decimalClashes.length ? [`G6 자릿수 불일치 ${got.decimalClashes.length}건 (P1-3 미구현)`] : [];

    results.push({ page, theme: actualTheme, ...got, bad, warn });
    if (bad.length) failed++;
    await ctx.close();
  }
}
await browser.close();

for (const r of results) {
  const mark = r.bad.length ? 'FAIL' : 'PASS';
  console.log(`\n[${mark}] ${r.page} / ${r.theme} — 텍스트 요소 ${r.textEls}`);
  console.log(`  G1 대비 미달 ${r.contrastFails}  G2 12px미만 ${(r.smallTextRatio * 100).toFixed(1)}% (${r.smallCount})  ` +
              `G3 한글웹폰트 ${r.koreanWebfont ? 'O' : 'X'}  G4 줄길이 ${r.maxCharsPerLine}자  G5 인라인색 ${r.inlineColor}`);
  if (r.worst.length) {
    console.log('  대비 미달:');
    for (const w of r.worst) console.log(`    ${w.ratio}:1 (필요 ${w.need}) ${w.fontSize} ${w.color} on ${w.bg} — "${w.text}" .${w.cls}`);
  }
  if (r.maxCharsPerLine > LIMITS.maxCharsPerLine) console.log(`  가장 긴 줄: ${r.widestSample}`);
  if (r.decimalClashes.length) console.log(`  자릿수 불일치: ${r.decimalClashes.join(', ')}`);
  if (r.warn.length) console.log(`  경고 ${r.warn.join(' · ')}`);
  if (r.bad.length) console.log(`  → ${r.bad.join(' · ')}`);
}

console.log(`\n${failed ? `FAIL — ${failed}/${results.length} 조합이 기준 미달` : `PASS — ${results.length}개 조합 전부 통과`}`);
process.exit(failed ? 1 : 0);
