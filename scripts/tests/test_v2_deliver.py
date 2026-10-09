"""발송 — 세 채널 독립 · 보류는 디스코드만 · 카톡 친구 모드 없으면 메모로 디스코드를 따라감 · 푸시 큐 모양."""
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
    assert res == {"push": 1, "kakao": False, "discord": True, "memo": False}
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


def _fake_kakao(friends_on: bool, friends: list, sent: list, refresh=None, send_card=None, calls=None):
    calls = calls if calls is not None else []
    return SimpleNamespace(refresh_access_token=refresh or (lambda a, b: calls.append("refresh") or "tok"),
                           get_friends=lambda t: friends, _friends_enabled=lambda: friends_on,
                           send_card=send_card or (lambda tok, title, cap, **k: sent.append(k.get("uuids")) or True))


def _kakao_env(monkeypatch, fake):
    monkeypatch.setattr(deliver, "_KAKAO_SESSION", None)         # conftest 기본 「꺼짐」을 풀어 세션을 새로 만든다
    monkeypatch.setenv("KAKAO_REST_API_KEY", "k"); monkeypatch.setenv("KAKAO_REFRESH_TOKEN", "r")
    monkeypatch.setitem(sys.modules, "send_kakao_digest", fake)
    monkeypatch.setattr(deliver, "_card_png", lambda s, ctx: None)


def test_kakao_memo_when_friends_off_or_empty(monkeypatch):
    """친구 모드가 아니면(KAKAO_FRIENDS=0 · 친구 0명) 멈추지 않고 메모(uuids=None)로 보낸다(2026-10-07)."""
    for on, friends in ((False, [{"uuid": "u"}]), (True, [])):
        sent = []
        _kakao_env(monkeypatch, _fake_kakao(on, friends, sent))
        assert deliver.send_kakao(Send(row=_row(), level="alert", kakao=True), _ctx(), log=lambda *a: None) is True
        assert sent == [None] and deliver.memo_mode(lambda *a: None) is True


def test_memo_mode_mirrors_discord(tmp_path, monkeypatch):
    """메모 모드: 편성이 카톡을 안 골라도(안내 · 울림 아님) 디스코드로 가는 건 따라간다 — 원장엔 kakao 가 아니라 memo 로
    (하루 상한 · 카톡 쿼터가 kakao 만 센다). 디스코드가 먼저 나간다. 친구 모드는 편성대로."""
    for on, friends, want in ((False, [], [None]), (True, [{"uuid": "u"}], [])):
        order, sent = [], []
        dc = _Discord()
        dc.send_level = lambda level, title, body, **kw: order.append("discord") or True
        monkeypatch.setitem(sys.modules, "notify_discord", dc)
        card = lambda tok, title, cap, **k: order.append("kakao") or sent.append(k.get("uuids")) or True  # noqa: E731
        _kakao_env(monkeypatch, _fake_kakao(on, friends, sent, send_card=card))
        led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path / str(on))); led.append(_row(level="notice"))
        res = deliver.send(Send(row=_row(level="notice"), level="notice", discord=True), led, _ctx(), log=lambda *a: None,
                           queue_path=str(tmp_path / "q.json"))
        assert sent == want and res["memo"] is bool(want) and res["kakao"] is False and res["discord"] is True
        assert order == ["discord"] + ["kakao"] * len(want)
        got = led.get("A1:kospi:up:2026-10-02")["sent"]
        assert got["kakao"] is False and got.get("memo", False) is bool(want)


def test_held_stays_discord_only_in_memo_mode(tmp_path, monkeypatch):
    """조용한 시간 보류분은 메모로도 안 간다 — 아침 브리핑에 합류한다."""
    monkeypatch.setitem(sys.modules, "notify_discord", _Discord())
    sent = []
    _kakao_env(monkeypatch, _fake_kakao(False, [], sent))
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path)); led.append(_row())
    res = deliver.send(Send(row=_row(), level="alert", push=True, discord=True, held=True), led, _ctx(), log=lambda *a: None,
                       queue_path=str(tmp_path / "q.json"))
    assert sent == [] and res["discord"] is True and res["memo"] is False


def test_kakao_token_once_per_run_and_down_after_failure(tmp_path, monkeypatch):
    """토큰은 런당 한 번. 한 통이 실패(SystemExit 포함)하면 그 런의 나머지 카톡은 건너뛰고 디스코드는 계속 나간다
    — 카카오가 시간을 끌면 한 통에 수 분이라 잡 시한을 넘긴다."""
    dc = _Discord()
    monkeypatch.setitem(sys.modules, "notify_discord", dc)
    calls, sent = [], []

    def card(tok, title, cap, **k):
        sent.append(title)
        if len(sent) == 2:
            raise SystemExit("메모 발송 실패")
        return True
    _kakao_env(monkeypatch, _fake_kakao(False, [], sent, send_card=card, calls=calls))
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    out = []
    for i in range(3):
        r = _row(f"A1:k{i}:up:2026-10-02"); led.append(r)
        out.append(deliver.send(Send(row=r, level="alert", discord=True), led, _ctx(), log=lambda *a: None,
                                queue_path=str(tmp_path / "q.json")))
    assert calls == ["refresh"] and len(sent) == 2                      # 셋째 통은 카톡을 부르지 않는다
    assert [o["memo"] for o in out] == [True, False, False] and all(o["discord"] for o in out) and len(dc.calls) == 3


def test_kakao_token_death_does_not_kill_discord(tmp_path, monkeypatch):
    """refresh_access_token 은 토큰 사망을 SystemExit 로 던진다 — 카톡만 빠지고 디스코드는 나가야 한다."""
    fake_dc = _Discord()
    monkeypatch.setitem(sys.modules, "notify_discord", fake_dc)
    sent = []
    _kakao_env(monkeypatch, _fake_kakao(False, [], sent, refresh=lambda a, b: (_ for _ in ()).throw(SystemExit("KOE322"))))
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path)); led.append(_row())
    res = deliver.send(Send(row=_row(), level="alert", kakao=True, discord=True), led, _ctx(), log=lambda *a: None,
                       queue_path=str(tmp_path / "q.json"))
    assert res["kakao"] is False and res["memo"] is False and res["discord"] is True and sent == [] and fake_dc.calls


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


def test_card_bytes_upload_without_text_fallback(monkeypatch):
    """v2 카드는 PNG bytes — 업로드가 경로만 받던 때는 open(bytes) 가 「embedded null byte」로 죽어
    카톡이 전부 텍스트로 떨어지고 #시스템이 「카톡 카드 경고」로 울렸다(2026-10-08 실측)."""
    import requests
    import send_kakao_digest as k
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    sent = {}

    def post(url, headers=None, files=None, timeout=None):
        sent["file"] = files["file"]
        return SimpleNamespace(status_code=200, json=lambda: {"infos": {"original": {"url": "https://k.kakaocdn/x.png"}}})

    monkeypatch.setattr(requests, "post", post)
    assert k.kakao_upload_image("tok", png) == "https://k.kakaocdn/x.png"
    assert sent["file"][1] == png
    feeds, notices = [], []
    monkeypatch.setattr(k, "send_feed", lambda *a, **kw: feeds.append(a[3]) or True)
    monkeypatch.setattr(k, "_system_notice", notices.append)
    monkeypatch.setattr(k, "send_memo", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("텍스트 폴백")))
    assert k.send_card("tok", "코스피 +2.6% · 7,004", "나스닥 동반", png=png, kind="알림 v2 알림")
    assert feeds == ["https://k.kakaocdn/x.png"] and notices == []      # 사진으로 나가고 #시스템 경고 없음
