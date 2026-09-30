#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""묘비(폐기) 지표 — 수집에서 뺀 키가 되살아나지 않고, 판정표·레지스트리가 세지 않는다.

2026-09-30 사용자 결정 D1: 전월세전환율(realestate.kr.conversion_rate_kr)은 무료 공식 경로가
없어 화면·판정표에서 뺐는데, 수집(R-ONE 카탈로그 검색)과 직전 값 보존(lane·preserve)이 남아
판정표가 매 런 「stale (as-of 2024-04-01, 883일)」 경고를 냈다.
실행: python -m pytest scripts/tests/test_tombstone.py"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import build_indicators as bi  # noqa: E402
import data_sla  # noqa: E402
import fetch_data as fd  # noqa: E402

KEY = "conversion_rate_kr"
PATH = "realestate.kr." + KEY
# data.json 에 실제로 남아 있던 잎 — 2024-04 이후 갱신 없음, 이번 런이 못 받아 lane 으로 이었던 값
LEAF = {"value": 5.96, "period": "202404", "desc": "전월세전환율 (전국, 월)",
        "history": {"202402": 5.26, "202403": 5.27, "202404": 5.96}, "preserved_reason": "lane"}
FRESH = {"value": 300827.99, "period": "202608", "desc": "전국 아파트 평균 전세가격(천원)",
         "history": {"202606": 1.0, "202607": 1.0, "202608": 1.0}}


def test_drop_tombstoned_removes_conversion_rate_and_keeps_the_rest():
    data = {"realestate": {"kr": {KEY: dict(LEAF), "avg_jeonse_price_kr": dict(FRESH)}}}
    removed = data_sla.drop_tombstoned(data)
    assert removed == [PATH]
    assert KEY not in data["realestate"]["kr"] and "avg_jeonse_price_kr" in data["realestate"]["kr"]
    assert data_sla.drop_tombstoned(data) == []          # 멱등


def test_lane_carry_cannot_resurrect_tombstoned_leaf():
    """매시 풀 런(FETCH_MACRO=0)은 rone 묶음을 건너뛰고 직전 잎을 lane 으로 잇는다 — 묘비가 그 뒤에서 지운다."""
    prev = {"realestate": {"kr": {KEY: dict(LEAF)}}}
    data = {"realestate": {"kr": {}}}
    assert fd._carry_lane(data, prev, {"rone"}) == 1
    assert KEY in data["realestate"]["kr"]               # 이 함수만으로는 되살아난다 — 그래서 묘비가 필요하다
    data_sla.drop_tombstoned(data)
    assert KEY not in data["realestate"]["kr"]


def test_fetch_data_drops_tombstones_after_every_preserve_step():
    src = open(os.path.join(os.path.dirname(fd.__file__), "fetch_data.py"), encoding="utf-8").read()
    drop = src.index("data_sla.drop_tombstoned(data)")
    assert drop > src.index("_carry_lane(data, prev"), "묘비 정리는 lane 이음 뒤여야 한다"
    assert drop > src.rindex("_preserve_from_prev(data, prev"), "묘비 정리는 preserve 뒤여야 한다"


def test_fetch_realestate_no_longer_collects_conversion_rate():
    src = open(os.path.join(os.path.dirname(fd.__file__), "fetch_data.py"), encoding="utf-8").read()
    assert 'result["%s"]' % KEY not in src
    assert 'fetch_rone_table_catalog("전월세전환율"' not in src


def test_health_table_does_not_measure_tombstoned_leaf():
    """옛 data.json 에 잎이 남아 있어도 판정표는 그 경로를 재지 않는다(stale 883일 경고 제거)."""
    data = {"realestate": {"kr": {KEY: dict(LEAF), "avg_jeonse_price_kr": dict(FRESH)}}}
    h = data_sla.build_health(data, today=date(2026, 9, 30), sources={})
    assert PATH not in {i["path"] for i in h["items"]}
    assert h["summary"]["stale"] == 0, h["summary"]


def test_registry_skips_tombstoned_key_even_if_data_json_still_has_it():
    rows, _, _ = bi.build({"realestate": {"kr": {KEY: dict(LEAF), "avg_jeonse_price_kr": dict(FRESH)}}}, {})
    ids = {r["id"] for r in rows}
    assert "conversion_rate_kr" not in ids and "avg_jeonse_price_kr" in ids


def test_collect_only_has_no_entry_for_removed_indicator():
    assert "conversion_rate_kr" not in bi.COLLECT_ONLY
