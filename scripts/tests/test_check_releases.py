"""A3 releases-calendar 회귀 테스트 (오프라인).

발표 시각 가드(release_due) · 일정표 이름 → 지표 잎 연결 · FRED release_id 표 · 연준 FOMC 일정(KST 변환) ·
act 백필의 기준기간 가드 · slot_line_ok 의 일정표 대조.
실행: python -m pytest scripts/tests/test_check_releases.py
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ai_briefing as ab  # noqa: E402
import check_releases as cr  # noqa: E402
import fetch_data as fd  # noqa: E402

KST = timezone(timedelta(hours=9))
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _json(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return json.load(f)


def _fix(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def at(d, h, m=0):
    return datetime(2026, 10, d, h, m, tzinfo=KST)


# ── 1. 발표 시각 가드 ──────────────────────────────────────────────────────────
IP = {"iso": "2026-10-02", "dt": "10.02 22:15", "cc": "US", "name": "X", "stars": 3, "act": "+0.4%", "fore": "+0.1%"}


def _sent(ev, now):
    return [e["name"] for e, _ in cr.collect({"economicCalendar": {"events": [ev]}}, ev["iso"], now)]


def test_release_not_sent_before_its_time_2026_10_02_repro():
    # 실측: 일정 22:15 인 결과 알림이 같은 날 00:11 에 나갔다(act 는 발표일 00시부터 직전 관측치로 채워진다)
    assert _sent(IP, at(2, 0, 11)) == []
    assert _sent(IP, at(2, 22, 14)) == []
    assert _sent(IP, at(2, 22, 15)) == ["X"] and _sent(IP, at(2, 22, 16)) == ["X"]


def test_time_approx_waits_30_more_minutes_and_missing_time_waits_for_9am():
    ev = dict(IP, iso="2026-10-22", dt="10.22 09:00", timeApprox=True)
    assert not cr.release_due(ev, at(22, 9, 29)) and cr.release_due(ev, at(22, 9, 30))
    assert cr.release_due(dict(ev, timeApprox=False), at(22, 9, 0))
    nt = dict(IP, iso="2026-10-22", dt="")
    assert not cr.release_due(nt, at(22, 8, 59)) and cr.release_due(nt, at(22, 9, 0))
    assert not cr.release_due(dict(IP, iso="2026-10-03"), at(2, 23, 0))          # 다음 날 일정
    assert cr.release_due(IP, datetime(2026, 10, 2, 22, 16))                     # naive 는 KST 로
    assert cr.release_due(IP, datetime(2026, 10, 2, 13, 16, tzinfo=timezone.utc))
    assert not cr.release_due({"iso": "garbage", "dt": ""}, at(2, 23))           # 못 읽으면 보내지 않는다
    assert cr.release_due({"iso": "2026-10-02T21:30:00+09:00"}, at(2, 21, 31))   # iso 에 시각이 있으면 그것


# ── 2. FRED release_id 표 · 시각 변환 ──────────────────────────────────────────
def test_fred_release_table_matches_the_measured_ids():
    # 2026-10-05 FRED 사이트로 실측: 10 CPI · 50 Employment Situation · 9 Retail · 53 GDP · 54 Personal Income and
    # Outlays · 46 PPI · 13 G.17 · 27 New Residential Construction. 옛 표의 11(=ECI)·14(=G.19)·15(=G.5)·18(=H.15)·151 은 틀렸다.
    t = fd.FRED_KEY_RELEASES
    assert {k: v[1] for k, v in t.items()} == {
        10: "미국 CPI (전월비)", 50: "미국 비농업고용(NFP)", 9: "미국 소매판매", 53: "미국 GDP", 54: "미국 PCE 물가지수",
        46: "미국 PPI", 13: "미국 산업생산", 27: "미국 주택착공 (Housing Starts)"}
    assert not {11, 14, 15, 18, 151} & set(t)


def test_us_et_to_kst_follows_daylight_saving():
    f = fd._us_et_kst
    assert f(date(2026, 10, 2), "08:30") == (date(2026, 10, 2), "21:30")          # EDT
    assert f(date(2026, 11, 6), "08:30") == (date(2026, 11, 6), "22:30")          # EST (11/1 종료)
    assert f(date(2026, 11, 17), "09:15") == (date(2026, 11, 17), "23:15")
    assert f(date(2026, 10, 28), "14:00") == (date(2026, 10, 29), "03:00")        # FOMC — 다음 날 새벽
    assert f(date(2026, 12, 9), "14:00") == (date(2026, 12, 10), "04:00")
    assert not fd._us_dst(date(2026, 3, 7)) and fd._us_dst(date(2026, 3, 8))
    assert fd._us_dst(date(2026, 10, 31)) and not fd._us_dst(date(2026, 11, 1))


def test_fred_events_carry_kst_time_by_release(monkeypatch):
    monkeypatch.setattr(fd, "FRED_API_KEY", "x")
    monkeypatch.setattr(fd, "log", lambda *a, **k: None)
    monkeypatch.setattr(fd, "fetch_fred_release_dates",
                        lambda rid, **k: {50: [{"date": "2026-10-02"}, {"date": "2026-11-06"}], 13: [{"date": "2026-11-17"}]}.get(rid))
    ev = {(e["name"], e["iso"]): e for e in fd.fetch_economic_calendar()["events"]}
    assert ev[("미국 비농업고용(NFP)", "2026-10-02")]["dt"] == "10.02 21:30"          # NFP 는 10/2(첫 금요일) — 10/30 은 ECI(release 11)였다
    assert ev[("미국 비농업고용(NFP)", "2026-11-06")]["dt"] == "11.06 22:30"          # 서머타임 종료 뒤 1시간 늦다
    assert ev[("미국 산업생산", "2026-11-17")]["dt"] == "11.17 23:15" and len(ev) == 3


def test_fomc_page_parser_gives_kst_dates_and_keeps_us_date():
    ev = fd._parse_fomc(_fix("fomc_calendars.html"))
    assert [e["usDate"] for e in ev] == ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29",
                                         "2026-09-16", "2026-10-28", "2026-12-09",
                                         "2027-01-27", "2027-03-17", "2027-04-28"]
    by = {e["usDate"]: e for e in ev}
    assert (by["2026-10-28"]["iso"], by["2026-10-28"]["dt"]) == ("2026-10-29", "10.29 03:00")
    assert (by["2026-12-09"]["iso"], by["2026-12-09"]["dt"]) == ("2026-12-10", "12.10 04:00")
    assert by["2026-03-18"]["dt"] == "03.19 03:00"                                # 3/8 서머타임 시작 뒤
    assert all(e["name"] == "미국 FOMC 회의" and e["cc"] == "US" and e["stars"] == 3 for e in ev)
    assert fd._parse_fomc("<html>no sections</html>") == []
    two = ('<h4><a id="1">2030 FOMC Meetings</a></h4><div class="fomc-meeting__month"><strong>Oct/Nov</strong></div>'
           '<div class="fomc-meeting__date">31-1</div>')
    assert [e["usDate"] for e in fd._parse_fomc(two)] == ["2030-11-01"]            # 달을 넘으면 뒤 달


# ── 3. 일정표 이름 → 지표 잎 ──────────────────────────────────────────────────
# 짝이 되는 잎이 없어 비워 둔 일정 — 라벨(전산업생산 · 취업자 증감)과 값(광공업생산 · 실업률)의 헤드라인이 다르다.
UNPAIRED = {"한국 산업활동동향", "한국 고용동향"}


def test_every_calendar_name_is_mapped_or_explicitly_unpaired():
    names = {e["name"] for fx, fn in (("bok_mpc_2026.html", fd._parse_bok_mpc), ("ecb_mgcgc.html", fd._parse_ecb_mpm),
                                      ("boj_mpmsche.html", fd._parse_boj_mpm), ("fomc_calendars.html", fd._parse_fomc),
                                      ("kostat_newspln_all.html", fd._parse_kostat_plan)) for e in fn(_fix(fx))}
    assert len(names) == 7, names                                                  # 이름이 늘면 짝을 다시 따져라
    assert {n for n in names if n not in fd.CALENDAR_INDICATOR_MAP} == UNPAIRED
    assert {"한국 소비자물가동향", "한국은행 금통위 (통화정책방향)", "ECB 통화정책 결정",
            "일본은행(BOJ) 금융정책결정회합", "미국 FOMC 회의"} <= set(fd.CALENDAR_INDICATOR_MAP)
    assert set(fd.CAL_DECISION_NAMES) <= set(fd.CALENDAR_INDICATOR_MAP)


def test_mapped_leaves_exist_in_registry_and_economic_indicators():
    reg = {r.get("dataPath") for r in _json("bundles", "registry.json")["rows"]}
    data = _json("data.json")
    for name, (path, fmt, _lower) in fd.CALENDAR_INDICATOR_MAP.items():
        node = fd._get_by_path(data, path)
        assert isinstance(node, dict) and node.get("history"), (name, path)       # 잎이 있고 history 가 있다
        if path.startswith("economicIndicators."):
            assert path in reg, (name, path)                                       # 지표 레지스트리에도 있다


# ── 4. 백필 — 기준기간·결정 당월 가드 ──────────────────────────────────────────
def _months(start_y, start_m, n, f):
    out, y, m = {}, start_y, start_m
    for i in range(n):
        out[f"{y}{m:02d}"] = f(i)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _ev(name, iso, **kw):
    return dict({"name": name, "iso": iso, "dt": iso[5:7] + "." + iso[8:] + " 08:00", "act": "", "prev": "", "fore": "",
                 "beat": None}, **kw)


def test_backfill_uses_only_the_reference_month_for_korean_cpi(monkeypatch):
    monkeypatch.setattr(fd, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: datetime(2026, 10, 5, tzinfo=KST))}))
    hist = _months(2025, 8, 14, lambda i: 100.0 + i)                               # 202508 ~ 202609
    ev = _ev("한국 소비자물가동향", "2026-10-02", refPeriod="2026-09")
    fd.backfill_calendar_actuals([ev], {"economicIndicators": {"kr": {"cpi_kr": {"history": hist}}}})
    assert ev["act"] == "+11.9%" and ev["prev"] == "+12.0%"                         # 202609 vs 202509 (전년동월비)
    old = dict(hist)
    del old["202609"]                                                              # 9월분이 아직 안 들어왔다
    ev2 = _ev("한국 소비자물가동향", "2026-10-02", refPeriod="2026-09")
    fd.backfill_calendar_actuals([ev2], {"economicIndicators": {"kr": {"cpi_kr": {"history": old}}}})
    assert ev2["act"] == ""                                                        # 8월분을 9월 실적으로 찍지 않는다


def test_backfill_policy_decision_needs_an_observation_of_the_decision_month(monkeypatch):
    monkeypatch.setattr(fd, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: datetime(2026, 10, 23, tzinfo=KST))}))
    name = "한국은행 금통위 (통화정책방향)"
    data = {"economicIndicators": {"kr": {"base_rate_kr": {"history": {"202608": 3.0, "202609": 3.0}}}}}
    ev = _ev(name, "2026-10-22")
    fd.backfill_calendar_actuals([ev], data)
    assert ev["act"] == ""                                                         # 9월 금리를 10/22 결정으로 보이지 않는다
    data["economicIndicators"]["kr"]["base_rate_kr"]["history"]["202610"] = 2.75
    ev = _ev(name, "2026-10-22")
    fd.backfill_calendar_actuals([ev], data)
    assert ev["act"] == "2.75%" and ev["fore"] == "3.00%"


# ── 5. slot_line_ok — 일정표 대조 ──────────────────────────────────────────────
CAL = {"events": [
    {"iso": "2026-10-14", "dt": "10.14 21:30", "name": "미국 CPI (전월비)", "stars": 3},
    {"iso": "2026-10-16", "dt": "10.16 08:00", "name": "한국 고용동향", "stars": 2},
]}


def test_slot_line_ok_checks_today_and_dated_announcements_against_the_calendar():
    now = at(14, 15)
    assert ab.slot_line_ok("오늘 미국 CPI 발표를 앞두고 달러가 강세다", CAL, now)
    assert not ab.slot_line_ok("오늘 미국 PPI 발표를 앞두고 달러가 강세다", CAL, now)       # 오늘 PPI 일정 없음
    assert not ab.slot_line_ok("오늘 미국 CPI 발표를 앞두고 달러가 강세다", {"events": []}, now)  # 오늘 일정 자체가 없다
    assert not ab.slot_line_ok("10월 15일 미국 CPI 발표를 앞두고 달러가 강세다", CAL, now)    # 날짜가 어긋난다
    assert ab.slot_line_ok("10월 14일 미국 CPI 발표를 앞두고 달러가 강세다", CAL, now)
    assert not ab.slot_line_ok("내일 미국 CPI 발표가 있다 달러가 강세다", CAL, now)           # 상대 시점어는 늘 금지


def test_slot_line_ok_drops_announcements_whose_time_has_already_passed():
    late = at(14, 22, 5)                                                           # 21:30 발표 뒤
    assert not ab.slot_line_ok("오늘 미국 CPI 발표를 앞두고 달러가 강세다", CAL, late)      # 이미 나왔다
    assert ab.slot_line_ok("오늘 발표된 미국 CPI 가 예상보다 높아 달러가 강세다", CAL, late)
    assert not ab.slot_line_ok("오늘 발표된 미국 CPI 가 예상보다 높아 달러가 강세다", CAL, at(14, 15))  # 아직 안 나왔다
    # 일정표를 안 주면 종전 그대로(길이·시점어·권유만)
    assert ab.slot_line_ok("오늘 미국 PPI 발표를 앞두고 달러가 강세다")
    assert ab.slot_line_ok("코스피가 반도체 강세로 2.5% 올랐고 발표 영향은 제한적", CAL, at(14, 15))   # 소수점은 날짜가 아니다
