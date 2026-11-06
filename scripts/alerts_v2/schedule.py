"""편성 — 조용한 시간 · 하루 최대 · 쿨다운 · 묶음(받는 곳 나누기, 2026-11-06 알림 개편 P1).

plan(decisions, ledger, ctx, settings) -> list[Send]   — 사건 알림은 폰 알림(웹앱 푸시)으로만 간다.
  경보: 하루 최대에 세지 않는다. 조용한 시간에도 보낸다(quietAlarm, 기본 켬).
  주의(alert): 쿨다운(사전 cooldown) → 조용한 시간이면 보류(held = 아침 브리핑에 합류) → 하루 최대 넘으면 한 통으로 묶음.
  안내 · 기록: 폰 알림 없음 — 원장(알림 기록)에 남고 카톡 브리핑이 모아 보여 준다. 「많이」는 subscribe 가 안내를 주의로 올린다.
  카톡은 브리핑만 받는다(briefing.send). 디스코드는 없다(운영 경고 #시스템만).
"""
from __future__ import annotations

import datetime as dt
import re

from . import LEVELS
from . import compose
from .model import DEFAULT_SETTINGS, PACKAGE_CAP, Decision, Send

RING_LEVELS = ("alarm", "alert")
CAP_LEVELS = ("alert",)             # 하루 최대가 세는 등급 — 경보 · 브리핑은 세지 않는다(2026-11-06 사용자 결정)


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
    """오늘 하루 최대에 들어간 폰 알림 수 — 주의 등급 · 묶음 한 통. 아침 브리핑에 합류한 보류분(joined)은 따로 울리지 않았다."""
    n = 0
    for r in ledger.rows:
        if r.get("key") == exclude_key or r.get("level") not in CAP_LEVELS:
            continue
        s = r.get("sent") or {}
        if (s.get("push") or s.get("kakao")) and not s.get("joined") and not s.get("bundled"):
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
        # discord 는 2026-10-13 전 옛 행에만 있다(그 뒤로 경제 알림은 디스코드로 안 나감) — 쿨다운 창 안의 옛 행용
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


# ── 이어진 알림(2026-11-06 알림 개편 P3) ─────────────────────────────
# 같은 날 같은 시장에서 이어진 급변 · 사이드카 · 서킷 · 선 돌파는 한 이야기다. 단계가 오를 때만 폰 알림을 보내고,
# 나머지는 원장에 이야기 이름표(sent.story)만 달아 알림 기록 카드에 모은다. 아이폰 웹 푸시는 같은 tag 로 보내도
# 앞 알림을 바꿔 끼우지 않아(11/6 실기기) 「조용히 고쳐 쓰기」는 쓰지 않는다.
STORY_EVENTS = ("A1", "A2", "A3", "A4", "A5", "B2", "C3", "C4", "C7")
STORY_GROUP = {"kospi": "kr", "kosdaq": "kr", "sp500": "us", "nasdaq": "us", "sox": "us"}


def story_key(row: dict) -> str | None:
    if str(row.get("event") or "") not in STORY_EVENTS or row.get("dir") == "exit":
        return None                                    # 해제(사이드카 · 서킷 풀림)는 단계가 아니다 — 들어간 단계와 같은 순위라 묶이면 해제 알림이 안 나간다
    day = str(row.get("ts") or row.get("asOf") or "")[:10]
    tgt = str(row.get("target") or "")
    return f"{day}:{STORY_GROUP.get(tgt, tgt)}" if day and tgt else None


def story_rank(row: dict) -> int:
    """이야기 안의 단계 — 클수록 높다. 서킷 N단계(20+N) > 사이드카(15) > 경보(12) > 주의(11) > 안내(10)."""
    key = str(row.get("key") or "")
    if m := re.search(r"\.circuit(\d)", key):
        return 20 + int(m.group(1))
    if key.endswith(".sidecar"):
        return 15
    return {"alarm": 12, "alert": 11}.get(str(row.get("level") or ""), 10)


def _story_state(rows) -> dict:
    """오늘 이야기마다 폰 알림으로 보낸 가장 높은 단계."""
    top: dict = {}
    for r in rows or []:
        s = r.get("sent") or {}
        k = s.get("story") or None
        if k and s.get("push") and not s.get("joined"):
            top[k] = max(top.get(k, 0), story_rank(r))
    return top


def plan(decisions: list[Decision], ledger, ctx, settings: dict | None = None,
         events_by_id: dict | None = None, history: list[dict] | None = None,
         kakao_rings: bool = True, story_rows: list | None = None) -> list[Send]:
    """story_rows = 이야기 단계를 읽을 원장 행(기본 ledger.rows). 멤버 편성은 마스터 원장을 넘겨 같은 이야기를 본다."""
    s = _settings(settings)
    now = ctx.now
    stories = _story_state(ledger.rows if story_rows is None else story_rows)
    quiet = in_quiet(now, s.get("quiet"))
    rung = _ring_count_today(ledger)
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
            # 안내 · 울림 밖(관심 아님 · 세기 미달 · 울림 끔) — 폰 알림 없음. 원장(알림 기록)에 이미 있고 카톡 브리핑이 모아 보여 준다.
            # 종전(2026-10-13~11-05)엔 안내도 폰 알림으로 보냈다 — 하루 평균 9.1통 중 안내 1.4통(2026-11-06 기획 D1 로 뺌).
            continue
        if ev and in_cooldown(row, ev, history, rung_only=True):
            continue                                   # 같은 사건 반복 — 원장엔 남고 발송 없음
        if quiet and not (level == "alarm" and s.get("quietAlarm")):
            out.append(Send(row=row, level=level, held=True))
            continue
        sk = story_key(row)
        if sk and sk in stories and story_rank(dict(row, level=level)) <= stories[sk]:
            if story_rows is None:                     # 마스터 원장에만 적는다(멤버 편성은 원장을 안 건드린다)
                ledger.update_sent(row["key"], story=sk, folded=True)
            continue                                   # 같은 이야기의 같은 · 낮은 단계 = 알림 기록 카드에만
        if level == "alert" and rung >= cap:
            bundle.append(row)
            continue
        out.append(Send(row=row, level=level, push=True, kakao=False))
        if sk:
            stories[sk] = max(stories.get(sk, 0), story_rank(dict(row, level=level)))
            if story_rows is None:
                ledger.update_sent(row["key"], story=sk)
        if level == "alert":
            rung += 1

    if bundle:
        title = f"하루 최대를 넘은 알림 {len(bundle)}건"          # 폭 18 안(용어 정제 2차 B) — 「알림 N건 더 · …」 대신
        brow = {
            "key": f"BUNDLE:{now.date().isoformat()}:{now.strftime('%H%M')}",
            "event": "BUNDLE", "target": "bundle", "dir": "new", "level": "alert",
            "value": len(bundle), "unit": "건", "asOf": now.date().isoformat(), "fresh": "live",
            "title": title,
            "why": compose.cut_w(" · ".join(str(r.get("title") or "").split(" · ")[0] for r in bundle[:2]), compose.BODY_W),
            "next": "", "url": "#/alerts",
            "ts": now.isoformat(timespec="seconds"),
        }
        out.append(Send(row=brow, level="alert", push=True, kakao=False,
                        bundled=True, bundle=bundle, kind="bundle"))
        for r in bundle:
            ledger.update_sent(r["key"], bundled=True)
    return out
