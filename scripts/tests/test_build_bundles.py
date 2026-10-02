#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""화면 묶음(scripts/build_bundles.py) 검사 — 크기·줄임 이름·신선도·이유 한 줄·김치프리미엄·묶음 간 일치.

실행: python scripts/tests/test_build_bundles.py      (pytest 로도 돈다)
저장소의 data.json·mer_signals.json 을 그대로 읽는다(쓰지 않는다). 기준 시각은 data.json 수집 5분 뒤로 고정."""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import build_bundles as bb  # noqa: E402
import one_liners as ol  # noqa: E402

DATA = bb.load("data.json")
MER = bb.load("mer_signals.json", {})
NOW = bb._iso_dt(DATA["lastUpdated"]).astimezone(bb.KST) + dt.timedelta(minutes=5)
_B = {}


def bundles():
    if not _B:
        _B.update(bb.build_all(DATA, MER, NOW, bb.load("toss_snapshot.json", {})))
    return _B


def _item(bundle, ind_id):
    return next(x for x in bundle["strip"] if x["id"] == ind_id)


def test_each_bundle_within_200kb():
    for name, obj in bundles().items():
        n = len(bb.dumps(obj).encode("utf-8"))
        assert n <= bb.MAX_BYTES, "%s.json %d bytes > %d" % (name, n, bb.MAX_BYTES)
    assert set(bundles()) >= {"registry", "home", "lens", "market-domestic", "market-global", "market-fxrates",
                              "market-commodities", "market-macro", "market-flows", "market-realestate"}


def test_short_names_within_caps():
    bad = [(r["id"], r["short"], r["shortM"]) for r in bundles()["registry"]["rows"]
           if ol.width(r["short"]) > bb.SHORT_PC or ol.width(r["shortM"]) > bb.SHORT_M]
    assert not bad, "줄임 이름 상한 초과 — build_bundles.SHORT 에 한 줄 더할 것: %r" % bad
    assert bb.stock_short("HANARO 코스닥150선물레버리지")[0] == "HANARO 코닥150레버"
    for name in ("SOL SK하이닉스선물단일종목인버스2X", "마이티 신약포커스바이오액티브", "삼성전자", ""):
        pc, m = bb.stock_short(name)
        assert ol.width(pc) <= bb.SHORT_PC and ol.width(m) <= bb.SHORT_M, (name, pc, m)
    # 나라만 다른 같은 이름은 나라가 붙어 갈린다
    shorts = {r["id"]: r["shortM"] for r in bundles()["registry"]["rows"]}
    assert shorts["cpi_kr"] != shorts["cpi_us"] and shorts["unemployment_kr"] != shorts["unemployment"]


def test_freshness_table():
    f = bb.freshness
    assert f(5, True, False) == "live"
    assert f(30, True, False) == "prev"            # 장중이라도 15분 넘으면 실시간이 아니다
    assert f(121, True, False) == "stale"
    assert f(200, False, False) == "prev" and f(241, False, False) == "stale"
    assert f(700, False, True) == "prev" and f(721, False, True) == "stale"
    assert f(1, True, False, kept=True) == "kept"
    assert f(None, True, False) == "missing"


def _states(node, skip=("market", "lens", "triggers", "today", "breach", "watch", "chain")):
    """묶음 안의 모든 신선도 state (장 상태·렌즈 트리거 state 는 다른 말이라 뺀다)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in skip:
                continue
            if k == "state" and isinstance(v, str):
                yield v
            else:
                yield from _states(v, skip)
    elif isinstance(node, list):
        for v in node:
            yield from _states(v, skip)


def test_freshness_states_are_the_fixed_set():
    for name, obj in bundles().items():
        if name in ("lens", "registry") or name.startswith("_"):
            continue
        got = set(_states(obj))
        assert got and got <= set(bb.STATES), (name, got - set(bb.STATES))


