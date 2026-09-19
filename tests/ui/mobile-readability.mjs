// 모바일 가독성 게이트 — 기획안(문서 1xWjJ5MM) M1~M7 을 390px 에서 그대로 잰다.
//
//   node tests/ui/mobile-readability.mjs                 # 10페이지 × 라이트/다크 = 20조합
//   node tests/ui/mobile-readability.mjs --page=calendar # 한 페이지만
//   node tests/ui/mobile-readability.mjs --json          # 수치만 JSON 으로
//
// 전제: python -m http.server 8080 --bind 127.0.0.1 (npm run ui:serve)
//
// 왜 이 파일이 따로 있나 — readability.mjs 는 viewport 1440 에 대상이 dashboard,merlens
// 두 개다. 그 둘이 390 에서도 대비 미달 0 인 유일한 페이지라, 나머지 8페이지의 36곳
// (라이트 17 · 다크 19)이 게이트 밖에 있었다. 또 G2 가 「12px 미만」이라 13px 도배는
// 원래 통과한다 — 모바일 본문의 실제 지배값이 그 13px 이다. 데스크톱은 readability.mjs,
// 모바일은 이 파일이 담당한다.

import { chromium } from 'playwright';

const arg = (k, d) => {
  const hit = process.argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};

const BASE   = arg('base', 'http://127.0.0.1:8080');
const W      = Number(arg('w', 390));
const H      = Number(arg('h', 844));
const PAGES  = arg('page', 'dashboard,equity,market,macro,calendar,realestate,investor,notes,study,merlens')
                 .split(',').map(s => s.trim()).filter(Boolean);
const THEMES = arg('theme', 'light,dark').split(',').map(s => s.trim()).filter(Boolean);
const JSON_OUT = process.argv.includes('--json');

// 기준값 — 현재 통과선. 내리려면 근거를 같이 적을 것.
const LIMITS = {
  // M1 은 두 가지를 따로 본다. 하나로는 못 잡는다:
  //  · belowFloor — 모바일 최소 단계(13px) 아래로 내려간 글자. 스케일을 우회한 리터럴이나
  //    t1·t2 에 직접 박힌 recipe 만 여기 걸린다. 0 이어야 한다.
  //  · smallTextRatio — 14px 미만 비율. 13px(xs)은 단위·타임스탬프·표 머리처럼 제자리가
  //    있으므로 0 을 요구하면 거짓이 된다. 라벨이 많은 화면(macro·realestate)의 실측
  //    바닥이 30% 대라 35% 를 통과선으로 둔다. 그 위는 본문이 xs 로 새고 있다는 뜻이다.
  belowFloor:     0,      // M1a 13px 미만 요소 수
  smallTextRatio: 0.35,   // M1b 본문 글자 중 14px 미만으로 그려지는 글자의 비율
  contrastFails:  0,      // M2  WCAG AA (일반 4.5:1 · 큰 글자 3:1)
  tinyTaps:       0,      // M3  탭 타깃 최소변 24px 미만 (WCAG 2.2 2.5.8)
  tableOverflow:  0,      // M4  표 하나가 390 을 넘는 픽셀
  screens:        4.0,    // M5  문서 길이 ÷ 844
  // M6 은 처음엔 '첫 canvas/table 까지의 거리'였는데, 홈의 3줄 요약이나 캘린더 격자처럼
  // canvas 도 table 도 아닌 본문이 첫 화면을 채우는 경우를 「데이터가 없다」로 잘못 셌다.
  // 재는 대상을 바꾼다 — 첫 화면에서 컨트롤(버튼·탭·입력)이 먹는 세로 비율.
  // 그게 실제 결함이다(equity 첫 화면은 지수 6 + 단위 4 + 기간 6 + 유틸 4 = 칩 19개였다).
  // 699 = 844 − 상시 고정 요소 145(헤더 56 + 티커 32 + 하단 내비 57).
  firstScreenControl: 0.40,   // M6  첫 화면 컨트롤 점유 비율
  overflowX:      0,      // M7  가로로 삐져나온 요소 (2026-09-18 감사가 0 으로 만들어 뒀다 — 회귀 방지)
};

