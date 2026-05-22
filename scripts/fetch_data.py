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
import re
import sys
import time as _time
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

KST = timezone(timedelta(hours=9))

# KIS 토큰 영속 캐시 — GitHub Actions cache 액션이 보관해서 24시간 재사용
KIS_TOKEN_FILE = os.environ.get("KIS_TOKEN_FILE", ".kis_token_cache.json")

# ──────────────── API 키 (GitHub Secrets → 환경변수) ────────────────
KRX_API_KEY       = os.environ.get("KRX_API_KEY",       "").strip()
FRED_API_KEY      = os.environ.get("FRED_API_KEY",      "").strip()
ECOS_API_KEY      = os.environ.get("ECOS_API_KEY",      "").strip()
REALESTATE_API_KEY= os.environ.get("REALESTATE_API_KEY","").strip()
KOSIS_API_KEY     = os.environ.get("KOSIS_API_KEY",     "").strip()
# 신규: 공공데이터포털 통합 키 (data.go.kr) — 국토부 실거래가, 금융위 시세, KOTRA, KOSIS 등 50+ 서비스
DATA_GO_KR_API_KEY= os.environ.get("DATA_GO_KR_API_KEY","").strip()
# 신규: 한국수출입은행 환율·금리 (KOREAEXIM)
EXIM_API_KEY      = os.environ.get("EXIM_API_KEY",      "").strip()
# 신규: 한국투자증권 KIS Developers API — Secrets 에 등록된 키만 사용 (하드코딩 금지)
# 잦은 토큰 발급으로 인한 카카오톡 알람 + 한투 측 이용 제한을 막기 위해 KIS_ENABLED=1
# 로 명시 설정된 경우에만 KIS API 를 호출. 기본은 비활성화 (Naver/pykrx 폴백 사용).
KIS_APP_KEY       = os.environ.get("KIS_APP_KEY",       "").strip()
KIS_APP_SECRET    = os.environ.get("KIS_APP_SECRET",    "").strip()
KIS_ENABLED       = os.environ.get("KIS_ENABLED",       "0").strip() in ("1", "true", "True", "yes")
# 네이버 검색 OpenAPI (developers.naver.com) — 뉴스 검색에 사용 (선택)
NAVER_CLIENT_ID   = os.environ.get("NAVER_CLIENT_ID",   "").strip()
NAVER_CLIENT_SECRET= os.environ.get("NAVER_CLIENT_SECRET","").strip()

KRX_BASE     = "http://data-dbg.krx.co.kr/svc/apis"
KIS_BASE     = "https://openapi.koreainvestment.com:9443"
# 신규: 산업통상자원부 광물자원공사 원자재 가격 (motir.go.kr)
MOTIR_BASE   = "https://www.motir.go.kr"
FRED_BASE    = "https://api.stlouisfed.org/fred"
ECOS_BASE    = "https://ecos.bok.or.kr/api"
# R-ONE 공식 OpenAPI 엔드포인트 (2023~ 신 버전)
RONE_BASE    = "https://www.reb.or.kr/r-one/openapi"
# 구 R-ONE 엔드포인트 (legacy, 일부 시리즈만 응답)
RONE_BASE_LEGACY = "http://openapi.reb.or.kr/OpenAPI_ToolInstallPackage/service/rest"
KOSIS_BASE   = "https://kosis.kr/openapi/statisticsData.do"
DATA_GO_KR_BASE = "http://apis.data.go.kr"
EXIM_BASE       = "https://www.koreaexim.go.kr/site/program/financial/exchangeJSON"

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


# ============================================================
# pykrx — KRX 정보데이터시스템 (data.krx.co.kr) 직접 호출 무인증 라이브러리
# ============================================================
# 한국거래소 공식 KRX OpenAPI(data-dbg.krx.co.kr)는 FLUC_RT 가 0 으로 오는 garbage
# 케이스가 있어 등락률 랭킹이 무력화. pykrx 는 일반 공시 페이지(data.krx.co.kr)를
# 직접 호출하므로 GHA 러너 IP 차단도 없고 데이터 품질이 더 안정적.
# 키 없음 = 누구나 호출 가능 = 카카오톡 알람 없음.
try:
    from pykrx import stock as _pykrx_stock
    _PYKRX_AVAILABLE = True
except ImportError:
    _pykrx_stock = None
    _PYKRX_AVAILABLE = False


def _last_kr_business_day(max_lookback=14):
    """가장 최근 영업일 찾기 — pykrx 가 데이터를 반환하는 첫 평일."""
    for offset in range(max_lookback):
        dt = datetime.now(KST) - timedelta(days=offset)
        if dt.weekday() >= 5:  # 토(5)/일(6) skip
            continue
        yield dt.strftime("%Y%m%d")


def fetch_pykrx_stock_movers(market="KOSPI", top_n=10):
    """pykrx 로 KOSPI/KOSDAQ 등락률 상위/하위 Top10 조회.

    KRX 정보데이터시스템(data.krx.co.kr)에서 직접 가져와 가장 안정적.
    """
    if not _PYKRX_AVAILABLE:
        return None, None
    market = "KOSDAQ" if market.upper() == "KOSDAQ" else "KOSPI"
    for bd in _last_kr_business_day():
        try:
            df = _pykrx_stock.get_market_price_change(bd, bd, market=market)
            if df is None or df.empty:
                continue
            # df 컬럼: 시가/종가/변동폭/등락률/거래량/거래대금 + index = 종목코드
            # 한글 컬럼 우선, 없으면 영문
            chg_col = "등락률" if "등락률" in df.columns else "Change"
            close_col = "종가" if "종가" in df.columns else "Close"
            vol_col = "거래량" if "거래량" in df.columns else "Volume"
            df = df[df[close_col] > 0].copy()
            if df.empty:
                continue
            # 종목명도 함께 가져오기
            try:
                tickers = list(df.index)
                names = {t: _pykrx_stock.get_market_ticker_name(t) for t in tickers[:200]}
            except Exception:
                names = {}
            parsed = []
            iso_date = f"{bd[:4]}-{bd[4:6]}-{bd[6:8]}"
            for code, row in df.iterrows():
                name = names.get(code) or row.get("종목명") or code
                price = float(row[close_col])
                chg = float(row[chg_col])
                vol = float(row.get(vol_col, 0) or 0)
                parsed.append({
                    "name": str(name), "code": str(code), "price": price,
                    "chg": round(chg, 2), "vol": vol, "as_of": iso_date,
                })
            if not parsed:
                continue
            gainers = sorted(parsed, key=lambda x: x["chg"], reverse=True)[:top_n]
            losers = sorted(parsed, key=lambda x: x["chg"])[:top_n]
            log(f"[pykrx] {market} 영업일={bd} 총={len(parsed)}건 → 상승 Top: "
                f"{gainers[0]['name']} {gainers[0]['chg']:+.2f}% / 하락 Top: "
                f"{losers[0]['name']} {losers[0]['chg']:+.2f}%")
            return gainers, losers
        except Exception as e:
            log(f"[pykrx] {market} {bd} 페치 오류: {e}")
            continue
    log(f"[pykrx] {market} 모든 영업일 시도 실패")
    return None, None


def fetch_pykrx_etf_movers(top_n=10):
    """pykrx 로 ETF 등락률 상위/하위 Top10 조회."""
    if not _PYKRX_AVAILABLE:
        return None, None
    for bd in _last_kr_business_day():
        try:
            # ETF 전체 등락률 — get_etf_ohlcv_by_ticker 가 가장 안정적
            tickers = _pykrx_stock.get_etf_ticker_list(bd)
            if not tickers:
                continue
            parsed = []
            iso_date = f"{bd[:4]}-{bd[4:6]}-{bd[6:8]}"
            # 일괄 조회 — get_etf_ohlcv_by_date (개별 ETF), 또는 get_etf_price_change
            try:
                df = _pykrx_stock.get_etf_price_change_by_ticker(bd, bd)
                if df is None or df.empty:
                    raise ValueError("price_change empty")
                chg_col = "등락률" if "등락률" in df.columns else "Change"
                close_col = "종가" if "종가" in df.columns else "Close"
                vol_col = "거래량" if "거래량" in df.columns else "Volume"
                df = df[df[close_col] > 0].copy()
                # 종목명 매핑
                names = {}
                for t in df.index[:200]:
                    try:
                        names[t] = _pykrx_stock.get_etf_ticker_name(t)
                    except Exception:
                        names[t] = t
                for code, row in df.iterrows():
                    parsed.append({
                        "name": str(names.get(code, code)),
                        "code": str(code),
                        "price": float(row[close_col]),
                        "chg": round(float(row[chg_col]), 2),
                        "vol": float(row.get(vol_col, 0) or 0),
                        "as_of": iso_date,
                    })
            except Exception as e:
                log(f"[pykrx] ETF price_change 폴백 → 개별 조회: {e}")
                # 폴백: 개별 ETF OHLCV 로 시계열 변화율 계산
                from_dt = (datetime.strptime(bd, "%Y%m%d") - timedelta(days=10)).strftime("%Y%m%d")
                for t in tickers[:300]:
                    try:
                        d2 = _pykrx_stock.get_etf_ohlcv_by_date(from_dt, bd, t)
                        if d2 is None or len(d2) < 2:
                            continue
                        close = float(d2["NAV"].iloc[-1]) if "NAV" in d2 else float(d2["종가"].iloc[-1])
                        prev = float(d2["NAV"].iloc[-2]) if "NAV" in d2 else float(d2["종가"].iloc[-2])
                        if prev <= 0:
                            continue
                        chg = round((close - prev) / prev * 100, 2)
                        try:
                            name = _pykrx_stock.get_etf_ticker_name(t)
                        except Exception:
                            name = t
                        parsed.append({
                            "name": name, "code": t, "price": close,
                            "chg": chg, "vol": 0, "as_of": iso_date,
                        })
                    except Exception:
                        continue
            if not parsed:
                continue
            gainers = sorted(parsed, key=lambda x: x["chg"], reverse=True)[:top_n]
            losers = sorted(parsed, key=lambda x: x["chg"])[:top_n]
            log(f"[pykrx-ETF] 영업일={bd} 총={len(parsed)}건 → 상승 Top: "
                f"{gainers[0]['name']} {gainers[0]['chg']:+.2f}% / 하락 Top: "
                f"{losers[0]['name']} {losers[0]['chg']:+.2f}%")
            return gainers, losers
        except Exception as e:
            log(f"[pykrx-ETF] {bd} 페치 오류: {e}")
            continue
    log("[pykrx-ETF] 모든 영업일 시도 실패")
    return None, None


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
        code = (row.get("ISU_SRT_CD") or "").strip()
        price = _parse_num(row.get("TDD_CLSPRC") or row.get("CLSPRC"))
        chg_rt = _parse_num(row.get("FLUC_RT"))
        vol = _parse_num(row.get("ACML_VOL"))
        if price and price > 0 and chg_rt is not None:
            parsed.append({"name": name, "code": code, "price": price, "chg": chg_rt, "vol": vol or 0, "as_of": basd})
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


def _get_via_proxies(target_url, headers=None, timeout=15, expect_json=True):
    """대상 URL 을 직접 호출하고, 실패 시 공개 CORS 프록시 여러 개 순차 시도.

    GitHub Actions 러너 IP 가 Naver 등에서 차단되는 케이스 회피 목적.
    반환: 응답 JSON (또는 expect_json=False 일 때 raw text).
    """
    headers = headers or {}
    candidates = [
        target_url,
        f"https://corsproxy.io/?{quote_plus(target_url)}",
        f"https://api.allorigins.win/raw?url={quote_plus(target_url)}",
        f"https://api.codetabs.com/v1/proxy/?quest={quote_plus(target_url)}",
    ]
    for url in candidates:
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code != 200:
                continue
            if expect_json:
                try:
                    return r.json()
                except ValueError:
                    continue
            else:
                return r.text
        except Exception:
            continue
    return None


def fetch_naver_api_movers(market="KOSPI", direction="up", top_n=10):
    """네이버 증권 모바일 JSON API (m.stock.naver.com)로 등락 상위/하위 조회.

    엔드포인트: https://m.stock.naver.com/api/stocks/exchange/{KOSPI|KOSDAQ}/{up|down}?page=1&pageSize=20
    응답 구조: {"stocks": [{"itemCode","stockName","closePrice","fluctuationsRatio", ...}]}

    GHA 러너 IP 차단 회피 — 직접 호출 실패 시 corsproxy.io / allorigins.win / codetabs 순차 시도.
    """
    market = market.upper()
    market = "KOSDAQ" if market == "KOSDAQ" else "KOSPI"
    direction = "up" if direction == "up" else "down"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://m.stock.naver.com/",
        "Origin":  "https://m.stock.naver.com",
    }
    today = datetime.now(KST).strftime("%Y-%m-%d")
    targets = [
        f"https://m.stock.naver.com/api/stocks/exchange/{market}/{direction}?page=1&pageSize=30",
        f"https://api.stock.naver.com/stock/exchange/{market}/{direction}?page=1&pageSize=30",
    ]
    for url in targets:
        data = _get_via_proxies(url, headers=headers, timeout=15, expect_json=True)
        if not data:
            log(f"[NaverAPI] {url} 모든 시도 실패")
            continue
        stocks = data.get("stocks") or data.get("result") or []
        items = []
        for s in stocks:
            name = s.get("stockName") or s.get("name") or s.get("itemName") or ""
            code = (s.get("itemCode") or s.get("code") or "").strip()
            price = _parse_num(s.get("closePrice") or s.get("nowVal") or s.get("currentPrice"))
            chg = _parse_num(s.get("fluctuationsRatio") or s.get("changeRate") or s.get("cttr"))
            vol = _parse_num(s.get("accumulatedTradingVolume") or s.get("aq") or s.get("volume"))
            if name and price and chg is not None:
                items.append({"name": name.strip(), "code": code, "price": price, "chg": chg, "vol": vol or 0, "as_of": today})
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
        # 패턴1: 종목 링크 (코드 포함) + 가격 + 등락률 + 거래량
        # <a href="/item/main.naver?code=NNNNNN" class="tltle">종목명</a>
        # <td class="number">가격</td> <td>...</td> ... <span>±N.NN%</span> ... <td class="number">거래량</td>
        rows_pat = _re.findall(
            r'<a\s+href="/item/main\.naver\?code=(\d+)"[^>]*class="tltle"[^>]*>([^<]+)</a>'
            r'(.*?)</tr>',
            html, _re.DOTALL)
        for code, name, rest in rows_pat:
            # rest 안에서 가격/등락률/거래량 추출
            numbers = _re.findall(r'<td[^>]*class="number"[^>]*>([^<]+)</td>', rest)
            chg_match = _re.search(r'([+\-]?[\d.]+)%', rest)
            if len(numbers) < 2 or not chg_match: continue
            try:
                price = float(numbers[0].replace(",", "").strip())
                chg = float(chg_match.group(1))
                # 거래량은 보통 5번째 number 컬럼 (가격, 전일비, 등락률, 매도호가, 거래량…)
                vol = 0
                for n in numbers[2:]:
                    cleaned = n.replace(",", "").strip()
                    if cleaned.isdigit():
                        v = int(cleaned)
                        if v > 100:  # 의미 있는 거래량(>100주)
                            vol = v
                            break
                items.append({"name": name.strip(), "code": code, "price": price, "chg": chg, "vol": vol, "as_of": today})
            except (ValueError, TypeError):
                continue
        # 패턴2 (구식): <a class="tltle">종목명</a> 만 (코드 없음)
        if not items:
            rows_pat = _re.findall(
                r'<a[^>]*class="tltle"[^>]*>([^<]+)</a>'
                r'(?:.*?<td class="number">([\d,\.]+)</td>)'
                r'(?:.*?<span[^>]*>\s*([+\-]?[\d\.]+)%)',
                html, _re.DOTALL)
            for name, price_str, chg_str in rows_pat:
                try:
                    price = float(price_str.replace(",", ""))
                    chg = float(chg_str)
                    items.append({"name": name.strip(), "code": "", "price": price, "chg": chg, "vol": 0, "as_of": today})
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
    """KRX ETF 등락률 상위/하위 조회. 실패 또는 모든 등락률 0% 시 Naver Finance 폴백."""
    if KRX_API_KEY:
        rows, basd = fetch_krx_latest("/eto/etf_bydd_trd")
        if rows:
            parsed = []
            for row in rows:
                name = row.get("ISU_NM") or ""
                code = (row.get("ISU_SRT_CD") or "").strip()
                price = _parse_num(row.get("TDD_CLSPRC") or row.get("CLSPRC"))
                chg_rt = _parse_num(row.get("FLUC_RT"))
                # FLUC_RT 가 0 또는 누락된 경우 CMPPREVDD_PRC (전일대비)와 가격으로 직접 계산
                if (chg_rt is None or chg_rt == 0) and price:
                    diff = _parse_num(row.get("CMPPREVDD_PRC"))
                    if diff is not None and (price - diff) > 0:
                        chg_rt = round(diff / (price - diff) * 100, 2)
                if price and price > 0 and chg_rt is not None:
                    parsed.append({"name": name, "code": code, "price": price, "chg": chg_rt, "as_of": basd})
            if parsed:
                # 모든 등락률이 0이면 데이터가 오래된 것 — Naver 폴백
                non_zero = [p for p in parsed if p["chg"] != 0]
                if len(non_zero) >= 3:
                    gainers = sorted(parsed, key=lambda x: x["chg"], reverse=True)[:top_n]
                    losers  = sorted(parsed, key=lambda x: x["chg"])[:top_n]
                    log(f"[KRX-ETF] {len(parsed)}건 (비영점 {len(non_zero)}건) - {basd}")
                    return gainers, losers
                else:
                    log(f"[KRX-ETF] 등락률 0% 우세 ({len(non_zero)}/{len(parsed)}) - Naver 폴백")
    # KRX 실패 → Naver ETF 폴백
    return fetch_naver_etf_movers(top_n)


