"""
매 시간 실행되어 금융 시장 데이터를 수집하고 data.json을 업데이트합니다.

데이터 소스 우선순위:
- 한국 데이터 (KOSPI, KOSDAQ, 채권지수, 금, 석유) : KRX OpenAPI (공식)
- 해외 지수 (S&P, NASDAQ, 닛케이, 상하이)         : yfinance
- 해외 원자재 (Brent, Silver, Copper)             : yfinance
- 환율 (USD/KRW, EUR, JPY 등)                     : open.er-api.com + yfinance
- 미국 경제 지표 (VIX, HY스프레드 등)              : FRED API (무료)
- 한국 경제 지표 (기준금리 등)                     : ECOS API (한국은행)
- 한국 부동산 지수                                 : R-ONE API (한국부동산원)
- 한국 통계 지표                                   : KOSIS API (국가통계포털)

API 키는 모두 GitHub Secrets 에서 환경변수로 주입됩니다.
"""

import json
import os
import sys
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

# ──────────────── API 키 (GitHub Secrets → 환경변수) ────────────────
KRX_API_KEY       = os.environ.get("KRX_API_KEY",       "").strip()
FRED_API_KEY      = os.environ.get("FRED_API_KEY",      "").strip()
ECOS_API_KEY      = os.environ.get("ECOS_API_KEY",      "").strip()
REALESTATE_API_KEY= os.environ.get("REALESTATE_API_KEY","").strip()
KOSIS_API_KEY     = os.environ.get("KOSIS_API_KEY",     "").strip()

KRX_BASE  = "http://data-dbg.krx.co.kr/svc/apis"
FRED_BASE = "https://api.stlouisfed.org/fred"
ECOS_BASE = "https://ecos.bok.or.kr/api"
RONE_BASE = "http://openapi.reb.or.kr/OpenAPI_ToolInstallPackage/service/rest"
KOSIS_BASE= "https://kosis.kr/openapi/statisticsData.do"

FALLBACK = {
    "fx": {
        "USDKRW": {"rate": 1490.00, "change": 0.0},
        "EURKRW": {"rate": 1745.00, "change": 0.0},
        "JPYKRW": {"rate": 10.30,   "change": 0.0},
        "EURUSD": {"rate": 1.1720,  "change": 0.0},
        "USDJPY": {"rate": 144.70,  "change": 0.0},
    },
    "indices": {
        "KOSPI":    {"price": 7600.00,  "change": 0.0},
        "KOSDAQ":   {"price": 1140.00,  "change": 0.0},
        "SP500":    {"price": 5650.00,  "change": 0.0},
        "NASDAQ":   {"price": 26500.00, "change": 0.0},
        "Nikkei":   {"price": 61000.00, "change": 0.0},
        "Shanghai": {"price": 4100.00,  "change": 0.0},
    },
    "commodities": {
        "Gold":   {"price": 3200.00, "change": 0.0},
        "Silver": {"price": 32.50,   "change": 0.0},
        "Copper": {"price": 4.60,    "change": 0.0},
        "WTI":    {"price": 62.00,   "change": 0.0},
        "Brent":  {"price": 65.50,   "change": 0.0},
    },
}


def log(msg):
    print(msg, file=sys.stderr)


def _parse_num(s):
    if s is None:
        return None
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


