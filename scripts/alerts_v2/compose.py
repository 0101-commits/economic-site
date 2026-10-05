"""문구 틀 — 사건 행 + Hit → 「무엇 · 값 · 왜 · 다음 · 어디」 다섯 칸(기획서 4장).

규칙(계약서 Global Constraints):
  제목 ≤30자(숫자 한 번) · 왜 ≤40 · 다음 ≤40 · 푸시 본문 = 왜 + 줄바꿈 + 다음 ≤80
  묵은 값(prev · kept)은 값 뒤에 「(M/D)」 · 「(이전 값)」 꼬리표 · 상대 시점어 금지 · 금액 없음
템플릿 변수가 비면 그 조각은 조용히 빠지고, 「 · 」 구분자는 정리한다.
"""
from __future__ import annotations

import datetime as dt
import re
import string

from . import LEVELS

TITLE_MAX = 30
BRIEF_TITLE_MAX = 48
LINE_MAX = 40
PUSH_BODY_MAX = 80
DISCORD_MAX = 1500
MINUS = "−"
_REL_WORDS = ("내일", "모레", "다음 주", "다음주", "이번 주", "연휴", "오늘 밤", "어제")

DIR_KO = {
    "up": "상승", "down": "하락", "sell": "순매도", "buy": "순매수", "cross": "돌파", "near": "근접",
    "new": "새로", "change": "변경", "enter": "진입", "exit": "해제",
}
DIR_REV_KO = {"sell": "순매수", "buy": "순매도", "up": "하락", "down": "상승"}


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
    s = re.sub(r"(\s*·\s*)+", " · ", s)
    s = re.sub(r"^\s*·\s*|\s*·\s*$", "", s)
    s = re.sub(r"\(\s*\)", "", s).strip()
    return s


def fill(template: str, data: dict) -> tuple[str, bool]:
    """(채운 글, 빠진 변수 있었나)."""
    f = _Fmt(data)
    out = f.vformat(template, (), {})
    return _tidy(out), f.missing


def first_full(templates, data: dict) -> str:
    """빠진 변수가 없는 첫 틀. 전부 비면 빠진 변수를 뺀 첫 틀."""
    fallback = ""
    for t in templates or []:
        s, missing = fill(t, data)
        if s and not missing:
            return s
        if s and not fallback:
            fallback = s
    return fallback


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
        s = s + "$"
    elif unit in ("원", "주", "p", "호"):
        s = s + unit
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


def _display_name(target: str, ctx) -> str:
    if ctx is not None:
        row = getattr(ctx, "registry", {}).get(getattr(ctx, "rid", lambda t: t)(target)) or {}
        return row.get("short") or row.get("label") or target
    return target


def variables(ev: dict, hit, ctx=None, today: dt.date | None = None) -> dict:
    """틀 변수 사전 — 표준 변수 + Hit.fields."""
    today = today or (ctx.now.date() if ctx is not None else dt.date.today())
    reg = (getattr(ctx, "registry", {}) or {}).get(getattr(ctx, "rid", lambda t: t)(hit.target)) or {} if ctx else {}
    decimals = reg.get("decimals")
    unit = hit.unit or reg.get("unit") or ""
    value = fmt_num(hit.value, unit, decimals)
    tag = stale_tag(hit.fresh, hit.asOf, today)
    d = {
        "name": hit.fields.get("name") or _display_name(hit.target, ctx),
        "target": hit.target,
        "value": _tidy(f"{value} {tag}") if tag else value,
        "value_raw": hit.value,
        "chg": hit.chg,
        "dir": hit.dir,
        "dir_ko": DIR_KO.get(hit.dir, hit.dir),
        "dir_rev_ko": DIR_REV_KO.get(hit.dir, ""),
        "asof_md": _md(hit.asOf),
        "today_md": f"{today.month}/{today.day}",
    }
    for k, v in (hit.fields or {}).items():
        if k == "level":
            continue
        d.setdefault(k, v)
    return d


def _md(as_of: str) -> str:
    try:
        d = dt.date.fromisoformat(str(as_of)[:10])
        return f"{d.month}/{d.day}"
    except (TypeError, ValueError):
        return ""


def render(ev: dict, hit, ctx=None, today: dt.date | None = None) -> dict:
    """다섯 칸 + 채널별 본문. 길이 상한은 여기서 강제한다."""
    data = variables(ev, hit, ctx, today)
    title_max = BRIEF_TITLE_MAX if ev.get("level") == "brief" else TITLE_MAX
    title = cut(fill(ev["title"], data)[0], title_max)
    why = cut(first_full(ev.get("why"), data), LINE_MAX)
    nxt = cut(first_full(ev.get("next"), data), LINE_MAX)
    if has_relative_time(nxt):
        nxt = ""                                   # 상대 시점어는 날짜로만 — 틀이 못 지키면 뺀다
    url = fill(ev.get("url", "#/alerts"), data)[0] or "#/alerts"
    body_push = "\n".join(x for x in (why, nxt) if x)
    if len(body_push) > PUSH_BODY_MAX:
        body_push = why if len(why) <= PUSH_BODY_MAX else cut(why, PUSH_BODY_MAX)
    level = hit.fields.get("level") or ev["level"]
    if level not in LEVELS:
        level = ev["level"]
    return {
        "title": title, "why": why, "next": nxt, "url": url, "level": level,
        "body_push": body_push,
        "body_discord": cut("\n".join(x for x in (why, nxt) if x), DISCORD_MAX),
        "name": data["name"], "value": data["value"],
    }
