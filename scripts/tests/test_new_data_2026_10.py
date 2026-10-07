#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""신규 데이터 3건(기획 v4 9장 후보 1·2·4) 검사 — 오프라인, 네트워크를 부르지 않는다.

  1. 시도 17 매매·전세 지수 시계열   realestate.kr.regionSeries  (R-ONE, 월 1회)
  2. KRX 보기 확장                  rankingsKr.marketCap·volume·high52·low52  (KRX OpenAPI 일별매매정보)
  3. 배당·실적 일정                 corpEvents  (OpenDART 공시검색·배당에 관한 사항, 일 1회)

응답 견본(scripts/tests/fixtures/)
  rone_A_2024_00045_cls500008.json · rone_A_2024_00050_cls500013.json — 2026-10-02 무키 실측 응답 그대로
      (무키는 앞 5행만 준다. list_total_count 274 = 2003-11 부터 한 분류 전체).
  dart_list_005930.json · dart_alotMatter_005930_2025.json — 2026-10-02 삼성전자 실제 응답에서 행만 추렸다
      (보고서명 뒤 공백·같은 날 [기재정정] 공시가 실제 모양이다).
  krx_stk_bydd_trd_spec.json — KRX 는 무키 401 이라 OpenAPI 명세(유가증권 일별매매정보 OutBlock_1) 필드로 만든 견본.