def fetch_naver_etf_movers(top_n=10):
    """Naver Finance ETF 페이지에서 등락 상위 조회.

    여러 엔드포인트를 시도하여 등락률을 안정적으로 수집:
    1) finance.naver.com/api/sise/etfItemList.nhn (전통 API)
    2) m.stock.naver.com/api/stocks/etf/domesticEtfList (모바일 신 API)
    3) finance.naver.com/sise/etf.naver HTML 스크래핑

    GHA IP 차단 회피 — 모든 엔드포인트를 CORS 프록시로도 시도.
    """
    today = datetime.now(KST).strftime("%Y-%m-%d")
    desktop_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://finance.naver.com/",
    }
    mobile_headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                      "(KHTML, like Gecko) Mobile/15E148 Safari/604.1",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://m.stock.naver.com/",
    }

    # 시도 1: 전통 API (직접 + 프록시)
    data = _get_via_proxies(
        "https://finance.naver.com/api/sise/etfItemList.nhn?etfType=0",
        headers=desktop_headers, timeout=15, expect_json=True,
    )
    if data:
        rows = data.get("result", {}).get("etfItemList", [])
        parsed = []
        for row in rows:
            name = row.get("itemname") or ""
            code = (row.get("itemcode") or "").strip()
            price = _parse_num(row.get("nowVal"))
            chg = _parse_num(row.get("changeRate"))
            if chg is None or chg == 0:
                chg_val = _parse_num(row.get("changeVal"))
                if chg_val is not None and price and price > 0:
                    chg = round(chg_val / (price - chg_val) * 100, 2) if (price - chg_val) > 0 else 0.0
            if name and price:
                parsed.append({"name": name.strip(), "code": code, "price": price, "chg": chg or 0.0, "as_of": today})
        if parsed:
            non_zero = [p for p in parsed if p["chg"] != 0]
            if len(non_zero) >= 3:
                gainers = sorted(parsed, key=lambda x: x["chg"], reverse=True)[:top_n]
                losers  = sorted(parsed, key=lambda x: x["chg"])[:top_n]
                log(f"[NaverETF] 1차(전통 API) 성공: {len(parsed)}건 (non-zero {len(non_zero)})")
                return gainers, losers
            log(f"[NaverETF] 1차 등락률 모두 0 — 다음 endpoint 시도")

    # 시도 2: 모바일 신 API (직접 + 프록시)
    data = _get_via_proxies(
        "https://m.stock.naver.com/api/stocks/etf/domesticEtfList?category=domestic&page=1&pageSize=200",
        headers=mobile_headers, timeout=15, expect_json=True,
    )
    if data:
        rows = data.get("stocks") or data.get("result", {}).get("stocks") or []
        parsed = []
        for row in rows:
            name = row.get("stockName") or row.get("itemName") or ""
            code = (row.get("itemCode") or "").strip()
            price = _parse_num(row.get("closePrice") or row.get("nowVal"))
            chg = _parse_num(row.get("fluctuationsRatio") or row.get("changeRate"))
            if name and price and chg is not None:
                parsed.append({"name": name.strip(), "code": code, "price": price, "chg": chg, "as_of": today})
        if parsed:
            non_zero = [p for p in parsed if p["chg"] != 0]
            if len(non_zero) >= 3:
                gainers = sorted(parsed, key=lambda x: x["chg"], reverse=True)[:top_n]
                losers  = sorted(parsed, key=lambda x: x["chg"])[:top_n]
                log(f"[NaverETF] 2차(모바일) 성공: {len(parsed)}건")
                return gainers, losers

    # 시도 3: 다른 모바일 엔드포인트 (구조 변경 대비)
    data = _get_via_proxies(
        "https://m.stock.naver.com/api/stocks/etf/domestic?category=domestic&page=1&pageSize=200",
        headers=mobile_headers, timeout=15, expect_json=True,
    )
    if data:
        rows = data.get("stocks") or data.get("result", {}).get("stocks") or []
        parsed = []
        for row in rows:
            name = row.get("stockName") or row.get("itemName") or ""
            code = (row.get("itemCode") or "").strip()
            price = _parse_num(row.get("closePrice") or row.get("nowVal"))
            chg = _parse_num(row.get("fluctuationsRatio") or row.get("changeRate"))
            if name and price and chg is not None:
                parsed.append({"name": name.strip(), "code": code, "price": price, "chg": chg, "as_of": today})
        if parsed:
            non_zero = [p for p in parsed if p["chg"] != 0]
            if len(non_zero) >= 3:
                gainers = sorted(parsed, key=lambda x: x["chg"], reverse=True)[:top_n]
                losers  = sorted(parsed, key=lambda x: x["chg"])[:top_n]
                log(f"[NaverETF] 3차(대체 모바일) 성공: {len(parsed)}건")
                return gainers, losers

    log(f"[NaverETF] 모든 endpoint 실패 또는 등락률 0")
    return None, None


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
    """주요 미국 경제 지표 일괄 조회 (최신 값 + 24개 시점 시계열)."""
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
        # ⚠ DXY 는 FRED 에 없음. 아래는 Broad Dollar Index (참고용, 1월 2006=100 베이스).
        # 실제 DXY (1973=100, ICE 발표) 는 fetch_dxy_from_yf() 가 yfinance 로 별도 페치.
        "broad_dollar":("DTWEXBGS",        "달러 인덱스 (브로드, 2006=100)"),
        "m2_us":       ("M2SL",            "미국 M2 통화량"),
    }
    # 시리즈별 빈도에 맞는 limit (분기/연 단위 차트 표시 위해 5년치 이상 확보)
    # daily 시리즈: 1300 (≈5년), monthly: 60 (5년), quarterly: 20 (5년)
    FRED_LIMITS = {
        # daily series
        "vix":         1300,
        "hy_spread":   1300,
        "us10y":       60,   # GS10 is monthly
        "us2y":        60,
        "ff_rate":     60,
        "broad_dollar":1300, # DTWEXBGS is daily — 5y history for chart
        # monthly series
        "cpi_us":      60,
        "pce_us":      60,
        "unemployment":60,
        "m2_us":       60,
        # quarterly series
        "gdp_us":      20,
    }
    result = {}
    for key, (series_id, desc) in indicators.items():
        limit = FRED_LIMITS.get(key, 60)
        obs = fetch_fred_series(series_id, limit=limit)
        if obs:
            history = {o["date"]: o["value"] for o in obs}
            result[key] = {
                "value": obs[0]["value"],
                "period": obs[0]["date"],
                "desc": desc,
                "source": f"FRED:{series_id}",
                "history": history,
            }
            log(f"[FRED] {series_id}: {obs[0]['value']} ({obs[0]['date']}) +{len(history)}점 시계열")
        else:
            log(f"[FRED] {series_id}: 데이터 없음")
    return result


# ─── FRED 국제 시리즈 (일본/유로존/중국/독일/영국) ──────────────
# FRED 의 international 데이터는 OECD/IMF/Eurostat 가 원본인 경우가 많음.
# 각 시리즈 id 는 fred.stlouisfed.org/searchresults 에서 확인.
FRED_INTL_INDICATORS = {
    "jp": {
        "cpi":          ("JPNCPIALLMINMEI",  "일본 CPI (전체, 2015=100)"),
        "gdp":          ("JPNRGDPEXP",       "일본 실질GDP (분기, 십억엔)"),
        "unemployment": ("LRUN64TTJPM156S",  "일본 실업률 (15-64세, 계절조정)"),
        "base_rate":    ("INTDSRJPM193N",    "일본 정책금리 (할인율)"),
    },
    "eu": {
        "cpi":          ("CP0000EZ19M086NEST", "유로존 HICP (전체)"),
        "gdp":          ("CLVMNACSCAB1GQEA19", "유로존 실질GDP (백만유로)"),
        "unemployment": ("LRHUTTTTEZM156S",  "유로존 실업률 (계절조정)"),
        "base_rate":    ("ECBDFR",            "ECB 예금금리"),
    },
    "cn": {
        "cpi":          ("CHNCPIALLMINMEI",   "중국 CPI (전체, 2015=100)"),
        "gdp":          ("MKTGDPCNA646NWDB",  "중국 GDP (USD)"),
        "ip":           ("CHNPROINDMISMEI",   "중국 산업생산지수"),
    },
    "de": {
        "cpi":          ("DEUCPIALLMINMEI",   "독일 CPI"),
        "gdp":          ("CLVMNACSCAB1GQDE",  "독일 실질GDP"),
        "unemployment": ("LRHUTTTTDEM156S",   "독일 실업률"),
    },
    "uk": {
        "cpi":          ("GBRCPIALLMINMEI",   "영국 CPI"),
        "gdp":          ("CLVMNACSCAB1GQUK",  "영국 실질GDP"),
        "unemployment": ("LRHUTTTTGBM156S",   "영국 실업률"),
        "base_rate":    ("IRSTCB01GBM156N",   "영국 BOE 정책금리"),
    },
}


def fetch_fred_intl_indicators():
    """FRED 의 OECD/Eurostat/IMF 국제 시리즈에서 일본·유로존·중국·독일·영국 핵심 지표 조회 (시계열 포함)."""
    if not FRED_API_KEY:
        return {}
    out = {}
    for cc, ind_map in FRED_INTL_INDICATORS.items():
        cc_data = {}
        for key, (series_id, desc) in ind_map.items():
            # 국제 시리즈는 대부분 월간이므로 limit=60 (5년)
            obs = fetch_fred_series(series_id, limit=60)
            if obs:
                history = {o["date"]: o["value"] for o in obs}
                cc_data[f"{key}_{cc}"] = {
                    "value": obs[0]["value"],
                    "period": obs[0]["date"],
                    "desc": desc,
                    "source": f"FRED:{series_id}",
                    "history": history,
                }
                log(f"[FRED-INTL:{cc.upper()}] {series_id}: {obs[0]['value']} ({obs[0]['date']}) +{len(history)}점")
            else:
                log(f"[FRED-INTL:{cc.upper()}] {series_id}: 데이터 없음")
        if cc_data:
            out[cc] = cc_data
    return out


