"""investor_flows 교차검증 가드 — 알림에 틀린 수급 숫자가 실리는 회귀를 막는다.

계약(2026-09-11 기획 .omc/plans/investor-flow-mismatch-fix.md):
  1. 표시값은 네이버(포털·언론 기준), 토스는 교차검증용.
  2. 총체적 불일치(부호 뒤집힘·상대차 35% 초과)면 **숫자를 내보내지 않는다**.
  3. 오늘 날짜 행이 없으면 None — 묵은 값을 오늘 카드에 쓰지 않는다.
  4. 미검증이면 카드 대신 '집계 중' 문구.

실행: python -m pytest scripts/tests/test_investor_flows.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import investor_flows as inf  # noqa: E402
import send_kakao_digest as skd  # noqa: E402

NAV = {"date": "2026-09-11", "foreign": -22915.0, "inst": -12253.0, "retail": 18675.0}
TOS = {"date": "2026-09-11", "foreign": -24361.0, "inst": -12500.0, "retail": 18900.0,
       "updatedAt": "2026-09-11T20:00:02.000+09:00"}


def test_agree_within_relative_tolerance():
    a = {"foreign": -20000.0, "inst": 5000.0, "retail": 15000.0}
    b = {"foreign": -20500.0, "inst": 5100.0, "retail": 15300.0}     # 최대 2.5%
    ok, worst = inf.agree(a, b)
    assert ok is True
    assert worst < 0.03


def test_agree_rejects_beyond_tolerance():
    ok, worst = inf.agree(NAV, {"foreign": -24361.0, "inst": -12253.0, "retail": 18675.0})
    assert ok is False                      # 외국인 6% 차 — 실측된 09-11 불일치
    assert round(worst, 3) == 0.059


def test_agree_absolute_floor_allows_small_numbers():
    """작은 값은 상대차가 커도 절대 200억 안이면 일치로 본다(0 근처 노이즈)."""
    ok, _ = inf.agree({"foreign": 50.0, "inst": -30.0, "retail": -20.0},
                      {"foreign": -60.0, "inst": 20.0, "retail": 40.0})
    assert ok is True


def test_gross_mismatch_blocks_sign_flip():
    bad = inf.gross_mismatch({"foreign": -5000.0, "inst": 1000.0, "retail": 4000.0},
                             {"foreign": +5000.0, "inst": 1000.0, "retail": -6000.0})
    assert bad and "foreign" in bad and "부호" in bad


def test_gross_mismatch_ignores_sign_flip_near_zero():
    """부호가 달라도 양쪽 모두 1,000억 미만이면 총체적 오류가 아니다."""
    assert inf.gross_mismatch({"foreign": 120.0, "inst": 200.0, "retail": -320.0},
                              {"foreign": -130.0, "inst": 210.0, "retail": -80.0}) is None


def test_gross_mismatch_blocks_large_relative_gap():
    """실측 2026-09-10: 기관 토스 -134 vs 네이버 +5,744 → 차단되어야 한다."""
    nav = {"foreign": -26217.0, "inst": 5744.0, "retail": 3802.0}
    tos = {"foreign": -28768.0, "inst": -134.0, "retail": 12524.0}
    assert inf.gross_mismatch(nav, tos) is not None


def test_gross_mismatch_passes_small_gap():
    assert inf.gross_mismatch(NAV, TOS) is None


def test_verified_latest_uses_naver_values(monkeypatch):
    monkeypatch.setattr(inf, "naver_daily", lambda *a, **k: [NAV])
    monkeypatch.setattr(inf, "toss_daily", lambda *a, **k: [TOS])
    out = inf.verified_latest("KOSPI", today="2026-09-11")
    assert out["foreign"] == NAV["foreign"] and out["inst"] == NAV["inst"]
    assert out["primary"] == "naver" and out["cross"] == "toss"
    assert out["confirmed"] is True and out["reason"] == "확정"     # updatedAt 20시
    assert out["agree"] is False and out["maxDiffPct"] == 5.9       # 값은 싣되 불일치는 기록


def test_confirmed_by_clock_when_snapshot_has_no_updated_at(monkeypatch):
    """CI 회귀 가드 — 토스 403 → 스냅샷(updatedAt 없음) 경로에서도 19시 이후면 확정.

    2026-09-11 20시 런 실측: updatedAt 에만 의존해 20시에도 '잠정'이 되어
    확정 수급 줄이 한 번도 실리지 않았다.
    """
    import datetime as _dt
    monkeypatch.setattr(inf, "naver_daily", lambda *a, **k: [NAV])
    monkeypatch.setattr(inf, "toss_daily", lambda *a, **k: [dict(TOS, updatedAt=None)])
    at20 = _dt.datetime(2026, 9, 11, 20, 5, tzinfo=inf.KST)
    out = inf.verified_latest("KOSPI", today="2026-09-11", now=at20)
    assert out["confirmed"] is True and out["reason"] == "확정"
    at17 = _dt.datetime(2026, 9, 11, 17, 5, tzinfo=inf.KST)
    assert inf.verified_latest("KOSPI", today="2026-09-11", now=at17)["reason"] == "잠정"


def test_confirmed_clock_rule_needs_same_day(monkeypatch):
    """어제 날짜를 오늘 20시에 조회해도 '확정'을 자칭하지 않는다."""
    import datetime as _dt
    monkeypatch.setattr(inf, "naver_daily", lambda *a, **k: [dict(NAV, date="2026-09-10")])
    monkeypatch.setattr(inf, "toss_daily", lambda *a, **k: [
        dict(TOS, date="2026-09-10", updatedAt=None)])
    out = inf.verified_latest("KOSPI", today="2026-09-10",
                              now=_dt.datetime(2026, 9, 11, 20, 5, tzinfo=inf.KST))
    assert out["confirmed"] is False


def test_verified_latest_none_when_today_row_missing(monkeypatch):
    monkeypatch.setattr(inf, "naver_daily", lambda *a, **k: [NAV])   # 09-11 만 있음
    monkeypatch.setattr(inf, "toss_daily", lambda *a, **k: [TOS])
    assert inf.verified_latest("KOSPI", today="2026-09-12") is None


def test_verified_latest_none_on_gross_mismatch(monkeypatch):
    monkeypatch.setattr(inf, "naver_daily", lambda *a, **k: [NAV])
    monkeypatch.setattr(inf, "toss_daily", lambda *a, **k: [
        dict(TOS, foreign=+22915.0)])                                # 부호 뒤집힘
    assert inf.verified_latest("KOSPI", today="2026-09-11") is None


def test_verified_latest_falls_back_to_toss(monkeypatch):
    """네이버가 죽어도 수급이 사라지지 않는다 — 2026-09-21 실측: investorDealTrendDay 가
    HTTP 410(Gone). 그대로 두면 수급 줄이 영영 안 뜨는데, 그 침묵은 '수급이 없는 날'과
    구별되지 않는다. 토스 값을 쓰되 교차검증을 못 했다는 사실을 표기에 남긴다."""
    import datetime as _dt

    def _gone(*a, **k):
        raise OSError("HTTP Error 410: 410")
    monkeypatch.setattr(inf, "naver_daily", _gone)
    # 포털 기준의 두 번째 창구(data.json 의 KRX 확정치)도 없는 상황 — 실제 data.json 에
    # 기대지 않게 비운다(첫 운영 런 이후 krxDaily 가 생겨 이 테스트가 환경에 따라 갈렸다).
    monkeypatch.setattr(inf, "_krx_daily_from_data", lambda market="KOSPI": [])
    monkeypatch.setattr(inf, "toss_daily", lambda *a, **k: [TOS])
    # KRX 확정치(data.json krxDaily)도 없는 날 — 실제 data.json 을 읽으면 그날 행이 있어
    # 토스 단독 경로가 검사되지 않는다(ac048698 이후 KRX 가 먼저다).
    monkeypatch.setattr(inf, "_krx_daily_from_data", lambda *a, **k: [])
    out = inf.verified_latest("KOSPI", today="2026-09-11",
                              now=_dt.datetime(2026, 9, 11, 20, 5, tzinfo=inf.KST))
    assert out and out["primary"] == "toss" and out["cross"] is None
    assert out["agree"] is None
    assert "토스 단독" in out["reason"], out["reason"]
    assert out["foreign"] == TOS["foreign"]
    # 네이버도 토스도 오늘 행이 없으면 종전대로 침묵한다(값을 지어내지 않는다).
    monkeypatch.setattr(inf, "toss_daily", lambda *a, **k: [])
    assert inf.verified_latest("KOSPI", today="2026-09-11") is None


def test_verified_latest_allows_naver_only(monkeypatch):
    """토스 키가 없는 환경(CI) — 교차검증 불가라도 포털값은 '틀린 값'이 아니다."""
    monkeypatch.setattr(inf, "naver_daily", lambda *a, **k: [NAV])
    monkeypatch.setattr(inf, "toss_daily", lambda *a, **k: [])
    out = inf.verified_latest("KOSPI", today="2026-09-11")
    assert out and out["agree"] is None and out["cross"] is None


def test_toss_daily_falls_back_to_snapshot(monkeypatch):
    """CI 에선 토스 라이브가 403 이다 — PC 스냅샷으로 교차검증이 살아 있어야 한다."""
    import toss_api
    monkeypatch.setattr(toss_api, "CLIENT_ID", "")           # enabled() False
    monkeypatch.setattr(inf, "_toss_snapshot_daily", lambda *a, **k: [dict(TOS)])
    assert inf.toss_daily("KOSPI") == [dict(TOS)]


def test_toss_snapshot_daily_skips_malformed_rows(tmp_path, monkeypatch):
    import json
    snap = {"investorDaily": [
        {"date": "2026-09-10", "foreign": -1.0, "inst": 2.0, "retail": -1.0},
        {"date": "2026-09-11", "foreign": None, "inst": 2.0, "retail": -1.0},   # 결측
        {"foreign": 1.0, "inst": 2.0, "retail": -3.0},                          # 날짜 없음
    ]}
    p = tmp_path / "toss_snapshot.json"
    p.write_text(json.dumps(snap), encoding="utf-8")
    monkeypatch.setattr(os.path, "dirname", lambda _p: str(tmp_path))
    monkeypatch.setattr(os.path, "join", lambda *a: str(p))
    rows = inf._toss_snapshot_daily("KOSPI")
    assert [r["date"] for r in rows] == ["2026-09-10"]


def test_week_sum_needs_full_window(monkeypatch):
    rows = [dict(NAV, date=f"2026-09-0{i}") for i in range(4, 9)]
    monkeypatch.setattr(inf, "naver_daily", lambda *a, **k: rows)
    w = inf.week_sum("KOSPI", 5)
    assert w["days"] == 5 and w["from"] == "2026-09-04" and w["to"] == "2026-09-08"
    assert w["foreign"] == NAV["foreign"] * 5
    # 네이버 창이 모자라면 토스로 폴백한다(2026-09-21: 네이버 410 Gone).
    trows = [dict(NAV, date=f"2026-09-1{i}") for i in range(1, 6)]
    monkeypatch.setattr(inf, "naver_daily", lambda *a, **k: rows[:3])
    monkeypatch.setattr(inf, "toss_daily", lambda *a, **k: trows)
    w = inf.week_sum("KOSPI", 5)
    assert w["days"] == 5 and w["from"] == "2026-09-11", w
    # 둘 다 모자라면 여전히 None — 3일치를 5일 합계라고 부르지 않는다.
    monkeypatch.setattr(inf, "toss_daily", lambda *a, **k: trows[:2])
    assert inf.week_sum("KOSPI", 5) is None


def test_asof_label():
    assert inf.asof_label({"date": "2026-09-11", "reason": "확정"}) == "09-11 확정"
    assert inf.asof_label(None) == ""


def test_digest_row_omits_number_when_unverified():
    lab, val, _ = skd._investor_row(None)
    assert "집계 중" in val
    assert not any(ch.isdigit() for ch in val)      # 숫자 금지 — 이게 이 수정의 핵심 계약


def test_digest_row_carries_asof():
    lab, val, _ = skd._investor_row(dict(NAV, reason="확정"))
    assert "외국인 -22,915억" in val and "기관 -12,253억" in val and "09-11 확정" in val


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_portal_daily_falls_back_to_krx_when_naver_gone(monkeypatch):
    """네이버 410(2026-09-21) 이후 포털 기준은 data.json 의 KRX 확정치(krxDaily)다."""
    import investor_flows as f

    def gone(*a, **k):
        raise RuntimeError("HTTP Error 410: Gone")
    monkeypatch.setattr(f, "naver_daily", gone)
    monkeypatch.setattr(f, "_krx_daily_from_data",
                        lambda market="KOSPI": [{"date": "2026-09-23", "foreign": -3420.0,
                                                 "inst": 4074.0, "retail": -700.0}])
    rows, src = f.portal_daily("KOSPI")
    assert src == "krx" and rows[0]["inst"] == 4074.0
