"""알림 설정 화면 숫자 — 지난 4주 원장에 지금 규칙을 대 보면 하루 몇 통이었나(2026-11-06 알림 개편 P5).

events/stats.json = {v, asOf, from, to, days, sim: {"<꾸러미>:<하루 최대>:<q|n>": [하루 평균, 많은 날]}}
  꾸러미 quiet · normal · many × 하루 최대 1~50 × 조용한 시간 켬(q) · 끔(n). 화면(Alerts 설정 탭)이 고른 값의 칸을 읽어
  「최근 N일 기록으로는 하루 평균 X통, 많은 날 Y통입니다」를 쓴다. 일일 런(run.py --mode daily)이 다시 쓴다.

센다 = 폰 알림 한 통이 되는 것: 시장 사건(내 조건 · 묶음 · 브리핑 행 제외) 중 그때 마스터에게 켜져 있던 것
(발송 기록이 하나라도 있는 행 — 안내는 발송 기록이 없어도 사전 기본 켜짐이면 켜진 것) + 아침 브리핑 1통.
규칙은 schedule.plan 과 같은 차례: 꾸러미 등급 → 조용한 시간(경보만 뚫음, 나머지는 아침 브리핑에 합류) → 이어진 알림
(단계가 오를 때만) → 하루 최대(주의만 세고, 넘으면 그 런의 나머지를 한 통으로 묶음). 사람마다 켠 사건 · 관심 종목이
달라 어림이다 — 화면도 「기록으로는」이라고만 쓴다.
"""
from __future__ import annotations

import datetime as dt
import json
import os

import sys

if __package__ in (None, ""):                          # python scripts/alerts_v2/stats.py 로 바로 돌릴 때
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "alerts_v2"
from alerts_v2 import schema  # noqa: E402
from alerts_v2.ledger import EVENTS_DIR, KST, Ledger  # noqa: E402
from alerts_v2.schedule import story_key, story_rank  # noqa: E402

PACKAGES = ("quiet", "normal", "many")
CAPS = range(1, 51)
DAYS = 28
QUIET = (dt.time(23, 0), dt.time(7, 0))
_SENT_KEYS = ("push", "held", "bundled", "kakao", "memo", "discord", "joined", "folded", "story")


def _personal(r: dict) -> bool:
    ev = str(r.get("event") or "")
    return bool(r.get("cond")) or ev.startswith("U") or ev in ("BUNDLE", "BRIEF") or r.get("level") in ("brief", "record")


def _on(r: dict, default_on: dict) -> bool:
    s = r.get("sent") or {}
    if any(s.get(k) for k in _SENT_KEYS):
        return True
    return r.get("level") == "notice" and r.get("target") in default_on.get(r.get("event"), ())


def _night(r: dict) -> bool:
    try:
        t = dt.datetime.fromisoformat(r["ts"]).astimezone(KST).time()
    except (KeyError, ValueError):
        return False
    return t >= QUIET[0] or t < QUIET[1]


def day_count(rows: list[dict], package: str, cap: int, quiet: bool, morning: bool) -> int:
    """하루 행(시각순) → 폰 알림 통수."""
    n = 1 if morning else 0
    rung, stories, bundles = 0, {}, set()
    for r in rows:
        lv = r.get("level")
        if package == "quiet" and lv != "alarm":
            continue
        if package == "normal" and lv not in ("alarm", "alert"):
            continue
        if package == "many" and lv == "notice":
            lv = "alert"
        if quiet and lv != "alarm" and _night(r):
            continue                                   # 아침 브리핑에 합류 — 따로 울리지 않는다
        sk = story_key(r)
        rank = story_rank(dict(r, level=lv))
        if sk and sk in stories and rank <= stories[sk]:
            continue
        if lv == "alert" and rung >= cap:
            bundles.add(str(r.get("ts") or "")[:16])   # 같은 런(같은 분)의 넘친 것은 한 통
            continue
        n += 1
        if sk:
            stories[sk] = max(stories.get(sk, 0), rank)
        if lv == "alert":
            rung += 1
    return n + len(bundles)


def build(end: dt.date, root: str | None = None, days: int = DAYS) -> dict:
    """end(포함하지 않음 — 오늘은 아직 덜 찼다) 앞 days 일."""
    default_on = {e["id"]: set(e.get("default_on") or []) for e in schema.load_events()}
    by_day: dict[str, list[dict]] = {}
    mornings: set[str] = set()
    span = [(end - dt.timedelta(days=i)).isoformat() for i in range(days, 0, -1)]
    for r in Ledger.load_days(days, end=end - dt.timedelta(days=1), root=root):
        day = str(r.get("ts") or "")[:10]
        if day not in span:
            continue
        if str(r.get("key") or "").startswith("BRIEF:morning:"):
            mornings.add(day)
        if not _personal(r) and _on(r, default_on):
            by_day.setdefault(day, []).append(r)
    seen = [d for d in span if d in by_day or d in mornings]
    sim = {}
    for pkg in PACKAGES:
        for cap in CAPS:
            for q in (True, False):
                v = [day_count(sorted(by_day.get(d, []), key=lambda r: r.get("ts", "")), pkg, cap, q, d in mornings)
                     for d in seen]
                sim[f"{pkg}:{cap}:{'q' if q else 'n'}"] = [round(sum(v) / len(v), 1), max(v)] if v else [0, 0]
    return {"v": 1, "asOf": end.isoformat(), "from": seen[0] if seen else None, "to": seen[-1] if seen else None,
            "days": len(seen), "sim": sim}


def write(end: dt.date | None = None, root: str | None = None) -> str:
    root = root or EVENTS_DIR
    end = end or dt.datetime.now(KST).date()
    out = build(end, root)
    path = os.path.join(root, "stats.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    return path


if __name__ == "__main__":
    p = write()
    s = json.load(open(p, encoding="utf-8"))
    print(f"[v2 stats] {s['from']}~{s['to']} {s['days']}일 · 보통 10통 · 조용한 시간 켬 = {s['sim'].get('normal:10:q')}")
