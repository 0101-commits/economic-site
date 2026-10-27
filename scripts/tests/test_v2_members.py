"""멤버 알림(Task 13) — 사람마다 판정, 공개 기록 키는 HMAC, 멤버 사용자 조건은 공개 원장 밖(/fired).

- 마스터 공개 기록 키는 조건 id 그대로, 멤버는 HMAC(uid:조건 id) — 원문 id · 임계는 공개 파일에 없다.
- 멤버 사용자 조건(U1 · U2 · 종목 B1)은 원장에 안 넣고 Worker /fired 로만 남긴다. 시장 사건은 원장 한 줄(uid 없음).
- 카톡은 마스터만. 푸시 큐 항목엔 uid. 정리(_prefs 가지치기)는 모든 사람 키의 합집합 밖만, 사람별 설정을 못 읽으면 안 한다.
원장 · 공개 기록 · 푸시 큐는 임시 폴더, Worker · 카톡 · 푸시는 전부 가짜(네트워크 없음).
"""
import datetime as dt
import json
import os
import sys
import urllib.error
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import deliver, run, subscribe  # noqa: E402
from alerts_v2 import ledger as ledger_mod  # noqa: E402
from alerts_v2.ledger import KST, Ledger  # noqa: E402
from alerts_v2.model import Send  # noqa: E402

OWNER, MEMBER, MEMBER2 = "own1", "mem1", "mem2"
SAVED = "2026-10-01T00:00:00Z"


def _at(day, hm):
    return dt.datetime.fromisoformat(f"{day}T{hm}:00").replace(tzinfo=KST)


def _ctx(at, root, value=None, chg=None):
    return SimpleNamespace(now=at, registry={}, rid=lambda t: t, value=lambda t: value, change_pct=lambda t: chg,
                           as_of=lambda t: at.date().isoformat(), fresh=lambda t: "live", scale=lambda t: None,
                           stock=lambda t: None, root=str(root))


def _u(cid, event="U1", **kw):
    return dict({"id": cid, "event": event, "target": "usdkrw", "dir": "up", "repeat": "each", "enabled": True}, **kw)


def _prefs(*alerts, **settings):
    return {"updatedAt": SAVED, "alerts": list(alerts), "settings": dict(settings)}


def _mk(uid, cid):
    return subscribe.state_key(uid, "member", cid)


def _mrow(at, key="A1:kospi:up:2026-10-02", level="alert"):
    return {"key": key, "event": key.split(":")[0], "target": "kospi", "dir": key.split(":")[2], "level": level, "value": 1,
            "unit": "", "asOf": at.date().isoformat(), "fresh": "live", "title": "코스피 급등", "why": "", "next": "",
            "url": "#/i/kospi", "ts": at.isoformat(timespec="seconds")}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    monkeypatch.setenv("ALERTS_V2", "1")
    monkeypatch.delenv("PUSH_WRITE_KEY", raising=False)
    monkeypatch.setattr(ledger_mod, "EVENTS_DIR", str(tmp_path / "events"))   # 진짜 events/ 를 읽지도 쓰지도 않는다
    monkeypatch.setattr(run, "_render", lambda ctx: None)
    rec = SimpleNamespace(owner=[], pushes=[], fired=[], decisions=[])

    def send(s, ledger, ctx, log=print):                  # 마스터 경로(푸시 + 카톡) — 가짜, 원장 sent 만 갱신
        rec.owner.append((s.uid, s.row.get("cond"), s.row["key"]))
        ledger.update_sent(s.row["key"], push=1)
        return {"push": 1, "kakao": False, "memo": False}
    monkeypatch.setattr(deliver, "send", send)
    monkeypatch.setattr(deliver, "enqueue_push", lambda items, path=None: rec.pushes.extend(items) or True)
    monkeypatch.setattr(deliver, "post_fired", lambda uid, item, log=print: rec.fired.append((uid, item)) or True)
    match = subscribe.match

    def spy(*a, **k):
        out = match(*a, **k)
        rec.decisions.extend(out)
        return out
    monkeypatch.setattr(subscribe, "match", spy)

    def one(people, at, value=None, chg=None, mode="light", sides=None, rows=(), owner_prefs=None, dry_run=False):
        """한 런: 공개 기록을 읽고 판정 · 발송 · 원장 저장 → 공개 기록(바뀐 것, 없으면 읽은 그대로)."""
        monkeypatch.setattr(subscribe, "load_all_prefs", lambda log=print: people)
        monkeypatch.setattr(subscribe, "load_prefs", lambda log=print: owner_prefs)
        path = tmp_path / "alerts_state.json"
        if sides is not None:
            path.write_text(json.dumps({"_prefs": sides}), encoding="utf-8")
        led = Ledger(day=at.date(), root=str(tmp_path / "events"))
        for r in rows:                                      # 추출이 원장에 넣고 새 행으로 돌려준 것처럼
            led.append(dict(r))
        st = run._pipeline_b(_ctx(at, tmp_path, value, chg), [dict(r) for r in rows], led, dry_run=dry_run, mode=mode)
        led.save()
        if st is not None:
            run.save_state(str(path), st)
        one.ledger = led
        return json.loads(path.read_text(encoding="utf-8"))["_prefs"] if path.exists() else {}
    one.rec = rec
    one.root = str(tmp_path / "events")
    return one


