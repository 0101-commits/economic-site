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
SQ_MIN_FS = 13.0
# 타일 행(y0=0.775, pad 0.004 → 실하단 0.771)과 그 아래 차트 축(상단 0.732) 사이의
# 라벨 띠 한가운데. 여기에 va="center" 로 놓아야 글자가 타일 안으로 파고들지 않는다.
SEC_LAB_Y = 0.7515

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


# ── 알림 표기 단일 원천(2026-09-24 알림 개편 A8·B6) ─────────────────────────
# 카드·카톡 본문·디스코드 필드가 기간·기준일·휴장을 각자 만들던 것을 여기 한 곳으로 모은다.
# 한 통 안에서 두 형식(「9/14~9/17」과 「09-17~09-23」)이 보이면 그 자리가 버그다.
# 이 모듈은 matplotlib 을 지연 로드하므로 send_kakao_digest 가 가볍게 import 할 수 있다.
def _as_date(s):
    try:
        return datetime.datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def stale_tag(s, now):
    """기준일 꼬리표 — 오늘이면 "", 어제면 "·전일", 그 전이면 "·M/D". 파싱 실패는 ""."""
    d = _as_date(s)
    if d is None or now is None:
        return ""
    days = (now.date() - d).days
    if days <= 0:
        return ""
    return "·전일" if days == 1 else f"·{d.month}/{d.day}"


def period_label(a, b):
    """기간 표기 "M/D~M/D" — date·datetime·'YYYY-MM-DD' 문자열 모두 받는다."""
    def md(x):
        x = x if hasattr(x, "month") else _as_date(x)
        return f"{x.month}/{x.day}" if x else "?"
    return f"{md(a)}~{md(b)}"


def week_period(now):
    """주간 리포트 기간 — 발송일 포함 7일(now-6일 ~ now). 본문 제목·카드가 같이 쓴다."""
    return period_label(now - datetime.timedelta(days=6), now)


def kr_closed(d, now):
    """오늘 한국장이 휴장이면 직전 영업일('YYYY-MM-DD'), 아니면 "".

    marketCalendarKr 는 fetch 가 매일 만든다(토스 영업일 달력). 주말은 달력이 없어도
    휴장이 자명하지만 여기서는 '달력이 오늘을 휴장이라고 말한 경우'만 본다 — 달력이
    어제 것이면(수집 정체) 판정하지 않는다. 모르면 비운다."""
    cal = (d or {}).get("marketCalendarKr") or {}
    today = cal.get("today") or {}
    if now is None or str(today.get("date") or "") != now.strftime("%Y-%m-%d"):
        return ""
    if today.get("open") is not False:
        return ""
    return str((cal.get("previousBusinessDay") or {}).get("date") or "")


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


