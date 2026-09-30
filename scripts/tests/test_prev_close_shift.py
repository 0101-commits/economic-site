# -*- coding: utf-8 -*-
"""전일 봉 밀림(Yahoo 개장 무렵 전날 봉이 오늘 날짜로 붙는 현상)에서 등락률 기준가 가드.

2026-07-29 09:16 data.json 이력: KOSPI 7/27 6755.75 · '7/29' 6023.66 (7/28 없음). 같은 모양이
급변 속보에서 8/6·8/7·8/12~14·8/19·8/25 에 나왔다(GHA 로그로 역산한 기준가 = 이틀 전 종가).
rows[-2]/closes[-2] 를 기준가로 쓰던 yahoo_snapshot·_yahoo_live_quote 가 가짜 등락률을 냈다.
네트워크는 전부 monkeypatch 로 막는다."""
import datetime
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import check_alerts as ca          # noqa: E402
import send_kakao_digest as k      # noqa: E402
import toss_api                    # noqa: E402

KST = datetime.timezone(datetime.timedelta(hours=9))
ET = datetime.timezone(datetime.timedelta(hours=-4))


class _Frozen(datetime.datetime):
    NOW = None

    @classmethod
    def now(cls, tz=None):
        return cls.NOW.astimezone(tz) if tz else cls.NOW.replace(tzinfo=None)


def _res(symbol, bars, price, tz=KST):
    """Yahoo v8 chart result[0] — bars = [(현지 날짜, 종가)], 봉 시각은 현지 09:00."""
    ts = [int(datetime.datetime.fromisoformat(d + "T09:00:00").replace(tzinfo=tz).timestamp())
          for d, _ in bars]
    cl = [c for _, c in bars]
    return {"meta": {"symbol": symbol, "regularMarketPrice": price,
                     "gmtoffset": int(tz.utcoffset(None).total_seconds())},
            "timestamp": ts,
            "indicators": {"quote": [{"open": cl, "high": cl, "low": cl, "close": cl,
                                      "volume": [1] * len(cl)}]}}


def _setup(monkeypatch, now_iso, res, cal=None):
    _Frozen.NOW = datetime.datetime.fromisoformat(now_iso)
    shim = types.SimpleNamespace(datetime=_Frozen, timezone=datetime.timezone,
                                 timedelta=datetime.timedelta, date=datetime.date)
    monkeypatch.setattr(ca, "datetime", shim)
    monkeypatch.setattr(k, "datetime", shim)
    monkeypatch.setattr(toss_api, "snapshot", lambda *a, **kw: None)
    monkeypatch.setattr(toss_api, "live_quote", lambda *a, **kw: None)
    monkeypatch.setattr(ca, "_http_get_json", lambda url, mobile=False: {"chart": {"result": [res]}})
    monkeypatch.setattr(k, "_yahoo_chart_result", lambda symbol, rng="1d", interval="5m": res)
    monkeypatch.setattr(k, "_kr_calendar", lambda: cal or {}, raising=False)


# 7/29 09:40 — 7/28 봉(6023.66)이 빠지고 7/29 봉이 라이브값(+1.5%)을 달고 있다.
_0729 = _res("^KS11", [("2026-07-22", 6797.70), ("2026-07-23", 7096.89), ("2026-07-24", 6690.62),
                       ("2026-07-27", 6755.75), ("2026-07-29", 6114.0)], 6114.0)
_CAL_0729 = {"today": {"date": "2026-07-29", "open": True},
             "previousBusinessDay": {"date": "2026-07-28", "open": True}}


def test_snapshot_holds_when_prev_session_bar_missing(monkeypatch):
    _setup(monkeypatch, "2026-07-29T09:40:00+09:00", _0729, _CAL_0729)
    snap = ca.yahoo_snapshot("^KS11")
    # 종전: 7/27 종가 기준 -9.50% (실제 +1.5%) → 급변 속보·시장 대비 문구에 그대로 실렸다.
    assert snap is None, f"7/27 기준 가짜 등락률 {snap and round(snap['pct'], 2)}%"


def test_live_quote_holds_when_prev_session_bar_missing(monkeypatch):
    _setup(monkeypatch, "2026-07-29T09:40:00+09:00", _0729, _CAL_0729)
    # None 이면 apply_live_quotes 가 data.json 값·등락률 한 쌍을 그대로 둔다.
    assert k._yahoo_live_quote("^KS11") is None


def test_live_quote_holds_on_0819_digest_shape(monkeypatch):
    """실발송: 8/19 09시 시황 「코스피 6,870 ▲0.8%」 — 6869.83 은 8/18 종가, 기준가는 8/13 종가
    (6813.34, 8/14 봉 누락). 직전 세션(8/18)의 실제 등락은 8/14 대비 ▼1.5% 였다."""
    res = _res("^KS11", [("2026-08-11", 6345.53), ("2026-08-12", 6579.04), ("2026-08-13", 6813.34),
                         ("2026-08-18", 6869.83)], 6869.83)
    cal = {"today": {"date": "2026-08-19", "open": True},
           "previousBusinessDay": {"date": "2026-08-18", "open": True}}
    _setup(monkeypatch, "2026-08-19T09:00:30+09:00", res, cal)
    assert k._yahoo_live_quote("^KS11") is None


def test_legit_gaps_and_normal_days_still_quote(monkeypatch):
    # 연휴 다음 날(8/17 대체공휴일) — 달력이 직전 영업일을 8/14 로 알려 주므로 보류하지 않는다.
    res = _res("^KS11", [("2026-08-12", 6579.04), ("2026-08-13", 6813.34), ("2026-08-14", 6977.94),
                         ("2026-08-18", 7121.0)], 7121.0)
    cal = {"today": {"date": "2026-08-18", "open": True},
           "previousBusinessDay": {"date": "2026-08-14", "open": True}}
    _setup(monkeypatch, "2026-08-18T09:20:00+09:00", res, cal)
    want = (7121.0 / 6977.94 - 1) * 100
    assert abs(ca.yahoo_snapshot("^KS11")["pct"] - want) < 1e-6
    assert abs(k._yahoo_live_quote("^KS11")[1] - want) < 1e-6
    # 해외 평일(달력 없음) — 직전 평일 봉이 있으면 종전 그대로.
    res = _res("^GSPC", [("2026-09-25", 7743.41), ("2026-09-28", 7683.69), ("2026-09-29", 7670.84),
                         ("2026-09-30", 7714.87)], 7714.87, tz=ET)
    _setup(monkeypatch, "2026-09-30T11:00:00-04:00", res)
    want = (7714.87 / 7670.84 - 1) * 100
    assert abs(ca.yahoo_snapshot("^GSPC")["pct"] - want) < 1e-6
    assert abs(k._yahoo_live_quote("^GSPC")[1] - want) < 1e-6
