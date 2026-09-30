import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import twelvedata as td  # noqa: E402


class R:
    def __init__(self, j): self._j = j
    def json(self): return self._j


def _stub(monkeypatch, payload, calls=None):
    def get(url, params=None, timeout=None):
        if calls is not None:
            calls.append(params)
        return R(payload)
    monkeypatch.setattr(td.requests, "get", get)


def setup(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "k")
    monkeypatch.setattr(td, "_last_call_ts", 0.0)


def test_disabled(monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    assert not td.enabled() and td.quote(["^GSPC"]) == {}


def test_batch_mapping(monkeypatch):
    setup(monkeypatch)
    calls = []
    _stub(monkeypatch, {"SPX": {"close": "5000", "previous_close": "4950", "percent_change": "1.01", "datetime": "2026-09-29"},
                        "000001:XSHG": {"close": "3000", "previous_close": "3030", "datetime": "2026-09-30"},
                        "HSI": {"status": "error", "code": 400}}, calls)
    out = td.quote(["^GSPC", "000001.SS", "^HSI", "^UNKNOWN"], log=lambda *_: None)
    assert calls[0]["symbol"] == "SPX,000001:XSHG,HSI"
    assert out["^GSPC"]["price"] == 5000 and out["^GSPC"]["source"] == "Twelve Data"
    assert abs(out["000001.SS"]["change_pct"] - (-0.990099)) < 1e-3
    assert "^HSI" not in out


def test_single_symbol_shape(monkeypatch):
    setup(monkeypatch)
    _stub(monkeypatch, {"symbol": "N225", "close": "40000", "previous_close": "39000", "datetime": "d"})
    assert td.quote(["^N225"])["^N225"]["price"] == 40000


def test_error_and_exception_return_empty(monkeypatch):
    setup(monkeypatch)
    _stub(monkeypatch, {"status": "error", "code": 429, "message": "limit"})
    assert td.quote(["^GSPC"], log=lambda *_: None) == {}
    monkeypatch.setattr(td, "_last_call_ts", 0.0)
    monkeypatch.setattr(td.requests, "get", lambda *a, **k: 1 / 0)
    assert td.quote(["^GSPC"], log=lambda *_: None) == {}


def test_rate_guard(monkeypatch):
    setup(monkeypatch)
    calls = []
    _stub(monkeypatch, {"SPX": {"close": "1"}}, calls)
    td.quote(["^GSPC"])
    assert td.quote(["^GSPC"], log=lambda *_: None) == {} and len(calls) == 1


def test_cross_check():
    r = td.cross_check({"^GSPC": {"price": 100}, "^HSI": 200},
                       {"^GSPC": {"price": 100.5}, "^HSI": {"price": 205}, "^N225": {"price": 1}})
    d = {x["sym"]: x for x in r}
    assert d["^GSPC"]["ok"] and not d["^HSI"]["ok"] and "^N225" not in d
