#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R-ONE 주택 공급 4표(미분양·착공·인허가·준공) — 전국 코드 질의와 검사 (오프라인).

2026-10-01 키 없이 실측: T 표는 분류 코드가 5자리 정수이고 표마다 다르다(착공·준공 전국>총계 50019 · 인허가
50023 · 미분양 미확인). CLS_ID=500001 은 INFO-200 이라 무필터로 넘어가면 서버가 오래된 순 전체(착공 66,957행)를
주고, 전국 하위 행(전국>총계·전국>공공부문>소계 …)이 시점마다 여럿이라 시점 키로 덮으면 마지막 행이 잡혔다.
ITM 은 10001 하나라 항목 수 검사는 헛통과했다 → (CLS_ID, ITM_ID) 조합·잘림·전국 행으로 검사한다.
실행: python -m pytest scripts/tests/test_rone_housing.py"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import data_sla  # noqa: E402
import fetch_data as fd  # noqa: E402

NEW = {"unsold_total_kr": "T237973129847263", "housing_start_kr": "T233033129823134",
       "housing_permit_kr": "T235263129553687", "housing_complete_kr": "T237273130004614"}
START = NEW["housing_start_kr"]


def _row(p, v, cls=50019, cls_nm="총계", full="전국>총계", itm=10001, itm_nm="착공실적"):
    """실제 응답 모양 — CLS_ID·ITM_ID 는 정수, 이름은 CLS_NM(끝 이름)·CLS_FULLNM(> 경로)."""
    return {"STATBL_ID": START, "DTACYCLE_CD": "MM", "WRTTIME_IDTFR_ID": p, "CLS_ID": cls, "CLS_NM": cls_nm,
            "CLS_FULLNM": full, "ITM_ID": itm, "ITM_NM": itm_nm, "ITM_FULLNM": itm_nm, "DTA_VAL": v, "UI_NM": "호"}


TOTAL = [_row("202605", 17000), _row("202606", 19000), _row("202607", 20378)]
PUBLIC = [_row(p, 900, cls=50020, cls_nm="소계", full="전국>공공부문>소계") for p in ("202605", "202606", "202607")]


def _env(monkeypatch, by_cls):
    """by_cls: CLS_ID 질의값 → 응답 행. 500001 은 늘 None(T 표 실측), 없는 키도 None."""
    calls, logs = [], []

    def stats(sid, item_code1=None, item_code2=None, item_code3=None, period_type="M",
              start_prd=None, end_prd=None, limit=24, page=1):
        calls.append({"sid": sid, "cls": item_code2, "start": start_prd, "end": end_prd, "limit": limit})
        return None if item_code2 == fd.RONE_NATIONWIDE_CLS else by_cls.get(item_code2)

    monkeypatch.setattr(fd, "fetch_rone_stats", stats)
    monkeypatch.setattr(fd, "log", logs.append)
    return calls, logs


def test_cls_query_passes_once_without_retry(monkeypatch):
    calls, logs = _env(monkeypatch, {"50019": TOTAL})
    got = fd.fetch_rone_nationwide_latest(START, limit=1000, strict_item=True, cls_id="50019")
    assert got["value"] == 20378 and got["period"] == "202607" and got["prev"] == 19000
    assert [c["cls"] for c in calls] == ["50019"]                    # 500001·무필터 재시도 없음
    line = next(m for m in logs if "전국 조합 1종" in m)
    assert "(50019, 10001)" in line and "전국>총계/착공실적" in line and "최신 202607" in line


def test_nationwide_sub_rows_per_period_is_none(monkeypatch):
    # 필터가 안 먹어 전국>총계와 전국>공공부문>소계가 같은 시점에 섞여 오면 덮어쓰기 대신 None
    calls, logs = _env(monkeypatch, {"50019": TOTAL + PUBLIC})
    assert fd.fetch_rone_nationwide_latest(START, limit=1000, strict_item=True, cls_id="50019") is None
    line = next(m for m in logs if "전국 조합 2종" in m)
    assert "시점당 조합 2종 이상" in line and "(50020, 10001)" in line and "전국>공공부문>소계" in line
    assert any("조합별 최근 3시점" in m for m in logs) and len(calls) == 1


def test_rows_at_limit_are_truncated(monkeypatch):
    rows = [_row(f"{2011 + i // 12}{i % 12 + 1:02d}", 1000 + i) for i in range(1000)]
    _, logs = _env(monkeypatch, {"50019": rows})
    assert fd.fetch_rone_nationwide_latest(START, limit=1000, strict_item=True, cls_id="50019") is None
    assert any("1000행에서 잘림" in m for m in logs)


def test_no_nationwide_rows_or_empty_is_none_without_retry(monkeypatch):
    seoul = [_row("202607", 5, full="서울>종로구", cls_nm="종로구")]     # 같은 50019 가 다른 표에선 서울>종로구
    calls, logs = _env(monkeypatch, {"50019": seoul})
    assert fd.fetch_rone_nationwide_latest(START, limit=1000, strict_item=True, cls_id="50019") is None
    assert any("전국 행 없음" in m for m in logs)
    calls2, _ = _env(monkeypatch, {})                                   # 응답 없음(INFO-200)
    assert fd.fetch_rone_nationwide_latest(START, limit=1000, strict_item=True, cls_id="50023") is None
    assert len(calls) == 1 and [c["cls"] for c in calls2] == ["50023"]


