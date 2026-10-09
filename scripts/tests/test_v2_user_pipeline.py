"""사용자 조건의 발송 사슬(run._pipeline_b · run.main) — 2026-10-09 리뷰 지적.

- 쿨다운은 [조건 id · 방향] — 같은 대상의 두 조건이 서로 막지 않는다. 다시 켠 조건은 새 원장 키이고 그 전 울림은 쿨다운에서 뺀다.
- 울림 기록(ts · fired)은 원장에 들어가 실제로 나간 행만. 「한 번」 U2 · B1 도 남겨 원장 8일 창 밖에서 다시 울리지 않는다.
- 사용자 조건은 light 런에서만 판정. 공개 기록(alerts_state.json)은 원장을 저장한 뒤에만 쓴다.
- 지운 조건의 기록은 /prefs 를 정상으로 읽은 런에서만 정리.
원장 · 공개 기록은 임시 폴더, 발송은 가짜(네트워크 없음).
"""
import datetime as dt
import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import deliver, run, subscribe  # noqa: E402
from alerts_v2 import ledger as ledger_mod  # noqa: E402
from alerts_v2.ledger import KST, Ledger  # noqa: E402


def _at(day, hm):
    return dt.datetime.fromisoformat(f"{day}T{hm}:00").replace(tzinfo=KST)


def _ctx(at, root, value=None, chg=None):
    return SimpleNamespace(now=at, registry={}, rid=lambda t: t, value=lambda t: value, change_pct=lambda t: chg,
                           as_of=lambda t: at.date().isoformat(), fresh=lambda t: "live", scale=lambda t: None,
                           root=str(root))


def _u(cid, event="U1", **kw):
    return dict({"id": cid, "event": event, "target": "usdkrw", "dir": "up", "repeat": "each", "enabled": True}, **kw)


def _base(monkeypatch, tmp_path):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    monkeypatch.setenv("ALERTS_V2", "1")
    monkeypatch.setattr(ledger_mod, "EVENTS_DIR", str(tmp_path / "events"))   # 진짜 events/ 를 읽지도 쓰지도 않는다
    monkeypatch.setattr(run, "_render", lambda ctx: None)


@pytest.fixture
def env(monkeypatch, tmp_path):
    _base(monkeypatch, tmp_path)
    sent = []

    def send(s, ledger, ctx, log=print, ok=True):
        sent.append(s.row.get("cond"))
        if ok:
            ledger.update_sent(s.row["key"], push=1, discord=True)
        return {}
    monkeypatch.setattr(deliver, "send", send)

    def one(prefs, at, value=None, chg=None, mode="light", sides=None):
        """한 런: 공개 기록을 읽고 판정 · 발송 · 원장 저장 → 공개 기록(바뀐 것, 없으면 읽은 그대로)."""
        monkeypatch.setattr(subscribe, "load_prefs", lambda log=print: prefs)
        path = tmp_path / "alerts_state.json"
        if sides is not None:
            path.write_text(json.dumps({"_prefs": sides}), encoding="utf-8")
        led = Ledger(day=at.date(), root=str(tmp_path / "events"))
        st = run._pipeline_b(_ctx(at, tmp_path, value, chg), [], led, dry_run=False, mode=mode)
        led.save()
        if st is not None:
            run.save_state(str(path), st)
        return json.loads(path.read_text(encoding="utf-8"))["_prefs"]
    one.sent = sent
    return one


def test_two_conditions_same_target_do_not_block_each_other(env):
    """「위로 100」이 울린 날 「위로 105」도 넘으면 울린다(쿨다운 = 조건마다). 화면 「울림」은 실제로 나간 것만."""
    prefs = {"alerts": [_u("c1", value=100), _u("c2", value=105)], "settings": {}}
    env(prefs, _at("2026-10-02", "09:30"), value=99, sides={})
    env(prefs, _at("2026-10-02", "10:00"), value=101)
    rec = env(prefs, _at("2026-10-02", "11:00"), value=106)
    assert env.sent == ["c1", "c2"]
    assert rec["c2"]["ts"] == int(_at("2026-10-02", "11:00").timestamp())


