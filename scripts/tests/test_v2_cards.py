"""카톡 카드 — PNG 1080² · 최장 데이터 · 차트 없음 · 글자 하한 · 글자 겹침 · 실패는 예외 · 미리보기 저장."""
import datetime as dt
import os
import struct
import sys
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
pytest.importorskip("matplotlib")

import discord_card as dc  # noqa: E402
from alerts_v2 import cards  # noqa: E402
from test_card_layout import problems  # noqa: E402  (렌더러가 계산한 글자 상자로 겹침 · 이탈 · 타일 삐짐 검사)

OUT = os.path.join(ROOT, "out", "alerts_v2_cards")        # .gitignore 의 /out/ — 커밋하지 않는다
LONG_TITLE = "HANARO 코닥150레버 +12.3% · 1,234,567"        # 최장 데이터
WHY = "나스닥 동반 하락 · 외국인 선물 순매도가 받침 확대"      # 40자 상한 근처
NEXT = "확정 18:00 · 순매수로 돌아서면 알림 · 10/9 연휴 전"
SERIES = [{"date": f"2026-09-{26 + i:02d}", "close": 6800 + 40 * i + (i % 3) * 25} for i in range(5)] + \
         [{"date": "2026-10-01", "close": 7010}, {"date": "2026-10-02", "close": 7004}]


@pytest.fixture(autouse=True)
def _korean_font():
    if not dc._setup()[1]:
        pytest.skip("한글 폰트 없음 — 카드는 이 환경에서 예외로 멈춘다(test_no_korean_font_raises 는 폰트 있는 곳에서)")


def _ctx(with_series=True):
    return SimpleNamespace(
        now=dt.datetime(2026, 10, 2, 10, 0), rid=lambda t: t,
        registry={"kospi": {"id": "kospi", "short": "KOSPI", "source": "토스증권"}},
        series=lambda t, n: SERIES[-n:] if with_series and t == "kospi" else [])


def _row(level="alert", title="코스피 +6.1% · 7,004", **kw):
    r = {"key": "A1:kospi:up:2026-10-02", "event": "A1", "target": "kospi", "dir": "up", "level": level, "value": "7,004",
         "unit": "", "asOf": "2026-10-02", "fresh": "live", "title": title, "why": "나스닥 동반", "next": "다음 마디 8,000",
         "url": "#/i/kospi", "ts": "2026-10-02T10:00:12+09:00"}
    r.update(kw)
    return r


def _longest(level="alarm"):
    return _row(level, LONG_TITLE, value="1,234,567", why=WHY, next=NEXT, fresh="kept", target="kospi",
                fields={"line": 7000})


def _size(png: bytes):
    assert png[:4] == b"\x89PNG"
    return struct.unpack(">II", png[16:24])               # IHDR 폭 · 높이


def test_event_card_is_1080_square_png():
    for level in ("alarm", "alert", "notice"):
        assert _size(cards.event_card_png(_row(level), _ctx())) == (1080, 1080)


def test_bundle_card_is_1080_square_png():
    rows = [_row("alert", f"지표 {i} +2.{i}% · {7000 + i}", key=f"A1:x{i}:up:2026-10-02") for i in range(9)]
    assert _size(cards.bundle_card_png(rows, _ctx())) == (1080, 1080)
    assert _size(cards.bundle_card_png(rows[:2], _ctx())) == (1080, 1080)        # 6건 이하는 「+N」 없이


def test_longest_data_renders_all_levels():
    for level in ("alarm", "alert", "notice"):
        assert _size(cards.event_card_png(_longest(level), _ctx())) == (1080, 1080)
    assert _size(cards.bundle_card_png([_longest()] * 8, _ctx())) == (1080, 1080)


def test_numeric_value_uses_one_number_style():
    r = _row("alert", "외국인 5일째 순매도 · 오늘 −2,040억", value=-2040, unit="억", dir="sell")
    assert cards._value_text(r) == "−2,040억"
    assert cards._value_text(_row(value=None)) == "7,004"                          # 값이 비면 제목 뒷부분
    assert cards._value_text(_row(value="7,004")) == "7,004"                       # 글자 그대로


def test_chart_slot_becomes_cells_without_series():
    with_chart = cards._event_fig(_row(), _ctx())
    no_chart = cards._event_fig(_row(), _ctx(with_series=False))
    try:
        assert len(with_chart.axes) == 1 and len(no_chart.axes) == 0
    finally:
        dc._STATE["plt"].close(with_chart)
        dc._STATE["plt"].close(no_chart)
    assert _size(cards.event_card_png(_row(), _ctx(with_series=False))) == (1080, 1080)


