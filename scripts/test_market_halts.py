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
    d1 = {"indices": {"KOSPI": {"price": 6992, "change": -8.2}}}
    s1 = mh.detect_market_halts(d1, {}, now=NOW)                       # 발동(14:31, resume 15:01)
    assert len(s1["active"]) == 1
    later = NOW + datetime.timedelta(minutes=10)                       # 14:41 등락 회복(-5%)
    s2 = mh.detect_market_halts({"indices": {"KOSPI": {"price": 7230, "change": -5.0}}},
                                {"marketHalts": s1}, now=later)
    assert len(s2["active"]) == 1, s2                                  # resume 전 → 유지
    assert s2["active"][0]["triggeredAt"] == s1["active"][0]["triggeredAt"]  # 시작시각 고정
    after = datetime.datetime(2026, 6, 23, 15, 5, tzinfo=KST)          # 15:05 resume 경과
    s3 = mh.detect_market_halts({"indices": {"KOSPI": {"price": 7230, "change": -5.0}}},
                                {"marketHalts": s2}, now=after)
    assert s3["active"] == [], s3                                      # 해제
    assert len(s3["history"]) == 1 and s3["history"][0].get("resolvedAt")


# ── 회귀: 세션 게이트 3중 (2026-07-02 15:43 장마감 후 오발송 실사건) ──
def test_no_cb_after_market_close():
    """① 장마감(15:30) 후에는 -8% 여도 지수기반 CB 를 만들지 않는다(07-02 실사건 재현)."""
    after_close = datetime.datetime(2026, 6, 23, 15, 43, tzinfo=KST)   # 화요일 15:43
    d = {"indices": {"KOSPI": {"price": 6992, "change": -8.0}}}
    out = mh.detect_market_halts(d, {}, now=after_close)
    assert out["active"] == [], out
    before_open = datetime.datetime(2026, 6, 23, 8, 59, tzinfo=KST)    # 개장 전
    assert mh.detect_market_halts(d, {}, now=before_open)["active"] == []


def test_no_cb_on_weekend():
    """① 주말 hourly 런이 금요일 -8% '종가'를 보고 오발동하지 않는다."""
    d = {"indices": {"KOSPI": {"price": 6992, "change": -8.1}}}
    for day in (27, 28):                                               # 토·일
        wk = datetime.datetime(2026, 6, day, 10, 0, tzinfo=KST)
        assert mh.detect_market_halts(d, {}, now=wk)["active"] == [], day


def test_stage12_blocked_after_1450_stage3_allowed():
    """② KRX 규정: 1·2단계는 14:50 이후 발동 불가, 3단계(endOfDay)만 15:30 까지."""
    late = datetime.datetime(2026, 6, 23, 14, 55, tzinfo=KST)
    d12 = {"indices": {"KOSPI": {"price": 6400, "change": -15.5}}}     # 2단계 상당
    assert mh.detect_market_halts(d12, {}, now=late)["active"] == []
    d3 = {"indices": {"KOSPI": {"price": 6080, "change": -20.5}}}      # 3단계
    out = mh.detect_market_halts(d3, {}, now=late)
    assert len(out["active"]) == 1 and out["active"][0]["stage"] == 3, out


def test_no_cb_when_value_none():
    """③ 지수 값 None + change=-8.00 오염(07-02 실사건 직접 원인) → 감지 스킵 + stale."""
    d = {"indices": {"KOSPI": {"price": None, "change": -8.0}}}
    out = mh.detect_market_halts(d, {}, now=NOW)
    assert out["active"] == [], out
    assert out["stale"] is True, out                                   # 깜깜이 빌드로 표시
    # 라이브 모드 산출 키(value)도 동일하게 취급
    d2 = {"indices": {"KOSPI": {"value": None, "change": -8.0}}}
    assert mh.detect_market_halts(d2, {}, now=NOW)["active"] == []
    # value 키로 정상 값이 오면 감지된다(check_halts 라이브 경로)
    d3 = {"indices": {"KOSPI": {"value": 6992.0, "change": -8.1}}}
    assert len(mh.detect_market_halts(d3, {}, now=NOW)["active"]) == 1


def test_merge_endofday_or():
    """B 회귀: 1→3단계 격상 병합 시 endOfDay 는 OR(더 심각한 쪽) — '가장 이른' 기준이면
    3단계 격상 후에도 False 로 남아 당일종료 유지가 깨진다."""
    ev1 = mh.cb_from_index("KOSPI", -8.5, NOW)                          # 1단계(이른 시각)
    ev3 = mh.cb_from_index("KOSPI", -20.5, NOW + datetime.timedelta(minutes=20))  # 3단계 격상
    merged = mh._merge(ev1, ev3)
    assert merged["stage"] == 3, merged
    assert merged["endOfDay"] is True, merged
    assert merged["resumeAt"] is None, merged                           # 당일종료 = 재개시각 없음
    assert merged["triggeredAt"] == ev1["triggeredAt"]                  # 시작시각은 이른 값 유지


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("ALL PASS")


if __name__ == "__main__":
    run()
