"""브리핑 아침 · 점심 · 마감 — B안 시세판 카드 + 규칙 글(2026-11-20 개편, 기획 4ioDhgSA ③ ④ ⑤ · 결정 D9=B · D10 · D11).

슬롯 역할(무엇을 어디서 말하나):
  아침 07:30 = 밤사이 · 오늘 — 미국 지수 · 환율 · 금리 · VIX, 어제 수급 「확정 18:00」, 밤사이 발표 결과
  점심 12:00 = 오전장 정리 — 코스피 · 코스닥 오전 등락, 수급 「잠정 HH:MM」(읽은 시각), 오전 시장 조치(공시)
  마감 16:30 = 하루 · 내일 — 마감 등락 · 하루 수급 「잠정 HH:MM」, 오늘 시장 조치, 오늘 밤 · 내일 일정
카드 = 숫자(구역 + 행 + 막대). 카톡 제목 = 결론 한 줄(그 슬롯의 주인공 숫자 하나 — 점심 · 마감은 코스피).
설명 = 카드에 없는 사실 한 문장, 규칙으로 만든다(AI 문장 안 씀 — 숫자가 카드와 어긋났다). 행 = 일과 일정(알림 · 내 조건 ·
다음 일정 · 휴장), 카카오 규격(이름 6자 · 값 25자) 안. 시간띠 · 빈 일정 칸은 없다.
"""
from __future__ import annotations

import datetime as dt
import re

from . import cards, compose
from .context import KST

import send_kakao_digest as k                      # noqa: E402  (briefing 이 scripts/ 를 sys.path 에 올린 뒤 불린다)

BOARD_SLOTS = ("morning", "noon", "close")
SLOT_KO = {"morning": "아침", "noon": "점심", "close": "마감"}
WD = "월화수목금토일"
ROW_LABEL_MAX, ROW_VALUE_MAX = 6, 25               # 카카오 피드 행 규격(이름 6자 · 값 두 줄 25자) — kakao_item 은 20/60 이라 여기서 지킨다
ITEMS_MAX = 5
BAR_CAP = {"kospi": 6, "kosdaq": 6, "sp500": 4, "nasdaq": 4, "usdkrw": 1.5, "vix": 30, "us10y": 30}   # 막대 끝 = 이만큼
FLOW_CAP = 20000                                   # 수급 막대 끝 = 2조
WINDOW = {"morning": (-1, 16, 30), "noon": (0, 7, 30), "close": (0, 12, 0)}   # 행 「알림」 구간 시작(앞 브리핑)


def _md(d) -> str:
    return f"{d.month}/{d.day}"


def _signed(x: float, nd: int = 2, unit: str = "%") -> str:
    return f"{'+' if x > 0 else compose.MINUS if x < 0 else ''}{abs(x):,.{nd}f}{unit}"


def eok(v) -> str:
    """억 → 「−7,368억」 · 1조 넘으면 「−1.24조」."""
    v = float(v)
    s = f"{abs(v) / 10000:.2f}조" if abs(v) >= 10000 else f"{abs(v):,.0f}억"
    return ("+" if v > 0 else compose.MINUS if v < 0 else "") + s


def row_ok(label: str, value: str) -> bool:
    return len(label) <= ROW_LABEL_MAX and len(value) <= ROW_VALUE_MAX


def _fit_row(label: str, value: str) -> tuple[str, str]:
    """카카오 행 규격 안으로 — 이름은 6자, 값은 25자(넘치면 「…」)."""
    label = label[:ROW_LABEL_MAX]
    return label, (value if len(value) <= ROW_VALUE_MAX else value[:ROW_VALUE_MAX - 1] + "…")


