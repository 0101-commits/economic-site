#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""디스코드 전용 '시각 보드' 카드 렌더러 (기획 2026-08-11, 아티팩트 e9144cf7).

카드 4종 — 전부 embed 이미지 1장이 본문이 되는 형식(카카오는 무변경):
  board()        카드 A: 정기 다이제스트 — 슬롯별 편성(PROFILES) 타일 + 캡션 + 30일 추세
  close_report() 카드 B: 장 마감 — 다이버징 수평 바 + 오늘 발동 알림 수·내일 일정
  weekly()       카드 C: 주간 — 주간 수익률 정렬 다이버징 바
  swing()        카드 D: 급변·서킷 — 히어로 등락률 + 인트라데이 임계선

신뢰성: 모든 공개 함수는 예외를 내부에서 삼키고 None 을 반환 — 호출측이 기존
embed(필드/슬롯 차트)로 폴백한다. 카드 실패가 알림 실패가 되지 않는다.

색: 상승 #E0443E / 하락 #3E7BE0 (국내 관습). 카드 바탕은 흰색(2026-08-25 사용자 지시)
이라 보조·선·패널 팔레트는 흰 배경 기준으로 다시 골랐다 — 강조색(UP/DN)만 값 유지.
대비는 본문 4.5:1 / 도형 3:1 을 넘긴다(test_discord_card.py 가 강제). 강도는 혼합비(램프)로.

편성: 카드 A(board)는 슬롯마다 다른 PROFILES 편성을 그린다 — 07시엔 한국·일본장이,
14시엔 미국장이 멈춰 있어 '안 움직이는 숫자'가 절반을 차지하던 고정 12타일을 대체한다.

