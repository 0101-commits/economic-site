#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""지표 레지스트리 생성기 — IA 개편 v3 P0.

왜 있나: 같은 지표를 부르는 분류 체계가 코드 안에 7개 있었다(사이드바 그룹 5 ·
비교차트 카탈로그 85 · 거시 카테고리 10×50 · 메르 렌즈 레이어 4×48 · 뉴스 16 ·
분석 노트 4 · sources 33). 서로 매핑이 없어 KOSPI 가 14곳, USD/KRW 가 12곳에
각자 원본처럼 떴고, 반대로 매일 수집만 하고 화면에 없는 데이터가 22건 남았다.
여기서 한 지표 = 한 행으로 합친다.

  data.json + js/app1.js(macroIndicators) + mer_signals.json
     → (이 스크립트의 규칙 + 아래 결정 표)
        → js/app0.js   (window.ECON_IND — 화면이 읽는 단일 원천)

app0 인 이유: 로더(index.html)와 build-frontend.yml 이 `js/app[0-9].js` 를 그대로
집어가므로 minify·캐시버스팅·로드 순서가 공짜로 따라온다. 0 이라 app1 보다 먼저 선다.

사용:
  python scripts/build_indicators.py           # js/app0.js 재생성
  python scripts/build_indicators.py --check   # 드리프트·죽은 경로·누락 검사(게이트)
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "js", "app0.js")

# ── 사람이 내리는 결정 ─────────────────────────────────────────────────────
# tier 1 = 홈에 실리는 대표 지표. 현행 상단 티커 12종과 같은 집합으로 시작한다
# (홈 KPI 4장이 index.html 에 하드코딩돼 있던 것을 이 목록이 대체한다).
TIER1 = [
    "kospi", "kosdaq", "usdkrw", "eurkrw", "wti", "brent", "gold",
    "sp500", "nasdaq", "nikkei", "base_rate_kr", "us10y",
]

# tier 2 = 각 자산군 화면의 주요 지표. 나머지는 3(상세 표 전용).
TIER2 = [
    "shanghai", "sox", "usdjpy", "eurusd", "jpykrw", "silver", "copper", "natgas",
    "kr10y", "us2y", "vix", "vkospi", "fear_greed", "move",
    "cpi_kr", "cpi_us", "gdp_kr", "gdp_us", "unemployment_kr", "unemployment_us",
    "exports_kr", "base_rate_us", "ff_target", "t10y2y_us",
]

# 지표 → news 주제 키(16종). 한 줄 맥락(P3)이 여기서 나온다. 없으면 줄을 비운다.
NEWS_BY_ASSET = {
    "fx": "외환",
    "index": "주식",
    "rate": "채권",
    "commodity": "원자재",
}
NEWS_BY_ID = {
    "wti": "원유", "brent": "원유", "natgas": "원유",
    "gold": "귀금속", "silver": "귀금속", "platinum": "귀금속", "palladium": "귀금속",
    "copper": "비철금속", "aluminum": "비철금속", "zinc": "비철금속", "nickel": "비철금속",
    "lead": "비철금속", "tin": "비철금속",
    "gdp_kr": "한국GDP", "cpi_us": "미국CPI", "exports_kr": "한국수출",
    "base_rate_kr": "한국은행", "gdp_cn": "중국경기", "pmi_cn": "중국경기",
    "gdp_jp": "일본경기", "pmi_jp": "일본경기", "gdp_de": "독일경기", "pmi_de": "독일경기",
    "gdp_uk": "영국경기", "pmi_uk": "영국경기", "gdp_eu": "유로존", "pmi_eu": "유로존",
}

# 자산군 → 원본 화면(canonical). 화면이 여럿인 지표는 여기 적힌 한 곳이 원본이고
# 다른 화면에 같은 값이 나오면 그건 요약이다(제목 옆 › 로 원본에 연결).
CANONICAL = {
    "index": "market#index",
    "equity": "market#equity",
    "fx": "market#fx",
    "rate": "market#bond",
    "commodity": "market#commodity",
    "macro": "macro",
    "realestate": "realestate",
    "flow": "flow",
    "sentiment": "dashboard#mood",
}

