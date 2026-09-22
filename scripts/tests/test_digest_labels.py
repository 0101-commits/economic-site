#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""다이제스트 블록 라벨 단일 원천 — 라벨이 어긋나면 그 블록은 조용히 사라진다.

2026-09-21 편성 개편에서 블록 "증시"가 "국내증시"/"미국증시"로 갈렸는데 DESC_LABELS
(피드 헤드라인 선별)와 SLOT_BLOCKS(슬롯 편성)가 각각 자기 글자를 들고 있어, 이후
모든 슬롯의 헤드라인이 환율 한 줄로 쪼그라들고 지수가 아래 행으로 내려갔다. 어느
예외도 나지 않았다 — 문자열이 안 맞으면 그냥 안 걸릴 뿐이라서.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import send_kakao_digest as K  # noqa: E402

# 주간 리포트(일요일)는 build_weekly_parts 가 따로 만든다 — SLOT_BLOCKS 밖이다.
WEEKLY = {"주간증시", "주간환율", "주간원자재", "다음주"}


def _produced():
    """build_digest_parts 가 실제로 붙이는 라벨 — 소스에서 직접 읽는다."""
    import re
    src = open(K.__file__, encoding="utf-8").read()
    return set(re.findall(r'blocks\.append\(\("([^"]+)"', src))


def test_slot_blocks_labels_are_produced():
    """편성표가 부르는 라벨은 빌더가 실제로 만드는 라벨이어야 한다."""
    made = _produced()
    for slot, labs in K.SLOT_BLOCKS.items():
        unknown = [l for l in labs if l not in made]
        assert not unknown, f"{slot}: {unknown}"


def test_all_blocks_labels_are_produced():
    assert not [l for l in K.ALL_BLOCKS if l not in _produced()]


def test_desc_labels_are_produced():
    """헤드라인 라벨이 빌더에 없으면 그 헤드라인은 영원히 안 뜬다(무증상)."""
    made = _produced()
    assert not [l for l in K.DESC_LABELS if l not in made and l not in WEEKLY]


def test_desc_labels_reach_the_headline():
    """라벨이 맞아도 헤드라인에 실제로 올라가는지까지 본다."""
    blocks = [("국내증시", "코스피 1▲1%"), ("환율", "달러-원 2▼1%"), ("심리", "공포탐욕 50")]
    desc, items = K.build_feed_parts(blocks)
    assert "코스피" in desc and "달러-원" in desc
    assert "공포탐욕" not in desc
    assert len(desc.split("\n")) <= K.DESC_MAX


def test_headline_overflow_goes_to_rows():
    """후보가 상한을 넘으면 버리지 않고 행으로 내린다(주말 슬롯)."""
    blocks = [("국내증시", "a 1"), ("미국증시", "b 2"), ("환율", "c 3"), ("심리", "d 4")]
    desc, items = K.build_feed_parts(blocks)
    assert len(desc.split("\n")) == K.DESC_MAX
    assert "c 3" in " ".join(i["item_op"] for i in items)
