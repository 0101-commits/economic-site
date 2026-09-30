"""P0 수집기 정비 회귀 테스트 (오프라인 — 네트워크를 부르지 않는다).

원천 이전(EXIM)·KRX 401 가드·호스트별 실패 기록·보존 표식·일본 CPI 전년동월비·연속 실패 누적.
실행: python -m pytest scripts/tests/test_p0_collector.py
"""
import os
import sys
import types
from urllib.parse import urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fetch_data as fd  # noqa: E402


class _Resp:
    def __init__(self, code=200, payload=None):
        self.status_code = code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise fd._requests.exceptions.HTTPError(f"{self.status_code}")


def test_exim_moved_to_oapi_host():
    assert urlsplit(fd.EXIM_BASE).hostname == "oapi.koreaexim.go.kr"


def test_breaker_counts_4xx_response_as_fail():
    hb = fd._HostBreaker()
    hb._call(lambda url, *a, **kw: _Resp(401), "https://data-dbg.krx.co.kr/svc/apis/idx/x?basDd=1")
    hb._call(lambda url, *a, **kw: _Resp(200), "https://api.stlouisfed.org/fred/x")
    snap = hb.status_snapshot()
    krx = snap["data-dbg.krx.co.kr"]
    assert (krx["calls"], krx["fails"], krx["lastError"], krx["lastOkAt"]) == (1, 1, "HTTP 401", None)
    assert snap["api.stlouisfed.org"]["fails"] == 0 and snap["api.stlouisfed.org"]["lastOkAt"]


def test_breaker_error_text_drops_url_and_query():
    hb = fd._HostBreaker()

    def boom(url, *a, **kw):
        raise fd._requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='ecos.bok.or.kr', port=443): Max retries exceeded with url: "
            "/api/StatisticSearch/SECRETKEY123/json?x=1 (Caused by timeout)")
    try:
        hb._call(boom, "https://ecos.bok.or.kr/api/StatisticSearch/SECRETKEY123/json?x=1")
    except fd._requests.exceptions.ConnectionError:
        pass
    err = hb.status_snapshot()["ecos.bok.or.kr"]["lastError"]
    assert "SECRETKEY123" not in err and "?" not in err and len(err) <= 120, err


def test_krx_401_stops_further_calls(monkeypatch):
    calls = []

    class _Fake:
        def get(self, url, **kw):
            calls.append(url)
            return _Resp(401)

    monkeypatch.setattr(fd, "requests", _Fake())
    monkeypatch.setattr(fd, "KRX_API_KEY", "k" * 12)
    monkeypatch.setattr(fd, "_KRX_DENIED", set())
    monkeypatch.setattr(fd, "_KRX_ROWS", {})
    # 이용신청은 서비스별이라 401 도 엔드포인트별로 막는다(A19) — 한 엔드포인트에 한 번, 날짜 되짚기는 안 한다
    assert fd.fetch_krx("/idx/kospi_dd_trd", "20260929") is None
    assert fd.fetch_krx("/idx/kospi_dd_trd", "20260928") is None
    assert fd.fetch_krx("/gen/gold_bydd_trd", "20260929") is None
    assert fd.fetch_krx_latest("/etp/etf_bydd_trd") == (None, None)
    assert len(calls) == 3


def test_restore_marks_preserved_and_leaves_prev_untouched():
    cur = {"us": {"a": {"value": 1}}}
    prev = {"us": {"a": {"value": 0.5}, "b": {"value": 2}},
            "jp": {"x": {"value": 3}},
            "kr": {"old": {"value": 4, "preserved": True, "preservedAt": "2026-09-01T00:00:00+09:00"}}}
    assert fd._restore_missing_metrics(cur, prev) == 3
    assert "preserved" not in cur["us"]["a"]                      # 이번 런 값은 표식 없음
    assert cur["us"]["b"]["preserved"] is True and cur["us"]["b"]["preservedAt"]
    assert cur["jp"]["x"]["preserved"] is True                    # 컨테이너째 복원 → 잎마다 표식
    assert cur["kr"]["old"]["preservedAt"] == "2026-09-01T00:00:00+09:00"   # 처음 되살린 시각 유지
    assert "preserved" not in prev["us"]["b"]                     # prev 는 읽기 전용