def test_state_key_owner_plain_member_hmac(monkeypatch):
    monkeypatch.setenv("ALERTS_STATE_SALT", "salt-for-test")
    assert subscribe.state_key(OWNER, "owner", "c1") == "c1"                 # 마스터 키는 지금 그대로(바뀌지 않음)
    k = subscribe.state_key(MEMBER, "member", "c1")
    assert k == subscribe.hmac_key(MEMBER + ":c1") and len(k) == 12 and k != "c1"
    assert subscribe.state_key(MEMBER2, "member", "c1") != k                # 같은 조건 id 라도 사람마다 다른 키
    monkeypatch.delenv("ALERTS_STATE_SALT")
    assert subscribe.state_key(OWNER, "owner", "c1") == "c1"
    assert subscribe.state_key(MEMBER, "member", "c1") is None              # 소금 없으면 멤버 키를 만들지 않는다


def test_member_u1_cross_goes_to_fired_not_public_ledger(env):
    people = [(OWNER, "owner", _prefs(_u("c1", value=100))), (MEMBER, "member", _prefs(_u("m1", value=105)))]
    env(people, _at("2026-10-02", "09:30"), value=99, sides={})               # 첫 관측 — 쪽만
    at = _at("2026-10-02", "10:00")
    sides = env(people, at, value=106)                                          # 둘 다 넘음
    rec = env.rec
    mine = [d for d in rec.decisions if d.cond_id == "m1"]
    assert len(mine) == 1 and mine[0].uid == MEMBER and mine[0].role == "member"
    assert [(d.uid, d.role) for d in rec.decisions if d.cond_id == "c1"] == [(OWNER, "owner")]
    on_disk = Ledger.load_days(1, end=at.date(), root=env.root)
    assert [r.get("cond") for r in on_disk] == ["c1"]                         # 공개 원장엔 마스터 행만
    assert "m1" not in json.dumps(on_disk, ensure_ascii=False)
    assert len(rec.fired) == 1 and rec.fired[0][0] == MEMBER                  # /fired 한 번
    item = rec.fired[0][1]
    assert item["event"] == "U1" and item["cond"] == "m1" and item["title"] and item["ts"]
    assert [p.get("uid") for p in rec.pushes] == [MEMBER]                     # 멤버 푸시 항목엔 uid
    assert [(u, c) for u, c, _k in rec.owner] == [(OWNER, "c1")]              # 카톡 경로(deliver.send)는 마스터만
    mk = _mk(MEMBER, "m1")
    assert set(sides) == {"c1", mk, _mk(MEMBER, "@day")}
    assert sides["c1"]["side"] == "u" and sides["c1"]["ts"] == int(at.timestamp())
    assert set(sides[mk]) == {"side", "ts", "fd", "keys"} and sides[mk]["side"] == "u" and sides[mk]["fd"] == "u"
    assert sides[mk]["ts"] == int(at.timestamp()) and len(sides[mk]["keys"]) == 1
    assert sides[_mk(MEMBER, "@day")] == {"d": "2026-10-02", "n": 1}
    assert "m1" not in json.dumps(sides) and MEMBER not in json.dumps(sides)   # 멤버 원문 id · uid 는 공개 기록에 없다
    env(people, _at("2026-10-02", "10:05"), value=107)                        # 위에 머무는 동안 조용
    assert len(rec.fired) == 1 and len(rec.pushes) == 1