# 자산군 규칙과 다른 원본을 갖는 지표. 정책금리는 거시 통계이면서도 화면상 원본은
# 「시장 > 금리·채권」이다(곡선·주요국 현황표가 거기 있다).
CANONICAL_BY_ID = {
    "base_rate_kr": "market#rate", "base_rate_us": "market#rate",
    "base_rate_jp": "market#rate", "base_rate_eu": "market#rate",
    "base_rate_uk": "market#rate", "base_rate_cn": "market#rate",
    "ff_target": "market#rate", "t10y2y_us": "market#bond",
    "bond10y_jp": "market#bond", "hy_spread": "market#bond",
    "vix": "dashboard#mood", "dxy_idx": "market#fx",
}

# 거시 카테고리(10) → 거시 화면 주제 탭(6).
TOPIC_TAB = {
    "경기": "growth", "물가": "price", "고용": "labor",
    "통화": "money", "금리": "money", "외환": "trade", "무역": "trade",
    "소비": "demand", "부동산": "demand", "시장": "growth",
}

# 라벨 표기 단일화(D5). 화면마다 달리 부르던 이름을 여기로 모은다.
LABEL = {
    "KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ", "SP500": "S&P 500", "NASDAQ": "NASDAQ",
    "Nikkei": "닛케이 225", "Shanghai": "상하이종합", "SOX": "필라델피아 반도체",
    "USDKRW": "USD/KRW", "EURKRW": "EUR/KRW", "JPYKRW": "JPY(100)/KRW",
    "EURUSD": "EUR/USD", "USDJPY": "USD/JPY",
    "Gold": "금", "Silver": "은", "Platinum": "백금", "Palladium": "팔라듐",
    "Copper": "구리", "Aluminum": "알루미늄", "Zinc": "아연", "Nickel": "니켈",
    "Lead": "납", "Tin": "주석",
    "WTI": "WTI 원유", "Brent": "브렌트유", "NatGas": "천연가스",
    "Wheat": "밀", "Corn": "옥수수", "Soybean": "대두", "Rice": "쌀",
    "Coffee": "커피", "Sugar": "설탕", "Cotton": "면화", "Cocoa": "코코아",
    "vix": "VIX", "vkospi": "V-KOSPI", "move": "MOVE", "fear_greed": "공포·탐욕 지수",
}

# 옛 이름 → 새 이름. 화면이 같은 대상을 달리 부르던 표기를 여기 모은다(D5).
# 티커·위젯 제목이 쓰는 문자열이 전부 들어 있어야 ECON_IND.find(name) 이 맞는다.
ALIASES = {
    "kospi": ["KOSPI", "KOSPI 지수"],
    "kosdaq": ["KOSDAQ"],
    "usdkrw": ["USD/KRW", "USD / KRW", "달러/원"],
    "eurkrw": ["EUR/KRW", "EUR / KRW"],
    "wti": ["WTI", "WTI 유가", "WTI 원유"],
    "brent": ["BRENT", "브렌트유"],
    "gold": ["금(GOLD)", "금(Gold)", "금"],
    "sp500": ["S&P 500", "S&P500"],
    "nasdaq": ["NASDAQ"],
    "nikkei": ["닛케이", "닛케이 225"],
    "base_rate_kr": ["한국 기준금리", "기준금리"],
    "us10y": ["미 10년물", "미국 10년물", "미국채 10년물"],
}

# 검색어(전역 검색 전용). aliases 와 달리 화면 제목 매칭에는 쓰지 않는다 —
# '환율' 같은 말은 사람이 검색창에 치는 말이지, 위젯 제목이 아니기 때문이다.
KEYWORDS = {
    "usdkrw": ["환율", "달러", "원달러", "달러원"],
    "eurkrw": ["유로 환율"], "usdjpy": ["엔화", "엔 환율"], "jpykrw": ["엔화", "엔 환율"],
    "base_rate_kr": ["기준금리", "한국은행", "금리"],
    "base_rate_us": ["미국 금리", "연준", "FOMC"], "ff_target": ["연준", "정책금리", "FOMC"],
    "us10y": ["미국 금리", "국채", "장기금리"], "kr10y": ["국고채", "국채", "금리"],
    "wti": ["유가", "기름값", "원유"], "brent": ["유가", "원유"],
    "gold": ["금값", "귀금속"], "silver": ["은값", "귀금속"], "copper": ["구리", "비철"],
    "kospi": ["코스피", "주가", "증시"], "kosdaq": ["코스닥", "주가", "증시"],
    "sp500": ["미국 증시", "미장"], "nasdaq": ["나스닥", "미국 증시", "미장"],
    "cpi_kr": ["물가", "인플레이션"], "cpi_us": ["물가", "인플레이션", "미국 물가"],
    "unemployment_kr": ["고용", "실업"], "unemployment_us": ["고용", "실업"],
    "vix": ["변동성", "공포"], "vkospi": ["변동성", "공포"],
    "btc": ["비트코인", "코인", "가상자산"],
}

