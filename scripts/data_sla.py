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
    ("rankingsKr.*",                     4,   "important"),  # 토스 거래대금 + KRX 시총·거래량·52주(2026-10, 전일 확정치)
    ("marketBreadth*",                   4,   "important"),  # A19 KRX 등락 종목 수(전일 확정치) — 블록째 missing 도 같은 등급
    ("sectorMoves",                      4,   "important"),  # A19 코스피 업종 등락
    ("investorTrading",                  6,   "important"),
    ("sentiment.*",                      4,   "important"),
    ("freight",                          10,  "normal"),
    ("marketHalts",                      400, "normal"),
    ("corpEvents",                       3,   "normal"),    # OpenDART 배당·실적 일정 — 일일 런 하루 1회(as-of = 검색 끝 날짜)

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
# 월간 70 일로는 정상 갱신 중에도 지연으로 뜬다. 한국 수출 달러액(FRED XTEXVA01KRM667S,
# OECD MEI)은 약 3개월 늦다 — 2026-09-28 에 원천 최신이 6월이라 90일째 '지연'으로 떴지만
# 수집은 정상이었다(적시성은 ECOS 수출금액지수 exports_idx_kr 가 맡는다).
EXTRA_LAG = [("realestate.us.case_shiller*", 30), ("economicIndicators.kr.exports_kr", 60)]
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


# 거래일에만 값이 생기는 시장 경로 — 나이를 달력일이 아니라 평일 수로 센다. 달력일로 세면
# 2026-09-28(월) 아침, 추석 휴장(9/24·25)+주말 뒤 마지막 거래일 9/23 KOSPI 가 5일로 찍혀
# critical 게이트가 수집을 매번 막았다. 평일 4일이면 설 연휴(평일 3일 휴장) 뒤 첫 장 아침도 통과.
# ponytail: 공휴일 표 없이 주말만 거른다 — 평일 4일 넘게 쉬는 휴장이 생기면 KRX 휴장일 표로.
TRADING_DAY_PATHS = ("history.indices.*", "history.fx.*", "history.commodities.*",
                     "stockMovers.*", "etfMovers.*", "rankingsKr.*", "investorTrading",
                     "sentiment.*", "yieldCurve.*", "marketBreadth.*", "sectorMoves")


def _weekdays_between(a, b):
    """a 다음 날부터 b 까지의 평일 수."""
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        n += d.weekday() < 5
    return n


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


def _raw_asof(node, depth=0):
    """as-of 원문(주기 추론용). 자기 키에 없으면 첫 자식(시도별 칸 dict·행 list)의 것 — 2026-10-02 전엔
    realestate.kr.region·region_sub 가 이것 없이 주기를 몰라 기본 60일(기간 시작일부터)로 재여 정상 갱신 중에도 '지연'이었다."""
    if isinstance(node, dict):
        for k in _ASOF_KEYS:
            if isinstance(node.get(k), str):
                return node[k]
    kids = list(node.values()) if isinstance(node, dict) else node if isinstance(node, list) else []
    if depth < 2 and kids and isinstance(kids[0], (dict, list)):
        return _raw_asof(kids[0], depth + 1)
    return None


# 블록 전체가 하나의 지표로 취급되는 최상위 키 (내부를 쪼개지 않는다)
_ATOMIC_TOPS = ("freight", "investorTrading", "news", "economicCalendar", "marketCalendarKr",
                "nps", "subscription", "marketHalts", "aiBriefing", "lmeInventory", "sectorMoves",
                "corpEvents")   # 배당·실적 일정(2026-10) — items·corpMap 을 쪼개지 않는다. as-of = 공시 검색 끝 날짜
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
                  # 2026-09-30 사용자 결정(D1): sentiment.pcr · realestate.kr.conversion_rate_kr ·
                  # climate.enso.forecast 는 원천이 없거나 화면 필수가 아니라 기대 목록에서 뺐다
                  # (없는 걸 매 런 '실종'으로 세면 경고가 상시라 진짜 실종이 묻힌다).
                  "realestate.kr.region", "realestate.kr.region_sub",
                  # A19(2026-09-30): 프런트(주식시장 시장 폭·업종 등락)가 읽기 시작해 기대 목록에 넣음 —
                  #   KRX /sto/·/idx/ 승인이 풀리면 채워지고, 그 전엔 실종으로 드러나는 것이 맞다.
                  "marketBreadth", "sectorMoves")
