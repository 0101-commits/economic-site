#!/usr/bin/env python3
"""index.html 의 색/타이포 토큰 레이어를 astryx econ 토큰으로 교체하는 1회성 마이그레이션.

astryx 원칙(principles.doc): "semantic tokens, not hardcoded values" /
"CSS custom properties for colors, not hex values".
기존 index.html 은 --c-* 토큰을 쓰면서도 곳곳에 다크 팔레트 hex 를 직접 박아 두었고,
그 때문에 html.light 오버라이드 규칙이 100 줄 넘게 누적돼 있었다.
이 스크립트는

  1) 구 토큰 블록 4개(:root 다크 / Design Tokens v2 / html.light / v2 light)를
     astryx 생성 토큰 + --c-* 별칭 레이어로 교체
  2) style="" 속성 안의 구 팔레트 hex 를 토큰 var() 로 치환
     (JS 안의 Chart.js 색 문자열은 캔버스가 var() 를 못 읽으므로 건드리지 않는다)
  3) 'Inter' / 'Public Sans' 폰트 직접 지정을 --font-family-body / --font-num 으로 치환

실행 전 index.html.bak 백업을 남긴다.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "index.html"
TOKENS = ROOT / "scripts" / "_astryx_tokens.css"   # build_astryx_tokens.py 산출물

# ── style="" 속성 안에서만 치환할 구 팔레트 → 토큰 매핑 ──────────────────────
HEX_MAP = {
    # 표면
    "#0a0e18": "var(--c-bg)",
    "#1a2236": "var(--c-surface)",
    "#1f2945": "var(--c-card)",
    "#2a3556": "var(--c-card-hi)",
    "#262a35": "var(--c-surface)",
    "#131722": "var(--c-bg)",
    # 테두리
    "#3e4870": "var(--c-border)",
    "#2a2e3d": "var(--c-border)",
    "#3a4054": "var(--c-border)",
    "#2c3454": "var(--c-border-weak)",
    # 텍스트
    "#e8ebf5": "var(--c-txt)",
    "#dfe2f2": "var(--c-txt)",
    "#a4a8bc": "var(--c-txt-dim)",
    "#8d90a2": "var(--c-txt-dim)",
    "#b6bbcf": "var(--c-txt-dim)",
    "#8b90a8": "var(--c-txt-muted)",
    "#7a8099": "var(--c-txt-muted)",
    # 강조
    "#b6c4ff": "var(--c-primary)",
    "#c8d2ff": "var(--c-primary)",
    "#2962ff": "var(--c-accent)",
    # 상태
    "#f0c75e": "var(--c-warn)",
    "#ef5350": "var(--c-error)",
    "#26a69a": "var(--c-success)",
}
# 알파 접미사가 붙은 accent 변형 (#2962ff33 등) → accent-container
HEX_ALPHA = re.compile(r"#2962ff(?:[0-9a-fA-F]{2})")

ALIASES = """
  /* ═══ astryx 토큰 → 레거시 --c-* 별칭 레이어 ═══
     index.html 에는 var(--c-*) 사용처가 2000 곳 넘는다. 전부 고치는 대신
     별칭 한 겹을 두어 astryx 토큰이 단일 출처가 되게 한다.
     새 코드는 --color-* / --spacing-* / --radius-* 를 직접 쓸 것. */
  :root {
    --ease-standard: cubic-bezier(0.24, 1, 0.4, 1);

    /* 표면 — 무채색 사다리 (body → card → hover) */
    --c-bg:        var(--color-background-body);
    --c-surface:   var(--color-background-surface);
    --c-card:      var(--color-background-card);
    --c-card-hi:   color-mix(in srgb, var(--color-tint-hover) 8%, var(--color-background-card));
    --c-border:    var(--color-border);
    --c-border-weak: color-mix(in srgb, var(--color-border) 55%, transparent);

    /* 텍스트 — muted 는 카드 위 4.5:1 을 지키려고 secondary 를 배경 쪽으로 10% 만 민다 */
    --c-txt:       var(--color-text-primary);
    --c-txt-dim:   var(--color-text-secondary);
    --c-txt-muted: color-mix(in srgb, var(--color-text-secondary) 90%, var(--color-background-card));

    /* 상호작용 */
    --c-accent:           var(--color-accent);
    --c-on-accent:        var(--color-on-accent);
    --c-accent-container: var(--color-accent-muted);
    --c-primary:          var(--color-text-accent);

    /* 의미색 — 색은 데이터에만 */
    --c-up:      var(--color-market-up);
    --c-down:    var(--color-market-down);
    --c-warn:    var(--color-warning);
    --c-success: var(--color-success);
    --c-error:   var(--color-error);
    --ind-pos:   var(--color-success);
    --ind-neg:   var(--color-error);
    --ind-neu:   var(--color-text-secondary);

    /* 모달·칩 */
    --modal-bg:      var(--color-background-popover);
    --modal-text:    var(--color-text-primary);
    --modal-border:  var(--color-border);
    --modal-surface: var(--color-background-body);
    --chip-bg:       var(--color-accent-muted);
    --chip-fg:       var(--color-text-accent);

    /* 모양 — astryx radius 스케일 */
    --r-xs:   var(--radius-none);       /* 4px  */
    --r-sm:   var(--radius-inner);      /* 6px  */
    --r-md:   var(--radius-element);    /* 10px */
    --r-lg:   var(--radius-container);  /* 12px */
    --r-full: var(--radius-full);

    /* 고도 */
    --e-1: var(--shadow-low);
    --e-2: var(--shadow-med);
    --e-3: var(--shadow-high);

    /* 모션 */
    --t-fast: var(--duration-fast) var(--ease-standard);
    --t-base: var(--duration-medium-min) var(--ease-standard);
    --t-emph: var(--duration-medium) var(--ease-standard);

    /* 간격 4px base */
    --sp-1: var(--spacing-1); --sp-2: var(--spacing-2); --sp-3: var(--spacing-3);
    --sp-4: var(--spacing-4); --sp-5: var(--spacing-5); --sp-6: var(--spacing-6);

    /* 타이포 — astryx 스케일에만 맞춘다 */
    --fs-label:    var(--font-size-xs);    /* 10 */
    --fs-body-sm:  var(--font-size-sm);    /* 12 */
    --fs-body:     var(--font-size-sm);    /* 12 */
    --fs-body-lg:  var(--font-size-base);  /* 14 */
    --fs-title-sm: var(--font-size-base);  /* 14 */
    --fs-title-lg: var(--font-size-lg);    /* 17 */
    --fs-headline: var(--font-size-xl);    /* 20 */
    --fs-display:  var(--font-size-2xl);   /* 24 */
    --font-num:    var(--font-family-body);

    /* 프레임 예산 (astryx layout: side nav 240–280) */
    --frame-header:      56px;
    --frame-nav:         240px;
    --frame-content-max: 1680px;
    --touch-min:         48px;
  }
  /* 등락 색상 관습 — 한국(상승 빨강 / 하락 파랑) */
  html.kr-colors {
    --c-up:   var(--color-market-up-kr);
    --c-down: var(--color-market-down-kr);
  }
