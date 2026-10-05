"""사전(events.yml) — 읽기 · 검증 · 파리티의 뿌리."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import FAMILIES, LEVELS, RUNS  # noqa: E402
from alerts_v2 import schema  # noqa: E402


def test_parse_minimal_yaml_subset():
    items = schema.parse(
        "- id: A1\n  name: 지수 급변  # 주석\n  targets: [kospi, sp500]\n"
        "  params: {sigma: 2.5, clamp_pct: [0.5, 5.0], fb: {kospi: 2.0}}\n  enabled: false\n  title: \"{name} {chg:+.1f}%\"\n"
    )
    assert items[0]["id"] == "A1" and items[0]["name"] == "지수 급변"
    assert items[0]["targets"] == ["kospi", "sp500"]
    assert items[0]["params"] == {"sigma": 2.5, "clamp_pct": [0.5, 5.0], "fb": {"kospi": 2.0}}
    assert items[0]["enabled"] is False
    assert items[0]["title"] == "{name} {chg:+.1f}%"


def test_events_yml_loads_and_validates():
    events = schema.load_events()
    ids = [e["id"] for e in events]
    assert len(ids) == len(set(ids))
    assert len([e for e in events if not e["id"].startswith("U")]) == 37
    assert {e["id"] for e in events} >= {"A1", "A5", "B1", "C1", "D1", "E2", "F1", "G1", "H1", "U1", "U2"}
    for e in events:
        assert e["level"] in LEVELS and e["run"] in RUNS
        assert e["family"] in FAMILIES
        assert "{" in e["title"]  # 틀 변수 하나는 있어야 함


def test_validate_reports_missing_keys():
    errs = schema.validate([{"id": "Z1", "name": "x", "level": "loud", "run": "never", "targets": []}])
    assert any("필수 키 없음" in e for e in errs)
    assert any("level" in e for e in errs) and any("run" in e for e in errs)
    assert any("targets" in e for e in errs)


def test_for_run_filters_disabled():
    events = schema.load_events()
    light = schema.for_run(events, "light")
    assert all(e["run"] == "light" for e in light)
    assert "F3" not in {e["id"] for e in schema.for_run(events, "full")}  # enabled: false