# ---------- 카드 재료 ----------
def quote_row(ctx, target: str, name: str | None = None) -> dict | None:
    q = cards.quote(ctx, target)
    if not q:
        return None
    nm, val, txt, c, _day = q
    if re.match(r"^[\d,]{6,}\.\d+$", val):           # 1만 넘는 값(나스닥 23,879.84)은 소수 없이 — 칸 폭
        val = val.split(".")[0]
    if c is None:
        return {"key": target, "name": name or nm, "sub": val, "big": "—", "chg": None, "bar": None}
    bp = txt.endswith("bp")
    big = txt.replace("▲", "+").replace("▼", compose.MINUS).replace("■", "") if bp else _signed(c)
    v = c * 100 if bp else c
    return {"key": target, "name": name or nm, "sub": val, "big": big, "chg": v, "bar": v / BAR_CAP.get(target, 5)}


def flow_rows(vals: dict) -> list[dict]:
    out = []
    for key, nm in (("foreign", "외국인"), ("inst", "기관"), ("retail", "개인")):
        v = vals.get(key)
        if v is None:
            continue
        out.append({"name": nm, "big": eok(v), "chg": float(v), "bar": float(v) / FLOW_CAP})
    return out


def who_line(vals: dict) -> str:
    """「외국인 · 기관 순매도, 개인 순매수」 — 부호로 묶은 한 문장(숫자 없음 — 숫자는 카드가 말한다)."""
    names = {"foreign": "외국인", "inst": "기관", "retail": "개인"}
    sell = [names[k2] for k2 in names if (vals.get(k2) or 0) < 0]
    buy = [names[k2] for k2 in names if (vals.get(k2) or 0) > 0]
    parts = [f"{' · '.join(sell)} 순매도" if sell else "", f"{' · '.join(buy)} 순매수" if buy else ""]
    return ", ".join(p for p in parts if p)


def actions(ctx) -> list[dict]:
    """오늘 지금까지의 시장 조치 공시(사이드카 · 서킷) — 이번 런의 공시 읽기 + 수집 런의 marketHalts(source krx)."""
    from . import judges_market
    today = ctx.now.astimezone(KST).date().isoformat()
    halts = ctx.data.get("marketHalts") or {}
    pool = list(judges_market._kind_today(ctx) or []) + list(halts.get("active") or []) + list(halts.get("history") or [])
    best: dict = {}                                    # 같은 공시가 여러 길로 온다 — 본문 사실(등락률)이 있는 것을 고른다
    for h in pool:
        if isinstance(h, dict) and h.get("source") == "krx" and str(h.get("triggeredAt") or "")[:10] == today:
            cur = best.get(h.get("id"))
            if cur is None or (cur.get("basePct") is None and h.get("basePct") is not None):
                best[h.get("id")] = h
    out, bodies = [], 0
    for h in sorted(best.values(), key=lambda h: str(h.get("triggeredAt") or "")):
        try:
            at = dt.datetime.fromisoformat(str(h.get("triggeredAt")))
        except ValueError:
            continue
        if at > ctx.now:
            continue
        if h.get("basePct") is None and h.get("acptno") and bodies < 3:   # 목록 시각만 있는 공시 — 본문을 한 번 읽는다
            bodies += 1
            try:
                import kind_notices
                facts = kind_notices.body_facts(h["acptno"])
                if facts.get("pct") is not None:
                    h = dict(h, basePct=facts["pct"])
            except Exception:                          # noqa: BLE001
                pass
        typ = h.get("type")
        kind = (f"{'매도' if h.get('direction') != 'up' else '매수'} 사이드카" if typ == "sidecar"
                else f"서킷 {h.get('stage') or 1}단계")
        pct = h.get("basePct")
        out.append({"at": at.astimezone(KST).strftime("%H:%M"), "market": h.get("market"), "kind": kind,
                    "pct": pct, "base": "선물" if typ == "sidecar" else "지수"})
    return out


def action_rows(acts: list[dict]) -> list[dict]:
    rows = []
    for a in acts[-2:]:
        mk = "" if a["market"] == "KOSPI" else "코스닥 "
        big = f"{a['base']} {_signed(float(a['pct']))}" if a.get("pct") is not None else ""
        rows.append({"name": f"{a['at']} {mk}{a['kind']}", "big": big, "chg": a.get("pct"), "plain": True})
    return rows


