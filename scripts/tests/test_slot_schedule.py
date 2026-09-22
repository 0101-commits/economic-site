#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""발송 슬롯 단일 원천 — 워크플로 게이트와 파이썬 편성표가 같은 시각을 봐야 한다.

kakao-daily.yml 이 '지금 발송할 시각인가'를 판정하고, send_kakao_digest.py 가
'그 시각의 편성'을 고른다. 둘이 어긋나면 게이트는 통과하는데 파이썬이 '가장 가까운
슬롯'으로 스냅해 엉뚱한 편성이 나간다 — 예외도 경고도 없다. 워크플로 주석이 이미
"같은 값이어야 한다"고 적어 두었지만, 주석은 어긋남을 막지 못한다.
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import send_kakao_digest as K  # noqa: E402

YML = open(os.path.join(ROOT, ".github", "workflows", "kakao-daily.yml"),
           encoding="utf-8").read()


def _hours():
    """게이트의 HOURS 두 줄 → (평일, 주말) 시각 목록."""
    got = [sorted(int(h) for h in m.split())
           for m in re.findall(r'HOURS="([\d ]+)"', YML)]
    assert len(got) == 2, f"HOURS 줄이 2개가 아니다: {got}"
    return got


def test_weekday_and_weekend_slots_match():
    weekend, weekday = _hours()            # YAML 순서: 주말 → 평일
    assert weekday == sorted(K.SLOT_HOURS_WEEKDAY)
    assert weekend == sorted(K.SLOT_HOURS_WEEKEND)


def test_close_time_matches():
    """마감 리포트 시각 — 15:45 로 앞당기면 수급이 KRX 잠정치다(2026-09-11 회귀)."""
    m = re.search(r'"\$H" = "(\d+)" \] && \[ "\$M" -ge (\d+)', YML)
    assert m, "마감 게이트 조건을 못 찾았다 — 조건식이 바뀌었으면 이 테스트도 따라와야 한다"
    assert (int(m.group(1)), int(m.group(2))) == K.CLOSE_AT


def test_every_slot_has_a_lineup():
    """게이트가 통과시키는 시각마다 편성이 있어야 한다(없으면 ALL_BLOCKS 로 새어 나간다)."""
    weekend, weekday = _hours()
    for h in weekday + weekend:
        assert f"h{h:02d}" in K.SLOT_BLOCKS, f"h{h:02d} 편성 없음"
