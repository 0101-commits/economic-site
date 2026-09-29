// 가독성 게이트 2 — 기획서(Claude Docs c5abb330, 2026-09-29) §8 의 R1~R8 을 14화면에서 잰다.
//
//   node tests/ui/readability2.mjs                      # 14화면 × 1440/390
//   node tests/ui/readability2.mjs --screen=merlens     # 한 화면(이름은 아래 SCREENS 의 key)
//   node tests/ui/readability2.mjs --strict=all         # 전 화면을 통과선으로(P3 완료 뒤)
//
// 전제: python -m http.server 8080 --bind 127.0.0.1
//
// 왜 이 여덟인가 — 2026-09-29 라이브 실측: 첫 화면(900px) 안에 말로 된 결론이 있는 화면이 14개 중 1개(홈),
// 메르 렌즈는 4,913px(5.5화면)·글자색 10종·돌파 지표가 표 맨 아래, 엘니뇨 카드는 1,579px 중 45%가 차트·외부
// 이미지였고 ▲▼ 막대가 둘 다 파랑이었다. 원자재 딥링크는 차트 6개가 비어 있었다. 눈으로 보면 되돌아가므로
// 숫자로 고정한다. STRICT 에 든 화면은 FAIL 이 곧 게이트 실패, 나머지는 측정만 하고 알린다(단계별로 넓힌다).
import { chromium } from 'playwright';

const arg = (k, d) => { const hit = process.argv.find(a => a.startsWith(`--${k}=`)); return hit ? hit.slice(k.length + 3) : d; };
const BASE = arg('base', 'http://127.0.0.1:8080');

// 14화면 — 기획서 §2 실측표와 같은 묶음. lead:false = 데이터 화면이 아니라 결론 줄을 요구하지 않는다(글 찾기·분석 노트).
const SCREENS = {
  'dashboard':        { q: 'p=dashboard' },
  'equity':           { q: 'p=equity' },
  'macro-kr':         { q: 'p=macro' },
  'macro-us':         { q: 'p=macro&t=us' },
  'market-fx':        { q: 'p=market&t=fx' },
  'market-rate':      { q: 'p=market&t=rate' },
  'market-bond':      { q: 'p=market&t=bond' },
  'market-commodity': { q: 'p=market&t=commodity', card: '#ensoCard' },
  'investor':         { q: 'p=investor' },
  'realestate':       { q: 'p=realestate' },
  'calendar':         { q: 'p=calendar' },
  'notes':            { q: 'p=notes', lead: false },
  'merlens':          { q: 'p=merlens' },
  'merlens-search':   { q: 'p=merlens&t=search', lead: false },
};
// 통과선을 강제하는 화면 — P0(2026-09-29) 엘니뇨 카드(원자재 탭) · 메르 렌즈 → P2·P3(같은 날) 전 화면.
// 원자재 탭은 R1·R2·R5·R6 를 카드(#ensoCard) 기준으로 재고, 화면수(R3)는 탭 전체를 잰다.
const STRICT_DEFAULT = Object.keys(SCREENS);
const STRICT = arg('strict', '') === 'all' ? Object.keys(SCREENS) : (arg('strict', '') ? arg('strict', '').split(',') : STRICT_DEFAULT);
const ONLY = arg('screen', '') ? arg('screen', '').split(',') : Object.keys(SCREENS);