def releases(ctx, hours: int = 14) -> list[dict]:
    """지난 hours 시간 안에 발표된 ★★ 이상 일정 중 실제 값이 찬 것 — 「미국 소매판매 +0.2% · 예상 +0.1%」."""
    now = ctx.now.astimezone(KST)
    out = []
    for e in ctx.calendar:
        if int(e.get("stars") or 0) < 2 or not e.get("act"):
            continue
        m = re.match(r"(\d{2})\.(\d{2}) (\d{2}):(\d{2})", str(e.get("dt") or ""))
        if not m:
            continue
        try:
            at = dt.datetime(now.year, int(m[1]), int(m[2]), int(m[3]), int(m[4]), tzinfo=KST)
        except ValueError:
            continue
        if at > now:
            at = at.replace(year=now.year - 1)
        if now - dt.timedelta(hours=hours) <= at <= now:
            out.append({"at": at, "name": compose.short_event(str(e.get("name") or "")).split(" (")[0],
                        "act": str(e["act"]), "fore": str(e.get("fore") or ""), "prev": str(e.get("prev") or "")})
    return sorted(out, key=lambda r: r["at"])


def release_rows(rels: list[dict]) -> list[dict]:
    rows = []
    for r in rels[-2:]:
        rows.append({"name": r["name"], "sub": f"예상 {r['fore']}" if r["fore"] else "",
                     "big": compose._tidy(r["act"]), "chg": None, "plain": False})
    return rows


# ---------- 글 ----------
def _pct1(c) -> str:
    return _signed(float(c), 1) if c is not None else ""


def _ledger_rows(ledger, slot: str, now: dt.datetime) -> list[dict]:
    from .briefing import _window_rows
    back, h, m = WINDOW[slot]
    d = now.date() + dt.timedelta(days=back)
    t0 = dt.datetime(d.year, d.month, d.day, h, m, tzinfo=KST)
    try:
        return _window_rows(ledger, t0, now)
    except Exception as e:                             # noqa: BLE001 — 원장이 깨져도 브리핑은 나간다
        print(f"[v2 brief] 원장 행 실패: {type(e).__name__}")
        return []


def _personal(r: dict) -> bool:
    return bool(r.get("cond")) or str(r.get("event") or "").startswith("U") or r.get("event") == "BUNDLE"


def feed_items(slot: str, ctx, ledger, next_line: str, holiday: str, changed: list | None = None) -> list[tuple[str, str]]:
    """행 ≤5 — 알림(경보 · 주의, 시장 조치는 카드가 싣는다) ≤2 · 내 조건 ≤1 · 안내(마감, 오늘 안내 행 수 · 첫 제목) · 다음 일정 · 휴장.
    안내 행은 합침 사건(G3 · E5)이 카톡에 닿는 유일한 길이라 마감에 늘 싣는다."""
    rows = _ledger_rows(ledger, slot, ctx.now)
    market = [r for r in rows if r.get("level") in ("alarm", "alert") and not _personal(r) and r.get("event") != "A5"]
    mine = [r for r in rows if _personal(r) and r.get("event") != "BUNDLE"]
    out = []
    seen = set()
    for r in sorted(market, key=lambda r: (r.get("level") != "alarm", r.get("ts", ""))):
        story = (r.get("sent") or {}).get("story") or (r.get("event"), r.get("target"))
        if story in seen:
            continue
        seen.add(story)
        t = cards._hhmm(r.get("ts"))
        head = re.sub(r"(?<![\w.])-(?=\d)", compose.MINUS, str(r.get("title") or "").split(" · ")[0]).strip()
        out.append(("알림", f"{t} {head}".strip()))
        if len(out) == 2:
            break
    if mine:
        r = mine[-1]
        head = str(r.get("title") or "").split(" · ")[0]
        out.append(("내 조건", re.sub(r"(?<![\w.])-(?=\d)", compose.MINUS, head).strip()))
    if changed:
        out.append(("안내", f"{len(changed)}건 · {changed[0].get('title') or ''}".strip()))
    if next_line:
        out.append(("다음 일정", next_line))
    if holiday:
        out.append(("휴장", holiday))
    return [_fit_row(lab, v) for lab, v in out if v][:ITEMS_MAX]


