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
# 공식 예측(향후 9개 중첩 3개월 시즌의 엘니뇨/중립/라니냐 확률) 테이블 페이지.
# 정적 PNG(enso-probs-current.png) 대신 표를 파싱해 인터랙티브 차트로 구동한다.
PROB_URL = "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/probabilities/"
# JMA 는 best-effort. 정확한 URL/포맷은 구현 중 확인(아래 Task 4 주석 참고).
JMA_URL = "https://ds.data.jma.go.jp/tcc/tcc/products/elnino/index/sstindex/base_period_9120/Nino_3/anomaly"

_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
           "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}

# ONI 시즌(rolling 3개월) → 대표 '중앙월'. 추이 차트 x축 라벨용(DJF→01 … NDJ→12).
_SEASON_MONTH = {"DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
                 "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12}


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


def parse_oni_history(text, keep=120):
    """oni.ascii.txt 전체 → 최근 keep개월 시계열 [{"t":"YYYY-MM","v":ANOM}].

    추이 차트용. 각 행 'SEAS YR TOTAL ANOM'. 시즌을 대표 중앙월에 매핑하고
    (DJF→01 … NDJ→12) 파일의 시간순을 신뢰해 마지막 keep개만 취한다.
    값을 지어내지 않는다 — 데이터행이 없으면 ValueError.
    """
    out = []
    for line in text.splitlines():
        p = line.split()
        if len(p) == 4 and p[1].isdigit() and p[0] in _SEASON_MONTH:
            try:
                v = float(p[3])
            except ValueError:
                continue
            out.append({"t": f"{int(p[1]):04d}-{_SEASON_MONTH[p[0]]:02d}", "v": v})
    if not out:
        raise ValueError("ONI history: no data rows")
    return out[-keep:]


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


def _prob_classify_header(text):
    """헤더 셀 텍스트 → 'lanina'|'neutral'|'elnino'|None.

    위치(컬럼 순서)를 가정하지 않고 헤더 단어로만 분류한다 — 라니냐/엘니뇨를
    뒤바꿔 표기하는 사고를 원천 차단(잘못된 라벨은 데이터 날조와 같다).
    """
    t = (text or "").strip().lower().replace("ñ", "n")
    if "neutral" in t:
        return "neutral"
    if "nina" in t:
        return "lanina"
    if "nino" in t:
        return "elnino"
    return None


def _prob_first_num(text):
    """셀에서 첫 숫자(확률 %) 추출. '55%', '~55', '55*' 등 표기 흡수. 없으면 None."""
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else None


def _prob_season_label(text):
    """셀 텍스트에서 'MJJ 2026' 형태의 시즌 라벨 추출. 코드가 _SEASON_MONTH 에
    있어야만 인정(임의 3글자 오인식 방지). 없으면 None."""
    s = re.sub(r"\s+", " ", text or "").strip()
    m = re.search(r"\b([A-Z]{3})\b\D*?(\d{4})", s)
    if m and m.group(1) in _SEASON_MONTH:
        return f"{m.group(1)} {m.group(2)}"
    return None


def parse_cpc_probabilities(html):
    """CPC/IRI 공식 ENSO 확률 표(향후 9개 중첩 3개월 시즌) → 시즌별 확률 리스트.

    반환: [{"label":"MJJ 2026","lanina":55.0,"neutral":42.0,"elnino":3.0}, ...]
    엄격(correct-or-nothing): 헤더에서 라니냐/중립/엘니뇨 3개 컬럼을 모두
    단어로 식별하지 못하거나 유효 시즌 행이 3개 미만이면 ValueError 를 던져
    호출측이 stale 처리(프런트는 기존 원본 이미지로 폴백)하게 한다.
    bs4 미설치 시 ImportError → 동일하게 stale 폴백.
    """
    from bs4 import BeautifulSoup  # 워크플로에 설치됨. 없으면 stale 폴백.
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        colmap, header_idx = {}, None
        for ri, tr in enumerate(rows):
            cells = tr.find_all(["th", "td"])
            m = {}
            for ci, c in enumerate(cells):
                cat = _prob_classify_header(c.get_text(" ", strip=True))
                if cat and cat not in m:
                    m[cat] = ci
            if len(m) == 3:
                colmap, header_idx = m, ri
                break
        if header_idx is None:
            continue
        seasons = []
        for tr in rows[header_idx + 1:]:
            texts = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if not texts:
                continue
            label = next((lbl for lbl in (_prob_season_label(t) for t in texts) if lbl), None)
            if not label:
                continue
            try:
                ln = _prob_first_num(texts[colmap["lanina"]])
                nu = _prob_first_num(texts[colmap["neutral"]])
                en = _prob_first_num(texts[colmap["elnino"]])
            except IndexError:
                continue
            if None in (ln, nu, en):
                continue
            seasons.append({"label": label, "lanina": ln, "neutral": nu, "elnino": en})
            if len(seasons) >= 9:
                break
        if len(seasons) >= 3:
            return seasons
    raise ValueError("CPC probabilities: no parseable table")


def fetch_enso(get=_http_get):
    """ENSO 블록 생성. 소스별 독립 try/except — 부분 실패는 stale 플래그로 표시하고
    다른 소스는 살린다. 모든 소스 실패 시 None(호출측이 직전값 보존)."""
    enso = {"phase": "neutral", "strength": "neutral", "trend": "steady",
            "stale": {}, "sources": {}}
    ok = False

    try:
        _oni_txt = get(ONI_URL)
        o = parse_oni(_oni_txt)
        enso["oni"] = {"value": o["value"], "season": o["season"],
                       "year": o["year"], "asOf": f'{o["season"]} {o["year"]}'}
        enso["sources"]["oni"] = ONI_URL
        enso["stale"]["oni"] = False
        enso["phase"] = derive_phase(o["value"])
        enso["strength"] = derive_strength(o["value"])
        ok = True
        # 과거 시계열(추이 차트용) — 같은 텍스트 재사용, 독립 실패 처리.
        try:
            enso["oni_history"] = parse_oni_history(_oni_txt)
            enso["stale"]["oni_history"] = False
        except Exception:
            enso["stale"]["oni_history"] = True
    except Exception:
        enso["stale"]["oni"] = True
        enso["stale"]["oni_history"] = True

    try:
        m = parse_nino34_monthly(get(NINO34_MTH_URL))
        enso["nino34_monthly"] = m
        enso["sources"]["nino34_monthly"] = NINO34_MTH_URL
        enso["stale"]["nino34_monthly"] = False
        ok = True
    except Exception:
        enso["stale"]["nino34_monthly"] = True

    try:
        w = parse_nino34_weekly(get(NINO34_WK_URL))
        enso["nino34_weekly"] = {"value": w["value"], "weekEnding": w["weekEnding"]}
        enso["sources"]["nino34_weekly"] = NINO34_WK_URL
        enso["stale"]["nino34_weekly"] = False
        enso["trend"] = derive_trend(w["prevValue"], w["value"])
        ok = True
    except Exception:
        enso["stale"]["nino34_weekly"] = True

    # 공식 예측 확률 — 정적 PNG 대신 표를 파싱해 인터랙티브 차트 데이터로 제공.
    # 실패(포맷 변경/표 부재/bs4 미설치) 시 stale 플래그만 세우고 forecast 키를
    # 만들지 않는다 → 프런트는 기존 NOAA 이미지로 자동 폴백(무회귀).
    try:
        seasons = parse_cpc_probabilities(get(PROB_URL))
        enso["forecast"] = {"source": "NOAA CPC/IRI", "url": PROB_URL,
                            "seasons": seasons}
        enso["sources"]["forecast"] = PROB_URL
        enso["stale"]["forecast"] = False
    except Exception:
        enso["stale"]["forecast"] = True

    try:
        j = parse_jma_nino3(get(JMA_URL))
        enso["jma_nino3"] = j
        enso["stale"]["jma_nino3"] = j is None
        if j:
            enso["sources"]["jma_nino3"] = JMA_URL
    except Exception:
        enso["jma_nino3"] = None
        enso["stale"]["jma_nino3"] = True

    return enso if ok else None
