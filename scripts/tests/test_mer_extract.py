"""mer_extract.py 순수 함수 게이트 — 네트워크·LLM 호출 없음.

지키는 것: ① 한줄 코멘트는 마지막 매치 ② 인용은 원문에 실재해야 하고 80자를 넘지 않는다
③ LLM 이 만들어낸 인용은 버린다(날조 차단) ④ 스키마 enum 을 벗어난 값은 정규화된다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mer_extract as X  # noqa: E402


# ── ① 한줄 코멘트 마지막 매치 ────────────────────────────────────────────
def test_one_liner_single():
    body = "본문 어쩌고 저쩌고. 한줄 코멘트. 미국채 금리가 결국 발작을 시작한 것으로 보인다."
    assert X.one_liner_last(body) == "미국채 금리가 결국 발작을 시작한 것으로 보인다."


def test_one_liner_takes_last_not_first():
    """A/S 글은 과거 본문을 통째로 재수록한다 — 앞쪽 코멘트를 잡으면 옛 결론이 올라온다.
    프론트 정규식(app6.js)의 첫-매치 오탐이 여기서 막힌다."""
    body = ("예전 글 재수록. 한줄 코멘트. 이것은 지난달의 옛 결론이고 지금과 다르다. "
            "그 뒤 새로 쓴 본문이 이어진다. "
            "한줄 코멘트. 이번 글의 진짜 결론은 엔캐리 청산이 생각만큼 일어나지 않는다는 것이다.")
    got = X.one_liner_last(body)
    assert got.startswith("이번 글의 진짜 결론")
    assert "옛 결론" not in got


def test_one_liner_stops_at_ps():
    body = "한줄 코멘트. 금리는 재정이 만든다는 것이 1년의 결론이다. PS) 다음 글에서 이어감."
    got = X.one_liner_last(body)
    assert got == "금리는 재정이 만든다는 것이 1년의 결론이다."


def test_one_liner_absent():
    assert X.one_liner_last("한줄 코멘트가 없는 글") is None
    assert X.one_liner_last("") is None


# ── ② 인용 검증·길이 ─────────────────────────────────────────────────────
def test_quote_is_real_ignores_whitespace():
    src = "미국국채  10년물이\n4.9%를 넘어가고 있다"
    assert X.quote_is_real("미국국채 10년물이 4.9%를 넘어가고 있다", src)


def test_quote_is_real_rejects_fabrication():
    src = "미국국채 10년물이 4.9%를 넘어가고 있다"
    assert not X.quote_is_real("미국국채 10년물이 5.5%를 넘어가고 있다", src)
    assert not X.quote_is_real("", src)


def test_trim_quote_caps_at_80():
    q = X.trim_quote("가" * 200)
    assert len(q) <= X.QUOTE_MAX
    assert q.endswith("…")


# ── ③ sanitize — 날조 항목은 버린다 ──────────────────────────────────────
POST = {"logNo": "224407689635", "date": "2026-09-11T08:00:00+09:00",
        "title": "미국 국채금리가 결국 발작을 시작했다."}
BODY = ("미국국채 10년물이 4.9%를 넘어가고 있다. 5%를 찍고, 시장이 놀라서 움직일 수 있다. "
        "한줄 코멘트. 바이백은 속도조절일 뿐이다.")


def test_sanitize_keeps_real_quote_drops_fake():
    raw = {
        "econ": True, "topics": ["미국채금리"],
        "indicators": [{"name": "미국채 10년물", "value": "4.9%", "kind": "level",
                        "direction": "up", "quote": "미국국채 10년물이 4.9%를 넘어가고 있다"}],
        "thresholds": [{"indicator": "미국채 10년물", "level": "5%", "meaning": "시장이 놀라는 선",
                        "quote": "5%를 찍고, 시장이 놀라서"},
                       {"indicator": "미국채 10년물", "level": "6%", "meaning": "지어낸 것",
                        "quote": "6%를 넘으면 연준이 개입한다"}],
        "impacts": [], "stance": [], "chain": None, "risk_flags": ["금리발작"],
    }
    row, dropped = X.sanitize(raw, POST, BODY, "test-model")
    assert dropped == 1                                   # 원문에 없는 인용 1건 폐기
    assert len(row["thresholds"]) == 1
    assert row["thresholds"][0]["level"] == "5%"
    assert len(row["indicators"]) == 1
    assert row["one_liner"] == "바이백은 속도조절일 뿐이다."
    assert row["logNo"] == "224407689635" and row["date"] == "2026-09-11"
    assert row["_meta"]["schema"] == X.SCHEMA_VERSION


def test_sanitize_normalizes_enums_and_bounds():
    raw = {
        "econ": True, "topics": [],
        "indicators": [], "thresholds": [],
        "impacts": [{"from": "미국채 10년물 상승", "to": "기술주", "direction": "위쪽",
                     "strength": 9, "horizon": "영원", "quote": "5%를 찍고, 시장이 놀라서"}],
        "stance": [{"asset": "미국채", "view": -7, "why": "재정적자"},
                   {"asset": "금", "view": "숫자아님", "why": "버려져야 함"}],
        "chain": None, "risk_flags": [],
    }
    row, _ = X.sanitize(raw, POST, BODY, "test-model")
    im = row["impacts"][0]
    assert im["direction"] == "±"          # enum 밖 → ±
    assert im["strength"] == 3             # 1~3 로 clamp
    assert im["horizon"] == "중기"          # enum 밖 → 중기
    assert len(row["stance"]) == 1         # view 가 숫자가 아닌 항목은 폐기
    assert row["stance"][0]["view"] == -2  # -2~+2 로 clamp


def test_sanitize_all_quotes_within_cap():
    long_real = BODY[:120]                 # 원문에 실재하지만 80자를 넘는 인용
    raw = {"econ": True, "topics": [], "indicators": [], "thresholds": [],
           "impacts": [{"from": "a", "to": "b", "direction": "-", "strength": 2,
                        "horizon": "단기", "quote": long_real}],
           "stance": [], "chain": None, "risk_flags": []}
    row, dropped = X.sanitize(raw, POST, BODY, "test-model")
    assert dropped == 0
    assert all(len(i["quote"]) <= X.QUOTE_MAX for i in row["impacts"])


# ── ④ 카테고리 사전 제외(결정 D3) ────────────────────────────────────────
def test_skip_category_excludes_non_economic_only():
    assert X.SKIP_CATEGORY.search("건강/의학/맛집/일상/역사등")
    assert not X.SKIP_CATEGORY.search("경제/주식/국제정세/사회")
    assert not X.SKIP_CATEGORY.search("주절주절 ")
    assert not X.SKIP_CATEGORY.search("피드메이커4기(경제)")


def test_strip_fence_handles_code_block():
    assert X._strip_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert X._strip_fence('설명 문장 {"a": 1} 꼬리') == '{"a": 1}'


# ── ⑤ 체계적 실패만 종료코드로 알린다 ─────────────────────────────────────
def test_systemic_failure_fires_on_dead_key():
    """키가 죽으면 한 편만 시도하고 끊겨도 알려야 한다 — 남은 편을 안 돌았을 뿐 고장이다."""
    assert X.is_systemic_failure(True, 0, 1)
    assert X.is_systemic_failure(True, 3, 7)


def test_systemic_failure_ignores_single_bad_post():
    """원문이 96자뿐인 글 하나로 알림이 가면 사람이 알림을 꺼 버린다 — 그러면 진짜 고장도 묻힌다."""
    assert not X.is_systemic_failure(False, 0, 1)
    assert not X.is_systemic_failure(False, 0, 4)


def test_systemic_failure_fires_when_nothing_survives():
    """5편 이상 시도해 한 편도 못 건졌으면 글의 문제가 아니라 파이프라인의 문제다."""
    assert X.is_systemic_failure(False, 0, 5)
    assert X.is_systemic_failure(False, 0, 40)


def test_systemic_failure_quiet_on_partial_success():
    """일부라도 성공했으면 파이프라인은 살아 있다 — 울리지 않는다."""
    assert not X.is_systemic_failure(False, 1, 39)
    assert not X.is_systemic_failure(False, 348, 1)