# ============================================================
# KRX OpenAPI 호출 헬퍼
# ============================================================
def fetch_krx(endpoint, bas_dd):
    if not KRX_API_KEY:
        return None
    try:
        r = requests.get(
            f"{KRX_BASE}{endpoint}",
            params={"basDd": bas_dd},
            headers={"AUTH_KEY": KRX_API_KEY},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        rows = data.get("OutBlock_1") or data.get("OutBlock") or []
        return rows if rows else None
    except Exception as e:
        log(f"[KRX] {endpoint} 오류: {e}")
        return None


def fetch_krx_latest(endpoint, max_lookback=7):
    for offset in range(0, max_lookback):
        dt = datetime.now(KST) - timedelta(days=offset)
        if dt.weekday() >= 5:
            continue
        rows = fetch_krx(endpoint, dt.strftime("%Y%m%d"))
        if rows:
            return rows, dt.strftime("%Y-%m-%d")
    return None, None


def krx_index(endpoint, name_match):
    rows, basd = fetch_krx_latest(endpoint)
    if not rows:
        return None
    for row in rows:
        nm = (row.get("IDX_NM") or row.get("IDX_CLSS") or "").strip()
        if name_match == nm or name_match in nm:
            price = _parse_num(row.get("CLSPRC_IDX"))
            chg_pct = _parse_num(row.get("FLUC_RT"))
            if price and price > 0:
                return {
                    "price": round(price, 2),
                    "change": round(chg_pct or 0.0, 2),
                    "as_of": basd,
                }
    log(f"[KRX] {endpoint}: '{name_match}' 매칭 행 없음 (총 {len(rows)}개 행)")
    return None


def krx_commodity(endpoint, isu_match):
    rows, basd = fetch_krx_latest(endpoint)
    if not rows:
        return None
    matched = None
    for row in rows:
        nm = (row.get("ISU_NM") or row.get("ISU_CD") or "").strip()
        if isu_match == nm:
            matched = row
            break
    if not matched:
        for row in rows:
            nm = (row.get("ISU_NM") or row.get("ISU_CD") or "").strip()
            if isu_match in nm:
                matched = row
                break
    if not matched:
        return None
    price = _parse_num(matched.get("TDD_CLSPRC")) or _parse_num(matched.get("CLSPRC"))
    chg_pct = _parse_num(matched.get("FLUC_RT"))
    if not price or price <= 0:
        return None
    return {
        "price": round(price, 2),
        "change": round(chg_pct or 0.0, 2),
        "as_of": basd,
    }


def fetch_krx_stock_movers(market="kospi", top_n=10):
    """KRX에서 주식 등락률 상위/하위 종목 조회 (상승/하락 Top10)."""
    if not KRX_API_KEY:
        log("[KRX] API 키 없음 — 주식 이동자 폴백 시도")
        return fetch_naver_stock_movers(market=market, top_n=top_n)
    endpoint = "/sto/stk_bydd_trd"  # KOSPI 일별 매매
    if market == "kosdaq":
        endpoint = "/sto/ksq_bydd_trd"  # KOSDAQ (정정: /sto/ksq, /cos/ 아님)
    rows, basd = fetch_krx_latest(endpoint)
    if not rows:
        log(f"[KRX] {endpoint} 데이터 없음 — Naver Finance 폴백 시도")
        return fetch_naver_stock_movers(market=market, top_n=top_n)
    parsed = []
    for row in rows:
        name = row.get("ISU_NM") or row.get("ISU_SRT_CD") or ""
        price = _parse_num(row.get("TDD_CLSPRC") or row.get("CLSPRC"))
        chg_rt = _parse_num(row.get("FLUC_RT"))
        vol = _parse_num(row.get("ACML_VOL"))
        if price and price > 0 and chg_rt is not None:
            parsed.append({"name": name, "price": price, "chg": chg_rt, "vol": vol or 0, "as_of": basd})
    if not parsed:
        log(f"[KRX] {endpoint} 파싱 실패 — Naver Finance 폴백 시도")
        return fetch_naver_stock_movers(market=market, top_n=top_n)
    sorted_asc  = sorted(parsed, key=lambda x: x["chg"])
    sorted_desc = sorted(parsed, key=lambda x: x["chg"], reverse=True)
    gainers = sorted_desc[:top_n]
    losers  = sorted_asc[:top_n]
    log(f"[KRX] {market.upper()} 상승Top{top_n}: {gainers[0]['name']} +{gainers[0]['chg']}%" if gainers else "[KRX] 상승 종목 없음")
    return gainers, losers


def _naver_session():
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Referer": "https://finance.naver.com/",
        "Connection": "close",
    })
    try:
        sess.get("https://finance.naver.com/", timeout=10)
    except Exception:
        pass
    return sess


def fetch_naver_api_movers(market="KOSPI", direction="up", top_n=10):
    """네이버 증권 모바일 JSON API (m.stock.naver.com)로 등락 상위/하위 조회.

    엔드포인트: https://m.stock.naver.com/api/stocks/exchange/{KOSPI|KOSDAQ}/{up|down}?page=1&pageSize=20
    응답 구조: {"stocks": [{"itemCode","stockName","closePrice","fluctuationsRatio", ...}]}
    """
    market = market.upper()
    market = "KOSDAQ" if market == "KOSDAQ" else "KOSPI"
    direction = "up" if direction == "up" else "down"
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://m.stock.naver.com/",
        "Origin":  "https://m.stock.naver.com",
    })
    today = datetime.now(KST).strftime("%Y-%m-%d")
    urls = [
        f"https://m.stock.naver.com/api/stocks/exchange/{market}/{direction}?page=1&pageSize=30",
        f"https://api.stock.naver.com/stock/exchange/{market}/{direction}?page=1&pageSize=30",
    ]
    for url in urls:
        try:
            r = sess.get(url, timeout=15)
            if r.status_code != 200:
                log(f"[NaverAPI] {url} HTTP {r.status_code}")
                continue
            data = r.json()
        except Exception as e:
            log(f"[NaverAPI] {url} 오류: {e}")
            continue
        stocks = data.get("stocks") or data.get("result") or []
        items = []
        for s in stocks:
            name = s.get("stockName") or s.get("name") or s.get("itemName") or ""
            price = _parse_num(s.get("closePrice") or s.get("nowVal") or s.get("currentPrice"))
            chg = _parse_num(s.get("fluctuationsRatio") or s.get("changeRate") or s.get("cttr"))
            vol = _parse_num(s.get("accumulatedTradingVolume") or s.get("aq") or s.get("volume"))
            if name and price and chg is not None:
                items.append({"name": name.strip(), "price": price, "chg": chg, "vol": vol or 0, "as_of": today})
        if items:
            log(f"[NaverAPI] {market} {direction} {len(items)}건 수집 성공 ({url.split('?')[0]})")
            return items[:top_n]
    log(f"[NaverAPI] {market} {direction} 모든 엔드포인트 실패")
    return []