폰트: 한글 폰트(Noto Sans CJK KR — kakao-daily.yml 이 설치 / 로컬 Malgun Gothic)를
찾고, 없으면 영문 라벨로 강등(stock-alerts.yml 은 매분 런이라 폰트 미설치).
이모지는 CI 폰트에 없어 카드 내부 텍스트에 쓰지 않는다(embed 제목이 담당).
"""
import datetime
import os
import tempfile

# ── 팔레트(흰 바탕 기준) ──────────────────────────────────────────────────
# 괄호 안은 BG(#FFFFFF) 대비 WCAG 대비비. 구 다크 표면(#313338)용 값을 그대로 쓰면
# MUT 1.95:1 · LINE 1.39:1 로 무너지고 TILE 은 흰 카드에 짙은 박스로 남는다.
BG = "#FFFFFF"        # 카드 바탕
TILE = "#F1F3F5"      # 보합 타일 · 차트 패널 배경(살짝 내려앉은 면)
INK = "#000000"       # 메인 텍스트 (21.0:1)
MUT = "#4A5461"       # 보조 텍스트 — 라벨·캡션·축 (8.7:1)
FAINT = "#6B7683"     # footer · 눈금 · 0선 (5.0:1)
LINE = "#3D4752"      # 추세선 · 일봉선 (10.5:1)
UP = "#E0443E"        # 상승 — 채움색(도형 4.15:1). 사용자 지정: 값 유지
DN = "#3E7BE0"        # 하락 — 채움색(도형 4.11:1). 사용자 지정: 값 유지
# 같은 색상의 어두운 변형 — 12pt 내외 '작은 글자'로 등락을 쓸 때만(원색은 4.1:1 로
# 본문 기준 4.5:1 미달). 채움색은 위 UP/DN 그대로 둔다.
UP_TXT = "#C4362F"    # (6.0:1)
DN_TXT = "#2F62BE"    # (6.0:1)

# ── 정사각(카카오) 캔버스 규격 ────────────────────────────────────────────
# 카톡 말풍선은 카드를 단변 400px 안팎으로 줄여 표시한다(1080 → 2.5배 축소). 축소 후에도
# 읽히는 하한 = 단변의 2.2%(1080에서 24px) → 150dpi 에서 24 * 72 / 150 = 11.52pt.
# 정사각 카드의 모든 본문 글자는 SQ_MIN_FS 로 하한이 걸린다(_fs / _draw_cells).
SQ = (7.2, 7.2)          # 7.2in × 150dpi = 1080px
SQ_DPI = 150
SQ_MIN_FS = 11.5

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


# ── 가상 카테고리 어댑터 ──────────────────────────────────────────────────
# 편성표가 참조하는 타일 중 indices/fx/commodities 에 없는 것들. 새 수집은 없다 —
# 이미 data.json 에 있는 필드를 타일이 읽는 (값, 등락) 모양으로 바꿔줄 뿐이다.
_YIELD_KEY = {"US10Y": ("us", "10Y"), "KR10Y": ("kr", "10Y"), "EU10Y": ("eu", "10Y")}
# jp 는 최신값이 2026-06-01 에서 멈춰 있어(3개월 정지) 타일 편성에 넣지 않는다.


def _yield_series(d, key):
    """yieldCurve.{국가}.series[만기] → [수익률%…] 시간순. 없으면 []."""
    cc, tenor = _YIELD_KEY.get(key, (None, None))
    if not cc:
        return []
    for s in (((d.get("yieldCurve") or {}).get(cc) or {}).get("series") or []):
        if s.get("tenor") == tenor:
            return [v for v in (_f(r.get("value")) for r in (s.get("data") or [])) if v is not None]
    return []


def _dxy_series(d):
    """달러인덱스 이력. economicIndicators.us.dxy_idx.history 는 {날짜: 값} dict — 키 정렬."""
    h = ((((d.get("economicIndicators") or {}).get("us") or {}).get("dxy_idx") or {})
         .get("history") or {})
    return [v for v in (_f(h[k]) for k in sorted(h)) if v is not None]


def _node(d, cat, key):
    """(현재값, 등락) — 금리만 등락 단위가 %가 아니라 bp.

    라이브 오버레이(_liveTiles)를 먼저 본다: send_kakao_digest.apply_live_quotes 가
    data.json 에 노드가 없거나(달러인덱스) 소스가 지연되는(미국채 10Y = FRED 2영업일)
    항목을 발송 시점 시세로 채워 넣는다. 없으면 스냅샷 값으로 내려간다."""
    lt = (d.get("_liveTiles") or {}).get(key)
    if lt:
        return _f(lt.get("value")), _f(lt.get("change"))
    if cat == "yield":
        vs = _yield_series(d, key)
        if not vs:
            return None, None
        bp = float(round((vs[-1] - vs[-2]) * 100)) if len(vs) > 1 else None
        return vs[-1], bp
    if cat == "macro" and key == "DXY":
        n = (((d.get("economicIndicators") or {}).get("us") or {}).get("dxy_idx") or {})
        return _f(n.get("value")), _f(n.get("change"))
    n = (d.get(cat) or {}).get(key) or {}
    price = _f(n.get("price") if n.get("price") is not None else n.get("rate"))
    chg = _f(n.get("change") if n.get("change") is not None else n.get("chgPct"))
    return price, chg


def _hist(d, cat, key, days=30):
    if cat == "yield":
        return _yield_series(d, key)[-days:]
    if cat == "macro" and key == "DXY":
        return _dxy_series(d)[-days:]
    h = ((d.get("history") or {}).get(cat) or {}).get(key) or []
    vals = [_f(r.get("close")) for r in h[-days:]]
    return [v for v in vals if v is not None]


def _fmt(v):
    if v is None:
        return "—"
    return f"{v:,.2f}" if v < 100 else f"{v:,.0f}" if v > 5000 else f"{v:,.1f}"


def _fmt_cnt(v):
    """거래량 같은 큰 정수 축약 — 타일 한 칸(약 12자)을 넘기지 않게. 한글은 만/억 단위."""
    if v is None:
        return "—"
    if not _STATE.get("ko"):
        return f"{v / 1e9:.1f}B" if v >= 1e9 else f"{v / 1e6:.1f}M" if v >= 1e6 else f"{v:,.0f}"
    if v >= 1e8:
        return f"{v / 1e8:,.1f}억"
    if v >= 1e4:
        return f"{v / 1e4:,.0f}만"
    return f"{v:,.0f}"


def _chgtxt(c):
    if c is None:
        return ""
    a = "▲" if c > 0 else "▼" if c < 0 else "■"
    return f"{a}{abs(c):.2f}%"


def _txt_color(up, flat=False):
    """작은 글자(14pt bold 미만)용 등락색. 원색 UP/DN 은 흰 바탕에서 4.1:1 이라
    본문 기준 4.5:1 에 못 미친다 — 같은 색상의 어두운 변형으로. 채움색은 원색 그대로."""
    if flat:
        return MUT
    return UP_TXT if up else DN_TXT


def _fmt_tile(cat, v):
    """타일 현재값 — 금리엔 %를 붙이고, 1 근처인 통화쌍(유로-달러)은 4자리까지."""
    if v is None:
        return "—"
    if cat == "yield":
        return f"{v:.2f}%"
    if cat == "fx" and abs(v) < 10:
        return f"{v:.4f}"
    return _fmt(v)


def _chgtxt_tile(cat, c):
    """타일 등락 — 금리는 bp, 나머지는 %."""
    if c is None:
        return ""
    if cat != "yield":
        return _chgtxt(c)
    a = "▲" if c > 0 else "▼" if c < 0 else "■"
    return f"{a}{abs(c):.0f}bp"


def _tile_color(c, sat=3.0):
    """등락 → (타일 배경, 잉크, 보합여부). 방향=색상, 강도=표면과의 혼합비.

    sat = 색이 포화하는 등락폭. 지수·원자재 3%, 통화 1%, 달러인덱스 0.8%, 금리 15bp
    (_sat_of). 금리를 bp 로 넣고 3% 스케일을 그대로 쓰면 평범한 5bp 날이 최대 채도가 된다.
    '보합여부'를 돌려주는 이유: 호출측이 bgc != TILE 로 보합을 되짚던 색 비교를 없애기 위함."""
    if c is None or abs(c) < 0.05 * (sat / 3.0):
        return TILE, MUT, True
    base = UP if c > 0 else DN
    a = min(0.95, 0.30 + abs(c) / float(sat) * 0.65)
    rgb = tuple(int(base[i:i + 2], 16) for i in (1, 3, 5))
    bgc = tuple(int(BG[i:i + 2], 16) for i in (1, 3, 5))
    mix = tuple(int(x * a + y * (1 - a)) for x, y in zip(rgb, bgc))
    return "#%02x%02x%02x" % mix, INK, False


def _fs(size, square=False):
    """정사각 카드의 글자 하한(SQ_MIN_FS) 적용 — 축소 말풍선 판독 규격."""
    return max(float(size), SQ_MIN_FS) if square else float(size)


def _sq_fig(plt, title, meta=""):
    """정사각 카드 공통 골격 1단 — 1080×1080 캔버스 + 제목줄(+ 우측 보조)."""
    fig = plt.figure(figsize=SQ, dpi=SQ_DPI)
    fig.patch.set_facecolor(BG)
    fig.text(0.03, 0.955, str(title)[:44], color=INK,
             fontsize=_fs(20, True), fontweight="bold")
    if meta:
        fig.text(0.97, 0.958, str(meta)[:40], color=MUT,
                 fontsize=_fs(11.5, True), ha="right")
    return fig


def _sq_panel(fig, box, ys, xs=None, prev=None, up=True, label="", right="",
              lines=(), src="", area=True):
    """정사각 카드 공통 골격 3단 — 주 영역(선 그래프 패널). 재료가 없으면 패널만 비고
    카드는 산다(사건형·지표형이 같은 패널을 쓴다).

    lines = [(값, 색, 라벨)] — 목표선·임계선·전일선처럼 수평 기준선. 첫 원소가 None 인
    항목은 건너뛴다. up = 상승 방향(채움·끝점 색)."""
    ax = fig.add_axes(box)
    ax.set_facecolor(TILE)
    col = UP if up else DN
    if label:
        ax.text(0.012, 1.045, label, transform=ax.transAxes, color=MUT,
                fontsize=_fs(12.5, True), va="bottom")
    if right:
        ax.text(1.0, 1.045, right, transform=ax.transAxes,
                color=_txt_color(up), fontsize=_fs(13, True),
                fontweight="bold", ha="right", va="bottom")
    vals = [v for v in (ys or []) if v is not None]
    refs = [v for v, _c, _l in lines if v is not None] + ([prev] if prev else [])
    if len(vals) >= 3:
        lo, hi = min(vals + refs), max(vals + refs)
        rng = (hi - lo) or (abs(hi) * 0.01) or 1.0
        floor = lo - 0.14 * rng
        ax.set_ylim(floor, hi + 0.16 * rng)
        ax.plot(range(len(vals)), vals, color=LINE, lw=2.0)
        if area:
            ax.fill_between(range(len(vals)), vals, floor, color=col, alpha=0.10)
        if prev:
            ax.axhline(prev, color=FAINT, lw=1.0, ls="--")
            ax.text(0.004, prev, _L("전일 ", "prev ") + _fmt(prev) + " ", color=FAINT,
                    fontsize=_fs(10.5, True), va="bottom",
                    transform=ax.get_yaxis_transform())
        for v, lcol, llab in lines:
            if v is None:
                continue
            ax.axhline(v, color=lcol, lw=1.3, ls="--")
            if llab:
                ax.text(0.996, v, llab + " ", color=lcol, fontsize=_fs(11, True),
                        ha="right", va="bottom", transform=ax.get_yaxis_transform())
        ax.plot(len(vals) - 1, vals[-1], "o", color=col, ms=7)
        ticks = sorted({0, len(vals) // 3, 2 * len(vals) // 3, len(vals) - 1})
        ax.set_xticks(ticks)
        if xs:
            xfmt = "%m/%d" if (xs[-1] - xs[0]).days >= 1 else "%H:%M"
            ax.set_xticklabels([xs[t].strftime(xfmt) if t < len(xs) else "" for t in ticks],
                               color=FAINT, fontsize=_fs(11, True))
        else:
            ax.set_xticklabels([""] * len(ticks))
        if src:
            ax.text(0.012, 0.03, src, transform=ax.transAxes, color=FAINT,
                    fontsize=_fs(10.5, True))
    else:
        ax.text(0.5, 0.5, _L("시세 데이터 없음", "no intraday data"), transform=ax.transAxes,
                color=FAINT, fontsize=_fs(12, True), ha="center", va="center")
        ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(axis="y", color="#E4E9EF", lw=0.8)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    return ax


def _footer(fig, now, extra="", square=False):
    fig.text(0.03, 0.022, _L(f"시세 {now.strftime('%m/%d %H:%M')} 기준 · 무료 시세 지연 가능",
                             f"as of {now.strftime('%m/%d %H:%M')} KST · free quotes may lag") + extra,
             color=FAINT, fontsize=_fs(11, square))
    fig.text(0.97, 0.022, "econ dashboard →", color=FAINT,
             fontsize=_fs(11, square), ha="right")


def _save(fig, name):
    plt = _STATE["plt"]
    path = os.path.join(tempfile.gettempdir(), name)
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return path


def _us_yield_line(d):
    """카드 A 하단 캡션 — 미국채 1·5·10·30Y 레벨% + 전일 대비 bp.
    출처 = data.yieldCurve.us.series(FRED DGS*). 데이터 없으면 ""(캡션 생략).

    10Y 만은 라이브(_liveTiles, ^TNX)가 있으면 그 값을 쓴다 — FRED 는 영업일 2일
    지연이라, 같은 카드의 10Y 타일(라이브)과 캡션(FRED)이 4.70% vs 4.74% 로 어긋난다."""
    try:
        series = ((d.get("yieldCurve") or {}).get("us") or {}).get("series") or []
        by = {s.get("tenor"): (s.get("data") or []) for s in series}
        live10 = (d.get("_liveTiles") or {}).get("US10Y") or {}
        parts = []
        for t in ("1Y", "5Y", "10Y", "30Y"):
            dt = by.get(t) or []
            last = _f((dt[-1] or {}).get("value")) if dt else None
            b = None
            if last is not None and len(dt) > 1 and _f((dt[-2] or {}).get("value")) is not None:
                b = round((last - _f((dt[-2] or {}).get("value"))) * 100)
            if t == "10Y" and _f(live10.get("value")) is not None:
                last = _f(live10.get("value"))
                b = _f(live10.get("change"))
            if last is None:
                continue
            bp = ""
            if b is not None:
                bp = f" {'▲' if b > 0 else '▼' if b < 0 else '■'}{abs(b):.0f}bp"
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

# ── 타일 카탈로그 ─────────────────────────────────────────────────────────
# _ASSETS 는 '자산 목록'으로 남긴다(디스코드 지표 드롭다운 _dc_select 와 주간 정렬
# weekly_rows 가 이 순서를 읽는다). 편성표는 아래 카탈로그의 키를 참조만 하므로
# 두 기능은 편성이 어떻게 바뀌든 무영향.
_EXTRA = [("달러인덱스", "Dollar Idx", "macro", "DXY"),
          ("유로-달러", "EUR/USD", "fx", "EURUSD"),
          ("상하이", "Shanghai", "indices", "Shanghai"),
          ("미국채 10Y", "UST 10Y", "yield", "US10Y"),
          ("한국채 10Y", "KTB 10Y", "yield", "KR10Y"),
          ("유로 10Y", "Bund 10Y", "yield", "EU10Y")]
_CATALOG = {key: (ko, en, cat) for ko, en, cat, key in _ASSETS + _EXTRA}
# 등락 강도가 포화하는 폭 — 카테고리별. 금리는 bp 단위라 스케일이 다르다.
_SAT = {"fx": 1.0, "yield": 15.0, "macro": 0.8}   # 금리는 bp — 15bp 하루면 주식 3% 급


def _sat_of(cat):
    return _SAT.get(cat, 3.0)


# ── 슬롯별 편성표 ─────────────────────────────────────────────────────────
# rows 의 각 줄이 카드의 한 줄이 된다(줄마다 길이가 달라도 됨 — 렌더가 최대 길이로
# 열 수를 잡는다). spark = 하단 30일 추세 패널. caption = 하단 캡션 종류.
# 경계는 KST 세션 겹침에서 나온다: 한국 09:00–15:30 · 일본 09:00–15:00 ·
# 유럽 16:00– · 미국 22:30(서머타임)/23:30.
PROFILES = {
    "kr_session": {                                   # 09~15시 — 사용자 지정 편성
        "title": "장중",
        "rows": [["KOSPI", "KOSDAQ", "Nikkei"],
                 ["USDKRW", "USDJPY", "DXY"],
                 ["Gold", "WTI", "US10Y"]],
        "spark": ["KOSPI", "SP500", "USDKRW"],
        "caption": "us_curve",
    },
    "pre_kr": {                                       # 07~08시 — 미국장 마감 정산
        "title": "개장 전",
        "rows": [["SP500", "NASDAQ", "SOX"],
                 ["DXY", "USDKRW", "USDJPY"],
                 ["US10Y", "Gold", "WTI"]],
        "spark": ["SP500", "NASDAQ", "USDKRW"],
        "caption": "us_curve",
    },
    "kr_close_eu": {                                  # 16~18시 — 마감 확정 + 유럽 개장
        "title": "마감·유럽",
        "rows": [["KOSPI", "Nikkei", "Shanghai"],
                 ["USDKRW", "USDJPY", "DXY"],
                 ["Gold", "Copper", "WTI"]],
        "spark": ["KOSPI", "USDKRW", "Gold"],
        "caption": "us_curve",
    },
    "us_pre": {                                       # 19~21시 — 금리·달러 중심
        "title": "미국 개장 전",
        "rows": [["US10Y", "KR10Y", "EU10Y"],
                 ["DXY", "USDKRW", "EURUSD"],
                 ["Gold", "Silver", "Copper"]],
        "spark": ["US10Y", "DXY", "Gold"],
        "caption": "us_curve",
    },
    "us_open": {                                      # 22시 — 미국 개장
        "title": "미국 장중",
        "rows": [["SP500", "NASDAQ", "SOX"],
                 ["DXY", "USDKRW", "US10Y"],
                 ["Gold", "WTI", "NatGas"]],
        "spark": ["SP500", "NASDAQ", "USDKRW"],
        "caption": "us_curve",
    },
    "weekend": {                                      # 주말·공휴일 11·17시
        "title": "주말",
        "rows": [["USDKRW", "USDJPY", "DXY"],
                 ["Gold", "Silver", "WTI"],
                 ["US10Y", "KR10Y", "Copper"]],
        "spark": ["USDKRW", "Gold", "SP500"],
        "caption": "us_curve",
    },
}
DEFAULT_PROFILE = "kr_session"


def _us_regular_session(now):
    """미국 정규장(현지 09:30~16:00 평일) 여부. 서머타임은 tz 데이터에 맡긴다 —
    3~11월 22:30 KST / 그 외 23:30 KST 를 직접 계산하면 전환주에 어긋난다.
    판정 불가(naive datetime·tz 데이터 부재)면 True — h22 를 종전 성격으로 둔다."""
    try:
        from zoneinfo import ZoneInfo
        if now is None or now.tzinfo is None:
            return True
        ny = now.astimezone(ZoneInfo("America/New_York"))
        return ny.weekday() < 5 and (9, 30) <= (ny.hour, ny.minute) < (16, 0)
    except Exception:
        return True


def profile_for(slot=None, weekend=False, now=None):
    """슬롯('h07'~'h22') → 편성 키. 모르는 슬롯은 DEFAULT_PROFILE 로 폴백(빈 카드 금지)."""
    if weekend:
        return "weekend"
    hr = None
    s = str(slot or "").strip().lower()
    if s.startswith("h") and s[1:].isdigit():
        hr = int(s[1:])
    elif now is not None:
        hr = now.hour
    if hr is None:
        return DEFAULT_PROFILE
    if hr < 9:
        return "pre_kr"
    if hr < 16:
        return "kr_session"
    if hr < 19:
        return "kr_close_eu"
    if hr < 22:
        return "us_pre"
    # '지금' 이 아니라 '그 슬롯 시각'에 미국장이 열려 있는지를 묻는다 — 오프시간
    # 미리보기·수동 실행에서 now 가 슬롯과 어긋나면 판정이 뒤집히기 때문.
    ref = now
    if now is not None and hr != now.hour:
        try:
            ref = now.replace(hour=hr, minute=30, second=0, microsecond=0)
        except ValueError:
            ref = now
    return "us_open" if _us_regular_session(ref) else "us_pre"


# 프로필마다 '오늘의 주인공' 하나 — 정사각(카톡) 캔버스 하단의 큰 인트라데이 패널.
HERO = {"kr_session": "KOSPI", "pre_kr": "SP500", "kr_close_eu": "KOSPI",
        "us_pre": "US10Y", "us_open": "SP500", "weekend": "USDKRW"}


def _draw_cells(fig, grid, box, fs, square=False):
    """타일 격자를 box=(x0, y0, w, h) figure 좌표에 그린다. fs=(라벨, 값, 등락) 폰트.

    grid = [[cell, …], …], cell = (라벨, 값 문자열, 우하단 문자열, 등락값|None, 포화폭).
    등락값은 색·잉크 결정에만 쓴다(문자열은 호출측이 이미 만들어 넘긴다) — 그래서
    카탈로그 지표(_draw_tiles)와 사건 타일(종목·목표가·상태)이 같은 코드로 그려진다.

    글자 위치는 타일 높이 비율로 잡는다 — 캔버스(가로 10×7 / 정사각 1:1)마다 타일
    높이가 달라도 같은 코드로 겹침 없이 배치되게. square=True 면 폰트에
    SQ_MIN_FS 하한을 걸어 축소 말풍선에서 읽히게 한다."""
    from matplotlib.patches import FancyBboxPatch
    gx0, gy0, gw, gh = box
    grid = [r for r in grid if r]
    if not grid:
        return
    cols = max(len(r) for r in grid)
    rows = len(grid)
    fs_l, fs_p, fs_c = (_fs(f, square) for f in fs)
    for r_, line in enumerate(grid):
        for c_, cell in enumerate(line):
            label, val, note, chg, sat = cell
            x = gx0 + c_ * gw / cols
            y = gy0 + (rows - 1 - r_) * gh / rows
            w, h = gw / cols - 0.008, gh / rows - 0.015
            bgc, ink, _flat = _tile_color(chg, sat)
            fig.patches.append(FancyBboxPatch(
                (x, y), w, h, boxstyle="round,pad=0.004,rounding_size=0.009",
                transform=fig.transFigure, fc=bgc, ec="none"))
            fig.text(x + 0.013, y + 0.71 * h, label, color=ink, fontsize=fs_l)
            fig.text(x + 0.013, y + 0.33 * h, val, color=INK, fontsize=fs_p, fontweight="bold")
            if note:
                fig.text(x + w - 0.011, y + 0.09 * h, note, color=ink,
                         fontsize=fs_c, fontweight="bold", ha="right")


def _cell(label, val, note="", chg=None, sat=3.0):
    """자유 타일 한 칸 — 사건형·상태형 카드가 쓴다(카탈로그 비의존)."""
    return (str(label), str(val), str(note), chg, sat)


def _draw_tiles(fig, d, grid, box, fs, square=False):
    """카탈로그 키 격자(편성표) → 셀 격자로 바꿔 _draw_cells 에 넘긴다."""
    cells = []
    for line in grid:
        row = []
        for key in line:
            ko, en, cat = _CATALOG.get(key, (key, key, "indices"))
            price, chg = _node(d, cat, key)
            row.append(_cell(_L(ko, en), _fmt_tile(cat, price),
                             _chgtxt_tile(cat, chg), chg, _sat_of(cat)))
        cells.append(row)
    _draw_cells(fig, cells, box, fs, square=square)


def _meta_line(d, cal):
    """헤더 우측 보조 — MOVE 지수 + 오늘 일정."""
    mv = ((d.get("sentiment") or {}).get("move")) or {}
    head = []
    if _f(mv.get("value")) is not None:
        head.append(f"MOVE {mv['value']:.1f} {_chgtxt(_f(mv.get('change')))}".strip())
    if cal:
        head.append((_L("오늘 ", "today ") + cal).strip())
    return " · ".join(head)


def board(d, now, cal="", slot=None, weekend=False, profile=None, shape="wide", hero=None):
    """카드 A — 시황 보드. 실패 시 None(호출측이 슬롯 차트로 폴백).

    편성(v5): 고정 12타일 대신 PROFILES 의 슬롯별 편성을 그린다 — 07시엔 한국·일본장이,
    14시엔 미국장이 멈춰 있어 '안 움직이는 숫자'가 절반을 차지하던 문제. rows 의 줄 수·
    길이를 그대로 따르므로 3×3 도 4×3 도 같은 루프로 나온다.

    캔버스(v6): shape="wide"=디스코드 embed(10×7) / "square"=카카오 피드(1080×1080).
    편성표는 하나이고 캔버스만 둘 — 편성을 바꾸면 두 채널이 함께 바뀐다. 정사각을 쓰는
    이유는 카톡 말풍선이 폭 고정·높이 비례라 세로가 길면 확대·크롭되기 때문(2026-07-08
    이력: 1080×1440 → 864×1080 → 1:1). hero=(xs, ys, prev, 라벨) = 정사각 하단 인트라데이
    재료. 네트워크는 호출측이 담당한다 — 이 모듈은 시세를 직접 조회하지 않는다.
    profile 인자는 미리보기·테스트용 강제 지정(운영은 slot/weekend 로 판정)."""
    try:
        plt, _ = _setup()
        pkey = profile if profile in PROFILES else profile_for(slot, weekend, now)
        prof = PROFILES.get(pkey) or PROFILES[DEFAULT_PROFILE]
        if shape == "square":
            return _board_square(plt, d, now, pkey, prof, cal, hero)
        return _board_wide(plt, d, now, prof, cal)
    except Exception as e:
        print(f"::warning title=디스코드 카드 실패::board({shape}): {e} — 기존 형식 폴백")
        return None


def _board_wide(plt, d, now, prof, cal):
    """가로 10×7 @160dpi — 디스코드 embed. 타일 격자 + 미국채 캡션 + 30일 추세 n개."""
    grid = [r for r in prof["rows"] if r]
    cols = max(len(r) for r in grid)
    fs = (14, 21, 14) if cols <= 3 else (13, 17, 13)   # 3열이면 타일이 넓어 글자를 키운다
    fig = plt.figure(figsize=(10, 7.0), dpi=160)
    fig.patch.set_facecolor(BG)
    fig.text(0.03, 0.945, _L(f"{now.month}/{now.day} {now.hour}시 시황 보드 · {prof['title']}",
                             f"{now.month}/{now.day} {now.hour}h Market Board"),
             color=INK, fontsize=19, fontweight="bold")
    meta = _meta_line(d, cal)
    if meta:
        fig.text(0.97, 0.950, meta, color=MUT, fontsize=11, ha="right")
    _draw_tiles(fig, d, grid, (0.03, 0.44, 0.94, 0.46), fs)
    # 하단 캡션 — 미국채 1·5·10·30Y(사용자 지정 2026-08-20, 구 원자재 4종 대체).
    rest = _us_yield_line(d) if prof.get("caption") == "us_curve" else ""
    if rest:
        fig.text(0.03, 0.395, rest, color=MUT, fontsize=12)
    fig.text(0.03, 0.335, _L("추세 30일", "30-day trend"), color=MUT, fontsize=12)
    sparks = prof.get("spark") or []
    n = len(sparks)
    gap = 0.0175
    sw = (0.94 - gap * (n - 1)) / n if n else 0.94
    for i, key in enumerate(sparks):
        ko, en, cat = _CATALOG.get(key, (key, key, "indices"))
        ax = fig.add_axes([0.03 + i * (sw + gap), 0.075, sw, 0.235])
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
            up = vs[-1] >= vs[0]
            ax.plot(len(vs) - 1, vs[-1], "o", color=UP if up else DN, ms=5)
            # 30일 변화 — 금리는 %가 아니라 bp(4.50→4.74 는 +5.3% 가 아니라 +24bp).
            if cat == "yield":
                p30 = f"{(vs[-1] - vs[0]) * 100:+.0f}bp"
            else:
                p30 = f"{((vs[-1] / vs[0] - 1) * 100 if vs[0] else 0.0):+.1f}%"
            ax.text(0.05, 0.84, _L(ko, en), transform=ax.transAxes, color=MUT, fontsize=12)
            ax.text(0.95, 0.84, p30, transform=ax.transAxes,
                    color=UP_TXT if up else DN_TXT, fontsize=12, ha="right", fontweight="bold")
            ax.text(0.05, 0.08, _fmt_tile(cat, vs[-1]), transform=ax.transAxes,
                    color=INK, fontsize=13)
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
    _footer(fig, now)
    return _save(fig, "discord_card_board.png")


def _board_square(plt, d, now, pkey, prof, cal, hero):
    """정사각 1080×1080 @150dpi — 카카오 피드 한 통의 이미지.

    구성 = 타일 격자 + 미국채 캡션 + 히어로 인트라데이 1개(전 폭). 종전 카톡 이미지는
    지표 2개짜리 2패널이었다 — 타일이 편성을 담고, 카톡이 잘하던 '오늘 어떻게 움직였나'는
    패널이 하나로 합쳐지며 오히려 커진다. hero 재료가 없으면 패널만 비고 카드는 산다."""
    grid = [r for r in prof["rows"] if r]
    fig = plt.figure(figsize=(7.2, 7.2), dpi=150)
    fig.patch.set_facecolor(BG)
    wd = "월화수목금토일"[now.weekday()]
    fig.text(0.03, 0.955, _L(f"{now.month}/{now.day}({wd}) {now.hour}시 시황 · {prof['title']}",
                             f"{now.month}/{now.day} {now.hour}h · {prof['title']}"),
             color=INK, fontsize=20, fontweight="bold")
    meta = _meta_line(d, cal)
    if meta:
        fig.text(0.97, 0.958, meta, color=MUT, fontsize=11.5, ha="right")
    _draw_tiles(fig, d, grid, (0.03, 0.575, 0.94, 0.345), (13, 19, 13), square=True)
    cap = _us_yield_line(d) if prof.get("caption") == "us_curve" else ""
    if cap:
        fig.text(0.03, 0.533, cap, color=MUT, fontsize=12)

    hkey = HERO.get(pkey) or (grid[0][0] if grid and grid[0] else None)
    if not hkey:
        _footer(fig, now)
        return _save(fig, "kakao_card_board.png")
    hko, hen, hcat = _CATALOG.get(hkey, (hkey, hkey, "indices"))
    hprice, hchg = _node(d, hcat, hkey)
    xs, ys, prev, src = (hero or ([], [], None, ""))
    # '오늘'은 구간이 정말 오늘 하루일 때만 쓴다 — 20시 슬롯의 미국채 패널은
    # 간밤 미국 세션(어제 21:20~오늘 03:55)이라 '오늘'로 적으면 지금 움직이는 중으로 읽힌다.
    when = _L("오늘", "today")
    if xs:
        if xs[0].date() != xs[-1].date():
            when = _L("간밤", "overnight")
        elif xs[-1].date() != now.date():
            when = xs[-1].strftime("%m/%d")
    fig.text(0.03, 0.475, f"{_L(hko, hen)} {when}" + (f" · {src}" if src else ""),
             color=MUT, fontsize=12.5)
    fig.text(0.97, 0.475, f"{_fmt_tile(hcat, hprice)}  {_chgtxt_tile(hcat, hchg)}".strip(),
             color=_txt_color((hchg or 0) >= 0, flat=hchg is None),
             fontsize=14, fontweight="bold", ha="right")
    ax = fig.add_axes([0.03, 0.085, 0.94, 0.375])
    ax.set_facecolor(TILE)
    if ys and len(ys) >= 3:
        lo, hi = min(ys + ([prev] if prev else [])), max(ys + ([prev] if prev else []))
        rng = (hi - lo) or (abs(hi) * 0.01) or 1.0
        floor = lo - 0.14 * rng
        ax.set_ylim(floor, hi + 0.14 * rng)
        up = (ys[-1] >= prev) if prev else (ys[-1] >= ys[0])
        ax.plot(range(len(ys)), ys, color=LINE, lw=2.0)
        ax.fill_between(range(len(ys)), ys, floor, color=UP if up else DN, alpha=0.10)
        if prev:
            ax.axhline(prev, color=FAINT, lw=1.0, ls="--")
            ax.text(0.004, prev, _L("전일 ", "prev ") + _fmt_tile(hcat, prev) + " ",
                    color=FAINT, fontsize=10.5, va="bottom",
                    transform=ax.get_yaxis_transform())
        ax.plot(len(ys) - 1, ys[-1], "o", color=UP if up else DN, ms=7)
        ticks = sorted({0, len(ys) // 3, 2 * len(ys) // 3, len(ys) - 1})
        ax.set_xticks(ticks)
        # 구간이 하루를 넘으면(일봉 폴백) 날짜 눈금 — 인트라데이 오독 방지.
        xfmt = "%m/%d" if (xs and (xs[-1] - xs[0]).days >= 1) else "%H:%M"
        ax.set_xticklabels([xs[t].strftime(xfmt) if xs else "" for t in ticks],
                           color=FAINT, fontsize=11)
    ax.set_yticks([])
    ax.grid(axis="y", color="#E4E9EF", lw=0.8)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    _footer(fig, now)
    return _save(fig, "kakao_card_board.png")


def stock_alert(hero, others, now, shape="wide", extra_tiles=None):
    """카드 E — 종목 알림(기획 5154773b P1). 좌 히어로(조건·현재가·등락·거래량) +
    우 30일 일봉 + 목표선(점선) + 발동점 도트, 하단 = 나머지 종목 1줄씩.

    hero = {name, cond, price, pct, target(없으면 None), closes(일봉 종가 리스트),
            vol_today, vol_prev, market}, others = [문자열 줄]. 재료는 전부
    check_alerts.yahoo_snapshot 반환값 — 추가 API 호출 없음. 실패 시 None(텍스트 폴백).

    shape="square"(기획 v3 I1) = 카카오 피드용 1080². 나머지 종목은 줄글이 아니라
    타일로 들어가(합본, 최대 6칸) 통 수가 늘어도 사진은 한 장이다.
    extra_tiles = [(라벨, 값, 우하단, 등락|None)] — 호출측이 시장 맥락·일정을 넣는 자리."""
    try:
        if not hero or hero.get("price") is None:
            return None
        plt, _ = _setup()
        if shape == "square":
            return _stock_square(plt, hero, others, now, extra_tiles)
        extra = min(len(others or []), 4)
        hgt = 4.2 + 0.42 * extra
        fig = plt.figure(figsize=(10, hgt), dpi=160)
        fig.patch.set_facecolor(BG)
        pct = _f(hero.get("pct"))
        col = UP if (pct or 0) > 0 else DN if (pct or 0) < 0 else MUT
        coltxt = _txt_color((pct or 0) > 0, flat=not (pct or 0))   # 작은 글자용
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
                        color=coltxt, fontsize=10.5, va="bottom")
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


def _stock_square(plt, hero, others, now, extra_tiles=None):
    """사건형 정사각 — 종목 알림. 타일(종목·목표·거래량·동시발동 종목) + 30일 일봉+목표선."""
    pct = _f(hero.get("pct"))
    mkt = hero.get("market", "KR")
    up = (pct or 0) >= 0
    col = UP if (pct or 0) > 0 else DN if (pct or 0) < 0 else MUT
    name = str(hero.get("name") or "")[:14]
    fig = _sq_fig(plt, _L(f"종목 알림 · {name}", f"Stock Alert · {name}"),
                  now.strftime("%m/%d %H:%M"))
    fig.text(0.03, 0.905, str(hero.get("cond") or "")[:40], color=MUT, fontsize=_fs(12.5, True))

    def _p(v):
        return f"{v:,.2f}" if mkt == "US" else f"{v:,.0f}"

    tgt = _f(hero.get("target"))
    cells = [[_cell(name, _p(hero["price"]), _chgtxt(pct), pct)]]
    if tgt:
        gap = (hero["price"] / tgt - 1) * 100 if hero["price"] else None
        cells[0].append(_cell(_L("목표가", "target"), _p(tgt),
                              (f"{gap:+.1f}%" if gap is not None else ""), None))
    vt, vp = _f(hero.get("vol_today")), _f(hero.get("vol_prev"))
    if vt:
        # 거래량엔 방향색을 주지 않는다(chg=None) — 붉게 칠하면 '올랐다'로 읽힌다.
        cells[0].append(_cell(_L("거래량", "volume"), _fmt_cnt(vt),
                              (_L(f"전일比 {(vt / vp - 1) * 100:+.0f}%", f"{(vt / vp - 1) * 100:+.0f}% d/d")
                               if vp else ""), None))
    row2 = [_cell(str(l)[:10], str(v), str(n), c) for l, v, n, c in (extra_tiles or [])[:3]]
    # 동시 발동 나머지 종목 — 줄글 대신 타일(합본). "삼성전자 71,200 ▲2.4%" 형태를 쪼갠다.
    for ln in (others or [])[:3]:
        if len(row2) >= 3:
            break
        parts = str(ln).split()
        row2.append(_cell(parts[0][:10] if parts else "?",
                          parts[1] if len(parts) > 1 else "",
                          parts[2] if len(parts) > 2 else "", None))
    if row2:
        cells.append(row2)
    _draw_cells(fig, cells, (0.03, 0.60, 0.94, 0.28), (13, 19, 13), square=True)

    closes = [c for c in (hero.get("closes") or [])[-30:] if c is not None]
    _sq_panel(fig, [0.03, 0.085, 0.94, 0.44], closes, up=up,
              label=_L("30일 일봉", "30-day daily"),
              right=f"{_p(hero['price'])}  {_chgtxt(pct)}".strip(),
              lines=[(tgt, col, _L(f"목표 {_p(tgt)}", f"target {_p(tgt)}") if tgt else "")])
    _footer(fig, now, square=True)
    return _save(fig, "kakao_card_stock.png")


def close_report(items, now, alerts_cnt=None, cal="", intraday=None, investor=None,
                 movers=None, fired_names=None, shape="wide"):
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
        if shape == "square":
            return _close_square(plt, its, now, alerts_cnt, cal, intraday, investor, fired_names)
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
                         color=_txt_color(dirc == UP), fontsize=12.5,
                         ha="right", va="top", fontweight="bold")
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
                     + (f" · {inv.get('date')}" if inv.get("date") else "")
                     + (f" {inv.get('reason')}" if inv.get("reason") else ""),
                     color=MUT, fontsize=12)
        # ── 우하: 특징주 top3 + 오늘 발동 알림 + 내일 일정
        ty = 0.435
        gain, lose = (movers or ([], []))
        if gain or lose:
            fig.text(0.56, ty, _L("특징주(코스피)", "KOSPI movers"), color=MUT, fontsize=12)
            ty -= 0.045
            for r in (gain or [])[:3]:
                fig.text(0.56, ty, f"▲ {str(r.get('name'))[:10]} {abs(_f(r.get('chg')) or 0):.1f}%",
                         color=UP_TXT, fontsize=12)
                ty -= 0.042
            for r in (lose or [])[:3]:
                fig.text(0.56, ty, f"▼ {str(r.get('name'))[:10]} {abs(_f(r.get('chg')) or 0):.1f}%",
                         color=DN_TXT, fontsize=12)
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


def _close_square(plt, its, now, alerts_cnt, cal, intraday, investor, fired_names):
    """지표형 정사각 — 장 마감(기획 v3 §02 P2). 지수 다이버징 바 + 수급·알림 타일
    + 코스피 인트라데이. 가로 4분면을 세로 3단으로 접는다."""
    fig = _sq_fig(plt, _L(f"{now.month}/{now.day} 장 마감", f"{now.month}/{now.day} Market Close"),
                  now.strftime("%H:%M"))
    inv = investor or {}
    # as-of 라벨 필수 — 정사각 카드엔 날짜 칸이 없어 '언제 기준 수급인지' 확인이 불가능했다.
    # (확정치는 KRX 18시 이후 — 잠정 값을 확정처럼 읽히게 두면 실제 값과 어긋난다.)
    _asof = " ".join(x for x in (str(inv.get("date") or "")[5:], inv.get("reason") or "") if x)
    _unit = _L("억원", "0.1bn") + (f" · {_asof}" if _asof else "")
    cells = [[]]
    for lab, key, sat in ((_L("외국인", "foreign"), "foreign", 5000.0),
                          (_L("기관", "inst"), "inst", 5000.0)):
        v = _f(inv.get(key))
        if v is not None:
            cells[0].append(_cell(lab, f"{v:+,.0f}", _unit, v, sat=sat))
    if alerts_cnt is not None:
        nm = ""
        if fired_names:
            nm = str(fired_names[0])[:8]
            if len(fired_names) > 1:
                nm += _L(f" 외 {len(fired_names) - 1}", f" +{len(fired_names) - 1}")
        cells[0].append(_cell(_L("오늘 알림", "alerts"), f"{alerts_cnt}", nm, None))
    if cells[0]:
        _draw_cells(fig, cells, (0.03, 0.775, 0.94, 0.145), (13, 19, 13), square=True)
        bar_box, bar_lab = [0.17, 0.475, 0.80, 0.265], 0.755
    else:
        bar_box, bar_lab = [0.17, 0.475, 0.80, 0.42], 0.915
    _bars(fig, bar_box, [(l, c) for l, _p, c in its], square=True, lim_mul=1.35)
    fig.text(0.03, bar_lab, _L("지수 등락", "index moves"), color=MUT, fontsize=_fs(12.5, True))
    xs, ys, prev, src = intraday or ([], [], None, "")
    _sq_panel(fig, [0.03, 0.165, 0.94, 0.245], ys, xs=xs, prev=prev,
              up=bool(ys) and (ys[-1] >= (prev or ys[0])),
              label=_L("코스피 오늘", "KOSPI today") + (f" · {src}" if src else ""))
    if cal:
        fig.text(0.03, 0.075, _L("내일  ", "tomorrow  ") + str(cal)[:44],
                 color=INK, fontsize=_fs(12.5, True))
    _footer(fig, now, square=True)
    return _save(fig, "kakao_card_close.png")


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


def _week_flow_5d(d):
    """주간 수급 5영업일 합 → {from, to, foreign, inst} / 없으면 None.

    소스는 investor_flows(네이버 = 포털·언론 기준) — 일별 타일과 같은 기준이어야 한다.
    조회 실패 시 data.json.investorTrading 으로 폴백하되, 그때는 집계 구간을 캡션에 적어
    '어디까지 더한 값'인지 숨기지 않는다.
    """
    try:
        import investor_flows
        w = investor_flows.week_sum("KOSPI", 5)
        if w:
            return w
    except Exception:                                        # noqa: BLE001
        pass
    daily = [r for r in ((d.get("investorTrading") or {}).get("daily") or [])
             if _f(r.get("foreign")) is not None and _f(r.get("inst")) is not None][-5:]
    if not daily:
        return None
    return {"from": daily[0].get("date"), "to": daily[-1].get("date"), "days": len(daily),
            "foreign": sum(_f(r.get("foreign")) for r in daily),
            "inst": sum(_f(r.get("inst")) for r in daily)}


def _week_flow_line(d):
    """주간 수급 합계 캡션(기획 5154773b P3) — 최근 5영업일 외국인·기관 순매수 합(억원).

    집계 구간(MM-DD~MM-DD)을 함께 적는다 — 구간을 안 적으면 '5일'이 어느 5일인지
    확인할 방법이 없어 실제 값 대조가 불가능했다. 결측이면 "".
    """
    try:
        w = _week_flow_5d(d)
        if not w:
            return ""
        fo, it = w["foreign"], w["inst"]
        span = f"{str(w.get('from') or '')[5:]}~{str(w.get('to') or '')[5:]}"
        return _L(f"주간 수급(코스피 {span}): 외국인 {fo:+,.0f}억 · 기관 {it:+,.0f}억",
                  f"weekly net buy (KOSPI {span}): foreign {fo:+,.0f} · inst {it:+,.0f} (0.1bn KRW)")
    except Exception:
        return ""


def _bars(fig, box, rows, square=False, unit="%", nd=2, lim_mul=1.6):
    """다이버징 수평 바 — rows=[(라벨, 값)]. 주간·마감 카드가 공유한다."""
    ax = fig.add_axes(box)
    ax.set_facecolor(BG)
    vals = [v for _l, v in rows]
    ax.barh(range(len(rows)), vals, height=0.55,
            color=[UP if v > 0 else DN if v < 0 else FAINT for v in vals])
    ax.axvline(0, color=FAINT, lw=1)
    for i, (_l, v) in enumerate(rows):
        ax.text(v + (0.08 if v >= 0 else -0.08) * (max(abs(x) for x in vals) or 1) / 2.5, i,
                f"{v:+.{nd}f}{unit}", va="center", ha="left" if v >= 0 else "right",
                color=INK, fontsize=_fs(12, square))
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([l for l, _v in rows], color=MUT, fontsize=_fs(12.5, square))
    lim = (max(abs(v) for v in vals) or 1) * lim_mul + 0.2
    ax.set_xlim(-lim, lim)
    ax.set_xticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    return ax


def weekly(d, now, next_week="", shape="wide"):
    """카드 C — 주간 수익률 정렬 바 + 주간 경로 스파크(기획 5154773b P3). 실패 시 None.

    스파크(각 자산 6일 종가)는 같은 -2%라도 '내내 하락'과 '금요일 급락'을 구분한다.
    하단 캡션 = 주간 수급 합계 + 다음 주 일정(next_week — build_weekly_parts 의 '다음주' 블록)."""
    try:
        plt, _ = _setup()
        cat_of = {key: cat for ko, en, cat, key in _ASSETS}
        rows = [(_L(ko, en), key, chg) for ko, en, key, chg in weekly_rows(d)]
        if not rows:
            return None
        if shape == "square":
            return _weekly_square(plt, d, now, rows, next_week)
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


def _weekly_square(plt, d, now, rows, next_week):
    """지표형 정사각 — 주간 리포트(기획 v3 I2). 주간 수익률 다이버징 바 + 수급·일정 타일.

    카톡 주간 슬롯이 옛 2티커 라인 차트로 나가던 것을 대체한다. '지금 시각 타일'이
    주간 본문과 어긋나던 문제는 타일을 없애는 대신 주간 수치(최고·최저·수급)로 바꿔 푼다."""
    wk0 = now - datetime.timedelta(days=now.weekday())
    fig = _sq_fig(plt, _L(f"주간 리포트 · {wk0.month}/{wk0.day}~{now.month}/{now.day}",
                          f"Weekly · {wk0.month}/{wk0.day}~{now.month}/{now.day}"),
                  _L("주간 종가 기준", "weekly close"))
    best, worst = rows[-1], rows[0]
    cells = [[_cell(_L("최고", "best"), best[0], f"{best[2]:+.2f}%", best[2]),
              _cell(_L("최저", "worst"), worst[0], f"{worst[2]:+.2f}%", worst[2])]]
    _w5 = _week_flow_5d(d)
    if _w5:
        fo = _w5["foreign"]
        _span = f"{str(_w5.get('from') or '')[5:]}~{str(_w5.get('to') or '')[5:]}"
        cells[0].append(_cell(_L("외국인 5일", "foreign 5d"), f"{fo:+,.0f}",
                              _L("억원", "0.1bn") + f" · {_span}", fo, sat=20000.0))
    _draw_cells(fig, cells, (0.03, 0.775, 0.94, 0.145), (13, 19, 13), square=True)
    _bars(fig, [0.17, 0.135, 0.80, 0.60], [(l, c) for l, _k, c in rows],
          square=True, lim_mul=1.3)
    fig.text(0.03, 0.755, _L("주간 수익률", "weekly returns"), color=MUT, fontsize=_fs(12.5, True))
    if next_week:
        fig.text(0.03, 0.075, _L("다음 주  ", "next week  ") + str(next_week)[:46],
                 color=INK, fontsize=_fs(12.5, True))
    _footer(fig, now, square=True)
    return _save(fig, "kakao_card_weekly.png")


def swing(name, price, pct, thr_pct, xs, ys, prev, now, resume="", src="", shape="wide"):
    """카드 D — 급변·서킷. 히어로 등락률 + 인트라데이(또는 일봉 폴백) 임계선.
    xs/ys/prev = send_kakao_digest._intraday_chain 반환값(비어 있으면 히어로만 — 최후).
    src = 폴백 라벨('일봉 7D' 등, 기획 5154773b P0) — 패널에 표기해 인트라데이 오독 방지.
    x축 눈금은 구간 폭으로 자동(하루 안=HH:MM, 여러 날=M/D). 실패 시 None."""
    try:
        if pct is None:
            return None
        plt, _ = _setup()
        if shape == "square":
            return _swing_square(plt, name, price, pct, thr_pct, xs, ys, prev, now, resume, src)
        col = UP if pct > 0 else DN
        coltxt = _txt_color(pct > 0)                   # 작은 글자용
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
                        color=coltxt, fontsize=11.5, ha="right",
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


def _swing_square(plt, name, price, pct, thr_pct, xs, ys, prev, now, resume, src):
    """사건형 정사각 — 급변·서킷 발동. 히어로 등락률 + 타일 3 + 인트라데이 임계선."""
    col = UP if pct > 0 else DN
    fig = _sq_fig(plt, _L(f"시장 급변 · {str(name)[:14]}", f"Market Swing · {str(name)[:14]}"),
                  now.strftime("%m/%d %H:%M"))
    fig.text(0.03, 0.845, f"{pct:+.2f}%", color=col, fontsize=_fs(56, True), fontweight="bold")
    sub = _L(f"임계 ±{abs(thr_pct):.1f}% {'상향' if pct > 0 else '하향'} 돌파",
             f"threshold ±{abs(thr_pct):.1f}% crossed")
    if resume:
        sub += " · " + str(resume)
    fig.text(0.03, 0.795, sub[:44], color=MUT, fontsize=_fs(12.5, True))
    thr_v = prev * (1 + (abs(thr_pct) if pct > 0 else -abs(thr_pct)) / 100.0) if prev else None
    cells = [[_cell(str(name)[:10], _fmt(price) if price is not None else "—",
                    _chgtxt(pct), pct)]]
    if prev:
        cells[0].append(_cell(_L("전일", "prev"), _fmt(prev),
                              (f"{price - prev:+,.1f}" if price is not None else ""), None))
        cells[0].append(_cell(_L("임계선", "threshold"), _fmt(thr_v),
                              f"±{abs(thr_pct):.1f}%", None))
    _draw_cells(fig, cells, (0.03, 0.60, 0.94, 0.145), (13, 19, 13), square=True)
    _sq_panel(fig, [0.03, 0.085, 0.94, 0.44], ys, xs=xs, prev=prev, up=pct > 0,
              label=_L("당일 흐름", "today") + (f" · {src}" if src else ""),
              right=f"{_fmt(price)}  {_chgtxt(pct)}".strip() if price is not None else "",
              lines=[(thr_v, col, f"{'+' if pct > 0 else '-'}{abs(thr_pct):.1f}%")])
    _footer(fig, now, square=True)
    return _save(fig, "kakao_card_swing.png")


def status(title, state, reason="", timeline=None, tiles=None, now=None, tone="ok"):
    """상태형 정사각 카드(기획 v3 I1) — 차트가 없거나 의미 없는 통지용.
    서킷 해제·테스트 발송·복구 통지가 쓴다. 실패 시 None(텍스트 폴백).

    title 에는 이모지를 넣지 않는다(카드 폰트에 글리프가 없다 — 본문 제목이 담당).
    state = 큰 상태 배지 문구("거래 재개"), reason = 그 아래 한 줄,
    timeline = [(문구, 지남여부)] 최대 4칸, tiles = [(라벨, 값, 우하단, 등락|None)],
    tone = "ok"(초록 계열=해제·정상) / "warn"(주의) / "info"(회색=테스트·운영)."""
    try:
        plt, _ = _setup()
        now = now or datetime.datetime.now()
        band = {"ok": "#1F7A4D", "warn": UP_TXT, "info": MUT}.get(tone, MUT)
        wash = {"ok": "#E4F2EA", "warn": "#FBE7E6", "info": TILE}.get(tone, TILE)
        fig = _sq_fig(plt, title, now.strftime("%m/%d %H:%M"))
        from matplotlib.patches import FancyBboxPatch
        # 세로 배분 — 상태 배지가 주 영역이고, 타임라인·타일이 있으면 그만큼만 내준다.
        # (요소를 상단에 몰면 아래 절반이 비고, 타일에 남은 높이를 다 주면 한 칸이
        #  카드 절반을 먹는다 — 2026-09-08 두 번의 실측 결과 고정한 배분.)
        tl = [t for t in (timeline or []) if t][:4]
        rows = []
        if tiles:
            rows = [[_cell(str(l)[:10], str(v), str(n), c) for l, v, n, c in tiles[:3]]]
            if len(tiles) > 3:
                rows.append([_cell(str(l)[:10], str(v), str(n), c) for l, v, n, c in tiles[3:6]])
        # 남은 세로를 가중치로 나눈다 — 배지 3 : 타임라인 1.2 : 타일행 2.2.
        # (밴드에 남은 높이를 다 주면 카드 절반이 초록 사각형이 되고, 고정 높이로 두면
        #  요소가 적은 카드에서 아래가 빈다 — 2026-09-08 실측 후 고정.)
        gap, top, bot = 0.018, 0.885, 0.075
        w_band, w_tl, w_tiles = 3.0, 1.2, 2.2 * len(rows)
        wtot = w_band + (w_tl if tl else 0.0) + w_tiles
        avail = (top - bot) - gap * ((1 if tl else 0) + (1 if rows else 0))
        band_h = avail * w_band / wtot
        tl_h = avail * w_tl / wtot if tl else 0.0
        tiles_h = avail * w_tiles / wtot if rows else 0.0
        band_y = top - band_h
        fig.patches.append(FancyBboxPatch(
            (0.03, band_y), 0.94, band_h, boxstyle="round,pad=0.004,rounding_size=0.012",
            transform=fig.transFigure, fc=wash, ec="none"))
        fig.text(0.06, band_y + band_h * (0.55 if reason else 0.42), str(state)[:22],
                 color=band, fontsize=_fs(38, True), fontweight="bold")
        if reason:
            fig.text(0.06, band_y + band_h * 0.22, str(reason)[:52], color=INK,
                     fontsize=_fs(13.5, True))
        if tl:
            w = (0.94 - 0.012 * (len(tl) - 1)) / len(tl)
            ty = band_y - gap - tl_h
            for i_, (txt, done) in enumerate(tl):
                x = 0.03 + i_ * (w + 0.012)
                fig.patches.append(FancyBboxPatch(
                    (x, ty), w, tl_h, boxstyle="round,pad=0.004,rounding_size=0.009",
                    transform=fig.transFigure, fc=wash if done else TILE, ec="none"))
                fig.text(x + w / 2, ty + tl_h * 0.38, str(txt)[:16],
                         color=band if done else MUT, fontsize=_fs(12.5, True),
                         ha="center", fontweight="bold" if done else "normal")
        if rows:
            _draw_cells(fig, rows, (0.03, bot, 0.94, tiles_h), (13, 20, 13), square=True)
        _footer(fig, now, square=True)
        return _save(fig, "kakao_card_status.png")
    except Exception as e:
        print(f"::warning title=카드 실패::status: {e} — 텍스트 폴백")
        return None


# ── 미리보기 CLI ──────────────────────────────────────────────────────────
# 디스코드로 쏘지 않고 편성을 눈으로 검토하기 위한 진입점.
#   python scripts/discord_card.py                     # 지금 시각의 프로필
#   python scripts/discord_card.py kr_session          # 특정 프로필
#   python scripts/discord_card.py all -o out/         # 6종 전부 파일로
#   python scripts/discord_card.py all -o out/ --square  # 카톡용 정사각 캔버스
def _preview(argv):
    import json
    import shutil
    args = [a for a in argv if not a.startswith("-")]
    out = ""
    if "-o" in argv:
        out = argv[argv.index("-o") + 1] if len(argv) > argv.index("-o") + 1 else ""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "data.json"), encoding="utf-8") as f:
        d = json.load(f)
    now = datetime.datetime.now()
    want = args[0] if args else profile_for(now=now)
    shape = "square" if "--square" in argv else "wide"
    keys = list(PROFILES) if want == "all" else [want]
    for k in keys:
        if k not in PROFILES:
            print(f"알 수 없는 프로필: {k} — 가능: {', '.join(PROFILES)}")
            return 1
        # 정사각 히어로 패널은 인트라데이가 재료다 — 미리보기는 네트워크를 타지 않으므로
        # 30일 일봉으로 대신 채운다(레이아웃 확인용). 운영 값은 _build_kakao_card 가 넘긴다.
        hero = None
        if shape == "square":
            hk = HERO.get(k, "")
            hc = (_CATALOG.get(hk) or ("", "", "indices"))[2]
            vs = _hist(d, hc, hk)
            base = datetime.datetime(now.year, now.month, now.day)
            hero = ([base + datetime.timedelta(days=i) for i in range(len(vs))],
                    vs, (vs[0] if vs else None), "일봉 30D")
        p = board(d, now, profile=k, shape=shape, hero=hero)
        if not p:
            print(f"{k}: 렌더 실패")
            return 1
        if out:
            os.makedirs(out, exist_ok=True)
            p2 = os.path.join(out, f"board_{k}_{shape}.png")
            shutil.copy(p, p2)
            p = p2
        print(f"{k:12} → {p}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_preview(sys.argv[1:]))
