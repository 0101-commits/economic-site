#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""구조 벤치마크 개편 자료 층(계약 docs/superpowers/specs/2026-10-14-struct-bench-plan.md C1 · C2 · C3 + F1) 검사.

C1 묶음 market — 국내 openAt · closeAt, 미국 us(장 전 · 정규 · 장 뒤 · 마감 · 휴장)
C2 meta — nextAt(Worker 크론 경계) · hashes(묶음 내용 sha1 앞 8자)
C3 AI 요약 근거 — 근거 목록 · 문장 대조(숫자 · 「발표 없음」 · 금지 낱말 · refs) · 규칙 폴백 refs · briefs 회차 파일
F1 — 발표 전 실적 칸이 찬 일정이 일정 목록에서 빠지지 않는다 · 수집기가 발표 전에 실적을 채우지 않는다
Gemini 는 가짜 응답으로만 부른다(네트워크 없음)."""
import datetime as dt
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import ai_briefing as ab  # noqa: E402
import build_bundles as bb  # noqa: E402
import fetch_data as fd  # noqa: E402

KST = bb.KST
MER = bb.load("mer_signals.json", {})
t = bb._iso_dt
CPI = {"iso": "2026-10-14", "dt": "10.14 21:30", "cc": "US", "name": "미국 CPI (전월비)", "stars": 3, "act": "+0.4%"}


def _fix_now(monkeypatch, when):
    class D(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return when
    monkeypatch.setattr(ab, "datetime", D)


# ── C1 장 상태 ──────────────────────────────────────────────────────────────
def test_us_session_states_in_kst():
    s = bb.us_session(t("2026-10-14T14:41:00+09:00"))                 # 뉴욕 01:41 수 = 장 전보다 이른 마감
    assert s == {"state": "closed", "label": "마감", "session": "2026-10-13", "openAt": "2026-10-14T22:30:00+09:00",
                 "closeAt": "2026-10-15T05:00:00+09:00", "nextOpen": "2026-10-14T22:30:00+09:00"}
    assert bb.us_session(t("2026-10-14T18:00:00+09:00"))["state"] == "pre"            # 05:00 EDT
    o = bb.us_session(t("2026-10-14T23:00:00+09:00"))                                  # 10:00 EDT 정규장
    assert (o["state"], o["session"], o["openAt"], o["nextOpen"]) == (
        "open", "2026-10-14", "2026-10-14T22:30:00+09:00", "2026-10-15T22:30:00+09:00")
    a = bb.us_session(t("2026-10-15T06:00:00+09:00"))                                  # 17:00 EDT 장 뒤 → 다음 세션
    assert (a["state"], a["openAt"], a["closeAt"]) == ("after", "2026-10-15T22:30:00+09:00", "2026-10-16T05:00:00+09:00")
    h = bb.us_session(t("2026-11-26T23:45:00+09:00"))                                  # 추수감사절
    assert h["state"] == "holiday" and h["label"] == "휴장" and h["openAt"] == "2026-11-27T23:30:00+09:00"   # 겨울 EST
    assert bb.us_session(t("2026-10-17T12:00:00+09:00"))["openAt"] == "2026-10-19T22:30:00+09:00"            # 토요일


def test_kr_open_close_and_bundle_market():
    cal = {"today": {"date": "2026-10-14", "open": True}}
    k = bb.kr_market(t("2026-10-14T14:41:00+09:00"), cal)
    assert (k["openAt"], k["closeAt"]) == ("2026-10-14T09:00:00+09:00", "2026-10-14T15:30:00+09:00")
    h = bb.kr_market(t("2026-10-09T10:00:00+09:00"), {"today": {"date": "2026-10-09", "open": False}})
    assert h["state"] == "holiday" and h["openAt"] is None and h["closeAt"] is None
    data = bb.load("data.json")
    b = bb.build_all(data, MER, t(data["lastUpdated"]).astimezone(KST))
    for name in [n for n in b if n == "home" or n.startswith("market-")]:
        m = b[name]["market"]
        assert {"state", "label", "nextOpen", "calendarKnown", "openAt", "closeAt"} <= set(m), name
        assert set(m["us"]) == {"state", "label", "session", "openAt", "closeAt", "nextOpen"}, name


# ── C2 다시 읽기 ────────────────────────────────────────────────────────────
def test_next_at_follows_worker_cron():
    hol = bb.worker_kr_holidays()
    assert "2026-10-09" in hol and "2027-02-08" in hol                                   # worker.js KR_HOLIDAYS 를 읽는다
    n = lambda s: bb.next_at(t(s), hol)
    assert n("2026-10-14T14:36:10+09:00") == "2026-10-14T14:43:00+09:00"                # 장중 = 다음 5분 칸 + 3분
    assert n("2026-10-14T15:31:00+09:00") == "2026-10-14T15:38:00+09:00"                # 마감 직후 15:35 칸
    assert n("2026-10-14T15:58:00+09:00") == "2026-10-14T16:10:00+09:00"                # 창 밖 = :07 풀 런 + 3분
    assert n("2026-10-14T16:20:00+09:00") == "2026-10-14T16:38:00+09:00"                # :35 경량 런 + 3분
    assert n("2026-10-17T12:10:00+09:00") == "2026-10-17T12:38:00+09:00"                # 주말
    assert n("2026-10-14T22:01:00+09:00") == "2026-10-14T22:08:00+09:00"                # 미국 창(UTC 13~21)
    assert n("2026-10-17T00:02:00+09:00") == "2026-10-17T00:08:00+09:00"                # 토 00시 KST = 금 UTC 15시 → 미국 창
    assert n("2026-10-09T10:00:00+09:00") == "2026-10-09T10:10:00+09:00"                # 한국 휴장일 = 창 밖
    assert n("2026-10-14T08:40:00+09:00") == "2026-10-14T09:03:00+09:00"                # 개장 첫 칸


def test_meta_hashes_are_bundle_content(tmp_path):
    data = bb.load("data.json")
    now = t(data["lastUpdated"]).astimezone(KST)
    b = bb.build_all(data, MER, now)
    bb.write(b, data, MER, now, out_dir=str(tmp_path))
    m = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    names = {k for k in b if not k.startswith("_")}
    assert set(m["hashes"]) == names and m["nextAt"] == bb.next_at(now, bb.worker_kr_holidays())
    for k in names:
        assert m["hashes"][k] == hashlib.sha1((tmp_path / (k + ".json")).read_bytes()).hexdigest()[:8], k
    later = now + dt.timedelta(seconds=30)                       # 같은 내용 · 다른 생성 시각 = 같은 지문
    bb.write(bb.build_all(data, MER, now), data, MER, later, out_dir=str(tmp_path))
    m2 = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert m2["generatedAt"] != m["generatedAt"] and m2["hashes"] == m["hashes"]


# ── C3 근거 · 대조 ─────────────────────────────────────────────────────────
def _brief_data():
    rows = [{"date": "2026-10-%02d" % d, "foreign": f, "inst": i, "src": "naver"}
            for d, f, i in ((7, 300.0, 10.0), (8, -100.0, 5.0), (12, -20103.0, -1345.0), (13, -45789.0, 16685.0),
                            (14, -11715.0, 8005.0))]
    return {"lastUpdated": "2026-10-14T14:35:00+09:00",
            "indices": {"KOSPI": {"price": 6077.57, "change": 1.19}},
            "history": {"indices": {"KOSPI": [{"date": "2026-10-14", "close": 6077.57}]}},
            "fx": {"USDKRW": {"rate": 1335.14, "change": -0.32}},
            "investorTrading": {"unit": "억원", "portalFetchedAt": "2026-10-14T14:15:00+09:00", "daily": rows},
            "news": {"주식": [{"title": "코스피, 외국인 7일째 &quot;팔자&quot;", "url": "https://news1.kr/a",
                               "pubDate": "Wed, 14 Oct 2026 13:51:00 +0900"}]},
            "economicCalendar": {"events": [CPI, {"iso": "2026-10-20", "dt": "10.20 08:00", "name": "먼 일정", "stars": 3}]}}


def test_sources_numbered_with_streak_from_rows(monkeypatch):
    now = dt.datetime(2026, 10, 14, 14, 35, tzinfo=KST)
    _fix_now(monkeypatch, now)
    d = _brief_data()
    src = ab.build_sources(d, ab.build_snapshot(d), now)
    assert [s["n"] for s in src] == list(range(1, len(src) + 1))
    by = {s["kind"]: s for s in reversed(src)}
    assert src[0] == {"n": 1, "kind": "지표", "label": "코스피 6,077.57 ▲1.19%", "at": "14:35", "_key": "KOSPI"}
    flow = next(s for s in src if s.get("_key") == "foreign")
    assert flow["label"] == "외국인 −11,715억원 · 4일 연속 순매도 · 5일 누적 −77,407억원" and flow["at"] == "14:15"   # 기사 「7일째」가 아니라 행으로 센다
    assert {k: v for k, v in by["기사"].items() if k != "n"} == {"kind": "기사", "label": "코스피, 외국인 7일째 \"팔자\"",
                                                              "src": "news1.kr", "url": "https://news1.kr/a", "at": "13:51"}
    assert by["일정"]["label"] == "미국 CPI (전월비) · 10/14(수) 21:30 · ★★★" and "먼 일정" not in str(src)


def test_count_numbers_must_match_exactly():
    """PR #170 검토: 「3거래일」이 「미국 기준금리 3.75%」 근거로 통과했다 — 개수는 정확히, 한두 자리 정수는 반올림만."""
    toks = ab._tokens("외국인이 3거래일 연속 순매도했습니다")
    assert [t[3] for t in toks] == ["count"] and not ab._num_ok(toks[0], 3.75)
    assert ab._num_ok(ab._tokens("외국인 12일 연속")[0], 12.0)
    assert not ab._num_ok(ab._tokens("3% 올랐다")[0], 3.75) and ab._num_ok(ab._tokens("4% 올랐다")[0], 3.75)
    assert ab._num_ok(ab._tokens("코스피 6,008")[0], 6008.81) and ab._num_ok(ab._tokens("1.1% 올랐다")[0], 1.17)


