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


def _ctx(v, day="2026-10-02", root=None, scale=None, registry=None):
    d = dt.date.fromisoformat(day)
    return SimpleNamespace(now=dt.datetime(d.year, d.month, d.day, 10, 0, tzinfo=KST), registry=registry or {},
                           rid=lambda t: t, value=lambda t: v, change_pct=lambda t: None, as_of=lambda t: day,
                           fresh=lambda t: "live", scale=lambda t: scale, root=root)


def _cond(**kw):
    return dict({"id": "c1", "event": "U1", "target": "usdkrw", "dir": "up", "value": THR, "repeat": "each",
                 "enabled": True}, **kw)


def _run(v, sides, day="2026-10-02", history=(), **kw):
    return subscribe.user_hits(_ctx(v, day), {"alerts": [_cond(**kw)]}, list(history), sides=sides)


def _sent(v, sides, day="2026-10-02", **kw):
    """판정 → 실제로 나갔다고 치고 울림 기록(mark_sent)까지 — 울림 기록은 발송된 행에만 남는다."""
    rows = _run(v, sides, day, **kw)
    subscribe.mark_sent(sides, {"alerts": [_cond(**kw)]}, rows, SimpleNamespace(get=lambda k: {"sent": {"push": 1}}),
                        _ctx(v, day).now)
    return rows


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
    assert sides["c1"] == {"side": "u"}                                   # 울림 기록(ts)은 판정이 아니라 발송 뒤(mark_sent)
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
    assert len(_sent(1401, sides, repeat="once")) == 1
    assert sides["c1"]["fired"] is True and isinstance(sides["c1"]["ts"], int)
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
        _sent(v, sides, repeat="once")
    text = json.dumps(sides)
    assert set(sides["c1"]) == {"side", "ts", "fired"} and sides["c1"]["side"] in ("u", "d")
    for secret in ("1400.5", "1390.25", "1401.75", "1399.5", "1402.125"):
        assert secret not in text


def test_state_doc_light_only_and_not_on_dry_run(monkeypatch, tmp_path):
    """_pipeline_b 는 파일을 쓰지 않고 「원장 저장 뒤 쓸 문서」만 돌려준다(쓰기는 run.main — test_v2_user_pipeline)."""
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    monkeypatch.setenv("ALERTS_V2", "1")
    monkeypatch.setattr(subscribe, "load_prefs", lambda log=print: {"alerts": [_cond()], "settings": {}})
    monkeypatch.setattr(schedule, "plan", lambda *a, **k: [])
    path = tmp_path / "alerts_state.json"
    raw = json.dumps({"_swings": {"kospi": 1}, "_prefs": {"c1x": {"ts": 1, "fired": True}}})
    path.write_text(raw, encoding="utf-8")
    ledger = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path / "events"))

    assert run._pipeline_b(_ctx(1390, root=str(tmp_path)), [], ledger, dry_run=False, mode="full") is None   # light 만
    assert run._pipeline_b(_ctx(1390, root=str(tmp_path)), [], ledger, dry_run=True, mode="light") is None   # 드라이런
    st = run._pipeline_b(_ctx(1390, root=str(tmp_path)), [], ledger, dry_run=False, mode="light")
    assert st == {"_swings": {"kospi": 1}, "_prefs": {"c1": {"side": "d"}}}   # 지운 조건(c1x) 기록은 정리
    assert path.read_text(encoding="utf-8") == raw                        # 파일은 그대로

    path.write_text("{깨짐", encoding="utf-8")                             # 깨진 파일은 덮어쓰지 않는다(다른 키 보존)
    assert run._pipeline_b(_ctx(1401, root=str(tmp_path)), [], ledger, dry_run=False, mode="light") is None


def test_arm_side_after_save_or_enable(monkeypatch):
    """저장 · 켜기 때 화면이 잰 쪽(armSide)이 armedAt 뒤 첫 관측의 직전 쪽 — 밤에 만든 조건의 시초 갭 · 꺼 둔 동안의 쪽."""
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    eve = "2026-10-01T12:00:00Z"                                           # 전날 21:00 KST 저장, 그때 임계 위(u)
    sides = {}
    rows = _run(1395, sides, dir="down", armedAt=eve, armSide="u")         # 다음 날 시초 갭으로 곧장 아래 — 넘음
    assert [r["dir"] for r in rows] == ["down"] and sides["c1"]["side"] == "d"
    assert _run(1390, sides, dir="down", armedAt=eve, armSide="u") == []   # 그 뒤엔 공개 쪽 — 머묾

    on = "2026-10-02T00:30:00Z"                                            # 꺼 둔 조건을 09:30 KST 에 다시 켬, 그때 위(u)
    sides = {"c1": {"side": "d", "ts": 1}}                                 # 남은 쪽은 끄기 전의 아래
    assert _run(1405, sides, armedAt=on, armSide="u") == [] and sides["c1"]["side"] == "u"
    _run(1395, sides, armedAt=on, armSide="u")
    assert len(_run(1402, sides, day="2026-10-05", armedAt=on, armSide="u")) == 1   # 켠 뒤엔 보통의 교차

    sides = {"c1": {"side": "d"}}                                          # 켠 순간 값을 몰랐으면(armSide 없음) 첫 관측 무음
    assert _run(1405, sides, armedAt=on) == [] and sides["c1"]["side"] == "u"

    ahead = "2026-10-02T01:30:00Z"                                         # 기기 시계가 서버보다 빨라도 한 번만 반영
    sides = {}
    _run(1395, sides, armedAt=ahead, armSide="d")
    assert sides["c1"]["at"] == int(subscribe._sec(ahead))
    assert len(_run(1401, sides, armedAt=ahead, armSide="u")) == 1         # 이제 공개 쪽(d)을 본다 — armSide 를 다시 안 씀


def test_scaled_indicator_compares_and_says_in_screen_units(monkeypatch):
    """축척 지표(묶음 scale) — 조건 값은 화면 단위(사용자가 본 그대로). 엔/원 원본 8.95(scale 0.01) = 화면 895원."""
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    from alerts_v2 import compose
    reg = {"jpykrw": {"short": "엔/원", "unit": "원", "decimals": 2}}
    cond = _cond(target="jpykrw", value=900)

    def run_(raw, sides):
        ctx = _ctx(raw, scale=0.01, registry=reg)
        return subscribe.user_hits(ctx, {"alerts": [cond]}, [], render=lambda ev, h: compose.render(ev, h, ctx), sides=sides)

    sides = {}
    assert run_(8.95, sides) == [] and sides["c1"]["side"] == "d"        # 895원 < 900원 — 원본 8.95 를 900 과 견주면 안 된다
    rows = run_(9.05, sides)                                              # 905원 — 넘음
    assert [r["dir"] for r in rows] == ["up"]
    assert rows[0]["title"] == "엔/원 905.00원 · 내 조건 위로" and rows[0]["value"] == 905.0
