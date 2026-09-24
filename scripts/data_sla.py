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
import os
import re
import sys
from datetime import date, datetime, timedelta

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
    ("history.commodities.Dubai",        None, "normal"),    # FRED 월간 — 주기에서 도출
    ("history.commodities.*",            5,   "important"),

    # 장중 스냅샷
    ("stockMovers.*",                    4,   "important"),
    ("etfMovers.*",                      4,   "important"),
    ("rankingsKr.*",                     4,   "important"),
    ("investorTrading",                  6,   "important"),
    ("sentiment.*",                      4,   "important"),
    ("freight",                          10,  "normal"),
    ("marketHalts",                      400, "normal"),

    # 거시 — 일간 시리즈만 명시, 나머지는 주기에서 도출(None)
    ("economicIndicators.us.vix",        6,   "important"),
    ("economicIndicators.us.hy_spread",  6,   "normal"),
    ("economicIndicators.us.broad_dollar", 10, "normal"),  # FRED H.10 — 주 1회(월) 전주분 공표
    ("economicIndicators.*",             None, "normal"),
    ("realestate.*",                     None, "normal"),
    ("yieldCurve.*",                     6,   "important"),
    ("nps",                              400, "normal"),
    ("berkshire",                        200, "normal"),    # SEC 13F — 분기 공시
    ("lmeInventory",                     7,   "normal"),    # Westmetall 일일 재고
    ("mer_series",                       7,   "normal"),
    ("mer_signals",                      7,   "normal"),
    ("subscription",                     40,  "normal"),
    ("climate.*",                        None, "normal"),
    ("news",                             2,   "important"),
    ("economicCalendar",                 10,  "normal"),   # as-of = 지난 발표 중 가장 최근(주 단위로 있다)
    ("marketCalendarKr",                 4,   "normal"),
    ("aiBriefing",                       2,   "normal"),
]

# 주기별 허용치 — '기간이 끝난 날'부터 센다(2026-09-24 개편). 종전엔 기간 시작일(월 1일·
# 분기 첫날·연 1월 1일)부터 세면서 경로마다 100·150·200 일을 손으로 맞췄고, 연간 지표
# (중국 GDP)·월간 곡선(일본 10년물)이 상시 '지연'으로 떠 경고 9건 중 5건이 거짓이었다.
# 값 = 공표 지연 + 여유. 월간 70 = 대부분 다음 달 중순~말 공표, 분기 120, 연간 300.
CADENCE_SLA = {"daily": 4, "weekly": 12, "monthly": 70, "quarterly": 120, "annual": 300}
_PERIOD_MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}
# 주기 허용치에 더하는 경로별 공표 지연(일). 케이스실러는 두 달 뒤 마지막 화요일 공표라
# 월간 70 일로는 정상 갱신 중에도 지연으로 뜬다.
EXTRA_LAG = [("realestate.us.case_shiller*", 30)]
DEFAULT_SLA = (60, "normal")

# as-of 로 인정하는 키 (우선순위 순)
# ⚠ lastFetched 는 여기 넣지 않는다 — '우리가 언제 돌았나'(수집 시각)이지 '데이터가 언제
#   것인가'(as-of)가 아니다. 이 키가 들어있던 동안 freight(내용 07-31)·news(6개 카테고리
#   빈 배열) 등 8개 원자 블록이 수집 시각으로 자기 신선도를 증명해 영원히 ok 였다(2026-08 감사).
#   lastFetched 를 빼면 items/daily/events 등 내용 날짜 경로로 내려가고, 그것도 없으면
#   unknown 으로 정직하게 보고된다.
_ASOF_KEYS = ("as_of", "asOf", "asof", "period", "date", "iso", "isoDate", "weekEnding",
              "reportDate", "filedDate", "lastUpdated", "checkedAt")


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
    # ONI 계절 코드 'JAS 2026' → 가운데 달(8월). NDJ 는 12월, DJF 는 1월(해당 연도).
    m = re.match(r"^([A-Z]{3})\s+(\d{4})$", s)
    if m and m.group(1) in _SEASON_MID:
        return date(int(m.group(2)), _SEASON_MID[m.group(1)], 1)
    return None


