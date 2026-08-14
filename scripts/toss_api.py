"""토스증권 Open API 클라이언트 (https://openapi.tossinvest.com).

왜 필요한가
-----------
이 저장소의 한국 시장 데이터는 그동안 pykrx(KRX 로그인 필요) / 네이버 HTML 스크레이핑 /
Yahoo 지연 시세에 의존했다. 셋 다 비공식 경로라 (a) KRX 로그인 실패 시 통째로 죽고,
(b) 네이버가 개편할 때마다 404 가 나고, (c) Yahoo 는 국내 지수·종목이 지연·부정확하다.
토스증권 Open API 는 공식 인증(OAuth2 client_credentials) + 실시간 KRX 시세라
위 세 경로의 상위 소스가 된다.

설계 원칙
---------
* **키 없으면 조용히 비활성** — `enabled()` 가 False 면 모든 fetch 함수가 None/빈값을
  돌려주고, 호출측은 기존 폴백 체인을 그대로 탄다. 이 저장소의 다른 API 가드와 같은 패턴.
* **날조 금지** — 응답이 없거나 형태가 다르면 None. 추정값을 만들어내지 않는다.
* **토큰은 프로세스 1회 발급** (expires_in 86400s). 만료 60초 전 자동 재발급.

환경변수: `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET`
"""

import gzip
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://openapi.tossinvest.com"
CLIENT_ID = os.environ.get("TOSS_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("TOSS_CLIENT_SECRET", "").strip()

# 지수·채권 지표 심볼 (그 외 심볼은 400 unsupported-symbol)
INDICATOR_SYMBOLS = ("KOSPI", "KOSDAQ", "KR_BOND_2Y", "KR_BOND_3Y",
                     "KR_BOND_5Y", "KR_BOND_10Y", "KR_BOND_20Y", "KR_BOND_30Y")

_token = {"value": None, "exp": 0.0}

# 토스 API 는 봇 차단 앞단(Cloudflare)을 두고 있다. GitHub Actions 러너에서
# `Python-urllib/3.x` UA 로 호출하면 403 Forbidden 이 떨어진다(2026-08-14 실측:
# 로컬 한국 IP 는 통과, GHA 러너는 전부 403). 브라우저형 헤더를 실어 통과율을 올린다.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
_BASE_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://openapi.tossinvest.com",
    "Referer": "https://openapi.tossinvest.com/docs",
}

# 러너 IP 가 차단될 때의 우회로 — 우리 Cloudflare Worker 의 `/toss` 릴레이.
# Worker 가 TOSS_CLIENT_ID/SECRET 을 쥐고 토큰까지 발급하므로 자격증명은 여기서 나가지 않는다.
# 인증 = 전용 공유키 TOSS_RELAY_KEY 의 SHA-256 해시(동기화 키를 재사용하지 않는 이유는
# 그 키를 프론트도 알고 있어 브라우저에서 릴레이를 부를 수 있게 되기 때문).
TOSS_RELAY = os.environ.get(
    "TOSS_RELAY", "https://ecom-dashboard-proxy.baldr0001.workers.dev/toss").strip()
RELAY_KEY = os.environ.get("TOSS_RELAY_KEY", "").strip()
_relay_mode = {"on": False}


def _relay_key_hash():
    import hashlib
    return hashlib.sha256(RELAY_KEY.encode()).hexdigest()


def log(msg):
    print(f"[TOSS] {msg}", flush=True)


def enabled():
    return bool(CLIENT_ID and CLIENT_SECRET)


