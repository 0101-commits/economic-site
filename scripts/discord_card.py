#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""디스코드 전용 '시각 보드' 카드 렌더러 (기획 2026-08-11, 아티팩트 e9144cf7).

카드 4종 — 전부 embed 이미지 1장이 본문이 되는 형식(카카오는 무변경):
  board()        카드 A: 정기 다이제스트 — 히트맵 타일 12 + 미국채 캡션 + 30일 스파크라인 4
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
        # KO_FONT_PATH(기획 5154773b P1) — stock-alerts.yml 이 actions/cache 로 받아둔
        # 한글 폰트를 직접 등록(매분 런에 apt 설치 비용 없이 한글 카드). 파일 또는
        # 디렉터리(내부 .otf/.ttf 전부 — Regular+Bold 정적 2종. 가변폰트 NotoSansKR[wght]는
        # matplotlib 이 weight 100 으로 추락해 부적합 — 2026-08-20 실측). 실패 시 종전 강등.
        fp = os.path.expanduser(os.environ.get("KO_FONT_PATH", "").strip())
        if fp and os.path.exists(fp):
            try:
                files = ([os.path.join(fp, n) for n in sorted(os.listdir(fp))
                          if n.lower().endswith((".otf", ".ttf"))]
                         if os.path.isdir(fp) else [fp])
                fname = None
                for f1 in files:
                    font_manager.fontManager.addfont(f1)
                    fname = font_manager.FontProperties(fname=f1).get_name()
                if fname:
                    avail.add(fname)
                    _KO_FONTS.insert(0, fname)
            except Exception as e:
                print(f"[card] KO_FONT_PATH 등록 실패({e}) — 시스템 폰트 탐지로 폴백")
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


def _us_yield_line(d):
    """카드 A 하단 캡션 — 미국채 1·5·10·30Y 레벨% + 전일 대비 bp.
    출처 = data.yieldCurve.us.series(FRED DGS*). 데이터 없으면 ""(캡션 생략)."""
    try:
        series = ((d.get("yieldCurve") or {}).get("us") or {}).get("series") or []
        by = {s.get("tenor"): (s.get("data") or []) for s in series}
        parts = []
        for t in ("1Y", "5Y", "10Y", "30Y"):
            dt = by.get(t) or []
            last = _f((dt[-1] or {}).get("value")) if dt else None
            if last is None:
                continue
            prev = _f((dt[-2] or {}).get("value")) if len(dt) > 1 else None
            bp = ""
            if prev is not None:
                b = round((last - prev) * 100)
                bp = f" {'▲' if b > 0 else '▼' if b < 0 else '■'}{abs(b)}bp"
            parts.append(f"{t} {last:.2f}%{bp}")
        return (_L("미국채  ", "UST  ") + "  ·  ".join(parts)) if parts else ""
    except Exception:
        return ""


