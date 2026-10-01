# -*- coding: utf-8 -*-
"""NYSE 휴장일 — 규칙 계산(stdlib 만). 외부 호출 0 · 연방 공휴일 달력과 연 3일 어긋나 못 쓴다(성금요일은 NYSE 만,
콜럼버스·재향군인의 날은 연방만) · 임시 휴장(국장일 등)은 못 보며 그날은 종전처럼 보류(안전 쪽)."""
import datetime

_ONE_DAY = datetime.timedelta(days=1)


def _nth_weekday(year, month, weekday, n):
    """month 의 n번째 weekday(월=0). n=-1 이면 마지막."""
    if n > 0:
        d = datetime.date(year, month, 1)
        d += datetime.timedelta(days=(weekday - d.weekday()) % 7 + 7 * (n - 1))
        return d
    d = (datetime.date(year + (month == 12), month % 12 + 1, 1)) - _ONE_DAY
    return d - datetime.timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d):
    """고정일 휴일의 관측일 — 토→금, 일→월."""
    if d.weekday() == 5:
        return d - _ONE_DAY
    if d.weekday() == 6:
        return d + _ONE_DAY
    return d


def _easter(year):
    """그레고리력 부활절(익명 알고리즘)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    w = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * w) // 451
    month, day = divmod(h + w - 7 * m + 114, 31)
    return datetime.date(year, month, day + 1)


def holidays(year):
    """year 의 NYSE 휴장일 집합(10종, 준틴스는 2022 부터)."""
    days = {
        _nth_weekday(year, 1, 0, 3),                    # 마틴루터킹
        _nth_weekday(year, 2, 0, 3),                    # 대통령의 날
        _easter(year) - 2 * _ONE_DAY,                   # 성금요일
        _nth_weekday(year, 5, 0, -1),                   # 현충일
        _observed(datetime.date(year, 7, 4)),           # 독립기념일
        _nth_weekday(year, 9, 0, 1),                    # 노동절
        _nth_weekday(year, 11, 3, 4),                   # 추수감사절
        _observed(datetime.date(year, 12, 25)),         # 성탄절
    }
    jan1 = datetime.date(year, 1, 1)
    if jan1.weekday() != 5:                             # 신정이 토요일이면 관측 없음(전년 12/31 도 개장)
        days.add(_observed(jan1))
    if year >= 2022:
        days.add(_observed(datetime.date(year, 6, 19)))  # 준틴스
    return days


def is_trading_day(d):
    return d.weekday() < 5 and d not in holidays(d.year)


def prev_trading_day(d):
    """d 직전 거래일(d 자신은 제외)."""
    d -= _ONE_DAY
    while not is_trading_day(d):
        d -= _ONE_DAY
    return d
