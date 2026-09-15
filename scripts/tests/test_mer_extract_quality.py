"""mer_extract_cache.jsonl 품질 표본 검수 (P5-3) — 네트워크 없이, 기계로 검증 가능한 항목만.

인용이 원문에 실재하는지는 여기서 검사하지 않는다 — 원문 자체를 저장하지 않기 때문
(공개 저장소, CLAUDE.md). 그 항목은 docs/mer-lens/REVIEW.md 에 사람이 표본으로 확인할
목록으로 남겨뒀다.

실행: python -m pytest scripts/tests/test_mer_extract_quality.py -q
"""
import json
import os
import re

CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "mer_extract_cache.jsonl")

_VALID_DIR = {"+", "-", "±"}
_VALID_HORIZON = {"단기", "중기", "장기"}
_VALID_RISK_FLAGS = {
    "정책", "지정학", "유동성", "금리발작", "신용", "관세", "부동산", "엔캐리 청산", "공급망", "AI버블",
}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _load():
    if not os.path.exists(CACHE):
        return []
    rows = []
    with open(CACHE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def test_cache_file_present_and_nonempty():
    rows = _load()
    assert rows, "mer_extract_cache.jsonl 이 없거나 비어 있음 — 나머지 검사가 전부 무의미해진다"


def test_all_quotes_80_chars_or_less():
    rows = _load()
    bad = []
    for r in rows:
        for coll in ("indicators", "thresholds", "impacts"):
            for it in r.get(coll) or []:
                q = it.get("quote") or ""
                if len(q) > 80:
                    bad.append((r.get("logNo"), coll, len(q)))
    assert not bad, "80자 초과 인용 %d건: %s" % (len(bad), bad[:10])


def test_stance_view_is_integer_in_range():
    rows = _load()
    bad = []
    for r in rows:
        for s in r.get("stance") or []:
            v = s.get("view")
            if not isinstance(v, int) or isinstance(v, bool) or v < -2 or v > 2:
                bad.append((r.get("logNo"), v))
    assert not bad, "stance.view 가 -2~2 정수를 벗어남 %d건: %s" % (len(bad), bad[:10])


def test_impact_direction_is_valid_enum():
    rows = _load()
    bad = []
    for r in rows:
        for im in r.get("impacts") or []:
            d = im.get("direction")
            if d not in _VALID_DIR:
                bad.append((r.get("logNo"), d))
    assert not bad, "impacts.direction 이 +|-|± 가 아님 %d건: %s" % (len(bad), bad[:10])


def test_impact_strength_in_range():
    rows = _load()
    bad = []
    for r in rows:
        for im in r.get("impacts") or []:
            s = im.get("strength")
            if not isinstance(s, int) or isinstance(s, bool) or s < 1 or s > 3:
                bad.append((r.get("logNo"), s))
    assert not bad, "impacts.strength 이 1~3 이 아님 %d건: %s" % (len(bad), bad[:10])


def test_impact_horizon_is_valid_enum():
    rows = _load()
    bad = []
    for r in rows:
        for im in r.get("impacts") or []:
            h = im.get("horizon")
            if h not in _VALID_HORIZON:
                bad.append((r.get("logNo"), h))
    assert not bad, "impacts.horizon 이 단기/중기/장기 가 아님 %d건: %s" % (len(bad), bad[:10])


def test_no_duplicate_lognos():
    rows = _load()
    seen = {}
    dup = []
    for r in rows:
        ln = r.get("logNo")
        if ln in seen:
            dup.append(ln)
        seen[ln] = True
    assert not dup, "logNo 중복 %d건: %s" % (len(dup), dup[:10])


def test_date_format_iso():
    rows = _load()
    bad = [r.get("logNo") for r in rows if not _DATE_RE.match(r.get("date") or "")]
    assert not bad, "date 가 YYYY-MM-DD 형식이 아닌 항목 %d건: %s" % (len(bad), bad[:10])


def test_risk_flags_within_allowed_list():
    rows = _load()
    bad = []
    for r in rows:
        for f in r.get("risk_flags") or []:
            if f not in _VALID_RISK_FLAGS:
                bad.append((r.get("logNo"), f))
    assert not bad, "risk_flags 가 허용 목록 밖 %d건: %s" % (len(bad), bad[:10])


def test_econ_ratio_within_expected_band():
    rows = _load()
    total = len(rows)
    econ_true = sum(1 for r in rows if r.get("econ"))
    ratio = econ_true / total if total else 0
    assert 0.70 <= ratio <= 0.95, (
        "econ=true 비율 %.1f%% (%d/%d) 가 기획안 실측 대역(70~95%%, 참고치 87%%) 밖" % (ratio * 100, econ_true, total)
    )


if __name__ == "__main__":
    # ponytail: 셀프체크 — pytest 없이도 핵심 규칙이 살아있는지 바로 확인
    rows = _load()
    assert rows, "cache empty"
    print("records:", len(rows))
    print("OK (run `python -m pytest %s -q` for the full report)" % __file__)
