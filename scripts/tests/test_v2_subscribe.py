"""구독 — 꾸러미 3 × 기본 켜짐 · 관심 · 갈래 · 사용자 조건(HMAC 키 · 한 번 멈춤) · v1 변환."""
import datetime as dt
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import compose, schema, subscribe  # noqa: E402
from alerts_v2.ledger import KST  # noqa: E402

EV = schema.by_id(schema.load_events())


def _row(event="A1", target="kospi", level="alert", dir_="up"):
    return {"key": f"{event}:{target}:{dir_}:2026-10-02", "event": event, "target": target, "dir": dir_, "level": level,
            "value": 1, "unit": "", "asOf": "2026-10-02", "fresh": "live", "title": "t", "why": "", "next": "", "url": "#/",
            "ts": "2026-10-02T10:00:00+09:00", "sent": {}}


def _ctx(values=None, chg=None):
    values = values or {}
    chg = chg or {}
    return SimpleNamespace(
        now=dt.datetime(2026, 10, 2, 10, 0, tzinfo=KST), registry={},
        rid=lambda t: t, value=lambda t: values.get(t), change_pct=lambda t: chg.get(t),
        as_of=lambda t: "2026-10-02", fresh=lambda t: "live", scale=lambda t: None)


def test_default_on_watch_and_family_rules():
    rows = [_row("A1", "kospi"), _row("A1", "nasdaq"), _row("A3", "gold"), _row("B2", "kospi", level="notice"),
            _row("H2", "cpi_kr", level="record")]
    prefs = {"watch": [{"id": "gold"}], "settings": {"package": "normal", "families": {"B": False}}}
    d = {x.row["target"] + x.row["event"]: x for x in subscribe.match(rows, _ctx(), prefs, EV)}
    assert d["kospiA1"].ring and d["kospiA1"].reason == "기본 켜짐"
    assert not d["nasdaqA1"].ring and d["nasdaqA1"].reason == "관심 아님"
    assert d["goldA3"].ring and d["goldA3"].reason == "관심"
    assert not d["kospiB2"].ring and d["kospiB2"].reason == "갈래 꺼짐"
    assert not d["cpi_krH2"].ring and d["cpi_krH2"].level == "record"


def test_packages_quiet_and_many():
    rows = [_row("A1", "kospi"), _row("A5", "kospi", level="alarm"), _row("B2", "kospi", level="notice")]
    quiet = subscribe.match(rows, _ctx(), {"settings": {"package": "quiet"}}, EV)
    assert [x.ring for x in quiet] == [False, True, False]
    many = subscribe.match(rows, _ctx(), {"settings": {"package": "many"}}, EV)
    assert [x.ring for x in many] == [True, True, True] and many[2].level == "alert"


def test_user_override_level_and_off():
    rows = [_row("A1", "kospi")]
    prefs = {"alerts": [{"id": "x1", "event": "A1", "target": "kospi", "level": "alarm"}]}
    assert subscribe.match(rows, _ctx(), prefs, EV)[0].level == "alarm"
    prefs = {"alerts": [{"id": "x1", "event": "A1", "target": "kospi", "enabled": False}]}
    assert subscribe.match(rows, _ctx(), prefs, EV)[0].ring is False


def test_user_hits_need_salt_and_hmac_key(monkeypatch):
    prefs = {"alerts": [{"id": "c1", "event": "U1", "target": "usdkrw", "dir": "up", "value": 1400, "repeat": "each", "enabled": True},
                        {"id": "c2", "event": "U2", "target": "kospi", "value": 3, "repeat": "each", "enabled": True}]}
    ctx = _ctx(values={"usdkrw": 1401.2, "kospi": 7003}, chg={"kospi": -3.4})
    monkeypatch.delenv("ALERTS_STATE_SALT", raising=False)
    assert subscribe.user_hits(ctx, prefs, [], render=lambda ev, h: compose.render(ev, h, ctx)) == []
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    rows = subscribe.user_hits(ctx, prefs, [], render=lambda ev, h: compose.render(ev, h, ctx),
                               sides={"c1": {"side": "d"}})                   # 직전 런엔 1400 아래 — 이번에 넘음
    assert [r["event"] for r in rows] == ["U1", "U2"]
    assert rows[0]["key"].startswith("U1:usdkrw:up:") and len(rows[0]["key"].split(":")[-1]) == 12
    assert "1400" not in rows[0]["key"] and rows[0]["cond"] == "c1"
    assert rows[0]["title"] == "usdkrw 1,401 · 내 조건 위로" and rows[1]["dir"] == "down"
    assert "1400" not in rows[0]["title"] and "threshold" not in rows[0]       # 임계값은 공개 원장에 없음(G5)


