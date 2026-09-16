#!/usr/bin/env python3
"""
메르 리스크 렌즈 v2 — P2 집계·조인.

mer_extract_cache.jsonl(376편 추출) + data.json + mer_series.json + scripts/mer_dict.yml
→ mer_signals.json (repo 루트).

왜: P1 추출기는 글 단위 자유서술(logNo,indicators,thresholds,impacts,stance,chain...)만
남긴다. 화면(P3)이 그리려면 (a) 자유서술을 정식 entity id 로 묶고 (b) 시계열(data.json/
mer_series.json)과 조인해 "지금 어디에 있나"를 계산해야 한다. 이 스크립트가 그 유일한 지점.

실행: python scripts/mer_aggregate.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

import yaml

ROOT = __file__.replace("\\", "/").rsplit("/scripts/", 1)[0]

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).date()

# ── 사전 로드 ────────────────────────────────────────────────────────────
def load_dict(path=f"{ROOT}/scripts/mer_dict.yml"):
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f)
    entities = d["entities"]
    by_id = {e["id"]: e for e in entities}
    # (compiled_pattern, entity_id) — entities 순서 그대로, 엔티티 내부는 alias 순서 그대로.
    # 정규식은 한 번만 컴파일해 재사용한다.
    alias_patterns = []
    # joinable_patterns: plausible 또는 dataPath 를 가진(=조인 가능한) 엔티티만의 부분집합,
    # 같은 상대 순서. normalize_indicator() 의 1패스 전용 — cause 계층 엔티티(예: geopolitics)가
    # 조인 가능한 market/asset 엔티티(예: oil)보다 사전에 먼저 나와 트리거 지표명을 가로채는
    # 문제(예: "이란 경고 상한 유가" → geopolitics 로 접혀 조인 불가) 때문에 분리했다.
    joinable_patterns = []
    for e in entities:
        joinable = bool(e.get("plausible")) or bool(e.get("dataPath"))
        for a in e.get("aliases") or []:
            pat = re.compile(a, re.IGNORECASE)
            alias_patterns.append((pat, e["id"]))
            if joinable:
                joinable_patterns.append((pat, e["id"]))
    return d.get("version", "?"), entities, by_id, alias_patterns, joinable_patterns, (d.get("chains") or [])


def normalize_entity(text, alias_patterns):
    """단일 패스 정규화 — impacts.from|to / stance.asset / chain 스텝처럼 그래프 노드가
    될 수 있는 모든 계층(cause 포함)을 사전 순서 그대로 first-match 한다."""
    if not text:
        return None
    for pat, eid in alias_patterns:
        if pat.search(text):
            return eid
    return None


def normalize_indicator(text, joinable_patterns, alias_patterns):
    """thresholds[].indicator 전용 2패스 정규화. 1패스는 조인 가능(plausible 또는
    dataPath 존재) 엔티티만 사전 순서로 검사해 cause 엔티티(조인 불가)에 가로채이는
    것을 막는다. 1패스가 실패했을 때만 전체 엔티티로 2패스."""
    if not text:
        return None
    for pat, eid in joinable_patterns:
        if pat.search(text):
            return eid
    for pat, eid in alias_patterns:
        if pat.search(text):
            return eid
    return None


_SPLIT_RE = re.compile(r"[·|,/]")


def split_composite(text, alias_patterns):
    """stance.asset / impacts.from|to 의 합성 자산명을 분해해 entity id 리스트로.
    쪼갠 조각이 전부 같은 id(None 포함)면 [그 id] 1개. 서로 다른 id 가 나오면
    None 을 버리고 남은 non-None id 들을 각각 반환(엔트리 복제 대상)."""
    if not text:
        return [None]
    parts = [p.strip() for p in _SPLIT_RE.split(text) if p.strip()]
    if len(parts) <= 1:
        return [normalize_entity(text, alias_patterns)]
    ids = []
    for p in parts:
        nid = normalize_entity(p, alias_patterns)
        if nid not in ids:
            ids.append(nid)
    if len(ids) == 1:
        return [ids[0]]
    non_none = [i for i in ids if i is not None]
    return non_none if non_none else [None]


# ── 임계 레벨 분류 (§ classify_threshold, 순서 고정) ────────────────────
_RE_COUNTER = re.compile(r"일분|일치|일째|개월|일간|days|비축|소진|남은|\d+\s*일")
# ISO 날짜(2026-07-24)를 먼저 잡는다 — 안 잡으면 연도 2026 이 가격 레벨로 파싱돼
# 금(4,330) 이 "2026 돌파" 로 뜬다(실측 오탐, 2026-09-15).
_RE_CALENDAR = re.compile(
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{4}[-/.]\d{1,2}\b"
    r"|\d+\s*월\s*\d+\s*일|\d+\s*월(?!\s*\d*\s*(달러|원|엔|%))|\d{4}\s*년"
    r"|분기|발효|시행|만기"
    r"|\d+\s*시\s*\d+\s*분"
)
_RE_QUAL_REJECT = re.compile(r"[÷×]|배(?!럴)|\d+\s*번|\d+\s*표|%p|bp")
# 재고 일수 블록에 실릴 자격 — 「버틸 수 있는 잔여량」을 말하는 것만.
_RE_STOCKPILE = re.compile(r"비축|재고|보관|저장|보유\s*물량|커버|공급\s*여력|소진")
_RE_NUMBER = re.compile(r"(-?\d+(?:\.\d+)?)")
_RE_UNIT = re.compile(r"(%|원|달러|엔|TEU)")
_UNIT_ALIAS = {"달러": "$"}


def classify_threshold(level_text, entity):
    # 스펙 원문 순서(counter→calendar)대로 두 정규식을 그대로 두면 "3월 20일"의
    # "20일"이 counter 의 '\d+\s*일' 에도 걸려 calendar 테스트 케이스와 충돌한다
    # (376편 실측 예시 자체가 calendar 를 기대). 더 구체적인 calendar 패턴을
    # 먼저 본다 — "8일분" 류(월/년/분기 없음)는 여전히 counter 로 떨어진다.
    lvl = level_text or ""
    if _RE_CALENDAR.search(lvl):
        return {"kind": "calendar"}
    if _RE_COUNTER.search(lvl):
        return {"kind": "counter"}
    if _RE_QUAL_REJECT.search(lvl):
        return {"kind": "qualitative"}
    m = _RE_NUMBER.search(lvl.replace(",", ""))
    if not m:
        return {"kind": "qualitative"}
    if entity is None or not entity.get("plausible"):
        return {"kind": "qualitative"}
    value = float(m.group(1))
    lo, hi = entity["plausible"]
    if not (lo <= value <= hi):
        return {"kind": "qualitative"}
    um = _RE_UNIT.search(lvl)
    if um:
        utoken = _UNIT_ALIAS.get(um.group(1), um.group(1))
        eunit = entity.get("unit")
        if eunit is not None and utoken != eunit:
            return {"kind": "qualitative"}
    return {"kind": "level", "value": value}


_RE_DIR_UP = re.compile(r"초과|넘|이상|돌파|위면")
_RE_DIR_DOWN = re.compile(r"이하|밑|미만|아래")


def infer_dir(meaning, level):
    text = f"{meaning or ''} {level or ''}"
    if _RE_DIR_UP.search(text):
        return "up"
    if _RE_DIR_DOWN.search(text):
        return "down"
    return "up"


# ── data.json / mer_series.json 조인 ────────────────────────────────────
def _dig(node, path):
    for part in path.split("."):
        if not isinstance(node, dict):
            return {}
        node = node.get(part, {})
    return node


def _yoy(pts):
    """월간 인덱스 시계열 → 전년동월 대비 %. 12개월 전 실측이 없는 달은 버린다(보간·외삽 금지).
    CPIAUCSL·PCEPI 처럼 data.json 이 지수(레벨)로 주는데 글의 임계는 '%' 로 적힌 지표 전용."""
    by_date = dict(pts)
    out = []
    for d, v in pts:
        if not (len(d) >= 6 and d[:4].isdigit()):
            continue
        base = by_date.get(str(int(d[:4]) - 1) + d[4:])   # 'YYYY-MM-DD'(FRED)·'YYYYMM'(ECOS) 공통
        if base:
            out.append((d, round((v / base - 1) * 100, 2)))
    return out


def join_series(entity, data, mer_series):
    """entity.dataKind 에 따라 (current, history_points[(date,value)]) 를 돌려준다.
    조인 불가면 (None, [])."""
    kind = entity.get("dataKind") or "none"
    dp = entity.get("dataPath")
    if kind == "none" or not dp:
        return None, []

    pts = []
    if kind == "curve":
        path, tenor = dp.split(":")
        node = _dig(data, path)
        if isinstance(node, dict) and "series" in node:
            arr = next((s.get("data") or [] for s in node["series"] if s.get("tenor") == tenor), [])
        else:
            sub = node.get(tenor, {}) if isinstance(node, dict) else {}
            arr = sub.get("data", []) if isinstance(sub, dict) else []
        pts = [(p["date"], p["value"]) for p in arr if isinstance(p, dict) and p.get("value") is not None]
    elif kind == "jgb":
        path, tenor = dp.split(":")
        node = mer_series
        for part in path.split(".")[1:]:  # drop leading "mer_series"
            node = node.get(part, {}) if isinstance(node, dict) else {}
        arr = node.get(tenor, []) if isinstance(node, dict) else []
        pts = [(p["date"], p["value"]) for p in arr if isinstance(p, dict) and p.get("value") is not None]
    elif kind == "close":
        node = _dig(data, dp)
        arr = node if isinstance(node, list) else []
        pts = [(p["date"], p["close"]) for p in arr if isinstance(p, dict) and p.get("close") is not None]
    elif kind == "rows":
        # <path>:<field> — investorTrading.daily 처럼 [{date, field...}] 인 행 배열
        path, field = dp.split(":")
        arr = _dig(data, path)
        pts = [(p["date"], p[field]) for p in (arr if isinstance(arr, list) else [])
               if isinstance(p, dict) and isinstance(p.get(field), (int, float))]
    elif kind == "meritems":
        # mer_series.<name>:<item> — fetch_mer_series.py 가 [{date, items:{...}}] 로 자가축적하는 계열
        path, item = dp.split(":")
        arr = mer_series.get(path.split(".", 1)[1], []) if isinstance(mer_series, dict) else []
        pts = []
        for p in arr:
            if not isinstance(p, dict):
                continue
            bag = p.get("items") or p.get("alloc")   # freight·lme 는 items, NPS 는 alloc
            if isinstance(bag, dict) and isinstance(bag.get(item), (int, float)):
                pts.append((p["date"], bag[item]))
    elif kind in ("map", "sentiment"):
        node = _dig(data, dp)
        hist = node.get("history", {}) if isinstance(node, dict) else {}
        pts = list(hist.items()) if isinstance(hist, dict) else []

    pts = [(d, v) for d, v in pts if isinstance(v, (int, float))]
    if entity.get("scale"):   # 원천 단위가 제각각인 계열을 한 판에 올릴 때만 쓴다
        pts = [(d, round(v * entity["scale"], 4)) for d, v in pts]
    if entity.get("transform") == "yoy":
        pts.sort(key=lambda x: x[0])
        pts = _yoy(pts)

    if not pts:
        return None, []
    pts.sort(key=lambda x: x[0])
    current = {"value": pts[-1][1], "asOf": pts[-1][0]}
    return current, pts


def history_1y(pts, as_of):
    # ECOS 계열은 'YYYYMM' 이라 fromisoformat 이 죽는다 — 그 경우 통째로 돌려주면
    # 「1년」 이라 써 놓고 10년치를 그리게 된다. 키 포맷대로 잘라낸다.
    if isinstance(as_of, str) and len(as_of) == 6 and as_of.isdigit():
        cutoff = str(int(as_of[:4]) - 1) + as_of[4:]
    else:
        try:
            cutoff = (datetime.fromisoformat(as_of) - timedelta(days=365)).date().isoformat()
        except (ValueError, TypeError):
            return [{"date": d, "value": v} for d, v in pts]
    return [{"date": d, "value": v} for d, v in pts if d >= cutoff]


# ── 날짜 파싱 (events용) ─────────────────────────────────────────────────
_RE_YMD = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_RE_MD = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_RE_Y = re.compile(r"(\d{4})\s*년")


def parse_event_date(level_text, post_date):
    text = level_text or ""
    m = _RE_YMD.search(text)
    if m:
        y, mo, da = map(int, m.groups())
        try:
            return f"{y:04d}-{mo:02d}-{da:02d}", "day"
        except ValueError:
            return None, None
    m = _RE_MD.search(text)
    if m:
        mo, da = map(int, m.groups())
        try:
            post_y = int(post_date[:4])
            cand = f"{post_y:04d}-{mo:02d}-{da:02d}"
            # 게시일보다 6개월 이상 과거로 보이면 내년으로 굴린다(전방 이벤트 가정)
            if cand < post_date and (datetime.fromisoformat(post_date).date()
                                      - datetime.fromisoformat(cand).date()).days > 183:
                cand = f"{post_y + 1:04d}-{mo:02d}-{da:02d}"
            return cand, "day"
        except ValueError:
            return None, None
    m = _RE_Y.search(text)
    if m:
        # 연도만 아는 이벤트를 1월 1일로 적으면 D-day 가 거짓말이 된다.
        # 날짜는 정렬용으로만 두고 정밀도를 함께 실어 화면이 "2027년" 으로 적게 한다.
        return f"{int(m.group(1)):04d}-01-01", "year"
    return None, None


_RE_REVOCABLE = re.compile(r"철회|유예|연기|협상")


# ── 메인 ─────────────────────────────────────────────────────────────────
def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    dict_version, entities, by_id, alias_patterns, joinable_patterns, chains_preset = load_dict()
    with open(f"{ROOT}/mer_extract_cache.jsonl", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    with open(f"{ROOT}/data.json", encoding="utf-8") as f:
        data = json.load(f)
    with open(f"{ROOT}/mer_series.json", encoding="utf-8") as f:
        mer_series = json.load(f)

    dates = [r["date"] for r in records]
    window = {"from": min(dates), "to": max(dates)}
    coverage = {
        "posts": len(records),
        "econ": sum(1 for r in records if r.get("econ")),
        "extracted": len(records),
    }

    unmapped = {"impacts": Counter(), "thresholds": Counter(), "stance": Counter()}

    # ── thresholds → entity 별로 묶기 ────────────────────────────────────
    th_by_entity = defaultdict(list)  # entity_id -> [ {kind,value,levelText,meaning,quote,logNo,date,dir} ]
    events = []
    counters_out = []
    for r in records:
        for th in r.get("thresholds") or []:
            eid = normalize_indicator(th.get("indicator"), joinable_patterns, alias_patterns)
            entity = by_id.get(eid)
            cls = classify_threshold(th.get("level"), entity)
            kind = cls["kind"]
            if eid is None:
                unmapped["thresholds"][th.get("indicator") or ""] += 1
            row = {
                "level": cls.get("value") if kind == "level" else None,
                "levelText": th.get("level"),
                "meaning": th.get("meaning"),
                "quote": th.get("quote"),
                "logNo": r["logNo"],
                "date": r["date"],
                "kind": kind,
            }
            if kind == "level":
                row["dir"] = infer_dir(th.get("meaning"), th.get("level"))
            if eid is not None:
                th_by_entity[eid].append(row)

            if kind == "calendar":
                ev_date, ev_prec = parse_event_date(th.get("level"), r["date"])
                if ev_date:
                    revocable = bool(_RE_REVOCABLE.search(f"{th.get('meaning') or ''} {th.get('quote') or ''}"))
                    events.append({
                        "date": ev_date, "label": th.get("indicator") or th.get("meaning"),
                        "kind": "calendar", "precision": ev_prec,
                        "revocable": revocable, "logNo": r["logNo"],
                    })
            elif kind == "counter" and _RE_STOCKPILE.search(
                f"{th.get('indicator') or ''} {th.get('level') or ''} {th.get('meaning') or ''}"
            ):
                # 재고 일수(Days of Cover)는 「얼마나 버티나」만 담는다.
                # 이 문턱이 없으면 "셧다운 지속일 5일"·"한은 총재 화법 3개월" 같은
                # 기간 시나리오가 재고 막대로 그려진다(실측 오탐, 2026-09-15).
                nums = re.findall(r"\d+", (th.get("level") or "").replace(",", ""))
                sep_m = re.search(r"(\d+)\s*[~/]\s*(\d+)", (th.get("level") or "").replace(",", ""))
                days = int(nums[0]) if nums else None
                days_alt = int(sep_m.group(2)) if sep_m else None
                if days is None:
                    continue   # 일수 없는 항목은 막대를 그릴 수 없다
                counters_out.append({
                    "label": th.get("indicator"), "days": days, "daysAlt": days_alt,
                    "assumption": th.get("meaning"), "asOfPost": r["date"], "logNo": r["logNo"],
                })

    # 과거 이벤트는 오늘 기준 30일까지만 보존
    cutoff = (TODAY - timedelta(days=30)).isoformat()
    events = [e for e in events if e["date"] >= cutoff]

    # ── indicators[] 조립 ────────────────────────────────────────────────
    indicators = []
    entity_state = {}  # id -> state (그래프 노드용)
    for e in entities:
        eid = e["id"]
        ths = th_by_entity.get(eid, [])
        current, pts = join_series(e, data, mer_series)
        level_ths = [t for t in ths if t["kind"] == "level"]
        if not level_ths and current is None:
            continue  # 포함 조건 미달

        nearest = None
        state = "unknown"
        if current is not None and level_ths:
            def dist(t):
                return abs((current["value"] - t["level"]) / t["level"] * 100) if t["level"] else float("inf")
            best = min(level_ths, key=dist)
            distance_pct = (current["value"] - best["level"]) / best["level"] * 100 if best["level"] else None
            nearest = {"level": best["level"], "distancePct": distance_pct}
            crossed = (best["dir"] == "up" and current["value"] >= best["level"]) or \
                      (best["dir"] == "down" and current["value"] <= best["level"])
            if crossed:
                state = "crossed"
            elif distance_pct is not None and abs(distance_pct) <= 2:
                state = "near"
            else:
                state = "below"
        entity_state[eid] = state

        post_dates = sorted({t["date"] for t in ths})
        last_quotes = [t["quote"] for t in sorted(ths, key=lambda t: t["date"], reverse=True)[:3] if t.get("quote")]

        indicators.append({
            "id": eid, "label": e.get("label"), "layer": e.get("layer"), "unit": e.get("unit"),
            "dataPath": e.get("dataPath"),
            "current": current,
            "history1y": history_1y(pts, current["asOf"]) if current else [],
            "thresholds": ths,
            "nearest": nearest,
            "state": state,
            "postDates": post_dates,
            "lastQuotes": last_quotes,
        })

    # ── impacts (post 단위, 합성분해 후) ─────────────────────────────────
    impact_mentions = []  # 개별 mention: from,to,dir,strength,horizon,quote,logNo,date
    for r in records:
        for im in r.get("impacts") or []:
            from_ids = split_composite(im.get("from"), alias_patterns)
            to_ids = split_composite(im.get("to"), alias_patterns)
            if from_ids == [None]:
                unmapped["impacts"][im.get("from") or ""] += 1
            if to_ids == [None]:
                unmapped["impacts"][im.get("to") or ""] += 1
            for f in from_ids:
                for t in to_ids:
                    if f is None or t is None or f == t:
                        continue
                    impact_mentions.append({
                        "from": f, "to": t, "dir": im.get("direction"),
                        "strength": im.get("strength"), "horizon": im.get("horizon"),
                        "quote": im.get("quote"), "logNo": r["logNo"], "date": r["date"],
                    })

    agg = defaultdict(lambda: {"quotes": [], "strengths": [], "horizons": Counter(), "logNos": []})
    for m in impact_mentions:
        key = (m["from"], m["to"], m["dir"])
        a = agg[key]
        a["logNos"].append(m["logNo"])
        if m["strength"] is not None:
            a["strengths"].append(m["strength"])
        if m["horizon"]:
            a["horizons"][m["horizon"]] += 1
        if len(a["quotes"]) < 3 and m["quote"]:
            a["quotes"].append({"logNo": m["logNo"], "date": m["date"], "q": m["quote"]})

    impacts_out = []
    for (f, t, direction), a in agg.items():
        n = len(a["logNos"])
        if n < 2:
            continue
        strength = round(sum(a["strengths"]) / len(a["strengths"])) if a["strengths"] else None
        horizon = a["horizons"].most_common(1)[0][0] if a["horizons"] else None
        impacts_out.append({
            "from": f, "to": t, "dir": direction, "strength": strength,
            "horizon": horizon, "n": n, "quotes": a["quotes"],
        })

    # ── graph ────────────────────────────────────────────────────────────
    node_ids = set()
    for im in impacts_out:
        node_ids.add(im["from"])
        node_ids.add(im["to"])
    # asset 노드 view = stance 최신값(있으면) — stance 는 아래서 계산하므로 먼저 만든다
    stance_by_asset = defaultdict(list)
    for r in records:
        for st in r.get("stance") or []:
            ids = split_composite(st.get("asset"), alias_patterns)
            if ids == [None]:
                unmapped["stance"][st.get("asset") or ""] += 1
                continue
            for aid in ids:
                if aid is None:
                    continue
                stance_by_asset[aid].append({
                    "date": r["date"], "view": st.get("view"), "logNo": r["logNo"], "why": st.get("why"),
                })

    edge_count_by_node = Counter()
    for im in impacts_out:
        edge_count_by_node[im["from"]] += 1
        edge_count_by_node[im["to"]] += 1

    nodes = []
    for nid in node_ids:
        e = by_id.get(nid, {})
        series = sorted(stance_by_asset.get(nid, []), key=lambda s: s["date"])
        view = series[-1]["view"] if series else None
        nodes.append({
            "id": nid, "label": e.get("label", nid), "layer": e.get("layer"),
            "state": entity_state.get(nid, "unknown"), "view": view,
        })
    layer_order = {"cause": 0, "market": 1, "channel": 2, "asset": 3}
    # id 를 마지막 타이브레이크로 둔다. node_ids 는 집합이라 순회 순서가 프로세스마다
    # 달라지고, 같은 계층·같은 엣지 수인 노드끼리 순서가 매 실행 뒤바뀐다.
    # 그러면 내용이 안 변해도 파일이 매번 달라져 파이프라인이 빈 커밋을 계속 만든다.
    nodes.sort(key=lambda n: (layer_order.get(n["layer"], 9),
                              -edge_count_by_node[n["id"]], n["id"]))

    edges = []
    for im in impacts_out:
        full_lognos = agg[(im["from"], im["to"], im["dir"])]["logNos"]
        edges.append({
            "from": im["from"], "to": im["to"], "dir": im["dir"], "n": im["n"],
            "horizon": im["horizon"], "logNos": full_lognos,
        })

    graph = {"nodes": nodes, "edges": edges}

    # ── matrix ───────────────────────────────────────────────────────────
    src_layers = {"cause", "market", "channel"}
    rows, cols = [], []
    cells = []
    row_sums, col_sums = Counter(), Counter()
    for im in impacts_out:
        f_layer = by_id.get(im["from"], {}).get("layer")
        t_layer = by_id.get(im["to"], {}).get("layer")
        if f_layer in src_layers and t_layer == "asset":
            if im["from"] not in rows:
                rows.append(im["from"])
            if im["to"] not in cols:
                cols.append(im["to"])
            cells.append({"row": im["from"], "col": im["to"], "dir": im["dir"],
                           "n": im["n"], "strength": im["strength"]})
            row_sums[im["from"]] += im["n"]
            col_sums[im["to"]] += im["n"]
    matrix = {"rows": rows, "cols": cols, "cells": cells,
              "rowSums": dict(row_sums), "colSums": dict(col_sums)}

    # ── stance{} ─────────────────────────────────────────────────────────
    stance_assets = []
    for aid, series in stance_by_asset.items():
        series = sorted(series, key=lambda s: s["date"])
        views = [s["view"] for s in series if isinstance(s.get("view"), (int, float))]
        last12_cutoff = (datetime.fromisoformat(series[-1]["date"]).date() - timedelta(days=365)).isoformat()
        recent_views = [s["view"] for s in series if s["date"] >= last12_cutoff and isinstance(s.get("view"), (int, float))]
        avg12m = round(sum(recent_views) / len(recent_views), 2) if recent_views else None
        reversals = []
        for prev, cur in zip(series, series[1:]):
            pv, cv = prev.get("view"), cur.get("view")
            if isinstance(pv, (int, float)) and isinstance(cv, (int, float)) and pv * cv < 0:
                reversals.append(cur["date"])
        stance_assets.append({
            "asset": aid, "label": by_id.get(aid, {}).get("label", aid), "series": series,
            "last": views[-1] if views else None, "avg12m": avg12m, "n": len(series),
            "reversals": reversals,
        })
    stance_assets.sort(key=lambda a: -a["n"])
    stance = {"assets": stance_assets}

    # ── factors[] ────────────────────────────────────────────────────────
    FACTOR_TARGETS = {"usdkrw", "usdjpy", "dxy", "kospi", "us_equity"}

    def side_of(direction):
        if direction == "+":
            return "bull"
        if direction == "-":
            return "bear"
        return "neutral"

    factor_groups = defaultdict(list)
    for m in impact_mentions:
        if m["to"] not in FACTOR_TARGETS:
            continue
        label = by_id.get(m["from"], {}).get("label", m["from"])
        factor_groups[(m["to"], label)].append({
            "asset": m["to"], "factor": label, "side": side_of(m["dir"]),
            "horizon": m["horizon"], "logNo": m["logNo"], "date": m["date"],
        })
    factors_out = []
    for key, arr in factor_groups.items():
        arr.sort(key=lambda x: x["date"])
        non_neutral_idx = [i for i, x in enumerate(arr) if x["side"] in ("bull", "bear")]
        for pos, i in enumerate(non_neutral_idx):
            if pos == len(non_neutral_idx) - 1:
                arr[i]["status"] = "active"
            else:
                j = non_neutral_idx[pos + 1]
                arr[i]["status"] = "expired" if arr[j]["side"] != arr[i]["side"] else "active"
        for x in arr:
            if x["side"] == "neutral":
                x["status"] = "neutral"
        # 스코어카드는 「무엇이 밀고 당기나」를 읽는 표다. 같은 (자산, 팩터, 방향)이
        # 글마다 한 줄씩 쌓이면 "환헤지·역송금" 이 세 번 반복돼 표가 못 읽힌다
        # (실측 오탐, 2026-09-15). 최신 글 하나만 남기고 근거 수를 n 으로 옮긴다.
        latest = arr[-1]
        latest["n"] = len(arr)
        latest["logNos"] = [x["logNo"] for x in arr][-5:]
        factors_out.append(latest)

    # ── regime{} ─────────────────────────────────────────────────────────
    all_months = sorted({r["date"][:7] for r in records})
    months = all_months[-12:]
    factor_names = sorted({flag for r in records for flag in (r.get("risk_flags") or [])})
    counts = [[0] * len(factor_names) for _ in months]
    month_idx = {m: i for i, m in enumerate(months)}
    for r in records:
        mi = month_idx.get(r["date"][:7])
        if mi is None:
            continue
        for flag in r.get("risk_flags") or []:
            fi = factor_names.index(flag)
            counts[mi][fi] += 1
    dominant = []
    for row in counts:
        if any(row):
            dominant.append(factor_names[row.index(max(row))])
        else:
            dominant.append(None)
    regime = {"months": months, "factors": factor_names, "counts": counts, "dominant": dominant}

    # ── chains[] (전이 경로 프리셋, §3.3 C1~C10) ─────────────────────────
    # 통계로 재발견하지 않는다 — 자유서술 chain 문자열은 문자 그대로 일치하는 법이
    # 없어(376편 실측 max group size=1) 통계 병합은 항상 0으로 떨어진다. 사전
    # mer_dict.yml 의 chains: 프리셋을 그대로 쓰고, 추출 chain 에서 프리셋 step
    # id 가 2개 이상 겹치는 글만 증거로 붙인다.
    post_chain_ids = []  # 레코드별 정규화된 스텝 id 집합(캐시)
    for r in records:
        chain = r.get("chain")
        raw_steps = [s.strip() for s in chain.split("→") if s.strip()] if chain else []
        ids = {normalize_entity(s, alias_patterns) for s in raw_steps}
        ids.discard(None)
        post_chain_ids.append((r, ids))

    chains_out = []
    for preset in chains_preset:
        preset_ids = set(preset.get("steps") or [])
        matched = [(r, ids) for r, ids in post_chain_ids if len(ids & preset_ids) >= 2]
        matched.sort(key=lambda pair: pair[0]["date"], reverse=True)
        log_nos = [r["logNo"] for r, _ in matched[:20]]
        last_date = max((r["date"] for r, _ in matched), default=None)
        hot_step = None
        for sid in preset.get("steps") or []:
            if entity_state.get(sid) == "crossed":
                hot_step = sid
                break
        if hot_step is None:
            for sid in preset.get("steps") or []:
                if entity_state.get(sid) == "near":
                    hot_step = sid
                    break
        chains_out.append({
            "id": preset["id"], "label": preset.get("label"),
            "steps": [{"id": sid, "label": by_id.get(sid, {}).get("label", sid)}
                      for sid in preset.get("steps") or []],
            "note": preset.get("note"), "n": len(matched),
            "logNos": log_nos, "lastDate": last_date, "hotStep": hot_step,
        })

    # ── lens{} (메르 리스크 지수, MRI) ────────────────────────────────────
    # 세 구성요소 전부 "그 날짜 기준" 으로 다시 센다. 하나라도 오늘값으로 고정하면
    # 30일 추이가 직선이 되어 "지수가 한 달 내내 안 움직였다" 는 거짓말이 된다
    # (실측: 고정 구현은 30일 전부 56 이었다).
    _RANK = {"crossed": 2, "near": 1, "below": 0}

    def state_as_of(ind, day):
        """그 날짜의 시계열 값과, 그 날짜까지 발행된 글의 트리거만으로 상태를 판정.
        미래 글의 트리거를 과거 날짜에 적용하지 않는다."""
        val = None
        for p in ind.get("history1y") or []:
            if p["date"] <= day:
                val = p["value"]
            else:
                break
        if val is None:
            return None
        best = None
        for t in ind.get("thresholds") or []:
            if t.get("kind") != "level" or t.get("level") in (None, 0) or t.get("date", "") > day:
                continue
            dist = (val - t["level"]) / t["level"] * 100
            crossed = dist >= 0 if t.get("dir") == "up" else dist <= 0
            st = "crossed" if crossed else ("near" if abs(dist) <= 2 else "below")
            if best is None or _RANK[st] > _RANK[best]:
                best = st
        return best

    def comp_threshold_at(day):
        states = [state_as_of(i, day) for i in indicators]
        crossed = sum(1 for s in states if s == "crossed")
        near = sum(1 for s in states if s == "near")
        return min(crossed * 20 + near * 10, 40)

    def _flags_in_window(day, days=30):
        lo = (datetime.fromisoformat(day).date() - timedelta(days=days)).isoformat()
        return sum(len(r.get("risk_flags") or []) for r in records if lo < r["date"] <= day)

    # 30일 창 편수의 12개월 분포 — 백분위의 기준선(하루 단위로 미리 만든다)
    _flag_window_dist = sorted(
        _flags_in_window((TODAY - timedelta(days=k)).isoformat()) for k in range(0, 366, 7)
    )

    def mri_at(day):
        c_th = comp_threshold_at(day)
        lo = (datetime.fromisoformat(day).date() - timedelta(days=30)).isoformat()
        stance_entries = [st for r in records if lo < r["date"] <= day
                          for st in (r.get("stance") or [])
                          if isinstance(st.get("view"), (int, float))]
        uw_ratio = (sum(1 for s in stance_entries if s["view"] < 0) / len(stance_entries)
                    if stance_entries else 0)
        c_uw = uw_ratio * 40
        cur = _flags_in_window(day)
        pct = (sum(1 for v in _flag_window_dist if v <= cur) / len(_flag_window_dist) * 100
               if _flag_window_dist else 0)
        c_fl = pct / 100 * 20
        return int(c_th + c_uw + c_fl), c_th, c_uw, c_fl

    score, c_th, c_uw, c_fl = mri_at(TODAY.isoformat())
    history30d = []
    for i in range(29, -1, -1):
        day = (TODAY - timedelta(days=i)).isoformat()
        history30d.append({"date": day, "score": mri_at(day)[0]})

    lens = {
        "score": score,
        "components": {"thresholdsCrossed": c_th, "negativeStance30d": round(c_uw, 1),
                        "riskFlags30d": round(c_fl, 1)},
        "asOf": TODAY.isoformat(),
        "history30d": history30d,
    }

    # ── posts[] ──────────────────────────────────────────────────────────
    posts = [{
        "logNo": r["logNo"], "date": r["date"], "title": r.get("title"), "econ": r.get("econ"),
        "one_liner": r.get("one_liner"), "topics": r.get("topics") or [],
        "risk_flags": r.get("risk_flags") or [],
    } for r in records]

    def top50(counter):
        return [[k, v] for k, v in counter.most_common(50)]

    signals = {
        "asOf": datetime.now(KST).isoformat(),
        "window": window,
        "coverage": coverage,
        "dictVersion": dict_version,
        "indicators": indicators,
        "impacts": impacts_out,
        "graph": graph,
        "matrix": matrix,
        "stance": stance,
        "factors": factors_out,
        "events": sorted(events, key=lambda e: e["date"]),
        "counters": counters_out,
        "regime": regime,
        "chains": chains_out,
        "lens": lens,
        "posts": posts,
        "unmapped": {k: top50(v) for k, v in unmapped.items()},
    }

    with open(f"{ROOT}/mer_signals.json", "w", encoding="utf-8") as f:
        json.dump(signals, f, ensure_ascii=False, indent=1)

    # ── 완료 보고 ────────────────────────────────────────────────────────
    level_total = sum(1 for i in indicators for t in i["thresholds"] if t["kind"] == "level")
    print(f"indicators={len(indicators)} level_triggers={level_total} "
          f"impacts(n>=2)={len(impacts_out)} graph_nodes={len(nodes)} "
          f"stance_assets={len(stance_assets)} events={len(events)} counters={len(counters_out)} "
          f"MRI={score}")

    for probe_id, expect in [("us10y", "4.96 vs 5.0"), ("jgb30y", "4.04 vs 4.0"),
                              ("kospi", "6684 vs 8200"), ("usdjpy", "trigger 160")]:
        ind = next((i for i in indicators if i["id"] == probe_id), None)
        if ind:
            print(f"  {probe_id}: current={ind['current']} nearest={ind['nearest']} "
                  f"state={ind['state']} ({expect})")
        else:
            print(f"  {probe_id}: NOT INCLUDED ({expect})")

    for cat in ("impacts", "thresholds", "stance"):
        print(f"unmapped.{cat} top10:", signals["unmapped"][cat][:10])


if __name__ == "__main__":
    main()
