// 화면 품질 게이트 공용 부품 — overflow.mjs · longdata.mjs · matrix.mjs 가 같이 쓴다.
// 인자는 `--키=값` 과 `--키 값` 둘 다 받는다. 환경변수 UI_URL 이 --url 의 기본값이다.
import { chromium } from 'playwright';

const argv = process.argv.slice(2);
export const opt = (k, d) => {
  const i = argv.findIndex(a => a === `--${k}` || a.startsWith(`--${k}=`));
  if (i < 0) return d;
  if (argv[i].includes('=')) return argv[i].split('=').slice(1).join('=');
  const nx = argv[i + 1];
  return nx && !nx.startsWith('--') ? nx : true;
};

export const WIDTHS = String(opt('widths', '360,390,768,1440')).split(',').map(Number);
export const THEMES = String(opt('themes', 'light,dark')).split(',');
export const WAIT = Number(opt('wait', 2500));

// 새 화면 층 5개 + 기존 index.html 의 ?p= 12종. 주소로 자동 고른다(5173=새 층, 그 밖=기존).
// 알림 v2: 사건 탭 · 채널 탭 · 지표 상세(#/i/kospi) + 벨 시트를 연 채로(?bell=1) 본 상세.
// 국내 상승 · 하락 보기(v=gainers · losers)는 표 열이 많아 PC 둘째 줄 4칸에서 잘리던 자리라 따로 찍는다.
// 거시(주제 한 격자 · 나라 꼬리표)와 렌즈 지표 상세(#/i/us10y — 렌즈 패널 · 흐름 차트 기준선)도 본다.
export const NEXT_PATHS = ['#/', '#/market', '#/market?a=kr&v=gainers', '#/market?a=kr&v=losers', '#/market?a=macro', '#/lens', '#/my', '#/alerts', '#/alerts?v=cond', '#/alerts?v=chan', '#/i/kospi', '#/i/kospi?bell=1', '#/i/us10y'];   // 새 층은 HashRouter
export const LEGACY_PATHS = ['dashboard', 'equity', 'market', 'macro', 'calendar', 'realestate',
  'investor', 'merlens', 'merblog', 'notes', 'study', 'settings'].map(p => `/?p=${p}`);

