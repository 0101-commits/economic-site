"""문구 틀 — 사건 행 + Hit → 「무엇 · 값 · 왜 · 다음 · 어디」 다섯 칸(기획서 4장).

규칙(2026-11-06 알림 개편 P2 — 잠금 화면 한 줄, 아이폰 실기기로 잰 값):
  제목 = 폭 18칸 한 줄(한글 1칸, 숫자 · 영문 · 기호 · 띄어쓰기 0.6칸 — width()). 넘치면 글자로 자르지 않고
    더 짧은 이름(shortM) → 운용사 이름 빼기 → 일정 이름 줄이기 → 날짜 꼬리 빼기 → 뒤 「 · 」 조각 빼기 순으로 줄인다.
  폰 알림 본문 = 폭 20칸 한 줄, 사실 하나(왜). 틀 목록에서 20칸 안에 드는 첫 틀(first_fit). 다음 · 몇 번째 같은 설명은 싣지 않는다.
  알림 기록용 왜 · 다음 = ≤40자. 묵은 값(prev · kept)은 값 뒤에 「(M/D)」 · 「(이전 값)」 · 상대 시점어 금지 · 금액 없음.
템플릿 변수가 비면 그 조각은 조용히 빠지고, 「 · 」 구분자는 정리한다.
"""
from __future__ import annotations

import datetime as dt
import re
import string
import unicodedata

from . import LEVELS

TITLE_W = 18                     # 제목 한 줄(아이폰 잠금 화면: 한글 18자까지 보이고 19자부터 「…」, 2026-11-06 실측)
BODY_W = 20                      # 본문 한 줄(아이폰 한 줄 약 21자 · 갤럭시 접힌 알림 한 줄)
BRIEF_TITLE_MAX = 48             # 카톡 브리핑 제목(카톡 말풍선은 두 줄까지 보인다)
TITLE_MAX = 30                   # 옛 상한 — 원장 제목 안전 레일(폭 규칙이 먼저 걸린다)
LINE_MAX = 40
PUSH_BODY_MAX = 80
MINUS = "−"


def width(s: str) -> float:
    """화면 폭 — 한글 · 한자(동아시아 전각) 1칸, 그 밖(숫자 · 영문 · 기호 · 띄어쓰기) 0.6칸."""
    return round(sum(1.0 if unicodedata.east_asian_width(c) in "WF" else 0.6 for c in str(s or "")), 1)


def cut_w(s: str, w: float) -> str:
    """폭 w 안으로 — 넘치면 끝에 「…」. 이름 보존 규칙(render)이 다 실패했을 때만 쓰는 마지막 레일."""
    s = str(s or "")
    if width(s) <= w:
        return s
    out = ""
    for c in s:
        if width(out + c) > w - 1:
            break
        out += c
    return out.rstrip() + "…"


# 운용사 이름(ETF 앞머리) — 제목이 넘치면 뺀다. 상세 화면에는 그대로 있다.
_BRANDS = ("KODEX", "TIGER", "RISE", "SOL", "ACE", "PLUS", "HANARO", "KOSEF", "KIWOOM", "TIMEFOLIO", "WON", "1Q",
           "KBSTAR", "ARIRANG", "BNK", "마이다스", "에셋플러스", "히어로즈", "파워", "UNICORN", "FOCUS", "TRUSTON", "DAISHIN343")
_BRAND_RE = re.compile(r"^(?:" + "|".join(map(re.escape, _BRANDS)) + r")\s+")
# 일정 이름 줄이기(긴 공식 이름 → 짧은 이름). 앞에서부터 바꾼다.
_EVENT_SHORT = (
    ("소비자물가동향", "CPI"), ("소비자물가지수(CPI)", "CPI"), ("소비자물가지수", "CPI"), ("생산자물가지수(PPI)", "PPI"),
    ("비농업고용(NFP)", "비농업 고용"), ("비농업고용", "비농업 고용"), ("금융정책결정회합", "금리 결정"), ("통화정책 결정", "금리 결정"),
    ("일본은행(BOJ)", "일본은행"), ("금융통화위원회", "금통위"), ("FOMC 금리 결정", "FOMC"), ("개인소비지출(PCE)", "PCE"),
    ("국내총생산(GDP)", "GDP"), ("PCE 물가지수", "PCE"), ("물가지수", "물가"), ("소매판매", "소매판매"), ("실업률", "실업률"),
)


