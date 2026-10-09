"""브리핑(B5) — 슬롯 6 실데이터 드라이런 · 제목 48자 · 상대 시점어 0 · 휴장일 아침 · 밤사이 합류 · 오늘 바뀐 것 ≤4줄 · 꺼진 슬롯 0통.

네트워크는 conftest 가 막고, 시세 조회 · 수급 · AI 한 문장은 여기서 스텁으로 바꾼다(재시도 대기로 느려지지 않게).
"""
import copy
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import investor_flows  # noqa: E402
import send_kakao_digest as k  # noqa: E402
from alerts_v2 import briefing, compose, deliver  # noqa: E402
from alerts_v2.context import KST, Context  # noqa: E402
from alerts_v2.ledger import Ledger  # noqa: E402

ALL_ON = {"briefings": {s: True for s in briefing.SLOTS}}


@pytest.fixture(scope="module")
def real_ctx():
    return Context.load(now=dt.datetime.now(KST))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    empty = lambda *a, **kw: ([], [], None, "")          # noqa: E731
    monkeypatch.setattr(k, "_session_chain", empty)
    monkeypatch.setattr(k, "_intraday_chain", empty)
    monkeypatch.setattr(k, "_verified_investor", lambda market="KOSPI": None)
    monkeypatch.setattr(k, "slot_ai_line", lambda *a, **kw: "")
    monkeypatch.setattr(investor_flows, "week_sum", lambda *a, **kw: None)


def _no_cards(monkeypatch):
    monkeypatch.setattr(k, "_build_kakao_card", lambda *a, **kw: "card.png")
    monkeypatch.setattr(briefing.dc, "close_report", lambda *a, **kw: "card.png")


def _row(key, level="alert", ts="2026-10-03T01:00:00+09:00", held=False, why="나스닥 동반"):
    return {"key": key, "event": key.split(":")[0], "target": "kospi", "dir": "up", "level": level, "value": 1,
            "unit": "", "asOf": ts[:10], "fresh": "live", "title": f"제목 {key}", "why": why, "next": "",
            "url": "#/alerts", "ts": ts,
            "sent": {"push": 0, "kakao": False, "discord": True, "bundled": False, "held": held}}


def _holiday_ctx(ctx, now):
    """10/3 가짜 달력 — 오늘 휴장, 직전 영업일 10/2, 다음 개장 10/6."""
    c = copy.copy(ctx)
    c.now = now
    c.data = {**ctx.data, "marketCalendarKr": {"today": {"date": now.date().isoformat(), "open": False},
                                               "previousBusinessDay": {"date": "2026-10-02", "open": True},
                                               "nextBusinessDay": {"date": "2026-10-06", "open": True}}}
    return c


def _no_relative(out):
    texts = [out["title"]] + out["lines"] + [f"{a} {b}" for a, b in out["items"]]
    return [t for t in texts if compose.has_relative_time(t)]


@pytest.mark.parametrize("slot", list(briefing.SLOTS))
def test_six_slots_dry_run_on_real_data(slot, real_ctx, tmp_path):
    led = Ledger(day=real_ctx.now.date(), root=str(tmp_path))
    out = briefing.build(slot, real_ctx, led, ALL_ON)
    assert out["title"] and len(out["title"]) <= compose.BRIEF_TITLE_MAX, out["title"]
    assert len(out["lines"]) == 3 and len(out["items"]) <= briefing.ITEMS_MAX
    assert not _no_relative(out), _no_relative(out)
    assert out["card_png"], f"{slot} 카드 없음"
    res = briefing.send(slot, real_ctx, led, ALL_ON, dry_run=True, log=lambda *a: None)
    assert res == {"push": 0, "kakao": False, "discord": False, "memo": False}


