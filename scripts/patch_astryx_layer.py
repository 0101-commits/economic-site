#!/usr/bin/env python3
"""글래스모피즘 레이어 제거 + astryx 컴포넌트 레이어 주입 (1회성 마이그레이션).

왜
--
astryx docs/principles 의 안티패턴 목록:
  · 하드코딩 색(#fff) 금지 -> var(--color-*)
  · 리스트 항목마다 Card 로 감싸기(card soup) 금지 -> 밀집 데이터는 행(row)
  · Badge 를 장식으로 쓰지 말 것 -> 카운트/열거 상태에만
astryx docs/layout: "frame first" — 셸을 먼저 정하고 각 영역에 px 예산을 준다.
astryx docs/motion: 초당 수십 번 일어나는 상호작용(행 hover)에 지각 가능한
  지속시간을 주지 말 것.

기존 index.html 은 반대로 가 있었다: 4겹 radial-gradient 배경 + 모든 표면에
backdrop-filter blur + 파란 rgba 하드코딩, 그리고 그걸 라이트 테마에서
되돌리는 !important 패치가 100 줄 넘게 쌓여 있었다.
이 스크립트는 그 두 덩어리를 삭제하고, 토큰만 쓰는 평면 레이어로 대체한다.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "index.html"

# ── 삭제할 레거시 구간 (시작 마커 … 끝 마커, 둘 다 포함) ────────────────────
DROP = [
    # 라이트 테마 글래스 + 인라인 hex 되돌리기 패치 뭉치
    (
        "  /* ======= 글래스모피즘 — 라이트 테마 ======= */",
        "  /* 시장 분위기 카드 호버 — 테마 무관 (라이트/다크 모두 자연스럽게) */",
    ),
    # 다크 글래스 카드 / 헤더·사이드바 / 모달·팝업 글래스
    (
        "  /* ======= 글래스모피즘 카드 (다크 테마 기본) =======",
        "  html.light .link-card:hover { border-color: rgb(53,108,181); }",
    ),
    # 구 등락 관습 하드코딩 — astryx market 토큰이 대체
    (
        "html.kr-colors { --c-up:#f87171; --c-down:#58a6ff; }",
        "html.light.kr-colors { --c-up:#d32f2f; --c-down:#1565c0; }",
    ),
]

LAYER = r"""
/* ═══════════════════════════════════════════════════════════════════
   astryx layer — 프레임 · 표면 · 행 밀도 · 상태
   근거: astryx docs {principles, layout, color, motion, elevation}
   · 무채색 표면 + 의미색만 유채색      · frame-first, 영역별 px 예산
   · 밀집 데이터는 카드가 아니라 행     · 자주 일어나는 hover 는 무지연
   레거시 규칙을 이기려면 <style> 의 마지막에 있어야 한다.
═══════════════════════════════════════════════════════════════════ */

/* ── 0. 지면 ───────────────────────────────────────────────────── */
body {
  font-family: var(--font-family-body);
  font-size: var(--font-size-base);
  line-height: 1.4286;
  color: var(--c-txt);
  /* 4겹 radial-gradient 블롭 제거 — astryx 는 평면 캔버스 */
  background: var(--c-bg) !important;
  background-attachment: initial !important;
}
h1, h2, h3, h4, h5, h6 { font-family: var(--font-family-heading); color: var(--c-txt); }
h1 { font-size: var(--font-size-2xl); font-weight: 600; line-height: 1.3333; }
h2 { font-size: var(--font-size-xl);  font-weight: 600; line-height: 1.4; }
h3 { font-size: var(--font-size-lg);  font-weight: 700; line-height: 1.4118; }
h4 { font-size: var(--font-size-base); font-weight: 700; line-height: 1.4286; }
::selection { background: var(--color-accent-muted); color: var(--c-txt); }

/* 숫자 = 고정폭. 주기 갱신 때 자릿수가 흔들리지 않게 */
table, .up-txt, .down-txt, .brief-val, #clock, #ticker,
[id^="kpi-"], [id$="Val"], [id$="Price"], [id$="Chg"] { font-variant-numeric: tabular-nums; }

/* ── 1. 프레임 (frame-first) ────────────────────────────────────
   반응형 계약:
     > 1024px  nav 240 | content(flex)
     <=1024px  nav 는 오버레이 드로어로 전환, 콘텐츠는 압축하지 않음
     <= 768px  모든 다열 그리드 1열, 툴바 wrap                       */
