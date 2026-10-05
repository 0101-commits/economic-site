"""이력 1점 묶음의 일일 적재기 — 현재값 한 점만 보관하던 지표에 하루 한 점씩 쌓는다.

대상(42): VKOSPI · 금 김프 · 운임 9 · LME 재고 6 · 시장 폭(코스피 상승·하락) · 업종 23.
`events/history/<key>.json` = [{date, value}] 날짜 오름차순 · 끝 400점. 같은 날짜는 한 점(나중 값이 이긴다 — 잠정 → 확정).
날짜 = 소스가 준 기준일(수집일이 아니다). 직전 값 보강(kept) · 값 없음은 싣지 않는다 — 묵은 값을 오늘 날짜로 찍지 않으려고.
`run.py --mode daily` 가 부른다.
"""
from __future__ import annotations

import os
import re

from .ledger import _read, _write

TAIL = 400


def _key(prefix: str, name: str) -> str:
    return f"{prefix}_{re.sub(r'[^0-9A-Za-z가-힣]+', '_', str(name)).strip('_').lower()}"


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def points(ctx) -> dict[str, tuple[str, float]]:
    """오늘 적재할 {키: (기준일, 값)}. 값이 없거나 묵은 칸은 빠진다."""
    out: dict[str, tuple[str, float]] = {}

    def put(key, date, value):
        if _num(value) is not None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date or "")[:10]):
            out[key] = (str(date)[:10], value)

    for key in ("vkospi", "gold_premium"):                       # 번들 띠 — 화면과 같은 값
        s = ctx.strip(key) or {}
        if s.get("state") not in ("kept", "missing"):
            put(key, s.get("asOf"), s.get("value"))
    d = ctx.data
    for f in ((d.get("freight") or {}).get("items") or []):
        put(_key("freight", f.get("code")), f.get("date"), f.get("price"))
    lme = d.get("lmeInventory") or {}
    if not lme.get("preserved"):
        for m in lme.get("data") or []:
            put(_key("lme", m.get("name")), lme.get("as_of"), m.get("cur"))
    br = (d.get("marketBreadth") or {}).get("kospi") or {}
    if not br.get("preserved"):
        for side in ("up", "down"):
            put(f"breadth_kospi_{side}", br.get("as_of"), br.get(side))
    sm = d.get("sectorMoves") or {}
    if not sm.get("preserved"):
        for it in sm.get("items") or []:
            if not it.get("preserved"):
                put(_key("sector", it.get("name")), sm.get("as_of"), it.get("close"))
    return out


def add(rows: list[dict], date: str, value) -> list[dict]:
    """날짜 하나를 멱등으로 더한다 — 같은 날짜는 값을 갈아끼우고, 끝 400점만 남긴다."""
    by = {r["date"]: r["value"] for r in rows if isinstance(r, dict) and "date" in r}
    by[date] = value
    return [{"date": k, "value": by[k]} for k in sorted(by)][-TAIL:]


def run(ctx, dry_run: bool = False) -> list[str]:
    """적재하고, 새 점이 생겼거나 값이 바뀐 키 목록을 돌려준다."""
    folder = os.path.join(ctx.root, "events", "history")
    todo = points(ctx)
    changed = []
    for key, (date, value) in sorted(todo.items()):
        path = os.path.join(folder, f"{key}.json")
        old = _read(path)
        new = add(old, date, value)
        if new != old:
            changed.append(key)
            if not dry_run:
                _write(path, new)
    print(f"[v2] 이력 적재 {len(changed)}/{len(todo)}개{' (dry-run)' if dry_run else ''}")
    return changed