def _decode(raw, headers):
    if (headers.get("Content-Encoding") or "").lower() == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def _access_token():
    """client_credentials 토큰. 만료 60초 전까지 재사용."""
    if not enabled():
        return None
    if _token["value"] and time.time() < _token["exp"] - 60:
        return _token["value"]
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode()
    req = urllib.request.Request(
        BASE + "/oauth2/token", data=body,
        headers={**_BASE_HEADERS, "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.loads(_decode(r.read(), r.headers))
    except urllib.error.HTTPError as e:
        # 403 = 러너 IP/UA 가 토스 앞단 봇 차단에 걸림 → Worker 릴레이로 전환
        if e.code == 403 and RELAY_KEY and TOSS_RELAY and not _relay_mode["on"]:
            _relay_mode["on"] = True
            log("직접 호출 403 — Cloudflare Worker 릴레이로 전환")
            return "relay"
        log(f"토큰 발급 실패: {e}")
        return None
    except Exception as e:                                  # noqa: BLE001
        log(f"토큰 발급 실패: {e}")
        return None
    tok = j.get("access_token")
    if not tok:
        log("토큰 응답에 access_token 없음")
        return None
    _token["value"] = tok
    _token["exp"] = time.time() + float(j.get("expires_in") or 3600)
    return tok


def _relay_get(path, params=None):
    """Worker 릴레이 경유 GET — Worker 가 토스 토큰을 쥐고 대신 호출한다."""
    q = dict(params or {})
    q["_path"] = path
    url = TOSS_RELAY + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={**_BASE_HEADERS,
                                               "X-Relay-Key-Hash": _relay_key_hash()})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(_decode(r.read(), r.headers)).get("result")
    except Exception as e:                                  # noqa: BLE001
        log(f"릴레이 {path} 오류: {e}")
        return None


def get(path, params=None, retries=2):
    """GET → result 필드. 실패하면 None (에러 메시지는 로그로만)."""
    if _relay_mode["on"]:
        return _relay_get(path, params)
    tok = _access_token()
    if not tok:
        return None
    if tok == "relay":                     # 직접 호출 403 → 릴레이로 재시도
        return _relay_get(path, params)
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={**_BASE_HEADERS,
                                                   "Authorization": "Bearer " + tok})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(_decode(r.read(), r.headers)).get("result")
        except urllib.error.HTTPError as e:
            body = _decode(e.read(), e.headers)[:300]
            # 429 는 Retry-After 만큼 쉬고 재시도, 그 외 4xx 는 재시도 무의미
            if e.code == 429 and attempt < retries:
                time.sleep(float(e.headers.get("Retry-After") or 1))
                continue
            log(f"{e.code} {path} {params or ''} — {body}")
            return None
        except Exception as e:                              # noqa: BLE001
            if attempt < retries:
                time.sleep(1)
                continue
            log(f"{path} 오류: {e}")
            return None
    return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── 시세 ────────────────────────────────────────────────────────────────────
def prices(symbols):
    """현재가. symbols=['005930','AAPL'] → {'005930': {'price':…,'currency':…,'ts':…}}"""
    syms = [s for s in symbols if s]
    out = {}
    for i in range(0, len(syms), 200):            # 1회 200종목 상한
        res = get("/api/v1/prices", {"symbols": ",".join(syms[i:i + 200])}) or []
        for row in res:
            p = _f(row.get("lastPrice"))
            if p is not None and p > 0:
                out[row.get("symbol")] = {
                    "price": p,
                    "currency": row.get("currency"),
                    "ts": row.get("timestamp"),
                }
    return out


def candles(symbol, interval="1d", count=200):
    """종목 일봉/분봉. 최신 → 과거 순으로 오므로 **과거 → 최신**으로 뒤집어 돌려준다."""
    res = get("/api/v1/candles",
              {"symbol": symbol, "interval": interval, "count": min(count, 200)})
    rows = (res or {}).get("candles") or []
    return _norm_candles(rows)


def indicator_prices(symbols=INDICATOR_SYMBOLS):
    """지수·국고채 현재값 → {'KOSPI': 6977.94, 'KR_BOND_5Y': 4.015, …}"""
    res = get("/api/v1/market-indicators/prices", {"symbols": ",".join(symbols)}) or []
    out = {}
    for row in res:
        v = _f(row.get("lastPrice"))
        if v is not None:
            out[row.get("symbol")] = v
    return out


def indicator_candles(symbol, interval="1d", count=200):
    """지수·국고채 일봉. 과거 → 최신 순."""
    res = get(f"/api/v1/market-indicators/{symbol}/candles",
              {"interval": interval, "count": min(count, 200)})
    return _norm_candles((res or {}).get("candles") or [])


def _norm_candles(rows):
    out = []
    for c in rows:
        close = _f(c.get("closePrice"))
        ts = c.get("timestamp") or ""
        if close is None or not ts:
            continue
        out.append({
            "date": ts[:10],
            "open": _f(c.get("openPrice")),
            "high": _f(c.get("highPrice")),
            "low": _f(c.get("lowPrice")),
            "close": close,
            "volume": _f(c.get("volume")),
        })
    out.sort(key=lambda x: x["date"])
    return out


def index_quote(symbol):
    """지수 현재가 + 전일比 %. 일봉 2개로 직접 계산(공식 등락률 필드가 없음).

    반환 {'price':…, 'change':…, 'asOf':'YYYY-MM-DD'} / 실패 시 None.
    """
    cs = indicator_candles(symbol, "1d", 3)
    if len(cs) < 2:
        return None
    last, prev = cs[-1], cs[-2]
    live = indicator_prices([symbol]).get(symbol)
    price = live if live else last["close"]
    if not price or not prev["close"]:
        return None
    return {
        "price": round(price, 2),
        "change": round((price / prev["close"] - 1) * 100, 2),
        "asOf": last["date"],
    }


