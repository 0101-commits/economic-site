"""알림 v2 시장 판정(A1~A5 · B1~B2 · C1~C8 · H1) — 고정 데이터(fixtures/v2)로 함수마다 걸림 · 안 걸림.

고정 데이터의 장면은 fixtures/v2/make_fixtures.py 주석에 있다. 검사마다 문맥을 새로 읽어 한 칸만 바꾼다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import check_swings as cs  # noqa: E402
import volatility as vol  # noqa: E402
from alerts_v2 import judges_market  # noqa: E402,F401  판정 함수 등록
from alerts_v2 import compose, schema  # noqa: E402
from alerts_v2.context import KST, Context  # noqa: E402
from alerts_v2.events import JUDGES, extract, run_event  # noqa: E402
from alerts_v2.ledger import Ledger, Row  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "v2")
NOW = dt.datetime(2026, 10, 5, 10, 30, tzinfo=KST)        # 월요일 장중
EVS = schema.by_id(schema.load_events())


def ctx(now=NOW):
    return Context.load(now=now, root=FIX)


def hits(c, eid):
    return run_event(c, EVS[eid])


def by_target(hs):
    return {h.target: h for h in hs}


def ind(c, iid):
    return next(i for i in c.mer["indicators"] if i["id"] == iid)


# ---- 등록 · 문맥 ----
def test_market_judges_registered_for_their_events():
    mine = ("A1", "A2", "A3", "A4", "A5", "B1", "B2", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "H1")
    for eid in mine:
        assert EVS[eid]["judge"] in JUDGES, eid


def test_context_single_source_reads():
    c = ctx()
    assert c.fresh("kospi") == "live"                        # 번들 칸은 신선도를 state 로 싣는다
    assert c.value("vix") == 26.0 and c.fresh("vix") == "prev"   # 띠가 아니라 보기 칸에만 있는 지표
    assert c.value("us10y") == 5.06                          # 만기 경로 yieldCurve.us:10Y(current 는 숫자 목록)
    assert c.value("jp30y") == 4.13                          # 레지스트리에 없는 대상 = 가상 행
    assert abs(c.value("btc") - c.series("btc", 1)[0]["close"]) < 1e-9   # 일봉 목록이면 끝 종가
    assert c.as_of("btc") == "2026-10-05" and c.fresh("btc") == "prev"


# ---- A1~A4 급변(σ) ----
def test_swing_sigma_hit_escalates_and_names_peer():
    h = by_target(hits(ctx(), "A1"))
    k = h["kospi"]
    assert (k.dir, k.chg, k.asOf, k.fresh) == ("down", -4.0, "2026-10-05", "live")
    assert k.fields["abs_z"] == 4.0 and k.fields["thr"] == 3.0      # 고정 단계(2026-11-06 P4) — 코스피 첫 단계 ±3%
    assert k.fields["tier"] == 3 and k.fields["next_tier"] == 5 and k.fields["zx"] == "4.0"
    assert "level" not in k.fields                           # 맨 위 단계(국내 ±5%)만 경보 — σ 4배여도 −4% 는 주의
    assert k.fields["peer"] == "KOSDAQ"                      # 같은 방향 1σ 이상(코스닥 −1.8σ)
    assert k.fields["next_round"] == 5000                    # B2 마디표(코스피 1000) 아래쪽 다음 마디


def test_run_event_reports_value_in_screen_units():
    """축척 지표(엔/원 scale 0.01)의 사전 알림 값은 화면 단위 — 문구가 화면(100엔당 원)과 같은 수를 말한다."""
    c = ctx()
    raw = by_target(hits(c, "A1"))["kospi"].value
    c.scale = lambda t: 0.01 if t == "kospi" else None
    assert abs(by_target(hits(c, "A1"))["kospi"].value - raw / 0.01) < 1e-6


def test_swing_sigma_clamp_upper_and_lower():
    h = by_target(hits(ctx(), "A1"))
    # 고정 단계: 코스닥 −5% 이상 = 맨 위 단계 → 경보(평소 움직임이 커서 z 1.8 이어도)
    q = h["kosdaq"]
    assert q.fields["thr"] == 3.0 and q.fields["tier"] == 5 and q.fields["abs_z"] < 2.5 and q.fields["level"] == "alarm"
    # S&P 500 +0.4% 는 첫 단계(±2%) 아래 → 안 걸림(σ 0.1% 라 z +4 여도)
    assert "sp500" not in h
    assert vol.clamp_threshold(0.1, 2.5, 0.5, 5.0) == 0.5
    assert vol.clamp_threshold(3.0, 2.5, 0.5, 5.0) == 5.0
    assert vol.clamp_threshold(None, 2.5, 0.5, 5.0, 2.0) == 2.0 and vol.clamp_threshold(None, 2.5, 0.5, 5.0) is None


def test_check_swings_breach_unchanged_by_extraction():
    alt = [100.0]
    for i in range(300):
        alt.append(alt[-1] * (1.01 if i % 2 else 0.99))
    fired, thr, why = cs._breach(3.0, alt + [alt[-1] * 1.03], 2.0)
    assert fired and abs(thr - 2.5 * vol.sigma(alt, exclude_last=False)) < 1e-9 and why.startswith("z ")
    assert cs._breach(1.5, [100, 101], 2.0) == (False, 2.0, "")      # σ 없음 → 폴백 2%
    assert cs._breach(6.0, [100, 101], 9.0)[:2] == (True, 5.0)       # 폴백도 상한 5% 로 자른다


def test_swing_sigma_needs_live_value():
    c = ctx()
    c.strip("kospi")["state"] = "prev"                      # 직전 종가로 「오늘 급변」을 말하지 않는다
    assert "kospi" not in by_target(hits(c, "A1"))
    assert hits(ctx(), "A2") == []                           # 달러-원 +0.2%


def test_swing_sigma_daily_bitcoin():
    h = hits(ctx(), "A4")
    assert [(x.target, x.dir, x.chg, x.fields["thr"]) for x in h] == [("btc", "up", 9.0, 4.0)]   # 사전 sigma 2.0 × σ 2%
    c = ctx()
    bars = c.data["history"]["crypto"]["BTC"]
    bars[-1]["close"] = round(bars[-2]["close"] * 1.03, 4)  # +3% < 5%
    assert hits(c, "A4") == []


# ---- A5 서킷브레이커 · 사이드카(거래소 공시, 2026-11-20) ----
def _notice(typ="sidecar", market="KOSPI", direction="down", stage=None, at="2026-10-05T10:01:05+09:00", pct=-5.04):
    import kind_notices
    t = dt.datetime.fromisoformat(at)
    title = {"sidecar": f"유가증권시장 {'매도' if direction == 'down' else '매수'} 사이드카(Side car) 발동",
             "circuit": f"유가증권시장 매매거래 일시중단({stage or 1}단계 CB 발동)"}[typ]
    by = "유가증권시장본부" if market == "KOSPI" else "코스닥시장본부"
    if market == "KOSDAQ":
        title = f"코스닥시장 프로그램{'매도' if direction == 'down' else '매수'}호가 일시효력정지(Sidecar 발동)"
    return kind_notices.to_halt({"time": t.strftime("%H:%M"), "title": title, "by": by, "acptno": "9"},
                                t.date().isoformat(), {"at": t, "pct": pct, "kind": "fut"})


def test_market_halt_quiet_without_halt():
    c = ctx()
    c._kind_cache = []                                       # 공시 읽음 · 시장조치 없음
    assert hits(c, "A5") == []


def test_market_halt_sidecar_from_kind_only_kospi():
    c = ctx()
    c._kind_cache = [_notice(), _notice(market="KOSDAQ", at="2026-10-05T10:03:00+09:00")]
    h = hits(c, "A5")
    assert [(x.target, x.dir, x.asOf) for x in h] == [("kospi", "enter", "2026-10-05.sidecar-down")]
    f = h[0].fields
    assert (f["halt_kind"], f["at"], f["approx"], f["source"]) == ("매도 사이드카", "10:01", "", "거래소 공시")
    assert f["halt_line"] == "코스피200 선물 -5.04%"
    r = compose.render(EVS["A5"], h[0], c)
    assert r["title"].endswith(" 매도 사이드카 발동") and r["body_push"] == "10:01 · 코스피200 선물 −5.04%", r


def test_market_halt_old_notice_not_sent_late():
    """원장에 없던 옛 공시(배포 직후 · 공시 읽기 회복 · 밤 런) — 발동 30분이 지났으면 경보를 만들지 않는다."""
    c = ctx()
    c._kind_cache = [_notice(at="2026-10-05T09:59:00+09:00")]          # 31분 전
    assert hits(c, "A5") == []
    c._kind_cache = [_notice(at="2026-10-05T10:01:00+09:00")]          # 29분 전
    assert len(hits(c, "A5")) == 1


def test_market_halt_kind_read_no_index_estimate():
    """공시를 읽었으면 지수 −8.4% 여도 서킷을 추정하지 않는다 — 공시가 정답."""
    c = ctx()
    c._kind_cache = []
    c.strip("kospi")["changePct"] = -8.4
    assert hits(c, "A5") == []


def test_market_halt_index_estimate_when_kind_unreadable():
    c = ctx()
    c._kind_cache = None                                     # 공시를 못 읽음(D3)
    c.strip("kospi")["changePct"] = -8.4
    h = hits(c, "A5")
    assert [(x.target, x.asOf) for x in h] == [("kospi", "2026-10-05.circuit1")]
    f = h[0].fields
    assert (f["stage"], f["next_stage"], f["approx"], f["halt_kind"]) == (1, -15, "(추정)", "서킷브레이커 1단계")
    c.data["marketHalts"]["active"] = [{"id": "sidecar-KOSPI-20261005", "type": "sidecar", "market": "KOSPI",
                                        "source": "news", "corroborated": True,
                                        "triggeredAt": "2026-10-05T10:01:00+09:00"}]
    assert [x.asOf for x in hits(c, "A5")] == ["2026-10-05.circuit1"]   # 뉴스 사이드카는 어떤 길로도 안 만든다


def test_market_halt_circuit_resume_line_and_no_exit():
    c = ctx()
    c._kind_cache = [_notice("circuit", stage=1, at="2026-10-05T10:12:30+09:00")]
    c.data["marketHalts"]["history"] = [dict(_notice(at="2026-10-05T09:30:00+09:00"),
                                             resolvedAt="2026-10-05T09:35:00+09:00")]
    h = {x.asOf: x for x in hits(c, "A5")}
    assert set(h) == {"2026-10-05.circuit1"}                  # 1시간 전 사이드카 = 30분 넘은 공시 — 늦은 경보로 안 낸다
    assert all(x.dir == "enter" for x in h.values())          # 해제 행은 없다
    r = compose.render(EVS["A5"], h["2026-10-05.circuit1"], c)
    assert r["title"].endswith(" 서킷브레이커 1단계 발동") and r["body_push"] == "10:12 · 10:32까지 거래 멈춤", r


# ---- B1 52주 · B2 마디 ----
def test_high52_first_day_only():
    h = by_target(hits(ctx(), "B1"))
    g = h["gold"]
    assert g.dir == "up" and g.fields["prev_extreme"] == 4200.0 and g.fields["prev_date"] == "2026-08-21"
    assert h["kospi"].dir == "down"                          # 코스피 −4% 로 52주 최저 첫날
    c = ctx()
    c.data["history"]["commodities"]["Gold"][-1]["close"] = 4210.0   # 어제도 신고가였다면 오늘은 이어지는 기록
    assert "gold" not in by_target(hits(c, "B1"))


def test_round_level_crossing():
    h = by_target(hits(ctx(), "B2"))
    assert (h["kospi"].dir, h["kospi"].fields["level_value"], h["kospi"].fields["next_level"]) == ("down", 6000, 5000)
    assert (h["gold"].dir, h["gold"].fields["level_value"]) == ("up", 4250)
    assert "usdkrw" not in h and "sp500" not in h            # 1340 → 1342.7 · 7700 → 7730.8: 마디 없음
    c = ctx()
    c.strip("kospi")["change"] = -92.0                       # 직전 5900 → 5808: 6000 을 건너지 않음
    assert "kospi" not in by_target(hits(c, "B2"))


# ---- C1 렌즈 새 돌파 ----
def test_lens_cross_new_two_day_breakout():
    h = hits(ctx(), "C1")
    assert [x.target for x in h] == ["us10y"]
    f = h[0].fields
    assert (h[0].dir, h[0].value, h[0].asOf) == ("up", 5.06, "2026-10-02")
    assert (f["line"], f["chain"], f["chain_id"], f["step"], f["post_date"]) == (5, "재정 눈덩이", "C1", 1, "2026-09-15")
    assert f["next_line"] == 5.5 and f["dist"] == 8.7 and f["node"] == "us10y"
    assert f["level"] == "alarm"                             # 기본 켜짐 대상(default_target)


def test_lens_cross_skips_lines_crossed_over_a_year():
    c = ctx()
    for iid in ("pce_us", "cpi_kr", "jgb10y"):              # 미 PCE · 한국 CPI(월간) · JGB10 — 창 첫 점부터 넘어 있음
        assert ind(c, iid)["state"] == "crossed"
    got = {x.target for x in hits(c, "C1")}
    assert not got & {"pce_us", "cpi_kr", "jp10y", "jgb10y"}
    # 이력이 지속 기간만큼만 남아 있어도(2점 다 선 위) 돌파한 날을 창 안에서 못 봤으면 새 돌파라 하지 않는다
    ind(c, "cpi_kr")["history1y"] = ind(c, "cpi_kr")["history1y"][-2:]
    assert "cpi_kr" not in {x.target for x in hits(c, "C1")}


def test_lens_cross_needs_two_days_and_first_in_year():
    c = ctx()
    ind(c, "us10y")["history1y"][-2]["value"] = 4.95        # 넘은 지 1점째 → 지속 미확인
    assert hits(c, "C1") == []                               # 3점째(us30y) · 1점째(kospi)도 안 걸림
    c = ctx()
    assert "jp30y" not in {x.target for x in hits(c, "C1")}   # 두 달 전에 같은 선(4.0)을 넘었음
    for p in ind(c, "jgb30y")["history1y"]:
        if p["value"] == 4.05:
            p["value"] = 3.9                                 # 그 앞선 돌파를 지우면 새 돌파
    h = by_target(hits(c, "C1"))
    assert "jp30y" in h and h["jp30y"].fields["node"] == "jgb30y" and h["jp30y"].fields["chain"] == "엔 스퀴즈"


# ---- C2 렌즈 주시 ----
def test_lens_near_entry_only():
    h = hits(ctx(), "C2")
    assert [(x.target, x.dir, x.fields["line"], x.fields["dist"]) for x in h] == [("usdjpy", "near", 160, 1.59)]
    c = ctx()
    ind(c, "usdjpy")["history1y"][-2]["value"] = 157.0     # 어제도 ±2% 안 = 진입 아님
    assert hits(c, "C2") == []


# ---- C3 · C4 단계 ----
def test_stage_up_crossing_and_escalation():
    h = hits(ctx(), "C3")
    assert [(x.target, x.fields["stage"], x.fields["next_stage"]) for x in h] == [("vix", 25, 30)]
    assert h[0].fields["peer_chg"] == "+0.4%" and "level" not in h[0].fields
    assert hits(ctx(), "C4") == []                           # MOVE 100 → 99
    c = ctx()
    c.strip("vix").update(value=41.0, change=6.0)            # 35 → 41: 40 단계 = 경보
    h = hits(c, "C3")
    assert h[0].fields["stage"] == 40 and h[0].fields["level"] == "alarm" and h[0].fields["next_stage"] is None
    c = ctx()
    c.strip("vix")["change"] = 0.5                           # 25.5 → 26: 이미 25 위
    assert hits(c, "C3") == []


# ---- C5 공포탐욕 ----
def test_band_enter_fear():
    h = hits(ctx(), "C5")
    assert [(x.dir, x.fields["band_ko"], x.fields["prev"]) for x in h] == [("down", "극단 공포", 28.0)]
    c = ctx()
    c.strip("fear_greed")["change"] = -1.0                  # 23 → 22: 이미 띠 안
    assert hits(c, "C5") == []


# ---- C6 VKOSPI ----
def test_vkospi_relative_entry_and_min_history():
    h = hits(ctx(), "C6")
    assert len(h) == 1 and "실현변동성의 1.9배" in h[0].fields["reason"] and h[0].fields["realized"] == 15.9
    c = ctx()
    hist = c.data["sentiment"]["vkospi"]["history"]
    for k in sorted(hist)[:-50]:                             # 50점 < 90 = 평소 배수를 모른다
        del hist[k]
    assert hits(c, "C6") == []


# ---- C7 금리 · C8 역전 ----
def test_rate_jump_bp():
    h = hits(ctx(), "C7")
    assert [(x.target, x.dir, x.fields["chg_bp"], x.fields["asof_md"]) for x in h] == [("kr10y", "up", 12, "10/2")]
    assert h[0].fields["peer"] == "일본 국채 30Y" and h[0].fields["peer_chg"] == "+3bp"
    c = ctx()
    c.data["yieldCurve"]["kr"]["series"][0]["data"][-1]["value"] = 4.35   # +5bp
    assert hits(c, "C7") == []


def test_sign_flip_inversion():
    h = hits(ctx(), "C8")
    assert [(x.target, x.dir, x.fields["flip_ko"], x.fields["prev"]) for x in h] == [("t10y2y", "down", "역전", 0.05)]
    c = ctx()
    c.strip("t10y2y")["change"] = -0.01                      # −0.02 → −0.03: 이미 역전
    assert hits(c, "C8") == []


# ---- H1 금 김치프리미엄 ----
def test_gold_premium_needs_history(tmp_path):
    h = hits(ctx(), "H1")
    assert [(x.target, x.dir, x.value) for x in h] == [("gold_premium", "up", 1.4)]
    assert h[0].fields == {"krw_g": 199000.0, "usd_oz": 4100.0}   # 프리미엄을 잰 날(10/2)의 국제 금
    c = ctx()
    c.root = str(tmp_path)                                   # events/history/gold_premium.json 없음 = 판정 안 함
    assert hits(c, "H1") == []


# ---- 원장: 같은 관측은 다른 날 런에서도 한 번 ----
def test_same_observation_not_relogged_next_day(tmp_path):
    evs = [EVS[e] for e in ("A1", "B2", "C1", "C8")]
    led = Ledger(day=dt.date(2026, 10, 5), root=str(tmp_path))
    first = extract(ctx(), evs, led)
    keys = {r.key for r in first}
    assert {"C1:us10y:up:2026-10-02", "C8:t10y2y:down:2026-10-02"} <= keys
    # 급변 키 = 사건:대상:방향:거래일 + 세기 단계(:2s · :2.5s · :3s) — 같은 날 커지는 급변이 새 행이 되게
    assert any(k.startswith("A1:kospi:down:2026-10-05:") and k.endswith(":t3") for k in keys), keys
    assert extract(ctx(), evs, led) == []                    # 같은 날 재시도 런
    led.save()
    nxt = Ledger(day=dt.date(2026, 10, 6), root=str(tmp_path))
    later = ctx(NOW + dt.timedelta(days=1))
    assert [r.key for r in extract(later, [EVS["C1"], EVS["C8"]], nxt)] == []   # 값이 그대로인 다음 날
    assert nxt.append(Row(key="C8:t10y2y:down:2026-10-06", event="C8", target="t10y2y", dir="down", level="alert",
                          value=-0.1, unit="%p", asOf="2026-10-06", fresh="prev", title="t", why="", next="",
                          url="#", ts="2026-10-06T10:00:00+09:00")) is True


# ---- 국내 지수 실시간 · 개장 가드(2026-11-20, 기획 4ioDhgSA ②) ----
def test_kr_open_guard_blocks_value_stamped_before_open():
    c = ctx()
    c.strip("kospi").update(asOf="2026-10-05T08:59:00+09:00", state="live")
    assert "kospi" not in by_target(hits(c, "A1"))          # 09:00 전 시각 = 전날 종가


def test_kr_bundle_change_recounted_from_prior_close():
    """번들 등락이 다른 기준값이어도 일봉 직전 종가로 다시 센다 — 값이 어제 종가면 등락 0, 울림 없음."""
    c = ctx()
    prior = [b for b in c.series("kospi") if b["date"] < "2026-10-05"][-1]["close"]
    c.strip("kospi").update(value=prior, changePct=-4.0, state="live", asOf="2026-10-05T09:05:00+09:00")
    assert "kospi" not in by_target(hits(c, "A1"))


def test_apply_live_kr_patches_strip_and_marks_preopen_prev():
    c = ctx()
    q = {"kospi": {"value": 100.0, "change": -5.0, "changePct": -4.76, "asOf": "2026-10-05T10:29:00+09:00", "live": True},
         "kosdaq": {"value": 50.0, "change": 0.0, "changePct": 0.0, "asOf": "2026-10-02T15:30:00+09:00", "live": False}}
    assert c.apply_live_kr(lambda t, now: q[t]) == ["kospi", "kosdaq"]
    assert (c.value("kospi"), c.change_pct("kospi"), c.fresh("kospi")) == (100.0, -4.76, "live")
    assert c.fresh("kosdaq") == "prev"                      # 전날 값 — 급변 판정에서 빠진다
    assert c.apply_live_kr(lambda t, now: None) == []      # 실패하면 그대로
