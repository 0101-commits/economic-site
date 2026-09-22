// 구조 통일 게이트 — 2026-09-21 기획(docs/superpowers/specs/2026-09-21-structure-consistency-design.md)의 통과선.
// P0 에서 실제로 고친 축만 잰다. 아직 안 고친 축(표 규격·차트 규격)은 기획서에 남겨 두고 여기 넣지 않는다 —
// 통과할 수 없는 기준을 게이트에 올리면 게이트 전체가 무의미해진다.
//
//   S10  같은 지표는 한 표기       — econFmt 가 내는 값과 화면 값이 어긋나지 않는다(FX 표 기준)
//   S13  천단위 구분기호            — 정수부 4자리 이상 수치에 콤마가 붙는다(연도·날짜 제외)
//   S15  레지스트리 표기 커버리지   — 지표 행의 decimals 100% (데이터셋 묶음 행은 제외)
//   S16  52주 범위는 실측값         — 현재가가 52주 고·저 범위 안에 있다(하드코딩 상수 금지)
//   S17  퍼센트 자릿수              — 한 화면의 % 표기가 2종 이하(4% · 4.1% · 0.977% 혼재 금지)
//   S18  미노출 지표 0              — 수집만 하고 어느 화면에도 없는 지표가 없다
//   S19  화면 머리 한 벌             — 열 화면 모두 첫 줄이 `nav.page-toc` + 보이는 화면 이름
//   S20  탭 부품 한 벌               — 한 묶음이 chip 과 tabs 를 섞지 않고, chip 은 tablist 가 아니다
//   S21  차트 범례 규칙              — 이름 붙은 계열 2개 이상이면 범례가 보인다
//   S22  안 열린 화면의 차트 0       — 지금 화면 밖 캔버스에 새로 그려진 차트가 없다
//
// usage: node tests/ui/structure.mjs [--base=http://127.0.0.1:8080/index.html]
import { chromium } from 'playwright';

const arg = (k, d) => {
  const hit = process.argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};
const BASE = arg('base', 'http://127.0.0.1:8080/index.html');
const url = q => BASE + (q ? (BASE.includes('?') ? '&' : '?') + q : '');

