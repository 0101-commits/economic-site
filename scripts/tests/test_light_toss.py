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
    data = {"rankingsKr": {"tradingAmount": [{"code": "x"}]}, "sources": {"rankingsKr": TOSS + " (거래대금·토스 체결 랭킹)"}}
    assert fd._light_toss(data) == 0
    assert data["sources"]["rankingsKr"].startswith("이전 빌드 보존")       # 옛 랭킹에 새 스냅샷 시각을 찍지 않는다
    assert data["rankingsKr"]["tradingAmount"] == [{"code": "x"}]