def _figs():
    yield "event alarm 차트+임계선(최장)", cards._event_fig(_longest("alarm"), _ctx())
    yield "event alert 차트", cards._event_fig(_row("alert"), _ctx())
    yield "event notice 차트 없음(최장)", cards._event_fig(_longest("notice"), _ctx(with_series=False))
    yield "bundle 8건(최장)", cards._bundle_fig([_longest()] * 8, _ctx())


def test_no_text_overlap_and_min_font():
    """글자 겹침 · 캔버스 이탈 · 타일 삐짐 0건, 모든 글자 ≥ SQ_MIN_FS(test_card_layout 과 같은 검사)."""
    bad = {}
    for tag, fig in _figs():
        try:
            probs = problems(fig)
            small = [(t.get_text(), t.get_fontsize()) for t in
                     fig.texts + [x for ax in fig.axes for x in ax.texts + ax.get_xticklabels()]
                     if t.get_text().strip() and t.get_visible() and t.get_fontsize() < dc.SQ_MIN_FS]
            if probs or small:
                bad[tag] = (probs[:3], small[:3])
        finally:
            dc._STATE["plt"].close(fig)
    assert not bad, bad


def test_main_text_stays_readable_in_the_bubble():
    """카톡은 1080 카드를 270px 로 줄여 보인다 — 주 글자(제목 · 큰 숫자 · 왜 · 다음 · 칸 값)는 줄어든 뒤에도 9px 이상."""
    floor_pt = 9.0 / (150 / 72 * 270 / 1080)               # 9px ÷ (dpi/72 × 축소비) ≈ 17.3pt
    figs = {"event": cards._event_fig(_row(), _ctx()), "bundle": cards._bundle_fig([_row("alert", "지표 0 · 0")], _ctx())}
    main = {"event": ("코스피 +6.1%", "7,004", "나스닥 동반", "다음 마디 8,000", "지금", "10/2"), "bundle": ("지표 0 · 0",)}
    try:
        for k, fig in figs.items():
            sizes = {t.get_text(): t.get_fontsize() for t in fig.texts}
            for s in main[k]:
                assert s in sizes and sizes[s] >= floor_pt, (k, s, sizes.get(s), floor_pt)
    finally:
        for fig in figs.values():
            dc._STATE["plt"].close(fig)


def test_failures_raise():
    with pytest.raises(KeyError):
        cards.event_card_png({"level": "alert"}, _ctx())                          # 제목 없음 — 빈 카드로 나가지 않는다
    with pytest.raises(ValueError):
        cards.bundle_card_png([], _ctx())


def test_no_korean_font_raises(monkeypatch):
    monkeypatch.setitem(dc._STATE, "ko", False)
    with pytest.raises(RuntimeError):
        cards.event_card_png(_row(), _ctx())


def test_save_previews():
    """눈으로 볼 미리보기 — 등급 3 × 1장 + 묶음. 커밋하지 않는다(/out/)."""
    os.makedirs(OUT, exist_ok=True)
    shots = {"event_alarm": cards.event_card_png(_longest("alarm"), _ctx()),
             "event_alert": cards.event_card_png(_row("alert", why=WHY, next=NEXT), _ctx()),
             "event_notice": cards.event_card_png(_row("notice", "기준금리 동결 · 3.50%", value="3.50%", dir="change",
                                                     target="base_rate", event="C2"), _ctx()),
             "bundle": cards.bundle_card_png([_longest("alert")] * 3 + [_row("notice", f"지표 {i} · {i}") for i in range(5)],
                                             _ctx())}
    for name, png in shots.items():
        with open(os.path.join(OUT, name + ".png"), "wb") as f:
            f.write(png)
    assert all(_size(p) == (1080, 1080) for p in shots.values())


# ---------- 브리핑 카드(기획서 5장 대화창 목업) ----------
YS = [6800 + 30 * ((i * 7) % 11) - 2 * i for i in range(120)]
INFO_LONG = [("휴장", "10/3~10/5 휴장 · 다음 개장 10/6 · 미국은 정상 개장"), ("밤사이 알림", "3건 · " + LONG_TITLE),
             ("오늘 일정", "10/6 21:30 미국 CPI (전월비) ★★★ · 10/6 22:00 ISM 서비스 ★★"), ("외국인", "9일째 순매도 · 5일 누적 −7.1조")]


