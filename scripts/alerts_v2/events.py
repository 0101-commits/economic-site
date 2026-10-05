"""사건 추출기 — 사전 행 × 문맥 → Hit 목록 → 원장 행.

판정 함수는 `JUDGES` 에 이름으로 등록한다(사전 `judge` 키와 같은 이름, 파리티 검사 G1).
    @judge("swing_sigma")
    def swing_sigma(ctx, ev) -> list[Hit]: ...
A1~A5 · B · C · H1 은 물결 A6, D · E · F · G · H2~H4 는 A7 이 채운다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable

from .context import Context
from .ledger import Ledger, Row, make_key

JUDGES: dict[str, Callable[[Context, dict], list["Hit"]]] = {}


@dataclass
class Hit:
    target: str
    dir: str                      # up|down|sell|buy|cross|near|new|change|enter|exit
    value: object
    unit: str
    asOf: str
    fresh: str
    chg: float | None = None
    fields: dict = field(default_factory=dict)


def judge(name: str):
    def deco(fn):
        JUDGES[name] = fn
        return fn
    return deco


def run_event(ctx: Context, ev: dict) -> list[Hit]:
    fn = JUDGES.get(ev["judge"])
    if fn is None:
        raise KeyError(f"{ev['id']}: 판정 함수 없음 {ev['judge']!r}")
    return fn(ctx, ev)


def hits_to_rows(ctx: Context, ev: dict, hits: list[Hit], render) -> list[Row]:
    """render(ev, hit) -> {title, why, next, url} — compose.render(물결 B3). 그전엔 사전 title 만."""
    rows = []
    for h in hits:
        txt = render(ev, h) if render else {"title": ev["title"], "why": "", "next": "", "url": ev["url"]}
        rows.append(Row(
            key=make_key(ev["id"], h.target, h.dir, h.asOf or ctx.now.date().isoformat()),
            event=ev["id"], target=h.target, dir=h.dir, level=h.fields.get("level") or ev["level"],
            value=h.value, unit=h.unit, asOf=h.asOf, fresh=h.fresh,
            title=txt["title"], why=txt.get("why", ""), next=txt.get("next", ""), url=txt.get("url") or ev["url"],
            ts=ctx.now.isoformat(timespec="seconds"),
        ))
    return rows


def extract(ctx: Context, events: list[dict], ledger: Ledger, render=None) -> list[Row]:
    """사전 행들을 판정해 원장에 덧붙인다. 새로 들어간 행만 돌려준다(멱등)."""
    new_rows: list[Row] = []
    for ev in events:
        try:
            hits = run_event(ctx, ev)
        except KeyError:
            raise
        except Exception as e:                       # 판정 하나가 죽어도 나머지는 돈다
            print(f"[v2] {ev['id']} 판정 오류: {e!r}")
            continue
        for row in hits_to_rows(ctx, ev, hits, render):
            if ledger.append(row):
                new_rows.append(row)
    return new_rows


def targets_of(ev: dict) -> list[str]:
    return list(ev.get("targets") or [])


def kst_date(ctx: Context) -> str:
    return ctx.now.astimezone(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
