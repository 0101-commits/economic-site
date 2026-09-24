"""한 점짜리 history 누적(_accumulate_short_histories) 회귀 테스트.

배경: ECOS KeyStatisticList·PMI 스크래핑은 응답이 최신값 하나라 매 런 history 가 1점으로
덮여 추세 차트가 안 그려졌다. 같은 source 일 때만 직전 빌드와 합친다.
실행: python -m pytest scripts/tests/test_history_acc.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fetch_data import _accumulate_short_histories  # noqa: E402


def _d(src, hist):
    return {"economicIndicators": {"kr": {"gdp_kr": {"source": src, "history": hist}}}}


def test_merges_same_source():
    cur = _d("ECOS:KeyStatisticList", {"2026Q2": 0.6})
    assert _accumulate_short_histories(cur, _d("ECOS:KeyStatisticList", {"2026Q1": 0.8})) == 1
    assert cur["economicIndicators"]["kr"]["gdp_kr"]["history"] == {"2026Q1": 0.8, "2026Q2": 0.6}


def test_current_value_wins_on_overlap():
    cur = _d("S", {"2026Q2": 0.7})
    _accumulate_short_histories(cur, _d("S", {"2026Q1": 0.8, "2026Q2": 0.6}))
    assert cur["economicIndicators"]["kr"]["gdp_kr"]["history"]["2026Q2"] == 0.7


def test_skips_when_source_changed():
    cur = _d("B", {"202608": 1})
    assert _accumulate_short_histories(cur, _d("A", {"2026-07-01": 1})) == 0


def test_skips_long_histories():
    long = {f"2020-{m:02d}-01": m for m in range(1, 13)}
    cur = _d("S", dict(long))
    assert _accumulate_short_histories(cur, _d("S", {"2019-12-01": 0})) == 0


def test_caps_length():
    prev = _d("S", {f"{y}Q{q}": 1 for y in range(2000, 2030) for q in range(1, 5)})
    cur = _d("S", {"2030Q1": 2})
    _accumulate_short_histories(cur, prev, cap=60)
    h = cur["economicIndicators"]["kr"]["gdp_kr"]["history"]
    assert len(h) == 60 and "2030Q1" in h
