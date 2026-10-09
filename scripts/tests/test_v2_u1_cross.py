"""U1(수준 도달)은 넘는 순간만 — 2026-10-09 사용자 결정.

직전 쪽은 공개 파일 alerts_state.json._prefs[조건 id].side 한 글자(u 임계 위 · d 아래)로만 남는다.
처음 보는 조건은 쪽만 남기고 울리지 않는다(이미 임계 아래였던 가져온 조건이 켜자마자 한꺼번에 울리지 않게).
파일 쓰기 검사는 임시 폴더에서만 한다.
"""
import datetime as dt
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import run, schedule, subscribe  # noqa: E402
from alerts_v2.ledger import KST, Ledger  # noqa: E402

THR = 1400.5


def _ctx(v, day="2026-10-02", root=None):
    d = dt.date.fromisoformat(day)
    return SimpleNamespace(now=dt.datetime(d.year, d.month, d.day, 10, 0, tzinfo=KST), registry={}, rid=lambda t: t,
                           value=lambda t: v, change_pct=lambda t: None, as_of=lambda t: day, fresh=lambda t: "live",
                           root=root)


def _cond(**kw):
    return dict({"id": "c1", "event": "U1", "target": "usdkrw", "dir": "up", "value": THR, "repeat": "each",
                 "enabled": True}, **kw)


def _run(v, sides, day="2026-10-02", history=(), **kw):
    return subscribe.user_hits(_ctx(v, day), {"alerts": [_cond(**kw)]}, list(history), sides=sides)


def test_first_observation_records_side_without_ringing(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    sides = {}
    assert _run(1410, sides) == [] and sides == {"c1": {"side": "u"}}     # 이미 넘어 있어도 첫 관측은 조용
    sides = {}
    assert _run(1390, sides) == [] and sides == {"c1": {"side": "d"}}


def test_cross_up_rings_then_silent_while_staying(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    sides = {}
    _run(1390, sides)
    rows = _run(1401, sides)                                              # 아래 → 위
    assert [(r["cond"], r["dir"]) for r in rows] == [("c1", "up")]
    assert sides["c1"]["side"] == "u" and isinstance(sides["c1"]["ts"], int) and "fired" not in sides["c1"]
    assert _run(1405, sides, day="2026-10-05") == []                      # 위에 머무는 동안(다음 날도) 조용


def test_cross_down_condition(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    sides = {}
    assert _run(1410, sides, dir="down") == [] and sides["c1"]["side"] == "u"
    assert _run(THR, sides, dir="down")[0]["dir"] == "down"               # 같은 값(이하)도 넘은 것
    assert sides["c1"]["side"] == "d"


def test_each_rings_again_after_going_back(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    sides = {}
    _run(1390, sides, day="2026-10-01")
    first = _run(1401, sides, day="2026-10-01")
    assert _run(1395, sides, day="2026-10-02") == [] and sides["c1"]["side"] == "d"     # 되돌아감 — 조용
    again = _run(1402, sides, day="2026-10-05")                                           # 다시 넘음 — 또
    assert len(first) == len(again) == 1 and first[0]["key"] != again[0]["key"]


def test_once_rings_only_once_until_rearmed(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    sides = {}
    _run(1390, sides, repeat="once")
    assert len(_run(1401, sides, repeat="once")) == 1
    assert sides["c1"]["fired"] is True
    _run(1390, sides, day="2026-10-05", repeat="once")
    assert _run(1401, sides, day="2026-10-05", repeat="once") == []       # 원장 창(8일) 밖이어도 공개 기록이 멈춘다
    armed = "2026-10-06T00:00:00Z"                                         # 다시 켜기 — armedAt 뒤의 첫 교차만
    assert _run(1402, sides, day="2026-10-07", repeat="once", armedAt=armed) == []   # 이미 위 — 교차 아님
    _run(1390, sides, day="2026-10-07", repeat="once", armedAt=armed)
    assert len(_run(1403, sides, day="2026-10-08", repeat="once", armedAt=armed)) == 1


def test_armed_at_compares_instants_not_strings():
    """화면 armedAt 은 UTC(Z), 원장 ts 는 KST — 같은 순간 앞뒤를 글자로 견주면 9시간 어긋난다."""
    c = {"id": "c1", "armedAt": "2026-10-05T03:00:00.000Z"}                 # = 12:00 KST
    assert subscribe._fired_after_arm(c, [{"cond": "c1", "ts": "2026-10-05T11:00:00+09:00"}]) is False
    assert subscribe._fired_after_arm(c, [{"cond": "c1", "ts": "2026-10-05T12:30:00+09:00"}]) is True


def test_broken_or_missing_record_is_safe(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    for bad in ("u", None, {"side": "x"}, {"side": 1}, ["d"]):
        sides = {"c1": bad}
        assert _run(1401, sides) == [] and sides["c1"]["side"] == "u"      # 깨진 기록 = 처음 관측
    assert _run(1401, None) == []                                         # 쪽을 남기지 못하는 런은 U1 을 안 본다
    sides = {"c1": {"side": "d"}}
    assert _run(None, sides) == [] and sides == {"c1": {"side": "d"}}     # 값 없음 — 쪽을 바꾸지 않는다


def test_public_record_has_no_threshold_or_value(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    sides = {}
    for v in (1390.25, 1401.75, 1399.5, 1402.125):
        _run(v, sides, repeat="once")
    text = json.dumps(sides)
    assert set(sides["c1"]) <= {"side", "ts", "fired"} and sides["c1"]["side"] in ("u", "d")
    for secret in ("1400.5", "1390.25", "1401.75", "1399.5", "1402.125"):
        assert secret not in text


def test_state_file_light_only_and_not_on_dry_run(monkeypatch, tmp_path):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    monkeypatch.setenv("ALERTS_V2", "1")
    monkeypatch.setattr(subscribe, "load_prefs", lambda log=print: {"alerts": [_cond()], "settings": {}})
    monkeypatch.setattr(schedule, "plan", lambda *a, **k: [])
    path = tmp_path / "alerts_state.json"
    path.write_text(json.dumps({"_swings": {"kospi": 1}, "_prefs": {"old": {"ts": 1, "fired": True}}}), encoding="utf-8")
    ledger = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path / "events"))

    run._pipeline_b(_ctx(1390, root=str(tmp_path)), [], ledger, dry_run=False, mode="full")
    assert "c1" not in path.read_text(encoding="utf-8")                   # light 가 아니면 U1 · 파일 둘 다 안 건드림
    run._pipeline_b(_ctx(1390, root=str(tmp_path)), [], ledger, dry_run=True, mode="light")
    assert "c1" not in path.read_text(encoding="utf-8")                   # 드라이런은 쓰지 않는다
    run._pipeline_b(_ctx(1390, root=str(tmp_path)), [], ledger, dry_run=False, mode="light")
    st = json.loads(path.read_text(encoding="utf-8"))
    assert st == {"_swings": {"kospi": 1}, "_prefs": {"old": {"ts": 1, "fired": True}, "c1": {"side": "d"}}}

    path.write_text("{깨짐", encoding="utf-8")                             # 깨진 파일은 덮어쓰지 않는다(다른 키 보존)
    run._pipeline_b(_ctx(1401, root=str(tmp_path)), [], ledger, dry_run=False, mode="light")
    assert path.read_text(encoding="utf-8") == "{깨짐"