def test_check_drops_bad_sentences(monkeypatch):
    now = dt.datetime(2026, 10, 14, 14, 35, tzinfo=KST)
    _fix_now(monkeypatch, now)
    d = _brief_data()
    src = ab.build_sources(d, ab.build_snapshot(d), now)
    n = {s.get("_key") or s["kind"]: s["n"] for s in src}
    lines = [f"코스피가 6,078로 1.2% 올랐습니다 [{n['KOSPI']}]",                                  # 반올림 차 허용
             f"외국인이 4거래일 연속 순매도했습니다 [{n['foreign']}]",
             f"원/달러는 1,335원대에서 0.3% 내렸습니다 [{n['USDKRW']}]",
             f"코스피가 6,100로 올랐습니다 [{n['KOSPI']}]",                                         # 숫자 불일치
             f"외국인이 12일 연속 팔았습니다 [{n['foreign']}]",                                     # 근거는 4일
             f"오늘은 예정된 주요 지표 발표가 없어 수급이 관건입니다 [{n['foreign']}]",              # 오늘 일정이 근거에 있다
             f"스냅샷 기준 코스피가 올랐습니다 [{n['KOSPI']}]",                                     # 금지 낱말
             f"내일 미국 CPI 를 확인할 것 [{n['일정']}]",                                            # 상대 시점어
             "코스피가 1.19% 올랐습니다",                                                           # refs 없음
             "코스피가 1.19% 올랐습니다 [99]",                                                      # 없는 번호
             f"10/14(수) 21:30 발표되는 미국 CPI 가 다음 변수입니다 [{n['일정']}]"]
    kept, dropped, nums, sched = ab.verify_items(lines, src, d["economicCalendar"], now)
    assert [k["text"] for k in kept] == [ab._REFS.sub("", lines[i]).strip() for i in (0, 1, 2, 10)]
    assert dropped == 7 and (nums, sched) == (5, 1)
    assert ab.parse_items(["가 나 [1, 3][3] 다."], 3) == [{"text": "가 나 다.", "refs": [1, 3]}]
    # 오늘 일정이 근거에 없으면 「발표 없음」 문장은 숫자 · refs 만 본다
    no_today = [s for s in src if s["kind"] != "일정"]
    assert ab.verify_items([lines[5]], no_today, None, now)[0]


