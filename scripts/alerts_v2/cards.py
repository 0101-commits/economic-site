"""카톡 카드 — 사건 카드 · 묶음 카드(기획서 5장). 1080×1080, discord_card 정사각 골격 재사용.

deliver.py 가 `event_card_png(row, ctx)` · `bundle_card_png(rows, ctx)` 로 부른다. 실패하면 **예외**를 던진다 —
deliver 가 잡아 텍스트로 내려간다(조용한 None 으로 빈 카드가 나가지 않게). 한글 폰트가 없을 때도 마찬가지다
(행 글자가 한국어라 영문 강등이 안 되고, 두부(□) 카드를 보내느니 텍스트가 낫다).

판독 규격(CLAUDE.md): 카톡은 카드를 약 270px 로 줄여 보인다 → 모든 글자는 discord_card.SQ_MIN_FS(13pt) 이상,
긴 글은 글자수가 아니라 렌더 폭으로 자른다(_clip). 색은 등락색 2(UP · DN) + 검정 + 회색뿐, 이모지 없음.
"""
from __future__ import annotations

import datetime as dt
import io
import os
import sys

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import discord_card as dc  # noqa: E402

LEVEL_KO = {"alarm": "경보", "alert": "알림", "notice": "안내", "record": "기록"}
FRESH_KO = {"live": "지금", "prev": "전일", "stale": "묵음", "kept": "이전 값", "missing": "없음"}
UP_DIRS, DOWN_DIRS = ("up", "buy"), ("down", "sell")
FS_TITLE, FS_PILL = 22, 15
FS_WHY, FS_LABEL = 23, 16
TOP_Y = 0.955                      # _head 의 제목 기준선
CHART_BOX = [0.03, 0.285, 0.94, 0.26]
BUNDLE_MAX = 6


def _plt():
    plt, ko = dc._setup()
    if not ko:
        raise RuntimeError("한글 폰트 없음 — 카드 대신 텍스트로 보낸다")
    return plt


def _new(plt):
    fig = plt.figure(figsize=dc.SQ, dpi=dc.SQ_DPI)
    fig.patch.set_facecolor(dc.BG)
    return fig


def _png(fig) -> bytes:
    try:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=dc.BG)
        return buf.getvalue()
    finally:
        dc._STATE["plt"].close(fig)


def _hhmm(ts) -> str:
    try:
        return dt.datetime.fromisoformat(str(ts)).strftime("%H:%M")
    except ValueError:
        return ""


def _md(as_of) -> str:
    s = str(as_of or "")
    try:
        d = dt.date.fromisoformat(s[:10])
        return f"{d.month}/{d.day}"
    except ValueError:
        return s


def _value_text(row: dict) -> str:
    v = row.get("value")
    if isinstance(v, str) and v:
        return v                                         # 글자 그대로
    if v is not None and v != "":
        from .compose import fmt_num                     # 숫자는 문구 틀과 같은 한 벌 표기(−2,040억)
        return fmt_num(v, row.get("unit") or "")
    tail = str(row["title"]).split(" · ", 1)
    return tail[1] if len(tail) > 1 else "—"


def _dir_color(d) -> str:
    return dc.UP if d in UP_DIRS else dc.DN if d in DOWN_DIRS else dc.INK


def _pill(fig, level: str, x: float) -> None:
    """등급 알약 — 경보만 검정 채움 흰 글자, 알림 · 안내 · 기록은 테두리."""
    from matplotlib.patches import FancyBboxPatch
    label = LEVEL_KO.get(level, str(level))
    fs = dc._fs(FS_PILL, True)
    w, h, cy = dc._text_w(fig, label, fs, "bold") + 0.036, 0.044, TOP_Y + 0.0145
    solid = level == "alarm"
    fig.patches.append(FancyBboxPatch(
        (x, cy - h / 2), w, h, boxstyle="round,pad=0,rounding_size=0.012", transform=fig.transFigure,
        fc=dc.INK if solid else dc.BG, ec=dc.INK, lw=1.6))
    fig.text(x + w / 2, cy, label, color=dc.BG if solid else dc.INK, fontsize=fs, fontweight="bold",
             ha="center", va="center")


