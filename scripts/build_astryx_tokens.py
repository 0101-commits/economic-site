#!/usr/bin/env python3
"""astryx 테마 CSS → index.html 용 단일 토큰 블록 변환기.

왜 필요한가
-----------
`astryx theme build` 산출물(dist/econ.css)은 React 앱 전제라
  · `@scope ([data-astryx-theme="econ"])`
  · `light-dark(라이트, 다크)`
두 최신 문법에 의존한다. economic-site 는 빌드 스텝이 없는 단일 index.html 이고
구형 모바일 웹뷰까지 지원해야 하므로, 두 문법을 제거하고
  :root { …다크 값… }  /  html.light { …라이트 값… }
평문 두 블록으로 펼쳐서 넣는다. (사이트의 테마 토글은 html.light 클래스 방식)

사용법
------
  1) C:\\Users\\cgpar\\astryx\\econ.theme.ts 를 수정
  2) cd C:\\Users\\cgpar\\astryx
     node node_modules/@astryxdesign/cli/bin/astryx.mjs theme build econ.theme.ts --out dist/econ.css
  3) python scripts/build_astryx_tokens.py       # → 표준출력에 CSS 블록
     (index.html 의 `astryx econ tokens` 주석 구간을 통째로 교체)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# econ.theme.ts 는 "차이분"만 방출한다(astryx theme build 동작).
# 나머지 기본값은 theme-neutral 이 갖고 있으므로 둘을 이 순서로 병합한다.
BASE = Path(
    r"C:\Users\cgpar\astryx\node_modules\@astryxdesign\theme-neutral\dist\theme.css"
)
SRC = Path(r"C:\Users\cgpar\astryx\dist\econ.css")

# astryx core 의 spacing 스케일(4px base). 테마 CSS 가 아니라 core 패키지에 있어
# 여기서 함께 방출한다. (astryx docs spacing: 4px base-unit)
SPACING = {f"--spacing-{i}": f"{i * 4}px" for i in range(0, 13)}
SPACING["--spacing-0\\.5"] = "2px"
SPACING["--spacing-1\\.5"] = "6px"

# 의미 폰트 웨이트(astryx docs typography: normal/medium/semibold/bold).
# theme.css 는 --text-*-weight 에서 이 토큰들을 참조만 하고 정의는 core 기본값에
# 있어서, 테마 CSS 만 떼어 오면 정의가 비어 무효 선언이 된다. 여기서 채운다.
WEIGHTS = {
    "--font-weight-normal": "400",
    "--font-weight-medium": "500",
    "--font-weight-semibold": "600",
    "--font-weight-bold": "700",
}

# 컨트롤 높이(astryx core size 토큰)
SIZES = {
    "--size-element-sm": "28px",
    "--size-element-md": "32px",
    "--size-element-lg": "36px",
}


def split_light_dark(value: str) -> tuple[str, str]:
    """light-dark(a, b) 를 (라이트값, 다크값) 두 문자열로 펼친다.

    중첩 괄호(color-mix, oklch)를 포함할 수 있어 수동 스캔한다.
    """
    light: list[str] = []
    dark: list[str] = []
    i = 0
    while i < len(value):
        if value.startswith("light-dark(", i):
            depth = 0
            j = i + len("light-dark(") - 1
            start = j + 1
            comma = -1
            while j < len(value):
                ch = value[j]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        break
                elif ch == "," and depth == 1 and comma < 0:
                    comma = j
                j += 1
            a = value[start:comma].strip()
            b = value[comma + 1 : j].strip()
            light.append(split_light_dark(a)[0])
            dark.append(split_light_dark(b)[1])
            i = j + 1
        else:
            light.append(value[i])
            dark.append(value[i])
            i += 1
    return "".join(light), "".join(dark)


def main() -> int:
    for path in (BASE, SRC):
        if not path.exists():
            sys.stderr.write(f"not found: {path}\n  → astryx theme build 를 먼저 실행하세요\n")
            return 1

    tokens: dict[str, str] = {}   # 선언 순서 유지 + 나중 파일이 덮어씀
    for path in (BASE, SRC):
        m = re.search(r":scope\s*\{(.*?)\n  \}", path.read_text(encoding="utf-8"), re.S)
        if not m:
            sys.stderr.write(f"token block(:scope{{…}}) not found in {path.name}\n")
            return 1
        for decl in m.group(1).split(";"):
            decl = decl.strip()
            if not decl.startswith("--"):
                continue
            name, _, value = decl.partition(":")
            name = name.strip()
            if name.startswith("--color-syntax-"):
                continue  # 코드 하이라이팅 — 이 사이트에 코드 블록 없음
            tokens[name] = value.strip()

    light_lines: list[str] = []
    dark_lines: list[str] = []
    for name, value in tokens.items():
        lv, dv = split_light_dark(value)
        dark_lines.append(f"    {name}:{dv};")
        if lv != dv:
            light_lines.append(f"    {name}:{lv};")

    for name, value in {**SPACING, **SIZES, **WEIGHTS}.items():
        dark_lines.append(f"    {name}:{value};")

    out = [
        "  /* ═══ astryx econ tokens — GENERATED, 손으로 고치지 말 것 ═══",
        "     source : C:\\Users\\cgpar\\astryx\\econ.theme.ts",
        "     rebuild: astryx theme build econ.theme.ts --out dist/econ.css",
        "              && python scripts/build_astryx_tokens.py",
        "     light-dark()/@scope 는 구형 웹뷰 호환을 위해 두 블록으로 펼쳐 둠. */",
        "  :root {",
        "    color-scheme: dark;",
        *dark_lines,
        "  }",
        "  html.light {",
        "    color-scheme: light;",
        *light_lines,
        "  }",
        "  /* ═══ /astryx econ tokens ═══ */",
    ]
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔에서도 UTF-8 로 출력
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
