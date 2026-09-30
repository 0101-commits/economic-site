import os, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fetch_fundamentals as ff


def test_etf_excluded_and_us_loop(tmp_path, monkeypatch):
    cfg = tmp_path / "c.json"
    cfg.write_text('{"tracking":{"items":['
        '{"symbol":"360750","market":"KR","secType":"etf"},'
        '{"symbol":"005930","market":"KR","name":"삼성전자"},'
        '{"symbol":"AAPL","market":"US"}]}}', encoding="utf-8")
    monkeypatch.setattr(ff, "CFG_PATH", str(cfg))
    monkeypatch.setattr(ff, "OUT_PATH", str(tmp_path / "f.json"))
    monkeypatch.setattr(ff, "DART_KEY", "")
    monkeypatch.setattr(ff.time, "sleep", lambda s: None)
    kr, us = ff.load_symbols()
    assert [k["code"] for k in kr] == ["005930"] and us == {"AAPL": "AAPL"}

    class T:
        info = {"trailingPE": 30.5, "returnOnEquity": 0.5}
        calendar = {"Earnings Date": ["2026-10-30"]}
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=lambda s: T()))
    ff.main()
    import json
    out = json.load(open(ff.OUT_PATH, encoding="utf-8"))
    assert out["us"]["AAPL"]["per"] == 30.5 and out["us"]["AAPL"]["earningsDate"] == "2026-10-30"
    assert out["kr"] == {}
