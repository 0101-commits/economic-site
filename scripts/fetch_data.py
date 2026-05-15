"""
매 시간 실행되어 금융 시장 데이터를 수집하고 data.json을 업데이트합니다.

데이터 소스 우선순위:
- 한국 데이터 (KOSPI, KOSDAQ, 채권지수, 금, 석유) : KRX OpenAPI (공식)
- 해외 지수 (S&P, NASDAQ, 닛케이, 상하이)         : yfinance
- 해외 원자재 (Brent, Silver, Copper)             : yfinance
- 환율 (USD/KRW, EUR, JPY 등)                     : open.er-api.com + yfinance

KRX API 키는 환경변수 KRX_API_KEY 로 주입 (GitHub Secret).
"""

import json
import os
import sys
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
KRX_API_KEY = os.environ.get("KRX_API_KEY", "").strip()
KRX_BASE = "http://data-dbg.krx.co.kr/svc/apis"

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
    """KRX 응답은 콤마 포함 문자열 → float 변환."""
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
    """KRX OpenAPI 단일 호출. 최신 영업일 데이터를 OutBlock 리스트로 반환."""
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
        # KRX는 OutBlock_1 또는 OutBlock 키로 응답
        rows = data.get("OutBlock_1") or data.get("OutBlock") or []
        return rows if rows else None
    except Exception as e:
        log(f"[KRX] {endpoint} 오류: {e}")
        return None


def fetch_krx_latest(endpoint, max_lookback=7):
    """최근 영업일을 거꾸로 탐색해 첫 번째로 데이터가 있는 날 반환."""
    for offset in range(0, max_lookback):
        dt = datetime.now(KST) - timedelta(days=offset)
        if dt.weekday() >= 5:  # 토·일 스킵
            continue
        rows = fetch_krx(endpoint, dt.strftime("%Y%m%d"))
        if rows:
            return rows, dt.strftime("%Y-%m-%d")
    return None, None


def krx_index(endpoint, name_match):
    """KRX 지수 일별시세에서 특정 지수명만 추출."""
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
    """KRX 금시장·석유시장에서 대표 종목 추출."""
    rows, basd = fetch_krx_latest(endpoint)
    if not rows:
        return None
    # 우선 정확 일치 → 부분 일치 순서로 탐색
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
# 환율 (open.er-api.com + yfinance 보강)
# ============================================================
def fetch_fx_spot():
    """ExchangeRate-API에서 현재 환율 조회 (무료, 인증 불필요)."""
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
    """yfinance를 사용해 종목 시세 조회."""
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
        # KOSPI 시리즈 (대표: "코스피")
        kospi = krx_index("/idx/kospi_dd_trd", "코스피")
        if kospi:
            data["indices"]["KOSPI"] = {"price": kospi["price"], "change": kospi["change"]}
            log(f"[KRX] KOSPI: {kospi['price']} ({kospi['change']:+.2f}%) [as of {kospi['as_of']}]")
        # KOSDAQ 시리즈 (대표: "코스닥")
        kosdaq = krx_index("/idx/kosdaq_dd_trd", "코스닥")
        if kosdaq:
            data["indices"]["KOSDAQ"] = {"price": kosdaq["price"], "change": kosdaq["change"]}
            log(f"[KRX] KOSDAQ: {kosdaq['price']} ({kosdaq['change']:+.2f}%) [as of {kosdaq['as_of']}]")

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
        # 금 (KRX 금시장 1g 종가)
        gold = krx_commodity("/gen/gold_bydd_trd", "금 99.99_1Kg")
        if not gold:
            gold = krx_commodity("/gen/gold_bydd_trd", "금")
        if gold:
            # KRX 금은 원/g 단위 → 사용자 표시는 oz 변환 안 함 (그대로 노출도 무방하나,
            # 기존 USD/oz 형식과 호환을 위해 KRX 값은 별도 키로 보관)
            data["commodities"]["GoldKRW"] = {
                "price": gold["price"], "change": gold["change"]
            }
            log(f"[KRX] Gold(KRW/g): {gold['price']} ({gold['change']:+.2f}%)")
        # 석유 (휘발유 또는 경유 평균가) — 보통 "휘발유" 행
        oil = krx_commodity("/gen/oil_bydd_trd", "휘발유")
        if oil:
            data["commodities"]["OilKR"] = {
                "price": oil["price"], "change": oil["change"]
            }
            log(f"[KRX] 휘발유(원/L): {oil['price']} ({oil['change']:+.2f}%)")

    # 국제 원자재는 yfinance
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

    return data


if __name__ == "__main__":
    log("=== 시장 데이터 수집 시작 ===")
    if KRX_API_KEY:
        log(f"[KRX] API 키 설정됨 ({KRX_API_KEY[:6]}...{KRX_API_KEY[-4:]})")
    else:
        log("[KRX] API 키 없음 — yfinance 전용 모드")
    d = build_data()
    output_path = "data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    log(f"=== 완료: {d['lastUpdated']} → {output_path} ===")
