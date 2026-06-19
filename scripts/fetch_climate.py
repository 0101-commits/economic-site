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


def parse_nino34_monthly(text):
    """ersst5.nino.mth.91-20.ascii → NINO3.4 ANOM(마지막 컬럼) 의 최신 행."""
    last = None
    for line in text.splitlines():
        p = line.split()
        if len(p) == 10 and p[0].isdigit() and p[1].isdigit():
            last = p
    if not last:
        raise ValueError("NINO3.4 monthly: no data rows")
    return {"value": float(last[-1]), "year": int(last[0]), "mon": int(last[1])}


def _wk_date(token):
    d = int(token[:2]); mon = _MONTHS[token[2:5].upper()]; y = int(token[5:])
    return f"{y:04d}-{mon:02d}-{d:02d}"


def parse_nino34_weekly(text):
    """wksst9120.for(고정폭) → Nino34 SSTA.

    음수 SSTA 가 SST 에 붙는 포맷(26.6-0.2) 때문에 split 대신 부호 포함 float 를
    추출한다. 각 데이터행은 [N12 SST,SSTA, N3 SST,SSTA, N34 SST,SSTA, N4 SST,SSTA]
    8개 float → Nino34 SSTA = index 5.
    """
    date_re = re.compile(r"^\s*(\d{2}[A-Za-z]{3}\d{4})")
    num_re = re.compile(r"[-+]?\d+\.\d+")
    rows = []
    for line in text.splitlines():
        m = date_re.match(line)
        if not m:
            continue
        nums = num_re.findall(line)
        if len(nums) >= 8:
            rows.append((m.group(1).upper(), float(nums[5])))
    if not rows:
        raise ValueError("NINO3.4 weekly: no data rows")
    token, val = rows[-1]
    prev = rows[-2][1] if len(rows) >= 2 else None
    return {"value": val, "weekEnding": _wk_date(token), "prevValue": prev}


def derive_phase(oni_value):
    if oni_value >= 0.5:
        return "elnino"
    if oni_value <= -0.5:
        return "lanina"
    return "neutral"


def derive_strength(oni_value):
    a = abs(oni_value)
    if a < 0.5:
        return "neutral"
    if a < 1.0:
        return "weak"
    if a < 1.5:
        return "moderate"
    if a < 2.0:
        return "strong"
    return "very_strong"


def derive_trend(prev, last, eps=0.1):
    if prev is None:
        return "steady"
    d = last - prev
    if d > eps:
        return "warming"
    if d < -eps:
        return "cooling"
    return "steady"


def parse_jma_nino3(text):
    """JMA NINO.3 월별 편차 — best-effort. 'YYYY MM value' 마지막 행, 없으면 None."""
    row_re = re.compile(r"^\s*(\d{4})\s+(\d{1,2})\s+([-+]?\d+\.\d+)\s*$")
    last = None
    for line in (text or "").splitlines():
        m = row_re.match(line)
        if m:
            last = m
    if not last:
        return None
    y, mon, val = int(last.group(1)), int(last.group(2)), float(last.group(3))
    return {"value": val, "asOf": f"{y:04d}-{mon:02d}"}