// ── 페이지 안에서 도는 측정기 ────────────────────────────────────────────────
function collect(a) {
  const vw = a[0], vh = a[1];

  const lum = (r, g, b) => {
    const f = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  // color-mix() 는 브라우저가 `color(srgb 0.07 0.37 0.80)` 로 직렬화한다 — 0~1 스케일이라
  // 그대로 읽으면 거의 검정으로 잡혀 대비가 1.2:1 처럼 나온다(readability.mjs 와 같은 함정).
  const nums = s => {
    const v = (String(s).match(/-?\d+(\.\d+)?/g) || []).map(Number);
    return /^color\(/i.test(String(s).trim()) ? v.slice(0, 3).map(x => x * 255).concat(v.slice(3)) : v;
  };
  const ratio = (fg, bg) => {
    const x = Math.max(lum(...fg.slice(0, 3)), lum(...bg.slice(0, 3)));
    const y = Math.min(lum(...fg.slice(0, 3)), lum(...bg.slice(0, 3)));
    return (x + 0.05) / (y + 0.05);
  };
  const bgOf = el => {
    for (let e = el; e; e = e.parentElement) {
      const p = nums(getComputedStyle(e).backgroundColor);
      if (p.length >= 3 && (p[3] === undefined || p[3] > 0.5)) return p;
    }
    return [255, 255, 255];
  };
  const visible = el => {
    for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
    }
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  const active = document.querySelector('.page.active') || document.body;

  // M1 · M2 — 자기 글자를 가진 요소만 센다(부모가 자식 글자를 다시 세지 않게)
  const els = [...active.querySelectorAll('*')].filter(e => {
    if (!visible(e)) return false;
    return [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  });

  // 읽을거리인가 — 이모지·화살표·구분자 하나짜리는 글자 크기 비율에서 뺀다.
  // realestate 의 💡 25개, macro 의 · 같은 것이 M1b 를 2~5%p 씩 밀어올려
  // 「본문이 작다」와 「아이콘이 많다」가 한 숫자에 섞여 있었다. 대비(M2)는 아이콘도
  // 보여야 하므로 거기서는 빼지 않는다.
  // 컨트롤 안 글자는 본문이 아니다 — 칩·탭·링크 라벨은 13px 이 제자리고, 크기를 키우면
  // 첫 화면이 다시 길어진다(M5·M6 와 충돌). 바닥(M1a)과 대비(M2)에서는 그대로 본다.
  const isControlText = e => !!e.closest('button,a[href],label,[role="tab"],summary,select,option');
  // 「읽는 글」의 정의 = 이어서 읽는 문장. 20자를 경계로 둔다 — 그 아래는 값·라벨·
  // 꼬리표(“· 7개국 · 분기”)이고, 그것들은 13px 이 제자리다. 20자를 넘는 덩어리가
  // 13px 로 나오면 그건 본문이 작은 것이다(study 의 116자 안내문, notes 의 88자 경고).
  const readable = e => {
    const t = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('')
      .replace(/[\p{Extended_Pictographic}\p{Emoji_Presentation}️]/gu, '')
      .replace(/[\s·,.:;/|()[\]{}<>→←↑↓▲▼●○◆◇★☆✕✓~—–-]/g, '');
    return t.length >= 20;
  };

  const sizes = {}, fails = [], tiny = [];
  let small = 0, textCount = 0;
  for (const e of els) {
    const cs = getComputedStyle(e);
    const fs = parseFloat(cs.fontSize);
    sizes[cs.fontSize] = (sizes[cs.fontSize] || 0) + 1;
    // 글자 수로 가중한다 — 요소 수로 세면 "· 7개국" 같은 다섯 글자 꼬리표가
    // 문단 하나와 같은 무게를 갖는다. 재려는 것은 '작은 글씨로 읽는 양'이다.
    const reads = readable(e) && !isControlText(e);
    if (reads) {
      const len = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('').length;
      textCount += len;
      if (fs < 14) small += len;
    }
    if (fs < 13 && reads && tiny.length < 8) tiny.push({
      fontSize: cs.fontSize, text: e.textContent.trim().slice(0, 20),
      cls: (e.className || '').toString().slice(0, 32),
    });
    const bg = bgOf(e), fg = nums(cs.color);
    const cr = ratio(fg, bg);
    const large = fs >= 24 || (fs >= 18.66 && parseInt(cs.fontWeight) >= 700);
    const need = large ? 3 : 4.5;
    if (cr < need) fails.push({
      text: e.textContent.trim().slice(0, 24),
      cls: (e.className || '').toString().slice(0, 40),
      fontSize: cs.fontSize, color: cs.color, bg: `rgb(${bg.slice(0, 3).join(',')})`,
      ratio: +cr.toFixed(2), need,
    });
  }

  // M3 — 탭 타깃. 히트 영역을 ::after 로 넓힌 것은 통과여야 하므로 의사요소까지 본다.
  const taps = [];
  // 남의 위젯(네이버 지도 SDK)이 심는 저작권·약관 링크는 우리 DOM 이 아니다 — 세지 않는다.
  const THIRD_PARTY = '#reRegionNaverMap, .nmap, [class^="nmap"], iframe';
  active.querySelectorAll('button,a[href],input,select,textarea,[role="button"],summary').forEach(e => {
    if (!visible(e)) return;
    if (e.closest(THIRD_PARTY)) return;
    const r = e.getBoundingClientRect();
    let w = r.width, h = r.height;
    for (const pe of ['::after', '::before']) {
      const s = getComputedStyle(e, pe);
      if (s.content === 'none' || s.position !== 'absolute') continue;
      const px = v => (v && v.endsWith('px') ? parseFloat(v) : 0);
      // inset 음수만큼 히트 영역이 커진다 (inset: -10px -2px → 세로 +20, 가로 +4)
      const grow = (t, b) => Math.max(0, -px(t)) + Math.max(0, -px(b));
      h += grow(s.top, s.bottom);
      w += grow(s.left, s.right);
    }
    const min = Math.min(w, h);
    if (min < 24) taps.push({
      sel: e.tagName.toLowerCase() + (e.className && typeof e.className === 'string'
            ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : ''),
      w: Math.round(w), h: Math.round(h), text: (e.textContent || '').trim().slice(0, 16),
    });
  });

  // M4 — 표의 실제 폭. 가로 스크롤 래퍼 안에 있어도 「옆으로 밀어야 읽힌다」는 사실은 같다.
  const tables = [];
  active.querySelectorAll('table').forEach(t => {
    if (!visible(t)) return;
    const over = Math.round(Math.max(t.scrollWidth, t.getBoundingClientRect().width) - vw);
    if (over > 2) tables.push({
      cols: t.querySelector('tr') ? t.querySelector('tr').children.length : 0,
      rows: t.querySelectorAll('tr').length,
      over,
      id: t.id || (t.className || '').toString().trim().split(/\s+/)[0] || '(무명)',
    });
  });

  // M5 · M6 — 길이와 첫 데이터까지의 거리
  const y = e => Math.round(e.getBoundingClientRect().top + window.scrollY);
  // 값 카드도 데이터다 — 차트·표만 세면 KPI 4카드로 시작하는 화면이 "데이터 없음"으로
  // 잡힌다(2026-09-19). 벤치마크의 첫 지수 스트립(네이버 m 142px)도 값 카드다.
  const dataEls = [...active.querySelectorAll('canvas,table,.econ-row,svg,.kpi-card,.econ-stat,.econ-num,.econ-data')]
    .filter(visible).map(y);
  const firstData = dataEls.length ? Math.min(...dataEls) : null;

  // M7 — 가로 넘침 (의도된 가로 스크롤 영역은 뺀다)
  const overflowX = [];
  active.querySelectorAll('*').forEach(e => {
    if (!visible(e)) return;
    const r = e.getBoundingClientRect();
    if (r.width <= vw + 2 && r.right <= vw + 2) return;
    const cs = getComputedStyle(e);
    if (cs.overflowX === 'auto' || cs.overflowX === 'scroll') return;
    if (e.closest('[style*="overflow-x:auto"],[style*="overflow-x: auto"],.g-scroll')) return;
    if (overflowX.length < 8) overflowX.push({
      sel: e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') +
           (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/)[0] : ''),
      w: Math.round(r.width), right: Math.round(r.right),
    });
  });

  // M6 — 컨트롤이 먹는 세로. 같은 줄에 나란히 선 버튼은 한 번만 센다.
  const FIRST = 699;
  let controlPx = 0, firstScreenPx = 0;
  const rows = new Set();
  // 이 저장소에서는 내용 자체가 button 이다 — 표의 행, KPI 카드, 목록 줄 전부.
  // 「모양 유지 리셋」인 .btn-plain 이 그 표식이고, 카드는 키가 크다. 컨트롤만 센다.
  active.querySelectorAll('button,[role="tab"],select,input').forEach(e => {
    if (!visible(e)) return;
    if (e.classList.contains('btn-plain') || e.closest('.kpi-card,.econ-row')) return;
    const r = e.getBoundingClientRect();
    if (r.height > 48) return;                       // 카드·타일은 컨트롤이 아니다
    const top = r.top + window.scrollY;
    const key = Math.round(top / 8);
    if (rows.has(key)) return;
    rows.add(key);
    controlPx += r.height;
    if (top < FIRST) firstScreenPx += Math.min(r.height, FIRST - top);
  });

  const docH = document.documentElement.scrollHeight;
  return {
    textEls: els.length, readableEls: textCount,
    smallCount: small, smallTextRatio: +(small / (textCount || 1)).toFixed(3),
    belowFloor: tiny.length, floorWorst: tiny,
    sizes: Object.entries(sizes).sort((x, z) => z[1] - x[1]).slice(0, 8),
    contrastFails: fails.length, worst: fails.sort((x, z) => x.ratio - z.ratio).slice(0, 6),
    tinyTaps: taps.length, tapWorst: taps.slice(0, 6),
    tableOverflow: tables.reduce((m, t) => Math.max(m, t.over), 0), tables,
    docH, screens: +(docH / vh).toFixed(1),
    firstData,
    overflowX: overflowX.length, overflowWorst: overflowX,
    controlPx: Math.round(controlPx),
    firstScreenControl: +(firstScreenPx / FIRST).toFixed(3), firstScreenPx: Math.round(firstScreenPx),
  };
}

// ── 러너 ────────────────────────────────────────────────────────────────────
const browser = await chromium.launch();
const results = [];
let failed = 0;

for (const page of PAGES) {
  for (const theme of THEMES) {
    const ctx = await browser.newContext({
      viewport: { width: W, height: H }, deviceScaleFactor: 3, isMobile: true, hasTouch: true,
    });
    const p = await ctx.newPage();
    // 테마는 로드 전에 심는다 — 전환 직후는 JS 가 인라인으로 칠한 색이 아직 옛 테마다.
    await p.addInitScript(t => { try { localStorage.setItem('econ_theme', t); } catch {} }, theme);
    await p.goto(`${BASE}/index.html?p=${page}`, { waitUntil: 'networkidle', timeout: 60000 });
    await p.waitForTimeout(3500);

    const got = await p.evaluate(collect, [W, H]);
    const bad = [];
    if (got.belowFloor     > LIMITS.belowFloor)     bad.push(`M1a 13px미만 ${got.belowFloor}곳`);
    if (got.smallTextRatio > LIMITS.smallTextRatio) bad.push(`M1b 14px미만 ${(got.smallTextRatio * 100).toFixed(1)}%`);
    if (got.contrastFails  > LIMITS.contrastFails)  bad.push(`M2 대비 미달 ${got.contrastFails}곳`);
    if (got.tinyTaps       > LIMITS.tinyTaps)       bad.push(`M3 탭타깃 24px미만 ${got.tinyTaps}개`);
    if (got.tableOverflow  > LIMITS.tableOverflow)  bad.push(`M4 표 넘침 ${got.tableOverflow}px`);
    if (got.screens        > LIMITS.screens)        bad.push(`M5 길이 ${got.screens}화면`);
    if (got.firstScreenControl > LIMITS.firstScreenControl) bad.push(`M6 첫화면 컨트롤 ${(got.firstScreenControl * 100).toFixed(0)}%`);
    if (got.overflowX      > LIMITS.overflowX)      bad.push(`M7 가로 넘침 ${got.overflowX}개`);

    results.push({ page, theme, ...got, bad });
    if (bad.length) failed++;
    await ctx.close();
  }
}
await browser.close();

if (JSON_OUT) {
  console.log(JSON.stringify(results, null, 1));
} else {
  for (const r of results) {
    console.log(`\n[${r.bad.length ? 'FAIL' : 'PASS'}] ${r.page} / ${r.theme} — 본문 ${r.readableEls}자/${r.textEls}요소 · 컨트롤 ${r.controlPx}px`);
    console.log(`  M1a ${r.belowFloor}  M1b ${(r.smallTextRatio * 100).toFixed(1)}%(${r.smallCount})  M2 ${r.contrastFails}  M3 ${r.tinyTaps}  ` +
                `M4 ${r.tableOverflow}px  M5 ${r.screens}화면  M6 ${(r.firstScreenControl * 100).toFixed(0)}%(${r.firstScreenPx}px)  M7 ${r.overflowX}`);
    if (r.worst.length) {
      console.log('  대비 미달:');
      for (const w of r.worst) console.log(`    ${w.ratio}:1 (필요 ${w.need}) ${w.fontSize} ${w.color} on ${w.bg} — "${w.text}" .${w.cls}`);
    }
    if (r.floorWorst.length) console.log('  13px 미만: ' + r.floorWorst.map(t => `${t.fontSize} "${t.text}" .${t.cls}`).join(' · '));
    if (r.tapWorst.length) console.log('  작은 탭타깃: ' + r.tapWorst.map(t => `${t.sel} ${t.w}×${t.h}"${t.text}"`).join(' · '));
    if (r.tables.length)   console.log('  표: ' + r.tables.map(t => `${t.id} ${t.cols}열 +${t.over}px`).join(' · '));
    if (r.overflowWorst.length) console.log('  넘침: ' + r.overflowWorst.map(o => `${o.sel} ${o.w}px`).join(' · '));
    if (r.bad.length) console.log(`  → ${r.bad.join(' · ')}`);
  }
}

console.log(`\n${failed ? `FAIL — ${failed}/${results.length} 조합이 기준 미달` : `PASS — ${results.length}개 조합 전부 통과`}`);
process.exit(failed ? 1 : 0);
