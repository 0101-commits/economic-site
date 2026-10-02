"""데이터 결함 회귀 검사(2026-10-02, 오프라인 — 가짜 자료만).

1) 코스피 등락상위에 코스닥이 섞이던 결함 — 토스 랭킹은 KR 통합이라 시장별로 갈라 담아야 한다.
2) fundamentals.json 종목 0 — 관심목록이 ETF 뿐이라 대상이 비었다. 배당·실적 일정 대상(corpEvents.corpMap)을 같이 쓴다.
실행: python -m pytest scripts/tests/test_movers_fundamentals.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fetch_data as fd  # noqa: E402
import fetch_fundamentals as ff  # noqa: E402
import toss_api  # noqa: E402

DAY = "2026-10-02"
# 등락률 순: 코스닥이 위를 덮는 실제 모양(2026-10-02 실측 10개 중 8개 코스닥)
RANK = [{"code": f"K{i:05d}", "price": 1000 + i, "chg": 29.9 - i, "vol": 5000 + i, "amount": 1} for i in range(14)]
META = {r["code"]: {"name": "가" + r["code"], "type": "STOCK", "market": "KOSDAQ"} for r in RANK}
for c in ("K00002", "K00007", "K00011"):
    META[c]["market"] = "KOSPI"
META["K00004"] = {"name": "어떤ETF", "type": "ETF", "market": "KOSPI"}


def test_movers_split_by_market(monkeypatch):
    monkeypatch.setattr(toss_api, "rankings", lambda *a, **k: RANK)
    monkeypatch.setattr(toss_api, "stocks", lambda codes: META)
    got = toss_api.movers("TOP_GAINERS", DAY, top_n=10)
    assert [r["code"] for r in got["KOSPI"]] == ["K00002", "K00007", "K00011"]   # 모자라면 있는 만큼만 — 채우지 않는다
    assert all(r["market"] == "KOSPI" and r["as_of"] == DAY for r in got["KOSPI"])
    assert len(got["KOSDAQ"]) == 10 and all(r["market"] == "KOSDAQ" for r in got["KOSDAQ"])
    assert [r["code"] for r in got["ETF"]] == ["K00004"]          # ETF 는 시장 칸에 들어가지 않는다


def test_direct_toss_movers_return_kospi_only(monkeypatch):
    monkeypatch.setattr(toss_api, "enabled", lambda: True)
    monkeypatch.setattr(toss_api, "rankings", lambda *a, **k: RANK)
    monkeypatch.setattr(toss_api, "stocks", lambda codes: META)
    monkeypatch.setattr(fd, "_kr_session_date", lambda: DAY)
    g, l = fd.fetch_toss_stock_movers(top_n=10)
    assert {r["market"] for r in g} == {"KOSPI"} and len(g) == 3


def test_old_mixed_snapshot_is_filtered():
    row = lambda code, mk, d=DAY: {"code": code, "chg": 5.0, "price": 1, "vol": 2, "market": mk, "as_of": d}
    snap = {"stockMovers": {"kospiGainers": [row("A", "KOSDAQ"), row("B", "KOSPI"), row("C", "KOSDAQ")],
                            "kospiLosers": [row("D", "KOSPI", "2026-10-01")]}}
    g, l = fd._snapshot_kospi_movers(snap, DAY)
    assert [r["code"] for r in g] == ["B"]
    assert l is None                                   # 어제 목록은 오늘 것으로 쓰지 않는다
    assert fd._snapshot_kospi_movers({"stockMovers": {"kospiGainers": [row("A", "KOSDAQ")]}}, DAY) == (None, None)


def test_fundamentals_targets_include_corp_events(tmp_path, monkeypatch):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"tracking": {"items": [{"symbol": "360750", "market": "KR", "secType": "etf"}]}}),
                   encoding="utf-8")
    data = {"rankingsKr": {"tradingAmount": [{"code": "005930", "name": "삼성전자"}]},
            "corpEvents": {"corpMap": {"005930": "00126380", "005935": ""}}}
    (tmp_path / "d.json").write_text(json.dumps(data), encoding="utf-8")
    out_p = tmp_path / "f.json"
    out_p.write_text(json.dumps({"kr": {"999999": {"name": "빠진종목"}}, "corpMap": {"999999": "1"}}), encoding="utf-8")
    monkeypatch.setattr(ff, "CFG_PATH", str(cfg))
    monkeypatch.setattr(ff, "DATA_PATH", str(tmp_path / "d.json"))
    monkeypatch.setattr(ff, "OUT_PATH", str(out_p))
    monkeypatch.setattr(ff, "DART_KEY", "dummy")

    def no_net(*a, **k):
        raise AssertionError("기업코드가 이미 있으면 목록 zip 을 받지 않는다")
    monkeypatch.setattr(ff.requests, "get", no_net)
    seen = []
    monkeypatch.setattr(ff, "fetch_kr_one", lambda cc, code, name, year: seen.append((cc, code, name)) or {"name": name, "eps": 1})

    kr, us = ff.load_symbols(data)
    assert [k["code"] for k in kr] == ["005930"] and us == {}       # ETF·기업코드 없는 우선주는 뺀다
    ff.main()
    out = json.load(open(out_p, encoding="utf-8"))
    assert seen == [("00126380", "005930", "삼성전자")]
    assert list(out["kr"]) == ["005930"]                             # 대상에서 빠진 종목은 잇지 않는다
    assert out["corpMap"] == {"005930": "00126380"}
