#!/usr/bin/env python3
"""인라인 font-size / font-weight 를 astryx 타입 스케일 토큰으로 스냅 (1회성).

astryx docs/typography 의 안티패턴 첫 줄:
  "Set font-size or line-height manually; use the semantic type scale tokens
   so the full ramp stays consistent and 4px-grid-aligned."

index.html 의 style="" 속성에는 font-size 가 1100곳, font-weight 가 350곳
직접 px/숫자로 박혀 있었다. 스케일 밖 값(11, 13, 15, 16, 18, 22, 26 …)이 섞여
있어 같은 위계의 텍스트가 화면마다 1~2px씩 어긋난다.

스냅 규칙
---------
astryx 기하 스케일(base 14, ratio 1.2): 6 7 8 10 12 14 17 20 24 29 35 42.
가장 가까운 단계로 스냅하되 **동점이면 큰 쪽**(11 -> 12, 13 -> 14, 22 -> 24).
작은 글자를 더 줄이면 한글 가독성이 나빠져서 올림 쪽을 택했다.
9px 이하는 xs(10px) 로 올려 최소 크기를 보장한다.

font-weight 는 400/500/600/700 -> normal/medium/semibold/bold 토큰으로.
800 은 astryx 에 대응 단계가 없어 bold(700) 로 접는다.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "index.html"

SCALE = [
    (6, "4xs"), (7, "3xs"), (8, "2xs"), (10, "xs"), (12, "sm"), (14, "base"),
    (17, "lg"), (20, "xl"), (24, "2xl"), (29, "3xl"), (35, "4xl"), (42, "5xl"),
]
MIN_PX = 10  # 이보다 작은 글자는 만들지 않는다

WEIGHTS = {"400": "normal", "500": "medium", "600": "semibold",
           "700": "bold", "800": "bold"}


def snap(px: int) -> str:
    """px -> --font-size-* 이름. 동점이면 큰 단계."""
    px = max(px, MIN_PX)
    return min(SCALE, key=lambda s: (abs(s[0] - px), -s[0]))[1]


def main() -> int:
    src = HTML.read_text(encoding="utf-8")
    shutil.copyfile(HTML, ROOT / "index.html.bak3")
    head, sep, body = src.partition("</style>")
    if not sep:
        raise SystemExit("</style> not found")

    stats = {"size": 0, "weight": 0}

    def fix_attr(m: re.Match[str]) -> str:
        s = m.group(1)

        def fs(mm: re.Match[str]) -> str:
            stats["size"] += 1
            return "font-size:var(--font-size-%s)" % snap(int(mm.group(1)))

        def fw(mm: re.Match[str]) -> str:
            name = WEIGHTS.get(mm.group(1))
            if not name:
                return mm.group(0)
            stats["weight"] += 1
            return "font-weight:var(--font-weight-%s)" % name

        s = re.sub(r"font-size:\s*(\d+)px", fs, s)
        s = re.sub(r"font-weight:\s*(\d00)\b", fw, s)
        return 'style="%s"' % s

    body = re.sub(r'style="([^"]*)"', fix_attr, body)
    HTML.write_text(head + sep + body, encoding="utf-8")
    print("font-size snapped: %d, font-weight tokenized: %d"
          % (stats["size"], stats["weight"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
