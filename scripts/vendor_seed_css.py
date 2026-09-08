#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""@seed-design/css 벤더링 — css/seed/seed.css 를 만든다.

왜 벤더링인가: CSP 가 style-src 'self' 라 서드파티 CDN <link> 는 차단된다.
SEED 는 React/Lynx 문서만 있지만 @seed-design/css 는 순수 CSS(토큰 + BEM recipe)라
빌드 없는 단일 index.html 에 그대로 얹을 수 있다.

만드는 것
  css/seed/seed.css   base.css + 채택 recipe 결합본 (1 파일 = 요청 1회)
  css/seed/VERSION    "2.7.0" — 캐시버스팅·재현용

검사(실패 시 exit 1)
  A) recipe 가 참조하나 어디에도 정의되지 않은 --seed-* 변수 (폴백 없는 것만)
  B) !important 개수 리포트 (SEED 는 0 이 정상 — 늘면 사이트 규칙과 싸운다)
  C) index.html/_UPDN·js 폴백 hex ↔ base.css 팔레트 값 diff
     (등락색 3곳 수동 동기 규칙을 기계가 지키게 한다)

사용:  python scripts/vendor_seed_css.py [--check]
       --check 는 파일을 쓰지 않고 검사만 (CI/사전 커밋용)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

sys.stdout.reconfigure(encoding="utf-8")

VERSION = "2.7.0"
PKG = "@seed-design/css@" + VERSION
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "css", "seed")

# 채택 recipe. Deprecated(action-chip·control-chip·inline-banner)는 제외.
# 목록 근거 = 기획안 §9 컴포넌트 매핑.
RECIPES = [
    "action-button", "toggle-button", "segmented-control", "tabs", "chip-tabs", "chip",
    "badge", "tag-group", "tag-group-item", "callout", "page-banner", "skeleton",
    "snackbar", "snackbar-region", "progress-circle", "dialog", "content-dialog",
    "side-panel", "bottom-sheet", "bottom-sheet-handle", "menu", "menu-item",
    "help-bubble", "side-navigation", "side-navigation-menu-item", "app-bar",
    "app-bar-main", "list-item", "list-header", "text", "switch", "switchmark",
    "checkbox", "checkmark", "radio", "radiomark", "text-input", "select-trigger",
    "scroll-fog", "field", "field-label",
]

# recipe 가 참조하지만 base.css 에 정의가 없는 런타임 변수의 사이트 기본값.
# (SEED React 런타임이 인라인으로 주던 값들 — 우리는 CSS 로만 쓰므로 여기서 채운다)
SITE_DEFAULTS = """
/* ── site-defaults — recipe 가 참조하나 base.css 에 없는 런타임 변수 ──
   SEED React 런타임(Ark UI)이 인라인 스타일로 주던 값. no-build 사용에서는
   여기서 정적 기본값을 준다. 값이 필요한 곳(메뉴 위치 등)은 JS 가 덮어쓴다. */
:root {
  --seed-menu-transform-origin: top center;
}
"""


def npm_pack(dest):
    """npm pack 으로 tarball 을 받아 dest 에 풀고 package/ 경로를 돌려준다."""
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        sys.exit("npm 이 없다. Node 설치 후 다시 실행.")
    subprocess.run([npm, "pack", PKG, "--silent"], cwd=dest, check=True,
                   stdout=subprocess.DEVNULL)
    tgz = [f for f in os.listdir(dest) if f.endswith(".tgz")]
    if not tgz:
        sys.exit("npm pack 산출물(.tgz)을 못 찾았다.")
    with tarfile.open(os.path.join(dest, tgz[0])) as tf:
        tf.extractall(dest)
    pkg = os.path.join(dest, "package")
    with open(os.path.join(pkg, "package.json"), encoding="utf-8") as fp:
        got = json.load(fp)["version"]
    if got != VERSION:
        sys.exit("버전 불일치: 기대 %s, 받은 %s" % (VERSION, got))
    return pkg


