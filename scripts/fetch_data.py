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
# R-ONE (한국부동산원) — 키는 GitHub Secrets(REALESTATE_API_KEY) 로만 주입한다.
# ⚠️ 코드에 기본값(개인 키) 하드코딩 금지: 공개 저장소라 키가 그대로 유출된다.
#    미설정 시 해당 수집은 건너뛰며(각 함수의 `if not REALESTATE_API_KEY` 가드), 기존 data.json 값이 유지된다.
REALESTATE_API_KEY= os.environ.get("REALESTATE_API_KEY","").strip()
KOSIS_API_KEY     = os.environ.get("KOSIS_API_KEY",     "").strip()
# 신규: Alpha Vantage API — 미국 경제지표/원자재/FX 보강. 키는 GitHub Secrets(ALPHAVANTAGE_API_KEY) 로만 주입.
# ⚠️ 코드에 기본값(개인 키) 하드코딩 금지: 공개 저장소라 키가 그대로 유출된다. 미설정 시 보강은 건너뜀.
# 일 25회/분당 5회 무료 한도 → 매 시간 호출은 피하고 09:00/22:00 KST 일일 갱신에서만 사용.
ALPHAVANTAGE_API_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
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
# R-ONE 표준 지역분류 코드: 전국=500001 (500002 수도권, 500003 지방권, 500008 서울 …).
# SttsApiTblData 는 날짜범위를 무시하고 모든 지역을 오래된 순으로 반환하므로, 전국 최신값을
# 얻으려면 반드시 CLS_ID=500001 로 지역을 한정해야 한다 (GHA 프로브로 확인).
RONE_NATIONWIDE_CLS = "500001"
KOSIS_BASE   = "https://kosis.kr/openapi/statisticsData.do"
DATA_GO_KR_BASE = "http://apis.data.go.kr"
EXIM_BASE       = "https://www.koreaexim.go.kr/site/program/financial/exchangeJSON"
ALPHAVANTAGE_BASE = "https://www.alphavantage.co/query"
BOE_IADB_BASE     = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"

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

# KRX 로그인 가능 여부 — 2026 부터 KRX 정보데이터시스템이 로그인을 요구하기 시작했다.
# pykrx 1.2.x 는 KRX_ID/KRX_PW 환경변수가 있으면 import 시 자동 로그인하며, 없으면
# 익명 접근을 시도하나 KRX 가 거부해 데이터가 비는 경우가 많다(투자자별 순매매가 대표적).
# 워크플로 Secrets(KRX_ID/KRX_PW)에 data.krx.co.kr 무료 계정을 등록하면 정상화된다.
_KRX_LOGIN_AVAILABLE = bool(os.environ.get("KRX_ID", "").strip() and os.environ.get("KRX_PW", "").strip())
if _PYKRX_AVAILABLE and not _KRX_LOGIN_AVAILABLE:
    log("[KRX-login] KRX_ID/KRX_PW 미설정 — pykrx 익명 접근 시도(투자자별 순매매 등 일부 데이터가 거부될 수 있음). "
        "data.krx.co.kr 무료 가입 후 Secrets 에 KRX_ID/KRX_PW 등록 권장.")


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


def _fetch_investor_pykrx(lookback_days=400):
    """투자자별(외국인/기관/개인) 일별 순매수 추이 — pykrx 실데이터 (KRX 로그인 시).

    KRX 정보데이터시스템의 '투자자별 거래실적(일별 순매수 거래대금)' 을 KOSPI+KOSDAQ
    합산해 가져온다. 단위는 억원(1e8 원). **더미/랜덤 데이터는 절대 쓰지 않는다** —
    pykrx 가 없거나 응답이 비면 빈 dict 를 반환하고, 호출자가 Naver 폴백을 시도한다.

    Returns: {"daily":[{date, foreign, inst, retail}...], "markets":[...],
              "unit":"억원", "source":..., "lastFetched":...} 또는 {}.
    """
    if not _PYKRX_AVAILABLE:
        log("[투자자] pykrx 미설치 — 투자자별 매매동향 건너뜀")
        return {}
    fn = getattr(_pykrx_stock, "get_market_trading_value_by_date", None)
    if fn is None:
        log("[투자자] pykrx get_market_trading_value_by_date 미지원 — 건너뜀")
        return {}
    now = datetime.now(KST)
    todate = next(iter(_last_kr_business_day()), now.strftime("%Y%m%d"))
    fromdate = (now - timedelta(days=lookback_days)).strftime("%Y%m%d")

    agg = {}            # date -> {foreign, inst, retail} (억원)
    markets_ok = []
    for mkt in ("KOSPI", "KOSDAQ"):
        try:
            df = fn(fromdate, todate, mkt)
        except Exception as e:
            log(f"[투자자] {mkt} 조회 오류: {e}")
            continue
        if df is None or getattr(df, "empty", True):
            log(f"[투자자] {mkt} 응답 없음/비어있음")
            continue
        cols = [str(c) for c in df.columns]

        def _find_col(*keywords, exclude=()):
            for c in cols:
                if any(k in c for k in keywords) and not any(x in c for x in exclude):
                    return c
            return None
        # KRX 투자자 분류 컬럼: 기관합계 / 기타법인 / 개인 / 외국인합계 / 기타외국인 / 전체
        col_foreign = _find_col("외국인합계") or _find_col("외국인", exclude=("기타외국인",))
        col_inst    = _find_col("기관합계") or _find_col("기관")
        col_retail  = _find_col("개인")
        if not (col_foreign and col_inst and col_retail):
            log(f"[투자자] {mkt} 투자자 컬럼 매칭 실패 — 컬럼={cols}")
            continue

        def _eok(v):
            try:
                return float(v) / 1e8
            except (TypeError, ValueError):
                return 0.0
        n = 0
        for idx, row in df.iterrows():
            try:
                dstr = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else (
                    (lambda s: s[:10] if "-" in s else f"{s[:4]}-{s[4:6]}-{s[6:8]}")(str(idx)))
            except Exception:
                continue
            rec = agg.setdefault(dstr, {"foreign": 0.0, "inst": 0.0, "retail": 0.0})
            rec["foreign"] += _eok(row[col_foreign])
            rec["inst"]    += _eok(row[col_inst])
            rec["retail"]  += _eok(row[col_retail])
            n += 1
        if n:
            markets_ok.append(mkt)
            log(f"[투자자] {mkt} {n}일 수집 (외국인={col_foreign}/기관={col_inst}/개인={col_retail})")

    if not agg or not markets_ok:
        log("[투자자] pykrx 미수집 (KRX 로그인 미설정/응답 없음) — Naver 폴백 시도 예정.")
        return {}
    daily = [{
        "date": d,
        "foreign": round(agg[d]["foreign"], 1),
        "inst":    round(agg[d]["inst"], 1),
        "retail":  round(agg[d]["retail"], 1),
    } for d in sorted(agg.keys())]
    last = daily[-1]
    log(f"[투자자] 완료: {len(daily)}일 ({'+'.join(markets_ok)}) 최근일={last['date']} "
        f"외국인={last['foreign']:+.0f}억 기관={last['inst']:+.0f}억 개인={last['retail']:+.0f}억")
    return {
        "daily": daily,
        "markets": markets_ok,
        "unit": "억원",
        "source": "pykrx 투자자별 거래실적 (KRX 정보데이터시스템)",
        "lastFetched": now.isoformat(),
    }


def fetch_naver_investor_trading(lookback_days=400):
    """투자자별 순매수 — 네이버 금융 무인증 폴백 (KRX 로그인/KIS 키/카카오 알람 불필요).

    finance.naver.com/sise/sise_index_buyer.naver?code=KOSPI|KOSDAQ 의 일별 표에서
    개인/외국인/기관 순매수를 추출해 KOSPI+KOSDAQ 합산(억원). HTML 구조 변동에 대비해
    표/컬럼을 헤더 키워드로 동적 매핑하고, 단위는 값 크기로 자동 감지한다. 구조 불일치 시
    빈 dict 를 반환(더미 절대 미사용) — CI 로그의 raw 샘플로 파싱을 점검/보정할 수 있다.
    """
    try:
        from bs4 import BeautifulSoup
    except Exception:
        log("[투자자-Naver] bs4 미설치 — 건너뜀")
        return {}
    import re as _re
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
        "Referer": "https://finance.naver.com/sise/",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    date_re = _re.compile(r"\d{2,4}\.\d{1,2}\.\d{1,2}")

    def _num(s):
        s = (s or "").replace(",", "").replace("+", "").strip()
        if not s or s in ("-", "—", "·"):
            return None
        try:
            return float(s)
        except ValueError:
            return None

    agg, markets_ok, raw_samples = {}, [], []
    for mkt in ("KOSPI", "KOSDAQ"):
        try:
            url = f"https://finance.naver.com/sise/sise_index_buyer.naver?code={mkt}"
            r = requests.get(url, headers=hdrs, timeout=15)
            r.encoding = "euc-kr"
            soup = BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            log(f"[투자자-Naver] {mkt} 요청 오류: {e}")
            continue
        target, colmap, hdr_text = None, {}, ""
        for tbl in soup.find_all("table"):
            ttext = tbl.get_text(" ", strip=True)
            if not ("개인" in ttext and "외국인" in ttext and "기관" in ttext):
                continue
            for tr in tbl.find_all("tr"):
                cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
                cm = {}
                for i, ct in enumerate(cells):
                    if "개인" in ct and "retail" not in cm:
                        cm["retail"] = i
                    elif "외국인" in ct and "기타" not in ct and "foreign" not in cm:
                        cm["foreign"] = i
                    elif "기관" in ct and "inst" not in cm:
                        cm["inst"] = i
                if len(cm) == 3:
                    colmap, target, hdr_text = cm, tbl, " | ".join(cells)
                    break
            if target:
                break
        if not target:
            log(f"[투자자-Naver] {mkt} 표/컬럼 매핑 실패 — 건너뜀")
            continue
        n = 0
        for tr in target.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            dcell = next((c for c in cells if date_re.fullmatch(c.replace(" ", ""))), None)
            if not dcell or len(cells) <= max(colmap.values()):
                continue
            f, ins, ret = (_num(cells[colmap["foreign"]]), _num(cells[colmap["inst"]]), _num(cells[colmap["retail"]]))
            if f is None and ins is None and ret is None:
                continue
            p = dcell.replace(" ", "").split(".")
            if len(p) != 3:
                continue
            y = p[0] if len(p[0]) == 4 else ("20" + p[0] if len(p[0]) == 2 else str(datetime.now(KST).year))
            try:
                dstr = f"{int(y):04d}-{int(p[1]):02d}-{int(p[2]):02d}"
            except ValueError:
                continue
            rec = agg.setdefault(dstr, {"foreign": 0.0, "inst": 0.0, "retail": 0.0})
            rec["foreign"] += (f or 0.0); rec["inst"] += (ins or 0.0); rec["retail"] += (ret or 0.0)
            n += 1
            if len(raw_samples) < 4:
                raw_samples.append((mkt, dstr, f, ins, ret))
        if n:
            markets_ok.append(mkt)
            log(f"[투자자-Naver] {mkt} {n}행 (헤더='{hdr_text[:80]}')")
    if not agg:
        log("[투자자-Naver] 수집 실패 — 빈 결과 (프론트 '수집 중')")
        return {}
    # 단위 자동 감지 — 순매수 거래대금이 백만원 단위면 ÷100 으로 억원 정규화
    allvals = sorted(abs(v) for r in agg.values() for v in r.values() if v)
    median = allvals[len(allvals) // 2] if allvals else 0
    scale = 0.01 if median > 100000 else 1.0
    log(f"[투자자-Naver] 샘플={raw_samples} median={median:.0f} scale={scale} → {len(agg)}일")
    daily = [{
        "date": d,
        "foreign": round(agg[d]["foreign"] * scale, 1),
        "inst":    round(agg[d]["inst"] * scale, 1),
        "retail":  round(agg[d]["retail"] * scale, 1),
    } for d in sorted(agg.keys())][-lookback_days:]
    return {
        "daily": daily,
        "markets": markets_ok,
        "unit": "억원",
        "source": "Naver 금융 투자자별 매매동향 (무인증 폴백)",
        "lastFetched": datetime.now(KST).isoformat(),
    }


def fetch_investor_trading(lookback_days=400):
    """투자자별 순매수 — pykrx(KRX 로그인) 우선, 실패 시 Naver 무인증 폴백.

    우선순위: ① pykrx(KRX_ID/KRX_PW 설정 시 — 전체 시계열, 가장 정확)
              ② KIS 한국투자증권 API(KIS_ENABLED=1 시 — 최신 영업일)
              ③ Naver 금융 파싱(무인증·무알람 — 최근 수십일 시계열).
    모두 실패하면 빈 dict (프론트 '수집 중' 안내; 더미 절대 미사용).
    """
    res = _fetch_investor_pykrx(lookback_days)
    if res.get("daily"):
        return res
    # ② KIS — 한국투자증권 OpenAPI (KIS_ENABLED=1 일 때만 토큰 발급/호출)
    try:
        kis = fetch_kis_investor_trading()
        if kis.get("daily"):
            return kis
    except Exception as e:
        log(f"[투자자-KIS] 오류(무시): {e}")
    return fetch_naver_investor_trading(lookback_days)


# 해상 운임지수(운송) — SCFI/CCFI/BDI 등. 네이버 금융 '시장지표 > 운송' 표시 항목.
# 무료·검증 가능한 공개 API가 없어 네이버 신(新) 금융 마켓 API 를 best-effort 로 시도한다.
# (GitHub Actions 러너는 네이버 접근 가능. 엔드포인트/필드는 배포 후 로그로 검증·보정.)
FREIGHT_INDEX_META = [
    # (코드, 표시명, 거래소)
    ("SCFI", "상하이컨테이너 운임지수", "상하이해운거래소(SSE)"),
    ("CCFI", "중국컨테이너 운임지수", "상하이해운거래소(SSE)"),
    ("BDI",  "BDI 건화물선지수",       "발틱해운거래소(BDI)"),
    ("BCI",  "BCI 케이프사이즈지수",   "발틱해운거래소(BDI)"),
    ("BPI",  "BPI 파나막스지수",       "발틱해운거래소(BDI)"),
    ("BSI",  "BSI 수프라막스지수",     "발틱해운거래소(BDI)"),
    ("BHI",  "BHI 핸디사이즈지수",     "발틱해운거래소(BDI)"),
    ("BDTI", "BDTI 원유유조선지수",    "발틱해운거래소(BDI)"),
    ("BCTI", "BCTI 석유제품선지수",    "발틱해운거래소(BDI)"),
]


def _freight_num(v):
    try:
        return float(str(v).replace(",", "").replace("+", "").replace("\xa0", "").strip())
    except (TypeError, ValueError):
        return None


def _freight_from_naver():
    """네이버 신(新) 금융 시장지표 '운송' JSON API 후보들을 시도. {code: item} 반환.
    (엔드포인트가 비공개라 여러 후보를 시도 — 성공 후보는 배포 로그로 확인해 고정.)"""
    hdrs = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://m.stock.naver.com/",
        "Origin": "https://m.stock.naver.com",
    }
    candidates = [
        "https://api.stock.naver.com/marketindex/shipping/prices",
        "https://api.stock.naver.com/marketindex/shippings",
        "https://api.stock.naver.com/marketindex/category/shipping",
        "https://api.stock.naver.com/marketindex/shipping",
        "https://api.stock.naver.com/marketindex/transport",
        "https://m.stock.naver.com/api/marketindex/shippings",
    ]
    code_kw = [(c, n) for (c, n, _x) in FREIGHT_INDEX_META]
    out = {}
    for url in candidates:
        try:
            r = requests.get(url, headers=hdrs, timeout=12)
            if r.status_code != 200:
                log(f"[운임-Naver] {url} HTTP {r.status_code}")
                continue
            data = r.json()
        except Exception as e:
            log(f"[운임-Naver] {url} 오류: {e}")
            continue
        rows = data if isinstance(data, list) else (
            data.get("result") or data.get("list") or data.get("datas") or data.get("items") or [])
        if not isinstance(rows, list) or not rows:
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = (row.get("indexName") or row.get("name") or row.get("itemName")
                    or row.get("korName") or "").strip()
            price = _freight_num(row.get("closePrice") or row.get("nowVal") or row.get("nowValue")
                                 or row.get("value") or row.get("price"))
            if not name or price is None:
                continue
            code = next((c for (c, kw) in code_kw if kw[:4] in name or c in name.upper()), None)
            if not code:
                continue
            out[code] = {
                "code": code, "price": price,
                "change": _freight_num(row.get("compareToPreviousClosePrice") or row.get("changeVal") or row.get("change")),
                "chgPct": _freight_num(row.get("fluctuationsRatio") or row.get("changeRate") or row.get("chgPct")),
                "date": (str(row.get("localTradedAt") or row.get("tradeDate") or row.get("date") or ""))[:10],
            }
        if out:
            log(f"[운임-Naver] {url} → {len(out)}건 {list(out)}")
            return out
    return out


