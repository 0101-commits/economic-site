"""2026-10-11 기획안 대조 점검에서 나온 결함 회귀 — 급변 세기 단계 키 · 안내/구독 밖 쿨다운 · 조용한 시간 · 마감 합침 ·
경보 격상 · 울림 채널 D11 · 「울림 끄기」 · 서킷 항상 켜짐 · 원장 행 단위 병합 · 보류분 디스코드 무음."""
import datetime as dt
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import deliver, schedule, subscribe  # noqa: E402
from alerts_v2.events import Hit, hits_to_rows  # noqa: E402
from alerts_v2.ledger import KST, Ledger, merge_dir  # noqa: E402
from alerts_v2.model import Decision, Send  # noqa: E402

EV = {"A1": {"id": "A1", "judge": "swing_sigma", "family": "A", "level": "alert", "default_on": ["kospi"],
             "cooldown": {"per": ["target", "dir"], "days": 1}, "params": {"clamp_pct": [0.5, 5.0]}},
      "A5": {"id": "A5", "judge": "market_halt", "family": "A", "level": "alarm", "default_on": ["kospi"]},
      "B2": {"id": "B2", "judge": "round_level", "family": "B", "level": "notice", "default_on": ["kospi"],
             "cooldown": {"per": ["target"], "days": 1}},
      "G3": {"id": "G3", "judge": "mer_posts", "family": "G", "level": "notice", "merge": "close", "default_on": ["posts"]}}


def _ctx(hour=15):
    return SimpleNamespace(now=dt.datetime(2026, 10, 2, hour, 0, tzinfo=KST))


def _row(event="A1", level="alert", target="kospi", dir_="up", ts="2026-10-02T15:00:00+09:00", key=None, **kw):
    r = {"key": key or f"{event}:{target}:{dir_}:2026-10-02", "event": event, "target": target, "dir": dir_,
         "level": level, "value": 1.0, "unit": "", "asOf": "2026-10-02", "fresh": "live", "title": "t", "why": "",
         "next": "", "url": "#/", "ts": ts, "sent": {"push": 0, "kakao": False, "discord": False, "bundled": False,
                                                    "held": False}}
    r.update(kw)
    return r


def test_swing_tier_key_lets_bigger_move_in_same_day():
    """2.2σ 로 먼저 들어간 행이 같은 날 2.7σ · 3.2σ 행을 멱등 검사로 막지 않는다(단계마다 한 행)."""
    ev = {"id": "A1", "judge": "swing_sigma", "level": "alert", "url": "#/", "title": "t"}
    ctx = SimpleNamespace(now=dt.datetime(2026, 10, 2, 11, 0, tzinfo=KST))
    keys = [hits_to_rows(ctx, ev, [Hit("kospi", "down", 7000, "", "2026-10-02", "live", -2.0, {"abs_z": z})], None)[0].key
            for z in (2.2, 2.7, 3.2, 2.3)]
    assert keys[0] != keys[1] != keys[2] and keys[0] == keys[3]
    assert keys[2].endswith(":3s")


def test_notice_off_cooldown_quiet_merge(tmp_path):
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    off = Decision(_row("B2", "notice", target="sox"), "notice", False, "관심 아님", on=False)
    assert schedule.plan([off], led, _ctx(), events_by_id=EV) == []            # 관심 밖 안내 = 원장만
    prev = _row("B2", "notice", dir_="down", ts="2026-10-02T10:00:00+09:00", key="B2:kospi:down:2026-10-02")
    prev["sent"]["discord"] = True
    again = Decision(_row("B2", "notice"), "notice", False, "안내")
    assert schedule.plan([again], led, _ctx(), events_by_id=EV, history=[prev]) == []   # 마디 하루 1(방향 무관)
    night = schedule.plan([again], led, _ctx(3), events_by_id=EV, settings={"quiet": {"from": "23:00", "to": "07:00"}})
    assert len(night) == 1 and night[0].held and night[0].discord                   # 조용한 시간 = 보류(아침 합류)
    merged = Decision(_row("G3", "notice", target="posts"), "notice", False, "안내")
    assert schedule.plan([merged], led, _ctx(), events_by_id=EV) == []               # 오늘 16:30 마감 브리핑에 합침
    assert len(schedule.plan([merged], led, _ctx(17), events_by_id=EV)) == 1         # 마감 뒤면 낱개로(안 그러면 어디에도 안 나감)
    off = {"briefings": {"close": False}}
    assert len(schedule.plan([merged], led, _ctx(), settings=off, events_by_id=EV)) == 1   # 마감 브리핑을 껐으면 낱개로


def test_unrung_alert_not_posted_and_alarm_escalates_past_alert_cooldown(tmp_path):
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    natgas = Decision(_row("A1", target="natgas"), "alert", False, "관심 아님", on=False)
    assert schedule.plan([natgas], led, _ctx(), events_by_id=EV) == []              # 관심 아닌 급변은 안 나간다
    rang = _row("A1", ts="2026-10-02T10:00:00+09:00", key="A1:kospi:up:2026-10-02:2.5s")
    rang["sent"]["push"] = 1
    alarm = Decision(_row("A1", level="alarm", key="A1:kospi:up:2026-10-02:3s"), "alarm", True)
    assert len(schedule.plan([alarm], led, _ctx(), events_by_id=EV, history=[rang])) == 1   # 3σ 경보 격상은 통과
    alert2 = Decision(_row("A1", key="A1:kospi:up:2026-10-02:2.5s-b"), "alert", True)
    assert schedule.plan([alert2], led, _ctx(), events_by_id=EV, history=[rang]) == []       # 같은 등급은 하루 1