def fetch_naver_stock_movers(market="kospi", top_n=10):
    """네이버 금융 등락률 페이지/모바일 JSON API 통합 폴백.

    1차: m.stock.naver.com JSON API (CORS 친화적, 안정적)
    2차: finance.naver.com HTML 스크래핑 (백업)
    """
    import re as _re
    market_lc = "kosdaq" if market == "kosdaq" else "kospi"
    market_uc = "KOSDAQ" if market == "kosdaq" else "KOSPI"
    sosok = "1" if market == "kosdaq" else "0"
    today = datetime.now(KST).strftime("%Y-%m-%d")

    # 1차: 모바일 JSON API
    gainers = fetch_naver_api_movers(market_uc, "up", top_n)
    losers  = fetch_naver_api_movers(market_uc, "down", top_n)
    if gainers and losers:
        log(f"[Naver] {market_uc} JSON API 성공 → 상승 {len(gainers)}건 / 하락 {len(losers)}건")
        return gainers, losers

    # 2차: HTML 스크래핑 폴백
    log(f"[Naver] {market_uc} JSON API 실패 → HTML 스크래핑 시도")
    sess = _naver_session()

    def _scrape(url):
        try:
            r = sess.get(url, timeout=15)
            if r.status_code != 200:
                log(f"[Naver] {url} HTTP {r.status_code}")
                return []
            r.encoding = "euc-kr"
            html = r.text
        except Exception as e:
            log(f"[Naver] 스크래핑 오류: {e}")
            return []
        items = []
        # 패턴1: <a class="tltle">종목명</a> ... 가격 ... 등락률
        rows_pat = _re.findall(
            r'<a[^>]*class="tltle"[^>]*>([^<]+)</a>'
            r'(?:.*?<td class="number">([\d,\.]+)</td>)'
            r'(?:.*?<span[^>]*>\s*([+\-]?[\d\.]+)%)',
            html, _re.DOTALL)
        for name, price_str, chg_str in rows_pat:
            try:
                price = float(price_str.replace(",", ""))
                chg = float(chg_str)
                items.append({"name": name.strip(), "price": price, "chg": chg, "vol": 0, "as_of": today})
            except (ValueError, TypeError):
                continue
        # 패턴2 (백업): <td class="no">...</td><td><a ...>종목명</a>...</td><td class="number">가격</td>...
        if not items:
            rows_pat2 = _re.findall(
                r'<tr[^>]*onmouseover[^>]*>.*?<a[^>]+>([^<]+)</a>.*?<td class="number">([\d,\.]+)</td>'
                r'.*?<td class="number"[^>]*>.*?([+\-]?[\d\.]+)%',
                html, _re.DOTALL)
            for name, price_str, chg_str in rows_pat2:
                try:
                    price = float(price_str.replace(",", ""))
                    chg = float(chg_str)
                    items.append({"name": name.strip(), "price": price, "chg": chg, "vol": 0, "as_of": today})
                except (ValueError, TypeError):
                    continue
        return items

    if not gainers:
        gainers = _scrape(f"https://finance.naver.com/sise/sise_rise.naver?sosok={sosok}")[:top_n]
    if not losers:
        losers  = _scrape(f"https://finance.naver.com/sise/sise_fall.naver?sosok={sosok}")[:top_n]

    if gainers:
        log(f"[Naver] {market_uc} 상승Top: {gainers[0]['name']} +{gainers[0]['chg']}% ({len(gainers)}건)")
    else:
        log(f"[Naver] {market_uc} 상승 종목 수집 실패")
    if losers:
        log(f"[Naver] {market_uc} 하락Top: {losers[0]['name']} {losers[0]['chg']}% ({len(losers)}건)")
    else:
        log(f"[Naver] {market_uc} 하락 종목 수집 실패")
    return (gainers or None), (losers or None)


def fetch_krx_etf_movers(top_n=10):
    """KRX ETF 등락률 상위/하위 조회. 실패 시 Naver Finance ETF 페이지 폴백."""
    if KRX_API_KEY:
        rows, basd = fetch_krx_latest("/eto/etf_bydd_trd")
        if rows:
            parsed = []
            for row in rows:
                name = row.get("ISU_NM") or ""
                price = _parse_num(row.get("TDD_CLSPRC") or row.get("CLSPRC"))
                chg_rt = _parse_num(row.get("FLUC_RT"))
                if price and price > 0 and chg_rt is not None:
                    parsed.append({"name": name, "price": price, "chg": chg_rt, "as_of": basd})
            if parsed:
                gainers = sorted(parsed, key=lambda x: x["chg"], reverse=True)[:top_n]
                losers  = sorted(parsed, key=lambda x: x["chg"])[:top_n]
                return gainers, losers
    # KRX 실패 → Naver ETF 폴백 (https://finance.naver.com/sise/etf.naver)
    return fetch_naver_etf_movers(top_n)


def fetch_naver_etf_movers(top_n=10):
    """Naver Finance ETF 페이지에서 등락 상위 조회."""
    import re as _re
    today = datetime.now(KST).strftime("%Y-%m-%d")
    sess = _naver_session()
    url = "https://finance.naver.com/api/sise/etfItemList.nhn?etfType=0"
    try:
        r = sess.get(url, timeout=15)
        if r.status_code != 200:
            log(f"[NaverETF] HTTP {r.status_code}")
            return None, None
        data = r.json()
    except Exception as e:
        log(f"[NaverETF] API 오류: {e}")
        return None, None
    rows = data.get("result", {}).get("etfItemList", [])
    parsed = []
    for row in rows:
        name = row.get("itemname") or ""
        price = _parse_num(row.get("nowVal"))
        chg = _parse_num(row.get("changeRate"))
        if name and price and chg is not None:
            parsed.append({"name": name.strip(), "price": price, "chg": chg, "as_of": today})
    if not parsed:
        log(f"[NaverETF] 파싱 결과 0건")
        return None, None
    gainers = sorted(parsed, key=lambda x: x["chg"], reverse=True)[:top_n]
    losers  = sorted(parsed, key=lambda x: x["chg"])[:top_n]
    log(f"[NaverETF] 상위 {top_n}건 수집: 상승 {gainers[0]['name']} +{gainers[0]['chg']}% / 하락 {losers[0]['name']} {losers[0]['chg']}%")
    return gainers, losers