def _fmt_diff(v):
    """변화폭 — 100 이상이면 정수(「+2,300」), 아니면 소수 1~2자리. 「+2,300.0」 방지."""
    return f"{v:+,.0f}" if abs(v) >= 100 else f"{v:+,.2f}" if abs(v) < 10 else f"{v:+,.1f}"


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
    '보합여부'를 돌려주는 이유: 호출측이 bgc != TILE 로 보합을 되짚던 색 비교를 없애기 위함.

    ⚠ 하한은 0.30 → 0.10 이다(2026-09-18). 방향은 화살표가 이미 말하므로 색이 할 일은
    크기 전달뿐인데, 하한 0.30 은 0.16% 짜리 움직임도 곧장 뚜렷한 분홍으로 칠해 상승장에
    6칸이 '붉은 벽'이 됐다 — 무엇이 큰 움직임인지가 색에서 사라진 상태였다. 0.10 이면
    0.2% 는 거의 흰색이고 2% 넘는 칸만 한눈에 들어온다(포화점 sat 은 그대로)."""
    if c is None or abs(c) < 0.05 * (sat / 3.0):
        return TILE, MUT, True
    base = UP if c > 0 else DN
    a = min(0.95, 0.10 + abs(c) / float(sat) * 0.85)
    rgb = tuple(int(base[i:i + 2], 16) for i in (1, 3, 5))
    bgc = tuple(int(BG[i:i + 2], 16) for i in (1, 3, 5))
    mix = tuple(int(x * a + y * (1 - a)) for x, y in zip(rgb, bgc))
    return "#%02x%02x%02x" % mix, INK, False


def _fs(size, square=False):
    """정사각 카드의 글자 하한(SQ_MIN_FS) 적용 — 축소 말풍선 판독 규격."""
    return max(float(size), SQ_MIN_FS) if square else float(size)


def _text_w(fig, s, fontsize, weight="normal"):
    """s 를 그렸을 때 차지하는 가로 폭(figure 폭 대비 비율 0~1). Agg 렌더러로 실측."""
    if not s:
        return 0.0
    t = fig.text(0, 0, str(s), fontsize=fontsize, fontweight=weight)
    try:
        return t.get_window_extent(renderer=fig.canvas.get_renderer()).width / fig.bbox.width
    except Exception:
        # 렌더러를 못 얻는 환경 — 한글 1자 ≈ 1em 가정의 보수적 근사(과대 추정 쪽).
        return len(str(s)) * (fontsize / 72.0) / fig.get_figwidth()
    finally:
        t.remove()


def _clip(fig, s, max_frac, fontsize, weight="normal"):
    """max_frac(figure 폭 비율) 안에 들어가게 뒤를 잘라 말줄임표를 붙인다.

    글자수(`[:N]`)로 자르면 한글·숫자·이모지·비율기호의 폭이 제각각이라 같은 N 이어도
    어떤 문구는 카드 밖으로 넘치고 어떤 문구는 옆 글자를 파고든다 — 2026-09-17 실측에서
    정사각 보드 6종의 제목↔보조가 최대 221px 겹쳤고, 마감 카드의 발동 종목 줄은 캔버스를
    159px 넘어갔다. 그래서 자르는 기준을 글자수가 아니라 '실제 렌더 폭'으로 바꾼다."""
    s = str(s or "")
    if not s or _text_w(fig, s, fontsize, weight) <= max_frac:
        return s
    lo, hi = 0, len(s)
    while lo < hi:                                    # 들어가는 최대 길이를 이분 탐색
        mid = (lo + hi + 1) // 2
        if _text_w(fig, s[:mid] + "…", fontsize, weight) <= max_frac:
            lo = mid
        else:
            hi = mid - 1
    return (s[:lo].rstrip() + "…") if lo else ""


def _head(fig, title, meta="", fs_t=20, fs_m=11.5, y=0.955, square=True):
    """카드 머리글 — 왼쪽 제목 + 오른쪽 보조를 한 줄에서 폭으로 나눠 쓴다.

    둘 다 같은 줄(0.03~0.97)을 쓰는데 종전엔 각자 글자수로만 잘라서 서로 파고들었다.
    제목에 최대 0.62 를 주고, 보조는 '제목이 실제로 쓴 폭'을 뺀 나머지만 쓴다."""
    fs_t, fs_m = _fs(fs_t, square), _fs(fs_m, square)
    t = _clip(fig, title, 0.62, fs_t, "bold")
    fig.text(0.03, y, t, color=INK, fontsize=fs_t, fontweight="bold")
    if meta:
        room = max(0.94 - _text_w(fig, t, fs_t, "bold") - 0.03, 0.0)   # 제목 뒤 남은 폭
        # 보조는 " · " 로 이어 붙인 조각들(MOVE · 오늘 일정)이다. 폭이 모자라면 글자를
        # 자르는 대신 뒤 조각을 통째로 버린다 — "오늘 미…" 처럼 반쯤 잘린 일정은
        # 정보가 아니라 노이즈고, 앞 조각(MOVE)까지 밀려 나가게 만든다.
        segs = [s for s in str(meta).split(" · ") if s]
        m = ""
        while segs:
            cand = " · ".join(segs)
            if _text_w(fig, cand, fs_m) <= room:
                m = cand
                break
            segs.pop()
        if not m:                                     # 첫 조각조차 안 들어가면 그것만 줄여서
            m = _clip(fig, str(meta).split(" · ")[0], room, fs_m)
        if m:
            fig.text(0.97, y + 0.003, m, color=MUT, fontsize=fs_m, ha="right")


def _sq_fig(plt, title, meta=""):
    """정사각 카드 공통 골격 1단 — 1080×1080 캔버스 + 제목줄(+ 우측 보조)."""
    fig = plt.figure(figsize=SQ, dpi=SQ_DPI)
    fig.patch.set_facecolor(BG)
    _head(fig, title, meta)
    return fig


def _sq_panel(fig, box, ys, xs=None, prev=None, up=True, label="", right="",
              lines=(), src="", area=True, fmt=None):
    """정사각 카드 공통 골격 3단 — 주 영역(선 그래프 패널). 재료가 없으면 패널만 비고
    카드는 산다(사건형·지표형이 같은 패널을 쓴다).

    lines = [(값, 색, 라벨)] — 목표선·임계선·전일선처럼 수평 기준선. 첫 원소가 None 인
    항목은 건너뛴다. up = 상승 방향(끝점 색). fmt = 축·기준선 값 표기 함수(기본 _fmt) —
    금리 패널은 '4.63%' 처럼 단위가 달라서 호출측이 바꿔 넘긴다."""
    ax = fig.add_axes(box)
    ax.set_facecolor(TILE)
    col = UP if up else DN
    f = fmt or _fmt
    if label:
        ax.text(0.012, 1.045, label, transform=ax.transAxes, color=MUT,
                fontsize=_fs(16, True), va="bottom")
    if right:
        ax.text(1.0, 1.045, right, transform=ax.transAxes,
                color=_txt_color(up), fontsize=_fs(17, True),
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
            # 채움은 전일선을 기준으로 위아래를 나눈다. 종전엔 패널 바닥부터 한 색으로
            # 채워서, 전일선 아래로 빠진 구간까지 상승처럼 보였다(2026-09-17 지적).
            if prev:
                _x = range(len(vals))
                ax.fill_between(_x, vals, prev, where=[v >= prev for v in vals],
                                color=UP, alpha=0.11, interpolate=True)
                ax.fill_between(_x, vals, prev, where=[v < prev for v in vals],
                                color=DN, alpha=0.11, interpolate=True)
            else:
                ax.fill_between(range(len(vals)), vals, floor, color=col, alpha=0.10)
        # 세로축 — 종전엔 눈금이 아예 없어서(set_yticks([])) 그래프 높이가 무엇을
        # 뜻하는지 알 수 없었고, 값 없는 가로 격자선만 남아 '기준이 있어 보이지만
        # 읽을 수 없는' 상태였다. 전일·고가·저가 셋을 패널 안 왼쪽에 값과 함께 적는다.
        #
        # 자리는 데이터 단위가 아니라 '화면 픽셀'로 다툰다 — 장 초반처럼 고가와 전일이
        # 붙어 있는 날엔 두 라벨이 겹치는데, 겹침 여부는 값 차이가 아니라 글자 높이가
        # 정하기 때문이다. 우선순위는 전일 > 고 > 저(전일선이 방향 판단의 기준선이다).
        _fs_ax = _fs(14, True)
        _y0, _y1 = ax.get_ylim()
        _span = (_y1 - _y0) or 1.0
        # 2.3배인 이유: 전일 라벨은 선 위(va=bottom), 고가 라벨은 선 아래(va=top)로
        # 자라서 서로 마주 본다 — 필요한 간격은 한 줄 높이가 아니라 두 줄 높이다.
        _minfrac = (_fs_ax / 72.0 * fig.dpi * 2.3) / max(box[3] * fig.bbox.height, 1.0)
        _taken = []

        def _axlabel(v, text, va, color, dashed):
            frac = (v - _y0) / _span
            if any(abs(frac - t) < _minfrac for t in _taken):
                return
            _taken.append(frac)
            ax.axhline(v, color=color, lw=1.2 if dashed else 0.9,
                       ls="--" if dashed else "-")
            # 라벨엔 패널색 배경을 깐다 — 시세가 그 자리를 지나면 글자 위로 선이 그어져
            # 숫자를 못 읽는다(2026-09-17 실측). 배경을 깔면 글자 양끝 여백은 bbox 가
            # 맡으므로 앞뒤 공백을 넣지 않는다(공백까지 배경이 늘어나 패널 밖으로 샜다).
            ax.text(0.008, v, text, color=color, fontsize=_fs_ax, va=va,
                    bbox=dict(facecolor=TILE, edgecolor="none", pad=1.0),
                    transform=ax.get_yaxis_transform())

        if prev:
            _axlabel(prev, _L("전일 ", "prev ") + f(prev), "bottom", FAINT, True)
        _axlabel(max(vals), _L("고 ", "hi ") + f(max(vals)), "top", FAINT, False)
        _axlabel(min(vals), _L("저 ", "lo ") + f(min(vals)), "bottom", FAINT, False)
        for v, lcol, llab in lines:
            if v is None:
                continue
            ax.axhline(v, color=lcol, lw=1.6, ls="--")
            if llab:
                ax.text(0.99, v, llab, color=lcol, fontsize=_fs(13, True),
                        ha="right", va="bottom", fontweight="bold",
                        bbox=dict(facecolor=TILE, edgecolor="none", pad=1.0),
                        transform=ax.get_yaxis_transform())
        ax.plot(len(vals) - 1, vals[-1], "o", color=col, ms=7)
        ticks = sorted({0, len(vals) // 3, 2 * len(vals) // 3, len(vals) - 1})
        ax.set_xticks(ticks)
        if xs:
            xfmt = "%m/%d" if (xs[-1] - xs[0]).days >= 1 else "%H:%M"
            ax.set_xticklabels([xs[t].strftime(xfmt) if t < len(xs) else "" for t in ticks],
                               color=FAINT, fontsize=_fs(14, True))
        else:
            ax.set_xticklabels([""] * len(ticks))
        if src:
            ax.text(0.012, 0.03, src, transform=ax.transAxes, color=FAINT,
                    fontsize=_fs(11, True))
    else:
        ax.text(0.5, 0.5, _L("시세 데이터 없음", "no intraday data"), transform=ax.transAxes,
                color=FAINT, fontsize=_fs(13, True), ha="center", va="center")
        ax.set_xticks([])
    ax.set_yticks([])
    # 값 없는 격자선은 지웠다 — 눈금이 없는 격자는 기준이 있는 것처럼 보이게만 한다.
    # 축 역할은 위에서 그린 고가·저가·전일 세 선이 값과 함께 맡는다.
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    return ax


def _footer(fig, now, extra="", square=False):
    fig.text(0.03, 0.022, _L(f"시세 {now.strftime('%m/%d %H:%M')} 기준 · 무료 시세 지연 가능",
                             f"as of {now.strftime('%m/%d %H:%M')} KST · free quotes may lag") + extra,
             color=FAINT, fontsize=_fs(13, square))
    fig.text(0.97, 0.022, "econ dashboard →", color=FAINT,
             fontsize=_fs(13, square), ha="right")


def _save(fig, name):
    plt = _STATE["plt"]
    path = os.path.join(tempfile.gettempdir(), name)
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return path


def _us_yield_line(d, now=None):
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
        # 장단기(10Y−2Y) — 경기 국면을 읽는 기본 재료인데 어느 알림에도 없었다(2026-09-24 B10).
        two = [r for r in (by.get("2Y") or []) if _f(r.get("value")) is not None]
        ten = [r for r in (by.get("10Y") or []) if _f(r.get("value")) is not None]
        if two and ten:
            parts.append(_L("장단기 ", "10s2s ") + f"{(_f(ten[-1]['value']) - _f(two[-1]['value'])) * 100:+.0f}bp")
        # 기준일 — FRED 는 1~2영업일 늦다. 날짜 없이 '■0bp'를 보이면 '안 움직였다'로 읽힌다.
        tag = stale_tag(ten[-1].get("date"), now) if (ten and now) else ""
        return (_L(f"미국채{tag}  ", "UST  ") + "  ·  ".join(parts)) if parts else ""
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
# 편성은 3열 9타일에서 2열 6타일로 줄었다(2026-09-17 사용자 결정 — 닛케이·달러인덱스·금 제외).
# 이유는 취향이 아니라 판독이다: 카톡 말풍선은 1080px 카드를 약 270px 로 줄여 보여줘서
# 축소비가 4배다. 9타일 편성에서는 카드 글자의 74~90%가 읽히는 크기(화면 9px)를 밑돌았다.
# 타일을 6개로 줄이면 한 칸이 1.5배 넓어지고 글자를 1.6배로 키울 수 있다 — 빠진 지표는
# 카드 대신 대시보드 버튼·드롭다운이 받는다.
PROFILES = {
    "kr_session": {                                   # 09~15시 — 장중
        # 6타일 → 4타일(2026-09-21 기획안 P2). 한국 장중에 실제로 움직이는 것은 네 개뿐이고,
        # 나머지 두 칸을 채우려다 한 칸이 좁아져 글자가 작아졌다. 달러-엔 자리에 닛케이를
        # 넣은 것은 실측 때문이다 — 코스피와 동시간 상관이 닛케이 +0.765 로 가장 높다.
        "title": "장중",
        "rows": [["KOSPI", "KOSDAQ"],
                 ["USDKRW", "Nikkei"]],
        "spark": ["KOSPI", "SP500", "USDKRW"],
        "caption": "us_curve",
    },
    "pre_kr": {                                       # 07~08시 — 미국장 마감 정산
        "title": "개장 전",
        "rows": [["SP500", "NASDAQ"],
                 ["SOX", "USDKRW"],
                 ["US10Y", "WTI"]],
        "spark": ["SP500", "NASDAQ", "USDKRW"],
        "caption": "us_curve",
    },
    "kr_close_eu": {                                  # 16~18시 — 마감 확정 + 유럽 개장
        # 상하이종합을 닛케이로 교체(2026-09-21 기획안 D3). 상하이는 코스피와 동시간
        # 상관이 +0.525 이고 전일→당일 예측력은 −0.10 으로 사실상 없다. 게다가 이 슬롯은
        # 코스피가 이미 마감(15:30)한 뒤라 그 시간에 상하이 숫자로 할 수 있는 일이 없다.
        # 닛케이는 같은 시간대에 거래되고 동시간 상관이 +0.765 로 가장 높다.
        "title": "마감·유럽",
        "rows": [["KOSPI", "Nikkei"],
                 ["USDKRW", "USDJPY"],
                 ["Copper", "WTI"]],
        "spark": ["KOSPI", "USDKRW", "SP500"],
        "caption": "us_curve",
    },
    "us_pre": {                                       # 19~21시 — 금리·달러 중심
        "title": "미국 개장 전",
        "rows": [["US10Y", "KR10Y"],
                 ["EU10Y", "USDKRW"],
                 ["EURUSD", "Copper"]],
        "spark": ["US10Y", "USDKRW", "Copper"],
        "caption": "us_curve",
    },
    "us_open": {                                      # 22시 — 미국 개장
        "title": "미국 장중",
        "rows": [["SP500", "NASDAQ"],
                 ["SOX", "USDKRW"],
                 ["US10Y", "WTI"]],
        "spark": ["SP500", "NASDAQ", "USDKRW"],
        "caption": "us_curve",
    },
    "weekend": {                                      # 주말·공휴일 11·17시
        "title": "주말",
        "rows": [["USDKRW", "USDJPY"],
                 ["WTI", "Copper"],
                 ["US10Y", "KR10Y"]],
        "spark": ["USDKRW", "SP500", "WTI"],
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
# 평범한 날의 기본값이다. 이례적인 날은 아래 anomaly() 가 고른 자산이 이 자리를 가져간다.
HERO = {"kr_session": "KOSPI", "pre_kr": "SP500", "kr_close_eu": "KOSPI",
        "us_pre": "US10Y", "us_open": "SP500", "weekend": "USDKRW"}

# 주인공을 바꿀 만큼 이례적이라고 볼 하한. 타일 배지(1.5σ)보다 높게 잡는다 —
# 배지는 '눈길을 끄는 정도'지만 주인공 교체는 '오늘 카드가 무엇에 관한 것인가'를
# 바꾸는 일이라 더 확실할 때만 한다. 2.0σ 는 정규분포 기준 상위 4.6%다.
ANOMALY_MIN_Z = 2.0


def shown_keys(prof, hero_key=None):
    """카드가 실제로 보여 주는 지표 키 — 히어로 먼저, 그다음 타일(좌→우·위→아래).

    알림 링크 목록의 단일 원천이다. 링크가 카드와 **같은 순서·같은 구성**이어야
    "사진에서 본 그 칸"을 목록에서 눈으로 찾을 수 있다. 카드에 없는 지표를 목록에
    섞으면(종전 드롭다운은 _ASSETS 16종 전부였다) 사진과 목록이 다른 것을 말한다.
    스파크라인은 캡션 영역의 보조선이라 제외한다 — 칸으로 보이지 않는다."""
    out, seen = [], set()
    for k in ([hero_key] if hero_key else []) + [k for row in (prof.get("rows") or []) for k in row]:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _stale_fx(cat, hist, today=None):
    """환율 일봉이 KST 오늘 것이 아니면 True — 주인공 후보에서 뺀다.

    야후 환율의 하루는 UTC 기준이라 KST 09시에야 넘어간다. 그 전(07·09시 슬롯)의 등락률은
    **어제 한국 장중에 이미 알린 움직임**인데, 종전엔 그걸로 또 주인공을 바꿔 원달러 카드가
    다섯 통 연속 나갔다(2026-09-22 12·19·22시 → 09-23 07·09시 실측). 지수는 07시의 간밤
    미국장이 새 소식이라 이 규칙을 적용하지 않는다."""
    if cat != "fx" or not hist:
        return False
    today = today or datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d")
    return str(hist[-1].get("date") or "") < today


def anomalies(d, keys, min_z=ANOMALY_MIN_Z):
    """이례적으로 움직인 자산 전부 → [(키, z)] |z| 내림차순. 없으면 [].

    주인공은 1등 하나지만, '오늘 이례 2건'처럼 몇 건인지는 말해 줘야 한다 —
    하나만 보여주면 그날이 한 자산의 문제인지 시장 전체의 문제인지 구별되지 않는다."""
    out = []
    for key in keys:
        ko, en, cat = _CATALOG.get(key, (key, key, "indices"))
        _price, chg = _node(d, cat, key)
        if chg is None or cat not in ("indices", "fx", "commodities"):
            continue
        hist = ((d.get("history") or {}).get(cat) or {}).get(key)
        if not isinstance(hist, list) or _stale_fx(cat, hist):
            continue
        try:
            import volatility as vol
            z = vol.zscore(chg, [h.get("close") for h in hist], exclude_last=False)
        except Exception:                                    # noqa: BLE001
            continue
        if z is not None and abs(z) >= min_z:
            out.append((key, z))
    out.sort(key=lambda t: -abs(t[1]))
    return out


def anomaly(d, keys, min_z=ANOMALY_MIN_Z):
    """그날 가장 이례적으로 움직인 자산 → (키, z) 또는 None.

    keys 안에서만 고른다 — 호출측이 '차트를 그릴 수 있는 것'만 넘기기 때문이다
    (인트라데이 심볼이 없는 키를 주인공으로 뽑으면 빈 패널이 된다).
    금리(bp)·macro 는 일봉 이력이 없어 z 를 못 내므로 자연히 빠진다."""
    best = None
    for key in keys:
        ko, en, cat = _CATALOG.get(key, (key, key, "indices"))
        _price, chg = _node(d, cat, key)
        if chg is None or cat not in ("indices", "fx", "commodities"):
            continue
        hist = ((d.get("history") or {}).get(cat) or {}).get(key)
        if not isinstance(hist, list) or _stale_fx(cat, hist):
            continue
        try:
            import volatility as vol
            z = vol.zscore(chg, [h.get("close") for h in hist], exclude_last=False)
        except Exception:                                    # noqa: BLE001
            continue
        if z is None or abs(z) < min_z:
            continue
        if best is None or abs(z) > abs(best[1]):
            best = (key, z)
    return best


def focus_all(d, prof, pkey, allowed=None):
    """focus_of 와 같은 후보 풀에서 이례 자산 **전부** → [(키, z)]. 없으면 []."""
    static = HERO.get(pkey) or ((prof.get("rows") or [[None]])[0] or [None])[0]
    pool = [k for row in (prof.get("rows") or []) for k in row]
    pool += list(prof.get("spark") or [])
    if static:
        pool.append(static)
    seen, cands = set(), []
    for k in pool:
        if k in seen or (allowed is not None and k not in allowed):
            continue
        seen.add(k)
        cands.append(k)
    return anomalies(d, cands)


# ── 시장 전체 이례 판정(2026-09-24 알림 개편 B2) ─────────────────────────────
# anomalies() 는 '주인공 후보'라 인트라데이를 그릴 수 있는 카드 키만 본다. 그런데 제목·헤더
# 배지가 말해야 하는 것은 '오늘 시장에서 무엇이 평소와 달랐나'다 — 9/24 에 MOVE(채권
# 변동성)가 +21.5% 뛰었는데 카드 키가 아니어서 알림은 '이례 0건'이었다. 여기선 심리·금리를
# 더해 본다. 주인공 선정(pick_focus)은 종전대로 anomalies() 를 쓴다(빈 패널 방지).
# (sentiment 키, 카드 이름, 영문, 제목용 짧은 이름)
_SENT_Z = {"MOVE": ("move", "채권변동성 MOVE", "bond vol MOVE", "채권변동성"),
           "VKOSPI": ("vkospi", "VKOSPI", "VKOSPI", "VKOSPI")}
_YIELD_Z = ("US10Y", "KR10Y")
Z_WINDOW = 250
Z_MIN_SAMPLES = 60


def _sd(xs):
    import statistics
    xs = [x for x in xs if x is not None][-Z_WINDOW:]
    return statistics.pstdev(xs) if len(xs) >= Z_MIN_SAMPLES else None


def _fresh(asof, now):
    """기준일이 오늘·어제면 True — 그보다 묵은 값의 '오늘 변화'는 이례 판정에 넣지 않는다."""
    dd = _as_date(asof)
    return dd is not None and now is not None and (now.date() - dd).days <= 1


def _extra_z(d, key, now):
    """심리·금리 한 지표 → (z, 등락 문자열) 또는 None."""
    if key in _SENT_Z:
        n = ((d.get("sentiment") or {}).get(_SENT_Z[key][0])) or {}
        chg, hist = _f(n.get("change")), n.get("history") or {}
        if chg is None or not isinstance(hist, dict) or not _fresh(n.get("as_of"), now):
            return None
        vs = [_f(hist[k]) for k in sorted(hist)]
        vs = [v for v in vs if v]
        sd = _sd([(b / a - 1) * 100 for a, b in zip(vs, vs[1:]) if a])
        return (chg / sd, f"{chg:+.1f}%") if sd else None
    if key in _YIELD_Z:
        _p, bp = _node(d, "yield", key)
        asof = tile_asof(d, "yield", key, now)
        if bp is None or (asof is not None and not _fresh(asof, now)):
            return None
        vs = _yield_series(d, key)
        sd = _sd([(b - a) * 100 for a, b in zip(vs, vs[1:])])
        return (bp / sd, f"{bp:+.0f}bp") if sd else None
    return None


def market_anomalies(d, keys=(), now=None, min_z=ANOMALY_MIN_Z):
    """카드 키 + 심리(MOVE·VKOSPI) + 금리(미·한 10Y) → [(키, z, 한글 이름, 등락, 영문 이름)].

    이름은 한글로 돌려준다 — 제목·본문은 폰트와 무관한 텍스트다. 카드(그림)만 한글 폰트가
    없을 때 영문으로 내려가야 하므로 anomaly_badge(card=True) 가 그때 영문을 고른다.
    (2026-09-24 실측: 텍스트 경로가 _L 을 타서 제목에 'bond vol MOVE' 가 들어갈 뻔했다.)"""
    now = now or datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    out = []
    for key, z in anomalies(d, [k for k in keys if k not in _YIELD_Z], min_z=min_z):
        ko, en, cat = _CATALOG.get(key, (key, key, "indices"))
        out.append((key, z, ko, _chgtxt_tile(cat, _node(d, cat, key)[1]), en))
    for key in list(_SENT_Z) + list(_YIELD_Z):
        r = _extra_z(d, key, now)
        if r and abs(r[0]) >= min_z:
            ko, en = (_SENT_Z[key][1:3] if key in _SENT_Z else _CATALOG[key][:2])
            out.append((key, r[0], ko, r[1], en))
    out.sort(key=lambda t: -abs(t[1]))
    return out


def repeat_hit(key, z, seen, esc=0.5):
    """오늘 같은 방향으로 이미 알렸고 그 뒤 |z| 가 esc 이상 커지지 않았으면 True.

    MOVE·VKOSPI 는 하루 한 값이라 막지 않으면 여섯 통 제목이 전부 같은 이례로 시작한다 —
    9/23 에 주인공(달러-원) 재탕을 막은 규칙을 제목·헤더 배지에도 그대로 쓴다."""
    prev = (seen or {}).get(key)
    return (prev is not None and z is not None and (prev > 0) == (z > 0)
            and abs(z) < abs(prev) + esc)


def anomaly_badge(hit, card=True, short=False):
    """이례 한 조각. card=True → 카드 헤더(폰트 없으면 영문), short=True → 제목용 짧은 형식.

    카드: "채권변동성 MOVE +21.5% 평소의 4.0배" / 제목: "채권변동성 +21.5%(평소 4.0배)"."""
    key, z, ko, chg, en = hit
    if short:
        nm = _SENT_Z[key][3] if key in _SENT_Z else ko
        return f"{nm} {chg}(평소 {abs(z):.1f}배)"
    if card and not _STATE.get("ko"):
        return f"{en} {chg} {abs(z):.1f}x usual"
    return f"{ko} {chg} 평소의 {abs(z):.1f}배"


def _draw_cells(fig, grid, box, fs, square=False, note_inline=False):
    """타일 격자를 box=(x0, y0, w, h) figure 좌표에 그린다. fs=(라벨, 값, 등락) 폰트.

    grid = [[cell, …], …], cell = (라벨, 값 문자열, 우하단 문자열, 등락값|None, 포화폭).
    등락값은 색·잉크 결정에만 쓴다(문자열은 호출측이 이미 만들어 넘긴다) — 그래서
    카탈로그 지표(_draw_tiles)와 사건 타일(종목·목표가·상태)이 같은 코드로 그려진다.

    글자 위치는 타일 높이 비율로 잡는다 — 캔버스(가로 10×7 / 정사각 1:1)마다 타일
    높이가 달라도 같은 코드로 겹침 없이 배치되게. square=True 면 폰트에
    SQ_MIN_FS 하한을 걸어 축소 말풍선에서 읽히게 한다.

    note_inline=True 면 우하단 문자열을 값과 같은 줄 오른쪽에 붙인다(2줄 타일).
    세 줄을 쌓으면 값 글자를 키울 자리가 없어 등락률이 가장 작아지는데, 등락률은
    값 다음으로 중요한 숫자다. 지표 타일처럼 우하단이 '등락률'인 카드가 이걸 쓰고,
    우하단이 단위·기준일(「억원 · 09-17 (잠정)」)인 카드는 세 줄을 유지한다 —
    긴 문자열을 값 옆에 붙이면 폭이 모자라 기준일이 잘려 나간다."""
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
            # badge 는 나중에 붙은 6번째 필드 — 옛 5튜플도 그대로 받는다.
            label, val, note, chg, sat = cell[:5]
            badge = cell[5] if len(cell) > 5 else ""
            x = gx0 + c_ * gw / cols
            y = gy0 + (rows - 1 - r_) * gh / rows
            w, h = gw / cols - 0.008, gh / rows - 0.015
            bgc, ink, _flat = _tile_color(chg, sat)
            fig.patches.append(FancyBboxPatch(
                (x, y), w, h, boxstyle="round,pad=0.004,rounding_size=0.009",
                transform=fig.transFigure, fc=bgc, ec="none"))
            # 한 칸 안에서 쓸 수 있는 가로 폭(좌 0.013 / 우 0.011 여백). 종목명·기간
            # 문자열은 길이가 제각각이라 글자수로 자르면 타일 밖으로 삐져나가 옆 칸
            # 글자와 겹친다 — 실제 렌더 폭으로 자른다.
            iw = max(w - 0.024, 0.0)
            f_l, f_p, f_c = fs_l, fs_p, fs_c
            inline = bool(note_inline and note)
            if inline and (_text_w(fig, val, f_p, "bold")
                           + _text_w(fig, note, f_c, "bold") + 0.012) > iw:
                # 한 줄에 값과 등락이 같이 안 들어가는 좁은 칸(3열 이상)은 세 줄로 내린다.
                # 세 줄이면 값과 등락이 각자 한 줄을 쓰므로 폭 때문에 글자를 줄일 이유가
                # 없다 — 종전엔 여기서 0.85/0.8 로 줄여, 히어로 등락률이 14.4pt(축소 화면
                # 7.5px)까지 내려가 판독 하한 9px 아래로 떨어졌다(2026-09-18 게이트 적발).
                # 세로가 모자란 칸에서만 줄인다(라벨+값+등락 3줄 높이 vs 칸 높이).
                inline = False
                need = (f_l + f_p + f_c) / 72.0 * fig.dpi * 1.35
                if need > h * fig.bbox.height:
                    sc = max(0.7, h * fig.bbox.height / need)
                    f_p, f_c = _fs(f_p * sc, square), _fs(f_c * sc, square)
            y_lab, y_val = (0.72, 0.30) if inline else (0.72, 0.36)
            # 라벨이 쓰는 폭 — badge 가 있으면 그만큼 줄여 둘이 겹치지 않게 한다.
            lab_w = iw
            if badge:
                bw = _text_w(fig, badge, f_c)
                lab_w = max(iw - bw - 0.010, 0.0)
                # 우상단 = 라벨과 같은 높이의 반대쪽 끝. 값·등락 자리를 건드리지 않는
                # 유일한 빈 자리다. 색은 타일 잉크(라벨과 동일) — 진한 배경 칸에서
                # FAINT 를 쓰면 대비가 무너져 읽히지 않는다(실측).
                fig.text(x + w - 0.011, y + y_lab * h, badge,
                         color=ink, fontsize=f_c, ha="right")
            fig.text(x + 0.013, y + y_lab * h, _clip(fig, label, lab_w, f_l),
                     color=ink, fontsize=f_l)
            if inline:
                fig.text(x + 0.013, y + y_val * h, val, color=INK,
                         fontsize=f_p, fontweight="bold")
                # 등락률은 값 바로 오른쪽에 붙인다 — 칸 오른쪽 끝에 고정하면 한 쌍의
                # 숫자를 읽는 데 시선이 칸 폭(가로 카드에서 750px)을 건넜다(2026-09-18).
                # 들어가는지는 위 폭 검사가 이미 봤다(안 들어가면 세 줄로 내려간다).
                fig.text(x + 0.013 + _text_w(fig, val, f_p, "bold") + 0.012,
                         y + y_val * h, note, color=ink, fontsize=f_c, fontweight="bold")
            else:
                fig.text(x + 0.013, y + y_val * h, _clip(fig, val, iw, f_p, "bold"),
                         color=INK, fontsize=f_p, fontweight="bold")
                if note:
                    fig.text(x + w - 0.011, y + 0.07 * h, _clip(fig, note, iw, f_c, "bold"),
                             color=ink, fontsize=f_c, fontweight="bold", ha="right")


def _cell(label, val, note="", chg=None, sat=3.0, badge=""):
    """자유 타일 한 칸 — 사건형·상태형 카드가 쓴다(카탈로그 비의존).

    badge = 칸 우상단의 작은 보조 표기(비어 있으면 안 그린다). 지표 타일은 여기에
    이례성(σ 배수)을 넣는다 — 값·등락률 자리를 건드리지 않고 '평소보다 큰가'를
    같은 칸 안에서 읽게 하려는 것(기획안 P2)."""
    return (str(label), str(val), str(note), chg, sat, str(badge))


# 우상단 σ 배지를 다는 하한. 이보다 평범한 움직임엔 아무것도 쓰지 않는다 — 모든 칸에
# 숫자를 하나 더 얹으면 '무엇이 이례적인가'가 다시 사라진다(타일 색과 같은 원리).
BADGE_MIN_Z = 1.5


def _tile_badge(d, cat, key, chg):
    """타일 우상단 배지 — "2.4σ" 또는 "". 이례성이 뚜렷할 때만 값을 돌려준다.

    σ 는 data.json 의 일봉 이력에서 구한다(indices·fx·commodities). 금리는 등락이
    bp 라 같은 이력에 없고, macro 는 이력 자체가 없어 배지를 달지 않는다 — 없는 값을
    지어내느니 칸을 비워 둔다."""
    if chg is None or cat not in ("indices", "fx", "commodities"):
        return ""
    hist = ((d.get("history") or {}).get(cat) or {}).get(key)
    if not isinstance(hist, list):
        return ""
    try:
        import volatility as vol
        z = vol.zscore(chg, [h.get("close") for h in hist], exclude_last=False)
    except Exception:                                    # noqa: BLE001
        return ""
    return f"{abs(z):.1f}σ" if z is not None and abs(z) >= BADGE_MIN_Z else ""


_KR_KEYS = ("KOSPI", "KOSDAQ")


def tile_asof(d, cat, key, now):
    """타일 값의 기준일('YYYY-MM-DD') — 발송 시점 값이면 None.

    두 경우만 날짜가 있다(2026-09-24 알림 개편 A3). ① 금리: yieldCurve 는 FRED·ECOS 일별이라
    라이브 오버레이(_liveTiles)가 없으면 1~2일 전 값이다 — 이틀 연속 같은 값이면 '■0bp'가
    되어 '안 움직였다'로 읽혔다. ② 한국 지수: 휴장일엔 직전 영업일 종가가 오늘 값처럼 나갔다.
    나머지는 apply_live_quotes 가 발송 시점 시세로 덮으므로 날짜를 달지 않는다."""
    if (d.get("_liveTiles") or {}).get(key):
        return None
    if cat == "yield":
        cc, tenor = _YIELD_KEY.get(key, (None, None))
        for se in (((d.get("yieldCurve") or {}).get(cc) or {}).get("series") or []):
            if se.get("tenor") == tenor:
                rows = [r for r in (se.get("data") or []) if _f(r.get("value")) is not None]
                return str(rows[-1].get("date")) if rows else None
        return None
    if key in _KR_KEYS:
        return kr_closed(d, now) or None
    return None


def _draw_tiles(fig, d, grid, box, fs, square=False, note_inline=True, now=None):
    """카탈로그 키 격자(편성표) → 셀 격자로 바꿔 _draw_cells 에 넘긴다.

    지표 타일의 우하단은 언제나 등락률이라 기본값이 note_inline=True 다.
    우상단에는 이례적인 칸에만 σ 배지가 붙는다(_tile_badge).
    기준일이 오늘이 아닌 칸은 라벨 끝에 「·9/22」를 붙인다(tile_asof) — 본문 심리 블록이
    쓰는 stale_tag 와 같은 함수라 카드와 본문의 꼬리표가 어긋나지 않는다."""
    cells = []
    for line in grid:
        row = []
        for key in line:
            ko, en, cat = _CATALOG.get(key, (key, key, "indices"))
            price, chg = _node(d, cat, key)
            tag = stale_tag(tile_asof(d, cat, key, now), now) if now else ""
            row.append(_cell(_L(ko, en) + tag, _fmt_tile(cat, price),
                             _chgtxt_tile(cat, chg), chg, _sat_of(cat),
                             _tile_badge(d, cat, key, chg)))
        cells.append(row)
    _draw_cells(fig, cells, box, fs, square=square, note_inline=note_inline)


def _meta_line(d, cal, badge=""):
    """헤더 우측 보조 — 리스크 지수(MRI) + MOVE 지수 + 오늘 일정.

    MRI 는 send_kakao_digest.load_mri 가 발송 직전에 _mri 로 주입한다(mer_signals.json
    은 별도 파일이라 여기서 직접 읽지 않는다). 지금까지 카드에 '오늘이 평소보다 위험한
    국면인가'를 말해 주는 숫자가 없었다(기획안 D8)."""
    head = []
    mri = d.get("_mri") or {}
    if _f(mri.get("score")) is not None:
        # MRI 는 0~100 점수라 변화도 '점'이다 — _chgtxt 를 쓰면 % 가 붙어 거짓이 된다.
        dl = _f(mri.get("delta"))
        dtxt = ""
        if dl is not None and abs(dl) >= 1:
            dtxt = f" {'▲' if dl > 0 else '▼'}{abs(dl):.0f}" + _L("(30일)", "(30d)")
        head.append((_L("리스크 ", "risk ") + f"{mri['score']:.0f}" + dtxt).strip())
    # MOVE 를 늘 싣던 자리(2026-09-24 A2) — 그날 가장 큰 이례 한 건으로 바꿨다. 고정 지표는
    # 매번 같은 자리에 같은 회색으로 있어 정작 이례적인 날에도 눈에 띄지 않았다.
    if badge:
        head.append(badge)
    if cal:
        head.append((_L("오늘 ", "today ") + cal).strip())
    return " · ".join(head)


