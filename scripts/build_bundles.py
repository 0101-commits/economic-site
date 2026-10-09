#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""화면 묶음 생성기 — 기획안 v4 P0.

왜 있나: 새 화면 층(app/, React)은 data.json(1.3MB)·mer_signals.json(1.4MB) 통째가 아니라
화면 하나가 쓰는 JSON 묶음만 받는다. 이름·자릿수·원본 화면은 지표 레지스트리
(build_indicators.build)에서, 이유 한 줄은 one_liners.py 에서 가져온다.

  data.json + mer_signals.json (+ toss_snapshot.json 의 시각)
    → bundles/registry.json · home.json · market-*.json(7) · lens.json · news.json · meta.json

규칙
- 값을 지어내지 않는다. 없는 값은 null, 상태는 'missing'.
- 신선도 상태 4종(+missing) — freshness() 한 곳에서 정한다.
    live  장중이고 값이 15분 이내
    prev  장이 닫혔거나(전일·직전 종가) 저빈도 지표의 확정치
    stale 장중 120분 · 장외 240분 · 주말·공휴일 720분 초과(시세), 저빈도는 data_sla 판정표의 stale
    kept  직전 값 보강(잎의 preserved:true · _prev_spot 의 stale:true · 판정표 preserved)
- 원본 값의 소수는 그대로 둔다. 반올림은 이 파일이 계산한 값(등락 포인트·비교 지수·프리미엄)만.
- 기준시각(asOf)은 소스가 준 시각·날짜다. 나이(분)는 화면이 meta.generatedAt 과 asOf 로 잰다
  (묶음에 나이를 적으면 내용이 그대로여도 매 런 파일이 바뀌어 커밋이 불어난다).

사용
  python scripts/build_bundles.py                      # bundles/ 생성
  python scripts/build_bundles.py --now 2026-10-01T10:00:00+09:00   # 기준 시각 고정(재현용)
