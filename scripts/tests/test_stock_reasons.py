#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""종목 「왜 움직였나」(scripts/stock_reasons.py, 계약 C4) 검사 — 오프라인, 네트워크는 전부 가짜.

  대상 고르기(관심 먼저 · ETF 제외 · 상위 20 · 30 상한 · fetch_data._corp_targets 와 같은 결과)
  재료 규칙(지수 동행 1%p 경계 · 반대 방향 · 공시 10일 · 기사 이름 일치 · 52주) · 재료 0 → 싣지 않음
  AI 다듬기 대조(출력 숫자 ⊆ 입력 숫자 · 금지 낱말 · 길이) · 실패 시 규칙 문장 · 연속 실패면 그만 부름 · 재료가 같으면 재사용
  키 없음 · 장 안 서는 날 → 건너뜀 · 기사 검색 실패는 종목 단위
  묶음 home.reasons 는 오늘 쓴 것만 · 수집기 잇기 · 판정표 · 재시도 병합 · 워크플로 단계

실행: python -m pytest scripts/tests/test_stock_reasons.py -q
"""
import copy
import datetime as dt
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import build_bundles as bb  # noqa: E402
import data_sla  # noqa: E402
import merge_newer  # noqa: E402
import stock_reasons as sr  # noqa: E402

NOW = dt.datetime(2026, 10, 14, 14, 30, tzinfo=sr.KST)
TODAY = "2026-10-14"


def _row(code, name, chg, market="KOSPI", typ="STOCK", as_of=TODAY):
    return {"name": name, "code": code, "price": 10000.0, "chg": chg, "amount": 1e12,
            "market": market, "type": typ, "as_of": as_of}


def _data(rows=(), **kw):
    d = {"lastUpdated": "2026-10-14T14:25:00+09:00",
         "indices": {"KOSPI": {"price": 6008.81, "change": -0.44}, "KOSDAQ": {"price": 823.88, "change": 1.2}},
         "history": {"indices": {"KOSPI": [{"date": "2026-10-12", "close": 6000.0}, {"date": "2026-10-13", "close": 6060.0},
                                           {"date": "2026-10-14", "close": 6008.81}]}},
         "rankingsKr": {"as_of": TODAY, "tradingAmount": list(rows)},
         "marketCalendarKr": {"today": {"date": TODAY, "open": True}}}
    d.update(kw)
    return d


def _cfg(tmp_path, items=()):
    p = tmp_path / "alerts_config.json"
    p.write_text(json.dumps({"tracking": {"items": list(items)}}, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _art(title, hours_ago=1.0, url=None):
    t = NOW - dt.timedelta(hours=hours_ago)
    return {"title": title, "originallink": url or "https://www.example.co.kr/a/%d" % abs(hash(title)),
            "link": "https://n.news.naver.com/x", "description": "",
            "pubDate": t.strftime("%a, %d %b %Y %H:%M:%S +0900")}


# ── 대상 ──────────────────────────────────────────────────────────────────
def test_targets_watchlist_first_etf_out_top20_cap30(tmp_path):
    cfg = _cfg(tmp_path, [{"symbol": "035420", "market": "KR", "name": "NAVER"},
                          {"symbol": "069500", "market": "KR", "name": "KODEX 200", "secType": "etf"},
                          {"symbol": "AAPL", "market": "US", "name": "Apple"}])
    rows = [_row("%06d" % (100 + i), "종목%d" % i, 1.0) for i in range(25)]
    rows[1]["type"] = "ETF"
    rows[2]["code"] = "035420"                           # 관심과 겹치는 행 — 한 번만
    got = sr.targets(_data(rows), cfg)
    codes = [c for c, _ in got]
    assert codes[0] == "035420" and "069500" not in codes and "AAPL" not in codes
    assert "000101" not in codes                         # ETF
    assert "000120" not in codes and "000119" in codes  # 상위 20 까지만
    assert len(codes) == len(set(codes)) == 19          # 관심 1 + 상위 20 중 ETF · 겹침 뺀 18
    many = _cfg(tmp_path, [{"symbol": "%06d" % (500 + i), "market": "KR", "name": "관심%d" % i} for i in range(35)])
    assert len(sr.targets(_data(rows), many)) == sr.MAX_TARGETS


def test_targets_same_as_corp_events_rule(tmp_path):
    import fetch_data as fd
    cfg = _cfg(tmp_path, [{"symbol": "035420", "market": "KR", "name": "NAVER"},
                          {"symbol": "0018Z0", "market": "KR", "name": "RISE 미국양자컴퓨팅", "secType": "etf"}])
    rows = [_row("%06d" % (100 + i), "종목%d" % i, 1.0, typ="ETF" if i % 4 == 0 else "STOCK") for i in range(20)]
    d = _data(rows)
    assert sr.targets(d, cfg) == fd._corp_targets(d, {}, cfg_path=cfg)


# ── 재료 규칙 ─────────────────────────────────────────────────────────────
def test_index_comove_boundary_is_1pp_same_direction():
    d = _data()
    got = sr.reason_for("000660", _row("000660", "SK하이닉스", -1.44), d, [], TODAY)     # 차이 1.00%p — 경계 안
    assert got and got[0] == "코스피 하락과 함께 내렸습니다"
    assert got[1] == [{"kind": "지수", "label": "코스피 ▼0.44%", "at": TODAY}]
    assert sr.reason_for("000660", _row("000660", "SK하이닉스", -1.45), d, [], TODAY) is None   # 1.01%p
    assert sr.reason_for("005930", _row("005930", "삼성전자", 0.56), d, [], TODAY) is None       # 반대 방향
    assert sr.reason_for("005930", _row("005930", "삼성전자", 0.0), d, [], TODAY) is None        # 방향 없음
    kq = sr.reason_for("247540", _row("247540", "에코프로비엠", 1.5, market="KOSDAQ"), d, [], TODAY)
    assert kq[0] == "코스닥 상승과 함께 올랐습니다" and kq[1][0]["label"] == "코스닥 ▲1.20%"   # 시장은 행의 market


def test_index_comove_past_session_uses_history_and_says_date():
    d = _data()
    got = sr.reason_for("000660", _row("000660", "SK하이닉스", 1.5, as_of="2026-10-13"), d, [], TODAY)
    assert got[0] == "10/13 코스피 상승과 함께 올랐습니다"
    assert got[1][0] == {"kind": "지수", "label": "코스피 ▲1.00%", "at": "2026-10-13"}


def _ev(date, code="005930", kind="earnings", **kw):
    return dict({"code": code, "name": "삼성전자", "kind": kind, "date": date,
                 "title": "잠정실적" if kind == "earnings" else "배당 결정", "rcpNo": "20261008800004"}, **kw)


def test_disclosure_within_10_days_only():
    row = _row("005930", "삼성전자", 0.86)                                   # 지수와 반대 — 공시만 재료
    def line(*evs):
        got = sr.reason_for("005930", row, _data(corpEvents={"items": list(evs)}), [], TODAY)
        return got and got[0]
    assert line(_ev("2026-10-08")) == "10/8 잠정실적 공시 엿새 뒤"
    assert line(_ev("2026-10-04")) == "10/4 잠정실적 공시 열흘 뒤"
    assert line(_ev("2026-10-03")) is None                                     # 11일
    assert line(_ev(TODAY, kind="dividend")) == "오늘 배당 결정 공시"
    assert line(_ev("2026-10-12", via="alotMatter", title="결산 배당 1,444원")) is None   # 결산 배당 표는 공시가 아니다
    assert line(_ev("2026-10-12", code="000660")) is None                      # 다른 종목
    assert line(_ev("2026-10-04"), _ev("2026-10-12")) == "10/12 잠정실적 공시 이틀 뒤"    # 가장 최근 것
    got = sr.reason_for("005930", row, _data(corpEvents={"items": [_ev("2026-10-08")]}), [], TODAY)
    assert got[1] == [{"kind": "공시", "label": "10/8 잠정실적", "at": "2026-10-08",
                       "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261008800004"}]
    # 등락이 전날 장이면 그 뒤에 낸 공시는 까닭이 될 수 없다
    prev_row = _row("005930", "삼성전자", -0.86, as_of="2026-10-13")       # 그날 코스피 ▲1.00% 와 반대
    assert sr.reason_for("005930", prev_row, _data(corpEvents={"items": [_ev(TODAY)]}), [], TODAY) is None


def test_52week_high_low_from_krx_lists():
    def krx(as_of, code):
        return {"as_of": as_of, "kospi": [_row(code, "x", 3.0, as_of=as_of)], "kosdaq": []}
    row = _row("028670", "팬오션", 0.5)
    hi = _data(); hi["rankingsKr"]["high52"] = krx("2026-10-13", "028670")
    got = sr.reason_for("028670", row, hi, [], TODAY)
    assert got[0] == "10/13 52주 신고가" and got[1] == [{"kind": "신고가", "label": "10/13 52주 신고가", "at": "2026-10-13"}]
    lo = _data(); lo["rankingsKr"]["low52"] = krx(TODAY, "028670")
    assert sr.reason_for("028670", row, lo, [], TODAY)[0] == "52주 신저가"
    old = _data(); old["rankingsKr"]["high52"] = krx("2026-10-01", "028670")          # 13일 전 목록
    assert sr.reason_for("028670", row, old, [], TODAY) is None


def test_articles_title_must_name_the_stock_within_24h():
    others = {"삼성전자", "삼성전자우", "SK", "SK하이닉스"}
    raw = [_art("<b>삼성전자</b>, 3분기 &quot;깜짝&quot; 실적", 1),
           _art("삼성전자우 급등", 2),
           _art("반도체 업황 개선", 2),
           _art("삼성전자 어제 소식", 25),
           _art("삼성전자 링크 이상", 1, url="javascript:alert(1)"),
           _art("<b>삼성전자</b>, 3분기 &quot;깜짝&quot; 실적", 1)]
    got = sr.pick_articles(raw, "삼성전자", others, NOW)
    assert [a["title"] for a in got] == ['삼성전자, 3분기 "깜짝" 실적']
    a = got[0]
    assert a["src"] == "example.co.kr" and a["url"].startswith("https://") and a["at"] == "2026-10-14T13:30:00+09:00"
    sk = sr.pick_articles([_art("SK하이닉스 신고가", 1), _art("SK, 지주사 할인 축소", 1)], "SK", others, NOW)
    assert [x["title"] for x in sk] == ["SK, 지주사 할인 축소"]
    # 기사만 재료 — 문장은 기사 제목, 근거 칩은 최신 2건
    arts = sr.pick_articles([_art("삼성전자 신제품 공개", 1), _art("삼성전자 노사 합의", 3), _art("삼성전자 투자", 5)],
                            "삼성전자", others, NOW)
    line, refs = sr.reason_for("005930", _row("005930", "삼성전자", 0.86), _data(), arts, TODAY)
    assert line == "기사 「삼성전자 신제품 공개」" and [r["kind"] for r in refs] == ["기사", "기사"]


def test_no_material_means_no_entry(tmp_path):
    d = _data([_row("005930", "삼성전자", 0.86), _row("000660", "SK하이닉스", -1.0)])
    sn, rs = sr.build(d, NOW, _cfg(tmp_path))
    assert sn is None                                   # 기사 단계 건너뜀(news=None)
    assert list(rs["items"]) == ["000660"]              # 삼성전자는 재료 0 → 싣지 않는다
    it = rs["items"]["000660"]
    assert it["source"] == "rule" and it["line"] == it["rule"] and it["at"] == NOW.isoformat(timespec="seconds")
    assert rs["asOf"] == it["at"]


# ── AI 다듬기 ─────────────────────────────────────────────────────────────
RULE = "코스피 하락과 함께 내렸습니다 · 10/8 잠정실적 공시 엿새 뒤"
REFS = [{"kind": "지수", "label": "코스피 ▼0.44%"}, {"kind": "공시", "label": "10/8 잠정실적"}]


def test_polish_ok_numbers_subset_and_banned_words():
    ok = sr.polish_ok
    assert ok("코스피가 0.44% 내린 날 10월 8일 잠정실적 공시 뒤 함께 약세였습니다", RULE, REFS)
    assert not ok("코스피 약세 속 3분기 영업이익 12조 원 발표 엿새 뒤 내렸습니다", RULE, REFS)    # 새 숫자
    assert not ok("코스피 0.45% 하락과 함께 내렸습니다", RULE, REFS)                            # 바뀐 숫자
    assert not ok("잠정실적 공시 뒤 차익 실현 매도가 나오며 내렸습니다", RULE, REFS)            # 재료에 없는 매도
    assert ok("외국인 매도 기사와 함께 코스피 하락 속에 내렸습니다",
              RULE, REFS + [{"kind": "기사", "label": "삼성전자, 외국인 매도에 약세"}])
    for bad in ("스냅샷 기준 코스피 하락과 함께 내렸습니다", "내일 반등을 기대해 볼 만합니다",
                "코스피 하락과 함께 내렸습니다\n잠정실적 공시 엿새 뒤", "짧다", "가" * 61):
        assert not ok(bad, RULE, REFS), bad


def _two_material_data():
    rows = [_row("%06d" % (100 + i), "종목%d" % i, -0.5) for i in range(4)]
    return _data(rows)


def test_build_uses_gemini_only_when_it_passes(tmp_path):
    cfg = _cfg(tmp_path)
    good = lambda p: "“코스피가 0.44% 내린 흐름을 따라 함께 내렸습니다”"
    _, rs = sr.build(_two_material_data(), NOW, cfg, polish=good)
    it = rs["items"]["000100"]
    assert it["source"] == "gemini" and it["line"] == "코스피가 0.44% 내린 흐름을 따라 함께 내렸습니다"
    assert it["rule"] == "코스피 하락과 함께 내렸습니다"
    _, rs = sr.build(_two_material_data(), NOW, cfg, polish=lambda p: "코스피가 1.5% 빠지며 함께 내렸습니다")
    assert all(x["source"] == "rule" and x["line"] == x["rule"] for x in rs["items"].values())
    prompts = []
    sr.build(_two_material_data(), NOW, cfg, polish=lambda p: prompts.append(p) or "x")
    assert "문장: 코스피 하락과 함께 내렸습니다" in prompts[0] and "- 지수: 코스피 ▼0.44%" in prompts[0]


def test_build_stops_calling_gemini_after_consecutive_failures(tmp_path):
    calls = []

    def boom(p):
        calls.append(p)
        raise TimeoutError("느림")
    _, rs = sr.build(_two_material_data(), NOW, _cfg(tmp_path), polish=boom)
    assert len(calls) == sr.GEMINI_FAIL_STOP and len(rs["items"]) == 4
    assert all(x["source"] == "rule" for x in rs["items"].values())


def test_build_reuses_previous_line_when_material_unchanged(tmp_path):
    cfg = _cfg(tmp_path)
    d = _two_material_data()
    _, first = sr.build(d, NOW - dt.timedelta(hours=1), cfg, polish=lambda p: "코스피 약세를 따라 함께 내렸습니다")
    d["stockReasons"] = first
    calls = []
    _, again = sr.build(d, NOW, cfg, polish=lambda p: calls.append(p) or "다른 문장입니다 다른 문장")
    assert calls == [] and again["items"]["000100"]["line"] == "코스피 약세를 따라 함께 내렸습니다"
    assert again["items"]["000100"]["at"] == NOW.isoformat(timespec="seconds")


# ── 기사 단계 · 키 · 실행 조건 ──────────────────────────────────────────────
def test_news_failure_is_per_stock_and_keeps_fresh_prev(tmp_path):
    d = _data([_row("005930", "삼성전자", 0.86), _row("000660", "SK하이닉스", 0.9)])
    fresh = {"title": "SK하이닉스 직전 기사", "url": "https://a.kr/1", "src": "a.kr", "at": "2026-10-14T10:00:00+09:00"}
    stale = {"title": "SK하이닉스 묵은 기사", "url": "https://a.kr/2", "src": "a.kr", "at": "2026-10-13T10:00:00+09:00"}
    d["stockNews"] = {"asOf": "2026-10-14T13:30:00+09:00", "items": {"000660": [fresh, stale]}}

    def news(name):
        if name == "SK하이닉스":
            raise RuntimeError("HTTP 500")
        return [_art("삼성전자 신제품 공개", 1)]
    sn, rs = sr.build(d, NOW, _cfg(tmp_path), news=news)
    assert [a["title"] for a in sn["items"]["005930"]] == ["삼성전자 신제품 공개"]
    assert sn["items"]["000660"] == [fresh]                       # 실패한 종목은 직전 기사 중 24시간 안 것만
    assert set(rs["items"]) == {"005930", "000660"}


class _Resp:
    def __init__(self, items, status=200):
        self.items, self.status_code = items, status

    def json(self):
        return {"items": self.items}


def _write(tmp_path, d):
    p = tmp_path / "data.json"
    p.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return p


def test_main_without_keys_skips_news_and_ai(tmp_path, monkeypatch, capsys):
    for k in ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    p = _write(tmp_path, _data([_row("000660", "SK하이닉스", -1.0)]))
    monkeypatch.setattr(sr, "DATA_FILE", str(p))
    monkeypatch.setattr(sr, "CFG_FILE", _cfg(tmp_path))
    monkeypatch.setattr(sr.requests, "get", lambda *a, **k: pytest.fail("키 없이 기사 검색을 불렀다"))
    monkeypatch.setattr(sr, "_gemini_text", lambda *a, **k: pytest.fail("키 없이 Gemini 를 불렀다"))
    assert sr.main(["--force"]) == 0
    text = p.read_text(encoding="utf-8")
    out = json.loads(text)
    assert "stockNews" not in out and list(out["stockReasons"]["items"]) == ["000660"]
    assert text == json.dumps(out, ensure_ascii=False, separators=(",", ":"))      # 압축 저장
    assert "기사 단계 건너뜀" in capsys.readouterr().out


def test_main_with_keys_calls_naver_once_per_stock_and_never_logs_keys(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NAVER_CLIENT_ID", "id-secret-글자")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "pw-secret-글자")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(sr, "NEWS_GAP", 0)
    p = _write(tmp_path, _data([_row("005930", "삼성전자", 0.86), _row("000660", "SK하이닉스", -1.0)]))
    monkeypatch.setattr(sr, "DATA_FILE", str(p))
    monkeypatch.setattr(sr, "CFG_FILE", _cfg(tmp_path))
    seen = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append((url, params, headers))
        if params["query"].startswith("SK"):
            return _Resp([], status=429)
        return _Resp([_art("삼성전자 신제품 공개", 0.5)])
    monkeypatch.setattr(sr.requests, "get", fake_get)
    sr.main(["--force"])
    out = json.loads(p.read_text(encoding="utf-8"))
    assert len(seen) == 2 and all(u == sr.NEWS_URL and q["sort"] == "date" and q["display"] == 10 for u, q, _ in seen)
    assert seen[0][2]["X-Naver-Client-Id"] == "id-secret-글자" and seen[0][1]["query"] == "삼성전자 주가"
    assert list(out["stockNews"]["items"]) == ["005930"]
    assert out["stockReasons"]["items"]["005930"]["refs"][0]["kind"] == "기사"
    log = capsys.readouterr().out
    assert "secret" not in log and "HTTP 429" in log


def test_main_skips_when_market_closed(tmp_path, monkeypatch):
    today = dt.datetime.now(sr.KST).date().isoformat()
    d = _data([_row("000660", "SK하이닉스", -1.0)], marketCalendarKr={"today": {"date": today, "open": False}})
    p = _write(tmp_path, d)
    before = p.read_text(encoding="utf-8")
    monkeypatch.setattr(sr, "DATA_FILE", str(p))
    assert sr.main([]) == 0 and p.read_text(encoding="utf-8") == before


def test_should_run_window():
    d = _data()
    at = lambda h, day=14: dt.datetime(2026, 10, day, h, 7, tzinfo=sr.KST)
    assert sr.should_run(d, at(8)) and sr.should_run(d, at(20))
    assert not sr.should_run(d, at(7)) and not sr.should_run(d, at(21))
    closed = _data(marketCalendarKr={"today": {"date": TODAY, "open": False}})
    assert not sr.should_run(closed, at(10))
    assert not sr.should_run(_data(marketCalendarKr={}), at(10, day=18))   # 달력 모름 → 평일만(10/18 일요일)


# ── 묶음 · 잇기 · 판정표 · 병합 · 워크플로 ────────────────────────────────────
def _reasons(now):
    today_at, old_at = now.isoformat(timespec="seconds"), (now - dt.timedelta(days=1)).isoformat(timespec="seconds")
    return {"asOf": today_at, "items": {
        "000660": {"line": "코스피 하락과 함께 내렸습니다", "rule": "코스피 하락과 함께 내렸습니다", "source": "rule",
                   "at": today_at, "refs": [{"kind": "지수", "label": "코스피 ▼0.44%", "at": TODAY},
                                            {"kind": "기사", "label": "x", "url": "javascript:alert(1)", "at": today_at}]},
        "005930": {"line": "어제 문장", "rule": "어제 문장", "source": "rule", "at": old_at, "refs": []}}}


def test_home_reasons_today_only():
    data = bb.load("data.json")
    now = bb._iso_dt(data["lastUpdated"]).astimezone(bb.KST) + dt.timedelta(minutes=5)
    data = copy.deepcopy(data)
    data["stockReasons"] = _reasons(now)
    home = bb.build_all(data, bb.load("mer_signals.json", {}), now, bb.load("toss_snapshot.json", {}))["home"]
    r = home["reasons"]
    assert list(r["items"]) == ["000660"] and r["asOf"] is data["stockReasons"]["asOf"]
    it = r["items"]["000660"]
    assert it["line"] is data["stockReasons"]["items"]["000660"]["line"]    # 원본 잎 그대로(묶음 사용률 게이트가 센다)
    assert it["refs"][1]["url"] is None and it["refs"][0] == {"kind": "지수", "label": "코스피 ▼0.44%", "at": TODAY}
    tomorrow = now + dt.timedelta(days=2)
    assert bb.home_reasons(data, tomorrow.date()) is None                   # 오늘 쓴 것이 없으면 칸 없음
    assert bb.home_reasons({}, now.date()) is None


def test_bundle_usage_gate_excuses_new_keys():
    import test_bundle_usage as tbu
    data = copy.deepcopy(bb.load("data.json"))
    now = bb._iso_dt(data["lastUpdated"]).astimezone(bb.KST)
    data["stockReasons"] = _reasons(now - dt.timedelta(days=3))           # 휴장일 뒤 — 묶음에 안 실린다
    data["stockNews"] = {"asOf": data["stockReasons"]["asOf"], "items": {"000660": [{"title": "SK하이닉스 기사",
                         "url": "https://a.kr/1", "src": "a.kr", "at": data["stockReasons"]["asOf"]}]}}
    got = tbu.unread_now(data, bb.load("mer_signals.json", {}), bb.load("toss_snapshot.json", {}))
    assert not [u for u in got if not tbu.excused(u)], got


def test_fetch_data_carries_blocks_between_runs():
    with open(os.path.join(HERE, "..", "fetch_data.py"), encoding="utf-8") as f:
        src = f.read()
    assert 'for _k in ("stockNews", "stockReasons"):' in src and "data[_k] = prev[_k]" in src


def test_data_sla_treats_blocks_as_one_item():
    d = {"lastUpdated": "2026-10-14T14:30:00+09:00", "stockReasons": _reasons(NOW),
         "stockNews": {"asOf": NOW.isoformat(), "items": {"000660": []}}}
    h = data_sla.build_health(d, today=NOW.date())
    by = {i["path"]: i for i in h["items"]}
    assert by["stockReasons"]["state"] == "ok" and by["stockNews"]["state"] == "ok"
    assert not [p for p in by if p.startswith(("stockReasons.", "stockNews."))]


def test_merge_newer_keeps_the_newer_reasons_on_retry():
    old, new = _reasons(NOW - dt.timedelta(hours=1)), _reasons(NOW)
    run = {"lastUpdated": "2026-10-14T14:40:00+09:00", "stockReasons": old}     # 경량 런 — 직전 이유 줄을 이은 판
    origin = {"lastUpdated": "2026-10-14T14:35:00+09:00", "stockReasons": new}  # 그사이 풀 런이 새로 쓴 판
    assert merge_newer.merge(run, origin)["stockReasons"] is new
    run2 = {"lastUpdated": "2026-10-14T14:40:00+09:00", "stockReasons": copy.deepcopy(new)}
    assert merge_newer.merge(run2, {"stockReasons": old})["stockReasons"]["asOf"] == new["asOf"]


def test_workflow_runs_stock_reasons_after_briefing_on_full_runs_only():
    from test_workflows_have_pytest import split_steps, _field
    with open(os.path.join(HERE, "..", "..", ".github", "workflows", "fetch-data.yml"), encoding="utf-8") as f:
        steps = split_steps(f.read())
    runs = {i: "\n".join(ls) for i, (_n, ls) in enumerate(steps)}
    at = lambda script: next(i for i, body in runs.items() if "python scripts/" + script in body)
    i = at("stock_reasons.py")
    assert at("ai_briefing.py") < i < at("validate_data.py") < at("build_bundles.py")
    ls = steps[i][1]
    assert _field(ls, "if") == "env.FETCH_LIGHT != '1'" and _field(ls, "continue-on-error") == "true"
    for k in ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "GEMINI_API_KEY"):
        assert _field(ls, k) == "${{ secrets.%s }}" % k