"""


def patch_tokens(src: str) -> str:
    """구 토큰 블록 4개를 astryx 토큰 + 별칭 레이어로 교체."""
    tokens = TOKENS.read_text(encoding="utf-8").rstrip("\n")
    blocks = [
        # 1) 다크 :root — 이 자리에 새 레이어를 넣는다
        (
            re.compile(
                r"  /\* ======= CSS 변수 — 다크 테마 \(기본\) ======= \*/.*?"
                r"--chip-fg:#7dd3fc;\s*\n  \}",
                re.S,
            ),
            tokens + "\n" + ALIASES,
        ),
        # 2) Design Tokens v2 (:root 보강분) — 별칭 레이어가 대체
        (
            re.compile(
                r"  /\* ═══ Design Tokens v2 — MD3 roles.*?--touch-min:48px;\s*\n  \}\n",
                re.S,
            ),
            "",
        ),
        # 3) html.light 기본 오버라이드 — astryx 토큰이 테마 전환을 담당
        (
            re.compile(
                r"  /\* ======= 라이트 테마 오버라이드 ======= \*/\n  html\.light \{.*?"
                r"--chip-fg:#0369a1;\s*\n  \}\n",
                re.S,
            ),
            "",
        ),
        # 4) Design Tokens v2 light overrides
        (
            re.compile(
                r"  /\* ═══ Design Tokens v2 — light overrides.*?--c-on-accent:#ffffff;\s*\n  \}\n",
                re.S,
            ),
            "",
        ),
    ]
    for pat, repl in blocks:
        src, n = pat.subn(lambda _m, r=repl: r, src, count=1)
        if n != 1:
            raise SystemExit(f"token block not matched: {pat.pattern[:60]}...")
    return src


def patch_style_attrs(src: str) -> str:
    """style="" 안의 구 팔레트 hex 만 토큰으로 치환."""

    def repl(m: re.Match[str]) -> str:
        body = m.group(1)
        body = HEX_ALPHA.sub("var(--c-accent-container)", body)
        for old, new in HEX_MAP.items():
            body = re.sub(re.escape(old), new, body, flags=re.I)
        # var(--c-x, var(--c-x)) 처럼 중첩된 폴백 정리
        body = re.sub(r"var\(--([a-z-]+),\s*var\(--\1\)\)", r"var(--\1)", body)
        return f'style="{body}"'

    return re.sub(r'style="([^"]*)"', repl, src)


def patch_fonts(src: str) -> str:
    """직접 지정된 웹폰트 이름 → 토큰. 숫자 강조는 --font-num."""
    src = re.sub(r"font-family:\s*'Public Sans',\s*sans-serif", "font-family:var(--font-num)", src)
    src = re.sub(r"font-family:\s*'Public Sans'", "font-family:var(--font-num)", src)
    src = re.sub(r"font-family:\s*'Inter',\s*sans-serif", "font-family:var(--font-family-body)", src)
    src = re.sub(r"font-family:\s*'Inter'", "font-family:var(--font-family-body)", src)
    return src


def main() -> int:
    if not TOKENS.exists():
        sys.stderr.write(
            f"not found: {TOKENS}\n  -> python scripts/build_astryx_tokens.py > "
            f"scripts/_astryx_tokens.css\n"
        )
        return 1
    src = HTML.read_text(encoding="utf-8")
    shutil.copyfile(HTML, ROOT / "index.html.bak")

    head, sep, body = src.partition("</style>")
    if not sep:
        raise SystemExit("</style> not found")

    head = patch_tokens(head)
    out = patch_fonts(patch_style_attrs(head + sep + body))
    HTML.write_text(out, encoding="utf-8")
    print(f"patched {HTML}  ({len(src):,} -> {len(out):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
