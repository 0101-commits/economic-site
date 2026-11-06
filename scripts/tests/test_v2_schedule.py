"""편성 — 조용한 시간 · 하루 최대(주의만 셈) 묶음 · 쿨다운 · 안내는 폰 알림 없음 · 사건은 카톡 없음."""
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
    for i in range(10):                          # 이미 10건 울림(기본 하루 최대)
        r = _row(i); r["sent"]["push"] = 1; led.append(r)
    decs = [Decision(_row(10 + i), "alert", True) for i in range(3)] + [Decision(_row(30, level="alarm"), "alarm", True)]
    for d in decs:                               # 실제 흐름: 추출기가 원장에 넣은 뒤 편성
        led.append(d.row)
    sends = schedule.plan(decs, led, _ctx(14), settings={"package": "normal"}, events_by_id=EV)
    kinds = [s.kind for s in sends]
    assert kinds.count("bundle") == 1 and kinds.count("event") == 1          # 경보는 상한 밖
    b = next(s for s in sends if s.kind == "bundle")
    assert len(b.bundle) == 3 and b.row["title"] == "하루 최대를 넘은 알림 3건"
    assert b.push and not b.kakao                                            # 묶음도 폰 알림만
    assert all(led.get(r["key"])["sent"]["bundled"] for r in b.bundle)


def test_cap_counts_only_alerts_not_alarms_joined_or_bundled(tmp_path):
    """하루 최대는 주의(alert) 폰 알림만 센다 — 경보 · 아침 합류(joined) · 묶음에 든 행 · 안내는 안 센다."""
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    for i in range(10):                          # 경보 10통 — 안 센다
        r = _row(i, level="alarm"); r["sent"]["push"] = 1; led.append(r)
    for i in range(10, 20):                      # 합류한 보류분 10건 · 묶인 10건 — 안 센다
        r = _row(i); r["sent"].update(push=1, joined=True); led.append(r)
    for i in range(20, 30):
        r = _row(i); r["sent"].update(push=1, bundled=True); led.append(r)
    assert schedule._ring_count_today(led) == 0
    r = _row(40); r["sent"]["push"] = 1; led.append(r)                      # 주의 한 통만 센다
    assert schedule._ring_count_today(led) == 1
    sends = schedule.plan([Decision(_row(50), "alert", True)], led, _ctx(14), settings={"dailyCap": 2}, events_by_id=EV)
    assert len(sends) == 1 and sends[0].kind != "bundle" and sends[0].push


def test_notice_not_pushed_and_record_dropped(tmp_path):
    """안내(notice)는 폰 알림 없음(원장에만) · 기록은 발송 없음 — 「많이」의 안내→주의 격상은 subscribe 몫(2026-11-06 P1)."""
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    decs = [Decision(_row(1, level="notice", event="B2"), "notice", True), Decision(_row(2, level="record", event="H2"), "record", True)]
    assert schedule.plan(decs, led, _ctx(15), events_by_id=EV) == []


def test_event_sends_are_push_only_even_with_old_kakao_settings(tmp_path):
    """ringChannel · 카톡 쿼터 칸은 읽지 않는다 — 사건은 어떤 설정이든 폰 알림만, 카톡 없음."""
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    for i in range(20):                          # 옛 쿼터 20 소진 모양 — 영향 없음
        r = _row(i, level="notice"); r["sent"]["kakao"] = True; led.append(r)
    decs = [Decision(_row(50), "alert", True), Decision(_row(51, level="alarm"), "alarm", True)]
    for ring in ("kakao", "both", "push"):
        sends = schedule.plan(decs, led, _ctx(15), settings={"ringChannel": ring, "kakaoBundleAt": 1, "kakaoQuota": 1},
                              events_by_id=EV)
        assert len(sends) == 2 and all(s.push and not s.kakao and s.kind != "bundle" for s in sends)


def test_cooldown_same_target_dir_within_day_skipped(tmp_path):
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    prev = _row(1, ts="2026-10-02T09:30:00+09:00"); prev["sent"]["push"] = 1
    again = dict(_row(1, ts="2026-10-02T13:00:00+09:00"), key="A1:kospi1:up:2026-10-02b")
    sends = schedule.plan([Decision(again, "alert", True)], led, _ctx(13), events_by_id=EV, history=[prev])
    assert sends == []
    other = dict(again, dir="down", key="A1:kospi1:down:2026-10-02")
    assert len(schedule.plan([Decision(other, "alert", True)], led, _ctx(13), events_by_id=EV, history=[prev])) == 1