def build(pkg):
    parts = ["/* @seed-design/css@%s — vendored by scripts/vendor_seed_css.py. 손으로 고치지 말 것. */\n" % VERSION]
    with open(os.path.join(pkg, "base.css"), encoding="utf-8") as fp:
        parts.append("/* ── base.css (토큰 + .seed-box/.seed-grid) ── */\n" + fp.read())
    missing = []
    for name in RECIPES:
        path = os.path.join(pkg, "recipes", name + ".css")
        if not os.path.exists(path):
            missing.append(name)
            continue
        with open(path, encoding="utf-8") as fp:
            parts.append("\n/* ── recipes/%s.css ── */\n" % name + fp.read())
    if missing:
        sys.exit("패키지에 없는 recipe: " + ", ".join(missing))
    parts.append("\n" + SITE_DEFAULTS)
    return "".join(parts)


# 폴백 없이 참조되지만 미정의여도 안전한 변수 — 이유를 각각 확인했다.
# 미정의 var() 는 그 선언만 invalid-at-computed-value-time 이 되고(속성이 unset 처리),
# 아래는 모두 우리가 쓰지 않는 파트이거나 상위에 폴백이 한 겹 더 있는 경우다.
UNDEFINED_OK = {
    # .seed-count — 배지 숫자 파트. 채택 컴포넌트 어디에도 쓰지 않는다.
    "--seed-count-color", "--seed-count-font-size", "--seed-count-font-weight",
    "--seed-count-line-height",
    # .seed-scale-feedback — React 런타임이 요소 크기를 재서 넣는다.
    # 미정의 시 --seed-dynamic-scale 이 무효가 되고 var(--seed-dynamic-scale, 1) 이 받는다.
    "--seed-element-height", "--seed-element-width",
    # prefix/suffix 아이콘 정렬 — 미정의면 align-self/justify-self 가 초기값.
    "--seed-prefix-icon-align-self", "--seed-prefix-icon-justify-self",
    "--seed-suffix-icon-justify-self",
    # .seed-box[data-has-active-bg] 전용. .seed-box 를 쓰지 않는다.
    "--seed-box-background--active",
}


def check_undefined_vars(css):
    """정의도 없고 폴백도 없이 참조되는 --seed-* 변수(허용 목록 제외)."""
    defined = set(re.findall(r"(--seed-[a-z0-9-]+)\s*:", css))
    bad = set()
    for m in re.finditer(r"var\(\s*(--seed-[a-z0-9-]+)\s*([,)])", css):
        if m.group(2) == ")" and m.group(1) not in defined and m.group(1) not in UNDEFINED_OK:
            bad.add(m.group(1))
    return sorted(bad)


def palette(css):
    """base.css 팔레트를 {(mode, name): hex} 로. mode = light|dark."""
    out = {}
    for sel, body in re.findall(r"(:root[^{]*?)\{([^}]*)\}", css, re.S):
        if "--seed-color-palette-gray-00" not in body:
            continue
        mode = "dark" if "dark-only" in sel else "light"
        for name, val in re.findall(r"--seed-color-palette-([a-z0-9-]+)\s*:\s*([^;]+);", body):
            out[(mode, name)] = val.strip()
    return out


def norm(h):
    """#fff → #ffffff, 대문자 → 소문자."""
    h = h.strip().lower()
    if re.fullmatch(r"#[0-9a-f]{3}", h):
        h = "#" + "".join(c * 2 for c in h[1:])
    return h


