"""편성 — 조용한 시간 · 상한 묶음 · 쿨다운 · 안내 무음 · 카톡 쿼터."""
import datetime as dt
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import schedule, schema  # noqa: E402
from alerts_v2.ledger import KST, Ledger  # noqa: E402
from alerts_v2.model import Decision  # noqa: E402

EV = schema.by_id(schema.load_events())


def _ctx(hh, mm=0, day=dt.date(2026, 10, 2)):
    return SimpleNamespace(now=dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=KST))


def _row(i, level="alert", event="A1", target="kospi", dir_="up", ts=None, day="2026-10-02"):
    return {"key": f"{event}:{target}{i}:{dir_}:{day}", "event": event, "target": f"{target}{i}", "dir": dir_,
            "level": level, "value": 1, "unit": "", "asOf": day, "fresh": "live", "title": f"사건 {i}",
            "why": "", "next": "", "url": "#/", "ts": ts or f"{day}T10:0{i % 10}:00+09:00",
            "sent": {"push": 0, "kakao": False, "discord": False, "bundled": False, "held": False}}


def test_quiet_hours_hold_alerts_but_alarm_with_setting_passes(tmp_path):
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    decs = [Decision(_row(1), "alert", True), Decision(_row(2, level="alarm"), "alarm", True)]
    sends = schedule.plan(decs, led, _ctx(23, 30), settings={"quietAlarm": False, "ringChannel": "push"}, events_by_id=EV)
    assert [s.held for s in sends] == [True, True]
    sends = schedule.plan(decs, led, _ctx(6, 59), settings={"quietAlarm": True}, events_by_id=EV)
    assert sends[0].held is True and sends[1].held is False and sends[1].push is True


def test_daily_cap_bundles_overflow(tmp_path):
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    for i in range(6):                           # 이미 6건 울림
        r = _row(i); r["sent"]["push"] = 1; led.append(r)
    decs = [Decision(_row(10 + i), "alert", True) for i in range(3)] + [Decision(_row(30, level="alarm"), "alarm", True)]
    for d in decs:                               # 실제 흐름: 추출기가 원장에 넣은 뒤 편성
        led.append(d.row)
    sends = schedule.plan(decs, led, _ctx(14), settings={"package": "normal"}, events_by_id=EV)
    kinds = [s.kind for s in sends]
    assert kinds.count("bundle") == 1 and kinds.count("event") == 1          # 경보는 상한 밖
    b = next(s for s in sends if s.kind == "bundle")
    assert len(b.bundle) == 3 and b.row["title"].startswith("알림 3건 더")
    assert all(led.get(r["key"])["sent"]["bundled"] for r in b.bundle)


def test_notice_is_discord_only_and_record_dropped(tmp_path):
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    decs = [Decision(_row(1, level="notice", event="B2"), "notice", True), Decision(_row(2, level="record", event="H2"), "record", True)]
    sends = schedule.plan(decs, led, _ctx(15), events_by_id=EV)
    assert len(sends) == 1 and sends[0].discord and not sends[0].push and not sends[0].kakao


def test_cooldown_same_target_dir_within_day_skipped(tmp_path):
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    prev = _row(1, ts="2026-10-02T09:30:00+09:00"); prev["sent"]["push"] = 1
    again = dict(_row(1, ts="2026-10-02T13:00:00+09:00"), key="A1:kospi1:up:2026-10-02b")
    sends = schedule.plan([Decision(again, "alert", True)], led, _ctx(13), events_by_id=EV, history=[prev])
    assert sends == []
    other = dict(again, dir="down", key="A1:kospi1:down:2026-10-02")
    assert len(schedule.plan([Decision(other, "alert", True)], led, _ctx(13), events_by_id=EV, history=[prev])) == 1


def test_kakao_quota_bundles_at_18_and_stops_at_20(tmp_path):
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    for i in range(18):
        r = _row(i, level="notice"); r["sent"]["kakao"] = True; led.append(r)
    decs = [Decision(_row(50), "alert", True), Decision(_row(51, level="alarm"), "alarm", True)]
    sends = schedule.plan(decs, led, _ctx(15), settings={"ringChannel": "kakao", "dailyCap": 12}, events_by_id=EV)
    assert any(s.kind == "bundle" and s.kakao for s in sends)          # 18 → 알림은 묶음으로
    assert any(s.level == "alarm" and s.kakao is False and s.discord for s in sends)  # 경보는 즉시, 카톡 자리 없음
    for i in range(18, 20):
        r = _row(i, level="notice"); r["sent"]["kakao"] = True; led.append(r)
    sends = schedule.plan([Decision(_row(60), "alert", True)], led, _ctx(15), settings={"ringChannel": "kakao"}, events_by_id=EV)
    assert all(not s.kakao for s in sends)                               # 20 → 카톡 멈춤


def test_in_quiet_wraps_midnight():
    q = {"from": "23:00", "to": "07:00"}
    assert schedule.in_quiet(_ctx(23, 0).now, q) and schedule.in_quiet(_ctx(3).now, q)
    assert not schedule.in_quiet(_ctx(7, 0).now, q) and not schedule.in_quiet(_ctx(12).now, q)