def _big(fig, text: str, color: str) -> None:
    """큰 숫자 하나 — 폭이 모자라면 글자를 줄이고, 그래도 안 들어가면 렌더 폭으로 자른다."""
    fs = 80.0
    while dc._text_w(fig, text, fs, "bold") > 0.94 and fs > 40:
        fs *= 0.92
    fig.text(0.03, 0.79, dc._clip(fig, text, 0.94, fs, "bold"), color=color, fontsize=fs, fontweight="bold")


def _line(fig, label: str, text: str, y: float) -> None:
    """「왜」 · 「다음」 한 줄 — 왼쪽에 작은 이름표, 오른쪽에 본문."""
    if not text:
        return
    fig.text(0.03, y, label, color=dc.MUT, fontsize=dc._fs(FS_LABEL, True), fontweight="bold")
    fs = dc._fs(FS_WHY, True)
    fig.text(0.13, y, dc._clip(fig, text, 0.97 - 0.13, fs), color=dc.INK, fontsize=fs)


def _chart(row: dict, ctx):
    """(xs, ys) 7점. 3점 미만이면 (None, []) — 차트 자리는 칸 3 이 쓴다."""
    fn = getattr(ctx, "series", None)
    pts = [p for p in (fn(row["target"], 7) if fn and row.get("target") else []) if p.get("close") is not None][-7:]
    ys = [float(p["close"]) for p in pts]
    if len(ys) < 3:
        return None, []
    try:
        xs = [dt.datetime.fromisoformat(str(p["date"])) for p in pts]
    except (KeyError, ValueError):
        xs = None
    return xs, ys


def _source(row: dict, ctx) -> str:
    reg = getattr(ctx, "registry", None) or {}
    rid = getattr(ctx, "rid", None) or (lambda t: t)
    return str((reg.get(rid(row.get("target"))) or {}).get("source") or "")


def _guarded(draw, *args):
    """그리다 실패하면 그림을 닫고 예외를 다시 던진다(런 하나에 수십 장 — 열린 채 쌓이지 않게)."""
    plt = _plt()
    fig = _new(plt)
    try:
        draw(plt, fig, *args)
    except BaseException:
        plt.close(fig)
        raise
    return fig


def _event_fig(row: dict, ctx):
    return _guarded(_draw_event, row, ctx)


def _bundle_fig(rows: list[dict], ctx):
    return _guarded(_draw_bundle, list(rows), ctx)


# 숫자가 주인공이 아닌 사건 — 카드 대신 사진 없는 피드로 보낸다(deliver.photo_worthy). 큰 숫자 자리에 「3」(휴장 일수) ·
# 「1」(새 글 수) · 「잠정실적」 같은 글자가 박히던 카드였다(2026-10-11 사용자: 「그림과 텍스트가 중복」).
TEXT_EVENTS = {"D5", "E1", "E5", "F1", "F2", "F3", "G1", "G2", "G3", "G5", "H2", "H4"}   # D5 = 종목 수급(주 수)
FLOW_FAMILY = "D"


def photo_worthy(row: dict) -> bool:
    """카드(사진)를 그릴 사건인가 — 값이 숫자이고 글자 사건이 아니면."""
    v = row.get("value")
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and str(row.get("event") or "") not in TEXT_EVENTS)


def _event_name(row: dict) -> str:
    try:
        from . import schema
        return str(schema.by_id(schema.load_events()).get(row.get("event"), {}).get("name") or row.get("event") or "")
    except Exception:                                        # noqa: BLE001
        return str(row.get("event") or "")


def _subject(row: dict, ctx) -> str:
    """카드 둘째 줄 = 무엇(대상). 수급 사건은 대상 id 가 시장(kospi)이라 「코스피 외국인」."""
    if str(row.get("event") or "").startswith(FLOW_FAMILY):
        return "코스피 외국인" if row.get("target") in ("kospi", None, "") else str(row.get("target"))
    reg = getattr(ctx, "registry", None) or {}
    rid = getattr(ctx, "rid", None) or (lambda t: t)
    r = reg.get(rid(row.get("target"))) or {}
    return str(r.get("short") or r.get("label") or str(row.get("title") or "").split(" · ")[0])


