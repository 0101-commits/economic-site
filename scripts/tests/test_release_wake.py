"""발표 직후 알림(알림 개편 P4) — 한국 소비자물가 보도자료 빠른 채움 · Worker 가 깨울 발표 시각 목록.

11/3 한국 CPI(08:00)는 나스닥이 12:07 에야 발표값을 올리고 ECOS 는 그날 새 달이 없어 발표 결과 알림이 4시간 늦었다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import check_releases  # noqa: E402
import fetch_data as F  # noqa: E402

KST = dt.timezone(dt.timedelta(hours=9))

BOARD = """<ul><li><a href="javascript:addSearchParam('/board.es?mid=a10301040100&bid=213&act=view&list_no=447801&tag=&nPage=1');">
<span class="new">새글</span> 2026년 10월 소비자물가동향</a></li>
<li><a href="javascript:addSearchParam('/board.es?mid=a10301040100&bid=213&act=view&list_no=447322&tag=&nPage=1');">2026년 9월 소비자물가동향</a></li></ul>"""
VIEW = ("<div>게시일 2026-11-03</div><div class='view'><p>□ 10월 소비자물가지수는 전월대비 0.2%, "
        "전년동월대비 2.8% 각각 상승</p><p>□ 식료품및에너지제외지수는 전월대비 0.4%, 전년동월대비 2.8% 각각 상승</p></div>")


def _ev(**kw):
    e = {"dt": "11.03 08:00", "cc": "KR", "name": "한국 소비자물가동향", "stars": 3, "prev": "+2.9%", "fore": "+2.9%",
         "act": "", "iso": "2026-11-03", "refPeriod": "2026-10"}
    e.update(kw)
    return e


def _get(calls):
    def get(url):
        calls.append(url)
        return VIEW if "list_no=447801" in url else BOARD
    return get


def test_fills_yoy_after_release_from_press_board():
    calls, ev = [], [_ev()]
    n = F.fill_kostat_cpi_act(ev, now=dt.datetime(2026, 11, 3, 8, 3, tzinfo=KST), get=_get(calls))
    assert n == 1 and ev[0]["act"] == "+2.8%" and ev[0]["actSrc"] == F.KOSTAT_ACT_SRC
    assert any("list_no=447801" in u for u in calls)          # 10월분 글을 열었다(9월분이 아니라)


def test_waits_until_release_time_and_skips_filled_or_other_days():
    calls = []
    early = [_ev()]
    assert F.fill_kostat_cpi_act(early, now=dt.datetime(2026, 11, 3, 7, 59, tzinfo=KST), get=_get(calls)) == 0
    assert early[0]["act"] == "" and not calls                # 발표 전엔 묻지도 않는다
    done = [_ev(act="+2.8%", actSrc="나스닥 경제 일정")]
    assert F.fill_kostat_cpi_act(done, now=dt.datetime(2026, 11, 3, 9, 0, tzinfo=KST), get=_get(calls)) == 0
    other = [_ev(iso="2026-10-02", refPeriod="2026-09")]
    assert F.fill_kostat_cpi_act(other, now=dt.datetime(2026, 11, 3, 9, 0, tzinfo=KST), get=_get(calls)) == 0
    assert not calls


def test_carries_previous_run_without_fetching_again():
    calls, ev = [], [_ev()]
    prev = [_ev(act="+2.8%", actSrc=F.KOSTAT_ACT_SRC)]
    assert F.fill_kostat_cpi_act(ev, prev, now=dt.datetime(2026, 11, 3, 9, 7, tzinfo=KST), get=_get(calls)) == 1
    assert ev[0]["act"] == "+2.8%" and not calls


def test_missing_post_or_failed_fetch_leaves_act_empty():
    ev = [_ev(refPeriod="2026-11", iso="2026-11-03")]          # 게시판에 11월분 글이 아직 없다
    assert F.fill_kostat_cpi_act(ev, now=dt.datetime(2026, 11, 3, 8, 3, tzinfo=KST), get=_get([])) == 0
    assert ev[0]["act"] == ""

    def boom(url):
        raise OSError("down")
    ev = [_ev()]
    assert F.fill_kostat_cpi_act(ev, now=dt.datetime(2026, 11, 3, 8, 3, tzinfo=KST), get=boom) == 0
    assert ev[0]["act"] == ""


def test_yoy_phrasings():
    assert F._kostat_yoy("□ 3월 소비자물가지수는 전월대비 0.3% 하락, 전년동월대비 2.0% 상승") == 2.0
    assert F._kostat_yoy("□ 소비자물가지수는 전월대비 보합, 전년동월대비 1.1% 하락") == -1.1
    assert F._kostat_yoy("□ 소비자물가지수는 전월대비 0.1% 상승, 전년동월대비 보합") == 0.0
    assert F._kostat_yoy("<p>식료품및에너지제외지수는 전년동월대비 2.8% 상승</p>") is None   # 헤드라인 줄만


def test_wake_times_only_mapped_two_star_events_near_now():
    now = dt.datetime(2026, 11, 12, 7, 0, tzinfo=KST)
    evs = [
        {"name": "미국 CPI", "stars": 3, "iso": "2026-11-12", "dt": "11.12 22:30"},
        {"name": "미국 CPI", "stars": 3, "iso": "2026-11-12", "dt": "11.12 22:30"},          # 같은 시각은 하나
        {"name": "한국은행 금통위", "stars": 3, "iso": "2026-11-13", "dt": "11.13 09:00", "timeApprox": True},
        {"name": "모르는 지표", "stars": 3, "iso": "2026-11-12", "dt": "11.12 21:00"},       # 채울 길 없음
        {"name": "미국 CPI", "stars": 1, "iso": "2026-11-12", "dt": "11.12 20:00"},          # ★ 하나
        {"name": "미국 CPI", "stars": 3, "iso": "2026-11-12", "dt": "11.12 06:20"},          # 40분 전 — 깨움 다 지남
        {"name": "미국 CPI", "stars": 3, "iso": "2026-11-15", "dt": "11.15 22:30"},          # 36시간 밖
    ]
    names = {"미국 CPI", "한국은행 금통위"}
    assert check_releases.wake_times(evs, now, names) == ["2026-11-12T13:30Z", "2026-11-13T00:30Z"]


def test_release_due_unchanged_by_refactor():
    ev = {"iso": "2026-11-12", "dt": "11.12 22:30"}
    assert not check_releases.release_due(ev, dt.datetime(2026, 11, 12, 22, 29, tzinfo=KST))
    assert check_releases.release_due(ev, dt.datetime(2026, 11, 12, 22, 30, tzinfo=KST))
    assert not check_releases.release_due({"iso": "x"}, dt.datetime(2026, 11, 12, tzinfo=KST))