# ── 종목 마스터 ──────────────────────────────────────────────────────────────
def stocks(symbols):
    """종목 기본정보 → {symbol: {'name':…, 'market':'KOSPI'|'KOSDAQ'|…, 'type':…}}"""
    syms = [s for s in symbols if s]
    out = {}
    for i in range(0, len(syms), 200):
        res = get("/api/v1/stocks", {"symbols": ",".join(syms[i:i + 200])}) or []
        for row in res:
            out[row.get("symbol")] = {
                "name": row.get("name"),
                "market": row.get("market"),
                "type": row.get("securityType"),
                "currency": row.get("currency"),
                "shares": _f(row.get("sharesOutstanding")),
            }
    return out


# ── 등락률 순위 ──────────────────────────────────────────────────────────────
def rankings(rank_type, market_country="KR", duration="1d", limit=30):
    """등락률/거래대금 순위.

    rank_type: MARKET_TRADING_AMOUNT | MARKET_TRADING_VOLUME | TOP_GAINERS |
               TOP_LOSERS | TOSS_SECURITIES_TRADING_AMOUNT | TOSS_SECURITIES_TRADING_VOLUME
    duration : realtime | 1d | 1w | 1mo | 3mo | 6mo | 1y

    → [{'code','price','chg','vol','amount'}] (chg 는 %). 종목명·시장은 stocks() 로 별도 조인.
    """
    res = get("/api/v1/rankings", {"type": rank_type, "marketCountry": market_country,
                                   "duration": duration})
    rows = (res or {}).get("rankings") or []
    out = []
    for r in rows[:limit]:
        p = (r.get("price") or {})
        last, rate = _f(p.get("lastPrice")), _f(p.get("changeRate"))
        if last is None or rate is None:
            continue
        out.append({
            "code": r.get("symbol"),
            "price": last,
            "chg": round(rate * 100, 2),          # 0.2998 → 29.98
            "vol": _f(r.get("tradingVolume")),
            "amount": _f(r.get("tradingAmount")),
        })
    return out


# ── 투자자별 매매동향 ────────────────────────────────────────────────────────
def _net_amt(node):
    """buyAmount/sellAmount(원) → 순매수 억원."""
    b, s = _f((node or {}).get("buyAmount")), _f((node or {}).get("sellAmount"))
    if b is None or s is None:
        return None
    return round((b - s) / 1e8, 1)


def index_investor_trading(symbol="KOSPI", interval="1d", max_pages=6):
    """지수(KOSPI/KOSDAQ) 투자자별 순매수 — 억원 단위, 과거 → 최신.

    한 번에 ~1개월치만 오므로 nextUntil 커서로 이어 받는다.
    → [{'date','foreign','inst','retail'}]
    """
    seen, rows, until = set(), [], None
    for _ in range(max_pages):
        q = {"interval": interval}
        if until:
            q["until"] = until
        res = get(f"/api/v1/market-indicators/{symbol}/investor-trading", q)
        recs = (res or {}).get("records") or []
        if not recs:
            break
        for r in recs:
            d = r.get("date")
            if not d or d in seen:
                continue
            f_, i_, p_ = (_net_amt(r.get("foreigner")), _net_amt(r.get("institution")),
                          _net_amt(r.get("individual")))
            if f_ is None and i_ is None and p_ is None:
                continue
            seen.add(d)
            rows.append({"date": d, "foreign": f_, "inst": i_, "retail": p_})
        until = (res or {}).get("nextUntil")
        if not until:
            break
    rows.sort(key=lambda x: x["date"])
    return rows


# ── 알림 스크립트용 스냅샷 ───────────────────────────────────────────────────
# 카톡·디스코드 알림(check_alerts / check_swings / check_halts / send_kakao_digest)은
# 여태 Yahoo 심볼(^KS11, ^KQ11)로 국내 지수를 읽었다. Yahoo 국내 지수는 지연·결측이
# 잦아 사이트 값과 알림 숫자가 어긋나는 원인이었다 → 같은 심볼을 토스로 갈아끼운다.
YAHOO_INDEX_MAP = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}