def test_prune_keeps_union_and_drops_only_deleted_member_condition(env):
    m1, m2, x1 = _mk(MEMBER, "m1"), _mk(MEMBER, "m2"), _mk(MEMBER2, "x1")
    sides = {"c1": {"side": "u"}, "gone": {"ts": 1, "fired": True}, m1: {"side": "d"}, m2: {"side": "d"},
             x1: {"side": "d"}}
    people = [(OWNER, "owner", _prefs(_u("c1", value=100, enabled=False))),   # 꺼 둔 마스터 조건은 남긴다
              (MEMBER, "member", _prefs(_u("m1", value=200))),                 # m2 를 지움
              (MEMBER2, "member", _prefs(_u("x1", value=200)))]
    out = env(people, _at("2026-10-02", "10:00"), value=99, sides=sides)
    assert set(out) == {"c1", m1, x1}                                         # 지운 것만(마스터 gone · 멤버 m2)
    assert out["c1"] == {"side": "u"}


def test_people_unreadable_falls_back_to_owner_without_pruning(env):
    m1 = _mk(MEMBER, "m1")
    sides = {"c1": {"side": "d"}, "gone": {"ts": 1}, m1: {"side": "d"}}
    owner = {"alerts": [_u("c1", value=100)], "settings": {}}
    out = env(None, _at("2026-10-02", "10:00"), value=101, sides=sides, owner_prefs=owner)
    assert out["gone"] == {"ts": 1} and out[m1] == {"side": "d"}              # 정리 없음
    assert out["c1"]["side"] == "u"
    assert [(u, c) for u, c, _k in env.rec.owner] == [(None, "c1")]           # 마스터만(uid 모름 = 옛 큐 = 마스터에게만)
    assert env.rec.fired == [] and {d.role for d in env.rec.decisions} == {"owner"}


def test_no_owner_or_unsaved_owner_or_no_salt_skips_pruning(env, monkeypatch):
    m1 = _mk(MEMBER, "m1")
    base = {"c1": {"side": "d"}, "gone": {"ts": 1}, m1: {"side": "d"}}
    member = (MEMBER, "member", _prefs(_u("m1", value=200)))
    owner = {"alerts": [_u("c1", value=200)], "settings": {}}
    out = env([member], _at("2026-10-02", "10:00"), value=99, sides=dict(base), owner_prefs=owner)   # 마스터 없음
    assert "gone" in out and env.rec.fired == [] and not env.rec.pushes
    unsaved = (OWNER, "owner", {"updatedAt": None, "alerts": [], "settings": {}})                     # 저장 전 빈 문서
    out = env([unsaved, member], _at("2026-10-02", "10:05"), value=99, sides=dict(base))
    assert "gone" in out and "c1" in out and m1 in out
    monkeypatch.delenv("ALERTS_STATE_SALT")                                    # 소금 없음 + 멤버 있음
    out = env([(OWNER, "owner", _prefs(_u("c1", value=200))), member], _at("2026-10-02", "10:10"), value=99,
              sides=dict(base))
    assert out == base


def test_member_u2_once_per_occurrence_and_cooldown(env):
    people = [(OWNER, "owner", _prefs()), (MEMBER, "member", _prefs(_u("m1", event="U2", value=2)))]
    env(people, _at("2026-10-02", "10:00"), value=1400, chg=3.0, sides={})
    env(people, _at("2026-10-02", "10:05"), value=1400, chg=3.5)              # 같은 발생 — 원장 키 대신 공개 기록 keys
    assert len(env.rec.fired) == 1
    env(people, _at("2026-10-02", "11:00"), value=1400, chg=-3.0)             # 반대 방향 — 쿨다운은 방향마다
    assert len(env.rec.fired) == 2
    env(people, _at("2026-10-03", "09:00"), value=1400, chg=-3.0)             # 새 기준일이지만 하루 쿨다운 안
    assert len(env.rec.fired) == 2
    sides = env(people, _at("2026-10-03", "11:30"), value=1400, chg=-3.0)
    assert len(env.rec.fired) == 3
    assert len(sides[_mk(MEMBER, "m1")]["keys"]) == 3 and sides[_mk(MEMBER, "m1")]["fd"] == "d"
    assert not any(r.get("cond") for r in Ledger.load_days(2, end=dt.date(2026, 10, 3), root=env.root))


