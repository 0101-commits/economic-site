"""운영 점검(2026-10-09) — 국고채 곡선 시계열 유실 · 일정 이름 영어 괄호.

실행: python -m pytest scripts/tests/test_p3_audit.py -q
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import build_bundles as bb  # noqa: E402
import fetch_data as fd  # noqa: E402


def _s(tenor, last, **kw):
    return {"tenor": tenor, "label": tenor, "data": [{"date": "2026-10-07", "value": last - 0.01},
                                                     {"date": "2026-10-08", "value": last}], **kw}


def test_toss_current_without_candles_keeps_ecos_series():
    """2026-10-09 11:00 스냅샷 실측: 토스가 5만기 현재값은 줬는데 일봉은 30Y 만 — 2Y·5Y·10Y·20Y 의
    ECOS 시계열까지 지워져 곡선에 1Y·30Y 만 남고 kr10y 가 「자료 없음」이 됐다."""
    ecos = {"current": [None, None, None, 3.74, 3.9, None, None, 4.38, 4.41, 4.49],
            "prev_month": [None] * 10,
            "series": [_s(t, v, ecos_item="x") for t, v in (("1Y", 3.74), ("2Y", 3.9), ("10Y", 4.38),
                                                            ("20Y", 4.41), ("30Y", 4.49))],
            "source": "ECOS"}
    toss = {"current": [None, None, None, None, 3.897, 4.137, None, 4.377, 4.406, 4.489],
            "prev_month": [None, None, None, None, 3.7, 4.1, None, 4.36, 4.57, 4.63],
            "series": [_s("30Y", 4.439, toss_symbol="KR_BOND_30Y")]}
    out = fd._merge_toss_yield_curve(ecos, toss)
    by = {s["tenor"]: s for s in out["series"]}
    assert set(by) == {"1Y", "2Y", "10Y", "20Y", "30Y"}           # 일봉 없는 만기는 ECOS 시계열이 남는다
    assert by["10Y"].get("ecos_item") == "x" and by["30Y"].get("toss_symbol") == "KR_BOND_30Y"
    assert out["current"][7] == 4.377                              # 현재값은 종전대로 토스


def test_toss_series_still_replaces_ecos_when_present():
    ecos = {"current": [None] * 10, "prev_month": [None] * 10,
            "series": [{"tenor": "10Y", "data": [{"date": "2025-10-01", "value": 2.8},
                                                 {"date": "2026-10-08", "value": 4.3}]}]}
    toss = {"current": [None] * 7 + [4.377, None, None], "prev_month": [None] * 10,
            "series": [{"tenor": "10Y", "data": [{"date": "2026-01-02", "value": 3.4},
                                                 {"date": "2026-10-08", "value": 4.39}]}]}
    out = fd._merge_toss_yield_curve(ecos, toss)
    assert [s["tenor"] for s in out["series"]] == ["10Y"]
    assert [p["value"] for p in out["series"][0]["data"]] == [2.8, 3.4, 4.39]   # 앞 구간만 ECOS


def test_event_name_strips_english_gloss_only():
    cases = {
        "미국 주택착공 (Housing Starts)": "미국 주택착공",
        "미국 근원 PCE (Core PCE m/m)": "미국 근원 PCE",
        "미국 소매판매(Retail Sales)": "미국 소매판매",
        "미국 비농업고용(NFP)": "미국 비농업고용(NFP)",               # 대문자 약어는 남긴다
        "미국 FOMC 금리 결정 (FOMC)": "미국 FOMC 금리 결정 (FOMC)",
        "미국 CPI (전월비)": "미국 CPI (전월비)",                      # 우리말 괄호
        "일본은행(BOJ) 금융정책결정회합": "일본은행(BOJ) 금융정책결정회합",  # 중간 괄호
        "(Housing Starts)": "(Housing Starts)",                       # 이름이 통째로 괄호면 남긴다
        None: None,
    }
    for raw, want in cases.items():
        assert bb.event_name(raw) == want, raw


def test_calendar_bundles_use_event_name():
    import datetime as dt
    data = {"economicCalendar": {"events": [{"iso": "2026-10-20", "dt": "2026-10-20 21:30", "cc": "US",
                                             "name": "미국 주택착공 (Housing Starts)"}]}}
    now = dt.datetime(2026, 10, 9, 12, 0, tzinfo=bb.KST)
    assert bb.calendar_events(data, now)[0]["name"] == "미국 주택착공"
    assert bb.all_events(data)[0]["name"] == "미국 주택착공"


def test_lens_post_meta_covers_chain_and_edge_posts_once():
    """사슬 원문 링크 64개가 모두 「원문 열기」였다 — posts 가 최근 3편뿐이라서. postMeta 가 logNo 마다 제목·날짜를 싣는다."""
    mer = {"posts": [{"logNo": "1", "date": "2025-09-16", "title": "가"}, {"logNo": "2", "date": "2025-09-17", "title": "나"},
                     {"logNo": "3", "date": "2025-09-18", "title": "다"}],
           "graph": {"edges": [{"from": "a", "to": "b", "dir": "+", "logNos": ["2", "3"]}]},
           "chains": [{"id": "C1", "steps": [], "logNos": ["1", "2", "9"]}]}
    lens = bb.build_lens(mer)
    assert lens["postMeta"] == {"1": {"title": "가", "date": "2025-09-16"}, "2": {"title": "나", "date": "2025-09-17"},
                                "3": {"title": "다", "date": "2025-09-18"}}       # 원천에 없는 9 는 싣지 않는다