const LIMITS = {
  leadMin: 20, leadMax: 90,          // R1 결론 줄 글자 수(부제 .econ-lead__sub 제외)
  leadTop: 900,                      // R1 첫 900px 안
  firstJudgePx: 320,                 // R2 본문 시작 → 첫 판정(결론 줄·상태 배지)
  screensDesktop: 3.5, screensMobile: 3.0,   // R3 (기존 G9 5.5 · M5 4.0 에서 내림)
  colors: 5, sizes: 5,               // R4 첫 900px 안 글자색·크기 종수
  statusMarks: 3,                    // R5 첫 900px 안 critical·warning 배지 + 방향색 강조 글자
  nameRepeat: 3,                     // R6 같은 지표 이름이 첫 900px 안에 나오는 횟수 — 결론 줄·카드·사슬이 한 번씩(기획 ≤2 에서 조정, 근거 아래)
  emptyCanvas: 0,                    // R7 딥링크 8초 뒤 보이는 빈 캔버스
  vocab: 0,                          // R8 말 사전 밖의 판정어·이모지·한자 등급
};
// R6 를 2 가 아니라 3 으로 둔 이유: 골격이 결론 줄(무엇이 넘었나) → 볼 것 카드(얼마나) → 사슬(그래서 어디로) 세 층이라
// 같은 지표가 층마다 한 번씩 정당하게 나온다. 넷째부터가 반복이다. 기획서 §8 에 이 조정을 적었다.