def _brief_specs():
    rows = [("S&P 500", "7,765.36", "▼0.47%", -0.47, ""), ("NASDAQ", "27,193.34", "▼1.25%", -1.25, ""),
            ("USD/KRW", "1,341.75", "■0.00%", 0.0, ""), ("USD/JPY", "157.83", "▲0.03%", 0.03, ""),
            ("미국 국채 10Y", "5.28%", "+1bp", 0.01, "10/7"), ("WTI 원유", "90.90$", "▲1.15%", 1.15, "")]
    tiles3 = [dc._cell("KOSPI", "6,625.93", "▼2.62%", -2.62), dc._cell("KOSDAQ", "892.27", "▼0.69%", -0.69),
              dc._cell("USD/KRW", "1,341.75", "■0.00%", 0.0)]
    tiles4 = [dc._cell(f"{n} 주간", v, t, c) for n, v, t, c, _ in rows[:4]]
    yield "아침 목록(최장)", {"title": "휴장일 아침 · 10/9(금) 07:30", "meta": "미국 10/8 마감", "rows": rows, "info": INFO_LONG,
                         "foot": "10/09 07:30 기준 · ecom"}
    yield "마감 칸+흐름+수급(최장)", {"title": "마감 · 10/8(목) 16:30", "meta": "수급 잠정", "tiles": tiles3,
                                "chart": {"ys": YS, "prev": 6804, "up": False, "label": "KOSPI 하루 흐름", "right": "6,625.93"},
                                "bars": [("외국인", -20240), ("기관", 4155), ("개인", 17897)],
                                "info": [("바뀐 것 12", LONG_TITLE), ("", WHY), ("", NEXT), ("휴장", INFO_LONG[0][1])]}
    yield "마감 수급 없음", {"title": "마감 · 10/8(목) 16:30", "meta": "수급 집계 중", "tiles": tiles3,
                         "chart": {"ys": YS, "prev": 6804, "label": "KOSPI 하루 흐름"}, "info": INFO_LONG}
    yield "주간 칸 4 + 행(최장)", {"title": "주간 · 10/4~10/10", "meta": "09:00", "tiles": tiles4,
                              "info": INFO_LONG + [("알림", LONG_TITLE), ("", WHY), ("", NEXT)]}


def test_brief_cards_layout_and_size():
    """브리핑 카드 3형 — 1080² · 글자 겹침 · 캔버스 이탈 · 타일 삐짐 0 · 모든 글자 ≥ SQ_MIN_FS · 꼬리 위로만."""
    bad = {}
    for tag, spec in _brief_specs():
        fig = cards._guarded(cards._draw_brief, spec)
        try:
            probs = problems(fig)
            small = [(t.get_text(), t.get_fontsize()) for t in
                     fig.texts + [x for ax in fig.axes for x in ax.texts + ax.get_xticklabels()]
                     if t.get_text().strip() and t.get_visible() and t.get_fontsize() < dc.SQ_MIN_FS]
            low = [t.get_text() for t in fig.texts if t.get_position()[1] < cards.Y_FLOOR - 0.01 and "기준" not in t.get_text()
                   and t.get_text() != "ecom"]
            if probs or small or low:
                bad[tag] = (probs[:3], small[:3], low[:3])
        finally:
            dc._STATE["plt"].close(fig)
        assert _size(cards.brief_card_png(spec)) == (1080, 1080)
    assert not bad, bad


def test_brief_quote_from_strip():
    """값 · 등락은 번들 띠(화면과 같은 값) — 금리는 bp, 나머지는 %, 띠 없으면 None."""
    strips = {"us10y": {"short": "미국 국채 10Y", "unit": "%", "decimals": 2, "value": 5.28, "change": -0.03, "asOf": "2026-10-07"},
              "sp500": {"short": "S&P 500", "decimals": 2, "value": 7765.36, "changePct": -0.47, "asOf": "2026-10-08"},
              "wti": {"short": "WTI 원유", "unit": "$", "decimals": 2, "value": 90.9, "changePct": 1.15, "asOf": "2026-10-09T10:36"}}
    ctx = SimpleNamespace(strip=strips.get)
    assert cards.quote(ctx, "us10y") == ("미국 국채 10Y", "5.28%", "−3bp", -0.03, dt.date(2026, 10, 7))
    assert cards.quote(ctx, "sp500")[1:3] == ("7,765.36", "▼0.47%")
    assert cards.quote(ctx, "wti")[1:3] == ("90.90$", "▲1.15%")
    assert cards.quote(ctx, "kospi") is None


def test_save_brief_previews():
    os.makedirs(OUT, exist_ok=True)
    for i, (_tag, spec) in enumerate(_brief_specs()):
        with open(os.path.join(OUT, f"brief_{i}.png"), "wb") as f:
            f.write(cards.brief_card_png(spec))