# 화면 없이 수집만 되는 것들의 처리 결정(D10). 기획 §C3 의 "결정 필요" 3건.
COLLECT_ONLY = {
    "btc": "시장>지수 탭에 가상자산 카드 1장으로 노출 예정(P3). 그때까지 수집만.",
}

ASSET_ORDER = ["index", "equity", "fx", "rate", "commodity", "macro", "realestate",
               "sentiment", "flow"]


def load(path):
    with io.open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return json.load(f)


def macro_rows():
    """js/app1.js 의 macroIndicators 를 그대로 읽는다(이름·국가·분류·경로의 원천)."""
    with io.open(os.path.join(ROOT, "js", "app1.js"), encoding="utf-8") as f:
        src = f.read()
    start = src.index("const macroIndicators = [")
    body = src[start: src.index("\n];", start)]
    objs, depth, cur = [], 0, ""
    for ch in body[body.index("["):]:
        if ch == "{":
            depth += 1
            if depth == 1:
                cur = ""
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                objs.append(cur)
            continue
        if depth >= 1:
            cur += ch
    rows = []
    for o in objs:
        def g(key):
            m = re.search(key + r":\s*'((?:[^'\\]|\\.)*)'", o)
            return m.group(1) if m else None
        rows.append({k: g(k) for k in ("name", "cc", "cat", "unit", "src", "freq", "dataPath")})
    return rows


_SRC_CACHE = None


def on_screen(key):
    """화면 코드(index.html · js/app[1-7].js)가 그 키를 실제로 읽는가."""
    global _SRC_CACHE
    if _SRC_CACHE is None:
        parts = []
        for name in ["index.html"] + ["js/app%d.js" % i for i in range(1, 8)]:
            path = os.path.join(ROOT, *name.split("/"))
            if os.path.exists(path):
                with io.open(path, encoding="utf-8", errors="replace") as f:
                    parts.append(f.read())
        _SRC_CACHE = "\n".join(parts)
    return key in _SRC_CACHE


def has_path(data, path):
    """'a.b.c' 또는 'yieldCurve.us:10Y' 가 data.json 에 실재하는지."""
    head, _, tenor = path.partition(":")
    cur = data
    for part in head.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False
    if tenor:
        # 곡선은 {current:[…], series:[{tenor,…}]} 꼴이다 — 만기는 series 안에 있다
        if isinstance(cur, dict):
            if tenor in cur:
                return True
            cur = cur.get("series") or list(cur.values())
        if isinstance(cur, list):
            return any(isinstance(v, dict) and v.get("tenor") == tenor for v in cur)
        return False
    return True


def tier_of(ind_id):
    if ind_id in TIER1:
        return 1
    if ind_id in TIER2:
        return 2
    return 3


