"""toss_connection_status 회귀 테스트 — 토스 연결상태 배지의 판정 로직.

배경: 토스는 IP 허용 목록 때문에 CI 에서 호출할 수 없고, 허용 IP 가 등록된 PC 수집기가
toss_snapshot.json 을 커밋해 넘긴다. 따라서 "토스 연결상태"는 곧 그 스냅샷의 신선도다.
PC 가 꺼져 있으면 파일이 늙고, fetch_data 의 항목별 가드가 낡은 부분을 떨궈 폴백이 돈다.
배지가 이 상태를 잘못 읽으면 사용자는 폴백 값을 실시간으로 오인한다.

실행: python -m pytest scripts/tests/test_toss_status.py  (또는 python scripts/tests/test_toss_status.py)
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fetch_data  # noqa: E402
from fetch_data import toss_connection_status  # noqa: E402

GEN = "2026-08-14T20:44:42.601027+09:00"
BASE = datetime.fromisoformat(GEN)
SOURCES = {
    "stockMovers": "토스증권 Open API",
    "investorTrading": "토스증권 Open API (KOSPI 투자자별 매매동향, PC 수집기)",
    "etfMovers": "KRX OpenAPI",
    "fx": "open.er-api.com + yfinance",
}


def _snap(data):
    """_toss_snapshot 의 프로세스 캐시를 직접 세팅한다(파일 IO 없이)."""
    fetch_data._toss_snap_cache = {"loaded": True, "data": data}


def test_live_when_fresh():
    _snap({"generatedAt": GEN})
    r = toss_connection_status(SOURCES, now=BASE + timedelta(minutes=30))
    assert r["state"] == "LIVE"
    assert r["ageMinutes"] == 30.0
    assert r["reason"] == ""
    # 토스가 실제로 채운 블록만 집계한다 — KRX/yfinance 는 빠져야 한다.
    assert r["supplied"] == ["investorTrading", "stockMovers"]


# 장중 기준 시각 — 2026-08-13(목) 08:30 에 마지막으로 쓰인 스냅샷.
GEN_AM = "2026-08-13T08:30:00+09:00"
BASE_AM = datetime.fromisoformat(GEN_AM)


def test_stale_when_market_hours_and_old():
    """영업일 장중에 2시간 넘게 안 바뀌었으면 PC 미가동이다."""
    _snap({"generatedAt": GEN_AM})
    r = toss_connection_status(SOURCES, now=BASE_AM + timedelta(hours=3))   # 목 11:30
    assert r["state"] == "STALE"
    assert "PC 미가동" in r["reason"]


def test_boundary_2h_is_still_live():
    _snap({"generatedAt": GEN_AM})
    assert toss_connection_status(SOURCES, now=BASE_AM + timedelta(hours=2))["state"] == "LIVE"
    assert toss_connection_status(
        SOURCES, now=BASE_AM + timedelta(hours=2, minutes=1))["state"] == "STALE"


def test_idle_on_weekend_night():
    """금요일 밤 → 토요일 새벽. 수집기는 변경 없으면 파일을 안 쓰므로 늙는 게 정상."""
    _snap({"generatedAt": GEN})                                        # 금 20:44
    r = toss_connection_status(SOURCES, now=BASE + timedelta(hours=10))  # 토 06:44
    assert r["state"] == "IDLE", r
    assert "휴장" in r["reason"]


def test_idle_on_holiday_by_calendar_today():
    """2026-09-24(목, 추석) 실측 재현 — 캘린더가 오늘 휴장이라고 말한다."""
    _snap({"generatedAt": "2026-09-24T09:00:01+09:00",
           "marketCalendarKr": {"today": {"date": "2026-09-24", "open": False},
                                "previousBusinessDay": {"date": "2026-09-23", "open": True},
                                "nextBusinessDay": {"date": "2026-09-28", "open": True}}})
    r = toss_connection_status(SOURCES, now=datetime.fromisoformat("2026-09-24T15:22:00+09:00"))
    assert r["state"] == "IDLE", r
    assert "2026-09-23" in r["reason"]


def test_idle_on_holiday_by_yesterdays_calendar():
    """PC 가 전날부터 꺼져 캘린더가 어제 것이어도 nextBusinessDay 로 휴장을 안다."""
    _snap({"generatedAt": "2026-09-23T20:00:00+09:00",
           "marketCalendarKr": {"today": {"date": "2026-09-23", "open": True},
                                "nextBusinessDay": {"date": "2026-09-28", "open": True}}})
    r = toss_connection_status(SOURCES, now=datetime.fromisoformat("2026-09-25T11:00:00+09:00"))
    assert r["state"] == "IDLE", r


def test_stale_on_next_business_day():
    """전날 캘린더가 '다음 영업일=오늘'이라고 했는데 장중에 안 바뀌면 STALE."""
    _snap({"generatedAt": "2026-09-22T20:00:00+09:00",
           "marketCalendarKr": {"today": {"date": "2026-09-22", "open": True},
                                "nextBusinessDay": {"date": "2026-09-23", "open": True}}})
    r = toss_connection_status(SOURCES, now=datetime.fromisoformat("2026-09-23T11:00:00+09:00"))
    assert r["state"] == "STALE", r


def test_offline_beyond_96h():
    _snap({"generatedAt": GEN})
    r = toss_connection_status(SOURCES, now=BASE + timedelta(hours=97))
    assert r["state"] == "OFFLINE"
    assert "96시간" in r["reason"]


def test_offline_when_no_snapshot():
    _snap(None)
    r = toss_connection_status(SOURCES, now=BASE)
    assert r["state"] == "OFFLINE"
    assert r["generatedAt"] is None
    assert r["ageMinutes"] is None
    # 스냅샷이 없어도 supplied 집계는 살아 있어야 프론트가 "무엇이 폴백됐는지" 보여준다.
    assert r["supplied"] == ["investorTrading", "stockMovers"]


def test_unparsable_timestamp_is_offline_not_crash():
    _snap({"generatedAt": "20260814-2044"})
    r = toss_connection_status(SOURCES, now=BASE)
    assert r["state"] == "OFFLINE"
    assert "파싱 불가" in r["reason"]


def test_future_timestamp_clamped_not_negative():
    """수집기 PC 와 러너의 시계가 어긋나도 음수 나이를 신선함으로 읽지 않는다."""
    _snap({"generatedAt": GEN})
    r = toss_connection_status(SOURCES, now=BASE - timedelta(hours=5))
    assert r["ageMinutes"] == 0.0
    assert r["state"] == "LIVE"


def test_missing_sources_is_tolerated():
    _snap({"generatedAt": GEN})
    r = toss_connection_status(None, now=BASE)
    assert r["supplied"] == []
    assert r["state"] == "LIVE"


if __name__ == "__main__":
    failed = 0
    for _name, _fn in sorted(globals().items()):
        if not _name.startswith("test_") or not callable(_fn):
            continue
        try:
            _fn()
            print(f"  ok   {_name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {_name}: {e}")
    print(f"\n{'FAILED' if failed else 'all passed'} ({failed} failures)")
    sys.exit(1 if failed else 0)
