#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SEED 클래스 사용 게이트 — 마크업·JS 가 쓰는 seed-* 가 벤더 CSS 에 있는지 본다.

빌드가 없는 사이트라 오타 난 클래스는 조용히 무효 스타일이 된다(에러 0, 화면만 깨짐).
그 침묵을 깨는 게 이 스크립트의 유일한 목적이다.

검사
  1) 사용된 seed-* 클래스가 css/seed/seed.css 에 없음        → exit 1
  2) 빈 규칙 클래스만 단독으로 쓰임(예: --layout_withText)    → 경고
  3) 병기 전환 중인 사이트 셀렉터가 남아 있음(.menu-item{ 등) → 경고
  4) 브리지에서 재정의한 이름이 astryx 라이트 블록에도 있음   → 경고(특이성 역전 위험)
  5) ms 리터럴 신규 사용(transition/animation)                → 경고(모션 토큰 사용)

사용:  python scripts/check_seed_classes.py
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = os.path.join(ROOT, "css", "seed", "seed.css")
SOURCES = ["index.html"] + ["js/app%d.js" % i for i in range(1, 7)]

# 전환기 동안 recipe 와 병기하는 사이트 클래스 — 대응 recipe 를 붙인 뒤에도 옛
# 사이트 규칙이 살아 있으면 !important 로 recipe 를 덮는다(위험 R5).
PAIRED = {
    "seed-side-navigation-menu-item__root": ".menu-item",
    "seed-list-header": ".widget-title",
    "seed-snackbar__root": ".toast",
    "seed-tabs__trigger": ".tab-btn",
    "seed-chip__root": ".preset-btn",
}


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fp:
        return fp.read()


# 클래스가 등장하는 자리만 본다 — 변수명(--seed-color-*)·패키지명(@seed-design)을
# 클래스로 오인하지 않기 위해 문맥을 좁힌다.
CLASS_CONTEXTS = (
    r"""class\s*=\s*["']([^"']*)["']""",          # <div class="…">
    r"""class\s*=\s*\\?["']([^"'\\]*)""",          # JS 템플릿 내부 class=\"…\"
    r"""classList\.(?:add|remove|toggle|contains)\(([^)]*)\)""",
    r"""className\s*=\s*[`"']([^`"']*)[`"']""",
)


def used_classes(text):
    """마크업·JS 의 클래스 자리에서 seed-* 토큰을 모은다.

    템플릿 리터럴로 조립되는 이름(`--tone_${tone}-variant_solid`)은 정적으로
    검증할 수 없다 — 따로 모아 리포트만 한다(무시하면 오타를 놓치고, 실패로
    치면 정상 코드가 게이트를 막는다).
    """
    out, dynamic = set(), set()
    for pat in CLASS_CONTEXTS:
        for chunk in re.findall(pat, text):
            for word in re.split(r"[\s,'\"`]+", chunk):
                if not word.startswith("seed-"):
                    continue
                (dynamic if "${" in word or "'+" in word else out).add(word)
    return out, dynamic


def main():
    if not os.path.exists(CSS):
        print("css/seed/seed.css 가 없다 — python scripts/vendor_seed_css.py 먼저 실행")
        return 1
    css = read(os.path.join("css", "seed", "seed.css"))
    defined = set(re.findall(r"\.(seed-[a-zA-Z0-9_-]+)", css))
    # 빈 규칙(선언 0)인 클래스 — 단독 사용은 무의미하다
    empty = set()
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if body.strip():
            continue
        for cls in re.findall(r"\.(seed-[a-zA-Z0-9_-]+)", sel):
            empty.add(cls)

    fail = False
    used, dyn = {}, {}
    for rel in SOURCES:
        static, dynamic = used_classes(read(rel))
        for cls in static:
            used.setdefault(cls, set()).add(rel)
        for cls in dynamic:
            dyn.setdefault(cls, set()).add(rel)

    unknown = {c: v for c, v in used.items() if c not in defined}
    if unknown:
        fail = True
        print("1) 벤더 CSS 에 없는 seed-* 클래스 %d개:" % len(unknown))
        for c in sorted(unknown):
            print("   %-60s %s" % (c, ", ".join(sorted(unknown[c]))))
    else:
        print("1) 미정의 seed-* 클래스 0 (사용 %d종)" % len(used))
    if dyn:
        print("1b) 조립형 이름 %d개 — 정적 검증 불가, 육안 확인 대상: %s"
              % (len(dyn), ", ".join(sorted(dyn))))

    solo_empty = sorted(c for c in used if c in empty and c in defined)
    if solo_empty:
        print("2) 경고 — 빈 규칙 클래스 사용(복합 클래스가 필요할 수 있다): %s"
              % ", ".join(solo_empty))

    html = read("index.html")
    for cls, site_sel in PAIRED.items():
        if cls in used and re.search(re.escape(site_sel) + r"\s*[,{]", html):
            print("3) 경고 — %s 를 채택했는데 사이트 셀렉터 %s 규칙이 남아 있다"
                  " (동커밋 삭제 또는 :not(.seed-*) 스코프 필요)" % (cls, site_sel))

    # 4) 브리지 정의명이 astryx 라이트 블록에도 있는지 — html:root 가 이겨야 한다
    m_bridge = re.search(r"html:root \{(.*?)\n  \}", html, re.S)
    m_light = re.search(r"\n  html\.light \{(.*?)\n  \}", html, re.S)
    if m_bridge and m_light:
        b = set(re.findall(r"(--[a-z0-9-]+)\s*:", m_bridge.group(1)))
        l = set(re.findall(r"(--[a-z0-9-]+)\s*:", m_light.group(1)))
        both = sorted(b & l)
        if both:
            # 정상 상태다(브리지가 덮는 것이 목적) — 순서만 확인한다
            if html.index(m_light.group(0)) > html.index(m_bridge.group(0)):
                fail = True
                print("4) 실패 — astryx html.light 블록이 브리지보다 뒤에 있다."
                      " 동특이성이라 라이트에서 브리지가 패배한다: %d개 이름" % len(both))
            else:
                print("4) 브리지가 astryx html.light 보다 뒤 (중복 %d개, 정상)" % len(both))
    else:
        print("4) 경고 — 브리지 또는 astryx html.light 블록을 못 찾음")

    ms = re.findall(r"(?:transition|animation)[^;{}]*?\b(\d{2,4})ms", html)
    if ms:
        print("5) 경고 — ms 리터럴 %d건(모션 토큰 --duration-* 사용 권장)" % len(ms))

    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