def test_once_rearmed_same_day_rings_again(env):
    """「한 번」을 울린 날 다시 켜고 다시 넘으면 — 새 원장 키, 그 전 울림은 쿨다운에서 빠진다."""
    prefs = {"alerts": [_u("c1", value=100, repeat="once")], "settings": {}}
    env(prefs, _at("2026-10-02", "09:30"), value=99, sides={})
    env(prefs, _at("2026-10-02", "10:00"), value=101)
    assert env.sent == ["c1"]
    prefs = {"alerts": [_u("c1", value=100, repeat="once", armedAt="2026-10-02T01:30:00Z", armSide="d")], "settings": {}}
    rec = env(prefs, _at("2026-10-02", "11:00"), value=102)
    assert env.sent == ["c1", "c1"]
    assert rec["c1"]["fired"] is True and rec["c1"]["ts"] == int(_at("2026-10-02", "11:00").timestamp())
    env(prefs, _at("2026-10-02", "12:00"), value=99)
    env(prefs, _at("2026-10-05", "10:00"), value=103)
    assert env.sent == ["c1", "c1"]                                       # 다시 멈춤


def test_full_run_does_not_judge_user_conditions(env):
    prefs = {"alerts": [_u("c1", event="U2", value=1)], "settings": {}}
    env(prefs, _at("2026-10-02", "10:00"), value=1400, chg=3.0, mode="full", sides={})
    assert env.sent == [] and not any(r.get("cond") for r in Ledger.load_days(1, end=dt.date(2026, 10, 2)))
    env(prefs, _at("2026-10-02", "10:05"), value=1400, chg=3.0)
    assert env.sent == ["c1"]                                             # light 런은 판정한다


def test_once_u2_does_not_ring_again_after_ledger_window(env, monkeypatch):
    """「한 번」 U2 는 실제로 나가면 공개 기록에 fired — 원장 8일 창 밖(10일 뒤)에서도 멈춘 채."""
    prefs = {"alerts": [_u("c1", event="U2", value=2, repeat="once")], "settings": {}}
    env(prefs, _at("2026-10-02", "10:00"), value=1400, chg=3.0, sides={})
    rec = env(prefs, _at("2026-10-12", "10:00"), value=1400, chg=-4.0)
    assert env.sent == ["c1"] and rec["c1"]["fired"] is True

    send = deliver.send                                                    # 모든 채널이 실패하면 기록하지 않는다
    monkeypatch.setattr(deliver, "send", lambda s, ledger, ctx, log=print: send(s, ledger, ctx, ok=False))
    rec = env(prefs, _at("2026-10-20", "10:00"), value=1400, chg=3.0, sides={})
    assert env.sent == ["c1", "c1"] and rec == {}


def test_prune_deleted_conditions_only_when_prefs_read(env):
    keep = {"gone": {"ts": 1, "fired": True}, "c1": {"side": "u"}}
    assert env(None, _at("2026-10-02", "10:00"), value=99, sides=dict(keep)) == keep   # /prefs 읽기 실패 — 그대로
    rec = env({"alerts": [_u("c1", value=100, enabled=False)], "settings": {}}, _at("2026-10-02", "10:00"), value=99)
    assert rec == {"c1": {"side": "u"}}                                   # 지운 조건만 정리(꺼 둔 조건은 남김)


def test_state_written_only_after_ledger_saved(monkeypatch, tmp_path):
    """발송 단계에서 예외가 나면 원장도 공개 기록도 그대로 — 다음 런이 같은 교차를 다시 본다."""
    _base(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "extract", lambda *a, **k: [])
    monkeypatch.setattr(subscribe, "load_prefs", lambda log=print: {"alerts": [_u("c1", value=100)], "settings": {}})
    at = _at("2026-10-02", "10:00")
    monkeypatch.setattr(run.Context, "load", lambda now=None: _ctx(at, tmp_path, value=101))
    path = tmp_path / "alerts_state.json"
    raw = json.dumps({"_prefs": {"c1": {"side": "d"}}})
    path.write_text(raw, encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("발송 실패")
    monkeypatch.setattr(deliver, "send", boom)
    with pytest.raises(RuntimeError):
        run.main(["--mode", "light", "--now", at.isoformat()])
    assert path.read_text(encoding="utf-8") == raw

    monkeypatch.setattr(deliver, "send", lambda s, ledger, ctx, log=print: ledger.update_sent(s.row["key"], push=1))
    run.main(["--mode", "light", "--now", at.isoformat()])
    rec = json.loads(path.read_text(encoding="utf-8"))["_prefs"]["c1"]
    assert rec["side"] == "u" and rec["ts"] == int(at.timestamp())