def short_event(name: str) -> str:
    out = str(name or "")
    for a, b in _EVENT_SHORT:
        out = out.replace(a, b)
    return re.sub(r"\s+", " ", out).strip()


def first_fit(templates, data: dict, w: float) -> str:
    """틀 목록에서 빈 변수 없이 채워지고 폭 w 안에 드는 첫 틀. 없으면 채워진 첫 틀을 폭으로 자른다."""
    if isinstance(templates, str):
        templates = [templates]
    full = []
    for t in templates or []:
        s, missing = fill(t, data)
        if s and not missing:
            if width(s) <= w:
                return s
            full.append(s)
    return cut_w(full[0], w) if full else ""
_REL_WORDS = ("내일", "모레", "다음 주", "다음주", "이번 주", "연휴", "오늘 밤", "어제")

DIR_KO = {
    "up": "상승", "down": "하락", "sell": "순매도", "buy": "순매수", "cross": "돌파", "near": "근접",
    "new": "새로", "change": "변경", "enter": "진입", "exit": "해제",
}
DIR_REV_KO = {"sell": "순매수", "buy": "순매도", "up": "하락", "down": "상승"}
DIR_LINE = {"up": "위로", "down": "아래로", "cross": "돌파", "near": "가까이"}   # 선 기준 방향(용어 정제 2차 F)


class _Missing:
    """없는 변수 — 어떤 서식 지정자도 빈 글자로."""
    def __format__(self, spec):
        return ""
    def __str__(self):
        return ""


class _Fmt(string.Formatter):
    def __init__(self, data: dict):
        super().__init__()
        self.data = data
        self.missing = False

    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            if key in self.data and self.data[key] is not None and self.data[key] != "":
                return self.data[key]
            self.missing = True
            return _Missing()
        return super().get_value(key, args, kwargs)

    def format_field(self, value, spec):
        if isinstance(value, _Missing):
            return ""
        try:
            return super().format_field(value, spec)
        except (ValueError, TypeError):
            return str(value)


def _tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    # 구분자 「 · 」만 정리한다 — 띄어 쓴 가운뎃점. 이름 속 가운뎃점(원·달러 · 공포·탐욕 · 신고가·신저가)은 건드리지 않는다.
    s = re.sub(r"(?:\s+·\s*|\s*·\s+)+", " · ", s)
    s = re.sub(r"^\s*·\s+|\s+·\s*$|^·\s*|\s*·$", "", s)
    s = re.sub(r"\(\s*\)", "", s).strip()
    s = re.sub(r"(?<![\w/.])-(?=\d)", MINUS, s)       # 마이너스는 「−」 하나(서식 지정자 {chg:+.1f} 가 낸 하이픈 포함)
    return s


def fill(template: str, data: dict) -> tuple[str, bool]:
    """(채운 글, 빠진 변수 있었나)."""
    f = _Fmt(data)
    out = f.vformat(template, (), {})
    return _tidy(out), f.missing


def first_full(templates, data: dict) -> str:
    """빠진 변수가 없는 첫 틀. 다 빠지면 빈칸 — 반쯤 채운 줄(「 동반」 · 「1,300」 뒤 말 없음)은 내보내지 않는다
    (기획서 4장 「없으면 비우고 『이유 없음』이라 쓰지 않음」). 대안이 필요하면 틀 목록 뒤에 짧은 틀을 둔다."""
    for t in templates or []:
        s, missing = fill(t, data)
        if s and not missing:
            return s
    return ""


