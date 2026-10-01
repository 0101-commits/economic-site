# -*- coding: utf-8 -*-
"""NYSE 휴장 달력(규칙 계산)과 yahoo_prev_bar_ok 의 해외 연결.

종전 해외 판정은 「직전 평일」이라 미국 연휴 다음 날(연 9일 안팎) S&P500 속보가 보류됐다.
네트워크는 쓰지 않는다 — 국내 경로의 marketCalendarKr 만 monkeypatch 로 막는다."""
import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import nyse_calendar as nc            # noqa: E402
import send_kakao_digest as k         # noqa: E402

D = datetime.date


@pytest.mark.parametrize("today, want", [
    (D(2026, 4, 6), D(2026, 4, 2)),      # 성금요일(4/3) 다음 월요일
    (D(2026, 7, 6), D(2026, 7, 2)),      # 7/4 토 → 7/3 금 관측
    (D(2026, 11, 27), D(2026, 11, 25)),  # 추수감사절(11/26) 다음 날
    (D(2026, 5, 26), D(2026, 5, 22)),    # 현충일(5/25) 다음 날
    (D(2022, 1, 3), D(2021, 12, 31)),    # 신정 토요일은 관측 없음 — 전년 12/31 개장
    (D(2026, 10, 13), D(2026, 10, 12)),  # 콜럼버스의 날은 NYSE 개장
    (D(2026, 1, 20), D(2026, 1, 16)),    # MLK(1/19) 다음 날
])
def test_prev_trading_day(today, want):
    assert nc.prev_trading_day(today) == want


def test_holidays_2026():
    h = nc.holidays(2026)
    assert {D(2026, 4, 3), D(2026, 6, 19), D(2026, 12, 25)} <= h
    assert D(2026, 10, 12) not in h and D(2026, 11, 11) not in h   # 콜럼버스·재향군인의 날
    assert len(h) == 10


def test_is_trading_day():
    assert nc.is_trading_day(D(2026, 7, 2))
    assert not nc.is_trading_day(D(2026, 7, 3))    # 독립기념일 관측
    assert not nc.is_trading_day(D(2026, 7, 4))    # 토요일


def test_overseas_prev_bar_after_holiday():
    # 7/3 관측 휴장 다음 월요일 — 기준 봉이 7/2 면 정상, 7/1 이면 7/2 봉 누락.
    assert k.yahoo_prev_bar_ok("^GSPC", [D(2026, 7, 2), D(2026, 7, 6)], D(2026, 7, 6)) is True
    assert k.yahoo_prev_bar_ok("^GSPC", [D(2026, 7, 1), D(2026, 7, 6)], D(2026, 7, 6)) is False


@pytest.mark.parametrize("symbol, days", [
    ("KRW=X", [D(2026, 1, 19), D(2026, 1, 20)]),   # 환율은 MLK(1/19)에도 Yahoo 봉이 있다 — 직전 평일
    ("^N225", [D(2026, 4, 3), D(2026, 4, 6)]),     # 닛케이는 성금요일(4/3)에 연다
    ("CL=F", [D(2026, 7, 2), D(2026, 7, 6)]),      # CME 선물은 NYSE 휴일(7/3 관측)에 봉이 없다 — NYSE 달력
])
def test_non_nyse_and_futures_prev_bar(symbol, days):
    assert k.yahoo_prev_bar_ok(symbol, days, days[-1]) is True


def test_domestic_path_unchanged(monkeypatch):
    # 국내는 NYSE 달력을 보지 않는다 — KR 달력이 직전 영업일(8/14)을 알려 주면 그대로 따른다
    # (NYSE 라면 8/17 이 직전 거래일이라 False).
    cal = {"today": {"date": "2026-08-18"}, "previousBusinessDay": {"date": "2026-08-14"}}
    monkeypatch.setattr(k, "_kr_calendar", lambda: cal)
    assert k.yahoo_prev_bar_ok("^KS11", [D(2026, 8, 14), D(2026, 8, 18)], D(2026, 8, 18)) is True
    assert k.yahoo_prev_bar_ok("^KS11", [D(2026, 8, 17), D(2026, 8, 18)], D(2026, 8, 18)) is False
    # KR 달력이 없으면 종전대로 직전 평일 — 성금요일(4/3)은 한국 장이 열린다(NYSE 라면 4/2 → False).
    monkeypatch.setattr(k, "_kr_calendar", lambda: {})
    assert k.yahoo_prev_bar_ok("^KS11", [D(2026, 4, 3), D(2026, 4, 6)], D(2026, 4, 6)) is True
