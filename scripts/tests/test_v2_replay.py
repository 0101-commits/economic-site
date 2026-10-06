"""재생 — 되돌린 문맥이 그날 값 · 등락 · 일봉만 보는지(미래 누설 0)."""
import datetime as dt
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2.replay import ReplayContext  # noqa: E402


def _base():
    bars = [{"date": f"2026-09-{d:02d}", "close": 100 + d} for d in range(1, 31)]
    base = SimpleNamespace(data={}, bundles={}, registry={"kospi": {"id": "kospi"}}, mer={}, root=".",
                           series=lambda t, n=400: bars[-n:] if t == "kospi" else [])
    return base


def test_replay_context_sees_only_that_day():
    ctx = ReplayContext(_base(), dt.date(2026, 9, 10))
    assert ctx.value("kospi") == 110 and round(ctx.change_pct("kospi"), 4) == round(100 / 109, 4)
    assert ctx.series("kospi")[-1]["date"] == "2026-09-10" and len(ctx.series("kospi")) == 10
    assert ctx.fresh("kospi") == "live" and ctx.as_of("kospi") == "2026-09-10"
    assert ctx.now.hour == 15 and ctx.now.tzinfo is not None


def test_replay_context_missing_day_is_missing():
    ctx = ReplayContext(_base(), dt.date(2026, 10, 3))      # 그날 봉 없음(휴장)
    assert ctx.value("kospi") is None and ctx.fresh("kospi") == "missing"
    assert ctx.series("kospi")[-1]["date"] == "2026-09-30"
