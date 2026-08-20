#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""디스코드 전용 '시각 보드' 카드 렌더러 (기획 2026-08-11, 아티팩트 e9144cf7).

카드 4종 — 전부 embed 이미지 1장이 본문이 되는 형식(카카오는 무변경):
  board()        카드 A: 정기 다이제스트 — 히트맵 타일 12(+캡션 4) + 30일 스파크라인 4
  close_report() 카드 B: 장 마감 — 다이버징 수평 바 + 오늘 발동 알림 수·내일 일정
  weekly()       카드 C: 주간 — 주간 수익률 정렬 다이버징 바
  swing()        카드 D: 급변·서킷 — 히어로 등락률 + 인트라데이 임계선

신뢰성: 모든 공개 함수는 예외를 내부에서 삼키고 None 을 반환 — 호출측이 기존
embed(필드/슬롯 차트)로 폴백한다. 카드 실패가 알림 실패가 되지 않는다.

색: 상승 #E0443E / 하락 #3E7BE0 (국내 관습) — 디스코드 다크 표면 #313338 기준
CVD ΔE 24.4 · 대비 3:1+ 검증 통과(기획안 참조). 강도는 표면과의 혼합비(램프)로.

폰트: 한글 폰트(Noto Sans CJK KR — kakao-daily.yml 이 설치 / 로컬 Malgun Gothic)를
찾고, 없으면 영문 라벨로 강등(stock-alerts.yml 은 매분 런이라 폰트 미설치).
이모지는 CI 폰트에 없어 카드 내부 텍스트에 쓰지 않는다(embed 제목이 담당).
"""
import datetime
import os
import tempfile

BG = "#313338"        # 디스코드 다크 embed 표면
TILE = "#3A3D44"
INK = "#F2F3F5"
MUT = "#B5BAC1"
FAINT = "#7A7F87"
UP = "#E0443E"
DN = "#3E7BE0"
LINE = "#D7DBE1"

_KO_FONTS = ["Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR"]
_STATE = {}           # {"plt": module, "ko": bool} — 1회 초기화 캐시


def _setup():
    """matplotlib 지연 로드 + 한글 폰트 탐지. 반환 (plt, 한글가능여부)."""
    if "plt" not in _STATE:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        avail = {f.name for f in font_manager.fontManager.ttflist}
        ko = next((n for n in _KO_FONTS if n in avail), None)
        plt.rcParams["font.family"] = [ko] if ko else ["DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        if not ko:
            print("[card] 한글 폰트 없음 — 영문 라벨로 강등")
        _STATE["plt"] = plt
        _STATE["ko"] = bool(ko)
    return _STATE["plt"], _STATE["ko"]


def _L(ko, en):
    return ko if _STATE.get("ko") else en


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _node(d, cat, key):
    n = (d.get(cat) or {}).get(key) or {}
    price = _f(n.get("price") if n.get("price") is not None else n.get("rate"))
    chg = _f(n.get("change") if n.get("change") is not None else n.get("chgPct"))
    return price, chg


def _hist(d, cat, key, days=30):
    h = ((d.get("history") or {}).get(cat) or {}).get(key) or []
    vals = [_f(r.get("close")) for r in h[-days:]]
    return [v for v in vals if v is not None]


def _fmt(v):
    if v is None:
        return "—"
    return f"{v:,.2f}" if v < 100 else f"{v:,.0f}" if v > 5000 else f"{v:,.1f}"


def _chgtxt(c):
    if c is None:
        return ""
    a = "▲" if c > 0 else "▼" if c < 0 else "■"
    return f"{a}{abs(c):.2f}%"


def _tile_color(c):
    """등락 → (타일 배경, 라벨 잉크). 방향=색상, 강도=표면과의 혼합비(±3%에서 포화)."""
    if c is None or abs(c) < 0.05:
        return TILE, MUT
    base = UP if c > 0 else DN
    a = min(0.95, 0.30 + abs(c) / 3.0 * 0.65)
    rgb = tuple(int(base[i:i + 2], 16) for i in (1, 3, 5))
    bgc = tuple(int(BG[i:i + 2], 16) for i in (1, 3, 5))
    mix = tuple(int(x * a + y * (1 - a)) for x, y in zip(rgb, bgc))
    return "#%02x%02x%02x" % mix, INK


def _footer(fig, now, extra=""):
    fig.text(0.03, 0.022, _L(f"시세 {now.strftime('%m/%d %H:%M')} 기준 · 무료 시세 지연 가능",
                             f"as of {now.strftime('%m/%d %H:%M')} KST · free quotes may lag") + extra,
             color=FAINT, fontsize=11)
    fig.text(0.97, 0.022, "econ dashboard →", color=FAINT, fontsize=11, ha="right")


def _save(fig, name):
    plt = _STATE["plt"]
    path = os.path.join(tempfile.gettempdir(), name)
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return path


# (한글, 영문, 카테고리, 키) — 카드 A 타일 12(+캡션 4) · 카드 C 상위 12 재사용
_ASSETS = [("코스피", "KOSPI", "indices", "KOSPI"), ("코스닥", "KOSDAQ", "indices", "KOSDAQ"),
           ("S&P500", "S&P500", "indices", "SP500"), ("나스닥", "NASDAQ", "indices", "NASDAQ"),
           ("닛케이", "Nikkei", "indices", "Nikkei"), ("SOX 반도체", "SOX", "indices", "SOX"),
           ("달러-원", "USD/KRW", "fx", "USDKRW"), ("달러-엔", "USD/JPY", "fx", "USDJPY"),
           ("금", "Gold", "commodities", "Gold"), ("구리", "Copper", "commodities", "Copper"),
           ("WTI", "WTI", "commodities", "WTI"), ("천연가스", "NatGas", "commodities", "NatGas"),
           ("밀", "Wheat", "commodities", "Wheat"), ("옥수수", "Corn", "commodities", "Corn"),
           ("은", "Silver", "commodities", "Silver"), ("브렌트", "Brent", "commodities", "Brent")]


def board(d, now, cal=""):
    """카드 A — 시황 보드. 실패 시 None(호출측이 슬롯 차트로 폴백).

    v4(기획 ed0e5496 — 버튼 다이어트): 폐기된 16버튼 그리드의 정보를 카드가 단독
    흡수한다 — 타일 16→12 로 줄여 키우고(4×3), 글자 전반 확대 + dpi 130→160 으로
    모바일 가독성 확보. 밀려난 저변동 4종(밀·옥수수·은·브렌트)은 하단 캡션 한 줄."""
    try:
        plt, _ = _setup()
        fig = plt.figure(figsize=(10, 7.0), dpi=160)
        fig.patch.set_facecolor(BG)
        fig.text(0.03, 0.945, _L(f"{now.month}/{now.day} {now.hour}시 시황 보드",
                                 f"{now.month}/{now.day} {now.hour}h Market Board"),
                 color=INK, fontsize=19, fontweight="bold")
        mv = ((d.get("sentiment") or {}).get("move")) or {}
        head = []
        if _f(mv.get("value")) is not None:
            head.append(f"MOVE {mv['value']:.1f} {_chgtxt(_f(mv.get('change')))}".strip())
        if cal:
            head.append((_L("오늘 ", "today ") + cal).strip())
        if head:
            fig.text(0.97, 0.950, " · ".join(head), color=MUT, fontsize=11, ha="right")
        cols, rows = 4, 3
        gx0, gy0, gw, gh = 0.03, 0.44, 0.94, 0.46
        from matplotlib.patches import FancyBboxPatch
        for i, (ko, en, cat, key) in enumerate(_ASSETS[:12]):
            r_, c_ = divmod(i, cols)
            x = gx0 + c_ * gw / cols
            y = gy0 + (rows - 1 - r_) * gh / rows
            w, h = gw / cols - 0.008, gh / rows - 0.016
            price, chg = _node(d, cat, key)
            bgc, ink = _tile_color(chg)
            fig.patches.append(FancyBboxPatch(
                (x, y), w, h, boxstyle="round,pad=0.004,rounding_size=0.008",
                transform=fig.transFigure, fc=bgc, ec="none"))
            fig.text(x + 0.012, y + h - 0.038, _L(ko, en),
                     color=ink if bgc != TILE else MUT, fontsize=13)
            fig.text(x + 0.012, y + 0.048, _fmt(price), color=INK, fontsize=17, fontweight="bold")
            fig.text(x + w - 0.010, y + 0.014, _chgtxt(chg),
                     color=INK if bgc != TILE else MUT, fontsize=13, fontweight="bold", ha="right")
        # 타일에서 밀려난 저변동 4종 — 캡션 한 줄(정보 유실 방지).
        rest = " · ".join(f"{_L(ko, en)} {_chgtxt(_node(d, cat, key)[1]) or '—'}"
                          for ko, en, cat, key in _ASSETS[12:])
        fig.text(0.03, 0.395, rest, color=MUT, fontsize=11)
        fig.text(0.03, 0.335, _L("추세 30일", "30-day trend"), color=MUT, fontsize=12)
        sparks = [_ASSETS[0], _ASSETS[2], _ASSETS[6], _ASSETS[8]]  # 코스피·S&P·달러원·금
        for i, (ko, en, cat, key) in enumerate(sparks):
            ax = fig.add_axes([0.03 + i * 0.2425, 0.075, 0.205, 0.235])
            ax.set_facecolor(TILE)
            vs = _hist(d, cat, key)
            if vs:
                ax.plot(vs, color=LINE, lw=1.6)
                dirc = UP if vs[-1] >= vs[0] else DN
                ax.plot(len(vs) - 1, vs[-1], "o", color=dirc, ms=5)
                p30 = (vs[-1] / vs[0] - 1) * 100 if vs[0] else 0.0
                ax.text(0.05, 0.84, _L(ko, en), transform=ax.transAxes, color=MUT, fontsize=12)
                ax.text(0.95, 0.84, f"{'+' if p30 >= 0 else ''}{p30:.1f}%", transform=ax.transAxes,
                        color=dirc, fontsize=12, ha="right", fontweight="bold")
                ax.text(0.05, 0.08, _fmt(vs[-1]), transform=ax.transAxes, color=INK, fontsize=13)
            ax.set_xticks([]); ax.set_yticks([])
            for s in ax.spines.values():
                s.set_visible(False)
        _footer(fig, now)
        return _save(fig, "discord_card_board.png")
    except Exception as e:
        print(f"::warning title=디스코드 카드 실패::board: {e} — 기존 형식 폴백")
        return None


def close_report(items, now, alerts_cnt=None, cal=""):
    """카드 B — 장 마감. items=[(라벨, 가격, 등락%)]. 실패 시 None."""
    try:
        plt, _ = _setup()
        its = [(l, p, c if c is not None else 0.0) for l, p, c in items if p is not None][::-1]
        if not its:
            return None
        fig = plt.figure(figsize=(10, 5.8), dpi=130)
        fig.patch.set_facecolor(BG)
        fig.text(0.03, 0.94, _L(f"{now.month}/{now.day} 장 마감 리포트",
                                f"{now.month}/{now.day} Market Close"),
                 color=INK, fontsize=18, fontweight="bold")
        ax = fig.add_axes([0.13, 0.14, 0.50, 0.70])
        ax.set_facecolor(BG)
        chgs = [c for _, _, c in its]
        ax.barh(range(len(its)), chgs, height=0.52,
                color=[UP if c > 0 else DN if c < 0 else FAINT for c in chgs])
        ax.axvline(0, color=FAINT, lw=1)
        for i, (l, p, c) in enumerate(its):
            ax.text(c + (0.06 if c >= 0 else -0.06), i, f"{_fmt(p)}  {_chgtxt(c)}",
                    va="center", ha="left" if c >= 0 else "right", color=INK, fontsize=12.5)
        ax.set_yticks(range(len(its)))
        ax.set_yticklabels([l for l, _, _ in its], color=MUT, fontsize=13)
        lim = max(abs(c) for c in chgs) * 1.9 + 0.3
        ax.set_xlim(-lim, lim)
        ax.set_xticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0)
        y = 0.80
        if alerts_cnt is not None:
            fig.text(0.70, y, _L("오늘 발동 알림", "alerts fired today"), color=MUT, fontsize=12.5)
            fig.text(0.70, y - 0.10, _L(f"{alerts_cnt}건", f"{alerts_cnt}"),
                     color=INK, fontsize=24, fontweight="bold")
            y -= 0.30
        if cal:
            fig.text(0.70, y, _L("내일 일정", "tomorrow"), color=MUT, fontsize=12.5)
            fig.text(0.70, y - 0.08, cal, color=INK, fontsize=12)
        _footer(fig, now)
        return _save(fig, "discord_card_close.png")
    except Exception as e:
        print(f"::warning title=디스코드 카드 실패::close: {e} — 기존 형식 폴백")
        return None


def weekly_rows(d):
    """주간 수익률 정렬 [(ko, en, key, chg%)] — weekly() 차트와 버튼 그리드(v3)가
    같은 순서를 쓰도록 하는 단일 원천."""
    rows = []
    for ko, en, cat, key in _ASSETS[:12]:
        vs = _hist(d, cat, key, days=6)
        if len(vs) >= 2 and vs[0]:
            rows.append((ko, en, key, (vs[-1] / vs[0] - 1) * 100))
    rows.sort(key=lambda r: r[3])
    return rows


def weekly(d, now):
    """카드 C — 주간 수익률 정렬 바. 실패 시 None."""
    try:
        plt, _ = _setup()
        rows = [(_L(ko, en), chg) for ko, en, key, chg in weekly_rows(d)]
        if not rows:
            return None
        fig = plt.figure(figsize=(10, 6.4), dpi=130)
        fig.patch.set_facecolor(BG)
        wk0 = now - datetime.timedelta(days=now.weekday())
        fig.text(0.03, 0.945,
                 _L(f"주간 리포트 — {wk0.month}/{wk0.day}~{now.month}/{now.day} 수익률",
                    f"Weekly — {wk0.month}/{wk0.day}~{now.month}/{now.day} returns"),
                 color=INK, fontsize=18, fontweight="bold")
        ax = fig.add_axes([0.16, 0.11, 0.78, 0.78])
        ax.set_facecolor(BG)
        ax.barh(range(len(rows)), [r[1] for r in rows], height=0.55,
                color=[UP if r[1] > 0 else DN for r in rows])
        ax.axvline(0, color=FAINT, lw=1)
        for i, (l, c) in enumerate(rows):
            ax.text(c + (0.08 if c >= 0 else -0.08), i, f"{'+' if c >= 0 else ''}{c:.2f}%",
                    va="center", ha="left" if c >= 0 else "right", color=INK, fontsize=12.5)
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([r[0] for r in rows], color=MUT, fontsize=13)
        lim = max(abs(r[1]) for r in rows) * 1.35 + 0.2
        ax.set_xlim(-lim, lim)
        ax.set_xticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0)
        _footer(fig, now)
        return _save(fig, "discord_card_weekly.png")
    except Exception as e:
        print(f"::warning title=디스코드 카드 실패::weekly: {e} — 기존 형식 폴백")
        return None


def swing(name, price, pct, thr_pct, xs, ys, prev, now, resume=""):
    """카드 D — 급변·서킷. 히어로 등락률 + 인트라데이 임계선.
    xs/ys/prev = send_kakao_digest._yahoo_intraday 반환값(비어 있으면 히어로만).
    실패 시 None(호출측이 텍스트 그대로 발송)."""
    try:
        if pct is None:
            return None
        plt, _ = _setup()
        col = UP if pct > 0 else DN
        fig = plt.figure(figsize=(10, 5.0), dpi=130)
        fig.patch.set_facecolor(BG)
        fig.text(0.03, 0.93,
                 _L(f"{now.month}/{now.day} {now.strftime('%H:%M')} 시장 급변 — {name}",
                    f"{now.month}/{now.day} {now.strftime('%H:%M')} Market Swing — {name}"),
                 color=INK, fontsize=18, fontweight="bold")
        fig.text(0.03, 0.60, f"{pct:+.2f}%", color=col, fontsize=54, fontweight="bold")
        if price is not None and prev:
            diff = price - prev
            fig.text(0.03, 0.47, f"{_fmt(price)}  {'▲' if diff >= 0 else '▼'}{abs(diff):,.1f}",
                     color=INK, fontsize=17)
        sub = _L(f"임계 ±{abs(thr_pct):.1f}% {'상향' if pct > 0 else '하향'} 돌파",
                 f"threshold ±{abs(thr_pct):.1f}% crossed")
        if resume:
            sub += " · " + resume
        fig.text(0.03, 0.36, sub, color=MUT, fontsize=13)
        if ys and len(ys) >= 3:
            ax = fig.add_axes([0.42, 0.14, 0.55, 0.66])
            ax.set_facecolor(BG)
            ax.plot(range(len(ys)), ys, color=LINE, lw=1.8)
            if prev:
                thr_v = prev * (1 + (abs(thr_pct) if pct > 0 else -abs(thr_pct)) / 100.0)
                ax.axhline(thr_v, color=col, lw=1.2, ls="--")
                ax.text(len(ys) - 1, thr_v,
                        f"{'-' if pct < 0 else '+'}{abs(thr_pct):.1f}% ",
                        color=col, fontsize=11.5, ha="right",
                        va="bottom" if pct < 0 else "top")
                crossed = [i for i, v in enumerate(ys)
                           if (v <= thr_v if pct < 0 else v >= thr_v)]
                if crossed:
                    ax.plot(crossed[0], ys[crossed[0]], "o", color=col, ms=7)
            ticks = sorted({0, len(ys) // 3, 2 * len(ys) // 3, len(ys) - 1})
            ax.set_xticks(ticks)
            ax.set_xticklabels([xs[t].strftime("%H:%M") if xs else "" for t in ticks],
                               color=FAINT, fontsize=11)
            ax.set_yticks([])
            for s in ax.spines.values():
                s.set_visible(False)
            ax.tick_params(length=0, colors=FAINT)
        _footer(fig, now)
        return _save(fig, "discord_card_swing.png")
    except Exception as e:
        print(f"::warning title=디스코드 카드 실패::swing: {e} — 기존 형식 폴백")
        return None
