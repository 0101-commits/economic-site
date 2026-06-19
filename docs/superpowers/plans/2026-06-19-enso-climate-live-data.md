# Live ENSO Climate Data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive the static 엘니뇨·라니냐 impact card from live NOAA ONI/Niño 3.4 observations (+ best-effort JMA), keeping the scenario library and disclaimer.

**Architecture:** New isolated Python module `scripts/fetch_climate.py` (pure parsers + a dependency-injected `fetch_enso()` orchestrator) is called by `scripts/fetch_data.py` on daily runs and merged under a new `data.json.climate.enso` key. `index.html` reads that block to auto-select the ENSO phase, render a live headline sentence + strength badges, and degrade gracefully when data is missing/stale. ECMWF stays a reference link.

**Tech Stack:** Python 3 stdlib (`urllib.request`, `re`), pytest (dev-only, local), vanilla inline JS + Chart.js (existing). No build step, no new runtime dependency, no CDN.

## Global Constraints

- `data.json` is **bot-owned** — written only by the pipeline (`fetch_data.py`), never hand-edited or committed manually. Verify by inspecting the working tree before any commit.
- **CSP:** no `eval`, no Tailwind/CDN re-add. Inline JS only.
- **Stale-endpoint ban:** never use `detrend.nino34.ascii.txt` (frozen 2019) or `wksst8110.for` (frozen ~2021). Current files only: `oni.ascii.txt`, `ersst5.nino.mth.91-20.ascii`, `wksst9120.for`.
- **Never fabricate a value.** On fetch/parse failure, degrade (stale flag / last-known / fall back to static tool) — never show an invented number.
- **Preserve-on-failure:** a single source failing must not blank the others; total failure preserves the previous `data.json.climate` block.
- **Cadence:** climate fetch runs on **daily** pipeline runs only, not every-10-min runs.
- **Branch/ship:** all work on `feat/enso-climate-live-data`; ships via **PR**, not direct push to `main`.
- **Commits:** Conventional Commits; every commit ends with the trailer
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Verified reference values (2026-06-19, for test fixtures & smoke checks):** ONI `MAM 2026 = +0.48`; monthly Niño3.4 `2026-05 = +0.82`; weekly Niño3.4 `2026-06-10 = +1.5` (prev week `+1.3`). Current phase = `neutral`, trend = `warming`.

---

### Task 1: `fetch_climate.py` scaffold + ONI parser

**Files:**
- Create: `scripts/fetch_climate.py`
- Test: `scripts/tests/test_fetch_climate.py`

**Interfaces:**
- Produces: `parse_oni(text: str) -> {"value": float, "season": str, "year": int}`; module constants `ONI_URL`, `NINO34_MTH_URL`, `NINO34_WK_URL`, `JMA_URL`; `_http_get(url, timeout=20) -> str`; `_MONTHS` dict.

- [ ] **Step 1: Write the failing test**

```python
# scripts/tests/test_fetch_climate.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fetch_climate as fc

ONI_FIX = """ SEAS  YR   TOTAL   ANOM
  DJF 2026  26.13  -0.37
  JFM 2026  26.58  -0.14
  FMA 2026  27.30   0.13
  MAM 2026  28.06   0.48
"""

def test_parse_oni_last_row():
    assert fc.parse_oni(ONI_FIX) == {"value": 0.48, "season": "MAM", "year": 2026}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest scripts/tests/test_fetch_climate.py::test_parse_oni_last_row -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fetch_climate'` (or `AttributeError: parse_oni`). If pytest is missing: `pip install pytest` first.

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest scripts/tests/test_fetch_climate.py::test_parse_oni_last_row -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_climate.py scripts/tests/test_fetch_climate.py
git commit -m "feat: add fetch_climate scaffold + ONI parser

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Monthly + weekly Niño 3.4 parsers

**Files:**
- Modify: `scripts/fetch_climate.py`
- Test: `scripts/tests/test_fetch_climate.py`

**Interfaces:**
- Consumes: `_MONTHS`.
- Produces: `parse_nino34_monthly(text) -> {"value","year","mon"}`; `parse_nino34_weekly(text) -> {"value","weekEnding","prevValue"}`; `_wk_date(token) -> "YYYY-MM-DD"`.

