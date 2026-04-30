"""
매일 오전 8시 KST에 실행되어 금융 시장 데이터를 수집하고 data.json을 업데이트합니다.

데이터 소스:
- open.er-api.com : 환율 (USD/KRW, EUR, JPY 등)
- Yahoo Finance   : 주가 지수, 원자재 선물
"""

import json
import sys
import requests
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

FALLBACK = {
    "fx": {
        "USDKRW": {"rate": 1341.50, "change": 0.08},
        "EURKRW": {"rate": 1482.30, "change": -0.15},
        "JPYKRW": {"rate": 8.9120,  "change": 0.22},
        "EURUSD": {"rate": 1.1060,  "change": -0.27},
        "USDJPY": {"rate": 150.32,  "change": -0.12},
    },
    "indices": {
        "KOSPI":    {"price": 2587.23, "change": 0.34},
        "KOSDAQ":   {"price": 742.15,  "change": -0.12},
        "SP500":    {"price": 5635.01, "change": 0.21},
        "NASDAQ":   {"price": 17841.20,"change": 0.18},
        "Nikkei":   {"price": 38405.10,"change": 0.45},
        "Shanghai": {"price": 3298.40, "change": -0.33},
    },
    "commodities": {
        "Gold":   {"price": 2387.60, "change": 0.30},
        "Silver": {"price": 28.42,   "change": 0.55},
        "Copper": {"price": 4.12,    "change": -0.82},
        "WTI":    {"price": 78.42,   "change": -0.55},
        "Brent":  {"price": 82.17,   "change": -0.48},
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def log(msg):
    print(msg, file=sys.stderr)


def fetch_fx_spot():
    """ExchangeRate-API에서 현재 환율 조회 (무료, 인증 불필요)."""
    try:
        r = requests.get(
            "https://open.er-api.com/v6/latest/USD",
            timeout=15,
        )
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


def fetch_yahoo(symbol):
    """Yahoo Finance에서 종목 시세 조회."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?interval=1d&range=5d"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        meta = r.json()["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        prev = meta.get("previousClose") or meta.get("chartPreviousClose")
        if price and prev:
            change_pct = round((price - prev) / prev * 100, 2)
            return {"price": round(price, 2), "change": change_pct}
    except Exception as e:
        log(f"[Yahoo] {symbol} 오류: {e}")
    return None


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
        data["sources"]["fx"] = "open.er-api.com"
        data["fx"] = {k: {"rate": v, "change": 0.0} for k, v in spot.items()}
        # Yahoo에서 변동률 보강
        for pair, sym in [("USDKRW", "USDKRW=X"), ("EURUSD", "EURUSD=X"), ("USDJPY", "USDJPY=X")]:
            q = fetch_yahoo(sym)
            if q:
                data["fx"][pair]["change"] = q["change"]
                data["fx"][pair]["rate"]   = q["price"]
        # EURKRW, JPYKRW 변동률: 기준통화 변동률로 근사
        if "EURUSD" in data["fx"] and "USDKRW" in data["fx"]:
            data["fx"]["EURKRW"]["change"] = round(
                data["fx"]["EURUSD"]["change"] + data["fx"]["USDKRW"]["change"], 2
            )
        if "USDJPY" in data["fx"] and "USDKRW" in data["fx"]:
            data["fx"]["JPYKRW"]["change"] = round(
                data["fx"]["USDKRW"]["change"] - data["fx"]["USDJPY"]["change"], 2
            )
    else:
        data["sources"]["fx"] = "fallback"
        data["fx"] = {k: dict(v) for k, v in FALLBACK["fx"].items()}
    log(f"[FX] {data['sources']['fx']}: USDKRW={data['fx'].get('USDKRW')}")

    # ── 주가 지수 ────────────────────────────────────────────
    index_map = {
        "KOSPI":    "^KS11",
        "KOSDAQ":   "^KQ11",
        "SP500":    "^GSPC",
        "NASDAQ":   "^IXIC",
        "Nikkei":   "^N225",
        "Shanghai": "000001.SS",
    }
    data["sources"]["indices"] = "Yahoo Finance"
    for name, sym in index_map.items():
        q = fetch_yahoo(sym)
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
    data["sources"]["commodities"] = "Yahoo Finance"
    for name, sym in commodity_map.items():
        q = fetch_yahoo(sym)
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
