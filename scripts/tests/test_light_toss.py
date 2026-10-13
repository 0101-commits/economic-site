"""경량 런의 토스 스냅샷 목록(_light_toss) — 새 스냅샷의 오늘 목록만 받고, 못 받은 토스 목록엔 새 시각을 찍지 않는다.

실행: python -m pytest scripts/tests/test_light_toss.py -q
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import build_bundles as bb  # noqa: E402
import fetch_data as fd  # noqa: E402

D = "2026-10-13"
TOSS = "토스증권 Open API"


def _rows(mk="KOSPI", sign=1, as_of=D, n=5):
    return [{"name": f"종목{i}", "code": f"00000{i}", "price": 1000.0 + i, "chg": sign * (1.0 + i), "vol": 50000.0 + i,
             "market": mk, "as_of": as_of} for i in range(n)]


def test_light_run_takes_new_snapshot_lists(monkeypatch):
    snap = {"generatedAt": "2026-10-13T10:30:03+09:00",
            "stockMovers": {"kospiGainers": _rows(), "kospiLosers": _rows(sign=-1, as_of="2026-10-12")},   # 하락은 어제 것
            "etfMovers": {"etfGainers": _rows(mk="ETF")},
            "rankings": {"tradingAmount": [{"name": "SK하이닉스", "code": "000660", "amount": 4.9e12, "as_of": D}]},
            "stockData": [{"code": "005930"}]}
    monkeypatch.setattr(fd, "_toss_snap_cache", {"loaded": True, "data": snap})
    monkeypatch.setattr(fd, "_kr_session_date", lambda now=None: D)
    old_losers = _rows(sign=-1)
    data = {"diagnostics": {"toss": {"generatedAt": "2026-10-13T10:00:04+09:00"}},
            "stockMovers": {"kospiLosers": old_losers},
            "rankingsKr": {"tradingAmount": [{"code": "x"}], "tossAmount": [{"code": "y"}], "marketCap": {"as_of": "2026-10-12"}},
            "sources": {"stockMovers.kospiLosers": TOSS, "stockMovers.kospiGainers": TOSS}}

    assert fd._light_toss(data) == 4                      # 코스피 상승 · ETF 상승 · 랭킹 · 종목 수급
    assert [r["code"] for r in data["stockMovers"]["kospiGainers"]] == [r["code"] for r in snap["stockMovers"]["kospiGainers"]]
    assert data["stockMovers"]["kospiLosers"] is old_losers                    # 어제 목록은 안 받는다
    assert data["sources"]["stockMovers.kospiLosers"].startswith("이전 빌드 보존")
    assert data["rankingsKr"]["tradingAmount"] == snap["rankings"]["tradingAmount"]
    assert "tossAmount" not in data["rankingsKr"] and data["rankingsKr"]["marketCap"] == {"as_of": "2026-10-12"}
    assert data["stockFlows"]["generatedAt"] == snap["generatedAt"]
    assert data["diagnostics"]["toss"]["generatedAt"] == snap["generatedAt"]
    # 묶음: 새로 받은 목록만 새 스냅샷 시각, 못 받은 토스 목록은 시각 모름
    assert bb.toss_time(data, "stockMovers.kospiGainers") == bb._iso_dt(snap["generatedAt"])
    assert bb.toss_time(data, "stockMovers.kospiLosers") is None
    assert bb.toss_time(data, "rankingsKr") == bb._iso_dt(snap["generatedAt"])

    assert fd._light_toss(data) == 0                      # 같은 스냅샷이면 아무것도 안 한다


def test_stale_rankings_lose_toss_label(monkeypatch):
    snap = {"generatedAt": "2026-10-13T10:45:00+09:00", "rankings": {"tradingAmount": [{"code": "z", "as_of": "2026-10-12"}]}}
    monkeypatch.setattr(fd, "_toss_snap_cache", {"loaded": True, "data": snap})
    monkeypatch.setattr(fd, "_kr_session_date", lambda now=None: D)
    data = {"rankingsKr": {"tradingAmount": [{"code": "x", "as_of": D}]}, "sources": {"rankingsKr": TOSS + " (거래대금·토스 체결 랭킹)"}}
    assert fd._light_toss(data) == 0
    assert data["sources"]["rankingsKr"].startswith("이전 빌드 보존")       # 앞선 스냅샷의 오늘 랭킹은 남기되 새 시각은 안 찍는다
    assert data["rankingsKr"]["tradingAmount"] == [{"code": "x", "as_of": D}]


def test_block_label_needs_both_lists_and_old_snapshot_is_ignored(monkeypatch):
    snap = {"generatedAt": "2026-10-13T11:00:00+09:00", "stockMovers": {"kospiGainers": _rows()}}
    monkeypatch.setattr(fd, "_toss_snap_cache", {"loaded": True, "data": snap})
    monkeypatch.setattr(fd, "_kr_session_date", lambda now=None: D)
    kept = "이전 빌드 보존 ← pykrx (KRX 정보데이터시스템)"
    data = {"diagnostics": {"toss": {"generatedAt": "2026-10-13T10:45:00+09:00"}},
            "stockMovers": {"kospiLosers": _rows(sign=-1, as_of="2026-10-12")}, "sources": {"stockMovers": kept}}
    assert fd._light_toss(data) == 1
    assert data["sources"]["stockMovers"] == kept            # 하락이 보존이면 묶음 출처도 보존 — 판정표가 「정상」으로 안 본다
    assert data["sources"]["stockMovers.kospiGainers"] == TOSS
    data["diagnostics"]["toss"]["generatedAt"] = "2026-10-13T11:15:00+09:00"   # 다른 수집기가 먼저 올린 더 새 스냅샷
    assert fd._light_toss(data) == 0


def test_yesterday_toss_rankings_dropped(monkeypatch):
    snap = {"generatedAt": "2026-10-14T00:05:00+09:00", "rankings": {}}
    monkeypatch.setattr(fd, "_toss_snap_cache", {"loaded": True, "data": snap})
    monkeypatch.setattr(fd, "_kr_session_date", lambda now=None: "2026-10-14")
    data = {"rankingsKr": {"tradingAmount": [{"code": "x", "as_of": D}], "marketCap": {"as_of": D}}}
    fd._light_toss(data)
    assert data["rankingsKr"] == {"marketCap": {"as_of": D}}   # 풀 런처럼 어제 토스 순위는 싣지 않는다 · KRX 칸은 그대로


def test_toss_only_light_run_keeps_quote_time(tmp_path, monkeypatch):
    """야후 시세가 0건이면 lastUpdated 를 올리지 않는다 — 묶음이 그 시각으로 지수 · 환율을 「실시간」으로 잰다."""
    import json
    monkeypatch.chdir(tmp_path)
    prev = {"lastUpdated": "2026-10-13T10:40:00+09:00", "diagnostics": {"toss": {"generatedAt": "2026-10-13T10:00:00+09:00"}}}
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(prev, f)
    monkeypatch.setattr(fd, "fetch_yf", lambda sym: None)
    monkeypatch.setattr(fd, "_toss_snap_cache", {"loaded": True, "data": {"generatedAt": "2026-10-13T10:45:00+09:00",
                                                                          "stockData": [{"code": "005930"}]}})
    monkeypatch.setattr(fd, "_kr_session_date", lambda now=None: D)
    d, n = fd.build_light_data()
    assert n == 1 and d["lastUpdated"] == prev["lastUpdated"] and d["stockFlows"]["generatedAt"].startswith("2026-10-13T10:45")
