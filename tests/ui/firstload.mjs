// 첫 도착 게이트 — data.json 을 4초 늦춰 '딥링크로 곧장 연 화면이 자료 도착 뒤 차트를 그리는가'를 잰다.
//
//   node tests/ui/firstload.mjs                 # 7화면 · 1440
//   node tests/ui/firstload.mjs --delay=6000
//   node tests/ui/firstload.mjs --only=history  # 이력 분리(history.json 늦게 옴 · 404) 두 경우만
//
// 전제: python -m http.server 8080 --bind 127.0.0.1
//
// 왜 — 로컬은 data.json(3.6MB)이 빌더(showPage +50ms)보다 먼저 와서 재현되지 않고, 라이브(GitHub Pages)는
// 늦게 온다. 2026-09-29 라이브 실측: ?p=equity 두 차트가 20초 뒤에도 '데이터 추가 필요', 원자재 탭 차트 6개도 같은 뿌리.
// loadRealData 의 활성 화면 재렌더가 두 번째 갱신부터만 돌았던 것이 원인이었다. 이 게이트는 그 경로를 느린 망으로 고정한다.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { chromium } from 'playwright';

const arg = (k, d) => { const hit = process.argv.find(a => a.startsWith(`--${k}=`)); return hit ? hit.slice(k.length + 3) : d; };
const BASE = arg('base', 'http://127.0.0.1:8080');
const DELAY = +arg('delay', 4000);
const ONLY = arg('only', '');
const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCREENS = ['p=dashboard', 'p=equity', 'p=macro', 'p=market&t=fx', 'p=market&t=commodity', 'p=investor', 'p=realestate'];

const browser = await chromium.launch();
let failed = 0;
for (const q of (ONLY === 'history' ? [] : SCREENS)) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ko-KR', timezoneId: 'Asia/Seoul' });
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', e => { if (!/oapi\.map\.naver|maps\.js/.test(e.stack || '')) errs.push(String(e.message).slice(0, 100)); });
  await page.route('**/data.json*', async route => { await new Promise(r => setTimeout(r, DELAY)); await route.continue(); });
  await page.goto(`${BASE}/?${q}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(DELAY + 6000);
  const r = await page.evaluate(() => {
    const vis = e => !!e.offsetParent;
    const pg = document.querySelector('.page.active');
    const cs = [...pg.querySelectorAll('canvas')].filter(vis);
    const empty = cs.filter(c => { const o = c.parentElement && c.parentElement.querySelector('.no-data-overlay'); return !c.getAttribute('width') || (o && vis(o) && o.getBoundingClientRect().height > 0); }).map(c => c.id);
    const lead = pg.querySelector('.econ-lead');
    return { canv: cs.length, empty, lead: !!lead && !/자료 없음/.test(lead.innerText) };
  });
  const bad = [];
  if (r.empty.length) bad.push('빈 차트 ' + r.empty.join(','));
  if (!r.lead) bad.push('결론 줄 없음/자료 없음');
  if (errs.length) bad.push('콘솔 오류 ' + errs[0]);
  if (bad.length) failed++;
  console.log(`${bad.length ? 'FAIL' : 'PASS'} ${q.padEnd(24)} 캔버스 ${r.canv}  ${bad.join(' · ')}`);
  await ctx.close();
}

// ── 이력 분리(A14) — data.json 은 계열마다 끝 400점, 그 앞 5년은 history.json 이다. 두 경우를 잰다.
//   late: history.json 을 DELAY 만큼 늦춰, 그 전에 연 지수 모달이 도착 뒤 5년으로 다시 그려지는가(요청은 1회).
//   404 : history.json 이 없어도 오류 없이 꼬리만으로 메인 차트를 그리는가.
// 분리 전 저장소에서도 돌도록 data.json 응답을 꼬리 400점 + historyVersion 으로 바꾸고, history.json 은
// 디스크 파일이 있으면 그것을, 없으면 원본 data.json 의 전체 이력으로 만든다.
const TAIL = 400;
const histBody = fs.existsSync(path.join(ROOT, 'history.json'))
  ? fs.readFileSync(path.join(ROOT, 'history.json'), 'utf8')
  : (d => JSON.stringify({ lastUpdated: d.lastUpdated, history: d.history }))(JSON.parse(fs.readFileSync(path.join(ROOT, 'data.json'), 'utf8')));
for (const mode of ['late', '404']) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ko-KR', timezoneId: 'Asia/Seoul' });
  const page = await ctx.newPage();
  const errs = [];
  let histReqs = 0;
  page.on('pageerror', e => { if (!/oapi\.map\.naver|maps\.js/.test(e.stack || '')) errs.push(String(e.message).slice(0, 100)); });
  await page.route('**/data.json*', async route => {
    const resp = await route.fetch();
    const d = await resp.json();
    for (const m of Object.values(d.history || {})) for (const k of Object.keys(m)) m[k] = m[k].slice(-TAIL);
    d.historyVersion = d.historyVersion || d.lastUpdated;
    await route.fulfill({ response: resp, json: d });
  });
  await page.route('**/history.json*', async route => {
    histReqs++;
    if (mode === '404') return route.fulfill({ status: 404, body: 'not found' });
    await new Promise(r => setTimeout(r, DELAY));
    await route.fulfill({ status: 200, contentType: 'application/json', body: histBody });
  });
  await page.goto(`${BASE}/?p=dashboard`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForFunction(() => window._lastRealDataTs, null, { timeout: 30000 });
  const kospi = () => page.evaluate(() => ((((_latestDataForIndicators || {}).history || {}).indices || {}).KOSPI || []).length);
  const pts = id => page.evaluate(id => { const c = window.Chart && Chart.getChart(id); return c ? c.data.labels.length : 0; }, id);
  const bad = [];
  let info;
  if (mode === 'late') {
    await page.evaluate(() => showGlobalIndexDetail('KOSPI'));
    const n0 = await kospi(), m0 = await pts('reHistChart');
    await page.waitForTimeout(DELAY + 5000);
    const n1 = await kospi(), m1 = await pts('reHistChart');
    if (n0 > TAIL) bad.push(`도착 전 KOSPI ${n0}점(꼬리가 아님)`);
    if (n1 <= 1000) bad.push(`도착 뒤 KOSPI ${n1}점`);
    if (!(m1 > m0)) bad.push(`지수 모달을 다시 안 그림 ${m0}→${m1}칸`);
    info = `KOSPI ${n0}→${n1}점 · 지수 모달 ${m0}→${m1}칸`;
  } else {
    await page.waitForTimeout(3000);
    const n = await kospi(), main = await pts('mainChart');
    if (!n || n > TAIL) bad.push(`KOSPI ${n}점`);
    if (!main) bad.push('메인 차트 비어 있음');
    info = `KOSPI ${n}점 · 메인 차트 ${main}칸`;
  }
  if (histReqs !== 1) bad.push(`history.json 요청 ${histReqs}회(페이지당 1회여야 함)`);
  if (errs.length) bad.push('콘솔 오류 ' + errs[0]);
  if (bad.length) failed++;
  console.log(`${bad.length ? 'FAIL' : 'PASS'} ${('history ' + mode).padEnd(24)} ${info}  ${bad.join(' · ')}`);
  await ctx.close();
}
await browser.close();
console.log(failed ? `\nFAIL — ${failed}건` : '\nPASS — 첫 도착(느린 자료) 7화면 + 이력 분리 2건 통과');
process.exit(failed ? 1 : 0);
