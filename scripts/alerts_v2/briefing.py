"""브리핑 — 시각이 정해진 통(기획서 4장 「브리핑 틀」 · 6장 편성표 · 계약서 B5).

슬롯 6: morning 07:30 · close 16:30 · noon 12:00 · evening 18:30 · us 22:40 · weekly 토 09:00.
이름은 설정 `briefings` 키와 같다. 꺼진 슬롯은 보내지 않는다(기본: 아침 · 마감 · 주간 켜짐).

카드는 기획서 5장 대화창 목업(cards.brief_card_png — 아침 목록 · 마감 칸+하루 흐름+수급 · 주간 칸+행, 2026-10-09
옛 시황 6칸 카드에서 교체). 제목 틀(headline, 48자 상한) · AI 한 문장(slot_ai_line)은 현행 다이제스트를 부른다.
원장에서 오는 것은 세 가지다.
  · 「밤사이 알림 N건」 — 조용한 시간에 보류된 행(deliver.held_rows)을 아침 카드에 싣고 「합류」 표시(held=False)
  · 「오늘 바뀐 것」 — 원장 오늘 안내(notice) 행 묶음 ≤4줄(마감)
  · 휴장 문법 — 휴장일 아침은 머리 「휴장일 아침」, 한국 장 칸 없음 / 마감은 연휴 앞이면 「휴장 · 다음 개장」
상대 시점어(내일 · 다음 주 · 연휴 …)는 쓰지 않는다 — 일정은 날짜로, 걸리는 줄은 뺀다(compose.has_relative_time).
"""
from __future__ import annotations

import datetime as dt
import re

from . import cards, compose, deliver                 # deliver 가 scripts/ 를 sys.path 에 올린다 — 아래 두 줄보다 먼저
from .ledger import Ledger
from .model import DEFAULT_SETTINGS

import discord_card as dc                          # noqa: E402
import send_kakao_digest as k                      # noqa: E402

# 슬롯 → (현행 다이제스트 슬롯 = PROFILES · SLOT_BLOCKS 편성 키, 제목 이름). 시각은 SLOT_AT 한 곳.
SLOTS = {
    "morning": ("h07", "아침"), "noon": ("h12", "점심"), "close": ("h16", "마감"),
    "evening": ("h19", "저녁"), "us": ("h22", "미국 개장"), "weekly": ("h11", "주간"),
}
# KST (시, 분, 요일). briefing.yml 의 cron 이 이것과 같아야 한다(test_slot_schedule 이 대조).
WEEKDAYS = (0, 1, 2, 3, 4)
SLOT_AT = {
    "morning": (7, 30, WEEKDAYS), "noon": (12, 0, WEEKDAYS), "close": (16, 30, WEEKDAYS),
    "evening": (18, 30, WEEKDAYS), "us": (22, 40, WEEKDAYS), "weekly": (9, 0, (5,)),
}
PUSH_SLOTS = ("morning", "close")                    # 폰 푸시는 아침 · 마감만
KR_SLOTS = ("noon", "close", "evening")              # 한국 휴장일엔 보내지 않는다(편성표 「안 나가는 것」)
ITEMS_MAX = 5                                        # 카톡 피드 행 상한(KAKAO_FEED_ROWS)
CHANGED_MAX = 4                                      # 「오늘 바뀐 것」 줄 상한
HELD_LOOKBACK = 3                                    # 금요일 밤 보류분이 월요일 아침에 합류하도록 지난 3일 원장까지
WD = "월화수목금토일"


def enabled(slot: str, settings: dict | None) -> bool:
    b = {**DEFAULT_SETTINGS["briefings"], **((settings or {}).get("briefings") or {})}
    return bool(b.get(slot))


def _md(d) -> str:
    return f"{d.month}/{d.day}"


