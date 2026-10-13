#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notify_discord.send — #시스템 무음 · 플래그 · 링크 버튼 웹훅 경로.

폰 알림 경로 고정(2026-10-13): 경제 알림은 디스코드로 안 가고(웹앱 푸시 + 카톡), 디스코드엔 운영 경고(#시스템)만
무음으로 남는다. 등급 표(send_level)는 쓰는 곳이 없어져 지웠다.
실제 전송은 없다: 웹훅 URL 은 env 이름이 보이게 가짜로 두고, 이 사본의 _post 만 바꿔 페이로드를 받아 적는다.
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


def test_system_is_silent_without_mention():
    """운영 경고는 기록만 — 무음 플래그, 멘션 없음(감시자 침묵 경보가 @everyone 을 달아 불러도)."""
    assert nd.system("수집 실패", mention=True) is True
    got = _last()
    assert got["url"] == "https://hook.invalid/DISCORD_WEBHOOK_SYSTEM"
    assert got["payload"]["flags"] == SUPPRESS and "content" not in got["payload"]


def test_system_silent_even_on_fallback_hook(monkeypatch):
    """#시스템 웹훅이 비어 기본 채널로 떨어져도 무음은 그대로 — 판정은 요청한 env 이름으로 한다."""
    monkeypatch.delenv("DISCORD_WEBHOOK_SYSTEM")
    assert nd.send("월간 보고", title="t", env="DISCORD_WEBHOOK_SYSTEM", flags=None) is True
    got = _last()
    assert got["url"] == "https://hook.invalid/DISCORD_WEBHOOK_URL" and got["payload"]["flags"] == SUPPRESS


def test_send_flags_default_leaves_other_callers_untouched():
    assert nd.send("본문", title="t") is True                # 종전 호출 — flags 키 없음
    assert "flags" not in _last()["payload"]
    POSTED.clear()
    assert nd.send("본문") is True                           # title 없는 content 경로도 같다
    assert "flags" not in _last()["payload"]
    POSTED.clear()
    assert nd.send("본문", flags=SUPPRESS) is True
    assert _last()["payload"]["flags"] == SUPPRESS


def test_unset_hooks_are_noop(monkeypatch):
    for k in ENVS:
        monkeypatch.delenv(k)
    assert nd.system("t") is False and nd.send("t", env="DISCORD_WEBHOOK_ALERTS") is False
    assert POSTED == []


def test_link_buttons_ride_the_webhook_without_bot(monkeypatch):
    """링크 버튼뿐이면 봇 없이 웹훅에 단다(with_components=true) — 봇 403(채널 권한 없음)으로 버튼이 사라졌었다."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    assert nd.send("본문", title="10/9 아침", buttons=[("S&P 500", "https://x/sp"), ("대시보드", "https://x/")])
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
    assert nd.send("본문", title="10/9 아침", buttons=[("S&P 500", "https://x/sp")])
    assert "components" not in POSTED[0]["payload"]
    assert POSTED[0]["payload"]["embeds"][0]["fields"][-1]["value"] == "[S&P 500](https://x/sp)"
