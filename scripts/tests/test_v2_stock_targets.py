"""종목 대상 사용자 조건 — U1 · U2 · B1 이 종목(국내 6자리 · 미국 티커) 값을 찾는가.

2026-10-09 실측: 운영 /prefs 의 사용자 조건 36건이 전부 종목 대상이었는데 Context 가 종목 값을 몰라
10/6(ALERTS_V2=1) 이후 한 건도 울리지 않았다. 네트워크는 전부 가짜(check_alerts.get_snapshot 을 바꿔 끼운다).
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import check_alerts as ca  # noqa: E402
from alerts_v2 import compose, subscribe  # noqa: E402
from alerts_v2.context import KST, Context  # noqa: E402

OPEN = dt.datetime(2026, 10, 7, 10, 0, tzinfo=KST)        # 수요일 장중


def _snap(price, pct, prior, today="2026-10-07"):
    """prior = 오늘 앞 종가들(오래된 순). 끝 봉 = 오늘(현재가)."""
    d0 = dt.date.fromisoformat(today)
    dates = [(d0 - dt.timedelta(days=len(prior) - i)).isoformat() for i in range(len(prior))] + [today]
    return {"price": price, "pct": pct, "closes": list(prior) + [price], "dates": dates, "fresh": True,
            "highs": [], "lows": [], "vol_today": None, "vol_prev": None}


def _fake(monkeypatch, table):
    """table: 종목 → 스냅샷 · None · 예외. 부른 (시장, 종목) 을 순서대로 돌려준다."""
    calls = []

    def get_snapshot(market, symbol, yahoo_sym):
        calls.append((market, symbol))
        v = table.get(symbol)
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(ca, "get_snapshot", get_snapshot)
    return calls


def _ctx(now=OPEN, bundles=None):
    data = {"stockFlows": {"items": {"005930": {"name": "삼성전자"}, "0051G0": {"name": "SOL 미국원자력SMR"}}}}
    return Context(now=now, data=data, bundles=bundles or {}, registry={}, mer={})


def _hits(ctx, conds):
    prefs = {"alerts": [dict(c, enabled=True, repeat="each") for c in conds]}
    return subscribe.user_hits(ctx, prefs, [], render=lambda ev, h: compose.render(ev, h, ctx), log=lambda *a: None)


def test_u1_stock_up_and_down(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    _fake(monkeypatch, {"005930": _snap(71000, 1.2, [70000] * 70)})
    rows = _hits(_ctx(), [{"id": "a", "event": "U1", "target": "005930", "dir": "up", "value": 70500},
                          {"id": "b", "event": "U1", "target": "005930", "dir": "down", "value": 72000},
                          {"id": "c", "event": "U1", "target": "005930", "dir": "up", "value": 80000},
                          {"id": "d", "event": "U1", "target": "005930", "dir": "down", "value": 60000}])
    assert [(r["cond"], r["dir"]) for r in rows] == [("a", "up"), ("b", "down")]
    assert rows[0]["key"].startswith("U1:005930:up:") and rows[0]["asOf"] == "2026-10-07"
    assert rows[0]["title"].startswith("삼성전자 71,000") and rows[0]["fresh"] == "live"
    assert "70500" not in rows[0]["key"] + rows[0]["title"]                  # 임계값은 공개 원장에 없다(G5)


def test_u2_stock_both_directions(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    _fake(monkeypatch, {"005930": _snap(68000, -3.4, [70400] * 70), "0051G0": _snap(10500, 5.0, [10000] * 70)})
    rows = _hits(_ctx(), [{"id": "a", "event": "U2", "target": "005930", "value": 3},
                          {"id": "b", "event": "U2", "target": "005930", "value": 5},
                          {"id": "c", "event": "U2", "target": "0051G0", "value": 3}])
    assert [(r["cond"], r["dir"]) for r in rows] == [("a", "down"), ("c", "up")]
    assert rows[1]["title"].startswith("SOL 미국원자력SMR +5.0%")


def test_b1_stock_new_high_first_day_only(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    prior = [100.0 + (i % 7) for i in range(80)]                             # 직전 최고 106
    _fake(monkeypatch, {"005930": _snap(110, 2.0, prior), "0051G0": _snap(110, 1.0, prior[:-1] + [108.0])})
    rows = _hits(_ctx(), [{"id": "a", "event": "B1", "target": "005930"},
                          {"id": "b", "event": "B1", "target": "005930", "dir": "down"},     # 신저가만 원함
                          {"id": "c", "event": "B1", "target": "0051G0"}])                # 어제(108)도 신고가 — 이어지는 기록
    assert [(r["cond"], r["event"], r["dir"]) for r in rows] == [("a", "B1", "up")]
    assert rows[0]["key"].startswith("B1:005930:up:") and "52주" in rows[0]["title"]
    assert "106" in rows[0]["why"]                                            # 사전 B1 틀 = 직전 최고와 그 날짜


def test_b1_needs_sixty_bars(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    _fake(monkeypatch, {"0051G0": _snap(110, 2.0, [100.0] * 30)})          # 상장 30일 — 옛 판정과 같이 판정하지 않는다
    assert _hits(_ctx(), [{"id": "a", "event": "B1", "target": "0051G0"}]) == []


def test_fetch_failure_skips_only_that_stock(monkeypatch, capsys):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    calls = _fake(monkeypatch, {"000660": RuntimeError("boom"), "035420": None,
                                "005930": _snap(71000, 1.2, [70000] * 70)})
    rows = _hits(_ctx(), [{"id": "x", "event": "U1", "target": "000660", "dir": "up", "value": 1},
                          {"id": "y", "event": "U2", "target": "035420", "value": 0.1},
                          {"id": "a", "event": "U1", "target": "005930", "dir": "up", "value": 70500},
                          {"id": "k", "event": "U1", "target": "usdkrw", "dir": "up", "value": 1}])
    assert [r["cond"] for r in rows] == ["a"]
    out = capsys.readouterr().out
    assert "000660(RuntimeError)" in out and "035420(조회 실패)" in out
    assert ("KR", "000660") in calls and ("KR", "005930") in calls


def test_bundle_row_first_without_fetch(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    calls = _fake(monkeypatch, {"005930": _snap(1, 0.0, [1] * 70), "000660": _snap(250000, 0.5, [249000] * 70)})
    bundles = {"market-domestic": {"views": {
        "amount": {"asOf": "2026-10-07", "state": "live",
                   "items": [{"code": "005930", "name": "삼성전자", "price": 71000.0, "chgPct": -3.5}]},
        "marketCap": {"asOf": "2026-10-06", "state": "prev",                 # 어제 칸 — 쓰지 않는다
                      "kospi": [{"code": "000660", "name": "SK하이닉스", "price": 1.0, "chgPct": 0.0}]}}}}
    ctx = _ctx(bundles=bundles)
    rows = _hits(ctx, [{"id": "a", "event": "U1", "target": "005930", "dir": "up", "value": 70500},
                       {"id": "b", "event": "U2", "target": "005930", "value": 3}])
    assert [(r["cond"], r["value"]) for r in rows] == [("a", 71000.0), ("b", 71000.0)]
    assert calls == []                                                        # 화면과 같은 값 — 조회 0
    q = ctx.stock("000660")
    assert calls == [("KR", "000660")]                                        # 어제 칸만 있으면 조회
    assert (q["value"], q["name"]) == (250000, "SK하이닉스")                   # 값은 조회, 이름은 묶음


def test_one_fetch_per_stock_per_run(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    calls = _fake(monkeypatch, {"005930": _snap(71000, 1.2, [70000.0] * 70), "000660": None})
    _hits(_ctx(), [{"id": "a", "event": "U1", "target": "005930", "dir": "up", "value": 70500},
                   {"id": "b", "event": "U2", "target": "005930", "value": 1},
                   {"id": "c", "event": "B1", "target": "005930"},
                   {"id": "d", "event": "U1", "target": "000660", "dir": "up", "value": 1},
                   {"id": "e", "event": "U2", "target": "000660", "value": 1}])
    assert sorted(calls) == [("KR", "000660"), ("KR", "005930")]


def test_closed_market_and_holiday_skip(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    calls = _fake(monkeypatch, {"005930": _snap(71000, 1.2, [70000] * 70)})
    cond = [{"id": "a", "event": "U1", "target": "005930", "dir": "up", "value": 1}]
    assert _hits(_ctx(now=dt.datetime(2026, 10, 7, 20, 0, tzinfo=KST)), cond) == []   # 장 밖 — 조회도 안 한다
    assert calls == []
    stale = dict(_snap(71000, 0.0, [70000] * 70), fresh=False)                         # 휴장 — 마지막 봉이 오늘 아님
    _fake(monkeypatch, {"005930": stale})
    assert _hits(_ctx(), cond) == []


def test_us_ticker_uses_us_market(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    calls = _fake(monkeypatch, {"NVDA": _snap(190.0, 4.2, [182.0] * 70, today="2026-10-07")})
    rows = _hits(_ctx(now=dt.datetime(2026, 10, 7, 23, 30, tzinfo=KST)),
                 [{"id": "a", "event": "U2", "target": "NVDA", "value": 4}])
    assert calls == [("US", "NVDA")] and rows[0]["key"].startswith("U2:NVDA:up:")


def test_naver_snapshot_dates_align_with_closes(monkeypatch):
    """52주 판정이 쓰는 일봉 날짜 — 현재가를 덧붙인 경우까지 closes 와 같은 길이."""
    now = dt.datetime(2026, 10, 7, 10, 0, tzinfo=KST)
    monkeypatch.setattr(ca, "_now", lambda: now)
    monkeypatch.setattr(ca, "_http_get_json", lambda url, mobile=False: {"closePrice": "71,000", "fluctuationsRatio": "1.2"})
    rows = "".join(f'["202610{d:02d}", 1, 2, 1, {70000 + d}, 10],' for d in (5, 6))
    monkeypatch.setattr(ca, "_http_get_text", lambda url: f"[{rows}]" + " " * 60)
    s = ca.naver_snapshot("005930")
    assert s["dates"] == ["2026-10-05", "2026-10-06", "2026-10-07"] and s["closes"][-1] == 71000.0
    assert len(s["dates"]) == len(s["closes"])
