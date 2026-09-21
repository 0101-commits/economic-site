// 조작·전환 게이트 — 2026-09-21 기획(docs/superpowers/specs/2026-09-21-interaction-ux-plan-design.md)의 통과선.
// 가독성 게이트(readability/mobile-readability/uxgates)와 겹치지 않는 축만 잰다.
//
//   G10  유휴 화면이 멈춘다        — 10초 동안 DOM 변경 ≤250건 · 300ms 조용 구간 ≥4
//   G11  보기 전환이 주소에 남는다 — 등록된 조작 100% 가 주소를 바꾸고, 그 주소로 다시 열면 같은 상태
//   G12  누를 것이 충분히 크다     — 실효 타깃(elementFromPoint) min<24px: 390 은 0% · 1440 은 ≤10%
//   G13  모르는 주소에 말을 건다   — 없는 ?p= 값이면 안내 문구 + 복구 버튼
//   G14  정렬이 보인다             — 정렬 가능한 th 의 ::after 표식 100%
//   G15  말이 사전 안에 있다       — 해독 키 없는 약어(OW/UW/N)·장식 이모지·장식 붙은 표기 0
//   G16  옮기는 것은 링크다        — 화면을 옮기는 컨트롤 100% 가 a[href]
//
// 벤치 근거(2026-09-19 아카이브): 유휴 20초 조용 구간 토스 18 · 네이버 14 · 우리(개편 전) 0.
// 화면 안 조작의 주소 반영 네이버 9/20 · 토스 7/23 · 우리(개편 전) 0/19.
// 실효 타깃 min<24px 네이버 모바일 17.9% · 우리(개편 전) 모바일 56.4%.
//
// usage: node tests/ui/interaction.mjs [--base=http://127.0.0.1:8080/index.html]
import { chromium } from 'playwright';

const arg = (k, d) => {
  const hit = process.argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};
const BASE = arg('base', 'http://127.0.0.1:8080/index.html');
const url = q => BASE + (q ? (BASE.includes('?') ? '&' : '?') + q : '');

const LIMITS = { idleMutations: 250, idleQuietWindows: 4, idleSeconds: 10 };

// 등록된 보기 전환 — [화면, 축, 누를 것, 기대값(없으면 '바뀌기만 하면 통과')]
const VIEWS = [
  { page: 'market',  axis: 't', pick: `#page-market .tab-btn`, nth: 2 },
  { page: 'equity',  axis: 'f', pick: `#market-equity .tab-btn`, text: 'KOSDAQ', expect: 'kosdaq' },
  { page: 'equity',  axis: 'r', pick: `#market-equity .eq-unit-btn`, nth: 2 },
  { page: 'macro',   axis: 'v', pick: `#macroViewToggle button`, nth: 1, expect: 'topic' },
  { page: 'macro',   axis: 'f', pick: `.econ-catchips button`, nth: 2 },
  { page: 'merlens', axis: 'f', pick: `[data-mer-filter="crossed"]`, expect: 'crossed' },
];

const wait = (p, ms) => p.waitForTimeout(ms);

async function open(browser, q, viewport) {
  const ctx = await browser.newContext({
    viewport: viewport || { width: 1440, height: 900 },
    isMobile: !!viewport && viewport.width < 500,
    hasTouch: !!viewport && viewport.width < 500,
    locale: 'ko-KR', timezoneId: 'Asia/Seoul',
  });
  const page = await ctx.newPage();
  await page.goto(url(q), { waitUntil: 'domcontentloaded', timeout: 60000 });
  await wait(page, 6000);
  return { ctx, page };
}

// ── G10 유휴 ──────────────────────────────────────────────────────────────────
async function gateIdle(browser) {
  const { ctx, page } = await open(browser, 'p=dashboard');
  const r = await page.evaluate(async (sec) => {
    let total = 0; const gaps = []; let last = performance.now();
    const tally = {};
    const mo = new MutationObserver(muts => {
      const now = performance.now(); gaps.push(now - last); last = now;
      for (const m of muts) {
        total++;
        const el = m.target.nodeType === 3 ? m.target.parentElement : m.target;
        if (!el || !el.tagName) continue;
        const k = el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(/\s+/)[0] : '');
        tally[k] = (tally[k] || 0) + 1;
      }
    });
    mo.observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true });
    await new Promise(r => setTimeout(r, sec * 1000));
    mo.disconnect();
    return {
      total, quiet: gaps.filter(g => g > 300).length, longest: Math.round(Math.max(0, ...gaps)),
      top: Object.entries(tally).sort((a, b) => b[1] - a[1]).slice(0, 3),
    };
  }, LIMITS.idleSeconds);
  await ctx.close();

  const pass = r.total <= LIMITS.idleMutations && r.quiet >= LIMITS.idleQuietWindows;
  console.log(`G10 유휴 ${LIMITS.idleSeconds}초 — 변경 ${r.total}건(한도 ${LIMITS.idleMutations}) · 300ms 조용 구간 ${r.quiet}회(하한 ${LIMITS.idleQuietWindows}) · 최장 정적 ${r.longest}ms  ${pass ? 'PASS' : 'FAIL'}`);
  if (!pass) console.log('   최다 변경:', r.top.map(([k, v]) => `${k} ${v}`).join(' · '));
  return pass;
}

