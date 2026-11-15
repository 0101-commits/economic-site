#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""읽는 값(scripts/read_values.py) 가드 — 공식값 우선 · 반올림 한 번 · 날짜로 찾는 1년 전 · 빈칸 사유 · 기간 대응.
실행: python -m pytest scripts/tests/test_read_values.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import consensus  # noqa: E402
import read_values as rv  # noqa: E402


def _monthly(start_y, start_m, vals, skip=()):
    out, y, m = {}, start_y, start_m
    for v in vals:
        k = "%d-%02d-01" % (y, m)
        if k[:7] not in skip:
            out[k] = v
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def test_round_once_half_up():
    assert rv.rnd(0.35, 1) == 0.4            # 부동소수 0.3499… 로 내려가지 않는다
    assert rv.rnd(0.649, 1) == 0.6           # 0.65 로 먼저 자르면 0.7 이 된다(2026-11 일정 칸 버그)
    assert rv.rnd(-0.25, 1) == -0.3
    assert rv.rnd(3.75, 1) == 3.8
    assert rv.rnd(None, 1) is None


def test_ref_of_release():
    assert rv.ref_of_release("2026-11-11", "M", 1) == "2026-10"     # 미국 CPI 10월분
    assert rv.ref_of_release("2026-11-03", "M", 1) == "2026-10"     # 한국 CPI
    assert rv.ref_of_release("2026-11-05", "M", 2) == "2026-09"     # 한국 경상수지(두 달 뒤)
    assert rv.ref_of_release("2026-10-27", "Q", 1) == "2026-Q3"     # 한국 GDP 속보
    assert rv.ref_of_release("2026-10-19", "Q", 1) == "2026-Q3"     # 중국 GDP(분기 끝 19일 뒤)
    assert rv.ref_of_release("2026-12-23", "Q", 1) == "2026-Q3"     # 미국 GDP 확정치
    assert rv.ref_of_release("2026-01-29", "Q", 1) == "2025-Q4"
    assert rv.ref_of_release("2026-10-30", "D", 1) == "2026-10-29"
    # 기준 달은 한국 날짜 발표일로 센다 — 9/30 밤 미국 PCE(8월분)는 조회일이 10/1 이다(검토 2026-11-15)
    assert rv.ref_of_release("2026-10-01", "M", 1, "United States") == "2026-08"
    assert rv.ref_of_release("2026-11-01", "M", 1, "Euro Zone", "eu_cpi_yoy") == "2026-10"      # 10/31 속보 = 10월분
    assert rv.ref_of_release("2026-11-18", "M", 1, "Euro Zone", "eu_cpi_yoy") == "2026-10"      # 확정치
    assert rv.ref_of_release("2026-11-01", "M", 1, "South Korea", "kr_exports_yoy") == "2026-10"
    assert rv.ref_of_release("2026-11-15", "M", 1, "South Korea", "kr_exports_yoy") is None     # 중순 잠정치는 받지 않는다
    assert rv.released_of("2026-11-11", "United States") == "2026-11-10"
    assert rv.released_of("2026-11-03", "South Korea") == "2026-11-03"


def test_shift_and_keys():
    assert rv.shift("2026-01", "M", -1) == "2025-12" and rv.shift("2026-10", "M", -12) == "2025-10"
    assert rv.shift("2026-Q1", "Q", -1) == "2025-Q4"
    assert rv.ref_of_key("202610", "M") == "2026-10" and rv.ref_of_key("2026-10-01", "M") == "2026-10"
    assert rv.ref_of_key("2026-07-01", "Q") == "2026-Q3" and rv.ref_of_key("2026Q2", "Q") == "2026-Q2"


def test_yoy_by_date_not_index():
    """빠진 달(2025-10)이 있으면 2026-10 전년비는 없고, 2026-09 는 2025-09 와 견준다(칸 순서로 세면 2025-08)."""
    hist = rv.norm_history({"history": _monthly(2025, 1, [100 + i for i in range(22)], skip={"2025-10"})}, "M")
    yoy = rv.calc_series(hist, rv.B("yoy"), "M")
    assert "2026-10" not in yoy
    assert yoy["2026-09"] == pytest.approx((120 / 108 - 1) * 100)


def _cpi_leaf():
    vals = [300 + i for i in range(22)]
    return {"value": 321.0, "period": "2026-10-01", "history": _monthly(2025, 1, vals, skip={"2025-10"})}


