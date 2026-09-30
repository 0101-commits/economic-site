#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""market_halts 단위 테스트 — pytest 없이 직접 실행.
실행: python scripts/tests/test_market_halts.py  (성공 시 'ALL PASS')."""
import os
import sys
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
# 스크레이프(네트워크) 비활성 — 1겹(지수) 로직만 결정적으로 테스트
os.environ.pop("NAVER_CLIENT_ID", None)
os.environ.pop("NAVER_CLIENT_SECRET", None)
import market_halts as mh

KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime(2026, 6, 23, 14, 31, tzinfo=KST)
PD = "2026-06-22"   # NOW(6/23 화)의 직전 영업일 — 달력이 없으면 평일 역산


def _d(pd=PD, key="price", **mk):
    """{'KOSPI': (가격, 전일比%)} → indices + 직전 영업일 종가 이력(가격 None 이면 이력 없음).
    판정은 공급원 change 가 아니라 이 종가 기준으로 계산된다(2026-07-29 회귀)."""
    ind, hist = {}, {}
    for m, (p, c) in mk.items():
        ind[m] = {key: p, "change": c}
        if p is not None:
            hist[m] = [{"date": pd, "close": p / (1 + c / 100)}]
    return {"indices": ind, "history": {"indices": hist}}


def test_no_halt_when_small_move():
    d = _d(KOSPI=(7600, -3.0), KOSDAQ=(1140, -2.0))
    out = mh.detect_market_halts(d, {}, now=NOW)
    assert out["active"] == [], out
    assert out["history"] == []


def test_cb_stage1_on_minus8():
    d = _d(KOSPI=(6992, -8.1), KOSDAQ=(1140, -1.0))
    out = mh.detect_market_halts(d, {}, now=NOW)
    assert len(out["active"]) == 1, out
    ev = out["active"][0]
    assert ev["type"] == "circuit" and ev["market"] == "KOSPI" and ev["stage"] == 1
    assert ev["id"] == "circuit-KOSPI-20260623"
    assert ev["resumeAt"] == datetime.datetime(2026, 6, 23, 15, 1, tzinfo=KST).isoformat()
    assert ev["endOfDay"] is False


def test_cb_stage3_is_end_of_day():
    d = _d(KOSPI=(6080, -20.5))
    out = mh.detect_market_halts(d, {}, now=NOW)
    ev = out["active"][0]
    assert ev["stage"] == 3 and ev["endOfDay"] is True and ev["resumeAt"] is None


def test_carry_forward_then_resolve():
    d1 = _d(KOSPI=(6992, -8.2))
    s1 = mh.detect_market_halts(d1, {}, now=NOW)                       # 발동(14:31, resume 15:01)
    assert len(s1["active"]) == 1
    later = NOW + datetime.timedelta(minutes=10)                       # 14:41 등락 회복(-5%)
    s2 = mh.detect_market_halts(_d(KOSPI=(7230, -5.0)),
                                {"marketHalts": s1}, now=later)
    assert len(s2["active"]) == 1, s2                                  # resume 전 → 유지
    assert s2["active"][0]["triggeredAt"] == s1["active"][0]["triggeredAt"]  # 시작시각 고정
    after = datetime.datetime(2026, 6, 23, 15, 5, tzinfo=KST)          # 15:05 resume 경과
    s3 = mh.detect_market_halts(_d(KOSPI=(7230, -5.0)),
                                {"marketHalts": s2}, now=after)
    assert s3["active"] == [], s3                                      # 해제
    assert len(s3["history"]) == 1 and s3["history"][0].get("resolvedAt")


# ── 회귀: 세션 게이트 3중 (2026-07-02 15:43 장마감 후 오발송 실사건) ──
def test_no_cb_after_market_close():
    """① 장마감(15:30) 후에는 -8% 여도 지수기반 CB 를 만들지 않는다(07-02 실사건 재현)."""
    after_close = datetime.datetime(2026, 6, 23, 15, 43, tzinfo=KST)   # 화요일 15:43
    d = _d(KOSPI=(6992, -8.0))
    out = mh.detect_market_halts(d, {}, now=after_close)
    assert out["active"] == [], out
    before_open = datetime.datetime(2026, 6, 23, 8, 59, tzinfo=KST)    # 개장 전
    assert mh.detect_market_halts(d, {}, now=before_open)["active"] == []


def test_no_cb_on_weekend():
    """① 주말 hourly 런이 금요일 -8% '종가'를 보고 오발동하지 않는다."""
    d = _d(KOSPI=(6992, -8.1))
    for day in (27, 28):                                               # 토·일
        wk = datetime.datetime(2026, 6, day, 10, 0, tzinfo=KST)
        assert mh.detect_market_halts(d, {}, now=wk)["active"] == [], day


def test_stage12_blocked_after_1450_stage3_allowed():
    """② KRX 규정: 1·2단계는 14:50 이후 발동 불가, 3단계(endOfDay)만 15:30 까지."""
    late = datetime.datetime(2026, 6, 23, 14, 55, tzinfo=KST)
    d12 = _d(KOSPI=(6400, -15.5))     # 2단계 상당
    assert mh.detect_market_halts(d12, {}, now=late)["active"] == []
    d3 = _d(KOSPI=(6080, -20.5))      # 3단계
    out = mh.detect_market_halts(d3, {}, now=late)
    assert len(out["active"]) == 1 and out["active"][0]["stage"] == 3, out


def test_no_cb_when_value_none():
    """③ 지수 값 None + change=-8.00 오염(07-02 실사건 직접 원인) → 감지 스킵 + stale."""
    d = _d(KOSPI=(None, -8.0))
    out = mh.detect_market_halts(d, {}, now=NOW)
    assert out["active"] == [], out
    assert out["stale"] is True, out                                   # 깜깜이 빌드로 표시
    # 라이브 모드 산출 키(value)도 동일하게 취급
    d2 = _d(key="value", KOSPI=(None, -8.0))
    assert mh.detect_market_halts(d2, {}, now=NOW)["active"] == []
    # value 키로 정상 값이 오면 감지된다(check_halts 라이브 경로)
    d3 = _d(key="value", KOSPI=(6992.0, -8.1))
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


# ── 회귀: 뉴스 오탐 (2026-09-30 실사건) ──
# 19:44 기사 「사이드카도 멈춘 9월 코스피 … 이달 매수·매도 사이드카는 한 차례도 발동(되지 않았다)」가
# '발동' 부분일치로 사이드카 + 서킷 1단계 둘 다 발송됐다. 그날 KOSPI 는 -0.48%.
def _news(typ, market="KOSPI", t=None):
    t = t or NOW
    return {"id": mh._halt_id(typ, market, t.strftime("%Y%m%d")), "type": typ, "market": market,
            "stage": 1 if typ == "circuit" else None, "direction": "down",
            "reason": "이달 매수·매도 사이드카는 한 차례도 발동", "triggeredAt": t.isoformat(),
            "resumeAt": (t + datetime.timedelta(minutes=5)).isoformat(),
            "endOfDay": False, "source": "news", "approx": True}


def _with_news(events, fn):
    orig = mh.scrape_market_halts
    mh.scrape_market_halts = lambda now: [dict(e) for e in events]
    try:
        return fn()
    finally:
        mh.scrape_market_halts = orig


def test_news_ignored_after_close_quiet_day():
    now = datetime.datetime(2026, 9, 30, 19, 48, tzinfo=KST)
    d = _d(pd="2026-09-29", KOSPI=(3400, -0.48), KOSDAQ=(900, 0.72))
    out = _with_news([_news("sidecar", t=now), _news("circuit", t=now)],
                     lambda: mh.detect_market_halts(d, {}, now=now))
    assert out["active"] == [], out


def test_news_ignored_in_session_quiet_day():
    d = _d(KOSPI=(3400, -0.48))
    out = _with_news([_news("sidecar"), _news("circuit")],
                     lambda: mh.detect_market_halts(d, {}, now=NOW))
    assert out["active"] == [], out


def test_news_sidecar_accepted_on_big_move():
    d = _d(KOSPI=(3400, 4.2))
    out = _with_news([_news("sidecar")], lambda: mh.detect_market_halts(d, {}, now=NOW))
    assert [h["type"] for h in out["active"]] == ["sidecar"], out


def test_news_circuit_needs_index_cb():
    d = _d(KOSPI=(3400, -5.0))           # -8% 미달
    out = _with_news([_news("circuit")], lambda: mh.detect_market_halts(d, {}, now=NOW))
    assert out["active"] == [], out


def test_uncorroborated_news_dropped_from_history():
    prev = {"marketHalts": {"active": [], "history": [
        dict(_news("sidecar"), resolvedAt=NOW.isoformat()),
        {"id": "circuit-KOSPI-20260626", "source": "index", "reason": "KOSPI 지수 전일比 -8.52%"}]}}
    out = mh.detect_market_halts({"indices": {}}, prev, now=NOW)
    assert [h["id"] for h in out["history"]] == ["circuit-KOSPI-20260626"], out


# ── 회귀: 전일 종가 밀림 (2026-07-29 실사건 — 가짜 서킷 4건) ──
# 개장 무렵 Yahoo 일봉이 7/28 봉을 7/29 날짜로 내보냈다(이력: 7/27 6755.75 · '7/29' 6023.66, 7/28 없음).
# 그래서 공급원의 change 와 rows[-2] 가 전부 7/27 종가 기준이 됐다 — 전일(7/28) 종가는 6023.66.
D729 = datetime.datetime(2026, 7, 29, 9, 12, tzinfo=KST)
H_POISONED = {"KOSPI": [{"date": "2026-07-27", "close": 6755.75}, {"date": "2026-07-29", "close": 6023.66}],
              "KOSDAQ": [{"date": "2026-07-27", "close": 764.86}, {"date": "2026-07-29", "close": 705.85}]}
H_OK = {"KOSPI": [{"date": "2026-07-27", "close": 6755.75}, {"date": "2026-07-28", "close": 6023.66}],
        "KOSDAQ": [{"date": "2026-07-27", "close": 764.86}, {"date": "2026-07-28", "close": 705.85}]}


def test_0729_open_stale_change_no_cb():
    """09:12 — fetch_data 지수가 전일 종가·전일 등락률(-10.84%) 그대로. 장은 그때 +1.5%."""
    d = {"indices": {"KOSPI": {"price": 6023.66, "change": -10.84}}, "history": {"indices": H_POISONED}}
    out = mh.detect_market_halts(d, {}, now=D729)
    assert out["active"] == [], out


def test_0729_live_prev_shifted_no_cb():
    """09:45 KOSDAQ -8.13% · 11:20 KOSPI -15.11% · 12:23 KOSDAQ -15.09% — 라이브 조회가 7/27 을 전일로 씀."""
    cases = [(datetime.time(9, 45), "KOSDAQ", 702.68, -8.13, H_POISONED),
             (datetime.time(11, 20), "KOSPI", 5734.9, -15.11, H_OK),
             (datetime.time(12, 23), "KOSDAQ", 649.44, -15.09, H_OK)]
    for t, m, price, chg, hist in cases:
        now = datetime.datetime.combine(D729.date(), t, tzinfo=KST)
        out = mh.detect_market_halts({"indices": {m: {"value": price, "change": chg}}},
                                     {"history": {"indices": hist}}, now=now)
        assert all(h.get("stage") != 2 for h in out["active"]), (t, out)
        if m == "KOSDAQ" and t.hour == 9:
            assert out["active"] == [], (t, out)                       # 실제 +0.45% — 발동 자체가 가짜


def test_0729_real_cb_still_fires():
    """12:50 진짜 1단계 — 5531.56 / 전일 6023.66 = -8.17%."""
    now = datetime.datetime(2026, 7, 29, 12, 50, tzinfo=KST)
    out = mh.detect_market_halts({"indices": {"KOSPI": {"value": 5531.56, "change": -8.1}}},
                                 {"history": {"indices": H_OK}}, now=now)
    assert [(h["market"], h["stage"]) for h in out["active"]] == [("KOSPI", 1)], out
    assert "-8.17%" in out["active"][0]["reason"], out


def test_prev_business_day_from_calendar():
    """연휴 다음 날 — 직전 영업일은 달력(marketCalendarKr)이 정한다. 평일 역산이면 휴일을 짚는다."""
    now = datetime.datetime(2026, 10, 8, 10, 0, tzinfo=KST)                # 목, 10/7 휴장 가정
    cal = {"today": {"date": "2026-10-08"}, "previousBusinessDay": {"date": "2026-10-06"}}
    d = {"indices": {"KOSPI": {"price": 6400.0, "change": -3.0}}, "marketCalendarKr": cal,
         "history": {"indices": {"KOSPI": [{"date": "2026-10-06", "close": 7000.0}]}}}
    out = mh.detect_market_halts(d, {}, now=now)                           # 6400/7000 = -8.57%
    assert [h["stage"] for h in out["active"]] == [1], out


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("ALL PASS")


if __name__ == "__main__":
    run()
