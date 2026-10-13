"""발송 — 두 채널(푸시 · 카톡) 독립 · 디스코드 없음(2026-10-13 폰 알림 경로 고정) · 메모 모드는 보류분까지 전부 메모 · 푸시 큐 모양."""
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


class _NoDiscord:
    """경제 알림은 디스코드로 안 간다 — 부르면 시험이 깨진다."""
    def __getattr__(self, name):
        raise AssertionError(f"디스코드 호출: {name}")


def _ctx():
    return SimpleNamespace(now=dt.datetime(2026, 10, 2, 10, 0, tzinfo=KST))


def test_two_channels_independent_no_discord(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "notify_discord", _NoDiscord())
    monkeypatch.setattr(deliver, "send_kakao", lambda s, ctx, log=print: False)      # 카톡 실패해도
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path)); led.append(_row())
    q = str(tmp_path / "push_queue.json")
    res = deliver.send(Send(row=_row(), level="alert", push=True, kakao=True), led, _ctx(), log=lambda *a: None, queue_path=q)
    assert res == {"push": 1, "kakao": False, "memo": False}
    assert led.get("A1:kospi:up:2026-10-02")["sent"]["push"] == 1
    item = json.load(open(q, encoding="utf-8"))[0]
    assert item["id"] == "A1:kospi:up:2026-10-02" and item["title"] == "코스피 +2.6% · 7,004"
    assert item["body"] == "나스닥 동반\n다음 마디 8,000" and item["url"].endswith("#/i/kospi") and item["requireInteraction"] is False


def test_held_sends_no_push(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "notify_discord", _NoDiscord())
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path)); led.append(_row())
    q = str(tmp_path / "push_queue.json")
    res = deliver.send(Send(row=_row(), level="alert", push=True, kakao=True, held=True), led, _ctx(), log=lambda *a: None, queue_path=q)
    assert res == {"push": 0, "kakao": False, "memo": False}                       # 카톡 시크릿 없음(conftest) = 메모도 없음
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


def test_memo_mode_records_everything(tmp_path, monkeypatch):
    """메모 모드: 편성이 카톡을 안 골라도(안내) 메모로 남긴다 — 원장엔 kakao 가 아니라 memo 로(하루 상한 · 카톡 쿼터는
    kakao 만 센다). 푸시가 먼저, 카톡은 마지막. 친구 모드는 편성대로(안내는 카톡 없음)."""
    monkeypatch.setitem(sys.modules, "notify_discord", _NoDiscord())
    for on, friends, want in ((False, [], [None]), (True, [{"uuid": "u"}], [])):
        order, sent = [], []
        card = lambda tok, title, cap, **k: order.append("kakao") or sent.append(k.get("uuids")) or True  # noqa: E731
        _kakao_env(monkeypatch, _fake_kakao(on, friends, sent, send_card=card))
        monkeypatch.setattr(deliver, "enqueue_push", lambda items, path: order.append("push") or True)
        led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path / str(on))); led.append(_row(level="notice"))
        res = deliver.send(Send(row=_row(level="notice"), level="notice", push=True), led, _ctx(), log=lambda *a: None,
                           queue_path=str(tmp_path / "q.json"))
        assert sent == want and res["memo"] is bool(want) and res["kakao"] is False and res["push"] == 1
        assert order == ["push"] + ["kakao"] * len(want)
        got = led.get("A1:kospi:up:2026-10-02")["sent"]
        assert got["kakao"] is False and got.get("memo", False) is bool(want)


def test_held_goes_to_memo_only_in_memo_mode(tmp_path, monkeypatch):
    """조용한 시간 보류분은 무음 메모로만 남는다 — 푸시는 아침 브리핑에 합류(held_rows)."""
    monkeypatch.setitem(sys.modules, "notify_discord", _NoDiscord())
    sent = []
    _kakao_env(monkeypatch, _fake_kakao(False, [], sent))
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path)); led.append(_row())
    q = str(tmp_path / "q.json")
    res = deliver.send(Send(row=_row(), level="alert", push=True, held=True), led, _ctx(), log=lambda *a: None, queue_path=q)
    assert sent == [None] and res == {"push": 0, "kakao": False, "memo": True} and not os.path.exists(q)
    assert deliver.held_rows(led)[0]["key"] == "A1:kospi:up:2026-10-02"
    # 친구 모드(울리는 카톡)면 밤에는 카톡도 안 보낸다
    sent.clear()
    _kakao_env(monkeypatch, _fake_kakao(True, [{"uuid": "u"}], sent))
    deliver.send(Send(row=_row(), level="alert", kakao=True, held=True), led, _ctx(), log=lambda *a: None, queue_path=q)
    assert sent == []