- [ ] **Step 1: Write the failing tests**

```python
# append to scripts/tests/test_fetch_climate.py
MTH_FIX = """ YR   MON  NINO1+2  ANOM   NINO3    ANOM   NINO4    ANOM   NINO3.4  ANOM
1950   1   23.01   -1.55   23.56   -2.10   26.94   -1.38   24.55   -1.99
2026   4   26.85    1.31   28.01    0.43   29.44    0.81   28.11    0.29
2026   5   26.23    1.81   28.30    1.05   29.98    1.07   28.75    0.82
"""

# 음수 SSTA 가 SST 에 붙는 고정폭 포맷(26.6-0.2) 포함
WK_FIX = """ Weekly SST data starts week centered on 2Sept1981

                Nino1+2      Nino3        Nino34        Nino4
 Week          SST SSTA     SST SSTA     SST SSTA     SST SSTA
 27JAN2021     24.6-0.4     25.7-0.2     25.9-0.7     27.1-1.1
 03JUN2026     26.3 2.6     28.4 1.5     29.0 1.3     30.0 1.1
 10JUN2026     26.1 2.7     28.3 1.6     29.2 1.5     30.1 1.3
"""

def test_parse_nino34_monthly_last_row():
    assert fc.parse_nino34_monthly(MTH_FIX) == {"value": 0.82, "year": 2026, "mon": 5}

def test_parse_nino34_weekly_last_row_and_prev():
    out = fc.parse_nino34_weekly(WK_FIX)
    assert out["value"] == 1.5
    assert out["weekEnding"] == "2026-06-10"
    assert out["prevValue"] == 1.3

def test_parse_nino34_weekly_handles_glued_negative():
    # 첫 데이터행(27JAN2021)만 주면 Nino34 SSTA = -0.7
    one = "\n".join(WK_FIX.splitlines()[:5])
    assert fc.parse_nino34_weekly(one)["value"] == -0.7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest scripts/tests/test_fetch_climate.py -k nino34 -v`
Expected: FAIL — `AttributeError: module 'fetch_climate' has no attribute 'parse_nino34_monthly'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to scripts/fetch_climate.py

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest scripts/tests/test_fetch_climate.py -k nino34 -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_climate.py scripts/tests/test_fetch_climate.py
git commit -m "feat: add monthly + weekly Niño3.4 parsers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Phase / strength / trend derivation

**Files:**
- Modify: `scripts/fetch_climate.py`
- Test: `scripts/tests/test_fetch_climate.py`

**Interfaces:**
- Produces: `derive_phase(oni_value: float) -> str` (`elnino`|`lanina`|`neutral`); `derive_strength(oni_value: float) -> str` (`weak`|`moderate`|`strong`|`very_strong`|`neutral`); `derive_trend(prev: float|None, last: float, eps=0.1) -> str` (`warming`|`cooling`|`steady`).

- [ ] **Step 1: Write the failing tests**

```python
# append to scripts/tests/test_fetch_climate.py
def test_derive_phase_thresholds():
    assert fc.derive_phase(0.48) == "neutral"
    assert fc.derive_phase(0.5) == "elnino"
    assert fc.derive_phase(-0.5) == "lanina"

def test_derive_strength_bands():
    assert fc.derive_strength(0.48) == "neutral"
    assert fc.derive_strength(0.8) == "weak"
    assert fc.derive_strength(1.2) == "moderate"
    assert fc.derive_strength(1.7) == "strong"
    assert fc.derive_strength(-2.1) == "very_strong"

def test_derive_trend():
    assert fc.derive_trend(1.3, 1.5) == "warming"
    assert fc.derive_trend(1.5, 1.3) == "cooling"
    assert fc.derive_trend(1.50, 1.52) == "steady"
    assert fc.derive_trend(None, 1.5) == "steady"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest scripts/tests/test_fetch_climate.py -k derive -v`
Expected: FAIL — `AttributeError: ... 'derive_phase'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to scripts/fetch_climate.py

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest scripts/tests/test_fetch_climate.py -k derive -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_climate.py scripts/tests/test_fetch_climate.py
git commit -m "feat: add ENSO phase/strength/trend derivation

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: JMA NINO.3 best-effort parser

