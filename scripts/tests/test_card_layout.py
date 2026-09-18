#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""카드 글자 겹침 가드 (2026-09-17).

카드는 실패해도 조용히 None 을 돌려주고 옛 형식으로 폴백한다. 그래서 '렌더는 됐지만
글자가 서로 겹친 카드'는 어떤 경고도 남기지 않고 그대로 카톡·디스코드로 나간다 —
실제로 정사각 보드 6종 전부가 제목↔보조 겹침(최대 221px)을, 마감 카드가 발동 종목
줄의 캔버스 이탈(159px)과 일정↔footer 겹침을 달고 몇 달간 발송됐다.

그래서 '눈으로 본다'가 아니라 렌더러가 계산한 글자 상자로 기계 검사한다:

  OUT      캔버스 밖으로 벗어난 글자(말풍선에서 잘려 보인다)
  OVERLAP  글자끼리 겹침
  SPILL    타일 경계를 넘어 삐져나온 글자

재료는 '가장 빽빽한 경우'로 준다 — 특징주 6줄 + 발동 종목 7개 + 내일 일정이 한꺼번에
찬 마감 카드처럼, 자리가 모자라야 겹침이 드러난다.

실행: python scripts/tests/test_card_layout.py  (matplotlib 없으면 건너뜀)
"""
import datetime
import io
import itertools
import json
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


# ── 겹침 검출 ─────────────────────────────────────────────────────────────
def _texts(fig):
    """(소유자, Text) — figure 직속 + 각 axes 의 텍스트·축 라벨 중 실제로 보이는 것."""
    items = [("fig", t) for t in fig.texts]
    for i, ax in enumerate(fig.axes):
        items += [(f"ax{i}", t) for t in ax.texts]
        items += [(f"ax{i}.x", t) for t in ax.get_xticklabels()]
        items += [(f"ax{i}.y", t) for t in ax.get_yticklabels()]
    return [(o, t) for o, t in items if (t.get_text() or "").strip() and t.get_visible()]


def _ovl(b1, b2):
    return (min(b1.x1, b2.x1) - max(b1.x0, b2.x0), min(b1.y1, b2.y1) - max(b1.y0, b2.y0))


def problems(fig, tol=1.0):
    """figure 하나에서 찾은 [(종류, 설명)] — 비어 있으면 합격."""
    from matplotlib.patches import FancyBboxPatch
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    W, H = fig.canvas.get_width_height()
    rows = []
    for owner, t in _texts(fig):
        try:
            rows.append((owner, t.get_text(), t.get_window_extent(renderer=r)))
        except Exception:
            pass
    tiles = []
    for p in fig.patches:
        if isinstance(p, FancyBboxPatch):
            try:
                tiles.append(p.get_window_extent(renderer=r))
            except Exception:
                pass
    out = []
    for owner, s, bb in rows:
        if bb.x0 < -tol or bb.y0 < -tol or bb.x1 > W + tol or bb.y1 > H + tol:
            out.append(("OUT", f"{owner} {s!r} → ({bb.x0:.0f},{bb.y0:.0f})-({bb.x1:.0f},{bb.y1:.0f})"
                               f" / 캔버스 {W}x{H}"))
    for (o1, s1, b1), (o2, s2, b2) in itertools.combinations(rows, 2):
        ox, oy = _ovl(b1, b2)
        if ox > tol and oy > tol:
            out.append(("OVERLAP", f"{o1} {s1!r} × {o2} {s2!r} ({ox:.0f}x{oy:.0f}px)"))
    for owner, s, bb in rows:
        if owner != "fig":
            continue
        for tb in tiles:
            ox, oy = _ovl(bb, tb)
            if ox > tol and oy > tol and not (bb.x0 >= tb.x0 - tol and bb.x1 <= tb.x1 + tol
                                              and bb.y0 >= tb.y0 - tol and bb.y1 <= tb.y1 + tol):
                out.append(("SPILL", f"{s!r} 가 타일 밖으로 ({ox:.0f}x{oy:.0f}px)"))
    return out


# ── 재료(최악 조건) ───────────────────────────────────────────────────────
NOW = datetime.datetime(2026, 9, 17, 15, 42)
_XS = [NOW.replace(hour=9, minute=0) + datetime.timedelta(minutes=5 * i) for i in range(78)]
_YS = [2500 + 40 * math.sin(i / 9.0) + (i % 7) for i in range(78)]
_CLOSES = [70000 + 3000 * math.sin(i / 3.0) + (i % 11) * 80 for i in range(30)]
# 제목줄을 가장 세게 미는 조합 — 실제 경제 캘린더에 있는 최장 문구(36자) + MOVE.
LONG_CAL = "US 미국 주택착공 (Housing Starts) 21:30 ★★"
HERO = {"name": "에이치엘비생명과학", "cond": "목표가 도달 · 종가 82,400원 ≥ 목표 80,000원",
        "price": 82400, "pct": 7.42, "target": 80000, "closes": _CLOSES,
        "vol_today": 31450000, "vol_prev": 8900000, "market": "KR"}
# 나머지 종목은 구조화 튜플 (이름, 가격문자열, 등락률, 조건) — 2026-09-18 계약 변경.
OTHERS = [("삼성전자", "71,200원", 2.41, "목표가"), ("SK하이닉스", "248,500원", -1.80, "지정가"),
          ("카카오", "44,150원", 5.02, "신고가"), ("LG에너지솔루션", "393,000원", -0.75, "데드크로스")]
ITEMS = [("코스피", 2548.9, 0.93), ("코스닥", 816.6, 0.38), ("닛케이", 63923, 0.49),
         ("S&P500", 7552.1, -2.21), ("달러-원", 1379.7, 0.18)]
MOVERS = ([{"name": "한화오션우선주", "chg": 29.9}, {"name": "두산에너빌리티", "chg": 12.4},
           {"name": "포스코퓨처엠", "chg": 9.1}],
          [{"name": "에코프로비엠", "chg": -11.2}, {"name": "엘앤에프", "chg": -8.7},
           {"name": "카카오뱅크", "chg": -6.3}])
INV = {"foreign": -12450, "inst": 8320, "retail": 4130, "date": "2026-09-17", "reason": "(잠정)"}
FIRED = ["에이치엘비생명과학", "삼성전자", "SK하이닉스", "카카오", "네이버", "현대차", "기아"]
CLOSE_CAL = "미국 CPI 발표 · 한은 금통위 · 옵션만기"


def _cases(dc, d):
    """[(이름, 렌더 함수)] — 6편성 보드 × 2모양 + 사건형·지표형·상태형."""
    cases = []
    for k in dc.PROFILES:
        for shape in ("wide", "square"):
            hero = None
            if shape == "square":
                hk = dc.HERO.get(k, "")
                hc = (dc._CATALOG.get(hk) or ("", "", "indices"))[2]
                vs = dc._hist(d, hc, hk)
                base = datetime.datetime(NOW.year, NOW.month, NOW.day)
                hero = ([base + datetime.timedelta(days=i) for i in range(len(vs))],
                        vs, (vs[0] if vs else None), "일봉 30D")
            cases.append((f"board {k} {shape}",
                          lambda k=k, s=shape, h=hero:
                          dc.board(d, NOW, cal=LONG_CAL, profile=k, shape=s, hero=h)))
    for shape in ("wide", "square"):
        cases += [
            (f"stock {shape}",
             lambda s=shape: dc.stock_alert(HERO, OTHERS, NOW, shape=s)),
            (f"close {shape}",
             lambda s=shape: dc.close_report(ITEMS, NOW, alerts_cnt=17, cal=CLOSE_CAL,
                                             intraday=(_XS, _YS, 2525.0, "토스"), investor=INV,
                                             movers=MOVERS, fired_names=FIRED, shape=s)),
            (f"close-min {shape}", lambda s=shape: dc.close_report(ITEMS[:2], NOW, shape=s)),
            (f"weekly {shape}",
             lambda s=shape: dc.weekly(d, NOW, next_week="미국 CPI·한은 금통위·옵션만기·FOMC 의사록",
                                       shape=s)),
            (f"swing {shape}",
             lambda s=shape: dc.swing("에이치엘비생명과학", 82400, 7.42, 5.0, _XS, _YS, 80100.0,
                                      NOW, resume="09/17 14:30 거래 재개", src="토스 인트라데이",
                                      shape=s)),
        ]
    cases.append(("status", lambda: dc.status(
        "종목 알림 경로 확인", "정상", "알림 24건 평가 · 현재 충족 조건 없음",
        timeline=[("설정 읽기", True), ("시세 조회", True), ("발송", True)],
        tiles=[("평가", "24", "건", None), ("충족", "0", "건", None),
               ("전역 알림", "ON", "", None)], now=NOW, tone="info")))
    return cases


def test_no_text_overlap_in_any_card():
    """모든 카드 도안에서 글자 겹침·캔버스 이탈·타일 삐짐이 0건."""
    try:
        import discord_card as dc
    except Exception as e:                                # matplotlib 부재 등
        print(f"  SKIP 겹침 검사 ({e})")
        return
    dpath = os.path.join(ROOT, "data.json")
    if not os.path.exists(dpath):
        print("  SKIP 겹침 검사 (data.json 없음)")
        return
    d = json.load(io.open(dpath, encoding="utf-8"))

    found = {}
    orig_save = dc._save

    def spy(fig, name):
        p = problems(fig)
        if p:
            found[dc._LAYOUT_TAG] = p
        return orig_save(fig, name)

    dc._save = spy
    try:
        for tag, fn in _cases(dc, d):
            dc._LAYOUT_TAG = tag
            try:
                if not fn():
                    check(f"render {tag}", False, "None 반환")
            except Exception as e:
                check(f"render {tag}", False, f"예외 {e}")
    finally:
        dc._save = orig_save

    for tag, probs in found.items():
        check(f"layout {tag}", False, "; ".join(f"[{k}] {v}" for k, v in probs[:4]))
    check("test_no_text_overlap_in_any_card", not found, f"{len(found)}종에서 겹침")


def test_clip_fits_the_given_width():
    """_clip 이 돌려준 문자열은 반드시 요구 폭 안에 든다(빈 문자열 제외)."""
    try:
        import discord_card as dc
    except Exception as e:
        print(f"  SKIP _clip 검사 ({e})")
        return
    plt, _ = dc._setup()
    fig = plt.figure(figsize=dc.SQ, dpi=dc.SQ_DPI)
    try:
        for s in ("코스피 2,548.9 ▲0.93% · 코스닥 816.6 ▲0.38% · 닛케이 63,923 ▲0.49%",
                  "에이치엘비생명과학 · 삼성전자 · SK하이닉스 · 카카오 · 네이버 · 현대차 · 기아",
                  "MOVE 80.7 ▼3.56% · 오늘 " + LONG_CAL, "짧음"):
            for room in (0.12, 0.30, 0.62):
                got = dc._clip(fig, s, room, 12.5)
                w = dc._text_w(fig, got, 12.5)
                check(f"_clip({room}) {got[:14]!r}", (not got) or w <= room + 1e-6,
                      f"폭 {w:.3f} > {room}")
    finally:
        plt.close(fig)


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("test_"):
            fn()
    print(f"실패 {len(FAILED)}건" + (f": {FAILED}" if FAILED else ""))
    sys.exit(1 if FAILED else 0)
