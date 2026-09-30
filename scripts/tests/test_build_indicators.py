#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_indicators 생성 규칙 — 사람이 정한 이름은 결정 표(LABEL)가 지키고, 지표가 아닌 사전은 행이 되지 않는다.

2026-09-30: js/app0.js 를 손으로 고친 라벨 3개(cpi_jp·avg_jeonse_price_kr·semi_jeonse_idx_kr)가
생성기에 없어 --check 가 빨갛게 됐고, 새 키 GoldKRW(원화 금값)는 단위 '$' 로, region_sub(시군구
드릴다운 사전)는 지표 행으로 들어갔다.
실행: python -m pytest scripts/tests/test_build_indicators.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import build_indicators as bi


def _rows(data):
    rows, _, _ = bi.build(data, {})
    return {r["id"]: r for r in rows}


def _ind(desc):
    return {"value": 1.0, "period": "2026-08", "desc": desc}


def test_realestate_label_from_decision_table():
    rows = _rows({"realestate": {"kr": {
        "avg_jeonse_price_kr": _ind("전국 아파트 평균 전세가격(천원)"),
        "semi_jeonse_idx_kr": _ind("전국 아파트 준전세가격지수(2026.06=100)")}}})
    assert rows["avg_jeonse_price_kr"]["label"] == "아파트 평균 전세가격 (전국)"
    assert rows["semi_jeonse_idx_kr"]["label"] == "준전세가격지수 (전국)"


def test_macro_label_from_decision_table():
    rows = _rows({"economicIndicators": {"jp": {"cpi_jp": _ind("일본 CPI")}}})
    assert rows["cpi_jp"]["label"] == "일본 소비자물가(전년비)"


def test_drilldown_dict_is_not_an_indicator():
    rows = _rows({"realestate": {"kr": {
        "apt_price_idx_kr": _ind("아파트 매매가격지수"),
        "region_sub": {"11": {"period": "202608", "subs": []}, "26": {"period": "202608", "subs": []}}},
        "us": {"case_shiller_state": {"CA": {"value": 1.0}, "NY": {"value": 2.0}}}}})
    assert "apt_price_idx_kr" in rows
    assert "region_sub_kr" not in rows
    assert "case_shiller_state_us" not in rows


def test_gold_krw_is_won_not_dollar():
    rows = _rows({"commodities": {"Gold": {"price": 4000.0}, "GoldKRW": {"price": 181460.0}}})
    assert rows["goldkrw"]["label"] == "금 현물 (KRX)"
    assert rows["goldkrw"]["unit"] == "원" and rows["goldkrw"]["decimals"] == 0
    assert rows["gold"]["unit"] == "$"                                   # 달러 금값은 그대로