def fetch_fred_yield_curve_us():
    """FRED 미국 국채 수익률 곡선 조회 (DGS 시리즈).

    각 만기별 최근 252영업일(약 1년) 관측치를 받아:
    - current: 최신 종가
    - prev_month: 1개월 전 (~21영업일)
    - series: 시계열 [{date, value}, ...] - 채권 차트용
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
    series_data = []  # 각 만기별 시계열
    for label, sid in terms:
        obs = fetch_fred_series(sid, limit=252)  # ~1년
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
        # 시계열을 오래된 → 최신 순으로 저장 (차트용)
        series_data.append({
            "tenor": label,
            "label": label,
            "fred_id": sid,
            "data": [{"date": o["date"], "value": o["value"]} for o in reversed(obs)],
        })
        log(f"[FRED-YC] {label}: {cur:.2f}% (1M전 {pm:.2f}%) - {len(obs)}일 시계열")
    if not series_used:
        return None
    return {
        "us": {
            "current": current,
            "prev_month": prev_month,
            "series": series_data,
            "source": "FRED: " + ", ".join(series_used),
        }
    }


def fetch_ecos_yield_curve_kr():
    """한국은행 ECOS API 로 한국 국고채 수익률 곡선 조회.

    시장금리 일별 (817Y002) — 주요 만기:
    - 010190000: 국고채(1년)
    - 010195000: 국고채(3년)
    - 010200000: 국고채(5년)
    - 010210000: 국고채(10년)
    - 010220000: 국고채(20년)
    - 010230000: 국고채(30년)
    - 010300000: 회사채(3년 AA-)
    - 010301000: 회사채(3년 BBB-)

    yieldCurveData.kr 의 terms 인덱스(['1M','3M','6M','1Y','2Y','5Y','7Y','10Y','20Y','30Y'])
    에 맞춰 데이터를 채움. 미수집 만기는 None.
    """
    if not ECOS_API_KEY:
        log("[ECOS-YC] API 키 없음 — 한국 국채 수익률 곡선 건너뜀")
        return None
    # (yieldCurveData.kr.terms 인덱스, ECOS item_code, label)
    # 1M/3M/6M/2Y/7Y 는 ECOS에 직접 없음 → 1Y, 3Y, 5Y, 10Y, 20Y, 30Y 만 수집
    terms_map = [
        (3, "010190000", "1Y"),
        (5, "010195000", "3Y"),  # 3Y → 2Y 슬롯에 매핑 (인덱스 4)
        (5, "010200000", "5Y"),
        (7, "010210000", "10Y"),
        (8, "010220000", "20Y"),
        (9, "010230000", "30Y"),
    ]
    # yield curve 10개 슬롯 초기화
    current    = [None] * 10
    prev_month = [None] * 10
    series_data = []
    series_used = []
    # ECOS 시장금리는 일별 (D)
    now = datetime.now(KST)
    end_period = now.strftime("%Y%m%d")
    # 1년치 (약 252 영업일)
    start_period = (now - timedelta(days=400)).strftime("%Y%m%d")
    for slot, item_code, label in terms_map:
        try:
            url = f"{ECOS_BASE}/StatisticSearch/{ECOS_API_KEY}/json/kr/1/600/817Y002/D/{start_period}/{end_period}/{item_code}"
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            rows = r.json().get("StatisticSearch", {}).get("row", [])
            if not rows:
                log(f"[ECOS-YC] {label} (item={item_code}): 데이터 없음")
                continue
            # TIME 오름차순 정렬 (오래된 → 최신)
            rows_sorted = sorted(rows, key=lambda x: x.get("TIME", ""))
            # 최신값
            latest = rows_sorted[-1]
            cur_val = _parse_num(latest.get("DATA_VALUE"))
            # 1개월 전 (영업일 기준 ~21번째 뒤에서부터)
            prev_val = None
            if len(rows_sorted) > 21:
                prev_val = _parse_num(rows_sorted[-22].get("DATA_VALUE"))
            else:
                prev_val = _parse_num(rows_sorted[0].get("DATA_VALUE"))
            if cur_val is None:
                continue
            # yieldCurveData.kr 슬롯에 매핑 (단, 같은 슬롯에 두 번 쓰면 후자가 덮어씀)
            # 3Y는 slot 4(2Y) 에 매핑하지 않고 별도 처리 → 5Y 우선 채우기 후 3Y 폴백
            if label == "3Y":
                # 3Y → 2Y 슬롯 (terms_idx=4) — 3Y 값이 2Y 보다 약간 높음
                if current[4] is None:
                    current[4]    = round(cur_val, 3)
                    prev_month[4] = round(prev_val, 3) if prev_val is not None else None
                continue
            current[slot]    = round(cur_val, 3)
            prev_month[slot] = round(prev_val, 3) if prev_val is not None else None
            # 시계열 데이터 (차트용)
            ts = []
            for row in rows_sorted[-252:]:  # 최근 1년
                v = _parse_num(row.get("DATA_VALUE"))
                t = row.get("TIME")
                if v is not None and t and len(t) == 8:
                    # YYYYMMDD → YYYY-MM-DD
                    ts.append({"date": f"{t[:4]}-{t[4:6]}-{t[6:8]}", "value": v})
            if ts:
                series_data.append({
                    "tenor": label,
                    "label": label,
                    "ecos_item": item_code,
                    "data": ts,
                })
            series_used.append(f"{label}({item_code})")
            log(f"[ECOS-YC] {label}: {cur_val:.3f}% (1M전 {prev_val if prev_val is None else f'{prev_val:.3f}'}%) — {len(ts)}일 시계열")
        except Exception as e:
            log(f"[ECOS-YC] {label} (item={item_code}) 오류: {e}")
            continue
    if not series_used:
        log("[ECOS-YC] 한국 국채 데이터 없음 — yieldCurve.kr 미갱신")
        return None
    return {
        "kr": {
            "current": current,
            "prev_month": prev_month,
            "series": series_data,
            "source": "ECOS API (817Y002): " + ", ".join(series_used),
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
        # 부동산 지표는 대부분 월간 → 60개월(5년) 시계열
        for sid in series_ids:
            obs = fetch_fred_series(sid, limit=60)
            if obs:
                used_id = sid
                break
            else:
                log(f"[FRED-RE] {sid}: 데이터 없음 (다음 후보 시도)")
        if obs:
            cur = obs[0]["value"]
            prev = obs[1]["value"] if len(obs) > 1 else None
            chg = round((cur - prev) / prev * 100, 2) if prev and prev != 0 else None
            history = {o["date"]: o["value"] for o in obs}
            result[key] = {
                "value": cur,
                "prev": prev,
                "chg": chg,
                "period": obs[0]["date"],
                "desc": desc,
                "source": f"FRED:{used_id}",
                "history": history,
            }
            log(f"[FRED-RE] {used_id}: {cur} ({obs[0]['date']}) chg={chg} +{len(history)}점")
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


def _ecos_latest(stat_code, item_code, freq, desc, source_id, limit=60):
    """ECOS 단일 시계열 최신값 + 60개월/분기/연 히스토리 조회 헬퍼.
    limit 60 → 월간이면 5년, 분기면 15년, 연이면 60년 (분기/연 차트 적절 표시).
    """
    rows = fetch_ecos_series(stat_code, item_code, freq, limit=limit)
    if not rows:
        return None
    # 최신값이 가장 뒤일 수도, 앞일 수도 있으므로 TIME 기준 정렬
    rows_sorted = sorted(rows, key=lambda r: r.get("TIME", ""))
    latest = rows_sorted[-1]
    val = _parse_num(latest.get("DATA_VALUE"))
    if val is None:
        return None
    # 히스토리 (모든 관측값)
    history = {}
    for row in rows_sorted:
        t = row.get("TIME")
        v = _parse_num(row.get("DATA_VALUE"))
        if t and v is not None:
            history[t] = v
    return {
        "value": val,
        "period": latest.get("TIME"),
        "desc": desc,
        "source": f"ECOS:{source_id}",
        "history": history,
    }


def _ecos_try_multi(stat_codes, items, freq, desc, source_id):
    """여러 stat_code × item_code 조합을 시도해서 성공한 첫 번째 결과를 반환.
    각 ECOS 시리즈는 시기에 따라 코드 체계가 변경되거나 신·구 코드가 공존함.
    """
    if isinstance(stat_codes, str): stat_codes = [stat_codes]
    if isinstance(items, str): items = [items]
    for stat in stat_codes:
        for item in items:
            r = _ecos_latest(stat, item, freq, desc, source_id)
            if r:
                return r, stat, item
    return None, None, None


def fetch_ecos_economic_indicators():
    """주요 한국 경제 지표 일괄 조회 (ECOS).

    각 ECOS 시리즈 ID 는 ECOS 통계지원 > 통계조회 페이지에서 확인. 잘못된 항목 코드는
    데이터 0건으로 회신되므로 정상 응답이 오는 시리즈만 결과에 포함.
    여러 stat × item 조합을 시도하여 ECOS 정책 변경에도 대응.
    """
    if not ECOS_API_KEY:
        log("[ECOS] API 키 없음 — 건너뜀")
        return {}
    result = {}
    # ─── 통화·금리 ───
    r = _ecos_latest("722Y001", "0101000", "M", "한국 기준금리", "722Y001")
    if r: result["base_rate_kr"] = r; log(f"[ECOS] 기준금리: {r['value']} ({r['period']})")

    # ─── 물가 ───
    r = _ecos_latest("901Y009", "0", "M", "한국 소비자물가지수", "901Y009")
    if r: result["cpi_kr"] = r; log(f"[ECOS] CPI: {r['value']} ({r['period']})")

    # PPI - 생산자물가지수 (404Y014) — 총지수 item 코드 후보 여럿 시도
    r, _, used_item = _ecos_try_multi(
        ["404Y014"],
        ["1010000", "*AA", "T00000", "0000", "X1AA", "AA0000"],
        "M", "한국 생산자물가지수", "404Y014",
    )
    if r:
        result["ppi_kr"] = r
        log(f"[ECOS] PPI: {r['value']} ({r['period']}) item={used_item}")

    # ─── 경기 ───
    # GDP 성장률 (전기비 또는 전년동기비)
    # 200Y001 (실질GDP, 분기, 원계열 = 100), 200Y002 (계절조정), 200Y005 (성장률)
    # item code: 10101 (GDP), 10111 (GDP, 계절조정), AAA (전체)
    r, used_stat, used_item = _ecos_try_multi(
        ["200Y104", "200Y005", "200Y002", "200Y001"],
        ["10101", "10111", "1000", "0000", "AAA", "GDP"],
        "Q", "한국 실질GDP 성장률(전기비)", "GDP",
    )
    if r:
        r["source"] = f"ECOS:{used_stat}"
        result["gdp_kr"] = r
        log(f"[ECOS] GDP: {r['value']} ({r['period']}) stat={used_stat} item={used_item}")

    # 산업생산지수 - 901Y033 (광공업생산지수) / 901Y043 (제조업)
    # ECOS 통계기준 변경으로 코드가 자주 바뀌므로 여러 조합 시도
    r, used_stat, used_item = _ecos_try_multi(
        ["901Y033", "901Y055", "901Y034"],
        ["I61BC", "A00", "AAA", "0", "1", "I61B", "I61BC1"],
        "M", "한국 광공업생산지수", "IP",
    )
    if r:
        r["source"] = f"ECOS:{used_stat}"
        result["ip_kr"] = r
        log(f"[ECOS] 산업생산: {r['value']} ({r['period']}) stat={used_stat} item={used_item}")

    # 소매판매 - 901Y028 (서비스업 동향) / 901Y055 (소매판매액지수)
    r, used_stat, used_item = _ecos_try_multi(
        ["901Y028", "901Y055", "901Y027"],
        ["I71BC", "RT00", "A00", "AAA", "0", "1", "I71BC1"],
        "M", "한국 소매판매액지수", "RETAIL",
    )
    if r:
        r["source"] = f"ECOS:{used_stat}"
        result["retail_kr"] = r
        log(f"[ECOS] 소매판매: {r['value']} ({r['period']}) stat={used_stat} item={used_item}")

    # ─── 고용 ───
    # 실업률 - 901Y027 (경제활동인구).
    # ⚠ 주의: I61EC = 고용률(%) 약 62%, I61G/I61F = 실업률(%) 약 3%
    # 값 범위로 판단하여 실업률만 채택 (0~10% 범위)
    # 후보 item 코드 시도 후 값이 0~15 범위에 들어오는 것만 채택
    candidates = ["I61G", "I61F", "I61BB", "I61EAA", "I61CA"]
    chosen = None
    for item in candidates:
        r = _ecos_latest("901Y027", item, "M", "한국 실업률 (계절조정)", "UNEMP")
        if r and r.get("value") is not None and 0 < r["value"] < 15:
            chosen = (r, item)
            break
    if chosen:
        r, used_item = chosen
        r["source"] = "ECOS:901Y027"
        result["unemployment_kr"] = r
        log(f"[ECOS] 실업률: {r['value']}% ({r['period']}) item={used_item}")
    else:
        # 백업: 200Y004 (취업·실업·근로) 시리즈
        r = _ecos_latest("200Y004", "1010000", "M", "한국 실업률", "UNEMP")
        if r and 0 < (r.get("value") or 0) < 15:
            result["unemployment_kr"] = r
            log(f"[ECOS] 실업률 (200Y004): {r['value']}%")

    # ─── 무역 ───
    # 경상수지 - 301Y013. item: 000000 (전체)
    r = _ecos_latest("301Y013", "000000", "M", "한국 경상수지 (백만달러)", "301Y013")
    if r: result["current_account_kr"] = r; log(f"[ECOS] 경상수지: {r['value']} ({r['period']})")

    # 수출 - 관세청 통관 (백만달러) - 901Y011 (수출입물량/금액지수) or 401Y013/401Y014 (실제 수출액)
    r, used_stat, used_item = _ecos_try_multi(
        ["401Y014", "401Y013", "401Y015", "401Y016", "901Y011"],
        ["AAA", "EXP", "000", "1000", "FIEED", "A0000"],
        "M", "한국 수출금액 (백만달러)", "EXPORTS",
    )
    if r:
        r["source"] = f"ECOS:{used_stat}"
        result["exports_kr"] = r
        log(f"[ECOS] 수출: {r['value']} ({r['period']}) stat={used_stat} item={used_item}")

    # ─── 부동산 (KR) ──────────────────────────────────────────
    # 주담대 평균금리 - 121Y006 (예금은행 가중평균금리), item: 종류별 코드
    r, used_stat, used_item = _ecos_try_multi(
        ["121Y006", "121Y013"],
        ["BECBLA01", "BECBLA02", "BECBLA0301", "BB001", "BHBLA"],
        "M", "한국 주담대 평균금리 (신규)", "MORT_RATE",
    )
    if r:
        r["source"] = f"ECOS:{used_stat}"
        result["mortgage_rate_kr"] = r
        log(f"[ECOS] 주담대 금리: {r['value']} ({r['period']}) item={used_item}")

    # 가계신용 잔액 - 151Y005 (가계신용)
    r, used_stat, used_item = _ecos_try_multi(
        ["151Y005", "151Y009", "151Y013"],
        ["1100000", "AAA", "1000", "0000", "1A0"],
        "Q", "한국 가계신용 잔액 (10억원)", "HOUSEHOLD_DEBT",
    )
    if r:
        r["source"] = f"ECOS:{used_stat}"
        result["household_debt_kr"] = r
        log(f"[ECOS] 가계신용: {r['value']} ({r['period']}) item={used_item}")

    return result


# ============================================================
# R-ONE API (한국부동산원 부동산 가격지수)
# ============================================================
def fetch_rone_stats(stats_id, item_code1=None, item_code2=None, item_code3=None,
                    period_type="M", start_prd=None, end_prd=None, limit=24):
    """R-ONE 신 OpenAPI (SttsApiTblData) 호출.

    stats_id: 통계 ID (예: A_2024_00026 전국주택가격동향조사 매매가격지수)
    item_code1~3: 분류 코드 (지역, 주택유형 등)
    """
    if not REALESTATE_API_KEY:
        return None
    now = datetime.now(KST)
    if not start_prd:
        if period_type == "M":
            start_prd = (now - timedelta(days=30 * limit)).strftime("%Y%m")
            end_prd   = now.strftime("%Y%m")
        elif period_type == "W":
            start_prd = (now - timedelta(days=7 * limit)).strftime("%Y%m%d")
            end_prd   = now.strftime("%Y%m%d")
        elif period_type == "Q":
            start_prd = f"{now.year - 5}Q1"
            end_prd   = f"{now.year}Q{(now.month - 1) // 3 + 1}"
        else:  # Y
            start_prd = str(now.year - limit)
            end_prd   = str(now.year)
    params = {
        "KEY":        REALESTATE_API_KEY,
        "Type":       "json",
        "pIndex":     1,
        "pSize":      limit,
        "STATBL_ID":  stats_id,
        "DTACYCLE_CD": period_type,
        "WRTTIME_IDTFR_ID_FROM": start_prd,
        "WRTTIME_IDTFR_ID_TO":   end_prd,
    }
    if item_code1: params["ITM_ID"]    = item_code1
    if item_code2: params["CLS_ID"]    = item_code2
    if item_code3: params["CLS_ID_2"]  = item_code3
    # 신 API: https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do
    urls = [
        f"{RONE_BASE}/SttsApiTblData.do",
        f"{RONE_BASE}/SttsApiTblData.do",  # alternative path
    ]
    for url in urls:
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code != 200:
                continue
            try:
                data = r.json()
            except ValueError:
                continue
            rows = data.get("SttsApiTblData", [])
            if isinstance(rows, list):
                for blk in rows:
                    if "row" in blk:
                        return blk["row"]
            return None
        except Exception as e:
            log(f"[R-ONE-new] {stats_id} 오류: {e}")
            continue
    return None


def fetch_realestate_kr():
    """한국부동산원 R-ONE API로 아파트 가격지수 조회.

    R-ONE은 2가지 엔드포인트 운영:
    1) https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do (신 버전, JSON)
    2) http://openapi.reb.or.kr/.../AptPriceIndex/... (legacy, XML)
    먼저 신 버전 시도 → 실패 시 legacy 시도.
    """
    if not REALESTATE_API_KEY:
        log("[R-ONE] API 키 없음 — 건너뜀")
        return {}
    now = datetime.now(KST)
    result = {}

    # ─── 신 API: 전국주택가격동향 (월간) ─────────────
    # R-ONE 신 OpenAPI 의 정확한 STATBL_ID 는 reb.or.kr 의 R-ONE 페이지에서 확인 가능.
    # 사용자가 보는 R-ONE "매매가격지수 변동률 (%)" 는 월간 동향 조사의 변동률.
    # 우리는 그것을 보여주는 게 맞음 — 지수 값(예: 105.2) 보다 변동률(%) 이 사용자에게 친숙.
    # STATBL_ID 후보 — 변동률 PRIMARY (사용자가 사이트에서 보는 값과 동일)
    stats_candidates = [
        # 변동률 시리즈 (매월 변동률 %)
        ("A_2024_00177", "전국 아파트 매매가격지수 변동률 (%)"),
        ("A_2024_00200", "전국 아파트 매매가격지수 변동률 (%)"),
        # 지수 시리즈 (110.5 등)
        ("A_2024_00026", "전국 아파트 매매가격지수"),
        ("A_2024_00301", "전국 아파트 매매가격지수"),
        ("A_2022_00131", "전국 종합주택 매매가격지수"),
    ]
    for stats_id, desc in stats_candidates:
        try:
            rows = fetch_rone_stats(stats_id, period_type="M", limit=12)
            if not rows: continue
            # 정렬 후 최신
            rows_sorted = sorted(rows, key=lambda r: r.get("WRTTIME_IDTFR_ID", ""))
            latest = rows_sorted[-1]
            val = _parse_num(latest.get("DTA_VAL"))
            if val is None: continue
            prev = _parse_num(rows_sorted[-2].get("DTA_VAL")) if len(rows_sorted) > 1 else None
            chg = round((val - prev) / prev * 100, 2) if prev and prev != 0 else None
            history = {}
            for row in rows_sorted:
                p = row.get("WRTTIME_IDTFR_ID")
                v = _parse_num(row.get("DTA_VAL"))
                if p and v is not None: history[p] = v
            result["apt_price_idx_kr"] = {
                "value":  round(val, 2),
                "prev":   prev,
                "chg":    chg,
                "period": latest.get("WRTTIME_IDTFR_ID"),
                "region": "전국",
                "desc":   desc,
                "source": f"R-ONE:{stats_id}",
                "history": history,
            }
            log(f"[R-ONE-new] 매매가격지수 ({stats_id}): {val} ({latest.get('WRTTIME_IDTFR_ID')})")
            break
        except Exception as e:
            log(f"[R-ONE-new] {stats_id} 오류: {e}")
            continue

    # 전세가격지수 변동률 (월간)
    jns_candidates = [
        # 변동률 시리즈
        ("A_2024_00178", "전국 아파트 전세가격지수 변동률 (%)"),
        ("A_2024_00201", "전국 아파트 전세가격지수 변동률 (%)"),
        # 지수 시리즈
        ("A_2024_00027", "전국 아파트 전세가격지수"),
        ("A_2022_00132", "전국 종합주택 전세가격지수"),
    ]
    for stats_id, desc in jns_candidates:
        try:
            rows = fetch_rone_stats(stats_id, period_type="M", limit=12)
            if not rows: continue
            rows_sorted = sorted(rows, key=lambda r: r.get("WRTTIME_IDTFR_ID", ""))
            latest = rows_sorted[-1]
            val = _parse_num(latest.get("DTA_VAL"))
            if val is None: continue
            prev = _parse_num(rows_sorted[-2].get("DTA_VAL")) if len(rows_sorted) > 1 else None
            chg = round((val - prev) / prev * 100, 2) if prev and prev != 0 else None
            history = {}
            for row in rows_sorted:
                p = row.get("WRTTIME_IDTFR_ID")
                v = _parse_num(row.get("DTA_VAL"))
                if p and v is not None: history[p] = v
            result["jns_price_idx_kr"] = {
                "value":  round(val, 2),
                "prev":   prev,
                "chg":    chg,
                "period": latest.get("WRTTIME_IDTFR_ID"),
                "region": "전국",
                "desc":   desc,
                "source": f"R-ONE:{stats_id}",
                "history": history,
            }
            log(f"[R-ONE-new] 전세지수 ({stats_id}): {val}")
            break
        except Exception as e:
            log(f"[R-ONE-new] {stats_id} 오류: {e}")
            continue

    # ─── Legacy API 폴백 ─────────────
    if not result:
        try:
            start_ym = (now - timedelta(days=60)).strftime("%Y%m")
            end_ym   = now.strftime("%Y%m")
            r = requests.get(
                f"{RONE_BASE_LEGACY}/AptPriceIndex/getAptPrcIdxByRegion",
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
                    "source": "R-ONE (legacy)",
                }
                log(f"[R-ONE-legacy] 매매지수: {result['apt_price_idx_kr']}")
        except Exception as e:
            log(f"[R-ONE-legacy] 오류: {e}")

    # ─── R-ONE 추가 시리즈: 미분양 / 인허가 / 착공 / 월간 거래량 ──
    extra_stats = [
        # (key,                desc,                            statbl_id,        period_type)
        ("unsold_kr",          "전국 미분양 주택 수",            "A_2024_00064",  "M"),
        ("permit_kr",          "주택 인허가 실적 (전국)",       "A_2024_00058",  "M"),
        ("start_kr",           "주택 착공 실적 (전국)",          "A_2024_00057",  "M"),
        ("complete_kr",        "주택 준공 실적 (전국)",          "A_2024_00059",  "M"),
        ("trade_count_kr_rone","전국 주택 매매 거래량 (R-ONE)",  "A_2024_00061",  "M"),
    ]
    for key, desc, statbl_id, period_type in extra_stats:
        try:
            rows = fetch_rone_stats(statbl_id, period_type=period_type, limit=24)
            if not rows:
                log(f"[R-ONE] {statbl_id} ({key}): 응답 없음 — 건너뜀")
                continue
            rows_sorted = sorted(rows, key=lambda r: r.get("WRTTIME_IDTFR_ID", ""))
            # 전국 (CL_NM == '전국') 행만 필터
            nationwide = [r for r in rows_sorted
                          if (r.get("CL_NM", "") in ("전국", "") or
                              "전국" in (r.get("CLS_NM", "") or ""))]
            target_rows = nationwide if nationwide else rows_sorted
            latest = target_rows[-1]
            val = _parse_num(latest.get("DTA_VAL"))
            if val is None: continue
            prev = _parse_num(target_rows[-2].get("DTA_VAL")) if len(target_rows) > 1 else None
            chg  = round((val - prev) / prev * 100, 2) if prev and prev != 0 else None
            history = {}
            for row in target_rows:
                p = row.get("WRTTIME_IDTFR_ID")
                v = _parse_num(row.get("DTA_VAL"))
                if p and v is not None:
                    history[p] = v
            result[key] = {
                "value":  round(val, 2),
                "prev":   prev,
                "chg":    chg,
                "period": latest.get("WRTTIME_IDTFR_ID"),
                "region": "전국",
                "desc":   desc,
                "source": f"R-ONE:{statbl_id}",
                "history": history,
            }
            log(f"[R-ONE] {key} ({statbl_id}): {val} ({latest.get('WRTTIME_IDTFR_ID')})")
        except Exception as e:
            log(f"[R-ONE] {key} ({statbl_id}) 오류: {e}")

    return result


# ============================================================
# KOSIS API (국가통계포털)
# ============================================================
def fetch_kosis_series(org_id, table_id, item_id="", period_type="M", start_prd=None, end_prd=None,
                       obj_l1=None):
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
            "objL1":       obj_l1 if obj_l1 is not None else item_id,
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


def fetch_kosis_retail_sales():
    """KOSIS 에서 한국 소매판매액지수 (총지수 + 전년동월비) 조회.

    통계표: DT_1JG2105 (서비스업동향조사: 소매판매액지수)
    조직: 101 (통계청)
    아이템:
      - T2 / T20: 소매판매액지수 (총지수, 불변)
      - T6 / T60: 소매판매액지수 (전년동월비, %)
    KOSIS 사이트에서 보여주는 값과 일치하도록 두 시리즈 모두 반환.
    """
    if not KOSIS_API_KEY:
        return None
    # KOSIS 통계표 ID 후보 — 시도 순서대로
    table_candidates = [
        # (orgId, tblId, label)
        ("101", "DT_1JG2105", "서비스업동향조사: 소매판매액지수"),
        ("101", "DT_1KI2017", "도소매업조사: 소매판매액지수"),
    ]
    # 항목코드 후보 — KOSIS 마다 다름
    item_candidates = ["T2", "T20", "13102803005A", "ALL", "T03"]
    now = datetime.now(KST)
    end_prd = now.strftime("%Y%m")
    start_prd = (now - timedelta(days=400)).strftime("%Y%m")
    for org_id, tbl_id, label in table_candidates:
        for item_id in item_candidates:
            try:
                data = fetch_kosis_series(org_id, tbl_id, item_id, "M", start_prd, end_prd)
                if not data or not isinstance(data, list):
                    continue
                # 유효한 데이터 행 필터링
                rows = [r for r in data if r.get("DT") and r.get("PRD_DE")]
                if not rows:
                    continue
                # 최신 PRD_DE 정렬
                rows.sort(key=lambda r: r.get("PRD_DE", ""))
                latest = rows[-1]
                val = _parse_num(latest.get("DT"))
                if val is None or val == 0:
                    continue
                prev = _parse_num(rows[-2].get("DT")) if len(rows) > 1 else None
                history = {}
                for r in rows[-24:]:  # 최근 24개월
                    p = r.get("PRD_DE")
                    v = _parse_num(r.get("DT"))
                    if p and v is not None:
                        history[p] = v
                log(f"[KOSIS] 소매판매액지수: value={val} period={latest.get('PRD_DE')} "
                    f"src={tbl_id}/{item_id}")
                return {
                    "value":  round(val, 2),
                    "prev":   prev,
                    "period": latest.get("PRD_DE"),
                    "desc":   "한국 소매판매액지수 (KOSIS)",
                    "source": f"KOSIS:{tbl_id}/{item_id}",
                    "history": history,
                }
            except Exception as e:
                log(f"[KOSIS] {tbl_id}/{item_id} 오류: {e}")
                continue
    log("[KOSIS] 소매판매액지수 모든 후보 실패")
    return None


# ============================================================
# 공공데이터포털 (data.go.kr) 통합 API
# ============================================================
def fetch_data_go_kr(service_path, params=None):
    """공공데이터포털 일반 API 호출 헬퍼.

    service_path 예: '/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'
    (국토부 아파트 매매 실거래가)
    DATA_GO_KR_API_KEY 가 ServiceKey 파라미터로 자동 추가됨.
    """
    if not DATA_GO_KR_API_KEY:
        return None
    try:
        params = dict(params or {})
        # 공공데이터포털은 ServiceKey 쿼리 파라미터를 사용 (디코딩된 키)
        params["serviceKey"] = DATA_GO_KR_API_KEY
        params.setdefault("_type", "json")
        url = f"{DATA_GO_KR_BASE}{service_path}"
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        # 일부 API는 XML 응답이므로 JSON 파싱 실패 시 XML 처리
        try:
            return r.json()
        except ValueError:
            return {"_xml_text": r.text}
    except Exception as e:
        log(f"[data.go.kr] {service_path} 오류: {e}")
        return None


def fetch_molit_apt_trade_count(months_back=3):
    """국토교통부_아파트 매매 실거래가 자료 — 최근 N개월 전국 거래량 합계.
    Returns: dict with monthly counts {YYYYMM: count, ...}
    """
    if not DATA_GO_KR_API_KEY:
        log("[MOLIT] DATA_GO_KR_API_KEY 없음 — 아파트 실거래 건너뜀")
        return None
    # 전국 17개 시도 코드 (LAWD_CD 앞 2자리)
    sido_codes = ["11", "26", "27", "28", "29", "30", "31", "36",
                  "41", "43", "44", "46", "47", "48", "50", "51", "52"]
    now = datetime.now(KST)
    results = {}
    for offset in range(months_back):
        y = now.year
        m = now.month - offset
        while m <= 0:
            m += 12
            y -= 1
        ym = f"{y:04d}{m:02d}"
        total = 0
        ok = 0
        for sido in sido_codes:
            data = fetch_data_go_kr(
                "/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
                {"LAWD_CD": sido, "DEAL_YMD": ym, "numOfRows": 1, "pageNo": 1},
            )
            if not data:
                continue
            try:
                total_cnt = int(
                    data.get("response", {})
                    .get("body", {})
                    .get("totalCount", 0)
                )
                total += total_cnt
                ok += 1
            except (TypeError, ValueError):
                continue
        if ok > 0:
            results[ym] = total
            log(f"[MOLIT] {ym} 전국 아파트 매매 거래: {total:,}건 ({ok}/{len(sido_codes)} 시도)")
    return results if results else None


# ============================================================
# 한국수출입은행 환율·금리 API
# ============================================================
def fetch_exim_exchange(target_date=None):
    """한국수출입은행 일별 환율 정보 (KRW 기준).

    target_date: YYYYMMDD (영업일). 미지정 시 어제 자동.
    Returns: list of dicts [{"cur_unit": "USD", "deal_bas_r": "1340.5", ...}, ...]
    """
    if not EXIM_API_KEY:
        return None
    try:
        if not target_date:
            # 영업일 보정: 주말이면 금요일로
            now = datetime.now(KST) - timedelta(days=1)
            while now.weekday() >= 5:
                now -= timedelta(days=1)
            target_date = now.strftime("%Y%m%d")
        r = requests.get(
            EXIM_BASE,
            params={
                "authkey": EXIM_API_KEY,
                "searchdate": target_date,
                "data": "AP01",  # 환율
            },
            timeout=15,
            verify=False,  # 한국수출입은행 SSL 인증서가 일부 환경에서 검증 실패
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or not data:
            return None
        log(f"[EXIM] {target_date}: {len(data)}개 환율 수신")
        return data
    except Exception as e:
        log(f"[EXIM] 환율 오류: {e}")
        return None


def fetch_exim_lending_rate(target_date=None):
    """한국수출입은행 대출금리 정보."""
    if not EXIM_API_KEY:
        return None
    try:
        if not target_date:
            now = datetime.now(KST) - timedelta(days=1)
            while now.weekday() >= 5:
                now -= timedelta(days=1)
            target_date = now.strftime("%Y%m%d")
        r = requests.get(
            EXIM_BASE.replace("exchangeJSON", "newKoreaeximLending"),
            params={"authkey": EXIM_API_KEY, "data": "EX02", "searchdate": target_date},
            timeout=15,
            verify=False,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        return data if isinstance(data, list) else None
    except Exception as e:
        log(f"[EXIM] 대출금리 오류: {e}")
        return None


def fetch_exim_intl_rate():
    """한국수출입은행 국제금리 정보."""
    if not EXIM_API_KEY:
        return None
    try:
        r = requests.get(
            EXIM_BASE.replace("exchangeJSON", "newKoreaeximIntRate"),
            params={"authkey": EXIM_API_KEY, "data": "AP05"},
            timeout=15,
            verify=False,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        return data if isinstance(data, list) else None
    except Exception as e:
        log(f"[EXIM] 국제금리 오류: {e}")
        return None


# ============================================================
# 산업통상자원부 — motir.go.kr 원자재 가격 (광물자원공사)
# ============================================================
def fetch_motir_commodities():
    """광물자원공사(MOTIR) 일일 원자재 가격 크롤링.

    https://www.motir.go.kr/kor/contents/103
    페이지에서 비철금속/귀금속/희소금속 일일 가격을 추출.
    Returns: {item: {price, change, unit, as_of}} or None
    """
    try:
        import re as _re
        r = requests.get(
            f"{MOTIR_BASE}/kor/contents/103",
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; FinanceCrawler/1.0)",
                "Accept-Language": "ko-KR,ko;q=0.9",
            },
            verify=False,
        )
        if r.status_code != 200:
            log(f"[MOTIR] HTTP {r.status_code}")
            return None
        r.encoding = "utf-8"
        html = r.text
        items = {}
        # 표 형식 추출 — 일반적으로 <tr>품목명</td><td>가격</td><td>변동</td>...
        # 우선 광물자원 공시 형식 패턴 시도
        # 패턴: <td>구리</td><td>9,234.50</td><td>+0.45%</td>
        rows = _re.findall(
            r'<t[dh][^>]*>\s*(구리|알루미늄|아연|니켈|납|주석|금|은|백금|팔라듐|텅스텐|몰리브덴|망간|리튬|코발트|희토류)[^<]*</t[dh]>'
            r'\s*(?:<t[dh][^>]*>[^<]*</t[dh]>)*?'
            r'\s*<t[dh][^>]*>([\d,\.]+)</t[dh]>',
            html, _re.DOTALL,
        )
        for name, price_str in rows:
            v = _parse_num(price_str)
            if v and v > 0:
                items[name] = {"price": v, "as_of": datetime.now(KST).strftime("%Y-%m-%d"),
                               "source": "motir.go.kr 광물자원공사"}
        if items:
            log(f"[MOTIR] {len(items)}개 원자재 가격 수집 ({', '.join(items.keys())[:60]})")
            return items
        log("[MOTIR] 표 형식 매칭 실패 — HTML 구조 변경 가능")
        return None
    except Exception as e:
        log(f"[MOTIR] 크롤링 오류: {e}")
        return None


# ============================================================
# 국민연금 자산배분 (NPS) — fund.nps.or.kr 공시
# ============================================================
def fetch_nps_allocation():
    """국민연금 자산배분 현황 크롤링.

    출처: https://fund.nps.or.kr/oprtprcn/ivsmprcn/getOHED0016M0.do
    JSON 응답이 있으면 사용, 없으면 HTML 파싱.
    """
    try:
        import re as _re
        # NPS는 EVE 형식 (REST POST + body로 paramset)
        url = "https://fund.nps.or.kr/oprtprcn/ivsmprcn/getOHED0016M0.do"
        r = requests.post(
            url,
            data={"paramset": "{}"},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://fund.nps.or.kr/",
            },
            timeout=20,
            verify=False,
        )
        if r.status_code != 200:
            log(f"[NPS] 자산배분 HTTP {r.status_code}")
            return None
        r.encoding = "utf-8"
        # HTML 안에서 자산비중 추출 (테이블 형식)
        html = r.text
        items = []
        # 형식: <td>국내주식</td>... <td>비중(%)</td><td>14.9</td>
        patterns = [
            (r'국내주식.*?([\d.]+)%', '국내주식'),
            (r'해외주식.*?([\d.]+)%', '해외주식'),
            (r'국내채권.*?([\d.]+)%', '국내채권'),
            (r'해외채권.*?([\d.]+)%', '해외채권'),
            (r'대체투자.*?([\d.]+)%', '대체투자'),
        ]
        for pat, asset_name in patterns:
            m = _re.search(pat, html, _re.DOTALL)
            if m:
                pct = _parse_num(m.group(1))
                if pct:
                    items.append({"asset": asset_name, "pct": pct})
        if items:
            log(f"[NPS] 자산배분 {len(items)}개 수집")
            return {"allocation": items, "as_of": datetime.now(KST).strftime("%Y-%m-%d"),
                    "source": "fund.nps.or.kr"}
        return None
    except Exception as e:
        log(f"[NPS] 자산배분 크롤링 오류: {e}")
        return None


# ============================================================
# VKOSPI (KOSPI200 변동성 지수)
# ============================================================
def _is_valid_vkospi(v):
    """VKOSPI 합리적 범위 체크 — 변동성 지수는 보통 5~100 사이.
    KOSPI/KOSPI200 지수가 잘못 들어오면 1000~10000+ 이므로 검출됨.
    """
    return v is not None and 1 < v < 200


def _stooq_history(symbol, validator=None, max_points=520):
    """Stooq CSV 에서 시계열 데이터 수집. validator(close)->bool 로 합리적 범위 검증.
    Returns: {"YYYY-MM-DD": close, ...} 형태의 dict (최대 max_points 일).
    """
    try:
        r = requests.get(
            f"https://stooq.com/q/d/l/?s={symbol}&i=d&o=1110000",
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code != 200 or not r.text:
            return {}
        history = {}
        lines = [l for l in r.text.strip().split("\n") if l and not l.startswith("Date")]
        for ln in lines[-max_points:]:
            parts = ln.split(",")
            if len(parts) < 5:
                continue
            dt = parts[0].strip()
            try:
                close = float(parts[4])
            except (ValueError, TypeError):
                continue
            if validator and not validator(close):
                continue
            history[dt] = round(close, 4)
        return history
    except Exception as e:
        log(f"[STOOQ] {symbol} 오류: {e}")
        return {}


def _naver_chart_history(symbol, validator=None, days_back=730):
    """네이버 금융 모바일 차트 API 에서 시계열 데이터 수집.

    엔드포인트: https://m.stock.naver.com/front-api/external/chart/domestic/info
                ?symbol=SYMBOL&requestType=1&startTime=YYYYMMDD&endTime=YYYYMMDD&timeframe=day

    응답: JSON-in-XML 형태 (HTML escaped JSON string) — 정규식으로 파싱.
    symbol 예: VKOSPI, KOSPI, KOSDAQ
    Returns: {"YYYY-MM-DD": close, ...}
    """
    try:
        end_dt = datetime.now(KST)
        start_dt = end_dt - timedelta(days=days_back)
        url = (
            "https://m.stock.naver.com/front-api/external/chart/domestic/info"
            f"?symbol={symbol}"
            "&requestType=1"
            f"&startTime={start_dt.strftime('%Y%m%d')}"
            f"&endTime={end_dt.strftime('%Y%m%d')}"
            "&timeframe=day"
        )
        sess = _naver_session()
        r = sess.get(url, timeout=20)
        if r.status_code != 200:
            log(f"[NaverChart] {symbol} HTTP {r.status_code}")
            return {}
        text = r.text
        # 응답: '...|YYYYMMDD|open|high|low|close|volume|foreign_ratio|...' 형태 또는
        # 'CHARTDATA={...}' / JSON 배열. 다중 포맷 처리.
        import re as _re
        history = {}
        # 패턴 A: '[YYYYMMDD, open, high, low, close, volume]' (배열 in 응답)
        for m in _re.finditer(r'\[\s*"?(\d{8})"?\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)', text):
            dt = m.group(1)
            try:
                close = float(m.group(5))
            except (ValueError, TypeError):
                continue
            if validator and not validator(close):
                continue
            iso = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
            history[iso] = round(close, 4)
        # 패턴 B: 'YYYYMMDD|open|high|low|close|...' (pipe-separated)
        if not history:
            for m in _re.finditer(r'(\d{8})\|[\d.]+\|[\d.]+\|[\d.]+\|([\d.]+)\|', text):
                dt = m.group(1)
                try:
                    close = float(m.group(2))
                except (ValueError, TypeError):
                    continue
                if validator and not validator(close):
                    continue
                iso = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
                history[iso] = round(close, 4)
        return history
    except Exception as e:
        log(f"[NaverChart] {symbol} 오류: {e}")
        return {}


def _krx_vkospi_history_series(days_back=365):
    """KRX OpenAPI 의 변동성지수 일별 시세를 여러 날짜로 페치하여 시계열 구축.
    /idx/kospi_dd_trd 가 basd 별 한 날짜의 모든 인덱스 row 를 반환하므로
    날짜 범위 모드로 호출 (KRX OpenAPI 는 strtDd/endDd 파라미터 지원).
    """
    history = {}
    if not KRX_API_KEY:
        return history
    try:
        end_dt = datetime.now(KST)
        start_dt = end_dt - timedelta(days=days_back)
        url = "http://data-dbg.krx.co.kr/svc/apis/idx/kospi_dd_trd"
        headers = {"AUTH_KEY": KRX_API_KEY}
        params = {
            "basDd":  end_dt.strftime("%Y%m%d"),  # KRX 는 단일 basDd 만 지원 → 최신만
        }
        # KRX 는 단일 basDd 만 받음. 시계열은 _krx_index_series 의 별도 호출.
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            j = r.json()
            for row in (j.get("OutBlock_1") or []):
                nm = (row.get("IDX_NM") or "").strip()
                if "변동성" in nm or "VKOSPI" in nm.upper() or "V-KOSPI" in nm.upper():
                    val = _parse_num(row.get("CLSPRC_IDX"))
                    basd = row.get("BAS_DD") or end_dt.strftime("%Y%m%d")
                    if _is_valid_vkospi(val):
                        iso = f"{basd[:4]}-{basd[4:6]}-{basd[6:8]}"
                        history[iso] = round(val, 4)
                    break
    except Exception as e:
        log(f"[KRX-VKOSPI-HIST] 오류: {e}")
    return history


def fetch_vkospi():
    """KSVKOSPI (KOSPI 200 변동성지수, 한국거래소 공식) 조회 — 범위(5~100) 검증.

    KRX/네이버 정식 심볼 코드는 KSVKOSPI (V-KOSPI 200 정식 명칭).
    사용자가 네이버에서 보는 시세 페이지(finance.naver.com/sise/sise_index.naver?code=KSVKOSPI)
    와 동일한 값을 우선 가져온다.

    1차: Naver 모바일 차트 API (KSVKOSPI) — 시계열 + 최신값
    2차: KRX OpenAPI /idx/kospi_dd_trd 에서 '변동성지수' 검색
    3차: 네이버 증권 KSVKOSPI 페이지 스크래핑
    4차: yfinance '^VKOSPI' (Yahoo 가 KOSPI 와 혼동하는 케이스 검증)
    Returns: {"value": float, "change": float, "as_of": "YYYY-MM-DD", "history": {...}} or None
    """
    # History 다중 소스 시도 (KSVKOSPI 정식 심볼 우선, VKOSPI 폴백)
    history = _naver_chart_history("KSVKOSPI", validator=_is_valid_vkospi, days_back=730)
    if history:
        log(f"[KSVKOSPI] Naver 차트 시계열: {len(history)}점 수집")
    else:
        # 구 심볼 VKOSPI 도 시도
        history = _naver_chart_history("VKOSPI", validator=_is_valid_vkospi, days_back=730)
        if history:
            log(f"[KSVKOSPI] Naver 차트 (구 심볼) 시계열: {len(history)}점")
    if not history:
        history = _stooq_history("%5Evkospi.kr", validator=_is_valid_vkospi)
        if history:
            log(f"[KSVKOSPI] Stooq 시계열: {len(history)}점 수집")
    # yfinance 시계열 보강 (Naver/Stooq 가 적은 경우)
    if len(history) < 30:
        try:
            yf_hist = fetch_yf_history("^VKOSPI", period="2y", interval="1d")
            if yf_hist:
                added = 0
                for row in yf_hist:
                    if _is_valid_vkospi(row.get("close")):
                        history[row["date"]] = round(row["close"], 4)
                        added += 1
                if added:
                    log(f"[KSVKOSPI] yfinance 시계열 추가: {added}점")
        except Exception as e:
            log(f"[KSVKOSPI] yfinance 시계열 오류: {e}")

    def _attach_history(result):
        if result and history:
            result["history"] = history
        return result

    # 1차: KRX 공식
    if KRX_API_KEY:
        rows, basd = fetch_krx_latest("/idx/kospi_dd_trd")
        if rows:
            for row in rows:
                nm = (row.get("IDX_NM") or "").strip()
                if "변동성" in nm or "VKOSPI" in nm.upper() or "V-KOSPI" in nm.upper():
                    val = _parse_num(row.get("CLSPRC_IDX"))
                    chg = _parse_num(row.get("FLUC_RT"))
                    if _is_valid_vkospi(val):
                        log(f"[KSVKOSPI] KRX: {nm} = {val} ({chg}%)")
                        return _attach_history({"value": round(val, 2), "change": round(chg or 0.0, 2), "as_of": basd, "source": "KRX OpenAPI", "symbol": "KSVKOSPI"})
                    elif val:
                        log(f"[KSVKOSPI] KRX {nm} = {val} → 범위 벗어남, 무시")
    # 2차: 네이버 증권 KSVKOSPI 페이지 스크래핑
    sess = _naver_session()
    for code in ("KSVKOSPI", "VKOSPI"):
        try:
            r = sess.get(f"https://finance.naver.com/sise/sise_index.naver?code={code}", timeout=15)
            if r.status_code != 200:
                continue
            r.encoding = "euc-kr"
            import re as _re
            html = r.text
            m_price = _re.search(r'<em id="now_value">([\d.,]+)</em>', html)
            m_chg = _re.search(r'<em id="change_value_and_rate">.*?([+\-]?[\d.]+)%', html, _re.DOTALL)
            if m_price:
                v = _parse_num(m_price.group(1))
                chg = _parse_num(m_chg.group(1)) if m_chg else 0.0
                if _is_valid_vkospi(v):
                    log(f"[KSVKOSPI] Naver ({code}): {v} ({chg}%)")
                    return _attach_history({"value": round(v, 2), "change": round(chg or 0.0, 2),
                            "as_of": datetime.now(KST).strftime("%Y-%m-%d"),
                            "source": f"Naver Finance ({code})", "symbol": "KSVKOSPI"})
        except Exception as e:
            log(f"[KSVKOSPI] Naver {code} 폴백 오류: {e}")
    # 3차: yfinance — 범위 검증으로 KOSPI 잘못 매핑 검출
    try:
        q = fetch_yf("^VKOSPI")
        if q and _is_valid_vkospi(q.get("price")):
            log(f"[KSVKOSPI] yfinance: {q['price']} ({q['change']}%)")
            return _attach_history({"value": q["price"], "change": q["change"], "as_of": datetime.now(KST).strftime("%Y-%m-%d"), "source": "yfinance", "symbol": "KSVKOSPI"})
        elif q and q.get("price"):
            log(f"[KSVKOSPI] yfinance {q['price']} → 범위 벗어남 (KOSPI 오매핑 가능성), 무시")
    except Exception as e:
        log(f"[KSVKOSPI] yfinance 폴백 오류: {e}")
    # 4차: Stooq 만으로 현재값 추출
    if history:
        dates = sorted(history.keys())
        latest = history[dates[-1]]
        prev = history[dates[-2]] if len(dates) > 1 else None
        chg = round((latest - prev) / prev * 100, 2) if prev else 0.0
        log(f"[KSVKOSPI] Stooq fallback: {latest} ({chg}%)")
        return {"value": latest, "change": chg, "as_of": dates[-1], "source": "Stooq ^vkospi.kr", "symbol": "KSVKOSPI", "history": history}
    log("[KSVKOSPI] 데이터 수집 실패")
    return None


def fetch_move_index():
    """ICE BofA MOVE Index (미국채 옵션 내재변동성).
    yfinance 시계열 + Stooq 보강.
    """
    move_validator = lambda v: 10 < v < 500
    # 1차: yfinance history (가장 안정적)
    history = {}
    try:
        yf_hist = fetch_yf_history("^MOVE", period="2y", interval="1d")
        if yf_hist:
            for row in yf_hist:
                if move_validator(row.get("close") or 0):
                    history[row["date"]] = round(row["close"], 4)
            if history:
                log(f"[MOVE] yfinance 시계열: {len(history)}점 수집")
    except Exception as e:
        log(f"[MOVE] yfinance 시계열 오류: {e}")
    # 2차: Stooq 보강
    if len(history) < 30:
        stooq = _stooq_history("%5Emove", validator=move_validator)
        if stooq:
            history.update(stooq)
            log(f"[MOVE] Stooq 시계열 추가: {len(stooq)}점 (총 {len(history)}점)")

    # 현재값 수집
    try:
        q = fetch_yf("^MOVE")
        if q and q.get("price"):
            log(f"[MOVE] yfinance: {q['price']}")
            result = {"value": q["price"], "change": q["change"],
                    "as_of": datetime.now(KST).strftime("%Y-%m-%d"),
                    "source": "yfinance ^MOVE"}
            if history:
                result["history"] = history
            return result
    except Exception as e:
        log(f"[MOVE] yfinance 오류: {e}")
    # yfinance 현재값 실패 시 history 의 마지막 값 사용
    if history:
        dates = sorted(history.keys())
        latest = history[dates[-1]]
        prev = history[dates[-2]] if len(dates) > 1 else None
        chg = round((latest - prev) / prev * 100, 2) if prev else 0.0
        log(f"[MOVE] history fallback: {latest} ({chg}%)")
        return {"value": latest, "change": chg, "as_of": dates[-1],
                "source": "yfinance ^MOVE (시계열)", "history": history}
    return None


def fetch_putcall_ratio():
    """CBOE Put/Call Ratio (시장 옵션 심리).

    다중 소스 폴백:
    1) Stooq ^pcc (Total Put/Call Ratio)
    2) CBOE 직접 페이지에서 최신 일별 데이터
    3) yfinance ^PCC
    4) Alpha Vantage (있는 경우)

    또한 과거 시계열을 함께 수집 (history)
    """
    # 1) Stooq — CSV 직접 다운로드 (일별 ~1년치)
    history = {}
    latest = None
    try:
        # 1년치 일별 PCR 데이터 — 차트 표시용
        end = datetime.now(KST).strftime("%Y%m%d")
        start = (datetime.now(KST) - timedelta(days=400)).strftime("%Y%m%d")
        r = requests.get(
            f"https://stooq.com/q/d/l/?s=%5Epcc&i=d&d1={start}&d2={end}",
            timeout=15,
        )
        if r.status_code == 200 and r.text:
            lines = [l for l in r.text.strip().split("\n") if l and not l.startswith("Date")]
            for ln in lines:
                parts = ln.split(",")
                if len(parts) >= 5:
                    dt = parts[0].strip()
                    # 종가 (4번째 컬럼)
                    v = _parse_num(parts[4])
                    if v and 0.1 < v < 5.0:
                        history[dt] = v
            if history:
                latest_date = sorted(history.keys())[-1]
                latest = history[latest_date]
                prev_keys = sorted(history.keys())
                prev = history[prev_keys[-2]] if len(prev_keys) > 1 else None
                chg = round((latest - prev) / prev * 100, 2) if prev else 0
                log(f"[PCR] Stooq: {latest} ({latest_date}, +{len(history)}점 일별 시계열)")
                return {"value": latest, "change": chg, "as_of": latest_date,
                        "history": history, "source": "Stooq ^pcc (일별)"}
    except Exception as e:
        log(f"[PCR] Stooq 오류: {e}")

    # 2) CBOE 직접 (Equity Put/Call Ratio) — 1년치 일별
    try:
        r = requests.get(
            "https://cdn.cboe.com/api/global/us_indices/daily_prices/EQUITYPC_History.csv",
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200 and r.text:
            lines = [l for l in r.text.strip().split("\n") if l and not l.startswith("DATE")]
            for ln in lines[-260:]:  # 최근 ~1년 영업일
                parts = ln.split(",")
                if len(parts) >= 2:
                    dt = parts[0].strip()
                    v = _parse_num(parts[1])
                    if v and 0.1 < v < 5.0:
                        history[dt] = v
            if history:
                latest_date = sorted(history.keys())[-1]
                latest = history[latest_date]
                prev_keys = sorted(history.keys())
                prev = history[prev_keys[-2]] if len(prev_keys) > 1 else None
                chg = round((latest - prev) / prev * 100, 2) if prev else 0
                log(f"[PCR] CBOE Equity: {latest} ({latest_date}, +{len(history)}점)")
                return {"value": latest, "change": chg, "as_of": latest_date,
                        "history": history, "source": "CBOE Equity P/C (일별)"}
    except Exception as e:
        log(f"[PCR] CBOE 오류: {e}")

    # 3) yfinance ^PCC
    try:
        q = fetch_yf("^PCC")
        if q and q.get("price") and 0.1 < q["price"] < 5.0:
            log(f"[PCR] yfinance: {q['price']}")
            return {"value": q["price"], "change": q.get("change", 0),
                    "as_of": datetime.now(KST).strftime("%Y-%m-%d"),
                    "source": "yfinance ^PCC"}
    except Exception as e:
        log(f"[PCR] yfinance 오류: {e}")

    log("[PCR] 데이터 수집 실패")
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


# ============================================================
# 한국투자증권 KIS Developers API
# ============================================================
# 토큰은 24h 유효 — 메모리 + 파일 캐시(GHA cache) 로 매시간 재발급 방지.
# 잦은 발급 시 한투에서 카카오톡 알람을 보내고 이용 제한이 걸릴 수 있어 1일 1회로 제한한다.
_KIS_TOKEN_CACHE = {"token": None, "expires_at": 0}


def _load_kis_token_from_file():
    """디스크에 저장된 KIS 토큰을 로드 (GitHub Actions cache로 런 간 공유)."""
    try:
        if not os.path.exists(KIS_TOKEN_FILE):
            return None
        with open(KIS_TOKEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        tok = data.get("token")
        exp = float(data.get("expires_at", 0))
        # 키 변경 감지 — 같은 키로 발급된 토큰만 재사용
        saved_key_hash = data.get("appkey_hash") or ""
        cur_key_hash = (KIS_APP_KEY[:8] + KIS_APP_KEY[-4:]) if KIS_APP_KEY else ""
        if tok and exp > _time.time() + 60 and saved_key_hash == cur_key_hash:
            log(f"[KIS] 파일 캐시 토큰 재사용 (만료까지 {int(exp - _time.time())}초)")
            return {"token": tok, "expires_at": exp}
    except Exception as e:
        log(f"[KIS] 토큰 캐시 로드 실패: {e}")
    return None


def _save_kis_token_to_file(token, expires_at):
    """KIS 토큰을 디스크에 저장 (다음 런에서 재사용)."""
    try:
        with open(KIS_TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "token": token,
                "expires_at": expires_at,
                "appkey_hash": (KIS_APP_KEY[:8] + KIS_APP_KEY[-4:]) if KIS_APP_KEY else "",
                "saved_at": datetime.now(KST).isoformat(),
            }, f)
        log(f"[KIS] 토큰 디스크 저장 완료 ({KIS_TOKEN_FILE})")
    except Exception as e:
        log(f"[KIS] 토큰 디스크 저장 실패: {e}")


def kis_get_token():
    """KIS OAuth 2.0 토큰 발급 — 1일 1회 발급으로 충분 (24h 유효).

    캐시 우선순위:
      1) 메모리 캐시 (_KIS_TOKEN_CACHE)
      2) 파일 캐시 (KIS_TOKEN_FILE)  ← GitHub Actions cache 액션이 보존
      3) 신규 발급 (한투에 POST /oauth2/tokenP)

    KIS_ENABLED=1 환경변수가 명시 설정되지 않으면 신규 발급을 건너뛴다.
    이는 한투 카카오톡 알람을 완전히 차단하기 위한 안전 장치 (기본 비활성화).
    """
    if not KIS_APP_KEY or not KIS_APP_SECRET:
        return None
    # 1) 메모리 캐시 확인
    if _KIS_TOKEN_CACHE["token"] and _KIS_TOKEN_CACHE["expires_at"] > _time.time() + 60:
        return _KIS_TOKEN_CACHE["token"]
    # 2) 파일 캐시 확인 (GHA cache로 런 간 보존)
    cached = _load_kis_token_from_file()
    if cached:
        _KIS_TOKEN_CACHE["token"] = cached["token"]
        _KIS_TOKEN_CACHE["expires_at"] = cached["expires_at"]
        return cached["token"]
    # 3) 신규 토큰 발급 — KIS_ENABLED=1 인 경우에만 (한투 카카오톡 알람 차단)
    if not KIS_ENABLED:
        log("[KIS] 캐시 만료 + KIS_ENABLED 비활성 — 토큰 발급 건너뜀 (카카오톡 알람 차단). "
            "신규 토큰이 필요하면 워크플로우에 KIS_ENABLED=1 을 설정하세요.")
        return None
    try:
        r = requests.post(
            f"{KIS_BASE}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": KIS_APP_KEY,
                "appsecret": KIS_APP_SECRET,
            },
            timeout=15,
        )
        if r.status_code != 200:
            log(f"[KIS] 토큰 발급 실패: HTTP {r.status_code} {r.text[:200]}")
            return None
        j = r.json()
        tok = j.get("access_token")
        exp = j.get("expires_in", 86400)
        if not tok:
            log(f"[KIS] 토큰 응답에 access_token 없음: {j}")
            return None
        expires_at = _time.time() + int(exp) - 60
        _KIS_TOKEN_CACHE["token"] = tok
        _KIS_TOKEN_CACHE["expires_at"] = expires_at
        _save_kis_token_to_file(tok, expires_at)
        log(f"[KIS] 토큰 신규 발급 성공 (만료까지 {exp}초) — 다음 24시간 동안 재사용")
        return tok
    except Exception as e:
        log(f"[KIS] 토큰 발급 오류: {e}")
        return None


def kis_request(path, tr_id, params=None):
    """KIS API 공통 GET 요청 헬퍼."""
    token = kis_get_token()
    if not token:
        return None
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }
    try:
        r = requests.get(f"{KIS_BASE}{path}", headers=headers, params=params or {}, timeout=15)
        if r.status_code != 200:
            log(f"[KIS] {path} {tr_id} HTTP {r.status_code}: {r.text[:200]}")
            return None
        return r.json()
    except Exception as e:
        log(f"[KIS] {path} 오류: {e}")
        return None


def fetch_kis_index_quote(market_code):
    """KIS API로 KOSPI/KOSDAQ 지수 조회.

    market_code: '0001' (KOSPI), '1001' (KOSDAQ)
    """
    # 국내업종 현재가 조회 (FHPUP02100000): tr_id 'FHPUP02100000'
    res = kis_request(
        "/uapi/domestic-stock/v1/quotations/inquire-index-price",
        "FHPUP02100000",
        params={
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": market_code,
        },
    )
    if not res or res.get("rt_cd") != "0":
        return None
    out = res.get("output", {})
    price = _parse_num(out.get("bstp_nmix_prpr"))
    chg_pct = _parse_num(out.get("bstp_nmix_prdy_ctrt"))
    if not price:
        return None
    return {"price": round(price, 2), "change": round(chg_pct or 0.0, 2),
            "as_of": datetime.now(KST).strftime("%Y-%m-%d"),
            "source": "KIS OpenAPI"}


def fetch_kis_stock_quote(stock_code):
    """KIS API로 개별 종목 시세 조회 (6자리 종목코드)."""
    res = kis_request(
        "/uapi/domestic-stock/v1/quotations/inquire-price",
        "FHKST01010100",
        params={
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
        },
    )
    if not res or res.get("rt_cd") != "0":
        return None
    out = res.get("output", {})
    return {
        "price":  _parse_num(out.get("stck_prpr")),
        "change": _parse_num(out.get("prdy_ctrt")),
        "volume": _parse_num(out.get("acml_vol")),
        "high":   _parse_num(out.get("stck_hgpr")),
        "low":    _parse_num(out.get("stck_lwpr")),
        "open":   _parse_num(out.get("stck_oprc")),
        "as_of":  datetime.now(KST).strftime("%Y-%m-%d"),
        "source": "KIS OpenAPI",
    }


def fetch_kis_index_dailyprice(market_code, period_days=60):
    """KIS API로 지수 일별 시세 조회 (시계열)."""
    end_dt = datetime.now(KST).strftime("%Y%m%d")
    start_dt = (datetime.now(KST) - timedelta(days=period_days*2)).strftime("%Y%m%d")
    res = kis_request(
        "/uapi/domestic-stock/v1/quotations/inquire-index-daily-price",
        "FHPUP02120000",
        params={
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": market_code,
            "FID_INPUT_DATE_1": start_dt,
            "FID_INPUT_DATE_2": end_dt,
            "FID_PERIOD_DIV_CODE": "D",
        },
    )
    if not res or res.get("rt_cd") != "0":
        return None
    out = res.get("output2") or res.get("output") or []
    series = []
    for r in out:
        date = r.get("stck_bsop_date")
        close = _parse_num(r.get("bstp_nmix_prpr") or r.get("clos_prc"))
        if date and close:
            series.append({"date": f"{date[:4]}-{date[4:6]}-{date[6:8]}", "close": close})
    series.sort(key=lambda x: x["date"])
    return series if series else None


def _kis_parse_mover_row(r):
    """KIS 등락률 순위 응답 한 행을 표준 dict 로 변환. 필드명이 응답마다 약간 다르므로 다중 키 시도."""
    # chg 는 양수/음수 모두 % 단위. KIS 는 prdy_ctrt (% 변화율) 또는 prdy_vrss_rate 등을 사용
    chg_raw = r.get("prdy_ctrt") or r.get("prdy_vrss_rate") or r.get("prdy_vrss_ratio") or r.get("ctrt") or "0"
    vol_raw = r.get("acml_vol") or r.get("vol") or r.get("acml_trd_vol") or "0"
    return {
        "name":  (r.get("hts_kor_isnm") or r.get("isnm") or "").strip(),
        "code":  (r.get("stck_shrn_iscd") or r.get("mksc_shrn_iscd") or "").strip(),
        "price": _parse_num(r.get("stck_prpr") or r.get("prpr") or r.get("price")) or 0,
        "chg":   _parse_num(chg_raw) or 0,
        "vol":   _parse_num(vol_raw) or 0,
        "as_of": datetime.now(KST).strftime("%Y-%m-%d"),
    }


def _is_valid_mover_list(items, min_nonzero=3):
    """등락 데이터 검증: 최소 min_nonzero 개 종목이 chg!=0 이어야 유효.
    또한 모든 종목이 동일 chg=0 이면 무효 (랭킹 미동작).
    """
    if not items or len(items) < min_nonzero:
        return False
    nonzero = sum(1 for it in items if it.get("chg") and it["chg"] != 0)
    return nonzero >= min_nonzero


def _kis_fetch_ranking(market_code, sort_code, top_n):
    """KIS 등락률 순위 단일 호출 — sort_code: '0'=상승, '1'=하락"""
    res = kis_request(
        "/uapi/domestic-stock/v1/ranking/fluctuation",
        "FHPST01700000",
        params={
            "fid_cond_mrkt_div_code":  "J",
            "fid_cond_scr_div_code":   "20170",
            "fid_input_iscd":          market_code,
            "fid_rank_sort_cls_code":  sort_code,
            "fid_input_cnt_1":         "0",
            "fid_prc_cls_code":        "1",
            "fid_input_price_1":       "",
            "fid_input_price_2":       "",
            "fid_vol_cnt":             "",
            "fid_trgt_cls_code":       "0",
            "fid_trgt_exls_cls_code":  "0",
            "fid_div_cls_code":        "0",
            "fid_rsfl_rate1":          "",
            "fid_rsfl_rate2":          "",
        },
    )
    if not res or res.get("rt_cd") != "0":
        if res:
            log(f"[KIS-RANK] {market_code} sort={sort_code} rt_cd={res.get('rt_cd')} msg={res.get('msg1','')[:80]}")
        return []
    rows = (res.get("output") or [])[:top_n]
    return [_kis_parse_mover_row(r) for r in rows]


def fetch_kis_stock_movers(top_n=10):
    """KIS API로 KOSPI/KOSDAQ 상승/하락 Top 종목 조회.

    국내주식 등락률 순위 조회 (FHPST01700000)
    여러 market_code 를 순차 시도 (일부 KIS 계정은 0000/0001 만 동작).
    응답 검증: 최소 3개 종목이 chg!=0 이고, 상승/하락 리스트가 동일하지 않아야 유효.
    """
    # KIS 시장코드: 0000=전체 / 0001=KOSPI / 1001=KOSDAQ / 2001=KOSPI200
    # 일부 모의투자 계정은 "0000" 만 동작하지만 등락률 정렬이 안 되는 경우가 있음 → 검증으로 fallback
    for market_code, label in [("0001", "KOSPI"), ("0000", "전체"), ("1001", "KOSDAQ"), ("2001", "KOSPI200")]:
        gainers = _kis_fetch_ranking(market_code, "0", top_n)
        losers  = _kis_fetch_ranking(market_code, "1", top_n)
        # 검증: 상승/하락 리스트가 다르고, chg!=0 인 종목이 충분한지
        if _is_valid_mover_list(gainers) and _is_valid_mover_list(losers):
            # 종목 코드 셋 비교 — 두 리스트가 90% 이상 같으면 랭킹이 작동 안 한 것 (KIS 가 generic list 리턴)
            gset = set(g.get("code") for g in gainers)
            lset = set(l.get("code") for l in losers)
            overlap = len(gset & lset) / max(len(gset), 1)
            if overlap < 0.5:
                log(f"[KIS] {label}(iscd={market_code}) 상승/하락 {len(gainers)}/{len(losers)}건 수집 (검증 통과)")
                return gainers[:top_n], losers[:top_n]
            else:
                log(f"[KIS] {label}(iscd={market_code}) 상승≅하락 ({overlap*100:.0f}% 중복) → 랭킹 미작동, 다음 코드 시도")
        else:
            log(f"[KIS] {label}(iscd={market_code}) chg 값이 모두 0 또는 부족 → 다음 코드 시도")
    log("[KIS] 모든 market_code 실패 — 빈 리스트 반환 (Naver Finance 폴백 트리거)")
    return [], []


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
        "Gold":     "GC=F",
        "Silver":   "SI=F",
        "Platinum": "PL=F",
        "Copper":   "HG=F",
        "WTI":      "CL=F",
        "Brent":    "BZ=F",
        "NatGas":   "NG=F",
        "Aluminum": "ALI=F",
        # 농산물 (사용자 요청: ZW=F/ZC=F/ZS=F/ZR=F)
        "Wheat":    "ZW=F",
        "Corn":     "ZC=F",
        "Soybean":  "ZS=F",
        "Rice":     "ZR=F",
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
        "sentiment": {},  # 시장 분위기 추가 지표 (VKOSPI 등)
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

        # KOSPI 상승/하락 Top10 — 검증 포함
        gainers, losers = fetch_krx_stock_movers("kospi", top_n=10)
        if _is_valid_mover_list(gainers):
            data["stockMovers"]["kospiGainers"] = gainers
        elif gainers:
            log(f"[KRX] 상승종목 {len(gainers)}건 chg=0 garbage — 폴백 트리거")
        if _is_valid_mover_list(losers):
            data["stockMovers"]["kospiLosers"] = losers
        elif losers:
            log(f"[KRX] 하락종목 {len(losers)}건 chg=0 garbage — 폴백 트리거")

        # ETF 상승/하락 Top10
        etf_up, etf_down = fetch_krx_etf_movers(top_n=10)
        if etf_up:
            data["etfMovers"]["etfGainers"] = etf_up
        if etf_down:
            data["etfMovers"]["etfLosers"] = etf_down

        data["sources"]["stockMovers"] = "KRX OpenAPI"
    else:
        log("[KRX] API 키 없음 — Naver Finance 폴백 시도")

    # 주식 상승/하락 Top10 — 다중 폴백 (pykrx → KIS → Naver)
    # 우선순위:
    #   1) pykrx: KRX 정보데이터시스템 직접 호출 — 키 없음·차단 없음·품질 최고
    #   2) KIS (KIS_ENABLED=1 인 경우만): 한투 OpenAPI 등락률 순위
    #   3) Naver Finance: m.stock.naver.com 등 다중 CORS 프록시 시도
    def _stock_movers_valid(key):
        items = data["stockMovers"].get(key, [])
        return _is_valid_mover_list(items) if items else False

    # 1) pykrx PRIMARY — 무인증·안정적
    if not _stock_movers_valid("kospiGainers") or not _stock_movers_valid("kospiLosers"):
        try:
            pkg, pkl = fetch_pykrx_stock_movers(market="KOSPI", top_n=10)
            if _is_valid_mover_list(pkg) and not _stock_movers_valid("kospiGainers"):
                data["stockMovers"]["kospiGainers"] = pkg
                data["sources"]["stockMovers"] = "pykrx (KRX 정보데이터시스템)"
            if _is_valid_mover_list(pkl) and not _stock_movers_valid("kospiLosers"):
                data["stockMovers"]["kospiLosers"] = pkl
                if not data["sources"].get("stockMovers"):
                    data["sources"]["stockMovers"] = "pykrx (KRX 정보데이터시스템)"
        except Exception as e:
            log(f"[pykrx] 주식 movers 조회 오류: {e}")

    # 2) KIS — KIS_ENABLED=1 인 경우에만 (카카오톡 알람 차단을 위해 기본 OFF)
    if not _stock_movers_valid("kospiGainers") or not _stock_movers_valid("kospiLosers"):
        if KIS_ENABLED and KIS_APP_KEY and KIS_APP_SECRET:
            try:
                kis_gainers, kis_losers = fetch_kis_stock_movers(top_n=10)
                if _is_valid_mover_list(kis_gainers) and not _stock_movers_valid("kospiGainers"):
                    data["stockMovers"]["kospiGainers"] = kis_gainers
                    data["sources"]["stockMovers"] = "KIS OpenAPI (한국투자증권)"
                if _is_valid_mover_list(kis_losers) and not _stock_movers_valid("kospiLosers"):
                    data["stockMovers"]["kospiLosers"] = kis_losers
            except Exception as e:
                log(f"[KIS] 상승/하락 종목 조회 오류: {e}")

    # 3) Naver Finance — 마지막 폴백 (다중 CORS 프록시)
    if not _stock_movers_valid("kospiGainers") or not _stock_movers_valid("kospiLosers"):
        gainers, losers = fetch_naver_stock_movers(market="kospi", top_n=10)
        if _is_valid_mover_list(gainers) and not _stock_movers_valid("kospiGainers"):
            data["stockMovers"]["kospiGainers"] = gainers
            data["sources"]["stockMovers"] = "Naver Finance"
        if _is_valid_mover_list(losers) and not _stock_movers_valid("kospiLosers"):
            data["stockMovers"]["kospiLosers"] = losers

    # ETF — pykrx 우선, 실패 시 Naver
    if not data["etfMovers"].get("etfGainers") or not data["etfMovers"].get("etfLosers"):
        try:
            peg, pel = fetch_pykrx_etf_movers(top_n=10)
            if peg and not data["etfMovers"].get("etfGainers"):
                data["etfMovers"]["etfGainers"] = peg
                data["sources"]["etfMovers"] = "pykrx (KRX 정보데이터시스템)"
            if pel and not data["etfMovers"].get("etfLosers"):
                data["etfMovers"]["etfLosers"] = pel
                if not data["sources"].get("etfMovers"):
                    data["sources"]["etfMovers"] = "pykrx (KRX 정보데이터시스템)"
        except Exception as e:
            log(f"[pykrx-ETF] 조회 오류: {e}")
    # pykrx 실패 → Naver 폴백
    if not data["etfMovers"].get("etfGainers") or not data["etfMovers"].get("etfLosers"):
        etf_up, etf_down = fetch_naver_etf_movers(top_n=10)
        if etf_up and not data["etfMovers"].get("etfGainers"):
            data["etfMovers"]["etfGainers"] = etf_up
            data["sources"]["etfMovers"] = "Naver Finance"
        if etf_down and not data["etfMovers"].get("etfLosers"):
            data["etfMovers"]["etfLosers"] = etf_down

    # 진단 정보 — 어떤 소스가 성공/실패했는지 frontend 에서 표시 가능
    data.setdefault("diagnostics", {})
    data["diagnostics"]["stockMoversSource"] = data["sources"].get("stockMovers", "FAILED")
    data["diagnostics"]["etfMoversSource"]   = data["sources"].get("etfMovers",   "FAILED")
    data["diagnostics"]["kisEnabled"]        = KIS_ENABLED
    data["diagnostics"]["pykrxAvailable"]    = _PYKRX_AVAILABLE

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
        "Gold":     "GC=F",
        "Silver":   "SI=F",
        "Platinum": "PL=F",
        "Copper":   "HG=F",
        "WTI":      "CL=F",
        "Brent":    "BZ=F",
        "NatGas":   "NG=F",
        # 비철금속 (LME 선물)
        "Aluminum": "ALI=F",
        # 농산물 (시카고 상품거래소 선물) — 사용자 요청에 따라 yfinance ZW=F/ZC=F/ZS=F/ZR=F
        "Wheat":    "ZW=F",
        "Corn":     "ZC=F",
        "Soybean":  "ZS=F",
        "Rice":     "ZR=F",
    }
    for name, sym in intl_com.items():
        q = fetch_yf(sym)
        if q:
            data["commodities"][name] = q
            log(f"[yf] {name}: {q['price']} ({q['change']:+.2f}%)")
        elif name in FALLBACK["commodities"]:
            data["commodities"][name] = dict(FALLBACK["commodities"][name])

    data["sources"]["commodities"] = (
        "KRX OpenAPI (한국 금·석유) + yfinance (국제·농산물·비철금속)" if krx_available else "yfinance"
    )

    # ── FRED 경제 지표 (미국) ─────────────────────────────────
    if FRED_API_KEY:
        log("[FRED] 미국 경제 지표 수집 시작")
        fred_data = fetch_fred_economic_indicators()
        data["economicIndicators"]["us"] = fred_data
        data["sources"]["economicIndicators_us"] = "FRED API (stlouisfed.org)"
        # DXY (ICE Dollar Index, 1973=100) — yfinance 로 별도 페치
        # FRED 에는 DXY 가 없고 DTWEXBGS (Broad, 2006=100) 만 있어 값이 다름.
        # 사용자가 마켓에서 보는 "달러 인덱스" 는 DXY 이므로 이를 PRIMARY 로 사용.
        log("[yf-DXY] DXY (DX-Y.NYB) yfinance 페치 시작")
        try:
            dxy_quote = fetch_yf("DX-Y.NYB")
            if dxy_quote and dxy_quote.get("price"):
                # 시계열도 함께
                dxy_hist = fetch_yf_history("DX-Y.NYB", period="5y")
                history_map = {}
                for pt in (dxy_hist or []):
                    history_map[pt["date"]] = pt["close"]
                data["economicIndicators"]["us"]["dxy_idx"] = {
                    "value":  round(dxy_quote["price"], 2),
                    "change": dxy_quote.get("change", 0),
                    "period": datetime.now(KST).strftime("%Y-%m-%d"),
                    "desc":   "달러 인덱스 (DXY, ICE 1973=100)",
                    "source": "yfinance DX-Y.NYB",
                    "history": history_map,
                }
                log(f"[yf-DXY] DXY = {dxy_quote['price']} ({dxy_quote.get('change',0):+.2f}%)")
            else:
                log("[yf-DXY] DX-Y.NYB 응답 없음 — FRED broad_dollar 폴백 유지")
        except Exception as e:
            log(f"[yf-DXY] 오류: {e}")
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
        # 국제 경제 지표 (일본/유로존/중국/독일/영국 OECD/IMF 시리즈)
        log("[FRED] 국제 경제 지표 수집 시작")
        intl_data = fetch_fred_intl_indicators()
        for cc, ind in intl_data.items():
            data["economicIndicators"][cc] = ind
        if intl_data:
            data["sources"]["economicIndicators_intl"] = "FRED API (OECD/IMF/Eurostat 시리즈)"
    else:
        log("[FRED] API 키 없음 — 미국 지표 건너뜀")

    # ── ECOS 경제 지표 (한국은행) ─────────────────────────────
    if ECOS_API_KEY:
        log("[ECOS] 한국 경제 지표 수집 시작")
        ecos_data = fetch_ecos_economic_indicators()
        data["economicIndicators"]["kr"] = ecos_data
        data["sources"]["economicIndicators_kr"] = "ECOS API (ecos.bok.or.kr)"
        # 소매판매액지수가 ECOS 에서 누락되면 KOSIS API 로 보강
        if not (ecos_data.get("retail_kr") or {}).get("value") and KOSIS_API_KEY:
            log("[KOSIS] retail_kr 누락 → KOSIS 보강 시도")
            try:
                kosis_retail = fetch_kosis_retail_sales()
                if kosis_retail:
                    data["economicIndicators"]["kr"]["retail_kr"] = kosis_retail
                    data["sources"]["retail_kr_kosis"] = "KOSIS API (101: 통계청)"
            except Exception as e:
                log(f"[KOSIS] 소매판매액지수 보강 오류: {e}")
        # 한국 국채 수익률 곡선 (1Y/3Y/5Y/10Y/20Y/30Y)
        log("[ECOS-YC] 한국 국채 수익률 곡선 수집 시작")
        try:
            kr_yc = fetch_ecos_yield_curve_kr()
            if kr_yc:
                data["yieldCurve"].update(kr_yc)
                data["sources"]["yieldCurve_kr"] = "ECOS API (817Y002: 시장금리 일별)"
        except Exception as e:
            log(f"[ECOS-YC] 오류: {e}")
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

    # ── VKOSPI (KOSPI200 변동성 지수) — 시장 분위기 ────────
    try:
        vk = fetch_vkospi()
        if vk:
            data["sentiment"]["vkospi"] = vk
            data["sources"]["vkospi"] = vk.get("source", "KRX/yfinance")
    except Exception as e:
        log(f"[VKOSPI] 오류: {e}")

    # ── MOVE Index (미국채 옵션 변동성) ────────
    try:
        mv = fetch_move_index()
        if mv:
            data["sentiment"]["move"] = mv
            data["sources"]["move"] = mv.get("source", "yfinance")
    except Exception as e:
        log(f"[MOVE] 오류: {e}")

    # ── Put/Call Ratio (옵션 심리) ────────
    try:
        pc = fetch_putcall_ratio()
        if pc:
            data["sentiment"]["pcr"] = pc
            data["sources"]["pcr"] = pc.get("source", "Stooq/CBOE")
    except Exception as e:
        log(f"[PCR] 오류: {e}")

    # ── 공공데이터포털: 국토부 아파트 매매 실거래 — 한국 부동산 보강 ──
    if DATA_GO_KR_API_KEY:
        try:
            log("[MOLIT] 국토부 아파트 매매 실거래 거래량 수집 시작")
            apt_trades = fetch_molit_apt_trade_count(months_back=3)
            if apt_trades:
                # 최신 월/전월 거래량
                sorted_keys = sorted(apt_trades.keys())
                latest = sorted_keys[-1]
                prev = sorted_keys[-2] if len(sorted_keys) > 1 else None
                cur_cnt = apt_trades[latest]
                prev_cnt = apt_trades[prev] if prev else None
                chg = round((cur_cnt - prev_cnt) / prev_cnt * 100, 2) if prev_cnt else None
                # 부동산 KR 데이터에 추가
                data["realestate"].setdefault("kr", {})["trade_count_kr"] = {
                    "value": cur_cnt,
                    "prev": prev_cnt,
                    "chg": chg,
                    "period": latest,
                    "desc": "전국 아파트 매매 실거래 건수",
                    "source": "data.go.kr (MOLIT 1613000)",
                    "history": apt_trades,
                }
                data["sources"]["realestate_molit"] = "data.go.kr (국토부 실거래가)"
        except Exception as e:
            log(f"[MOLIT] 오류: {e}")
    else:
        log("[MOLIT] DATA_GO_KR_API_KEY 없음 — 실거래가 건너뜀")

    # ── 한국수출입은행 EXIM: 환율/금리 검증용 ────────────────
    if EXIM_API_KEY:
        try:
            exim_rates = fetch_exim_exchange()
            if exim_rates:
                # USD/KRW 등 주요 통화 추출 (open.er-api 와 cross-check)
                exim_map = {}
                for r in exim_rates:
                    cur = r.get("cur_unit", "").upper()
                    bas = _parse_num((r.get("deal_bas_r") or "").replace(",", ""))
                    if cur and bas:
                        # cur_unit 이 'JPY(100)' 등 100엔 단위로 오는 경우 환산
                        if "(100)" in cur:
                            exim_map[cur.replace("(100)", "")] = bas / 100
                        else:
                            exim_map[cur] = bas
                if exim_map:
                    data["sources"]["fx_verify"] = "한국수출입은행 EXIM (검증)"
                    log(f"[EXIM] 환율 검증 데이터: USD={exim_map.get('USD')}, EUR={exim_map.get('EUR')}, JPY={exim_map.get('JPY')}")
        except Exception as e:
            log(f"[EXIM] 환율 오류: {e}")

    # ── 광물자원공사 (motir.go.kr) 원자재 가격 크롤링 ──────────
    try:
        log("[MOTIR] 광물자원공사 원자재 가격 수집 시작")
        motir_data = fetch_motir_commodities()
        if motir_data:
            data["commoditiesKr"] = motir_data
            data["sources"]["commoditiesKr"] = "motir.go.kr 광물자원공사"
    except Exception as e:
        log(f"[MOTIR] 오류: {e}")

    # ── 국민연금 자산배분 (NPS) ──────────────────────
    try:
        log("[NPS] 자산배분 크롤링 시작")
        nps_data = fetch_nps_allocation()
        if nps_data:
            data["nps"] = nps_data
            data["sources"]["nps"] = nps_data.get("source", "fund.nps.or.kr")
    except Exception as e:
        log(f"[NPS] 오류: {e}")

    # ── 시계열 데이터 (FX/지수/원자재 5년치) ──────────────────
    # 프런트엔드 차트가 더미(genSeries) 대신 실제 데이터를 사용하기 위함
    try:
        hist = fetch_all_historical_data()
        if hist:
            data["history"] = hist
            data["sources"]["history"] = "yfinance (FX/Indices/Commodities 5Y daily)"
    except Exception as e:
        log(f"[YF-HIST] 전체 수집 오류: {e}")

    # ── 뉴스 기사 (Google News RSS) ──────────────────
    # 클라이언트 CORS 프록시 의존도를 줄이기 위해 서버측에서 미리 가져와
    # data.json 에 저장. 프론트엔드는 이를 우선 사용하고, 실패 시 클라이언트 페치로 폴백.
    try:
        log("[News] Google News RSS 카테고리별 기사 수집 시작")
        news_data = fetch_news_all_feeds()
        if news_data:
            data["news"] = news_data
            data["sources"]["news"] = "Google News RSS (서버측 페치)"
            total = sum(len(v) for v in news_data.values()) - 1  # exclude 'lastFetched' field
            log(f"[News] 총 {total}건 기사 수집 완료")
    except Exception as e:
        log(f"[News] 수집 오류: {e}")

    return data


# ============================================================
# Google News RSS — 카테고리별 기사 사전 페치
# ============================================================
# 카테고리 키 = 프론트엔드 newsItems/commodityNewsItems/macroNewsItems/calendarNewsItems
# 의 item.cat 필드와 1:1 매칭. 갱신 시 cat 별로 최대 5건씩 가져와 frontend 에 주입.
NEWS_CATEGORY_QUERIES = {
    "채권":       "한국 국채 금리 동향",
    "외환":       "원달러 환율 시황",
    "주식":       "코스피 코스닥 시황",
    "원자재":     "WTI 국제유가 동향",
    "원유":       "WTI Brent 국제유가",
    "귀금속":     "금 시세 골드",
    "비철금속":   "LME 구리 가격 동향",
    "한국GDP":    "한국 GDP 성장률",
    "미국CPI":    "미국 CPI 인플레이션",
    "중국경기":   "중국 경기 PMI",
    "일본경기":   "일본 경기 BOJ",
    "독일경기":   "독일 경기 ZEW",
    "영국경기":   "영국 경기 BOE",
    "유로존":     "유로존 인플레이션 ECB",
    "한국수출":   "한국 수출 무역수지",
    "한국은행":   "한국은행 금통위 기준금리",
}


def _decode_gnews_url(g_url):
    """Google News RSS 의 base64 인코딩된 article URL 에서 원본 URL 추출."""
    try:
        m = re.search(r"/articles/([A-Za-z0-9_-]+)", g_url or "")
        if not m:
            return None
        b64 = m.group(1).replace("-", "+").replace("_", "/")
        b64 += "=" * (-len(b64) % 4)
        import base64
        raw = base64.b64decode(b64, validate=False).decode("latin-1", errors="ignore")
        idx = raw.find("http")
        if idx < 0:
            return None
        end = idx
        while end < len(raw) and 0x20 <= ord(raw[end]) < 0x7f:
            end += 1
        decoded = raw[idx:end]
        if re.match(r"^https?://[a-z0-9.\-]+\.[a-z]{2,}/", decoded, re.I):
            return decoded
    except Exception:
        pass
    return None


def _resolve_redirect(url, timeout=8):
    """Google News redirect URL 을 따라가 최종 publisher URL 획득.

    Google News URL 형식이 점진적으로 변하여 base64 디코드가 실패하는 케이스 보강.
    HTTP HEAD/GET 으로 redirect chain 을 따라가 r.url 의 최종 URL 을 반환.
    """
    try:
        # HEAD 가 redirect 정보를 더 빨리 줌
        r = requests.head(url, timeout=timeout, allow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"})
        if r.url and "news.google.com" not in r.url:
            return r.url
        # HEAD 가 차단되면 GET 으로 재시도 (stream=True 로 본문 받지 않음)
        r = requests.get(url, timeout=timeout, allow_redirects=True, stream=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.close()
        if r.url and "news.google.com" not in r.url:
            return r.url
    except Exception:
        pass
    return None


def _is_publisher_home(url):
    """URL 이 publisher 홈페이지인지 판정 — 경로 없거나 단순 슬래시일 때 True.

    예: https://www.yna.co.kr → True (홈페이지)
         https://www.yna.co.kr/view/AKR20260522 → False (기사)
    홈페이지 URL 은 기사 링크로 부적합하므로 다음 우선순위로 폴백해야 함.
    """
    if not url:
        return True
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        path = (p.path or "").strip("/")
        if not path or path in ("", "index.html", "main.html", "home", "main"):
            return True
        # 경로가 너무 짧으면 (예: /m, /news) 카테고리 페이지일 가능성 — 5자 미만이면 의심
        if len(path) < 5 and "?" not in url and "#" not in url:
            return True
        return False
    except Exception:
        return False


def _gnews_resolve_via_html(g_url, timeout=8):
    """Google News 기사 URL 을 HTML 페이지에서 redirect URL 추출.

    `news.google.com/articles/...` 페이지는 JS-based redirect 인 경우가 많아
    HTTP HEAD/GET 의 allow_redirects 로는 따라갈 수 없음. HTML 본문에서
    `data-n-au="<URL>"` 또는 meta refresh URL 을 직접 추출한다.
    """
    try:
        r = requests.get(
            g_url, timeout=timeout, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36"},
        )
        # 최종 redirect 가 news.google.com 외부면 그것이 publisher URL
        if r.url and "news.google.com" not in r.url:
            return r.url
        html = r.text or ""
        # 패턴 1: data-n-au="https://..."
        m = re.search(r'data-n-au="(https?://[^"]+)"', html)
        if m and "news.google.com" not in m.group(1):
            return m.group(1)
        # 패턴 2: <meta http-equiv="refresh" content="0;URL=https://...">
        m = re.search(r'http-equiv="refresh"[^>]*content="[^"]*URL=(https?://[^"]+)"', html, re.I)
        if m and "news.google.com" not in m.group(1):
            return m.group(1)
        # 패턴 3: JS 변수 안의 URL — "url":"https://..."
        m = re.search(r'"(https?://(?!news\.google\.com)[^"]+\.(?:html|do|asp|php|jsp|nhn|naver|kr/[^"]+))"', html)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _extract_real_url(item_xml):
    """RSS item XML 에서 실제 기사 URL 추출.

    우선순위 (publisher 홈페이지가 아닌 실제 기사 URL 을 얻는 데 최적화):
      1) description 내 외부 사이트 링크 (경로 있는 기사 URL)
      2) Google News URL base64 디코드 (성공 시 publisher 기사 URL)
      3) Google News URL HTML 페이지에서 redirect URL 추출 (JS-based redirect 회피)
      4) Google News URL HTTP redirect 추적 (HEAD/GET)
      5) source url 속성 — 단, publisher 홈페이지가 아닐 때만
      6) Google News URL 원본 (최후 — 브라우저가 클릭 시 redirect)
    """
    desc = ""
    link = ""
    guid = ""
    src_url = ""
    for child in item_xml:
        tag = child.tag.split("}")[-1]
        if tag == "description":
            desc = child.text or ""
        elif tag == "link":
            link = child.text or ""
        elif tag == "guid":
            guid = child.text or ""
        elif tag == "source":
            src_url = child.attrib.get("url", "")
    # 1) description 안의 외부 링크 (google news 외) — 가장 신뢰성 있는 기사 URL
    m = re.search(r'href="(https?://(?!news\.google\.com)[^"]+)"', desc)
    if m and not _is_publisher_home(m.group(1)):
        return m.group(1)
    # 2) Google News URL → base64 디코드
    for cand in (link, guid):
        if cand and "news.google.com" in cand:
            decoded = _decode_gnews_url(cand)
            if decoded and not _is_publisher_home(decoded):
                return decoded
    # 3) Google News HTML 페이지에서 redirect URL 추출 (JS-based)
    for cand in (link, guid):
        if cand and "news.google.com" in cand:
            resolved = _gnews_resolve_via_html(cand)
            if resolved and not _is_publisher_home(resolved):
                return resolved
    # 4) HTTP redirect 추적
    for cand in (link, guid):
        if cand and "news.google.com" in cand:
            resolved = _resolve_redirect(cand)
            if resolved and not _is_publisher_home(resolved):
                return resolved
    # 5) source url 속성 — publisher 홈페이지만 가능하므로 마지막 폴백
    if src_url and "news.google.com" not in src_url and not _is_publisher_home(src_url):
        return src_url
    # 6) 원본 Google News URL — 브라우저가 클릭 시 redirect 처리
    return link or guid or ""


def fetch_news_articles(query, count=5, timeout=10):
    """Google News RSS 에서 query 에 매칭되는 최신 기사 리스트 반환.

    GHA 러너 IP가 Google News에 차단되는 케이스 회피 — 직접 → CORS 프록시 폴백.

    반환: [{"title": str, "url": str, "isoDate": "YYYY-MM-DD", "pubDate": str}]
    """
    rss_url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ko&gl=KR&ceid=KR:ko"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml,application/xml,text/xml,*/*",
    }
    xml_text = None
    candidates = [
        rss_url,
        f"https://corsproxy.io/?{quote_plus(rss_url)}",
        f"https://api.allorigins.win/raw?url={quote_plus(rss_url)}",
        f"https://api.codetabs.com/v1/proxy/?quest={quote_plus(rss_url)}",
    ]
    for url in candidates:
        try:
            r = requests.get(url, timeout=timeout, headers=headers)
            if r.status_code == 200 and r.text and len(r.text) > 100:
                xml_text = r.text
                break
            else:
                continue
        except Exception:
            continue
    if not xml_text:
        log(f"[News] '{query}' 모든 시도 실패 (Google News 차단)")
        return []
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except Exception as e:
        log(f"[News] '{query}' RSS XML 파싱 실패: {e}")
        return []
    out = []
    for item in root.iter("item"):
        title_el = item.find("title")
        pub_el = item.find("pubDate")
        title = (title_el.text or "").strip() if title_el is not None else ""
        # Google News 가 "제목 - 출처" 형식으로 붙이는 suffix 제거
        title = re.sub(r"\s*-\s*[^-]+$", "", title).strip()
        pub_date = (pub_el.text or "").strip() if pub_el is not None else ""
        iso_date = None
        if pub_date:
            try:
                from email.utils import parsedate_to_datetime
                iso_date = parsedate_to_datetime(pub_date).strftime("%Y-%m-%d")
            except Exception:
                iso_date = None
        url = _extract_real_url(item)
        if title and url:
            out.append({"title": title, "url": url, "isoDate": iso_date or "", "pubDate": pub_date})
        if len(out) >= count:
            break
    if out:
        log(f"[News] '{query}' {len(out)}건 수집 (1위: {out[0]['title'][:30]}…)")
    else:
        log(f"[News] '{query}' 기사 없음")
    return out


def fetch_naver_search_news(query, count=5, timeout=8):
    """네이버 검색 OpenAPI 로 뉴스 검색 — 공식 API, 안정적이고 실제 기사 URL 반환.

    NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 가 secrets 에 설정된 경우에만 동작.
    Google News 가 실패한 카테고리 보강용.
    """
    if not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET):
        return []
    try:
        r = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            params={"query": query, "display": count, "sort": "date"},
            headers={
                "X-Naver-Client-Id": NAVER_CLIENT_ID,
                "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
                "User-Agent": "economic-site/1.0",
            },
            timeout=timeout,
        )
        if r.status_code != 200:
            log(f"[NaverSearch] '{query}' HTTP {r.status_code} {r.text[:200]}")
            return []
        items = r.json().get("items", [])
    except Exception as e:
        log(f"[NaverSearch] '{query}' 오류: {e}")
        return []
    out = []
    for it in items[:count]:
        # 네이버 검색 API 는 HTML 엔티티/태그를 포함해 반환 → 제거
        title = re.sub(r"<[^>]+>", "", it.get("title", "")).replace("&quot;", '"') \
                  .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()
        # originallink 가 publisher 의 원본 기사 URL (네이버 link 보다 우선)
        url = (it.get("originallink") or it.get("link") or "").strip()
        pub_date = it.get("pubDate", "")
        iso_date = ""
        if pub_date:
            try:
                from email.utils import parsedate_to_datetime
                iso_date = parsedate_to_datetime(pub_date).strftime("%Y-%m-%d")
            except Exception:
                iso_date = ""
        if title and url:
            out.append({"title": title, "url": url, "isoDate": iso_date, "pubDate": pub_date})
    if out:
        log(f"[NaverSearch] '{query}' {len(out)}건 수집 (1위: {out[0]['title'][:30]}…)")
    return out


def fetch_news_all_feeds():
    """모든 카테고리 별로 최대 5건씩 페치하여 카테고리→[articles] 매핑 반환.

    페치 순서 (publisher 홈페이지가 아닌 실제 기사 URL 우선):
      1) Naver Search API (originallink = publisher 직접 기사 URL, NAVER_CLIENT_ID/SECRET 있을 때)
      2) Google News RSS (직접 + CORS 프록시 폴백, URL 검증 통과한 것만)
      3) 두 결과 합쳐 최대 5건 (publisher 홈페이지 URL 은 제외, 중복 url 제거)

    실패한 카테고리는 빈 리스트로 채우고, 나머지는 전부 시도.
    """
    result = {"lastFetched": datetime.now(KST).isoformat()}
    naver_available = bool(NAVER_CLIENT_ID and NAVER_CLIENT_SECRET)
    if naver_available:
        log("[News] 네이버 검색 OpenAPI 활성 (PRIMARY)")
    else:
        log("[News] NAVER_CLIENT_ID/SECRET 미설정 — Google News RSS 만 사용 (publisher 홈페이지 URL 회귀 위험 ↑)")

    def _is_good_article_url(u):
        """기사 URL 검증 — 빈 값, google news 직링크, publisher 홈페이지는 제외."""
        if not u or u == "#":
            return False
        if "news.google.com" in u:
            return False  # 디코드 실패한 raw google URL 은 클릭해도 redirect 안 따라가므로 제외
        if _is_publisher_home(u):
            return False
        return True

    for cat, query in NEWS_CATEGORY_QUERIES.items():
        articles = []
        seen_urls = set()
        # 1) Naver Search 우선 — originallink 가 publisher 직접 기사 URL
        if naver_available:
            try:
                for na in fetch_naver_search_news(query, count=8):
                    if _is_good_article_url(na["url"]) and na["url"] not in seen_urls:
                        articles.append(na)
                        seen_urls.add(na["url"])
                        if len(articles) >= 5:
                            break
            except Exception as e:
                log(f"[NaverSearch] '{cat}' 예외: {e}")
        # 2) Google News RSS 로 부족분 보강
        if len(articles) < 5:
            try:
                for ga in fetch_news_articles(query, count=10):
                    if _is_good_article_url(ga["url"]) and ga["url"] not in seen_urls:
                        articles.append(ga)
                        seen_urls.add(ga["url"])
                        if len(articles) >= 5:
                            break
            except Exception as e:
                log(f"[News] Google '{cat}' 예외: {e}")
        # 3) 그래도 부족하면 Naver Search 키워드를 좀 더 일반화해서 재시도
        if len(articles) < 3 and naver_available:
            try:
                for na in fetch_naver_search_news(query.split()[0], count=8):
                    if _is_good_article_url(na["url"]) and na["url"] not in seen_urls:
                        articles.append(na)
                        seen_urls.add(na["url"])
                        if len(articles) >= 5:
                            break
            except Exception:
                pass
        result[cat] = articles[:5]
        _time.sleep(0.3)  # rate-limit 회피
    return result


if __name__ == "__main__":
    log("=== 시장 데이터 수집 시작 ===")
    for name, key in [
        ("KRX",         KRX_API_KEY),
        ("FRED",        FRED_API_KEY),
        ("ECOS",        ECOS_API_KEY),
        ("R-ONE",       REALESTATE_API_KEY),
        ("KOSIS",       KOSIS_API_KEY),
        ("data.go.kr",  DATA_GO_KR_API_KEY),
        ("EXIM",        EXIM_API_KEY),
        ("KIS",         KIS_APP_KEY),
        ("NaverSearch", NAVER_CLIENT_ID),
    ]:
        if key:
            log(f"[{name}] API 키 설정됨 ({key[:4]}...{key[-4:]})")
        else:
            log(f"[{name}] API 키 없음")
    # 추가 상태 로그 — 어떤 데이터 소스가 활성/비활성인지 명확히
    log(f"[STATE] pykrx 가용: {_PYKRX_AVAILABLE} (False 면 pip install pykrx 필요)")
    log(f"[STATE] KIS_ENABLED={KIS_ENABLED} (False 면 KIS 토큰 발급 안함 = 카카오톡 알람 없음)")
    d = build_data()
    output_path = "data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    log(f"=== 완료: {d['lastUpdated']} → {output_path} ===")
    log(f"[RESULT] stockMovers: {d['diagnostics'].get('stockMoversSource','-')}")
    log(f"[RESULT] etfMovers:   {d['diagnostics'].get('etfMoversSource','-')}")
    news = d.get("news", {})
    total_news = sum(len(v) for k, v in news.items() if k != "lastFetched" and isinstance(v, list))
    log(f"[RESULT] news:        {total_news}건 ({len([k for k,v in news.items() if k != 'lastFetched' and v])}/16 카테고리)")