def snapshot(symbol, days=260):
    """알림 스크립트가 쓰는 스냅샷 형태로 반환.

    symbol: '^KS11'/'^KQ11'(지수) 또는 '005930'/'AAPL'(종목).
    → {price, pct, closes, highs, lows, vol_today, vol_prev, fresh} / 실패 시 None.
      (check_alerts.yahoo_snapshot 와 동일 계약 — SMA·RSI·일중 고저 판정이 그대로 동작)

    ⚠ **개별 종목 등락률에는 쓰지 말 것.** 토스 종목 일봉은 장전·정규장·시간외를 합친
      '통합 세션'이라 종가가 정규장 종가와 다르다(2026-08-14 실측: 삼성전자 08-13
      토스 263,000 vs 정규장 268,000 — 후자가 다음날 등락률의 기준가). 그래서 pct 가
      토스 앱 표시(+2.23%)보다 부풀었다(+4.2%). 종목 등락률이 필요하면 rankings() 의
      changeRate(기준가 기반)를 쓰거나 네이버/Yahoo 스냅샷을 그대로 둘 것.
      지수(KOSPI/KOSDAQ)는 시간외 산출이 없어 이 문제가 없다.
    """
    if not enabled():
        return None
    ind = YAHOO_INDEX_MAP.get(symbol)
    try:
        rows = (indicator_candles(ind, "1d", min(days, 200)) if ind
                else candles(symbol, "1d", min(days, 200)))
        live = (indicator_prices([ind]).get(ind) if ind
                else (prices([symbol]).get(symbol) or {}).get("price"))
    except Exception as e:                                  # noqa: BLE001
        log(f"snapshot({symbol}) 오류: {e}")
        return None
    if len(rows) < 2:
        return None
    import datetime as _dt
    today = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).date().isoformat()
    fresh = rows[-1]["date"] == today
    price = live or rows[-1]["close"]
    prev = rows[-2]["close"] if fresh else rows[-1]["close"]
    if not price or not prev:
        return None
    closes = [r["close"] for r in rows]
    closes[-1] = float(price)
    return {
        "price": float(price),
        "pct": (float(price) / float(prev) - 1) * 100,
        "closes": closes,
        "highs": [r["high"] for r in rows if r["high"] is not None],
        "lows": [r["low"] for r in rows if r["low"] is not None],
        "vol_today": rows[-1]["volume"] or None,
        "vol_prev": rows[-2]["volume"] or None,
        "fresh": fresh,
    }


def live_quote(symbol):
    """(현재가, 전일比 %) — 실패 시 None. 알림 본문 수치 보정용."""
    s = snapshot(symbol, days=5)
    return (s["price"], s["pct"]) if s else None


def stock_short_selling(symbol, max_pages=1):
    """종목 공매도 추이 → [{'date','volume','amount','volumeRate'}] 과거 → 최신."""
    rows, until = [], None
    for _ in range(max_pages):
        q = {"until": until} if until else None
        res = get(f"/api/v1/stocks/{symbol}/short-selling", q)
        recs = (res or {}).get("records") or []
        if not recs:
            break
        for r in recs:
            rows.append({
                "date": r.get("date"),
                "volume": _f(r.get("shortSellingVolume")),
                "amount": _f(r.get("shortSellingAmount")),
                "volumeRate": _f(r.get("shortSellingVolumeRate")),
            })
        until = (res or {}).get("nextUntil")
        if not until:
            break
    rows = [r for r in rows if r["date"]]
    rows.sort(key=lambda x: x["date"])
    return rows


# ── 환율 ────────────────────────────────────────────────────────────────────
def exchange_rate(base="USD", quote="KRW"):
    """토스 고시 환율 → {'rate':…, 'midRate':…, 'asOf':…} / 실패 시 None."""
    res = get("/api/v1/exchange-rate", {"baseCurrency": base, "quoteCurrency": quote})
    if not res:
        return None
    mid = _f(res.get("midRate")) or _f(res.get("rate"))
    if mid is None:
        return None
    return {"rate": _f(res.get("rate")), "midRate": mid, "asOf": res.get("validFrom")}


# ── 장 운영시간 ──────────────────────────────────────────────────────────────
def market_open_kr():
    """오늘이 국내 영업일인가 (휴장일이면 today 가 없거나 시간대가 비어 있음)."""
    res = get("/api/v1/market-calendar/KR")
    today = ((res or {}).get("today") or {})
    return bool((today.get("integrated") or {}).get("regularMarket"))


if __name__ == "__main__":                       # 자체 점검: python scripts/toss_api.py
    if not enabled():
        raise SystemExit("TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 미설정")
    q = index_quote("KOSPI")
    assert q and q["price"] > 0, f"KOSPI 시세 실패: {q}"
    ind = indicator_prices()
    assert ind.get("KR_BOND_5Y"), f"국고채 5Y 없음: {ind}"
    assert ind["KR_BOND_2Y"] < ind["KR_BOND_30Y"], "만기 구조 이상 (2Y >= 30Y)"
    g = rankings("TOP_GAINERS")
    assert g and g[0]["chg"] > 0, f"상승 상위 실패: {g[:1]}"
    inv = index_investor_trading("KOSPI")
    assert len(inv) > 10, f"투자자 동향 부족: {len(inv)}"
    px = prices(["005930"])
    assert px.get("005930", {}).get("price", 0) > 0, f"삼성전자 시세 실패: {px}"
    print(f"OK  KOSPI={q}  bonds={ind}  gainers={len(g)}  investor={len(inv)}일  005930={px}")
