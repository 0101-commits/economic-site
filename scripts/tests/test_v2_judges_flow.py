"""알림 v2 판정 A7 — D 수급 · E 일정 · F 공시 · G 렌즈 · H2~H4. 함수마다 「걸림 1 · 안 걸림 1」.

고정 데이터 = fixtures/v2/flow_ctx.json(기준 2026-10-01 목 18:30 KST). 원장은 tmp_path/events.
"""
import copy
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import judges_flow_cal as J  # noqa: E402
from alerts_v2 import schema  # noqa: E402
from alerts_v2.context import Context  # noqa: E402
from alerts_v2.events import JUDGES  # noqa: E402
from alerts_v2.ledger import Ledger  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "v2", "flow_ctx.json")
NOW = "2026-10-01T18:30:00+09:00"
EV = schema.by_id(schema.load_events())
with open(FIX, encoding="utf-8") as _f:
    RAW = json.load(_f)


def _ctx(tmp_path, now=NOW, edit=None):
    raw = copy.deepcopy(RAW)
    if edit:
        edit(raw["data"], raw["mer"])
    return Context(now=dt.datetime.fromisoformat(now), data=raw["data"], bundles={},
                   registry={r["id"]: r for r in raw["registry"]}, mer=raw["mer"], root=str(tmp_path))


def _run(ev_id, ctx, **params):
    ev = EV[ev_id] if not params else dict(EV[ev_id], params={**EV[ev_id].get("params", {}), **params})
    return JUDGES[ev["judge"]](ctx, ev)


def _ledger(tmp_path, day, *rows):
    led = Ledger(day=dt.date.fromisoformat(day), root=str(tmp_path / "events"))
    for r in rows:
        led.append({"ts": f"{day}T18:00:00+09:00", **r})
    led.save()


def _add_flow(date, foreign, inst=0, retail=0):
    return lambda d, m: d["investorTrading"]["daily"].append(
        {"date": date, "foreign": foreign, "inst": inst, "retail": retail})


def test_every_a7_judge_is_registered():
    mine = [ev for ev in EV.values() if ev["family"] in "DEFG" or ev["id"] in ("H2", "H3", "H4")]
    assert len(mine) == 21
    assert all(ev["judge"] in JUDGES for ev in mine)


# ---- D 수급 ----
def test_d1_fires_exactly_on_fifth_day(tmp_path):
    hits = _run("D1", _ctx(tmp_path))
    assert len(hits) == 1
    h = hits[0]
    assert (h.target, h.dir, h.value, h.asOf) == ("kospi", "sell", -2040, "2026-10-01")
    assert h.fields["streak"] == 5 and h.fields["supporter"] == "기관"
    assert h.fields["cum5"] == "−1.7조" and h.fields["dir_rev_ko"] == "순매수"
    # 18시 전 = 오늘 행은 잠정치 → 4일째 → 안 걸림
    assert _run("D1", _ctx(tmp_path, "2026-10-01T17:00:00+09:00")) == []
    # 6일째 → 안 걸림(정확히 5일째만)
    assert _run("D1", _ctx(tmp_path, "2026-10-02T18:30:00+09:00", _add_flow("2026-10-02", -1000))) == []


def test_d1_not_again_from_ledger(tmp_path):
    _ledger(tmp_path, "2026-10-01", {"key": "D1:kospi:sell:2026-10-01", "event": "D1"})
    assert _run("D1", _ctx(tmp_path, "2026-10-02T18:30:00+09:00")) == []      # 휴장 다음 날 같은 확정치


def test_d2_streak_end(tmp_path):
    hits = _run("D2", _ctx(tmp_path, "2026-10-02T18:30:00+09:00", _add_flow("2026-10-02", 3000, -1000, -2000)))
    assert len(hits) == 1 and hits[0].dir == "buy"
    assert hits[0].fields["streak"] == 5 and hits[0].fields["prev_dir_ko"] == "순매도"
    assert hits[0].fields["cum"] == "−1.7조" and hits[0].fields["streak_min"] == 5
    assert _run("D2", _ctx(tmp_path)) == []