# ============================================================
# FRED API (미국 경제 지표)
# ============================================================
def fetch_fred_series(series_id, limit=1):
    """FRED API에서 시계열 데이터 최신값 조회."""
    if not FRED_API_KEY:
        return None
    try:
        r = requests.get(
            f"{FRED_BASE}/series/observations",
            params={
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "limit": limit,
                "sort_order": "desc",
            },
            timeout=15,
        )
        r.raise_for_status()
        obs = r.json().get("observations", [])
        if not obs:
            return None
        vals = []
        for o in obs:
            v = _parse_num(o.get("value"))
            if v is not None:
                vals.append({"date": o["date"], "value": v})
        return vals if vals else None
    except Exception as e:
        log(f"[FRED] {series_id} 오류: {e}")
        return None


def fetch_fred_latest(series_id):
    """FRED 최신값 (float) 반환."""
    obs = fetch_fred_series(series_id)
    if obs:
        return obs[0]["value"]
    return None


def fetch_fred_economic_indicators():
    """주요 미국 경제 지표 일괄 조회."""
    if not FRED_API_KEY:
        log("[FRED] API 키 없음 — 건너뜀")
        return {}
    indicators = {
        "vix":         ("VIXCLS",         "VIX 변동성 지수"),
        "ff_rate":     ("FEDFUNDS",        "미국 기준금리"),
        "cpi_us":      ("CPIAUCSL",        "미국 CPI (계절조정)"),
        "pce_us":      ("PCEPI",           "미국 PCE"),
        "unemployment":("UNRATE",          "미국 실업률"),
        "gdp_us":      ("GDP",             "미국 GDP (연환산, 조달러)"),
        "hy_spread":   ("BAMLH0A0HYM2",    "HY 크레딧 스프레드"),
        "us10y":       ("GS10",            "미국 10년 국채"),
        "us2y":        ("GS2",             "미국 2년 국채"),
        "dxy_idx":     ("DTWEXBGS",        "달러 인덱스 (브로드)"),
        "m2_us":       ("M2SL",            "미국 M2 통화량"),
    }
    result = {}
    for key, (series_id, desc) in indicators.items():
        obs = fetch_fred_series(series_id, limit=1)
        if obs:
            result[key] = {
                "value": obs[0]["value"],
                "period": obs[0]["date"],
                "desc": desc,
                "source": f"FRED:{series_id}",
            }
            log(f"[FRED] {series_id}: {obs[0]['value']} ({obs[0]['date']})")
        else:
            log(f"[FRED] {series_id}: 데이터 없음")
    return result


def fetch_fred_yield_curve_us():
    """FRED 미국 국채 수익률 곡선 조회 (DGS 시리즈).

    각 만기별 최근 30개 일간 관측치를 받아 현재값 + 약 1개월 전 값을 추출.
    """
    if not FRED_API_KEY:
        log("[FRED-YC] API 키 없음 — 수익률 곡선 건너뜀")
        return None
    terms = [
        ("1M",  "DGS1MO"),
        ("3M",  "DGS3MO"),
        ("6M",  "DGS6MO"),
        ("1Y",  "DGS1"),
        ("2Y",  "DGS2"),
        ("5Y",  "DGS5"),
        ("7Y",  "DGS7"),
        ("10Y", "DGS10"),
        ("20Y", "DGS20"),
        ("30Y", "DGS30"),
    ]
    current, prev_month = [], []
    series_used = []
    for label, sid in terms:
        obs = fetch_fred_series(sid, limit=30)
        if not obs:
            current.append(None)
            prev_month.append(None)
            log(f"[FRED-YC] {sid} ({label}): 데이터 없음")
            continue
        cur = obs[0]["value"]
        # ~1개월 전 (영업일 기준 약 21개) — 부족하면 가장 오래된 값 사용
        pm = obs[21]["value"] if len(obs) > 21 else obs[-1]["value"]
        current.append(cur)
        prev_month.append(pm)
        series_used.append(sid)
        log(f"[FRED-YC] {label}: {cur:.2f}% (1M전 {pm:.2f}%)")
    if not series_used:
        return None
    return {
        "us": {
            "current": current,
            "prev_month": prev_month,
            "source": "FRED: " + ", ".join(series_used),
        }
    }


def fetch_fred_realestate_us():
    """미국 부동산 주요 지표 FRED API로 조회.

    각 series_id가 잘못된 경우를 대비해 fallback 후보를 list로 제공.
    """
    if not FRED_API_KEY:
        log("[FRED] API 키 없음 — 미국 부동산 건너뜀")
        return {}
    # (series_ids list, desc) — 첫 번째가 실패하면 다음 후보 시도
    indicators = {
        "case_shiller_national": (["CSUSHPINSA"],                    "Case-Shiller 전국 HPI"),
        "case_shiller_20city":   (["SPCS20RSA", "SPCS20RPSNSA"],     "Case-Shiller 20대도시 HPI"),
        "mortgage_30y":          (["MORTGAGE30US"],                  "30년 고정 모기지 금리 (%)"),
        "mortgage_15y":          (["MORTGAGE15US"],                  "15년 고정 모기지 금리 (%)"),
        "housing_starts":        (["HOUST"],                          "주택착공 (천 호, 연환산)"),
        "building_permits":      (["PERMIT"],                         "건축허가 (천 건, 연환산)"),
        "existing_home_sales":   (["EXHOSLUSM495S", "EXHOSLUSM495N"], "기존주택판매 (백만 건, 연환산)"),
        "new_home_sales":        (["HSN1F", "HSN1FNSA"],              "신규주택판매 (천 건, 연환산)"),
        "nahb_index":            (["NAHBMMI", "MSACSR"],              "NAHB 주택시장지수"),
    }
    result = {}
    for key, (series_ids, desc) in indicators.items():
        obs = None
        used_id = None
        for sid in series_ids:
            obs = fetch_fred_series(sid, limit=2)
            if obs:
                used_id = sid
                break
            else:
                log(f"[FRED-RE] {sid}: 데이터 없음 (다음 후보 시도)")
        if obs:
            cur = obs[0]["value"]
            prev = obs[1]["value"] if len(obs) > 1 else None
            chg = round((cur - prev) / prev * 100, 2) if prev and prev != 0 else None
            result[key] = {
                "value": cur,
                "prev": prev,
                "chg": chg,
                "period": obs[0]["date"],
                "desc": desc,
                "source": f"FRED:{used_id}",
            }
            log(f"[FRED-RE] {used_id}: {cur} ({obs[0]['date']}) chg={chg}")
        else:
            log(f"[FRED-RE] {key}: 모든 후보 실패")
    log(f"[FRED-RE] 미국 부동산: {len(result)}/{len(indicators)} 지표 수집됨")
    return result