def _date(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


# ---------- 원장 ----------
def _held(ledger) -> list[tuple]:
    """오늘 + 지난 HELD_LOOKBACK 일 원장의 보류 행 → [(원장, 행)]. 23시대 보류분은 전날 원장에 있다."""
    books = [ledger] + [Ledger(day=ledger.day - dt.timedelta(days=i), root=ledger.root, lookback_days=0)
                        for i in range(1, HELD_LOOKBACK + 1)]
    pairs = [(b, r) for b in books for r in deliver.held_rows(b)]
    return sorted(pairs, key=lambda p: p[1].get("ts", ""))


def changed_lines(rows: list[dict]) -> list[str]:
    """「오늘 바뀐 것」 ≤4줄 — 넘치면 3줄 + 「외 N건」."""
    titles = [r.get("title") or "" for r in rows]
    if len(titles) <= CHANGED_MAX:
        return titles
    return titles[:CHANGED_MAX - 1] + [f"외 {len(titles) - CHANGED_MAX + 1}건"]


# ---------- 일정 · 휴장 ----------
def _ev_day(e: dict, today: dt.date):
    d = _date(e.get("iso"))
    if d:
        return d
    m = re.match(r"(\d{2})\.(\d{2})", str(e.get("dt", "")))
    if not m:
        return None
    try:
        d = dt.date(today.year, int(m[1]), int(m[2]))
    except ValueError:
        return None
    return d.replace(year=today.year + 1) if d < today - dt.timedelta(days=180) else d   # 12월에 보는 1월 일정


def calendar_lines(ctx, start: dt.date, end: dt.date, min_stars: int = 2, after=None, n: int = 3) -> list[str]:
    """[start, end] 의 ★ min_stars 이상 일정 → 「10/6 21:30 미국 CPI ★★★」 시간순 ≤n. after 시각 이전 일정은 뺀다."""
    evs = list(ctx.calendar)
    for i in range((end - start).days + 1):
        evs += k.kr_events(start + dt.timedelta(days=i))          # 규칙으로 정해지는 한국 일정(옵션 만기)
    rows = []
    for e in evs:
        day, stars, hm = _ev_day(e, ctx.now.date()), int(e.get("stars") or 0), str(e.get("dt", ""))[6:11]
        if day is None or not start <= day <= end or stars < min_stars:
            continue
        if after is not None and day == after.date() and hm and hm < after.strftime("%H:%M"):
            continue
        rows.append((day, hm, " ".join(x for x in (_md(day), hm, str(e.get("name", "")).strip(), "★" * stars) if x)))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [s for s in dict.fromkeys(r[2] for r in rows) if not compose.has_relative_time(s)][:n]


def roll_calendar(d: dict, today: dt.date) -> None:
    """data.json 의 한국 영업일 달력이 지난 날 것이면 오늘로 굴린다 — 다음 영업일이 오늘 뒤면 오늘은 휴장
    (fetch_data._toss_change_expected 와 같은 추론). kr_closed 는 오늘 날짜 달력만 믿어서, 수집이 금요일 달력에서
    멈춘 연휴 월요일(2026-10-05 실측: today=10/2 · next=10/6)엔 휴장을 몰랐고 마감 카드가 10/2 종가를 오늘처럼 그렸다.
    다음 영업일이 이미 지났으면 모르는 것이라 그대로 둔다."""
    cal = d.get("marketCalendarKr") or {}
    t = cal.get("today") or {}
    last, nxt = _date(t.get("date")), _date((cal.get("nextBusinessDay") or {}).get("date"))
    if not last or not nxt or last >= today or nxt < today:
        return
    prev = t["date"] if t.get("open") else (cal.get("previousBusinessDay") or {}).get("date")
    d["marketCalendarKr"] = {**cal, "today": {"date": today.isoformat(), "open": nxt == today},
                             "previousBusinessDay": {"date": prev, "open": True}}


def holiday_line(d: dict, now: dt.datetime, slot: str) -> str:
    """오늘 한국 휴장이면 「10/3 한국 휴장 · 다음 개장 10/6」. 마감은 다음 영업일 사이에 평일 휴장이 끼면
    「10/3~10/5 휴장 · 다음 개장 10/6」(주말만이면 빈칸 — 매주 오는 건 소식이 아니다)."""
    cal = d.get("marketCalendarKr") or {}
    nxt = _date((cal.get("nextBusinessDay") or {}).get("date"))
    today = now.date()
    tail = f" · 다음 개장 {_md(nxt)}" if nxt and nxt > today else ""
    if dc.kr_closed(d, now):
        return f"{_md(today)} 한국 휴장{tail}"
    if slot == "close" and nxt and str((cal.get("today") or {}).get("date")) == today.isoformat():
        gap = [today + dt.timedelta(days=i) for i in range(1, (nxt - today).days)]
        if any(g.weekday() < 5 for g in gap):
            return f"{_md(gap[0])}~{_md(gap[-1])} 휴장{tail}"
    return ""


# ---------- 수급 ----------
def flow_streak(ctx) -> tuple[str, int]:
    """외국인 연속 상태(확정치) → (「외국인 5일째 순매도 · 5일 누적 −7.9조(10/1 확정)」, 일수). 판정 D 와 같은 자료 규칙."""
    from .judges_flow_cal import _dir_ko, _eok, _flow, _streak
    rows = _flow(ctx, "foreign")
    vals = [v for *_, v in rows]
    if not vals:
        return "", 0
    n = _streak(vals)
    return f"외국인 {n}일째 {_dir_ko(vals[-1] < 0)} · 5일 누적 {_eok(sum(vals[-5:]))}({_md(rows[-1][0])} 확정)", n


# ---------- 만들기 ----------
def _quotes(ctx, targets) -> tuple[list, dt.date | None]:
    """카드 목록 행 — 기준일이 첫 행(미국 = S&P500)보다 묵은 값엔 「M/D」 꼬리표(금리 FRED 1영업일 지연 등)."""
    qs = [q for q in (cards.quote(ctx, t) for t in targets) if q]
    ref = qs[0][4] if qs else None
    return [(n, v, t, c, _md(day) if day and ref and day < ref else "") for n, v, t, c, day in qs], ref


def _week_tiles(ctx) -> list:
    """주간 칸 4 — 값 + 이번 주 등락(일봉 6개 = 5영업일)."""
    out = []
    for t in ("kospi", "sp500", "usdkrw", "wti"):
        q = cards.quote(ctx, t)
        ser = [p["close"] for p in ctx.series(t, 6) if p.get("close") is not None]
        if q and len(ser) >= 2 and ser[0]:
            c = (ser[-1] / ser[0] - 1) * 100
            out.append(dc._cell(f"{q[0]} 주간", q[1], f"{'▲' if c > 0 else '▼' if c < 0 else '■'}{abs(c):.2f}%", c))
    return out


def _moves(spec: dict, title: str) -> str:
    """AI 문장이 없을 때의 사전 문장 — 카드에서 제목에 안 나온 큰 움직임 둘(「NASDAQ ▼1.25% · WTI 원유 ▲1.15%」)."""
    cand = [(r[0], r[2], r[3]) for r in spec.get("rows") or []] + [(c[0], c[2], c[3]) for c in spec.get("tiles") or []]
    cand = [x for x in cand if x[1] and x[2] is not None and not x[1].endswith("bp")   # 금리(bp)와 %는 크기 비교 불가
            and x[0].split(" ")[0] not in title]
    return " · ".join(f"{n} {t}" for n, t, _c in sorted(cand, key=lambda x: -abs(x[2]))[:2])


def build(slot: str, ctx, ledger, settings: dict | None = None) -> dict:
    """브리핑 한 통 → {title, lines[3], items[≤5], card_png, held_rows, changed_rows, calendar_lines, holiday, links}.

    카드 = 기획서 5장 대화창 목업(cards.brief_card_png): 아침 · 미국 개장은 목록(미국 · 환율 · 금리 · 유가), 마감 · 점심 ·
    저녁은 칸 3 + 코스피 하루 흐름 + 수급 3주체, 주간은 칸 4 + 행. 카톡 행 = 기획서 「행 ≤5」 — 아침은 밤사이 알림 · 오늘
    일정(휴장일은 + 외국인), 마감은 오늘 바뀐 것 · S&P500(전일) · 일정 · 휴장, 주간은 사건 · 가장 큰 움직임 · 다음 주.
    옛 다이제스트 묶음 글(「금리 | 미국채10Y … 한미차 …」)은 행에 싣지 않고 AI 한 문장의 재료로만 넘긴다.
    lines = AI 한 문장(실패하면 경보 · 알림 「왜」 → 카드의 큰 움직임) · 수급/휴장 · 바뀐 것/일정 요약."""
    if slot not in SLOTS:
        raise ValueError(f"모르는 브리핑 슬롯: {slot!r} ({', '.join(SLOTS)})")
    d, now = ctx.data, ctx.now
    lslot, name = SLOTS[slot]
    today = now.date()
    closed = bool(dc.kr_closed(d, now))
    holiday = holiday_line(d, now, slot)
    base = f"{_md(now)}({WD[now.weekday()]}) {'휴장일 아침' if slot == 'morning' and closed else name}"
    held = [r for _, r in _held(ledger)] if slot == "morning" else []
    changed = sorted((r for r in ledger.rows if r.get("level") == "notice"),
                     key=lambda r: r.get("ts", "")) if slot == "close" else []
    hm = f"{_md(now)}({WD[now.weekday()]}) {now:%H:%M}"
    spec = {"foot": f"{now:%m/%d %H:%M} 기준 · ecom"}
    items, mid, ai_blocks = [], "", []

    if slot == "weekly":
        week = [r for r in Ledger.load_days(7, end=ledger.day, root=ledger.root) if r.get("level") != "record"]
        lv = {x: sum(1 for r in week if r.get("level") == x) for x in ("alarm", "alert", "notice")}
        big = max(dc.weekly_rows(d), key=lambda r: abs(r[3]), default=None)
        big_txt = f"{big[0]} {big[3]:+.1f}%" if big else ""
        cal = calendar_lines(ctx, today + dt.timedelta(days=1), today + dt.timedelta(days=7), min_stars=3)
        title = k._fit(base, [f"사건 {len(week)}건", big_txt])
        mid = " · ".join(x for x in (f"{dc.week_period(now)} 사건 {len(week)}건",
                                     big_txt and f"가장 큰 움직임 {big_txt}") if x)
        items = [("사건", f"{len(week)}건 · 경보 {lv['alarm']} · 알림 {lv['alert']} · 안내 {lv['notice']}"),
                 ("가장 큰 움직임", big_txt), ("★★★ 일정", " · ".join(cal)), ("외국인", flow_streak(ctx)[0].removeprefix("외국인 "))]
        loud = [r.get("title") or "" for r in week if r.get("level") in ("alarm", "alert")][-3:]
        spec.update(title=f"주간 · {dc.week_period(now)}", meta=f"{now:%H:%M}", tiles=_week_tiles(ctx),
                    info=items + [("알림" if i == 0 else "", t) for i, t in enumerate(loud)])
        links = k.card_links(d, None, False, now, weekly=True)
        ai_rows = week
    else:
        extra, inv = "", None
        if slot == "morning":
            mid, n = ("", 0) if closed else flow_streak(ctx)
            extra = f"외국인 {n}일째" if n >= 2 else ""
        elif slot == "us":
            mid = dict(k.build_digest_parts(d)[1]).get("금리", "")       # 미국 개장 — 금리 3국 · 한미차 · 장단기
        else:
            inv = k._verified_investor()
            mid = k._investor_row(inv)[1]
            if inv and inv.get("foreign") is not None:
                extra = f"외국인 {inv['foreign']:+,.0f}억" + ("" if inv.get("confirmed") else "(잠정)")
        cal = calendar_lines(ctx, today, today + dt.timedelta(days=1 if slot == "close" else 0), after=now)
        fkey, fz = k.pick_focus(d, lslot, False, now)[:2]
        if closed and fkey in dc._KR_KEYS:             # 휴장일 — 한국 지수 움직임은 어제 것이다
            fkey, fz = None, None
        focus = (fkey, fz) if fkey else None
        title = k.headline(d, lslot, False, now, focus=focus, extra=extra, base=base)[0]
        if slot == "morning" and closed:
            mid = holiday                                # 휴장일 아침 — 수급 대신 휴장 · 다음 개장
        if slot in ("morning", "us"):
            rows, ref = _quotes(ctx, cards.BRIEF_US)
            spec.update(title=f"{base.split(' ', 1)[1]} · {hm}", meta=f"미국 {_md(ref)} 마감" if ref else "", rows=rows)
        else:
            qs = [q for q in (cards.quote(ctx, t) for t in cards.BRIEF_KR) if q]
            kq = cards.quote(ctx, "kospi")                         # 차트는 늘 ^KS11 — 이름 · 값도 코스피 것만
            xs, ys, prev, src = k._intraday_chain("^KS11")          # src = 「일봉 7D」 등 하루 흐름이 아닐 때의 표식
            spec.update(title=f"{name} · {hm}",
                        meta="수급 확정" if inv and inv.get("confirmed") else "수급 잠정" if inv else "수급 집계 중",
                        tiles=[dc._cell(q[0], q[1], q[2], q[3]) for q in qs],
                        chart={"ys": ys, "xs": xs, "prev": prev, "up": bool(ys) and prev is not None and ys[-1] >= prev,
                               "label": f"{kq[0]} {src or '하루 흐름'}" if kq else src, "right": kq[1] if kq else ""},
                        bars=[("외국인", inv.get("foreign")), ("기관", inv.get("inst")), ("개인", inv.get("retail"))]
                        if inv else [])
        if slot == "morning":
            items = [("밤사이 알림", f"{len(held)}건" + (" · " + " · ".join(r.get("title") or "" for r in held[:3])
                                                     if held else "")),
                     ("오늘 일정", " · ".join(cal) or "★★ 이상 없음")]
            if closed:
                items.append(("외국인", flow_streak(ctx)[0].removeprefix("외국인 ")))
        else:
            if changed:
                items.append(("오늘 바뀐 것", f"안내 {len(changed)}건 · " + " · ".join(changed_lines(changed))))
            sp = cards.quote(ctx, "sp500") if slot != "us" else None
            if sp:
                items.append((f"{sp[0]}(전일)", f"{sp[1]} {sp[2]}".strip()))
            if cal:
                items.append(("일정", " · ".join(cal)))
        if holiday and not (slot == "morning" and closed):
            items.append(("휴장", holiday))
        card_items = [x for x in items if x[0] != "오늘 바뀐 것"]       # 카드엔 바뀐 것을 한 줄씩
        if changed:
            card_items = [(f"바뀐 것 {len(changed)}" if i == 0 else "", t)
                          for i, t in enumerate(changed_lines(changed)[:3])] + card_items
        spec["info"] = ([("휴장" if closed else "수급", mid)] if slot == "morning" and mid else []) + card_items
        links = k.card_links(d, lslot, False, now, focus_key=fkey)
        ai_rows = held + list(ledger.rows)
        ai_blocks = k.build_digest_parts(d, slot=lslot)[1]          # 옛 묶음 글 — 행엔 안 싣고 AI 재료로만
    if compose.has_relative_time(title):
        title = base

    items = [(lab, v) for lab, v in items if v and not compose.has_relative_time(f"{lab} {v}")][:ITEMS_MAX]
    spec["info"] = [(lab, v) for lab, v in spec.get("info") or [] if v and not compose.has_relative_time(f"{lab} {v}")]
    ai = k.slot_ai_line(d, lslot, title, [("", mid)] + items + list(ai_blocks))
    if not ai or compose.has_relative_time(ai):        # 사전 문장 — 경보 · 알림 「왜」, 없으면 카드의 큰 움직임
        ai = next((r["why"] for r in ai_rows if r.get("why") and r.get("level") in ("alarm", "alert")), "") \
            or _moves(spec, title)
    summary = " · ".join(([f"오늘 바뀐 것 {len(changed)}건"] if changed else []) + cal)
    lines = [x if x and not compose.has_relative_time(x) else "" for x in (ai, mid, summary)]
    try:
        png = cards.brief_card_png(spec)
    except Exception as e:                             # noqa: BLE001 — 카드가 죽어도 브리핑은 나간다(카톡은 텍스트, 경고 남음)
        print(f"[v2 brief] 카드 렌더 실패: {type(e).__name__} {str(e)[:120]}")
        png = None
    return {"title": title, "lines": lines, "items": items, "card_png": png, "held_rows": held,
            "changed_rows": changed, "calendar_lines": cal, "holiday": holiday, "links": links}


# ---------- 보내기 ----------
def _kakao(out: dict, slot: str, log=print) -> bool:
    ses = deliver._kakao_session(log)                  # uuids None = 메모(나에게 보내기 · 소리 없음)
    if not ses:
        return False
    hb = k._hero_button(out["links"])
    buttons = ([(hb["title"], hb["link"]["web_url"])] if hb else []) + [("대시보드 보기", k.DASHBOARD_URL)]
    try:
        return bool(k.send_card(ses["token"], out["title"], "\n".join(x for x in out["lines"][:2] if x),
                                png=out["card_png"], uuids=ses["uuids"], buttons=buttons,
                                items=[k.kakao_item(lab, v) for lab, v in out["items"]],
                                kind=f"브리핑 {SLOTS[slot][1]}", link_url=k.hero_link(out["links"])))
    except SystemExit:
        return False
    except Exception as e:                             # noqa: BLE001
        log(f"[v2 brief] 카톡 발송 예외: {type(e).__name__}")
        return False


def _discord(out: dict, log=print) -> bool:
    try:
        import notify_discord
        body = "\n".join(x for x in out["lines"] if x)
        fields = [(lab, v, len(v) <= k.DC_FIELD_INLINE_MAX) for lab, v in out["items"] if v not in body]
        return bool(notify_discord.send_level("brief", out["title"], body, fields=fields or None,
                                              url=k.hero_link(out["links"]) or k.DASHBOARD_URL,
                                              buttons=k._dc_link_buttons(out["links"]) or None, png=out["card_png"]))
    except Exception as e:                             # noqa: BLE001
        log(f"[v2 brief] 디스코드 발송 예외: {type(e).__name__}")
        return False


def send(slot: str, ctx, ledger, settings: dict | None = None, dry_run: bool = False, log=print,
         queue_path: str = deliver.PUSH_QUEUE_PATH) -> dict:
    """세 채널 독립 발송 → {push, kakao, discord}. 꺼진 슬롯 · 휴장일 한국 슬롯은 아무것도 안 보낸다.
    보낸 뒤 밤사이 보류 행을 「합류」(held=False)로 적고 그 원장을 저장한다(드라이런은 쓰지 않음)."""
    res = {"push": 0, "kakao": False, "discord": False, "memo": False}
    if not enabled(slot, settings):
        log(f"[v2 brief] {slot} 꺼짐 — 보내지 않음")
        return res
    if slot in KR_SLOTS and dc.kr_closed(ctx.data, ctx.now):
        log(f"[v2 brief] {slot} 한국 휴장 — 보내지 않음")
        return res
    pairs = _held(ledger) if slot == "morning" else []
    out = build(slot, ctx, ledger, settings)
    log(f"[v2 brief{' dry-run' if dry_run else ''}] {slot}: {out['title']}")
    for x in out["lines"] + [f"{lab} | {v}" for lab, v in out["items"]]:
        if x:
            log(f"  {x}")
    if dry_run:
        return res
    ring = ((settings or {}).get("ringChannel") or DEFAULT_SETTINGS["ringChannel"])
    if slot in PUSH_SLOTS and ring != "kakao":
        item = {"id": f"brief:{slot}:{ctx.now.date().isoformat()}", "title": out["title"],
                "body": compose.cut("\n".join(x for x in out["lines"][:2] if x), compose.PUSH_BODY_MAX),
                "url": deliver.abs_url("#/"), "ts": ctx.now.isoformat(timespec="seconds"),
                "level": "brief", "requireInteraction": False}
        res["push"] = 1 if deliver.enqueue_push([item], queue_path) else 0
    res["discord"] = _discord(out, log)                # 울리는 채널 먼저, 카톡(메모면 memo 로 적음)은 마지막
    res["memo" if deliver.memo_mode(log) else "kakao"] = _kakao(out, slot, log)
    if any(res.values()) and pairs:                    # 합류 — 아침 카드가 실제로 나갔을 때만
        for book, r in pairs:
            book.update_sent(r["key"], held=False, push=res["push"], kakao=res["kakao"], memo=res["memo"])
        for book in {id(b): b for b, _ in pairs}.values():
            book.save()
    log(f"[v2 brief] {slot} → push {res['push']} · kakao {res['kakao']} · memo {res['memo']} · discord {res['discord']}")
    return res
