// 컴포넌트 규격 게이트 — 2026-09-24 6차 기획(docs/superpowers/specs/2026-09-24-component-spec-consistency-design.md §4·§8).
// 규칙이 문장으로만 있고 부품이 없으면 위젯마다 각자 만든다 — 그 결과를 여기서 센다.
//
//   S27  위젯 제목 한 벌        — 보이는 h3.widget-title 의 (크기·굵기·색) 조합 1종, 굵기 700
//   S28  제목 줄 도구 차례       — 별 → 새로고침 → 접기, 제목 줄 끝에 모여 있다
//   S29  실행 버튼 높이          — 고르기·행/카드 감싸개·지도 마커를 뺀 버튼의 높이 ∈ {28, 32, 36}
//   S30  고르기 칩 규격          — 칩(aria-pressed 가 있거나 seed-chip)은 높이 32, aria-pressed 를 가진다
//   S31  탭은 라인탭 한 벌       — tablist 안 탭은 seed-tabs__trigger, 칩 부품·aria-pressed 섞임 0
//   S32  골라진 칩이 보인다      — 한 묶음에서 pressed=true 와 false 의 계산 스타일이 다르다
//   S33  숫자 블록               — KPI·안쪽 카드 값 크기 ∈ {14, 18, 24}, 등락은 값 아래, 카드 상자 2벌(A·B)
//   S34  표                      — 머리 글자 한 벌(정의표 제외), 빈칸 문자는 — 하나(– · N/A 0)
//   S35  간격                    — 위젯 padding 한 값, 격자(g-*) gap 한 값
//   S36  화면 머리               — page-toc 가 보이고(390 포함), 머리(page-toc~탭 줄)가 ≤ 117px(57+16+44)
//
// usage: node tests/ui/components.mjs [--base=http://127.0.0.1:8080/index.html] [--only=S27,S28]
import { chromium } from 'playwright';

const arg = (k, d) => {
  const hit = process.argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};
const BASE = arg('base', 'http://127.0.0.1:8080/index.html');
const ONLY = (arg('only', '') || '').split(',').filter(Boolean);
const url = q => BASE + (q ? (BASE.includes('?') ? '&' : '?') + q : '');

const ROUTES = ['dashboard', 'equity', 'market', 'market&t=rate', 'market&t=bond', 'market&t=commodity',
  'macro', 'macro&v=topic', 'calendar', 'realestate', 'investor', 'merlens', 'notes', 'study'];

