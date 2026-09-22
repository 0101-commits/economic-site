#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""제목 키워드 매칭 — 부분 문자열 오탐을 걸러 내는 단일 원천.

한국어 기사 제목에서 "유가"는 "유가족"에, "금리"는 "중금리대출"에 걸린다. 그렇게
걸린 기사가 뉴스 카테고리로 배포되고(fetch_data), 이례 알림의 '왜 움직였나' 자리에도
붙는다(send_kakao_digest.focus_news). 두 곳이 각자 `k in title` 을 쓰고 있었기 때문에
한쪽만 고치면 다른 쪽에서 같은 오탐이 계속 나왔다 — 그래서 여기 하나로 모은다.
"""

# 키워드 → 그 키워드를 품기만 한 오탐 어휘. 오탐 어휘는 반드시 키워드를 포함해야 한다
# (그래야 '그 키워드의 모든 출현이 오탐 안인가'를 판정할 수 있다).
FALSE_FRIENDS = {
    "유가": ("유가족", "유가증권"),
    "금리": ("요금리", "대금리", "중금리"),   # 중금리대출 = 금융상품 분류지 금리 기사가 아니다
    "구리": ("구리시", "너구리"),
    "은":   ("은행", "은퇴", "은밀"),
    "일본": ("일본어",),
}


def hit(title, kws):
    """제목이 키워드 중 하나에 실제로 걸리는지 — 오탐 어휘는 제외하고 판정."""
    for k in kws:
        if k not in title:
            continue
        bad = FALSE_FRIENDS.get(k)
        if bad:
            # 그 키워드의 모든 출현이 오탐 어휘 안이면 진짜 매칭이 아니다.
            stripped = title
            for b in bad:
                stripped = stripped.replace(b, "")
            if k not in stripped:
                continue
        return True
    return False


def demo():
    assert not hit("고인 보험금, 유가족이 찾고 받기 쉬워졌다", ("유가", "원유"))
    assert hit("유가족 지원 확대에 국제유가도 반등", ("유가",))
    assert not hit("'우수 온투업자' 자기자금 투자한도 40%로↑…중금리대출 활성화",
                   ("금리", "국채", "국고채"))
    assert hit("국고채 금리 대체로 상승", ("금리", "국채", "국고채"))
    assert all(k in b for k, bads in FALSE_FRIENDS.items() for b in bads), \
        "오탐 어휘는 키워드를 포함해야 한다"
    print("kwmatch.py 자가 점검 통과")


if __name__ == "__main__":
    demo()
