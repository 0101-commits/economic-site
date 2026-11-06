"""폰 알림 글자 수 검사(P5) — 사전 39종 × 예제 값이 잠금 화면 한 줄(제목 18칸 · 본문 20칸)에 든다."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import check_copy, compose  # noqa: E402


def test_every_event_fits_lock_screen_line():
    assert check_copy.check() == []


def test_calendar_titles_keep_verdict_and_country():
    """발표 결과 제목은 판정어를 남기고, 일정 이름은 줄임 표로만 줄인다(「미국 소매…」 금지)."""
    d = {"event_name": "미국 소매판매", "act": "+0.6%", "vs_fore": "예상 웃돎"}
    assert compose.fit_title("{event_name} {act} · {vs_fore}", d) == "미국 소매판매 +0.6% · 예상 웃돎"
    d = {"event_name": "일본은행(BOJ) 금융정책결정회합", "act": "0.75%", "vs_fore": "예상대로"}
    assert compose.fit_title("{event_name} {act} · {vs_fore}", d) == "일본은행 금리 0.75% · 예상대로"
    d = {"event_name": "미국 소매판매", "act": "+2.8%", "vs_big": "예상과 큰 차이"}
    assert compose.fit_title("{event_name} {act} · {vs_big}", d) == "미국 소매판매 +2.8% · 큰 차이"