**Files:**
- Modify: `scripts/fetch_climate.py`
- Test: `scripts/tests/test_fetch_climate.py`

**Interfaces:**
- Produces: `parse_jma_nino3(text: str) -> {"value": float, "asOf": "YYYY-MM"} | None`.

> **Note:** JMA's exact data URL/format is unconfirmed (the TCC monitoring page is a nav hub). This parser is intentionally tolerant: it finds the last `YYYY MM value` row and returns `None` on anything unexpected. During implementation, confirm the real file behind the TCC page; if no clean file exists, leave `JMA_URL` as-is — `fetch_enso()` will degrade JMA to `null` (like ECMWF) without failing.

- [ ] **Step 1: Write the failing tests**

```python
# append to scripts/tests/test_fetch_climate.py
JMA_FIX = """# JMA NINO.3 SST anomaly (deg C)
2026 03 0.7
2026 04 0.8
2026 05 0.9
"""

def test_parse_jma_nino3_ok():
    assert fc.parse_jma_nino3(JMA_FIX) == {"value": 0.9, "asOf": "2026-05"}

def test_parse_jma_nino3_garbage_returns_none():
    assert fc.parse_jma_nino3("<html>unexpected</html>") is None
    assert fc.parse_jma_nino3("") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest scripts/tests/test_fetch_climate.py -k jma -v`
Expected: FAIL — `AttributeError: ... 'parse_jma_nino3'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to scripts/fetch_climate.py

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest scripts/tests/test_fetch_climate.py -k jma -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_climate.py scripts/tests/test_fetch_climate.py
git commit -m "feat: add best-effort JMA NINO.3 parser

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `fetch_enso()` orchestrator (degradation + None)

**Files:**
- Modify: `scripts/fetch_climate.py`
- Test: `scripts/tests/test_fetch_climate.py`

**Interfaces:**
- Consumes: all parsers + derivations + `_http_get`.
- Produces: `fetch_enso(get=_http_get) -> dict | None` returning the `enso` block matching the spec schema (keys: `oni`, `nino34_monthly`, `nino34_weekly`, `jma_nino3`, `phase`, `strength`, `trend`, `stale`, `sources`). `get` is injectable for tests.

- [ ] **Step 1: Write the failing tests**

```python
# append to scripts/tests/test_fetch_climate.py
def _fake_all_ok(url):
    return {fc.ONI_URL: ONI_FIX, fc.NINO34_MTH_URL: MTH_FIX,
            fc.NINO34_WK_URL: WK_FIX, fc.JMA_URL: JMA_FIX}[url]

def test_fetch_enso_all_ok():
    e = fc.fetch_enso(get=_fake_all_ok)
    assert e["oni"]["value"] == 0.48
    assert e["phase"] == "neutral"
    assert e["strength"] == "neutral"
    assert e["nino34_weekly"]["value"] == 1.5
    assert e["trend"] == "warming"
    assert e["jma_nino3"]["value"] == 0.9
    assert e["stale"]["oni"] is False

def test_fetch_enso_oni_fails_others_survive():
    def g(url):
        if url == fc.ONI_URL:
            raise RuntimeError("boom")
        return _fake_all_ok(url)
    e = fc.fetch_enso(get=g)
    assert e is not None
    assert e["stale"]["oni"] is True
    assert "oni" not in e            # 실패 소스는 값 미기록
    assert e["nino34_weekly"]["value"] == 1.5  # 다른 소스 생존

def test_fetch_enso_total_failure_returns_none():
    def g(url):
        raise RuntimeError("network down")
    assert fc.fetch_enso(get=g) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest scripts/tests/test_fetch_climate.py -k fetch_enso -v`
Expected: FAIL — `AttributeError: ... 'fetch_enso'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to scripts/fetch_climate.py