# A19 marketBreadth · sectorMoves 는 프런트가 읽기 시작하면 여기에 넣는다(리드가 프런트 연결 뒤 추가).
# 읽는 화면이 없는데 넣으면 KRX 승인 전 매 런 missing 2줄이 상시 경고가 된다.

# ── 합리 범위표 (A9) ───────────────────────────────────────────────────────
# (glob 경로, 하한, 상한, 하루 최대 변화율 %(없으면 None), 메모). 값이 범위를 벗어나면
# state="suspect"(검증 필요). 왜: as-of 가 신선해도 값 자체가 엉뚱한 칸(호수 자리의 지수값,
# 단위가 다른 표)이면 신선도 판정은 ok 로 통과한다 — 2026-09-30 첫 포착: '미분양' 300,827.99 · '착공' 100.44 는
# 표 오인이었다(실제 = 평균전세가격 천원 · 준전세가격지수) → 키를 바로잡고 새 키에 범위를 건다. 차단은 하지 않는다(경고만).
# 값은 leaf 의 value → price → rate 순, 수익률곡선은 current 리스트 전체를 본다.
# ⚠ cpi 는 나라마다 단위가 다르다(cn·uk = 전년동월비 %, us·eu·de·kr = 지수 수준 120~334)라
#   전체 glob 을 걸면 거짓 경보가 난다 — yoy 인 나라만 명시.
RANGE_RULES = [
    ("realestate.kr.avg_jeonse_price_kr", 50000, 1000000, None, "천원 — 전국 아파트 평균 전세가격(R-ONE A_2024_00064)"),
    ("realestate.kr.semi_jeonse_idx_kr",  50,    200,     None, "지수 2026.06=100 — 전국 아파트 준전세가격지수(A_2024_00057)"),
    # 주택 공급 4표(2026-10-01, R-ONE T 표) — 호, 전국 월. 통계누리 2026-08: 미분양 69,134 · 착공 18,013 · 준공 15,151.
    ("realestate.kr.unsold_total_kr",     10000, 200000,  None, "호 — 전국 미분양주택(KOSIS 116/DT_MLTM_2080 전국·총합·총합)"),
    ("realestate.kr.housing_start_kr",    3000,  100000,  None, "호 — 전국 주택 착공실적(R-ONE T233033129823134)"),
    ("realestate.kr.housing_permit_kr",   3000,  150000,  None, "호 — 전국 주택건설 인허가실적(R-ONE T235263129553687)"),
    ("realestate.kr.housing_complete_kr", 3000,  100000,  None, "호 — 전국 주택 준공실적(R-ONE T237273130004614)"),
    ("fx.USDKRW",                       800,   2500,   None, "원/달러"),
    ("indices.KOSPI",                   1000,  10000,  None, "코스피 지수"),
    ("sentiment.vkospi",                5,     100,    None, "변동성지수"),
    ("sentiment.fear_greed",            0,     100,    None, "0~100 지수"),
    ("yieldCurve.*",                    -2,    20,     None, "금리 %"),
    ("economicIndicators.cn.cpi_*",     -5,    30,     None, "전년동월비 %"),
    ("economicIndicators.uk.cpi_*",     -5,    30,     None, "전년동월비 %"),
    ("marketBreadth.*",                 0,     3000,   None, "종목 수(up·down·flat·limitUp·limitDown)"),
]


def _get_path(data, path):
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


# 폐기(묘비) 지표 — 수집 소스가 없어 지표째 뺀 잎. 한 곳에서 정의해 fetch_data(preserve·lane 부활 차단)·
# 판정표(_walk_paths)·지표 레지스트리(build_indicators)가 같이 본다. 값 = {부모 경로: (잎 키, …)}.
# 대체 소스가 생기면 여기서 뺀다. (eu 실업률·uk/cn CPI 는 intl_sources 가, 일본 CPI 는 DBnomics 가
# 같은 키를 다시 채우므로 묘비 대상이 아니다.)
TOMBSTONED = {
    # JPNPROINDMISMEI(2024-03 종료), OECD 도 같은 상류. DBnomics 검색에도 최신 계열 없음(2026-09-30).
    "economicIndicators.jp": ("ip_jp",),
    # NAHBMMI 는 FRED 400, 폴백 MSACSR 은 다른 지표(재고 개월 수)였다 — 대체 소스 없음.
    "realestate.us": ("nahb_index",),
    # R-ONE 표 오인(2026-09-30): 두 표는 평균전세가격·준전세가격지수였다 → avg_jeonse_price_kr·semi_jeonse_idx_kr
    # 로 옮겼다. 옛 키가 lane·preserve 로 되살아나 '미분양 300,828호'가 다시 뜨지 않게 묻는다.
    # conversion_rate_kr: 사용자 결정 D1(2026-09-30) — 전월세전환율은 무료 공식 경로가 없다(R-ONE 2024-04 이후 갱신 없음).
    "realestate.kr": ("unsold_kr", "start_kr", "conversion_rate_kr"),
}