# ── 표기 규칙 — 자릿수·단위는 지표가 정한다 (기획 2026-09-21 구조 통일 S1) ────────
# 왜 여기인가: 자릿수를 정하는 경로가 코드 안에 8가지 있었고 가장 넓은 것이 하드코딩
# toFixed 285곳이었다. 같은 USD/KRW 가 화면마다 1,372.58 / 1,372.6 / 1372.6 / 1,372.58원
# 네 모양으로 나왔다. 표기는 화면이 아니라 지표가 정하는 것이 맞다.
#   decimals  소수 자릿수(고정 — trailing zero 를 남긴다. 훑어 읽으려면 자리가 고정돼야 한다)
#   unit      값 뒤에 붙는 단위. 표에서는 열 머리로 올라가고 카드에서는 값 옆에 붙는다
#   scale     {"by": 배율, "unit": 바꾼 단위} — 원 단위 값을 조원으로 줄여 보일 때
FORMAT_BY_ASSET = {
    "index":     {"decimals": 2},
    "fx":        {"decimals": 2, "unit": "원"},
    "commodity": {"decimals": 2, "unit": "$"},
    "rate":      {"decimals": 2, "unit": "%"},
    "macro":     {"decimals": 1},
    "realestate": {"decimals": 1},
    "sentiment": {"decimals": 2},
    "flow":      {"decimals": 0},
    "equity":    {"decimals": 0, "unit": "원"},
}
# 자산군 기본값을 뒤집는 지표. data.json 이 이미 갖고 있는 정밀도를 화면이 버리지 않게 한다.
FORMAT_BY_ID = {
    "jpykrw":     {"decimals": 4, "unit": "원"},   # 8.7226 — 2자리면 8.72 로 잘린다
    "eurusd":     {"decimals": 4, "unit": ""},     # 1.1477 — 통화쌍이라 원이 아니다
    "usdjpy":     {"decimals": 2, "unit": "엔"},
    "fear_greed": {"decimals": 0, "unit": ""},
    "vkospi":     {"decimals": 2, "unit": ""},
    "vix":        {"decimals": 2, "unit": ""},
    "nps_aum":    {"decimals": 1, "unit": "조원"},
    "btc":        {"decimals": 0, "unit": "$"},
}


def format_of(ind_id, asset, unit_hint=None):
    """지표 하나의 표기 규칙 — id 결정이 자산군 기본값을 이긴다."""
    out = dict(FORMAT_BY_ASSET.get(asset) or {})
    out.update(FORMAT_BY_ID.get(ind_id) or {})
    # 수집원이 단위를 들고 온 경우(거시 지표) 그것을 쓴다 — 우리가 지어내지 않는다.
    if unit_hint and not FORMAT_BY_ID.get(ind_id, {}).get("unit"):
        out["unit"] = unit_hint
    if out.get("unit") == "":
        out.pop("unit")
    return out


def news_of(ind_id, asset):
    return NEWS_BY_ID.get(ind_id) or NEWS_BY_ASSET.get(asset)