def test_preserve_from_prev_marks_restored_leaf():
    data = {"sentiment": {}}
    prev = {"sentiment": {"vkospi": {"value": 20, "as_of": "2026-09-29"}}}
    assert fd._preserve_from_prev(data, prev, ["sentiment.vkospi"]) == 1
    assert data["sentiment"]["vkospi"]["preserved"] is True


def _cpi_fixture():
    periods = [f"{y}-{m:02d}" for y in (2025, 2026) for m in range(1, 13)][:20]   # 2025-01 ~ 2026-08
    values = [100 + i for i in range(20)]
    values[3] = "NA"                                                            # 2025-04 결측
    return {"series": {"docs": [{"period": periods, "value": values}]}}


def test_yoy_series_matches_same_month_last_year():
    doc = _cpi_fixture()["series"]["docs"][0]
    out = fd._yoy_series(doc["period"], doc["value"])
    assert out[0] == ("2026-01", 12.0)            # 112 / 100
    assert "2026-04" not in dict(out)              # 기준 달이 NA 면 건너뛴다
    assert out[-1] == ("2026-08", round((119 / 107 - 1) * 100, 1))


def test_fetch_dbnomics_cpi_jp_node_shape(monkeypatch):
    class _Fake:
        def get(self, url, **kw):
            assert "observations=1" in url
            return _Resp(200, _cpi_fixture())

    monkeypatch.setattr(fd, "requests", _Fake())
    node = fd.fetch_dbnomics_cpi_jp()
    assert node["period"] == "2026-08-01" and node["value"] == round((119 / 107 - 1) * 100, 1)
    assert node["source"].startswith("DBnomics STATJP/CPIm")
    assert set(node) == {"value", "period", "desc", "source", "history"}
    assert all(k.endswith("-01") for k in node["history"])


def test_source_status_streak_and_alert(monkeypatch):
    snap = {"dead.example": {"calls": 3, "fails": 3, "lastError": "HTTP 401", "lastOkAt": None},
            "ok.example": {"calls": 2, "fails": 1, "lastError": "HTTP 500", "lastOkAt": "2026-09-30T10:00:00+09:00"}}
    prev = {"dead.example": {"consecutiveFailRuns": 99, "lastOkAt": "2026-09-01T00:00:00+09:00"},
            "ok.example": {"consecutiveFailRuns": 7, "alertedAt": "2026-09-20T00:00:00+09:00"},
            "daily.example": {"calls": 1, "fails": 1, "consecutiveFailRuns": 2}}
    ss = fd._source_status(snap, prev)
    assert list(ss) == sorted(ss)
    assert ss["dead.example"]["consecutiveFailRuns"] == 100
    assert ss["dead.example"]["lastOkAt"] == "2026-09-01T00:00:00+09:00"   # 마지막 성공 시각은 이어받는다
    assert ss["ok.example"]["consecutiveFailRuns"] == 0 and "alertedAt" not in ss["ok.example"]
    assert ss["daily.example"] == prev["daily.example"]                   # 이번 런 미호출 → 그대로

    sent = []
    monkeypatch.setitem(sys.modules, "notify_discord",
                        types.SimpleNamespace(system=lambda text, **kw: sent.append(text) or True))
    fd._alert_dead_sources(ss)
    fd._alert_dead_sources(ss)                                             # 두 번째는 alertedAt 때문에 조용
    assert len(sent) == 1 and "dead.example" in sent[0] and ss["dead.example"]["alertedAt"]
    nxt = fd._source_status(snap, ss)
    assert nxt["dead.example"]["consecutiveFailRuns"] == 101 and nxt["dead.example"]["alertedAt"]
