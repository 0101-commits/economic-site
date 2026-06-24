#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""market_halts 단위 테스트 — pytest 없이 직접 실행.
실행: python scripts/test_market_halts.py  (성공 시 'ALL PASS')."""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 스크레이프(네트워크) 비활성 — 1겹(지수) 로직만 결정적으로 테스트
os.environ.pop("NAVER_CLIENT_ID", None)
os.environ.pop("NAVER_CLIENT_SECRET", None)
import market_halts as mh

KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime(2026, 6, 23, 14, 31, tzinfo=KST)


def test_no_halt_when_small_move():
    d = {"indices": {"KOSPI": {"price": 7600, "change": -3.0},
                     "KOSDAQ": {"price": 1140, "change": -2.0}}}
    out = mh.detect_market_halts(d, {}, now=NOW)
    assert out["active"] == [], out
    assert out["history"] == []


def test_cb_stage1_on_minus8():
    d = {"indices": {"KOSPI": {"price": 6992, "change": -8.1},
                     "KOSDAQ": {"price": 1140, "change": -1.0}}}
    out = mh.detect_market_halts(d, {}, now=NOW)
    assert len(out["active"]) == 1, out
    ev = out["active"][0]
    assert ev["type"] == "circuit" and ev["market"] == "KOSPI" and ev["stage"] == 1
    assert ev["id"] == "circuit-KOSPI-20260623"
    assert ev["resumeAt"] == datetime.datetime(2026, 6, 23, 15, 1, tzinfo=KST).isoformat()
    assert ev["endOfDay"] is False


def test_cb_stage3_is_end_of_day():
    d = {"indices": {"KOSPI": {"price": 6080, "change": -20.5}}}
    out = mh.detect_market_halts(d, {}, now=NOW)
    ev = out["active"][0]
    assert ev["stage"] == 3 and ev["endOfDay"] is True and ev["resumeAt"] is None


def test_carry_forward_then_resolve():
    d1 = {"indices": {"KOSPI": {"change": -8.2}}}
    s1 = mh.detect_market_halts(d1, {}, now=NOW)                       # 발동(14:31, resume 15:01)
    assert len(s1["active"]) == 1
    later = NOW + datetime.timedelta(minutes=10)                       # 14:41 등락 회복(-5%)
    s2 = mh.detect_market_halts({"indices": {"KOSPI": {"change": -5.0}}},
                                {"marketHalts": s1}, now=later)
    assert len(s2["active"]) == 1, s2                                  # resume 전 → 유지
    assert s2["active"][0]["triggeredAt"] == s1["active"][0]["triggeredAt"]  # 시작시각 고정
    after = datetime.datetime(2026, 6, 23, 15, 5, tzinfo=KST)          # 15:05 resume 경과
    s3 = mh.detect_market_halts({"indices": {"KOSPI": {"change": -5.0}}},
                                {"marketHalts": s2}, now=after)
    assert s3["active"] == [], s3                                      # 해제
    assert len(s3["history"]) == 1 and s3["history"][0].get("resolvedAt")


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("ALL PASS")


if __name__ == "__main__":
    run()
