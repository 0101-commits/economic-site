"""A14 이력 분리 — data.json 기록자 형식 패리티.

data.json 을 쓰는 곳이 하나라도 indent 로 쓰면 압축 직렬화 효과(4.86MB → 1.27MB)가 통째로 사라진다.
정상 경로의 마지막 기록자는 validate_data, 커밋 재시도 경로는 merge_newer 다.
fetch_data.py 두 곳(run_light_build · __main__)과 split_history 동작·소비처 동등성 검사는 아래 2부 절.
"""
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")
COMPACT = 'separators=(",", ":")'

# (파일, data.json 을 쓰는 dump 호출 한 줄을 찾는 정규식)
WRITERS = [
    ("merge_newer.py", r"json\.dumps\(merged,[^\n]*"),
    ("validate_data.py", r"json\.dump\(d, f,[^\n]*"),
    ("ai_briefing.py", r"json\.dump\(d, f,[^\n]*"),
    ("climate_impact.py", r"json\.dump\(d, f,[^\n]*"),
]


def test_data_json_writers_use_compact_separators():
    for name, pat in WRITERS:
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            hits = re.findall(pat, f.read())
        assert hits, f"{name}: data.json 기록 호출을 못 찾음 — 패턴을 갱신할 것"
        for line in hits:
            assert COMPACT in line and "indent" not in line, f"{name}: {line.strip()}"


# ── 2부: fetch_data.split_history (오프라인 — 네트워크를 부르지 않는다) ─────────
import datetime  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import types  # noqa: E402

import pytest  # noqa: E402

sys.path.insert(0, ROOT)
import fetch_data as fd  # noqa: E402


def test_fetch_data_writers_use_compact_separators():
    with open(os.path.join(ROOT, "fetch_data.py"), encoding="utf-8") as f:
        hits = re.findall(r"_payload = json\.dumps\(d,[^\n]*", f.read())
    assert len(hits) == 2, hits      # run_light_build · __main__
    for line in hits:
        assert COMPACT in line and "indent" not in line, line.strip()


def _series(n, start="2021-01-01", step=1):
    d0 = datetime.date.fromisoformat(start)
    return [{"date": (d0 + datetime.timedelta(days=i * step)).isoformat(), "close": 100.0 + i}
            for i in range(n)]


def _run(**hist):
    return {"lastUpdated": "2026-09-30T10:00:00+09:00", "history": hist}


def _read_hist():
    with open("history.json", encoding="utf-8") as f:
        return json.load(f)


def test_split_keeps_tail_in_data_and_full_in_history_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    kospi, dubai = _series(1226), _series(69, step=30)
    d = _run(indices={"KOSPI": kospi}, commodities={"Dubai": dubai})
    fd.split_history(d, {}, False)                  # prev 에 버전 없음 → 부트스트랩으로 쓴다
    h = _read_hist()
    assert h["lastUpdated"] == d["historyVersion"] == d["lastUpdated"]
    assert h["history"]["indices"]["KOSPI"] == kospi
    tail = d["history"]["indices"]["KOSPI"]
    assert len(tail) == fd.HISTORY_TAIL == 400 and tail == kospi[-400:] and tail[-1] == kospi[-1]
    # 월간 Dubai(69점)는 꼬리보다 짧아 양쪽에 통째로 남는다
    assert d["history"]["commodities"]["Dubai"] == dubai == h["history"]["commodities"]["Dubai"]
    with open("history.json", encoding="utf-8") as f:
        raw = f.read()
    assert '": ' not in raw and "\n" not in raw      # 압축 직렬화


def test_missing_or_shrunk_series_keeps_old_history_json_not_tail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    old = {"crypto": {"BTC": _series(1826)}, "commodities": {"Gold": _series(1250)},
           "indices": {"KOSPI": _series(1226, start="2020-06-01")}}
    with open("history.json", "w", encoding="utf-8") as f:
        json.dump({"lastUpdated": "v-old", "history": old}, f)
    short_gold, kospi = _series(300, start="2026-01-01"), _series(1200)
    d = _run(indices={"KOSPI": kospi}, commodities={"Gold": short_gold})   # BTC 는 이번 런에 없음
    fd.split_history(d, {"historyVersion": "v-old"}, True)
    h = _read_hist()["history"]
    assert h["crypto"]["BTC"] == old["crypto"]["BTC"]                    # 빠진 계열 = 직전 파일
    assert h["commodities"]["Gold"] == old["commodities"]["Gold"]        # 0.9 미만으로 짧아짐 = 직전 파일
    assert h["indices"]["KOSPI"] == kospi                                # 0.9 이상 = 이번 런
    assert "crypto" not in d["history"]                                  # 꼬리엔 되살리지 않는다(날조 금지)
    assert d["history"]["commodities"]["Gold"] == short_gold
    assert d["historyVersion"] == d["lastUpdated"]


