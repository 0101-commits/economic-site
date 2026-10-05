"""원장 — 멱등 · 하루 파일 · latest.json 7일 합본."""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2.ledger import Ledger, Row, make_key  # noqa: E402


def _row(key="D1:kospi:sell:2026-10-01", **kw):
    base = dict(key=key, event="D1", target="kospi", dir="sell", level="alert", value=-2040, unit="억",
                asOf="2026-10-01", fresh="prev", title="외국인 5일째 순매도 · 오늘 −2,040억",
                why="5일 누적 −7.9조", next="확정 18:00", url="#/market?a=flow",
                ts="2026-10-01T18:05:12+09:00")
    base.update(kw)
    return Row(**base)


def test_append_is_idempotent(tmp_path):
    led = Ledger(day=dt.date(2026, 10, 1), root=str(tmp_path))
    assert led.append(_row()) is True
    assert led.append(_row()) is False          # 같은 key 두 번 없음(재시도 런 · 중복 dispatch)
    assert led.append(_row(key=make_key("D1", "kospi", "buy", "2026-10-01"))) is True
    assert len(led.rows) == 2
    p = led.save()
    assert os.path.basename(p) == "2026-10-01.json"
    again = Ledger(day=dt.date(2026, 10, 1), root=str(tmp_path))
    assert again.has("D1:kospi:sell:2026-10-01") and len(again.rows) == 2


def test_sent_default_and_update(tmp_path):
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    led.append(_row(key="A1:sp500:up:2026-10-02"))
    assert led.get("A1:sp500:up:2026-10-02")["sent"] == {"push": 0, "kakao": False, "discord": False,
                                                        "bundled": False, "held": False}
    led.update_sent("A1:sp500:up:2026-10-02", push=2, discord=True)
    assert led.get("A1:sp500:up:2026-10-02")["sent"]["push"] == 2


def test_latest_merges_seven_days_newest_first(tmp_path):
    for i in range(9):
        d = dt.date(2026, 10, 2) - dt.timedelta(days=i)
        led = Ledger(day=d, root=str(tmp_path))
        led.append(_row(key=f"B2:kospi:up:{d.isoformat()}", event="B2", dir="up", asOf=d.isoformat(), ts=f"{d.isoformat()}T15:35:00+09:00"))
        led.save()
    p = Ledger.rebuild_latest(root=str(tmp_path), end=dt.date(2026, 10, 2))
    rows = json.load(open(p, encoding="utf-8"))
    assert len(rows) == 7
    assert rows[0]["asOf"] == "2026-10-02" and rows[-1]["asOf"] == "2026-09-26"
    assert Ledger.count_in_year("B2", "kospi", end=dt.date(2026, 10, 2), root=str(tmp_path)) == 9


def test_row_has_no_user_threshold_field():
    # 사용자 조건의 임계값은 원장에 넣지 않는다(G5) — Row 에 그런 칸이 없어야 한다
    assert "threshold" not in Row.__dataclass_fields__