def test_cumulative_to_monthly():
    cum = {"202611": 150000, "202612": 170000, "202701": 12038, "202702": 29789, "202703": 49827,
           "202705": 99606}                                             # 4월이 빠지면 5월은 뺀다
    got = fd._rone_monthly_from_cumulative({"history": cum})
    assert got["history"] == {"202612": 20000, "202701": 12038, "202702": 17751, "202703": 20038}
    assert (got["value"], got["prev"], got["period"]) == (20038, 17751, "202703")
    assert got["chg"] == round((20038 - 17751) / 17751 * 100, 2)


def test_unknown_cls_probes_single_month_and_loads_nothing(monkeypatch):
    month = [_row("202607", 7000, cls=50266, cls_nm="계", full="전국>계", itm_nm="미분양현황"),
             _row("202607", 300, cls=50019, cls_nm="종로구", full="서울>종로구", itm_nm="미분양현황")]
    calls, logs = [], []

    def stats(sid, item_code1=None, item_code2=None, item_code3=None, period_type="M",
              start_prd=None, end_prd=None, limit=24, page=1):
        calls.append((item_code2, start_prd, end_prd, limit))
        return month if len(calls) == 2 else None                       # 지난달은 빈 응답, 그 전달에 자료

    monkeypatch.setattr(fd, "fetch_rone_stats", stats)
    monkeypatch.setattr(fd, "log", logs.append)
    assert fd.fetch_rone_nationwide_latest(NEW["unsold_total_kr"], limit=1000, strict_item=True) is None
    assert len(calls) == 2 and all(c[0] is None and c[1] == c[2] and len(c[1]) == 6 and c[3] == 1000 for c in calls)
    y, m = int(calls[0][1][:4]), int(calls[0][1][4:])
    assert calls[1][1] == (f"{y}{m - 1:02d}" if m > 1 else f"{y - 1}12")   # 한 달씩 거슬러 간다
    line = next(m for m in logs if "전국 후보" in m)
    assert "(50266, '전국>계', 10001, '미분양현황', 7000)" in line and "서울>종로구" not in line


def test_default_is_unchanged_for_existing_callers(monkeypatch):
    # 비 strict(A 표)는 종전대로 500001 → 실패 시 무필터 재시도, 항목 검사·조합 로그 없음
    calls, logs = _env(monkeypatch, {None: [_row("202608", 300000, cls=500001, cls_nm="전국", full="전국")]})
    got = fd.fetch_rone_nationwide_latest("A_2024_00064", limit=300)
    assert got["value"] == 300000 and [c["cls"] for c in calls] == ["500001", None]
    assert not any("조합" in m for m in logs)


def test_extra_stats_carries_cls_and_cumulative(monkeypatch):
    calls = {}

    def nat(sid, limit=600, itm_id=None, strict_item=False, cls_id=None):
        calls[sid] = (strict_item, cls_id, limit)
        return {"value": 49827.0, "prev": 29789.0, "period": "202703",
                "history": {"202701": 12038.0, "202702": 29789.0, "202703": 49827.0}}

    def offline(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr(fd, "REALESTATE_API_KEY", "k")
    monkeypatch.setattr(fd, "fetch_rone_nationwide_latest", nat)
    monkeypatch.setattr(fd, "fetch_rone_table_catalog", lambda *a, **k: [])
    monkeypatch.setattr(fd, "fetch_rone_sigungu_breakdown", lambda *a, **k: None)
    monkeypatch.setattr(fd, "requests", types.SimpleNamespace(get=offline, post=offline))
    monkeypatch.setattr(fd, "log", lambda *a, **k: None)
    monkeypatch.setenv("AV_FETCH_FULL", "")
    res = fd.fetch_realestate_kr()
    big = fd._RONE_MAX_PSIZE
    assert calls[NEW["housing_start_kr"]] == (True, "50019", big)
    assert calls[NEW["housing_complete_kr"]] == (True, "50019", big)
    assert calls[NEW["housing_permit_kr"]] == (True, "50023", big)
    assert NEW["unsold_total_kr"] not in calls                     # 미분양은 R-ONE 에 전국 행이 없어 KOSIS 가 본선
    assert calls["A_2024_00064"] == (False, None, 300) and calls["A_2024_00057"] == (False, None, 300)
    for key, sid in NEW.items():
        if key == "unsold_total_kr":
            continue
        assert res[key]["unit"] == "호" and res[key]["source"] == "R-ONE:" + sid and res[key]["region"] == "전국"
    permit = res["housing_permit_kr"]                               # 연간 누계 → 월분
    assert permit["history"] == {"202701": 12038.0, "202702": 17751.0, "202703": 20038.0}
    assert permit["value"] == 20038.0 and "월분, 연간 누계 차분" in permit["desc"]
    assert res["housing_start_kr"]["value"] == 49827.0              # 누계 아님 → 그대로


def test_range_rules_cover_the_four_paths():
    paths = {r[0] for r in data_sla.RANGE_RULES}
    assert {"realestate.kr." + k for k in NEW} <= paths
    leaf = lambda v: {"value": v, "period": "202608"}
    bad = data_sla._range_checks({"realestate": {"kr": {
        "unsold_total_kr": leaf(300828), "housing_start_kr": leaf(100.44),     # 표 오인 때 찍힌 두 값
        "housing_permit_kr": leaf(21607), "housing_complete_kr": leaf(15151)}}})
    assert set(bad) == {"realestate.kr.unsold_total_kr", "realestate.kr.housing_start_kr"}


def test_old_keys_stay_tombstoned_and_new_keys_do_not():
    assert data_sla.is_tombstoned("realestate.kr.unsold_kr") and data_sla.is_tombstoned("realestate.kr.start_kr")
    assert not any(data_sla.is_tombstoned("realestate.kr." + k) for k in NEW)
