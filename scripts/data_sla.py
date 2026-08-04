#!/usr/bin/env python3
"""데이터 신선도 계약(SLA) — data.json 의 지표별 as-of 를 뽑아 상태를 판정한다.

왜 이 파일이 따로 있나: 신선도 기준이 세 곳(커밋 게이트 validate_data.py, 사이트
index.html, 카톡 다이제스트)에서 필요한데, 각자 자기 기준을 들고 있으면 반드시 어긋난다.
기준표는 여기 하나뿐이고, fetch_data.py 가 이 표로 계산한 결과를 data.json.dataHealth 에
실어 보내면 나머지 소비자는 판정하지 않고 읽기만 한다.

배경(2026-08 감사): FRED 가 OECD MEI 계열을 폐기해 일본 CPI 가 2021-06, 영국 GDP 가
2020-07 에서 멈췄는데도 게이트를 통과했다. 개별 소스 실패 시 직전값을 보존하는 설계는
옳지만, 보존됐다는 사실이 어디에도 드러나지 않은 게 문제였다.
"""
import fnmatch
import json
import re
import sys
from datetime import date, datetime

# ── 신선도 규칙 ────────────────────────────────────────────────────────────
# (glob 패턴, 허용 나이(일), 등급). 위에서부터 첫 매치를 쓴다 — 좁은 패턴을 먼저 둘 것.
#
# 나이 산정 기준:
#   일간 시장 데이터 = 4일  (금요일 종가가 월요일 아침까지 유효 + 연휴 여유)
#   주간 지표        = 12일
#   월간 지표        = 100일 — as-of 가 '해당 월 1일'로 기록되므로 공표 지연(1~2개월)에
#                     월 길이가 더해진다. 실측: 정상 갱신 중인 독일 실업률이 95일로 찍힌다.
#   분기 지표        = 200일 (같은 이유 + 분기 확정치 지연)
#
# 등급:
#   critical  — 없으면 대시보드가 무의미. stale 이면 커밋 차단(exit 1).
#   important — 눈에 띄는 위젯. stale 이면 화면에 경고 표시하되 배포는 진행.
#   normal    — 배경 지표. 표시만.
SLA_RULES = [
    # 일간 시장 — 대시보드의 근간
    ("history.indices.KOSPI",            4,   "critical"),
    ("history.indices.SP500",            4,   "critical"),
    ("history.fx.USDKRW",                4,   "critical"),
    ("history.indices.*",                4,   "important"),
    ("history.fx.*",                     4,   "important"),
    ("history.commodities.Dubai",        70,  "normal"),     # FRED 월간 시리즈
    ("history.commodities.*",            5,   "important"),

    # 장중 스냅샷
    ("stockMovers.*",                    4,   "important"),
    ("etfMovers.*",                      4,   "important"),
    ("investorTrading",                  6,   "important"),
    ("sentiment.*",                      4,   "important"),
    ("freight",                          10,  "normal"),
    ("marketHalts",                      400, "normal"),

    # 거시 — 분기 지표를 먼저 좁게 잡는다
    ("economicIndicators.*.gdp*",        200, "normal"),
    ("economicIndicators.kr.household_debt_kr", 200, "normal"),
    ("economicIndicators.us.vix",        6,   "important"),
    ("economicIndicators.us.hy_spread",  6,   "normal"),
    ("economicIndicators.*",             100, "normal"),

    ("realestate.us.case_shiller*",      150, "normal"),
    ("realestate.*",                     100, "normal"),
    ("yieldCurve.*",                     6,   "important"),
    ("nps",                              400, "normal"),
    ("subscription",                     40,  "normal"),
    ("climate.*",                        45,  "normal"),
    ("news",                             2,   "important"),
    ("economicCalendar",                 3,   "normal"),
    ("aiBriefing",                       2,   "normal"),
]

DEFAULT_SLA = (60, "normal")

# as-of 로 인정하는 키 (우선순위 순)
_ASOF_KEYS = ("as_of", "asOf", "period", "date", "lastFetched", "lastUpdated", "checkedAt")


def _parse_date(s):
    """'2026-08-04', '2026-08-04T12:00:00+09:00', '202606', '2026Q2', '2026-06-01' → date"""
    if isinstance(s, (int, float)):
        s = str(int(s))
    if not isinstance(s, str) or not s:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, dd = map(int, m.groups())
        return date(y, mo, dd) if 1 <= mo <= 12 and 1 <= dd <= 31 else None
    m = re.match(r"^(\d{4})[-.]?(\d{2})$", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return date(y, mo, 1) if 1 <= mo <= 12 else None
    m = re.match(r"^(\d{4})Q([1-4])$", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)) * 3 - 2, 1)
    return None