def test_official_first_and_why():
    off = {"us_cpi_mom": [{"q": "2026-10-15", "a": 0.6, "c": 0.6, "p": 0.4}, {"q": "2026-11-11", "a": 0.4, "c": 0.3, "p": 0.6}],
           "us_cpi_yoy": [{"q": "2026-10-15", "a": 3.7, "c": 3.6, "p": 3.4}]}
    stats = {"us_cpi_mom": {"n": 9, "meanAbs": 0.05}}
    rd = rv.build_read(_cpi_leaf(), rv.RULES["economicIndicators.us.cpi_us"], off, stats)
    assert rd["ref"] == "2026-10" and rd["main"]["value"] == 0.4 and rd["main"]["src"] == "official"
    assert rd["main"]["b"] == "mom" and rd["main"]["sign"] is True and rd["main"]["unit"] == "%"
    assert (rd["prev"], rd["cons"], rd["diff"], rd["size"]) == (0.6, 0.3, 0.1, "큼")       # 0.1 ÷ 0.05 = 2배
    assert rd["released"] == "2026-11-10"
    yoy = rd["subs"][0]
    assert yoy["b"] == "yoy" and yoy["value"] is None and yoy["why"] == "1년 전 값 미발표"
    assert rd["rel"][-1] == ["2026-10", 0.4, 0.3]
    assert rd["series"][-1] == ["2026-10", 0.4]                                           # 공식값이 계산값을 덮는다


def test_calc_when_no_official():
    rd = rv.build_read(_cpi_leaf(), rv.RULES["economicIndicators.us.cpi_us"], {}, {})
    assert rd["main"]["src"] == "calc" and rd["main"]["value"] == rv.rnd((321 / 320 - 1) * 100, 1)
    assert "cons" not in rd and "released" not in rd


def test_official_fresher_than_leaf():
    """한국 수출: 통관 금액은 9월분까지인데 산업부 공식 전년비는 10월분이 먼저 온다 → 큰 숫자는 10월, 금액은 9월(ref 표시)."""
    leaf = {"value": 121050082000, "period": "2026-09-01",
            "history": _monthly(2025, 1, [60e9 + i * 1e9 for i in range(21)])}
    off = {"kr_exports_yoy": [{"q": "2026-11-01", "a": 93.7, "c": 93.2, "p": 83.7}]}
    rd = rv.build_read(leaf, rv.RULES["economicIndicators.kr.exports_kr"], off, {})
    assert rd["ref"] == "2026-10" and rd["main"]["value"] == 93.7 and rd["released"] == "2026-11-01"
    amt = rd["subs"][0]
    assert amt["b"] == "level" and amt["ref"] == "2026-09" and amt["unit"] == "억 달러" and amt["value"] == 1210.5


def test_diff_scale_and_range():
    nfp = {"value": 159293.0, "period": "2026-10-01", "history": {"2026-09-01": 159128.0, "2026-10-01": 159293.0}}
    rd = rv.build_read(nfp, rv.RULES["economicIndicators.us.nfp_us"], {"us_nfp": [{"q": "2026-11-07", "a": 165, "c": 65, "p": 60}]}, {})
    assert rd["main"]["value"] == 16.5 and rd["main"]["unit"] == "만 명" and rd["cons"] == 6.5 and rd["prev"] == 6.0
    # 크기는 나스닥 단위(K)로 견준다 — 10만 명(100K) 차이 ÷ 평소 60K = 1.67배 → 큼(만 명으로 견주면 0.17배라 늘 침묵)
    rd = rv.build_read(nfp, rv.RULES["economicIndicators.us.nfp_us"], {"us_nfp": [{"q": "2026-11-07", "a": 165, "c": 65, "p": 60}]},
                       {"us_nfp": {"n": 11, "meanAbs": 60}})
    assert rd["size"] == "큼"
    ff = {"value": 4.0, "period": "2026-11-14", "history": {"2026-09-17": 4.25, "2026-11-14": 4.0}}
    rd = rv.build_read(ff, rv.RULES["economicIndicators.us.ff_target"], {}, {})
    assert rd["main"]["b"] == "range" and rd["main"]["value"] == 4.0 and rd["main"]["lo"] == 3.75 and rd["prev"] == 4.25
    # 일간: 마지막 공식 결정(10/29)이 지금 수준과 같으면 그 발표로 본다(결정일 ≠ 이력 마지막 날)
    rd = rv.build_read(ff, rv.RULES["economicIndicators.us.ff_target"], {"us_fed": [{"q": "2026-10-30", "a": 4.0, "c": 4.0, "p": 4.25}]}, {})
    assert rd["main"]["src"] == "official" and rd["released"] == "2026-10-29" and rd["cons"] == 4.0 and rd["prev"] == 4.25


def test_attach_marks_mismatch():
    data = {"economicIndicators": {"us": {"cpi_us": _cpi_leaf()}},
            "economicCalendar": {"officialHistory": {"series": {"us_cpi_mom": [{"q": "2026-11-11", "a": 0.9, "c": 0.3}]}}}}
    st = rv.attach(data)
    assert st["filled"] == 1 and st["official"] == 1
    assert st["mismatch"] and st["mismatch"][0]["path"] == "economicIndicators.us.cpi_us"     # 0.9 vs 계산 0.31


def test_rules_point_at_official_keys():
    """RULES 의 공식값 열쇠는 전부 consensus.OFFICIAL_MAP 에 있다(오타면 그 지표는 늘 계산값만 쓴다)."""
    for path, rule in rv.RULES.items():
        for b in [rule["main"], *rule["subs"]]:
            if b["off"]:
                assert b["off"] in consensus.OFFICIAL_MAP, (path, b["off"])