def _big_text(row: dict, ctx) -> str:
    from .compose import fmt_num
    reg = getattr(ctx, "registry", None) or {}
    rid = getattr(ctx, "rid", None) or (lambda t: t)
    r = reg.get(rid(row.get("target"))) or {}
    unit = row.get("unit") or r.get("unit") or ""
    s = fmt_num(row.get("value"), unit, None if unit == "억" else r.get("decimals"))
    if unit == "억" and isinstance(row.get("value"), (int, float)) and row["value"] > 0:
        s = "+" + s
    return s.replace("−", "-")                               # 카드 글꼴에 U+2212 가 없을 수 있다


def _chg_text(row: dict) -> str:
    c = row.get("chg")
    if not isinstance(c, (int, float)) or str(row.get("event") or "").startswith(FLOW_FAMILY):
        return ""
    return f"{'▲' if c > 0 else '▼' if c < 0 else '■'}{abs(c):.2f}%"


def _flow_series(ctx, as_of=None) -> list[tuple]:
    """수급 사건의 작은 막대 — 사건 기준일까지 외국인 7영업일(판정과 같은 자료 규칙). 끝 막대 = 그 사건의 날."""
    try:
        from .judges_flow_cal import _flow
        end = dt.date.fromisoformat(str(as_of)[:10]) if as_of else None
        return [(d, v) for d, _r, v in _flow(ctx, "foreign") if end is None or d <= end][-7:]
    except Exception:                                        # noqa: BLE001
        return []


def _flow_bars(plt, fig, pts, box) -> None:
    from .compose import fmt_num
    ax = fig.add_axes(box)
    ax.set_facecolor(dc.TILE)
    vals = [v for _d, v in pts]
    ax.bar(range(len(vals)), vals, color=[dc.UP if v > 0 else dc.DN for v in vals], width=0.6)
    ax.axhline(0, color=dc.FAINT, lw=1.0)
    ax.set_xticks(range(len(pts)))
    ax.set_xticklabels([f"{d.month}/{d.day}" for d, _v in pts], color=dc.FAINT, fontsize=dc._fs(14, True))
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0)
    ax.text(0.012, 1.045, "최근 영업일 외국인 순매수(억)", transform=ax.transAxes, color=dc.MUT,
            fontsize=dc._fs(16, True), va="bottom")
    lo, hi = min(vals + [0]), max(vals + [0])
    pad = (hi - lo) * 0.18 or 1.0
    ax.set_ylim(lo - pad, hi + pad)
    ax.text(len(vals) - 1, vals[-1], fmt_num(vals[-1], "억").replace("−", "-"), color=dc.INK, fontweight="bold",
            fontsize=dc._fs(15, True), ha="center", va="bottom" if vals[-1] >= 0 else "top")