async function open(browser, q) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ko-KR', timezoneId: 'Asia/Seoul' });
  const page = await ctx.newPage();
  await page.goto(url(q), { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(7000);
  return { ctx, page };
}

// ── S10 표기 일치 ─────────────────────────────────────────────────────────────
// 상태(fxPairs)와 화면(표)이 같은 시점을 보여주는가. 예전엔 data.json 적용 경로가 표를 다시
// 그리지 않아 상태는 8.7226 인데 표는 870.00(= 8.70×100)이었다.
async function gateFormatMatch(browser) {
  const { ctx, page } = await open(browser, 'p=market&t=fx');
  const r = await page.evaluate(() => {
    if (typeof fxPairs === 'undefined') return { err: 'fxPairs 없음' };
    const rows = [...document.querySelectorAll('#fxTable tr')];
    const out = [];
    fxPairs.forEach((p, i) => {
      const cell = rows[i] && rows[i].cells[1];
      if (!cell) return;
      const shown = parseFloat(cell.innerText.replace(/,/g, ''));
      const state = parseFloat(String(p.cur).replace(/,/g, '')) * (p.displayMult || 1);
      out.push({ pair: p.pair, shown, state, ok: Math.abs(shown - state) < Math.max(0.01, state * 0.0001) });
    });
    return { rows: out };
  });
  await ctx.close();
  if (r.err) { console.log('S10 표기 일치 — ' + r.err + '  FAIL'); return false; }
  const bad = r.rows.filter(x => !x.ok);
  const pass = r.rows.length > 0 && bad.length === 0;
  console.log(`S10 표기 일치(FX 표 ↔ 상태) — ${r.rows.length - bad.length}/${r.rows.length}  ${pass ? 'PASS' : 'FAIL'}`);
  if (!pass) bad.forEach(x => console.log(`    ${x.pair}: 화면 ${x.shown} vs 상태 ${x.state}`));
  return pass;
}

// ── S13 천단위 구분기호 ───────────────────────────────────────────────────────
async function gateThousandSep(browser) {
  let ok = true;
  for (const pg of ['dashboard', 'equity', 'realestate', 'merlens']) {
    const { ctx, page } = await open(browser, 'p=' + pg);
    const r = await page.evaluate(() => {
      // 값이 사는 자리에서만 센다. 첫 판에서는 문서 전체를 훑어 'ECOS:404Y014 · 월간 · 202608' 같은
      // 출처·기간 코드가 천단위 누락으로 잡혔다 — 그건 수치가 아니라 식별자다(검사기 오탐).
      const cells = [...document.querySelectorAll(
        'td, .econ-num, .econ-numcell, .econ-stat__val, .econ-row__val, .kpi-card .econ-stat__value')];
      let want = 0, got = 0;
      const miss = [];
      for (const el of cells) {
        if (!el.getBoundingClientRect().width) continue;
        const raw = (el.innerText || '').trim();
        if (!raw) continue;
        const m = raw.match(/(?:^|[\s(])(\d{4,}(?:\.\d+)?)(?=$|[\s)원%주건])/);
        if (!m) continue;
        const int = m[1].split('.')[0];
        if (+int >= 1900 && +int <= 2100) continue;          // 연도
        if (/^(19|20)\d{4}$/.test(int)) continue;             // YYYYMM 기간 코드
        want++;
        if (raw.includes(',')) got++; else if (miss.length < 4) miss.push(raw.slice(0, 40));
      }
      return { want, got, miss };
    });
    await ctx.close();
    const ratio = r.want ? r.got / r.want : 1;
    const pass = ratio >= 0.95;
    ok = ok && pass;
    console.log(`S13 ${pg} 천단위 — ${r.got}/${r.want} (${(ratio * 100).toFixed(0)}%)  ${pass ? 'PASS' : 'FAIL'}`);
    if (!pass) console.log('    누락 예:', JSON.stringify(r.miss));
  }
  return ok;
}

// ── S15 레지스트리 표기 커버리지 ──────────────────────────────────────────────
async function gateRegistryCoverage(browser) {
  const { ctx, page } = await open(browser, 'p=dashboard');
  const r = await page.evaluate(() => {
    const R = window.ECON_IND;
    if (!R) return { err: 'ECON_IND 없음' };
    // 데이터셋 묶음(kospi_movers 같은 행)은 지표가 아니라 자릿수가 없다 — data 경로가 배열류인 행을 제외한다.
    const rows = R.rows.filter(x => x.tier != null && x.asset && !/movers|indices$|indicators$|mood$/.test(x.id));
    const withDec = rows.filter(x => x.decimals != null);
    const noDec = rows.filter(x => x.decimals == null).map(x => x.id);
    return { total: rows.length, dec: withDec.length, noDec: noDec.slice(0, 6) };
  });
  await ctx.close();
  if (r.err) { console.log('S15 레지스트리 — ' + r.err + '  FAIL'); return false; }
  const pct = r.total ? r.dec / r.total : 0;
  const pass = pct >= 0.99;
  console.log(`S15 레지스트리 decimals — ${r.dec}/${r.total} (${(pct * 100).toFixed(0)}%)  ${pass ? 'PASS' : 'FAIL'}`);
  if (!pass) console.log('    누락:', JSON.stringify(r.noDec));
  return pass;
}

// ── S16 52주 범위 ─────────────────────────────────────────────────────────────
// 현재가가 52주 고·저 사이에 있어야 한다. 하드코딩 상수를 쓰면 이 검사가 깨진다
// (실측 2026-09-21: 100 JPY/KRW 현재가 872 인데 '52주 저가'가 920 이었다).
async function gateRange52(browser) {
  const { ctx, page } = await open(browser, 'p=market&t=fx');
  const r = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#fxTable tr')];
    const out = [];
    for (const tr of rows) {
      const c = [...tr.cells].map(x => x.innerText.replace(/,/g, '').trim());
      if (c.length < 6) continue;
      const cur = parseFloat(c[1]), hi = parseFloat(c[4]), lo = parseFloat(c[5]);
      if ([cur, hi, lo].some(v => !isFinite(v))) { out.push({ pair: c[0], skip: true }); continue; }
      out.push({ pair: c[0], cur, hi, lo, ok: cur <= hi && cur >= lo });
    }
    return out;
  });
  await ctx.close();
  const judged = r.filter(x => !x.skip);
  const bad = judged.filter(x => !x.ok);
  const pass = judged.length > 0 && bad.length === 0;
  console.log(`S16 52주 범위 — ${judged.length - bad.length}/${judged.length} 정상${r.length - judged.length ? ` (값없음 ${r.length - judged.length})` : ''}  ${pass ? 'PASS' : 'FAIL'}`);
  if (!pass) bad.forEach(x => console.log(`    ${x.pair}: 현재 ${x.cur} · 범위 ${x.lo}~${x.hi}`));
  return pass;
}

