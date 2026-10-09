#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notify_discord.send_level — 등급 → 웹훅 env · 멘션 · 플래그 표(알림 v2 A5, 계약서 「등급 level」).

실제 전송은 없다: 웹훅 URL 은 env 이름이 보이게 가짜로 두고, 이 사본의 _post 만 바꿔 페이로드를 받아 적는다.
(이 모듈은 requests 가 아니라 urllib 로 보낸다 — 가짜로 바꿀 자리는 _post 하나.)
실행: python -m pytest scripts/tests/test_notify_levels.py -q
"""
import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENVS = ("DISCORD_WEBHOOK_URL", "DISCORD_WEBHOOK_ALERTS", "DISCORD_WEBHOOK_SWINGS", "DISCORD_WEBHOOK_SYSTEM")
SUPPRESS = 4096


def _fresh():
    # 다른 검사가 공유 모듈의 send 를 갈아 끼우므로 따로 한 벌 읽는다(test_discord_limits 와 같은 이유)
    spec = importlib.util.spec_from_file_location("nd_levels", os.path.join(HERE, "..", "notify_discord.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


nd = _fresh()
POSTED = []


@pytest.fixture(autouse=True)
def hooks(monkeypatch):
    """네 웹훅 env 를 모두 채워(값 = 자기 이름이 든 URL) 어느 env 로 갔는지 URL 로 읽는다. 봇 토큰은 끈다."""
    POSTED.clear()
    for k in ENVS:
        monkeypatch.setenv(k, f"https://hook.invalid/{k}")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setattr(nd, "_post", lambda url, payload, png, filename, extra=None:
                        POSTED.append({"url": url, "payload": payload, "png": png}))


def _last():
    assert len(POSTED) == 1, POSTED
    return POSTED[0]


# 등급 → (웹훅 env, content 멘션, flags)
TABLE = {
    "alarm":  ("DISCORD_WEBHOOK_SWINGS", "@everyone", None),
    "alert":  ("DISCORD_WEBHOOK_ALERTS", None, None),
    "notice": ("DISCORD_WEBHOOK_ALERTS", None, None),         # 무음 해제(2026-10-07)
    "brief":  ("DISCORD_WEBHOOK_URL", None, None),
    "ops":    ("DISCORD_WEBHOOK_SYSTEM", None, None),
}


@pytest.mark.parametrize("level", list(TABLE))
def test_level_table(level):
    env, mention, flags = TABLE[level]
    assert nd.send_level(level, "제목 그대로", "본문") is True
    got = _last()
    assert got["url"] == f"https://hook.invalid/{env}"
    assert got["payload"].get("content") == mention          # 멘션 없음 = content 키 자체가 없다
    assert got["payload"].get("flags") == flags              # 플래그 없음 = flags 키 자체가 없다
    assert got["payload"]["embeds"][0]["title"] == "제목 그대로"


def test_record_is_not_sent_and_unknown_level_raises():
    assert nd.send_level("record", "t", "b") is False
    assert POSTED == []
    with pytest.raises(ValueError):
        nd.send_level("alrm", "t", "b")
    assert POSTED == []


def test_env_fallback_to_default_hook_and_noop(monkeypatch):
    for k in ENVS[1:]:                                       # 전용 env 가 비면 URL(#시황-다이제스트)로
        monkeypatch.delenv(k)
    for level in ("alarm", "alert", "notice", "ops"):
        POSTED.clear()
        assert nd.send_level(level, "t", "b") is True
        assert _last()["url"] == "https://hook.invalid/DISCORD_WEBHOOK_URL"
    monkeypatch.delenv("DISCORD_WEBHOOK_URL")                # 전부 비면 조용히 no-op
    POSTED.clear()
    assert all(nd.send_level(lv, "t", "b") is False for lv in TABLE)
    assert POSTED == []


def test_ops_mention_override_for_silence_watch():
    assert nd.send_level("ops", "침묵", "본문", mention="everyone") is True
    assert _last()["payload"]["content"] == "@everyone"


def test_body_fits_total_1500_with_title_fields_footer():
    body = "\n".join(f"{i:03d} " + "본" * 40 for i in range(80))
    fields = [("이름", "값" * 100, False)]
    assert nd.send_level("brief", "제" * 30, body, fields=fields, footer="꼬" * 20) is True
    e = _last()["payload"]["embeds"][0]
    total = len(e["title"]) + len(e["description"]) + len(e["footer"]["text"]) + sum(
        len(f["name"]) + len(f["value"]) for f in e["fields"])
    assert total <= 1500 and e["description"].endswith("항목")
    assert e["description"].startswith("000 ")               # 앞줄부터 통째로 남는다
    POSTED.clear()
    assert nd.send_level("alert", "t", "짧은 본문") is True      # 안 넘치면 그대로
    assert _last()["payload"]["embeds"][0]["description"] == "짧은 본문"


def test_url_png_and_color_pass_through():
    assert nd.send_level("brief", "t", "b", url="https://x.invalid/", png=b"PNG") is True
    got = _last()
    assert got["png"] == b"PNG" and got["payload"]["embeds"][0]["url"] == "https://x.invalid/"
    assert got["payload"]["embeds"][0]["image"]["url"] == "attachment://chart.png"
    assert got["payload"]["embeds"][0]["color"] == nd.COLOR_DIGEST


def test_send_flags_default_leaves_current_callers_untouched():
    assert nd.send("본문", title="t") is True                # 종전 호출 — flags 키 없음
    assert "flags" not in _last()["payload"]
    POSTED.clear()
    assert nd.send("본문") is True                           # title 없는 content 경로도 같다
    assert "flags" not in _last()["payload"]
    POSTED.clear()
    assert nd.send("본문", flags=SUPPRESS) is True
    assert _last()["payload"]["flags"] == SUPPRESS


def test_link_buttons_ride_the_webhook_without_bot(monkeypatch):
    """링크 버튼뿐이면 봇 없이 웹훅에 단다(with_components=true) — 봇 403(채널 권한 없음)으로 브리핑 버튼이 사라졌었다."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    assert nd.send_level("brief", "10/9 아침", "본문", buttons=[("S&P 500", "https://x/sp"), ("대시보드", "https://x/")])
    assert len(POSTED) == 1 and "/channels/" not in POSTED[0]["url"]           # 봇 경로를 타지 않는다
    assert POSTED[0]["url"].endswith("?with_components=true&wait=true")
    row = POSTED[0]["payload"]["components"][0]["components"]
    assert [b["url"] for b in row] == ["https://x/sp", "https://x/"] and all(b["style"] == 5 for b in row)
    assert not any(f.get("name", "").startswith("바로가기") for f in POSTED[0]["payload"]["embeds"][0].get("fields", []))


def test_webhook_refuses_components_falls_back_to_link_field(monkeypatch):
    def post(url, payload, png, filename, extra=None):
        if "with_components" in url:
            raise RuntimeError("HTTP 400")
        POSTED.append({"url": url, "payload": payload})
    monkeypatch.setattr(nd, "_post", post)
    assert nd.send_level("brief", "10/9 아침", "본문", buttons=[("S&P 500", "https://x/sp")])
    assert "components" not in POSTED[0]["payload"]
    assert POSTED[0]["payload"]["embeds"][0]["fields"][-1]["value"] == "[S&P 500](https://x/sp)"
