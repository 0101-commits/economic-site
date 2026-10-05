"""판정 문맥 — data.json · bundles · registry · mer_signals · 달력을 한 번 읽고, 값의 단일 원천을 준다.

`value(target)` 는 번들(화면과 같은 값)에서 먼저 찾고, 없으면 레지스트리 dataPath 로 data.json 을 본다.
`series(target, n)` 은 레지스트리 seriesPath(없으면 dataPath) 의 일봉 n개 [{date, close}] 를 준다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUNDLE_FILES = ("home", "market-domestic", "market-global", "market-fxrates", "market-commodities",
                "market-macro", "market-flows", "market-realestate", "lens", "meta")

# 사전 대상 id → 레지스트리 id 가 다를 때의 별칭(레지스트리에 없는 번들 칸 포함)
ALIASES = {
    "btc": "btc", "vix": "vix_us", "move": "move", "fear_greed": "fear_greed", "vkospi": "vkospi",
    "t10y2y": "t10y2y_us", "ff_target": "ff_target_us", "gold_premium": "gold_premium",
}


def _get(obj, path: str):
    """점 경로 + `a.b:10Y`(만기) 지원. 없으면 None."""
    cur = obj
    for part in path.split("."):
        tenor = None
        if ":" in part:
            part, tenor = part.split(":", 1)
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            return None
        if tenor is not None:
            rows = (cur or {}).get("current") if isinstance(cur, dict) else None
            cur = next((r for r in (rows or []) if r.get("tenor") == tenor), None)
        if cur is None:
            return None
    return cur


@dataclass
class Context:
    now: dt.datetime
    data: dict
    bundles: dict
    registry: dict               # id → 행
    mer: dict
    root: str = ROOT
    _strip: dict = field(default_factory=dict)

    @classmethod
    def load(cls, now: dt.datetime | None = None, root: str = ROOT) -> "Context":
        now = now or dt.datetime.now(KST)
        with open(os.path.join(root, "data.json"), encoding="utf-8") as f:
            data = json.load(f)
        bundles = {}
        for name in BUNDLE_FILES:
            p = os.path.join(root, "bundles", f"{name}.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    bundles[name] = json.load(f)
        reg_rows = bundles.get("registry") or []
        if not reg_rows:
            p = os.path.join(root, "bundles", "registry.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    reg_rows = json.load(f)
        if isinstance(reg_rows, dict):
            reg_rows = reg_rows.get("items") or reg_rows.get("rows") or []
        registry = {r["id"]: r for r in reg_rows if isinstance(r, dict) and "id" in r}
        mer = {}
        p = os.path.join(root, "mer_signals.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                mer = json.load(f)
        ctx = cls(now=now, data=data, bundles=bundles, registry=registry, mer=mer, root=root)
        ctx._index_strips()
        return ctx

    # ---- 번들 띠 색인(화면과 같은 값) ----
    def _index_strips(self) -> None:
        for name, b in self.bundles.items():
            if not isinstance(b, dict):
                continue
            for s in (b.get("strip") or []):
                if isinstance(s, dict) and s.get("id"):
                    self._strip.setdefault(s["id"], s)

    def rid(self, target: str) -> str:
        return ALIASES.get(target, target)

    def strip(self, target: str) -> dict | None:
        return self._strip.get(self.rid(target))

    def value(self, target: str):
        """현재값(화면 값과 같은 원천). 번들 띠 → 레지스트리 dataPath 순."""
        s = self.strip(target)
        if s and s.get("value") is not None:
            return s["value"]
        row = self.registry.get(self.rid(target))
        if row and row.get("dataPath"):
            v = _get(self.data, row["dataPath"])
            if isinstance(v, dict):
                return v.get("value", v.get("price", v.get("rate")))
            return v
        return None

    def change_pct(self, target: str):
        s = self.strip(target)
        if s and s.get("changePct") is not None:
            return s["changePct"]
        return None

    def fresh(self, target: str) -> str:
        s = self.strip(target)
        return (s or {}).get("fresh") or "missing"

    def as_of(self, target: str) -> str:
        s = self.strip(target)
        return (s or {}).get("asOf") or self.now.date().isoformat()

    def series(self, target: str, n: int = 400) -> list[dict]:
        row = self.registry.get(self.rid(target)) or {}
        path = row.get("seriesPath") or row.get("dataPath")
        if not path:
            return []
        v = _get(self.data, path)
        if isinstance(v, dict) and "data" in v:
            v = v["data"]
        if isinstance(v, dict) and "history" in v:          # economicIndicators 잎: {날짜: 값}
            h = v["history"]
            v = [{"date": k, "close": h[k]} for k in sorted(h)]
        if not isinstance(v, list):
            return []
        out = [{"date": r.get("date"), "close": r.get("close", r.get("value"))} for r in v if isinstance(r, dict)]
        return out[-n:]

    @property
    def calendar(self) -> list[dict]:
        return ((self.data.get("economicCalendar") or {}).get("events") or [])

    @property
    def kr_open_today(self) -> bool | None:
        cal = self.data.get("marketCalendarKr") or {}
        today = cal.get("today") or {}
        return today.get("open") if today.get("date") == self.now.date().isoformat() else None
