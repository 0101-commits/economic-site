"""브리핑 — 시각이 정해진 통(기획서 4장 「브리핑 틀」 · 6장 편성표 · 계약서 B5).

슬롯 6: morning 07:30 · close 16:30 · noon 12:00 · evening 18:30 · us 22:40 · weekly 토 09:00.
이름은 설정 `briefings` 키와 같다. 꺼진 슬롯은 보내지 않는다(기본: 아침 · 마감 · 주간 켜짐).

카드 · 제목 · 한 문장은 현행 다이제스트(send_kakao_digest · discord_card)를 그대로 부른다 — 편성(PROFILES) ·
제목 틀(headline, 48자 상한) · AI 한 문장(slot_ai_line). 새로 만든 것은 원장에서 오는 세 가지뿐이다.
  · 「밤사이 알림 N건」 — 조용한 시간에 보류된 행(deliver.held_rows)을 아침 카드에 싣고 「합류」 표시(held=False)
  · 「오늘 바뀐 것」 — 원장 오늘 안내(notice) 행 묶음 ≤4줄(마감)
  · 휴장 문법 — 휴장일 아침은 머리 「휴장일 아침」, 한국 장 칸 없음 / 마감은 연휴 앞이면 「휴장 · 다음 개장」
상대 시점어(내일 · 다음 주 · 연휴 …)는 쓰지 않는다 — 일정은 날짜로, 걸리는 줄은 뺀다(compose.has_relative_time).
"""
from __future__ import annotations

import datetime as dt
import re

from . import compose, deliver                    # deliver 가 scripts/ 를 sys.path 에 올린다 — 아래 두 줄보다 먼저
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
def build(slot: str, ctx, ledger, settings: dict | None = None) -> dict:
    """브리핑 한 통 → {title, lines[3], items[≤5], card_png, held_rows, changed_rows, calendar_lines, holiday, links}.

    lines = 움직임(AI 한 문장, 실패하면 원장 첫 행 「왜」) · 수급(휴장일 아침은 휴장 줄) · 바뀐 것/일정 요약.
    items = 카톡 행(이름, 값) — 원장 행(밤사이 · 바뀐 것) → 일정 → 휴장 → 카드에 없는 지표 순, 앞이 남는다.
    카드 타일과 겹치는 지표는 조립 단계에서 뺀다(_card_tile_labels). settings 는 send 가 쓴다(꺼짐 · 울림 채널)."""
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
    head, extras, mid = [], [], ""
    if held:
        head.append((f"밤사이 알림 {len(held)}건", " · ".join(r.get("title") or "" for r in held[:3])))
    if changed:
        head.append((f"오늘 바뀐 것 {len(changed)}건", " · ".join(changed_lines(changed))))

    if slot == "weekly":
        week = [r for r in Ledger.load_days(7, end=ledger.day, root=ledger.root) if r.get("level") != "record"]
        lv = {x: sum(1 for r in week if r.get("level") == x) for x in ("alarm", "alert", "notice")}
        big = max(dc.weekly_rows(d), key=lambda r: abs(r[3]), default=None)
        big_txt = f"{big[0]} {big[3]:+.1f}%" if big else ""
        cal = calendar_lines(ctx, today + dt.timedelta(days=1), today + dt.timedelta(days=7), min_stars=3)
        title = k._fit(base, [f"사건 {len(week)}건", big_txt])
        mid = " · ".join(x for x in (f"{dc.week_period(now)} 사건 {len(week)}건",
                                     big_txt and f"가장 큰 움직임 {big_txt}") if x)
        head += [("사건", f"경보 {lv['alarm']} · 알림 {lv['alert']} · 안내 {lv['notice']}"), ("일정", " · ".join(cal))]
        card = k._build_kakao_card(d, now, None, False, weekly=True, next_week=" · ".join(cal))
        links = k.card_links(d, None, False, now, weekly=True)
        ai_rows = week
    else:
        extra = ""
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
        if slot == "close":
            idx, fx = d.get("indices") or {}, d.get("fx") or {}
            citems = [(lab, k._f((idx.get(key) or {}).get("price")), k._f((idx.get(key) or {}).get("change")))
                      for lab, key in (("코스피", "KOSPI"), ("코스닥", "KOSDAQ"), ("S&P500", "SP500"), ("나스닥", "NASDAQ"))]
            usd = fx.get("USDKRW") or {}
            citems.append(("달러-원", k._f(usd.get("rate")), k._f(usd.get("change"))))
            sm = d.get("stockMovers") or {}
            card = dc.close_report(
                citems, now, alerts_cnt=sum(1 for r in ledger.rows if r.get("level") in ("alarm", "alert")),
                cal=k._dc_cal_line(d, now + dt.timedelta(days=1)), intraday=k._intraday_chain("^KS11"),
                investor=inv,
                movers=(k._kospi_movers(sm.get("kospiGainers"))[:3], k._kospi_movers(sm.get("kospiLosers"))[:3]),
                shape="square")
        else:
            card = k._build_kakao_card(d, now, lslot, False, focus=focus)
            drop = k._card_tile_labels(lslot, False, now)
            extras = [(lab, v) for lab, v in k.build_digest_parts(d, drop=drop, slot=lslot)[1]
                      if v and lab not in ("일정", "수급")]
        if slot == "morning" and closed:
            mid, holiday_row = holiday, []               # 휴장일 아침 — 수급 대신 휴장 · 다음 개장
        else:
            holiday_row = [("휴장", holiday)] if holiday else []
        head += ([("일정", " · ".join(cal))] if cal else []) + holiday_row
        links = k.card_links(d, lslot, False, now, focus_key=fkey)
        ai_rows = held + list(ledger.rows)
    if compose.has_relative_time(title):
        title = base

    items = [(lab, v) for lab, v in head + extras if v and not compose.has_relative_time(f"{lab} {v}")][:ITEMS_MAX]
    ai = k.slot_ai_line(d, lslot, title, [("", mid)] + items)
    if not ai or compose.has_relative_time(ai):        # 사전 문장 — 원장 첫 행 「왜」(기록 등급 제외)
        ai = next((r["why"] for r in ai_rows if r.get("why") and r.get("level") != "record"), "")
    summary = " · ".join(([f"오늘 바뀐 것 {len(changed)}건"] if changed else []) + cal)
    lines = [x if x and not compose.has_relative_time(x) else "" for x in (ai, mid, summary)]
    return {"title": title, "lines": lines, "items": items, "card_png": card, "held_rows": held,
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
