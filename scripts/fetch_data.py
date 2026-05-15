"""
매 시간 실행되어 금융 시장 데이터를 수집하고 data.json을 업데이트합니다.

데이터 소스:
- open.er-api.com : 환율 (USD/KRW, EUR, JPY 등)
- yfinance        : 주가 지수, 원자재 선물 (Yahoo Finance 공식 클라이언트)
"""

import json
import sys
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

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
    """yfinance를 사용해 종목 시세 조회 (공식 클라이언트, 더 안정적)."""
    try:
        ticker = yf.Ticker(symbol)
        # fast_info가 가장 빠르고 최신 값을 반환
        info = ticker.fast_info
        price = getattr(info, 'last_price', None) or getattr(info, 'regular_market_price', None)
        prev  = getattr(info, 'previous_close', None)
        if price is None:
            # 히스토리로 폴백
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
    """yfinance로 환율 변동률 조회."""
    try:
        res = fetch_yf(pair_symbol)
        return res["change"] if res else 0.0
    except Exception:
        return 0.0


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
        # yfinance로 변동률 보강
        for pair, sym in [("USDKRW", "USDKRW=X"), ("EURUSD", "EURUSD=X"), ("USDJPY", "USDJPY=X")]:
            chg = fetch_fx_change(sym)
            data["fx"][pair]["change"] = chg
            log(f"[FX] {pair}: {data['fx'][pair]['rate']} ({chg:+.2f}%)")
        # EURKRW, JPYKRW 변동률 근사
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

    # ── 주가 지수 ────────────────────────────────────────────
    index_map = {
        "KOSPI":    "^KS11",
        "KOSDAQ":   "^KQ11",
        "SP500":    "^GSPC",
        "NASDAQ":   "^IXIC",
        "Nikkei":   "^N225",
        "Shanghai": "000001.SS",
    }
    data["sources"]["indices"] = "yfinance"
    for name, sym in index_map.items():
        q = fetch_yf(sym)
        if q:
            data["indices"][name] = q
            log(f"[Index] {name}: {q['price']} ({q['change']:+.2f}%)")
        else:
            data["indices"][name] = dict(FALLBACK["indices"][name])
            log(f"[Index] {name}: fallback 사용")

    # ── 원자재 ───────────────────────────────────────────────
    commodity_map = {
        "Gold":   "GC=F",
        "Silver": "SI=F",
        "Copper": "HG=F",
        "WTI":    "CL=F",
        "Brent":  "BZ=F",
    }
    data["sources"]["commodities"] = "yfinance"
    for name, sym in commodity_map.items():
        q = fetch_yf(sym)
        if q:
            data["commodities"][name] = q
            log(f"[Commodity] {name}: {q['price']} ({q['change']:+.2f}%)")
        else:
            data["commodities"][name] = dict(FALLBACK["commodities"][name])
            log(f"[Commodity] {name}: fallback 사용")

    return data


if __name__ == "__main__":
    log("=== 시장 데이터 수집 시작 ===")
    d = build_data()
    output_path = "data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    log(f"=== 완료: {d['lastUpdated']} → {output_path} ===")
