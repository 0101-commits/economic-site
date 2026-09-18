#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""가독성 게이트 (2026-09-18 개편).

test_card_layout.py 는 '겹치지 않는가'를 본다. 이 파일은 '읽히는가'를 본다 — 겹침이
없어도 ①정보가 잘려 사라지고 ②같은 숫자가 한 통에 두 번 실리고 ③색이 크기를 말하지
않고 ④캔버스 절반이 비어 글자가 작아지는 상태는 어떤 경고도 남기지 않고 발송된다.

게이트 6종:
  정보 보존   동시 발동 나머지 종목 타일에 이름·등락률이 온전히 남아 있나
  중복        카드 타일이 보여주는 지표가 피드 본문에 다시 실리지 않나
  축소 판독   정사각 카드의 글자 하한(SQ_MIN_FS)이 지켜지고 주 숫자가 9px 이상인가
  강도 대비   0.2% 칸과 2.0% 칸의 배경이 구별되나 / 0.2% 칸이 흰 바탕에 가깝나
  여백        캔버스를 4등분했을 때 잉크가 없는 구간이 없나
  잘림 고지   200자 한도로 줄이 빠지면 '외 N항목'이 남나

실행: python scripts/tests/test_readability.py  (matplotlib 없으면 렌더 검사만 건너뜀)
"""
import datetime
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

FAILED = []
NOW = datetime.datetime(2026, 9, 18, 15, 40)

# 카톡 말풍선 축소비 — 1080px 카드가 약 270px 로 표시된다(CLAUDE.md 판독 규격).
BUBBLE_SCALE = 270.0 / 1080.0
READABLE_PX = 9.0            # 한글 하한 — 주 숫자(값·등락률)에 적용
# 보조 정보(footer·축 눈금·기준선 라벨)는 9px 아래가 정상이다. 대신 '하한 자체'를 지킨다:
# 정사각 카드의 모든 글자는 SQ_MIN_FS 로 바닥이 걸려 있어야 한다(_fs(square=True)).
# 가로 카드는 디스코드 전용이고 축소비·클릭 확대가 달라 별도 하한(10pt)만 본다.
WIDE_MIN_PT = 10.0


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


# ── 재료 ──────────────────────────────────────────────────────────────────
HERO = {"name": "삼성전자", "cond": "목표가 78,000원", "price": 78500, "pct": 3.2,
        "target": 78000, "closes": [76000 + i * 90 for i in range(30)],
        "vol_today": 21000000, "vol_prev": 14000000, "market": "KR"}
OTHERS = [("SK하이닉스", "412,000원", 5.1, "신고가"),
          ("NAVER", "198,000원", -2.4, "지정가"),
          ("LG에너지솔루션", "393,000원", -0.75, "데드크로스")]


def _data():
    with open(os.path.join(ROOT, "data.json"), encoding="utf-8") as f:
        return json.load(f)


# ── ① 정보 보존 ───────────────────────────────────────────────────────────
def test_other_symbol_tiles_keep_change_pct(dc):
    """나머지 종목 타일이 등락률을 잃지 않는다.

    종전엔 완성된 발동 문장을 공백으로 쪼개 타일에 넣어 '412,000원(+5…' 만 남았다.
    타일 문자열을 직접 들여다보는 대신, 카드가 실제로 그린 텍스트를 읽어 확인한다."""
    fig = _fig_of(dc, lambda: dc._stock_square(dc._STATE["plt"], HERO, OTHERS, NOW, None))
    if fig is None:
        return
    txts = [t.get_text() for _o, t in _texts(fig)]
    for nm, _px, pct, cond in OTHERS:
        # 이름은 언제나 온전해야 한다(잘리면 어느 종목인지 알 수 없다). 조건은 한 칸에
        # 함께 들어갈 때만 붙는다 — 긴 이름은 조건을 버리고 이름을 살린다.
        lab = next((s for s in txts if s.startswith(nm[:4])), "")
        check(f"타일 이름 온전 {nm}", lab.startswith(nm) and not lab.endswith("…"),
              f"라벨='{lab}'")
    # 등락률 셋 다 그려졌나 — 방향 기호 + 소수 2자리
    pcts = [s for s in txts if s.startswith(("▲", "▼")) and s.endswith("%")]
    check("나머지 종목 등락률 3건", len(pcts) >= 4, f"발견 {len(pcts)}건(히어로 포함)")
    dc._STATE["plt"].close(fig)


# ── ② 중복 ────────────────────────────────────────────────────────────────
def test_feed_body_excludes_card_tiles(kakao):
    """카드 타일 지표가 피드 본문(설명·행)에 다시 실리지 않는다."""
    d = _data()
    drop = kakao._card_tile_labels("h10", False, NOW)
    check("카드 타일 목록 조회", bool(drop), f"drop={sorted(drop)}")
    _t, blocks = kakao.build_digest_parts(d, drop=drop)
    desc, items = kakao.build_feed_parts(blocks)
    body = desc + " " + " ".join(f"{i['item']} {i['item_op']}" for i in items)
    dup = sorted(lab for lab in drop if lab in body)
    check("피드 본문 ↔ 카드 타일 중복 0", not dup, f"중복={dup}")


# ── ③ 축소 판독 ───────────────────────────────────────────────────────────
def _screen_px(t, fig):
    """말풍선에 표시될 글자 높이(px) = pt ÷ 72 × dpi × 축소비."""
    return t.get_fontsize() / 72.0 * fig.dpi * BUBBLE_SCALE


def test_bubble_legibility(dc, cards):
    for name, make in cards.items():
        fig = _fig_of(dc, make)
        if fig is None:
            continue
        square = "정사각" in name
        pts = [t.get_fontsize() for _o, t in _texts(fig)]
        floor = dc.SQ_MIN_FS if square else WIDE_MIN_PT
        low = [p for p in pts if p < floor - 0.01]
        check(f"글자 하한 {name}", not low,
              f"하한 {floor}pt 미달 {len(low)}건 (최소 {min(pts):.1f}pt)")
        if square:                                    # 주 숫자는 축소 후에도 9px 이상
            top = sorted(_screen_px(t, fig) for _o, t in _texts(fig))[-3:]
            check(f"주 숫자 판독 {name}", min(top) >= READABLE_PX,
                  f"상위 3개 {[round(x, 1) for x in top]}px (하한 {READABLE_PX})")
        dc._STATE["plt"].close(fig)


# ── ④ 강도 대비 ───────────────────────────────────────────────────────────
def _lum(hexs):
    r, g, b = (int(hexs[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def test_saturation_carries_magnitude(dc):
    """색은 방향이 아니라 크기를 말해야 한다 — 작은 등락은 흰 바탕에 가깝고,
    큰 등락만 눈에 들어와야 한다. 하한 0.30 시절엔 0.2% 도 뚜렷한 분홍이었다."""
    small, _i1, _f1 = dc._tile_color(0.2, 3.0)
    big, _i2, _f2 = dc._tile_color(2.0, 3.0)
    ls, lb, lw = _lum(small), _lum(big), _lum(dc.BG)
    # 실측 1.24:1(하한 0.10 기준) — 사실상 흰색이다. 1.3 을 넘으면 하한이 다시 올라간 것.
    check("0.2% 칸은 흰 바탕에 가깝다", (lw + 0.05) / (ls + 0.05) <= 1.3,
          f"대비 {(lw + 0.05) / (ls + 0.05):.2f}:1")
    check("0.2% ↔ 2.0% 칸 구별", (ls - lb) / max(ls, 1e-6) >= 0.25,
          f"밝기 차 {(ls - lb) / max(ls, 1e-6):.0%}")
    check("보합은 무채색", dc._tile_color(0.0, 3.0)[2] is True)


# ── ⑤ 여백 ────────────────────────────────────────────────────────────────
def test_no_empty_band(dc, cards):
    """캔버스를 세로 4등분했을 때 잉크(글자·타일)가 없는 구간이 없다.

    디스코드·카톡은 이미지를 폭에 맞춰 축소하므로, 빈 띠는 그만큼 글자를 작게 만든다."""
    for name, make in cards.items():
        fig = _fig_of(dc, make)
        if fig is None:
            continue
        fig.canvas.draw()
        H = fig.bbox.height
        bands = [0, 0, 0, 0]
        boxes = [t.get_window_extent(renderer=fig.canvas.get_renderer())
                 for _o, t in _texts(fig)]
        boxes += [ax.get_window_extent() for ax in fig.axes]
        for b in boxes:
            for i in range(4):
                if b.y1 > H * i / 4 and b.y0 < H * (i + 1) / 4:
                    bands[i] += 1
        empty = [i for i, n in enumerate(bands) if n == 0]
        check(f"빈 띠 없음 {name}", not empty, f"빈 구간(아래→위) {empty} · 분포 {bands}")
        dc._STATE["plt"].close(fig)


# ── ⑥ 잘림 고지 ───────────────────────────────────────────────────────────
def test_truncation_is_announced(kakao):
    blocks = [(f"블록{i}", f"지표{i} " + "9" * 40) for i in range(6)]
    msg = kakao.build_text_message("제목", blocks)
    check("200자 한도 준수", len(msg) <= kakao.TEXT_LIMIT, f"{len(msg)}자")
    check("생략 고지 표시", "외 " in msg and "항목" in msg, msg[-14:])
    full = kakao.build_text_message("제목", [("증시", "코스피 3,150▲1.2%")])
    check("다 들어가면 고지 없음", "항목" not in full, full)


# ── 렌더 헬퍼 ─────────────────────────────────────────────────────────────
def _texts(fig):
    items = [("fig", t) for t in fig.texts]
    for i, ax in enumerate(fig.axes):
        items += [(f"ax{i}", t) for t in ax.texts]
        items += [(f"ax{i}.x", t) for t in ax.get_xticklabels()]
        items += [(f"ax{i}.y", t) for t in ax.get_yticklabels()]
    return [(o, t) for o, t in items if (t.get_text() or "").strip() and t.get_visible()]


_FIGS = {}


def _fig_of(dc, make):
    """카드 함수는 PNG 경로만 돌려주므로, _save 를 가로채 figure 를 붙든다."""
    keep = {}
    orig = dc._save

    def spy(fig, name):
        keep["fig"] = fig
        return name                                   # 저장·close 를 건너뛴다

    dc._save = spy
    try:
        make()
    finally:
        dc._save = orig
    return keep.get("fig")


def main():
    try:
        import discord_card as dc
        import send_kakao_digest as kakao
        dc._setup()
    except Exception as e:                            # matplotlib 부재 등
        print(f"SKIP 가독성 게이트 ({e})")
        return 0
    d = _data()
    plt = dc._STATE["plt"]
    items = [("코스피", 6860, 2.4), ("코스닥", 828.1, 0.96), ("S&P500", 7638, -0.9),
             ("나스닥", 25100, -1.2), ("달러-원", 1383.8, 0.27)]
    hero_sq = ([NOW - datetime.timedelta(minutes=5 * i) for i in range(40)][::-1],
               [6800 + i * 2 for i in range(40)], 6790.0, "토스 1분봉")
    cards = {
        "보드(정사각)": lambda: dc.board(d, NOW, shape="square", profile="kr_session",
                                     hero=hero_sq),
        "보드(가로)": lambda: dc.board(d, NOW, shape="wide", profile="kr_session"),
        "종목(정사각)": lambda: dc.stock_alert(HERO, OTHERS, NOW, shape="square"),
        "종목(가로)": lambda: dc.stock_alert(HERO, OTHERS, NOW, shape="wide"),
        "마감(재료 최소)": lambda: dc.close_report(items, NOW, alerts_cnt=3,
                                              cal="US CPI 21:30 ★★★"),
        "급변(정사각)": lambda: dc.swing("코스피", 6860.0, 2.4, 2.0, hero_sq[0], hero_sq[1],
                                    6700.0, NOW, src="토스 1분봉", shape="square"),
    }
    print("① 정보 보존")
    test_other_symbol_tiles_keep_change_pct(dc)
    print("② 중복")
    test_feed_body_excludes_card_tiles(kakao)
    print("③ 축소 판독")
    test_bubble_legibility(dc, cards)
    print("④ 강도 대비")
    test_saturation_carries_magnitude(dc)
    print("⑤ 여백")
    test_no_empty_band(dc, cards)
    print("⑥ 잘림 고지")
    test_truncation_is_announced(kakao)
    plt.close("all")
    print(f"실패 {len(FAILED)}건" + (": " + ", ".join(FAILED) if FAILED else ""))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