def test_live_during_kr_session_and_prev_on_weekend():
    """장중 3분 전 값 = live(코스피), 같은 시각 미국 장은 닫혀 prev. 토요일 1시간 전 값 = prev(휴장 임계 720분)."""
    data = json.loads(json.dumps(DATA))
    data["marketCalendarKr"] = {"today": {"date": "2026-10-01", "open": True},
                                "previousBusinessDay": {"date": "2026-09-30", "open": True},
                                "nextBusinessDay": {"date": "2026-10-02", "open": True}}
    data["lastUpdated"] = "2026-10-01T09:57:00+09:00"
    b = bb.build_all(data, MER, bb._iso_dt("2026-10-01T10:00:00+09:00"))   # 토스 스냅샷 없이 → 시각 = 수집 시각
    assert b["home"]["market"]["state"] == "open"
    assert _item(b["home"], "kospi")["state"] == "live"
    assert _item(b["home"], "sp500")["state"] == "prev"
    data["lastUpdated"] = "2026-10-03T11:00:00+09:00"
    b = bb.build_all(data, MER, bb._iso_dt("2026-10-03T12:00:00+09:00"))
    assert b["home"]["market"]["state"] == "holiday" and _item(b["home"], "kospi")["state"] == "prev"
    b = bb.build_all(data, MER, bb._iso_dt("2026-10-04T00:01:00+09:00"))   # 13시간 뒤 → 720분 초과
    assert _item(b["home"], "kospi")["state"] == "stale"


def test_us_market_holiday_and_dst():
    """뉴욕 현지 시각으로 잰다 — 추수감사절·서머타임 경계(검토 2026-10-01)."""
    t = bb._iso_dt
    assert bb.us_market(t("2026-11-26T23:45:00+09:00"))[:2] == (False, True)       # 추수감사절 09:45 EST
    assert bb.us_market(t("2026-07-01T05:30:00+09:00"))[0] is False                # 여름 16:30 EDT = 마감 뒤
    assert bb.us_market(t("2026-07-01T22:45:00+09:00"))[0] is True                 # 여름 09:45 EDT
    assert bb.us_market(t("2026-12-01T22:45:00+09:00"))[0] is False                # 겨울 08:45 EST = 개장 전
    assert bb.us_market(t("2026-12-01T23:45:00+09:00"))[0] is True
    assert bb.us_market(t("2026-10-01T10:00:00+09:00"))[2] == "2026-09-30"         # 마지막 세션 날짜
    assert bb.globex_market(t("2026-10-03T12:00:00+09:00"))[:2] == (False, True)   # 토요일 = 주말 휴장
    assert bb.globex_market(t("2026-10-01T17:00:00+09:00"))[0] is True             # 뉴욕 04:00 목


def _fresh_open_data():
    data = json.loads(json.dumps(DATA))
    data["marketCalendarKr"] = {"today": {"date": "2026-10-01", "open": True},
                                "previousBusinessDay": {"date": "2026-09-30", "open": True},
                                "nextBusinessDay": {"date": "2026-10-02", "open": True}}
    data["lastUpdated"] = "2026-10-01T09:57:00+09:00"
    return data


def test_asia_and_krx_gold_are_never_live():
    b = bb.build_all(_fresh_open_data(), MER, bb._iso_dt("2026-10-01T10:00:00+09:00"))
    g = {x["id"]: x for x in b["market-global"]["views"]["indices"]}
    assert g["kospi"]["state"] == "live" and g["kospi"]["liveUntil"] == "2026-10-01T10:12:00+09:00"
    assert all(g[i]["state"] != "live" for i in ("nikkei", "shanghai", "hsi"))   # 10/1 상하이 국경절 휴장
    gk = next(x for x in b["market-commodities"]["views"]["items"] if x["id"] == "goldkrw")
    assert gk["state"] != "live" and "liveUntil" not in gk


def test_kr_close_is_not_stale_overnight():
    """토스 스냅샷은 값이 그대로면 시각을 올리지 않는다 — 마감 뒤 확인된 종가는 밤새 prev 다."""
    data = json.loads(json.dumps(DATA))
    data["lastUpdated"] = "2026-10-01T21:50:00+09:00"
    toss = {"generatedAt": "2026-10-01T15:30:03+09:00", "indices": {"KOSPI": {"price": data["indices"]["KOSPI"]["price"]}}}
    now = bb._iso_dt("2026-10-01T22:00:00+09:00")
    k = _item(bb.build_all(data, MER, now, toss)["home"], "kospi")
    assert k["state"] == "prev" and k["asOf"] == "2026-10-01T15:30:03+09:00"
    toss["generatedAt"] = "2026-10-01T11:00:00+09:00"                    # 장중에 멈춘 스냅샷 = 종가가 아니다
    assert _item(bb.build_all(data, MER, now, toss)["home"], "kospi")["state"] == "stale"