header {
  height: var(--frame-header);
  background: var(--c-bg) !important;
  border-bottom: 1px solid var(--c-border) !important;
  backdrop-filter: none !important; -webkit-backdrop-filter: none !important;
  box-shadow: none !important;
}
nav#sidebar {
  background: var(--c-bg) !important;
  border-right: 1px solid var(--c-border) !important;
  backdrop-filter: none !important; -webkit-backdrop-filter: none !important;
  padding: var(--spacing-2) !important;
}
@media (min-width: 1025px) {
  nav#sidebar:not(.collapsed) { width: var(--frame-nav) !important; }
}
@media (max-width: 1024px) {
  /* 드로어는 캔버스가 아니라 surface — 뒤 콘텐츠와 확실히 분리 */
  nav#sidebar { background: var(--c-surface) !important; box-shadow: var(--e-3); }
}
main#mainContent { padding: var(--spacing-5); }
@media (max-width: 768px) { main#mainContent { padding: var(--spacing-3) !important; } }

/* 사이드바 항목 = 행(36px). 선택 상태만 색을 쓴다 */
.menu-item {
  min-height: var(--size-element-lg);
  padding: 0 var(--spacing-3);
  gap: var(--spacing-2);
  border-radius: var(--r-sm);
  font-size: var(--font-size-base);
  font-weight: 500;
  color: var(--c-txt-dim);
  border: 1px solid transparent;
  transition: background var(--duration-fast-min) var(--ease-standard);
}
.menu-item:hover { background: var(--color-overlay-hover); color: var(--c-txt); }
.menu-item.active {
  background: var(--color-accent-muted) !important;
  color: var(--c-primary) !important;
  border-color: transparent !important;
  font-weight: 600;
}

/* ── 2. 카드 = 위젯 컨테이너 (리스트 래퍼 아님) ─────────────────
   평면 표면 + 1px 테두리 + 낮은 그림자. blur/그라디언트 없음.     */
.widget, .kpi-card, .themed-modal > div, .themed-popup, .data-source-popup,
#calGridFloating, .link-card, .sentiment-card, .mer-item, .pf-card, .toast {
  backdrop-filter: none !important; -webkit-backdrop-filter: none !important;
}
.widget, .kpi-card {
  background: var(--c-card) !important;
  border: 1px solid var(--c-border) !important;
  border-radius: var(--radius-container) !important;
  padding: var(--spacing-4);
  box-shadow: var(--shadow-low) !important;
}
.widget-title {
  font-size: var(--font-size-xs);
  font-weight: 600;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--c-txt-dim) !important;   /* 제목은 강조색이 아니라 보조 텍스트 */
  margin-bottom: var(--spacing-3);
}
/* 클릭 가능한 카드: 들어올리지 말고 테두리로 알린다(모션 최소화) */
.kpi-card.kpi-clickable, .clickable-card, .link-card {
  transition: border-color var(--duration-fast-min) var(--ease-standard),
              background-color var(--duration-fast-min) var(--ease-standard);
}
.kpi-card:hover, .kpi-clickable:hover, .clickable-card:hover, .link-card:hover {
  border-color: var(--color-border-emphasized) !important;
  background: var(--c-card-hi) !important;
  transform: none !important;
  box-shadow: var(--shadow-low) !important;
}
.link-card { background: var(--c-card); border: 1px solid var(--c-border); border-radius: var(--r-sm); }
.sentiment-card {
  background: var(--c-surface) !important;
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  box-shadow: none;
}
.sentiment-card:hover { background: var(--c-card-hi) !important; border-color: var(--color-border-emphasized); transform: none !important; }
/* 카드 안의 서브 표면 */
.widget [style*="background:var(--c-bg)"], .kpi-card [style*="background:var(--c-bg)"] {
  background: var(--color-background-muted) !important;
  border: 1px solid var(--c-border) !important;
  border-radius: var(--r-sm) !important;
  backdrop-filter: none !important; -webkit-backdrop-filter: none !important;
}

/* ── 3. 밀집 데이터 = 행 (카드 금지) ────────────────────────────
   행 높이 32–40px, 구분선, 즉시 반응하는 hover.                    */
main table { width: 100%; border-collapse: collapse; font-size: var(--font-size-sm); }
main table th {
  font-size: var(--font-size-xs); font-weight: 600; letter-spacing: .04em;
  text-transform: uppercase; color: var(--c-txt-dim);
  text-align: left; padding: var(--spacing-2) var(--spacing-2);
  border-bottom: 1px solid var(--c-border); white-space: nowrap;
}
main table td {
  padding: var(--spacing-2); border-bottom: 1px solid var(--c-border-weak);
  color: var(--c-txt);
}
main table tbody tr:last-child td { border-bottom: none; }
tr:hover td, .hoverable-row:hover td {
  background: var(--color-overlay-hover) !important;   /* 무지연 */
}
.up-txt { color: var(--c-up); } .down-txt { color: var(--c-down); }