# ============================================================
# ECOS API (한국은행 경제 통계)
# ============================================================
def fetch_ecos_series(stat_code, item_code="", freq="A", start_period=None, end_period=None, limit=5):
    """ECOS API 시계열 데이터 조회."""
    if not ECOS_API_KEY:
        return None
    now = datetime.now(KST)
    if not start_period:
        if freq == "A":
            start_period = str(now.year - limit)
            end_period   = str(now.year)
        elif freq == "M":
            start_period = (now - timedelta(days=30*limit)).strftime("%Y%m")
            end_period   = now.strftime("%Y%m")
        elif freq == "Q":
            y = now.year; q = (now.month-1)//3 + 1
            start_period = f"{y-limit}Q1"
            end_period   = f"{y}Q{q}"
    try:
        url = f"{ECOS_BASE}/StatisticSearch/{ECOS_API_KEY}/json/kr/1/{limit*12}/{stat_code}/{freq}/{start_period}/{end_period}/{item_code}"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        rows = data.get("StatisticSearch", {}).get("row", [])
        return rows if rows else None
    except Exception as e:
        log(f"[ECOS] {stat_code} 오류: {e}")
        return None


def fetch_ecos_economic_indicators():
    """주요 한국 경제 지표 일괄 조회 (ECOS)."""
    if not ECOS_API_KEY:
        log("[ECOS] API 키 없음 — 건너뜀")
        return {}
    result = {}
    # 기준금리 (722Y001 - 한국은행 기준금리)
    rows = fetch_ecos_series("722Y001", "0101000", "M", limit=3)
    if rows:
        latest = rows[-1]
        result["base_rate_kr"] = {
            "value": _parse_num(latest.get("DATA_VALUE")),
            "period": latest.get("TIME"),
            "desc": "한국 기준금리",
            "source": "ECOS:722Y001",
        }
        log(f"[ECOS] 기준금리: {result['base_rate_kr']}")
    # CPI 한국 (901Y009 - 소비자물가지수)
    rows = fetch_ecos_series("901Y009", "0", "M", limit=3)
    if rows:
        latest = rows[-1]
        result["cpi_kr"] = {
            "value": _parse_num(latest.get("DATA_VALUE")),
            "period": latest.get("TIME"),
            "desc": "한국 소비자물가지수",
            "source": "ECOS:901Y009",
        }
        log(f"[ECOS] CPI(한국): {result['cpi_kr']}")
    # GDP 한국 (200Y002 - 실질 GDP 성장률)
    rows = fetch_ecos_series("200Y002", "10101", "Q", limit=4)
    if rows:
        latest = rows[-1]
        result["gdp_kr"] = {
            "value": _parse_num(latest.get("DATA_VALUE")),
            "period": latest.get("TIME"),
            "desc": "한국 실질GDP 성장률(전기비)",
            "source": "ECOS:200Y002",
        }
        log(f"[ECOS] GDP(한국): {result['gdp_kr']}")
    return result


# ============================================================
# R-ONE API (한국부동산원 부동산 가격지수)
# ============================================================
def fetch_realestate_kr():
    """한국부동산원 R-ONE API로 아파트 가격지수 조회."""
    if not REALESTATE_API_KEY:
        log("[R-ONE] API 키 없음 — 건너뜀")
        return {}
    now = datetime.now(KST)
    result = {}
    # 전국 아파트 매매가격지수 (주간)
    try:
        start_ym = (now - timedelta(days=60)).strftime("%Y%m")
        end_ym   = now.strftime("%Y%m")
        r = requests.get(
            f"{RONE_BASE}/AptPriceIndex/getAptPrcIdxByRegion",
            params={
                "serviceKey": REALESTATE_API_KEY,
                "pageNo":     1,
                "numOfRows":  5,
                "startMonth": start_ym,
                "endMonth":   end_ym,
                "regionCode": "00",  # 전국
            },
            timeout=20,
        )
        r.raise_for_status()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.text)
        items = root.findall(".//item")
        if items:
            latest = items[-1]
            result["apt_price_idx_kr"] = {
                "value":  _parse_num(latest.findtext("aptPrcIdx")),
                "period": latest.findtext("yearMonth"),
                "chg":    _parse_num(latest.findtext("aptPrcIdxMoM")),
                "region": "전국",
                "desc":   "전국 아파트 매매가격지수",
                "source": "R-ONE",
            }
            log(f"[R-ONE] 전국 아파트 매매지수: {result['apt_price_idx_kr']}")
    except Exception as e:
        log(f"[R-ONE] 아파트 매매가격지수 오류: {e}")
    # 전세가격지수 (전국)
    try:
        r = requests.get(
            f"{RONE_BASE}/AptPriceIndex/getAptJnsRntPrcIdxByRegion",
            params={
                "serviceKey": REALESTATE_API_KEY,
                "pageNo":     1,
                "numOfRows":  5,
                "startMonth": start_ym,
                "endMonth":   end_ym,
                "regionCode": "00",
            },
            timeout=20,
        )
        r.raise_for_status()
        root = ET.fromstring(r.text)
        items = root.findall(".//item")
        if items:
            latest = items[-1]
            result["jns_price_idx_kr"] = {
                "value":  _parse_num(latest.findtext("aptJnsRntPrcIdx")),
                "period": latest.findtext("yearMonth"),
                "region": "전국",
                "desc":   "전국 아파트 전세가격지수",
                "source": "R-ONE",
            }
            log(f"[R-ONE] 전국 전세가격지수: {result['jns_price_idx_kr']}")
    except Exception as e:
        log(f"[R-ONE] 전세가격지수 오류: {e}")
    return result


