"""사전(events.yml) 읽기 · 검증 — 사건 이름 · 판정 함수 · 등급의 단일 원천.

PyYAML 을 쓰지 않는다(새 의존성 금지). 사전은 아래 「최소 YAML」 부분집합으로만 적는다:
  - 목록 항목은 `- id: A1` 로 시작하고, 그 항목의 키는 두 칸 들여쓰기 `  key: value`
  - 값은 문자열 · 정수 · 실수 · true/false · 한 줄 목록 `[a, b]` · 한 줄 사전 `{k: v, k2: [1, 2]}`
  - 문자열은 따옴표 있어도 없어도 됨. `#` 뒤는 주석(따옴표 안은 제외)
"""
from __future__ import annotations

import os
import re

from . import FAMILIES, LEVELS, RUNS

HERE = os.path.dirname(os.path.abspath(__file__))
EVENTS_YML = os.path.join(HERE, "events.yml")
REQUIRED = ("id", "name", "family", "level", "targets", "judge", "run", "title", "url")
ID_RE = re.compile(r"^[A-HU]\d{1,2}$")


def _strip_comment(line: str) -> str:
    out, q = [], None
    for ch in line:
        if q:
            out.append(ch)
            if ch == q:
                q = None
        elif ch in ("'", '"'):
            q = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _scalar(tok: str):
    t = tok.strip()
    if t == "":
        return ""
    if (t[0] == t[-1]) and t[0] in ("'", '"') and len(t) >= 2:
        return t[1:-1]
    if t in ("true", "True"):
        return True
    if t in ("false", "False"):
        return False
    if t in ("null", "~", "None"):
        return None
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r"-?\d+\.\d*", t):
        return float(t)
    return t


def _split_top(s: str, sep: str = ",") -> list[str]:
    """괄호 · 따옴표 안의 구분자는 건너뛰고 나눈다."""
    parts, depth, q, cur = [], 0, None, []
    for ch in s:
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            continue
        if ch in ("'", '"'):
            q = ch
            cur.append(ch)
        elif ch in "[{":
            depth += 1
            cur.append(ch)
        elif ch in "]}":
            depth -= 1
            cur.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


def _value(tok: str):
    t = tok.strip()
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        return [_value(p) for p in _split_top(inner)] if inner else []
    if t.startswith("{") and t.endswith("}"):
        inner = t[1:-1].strip()
        d = {}
        for p in (_split_top(inner) if inner else []):
            k, _, v = p.partition(":")
            d[k.strip().strip("'\"")] = _value(v)
        return d
    return _scalar(t)


def parse(text: str) -> list[dict]:
    items, cur = [], None
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        if line.startswith("- "):
            cur = {}
            items.append(cur)
            line = "  " + line[2:]
        if cur is None:
            raise ValueError(f"목록 항목 밖의 줄: {raw!r}")
        m = re.match(r"^  ([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if not m:
            raise ValueError(f"읽을 수 없는 줄: {raw!r}")
        cur[m.group(1)] = _value(m.group(2))
    return items


def validate(events: list[dict]) -> list[str]:
    errs, seen = [], set()
    for ev in events:
        eid = ev.get("id", "?")
        for k in REQUIRED:
            if k not in ev:
                errs.append(f"{eid}: 필수 키 없음 {k}")
        if eid in seen:
            errs.append(f"{eid}: id 중복")
        seen.add(eid)
        if not ID_RE.match(str(eid)):
            errs.append(f"{eid}: id 형식(갈래 글자 + 번호)")
        if ev.get("family") not in FAMILIES and not str(eid).startswith("U"):
            errs.append(f"{eid}: family {ev.get('family')!r}")
        if ev.get("level") not in LEVELS:
            errs.append(f"{eid}: level {ev.get('level')!r}")
        if ev.get("run") not in RUNS:
            errs.append(f"{eid}: run {ev.get('run')!r}")
        if not isinstance(ev.get("targets"), list) or not ev.get("targets"):
            errs.append(f"{eid}: targets 는 비지 않은 목록")
        if "default_on" in ev and not isinstance(ev["default_on"], list):
            errs.append(f"{eid}: default_on 은 목록")
        for key in ("why", "next"):
            if key in ev and not isinstance(ev[key], list):
                errs.append(f"{eid}: {key} 는 목록")
        if len(str(ev.get("name", ""))) > 12:
            errs.append(f"{eid}: name 12자 초과")
    return errs


def load_events(path: str = EVENTS_YML) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        events = parse(f.read())
    errs = validate(events)
    if errs:
        raise ValueError("events.yml 검증 실패:\n  " + "\n  ".join(errs))
    return events


def by_id(events: list[dict]) -> dict[str, dict]:
    return {ev["id"]: ev for ev in events}


def for_run(events: list[dict], run: str) -> list[dict]:
    return [ev for ev in events if ev.get("run") == run and ev.get("enabled", True)]