def test_d3_first_day_only(tmp_path):
    hits = _run("D3", _ctx(tmp_path), sell_le=-15000)
    assert len(hits) == 1 and hits[0].dir == "sell"
    assert hits[0].fields["cum"] == "−1.7조" and hits[0].fields["band_ko"] == "−1.5조 이하"
    # 다음 날도 구간 안이지만 어제 이미 안 → 안 걸림
    assert _run("D3", _ctx(tmp_path, "2026-10-02T18:30:00+09:00", _add_flow("2026-10-02", -1000)),
                sell_le=-15000) == []


def test_d4_big_day(tmp_path):
    assert _run("D4", _ctx(tmp_path)) == []

    def big(d, m):
        d["investorTrading"]["daily"][-1].update(foreign=-25000, inst=20000, retail=5000)
    hits = _run("D4", _ctx(tmp_path, edit=big))
    assert len(hits) == 1 and hits[0].fields["inst"] == "+2조" and hits[0].fields["retail"] == "+5,000억"
    assert hits[0].fields["dir_ko"] == "순매도"


def test_d5_stock_flip(tmp_path):
    hits = _run("D5", _ctx(tmp_path))
    assert [(h.target, h.dir, h.value, h.unit) for h in hits] == [("005930", "sell", -300, "주")]
    assert hits[0].fields["name"] == "삼성전자" and hits[0].fields["prev_days"] == 2
    assert _run("D5", _ctx(tmp_path, "2026-10-01T17:00:00+09:00")) == []       # 오늘 행 잠정 → 전환 없음


# ---- E 일정 ----
def test_e1_eve(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "_CAL_MAP", {"미국 산업생산": ("economicIndicators.us.ip_us", "mom1", False)})
    ctx = _ctx(tmp_path, "2026-10-01T21:00:00+09:00")
    hits = _run("E1", ctx)
    assert len(hits) == 1
    h = hits[0]
    assert (h.target, h.dir, h.asOf, h.value) == ("calendar", "new", "2026-10-02", 2)
    assert h.fields["first"] == "08:00 한국 소비자물가동향"
    assert h.fields["list"] == "08:00 한국 소비자물가동향\n22:15 미국 산업생산"
    assert [i["stars"] for i in h.fields["items"]] == [3, 2] and h.fields["related"] == "산업생산지수"
    assert _run("E1", _ctx(tmp_path, "2026-10-02T21:00:00+09:00")) == []       # 10/3 일정 없음


def test_e2_release_time_guard(tmp_path):
    names = lambda hits: [h.fields["event_name"] for h in hits]   # noqa: E731
    assert names(_run("E2", _ctx(tmp_path, "2026-10-01T09:20:00+09:00"))) == []   # timeApprox → 09:30 부터
    assert names(_run("E2", _ctx(tmp_path, "2026-10-01T09:31:00+09:00"))) == ["한국은행 금통위 (통화정책방향)"]
    assert "미국 PCE 물가지수" not in names(_run("E2", _ctx(tmp_path, "2026-10-01T21:29:00+09:00")))
    hits = [h for h in _run("E2", _ctx(tmp_path, "2026-10-01T21:30:00+09:00"))
            if h.fields["event_name"] == "미국 PCE 물가지수"]
    assert len(hits) == 1
    h = hits[0]
    assert h.asOf == "2026-10-01:미국 PCE 물가지수" and h.fields["verdict_ko"] == "상회"
    assert h.fields["level"] == "alarm" and h.fields["next_event"] == "10/2 08:00 한국 소비자물가동향"


def test_e3_surprise(tmp_path, monkeypatch):
    calm = [0.1, 0.2] * 15                                         # 회차 간 변화 0.1 × 29
    monkeypatch.setattr(J, "_hist_values", lambda data, name: calm if name == "미국 PCE 물가지수" else [])
    hits = _run("E3", _ctx(tmp_path, "2026-10-01T21:31:00+09:00"))
    assert len(hits) == 1
    assert hits[0].fields["gap"] == "+0.2%p" and hits[0].fields["hist_n"] == 29
    assert hits[0].fields["rank_pct"] == "3%"
    wild = [0.0, 1.0] * 15                                         # 변화 1.0 × 29 → 0.2 는 평범
    monkeypatch.setattr(J, "_hist_values", lambda data, name: wild)
    assert _run("E3", _ctx(tmp_path, "2026-10-01T21:31:00+09:00")) == []


