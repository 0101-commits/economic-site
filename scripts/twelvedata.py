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


PROXY_MAP = {"^GSPC": "SPY", "^IXIC": "QQQ", "^SOX": "SOXX"}  # 지수 실패 시 방향 대조 전용 ETF
SLEEP = 1.2  # 초: 심볼별 폴백 요청 간격(무료 분당 8)


def _parse(item):
    if not isinstance(item, dict) or item.get("status") == "error":
        return None
    price, prev = _num(item.get("close")), _num(item.get("previous_close"))
    if price is None:
        return None
    chg = _num(item.get("percent_change"))
    if chg is None and prev:
        chg = (price / prev - 1) * 100
    return {"price": price, "prev_close": prev, "change_pct": chg,
            "as_of": item.get("datetime"), "source": "Twelve Data"}


def _get(params, key):
    return requests.get(URL, params={**params, "apikey": key}, timeout=15).json()


def _top_error(data):
    return isinstance(data, dict) and (data.get("status") == "error" or (
        "code" in data and "message" in data and not any(isinstance(v, dict) for v in data.values())))


def _fetch(syms, key, errs, extra=None):
    """Twelve Data 심볼 리스트 -> {td_sym: 파싱된 시세}. 배치 1회, 최상위 오류면 심볼별 재요청. 실패 사유는 errs."""
    out = {}
    data = _get({"symbol": ",".join(syms), **(extra or {})}, key)
    if _top_error(data):
        if len(syms) == 1:
            errs[syms[0]] = data.get("message")
            return out
        for i, s in enumerate(syms):  # 배치 전체가 거절됨 -> 심볼별
            if i:
                time.sleep(SLEEP)
            out.update(_fetch([s], key, errs, extra))
        return out
    if len(syms) == 1 and "symbol" in data:  # 단일 심볼은 키 없이 객체로 옴
        data = {syms[0]: data}
    for k, item in (data.items() if isinstance(data, dict) else []):
        sym = k if k in syms else (str(item.get("symbol")) if isinstance(item, dict) else None)
        if sym not in syms:
            continue
        q = _parse(item)
        if q:
            out[sym] = q
        else:
            errs[sym] = item.get("message") if isinstance(item, dict) else "invalid"
    return out


def quote(symbols, log=print):
    """Yahoo 심볼 리스트 -> {yahoo_sym: {price, prev_close, change_pct, as_of, source}}. 실패 시 {}.
    지수가 실패한 미국 3종은 ETF 대용 시세를 out["_proxies"][yahoo_sym] 에 따로 싣는다(채움용 아님, 방향 대조 전용)."""
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
        _last_call_ts = now  # 가드는 quote() 호출 단위 — 안의 폴백 루프는 SLEEP 으로만 간격 조절
        errs = {}
        got = _fetch(list(rev), key, errs)
        if "000001:XSHG" in rev and "000001:XSHG" not in got:
            time.sleep(SLEEP)
            sh = _fetch(["000001"], key, errs, {"exchange": "XSHG"})
            if "000001" in sh:
                got["000001:XSHG"] = sh["000001"]
                errs.pop("000001:XSHG", None)
        out = {rev[k]: v for k, v in got.items()}
        proxies = {}
        want = {PROXY_MAP[y]: y for y in rev.values() if y in PROXY_MAP and y not in out}
        if want:
            time.sleep(SLEEP)
            for etf, q in _fetch(list(want), key, {}).items():
                proxies[want[etf]] = {**q, "proxy": etf, "fill_ok": False}
        if proxies:
            out["_proxies"] = proxies
        bad = [f"{rev[k]}: {m}" for k, m in errs.items() if k in rev and rev[k] not in out]
        log(f"[TD] {len(got)}/{len(rev)} 심볼 수신 (실패: {'; '.join(bad) or '없음'})"
            + (f" 프록시 {sorted(proxies)}" if proxies else ""))
        for sym, msg in errs.items():
            log(f"[TD] {sym}: {msg}")
        return out
    except Exception as e:  # noqa: BLE001 - 모듈은 절대 raise 하지 않는다
        log(f"[TD] {type(e).__name__}: {e}")
        return {}


def cross_check(yahoo_quotes, td_quotes, tol_pct=1.0):
    """두 소스 가격 비교 -> [{sym, yahoo, td, diffPct, ok}]. yahoo_quotes 값은 {price} dict 또는 숫자."""
    res = []
    for sym, td in td_quotes.items():
        if sym == "_proxies":  # ETF 대용은 수준 비교 불가 — 등락 방향만 대조
            for psym, p in td.items():
                y = yahoo_quotes.get(psym)
                yc = _num(y.get("change") if isinstance(y, dict) else None)
                if yc is not None and p.get("change_pct") is not None:
                    res.append({"sym": psym, "proxy": p["proxy"], "yahooChg": yc, "tdChg": round(p["change_pct"], 3),
                                "ok": (yc >= 0) == (p["change_pct"] >= 0)})
            continue
        y = yahoo_quotes.get(sym)
        yp = _num(y.get("price") if isinstance(y, dict) else y)
        tp = td.get("price")
        if not yp or tp is None:
            continue
        diff = abs(tp / yp - 1) * 100
        res.append({"sym": sym, "yahoo": yp, "td": tp, "diffPct": round(diff, 3), "ok": diff <= tol_pct})
    return res