def test_memo_sends_do_not_count_toward_cap_or_quota(tmp_path):
    """카톡 메모(나에게 보내기)는 울림이 아니다 — deliver 가 sent.memo 로 적고, 하루 상한 · 카톡 쿼터는 그걸 안 센다."""
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    for i in range(6):
        r = _row(i); r["sent"].update(memo=True, discord=True); led.append(r)
    assert schedule._ring_count_today(led) == 0 and schedule._kakao_count_today(led) == 0
    sends = schedule.plan([Decision(_row(50), "alert", True)], led, _ctx(15), settings={"dailyCap": 6}, events_by_id=EV)
    assert len(sends) == 1 and sends[0].kind != "bundle" and sends[0].push


def test_in_quiet_wraps_midnight():
    q = {"from": "23:00", "to": "07:00"}
    assert schedule.in_quiet(_ctx(23, 0).now, q) and schedule.in_quiet(_ctx(3).now, q)
    assert not schedule.in_quiet(_ctx(7, 0).now, q) and not schedule.in_quiet(_ctx(12).now, q)


def test_story_pushes_only_when_step_rises():
    """이어진 알림(P3): 11/6 국내 증시 — 사이드카(코스닥) 폰 알림 → 서킷 1단계(코스피) 다시 알림 → 같은 단계 사이드카 · 급변은 기록만."""
    from alerts_v2 import schedule as S
    from alerts_v2.model import Decision

    class L:
        def __init__(self):
            self.rows = []
        def update_sent(self, key, **kw):
            for r in self.rows:
                if r["key"] == key:
                    r.setdefault("sent", {}).update(kw)

    led = L()
    def row(key, ev, tgt, level, ts):
        r = {"key": key, "event": ev, "target": tgt, "level": level, "ts": f"2026-11-06T{ts}:00+09:00", "title": key, "sent": {}}
        led.rows.append(r)
        return r
    ctx = type("C", (), {"now": __import__("datetime").datetime(2026, 11, 6, 9, 21, tzinfo=__import__("datetime").timezone(__import__("datetime").timedelta(hours=9))), "data": {}})()
    sets = {"quiet": None}
    a = row("A5:kosdaq:enter:2026-11-06.sidecar", "A5", "kosdaq", "alarm", "09:21")
    out = S.plan([Decision(a, "alarm", True)], led, ctx, sets)
    assert [o.row["key"] for o in out] == [a["key"]] and led.rows[0]["sent"]["story"] == "2026-11-06:kr"
    led.rows[0]["sent"]["push"] = 1                                     # 발송됨
    b = row("A5:kospi:enter:2026-11-06.circuit1", "A5", "kospi", "alarm", "09:26")
    c = row("A1:kospi:down:2026-11-06:2s", "A1", "kospi", "alert", "09:26")
    d = row("A5:kospi:enter:2026-11-06.sidecar", "A5", "kospi", "alarm", "09:37")
    out = S.plan([Decision(b, "alarm", True), Decision(c, "alert", True), Decision(d, "alarm", True)], led, ctx, sets)
    assert [o.row["key"] for o in out] == [b["key"]]                    # 단계 오름만 폰 알림
    assert c["sent"].get("folded") and d["sent"].get("folded")          # 나머지는 이야기 카드로
    assert S.story_key({"event": "A1", "target": "sp500", "ts": "2026-11-06T00:12"}) == "2026-11-06:us"
    assert S.story_key({"event": "E2", "target": "calendar", "ts": "2026-11-06T00:12"}) is None

    e = dict(row("A5:kosdaq:exit:2026-11-06.sidecar", "A5", "kosdaq", "alarm", "09:26"), dir="exit")
    led.rows[-1] = e
    out = S.plan([Decision(e, "alarm", True)], led, ctx, sets)
    assert [o.row["key"] for o in out] == [e["key"]] and not e["sent"].get("folded")   # 해제는 단계가 아니다 — 늘 나간다


def test_merge_sent_keeps_story_label():
    """푸시 충돌 재시도 합치기가 이야기 이름표(글자)를 True 로 바꾸지 않는다(P3 검토)."""
    from alerts_v2.ledger import _merge_sent
    m = _merge_sent({"story": "2026-11-06:kr", "push": 1}, {"push": 0})
    assert m["story"] == "2026-11-06:kr" and m["push"] == 1
    assert _merge_sent({"push": 0}, {"story": "2026-11-06:us"})["story"] == "2026-11-06:us"
