#!/usr/bin/env python3
"""FRED 가 폐기한 국제 지표의 대체 소스 — ECB Data Portal + OECD SDMX.

왜 이 파일이 생겼나 (2026-08 감사):
FRED 가 OECD MEI 계열 전체를 폐기하면서 일본 CPI(2021-06), 유로존 실업률(2023-01),
중국 CPI(2025-04), 영국 CPI(2025-03) 가 원본에서 끊겼다. fetch_data.py 는 정직하게
마지막 값을 가져왔을 뿐이라 코드로 고칠 수 없고, 소스를 바꾸는 수밖에 없다.

둘 다 **인증 불필요·무료** 공개 API 라 공개 저장소 제약과 충돌하지 않는다.
반환 형태는 fetch_fred_intl_indicators() 와 동일하게 맞춰, 호출 측이
economicIndicators[cc] 에 그대로 병합할 수 있게 한다:

    {"cn": {"cpi_cn": {"value": 1.0, "period": "2026-06-01", "desc": ...,
                       "source": ..., "history": {"2026-06-01": 1.0, ...}}}}
"""
import json
import sys
import urllib.request

_UA = {"User-Agent": "economic-site/1.0 (+https://github.com/0101-commits/economic-site)"}
_TIMEOUT = 30


def _get_json(url, accept=None):
    headers = dict(_UA)
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.load(r)


def _month_key(period):
    """'2026-06' → '2026-06-01', '2026-Q3' → '2026-07-01' (FRED 키 형식 — 프런트가 이 형식을 기대한다)"""
    p = str(period)
    if len(p) == 7 and p[5] == "Q" and p[6] in "1234":
        return f"{p[:4]}-{(int(p[6]) - 1) * 3 + 1:02d}-01"
    return f"{p}-01" if len(p) == 7 else p


# ── ECB Data Portal ────────────────────────────────────────────────────────
# https://data-api.ecb.europa.eu/service/data/<flowRef>/<key>?format=jsondata
ECB_SERIES = {
    # 유로존 실업률 (계절조정, 15-74세) — FRED LRHUTTTTEZM156S 대체
    "unemployment_eu": ("LFSI/M.I9.S.UNEHRT.TOTAL0.15_74.T", "유로존 실업률 (계절조정, ECB)"),
}


def fetch_ecb(key, n=60):
    """ECB SDMX-JSON → [(period, value), ...] 오래된 순."""
    url = (f"https://data-api.ecb.europa.eu/service/data/{key}"
           f"?lastNObservations={n}&format=jsondata")
    d = _get_json(url, accept="application/json")
    series = d["dataSets"][0]["series"]
    obs_dim = d["structure"]["dimensions"]["observation"][0]["values"]
    out = []
    for s in series.values():
        for idx, val in s["observations"].items():
            if val and val[0] is not None:
                out.append((obs_dim[int(idx)]["id"], val[0]))
        break                                   # 키를 특정했으므로 시리즈는 하나
    return sorted(out)


# ── OECD SDMX (Data Explorer) ──────────────────────────────────────────────
_OECD_PRICES = "OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0"

OECD_SERIES = {
    # FRED CHNCPIALLMINMEI / GBRCPIALLMINMEI 대체. GY = 전년동월비 %.
    "cpi_cn": (f"{_OECD_PRICES}/CHN.M.N.CPI.PA._T.N.GY", "중국 CPI 상승률 (전년동월비 %, OECD)"),
    "cpi_uk": (f"{_OECD_PRICES}/GBR.M.N.CPI.PA._T.N.GY", "영국 CPI 상승률 (전년동월비 %, OECD)"),
    # 일본 CPI 는 OECD 도 2021-06 에서 끊겨 있다(FRED 와 같은 상류). 되살아나면 여기 추가.
    # 중국 실질GDP 성장률(분기, 계절조정, 전년동기비). 종전 FRED MKTGDPCNA646NWDB(세계은행 연간 명목 USD)는
    # 2025년 값 하나가 마지막이었다. OECD 직접 호출은 2026-11-04 에 3분기분까지 준다(DBnomics 중계본은 1분기).
    "gdp_yoy_cn": ("OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA_EXPENDITURE_GROWTH_OECD,/Q.Y.CHN.S1.S1.B1GQ._Z._Z._Z.PC.L.GY.",
                   "중국 실질GDP 성장률 (전년동기비 %, 분기, OECD)"),
}


def fetch_oecd(key, n=60):
    """OECD SDMX-JSON → [(period, value), ...] 오래된 순."""
    url = (f"https://sdmx.oecd.org/public/rest/data/{key}"
           f"?lastNObservations={n}&dimensionAtObservation=TIME_PERIOD")
    d = _get_json(url, accept="application/vnd.sdmx.data+json;version=1.0")
    root = d.get("data", d)
    series = root["dataSets"][0]["series"]
    obs_dim = root["structure"]["dimensions"]["observation"][0]["values"]
    out = []
    for s in series.values():
        for idx, val in s["observations"].items():
            if val and val[0] is not None:
                out.append((obs_dim[int(idx)]["id"], val[0]))
        break
    return sorted(out)