def is_tombstoned(path):
    """'realestate.kr.conversion_rate_kr' → True. 부모 경로 + 잎 키로 묘비 표를 본다."""
    parent, _, leaf = path.rpartition(".")
    return leaf in TOMBSTONED.get(parent, ())


def drop_tombstoned(data):
    """묘비 잎을 data 에서 뺀다(제자리). 모든 preserve·lane 이음 뒤에 불러야 한다. Returns: 뺀 경로 목록."""
    removed = []
    for parent, leaves in TOMBSTONED.items():
        top, sub = parent.split(".")
        node = (data.get(top) or {}).get(sub)
        if isinstance(node, dict):
            for leaf in leaves:
                if node.pop(leaf, None) is not None:
                    removed.append(f"{parent}.{leaf}")
    return removed


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
                    if isinstance(v2, (dict, list)) and not is_tombstoned(f"{top}.{k}.{k2}"):
                        out.append((f"{top}.{k}.{k2}", v2))
            else:
                out.append((f"{top}.{k}", v))
    return out


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _range_checks(data):
    """RANGE_RULES 위반 {경로: 사유}. 걷기 대상이 아닌 현재가 블록(fx·indices)도 본다."""
    bad = {}

    def visit(node, path, depth):
        if not isinstance(node, dict) or depth > 3:
            return
        for pat, lo, hi, max_chg, _note in RANGE_RULES:
            if not fnmatch.fnmatchcase(path, pat):
                continue
            cur = node.get("current")
            vals = [_num(v) for v in cur] if isinstance(cur, list) else \
                   [next((_num(node.get(k)) for k in ("value", "price", "rate") if _num(node.get(k)) is not None), None)]
            if vals == [None] and "up" in node:   # 값 칸이 없는 개수 묶음(A19 marketBreadth.*)
                vals = [_num(node.get(k)) for k in ("up", "down", "flat", "limitUp", "limitDown")]
            vals = [v for v in vals if v is not None]
            why = next((f"{v:g} 가 합리 범위 {lo}~{hi} 밖" for v in vals if not lo <= v <= hi), None)
            prev, v0 = _num(node.get("prev")), vals[0] if vals else None
            if not why and max_chg and prev and v0 is not None and abs(v0 - prev) / abs(prev) * 100 > max_chg:
                why = f"전일 대비 {abs(v0 - prev) / abs(prev) * 100:.1f}% > 하루 상한 {max_chg}%"
            if why:
                bad[path] = why
                return
        for k, v in node.items():
            visit(v, f"{path}.{k}", depth + 1)

    for top, node in data.items():
        if top not in _SKIP_TOPS:
            visit(node, top, 1)
    return bad


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
        # 경로 자신의 소스 라벨이 먼저다 — 한 블록에 원천이 둘인 곳(stockMovers: 코스피=토스, 코스닥=KRX)에서
        # 한쪽의 '보존' 라벨이 다른 쪽까지 보존으로 읽히지 않게. 점 경로 키는 A19 전엔 없었다(종전 판정 불변).
        src = sources.get(path) or sources.get(top) or ""
        # 보존 판정 두 갈래: sources 라벨의 '보존' 또는 leaf 자체의 preserved 표식(fetch_data 가
        # 직전 빌드에서 되살린 leaf 에 단다 — 이번 런에 수집되지 않았다는 사실이 as-of 가
        # SLA 안이라는 이유로 가려지지 않게).
        # 목록 잎(stockMovers.kosdaqGainers)은 행마다 표식이 달린다 — 전부 달렸으면 보존.
        leaf_preserved = (isinstance(node, dict) and node.get("preserved") is True) or (
            isinstance(node, list) and bool(node)
            and all(isinstance(r, dict) and r.get("preserved") is True for r in node))
        preserved = "보존" in str(src) or leaf_preserved
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
            age = (_weekdays_between(asof, today)
                   if any(fnmatch.fnmatchcase(path, p) for p in TRADING_DAY_PATHS)
                   else (today - asof).days)
            state = "stale" if age > sla_days else "ok"
        if preserved and state == "ok":
            state = "preserved"
        item = {
            "path": path,
            "asOf": asof.isoformat() if asof else None,
            "ageDays": age,
            "sla": sla_days,
            "tier": tier,
            "state": state,
            "cadence": cadence,
        }
        if leaf_preserved:
            item["preserved"] = True
        items.append(item)

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
        if it["path"].split(".")[0] in failed_tops and it["path"] not in sources:   # 자기 소스가 있으면 따로 판정
            it["state"] = "failed"

    # 합리 범위 — 신선해도 값이 엉뚱하면 suspect. failed·missing 은 더 나쁜 상태라 덮지 않는다.
    by_path = {it["path"]: it for it in items}
    for path, why in _range_checks(data).items():
        it = by_path.get(path)
        if it is None:                       # fx·indices 같은 현재가 블록 — 판정표에 행이 없다
            it = {"path": path, "asOf": None, "ageDays": None, "sla": None, "tier": "important"}
            items.append(it)
        if it.get("state") not in ("failed", "missing"):
            it["state"], it["reason"] = "suspect", why

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
            "suspect": counts.get("suspect", 0),
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
        "kr": {"cpi_kr": {"period": "2026-04-01", "history": {"2026-02-01": 1, "2026-03-01": 1, "2026-04-01": 1}},
               "exports_kr": {"period": "2026-04-01", "history": {"2026-02-01": 1, "2026-03-01": 1, "2026-04-01": 1}}},
    }
    h = build_health(sample, today=date(2026, 8, 4))
    by = {i["path"]: i for i in h["items"]}
    assert by["history.indices.KOSPI"]["state"] == "ok", by["history.indices.KOSPI"]
    assert by["economicIndicators.cn.gdp_cn"]["state"] == "ok", by["economicIndicators.cn.gdp_cn"]      # 연간, 연말+216일
    assert by["economicIndicators.kr.cpi_kr"]["state"] == "stale", by["economicIndicators.kr.cpi_kr"]  # 월간, 4월말+95일
    assert by["economicIndicators.kr.exports_kr"]["state"] == "ok", by["economicIndicators.kr.exports_kr"]  # 같은 95일이나 원천 3개월 지연(EXTRA_LAG)
    assert by["sentiment.vkospi"]["state"] == "stale", by["sentiment.vkospi"]
    assert by["stockMovers.kospiGainers"]["state"] == "failed", by["stockMovers.kospiGainers"]
    assert by["berkshire"]["state"] == "missing", by["berkshire"]      # _EXPECTED_TOPS 실종 감지
    assert by["lmeInventory"]["state"] == "missing", by["lmeInventory"]
    assert h["summary"]["missing"] == 2 + 4          # berkshire·lme + 화면 공백 경로 2(region·region_sub)
    assert by["marketBreadth"]["state"] == "missing" and by["sectorMoves"]["state"] == "missing"    # A19 — 프런트가 읽어 기대 목록에 넣음
    assert _rule_for("marketBreadth") == (4, "important") and _rule_for("marketBreadth.kospi") == (4, "important")
    for gone in ("sentiment.pcr", "climate.enso.forecast", "realestate.kr.conversion_rate_kr"):
        assert gone not in by, gone                    # 2026-09-30 D1: 기대 목록에서 제외
    # lmeInventory 는 원자 블록 — as_of 로 블록 단위 판정
    assert _extract_asof({"data": [{"cur": 1}], "as_of": "2026-08-03"}) == date(2026, 8, 3)
    # lastFetched(수집 시각)는 as-of 로 인정하지 않는다 — 내용 날짜 items 로 내려가야 함
    assert _extract_asof({"lastFetched": "2026-08-04T09:00:00+09:00",
                          "items": [{"date": "2026-07-31"}]}) == date(2026, 7, 31)
    assert h["blocking"] == []
    # critical 이 늦으면 blocking 에 들어간다
    sample["history"]["indices"]["KOSPI"] = [{"date": "2026-07-01", "close": 1}]
    assert build_health(sample, today=date(2026, 8, 4))["blocking"] == ["history.indices.KOSPI"]
    # 추석 휴장+주말 뒤 월요일 아침: 마지막 거래일 9/23 은 달력 5일이지만 평일 3일 → 통과
    sample["history"]["indices"]["KOSPI"] = [{"date": "2026-09-23", "close": 1}]
    assert "history.indices.KOSPI" not in build_health(sample, today=date(2026, 9, 28))["blocking"]

    # 이번 런 미수집(preserved 표식) — as-of 가 SLA 안이어도 preserved, 차단 아님
    s2 = {"sentiment": {"vkospi": {"as_of": "2026-08-04", "value": 30, "preserved": True}}}
    h2 = build_health(s2, today=date(2026, 8, 4))
    v = {i["path"]: i for i in h2["items"]}["sentiment.vkospi"]
    assert v["state"] == "preserved" and v.get("preserved") is True and h2["summary"]["preserved"] == 1, v
    assert h2["blocking"] == []
    # 합리 범위 — 범위 밖은 suspect(사유 포함, 차단 아님). fx 는 걷기 대상이 아니어도 잡힌다
    s3 = {"realestate": {"kr": {"avg_jeonse_price_kr": {"period": "202608", "value": 3008.28},   # 천원 자리에 만원값
                                "semi_jeonse_idx_kr": {"period": "202608", "value": 1004.4}}},
          "fx": {"USDKRW": {"rate": 5000}}, "indices": {"KOSPI": {"price": 6902.9}},
          "yieldCurve": {"us": {"current": [4.0, 25.0]}},
          "sentiment": {"vkospi": {"as_of": "2026-08-04", "value": 44.7}}}
    h3 = build_health(s3, today=date(2026, 8, 4))
    b = {i["path"]: i for i in h3["items"]}
    for p in ("realestate.kr.avg_jeonse_price_kr", "realestate.kr.semi_jeonse_idx_kr", "fx.USDKRW", "yieldCurve.us"):
        assert b[p]["state"] == "suspect" and b[p]["reason"], (p, b[p])
    assert "indices.KOSPI" not in b and b["sentiment.vkospi"]["state"] == "ok"
    assert h3["summary"]["suspect"] == 4 and h3["blocking"] == []
    # 오인됐던 실측값은 새 키에선 정상 범위다(평균전세가격 3억 원 · 준전세지수 100.44)
    ok3 = {"realestate": {"kr": {"avg_jeonse_price_kr": {"period": "202608", "value": 300827.99},
                                 "semi_jeonse_idx_kr": {"period": "202608", "value": 100.44}}}}
    assert _range_checks(ok3) == {}

    # A19 — 등락 종목 수(평일 수로 셈)·업종(원자 블록)·코스닥 목록 행 보존·종목 수 범위
    s4 = {"marketBreadth": {"kospi": {"up": 500, "down": 300, "flat": 50, "limitUp": 2, "limitDown": 0,
                                      "as_of": "2026-09-25"},
                            "kosdaq": {"up": 5000, "down": 1, "flat": 1, "limitUp": 0, "limitDown": 0,
                                       "as_of": "2026-09-25"},
                            "source": "KRX"},
          "sectorMoves": {"as_of": "2026-09-25", "items": [{"name": "화학", "close": 1.0, "chg_pct": 1.0}]},
          "stockMovers": {"kosdaqGainers": [{"as_of": "2026-09-25", "chg": 30, "preserved": True}],
                          "kospiGainers": [{"as_of": "2026-09-25", "chg": 3}]}}
    b4 = {i["path"]: i for i in build_health(s4, today=date(2026, 9, 28))["items"]}   # 금→월 = 평일 1일
    assert b4["marketBreadth.kospi"]["state"] == "ok" and b4["sectorMoves"]["state"] == "ok", b4
    assert b4["marketBreadth.kosdaq"]["state"] == "suspect", b4["marketBreadth.kosdaq"]   # 5000 > 3000
    assert b4["stockMovers.kosdaqGainers"]["state"] == "preserved", b4["stockMovers.kosdaqGainers"]
    assert b4["stockMovers.kospiGainers"]["state"] == "ok"
    # 한 블록 두 원천 — 코스피(토스) 실패·보존이 제 소스를 가진 코스닥(KRX) 목록으로 번지지 않는다
    s5 = {"stockMovers": {"kospiGainers": [{"as_of": "2026-09-25"}], "kosdaqGainers": [{"as_of": "2026-09-25"}]},
          "sources": {"stockMovers.kosdaqGainers": "KRX OpenAPI"}, "diagnostics": {"stockMoversSource": "FAILED"}}
    b5 = {i["path"]: i for i in build_health(s5, today=date(2026, 9, 28))["items"]}
    assert b5["stockMovers.kospiGainers"]["state"] == "failed" and b5["stockMovers.kosdaqGainers"]["state"] == "ok"
    s5["sources"]["stockMovers"], s5["diagnostics"] = "이전 빌드 보존 ← 토스증권", {}
    b5 = {i["path"]: i for i in build_health(s5, today=date(2026, 9, 28))["items"]}
    assert b5["stockMovers.kospiGainers"]["state"] == "preserved" and b5["stockMovers.kosdaqGainers"]["state"] == "ok"

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