# ============================================================
# KOSIS API (국가통계포털)
# ============================================================
def fetch_kosis_series(org_id, table_id, item_id="", period_type="M", start_prd=None, end_prd=None):
    """KOSIS API 통계 데이터 조회."""
    if not KOSIS_API_KEY:
        return None
    now = datetime.now(KST)
    if not start_prd:
        start_prd = (now - timedelta(days=365)).strftime("%Y%m")
    if not end_prd:
        end_prd = now.strftime("%Y%m")
    try:
        params = {
            "method":      "getList",
            "apiKey":      KOSIS_API_KEY,
            "itmId":       item_id,
            "objL1":       item_id,
            "format":      "json",
            "jsonVD":      "Y",
            "userStatsId": "",
            "prdSe":       period_type,
            "startPrdDe":  start_prd,
            "endPrdDe":    end_prd,
            "orgId":       org_id,
            "tblId":       table_id,
        }
        r = requests.get(KOSIS_BASE, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"[KOSIS] {org_id}/{table_id} 오류: {e}")
        return None


# ============================================================
# 환율 (open.er-api.com + yfinance 보강)
# ============================================================
def fetch_fx_spot():
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("result") != "success":
            return None
        rates = data["rates"]
        krw = rates["KRW"]
        eur = rates["EUR"]
        jpy = rates["JPY"]
        return {
            "USDKRW": round(krw, 2),
            "EURKRW": round(krw / eur, 2),
            "JPYKRW": round(krw / jpy, 4),
            "EURUSD": round(1.0 / eur, 4),
            "USDJPY": round(jpy, 2),
        }
    except Exception as e:
        log(f"[FX] open.er-api 오류: {e}")
        return None


def fetch_yf(symbol):
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price = getattr(info, 'last_price', None) or getattr(info, 'regular_market_price', None)
        prev  = getattr(info, 'previous_close', None)
        if price is None:
            hist = ticker.history(period="5d", interval="1d")
            if hist.empty or len(hist) < 1:
                return None
            price = float(hist['Close'].iloc[-1])
            prev  = float(hist['Close'].iloc[-2]) if len(hist) >= 2 else price
        if price and prev and prev != 0:
            change_pct = round((price - prev) / prev * 100, 2)
        else:
            change_pct = 0.0
        return {"price": round(float(price), 2), "change": change_pct}
    except Exception as e:
        log(f"[yfinance] {symbol} 오류: {e}")
        return None


def fetch_fx_change(pair_symbol):
    try:
        res = fetch_yf(pair_symbol)
        return res["change"] if res else 0.0
    except Exception:
        return 0.0


