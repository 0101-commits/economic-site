# -*- coding: utf-8 -*-
"""링크 주소 단일 원천 — app_url.py 동작 + 옛 주소 하드코딩 재발 방지."""
import glob
import importlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import app_url  # noqa: E402

OLD = "0101-commits.github.io"

# (파일, 그 줄에 들어 있어야 하는 조각, 이유) — 이 줄만 옛 주소가 남아도 된다. 조각이 빈 문자열이면 파일 전체 허용.
ALLOW = [
    ("scripts/app_url.py", "", "단일 원천 — OLD_URL 정의"),
    ("cloudflare-worker/worker.js", "https://0101-commits.github.io',", "ALLOWED_ORIGINS — 옛 주소 출처도 계속 허용(이전 기간)"),
    ("app/src/lib/moved.ts", "", "옛 주소 안내 띠 — 옛 호스트를 알아봐야 한다"),
    ("cloudflare-pages/_worker.js", "", "넘김 장치의 원본 주소"),
    ("app/src/lib/refresh.test.ts", "buildOf('https://0101-commits.github.io/", "옛 주소 사본 자산 URL 에서 판 이름을 뽑는 시험 입력"),
    ("scripts/check_links.py", "", "링크 점검기 User-Agent 연락처"),
    ("index.html", "Naver Maps JS API v3", "네이버 지도 Client ID 가 옛 도메인에 등록됨 — 설명 주석"),
    ("scripts/build_go_page.py", "0101-commits.github.io/sise/", "카카오 도메인 치환 사고 설명 주석"),
    ("scripts/send_kakao_digest.py", "0101-commits.github.io/sise/", "카카오 도메인 치환 사고 설명 주석"),
]


def _allowed(rel, line):
    for f, frag, _ in ALLOW:
        if rel == f and frag in line:
            return True
    return rel.startswith("scripts/tests/")


def _targets():
    pats = ["scripts/**/*.py", "cloudflare-worker/worker.js", "cloudflare-pages/_worker.js",
            "index.html", "go.html", "app/index.html", "app/src/**/*.ts", "app/src/**/*.tsx"]
    seen = set()
    for p in pats:
        for f in glob.glob(os.path.join(ROOT, p), recursive=True):
            seen.add(os.path.relpath(f, ROOT).replace(os.sep, "/"))
    return sorted(seen)


def test_app_link():
    assert app_url.app_link("?p=market") == "https://ecom-terminal.pages.dev/?p=market"
    assert app_url.app_link() == "https://ecom-terminal.pages.dev/"
    assert app_url.OLD_URL == "https://0101-commits.github.io/economic-site/"


def test_env_override(monkeypatch):
    monkeypatch.setenv("APP_URL", "https://example.test/x/")
    try:
        m = importlib.reload(app_url)
        assert m.app_link("?a=1") == "https://example.test/x/?a=1"
    finally:
        monkeypatch.delenv("APP_URL", raising=False)
        importlib.reload(app_url)


def test_no_hardcoded_old_url():
    bad = []
    for rel in _targets():
        with open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                if OLD in line and not _allowed(rel, line):
                    bad.append(f"{rel}:{n}: {line.strip()[:100]}")
    assert not bad, "옛 주소 하드코딩:\n" + "\n".join(bad)
