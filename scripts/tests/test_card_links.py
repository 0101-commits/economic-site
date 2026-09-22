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


# ── 종목 알림 — 카드 히어로와 링크가 같은 종목이어야 한다 ────────────────────
SNAPS = {("KR", "005930"): {"pct": 2.0, "price": 78000, "closes": [1] * 30},
         ("KR", "000660"): {"pct": -5.4, "price": 412000, "closes": [1] * 30},
         ("US", "AAPL"): {"pct": 9.9, "price": 230, "closes": [1] * 30}}
TO_SEND = [({"name": "삼성전자", "symbol": "005930", "market": "KR"}, "l1"),
           ({"name": "SK하이닉스", "symbol": "000660", "market": "KR"}, "l2")]


def test_alert_hero_matches_card_hero_rule():
    """링크 대상 = 카드가 크게 그린 종목(|등락| 최대). 둘이 갈리면 다른 알림을 말한다."""
    import check_alerts as CA
    nm, url = CA._alert_hero(TO_SEND, SNAPS)
    assert nm == "SK하이닉스", nm                       # |−5.4| > |+2.0|
    assert url == "https://finance.naver.com/item/main.naver?code=000660"


def test_alert_hero_is_safe_when_nothing_links():
    """미국 종목·스냅 결측·빈 입력에서 예외 없이 (이름, None)."""
    import check_alerts as CA
    assert CA._alert_hero([({"name": "애플", "symbol": "AAPL", "market": "US"}, "l")],
                          SNAPS) == ("애플", None)
    assert CA._alert_hero([], SNAPS) == ("", None)
    assert CA._alert_hero([({"name": "X", "symbol": "999999", "market": "KR"}, "l")],
                          {}) == ("", None)


# ── 카카오 링크 도메인 제약 ────────────────────────────────────────────────
# 카카오톡 link.web_url 은 앱에 등록된 사이트 도메인이어야 한다. 미등록 도메인을 넣으면
# 카카오가 도메인만 갈아 끼우고 경로는 남겨 GitHub 404 가 된다(2026-09-22 13:16 실측:
# finance.naver.com/sise/sise_index.naver?code=KOSPI
#   → 0101-commits.github.io/sise/sise_index.naver?code=KOSPI).
GO = K.DASHBOARD_URL + "go.html"


def test_kakao_links_never_leave_the_registered_domain():
    """카톡에 실리는 모든 링크는 등록 도메인이어야 한다 — 하나라도 새면 404 가 뜬다."""
    for key, url in N.NAVER_LINKS.items():
        got = K.kakao_link(url)
        assert got.startswith(K.DASHBOARD_URL), f"{key}: {got}"
        assert got == f"{GO}?k={key}"
    assert K.kakao_link("https://finance.naver.com/item/main.naver?code=000660") == f"{GO}?s=000660"


def test_kakao_link_passes_own_domain_through():
    """우리 도메인은 중계할 이유가 없다 — 한 번 더 튕기면 느려지기만 한다."""
    assert K.kakao_link(K.DASHBOARD_URL + "?p=market") == K.DASHBOARD_URL + "?p=market"
    assert K.kakao_link(None) == K.DASHBOARD_URL
    assert K.kakao_link("") == K.DASHBOARD_URL


def test_kakao_link_refuses_unknown_external():
    """화이트리스트 밖 외부 URL 은 대시보드로 — 우리 도메인이 중계기가 되면 안 된다."""
    assert K.kakao_link("https://example.com/evil") == K.DASHBOARD_URL
    assert K.kakao_button("x", "https://example.com/evil")["link"]["web_url"] == K.DASHBOARD_URL


def test_kakao_button_always_converts():
    """버튼도 같은 관문을 지난다(종전엔 버튼만 네이버 생 URL 이었다)."""
    b = K.kakao_button("코스피 시세", N.NAVER_LINKS["KOSPI"])
    assert b["link"]["web_url"] == f"{GO}?k=KOSPI"
    assert b["link"]["web_url"] == b["link"]["mobile_web_url"]


def test_go_page_is_in_sync_with_naver_links():
    """go.html 은 생성물 — NAVER_LINKS 와 어긋나면 중계가 대시보드로 떨어진다."""
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_go_page.py"),
                        "--check"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr


def test_go_page_takes_no_url_parameter():
    """열린 리다이렉트 방지 — go.html 은 키/종목코드만 받고 URL 은 받지 않는다."""
    html = open(os.path.join(ROOT, "go.html"), encoding="utf-8").read()
    assert "q.get('k')" in html and "q.get('s')" in html
    assert "q.get('url')" not in html and "q.get('to')" not in html
    assert "[0-9]{6}" in html          # 종목은 6자리 숫자만


# ── 디스코드 링크는 상호작용에 기대지 않는다 ────────────────────────────────
def test_link_buttons_are_plain_urls():
    """지표 링크는 URL 버튼이어야 한다 — custom_id 면 Interactions 경로에 목숨이 걸린다.

    2026-09-22 실측: 드롭다운(goto_link)과 '지금 시세'(refresh_quotes)가 둘 다
    "애플리케이션이 적시에 응답하지 않았어요" 로 죽었다. 링크를 주는 데 왕복이 필요할
    이유가 없다 — 카드 칸이 16종에서 3~6종으로 줄어 버튼으로 충분하다.
    """
    links = K.card_links(DATA, "h09", False, NOW.replace(hour=9))
    rows = N._components([K._dc_link_buttons(links), K._dc_buttons()])
    link_row = rows[0]["components"]
    assert link_row, "지표 버튼이 비었다"
    for c in link_row:
        assert c["style"] == 5 and c.get("url"), c      # style 5 = URL 버튼
        assert "custom_id" not in c
    assert len(link_row) <= 5                            # 디스코드 행당 5개 상한


def test_link_buttons_follow_card_order():
    """버튼 순서 = 카드 읽는 순서(주인공 먼저)."""
    links = K.card_links(DATA, "h12", False, NOW, focus_key="USDKRW")
    labs = [lab for lab, _u in K._dc_link_buttons(links)]
    assert "달러-원" in labs[0], labs


def test_senders_do_not_use_the_dropdown():
    """발송 경로가 다시 드롭다운으로 돌아가면 같은 장애가 재발한다."""
    src = open(os.path.join(ROOT, "scripts", "send_kakao_digest.py"), encoding="utf-8").read()
    assert "select=_dc_select" not in src, "발송 경로가 드롭다운을 다시 쓰고 있다"