def build(data, mer):
    rows = []
    seen = set()

    by_id = {}

    def add(**kw):
        # 같은 지표가 두 곳에서 수집되는 경우가 있다(미10년물 = yieldCurve 곡선 +
        # economicIndicators 단일값). 행을 늘리지 않고 먼저 선 행에 경로만 붙인다 —
        # "한 지표 = 한 행"이 이 파일의 전부다.
        if kw["id"] in seen:
            prev = by_id[kw["id"]]
            prev.setdefault("alsoData", []).append(kw.get("data"))
            if kw.get("series") and not prev.get("series"):
                prev["series"] = kw["series"]
            return
        seen.add(kw["id"])
        by_id[kw["id"]] = kw
        kw.setdefault("tier", tier_of(kw["id"]))
        kw.setdefault("canonical", CANONICAL_BY_ID.get(kw["id"]) or CANONICAL[kw["asset"]])
        news = news_of(kw["id"], kw["asset"])
        if news:
            kw["news"] = news
        if kw["id"] in ALIASES:
            kw["aliases"] = ALIASES[kw["id"]]
        if kw["id"] in KEYWORDS:
            kw["keywords"] = KEYWORDS[kw["id"]]
        if kw["id"] in COLLECT_ONLY:
            kw["collectOnly"] = COLLECT_ONLY[kw["id"]]
        # 표기(S1) — 자릿수는 항상, 단위는 아는 것만. 화면은 이 두 값만 보고 숫자를 찍는다.
        fmt = format_of(kw["id"], kw["asset"], kw.get("unit"))
        if fmt.get("decimals") is not None:
            kw["decimals"] = fmt["decimals"]
        if fmt.get("unit"):
            kw["unit"] = fmt["unit"]
        if fmt.get("scale"):
            kw["scale"] = fmt["scale"]
        rows.append(kw)

    # 지수 · 환율 · 원자재 — data.json 의 현재값 + history 시계열
    for key in data.get("indices", {}):
        add(id=key.lower(), label=LABEL.get(key, key), asset="index",
            data="indices." + key, series="history.indices." + key)
    for key in data.get("fx", {}):
        add(id=key.lower(), label=LABEL.get(key, key), asset="fx",
            data="fx." + key, series="history.fx." + key)
    for key in data.get("commodities", {}):
        add(id=key.lower(), label=LABEL.get(key, key), asset="commodity",
            data="commodities." + key, series="history.commodities." + key)
    for key in (data.get("history", {}).get("crypto") or {}):
        add(id=key.lower(), label=key, asset="index", data="history.crypto." + key,
            series="history.crypto." + key)

    # 금리·채권 — 나라별 곡선에서 대표 만기만 지표로 세운다(나머지는 곡선 차트가 쓴다)
    tenors = {"us": ["2Y", "10Y", "30Y"], "kr": ["3Y", "10Y"], "jp": ["10Y"],
              "eu": ["10Y"], "uk": ["10Y"]}
    for cc, want in tenors.items():
        curve = data.get("yieldCurve", {}).get(cc) or {}
        for tenor in want:
            path = "yieldCurve.%s:%s" % (cc, tenor)
            if not has_path(data, path):
                continue
            add(id="%s%s" % (cc, tenor.lower()), label="%s 국채 %s" % (
                {"us": "미국", "kr": "한국", "jp": "일본", "eu": "유로존", "uk": "영국"}[cc], tenor),
                unit="%", asset="rate", data=path)

    # 심리 지표
    for key in data.get("sentiment", {}):
        add(id=key.lower(), label=LABEL.get(key, key), asset="sentiment",
            data="sentiment." + key)

    # 거시 — macroIndicators(화면에 있는 것) ∪ data.json(수집된 것)
    by_path = {r["dataPath"]: r for r in macro_rows()}
    ei = data.get("economicIndicators", {})
    for cc in ei:
        for key in ei[cc]:
            path = "economicIndicators.%s.%s" % (cc, key)
            row = by_path.get(path)
            desc = (ei[cc][key] or {}).get("desc")
            cat = (row or {}).get("cat") or ""
            add(id=key.lower(), label=LABEL.get(key.lower()) or (row or {}).get("name") or desc or key,
                unit=(row or {}).get("unit"), asset="macro",
                topic=TOPIC_TAB.get(cat, "growth"), cat=cat or None,
                country=cc, data=path, onScreen=bool(row) or on_screen(key))

    # 부동산
    for cc in data.get("realestate", {}):
        block = data["realestate"][cc] or {}
        for key in block:
            if not isinstance(block[key], dict):
                continue
            path = "realestate.%s.%s" % (cc, key)
            row = by_path.get(path)
            base = re.sub(r"_(kr|us)$", "", key.lower())
            add(id="%s_%s" % (base, cc), label=(row or {}).get("name") or
                block[key].get("desc") or key, asset="realestate",
                topic=cc, data=path, onScreen=bool(row) or on_screen(key))

    # 메르 렌즈 id 를 같은 행에 붙인다(렌즈 48 중 43이 여기 이미 있다)
    mer_by_path, mer_ids = {}, {}
    for item in (mer.get("indicators") or []):
        if item.get("dataPath"):
            mer_by_path[item["dataPath"]] = item["id"]
        mer_ids[item["id"]] = item

    def mer_id_for(row):
        for cand in (row.get("data"), row.get("series")):
            if cand and cand in mer_by_path:
                return mer_by_path[cand]
        # mer_series.* 는 렌즈가 자체 축적한 사본이다 — 같은 대상이면 묶는다
        head = {"mer_series.jgb": "jp10y", "mer_series.lmeInventory": "lme_inventory",
                "mer_series.npsAllocation": "nps", "mer_series.freight": "freight",
                "investorTrading.daily": "investor_trading"}
        for prefix, our in head.items():
            if row["id"] == our:
                for path, mid in mer_by_path.items():
                    if path.startswith(prefix):
                        return mid
        return row["id"] if row["id"] in mer_ids else None

    datasets = [
        {"id": "macro_indicators", "label": "주요 경제 지표 전체", "asset": "macro",
         "canonical": "macro", "data": "economicIndicators",
         "aliases": ["주요 경제 지표 전체 (실시간)", "주요 경제 지표 전체", "주요 경제 지표"]},
        {"id": "market_mood", "label": "시장 분위기", "asset": "sentiment",
         "canonical": "dashboard#mood", "data": "sentiment", "aliases": ["시장 분위기"]},
        {"id": "apt_price_kr", "label": "아파트 가격지수 추이", "asset": "realestate",
         "canonical": "realestate", "data": "realestate.kr",
         "aliases": ["아파트 가격지수 추이", "아파트 가격지수"]},
        {"id": "global_indices", "label": "글로벌 지수", "asset": "index",
         "canonical": "market#index", "data": "indices",
         "aliases": ["글로벌 지수", "글로벌 지수 현황", "글로벌 주요 지수"]},
        {"id": "kospi_movers", "label": "등락 Top10", "asset": "equity",
         "canonical": "market#equity", "data": "stockMovers"},
        {"id": "etf_movers", "label": "ETF 등락", "asset": "equity",
         "canonical": "market#equity", "data": "etfMovers"},
        {"id": "rankings_kr", "label": "거래대금·토스 체결 순위", "asset": "equity",
         "canonical": "market#equity", "data": "rankingsKr"},
        {"id": "investor_trading", "label": "투자자별 순매매", "asset": "flow",
         "canonical": "flow#investor", "data": "investorTrading"},
        {"id": "stock_flows", "label": "종목별 수급·공매도·신용", "asset": "flow",
         "canonical": "flow#stock", "data": "stockFlows"},
        {"id": "nps", "label": "국민연금 자산배분", "asset": "flow",
         "canonical": "flow#nps", "data": "nps",
         "aliases": ["국민연금 자산배분", "자산 배분 현황"]},
        {"id": "lme_inventory", "label": "LME 금속 재고", "asset": "commodity",
         "canonical": "market#commodity", "data": "lmeInventory"},
        {"id": "freight", "label": "해상운임 지수", "asset": "commodity",
         "canonical": "market#commodity", "data": "freight",
         "aliases": ["해상운임 지수", "운송 운임지수 (해상운임)", "운송 운임지수"]},
        {"id": "subscription", "label": "청약 경쟁률", "asset": "realestate",
         "canonical": "realestate#kr", "data": "subscription"},
        {"id": "economic_calendar", "label": "경제 일정", "asset": "macro",
         "canonical": "macro#calendar", "data": "economicCalendar"},
        {"id": "market_calendar_kr", "label": "장 운영 일정", "asset": "macro",
         "canonical": "macro#calendar", "data": "marketCalendarKr"},
        {"id": "climate", "label": "엘니뇨·라니냐", "asset": "commodity",
         "canonical": "market#commodity", "data": "climate"},
        {"id": "news", "label": "뉴스", "asset": "macro", "canonical": "inline",
         "data": "news"},
        {"id": "ai_briefing", "label": "AI 브리핑", "asset": "macro",
         "canonical": "dashboard", "data": "aiBriefing"},
        {"id": "market_halts", "label": "서킷브레이커·사이드카", "asset": "equity",
         "canonical": "global-banner", "data": "marketHalts"},
    ]
    for ds in datasets:
        ds["kind"] = "dataset"
        ds.setdefault("tier", 2)

    for row in rows + datasets:
        mid = mer_id_for(row)
        if mid:
            row["merLens"] = mid
    matched = {r.get("merLens") for r in rows + datasets if r.get("merLens")}
    mer_only = [i for i in mer_ids if i not in matched]
    return rows, datasets, mer_only


