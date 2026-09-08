#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""카톡 카드 라인업 가드(기획 v3 I4·I5).

두 가지를 고정한다:
  I5 — 카카오 발송은 send_card 단일 진입점만 쓴다. send_memo 직접 호출이 늘어나면
       라인업에 '사진 없는 경로'가 조용히 생기므로, 화이트리스트 밖 호출을 실패로 만든다.
  I4 — 정사각 카드는 말풍선에서 2.5배 축소돼 표시된다(1080 → 400px 안팎). 축소 후에도
       읽히도록 모든 본문 글자에 SQ_MIN_FS(단변의 2.2%) 하한이 걸려 있는지 검사한다.

실행: python scripts/tests/test_kakao_cards.py   (matplotlib 없으면 렌더 검사는 건너뜀)
"""
import io
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


# ── I5: 카카오 발송 진입점 단일화 ─────────────────────────────────────────
# 화이트리스트 = 진입점 자신의 텍스트 폴백(send_card 내부)과 차트 비활성(KAKAO_CHARTS=0)
# 경로, 그리고 발송 함수 정의·테스트 스텁.
_WHITELIST = {
    ("send_kakao_digest.py", "send_card 내부 3차 폴백"),
    ("send_kakao_digest.py", "차트 비활성 폴백"),
}


def test_no_direct_send_memo():
    """발송 스크립트에서 send_memo 직접 호출은 send_kakao_digest.py 안에서만 허용."""
    offenders = []
    for fn in ("check_alerts.py", "check_swings.py", "check_halts.py"):
        src = io.open(os.path.join(SCRIPTS, fn), encoding="utf-8").read()
        for i, line in enumerate(src.split("\n"), 1):
            if re.search(r"\bsend_memo\s*\(", line) and not line.strip().startswith("#"):
                offenders.append(f"{fn}:{i}")
    check("test_no_direct_send_memo", not offenders,
          f"send_card 를 쓰세요: {offenders}")


def test_send_card_is_used_by_every_sender():
    """세 발송 스크립트가 모두 send_card 를 통해 보낸다(사진 없는 경로 0)."""
    missing = [fn for fn in ("check_alerts.py", "check_swings.py", "check_halts.py")
               if "send_card(" not in io.open(os.path.join(SCRIPTS, fn), encoding="utf-8").read()]
    check("test_send_card_is_used_by_every_sender", not missing, f"미사용: {missing}")


def test_send_card_warns_without_png():
    """카드 없이 부르면 경고 + #시스템 통보(회귀를 눈에 보이게)."""
    import send_kakao_digest as k
    calls = {"notice": 0, "memo": 0}
    orig_notice, orig_memo = k._system_notice, k.send_memo
    k._system_notice = lambda t: calls.__setitem__("notice", calls["notice"] + 1)
    k.send_memo = lambda *a, **kw: calls.__setitem__("memo", calls["memo"] + 1)
    try:
        k.send_card("TOK", "제목", "캡션", png=None, kind="테스트")
    finally:
        k._system_notice, k.send_memo = orig_notice, orig_memo
    check("test_send_card_warns_without_png",
          calls["notice"] == 1 and calls["memo"] == 1, str(calls))


# ── I4: 축소 판독 규격 ────────────────────────────────────────────────────
def test_min_font_size_matches_spec():
    """SQ_MIN_FS = 단변 2.2%(1080px = 23.76px) → 150dpi 에서 11.4pt 이상."""
    import discord_card as dc
    need = 1080 * 0.022 * 72.0 / dc.SQ_DPI
    check("test_min_font_size_matches_spec", dc.SQ_MIN_FS >= need - 0.05,
          f"SQ_MIN_FS={dc.SQ_MIN_FS} < {need:.2f}")


def test_fs_clamps_only_square():
    import discord_card as dc
    check("test_fs_clamps_only_square",
          dc._fs(8, True) == dc.SQ_MIN_FS and dc._fs(8, False) == 8.0
          and dc._fs(30, True) == 30.0)


def test_square_canvas_is_1080():
    import discord_card as dc
    check("test_square_canvas_is_1080",
          dc.SQ[0] * dc.SQ_DPI == 1080 and dc.SQ[0] == dc.SQ[1])


