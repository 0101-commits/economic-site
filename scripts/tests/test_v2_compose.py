"""문구 틀 — 다섯 칸 · 길이 상한 · 꼬리표 · 빈 변수 · 상대 시점어."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import compose, schema  # noqa: E402
from alerts_v2.events import Hit  # noqa: E402

EV = schema.by_id(schema.load_events())
TODAY = dt.date(2026, 10, 2)


def test_flow_streak_title_and_body():
    h = Hit(target="kospi", dir="sell", value=-2040, unit="억", asOf="2026-10-01", fresh="prev",
            fields={"streak": 5, "cum5": "−7.9조", "supporter": "기관 순매수", "dir_ko": "순매도", "dir_rev_ko": "순매수"})
    r = compose.render(EV["D1"], h, None, today=dt.date(2026, 10, 1))
    assert r["title"] == "외국인 5일째 순매도 · 오늘 −2,040억"
    assert r["why"] == "5일 누적 −7.9조 · 기관 순매수가 받침"
    assert r["next"] == "확정 18:00 · 순매수로 돌아서면 알림"
    assert r["body_push"] == r["why"] + "\n" + r["next"] and len(r["body_push"]) <= 80
    assert r["url"] == "#/market?a=flow" and r["level"] == "alert"


def test_stale_value_gets_date_tag_and_cho_unit():
    assert compose.fmt_num(-89888, "억") == "−8.99조"
    assert compose.fmt_num(7003.74) == "7,004"
    assert compose.fmt_num(5.64, "%") == "5.64%"
    assert compose.stale_tag("prev", "2026-09-30", TODAY) == "(9/30)"
    assert compose.stale_tag("kept", "2026-09-30", TODAY) == "(이전 값)"
    assert compose.stale_tag("live", "2026-10-02", TODAY) == ""
    h = Hit(target="us10y", dir="up", value=5.29, unit="%", asOf="2026-09-30", fresh="prev", chg=None,
            fields={"name": "미 10년", "chg_bp": 3, "peer": "한 10년", "peer_chg": "+3bp"})
    r = compose.render(EV["C7"], h, None, today=TODAY)
    assert "5.29% (9/30)" in r["title"] and len(r["title"]) <= 30


def test_missing_variables_drop_cleanly():
    h = Hit(target="sp500", dir="up", value=7747.03, unit="", asOf="2026-10-02", fresh="live", chg=1.02,
            fields={"name": "S&P500"})
    r = compose.render(EV["A1"], h, None, today=TODAY)
    assert r["title"] == "S&P500 +1.0% · 7,747"
    assert "·" not in r["why"] or r["why"].strip("· ") == r["why"]   # 빈 변수로 「 · 」만 남지 않음
    assert r["next"] == ""                                            # next 틀 변수 전부 없음 → 빈 줄


def test_title_cut_and_relative_time_removed():
    ev = dict(EV["A1"], title="{name} " + "가" * 40, next=["내일 발표 {x}"])
    h = Hit(target="kospi", dir="up", value=7003, unit="", asOf="2026-10-02", fresh="live", chg=0.46,
            fields={"name": "코스피", "x": "GDP"})
    r = compose.render(ev, h, None, today=TODAY)
    assert len(r["title"]) == 30 and r["title"].endswith("…")
    assert r["next"] == ""   # 「내일」 상대 시점어 금지


def test_brief_level_allows_48():
    ev = dict(EV["A1"], level="brief", title="{name} " + "가" * 44)
    h = Hit(target="kospi", dir="up", value=1, unit="", asOf="2026-10-02", fresh="live", fields={"name": "코스피"})
    assert len(compose.render(ev, h, None, today=TODAY)["title"]) == 48