def test_scale_and_rate_change_pct():
    reg = {r["id"]: r for r in bundles()["registry"]["rows"]}
    assert reg["exports_kr"]["scale"] == 1e8 and reg["exports_kr"]["unit"] == "억달러"
    assert reg["jpykrw"]["scale"] == 0.01 and reg["jpykrw"]["decimals"] == 2   # 100엔당으로 보인다
    q = {x["id"]: x for x in bundles()["market-macro"]["views"]["topics"]["trade"]}
    assert q["exports_kr"]["value"] == DATA["economicIndicators"]["kr"]["exports_kr"]["value"]   # 값은 원본 그대로
    home = {x["id"]: x for x in bundles()["home"]["strip"]}
    assert home["us10y"]["changePct"] is None and home["us10y"]["change"] is not None
    us = {x["id"]: x for x in bundles()["market-realestate"]["views"]["us"]}
    assert us["mortgage_30y_us"]["changePct"] is None                     # 소스가 준 chg 라도 금리는 싣지 않는다


def test_gold_premium_same_day_when_krx_date_known():
    data = json.loads(json.dumps(DATA))
    d = "2026-09-30"
    data["commodities"]["GoldKRW"] = dict(data["commodities"]["GoldKRW"], as_of=d)
    gp = bb.build_all(data, MER, NOW)["market-commodities"]["views"]["goldPremium"]
    gold_d = next(p["close"] for p in data["history"]["commodities"]["Gold"] if p["date"] == d)
    fx_d = next(p["close"] for p in data["history"]["fx"]["USDKRW"] if p["date"] == d)
    assert gp["basis"] == "sameDay" and gp["date"] == d
    assert gp["pct"] == bb.gold_premium(data["commodities"]["GoldKRW"]["price"], gold_d, fx_d)


def test_strips_follow_plan_table():
    """기획안 v4 4장 띠 표 그대로 — 칸 순서·이름 상한."""
    b = bundles()
    assert [x["id"] for x in b["home"]["strip"]] == bb.HOME_STRIP
    for name, ids in bb.STRIPS.items():
        strip = b["market-" + name]["strip"]
        assert [x["id"] for x in strip] == ids, name
        for x in strip:
            assert x["state"] in bb.STATES, (name, x)
            if x.get("short"):
                assert ol.width(x["short"]) <= bb.SHORT_PC and ol.width(x["shortM"]) <= bb.SHORT_M, x
    fh = _item(b["market-flows"], "foreign_hold_ratio")
    assert fh["value"] is None and fh["state"] == "missing"                 # 수집하지 않는 값은 지어내지 않는다


def test_yoy_and_derived_cells():
    b = bundles()
    h = DATA["economicIndicators"]["kr"]["cpi_kr"]["history"]
    k = DATA["economicIndicators"]["kr"]["cpi_kr"]["period"]
    want = round((h[k] / h[str(int(k[:4]) - 1) + k[4:]] - 1) * 100, 2)
    assert _item(b["market-macro"], "cpi_kr_yoy")["value"] == want
    assert _item(b["market-macro"], "unemployment")["asOf"] == DATA["economicIndicators"]["us"]["unemployment"]["period"][:7]
    jeonse = _item(b["market-realestate"], "avg_jeonse_price_kr")
    assert jeonse["scale"] == 1e5 and jeonse["unit"] == "억원"               # 천원 → 억원
    top = _item(b["market-domestic"], "top20_amount")
    assert top["value"] == sum(r["amount"] for r in DATA["rankingsKr"]["tradingAmount"][:20]) and top["scale"] == 1e12
    br = _item(b["market-domestic"], "breadth_kospi")
    assert (br["up"], br["down"]) == (DATA["marketBreadth"]["kospi"]["up"], DATA["marketBreadth"]["kospi"]["down"])
    assert _item(b["market-commodities"], "gold_premium")["value"] == b["market-commodities"]["views"]["goldPremium"]["pct"]
    assert set(b["market-realestate"]["views"]["capital"]) <= set(bb.CAPITAL_AREA)


