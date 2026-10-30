"""컨센서스 붙이기(scripts/consensus.py) — 나스닥 하루 묶음의 함정(날짜 +1 · 동부 시각 · 같은 이름 두 줄 · 빈 칸)을 지킨다.

묶음은 2026-10-30 에 실제로 받은 줄을 옮겨 적었다(네트워크 없이 돈다).
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from consensus import KST, apply_consensus, pick_row, query_date  # noqa: E402


def _row(country, name, act, cons, prev, gmt="08:30"):
    return {"country": country, "eventName": name, "actual": act, "consensus": cons, "previous": prev, "gmt": gmt}


DAYS = {
    # 2026-10-14 08:30 ET 미국 CPI → 조회일 10-15. 같은 이름 두 줄(전월 0.6 · 전년 3.7)
    "2026-10-15": [_row("United States", "CPI", "3.7%", "3.6%", "3.4%"),
                   _row("United States", "CPI", "0.6%", "0.6%", "0.4%"),
                   _row("United States", "Core CPI", "0.3%", "0.2%", "0.3%")],
    # 2026-10-01 19:00 ET = 10-02 08:00 KST 한국 CPI → 조회일 10-02
    "2026-10-02": [_row("South Korea", "CPI", "2.9%", "2.9%", "3.1%", "19:00"),
                   _row("South Korea", "CPI", "0.3%", "0.4%", "0.2%", "19:00")],
    # 주택착공 — 수준 줄(M)과 % 줄
    "2026-10-21": [_row("United States", "Housing Starts", "1.221M", "1.300M", "1.288M"),
                   _row("United States", "Housing Starts", "-5.2%", "1.9%", "-5.9%")],
    # 앞으로의 회차 — 발표값 빈 칸, 컨센서스도 아직
    "2026-11-03": [_row("South Korea", "CPI", "&nbsp;", " ", "2.9%", "19:00"),
                   _row("South Korea", "CPI", "&nbsp;", " ", "0.3%", "19:00")],
    # FOMC 14:00 ET 10-28 → 10-29 03:00 KST · 조회일 10-29
    "2026-10-29": [_row("United States", "Fed Interest Rate Decision", "4.00%", "4.00%", "4.00%", "14:00")],
    # NFP
    "2026-10-03": [_row("United States", "Nonfarm Payrolls", "29K", "89K", "133K")],
}


def _fetch(q):
    return DAYS.get(q, [])


def _ev(name, iso, hm):
    return {"name": name, "iso": iso, "dt": f"{iso[5:7]}.{iso[8:10]} {hm}", "prev": "", "fore": "", "act": ""}


def test_query_date_is_us_eastern_day_plus_one():
    assert query_date(_ev("미국 CPI (전월비)", "2026-10-14", "21:30")) == "2026-10-15"
    assert query_date(_ev("한국 소비자물가동향", "2026-10-02", "08:00")) == "2026-10-02"
    assert query_date(_ev("미국 FOMC 회의", "2026-10-29", "03:00")) == "2026-10-29"
    # 서머타임이 끝난 뒤(11월 둘째 주) — 22:30 KST = 08:30 EST
    assert query_date(_ev("미국 CPI (전월비)", "2026-11-10", "22:30")) == "2026-11-11"


def test_same_name_two_rows_split_by_previous_size():
    rows = DAYS["2026-10-15"]
    assert (pick_row(rows, "United States", "cpi", "short") or {}).get("actual") == "0.6%"
    assert (pick_row(rows, "United States", "cpi", "long") or {}).get("actual") == "3.7%"
    # 한 줄만 왔으면 가르지 않는다 — 지어내지 않는다
    assert pick_row(rows[:1], "United States", "cpi", "short") is None
    assert (pick_row(DAYS["2026-10-21"], "United States", "housing starts", "level") or {}).get("actual") == "1.221M"


def test_apply_full_run_fills_and_formats():
    now = datetime(2026, 10, 30, 9, 5, tzinfo=KST)
    evs = [_ev("미국 CPI (전월비)", "2026-10-14", "21:30"),
           _ev("한국 소비자물가동향", "2026-10-02", "08:00"),
           _ev("미국 주택착공 (Housing Starts)", "2026-10-20", "21:30"),
           _ev("미국 FOMC 회의", "2026-10-29", "03:00"),
           _ev("미국 비농업고용(NFP)", "2026-10-02", "21:30"),
           _ev("한국 소비자물가동향", "2026-11-03", "08:00"),
           _ev("한국 고용동향", "2026-10-16", "08:00")]          # 짝 없는 일정은 건드리지 않는다
    evs[0]["act"] = "+0.7%"                                       # FRED 직접 계산값 → 공식 발표값으로 바뀐다
    st = apply_consensus(evs, [], full=True, now=now, fetch=_fetch, pause=0)
    cpi, kr, hs, fomc, nfp, kr_next, emp = evs
    assert (cpi["prev"], cpi["fore"], cpi["act"]) == ("+0.4%", "+0.6%", "+0.6%")
    assert (kr["prev"], kr["fore"], kr["act"]) == ("+3.1%", "+2.9%", "+2.9%")
    assert (hs["fore"], hs["act"]) == ("1300.0", "1221.0")
    assert (fomc["fore"], fomc["act"]) == ("4.00%", "4.00%")
    assert (nfp["prev"], nfp["fore"], nfp["act"]) == ("+133K", "+89K", "+29K")
    assert kr_next["act"] == "" and kr_next["fore"] == "" and kr_next["prev"] == "+2.9%"
    assert "consSrc" not in emp and emp["fore"] == ""
    assert cpi["consSrc"] == "나스닥 경제 일정" and cpi["actSrc"] == "나스닥 경제 일정"
    assert st["failed"] == 0 and st["filled"] == 6


def test_light_run_fetches_only_recent_and_carries_the_rest():
    now = datetime(2026, 10, 29, 4, 0, tzinfo=KST)        # FOMC(03:00) 한 시간 뒤의 일반 런
    prev = [dict(_ev("미국 CPI (전월비)", "2026-10-14", "21:30"), prev="+0.4%", fore="+0.6%", act="+0.6%",
                 consSrc="나스닥 경제 일정", actSrc="나스닥 경제 일정", consAt="2026-10-29T22:05+09:00")]
    evs = [_ev("미국 CPI (전월비)", "2026-10-14", "21:30"), _ev("미국 FOMC 회의", "2026-10-29", "03:00")]
    evs[0]["act"] = "+0.7%"
    calls = []
    st = apply_consensus(evs, prev, full=False, now=now, fetch=lambda q: calls.append(q) or _fetch(q), pause=0)
    assert calls == ["2026-10-29"]                     # 6시간 안의 FOMC 만 새로 받는다
    assert (evs[0]["fore"], evs[0]["act"]) == ("+0.6%", "+0.6%")   # 나머지는 직전 값을 잇는다
    assert evs[1]["fore"] == "4.00%" and st["carried"] == 1


def test_fetch_failure_stops_and_keeps_carry():
    now = datetime(2026, 10, 30, 9, 5, tzinfo=KST)

    def boom(_q):
        raise OSError("403 Forbidden")
    evs = [_ev("미국 CPI (전월비)", "2026-10-14", "21:30")]
    st = apply_consensus(evs, [], full=True, now=now, fetch=boom, pause=0)
    assert st["failed"] == 1 and st["requests"] == 1 and "403" in st["error"]
    assert evs[0]["fore"] == ""


def test_blocked_stops_but_timeout_skips_and_newest_first():
    now = datetime(2026, 10, 30, 9, 5, tzinfo=KST)
    evs = [_ev("미국 CPI (전월비)", "2026-10-14", "21:30"), _ev("한국 소비자물가동향", "2026-10-02", "08:00")]
    calls = []

    def flaky(q):
        calls.append(q)
        if q == "2026-10-15":
            raise TimeoutError("timed out")
        return _fetch(q)
    st = apply_consensus(evs, [], full=True, now=now, fetch=flaky, pause=0)
    assert calls == ["2026-10-15", "2026-10-02"]          # 새 날짜부터 · 시간 초과는 건너뛰고 이어 간다
    assert evs[1]["fore"] == "+2.9%" and st["failed"] == 1
    calls.clear()

    def blocked(q):
        calls.append(q)
        raise OSError("HTTP Error 429: Too Many Requests")
    apply_consensus([_ev("미국 CPI (전월비)", "2026-10-14", "21:30"), _ev("한국 소비자물가동향", "2026-10-02", "08:00")],
                    [], full=True, now=now, fetch=blocked, pause=0)
    assert calls == ["2026-10-15"]                         # 막히면 그 런은 멈춘다


def test_blank_consensus_keeps_previous_and_tie_is_not_guessed():
    now = datetime(2026, 11, 2, 9, 5, tzinfo=KST)
    prev = [dict(_ev("한국 소비자물가동향", "2026-11-03", "08:00"), fore="+2.7%", consSrc="나스닥 경제 일정")]
    evs = [_ev("한국 소비자물가동향", "2026-11-03", "08:00")]
    apply_consensus(evs, prev, full=True, now=now, fetch=_fetch, pause=0)
    assert evs[0]["fore"] == "+2.7%" and evs[0]["prev"] == "+2.9%"
    tie = [_row("United States", "CPI", "0.3%", "0.3%", "0.3%"), _row("United States", "CPI", "0.3%", "0.2%", "0.3%")]
    assert pick_row(tie, "United States", "cpi", "short") is None


def test_history_harvest_stats_and_backfill_cursor():
    from consensus import update_history
    now = datetime(2026, 10, 30, 9, 5, tzinfo=KST)
    # 일반 런: 받은 묶음에서만 거둔다(거꾸로 훑기 없음)
    hist, st = update_history(None, {"2026-10-15": DAYS["2026-10-15"]}, full=False, now=now, fetch=_fetch, pause=0)
    s = hist["series"]
    assert [x["a"] for x in s["미국 CPI (전월비)"]] == [0.6] and [x["c"] for x in s["미국 CPI (전년비)"]] == [3.6]
    assert hist["stats"]["미국 CPI (전년비)"] == {"n": 1, "meanAbs": 0.1, "above": 1, "same": 0, "below": 0, "unit": "%"}
    assert hist["scannedTo"] is None and st["requests"] == 0
    # 일일 런: 오늘부터 거꾸로 120일을 훑고, 다음 일일 런은 그 아래부터 잇는다
    calls = []
    hist2, st2 = update_history(hist, {}, full=True, now=now, fetch=lambda q: calls.append(q) or _fetch(q), pause=0)
    assert calls[0] == "2026-10-30" and len(calls) == 120 and hist2["scannedTo"] == calls[-1]
    assert [x["q"] for x in hist2["series"]["한국 소비자물가동향"]] == ["2026-10-02"]
    assert hist2["series"]["미국 비농업고용(NFP)"][0]["a"] == 29 and hist2["series"]["미국 주택착공 (Housing Starts)"][0]["a"] == 1221
    calls.clear()
    hist3, _ = update_history(hist2, {}, full=True, now=now, fetch=lambda q: calls.append(q) or [], pause=0)
    assert calls[0] < hist2["scannedTo"] and hist3["series"]["미국 CPI (전월비)"][0]["q"] == "2026-10-15"   # 기록은 남는다
    # 1년 넘게 훑었으면 더 묻지 않는다
    done = dict(hist3, scannedTo="2025-09-01")
    calls.clear()
    update_history(done, {}, full=True, now=now, fetch=lambda q: calls.append(q) or [], pause=0)
    assert calls == []