_SEASON_MID = {"DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
               "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12}


_TODAY = [None]   # build_health 가 판정 기준일을 넣는다(러너는 UTC — KST 오늘 값을 미래로 버리지 않게)


def _past(d):
    """미래 날짜는 as-of 가 아니다 — 경제 캘린더의 다음 달 일정이 '최신'으로 잡혀
    영원히 ok 가 되는 것을 막는다. 하루 여유는 UTC 러너가 KST 오늘 날짜를 받는 경우."""
    ref = _TODAY[0] or date.today()
    return d if d and d <= ref + timedelta(days=1) else None


def _extract_asof(node):
    """지표 노드에서 as-of 날짜를 뽑는다. dict/list 형태를 모두 다룬다(미래 날짜 제외)."""
    if isinstance(node, list):
        # [{date: ...}, ...] 시계열 — 뒤쪽이 최신
        ds = [d for d in (_extract_asof(i) for i in node[-40:] if isinstance(i, (dict, list))) if d]
        return max(ds) if ds else None
    if not isinstance(node, dict):
        return None
    for k in _ASOF_KEYS:
        d = _past(_parse_date(node.get(k)))
        if d:
            return d
    # history 가 {날짜: 값} 형태면 최대 키가 as-of
    hist = node.get("history")
    if isinstance(hist, dict) and hist:
        ds = [x for x in (_past(_parse_date(k)) for k in hist) if x]
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


def _history_dates(node):
    """노드의 시계열 날짜들(정렬). {날짜: 값}·[{date: …}]·노드 자체가 리스트인 경우,
    그리고 자식들이 각자 history 를 가진 묶음(예: 주별 HPI 51개)이면 첫 자식 것."""
    if isinstance(node, list):
        return sorted(d for d in (_parse_date(p.get("date")) for p in node if isinstance(p, dict)) if d)
    if not isinstance(node, dict):
        return []
    if "history" not in node:
        for v in node.values():
            if isinstance(v, dict) and "history" in v:
                return _history_dates(v)
        return []
    h = node.get("history")
    if isinstance(h, dict):
        ds = [_parse_date(k) for k in h]
    elif isinstance(h, list):
        ds = [_parse_date(p.get("date")) for p in h if isinstance(p, dict)]
    else:
        return []
    return sorted(d for d in ds if d)


def infer_cadence(node, asof_raw=None):
    """지표의 공표 주기. 우선순위: 노드의 cadence 선언 → history 간격 중앙값 → period 형식."""
    if isinstance(node, dict) and node.get("cadence") in CADENCE_SLA:
        return node["cadence"]
    ds = _history_dates(node)[-13:]
    if len(ds) >= 3:
        gaps = sorted((b - a).days for a, b in zip(ds, ds[1:]))
        g = gaps[len(gaps) // 2]
        if g <= 4:
            return "daily"
        if g <= 10:
            return "weekly"
        if g <= 45:
            return "monthly"
        if g <= 140:
            return "quarterly"
        return "annual"
    if isinstance(asof_raw, str):
        if re.match(r"^[A-Z]{3}\s+\d{4}$", asof_raw):     # ONI 계절(3개월 이동평균, 매월 갱신)
            return "monthly"
        if re.match(r"^\d{4}Q[1-4]$", asof_raw):
            return "quarterly"
        if re.match(r"^\d{4}[-.]?\d{2}$", asof_raw):
            return "monthly"
    return None


def _period_end(asof, cadence):
    """기간 시작일(as-of) → 기간 마지막 날. 일간·주간은 as-of 가 곧 그 날."""
    n = _PERIOD_MONTHS.get(cadence)
    if not n:
        return asof
    y, m = asof.year, asof.month + n
    while m > 12:
        y, m = y + 1, m - 12
    return date(y, m, 1) - timedelta(days=1)


def _raw_asof(node):
    if isinstance(node, dict):
        for k in _ASOF_KEYS:
            if isinstance(node.get(k), str):
                return node[k]
    return None


# 블록 전체가 하나의 지표로 취급되는 최상위 키 (내부를 쪼개지 않는다)
_ATOMIC_TOPS = ("freight", "investorTrading", "news", "economicCalendar", "marketCalendarKr",
                "nps", "subscription", "marketHalts", "aiBriefing", "lmeInventory")
_SKIP_TOPS = ("lastUpdated", "sources", "diagnostics", "dataHealth")
# 현재가 스냅샷 블록 — 자체 날짜 필드가 없고 신선도는 같은 심볼의 history 가 대변한다.
# 여기서 판정하면 심볼마다 'unknown' 이 중복으로 쌓여 요약이 무의미해진다.
_SPOT_TOPS = ("indices", "commodities", "fx")
# 프런트가 렌더하지만 수집 실패 시 키 자체가 사라질 수 있는 최상위 블록.
# SLA 는 '존재하는 키'만 순회하므로 통째 실종은 보이지 않는다 — 여기 있는 키가
# data 에 없으면 state="missing" 으로 보고한다. (실측: berkshire 가 SEC 13F 실패 +
# prev 에도 없어 키째 사라졌는데 몇 달간 아무도 몰랐다 — 2026-08 감사.)
_EXPECTED_TOPS = ("berkshire", "lmeInventory",
                  # 프런트가 읽는데 수집 실패 시 키째 사라지는 경로(2026-09-24 감사 F6) — 화면에서는
                  # 빈 카드·시드값 지도·안 그려지는 차트로 보였고 판정표에는 흔적이 없었다.
                  "sentiment.pcr", "realestate.kr.region", "realestate.kr.region_sub",
                  "commoditiesKr", "climate.enso.forecast")


def _get_path(data, path):
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


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
    _TODAY[0] = today
    sources = sources if sources is not None else (data.get("sources") or {})
    items = []
    for path, node in _walk_paths(data):
        sla_days, tier = _rule_for(path)
        asof = _extract_asof(node)
        cadence = infer_cadence(node, _raw_asof(node))
        top = path.split(".")[0]
        src = sources.get(top) or sources.get(path) or ""
        preserved = "보존" in str(src)
        if asof is None:
            state, age = "unknown", None
        elif sla_days is None:
            # 주기 도출 — 기간이 끝난 날부터 센다. 주기를 모르면 종전 기본값(시작일 기준).
            if cadence in CADENCE_SLA:
                sla_days = CADENCE_SLA[cadence] + next(
                    (d for pat, d in EXTRA_LAG if fnmatch.fnmatchcase(path, pat)), 0)
                age = (today - _period_end(asof, cadence)).days
            else:
                sla_days = DEFAULT_SLA[0]
                age = (today - asof).days
            state = "stale" if age > sla_days else "ok"
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
            "cadence": cadence,
        })

    # 통째 실종 감지 — 있어야 할 최상위 블록이 키째 없으면 missing
    for path in _EXPECTED_TOPS:
        if _get_path(data, path) in (None, {}, []):
            sla_days, tier = _rule_for(path)
            items.append({"path": path, "asOf": None, "ageDays": None,
                          "sla": sla_days, "tier": tier, "state": "missing"})

    # 현재가 블록 — 판정은 history 가 대변하지만, 수집 실패로 직전 값을 되살린 leaf
    # (stale=True, fetch_data._prev_spot)는 여기서 드러낸다. 종전엔 하드코딩 상수가
    # 들어가도 판정표에 흔적이 없었다(2026-09-24 감사 F11·F13).
    for top in _SPOT_TOPS:
        for name, leaf in (data.get(top) or {}).items():
            if isinstance(leaf, dict) and leaf.get("stale"):
                items.append({"path": f"{top}.{name}", "asOf": leaf.get("asOf"), "ageDays": None,
                              "sla": None, "tier": "important", "state": "preserved"})

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
            "missing": counts.get("missing", 0),
        },
        "blocking": blocking,
        "items": sorted(items, key=lambda x: (x["state"] == "ok", x["path"])),
    }