def _extract_asof(node):
    """지표 노드에서 as-of 날짜를 뽑는다. dict/list 형태를 모두 다룬다."""
    if isinstance(node, list):
        # [{date: ...}, ...] 시계열 — 뒤쪽이 최신
        for item in reversed(node[-3:]):
            if isinstance(item, dict):
                d = _extract_asof(item)
                if d:
                    return d
        return None
    if not isinstance(node, dict):
        return None
    for k in _ASOF_KEYS:
        d = _parse_date(node.get(k))
        if d:
            return d
    # history 가 {날짜: 값} 형태면 최대 키가 as-of
    hist = node.get("history")
    if isinstance(hist, dict) and hist:
        ds = [x for x in (_parse_date(k) for k in hist) if x]
        if ds:
            return max(ds)
    if isinstance(hist, list) and hist:
        return _extract_asof(hist)
    # items 배열을 갖는 블록(freight·investorTrading·economicCalendar·yieldCurve 등)
    items = node.get("items") or node.get("daily") or node.get("events") or node.get("series")
    if isinstance(items, list) and items:
        ds = [x for x in (_extract_asof(i) for i in items) if x]
        if ds:
            return max(ds)
    # 컨테이너 폴백 — 자식들이 각자 as-of 를 갖는 묶음(예: case_shiller_state 의 주별 항목,
    # yieldCurve.<cc>.series[].data). 가장 최신 자식이 이 블록의 as-of 다.
    ds = []
    for v in node.values():
        if isinstance(v, (dict, list)):
            d = _extract_asof(v)
            if d:
                ds.append(d)
    return max(ds) if ds else None


def _rule_for(path):
    for pat, days, tier in SLA_RULES:
        if fnmatch.fnmatchcase(path, pat):
            return days, tier
    return DEFAULT_SLA


# 블록 전체가 하나의 지표로 취급되는 최상위 키 (내부를 쪼개지 않는다)
_ATOMIC_TOPS = ("freight", "investorTrading", "news", "economicCalendar",
                "nps", "subscription", "marketHalts", "aiBriefing")
_SKIP_TOPS = ("lastUpdated", "sources", "diagnostics", "dataHealth")
# 현재가 스냅샷 블록 — 자체 날짜 필드가 없고 신선도는 같은 심볼의 history 가 대변한다.
# 여기서 판정하면 심볼마다 'unknown' 이 중복으로 쌓여 요약이 무의미해진다.
_SPOT_TOPS = ("indices", "commodities", "fx")


def _walk_paths(data):
    """SLA 판정 대상 경로를 만든다. 지표 단위(리프 dict)까지만 내려간다."""
    out = []
    for top, node in data.items():
        if top in _SKIP_TOPS or top in _SPOT_TOPS or not isinstance(node, (dict, list)):
            continue
        if top in _ATOMIC_TOPS:
            out.append((top, node))
            continue
        if not isinstance(node, dict):
            continue
        for k, v in node.items():
            if not isinstance(v, (dict, list)):
                continue
            nested = (top in ("economicIndicators", "realestate", "history")
                      and isinstance(v, dict)
                      and not any(a in v for a in _ASOF_KEYS))
            if nested:
                for k2, v2 in v.items():          # 2단 중첩 (지역/그룹 → 지표)
                    if isinstance(v2, (dict, list)):
                        out.append((f"{top}.{k}.{k2}", v2))
            else:
                out.append((f"{top}.{k}", v))
    return out