def test_rule_fallback_items_have_refs_that_pass(monkeypatch):
    now = dt.datetime(2026, 10, 14, 14, 35, tzinfo=KST)
    _fix_now(monkeypatch, now)
    d = _brief_data()
    snap = ab.build_snapshot(d)
    src = ab.build_sources(d, snap, now)
    items, nums, sched = ab.rule_items(snap, src)
    by = {s["n"]: s for s in src}
    assert len(items) == 3 and all(it["refs"] for it in items[:2])
    assert by[items[0]["refs"][0]]["_key"] == "KOSPI" and by[items[2]["refs"][-1]]["kind"] == "일정"
    assert nums == 4 and sched == 1                     # 코스피 값 · 등락, 원/달러 값 · 등락, CPI 일정


def test_main_writes_brief_fields_and_runs(monkeypatch, tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps(_brief_data()), encoding="utf-8")
    monkeypatch.setattr(ab, "DATA_FILE", str(path))
    monkeypatch.setattr(ab, "try_openai", lambda snap, sources=(): None)
    monkeypatch.setattr(ab, "try_gemini", lambda snap, sources=(): ["코스피가 1.19% 올랐습니다 [1]", "외국인이 4일 연속 순매도 [3][1]",
                                                                    "환율 메모 JSON [2]"])
    briefs = tmp_path / "briefs"
    old = briefs / "2026-09-13.json"
    keep = briefs / "2026-09-14.json"
    briefs.mkdir()
    old.write_text("{}", encoding="utf-8"), keep.write_text("{}", encoding="utf-8")
    for hm in ((14, 22), (14, 22), (15, 7)):
        _fix_now(monkeypatch, dt.datetime(2026, 10, 14, *hm, tzinfo=KST))
        ab.main()
    ai = json.loads(path.read_text(encoding="utf-8"))["aiBriefing"]
    assert ai["source"] == "gemini" and ai["day"] == "2026-10-14" and ai["dropped"] == 1
    assert ai["items"] == [{"text": "코스피가 1.19% 올랐습니다", "refs": [1]}, {"text": "외국인이 4일 연속 순매도", "refs": [3, 1]}]
    assert [s["n"] for s in ai["sources"]] == [1, 3] and all(not k.startswith("_") for s in ai["sources"] for k in s)
    assert ai["check"] == {"numbers": 2, "schedule": 0} and ai["lines"] == [it["text"] for it in ai["items"]]
    doc = json.loads((briefs / "2026-10-14.json").read_text(encoding="utf-8"))
    assert doc["date"] == "2026-10-14" and [r["at"] for r in doc["runs"]] == ["14:22", "15:07"]   # 같은 at 은 바꿔 끼움
    assert set(doc["runs"][0]) == {"at", "source", "day", "lines", "items", "sources", "dropped", "check"}
    assert not old.exists() and keep.exists()                                                      # 30일 지난 파일만 지운다