def test_yoy_guard_over_50pct():
    """전년비가 ±50% 를 넘으면 싣지 않고(null·missing) meta.health.issues 에 한 줄 남긴다 — 팀장 결정 2026-10-01."""
    data = json.loads(json.dumps(DATA))
    leaf = data["economicIndicators"]["kr"]["cpi_kr"]
    k = leaf["period"]
    leaf["history"][str(int(k[:4]) - 1) + k[4:]] = leaf["history"][k] / 1.6          # 전년비 +60% 로 만든다
    b = bb.build_all(data, MER, NOW)
    cpi = _item(b["market-macro"], "cpi_kr_yoy")
    assert cpi["value"] is None and cpi["state"] == "missing" and cpi["guarded"] == 60.0
    assert any(i["path"] == "economicIndicators.kr.cpi_kr" and "전년비 60.0%" in i["note"] for i in b["_issues"])
    assert _item(b["market-macro"], "cpi_us_yoy")["value"] is not None           # 범위 안은 그대로
    m = bb.meta(data, MER, {}, NOW, b)
    assert any("cpi_kr 전년비 60.0% — 원본 이력 확인 필요" in (i.get("note") or "") for i in m["health"]["issues"])
    # 거시 띠의 수출 칸 = 절대값(억달러·월), 전년비는 note 로만
    ex = _item(bundles()["market-macro"], "exports_kr")
    assert ex["value"] == DATA["economicIndicators"]["kr"]["exports_kr"]["value"] and ex["scale"] == 1e8
    assert ex["label"] == "한국 수출(억달러·월)" and len(ex["asOf"]) == 7 and "전년비" in ex["note"]


def test_lens_node_short_within_mobile_cap():
    lens = bundles()["lens"]
    bad = [(n["id"], n["short"]) for n in lens["nodes"] if not n.get("short") or ol.width(n["short"]) > bb.SHORT_M]
    assert not bad, "렌즈 노드 줄임 이름 8칸 초과 — build_bundles.LENS_SHORT 에 한 줄 더할 것: %r" % bad
    assert lens["coverage"]["posts"] == MER["coverage"]["posts"]
    assert bb.node_short({"id": "x", "label": "부동산(전국 주택가격지수)"}) == "부동산"
    assert bb.node_short({"id": "x", "label": "AI 캐펙스·데이터센터"}) == "AI 캐펙스"


def test_lens_edge_has_one_recent_quote():
    lens = bundles()["lens"]
    assert len(lens["edges"]) == len(MER["graph"]["edges"])
    for e in lens["edges"]:
        assert len(e["quotes"]) <= 1, e
        for q in e["quotes"]:
            assert set(q) == {"logNo", "date", "q"} and len(q["q"]) <= bb.QUOTE_MAX, q
    # 가장 최근 1건을 고른다 — 원천 인용 중 날짜가 가장 늦은 것
    mer = {"graph": {"edges": [{"from": "a", "to": "b", "dir": "+"}]},
           "impacts": [{"from": "a", "to": "b", "dir": "+", "quotes": [
               {"logNo": "1", "date": "2026-01-01", "q": "옛 글"}, {"logNo": "2", "date": "2026-09-01", "q": "가" * 80}]}]}
    q = bb.edges_with_quote(mer)[0]["quotes"][0]
    assert q["logNo"] == "2" and len(q["q"]) == bb.QUOTE_MAX and q["q"].endswith("…")


def test_lens_chain_lognos_capped():
    lens = bundles()["lens"]
    src = {c["id"]: c for c in MER["chains"]}
    for c in lens["chains"]:
        assert len(c["logNos"]) <= 10 and c["logNos"] == (src[c["id"]].get("logNos") or [])[:10], c["id"]


def test_commodity_groups_and_korean_names():
    items = bundles()["market-commodities"]["views"]["items"]
    assert all(i["group"] in ("energy", "metal", "agri") for i in items), [i["id"] for i in items if not i.get("group")]
    names = {i["id"]: i["label"] for i in items}
    assert (names["gasoline"], names["heatingoil"], names["dubai"]) == ("휘발유", "난방유", "두바이유")


def test_count_units_have_no_decimals():
    reg = {r["id"]: r for r in bundles()["registry"]["rows"]}
    for i in ("unsold_total_kr", "housing_start_kr", "housing_permit_kr", "housing_complete_kr", "trade_count_kr",
              "housing_starts_us", "claims_us"):
        assert reg[i]["decimals"] == 0, i
    assert _item(bundles()["market-realestate"], "unsold_total_kr")["decimals"] == 0
    assert reg["unsold_total_kr"]["unit"] == "호" and reg["trade_count_kr"]["unit"] == "건"   # 레지스트리(app0.js)와 같은 값
    country = {i: reg[i].get("country") for i in ("kospi", "vkospi", "sp500", "sox", "nikkei", "shanghai", "hsi", "move", "fear_greed")}
    assert country == {"kospi": "kr", "vkospi": "kr", "sp500": "us", "sox": "us", "nikkei": "jp",
                       "shanghai": "cn", "hsi": "hk", "move": "us", "fear_greed": "us"}
    assert _item(bundles()["market-domestic"], "breadth_kospi")["decimals"] == 0