def focus_of(d, prof, pkey, allowed=None):
    """그 슬롯 카드의 '주인공' 키 → (키, z|None). 이례적인 날엔 그날 자산으로 바뀐다.

    후보는 그 편성이 이미 보여주는 것(타일 + 추세) + 고정 주인공이다. 편성 밖 자산까지
    끌어오면 본문 수치와 그림이 따로 놀아서다. allowed 를 주면 그 안에서만 고른다 —
    호출측이 '인트라데이를 그릴 수 있는 키'를 넘긴다(없는 키를 뽑으면 빈 패널이 된다).

    반환 z 가 None 이면 평범한 날(고정 주인공)이라는 뜻이다."""
    static = HERO.get(pkey) or ((prof.get("rows") or [[None]])[0] or [None])[0]
    pool = [k for row in (prof.get("rows") or []) for k in row]
    pool += list(prof.get("spark") or [])
    if static:
        pool.append(static)
    seen, cands = set(), []
    for k in pool:
        if k in seen or (allowed is not None and k not in allowed):
            continue
        seen.add(k)
        cands.append(k)
    hit = anomaly(d, cands)
    return (hit[0], hit[1]) if hit else (static, None)


def focus_note(d, key, z, with_name=True):
    """주인공 교체 사유 한 줄. 평범한 날이면 "".

    with_name=True  → "달러-원 평소의 2.4배"  (추세 라벨 옆 — 무엇인지 밝혀야 한다)
    with_name=False → "평소의 2.4배"          (히어로 패널 라벨 — 이미 이름이 앞에 있다)"""
    if z is None or not key:
        return ""
    ko, en, _cat = _CATALOG.get(key, (key, key, "indices"))
    tail = _L(f"평소의 {abs(z):.1f}배", f"{abs(z):.1f}x usual")
    return f"{_L(ko, en)} {tail}" if with_name else tail