function collect(cardSel) {
  const vis = el => {
    for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
    }
    return true;
  };
  const scope = cardSel ? document.querySelector(cardSel) : document.querySelector('.page.active');
  const pg = document.querySelector('.page.active');
  if (!scope || !pg) return { error: 'no active page' };
  const top0 = scope.getBoundingClientRect().top + scrollY;
  const within = (el, px) => (el.getBoundingClientRect().top + scrollY - top0) < px;
  const textEls = [...scope.querySelectorAll('*')].filter(e => {
    const r = e.getBoundingClientRect();
    return r.width && r.height && vis(e) && e.tagName !== 'CANVAS' && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  });
  const first = textEls.filter(e => within(e, 900));
  // R4 는 '내용 글자'의 색·크기다 — 부품(버튼·탭·칩·아이콘 글꼴)과 상태 배지·콜아웃은 각자 규격(S27~S36 · R5)이 따로 잰다.
  const isControl = e => !!e.closest('button, [role=tab], [role=button], .seed-chip__root, .seed-badge__root, .seed-callout__root, .mat, select, input, .w-fresh-chip');
  const content = first.filter(e => !isControl(e));

  // R1 · R2
  const lead = [...scope.querySelectorAll('.econ-lead')].find(vis) || null;
  const leadText = lead ? [...lead.childNodes].filter(n => !(n.nodeType === 1 && n.classList.contains('econ-lead__sub'))).map(n => n.textContent).join('').replace(/\s+/g, ' ').trim() : '';
  const leadTop = lead ? Math.round(lead.getBoundingClientRect().top + scrollY - top0) : null;
  const judges = [...scope.querySelectorAll('.econ-lead, .seed-badge__root')].filter(vis);
  const firstJudge = judges.length ? Math.min(...judges.map(e => Math.round(e.getBoundingClientRect().top + scrollY - top0))) : null;

  // R4
  const colors = new Set(), sizes = new Set();
  content.forEach(e => { const cs = getComputedStyle(e); colors.add(cs.color); sizes.add(cs.fontSize); });

  // R5 — 배지(critical·warning) + 방향색 **말**(상방·수혜처럼 글자에 색을 입힌 것). 숫자 등락(▲0.3%·+13%)은 값이라 세지 않는다.
  const badges = first.filter(e => /seed-badge__root--tone_(critical|warning)/.test(e.className) || (e.closest && e.closest('.seed-badge__root--tone_critical-variant_weak, .seed-badge__root--tone_warning-variant_weak')));
  const badgeRoots = new Set(badges.map(e => e.closest('.seed-badge__root') || e));
  const isNumeric = t => /^[▲▼△▽+\-−]?\s*[\d,.]+/.test(t) || /^[▲▼△▽]/.test(t);
  const dirTxt = first.filter(e => e.matches('.up-txt, .down-txt, b.up-txt, b.down-txt') && !e.closest('.ticker, .ticker-strip, #tickerStrip, .econ-kpi__c, td') && !isNumeric(e.textContent.trim()));
  const status = badgeRoots.size + dirTxt.length;

  // R6 — 지표 이름 반복: 레지스트리 라벨 + 메르 지표 라벨을 첫 900px 텍스트 요소에서 센다
  const names = new Set();
  try { (window.ECON_IND && window.ECON_IND.all ? window.ECON_IND.all() : []).forEach(r => r.label && names.add(r.label)); } catch (_) {}
  try { ((window._merSignalsData || {}).indicators || []).forEach(i => i.label && names.add(i.label)); } catch (_) {}
  // '라벨로 선' 이름만 센다(글자가 이름과 같은 요소). 문장 속에 든 이름(「KOSPI 추이」·「코스피 기준」)은 반복이 아니라 주어다.
  const rep = {};
  first.forEach(e => {
    const t = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').replace(/\s+/g, ' ').trim();
    if (names.has(t)) rep[t] = (rep[t] || 0) + 1;
  });
  const worstRep = Object.entries(rep).sort((a, b) => b[1] - a[1])[0] || null;

  // R7 — 보이는 캔버스 중 그려지지 않은 것(width 없음) 또는 '데이터 추가 필요' 덧판이 있는 것
  const canv = [...pg.querySelectorAll('canvas')].filter(vis);
  // 덧판(.no-data-overlay)은 숨긴 채 남아 있을 수 있다 — 보이는 덧판만 '빈 차트'다.
  const overlayOn = c => { const o = c.parentElement && c.parentElement.querySelector('.no-data-overlay'); return !!(o && vis(o) && o.getBoundingClientRect().height > 0); };
  const empty = canv.filter(c => !c.getAttribute('width') || +c.getAttribute('width') === 0 || overlayOn(c));

  // R8 — 말 사전: 상태어 {돌파·주시·정상·자료 없음} · 방향어 {상방·하방·혼조} 밖의 판정어, 이모지(국기 제외), 한자 등급.
  // 외부 링크 글자(뉴스 제목)는 남이 쓴 말이라 빼고 잰다.
  const RE_EMOJI = /[\u{1F300}-\u{1F5FF}\u{1F900}-\u{1FAFF}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
  const RE_FLAG = /[\u{1F1E6}-\u{1F1FF}]/u;
  const RE_BAD = /[高中低]|(^|[^A-Za-z])(OW|UW)([^A-Za-z]|$)|판정 불가|호재|악재|혼재|↔/;
  const vocab = [];
  textEls.filter(e => !e.closest('a[href^="http"]')).forEach(e => {
    const t = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').trim();
    if (!t) return;
    const t2 = t.replace(/[☆★✕×]/g, '');   // 위젯 도구(즐겨찾기 별·닫기)는 판정어가 아니다
    if ((RE_EMOJI.test(t2) && !RE_FLAG.test(t2)) || RE_BAD.test(t2)) vocab.push(t.slice(0, 40));
  });

  return {
    h: document.documentElement.scrollHeight, screens: +(document.documentElement.scrollHeight / innerHeight).toFixed(2),
    lead: leadText, leadLen: leadText.length, leadTop, firstJudge,
    colors: colors.size, sizes: sizes.size, sizeList: [...sizes].map(s => parseFloat(s)).sort((a, b) => a - b),
    status, statusEx: [...badgeRoots].slice(0, 3).map(e => e.textContent.trim()).concat(dirTxt.slice(0, 3).map(e => e.textContent.trim())),
    worstRep, emptyCanvas: empty.length, canvases: canv.length,
    vocab: [...new Set(vocab)].slice(0, 6), vocabN: new Set(vocab).size,
  };
}