export function baseUrl() {
  let u = String(opt('url', process.env.UI_URL || 'http://127.0.0.1:5173/next/'));
  if (!u.endsWith('/') && !/\.html?$/.test(u)) u += '/';
  return u;
}
export function paths() {
  const p = opt('paths', '');
  if (p && p !== true) return p.split(',').map(s => s.trim()).filter(Boolean);
  return baseUrl().includes(':5173') ? NEXT_PATHS : LEGACY_PATHS;
}
// 새 층(5173)은 HashRouter 라 '/my' 는 홈이 뜬다 → 자동으로 '#/my' 로 바꾼다.
// Git Bash(MSYS)가 '/my' 를 'C:/Program Files/Git/my' 로 바꿔 넘기는 것도 되돌린다.
export const fullUrl = (base, p) => {
  p = p.replace(/^[A-Za-z]:\/Program Files\/Git/, '');
  if (base.includes(':5173') && p.startsWith('/') && !p.startsWith('/?')) p = '#' + p;
  return p.startsWith('#') ? base + p : new URL(p.replace(/^\//, ''), base).href;
};
export const slug = p => (p.replace(/^#?\//, '').replace(/[?&=\/#]+/g, '-').replace(/^-|-$/g, '') || 'home');

// 폭 × 테마 문맥. 테마는 세 겹으로 건다: 에뮬레이션, 기존 사이트 저장값, 새 층의 data-theme.
export async function newCtx(browser, w, theme) {
  const ctx = await browser.newContext({ viewport: { width: w, height: w < 500 ? 844 : 900 }, colorScheme: theme });
  await ctx.addInitScript(t => {
    try {
      localStorage.setItem('econ_theme', t);
      sessionStorage.setItem('econLockOk_v1', '1');   // PIN 관문 해제(안 풀면 잠긴 화면을 못 잼)
      sessionStorage.setItem('econLockAt_v1', String(Date.now()));   // 해제 시각(5분 안이어야 열린 것으로 본다, lib/pin.ts)
      document.documentElement.setAttribute('data-theme', t);
    } catch (_) {}
  }, theme);
  return ctx;
}

// 페이지 안에서 도는 검사. 위반 = {kind, sel, text, detail}
export function inPage(allowExtra) {
  const out = [];
  const de = document.scrollingElement || document.documentElement;
  if (de.scrollWidth > de.clientWidth) out.push({ kind: 'T1 문서 가로넘침', sel: 'document', text: '', detail: `${de.scrollWidth}>${de.clientWidth}` });

  const allow = ['.ellipsis-ok', ...allowExtra].join(',');
  const path = el => {
    const parts = [];
    for (let n = el; n && n.nodeType === 1 && parts.length < 4; n = n.parentElement) {
      let s = n.tagName.toLowerCase();
      if (n.id) { parts.unshift(s + '#' + n.id); break; }
      const c = typeof n.className === 'string' ? n.className.trim().split(/\s+/).filter(Boolean).slice(0, 2).join('.') : '';
      if (c) s += '.' + c;
      parts.unshift(s);
    }
    return parts.join(' > ');
  };
  const inScroller = el => {
    for (let n = el.parentElement; n; n = n.parentElement) {
      const o = getComputedStyle(n).overflowX;
      if ((o === 'auto' || o === 'scroll') && n.scrollWidth > n.clientWidth) return true;
    }
    return false;
  };
  const NUM = /^[\d,.\-▲▼%]+$/;
  for (const el of document.body.querySelectorAll('*')) {
    if (['SCRIPT', 'STYLE', 'SVG', 'PATH', 'CANVAS', 'NOSCRIPT'].includes(el.tagName.toUpperCase())) continue;
    if (!el.getClientRects().length) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'inline') continue;
    const txt = (el.textContent || '').trim().replace(/\s+/g, ' ');
    const free = !el.closest(allow);
    // T1 요소 넘침(overflow:visible 인데 내용이 상자보다 큼)
    if (free && el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 1 && cs.overflowX === 'visible' && !inScroller(el))
      out.push({ kind: 'T1 요소 넘침', sel: path(el), text: txt.slice(0, 40), detail: `${el.scrollWidth}>${el.clientWidth}` });
    // T2 말줄임으로 실제 잘림
    if (free && cs.textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 1)
      out.push({ kind: 'T2 말줄임 잘림', sel: path(el), text: txt.slice(0, 40), detail: `${el.scrollWidth}>${el.clientWidth}` });
    // T2 숫자 두 줄 꺾임(자식 요소 없는 순수 숫자 글자)
    if (!el.children.length && NUM.test(txt)) {
      // 줄 수 = 글자 상자의 서로 다른 세로 위치 수. 상자 수로 세면 한 줄에 놓인 텍스트 노드 둘(React 의 {값}% = 「3.00」+「%」)을 두 줄로 센다.
      const r = document.createRange(); r.selectNodeContents(el);
      const lines = new Set([...r.getClientRects()].map(x => Math.round(x.top))).size;
      if (lines > 1) out.push({ kind: 'T2 숫자 줄꺾임', sel: path(el), text: txt.slice(0, 40), detail: `${lines}줄` });
    }
  }
  return out;
}

// 주어진 조합 전부를 돌며 위반을 모은다. setup(ctx) 로 route 가로채기 등을 끼울 수 있다.
export async function sweep({ setup, onShot } = {}) {
  const base = baseUrl(), list = paths(), allowExtra = String(opt('allow', '')).split(',').filter(Boolean);
  const browser = await chromium.launch();
  const rows = [];
  for (const theme of THEMES) for (const w of WIDTHS) {
    const ctx = await newCtx(browser, w, theme);
    if (setup) await setup(ctx);
    for (const p of list) {
      const page = await ctx.newPage();
      let v = [], err = null;
      try {
        await page.goto(fullUrl(base, p), { waitUntil: 'load', timeout: 60000 });
        await page.waitForTimeout(WAIT);
        v = await page.evaluate(inPage, allowExtra);
        if (onShot) await onShot(page, { w, theme, p });
      } catch (e) { err = String(e.message || e).split('\n')[0]; }
      rows.push({ w, theme, p, v, err });
      await page.close();
    }
    await ctx.close();
  }
  await browser.close();
  return rows;
}

export function report(rows, title) {
  let bad = 0, errs = 0;
  const seen = new Set();
  console.log(`[${title}] 기준 주소 ${baseUrl()}`);
  for (const r of rows) {
    if (r.err) { errs++; console.log(`  오류  ${r.theme} ${r.w} ${r.p} — ${r.err}`); continue; }
    bad += r.v.length;
    const shown = r.v.filter(x => { const k = r.p + x.kind + x.sel; if (seen.has(k)) return false; seen.add(k); return true; });
    console.log(`  ${r.v.length ? '위반' : '통과'}  ${r.theme} ${String(r.w).padStart(4)} ${r.p} — ${r.v.length}건`);
    for (const x of shown.slice(0, 6)) console.log(`        ${x.kind} | ${x.sel} | 「${x.text}」 | 폭${r.w} ${x.detail}`);
    if (r.v.length && !shown.length) console.log("        (앞선 조합에서 이미 보고한 위반과 같음)");
    if (shown.length > 6) console.log(`        … 이 조합에서 처음 보는 위반 ${shown.length - 6}건 더`);
  }
  const byPath = {};
  for (const r of rows) byPath[r.p] = (byPath[r.p] || 0) + r.v.length;
  console.log('\n경로별 위반 합계(전 폭·테마):', JSON.stringify(byPath));
  console.log(`합계 위반 ${bad}건, 실행 오류 ${errs}건 → ${bad || errs ? '실패(종료 코드 1)' : '통과'}`);
  return bad || errs ? 1 : 0;
}
