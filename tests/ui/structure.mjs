// 구조 통일 게이트 — 2026-09-21 기획(docs/superpowers/specs/2026-09-21-structure-consistency-design.md)의 통과선.
// P0 에서 실제로 고친 축만 잰다. 아직 안 고친 축(표 규격·차트 규격)은 기획서에 남겨 두고 여기 넣지 않는다 —
// 통과할 수 없는 기준을 게이트에 올리면 게이트 전체가 무의미해진다.
//
//   S10  같은 지표는 한 표기       — econFmt 가 내는 값과 화면 값이 어긋나지 않는다(FX 표 기준)
//   S13  천단위 구분기호            — 정수부 4자리 이상 수치에 콤마가 붙는다(연도·날짜 제외)
//   S15  레지스트리 표기 커버리지   — 지표 행의 decimals 100% (데이터셋 묶음 행은 제외)
//   S16  52주 범위는 실측값         — 현재가가 52주 고·저 범위 안에 있다(하드코딩 상수 금지)
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

const browser = await chromium.launch({ headless: true });
const results = [
  await gateFormatMatch(browser),
  await gateThousandSep(browser),
  await gateRegistryCoverage(browser),
  await gateRange52(browser),
];
await browser.close();
const pass = results.every(Boolean);
console.log(pass ? '\n구조 통일 게이트 PASS' : '\n구조 통일 게이트 FAIL');
process.exit(pass ? 0 : 1);
