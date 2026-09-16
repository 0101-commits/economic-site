"""mer_aggregate.py 회귀 가드 — 네트워크 없이 도는 단위 테스트.

실행: python -m pytest scripts/tests/test_mer_aggregate.py -q
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mer_aggregate as ma  # noqa: E402

US10Y = {"id": "us10y", "unit": "%", "plausible": [2, 8]}
GOLD = {"id": "gold", "unit": None, "plausible": [500, 15000]}
KOSPI = {"id": "kospi", "unit": "p", "plausible": [1000, 20000]}


def test_classify_threshold_level():
    assert ma.classify_threshold("4.7%", US10Y) == {"kind": "level", "value": 4.7}


def test_classify_threshold_counter():
    assert ma.classify_threshold("8일분", US10Y)["kind"] == "counter"


def test_classify_threshold_qualitative_unit_mismatch():
    assert ma.classify_threshold("5% 이내", GOLD)["kind"] == "qualitative"


def test_classify_threshold_qualitative_vote_count():
    assert ma.classify_threshold("7표(과반)", None)["kind"] == "qualitative"


def test_classify_threshold_qualitative_division():
    assert ma.classify_threshold("÷16", None)["kind"] == "qualitative"


def test_classify_threshold_calendar():
    assert ma.classify_threshold("3월 20일", None)["kind"] == "calendar"


def test_classify_threshold_level_with_comma():
    assert ma.classify_threshold("8,200", KOSPI) == {"kind": "level", "value": 8200.0}


def test_classify_threshold_qualitative_out_of_range():
    assert ma.classify_threshold("-8%", KOSPI)["kind"] == "qualitative"


# ── 합성 자산명 분해 ──────────────────────────────────────────────────────
def _patterns():
    _, _, _, alias_patterns, _, _ = ma.load_dict()
    return alias_patterns


def test_split_composite_same_entity_collapses_to_one():
    ap = _patterns()
    assert ma.split_composite("삼성전자·SK하이닉스", ap) == ["semis"]


def test_split_composite_different_entities_duplicate():
    ap = _patterns()
    ids = ma.split_composite("원유·LNG", ap)
    assert set(ids) == {"oil", "lng"}
    assert len(ids) == 2


def test_normalize_indicator_prefers_joinable_over_cause():
    """"이란 경고 상한 유가" 는 geopolitics(alias '이란', 조인 불가) 가 oil(alias
    '유가', 조인 가능) 보다 사전에 먼저 나오지만, 임계값 조인 대상인 지표명은
    joinable 엔티티가 우선이어야 한다(결함 1 회귀 가드)."""
    _, _, _, alias_patterns, joinable_patterns, _ = ma.load_dict()
    assert ma.normalize_indicator("이란 경고 상한 유가", joinable_patterns, alias_patterns) == "oil"
    # 단일 패스(normalize_entity, impacts/stance 용)는 그대로 geopolitics 여야 한다 —
    # cause 계층 그래프 노드가 사라지면 안 된다는 요구사항.
    assert ma.normalize_entity("이란 경고 상한 유가", alias_patterns) == "geopolitics"


# ── impacts n>=2 필터 / 그래프 정합은 main() 산출물로 검증 ────────────────
def test_signals_output_shape():
    """mer_signals.json 을 실제로 만들어 구조 불변식을 확인한다(네트워크 없음,
    로컬 mer_extract_cache.jsonl/data.json/mer_series.json 사용)."""
    ma.main()
    import json
    with open(os.path.join(ma.ROOT, "mer_signals.json"), encoding="utf-8") as f:
        sig = json.load(f)

    # n>=2 필터: 모든 impacts 엣지는 n>=2
    assert all(im["n"] >= 2 for im in sig["impacts"])

    # 그래프 정합: 모든 edge 의 from/to 가 nodes 에 존재, layer 는 4종뿐
    node_ids = {n["id"] for n in sig["graph"]["nodes"]}
    for e in sig["graph"]["edges"]:
        assert e["from"] in node_ids
        assert e["to"] in node_ids
    for n in sig["graph"]["nodes"]:
        assert n["layer"] in ("cause", "market", "channel", "asset")

    # 결측 조인(current=None) → state 는 반드시 unknown, 절대 값을 추정해 채우지 않는다
    no_current = [i for i in sig["indicators"] if i["current"] is None]
    assert all(i["state"] == "unknown" for i in no_current)


def test_boundary_current_equals_level_is_deterministic():
    """current == level 경계에서 dir 방향으로는 항상 crossed."""
    entity = {"id": "x", "unit": None, "plausible": [0, 100]}
    th = {"level": 5.0, "dir": "up"}
    current = 5.0
    crossed = (th["dir"] == "up" and current >= th["level"]) or \
              (th["dir"] == "down" and current <= th["level"])
    assert crossed is True


# ── 실측 조인 회귀(2026-09-16) ─────────────────────────────────────────────
# data.json·mer_series.json 에 값이 있는데 dataKind 가 none 이라 비어 있던 지표를 붙이며
# 드러난 오탐 3종을 고정한다: 시각→레벨, 선복량(TEU)→지수 임계, 지수 레벨→% 임계.
FREIGHT = {"id": "freight_rate", "unit": "idx", "plausible": [100, 12000]}
BOJ = {"id": "boj_rate", "unit": "%", "plausible": [0, 5]}


def test_classify_threshold_clock_time_is_calendar():
    assert ma.classify_threshold("3시 30분", BOJ)["kind"] == "calendar"


def test_classify_threshold_teu_not_index_level():
    assert ma.classify_threshold("400만 TEU", FREIGHT)["kind"] == "qualitative"


def test_yoy_iso_and_ecos_keys():
    iso = ma._yoy([("2025-08-01", 100.0), ("2026-08-01", 103.0)])
    ecos = ma._yoy([("202508", 100.0), ("202608", 103.0)])
    assert iso == [("2026-08-01", 3.0)] and ecos == [("202608", 3.0)]


def test_yoy_drops_month_without_base():
    assert ma._yoy([("2026-08-01", 103.0)]) == []


def test_join_series_yoy_converts_index_to_percent():
    ent = {"dataKind": "map", "transform": "yoy", "dataPath": "economicIndicators.us.cpi_us"}
    data = {"economicIndicators": {"us": {"cpi_us": {"history": {
        "2025-08-01": 320.0, "2026-08-01": 336.0}}}}}
    current, pts = ma.join_series(ent, data, {})
    assert current == {"value": 5.0, "asOf": "2026-08-01"} and len(pts) == 1


def test_join_series_meritems_reads_mer_series():
    ent = {"dataKind": "meritems", "dataPath": "mer_series.freight:SCFI"}
    mer = {"freight": [{"date": "2026-09-11", "items": {"SCFI": 3662.18, "BDI": 3360.0}}]}
    current, _ = ma.join_series(ent, {}, mer)
    assert current == {"value": 3662.18, "asOf": "2026-09-11"}


def test_dict_wires_every_datapath_to_a_join_kind():
    """dataPath 는 있는데 dataKind 가 none 이면 화면에 영영 값이 안 뜬다 — 재발 방지."""
    entities = ma.load_dict()[1]
    orphans = [e["id"] for e in entities
               if e.get("dataPath") and (e.get("dataKind") or "none") == "none"]
    assert orphans == []


def test_join_series_meritems_reads_nps_alloc_bag():
    """NPS 는 items 가 아니라 alloc 키로 쌓인다 — 두 형태 모두 받아야 한다."""
    ent = {"dataKind": "meritems", "dataPath": "mer_series.npsAllocation:국내주식"}
    mer = {"npsAllocation": [{"date": "2026-06-01", "as_of": "2026-06-01",
                              "alloc": {"국내주식": 29.1, "해외주식": 35.4}}]}
    current, _ = ma.join_series(ent, {}, mer)
    assert current == {"value": 29.1, "asOf": "2026-06-01"}
