#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""알림 개편(2026-09-24) 게이트 — 제목·신선도·휴장·버튼·AI 문장·이례 범위.

test_readability.py 가 '카드가 읽히는가'를 본다면 이 파일은 '글이 맞는 말을 하는가'를 본다.
전부 네트워크 없이 돈다(수급·AI 는 스텁). 시각은 발송 코드가 datetime.now 를 쓰므로
픽스처도 오늘 날짜로 만든다.

실행: python -m pytest scripts/tests/test_alert_redesign.py -q
"""
import copy
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import ai_briefing as ab           # noqa: E402
import discord_card as dc         # noqa: E402
import send_kakao_digest as k     # noqa: E402

NOW = datetime.datetime.now(k.KST)
TODAY = NOW.strftime("%Y-%m-%d")
YDAY = (NOW - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
OLD = (NOW - datetime.timedelta(days=2)).strftime("%Y-%m-%d")


def _hist(n=260, base=100.0, step=0.3):
    out, v = [], base
    for i in range(n):
        v *= 1 + (step if i % 2 else -step) / 100
        out.append({"date": (NOW - datetime.timedelta(days=n - i)).strftime("%Y-%m-%d"), "close": v})
    return out


def _data(open_today=True):
    """평범한 날 픽스처 — 모든 등락이 σ 안쪽(이례 0건)."""
    d = {
        "indices": {"KOSPI": {"price": 3000.0, "change": 0.2}, "KOSDAQ": {"price": 850.0, "change": -0.1},
                    "SP500": {"price": 6000.0, "change": 0.1}, "NASDAQ": {"price": 20000.0, "change": 0.2},
                    "SOX": {"price": 5000.0, "change": 0.3}, "Nikkei": {"price": 40000.0, "change": 0.1},
                    "Shanghai": {"price": 3300.0, "change": 0.0}},
        "fx": {"USDKRW": {"rate": 1380.0, "change": 0.1}, "USDJPY": {"rate": 150.0, "change": 0.0},
               "EURUSD": {"rate": 1.1, "change": 0.0}},
        "commodities": {"WTI": {"price": 70.0, "change": 0.2}, "Copper": {"price": 4.5, "change": 0.1},
                        "Gold": {"price": 2500.0, "change": 0.0}},
        "history": {"indices": {k_: _hist() for k_ in ("KOSPI", "KOSDAQ", "SP500", "NASDAQ", "SOX", "Nikkei")},
                    "fx": {k_: _hist(step=0.2) for k_ in ("USDKRW", "USDJPY")},
                    "commodities": {k_: _hist(step=1.0) for k_ in ("WTI", "Copper", "Gold")}},
        "yieldCurve": {"us": {"series": [{"tenor": "10Y", "data": [{"date": OLD, "value": 4.2},
                                                                    {"date": YDAY, "value": 4.2}]},
                                         {"tenor": "2Y", "data": [{"date": YDAY, "value": 3.9}]}]},
                       "kr": {"series": [{"tenor": "10Y", "data": [{"date": OLD, "value": 3.0},
                                                                    {"date": OLD, "value": 3.0}]}]}},
        "sentiment": {},
        "marketCalendarKr": {"today": {"date": TODAY, "open": open_today},
                             "previousBusinessDay": {"date": YDAY, "open": True}},
    }
    return d


def _no_net(monkeypatch):
    monkeypatch.setattr(k, "_verified_investor", lambda market="KOSPI": None)
    monkeypatch.setattr(ab, "slot_line", lambda *a, **kw: "")


# ── G1 제목 = 결론 ─────────────────────────────────────────────────────────
def test_titles_differ_by_slot_and_name_an_asset(monkeypatch):
    _no_net(monkeypatch)
    d = _data()
    titles = []
    for slot in ("h07", "h09", "h19", "h22"):
        base = k.build_digest_parts(d, slot=slot)[0]
        t, _hit = k.headline(d, slot, False, NOW, base=base)
        titles.append(t)
        assert "시 시황" not in t, t                               # 시각 제목 폐지
        assert " · " in t, f"결론이 없는 제목: {t}"
        assert len(t) <= k.TITLE_MAX, t
    assert len(set(titles)) == len(titles), titles


def test_headline_names_market_wide_anomaly_once_per_day(monkeypatch):
    """카드 키가 아닌 MOVE 가 튀어도 제목이 말하고, 같은 날 두 번째 통부터는 반복하지 않는다."""
    _no_net(monkeypatch)
    d = _data()
    hist = {(NOW - datetime.timedelta(days=300 - i)).strftime("%Y-%m-%d"): 80 + (i % 2) for i in range(300)}
    d["sentiment"]["move"] = {"value": 100.0, "change": 20.0, "as_of": TODAY, "history": hist}
    t1, hit = k.headline(d, "h07", False, NOW)
    assert "채권변동성" in t1 and hit and hit[0] == "MOVE", t1
    t2, hit2 = k.headline(d, "h09", False, NOW, seen={hit[0]: hit[1]})
    assert "채권변동성" not in t2 and hit2 is None, t2


# ── G3 신선도 꼬리표 ────────────────────────────────────────────────────────
def test_stale_yield_tile_carries_date_and_live_tile_does_not():
    d = _data()
    assert dc.tile_asof(d, "yield", "US10Y", NOW) == YDAY
    assert dc.stale_tag(dc.tile_asof(d, "yield", "KR10Y", NOW), NOW).startswith("·")
    d["_liveTiles"] = {"US10Y": {"value": 4.25, "change": 3}}
    assert dc.tile_asof(d, "yield", "US10Y", NOW) is None


def test_stale_yield_change_not_in_headline(monkeypatch):
    """이틀 묵은 금리의 '0bp'는 제목에 오르지 않는다(9/24 실측: 「미국채 10Y +0bp」)."""
    _no_net(monkeypatch)
    t, _ = k.headline(_data(), "h19", False, NOW)
    assert "한국채 10Y" not in t, t


# ── G5 기간 표기 단일 ───────────────────────────────────────────────────────
def test_period_labels_share_one_format():
    assert dc.period_label("2026-09-17", "2026-09-23") == "9/17~9/23"
    wk = k.build_weekly_parts({"history": {"indices": {"KOSPI": _hist()}}}, NOW)[0]
    assert wk == f"주간 시황 {dc.week_period(NOW)}"


# ── G7 버튼 라벨 ────────────────────────────────────────────────────────────
def test_kakao_quote_button_never_cut_midword():
    for name in ("코스피", "달러-원", "S&P500", "SOX 반도체"):
        t = k.quote_btn_title(name)
        assert len(t) <= k.KAKAO_BTN_MAX and not t.endswith(" 시"), t


def test_discord_link_labels_have_no_numbers():
    labels = [lab for lab, _k, _u in k.card_links(_data(), "h09", False, NOW)]
    assert labels and not [x for x in labels if "%" in x], labels


def test_alert_buttons_keep_portfolio():
    src = open(os.path.join(os.path.dirname(k.__file__), "check_alerts.py"), encoding="utf-8").read()
    assert '_btns = _btns[:2] + [("투자현황", PORTFOLIO_URL)]' in src


# ── G8 휴장 문법 ────────────────────────────────────────────────────────────
def test_holiday_marks_body_title_and_tiles(monkeypatch):
    _no_net(monkeypatch)
    d = _data(open_today=False)
    blocks = dict(k.build_digest_parts(d, slot="h09")[1])
    tail = f"({int(YDAY[5:7])}/{int(YDAY[8:10])} 마감)"
    assert blocks["국내증시"].endswith(tail), blocks["국내증시"]
    t, _ = k.headline(d, "h09", False, NOW)
    if NOW.weekday() < 5:
        assert "휴장" in t, t
    assert dc.tile_asof(d, "indices", "KOSPI", NOW) == YDAY


# ── G9 AI 문장 ──────────────────────────────────────────────────────────────
def test_slot_line_rejects_relative_time_and_advice():
    assert ab.slot_line_ok("코스피가 반도체 강세로 0.9% 올랐다")
    assert not ab.slot_line_ok("내일 장중 확인이 필요하다")
    assert not ab.slot_line_ok("연휴 이후 채권시장 방향성을 볼 것")
    assert not ab.slot_line_ok("가" * 90)


def test_slot_ai_fallback_skips_stale_sentences(monkeypatch):
    monkeypatch.setattr(ab, "slot_line", lambda *a, **kw: "")
    d = _data()
    d["aiBriefing"] = {"date": TODAY, "lines": ["내일 장중 지표를 확인해야 합니다", "원화 약세가 이어졌다"]}
    assert k.slot_ai_line(d, "h09", "제목", []) == "원화 약세가 이어졌다"
    d["aiBriefing"]["date"] = YDAY
    assert k.slot_ai_line(d, "h09", "제목", []) == ""


# ── B5·B7·B9 ────────────────────────────────────────────────────────────────
def test_provisional_flows_only_in_midday_slot(monkeypatch):
    monkeypatch.setattr(k, "_verified_investor", lambda market="KOSPI": {
        "date": TODAY, "foreign": -100.0, "inst": 50.0, "confirmed": False, "reason": "잠정 · 토스 단독"})
    assert "잠정" in dict(k.build_digest_parts(_data(), slot="h12")[1]).get("수급", "")
    assert "수급" not in dict(k.build_digest_parts(_data(), slot="h19")[1])


def test_kr_option_expiry_is_second_thursday():
    assert k.kr_events(datetime.date(2026, 10, 8))[0]["name"] == "옵션 만기"
    assert k.kr_events(datetime.date(2026, 12, 10))[0]["stars"] == 3
    assert k.kr_events(datetime.date(2026, 10, 15)) == []


def test_close_movers_drop_listing_day_and_kosdaq():
    rows = [{"name": "신규상장", "chg": 280.8, "market": "KOSDAQ"}, {"name": "코스닥주", "chg": 12.0, "market": "KOSDAQ"},
            {"name": "정상", "chg": 9.1, "market": "KOSPI"}, {"name": "표기없음", "chg": -8.0}]
    assert [r["name"] for r in k._kospi_movers(rows)] == ["정상", "표기없음"]


# ── G4 한 카드 한 숫자(마감) ───────────────────────────────────────────────
def test_close_card_states_kospi_change_once(monkeypatch):
    texts = []

    def grab(fig, name):
        texts.extend(t.get_text() for t in fig.findobj(match=lambda o: hasattr(o, "get_text")))
        return name
    monkeypatch.setattr(dc, "_save", grab)
    xs = [NOW.replace(hour=9) + datetime.timedelta(minutes=5 * i) for i in range(40)]
    ys = [2520 + i * 0.2 for i in range(40)]                  # 마지막 점 2527.8 → 체인 기준 +0.11%
    dc.close_report([("코스피", 2548.9, 0.93), ("코스닥", 816.6, 0.38)], NOW,
                    intraday=(xs, ys, 2525.0, "토스"))
    pcts = {t for t in texts if t.endswith("%") and ("0.93" in t or "0.11" in t)}
    assert not [t for t in pcts if "0.11" in t], pcts


# ── 리뷰 지적 회귀(2026-09-24) ─────────────────────────────────────────────
def test_malformed_news_and_history_do_not_raise():
    d = _data()
    d["news"] = {"주식": {"oops": 1}, "외환": [None, "x", {"title": "t"}]}
    d["history"]["indices"]["KOSPI"] = ["bad", None]
    assert k.slot_news(d, "h09", "KOSPI", 1) == [] or isinstance(k.slot_news(d, "h09"), list)
    assert k.range_pos(d, "KOSPI") == ""


def test_slot_line_allows_net_buying_fact():
    assert ab.slot_line_ok("외국인 순매수 4,000억에 코스피 강세")
    assert not ab.slot_line_ok("지금이 매수 기회입니다")


def test_circuit_fallback_card_uses_circuit_wording(monkeypatch):
    import importlib
    import check_halts as ch
    ch = importlib.reload(ch)                 # test_check_halts 가 _status_card 를 스텁으로 덮는다
    got = {}
    # 다른 테스트가 sys.modules 의 discord_card 를 바꿔 끼우므로 '지금 import 되는 것'을 패치한다.
    monkeypatch.setattr(sys.modules["discord_card"], "status", lambda title, state, reason, **kw: got.update(
        title=title, state=state, reason=reason) or "png")
    ch._status_card({"type": "circuit", "market": "KOSPI", "stage": 1, "endOfDay": True,
                     "triggeredAt": NOW.isoformat()}, "fire")
    assert got["state"] == "매매 정지" and "당일 장 종료" in got["reason"], got
    ch._status_card({"type": "sidecar", "market": "KOSPI", "triggeredAt": NOW.isoformat()}, "fire")
    assert got["state"] == "프로그램매매 정지", got


def test_alert_lines_add_market_relative_and_next_level():
    import check_alerts as ca
    a1 = {"id": "a1", "symbol": "005930", "market": "KR", "type": "price_above", "value": 80000}
    a2 = {"id": "a2", "symbol": "005930", "market": "KR", "type": "price_above", "value": 85000}
    snaps = {("KR", "005930"): {"price": 82000, "pct": 3.0}}
    ln = ca._alert_lines([(a1, "삼성전자 82,000원(+3.0%)")], snaps, {}, NOW,
                         bench={"KR": 1.0}, alerts=[a1, a2])[0]
    assert "코스피 대비 +2.0%p" in ln and "다음 85,000원" in ln, ln
