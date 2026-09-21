#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""변동성 정규화 공용 모듈 — 알림 임계를 '고정 %'에서 'σ 대비'로 바꾸는 단일 원천.

왜 필요한가(기획안 D2, 2026-09-21 실측):
  고정 ±2% 는 자산마다 전혀 다른 드물기를 뜻한다. 최근 250거래일 기준 코스피 σ=3.38%
  라 ±2% 가 연 103회 발동하는 반면 S&P500 은 σ=0.81% 라 같은 규칙이 연 5회다(27배 격차).
  최근 60거래일만 보면 코스피가 ±2% 를 넘는 날이 50.0% — 격일로 '급변 속보'가 울린다.
  σ 로 정규화하면(|z|≥2) 전 자산이 연 9~16회로 수렴한다.

업계 표준과의 관계(기획안 '벤치마크' 절):
  토스증권 ±5%, Robinhood 5%/10% 처럼 소비자 앱은 고정 %가 표준이다. 다만 그것은
  '이용자가 직접 고른 개별 종목'에 거는 규칙이고, 여기처럼 지수·환율·원자재 13종을
  한 규칙으로 감시하는 경우와 조건이 다르다. Trade-Ideas 의 Standard Deviation
  Breakout, TradingView 의 z-score 이상치 인디케이터가 같은 방식의 선례다.

표기(기획안 '표기법 수정'):
  카드 타일처럼 숫자끼리 비교하는 자리에는 z 를, 사람이 읽는 제목·근거 줄에는
  rank_phrase() 의 자연어 서수("최근 1년 중 4번째로 큰 하락")를 쓴다 — 금융
  저널리즘이 이례성을 z-score 로 쓰지 않는다는 관행을 따른다.
