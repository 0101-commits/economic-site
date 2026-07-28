// economic-site theme — astryx neutral 기반
//
// 원칙(astryx docs principles/layout/color):
//   · 무채색 spine — 표면·테두리·텍스트는 순수 그레이스케일. 색은 "의미"에만 쓴다.
//   · 색 = 데이터. 등락(up/down), 상태(success/warn/error), 차트 시리즈만 유채색.
//   · accent = 파랑(상호작용 어포던스). neutral 테마의 무채색 accent 대신
//     금융 대시보드의 학습된 "파랑=클릭 가능" 관습을 유지하되 astryx blue 램프에서만 고른다.
//
// build: node node_modules/@astryxdesign/cli/bin/astryx.mjs theme build econ.theme.ts --out dist/econ.css

import {defineTheme} from '@astryxdesign/core/theme';

export const econTheme = defineTheme({
  name: 'econ',

  // 한국어 본문 + Figtree 라틴/숫자. Pretendard 가 설치돼 있으면 우선 사용.
  typography: {
    scale: {base: 14, ratio: 1.2},
    body: {
      family: 'Figtree',
      fallbacks:
        'Pretendard, "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", Roboto, Helvetica, Arial, sans-serif',
    },
    heading: {
      family: 'Figtree',
      fallbacks:
        'Pretendard, "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", Roboto, Helvetica, Arial, sans-serif',
      weights: {3: 'bold', 4: 'bold'},
    },
    code: {
      family: 'ui-monospace',
      fallbacks:
        '"SF Mono", Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
    },
  },

  motion: {fast: 125, medium: 300, slow: 700, ratio: 0.75},

  tokens: {
    // ── 표면 사다리 ───────────────────────────────────────────────
    // 다크: body T09 → card/surface T15. 위젯이 캔버스 위로 확실히 분리되게
    // neutral 기본(card=body)보다 한 칸 벌린다. 라이트는 astryx 기본 사다리 유지.
    '--color-background-body': ['#f1f1f1', '#171717'],
    '--color-background-card': ['#ffffff', '#262626'],
    '--color-background-surface': ['#ffffff', '#262626'],
    '--color-background-popover': ['#ffffff', '#262626'],
    '--color-background-muted': ['#f1f1f1', '#1b1b1b'],

    // ── accent = 상호작용(파랑) ─────────────────────────────────
    '--color-accent': ['#00458c', '#9eb7ff'],
    '--color-accent-muted': [
      'color-mix(in srgb, #00458c 12%, transparent)',
      'color-mix(in srgb, #9eb7ff 18%, transparent)',
    ],
    '--color-on-accent': ['#ffffff', '#171717'],
    '--color-text-accent': ['#00458c', '#c7d3ff'],
    '--color-icon-accent': ['#00458c', '#9eb7ff'],

    // ── 시장 등락색 (관습 전환용 4종) ────────────────────────────
    // global: 상승 초록 / 하락 빨강. kr: 상승 빨강 / 하락 파랑.
    // 값은 모두 astryx 카테고리 램프의 icon/text stop → 카드 위 WCAG AA 통과.
    '--color-market-up': ['#0c5700', '#84c980'],
    '--color-market-down': ['#89001a', '#ff9e97'],
    '--color-market-up-kr': ['#89001a', '#ff9e97'],
    '--color-market-down-kr': ['#00458c', '#9eb7ff'],

    // ── 차트 시리즈 (카테고리 팔레트, OKLCH 등간격 hue) ──────────
    '--color-series-1': ['#00458c', '#9eb7ff'], // blue
    '--color-series-2': ['#6e3500', '#ffa258'], // orange
    '--color-series-3': ['#005348', '#7ec6b8'], // teal
    '--color-series-4': ['#700084', '#f297ff'], // purple
    '--color-series-5': ['#0c5700', '#84c980'], // green
    '--color-series-6': ['#89001a', '#ff9e97'], // red
    '--color-series-7': ['#00505f', '#83c2d4'], // cyan
    '--color-series-8': ['#83004b', '#ff99c3'], // pink
    '--color-series-9': ['#584400', '#deb433'], // yellow
  },
});

export default econTheme;
