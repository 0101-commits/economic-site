"""Twelve Data 2순위 시세 (교차검증/폴백 전용). 무료 플랜: 분당 8, 일 800 크레딧, 심볼 1개=1크레딧."""
import os
import time

import requests

URL = "https://api.twelvedata.com/quote"
# Yahoo -> Twelve Data. 검증: N225/HSI/000001(XSHG)는 무키 /indices 목록에서 확인.
# SPX/IXIC/SOX 는 /indices·symbol_search 에 없음(미검증, 무료 플랜 미포함 가능성).
SYMBOL_MAP = {
    "^GSPC": "SPX",
    "^IXIC": "IXIC",
    "^N225": "N225",
    "000001.SS": "000001:XSHG",
    "^SOX": "SOX",
    "^HSI": "HSI",
}
MIN_GAP = 10  # 초
_last_call_ts = 0.0


def enabled():
    return bool(os.environ.get("TWELVEDATA_API_KEY"))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def quote(symbols, log=print):
    """Yahoo 심볼 리스트 -> {yahoo_sym: {price, prev_close, change_pct, as_of, source}}. 실패 시 {}."""
    global _last_call_ts
    try:
        key = os.environ.get("TWELVEDATA_API_KEY")
        if not key:
            return {}
        rev = {SYMBOL_MAP[s]: s for s in symbols if s in SYMBOL_MAP}
        if not rev:
            return {}
        now = time.monotonic()
        if _last_call_ts and now - _last_call_ts < MIN_GAP:
            log("[TD] rate guard: 10초 내 재호출 거부")
            return {}
        _last_call_ts = now
        r = requests.get(URL, params={"symbol": ",".join(rev), "apikey": key}, timeout=15)
        data = r.json()
        if isinstance(data, dict) and data.get("status") == "error":
            log(f"[TD] error {data.get('code')}: {data.get('message')}")
            return {}
        if len(rev) == 1 and "symbol" in data:  # 단일 심볼은 키 없이 객체로 옴
            data = {next(iter(rev)): data}
        out = {}
        for td_sym, item in data.items():
            ysym = rev.get(td_sym) or rev.get(str(item.get("symbol")))
            if not ysym or not isinstance(item, dict) or item.get("status") == "error":
                continue
            price, prev = _num(item.get("close")), _num(item.get("previous_close"))
            if price is None:
                continue
            chg = _num(item.get("percent_change"))
            if chg is None and prev:
                chg = (price / prev - 1) * 100
            out[ysym] = {"price": price, "prev_close": prev, "change_pct": chg,
                         "as_of": item.get("datetime"), "source": "Twelve Data"}
        return out
    except Exception as e:  # noqa: BLE001 - 모듈은 절대 raise 하지 않는다
        log(f"[TD] {type(e).__name__}: {e}")
        return {}


def cross_check(yahoo_quotes, td_quotes, tol_pct=1.0):
    """두 소스 가격 비교 -> [{sym, yahoo, td, diffPct, ok}]. yahoo_quotes 값은 {price} dict 또는 숫자."""
    res = []
    for sym, td in td_quotes.items():
        y = yahoo_quotes.get(sym)
        yp = _num(y.get("price") if isinstance(y, dict) else y)
        tp = td.get("price")
        if not yp or tp is None:
            continue
        diff = abs(tp / yp - 1) * 100
        res.append({"sym": sym, "yahoo": yp, "td": tp, "diffPct": round(diff, 3), "ok": diff <= tol_pct})
    return res