// ── S17 퍼센트 자릿수 ─────────────────────────────────────────────────────────
// 한 화면 안에서 같은 성격의 % 가 4% · 4.1% · 5.29% · 0.977% 로 갈리면 훑어 읽을 수 없다.
async function gatePercentDecimals(browser) {
  let ok = true;
  for (const pg of ['merlens', 'macro']) {
    const { ctx, page } = await open(browser, 'p=' + pg);
    const r = await page.evaluate(() => {
      const cells = [...document.querySelectorAll('td, .econ-num, .econ-numcell, .econ-stat__unit')]
        .map(e => (e.innerText || '').trim())
        .filter(t => /^[\d,.()+-]*\d%$/.test(t));
      const dec = {};
      cells.forEach(t => {
        const n = t.replace(/[()%\s,+-]/g, '').split('.');
        const d = n[1] ? n[1].length : 0;
        dec[d] = (dec[d] || 0) + 1;
      });
      return { total: cells.length, kinds: Object.keys(dec).length, dec, sample: cells.slice(0, 6) };
    });
    await ctx.close();
    const pass = r.total === 0 || r.kinds <= 2;   // 0자리(정수 %)와 2자리 공존까지는 허용
    ok = ok && pass;
    console.log(`S17 ${pg} % 자릿수 — ${r.total}개 중 ${r.kinds}종 ${JSON.stringify(r.dec)}  ${pass ? 'PASS' : 'FAIL'}`);
    if (!pass) console.log('    예:', JSON.stringify(r.sample));
  }
  return ok;
}

// ── S18 수집만 하고 화면 없는 지표 ────────────────────────────────────────────
// 매일 받아오면서 어디에도 안 보이는 데이터가 남아 있으면 그건 만든 적 없는 화면과 같다.
async function gateHiddenIndicators(browser) {
  const { ctx, page } = await open(browser, 'p=dashboard');
  const r = await page.evaluate(() => {
    const R = window.ECON_IND;
    if (!R) return { err: 'ECON_IND 없음' };
    const hidden = R.rows.filter(x => x.onScreen === false && !x.collectOnly).map(x => x.id);
    return { hidden };
  });
  await ctx.close();
  if (r.err) { console.log('S18 미노출 지표 — ' + r.err + '  FAIL'); return false; }
  const pass = r.hidden.length === 0;
  console.log(`S18 수집만 하고 화면 없는 지표 — ${r.hidden.length}건  ${pass ? 'PASS' : 'FAIL'}`);
  if (!pass) console.log('   ', JSON.stringify(r.hidden.slice(0, 8)));
  return pass;
}


// ── S19 화면 머리 한 벌 ───────────────────────────────────────────────────────
// 실측(2026-09-22): 열 화면이 정확히 반반으로 갈려 있었다 — 다섯은 `nav.page-toc` 로 화면
// 이름이 눈에 보였고, 나머지 다섯은 `h2.sr-only` 라 읽기 도구에만 이름이 있었다.
// 화면을 옮겼을 때 "여기가 어디인지"를 눈으로 확인할 수 있는 화면과 없는 화면이 섞여 있었다.
async function gatePageHead(browser) {
  const pages = ['dashboard','market','macro','realestate','equity','investor','calendar','merlens','notes','study'];
  let ok = true;
  for (const p of pages) {
    const { ctx, page } = await open(browser, 'p=' + p);
    const r = await page.evaluate((pid) => {
      const root = document.getElementById('page-' + pid);
      if (!root) return { err: '화면 없음' };
      const first = [...root.children].find(e => { const q = e.getBoundingClientRect(); return q.width > 0 && q.height > 0; });
      const toc = root.querySelector(':scope > nav.page-toc');
      const h = toc && toc.querySelector('.page-toc-h');
      const vis = h && h.getBoundingClientRect().height > 0;
      return { firstIsToc: !!(first && first === toc), title: h ? (h.textContent || '').trim() : null, vis: !!vis };
    }, p);
    await ctx.close();
    const good = !r.err && r.firstIsToc && r.vis && !!r.title;
    if (!good) ok = false;
    console.log(`S19 ${p} 화면 머리 — ${r.err || ((r.firstIsToc ? '첫 줄 목차' : '첫 줄이 목차가 아님') + ' · 이름 ' + (r.title || '없음'))}  ${good ? 'PASS' : 'FAIL'}`);
  }
  return ok;
}