def _draw_event(plt, fig, row: dict, ctx) -> None:
    """사건 카드(기획서 5장) — 사전 이름 + 등급 + 시각 / 대상 / 큰 숫자 + 등락 / 작은 차트(임계 점선) / 칸 / 꼬리.
    「왜 · 다음」은 카드에 그리지 않는다 — 카톡은 카드를 약 270px 로 줄여 보이므로 문장은 카드 아래 글(본래 크기)이
    맡는다. 같은 줄이 그림과 글에 두 번 나오던 중복을 없앤다(2026-10-11)."""
    name = _event_name(row) or str(row["title"]).split(" · ")[0]
    stale = row.get("fresh") not in ("live", None, "")
    meta = " · ".join(x for x in (_hhmm(row.get("ts")), f"{_md(row.get('asOf'))} 기준" if stale else "") if x)
    dc._head(fig, name, meta, fs_t=FS_TITLE)
    shown = dc._clip(fig, name, 0.62, dc._fs(FS_TITLE, True), "bold")
    _pill(fig, row["level"], 0.03 + dc._text_w(fig, shown, dc._fs(FS_TITLE, True), "bold") + 0.015)
    fs_sub = dc._fs(26, True)
    fig.text(0.03, 0.855, dc._clip(fig, _subject(row, ctx), 0.94, fs_sub), color=dc.MUT, fontsize=fs_sub)
    color = _dir_color(row.get("dir"))
    big, chg = _big_text(row, ctx), _chg_text(row)
    fs = 80.0
    while dc._text_w(fig, big, fs, "bold") > (0.62 if chg else 0.94) and fs > 40:
        fs *= 0.92
    fig.text(0.03, 0.70, dc._clip(fig, big, 0.94, fs, "bold"), color=color, fontsize=fs, fontweight="bold")
    if chg:
        fc = dc._fs(34, True)
        fig.text(0.03 + dc._text_w(fig, big, fs, "bold") + 0.025, 0.70, chg, color=color, fontsize=fc, fontweight="bold")

    cells = []
    if isinstance(row.get("z"), (int, float)):
        cells.append(dc._cell("세기", f"{abs(row['z']):.1f}σ", "평소 변동의 배수"))
    if isinstance(row.get("line"), (int, float)):
        cells.append(dc._cell("선", dc._fmt(row["line"])))
    if stale:
        cells.append(dc._cell("기준", _md(row.get("asOf"))))
    top = 0.60                                       # 큰 숫자(기준선 0.70) 아래로 차트 제목이 붙지 않게
    box_h = (top - (0.23 if cells else 0.09)) - 0.06
    if str(row.get("event") or "").startswith(FLOW_FAMILY):
        pts = _flow_series(ctx, row.get("asOf"))
        if len(pts) >= 3:
            _flow_bars(plt, fig, pts, [0.03, top - box_h, 0.94, box_h])
    else:
        xs, ys = _chart(row, ctx)
        if ys:
            up = row.get("dir") in UP_DIRS or (row.get("dir") not in DOWN_DIRS and ys[-1] >= ys[0])
            lines = [(row["line"], color if color != dc.INK else dc.MUT, dc._fmt(row["line"]))]                 if isinstance(row.get("line"), (int, float)) else []
            dc._sq_panel(fig, [0.03, top - box_h, 0.94, box_h], ys, xs=xs, up=up, label=f"최근 {len(ys)}영업일",
                         lines=lines)
    if cells:
        dc._draw_cells(fig, [cells], (0.03, 0.065, 0.94, 0.15), (18, 26, 15), square=True)
    src = _source(row, ctx)
    fig.text(0.03, 0.022, " · ".join(x for x in (f"출처 {src}" if src else "", f"알림 사전 {row.get('event')}") if x),
             color=dc.FAINT, fontsize=dc._fs(13, True))


def _draw_bundle(plt, fig, rows: list[dict], ctx) -> None:
    if not rows:
        raise ValueError("묶음 카드: 행이 없다")
    dc._head(fig, f"알림 {len(rows)}건 더", _hhmm(max(str(r.get("ts") or "") for r in rows)), fs_t=FS_TITLE)
    fs, fl = dc._fs(24, True), dc._fs(FS_LABEL, True)
    for i, r in enumerate(rows[:BUNDLE_MAX]):
        y = 0.84 - i * 0.125
        fig.text(0.03, y, LEVEL_KO.get(r.get("level"), ""), color=dc.MUT, fontsize=fl, fontweight="bold")
        fig.text(0.14, y, dc._clip(fig, str(r["title"]), 0.97 - 0.14, fs), color=dc.INK, fontsize=fs)
        fig.add_artist(plt.Line2D([0.03, 0.97], [y - 0.034] * 2, transform=fig.transFigure, color=dc.FAINT,
                                  lw=0.8, alpha=0.35))
    if len(rows) > BUNDLE_MAX:
        fig.text(0.03, 0.095, f"+{len(rows) - BUNDLE_MAX}", color=dc.MUT, fontsize=dc._fs(26, True), fontweight="bold")
    fig.text(0.03, 0.022, "ecom · 받은 알림에서 전체 보기", color=dc.FAINT, fontsize=dc._fs(13, True))


