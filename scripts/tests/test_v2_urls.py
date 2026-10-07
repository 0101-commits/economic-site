"""사건 url 게이트 — 알림 카드의 주소가 앱에 실제로 있는 화면 · 변수 · 값인지 본다."""
import os
import re
import sys
import warnings

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import schema  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "..", "app", "src")
READ = r"(?:useViewParam(?:<[^>]*>)?\(|searchParams\.get\()\s*'([A-Za-z_]+)'"
EVENTS = [e for e in schema.load_events() if e.get("url")]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _routes():
    """{경로 패턴: 화면 이름} — App.tsx 의 <Route path=… element={…}>.
    감싼 부품(<PinGate> 등)은 건너뛰고 screens/ 에 파일이 있는 안쪽 화면을 잡는다."""
    out = {}
    for p, el in re.findall(r'<Route path="([^"*]+)" element=\{(.*)\} />', _read(os.path.join(SRC, "App.tsx"))):
        tags = re.findall(r"<(\w+)", el)
        screens = [t for t in tags if os.path.isfile(os.path.join(SRC, "screens", t + ".tsx"))]
        out[p] = (screens or tags)[0]
    return out


def _files(name, params):
    """화면 파일 + 그 화면이 쓰는 부품 폴더(market · lens …). 화면이 a= 로 부품을 고르면(시장 ASSETS 의 Body)
    다른 자산군 부품은 뺀다 — 같은 v= 라도 자산군마다 허용 값이 다르다."""
    screen = os.path.join(SRC, "screens", name + ".tsx")
    folder = os.path.join(SRC, "components", name.lower())
    parts = [os.path.join(folder, f) for f in sorted(os.listdir(folder))] if os.path.isdir(folder) else []
    bodies = dict(re.findall(r"key: '(\w+)'[^}\n]*Body: (\w+)", _read(screen)))
    pick = bodies.get(params.get("a"))
    if pick:
        stem = lambda p: os.path.splitext(os.path.basename(p))[0]  # noqa: E731
        parts = [p for p in parts if stem(p) == pick or stem(p) not in bodies.values()]
    return [screen] + parts


def _allowed(src, arg):
    """useViewParam 세 번째 인자 → 허용 값 집합. 리터럴 배열 · 같은 파일 상수(X 또는 X.map(o => o.key))만 읽고, 못 읽으면 None."""
    arg = arg.strip()
    if arg.startswith("["):
        return set(re.findall(r"'([^']*)'", arg))
    m = re.fullmatch(r"(\w+)(\.map\(\s*\w+\s*=>\s*\w+\.key\s*\))?", arg)
    d = m and re.search(r"^const " + m[1] + r"\b[^=]*=\s*\[(.*?)\]\s*(?:as const)?\s*$", src, re.M | re.S)
    if not d:
        return None
    return set(re.findall(r"key:\s*'([^']*)'" if m[2] else r"'([^']*)'", d[1]))


def _reads(src, k):
    """이 파일이 변수 k 를 읽는 곳마다 허용 목록 — 'any'(목록 없음) · 집합 · None(못 읽음)."""
    out = ["any"] * len(re.findall(r"searchParams\.get\(\s*'%s'" % k, src))
    for arg in re.findall(r"useViewParam(?:<[^>]*>)?\(\s*'%s'\s*,\s*'[^']*'\s*(,.*)?\)\s*$" % k, src, re.M):
        out.append("any" if not arg else _allowed(src, arg[1:]))
    return out


def _match(path, patterns):
    for p in patterns:
        if re.fullmatch(re.sub(r":\w+", "[^/]+", re.sub(r"\{[^}]*\}", "x", p)), re.sub(r"\{[^}]*\}", "x", path)):
            return p
    return None


def _check(url):
    """(틀린 것 목록, 값 대조를 건너뛴 수). 틀 변수 {…} 값은 대조하지 않는다."""
    routes = _routes()
    path, _, query = url[2:].partition("?")
    route = _match("/" + path, routes)
    if not route:
        return [f"경로 /{path} 가 App.tsx 의 Route 에 없음 ({sorted(routes)})"], 0
    screen = routes[route]
    params = dict(p.partition("=")[::2] for p in query.split("&") if p)
    srcs = [_read(f) for f in _files(screen, params)]
    have = {n for s in srcs for n in re.findall(READ, s)}
    errs, skipped = [], 0
    for k, v in params.items():
        if k not in have:
            errs.append(f"변수 '{k}' 를 {screen} 화면이 읽지 않음 (읽는 것: {sorted(have)})")
            continue
        reads = [r for s in srcs for r in _reads(s, k)]
        if "{" in v or "any" in reads:
            continue
        if not reads or None in reads:
            skipped += 1
            continue
        ok = set().union(*reads)
        if v not in ok:
            errs.append(f"변수 {k}={v} 가 {screen} 화면의 허용 목록에 없음 ({sorted(ok)})")
    return errs, skipped


@pytest.mark.parametrize("ev", EVENTS, ids=lambda e: e["id"])
def test_url_matches_app(ev):
    url = ev["url"]
    assert url.startswith("#/"), f"{ev['id']} {url}: '#/' 로 시작하지 않음"
    errs, _ = _check(url)
    assert not errs, f"{ev['id']} {url}: " + " · ".join(errs)


def test_url_value_skips_reported():
    """허용 목록을 못 읽어 값 대조를 건너뛴 수 — 0 이 아니면 경고로 드러낸다(다른 파일 상수 · 계산된 목록)."""
    skipped = sum(_check(e["url"])[1] for e in EVENTS if e["url"].startswith("#/"))
    print(f"사건 url 값 대조 건너뜀: {skipped}건")
    if skipped:
        warnings.warn(f"사건 url 값 대조를 {skipped}건 건너뜀 — 허용 목록을 같은 파일에서 읽지 못했다")


def test_checker_catches_bad_value_and_wrapped_screen():
    """게이트 자가검사: 다른 자산군의 보기 값 · 없는 값은 잡고, PinGate 로 감싼 화면은 안쪽 화면으로 본다."""
    assert _check("#/market?a=commod&v=gainers")[0], "원자재에 없는 보기 gainers 를 놓침"
    assert _check("#/market?a=macro&v=calender")[0], "철자 틀린 값을 놓침"
    assert _check("#/market?a=kr&v=gainers") == ([], 0)
    assert _routes()["/settings"] == "Settings"
