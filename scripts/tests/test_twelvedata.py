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


def _seq(monkeypatch, fn, calls):
    monkeypatch.setattr(td.time, "sleep", lambda *_: None)
    def get(url, params=None, timeout=None):
        calls.append(params)
        return R(fn(params))
    monkeypatch.setattr(td.requests, "get", get)


def test_top_level_error_falls_back_per_symbol(monkeypatch):
    setup(monkeypatch)
    calls = []
    def fn(p):
        if "," in p["symbol"]:
            return {"code": 400, "message": "bad symbol", "status": "error"}
        return {"symbol": p["symbol"], "close": "10", "previous_close": "10", "datetime": "d"}
    _seq(monkeypatch, fn, calls)
    out = td.quote(["^N225", "^HSI"], log=lambda *_: None)
    assert out["^N225"]["price"] == 10 and out["^HSI"]["price"] == 10 and len(calls) == 3


def test_proxy_for_failed_us_index(monkeypatch):
    setup(monkeypatch)
    calls = []
    def fn(p):
        s = p["symbol"]
        if s == "SPX,N225":
            return {"SPX": {"status": "error", "message": "plan"}, "N225": {"close": "1", "previous_close": "1"}}
        if s == "SPY":
            return {"symbol": "SPY", "close": "500", "previous_close": "495", "percent_change": "1.0"}
        return {"status": "error", "message": "x"}
    _seq(monkeypatch, fn, calls)
    out = td.quote(["^GSPC", "^N225"], log=lambda *_: None)
    assert "^GSPC" not in out and out["^N225"]["price"] == 1
    px = out["_proxies"]["^GSPC"]
    assert px["proxy"] == "SPY" and px["fill_ok"] is False
    r = td.cross_check({"^GSPC": {"price": 5000, "change": 0.8}}, out)
    assert r[-1]["proxy"] == "SPY" and r[-1]["ok"]


def test_shanghai_exchange_form(monkeypatch):
    setup(monkeypatch)
    calls = []
    def fn(p):
        if p.get("exchange") == "XSHG":
            return {"symbol": "000001", "close": "3000", "previous_close": "3000"}
        return {"status": "error", "message": "bad"}
    _seq(monkeypatch, fn, calls)
    out = td.quote(["000001.SS"], log=lambda *_: None)
    assert out["000001.SS"]["price"] == 3000


def test_cross_check():
    r = td.cross_check({"^GSPC": {"price": 100}, "^HSI": 200},
                       {"^GSPC": {"price": 100.5}, "^HSI": {"price": 205}, "^N225": {"price": 1}})
    d = {x["sym"]: x for x in r}
    assert d["^GSPC"]["ok"] and not d["^HSI"]["ok"] and "^N225" not in d
