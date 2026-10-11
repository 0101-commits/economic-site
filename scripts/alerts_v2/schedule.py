"""편성 — 조용한 시간 · 하루 상한 · 쿨다운 · 묶음 · 카톡 쿼터(기획서 2장 · 5장 · 6장).

plan(decisions, ledger, ctx, settings) -> list[Send]
  경보: 상한 밖, 조용한 시간은 quietAlarm 설정에 따라.
  알림: 쿨다운(사전 cooldown) → 조용한 시간이면 보류(held, 디스코드는 쌓임) → 하루 상한 넘으면 묶음.
  안내: 디스코드만(카톡 메모 모드면 deliver 가 메모도 따라 보냄). 기록: 발송 없음.
  카톡: 쌍당 하루 kakaoBundleAt(18) 부터 묶음, kakaoQuota(20) 에서 멈춤.
"""
from __future__ import annotations

import datetime as dt

from . import LEVELS
from .model import DEFAULT_SETTINGS, PACKAGE_CAP, Decision, Send

RING_LEVELS = ("alarm", "alert")


def _hm(s: str) -> dt.time:
    h, m = str(s).split(":")[:2]
    return dt.time(int(h), int(m))


def in_quiet(now: dt.datetime, quiet: dict | None) -> bool:
    if not quiet:
        return False
    a, b = _hm(quiet.get("from", "23:00")), _hm(quiet.get("to", "07:00"))
    t = now.time().replace(second=0, microsecond=0)
    return (a <= t or t < b) if a > b else (a <= t < b)


def _settings(user: dict | None) -> dict:
    s = dict(DEFAULT_SETTINGS)
    for k, v in (user or {}).items():
        if v is not None or k == "quiet":          # quiet=None = 조용한 시간 끔(v2 화면이 그렇게 저장한다)
            s[k] = v
    s["dailyCap"] = int((user or {}).get("dailyCap") or PACKAGE_CAP.get(s.get("package", "normal"), 6))
    return s


def _ring_count_today(ledger, exclude_key: str | None = None) -> int:
    n = 0
    for r in ledger.rows:
        if r.get("key") == exclude_key or r.get("level") not in RING_LEVELS:
            continue
        s = r.get("sent") or {}
        if s.get("push") or s.get("kakao"):
            n += 1
    return n


def _kakao_count_today(ledger) -> int:
    return sum(1 for r in ledger.rows if (r.get("sent") or {}).get("kakao"))


def in_cooldown(row: dict, ev: dict, history: list[dict], rung_only: bool = False) -> bool:
    """사전 cooldown {per:[…], days:N} — 같은 묶음 키로 N일 안에 나간 행이 있으면 참.
    rung_only = 울림(푸시 · 카톡 · 경보 디스코드)만 센다(울림 판정용). 경보는 경보만 센다 — 같은 날 2.5σ 알림 뒤의
    3σ 경보 격상을 막지 않게."""
    cd = ev.get("cooldown") or {}
    days = int(cd.get("days") or 0)
    per = list(cd.get("per") or ["target"])
    if days <= 0:
        return False
    def sig(r):
        cd = r.get("cd") or {}
        return tuple(r.get(k) if k in ("target", "dir", "level", "cond") else cd.get(k, r.get(k)) for k in per)
    me = sig(row)
    if any(v is None for v in me):
        return False                                   # 묶음 키를 모르면 막지 않는다(옛 행 · 값 없는 판정) — None 끼리 같다고 보지 않는다
    try:
        since = dt.datetime.fromisoformat(row["ts"]) - dt.timedelta(days=days)
    except (KeyError, ValueError):
        return False
    for r in history:
        if r.get("key") == row.get("key") or r.get("event") != row.get("event"):
            continue
        if sig(r) != me:
            continue
        s = r.get("sent") or {}
        if row.get("level") == "alarm" and r.get("level") != "alarm":
            continue
        rang = s.get("push") or s.get("kakao") or s.get("held") or (s.get("discord") and r.get("level") == "alarm")
        if not (rang if rung_only else (rang or s.get("discord") or s.get("memo"))):
            continue
        try:
            if dt.datetime.fromisoformat(r["ts"]) >= since:
                return True
        except (KeyError, ValueError):
            continue
    return False


CLOSE_BRIEF_AT = dt.time(16, 30)