# ── ONS (영국 통계청) ─────────────────────────────────────────────────────
# https://www.ons.gov.uk/<path>/data — 무인증 JSON. 노동시장 지표는 3개월 이동 평균이라
# label 이 '2026 MAY-JUL' 형태다 — 기간의 마지막 달(7월)을 as-of 로 쓴다. FRED 의 OECD 판
# (LRHUTTTTGBM156S)은 같은 값을 두 달 늦게 싣는다(2026-09-24 실측: FRED 5월 / ONS 7월).
ONS_SERIES = {
    "unemployment_uk": ("employmentandlabourmarket/peoplenotinwork/unemployment/timeseries/mgsx/lms",
                        "영국 실업률 (16세+, 계절조정, 3개월 이동 %)"),
}
_MON = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def _ons_period(label):
    """'2026 MAY-JUL' → '2026-07', '2025 NOV-JAN' → '2026-01', '2026 JUN' → '2026-06'."""
    parts = str(label).split()
    if len(parts) != 2 or not parts[0].isdigit():
        return None
    y, rng = int(parts[0]), parts[1].split("-")
    a, b = _MON.get(rng[0]), _MON.get(rng[-1])
    if not a or not b:
        return None
    if b < a:
        y += 1
    return f"{y:04d}-{b:02d}"


def fetch_ons(path, n=60):
    j = _get_json(f"https://www.ons.gov.uk/{path}/data")
    out = []
    for m in (j.get("months") or [])[-n:]:
        p = _ons_period(m.get("label") or m.get("date"))
        try:
            v = float(m.get("value"))
        except (TypeError, ValueError):
            continue
        if p:
            out.append((p, v))
    return sorted(out)


# ── 일본은행(BOJ) 시계열 API ──────────────────────────────────────────────
# https://www.stat-search.boj.or.jp/api/v1/getDataCode — 무인증. 정책금리(무담보 콜 익일물
# 유도목표)를 따르는 실제 콜금리 일별 평균을 월평균으로 접는다. 종전엔 FRED 의 OECD 판
# (IRSTCI01JPM156N, 2~3개월 지연) 위에 코드 안 결정표(_BOJ_KNOWN)를 덮어써서 사람이
# 고치지 않으면 갱신되지 않았다(2026-09-24 감사 F5).
BOJ_SERIES = {
    "base_rate_jp": ("FM01/STRDCLUCON", "일본 정책금리 (무담보 콜 익일물 평균, 월평균 %)"),
}


def fetch_boj(key, n=60):
    from datetime import date
    db, code = key.split("/")
    y = date.today().year - 5
    j = _get_json("https://www.stat-search.boj.or.jp/api/v1/getDataCode"
                  f"?format=json&lang=en&db={db}&code={code}&startDate={y}01")
    vals = ((j.get("RESULTSET") or [{}])[0].get("VALUES")) or {}
    by_month = {}
    for d, v in zip(vals.get("SURVEY_DATES") or [], vals.get("VALUES") or []):
        if v is None:
            continue
        k = f"{str(d)[:4]}-{str(d)[4:6]}"
        by_month.setdefault(k, []).append(float(v))
    return sorted((k, round(sum(v) / len(v), 3)) for k, v in by_month.items())[-n:]


# ── Eurostat (무인증 JSON-stat) ─────────────────────────────────────────────
# FRED LRHUTTTTDEM156S(OECD 중계)는 약 2개월 늦었다(2026-11-04 에 8월분이 마지막, Eurostat 는 9월분).
EUROSTAT_SERIES = {
    "unemployment_de": ("une_rt_m?geo=DE&s_adj=SA&age=TOTAL&sex=T&unit=PC_ACT",
                        "독일 실업률 (계절조정, ILO 기준, Eurostat)"),
}


