"""파리티(G1) — 사전 ↔ 판정 함수 ↔ 화면 사전 ↔ 문구 틀. 라벨을 두 곳에 손으로 적으면 여기서 어긋난다."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import compose, export_dict, schema  # noqa: E402
from alerts_v2.events import JUDGES, Hit  # noqa: E402

try:
    from alerts_v2 import judges_market, judges_flow_cal  # noqa: F401,E402
except ImportError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVENTS = schema.load_events()
DICT_PATH = os.path.join(ROOT, "app", "src", "lib", "alerts", "dict.json")
STD_VARS = {"name", "target", "value", "value_raw", "chg", "dir", "dir_ko", "dir_rev_ko", "asof_md", "today_md", "stage_label"}
FMT_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::[^}]*)?\}")


def test_every_judge_in_dictionary_is_registered():
    missing = [e["id"] for e in EVENTS if not e["id"].startswith("U") and e["judge"] not in JUDGES]
    assert missing == [], f"판정 함수 없음: {missing}"


def test_screen_dictionary_matches_events_yml():
    assert os.path.exists(DICT_PATH), "app/src/lib/alerts/dict.json 없음 — python scripts/alerts_v2/export_dict.py"
    on_disk = json.load(open(DICT_PATH, encoding="utf-8"))
    assert on_disk == export_dict.build(), "dict.json 이 events.yml 과 다름 — export_dict.py 를 다시 돌리고 커밋"


def test_templates_only_use_known_or_declared_variables():
    """틀 변수는 표준 변수이거나 사전 params 가 아닌 '판정 함수가 주는 변수'다 — 이름 오타를 잡는다(소문자 · 밑줄만)."""
    bad = []
    for ev in EVENTS:
        for key in ("title", "why", "next", "url"):
            tpls = ev.get(key) if isinstance(ev.get(key), list) else [ev.get(key, "")]
            for t in tpls:
                for v in FMT_RE.findall(t or ""):
                    if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
                        bad.append((ev["id"], key, v))
    assert bad == [], bad


def test_templates_render_without_crash_and_within_limits():
    """빈 Hit 로도 틀이 깨지지 않고, 길이 상한을 지킨다(빠진 변수는 조용히 빠짐)."""
    for ev in EVENTS:
        h = Hit(target=ev["targets"][0], dir="up", value=1234.5, unit="", asOf="2026-10-02", fresh="live", chg=1.2)
        r = compose.render(ev, h, None)
        assert len(r["title"]) <= 30 and len(r["why"]) <= 40 and len(r["next"]) <= 40, ev["id"]
        assert not compose.has_relative_time(r["next"]), ev["id"]
        assert "{" not in r["title"] and "}" not in r["title"], ev["id"]


def test_ids_families_levels_consistent():
    for ev in EVENTS:
        assert ev["id"][0] == ev["family"] or ev["id"].startswith("U"), ev["id"]
        assert ev["level"] in ("alarm", "alert", "notice", "record")
        if ev.get("escalate"):
            assert ev["escalate"].get("to") in ("alarm", "alert")


def test_no_portfolio_money_words_in_templates_or_rows():
    """G5 — 내 자산 금액은 어떤 사전 틀 · 원장 행에도 없다(평가액 · 손익 · 수량 · 평단가)."""
    words = ("평가액", "손익", "수량", "평단가", "보유 금액", "총평가")
    for ev in EVENTS:
        blob = " ".join([ev.get("title", "")] + list(ev.get("why") or []) + list(ev.get("next") or []))
        assert not any(w in blob for w in words), ev["id"]
    latest = os.path.join(ROOT, "events", "latest.json")
    if os.path.exists(latest):
        for r in json.load(open(latest, encoding="utf-8")):
            blob = " ".join(str(r.get(k, "")) for k in ("title", "why", "next"))
            assert not any(w in blob for w in words), r.get("key")
            assert "threshold" not in r, r.get("key")