def render(rows, datasets, data):
    def js(obj):
        return json.dumps(obj, ensure_ascii=False, sort_keys=False)

    rows = sorted(rows, key=lambda r: (ASSET_ORDER.index(r["asset"]), r["tier"], r["id"]))
    lines = [js(r) for r in rows]
    ds_lines = [js(d) for d in datasets]
    return """/* 지표 레지스트리 — scripts/build_indicators.py 가 생성한다. 직접 고치지 말 것.
 *
 * 한 지표 = 한 행. 화면·분류·중요도를 여기 한 곳에서만 정한다(IA 개편 v3 P0).
 *   asset      자산군 = 1차 네비 축 (index·equity·fx·rate·commodity·macro·realestate·sentiment·flow)
 *   topic      거시 주제 탭 (growth·price·labor·money·trade·demand)
 *   tier       1=대표(홈) 2=주요(자산군 화면) 3=상세 표 전용
 *   canonical  원본 화면. 다른 화면의 같은 값은 요약이며 원본으로 연결한다
 *   news       data.json.news 16주제 중 맥락 한 줄을 뽑을 키
 *   data       data.json 안의 현재값 경로 · series 는 시계열 경로
 *   merLens    mer_signals.json 의 같은 지표 id
 *   onScreen   false = 수집은 되는데 아직 어느 화면에도 없다(처리 대상)
 *
 * 생성 시각 기준 지표 %d · 데이터셋 %d · 미노출 %d.
 */
(function () {
  var ROWS = [
%s
  ];
  var SETS = [
%s
  ];
  var byId = {}, byPath = {}, byName = {};
  ROWS.concat(SETS).forEach(function (r) {
    byId[r.id] = r;
    if (r.data) byPath[r.data] = r;
    (r.alsoData || []).forEach(function (p) { byPath[p] = r; });
    [r.label].concat(r.aliases || []).forEach(function (n) {
      if (n && !byName[n]) byName[n] = r;
    });
  });
  window.ECON_IND = {
    rows: ROWS,
    datasets: SETS,
    get: function (id) { return byId[id] || null; },
    byPath: function (path) { return byPath[path] || null; },
    /* 화면에 쓰인 문자열(라벨·옛 이름)로 행을 찾는다 — 표기 통일의 대조표 */
    find: function (name) { return byName[name] || byId[name] || null; },
    label: function (id, fallback) { return (byId[id] && byId[id].label) || fallback || id; },
    tier: function (n) { return ROWS.filter(function (r) { return r.tier === n; }); },
    asset: function (a) { return ROWS.filter(function (r) { return r.asset === a; }); },
    topic: function (t) { return ROWS.filter(function (r) { return r.topic === t; }); },
    canonicalOf: function (id) { return (byId[id] || {}).canonical || null; },
    newsKeyOf: function (id) { return (byId[id] || {}).news || null; }
  };
})();
""" % (len(rows), len(datasets),
       len([r for r in rows if r.get("onScreen") is False]),
       "\n".join("    " + l + "," for l in lines),
       "\n".join("    " + l + "," for l in ds_lines))


