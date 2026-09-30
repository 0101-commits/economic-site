"""P1 수집기 회귀 테스트 (오프라인 — 네트워크를 부르지 않는다).

A10 ECOS 정식 통계표 · A12 R-ONE 시군구(한 달씩 조회 + '>' 경로 분류) · A8 수집 주기 묶음(lane)
· A17 pykrx 누계·수급 '검증 불가' · A11 Twelve Data 2순위.
실행: python -m pytest scripts/tests/test_p1_collector.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import data_sla  # noqa: E402
import fetch_data as fd  # noqa: E402
import investor_flows as inf  # noqa: E402


class _Resp:
    def __init__(self, payload, code=200):
        self.status_code = code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise fd._requests.exceptions.HTTPError(str(self.status_code))


def _fake_requests(get):
    return types.SimpleNamespace(get=get, exceptions=fd._requests.exceptions)


# ── A10 ECOS ────────────────────────────────────────────────────────────────
_NO_DATA = {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}


def _ecos_rows(periods, item1, name1, base):
    return [{"TIME": p, "DATA_VALUE": str(base + i * 0.1), "ITEM_CODE1": item1, "ITEM_NAME1": name1}
            for i, p in enumerate(periods)]


def test_ecos_uses_official_tables_with_item2_axis(monkeypatch):
    qs = [f"{y}Q{q}" for y in (2024, 2025, 2026) for q in (1, 2, 3, 4)]
    ms = [f"{y}{m:02d}" for y in (2024, 2025) for m in range(1, 13)]
    table = {
        ("200Y102", "10111"): _ecos_rows(qs, "10111", "국내총생산(GDP)(실질, 계절조정, 전기비)", 0.1),
        ("901Y100", "G0/T3"): _ecos_rows(ms, "G0", "총지수", 100.0),
        ("901Y027", "I61BC/I28A"): _ecos_rows(ms, "I61BC", "실업률", 2.0),
        ("151Y001", "1000000"): _ecos_rows(qs, "1000000", "가계신용", 1900000.0),
    }
    urls, logs = [], []

    def get(url, timeout=None, **kw):
        urls.append(url)
        if "/KeyStatisticList/" in url:
            return _Resp({"KeyStatisticList": {"row": []}})
        p = url.split("/StatisticSearch/")[1].split("/")
        rows = table.get((p[5], "/".join(p[9:])))
        return _Resp({"StatisticSearch": {"row": rows}} if rows else _NO_DATA)

    monkeypatch.setattr(fd, "ECOS_API_KEY", "testkey")
    monkeypatch.setattr(fd, "requests", _fake_requests(get))
    monkeypatch.setattr(fd, "log", logs.append)
    monkeypatch.setitem(fd._KEYSTAT_CACHE, "rows", None)
    res = fd.fetch_ecos_economic_indicators()

    assert res["gdp_kr"]["source"] == "ECOS:200Y102" and len(res["gdp_kr"]["history"]) == 12
    assert res["retail_kr"]["source"] == "ECOS:901Y100" and len(res["retail_kr"]["history"]) == 24
    assert res["unemployment_kr"]["source"] == "ECOS:901Y027" and "원계열" in res["unemployment_kr"]["desc"]
    assert res["household_debt_kr"]["source"] == "ECOS:151Y001"
    # 정식 코드가 후보의 맨 앞 — 첫 호출에서 맞히고 옛 후보(200Y104·901Y028·151Y005)는 부르지 않는다.
    gdp = [u for u in urls if "/200Y" in u]
    assert "/200Y102/Q/" in gdp[0] and gdp[0].endswith("/10111")
    assert not any(s in u for u in urls for s in ("/200Y104/", "/901Y028/", "/151Y005/"))
    assert any("/901Y100/M/" in u and u.endswith("/G0/T3") for u in urls)
    assert any(u.endswith("/I61BC/I28A") for u in urls)
    assert "testkey" not in "".join(logs)


def test_ecos_logs_when_statisticsearch_missing(monkeypatch):
    logs = []
    monkeypatch.setattr(fd, "ECOS_API_KEY", "testkey")
    monkeypatch.setattr(fd, "requests", _fake_requests(lambda url, timeout=None: _Resp(_NO_DATA)))
    monkeypatch.setattr(fd, "log", logs.append)
    assert fd.fetch_ecos_series("200Y104", "10101", "Q") is None
    hit = [m for m in logs if "StatisticSearch 없음" in m]
    assert len(hit) == 1 and "200Y104/10101" in hit[0] and "INFO-200" in hit[0]


def test_fresh_long_history_is_not_clobbered_by_prev():
    long = {f"20{y}Q{q}": 0.5 for y in (23, 24, 25) for q in (1, 2, 3, 4)}   # 12점
    cur = {"economicIndicators": {"kr": {"gdp_kr": {"source": "ECOS:200Y102", "history": dict(long)}}}}
    prev = {"economicIndicators": {"kr": {"gdp_kr": {"source": "ECOS:200Y102",
                                                     "history": {"2019Q1": 9.9, "2025Q4": 9.9}}}}}
    assert fd._accumulate_short_histories(cur, prev) == 0
    assert cur["economicIndicators"]["kr"]["gdp_kr"]["history"] == long


# ── A12 R-ONE 시군구 ────────────────────────────────────────────────────────
def test_rone_classify_uses_gt_path_and_strict_sido():
    c = fd._rone_classify_region
    assert c("전국", "전국") == (None, None)
    assert c("서울", "서울") == ("11", "")
    assert c("서울>강북지역", "강북지역") == (None, None)                 # 권역은 시군구가 아니다
    assert c("서울>강북지역>도심권>종로구", "종로구") == ("11", "종로구")
    assert c("경기>경부1권>성남시>분당구", "분당구") == ("41", "성남시 분당구")
    assert c("경기>동부1권>광주시", "광주시") == ("41", "광주시")          # 광주광역시로 잡지 않는다
    assert c("전남광주>광주", "광주") == ("29", "")
    assert c("전남광주>광주>광산구", "광산구") == ("29", "광산구")
    assert c("전남광주>전남", "전남") == ("46", "")
    assert c("수도권 경기 성남시 분당구", "") == ("41", "성남시 분당구")    # 옛 공백 경로도 유지


def _rone_month(prd, val):
    names = (["전국", "서울", "서울>강북지역", "서울>강북지역>도심권>종로구",
              "경기>경부1권>성남시", "경기>경부1권>성남시>분당구", "경기>경부1권>성남시>수정구",
              "경기>동부1권>광주시", "경기>동부1권>하남시",
              "전남광주>광주", "전남광주>광주>광산구", "전남광주>광주>북구", "전남광주>광주>서구"]
             + [f"서울>강남지역>동남권>시험{i}구" for i in range(50)])
    rows = [{"WRTTIME_IDTFR_ID": prd, "CLS_FULLNM": n, "CLS_NM": n.split(">")[-1], "DTA_VAL": val}
            for n in names]
    return {"SttsApiTblData": [{"head": [{"list_total_count": len(rows)},
                                         {"RESULT": {"CODE": "INFO-000", "MESSAGE": "정상"}}]},
                               {"row": rows}]}


def test_rone_sigungu_queries_single_months(monkeypatch):
    cur_m = fd.datetime.now(fd.KST).strftime("%Y%m")
    calls, logs = [], []

    def get(url, params=None, timeout=None, headers=None):
        calls.append(dict(params))
        prd = params.get("WRTTIME_IDTFR_ID")
        if prd == cur_m:                                   # 이번 달은 아직 미공표
            return _Resp(_NO_DATA)
        n_ok = sum(1 for c in calls if c.get("WRTTIME_IDTFR_ID") != cur_m)
        return _Resp(_rone_month(prd, 101.0 if n_ok == 1 else 100.0))

    monkeypatch.setattr(fd, "REALESTATE_API_KEY", "testkey")
    monkeypatch.setattr(fd, "requests", _fake_requests(get))
    monkeypatch.setattr(fd._time, "sleep", lambda s: None)
    monkeypatch.setattr(fd, "log", logs.append)
    out = fd.fetch_rone_sigungu_breakdown()

    assert len(calls) == 3                                          # 이번 달(빈) + 값 있는 두 달
    assert all("WRTTIME_IDTFR_ID" in c and "WRTTIME_IDTFR_ID_FROM" not in c for c in calls)
    assert len({c["WRTTIME_IDTFR_ID"] for c in calls}) == 3
    rs = out["region_sub"]
    names = {k: {s["name"] for s in v["subs"]} for k, v in rs.items()}
    assert "종로구" in names["11"] and "강북지역" not in names["11"]
    assert names["41"] == {"성남시 분당구", "성남시 수정구", "광주시", "하남시"}   # 구 있는 시는 구 단위만
    assert names["29"] == {"광산구", "북구", "서구"}
    assert all(s["val"] == 1.0 for s in rs["29"]["subs"])
    assert {r["code"] for r in out["region"]} >= {"11", "29"}
    url_logs = [m for m in logs if "SttsApiTblData.do?" in m]
    assert url_logs and all("WRTTIME_IDTFR_ID=" in m and "KEY=" not in m for m in url_logs)
    assert any("표본 CLS_FULLNM=" in m for m in logs)


# ── A8 수집 주기 묶음 ───────────────────────────────────────────────────────
def _prev():
    return {
        "economicIndicators": {
            "kr": {"gdp_kr": {"value": 0.6, "source": "ECOS:200Y102"},
                   "exports_kr": {"value": 1.0, "source": "FRED:XTEXVA01KRM667S"},
                   "pmi_kr": {"value": 50.0, "source": "tradingeconomics.com"}},
            "us": {"vix": {"value": 15.0, "source": "FRED:VIXCLS"},
                   "pmi_us": {"value": 52.0, "source": "tradingeconomics.com"}},
            "jp": {"cpi_jp": {"value": 2.0, "source": "DBnomics:STATJP/CPIm"}},
        },
        "realestate": {
            "kr": {"apt_price_idx_kr": {"value": 100.0, "source": "R-ONE:A_2024_00045"},
                   "region_sub": {"11": {"period": "202608", "subs": [{"name": "종로구", "val": 0.1}],
                                         "source": "R-ONE:A_2024_00045"}}},
            "us": {"mortgage_30y": {"value": 6.5, "source": "FRED:MORTGAGE30US"}},
        },
    }


def test_macro_sections_own_each_leaf_once():
    prev = _prev()
    for ck in ("economicIndicators", "realestate"):
        for g, leaves in prev[ck].items():
            for k in leaves:
                n = sum(1 for s in fd.MACRO_SECTIONS
                        if any((c, gg, kk) == (ck, g, k) for c, gg, kk, _ in fd._macro_leaves(prev, s)))
                assert n == (0 if (g, k) == ("us", "vix") else 1), (ck, g, k, n)


def test_lane_plan_skips_all_when_prev_is_clean(monkeypatch):
    monkeypatch.delenv("FETCH_MACRO", raising=False)
    assert fd._macro_lane_plan(_prev()) == set(fd.MACRO_SECTIONS)        # 기본 = 전부 받는다
    monkeypatch.setenv("FETCH_MACRO", "0")
    assert fd._macro_lane_plan(_prev()) == set()
    assert fd._macro_lane_plan({}) == set(fd.MACRO_SECTIONS)             # 직전이 없으면 받아야 한다


def test_lane_plan_retries_section_with_preserved_leaf(monkeypatch):
    monkeypatch.setenv("FETCH_MACRO", "0")
    p = _prev()
    p["economicIndicators"]["kr"]["gdp_kr"]["preserved"] = True          # 일일 런이 못 받아 되살림
    p["realestate"]["kr"]["region_sub"]["11"]["preserved"] = True        # 한 단계 아래 표식도 본다
    assert fd._macro_lane_plan(p) == {"ecos", "rone"}


def test_carry_lane_marks_reason_not_preserved():
    prev = _prev()
    data = {"economicIndicators": {"us": {"vix": {"value": 16.0, "source": "FRED:VIXCLS"}}}, "realestate": {}}
    n = fd._carry_lane(data, prev, set(fd.MACRO_SECTIONS))
    assert n == 8
    ei, re_ = data["economicIndicators"], data["realestate"]
    assert ei["us"]["vix"] == {"value": 16.0, "source": "FRED:VIXCLS"}  # 이번 런 값은 그대로
    for leaf in (ei["kr"]["gdp_kr"], ei["kr"]["exports_kr"], ei["us"]["pmi_us"], ei["jp"]["cpi_jp"],
                 re_["kr"]["apt_price_idx_kr"], re_["kr"]["region_sub"]["11"], re_["us"]["mortgage_30y"]):
        assert leaf["preserved_reason"] == "lane" and "preserved" not in leaf, leaf
    assert "preserved_reason" not in prev["economicIndicators"]["kr"]["gdp_kr"]   # prev 불변


def test_mark_preserved_distinguishes_lane():
    lane = fd._mark_preserved({"value": 1.0, "preserved": True, "preservedAt": "x"}, reason="lane")
    assert lane == {"value": 1.0, "preserved_reason": "lane"}
    failed = fd._mark_preserved(lane)                                    # 다음 일일 런도 못 받음
    assert failed["preserved"] is True and "preserved_reason" not in failed


def test_data_sla_counts_only_preserved_true():
    def health(extra):
        leaf = dict({"value": 0.6, "period": "2026Q2"}, **extra)
        return data_sla.build_health({"economicIndicators": {"kr": {"gdp_kr": leaf}}}, sources={})
    assert health({"preserved": True})["summary"]["preserved"] == 1     # 경로가 실제로 걸린다
    assert health({"preserved_reason": "lane"})["summary"]["preserved"] == 0


# ── A17 pykrx 누계 · 수급 '검증 불가' ───────────────────────────────────────
def test_pykrx_runs_accumulate():
    assert fd._pykrx_runs(None, True) == {"ok": 1, "fail": 0}
    assert fd._pykrx_runs({"ok": 3, "fail": 1}, False) == {"ok": 3, "fail": 2}
    assert fd._pykrx_runs("깨짐", False) == {"ok": 0, "fail": 1}


_ROW = {"date": "2026-09-11", "foreign": -22915.0, "inst": -12253.0, "retail": 33000.0}


def test_verified_latest_unavailable_without_second_source(monkeypatch):
    monkeypatch.setattr(inf, "portal_daily", lambda m, bizdate=None: ([dict(_ROW)], "naver"))
    monkeypatch.setattr(inf, "toss_daily", lambda m="KOSPI": [])
    out = inf.verified_latest("KOSPI", today="2026-09-11")
    assert out["verified"] == "unavailable" and out["foreign"] == -22915.0   # 숫자는 싣는다
    monkeypatch.setattr(inf, "toss_daily", lambda m="KOSPI": [dict(_ROW, updatedAt=None)])
    assert inf.verified_latest("KOSPI", today="2026-09-11")["verified"] is True
    monkeypatch.setattr(inf, "portal_daily", lambda m, bizdate=None: ([], "krx"))   # 토스 단독
    assert inf.verified_latest("KOSPI", today="2026-09-11")["verified"] == "unavailable"


def test_align_records_unavailable_cross(monkeypatch):
    monkeypatch.setattr(fd, "_fetch_investor_pykrx", lambda lookback_days=20: {"daily": []})
    monkeypatch.setattr(inf, "naver_daily", lambda *a, **k: [dict(_ROW, date="2026-09-28")])
    monkeypatch.setattr(inf, "naver_day", lambda *a, **k: None)
    toss = [dict(_ROW, date="2026-09-22")]                                # 09-28 행이 토스에 없다
    out = fd._investor_align_portal({"daily": toss, "source": "토스"}, None, days=1, backfill=0)
    assert out["crossCheck"] == [{"date": "2026-09-28", "verified": "unavailable", "gross": None}]


# ── A11 Twelve Data 2순위 ──────────────────────────────────────────────────
def test_twelvedata_fills_missing_index_once(monkeypatch):
    calls = []

    def quote(syms, log=None):
        calls.append(list(syms))
        return {"^GSPC": {"price": 6001.0, "change_pct": 0.5},
                "^SOX": {"price": 5000.123, "change_pct": 1.234}}

    monkeypatch.setattr(fd.twelvedata, "enabled", lambda: True)
    monkeypatch.setattr(fd.twelvedata, "quote", quote)
    data = {"indices": {"SP500": {"price": 6000.0, "change": 0.4},
                        "SOX": {"price": 4900.0, "change": None, "stale": True}}, "sources": {}}
    fd._apply_twelvedata(data, {"SP500": "^GSPC", "SOX": "^SOX", "HSI": "^HSI"})
    assert len(calls) == 1
    assert data["indices"]["SP500"] == {"price": 6000.0, "change": 0.4}             # yfinance 값 유지
    assert data["indices"]["SOX"] == {"price": 5000.12, "change": 1.23, "source": "Twelve Data"}
    assert "HSI" not in data["indices"]
    cross = data["diagnostics"]["indexCross"]
    assert [c["sym"] for c in cross] == ["^GSPC"] and cross[0]["ok"] is True      # stale 값과는 대조 안 함


def test_twelvedata_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(fd.twelvedata, "enabled", lambda: False)
    monkeypatch.setattr(fd.twelvedata, "quote", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    data = {"indices": {}}
    fd._apply_twelvedata(data, {"SP500": "^GSPC"})
    assert data == {"indices": {}}
