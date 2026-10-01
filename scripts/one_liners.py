#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""이유 한 줄 — 사전 문장 조합. 생성형 AI 를 부르지 않는다(화면 묶음 build_bundles.py 가 쓴다).

갈래는 넷: 주도 업종(sector) · 수급 방향(flow) · 환율 방향(fx) · 다음 일정(schedule).
갈래마다 (긴 꼴, 짧은 꼴) 두 변형을 내고, fit() 이 상한 안에 드는 첫 조합을 고른다.
상한 = PC 44 · 모바일 24, 단위는 표시 폭이다 — 한글·한자 1칸, 영문·숫자·기호·공백 반 칸
(가변폭 글꼴에서 실제 폭에 가깝다. 지표 줄임 이름의 8·12칸도 같은 자로 잰다).

재료가 없거나 그 장(場)의 것이 아니면 갈래를 빼고, 남는 게 없으면 None 이다 — 지어내지 않는다.
"""
from __future__ import annotations

import re
import unicodedata

PC, MOBILE = 44, 24
SEP = " · "


def width(s):
    """표시 폭 — 한글·한자(전각) 1, 나머지 0.5."""
    return sum(1 if unicodedata.east_asian_width(c) in "WF" else 0.5 for c in (s or ""))


def fit(parts, limit):
    """parts = [(긴 꼴, 짧은 꼴), …] 중요한 순. 앞에서부터 가장 많이, 같은 개수면 긴 꼴 먼저.
    모바일(limit ≤ MOBILE)은 짧은 꼴만 — 숫자 섞인 긴 꼴은 폭으론 들어가도 한눈에 안 읽힌다."""
    parts = [p for p in parts if p]
    for k in range(len(parts), 0, -1):
        for i in ((1,) if limit <= MOBILE else (0, 1)):
            s = SEP.join(p[i] for p in parts[:k])
            if width(s) <= limit:
                return s
    return None


def _amt(v):
    """억원 → '9,012억' / 1조 이상 '2.1조'."""
    a = abs(v)
    return "%.1f조" % (a / 10000) if a >= 10000 else "{:,.0f}억".format(a)


def _md(iso):
    m = re.match(r"\d{4}-(\d{2})-(\d{2})", iso or "")
    return "%d/%d" % (int(m.group(1)), int(m.group(2))) if m else (iso or "")


# ── 갈래 4 ────────────────────────────────────────────────────────────────
def sector(items):
    """주도 업종 — 가장 많이 오른 업종. 전부 내렸으면 가장 많이 내린 업종."""
    items = [i for i in (items or []) if isinstance(i.get("chg_pct"), (int, float))]
    if not items:
        return None
    top = max(items, key=lambda i: i["chg_pct"])
    if top["chg_pct"] > 0:
        return ("%s %+.2f%% 주도" % (top["name"], top["chg_pct"]), "%s 주도" % top["name"])
    low = min(items, key=lambda i: i["chg_pct"])
    return ("%s %+.2f%% 하락 주도" % (low["name"], low["chg_pct"]), "%s 약세" % low["name"])


def flow(row):
    """수급 방향 — 외국인 기준, 기관이 같은 쪽이면 함께 적는다(단위 억원)."""
    f = (row or {}).get("foreign")
    if not isinstance(f, (int, float)) or f == 0:
        return None
    side = "순매수" if f > 0 else "순매도"
    i = row.get("inst")
    if isinstance(i, (int, float)) and i != 0 and (i > 0) == (f > 0):
        return ("외국인·기관 %s %s" % (_amt(f + i), side), "외국인·기관 " + side)
    return ("외국인 %s %s" % (_amt(f), side), "외국인 " + side)


def fx(pct):
    """환율 방향 — 달러원 등락률(%) 부호로 원화 강약."""
    if not isinstance(pct, (int, float)):
        return None
    if abs(pct) < 0.05:
        return ("달러원 %+.2f%% 보합" % pct, "환율 보합")
    word = "원화 약세" if pct > 0 else "원화 강세"
    return ("달러원 %+.2f%% %s" % (pct, word), word)


def schedule(ev, today=None, tomorrow=None):
    """다음 일정 — 가장 가까운 예정 발표 하나."""
    if not ev or not ev.get("name"):
        return None
    iso = ev.get("iso")
    when = "오늘" if iso == today else "내일" if iso == tomorrow else _md(iso)
    bare = re.sub(r"\s*\([^)]*\)", "", ev["name"]).strip()
    return ("다음 일정 %s %s" % (when, ev["name"]), "%s %s" % (when, bare))


def move(name, pct):
    """지수 한 줄의 머리 — '코스피 +1.80%'."""
    if not isinstance(pct, (int, float)):
        return None
    word = "상승" if pct > 0 else "하락" if pct < 0 else "보합"
    return ("%s %+.2f%% %s" % (name, pct, word), "%s %s" % (name, word))


# 지표 → 갈래 순서. 투자자 수급·업종은 코스피 것만 수집된다(investorTrading.markets=['KOSPI'],
# sectorMoves=코스피 업종) — 코스닥 줄에 코스피 수급을 붙이면 틀린 이유가 된다.
ROUTES = {
    "kospi": ("sector", "flow", "fx_session"),
    "kosdaq": ("schedule_kr",),
    "usdkrw": ("fx", "flow"),
    "sp500": ("schedule_us",),
    "nasdaq": ("schedule_us",),
    "us10y": ("schedule_us",),
    "wti": ("schedule_us",),
    "gold": ("schedule_us",),
}


def _parts(routes, ctx):
    out = []
    for r in routes:
        if r == "sector":
            out.append(sector(ctx.get("sectors")))
        elif r == "flow":
            out.append(flow(ctx.get("flow")))
        elif r == "fx":
            out.append(fx(ctx.get("fxPct")))
        elif r == "fx_session":                      # 코스피 줄의 환율 조각 = 한국 장중의 움직임만(장 밖 환율은 그 세션 이유가 아니다)
            out.append(fx(ctx.get("fxPctSession")))
        elif r.startswith("schedule"):
            cc = {"schedule_kr": "KR", "schedule_us": "US"}.get(r, "*")
            out.append(schedule((ctx.get("next") or {}).get(cc), ctx.get("today"), ctx.get("tomorrow")))
    return [p for p in out if p]


def reason(ind_id, ctx):
    """띠 한 칸의 이유 한 줄 → {'pc': ≤44, 'mobile': ≤24} (없으면 None)."""
    parts = _parts(ROUTES.get(ind_id, ("schedule",)), ctx)
    return {"pc": fit(parts, PC), "mobile": fit(parts, MOBILE)}


def _first_sentence(text):
    m = re.match(r"(.+?[.!?。])(\s|$)", (text or "").strip())
    return (m.group(1) if m else (text or "")).strip() or None


def today_line(ai_lines, ctx):
    """홈 「오늘 한 줄」 — 오늘 자 aiBriefing 첫 문장이 상한 안이면 그것, 아니면 사전 조합."""
    first = _first_sentence(ai_lines[0]) if ai_lines else None
    parts = [move("코스피", ctx.get("kospiPct"))] + _parts(("sector", "flow", "fx_session", "schedule"), ctx)
    parts = [p for p in parts if p]
    out, src = {}, {}
    for key, limit in (("pc", PC), ("mobile", MOBILE)):
        if first and width(first) <= limit:
            out[key], src[key] = first, "aiBriefing"
        else:
            out[key], src[key] = fit(parts, limit), "rules"
    out["source"] = src
    return out


_PHASE = {"elnino": "엘니뇨", "lanina": "라니냐", "neutral": "중립"}
_STRENGTH = {"weak": "약한", "moderate": "중간", "strong": "강한", "very_strong": "매우 강한"}
_TREND = {"warming": "따뜻해지는 추세", "cooling": "차가워지는 추세", "steady": "안정적"}


def enso_line(enso):
    """엘니뇨 국면 한 줄 — 라벨 사전은 js/app1.js ensoPhaseLabel·ensoStrengthLabel·ensoTrendLabel 과 같다."""
    oni = (enso or {}).get("oni") or {}
    if not isinstance(oni.get("value"), (int, float)):
        return None
    head = (_STRENGTH.get(enso.get("strength"), "") + " " + _PHASE.get(enso.get("phase"), "중립")).strip()
    trend = _TREND.get(enso.get("trend"))
    tail = "ONI %+.1f, %s" % (oni["value"], oni.get("asOf") or "")
    return head + (" · " + trend if trend else "") + " (" + tail.rstrip(", ") + ")"


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    # 자가 점검 — 상한·갈래 탈락·AI 문장 우선
    ctx = {"sectors": [{"name": "기계·장비", "chg_pct": 1.98}, {"name": "화학", "chg_pct": -0.5}],
           "flow": {"foreign": -20646.0, "inst": -7993.0}, "fxPct": 0.25, "fxPctSession": 0.25, "today": "2026-10-01",
           "tomorrow": "2026-10-02", "kospiPct": 1.8,
           "next": {"KR": {"iso": "2026-10-02", "name": "한국 소비자물가동향"},
                    "US": {"iso": "2026-10-02", "name": "미국 비농업고용(NFP)"}}}
    for k in list(ROUTES) + ["unknown"]:
        r = reason(k, ctx)
        assert r["pc"] is None or width(r["pc"]) <= PC, r
        assert r["mobile"] is None or width(r["mobile"]) <= MOBILE, r
        print("%-8s %s | %s" % (k, r["pc"], r["mobile"]))
    assert reason("kospi", {})["pc"] is None                        # 재료 없으면 없다
    long_ai = ["사상 최대 수출 실적에도 불구하고 외국인 순매도가 5일간 9조 원을 넘어서며 수급 불균형이 심화되고 있습니다."]
    t = today_line(long_ai, ctx)
    assert t["source"]["pc"] == "rules" and width(t["pc"]) <= PC, t
    t2 = today_line(["코스피가 반도체 강세로 올랐습니다. 다음 문장."], ctx)
    assert t2["pc"] == "코스피가 반도체 강세로 올랐습니다." and t2["source"]["pc"] == "aiBriefing", t2
    print("오늘 한 줄:", t["pc"], "|", t["mobile"])
    print(enso_line({"phase": "elnino", "strength": "strong", "trend": "warming",
                     "oni": {"value": 1.8, "asOf": "JJA 2026"}}))
    print("ok")