def test_change_and_pct_agree_or_both_null():
    """MOVE 는 change 0 · changePct 3.61 로 서로 다른 말을 했다 — 둘이 같은 이야기를 하거나 둘 다 비어야 한다."""
    g = bundles()["market-global"]["views"]
    for q in (g["move"], g["fearGreed"], _item(bundles()["market-domestic"], "vkospi")):
        if q["change"] is None or q["changePct"] is None:
            assert q["change"] is None and q["changePct"] is None, q
            continue
        prev = q["value"] - q["change"]
        assert abs(q["change"] / prev * 100 - q["changePct"]) <= 0.1, q
    data = json.loads(json.dumps(DATA))
    data["sentiment"]["move"]["change"] = 50.0                          # 소스 등락률이 이력과 어긋나면
    mv = bb.build_all(data, MER, NOW)["market-global"]["views"]["move"]
    assert mv["change"] is None and mv["changePct"] is None             # 둘 다 믿지 않는다


def test_kospi_movers_filtered_and_contamination_logged():
    b = bundles()
    v = b["market-domestic"]["views"]
    assert all(x["market"] == "KOSPI" for x in v["gainers"]["kospi"] + v["losers"]["kospi"])
    assert all(x["market"] == "KOSDAQ" for x in v["gainers"]["kosdaq"] + v["losers"]["kosdaq"])
    bad = sum(1 for r in DATA["stockMovers"]["kospiGainers"] if r.get("market") != "KOSPI")
    logged = [i for i in b["_issues"] if i["path"] == "stockMovers.kospiGainers"]
    assert bool(logged) == bool(bad)                                     # 원천이 오염됐을 때만 기록


def test_is_etf_flag():
    assert bb.is_etf({"name": "삼성전자", "type": "STOCK"}) is False
    assert bb.is_etf({"name": "KODEX 200", "type": "ETF"}) is True
    assert bb.is_etf({"name": "TIGER 미국S&P500"}) is True and bb.is_etf({"name": "SK하이닉스"}) is False
    items = bundles()["market-domestic"]["views"]["amount"]["items"]
    src = {r["code"]: r for r in DATA["rankingsKr"]["tradingAmount"]}
    assert all(x["isEtf"] == (src[x["code"]].get("type") == "ETF") for x in items)


def test_market_lines_within_caps_and_not_invented():
    for name in bb.STRIPS:
        ln = bundles()["market-" + name]["line"]
        assert set(ln) == {"pc", "mobile"}, name
        assert ln["pc"] is None or ol.width(ln["pc"]) <= ol.PC, (name, ln)
        assert ln["mobile"] is None or ol.width(ln["mobile"]) <= ol.MOBILE, (name, ln)
    empty = bb.build_all({"lastUpdated": DATA["lastUpdated"]}, {}, NOW)
    assert all(empty["market-" + n]["line"] == {"pc": None, "mobile": None} for n in bb.STRIPS)
    assert ol.streak([{"foreign": -1.0}, {"foreign": -2.0}, {"foreign": 3.0}])[1] == "외국인 순매수"
    assert ol.streak([{"foreign": 1.0}, {"foreign": -2.0}, {"foreign": -3.0}])[1] == "외국인 2일 연속 순매도"


def test_registry_rows():
    rows = bundles()["registry"]["rows"]
    assert rows and all(r["canonical"] == "/i/" + r["id"] for r in rows)
    assert all({"id", "label", "short", "shortM", "asset", "tier", "dataPath"} <= set(r) for r in rows)


def test_kept_when_value_was_carried_over():
    data = json.loads(json.dumps(DATA))
    data["indices"]["KOSPI"] = dict(data["indices"]["KOSPI"], stale=True, change=None)
    b = bb.build_all(data, MER, NOW)
    k = _item(b["home"], "kospi")
    assert k["state"] == "kept" and k["changePct"] is None and k["change"] is None


