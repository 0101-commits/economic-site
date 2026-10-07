"""사건 url 게이트 — 알림 카드의 주소가 앱에 실제로 있는 화면 · 변수인지 본다."""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import schema  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "..", "app", "src")
READ = r"(?:useViewParam(?:<[^>]*>)?\(|searchParams\.get\()\s*'([A-Za-z_]+)'"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _routes():
    """{경로 패턴: 화면 이름} — App.tsx 의 <Route path=… element={<X />}>."""
    return {p: x for p, x in re.findall(r'<Route path="([^"*]+)" element=\{<(\w+)', _read(os.path.join(SRC, "App.tsx")))}


def _screen_params(name):
    """화면 파일 + 그 화면이 쓰는 market/lens 부품 폴더에서 읽는 변수 이름 집합."""
    names = set(re.findall(READ, _read(os.path.join(SRC, "screens", name + ".tsx"))))
    folder = os.path.join(SRC, "components", name.lower())
    if os.path.isdir(folder):
        for fn in os.listdir(folder):
            names |= set(re.findall(READ, _read(os.path.join(folder, fn))))
    return names


def _match(path, patterns):
    for p in patterns:
        if re.fullmatch(re.sub(r":\w+", "[^/]+", re.sub(r"\{[^}]*\}", "x", p)), re.sub(r"\{[^}]*\}", "x", path)):
            return p
    return None


@pytest.mark.parametrize("ev", [e for e in schema.load_events() if e.get("url")], ids=lambda e: e["id"])
def test_url_matches_app(ev):
    url, routes = ev["url"], _routes()
    assert url.startswith("#/"), f"{ev['id']} {url}: '#/' 로 시작하지 않음"
    path, _, query = url[2:].partition("?")
    route = _match("/" + path, routes)
    assert route, f"{ev['id']} {url}: 경로 /{path} 가 App.tsx 의 Route 에 없음 ({sorted(routes)})"
    have = _screen_params(routes[route])
    for pair in filter(None, query.split("&")):
        k = pair.split("=")[0]
        assert k in have, f"{ev['id']} {url}: 변수 '{k}' 를 {routes[route]} 화면이 읽지 않음 (읽는 것: {sorted(have)})"