def fetch_yf_history(symbol, period="5y", interval="1d"):
    """yfinance에서 시계열 데이터(historical close prices)를 가져와
    [{"date":"YYYY-MM-DD","close":NUM}, ...] 형식으로 반환.
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval=interval, auto_adjust=False)
        if hist.empty:
            return None
        out = []
        for idx, row in hist.iterrows():
            close = row.get("Close")
            if close is None or (isinstance(close, float) and (close != close)):  # NaN check
                continue
            try:
                date_str = idx.strftime("%Y-%m-%d")
            except Exception:
                date_str = str(idx)[:10]
            out.append({"date": date_str, "close": round(float(close), 4)})
        return out if out else None
    except Exception as e:
        log(f"[yfinance:hist] {symbol} 오류: {e}")
        return None


def fetch_all_historical_data():
    """주요 자산의 5년치 일별 시계열 데이터 일괄 조회.
    data.json 의 history 필드에 저장되어 프런트엔드 차트에서 사용.
    """
    log("[YF-HIST] 시계열 데이터 수집 시작 (5년치 일별 종가)")
    out = {"fx": {}, "indices": {}, "commodities": {}}
    fx_map = {
        "USDKRW": "KRW=X",
        "EURKRW": "EURKRW=X",
        "JPYKRW": "JPYKRW=X",
        "EURUSD": "EURUSD=X",
        "USDJPY": "JPY=X",
    }
    for name, sym in fx_map.items():
        h = fetch_yf_history(sym, period="5y")
        if h:
            out["fx"][name] = h
            log(f"[YF-HIST] FX {name}({sym}): {len(h)} bars")
        else:
            log(f"[YF-HIST] FX {name}({sym}): 데이터 없음")
    idx_map = {
        "KOSPI":    "^KS11",
        "KOSDAQ":   "^KQ11",
        "SP500":    "^GSPC",
        "NASDAQ":   "^IXIC",
        "Nikkei":   "^N225",
        "Shanghai": "000001.SS",
    }
    for name, sym in idx_map.items():
        h = fetch_yf_history(sym, period="5y")
        if h:
            out["indices"][name] = h
            log(f"[YF-HIST] IDX {name}({sym}): {len(h)} bars")
        else:
            log(f"[YF-HIST] IDX {name}({sym}): 데이터 없음")
    com_map = {
        "Gold":   "GC=F",
        "Silver": "SI=F",
        "Copper": "HG=F",
        "WTI":    "CL=F",
        "Brent":  "BZ=F",
    }
    for name, sym in com_map.items():
        h = fetch_yf_history(sym, period="5y")
        if h:
            out["commodities"][name] = h
            log(f"[YF-HIST] COM {name}({sym}): {len(h)} bars")
        else:
            log(f"[YF-HIST] COM {name}({sym}): 데이터 없음")
    log(f"[YF-HIST] 완료: fx={len(out['fx'])}, indices={len(out['indices'])}, commodities={len(out['commodities'])}")
    return out


# ============================================================
# 메인 빌드
# ============================================================
def build_data():
    now = datetime.now(KST)
    data = {
        "lastUpdated": now.isoformat(),
        "sources": {},
        "fx": {},
        "indices": {},
        "commodities": {},
        "stockMovers": {},
        "etfMovers": {},
        "economicIndicators": {},
        "realestate": {},
        "yieldCurve": {},
        "history": {},
    }

    # ── 환율 ────────────────────────────────────────────────
    spot = fetch_fx_spot()
    if spot:
        data["sources"]["fx"] = "open.er-api.com + yfinance"
        data["fx"] = {k: {"rate": v, "change": 0.0} for k, v in spot.items()}
        for pair, sym in [("USDKRW", "USDKRW=X"), ("EURUSD", "EURUSD=X"), ("USDJPY", "USDJPY=X")]:
            chg = fetch_fx_change(sym)
            data["fx"][pair]["change"] = chg
            log(f"[FX] {pair}: {data['fx'][pair]['rate']} ({chg:+.2f}%)")
        data["fx"]["EURKRW"]["change"] = round(
            data["fx"].get("EURUSD", {}).get("change", 0) +
            data["fx"].get("USDKRW", {}).get("change", 0), 2
        )
        data["fx"]["JPYKRW"]["change"] = round(
            data["fx"].get("USDKRW", {}).get("change", 0) -
            data["fx"].get("USDJPY", {}).get("change", 0), 2
        )
    else:
        data["sources"]["fx"] = "fallback"
        data["fx"] = {k: dict(v) for k, v in FALLBACK["fx"].items()}
    log(f"[FX] USDKRW={data['fx'].get('USDKRW')}")

    # ── 한국 지수 (KRX 공식) ──────────────────────────────────
    krx_available = bool(KRX_API_KEY)
    if krx_available:
        log("[KRX] API 키 감지 → 한국 지수·원자재는 KRX 공식 데이터 사용")
        kospi = krx_index("/idx/kospi_dd_trd", "코스피")
        if kospi:
            data["indices"]["KOSPI"] = {"price": kospi["price"], "change": kospi["change"]}
            log(f"[KRX] KOSPI: {kospi['price']} ({kospi['change']:+.2f}%)")
        kosdaq = krx_index("/idx/kosdaq_dd_trd", "코스닥")
        if kosdaq:
            data["indices"]["KOSDAQ"] = {"price": kosdaq["price"], "change": kosdaq["change"]}
            log(f"[KRX] KOSDAQ: {kosdaq['price']} ({kosdaq['change']:+.2f}%)")

        # KOSPI 상승/하락 Top10
        gainers, losers = fetch_krx_stock_movers("kospi", top_n=10)
        if gainers:
            data["stockMovers"]["kospiGainers"] = gainers
        if losers:
            data["stockMovers"]["kospiLosers"] = losers

        # ETF 상승/하락 Top10
        etf_up, etf_down = fetch_krx_etf_movers(top_n=10)
        if etf_up:
            data["etfMovers"]["etfGainers"] = etf_up
        if etf_down:
            data["etfMovers"]["etfLosers"] = etf_down

        data["sources"]["stockMovers"] = "KRX OpenAPI"
    else:
        log("[KRX] API 키 없음 — Naver Finance 폴백 시도")

    # 주식 상승/하락 Top10이 비어 있으면 Naver Finance 폴백 (KRX 권한 미가입 케이스)
    if not data["stockMovers"].get("kospiGainers") or not data["stockMovers"].get("kospiLosers"):
        gainers, losers = fetch_naver_stock_movers(market="kospi", top_n=10)
        if gainers and not data["stockMovers"].get("kospiGainers"):
            data["stockMovers"]["kospiGainers"] = gainers
            data["sources"]["stockMovers"] = "Naver Finance"
        if losers and not data["stockMovers"].get("kospiLosers"):
            data["stockMovers"]["kospiLosers"] = losers

    # ETF 비어 있으면 Naver Finance ETF 폴백
    if not data["etfMovers"].get("etfGainers") or not data["etfMovers"].get("etfLosers"):
        etf_up, etf_down = fetch_naver_etf_movers(top_n=10)
        if etf_up and not data["etfMovers"].get("etfGainers"):
            data["etfMovers"]["etfGainers"] = etf_up
            data["sources"]["etfMovers"] = "Naver Finance"
        if etf_down and not data["etfMovers"].get("etfLosers"):
            data["etfMovers"]["etfLosers"] = etf_down

    # ── 한국 지수 yfinance 폴백 ───────────────────────────────
    if "KOSPI" not in data["indices"]:
        q = fetch_yf("^KS11")
        if q:
            data["indices"]["KOSPI"] = q
            log(f"[yf] KOSPI: {q['price']} ({q['change']:+.2f}%)")
        else:
            data["indices"]["KOSPI"] = dict(FALLBACK["indices"]["KOSPI"])
    if "KOSDAQ" not in data["indices"]:
        q = fetch_yf("^KQ11")
        if q:
            data["indices"]["KOSDAQ"] = q
        else:
            data["indices"]["KOSDAQ"] = dict(FALLBACK["indices"]["KOSDAQ"])

    # ── 해외 지수 (yfinance) ──────────────────────────────────
    intl_indices = {
        "SP500":    "^GSPC",
        "NASDAQ":   "^IXIC",
        "Nikkei":   "^N225",
        "Shanghai": "000001.SS",
    }
    for name, sym in intl_indices.items():
        q = fetch_yf(sym)
        if q:
            data["indices"][name] = q
            log(f"[yf] {name}: {q['price']} ({q['change']:+.2f}%)")
        else:
            data["indices"][name] = dict(FALLBACK["indices"][name])
            log(f"[yf] {name}: fallback 사용")

    data["sources"]["indices"] = (
        "KRX OpenAPI (KR) + yfinance (해외)" if krx_available else "yfinance"
    )

    # ── 원자재: KRX 금·석유 → yfinance ────────────────────────
    if krx_available:
        gold = krx_commodity("/gen/gold_bydd_trd", "금 99.99_1Kg")
        if not gold:
            gold = krx_commodity("/gen/gold_bydd_trd", "금")
        if gold:
            data["commodities"]["GoldKRW"] = {
                "price": gold["price"], "change": gold["change"]
            }
            log(f"[KRX] Gold(KRW/g): {gold['price']} ({gold['change']:+.2f}%)")
        oil = krx_commodity("/gen/oil_bydd_trd", "휘발유")
        if oil:
            data["commodities"]["OilKR"] = {
                "price": oil["price"], "change": oil["change"]
            }
            log(f"[KRX] 휘발유(원/L): {oil['price']} ({oil['change']:+.2f}%)")

    intl_com = {
        "Gold":   "GC=F",
        "Silver": "SI=F",
        "Copper": "HG=F",
        "WTI":    "CL=F",
        "Brent":  "BZ=F",
    }
    for name, sym in intl_com.items():
        q = fetch_yf(sym)
        if q:
            data["commodities"][name] = q
            log(f"[yf] {name}: {q['price']} ({q['change']:+.2f}%)")
        else:
            data["commodities"][name] = dict(FALLBACK["commodities"][name])

    data["sources"]["commodities"] = (
        "KRX OpenAPI (한국 금·석유) + yfinance (국제)" if krx_available else "yfinance"
    )

    # ── FRED 경제 지표 (미국) ─────────────────────────────────
    if FRED_API_KEY:
        log("[FRED] 미국 경제 지표 수집 시작")
        fred_data = fetch_fred_economic_indicators()
        data["economicIndicators"]["us"] = fred_data
        data["sources"]["economicIndicators_us"] = "FRED API (stlouisfed.org)"
        # 미국 부동산 지표
        log("[FRED] 미국 부동산 지표 수집 시작")
        re_us_data = fetch_fred_realestate_us()
        data["realestate"]["us"] = re_us_data
        data["sources"]["realestate_us"] = "FRED API (stlouisfed.org)"
        # 미국 국채 수익률 곡선 (10년물 외 1M~30Y)
        log("[FRED] 미국 국채 수익률 곡선 수집 시작")
        yc_data = fetch_fred_yield_curve_us()
        if yc_data:
            data["yieldCurve"].update(yc_data)
            data["sources"]["yieldCurve_us"] = "FRED API (DGS1MO~DGS30)"
    else:
        log("[FRED] API 키 없음 — 미국 지표 건너뜀")

    # ── ECOS 경제 지표 (한국은행) ─────────────────────────────
    if ECOS_API_KEY:
        log("[ECOS] 한국 경제 지표 수집 시작")
        ecos_data = fetch_ecos_economic_indicators()
        data["economicIndicators"]["kr"] = ecos_data
        data["sources"]["economicIndicators_kr"] = "ECOS API (ecos.bok.or.kr)"
    else:
        log("[ECOS] API 키 없음 — 한국 지표 건너뜀")

    # ── R-ONE 부동산 지표 (한국부동산원) ─────────────────────
    if REALESTATE_API_KEY:
        log("[R-ONE] 한국 부동산 지표 수집 시작")
        re_data = fetch_realestate_kr()
        data["realestate"]["kr"] = re_data
        data["sources"]["realestate_kr"] = "R-ONE API (reb.or.kr)"
    else:
        log("[R-ONE] API 키 없음 — 부동산 지표 건너뜀")

    # ── 시계열 데이터 (FX/지수/원자재 5년치) ──────────────────
    # 프런트엔드 차트가 더미(genSeries) 대신 실제 데이터를 사용하기 위함
    try:
        hist = fetch_all_historical_data()
        if hist:
            data["history"] = hist
            data["sources"]["history"] = "yfinance (FX/Indices/Commodities 5Y daily)"
    except Exception as e:
        log(f"[YF-HIST] 전체 수집 오류: {e}")

    return data


if __name__ == "__main__":
    log("=== 시장 데이터 수집 시작 ===")
    for name, key in [
        ("KRX",        KRX_API_KEY),
        ("FRED",       FRED_API_KEY),
        ("ECOS",       ECOS_API_KEY),
        ("R-ONE",      REALESTATE_API_KEY),
        ("KOSIS",      KOSIS_API_KEY),
    ]:
        if key:
            log(f"[{name}] API 키 설정됨 ({key[:4]}...{key[-4:]})")
        else:
            log(f"[{name}] API 키 없음")
    d = build_data()
    output_path = "data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    log(f"=== 완료: {d['lastUpdated']} → {output_path} ===")