def next_line(slot: str, ctx) -> str:
    """다음 ★★★ 일정 한 줄 — 지금 뒤 7일 안 첫 일정(마감은 오늘 밤 미국 일정 포함). 「11/25(수) 22:30 미국 GDP」."""
    from .briefing import calendar_lines
    today = ctx.now.date()
    lines = calendar_lines(ctx, today, today + dt.timedelta(days=7), min_stars=3, after=ctx.now, n=1)
    m = re.match(r"(\d+)/(\d+)(?: (\d{2}:\d{2}))? (.+?) ★+$", lines[0]) if lines else None
    if not m:
        return ""
    try:
        d = dt.date(today.year + (int(m[1]) < today.month), int(m[1]), int(m[2]))
    except ValueError:
        return ""
    word = "오늘" if d == today else f"{_md(d)}({WD[d.weekday()]})"
    return " ".join(x for x in (word, m[3], compose.short_event(m[4])) if x)


def push_lines(title_fact: str, body_cands: list[str], slot: str) -> tuple[str, str]:
    """폰 알림 — 제목 「점심 브리핑 · 코스피 −4.8%」(18칸) · 본문 20칸 첫 후보."""
    name = f"{SLOT_KO[slot]} 브리핑"
    head = f"{name} · {title_fact}" if title_fact else name
    title = head if compose.width(head) <= compose.TITLE_W else name
    body = next((c for c in body_cands if c and compose.width(c) <= compose.BODY_W), "")
    if not body and body_cands:
        body = compose.cut_w(next((c for c in body_cands if c), ""), compose.BODY_W)
    return title, body