def fetch_enso(get=_http_get):
    """ENSO 블록 생성. 소스별 독립 try/except — 부분 실패는 stale 플래그로 표시하고
    다른 소스는 살린다. 모든 소스 실패 시 None(호출측이 직전값 보존)."""
    enso = {"phase": "neutral", "strength": "neutral", "trend": "steady",
            "stale": {}, "sources": {}}
    ok = False

    try:
        o = parse_oni(get(ONI_URL))
        enso["oni"] = {"value": o["value"], "season": o["season"],
                       "year": o["year"], "asOf": f'{o["season"]} {o["year"]}'}
        enso["sources"]["oni"] = ONI_URL
        enso["stale"]["oni"] = False
        enso["phase"] = derive_phase(o["value"])
        enso["strength"] = derive_strength(o["value"])
        ok = True
    except Exception:
        enso["stale"]["oni"] = True

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest scripts/tests/test_fetch_climate.py -v`
Expected: PASS (all tests across Tasks 1–5)

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_climate.py scripts/tests/test_fetch_climate.py
git commit -m "feat: add fetch_enso orchestrator with per-source degradation

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Wire into `fetch_data.py` + live smoke test + optional WARN

**Files:**
- Modify: `scripts/fetch_data.py` (locate insertion point in Step 1)
- Modify: `scripts/validate_data.py` (optional WARN, Step 6)

**Interfaces:**
- Consumes: `fetch_climate.fetch_enso`.
- Produces: `data.json.climate = {"enso": <fetch_enso output>}` on daily runs; previous block preserved on `None`.

- [ ] **Step 1: Locate the data-assembly + write point**

Run: `grep -n 'json.dump' scripts/fetch_data.py` and `grep -n '"news"\|"sentiment"\|"diagnostics"' scripts/fetch_data.py`
Expected: find where the final top-level `data` dict (containing keys like `news`, `sentiment`, `diagnostics`) is assembled and written via `json.dump(..., "data.json", ...)`. Read ~40 lines around the write site to identify the `data` variable name and the daily-run flag (look for `AV_FETCH_FULL` / the daily-cron gate near line ~1749–1753).

- [ ] **Step 2: Add the import**

At the top of `scripts/fetch_data.py`, with the other local imports, add:

```python
import fetch_climate
```

- [ ] **Step 3: Merge climate into the data dict (daily runs only, preserve-on-failure)**

Immediately **before** the `json.dump(data, ...)` write of `data.json` (the variable name confirmed in Step 1 — shown here as `data`), insert:

```python
# 🌊 ENSO(엘니뇨·라니냐) 실측 — 일일 런에서만 갱신(과호출 방지). 실패 시 직전 블록 보존.
try:
    _is_daily = os.environ.get("AV_FETCH_FULL", "").strip() in ("1", "true", "yes")
    if _is_daily:
        _enso = fetch_climate.fetch_enso()
        if _enso is not None:
            data["climate"] = {"enso": _enso}
        # _enso is None → 기존 data["climate"] 유지(아래 보존 로직)
    # 비일일 런 또는 미수집 시: 직전 data.json 의 climate 를 보존
    if "climate" not in data:
        try:
            with open("data.json", encoding="utf-8") as _f:
                _prev = json.load(_f)
            if isinstance(_prev.get("climate"), dict):
                data["climate"] = _prev["climate"]
        except (OSError, ValueError):
            pass
except Exception as _e:
    print(f"[climate] skipped: {_e}")
```

> If the daily-run flag identified in Step 1 differs from `AV_FETCH_FULL`, use that flag instead. The key behaviors: fetch only on daily runs, never blank a prior `climate` block.

- [ ] **Step 4: Local smoke test against live NOAA**

Run from repo root:
`python -c "import sys; sys.path.insert(0,'scripts'); import json, fetch_climate as f; print(json.dumps(f.fetch_enso(), ensure_ascii=False, indent=2))"`
Expected: real JSON with `oni.value` ≈ `0.48` (or current), `nino34_weekly.value` present, `phase`/`trend` set, `stale.oni == false`. Confirm no exception and no fabricated/`null` ONI.

- [ ] **Step 5: Verify the gate still passes with a climate block**

Create a throwaway augmented copy (do NOT commit it) and validate:
`python -c "import json; d=json.load(open('data.json',encoding='utf-8')); d['climate']={'enso':{'phase':'neutral'}}; json.dump(d,open('/tmp/aug.json','w',encoding='utf-8'))"`
then temporarily run `validate_data.py` against the real `data.json` (unchanged): `python scripts/validate_data.py`
Expected: `✅ data.json 검증 통과`. (Confirms the new key doesn't break the gate; `REQUIRED` ignores extra keys.)

- [ ] **Step 6: (Optional) Add a non-blocking staleness WARN**

In `scripts/validate_data.py`, inside the `warns` section (after the series checks, before `for w in warns:`), add:

```python
    # ENSO 실측 신선도 — 비차단 경고(배포는 막지 않음)
    enso = (d.get("climate") or {}).get("enso") or {}
    if enso and enso.get("stale", {}).get("oni") is True:
        warns.append("climate.enso.oni: 최신 ONI 수집 실패(직전값 사용 중)")