function probe() {
  const act = document.querySelector('.page.active');
  if (!act) return { err: '활성 화면 없음' };
  const vis = el => { const b = el.getBoundingClientRect(); return b.width > 0 && b.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const name = el => {
    const t = (el.getAttribute('aria-label') || el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 18);
    return (el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + [...el.classList].slice(0, 2).join('.')) + '「' + t + '」';
  };
  const out = {};

  // S27
  const titles = [...act.querySelectorAll('h3.widget-title')].filter(vis);
  const combos = {};
  titles.forEach(t => { const c = getComputedStyle(t); const k = `${c.fontSize}/${c.fontWeight}/${c.color}`; (combos[k] = combos[k] || []).push(name(t)); });
  out.S27 = { combos: Object.fromEntries(Object.entries(combos).map(([k, v]) => [k, v.length])), bad: Object.keys(combos).filter(k => k.split('/')[1] !== '700').map(k => k + ' ' + combos[k].slice(0, 3).join(' ')) };

  // S28
  const cat = e => e.classList.contains('econ-fav') ? 1 : e.classList.contains('w-toggle-btn') ? 3
    : e.matches('[data-chart-refresh], button[aria-label*="새로고침"]') ? 2 : 0;
  const s28 = [];
  titles.forEach(t => {
    // 화면에 보이는 차례 = (CSS order, DOM 차례). 메타가 나중에 끼어들어도 order 가 도구를 끝에 둔다.
    const kids = [...t.children].map((e, i) => ({ e, i, o: parseInt(getComputedStyle(e).order, 10) || 0 }))
      .sort((x, y) => x.o - y.o || x.i - y.i).map(x => x.e);
    const tools = kids.map(cat);
    const firstTool = tools.findIndex(c => c > 0);
    if (firstTool < 0) return;
    const seq = tools.slice(firstTool);
    const sorted = seq.every((c, i) => c > 0 && (i === 0 || c >= seq[i - 1]));
    if (!sorted) s28.push(name(t) + ' ' + seq.join(''));
  });
  out.S28 = { bad: s28 };

  // 고르기 판정
  // 칩 = 고르는 버튼. seed-chip 모양이어도 묶음(role=group) 밖에서 aria-pressed 가 없으면 고르기가 아니다(브리핑 칩=이동).
  const isChip = b => b.hasAttribute('aria-pressed') || (b.classList.contains('seed-chip__root') && !!b.closest('[role=group]'));
  const isTab = b => b.getAttribute('role') === 'tab' || b.closest('[role=tablist]');
  const inRowOrCard = b => b.closest('tr, .clickable-card, .kpi-clickable, .kpi-card, .leaflet-container, svg, .econ-search, .themed-modal, summary');
  const buttons = [...act.querySelectorAll('button')].filter(vis);

  // S29
  const s29 = {};
  buttons.forEach(b => {
    if (isChip(b) || isTab(b) || inRowOrCard(b)) return;
    if (b.classList.contains('btn-plain') && !b.classList.contains('w-toggle-btn') && !b.classList.contains('econ-failed__act')) return; // 감싸개(행·카드·제목 클릭)
    if (b.classList.contains('seed-toggle-button')) return;
    if (b.classList.contains('seed-list-item__root')) return;          // 목록 행(행 전체 누르기)
    const h = Math.round(b.getBoundingClientRect().height);
    if (h > 56) return;                                                 // 카드형 누르기 영역(요약 카드)은 버튼 규격 밖
    if (![28, 32, 36].includes(h)) (s29[h] = s29[h] || []).push(name(b));
  });
  out.S29 = { bad: Object.entries(s29).map(([h, v]) => `${h}px ×${v.length}: ${v.slice(0, 4).join(' ')}`), n: Object.values(s29).reduce((a, v) => a + v.length, 0) };

  // S30
  const s30 = { h: {}, aria: [] };
  buttons.filter(b => isChip(b) && !isTab(b) && !inRowOrCard(b) && !b.classList.contains('seed-toggle-button') && !b.classList.contains('econ-fav')).forEach(b => {
    const h = Math.round(b.getBoundingClientRect().height);
    if (h !== 32) (s30.h[h] = s30.h[h] || []).push(name(b));
    if (!b.hasAttribute('aria-pressed')) s30.aria.push(name(b));
  });
  out.S30 = { bad: Object.entries(s30.h).map(([h, v]) => `${h}px ×${v.length}: ${v.slice(0, 4).join(' ')}`).concat(s30.aria.length ? ['aria-pressed 없음 ×' + s30.aria.length + ': ' + s30.aria.slice(0, 4).join(' ')] : []) };

  // S31
  const s31 = [];
  act.querySelectorAll('[role=tablist]').forEach(tl => {
    if (!vis(tl)) return;
    const tabs = [...tl.querySelectorAll('[role=tab]')];
    if (tl.className.includes('seed-chip-tabs')) s31.push(name(tl) + ' 필 탭');
    tabs.forEach(t => {
      if (!t.classList.contains('seed-tabs__trigger')) s31.push(name(t) + ' 라인탭 아님');
      if (t.hasAttribute('aria-pressed')) s31.push(name(t) + ' aria-pressed');
    });
  });
  out.S31 = { bad: s31 };

  // S32
  const s32 = [];
  const groups = new Map();
  buttons.filter(b => b.hasAttribute('aria-pressed') && !isTab(b) && !b.classList.contains('econ-fav') && !b.classList.contains('seed-toggle-button')).forEach(b => {
    const p = b.parentElement; if (!groups.has(p)) groups.set(p, []); groups.get(p).push(b);
  });
  const sig = b => { const c = getComputedStyle(b); const l = b.querySelector('.seed-chip__label') || b; const cl = getComputedStyle(l); return [c.backgroundColor, c.borderColor, cl.fontWeight, cl.color].join('|'); };
  groups.forEach((bs, p) => {
    const on = bs.filter(b => b.getAttribute('aria-pressed') === 'true');
    const off = bs.filter(b => b.getAttribute('aria-pressed') === 'false');
    if (!on.length || !off.length) return;
    if (sig(on[0]) === sig(off[0])) s32.push(name(p) + ' ' + name(on[0]));
  });
  out.S32 = { bad: s32 };

  // S33 — 숫자 블록
  const s33 = [];
  const valEls = [...act.querySelectorAll('.econ-stat__val, .econ-num, .kpi-card [id^="reKpi"], .kpi-card [id^="usKpi"]')].filter(vis);
  valEls.forEach(v => { const fs = Math.round(parseFloat(getComputedStyle(v).fontSize)); if (![14, 18, 24].includes(fs)) s33.push(name(v) + ' ' + fs + 'px'); });
  act.querySelectorAll('.econ-stat, .kpi-card').forEach(c => {
    if (!vis(c)) return;
    const v = c.querySelector('.econ-stat__val, .econ-num'); const ch = c.querySelector('.econ-stat__chg, .econ-num__chg');
    if (v && ch && vis(v) && vis(ch) && ch.getBoundingClientRect().top < v.getBoundingClientRect().bottom - 2) s33.push(name(c) + ' 등락이 값 아래가 아님');
  });
  const boxes = {};
  [...act.querySelectorAll('.kpi-card, .clickable-card, .econ-inner')].filter(vis).forEach(c => {
    const cs = getComputedStyle(c); const k = cs.padding + '/' + cs.borderTopLeftRadius;
    (boxes[k] = boxes[k] || []).push(name(c));
  });
  out.S33 = { bad: s33, boxes: Object.fromEntries(Object.entries(boxes).map(([k, v]) => [k, v.length])) };

  // S34 — 표 머리·빈칸
  const s34 = []; const heads = {};
  act.querySelectorAll('table').forEach(t => {
    if (!vis(t) || !t.tHead) return;
    const th = t.tHead.querySelector('th'); if (!th) return;
    const c = getComputedStyle(th); const k = Math.round(parseFloat(c.fontSize)) + '/' + c.fontWeight;
    (heads[k] = heads[k] || []).push(name(t));
    t.querySelectorAll('td').forEach(td => { const x = td.innerText.trim(); if (x === '–' || x === 'N/A' || x === '-') s34.push(name(t) + ' 빈칸 「' + x + '」'); });
  });
  if (Object.keys(heads).length > 1) s34.push('머리 ' + JSON.stringify(Object.fromEntries(Object.entries(heads).map(([k, v]) => [k, v.length + ' ' + v[0]]))));
  out.S34 = { bad: [...new Set(s34)].slice(0, 8), heads };

  // S35 — 간격
  const pads = {}, gaps = {};
  act.querySelectorAll('.widget').forEach(w => { if (!vis(w) || w.classList.contains('w-collapsed') || w.classList.contains('econ-flush')) return; const p = getComputedStyle(w).padding; pads[p] = (pads[p] || 0) + 1; });
  act.querySelectorAll('[class*="g-"]').forEach(g => {
    if (!vis(g) || ![...g.classList].some(c => /^g-(\d|side|auto)/.test(c))) return;
    if (![...g.children].some(ch => ch.matches('.widget, .kpi-card:not(.pad-8):not(.pad-8-10), section, .home-sec'))) return;   // 위젯을 품은 격자만(안쪽 상자 B 격자 제외)
    const k = getComputedStyle(g).columnGap; gaps[k] = (gaps[k] || 0) + 1;
  });
  out.S35 = { pads, gaps, bad: [].concat(Object.keys(pads).length > 1 ? ['padding ' + JSON.stringify(pads)] : [], Object.keys(gaps).length > 1 ? ['gap ' + JSON.stringify(gaps)] : []) };

  // S36 — 화면 머리
  const toc = act.querySelector('nav.page-toc');
  const s36 = [];
  if (!toc || !vis(toc)) s36.push('page-toc 안 보임');
  else {
    const top = toc.getBoundingClientRect().top;
    let bottom = toc.getBoundingClientRect().bottom;
    // 머리 = page-toc 바로 다음에 이어지는 탭 줄(있으면)까지
    let nx = toc.nextElementSibling;
    while (nx && !vis(nx)) nx = nx.nextElementSibling;
    if (nx && (nx.getAttribute('role') === 'tablist' || nx.querySelector(':scope > [role=tablist], :scope > .seed-tabs__root'))) bottom = nx.getBoundingClientRect().bottom;
    const h = Math.round(bottom - top);
    if (h > 117) s36.push('머리 ' + h + 'px');   // 목차 57 + 간격 16 + 탭 한 줄 44 — 기획 §4.9 의 101 은 간격을 빠뜨린 값
  }
  out.S36 = { bad: s36 };
  return out;
}

const browser = await chromium.launch({ headless: true });
const VIEWS = [{ w: 1440, h: 900, tag: '' }, { w: 390, h: 844, tag: '@390', mobile: true }];
const agg = {};
for (const V of VIEWS) {
const ctx = await browser.newContext({ viewport: { width: V.w, height: V.h }, isMobile: !!V.mobile, hasTouch: !!V.mobile, locale: 'ko-KR', timezoneId: 'Asia/Seoul' });
for (const r0 of (V.mobile ? ROUTES.filter(x => !x.includes('&')) : ROUTES)) {
  const r = r0 + V.tag;
  const page = await ctx.newPage();
  await page.goto(url('p=' + r0), { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(6000);
  const res = await page.evaluate(probe);
  await page.close();
  if (res.err) { console.log(r, res.err); continue; }
  for (const [g, v] of Object.entries(res)) {
    // 버튼 높이 규격(S29·S30)은 1440 기준 — 390 은 손가락 타깃 규칙(M3)이 따로 있다
    if (V.mobile && !['S27', 'S28', 'S31', 'S32', 'S34', 'S35', 'S36'].includes(g)) continue;
    (agg[g] = agg[g] || []).push({ r, v });
  }
}
await ctx.close();
}
await browser.close();

let allPass = true;
for (const g of ['S27', 'S28', 'S29', 'S30', 'S31', 'S32', 'S33', 'S34', 'S35', 'S36']) {
  if (ONLY.length && !ONLY.includes(g)) continue;
  const rows = agg[g] || [];
  let bad = rows.filter(x => x.v.bad && x.v.bad.length);
  if (g === 'S27') {
    const all = {};
    rows.forEach(x => Object.entries(x.v.combos).forEach(([k, n]) => { all[k] = (all[k] || 0) + n; }));
    const one = Object.keys(all).length === 1 && Object.keys(all)[0].split('/')[1] === '700';
    console.log(`S27 위젯 제목 조합 ${Object.keys(all).length}종 ${JSON.stringify(all)}  ${one ? 'PASS' : 'FAIL'}`);
    if (!one) allPass = false;
    continue;
  }
  if (g === 'S33') {
    const all = {};
    rows.forEach(x => Object.entries(x.v.boxes || {}).forEach(([k, n]) => { all[k] = (all[k] || 0) + n; }));
    console.log('    카드 상자 조합 ' + Object.keys(all).length + '종 ' + JSON.stringify(all));
    if (Object.keys(all).length > 2) bad = bad.concat([{ r: '전체', v: { bad: ['상자 ' + Object.keys(all).length + '종 > 2'] } }]);
  }
  if (g === 'S35') {
    // 화면마다가 아니라 뷰포트 전체에서 한 값이어야 한다
    for (const tag of ['', '@390']) {
      const P = {}, G = {};
      rows.filter(x => tag ? x.r.endsWith(tag) : !x.r.includes('@')).forEach(x => { Object.entries(x.v.pads).forEach(([k, n]) => P[k] = (P[k] || 0) + n); Object.entries(x.v.gaps).forEach(([k, n]) => G[k] = (G[k] || 0) + n); });
      console.log(`    ${tag || '@1440'} padding ${JSON.stringify(P)} gap ${JSON.stringify(G)}`);
      if (Object.keys(P).length > 1 || Object.keys(G).length > 1) bad = bad.concat([{ r: tag || '@1440', v: { bad: ['뷰포트 전체 ' + Object.keys(P).length + '/' + Object.keys(G).length + '종'] } }]);
    }
  }
  const pass = bad.length === 0;
  if (!pass) allPass = false;
  console.log(`${g} — 위반 화면 ${bad.length}/${rows.length}  ${pass ? 'PASS' : 'FAIL'}`);
  bad.forEach(x => x.v.bad.slice(0, 6).forEach(m => console.log(`    [${x.r}] ${m}`)));
}
console.log(allPass ? '\n컴포넌트 게이트 PASS' : '\n컴포넌트 게이트 FAIL');
process.exit(allPass ? 0 : 1);
