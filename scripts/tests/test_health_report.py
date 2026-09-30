# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import health_report as H  # noqa: E402

ITEMS = [{"path": "a", "state": "ok"}, {"path": "b", "state": "ok"},
         {"path": "c", "state": "stale"}, {"path": "d", "state": "missing"},
         {"path": "e", "state": "preserved"}]
DATA = {"dataHealth": {"items": ITEMS}, "diagnostics": {
    "investorCrossChecked": 10, "investorCrossMismatch": 6,
    "fxTossCross": {"diffPct": -0.16},
    "sourceStatus": {"x.com": {"calls": 10, "fails": 5, "consecutiveFailRuns": 2},
                     "y.com": {"calls": 10, "fails": 0}}}}


def test_counts_and_text():
    cur = H.collect(DATA)
    assert cur["counts"] == {"정상": 2, "지연": 1, "보존": 1, "미확보": 1, "검증 필요": 0}
    assert cur["crossRate"] == 40.0
    t = H.build_text(cur, None, "2026-09")
    assert "정상 2" in t and "x.com : 5/10회 (50.0%)" in t and "y.com" not in t
    assert "40.0%" in t and "첫 보고" in t


def test_missing_source_status():
    cur = H.collect({"dataHealth": {"items": ITEMS}, "diagnostics": {}})
    assert "원천 집계 미수집" in H.build_text(cur, None, "2026-09")
    assert cur["crossRate"] is None


def test_diff():
    cur = H.collect(DATA)
    prev = {"month": "2026-08",
            "counts": {"정상": 4, "지연": 0, "보존": 0, "미확보": 1, "검증 필요": 0},
            "bad": [{"path": "d", "state": "missing"}, {"path": "z", "state": "stale"}]}
    dif = H.diff(cur, prev)
    assert dif["counts"]["정상"] == -2 and dif["new"] == ["c", "e"] and dif["recovered"] == ["z"]
    assert "정상 -2" in H.build_text(cur, dif, "2026-09")