/* 리스트형 레코드 — 항목마다 카드로 감싸지 않고 구분선 행으로 */
.mer-item, .ds-item, .study-list-item, .pf-card {
  background: transparent !important;
  border: none !important;
  border-bottom: 1px solid var(--c-border-weak) !important;
  border-radius: 0 !important;
  box-shadow: none !important;
  margin: 0 !important;
  padding: var(--spacing-3) var(--spacing-2) !important;
  transition: background var(--duration-fast-min) var(--ease-standard);
}
.mer-item:hover, .ds-item:hover, .study-list-item:hover, .pf-card:hover {
  background: var(--color-overlay-hover) !important;
  color: inherit !important;
}
.study-list-item.active {
  background: var(--color-accent-muted) !important;
  box-shadow: inset 2px 0 0 var(--c-accent);
}
.news-card-link:hover { background: var(--color-overlay-hover); opacity: 1; }

/* ── 4. 컨트롤 ──────────────────────────────────────────────────
   높이 28/32/36 3단, 라디우스 inner, 비활성은 무채색, 활성만 accent. */
.tab-btn, .preset-btn, .invUnitBtn, .news-filter-btn, .yoy-btn,
.reHistPeriodBtn, .reHistUnitBtn, .range-reset-btn, .study-btn, .gidx-btn {
  font-family: inherit;
  border-radius: var(--r-sm) !important;
  transition: background var(--duration-fast-min) var(--ease-standard),
              border-color var(--duration-fast-min) var(--ease-standard),
              color var(--duration-fast-min) var(--ease-standard);
}
.tab-btn, .preset-btn, .invUnitBtn, .news-filter-btn,
.reHistPeriodBtn, .reHistUnitBtn {
  min-height: var(--size-element-sm);
  padding: 0 var(--spacing-3);
  font-size: var(--font-size-sm) !important;
  font-weight: 600;
  color: var(--c-txt-dim) !important;
  background: transparent !important;
  border: 1px solid var(--c-border) !important;
}
.tab-btn:not(.active):hover, .preset-btn:not(.active):hover,
.invUnitBtn:not(.active):hover, .news-filter-btn:not(.act):hover,
.reHistPeriodBtn:not(.active):hover, .reHistUnitBtn:not(.active):hover {
  background: var(--color-overlay-hover) !important;
  color: var(--c-txt) !important;
  border-color: var(--color-border-emphasized) !important;
}
.tab-btn.active, .preset-btn.active, .invUnitBtn.active, .news-filter-btn.act,
.reHistPeriodBtn.active, .reHistUnitBtn.active, .yoy-btn.active,
button.active, .study-btn.primary {
  background: var(--c-accent) !important;
  color: var(--c-on-accent) !important;
  border-color: var(--c-accent) !important;
}
.yoy-btn.indeterminate {
  background: var(--color-accent-muted) !important;
  color: var(--c-primary) !important;
  border-color: var(--c-accent) !important;
}
#themeToggleBtn:hover, #globalRefreshBtn:hover, .widget-err button:hover {
  background: var(--color-overlay-hover) !important;
  color: var(--c-txt) !important;
  border-color: var(--color-border-emphasized) !important;
}
.widget-err button { border-color: var(--c-border) !important; color: var(--c-primary) !important; }

input[type="text"], input[type="date"], input[type="search"], input[type="number"],
textarea, select, .set-select, .study-field, .pf-card-grid input {
  background: var(--c-surface) !important;
  border: 1px solid var(--c-border) !important;
  border-radius: var(--r-sm) !important;
  color: var(--c-txt) !important;
  font-family: inherit;
  min-height: var(--size-element-md);
  padding: 0 var(--spacing-2);
}
input:hover, textarea:hover, select:hover { border-color: var(--color-border-emphasized) !important; }
input:focus-visible, textarea:focus-visible, select:focus-visible {
  outline: 2px solid var(--c-accent); outline-offset: -1px;
}
*:focus-visible { outline: 2px solid var(--c-accent) !important; outline-offset: 2px; }
.set-switch input:checked + .set-slider { background: var(--c-accent); }
.set-slider { background: var(--color-border-emphasized); }
.set-slider:before { background: var(--color-background-surface); }

