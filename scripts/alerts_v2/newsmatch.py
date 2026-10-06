"""뉴스 「왜」 재료 선택기 — 대상 지표의 뉴스 주제 안에서, 제목이 대상 키워드와 실제로 맞는 최신 1건만.

주제 카테고리만 맞고 제목이 무관한 기사(독일경기 칸의 축구 · 연예)는 붙이지 않는다 — 둘 다 만족할 때만, 24시간 이내.
주제 = 레지스트리 행의 `news`(없으면 build_indicators.news_of), 키워드 = build_indicators.KEYWORDS(없으면 별칭 · 이름),
일치 판정 = kwmatch.hit(「유가」가 「유가족」에 걸리는 오탐을 거른다).
"""
from __future__ import annotations

import datetime as dt
import email.utils
import os
import sys

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS not in sys.path:                      # run.py 와 같은 이유 — scripts/ 의 kwmatch · build_indicators 를 쓴다
    sys.path.insert(0, _SCRIPTS)

import build_indicators as bi  # noqa: E402
import kwmatch  # noqa: E402

MAX_AGE = dt.timedelta(hours=24)


def _keywords(row: dict) -> list[str]:
    kws = bi.KEYWORDS.get(row["id"])
    return list(kws) if kws else [x for x in (bi.ALIASES.get(row["id"]) or []) + [row.get("label"), row.get("short")] if x]


def _when(item: dict) -> dt.datetime | None:
    """기사 시각. pubDate(RFC 2822) 가 정본, 없으면 isoDate(날짜만 — 그날 0시로 보아 24시간 판정을 엄격하게)."""
    try:
        t = email.utils.parsedate_to_datetime(item["pubDate"])
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except (KeyError, TypeError, ValueError):
        pass
    try:
        return dt.datetime.fromisoformat(str(item["isoDate"])[:10]).replace(tzinfo=dt.timezone(dt.timedelta(hours=9)))
    except (KeyError, TypeError, ValueError):
        return None


def pick_news(ctx, target: str) -> dict | None:
    """{title, url, topic, ts} 또는 None. 주제 안에서 키워드가 제목에 맞고 24시간 안인 가장 최근 기사 1건."""
    row = ctx.registry.get(ctx.rid(target))
    if not row:
        return None
    topic = row.get("news") or bi.news_of(row["id"], row.get("asset"))
    if not topic:
        return None
    kws = _keywords(row)
    best = None
    for it in (ctx.data.get("news") or {}).get(topic) or []:
        if not isinstance(it, dict) or not it.get("title"):
            continue
        t = _when(it)
        if t is None or ctx.now - t > MAX_AGE or not kwmatch.hit(str(it["title"]), kws):
            continue
        if best is None or t > best[0]:
            best = (t, it)
    if best is None:
        return None
    t, it = best
    return {"title": str(it["title"]).strip(), "url": it.get("url") or "", "topic": topic, "ts": t.isoformat()}
