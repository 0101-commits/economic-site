"""400일 재생(G3) — 일봉 · 수급 이력으로 사전을 하루씩 되돌려 돌려 「하루 몇 통 울릴지」를 센다(기획서 10장 G3).

재생할 수 있는 사건 = 과거 값이 데이터에 있는 것: A1~A4 급변 · B1 52주 · B2 마디 · C7 금리 · D1~D4 수급.
렌즈 · 일정 · 공시 · 번들 전용 값(VIX 단계 등)은 과거 상태가 없어 뺀다(표에 「재생 밖」으로 적음).

  python scripts/alerts_v2/replay.py [--days 400] [--sigma 2.5] [--watch gold,wti] [--out docs/alerts_v2_replay.md]
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import os
import statistics
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from alerts_v2 import schema  # noqa: E402
from alerts_v2.context import KST, Context  # noqa: E402
from alerts_v2.events import JUDGES, extract  # noqa: E402
from alerts_v2.ledger import Ledger  # noqa: E402

try:
    from alerts_v2 import judges_market, judges_flow_cal  # noqa: F401,E402
except ImportError:
    pass

REPLAYABLE = {"A1", "A2", "A3", "A4", "B1", "B2", "C7", "D1", "D2", "D3", "D4"}
SETTLE = {"D1", "D2", "D3", "D4"}


class ReplayContext(Context):
    """날짜 d 로 되돌린 문맥 — 값 · 등락 · 신선도 · 일봉이 전부 d 기준."""

    def __init__(self, base: Context, day: dt.date, hour: int = 15, minute: int = 35):
        super().__init__(now=dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=KST),
                         data=base.data, bundles=base.bundles, registry=base.registry, mer=base.mer, root=base.root)
        self._base = base
        self._day = day.isoformat()
        self._cache: dict[str, list[dict]] = {}

    def _full(self, target: str) -> list[dict]:
        if target not in self._cache:
            self._cache[target] = self._base.series(target, 10000)
        return self._cache[target]

    def series(self, target: str, n: int = 400) -> list[dict]:
        bars = [b for b in self._full(target) if b.get("date") and str(b["date"])[:10] <= self._day]
        return bars[-n:]

    def _last_two(self, target: str):
        bars = self.series(target, 2)
        if not bars or str(bars[-1]["date"])[:10] != self._day:
            return None, None
        prev = bars[-2]["close"] if len(bars) > 1 else None
        return bars[-1]["close"], prev

    def strip(self, target: str):
        v, prev = self._last_two(target)
        if v is None:
            return None
        s = {"id": self.rid(target), "value": v, "asOf": self._day, "state": "live", "fresh": "live"}
        if prev:
            s["change"] = v - prev
            s["changePct"] = (v / prev - 1) * 100
        return s

    def value(self, target: str):
        return (self.strip(target) or {}).get("value")

    def change_pct(self, target: str):
        return (self.strip(target) or {}).get("changePct")

    def fresh(self, target: str) -> str:
        return "live" if self.strip(target) else "missing"

    def as_of(self, target: str) -> str:
        return self._day


def trading_days(base: Context, days: int) -> list[dt.date]:
    seen = set()
    for t in ("kospi", "sp500", "usdkrw", "gold"):
        for b in base.series(t, 10000):
            if b.get("date"):
                seen.add(str(b["date"])[:10])
    out = sorted(dt.date.fromisoformat(d) for d in seen)
    return out[-days:]


def run(days: int = 400, sigma: float | None = 2.5, watch: list[str] | None = None, out: str | None = None) -> dict:
    base = Context.load()
    events = [ev for ev in schema.load_events() if ev["id"] in REPLAYABLE and ev["judge"] in JUDGES]
    if sigma is not None:
        events = copy.deepcopy(events)
        for ev in events:
            if ev["judge"] == "swing_sigma":
                ev.setdefault("params", {})["sigma"] = sigma
    watch = set(watch or [])
    tmp = tempfile.mkdtemp(prefix="v2replay_")
    counts: dict[str, int] = {}
    rung_per_day: dict[str, int] = {}
    level_counts: dict[str, int] = {}
    skipped = sorted({ev["id"] for ev in schema.load_events() if ev["id"] not in REPLAYABLE and not ev["id"].startswith("U")})
    for day in trading_days(base, days):
        led = Ledger(day=day, root=tmp)
        for ev in events:
            hour, minute = (18, 5) if ev["id"] in SETTLE else (15, 35)
            ctx = ReplayContext(base, day, hour, minute)
            rows = extract(ctx, [ev], led, render=None)
            for r in rows:
                counts[ev["id"]] = counts.get(ev["id"], 0) + 1
                level_counts[r.level] = level_counts.get(r.level, 0) + 1
                on = r.target in (ev.get("default_on") or []) or r.target in watch
                if on and r.level in ("alarm", "alert"):
                    rung_per_day[day.isoformat()] = rung_per_day.get(day.isoformat(), 0) + 1
        led.save()
    n_days = max(1, len(trading_days(base, days)))
    per_day = list(rung_per_day.values()) + [0] * (n_days - len(rung_per_day))
    summary = {
        "days": n_days, "sigma": sigma, "watch": sorted(watch),
        "counts": counts, "levels": level_counts,
        "rung_total": sum(per_day), "rung_avg": sum(per_day) / n_days,
        "rung_max": max(per_day) if per_day else 0,
        "rung_p90": sorted(per_day)[int(0.9 * (len(per_day) - 1))] if per_day else 0,
        "skipped": skipped,
    }
    if out:
        write_md(summary, out)
    return summary


def write_md(s: dict, path: str) -> None:
    lines = [f"# 알림 v2 400일 재생 — σ {s['sigma'] or '사전 기본'} · 관심 {', '.join(s['watch']) or '없음'}", "",
             f"거래일 {s['days']} · 울림(경보 + 알림, 기본 켜짐 + 관심) 합계 {s['rung_total']} · 하루 평균 {s['rung_avg']:.2f} · "
             f"상위 10% 날 {s['rung_p90']} · 최대 {s['rung_max']}", "",
             "| 사건 | 건수 | 연 환산 |", "|---|---|---|"]
    for k in sorted(s["counts"]):
        lines.append(f"| {k} | {s['counts'][k]} | {s['counts'][k] * 250 / s['days']:.0f} |")
    lines += ["", "등급별: " + " · ".join(f"{k} {v}" for k, v in sorted(s["levels"].items())),
              "", "재생 밖(과거 상태 없음): " + ", ".join(s["skipped"])]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=400)
    ap.add_argument("--sigma", type=float, default=2.5)   # 사전은 2.0(보통) — 재생은 기본 세기 big 로 센다
    ap.add_argument("--watch", default="")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    s = run(a.days, a.sigma, [w for w in a.watch.split(",") if w], a.out)
    print(f"거래일 {s['days']} · 울림 합계 {s['rung_total']} · 하루 평균 {s['rung_avg']:.2f} · 최대 {s['rung_max']}")
    for k in sorted(s["counts"]):
        print(f"  {k}: {s['counts'][k]} (연 {s['counts'][k] * 250 / s['days']:.0f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
