"""데이터 신선도 점검(2026-11-04) 고침 — 늦던 원천 교체 · 잘리던 시계열 · 백필 · SEC 연락처.

전부 네트워크 없이 돈다(conftest 가 막는다). 원천 응답 모양은 2026-11-04 실제 호출에서 옮겨 적었다.
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fetch_data as fd          # noqa: E402
import fetch_mer_series as ms    # noqa: E402
import intl_sources as I         # noqa: E402


def test_exports_from_ecos_shape():
    """ECOS 천달러 · 'YYYYMM' → 화면이 읽는 USD · 'YYYY-MM-01'(FRED 모양 그대로)."""
    r = {"value": 121050082.0, "period": "202609", "desc": "d", "source": "ECOS:901Y118/T002",
         "history": {"202608": 98373699.0, "202609": 121050082.0}}
    n = fd._exports_from_ecos(r)
    assert n["period"] == "2026-09-01" and n["value"] == 121050082000
    assert n["history"] == {"2026-08-01": 98373699000, "2026-09-01": 121050082000}
    assert fd._exports_from_ecos(None) is None and fd._exports_from_ecos({"value": 1, "history": {}}) is None


def test_quarter_month_key():
    assert I._month_key("2026-Q3") == "2026-07-01" and I._month_key("2026-Q1") == "2026-01-01"
    assert I._month_key("2026-06") == "2026-06-01" and I._month_key("2026-06-01") == "2026-06-01"


def test_eurostat_and_dbnomics_parse(monkeypatch):
    es = {"dimension": {"time": {"category": {"index": {"2026-07": 0, "2026-08": 1, "2026-09": 2}}}},
          "value": {"0": 4.0, "1": 4.1, "2": 4.1}}
    db = {"series": {"docs": [{"period": ["2026-07", "2026-08", "2026-09"], "value": [2.4, 2.5, "NA"]}]}}
    monkeypatch.setattr(I, "_get_json", lambda url, accept=None: es if "eurostat" in url else db)
    assert I.fetch_eurostat(I.EUROSTAT_SERIES["unemployment_de"][0]) == [("2026-07", 4.0), ("2026-08", 4.1),
                                                                          ("2026-09", 4.1)]
    assert I.fetch_dbnomics(I.DBNOMICS_SERIES["unemployment_jp"][0]) == [("2026-07", 2.4), ("2026-08", 2.5)]   # NA 버림
    assert I._CC_OF["unemployment_de"] == "de" and I._CC_OF["unemployment_jp"] == "jp" and I._CC_OF["gdp_yoy_cn"] == "cn"


def test_fred_tables_drop_moved_series():
    """원천을 옮긴 계열이 FRED 표에 남아 있으면 intl 대체 원천이 실패한 런에 옛(늦은) 값이 새 값을 덮는다."""
    t = fd.FRED_INTL_INDICATORS
    assert "unemployment" not in t["jp"] and "unemployment" not in t["de"]
    assert "gdp_yoy" not in t["cn"] and "exports" not in t["kr"]
    assert fd.FRED_INTL_DAILY["ECBDFR"] >= 1000                  # 일간 계열 — 60점(두 달)에서 자르지 않는다


def test_umich_csv():
    text = "Month,YYYY,ICS_ALL\nNovember,1952,86.2\nSeptember,2026,48.1\nOctober,2026,48\nbad,2026,x\n"
    assert I.parse_umich_csv(text) == [("1952-11", 86.2), ("2026-09", 48.1), ("2026-10", 48.0)]
    assert I.parse_umich_csv(text, n=1) == [("2026-10", 48.0)]


def test_jp_cpi_keeps_five_years():
    periods = [f"{y}-{m:02d}" for y in range(2019, 2027) for m in range(1, 13)][:93]   # 2019-01 ~ 2026-09
    vals = [100 + i * 0.1 for i in range(len(periods))]
    out = fd._yoy_series(periods, vals)
    assert len(out) == 60 and out[-1][0] == "2026-09"


_SSE = {"data": {"currentDate": "2026-10-30", "lastDate": "2026-10-23", "lineDataList": [
    {"properties": {"lineName_EN": "Comprehensive Index"}, "currentContent": 3687.3527, "lastContent": 3681.3369,
     "percentage": 0.1634},
    {"properties": {"lineName_EN": "Europe 20ft (Base port)"}, "currentContent": None, "lastContent": None}]}}


def test_sse_composite():
    it = fd._sse_composite(_SSE, "SCFI")
    assert it["price"] == 3687.35 and it["date"] == "2026-10-30" and it["chgPct"] == 0.16
    assert it["prev"] == {"date": "2026-10-23", "price": 3681.34}
    assert fd._sse_composite(_SSE, "CCFI") is None                  # CCFI 는 'COMPOSITE INDEX' 행이어야 한다


def test_freight_prefers_newer_date(monkeypatch):
    """네이버 SCFI(한 주 늦음)와 SSE(이번 주)가 둘 다 주면 기준일이 늦은 쪽."""
    monkeypatch.setattr(fd, "_freight_from_naver", lambda: {"SCFI": {"code": "SCFI", "price": 3681.34, "date": "2026-10-23"},
                                                            "BDI": {"code": "BDI", "price": 2648, "date": "2026-11-02"}})
    monkeypatch.setattr(fd, "_freight_from_stockq", lambda: {"BDI": {"code": "BDI", "price": 2600, "date": "2026-10-30"}})
    monkeypatch.setattr(fd, "_freight_from_sse", lambda: {"SCFI": fd._sse_composite(_SSE, "SCFI")})
    monkeypatch.setattr(fd, "log", lambda *a, **k: None)
    got = {i["code"]: (i["price"], i["date"]) for i in fd.fetch_freight_indices()["items"]}
    assert got["SCFI"] == (3687.35, "2026-10-30") and got["BDI"] == (2648, "2026-11-02")


def test_backfill_freight_prev():
    arr = [{"date": "2026-10-30", "items": {"SCFI": 3687.35, "BDI": 2648}}]
    out = ms.backfill_freight_prev(arr, [{"code": "SCFI", "prev": {"date": "2026-10-23", "price": 3681.34}},
                                         {"code": "BDI"}])
    assert [e["date"] for e in out] == ["2026-10-23", "2026-10-30"] and out[0]["items"] == {"SCFI": 3681.34}
    again = ms.backfill_freight_prev(out, [{"code": "SCFI", "prev": {"date": "2026-10-23", "price": 1}}])
    assert again[0]["items"]["SCFI"] == 3681.34                       # 있는 값은 안 바꾼다


_WM = ("<table><tr><th>date</th></tr>"
       "<tr><td>03. November 2026</td><td>1</td><td>1</td><td>309,650</td></tr>"
       "<tr><td>30. October 2026</td><td>1</td><td>1</td><td>300,000</td></tr>"
       "<tr><td>04. November 2025</td><td>1</td><td>1</td><td>150,000</td></tr>"
       "<tr><td>01. November 2025</td><td>1</td><td>1</td><td>140,000</td></tr></table>")


def test_backfill_lme():
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        calls.append((params["field"], params["year"]))
        return types.SimpleNamespace(text=_WM, raise_for_status=lambda: None)

    from datetime import date
    arr = [{"date": "2026-10-30", "items": {"Copper": 1}}]
    out = ms.backfill_lme(arr, today=date(2026, 11, 4), get=get)
    by = {e["date"]: e["items"] for e in out}
    assert by["2026-10-30"]["Copper"] == 1                            # 날마다 쌓은 값이 원본 — 표가 덮지 않는다
    assert by["2026-11-03"]["Tin"] == 309650 and "2025-11-01" not in by   # 1년 창 밖은 버린다
    assert len(calls) == 12                                           # 금속 6 × 2해
    calls.clear()
    assert ms.backfill_lme(out, today=date(2026, 11, 4), get=get) is out and calls == []   # 1년 차면 다시 안 부른다


def test_berkshire_skips_without_contact(monkeypatch):
    monkeypatch.setattr(fd, "SEC_CONTACT", "")
    monkeypatch.setattr(fd, "log", lambda *a, **k: None)
    assert fd.fetch_berkshire_13f() is None                           # 연락처 없으면 SEC 를 부르지 않는다(403 헛호출)
    assert "pcr" not in fd.__dict__.get("FRED_LIMITS", {}) and not hasattr(fd, "fetch_putcall_ratio")


def test_vkospi_backfill(monkeypatch):
    """KRX 날짜별 조회로 VKOSPI 과거를 거꾸로 채운다 — 평일 · 없는 날만, 런당 상한, 1년 차면 안 부른다."""
    from datetime import date, timedelta
    calls = []

    def fetch(ep, bas):
        calls.append(bas)
        if bas == "20261102":                                  # 휴장(빈 응답)
            return None
        return [{"IDX_NM": "코스피 200 변동성지수", "CLSPRC_IDX": "30.5"}, {"IDX_NM": "x", "CLSPRC_IDX": "1"}]

    monkeypatch.setattr(fd, "log", lambda *a, **k: None)
    got = fd._vkospi_backfill({"2026-10-30": 29.0}, today=date(2026, 11, 4), budget=3, fetch=fetch)
    assert calls == ["20261103", "20261102", "20261029"]        # 11/1·2 주말, 10/30 있음 → 건너뜀
    assert got == {"2026-11-03": 30.5, "2026-10-29": 30.5}
    full = {(date(2026, 11, 3) - timedelta(days=i)).isoformat(): 30.0 for i in range(240)}
    calls.clear()
    assert fd._vkospi_backfill(full, today=date(2026, 11, 4), fetch=fetch) == {} and calls == []


def test_vkospi_backfill_stops_on_repeated_miss(monkeypatch):
    """두 표 모두 VKOSPI 행이 없는 날이 평일 8일 이어지면 멈춘다(런당 40콜을 헛되이 쓰지 않게)."""
    from datetime import date
    calls = []

    def fetch(ep, bas):
        calls.append((ep, bas))
        return [{"IDX_NM": "코스피 200", "CLSPRC_IDX": "400"}]

    monkeypatch.setattr(fd, "log", lambda *a, **k: None)
    assert fd._vkospi_backfill({}, today=date(2026, 11, 4), budget=40, fetch=fetch) == {}
    assert len(calls) == 16 and {ep for ep, _ in calls} == {"/idx/drvprod_dd_trd", "/idx/kospi_dd_trd"}


def test_merge_freight_per_item_date():
    """운임 항목은 각자의 기준일 행에 — 일간 BDI 가 주간 SCFI 날짜에 붙어 덮이지 않는다."""
    arr = [{"date": "2026-10-30", "items": {"SCFI": 1.0}}]
    items = [{"code": "SCFI", "price": 3687.35, "date": "2026-10-30"},
             {"code": "BDI", "price": 2648, "date": "2026-11-02"}, {"code": "BCI", "price": None, "date": "2026-11-02"}]
    out = ms.merge_freight(arr, items)
    assert {e["date"]: e["items"] for e in out} == {"2026-10-30": {"SCFI": 3687.35}, "2026-11-02": {"BDI": 2648}}
    out = ms.merge_freight(out, [{"code": "BDI", "price": 2590, "date": "2026-11-03"}])
    assert [e["date"] for e in out] == ["2026-10-30", "2026-11-02", "2026-11-03"]   # 일간 이력이 쌓인다


# ── 2차(2026-11-04 오후): 주택 공급 KOSIS · 짧은 창 쌓기 · 국민연금 연말 · 일정 헤드라인 ──

def _rone(hist):
    return {"value": 1, "period": max(hist), "history": hist, "region": "전국", "desc": "d", "unit": "호",
            "source": "R-ONE:T1"}


def test_kosis_supply_monthly_match(monkeypatch):
    monkeypatch.setattr(fd, "log", lambda *a, **k: None)
    ref = {f"2026{m:02d}": 1000.0 + m for m in range(1, 9)}               # R-ONE 1~8월
    kos = {**{k: v * 1.01 for k, v in ref.items()}, "202609": 2000.0}     # 1% 차 + 9월
    n = fd._kosis_supply_node("housing_start_kr", _rone(ref), fetch=lambda *a: kos)
    assert n["period"] == "202609" and n["value"] == 2000.0 and n["source"].startswith("KOSIS:116/DT_MLTM_5386")
    assert n["desc"] == "d" and n["unit"] == "호"


def test_kosis_supply_cumulative_and_guards(monkeypatch):
    monkeypatch.setattr(fd, "log", lambda *a, **k: None)
    ref = {f"2026{m:02d}": 100.0 for m in range(1, 9)}                    # 월분 100 씩
    cum = {f"2026{m:02d}": 100.0 * m for m in range(1, 10)}               # KOSIS 가 연간 누계라면
    n = fd._kosis_supply_node("housing_permit_kr", _rone(ref), fetch=lambda *a: cum)
    assert n and n["period"] == "202609" and n["history"]["202609"] == 100.0   # 누계 차분 해석이 맞아 채택
    off = {k: v * 1.5 for k, v in ref.items()} | {"202609": 1.0}
    assert fd._kosis_supply_node("housing_start_kr", _rone(ref), fetch=lambda *a: off) is None   # 어느 해석도 안 맞음
    same = dict(ref)
    assert fd._kosis_supply_node("housing_start_kr", _rone(ref), fetch=lambda *a: same) is None  # 더 새 달 없음
    assert fd._kosis_supply_node("housing_start_kr", None, fetch=lambda *a: cum) is None         # 대조 상대 없음


def test_accumulate_short_window():
    fresh = {"existing_home_sales": {"history": {"2026-08-01": 4.0, "2026-09-01": 4.1}}, "x": {"history": {"a": 1}}}
    prev = {"existing_home_sales": {"history": {"2025-01-01": 3.9, "2026-08-01": 3.0}}}
    fd._accumulate_history(fresh, prev, fd.FRED_SHORT_WINDOW)
    assert fresh["existing_home_sales"]["history"] == {"2025-01-01": 3.9, "2026-08-01": 4.0, "2026-09-01": 4.1}
    assert fresh["x"]["history"] == {"a": 1}


def test_nps_yearend():
    rows = [{"artclCn1": "2025", "artclCn3": "263737", "artclCn4": "304763", "artclCn5": "550485",
             "artclCn6": "101303", "artclCn7": "232576", "artclCn8": "4442"},
            {"artclCn1": "2026", "artclCn3": "1", "artclCn4": "1", "artclCn5": "1", "artclCn6": "1", "artclCn7": "1"},
            {"artclCn1": "합계"}]
    out = ms.parse_nps_yearend(rows, 2026)
    assert [e["date"] for e in out] == ["2025-12-01"] and out[0]["basis"] == "연말"
    assert out[0]["alloc"]["국내주식"] == round(263737 / 1457306 * 100, 1) and None not in out[0]["alloc"]

    from datetime import date
    called = []
    have = [{"date": "2024-12-01", "alloc": {}}]
    assert ms.backfill_nps_yearend(have, today=date(2026, 11, 4), post=lambda *a, **k: called.append(1)) is have
    assert called == []                                              # 2년 전 연말이 있으면 안 부른다
    resp = types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"resultDtlList": rows})
    got = ms.backfill_nps_yearend([{"date": "2026-08-01", "alloc": {"국내주식": 25.8}}], today=date(2026, 11, 4),
                                  post=lambda *a, **k: resp)
    assert [e["date"] for e in got] == ["2025-12-01", "2026-08-01"]


def test_calendar_kr_headlines(monkeypatch):
    import datetime as dt
    assert fd._fmt_indicator(193.0, "ykd") == "+19.3만명" and fd._fmt_indicator(-5.0, "ykd") == "-0.5만명"
    monkeypatch.setitem(fd.CALENDAR_INDICATOR_MAP, "한국 고용동향", ("economicIndicators.kr.employed_kr", "ykd", False))
    monkeypatch.setitem(fd.CALENDAR_INDICATOR_MAP, "한국 산업활동동향", ("economicIndicators.kr.ip_all_kr", "mom1", False))
    monkeypatch.setattr(fd, "log", lambda *a, **k: None)
    day = (dt.datetime.now(fd.KST) - dt.timedelta(days=3)).date()
    ref = (day.replace(day=1) - dt.timedelta(days=1))                 # 발표 달의 전달
    k = lambda d: d.strftime("%Y%m")
    last = ref.replace(year=ref.year - 1)
    prevm = ref.replace(day=1) - dt.timedelta(days=1)
    emp = {k(last): 29000.0, k(prevm.replace(year=prevm.year - 1)): 28900.0, k(prevm): 29100.0, k(ref): 29193.0}
    data = {"economicIndicators": {"kr": {"employed_kr": {"value": 29193.0, "history": emp},
                                          "ip_all_kr": {"value": 1, "history": {}}}}}
    ev = {"iso": day.isoformat(), "dt": day.strftime("%m.%d") + " 08:00", "name": "한국 고용동향",
          "refPeriod": ref.strftime("%Y-%m"), "prev": "", "fore": "", "act": ""}
    ip = {"iso": day.isoformat(), "dt": day.strftime("%m.%d") + " 08:00", "name": "한국 산업활동동향",
          "refPeriod": ref.strftime("%Y-%m"), "prev": "", "fore": "", "act": ""}
    fd.backfill_calendar_actuals([ev, ip], data)
    assert ev["act"] == "+19.3만명" and ev["prev"] == "+20.0만명"
    assert ip["act"] == ""                                            # 이력 없는 변화율은 수준 값으로 찍지 않는다
