#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""go.html 생성 — 카카오톡 링크가 네이버로 가게 하는 중계 페이지.

왜 필요한가(2026-09-22 실측):
  카카오톡 메시지의 link.web_url 은 **카카오 앱에 등록된 사이트 도메인**이어야 한다.
  미등록 도메인을 넣으면 카카오가 조용히 도메인만 등록된 것으로 바꾸고 경로는 그대로
  둔다 — finance.naver.com/sise/sise_index.naver?code=KOSPI 가
  0101-commits.github.io/sise/sise_index.naver?code=KOSPI 로 바뀌어 GitHub 404 가 떴다
  (13:16 발송본). KAKAO_SETUP.md 에 이미 적혀 있던 함정인데 링크를 네이버로 돌리면서
  놓쳤다. 디스코드는 이 제약이 없어 직접 링크를 그대로 쓴다.

해결: 등록된 도메인 위에 중계 페이지를 두고 카카오만 여기를 거친다.
  /economic-site/go.html?k=KOSPI     → 지표 네이버 페이지
  /economic-site/go.html?s=005930    → 종목 네이버 페이지
  그 외·미지의 키                     → 대시보드(깨진 링크 대신 늘 갈 곳이 있다)

열린 리다이렉트가 되지 않게 **URL 을 받지 않는다** — 화이트리스트 키와 6자리 숫자만
받는다. 임의 URL 파라미터를 허용하면 우리 도메인이 피싱 중계기가 된다.

재생성: python scripts/build_go_page.py   (검사: --check)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
OUT = os.path.join(ROOT, "go.html")

import notify_discord  # noqa: E402

DASH = "https://0101-commits.github.io/economic-site/"
STOCK = "https://finance.naver.com/item/main.naver?code="

TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>이동 중…</title>
<!-- 생성물 — 손으로 고치지 말 것. 재생성: python scripts/build_go_page.py
     카카오톡은 등록된 사이트 도메인으로만 링크할 수 있어, 카톡 알림의 링크가 이 페이지를
     거쳐 네이버로 간다(디스코드는 직접 링크). 상세 경위는 scripts/build_go_page.py. -->
<style>
  body {{ margin: 0; display: flex; min-height: 100vh; align-items: center;
         justify-content: center; font-family: system-ui, -apple-system, sans-serif;
         background: #fff; color: #1a1c20; }}
  main {{ text-align: center; padding: 24px; }}
  a {{ color: #135fcd; }}
  @media (prefers-color-scheme: dark) {{ body {{ background: #14161a; color: #e8eaed; }}
                                        a {{ color: #41a2f9; }} }}
</style>
</head>
<body>
<main>
  <p id="msg">네이버 증권으로 이동 중…</p>
  <p><a id="fallback" href="{dash}">바로 열리지 않으면 여기를 누르세요</a></p>
</main>
<script>
// 화이트리스트만 — 임의 URL 은 받지 않는다(열린 리다이렉트 방지).
var LINKS = {links};
var DASH = {dash_js};
(function () {{
  var q = new URLSearchParams(location.search);
  var k = q.get('k') || '';
  var s = q.get('s') || '';
  var to = null;
  if (k && Object.prototype.hasOwnProperty.call(LINKS, k)) to = LINKS[k];
  else if (/^[0-9]{{6}}$/.test(s)) to = {stock_js} + s;   // 국내 종목 6자리만
  if (!to) {{
    to = DASH;
    document.getElementById('msg').textContent = '대시보드로 이동 중…';
  }}
  document.getElementById('fallback').href = to;
  location.replace(to);
}})();
</script>
</body>
</html>
"""


def render():
    import json
    links = json.dumps(notify_discord.NAVER_LINKS, ensure_ascii=False, indent=2)
    return TEMPLATE.format(links=links, dash=DASH, dash_js=json.dumps(DASH),
                           stock_js=json.dumps(STOCK))


def main():
    html = render()
    if "--check" in sys.argv:
        cur = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if cur.replace("\r\n", "\n") != html:
            print("go.html 이 NAVER_LINKS 와 어긋난다 — python scripts/build_go_page.py 로 재생성할 것")
            return 1
        print("go.html ↔ NAVER_LINKS 일치")
        return 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    print(f"go.html 생성 — 지표 {len(notify_discord.NAVER_LINKS)}종 + 종목 6자리")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