def test_single_row_day():
    """2026-11-10 미국 CPI: 전년비 줄이 빠지고 전월비 한 줄만 왔다 — 지난 발표값 기억으로 전월비로 가른다."""
    rows = [{"country": "United States", "eventName": "CPI", "actual": "0.4%", "consensus": "0.3%", "previous": "0.6%"}]
    assert consensus.pick_row(rows, "United States", "cpi", "short") is None                   # 기억 없으면 고르지 않는다
    mem = {"short": 0.6, "long": 3.7}
    assert consensus.pick_row(rows, "United States", "cpi", "short", mem) is rows[0]
    assert consensus.pick_row(rows, "United States", "cpi", "long", mem) is None
    assert consensus.pick_row(rows, "United States", "cpi", "short", {"short": 0.6, "long": 0.7}) is None   # 가까우면 모른다
    series = {}
    consensus.harvest({"2026-10-15": [dict(rows[0], actual="0.6%", previous="0.4%"),
                                      dict(rows[0], actual="3.7%", consensus="3.6%", previous="3.4%")],
                       "2026-11-11": rows}, series, consensus.OFFICIAL_MAP)
    assert [x["a"] for x in series["us_cpi_mom"]] == [0.6, 0.4] and [x["a"] for x in series["us_cpi_yoy"]] == [3.7]


def test_compute_change_by_date():
    pytest.importorskip("pykrx")       # fetch_data 는 수집 의존성이 있는 환경에서만 불러온다
    import fetch_data as fd
    h = {"2025-08-01": 100.0, "2025-09-01": 101.0, "2025-11-01": 103.0, "2026-08-01": 103.0, "2026-09-01": 101.0 * 1.00649,
         "2026-10-01": 105.0}
    assert fd._compute_change(h, "2026-09-01", "yoy") == 0.6           # 0.649 → 반올림 한 번
    assert fd._compute_change(h, "2026-10-01", "yoy") is None          # 2025-10 없음 → 13개월 전과 비교하지 않는다
    assert fd._compute_change(h, "2025-11-01", "mom") is None          # 지난달(2025-10) 없음


def test_official_backfill_also_on_hourly_runs():
    """1년 채우기 전엔 매시 풀 런(full=False)도 20일씩 거꾸로 훑는다 — 다 채우면 요청 0."""
    import datetime as dt
    asked = []
    now = dt.datetime(2026, 11, 15, 12, 0, tzinfo=consensus.KST)
    off, st = consensus.update_official({"scannedTo": "2026-07-24"}, {}, full=False, now=now,
                                        fetch=lambda q: asked.append(q) or [], pause=0)
    assert len(asked) == consensus._BACKFILL_HOURLY and max(asked) == "2026-07-23" and off["scannedTo"] == min(asked)
    asked.clear()
    consensus.update_official({"scannedTo": "2025-10-01"}, {}, full=False, now=now, fetch=lambda q: asked.append(q) or [], pause=0)
    assert asked == []


def test_user_condition_on_read_value(monkeypatch):
    """알림 조건(벨) basis=read — 지수(337.5)가 아니라 읽는 값(전월비 +0.4%)과 견준다. 옛 조건(basis 없음)은 그대로 원값."""
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    import datetime as dt
    from alerts_v2 import compose, subscribe
    from alerts_v2.context import Context
    leaf = dict(_cpi_leaf(), read={"name": "소비자물가", "ref": "2026-10", "freq": "M",
                                   "main": {"b": "mom", "short": "전월비", "value": 0.4, "unit": "%", "dec": 1, "sign": True}})
    ctx = Context(now=dt.datetime(2026, 11, 15, 12, 0, tzinfo=consensus.KST), data={"economicIndicators": {"us": {"cpi_us": leaf}}},
                  bundles={}, registry={"cpi_us": {"id": "cpi_us", "label": "미국 소비자물가", "dataPath": "economicIndicators.us.cpi_us"}}, mer={})
    conds = [{"id": "r1", "event": "U1", "target": "cpi_us", "dir": "up", "value": 0.3, "basis": "read"},   # 0.4 ≥ 0.3 → 울림
             {"id": "r2", "event": "U1", "target": "cpi_us", "dir": "up", "value": 1.0, "basis": "read"},   # 0.4 < 1.0
             {"id": "r3", "event": "U2", "target": "cpi_us", "value": 1.0, "basis": "read"},               # 읽는 값엔 U2 없음
             {"id": "o1", "event": "U1", "target": "cpi_us", "dir": "up", "value": 1.0}]                   # 옛 조건 = 지수 321 ≥ 1
    sides = {c["id"]: {"side": "d"} for c in conds if c["event"] == "U1"}
    prefs = {"alerts": [dict(c, enabled=True, repeat="each") for c in conds]}
    rows = subscribe.user_hits(ctx, prefs, [], render=lambda ev, h: compose.render(ev, h, ctx), log=lambda *a: None, sides=sides)
    assert sorted(r["cond"] for r in rows) == ["o1", "r1"]
    r1 = next(r for r in rows if r["cond"] == "r1")
    assert "+0.4%" in r1["title"] and "0.3" not in r1["title"]          # 임계값은 공개 원장에 없다(G5)
