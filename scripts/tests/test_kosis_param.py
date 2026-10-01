"""KOSIS 통계표선택(Param) 호출 회귀 테스트 (오프라인 — 네트워크를 부르지 않는다).

종전 fetch_kosis_series 는 사전등록용 주소(statisticsData.do)에 userStatsId="" 로 보내 한 번도 성공하지 못했다.
실행: python -m pytest scripts/tests/test_kosis_param.py
"""
import os
import sys
import types

import requests as _rq

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fetch_data as fd  # noqa: E402


class _Resp:
    def __init__(self, payload, code=200):
        self.status_code, self._p = code, payload

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _env(monkeypatch, payload, key="k-test-12345"):
    calls, logs = [], []

    def get(url, params=None, headers=None, timeout=None):
        calls.append((url, dict(params or {})))
        return _Resp(payload(url, params) if callable(payload) else payload)

    monkeypatch.setattr(fd, "KOSIS_API_KEY", key)
    monkeypatch.setattr(fd, "requests", types.SimpleNamespace(get=get, exceptions=_rq.exceptions))
    monkeypatch.setattr(fd, "log", logs.append)
    return calls, logs


def test_series_uses_param_endpoint_without_user_stats_id(monkeypatch):
    calls, _ = _env(monkeypatch, [{"PRD_DE": "202608", "DT": "1"}])
    fd.fetch_kosis_series("101", "DT_1JG2105", "T2", "M", "202508", "202608")
    (url, p), = calls
    assert url == fd.KOSIS_PARAM_BASE and url.endswith("Param/statisticsParameterData.do")
    assert "userStatsId" not in p
    assert p["objL1"] == "ALL" and "objL2" not in p
    assert p["apiKey"] == "k-test-12345" and p["method"] == "getList"
    assert (p["orgId"], p["tblId"], p["itmId"], p["prdSe"]) == ("101", "DT_1JG2105", "T2", "M")
    assert (p["startPrdDe"], p["endPrdDe"], p["format"], p["jsonVD"]) == ("202508", "202608", "json", "Y")


def test_series_passes_obj_l1_and_l2_when_given(monkeypatch):
    calls, _ = _env(monkeypatch, [])
    fd.fetch_kosis_series("116", "DT_X", "T1", obj_l1="00", obj_l2="A")
    p = calls[0][1]
    assert p["objL1"] == "00" and p["objL2"] == "A"


def test_series_error_body_is_none_and_logged(monkeypatch):
    _, logs = _env(monkeypatch, {"err": "20", "errMsg": "필수요청변수값이 누락되었습니다."})
    assert fd.fetch_kosis_series("101", "DT_1JG2105", "T2") is None
    assert any("101/DT_1JG2105 오류 20: 필수요청변수값이 누락되었습니다." in m for m in logs)


def test_series_list_body_is_returned_as_is(monkeypatch):
    rows = [{"PRD_DE": "202608", "DT": "101.5"}]
    _env(monkeypatch, rows)
    assert fd.fetch_kosis_series("101", "DT_1JG2105", "T2") is rows


def test_series_without_key_does_not_call(monkeypatch):
    calls, _ = _env(monkeypatch, [], key="")
    assert fd.fetch_kosis_series("101", "DT_1JG2105", "T2") is None and calls == []


def test_probe_skips_without_key_or_daily_flag(monkeypatch):
    calls, logs = _env(monkeypatch, [], key="")
    monkeypatch.setenv("AV_FETCH_FULL", "1")
    fd.probe_kosis_housing_meta()                          # 키 없음
    calls2, _ = _env(monkeypatch, [])
    monkeypatch.setenv("AV_FETCH_FULL", "")
    fd.probe_kosis_housing_meta()                          # 일일 런 아님
    assert calls == [] and calls2 == [] and logs == []


def test_probe_logs_four_tables_with_get_meta(monkeypatch):
    meta = [{"OBJ_ID": "A", "OBJ_NM": "행정구역별", "ITM_ID": "00", "ITM_NM": "전국"},
            {"OBJ_ID": "A", "OBJ_NM": "행정구역별", "ITM_ID": "11", "ITM_NM": "서울"},
            {"OBJ_ID": "ITEM", "OBJ_NM": "항목", "ITM_ID": "T1", "ITM_NM": "미분양"}]
    calls, logs = _env(monkeypatch, meta)
    monkeypatch.setenv("AV_FETCH_FULL", "1")
    fd.probe_kosis_housing_meta()
    assert [c[0] for c in calls] == [fd.KOSIS_BASE] * 4
    assert [c[1]["tblId"] for c in calls] == ["DT_MLTM_2080", "DT_MLTM_5386", "DT_MLTM_5372", "DT_MLTM_1946"]
    assert all(c[1]["method"] == "getMeta" and c[1]["type"] == "ITM" and c[1]["orgId"] == "116" for c in calls)
    probe = [m for m in logs if m.startswith("[KOSIS-probe]")]
    assert len(probe) == 4
    assert "116/DT_MLTM_2080 ITM 3행" in probe[0]
    assert "A(행정구역별) 2종 [('00', '전국'), ('11', '서울')]" in probe[0]
    assert "ITEM(항목) 1종 [('T1', '미분양')]" in probe[0]


def test_probe_error_body_and_exception_only_log(monkeypatch):
    _, logs = _env(monkeypatch, {"err": "30", "errMsg": "조회결과가 없습니다."})
    monkeypatch.setenv("AV_FETCH_FULL", "1")
    fd.probe_kosis_housing_meta()                          # 예외 없이 4표를 다 돈다
    assert len([m for m in logs if "오류 30" in m]) == 4

    def boom(url, params=None, headers=None, timeout=None):
        raise ValueError("깨진 응답")

    monkeypatch.setattr(fd, "requests", types.SimpleNamespace(get=boom, exceptions=_rq.exceptions))
    logs.clear()
    fd.probe_kosis_housing_meta()
    assert len([m for m in logs if "오류(무시)" in m]) == 4


def test_retail_skips_candidate_with_mixed_rows_per_period(monkeypatch):
    # objL1=ALL 이라 같은 시점에 분류가 섞이면 덮어쓰지 않고 다음 후보로 간다. "ALL" 항목은 묻지 않는다.
    mixed = [{"PRD_DE": "202607", "DT": "100"}, {"PRD_DE": "202607", "DT": "80"},
             {"PRD_DE": "202608", "DT": "101"}, {"PRD_DE": "202608", "DT": "81"}]
    clean = [{"PRD_DE": "202607", "DT": "100"}, {"PRD_DE": "202608", "DT": "101.5"}]
    calls, logs = _env(monkeypatch, lambda url, p: clean if p["itmId"] == "T03" else mixed)
    got = fd.fetch_kosis_retail_sales()
    assert got["value"] == 101.5 and got["source"] == "KOSIS:DT_1JG2105/T03"
    assert [c[1]["itmId"] for c in calls] == ["T2", "T20", "13102803005A", "T03"]
    assert any("DT_1JG2105/T2: 같은 시점 행이 여럿" in m for m in logs)