# ── 도안 3형 렌더 — 사건형·상태형·지표형 ──────────────────────────────────
def _png_size(path):
    """PNG 헤더에서 (폭, 높이) — PIL 없이도 크기를 검사할 수 있게."""
    with open(path, "rb") as f:
        head = f.read(33)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return (0, 0)
    return (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))


def test_render_all_three_shapes():
    """세 도안이 1080² PNG 를 만들고 카카오 한도(5MB) 안에 든다."""
    try:
        import datetime
        import discord_card as dc
    except Exception as e:                                # matplotlib 부재 등
        print(f"  SKIP 렌더 검사 ({e})")
        return
    now = datetime.datetime(2026, 9, 8, 14, 30)
    xs = [now - datetime.timedelta(minutes=5 * i) for i in range(40)][::-1]
    ys = [3200 + i * 2 + (i % 5) * 3 for i in range(40)]
    cards = {
        "사건형(종목)": lambda: dc.stock_alert(
            {"name": "삼성전자", "cond": "목표가 70,000 상향 돌파", "price": 71200, "pct": 2.4,
             "target": 70000, "closes": [68000 + i * 100 for i in range(30)],
             "vol_today": 18500000, "vol_prev": 12100000, "market": "KR"},
            ["SK하이닉스 402,000 ▲3.1%"], now, shape="square",
            extra_tiles=[("코스피", "3,214", "▲0.62%", 0.62)]),
        "사건형(급변)": lambda: dc.swing("코스피", 3288.4, -2.35, 2.0, xs, ys, 3366.0, now,
                                     src="토스 1분봉", shape="square"),
        "상태형": lambda: dc.status("코스피 서킷 해제", "거래 재개", "14:02 발동 · 14:12 재개",
                                 timeline=[("14:02 발동", True), ("14:12 해제", True)],
                                 tiles=[("코스피", "2,940", "▼8.12%", -8.12)],
                                 now=now, tone="ok"),
        "지표형(마감)": lambda: dc.close_report(
            [("코스피", 3214.0, 0.62), ("코스닥", 826.0, -0.47)], now, alerts_cnt=2,
            cal="US CPI 21:30 ★★★", intraday=(xs, ys, 3200.0, "토스 1분봉"),
            investor={"foreign": 4120, "inst": -1830}, fired_names=["삼성전자", "SK하이닉스"],
            shape="square"),
    }
    for label, fn in cards.items():
        try:
            path = fn()
        except Exception as e:
            check(f"render {label}", False, f"예외 {e}")
            continue
        if not path:
            check(f"render {label}", False, "None 반환")
            continue
        w, h = _png_size(path)
        size_kb = os.path.getsize(path) / 1024
        check(f"render {label}", w == 1080 and h == 1080 and size_kb < 5120,
              f"{w}x{h} {size_kb:.0f}KB")


def test_weekly_square_exists():
    """주간 카드도 정사각 변형을 갖는다(기획 v3 I2 — 카톡 주간이 B등급에서 탈출)."""
    try:
        import datetime
        import json
        import discord_card as dc
    except Exception as e:
        print(f"  SKIP 주간 렌더 ({e})")
        return
    dpath = os.path.join(ROOT, "data.json")
    if not os.path.exists(dpath):
        print("  SKIP 주간 렌더 (data.json 없음)")
        return
    d = json.load(io.open(dpath, encoding="utf-8"))
    path = dc.weekly(d, datetime.datetime(2026, 9, 6, 17, 0), next_week="FOMC 수 03:00",
                     shape="square")
    ok = bool(path) and _png_size(path) == (1080, 1080)
    check("test_weekly_square_exists", ok, str(path))


def test_kakao_card_builder_routes_weekly():
    """_build_kakao_card(weekly=True) 가 주간 카드를 부른다(옛 라인 차트 분기 제거 확인)."""
    import send_kakao_digest as k
    src = io.open(os.path.join(SCRIPTS, "send_kakao_digest.py"), encoding="utf-8").read()
    check("test_kakao_card_builder_routes_weekly",
          "None if _weekly_mode" not in src and "weekly=_weekly_mode" in src
          and "weekly" in k._build_kakao_card.__code__.co_varnames)


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("test_"):
            fn()
    print(f"실패 {len(FAILED)}건" + (f": {FAILED}" if FAILED else ""))
    sys.exit(1 if FAILED else 0)