실행: python scripts/tests/test_new_data_2026_10.py      (pytest 로도 돈다)
"""
import copy
import io
import datetime as dt
import json
import os
import sys
import tempfile
import types
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import build_bundles as bb  # noqa: E402
import data_sla  # noqa: E402
import fetch_data as fd  # noqa: E402

FIX = os.path.join(HERE, "fixtures")


def _fix(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


class patch:
    """pytest 없이도 도는 속성 바꿔치기(with 블록이 끝나면 되돌린다)."""

    def __init__(self, obj, **kv):
        self.obj, self.kv, self.old = obj, kv, {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.old[k] = getattr(self.obj, k)
            setattr(self.obj, k, v)
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            setattr(self.obj, k, v)


LOGS = []
QUIET = patch(fd, log=LOGS.append)


# ── 1. R-ONE 시도 시계열 ─────────────────────────────────────────────────────────
def _rone_rows(name):
    return _fix(name)["SttsApiTblData"][1]["row"]


def _months(template, n, start=(2023, 1)):
    """실측 행 모양 그대로 n개월 행을 만든다(값만 바꾼다)."""
    y, m = start
    out = []
    for i in range(n):
        out.append(dict(template, WRTTIME_IDTFR_ID=f"{y}{m:02d}", DTA_VAL=90 + i * 0.1234567))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def test_rone_fixture_parses_real_rows():
    rows = _rone_rows("rone_A_2024_00045_cls500008.json")
    assert rows[0]["CLS_ID"] == 500008 and rows[0]["CLS_FULLNM"] == "서울"       # 실측: 정수 코드, 시도 이름 그대로
    with QUIET:
        s = fd._rone_class_series(rows, 500008, "11")
    assert [p[0] for p in s] == ["200311", "200312", "200401", "200402", "200403"]
    assert all(isinstance(p[1], float) and round(p[1], 3) == p[1] for p in s)
    gj = _rone_rows("rone_A_2024_00050_cls500013.json")
    assert gj[0]["CLS_FULLNM"] == "전남광주>광주"                                   # 실측: 광주·전남은 통합 권역 아래
    with QUIET:
        assert fd._rone_class_series(gj, 500013, "29")                               # 광주 = 29 로 읽힌다
        assert fd._rone_class_series(gj, 500013, "46") is None                       # 전남 칸에 광주 행이 오면 버린다
    assert fd.RONE_SIDO_CLS["29"] == 500013 and len(set(fd.RONE_SIDO_CLS.values())) == 17


def test_rone_series_keeps_last_36_and_rejects_bad_responses():
    tpl = _rone_rows("rone_A_2024_00045_cls500008.json")[0]
    rows = _months(tpl, 40)
    with QUIET:
        s = fd._rone_class_series(rows, 500008, "11")
        assert len(s) == 36 and s[0][0] == "202305" and s[-1][0] == "202604"
        other = dict(tpl, CLS_ID=500009, CLS_FULLNM="경기")
        assert fd._rone_class_series(rows + [other], 500008, "11") is None          # 필터가 안 먹어 다른 시도가 섞임
        assert fd._rone_class_series(_months(tpl, 1000), 500008, "11") is None       # 1000행 = 잘림
        two = rows + [dict(rows[-1], ITM_ID=100002)]
        assert fd._rone_class_series(two, 500008, "11") is None                      # 시점당 항목 2종
        assert fd._rone_class_series([], 500008, "11") is None
    assert any("필터가 안 먹었다" in m for m in LOGS) and any("잘림" in m for m in LOGS)


def _rone_env(by_cls, key="k" * 20):
    calls = []

    def stats(sid, item_code1=None, item_code2=None, item_code3=None, period_type="M",
              start_prd=None, end_prd=None, limit=24, page=1):
        calls.append((sid, item_code2))
        return by_cls.get((sid, item_code2))

    return calls, patch(fd, fetch_rone_stats=stats, REALESTATE_API_KEY=key, log=LOGS.append)


def _full_rone(tpl):
    out = {}
    for sid in fd.RONE_REGION_TABLES.values():
        for code, cls in fd.RONE_SIDO_CLS.items():
            full = ("전남광주>" if code in ("29", "46") else "") + bb.sido_names()[code]   # 실측 경로 모양
            out[(sid, str(cls))] = _months(dict(tpl, CLS_ID=cls, CLS_FULLNM=full, CLS_NM=full.split(">")[-1],
                                                STATBL_ID=sid), 40)
    return out


def test_rone_region_series_fetch_and_no_key_skip():
    tpl = _rone_rows("rone_A_2024_00045_cls500008.json")[0]
    calls, p = _rone_env(_full_rone(tpl))
    with p:
        out = fd.fetch_rone_region_series()
    assert len(calls) == 34 and len(out) == 17                                       # 시도 17 × 2표
    assert set(out["11"]) == {"apt", "jns", "period", "source"} and out["11"]["period"] == "202604"
    assert out["11"]["source"] == "R-ONE:A_2024_00045·A_2024_00050" and len(out["41"]["apt"]) == 36
    calls, p = _rone_env(_full_rone(tpl), key="")
    with p:
        assert fd.fetch_rone_region_series() == {} and calls == []                   # 키 없음 = 호출 0


def test_rone_region_series_monthly_gate():
    tpl = _rone_rows("rone_A_2024_00045_cls500008.json")[0]
    apt = {"apt_price_idx_kr": {"period": "202605", "source": "R-ONE:A_2024_00045"}}
    prs = {c: {"apt": [["202604", 1.0]], "jns": [["202604", 2.0]], "period": "202604", "source": "R-ONE:x",
               "preserved_reason": "lane"} for c in fd.RONE_SIDO_CLS}
    prev = {"realestate": {"kr": {"regionSeries": prs}}}
    calls, p = _rone_env(_full_rone(tpl))
    with p:
        same = fd._rone_region_series_step(prev, {"apt_price_idx_kr": dict(apt["apt_price_idx_kr"], period="202604")}, True)
        assert calls == [] and same["11"]["period"] == "202604" and "preserved_reason" not in same["11"]   # 최신 — 표식 지움
        # 일일 런 아님 — 호출 0, 직전 값을 표식 없이(직전 런 preserve-deep 이 단 preserved 도 걷는다 → lane 매시 재호출 끊김)
        marked = {"realestate": {"kr": {"regionSeries": {c: dict(n, preserved=True, preservedAt="t") for c, n in prs.items()}}}}
        hourly = fd._rone_region_series_step(marked, apt, False)
        assert calls == [] and "preserved" not in hourly["11"] and hourly["11"]["period"] == "202604"
        assert fd._rone_region_series_step({}, apt, False) is None
        ecos = fd._rone_region_series_step(prev, {"apt_price_idx_kr": {"period": "202605", "source": "ECOS"}}, True)
        assert calls == [] and ecos["11"]["period"] == "202604"                  # 전국이 R-ONE 이 아니면 새 달을 모른다
        new = fd._rone_region_series_step(prev, apt, True)                                                # 새 달 + 일일 런
    assert len(calls) == 34 and new["11"]["period"] == "202604" and len(new) == 17 and "preserved" not in new["11"]
    # 서울 전세 표만 빠지면 서울 칸은 직전 값(표식 없음 — 칸 날짜가 낡음을 말한다)을 두고, 다음 일일 런은 서울만 다시 묻는다.
    # preserved 를 달면 lane 계획이 R-ONE 묶음 전체를 매시 다시 부른다.
    data = _full_rone(tpl)
    del data[(fd.RONE_REGION_TABLES["jns"], "500008")]
    calls, p = _rone_env(data)
    apt6 = {"apt_price_idx_kr": dict(apt["apt_price_idx_kr"], period="202604")}
    behind = {"realestate": {"kr": {"regionSeries": {c: dict(n, apt=[["202603", 1.0]], period="202603")
                                                     for c, n in prs.items()}}}}
    with p:
        out = fd._rone_region_series_step(behind, apt6, True)
        assert len(calls) == 34                                            # 전 시도가 뒤처져 34콜
        assert out["11"]["apt"] == [["202603", 1.0]] and "preserved" not in out["11"] and "preserved_reason" not in out["11"]
        assert out["41"]["period"] == "202604" and len(out) == 17
        calls.clear()
        seoul_old = dict(out["11"], period="202603")                       # 서울만 뒤처진 상태
        fd._rone_region_series_step({"realestate": {"kr": {"regionSeries": dict(out, **{"11": seoul_old})}}}, apt6, True)
    assert calls == [(fd.RONE_REGION_TABLES["apt"], "500008"), (fd.RONE_REGION_TABLES["jns"], "500008")]   # 2콜
    # 새 달을 하나도 못 받아도(전 시도 실패) preserved 를 달지 않는다 — 매시 런이 지울 수 없는 표식이 lane 을 매시 깨운다
    calls, p = _rone_env({})
    with p:
        allfail = fd._rone_region_series_step(prev, apt, True)
    assert len(calls) == 34 and "preserved" not in allfail["11"] and allfail["11"]["apt"] == [["202604", 1.0]]
    lane = {"economicIndicators": {}, "realestate": {"kr": {"regionSeries": allfail}}}
    with patch(fd.os, environ={"FETCH_MACRO": "0"}):
        assert "rone" not in fd._macro_lane_plan(lane)                           # 매시 런이 R-ONE 을 다시 부르지 않는다


# ── 2. KRX 보기 확장 ─────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, payload, code=200):
        self.status_code, self._p = code, payload

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _krx_env(table, key="k" * 20, deny=()):
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        ep = url.replace(fd.KRX_BASE, "")
        calls.append(ep)
        if ep in deny:
            return _Resp({}, 401)
        return _Resp({"OutBlock_1": table.get(ep, [])})

    hilo = os.path.join(tempfile.mkdtemp(), "hilo.json")
    return calls, patch(fd, KRX_API_KEY=key, _KRX_DENIED=set(), _KRX_ROWS={}, KRX_HILO_FILE=hilo,
                        requests=types.SimpleNamespace(get=get), log=LOGS.append)


def _kosdaq(rows):
    return [dict(r, MKT_NM="KOSDAQ", ISU_CD="9" + r["ISU_CD"][1:]) for r in rows]


def test_krx_rows_read_new_fields():
    rows = fd._krx_stock_rows(_fix("krx_stk_bydd_trd_spec.json")["OutBlock_1"], "2026-09-30", "KOSPI")
    s = next(r for r in rows if r["code"] == "005930")
    assert (s["amount"], s["mktcap"], s["high"], s["low"], s["shares"]) == (1.27e12, 507431516750000.0, 85500.0, 83800.0,
                                                                           5969782550.0)


def test_krx_rankings_market_cap_and_volume():
    stk = _fix("krx_stk_bydd_trd_spec.json")["OutBlock_1"]
    calls, p = _krx_env({"/sto/stk_bydd_trd": stk, "/sto/ksq_bydd_trd": _kosdaq(stk)})
    data = {"rankingsKr": {"tradingAmount": [{"code": "000660"}], "as_of": "2026-10-01"}, "sources": {}}
    with p:
        fd._krx_rankings(data, {}, daily=False)
    rk = data["rankingsKr"]
    assert rk["tradingAmount"] and rk["as_of"] == "2026-10-01"                         # 토스 칸은 건드리지 않는다
    mc = rk["marketCap"]
    assert mc["as_of"] == "2026-09-30" and [r["code"] for r in mc["kospi"][:2]] == ["000660", "005930"]
    assert mc["kosdaq"][0]["market"] == "KOSDAQ" and mc["kospi"][0]["type"] == "STOCK"
    vol = rk["volume"]["kospi"]
    assert vol[0]["code"] == "456070" and "000040" not in [r["code"] for r in vol]     # 거래정지(거래량 0) 제외
    assert set(mc["kospi"][0]) >= {"name", "code", "price", "chg", "vol", "amount", "mktcap", "market", "as_of"}
    assert "high52" not in rk and "low52" not in rk                                    # 축적 0일 — 52주는 아직 안 싣는다
    assert data["sources"]["rankingsKr.marketCap"].startswith("KRX OpenAPI")
    assert sorted(set(calls)) == ["/sto/ksq_bydd_trd", "/sto/stk_bydd_trd"]            # 되짚기 없음(일일 런 아님)


def test_krx_rankings_401_and_no_key_carry_previous():
    prev = {"rankingsKr": {k: {"as_of": "2026-09-29", "kospi": [{"code": "005930", "price": 1}], "kosdaq": []}
                           for k in ("marketCap", "volume", "high52", "low52")}}
    calls, p = _krx_env({}, deny=("/sto/stk_bydd_trd", "/sto/ksq_bydd_trd"))
    data = {"sources": {}}
    with p:
        fd._krx_rankings(data, prev, daily=True)
        assert fd._KRX_DENIED == {"/sto/stk_bydd_trd", "/sto/ksq_bydd_trd"}           # 401 엔드포인트만 기록
    assert calls == ["/sto/stk_bydd_trd", "/sto/ksq_bydd_trd"]                         # 401 뒤 같은 표를 다시 안 부른다
    for k in ("marketCap", "volume", "high52", "low52"):
        node = data["rankingsKr"][k]
        assert node["preserved"] is True and node["kospi"][0]["code"] == "005930" and node["kospi"][0]["preserved"]
        assert "보존" in data["sources"][f"rankingsKr.{k}"]
    calls, p = _krx_env({}, key="")
    data = {"sources": {}}
    with p:
        fd._krx_rankings(data, {}, daily=True)
    assert calls == [] and "rankingsKr" not in data                                    # 키 없음 = 호출 0, 직전도 없으면 칸 없음


def test_krx_one_market_denied_keeps_other_and_carries_per_market():
    stk = _fix("krx_stk_bydd_trd_spec.json")["OutBlock_1"]
    prev = {"rankingsKr": {k: {"as_of": "2026-09-29", "kospi": [{"code": "OLDK", "price": 1}],
                               "kosdaq": [{"code": "OLDQ", "price": 1}], "count": {"kosdaq": 7}}
                           for k in ("marketCap", "volume", "high52", "low52")}}
    calls, p = _krx_env({"/sto/stk_bydd_trd": stk}, deny=("/sto/ksq_bydd_trd",))   # 코스닥만 미승인
    data = {"sources": {}}
    with p:
        fd._krx_rankings(data, prev, daily=True)
        state = fd._hilo_load()
    rk = data["rankingsKr"]
    mc = rk["marketCap"]
    assert mc["kospi"][0]["code"] == "000660" and "preserved" not in mc                # 받은 시장이 있으면 블록은 새 값
    assert mc["kosdaq"][0]["code"] == "OLDQ" and mc["kosdaq"][0]["preserved"] is True  # 못 받은 시장만 직전 행
    assert rk["high52"]["kosdaq"][0]["code"] == "OLDQ" and rk["high52"]["count"] == {"kosdaq": 7}
    assert "kospi" not in rk["high52"]                                                 # 받았지만 축적 중 = 잇지 않는다
    assert "2026-09-30" in state["days"]["kospi"] and len(state["days"]["kospi"]) == 1 + fd._HILO_BACKFILL
    assert "kosdaq" not in state["days"]                                               # 코스피 되짚기는 코스닥 401 과 무관하게 진행
    assert calls.count("/sto/ksq_bydd_trd") == 1                                       # 미승인 표는 되짚지 않는다


def test_krx_200_without_outblock_is_not_a_holiday():
    """한도·점검 같은 오류 JSON(200, 결과 칸 없음)은 빈 날로 담지 않는다 — 되짚기가 휴장으로 영구 기록하던 길."""
    def get(url, params=None, headers=None, timeout=None):
        return _Resp({"respCode": "E999", "respMsg": "한도 초과"})

    with patch(fd, KRX_API_KEY="k" * 20, _KRX_DENIED=set(), _KRX_ROWS={},
               requests=types.SimpleNamespace(get=get), log=LOGS.append):
        assert fd.fetch_krx("/sto/stk_bydd_trd", "20260929") is None and fd._KRX_ROWS == {}
        state = {"weeks": {}, "days": {}, "empty": {}}
        assert fd._hilo_backfill(state, "kospi", "/sto/stk_bydd_trd", "2026-09-30") == 1
    assert state["empty"]["kospi"] == [] and state["days"]["kospi"] == []


def _r(code, hi, lo, sh=1000, vol=10, cap=1, name=None):
    return {"code": code, "name": name or code, "vol": vol, "sect": "", "high": hi, "low": lo, "shares": sh,
            "mktcap": cap, "price": hi, "chg": 0.0, "market": "KOSPI", "as_of": None, "amount": 1}


def _year_state(last="2026-09-30"):
    """last 까지 364일 평일을 넣은 상태 — A 는 늘 100/90, B 는 한때 150, C 는 늘 50, D 는 최근 100일만, E 는 분할."""
    state, end = {"weeks": {}, "days": {"kospi": []}, "empty": {}}, dt.date.fromisoformat(last)
    d = end - dt.timedelta(days=fd._HILO_DAYS)
    while d < end:
        if d.weekday() < 5:
            day = d.isoformat()
            rows = [_r("A", 100, 90), _r("B", 150 if d.month == 3 else 110, 90), _r("C", 70, 50),
                    _r("E", 5000, 4000, sh=1000 if (end - d).days > 60 else 50000)]
            if (end - d).days < 100:
                rows.append(_r("D", 60, 55))
            fd._hilo_ingest(state, rows, day)
            state["days"]["kospi"].append(day)
        d += dt.timedelta(days=1)
    return state


def test_hilo_52_week_lists():
    state = _year_state()
    today = [_r("A", 120, 95, cap=3), _r("B", 120, 95, cap=9), _r("C", 60, 40, cap=2),
             _r("D", 999, 58), _r("E", 100, 80, sh=50000), _r("S", 999, 1, name="하나스팩1호")]
    fd._hilo_ingest(state, today, "2026-09-30")
    hi, lo, nh, nl = fd._hilo_lists(state, today, "2026-09-30", "kospi")
    assert [r["code"] for r in hi] == ["A"] and nh == 1          # B 는 3월 150 을 못 넘었다 · D 상장 1년 미만 · S 스팩
    assert [r["code"] for r in lo] == ["C"] and nl == 1          # E 는 분할(주식 수 50배)이라 뺀다
    assert hi[0]["type"] == "STOCK" and hi[0]["high"] == 120
    # 같은 날을 다시 넣어도 결과가 같다(매시 풀 런이 같은 전일 표를 또 읽는다)
    fd._hilo_ingest(state, today, "2026-09-30")
    assert fd._hilo_lists(state, today, "2026-09-30", "kospi")[:2] == (hi, lo)
    # 축적이 모자라면 None · 다른 시장 축적은 이 시장 판정에 안 쓴다
    short = {"weeks": state["weeks"], "days": {"kospi": state["days"]["kospi"][-100:]}, "empty": {}}
    assert fd._hilo_lists(short, today, "2026-09-30", "kospi") is None
    assert fd._hilo_lists(state, today, "2026-09-30", "kosdaq") is None


def test_hilo_backfill_holiday_and_error():
    stk = _fix("krx_stk_bydd_trd_spec.json")["OutBlock_1"]
    hol = "20260929"
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        ep, dd = url.replace(fd.KRX_BASE, ""), params["basDd"]
        calls.append((ep, dd))
        if dd == "20260925":
            raise RuntimeError("timeout")
        return _Resp({"OutBlock_1": [] if dd == hol else [dict(r, BAS_DD=dd) for r in stk]})

    state = {"weeks": {}, "days": {}, "empty": {}}
    with patch(fd, KRX_API_KEY="k" * 20, _KRX_DENIED=set(), _KRX_ROWS={},
               requests=types.SimpleNamespace(get=get), log=LOGS.append):
        n = fd._hilo_backfill(state, "kospi", "/sto/stk_bydd_trd", "2026-09-30", budget=5)
        assert fd._KRX_ROWS == {}                                    # 되짚기 행은 런 캐시에 남기지 않는다
    assert n == 3                                                    # 9/29(휴장) · 9/28 · 9/25(오류에서 멈춤)
    assert state["empty"]["kospi"] == ["2026-09-29"] and state["days"]["kospi"] == ["2026-09-28"]
    assert "2026-09-25" not in state["days"]["kospi"] + state["empty"]["kospi"]   # 오류 난 날은 다음 런에 다시
    assert state["weeks"]["2026-W40"]["005930"][:2] == [85500, 83800]
    # 휴장으로 적힌 날이 너무 많으면(잘못 적힌 것) 비운다 · 옛 모양 캐시는 빈 상태로 읽는다
    bad = {"weeks": {}, "days": {}, "empty": {"kospi": ["2026-09-%02d" % i for i in range(1, 29)]}}
    with patch(fd, log=LOGS.append):
        fd._hilo_prune(bad, "2026-09-30")
    assert bad["empty"]["kospi"] == []
    path = os.path.join(tempfile.mkdtemp(), "old.json")
    with open(path, "w") as f:
        json.dump({"weeks": {}, "days": ["2026-09-30"], "empty": []}, f)
    with patch(fd, KRX_HILO_FILE=path):
        assert fd._hilo_load() == {"weeks": {}, "days": {}, "empty": {}}
        fd._hilo_save({"weeks": {}, "days": {"kospi": ["2026-09-30"]}, "empty": {}})
        assert fd._hilo_load()["days"] == {"kospi": ["2026-09-30"]} and not os.path.exists(path + ".tmp")


def test_merge_newer_keeps_run_krx_lists():
    import merge_newer
    run = {"rankingsKr": {"marketCap": {"as_of": "2026-09-30", "kospi": ["new"]}}}           # 토스 칸 없음(PC 꺼짐)
    origin = {"rankingsKr": {"as_of": "2026-10-01", "tradingAmount": ["toss"],
                             "marketCap": {"as_of": "2026-09-29", "kospi": ["old"]},
                             "high52": {"as_of": "2026-09-29", "kospi": ["old52"]}}}
    rk = merge_newer.merge(run, origin)["rankingsKr"]
    assert rk["tradingAmount"] == ["toss"] and rk["marketCap"]["kospi"] == ["new"]
    assert "high52" not in rk                                                              # 이 런이 안 실은 52주는 되살리지 않는다
    newer = {"rankingsKr": {"as_of": "2026-10-02", "marketCap": {"as_of": "2026-10-01", "kospi": ["newer"]}}}
    run2 = {"rankingsKr": {"as_of": "2026-10-01", "marketCap": {"as_of": "2026-09-30", "kospi": ["new"]}}}
    assert merge_newer.merge(run2, newer)["rankingsKr"]["marketCap"]["kospi"] == ["newer"]


# ── 3. OpenDART 배당·실적 일정 ───────────────────────────────────────────────────
def test_dart_list_events_from_real_response():
    ev = fd._dart_list_events(_fix("dart_list_005930.json")["list"], "005930", "삼성전자")
    assert [(e["kind"], e["date"]) for e in ev] == [("dividend", "2026-07-30"), ("earnings", "2026-07-30")]
    earn = ev[1]
    assert earn["detail"] == "연결재무제표기준영업(잠정)실적(공정공시)"                  # 뒤 공백·[기재정정] 머리 제거
    assert earn["rcpNo"] == "20260730800103"                                         # 같은 날 둘 중 정정본(최신)
    assert ev[0]["title"] == "배당 결정" and earn["title"] == "잠정실적"
    sub = [{"report_nm": "현금ㆍ현물배당결정(자회사의 주요경영사항)", "rcept_dt": "20260801", "rcept_no": "1"}]
    assert fd._dart_list_events(sub, "x", "x") == []                                 # 자회사 공시는 남의 배당


def test_dart_dividend_event_from_real_response():
    dv = fd._dart_dividend_event(_fix("dart_alotMatter_005930_2025.json")["list"], "005930", "삼성전자", 2025)
    assert dv["kind"] == "dividend" and dv["date"] == "2025-12-31" and dv["title"] == "결산 배당 1,668원"
    assert dv["detail"] == "2025년 결산 보통주 주당 현금배당 1,668원 · 시가배당률 1.5%"   # 우선주 1,669원이 아니다
    assert fd._dart_dividend_event([], "x", "x", 2025) is None
    nodps = [{"se": "주당 현금배당금(원)", "stock_knd": "보통주", "thstrm": "-", "stlm_dt": "2025-12-31"}]
    assert fd._dart_dividend_event(nodps, "x", "x", 2025) is None                    # 무배당


def test_corp_targets_skip_etf_and_dedupe():
    cfg = os.path.join(tempfile.mkdtemp(), "cfg.json")
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"tracking": {"items": [
            {"symbol": "0018Z0", "market": "KR", "secType": "etf", "name": "RISE"},
            {"symbol": "005930", "market": "KR", "name": "삼성전자"},
            {"symbol": "AAPL", "market": "US", "name": "Apple"}]}}, f, ensure_ascii=False)
    ta = [{"code": "005930", "name": "삼성전자", "type": "STOCK"}, {"code": "102110", "name": "TIGER 200", "type": "ETF"},
          {"code": "000660", "name": "SK하이닉스", "type": "STOCK"}]
    assert fd._corp_targets({"rankingsKr": {"tradingAmount": ta}}, {}, cfg) == [("005930", "삼성전자"),
                                                                               ("000660", "SK하이닉스")]
    many = [{"code": f"{i:06d}", "type": "STOCK"} for i in range(50)]
    assert len(fd._corp_targets({}, {"rankingsKr": {"tradingAmount": many}}, cfg)) == fd.CORP_EVENTS_MAX


def _dart_env(fail=(), key="k" * 40):
    calls = []

    def dart_get(endpoint, **params):
        calls.append((endpoint, params.get("corp_code")))
        if params.get("corp_code") in fail:
            raise RuntimeError("DART list.json status=020 요청 제한")
        if endpoint == "list.json":
            assert params["pblntf_ty"] == "I" and params["page_count"] == 100
            return _fix("dart_list_005930.json") if params["corp_code"] == "00126380" else {"status": "013"}
        if endpoint == "alotMatter.json":
            return (_fix("dart_alotMatter_005930_2025.json") if params["corp_code"] == "00126380"
                    else {"status": "013"})
        raise AssertionError(endpoint)

    def get(url, params=None, timeout=None):        # 진짜 build_corp_map 이 이 get 으로 corpCode.xml(zip)을 받는다
        calls.append(("corpCode.xml", params.get("crtfc_key")))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("CORPCODE.xml", "<result><list><corp_code>00126380</corp_code><stock_code>005930</stock_code></list>"
                                       "<list><corp_code>00164779</corp_code><stock_code>000660</stock_code></list>"
                                       "<list><corp_code>00999999</corp_code><stock_code> </stock_code></list></result>")
        return types.SimpleNamespace(content=buf.getvalue(), raise_for_status=lambda: None)

    return calls, patch(fd, OPENDART_API_KEY=key, _dart_get=dart_get, log=LOGS.append,
                         requests=types.SimpleNamespace(get=get),
                         _corp_targets=lambda d, p: [("005930", "삼성전자"), ("000660", "SK하이닉스"),
                                                     ("005935", "삼성전자우")])


def test_corp_events_daily_once_and_skip_paths():
    calls, p1 = _dart_env()
    data = {"sources": {}}
    with p1:
        fd._corp_events_step(data, {}, daily=True)
    ce = data["corpEvents"]
    today = dt.datetime.now(fd.KST).date().isoformat()
    assert ce["asOf"] == today and ce["targets"] == 3
    assert ("corpCode.xml", "k" * 40) in calls                                        # 첫 런 = 목록 한 번(fetch_data 키·get 주입)
    assert ce["corpMap"] == {"005930": "00126380", "000660": "00164779", "005935": ""}  # 없는 종목(우선주)은 "" — 내일 재다운 안 함
    kinds = sorted((e["code"], e["kind"], e["date"]) for e in ce["items"])
    assert kinds == [("005930", "dividend", "2025-12-31"), ("005930", "dividend", "2026-07-30"),
                     ("005930", "earnings", "2026-07-30")]
    assert ce["items"][0]["date"] == "2026-07-30"                                     # 최신순
    # 같은 날 두 번째 일일 런(16·22시) — 공시검색만 다시, 배당 표·기업코드 목록은 안 부르고 결산 배당은 직전 것을 잇는다
    calls.clear()
    again = {"sources": {}}
    with p1:
        fd._corp_events_step(again, {"corpEvents": ce}, daily=True)
    assert sorted(c[0] for c in calls) == ["list.json", "list.json"]                  # 기업코드 있는 2종목 × 공시검색
    assert sorted((e["code"], e["kind"], e["date"]) for e in again["corpEvents"]["items"]) == kinds
    # 일일 런 아님 = 호출 0, 직전 블록 그대로
    calls.clear()
    hourly = {"sources": {}}
    with p1:
        fd._corp_events_step(hourly, {"corpEvents": ce}, daily=False)
    assert calls == [] and hourly["corpEvents"] is ce
    calls, p1 = _dart_env(key="")
    nokey = {"sources": {}}
    with p1:
        fd._corp_events_step(nokey, {"corpEvents": ce}, daily=True)
    assert calls == [] and nokey["corpEvents"] is ce                                  # 키 없음 = 호출 0, 직전 값 유지


def test_corp_events_failures_keep_previous():
    old = {"asOf": "2026-10-01", "items": [{"code": "000660", "kind": "earnings", "date": "2026-07-24", "name": "SK"}],
           "corpMap": {"005930": "00126380", "000660": "00164779", "005935": ""}}
    calls, p1 = _dart_env(fail=("00164779",))
    data = {"sources": {}}
    with p1:
        fd._corp_events_step(data, {"corpEvents": old}, daily=True)
    sk = [e for e in data["corpEvents"]["items"] if e["code"] == "000660"]
    assert sk and sk[0]["preserved"] is True and sk[0]["preservedAt"]                 # 한 종목 실패 = 그 종목 직전 일정
    assert not any(c[0] == "corpCode.xml" for c in calls)                             # 맵이 다 있으면 zip 안 받는다
    calls, p1 = _dart_env(fail=("00126380", "00164779"))
    data = {"sources": {}}
    with p1:
        fd._corp_events_step(data, {"corpEvents": old}, daily=True)
    assert data["corpEvents"]["preserved"] is True and data["corpEvents"]["asOf"] == "2026-10-01"   # 전부 실패 = 블록 보존
    # 기업코드 목록을 못 받아 매핑이 0 이면 실패다 — 빈 일정을 오늘 것처럼 쓰지 않는다
    calls, p1 = _dart_env()
    with p1, patch(fd, requests=types.SimpleNamespace(get=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("zip")))):
        data = {"sources": {}}
        fd._corp_events_step(data, {"corpEvents": dict(old, corpMap={})}, daily=True)
        assert data["corpEvents"]["preserved"] is True and data["corpEvents"]["asOf"] == "2026-10-01"
        empty = {"sources": {}}
        fd._corp_events_step(empty, {}, daily=True)
        assert "corpEvents" not in empty                                               # 직전도 없으면 블록을 안 쓴다
    # 대상에서 빠진 종목의 기업코드는 공개 파일에 남기지 않는다
    calls, p1 = _dart_env()
    with p1:
        data = {"sources": {}}
        fd._corp_events_step(data, {"corpEvents": dict(old, corpMap={**old["corpMap"], "111111": "00000001"})}, daily=True)
    assert "111111" not in data["corpEvents"]["corpMap"]


# ── 묶음·판정표 ──────────────────────────────────────────────────────────────────
DATA = bb.load("data.json")
MER = bb.load("mer_signals.json", {})
NOW = bb._iso_dt(DATA["lastUpdated"]).astimezone(bb.KST) + dt.timedelta(minutes=5)
# KRX 순위 기준일은 NOW 상대값 — 고정 날짜(2026-09-30)는 data_sla 의 rankingsKr 4일 SLA 를 넘기면 state 가 stale 로 바뀌어
# 테스트가 날짜 시한폭탄이 된다(2026-10-07 CI 실측 — pytest 마커 캐시가 깨진 날 전 런이 멈췄다).
RK_ASOF = (NOW.date() - dt.timedelta(days=1)).isoformat()
# 시도 지수 월 키도 같은 이유로 NOW 상대값 — 지난달 말이 월간 SLA(70일) 안이다(고정 202608 은 11월에 터졌다).
M_END = NOW.date().replace(day=1) - dt.timedelta(days=1)


def _ym(back: int) -> str:
    """지난달에서 back 달 전 → 'YYYYMM'."""
    y, m = M_END.year, M_END.month - back
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y}{m:02d}"


def _rich():
    """data.json + 신규 3블록(실제 크기: 시도 17×36×2, 시장별 20행×4, 일정 60건)."""
    d = copy.deepcopy(DATA)
    pts = [[_ym(35 - i), round(95 + i * 0.123456, 3)] for i in range(36)]          # 36개월, 끝 = 지난달
    # 봇이 갱신하는 저장소 data.json 에 기대지 않게 필요한 칸은 여기서 고정한다(시도 지도 17곳)
    kr = d.setdefault("realestate", {}).setdefault("kr", {})
    kr["region"] = [{"code": c, "val": 0.1, "period": pts[-1][0]} for c in fd.RONE_SIDO_CLS]
    kr["region_sub"] = {"11": {"period": pts[-1][0], "subs": [{"name": "강남구", "val": 0.5}], "source": "R-ONE:x"}}
    kr["regionSeries"] = {c: {"apt": pts, "jns": pts, "period": pts[-1][0], "source": "R-ONE:x"}
                          for c in fd.RONE_SIDO_CLS}
    row = lambda i, m: {"name": "종목%02d" % i, "code": "%06d" % i, "price": 85000.0, "chg": 1.19, "vol": 1.5e7,
                        "amount": 1.27e12, "mktcap": 5.07e14, "market": m, "as_of": RK_ASOF, "type": "STOCK",
                        "high": 85500.0, "low": 83800.0}
    rk = d.setdefault("rankingsKr", {})
    for k in ("marketCap", "volume", "high52", "low52"):
        rk[k] = {"as_of": RK_ASOF, "kospi": [row(i, "KOSPI") for i in range(20)],
                 "kosdaq": [row(i, "KOSDAQ") for i in range(20)]}
    rk["high52"]["count"] = {"kospi": 37, "kosdaq": 51}
    today = NOW.date().isoformat()
    d["corpEvents"] = {"asOf": today, "from": "2026-07-04", "source": "OpenDART", "targets": 30, "corpMap": {},
                       "items": [{"code": "005930", "name": "삼성전자", "kind": "earnings", "date": today,
                                  "title": "잠정실적", "detail": "연결재무제표기준영업(잠정)실적(공정공시)",
                                  "rcpNo": "20261008800077"}]
                                + [{"code": "%06d" % i, "name": "종목", "kind": "dividend", "date": "2026-08-%02d" % (i % 28 + 1),
                                    "title": "배당 결정", "detail": "현금ㆍ현물배당결정", "rcpNo": str(i)} for i in range(59)]}
    d["dataHealth"] = data_sla.build_health(d, today=NOW.date())
    return d


def test_bundles_carry_new_fields_within_200kb():
    b = bb.build_all(_rich(), MER, NOW)
    for name, obj in b.items():
        if not name.startswith("_"):
            assert len(bb.dumps(obj).encode("utf-8")) <= bb.MAX_BYTES, name
    v = b["market-domestic"]["views"]
    for k in ("marketCap", "volume", "high52", "low52"):
        assert len(v[k]["kospi"]) == 20 and len(v[k]["kosdaq"]) == 20 and v[k]["asOf"] == RK_ASOF
        assert v[k]["state"] in ("prev", "live") and v[k]["kospi"][0]["isEtf"] is False
    assert v["marketCap"]["kospi"][0]["marketCap"] == 5.07e14 and v["high52"]["count"] == {"kospi": 37, "kosdaq": 51}
    assert v["corpEvents"]["items"][0]["kind"] == "earnings" and len(v["corpEvents"]["items"]) == 60
    sched = b["home"]["schedule"]
    corp = [e for e in sched if e.get("kind")]
    assert [e["name"] for e in corp] == ["삼성전자 잠정실적"] and corp[0]["cc"] == "KR"     # 지난 공시는 홈 일정에 안 건다
    re_ = b["market-realestate"]["views"]
    cap = re_["capital"]
    assert set(cap) == set(bb.CAPITAL_AREA) and len(cap["11"]["series"]["apt"]) == 36
    assert cap["11"]["series"]["jns"][-1][0] == f"{M_END.year}-{M_END.month:02d}"          # 월 키는 화면 표기(YYYY-MM)
    assert all("series" in it for it in re_["regions"]["items"]) and re_["regions"]["seriesState"] == "prev"


def test_bundles_without_new_blocks_are_missing_not_broken():
    d = copy.deepcopy(DATA)
    for k in ("corpEvents",):
        d.pop(k, None)
    (d.get("rankingsKr") or {}).pop("marketCap", None)
    (d.get("realestate") or {}).get("kr", {}).pop("regionSeries", None)
    v = bb.build_all(d, MER, NOW)
    dom = v["market-domestic"]["views"]
    assert dom["marketCap"] == {"asOf": None, "state": "missing", "kospi": [], "kosdaq": []}
    assert dom["corpEvents"]["state"] == "missing" and dom["corpEvents"]["items"] == []
    assert v["market-realestate"]["views"]["regions"]["seriesState"] == "missing"


def test_health_judges_new_paths():
    h = {i["path"]: i for i in _rich()["dataHealth"]["items"]}
    assert h["corpEvents"]["state"] == "ok" and h["corpEvents"]["sla"] == 3            # 블록 하나(items 를 쪼개지 않는다)
    assert not any(p.startswith("corpEvents.") for p in h)
    assert h["realestate.kr.regionSeries"]["cadence"] == "monthly"                    # 첫 자식 period 로 주기 추론
    assert h["rankingsKr.high52"]["sla"] == 4 and h["rankingsKr.high52"]["tier"] == "important"
    # 주기를 몰라 60일 기본값으로 '지연'이던 region·region_sub 도 같은 수정으로 월간이 된다
    assert h["realestate.kr.region_sub"]["cadence"] == "monthly"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print("ok  " + t.__name__)
    print("%d개 통과" % len(tests))