@pytest.mark.parametrize("daily,hist", [
    (False, {"indices": {"KOSPI": _series(1226)}}),   # 비일일 풀 런 + 파일 있음
    (True, {}),                                        # 이번 런 이력 전멸 → 파일 보존·버전 이월
])
def test_history_json_untouched_and_version_carried(tmp_path, monkeypatch, daily, hist):
    monkeypatch.chdir(tmp_path)
    with open("history.json", "w", encoding="utf-8") as f:
        f.write("SENTINEL")                             # 다시 쓰거나 읽으려 들면 드러난다
    d = _run(**hist)
    fd.split_history(d, {"historyVersion": "v-old"}, daily)
    with open("history.json", encoding="utf-8") as f:
        assert f.read() == "SENTINEL"
    assert d["historyVersion"] == "v-old"
    assert all(len(v) <= fd.HISTORY_TAIL for m in d["history"].values() for v in m.values())


def test_missing_history_json_is_rewritten_even_on_non_daily_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = _run(indices={"KOSPI": _series(1226)})
    fd.split_history(d, {"historyVersion": "v-old"}, False)
    assert _read_hist()["lastUpdated"] == d["historyVersion"] == d["lastUpdated"]


def test_light_run_keeps_prev_history_version(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prev = {"lastUpdated": "2026-09-30T09:00:00+09:00", "historyVersion": "2026-09-30T07:05:00+09:00",
            "history": {"indices": {"KOSPI": _series(400)}}, "indices": {"KOSPI": {"price": 100.0}}}
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(prev, f)
    monkeypatch.setattr(fd, "fetch_yf", lambda sym: {"price": 101.0, "change": 1.0})
    monkeypatch.setitem(sys.modules, "market_halts",
                        types.SimpleNamespace(detect_market_halts=lambda d, p: {"active": [], "history": []}))
    fd.run_light_build()
    with open("data.json", encoding="utf-8") as f:
        out = json.load(f)
    assert out["lastUpdated"] != prev["lastUpdated"]        # 경량 런이 실제로 기록했다
    assert out["historyVersion"] == prev["historyVersion"]
    assert out["history"] == prev["history"]
    assert not os.path.exists("history.json")


def test_consumers_identical_after_split_on_real_data(tmp_path, monkeypatch):
    """꼬리 400점이면 파이썬 소비처 출력이 분리 전후 같아야 한다(설계 §1.3)."""
    import copy

    import discord_card as dc
    import mer_aggregate as ma
    import send_kakao_digest as kd

    repo = os.path.join(ROOT, "..")
    with open(os.path.join(repo, "data.json"), encoding="utf-8") as f:
        full = json.load(f)
    hp = os.path.join(repo, "history.json")
    if os.path.exists(hp):                              # 분리 뒤: 긴 이력은 history.json 에 있다
        with open(hp, encoding="utf-8") as f:
            full["history"] = json.load(f)["history"]
    monkeypatch.chdir(tmp_path)
    tail = copy.deepcopy(full)
    fd.split_history(tail, {}, False)
    assert tail["history"] != full["history"], "5년 이력이 아니라 동등성 검사가 무의미"

    keys = [k for k, (_ko, _en, cat) in dc._CATALOG.items() if cat in ("indices", "fx", "commodities", "crypto")]
    assert [kd.range_pos(full, k) for k in keys] == [kd.range_pos(tail, k) for k in keys]
    assert dc.anomalies(full, keys, min_z=0) == dc.anomalies(tail, keys, min_z=0)
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    for cat, m in full["history"].items():
        for k, v in m.items():
            assert kd._wk_pct(v, now) == kd._wk_pct(tail["history"][cat][k], now), (cat, k)
    _v, entities, *_ = ma.load_dict()
    for e in entities:
        if e.get("dataKind") != "close":
            continue
        c1, p1 = ma.join_series(e, full, {})
        c2, p2 = ma.join_series(e, tail, {})
        assert c1 == c2, e["id"]
        if c1:
            assert ma.history_1y(p1, c1["asOf"]) == ma.history_1y(p2, c2["asOf"]), e["id"]
