#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""알림 링크 단일 원천 — 사진이 말하는 지표와 링크가 어긋나지 않는다.

2026-09-22 사용자 요청: "각 사진에서 해당 영역을 누르면 네이버 증권 해당 페이지로,
기존 대시보드는 '대시보드 보기' 버튼으로." 사진의 칸 자체를 누를 수 있는 채널은 없다
(디스코드는 이미지 클릭이 항상 확대 보기, 카카오 피드는 칸별 링크가 없다). 그래서
**카드와 같은 구성·같은 순서의 링크 목록**을 옆에 세우는 것이 이 기능의 실체다.
이 파일은 그 '같음'을 지킨다.

고친 실측 결함:
  · 카톡 버튼이 편성표의 고정 히어로를 써서, 카드는 달러-원을 그리고 버튼은
    '코스피 시세'였다(09-22 12시, USDKRW z −2.8σ 로 주인공이 바뀐 날).
  · 디스코드 드롭다운이 _ASSETS 16종 전부라 카드에 없는 지표가 절반이었다.
  · 사진·제목 탭이 무조건 대시보드였다.
"""
import datetime
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import discord_card as DC  # noqa: E402
import notify_discord as N  # noqa: E402
import send_kakao_digest as K  # noqa: E402

NOW = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=K.KST)
DATA = {"indices": {}, "fx": {}, "commodities": {}, "yield": {}, "macro": {}}


def test_shown_keys_follows_card_order():
    """링크 순서 = 카드 읽는 순서(히어로 → 타일 좌→우·위→아래)."""
    prof = DC.PROFILES["kr_session"]
    assert DC.shown_keys(prof) == ["KOSPI", "KOSDAQ", "USDKRW", "Nikkei"]
    # 주인공이 바뀌면 그 지표가 맨 앞으로 오고, 중복되지 않는다.
    assert DC.shown_keys(prof, "USDKRW") == ["USDKRW", "KOSPI", "KOSDAQ", "Nikkei"]
    assert DC.shown_keys(prof, "WTI")[0] == "WTI"


def test_links_are_subset_of_card_tiles():
    """카드에 없는 지표가 목록에 섞이면 사진과 목록이 다른 것을 말한다."""
    for slot, hr, we in (("h07", 7, False), ("h09", 9, False), ("h12", 12, False),
                         ("h19", 19, False), ("h22", 22, False), ("h11", 11, True)):
        now = NOW.replace(hour=hr)
        prof = DC.PROFILES[DC.profile_for(slot, we, now)]
        shown = set(DC.shown_keys(prof, DC.HERO.get(DC.profile_for(slot, we, now))))
        got = [k for _lab, k, _u in K.card_links(DATA, slot, we, now)]
        assert set(got) <= shown, f"{slot}: {set(got) - shown}"


def test_hero_follows_the_day_focus():
    """그날 주인공이 바뀌면 첫 링크(=사진 탭·첫 버튼)도 따라간다."""
    links = K.card_links(DATA, "h12", False, NOW, focus_key="USDKRW")
    assert links[0][1] == "USDKRW"
    assert K.hero_link(links) == N.NAVER_LINKS["USDKRW"]
    btn = K._hero_button(links)
    assert btn and btn["link"]["web_url"] == N.NAVER_LINKS["USDKRW"]
    assert "달러-원" in btn["title"]


def test_every_link_is_a_verified_naver_url():
    """네이버 페이지가 없는 지표는 빠진다 — 깨진 링크보다 없는 편이 낫다."""
    for slot, hr in (("h07", 7), ("h09", 9), ("h19", 19), ("h22", 22)):
        for _lab, key, url in K.card_links(DATA, slot, False, NOW.replace(hour=hr)):
            assert url == N.NAVER_LINKS[key]
            assert url.startswith("https://finance.naver.com") or \
                   url.startswith("https://stock.naver.com"), url
    # h19/h22 의 히어로 US10Y 는 네이버에 페이지가 없다 — 빠지고 다음 칸이 대표가 된다.
    assert "US10Y" not in N.NAVER_LINKS
    assert K.card_links(DATA, "h19", False, NOW.replace(hour=19))[0][1] == "USDKRW"


def test_dropdown_mirrors_the_link_list():
    """드롭다운은 같은 목록의 (라벨, 키)일 뿐 — 두 벌로 갈라지면 또 어긋난다."""
    links = K.card_links(DATA, "h09", False, NOW.replace(hour=9))
    assert K._dc_select(DATA, links=links) == [(lab, k) for lab, k, _u in links]


def test_worker_table_matches_naver_links():
    """Worker 의 goto_link 표가 파이썬과 어긋나면 드롭다운이 옛 URL 로 답한다."""
    js = open(os.path.join(ROOT, "cloudflare-worker", "worker.js"), encoding="utf-8").read()
    block = js[js.index("const DISCORD_ASSET_LINKS = {"):]
    block = block[:block.index("};")]
    for key, url in N.NAVER_LINKS.items():
        assert f"{key}: [" in block, f"Worker 에 {key} 없음"
        assert url in block, f"Worker 의 {key} URL 이 다르다"


def test_kakao_feed_link_defaults_to_dashboard():
    """링크를 못 구한 날에도 사진 탭이 죽으면 안 된다(대시보드로 떨어진다)."""
    assert K.hero_link([]) is None
    assert K._hero_button([]) is None