def main():
    check = "--check" in sys.argv
    data = load("data.json")
    mer = load("mer_signals.json")
    rows, datasets, mer_only = build(data, mer)
    text = render(rows, datasets, data)

    problems = []
    for row in rows + datasets:
        if row.get("data") and not has_path(data, row["data"]):
            problems.append("죽은 경로: %s (%s)" % (row["data"], row["id"]))
    on_screen_paths = {r["dataPath"] for r in macro_rows() if r["dataPath"]}
    registry_paths = {r["data"] for r in rows}
    for row in rows:
        registry_paths.update(row.get("alsoData") or [])
    for path in sorted(on_screen_paths - registry_paths):
        problems.append("화면에 있는데 data.json 에 없다(죽은 카드): %s" % path)

    missing = [r for r in rows if r.get("onScreen") is False]
    if check:
        old = io.open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if old != text:
            problems.append("js/app0.js 가 생성 결과와 다르다 — "
                            "python scripts/build_indicators.py 로 재생성할 것")
        for p in problems:
            print("FAIL " + p)
        print("지표 %d · 데이터셋 %d · 미노출 %d · 메르 전용 %d(%s)"
              % (len(rows), len(datasets), len(missing), len(mer_only),
                 ", ".join(sorted(mer_only)) or "-"))
        return 1 if problems else 0

    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("생성 %s — 지표 %d · 데이터셋 %d" % (OUT, len(rows), len(datasets)))
    if missing:
        print("미노출(수집만) %d건:" % len(missing))
        for row in missing:
            print("   %-22s %s" % (row["id"], row["data"]))
    if mer_only:
        print("메르 렌즈 전용 %d건: %s" % (len(mer_only), ", ".join(sorted(mer_only))))
    for p in problems:
        print("경고 " + p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