// ── S20 탭 부품 한 벌 ─────────────────────────────────────────────────────────
// `.tab-btn` 은 두 부품에 붙는다 — 화면 내용을 바꾸는 2차 탭(seed-tabs__trigger)과
// 대상·기간을 고르는 칩(seed-chip__root). 한 묶음 안에서 둘이 섞이면 안 되고,
// 칩 묶음은 tablist 가 아니다(칩은 aria-pressed 로 말한다).
async function gateTabParts(browser) {
  const pages = ['dashboard','market','macro','realestate','equity','investor','calendar','merlens','notes','study'];
  let ok = true, groups = 0, bad = [];
  for (const p of pages) {
    const { ctx, page } = await open(browser, 'p=' + p);
    const r = await page.evaluate((pid) => {
      const root = document.getElementById('page-' + pid);
      if (!root) return [];
      const vis = el => { const q = el.getBoundingClientRect(); return q.width > 0 && q.height > 0; };
      const seen = new Map();
      [...root.querySelectorAll('.tab-btn')].filter(vis).forEach(b => {
        const w = b.parentElement;
        if (!seen.has(w)) seen.set(w, { chip: 0, tabs: 0, bare: 0, role: w.getAttribute('role'), id: w.id || (w.className || '').slice(0, 20) });
        const g = seen.get(w);
        if (b.classList.contains('seed-chip__root')) g.chip++;
        else if (b.classList.contains('seed-tabs__trigger')) g.tabs++;
        else g.bare++;
      });
      return [...seen.values()];
    }, p);
    await ctx.close();
    r.forEach(g => {
      groups++;
      const mixed = [g.chip, g.tabs, g.bare].filter(n => n > 0).length > 1;
      const chipAsTablist = g.chip > 0 && g.role === 'tablist';
      if (mixed || chipAsTablist) { ok = false; bad.push(`${p}/${g.id} ${JSON.stringify(g)}`); }
    });
  }
  console.log(`S20 탭 부품 한 벌 — 묶음 ${groups}개 중 섞임 ${bad.length}건  ${ok ? 'PASS' : 'FAIL'}`);
  bad.slice(0, 6).forEach(b => console.log('   ', b));
  return ok;
}

// ── S21 차트 범례 / S22 안 열린 화면의 차트 ───────────────────────────────────
// S21: 계열이 2개 이상인데 범례를 숨기면 점선·삼각점이 무엇인지 화면 어디에도 없다
//      (메르 렌즈 패널 8개가 계열 3~6개인데 전부 숨김이었다).
// S22: 어느 화면을 열든 차트 7개가 항상 생성됐다 — 캔버스가 0개인 분석 노트에서도.
//      부팅 때 홈이 잠깐 활성인 동안 만들어지는 것(2개)까지가 허용선이다.
async function gateChartSpec(browser) {
  const pages = ['dashboard','market','macro','realestate','equity','investor','calendar','merlens','notes','study'];
  let ok = true;
  for (const p of pages) {
    const { ctx, page } = await open(browser, 'p=' + p);
    const r = await page.evaluate((pid) => {
      const root = document.getElementById('page-' + pid);
      const reg = (typeof charts !== 'undefined') ? charts : (window.charts || {});
      const noLegend = [], offPage = [];
      Object.keys(reg).forEach(k => {
        const c = reg[k];
        if (!c || !c.config || !c.canvas) return;
        const inPage = !!(root && root.contains(c.canvas));
        if (!inPage) { offPage.push(k); return; }
        const named = ((c.data && c.data.datasets) || []).filter(d => d && d.label).length;
        const lg = c.options && c.options.plugins && c.options.plugins.legend;
        const shown = lg ? lg.display !== false : true;
        if (named >= 2 && !shown) noLegend.push(k + '(' + named + '계열)');
      });
      return { noLegend, offPage };
    }, p);
    await ctx.close();
    const legendOk = r.noLegend.length === 0;
    const offOk = r.offPage.length <= 2;
    if (!legendOk || !offOk) ok = false;
    console.log(`S21/S22 ${p} — 범례 빠진 다계열 ${r.noLegend.length}건 · 화면 밖 차트 ${r.offPage.length}개(한도 2)  ${legendOk && offOk ? 'PASS' : 'FAIL'}`);
    if (!legendOk) console.log('   ', r.noLegend.join(', '));
    if (!offOk) console.log('   ', r.offPage.join(', '));
  }
  return ok;
}

const browser = await chromium.launch({ headless: true });
const results = [
  await gateFormatMatch(browser),
  await gateThousandSep(browser),
  await gateRegistryCoverage(browser),
  await gateRange52(browser),
  await gatePercentDecimals(browser),
  await gateHiddenIndicators(browser),
  await gatePageHead(browser),
  await gateTabParts(browser),
  await gateChartSpec(browser),
];
await browser.close();
const pass = results.every(Boolean);
console.log(pass ? '\n구조 통일 게이트 PASS' : '\n구조 통일 게이트 FAIL');
process.exit(pass ? 0 : 1);