def fetch_eurostat(key, n=60):
    """Eurostat JSON-stat → [(YYYY-MM, value), ...] 오래된 순. value 는 시간 위치(문자열 숫자)를 키로 한다."""
    d = _get_json(f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{key}&format=JSON&lang=EN")
    idx = d["dimension"]["time"]["category"]["index"]          # {"2026-09": 524, ...}
    vals = d.get("value") or {}
    out = [(t, vals.get(str(i))) for t, i in idx.items()]
    return sorted((t, v) for t, v in out if isinstance(v, (int, float)))[-n:]


# ── DBnomics (무인증 중계) ──────────────────────────────────────────────────
# 일본 실업률 — FRED LRUN64TTJPM156S(15-64세, OECD 중계)는 1개월 늦었다. 총무성 노동력조사 원계열을 DBnomics 가
# 그대로 중계한다(일본 CPI 와 같은 제공처). 개념 차이: 15세 이상 전체(FRED 는 15-64세) — 2026-08 2.5 vs 2.6.
DBNOMICS_SERIES = {
    "unemployment_jp": ("STATJP/MIm/M.UR.B.PCT.SA", "일본 실업률 (계절조정, 15세 이상, 총무성)"),
}


def fetch_dbnomics(key, n=60):
    d = _get_json(f"https://api.db.nomics.world/v22/series/{key}?observations=1&format=json")
    doc = d["series"]["docs"][0]
    pts = [(str(p)[:7], v) for p, v in zip(doc["period"], doc["value"])
           if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return sorted(pts)[-n:]


# ── 미시간대 소비심리 (무인증 CSV) ──────────────────────────────────────────
# FRED UMCSENT 는 미시간대 사정으로 한 달 늦게 싣는다(2026-11-04 에 9월분, 10월 확정치는 10/30 공표).
UMICH_URL = "https://www.sca.isr.umich.edu/files/tbmics.csv"
_MONTHS_EN = {m: i for i, m in enumerate(
    ("january february march april may june july august september october november december").split(), 1)}


def parse_umich_csv(text, n=60):
    """tbmics.csv(Month,YYYY,ICS_ALL) → [(YYYY-MM, 지수)] 오래된 순. 1952~53 의 분기 값도 그대로 달 키로 둔다."""
    import csv
    import io
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        m = _MONTHS_EN.get(str(row.get("Month") or "").strip().lower())
        y = str(row.get("YYYY") or "").strip()
        try:
            v = float(row.get("ICS_ALL"))
        except (TypeError, ValueError):
            continue
        if m and y.isdigit():
            out[f"{y}-{m:02d}"] = v
    return sorted(out.items())[-n:]


def fetch_umich_sentiment(n=60):
    req = urllib.request.Request(UMICH_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; economic-site/1.0)"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return _node(parse_umich_csv(r.read().decode("utf-8", "replace"), n),
                     "미국 소비자심리지수 (미시간대)", "UMich SCA:tbmics")


def _node(obs, desc, source):
    if not obs:
        return None
    hist = {_month_key(p): v for p, v in obs}
    last_p, last_v = obs[-1]
    return {
        "value": last_v,
        "period": _month_key(last_p),
        "desc": desc,
        "source": source,
        "history": hist,
    }


# 지표 키 → 소속 국가코드 (economicIndicators 의 하위 키)
_CC_OF = {"unemployment_eu": "eu", "cpi_cn": "cn", "cpi_uk": "uk", "unemployment_uk": "uk",
          "base_rate_jp": "jp", "unemployment_de": "de", "unemployment_jp": "jp", "gdp_yoy_cn": "cn"}


def fetch_all(log=print):
    """{cc: {지표키: node}} 반환. 개별 실패는 건너뛴다 — 하나가 죽어도 나머지는 살린다."""
    out = {}
    jobs = [("ECB", fetch_ecb, ECB_SERIES), ("OECD", fetch_oecd, OECD_SERIES), ("ONS", fetch_ons, ONS_SERIES),
            ("BOJ", fetch_boj, BOJ_SERIES), ("Eurostat", fetch_eurostat, EUROSTAT_SERIES),
            ("DBnomics", fetch_dbnomics, DBNOMICS_SERIES)]
    for tag, fn, table in jobs:
        for name, (key, desc) in table.items():
            try:
                seg = key.split('/')
                src = (f"Eurostat:{key.split('?')[0]}/DE" if tag == "Eurostat"
                       else f"DBnomics:{key}" if tag == "DBnomics"
                       else f"{tag}:{seg[-2].upper() if tag == 'ONS' else seg[-1]}")   # ONS 는 경로 끝이 데이터셋(lms)
                node = _node(fn(key), desc, src)
                if node:
                    out.setdefault(_CC_OF[name], {})[name] = node
                    log(f"[{tag}] {name}: {node['value']} ({node['period']}) +{len(node['history'])}점")
                else:
                    log(f"[{tag}] {name}: 관측치 없음")
            except Exception as e:
                log(f"[{tag}] {name} 실패: {e}")
    return out


def _demo():
    assert _month_key("2026-06") == "2026-06-01"
    assert _month_key("2026-06-01") == "2026-06-01"
    n = _node([("2026-05", 1.2), ("2026-06", 1.0)], "d", "s")
    assert n["value"] == 1.0 and n["period"] == "2026-06-01" and len(n["history"]) == 2
    assert _node([], "d", "s") is None
    assert set(_CC_OF) == set(ECB_SERIES) | set(OECD_SERIES) | set(ONS_SERIES) | set(BOJ_SERIES)
    assert _ons_period("2026 MAY-JUL") == "2026-07"
    assert _ons_period("2025 NOV-JAN") == "2026-01"
    assert _ons_period("2026 JUN") == "2026-06"
    print("intl_sources self-check OK")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if "--demo" in sys.argv:
        _demo()
    else:
        print(json.dumps({cc: {k: {kk: vv for kk, vv in v.items() if kk != "history"}
                               for k, v in ind.items()}
                          for cc, ind in fetch_all().items()}, ensure_ascii=False, indent=1))