"""
from __future__ import annotations

import ast
import datetime as dt
import email.utils
import html
import io
import json
import os
import re
import sys
import urllib.parse
import zoneinfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_indicators as bi  # noqa: E402
import data_sla  # noqa: E402
import nyse_calendar  # noqa: E402
import one_liners as ol  # noqa: E402
from check_text_limits import LIMITS  # noqa: E402  길이 상한 표(줄임 이름·이유 한 줄)의 단일 원천

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "bundles")
KST = dt.timezone(dt.timedelta(hours=9))
NY = zoneinfo.ZoneInfo("America/New_York")
MAX_BYTES = 200 * 1024

# ── 신선도 임계(분) ────────────────────────────────────────────────────────
# data_sla 의 임계는 '일' 단위(저빈도 지표용)라 시세에는 맞지 않는다 — 시세만 여기 분 단위로 잰다.
LIVE_MIN, STALE_OPEN_MIN, STALE_CLOSED_MIN, STALE_OFFDAY_MIN = 15, 120, 240, 720
# 판정표(data_sla.build_health) 상태 → 묶음 상태
HEALTH_STATE = {"ok": "prev", "suspect": "prev", "stale": "stale", "failed": "stale",
                "unknown": "stale", "preserved": "kept", "missing": "missing"}
STATES = ("live", "prev", "stale", "kept", "missing")
STATE_LABEL = {"live": "실시간", "prev": "직전 종가", "stale": "지연", "kept": "직전 값", "missing": "자료 없음"}

# 시세 칸이 어느 장을 따르나(없는 id = globex).
#   kr     코스피·코스닥 — 한국 정규장 09:00~15:30, 휴장은 marketCalendarKr
#   us     미국 지수 — 뉴욕 09:30~16:00, 휴장은 nyse_calendar, 서머타임은 zoneinfo
#   globex 환율·선물 원자재 — 뉴욕 일 18:00 ~ 금 17:00(매일 17~18시 휴식)
#   daily  KRX 금 — 전일 확정치 일봉이라 실시간일 수 없다. 기준일 = 소스 as_of
#   asia   닛케이·상하이·항셍 — 거래소 달력이 없어 실시간이라 하지 않는다(10/1 상하이 국경절 휴장)
# ponytail: globex 는 미국 공휴일 단축 거래를 모른다 — 그날은 '실시간'이 과하게 나올 수 있다.
MARKET_OF = {"kospi": "kr", "kosdaq": "kr", "sp500": "us", "nasdaq": "us", "sox": "us",
             "nikkei": "asia", "shanghai": "asia", "hsi": "asia", "goldkrw": "daily"}
# 원자재 분류(원자재 화면의 묶음 탭). 없는 id 는 agri 가 아니라 None — 새 품목은 여기 한 줄을 더한다.
COMMODITY_GROUP = {
    **{i: "energy" for i in ("wti", "brent", "dubai", "natgas", "gasoline", "heatingoil")},
    **{i: "metal" for i in ("gold", "goldkrw", "silver", "platinum", "palladium", "copper", "aluminum",
                            "zinc", "nickel", "lead", "tin")},
    **{i: "agri" for i in ("wheat", "corn", "soybean", "rice", "coffee", "sugar", "cocoa", "cotton")},
}
COUNT_UNITS = ("호", "건", "명")
# ETF 판정 — 원천 type 이 있으면 그것, 없으면 운용사 상표로 시작하는 이름. 종목코드로는 가를 수 없다
# (2024 년부터 일반 종목도 영숫자 신규 코드를 받는다).
ETF_PREFIX = ("KODEX", "TIGER", "KBSTAR", "RISE", "ACE", "HANARO", "SOL", "PLUS", "ARIRANG", "KOSEF",
              "KIWOOM", "TIMEFOLIO", "1Q", "WON", "BNK", "UNICORN", "TRUSTON", "VITA", "FOCUS", "KoAct",
              "TREX", "HK", "마이티", "에셋플러스", "히어로즈", "파워", "DAISHIN343", "KCGI", "WOORI")

# ── 지표 띠 — 기획안 v4 4장 「자산군별 지표 띠 6」(홈 8칸). 바꿀 때는 여기 한 곳만. ──────────
# 레지스트리 id 가 아닌 칸(flow_* · breadth_kospi · top20_amount · gold_premium · *_yoy · nps_kr_equity)은
# build_all 의 derived 가 data.json 경로에서 직접 만든다.
HOME_STRIP = ["kospi", "kosdaq", "sp500", "nasdaq", "usdkrw", "us10y", "wti", "gold"]
STRIPS = {
    "domestic": ["kospi", "kosdaq", "vkospi", "flow_foreign", "breadth_kospi", "top20_amount"],
    "global": ["sp500", "nasdaq", "sox", "nikkei", "shanghai", "hsi", "btc"],   # btc = 24시간 자산 — 알림 v2 A4(2026-10-05), 일곱째 칸
    "fxrates": ["usdkrw", "usdjpy", "jpykrw", "eurkrw", "us10y", "kr10y"],
    "commodities": ["wti", "brent", "gold", "silver", "copper", "natgas", "gold_premium"],
    "macro": ["cpi_kr_yoy", "base_rate_kr", "cpi_us_yoy", "unemployment", "exports_kr", "gdp_growth_us"],
    # 여섯째 칸은 기관 5일 누적 — 「외국인 보유 비중」 칸은 시장 전체 값을 어느 원천에서도 받지 않아(종목별 fholdRate 만)
    # 띠가 생긴 2026-10-01 부터 늘 「자료 없음」이었다(2026-10-09 점검).
    "flows": ["flow_foreign", "flow_inst", "flow_retail", "flow_foreign_5d", "nps_kr_equity", "flow_inst_5d"],
    "realestate": ["apt_price_idx_kr", "jns_price_idx_kr", "avg_jeonse_price_kr", "unsold_total_kr",
                   "housing_start_kr", "housing_permit_kr"],
}
CAPITAL_AREA = ["11", "41", "28"]
# 홈 「분위기」 5칸(기획 C3) — 레지스트리 id. hy_spread = economicIndicators.us.hy_spread(미국 하이일드 스프레드)
MOOD = ["fear_greed", "vix", "vkospi", "move", "hy_spread"]
# 자산군 화면 → news.json 주제. 원천 16주제(fetch_data.NEWS_CATEGORY_QUERIES)에 해외 주식·부동산 주제는 없다.
#   해외 = 미국CPI — 「주식」은 검색어가 「코스피 코스닥 시황」이라 국내 기사다. 미국CPI 는 제목 키워드에 연준·파월이
#          들어가 미국 증시를 움직이는 기사가 모인다(fetch_data._KEYLESS_CATEGORY_KEYWORDS).
#   환율·금리 = 외환(띠 6칸 중 환율 4) · 거시 = 한국GDP(거시 묶음의 기본 주제가 성장) · 부동산 = 없음(null)
MARKET_NEWS = {"domestic": "주식", "global": "미국CPI", "fxrates": "외환", "commodities": "원자재",
               "macro": "한국GDP", "flows": "주식", "realestate": None}
NEWS_MAX = 8        # news.json 주제당 기사 상한(원천은 주제당 5건 안팎)
# 전년비 파생 칸의 합리 범위(±%). 넘으면 값을 싣지 않고 meta.health.issues 에 남긴다 — 2026-10-01 한국 수출
# 70.7%(2025-06 589억 → 2026-06 1,006억 달러, 평소 550~650억)는 원본 이력의 단위·집계 변경이 의심됐다(팀장 결정).
YOY_GUARD_PCT = 50
# 범위를 넘어도 다른 원천의 같은 달 전년비와 이만큼(%p) 안이면 실제 값으로 본다 — 2026-10-02 실측: 수출 70.7% 는
# ECOS 관세청 수출금액지수 전년비 74.6% 와 맞았다(반도체 수출 급증, 원본 오류 아님. 팀장 결정).
YOY_CROSS_PP = 10
# 수도권 = 서울·경기·인천(region_sub 시도 코드)
CENTRAL_BANKS = [  # (나라, 레지스트리 id, 경제 일정에서 다음 회의를 찾을 말)
    ("kr", "base_rate_kr", r"금통위"), ("us", "ff_target", r"FOMC"),
    ("eu", "base_rate_eu", r"ECB"), ("jp", "base_rate_jp", r"BOJ|일본은행"),
    ("uk", "base_rate_uk", r"BOE|영란"),
]
CURVE_TENORS = ["1M", "3M", "6M", "1Y", "2Y", "5Y", "7Y", "10Y", "20Y", "30Y"]  # current 배열의 칸 순서(js/app1.js yieldCurveTerms)

# ── 줄임 이름 — 상한은 check_text_limits.LIMITS["short"](모바일, PC), 표시 폭(한글 1칸, 그 외 반 칸) ────
SHORT_M, SHORT_PC = LIMITS["short"]          # 상한 표의 단일 원천 = check_text_limits.LIMITS
# 지표 id → (PC, 모바일). 괄호를 떼도 상한을 넘는 것만 사람이 정한다. 넘는 행이 새로 생기면
# scripts/tests/test_build_bundles.py 가 실패하고 그 id 를 알려 준다 — 여기에 한 줄 더한다.
SHORT = {
    "trade_count_kr": ("아파트 거래량", "아파트 거래"),
    "trade_count_kr_rone_kr": ("아파트 거래량", "아파트 거래"),
    "jns_price_idx_kr": ("전세가격지수", "전세지수"),
    "apt_price_idx_kr": ("아파트 매매지수", "매매지수"),
    "avg_jeonse_price_kr": ("평균 전세가", "평균 전세가"),
    "semi_jeonse_idx_kr": ("준전세가격지수", "준전세지수"),
    "ppi_us": ("미국 PPI", "미국 PPI"),
    "ff_target": ("미국 기준금리", "미 기준금리"),
    "retail_us": ("미국 소매판매", "미 소매판매"),
    "nfp_us": ("미국 비농업고용", "비농업고용"),
    "existing_home_sales_us": ("기존주택판매", "기존주택판매"),
    "new_home_sales_us": ("신규주택판매", "신규주택판매"),
    "gdp_jp": ("일본 실질GDP", "일본 GDP"),
    "pmi_kr_bsi": ("제조업 BSI", "제조업 BSI"),
    "mortgage_rate_kr": ("주담대 금리", "주담대 금리"),
    "household_debt_kr": ("가계신용 잔액", "가계신용"),
    "sentiment_us": ("미시간 소비심리", "소비심리"),
    "case_shiller_20city_us": ("케이스실러 20", "CS 20대도시"),
    "case_shiller_national_us": ("케이스실러 전국", "CS 전국"),
    "mortgage_15y_us": ("모기지 15년", "모기지 15년"),
    "mortgage_30y_us": ("모기지 30년", "모기지 30년"),
    "housing_starts_us": ("미국 주택착공", "미 주택착공"),
    "building_permits_us": ("미국 건축허가", "미 건축허가"),
    "cpi_jp": ("일본 소비자물가", "일본 CPI"),
    "t10y2y_us": ("장단기 금리차", "장단기차"),
    "tga_us": ("재무부 일반계정", "TGA"),
    "broad_dollar": ("브로드 달러", "브로드 달러"),
    "fx_reserves_kr": ("외환보유액", "외환보유액"),
    "pmi_us": ("미국 제조업 PMI", "미 PMI"), "pmi_jp": ("일본 제조업 PMI", "일본 PMI"),
    "pmi_eu": ("유로 제조업 PMI", "유로 PMI"), "pmi_cn": ("중국 제조업 PMI", "중국 PMI"),
    "pmi_de": ("독일 제조업 PMI", "독일 PMI"), "pmi_kr": ("한국 제조업 PMI", "한국 PMI"),
    "pmi_uk": ("영국 제조업 PMI", "영국 PMI"),
    "gdp_kr": ("GDP 성장률", "GDP 성장"),
    "hy_spread": ("하이일드 스프레드", "HY 스프레드"),
    "claims_us": ("신규 실업수당", "실업수당"),
    "bond10y_jp": ("일본 국채 10년", "일본 10년"),
    "housing_permit_kr": ("주택 인허가", "주택 인허가"),
    "housing_start_kr": ("주택 착공", "주택 착공"),
    "housing_complete_kr": ("주택 준공", "주택 준공"),
    "unsold_total_kr": ("미분양주택", "미분양"),
    "sox": ("필라델피아 반도체", "필라 반도체"),
    "rrp_us": ("역레포 잔액", "역레포"),
    "dxy_idx": ("달러 인덱스", "달러인덱스"),
    "fear_greed": ("공포·탐욕", "공포·탐욕"),
    "goldkrw": ("금 현물 KRX", "금 KRX"),
    "jpykrw": ("JPY100/KRW", "엔/원"),
    "cpi_de": ("독일 소비자물가", "독일 CPI"), "cpi_uk": ("영국 소비자물가", "영국 CPI"),
    "ip_kr": ("한국 산업생산", "한국 산업생산"), "ip_us": ("미국 산업생산", "미국 산업생산"),
    # 한국 지표 중 레지스트리 이름에 나라가 없는 것 — 띠에 미국 지표와 나란히 서면 구분이 안 된다
    "gdp_kr": ("한국 GDP 성장률", "한국 GDP"), "exports_kr": ("한국 수출", "한국 수출"),
    "base_rate_kr": ("한국 기준금리", "한국 기준금리"), "ppi_kr": ("한국 생산자물가", "한국 PPI"),
    "retail_kr": ("한국 소매판매", "한국 소매판매"),
}
# 종목·ETF 이름 줄임표 — 앞에서부터 차례로 바꾼다(예: 「HANARO 코스닥150선물레버리지」→「HANARO 코닥150레버」).
STOCK_TOKENS = [("코스닥", "코닥"), ("선물", ""), ("레버리지", "레버"), ("인버스", "인버"),
                ("액티브", "액티브"), ("커버드콜", "커버드"), ("채권", "채"), ("글로벌", "글로벌"),
                ("미국", "미"), ("TOP", "T"), ("(H)", "")]


# 배율 — 묶음은 원본 값을 그대로 싣고, 화면 값 = value / scale 이며 그 단위가 unit 이다.
# 거시 지표의 배율은 화면 지표 정의(js/app1.js macroIndicators)의 fmt 가 이미 갖고 있다(레지스트리 unit 은
# 나눈 뒤의 단위다 — 수출 100,558,300,000 달러 ÷ 1e8 = 1,006 억달러). 그 fmt 원문에서 읽는다.
# 엔/원은 1엔당 값인데 표기는 100엔당(js/app1.js displayMult 100)이라 0.01 로 나누고 2자리로 보인다.
# 평균 전세가는 천원 단위 → 1e5 로 나눠 억원.
SCALE_BY_ID = {"jpykrw": (0.01, 2, None), "avg_jeonse_price_kr": (1e5, 2, "억원")}


def macro_scales():
    """{dataPath: 나누는 수} — macroIndicators 의 fmt 가 v/1e8·v/1000 꼴로 나누는 행만."""
    with io.open(os.path.join(ROOT, "js", "app1.js"), encoding="utf-8") as f:
        src = f.read()
    start = src.index("const macroIndicators = [")
    body = src[start: src.index("\n];", start)]
    out = {}
    for m in re.finditer(r"dataPath:'([^']+)',\s*fmt:\s*v\s*=>([^\n]*)", body):
        d = re.search(r"\bv\s*/\s*(1e\d+|\d+)\b", m.group(2))
        if d:
            out[m.group(1)] = float(d.group(1))
    return out


def width(s):
    return ol.width(s)


def _strip_paren(s):
    return re.sub(r"\s*\([^)]*\)", "", s).strip()


COUNTRY_KO = {"kr": "한국", "us": "미국", "jp": "일본", "eu": "유로", "cn": "중국", "de": "독일", "uk": "영국"}


def short_names(ind_id, label, country=None):
    """레지스트리 행의 (PC, 모바일) 줄임 이름. 사전 → 후보 중 상한 안에 드는 첫 것.

    country 를 주면(같은 이름이 여러 나라에 있는 거시 지표 — 「실업률」 7개) 나라를 앞에 붙인다.
    괄호 안이 약어면(「소비자물가지수 (CPI)」) 모바일은 「한국 CPI」가 된다."""
    if ind_id in SHORT:
        return SHORT[ind_id]
    bare = _strip_paren(label)
    inner = (re.search(r"\(([^)]*)\)", label) or [None, None])[1]
    c = COUNTRY_KO.get(country) if country else None
    if c:
        cands = [c + " " + label, c + " " + bare] + ([c + " " + inner] if inner else [])
    else:
        cands = [label, bare]
    pick = lambda cap, xs: next((x for x in xs if width(x) <= cap), xs[-1])
    pc = pick(SHORT_PC, cands)
    m = pick(SHORT_M, [pc] + cands[1:])
    return pc, m


def make_shorts(rows):
    """id → (PC, 모바일). 이름이 겹치는 행(나라만 다른 거시 지표)에만 나라를 붙인다."""
    seen = {}
    for r in rows:
        seen[r["label"]] = seen.get(r["label"], 0) + 1
    return {r["id"]: short_names(r["id"], r["label"], r.get("country") if seen[r["label"]] > 1 else None)
            for r in rows}


def _cut(s, cap):
    if width(s) <= cap:
        return s
    while s and width(s + "…") > cap:
        s = s[:-1]
    return s.rstrip() + "…"


def stock_short(name):
    """종목·ETF 이름 → (PC, 모바일). 줄임표로도 넘치면 끝을 … 로 자른다(전체 이름은 name 에 남는다)."""
    s = name or ""
    if width(s) > SHORT_M:
        for a, b in STOCK_TOKENS:
            s = s.replace(a, b)
        s = re.sub(r"\s+", " ", s).strip()
    pc = name if width(name or "") <= SHORT_PC else _cut(s, SHORT_PC)
    return pc, _cut(s, SHORT_M)


# ── 공통 도구 ──────────────────────────────────────────────────────────────
def load(name, default=None):
    path = os.path.join(ROOT, name)
    if not os.path.exists(path):
        return default
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def get(data, path):
    cur = data
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _iso_dt(s):
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=KST)
    except (TypeError, ValueError):
        return None


def _month_yoy(hist, month):
    """{기간 키: 값} 의 'YYYY-MM' 전년비(%). 키 형식(202606 · 2026-06-01)이 달라도 달로 맞춘다. 없으면 None."""
    by = {_norm_date(k)[:7]: _num(v) for k, v in (hist or {}).items()}
    cur, ago = by.get(month), by.get("%d%s" % (int(month[:4]) - 1, month[4:]))
    return round((cur / ago - 1) * 100, 2) if cur is not None and ago else None


def _norm_date(k):
    """'202608' → '2026-08' (R-ONE 월 키). 나머지는 그대로."""
    k = str(k)
    return "%s-%s" % (k[:4], k[4:]) if re.fullmatch(r"\d{6}", k) else k


def is_pct_unit(row, desc=""):
    """금리·성장률처럼 값 자체가 % 인 지표. 레지스트리 unit 이 빈 금리(모기지·연준 목표)는 이름·수집원 설명으로 잡는다."""
    text = "%s %s" % (row.get("label") or "", desc or "")
    return (row.get("asset") == "rate" or str(row.get("unit") or "").startswith("%")
            or any(w in text for w in ("금리", "%", "률")))     # 「상승률(전년동월비 %)」·「실업률」·「성장률」


def _round(x, nd):
    return None if x is None else round(x, nd) + 0.0    # + 0.0 = -0.0 을 0.0 으로


# ── 장 상태 ────────────────────────────────────────────────────────────────
def kr_market(now, cal):
    """한국 정규장 상태 — marketCalendarKr 가 오늘 날짜를 갖고 있을 때만 휴장을 믿는다."""
    today = now.date().isoformat()
    t = (cal or {}).get("today") or {}
    known = t.get("date") == today
    open_day = bool(t.get("open")) if known else now.weekday() < 5
    hm = now.hour * 60 + now.minute
    state = "holiday" if not open_day else "open" if 9 * 60 <= hm < 15 * 60 + 30 else "closed"
    if open_day and hm < 9 * 60:
        nxt = today
    else:
        nxt = ((cal or {}).get("nextBusinessDay") or {}).get("date") if known else None
    if open_day and hm >= 9 * 60:
        session = today
    else:
        session = ((cal or {}).get("previousBusinessDay") or {}).get("date") if known else None
    return {"state": state, "label": {"open": "정규장", "closed": "장마감", "holiday": "휴장"}[state],
            "today": today, "session": session, "nextOpen": (nxt + "T09:00:00+09:00") if nxt else None,
            "calendarKnown": known}


def us_market(now):
    """미국 주식 정규장 — (열림, 휴장일, 마지막 세션 날짜). 뉴욕 현지 시각으로 잰다."""
    ny = now.astimezone(NY)
    d, hm = ny.date(), ny.hour * 60 + ny.minute
    trading = nyse_calendar.is_trading_day(d)
    is_open = trading and 9 * 60 + 30 <= hm < 16 * 60
    session = d if (trading and hm >= 9 * 60 + 30) else nyse_calendar.prev_trading_day(d)
    return is_open, not trading, session.isoformat()


def globex_market(now):
    """24시간 선물·환율 — (열림, 휴장일, 거래일). 뉴욕 18:00 에 다음 거래일이 시작된다."""
    ny = now.astimezone(NY)
    wd, h = ny.weekday(), ny.hour
    weekend = (wd == 4 and h >= 17) or wd == 5 or (wd == 6 and h < 18)
    d = ny.date() + dt.timedelta(days=1 if h >= 18 else 0)
    while d.weekday() >= 5:                                 # 토·일 → 직전 금요일
        d -= dt.timedelta(days=1)
    return not weekend and h != 17, weekend, d.isoformat()


class Clock:
    def __init__(self, now, cal):
        self.now = now
        self.kr = kr_market(now, cal)
        self.us = us_market(now)
        self.globex = globex_market(now)

    def market(self, ind_id):
        """(종류, 열림, 휴장일, 세션 날짜). 세션 날짜를 모르면 None."""
        kind = MARKET_OF.get(ind_id, "globex")
        if kind == "kr":
            return (kind, self.kr["state"] == "open" and self.kr["calendarKnown"],
                    self.kr["state"] == "holiday", self.kr["session"])
        if kind == "us":
            return (kind,) + self.us
        if kind == "globex":
            return (kind,) + self.globex
        return kind, False, self.kr["state"] == "holiday" or self.now.weekday() >= 5, None


def freshness(age_min, is_open, off_day, kept=False):
    """시세 한 칸의 상태 — 분 단위 나이와 장 상태만 본다."""
    if kept:
        return "kept"
    if age_min is None:
        return "missing"
    limit = STALE_OPEN_MIN if is_open else STALE_OFFDAY_MIN if off_day else STALE_CLOSED_MIN
    if age_min > limit:
        return "stale"
    return "live" if is_open and age_min <= LIVE_MIN else "prev"


class Health:
    """data.json.dataHealth.items — 경로의 가장 긴 접두로 찾는다."""

    def __init__(self, data):
        self.items = {i["path"]: i for i in ((data.get("dataHealth") or {}).get("items") or [])}

    def item(self, path):
        path = (path or "").split(":")[0]
        while path:
            if path in self.items:
                return self.items[path]
            path = path.rpartition(".")[0]
        return None

    def state(self, path, leaf=None):
        if isinstance(leaf, dict) and leaf.get("preserved") is True:
            return "kept"
        it = self.item(path)
        return HEALTH_STATE.get((it or {}).get("state"), "prev") if it else "prev"


# ── 지표 한 칸(값·등락·기준시각·상태·시계열) ─────────────────────────────────
class Quotes:
    def __init__(self, data, rows, clock, toss=None):
        self.data, self.clock, self.health = data, clock, Health(data)
        self.rows = {r["id"]: r for r in rows}
        self.shorts = make_shorts(rows)
        self.scales = macro_scales()
        self.updated = _iso_dt(data.get("lastUpdated"))
        self.toss = toss or {}
        self._cache = {}

    def _spot_time(self, ind_id, value):
        """시세 값의 시각 — KR 지수가 토스 PC 스냅샷 값이면 그 스냅샷 시각, 아니면 data.json 수집 시각."""
        if ind_id in ("kospi", "kosdaq"):
            snap = (self.toss.get("indices") or {}).get(ind_id.upper()) or {}
            if snap.get("price") == value and _iso_dt(self.toss.get("generatedAt")):
                return _iso_dt(self.toss["generatedAt"])
        return self.updated

    def series(self, ind_id):
        """[[날짜, 값], …] 오래된 순. 없으면 []."""
        q = self.get(ind_id)
        return q["_series"] if q else []

    def get(self, ind_id):
        if ind_id not in self._cache:
            self._cache[ind_id] = self._build(ind_id)
        return self._cache[ind_id]

    def _build(self, ind_id):
        row = self.rows.get(ind_id)
        if not row:
            return None
        path = row.get("data") or ""
        out = {"id": ind_id, "label": row["label"]}
        out["short"], out["shortM"] = self.shorts[ind_id]
        if row.get("unit"):
            out["unit"] = row["unit"]
        out["decimals"] = row.get("decimals", 2)
        nd = max(out["decimals"], 2)          # 등락은 2자리 이상 — 공포탐욕(0자리) 30.8→30.7 이 -0.0 이 되지 않게
        sc = self.scales.get(row.get("data"))
        if ind_id in SCALE_BY_ID:
            sc, out["decimals"], unit = SCALE_BY_ID[ind_id]
            if unit:
                out["unit"] = unit
        if sc:
            out["scale"] = sc
        head = path.split(".")[0]
        value = pct = change = as_of = None
        series = []
        if head in ("indices", "fx", "commodities"):
            leaf = get(self.data, path) or {}
            value = _num(leaf.get("price", leaf.get("rate")))
            pct = _num(leaf.get("change"))
            if value is not None and pct is not None and pct > -100:
                change = _round(value - value / (1 + pct / 100), nd)
            series = [[p.get("date"), p.get("close")] for p in (get(self.data, row.get("series") or "") or [])
                      if isinstance(p, dict) and _num(p.get("close")) is not None]
            kept = leaf.get("stale") is True or leaf.get("preserved") is True
            kind, is_open, off_day, session = self.clock.market(ind_id)
            hit = self.health.item(row.get("series"))
            if kept:
                out["keptSince"] = leaf.get("staleSince") or leaf.get("preservedAt")
            if hit and hit.get("cadence") in ("weekly", "monthly", "quarterly", "annual"):
                # 저빈도(두바이유 월간) — 분 단위로 재면 '실시간'이라고 거짓말하게 된다
                as_of = series[-1][0] if series else None
                state = self.health.state(row.get("series"), leaf)
            elif kind == "daily":
                # KRX 금 = 전일 확정치 일봉. 기준일(소스 as_of)로만 잰다. 기준일이 없던 옛 data.json 은 수집 나이로.
                as_of = leaf.get("as_of")
                if kept or value is None:
                    state = "kept" if kept else "missing"
                elif as_of:
                    state = "prev" if (self.clock.now.date() - dt.date.fromisoformat(as_of[:10])).days <= 4 else "stale"
                else:
                    age = (self.clock.now - self.updated).total_seconds() / 60 if self.updated else None
                    state = freshness(age, False, off_day)
            else:
                t = self._spot_time(ind_id, value)
                basis = t
                # 장이 닫혔고 값이 그 세션 마감 뒤에 확인된 것이면 나이는 수집 시각으로 잰다 — 토스 스냅샷은
                # 값이 그대로면 시각을 올리지 않아 저녁·주말 내내 '지연'으로 오판했다(검토 2026-10-01).
                if (kind == "kr" and not is_open and t and self.updated and session
                        and t >= dt.datetime.fromisoformat(session + "T15:30:00+09:00")):
                    basis = max(t, self.updated)
                age = max(0.0, (self.clock.now - basis).total_seconds() / 60) if (basis and value is not None) else None
                state = freshness(age, is_open, off_day, kept)
                if state == "live":
                    as_of = t.isoformat(timespec="seconds")
                    # 묶음은 만든 순간의 판정이다 — 화면은 이 시각이 지나면 '실시간'을 내려야 한다
                    out["liveUntil"] = (t + dt.timedelta(minutes=LIVE_MIN)).isoformat(timespec="seconds")
                elif kept:
                    as_of = None                               # 되살린 값의 원래 시각은 모른다(keptSince 만 안다)
                elif kind == "kr" and t is not self.updated:
                    as_of = t.isoformat(timespec="seconds")    # 토스 스냅샷 시각 = 소스의 시각
                else:
                    as_of = session or (series[-1][0] if series else None)   # 장이 닫혔으면 마지막 세션 날짜
                # 7일·큰 차트의 끝점 = 지금 값. history 의 그날 점이 직전 종가 사본으로 남는 일이 있다
                # (2026-10-01 KOSPI: history 10-01 6838.04 = 9/30 종가, 현재가 6961.32). 선물(globex)은
                # 거래일 경계가 소스마다 달라 같은 날짜 점만 바꾸고 새 점은 붙이지 않는다.
                if value is not None and session and not kept and series and kind in ("kr", "us", "globex"):
                    if series[-1][0] == session:
                        series[-1] = [session, value]
                    elif series[-1][0] < session and kind != "globex":
                        series.append([session, value])
        elif head == "yieldCurve":
            cc, _, tenor = path[len("yieldCurve."):].partition(":")
            s = next((x for x in (get(self.data, "yieldCurve." + cc + ".series") or [])
                      if x.get("tenor") == tenor), None) or {}
            series = [[p.get("date"), p.get("value")] for p in (s.get("data") or []) if _num(p.get("value")) is not None]
            if series:
                value, as_of = series[-1][1], series[-1][0]
                if len(series) > 1:
                    change = _round(value - series[-2][1], nd)
                    pct = _round((value / series[-2][1] - 1) * 100, 2) if series[-2][1] else None
            state = self.health.state(path) if value is not None else "missing"
        elif head == "history":                                      # 가상자산 — 일봉만 있다
            series = [[p.get("date"), p.get("close")] for p in (get(self.data, path) or []) if _num(p.get("close")) is not None]
            if series:
                value, as_of = series[-1][1], series[-1][0]
                if len(series) > 1:
                    change = _round(value - series[-2][1], nd)
                    pct = _round((value / series[-2][1] - 1) * 100, 2) if series[-2][1] else None
            state = self.health.state(path) if value is not None else "missing"
            if state == "prev":
                # 24시간 거래라 장 마감·휴장이 없다(globex 의 17시 휴식도 없다) — 닫힌 장 기준 '직전 종가' 가 아니라 분 단위로
                # 잰다. 일봉 한 칸 = UTC 하루: 오늘(UTC) 봉이면 값의 시각 = 수집 시각, 지난 봉이면 그날 24:00 UTC.
                # 판정표가 이미 stale·kept 로 본 값은 그대로 둔다(수집 실패를 나이로 덮지 않는다).
                t = dt.datetime.fromisoformat(as_of[:10]).replace(tzinfo=dt.timezone.utc) + dt.timedelta(days=1)
                t = min(t, self.updated) if self.updated else t
                state = freshness(max(0.0, (self.clock.now - t).total_seconds() / 60), True, False)
                if state == "live":
                    as_of = t.isoformat(timespec="seconds")
                    out["liveUntil"] = (t + dt.timedelta(minutes=LIVE_MIN)).isoformat(timespec="seconds")
        else:                                                        # 잎: sentiment · economicIndicators · realestate
            leaf = get(self.data, path)
            leaf = leaf if isinstance(leaf, dict) else {}
            value = _num(leaf.get("value"))
            as_of = leaf.get("as_of") or leaf.get("period") or leaf.get("asOf")
            hist = leaf.get("history")
            if isinstance(hist, dict):
                series = sorted(([k, v] for k, v in hist.items() if _num(v) is not None), key=lambda p: str(p[0]))
            prev = _num(leaf.get("prev"))
            if prev is None and as_of is not None:
                # 지금 값의 점 = as_of 이하 마지막 점. 그 점 값이 지금 값과 같으면 그게 '오늘 점'이고 직전 점은 그 앞이다 —
                # MOVE 는 as_of 가 수집일(10/1)이고 이력 끝 9/30 이 같은 값이라 직전을 9/30 으로 잡아 change 0 이 됐다.
                upto = [p for p in series if str(p[0]) <= str(as_of)]
                if upto and upto[-1][1] == value:
                    upto = upto[:-1]
                prev = upto[-1][1] if upto else None
            if value is not None and prev is not None:
                change = _round(value - prev, nd)
            pct = _num(leaf.get("chg")) if head == "realestate" else _num(leaf.get("change")) if head == "sentiment" else None
            if pct is None and value is not None and prev:
                pct = _round((value / prev - 1) * 100, 2)
            elif pct is not None and change is not None and prev:
                # 소스 등락률과 우리 등락이 서로 다른 말을 하면 둘 다 믿지 않는다(지어내지 않기)
                if abs((value / prev - 1) * 100 - pct) > 0.1:
                    change = pct = None
            # 호·건·명 단위(미분양·착공·인허가·준공·거래량·실업수당) = 정수 — 소수 자리를 쓰지 않는다
            desc = leaf.get("desc") or ""
            if (leaf.get("unit") in COUNT_UNITS or row.get("unit") in COUNT_UNITS
                    or re.search(r"\((?:천 |백만 )?(?:호|건)[,)]|\((?:호|건)\)|동\(호\)수", desc)):
                out["decimals"] = 0
                if not out.get("unit") and leaf.get("unit") in COUNT_UNITS:
                    out["unit"] = leaf["unit"]
            raw_asof = as_of
            series = [[_norm_date(k), v] for k, v in series]
            as_of = _norm_date(as_of) if as_of is not None else None
            # 월간 지표는 월로 적는다(「2026-08-01」은 8월 1일이 아니라 8월 값이다). 분기는 「2026-Q2」 —
            # 날짜로 두면 화면이 「전일 4/1」이라 적는다(2026-10-02 실측, GDP 12종).
            if as_of and re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
                cad = data_sla.infer_cadence(leaf, raw_asof)
                if cad == "monthly":
                    as_of = as_of[:7]
                elif cad == "quarterly":
                    as_of = "%s-Q%d" % (as_of[:4], (int(as_of[5:7]) - 1) // 3 + 1)
                elif cad == "annual":          # 연간(중국 GDP) 은 연도만 — 「전일 1/1」이 아니라 「2025년」
                    as_of = as_of[:4]
            elif as_of and re.fullmatch(r"\d{4}Q[1-4]", as_of):   # 「2026Q2」(ECOS 분기 키) 도 같은 꼴로
                as_of = as_of[:4] + "-" + as_of[4:]
            state = self.health.state(path, leaf) if value is not None else "missing"
            if (self.health.item(path) or {}).get("state") == "suspect":
                out["suspect"] = True
        if value is None:
            state = "missing"
        # 단위가 % 인 지표(금리·성장률·실업률)는 상대 등락률을 싣지 않는다 — GDP 1.8→0.6 이 「-66.67%」,
        # 모기지 6.95→7.03 이 「+1.15%」로 읽힌다(소스가 준 chg 도 마찬가지). 등락은 change(%p)가 맡는다.
        node = get(self.data, path.split(":")[0])
        if is_pct_unit(row, node.get("desc") if isinstance(node, dict) else ""):
            pct = None
        out.update({"value": value, "change": change, "changePct": pct, "asOf": as_of, "state": state})
        out["_series"] = series
        return out

    def item(self, ind_id, spark=7, tail=None):
        """화면에 내보낼 한 칸 — spark 개 작은 차트 값, tail 개 시계열([날짜, 값])."""
        q = self.get(ind_id)
        if not q:
            return {"id": ind_id, "label": ind_id, "value": None, "state": "missing"}
        out = {k: v for k, v in q.items() if not k.startswith("_")}
        if spark:
            out["spark"] = [p[1] for p in q["_series"][-spark:]] or None
        if tail:
            out["series"] = q["_series"][-tail:]
        return out


def since(series, days, today):
    """[[날짜, 값]] 중 today - days 이후 점."""
    cut = (today - dt.timedelta(days=days)).isoformat()
    return [p for p in series if str(p[0]) >= cut]


# ── 화면별 조각 ────────────────────────────────────────────────────────────
def is_etf(r):
    if r.get("type"):
        return r["type"] == "ETF"
    return str(r.get("name") or "").upper().startswith(tuple(p.upper() for p in ETF_PREFIX))


def stock_rows(rows, amount=False, market=None):
    """종목 목록. market 을 주면 그 시장 행만 — 원천 kospiGainers 에 KOSDAQ 종목이 섞여 온다(2026-10-01 10개 중 9개)."""
    out = []
    for r in rows or []:
        if market and r.get("market") != market:
            continue
        pc, m = stock_short(r.get("name"))
        it = {"name": r.get("name"), "short": pc, "shortM": m, "code": r.get("code"),
              "market": r.get("market"), "price": _num(r.get("price")), "chgPct": _num(r.get("chg")),
              "isEtf": is_etf(r)}
        it["amount" if amount else "volume"] = _num(r.get("amount" if amount else "vol"))
        for src, dst in (("mktcap", "marketCap"), ("high", "high"), ("low", "low")):   # KRX 순위 행에만 있다
            if r.get(src) is not None:
                it[dst] = _num(r.get(src))
        if r.get("preserved"):
            it["kept"] = True
        if r.get("suspect"):                       # 수집기가 단 이상치 표식(기준가 변경 의심) — 지우지 않고 화면·알림이 가른다
            it["suspect"] = True
        out.append(it)
    return out


def block_state(health, path, node):
    if not node:
        return "missing"
    return health.state(path, node if isinstance(node, dict) else None)


def krx_rank_view(health, rk, key):
    """KRX 순위(rankingsKr.<key> = {as_of, kospi, kosdaq[, count]}) → 화면 칸. 시장별 20행, 52주는 총수(count) 포함."""
    node = rk.get(key) if isinstance(rk.get(key), dict) else None
    v = {"asOf": (node or {}).get("as_of"), "state": block_state(health, "rankingsKr." + key, node),
         "kospi": stock_rows((node or {}).get("kospi")), "kosdaq": stock_rows((node or {}).get("kosdaq"))}
    if (node or {}).get("count"):
        v["count"] = node["count"]
    return v


def corp_events(data, since=None, until=None):
    """배당·실적 일정(data.json.corpEvents.items) — since ≤ 날짜 < until. 최신순 그대로."""
    out = []
    for e in ((data.get("corpEvents") or {}).get("items") or []):
        d = e.get("date") or ""
        if (since and d < since) or (until and d >= until):
            continue
        it = {k: e.get(k) for k in ("date", "code", "name", "kind", "title", "detail", "rcpNo")}
        if e.get("preserved"):
            it["kept"] = True
        out.append(it)
    return out


def schedule_with_corp(data, now, days=7):
    """홈 일정 = 경제 일정(지나지 않은 것) + 종목 일정(오늘~days 일, kind 로 갈린다). 날짜·시각 순.
    종목 일정 날짜는 공시 접수일이라 대개 지난 날이다 — 오늘 낸 공시만 여기 걸리고, 전체는 국내 묶음 corpEvents 에 있다."""
    today = now.date()
    corp = [{"date": e["date"], "time": None, "cc": "KR", "name": "%s %s" % (e.get("name") or e.get("code"), e.get("title") or ""),
             "stars": None, "prev": None, "fore": None, "act": None, "approx": False, "kind": e.get("kind"),
             "code": e.get("code")}
            for e in corp_events(data, today.isoformat(), (today + dt.timedelta(days=days)).isoformat())]
    return sorted(calendar_events(data, now, days=days) + corp, key=lambda e: (e["date"], e["time"] or ""))


def event_name(s):
    """일정 이름 끝의 영어 풀이 괄호를 뗀다 — 「미국 주택착공 (Housing Starts)」 → 「미국 주택착공」.
    소문자가 섞인 영어만 뗀다. 대문자 약어(「(NFP)」·「(FOMC)」)·우리말 괄호(「(전월비)」)·중간 괄호는 남긴다."""
    m = re.search(r"\s*\(([A-Za-z][A-Za-z0-9 .,&'/-]*)\)$", s) if isinstance(s, str) else None
    return s[:m.start()] if m and m.start() and m.group(1) != m.group(1).upper() else s


def calendar_events(data, now, days=None, cc=None):
    """경제 일정 — 아직 지나지 않은 것부터(days 가 있으면 그 날 수 안)."""
    today = now.date().isoformat()
    hm = now.strftime("%H:%M")
    end = (now.date() + dt.timedelta(days=days)).isoformat() if days else None
    out = []
    for e in ((data.get("economicCalendar") or {}).get("events") or []):
        iso = e.get("iso") or ""
        time = (e.get("dt") or "").split(" ")[-1] if " " in (e.get("dt") or "") else None
        if iso < today or (iso == today and time and time < hm) or (end and iso >= end):
            continue
        if cc and e.get("cc") != cc:
            continue
        out.append({"date": iso, "time": time, "cc": e.get("cc"), "name": event_name(e.get("name")), "stars": e.get("stars"),
                    "prev": e.get("prev") or None, "fore": e.get("fore") or None, "act": e.get("act") or None,
                    "approx": bool(e.get("timeApprox"))})
    return sorted(out, key=lambda e: (e["date"], e["time"] or ""))


def all_events(data):
    return [{"date": e.get("iso"), "time": (e.get("dt") or "").split(" ")[-1] if " " in (e.get("dt") or "") else None,
             "cc": e.get("cc"), "name": event_name(e.get("name")), "stars": e.get("stars"), "prev": e.get("prev") or None,
             "fore": e.get("fore") or None, "act": e.get("act") or None, "beat": e.get("beat")}
            for e in ((data.get("economicCalendar") or {}).get("events") or [])]


def investor_rows(data):
    return [r for r in ((data.get("investorTrading") or {}).get("daily") or []) if isinstance(r, dict) and r.get("date")]


def investors_block(data, health, n):
    rows = investor_rows(data)
    it = data.get("investorTrading") or {}
    last = rows[-1] if rows else None
    return {"market": (it.get("markets") or [None])[0], "unit": it.get("unit"), "source": it.get("source"),
            "asOf": last["date"] if last else None, "state": block_state(health, "investorTrading", it),
            "today": {k: last.get(k) for k in ("date", "foreign", "inst", "retail")} if last else None,
            "rows": [[r["date"], r.get("foreign"), r.get("inst"), r.get("retail")] for r in rows[-n:]],
            "columns": ["date", "foreign", "inst", "retail"]}


def clean_title(s):
    """뉴스 제목 — HTML 엔터티(&quot; 등)를 풀고 공백을 한 칸으로."""
    return re.sub(r"\s+", " ", html.unescape(str(s or ""))).strip()


def _pub_time(it):
    """기사 시각(pubDate, RFC 822) → aware datetime. 못 읽으면 None."""
    try:
        t = email.utils.parsedate_to_datetime(it.get("pubDate"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _web_url(u):
    """http/https 주소만 그대로, 나머지(javascript: · data: · 깨진 글)는 None — RSS <link> 원문이 화면 href 로 간다."""
    try:
        return u if isinstance(u, str) and urllib.parse.urlsplit(u.strip()).scheme.lower() in ("http", "https") else None
    except ValueError:
        return None


def news_top(data, n=5):
    seen, out = set(), []
    for topic, items in (data.get("news") or {}).items():
        if not isinstance(items, list):
            continue
        for it in items:
            url = _web_url(it.get("url")) if isinstance(it, dict) else None
            if not url or url in seen:
                continue
            seen.add(url)
            t = _pub_time(it)
            out.append((t.timestamp() if t else 0,
                        {"title": clean_title(it.get("title")), "url": url, "date": it.get("isoDate"), "topic": topic}))
    return [x[1] for x in sorted(out, key=lambda x: -x[0])[:n]]


def news_bundle(data, health=None):
    """bundles/news.json — data.json.news 16주제(lastFetched 제외)를 주제마다 최신순 NEWS_MAX 건.
    지표 상세는 registry 행의 news, 자산군 화면은 market-*.json 의 newsTopic 으로 주제를 찾는다."""
    news = data.get("news") or {}
    health = health or Health(data)
    topics = {}
    for topic, items in news.items():
        if not isinstance(items, list):
            continue
        seen, rows = set(), []
        for it in items:
            url = _web_url(it.get("url")) if isinstance(it, dict) else None
            if not url or url in seen or not clean_title(it.get("title")):
                continue
            seen.add(url)
            t = _pub_time(it)
            host = (urllib.parse.urlsplit(url).hostname or "").removeprefix("www.")
            rows.append((t.timestamp() if t else 0, {"title": clean_title(it["title"]), "source": host or None, "url": url,
                                                     "at": t.isoformat() if t else it.get("isoDate")}))
        topics[topic] = [r for _, r in sorted(rows, key=lambda x: -x[0])[:NEWS_MAX]]
    return {"asOf": news.get("lastFetched"), "state": block_state(health, "news", topics), "topics": topics}


def kst_stamp(s):
    """'2026-10-07 17:13 KST'(ai_briefing.py 의 generatedAt 꼴) → ISO. 다른 꼴이면 None."""
    try:
        return dt.datetime.strptime(str(s), "%Y-%m-%d %H:%M KST").replace(tzinfo=KST).isoformat()
    except ValueError:
        return None


def week_change(q):
    """1주 전 대비 차이 — asOf 7일 전 이하의 마지막 점과 비교. 그 점이 asOf 14일 전보다 오래면(이력 구멍) null."""
    try:
        day = dt.date.fromisoformat(str(q.get("asOf"))[:10])
    except ValueError:
        return None
    pts = [p for p in q.get("_series") or [] if str(p[0])[:10] <= (day - dt.timedelta(days=7)).isoformat()]
    if q.get("value") is None or not pts or str(pts[-1][0])[:10] < (day - dt.timedelta(days=14)).isoformat():
        return None
    return _round(q["value"] - pts[-1][1], max(q.get("decimals", 2), 2))


def mood_item(Q, i):
    """홈 「분위기」 한 칸 — 값·기준시각·상태는 다른 칸과 같은 Quotes 판정, 등락은 1주 전 대비."""
    q = Q.get(i) or {}
    return {"id": i, "label": q.get("label", i), "short": q.get("short"), "shortM": q.get("shortM"), "unit": q.get("unit"),
            "value": q.get("value"), "decimals": q.get("decimals", 2), "change": week_change(q),
            "asOf": q.get("asOf"), "state": q.get("state", "missing")}


def flow_last(s):
    """종목 수급 세 칸(단위 주) — 기록의 마지막 날 값 하나씩. 공매도(shortVol — short 는 줄임 이름 칸) = 그날 공매도 거래량,
    대차 = 그날 대차잔고, 프로그램 = 그날 차익 + 비차익 순매수(둘 다 있을 때만). 기록이 없거나 모양이 다르면 null(ETF 는 대개 비어 온다)."""
    def last(k):
        v = s.get(k)
        x = v[-1] if isinstance(v, list) and v else {}
        return x if isinstance(x, dict) else {}
    sh, ln, pg = last("short"), last("lending"), last("program")
    arb, non = _num(pg.get("arb")), _num(pg.get("nonArb"))
    return {"shortVol": _num(sh.get("volume")), "lending": _num(ln.get("bal")),
            "program": arb + non if arb is not None and non is not None else None,
            "flowDates": {"shortVol": sh.get("date"), "lending": ln.get("date"), "program": pg.get("date")}}


# ── 렌즈 ──────────────────────────────────────────────────────────────────
TRIGGER_LABEL = {"crossed": "돌파", "near": "주시", "below": "정상", "unknown": "자료 없음"}  # js/app7.js 필터와 같은 말


def _hot_chains(mer):
    return sorted((c for c in (mer.get("chains") or []) if c.get("hotStep")), key=lambda c: -(c.get("n") or 0))


def triggers(mer):
    """렌즈 트리거 줄 — 상태는 여기서 한 번 정한다(돌파 수·breach·화면 집계가 전부 이 목록을 센다).
    현재값과 임계(단위·범위 게이트를 넘은 것)가 둘 다 숫자일 때만 원천 상태를 믿고, 하나라도 없으면
    원천이 무엇이라 적었든 unknown(자료 없음)이다."""
    out = []
    for i in mer.get("indicators") or []:
        near = i.get("nearest") or {}
        cur = i.get("current") or {}
        st = i.get("state")
        if _num(cur.get("value")) is None or _num(near.get("level")) is None or st not in TRIGGER_LABEL:
            st = "unknown"
        out.append({"id": i.get("id"), "label": i.get("label"), "layer": i.get("layer"), "unit": i.get("unit"),
                    "state": st, "stateLabel": TRIGGER_LABEL[st],
                    "value": cur.get("value"), "asOf": cur.get("asOf"), "level": near.get("level"),
                    "distancePct": _round(_num(near.get("distancePct")), 2)})
    return out


def watch_list(mer):
    """지금 볼 것 — 사슬 발동 지표 먼저, 다음은 임계에 가까운 순(js/app7.js _merWatchList 와 같은 규칙)."""
    hot = {c["hotStep"] for c in _hot_chains(mer)}
    xs = [t for t in triggers(mer) if t["level"] is not None and t["value"] is not None and t["state"] in ("crossed", "near")]
    return sorted(xs, key=lambda t: (0 if t["id"] in hot else 1, abs(t["distancePct"] or 0)))


def chain_view(c):
    return {k: c.get(k) for k in ("id", "label", "note", "n", "lastDate", "hotStep")} | {
        "steps": [{"id": s.get("id"), "label": s.get("label")} for s in (c.get("steps") or [])],
        "logNos": (c.get("logNos") or [])[:10]}        # 원문 링크 목록용 — 원천 순서(최근 글 먼저) 그대로 최대 10


def lens_today(mer):
    lens = mer.get("lens") or {}
    hist = lens.get("history30d") or []
    score, first = _num(lens.get("score")), (_num(hist[0].get("score")) if hist else None)
    wl = watch_list(mer)
    hot = _hot_chains(mer)
    return {"score": score, "delta30d": _round(score - first, 1) if score is not None and first is not None else None,
            "asOf": lens.get("asOf"), "breach": [t for t in wl if t["state"] == "crossed"][:2],
            "watch": [t for t in wl if t["state"] == "near"][:2],
            "chain": chain_view(hot[0]) if hot else None, "hotChains": len(hot)}


# 렌즈 노드 줄임 이름 — 괄호·「·」 앞만 남겨도 모바일 상한(SHORT_M)을 넘는 것만 사람이 여기 정한다.
LENS_SHORT = {"nps_flow": "연금 리밸런싱"}   # 「국민연금 리밸런싱」 8.5칸
QUOTE_MAX = 80      # 인용 한 줄 상한(글자 수) — mer_extract.QUOTE_MAX 와 같다(원천 인용이 이미 80자 이하)
QUOTES_PER_POST = 3  # 한 관계·사슬 안에서 같은 글의 인용은 이만큼까지


def node_short(node):
    if node.get("id") in LENS_SHORT:
        return LENS_SHORT[node["id"]]
    return re.split(r"[(·]", node.get("label") or "")[0].strip() or node.get("label")


def post_quotes(impacts, titles):
    """impacts 의 인용 → [{logNo, title, date, text}] 최신순, 같은 글은 QUOTES_PER_POST 줄까지.
    인용은 mer_extract 가 원문 실재를 검증한 것만 mer_signals.json 에 남는다 — 여기서 새로 만들지 않는다."""
    qs = sorted((q for im in impacts for q in (im.get("quotes") or []) if q.get("q")),
                key=lambda q: (q.get("date") or "", q.get("logNo") or ""), reverse=True)
    seen, per, out = set(), {}, []
    for q in qs:
        no = q.get("logNo")
        if (no, q["q"]) in seen or per.get(no, 0) >= QUOTES_PER_POST:
            continue
        seen.add((no, q["q"]))
        per[no] = per.get(no, 0) + 1
        text = q["q"] if len(q["q"]) <= QUOTE_MAX else q["q"][:QUOTE_MAX - 1].rstrip() + "…"
        out.append({"logNo": no, "title": titles.get(no), "date": q.get("date"), "text": text})
    return out


def edges_with_quote(mer, titles=None):
    """간선마다 원천 impacts 의 인용(post_quotes). (출발, 도착, 방향)으로 짝짓고 같은 짝이 여럿이면 순서대로."""
    pool = {}
    for im in mer.get("impacts") or []:
        pool.setdefault((im.get("from"), im.get("to"), im.get("dir")), []).append(im)
    out = []
    for e in (mer.get("graph") or {}).get("edges") or []:
        same = pool.get((e.get("from"), e.get("to"), e.get("dir"))) or []
        out.append(dict(e, quotes=post_quotes([same.pop(0)] if same else [], titles or {})))
    return out


def chain_quotes(mer, c, titles):
    """사슬의 인용 — 양 끝이 모두 그 사슬 단계인 관계(impacts)의 인용. 사슬 logNos(추출 chain 이 겹친 글)와
    글이 다를 수 있다 — 단계 사이 관계를 말한 글의 인용이라서다."""
    ids = {s.get("id") for s in c.get("steps") or []}
    return post_quotes([im for im in mer.get("impacts") or [] if im.get("from") in ids and im.get("to") in ids], titles)


def build_lens(mer):
    g = mer.get("graph") or {}
    posts = sorted((p for p in (mer.get("posts") or []) if p.get("date")), key=lambda p: (p["date"], p.get("logNo") or ""))
    counts = {}
    for t in triggers(mer):
        counts[t["state"]] = counts.get(t["state"], 0) + 1
    by_no = {p.get("logNo"): p for p in mer.get("posts") or []}
    titles = {no: p.get("title") for no, p in by_no.items()}
    edges = edges_with_quote(mer, titles)
    chains = [chain_view(c) | {"quotes": chain_quotes(mer, c, titles)} for c in (mer.get("chains") or [])]
    # 사슬·관계가 가리키는 글의 제목·날짜 — logNo 마다 한 번. posts(최근 3편)에 없는 글이 대부분이라 사슬 원문 링크가
    # 「원문 열기」로만 읽혔다(2026-10-09 점검). 원천 = mer_signals.posts(779편, 사슬·관계 글 전부를 덮는다 — merblog.json 은 365일 창).
    nos = dict.fromkeys(no for x in edges + chains for no in x.get("logNos") or [])
    return {"asOf": mer.get("asOf"), "window": mer.get("window"), "coverage": mer.get("coverage"),
            "nodes": [dict(n, short=node_short(n)) for n in (g.get("nodes") or [])],
            "edges": edges, "chains": chains,
            "regime": mer.get("regime"), "lens": mer.get("lens"), "counters": mer.get("counters") or [],
            "triggers": triggers(mer), "triggerCounts": counts, "today": lens_today(mer),
            "posts": [{"logNo": p.get("logNo"), "date": p["date"], "title": p.get("title")} for p in posts[-3:][::-1]],
            "postMeta": {no: {"title": by_no[no].get("title"), "date": by_no[no].get("date")} for no in nos if no in by_no}}


# ── 금 김치프리미엄 ─────────────────────────────────────────────────────────
TROY_OZ_G = 31.1035


def gold_premium(krw_per_g, usd_per_oz, usdkrw):
    """국내 금 원/g ÷ (국제 금 $/oz × 달러원 ÷ 31.1035) − 1 → %. 셋 중 하나라도 없으면 None."""
    if not all(isinstance(x, (int, float)) and x > 0 for x in (krw_per_g, usd_per_oz, usdkrw)):
        return None
    return round((krw_per_g / (usd_per_oz * usdkrw / TROY_OZ_G) - 1) * 100, 2)


# ── 묶음 조립 ──────────────────────────────────────────────────────────────
def build_all(data, mer, now, toss=None):
    rows, _datasets, _ = bi.build(data, mer)
    clock = Clock(now, data.get("marketCalendarKr"))
    Q = Quotes(data, rows, clock, toss)
    H = Q.health
    today = now.date()
    kr = clock.kr
    b = {}

    # registry
    reg = []
    for r in sorted(rows, key=lambda r: (bi.ASSET_ORDER.index(r["asset"]), r["tier"], r["id"])):
        pc, m = Q.shorts[r["id"]]
        it = {"id": r["id"], "label": r["label"], "short": pc, "shortM": m}
        for k in ("unit", "decimals", "asset", "topic", "country", "tier"):
            if r.get(k) is not None:
                it[k] = r[k]
        q = Q.get(r["id"]) or {}
        if q.get("scale"):
            it["scale"] = q["scale"]
        for k in ("decimals", "unit"):          # 묶음이 정한 표기(배율·호/건 정수)가 레지스트리 값을 이긴다 — 두 곳이 갈리지 않게
            if q.get(k) is not None:
                it[k] = q[k]
        it["dataPath"] = r.get("data")
        if r.get("series"):
            it["seriesPath"] = r["series"]
        it["canonical"] = "/i/" + r["id"]
        it["news"] = r.get("news")              # news.json topics 의 키(build_indicators.news_of) — 없으면 null
        reg.append(it)
    b["registry"] = {"count": len(reg), "rows": reg}

    # 이유 한 줄의 재료 — 그 장(세션)의 것만
    sm = data.get("sectorMoves") or {}
    inv = investor_rows(data)
    session = kr["session"]
    usd = Q.get("usdkrw") or {}
    nxt = {}
    for e in calendar_events(data, now):
        nxt.setdefault(e["cc"], {"iso": e["date"], "name": e["name"]})
        nxt.setdefault("*", {"iso": e["date"], "name": e["name"]})
    ctx = {"sectors": sm.get("items") if sm.get("as_of") == session else None,
           "flow": inv[-1] if inv and inv[-1]["date"] == session else None,
           "fxPct": usd.get("changePct") if usd.get("state") != "kept" else None,
           "fxPctSession": usd.get("changePct") if usd.get("state") != "kept" and kr["state"] == "open" else None,
           "next": nxt, "today": today.isoformat(), "tomorrow": (today + dt.timedelta(days=1)).isoformat(),
           "kospiPct": (Q.get("kospi") or {}).get("changePct")}

    # home
    strip = []
    for i in HOME_STRIP:
        it = Q.item(i)
        r = ol.reason(i, ctx)
        it["reason"], it["reasonShort"] = r["pc"], r["mobile"]
        strip.append(it)
    ks = Q.series("kospi")
    ai = data.get("aiBriefing") or {}
    ra = data.get("rankingsKr") or {}
    b["home"] = {
        "asOf": data.get("lastUpdated"), "market": kr, "strip": strip,
        "todayLine": ol.today_line(ai.get("lines") if ai.get("date") == today.isoformat() else None, ctx),
        "kospiChart": {"1d": None, "1w": since(ks, 7, today), "3m": since(ks, 92, today), "1y": since(ks, 365, today),
                       "missing": {"1d": "장중 분봉을 수집하지 않는다"}},
        "sectors": {"asOf": sm.get("as_of"), "state": block_state(H, "sectorMoves", sm),
                    "items": [{"name": s.get("name"), "close": s.get("close"), "chgPct": s.get("chg_pct")} for s in (sm.get("items") or [])]},
        "topAmount": {"asOf": ra.get("as_of"), "state": block_state(H, "rankingsKr.tradingAmount", ra.get("tradingAmount")),
                      "items": stock_rows((ra.get("tradingAmount") or [])[:20], amount=True)},
        "investors": investors_block(data, H, 20),
        "schedule": schedule_with_corp(data, now, days=7),
        "news": news_top(data, 5),
        "lens": lens_today(mer),
        # AI 3줄 — 날짜가 오늘이 아니어도 싣는다(asOf 로 화면이 가른다). todayLine 은 오늘 자 첫 문장만 쓴다.
        "brief": {"asOf": kst_stamp(ai.get("generatedAt")) or ai.get("date"), "lines": (ai.get("lines") or [])[:3],
                  "source": ai.get("source")},
        "mood": [mood_item(Q, i) for i in MOOD],
    }

    # 묶음 머리에 수집 시각을 두지 않는다 — 거시·부동산처럼 하루 한 번 바뀌는 묶음까지 매 런 파일이 바뀐다.
    # 수집 시각은 meta.dataUpdated 하나, 칸마다의 기준시각은 asOf.
    derived = {}
    issues = []          # 묶음이 찾은 원본 이상 → meta.health.issues
    checks = []          # 범위를 넘었지만 다른 원천과 맞아 실은 값 → meta.health.checks(이상 목록엔 넣지 않는다)

    def pick(i):
        if i in derived:
            return derived[i]
        return Q.item(i) if i in Q.rows else {"id": i, "label": i, "value": None, "asOf": None, "state": "missing"}

    def market(name, views):
        return {"market": kr, "strip": [pick(i) for i in STRIPS[name]], "views": views, "newsTopic": MARKET_NEWS[name]}

    # ── 파생 칸(레지스트리 밖, data.json 경로에서 직접) ───────────────────────────
    def dv(i, label, short, shortM=None, unit=None, decimals=0, value=None, as_of=None, state="prev", **extra):
        it = {"id": i, "label": label, "short": short, "shortM": shortM or short, "decimals": decimals,
              "value": value, "change": None, "changePct": None, "asOf": as_of,
              "state": state if value is not None else "missing"}
        if unit:
            it["unit"] = unit
        it.update(extra)
        derived[i] = it

    inv_rows = investor_rows(data)
    unit = (data.get("investorTrading") or {}).get("unit")
    inv_state = block_state(H, "investorTrading", data.get("investorTrading"))
    last = inv_rows[-1] if inv_rows else {}
    for who, name in (("foreign", "외국인"), ("inst", "기관"), ("retail", "개인")):
        dv("flow_" + who, name + " 순매수", name, unit=unit, value=_num(last.get(who)),
           as_of=last.get("date"), state=inv_state)
        five = [r.get(who) for r in inv_rows[-5:]]
        ok5 = len(five) == 5 and all(_num(x) is not None for x in five)
        dv("flow_" + who + "_5d", name + " 5일 누적", name + " 5일", unit=unit,
           value=round(sum(five), 1) if ok5 else None, as_of=last.get("date"), state=inv_state)
    br = (data.get("marketBreadth") or {}).get("kospi") or {}
    dv("breadth_kospi", "코스피 상승/하락 종목", "상승/하락", unit="종목", value=_num(br.get("up")),
       as_of=br.get("as_of"), state=block_state(H, "marketBreadth.kospi", br),
       up=_num(br.get("up")), down=_num(br.get("down")), flat=_num(br.get("flat")))
    amt = [_num(r.get("amount")) for r in ((data.get("rankingsKr") or {}).get("tradingAmount") or [])[:20]]
    ok20 = bool(amt) and all(a is not None for a in amt)
    dv("top20_amount", "거래대금 상위 20 합계", "상위20 거래대금", "거래대금20", unit="조원", decimals=1,
       value=sum(amt) if ok20 else None, as_of=(data.get("rankingsKr") or {}).get("as_of"),
       state=block_state(H, "rankingsKr.tradingAmount", (data.get("rankingsKr") or {}).get("tradingAmount")),
       scale=1e12, count=len(amt))

    def yoy(src, i, label, short, shortM, cross=None):
        """전년비(%) — 지수·금액이면 history 로 (이번 기간 ÷ 1년 전 같은 기간 − 1), 1년 전 점이 없으면 null.
        cross = 대조할 다른 원천의 data 경로. ±YOY_GUARD_PCT 를 넘어도 그 원천의 같은 달 전년비와
        YOY_CROSS_PP 안이면 싣는다. 대조 값이 없거나 더 다르면 null + suspect."""
        row = Q.rows.get(src) or {}
        leaf = get(data, row.get("data") or "") or {}
        hist = leaf.get("history") if isinstance(leaf.get("history"), dict) else {}
        ago = lambda k: (lambda m: m and str(int(m.group(1)) - 1) + m.group(2))(re.match(r"(\d{4})(.*)", str(k)))
        calc = lambda k: (round((hist[k] / hist[ago(k)] - 1) * 100, 2)
                          if _num(hist.get(k)) is not None and _num(hist.get(ago(k))) else None)
        k = leaf.get("period")
        v = calc(k) if k in hist else None
        older = sorted(x for x in hist if str(x) < str(k))
        pv = calc(older[-1]) if (v is not None and older) else None
        q = Q.get(src) or {}
        raw_v = v
        cv = _month_yoy((get(data, cross) or {}).get("history"), _norm_date(k)[:7]) if cross and v is not None else None
        if v is not None and abs(v) > YOY_GUARD_PCT and cv is not None and abs(v - cv) <= YOY_CROSS_PP:
            checks.append({"path": row.get("data"), "state": "ok", "asOf": q.get("asOf"),
                           "note": "%s 전년비 %.1f%% — 대조 통과: 지수 전년비 %.1f%%(%s)" % (src, v, cv, cross.split(".")[-1])})
        elif v is not None and abs(v) > YOY_GUARD_PCT:
            sc, u = q.get("scale"), (q.get("unit") or "").replace("달러", "")
            amt = lambda x: "{:,.0f}{}".format(x / sc, u) if sc else "{:,.2f}".format(x)
            issues.append({"path": row.get("data"), "state": "suspect", "asOf": q.get("asOf"),
                           "note": "%s 전년비 %.1f%% — 원본 이력 확인 필요(%s %s → %s %s)" % (
                               src, v, _norm_date(ago(k))[:7], amt(hist[ago(k)]), _norm_date(k)[:7], amt(hist[k]))
                           + ("" if not cross else " · 대조 실패: 지수 전년비 %.1f%%" % cv if cv is not None else " · 대조할 지수 값 없음")})
            v = pv = None
        dv(i, label, short, shortM, unit="%", decimals=1, value=v, as_of=q.get("asOf"), state=q.get("state"),
           source=src)
        if raw_v is not None and v is None:
            derived[i]["guarded"] = raw_v                # 범위 밖이라 싣지 않은 계산값(화면은 쓰지 않는다)
        if v is not None and pv is not None:
            derived[i]["change"] = _round(v - pv, 2)
        return raw_v

    yoy("cpi_kr", "cpi_kr_yoy", "한국 CPI 전년비", "한국 CPI 전년비", "한국 CPI")
    yoy("cpi_us", "cpi_us_yoy", "미국 CPI 전년비", "미국 CPI 전년비", "미국 CPI")
    ex_yoy = yoy("exports_kr", "exports_kr_yoy", "한국 수출 전년비", "한국 수출 전년비", "한국 수출",
                 cross="economicIndicators.kr.exports_idx_kr")
    # 거시 띠의 수출 칸은 절대값(억달러·월). 전년비는 note 로만 — 범위 밖이면 그렇다고 적는다.
    ex = Q.item("exports_kr")
    ex["label"] = "한국 수출(억달러·월)"
    if ex_yoy is not None:
        ex["note"] = "전년비 %+.1f%%%s" % (ex_yoy, " — 원본 이력 확인 필요" if derived["exports_kr_yoy"]["value"] is None else "")
    derived["exports_kr"] = ex
    nps = data.get("nps") or {}
    eq = next((a.get("pct") for a in (nps.get("allocation") or []) if a.get("asset") == "국내주식"), None)
    nps_asof = nps.get("as_of")
    if eq is None:                                   # data.json 에 없으면 렌즈 시계열(mer_series 사본)
        mi = next((x for x in (mer.get("indicators") or []) if x.get("id") == "nps_kr_equity"), {})
        eq, nps_asof = (mi.get("current") or {}).get("value"), (mi.get("current") or {}).get("asOf")
    dv("nps_kr_equity", "국민연금 국내주식 비중", "연금 국내주식", "연금 국내주식", unit="%", decimals=1,
       value=_num(eq), as_of=(nps_asof or "")[:7] or None, state=block_state(H, "nps", nps) if nps else "prev")

    # 국내
    smv = data.get("stockMovers") or {}
    etf = data.get("etfMovers") or {}
    halts = data.get("marketHalts") or {}
    for key, want in (("kospiGainers", "KOSPI"), ("kospiLosers", "KOSPI"), ("kosdaqGainers", "KOSDAQ"),
                      ("kosdaqLosers", "KOSDAQ")):
        rows_ = smv.get(key) or []
        bad = sum(1 for r in rows_ if r.get("market") != want)
        if bad:
            issues.append({"path": "stockMovers." + key, "state": "suspect", "asOf": (rows_[0] if rows_ else {}).get("as_of"),
                           "note": "stockMovers.%s %d개 중 %d개가 %s 아님 — 원천 오염, 수집기 확인 필요(묶음은 %s 만 싣는다)"
                                   % (key, len(rows_), bad, want, want)})
    b["market-domestic"] = market("domestic", {
        "amount": b["home"]["topAmount"],
        # 토스 체결 거래대금 상위 20(코스피·코스닥 섞인 한 목록, 원천이 시장별로 나뉘지 않는다) — amount 와 같은 모양
        "tossAmount": {"asOf": ra.get("as_of"), "state": block_state(H, "rankingsKr.tossAmount", ra.get("tossAmount")),
                       "items": stock_rows(ra.get("tossAmount"), amount=True)},
        "gainers": {"kospi": stock_rows(smv.get("kospiGainers"), market="KOSPI"),
                    "kosdaq": stock_rows(smv.get("kosdaqGainers"), market="KOSDAQ"),
                    "state": block_state(H, "stockMovers.kospiGainers", smv.get("kospiGainers"))},
        "losers": {"kospi": stock_rows(smv.get("kospiLosers"), market="KOSPI"),
                   "kosdaq": stock_rows(smv.get("kosdaqLosers"), market="KOSDAQ"),
                   "state": block_state(H, "stockMovers.kospiLosers", smv.get("kospiLosers"))},
        "etf": {"gainers": stock_rows(etf.get("etfGainers")), "losers": stock_rows(etf.get("etfLosers")),
                "state": block_state(H, "etfMovers.etfGainers", etf.get("etfGainers"))},
        "sectors": b["home"]["sectors"],
        "flows": investors_block(data, H, 20),
        "breadth": {k: (data.get("marketBreadth") or {}).get(k) for k in ("kospi", "kosdaq")}
                   | {"state": block_state(H, "marketBreadth.kospi", (data.get("marketBreadth") or {}).get("kospi"))},
        "halts": {"active": halts.get("active") or [], "recent": (halts.get("history") or [])[:10],
                  "asOf": halts.get("asOf"), "state": block_state(H, "marketHalts", halts)},
        # KRX 보기 확장(기획 v4 9장 후보 2) — 시장별 20행. 화면 버튼은 후속(지금은 묶음 필드만)
        **{k: krx_rank_view(H, data.get("rankingsKr") or {}, k) for k in ("marketCap", "volume", "high52", "low52")},
        # 배당·실적 일정(후보 3) — 최근 90일 공시 + 직전 결산 배당, 최신순
        "corpEvents": {"asOf": (data.get("corpEvents") or {}).get("asOf"), "from": (data.get("corpEvents") or {}).get("from"),
                       "state": block_state(H, "corpEvents", data.get("corpEvents")), "items": corp_events(data)},
    })

    # 해외
    idx_ids = [k.lower() for k in (data.get("indices") or {})]
    yr = {i: since(Q.series(i), 365, today) for i in idx_ids}
    start = max((s[0][0] for s in yr.values() if s), default=None)
    compare = {}
    for i, s in yr.items():
        s = [p for p in s if start and p[0] >= start]
        if s and s[0][1]:
            compare[i] = [[p[0], round(p[1] / s[0][1] * 100, 2)] for p in s]
    sent = data.get("sentiment") or {}
    yc = data.get("yieldCurve") or {}

    def curve(cc):
        c = yc.get(cc) or {}
        last = max((s["data"][-1]["date"] for s in (c.get("series") or []) if s.get("data")), default=None)
        return {"label": c.get("label"), "tenors": CURVE_TENORS, "asOf": last, "state": block_state(H, "yieldCurve." + cc, c),
                **{k: c.get(k) for k in ("current", "prev_month", "prev_3m", "prev_6m", "prev_1y")}}

    def year(i):
        return Q.item(i, spark=0) | {"series": since(Q.series(i), 365, today)}

    b["market-global"] = market("global", {
        "indices": [Q.item(i, spark=0) | {"series": yr[i]} for i in idx_ids],
        "compare": {"from": start, "base": 100, "series": compare},
        "fearGreed": year("fear_greed") | {"rating": (sent.get("fear_greed") or {}).get("rating")},
        "vix": year("vix"), "move": year("move"), "crypto": year("btc"),
        "usCurve": curve("us"), "usCalendar": calendar_events(data, now, cc="US"),
    })

    # 환율·금리
    banks = []
    for cc, rid, pat in CENTRAL_BANKS:
        it = Q.item(rid, spark=0)
        it["country"] = cc
        it["nextMeeting"] = next((e for e in calendar_events(data, now) if re.search(pat, e["name"] or "")), None)
        banks.append(it)
    rate_ids = [r["id"] for r in rows if r["asset"] == "rate"]
    b["market-fxrates"] = market("fxrates", {
        "fx": [year(k.lower()) for k in (data.get("fx") or {})],
        "rates": [year(i) for i in rate_ids],
        "curves": {cc: curve(cc) for cc in yc},
        "centralBanks": banks,
    })

    # 원자재
    gk, g, fxq = Q.get("goldkrw") or {}, Q.get("gold") or {}, Q.get("usdkrw") or {}
    # KRX 금은 전일 확정치다 — 지금의 국제 금·환율과 섞으면 하루치 움직임이 프리미엄으로 둔갑한다.
    # 기준일(as_of)이 있으면 그날의 국제 금·달러원 종가(history)로 잰다. 없으면 지금 값끼리(basis=spot).
    d = (gk.get("asOf") or "")[:10] if MARKET_OF.get("goldkrw") == "daily" else ""
    day = lambda i: next((p[1] for p in reversed(Q.series(i)) if p[0] == d), None)
    if d and day("gold") is not None and day("usdkrw") is not None:
        basis, g_in, fx_in = "sameDay", day("gold"), day("usdkrw")
    else:
        basis, g_in, fx_in = "spot", g.get("value"), fxq.get("value")
    prem = gold_premium(gk.get("value"), g_in, fx_in)
    gp_state = ("missing" if prem is None else
                "kept" if "kept" in (gk.get("state"), g.get("state"), fxq.get("state")) else
                "stale" if "stale" in (gk.get("state"), g.get("state"), fxq.get("state")) else "prev")
    dv("gold_premium", "금 김치프리미엄", "금 김프", unit="%", decimals=2, value=prem,
       as_of=d or gk.get("asOf"), state=gp_state, basis=basis)
    fr = data.get("freight") or {}
    enso = (data.get("climate") or {}).get("enso") or {}
    lme = data.get("lmeInventory") or {}
    com_ids = [r["id"] for r in rows if r["asset"] == "commodity"]
    b["market-commodities"] = market("commodities", {
        "items": [Q.item(i) | {"group": COMMODITY_GROUP.get(i), "series": since(Q.series(i), 92, today)} for i in com_ids],
        "freight": {"state": block_state(H, "freight", fr), "items": [
            {k: f.get(k) for k in ("code", "name", "price", "chgPct", "date", "exchange")} for f in (fr.get("items") or [])]},
        "lme": {"asOf": lme.get("as_of"), "state": block_state(H, "lmeInventory", lme), "items": lme.get("data") or []},
        "enso": {"line": ol.enso_line(enso), "phase": enso.get("phase"), "strength": enso.get("strength"),
                 "trend": enso.get("trend"), "oni": (enso.get("oni") or {}).get("value"),
                 "asOf": (enso.get("oni") or {}).get("asOf"), "state": block_state(H, "climate.enso", enso)},
        "goldPremium": {"pct": prem, "basis": basis, "date": d or None,
                        "krwPerG": gk.get("value"), "usdPerOz": g_in, "usdkrw": fx_in,
                        "asOf": {"goldkrw": gk.get("asOf"), "gold": d if basis == "sameDay" else g.get("asOf"),
                                 "usdkrw": d if basis == "sameDay" else fxq.get("asOf")},
                        "state": gp_state,
                        "formula": "국내 금 원/g ÷ (국제 금 $/oz × 달러원 ÷ 31.1035) − 1"},
    })

    # 거시
    topics = {}
    for r in rows:
        if r["asset"] == "macro":
            it = Q.item(r["id"], spark=0, tail=24)
            it["country"], it["topic"] = r.get("country"), r.get("topic")
            topics.setdefault(r.get("topic") or "growth", []).append(it)
    b["market-macro"] = market("macro", {"topics": topics, "calendar": all_events(data)})

    # 수급
    nps = data.get("nps") or {}
    stocks = {}
    for code, s in ((data.get("stockFlows") or {}).get("items") or {}).items():
        stocks[code] = {"name": s.get("name"), "short": stock_short(s.get("name"))[0], "market": s.get("market"),
                        "secType": s.get("secType"), "shares": s.get("shares"),
                        "investor": [[r.get("date"), r.get("foreign"), r.get("inst"), r.get("retail"), r.get("fholdRate")]
                                     for r in (s.get("investor") or [])],
                        "credit": s.get("credit") or [], "warnings": s.get("warnings") or []} | flow_last(s)
    b["market-flows"] = {"market": kr, "newsTopic": MARKET_NEWS["flows"],
                         "strip": [pick(i) for i in STRIPS["flows"]],
                         "views": {"investors": investors_block(data, H, 400),
                                   "stocks": {"asOf": (data.get("stockFlows") or {}).get("generatedAt"),
                                              "state": block_state(H, "stockFlows.items", (data.get("stockFlows") or {}).get("items")),
                                              "columns": ["date", "foreign", "inst", "retail", "fholdRate"], "items": stocks},
                                   "nps": {"asOf": nps.get("as_of"), "state": block_state(H, "nps", nps),
                                           "allocation": nps.get("allocation") or [], "source": nps.get("source")}}}

    # 부동산
    rk = (data.get("realestate") or {}).get("kr") or {}
    ru = (data.get("realestate") or {}).get("us") or {}
    sido = sido_names()
    sub = data.get("subscription") or {}
    # 시도 17 아파트 매매·전세 지수 36개월(realestate.kr.regionSeries) — 수도권 겹침 차트용. 없는 시도는 series 를 안 단다.
    rs = rk.get("regionSeries") or {}
    ser = lambda code: ({k: [[_norm_date(p), v] for p, v in rs[code].get(k) or []] for k in ("apt", "jns")}
                        if isinstance(rs.get(code), dict) else None)
    with_series = lambda it, code: it | ({"series": ser(code)} if ser(code) else {})
    rsub = rk.get("region_sub") or {}
    b["market-realestate"] = market("realestate", {
        "kr": [Q.item(r["id"], spark=0, tail=24) for r in rows if r["asset"] == "realestate" and r.get("topic") == "kr"],
        "regions": {"state": block_state(H, "realestate.kr.region", rk.get("region")),
                    "seriesState": block_state(H, "realestate.kr.regionSeries", rs),
                    "items": [with_series({"code": x.get("code"), "name": sido.get(x.get("code")), "chgPct": x.get("val"),
                                           "period": _norm_date(x.get("period"))}, x.get("code"))
                              for x in (rk.get("region") or [])]},
        "regionSub": {"state": block_state(H, "realestate.kr.region_sub", rk.get("region_sub")),
                      "items": {code: {"name": sido.get(code), "period": _norm_date(v.get("period")),
                                       "subs": [{"name": s.get("name"), "chgPct": s.get("val")} for s in (v.get("subs") or [])]}
                                for code, v in (rk.get("region_sub") or {}).items()}},
        "capital": {code: with_series({"name": sido.get(code), "period": _norm_date((rsub.get(code) or {}).get("period")) if code in rsub else None,
                                       "subs": [{"name": x.get("name"), "chgPct": x.get("val")}
                                                for x in ((rsub.get(code) or {}).get("subs") or [])]}, code)
                    for code in CAPITAL_AREA if code in rsub or code in rs},
        "us": [Q.item(r["id"], spark=0, tail=24) for r in rows if r["asset"] == "realestate" and r.get("topic") == "us"],
        "usStates": {"state": block_state(H, "realestate.us.case_shiller_state", ru.get("case_shiller_state")),
                     "items": {st: {"value": v.get("value"), "chgPct": v.get("chg"), "period": v.get("period")}
                               for st, v in (ru.get("case_shiller_state") or {}).items() if isinstance(v, dict)}},
        "subscription": {"state": block_state(H, "subscription", sub), "source": sub.get("source"),
                         "byRegion": sub.get("byRegion") or {}},
    })

    # 시장 화면 한 줄 — one_liners 사전 조합. 되살린 값(kept)·없는 값은 재료로 쓰지 않는다.
    def live_q(i):
        q = Q.get(i) or {}
        return q if q.get("state") not in ("kept", "missing") else {}

    brd = derived.get("breadth_kospi") or {}
    flow_today = inv_rows[-1] if inv_rows and inv_rows[-1].get("date") == session else None
    done = [e for e in all_events(data) if e.get("act") and (e.get("date") or "") <= today.isoformat()]
    latest = max(done, key=lambda e: (e["date"], e.get("time") or ""), default=None)
    fgq, usq, apt, uns = live_q("fear_greed"), live_q("us10y"), live_q("apt_price_idx_kr"), live_q("unsold_total_kr")
    lines = {
        "domestic": [ol.move("코스피", live_q("kospi").get("changePct")),
                     ol.breadth(brd.get("up"), brd.get("down")) if brd.get("asOf") == session else None,
                     ol.flow(flow_today)],
        "global": [ol.move("S&P 500", live_q("sp500").get("changePct")),
                   ol.fear_greed(fgq.get("value"), (sent.get("fear_greed") or {}).get("rating"))],
        "fxrates": [ol.fx(live_q("usdkrw").get("changePct")), ol.yield_level("미 10년", usq.get("value"), usq.get("change"))],
        "commodities": [ol.move("WTI", live_q("wti").get("changePct")), ol.move("금", live_q("gold").get("changePct"))],
        "macro": [ol.release(latest)],
        "flows": [ol.streak(inv_rows)],
        "realestate": [ol.index_move("아파트 매매지수", apt.get("changePct"), apt.get("asOf")),
                       ol.count("미분양", uns.get("value"), "호", uns.get("changePct"))],
    }
    for name, parts in lines.items():
        b["market-" + name]["line"] = ol.line(parts)

    b["lens"] = build_lens(mer)
    b["news"] = news_bundle(data, H)
    b["_issues"] = issues            # 파일로 쓰지 않는다(write 가 meta 에 합친다)
    b["_checks"] = checks
    return b


def sido_names():
    """시도 코드 → 짧은 이름. 원천은 fetch_data.RONE_SIDO_CODE(첫 짧은 이름) — import 하면 수집기 의존성이 다 딸려 와서 소스에서 읽는다."""
    with io.open(os.path.join(ROOT, "scripts", "fetch_data.py"), encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"RONE_SIDO_CODE = (\[.*?\])\n", src, re.S)
    out = {}
    for name, code in ast.literal_eval(m.group(1)) if m else []:
        if code not in out or len(name) < len(out[code]):       # 「전라남」·「전남」 중 「전남」
            out[code] = name
    return out


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def meta(data, mer, sizes, now, bundles):
    dh = data.get("dataHealth") or {}
    fresh = {s: 0 for s in STATES}                      # 띠(홈 8 + 화면별 6) 칸의 신선도 집계
    for name, obj in bundles.items():
        if name.startswith("_"):
            continue
        for it in obj.get("strip") or []:
            fresh[it.get("state", "missing")] = fresh.get(it.get("state", "missing"), 0) + 1
    return {"generatedAt": now.isoformat(timespec="seconds"), "dataUpdated": data.get("lastUpdated"),
            "merAsOf": mer.get("asOf"), "bundles": sizes, "maxBytes": MAX_BYTES,
            "states": {s: STATE_LABEL[s] for s in STATES}, "stripFreshness": fresh,
            # 지금 발동 중인 매매중단 — 모든 화면 머리의 배너가 이 1KB 파일만 보고 판정한다(국내 묶음 54KB 를 받지 않게)
            "haltsActive": (((bundles.get("market-domestic") or {}).get("views") or {}).get("halts") or {}).get("active") or [],
            # 화면이 지금 시각으로 다시 잴 때 쓰는 임계(분). live 칸은 liveUntil 이 지나면 prev 로 내린다.
            "freshnessRules": {"liveMin": LIVE_MIN, "staleOpenMin": STALE_OPEN_MIN,
                               "staleClosedMin": STALE_CLOSED_MIN, "staleOffdayMin": STALE_OFFDAY_MIN},
            "health": {"checkedAt": dh.get("checkedAt"), "summary": dh.get("summary"), "blocking": dh.get("blocking") or [],
                       "issues": [{k: i.get(k) for k in ("path", "state", "asOf", "ageDays")}
                                  for i in (dh.get("items") or []) if i.get("state") != "ok"]
                                 + list(bundles.get("_issues") or []),
                       "checks": list(bundles.get("_checks") or [])}}


def write(bundles, data, mer, now, out_dir=OUT_DIR):
    os.makedirs(out_dir, exist_ok=True)
    sizes = {}
    for name, obj in bundles.items():
        if name.startswith("_"):
            continue
        text = dumps(obj)
        sizes[name + ".json"] = len(text.encode("utf-8"))
        if sizes[name + ".json"] > MAX_BYTES:            # 넘치면 직전 파일을 둔다 — main 이 exit 1 로 알린다
            continue
        with io.open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    m = meta(data, mer, sizes, now, bundles)
    with io.open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(m))
    return sizes


def main(argv):
    now = dt.datetime.now(KST)
    if "--now" in argv:
        now = _iso_dt(argv[argv.index("--now") + 1]).astimezone(KST)
    data, mer = load("data.json"), load("mer_signals.json", {})
    bundles = build_all(data, mer, now, load("toss_snapshot.json", {}))
    sizes = write(bundles, data, mer, now)
    over = {k: v for k, v in sizes.items() if v > MAX_BYTES}
    for k, v in sizes.items():
        print("%-26s %7.1f KB%s" % (k, v / 1024, "  ← 200KB 초과" if k in over else ""))
    for it in bundles.get("_issues") or []:
        print("주의 " + it["note"])
    for it in bundles.get("_checks") or []:
        print("대조 " + it["note"])
    print("화면 묶음 %d개 — 기준 %s" % (len(sizes) + 1, now.isoformat(timespec="minutes")))
    return 1 if over else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