def test_once_condition_stops_after_fired(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    prefs = {"alerts": [{"id": "c1", "event": "U1", "target": "usdkrw", "dir": "up", "value": 1400, "repeat": "once",
                         "enabled": True, "armedAt": "2026-10-01T00:00:00+09:00", "armSide": "d"}]}
    ctx = _ctx(values={"usdkrw": 1401.2})
    hist = [{"cond": "c1", "ts": "2026-10-01T09:00:00+09:00"}]
    assert subscribe.user_hits(ctx, prefs, hist, sides={"c1": {"side": "d"}}) == []
    hist = [{"cond": "c1", "ts": "2026-09-30T09:00:00+09:00"}]      # 다시 켜기 전 발동은 무시
    assert len(subscribe.user_hits(ctx, prefs, hist, sides={"c1": {"side": "d"}})) == 1


def test_upgrade_prefs_v1_to_v2():
    v1 = {"v": 1, "alerts": [
        {"id": "p1", "target": "usdkrw", "type": "price", "cond": {"op": "<=", "value": 1300}, "repeat": "once", "channels": ["push"], "enabled": True},
        {"id": "p2", "target": "kospi", "type": "pct", "cond": {"op": "<=", "value": -3}, "repeat": "daily", "channels": ["discord"], "enabled": True},
        {"id": "p3", "target": "kospi", "type": "flow", "cond": {"who": "foreign"}, "repeat": "daily", "channels": ["push"], "enabled": True},
        {"id": "p4", "target": "005930", "type": "flow", "cond": {"who": "foreign"}, "repeat": "daily", "channels": ["push"], "enabled": True},
        {"id": "p5", "target": "us10y", "type": "lens", "cond": {"state": "crossed"}, "repeat": "once", "channels": ["push"], "enabled": True}],
        "settings": {"quiet": None, "package": "weird"}}
    v2 = subscribe.upgrade_prefs(v1)
    byid = {a["id"]: a for a in v2["alerts"]}
    assert byid["p1"]["event"] == "U1" and byid["p1"]["dir"] == "down" and byid["p1"]["value"] == 1300 and byid["p1"]["repeat"] == "once"
    assert byid["p2"]["event"] == "U2" and byid["p2"]["value"] == 3 and byid["p2"]["dir"] == "down" and byid["p2"]["repeat"] == "each"
    assert byid["p3"]["event"] == "D2" and byid["p4"]["event"] == "D5" and byid["p5"]["event"] == "C1"
    assert v2["settings"]["package"] == "normal" and v2["settings"]["dailyCap"] == 6 and v2["v"] == 2


def test_strength_filters_swing_rows_by_user_sigma():
    """사전은 2σ 로 넓게 잡고, 울림은 사용자 세기(기본 big 2.5σ)로 거른다 — σ = |등락| / z."""
    row = dict(_row("A1", "kospi"), chg=2.2, z=2.2)          # σ 1.0% → 2.2σ
    base = subscribe.match([row], _ctx(), {"settings": {"package": "normal"}}, EV)[0]
    assert base.level == "record" and base.reason == "세기 미달"              # 기본 big 2.5σ 미달
    normal = subscribe.match([row], _ctx(), {"alerts": [{"id": "s", "event": "A1", "target": "kospi", "strength": "normal"}]}, EV)[0]
    assert normal.ring and normal.level == "alert"
    val = subscribe.match([row], _ctx(), {"alerts": [{"id": "s", "event": "A1", "target": "kospi", "strength": "value", "value": 2.0}]}, EV)[0]
    assert val.ring
    big_row = dict(_row("A1", "kospi"), chg=3.0, z=3.0)
    assert subscribe.match([big_row], _ctx(), None, EV)[0].ring                  # 3σ 는 기본으로 울림
    clamp_row = dict(_row("A1", "kospi"), chg=0.6, z=3.0)   # σ 0.2% → 2.5σ = 0.5% 하한 적용 → 0.6 ≥ 0.5 울림
    assert subscribe.match([clamp_row], _ctx(), None, EV)[0].ring


def test_load_prefs_hits_worker_prefs_path_once(monkeypatch):
    """PREFS_URL 은 바탕 주소다 — /prefs 까지 적으면 fetch 가 /prefs/prefs 로 가서 Worker 상태 JSON 을 받고
    설정이 통째로 무시된다(2026-10-06 첫 라이브 런 「조건 문서 모양이 다름」)."""
    import prefs_client
    seen = []

    def fake(base):
        seen.append(base)
        return {"alerts": [], "settings": {}, "updatedAt": "2026-10-06T00:00:00Z"}

    monkeypatch.setattr(prefs_client, "fetch", fake)
    monkeypatch.setenv("PUSH_READ_KEY", "k")
    doc = subscribe.load_prefs(log=lambda *a, **k: None)
    assert seen == ["https://ecom-dashboard-proxy.e-hcg.workers.dev"]
    assert not subscribe.PREFS_URL.endswith("/prefs")
    assert doc["v"] == 2


def test_load_prefs_reads_with_push_read_key_alone(monkeypatch):
    """B6 — 워크플로는 PUSH_READ_KEY 만 넘긴다(GitHub 시크릿 ALERTS_SYNC_KEY 는 2026-10-09 삭제). 그것만으로 /prefs 를 읽어야 하고,
    없으면 부르지 않고 기본 설정으로 간다."""
    import prefs_client
    used, logs = [], []

    def fake(base):
        used.append(prefs_client.auth_header()[0])
        return {"alerts": [], "settings": {}, "updatedAt": "2026-10-07T00:00:00Z"}

    monkeypatch.setattr(prefs_client, "fetch", fake)
    monkeypatch.setenv("PUSH_READ_KEY", "rk")
    assert subscribe.load_prefs(log=logs.append)["v"] == 2
    monkeypatch.delenv("PUSH_READ_KEY")
    assert subscribe.load_prefs(log=logs.append) is None
    assert used == ["X-Push-Read-Key"]
    assert len(logs) == 1 and "PUSH_READ_KEY" in logs[0]


def test_user_conditions_are_not_missing_judges():
    """U1 · U2 는 사전 family 가 A 라 family 로 거르면 매분 「판정 함수 미구현」 경고가 났다(2026-10-06 라이브) — judge 이름으로 거른다."""
    from alerts_v2 import run, judges_market, judges_flow_cal  # noqa: F401 — 판정 등록
    todo = schema.for_run(schema.load_events(), "light")
    assert {ev["id"] for ev in todo} >= {"U1", "U2"}
    assert run.missing_judges(todo) == []