def test_holiday_morning(real_ctx, tmp_path, monkeypatch):
    _no_cards(monkeypatch)
    now = dt.datetime(2026, 10, 3, 7, 30, tzinfo=KST)
    ctx = _holiday_ctx(real_ctx, now)
    out = briefing.build("morning", ctx, Ledger(day=now.date(), root=str(tmp_path)), ALL_ON)
    assert out["title"].startswith("10/3(토) 휴장일 아침"), out["title"]
    assert "휴장" in out["title"] and not _no_relative(out)
    assert out["lines"][1] == out["holiday"] == "10/3 한국 휴장 · 다음 개장 10/6"
    assert "코스피" not in out["title"] and "코스닥" not in out["title"]       # 한국 장 칸 없음
    assert not any(lab in ("국내증시", "수급") for lab, _ in out["items"])
    # 한국 장 슬롯은 휴장일에 아무것도 안 보낸다
    sent = []
    monkeypatch.setattr(briefing, "build", lambda *a, **kw: sent.append(a) or {})
    for slot in briefing.KR_SLOTS:
        assert briefing.send(slot, ctx, Ledger(day=now.date(), root=str(tmp_path)), ALL_ON, log=lambda *a: None) \
            == {"push": 0, "kakao": False, "discord": False, "memo": False}
    assert sent == []


def test_stale_calendar_rolls_to_holiday():
    """금요일 달력(today 10/2 · next 10/6)이 멈춘 연휴 월요일 10/5 — 오늘은 휴장, 10/6 은 개장, 10/7 은 모름."""
    stale = {"today": {"date": "2026-10-02", "open": True}, "previousBusinessDay": {"date": "2026-10-01", "open": True},
             "nextBusinessDay": {"date": "2026-10-06", "open": True}}
    d = {"marketCalendarKr": dict(stale)}
    briefing.roll_calendar(d, dt.date(2026, 10, 5))
    assert briefing.dc.kr_closed(d, dt.datetime(2026, 10, 5, 16, 30, tzinfo=KST)) == "2026-10-02"
    d = {"marketCalendarKr": dict(stale)}
    briefing.roll_calendar(d, dt.date(2026, 10, 6))
    assert d["marketCalendarKr"]["today"] == {"date": "2026-10-06", "open": True}
    d = {"marketCalendarKr": dict(stale)}
    briefing.roll_calendar(d, dt.date(2026, 10, 7))
    assert d["marketCalendarKr"] == stale


def test_held_rows_join_morning(real_ctx, tmp_path, monkeypatch):
    _no_cards(monkeypatch)
    now = dt.datetime(2026, 10, 6, 7, 30, tzinfo=KST)
    ctx = copy.copy(real_ctx)
    ctx.now = now
    yday = Ledger(day=now.date() - dt.timedelta(days=1), root=str(tmp_path))
    yday.append(_row("A2:usdkrw:down:2026-10-05", ts="2026-10-05T23:30:00+09:00", held=True, why="엔화 동반 약세"))
    yday.save()
    led = Ledger(day=now.date(), root=str(tmp_path))
    led.append(_row("A1:sp500:up:2026-10-06", ts="2026-10-06T01:00:00+09:00", held=True))
    led.append(_row("C7:us10y:up:2026-10-06", level="notice", ts="2026-10-06T02:00:00+09:00"))   # 보류 아님
    out = briefing.build("morning", ctx, led, ALL_ON)
    assert out["items"][0][0] == "밤사이 알림" and out["items"][0][1].startswith("2건 · "), out["items"]
    assert [r["key"] for r in out["held_rows"]] == ["A2:usdkrw:down:2026-10-05", "A1:sp500:up:2026-10-06"]
    assert out["lines"][0] == "엔화 동반 약세"               # AI 실패 → 원장 첫 행 「왜」
    monkeypatch.setattr(k, "slot_ai_line", lambda *a, **kw: "내일 발표가 남아 있다")   # 상대 시점어 → 사전 문장
    assert briefing.build("morning", ctx, led, ALL_ON)["lines"][0] == "엔화 동반 약세"

    briefing.send("morning", ctx, led, ALL_ON, dry_run=True, log=lambda *a: None)
    assert len(deliver.held_rows(led)) == 1                 # 드라이런은 원장을 건드리지 않는다
    monkeypatch.setattr(briefing, "_kakao", lambda *a, **kw: False)
    monkeypatch.setattr(briefing, "_discord", lambda *a, **kw: True)
    q = str(tmp_path / "push_queue.json")
    res = briefing.send("morning", ctx, led, ALL_ON, log=lambda *a: None, queue_path=q)
    assert res == {"push": 1, "kakao": False, "discord": True, "memo": False}
    assert deliver.held_rows(led) == [] and led.get("A1:sp500:up:2026-10-06")["sent"]["push"] == 1
    on_disk = Ledger(day=now.date() - dt.timedelta(days=1), root=str(tmp_path))
    assert on_disk.get("A2:usdkrw:down:2026-10-05")["sent"]["held"] is False      # 전날 원장도 합류 표시 · 저장
    assert briefing.build("morning", ctx, led, ALL_ON)["held_rows"] == []          # 다음 아침엔 다시 안 실린다


