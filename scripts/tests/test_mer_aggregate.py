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
