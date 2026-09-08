"""_stale_limit_min 회귀 테스트 — ⚙️ 파이프라인 경고의 시간대별 임계.

배경(2026-09-08 진단): data.json 을 채우는 쪽과 스테일을 판정하는 쪽의 주기가 다르다.
Worker cron 은 장중(평일 KST 09~16시·22~07시)에만 fetch-data 를 5분 주기로 깨우고,
장외·주말의 공급은 GHA 시간당 cron 하나뿐인데 그 cron 의 실측 미발화율이 42%다.
그런데 카카오 다이제스트는 평일 07~22시 매시간·주말 11·17시에 판정한다 — 겹치지 않는
평일 07~09시·16~22시와 주말 전체가 구조적 오탐 구간이었다(10일간 120분 초과 공백 28건,
최장 324분, 전부 이 구간).

이 테스트가 지키는 것: 장중은 종전 120분을 유지하고(진짜 이상은 여전히 잡는다),
공급이 없는 시간대만 완화된다. 경계(07/09/16/22시)가 어긋나면 오탐이 되돌아온다.

실행: python -m pytest scripts/tests/test_stale_limit.py  (또는 python scripts/tests/test_stale_limit.py)
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import send_kakao_digest  # noqa: E402
from send_kakao_digest import KST, _stale_limit_min  # noqa: E402

MARKET = 120        # 장중 — Worker 가 5분마다 경량 런을 깨우는 구간
OFF = 240           # 평일 장외 — 시간당 cron 1회 + 풀 런 44~62분
WEEKEND = 720       # 주말·공휴일 — 공급이 시간당 cron 하나, 실측 미발화율 42%


def _at(hour, minute=30):
    """2026-09-08 = 화요일 — 평일 케이스의 기준일."""
    return datetime.datetime(2026, 9, 8, hour, minute, tzinfo=KST)


def test_weekday_market_hours_keep_120():
    # 심야 미국장(00~06시), 한국장(09~15시), 미국장 개장 후(22~23시)
    for h in (0, 3, 6, 9, 12, 15, 22, 23):
        assert _stale_limit_min(_at(h), False) == MARKET, f"{h}시는 장중이어야 한다"


def test_weekday_off_hours_relax_to_240():
    # 07~08시(장 개시 전)와 16~21시(한국장 마감~미국장 개시 전)
    for h in (7, 8, 16, 18, 21):
        assert _stale_limit_min(_at(h), False) == OFF, f"{h}시는 평일 장외여야 한다"


def test_boundaries_are_exact():
    # 경계 하나만 밀려도 정상 케이던스가 다시 경고를 쏜다.
    assert _stale_limit_min(_at(6, 59), False) == MARKET
    assert _stale_limit_min(_at(7, 0), False) == OFF
    assert _stale_limit_min(_at(8, 59), False) == OFF
    assert _stale_limit_min(_at(9, 0), False) == MARKET
    assert _stale_limit_min(_at(15, 59), False) == MARKET
    assert _stale_limit_min(_at(16, 0), False) == OFF
    assert _stale_limit_min(_at(21, 59), False) == OFF
    assert _stale_limit_min(_at(22, 0), False) == MARKET


def test_weekend_and_holiday_ignore_hour():
    # weekend 인자는 _is_weekend() 값 = 토·일 + 공휴일(KR_HOLIDAY=1). 시각과 무관하게 720.
    for h in (0, 11, 17, 23):
        assert _stale_limit_min(_at(h), True) == WEEKEND


def test_is_weekend_feeds_holiday_flag():
    """호출부가 넘기는 weekend 가 공휴일도 담고 있는지 — 두 함수의 계약 확인."""
    monday = datetime.datetime(2026, 9, 7, 12, tzinfo=KST)   # 2026-09-07 = 월요일
    prev = os.environ.get("KR_HOLIDAY")
    try:
        os.environ.pop("KR_HOLIDAY", None)
        assert send_kakao_digest._is_weekend(monday) is False
        os.environ["KR_HOLIDAY"] = "1"
        assert send_kakao_digest._is_weekend(monday) is True
    finally:
        if prev is None:
            os.environ.pop("KR_HOLIDAY", None)
        else:
            os.environ["KR_HOLIDAY"] = prev


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  OK   {name}")
            except AssertionError as e:
                fails += 1
                print(f"  FAIL {name}: {e}")
    print("실패 0건" if not fails else f"실패 {fails}건")
    sys.exit(1 if fails else 0)