def close_brief_ahead(ctx, s: dict) -> bool:
    """오늘 마감 브리핑이 아직 나갈 예정인가 — 한국 영업일 · 16:30 전 · 마감 브리핑 켜짐. 아니면 합침 사건도 낱개로 보낸다
    (안 그러면 주말 · 휴장일 · 장 마감 뒤 메르 새 글이 원장 밖 어디에도 안 나간다)."""
    now = ctx.now
    if now.weekday() >= 5 or now.time() >= CLOSE_BRIEF_AT:
        return False
    if not ((s.get("briefings") or {}).get("close", True)):
        return False
    try:
        import discord_card as dc
        return not dc.kr_closed(getattr(ctx, "data", {}) or {}, now)
    except Exception:                                  # noqa: BLE001
        return True


def plan(decisions: list[Decision], ledger, ctx, settings: dict | None = None,
         events_by_id: dict | None = None, history: list[dict] | None = None,
         kakao_rings: bool = True) -> list[Send]:
    s = _settings(settings)
    now = ctx.now
    quiet = in_quiet(now, s.get("quiet"))
    ring_ch = s.get("ringChannel", "push")
    if ring_ch == "kakao" and not kakao_rings:
        ring_ch = "push"                               # D11 — 카톡이 울리지 않으면(메모 모드) 폰 푸시로. 둘 다 안 울리던 것
    push_on = ring_ch in ("push", "both")
    kakao_on = ring_ch in ("kakao", "both")
    rung = _ring_count_today(ledger)
    kakao_n = _kakao_count_today(ledger)
    cap = s["dailyCap"]
    history = history if history is not None else []
    out: list[Send] = []
    bundle: list[dict] = []

    for d in decisions:
        row, level = d.row, d.level
        if level not in LEVELS or level == "record":
            continue
        ev = (events_by_id or {}).get(row.get("event"), {})
        if ev.get("merge") == "close" and close_brief_ahead(ctx, s):
            continue                                   # 오늘 16:30 마감 브리핑 「오늘 바뀐 것」에 합침(G3 메르 새 글 · E5 휴장 — 기획서 3장)
        if not d.ring or level == "notice":
            # 안내 · 보관 — 켜진 것만, 쿨다운 · 조용한 시간을 거친다. 종전엔 둘 다 없이 곧장 디스코드(+ 카톡 메모)로
            # 나가 52주 신저가 사흘 연속 · 마디 하루 상승 · 하락 두 번 · 메르 새 글 새벽 4시가 울렸다(2026-10-11 점검).
            if level != "notice" or not getattr(d, "on", True):
                continue                               # 울림 밖 알림(관심 아님 · 세기 미달 · 울림 끔) = 원장 · 받은 알림에만
            if ev and in_cooldown(row, ev, history):
                continue
            out.append(Send(row=row, level=level, discord=True, push=False, kakao=False, held=quiet))
            continue
        if ev and in_cooldown(row, ev, history, rung_only=True):
            continue                                   # 같은 사건 반복 — 원장엔 남고 발송 없음
        if quiet and not (level == "alarm" and s.get("quietAlarm")):
            out.append(Send(row=row, level=level, discord=True, held=True))
            continue
        if level == "alert" and rung >= cap:
            bundle.append(row)
            continue
        push = push_on
        kakao = kakao_on and kakao_n < s["kakaoBundleAt"]
        if kakao_on and s["kakaoBundleAt"] <= kakao_n < s["kakaoQuota"] and level != "alarm":
            bundle.append(row)
            continue
        out.append(Send(row=row, level=level, push=push, kakao=kakao, discord=True))
        if level == "alert":
            rung += 1
        if kakao:
            kakao_n += 1

    if bundle:
        first = bundle[0]
        title = f"알림 {len(bundle)}건 더 · {first.get('title', '')}"
        if len(title) > 30:
            title = title[:29] + "…"
        brow = {
            "key": f"BUNDLE:{now.date().isoformat()}:{now.strftime('%H%M')}",
            "event": "BUNDLE", "target": "bundle", "dir": "new", "level": "alert",
            "value": len(bundle), "unit": "건", "asOf": now.date().isoformat(), "fresh": "live",
            "title": title,
            "why": " · ".join((r.get("title") or "")[:14] for r in bundle[:3]),
            "next": "상한 넘어 묶음 — 보관함에서 펼침", "url": "#/alerts",
            "ts": now.isoformat(timespec="seconds"),
        }
        kakao_b = kakao_on and kakao_n < s["kakaoQuota"]
        out.append(Send(row=brow, level="alert", push=push_on, kakao=kakao_b, discord=True,
                        bundled=True, bundle=bundle, kind="bundle"))
        for r in bundle:
            ledger.update_sent(r["key"], bundled=True)
    return out
