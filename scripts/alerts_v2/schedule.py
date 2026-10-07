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


def in_cooldown(row: dict, ev: dict, history: list[dict]) -> bool:
    """사전 cooldown {per:[…], days:N} — 같은 묶음 키로 N일 안에 울린 행이 있으면 참."""
    cd = ev.get("cooldown") or {}
    days = int(cd.get("days") or 0)
    per = list(cd.get("per") or ["target"])
    if days <= 0:
        return False
    def sig(r):
        return tuple(str((r.get(k) if k in ("target", "dir", "level") else (r.get("fields") or {}).get(k, r.get(k)))) for k in per)
    me = sig(row)
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
        if not (s.get("push") or s.get("kakao") or s.get("discord")):
            continue
        try:
            if dt.datetime.fromisoformat(r["ts"]) >= since:
                return True
        except (KeyError, ValueError):
            continue
    return False


def plan(decisions: list[Decision], ledger, ctx, settings: dict | None = None,
         events_by_id: dict | None = None, history: list[dict] | None = None) -> list[Send]:
    s = _settings(settings)
    now = ctx.now
    quiet = in_quiet(now, s.get("quiet"))
    ring_ch = s.get("ringChannel", "push")
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
        if level == "notice":
            out.append(Send(row=row, level=level, discord=True, push=False, kakao=False))
            continue
        if not d.ring:
            out.append(Send(row=row, level=level, discord=True))
            continue
        if ev and in_cooldown(row, ev, history):
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