def test_kakao_token_once_per_run_and_down_after_failure(tmp_path, monkeypatch):
    """토큰은 런당 한 번. 한 통이 실패(SystemExit 포함)하면 그 런의 나머지 카톡은 건너뛰고 푸시는 계속 나간다
    — 카카오가 시간을 끌면 한 통에 수 분이라 잡 시한을 넘긴다."""
    monkeypatch.setitem(sys.modules, "notify_discord", _NoDiscord())
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
        out.append(deliver.send(Send(row=r, level="alert", push=True), led, _ctx(), log=lambda *a: None,
                                queue_path=str(tmp_path / "q.json")))
    assert calls == ["refresh"] and len(sent) == 2                      # 셋째 통은 카톡을 부르지 않는다
    assert [o["memo"] for o in out] == [True, False, False] and all(o["push"] == 1 for o in out)


def test_kakao_token_death_does_not_kill_push(tmp_path, monkeypatch):
    """refresh_access_token 은 토큰 사망을 SystemExit 로 던진다 — 카톡만 빠지고 푸시는 나가야 한다."""
    monkeypatch.setitem(sys.modules, "notify_discord", _NoDiscord())
    sent = []
    _kakao_env(monkeypatch, _fake_kakao(False, [], sent, refresh=lambda a, b: (_ for _ in ()).throw(SystemExit("KOE322"))))
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path)); led.append(_row())
    res = deliver.send(Send(row=_row(), level="alert", push=True, kakao=True), led, _ctx(), log=lambda *a: None,
                       queue_path=str(tmp_path / "q.json"))
    assert res == {"push": 1, "kakao": False, "memo": False} and sent == []


def test_kakao_parts_buttons_8chars_and_items():
    s = Send(row=dict(_row(), value=7003.74), level="alarm", kakao=True)      # 원장 값은 숫자(compose 가 글로 바꾼다)
    p = deliver.kakao_parts(s)
    assert len(p["buttons"]) == 2 and all(len(b[0]) <= 8 for b in p["buttons"])
    # 카드가 값을 말하므로 행은 없고(그림·글 중복 제거, 2026-10-11), 설명 = 왜 · 다음, 버튼 = 그 화면 · 받은 알림
    assert p["items"] == [] and p["caption"] == "나스닥 동반\n다음 마디 8,000" and p["photo"] is True
    assert [b[0] for b in p["buttons"]] == ["지표 보기", "받은 알림"]
    assert p["kind"] == "알림 v2 경보"
    # 글자 사건(공시)은 사진 없는 피드 — 큰 숫자 자리에 「잠정실적」이 박히던 카드를 안 만든다
    f1 = dict(_row(), event="F1", value="잠정실적", url="#/i/005930")
    assert deliver.kakao_parts(Send(row=f1, level="notice", kakao=True))["photo"] is False
    assert deliver.screen_label({"url": "#/market?a=flow"}) == "수급 보기"


def test_bundle_marks_members(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "notify_discord", _NoDiscord())
    led = Ledger(day=dt.date(2026, 10, 2), root=str(tmp_path))
    members = [_row(f"A1:x{i}:up:2026-10-02") for i in range(3)]
    for m in members:
        led.append(m)
    brow = dict(_row("BUNDLE:2026-10-02:1400"), event="BUNDLE", title="알림 3건 더 · 코스피")
    q = str(tmp_path / "push_queue.json")
    deliver.send(Send(row=brow, level="alert", push=True, bundled=True, bundle=members, kind="bundle"), led, _ctx(), log=lambda *a: None, queue_path=q)
    assert all(led.get(m["key"])["sent"]["bundled"] and led.get(m["key"])["sent"]["push"] == 1 for m in members)
    assert led.get("BUNDLE:2026-10-02:1400") is not None
    assert json.load(open(q, encoding="utf-8"))[0]["title"] == "알림 3건 더 · 코스피"


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