"""
import statistics

# σ 추정에 필요한 최소 표본. 이보다 적으면 None 을 돌려 호출측이 고정 % 로 폴백한다.
MIN_SAMPLES = 60
# 기본 관측창 — 250거래일 ≈ 1년. 짧게 잡으면 급변 국면에서 σ 가 같이 부풀어
# '평소보다 큰 움직임'을 놓치고, 길게 잡으면 국면 전환에 둔해진다.
WINDOW = 250


def daily_returns(closes, window=WINDOW, exclude_last=True):
    """일봉 종가 목록 → 최근 window 개의 일간 수익률(%) 목록.

    exclude_last=True 면 마지막 값을 뺀다 — yahoo_snapshot 의 closes[-1] 은
    '오늘 현재가'라, 오늘 움직임이 오늘을 판정하는 기준선에 섞이면 안 된다.
    """
    xs = [float(c) for c in (closes or []) if c is not None]
    if exclude_last:
        xs = xs[:-1]
    # window 개의 '수익률'을 얻으려면 종가는 window+1 개가 필요하다.
    xs = xs[-(window + 1):]
    return [(xs[i + 1] / xs[i] - 1) * 100 for i in range(len(xs) - 1) if xs[i]]


def sigma(closes, window=WINDOW, exclude_last=True):
    """일간 수익률의 표준편차(%). 표본이 MIN_SAMPLES 미만이면 None.

    평균을 빼지 않는 RMS 가 아니라 표본 표준편차다 — 일간 수익률의 평균은 0 에
    가깝지만, 추세장에서 0 이 아닌 평균을 기준선으로 삼는 편이 '평소 대비'에 맞다.
    """
    r = daily_returns(closes, window, exclude_last)
    if len(r) < MIN_SAMPLES:
        return None
    return statistics.pstdev(r)


def zscore(pct, closes, window=WINDOW, exclude_last=True):
    """오늘 등락률(%) → z(σ 배수). σ 를 못 구하거나 0 이면 None.

    평균 대비가 아니라 0 대비로 나눈다 — 알림이 묻는 것은 '평균에서 얼마나 떨어졌나'가
    아니라 '평소 하루 움직임의 몇 배인가'이기 때문이다.
    """
    sd = sigma(closes, window, exclude_last)
    if not sd:
        return None
    try:
        return float(pct) / sd
    except (TypeError, ValueError):
        return None


def rank_phrase(pct, closes, window=WINDOW, exclude_last=True, label="1년"):
    """같은 방향 움직임 중 몇 번째로 큰지 → "최근 1년 중 4번째로 큰 하락". 없으면 ""..

    z 값은 카드 타일용이고, 사람이 읽는 줄에는 이 서수 표현을 쓴다(기획안 표기법).
    3위 밖이면 순위를 말하지 않고 상위 몇 %인지로 바꾼다 — "37번째로 큰 하락"은
    이례성을 전달하지 못한다.
    """
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return ""
    r = daily_returns(closes, window, exclude_last)
    if len(r) < MIN_SAMPLES or p == 0:
        return ""
    side = "상승" if p > 0 else "하락"
    same = [x for x in r if (x > 0) == (p > 0)]
    if not same:
        return ""
    bigger = sum(1 for x in same if abs(x) > abs(p))
    if bigger < 3:
        return f"최근 {label} 중 {bigger + 1}번째로 큰 {side}"
    pctile = bigger / len(same) * 100
    if pctile > 10:
        return ""                      # 흔한 움직임이면 아무 말도 하지 않는다
    return f"최근 {label} {side} 중 상위 {pctile:.0f}%"


def sigma_line(pct, closes, window=WINDOW, exclude_last=True):
    """카드·본문 공용 보조줄 — "z −2.6σ · 최근 1년 중 4번째로 큰 하락". 재료 없으면 ""."""
    z = zscore(pct, closes, window, exclude_last)
    parts = []
    if z is not None:
        parts.append(f"z {z:+.1f}σ")
    ph = rank_phrase(pct, closes, window, exclude_last)
    if ph:
        parts.append(ph)
    return " · ".join(parts)


def demo():
    """assert 기반 자가 점검 — python scripts/volatility.py 로 실행."""
    import random
    random.seed(7)

    # 표본 부족 → None (고정 % 폴백 경로가 살아 있어야 한다)
    assert sigma([100, 101, 102]) is None
    assert zscore(5.0, [100, 101, 102]) is None
    assert rank_phrase(5.0, [100, 101, 102]) == ""

    # 일간 1% 씩 번갈아 오르내리는 계열 → σ ≈ 1%
    alt = [100.0]
    for i in range(300):
        alt.append(alt[-1] * (1.01 if i % 2 else 0.99))
    sd = sigma(alt)
    assert sd is not None and 0.9 < sd < 1.1, sd

    # exclude_last: 마지막 값(=오늘 현재가)이 기준선에 섞이지 않는다
    spiked = alt + [alt[-1] * 1.30]
    assert abs(sigma(spiked) - sd) < 1e-9

    # z = 오늘 등락 / σ
    z = zscore(3.0, alt)
    assert z is not None and 2.7 < z < 3.4, z
    assert zscore(-3.0, alt) < 0

    # 고정 2% 와 2σ 가 자산마다 얼마나 다른지 — 이 모듈의 존재 이유
    calm = [100.0]
    for _ in range(300):
        calm.append(calm[-1] * (1 + random.gauss(0, 0.005)))
    wild = [100.0]
    for _ in range(300):
        wild.append(wild[-1] * (1 + random.gauss(0, 0.035)))
    assert sigma(calm) < 1.0 < sigma(wild)
    # 같은 2% 움직임이 조용한 자산에선 이례, 사나운 자산에선 평범
    assert zscore(2.0, calm) > 2.5
    assert zscore(2.0, wild) < 1.0

    # 서수 표현 — 관측창 최대 상승보다 큰 값이면 1번째
    top = max(daily_returns(alt))
    assert rank_phrase(top + 5, alt).startswith("최근 1년 중 1번째로 큰 상승")
    # 흔한 움직임엔 아무 말도 하지 않는다
    assert rank_phrase(0.2, wild) == ""

    # 보조줄은 z 만이라도 있으면 만들어진다
    assert sigma_line(3.0, alt).startswith("z +3.")
    assert sigma_line(3.0, [100, 101]) == ""

    print("volatility.py 자가 점검 통과")


if __name__ == "__main__":
    demo()
