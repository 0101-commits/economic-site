#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""뉴스 카테고리 키워드 매칭 — 부분 문자열 오탐 방어.

이 파일이 지키는 것: 키워드가 다른 단어 안에 들어갔을 뿐인 기사를 그 카테고리로
분류하지 않는다. 2026-09-21 실측으로 "고인 보험금, 유가족이 찾고 받기 쉬워졌다"가
'유가'에 걸려 원유 뉴스로 배포됐고, 그것이 이례 알림의 '왜 움직였나' 자리에 붙었다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import fetch_data as F  # noqa: E402

OIL = ("유가", "원유", "WTI", "브렌트")
BOND = ("국채", "채권", "금리")
METAL = ("구리", "니켈", "알루미늄", "아연", "LME", "비철", "광물", "제련")


def test_false_friend_alone_is_rejected():
    """오탐 어휘만 있으면 매칭이 아니다."""
    assert not F._kw_hit("고인 보험금, 유가족이 찾고 받기 쉬워졌다", OIL)
    assert not F._kw_hit("유가증권시장 상장 심사 통과", OIL)
    assert not F._kw_hit("구리시 신규 산업단지 조성", METAL)


def test_real_hit_still_matches():
    """진짜 기사는 그대로 통과한다 — 가드가 과잉 차단하면 카테고리가 빈다."""
    assert F._kw_hit("국제유가 급등…WTI 배럴당 95달러", OIL)
    assert F._kw_hit("구리 가격 사상 최고치", METAL)
    assert F._kw_hit("국고채 금리 대체로 상승", BOND)


def test_mixed_title_counts_as_hit():
    """오탐 어휘와 진짜 키워드가 같이 있으면 진짜로 본다."""
    assert F._kw_hit("유가족 지원 확대에 국제유가도 반등", OIL)


def test_keyword_without_false_friends_is_plain_substring():
    """오탐 목록이 없는 키워드는 종전대로 단순 부분 문자열 매칭이다."""
    assert F._kw_hit("LME 재고 급감", METAL)
    assert not F._kw_hit("환율 급등", METAL)


def test_every_category_keyword_set_is_nonempty():
    """카테고리마다 키워드가 있어야 폴백이 동작한다(빈 튜플이면 전부 매칭 실패)."""
    for cat, kws in F._KEYLESS_CATEGORY_KEYWORDS.items():
        assert kws, cat


def test_queries_and_keywords_cover_same_categories():
    """쿼리 표와 키워드 표가 어긋나면 그 카테고리는 폴백 없이 조용히 빈다."""
    assert set(F.NEWS_CATEGORY_QUERIES) == set(F._KEYLESS_CATEGORY_KEYWORDS)


def test_matcher_is_single_source():
    """fetch_data 와 send_kakao_digest 가 같은 판정기를 써야 한다.

    두 곳이 각자 `k in title` 이던 시절, fetch_data 만 고쳐 놓고 이례 알림의
    '왜 움직였나'에는 "'우수 온투업자'…중금리대출 활성화"가 US10Y 근거로 붙었다.
    """
    import kwmatch
    assert F._kw_hit is not None and F._KEYWORD_FALSE_FRIENDS is kwmatch.FALSE_FRIENDS
    assert not kwmatch.hit("'우수 온투업자' 자기자금 투자한도 40%로↑…중금리대출 활성화",
                           ["금리", "국채", "국고채"])
    assert kwmatch.hit("국고채 금리 대체로 상승", ["금리", "국채", "국고채"])


def test_focus_news_uses_the_matcher():
    """focus_news 의 키워드 게이트가 오탐 어휘를 통과시키지 않는다."""
    import send_kakao_digest as K
    data = {"news": {"채권": [{"title": "'우수 온투업자' 자기자금 투자한도 40%로↑…중금리대출 활성화",
                              "url": "u", "isoDate": "2099-01-01"}]}}
    assert K.focus_news(data, "US10Y") is None
    data["news"]["채권"].append({"title": "미 국채 금리 급등", "url": "u2",
                                "isoDate": "2099-01-01"})
    assert K.focus_news(data, "US10Y")[0] == "미 국채 금리 급등"