# ---------- 브리핑 카드(기획서 5장 대화창 목업) ----------
# 아침 = 목록(미국 · 환율 · 금리 · 유가), 마감 = 칸 3 + 하루 흐름 + 수급 3주체, 주간 = 칸 4 + 행. 옛 시황 6칸 카드
# (send_kakao_digest._build_kakao_card)를 쓰던 자리다 — 2026-10-09 「브리핑 사진이 옛 시황 카드」.
BRIEF_US = ("sp500", "nasdaq", "usdkrw", "usdjpy", "us10y", "wti")
BRIEF_KR = ("kospi", "kosdaq", "usdkrw")
FS_ROW = (25, 32, 25)              # 목록 행 이름 · 값 · 등락
FS_INFO = (18, 22)                 # 정보 행 이름표 · 본문
Y_FLOOR = 0.07                     # 꼬리(0.022) 위로 남길 자리


def quote(ctx, target: str):
    """번들 띠(화면과 같은 값) → (이름, 값 글자, 등락 글자, 등락값, 기준일 date|None). 값이 없으면 None.
    금리(단위 %)의 등락은 bp, 나머지는 %."""
    from .compose import MINUS, fmt_num
    fn = getattr(ctx, "strip", None)
    s = fn(target) if fn else None
    if not s or s.get("value") is None:
        return None
    unit = s.get("unit") or ""
    val = fmt_num(s["value"], unit if unit in ("%", "$") else "", s.get("decimals"))
    if unit == "%":
        c = s.get("change")
        txt = "" if c is None else f"{'+' if c >= 0 else MINUS}{abs(c) * 100:.0f}bp"
    else:
        c = s.get("changePct")
        txt = "" if c is None else f"{'▲' if c > 0 else '▼' if c < 0 else '■'}{abs(c):.2f}%"
    try:
        day = dt.date.fromisoformat(str(s.get("asOf"))[:10])
    except ValueError:
        day = None
    return str(s.get("short") or s.get("label") or target), val, txt, c, day


def _chg_color(c) -> str:
    return dc.UP_TXT if (c or 0) > 0 else dc.DN_TXT if (c or 0) < 0 else dc.MUT


def _rows(fig, plt, rows, y: float) -> float:
    """목록 행 — 이름(+ 묵은 값이면 「· M/D」) · 값(오른쪽 맞춤) · 등락(색). 아래로 내려간 y 를 돌려준다."""
    h = min(0.10, (y - 0.30) / max(len(rows), 1))
    fn, fv, fc = (dc._fs(f, True) for f in FS_ROW)
    for name, val, txt, c, tag in rows:
        y -= h
        base = y + h * 0.32
        shown = dc._clip(fig, name, 0.40 - (0.09 if tag else 0), fn)
        fig.text(0.03, base, shown, color=dc.INK, fontsize=fn)
        if tag:                                                      # 묵은 값 — 이름 뒤 작은 「10/7」
            fig.text(0.03 + dc._text_w(fig, shown, fn) + 0.012, base, tag, color=dc.FAINT, fontsize=dc._fs(18, True))
        fig.text(0.73, base, dc._clip(fig, val, 0.29, fv, "bold"), color=dc.INK, fontsize=fv, fontweight="bold", ha="right")
        fig.text(0.97, base, txt, color=_chg_color(c), fontsize=fc, fontweight="bold", ha="right")
        fig.add_artist(plt.Line2D([0.03, 0.97], [y] * 2, transform=fig.transFigure, color=dc.FAINT, lw=0.8, alpha=0.35))
    return y


def _bars(fig, plt, bars, y: float) -> float:
    """수급 막대 — 가운데 0선, 순매수는 오른쪽(상승색) · 순매도는 왼쪽(하락색), 값은 오른쪽 끝."""
    from .compose import MINUS, fmt_num        # 카드 글꼴에 「−」(U+2212)가 없을 수 있어 막대 값은 ASCII
    m = max(abs(v) for _, v in bars) or 1.0
    fl, fv = dc._fs(20, True), dc._fs(22, True)
    cx, half, h = 0.46, 0.20, 0.056
    top = y
    for name, v in bars:
        y -= h
        fig.text(0.03, y + h * 0.3, name, color=dc.MUT, fontsize=fl)
        w = half * abs(v) / m
        fig.patches.append(plt.Rectangle((cx if v >= 0 else cx - w, y + h * 0.22), w, h * 0.5,
                                         transform=fig.transFigure, fc=dc.UP if v >= 0 else dc.DN, ec="none"))
        fig.text(0.97, y + h * 0.3, ("+" if v > 0 else "") + fmt_num(v, "억").replace(MINUS, "-"), color=_chg_color(v), fontsize=fv,
                 fontweight="bold", ha="right")
    fig.add_artist(plt.Line2D([cx, cx], [y + h * 0.1, top - h * 0.1], transform=fig.transFigure, color=dc.FAINT, lw=1.0))
    return y


