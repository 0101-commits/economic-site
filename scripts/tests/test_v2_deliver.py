"""발송 — 세 채널 독립 · 보류는 디스코드만 · 카톡 친구 모드 없으면 멈춤 · 푸시 큐 모양."""
import datetime as dt
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import deliver  # noqa: E402
from alerts_v2.ledger import KST, Ledger  # noqa: E402
from alerts_v2.model import Send  # noqa: E402


def _row(key="A1:kospi:up:2026-10-02", level="alert"):
    return {"key": key, "event": "A1", "target": "kospi", "dir": "up", "level": level, "value": "7,004", "unit": "",
            "asOf": "2026-10-02", "fresh": "live", "title": "코스피 +2.6% · 7,004", "why": "나스닥 동반", "next": "다음 마디 8,000",
            "url": "#/i/kospi", "ts": "2026-10-02T10:00:00+09:00",
            "sent": {"push": 0, "kakao": False, "discord": False, "bundled": False, "held": False}}


class _Discord:
    def __init__(self):
        self.calls = []
    def send_level(self, level, title, body, **kw):
        self.calls.append((level, title, body, kw))
        return True


def _ctx():
    return SimpleNamespace(now=dt.datetime(2026, 10, 2, 10, 0, tzinfo=KST))


def test_three_channels_independent(tmp_path, monkeypatch):
    fake = _Discord()
    monkeypatch.setitem(sys.modules, "notify_discord", fake)
    monkeypatch.setattr(deliver, "send_kakao", lambda s, ctx, log=print: False)      # 카톡 실패해도
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path)); led.append(_row())
    q = str(tmp_path / "push_queue.json")
    res = deliver.send(Send(row=_row(), level="alert", push=True, kakao=True, discord=True), led, _ctx(), log=lambda *a: None, queue_path=q)
    assert res == {"push": 1, "kakao": False, "discord": True}
    assert led.get("A1:kospi:up:2026-10-02")["sent"]["push"] == 1 and led.get("A1:kospi:up:2026-10-02")["sent"]["discord"]
    item = json.load(open(q, encoding="utf-8"))[0]
    assert item["id"] == "A1:kospi:up:2026-10-02" and item["title"] == "코스피 +2.6% · 7,004"
    assert item["body"] == "나스닥 동반\n다음 마디 8,000" and item["url"].endswith("#/i/kospi") and item["requireInteraction"] is False
    assert fake.calls[0][0] == "alert" and fake.calls[0][1] == "코스피 +2.6% · 7,004"


def test_held_goes_to_discord_only(tmp_path, monkeypatch):
    fake = _Discord()
    monkeypatch.setitem(sys.modules, "notify_discord", fake)
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path)); led.append(_row())
    q = str(tmp_path / "push_queue.json")
    res = deliver.send(Send(row=_row(), level="alert", push=True, kakao=True, discord=True, held=True), led, _ctx(), log=lambda *a: None, queue_path=q)
    assert res["push"] == 0 and res["kakao"] is False and res["discord"] is True
    assert not os.path.exists(q)
    assert deliver.held_rows(led)[0]["key"] == "A1:kospi:up:2026-10-02"


def test_kakao_stops_without_friends(monkeypatch):
    deliver._KAKAO_SESSION = None
    monkeypatch.setenv("KAKAO_REST_API_KEY", "k"); monkeypatch.setenv("KAKAO_REFRESH_TOKEN", "r")
    ops = []
    fake_kakao = SimpleNamespace(refresh_access_token=lambda a, b: "tok", get_friends=lambda t: [], _friends_enabled=lambda: True,
                                 send_card=lambda *a, **k: (_ for _ in ()).throw(AssertionError("보내면 안 됨")))
    monkeypatch.setitem(sys.modules, "send_kakao_digest", fake_kakao)
    monkeypatch.setattr(deliver, "_ops", lambda text, log=print: ops.append(text))
    assert deliver.send_kakao(Send(row=_row(), level="alert", kakao=True), _ctx(), log=lambda *a: None) is False
    assert ops and "친구 모드" in ops[0]
    deliver._KAKAO_SESSION = None


def test_kakao_parts_buttons_8chars_and_items():
    s = Send(row=_row(), level="alarm", kakao=True)
    p = deliver.kakao_parts(s)
    assert len(p["buttons"]) == 2 and all(len(b[0]) <= 8 for b in p["buttons"])
    assert p["items"][0] == {"item": "값", "item_op": "7,004"} and p["caption"] == "나스닥 동반\n다음 마디 8,000"
    assert p["kind"] == "알림 v2 경보"


def test_bundle_marks_members(tmp_path, monkeypatch):
    fake = _Discord()
    monkeypatch.setitem(sys.modules, "notify_discord", fake)
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    members = [_row(f"A1:x{i}:up:2026-10-02") for i in range(3)]
    for m in members:
        led.append(m)
    brow = dict(_row("BUNDLE:2026-10-02:1400"), event="BUNDLE", title="알림 3건 더 · 코스피")
    q = str(tmp_path / "push_queue.json")
    deliver.send(Send(row=brow, level="alert", push=True, discord=True, bundled=True, bundle=members, kind="bundle"), led, _ctx(), log=lambda *a: None, queue_path=q)
    assert all(led.get(m["key"])["sent"]["bundled"] and led.get(m["key"])["sent"]["push"] == 1 for m in members)
    assert led.get("BUNDLE:2026-10-02:1400") is not None
    assert "· 코스피" in fake.calls[0][2]