def fmt_num(v, unit: str = "", decimals: int | None = None) -> str:
    """숫자 한 벌 표기 — 억은 1만 넘으면 조, % · bp · $ 단위 그대로, 음수는 「−」."""
    if v is None or v == "":
        return ""
    if isinstance(v, str):
        return v
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    neg = x < 0
    a = abs(x)
    if unit == "주":
        decimals = 0                                   # 주식 수는 정수(「287.00주」 · 「195.00주주」 버그, 2026-11-06)
    elif unit == "$" and a >= 1000:
        decimals = 0                                   # 「$4,143」 — 1,000 이상은 소수 없음(용어 정제 2차 D7)
    if unit == "억":
        if a >= 10000:
            s = f"{a / 10000:.2f}조"
        else:
            s = f"{a:,.0f}억"
    elif unit == "bp":
        s = f"{a:.0f}bp"
    elif unit == "%":
        s = f"{a:.2f}%" if decimals is None else f"{a:.{decimals}f}%"
    elif decimals is not None:
        s = f"{a:,.{decimals}f}"
    elif a >= 1000:
        s = f"{a:,.0f}"
    elif a >= 100:
        s = f"{a:,.2f}"
    else:
        s = f"{a:.2f}".rstrip("0").rstrip(".") if a != int(a) else f"{a:.0f}"
    if unit == "$":
        s = "$" + s                                    # 달러는 앞에(「4,143.00$」 → 「$4,143」)
    elif unit in ("원", "주", "호"):
        s = s + unit                                   # 지수는 단위 없음(「5,479.64p」 → 「5,479.64」, 화면과 같게)
    return (MINUS + s) if neg else s


def stale_tag(fresh: str, as_of: str, today: dt.date | None = None) -> str:
    """묵은 값 꼬리표. live · 오늘 값이면 빈 글자."""
    if fresh == "kept":
        return "(이전 값)"
    if not as_of:
        return ""
    try:
        d = dt.date.fromisoformat(str(as_of)[:10])
    except ValueError:
        return ""
    today = today or dt.date.today()
    if fresh in ("prev", "stale") and d < today:
        return f"({d.month}/{d.day})"
    return ""


def cut(s: str, n: int) -> str:
    return s if len(s) <= n else s[: max(n - 1, 1)] + "…"


def has_relative_time(s: str) -> bool:
    return any(w in s for w in _REL_WORDS)


# 레지스트리에 행이 없는 렌즈 전용 계열 — 내부 id(「jp30y」)가 제목에 그대로 나가던 자리(용어 정제 2차 A).
_NO_ROW_NAMES = {"jp30y": ("일본 국채 30년", "일본 30년"), "jp10y": ("일본 국채 10년", "일본 10년"), "jp1y": ("일본 국채 1년", "일본 1년")}


def _display_name(target: str, ctx, key: str = "short") -> str:
    if ctx is not None:
        row = getattr(ctx, "registry", {}).get(getattr(ctx, "rid", lambda t: t)(target)) or {}
        if row:
            return row.get(key) or row.get("short") or row.get("label") or target
    pair = _NO_ROW_NAMES.get(str(target))
    return (pair[1] if key == "shortM" else pair[0]) if pair else target


def variables(ev: dict, hit, ctx=None, today: dt.date | None = None) -> dict:
    """틀 변수 사전 — 표준 변수 + Hit.fields."""
    today = today or (ctx.now.date() if ctx is not None else dt.date.today())
    reg = (getattr(ctx, "registry", {}) or {}).get(getattr(ctx, "rid", lambda t: t)(hit.target)) or {} if ctx else {}
    decimals = reg.get("decimals")
    unit = hit.unit or reg.get("unit") or ""
    value = fmt_num(hit.value, unit, decimals)
    if unit == "억" and isinstance(hit.value, (int, float)) and hit.value > 0:
        value = "+" + value                        # 수급 순매수 — 「오늘 2.20조」가 매도인지 매수인지 안 보였다
    tag = stale_tag(hit.fresh, hit.asOf, today)
    d = {
        "name": hit.fields.get("name") or _display_name(hit.target, ctx),
        "name_m": hit.fields.get("name") or _display_name(hit.target, ctx, "shortM"),   # 더 짧은 이름(제목이 넘칠 때)
        "target": hit.target,
        "value": _tidy(f"{value} {tag}") if tag else value,
        "value_plain": value,                                                          # 날짜 꼬리 없는 값(기간을 따로 적는 틀)
        "dir_line": DIR_LINE.get(hit.dir, DIR_KO.get(hit.dir, hit.dir)),
        "value_raw": hit.value,
        "chg": hit.chg,
        "dir": hit.dir,
        "dir_ko": DIR_KO.get(hit.dir, hit.dir),
        "dir_rev_ko": DIR_REV_KO.get(hit.dir, ""),
        "asof_md": _md(hit.asOf),
        "today_md": f"{today.month}/{today.day}",
    }
    for k, v in (hit.fields or {}).items():    # 판정 함수가 준 변수가 표준 변수를 덮는다(dir_ko · name …)
        if k == "level" or v is None or v == "":
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) >= 1000 and k not in ("z", "abs_z"):
            v = fmt_num(v)                           # 7000 → 7,000 (마디 · 임계 · 누적 같은 큰 수)
        d[k] = v
    stage = (hit.fields or {}).get("stage")
    d.setdefault("stage_label", f"{stage}단계" if stage else "")
    return d