def test_home_brief_carries_new_fields():
    data = bb.load("data.json")
    data["aiBriefing"] = {"date": "2026-10-14", "generatedAt": "2026-10-14 14:22 KST", "lines": ["가"], "source": "gemini",
                          "day": "2026-10-14", "items": [{"text": "가", "refs": [1]}], "sources": [{"n": 1, "kind": "지표", "label": "x"}],
                          "dropped": 1, "check": {"numbers": 0, "schedule": 0}}
    h = bb.build_all(data, MER, t(data["lastUpdated"]).astimezone(KST))["home"]["brief"]
    assert h["asOf"] == "2026-10-14T14:22:00+09:00" and h["lines"] == ["가"] and h["items"][0]["refs"] == [1]
    assert (h["day"], h["dropped"], h["check"]) == ("2026-10-14", 1, {"numbers": 0, "schedule": 0})


# ── F1 ─────────────────────────────────────────────────────────────────────
def test_upcoming_uses_release_time_not_act(monkeypatch):
    d = {"economicCalendar": {"events": [CPI]}}
    _fix_now(monkeypatch, dt.datetime(2026, 10, 14, 14, 35, tzinfo=KST))
    assert ab.build_snapshot(d)["upcoming"] == ["10/14(수) 21:30 미국 CPI (전월비)"]     # 발표 전 act 가 차 있어도 남는다
    _fix_now(monkeypatch, dt.datetime(2026, 10, 14, 21, 40, tzinfo=KST))
    assert ab.build_snapshot(d)["upcoming"] == []


def test_backfill_waits_for_release_time_and_new_observation(monkeypatch):
    hist = {"2026-07-01": 332.813, "2026-08-01": 334.131}
    data = {"economicIndicators": {"us": {"cpi_us": {"history": hist}}}}
    ev = lambda: {"iso": "2026-10-14", "dt": "10.14 21:30", "name": "미국 CPI (전월비)", "act": "", "prev": "", "fore": "", "beat": None}

    def run(h, m):
        monkeypatch.setattr(fd, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: dt.datetime(2026, 10, 14, h, m, tzinfo=KST))}))
        e = ev()
        fd.backfill_calendar_actuals([e], data)
        return e["act"]
    assert run(14, 35) == ""                 # 발표 전 — 종전엔 00시부터 8월분 +0.4% 가 찼다
    assert run(22, 10) == ""                 # 발표 뒤지만 원천에 9월분이 아직 없다 — 직전 회차 값을 물리지 않는다
    hist["2026-09-01"] = 335.0
    assert run(22, 10) == "+0.3%"