def _freight_from_stockq():
    """StockQ.org 에서 BDI 현재값/등락 스크래핑(정적 HTML). {code: item}."""
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return {}
    import re as _re
    out = {}
    hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"}
    for code, url in (("BDI", "https://en.stockq.org/index/BDI.php"),):
        try:
            r = requests.get(url, headers=hdrs, timeout=12)
            if r.status_code != 200:
                log(f"[운임-StockQ] {code} HTTP {r.status_code}")
                continue
            soup = BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            log(f"[운임-StockQ] {code} 오류: {e}")
            continue
        # StockQ 지수 페이지: 최신 데이터 행 = [날짜, 지수, 등락, 등락%] (첫 일치 행 채택)
        for tr in soup.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all("td")]
            if len(cells) < 2:
                continue
            if _re.match(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", cells[0]) or _re.match(r"\d{1,2}/\d{1,2}", cells[0]):
                nums = [x for x in (_freight_num(c) for c in cells[1:]) if x is not None]
                if nums:
                    out[code] = {
                        "code": code, "price": nums[0],
                        "change": nums[1] if len(nums) > 1 else None,
                        "chgPct": nums[2] if len(nums) > 2 else None,
                        "date": cells[0].replace("/", "-")[:10],
                    }
                    log(f"[운임-StockQ] {code} {nums[0]} ({cells[0]})")
                    break
    return out


def _freight_from_sse():
    """상하이항운거래소(SSE) 영문 페이지에서 SCFI/CCFI 종합지수 스크래핑."""
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return {}
    import re as _re
    out = {}
    hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"}
    for code, url in (("SCFI", "https://en.sse.net.cn/indices/scfinew.jsp"),
                      ("CCFI", "https://en.sse.net.cn/indices/ccfinew.jsp")):
        try:
            r = requests.get(url, headers=hdrs, timeout=12)
            if r.status_code != 200:
                log(f"[운임-SSE] {code} HTTP {r.status_code}")
                continue
            r.encoding = r.apparent_encoding or "utf-8"
            text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
        except Exception as e:
            log(f"[운임-SSE] {code} 오류: {e}")
            continue
        # 'Comprehensive Index ... 1234.56' 패턴
        m = _re.search(r"(?:Comprehensive Index|综合指数)[^\d]{0,30}([\d,]+\.\d+)", text)
        if m:
            out[code] = {"code": code, "price": _freight_num(m.group(1)),
                         "change": None, "chgPct": None, "date": ""}
            log(f"[운임-SSE] {code} {m.group(1)}")
        else:
            log(f"[운임-SSE] {code} 패턴 미일치")
    return out


def fetch_freight_indices():
    """해상 운임지수(SCFI/CCFI/BDI 계열) 웹 스크래핑(무료 공개 API 부재 → 다중 소스).

    소스 우선순위: ① 네이버 시장지표(운송, 전 항목) ② StockQ(BDI) ③ SSE(SCFI/CCFI).
    각 소스가 주는 코드만 채우고 병합한다. 표시명/거래소는 FREIGHT_INDEX_META 로 통일.
    반환: {"items":[...], "source", "lastFetched"} / 전부 실패 시 {}.
    """
    meta_name = {c: n for (c, n, _x) in FREIGHT_INDEX_META}
    exch = {c: x for (c, _n, x) in FREIGHT_INDEX_META}
    collected = {}
    for strat in (_freight_from_naver, _freight_from_stockq, _freight_from_sse):
        try:
            got = strat() or {}
        except Exception as e:
            log(f"[운임] {strat.__name__} 오류: {e}")
            got = {}
        for code, it in got.items():
            if code not in collected and it.get("price") is not None:
                collected[code] = it
    if not collected:
        log("[운임] 전 소스 수집 실패 — 빈 결과")
        return {}
    items = []
    for (c, n, x) in FREIGHT_INDEX_META:
        if c in collected:
            it = collected[c]
            it["name"] = n
            it["exchange"] = x
            items.append(it)
    log(f"[운임] 총 {len(items)}건 수집: {[i['code'] for i in items]}")
    return {
        "items": items,
        "source": "해상운임 스크래핑(네이버/StockQ/SSE)",
        "lastFetched": datetime.now(KST).isoformat(),
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


# 주요 한국 ETF 30종 (Yahoo Finance 심볼) — pykrx/Naver 모두 실패 시 폴백
# KODEX/TIGER/KBSTAR 주력 ETF 위주, 시가총액·거래대금 상위
# ETF 코드 매핑: data.krx.co.kr 통계 기반 (2026년 5월 기준 상위 ETF)
YF_KR_ETF_FALLBACK = [
    ("069500.KS", "KODEX 200"),
    ("102110.KS", "TIGER 200"),
    ("114800.KS", "KODEX 인버스"),
    ("122630.KS", "KODEX 레버리지"),
    ("233740.KS", "KODEX 코스닥150 레버리지"),
    ("251340.KS", "KODEX 코스닥150선물인버스"),
    ("252670.KS", "KODEX 200선물인버스2X"),
    ("305720.KS", "KODEX 2차전지산업"),
    ("091170.KS", "KODEX 은행"),
    ("091160.KS", "KODEX 반도체"),
    ("139660.KS", "TIGER 200IT"),
    ("117460.KS", "KODEX 에너지화학"),
    ("139260.KS", "TIGER 200 IT"),
    ("305540.KS", "TIGER 2차전지테마"),
    ("371460.KS", "TIGER 차이나전기차SOLACTIVE"),
    ("098560.KS", "TIGER 방송통신"),
    ("228790.KS", "TIGER 화장품"),
    ("228810.KS", "TIGER 미디어컨텐츠"),
    ("117700.KS", "KODEX 철강"),
    ("139220.KS", "TIGER 200건설"),
    ("266150.KS", "KBSTAR 200건설"),
    ("139250.KS", "TIGER 200에너지화학"),
    ("261240.KS", "KODEX 미국S&P500선물(H)"),
    ("133690.KS", "TIGER 미국나스닥100"),
    ("360750.KS", "TIGER 미국S&P500"),
    ("381170.KS", "TIGER 미국필라델피아반도체나스닥"),
    ("114260.KS", "KODEX 국고채3년"),
    ("130680.KS", "TIGER 원유선물Enhanced(H)"),
    ("132030.KS", "KODEX 골드선물(H)"),
    ("139310.KS", "TIGER 200금융"),
]


def fetch_yf_kr_etf_movers(top_n=10):
    """yfinance 로 주요 한국 ETF 30종 일일 등락률 폴백 조회.

    pykrx + Naver 모두 실패 시 마지막 폴백. yfinance 는 globally accessible 하여
    GHA IP 차단 가능성이 가장 낮음. 단, 한국 ETF 30종만 커버하므로 'Top10' 의
    품질은 시장 전체 대비 약간 떨어질 수 있음.
    """
    today = datetime.now(KST).strftime("%Y-%m-%d")
    parsed = []
    for sym, name in YF_KR_ETF_FALLBACK:
        try:
            res = fetch_yf(sym)
            if not res:
                continue
            code = sym.split(".")[0]
            parsed.append({
                "name": name,
                "code": code,
                "price": res.get("price"),
                "chg": res.get("change", 0.0),
                "as_of": today,
            })
        except Exception:
            continue
    if len(parsed) < 5:
        log(f"[YF-ETF] 폴백 데이터 부족 ({len(parsed)}건) — 사용 불가")
        return None, None
    non_zero = [p for p in parsed if p["chg"] != 0]
    if len(non_zero) < 3:
        log(f"[YF-ETF] 등락률이 대부분 0 — 사용 불가")
        return None, None
    gainers = sorted(parsed, key=lambda x: x["chg"] or 0, reverse=True)[:top_n]
    losers = sorted(parsed, key=lambda x: x["chg"] or 0)[:top_n]
    log(f"[YF-ETF] 폴백 성공: {len(parsed)}건 (gainers/losers 각 {top_n})")
    return gainers, losers


# ============================================================
# FRED API (미국 경제 지표)
# ============================================================
def fetch_fred_series(series_id, limit=1):
    """FRED API에서 시계열 데이터 최신값 조회.

    일시적 네트워크/FRED 응답 지연으로 단발 실패하면 그 시리즈(예: VIXCLS)가
    통째로 누락되고, 그 누락이 _preserve_*() 로도 못 막히는 케이스가 있었다.
    (KST 09:00 일일 풀런이 FRED 전체를 한 번에 호출 → 한 번의 블립이 us/uk 의
     FRED 지표 16개를 날렸음.) 짧은 백오프로 최대 3회 재시도하여 전수 손실을 방지.
    """
    if not FRED_API_KEY:
        return None
    last_err = None
    for attempt in range(3):
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
                timeout=20,
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
            last_err = e
            if attempt < 2:
                _time.sleep(1.5 * (attempt + 1))  # 1.5s, 3s 백오프
    log(f"[FRED] {series_id} 오류(재시도 3회 소진): {last_err}")
    return None


def fetch_fred_latest(series_id):
    """FRED 최신값 (float) 반환."""
    obs = fetch_fred_series(series_id)
    if obs:
        return obs[0]["value"]
    return None


def fetch_dubai_crude():
    """두바이 현물유 가격 — FRED POILDUBUSDM (Global price of Dubai Crude, USD/bbl).

    두바이유는 중동·아시아 원유의 핵심 벤치마크지만 무료 '일별 현물' API 가 드물다.
    FRED 의 IMF 기반 시리즈(월간, 약 1~2개월 지연)로 신뢰성 있는 값과 시계열을 확보한다.
    yfinance 에는 두바이 현물/선물 티커가 없어 FRED 가 가장 안정적인 무료 소스.
    Returns: ({"price","change"}, history[{date,close}...] asc) 또는 (None, None).
    """
    obs = fetch_fred_series("POILDUBUSDM", limit=72)  # 최근 6년치 월간 (desc 정렬)
    if not obs:
        return None, None
    # 이상치 제거 — FRED 최신 관측치가 가끔 비정상값으로 들어온다(예: 2026-03 에 126.71 로 +85%).
    # 월간 원유가는 ±45% 넘게 튀지 않으므로, '과거→현재' 순으로 보며 직전 유효값 대비
    # 과도하게 벗어난 점(주로 맨 끝 최신 점)을 버린다.
    asc = [o for o in reversed(obs) if o.get("value") and o["value"] > 0]
    if not asc:
        return None, None
    clean = []
    for o in asc:  # 과거 → 현재
        v = o["value"]
        if clean:
            ref = clean[-1]["value"]  # 직전(더 과거) 유효값
            if ref and abs(v - ref) / ref > 0.45:
                log(f"[FRED] 두바이유 이상치 제외: {o.get('date')}={v} (직전 {ref})")
                continue
        clean.append({"date": o["date"], "value": v})
    latest = clean[-1]["value"]
    prev = clean[-2]["value"] if len(clean) > 1 else latest
    change = ((latest - prev) / prev * 100.0) if prev else 0.0
    hist = [{"date": o["date"], "close": round(o["value"], 2)} for o in clean]
    return {"price": round(latest, 2), "change": round(change, 2)}, hist


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
        # 미국 GDP '성장률' — BEA 헤드라인(실질, 전기비 연율 SAAR). 캘린더용.
        # gdp_us(명목 수준)의 단순 전기비%는 발표치(예: +1.6%)와 다르므로 별도 시리즈 사용.
        "gdp_growth_us":("A191RL1Q225SBEA", "미국 실질GDP 성장률 (전기비 연율, BEA)"),
        "hy_spread":   ("BAMLH0A0HYM2",    "HY 크레딧 스프레드"),
        "us10y":       ("GS10",            "미국 10년 국채"),
        "us2y":        ("GS2",             "미국 2년 국채"),
        # ⚠ DXY 는 FRED 에 없음. 아래는 Broad Dollar Index (참고용, 1월 2006=100 베이스).
        # 실제 DXY (1973=100, ICE 발표) 는 fetch_dxy_from_yf() 가 yfinance 로 별도 페치.
        "broad_dollar":("DTWEXBGS",        "달러 인덱스 (브로드, 2006=100)"),
        "m2_us":       ("M2SL",            "미국 M2 통화량"),
        # 산업생산지수 (월간, 2017=100, 계절조정) — 미국 IP 카드용
        "ip_us":       ("INDPRO",          "미국 산업생산지수 (2017=100, 계절조정)"),
        # PPI — 캘린더의 미국 PPI 이벤트가 잘못 CPI 값을 가져오던 문제 해결.
        # WPSFD4 = "Producer Price Index by Commodity: Final Demand" (월간, 2009.11=100)
        "ppi_us":      ("PPIFIS",          "미국 PPI 최종재 (월간, Final Demand)"),
        # 소매판매 — 캘린더 미국 소매판매 이벤트 백필용
        "retail_us":   ("RSXFS",           "미국 소매판매 (수정후, 백만USD)"),
        # 비농업고용 (NFP, 월간 수준, 단위: 천명) — 캘린더 NFP 백필용
        "nfp_us":      ("PAYEMS",          "미국 비농업고용 (PAYEMS, 천명)"),
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
        "ip_us":       60,
        "ppi_us":      60,
        "retail_us":   60,
        "nfp_us":      60,
        # quarterly series
        "gdp_us":      20,
        "gdp_growth_us": 24,  # A191RL1Q225SBEA — 분기 성장률 6년치
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
        # 일본 산업생산지수 (OECD 시계열, 2015=100, 계절조정)
        "ip":           ("JPNPROINDMISMEI",  "일본 산업생산지수 (2015=100, 계절조정)"),
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
        "ip":           ("CHNPROINDMISMEI",   "중국 산업생산지수 (2015=100, 계절조정)"),
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


# 미국 주(State) 코드 — FHFA 주별 주택가격지수(FRED {XX}STHPI) 조회용. DC 포함 51개.
_US_STATE_CODES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC",
]


def fetch_fred_state_hpi():
    """미국 주(State)별 주택가격지수 — FHFA All-Transactions HPI (FRED {XX}STHPI, 분기).

    Case-Shiller 는 전국+20대 도시만 제공하고 주별 시계열이 없어, 프론트의 '미국 지역별
    Case-Shiller 등락률' 지도에서 주를 클릭하면 차트가 비어 있었다. 주별 가격은 FHFA 지수
    (FRED 표준)가 정답이므로 이를 가져와 지도/차트에 실데이터를 채운다(전분기比 등락률 포함).
    Returns: {CODE: {value, chg, period, source, history{YYYY-MM-DD: val}}, ...}
    """
    out = {}
    for code in _US_STATE_CODES:
        try:
            obs = fetch_fred_series(f"{code}STHPI", limit=24)  # 분기 × 24 ≈ 6년
            if not obs:
                continue
            cur = obs[0]["value"]
            prev = obs[1]["value"] if len(obs) > 1 else None
            chg = round((cur - prev) / prev * 100, 2) if prev and prev != 0 else None
            out[code] = {
                "value":   round(cur, 2),
                "chg":     chg,
                "period":  obs[0]["date"],
                "source":  f"FRED:{code}STHPI (FHFA 주별 HPI)",
                "history": {o["date"]: o["value"] for o in obs},
            }
        except Exception as e:
            log(f"[FRED-STATE] {code}STHPI 오류: {e}")
    log(f"[FRED-STATE] 미국 주별 HPI {len(out)}/{len(_US_STATE_CODES)}개 수집")
    return out


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
    # 주별 주택가격지수(FHFA) — 지역별 Case-Shiller 지도 클릭 시 차트용 실데이터.
    # 분기 데이터라 매 런(10분 주기)마다 51콜은 과해 FRED rate-limit 위험 → 일일 윈도우
    # (KST 09:00/22:00 = UTC 00/13시) 또는 AV_FETCH_FULL 일 때만 새로 페치하고, 그 외에는
    # 직전 data.json 값을 보존한다(직전 값이 없으면 한 번은 페치해 빈 화면 방지).
    try:
        hour_utc = datetime.now(timezone.utc).hour
        full = os.environ.get("AV_FETCH_FULL", "").strip() in ("1", "true", "yes")
        if hour_utc in (0, 13) or full:
            state_hpi = fetch_fred_state_hpi()
        else:
            prev = _load_prev_data()
            state_hpi = (((prev.get("realestate") or {}).get("us") or {}).get("case_shiller_state")) or {}
            if state_hpi:
                log(f"[FRED-STATE] 직전 빌드 주별 HPI {len(state_hpi)}개 보존 (비-일일윈도우, FRED 콜 절약)")
            else:
                state_hpi = fetch_fred_state_hpi()  # 직전 값 없으면 최초 1회 페치
        if state_hpi:
            result["case_shiller_state"] = state_hpi
    except Exception as e:
        log(f"[FRED-STATE] 주별 HPI 수집 오류: {e}")
    return result


def fetch_fred_realestate_kr():
    """한국 주거용 부동산 가격지수 — FRED(BIS) 폴백.

    R-ONE / ECOS 가 모두 실패하는 환경(특히 GitHub Actions 러너)에서도 FRED 는
    안정적으로 응답하므로, BIS '한국 주거용 부동산 가격지수' 시리즈로 매매가격지수를
    보강한다. BIS 는 분기 데이터이며 전세(jeonse)는 제공하지 않으므로 매매(주거용)
    지수만 채운다. 명목/실질·코드 변형에 대비해 series_id 후보를 순차 시도하고
    첫 성공을 사용한다 (frontend 는 history 의 YYYYMM 키로 'YY.MM' 라벨을 만든다).
    """
    if not FRED_API_KEY:
        return {}

    def _ym(d):  # 'YYYY-MM-DD' → 'YYYYMM'
        return (d[:4] + d[5:7]) if d and len(d) >= 7 else d

    # BIS Residential Property Prices for Korea (분기, 지수). 명목 우선, 실질·코드변형 폴백.
    candidates = [
        ("QKRN628BIS", "전국 주거용 부동산 가격지수 (BIS 명목, 분기)"),
        ("QKRR628BIS", "전국 주거용 부동산 실질가격지수 (BIS, 분기)"),
        ("QKRN368BIS", "전국 주거용 부동산 가격지수 (BIS 명목, 분기)"),
        ("QKRR368BIS", "전국 주거용 부동산 실질가격지수 (BIS, 분기)"),
    ]
    result = {}
    for sid, desc in candidates:
        obs = fetch_fred_series(sid, limit=40)  # 분기 × 40 ≈ 10년
        if not obs:
            log(f"[FRED-RE-KR] {sid}: 데이터 없음 (다음 후보 시도)")
            continue
        cur = obs[0]["value"]
        prev = obs[1]["value"] if len(obs) > 1 else None
        chg = round((cur - prev) / prev * 100, 2) if prev and prev != 0 else None
        history = {}
        for o in obs:
            history[_ym(o["date"])] = o["value"]
        result["apt_price_idx_kr"] = {
            "value":   round(cur, 2),
            "prev":    round(prev, 2) if prev is not None else None,
            "chg":     chg,
            "period":  _ym(obs[0]["date"]),
            "region":  "전국",
            "desc":    desc,
            "source":  f"FRED:{sid} (BIS)",
            "history": history,
        }
        log(f"[FRED-RE-KR] 매매가격지수 ({sid}): {cur} ({obs[0]['date']}) chg={chg} +{len(history)}점")
        break
    if not result:
        log("[FRED-RE-KR] 한국 주거용 부동산 BIS 시리즈 모든 후보 실패")
    return result


# ============================================================
# Alpha Vantage — 미국 경제지표/원자재/FX 보강 (무료 25 req/day)
# ============================================================
# 일 한도가 작아 매 시간 호출은 비효율. 보강용으로 핵심 지표만 페치.
# 호출 정책: FRED 가 비어있거나 부정확한 경우의 보강용 + UK/PMI 등 FRED 가 약한 항목.

def fetch_av_json(params, timeout=15):
    """Alpha Vantage 공통 호출 헬퍼."""
    if not ALPHAVANTAGE_API_KEY:
        return None
    try:
        params = dict(params)
        params["apikey"] = ALPHAVANTAGE_API_KEY
        r = requests.get(ALPHAVANTAGE_BASE, params=params, timeout=timeout)
        if r.status_code != 200:
            log(f"[AV] HTTP {r.status_code} func={params.get('function')}")
            return None
        try:
            data = r.json()
        except ValueError:
            log(f"[AV] JSON parse 실패 func={params.get('function')}")
            return None
        # AV rate-limit/error message 감지
        if isinstance(data, dict):
            if "Note" in data:
                log(f"[AV] rate-limit/note: {str(data.get('Note'))[:120]}")
                return None
            if "Information" in data and len(data) <= 2:
                log(f"[AV] info-only response: {str(data.get('Information'))[:120]}")
                return None
            if "Error Message" in data:
                log(f"[AV] error: {data.get('Error Message')}")
                return None
        return data
    except Exception as e:
        log(f"[AV] {params.get('function')} 예외: {e}")
        return None


# Alpha Vantage 의 economic indicator endpoint 들 — 모두 US 지표
# 각 항목: (AV function name, interval, 한국어 desc, key 명)
AV_US_ECONOMIC = [
    ("REAL_GDP",            "quarterly", "미국 실질 GDP (전기비 연환산)",     "av_real_gdp"),
    ("CPI",                 "monthly",   "미국 CPI (Alpha Vantage)",          "av_cpi"),
    ("INFLATION",           None,        "미국 인플레이션 (연간)",            "av_inflation"),
    ("RETAIL_SALES",        None,        "미국 소매판매 (백만USD)",          "av_retail_sales"),
    ("DURABLES",            None,        "미국 내구재 수주 (백만USD)",       "av_durables"),
    ("UNEMPLOYMENT",        None,        "미국 실업률 (Alpha Vantage)",       "av_unemployment"),
    ("NONFARM_PAYROLL",     None,        "미국 비농업고용 (Alpha Vantage)",   "av_nfp"),
    ("FEDERAL_FUNDS_RATE",  "monthly",   "미국 FF금리 (Alpha Vantage)",       "av_ff_rate"),
]


def fetch_av_us_economic():
    """Alpha Vantage 미국 경제지표 — FRED 와 cross-check 및 빈 항목 보강."""
    if not ALPHAVANTAGE_API_KEY:
        return {}
    out = {}
    for func, interval, desc, key in AV_US_ECONOMIC:
        params = {"function": func}
        if interval: params["interval"] = interval
        data = fetch_av_json(params)
        if not data or not isinstance(data, dict):
            continue
        series = data.get("data") or []
        if not series:
            continue
        # AV 응답: data:[{date,value},...] (최신이 앞 또는 뒤일 수 있음 → 정렬 후 사용)
        try:
            series_sorted = sorted([s for s in series if s.get("date") and s.get("value")],
                                   key=lambda s: s["date"])
            if not series_sorted:
                continue
            latest = series_sorted[-1]
            val = _parse_num(latest.get("value"))
            if val is None:
                continue
            history = {s["date"]: _parse_num(s["value"]) for s in series_sorted if _parse_num(s["value"]) is not None}
            out[key] = {
                "value":   val,
                "period":  latest["date"],
                "desc":    desc,
                "source":  f"AlphaVantage:{func}",
                "history": history,
            }
            log(f"[AV] {func}: {val} ({latest['date']}) +{len(history)}점")
        except Exception as e:
            log(f"[AV] {func} 파싱 오류: {e}")
        _time.sleep(13)  # AV 분당 5회 → 안전 마진 12초
    return out


def fetch_av_commodity(function):
    """Alpha Vantage 원자재 가격 (WTI, BRENT, NATURAL_GAS, COPPER, ALUMINUM 등)."""
    if not ALPHAVANTAGE_API_KEY:
        return None
    data = fetch_av_json({"function": function, "interval": "daily"})
    if not data or not isinstance(data, dict):
        return None
    series = data.get("data") or []
    if not series:
        return None
    try:
        series_sorted = sorted([s for s in series if s.get("date") and s.get("value") and str(s["value"]) != "."],
                               key=lambda s: s["date"])
        if len(series_sorted) < 2:
            return None
        latest = series_sorted[-1]
        prev = series_sorted[-2]
        cur = _parse_num(latest.get("value"))
        pv  = _parse_num(prev.get("value"))
        if cur is None or pv is None or pv == 0:
            return None
        chg = round((cur - pv) / pv * 100, 2)
        return {
            "price":  round(cur, 4),
            "change": chg,
            "period": latest["date"],
            "source": f"AlphaVantage:{function}",
        }
    except Exception as e:
        log(f"[AV] {function} 파싱 오류: {e}")
        return None


def fetch_av_fx(from_sym, to_sym):
    """Alpha Vantage 실시간 환율 (CURRENCY_EXCHANGE_RATE)."""
    if not ALPHAVANTAGE_API_KEY:
        return None
    data = fetch_av_json({
        "function": "CURRENCY_EXCHANGE_RATE",
        "from_currency": from_sym,
        "to_currency":   to_sym,
    })
    if not data:
        return None
    try:
        node = data.get("Realtime Currency Exchange Rate", {})
        rate = _parse_num(node.get("5. Exchange Rate"))
        if rate is None:
            return None
        return {
            "rate":   round(rate, 4),
            "source": "AlphaVantage:CURRENCY_EXCHANGE_RATE",
            "time":   node.get("6. Last Refreshed"),
        }
    except Exception:
        return None


# ============================================================
# Bank of England — 영국 기준금리 (BOE Bank Rate) 직접 페치 (키 불필요)
# ============================================================
def fetch_boe_bank_rate():
    """BoE IADB API 로 영국 Bank Rate (시리즈 IUMABEDR) 페치.

    1차: FRED OECD 시리즈 IRSTCB01GBM156N (구버전, 일부 시기 누락 가능)
    2차: Bank of England 의 IADB CSV (실시간 정책금리)
    3차: Alpha Vantage 가 영국 직접 지원이 없으므로 미사용

    Returns: {"value", "period", "desc", "source", "history"} 또는 None
    """
    # 1차: BoE IADB (가장 신뢰도 높음)
    try:
        now = datetime.now(KST)
        params = {
            "csv.x":       "yes",
            "Datefrom":    "01/Jan/2018",
            "Dateto":      now.strftime("%d/%b/%Y"),
            "SeriesCodes": "IUMABEDR",   # Official Bank Rate
            "UsingCodes":  "Y",
            "CSVF":        "TT",         # TT = Tidy Time-series
            "VPD":         "Y",
        }
        r = requests.get(BOE_IADB_BASE, params=params, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0 (economic-site fetch)"})
        if r.status_code == 200 and r.text and "," in r.text:
            lines = [ln for ln in r.text.strip().splitlines() if ln.strip()]
            history = {}
            for ln in lines[1:]:  # skip header
                parts = ln.split(",")
                if len(parts) < 2: continue
                date_s = parts[0].strip().strip('"')
                val_s  = parts[1].strip().strip('"')
                v = _parse_num(val_s)
                if v is None: continue
                # 'DD Mon YYYY' → 'YYYY-MM-DD'
                try:
                    dt_obj = datetime.strptime(date_s, "%d %b %Y")
                    history[dt_obj.strftime("%Y-%m-%d")] = v
                except ValueError:
                    try:
                        dt_obj = datetime.strptime(date_s, "%d/%m/%Y")
                        history[dt_obj.strftime("%Y-%m-%d")] = v
                    except ValueError:
                        continue
            if history:
                keys = sorted(history.keys())
                latest = keys[-1]
                log(f"[BoE] Bank Rate (IUMABEDR): {history[latest]}% ({latest}) +{len(history)}점")
                return {
                    "value":   history[latest],
                    "period":  latest,
                    "desc":    "영국 BOE 정책금리 (Bank Rate)",
                    "source":  "BoE IADB:IUMABEDR",
                    "history": history,
                }
    except Exception as e:
        log(f"[BoE] IADB 오류: {e}")

    # 2차: FRED OECD 시리즈 (월간 평균, 최신성 떨어질 수 있음)
    try:
        obs = fetch_fred_series("IRSTCB01GBM156N", limit=60)
        if obs:
            history = {o["date"]: o["value"] for o in obs}
            latest = obs[0]
            log(f"[BoE-FRED] 폴백: IRSTCB01GBM156N {latest['value']} ({latest['date']})")
            return {
                "value":   latest["value"],
                "period":  latest["date"],
                "desc":    "영국 BOE 정책금리 (FRED 폴백)",
                "source":  "FRED:IRSTCB01GBM156N",
                "history": history,
            }
    except Exception as e:
        log(f"[BoE-FRED] 폴백 오류: {e}")

    return None


# ============================================================
# PMI 지표 — 국가별 제조업 경기지수 (BCI / BSI / PMI 다중 소스)
# ============================================================
# 실제 S&P Global / ISM PMI 는 유료 데이터. FRED 가 호스팅하는 OECD BSCICP02 시리즈는
# 2024 년 일부 국가 단종, 다른 BSCICP* 시리즈 명명이 혼재. 따라서 국가별로 여러
# 후보 시리즈를 순차 시도하고, 한국은 ECOS BSI (50기준 다이퓨전 인덱스 가까운 형태) 사용.
# 모든 BSCI 계열은 100=중립 (50=중립 PMI 와 다름). 사용자 카드 unit 도 100기준으로 명시.
PMI_FRED_CANDIDATES = {
    "us": [
        ("BSCICP02USM460S", "미국 제조업 BCI (OECD MEI)"),
        ("BSCICP03USM665S", "미국 제조업 BCI (OECD CLI, 진폭조정)"),
        # MANEMP 등의 고용 시리즈는 PMI 대체로 부적합하므로 제외
    ],
    "jp": [
        ("BSCICP02JPM460S", "일본 제조업 BCI (OECD MEI)"),
        ("BSCICP03JPM665S", "일본 제조업 BCI (OECD CLI, 진폭조정)"),
    ],
    "eu": [
        ("BSCICP02EZM460S", "유로존 제조업 BCI (OECD MEI)"),
        ("BSCICP03EZM665S", "유로존 제조업 BCI (OECD CLI, 진폭조정)"),
    ],
    "uk": [
        ("BSCICP02GBM460S", "영국 제조업 BCI (OECD MEI)"),
        ("BSCICP03GBM665S", "영국 제조업 BCI (OECD CLI, 진폭조정)"),
    ],
    "de": [
        ("BSCICP02DEM460S", "독일 제조업 BCI (OECD MEI)"),
        ("BSCICP03DEM665S", "독일 제조업 BCI (OECD CLI, 진폭조정)"),
    ],
    "cn": [
        ("BSCICP02CNM460S", "중국 제조업 BCI (OECD MEI)"),
        ("BSCICP03CNM665S", "중국 제조업 BCI (OECD CLI, 진폭조정)"),
    ],
    "kr": [
        ("BSCICP02KRM460S", "한국 제조업 BCI (OECD MEI)"),
        ("BSCICP03KRM665S", "한국 제조업 BCI (OECD CLI, 진폭조정)"),
    ],
}


# ── 실 제조업 PMI(50기준) 웹 스크래핑 + 영속 캐시 ────────────────────────────
# OECD BCI(100기준, FRED)는 사용자가 기대하는 'PMI 50기준'과 다른 지표라, 가능하면 실제
# S&P Global / au Jibun Bank 제조업 PMI 를 웹에서 보강한다. FRED/공식 무료 API 가 없는
# 데이터이므로 사용자 요청대로 '웹크롤링을 루틴으로' 사용하되, 아래 안전장치로 오류값 노출을 차단:
#   1) 값 검증 — 제조업 PMI 는 30~75 범위 밖이면 폐기 (BCI 폴백 유지).
#   2) 영속 캐시(.pmi_cache.json, GHA cache 액션이 런 간 보존) — 스크래핑 실패/스킵 시 최근
#      성공값(≤45일)을 재사용해 '값이 사라지거나 BCI 로 깜빡이는' 회귀를 막는다.
#   3) 실제 스크래핑은 일일 풀 갱신(AV_FETCH_FULL) 때만 — 소스 과호출/차단 위험 최소화.
PMI_CACHE_FILE = os.environ.get("PMI_CACHE_FILE", ".pmi_cache.json")
PMI_TE_SLUGS = {
    "us": "united-states", "jp": "japan", "eu": "euro-area", "cn": "china",
    "de": "germany", "uk": "united-kingdom", "kr": "south-korea",
}


def _load_pmi_cache():
    try:
        if os.path.exists(PMI_CACHE_FILE):
            with open(PMI_CACHE_FILE, "r", encoding="utf-8") as f:
                c = json.load(f)
                return c if isinstance(c, dict) else {}
    except Exception:
        pass
    return {}


def _save_pmi_cache(cache):
    try:
        with open(PMI_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        log(f"[PMI-scrape] 캐시 저장 실패(무시): {e}")


def _scrape_te_pmi(slug):
    """tradingeconomics.com/<slug>/manufacturing-pmi 에서 최신 제조업 PMI(NN.N) 추출.

    페이지 메타설명("Manufacturing PMI in Japan ... to 49.40 ...")에서 NN.N 형식 숫자만
    엄격히 매칭한다. 검증 실패/차단 시 None (BCI 폴백 유지 — 절대 오류값 미노출).
    """
    url = f"https://tradingeconomics.com/{slug}/manufacturing-pmi"
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = requests.get(url, headers=hdrs, timeout=8)
        if r.status_code != 200 or not r.text:
            return None
        html = r.text
        m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
                      html, re.I)
        desc = m.group(1) if m else html[:1200]
        if "PMI" not in desc:
            return None
        # 'PMI ... <동사구> ... (to|at|near) NN.N' — PMI 는 항상 소수1자리(예 49.4) 형식.
        mv = re.search(
            r"PMI\s+in\s+[A-Za-z ]+?"
            r"(?:increased|decreased|rose|fell|edged up|edged down|was unchanged|"
            r"came in|stood|jumped|dropped|climbed|slipped|ticked up|ticked down|"
            r"held|remained|unchanged|registered|posted|hit|reached)?\s*"
            r"(?:to|at|near)?\s*([0-9]{2}\.[0-9])\b", desc, re.I)
        if not mv:
            mv = re.search(r"([0-9]{2}\.[0-9])\b", desc)
        if not mv:
            return None
        val = float(mv.group(1))
        if not (30.0 <= val <= 75.0):   # 제조업 PMI 합리 범위 밖 → 폐기
            return None
        # 발표 월 추정 — 설명에 'in <Month>' 가 있으면 사용, 없으면 직전 월.
        period = None
        mm = re.search(r"\bin\s+(January|February|March|April|May|June|July|August|"
                       r"September|October|November|December)\b", desc, re.I)
        months = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,"july":7,
                  "august":8,"september":9,"october":10,"november":11,"december":12}
        now = datetime.now(KST)
        if mm:
            mo = months[mm.group(1).lower()]
            yr = now.year if mo <= now.month else now.year - 1
            period = f"{yr:04d}-{mo:02d}-01"
        if not period:
            pm = now.month - 1 or 12
            py = now.year if now.month > 1 else now.year - 1
            period = f"{py:04d}-{pm:02d}-01"
        return {"value": round(val, 1), "period": period}
    except Exception:
        return None


def fetch_real_pmi_scrape():
    """국가별 실 제조업 PMI(50기준) — 웹 스크래핑 + 영속 캐시. 실패 시 빈/캐시값."""
    cache = _load_pmi_cache()
    do_scrape = bool(os.environ.get("AV_FETCH_FULL"))   # 일일 풀 갱신 때만 실제 호출
    now = datetime.now(KST)
    out = {}
    for cc, slug in PMI_TE_SLUGS.items():
        if do_scrape:
            rec = _scrape_te_pmi(slug)
            if rec:
                ent = cache.get(cc) or {}
                hist = ent.get("history") or {}
                hist[rec["period"]] = rec["value"]
                # 히스토리 최근 36개월만 유지
                hist = dict(sorted(hist.items())[-36:])
                cache[cc] = {"value": rec["value"], "period": rec["period"],
                             "scrapedAt": now.isoformat(), "history": hist}
                log(f"[PMI-scrape:{cc.upper()}] {slug}: {rec['value']} ({rec['period']})")
        ent = cache.get(cc)
        if not ent or ent.get("value") is None:
            continue
        # 캐시 신선도 — 마지막 성공 스크래핑이 45일 이내일 때만 사용.
        try:
            age = (now - datetime.fromisoformat(ent["scrapedAt"])).days
        except Exception:
            age = 999
        if age > 45:
            continue
        out[cc] = {
            "value":   ent["value"],
            "period":  ent.get("period"),
            "desc":    "제조업 PMI (S&P Global / au Jibun Bank)",
            "source":  "tradingeconomics.com (웹 스크래핑)",
            "scale":   "pmi50",
            "unit":    "지수 (50=중립, S&P Global PMI)",
            "history": ent.get("history") or {},
            "asof":    ent.get("period"),
        }
    if do_scrape:
        _save_pmi_cache(cache)
    return out


def fetch_pmi_indicators():
    """국가별 제조업 PMI / BCI / BSI 일괄 페치 — 다중 후보 시리즈 폴백.

    Returns: {cc: {"pmi_cc": {value, period, desc, source, history}}}

    - FRED OECD BSCI 시리즈는 단종/누락이 잦으므로 후보 2개씩 순차 시도.
    - 한국은 위와 별개로 ECOS 511Y003 BSI (실제 50기준 다이퓨전 인덱스) 도 수집.
    - 모든 후보 실패 시 해당 cc 항목은 미생성 (프론트엔드는 '— ' 표시).
    """
    if not FRED_API_KEY:
        log("[PMI] FRED_API_KEY 없음 — PMI 수집 건너뜀")
        return {}
    out = {}
    for cc, candidates in PMI_FRED_CANDIDATES.items():
        # 후보 시리즈를 모두 시도해 '가장 최신' 관측을 가진 시리즈를 채택한다.
        # (과거 결함: 첫 후보(MEI)가 비면 두 번째(CLI)로 넘어가는데, 일본 CLI 는 2023-12 에
        #  단종돼 2년 넘게 묵은 값을 '현재값'으로 노출했다 → 최신 날짜 우선으로 교정.)
        best = None   # (latest_date, obs, series_id, desc)
        for series_id, desc in candidates:
            try:
                obs = fetch_fred_series(series_id, limit=60)
            except Exception as e:
                log(f"[PMI:{cc.upper()}] {series_id} 오류: {e}")
                continue
            if not obs:
                log(f"[PMI:{cc.upper()}] {series_id}: 데이터 없음 — 다음 후보 시도")
                continue
            latest = obs[0]["date"]
            if best is None or latest > best[0]:
                best = (latest, obs, series_id, desc)
        if not best:
            log(f"[PMI:{cc.upper()}] 모든 후보 시리즈 실패 — 해당 국가 PMI 미생성")
            continue
        _, obs, series_id, desc = best
        history = {o["date"]: o["value"] for o in obs}
        out.setdefault(cc, {})[f"pmi_{cc}"] = {
            "value":   obs[0]["value"],
            "period":  obs[0]["date"],
            "desc":    desc,
            "source":  f"FRED:{series_id} (OECD)",
            "history": history,
        }
        log(f"[PMI:{cc.upper()}] {series_id}: {obs[0]['value']:.1f} ({obs[0]['date']}) — 최신 후보 채택")

    # 한국 PMI 보강: ECOS BSI 제조업 (기업경기실사지수)
    # AX1AA item 외에도 시기별로 SX, 0000 등 코드 변경 가능 — 다중 시도
    if ECOS_API_KEY:
        bsi_candidates = [
            ("511Y003", "AX1AA",  "한국 제조업 BSI (업황 종합)"),
            ("511Y003", "AX1AB",  "한국 제조업 BSI (업황 실적)"),
            ("511Y014", "AX1AA",  "한국 제조업 경기실사지수 (전망)"),
            ("512Y014", "AX1AA",  "한국 기업경기실사지수"),
        ]
        for stat, item, desc in bsi_candidates:
            try:
                bsi = _ecos_latest(stat, item, "M", desc, f"ECOS:{stat}/{item}")
                if bsi:
                    # KR pmi_kr 가 비어있으면 ECOS BSI 를 primary 로 사용 (50기준에 더 가까움)
                    if not (out.get("kr", {}).get("pmi_kr") or {}).get("value"):
                        out.setdefault("kr", {})["pmi_kr"] = bsi
                        log(f"[PMI:KR] ECOS BSI ({stat}/{item}) 를 pmi_kr 로 사용: {bsi['value']}")
                    else:
                        # 이미 BCI 가 있으면 별도 키로 추가
                        out.setdefault("kr", {})["pmi_kr_bsi"] = bsi
                        log(f"[PMI:KR-BSI] {stat}/{item}: {bsi['value']} ({bsi['period']})")
                    break
            except Exception as e:
                log(f"[PMI:KR-BSI] {stat}/{item} 오류: {e}")

    # ── BCI 스케일 정규화 (일관된 '100=중립' 경기지수) ──
    # OECD BSCI 시리즈는 두 스케일이 혼재한다:
    #   · MEI(BSCICP02): 순감응(net balance) — 0 중심 (예: 미국 +5.4, 독일 -14.5, 유로존 -6.8)
    #   · CLI(BSCICP03): 진폭조정 지수 — 100 중심 (예: 일본 100.8, 중국 97.7)
    # 카드/차트가 '제조업 PMI(50기준)' 로 오표기되던 문제를 바로잡고 국가 간 비교가 가능하도록,
    # 0중심(순감응) 값을 +100 보정해 모두 '100=중립(장기평균)' 지수로 통일한다.
    # (관측 범위상 |v|<50 이면 순감응, 그 이상이면 이미 지수형 — 안전한 휴리스틱.)
    def _to_index100(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return v
        return round(f + 100, 2) if abs(f) < 50 else round(f, 2)
    now_naive = datetime.now(KST).replace(tzinfo=None)
    for cc, node in out.items():
        rec = node.get(f"pmi_{cc}")
        if not rec or rec.get("value") is None:
            continue
        # 한국은 위에서 ECOS BSI(50기준 다이퓨전)를 채택했을 수 있다 — 이 경우 +100 보정 금지.
        if rec.get("source", "").startswith("ECOS"):
            rec["scale"] = "bsi"
            rec["unit"]  = "지수 (50=중립, 한국은행 BSI)"
        else:
            rec["value"] = _to_index100(rec["value"])
            if isinstance(rec.get("history"), dict):
                rec["history"] = {k: _to_index100(v) for k, v in rec["history"].items()}
            rec["scale"] = "index100"
            rec["unit"]  = "지수 (장기평균 100=중립, OECD BCI)"
        # desc 정정 — 실제로는 OECD 기업경기지수(BCI), S&P Global PMI 아님.
        if rec.get("scale") == "index100":
            rec["desc"] = "제조업 경기지수(OECD BCI)"
        # 신선도 검사 — 월간 지표가 ~120일 이상 묵었으면 '갱신 지연' 플래그(프론트가 ⚠ 표시).
        try:
            pd = datetime.strptime(str(rec.get("period", ""))[:10], "%Y-%m-%d")
            age_days = (now_naive - pd).days
            rec["asof"] = rec.get("period")
            if age_days > 120:
                rec["stale"] = True
                log(f"[PMI:{cc.upper()}] ⚠ 데이터 지연 {age_days}일 (period={rec.get('period')})")
        except Exception:
            pass

    # ── 실 제조업 PMI(50기준, S&P Global) 웹 보강 ──────────────────────────
    # OECD BCI(100기준)는 사용자가 기대하는 'PMI 50기준'과 다른 지표다. 가능하면 실제
    # S&P Global / au Jibun Bank 제조업 PMI 를 웹에서 보강해 BCI 대신 노출한다(검증 실패 시 BCI 유지).
    try:
        real = fetch_real_pmi_scrape()
        for cc, rec in (real or {}).items():
            if rec and rec.get("value") is not None:
                out.setdefault(cc, {})[f"pmi_{cc}"] = rec
                log(f"[PMI:{cc.upper()}] 실 PMI 보강 채택: {rec['value']} ({rec.get('period')}) ← {rec.get('source')}")
    except Exception as e:
        log(f"[PMI] 실 PMI 웹 보강 오류(무시, BCI 유지): {e}")
    return out


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
    # R-ONE OpenAPI 의 DTACYCLE_CD 는 2글자 코드를 사용한다 (개발가이드 예: DTACYCLE_CD=YY).
    # 단일 문자("M"/"Q"/"Y"/"W")를 그대로 보내면 모든 STATBL_ID 가 빈 응답을 반환하므로
    # (유효한 통계표 ID 도 동일) 반드시 2글자 코드로 매핑해야 한다.
    cycle_code = {"M": "MM", "Q": "QQ", "Y": "YY", "W": "WK"}.get(period_type, period_type)
    params = {
        "KEY":        REALESTATE_API_KEY,
        "Type":       "json",
        "pIndex":     1,
        "pSize":      limit,
        "STATBL_ID":  stats_id,
        "DTACYCLE_CD": cycle_code,
        "WRTTIME_IDTFR_ID_FROM": start_prd,
        "WRTTIME_IDTFR_ID_TO":   end_prd,
    }
    if item_code1: params["ITM_ID"]    = item_code1
    if item_code2: params["CLS_ID"]    = item_code2
    if item_code3: params["CLS_ID_2"]  = item_code3
    # 신 API: https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do
    # 응답 구조 케이스:
    #   1) {"SttsApiTblData": [{"head":[...]}, {"row":[...]}]}  → 정상
    #   2) {"SttsApiTblData": [{"head":[{"RESULT":{...}}]}]}    → STATBL_ID 오류 등
    #   3) {"RESULT": {"CODE":"INFO-200","MESSAGE":"해당하는 데이터가 없습니다."}}
    #   4) HTML/일반 텍스트 응답 (서버 점검 등)
    try:
        # R-ONE 은 연속 호출 시 연결을 자주 끊는다(RemoteDisconnected). 호출 간 간격(throttle)을
        # 두면 드롭이 크게 줄어든다. 그래도 끊기면 백오프 재시도(최대 4회).
        _time.sleep(1.0)
        r = None
        for attempt in range(4):
            try:
                r = requests.get(f"{RONE_BASE}/SttsApiTblData.do", params=params, timeout=25,
                                 headers={"User-Agent": "Mozilla/5.0 (economic-site fetch)"})
                break
            except requests.exceptions.RequestException as e:
                if attempt == 3:
                    log(f"[R-ONE-new] {stats_id}: 연결 실패(재시도 소진) {type(e).__name__}")
                    return None
                _time.sleep(2.0 * (attempt + 1))
        if r.status_code != 200:
            log(f"[R-ONE-new] {stats_id}: HTTP {r.status_code}")
            return None
        try:
            data = r.json()
        except ValueError:
            log(f"[R-ONE-new] {stats_id}: JSON 파싱 실패 — 응답 앞 100자: {r.text[:100]}")
            return None
        # 응답 진단 — 어떤 케이스인지 명확히 로그
        if isinstance(data, dict):
            top_result = data.get("RESULT") or {}
            if top_result.get("CODE", "").startswith("INFO-2") or "데이터" in top_result.get("MESSAGE", ""):
                log(f"[R-ONE-new] {stats_id}: {top_result.get('CODE')} {top_result.get('MESSAGE','')[:60]}")
                return None
            rows_envelope = data.get("SttsApiTblData", [])
            if isinstance(rows_envelope, list):
                # head 의 RESULT 코드 확인
                for blk in rows_envelope:
                    if isinstance(blk, dict) and "head" in blk:
                        for h in (blk.get("head") or []):
                            res = (h or {}).get("RESULT") or {}
                            code = res.get("CODE", "")
                            msg  = res.get("MESSAGE", "")
                            if code and not code.startswith("INFO-000"):
                                log(f"[R-ONE-new] {stats_id}: {code} {msg[:60]}")
                                return None
                # row 추출
                for blk in rows_envelope:
                    if isinstance(blk, dict) and "row" in blk:
                        rows = blk["row"]
                        log(f"[R-ONE-new] {stats_id}: {len(rows) if isinstance(rows, list) else 1}행 수집")
                        return rows
        log(f"[R-ONE-new] {stats_id}: 응답 형식 미확인 — 키={list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
        return None
    except Exception as e:
        log(f"[R-ONE-new] {stats_id} 예외: {e}")
        return None


def fetch_rone_table_catalog(name_kw, cycle_code="MM", limit=200):
    """R-ONE 통계표 목록(SttsApiTbl)에서 이름으로 STATBL_ID 를 자동 탐색.

    하드코딩한 STATBL_ID 가 (등록 차수 변경 등으로) 더 이상 유효하지 않을 때
    이름 키워드로 현재 유효한 통계표 ID 를 동적으로 찾아 자가 복구한다.
    응답 구조/네트워크 오류 시 빈 리스트를 반환하므로 빌드를 깨지 않는다.

    Returns: [(STATBL_ID, STATBL_NM), ...] — name_kw 를 STATBL_NM 에 포함한 항목만.
    """
    if not REALESTATE_API_KEY:
        return []
    try:
        r = requests.get(
            f"{RONE_BASE}/SttsApiTbl.do",
            params={"KEY": REALESTATE_API_KEY, "Type": "json", "pIndex": 1, "pSize": limit},
            timeout=20, headers={"User-Agent": "Mozilla/5.0 (economic-site fetch)"},
        )
        if r.status_code != 200:
            log(f"[R-ONE-cat] SttsApiTbl HTTP {r.status_code}")
            return []
        try:
            data = r.json()
        except ValueError:
            log(f"[R-ONE-cat] JSON 파싱 실패 — 앞 100자: {r.text[:100]}")
            return []
        rows = []
        envelope = data.get("SttsApiTbl") if isinstance(data, dict) else None
        if isinstance(envelope, list):
            for blk in envelope:
                if isinstance(blk, dict) and "row" in blk and isinstance(blk["row"], list):
                    rows = blk["row"]
                    break
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            nm = row.get("STATBL_NM", "") or ""
            sid = row.get("STATBL_ID", "") or ""
            cyc = (row.get("DTACYCLE_CD", "") or "").upper()
            if not sid or name_kw not in nm:
                continue
            if cycle_code and cyc and cyc != cycle_code:
                continue
            out.append((sid, nm))
        if out:
            log(f"[R-ONE-cat] '{name_kw}' 매칭 통계표 {len(out)}건: {[s for s,_ in out][:5]}")
        return out
    except Exception as e:
        log(f"[R-ONE-cat] 카탈로그 조회 예외: {e}")
        return []


def _rone_pick_nationwide(rows):
    """R-ONE 통계표 행 리스트에서 '전국' 분류의 최신값/전월값/시계열을 추출.

    통계표는 지역(CLS_NM/CL_NM)·항목(ITM_NM) 차원으로 여러 행을 반환하므로
    그냥 마지막 행을 쓰면 임의 지역값이 잡힌다. '전국' 행만 필터해 사용하고,
    '전국'이 없으면 전체 행을 시점별로 합쳐 최신값을 고른다.

    Returns: dict(value, prev, chg, period, history) 또는 None.
    """
    if not rows:
        return None
    def _is_nationwide(r):
        for f in ("CLS_NM", "CL_NM", "CLS_FULLNM"):
            v = r.get(f)
            if v and "전국" in str(v):
                return True
        # 분류 필드가 아예 없으면 단일 시리즈로 간주 (전국으로 취급)
        return not any(r.get(f) for f in ("CLS_NM", "CL_NM", "CLS_FULLNM"))
    nationwide = [r for r in rows if _is_nationwide(r)]
    target = nationwide if nationwide else rows
    history = {}
    for r in target:
        p = r.get("WRTTIME_IDTFR_ID")
        v = _parse_num(r.get("DTA_VAL"))
        if p and v is not None:
            history[p] = v
    if not history:
        return None
    keys = sorted(history.keys())
    val = history[keys[-1]]
    prev = history[keys[-2]] if len(keys) > 1 else None
    chg = round((val - prev) / prev * 100, 2) if prev else None
    return {"value": round(val, 2), "prev": prev, "chg": chg,
            "period": keys[-1], "history": history}


def fetch_rone_nationwide_latest(stats_id, limit=600, itm_id=None):
    """전국(CLS_ID=500001) 월간 시계열을 받아 최신값/전월비/history 를 추출.

    SttsApiTblData 는 날짜범위를 무시하고 모든 지역을 오래된 순으로 주므로, CLS_ID=500001
    로 전국만 한정해야 최신값을 얻는다. limit 은 전국 단일 지역의 전체 월 수(현재 ~270)를
    덮을 만큼 크게 둔다. CLS_ID 필터가 안 먹는(전국 단일 차원) 통계표는 필터 없이 재시도하고
    _rone_pick_nationwide 가 '전국' 행(또는 분류 없는 단일 시리즈)을 골라낸다.

    itm_id: 한 통계표에 여러 항목(예: 거래현황의 동(호)수/면적)이 있을 때 ITM_ID 로 한정.
            미지정 시 _rone_pick_nationwide 가 단일 항목으로 가정하고 처리.
    """
    rows = fetch_rone_stats(stats_id, item_code1=itm_id, item_code2=RONE_NATIONWIDE_CLS,
                            period_type="M", limit=limit)
    picked = _rone_pick_nationwide(rows) if rows else None
    if picked:
        return picked
    rows = fetch_rone_stats(stats_id, item_code1=itm_id, period_type="M", limit=limit)
    return _rone_pick_nationwide(rows) if rows else None


def fetch_realestate_kr_ecos_fallback():
    """R-ONE API 실패 시 ECOS 의 부동산 시리즈로 폴백.

    ECOS 901Y014 — KB부동산 주택매매가격지수 (월간, 1986.1=100)
                901Y015 — 주택전세가격지수 (KB)
    KB 데이터는 R-ONE 과 약간 다르지만 시장 동향 파악에 충분히 유의미함.
    R-ONE API 키 미설정 케이스에 사용자 화면이 비지 않도록 폴백.
    """
    if not ECOS_API_KEY:
        return {}
    result = {}
    # 매매 시리즈 — KB 부동산 + BOK 종합 + 한국부동산원 매매지수 (ECOS 게재 시리즈)
    sale_candidates = [
        # 한국부동산원 → ECOS 게재본 (가장 사용자 기대에 부합)
        ("098Y001", "0.1.0.1", "전국 종합주택 매매가격지수 (한국부동산원→BOK)"),
        ("098Y001", "0.2.0.1", "전국 아파트 매매가격지수 (한국부동산원→BOK)"),
        ("099Y001", "0.1.0.1", "전국 종합주택 매매가격지수 (한국부동산원, 신코드)"),
        # KB 부동산 폴백
        ("901Y014", "AAA",     "전국 주택매매가격지수 (KB)"),
        ("901Y014", "AAA000",  "전국 주택매매가격지수 (KB)"),
        ("901Y018", "AAA",     "전국 아파트 매매가격지수 (KB)"),
    ]
    for stat, item, desc in sale_candidates:
        try:
            r = _ecos_latest(stat, item, "M", desc, f"ECOS:{stat}")
            if r:
                # R-ONE 과 같은 변동률(%) 표시를 위해 prev 와 chg 계산
                history = r.get("history", {})
                keys = sorted(history.keys())
                if len(keys) >= 2:
                    prev = history[keys[-2]]
                    cur = history[keys[-1]]
                    r["prev"] = prev
                    r["chg"] = round((cur - prev) / prev * 100, 2) if prev else None
                    r["region"] = "전국"
                result["apt_price_idx_kr"] = r
                log(f"[RE-ECOS-fb] 매매가격 ({stat}/{item}): {r['value']}")
                break
        except Exception as e:
            log(f"[RE-ECOS-fb] {stat}/{item} 오류: {e}")
    jns_candidates = [
        # 한국부동산원 → ECOS 게재본
        ("098Y002", "0.1.0.1", "전국 종합주택 전세가격지수 (한국부동산원→BOK)"),
        ("098Y002", "0.2.0.1", "전국 아파트 전세가격지수 (한국부동산원→BOK)"),
        # KB 폴백
        ("901Y015", "AAA",    "전국 주택전세가격지수 (KB)"),
        ("901Y015", "AAA000", "전국 주택전세가격지수 (KB)"),
        ("901Y019", "AAA",    "전국 아파트 전세가격지수 (KB)"),
    ]
    for stat, item, desc in jns_candidates:
        try:
            r = _ecos_latest(stat, item, "M", desc, f"ECOS:{stat}")
            if r:
                history = r.get("history", {})
                keys = sorted(history.keys())
                if len(keys) >= 2:
                    prev = history[keys[-2]]
                    cur = history[keys[-1]]
                    r["prev"] = prev
                    r["chg"] = round((cur - prev) / prev * 100, 2) if prev else None
                    r["region"] = "전국"
                result["jns_price_idx_kr"] = r
                log(f"[RE-ECOS-fb] 전세가격 ({stat}/{item}): {r['value']}")
                break
        except Exception as e:
            log(f"[RE-ECOS-fb] {stat}/{item} 오류: {e}")
    return result


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

    # ─── 신 API: 전국주택가격동향조사 (월간) ─────────────
    # STATBL_ID 는 reb.or.kr 공식 통계조회 페이지(easyStatPage/{ID}.do)에서 검증한 값을 우선 사용.
    #   A_2024_00045 = (월) 매매가격지수_아파트,  A_2024_00050 = (월) 전세가격지수_아파트
    # 등록 차수 변경에 대비해 구 후보도 폴백으로 유지하고, 모두 실패하면 통계표 목록(SttsApiTbl)
    # 에서 이름으로 동적 탐색(self-healing)한다. '전국' 분류 행만 골라 최신값/전월비를 계산한다.
    def _rone_index_series(candidates, discover_kw, desc, label):
        """candidates(검증 ID 우선) → 실패 시 카탈로그 탐색. 첫 성공의 파싱 결과를 반환."""
        ids = list(candidates)
        tried = {sid for sid, _ in ids}
        for sid, _ in ids:
            try:
                picked = fetch_rone_nationwide_latest(sid)
                if picked:
                    picked.update({"region": "전국", "desc": desc, "source": f"R-ONE:{sid}"})
                    log(f"[R-ONE-new] {label} ({sid}): {picked['value']} ({picked['period']}) chg={picked['chg']}")
                    return picked
            except Exception as e:
                log(f"[R-ONE-new] {sid} 오류: {e}")
        # 하드코딩 ID 전부 실패 → 통계표 목록에서 이름으로 동적 탐색
        for sid, nm in fetch_rone_table_catalog(discover_kw, "MM"):
            if sid in tried:
                continue
            try:
                picked = fetch_rone_nationwide_latest(sid)
                if picked:
                    picked.update({"region": "전국", "desc": desc, "source": f"R-ONE:{sid}(자동탐색)"})
                    log(f"[R-ONE-cat] {label} 자동탐색 성공 ({sid}={nm}): {picked['value']}")
                    return picked
            except Exception as e:
                log(f"[R-ONE-cat] {sid} 오류: {e}")
        return None

    sale = _rone_index_series(
        candidates=[
            ("A_2024_00045", "(월) 매매가격지수_아파트"),   # 공식 페이지 검증
            ("A_2025_00131", "전국 아파트 매매가격지수"),
            ("A_2024_00026", "전국 아파트 매매가격지수"),
            ("A_2022_00026", "전국 아파트 매매가격지수"),
        ],
        discover_kw="매매가격지수", desc="전국주택가격동향조사 아파트 매매가격지수",
        label="매매가격지수")
    if sale:
        result["apt_price_idx_kr"] = sale

    jns = _rone_index_series(
        candidates=[
            ("A_2024_00019", "(월) 전세가격지수_주택종합"),  # 사용자 지정 — 카탈로그 검증
            ("A_2024_00050", "(월) 전세가격지수_아파트"),    # 폴백
        ],
        discover_kw="전세가격지수_주택종합", desc="전국주택가격동향조사 주택종합 전세가격지수",
        label="전세가격지수(주택종합)")
    if jns:
        result["jns_price_idx_kr"] = jns

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

    # ─── R-ONE 추가 시리즈: 미분양 / 인허가 / 착공 / 준공 (전국 집계) ──
    # 모두 전국(CLS_ID=500001) 으로 한정해 최신값을 추출 (가격지수와 동일 메커니즘).
    # 주: '주택 인허가/준공'(permit/complete)은 국토교통부(MOLIT) 통계라 R-ONE OpenAPI 에
    #     존재하지 않아 항상 빈 응답이었다(프론트의 '주택 인허가' 차트가 비어 보이던 원인).
    #     → 인허가는 아래 '전월세전환율'(R-ONE 실제 제공 지표)로 대체한다. 준공은 제거.
    extra_stats = [
        # (key,          desc,                       statbl_id)
        ("unsold_kr",    "전국 미분양 주택 수",        "A_2024_00064"),
        ("start_kr",     "주택 착공 실적 (전국)",      "A_2024_00057"),
    ]
    for key, desc, statbl_id in extra_stats:
        try:
            picked = fetch_rone_nationwide_latest(statbl_id, limit=300)
            if not picked:
                log(f"[R-ONE] {statbl_id} ({key}): 응답 없음/전국행 없음 — 건너뜀")
                continue
            picked.update({"region": "전국", "desc": desc, "source": f"R-ONE:{statbl_id}"})
            result[key] = picked
            log(f"[R-ONE] {key} ({statbl_id}): {picked['value']} ({picked['period']})")
        except Exception as e:
            log(f"[R-ONE] {key} ({statbl_id}) 오류: {e}")

    # ─── 전월세전환율 (전국, 월) — '주택 인허가'(R-ONE 미제공) 대체 지표 ──
    # 전세보증금을 월세로 전환할 때 적용되는 연이율(%). 시장금리·임대차 수급을 반영하는
    # 의미 있는 시장 지표로, R-ONE 이 실제 제공한다. 등록 차수에 따라 STATBL_ID 가 바뀌므로
    # 카탈로그 검색(이름='전월세전환율')으로 유효한 통계표를 자동 탐색한다.
    try:
        conv = None
        conv_id = None
        for sid, nm in fetch_rone_table_catalog("전월세전환율", "MM"):
            conv = fetch_rone_nationwide_latest(sid, limit=300)
            if conv:
                conv_id = sid
                break
        if conv:
            conv.update({"region": "전국", "desc": "전월세전환율 (전국, 월)", "source": f"R-ONE:{conv_id}"})
            result["conversion_rate_kr"] = conv
            log(f"[R-ONE] conversion_rate_kr ({conv_id}): {conv['value']} ({conv['period']})")
        else:
            log("[R-ONE] 전월세전환율: 카탈로그 검색 실패 — 건너뜀 (프론트 '수집 중' 표시)")
    except Exception as e:
        log(f"[R-ONE] 전월세전환율 오류: {e}")

    # ─── 거래량: (월) 행정구역별 아파트거래현황 (A_2024_00549) ──
    # 전국(CLS_ID=500001) + ITM_ID=100001(동(호)수) 로 한정. 면적(100002) 항목과 섞이지 않게 ITM 필수.
    try:
        trade = fetch_rone_nationwide_latest("A_2024_00549", limit=600, itm_id="100001")
        if trade:
            trade.update({"region": "전국", "desc": "한국부동산원 행정구역별 아파트거래현황 (전국·동(호)수)",
                          "source": "R-ONE:A_2024_00549"})
            result["trade_count_kr_rone"] = trade
            log(f"[R-ONE] trade_count_kr_rone (A_2024_00549): {trade['value']} ({trade['period']})")
        else:
            log("[R-ONE] A_2024_00549 (거래현황): 응답 없음 — 건너뜀")
    except Exception as e:
        log(f"[R-ONE] A_2024_00549 (거래현황) 오류: {e}")

    # ─── 시군구별 매매가격지수 변동률 (드릴다운용 region/region_sub) ──
    try:
        breakdown = fetch_rone_sigungu_breakdown()
        if breakdown:
            if breakdown.get("region_sub"):
                result["region_sub"] = breakdown["region_sub"]
            if breakdown.get("region"):
                result["region"] = breakdown["region"]
            log(f"[R-ONE] 지역 드릴다운: 시도 {len(breakdown.get('region',[]))}개, "
                f"region_sub {len(breakdown.get('region_sub',{}))}개 시도")
    except Exception as e:
        log(f"[R-ONE] 시군구 드릴다운 오류: {e}")

    return result


# 시도 이름(부분 문자열) → 프론트엔드 지역 코드. R-ONE 의 긴 명칭(서울특별시/경기도/
# 강원특별자치도/전북특별자치도/충청북도 …)·짧은 명칭 모두 매칭되도록 접두어로 둔다.
RONE_SIDO_CODE = [
    ("서울", "11"), ("부산", "26"), ("대구", "27"), ("인천", "28"), ("광주", "29"),
    ("대전", "30"), ("울산", "31"), ("세종", "36"), ("경기", "41"),
    ("강원", "42"), ("충청북", "43"), ("충북", "43"), ("충청남", "44"), ("충남", "44"),
    ("전라북", "45"), ("전북", "45"), ("전라남", "46"), ("전남", "46"),
    ("경상북", "47"), ("경북", "47"), ("경상남", "48"), ("경남", "48"), ("제주", "50"),
]


def _rone_classify_region(full_name, short_name):
    """R-ONE 지역 행을 (시도코드, 시군구표시명) 으로 분류.

    full_name(CLS_FULLNM, 전체 경로 예: '수도권 경기 성남시 분당구') 를 우선 사용한다.
    경로 토큰 중 '시도' 토큰을 찾고, 그 뒤를 시군구명으로 구성한다. ('광주광역시' vs
    '경기 광주시' 같은 동음 충돌은 전체 경로가 있어야 정확히 구분된다.)

    Returns: (sido_code, sub_name) — sub_name 이 '' 이면 시도 자체(=광역) 행.
             분류 불가(전국/수도권/지방권 등)면 (None, None).
    """
    path = (full_name or "").strip()
    tokens = [t for t in path.replace(",", " ").split() if t]
    if not tokens:
        tokens = [(short_name or "").strip()] if short_name else []
    if not tokens:
        return None, None
    # 광역 집계행 제외
    if len(tokens) == 1 and tokens[0] in ("전국", "수도권", "지방권", "6대광역시", "5대광역시", "9개도", "8개도"):
        return None, None
    sido_idx = None
    sido_code = None
    for i, tok in enumerate(tokens):
        for name, code in RONE_SIDO_CODE:
            if tok.startswith(name):
                sido_idx, sido_code = i, code
                break
        if sido_code:
            break
    if sido_code is None:
        return None, None
    sub_tokens = tokens[sido_idx + 1:]
    sub_name = " ".join(sub_tokens).strip()
    return sido_code, sub_name


def fetch_rone_sigungu_breakdown():
    """R-ONE 아파트 매매가격지수의 시도·시군구별 '전월비 변동률(%)' 산출.

    경기뿐 아니라 모든 시도의 시군구를 동일하게 처리한다. 최근 몇 달만 받아
    (지역 × 월) 행을 시군구별로 모으고 최신월의 전월비 변동률을 계산한다.
    더미 없음 — 실패/불충분하면 빈 dict 반환(프론트는 내장 시드로 폴백).

    Returns: {"region":[{code,label,val}], "region_sub":{code:{period, subs:[{name,val}]}}}.
    """
    if not REALESTATE_API_KEY:
        return {}
    # 매매가격지수_아파트 통계표 후보 (fetch_realestate_kr 와 동일 우선순위)
    sid_candidates = ["A_2024_00045", "A_2025_00131", "A_2024_00026", "A_2022_00026"]
    now = datetime.now(KST)
    start_prd = (now - timedelta(days=210)).strftime("%Y%m")  # 최근 ~7개월
    end_prd = now.strftime("%Y%m")
    rows = None
    used_sid = None
    for sid in sid_candidates:
        try:
            r = fetch_rone_stats(sid, period_type="M", start_prd=start_prd, end_prd=end_prd, limit=6000)
        except Exception as e:
            log(f"[R-ONE-시군구] {sid} 오류: {e}")
            continue
        if r and len(r) > 50:  # 전 지역 × 수개월이면 수백 행
            rows, used_sid = r, sid
            break
    if not rows:
        log("[R-ONE-시군구] 지역 행 수집 실패 — region_sub 미생성(시드 폴백)")
        return {}

    # (시도코드, 시군구명) → {period: value}
    region_hist = {}     # 시도 자체: code -> {period: value}
    sub_hist = {}        # code -> { sub_name -> {period: value} }
    for row in rows:
        full = row.get("CLS_FULLNM") or row.get("CLS_NM") or row.get("CL_NM") or ""
        short = row.get("CLS_NM") or row.get("CL_NM") or ""
        period = row.get("WRTTIME_IDTFR_ID")
        val = _parse_num(row.get("DTA_VAL"))
        if not period or val is None:
            continue
        code, sub = _rone_classify_region(full, short)
        if code is None:
            continue
        if not sub:  # 시도(광역) 자체
            region_hist.setdefault(code, {})[period] = val
        else:
            sub_hist.setdefault(code, {}).setdefault(sub, {})[period] = val

    def _mom_pct(hist):
        ks = sorted(hist.keys())
        if len(ks) < 2:
            return None, ks[-1] if ks else None
        cur, prev = hist[ks[-1]], hist[ks[-2]]
        if prev in (None, 0):
            return None, ks[-1]
        return round((cur - prev) / prev * 100, 2), ks[-1]

    region = []
    for code, hist in region_hist.items():
        chg, period = _mom_pct(hist)
        if chg is not None:
            region.append({"code": code, "val": chg, "period": period})

    region_sub = {}
    period_label = None
    for code, subs in sub_hist.items():
        items = []
        for sub_name, hist in subs.items():
            chg, period = _mom_pct(hist)
            if chg is None:
                continue
            items.append({"name": sub_name, "val": chg})
            period_label = period_label or period
        if len(items) >= 3:  # 시군구 3개 이상 모인 시도만 채택(부분/오류 데이터 배제)
            region_sub[code] = {
                "period": period_label or end_prd,
                "subs": sorted(items, key=lambda x: x["val"], reverse=True),
                "source": f"R-ONE:{used_sid}",
            }
    if not region_sub:
        log("[R-ONE-시군구] 분류 결과 불충분 — region_sub 미생성(시드 폴백)")
        return {}
    log(f"[R-ONE-시군구] used_sid={used_sid} region={len(region)} region_sub={len(region_sub)}개 시도 "
        f"({sum(len(v['subs']) for v in region_sub.values())}개 시군구)")
    return {"region": region, "region_sub": region_sub}


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


def _applyhome_region_bucket(area_nm):
    """청약홈 공급지역명 → 프론트 지역 버킷(seoul/gyeonggi/metro/other)."""
    a = area_nm or ""
    if "서울" in a:
        return "seoul"
    if "경기" in a or "인천" in a:
        return "gyeonggi"
    if any(x in a for x in ("부산", "대구", "대전", "광주", "울산")):
        return "metro"
    return "other"


def _data_go_kr_get(url, params, timeout=20):
    """data.go.kr/odcloud GET — serviceKey 이중 인코딩 버그 회피.

    data.go.kr 인증키가 '인코딩 키'(%2B 등 포함)면 requests 가 % 를 다시 인코딩(%25)해 401 이
    난다. 키에 '%' 가 있으면 쿼리스트링을 직접 만들어 raw 로 붙이고(params 재인코딩 회피),
    아니면 평소대로 params 로 전달한다.
    """
    key = DATA_GO_KR_API_KEY
    if "%" in key:
        from urllib.parse import urlencode
        qs = urlencode({k: v for k, v in params.items()})
        full = f"{url}?serviceKey={key}&{qs}"
        return requests.get(full, timeout=timeout)
    p = dict(params)
    p["serviceKey"] = key
    return requests.get(url, params=p, timeout=timeout)


def fetch_applyhome_subscription(max_items=200):
    """청약홈(한국부동산원) 최근 APT 분양정보 — data.go.kr odcloud API.

    프론트 '청약 경쟁률' 지역 드릴다운(Task 4)용 '최근 분양 단지'를 지역 버킷
    (서울/경기인천/지방광역시/기타)으로 묶는다. 여러 엔드포인트 변형을 시도하고, 각 시도의
    상태/응답 일부를 진단 문자열로 모은다(원격 data.json.diagnostics 에 기록 → 사후 점검).
    Returns: (result_dict_or_{}, diag_str).
    """
    if not DATA_GO_KR_API_KEY:
        return {}, "DATA_GO_KR_API_KEY 미설정"
    since = (datetime.now(KST) - timedelta(days=365)).strftime("%Y-%m-%d")
    # 등록 차수/플랫폼에 따라 경로가 달라질 수 있어 후보를 순차 시도.
    candidates = [
        "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail",
        "https://api.odcloud.kr/api/ApplyhomeInfoSvc/v1/getAPTLttotPblancDetail",
        "https://api.odcloud.kr/api/15110480/v1/getAPTLttotPblancDetail",
    ]
    diag = []
    for url in candidates:
        tag = url.split("/api/")[-1].split("/")[0]
        for use_cond in (True, False):  # 날짜 필터가 막히면 필터 없이 재시도
            params = {"page": 1, "perPage": max_items}
            if use_cond:
                params["cond[RCRIT_PBLANC_DE::GTE]"] = since
            try:
                r = _data_go_kr_get(url, params)
            except Exception as e:
                diag.append(f"{tag} ERR {type(e).__name__}:{str(e)[:60]}")
                break
            snippet = (r.text or "")[:140].replace("\n", " ").replace("\r", " ")
            if r.status_code != 200:
                diag.append(f"{tag} HTTP{r.status_code} {snippet}")
                continue  # 다음 변형(필터 제거) 또는 다음 후보 URL 시도
            try:
                data = r.json()
            except Exception:
                diag.append(f"{tag} 200 non-JSON {snippet}")
                continue
            rows = data.get("data") if isinstance(data, dict) else None
            if not rows:
                tc = data.get("totalCount") if isinstance(data, dict) else "?"
                diag.append(f"{tag} 200 no-data tc={tc} {snippet}")
                continue
            rows = sorted(rows, key=lambda it: str(it.get("RCRIT_PBLANC_DE") or ""), reverse=True)
            by = {"seoul": [], "gyeonggi": [], "metro": [], "other": []}
            for it in rows:
                name = it.get("HOUSE_NM") or it.get("BSNS_MBY_NM") or ""
                if not name:
                    continue
                area = it.get("SUBSCRPT_AREA_CODE_NM") or it.get("HSSPLY_ADRES") or ""
                date = (str(it.get("RCRIT_PBLANC_DE") or ""))[:10]
                b = _applyhome_region_bucket(area)
                if len(by[b]) >= 15:
                    continue
                by[b].append({"name": name, "area": area, "date": date, "rate": None})
            total = sum(len(v) for v in by.values())
            if not total:
                diag.append(f"{tag} parsed-0/{len(rows)}rows")
                continue
            diag.append(f"OK {tag} {total}건")
            log(f"[청약홈] {total}건 수집 via {tag}")
            return {
                "byRegion": by,
                "source": "청약홈(한국부동산원, data.go.kr) APT 분양정보",
                "lastFetched": datetime.now(KST).isoformat(),
            }, " | ".join(diag)
    log(f"[청약홈] 수집 실패 — {' | '.join(diag)}")
    return {}, " | ".join(diag)


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
    # 3차: investing.com KOSPI Volatility 페이지 — 사용자가 직접 보는 페이지와 동일 값
    #      https://kr.investing.com/indices/kospi-volatility (= https://www.investing.com/indices/kospi-volatility)
    try:
        import re as _re
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ko,en;q=0.8",
        }
        for url in ("https://kr.investing.com/indices/kospi-volatility",
                    "https://www.investing.com/indices/kospi-volatility"):
            try:
                r = requests.get(url, headers=headers, timeout=15)
                if r.status_code != 200 or not r.text:
                    continue
                html = r.text
                # 다중 패턴 — investing.com 페이지 구조가 자주 바뀌므로 여러 패턴 시도.
                m = _re.search(r'data-test="instrument-price-last"[^>]*>([0-9,.]+)<', html)
                if not m:
                    m = _re.search(r'id="last_last"[^>]*>([0-9,.]+)<', html)
                if not m:
                    m = _re.search(r'"last"\s*:\s*"?([0-9.,]+)"?', html)
                if not m:
                    m = _re.search(r'pid-\d+-last[^>]*>([0-9,.]+)<', html)
                if m:
                    v = _parse_num(m.group(1).replace(",", ""))
                    if _is_valid_vkospi(v):
                        # 변화율도 시도
                        chg = 0.0
                        mc = _re.search(r'data-test="instrument-price-change-percent"[^>]*>\(?([+\-]?[0-9.,]+)\s*%', html) \
                             or _re.search(r'"changePercent"\s*:\s*"?([+\-]?[0-9.,]+)', html) \
                             or _re.search(r'pid-\d+-pcp[^>]*>\(?([+\-]?[0-9.,]+)\s*%', html)
                        if mc:
                            chg = _parse_num(mc.group(1).replace(",", "")) or 0.0
                        log(f"[KSVKOSPI] investing.com: {v} ({chg}%)")
                        return _attach_history({
                            "value": round(v, 2), "change": round(chg, 2),
                            "as_of": datetime.now(KST).strftime("%Y-%m-%d"),
                            "source": "investing.com KOSPI Volatility",
                            "symbol": "KSVKOSPI",
                        })
            except Exception as e:
                log(f"[KSVKOSPI] investing.com 시도 오류 ({url}): {e}")
    except Exception as e:
        log(f"[KSVKOSPI] investing.com 폴백 오류: {e}")
    # 4차: yfinance — 범위 검증으로 KOSPI 잘못 매핑 검출
    try:
        q = fetch_yf("^VKOSPI")
        if q and _is_valid_vkospi(q.get("price")):
            log(f"[KSVKOSPI] yfinance: {q['price']} ({q['change']}%)")
            return _attach_history({"value": q["price"], "change": q["change"], "as_of": datetime.now(KST).strftime("%Y-%m-%d"), "source": "yfinance", "symbol": "KSVKOSPI"})
        elif q and q.get("price"):
            log(f"[KSVKOSPI] yfinance {q['price']} → 범위 벗어남 (KOSPI 오매핑 가능성), 무시")
    except Exception as e:
        log(f"[KSVKOSPI] yfinance 폴백 오류: {e}")
    # 5차: Stooq 만으로 현재값 추출
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
# CNN Fear & Greed Index (시장 심리 종합 지표 0~100)
# ============================================================
def fetch_cnn_fear_greed():
    """CNN Money 공식 Fear & Greed Index 조회.
    공개 JSON 엔드포인트:
      https://production.dataviz.cnn.io/index/fearandgreed/graphdata
    응답: {"fear_and_greed": {"score": ..., "rating": ..., "previous_close": ...},
           "fear_and_greed_historical": {"data": [{"x": ms, "y": score, "rating": ...}, ...]}}
    Returns: {"value": int, "prev": int|None, "rating": str, "as_of": "YYYY-MM-DD",
              "history": {"YYYY-MM-DD": score}, "source": "CNN Fear & Greed Index"} or None.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            "Accept": "application/json",
            "Origin": "https://www.cnn.com",
            "Referer": "https://www.cnn.com/markets/fear-and-greed",
        }
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers=headers, timeout=15,
        )
        if r.status_code != 200 or not r.text:
            log(f"[FNG] HTTP {r.status_code}")
            return None
        j = r.json()
        fg = (j or {}).get("fear_and_greed") or {}
        score = fg.get("score")
        if not isinstance(score, (int, float)) or not (0 <= score <= 100):
            log(f"[FNG] 점수 범위 이상: {score}")
            return None
        prev = fg.get("previous_close")
        rating = fg.get("rating")
        history = {}
        for row in (j.get("fear_and_greed_historical") or {}).get("data", []):
            x = row.get("x"); y = row.get("y")
            if isinstance(y, (int, float)) and 0 <= y <= 100 and isinstance(x, (int, float)):
                try:
                    dt = datetime.fromtimestamp(x/1000, tz=KST).strftime("%Y-%m-%d")
                    history[dt] = round(float(y), 2)
                except Exception:
                    pass
        log(f"[FNG] score={round(score,1)} prev={prev} rating={rating} hist={len(history)}점")
        return {
            "value": round(float(score), 1),
            "prev":  round(float(prev), 1) if isinstance(prev, (int, float)) else None,
            "rating": rating,
            "as_of": datetime.now(KST).strftime("%Y-%m-%d"),
            "history": history,
            "source": "CNN Fear & Greed Index",
        }
    except Exception as e:
        log(f"[FNG] 오류: {e}")
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


def fetch_kis_investor_trading():
    """KIS(한국투자증권) 시장별 투자자 순매수 — 최신 영업일 KOSPI+KOSDAQ 합산(억원).

    사용자 요청: '투자자별 순매매 동향을 KRX/KIS API 로'. pykrx(KRX) 가 KRX 로그인 미설정으로
    비는 경우 KIS 를 보조 소스로 사용한다. KIS_ENABLED=1 + KIS 키가 있을 때만 동작한다.

    안전장치(절대 오류값 미노출): KIS 응답에서 '외국인/기관/개인 순매수 거래대금' 필드를
    명시적으로 식별하지 못하면 빈 dict 를 반환한다(더미/추정 절대 미사용).
    """
    if not (KIS_APP_KEY and KIS_APP_SECRET):
        return {}
    if not kis_get_token():   # KIS_ENABLED 비활성 시 토큰이 없어 안전히 스킵
        return {}
    # 시장별 투자자매매동향(시세) — 최신 누계 순매수.
    markets = {"KOSPI": "0001", "KOSDAQ": "1001"}
    agg = {}   # date -> {foreign, inst, retail} (억원)
    for mkt, code in markets.items():
        res = kis_request(
            "/uapi/domestic-stock/v1/quotations/inquire-investor-time-by-market",
            "FHPTJ04040000",
            params={"FID_INPUT_ISCD": code, "FID_COND_MRKT_DIV_CODE": "U",
                    "FID_INPUT_ISCD_1": code},
        )
        if not res or res.get("rt_cd") != "0":
            continue
        rows = res.get("output") or res.get("output1") or res.get("output2") or []
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            if not isinstance(row, dict):
                continue

            # 키 변형(거래대금 frgn_ntby_tr_pbmn / 수량 frgn_ntby_qty 등)에 대비해 부분 매칭.
            def _pick(actor):
                for k, v in row.items():
                    kl = k.lower()
                    if actor in kl and "ntby" in kl and ("pbmn" in kl or "amt" in kl):
                        return _parse_num(v)
                return None
            frgn = _pick("frgn")
            orgn = _pick("orgn")
            prsn = _pick("prsn")
            if frgn is None or orgn is None or prsn is None:
                continue   # 필드 식별 실패 → 안전히 건너뜀 (오류값 미노출)
            dstr_raw = (row.get("stck_bsop_date") or row.get("bsop_date")
                        or datetime.now(KST).strftime("%Y%m%d"))
            dstr_raw = str(dstr_raw)
            dstr = (f"{dstr_raw[:4]}-{dstr_raw[4:6]}-{dstr_raw[6:8]}"
                    if len(dstr_raw) == 8 and dstr_raw.isdigit() else dstr_raw[:10])
            rec = agg.setdefault(dstr, {"foreign": 0.0, "inst": 0.0, "retail": 0.0})
            # KIS 순매수 거래대금 단위는 원 → 억원(1e8). 백만원 단위 응답 대비 자동 보정은
            # 값 검증으로 갈음(억원 환산 후 |값| 이 비현실적이면 폐기).
            rec["foreign"] += frgn / 1e8
            rec["inst"]    += orgn / 1e8
            rec["retail"]  += prsn / 1e8
    if not agg:
        return {}
    daily = [{
        "date": d,
        "foreign": round(agg[d]["foreign"], 1),
        "inst":    round(agg[d]["inst"], 1),
        "retail":  round(agg[d]["retail"], 1),
    } for d in sorted(agg.keys())]
    # 합리성 검사 — 하루 시장 순매수 합계가 수십조(억원 환산 100만↑) 면 단위 오인 → 폐기.
    if any(abs(x[k]) > 1_000_000 for x in daily for k in ("foreign", "inst", "retail")):
        log("[투자자-KIS] 값 범위 비정상 — 폐기(단위 오인 의심)")
        return {}
    last = daily[-1]
    log(f"[투자자-KIS] {len(daily)}일 수집 최근일={last['date']} "
        f"외국인={last['foreign']:+.0f}억 기관={last['inst']:+.0f}억 개인={last['retail']:+.0f}억")
    return {
        "daily": daily,
        "markets": list(markets.keys()),
        "unit": "억원",
        "source": "KIS 한국투자증권 OpenAPI (시장별 투자자매매동향)",
        "lastFetched": datetime.now(KST).isoformat(),
    }


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
    """등락 데이터 검증.

    - 최소 min_nonzero 개 종목이 chg!=0 이어야 유효 (랭킹 미동작/올-0 garbage 차단).
    - 거래량(vol)이 현재가(price)와 사실상 동일한 행이 과반이면 컬럼 정렬 오류로 보고
      무효 처리한다. (과거 KRX OpenAPI 가 ACML_VOL≈TDD_CLSPRC 로 어긋난 garbage 를
      반환해 'LG전자 +29.9%' 같은 비현실적 상한가 떼가 표시되던 문제의 탐지 신호.
      무효 시 build_data 의 폴백 체인이 pykrx(품질 최고) 로 자동 전환된다.)
    """
    if not items or len(items) < min_nonzero:
        return False
    nonzero = sum(1 for it in items if it.get("chg") and it["chg"] != 0)
    if nonzero < min_nonzero:
        return False
    misaligned = 0
    for it in items:
        try:
            p = float(it.get("price") or 0)
            v = float(it.get("vol") or 0)
        except (TypeError, ValueError):
            continue
        if p > 0 and v > 0 and abs(p - v) <= max(1.0, p * 0.001):
            misaligned += 1
    if misaligned >= max(2, len(items) // 2):
        log(f"[검증] vol≈price 정렬 오류 의심 {misaligned}/{len(items)}건 — 무효 처리(pykrx 폴백 트리거)")
        return False
    return True


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


# pykrx 지수 티커 — KRX 정보데이터시스템(data.krx.co.kr) 공식 일별 종가.
# yfinance(^KS11/^KQ11)는 한국 지수 일별 종가가 며칠씩 지연되는 고질적 문제가 있어
# (spot 은 당일이지만 history 가 3~5 영업일 전에서 멈춤) 카드 헤더의 숫자와 차트 끝점이
# 어긋난다. pykrx 는 KRX 공식 종가를 지연 없이 제공하므로 한국 지수 시계열의 PRIMARY
# 소스로 사용하고, 실패 시에만 yfinance 로 폴백한다.
_PYKRX_INDEX_TICKER = {"KOSPI": "1001", "KOSDAQ": "2001"}


def fetch_pykrx_index_history(name, years=5):
    """pykrx 로 KOSPI/KOSDAQ 지수의 일별 종가 시계열 조회.
    Returns: [{"date":"YYYY-MM-DD","close":NUM}, ...] (오름차순) 또는 None
    """
    if not _PYKRX_AVAILABLE:
        return None
    ticker = _PYKRX_INDEX_TICKER.get(name)
    if not ticker:
        return None
    today = datetime.now(KST)
    fromdate = (today - timedelta(days=int(years * 365.25) + 5)).strftime("%Y%m%d")
    todate = today.strftime("%Y%m%d")
    # pykrx 버전에 따라 get_index_ohlcv / get_index_ohlcv_by_date 둘 중 하나
    getter = getattr(_pykrx_stock, "get_index_ohlcv", None) or \
             getattr(_pykrx_stock, "get_index_ohlcv_by_date", None)
    if getter is None:
        return None
    try:
        df = getter(fromdate, todate, ticker)
        if df is None or df.empty:
            return None
        close_col = "종가" if "종가" in df.columns else ("Close" if "Close" in df.columns else None)
        if close_col is None:
            return None
        out = []
        for idx, row in df.iterrows():
            try:
                close = float(row[close_col])
            except (TypeError, ValueError):
                continue
            if close <= 0 or close != close:  # 0/음수/NaN 제외
                continue
            try:
                date_str = idx.strftime("%Y-%m-%d")
            except Exception:
                date_str = str(idx)[:10]
            out.append({"date": date_str, "close": round(close, 4)})
        out.sort(key=lambda r: r["date"])
        return out if len(out) >= 50 else None
    except Exception as e:
        log(f"[pykrx:idx-hist] {name}({ticker}) 오류: {e}")
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
        h = None
        # 한국 지수(KOSPI/KOSDAQ)는 pykrx(KRX 공식)를 우선 사용 — yfinance 지연 회피
        if name in _PYKRX_INDEX_TICKER:
            h = fetch_pykrx_index_history(name)
            if h:
                log(f"[YF-HIST] IDX {name}: pykrx(KRX 공식) {len(h)} bars / 최신 {h[-1]['date']}")
        if not h:
            h = fetch_yf_history(sym, period="5y")
            if h:
                log(f"[YF-HIST] IDX {name}({sym}): yfinance {len(h)} bars / 최신 {h[-1]['date']}")
        if h:
            out["indices"][name] = h
        else:
            log(f"[YF-HIST] IDX {name}({sym}): 데이터 없음")
    com_map = {
        "Gold":      "GC=F",
        "Silver":    "SI=F",
        "Platinum":  "PL=F",
        "Palladium": "PA=F",
        "Copper":    "HG=F",
        "WTI":       "CL=F",
        "Brent":     "BZ=F",
        "NatGas":    "NG=F",
        "Gasoline":   "RB=F",
        "HeatingOil": "HO=F",
        "Aluminum":  "ALI=F",
        # 농산물 (사용자 요청: ZW=F/ZC=F/ZS=F/ZR=F)
        "Wheat":    "ZW=F",
        "Corn":     "ZC=F",
        "Soybean":  "ZS=F",
        "Rice":     "ZR=F",
        # 소프트 원자재 (ICE)
        "Coffee":   "KC=F",
        "Sugar":    "SB=F",
        "Cocoa":    "CC=F",
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
# 이전 data.json 로드 — 일부 fetch 실패해도 직전 값 보존
# ============================================================
def _load_prev_data(path="data.json"):
    """이전 빌드에서 저장된 data.json 을 로드. 첫 빌드/파일 없음 시 빈 dict.

    매 시간 cron 에서 외부 API 가 일시적으로 실패해도 이전 값을 그대로
    표시할 수 있도록 사용. _preserve_from_prev() 가 머지 정책을 결정.
    """
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        log(f"[prev-data] {path} 로드 실패 (무시): {e}")
        return {}


def _metric_is_empty(v):
    """단일 지표 dict({value, history, ...})가 '실데이터 없음'인지 판정.

    R-ONE/MOLIT 가 빈 응답일 때 value=0·history 전부 0 인 껍데기가 만들어지고,
    이것이 preserve 로 매 빌드 carry-forward 되어 "API 응답 없음" 이 사라지지 않는다.
    그런 0-only 지표를 비어있는 것으로 보아 보존 대상에서 제외한다.

    Returns: True(빈 지표) / False(유효) / None(지표 형태 아님).
    """
    if not isinstance(v, dict) or "value" not in v:
        return None
    val = v.get("value")
    if val is None:
        return True
    if val == 0:
        hist = v.get("history")
        if isinstance(hist, dict) and hist:
            return all(hv in (None, 0) for hv in hist.values())
        return True  # 값 0 + 시계열 없음 → 실데이터 아님
    return False


def _is_effectively_empty(val):
    """preserve 판정용 'effectively empty' 체크.

    None, [], {}, "" 외에도:
    - 뉴스: 모든 카테고리 리스트가 비어있으면 effectively empty
      (단 lastFetched 만 있어도 의미 없음 — 본문 없는 dict 는 빈 것으로 간주).
    - 캘린더: events 가 비어있으면 effectively empty.
    - 지표 컨테이너(realestate.kr 등): 모든 하위 지표가 0-only 면 effectively empty.
    """
    if val is None:
        return True
    if isinstance(val, str):
        return val.strip() == ""
    if isinstance(val, list):
        return len(val) == 0
    if isinstance(val, dict):
        if len(val) == 0:
            return True
        # economicCalendar 형식
        if "events" in val and isinstance(val["events"], list):
            return len(val["events"]) == 0
        # news 형식: 카테고리 리스트 dict (lastFetched/cutoff 등 메타 제외)
        meta_keys = {"lastFetched", "cutoff", "filteredManually", "source"}
        cat_lists = [v for k, v in val.items() if k not in meta_keys and isinstance(v, list)]
        if cat_lists and all(len(lst) == 0 for lst in cat_lists):
            return True
        # stockMovers/etfMovers 형식: kospiGainers/kospiLosers/etfGainers/etfLosers
        movers_keys = ("kospiGainers", "kospiLosers", "etfGainers", "etfLosers")
        if any(k in val for k in movers_keys):
            return all(not val.get(k) for k in movers_keys)
        # 단일 지표 dict (value/history) — 0-only 면 빈 것으로 간주
        single = _metric_is_empty(val)
        if single is not None:
            return single
        # 지표 컨테이너 (realestate.kr / economicIndicators.* 등):
        # 모든 하위 값이 지표 dict 이고 전부 0-only 면 컨테이너도 빈 것으로 간주
        flags = [_metric_is_empty(vv) for vv in val.values()]
        if flags and all(f is not None for f in flags):
            return all(flags)
        return False
    return False


def _preserve_from_prev(data, prev, keys, fresh_label=None):
    """현재 빌드 결과가 비어 있을 때 이전 빌드의 값을 보존.

    Args:
        data: 현재 빌드 결과 (mutable)
        prev: 이전 data.json (read-only)
        keys: 보존 후보 key 리스트 — 각 항목은 'top_key' 또는
              'top.sub.path' 형식. effectively empty 일 때 보존.
        fresh_label: 보존 시 sources 에 표시할 라벨 prefix.

    Returns: 보존된 key 개수.
    """
    if not prev:
        return 0
    preserved = 0
    for k in keys:
        try:
            cur = data
            par = None
            parent_key = None
            parts = k.split(".")
            for i, part in enumerate(parts):
                if not isinstance(cur, dict):
                    cur = None
                    break
                if i == len(parts) - 1:
                    par = cur
                    parent_key = part
                    cur = cur.get(part)
                else:
                    nxt = cur.get(part)
                    if nxt is None or not isinstance(nxt, dict):
                        cur = None
                        break
                    cur = nxt
            # 현재 비었음 판정 (effectively empty)
            if not _is_effectively_empty(cur) or par is None:
                continue
            # 이전 값 탐색
            pcur = prev
            for part in parts:
                if not isinstance(pcur, dict):
                    pcur = None
                    break
                pcur = pcur.get(part)
                if pcur is None:
                    break
            # 이전 값도 비어있으면 (또는 effectively empty) 보존할 이유 없음
            if pcur is None or _is_effectively_empty(pcur):
                continue
            par[parent_key] = pcur
            preserved += 1
            # 보존된 소스 메타 라벨링 — 단일 hop 으로만 표기 (무한 누적 방지).
            # 직전 라벨이 이미 "보존 ← 보존 ← … (ts)(ts)" 로 쌓였으면 원본 소스만 추출해 1회만 감싼다.
            try:
                src_key = parts[0]
                prev_src = (prev.get("sources") or {}).get(src_key) or "prev"
                prev_iso = prev.get("lastUpdated") or ""
                orig = prev_src.split(" ← ")[-1]                       # 누적 체인의 원본 소스
                orig = re.sub(r"(\s*\(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\))+\s*$", "", orig).strip() or "prev"
                label = f"{fresh_label or 'preserved'} ← {orig}"
                if prev_iso:
                    label = f"{label} ({prev_iso[:16]})"
                data.setdefault("sources", {})[src_key] = label
            except Exception:
                pass
            log(f"[preserve] {k}: 현재 비어있어 직전 값 보존")
        except Exception as e:
            log(f"[preserve] {k} 보존 실패 (무시): {e}")
    return preserved


def _restore_missing_metrics(cur_node, prev_node):
    """prev_node 의 개별 지표(metric leaf)를 cur_node 에 '지표 단위'로 채운다.

    배경(중요 버그):
      _preserve_from_prev 는 컨테이너 단위(예: economicIndicators.us)로만
      비어있음을 판정한다. 그런데 FRED 일시 실패로 us={dxy_idx}(yfinance) 처럼
      '일부만 남은' 상태가 되면 컨테이너는 '비어있지 않음'으로 보여 VIX 등
      나머지 16개 FRED 지표가 영구 손실됐다. (실제 2026-05-29 KST 09:00 발생.)

    해결: 컨테이너 내부를 leaf 단위로 순회하여, 현재 빌드에서 누락/빈값인
    지표만 직전 빌드의 유효값으로 복원한다. 신선하게 수집된 지표는 절대
    덮어쓰지 않는다(누락분만 채움).

    구조 차이 자동 처리:
      - economicIndicators: 2단계 (economicIndicators.us.vix.value)
      - sentiment/realestate: 혼합 → metric dict('value' 보유)면 leaf 로,
        그 외 dict 면 한 단계 더 재귀.
    """
    restored = 0
    if not isinstance(prev_node, dict) or not isinstance(cur_node, dict):
        return 0
    for k, pv in prev_node.items():
        cv = cur_node.get(k)
        if isinstance(pv, dict) and "value" in pv:
            # 지표 leaf — 현재 누락/빈값이고 직전이 유효하면 복원
            cur_empty = (k not in cur_node) or _is_effectively_empty(cv)
            if cur_empty and not _is_effectively_empty(pv):
                cur_node[k] = pv
                restored += 1
        elif isinstance(pv, dict):
            # 중첩 컨테이너(국가 등) — 현재에 없으면 통째로, 있으면 한 단계 재귀
            if not isinstance(cv, dict):
                if not _is_effectively_empty(pv):
                    cur_node[k] = pv
                    restored += 1
            else:
                restored += _restore_missing_metrics(cv, pv)
    return restored


def _preserve_indicators_deep(data, prev, container_keys, fresh_label="이전 빌드 보존(지표)"):
    """지표 컨테이너(economicIndicators 등) 내부를 leaf 단위로 직전 빌드에서 보강.

    _preserve_from_prev(컨테이너 단위) 의 사각지대를 메운다. 컨테이너 전체가
    비면 _preserve_from_prev 가, 일부만 비면 이 함수가 처리한다.

    Returns: 복원된 지표(leaf) 개수.
    """
    if not prev:
        return 0
    total = 0
    for ck in container_keys:
        cur = data.get(ck)
        pcur = prev.get(ck)
        if not isinstance(pcur, dict):
            continue
        if not isinstance(cur, dict):
            # 컨테이너 자체가 통째로 비었으면 직전 것으로 (방어적)
            if not _is_effectively_empty(pcur):
                data[ck] = pcur
                total += 1
            continue
        n = _restore_missing_metrics(cur, pcur)
        if n:
            total += n
            # 소스 라벨에 보강 흔적 남기기 (이미 'preserved' 라벨이면 중복 표기 안 함)
            try:
                src_key = f"{ck}_partial"
                data.setdefault("sources", {}).setdefault(
                    src_key, f"{fresh_label}: {n}개 지표 보강"
                )
            except Exception:
                pass
            log(f"[preserve-deep] {ck}: 누락 지표 {n}개를 직전 빌드 값으로 보강")
    return total


# ============================================================
# 메인 빌드
# ============================================================
def _reconcile_history_with_spot(data, now):
    """차트 끝점을 실시간 spot 값과 일치시킨다 (공통 보정).

    문제: 카드 헤더의 큰 숫자(spot)와 그 아래/상세 모달의 차트 마지막 점(history close)이
    서로 다른 소스에서 와서 어긋난다. 예) KOSPI spot=8047(KRX 당일)인데 history 마지막은
    7847(yfinance, 며칠 전). 사용자는 "차트와 수치가 맞지 않는다"고 인식한다.

    해결: indices/fx/commodities 모든 시계열의 마지막 점을 최신 영업일 기준으로 spot 과
    동기화. 마지막 점이 오늘이면 값 갱신, 더 과거이고 값이 유의미하게 다르면 오늘 점 추가.
    주말은 직전 영업일로 롤백(공휴일은 eps 가드로 중복 방지). 모든 카드/상세 차트가
    data.history 를 공유하므로 이 한 번의 보정이 전 차트에 일괄 적용된다.
    """
    hist = data.get("history") or {}
    specs = [
        ("indices",     data.get("indices", {}),     "price"),
        ("fx",          data.get("fx", {}),          "rate"),
        ("commodities", data.get("commodities", {}), "price"),
    ]
    tgt = now
    while tgt.weekday() >= 5:  # 토(5)/일(6) → 직전 영업일
        tgt -= timedelta(days=1)
    target_date = tgt.strftime("%Y-%m-%d")
    synced = 0
    for cat, spot_map, field in specs:
        series_map = hist.get(cat) or {}
        for name, arr in series_map.items():
            if not isinstance(arr, list) or not arr:
                continue
            spot_obj = spot_map.get(name) or {}
            spot = spot_obj.get(field)
            try:
                spot = float(spot)
            except (TypeError, ValueError):
                continue
            if spot <= 0:
                continue
            last = arr[-1]
            last_date = last.get("date", "")
            try:
                last_close = float(last.get("close"))
            except (TypeError, ValueError):
                continue
            if last_date == target_date:
                if abs(spot - last_close) > 1e-9:
                    last["close"] = round(spot, 4)
                    synced += 1
            elif last_date and last_date < target_date:
                # 새 영업일 — 값이 유의미하게(>0.01%) 다를 때만 오늘 점 추가
                rel = abs(spot - last_close) / (abs(last_close) or 1.0)
                if rel > 1e-4:
                    arr.append({"date": target_date, "close": round(spot, 4)})
                    synced += 1
            # last_date > target_date (미래) 는 건드리지 않음
    if synced:
        log(f"[reconcile] 차트 끝점 ↔ spot 동기화: {synced}개 시계열 (기준 {target_date})")
        data.setdefault("diagnostics", {})["historySpotSynced"] = synced
    return synced


def build_data():
    now = datetime.now(KST)
    prev = _load_prev_data("data.json")
    if prev:
        log(f"[prev-data] 이전 빌드 로드 OK (lastUpdated={prev.get('lastUpdated','')[:16]})")
    data = {
        "lastUpdated": now.isoformat(),
        "sources": {},
        "fx": {},
        "indices": {},
        "commodities": {},
        "stockMovers": {},
        "etfMovers": {},
        "investorTrading": {},
        "freight": {},  # 해상 운임지수 (SCFI/CCFI/BDI 계열)
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

        # ── KOSPI 상승/하락 Top10 ──
        # pykrx 를 PRIMARY 로 둔다(품질 최고·무인증). KRX OpenAPI 는 pykrx 실패 시에만 보조.
        # (과거엔 KRX OpenAPI 가 1순위였고, vol≈price 로 어긋난 garbage 가 약한 검증을 통과해
        #  'LG전자 +29.9%' 같은 비현실적 상한가 떼가 그대로 표시됐다 — 이제 pykrx 우선 +
        #  강화된 _is_valid_mover_list 로 차단한다.)
        try:
            pkg, pkl = fetch_pykrx_stock_movers(market="KOSPI", top_n=10)
        except Exception as e:
            log(f"[pykrx] 1순위 주식 movers 오류: {e}")
            pkg, pkl = None, None
        if _is_valid_mover_list(pkg):
            data["stockMovers"]["kospiGainers"] = pkg
            data["sources"]["stockMovers"] = "pykrx (KRX 정보데이터시스템)"
        if _is_valid_mover_list(pkl):
            data["stockMovers"]["kospiLosers"] = pkl
            data["sources"].setdefault("stockMovers", "pykrx (KRX 정보데이터시스템)")
        # pykrx 가 비면 KRX OpenAPI 로 보조 (검증 통과분만 채택)
        if not (data["stockMovers"].get("kospiGainers") and data["stockMovers"].get("kospiLosers")):
            gainers, losers = fetch_krx_stock_movers("kospi", top_n=10)
            if _is_valid_mover_list(gainers) and not data["stockMovers"].get("kospiGainers"):
                data["stockMovers"]["kospiGainers"] = gainers
                data["sources"].setdefault("stockMovers", "KRX OpenAPI")
            elif gainers and not data["stockMovers"].get("kospiGainers"):
                log(f"[KRX] 상승종목 {len(gainers)}건 garbage — 폴백 트리거")
            if _is_valid_mover_list(losers) and not data["stockMovers"].get("kospiLosers"):
                data["stockMovers"]["kospiLosers"] = losers
                data["sources"].setdefault("stockMovers", "KRX OpenAPI")
            elif losers and not data["stockMovers"].get("kospiLosers"):
                log(f"[KRX] 하락종목 {len(losers)}건 garbage — 폴백 트리거")

        # ETF 상승/하락 Top10 (KRX OpenAPI — 실패 시 이후 pykrx/Naver 폴백)
        etf_up, etf_down = fetch_krx_etf_movers(top_n=10)
        if etf_up:
            data["etfMovers"]["etfGainers"] = etf_up
        if etf_down:
            data["etfMovers"]["etfLosers"] = etf_down
        if data["etfMovers"].get("etfGainers") or data["etfMovers"].get("etfLosers"):
            data["sources"].setdefault("etfMovers", "KRX OpenAPI")
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

    # pykrx + Naver 모두 실패 → yfinance 폴백 (주요 한국 ETF 30종)
    if not data["etfMovers"].get("etfGainers") or not data["etfMovers"].get("etfLosers"):
        try:
            yf_up, yf_down = fetch_yf_kr_etf_movers(top_n=10)
            if yf_up and not data["etfMovers"].get("etfGainers"):
                data["etfMovers"]["etfGainers"] = yf_up
                data["sources"]["etfMovers"] = "yfinance (주요 한국 ETF 30종)"
            if yf_down and not data["etfMovers"].get("etfLosers"):
                data["etfMovers"]["etfLosers"] = yf_down
                if not data["sources"].get("etfMovers"):
                    data["sources"]["etfMovers"] = "yfinance (주요 한국 ETF 30종)"
        except Exception as e:
            log(f"[YF-ETF] 폴백 오류: {e}")

    # ── 투자자별 순매매 동향 (외국인/기관/개인) — pykrx 실데이터 ──
    # 이전: 프론트엔드가 Math.random/sin·cos 로 가짜 데이터를 생성했음(=더미).
    # 이제: KRX 정보데이터시스템의 실제 투자자별 거래실적을 서버에서 수집해 data.json 에 싣고,
    #       프론트엔드는 그것만 사용한다(수집 전에는 '수집 중' 안내, 더미 없음).
    try:
        inv = fetch_investor_trading()
        if inv and inv.get("daily"):
            data["investorTrading"] = inv
            data["sources"]["investorTrading"] = inv.get("source", "pykrx")
        else:
            log("[투자자] 실데이터 미수집 — investorTrading 비움 (프론트 '수집 중' 표시)")
    except Exception as e:
        log(f"[투자자] 수집 오류: {e}")

    # ── 해상 운임지수(운송): SCFI/CCFI/BDI 등 — 네이버 시장지표 best-effort ──
    # 실패 시 직전 빌드의 freight 를 보존(있으면) → 일시 실패에도 마지막 값 유지.
    try:
        fr = fetch_freight_indices()
        if fr and fr.get("items"):
            data["freight"] = fr
            data["sources"]["freight"] = fr.get("source", "Naver 시장지표")
        else:
            prev_fr = (prev.get("freight") or {}) if isinstance(prev, dict) else {}
            if prev_fr.get("items"):
                data["freight"] = prev_fr
                log(f"[운임] 신규 수집 실패 — 직전 빌드 보존({len(prev_fr['items'])}건)")
            else:
                log("[운임] 미수집 — freight 비움 (프론트 '수집 중' + 네이버 링크)")
    except Exception as e:
        log(f"[운임] 수집 오류: {e}")

    # 진단 정보 — 어떤 소스가 성공/실패했는지 frontend 에서 표시 가능
    data.setdefault("diagnostics", {})
    data["diagnostics"]["stockMoversSource"] = data["sources"].get("stockMovers", "FAILED")
    data["diagnostics"]["etfMoversSource"]   = data["sources"].get("etfMovers",   "FAILED")
    data["diagnostics"]["investorTradingDays"] = len((data.get("investorTrading") or {}).get("daily", []))
    data["diagnostics"]["kisEnabled"]        = KIS_ENABLED
    data["diagnostics"]["pykrxAvailable"]    = _PYKRX_AVAILABLE
    data["diagnostics"]["krxLoginAvailable"] = _KRX_LOGIN_AVAILABLE
    # 투자자별 순매매가 비었을 때 프론트가 사용자에게 보여줄 사유.
    # 이제 무인증 Naver 폴백이 있어, 비어있으면 두 소스(KRX/Naver) 모두 일시 실패한 상황.
    if not (data.get("investorTrading") or {}).get("daily"):
        data["diagnostics"]["investorTradingReason"] = (
            "투자자별 순매매 데이터를 실시간으로 불러오는 중입니다… (서버가 차단된 경우 대시보드가 "
            "브라우저에서 네이버 금융을 통해 직접 가져옵니다). 서버측 전체 시계열을 원하면 "
            "Secrets 에 KRX_ID/KRX_PW(무료 data.krx.co.kr 계정, KRX API)를 등록하거나, "
            "한국투자증권 API 사용 시 KIS_APP_KEY/KIS_APP_SECRET 등록 + 변수 KIS_ENABLED=1 로 설정하세요."
        )

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
        "Gold":      "GC=F",
        "Silver":    "SI=F",
        "Platinum":  "PL=F",
        "Palladium": "PA=F",   # 팔라듐 (NYMEX) — 자동차 촉매 수요 핵심 귀금속
        "Copper":    "HG=F",
        "WTI":       "CL=F",
        "Brent":     "BZ=F",
        "NatGas":    "NG=F",
        # 정유 제품 (NYMEX) — 휘발유/난방유 선물
        "Gasoline":   "RB=F",  # RBOB 휘발유 ($/gal)
        "HeatingOil": "HO=F",  # 난방유 ($/gal)
        # 비철금속 (LME 선물)
        "Aluminum": "ALI=F",
        # 농산물 (시카고 상품거래소 선물) — 사용자 요청에 따라 yfinance ZW=F/ZC=F/ZS=F/ZR=F
        "Wheat":    "ZW=F",
        "Corn":     "ZC=F",
        "Soybean":  "ZS=F",
        "Rice":     "ZR=F",
        # 소프트 원자재 (ICE 선물) — 커피/설탕/코코아
        "Coffee":   "KC=F",    # 커피 (¢/lb)
        "Sugar":    "SB=F",    # 설탕 11호 (¢/lb)
        "Cocoa":    "CC=F",    # 코코아 ($/MT)
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
        # VIX 폴백 — FRED VIXCLS 가 누락/실패한 경우 yfinance ^VIX 로 독립 보강.
        # (VIX 는 사용자가 시장분위기 카드에서 가장 먼저 보는 지표 → 절대 빈 값 방지.)
        # FRED VIXCLS 는 전일 종가(일 1회)라 약간 지연되며, yfinance ^VIX 는 장중
        # 실시간에 가까워 보강값이 더 최신일 수 있다.
        try:
            us_vix = (data["economicIndicators"]["us"].get("vix") or {})
            if us_vix.get("value") is None:
                log("[yf-VIX] FRED VIX 누락 → yfinance ^VIX 보강 시도")
                vix_quote = fetch_yf("^VIX")
                if vix_quote and vix_quote.get("price"):
                    vix_hist = fetch_yf_history("^VIX", period="5y")
                    vix_hist_map = {}
                    for pt in (vix_hist or []):
                        if pt.get("close") and pt["close"] > 0:
                            vix_hist_map[pt["date"]] = round(pt["close"], 2)
                    data["economicIndicators"]["us"]["vix"] = {
                        "value":  round(vix_quote["price"], 2),
                        "change": vix_quote.get("change", 0),
                        "period": datetime.now(KST).strftime("%Y-%m-%d"),
                        "desc":   "VIX 변동성 지수",
                        "source": "yfinance ^VIX",
                        "history": vix_hist_map,
                    }
                    log(f"[yf-VIX] VIX = {vix_quote['price']} ({vix_quote.get('change',0):+.2f}%)")
                else:
                    log("[yf-VIX] ^VIX 응답 없음 — preserve 로 직전 값 복원 예정")
        except Exception as e:
            log(f"[yf-VIX] 오류: {e}")
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

        # PMI 지표 — 국가별 제조업 PMI (OECD BSCICP02 via FRED)
        log("[PMI] 국가별 제조업 PMI 수집 시작")
        try:
            pmi_data = fetch_pmi_indicators()
            for cc, ind in pmi_data.items():
                data["economicIndicators"].setdefault(cc, {}).update(ind)
            if pmi_data:
                data["sources"]["pmi"] = "S&P Global PMI(웹) 우선 + FRED OECD BCI 폴백 + ECOS BSI(한국)"
        except Exception as e:
            log(f"[PMI] 수집 오류: {e}")

        # UK BOE Bank Rate 보강 (FRED IRSTCB01GBM156N 가 누락된 경우)
        try:
            uk_node = data["economicIndicators"].get("uk", {}) or {}
            if not (uk_node.get("base_rate_uk") or {}).get("value"):
                log("[BoE] UK base_rate_uk 누락 → Bank of England IADB 직접 페치")
                boe = fetch_boe_bank_rate()
                if boe:
                    data["economicIndicators"].setdefault("uk", {})["base_rate_uk"] = boe
                    data["sources"]["uk_base_rate"] = boe.get("source", "BoE IADB")
        except Exception as e:
            log(f"[BoE] 보강 오류: {e}")
    else:
        log("[FRED] API 키 없음 — 미국 지표 건너뜀")

    # ── Alpha Vantage 보강 (미국 지표 cross-check + 원자재 보강) ──
    # 일 25회 한도라 09:00/22:00 KST 일일 갱신 시점에만 호출.
    # AV_FETCH_FULL=1 환경변수가 있거나 매시간 cron 이 아닌 일일 트리거인 경우 활성.
    av_mode = os.environ.get("AV_FETCH_FULL", "").strip()
    now_hour_utc = datetime.now(timezone.utc).hour
    # UTC 00:00 (KST 09:00) 또는 UTC 13:00 (KST 22:00) ±30분 윈도우면 자동 활성
    is_daily_window = now_hour_utc in (0, 13)
    if ALPHAVANTAGE_API_KEY and (av_mode in ("1", "true", "yes") or is_daily_window):
        log(f"[AV] Alpha Vantage 보강 모드 활성 (hour_utc={now_hour_utc}, mode={av_mode or 'auto'})")
        try:
            av_us = fetch_av_us_economic()
            if av_us:
                data["economicIndicators"].setdefault("us", {}).update(av_us)
                data["sources"]["av_us"] = "Alpha Vantage (US 경제지표 cross-check)"
                log(f"[AV] US 지표 {len(av_us)}개 보강")
        except Exception as e:
            log(f"[AV] US 보강 오류: {e}")
        # 원자재 보강 — WTI/BRENT/COPPER/ALUMINUM 의 일일 가격
        try:
            for func, key in [("WTI", "WTI"), ("BRENT", "Brent"),
                              ("COPPER", "Copper"), ("ALUMINUM", "Aluminum"),
                              ("NATURAL_GAS", "NaturalGas")]:
                # 기존 가격이 비어있거나 변동률이 0인 경우만 보강
                cur = data.get("commodities", {}).get(key) or {}
                if cur.get("price") and cur.get("change", 0) != 0:
                    continue
                av_com = fetch_av_commodity(func)
                if av_com:
                    data.setdefault("commodities", {})[key] = {
                        "price":  av_com["price"],
                        "change": av_com["change"],
                    }
                    data["sources"].setdefault(f"commodity_{key}", av_com["source"])
                    log(f"[AV] {key} ({func}): {av_com['price']} ({av_com['change']:+.2f}%)")
        except Exception as e:
            log(f"[AV] 원자재 보강 오류: {e}")
    else:
        log(f"[AV] 보강 비활성 (현재시각 KST 09/22시 ±30분 또는 AV_FETCH_FULL=1 시 활성)")

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
    # R-ONE 우선 → 실패/키없음이면 ECOS KB 시리즈로 폴백 (사용자 화면 비지 않도록)
    re_data = {}
    re_diag = {"rone_tried": False, "rone_ok": False, "ecos_tried": False, "ecos_ok": False,
               "fred_tried": False, "fred_ok": False}
    if REALESTATE_API_KEY:
        log("[R-ONE] 한국 부동산 지표 수집 시작")
        re_diag["rone_tried"] = True
        re_data = fetch_realestate_kr() or {}
        if re_data.get("apt_price_idx_kr") or re_data.get("jns_price_idx_kr"):
            data["sources"]["realestate_kr"] = "R-ONE API (reb.or.kr)"
            re_diag["rone_ok"] = True
            log(f"[R-ONE] 성공: {list(re_data.keys())}")
        else:
            log("[R-ONE] 매매/전세 가격지수 미수집 — ECOS 폴백 시도")
    else:
        log("[R-ONE] API 키 없음 — ECOS 폴백 시도")
    # ECOS 폴백: 매매/전세 가격지수가 모두 비어있을 때만
    if (not re_data.get("apt_price_idx_kr")) or (not re_data.get("jns_price_idx_kr")):
        re_diag["ecos_tried"] = True
        try:
            ecos_fb = fetch_realestate_kr_ecos_fallback()
            for k, v in ecos_fb.items():
                if not re_data.get(k):
                    re_data[k] = v
            if ecos_fb:
                re_diag["ecos_ok"] = True
                if not data["sources"].get("realestate_kr"):
                    data["sources"]["realestate_kr"] = "ECOS API (KB/BOK 부동산 시계열 폴백)"
                log(f"[RE-FB] ECOS 폴백 성공: {list(ecos_fb.keys())}")
            else:
                log("[RE-FB] ECOS 폴백도 응답 없음 — 모든 시리즈 후보 실패")
        except Exception as e:
            log(f"[RE-FB] 오류: {e}")
    # FRED(BIS) 폴백: 매매가격지수가 여전히 비어있으면 BIS 한국 주거용 부동산 지수로 보강.
    # R-ONE/ECOS 가 모두 실패하는 환경에서도 FRED 는 안정적이라 사용자 화면이 비지 않도록 함.
    if not re_data.get("apt_price_idx_kr"):
        re_diag["fred_tried"] = True
        try:
            fred_fb = fetch_fred_realestate_kr()
            for k, v in fred_fb.items():
                if not re_data.get(k):
                    re_data[k] = v
            if fred_fb.get("apt_price_idx_kr"):
                re_diag["fred_ok"] = True
                if not data["sources"].get("realestate_kr"):
                    data["sources"]["realestate_kr"] = "FRED(BIS) 한국 주거용 부동산 가격지수 폴백"
                log(f"[RE-FB] FRED(BIS) 폴백 성공: {list(fred_fb.keys())}")
            else:
                log("[RE-FB] FRED(BIS) 폴백도 응답 없음")
        except Exception as e:
            log(f"[RE-FB] FRED 폴백 오류: {e}")
    # 0-only 껍데기 지표 제거 — "API 응답 없음"이 매 빌드 carry-forward 되는 것을 차단.
    re_data = {k: v for k, v in re_data.items() if _metric_is_empty(v) is not True}
    data["realestate"]["kr"] = re_data
    # 진단 노드에 미수집 사유 기록 — 프론트엔드/사용자가 어떤 단계가 실패했는지 확인 가능
    data.setdefault("diagnostics", {})["realestate_kr"] = re_diag

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

    # ── CNN Fear & Greed Index (시장 심리 종합 지표) ────────
    try:
        fg = fetch_cnn_fear_greed()
        if fg:
            data["sentiment"]["fear_greed"] = fg
            data["sources"]["fear_greed"] = fg.get("source", "CNN Money")
    except Exception as e:
        log(f"[FNG] 오류: {e}")

    # ── 월간 거래량: 한국부동산원 '행정구역별 아파트거래현황'(R-ONE) 1차 → 국토부 실거래(MOLIT) 보강 ──
    # 국토부 실거래가는 당월 신고 lag 으로 0 만 반환하는 경우가 잦아(=API 로 실데이터 확보 불가),
    # 부동산원 API 에서 확인되는 '행정구역별 아파트거래현황'(전국·동(호)수) 을 기본 거래량 소스로 쓴다.
    re_kr = data["realestate"].setdefault("kr", {})
    if re_kr.get("trade_count_kr_rone") and _metric_is_empty(re_kr["trade_count_kr_rone"]) is not True:
        rone_trade = dict(re_kr["trade_count_kr_rone"])
        rone_trade.setdefault("desc", "한국부동산원 행정구역별 아파트거래현황 (전국·동(호)수)")
        data["realestate"]["kr"]["trade_count_kr"] = rone_trade
        data["sources"]["realestate_kr_trade"] = "R-ONE 행정구역별 아파트거래현황 (reb.or.kr)"
        log(f"[거래량] R-ONE 행정구역별 아파트거래현황 사용: {rone_trade.get('period')} {rone_trade.get('value')}")
    # MOLIT 실거래가 — 실제 비영(非零) 데이터가 있을 때만 (더 세분화된 아파트 실거래) 우선 사용
    if DATA_GO_KR_API_KEY:
        try:
            log("[MOLIT] 국토부 아파트 매매 실거래 거래량 수집 시작")
            apt_trades = fetch_molit_apt_trade_count(months_back=6)
            if apt_trades:
                apt_trades = {k: v for k, v in apt_trades.items() if v and v > 0}
            if apt_trades:
                sorted_keys = sorted(apt_trades.keys())
                latest = sorted_keys[-1]
                prev = sorted_keys[-2] if len(sorted_keys) > 1 else None
                cur_cnt = apt_trades[latest]
                prev_cnt = apt_trades[prev] if prev else None
                chg = round((cur_cnt - prev_cnt) / prev_cnt * 100, 2) if prev_cnt else None
                data["realestate"]["kr"]["trade_count_kr"] = {
                    "value": cur_cnt, "prev": prev_cnt, "chg": chg, "period": latest,
                    "desc": "전국 아파트 매매 실거래 건수",
                    "source": "data.go.kr (MOLIT 1613000)",
                    "history": apt_trades,
                }
                data["sources"]["realestate_molit"] = "data.go.kr (국토부 실거래가)"
                log(f"[MOLIT] 성공(우선 적용): {latest} {cur_cnt:,}건 (prev {prev}: {prev_cnt:,}건)")
            else:
                log("[MOLIT] 최근 6개월 실거래 0 — R-ONE 부동산거래현황 값 유지")
        except Exception as e:
            log(f"[MOLIT] 오류: {e}")
    else:
        log("[MOLIT] DATA_GO_KR_API_KEY 없음 — R-ONE 부동산거래현황 값 유지")

    # ── 청약홈 분양정보 (지역별 드릴다운용) ──────────────────
    # 프론트 '청약 경쟁률' 지역 클릭 시 최근 분양 단지를 지역별로 보여주기 위함.
    # 진단 문자열을 항상 data.json.diagnostics.subscription 에 기록 → 원격에서 실패 원인 점검.
    try:
        subs, sub_diag = fetch_applyhome_subscription()
        data.setdefault("diagnostics", {})["subscription"] = sub_diag
        if subs and subs.get("byRegion"):
            data["subscription"] = subs
            data["sources"]["subscription"] = subs.get("source", "청약홈(data.go.kr)")
    except Exception as e:
        log(f"[청약홈] 수집 오류: {e}")
        data.setdefault("diagnostics", {})["subscription"] = f"EXC {type(e).__name__}:{str(e)[:80]}"

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

    # ── 두바이 현물유 (FRED POILDUBUSDM) ─────────────────────
    # data["history"] 가 위에서 세팅된 뒤 실행해야 history.commodities.Dubai 가 보존된다.
    if FRED_API_KEY:
        try:
            dub, dub_hist = fetch_dubai_crude()
            if dub:
                data.setdefault("commodities", {})["Dubai"] = dub
                if dub_hist:
                    data.setdefault("history", {}).setdefault("commodities", {})["Dubai"] = dub_hist
                data["sources"]["commodity_Dubai"] = "FRED POILDUBUSDM (두바이 현물유, 월간)"
                log(f"[FRED] 두바이 현물유 = ${dub['price']} ({dub['change']:+.2f}%)")
            else:
                log("[FRED] 두바이유(POILDUBUSDM) 응답 없음 — 프론트 폴백값 유지")
        except Exception as e:
            log(f"[FRED] 두바이유 오류: {e}")

    # ── 뉴스 기사 (Google News RSS) ──────────────────
    # 클라이언트 CORS 프록시 의존도를 줄이기 위해 서버측에서 미리 가져와
    # data.json 에 저장. 프론트엔드는 이를 우선 사용하고, 실패 시 클라이언트 페치로 폴백.
    try:
        log("[News] Google News RSS 카테고리별 기사 수집 시작")
        news_data = fetch_news_all_feeds()
        if news_data:
            data["news"] = news_data
            data["sources"]["news"] = "Google News RSS + Bing News + Naver (서버측 페치)"
            total = sum(len(v) for v in news_data.values()) - 1  # exclude 'lastFetched' field
            log(f"[News] 총 {total}건 기사 수집 완료")
    except Exception as e:
        log(f"[News] 수집 오류: {e}")

    # ── 경제 캘린더 (FRED Release Dates) ──────────────────
    # 매일 09:00 / 22:00 KST 트리거 — 오늘 발표될 지표를 자동 백필.
    # 프런트엔드 calEvents (하드코드) 와 머지되어 UI 에 표시됨.
    try:
        log("[Calendar] 경제 캘린더 수집 시작 (FRED release dates)")
        cal_data = fetch_economic_calendar()
        if cal_data:
            # 서버측 자동 백필 — 과거 이벤트의 prev/fore/act 값을 economicIndicators 에서 채움
            try:
                events = cal_data.get("events", []) or []
                filled = backfill_calendar_actuals(events, data)
                cal_data["events"] = events
                cal_data["backfilled"] = filled
            except Exception as e:
                log(f"[Calendar] 백필 오류: {e}")
            data["economicCalendar"] = cal_data
            data["sources"]["economicCalendar"] = cal_data.get("source", "FRED")
            log(f"[Calendar] 수집 완료: {len(cal_data.get('events', []))}건 (백필 {cal_data.get('backfilled',0)})")
    except Exception as e:
        log(f"[Calendar] 수집 오류: {e}")

    # ── 이전 데이터 보존 (직전 빌드 머지) ─────────────────────
    # 외부 API 가 일시적으로 실패해도 사용자 화면이 비지 않도록,
    # 현재 빌드에서 비어 있는 주요 필드만 직전 data.json 의 값으로 복원.
    # 비어있지 않은 필드는 그대로 새 값 사용.
    try:
        preserved = _preserve_from_prev(
            data, prev,
            keys=[
                # 등락 종목/ETF — KRX/pykrx/Naver 모두 실패 시 직전 값 유지
                "stockMovers.kospiGainers",
                "stockMovers.kospiLosers",
                "etfMovers.etfGainers",
                "etfMovers.etfLosers",
                # 뉴스 — Google/Naver/Bing 모두 실패 시 직전 값 유지
                "news",
                # 경제 캘린더 — FRED 실패 시 직전 값 유지
                "economicCalendar",
                # 부동산 — R-ONE/KOSIS 실패 시 직전 값 유지
                "realestate.kr",
                "realestate.us",
                # 거시 지표 (서브 카테고리별로 보존 — 한 국가만 실패해도 다른 국가 유지)
                "economicIndicators.kr",
                "economicIndicators.us",
                "economicIndicators.eu",
                "economicIndicators.jp",
                "economicIndicators.cn",
                "economicIndicators.uk",
                "economicIndicators.de",
            ],
            fresh_label="이전 빌드 보존",
        )
        if preserved:
            log(f"[preserve] 총 {preserved}개 필드를 직전 빌드 값으로 복원")
            data.setdefault("diagnostics", {})["preservedFields"] = preserved
    except Exception as e:
        log(f"[preserve] 머지 오류 (무시): {e}")

    # ── leaf 단위 지표 보강 (컨테이너 단위 보존의 사각지대 메우기) ──────
    # FRED 일시 실패로 economicIndicators.us 가 {dxy_idx} 처럼 '일부만 남으면'
    # 위 _preserve_from_prev 는 '비어있지 않음'으로 보고 건너뛴다 → VIX 등 손실.
    # 여기서 누락된 개별 지표만 직전 빌드 값으로 채워 전수 손실을 방지한다.
    try:
        deep = _preserve_indicators_deep(
            data, prev,
            container_keys=["economicIndicators", "realestate", "sentiment", "yieldCurve"],
        )
        if deep:
            log(f"[preserve-deep] 총 {deep}개 지표(leaf)를 직전 빌드 값으로 보강")
            dg = data.setdefault("diagnostics", {})
            dg["preservedMetricsDeep"] = deep
    except Exception as e:
        log(f"[preserve-deep] 머지 오류 (무시): {e}")

    # ── 차트 끝점 ↔ 실시간 spot 동기화 (소스 불일치 보정) ──────────
    # 모든 카드/상세 모달 차트가 data.history 를 공유하므로 한 번의 보정으로
    # 헤더 숫자와 차트 끝점 불일치(예: KOSPI 차트가 며칠 전에서 멈추는 문제)를 일괄 해결.
    try:
        _reconcile_history_with_spot(data, now)
    except Exception as e:
        log(f"[reconcile] 오류 (무시): {e}")

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


def fetch_bing_news_articles(query, count=5, timeout=10):
    """Bing News RSS — Google News 차단 시 대체 소스.

    Bing News RSS 는 한국어 쿼리도 지원하며 GHA 러너에서 차단 사례가 거의 없음.
    URL 형식이 publisher 직접 링크 (redirect 없음) 라 _is_publisher_home 검증 통과율 ↑.
    """
    rss_url = (
        f"https://www.bing.com/news/search?q={quote_plus(query)}"
        f"&format=rss&setmkt=ko-KR&setlang=ko"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml,application/xml,text/xml,*/*",
    }
    candidates = [
        rss_url,
        f"https://corsproxy.io/?{quote_plus(rss_url)}",
        f"https://api.allorigins.win/raw?url={quote_plus(rss_url)}",
    ]
    xml_text = None
    for url in candidates:
        try:
            r = requests.get(url, timeout=timeout, headers=headers)
            if r.status_code == 200 and r.text and len(r.text) > 100:
                xml_text = r.text
                break
        except Exception:
            continue
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except Exception:
        return []
    out = []
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        title = (title_el.text or "").strip() if title_el is not None else ""
        url = (link_el.text or "").strip() if link_el is not None else ""
        pub_date = (pub_el.text or "").strip() if pub_el is not None else ""
        iso_date = None
        if pub_date:
            try:
                from email.utils import parsedate_to_datetime
                iso_date = parsedate_to_datetime(pub_date).strftime("%Y-%m-%d")
            except Exception:
                iso_date = None
        # Bing 의 URL 은 종종 https://www.bing.com/news/apiclick.aspx?...&url=<encoded> 형태
        # 실제 기사 URL 추출
        m_url = re.search(r"[?&]url=(https?[^&]+)", url)
        if m_url:
            try:
                from urllib.parse import unquote
                url = unquote(m_url.group(1))
            except Exception:
                pass
        if title and url and "bing.com" not in url:
            out.append({"title": title, "url": url, "isoDate": iso_date or "", "pubDate": pub_date})
        if len(out) >= count:
            break
    if out:
        log(f"[BingNews] '{query}' {len(out)}건 수집 (1위: {out[0]['title'][:30]}…)")
    return out


def fetch_news_all_feeds():
    """모든 카테고리 별로 최대 5건씩 페치하여 카테고리→[articles] 매핑 반환.

    페치 순서 (publisher 홈페이지가 아닌 실제 기사 URL 우선):
      1) Naver Search API (originallink = publisher 직접 기사 URL, NAVER_CLIENT_ID/SECRET 있을 때)
      2) Google News RSS (직접 + CORS 프록시 폴백, URL 검증 통과한 것만)
      3) Bing News RSS (Google 차단 케이스 보강 — publisher 직접 링크)
      4) 결과 합쳐 최대 5건 (publisher 홈페이지 URL 은 제외, 중복 url 제거)

    실패한 카테고리는 빈 리스트로 채우고, 나머지는 전부 시도.
    """
    result = {"lastFetched": datetime.now(KST).isoformat()}
    naver_available = bool(NAVER_CLIENT_ID and NAVER_CLIENT_SECRET)
    if naver_available:
        log("[News] 네이버 검색 OpenAPI 활성 (PRIMARY)")
    else:
        log("[News] NAVER_CLIENT_ID/SECRET 미설정 — Google News RSS 만 사용 (publisher 홈페이지 URL 회귀 위험 ↑)")

    # 사용자 요구: 최근 15일 이내 기사만 표시. iso 날짜가 오늘-15일 보다 오래된 기사 제외.
    now_kst = datetime.now(KST)
    cutoff_iso = (now_kst - timedelta(days=15)).strftime("%Y-%m-%d")
    today_iso  = now_kst.strftime("%Y-%m-%d")
    log(f"[News] 15일 cutoff: {cutoff_iso} ~ {today_iso} 사이 기사만 채택 (미래 발행일 거부)")

    def _is_good_article_url(u):
        """기사 URL 검증 — 빈 값, google news 직링크, publisher 홈페이지/검색결과는 제외."""
        if not u or u == "#":
            return False
        if "news.google.com" in u:
            return False  # 디코드 실패한 raw google URL 은 클릭해도 redirect 안 따라가므로 제외
        # 검색결과 페이지 / 일반 검색 호스트 제외 (사용자가 "신문사 홈페이지" 로 인식)
        SEARCH_HOSTS = ("search.naver.com", "m.search.naver.com",
                        "search.daum.net", "www.bing.com", "google.com")
        try:
            from urllib.parse import urlparse
            host = (urlparse(u).hostname or "").lower()
            if any(host == h or host.endswith("." + h) for h in SEARCH_HOSTS):
                return False
        except Exception:
            pass
        if _is_publisher_home(u):
            return False
        return True

    def _is_recent(article):
        """isoDate 가 15일 이내인지 검사. isoDate 가 없거나 미래/과거 범위 밖이면 거부."""
        iso = (article.get("isoDate") or "").strip()
        # isoDate 없으면 pubDate 에서 재파싱 시도
        if not iso:
            pub = (article.get("pubDate") or "").strip()
            if pub:
                try:
                    from email.utils import parsedate_to_datetime
                    iso = parsedate_to_datetime(pub).strftime("%Y-%m-%d")
                    article["isoDate"] = iso  # 후속 처리를 위해 저장
                except Exception:
                    iso = ""
        if not iso:
            # 사용자 요구: 15일 이내 실제 기사만. 날짜 미상은 거부.
            return False
        # 미래 발행일 (RSS 가 가끔 잘못된 미래 날짜를 주는 케이스) 거부
        if iso > today_iso:
            return False
        return iso >= cutoff_iso

    def _filter_keep(article):
        return _is_good_article_url(article.get("url")) and _is_recent(article)

    for cat, query in NEWS_CATEGORY_QUERIES.items():
        articles = []
        seen_urls = set()
        # 1) Naver Search 우선 — originallink 가 publisher 직접 기사 URL, sort=date 로 최신순
        if naver_available:
            try:
                for na in fetch_naver_search_news(query, count=10):
                    if _filter_keep(na) and na["url"] not in seen_urls:
                        articles.append(na)
                        seen_urls.add(na["url"])
                        if len(articles) >= 5:
                            break
            except Exception as e:
                log(f"[NaverSearch] '{cat}' 예외: {e}")
        # 2) Google News RSS 로 부족분 보강
        if len(articles) < 5:
            try:
                for ga in fetch_news_articles(query, count=15):
                    if _filter_keep(ga) and ga["url"] not in seen_urls:
                        articles.append(ga)
                        seen_urls.add(ga["url"])
                        if len(articles) >= 5:
                            break
            except Exception as e:
                log(f"[News] Google '{cat}' 예외: {e}")
        # 3) Bing News RSS 로 추가 보강 — Google/Naver 모두 실패한 케이스 회복
        if len(articles) < 5:
            try:
                for ba in fetch_bing_news_articles(query, count=10):
                    if _filter_keep(ba) and ba["url"] not in seen_urls:
                        articles.append(ba)
                        seen_urls.add(ba["url"])
                        if len(articles) >= 5:
                            break
            except Exception as e:
                log(f"[BingNews] '{cat}' 예외: {e}")
        # 4) 그래도 부족하면 Naver Search 키워드를 좀 더 일반화해서 재시도
        if len(articles) < 3 and naver_available:
            try:
                for na in fetch_naver_search_news(query.split()[0], count=10):
                    if _filter_keep(na) and na["url"] not in seen_urls:
                        articles.append(na)
                        seen_urls.add(na["url"])
                        if len(articles) >= 5:
                            break
            except Exception:
                pass
        if articles:
            log(f"[News] '{cat}' 최종 {len(articles)}건 (15일 cutoff {cutoff_iso} 적용)")
        else:
            log(f"[News] '{cat}' 15일 이내 기사 0건 — 빈 카테고리")
        result[cat] = articles[:5]
        _time.sleep(0.3)  # rate-limit 회피
    return result


# ============================================================
# 경제 캘린더 (Economic Calendar) — 매일 09:00/22:00 KST 갱신
# ============================================================
# 사용자 요구: 오늘 8시 이후 발표되는 지표를 매일 오전 9시 / 오후 10시에 갱신.
# FRED 의 release dates 와 ECOS 의 발표 시리즈를 활용해 미·한 주요 발표 일정을 가져옴.
# 프론트엔드 calEvents (하드코드) 와 머지될 수 있도록 동일 스키마 사용:
#   {dt: 'MM.DD HH:MM', cc, name, stars, prev, fore, act, beat}

# FRED 주요 release_id → (cc, 한국어 지표명, 중요도, 발표 시각 KST)
# FRED Release IDs: https://api.stlouisfed.org/fred/releases?api_key=...
# ⚠ 데이터 정합성 원칙: 각 release_id 의 '발표일' 만 빌리고 '실제값' 은 아래
# CALENDAR_INDICATOR_MAP 이 가리키는 FRED 시리즈에서 백필한다. 따라서 라벨(지표명)은
# 반드시 그 값의 출처와 일치해야 한다. (과거 결함: 라벨과 값 출처가 어긋나
#  'ISM PMI = 5.4'(실제 OECD BCI), '주택지표(NAR) = 1465'(실제 주택착공) 처럼 표시됨.)
# FRED 에 없거나(ISM·ADP=민간 독점), 우리 데이터셋에 매칭 시리즈가 없는(미시간 심리·주간
# 실업수당) 지표는 잘못된 값을 보여주므로 캘린더에서 제외한다.
FRED_KEY_RELEASES = {
    10:  ("US", "미국 CPI (전월비)",          3, "21:30"),
    11:  ("US", "미국 비농업고용(NFP)",       3, "21:30"),
    13:  ("US", "미국 소매판매",              2, "21:30"),
    14:  ("US", "미국 GDP",                  3, "21:30"),
    15:  ("US", "미국 PCE 물가지수",          3, "21:30"),
    18:  ("US", "미국 PPI",                  2, "21:30"),
    50:  ("US", "미국 산업생산",              2, "22:15"),
    53:  ("US", "미국 주택착공 (Housing Starts)", 2, "21:30"),  # FRED:HOUST (천 호, 연환산)
    151: ("US", "미국 FOMC 회의",            3, "03:00"),
}

# 캘린더 이벤트 → data["economicIndicators"] 경로 매핑.
# 서버측 자동 백필 (auto-backfill calendar actuals) 에서 사용.
# 각 항목: (dotted-path, "fmt" 함수, lower_is_positive?)
# - fmt: "pct1" = "%.1f%%", "pct2" = "%.2f%%", "raw1" = "%.1f", "k" = "%dK"
# - lower_is_positive: True 면 act < fore 가 긍정 (CPI/실업률), False/None 이면 act > fore
CALENDAR_INDICATOR_MAP = {
    # 한국 — 대부분 발표 형식이 % 변화율 (전월비/전년비)
    "한국은행 금통위 회의":   ("economicIndicators.kr.base_rate_kr", "pct2", False),
    "한국 소비자물가지수(CPI)": ("economicIndicators.kr.cpi_kr", "yoy1", True),  # 전년비
    "한국 5월 소비자물가(CPI)": ("economicIndicators.kr.cpi_kr", "yoy1", True),
    "한국 1분기 GDP (확정)":  ("economicIndicators.kr.gdp_kr", "mom1", False),
    "한국 수출입 동향":       ("economicIndicators.kr.exports_kr", "yoy1", False),
    "한국 5월 수출입 동향":   ("economicIndicators.kr.exports_kr", "yoy1", False),
    "한국 산업생산지수":      ("economicIndicators.kr.ip_kr", "mom1", False),
    "한국 제조업 PMI":        ("economicIndicators.kr.pmi_kr", "raw1", False),
    # 미국 — CPI/PPI/소매/산업생산은 전월비 % 발표가 표준
    # ⚠ 각 라벨은 FRED 시리즈와 일치해야 한다(라벨↔값 정합성). ISM(독점)·ADP(독점)·
    #   미시간 심리·주간 실업수당 청구는 매칭 시리즈가 없어 제거했다(잘못된 값 표시 방지).
    "미국 CPI (전월비)":      ("economicIndicators.us.cpi_us", "mom1", True),
    "미국 CPI (전년비)":      ("economicIndicators.us.cpi_us", "yoy1", True),
    "미국 PCE 물가지수":      ("economicIndicators.us.pce_us", "mom1", True),
    "미국 실업률":            ("economicIndicators.us.unemployment", "raw1", True),  # 실업률은 %p 그 자체
    "미국 FOMC 회의":         ("economicIndicators.us.ff_rate", "pct2", False),
    # GDP 는 명목 수준의 전기비%가 아니라 BEA 실질 성장률(전기비 연율) 시리즈를 그대로 표시.
    "미국 1분기 GDP (2차)":   ("economicIndicators.us.gdp_growth_us", "pct1", False),
    "미국 GDP":               ("economicIndicators.us.gdp_growth_us", "pct1", False),
    # NFP 는 PAYEMS '수준' 이 아니라 '전월 대비 증감(천명)' 이 발표 헤드라인 — kd(delta) 사용.
    "미국 비농업고용(NFP)":   ("economicIndicators.us.nfp_us", "kd", False),
    "미국 PPI":               ("economicIndicators.us.ppi_us", "mom1", True),
    "미국 소매판매":          ("economicIndicators.us.retail_us", "mom1", False),
    "미국 산업생산":          ("economicIndicators.us.ip_us", "mom1", False),
    # 주택착공(HOUST) — 천 호(연환산). 과거 '주택지표(NAR)' 오라벨 수정.
    "미국 주택착공 (Housing Starts)": ("realestate.us.housing_starts", "raw1", False),
    # 유로존
    "유로존 CPI (전년비)":    ("economicIndicators.eu.cpi_eu", "yoy1", True),
    "ECB 통화정책회의":       ("economicIndicators.eu.base_rate_eu", "pct2", False),
    "유로존 제조업 PMI":      ("economicIndicators.eu.pmi_eu", "raw1", False),
    # 일본
    "일본 GDP (전기비)":      ("economicIndicators.jp.gdp_jp", "mom1", False),
    "일본 BOJ 금리결정":      ("economicIndicators.jp.base_rate_jp", "pct2", False),
    "일본 제조업 PMI":        ("economicIndicators.jp.pmi_jp", "raw1", False),
    # 중국
    "중국 CPI (전년비)":      ("economicIndicators.cn.cpi_cn", "yoy1", True),
    "중국 제조업 PMI":        ("economicIndicators.cn.pmi_cn", "raw1", False),
    # 영국
    "영국 BOE 금리결정":      ("economicIndicators.uk.base_rate_uk", "pct2", False),
    "영국 CPI (전년비)":      ("economicIndicators.uk.cpi_uk", "yoy1", True),
    "영국 제조업 PMI":        ("economicIndicators.uk.pmi_uk", "raw1", False),
    # 독일
    "독일 CPI":               ("economicIndicators.de.cpi_de", "yoy1", True),
    "독일 제조업 PMI":        ("economicIndicators.de.pmi_de", "raw1", False),
}


def _fmt_indicator(val, fmt):
    """캘린더용 값 포맷터.

    fmt 코드:
      pct1: "+2.5%" / "-1.3%"   (signed, 1 decimal)
      pct2: "3.50%"             (rate, 2 decimal)
      raw1: "49.7"              (1 decimal, no unit)
      raw2: "120.50"            (2 decimal, no unit)
      k:    "177K"              (thousands)
      mom1: "+0.2%"             (MoM % 변화율, signed, 1 decimal — pre-computed)
      yoy1: "+2.4%"             (YoY % 변화율, signed, 1 decimal — pre-computed)
    """
    if val is None:
        return ""
    try:
        if fmt in ("pct1", "mom1", "yoy1"):
            sign = "+" if val >= 0 else ""
            return f"{sign}{val:.1f}%"
        if fmt == "pct2":
            return f"{val:.2f}%"
        if fmt == "raw1":
            return f"{val:.1f}"
        if fmt == "raw2":
            return f"{val:.2f}"
        if fmt == "k":
            return f"{int(round(val))}K"
        if fmt == "kd":  # 전월 대비 증감(천명), signed — 예: "+158K" (NFP 헤드라인)
            sign = "+" if val >= 0 else ""
            return f"{sign}{int(round(val))}K"
        return f"{val}"
    except (ValueError, TypeError):
        return ""


def _compute_change(history, key, mode="mom"):
    """history 에서 key 시점의 전월비/전년비 %변화율 계산.

    mode='mom': 직전 키 대비 % 변화 (월간 시리즈에서 직전 월)
    mode='yoy': 12개월 전 키 대비 % 변화

    Returns: float (예: 0.2 = +0.2%) 또는 None.
    """
    if not history or not key:
        return None
    keys_sorted = sorted(history.keys())
    try:
        idx = keys_sorted.index(key)
    except ValueError:
        return None
    cur = history.get(key)
    if cur is None or cur == 0:
        return None
    if mode == "mom":
        if idx == 0:
            return None
        prev_key = keys_sorted[idx - 1]
    else:  # yoy
        if idx < 12:
            return None
        prev_key = keys_sorted[idx - 12]
    prev_val = history.get(prev_key)
    if prev_val is None or prev_val == 0:
        return None
    return round((cur - prev_val) / prev_val * 100, 2)


def _get_by_path(obj, path):
    """dotted path 로 중첩 dict 접근."""
    if not obj: return None
    cur = obj
    for k in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return None
        if cur is None:
            return None
    return cur


def backfill_calendar_actuals(events, data):
    """서버측 캘린더 백필 — 과거 발표 이벤트의 prev/fore/act 자동 채움.

    각 이벤트 (iso 날짜) 에 대해 CALENDAR_INDICATOR_MAP 으로 지표 노드를 찾고,
    history 에서 발표일 ≤ ISO 인 가장 최근 값을 act, 그 직전을 prev 로 채움.
    fmt_id 가 'mom1'/'yoy1' 이면 history 에서 직접 변화율을 계산해 채움
    (인덱스 레벨이 아닌 발표 형식과 일치하도록 — 예: CPI 332.4 → 전월비 +0.2%).
    """
    if not events or not data:
        return 0
    today_iso = datetime.now(KST).strftime("%Y-%m-%d")
    filled = 0
    for ev in events:
        try:
            if ev.get("act"):
                continue
            iso = ev.get("iso", "")
            if not iso:
                continue
            if iso > today_iso:
                continue  # 미래 이벤트는 그대로
            name = ev.get("name", "")
            mp = CALENDAR_INDICATOR_MAP.get(name)
            if not mp:
                continue
            path, fmt_id, _lower_pos = mp
            node = _get_by_path(data, path)
            if not node or not isinstance(node, dict):
                continue
            history = node.get("history") or {}
            if not history:
                v = node.get("value")
                if v is not None:
                    ev["act"] = _fmt_indicator(v, fmt_id)
                    filled += 1
                continue
            # history 키 정렬 후 발표일 이전(이하) 의 최근 키 = act, 그 전 = prev
            keys_sorted = sorted(history.keys())
            iso_yyyy_mm = iso[:7]
            recent_keys = [k for k in keys_sorted
                           if k <= iso or k <= iso_yyyy_mm or k.replace("-","") <= iso.replace("-","")]
            if not recent_keys:
                continue
            act_key = recent_keys[-1]
            prev_key = recent_keys[-2] if len(recent_keys) >= 2 else None

            # mom1/yoy1: 인덱스 레벨이 아닌 변화율 계산
            if fmt_id in ("mom1", "yoy1"):
                mode = "mom" if fmt_id == "mom1" else "yoy"
                act_chg = _compute_change(history, act_key, mode)
                prev_chg = _compute_change(history, prev_key, mode) if prev_key else None
                if act_chg is None:
                    continue
                ev["act"] = _fmt_indicator(act_chg, fmt_id)
                if not ev.get("prev") and prev_chg is not None:
                    ev["prev"] = _fmt_indicator(prev_chg, fmt_id)
                if not ev.get("fore") and prev_chg is not None:
                    ev["fore"] = _fmt_indicator(prev_chg, fmt_id)
                # beat 계산
                try:
                    fore_num = _parse_num(str(ev.get("fore", "")).replace("%", "").replace("+", ""))
                    if fore_num is not None:
                        if abs(act_chg - fore_num) < 0.05:
                            ev["beat"] = 0
                        elif any(x in name for x in ("CPI", "PPI", "물가", "실업", "미분양")):
                            ev["beat"] = 1 if act_chg < fore_num else -1
                        else:
                            ev["beat"] = 1 if act_chg > fore_num else -1
                except (ValueError, TypeError):
                    pass
                filled += 1
                continue

            # kd: '수준' 의 전월 대비 증감(천명) — NFP 헤드라인(PAYEMS 레벨이 아닌 증감)
            if fmt_id == "kd":
                prev_prev_key = recent_keys[-3] if len(recent_keys) >= 3 else None
                a, p = history.get(act_key), history.get(prev_key)
                if a is None or p is None:
                    continue
                act_delta = a - p
                ev["act"] = _fmt_indicator(act_delta, "kd")
                if prev_prev_key is not None:
                    pp = history.get(prev_prev_key)
                    if pp is not None:
                        prev_delta = p - pp
                        if not ev.get("prev"):
                            ev["prev"] = _fmt_indicator(prev_delta, "kd")
                        if not ev.get("fore"):
                            ev["fore"] = _fmt_indicator(prev_delta, "kd")
                try:
                    fore_num = _parse_num(str(ev.get("fore", "")).replace("+", "").replace("K", ""))
                    if fore_num is not None:
                        ev["beat"] = 0 if abs(act_delta - fore_num) < 5 else (1 if act_delta > fore_num else -1)
                except (ValueError, TypeError):
                    pass
                filled += 1
                continue

            # 그 외 (pct2, raw1, raw2, k): 인덱스 레벨을 그대로 표시
            act_v = history.get(act_key)
            prev_v = history.get(prev_key) if prev_key else None
            if act_v is not None:
                ev["act"] = _fmt_indicator(act_v, fmt_id)
                if not ev.get("prev") and prev_v is not None:
                    ev["prev"] = _fmt_indicator(prev_v, fmt_id)
                if not ev.get("fore") and prev_v is not None:
                    ev["fore"] = _fmt_indicator(prev_v, fmt_id)
                try:
                    fore_num = _parse_num(str(ev.get("fore", "")).replace("%", "").replace("+", "").replace("K", ""))
                    act_num  = float(act_v)
                    if fore_num is not None:
                        if abs(act_num - fore_num) < 0.05:
                            ev["beat"] = 0
                        elif any(x in name for x in ("CPI", "PPI", "물가", "실업", "미분양")):
                            ev["beat"] = 1 if act_num < fore_num else -1
                        else:
                            ev["beat"] = 1 if act_num > fore_num else -1
                except (ValueError, TypeError):
                    pass
                filled += 1
        except Exception as e:
            log(f"[Cal-Backfill] {ev.get('name','?')} 오류: {e}")
            continue
    if filled:
        log(f"[Cal-Backfill] {filled}/{len(events)}개 이벤트 prev/act 자동 채움 완료")
    return filled


def fetch_fred_release_dates(release_id, days_back=7, days_forward=30):
    """FRED Release Dates API — 특정 release_id 의 최근/예정 발표일 조회.

    Returns: [{"release_id": int, "date": "YYYY-MM-DD"}, ...]

    중요: include_release_dates_with_no_data 는 반드시 false. true 면
    실제 발표가 없는 날짜(매일/매주 기본 schedule)까지 모두 반환되어
    캘린더에 "매일 PPI 발표" 같은 가짜 이벤트가 무더기로 생성됨.
    """
    if not FRED_API_KEY:
        return None
    try:
        now = datetime.now(KST)
        start = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
        end = (now + timedelta(days=days_forward)).strftime("%Y-%m-%d")
        r = requests.get(
            f"{FRED_BASE}/release/dates",
            params={
                "release_id": release_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "realtime_start": start,
                "realtime_end": end,
                # 실제 데이터가 있는 발표일만 반환 (매일 PPI 같은 가짜 이벤트 방지)
                "include_release_dates_with_no_data": "false",
                "sort_order": "asc",
                "limit": 50,
            },
            timeout=15,
        )
        if r.status_code != 200:
            return None
        dates = r.json().get("release_dates", []) or []
        # 추가 안전장치: 동일 (YYYY-MM, release_id) 키 기준으로 첫번째만 유지
        # 일부 release 는 같은 달 안에 preliminary + revision 으로 2~3건 반환됨 → 첫 발표만.
        # 단, FOMC(151) 처럼 월 2회 이상 발표가 정상인 release 는 release_id 별 정책 적용.
        MULTI_PER_MONTH_OK = {151, 23}  # FOMC, 신규실업수당청구(주간)
        if int(release_id) in MULTI_PER_MONTH_OK:
            return dates
        seen_months = set()
        deduped = []
        for d in dates:
            ds = d.get("date", "")
            if not ds or len(ds) < 7:
                continue
            ym = ds[:7]  # YYYY-MM
            if ym in seen_months:
                continue
            seen_months.add(ym)
            deduped.append(d)
        return deduped
    except Exception as e:
        log(f"[FRED-Cal] release_id={release_id} 오류: {e}")
        return None


def fetch_economic_calendar():
    """경제 캘린더 — FRED 의 release dates 로부터 향후/최근 발표일 수집.

    매일 09:00/22:00 KST 에 갱신되어 프론트엔드 calEvents 와 머지됨.
    Returns: {"events": [{dt, cc, name, stars, ...}], "lastFetched": iso}
    """
    events = []
    if not FRED_API_KEY:
        log("[Calendar] FRED_API_KEY 없음 — 경제 캘린더 수집 건너뜀")
        return {"events": [], "lastFetched": datetime.now(KST).isoformat(),
                "source": "none (FRED_API_KEY 필요)"}
    log("[Calendar] FRED release dates 수집 시작")
    # 다층 중복 제거:
    #   1차 dt+name: 동일 표시일·이름 중복 방지 (당연 사항).
    #   2차 (cc, name, YYYY-MM): 동일 지표가 같은 달 안에 여러 일자로 들어오는 케이스 제거
    #        — FRED API 가 release_dates_with_no_data=false 무시하고 schedule date 반환하는
    #          극단 케이스에 대응. 단 FOMC/주간실업수당 같이 월 다회 발표 정상인 ID 제외.
    seen = set()
    seen_name_month = set()
    MULTI_PER_MONTH_NAMES = {"미국 FOMC 회의", "미국 신규 실업수당청구"}
    for rid, (cc, name, stars, time_kst) in FRED_KEY_RELEASES.items():
        dates = fetch_fred_release_dates(rid, days_back=14, days_forward=45)
        if not dates:
            continue
        # release_id 단위 month dedup 도 한 번 더 적용 (API 응답 신뢰도 보강)
        multi_ok = (name in MULTI_PER_MONTH_NAMES)
        for d in dates:
            try:
                date_str = d.get("date", "")
                if not date_str:
                    continue
                dt_iso = datetime.strptime(date_str, "%Y-%m-%d")
                # 'MM.DD HH:MM' 형식으로 변환
                dt_disp = f"{dt_iso.month:02d}.{dt_iso.day:02d} {time_kst}"
                key = (dt_disp, name)
                if key in seen:
                    continue
                nm_key = (cc, name, date_str[:7])  # YYYY-MM
                if not multi_ok and nm_key in seen_name_month:
                    continue
                seen.add(key)
                seen_name_month.add(nm_key)
                events.append({
                    "dt": dt_disp,
                    "cc": cc,
                    "name": name,
                    "stars": stars,
                    "prev": "", "fore": "", "act": "", "beat": None,
                    "source": f"FRED:release_id={rid}",
                    "iso": date_str,
                })
            except Exception:
                continue
    events.sort(key=lambda e: e.get("iso", ""))
    log(f"[Calendar] FRED release 수집 완료: {len(events)}건 (dedup 적용)")
    return {
        "events": events,
        "lastFetched": datetime.now(KST).isoformat(),
        "source": "FRED release dates API",
    }


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