def test_e4_policy_rate(tmp_path):
    hits = _run("E4", _ctx(tmp_path))
    assert [(h.target, h.dir, h.value, h.asOf) for h in hits] == [("ff_target", "up", 4.0, "2026-09-30")]
    f = hits[0].fields
    assert (f["chg_bp"], f["verb_ko"], f["prev_n"], f["prev_dir_ko"], f["next_meeting"]) == (25, "인상", 3, "인하", "10/28")
    assert _run("E4", _ctx(tmp_path, "2026-10-05T09:00:00+09:00")) == []      # 변경 5일 뒤 → 지난 일


def test_e5_holiday(tmp_path):
    hits = _run("E5", _ctx(tmp_path))
    assert len(hits) == 1
    f = hits[0].fields
    assert (f["from_md"], f["to_md"], f["next_md"]) == ("10/2", "10/5", "10/6")
    assert f["us_status"] == "10/2 · 10/5 개장" and hits[0].value == 4

    def weekend(d, m):
        d["marketCalendarKr"] = {"today": {"date": "2026-10-02", "open": True},
                                 "nextBusinessDay": {"date": "2026-10-05", "open": True}}
    assert _run("E5", _ctx(tmp_path, "2026-10-02T18:00:00+09:00", weekend)) == []   # 보통 주말


# ---- F 공시 ----
def test_f1_new_disclosure(tmp_path):
    hits = _run("F1", _ctx(tmp_path))
    assert [(h.target, h.asOf) for h in hits] == [("005930", "2026-10-01:20261001800123")]   # 결산 배당(작년)은 빠짐
    assert hits[0].fields["kind_ko"] == "실적"
    assert hits[0].fields["rcp_url"].endswith("rcpNo=20261001800123")
    _ledger(tmp_path, "2026-09-01", {"key": "F1:005930:new:2026-10-01:20261001800123", "event": "F1",
                                     "target": "005930", "asOf": "2026-10-01:20261001800123"})
    assert _run("F1", _ctx(tmp_path)) == []


def test_f2_warning_change(tmp_path):
    assert _run("F2", _ctx(tmp_path)) == []                         # 기준선 없음 = 첫 관측 → 알리지 않음
    with open(tmp_path / "alerts_state.json", "w", encoding="utf-8") as f:
        json.dump({"_tossWarnings": {"005930": {"labels": []}, "000660": {"labels": []}}}, f)
    hits = _run("F2", _ctx(tmp_path))
    assert [(h.target, h.dir, h.value) for h in hits] == [("005930", "enter", "투자주의")]
    assert hits[0].fields["verb_ko"] == "지정" and hits[0].fields["prev_labels"] == "직전 지정 없음"
    _ledger(tmp_path, "2026-09-30", {"key": "F2:005930:enter:2026-09-30:투자주의", "event": "F2",
                                     "target": "005930", "dir": "enter", "value": "투자주의"})
    assert _run("F2", _ctx(tmp_path)) == []                         # 어제 원장에 이미 지정


def test_f3_movers_record(tmp_path):
    hits = _run("F3", _ctx(tmp_path))
    assert [h.target for h in hits] == ["217590", "000002", "000001"]   # ±30% 넘는 한창 제외

    def wild(d, m):
        for lst in d["stockMovers"].values():
            for r in lst:
                r["chg"] = 45.0
    assert _run("F3", _ctx(tmp_path, edit=wild)) == []


# ---- G 렌즈 · 메르 ----
def test_g1_regime(tmp_path):
    hits = _run("G1", _ctx(tmp_path))
    assert [(h.value, h.asOf, h.fields["prev"]) for h in hits] == [("지정학", "2026-10", "정책")]
    assert hits[0].fields["counts"] == "지정학 4 · 정책 1"
    assert _run("G1", _ctx(tmp_path, edit=lambda d, m: m["regime"]["dominant"].__setitem__(-1, "정책"))) == []