_STALE_TAIL = re.compile(r"\s*\((?:\d{1,2}/\d{1,2}|이전 값)\)")


def fit_title(templates, data: dict, w: float = TITLE_W) -> str:
    """제목 한 줄(폭 w). 이름을 글자로 자르지 않는다 — 넘치면 차례로: 더 짧은 이름 → 운용사 이름 빼기 → 일정 이름 줄이기 →
    값의 날짜 꼬리 빼기 → 뒤 「 · 」 조각 빼기. 그래도 넘치면(드묾) 폭으로 자른다. 틀 목록이면 앞 틀부터."""
    if isinstance(templates, str):
        templates = [templates]
    if not templates:
        return ""
    steps = (
        lambda x: dict(x, name=x.get("name_m") or x.get("name")),
        lambda x: dict(x, name=_BRAND_RE.sub("", str(x.get("name") or ""))),
        lambda x: dict(x, event_name=short_event(x.get("event_name"))),
        lambda x: dict(x, value=_STALE_TAIL.sub("", str(x.get("value") or ""))),
    )
    shortest = []                                       # 틀마다 줄이기를 다 한 글
    for t in templates:
        s, missing = fill(t, data)
        if not s or (missing and len(templates) > 1):
            continue
        d = dict(data)
        if width(s) <= w:
            return s
        for step in steps:
            d = step(d)
            s = fill(t, d)[0]
            if width(s) <= w:
                return s
        # 그래도 넘치면 이름만 줄인다(꼬리 = 무슨 일 · 「내 조건 아래로」를 지킨다, 10/12 사고). 이름이 4칸 밑으로 가면 포기.
        for key in ("name", "event_name"):
            nm = str(d.get(key) or "")
            if nm and nm in s:
                keep = width(nm) - (width(s) - w)
                if keep >= 4:
                    s2 = fill(t, dict(d, **{key: cut_w(nm, keep)}))[0]
                    if width(s2) <= w:
                        return s2
        shortest.append(s)
    if not shortest:
        return cut_w(fill(templates[0], data)[0], w)
    parts = shortest[0].split(" · ")
    while len(parts) > 1:
        parts.pop()
        if width(" · ".join(parts)) <= w:
            return " · ".join(parts)
    return cut_w(shortest[0], w)


def _md(as_of: str) -> str:
    try:
        d = dt.date.fromisoformat(str(as_of)[:10])
        return f"{d.month}/{d.day}"
    except (TypeError, ValueError):
        return ""


def render(ev: dict, hit, ctx=None, today: dt.date | None = None) -> dict:
    """다섯 칸 + 채널별 본문. 길이 상한은 여기서 강제한다."""
    data = variables(ev, hit, ctx, today)
    if ev.get("level") == "brief":                     # 브리핑 행(카톡 제목)은 두 줄까지 — 폭 규칙 밖
        title = cut(fill(ev["title"], data)[0], BRIEF_TITLE_MAX)
    else:
        title = fit_title(ev["title"], data)
    why = cut(first_full(ev.get("why"), data), LINE_MAX)
    nxt = cut(first_full(ev.get("next"), data), LINE_MAX)
    if has_relative_time(nxt):
        nxt = ""                                   # 상대 시점어는 날짜로만 — 틀이 못 지키면 뺀다
    url = fill(ev.get("url", "#/alerts"), data)[0] or "#/alerts"
    body_push = first_fit(ev.get("why"), data, BODY_W) or first_fit(ev.get("next"), data, BODY_W)   # 한 줄 · 사실 하나
    level = hit.fields.get("level") or ev["level"]
    if level not in LEVELS:
        level = ev["level"]
    return {
        "title": title, "why": why, "next": nxt, "url": url, "level": level,
        "body_push": body_push,
        "name": data["name"], "value": data["value"],
    }