const browser = await chromium.launch();
let failed = 0, warned = 0;
console.log(`가독성 게이트 2 (R1~R8) — 통과선 강제: ${STRICT.join(', ')}\n`);
for (const key of ONLY) {
  const sc = SCREENS[key];
  if (!sc) { console.log(`?? 모르는 화면 ${key}`); continue; }
  for (const [w, h] of [[1440, 900], [390, 844]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, locale: 'ko-KR', timezoneId: 'Asia/Seoul', isMobile: w < 500, hasTouch: w < 500 });
    const page = await ctx.newPage();
    const errs = [];
    // 남의 스크립트(네이버 지도 SDK 가 localhost 에서 키 검증에 실패해 던지는 것)는 이 화면의 잘못이 아니다
    page.on('pageerror', e => { if (/oapi\.map\.naver\.com|maps\.js/.test(e.stack || '')) return; errs.push(String(e.message).slice(0, 120)); });
    try {
      await page.goto(`${BASE}/?${sc.q}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page.waitForTimeout(8000);   // R7 — 딥링크 8초 뒤
      const r = await page.evaluate(collect, sc.card || null);
      const bad = [];
      if (sc.lead !== false) {
        if (!r.lead) bad.push('R1 결론 줄 없음');
        else if (r.leadTop > LIMITS.leadTop) bad.push(`R1 결론 줄 ${r.leadTop}px (첫 ${LIMITS.leadTop}px 밖)`);
        else if (r.leadLen < LIMITS.leadMin || r.leadLen > LIMITS.leadMax) bad.push(`R1 결론 줄 ${r.leadLen}자 (${LIMITS.leadMin}~${LIMITS.leadMax})`);
        if (r.firstJudge == null) bad.push('R2 첫 판정 없음');
        else if (r.firstJudge > LIMITS.firstJudgePx) bad.push(`R2 첫 판정 ${r.firstJudge}px (상한 ${LIMITS.firstJudgePx})`);
      }
      const capS = w === 1440 ? LIMITS.screensDesktop : LIMITS.screensMobile;
      if (r.screens > capS) bad.push(`R3 화면수 ${r.screens} (상한 ${capS})`);   // 카드 기준 화면(원자재 탭)도 화면수는 탭 전체
      if (r.colors > LIMITS.colors) bad.push(`R4 글자색 ${r.colors}종 (상한 ${LIMITS.colors})`);
      if (r.sizes > LIMITS.sizes) bad.push(`R4 글자크기 ${r.sizes}종 ${JSON.stringify(r.sizeList)} (상한 ${LIMITS.sizes})`);
      if (r.status > LIMITS.statusMarks) bad.push(`R5 상태 표시 ${r.status}개 ${JSON.stringify(r.statusEx)} (상한 ${LIMITS.statusMarks})`);
      if (r.worstRep && r.worstRep[1] > LIMITS.nameRepeat) bad.push(`R6 이름 반복 ${r.worstRep[0]} ${r.worstRep[1]}회 (상한 ${LIMITS.nameRepeat})`);
      if (r.emptyCanvas > LIMITS.emptyCanvas) bad.push(`R7 빈 차트 ${r.emptyCanvas}/${r.canvases}`);
      if (r.vocabN > LIMITS.vocab) bad.push(`R8 말 사전 밖 ${r.vocabN}건 ${JSON.stringify(r.vocab.slice(0, 3))}`);
      if (errs.length) bad.push(`콘솔 오류 ${errs.length}: ${errs[0]}`);
      const strict = STRICT.includes(key);
      const tag = bad.length ? (strict ? 'FAIL' : 'warn') : 'PASS';
      if (bad.length) { if (strict) failed++; else warned++; }
      console.log(`${tag.padEnd(4)} ${key.padEnd(17)} ${w}  화면 ${String(r.screens).padEnd(5)} 결론 ${r.lead ? `${r.leadTop}px·${r.leadLen}자` : '없음'}  판정 ${r.firstJudge ?? '—'}px  색 ${r.colors} 크기 ${r.sizes}  상태 ${r.status}  빈차트 ${r.emptyCanvas}/${r.canvases}  사전 ${r.vocabN}`);
      bad.forEach(b => console.log(`      · ${b}`));
    } catch (e) {
      failed++;
      console.log(`FAIL ${key} ${w} — 측정 실패 ${String(e).split('\n')[0].slice(0, 100)}`);
    }
    await ctx.close();
  }
}
await browser.close();
console.log(failed ? `\nFAIL — 통과선 화면에서 ${failed}건 (측정만 한 화면의 경고 ${warned}건)` : `\nPASS — R1~R8 통과선 화면 통과 (측정만 한 화면의 경고 ${warned}건)`);
process.exit(failed ? 1 : 0);
