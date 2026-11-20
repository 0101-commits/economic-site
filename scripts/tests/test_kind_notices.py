"""거래소 시장조치 공시 읽기(kind_notices) · 네이버 실시간 지수(naver_realtime) — 네트워크 없이 실제 응답 일부로.

시험 자료(fixtures/kind): 2026-11-20 KIND 「오늘의 공시」 목록 셋째 쪽 중 11:54 코스피 매도 사이드카 앞뒤 7줄(실제 HTML),
그 공시 본문 글. 제목 · 본문 꼴은 10/1~11/20 시장조치 공시 20건(기획 4ioDhgSA 부록)에서 가져왔다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kind_notices as K  # noqa: E402
import naver_realtime as N  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "kind")
KST = dt.timezone(dt.timedelta(hours=9))


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def test_list_page_finds_kospi_sidecar_and_ignores_others():
    rows = K.parse_list(_read("list_20261120_1154.html"))
    assert len(rows) == 7 and all(r["time"] and r["acptno"] for r in rows)
    halts = [h for h in (K.to_halt(r, "2026-11-20") for r in rows) if h]
    assert [(h["market"], h["type"], h["direction"], h["triggeredAt"]) for h in halts] == \
        [("KOSPI", "sidecar", "down", "2026-11-20T11:54:00+09:00")]      # 파생상품시장본부 「가격제한폭 확대」 등은 아니다
    assert halts[0]["acptno"] == "20261120000368" and halts[0]["resumeAt"] == "2026-11-20T11:59:00+09:00"


def test_body_gives_second_and_futures_pct():
    f = K.parse_body(_read("body_20261120000368.txt"))
    assert f["at"] == dt.datetime(2026, 11, 20, 11, 54, 5, tzinfo=KST) and f["pct"] == -5.04 and f["kind"] == "fut"


def test_titles_of_all_market_actions():
    cases = {
        ("유가증권시장 매도 사이드카(Side car) 발동", "유가증권시장본부"): ("KOSPI", "sidecar", "down", None),
        ("유가증권시장 매수 사이드카(Side car) 발동", "유가증권시장본부"): ("KOSPI", "sidecar", "up", None),
        ("코스닥시장 프로그램매도호가 일시효력정지(Sidecar 발동)", "코스닥시장본부"): ("KOSDAQ", "sidecar", "down", None),
        ("코스닥시장 프로그램매수호가 일시효력정지(Sidecar 발동)", "코스닥시장본부"): ("KOSDAQ", "sidecar", "up", None),
        ("유가증권시장 매매거래 일시중단(1단계 CB 발동)", "유가증권시장본부"): ("KOSPI", "circuit", "down", 1),
        ("코스닥시장 매매거래 일시중단(1단계 CB 발동)", "코스닥시장본부"): ("KOSDAQ", "circuit", "down", 1),
        ("유가증권시장 매매거래 종료(3단계 CB 발동)", "유가증권시장본부"): ("KOSPI", "circuit", "down", 3),
    }
    for (title, by), want in cases.items():
        p = K.parse_title(title, by)
        assert (p["market"], p["type"], p["direction"], p["stage"]) == want, title
    for title, by in (("KRX 반도체 지수선물 2단계 가격제한폭 확대요건 도달(하락)", "파생상품시장본부"),
                      ("투자경고종목 지정", "유가증권시장본부"), ("사이드카 발동 관련 안내", "삼성전자")):
        assert K.parse_title(title, by) is None, title


def test_circuit_body_is_index_and_stage3_ends_day():
    body = ("유가증권시장 매매거래 일시중단(1단계 CB 발동) 1. 일자 및 시각 2026-10-15 12:38:12 2. 주가지수 변동내역 "
            "현재지수(P) 전일지수(P) 등락폭(P) 등락율(%) 5,528.05 6,008.81 -480.76 -8.00 3. 내용 …")
    f = K.parse_body(body)
    assert f["at"].strftime("%H:%M:%S") == "12:38:12" and f["pct"] == -8.0 and f["kind"] == "index"
    row = {"time": "14:51", "title": "유가증권시장 매매거래 종료(3단계 CB 발동)", "by": "유가증권시장본부", "acptno": "1"}
    h = K.to_halt(row, "2026-10-15")
    assert h["endOfDay"] is True and h["resumeAt"] is None and h["id"] == "circuit-KOSPI-20261015"


def test_kosdaq_sidecar_body_reads_futures_not_spot():
    body = ("구분 현재가(P) 전일종가(P) 등락폭(P) 등락율(%) 선물가격 1,072.80 1,141.80 -69.00 -6.04 "
            "현물지수(코스닥150) 1,070.37 1,134.16 -63.79 -5.62")
    assert K.parse_body(body)["pct"] == -6.04


def test_naver_realtime_parse_and_open_guard():
    payload = {"datas": [{"closePriceRaw": "4869.96", "compareToPreviousClosePriceRaw": "-267.93",
                          "fluctuationsRatioRaw": "-5.21", "marketStatus": "CLOSE",
                          "localTradedAt": "2026-11-20T15:59:00+09:00"}]}
    q = N.parse(payload, dt.datetime(2026, 11, 20, 16, 0, tzinfo=KST))
    assert q["value"] == 4869.96 and q["changePct"] == -5.21 and q["prevClose"] == 5137.89 and q["live"] is True
    pre = dict(payload["datas"][0], localTradedAt="2026-11-19T15:59:00+09:00")
    assert N.parse({"datas": [pre]}, dt.datetime(2026, 11, 20, 8, 55, tzinfo=KST))["live"] is False   # 09:00 전 = 전날 값
    assert N.parse({"datas": []}) is None
