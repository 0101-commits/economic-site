#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""국내 지수 실시간 값 — 네이버 증권 폴링 API(지연 0초, 무키).

`polling.finance.naver.com/api/realtime/domestic/index/{KOSPI|KOSDAQ|FUT}` 한 번에 한 지수.
등락률(fluctuationsRatio)은 공식 전날 종가 대비이고, 전날 종가 = 현재값 − compareToPreviousClosePrice 다
(2026-11-20 실측: 코스피 4,869.96 · −267.93 → 전날 5,137.89 = 네이버 일별 · 거래소 공시 기준가와 같다).

왜: 번들 · data.json 의 코스피 등락이 다른 기준값(5,084.76)으로 계산돼 −4.70% 를 −3.71% 로 보였고, 급변 경보가
10분 묶음을 기다려 중간값 20분 늦었다(기획 4ioDhgSA ②). 이 모듈은 값만 돌려주고, 쓰는 곳이 「오늘 장중 값인가」를
`live` 칸으로 가른다 — 09:00 전 시각 = 전날 종가(개장 가드).
"""
import datetime as dt
import json
import urllib.request

KST = dt.timezone(dt.timedelta(hours=9))
URL = "https://polling.finance.naver.com/api/realtime/domestic/index/{sym}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
SYMS = {"kospi": "KOSPI", "kosdaq": "KOSDAQ", "kospi200f": "FUT"}


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse(payload: dict, now: dt.datetime | None = None) -> dict | None:
    """폴링 응답 → {value, change, changePct, prevClose, asOf, status, live}. 값이 없으면 None.

    live = 오늘(KST) 09:00 이후에 찍힌 값. 장 마감 뒤에도 오늘 종가면 참이다(오늘 움직임)."""
    rows = (payload or {}).get("datas") or []
    if not rows or not isinstance(rows[0], dict):
        return None
    r = rows[0]
    v = _num(r.get("closePriceRaw") or r.get("closePrice"))
    pct = _num(r.get("fluctuationsRatioRaw") or r.get("fluctuationsRatio"))
    ch = _num(r.get("compareToPreviousClosePriceRaw") or r.get("compareToPreviousClosePrice"))
    if v is None or v <= 0 or pct is None:
        return None
    try:
        at = dt.datetime.fromisoformat(str(r.get("localTradedAt")))
    except (TypeError, ValueError):
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=KST)
    at = at.astimezone(KST)
    now = (now or dt.datetime.now(KST)).astimezone(KST)
    opened = at.replace(hour=9, minute=0, second=0, microsecond=0)
    live = at.date() == now.date() and at >= opened
    return {"value": v, "change": ch, "changePct": pct,
            "prevClose": round(v - ch, 2) if ch is not None else None,
            "asOf": at.isoformat(timespec="seconds"), "status": str(r.get("marketStatus") or ""),
            "live": live}


def quote(target: str, now: dt.datetime | None = None, timeout: float = 6.0) -> dict | None:
    """target = kospi · kosdaq · kospi200f. 실패하면 None(호출부는 번들 값으로 간다)."""
    sym = SYMS.get(target, target)
    req = urllib.request.Request(URL.format(sym=sym), headers={"User-Agent": UA, "Referer": "https://finance.naver.com/"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:                                 # noqa: BLE001 — 네트워크 · 형식 오류는 None
        print(f"[naver-rt] {sym} 실패: {type(e).__name__}")
        return None
    return parse(payload, now)


if __name__ == "__main__":
    for t in SYMS:
        print(t, quote(t))
