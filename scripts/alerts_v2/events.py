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
    hits = fn(ctx, ev)
    scale = getattr(ctx, "scale", None)
    for h in hits:                                   # 값은 화면 단위로(엔/원 원본 8.51 → 851원) — 사용자 조건(subscribe)과 같은 단위
        sc = scale(h.target) if scale else None
        if sc and isinstance(h.value, (int, float)) and not isinstance(h.value, bool):
            h.value = h.value / sc
    return hits


def _tier(ev: dict, h) -> str:
    """급변(swing_sigma) 원장 키 꼬리 = 세기 단계(2 · 2.5 · 3σ). 키가 `사건:대상:방향:거래일` 하나면 장중 2.2σ 에서
    먼저 들어간 행이 같은 날 2.6σ(알림) · 3.1σ(경보 격상) 행을 멱등 검사로 막아, 정작 큰 장에 안 울렸다(2026-10-11 점검).
    단계마다 한 행 — 같은 단계는 여전히 하루 한 번이다."""
    if ev.get("judge") != "swing_sigma":
        return ""
    z = h.fields.get("abs_z")
    if not isinstance(z, (int, float)):
        return ""
    return ":3s" if z >= 3.0 else ":2.5s" if z >= 2.5 else ":2s"


ROW_KEYS = ("target", "dir", "level", "cond")


def _cd_of(ev: dict, h) -> dict | None:
    """쿨다운 묶음 키 가운데 원장 행 칸이 아닌 것(rcp · stage · label · date · period …)의 값 — schedule.in_cooldown 이 읽는다.
    종전엔 행에 없어 None 끼리 같다고 보고, 관심 종목 첫 공시 뒤 1년간 그 종목 공시가 전부 막혔다(F1 [target, rcp] 365일)."""
    per = [k for k in ((ev.get("cooldown") or {}).get("per") or []) if k not in ROW_KEYS]
    if not per:
        return None
    return {k: (str(h.fields.get(k)) if h.fields.get(k) not in (None, "") else None) for k in per}


def _line_of(fields: dict):
    """판정 변수의 선(렌즈 line · 마디 level_value) → float. 글자(「7,000」)도 읽는다. 없으면 None."""
    v = fields.get("line", fields.get("level_value"))
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except ValueError:
        return None


def hits_to_rows(ctx: Context, ev: dict, hits: list[Hit], render) -> list[Row]:
    """render(ev, hit) -> {title, why, next, url} — compose.render(물결 B3). 그전엔 사전 title 만."""
    rows = []
    for h in hits:
        txt = render(ev, h) if render else {"title": ev["title"], "why": "", "next": "", "url": ev["url"]}
        rows.append(Row(
            key=make_key(ev["id"], h.target, h.dir, h.asOf or ctx.now.date().isoformat()) + _tier(ev, h),
            event=ev["id"], target=h.target, dir=h.dir, level=h.fields.get("level") or ev["level"],
            value=h.value, unit=h.unit, asOf=h.asOf, fresh=h.fresh,
            title=txt["title"], why=txt.get("why", ""), next=txt.get("next", ""), url=txt.get("url") or ev["url"],
            ts=ctx.now.isoformat(timespec="seconds"),
            chg=h.chg, z=h.fields.get("abs_z"), line=_line_of(h.fields), cd=_cd_of(ev, h),
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