# ── 독립 파일 신선도 ─────────────────────────────────────────────────────
# mer_series.json/mer_signals.json 은 data.json 에 병합되지 않는 별도 산출물이라
# 위 SLA_RULES(경로 기반, data.json 내부 전용) 로는 판정할 수 없다 — 파일 자체의
# 최상위 asOf 로 직접 판정한다. mer_signals.json 은 P2(집계)에서 생성될 예정이라
# 아직 없을 수 있음 — 그때는 에러가 아니라 skip.
EXTERNAL_FILES = [
    ("mer_series.json", 7),
    ("mer_signals.json", 7),
]


def check_external_files(root="."):
    out = []
    for name, sla_days in EXTERNAL_FILES:
        path = os.path.join(root, name)
        if not os.path.exists(path):
            out.append({"file": name, "state": "skip", "reason": "파일 없음(미생성)"})
            continue
        try:
            with open(path, encoding="utf-8") as f:
                node = json.load(f)
        except (OSError, ValueError) as e:
            out.append({"file": name, "state": "unknown", "reason": str(e)})
            continue
        asof = _extract_asof(node)
        if asof is None:
            out.append({"file": name, "state": "unknown", "asOf": None})
            continue
        age = (date.today() - asof).days
        out.append({"file": name, "state": "stale" if age > sla_days else "ok",
                    "asOf": asof.isoformat(), "ageDays": age, "sla": sla_days})
    return out


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
    assert _rule_for("economicIndicators.uk.gdp_uk") == (None, "normal")   # 주기에서 도출
    assert _rule_for("economicIndicators.us.vix") == (6, "important")
    # 주기 추정 + 기간 종료일 기준 판정
    assert _parse_date("JAS 2026") == date(2026, 8, 1)
    assert infer_cadence({"history": {"2026-01-01": 1, "2026-02-01": 1, "2026-03-01": 1}}) == "monthly"
    assert infer_cadence({"period": "2026Q2"}, "2026Q2") == "quarterly"
    assert infer_cadence([{"date": "2026-01-01"}, {"date": "2026-02-01"}, {"date": "2026-03-01"}]) == "monthly"
    assert _period_end(date(2026, 6, 1), "monthly") == date(2026, 6, 30)
    assert _period_end(date(2025, 1, 1), "annual") == date(2025, 12, 31)
    # 미래 날짜는 as-of 가 아니다(경제 캘린더의 다음 달 일정)
    assert _extract_asof({"events": [{"iso": "2000-01-05"}, {"iso": "2999-01-01"}]}) == date(2000, 1, 5)
    assert _rule_for("전혀없는.경로") == DEFAULT_SLA

    sample = {
        "history": {"indices": {"KOSPI": [{"date": "2026-08-04", "close": 1}]}},
        "sentiment": {"vkospi": {"as_of": "2026-07-27", "value": 78.3}},
        "stockMovers": {"kospiGainers": [{"as_of": "2026-07-29"}]},
        "diagnostics": {"stockMoversSource": "FAILED"},
        "sources": {"sentiment": "이전 빌드 보존 ← prev"},
    }
    sample["economicIndicators"] = {
        "cn": {"gdp_cn": {"period": "2025-01-01", "history": {"2023-01-01": 1, "2024-01-01": 1, "2025-01-01": 1}}},
        "kr": {"exports_kr": {"period": "2026-04-01", "history": {"2026-02-01": 1, "2026-03-01": 1, "2026-04-01": 1}}},
    }
    h = build_health(sample, today=date(2026, 8, 4))
    by = {i["path"]: i for i in h["items"]}
    assert by["history.indices.KOSPI"]["state"] == "ok", by["history.indices.KOSPI"]
    assert by["economicIndicators.cn.gdp_cn"]["state"] == "ok", by["economicIndicators.cn.gdp_cn"]      # 연간, 연말+216일
    assert by["economicIndicators.kr.exports_kr"]["state"] == "stale", by["economicIndicators.kr.exports_kr"]  # 월간, 4월말+95일
    assert by["sentiment.vkospi"]["state"] == "stale", by["sentiment.vkospi"]
    assert by["stockMovers.kospiGainers"]["state"] == "failed", by["stockMovers.kospiGainers"]
    assert by["berkshire"]["state"] == "missing", by["berkshire"]      # _EXPECTED_TOPS 실종 감지
    assert by["lmeInventory"]["state"] == "missing", by["lmeInventory"]
    assert h["summary"]["missing"] == 2 + 5          # berkshire·lme + 화면 공백 경로 5
    # lmeInventory 는 원자 블록 — as_of 로 블록 단위 판정
    assert _extract_asof({"data": [{"cur": 1}], "as_of": "2026-08-03"}) == date(2026, 8, 3)
    # lastFetched(수집 시각)는 as-of 로 인정하지 않는다 — 내용 날짜 items 로 내려가야 함
    assert _extract_asof({"lastFetched": "2026-08-04T09:00:00+09:00",
                          "items": [{"date": "2026-07-31"}]}) == date(2026, 7, 31)
    assert h["blocking"] == []
    # critical 이 늦으면 blocking 에 들어간다
    sample["history"]["indices"]["KOSPI"] = [{"date": "2026-07-01", "close": 1}]
    assert build_health(sample, today=date(2026, 8, 4))["blocking"] == ["history.indices.KOSPI"]

    # 독립 파일 신선도 — 없는 파일은 skip(에러 아님)
    res = check_external_files(root="__no_such_dir__")
    assert {r["file"]: r["state"] for r in res} == {"mer_series.json": "skip", "mer_signals.json": "skip"}
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
        for r in check_external_files():
            print(f"  [external] {r['file']:20s} state={r['state']} "
                  f"asOf={r.get('asOf')} age={r.get('ageDays')} sla={r.get('sla')} reason={r.get('reason', '')}")