```

- [ ] **Step 7: Commit**

```bash
git add scripts/fetch_data.py scripts/validate_data.py
git commit -m "feat: merge live ENSO data into pipeline on daily runs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Frontend — live helpers, phase auto-select, headline banner

**Files:**
- Modify: `index.html` (JS near 8261–8393; `ensoCurrent` at 8323; `setEnsoScenario` 8338; `renderEnsoCard` 8342)

**Interfaces:**
- Consumes: global `_latestDataForIndicators` (holds `data.json`); existing `ENSO_SCENARIOS`, `renderEnsoCard()`.
- Produces: `ensoData()`, `ensoPhaseLabel()`, `ensoStrengthLabel()`, `ensoTrendLabel()`, `ensoLiveSentence()`; global `ensoUserPinned`.

- [ ] **Step 1: Read the target region**

Read `index.html` 8261–8393 to confirm current structure before editing.

- [ ] **Step 2: Add pure helpers + pin flag** (insert directly above `let ensoCurrent = 'elnino';` at 8323)

```javascript
// 🌊 실측 ENSO 바인딩 — data.json.climate.enso 를 읽어 카드를 구동한다.
let ensoUserPinned = false;  // 사용자가 탭을 직접 고르면 자동 국면 덮어쓰기 중단
function ensoData() {
  const d = _latestDataForIndicators;
  return (d && d.climate && d.climate.enso) ? d.climate.enso : null;
}
function ensoPhaseLabel(p)   { return ({elnino:'엘니뇨', lanina:'라니냐', neutral:'중립'})[p] || '중립'; }
function ensoStrengthLabel(s){ return ({weak:'약한', moderate:'중간', strong:'강한', very_strong:'매우 강한', neutral:''})[s] || ''; }
function ensoTrendLabel(t)   { return ({warming:'따뜻해지는 추세', cooling:'차가워지는 추세', steady:'안정적'})[t] || ''; }
function ensoLiveSentence(e) {
  if (!e || !e.oni || typeof e.oni.value !== 'number') return null;
  const o = e.oni, sgn = o.value >= 0 ? '+' : '';
  let s = `현재 ${o.asOf} 관측 기준 ONI는 ${sgn}${o.value.toFixed(2)}℃(${ensoPhaseLabel(e.phase)})`;
  if (e.nino34_weekly && typeof e.nino34_weekly.value === 'number') {
    const w = e.nino34_weekly, ws = w.value >= 0 ? '+' : '';
    s += `이며, 최근 주간 Niño 3.4는 ${ws}${w.value.toFixed(1)}℃로 ${ensoTrendLabel(e.trend)}입니다.`;
  } else { s += '입니다.'; }
  return s;
}
```

- [ ] **Step 3: Pin on user click** — in `setEnsoScenario` (8338), set the flag:

```javascript
function setEnsoScenario(key, btn) {
  if(ENSO_SCENARIOS[key]) ensoCurrent = key;
  ensoUserPinned = true;
  renderEnsoCard();
}
```

- [ ] **Step 4: Auto-select phase + render banner** — at the top of `renderEnsoCard()` body (right after the `if(!bodyEl) return;` guard at 8345), insert:

```javascript
  const _live = ensoData();
  if (_live && !ensoUserPinned && ENSO_SCENARIOS[_live.phase]) ensoCurrent = _live.phase;
  const _sentence = _live ? ensoLiveSentence(_live) : null;
  const _liveBanner = _sentence ? `
    <div style="background:var(--c-card);border:1px solid var(--c-accent);border-radius:var(--r-sm);padding:9px 12px;margin-bottom:10px;font-size:12px;color:var(--c-txt);line-height:1.6;">
      <span style="font-size:10px;font-weight:700;color:#fff;background:var(--c-accent);border-radius:var(--r-full);padding:1px 8px;margin-right:6px;">실측</span>${_sentence}
    </div>` : '';
```