def test_missing_is_null_not_invented():
    data = {"lastUpdated": DATA["lastUpdated"], "indices": {"KOSPI": {"price": None, "change": None}},
            "commodities": {"Gold": {"price": 4000.0, "change": 0.1}}, "fx": {}}
    b = bb.build_all(data, {}, NOW)
    k = _item(b["home"], "kospi")
    assert k["value"] is None and k["state"] == "missing"
    us = _item(b["home"], "usdkrw")                 # 키째 없는 지표
    assert us["value"] is None and us["state"] == "missing"
    assert b["market-commodities"]["views"]["goldPremium"]["pct"] is None
    assert b["home"]["todayLine"]["pc"] is None or ol.width(b["home"]["todayLine"]["pc"]) <= ol.PC


def test_reason_lines_within_caps():
    home = bundles()["home"]
    for it in home["strip"]:
        assert it["reason"] is None or ol.width(it["reason"]) <= ol.PC, it
        assert it["reasonShort"] is None or ol.width(it["reasonShort"]) <= ol.MOBILE, it
    t = home["todayLine"]
    assert t["pc"] is None or ol.width(t["pc"]) <= ol.PC
    assert t["mobile"] is None or ol.width(t["mobile"]) <= ol.MOBILE
    # 넘치면 짧은 꼴, 그래도 넘치면 갈래를 덜어낸다
    parts = [("가" * 30, "가" * 10), ("나" * 30, "나" * 10), ("다" * 30, "다" * 10)]
    assert ol.fit(parts, ol.PC) == "가" * 10 + ol.SEP + "나" * 10 + ol.SEP + "다" * 10
    assert ol.fit(parts, ol.MOBILE) == "가" * 10 + ol.SEP + "나" * 10
    assert ol.fit([("가" * 50, "가" * 30)], ol.MOBILE) is None


def test_reason_uses_only_same_session_material():
    """어제 업종 등락을 오늘 코스피의 이유로 붙이지 않는다."""
    ctx = {"sectors": None, "flow": {"foreign": 100.0, "inst": -5.0}, "fxPct": None}
    assert "주도" not in (ol.reason("kospi", ctx)["pc"] or "")
    assert ol.reason("kospi", {})["pc"] is None


def test_gold_premium_formula():
    assert bb.gold_premium(182940.0, 4218.2, 1359.6) == round((182940.0 / (4218.2 * 1359.6 / 31.1035) - 1) * 100, 2)
    assert bb.gold_premium(None, 4218.2, 1359.6) is None
    assert bb.gold_premium(182940.0, 0, 1359.6) is None
    gp = bundles()["market-commodities"]["views"]["goldPremium"]
    c = DATA["commodities"]
    want = bb.gold_premium(c.get("GoldKRW", {}).get("price"), c.get("Gold", {}).get("price"), DATA["fx"]["USDKRW"]["rate"])
    assert gp["pct"] == want


def test_same_indicator_same_value_across_bundles():
    b = bundles()
    home = {x["id"]: x for x in b["home"]["strip"]}
    assert home["kospi"]["value"] == _item(b["market-domestic"], "kospi")["value"] == DATA["indices"]["KOSPI"]["price"]
    assert home["usdkrw"]["value"] == _item(b["market-fxrates"], "usdkrw")["value"] == DATA["fx"]["USDKRW"]["rate"]
    assert _item(b["market-domestic"], "flow_foreign")["value"] == _item(b["market-flows"], "flow_foreign")["value"] \
        == b["home"]["investors"]["today"]["foreign"]
    assert home["us10y"]["value"] == _item(b["market-fxrates"], "us10y")["value"]
    assert home["gold"]["value"] == _item(b["market-commodities"], "gold")["value"]
    assert home["sp500"]["value"] == _item(b["market-global"], "sp500")["value"]
    g = {x["id"]: x for x in b["market-global"]["views"]["indices"]}
    assert g["kospi"]["value"] == home["kospi"]["value"]
    # 큰 차트·7일 차트의 끝점 = 띠의 값
    if home["kospi"]["state"] != "kept" and home["kospi"]["spark"]:
        assert home["kospi"]["spark"][-1] == home["kospi"]["value"]
        assert b["home"]["kospiChart"]["1y"][-1][1] == home["kospi"]["value"]


def test_lens_counts_match_source():
    lens = bundles()["lens"]
    assert len(lens["nodes"]) == len(MER["graph"]["nodes"]) and len(lens["edges"]) == len(MER["graph"]["edges"])
    assert len(lens["chains"]) == len(MER["chains"]) and len(lens["triggers"]) == len(MER["indicators"])
    assert len(lens["posts"]) <= 3 and all(set(p) == {"logNo", "date", "title"} for p in lens["posts"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print("ok  " + t.__name__)
    print("%d개 통과" % len(tests))