def test_ring_channel_kakao_falls_back_to_push_without_kakao_ring(tmp_path):
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    d = Decision(_row("A1"), "alert", True)
    s = schedule.plan([d], led, _ctx(), settings={"ringChannel": "kakao"}, events_by_id=EV, kakao_rings=False)
    assert s and s[0].push and not s[0].kakao                                     # D11 — 메모 모드면 폰 푸시가 울린다
    s = schedule.plan([d], led, _ctx(), settings={"ringChannel": "kakao"}, events_by_id=EV, kakao_rings=True)
    assert s and s[0].kakao and not s[0].push


def test_user_ring_off_and_circuit_always_on():
    prefs = {"alerts": [{"id": "c1", "event": "U1", "target": "usdkrw", "ring": False}],
             "settings": {"families": {"A": False}}}
    u = _row("U1", target="usdkrw", cond="c1")
    halt = _row("A5", level="alarm")
    swing = _row("A1")
    ds = subscribe.match([u, halt, swing], None, prefs, EV)
    assert ds[0].ring is False and ds[0].reason == "울림 끔"                      # 「울림 끄기」 = 받은 알림에만
    assert ds[1].ring is True                                                    # 서킷은 갈래 A 를 꺼도 켜짐
    assert ds[2].ring is False and ds[2].reason == "갈래 꺼짐"


def test_ledger_merge_keeps_both_runs_rows(tmp_path):
    mine, remote = tmp_path / "run", tmp_path / "events"
    mine.mkdir(), remote.mkdir()
    a = _row("A1", key="A1:kospi:up:2026-10-02:2.5s")
    b = _row("B2", "notice", key="B2:kospi:up:2026-10-02")
    a_sent = dict(a, sent=dict(a["sent"], push=1))
    (mine / "2026-10-02.json").write_text(json.dumps([a_sent]), encoding="utf-8")
    (remote / "2026-10-02.json").write_text(json.dumps([a, b]), encoding="utf-8")
    assert merge_dir(str(mine), str(remote)) == 1
    rows = {r["key"]: r for r in json.loads((remote / "2026-10-02.json").read_text(encoding="utf-8"))}
    assert set(rows) == {a["key"], b["key"]} and rows[a["key"]]["sent"]["push"] == 1     # 다른 런 행도 남고 발송 기록은 합침
    assert (remote / "latest.json").exists()


def test_held_discord_is_silent(monkeypatch, tmp_path):
    calls = []

    class _D:
        @staticmethod
        def send_level(level, title, body, **kw):
            calls.append(kw)
            return True
    monkeypatch.setitem(sys.modules, "notify_discord", _D)
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    row = _row("B2", "notice")
    led.append(row)
    deliver.send(Send(row=row, level="notice", discord=True, held=True), led, _ctx(3), log=lambda *a: None)
    assert calls and calls[0].get("silent") is True                              # 조용한 시간 — 보관은 하되 깨우지 않는다


def test_cooldown_per_fields_from_row_cd():
    """쿨다운 묶음 키가 행 칸이 아니면(F1 접수번호 · C4 단계) 원장 행 cd 로 가른다 — None 끼리 같다고 보지 않는다."""
    ev = {"id": "F1", "cooldown": {"per": ["target", "rcp"], "days": 365}}
    prev = _row("F1", "notice", target="005930", key="F1:005930:new:a", cd={"rcp": "111"})
    prev["sent"]["discord"] = True
    same = _row("F1", "notice", target="005930", key="F1:005930:new:b", cd={"rcp": "111"})
    other = _row("F1", "notice", target="005930", key="F1:005930:new:c", cd={"rcp": "222"})
    legacy = _row("F1", "notice", target="005930", key="F1:005930:new:d")      # 옛 행(cd 없음) = 막지 않음
    assert schedule.in_cooldown(same, ev, [prev]) is True
    assert schedule.in_cooldown(other, ev, [prev]) is False and schedule.in_cooldown(legacy, ev, [prev]) is False


def test_merge_keeps_held_cleared_and_ignores_history_dir(tmp_path):
    mine, remote = tmp_path / "run", tmp_path / "events"
    (mine / "history").mkdir(parents=True), (remote / "history").mkdir(parents=True)
    r = _row("A1", key="A1:kospi:up:2026-10-02:2.5s")
    held = dict(r, sent=dict(r["sent"], held=True))
    cleared = dict(r, sent=dict(r["sent"], held=False, push=1))
    (mine / "2026-10-02.json").write_text(json.dumps([held]), encoding="utf-8")            # 이번 런 사본은 옛 「보류」
    (remote / "2026-10-02.json").write_text(json.dumps([cleared]), encoding="utf-8")       # 원격은 아침 브리핑이 합류 처리
    (mine / "history" / "vkospi.json").write_text("[1]", encoding="utf-8")
    (remote / "history" / "vkospi.json").write_text("[1, 2]", encoding="utf-8")
    merge_dir(str(mine), str(remote))
    got = json.loads((remote / "2026-10-02.json").read_text(encoding="utf-8"))[0]["sent"]
    assert got["held"] is False and got["push"] == 1                                       # 보류 해제가 이긴다
    assert (remote / "history" / "vkospi.json").read_text(encoding="utf-8") == "[1, 2]"   # history/ 는 건드리지 않는다