def test_close_changed_is_notice_rows_max_four_lines(real_ctx, tmp_path, monkeypatch):
    _no_cards(monkeypatch)
    now = dt.datetime(2026, 10, 6, 16, 30, tzinfo=KST)
    ctx = copy.copy(real_ctx)
    ctx.now = now
    led = Ledger(day=now.date(), root=str(tmp_path))
    for i in range(5):
        led.append(_row(f"B2:k{i}:up:2026-10-06", level="notice", ts=f"2026-10-06T1{i}:00:00+09:00"))
    led.append(_row("A1:kospi:up:2026-10-06", level="alert"))
    out = briefing.build("close", ctx, led, ALL_ON)
    assert len(out["changed_rows"]) == 5 and all(r["level"] == "notice" for r in out["changed_rows"])
    row = dict(out["items"])["오늘 바뀐 것"].split(" · ")
    assert row[0] == "안내 5건" and len(row) - 1 <= briefing.CHANGED_MAX and row[-1] == "외 2건", row
    assert briefing.changed_lines(out["changed_rows"][:4]) == [r["title"] for r in out["changed_rows"][:4]]
    assert not _no_relative(out)


def test_off_slot_sends_nothing(real_ctx, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(briefing, "build", lambda *a, **kw: calls.append("build"))
    monkeypatch.setattr(deliver, "enqueue_push", lambda *a, **kw: calls.append("push"))
    monkeypatch.setattr(briefing, "_kakao", lambda *a, **kw: calls.append("kakao"))
    monkeypatch.setattr(briefing, "_discord", lambda *a, **kw: calls.append("discord"))
    led = Ledger(day=real_ctx.now.date(), root=str(tmp_path))
    for slot in ("noon", "evening", "us"):                   # 기본 꺼짐
        assert briefing.send(slot, real_ctx, led, None, log=lambda *a: None) == {"push": 0, "kakao": False, "discord": False, "memo": False}
    off = {"briefings": {"morning": False}}
    assert briefing.send("morning", real_ctx, led, off, log=lambda *a: None) == {"push": 0, "kakao": False, "discord": False, "memo": False}
    assert calls == []


def test_workflow_runs_tests_before_briefing():
    from test_workflows_have_pytest import WORKFLOWS_DIR, problems
    with open(os.path.join(WORKFLOWS_DIR, "briefing.yml"), encoding="utf-8") as f:
        text = f.read()
    assert problems(text, "alerts_v2/run.py") == []
    assert "if: vars.ALERTS_V2 == '1'" in text


def test_card_failure_keeps_briefing(real_ctx, tmp_path, monkeypatch):
    """카드 렌더가 죽어도 build 는 글을 돌려준다(카톡은 텍스트로 내려가고 경고가 남는다) — 브리핑 통째 유실 방지."""
    def boom(spec):
        raise RuntimeError("렌더 실패")
    monkeypatch.setattr(briefing.cards, "brief_card_png", boom)
    out = briefing.build("close", real_ctx, Ledger(day=real_ctx.now.date(), root=str(tmp_path)), ALL_ON)
    assert out["card_png"] is None and out["title"]