def _info(fig, info, y: float) -> float:
    """정보 행(이름표 · 글) — 자리가 모자라면 뒤 행을 버린다(반쯤 잘린 행보다 낫다)."""
    fl, ft = (dc._fs(f, True) for f in FS_INFO)
    info = [(lab, txt) for lab, txt in info if txt]
    x = 0.03 + max((dc._text_w(fig, lab, fl, "bold") for lab, _ in info), default=0) + 0.025
    for lab, txt in info:
        if y - 0.062 < Y_FLOOR:
            break
        y -= 0.062
        fig.text(0.03, y, lab, color=dc.MUT, fontsize=fl, fontweight="bold")
        fig.text(x, y, dc._clip(fig, txt, 0.97 - x, ft), color=dc.INK, fontsize=ft)
    return y


def _draw_brief(plt, fig, spec: dict) -> None:
    """spec = {title, meta, tiles:[dc._cell], rows:[quote], chart:{ys, xs, prev, up, label, right},
    bars:[(이름, 억)], info:[(이름표, 글)], foot}. 위에서 아래로 쌓고 빠진 칸은 자리를 안 차지한다."""
    dc._head(fig, spec["title"], spec.get("meta", ""), fs_t=FS_TITLE)
    y = 0.915
    tiles = spec.get("tiles") or []
    if tiles:
        grid = [tiles[i:i + 2] for i in range(0, len(tiles), 2)] if len(tiles) == 4 else [tiles]
        h = (0.19 if len(grid) > 1 else 0.15) * len(grid)
        dc._draw_cells(fig, grid, (0.03, y - h, 0.94, h), (18, 30, 20), square=True, note_inline=True)
        y -= h + 0.015
    if spec.get("rows"):
        y = _rows(fig, plt, spec["rows"], y)
    bars = [(n, float(v)) for n, v in spec.get("bars") or [] if v is not None]
    ch = spec.get("chart") or {}
    if len([v for v in ch.get("ys") or [] if v is not None]) >= 3:
        h = 0.22 if bars else 0.33                                   # 수급이 없는 날은 차트가 그 자리를 쓴다
        y -= h + 0.05
        dc._sq_panel(fig, [0.03, y, 0.94, h], ch["ys"], xs=ch.get("xs"), prev=ch.get("prev"), up=ch.get("up", True),
                     label=ch.get("label", ""), right=ch.get("right", ""))
        y -= 0.06                                                    # x 눈금 자리
    if bars:
        y = _bars(fig, plt, bars, y - 0.01)
    if spec.get("info"):
        _info(fig, spec["info"], y - 0.01)
    fig.text(0.03, 0.022, spec.get("foot") or "ecom", color=dc.FAINT, fontsize=dc._fs(13, True))


def brief_card_png(spec: dict) -> bytes:
    """브리핑 카드 1080² PNG — 제목줄 · (칸) · (목록) · (하루 흐름) · (수급 막대) · 정보 행 · 꼬리."""
    return _png(_guarded(_draw_brief, spec))


def event_card_png(row: dict, ctx) -> bytes:
    """사건 카드 1080² PNG — 제목줄(이름 · 등급 · 시각) · 큰 숫자 · 왜 · 다음 · 작은 차트 · 칸 3 · 꼬리."""
    return _png(_event_fig(row, ctx))


def bundle_card_png(rows: list[dict], ctx) -> bytes:
    """「알림 N건 더」 카드 1080² PNG — 제목줄 + 행 ≤6(넘치면 +N) + 꼬리."""
    return _png(_bundle_fig(rows, ctx))
