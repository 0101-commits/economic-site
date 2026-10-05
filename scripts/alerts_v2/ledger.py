"""사건 원장 — events/YYYY-MM-DD.json(추가만, 멱등) + events/latest.json(최근 7일 합본).

행 모양은 계약서 「원장 행」 그대로. 같은 key 는 두 번 들어가지 않는다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import asdict, dataclass, field
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVENTS_DIR = os.path.join(ROOT, "events")
LATEST = os.path.join(EVENTS_DIR, "latest.json")
LATEST_DAYS = 7
SENT_DEFAULT = {"push": 0, "kakao": False, "discord": False, "bundled": False, "held": False}


@dataclass
class Row:
    key: str
    event: str
    target: str
    dir: str
    level: str
    value: object
    unit: str
    asOf: str
    fresh: str
    title: str
    why: str
    next: str
    url: str
    ts: str
    sent: dict = field(default_factory=lambda: dict(SENT_DEFAULT))

    def to_dict(self) -> dict:
        return asdict(self)


def make_key(event: str, target: str, dir_: str, as_of: str) -> str:
    return f"{event}:{target}:{dir_}:{as_of}"


def day_path(day: dt.date) -> str:
    return os.path.join(EVENTS_DIR, f"{day.isoformat()}.json")


def _read(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _write(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=0)
    os.replace(tmp, path)


class Ledger:
    """하루치 원장. `append` 는 새 행이면 True, 같은 key 가 이미 있으면 False."""

    def __init__(self, day: dt.date | None = None, root: str | None = None):
        self.day = day or dt.datetime.now(KST).date()
        self.root = root or EVENTS_DIR
        self.path = os.path.join(self.root, f"{self.day.isoformat()}.json")
        self.rows: list[dict] = _read(self.path)
        self._keys = {r["key"] for r in self.rows}

    def has(self, key: str) -> bool:
        return key in self._keys

    def append(self, row: Row | dict) -> bool:
        d = row.to_dict() if isinstance(row, Row) else dict(row)
        if d["key"] in self._keys:
            return False
        d.setdefault("sent", dict(SENT_DEFAULT))
        self.rows.append(d)
        self._keys.add(d["key"])
        return True

    def update_sent(self, key: str, **sent) -> None:
        for r in self.rows:
            if r["key"] == key:
                r.setdefault("sent", dict(SENT_DEFAULT)).update(sent)
                return

    def get(self, key: str) -> dict | None:
        return next((r for r in self.rows if r["key"] == key), None)

    def save(self) -> str:
        _write(self.path, self.rows)
        return self.path

    # ---- 조회 ----
    @staticmethod
    def load_days(days: int, end: dt.date | None = None, root: str | None = None) -> list[dict]:
        root = root or EVENTS_DIR
        end = end or dt.datetime.now(KST).date()
        out: list[dict] = []
        for i in range(days):
            d = end - dt.timedelta(days=i)
            out.extend(_read(os.path.join(root, f"{d.isoformat()}.json")))
        out.sort(key=lambda r: r.get("ts", ""), reverse=True)
        return out

    @staticmethod
    def rebuild_latest(root: str | None = None, end: dt.date | None = None) -> str:
        root = root or EVENTS_DIR
        rows = Ledger.load_days(LATEST_DAYS, end=end, root=root)
        path = os.path.join(root, "latest.json")
        _write(path, rows)
        return path

    @staticmethod
    def count_in_year(event: str, target: str, end: dt.date | None = None, root: str | None = None) -> int:
        """「지난 1년 N회」 — 세기 고를 때 화면이 보여 주는 수. 원장이 쌓인 만큼만."""
        rows = Ledger.load_days(365, end=end, root=root)
        return sum(1 for r in rows if r.get("event") == event and r.get("target") == target)