def test_member_market_event_by_own_prefs_push_only(env):
    at = _at("2026-10-02", "10:00")
    row = _mrow(at)
    people = [(OWNER, "owner", _prefs()), (MEMBER, "member", _prefs()),
              (MEMBER2, "member", _prefs(families={"A": False}))]               # mem2 는 A 갈래를 껐다
    env(people, at, rows=[row], sides={})
    assert [p.get("uid") for p in env.rec.pushes] == [MEMBER]                 # 마스터 푸시는 deliver.send(가짜) 경로
    assert env.rec.fired == []                                                # 시장 사건은 /fired 에 안 쓴다
    assert [(u, k) for u, _c, k in env.rec.owner] == [(OWNER, row["key"])]
    on_disk = Ledger.load_days(1, end=at.date(), root=env.root)
    assert [r["key"] for r in on_disk] == [row["key"]] and "uid" not in on_disk[0]   # 원장 한 줄, uid 없음
    assert on_disk[0]["sent"]["push"] == 1                                    # 마스터 발송만 적힘
    assert {(d.uid, d.ring) for d in env.rec.decisions} == {(OWNER, True), (MEMBER, True), (MEMBER2, False)}


def test_member_market_cooldown_counts_rows_sent_or_not(env):
    """멤버 쿨다운 = 공개 원장에 같은 묶음 키 행이 있으면(마스터에게 나갔든 안 나갔든) 막는다."""
    day1, day2 = _at("2026-10-02", "10:00"), _at("2026-10-03", "09:00")
    people = [(OWNER, "owner", _prefs(families={"A": False})), (MEMBER, "member", _prefs())]
    env(people, day1, rows=[_mrow(day1)], sides={})
    assert [p.get("uid") for p in env.rec.pushes] == [MEMBER] and env.rec.owner == []
    env(people, day2, rows=[_mrow(day2, key="A1:kospi:up:2026-10-03")])          # 하루 쿨다운 안 — 마스터는 안 받았어도
    assert [p.get("uid") for p in env.rec.pushes] == [MEMBER]


def test_member_daily_cap_counter_bundles_without_touching_ledger(env):
    at = _at("2026-10-02", "10:00")
    day = _mk(MEMBER, "@day")
    people = [(OWNER, "owner", _prefs(families={"A": False})), (MEMBER, "member", _prefs())]
    sides = env(people, at, rows=[_mrow(at)], sides={day: {"d": "2026-10-02", "n": 6}})   # 기본 상한 6 — 꽉 참
    assert len(env.rec.pushes) == 1 and env.rec.pushes[0]["title"].startswith("알림 1건 더")
    assert env.rec.pushes[0]["uid"] == MEMBER
    assert sides[day] == {"d": "2026-10-02", "n": 8}       # 마스터 원장 셈과 같게 — 묶음 행 1 + 묶인 알림 행 1
    assert env.ledger.get(_mrow(at)["key"])["sent"]["bundled"] is False      # 공개 원장은 멤버 편성이 안 건드린다
    assert not any(r["key"].startswith("BUNDLE") for r in env.ledger.rows)
    at2 = _at("2026-10-03", "10:00")
    sides = env(people, at2, rows=[_mrow(at2, key="A1:kospi:down:2026-10-03")])   # 날이 바뀌면 다시 0부터
    assert sides[day] == {"d": "2026-10-03", "n": 1}


def test_member_quiet_hours_held_records_fired_without_push(env):
    people = [(OWNER, "owner", _prefs()), (MEMBER, "member", _prefs(_u("m1", value=105)))]
    env(people, _at("2026-10-02", "23:20"), value=99, sides={})
    at = _at("2026-10-02", "23:30")
    sides = env(people, at, value=106)
    assert env.rec.pushes == []                                               # 조용한 시간 — 푸시 없음
    assert len(env.rec.fired) == 1 and env.rec.fired[0][1].get("held") is True
    assert sides[_mk(MEMBER, "m1")]["ts"] == int(at.timestamp())              # 보류도 나간 것(마스터와 같은 규칙)
    assert _mk(MEMBER, "@day") not in sides                                   # 울림 수엔 안 든다