- [ ] **Step 5: Prepend the banner** — change the `bodyEl.innerHTML = \`` assignment at 8374 so the template starts with the banner. Replace the opening:

```javascript
  bodyEl.innerHTML = `
    <div style="background:var(--c-bg);border:1px solid var(--c-border);border-left:3px solid ${s.accent};border-radius:var(--r-sm);padding:10px 12px;margin-bottom:12px;">
```

with:

```javascript
  bodyEl.innerHTML = _liveBanner + `
    <div style="background:var(--c-bg);border:1px solid var(--c-border);border-left:3px solid ${s.accent};border-radius:var(--r-sm);padding:10px 12px;margin-bottom:12px;">
```

- [ ] **Step 6: Verify pure helpers in the browser console**

Serve: `python -m http.server 8000` → open `http://localhost:8000/` → DevTools console:

```javascript
ensoLiveSentence({oni:{value:0.48,asOf:'MAM 2026'},phase:'neutral',trend:'warming',nino34_weekly:{value:1.5}})
// Expected exactly:
// "현재 MAM 2026 관측 기준 ONI는 +0.48℃(중립)이며, 최근 주간 Niño 3.4는 +1.5℃로 따뜻해지는 추세입니다."
ensoLiveSentence(null)            // Expected: null
ensoLiveSentence({phase:'elnino'})// Expected: null  (no oni)
```

- [ ] **Step 7: Verify auto-select with injected data**

In the console, simulate live data and re-render (no file change, no commit):

```javascript
_latestDataForIndicators.climate = {enso:{phase:'lanina',strength:'moderate',trend:'cooling',
  oni:{value:-1.1,asOf:'MAM 2026'}, nino34_weekly:{value:-1.2}, stale:{oni:false}}};
ensoUserPinned = false; renderEnsoCard();
// Expected: 라니냐 tab active; 실측 banner shows ONI -1.10℃(라니냐) … 차가워지는 추세.
// Then click the 엘니뇨 tab → banner persists, tab switches, and stays (pinned).
```

- [ ] **Step 8: Commit**

```bash
git add index.html
git commit -m "feat: bind ENSO card to live data — auto phase + headline

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Frontend — strength badges, degradation, links, polish

**Files:**
- Modify: `index.html` (section headers 8385/8389; card HTML 2137–2141)

**Interfaces:**
- Consumes: `ensoData()`, `ensoStrengthLabel()`, `ensoPhaseLabel()` (Task 7).

- [ ] **Step 1: Add a live "현재 강도" badge to the ① and ② section headers**

Replace the `① 원자재 …` header line at 8385:

```javascript
        <div style="font-size:11px;font-weight:700;color:var(--c-primary);letter-spacing:.04em;margin-bottom:2px;">① 원자재 수급·가격 변동성</div>
```

with (adds a badge only when live data exists):

```javascript
        <div style="font-size:11px;font-weight:700;color:var(--c-primary);letter-spacing:.04em;margin-bottom:2px;">① 원자재 수급·가격 변동성${_live ? ` <span style="font-weight:600;color:var(--c-txt-dim);">· 현재 강도: ${ensoStrengthLabel(_live.strength) || ensoPhaseLabel(_live.phase)}</span>` : ''}</div>
```

Apply the same `${_live ? …}` suffix to the `② 연동 주가·산업 (국내)` header at 8389.

- [ ] **Step 2: Verify the degradation path (no climate data)**

Serve locally; in console:

```javascript
delete _latestDataForIndicators.climate; ensoUserPinned = false; renderEnsoCard();
// Expected: NO 실측 banner, NO 현재 강도 badge; card renders exactly as the original static tool. No errors.
```

- [ ] **Step 3: Verify the stale path (last-known + flag)**

The banner already renders last-known values whenever `oni` is present; confirm a stale flag shows when `stale.oni` is true. In console:

```javascript
_latestDataForIndicators.climate = {enso:{phase:'neutral',strength:'neutral',trend:'steady',
  oni:{value:0.48,asOf:'MAM 2026'}, stale:{oni:true}}};