def test_g2_stance(tmp_path):
    hits = _run("G2", _ctx(tmp_path))
    assert [(h.target, h.dir, h.value) for h in hits] == [("banks", "down", "부정")]
    assert hits[0].fields["prev_ko"] == "긍정" and hits[0].fields["post_title"] == "은행이 위험하다"
    assert _run("G2", _ctx(tmp_path, "2026-10-05T12:00:00+09:00")) == []


def test_g3_kst_today(tmp_path):
    utc = "2026-09-30T15:30:00+00:00"                               # = 10/1 00:30 KST
    hits = _run("G3", _ctx(tmp_path, utc))
    assert len(hits) == 1 and hits[0].asOf == "2026-10-01"
    assert hits[0].fields["count"] == 1 and hits[0].fields["titles"] == "은행이 위험하다"
    assert hits[0].fields["month_count"] == 1

    def no_today(d, m):
        m["posts"] = [p for p in m["posts"] if p["date"] != "2026-10-01"]
    assert _run("G3", _ctx(tmp_path, utc, no_today)) == []          # UTC 날짜(9/30) 글은 오늘 글이 아니다


def test_g4_mri(tmp_path):
    hits = _run("G4", _ctx(tmp_path))
    assert len(hits) == 1 and hits[0].dir == "up" and hits[0].fields["reason"] == "60 선 위로"
    assert hits[0].fields["components"] == "임계 돌파 40 · 부정 입장 16.5 · 위험 신호 4.5"
    assert _run("G4", _ctx(tmp_path, edit=lambda d, m: m["lens"].update(score=59))) == []


def test_g5_chain_hot(tmp_path):
    first = _run("G5", _ctx(tmp_path))
    assert [(h.target, h.fields["step"], h.fields["level"]) for h in first] == [("C1", "미국채 10년물", "record")]
    assert first[0].fields["trigger"] == "미국채 10년물 5.24% · 5.1 선 돌파"
    assert first[0].fields["next_step"] == "재정적자·국채 발행"
    _ledger(tmp_path, "2026-09-28", {"key": "G5:C9:enter:2026-09-28", "event": "G5", "target": "C9"})
    hits = _run("G5", _ctx(tmp_path))
    assert [h.target for h in hits] == ["C1"] and "level" not in hits[0].fields     # 기준선 뒤 = 보통 등급
    _ledger(tmp_path, "2026-09-30", {"key": "G5:C1:enter:2026-09-30", "event": "G5", "target": "C1"})
    assert _run("G5", _ctx(tmp_path)) == []


# ---- H 실물 · 월간 ----
def test_h2_monthly_new_value(tmp_path):
    hits = _run("H2", _ctx(tmp_path))
    assert sorted(h.target for h in hits) == ["base_rate_kr", "cpi_us"]   # 일간 ff_target 은 아님
    cpi = next(h for h in hits if h.target == "cpi_us")
    assert cpi.asOf == "2026-08-01" and cpi.fields["period"] == "2026-08"
    _ledger(tmp_path, "2026-09-15", {"key": "H2:cpi_us:new:2026-08-01", "event": "H2", "target": "cpi_us"})
    assert [h.target for h in _run("H2", _ctx(tmp_path))] == ["base_rate_kr"]


def test_h3_realestate(tmp_path):
    hits = _run("H3", _ctx(tmp_path))
    assert [(h.target, h.dir, h.chg) for h in hits] == [("sido_11", "up", 1.05), ("sido_26", "down", -0.05)]
    assert hits[0].fields["name"] == "서울" and hits[0].fields["national"] == "+0.39%"
    assert hits[0].fields["level"] == "record"                      # 첫 런 = 기준선
    _ledger(tmp_path, "2026-09-16", {"key": "H3:sido_11:up:202608", "event": "H3", "target": "sido_11"},
            {"key": "H3:sido_26:down:202608", "event": "H3", "target": "sido_26"})
    assert _run("H3", _ctx(tmp_path)) == []


def test_h4_enso(tmp_path):
    hits = _run("H4", _ctx(tmp_path))
    assert [(h.value, h.fields["prev"], h.asOf) for h in hits] == [("엘니뇨", "중립", "JAS 2026")]
    assert _run("H4", _ctx(tmp_path, edit=lambda d, m: d["climate"]["enso"]["oni_history"][0].update(v=0.55))) == []