def build_health(data, today=None, sources=None):
    """data.json dict → dataHealth 블록. fetch_data.py 와 validate_data.py 가 공유한다."""
    today = today or date.today()
    sources = sources if sources is not None else (data.get("sources") or {})
    items = []
    for path, node in _walk_paths(data):
        sla_days, tier = _rule_for(path)
        asof = _extract_asof(node)
        top = path.split(".")[0]
        src = sources.get(top) or sources.get(path) or ""
        preserved = "보존" in str(src)
        if asof is None:
            state, age = "unknown", None
        else:
            age = (today - asof).days
            state = "stale" if age > sla_days else "ok"
        if preserved and state == "ok":
            state = "preserved"
        items.append({
            "path": path,
            "asOf": asof.isoformat() if asof else None,
            "ageDays": age,
            "sla": sla_days,
            "tier": tier,
            "state": state,
        })

    # 소스 자체가 실패를 자백한 경우 — diagnostics.*Source == "FAILED"
    failed_tops = set()
    for k, v in (data.get("diagnostics") or {}).items():
        if isinstance(v, str) and v.upper() == "FAILED" and k.endswith("Source"):
            failed_tops.add(k[:-6])          # stockMoversSource → stockMovers
    for it in items:
        if it["path"].split(".")[0] in failed_tops:
            it["state"] = "failed"

    counts = {}
    for it in items:
        counts[it["state"]] = counts.get(it["state"], 0) + 1
    blocking = [it["path"] for it in items
                if it["tier"] == "critical" and it["state"] in ("stale", "failed", "unknown")]
    return {
        "checkedAt": datetime.now().astimezone().isoformat(),
        "summary": {
            "total": len(items),
            "ok": counts.get("ok", 0),
            "preserved": counts.get("preserved", 0),
            "stale": counts.get("stale", 0),
            "failed": counts.get("failed", 0),
            "unknown": counts.get("unknown", 0),
        },
        "blocking": blocking,
        "items": sorted(items, key=lambda x: (x["state"] == "ok", x["path"])),
    }


def _demo():
    """자체 점검 — 규칙·파서가 깨지면 여기서 걸린다."""
    assert _parse_date("2026-08-04") == date(2026, 8, 4)
    assert _parse_date("2026-08-04T12:00:00+09:00") == date(2026, 8, 4)
    assert _parse_date("202606") == date(2026, 6, 1)
    assert _parse_date("2026Q2") == date(2026, 4, 1)
    assert _parse_date("2026-13") is None and _parse_date("") is None and _parse_date(None) is None

    assert _extract_asof({"as_of": "2026-07-27"}) == date(2026, 7, 27)
    assert _extract_asof({"history": {"2026-01-02": 1, "2026-03-04": 2}}) == date(2026, 3, 4)
    assert _extract_asof([{"date": "2026-05-01"}, {"date": "2026-05-02"}]) == date(2026, 5, 2)
    assert _extract_asof({"items": [{"date": "2026-07-31"}, {"date": "2026-08-03"}]}) == date(2026, 8, 3)
    assert _extract_asof({"nope": 1}) is None

    assert _rule_for("history.indices.KOSPI") == (4, "critical")
    assert _rule_for("history.indices.Nikkei") == (4, "important")
    assert _rule_for("economicIndicators.uk.gdp_uk")[0] == 200      # 분기 규칙이 먼저 매치
    assert _rule_for("economicIndicators.jp.cpi_jp") == (100, "normal")
    assert _rule_for("전혀없는.경로") == DEFAULT_SLA

    sample = {
        "history": {"indices": {"KOSPI": [{"date": "2026-08-04", "close": 1}]}},
        "sentiment": {"vkospi": {"as_of": "2026-07-27", "value": 78.3}},
        "stockMovers": {"kospiGainers": [{"as_of": "2026-07-29"}]},
        "diagnostics": {"stockMoversSource": "FAILED"},
        "sources": {"sentiment": "이전 빌드 보존 ← prev"},
    }
    h = build_health(sample, today=date(2026, 8, 4))
    by = {i["path"]: i for i in h["items"]}
    assert by["history.indices.KOSPI"]["state"] == "ok", by["history.indices.KOSPI"]
    assert by["sentiment.vkospi"]["state"] == "stale", by["sentiment.vkospi"]
    assert by["stockMovers.kospiGainers"]["state"] == "failed", by["stockMovers.kospiGainers"]
    assert h["blocking"] == []
    # critical 이 늦으면 blocking 에 들어간다
    sample["history"]["indices"]["KOSPI"] = [{"date": "2026-07-01", "close": 1}]
    assert build_health(sample, today=date(2026, 8, 4))["blocking"] == ["history.indices.KOSPI"]
    print("data_sla self-check OK")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    else:
        with open("data.json", encoding="utf-8") as f:
            d = json.load(f)
        h = build_health(d)
        print(json.dumps(h["summary"], ensure_ascii=False))
        for it in h["items"]:
            if it["state"] != "ok":
                print(f"  {it['state']:9s} {it['path']:44s} asOf={it['asOf']} age={it['ageDays']} sla={it['sla']} tier={it['tier']}")