def test_one_member_error_does_not_break_owner_or_others(env, monkeypatch, capsys):
    """마스터 발송이 끝난 뒤 멤버 판정이 터지면 원장이 저장되지 않아 다음 런이 마스터에게 또 보낸다 — 멤버 오류는 그 사람만."""
    people = [(OWNER, "owner", _prefs(_u("c1", value=100))), (MEMBER, "member", _prefs(_u("m1", value=105))),
              (MEMBER2, "member", _prefs(_u("x1", value=105)))]
    env(people, _at("2026-10-02", "09:30"), value=99, sides={})
    fresh = subscribe.member_fresh
    calls = []

    def flaky(rows, prefs, *a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return fresh(rows, prefs, *a, **k)
    monkeypatch.setattr(subscribe, "member_fresh", flaky)
    sides = env(people, _at("2026-10-02", "10:00"), value=106)
    assert [(u, c) for u, c, _k in env.rec.owner] == [(OWNER, "c1")] and sides["c1"]["ts"]
    assert [u for u, _i in env.rec.fired] == [MEMBER2]                         # 다른 멤버는 그대로
    out = capsys.readouterr().out
    assert "RuntimeError" in out and MEMBER not in out


def test_dry_run_member_sends_nothing(env):
    people = [(OWNER, "owner", _prefs()), (MEMBER, "member", _prefs(_u("m1", value=105)))]
    env(people, _at("2026-10-02", "09:30"), value=99, sides={})
    env(people, _at("2026-10-02", "10:00"), value=106, dry_run=True)
    assert env.rec.fired == [] and env.rec.pushes == []


def test_member_logs_have_no_uid_or_condition(env, capsys):
    people = [(OWNER, "owner", _prefs()), (MEMBER, "member", _prefs(_u("m1", value=105, target="005930")))]
    env(people, _at("2026-10-02", "09:30"), value=99, sides={})
    env(people, _at("2026-10-02", "10:00"), value=106)
    out = capsys.readouterr().out
    assert len(env.rec.fired) == 1
    assert MEMBER not in out and "005930" not in out and "m1" not in out


def test_member_stock_lookup_logs_no_code(monkeypatch, capsys):
    import check_alerts as ca
    from alerts_v2.context import Context
    monkeypatch.setattr(ca, "get_snapshot", lambda *a, **k: None)
    ctx = Context(now=dt.datetime(2026, 10, 7, 10, 0, tzinfo=KST), data={}, bundles={}, registry={}, mer={})
    ctx.redact_codes = True
    assert ctx._snap("123450") is None
    out = capsys.readouterr().out
    assert "123450" not in out and "종목 시세 없음" in out
    ctx.redact_codes = False
    ctx._snap("654320")
    assert "654320" in capsys.readouterr().out                                # 마스터 로그는 지금 그대로


def test_push_item_carries_uid():
    row = {"key": "A1:kospi:up:2026-10-02", "title": "t", "why": "", "url": "#/i/kospi", "ts": "x"}
    assert "uid" not in deliver.push_item(Send(row=row, level="alert", push=True))
    assert deliver.push_item(Send(row=row, level="alert", push=True, uid=OWNER))["uid"] == OWNER


def test_post_fired_header_body_and_failures(monkeypatch):
    import prefs_client
    logs, calls = [], []
    item = {"id": "U1:usdkrw:up:abc", "event": "U1", "title": "제목", "ts": "2026-10-02T10:00:00+09:00"}

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Opener:
        def open(self, req, timeout=None):
            calls.append(req)
            return Resp()
    monkeypatch.setattr(prefs_client, "_OPENER", Opener())
    monkeypatch.delenv("PUSH_WRITE_KEY", raising=False)
    assert deliver.post_fired(MEMBER, item, log=logs.append) is False and calls == []
    assert len(logs) == 1 and MEMBER not in logs[0]
    secret = "w" * 64
    monkeypatch.setenv("PUSH_WRITE_KEY", secret)
    assert deliver.post_fired(MEMBER, item, log=logs.append) is True
    req = calls[0]
    assert req.full_url.endswith("/fired") and req.get_method() == "POST"
    assert req.get_header("X-push-write-key") == secret
    assert json.loads(req.data.decode("utf-8")) == {"uid": MEMBER, "item": item}

    class Boom:
        def open(self, req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 403, "forbidden", {}, None)
    monkeypatch.setattr(prefs_client, "_OPENER", Boom())
    logs.clear()
    assert deliver.post_fired(MEMBER, item, log=logs.append) is False
    assert len(logs) == 1 and MEMBER not in logs[0] and secret not in logs[0]


def test_briefing_members_get_push_with_uid(monkeypatch, tmp_path):
    from alerts_v2 import briefing
    monkeypatch.setattr(briefing, "build", lambda *a, **k: {"title": "10/2(금) 아침", "lines": ["한 줄", "둘째", ""],
                                                             "items": [], "card_png": None, "caption": "한 줄",
                                                             "links": {}})
    monkeypatch.setattr(briefing.dc, "kr_closed", lambda *a, **k: False)
    monkeypatch.setattr(briefing, "_kakao", lambda *a, **k: False)
    ctx = SimpleNamespace(now=dt.datetime(2026, 10, 2, 7, 30, tzinfo=KST), data={})
    q = tmp_path / "q.json"
    led = Ledger(day=ctx.now.date(), root=str(tmp_path / "events"))
    off = {"briefings": {"morning": False}}
    members = [(MEMBER, None), (MEMBER2, {"briefings": {"morning": False}})]   # mem2 는 아침 브리핑을 껐다
    res = briefing.send("morning", ctx, led, off, log=lambda *a: None, queue_path=str(q), uid=OWNER, members=members)
    items = json.loads(q.read_text(encoding="utf-8"))
    assert res == {"push": 0, "kakao": False, "memo": False, "members": 1}
    assert [i.get("uid") for i in items] == [MEMBER] and items[0]["id"] == "brief:morning:2026-10-02"
    assert led.rows == []                                                     # 멤버만 받은 브리핑은 공개 원장에 안 적는다
    q.unlink()
    res = briefing.send("morning", ctx, led, None, log=lambda *a: None, queue_path=str(q), uid=OWNER,
                        members=[(MEMBER, None)])
    items = json.loads(q.read_text(encoding="utf-8"))
    assert [i.get("uid") for i in items] == [OWNER, MEMBER] and res["push"] == 1 and res["members"] == 1


def test_brief_marker_when_only_members_received(monkeypatch, tmp_path):
    import send_kakao_digest as kakao
    from alerts_v2 import briefing
    monkeypatch.setenv("ALERTS_V2", "1")
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ledger_mod, "EVENTS_DIR", str(tmp_path / "events"))
    now = dt.datetime(2026, 10, 2, 7, 30, tzinfo=KST)
    monkeypatch.setattr(run.Context, "load", lambda now=None: SimpleNamespace(now=now, data={}))
    monkeypatch.setattr(briefing, "roll_calendar", lambda *a, **k: None)
    monkeypatch.setattr(kakao, "apply_live_quotes", lambda d: None)
    monkeypatch.setattr(kakao, "load_mri", lambda d: None)
    monkeypatch.setattr(subscribe, "load_all_prefs", lambda log=print: [
        (OWNER, "owner", _prefs(briefings={"morning": False})), (MEMBER, "member", _prefs())])
    calls = []

    def fake_send(slot, ctx, ledger, settings=None, dry_run=False, log=print, queue_path=None, uid=None, members=None):
        calls.append((settings, uid, members))
        return {"push": 0, "kakao": False, "memo": False, "members": len(members or [])}
    monkeypatch.setattr(briefing, "send", fake_send)
    assert run._brief("morning", now, dry_run=False) == 0
    settings, uid, members = calls[0]
    assert uid == OWNER and settings["briefings"]["morning"] is False
    assert [m[0] for m in members] == [MEMBER]
    assert os.path.exists(tmp_path / run.BRIEF_SENT_MARKER)                  # 마스터 꺼짐 + 멤버가 받음 = 마커
