"""A19 수집기 회귀 테스트 (오프라인 — 네트워크를 부르지 않는다).

KRX 코스닥 등락상위·등락 종목 수·코스피 업종 등락 + 비미국 경제 일정(금통위·ECB·BOJ·국가데이터처).
KRX 행은 OpenAPI 명세(유가증권·코스닥 일별매매정보, 코스피 시리즈 일별시세 OutBlock_1)의 필드 이름으로 만든다.
캘린더 파서는 2026-09-30 에 받은 실제 페이지를 잘라 둔 scripts/tests/fixtures/*.html 로 돈다.
실행: python -m pytest scripts/tests/test_a19_collector.py
"""
import os
import sys
import types
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fetch_data as fd  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _fix(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def _stk(name, code, close, cmp_, rt, vol, sect="-"):
    return {"BAS_DD": "20260929", "ISU_CD": code, "ISU_NM": name, "MKT_NM": "KOSDAQ", "SECT_TP_NM": sect,
            "TDD_CLSPRC": f"{close:,}", "CMPPREVDD_PRC": str(cmp_), "FLUC_RT": str(rt),
            "ACC_TRDVOL": f"{vol:,}", "ACC_TRDVAL": "1", "MKTCAP": "1", "LIST_SHRS": "1"}


def _idx(name, close, rt):
    return {"BAS_DD": "20260929", "IDX_CLSS": "KOSPI", "IDX_NM": name, "CLSPRC_IDX": str(close),
            "CMPPREVDD_IDX": "0", "FLUC_RT": str(rt)}


KOSDAQ_ROWS = [
    _stk("알파", "111110", 13000, 3000, 30.0, 5000, "벤처기업부"),       # 상한가
    _stk("베타", "111120", 44, 10, 29.41, 900, "중견기업부"),            # 기준 34원 → 상한 44원(+29.41%)
    _stk("감마", "111130", 1299, 299, 29.9, 800, "우량기업부"),          # 기준 1000 → 상한 1300, 1299 는 한 호가 아래
    _stk("델타", "111140", 10500, 500, 5.0, 700),
    _stk("엡실론", "111150", 700, -300, -30.0, 600),                   # 하한가
    _stk("제타", "111160", 701, -299, -29.9, 500),                     # 하한 700 보다 한 호가 위
    _stk("에타", "111170", 9800, -200, -2.0, 400),
    _stk("세타", "111180", 5000, 0, 0.0, 300),                         # 보합
    _stk("정지주", "111190", 3000, 0, 0.0, 0),                          # 거래정지 — 어디에도 안 센다
    _stk("하나스팩9호", "111200", 2210, 510, 30.0, 9999, "SPAC(소속부없음)"),   # 기준 1700 → 상한 2210
    _stk("관리주", "111210", 1500, 340, 29.3, 9999, "관리종목(소속부없음)"),
]
KOSPI_ROWS = [_stk("큰회사", "005930", 70000, 1000, 1.45, 100000), _stk("작은회사", "000020", 9000, -100, -1.1, 200),
              _stk("무변동", "000030", 5000, 0, 0.0, 10)]
INDEX_ROWS = [_idx("코스피", 3500.1, 0.5), _idx("코스피 200", 480.2, 0.6), _idx("코스피 대형주", 3000, 0.4),
              _idx("음식료품", 4000.12, -1.2), _idx("전기·전자", 90000.5, 2.345), _idx("금융업", 600, 0.1),
              _idx("제조업", 5000, 0.3), _idx("반도체소부장", 100, 9.9)]


# ── KRX 행 해석 ─────────────────────────────────────────────────────────────
def test_stock_rows_read_official_field_names():
    rows = fd._krx_stock_rows(KOSDAQ_ROWS[:1], "2026-09-30", "KOSDAQ")
    assert rows[0]["code"] == "111110"          # ISU_CD (종전 코드는 ISU_SRT_CD 를 읽어 빈칸)
    assert rows[0]["vol"] == 5000               # ACC_TRDVOL (종전 ACML_VOL → 0)
    assert rows[0]["as_of"] == "2026-09-29"     # 요청 날짜가 아니라 응답의 BAS_DD
    assert rows[0]["base"] == 10000 and rows[0]["market"] == "KOSDAQ"


def test_kosdaq_movers_shape_and_exclusions():
    g, l = fd._krx_movers(fd._krx_stock_rows(KOSDAQ_ROWS, "2026-09-29", "KOSDAQ"), top_n=3)
    assert [r["name"] for r in g] == ["알파", "감마", "베타"]         # SPAC·관리종목 제외
    assert [r["name"] for r in l] == ["엡실론", "제타", "에타"]
    assert set(g[0]) == {"name", "code", "price", "chg", "vol", "market", "as_of"}   # kospiGainers 와 같은 모양
    names = {r["name"] for r in g + l}
    assert not names & {"정지주", "하나스팩9호", "관리주"}


def test_breadth_counts_with_tick_based_limits():
    b = fd._krx_breadth(fd._krx_stock_rows(KOSDAQ_ROWS, "2026-09-29", "KOSDAQ"))
    # 상승 = 알파·베타·감마·델타·스팩·관리주(6) / 하락 = 엡실론·제타·에타(3) / 보합 = 세타(1) / 정지주 제외
    assert b == {"up": 6, "down": 3, "flat": 1, "limitUp": 3, "limitDown": 1}, b
    # 상한가 셋 = 알파·베타(100원 미만 +29.41% — 29.5% 문턱이면 놓친다)·스팩. 감마는 한 호가 아래, 관리주(기준 1160 → 상한 1508)는 아님


def test_limit_detection_edge_cases():
    rows = lambda *specs: fd._krx_stock_rows([_stk("x", "1", c, d, r, 1) for c, d, r in specs], "d", "KOSPI")
    lu = lambda *s: fd._krx_breadth(rows(*s))["limitUp"]
    ld = lambda *s: fd._krx_breadth(rows(*s))["limitDown"]
    assert lu((1300, 300, 30.0)) == 1 and lu((1299, 299, 29.9)) == 0
    assert lu((2000, 460, 29.87)) == 1        # 기준 1540 × 1.3 = 2002 → 5원 단위 최고 호가 2000
    assert lu((1999, 459, 29.81)) == 0        # 한 호가(2000) 더 오를 수 있었다
    assert lu((44, 10, 29.41)) == 1           # 100원 미만 — 등락률 문턱으로는 못 잡는다
    assert ld((700, -300, -30.0)) == 1 and ld((701, -299, -29.9)) == 0
    # 폭은 기준가 호가단위로 절사 — 기준 2,010(5원 단위) → 폭 600 → 하한 1,410(1원 단위 가격대지만 1,407 이 아니다)
    assert fd._krx_limits(2010) == (2610, 1410) and ld((1410, -600, -29.85)) == 1
    assert fd._krx_limits(9980) == (12970, 6990)          # 폭 2,990 · 상한은 제 가격대 10원 단위
    assert fd._krx_limits(1540) == (2000, 1078)           # 상한 2,002 → 5원 단위로 절사
    # 30% 제한이 없는 날은 상·하한가로 세지 않는다 — 신규상장 첫날 +150%, 정리매매 -80%
    assert lu((25000, 15000, 150.0)) == 0 and ld((200, -800, -80.0)) == 0
    # 대비가 부호 없이 와도 하락 종목 기준가가 뒤집히지 않는다
    r = fd._krx_stock_rows([_stk("x", "1", 700, 300, -30.0, 1)], "d", "KOSPI")
    assert r[0]["base"] == 1000 and fd._krx_breadth(r)["limitDown"] == 1


def test_sector_moves_keep_only_sector_rows():
    sm, unknown = fd._krx_sector_moves(INDEX_ROWS, "2026-09-30")
    assert sm["as_of"] == "2026-09-29"
    assert [i["name"] for i in sm["items"]] == ["전기·전자", "금융업", "음식료품"]   # 등락률 내림차순
    assert sm["items"][0] == {"name": "전기·전자", "close": 90000.5, "chg_pct": 2.35}
    assert unknown == ["반도체소부장"]       # 코스피 계열·제조업은 조용히 빼고, 모르는 이름만 드러낸다
    assert fd._krx_sector_moves([_idx("코스피", 1, 1)], "d") == (None, [])


# ── 빌드 연결 (가짜 KRX) ─────────────────────────────────────────────────────
class _Resp:
    def __init__(self, payload, code=200):
        self.status_code, self._p = code, payload

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _krx_env(monkeypatch, table, key="k"):
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        ep = url.replace(fd.KRX_BASE, "")
        calls.append(ep)
        return _Resp({"OutBlock_1": table.get(ep, [])})

    monkeypatch.setattr(fd, "KRX_API_KEY", key)
    monkeypatch.setattr(fd, "_KRX_DENIED", set())
    monkeypatch.setattr(fd, "_KRX_ROWS", {})
    monkeypatch.setattr(fd, "requests", types.SimpleNamespace(get=get))
    monkeypatch.setattr(fd, "log", lambda *a, **k: None)
    return calls


def _blank():
    return {"stockMovers": {"kospiGainers": [{"name": "토스"}]}, "sources": {"stockMovers": "토스증권 Open API"}}


def test_a19_builds_three_blocks(monkeypatch):
    calls = _krx_env(monkeypatch, {"/sto/ksq_bydd_trd": KOSDAQ_ROWS, "/sto/stk_bydd_trd": KOSPI_ROWS,
                                   "/idx/kospi_dd_trd": INDEX_ROWS})
    data = _blank()
    fd._krx_a19(data, prev={})
    sm = data["stockMovers"]
    assert len(sm["kosdaqGainers"]) == 8 and sm["kosdaqGainers"][0]["name"] == "알파"   # 거래 있고 SPAC·관리 아닌 8종
    assert sm["kosdaqLosers"][0]["name"] == "엡실론" and "preserved" not in sm["kosdaqGainers"][0]
    assert data["sources"]["stockMovers"] == "토스증권 Open API"         # 코스피 라벨은 그대로
    assert data["sources"]["stockMovers.kosdaqGainers"] == "KRX OpenAPI"   # 경로별 소스 — 판정표가 따로 읽는다
    mb = data["marketBreadth"]
    assert mb["kospi"] == {"up": 1, "down": 1, "flat": 1, "limitUp": 0, "limitDown": 0, "as_of": "2026-09-29"}
    assert mb["kosdaq"]["limitUp"] == 3 and mb["kosdaq"]["as_of"] == "2026-09-29" and mb["source"]
    assert [i["name"] for i in data["sectorMoves"]["items"]] == ["전기·전자", "금융업", "음식료품"]
    assert data["sectorMoves"]["as_of"] == "2026-09-29"
    assert data["diagnostics"]["sectorMovesUnmatched"] == ["반도체소부장"]
    # 같은 (엔드포인트, 날짜)는 한 번만 — 두 번째 부름은 런 캐시에서
    n = len(calls)
    fd.fetch_krx_latest("/sto/ksq_bydd_trd")
    assert len(calls) == n


def test_a19_preserves_each_cell_without_key(monkeypatch):
    calls = _krx_env(monkeypatch, {}, key="")
    prev = {"stockMovers": {"kosdaqGainers": [dict(r) for r in fd._krx_movers(
                fd._krx_stock_rows(KOSDAQ_ROWS, "2026-09-26", "KOSDAQ"))[0]]},
            "marketBreadth": {"kospi": {"up": 1, "down": 2, "flat": 3, "limitUp": 0, "limitDown": 0,
                                        "as_of": "2026-09-26"}, "source": "KRX"},
            "sectorMoves": {"as_of": "2026-09-26", "items": [{"name": "화학", "close": 1, "chg_pct": 1}]}}
    data = _blank()
    fd._krx_a19(data, prev)
    assert calls == []                                                     # 키 없음 = 호출 0
    g = data["stockMovers"]["kosdaqGainers"]
    assert g and all(r["preserved"] is True and r["preservedAt"] for r in g)
    assert "kosdaqLosers" not in data["stockMovers"]                      # 직전에도 없던 칸은 만들지 않는다
    assert data["sources"]["stockMovers"] == "토스증권 Open API"          # 코스피 라벨을 '보존'으로 바꾸지 않는다
    assert "보존" in data["sources"]["stockMovers.kosdaqGainers"]
    assert data["marketBreadth"]["kospi"]["preserved"] is True and "kosdaq" not in data["marketBreadth"]
    assert data["sectorMoves"]["preserved"] is True and data["sectorMoves"]["items"][0]["name"] == "화학"
    # preservedAt 은 처음 못 받은 시각을 유지한다
    again = _blank()
    fd._krx_a19(again, {"stockMovers": {"kosdaqGainers": g}})
    assert again["stockMovers"]["kosdaqGainers"][0]["preservedAt"] == g[0]["preservedAt"]


def test_a19_sector_rename_is_missing_not_preserved(monkeypatch):
    _krx_env(monkeypatch, {"/idx/kospi_dd_trd": [_idx("코스피", 1, 1), _idx("새이름 전자", 1, 1)]})
    data = _blank()
    fd._krx_a19(data, {"sectorMoves": {"as_of": "2026-09-26", "items": [{"name": "화학", "close": 1, "chg_pct": 1}]}})
    assert "sectorMoves" not in data                                      # 개편 전 업종을 잇지 않는다
    assert data["diagnostics"]["sectorMovesUnmatched"] == ["새이름 전자"]


def test_a19_breadth_with_no_traded_rows_is_not_zero(monkeypatch):
    novol = [{k: v for k, v in r.items() if k != "ACC_TRDVOL"} for r in KOSPI_ROWS]   # 거래량 칸 이름이 바뀐 날
    _krx_env(monkeypatch, {"/sto/stk_bydd_trd": novol})
    prev_kospi = {"up": 9, "down": 9, "flat": 9, "limitUp": 0, "limitDown": 0, "as_of": "2026-09-26"}
    data = _blank()
    fd._krx_a19(data, {"marketBreadth": {"kospi": prev_kospi}})
    assert data["marketBreadth"]["kospi"]["preserved"] is True and data["marketBreadth"]["kospi"]["up"] == 9


def test_krx_401_is_per_endpoint(monkeypatch):
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        ep = url.replace(fd.KRX_BASE, "")
        calls.append(ep)
        return _Resp({}, 401) if ep.startswith("/sto/") else _Resp({"OutBlock_1": INDEX_ROWS})

    _krx_env(monkeypatch, {})
    monkeypatch.setattr(fd, "requests", types.SimpleNamespace(get=get))
    data = _blank()
    fd._krx_a19(data, prev={})
    # 승인 전 /sto/ 일별매매(401)가 승인된 지수 호출을 막지 않는다
    assert data["sectorMoves"]["items"] and "marketBreadth" not in data
    assert calls.count("/sto/stk_bydd_trd") == 1 and calls.count("/sto/ksq_bydd_trd") == 1


def test_a19_nothing_to_preserve_leaves_keys_absent(monkeypatch):
    _krx_env(monkeypatch, {}, key="")
    data = _blank()
    fd._krx_a19(data, prev={})
    assert "marketBreadth" not in data and "sectorMoves" not in data     # 판정표가 missing 으로 센다


# ── 비미국 경제 일정 파서 (실제 페이지 발췌) ───────────────────────────────────
def test_bok_schedule_parser():
    ev = fd._parse_bok_mpc(_fix("bok_mpc_2026.html"))
    assert [e["iso"] for e in ev] == ["2026-01-15", "2026-02-26", "2026-04-10", "2026-05-28",
                                      "2026-07-16", "2026-08-27", "2026-10-22", "2026-11-26"]
    e = ev[6]
    assert e["dt"] == "10.22 09:00" and e["cc"] == "KR" and e["stars"] == 3 and e["timeApprox"] is True
    assert e["source"].startswith("https://www.bok.or.kr/") and e["name"] in fd.CAL_DECISION_NAMES
    assert fd._parse_bok_mpc("<html>no year</html>") == []


def test_ecb_schedule_parser_and_cet_to_kst():
    ev = fd._parse_ecb_mpm(_fix("ecb_mgcgc.html"))
    # Day 1 · 비통화정책 회의 · 일반이사회는 빼고, 기자회견이 있는 결정일만
    assert [e["iso"] for e in ev] == ["2026-10-29", "2026-12-17", "2027-02-04", "2027-03-18"]
    assert ev[0]["dt"] == "10.29 22:15" and ev[0]["cc"] == "EU"          # 10/25 서머타임 종료 뒤 → CET+8
    assert fd._ecb_kst(date(2026, 7, 23)) == "21:15"                      # CEST+7
    assert fd._ecb_kst(date(2026, 3, 29)) == "21:15" and fd._ecb_kst(date(2026, 3, 28)) == "22:15"
    assert fd._ecb_kst(date(2026, 10, 24)) == "21:15" and fd._ecb_kst(date(2026, 10, 25)) == "22:15"


def test_boj_schedule_parser_takes_last_day():
    ev = fd._parse_boj_mpm(_fix("boj_mpmsche.html"))
    isos = [e["iso"] for e in ev]
    assert isos[:8] == ["2026-01-23", "2026-03-19", "2026-04-28", "2026-06-16",
                        "2026-07-31", "2026-09-18", "2026-10-30", "2026-12-18"]
    assert "2027-01-22" in isos and ev[0]["cc"] == "JP" and ev[0]["timeApprox"] is True
    # 달을 넘는 회합 — 둘째 날의 달을 따른다
    cross = ('<h2 id="p2027">2027</h2><table><tbody><tr><td><a>Apr. 30 (Fri.), May 1 (Sat.) [PDF 1KB]</a></td>'
             '<td>-</td></tr><tr><td>Sept. 21 (Tues.), 22 (Wed.)</td></tr></tbody></table>')
    assert [e["iso"] for e in fd._parse_boj_mpm(cross)] == ["2027-05-01", "2027-09-22"]


def test_kostat_plan_parser_picks_three_releases():
    ev = fd._parse_kostat_plan(_fix("kostat_newspln_all.html"))
    got = [(e["iso"], e["dt"], e["name"], e["stars"], e["refPeriod"]) for e in ev]
    assert got[:3] == [("2026-09-02", "09.02 08:00", "한국 소비자물가동향", 3, "2026-08"),
                       ("2026-09-09", "09.09 08:00", "한국 고용동향", 2, "2026-08"),
                       ("2026-09-30", "09.30 08:00", "한국 산업활동동향", 2, "2026-08")]
    # 짝이 되는 잎이 없는 둘(전산업생산·취업자 증감)은 표 밖 — 소비자물가동향만 cpi_kr 로 연결(refPeriod 월 관측만 act)
    assert {e["name"] for e in ev if e["name"] in fd.CALENDAR_INDICATOR_MAP} == {"한국 소비자물가동향"}
    one = ('<h3>2026년 전체 보도계획</h3><table><tr class="tr-notice"><td>12.31.( 목 )</td><td>08:00</td>'
           '<td>2026년 12월 및 연간 소비자물가동향</td></tr><tr class="tr-notice"><td>09.10.( 목 )</td>'
           '<td>12:00</td><td>국가데이터처, 추석 일일물가조사로 민생안정대책 신속 지원</td></tr></table>')
    assert [(e["iso"], e["refPeriod"]) for e in fd._parse_kostat_plan(one)] == [("2026-12-31", "2026-12")]


# ── 일일 lane · 보존 · 병합 ─────────────────────────────────────────────────
def _cal_env(monkeypatch, pages, fail=()):
    got = []

    def cal_get(url):
        got.append(url)
        if any(url.startswith(f) for f in fail):
            raise RuntimeError("boom")
        for prefix, name in pages.items():
            if url.startswith(prefix):
                return _fix(name)
        return "<html></html>"

    monkeypatch.setattr(fd, "_cal_get", cal_get)
    monkeypatch.setattr(fd, "log", lambda *a, **k: None)
    return got


PAGES = {fd._BOK_MPC_URL: "bok_mpc_2026.html", fd._ECB_MPM_URL: "ecb_mgcgc.html",
         fd._BOJ_MPM_URL: "boj_mpmsche.html", fd._KOSTAT_URL: "kostat_newspln_all.html",
         fd._FOMC_URL: "fomc_calendars.html"}
TODAY = date(2026, 9, 30)


def test_intl_calendar_daily_fetch_window_and_status(monkeypatch):
    got = _cal_env(monkeypatch, PAGES)
    ev, st = fd.fetch_intl_calendar([], daily=True, today=TODAY)
    isos = {e["iso"] for e in ev}
    assert st == {"bok": 2, "ecb": 1, "boj": 2, "fomc": 3, "kostat": 3}, st          # 9/16 ~ 12/14 창
    assert {"2026-09-18", "2026-09-30", "2026-10-22", "2026-10-29", "2026-11-26"} <= isos
    assert "2026-12-17" not in isos                                        # 창(75일 뒤) 밖 — 10/2 부터 보인다
    assert "2026-09-02" not in isos                                        # 창(14일 전) 밖
    assert not any("pYear=" in u for u in got)                              # 창이 올해 안 — 이듬해 쪽은 안 본다
    got.clear()
    fd.fetch_intl_calendar([], daily=True, today=date(2026, 11, 1))       # 창이 2027-01-15 까지
    assert any(u.endswith("&pYear=2027") for u in got)                    # 비어 있어도(아직 미공표) 실패가 아니다


def test_intl_calendar_hourly_carries_and_failed_source_preserves(monkeypatch):
    _cal_env(monkeypatch, PAGES)
    prev, _ = fd.fetch_intl_calendar([], daily=True, today=TODAY)
    got = _cal_env(monkeypatch, PAGES)
    ev, st = fd.fetch_intl_calendar(prev, daily=False, today=TODAY)       # 매시 런 — 안 묻고 잇는다
    assert got == [] and set(st.values()) == {"carried"} and len(ev) == len(prev)
    got = _cal_env(monkeypatch, PAGES, fail=(fd._ECB_MPM_URL,))
    ev, st = fd.fetch_intl_calendar(prev, daily=True, today=TODAY)        # 일일 런에서 ECB 실패
    assert st["ecb"] == "failed" and st["bok"] == 2
    ecb = [e for e in ev if e["cc"] == "EU"]
    assert len(ecb) == 1 and all(e["preserved"] is True and e["preservedAt"] for e in ecb)
    assert not any(e.get("preserved") for e in ev if e["cc"] != "EU")
    got = _cal_env(monkeypatch, PAGES)
    ev2, st2 = fd.fetch_intl_calendar(ev, daily=False, today=TODAY)       # 보존 표식이 남은 원천만 매시 재시도
    assert st2["ecb"] == 1 and st2["bok"] == "carried" and got == [fd._ECB_MPM_URL]
    assert not any(e.get("preserved") for e in ev2)


def test_intl_calendar_keeps_past_meetings_the_page_dropped(monkeypatch):
    # ECB 페이지는 앞으로의 일정만 싣는다 — 10/29 가 지난 뒤 받은 페이지엔 그날이 없다
    past = fd._cal_event("EU", "ECB 통화정책 결정", 3, date(2026, 10, 29), "22:15", fd._ECB_MPM_URL,
                         preserved=True, preservedAt="2026-10-30T09:00:00+09:00")
    later = ('<dl><dt>17/12/2026</dt><dd>Governing Council of the ECB: monetary policy meeting (Day 2), '
             'followed by press conference</dd></dl>')
    monkeypatch.setattr(fd, "_cal_get", lambda url: later if url.startswith(fd._ECB_MPM_URL) else "<html></html>")
    monkeypatch.setattr(fd, "log", lambda *a, **k: None)
    ev, st = fd.fetch_intl_calendar([past, dict(past, iso=None)], daily=True, today=date(2026, 11, 2))
    ecb = [e for e in ev if e["cc"] == "EU"]
    assert [e["iso"] for e in ecb] == ["2026-12-17", "2026-10-29"] and st["ecb"] == 1
    assert "preserved" not in ecb[1]          # 지난 일정은 안 바뀐다 — 표식을 떼야 매시 재조회가 멈춘다


def test_calendar_block_marks_fred_outage_preserved():
    prev = [{"iso": "2026-09-25", "dt": "09.25 21:30", "name": "미국 GDP", "source": "FRED:release_id=14"}]
    kr = [{"iso": "2026-10-02", "dt": "10.02 08:00", "name": "한국 소비자물가동향", "source": fd._KOSTAT_URL}]
    blk = fd._calendar_block({"events": [], "source": "FRED release dates API"}, kr, prev, today=TODAY)
    assert blk["preserved"] is True and blk["preservedAt"] and len(blk["events"]) == 2
    assert "국가데이터처" in blk["source"]
    ok = fd._calendar_block({"events": list(prev), "source": "FRED"}, kr, prev, today=TODAY)
    assert "preserved" not in ok                                        # FRED 를 받았으면 블록 표식 없음
    import data_sla
    h = data_sla.build_health({"economicCalendar": blk}, today=TODAY)
    assert {i["path"]: i for i in h["items"]}["economicCalendar"]["state"] == "preserved"


def test_intl_calendar_empty_parse_is_not_silent(monkeypatch):
    _cal_env(monkeypatch, {k: v for k, v in PAGES.items() if k != fd._BOJ_MPM_URL})   # BOJ 페이지 구조 바뀜
    ev, st = fd.fetch_intl_calendar([], daily=True, today=TODAY)
    assert st["boj"] == "empty" and not any(e["cc"] == "JP" for e in ev)


def test_merge_keeps_us_events_and_dedupes():
    us = [{"iso": "2026-10-14", "dt": "10.14 21:30", "name": "미국 CPI (전월비)", "source": "FRED:release_id=10"}]
    kr = [{"iso": "2026-10-02", "dt": "10.02 08:00", "name": "한국 소비자물가동향", "source": fd._KOSTAT_URL}]
    out = fd._merge_calendar(us, kr + kr, prev_events=[], today=TODAY)
    assert [e["name"] for e in out] == ["한국 소비자물가동향", "미국 CPI (전월비)"]   # 날짜순, 중복 1건 제거
    # FRED 가 비면 직전 FRED 일정을 보존 표식으로 잇는다(비미국만 남아 미국 일정이 사라지지 않게)
    old = us + [{"iso": "2026-08-01", "dt": "08.01 21:30", "name": "옛", "source": "FRED:release_id=11"}]
    out = fd._merge_calendar([], kr, prev_events=old + kr, today=TODAY)
    fred = [e for e in out if e["source"].startswith("FRED:")]
    assert [e["iso"] for e in fred] == ["2026-10-14"] and fred[0]["preserved"] is True
    assert len(out) == 2


# ── 리드 추가 3건 (A·B·C) ───────────────────────────────────────────────────
def test_ecos_source_prefix_is_added_once(monkeypatch):
    monkeypatch.setattr(fd, "fetch_ecos_series", lambda *a, **k: [{"TIME": "202609", "DATA_VALUE": "79"}])
    assert fd._ecos_latest("512Y013", "C0000/AA", "M", "BSI", "ECOS:512Y013/C0000/AA")["source"] == "ECOS:512Y013/C0000/AA"
    assert fd._ecos_latest("722Y001", "0101000", "M", "기준금리", "722Y001")["source"] == "ECOS:722Y001"


def test_rone_misread_tables_renamed_and_daily_table_probe(monkeypatch):
    monkeypatch.setattr(fd, "REALESTATE_API_KEY", "k")
    monkeypatch.setattr(fd, "fetch_rone_nationwide_latest",
                        lambda sid, limit=600, itm_id=None, **k: {"value": 1.0, "period": "202608", "history": {}})
    cats, logs = [], []

    def cat(kw, cycle_code="MM", limit=200):
        cats.append((kw, cycle_code, limit))
        return [("A_X_1", "(월) 미분양주택현황"), ("A_X_2", "(월) 매매가격지수")] if kw == "" else []

    monkeypatch.setattr(fd, "fetch_rone_table_catalog", cat)
    monkeypatch.setattr(fd, "fetch_rone_sigungu_breakdown", lambda *a, **k: None)

    def offline(*a, **k):
        raise RuntimeError("offline")                                   # 옛 R-ONE 주소(legacy) 등 실제 호출 차단

    monkeypatch.setattr(fd, "requests", types.SimpleNamespace(get=offline, post=offline))
    monkeypatch.setattr(fd, "log", logs.append)
    monkeypatch.setenv("AV_FETCH_FULL", "1")
    res = fd.fetch_realestate_kr()
    a, s = res["avg_jeonse_price_kr"], res["semi_jeonse_idx_kr"]
    assert a["source"] == "R-ONE:A_2024_00064" and a["unit"] == "천원" and "평균 전세가격" in a["desc"]
    assert s["source"] == "R-ONE:A_2024_00057" and "준전세가격지수" in s["desc"]
    assert "unsold_kr" not in res and "start_kr" not in res
    probe = [m for m in logs if "R-ONE-probe" in m]
    assert ("", None, 1000) in cats and len(probe) == 1 and "A_X_1" in probe[0] and "A_X_2" not in probe[0]
    cats.clear()
    monkeypatch.setenv("AV_FETCH_FULL", "")                              # 일일 런이 아니면 목록을 묻지 않는다
    fd.fetch_realestate_kr()
    assert ("", None, 1000) not in cats
