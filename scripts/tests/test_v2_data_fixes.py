"""알림 v2 A4 data-fixes(수집·번들) — 등락 종목 이상치 가드 · 시장별 기준일 통일 · BTC 번들.

실행: python -m pytest scripts/tests/test_v2_data_fixes.py -q
"""
import copy
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import build_bundles as bb  # noqa: E402
import fetch_data as fd  # noqa: E402

DAY, PREV = "2026-10-02", "2026-10-01"


def _row(name, price, chg, as_of=DAY, **kw):
    return {"name": name, "code": "000000", "price": price, "chg": chg, "vol": 1000.0, "market": "KOSPI", "as_of": as_of, **kw}


# ── 1) 등락 종목 이상치 가드 ────────────────────────────────────────────────
def test_suspect_rule_matches_the_2026_10_02_cases():
    assert fd._mover_suspect(_row("한창", 112.0, -91.07))             # 실측: 112원 −91%
    assert fd._mover_suspect(_row("부산주공", 27.0, -32.5))           # 실측: 27원 −32.5% (하한가 밖)
    assert fd._mover_suspect(_row("재상장", 20000.0, 300.0))          # 종가÷기준가 4.0 — 기준가 변경 의심
    assert fd._mover_suspect(_row("액면분할", 10000.0, -80.0))        # 0.2
    assert not fd._mover_suspect(_row("상한가", 18440.0, 29.95))      # 정상 범위
    assert not fd._mover_suspect(_row("동전주 상한가", 900.0, 29.9))  # 1,000원 미만이어도 30% 이내면 정상
    assert not fd._mover_suspect(_row("큰 낙폭", 5000.0, -35.0))      # 비율 0.65 — 가격·비율 어느 쪽도 비정상 아님
    assert not fd._mover_suspect(_row("값 없음", None, None))
    assert not fd._mover_suspect({})


def test_guard_marks_without_deleting_and_is_idempotent():
    data = {"stockMovers": {
        "kospiLosers": [_row("한창", 112.0, -91.07), _row("부산주공", 27.0, -32.5), _row("정상", 15000.0, -8.9)],
        "kospiGainers": [_row("티엠씨", 18440.0, 29.95)],
    }}
    got = fd._guard_movers(data, DAY)
    assert [(k, r["name"]) for k, r in got] == [("kospiLosers", "한창"), ("kospiLosers", "부산주공")]
    losers = data["stockMovers"]["kospiLosers"]
    assert len(losers) == 3 and [bool(r.get("suspect")) for r in losers] == [True, True, False]   # 지우지 않는다
    assert "suspect" not in data["stockMovers"]["kospiGainers"][0]
    snap = copy.deepcopy(data)
    fd._guard_movers(data, DAY)
    assert data == snap                                                # 두 번 돌려도 같다
    assert fd._guard_movers({}, DAY) == [] and fd._guard_movers({"stockMovers": None}, DAY) == []


def test_asof_unified_per_market_never_across_markets():
    data = {"stockMovers": {
        "kospiGainers": [_row("A", 9100.0, 16.8, PREV)],      # KRX 대체(전일) — 실측 4a20eb27c
        "kospiLosers": [_row("B", 15000.0, -9.0, DAY)],       # 토스(당일)
        "kosdaqGainers": [_row("C", 5000.0, 20.0, PREV, market="KOSDAQ")],
        "kosdaqLosers": [_row("D", 7000.0, -9.0, PREV, market="KOSDAQ")],
    }}
    fd._guard_movers(data, DAY)
    sm = data["stockMovers"]
    assert {r["as_of"] for k in ("kospiGainers", "kospiLosers") for r in sm[k]} == {DAY}      # 시장 안은 하나
    assert sm["kospiGainers"][0]["srcAsOf"] == PREV and "srcAsOf" not in sm["kospiLosers"][0]   # 원래 날짜는 남긴다
    assert {r["as_of"] for k in ("kosdaqGainers", "kosdaqLosers") for r in sm[k]} == {PREV}     # 시장 사이는 맞추지 않는다
    snap = copy.deepcopy(data)
    fd._guard_movers(data, DAY)
    assert data == snap