# ---------- 만들기 ----------
def build(slot: str, ctx, ledger, holiday: str = "", closed: bool = False, held: list | None = None,
          changed: list | None = None) -> dict:
    """→ briefing.build 와 같은 모양 {title, lines, items, card_png, push, public_push, …}."""
    from .judges_flow_cal import _flow, _streak
    now = ctx.now.astimezone(KST)
    date_ko = f"{_md(now)}({WD[now.weekday()]})"
    sections, body, desc = [], [], ""
    if slot == "morning":
        rows = [quote_row(ctx, t, nm) for t, nm in (("sp500", "S&P 500"), ("nasdaq", "나스닥"), ("usdkrw", "원·달러"),
                                                    ("us10y", "미국 10년"), ("vix", "VIX"))]
        rows = [r for r in rows if r]
        sp = cards.quote(ctx, "sp500")
        sections.append({"head": f"밤사이 해외{f' · 미국 {_md(sp[4])} 마감' if sp and sp[4] else ''}", "rows": rows})
        fl = _flow(ctx, "foreign")
        if fl:
            d, r, _v = fl[-1]
            vals = {k2: r.get(k2) for k2 in ("foreign", "inst", "retail")}
            sections.append({"head": f"수급 {_md(d)}", "tag": "확정 18:00", "rows": flow_rows(vals)})
            n = _streak([v for *_, v in fl])
            desc = (f"외국인 {n}일째 {'순매도' if fl[-1][2] < 0 else '순매수'} · 5일 누적 "
                    f"{eok(sum(v for *_, v in fl[-5:]))}({_md(d)} 확정)") if n >= 2 else f"{who_line(vals)}({_md(d)} 확정)"
        rels = releases(ctx)
        if rels:
            sections.append({"head": "밤사이 발표", "rows": release_rows(rels)})
        hero = rows[0] if rows and rows[0]["key"] == "sp500" else None
        fact = f"S&P 500 {_pct1(hero['chg'])}" if hero and hero["chg"] is not None else ""
        others = sorted((r for r in rows[1:] if r["chg"] is not None and r["key"] != "us10y"),
                        key=lambda r: -abs(r["chg"]) / BAR_CAP.get(r["key"], 5))      # 평소 크기 대비 큰 움직임 먼저
        body = [" · ".join(f"{r['name']} {_pct1(r['chg'])}" for r in others[:2]),
                *(f"{r['name']} {_pct1(r['chg'])}" for r in others[:1])]
        if rels:
            r0 = rels[-1]
            body.insert(0, f"{r0['name']} {r0['act']}")
        title = f"{'휴장일 아침' if closed else '아침'} · {fact}" if fact else ("휴장일 아침" if closed else "아침")
        meta = date_ko
    else:
        kr = [quote_row(ctx, "kospi", "코스피"), quote_row(ctx, "kosdaq", "코스닥"), quote_row(ctx, "usdkrw", "원·달러")]
        kr = [r for r in kr if r]
        sections.append({"head": "국내 지수 · 오전" if slot == "noon" else "국내 지수 · 마감", "rows": kr})
        inv = k._verified_investor()
        tag = ""
        if inv and inv.get("foreign") is not None:
            vals = {k2: inv.get(k2) for k2 in ("foreign", "inst", "retail")}
            tag = "확정" if inv.get("confirmed") else f"잠정 {now:%H:%M}"
            sections.append({"head": "수급", "tag": tag, "rows": flow_rows(vals)})
            fl = _flow(ctx, "foreign")
            n = _streak([v for *_, v in fl] + [float(vals["foreign"])]) if fl else 0
            desc = who_line(vals) + (f" · 외국인 {n}일째" if n >= 2 else "") + f"({tag})"
        else:
            sections.append({"head": "수급", "rows": [{"name": "집계 중", "big": "", "plain": True}]})
        acts = actions(ctx)
        if acts:
            sections.append({"head": "시장 조치" + (" · 오전" if slot == "noon" else ""), "rows": action_rows(acts)})
        hero = kr[0] if kr and kr[0]["key"] == "kospi" else None
        fact = f"코스피 {_pct1(hero['chg'])}" if hero and hero["chg"] is not None else ""
        title = f"{SLOT_KO[slot]} · {'오전 ' if slot == 'noon' else ''}{fact}" if fact else SLOT_KO[slot]
        kq = next((r for r in kr if r["key"] == "kosdaq"), None)
        f_txt = f"외국인 {eok(inv['foreign'])}" if inv and inv.get("foreign") is not None else ""
        kacts = [a for a in acts if a["market"] == "KOSPI"]
        a_txt = kacts[-1]["kind"] if kacts else (f"코스닥 {acts[-1]['kind']}" if acts else "")
        k_txt = f"코스닥 {_pct1(kq['chg'])}" if kq and kq["chg"] is not None else ""
        body = [" · ".join(x for x in (a_txt, f_txt) if x), " · ".join(x for x in (k_txt, f_txt) if x), f_txt, k_txt]
        meta = f"{date_ko} {now:%H:%M}" if slot == "noon" else f"{date_ko} 15:30 마감"
    nxt = next_line(slot, ctx)
    items = feed_items(slot, ctx, ledger, nxt, holiday, changed)
    spec = {"title": f"{SLOT_KO[slot]} 브리핑", "meta": meta, "sections": sections,
            "foot": f"ecom · {_md(now)} {now:%H:%M} 기준"}
    try:
        png = cards.board_card_png(spec)
    except Exception as e:                             # noqa: BLE001 — 카드가 죽어도 브리핑은 나간다(카톡은 텍스트)
        print(f"[v2 brief] 카드 렌더 실패: {type(e).__name__} {str(e)[:120]}")
        png = None
    p_title, p_body = push_lines(fact, body, slot)
    desc = re.sub(r"(?<![\w.])-(?=\d)", compose.MINUS, desc)
    lines = [desc, "", nxt]
    links = k.card_links(ctx.data, {"morning": "h07", "noon": "h12", "close": "h16"}[slot], False, now)
    return {"title": title, "lines": lines, "items": items, "card_png": png, "held_rows": held or [],
            "changed_rows": list(changed or []), "calendar_lines": [nxt] if nxt else [], "holiday": holiday, "links": links,
            "caption": desc, "card_info": [], "public_title": title, "public_lines": [desc, ""],
            "push": (p_title, p_body), "public_push": (p_title, p_body), "spec": spec}