// ── G11 주소 ──────────────────────────────────────────────────────────────────
async function gateViewParams(browser) {
  let ok = true;
  for (const v of VIEWS) {
    const { ctx, page } = await open(browser, 'p=' + v.page);
    let line = `G11 ${v.page}.${v.axis}`;
    try {
      const before = new URL(page.url()).searchParams.get(v.axis);
      const loc = v.text
        ? page.locator(v.pick, { hasText: v.text }).first()
        : page.locator(v.pick).nth(v.nth ?? 0);
      await loc.scrollIntoViewIfNeeded({ timeout: 8000 });
      await loc.click({ timeout: 8000 });
      await wait(page, 1500);

      const after = new URL(page.url()).searchParams.get(v.axis);
      const changed = after != null && after !== before;
      const expected = v.expect ? after === v.expect : true;

      // 그 주소를 새로 열면 같은 상태인가 — 화면이 주소를 실제로 되살리는지가 본 검사다.
      const shared = await open(browser, new URL(page.url()).searchParams.toString());
      await wait(shared.page, 2500);
      const restored = await shared.page.evaluate(([pg, ax]) => {
        const spec = (window.ECON_VIEW || {})[pg];
        if (!spec || !spec[ax] || !spec[ax].get) return null;
        return spec[ax].get();
      }, [v.page, v.axis]);
      const restoredOk = restored != null && String(restored) === String(after);
      await shared.ctx.close();

      const pass = changed && expected && restoredOk;
      ok = ok && pass;
      line += ` — 주소 ${before ?? '(없음)'} → ${after ?? '(없음)'}${v.expect ? ` (기대 ${v.expect})` : ''} · 복원 ${restored ?? '(못 읽음)'}  ${pass ? 'PASS' : 'FAIL'}`;
    } catch (e) {
      ok = false;
      line += ` — 측정 실패: ${String(e).split('\n')[0].slice(0, 90)}  FAIL`;
    }
    console.log(line);
    await ctx.close();
  }
  return ok;
}

// ── G12 실효 타깃 ─────────────────────────────────────────────────────────────
// 박스 크기가 아니라 elementFromPoint 로 "실제로 눌리는 범위"를 잰다(::after 확장이 반영된다).
async function gateHitArea(browser) {
  let ok = true;
  for (const [w, h, limit] of [[390, 844, 0], [1440, 900, 10]]) {
    const { ctx, page } = await open(browser, 'p=dashboard', { width: w, height: h });
    const r = await page.evaluate(() => {
      const vis = e => {
        const b = e.getBoundingClientRect(), s = getComputedStyle(e);
        return b.width > 2 && b.height > 2 && b.top >= 0 && b.bottom <= innerHeight
          && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
      };
      const rows = [];
      const list = [...document.querySelectorAll('a[href],button,[role=button],[role=tab],summary,input,select')].filter(vis).slice(0, 400);
      for (const e of list) {
        const b = e.getBoundingClientRect();
        const cx = b.x + b.width / 2, cy = b.y + b.height / 2;
        const reach = (dx, dy) => {
          let got = 0;
          for (let d = 0; d <= 16; d += 2) {
            const el = document.elementFromPoint(cx + dx * (b.width / 2 + d), cy + dy * (b.height / 2 + d));
            if (el && (el === e || e.contains(el) || el.contains(e))) got = d; else break;
          }
          return got;
        };
        const padX = Math.min(reach(1, 0), reach(-1, 0));
        const padY = Math.min(reach(0, 1), reach(0, -1));
        rows.push({
          lab: (e.getAttribute('aria-label') || e.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 28),
          m: Math.min(b.width + padX * 2, b.height + padY * 2),
        });
      }
      const small = rows.filter(x => x.m < 24);
      return { n: rows.length, pct: rows.length ? +(100 * small.length / rows.length).toFixed(1) : 0, worst: small.slice(0, 4) };
    });
    await ctx.close();
    const pass = r.pct <= limit;
    ok = ok && pass;
    console.log(`G12 ${w} 실효 타깃 min<24px — ${r.pct}% (${r.n}개 중, 한도 ${limit}%)  ${pass ? 'PASS' : 'FAIL'}`);
    if (!pass) console.log('   ', r.worst.map(x => `${x.lab || '(무라벨)'} ${x.m}px`).join(' · '));
  }
  return ok;
}