# index.html window._UPDN / js 폴백이 써야 하는 팔레트 좌표.
# 기획안 §6-2: 텍스트는 800(라이트)/700(다크), 도형·차트는 700(라이트)/600(다크).
UPDN_EXPECT = {
    ("kr", "dark", 0): ("dark", "red-700"), ("kr", "dark", 1): ("dark", "blue-700"),
    ("kr", "light", 0): ("light", "red-800"), ("kr", "light", 1): ("light", "blue-800"),
    ("global", "dark", 0): ("dark", "green-700"), ("global", "dark", 1): ("dark", "red-700"),
    ("global", "light", 0): ("light", "green-800"), ("global", "light", 1): ("light", "red-800"),
}
UPDNF_EXPECT = {
    ("kr", "dark", 0): ("dark", "red-600"), ("kr", "dark", 1): ("dark", "blue-600"),
    ("kr", "light", 0): ("light", "red-700"), ("kr", "light", 1): ("light", "blue-700"),
    ("global", "dark", 0): ("dark", "green-600"), ("global", "dark", 1): ("dark", "red-600"),
    ("global", "light", 0): ("light", "green-700"), ("global", "light", 1): ("light", "red-700"),
}


def check_updn(pal):
    """index.html 의 _UPDN / _UPDN_FILL 값이 팔레트와 어긋나면 목록을 돌려준다."""
    with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as fp:
        html = fp.read()
    errs = []
    for var, expect in (("_UPDN", UPDN_EXPECT), ("_UPDN_FILL", UPDNF_EXPECT)):
        m = re.search(r"window\.%s\s*=\s*\{(.*?)\n\s*\};" % var, html, re.S)
        if not m:
            errs.append("%s 정의를 index.html 에서 못 찾음" % var)
            continue
        body = m.group(1)
        for conv in ("kr", "global"):
            cm = re.search(r"%s\s*:\s*\{(.*?)\}\s*,?" % conv, body, re.S)
            if not cm:
                errs.append("%s.%s 없음" % (var, conv))
                continue
            for mode in ("dark", "light"):
                mm = re.search(r"%s\s*:\s*\[([^\]]*)\]" % mode, cm.group(1))
                if not mm:
                    errs.append("%s.%s.%s 없음" % (var, conv, mode))
                    continue
                got = [norm(x.strip().strip("'\"")) for x in mm.group(1).split(",")]
                for i in (0, 1):
                    pm, pname = expect[(conv, mode, i)]
                    want = norm(pal[(pm, pname)])
                    if i >= len(got) or got[i] != want:
                        errs.append("%s.%s.%s[%d] = %s, 팔레트 %s(%s) = %s"
                                    % (var, conv, mode, i,
                                       got[i] if i < len(got) else "없음", pname, pm, want))
    return errs


def main():
    check_only = "--check" in sys.argv
    tmp = tempfile.mkdtemp(prefix="seedcss")
    try:
        pkg = npm_pack(tmp)
        css = build(pkg)
        base = open(os.path.join(pkg, "base.css"), encoding="utf-8").read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    fail = False
    undef = check_undefined_vars(css)
    if undef:
        print("A) 정의·폴백 없는 --seed-* 변수 %d개: %s" % (len(undef), ", ".join(undef)))
        fail = True
    else:
        print("A) 미정의 --seed-* 변수 0")

    imps = re.findall(r"[^\n]*!important[^\n]*", css)
    print("B) !important %d건%s" % (len(imps), "" if not imps else ": " + " | ".join(i.strip()[:80] for i in imps)))

    errs = check_updn(palette(base))
    if errs:
        print("C) 등락색 팔레트 동기 실패:\n   " + "\n   ".join(errs))
        fail = True
    else:
        print("C) _UPDN·_UPDN_FILL ↔ base.css 팔레트 일치")

    if check_only:
        return 1 if fail else 0
    if fail:
        print("검사 실패 — 파일을 쓰지 않았다.")
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "seed.css")
    with open(out, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(css)
    with open(os.path.join(OUT_DIR, "VERSION"), "w", encoding="utf-8", newline="\n") as fp:
        fp.write(VERSION + "\n")
    print("wrote %s (%d bytes, recipe %d개)" % (out, len(css.encode("utf-8")), len(RECIPES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
