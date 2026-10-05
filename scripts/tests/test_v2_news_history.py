"""알림 v2 A4 data-fixes(알림 쪽) — 뉴스 「왜」 재료 선택기 · 이력 적재기 · run.py 연결.

실행: python -m pytest scripts/tests/test_v2_news_history.py -q
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from alerts_v2 import history_sink, newsmatch  # noqa: E402
from alerts_v2.context import KST, Context  # noqa: E402

# ── 1) 뉴스 재료 선택기 ─────────────────────────────────────────────────────
NOW = dt.datetime(2026, 10, 5, 14, 0, tzinfo=KST)


def _news_ctx(news):
    reg = {"kospi": {"id": "kospi", "asset": "index"}, "wti": {"id": "wti", "asset": "commodity"},
           "btc": {"id": "btc", "asset": "index"}}
    return Context(now=NOW, data={"news": news}, bundles={}, registry=reg, mer={})


def _item(title, pub, url="https://x/1"):
    return {"title": title, "url": url, "pubDate": pub, "isoDate": "2026-10-05"}


def test_pick_news_requires_topic_and_keyword_and_24h():
    news = {
        "주식": [
            _item("손흥민 멀티골…토트넘 3-1 승리", "Mon, 05 Oct 2026 12:00:00 +0900"),                  # 주제 안이지만 무관(축구)
            _item("[마감시황] 코스피, 장 막판 7천피 탈환", "Mon, 05 Oct 2026 09:00:00 +0900", "https://x/new"),
            _item("코스피 7,000선 회복 이틀째", "Sun, 04 Oct 2026 20:00:00 +0900", "https://x/old"),   # 더 오래됨 — 최신이 이긴다
            _item("코스피 연휴 직전 약세", "Sat, 03 Oct 2026 10:00:00 +0900"),                         # 24시간 밖
        ],
        "외환": [_item("코스피 외국인 순매도 확대", "Mon, 05 Oct 2026 10:00:00 +0900")],                 # 키워드는 맞지만 주제가 다르다
        "원유": [_item("고인 보험금, 유가족이 찾기 쉬워졌다", "Mon, 05 Oct 2026 11:00:00 +0900")],         # 「유가」 오탐(유가족)
    }
    got = newsmatch.pick_news(_news_ctx(news), "kospi")
    assert got and got["title"].startswith("[마감시황] 코스피") and got["url"] == "https://x/new" and got["topic"] == "주식"
    assert newsmatch.pick_news(_news_ctx(news), "wti") is None            # 유가족 기사만 — 걸리지 않는다
    only_soccer = {"주식": [_item("손흥민 멀티골…토트넘 3-1 승리", "Mon, 05 Oct 2026 12:00:00 +0900")]}
    assert newsmatch.pick_news(_news_ctx(only_soccer), "kospi") is None
    assert newsmatch.pick_news(_news_ctx(news), "없는지표") is None


def test_pick_news_handles_missing_dates_and_unknown_topic():
    ctx = _news_ctx({"주식": [{"title": "코스피 급등", "url": "u"}]})                 # 날짜 없음 — 24시간을 증명 못 하니 안 붙인다
    assert newsmatch.pick_news(ctx, "kospi") is None
    ctx = _news_ctx({"주식": [{"title": "비트코인 9만 달러 돌파", "url": "u", "isoDate": "2026-10-05"}]})
    assert newsmatch.pick_news(ctx, "btc")["title"].startswith("비트코인")           # 날짜만 있으면 그날 0시로 본다


# ── 2) 이력 적재기 ──────────────────────────────────────────────────────────
def _sink_ctx(root, vk=40.96, as_of="2026-10-02", state="prev"):
    data = {"freight": {"items": [{"code": "BDI", "price": 3148.0, "date": "2026-10-02"}]},
            "lmeInventory": {"as_of": "2026-10-02", "data": [{"name": "Copper", "cur": 248650}]},
            "marketBreadth": {"kospi": {"up": 500, "down": 362, "as_of": "2026-10-02"}},
            "sectorMoves": {"as_of": "2026-10-02", "items": [{"name": "섬유·의류", "close": 229.92, "chg_pct": 0.97}]}}
    b = {"market-domestic": {"strip": [{"id": "vkospi", "value": vk, "asOf": as_of, "state": state}]},
         "market-commodities": {"strip": [{"id": "gold_premium", "value": 0.38, "asOf": "2026-10-02", "state": "prev"}]}}
    ctx = Context(now=NOW, data=data, bundles=b, registry={}, mer={}, root=str(root))
    ctx._index_strips()
    return ctx


def _read(root, key):
    with open(os.path.join(str(root), "events", "history", key + ".json"), encoding="utf-8") as f:
        return json.load(f)


def test_history_sink_same_day_twice_is_one_point(tmp_path):
    ctx = _sink_ctx(tmp_path)
    first = history_sink.run(ctx)
    again = history_sink.run(ctx)
    assert first and again == []                                                  # 두 번째는 바뀐 게 없다
    assert _read(tmp_path, "vkospi") == [{"date": "2026-10-02", "value": 40.96}]
    assert sorted(first) == sorted(["vkospi", "gold_premium", "freight_bdi", "lme_copper", "breadth_kospi_up",
                                    "breadth_kospi_down", "sector_섬유_의류"])
    assert _read(tmp_path, "sector_섬유_의류") == [{"date": "2026-10-02", "value": 229.92}]        # 업종은 지수(종가)를 쌓는다
    history_sink.run(_sink_ctx(tmp_path, vk=41.5))                                  # 같은 날짜 다른 값 — 갈아끼운다(잠정 → 확정)
    assert _read(tmp_path, "vkospi") == [{"date": "2026-10-02", "value": 41.5}]
    history_sink.run(_sink_ctx(tmp_path, vk=39.0, as_of="2026-10-05"))              # 새 날짜 — 한 점 더
    assert [p["date"] for p in _read(tmp_path, "vkospi")] == ["2026-10-02", "2026-10-05"]


def test_history_sink_skips_kept_values_and_caps_at_400(tmp_path):
    assert "vkospi" not in history_sink.points(_sink_ctx(tmp_path, state="kept"))   # 묵은 값을 오늘 날짜로 찍지 않는다
    rows = []
    for i in range(405):
        rows = history_sink.add(rows, (dt.date(2025, 1, 1) + dt.timedelta(days=i)).isoformat(), i)
    assert len(rows) == 400 and rows[0]["value"] == 5 and rows[-1]["value"] == 404
    assert history_sink.add(rows, rows[-1]["date"], -1)[-1]["value"] == -1 and len(history_sink.add(rows, rows[-1]["date"], -1)) == 400


def test_history_sink_dry_run_writes_nothing(tmp_path):
    assert history_sink.run(_sink_ctx(tmp_path), dry_run=True)
    assert not os.path.exists(os.path.join(str(tmp_path), "events"))


def test_run_calls_history_sink_only_in_daily_mode(monkeypatch):
    from alerts_v2 import run as v2run
    calls = []
    monkeypatch.setattr(v2run.history_sink, "run", lambda ctx, dry_run=False: calls.append(dry_run) or [])
    assert v2run.main(["--mode", "daily", "--dry-run"]) == 0
    assert calls == [True]
    assert v2run.main(["--mode", "light", "--dry-run"]) == 0
    assert calls == [True]