// ── G13 모르는 주소 ───────────────────────────────────────────────────────────
async function gateUnknownPage(browser) {
  const { ctx, page } = await open(browser, 'p=nosuchpage_gate');
  const r = await page.evaluate(() => {
    const n = document.getElementById('econUnknownPage');
    return n ? { text: (n.innerText || '').replace(/\s+/g, ' ').trim(), acts: n.querySelectorAll('button').length } : null;
  });
  await ctx.close();
  const pass = !!r && r.text.length > 0 && r.acts >= 1;
  console.log(`G13 모르는 주소 안내 — ${r ? `"${r.text.slice(0, 40)}" 버튼 ${r.acts}개` : '없음'}  ${pass ? 'PASS' : 'FAIL'}`);
  return pass;
}

// ── G14 정렬 표식 ─────────────────────────────────────────────────────────────
async function gateSortMarker(browser) {
  let ok = true;
  for (const pg of ['investor', 'equity', 'merlens']) {
    const { ctx, page } = await open(browser, 'p=' + pg);
    const r = await page.evaluate(() => {
      const ths = [...document.querySelectorAll('th[aria-sort]')];
      const marked = ths.filter(e => {
        const c = getComputedStyle(e, '::after').content;
        return c && c !== 'none' && c !== 'normal';
      });
      return { n: ths.length, marked: marked.length };
    });
    await ctx.close();
    const pass = r.n === 0 || r.marked === r.n;
    ok = ok && pass;
    console.log(`G14 ${pg} 정렬 표식 — ${r.marked}/${r.n}  ${pass ? 'PASS' : 'FAIL'}`);
  }
  return ok;
}

// ── G15 말 사전 ───────────────────────────────────────────────────────────────
// 해독 키가 화면에 없는 약어와, 같은 말 앞에 붙은 장식 글리프를 막는다. 국기는 국가를 가리키는 정보라 센다.
async function gateVocabulary(browser) {
  let ok = true;
  for (const pg of ['dashboard', 'macro', 'merlens']) {
    const { ctx, page } = await open(browser, 'p=' + pg);
    const r = await page.evaluate(() => {
      const labels = [...document.querySelectorAll('a,button,[role=button],[role=tab]')]
        .filter(e => e.getBoundingClientRect().width > 2)
        .map(e => (e.getAttribute('aria-label') || e.innerText || '').replace(/\s+/g, ' ').trim())
        .filter(Boolean);
      const RE_ABBR = /(^|\s)(OW|UW)(\s|$)|^N$/;
      const RE_DECO = /[\u{1F300}-\u{1F5FF}\u{1F900}-\u{1FAFF}\u{1F680}-\u{1F6FF}⚙↻]/u;
      const RE_FLAG = /[\u{1F1E6}-\u{1F1FF}]/u;
      const abbr = labels.filter(t => RE_ABBR.test(t));
      const deco = labels.filter(t => RE_DECO.test(t) && !RE_FLAG.test(t));
      return { abbr: [...new Set(abbr)].slice(0, 4), deco: [...new Set(deco)].slice(0, 4) };
    });
    await ctx.close();
    const pass = r.abbr.length === 0 && r.deco.length === 0;
    ok = ok && pass;
    console.log(`G15 ${pg} 말 사전 — 약어 ${r.abbr.length} · 장식 글리프 ${r.deco.length}  ${pass ? 'PASS' : 'FAIL'}`);
    if (!pass) console.log('   ', JSON.stringify([...r.abbr, ...r.deco].slice(0, 5)));
  }
  return ok;
}

// ── G16 이동은 링크 ───────────────────────────────────────────────────────────
async function gateNavLinks(browser) {
  let ok = true;
  for (const pg of ['dashboard', 'equity', 'macro']) {
    const { ctx, page } = await open(browser, 'p=' + pg);
    const r = await page.evaluate(() => {
      const sel = '[data-goto],[data-page],[onclick*="showPage"],[onclick*="gotoCanonical"],'
                + '[onclick*="econNav"],[onclick*="tickerClick"],[onclick*="navigateToDetail"]';
      const nav = [...document.querySelectorAll(sel)].filter(e => e.getBoundingClientRect().width > 2);
      const bad = nav.filter(e => e.tagName !== 'A' || !e.getAttribute('href'));
      return { n: nav.length, bad: bad.length, sample: bad.slice(0, 3).map(e => e.tagName + ':' + (e.getAttribute('onclick') || '').slice(0, 36)) };
    });
    await ctx.close();
    const pass = r.bad === 0;
    ok = ok && pass;
    console.log(`G16 ${pg} 이동 컨트롤 링크 — ${r.n - r.bad}/${r.n}  ${pass ? 'PASS' : 'FAIL'}`);
    if (!pass) console.log('   ', r.sample.join(' · '));
  }
  return ok;
}

const browser = await chromium.launch({ headless: true });
const results = [
  await gateIdle(browser),
  await gateViewParams(browser),
  await gateHitArea(browser),
  await gateUnknownPage(browser),
  await gateSortMarker(browser),
  await gateVocabulary(browser),
  await gateNavLinks(browser),
];
await browser.close();
const pass = results.every(Boolean);
console.log(pass ? '\n조작·전환 게이트 PASS' : '\n조작·전환 게이트 FAIL');
process.exit(pass ? 0 : 1);
