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
# 같은 key 를 지난 이만큼의 원장에서도 찾는다. key 는 관측 날짜(asOf)로 만들어지므로 주말 · 연휴 · 월간 지표처럼
# 값이 그대로인 동안 매 런이 같은 사건을 다시 판정해도 하루 파일이 바뀌면 또 들어갔다. 월간 지표 한 주기(≤40일)를 덮는다.
LOOKBACK_DAYS = 40
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
    chg: float | None = None       # 등락(%) — 급변 사건의 사용자별 세기(σ 배수) 판정에 쓴다
    z: float | None = None         # |등락| / σ — 같은 용도. 둘 다 공개해도 되는 시장 값
    line: float | None = None      # 건넌 선 · 마디(렌즈 선 · 마디 돌파) — 카드 차트의 점선. 사전 사건의 공개 선이다
    cd: dict | None = None         # 쿨다운 묶음 키 값(사전 cooldown.per 가운데 행 칸이 아닌 것 — 공시 접수번호 · 단계 · 날짜 · 기간)

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
    """하루치 원장. `append` 는 새 행이면 True, 같은 key 가 오늘 또는 지난 LOOKBACK_DAYS 원장에 있으면 False."""

    def __init__(self, day: dt.date | None = None, root: str | None = None, lookback_days: int = LOOKBACK_DAYS):
        self.day = day or dt.datetime.now(KST).date()
        self.root = root or EVENTS_DIR
        self.path = os.path.join(self.root, f"{self.day.isoformat()}.json")
        self.rows: list[dict] = _read(self.path)
        self._keys = {r["key"] for r in self.rows}
        self._past: set[str] = set()                 # 지난 원장의 key(읽기만)
        for i in range(1, lookback_days + 1):
            d = self.day - dt.timedelta(days=i)
            self._past.update(r.get("key") for r in _read(os.path.join(self.root, f"{d.isoformat()}.json"))
                              if isinstance(r, dict))

    def has(self, key: str) -> bool:
        return key in self._keys

    def seen(self, key: str) -> bool:
        """오늘 또는 지난 LOOKBACK_DAYS 원장에 있는 key 인가."""
        return key in self._keys or key in self._past

    def append(self, row: Row | dict) -> bool:
        d = row.to_dict() if isinstance(row, Row) else dict(row)
        if self.seen(d["key"]):
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


def _merge_sent(a: dict, b: dict) -> dict:
    """두 사본의 발송 기록 합치기 — 한쪽이라도 나갔으면 나간 것(push 는 큰 수)."""
    out = dict(SENT_DEFAULT)
    for k in set(a) | set(b):
        va, vb = a.get(k), b.get(k)
        out[k] = max(va or 0, vb or 0) if k == "push" else bool(va and vb) if k == "held" else bool(va or vb)
    return out


def merge_dir(src: str, dst: str) -> int:
    """푸시 충돌 재시도용 — src(이번 런 사본)의 하루 파일을 dst(원격 최신)에 행 단위로 합친다. 같은 key 는 하나로 두고
    발송 기록은 합친다(_merge_sent). 종전엔 사본으로 통째 덮어 그사이 다른 런이 넣은 행이 사라졌고, 사라진 행은 다음 판정에서
    「새 행」이 되어 다시 나갈 수 있었다(2026-10-11 점검: 10/6 B2 S&P 행). 하루 파일이 아닌 것(history/)은 건드리지 않는다.
    돌려주는 값 = 합친 하루 파일 수. latest.json 은 dst 하루 파일로 다시 만든다."""
    n = 0
    os.makedirs(dst, exist_ok=True)
    for name in sorted(os.listdir(src)):
        s_path, d_path = os.path.join(src, name), os.path.join(dst, name)
        # 하루 파일(YYYY-MM-DD.json)만 — history/ 는 일일 런(history_sink)만 쓰고 자기 경로로 올린다. 사본으로 덮으면 되돌아간다
        if os.path.isdir(s_path) or not (name.endswith(".json") and len(name) == 15 and name[:2] == "20"):
            continue
        mine, theirs = _read(s_path), _read(d_path)
        rows = {r["key"]: dict(r) for r in theirs if isinstance(r, dict) and r.get("key")}
        for r in mine:
            if not isinstance(r, dict) or not r.get("key"):
                continue
            if r["key"] in rows:
                rows[r["key"]]["sent"] = _merge_sent(rows[r["key"]].get("sent") or {}, r.get("sent") or {})
            else:
                rows[r["key"]] = dict(r)
        _write(d_path, sorted(rows.values(), key=lambda r: r.get("ts", "")))
        n += 1
    Ledger.rebuild_latest(root=dst)
    return n


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 4 and sys.argv[1] == "--merge":
        print(f"[ledger] 행 단위 병합: 하루 파일 {merge_dir(sys.argv[2], sys.argv[3])}개")
    else:
        raise SystemExit("python scripts/alerts_v2/ledger.py --merge <이번 런 사본 events> <원격 events>")
