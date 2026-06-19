#!/usr/bin/env python3
"""ENSO(엘니뇨·라니냐) 기후 지표 수집 — NOAA CPC(주) + JMA(보조).

왜: index.html 의 엘니뇨·라니냐 카드를 실시간 관측값으로 구동하기 위해
data.json.climate.enso 블록을 만든다. 소스별 try/except 로 부분 실패가
전체를 비우지 않게 하고(직전값 보존은 fetch_data.py 가 담당), 절대 값을 지어내지 않는다.

금지: detrend.nino34.ascii.txt(2019 동결), wksst8110.for(~2021 동결).
현행 파일만 사용: oni.ascii.txt / ersst5.nino.mth.91-20.ascii / wksst9120.for.
"""
import re
import urllib.request

ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
NINO34_MTH_URL = "https://www.cpc.ncep.noaa.gov/data/indices/ersst5.nino.mth.91-20.ascii"
NINO34_WK_URL = "https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for"
# JMA 는 best-effort. 정확한 URL/포맷은 구현 중 확인(아래 Task 4 주석 참고).
JMA_URL = "https://ds.data.jma.go.jp/tcc/tcc/products/elnino/index/sstindex/base_period_9120/Nino_3/anomaly"

_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
           "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}


def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "economic-site climate fetch"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def parse_oni(text):
    """oni.ascii.txt(SEAS YR TOTAL ANOM) → 마지막 데이터행의 ANOM."""
    last = None
    for line in text.splitlines():
        p = line.split()
        if len(p) == 4 and p[1].isdigit():
            last = p
    if not last:
        raise ValueError("ONI: no data rows")
    return {"value": float(last[3]), "season": last[0], "year": int(last[1])}