def test_asof_unify_leaves_preserved_old_and_future_rows_alone():
    data = {"stockMovers": {
        "kospiGainers": [_row("묵은 보존", 9100.0, 16.8, "2026-09-25", preserved=True)],    # 보존 행은 건드리지 않는다
        "kospiLosers": [_row("당일", 15000.0, -9.0, DAY)],
        "kosdaqGainers": [_row("닷새 묵음", 5000.0, 20.0, "2026-09-26", market="KOSDAQ")],   # 4일 넘게 묵은 목록은 둔갑 금지
        "kosdaqLosers": [_row("당일", 7000.0, -9.0, DAY, market="KOSDAQ")],
    }}
    fd._guard_movers(data, DAY)
    sm = data["stockMovers"]
    assert sm["kospiGainers"][0]["as_of"] == "2026-09-25" and "srcAsOf" not in sm["kospiGainers"][0]
    assert sm["kosdaqGainers"][0]["as_of"] == "2026-09-26" and "srcAsOf" not in sm["kosdaqGainers"][0]
    # 거래일(session)보다 늦은 날짜는 기준일로 뽑지 않는다
    fut = {"stockMovers": {"kospiGainers": [_row("A", 9100.0, 5.0, PREV)], "kospiLosers": [_row("B", 9100.0, -5.0, "2026-10-09")]}}
    fd._guard_movers(fut, DAY)
    assert fut["stockMovers"]["kospiGainers"][0]["as_of"] == PREV


# ── 2) BTC 번들 ─────────────────────────────────────────────────────────────
_DATA, _MER = bb.load("data.json"), bb.load("mer_signals.json", {})


def _with_btc(updated_kst, last_bar_utc_date):
    d = copy.deepcopy(_DATA)
    d["lastUpdated"] = updated_kst
    day = dt.date.fromisoformat(last_bar_utc_date)
    d["history"]["crypto"]["BTC"] = [{"date": (day - dt.timedelta(days=n)).isoformat(), "close": 80000.0 + 100 * (2 - n)} for n in (2, 1, 0)]
    return d


def _bundles(data, minutes_after=5):
    now = bb._iso_dt(data["lastUpdated"]).astimezone(bb.KST) + dt.timedelta(minutes=minutes_after)
    return bb.build_all(data, _MER, now, bb.load("toss_snapshot.json", {}))


def test_btc_is_in_global_strip_and_crypto_view():
    upd = "2026-10-05T14:00:00+09:00"
    g = _bundles(_with_btc(upd, "2026-10-05"))["market-global"]           # 14:00 KST = 05:00 UTC(10-05)
    assert [x["id"] for x in g["strip"]] == bb.STRIPS["global"] and g["strip"][-1]["id"] == "btc" and len(g["strip"]) == 7
    btc = g["strip"][-1]
    assert btc["value"] == 80200.0 and btc["changePct"] == round((80200 / 80100 - 1) * 100, 2)
    assert btc["state"] == "live" and btc["asOf"] == upd and btc["liveUntil"] == "2026-10-05T14:15:00+09:00"   # 24시간 자산 — 주말·휴장 없음
    cv = g["views"]["crypto"]
    assert cv["id"] == "btc" and [p[1] for p in cv["series"]] == [80000.0, 80100.0, 80200.0]


def test_btc_freshness_is_minutes_based_like_a_24h_asset():
    upd = "2026-10-04T10:00:00+09:00"                                      # 일요일 — 주식 시장은 쉬어도 BTC 는 산다
    data = _with_btc(upd, "2026-10-04")
    assert _bundles(data, 5)["market-global"]["strip"][-1]["state"] == "live"
    prev = _bundles(data, 60)["market-global"]["strip"][-1]
    assert prev["state"] == "prev" and prev["asOf"] == "2026-10-04"        # 15분~120분
    assert _bundles(data, 600)["market-global"]["strip"][-1]["state"] == "stale"
    old = _bundles(_with_btc(upd, "2026-10-01"), 5)["market-global"]["strip"][-1]    # 마지막 봉이 사흘 전 — 수집 시각이 최근이어도 지난 봉의 종가 시각으로 잰다
    assert old["state"] == "stale"


def test_btc_leaves_macro_realestate_lens_registry_bytes_unchanged():
    upd = "2026-10-05T14:00:00+09:00"
    with_btc = _bundles(_with_btc(upd, "2026-10-05"))
    no_btc_data = _with_btc(upd, "2026-10-05")
    no_btc_data["history"]["crypto"]["BTC"] = []
    without = _bundles(no_btc_data)
    for name in ("market-macro", "market-realestate", "lens", "registry", "home", "market-fxrates", "market-flows",
                 "market-commodities", "market-domestic"):
        assert bb.dumps(with_btc[name]) == bb.dumps(without[name]), name
    assert without["market-global"]["strip"][-1]["state"] == "missing"     # 값 없으면 지어내지 않는다


def test_bundle_carries_suspect_flag_through():
    rows = bb.stock_rows([_row("한창", 112.0, -91.07, suspect=True), _row("정상", 15000.0, -8.9)])
    assert rows[0]["suspect"] is True and "suspect" not in rows[1]