/* ── 5. 상태 표시 — Badge 는 열거 상태/카운트에만 ──────────────── */
.brief-chip, .ann-chip, .cal-chip, .study-badge, .kpi-pct-badge, #globalDelayChip {
  background: var(--color-background-gray) !important;
  color: var(--c-txt-dim) !important;
  border: 1px solid var(--c-border) !important;
  border-radius: var(--r-full);
  font-size: var(--font-size-xs);
  transition: background var(--duration-fast-min) var(--ease-standard);
}
.brief-chip:hover { background: var(--c-card-hi) !important; transform: none !important; }
#globalDelayChip { color: var(--color-text-yellow) !important; border-color: var(--color-border-yellow) !important; background: var(--color-background-yellow) !important; }
.yoy-badge-up   { background: var(--c-up);   border-color: var(--c-up);   color: var(--color-on-success); }
.yoy-badge-down { background: var(--c-down); border-color: var(--c-down); color: var(--color-on-error); }
.yoy-badge-none { background: var(--color-background-gray); border-color: var(--c-border); color: var(--c-txt-dim); }
/* 신호등은 등락 관습과 무관하게 고정 (초록/노랑/빨강) */
.risk-dot.g { background: var(--color-icon-green); }
.risk-dot.y { background: var(--color-icon-yellow); }
.risk-dot.r { background: var(--color-icon-red); }
.ann-pending { color: var(--c-primary); background: var(--color-accent-muted); border: 1px dashed var(--c-accent); }
.ann-pending .dot { background: var(--c-accent); }
.guide-banner {
  background: var(--color-background-blue) !important;
  border: 1px solid var(--color-border-blue) !important;
  color: var(--color-text-blue) !important;
  border-radius: var(--r-sm);
}
.guide-banner b { color: inherit; }
.halt-banner.circuit { background: var(--color-icon-red); }
.halt-banner.sidecar { background: var(--color-icon-orange); }
#dataSrcBanner {
  background: var(--color-background-yellow) !important;
  border: 1px solid var(--color-border-yellow) !important;
  color: var(--color-text-yellow) !important;
  border-radius: var(--r-sm); box-shadow: var(--shadow-med);
}
.pf-input-err { border-color: var(--c-error) !important; background: var(--color-error-muted) !important; }
.skel-bar {
  background: linear-gradient(90deg, var(--color-skeleton) 25%,
              var(--color-overlay-hover) 50%, var(--color-skeleton) 75%);
  background-size: 200% 100%; border-radius: var(--r-xs);
}

/* ── 6. 오버레이 — 그림자로 띄우고, 블러는 스크림에만 ──────────── */
.themed-modal {
  background: var(--color-overlay) !important;
  backdrop-filter: blur(2px); -webkit-backdrop-filter: blur(2px);
}
.themed-modal > div, .themed-popup, .data-source-popup, #calGridFloating {
  background: var(--color-background-popover) !important;
  border: 1px solid var(--c-border) !important;
  border-radius: var(--radius-container) !important;
  box-shadow: var(--shadow-high) !important;
}
.themed-modal #reHistGuide, .themed-modal [style*="background:var(--c-surface"] {
  background: var(--color-background-muted) !important;
  border: 1px solid var(--c-border) !important;
}
.toast {
  background: var(--color-background-popover) !important;
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-high);
}
.toast.ok  { border-color: var(--color-border-green); }
.toast.err { border-color: var(--color-border-red); }

/* ── 7. 스크롤바 — 4px 은 잡기 어렵다. astryx 컨트롤 감각으로 8px ── */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--color-border-emphasized); border-radius: var(--r-full); }
::-webkit-scrollbar-thumb:hover { background: var(--c-txt-dim); }
* { scrollbar-width: thin; scrollbar-color: var(--color-border-emphasized) transparent; }

/* ── 8. 모션 — 방향은 트리거를 따르고, 반복 상호작용은 무지연 ──── */
.enso-com-detail { transition: max-height var(--duration-medium) var(--ease-standard); }
.enso-chev { transition: transform var(--duration-medium) var(--ease-standard); }
.spin-anim { animation: _spin var(--duration-slow) linear infinite; }
"""


def main() -> int:
    src = HTML.read_text(encoding="utf-8")
    shutil.copyfile(HTML, ROOT / "index.html.bak2")

    for start, end in DROP:
        i = src.find(start)
        j = src.find(end, i + 1) if i >= 0 else -1
        if i < 0 or j < 0:
            raise SystemExit(f"marker not found: {start[:50]}...")
        src = src[:i] + src[j + len(end):]

    if "astryx layer" in src:
        raise SystemExit("astryx layer already injected")
    src = src.replace("</style>", LAYER + "\n</style>", 1)

    HTML.write_text(src, encoding="utf-8")
    print("patched", HTML)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