def board(d, now, cal="", slot=None, weekend=False, profile=None, shape="wide", hero=None,
          focus=None, seen=None):
    """카드 A — 시황 보드. 실패 시 None(호출측이 슬롯 차트로 폴백).

    focus=(키, z) — 그날의 주인공. 주면 정사각 히어로 패널과 가로 추세 첫 칸이 그것을
    따르고, 그 자산이 편성 타일에 없으면 마지막 타일과 바꿔 수치도 함께 보이게 한다.
    안 주면 focus_of 로 직접 고른다(미리보기·테스트 경로).

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
        fkey, fz = focus if focus else focus_of(d, prof, pkey)
        # 주인공이 편성 타일에 없으면 마지막 칸과 바꾼다 — 그림만 그 자산이고 숫자가
        # 없으면 "왜 이게 주인공인지"를 카드 안에서 확인할 수 없다. 원본 PROFILES 는
        # 건드리지 않는다(모듈 전역이라 다음 호출에 새어 나간다).
        prof = dict(prof)
        rows = [list(r) for r in (prof.get("rows") or [])]
        if fz is not None and fkey and rows and not any(fkey in r for r in rows):
            rows[-1][-1] = fkey
            prof["rows"] = rows
        if fz is not None and fkey:                      # 추세 첫 칸도 주인공으로
            sp = [k for k in (prof.get("spark") or []) if k != fkey]
            prof["spark"] = [fkey] + sp[:max(len(prof.get("spark") or []) - 1, 0)]
        # 휴장일 평일은 편성 이름을 '휴장'으로 — 카드가 어제 종가를 오늘 장중처럼 보이지 않게.
        if kr_closed(d, now) and now.weekday() < 5:
            prof["title"] = _L("휴장", "KR holiday")
        # 헤더 우측 배지 = 주인공이 아닌 것 중 가장 큰 이례 1건(주인공은 히어로가 이미 말한다).
        keys = [k for r in (prof.get("rows") or []) for k in r]
        hits = [h for h in market_anomalies(d, keys, now=now)
                if h[0] != fkey and not repeat_hit(h[0], h[1], seen)]
        badge = anomaly_badge(hits[0]) if hits else ""
        if shape == "square":
            # 히어로 라벨은 이미 자산명으로 시작한다 — 이름을 또 넣으면 두 번 나온다.
            return _board_square(plt, d, now, pkey, prof, cal, hero, fkey,
                                 focus_note(d, fkey, fz, with_name=False), badge=badge)
        return _board_wide(plt, d, now, prof, cal, focus_note(d, fkey, fz), badge=badge)
    except Exception as e:
        print(f"::warning title=디스코드 카드 실패::board({shape}): {e} — 기존 형식 폴백")
        return None


def _board_wide(plt, d, now, prof, cal, note="", badge=""):
    """가로 10×7 @160dpi — 디스코드 embed. 타일 격자 + 미국채 캡션 + 30일 추세 n개.
    note = 그날 주인공 사유 한 줄(있으면 제목 옆에 붙인다)."""
    grid = [r for r in prof["rows"] if r]
    cols = max(len(r) for r in grid)
    fs = (14, 21, 14) if cols <= 3 else (13, 17, 13)   # 3열이면 타일이 넓어 글자를 키운다
    fig = plt.figure(figsize=(10, 7.0), dpi=160)
    fig.patch.set_facecolor(BG)
    # 제목에서 '18시'를 뺐다(2026-09-24 A1) — 시각은 footer 가 분 단위로 이미 말하고,
    # 제목 자리는 '어느 시장 국면인가'(편성 이름)가 쓴다.
    _t = _L(f"{now.month}/{now.day} {prof['title']} 시황 보드",
            f"{now.month}/{now.day} Market Board · {prof['title']}")
    _head(fig, _t, _meta_line(d, cal, badge), fs_t=19, fs_m=11, y=0.945, square=False)
    _draw_tiles(fig, d, grid, (0.03, 0.44, 0.94, 0.46), fs, now=now)
    # 하단 캡션 — 미국채 1·5·10·30Y(사용자 지정 2026-08-20, 구 원자재 4종 대체).
    rest = _us_yield_line(d, now) if prof.get("caption") == "us_curve" else ""
    if rest:
        fig.text(0.03, 0.395, rest, color=MUT, fontsize=12)
    # 추세 첫 칸이 곧 오늘의 주인공이라 사유를 여기에 붙인다 — 제목에 붙이면
    # 폭을 넘겨 잘린다(실측: "달러-원 평소의 3...."로 끊겼다).
    _tl = _L("추세 30일", "30-day trend") + (f"   ·   오늘 {note}" if note else "")
    fig.text(0.03, 0.335, _tl, color=MUT, fontsize=12)
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


def _board_square(plt, d, now, pkey, prof, cal, hero, fkey=None, note="", badge=""):
    """정사각 1080×1080 @150dpi — 카카오 피드 한 통의 이미지.

    구성 = 타일 격자 + 히어로 인트라데이 1개(전 폭). 종전 카톡 이미지는 지표 2개짜리
    2패널이었다 — 타일이 편성을 담고, 카톡이 잘하던 '오늘 어떻게 움직였나'는 패널이
    하나로 합쳐지며 오히려 커진다. hero 재료가 없으면 패널만 비고 카드는 산다.

    미국채 캡션 줄(1·5·10·30Y 레벨+bp)은 뺐다 — 12pt 한 줄에 수치 8개라 말풍선
    축소(4배) 후 화면에서 6px 가 되어 어떤 표시 크기에서도 읽히지 않았다. 10Y 는
    편성 타일로 크게 남아 있고, 곡선 전체는 대시보드 버튼이 받는다."""
    grid = [r for r in prof["rows"] if r]
    fig = plt.figure(figsize=(7.2, 7.2), dpi=150)
    fig.patch.set_facecolor(BG)
    wd = "월화수목금토일"[now.weekday()]
    _t = _L(f"{now.month}/{now.day}({wd}) {prof['title']} 시황",
            f"{now.month}/{now.day} · {prof['title']}")
    _head(fig, _t, _meta_line(d, cal, badge))
    # 캡션이 빠진 자리를 타일이 가져간다 — 6타일(2열) × 늘어난 높이라야 글자가 커진다.
    _draw_tiles(fig, d, grid, (0.03, 0.50, 0.94, 0.43), (20, 30, 21), square=True, now=now)

    # 주인공은 호출측(board)이 고른다 — 이례적인 날엔 그날 자산이 온다.
    hkey = fkey or HERO.get(pkey) or (grid[0][0] if grid and grid[0] else None)
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
    # 히어로 패널은 공용 _sq_panel 을 쓴다 — 종전엔 같은 그림을 여기서 따로 그려서
    # 세로축·채움 방향 개선이 이 카드만 빠져 있었다. 금리는 '4.63%' 처럼 표기가
    # 달라서 포매터를 넘긴다.
    _up = (ys[-1] >= prev) if (ys and prev) else bool(ys) and ys[-1] >= ys[0]
    _sq_panel(fig, [0.03, 0.09, 0.94, 0.355], ys, xs=xs, prev=prev, up=_up,
              label=f"{_L(hko, hen)} {when}" + (f" · {note}" if note else "")
                    + (f" · {src}" if src else ""),
              right=f"{_fmt_tile(hcat, hprice)}  {_chgtxt_tile(hcat, hchg)}".strip(),
              fmt=lambda v: _fmt_tile(hcat, v))
    _footer(fig, now, square=True)
    return _save(fig, "kakao_card_board.png")


def _other(o):
    """동시 발동 종목 한 건 → (이름, 가격문자열, 등락률, 조건). 튜플 계약 단일 해석기."""
    if isinstance(o, (list, tuple)):
        o = list(o) + [None] * (4 - len(o))
        return str(o[0] or ""), str(o[1] or ""), _f(o[2]), str(o[3] or "")
    return str(o or ""), "", None, ""                 # 방어용 — 문자열이 들어오면 이름으로만


def stock_alert(hero, others, now, shape="wide", extra_tiles=None):
    """카드 E — 종목 알림(기획 5154773b P1). 좌 히어로(조건·현재가·등락·거래량) +
    우 30일 일봉 + 목표선(점선) + 발동점 도트, 하단 = 나머지 종목 1줄씩.

    hero = {name, cond, price, pct, target(없으면 None), closes(일봉 종가 리스트),
            vol_today, vol_prev, market}, others = [(이름, 가격문자열, 등락률, 조건)].
    재료는 전부 check_alerts.yahoo_snapshot 반환값 — 추가 API 호출 없음. 실패 시 None.

    ⚠ others 를 완성된 문장으로 받던 종전 계약은 폐기했다 — 카드가 그 문장을 공백으로
    되쪼개 타일에 넣는 바람에 등락률·조건·방향색이 잘려 나갔다(2026-09-18 실측).

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
        # 제목에 종목명을 박는다 — 조건 문구(cond)가 '목표가 78,000원' 처럼 조건만
        # 남으면서 히어로 종목 이름이 wide 카드 어디에도 없어졌다(2026-09-18).
        _hn = str(hero.get("name") or "")[:14]
        fig.text(0.03, base_y,
                 _L(f"{now.month}/{now.day} {now.strftime('%H:%M')} 종목 알림 · {_hn}",
                    f"{now.month}/{now.day} {now.strftime('%H:%M')} Stock Alert · {_hn}"),
                 color=INK, fontsize=18, fontweight="bold")
        # 좌 히어로 — 조건 문구·현재가·등락·거래량(전일比)
        body_top = base_y - 0.14 * (4.2 / hgt)
        fig.text(0.03, body_top, _clip(fig, hero.get("cond") or hero.get("name") or "", 0.38, 13),
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
                vs += _L(f" (전일 대비 {(vt / vp - 1) * 100:+.0f}%)", f" ({(vt / vp - 1) * 100:+.0f}% d/d)")
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
                        color=coltxt, fontsize=10.5, va="bottom",
                        bbox=dict(facecolor=TILE, edgecolor="none", pad=1.0))
            ax.plot(len(closes) - 1, closes[-1], "o", color=col, ms=6)
            ax.text(0.02, 0.94, _L("30일 일봉", "30-day daily"), transform=ax.transAxes,
                    color=MUT, fontsize=11, va="top")
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        # 하단 — 동시 발동 나머지 종목. 차트 아래라 폭은 카드 전체를 쓴다(종전 0.38 은
        # 히어로 칼럼 폭이라 이름·가격까지만 남기고 등락률·조건을 잘라 먹었다).
        for i, o in enumerate((others or [])[:4]):
            nm, px, opct, ocond = _other(o)
            txt = " ".join(x for x in (f"· {nm}", px, _chgtxt(opct), ocond and f"· {ocond}") if x)
            fig.text(0.03, (0.42 * (extra - i) + 0.42) / hgt, _clip(fig, txt, 0.94, 12.5),
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
    fig.text(0.03, 0.905, _clip(fig, hero.get("cond") or "", 0.94, _fs(15, True)),
         color=MUT, fontsize=_fs(15, True))

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
        cells[0].append(_cell(_L("거래량 전일 대비", "volume (d/d)"), _fmt_cnt(vt),
                              (_L(f"{vt / vp:.1f}배", f"{vt / vp:.1f}x")
                               if vp else ""), None))
    row2 = [_cell(str(l)[:10], str(v), str(n), c) for l, v, n, c in (extra_tiles or [])[:3]]
    # 동시 발동 나머지 종목 — 구조화 튜플을 그대로 타일로. 등락률(색 포함)과 조건이 남는다.
    for o in (others or [])[:3]:
        if len(row2) >= 3:
            break
        nm, px, opct, ocond = _other(o)
        lab = f"{nm} {ocond}".strip()
        # 한 칸에 들어가는 라벨은 11자 남짓이다(3열 × 13.5pt). 이름과 조건이 함께
        # 안 들어가면 조건을 버린다 — 이름이 잘리면('LG에너지솔…') 어느 종목인지
        # 알 수 없고, 조건은 발송 본문 줄과 피드 행이 이미 나른다.
        row2.append(_cell(nm if len(lab) > 11 else lab, px, _chgtxt(opct), opct))
    # 두 줄을 한 번에 그리면 글자 크기가 같아져, 셋째 칸 라벨('SK하이닉스 52주 신고가')이
    # 히어로 줄 기준 18pt 로 잘린다. 줄마다 따로 그려 아래 줄만 글자를 줄인다 — 기하는
    # 종전과 같다(전체 0.28 높이를 두 줄이 반씩).
    if row2:
        # 값 24pt 로는 히어로 칸('78,500' + '▲3.20%')이 한 줄에 안 들어가 세 줄로
        # 내려가고, 칸 높이가 3줄에 모자라 등락률이 14.4pt(축소 7.5px)까지 줄었다.
        # 21pt 면 한 줄로 들어가고 등락률이 18pt(9.4px)를 지킨다.
        _draw_cells(fig, [cells[0]], (0.03, 0.735, 0.94, 0.145), (18, 21, 18),
                    square=True, note_inline=True)
        _draw_cells(fig, [row2], (0.03, 0.60, 0.94, 0.14), (13.5, 19, 14),
                    square=True, note_inline=True)
    else:
        _draw_cells(fig, cells, (0.03, 0.60, 0.94, 0.28), (18, 24, 18), square=True,
                    note_inline=True)

    closes = [c for c in (hero.get("closes") or [])[-30:] if c is not None]
    _sq_panel(fig, [0.03, 0.085, 0.94, 0.44], closes, up=up,
              label=_L("30일 일봉", "30-day daily"),
              right=f"{_p(hero['price'])}  {_chgtxt(pct)}".strip(),
              lines=[(tgt, col, _L(f"목표 {_p(tgt)}", f"target {_p(tgt)}") if tgt else "")])
    _footer(fig, now, square=True)
    return _save(fig, "kakao_card_stock.png")


def _close_stack(movers, alerts_cnt, fired_names, cal):
    """마감 카드 우하 분면의 [(문구, 색)] — 특징주·발동 알림·내일 일정.

    figure 를 만들기 전에 불린다(줄이 하나도 없으면 캔버스를 낮춰야 하므로). 자르기는
    그리는 쪽에서 실제 렌더 폭(_clip)으로 한다 — 여기선 문구만 만든다."""
    stack = []
    gain, lose = (movers or ([], []))
    if gain or lose:
        stack.append((_L("특징주(코스피)", "KOSPI movers"), MUT))
        for r in (gain or [])[:3]:
            stack.append((f"▲ {str(r.get('name'))[:10]} {abs(_f(r.get('chg')) or 0):.1f}%", UP_TXT))
        for r in (lose or [])[:3]:
            stack.append((f"▼ {str(r.get('name'))[:10]} {abs(_f(r.get('chg')) or 0):.1f}%", DN_TXT))
    if alerts_cnt is not None:
        stack.append((_L(f"오늘 발동 알림 {alerts_cnt}건", f"alerts fired today: {alerts_cnt}"), MUT))
        if fired_names:
            stack.append((" · ".join(str(n) for n in fired_names[:6]), INK))
    if cal:
        stack.append((_L("내일 ", "tomorrow ") + str(cal), INK))
    return stack


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
        # ── 재료를 먼저 세고 캔버스 높이를 정한다(2026-09-18). 종전엔 높이가 7.4 로 고정이라
        #    인트라데이·수급·특징주가 전부 없는 날엔 하단 45%가 빈 채로 나갔다 — 디스코드는
        #    이미지를 폭에 맞춰 축소하므로, 빈 자리만큼 글자가 작아진다(읽히는 크기가 준다).
        xs, ys, prev, src = intraday or ([], [], None, "")
        inv = investor or {}
        vals = [(l, v) for l, v in ((_L("외국인", "foreign"), _f(inv.get("foreign"))),
                                    (_L("기관", "inst"), _f(inv.get("inst"))),
                                    (_L("개인", "retail"), _f(inv.get("retail"))))
                if v is not None]
        stack = _close_stack(movers, alerts_cnt, fired_names, cal)
        # 수급 바가 있는 날만 아래 '행'이 생긴다. 우하 텍스트 몇 줄은 행을 차지할 이유가
        # 없어서, 없으면 상단 아래에 붙이고 캔버스를 줄 수만큼만 늘린다.
        has_bottom = bool(vals)
        hgt = 7.4 if has_bottom else max(4.2, min(7.4, 4.3 + 0.33 * len(stack)))
        fig = plt.figure(figsize=(10, hgt), dpi=160)
        fig.patch.set_facecolor(BG)
        # 제목·상단 분면의 '인치' 위치는 높이와 무관하게 같다(위에서부터 재는 값) — 비율로
        # 고정하면 캔버스가 짧아질 때 제목이 위로 튀거나 분면이 footer 를 파고든다.
        fig.text(0.03, 1 - 0.333 / hgt, _L(f"{now.month}/{now.day} 장 마감 리포트",
                                           f"{now.month}/{now.day} Market Close"),
                 color=INK, fontsize=18, fontweight="bold")
        _ty, _th = 1 - 3.367 / hgt, 2.553 / hgt       # 상단 분면 y·높이(인치 환산 고정)
        # ── 좌상: 다이버징 바. 우상 인트라데이가 없으면 오른쪽 절반이 빈 칸으로 남으므로
        #    바가 전폭을 쓴다(같은 캔버스에서 막대와 숫자가 커진다).
        _has_intra = bool(ys and len(ys) >= 3)
        ax = fig.add_axes([0.115, _ty, 0.40 if _has_intra else 0.80, _th])
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
        if _has_intra:
            ax2 = fig.add_axes([0.60, _ty, 0.37, _th])
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
            # 등락은 왼쪽 바와 같은 숫자를 쓴다(2026-09-24 A6). 종전엔 인트라데이 마지막 점과
            # 그 체인의 전일값으로 따로 계산해, 한 카드에 코스피 등락률이 두 값(+0.93% / +0.22%)
            # 으로 찍혔다. 인트라데이 마지막 점은 수집 지연만큼 종가와 어긋난다.
            _kc = next((c for l, _p, c in its if l in ("코스피", "KOSPI")), None)
            if _kc is None and prev:
                _kc = (ys[-1] / prev - 1) * 100
            if _kc is not None:
                ax2.text(0.97, 0.93, f"{_kc:+.2f}%", transform=ax2.transAxes,
                         color=_txt_color(_kc >= 0), fontsize=12.5,
                         ha="right", va="top", fontweight="bold")
            ax2.set_xticks([]); ax2.set_yticks([])
            for s in ax2.spines.values():
                s.set_visible(False)
        # ── 좌하: 투자자 순매수 3주체(코스피, 억원)
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
        # 줄을 먼저 모아 놓고 남은 세로에 맞춰 간격을 정한다 — 종전처럼 고정 간격으로
        # 쌓으면 특징주 6줄 + 알림 + 종목명 + 일정이 다 찼을 때 마지막 줄이 y=0.028 까지
        # 내려가 footer(y=0.022)를 파고들었다(2026-09-17 실측: 82×18px 겹침).
        if stack:
            if has_bottom:
                RX, RW, top = 0.56, 0.41, 0.435       # 우측 열 시작 x / 가용 폭 / 첫 줄
            else:
                RX, RW, top = 0.115, 0.86, _ty - 0.45 / hgt   # 상단 분면 바로 아래, 전폭
            floor = 0.075                             # footer(0.022) 위 안전 여백
            step = min(0.33 / hgt, (top - floor) / len(stack))
            for i, (txt, tcol) in enumerate(stack):
                fig.text(RX, top - i * step, _clip(fig, txt, RW, 12), color=tcol, fontsize=12)
        _footer(fig, now)
        return _save(fig, "discord_card_close.png")
    except Exception as e:
        print(f"::warning title=디스코드 카드 실패::close: {e} — 기존 형식 폴백")
        return None


def _close_square(plt, its, now, alerts_cnt, cal, intraday, investor, fired_names):
    """지표형 정사각 — 장 마감(기획 v3 §02 P2). 지수 다이버징 바 + 수급·알림 타일
    + 코스피 인트라데이. 가로 4분면을 세로 3단으로 접는다."""
    inv = investor or {}
    # as-of 는 타일이 아니라 제목 줄 오른쪽에 한 번만 적는다 — 종전엔 「억원 · 09-17 (잠정)」이
    # 타일 세 칸에 똑같이 반복되면서, 한 칸에서 가장 긴 글자가 되어 값 글자를 누르고 있었다.
    # (확정치는 KRX 18시 이후 — 잠정 값을 확정처럼 읽히게 두면 실제 값과 어긋난다.)
    _asof = " ".join(x for x in (str(inv.get("date") or "")[5:], inv.get("reason") or "") if x)
    fig = _sq_fig(plt, _L(f"{now.month}/{now.day} 장 마감", f"{now.month}/{now.day} Market Close"),
                  now.strftime("%H:%M") + (_L(f" · 수급 {_asof}", f" · flows {_asof}")
                                           if _asof else ""))
    _unit = _L("억원", "0.1bn")
    cells = [[]]
    # 3주체 전부 — 외국인·기관만 싣고 남은 칸을 '오늘 알림'(그날 이미 실시간으로 받은
    # 알림의 집계)에 내주던 것을 개인으로 바꿨다(2026-09-17 사용자 결정). 수급은 세 주체의
    # 합이 0 이라, 둘만 보여주면 나머지 하나를 머릿속에서 빼야 읽힌다.
    for lab, key, sat in ((_L("외국인", "foreign"), "foreign", 5000.0),
                          (_L("기관", "inst"), "inst", 5000.0),
                          (_L("개인", "retail"), "retail", 5000.0)):
        v = _f(inv.get(key))
        if v is not None:
            cells[0].append(_cell(lab, f"{v:+,.0f}", _unit, v, sat=sat))
    if not cells[0] and alerts_cnt is not None:
        # 수급이 통째로 비는 날(검증 실패·장 마감 전)에만 알림 집계가 그 자리를 대신한다.
        nm = ""
        if fired_names:
            nm = str(fired_names[0])
            if len(fired_names) > 1:
                nm += _L(f" 외 {len(fired_names) - 1}", f" +{len(fired_names) - 1}")
        cells[0].append(_cell(_L("오늘 알림", "alerts"), f"{alerts_cnt}", nm, None))
    if cells[0]:
        _draw_cells(fig, cells, (0.03, 0.775, 0.94, 0.145), (18, 24, 18), square=True,
                    note_inline=True)
        # 타일 아래 라벨 띠 — 타일 실하단(0.775-pad 0.004=0.771)과 바 축 상단 사이를 비워
        # 그 한가운데에 세로 중앙정렬로 놓는다. 종전(베이스라인 0.755)엔 글자 윗부분이
        # 타일 안으로 22px 들어가 잘려 보였다(2026-09-17 실측).
        bar_box, bar_lab = [0.26, 0.468, 0.71, 0.264], SEC_LAB_Y
    else:
        bar_box, bar_lab = [0.26, 0.475, 0.71, 0.42], 0.925
    # 가격을 같이 싣는다(2026-09-24 A6) — 가로 카드엔 있고 정사각엔 없어 카톡 수신자만
    # 「코스피 +0.93%」를 보고 레벨을 몰랐다. 칸이 좁아 여백을 조금 더 준다.
    _bars(fig, bar_box, [(l, c) for l, _p, c in its], square=True, lim_mul=2.6,
          texts=[f"{_fmt(p)} {c:+.2f}%" for _l, p, c in its])
    fig.text(0.03, bar_lab, _L("지수 등락", "index moves"), color=MUT,
             fontsize=_fs(17, True), va="center")
    xs, ys, prev, src = intraday or ([], [], None, "")
    # 패널 오른쪽 값 자리는 비어 있었다 — 카드의 주인공이 코스피 인트라데이인데
    # 정작 종가·등락은 아래 바 차트에서 작은 글씨로만 읽혔다.
    _kp = next(((p, c) for l, p, c in its if l in ("코스피", "KOSPI")), None)
    _sq_panel(fig, [0.03, 0.165, 0.94, 0.245], ys, xs=xs, prev=prev,
              up=bool(ys) and (ys[-1] >= (prev or ys[0])),
              label=_L("코스피 오늘", "KOSPI today") + (f" · {src}" if src else ""),
              right=(f"{_fmt(_kp[0])}  {_chgtxt(_kp[1])}".strip() if _kp else ""))
    if cal:
        fig.text(0.03, 0.075, _clip(fig, _L("내일  ", "tomorrow  ") + str(cal), 0.94, _fs(15, True)),
                 color=INK, fontsize=_fs(15, True))
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
        span = period_label(w.get("from"), w.get("to"))
        return _L(f"주간 수급(코스피 {span}): 외국인 {fo:+,.0f}억 · 기관 {it:+,.0f}억",
                  f"weekly net buy (KOSPI {span}): foreign {fo:+,.0f} · inst {it:+,.0f} (0.1bn KRW)")
    except Exception:
        return ""


def _bars(fig, box, rows, square=False, unit="%", nd=2, lim_mul=1.6, texts=None):
    """다이버징 수평 바 — rows=[(라벨, 값)]. 주간·마감 카드가 공유한다.
    texts = 행별 값 문구(없으면 「+0.93%」). 마감 카드는 가격을 함께 싣는다."""
    ax = fig.add_axes(box)
    ax.set_facecolor(BG)
    vals = [v for _l, v in rows]
    ax.barh(range(len(rows)), vals, height=0.55,
            color=[UP if v > 0 else DN if v < 0 else FAINT for v in vals])
    ax.axvline(0, color=FAINT, lw=1)
    for i, (_l, v) in enumerate(rows):
        ax.text(v + (0.08 if v >= 0 else -0.08) * (max(abs(x) for x in vals) or 1) / 2.5, i,
                (texts[i] if texts else f"{v:+.{nd}f}{unit}"),
                va="center", ha="left" if v >= 0 else "right",
                color=INK, fontsize=_fs(18, square))
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([l for l, _v in rows], color=MUT, fontsize=_fs(18, square))
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
        _pl = week_period(now)
        fig.text(0.03, 0.945,
                 _L(f"주간 리포트 — {_pl} 수익률", f"Weekly — {_pl} returns"),
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
            fig.text(0.03, 0.068, _clip(fig, _L("다음 주  ", "next week  ") + str(next_week), 0.94, 12),
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
    _pl = week_period(now)
    fig = _sq_fig(plt, _L(f"주간 리포트 · {_pl}", f"Weekly · {_pl}"),
                  _L("주간 종가 기준", "weekly close"))
    best, worst = rows[-1], rows[0]
    cells = [[_cell(_L("최고", "best"), best[0], f"{best[2]:+.2f}%", best[2]),
              _cell(_L("최저", "worst"), worst[0], f"{worst[2]:+.2f}%", worst[2])]]
    _w5 = _week_flow_5d(d)
    if _w5:
        fo = _w5["foreign"]
        _span = period_label(_w5.get("from"), _w5.get("to"))
        cells[0].append(_cell(_L("외국인 5일", "foreign 5d"), f"{fo:+,.0f}",
                              _L("억원", "0.1bn") + f" · {_span}", fo, sat=20000.0))
    _draw_cells(fig, cells, (0.03, 0.775, 0.94, 0.145), (15, 22, 13), square=True)
    _bars(fig, [0.26, 0.135, 0.71, 0.597], [(l, c) for l, _k, c in rows],
          square=True, lim_mul=1.85)
    fig.text(0.03, SEC_LAB_Y, _L("주간 수익률", "weekly returns"), color=MUT,
             fontsize=_fs(17, True), va="center")
    if next_week:
        fig.text(0.03, 0.075, _clip(fig, _L("다음 주  ", "next week  ") + str(next_week), 0.94,
                            _fs(15, True)),
                 color=INK, fontsize=_fs(15, True))
    _footer(fig, now, square=True)
    return _save(fig, "kakao_card_weekly.png")


def swing(name, price, pct, thr_pct, xs, ys, prev, now, resume="", src="", shape="wide",
          why=""):
    """카드 D — 급변·서킷. 히어로 등락률 + 인트라데이(또는 일봉 폴백) 임계선.
    why = 이례성 한 줄("z −2.6σ · 최근 1년 중 4번째로 큰 하락") — 있으면 보조줄을
    '임계 ±N% 돌파' 대신 이것으로 바꾼다. 임계값은 이제 자산의 σ 에서 나오므로
    숫자만 적어서는 그게 큰 움직임인지 알 수 없기 때문(기획안 P2).
    xs/ys/prev = send_kakao_digest._intraday_chain 반환값(비어 있으면 히어로만 — 최후).
    src = 폴백 라벨('일봉 7D' 등, 기획 5154773b P0) — 패널에 표기해 인트라데이 오독 방지.
    x축 눈금은 구간 폭으로 자동(하루 안=HH:MM, 여러 날=M/D). 실패 시 None."""
    try:
        if pct is None:
            return None
        plt, _ = _setup()
        if shape == "square":
            return _swing_square(plt, name, price, pct, thr_pct, xs, ys, prev, now, resume,
                                 src, why)
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
        sub = why or _L(f"임계 ±{abs(thr_pct):.1f}% {'상향' if pct > 0 else '하향'} 돌파",
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


def _swing_square(plt, name, price, pct, thr_pct, xs, ys, prev, now, resume, src, why=""):
    """사건형 정사각 — 급변·서킷 발동. 히어로 등락률 + 타일 3 + 인트라데이 임계선."""
    col = UP if pct > 0 else DN
    fig = _sq_fig(plt, _L(f"시장 급변 · {str(name)[:14]}", f"Market Swing · {str(name)[:14]}"),
                  now.strftime("%m/%d %H:%M"))
    fig.text(0.03, 0.845, f"{pct:+.2f}%", color=col, fontsize=_fs(56, True), fontweight="bold")
    sub = why or _L(f"임계 ±{abs(thr_pct):.1f}% {'상향' if pct > 0 else '하향'} 돌파",
                    f"threshold ±{abs(thr_pct):.1f}% crossed")
    if resume:
        sub += " · " + str(resume)
    fig.text(0.03, 0.795, _clip(fig, sub, 0.94, _fs(12.5, True)),
         color=MUT, fontsize=_fs(12.5, True))
    thr_v = prev * (1 + (abs(thr_pct) if pct > 0 else -abs(thr_pct)) / 100.0) if prev else None
    cells = [[_cell(str(name)[:10], _fmt(price) if price is not None else "—",
                    _chgtxt(pct), pct)]]
    if prev:
        cells[0].append(_cell(_L("전일", "prev"), _fmt(prev),
                              (_fmt_diff(price - prev) if price is not None else ""), None))
        cells[0].append(_cell(_L("임계선", "threshold"), _fmt(thr_v),
                              f"±{abs(thr_pct):.1f}%", None))
    _draw_cells(fig, cells, (0.03, 0.60, 0.94, 0.145), (18, 24, 18), square=True,
                note_inline=True)
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
        fig.text(0.06, band_y + band_h * (0.55 if reason else 0.42),
                 _clip(fig, state, 0.88, _fs(38, True), "bold"),
                 color=band, fontsize=_fs(38, True), fontweight="bold")
        if reason:
            fig.text(0.06, band_y + band_h * 0.22, _clip(fig, reason, 0.88, _fs(13.5, True)), color=INK,
                     fontsize=_fs(13.5, True))
        if tl:
            w = (0.94 - 0.012 * (len(tl) - 1)) / len(tl)
            ty = band_y - gap - tl_h
            for i_, (txt, done) in enumerate(tl):
                x = 0.03 + i_ * (w + 0.012)
                fig.patches.append(FancyBboxPatch(
                    (x, ty), w, tl_h, boxstyle="round,pad=0.004,rounding_size=0.009",
                    transform=fig.transFigure, fc=wash if done else TILE, ec="none"))
                fig.text(x + w / 2, ty + tl_h * 0.38, _clip(fig, txt, w - 0.02, _fs(12.5, True)),
                         color=band if done else MUT, fontsize=_fs(12.5, True),
                         ha="center", fontweight="bold" if done else "normal")
        if rows:
            _draw_cells(fig, rows, (0.03, bot, 0.94, tiles_h), (13, 20, 13), square=True)
        _footer(fig, now, square=True)
        return _save(fig, "kakao_card_status.png")
    except Exception as e:
        print(f"::warning title=카드 실패::status: {e} — 텍스트 폴백")
        return None


def surprise(ev, why, now=None, hist=None, shape="wide"):
    """카드 E — 경제지표 발표 결과(기획안 P4). 실패 시 None(텍스트 폴백).

    ev = economicCalendar 이벤트 dict(name·act·fore·prev·stars·dt).
    why = 근거 한 줄(check_releases.judge 가 만든 것).
    hist = 그 지표의 과거 관측값 목록 — 있으면 하단에 분포 띠를 그려 '오늘 값이 과거
           어디쯤인지'를 숫자가 아니라 위치로 보여준다.

    구성: 실제치 히어로 → 직전·예상·실제 3점 비교 → 과거 분포 띠.
    수치를 나열하지 않고 '예상과 실제 사이의 거리'를 길이로 보이게 하는 것이 요점이다."""
    try:
        import check_releases as cr
        plt, _ = _setup()
        now = now or datetime.datetime.now()
        act = cr._num(ev.get("act"))
        if act is None:
            return None
        fore, prev = cr._num(ev.get("fore")), cr._num(ev.get("prev"))
        stars = "★" * int(ev.get("stars") or 0)
        name = str(ev.get("name") or "")
        # 서프라이즈 방향 — 예상보다 높으면 위쪽 색, 낮으면 아래쪽 색. 예상이 없으면
        # 분포에서의 위치로 대신한다. '좋다/나쁘다'는 지표마다 달라 색에 담지 않는다.
        up = (act > fore) if fore is not None else bool(hist and act > (sum(hist) / len(hist)))
        col, coltxt = (UP, _txt_color(True)) if up else (DN, _txt_color(False))

        square = shape == "square"
        if square:
            fig = _sq_fig(plt, f"{name[:18]} {stars}".strip(), now.strftime("%m/%d %H:%M"))
            y_hero, y_why, ax_box, strip_box = 0.80, 0.755, [0.06, 0.40, 0.88, 0.26], [0.06, 0.16, 0.88, 0.10]
            fs_hero, fs_why = _fs(46, True), _fs(13, True)
        else:
            fig = plt.figure(figsize=(10, 5.0), dpi=130)
            fig.patch.set_facecolor(BG)
            _head(fig, f"{name} {stars}".strip(), str(ev.get("dt") or ""),
                  fs_t=19, fs_m=11, y=0.93, square=False)
            y_hero, y_why, ax_box, strip_box = 0.66, 0.58, [0.06, 0.28, 0.88, 0.22], [0.06, 0.12, 0.88, 0.08]
            fs_hero, fs_why = 46, 13

        fig.text(0.06, y_hero, str(ev.get("act")), color=col,
                 fontsize=fs_hero, fontweight="bold")
        fig.text(0.06, y_why, _clip(fig, why, 0.88, fs_why), color=INK, fontsize=fs_why)

        # 분포 띠가 없는 날은 3점 비교가 그 자리까지 쓴다(2026-09-24 A7) — 종전엔 정사각
        # 캔버스 하단 55%가 빈 채로 나가 말풍선에서 글자가 그만큼 작아졌다.
        if len([v for v in (hist or []) if v is not None]) < cr.MIN_HISTORY:
            ax_box = [ax_box[0], strip_box[1], ax_box[2], ax_box[1] + ax_box[3] - strip_box[1]]
        # 직전·예상·실제 3점 비교 — 값이 있는 것만. 한 축에 얹어 거리를 눈으로 본다.
        pts = [(lab, v) for lab, v in ((_L("직전", "prev"), prev),
                                       (_L("예상", "fore"), fore),
                                       (_L("실제", "act"), act)) if v is not None]
        if len(pts) >= 2:
            ax = fig.add_axes(ax_box)
            ax.set_facecolor(BG)
            lo, hi = min(v for _, v in pts), max(v for _, v in pts)
            pad = (hi - lo) * 0.35 or (abs(hi) * 0.1) or 1.0
            ax.set_xlim(lo - pad, hi + pad)
            ax.set_ylim(-0.6, len(pts) - 0.4)
            for i_, (lab, v) in enumerate(pts):
                y = len(pts) - 1 - i_
                is_act = lab in ("실제", "act")
                ax.plot([lo - pad, v], [y, y], color=col if is_act else LINE,
                        lw=3.0 if is_act else 1.2, alpha=1.0 if is_act else 0.35)
                ax.plot(v, y, "o", color=col if is_act else LINE, ms=9 if is_act else 6)
                ax.text(lo - pad, y + 0.22, lab, color=MUT, fontsize=_fs(12, square))
                ax.text(v, y + 0.22, f" {v:g}", color=coltxt if is_act else INK,
                        fontsize=_fs(12.5, square), fontweight="bold")
            ax.set_yticks([])
            ax.set_xticks([])
            for s in ax.spines.values():
                s.set_visible(False)

        # 과거 분포 띠 — 오늘 값이 최저~최고 사이 어디에 꽂히는지.
        vals = [v for v in (hist or []) if v is not None]
        if len(vals) >= cr.MIN_HISTORY:
            ax2 = fig.add_axes(strip_box)
            ax2.set_facecolor(TILE)
            lo, hi = min(vals), max(vals)
            ax2.set_xlim(lo, hi)
            ax2.set_ylim(0, 1)
            for v in vals:
                ax2.plot([v, v], [0.15, 0.85], color=LINE, lw=0.8, alpha=0.25)
            ax2.plot([act, act], [0.0, 1.0], color=col, lw=2.6)
            ax2.text(lo, 1.15, f"{lo:g}", color=FAINT, fontsize=_fs(10.5, square),
                     transform=ax2.get_xaxis_transform())
            ax2.text(hi, 1.15, f"{hi:g}", color=FAINT, fontsize=_fs(10.5, square),
                     ha="right", transform=ax2.get_xaxis_transform())
            ax2.text(0.0, -0.55, _L(f"과거 {len(vals)}회 분포", f"past {len(vals)}"),
                     color=MUT, fontsize=_fs(11, square), transform=ax2.transAxes)
            ax2.set_xticks([])
            ax2.set_yticks([])
            for s in ax2.spines.values():
                s.set_visible(False)
        _footer(fig, now, square=square)
        return _save(fig, "kakao_card_surprise.png" if square else "discord_card_surprise.png")
    except Exception as e:                                   # noqa: BLE001
        print(f"::warning title=카드 실패::surprise: {e} — 텍스트 폴백")
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