# (한글, 영문, 카테고리, 키) — 카드 A 타일 12(앞 12개) · 카드 C 상위 12 재사용
# 뒤 4종(밀·옥수수·은·브렌트)은 카드 미표시 — 드롭다운(_dc_select)용으로만 유지.
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
    모바일 가독성 확보. 하단 캡션 = 미국채 1·5·10·30Y(_us_yield_line)."""
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
        # 하단 캡션 — 미국채 1·5·10·30Y(사용자 지정 2026-08-20, 구 원자재 4종 대체).
        # 밀·옥수수·은·브렌트는 카드에서 제외(은·브렌트는 드롭다운으로 접근 가능).
        rest = _us_yield_line(d)
        if rest:
            fig.text(0.03, 0.395, rest, color=MUT, fontsize=12)
        fig.text(0.03, 0.335, _L("추세 30일", "30-day trend"), color=MUT, fontsize=12)
        sparks = [_ASSETS[0], _ASSETS[2], _ASSETS[6], _ASSETS[8]]  # 코스피·S&P·달러원·금
        for i, (ko, en, cat, key) in enumerate(sparks):
            ax = fig.add_axes([0.03 + i * 0.2425, 0.075, 0.205, 0.235])
            ax.set_facecolor(TILE)
            vs = _hist(d, cat, key)
            if vs:
                # 상·하단 여백 확보 — 라인·끝점이 라벨(상단)·현재가(하단) 글자 밴드에
                # 못 들어가게 y 범위를 넓힌다(글자 겹침 방지, 사용자 지적 2026-08-20).
                lo, hi = min(vs), max(vs)
                rng = (hi - lo) or (abs(hi) * 0.01) or 1.0
                ax.set_ylim(lo - 0.50 * rng, hi + 0.60 * rng)
                pad_x = max(1.0, (len(vs) - 1) * 0.04)
                ax.set_xlim(-pad_x, (len(vs) - 1) + pad_x)
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


def stock_alert(hero, others, now):
    """카드 E — 종목 알림(기획 5154773b P1). 좌 히어로(조건·현재가·등락·거래량) +
    우 30일 일봉 + 목표선(점선) + 발동점 도트, 하단 = 나머지 종목 1줄씩.

    hero = {name, cond, price, pct, target(없으면 None), closes(일봉 종가 리스트),
            vol_today, vol_prev, market}, others = [문자열 줄]. 재료는 전부
    check_alerts.yahoo_snapshot 반환값 — 추가 API 호출 없음. 실패 시 None(텍스트 폴백)."""
    try:
        if not hero or hero.get("price") is None:
            return None
        plt, _ = _setup()
        extra = min(len(others or []), 4)
        hgt = 4.2 + 0.42 * extra
        fig = plt.figure(figsize=(10, hgt), dpi=160)
        fig.patch.set_facecolor(BG)
        pct = _f(hero.get("pct"))
        col = UP if (pct or 0) > 0 else DN if (pct or 0) < 0 else MUT
        base_y = 1 - 0.55 / hgt                       # 제목 줄(높이 가변 보정)
        fig.text(0.03, base_y, _L(f"{now.month}/{now.day} {now.strftime('%H:%M')} 종목 알림",
                                  f"{now.month}/{now.day} {now.strftime('%H:%M')} Stock Alert"),
                 color=INK, fontsize=18, fontweight="bold")
        # 좌 히어로 — 조건 문구·현재가·등락·거래량(전일比)
        body_top = base_y - 0.14 * (4.2 / hgt)
        fig.text(0.03, body_top, str(hero.get("cond") or hero.get("name") or "")[:46],
                 color=MUT, fontsize=13)
        mkt = hero.get("market", "KR")
        ptxt = f"{hero['price']:,.2f}" if mkt == "US" else f"{hero['price']:,.0f}"
        fig.text(0.03, body_top - 0.30 * (4.2 / hgt), ptxt, color=col,
                 fontsize=30, fontweight="bold")
        sub = _chgtxt(pct)
        tgt = _f(hero.get("target"))
        if tgt and hero["price"]:
            sub += _L(f" · 목표 대비 {(hero['price'] / tgt - 1) * 100:+.1f}%",
                      f" · vs target {(hero['price'] / tgt - 1) * 100:+.1f}%")
        fig.text(0.03, body_top - 0.42 * (4.2 / hgt), sub, color=col, fontsize=14, fontweight="bold")
        vt, vp = _f(hero.get("vol_today")), _f(hero.get("vol_prev"))
        if vt:
            vs = _L(f"거래량 {vt:,.0f}", f"vol {vt:,.0f}")
            if vp:
                vs += _L(f" (전일比 {(vt / vp - 1) * 100:+.0f}%)", f" ({(vt / vp - 1) * 100:+.0f}% d/d)")
            fig.text(0.03, body_top - 0.54 * (4.2 / hgt), vs, color=MUT, fontsize=12)
        # 우 30일 일봉 + 목표선 + 발동점
        closes = [c for c in (hero.get("closes") or [])[-30:] if c is not None]
        ax_bot = (0.42 * extra + 0.85) / hgt
        ax = fig.add_axes([0.44, ax_bot, 0.53, max(0.30, 0.94 - ax_bot - 0.55 / hgt)])
        ax.set_facecolor(TILE)
        if len(closes) >= 2:
            lo, hi = min(closes + ([tgt] if tgt else [])), max(closes + ([tgt] if tgt else []))
            rng = (hi - lo) or (abs(hi) * 0.01) or 1.0
            ax.set_ylim(lo - 0.30 * rng, hi + 0.35 * rng)
            ax.set_xlim(-1, len(closes) + max(1, len(closes) * 0.03))
            ax.plot(closes, color=LINE, lw=1.7)
            if tgt:
                ax.axhline(tgt, color=col, lw=1.2, ls="--")
                ax.text(0.02, tgt, _L(f"목표 {tgt:,.0f} ", f"target {tgt:,.0f} "),
                        color=col, fontsize=10.5, va="bottom")
            ax.plot(len(closes) - 1, closes[-1], "o", color=col, ms=6)
            ax.text(0.02, 0.94, _L("30일 일봉", "30-day daily"), transform=ax.transAxes,
                    color=MUT, fontsize=11, va="top")
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        # 하단 — 동시 발동 나머지 종목
        for i, ln in enumerate((others or [])[:4]):
            fig.text(0.03, (0.42 * (extra - i) + 0.42) / hgt, "· " + str(ln)[:80],
                     color=INK, fontsize=12.5)
        _footer(fig, now)
        return _save(fig, "discord_card_stock.png")
    except Exception as e:
        print(f"::warning title=디스코드 카드 실패::stock_alert: {e} — 텍스트 폴백")
        return None


def close_report(items, now, alerts_cnt=None, cal="", intraday=None, investor=None,
                 movers=None, fired_names=None):
    """카드 B — 장 마감 4분면(기획 5154773b P2). 실패 시 None.

    좌상 = 다이버징 바(items=[(라벨, 가격, 등락%)]) / 우상 = 코스피 인트라데이
    (intraday=(xs, ys, prev, 폴백라벨) — _intraday_chain) / 좌하 = 투자자 순매수 3주체
    (investor={foreign, inst, retail, date} 억원) / 우하 = 특징주 top3
    (movers=(gainers, losers) — [{name, chg}]) + 발동 알림 종목명(fired_names) + 내일 일정.
    새 재료가 None 인 분면은 생략 — 결측일에도 카드 전체는 살아 있다."""
    try:
        plt, _ = _setup()
        its = [(l, p, c if c is not None else 0.0) for l, p, c in items if p is not None][::-1]
        if not its:
            return None
        fig = plt.figure(figsize=(10, 7.4), dpi=160)
        fig.patch.set_facecolor(BG)
        fig.text(0.03, 0.955, _L(f"{now.month}/{now.day} 장 마감 리포트",
                                 f"{now.month}/{now.day} Market Close"),
                 color=INK, fontsize=18, fontweight="bold")
        # ── 좌상: 다이버징 바(종전 유지·축소 배치)
        ax = fig.add_axes([0.115, 0.545, 0.40, 0.345])
        ax.set_facecolor(BG)
        chgs = [c for _, _, c in its]
        ax.barh(range(len(its)), chgs, height=0.55,
                color=[UP if c > 0 else DN if c < 0 else FAINT for c in chgs])
        ax.axvline(0, color=FAINT, lw=1)
        for i, (l, p, c) in enumerate(its):
            ax.text(c + (0.06 if c >= 0 else -0.06), i, f"{_fmt(p)} {_chgtxt(c)}",
                    va="center", ha="left" if c >= 0 else "right", color=INK, fontsize=11.5)
        ax.set_yticks(range(len(its)))
        ax.set_yticklabels([l for l, _, _ in its], color=MUT, fontsize=12)
        lim = max(abs(c) for c in chgs) * 2.1 + 0.3
        ax.set_xlim(-lim, lim)
        ax.set_xticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0)
        # ── 우상: 코스피 인트라데이(소스 체인 — 빈 패널 금지)
        xs, ys, prev, src = intraday or ([], [], None, "")
        if ys and len(ys) >= 3:
            ax2 = fig.add_axes([0.60, 0.545, 0.37, 0.345])
            ax2.set_facecolor(TILE)
            lo, hi = min(ys + ([prev] if prev else [])), max(ys + ([prev] if prev else []))
            rng = (hi - lo) or (abs(hi) * 0.01) or 1.0
            ax2.set_ylim(lo - 0.25 * rng, hi + 0.35 * rng)
            ax2.plot(range(len(ys)), ys, color=LINE, lw=1.6)
            if prev:
                ax2.axhline(prev, color=FAINT, lw=1.0, ls="--")
            dirc = UP if (prev and ys[-1] >= prev) or (not prev and ys[-1] >= ys[0]) else DN
            ax2.plot(len(ys) - 1, ys[-1], "o", color=dirc, ms=5)
            lab = _L("코스피 오늘", "KOSPI today") + (f" · {src}" if src else "")
            ax2.text(0.03, 0.93, lab, transform=ax2.transAxes, color=MUT, fontsize=11.5, va="top")
            if prev:
                ax2.text(0.97, 0.93, f"{(ys[-1] / prev - 1) * 100:+.2f}%", transform=ax2.transAxes,
                         color=dirc, fontsize=12.5, ha="right", va="top", fontweight="bold")
            ax2.set_xticks([]); ax2.set_yticks([])
            for s in ax2.spines.values():
                s.set_visible(False)
        # ── 좌하: 투자자 순매수 3주체(코스피, 억원)
        inv = investor or {}
        vals = [(_L("외국인", "foreign"), _f(inv.get("foreign"))),
                (_L("기관", "inst"), _f(inv.get("inst"))),
                (_L("개인", "retail"), _f(inv.get("retail")))]
        vals = [(l, v) for l, v in vals if v is not None]
        if vals:
            ax3 = fig.add_axes([0.115, 0.135, 0.34, 0.28])
            ax3.set_facecolor(BG)
            ax3.barh(range(len(vals)), [v for _, v in vals], height=0.5,
                     color=[UP if v > 0 else DN for _, v in vals])
            ax3.axvline(0, color=FAINT, lw=1)
            for i, (l, v) in enumerate(vals):
                ax3.text(v + (abs(v) * 0.06 + 1) * (1 if v >= 0 else -1), i,
                         f"{v:+,.0f}", va="center", ha="left" if v >= 0 else "right",
                         color=INK, fontsize=11.5)
            ax3.set_yticks(range(len(vals)))
            ax3.set_yticklabels([l for l, _ in vals], color=MUT, fontsize=12)
            vlim = max(abs(v) for _, v in vals) * 1.9 + 1
            ax3.set_xlim(-vlim, vlim)
            ax3.set_xticks([])
            for s in ax3.spines.values():
                s.set_visible(False)
            ax3.tick_params(length=0)
            fig.text(0.115, 0.435, _L("투자자 순매수(코스피, 억원)", "net buy (KOSPI, 0.1bn KRW)")
                     + (f" · {inv.get('date')}" if inv.get("date") else ""),
                     color=MUT, fontsize=12)
        # ── 우하: 특징주 top3 + 오늘 발동 알림 + 내일 일정
        ty = 0.435
        gain, lose = (movers or ([], []))
        if gain or lose:
            fig.text(0.56, ty, _L("특징주(코스피)", "KOSPI movers"), color=MUT, fontsize=12)
            ty -= 0.045
            for r in (gain or [])[:3]:
                fig.text(0.56, ty, f"▲ {str(r.get('name'))[:10]} {abs(_f(r.get('chg')) or 0):.1f}%",
                         color=UP, fontsize=12)
                ty -= 0.042
            for r in (lose or [])[:3]:
                fig.text(0.56, ty, f"▼ {str(r.get('name'))[:10]} {abs(_f(r.get('chg')) or 0):.1f}%",
                         color=DN, fontsize=12)
                ty -= 0.042
            ty -= 0.015
        if alerts_cnt is not None:
            head = _L(f"오늘 발동 알림 {alerts_cnt}건", f"alerts fired today: {alerts_cnt}")
            fig.text(0.56, ty, head, color=MUT, fontsize=12)
            ty -= 0.045
            if fired_names:
                fig.text(0.56, ty, " · ".join(fired_names[:6])[:52], color=INK, fontsize=12)
                ty -= 0.05
        if cal:
            fig.text(0.56, ty, _L("내일 ", "tomorrow ") + cal, color=INK, fontsize=12)
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


def _week_flow_line(d):
    """주간 수급 합계 캡션(기획 5154773b P3) — investorTrading.daily 최근 5영업일
    외국인·기관 순매수 합(억원). 결측이면 ""."""
    try:
        daily = ((d.get("investorTrading") or {}).get("daily") or [])[-5:]
        if not daily:
            return ""
        fo = sum(_f(r.get("foreign")) or 0 for r in daily)
        it = sum(_f(r.get("inst")) or 0 for r in daily)
        return _L(f"주간 수급(코스피 5일): 외국인 {fo:+,.0f}억 · 기관 {it:+,.0f}억",
                  f"weekly net buy (KOSPI 5d): foreign {fo:+,.0f} · inst {it:+,.0f} (0.1bn KRW)")
    except Exception:
        return ""


def weekly(d, now, next_week=""):
    """카드 C — 주간 수익률 정렬 바 + 주간 경로 스파크(기획 5154773b P3). 실패 시 None.

    스파크(각 자산 6일 종가)는 같은 -2%라도 '내내 하락'과 '금요일 급락'을 구분한다.
    하단 캡션 = 주간 수급 합계 + 다음 주 일정(next_week — build_weekly_parts 의 '다음주' 블록)."""
    try:
        plt, _ = _setup()
        cat_of = {key: cat for ko, en, cat, key in _ASSETS}
        rows = [(_L(ko, en), key, chg) for ko, en, key, chg in weekly_rows(d)]
        if not rows:
            return None
        fig = plt.figure(figsize=(10, 6.8), dpi=160)
        fig.patch.set_facecolor(BG)
        wk0 = now - datetime.timedelta(days=now.weekday())
        fig.text(0.03, 0.945,
                 _L(f"주간 리포트 — {wk0.month}/{wk0.day}~{now.month}/{now.day} 수익률",
                    f"Weekly — {wk0.month}/{wk0.day}~{now.month}/{now.day} returns"),
                 color=INK, fontsize=18, fontweight="bold")
        ax = fig.add_axes([0.16, 0.185, 0.58, 0.70])
        ax.set_facecolor(BG)
        ax.barh(range(len(rows)), [r[2] for r in rows], height=0.55,
                color=[UP if r[2] > 0 else DN for r in rows])
        ax.axvline(0, color=FAINT, lw=1)
        for i, (l, k, c) in enumerate(rows):
            ax.text(c + (0.08 if c >= 0 else -0.08), i, f"{'+' if c >= 0 else ''}{c:.2f}%",
                    va="center", ha="left" if c >= 0 else "right", color=INK, fontsize=12.5)
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([r[0] for r in rows], color=MUT, fontsize=13)
        lim = max(abs(r[2]) for r in rows) * 1.55 + 0.2   # 값 글자 확대분 여유(클리핑 방지)
        ax.set_xlim(-lim, lim)
        ax.set_xticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0)
        # 우측 스파크 열 — 바와 같은 행 순서, 각 행 밴드에 6일 종가 정규화 라인.
        axs = fig.add_axes([0.78, 0.185, 0.19, 0.70])
        axs.set_facecolor(BG)
        axs.set_xlim(0, 1)
        axs.set_ylim(-0.5, len(rows) - 0.5)
        for i, (l, k, c) in enumerate(rows):
            vs = _hist(d, cat_of.get(k, ""), k, days=6)
            if len(vs) < 2:
                continue
            lo, hi = min(vs), max(vs)
            rng = (hi - lo) or (abs(hi) * 0.001) or 1.0
            n = len(vs)
            xs_ = [0.06 + 0.88 * j / (n - 1) for j in range(n)]
            ys_ = [i - 0.30 + 0.60 * (v - lo) / rng for v in vs]
            axs.plot(xs_, ys_, color=FAINT, lw=1.3)
            axs.plot(xs_[-1], ys_[-1], "o", color=UP if c > 0 else DN, ms=3.5)
        axs.text(0.5, len(rows) - 0.15, _L("주간 경로", "weekly path"), color=MUT,
                 fontsize=11, ha="center", va="bottom")
        axs.set_xticks([]); axs.set_yticks([])
        for s in axs.spines.values():
            s.set_visible(False)
        # 하단 캡션 — 주간 수급 합계 + 다음 주 일정
        flow = _week_flow_line(d)
        if flow:
            fig.text(0.03, 0.115, flow, color=MUT, fontsize=12)
        if next_week:
            fig.text(0.03, 0.068, _L("다음 주  ", "next week  ") + str(next_week)[:70],
                     color=MUT, fontsize=12)
        _footer(fig, now)
        return _save(fig, "discord_card_weekly.png")
    except Exception as e:
        print(f"::warning title=디스코드 카드 실패::weekly: {e} — 기존 형식 폴백")
        return None


def swing(name, price, pct, thr_pct, xs, ys, prev, now, resume="", src=""):
    """카드 D — 급변·서킷. 히어로 등락률 + 인트라데이(또는 일봉 폴백) 임계선.
    xs/ys/prev = send_kakao_digest._intraday_chain 반환값(비어 있으면 히어로만 — 최후).
    src = 폴백 라벨('일봉 7D' 등, 기획 5154773b P0) — 패널에 표기해 인트라데이 오독 방지.
    x축 눈금은 구간 폭으로 자동(하루 안=HH:MM, 여러 날=M/D). 실패 시 None."""
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
            xfmt = "%H:%M"
            if xs and (xs[-1] - xs[0]).days >= 2:     # 일봉 폴백 — 날짜 눈금
                xfmt = "%m/%d"
            ax.set_xticklabels([xs[t].strftime(xfmt) if xs else "" for t in ticks],
                               color=FAINT, fontsize=11)
            if src:                                   # 폴백 출처 라벨(P0)
                ax.text(0.02, 1.02, src, transform=ax.transAxes, color=FAINT, fontsize=10)
            ax.set_yticks([])
            for s in ax.spines.values():
                s.set_visible(False)
            ax.tick_params(length=0, colors=FAINT)
        _footer(fig, now)
        return _save(fig, "discord_card_swing.png")
    except Exception as e:
        print(f"::warning title=디스코드 카드 실패::swing: {e} — 기존 형식 폴백")
        return None
