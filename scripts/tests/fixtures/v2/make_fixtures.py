"""알림 v2 시장 판정(judges_market) 검사용 고정 데이터 생성기 — 이 폴더에 JSON 을 쓴다.

    python scripts/tests/fixtures/v2/make_fixtures.py

기준 시각 2026-10-05(월) 10:30 KST, 직전 거래일 10/2(금). 결정적(난수 없음). 값마다 어떤 장면인지 주석에 적었다 —
검사(test_v2_judges_market.py)는 이 장면을 「걸림」으로 읽고, 한 칸씩 바꿔 「안 걸림」을 만든다.
"""
import datetime as dt
import json
import os

OUT = os.path.dirname(os.path.abspath(__file__))
END = dt.date(2026, 10, 2)          # 직전 거래일(금)


def bdays(n, end=END):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= dt.timedelta(days=1)
    return out[::-1]


def cdays(n, end):
    return [(end - dt.timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


def alt_series(dates, last, pct):
    """끝 값이 last 이고 일간 수익률이 +pct/−pct 로 번갈아 가는 일봉 — σ ≈ pct."""
    closes = [last]
    for i in range(len(dates) - 1):
        closes.append(closes[-1] / (1 + (pct if i % 2 == 0 else -pct) / 100))
    return [{"date": d, "close": round(c, 4)} for d, c in zip(dates, closes[::-1])]


N = 90
D = bdays(N)
kospi = alt_series(D, 6050.0, 1.0)        # σ 1% · 오늘 −4% → A1 경보(z −4) · B2 6000 하향 · B1 52주 최저
kosdaq = alt_series(D, 900.0, 3.0)        # σ 3% · 오늘 −5.5% → 2.5σ=7.5% 지만 상한 5% 로 걸림(z −1.8, 경보 아님)
sp500 = alt_series(D, 7700.0, 0.1)        # σ 0.1% · 오늘 +0.4% → 2.5σ=0.25% 지만 하한 0.5% 로 안 걸림(z +4)
usdkrw = alt_series(D, 1340.0, 0.5)       # 오늘 +0.2% → 안 걸림
gold = alt_series(D, 4100.0, 1.0)
gold[-31]["close"] = 4200.0               # 52주 최고 4200(약 6주 전) · 어제 4100 → 오늘 4250 = 첫날 신고가 · 4250 마디
btc_dates = cdays(N, dt.date(2026, 10, 5))
btc = alt_series(btc_dates, 79000.0, 2.0)
btc[-1]["close"] = round(btc[-2]["close"] * 1.09, 4)   # 일봉 끝 +9% → A4(임계 min(max(2.5×2, 0.5), 8)=5%)

vix_hist = {d: 20.0 + (i % 5) for i, d in enumerate(D[:-1])}
vix_hist[D[-1]] = 26.0                    # 24 → 26: 25 단계 상향 돌파
vkospi_hist = {d: 22.0 + (i % 3) for i, d in enumerate(D)}           # 90점 = min_history 경계
vkospi_hist[D[-2]] = 20.0                 # 어제 20(실현 15.9% 의 1.26배) → 오늘 30(1.89배) = 1.5배 진입
vkospi_hist[D[-1]] = 30.0
t10_hist = {d: 0.3 for d in D[:-2]}
t10_hist[D[-2]] = 0.05
t10_hist[D[-1]] = -0.03                   # +0.05 → −0.03 = 역전
fg_hist = {d: 45.0 for d in D[:-1]}
fg_hist[D[-1]] = 22.0                     # 28 → 22 = 극단 공포 진입


def curve(tenor, last2):
    data = [{"date": d, "value": 4.0} for d in D[:-2]]
    data += [{"date": D[-2], "value": last2[0]}, {"date": D[-1], "value": last2[1]}]
    return {"tenor": tenor, "label": tenor, "data": data}


data = {
    "lastUpdated": "2026-10-05T10:25:00+09:00",
    "indices": {"KOSPI": {"price": 5808.0, "change": -4.0}, "KOSDAQ": {"price": 850.5, "change": -5.5},
                "SP500": {"price": 7730.8, "change": 0.4}},
    "fx": {"USDKRW": {"rate": 1342.68, "change": 0.2}},
    "commodities": {"Gold": {"price": 4250.0, "change": 3.66},
                    "GoldKRW": {"price": 199000.0, "change": 0.5, "as_of": "2026-10-02"}},
    "history": {"indices": {"KOSPI": kospi, "KOSDAQ": kosdaq, "SP500": sp500}, "fx": {"USDKRW": usdkrw},
                "commodities": {"Gold": gold}, "crypto": {"BTC": btc}},
    "sentiment": {
        "vkospi": {"value": 30.0, "change": 50.0, "as_of": D[-1], "history": vkospi_hist},
        "move": {"value": 99.0, "change": -1.0, "as_of": D[-1], "history": {D[-2]: 100.0, D[-1]: 99.0}},
        "fear_greed": {"value": 22.0, "prev": 28.0, "as_of": D[-1], "history": fg_hist},
    },
    "economicIndicators": {"us": {"vix": {"value": 26.0, "period": D[-1], "history": vix_hist},
                                  "t10y2y_us": {"value": -0.03, "period": D[-1], "history": t10_hist}}},
    # 금리: 미 10년 +2bp(안 걸림) · 한 10년 +12bp(걸림) · 일 30년 +3bp. current 는 실데이터처럼 값만 든 목록
    "yieldCurve": {"us": {"current": [None] * 7 + [5.06], "series": [curve("10Y", [5.04, 5.06])]},
                   "kr": {"current": [None] * 7 + [4.42], "series": [curve("10Y", [4.30, 4.42])]},
                   "jp": {"current": [None] * 9 + [4.13], "series": [curve("30Y", [4.10, 4.13])]}},
    "marketHalts": {"active": [], "history": [], "stale": False},
    "marketCalendarKr": {"today": {"date": "2026-10-05", "open": True}, "previousBusinessDay": {"date": D[-1]}},
}

reg = [
    {"id": "kospi", "label": "KOSPI", "short": "KOSPI", "country": "kr", "dataPath": "indices.KOSPI",
     "seriesPath": "history.indices.KOSPI"},
    {"id": "kosdaq", "label": "KOSDAQ", "short": "KOSDAQ", "country": "kr", "dataPath": "indices.KOSDAQ",
     "seriesPath": "history.indices.KOSDAQ"},
    {"id": "sp500", "label": "S&P 500", "short": "S&P 500", "country": "us", "dataPath": "indices.SP500",
     "seriesPath": "history.indices.SP500"},
    {"id": "usdkrw", "label": "USD/KRW", "short": "USD/KRW", "unit": "원", "dataPath": "fx.USDKRW",
     "seriesPath": "history.fx.USDKRW"},
    {"id": "usdjpy", "label": "USD/JPY", "short": "USD/JPY", "unit": "엔", "dataPath": "fx.USDJPY",
     "seriesPath": "history.fx.USDJPY"},
    {"id": "gold", "label": "금", "short": "금", "unit": "$", "dataPath": "commodities.Gold",
     "seriesPath": "history.commodities.Gold"},
    {"id": "goldkrw", "label": "금(원/g)", "short": "금(원/g)", "unit": "원", "dataPath": "commodities.GoldKRW",
     "seriesPath": "history.commodities.GoldKRW"},
    {"id": "btc", "label": "비트코인", "short": "BTC", "unit": "$", "dataPath": "history.crypto.BTC",
     "seriesPath": "history.crypto.BTC"},
    {"id": "vix", "label": "VIX", "short": "VIX", "unit": "지수 (S&P500 30일 내재변동성)",
     "dataPath": "economicIndicators.us.vix"},
    {"id": "t10y2y_us", "label": "미 장단기 금리차", "short": "10Y-2Y", "unit": "%p",
     "dataPath": "economicIndicators.us.t10y2y_us"},
    {"id": "move", "label": "MOVE", "short": "MOVE", "dataPath": "sentiment.move"},
    {"id": "fear_greed", "label": "공포탐욕지수", "short": "공포탐욕", "dataPath": "sentiment.fear_greed"},
    {"id": "vkospi", "label": "V-KOSPI", "short": "V-KOSPI", "dataPath": "sentiment.vkospi"},
    {"id": "us10y", "label": "미국 국채 10Y", "short": "미 10년", "unit": "%", "dataPath": "yieldCurve.us:10Y"},
    {"id": "us30y", "label": "미국 국채 30Y", "short": "미 30년", "unit": "%", "dataPath": "yieldCurve.us:30Y"},
    {"id": "kr10y", "label": "한국 국채 10Y", "short": "한 10년", "unit": "%", "dataPath": "yieldCurve.kr:10Y"},
    {"id": "pce_us", "label": "미국 PCE", "short": "미 PCE", "dataPath": "economicIndicators.us.pce_us"},
    {"id": "cpi_kr", "label": "한국 CPI", "short": "한국 CPI", "dataPath": "economicIndicators.kr.cpi_kr"},
]

LIVE_AT = "2026-10-05T10:25:00+09:00"
home = {"asOf": LIVE_AT, "strip": [
    {"id": "kospi", "label": "KOSPI", "short": "KOSPI", "value": 5808.0, "change": -242.0, "changePct": -4.0,
     "asOf": LIVE_AT, "state": "live"},
    {"id": "kosdaq", "label": "KOSDAQ", "short": "KOSDAQ", "value": 850.5, "change": -49.5, "changePct": -5.5,
     "asOf": LIVE_AT, "state": "live"},
    {"id": "sp500", "label": "S&P 500", "short": "S&P 500", "value": 7730.8, "change": 30.8, "changePct": 0.4,
     "asOf": LIVE_AT, "state": "live"},
    {"id": "usdkrw", "label": "USD/KRW", "short": "USD/KRW", "unit": "원", "value": 1342.68, "change": 2.68,
     "changePct": 0.2, "asOf": LIVE_AT, "state": "live"},
    {"id": "gold", "label": "금", "short": "금", "unit": "$", "value": 4250.0, "change": 150.0, "changePct": 3.66,
     "asOf": LIVE_AT, "state": "live"},
    {"id": "vkospi", "label": "V-KOSPI", "short": "V-KOSPI", "value": 30.0, "change": 10.0, "changePct": 50.0,
     "asOf": D[-1], "state": "prev"},
    {"id": "gold_premium", "label": "금 김치프리미엄", "short": "금 김프", "unit": "%", "value": 1.4, "change": None,
     "changePct": None, "asOf": D[-1], "state": "prev"},
]}
# 띠에 없고 보기 칸에만 있는 지표(실데이터와 같은 자리)
glob = {"strip": [], "views": {
    "vix": {"id": "vix", "label": "VIX", "short": "VIX", "value": 26.0, "change": 2.0, "changePct": 8.33,
            "asOf": D[-1], "state": "prev"},
    "move": {"id": "move", "label": "MOVE", "short": "MOVE", "value": 99.0, "change": -1.0, "changePct": -1.0,
             "asOf": D[-1], "state": "prev"},
    "fearGreed": {"id": "fear_greed", "label": "공포탐욕지수", "short": "공포탐욕", "value": 22.0, "change": -6.0,
                  "changePct": -21.43, "asOf": D[-1], "state": "prev"},
    "rates": [{"id": "t10y2y_us", "label": "미 장단기 금리차", "short": "10Y-2Y", "unit": "%p", "value": -0.03,
               "change": -0.08, "changePct": None, "asOf": D[-1], "state": "prev"}],
}}

# ---- 메르 렌즈 ----
D60 = bdays(60)                            # 렌즈 이력(실데이터는 1년치, 규칙을 보이는 데는 60점이면 충분)
MONTHS = [f"{y}-{m:02d}-01" for y, m in [(2025, 9), (2025, 10), (2025, 11), (2025, 12)] + [(2026, k) for k in range(1, 10)]]
YYYYMM = [f"{y}{m:02d}" for y, m in [(2025, 9), (2025, 10), (2025, 11), (2025, 12)] + [(2026, k) for k in range(1, 10)]]


def hist(dates, vals):
    return [{"date": d, "value": v} for d, v in zip(dates, vals)]


def th(level, d="up", date="2026-09-15"):
    return {"level": level, "levelText": str(level), "meaning": "m", "quote": "q", "logNo": "1", "date": date,
            "kind": "level", "dir": d}


def ind(iid, path, unit, state, nearest, ths, h):
    cur = {"value": h[-1]["value"], "asOf": h[-1]["date"]}
    return {"id": iid, "label": iid, "layer": "market", "unit": unit, "dataPath": path, "current": cur,
            "history1y": h, "thresholds": ths,
            "nearest": {"level": nearest, "distancePct": (cur["value"] - nearest) / nearest * 100},
            "state": state, "postDates": [], "lastQuotes": []}


us10y_v = [round(4.5 + 0.4 * i / 57, 4) for i in range(58)] + [5.03, 5.06]   # 끝 2점만 5.0 위 = 새 돌파 이틀째(걸림)
us30y_v = [5.2] * 57 + [5.52, 5.55, 5.58]                                       # 3점째 = 이미 알린 돌파
jgb30_v = [3.8] * 10 + [4.05] * 5 + [3.9] * 43 + [4.02, 4.04]                  # 두 달 전에 같은 선을 넘었음
jgb10_v = [round(1.5 + 0.005 * i, 4) for i in range(60)]                        # 창 첫 점부터 1.0 위(1년 넘게)
kospi_v = [7000.0] * 59 + [7450.0]                                              # 1점째 = 지속 미확인
usdjpy_v = [150.0] * 58 + [156.0, 157.5]                                       # 어제 −2.5% → 오늘 −1.56% = 주시 진입

mer = {
    "asOf": "2026-10-05T10:00:00+09:00",
    "indicators": [
        ind("us10y", "yieldCurve.us:10Y", "%", "crossed", 5.0,
            [th(5.0), th(5.5, date="2026-08-18"), th(4.6, date="2026-07-25")], hist(D60, us10y_v)),
        ind("us30y", "yieldCurve.us:30Y", "%", "crossed", 5.5, [th(5.5, date="2026-08-26")], hist(D60, us30y_v)),
        ind("jgb30y", "mer_series.jgb:30Y", "%", "crossed", 4.0, [th(4.0, date="2026-09-14")], hist(D60, jgb30_v)),
        ind("jgb10y", "mer_series.jgb:10Y", "%", "crossed", 1.0, [th(1.0, date="2026-08-05")], hist(D60, jgb10_v)),
        ind("pce_us", "economicIndicators.us.pce_us", "%", "crossed", 2.0, [th(2.0)],
            hist(MONTHS, [round(2.5 + 0.07 * i, 2) for i in range(13)])),
        ind("cpi_kr", "economicIndicators.kr.cpi_kr", "%", "crossed", 2.0, [th(2.0)],
            hist(YYYYMM, [round(2.1 + 0.05 * i, 2) for i in range(13)])),
        ind("kospi", "history.indices.KOSPI", "", "crossed", 7400.0, [th(7400.0)], hist(D60, kospi_v)),
        ind("usdjpy", "history.fx.USDJPY", "엔", "near", 160.0, [th(160.0, date="2026-08-03")], hist(D60, usdjpy_v)),
        ind("vix", "economicIndicators.us.vix", "", "below", 40.0, [th(40.0)], hist(D60, [20.0] * 60)),
    ],
    "chains": [
        {"id": "C1", "label": "재정 눈덩이", "steps": [{"id": "us10y"}, {"id": "fiscal"}, {"id": "us10y"}],
         "hotStep": "us10y", "lastDate": "2026-10-03"},
        {"id": "C6", "label": "엔 스퀴즈", "steps": [{"id": "usdjpy"}, {"id": "jgb30y"}], "hotStep": None,
         "lastDate": "2026-09-19"},
    ],
}

gp_hist = [{"date": d, "value": round(0.5 + 0.02 * i, 2)} for i, d in enumerate(D[-40:])]   # 40점 ≥ 30


def dump(rel, obj):
    p = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


if __name__ == "__main__":
    dump("data.json", data)
    dump("bundles/registry.json", {"count": len(reg), "rows": reg})
    dump("bundles/home.json", home)
    dump("bundles/market-global.json", glob)
    dump("mer_signals.json", mer)
    dump("events/history/gold_premium.json", gp_hist)
    print("ok", OUT)
