"""discord_card 팔레트·슬롯 편성 가드 (2026-08-25 흰 바탕 전환 + 슬롯 편성).

카드는 실패해도 조용히 None 을 돌려주고 옛 형식으로 폴백한다 — 즉 '깨진 카드'가
알림 실패로 보이지 않는다. 흰 배경 전환이 절반만 된 채로 며칠 나간 이유이기도 하다.
그래서 이 파일이 세 가지를 강제한다:

  1) 팔레트 대비 — 흰 바탕에서 본문 4.5:1 / 도형 3:1. 상수를 잘못 만지면 여기서 깨진다.
  2) 편성표 무결성 — PROFILES 가 참조하는 모든 키가 _CATALOG 에 있을 것(오타 = 빈 타일).
  3) 렌더 스모크 — 실제 data.json 으로 6프로필 × 2캔버스(가로·정사각) 전부 PNG 가 나올 것.
  4) 채널 배선 — 히어로 시계열 소스 우선순위와 피드 버튼(카톡 정사각 카드용).

실행: python scripts/tests/test_discord_card.py  (또는 python -m pytest 이 파일)
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import discord_card as dc  # noqa: E402  (matplotlib 는 지연 import)
import send_kakao_digest as skd  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── WCAG 대비 ─────────────────────────────────────────────────────────────
def _lum(hexcolor):
    h = hexcolor.lstrip("#")
    ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    ch = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def contrast(a, b):
    l1, l2 = sorted((_lum(a), _lum(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def test_body_text_contrast():
    """카드 바탕 위 '글자'로 쓰이는 색은 전부 4.5:1 이상."""
    for name in ("INK", "MUT", "FAINT", "UP_TXT", "DN_TXT"):
        c = contrast(getattr(dc, name), dc.BG)
        assert c >= 4.5, f"{name}({getattr(dc, name)}) = {c:.2f}:1 — 본문 기준 4.5:1 미달"


def test_graphic_contrast():
    """선·채움 등 '도형'은 3:1 이상. UP/DN 원색은 값 유지가 지시라 여기까지만 요구한다."""
    for name in ("LINE", "UP", "DN"):
        c = contrast(getattr(dc, name), dc.BG)
        assert c >= 3.0, f"{name}({getattr(dc, name)}) = {c:.2f}:1 — 도형 기준 3:1 미달"


def test_flat_tile_contrast():
    """보합 타일(TILE) 위 라벨(MUT)·수치(INK)도 4.5:1."""
    for name in ("MUT", "INK"):
        c = contrast(getattr(dc, name), dc.TILE)
        assert c >= 4.5, f"{name} on TILE = {c:.2f}:1"


def test_saturated_tile_keeps_black_readable():
    """등락 타일은 강도가 셀수록 진해진다 — 최대 채도에서도 검은 글자가 읽혀야 한다.
    UP/DN 을 어둡게 바꾸면 여기서 걸린다(타일 잉크는 INK 고정이므로)."""
    for sat in (0.8, 1.0, 3.0, 15.0):
        for chg in (sat * 0.5, sat, sat * 3):
            for sign in (1, -1):
                bg, ink, flat = dc._tile_color(sign * chg, sat)
                assert not flat
                assert ink == dc.INK
                c = contrast(ink, bg)
                assert c >= 4.5, f"chg={sign * chg} sat={sat} tile={bg} → {c:.2f}:1"


def test_tile_color_returns_flat_flag():
    """보합 판정은 '색 비교'가 아니라 세 번째 반환값으로. (구: bgc != TILE)"""
    bg, ink, flat = dc._tile_color(None)
    assert (bg, ink, flat) == (dc.TILE, dc.MUT, True)
    assert dc._tile_color(0.0)[2] is True
    assert dc._tile_color(1.0)[2] is False


# ── 편성표 ────────────────────────────────────────────────────────────────
def test_profile_keys_exist_in_catalog():
    """편성표 오타 = 빈 타일. 모든 참조 키가 카탈로그에 있어야 한다."""
    for pname, prof in dc.PROFILES.items():
        keys = [k for row in prof["rows"] for k in row] + list(prof.get("spark") or [])
        for k in keys:
            assert k in dc._CATALOG, f"{pname}: 알 수 없는 타일 키 {k!r}"


def test_hero_covers_every_profile():
    """정사각 카드 하단 패널의 '주인공'. 빠지면 첫 타일로 대체되지만 의도가 아니다."""
    for p in dc.PROFILES:
        assert p in dc.HERO, f"{p}: HERO 미지정"
        assert dc.HERO[p] in dc._CATALOG, f"{p}: HERO 키 {dc.HERO[p]!r} 가 카탈로그에 없다"


def test_profile_shape():
    for pname, prof in dc.PROFILES.items():
        assert prof.get("title"), pname
        assert prof["rows"] and all(prof["rows"]), pname
        assert 1 <= len(prof.get("spark") or []) <= 5, pname


def test_profile_for_slots():
    assert dc.profile_for("h07") == "pre_kr"
    assert dc.profile_for("h08") == "pre_kr"
    assert dc.profile_for("h09") == "kr_session"
    assert dc.profile_for("h14") == "kr_session"
    assert dc.profile_for("h15") == "kr_session"
    assert dc.profile_for("h16") == "kr_close_eu"
    assert dc.profile_for("h18") == "kr_close_eu"
    assert dc.profile_for("h19") == "us_pre"
    assert dc.profile_for("h21") == "us_pre"
    assert dc.profile_for("h11", weekend=True) == "weekend"
    assert dc.profile_for("h17", weekend=True) == "weekend"
    # 모르는 슬롯·빈 슬롯은 폴백(빈 카드 금지)
    assert dc.profile_for("manual") == dc.DEFAULT_PROFILE
    assert dc.profile_for(None) == dc.DEFAULT_PROFILE


def test_h22_follows_us_dst():
    """h22 는 서머타임에만 미국 개장이다(3~11월 22:30 KST / 그 외 23:30 KST).
    직접 날짜 계산 금지 — tz 데이터에 물어본다."""
    import datetime
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("America/New_York")
    except Exception:                                     # tz 데이터 없는 환경은 건너뛴다
        print("skip: tz 데이터 없음 — 서머타임 판정 생략")
        return
    kst = datetime.timezone(datetime.timedelta(hours=9))
    summer = datetime.datetime(2026, 7, 15, 22, 40, tzinfo=kst)   # NY 09:40 EDT — 개장
    winter = datetime.datetime(2026, 12, 15, 22, 40, tzinfo=kst)  # NY 08:40 EST — 개장 전
    assert dc.profile_for("h22", now=summer) == "us_open"
    assert dc.profile_for("h22", now=winter) == "us_pre"


# ── 가상 카테고리 어댑터 ──────────────────────────────────────────────────
def test_yield_node_is_bp_not_pct():
    d = {"yieldCurve": {"us": {"series": [
        {"tenor": "10Y", "data": [{"date": "d1", "value": 4.69}, {"date": "d2", "value": 4.74}]}]}}}
    v, chg = dc._node(d, "yield", "US10Y")
    assert v == 4.74
    assert chg == 5.0, f"5bp 여야 함(0.05%p) — got {chg}"
    assert dc._chgtxt_tile("yield", chg) == "▲5bp"
    assert dc._fmt_tile("yield", v) == "4.74%"


def test_dxy_history_dict_is_sorted():
    d = {"economicIndicators": {"us": {"dxy_idx": {
        "value": 99.06, "change": 0.22,
        "history": {"2026-08-03": 97.0, "2026-08-01": 96.0, "2026-08-02": 98.0}}}}}
    assert dc._node(d, "macro", "DXY") == (99.06, 0.22)
    assert dc._hist(d, "macro", "DXY") == [96.0, 98.0, 97.0]


def test_live_overlay_wins():
    """apply_live_quotes 가 심은 _liveTiles 가 스냅샷보다 우선(FRED 2영업일 지연 회피)."""
    d = {"indices": {"KOSPI": {"price": 1.0, "change": 1.0}},
         "_liveTiles": {"KOSPI": {"value": 2.0, "change": -3.0}}}
    assert dc._node(d, "indices", "KOSPI") == (2.0, -3.0)


def test_eurusd_gets_four_decimals():
    assert dc._fmt_tile("fx", 1.1666) == "1.1666"
    assert dc._fmt_tile("fx", 1383.6) == "1,383.6"


def test_missing_data_is_dash_not_crash():
    assert dc._node({}, "yield", "US10Y") == (None, None)
    assert dc._node({}, "macro", "DXY") == (None, None)
    assert dc._fmt_tile("yield", None) == "—"
    assert dc._chgtxt_tile("yield", None) == ""


# ── 렌더 스모크 ───────────────────────────────────────────────────────────
def test_all_profiles_render_both_shapes():
    """실제 data.json 으로 6프로필 × 2캔버스 전부 PNG 가 나와야 한다.
    결측 키·빈 시계열로 죽는 편성을 잡는다. 히어로 재료는 네트워크 없이 일봉으로 대신한다."""
    import datetime
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        print("skip: matplotlib 미설치 — 렌더 스모크 생략")
        return
    with open(os.path.join(_ROOT, "data.json"), encoding="utf-8") as f:
        data = json.load(f)
    now = datetime.datetime.now()
    for pname in dc.PROFILES:
        hk = dc.HERO[pname]
        hc = dc._CATALOG[hk][2]
        vs = dc._hist(data, hc, hk)
        base = datetime.datetime(now.year, now.month, now.day)
        hero = ([base + datetime.timedelta(days=i) for i in range(len(vs))],
                vs, (vs[0] if vs else None), "일봉 30D")
        for shape, h in (("wide", None), ("square", hero)):
            png = dc.board(data, now, profile=pname, shape=shape, hero=h)
            assert png, f"{pname}/{shape}: 렌더 실패(None) — 카드가 조용히 폴백된다"
            assert os.path.getsize(png) > 10_000, f"{pname}/{shape}: PNG 가 너무 작다({png})"


def test_square_survives_missing_hero():
    """히어로 재료가 없어도(시세 조회 전부 실패) 카드 자체는 살아야 한다 — 패널만 빈다."""
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return
    import datetime
    with open(os.path.join(_ROOT, "data.json"), encoding="utf-8") as f:
        data = json.load(f)
    png = dc.board(data, datetime.datetime.now(), profile="kr_session",
                   shape="square", hero=None)
    assert png and os.path.getsize(png) > 10_000


# ── 채널 배선 ─────────────────────────────────────────────────────────────
def test_session_chain_prefers_full_day_source():
    """다이제스트 히어로는 '당일 전 구간'이 목적이다 — 토스 1분봉(count 상한 200 =
    최근 3.3h)이 1순위로 잡히면 오전장이 사라진다. Yahoo 5분봉이 먼저여야 한다."""
    orig = (skd._yahoo_intraday, skd._toss_index_intraday, skd._daily7)
    calls = []
    try:
        def _y(_sym):
            calls.append("yahoo")
            return [1, 2, 3], [10.0, 11.0, 12.0], 9.0

        def _t(_sym):
            calls.append("toss")
            return [1, 2, 3], [1.0, 2.0, 3.0], 0.5

        skd._yahoo_intraday, skd._toss_index_intraday = _y, _t
        skd._daily7 = lambda _s: ([], [], None)
        _xs, ys, _prev, src = skd._session_chain("^KS11")
        assert calls == ["yahoo"], f"토스가 먼저 불렸다: {calls}"
        assert ys == [10.0, 11.0, 12.0] and src == ""
        calls.clear()
        skd._yahoo_intraday = lambda _s: ([], [], None)      # Yahoo 실패 시에만 토스
        _xs, ys, _prev, src = skd._session_chain("^KS11")
        assert calls == ["toss"] and src == "1분봉 최근", (calls, src)
    finally:
        skd._yahoo_intraday, skd._toss_index_intraday, skd._daily7 = orig


def test_hero_symbol_reuses_existing_tables():
    assert skd._hero_symbol("KOSPI") == "^KS11"
    assert skd._hero_symbol("US10Y") == "^TNX"
    assert skd._hero_symbol("없는키") == ""


def test_hero_button_only_for_verified_links():
    """피드 2번째 버튼 — 네이버 2중 검사를 통과한 링크만. 없으면 버튼을 붙이지 않는다."""
    import datetime
    kst = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime(2026, 8, 25, 15, 0, tzinfo=kst)
    b = skd._hero_button("h15", False, now)                  # kr_session → KOSPI
    assert b and "코스피" in b["title"]
    assert b["link"]["web_url"].startswith("https://finance.naver.com")
    assert skd._hero_button("h20", False, now) is None       # us_pre → US10Y, 네이버 미제공


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_"):
            _f()
            print(f"ok {_n}")
    print("OK: discord_card 팔레트 · 편성표 · 렌더")
