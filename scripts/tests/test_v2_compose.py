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
            fields={"streak": 5, "cum5": "−7.9조", "supporter": "기관", "support_ko": "기관 순매수가 받침",
                    "dir_ko": "순매도", "dir_rev_ko": "순매수"})
    r = compose.render(EV["D1"], h, None, today=dt.date(2026, 10, 1))
    assert r["title"] == "외국인 5일째 순매도 · −2,040억"   # 제목 한 줄(폭 18) — 「오늘」은 알림 시각이 말한다
    assert r["why"] == "5일 누적 −7.9조 · 기관 순매수가 받침"
    assert r["next"] == ""   # 「…면 알림」 같은 설명 줄은 쓰지 않는다(2026-11-06)
    assert r["body_push"] == r["why"] and compose.width(r["body_push"]) <= compose.BODY_W   # 폰 알림 본문 = 한 줄 · 사실 하나
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
    assert compose.width(r["title"]) <= compose.TITLE_W and r["title"].endswith("…")
    assert r["next"] == ""   # 「내일」 상대 시점어 금지


def test_long_name_shrinks_before_tail():
    """긴 종목 이름은 이름을 줄인다 — 10/12 「ACE K휴머노이드로봇산업TOP2+ 8,970 · 내…」 방향이 잘렸다."""
    ev = dict(EV["U1"], title="{name} {value} · 내 조건 {dir_ko}")
    h = Hit(target="0177X0", dir="down", value=8970, unit="", asOf="2026-10-12", fresh="live",
            fields={"name": "ACE K휴머노이드로봇산업TOP2+", "dir_ko": "아래로"})
    r = compose.render(ev, h, None, today=dt.date(2026, 10, 12))
    assert r["title"].endswith("… 8,970 · 내 조건 아래로") and r["title"].startswith("K휴머노")   # 운용사 이름 뺀 뒤 이름만 줄인다(꼬리 보존)
    assert compose.width(r["title"]) <= compose.TITLE_W
    stale = Hit(target="0177X0", dir="down", value=8970, unit="", asOf="2026-10-10", fresh="prev",
                fields={"name": "ACE K휴머노이드로봇산업TOP2+", "dir_ko": "아래로"})
    t = compose.render(ev, stale, None, today=dt.date(2026, 10, 12))["title"]
    assert t.startswith("K휴머노") and t.endswith("내 조건 아래로") and compose.width(t) <= compose.TITLE_W, t   # 운용사 이름을 빼고 이름만 줄인다


def test_long_title_shortens_name_first():
    """길면 이름을 먼저 줄이고 다른 변수(값 · 조건 방향)는 남긴다 — 끝을 자르면 「· 내 조건 아래로」가 「· 내…」가 됐다
    (2026-10-12 0177X0). 사전 사건 · 사용자 조건 같은 길."""
    ev = {"id": "U1", "level": "alert", "title": "{name} {value} · 내 조건 {dir_ko}", "why": ["내 조건"], "next": [],
          "url": "#/i/{target}"}
    h = Hit(target="0177X0", dir="down", value=8970.0, unit="", asOf="2026-10-12", fresh="live",
            fields={"name": "ACE K휴머노이드로봇산업TOP2+", "dir_ko": "아래로"})
    r = compose.render(ev, h, None, today=dt.date(2026, 10, 12))
    assert r["title"] == "K휴머노… 8,970 · 내 조건 아래로" and compose.width(r["title"]) <= compose.TITLE_W
    assert r["name"] == "ACE K휴머노이드로봇산업TOP2+"                      # 줄인 이름은 제목에만
    h.fields["name"] = "코스피"
    assert compose.render(ev, h, None, today=dt.date(2026, 10, 12))["title"] == "코스피 8,970 · 내 조건 아래로"
    # 이름을 두 글자까지 줄여도 넘치면 종전처럼 끝을 자른다
    ev2 = dict(ev, title="{name} " + "가" * 40)
    r = compose.render(ev2, h, None, today=dt.date(2026, 10, 12))
    assert compose.width(r["title"]) <= compose.TITLE_W and r["title"].startswith("코스피 ") and r["title"].endswith("…")


def test_brief_level_allows_48():
    ev = dict(EV["A1"], level="brief", title="{name} " + "가" * 44)
    h = Hit(target="kospi", dir="up", value=1, unit="", asOf="2026-10-02", fresh="live", fields={"name": "코스피"})
    assert len(compose.render(ev, h, None, today=TODAY)["title"]) == 48


def test_brief_push_keeps_wide_first_fact_in_body():
    """제목에 못 든 아침 브리핑 첫 사실은 본문 맨 앞에 남는다(P2 검토 지적)."""
    from alerts_v2 import briefing
    t, b = briefing.push_text("11/6 아침 · 매우매우긴이름의지표가여기에들어갑니다 -4.4%", ["z"], "morning")
    assert t == "아침 브리핑" and b.startswith("매우매우긴") and compose.width(b) <= compose.BODY_W
    assert compose.fit_title([], {}) == ""