ensoUserPinned = false; renderEnsoCard();
// Expected: banner still shows the last-known ONI (never blank, never invented).
```

> The stale flag chip is optional polish; the hard requirement (never blank / never fabricate) is satisfied because `ensoLiveSentence` only renders real numbers and returns `null` otherwise.

- [ ] **Step 4: Add NOAA-weekly + JMA reference links** — in the disclaimer block (2139–2140), after the 기상청 link, append:

```html
            · <a href="https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for" target="_blank" rel="noopener noreferrer" style="color:var(--c-primary);">NOAA 주간 Niño 3.4</a>
            · <a href="https://ds.data.jma.go.jp/tcc/tcc/products/elnino/" target="_blank" rel="noopener noreferrer" style="color:var(--c-primary);">JMA El Niño</a>
```

- [ ] **Step 5: Verify links resolve**

Run: `python -c "import urllib.request as u; [print(x, u.urlopen(u.Request(x, headers={'User-Agent':'x'}), timeout=15).status) for x in ['https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for','https://ds.data.jma.go.jp/tcc/tcc/products/elnino/']]"`
Expected: each prints `200`. (If JMA ≠ 200, point the link at the working TCC page found during Task 4.)

- [ ] **Step 6: Final regression — full local pass**

- `python -m pytest scripts/tests/test_fetch_climate.py -v` → all PASS.
- `python scripts/validate_data.py` → `✅`.
- Browser: commodity page loads, ENSO card renders live banner + badges, all three console scenarios (live / degrade / stale) behave as documented, no console errors.

- [ ] **Step 7: Commit**

```bash
git add index.html
git commit -m "feat: ENSO strength badges, graceful degradation, source links

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Open PR (ship)

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/enso-climate-live-data
```

- [ ] **Step 2: Open the PR** (requires `gh auth` / write access to the repo)

```bash
gh pr create --base main --head feat/enso-climate-live-data \
  --title "feat: 미·유럽·일 기상청 실시간 데이터 연동 및 기후 영향 분석 동적 자산 매칭 기능 추가" \
  --body "Spec: docs/superpowers/specs/2026-06-19-enso-climate-live-data-design.md

NOAA-driven live ENSO (ONI/Niño3.4) + best-effort JMA; auto phase select, dynamic headline, strength badges, graceful degradation. ECMWF = reference link. data.json untouched (bot-owned). Deploy on merge.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 3: Report** the PR URL. Deploy happens **on merge** (reviewer merges → GitHub Pages updates). Do not merge automatically.

---

## Self-Review

**Spec coverage:**
- Data collection NOAA ONI/Niño3.4 → Tasks 1,2,5,6 ✓ · JMA best-effort → Task 4 ✓ · ECMWF link-only → Task 8 Step 4 ✓ · periodic/daily auto-update → Task 6 Step 3 ✓
- Phase auto-select ±0.5 → Task 3 + Task 7 Step 4 ✓ · dynamic headline text → Task 7 Step 2/4/5 ✓ · ①/② strength binding → Task 8 Step 1 ✓
- Source links active + add → Task 8 Step 4 (already-active links retained; new ones added) ✓ · font/load polish → Task 8 (badges lightweight; card already lazy-renders via buildCommodityPage) ✓
- Graceful degradation / never fabricate → Tasks 5,7,8 ✓ · validate_data.py gate → Task 6 Steps 5–6 ✓ · data.json bot-owned untouched → Global Constraints + Task 6 ✓
- Commit message + branch→PR ship → Task 9 ✓

**Placeholder scan:** No TBD/TODO. JMA URL is flagged as confirm-in-impl with a tolerant parser + degrade — an explicit, handled uncertainty, not a placeholder. The `fetch_data.py` insertion uses a `grep`-located anchor (file is 344KB) with complete insertion code given.

**Type consistency:** `fetch_enso()` keys (`oni`,`nino34_monthly`,`nino34_weekly`,`jma_nino3`,`phase`,`strength`,`trend`,`stale`,`sources`) match the frontend readers (`ensoData()`, `ensoLiveSentence`, badges) and the spec schema. `parse_nino34_weekly` returns `prevValue` consumed by `derive_trend`. Labels cover every enum value from `derive_phase`/`derive_strength`/`derive_trend`.
