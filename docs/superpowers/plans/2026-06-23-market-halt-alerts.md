# 시장중단 경보 (서킷브레이커·사이드카) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 한국 시장 서킷브레이커·사이드카 발동을 장중 자동 감지해 사이트 상단 경고 배너 + 국내증시 탭 배지 + 발동 이력표로 표시하고, 신규 발동/해제 시 카카오톡으로 알린다.

**Architecture:** 새 모듈 `scripts/market_halts.py` 가 감지 로직(2겹: 지수 등락률 기반 CB 추정 + 뉴스 best-effort 스크레이프)을 담는다. `fetch_data.py` 가 빌드 말미에 이를 호출해 `data.json.marketHalts` 를 만들고, `index.html` 이 이를 읽어 배너/배지/이력을 렌더한다. `check_halts.py` 가 `fetch-data.yml` 스텝에서 신규/해제만 카카오톡으로 보낸다(기존 `send_kakao_digest` 재사용).

**Tech Stack:** Python 3.11 (requests), 정적 `index.html`(인라인 CSS/JS, Chart.js 불필요), GitHub Actions, 기존 KakaoTalk REST 연동.

## Global Constraints

- **No build step.** `index.html` 은 단일 파일(~18000줄) 인라인 CSS/JS. 직접 편집, 푸시 즉시 라이브.
- **CSP 준수.** 인라인 `<script>`/`onclick` 만(기존 패턴과 동일). `eval` 금지, 외부 CDN/스타일 금지, **Tailwind CDN 재추가 금지**.
- **API 키 하드코딩 금지** (공개 저장소). 모든 키는 GitHub Secrets. 가드 패턴 `if not KEY: skip/return`.
- **`data.json` 은 봇 소유** — `fetch_data.py` 만 작성. 손수 편집 금지.
- **`validate_data.py` 는 하드 게이트** — 치명적 결손만 `errs`(차단), 품질 신호는 `warns`(비차단).
- **부분 실패 시 직전값 보존** — 감지 실패해도 이전 `marketHalts` 유지. **날조 금지**(미검증 데이터로 가짜 발동 만들지 않음).
- **시간대 = KST** (`datetime.timezone(timedelta(hours=9))`).
- **카카오 발송은 best-effort** — 실패해도 데이터 파이프라인을 막지 않는다.
- 사건 `id` 규칙: `"{type}-{market}-{YYYYMMDD}"` (하루·시장·종류당 1건). `type ∈ {circuit, sidecar}`, `market ∈ {KOSPI, KOSDAQ}`.

---

## File Structure

| 파일 | 책임 | 작업 |
|------|------|------|
| `scripts/market_halts.py` | 감지 로직(순수+스크레이프). 독립 import/테스트 가능. | 신규 |
| `scripts/test_market_halts.py` | `market_halts` 단위 테스트(pytest 없이 `python` 실행). | 신규 |
| `scripts/check_halts.py` | `marketHalts.active` → 신규/해제 카카오톡 발송. | 신규 |
| `halts_state.json` | 발송 이력(도배방지). 워크플로가 커밋해 런 간 보존. | 신규(런타임 생성) |
| `scripts/fetch_data.py` | 빌드 말미에 `detect_market_halts` 호출 → `d["marketHalts"]`. | 수정(~7160) |
| `scripts/validate_data.py` | `marketHalts` 형태 비차단 검증. | 수정(~119) |
| `.github/workflows/fetch-data.yml` | `check_halts.py` 스텝 + 커밋에 `halts_state.json` 포함. | 수정 |
| `.github/workflows/halts-test.yml` | 수동 테스트 발송(workflow_dispatch). | 신규 |
| `index.html` | 상단 배너 + 메뉴 배지 + 이력표 + `renderMarketHalts()`. | 수정(여러 곳) |
| `CLAUDE.md` | 새 스크립트/스키마/워크플로 문서화. | 수정 |

**의존:** Task 2·4·6 은 Task 1 의 스키마에 의존. Task 5 는 Task 4 에 의존. Task 7 은 전부 이후.

---

## Task 1: 감지 모듈 `market_halts.py` + 단위 테스트

**Files:**
- Create: `scripts/market_halts.py`
- Test: `scripts/test_market_halts.py`

**Interfaces:**
- Produces:
  - `detect_market_halts(data: dict, prev: dict, now: datetime|None=None) -> dict` — 반환 `{"active": list, "history": list, "asOf": str, "stale": bool}`. `data["indices"][m]["change"]` = 전일比 %, `prev["marketHalts"]` = 직전 상태.
  - `cb_from_index(market: str, change_pct: float|None, now: datetime) -> dict|None`
  - `scrape_market_halts(now: datetime) -> list[dict]`
  - 사건 dict 필드: `id, type, market, stage, direction, reason, triggeredAt, resumeAt, endOfDay, source` (+ 뉴스원은 `approx: true`).

- [ ] **Step 1: 단위 테스트 먼저 작성** — `scripts/test_market_halts.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""market_halts 단위 테스트 — pytest 없이 직접 실행.
실행: python scripts/test_market_halts.py  (성공 시 'ALL PASS')."""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 스크레이프(네트워크) 비활성 — 1겹(지수) 로직만 결정적으로 테스트
os.environ.pop("NAVER_CLIENT_ID", None)
os.environ.pop("NAVER_CLIENT_SECRET", None)
import market_halts as mh

KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime(2026, 6, 23, 14, 31, tzinfo=KST)


def test_no_halt_when_small_move():
    d = {"indices": {"KOSPI": {"price": 7600, "change": -3.0},
                     "KOSDAQ": {"price": 1140, "change": -2.0}}}
    out = mh.detect_market_halts(d, {}, now=NOW)
    assert out["active"] == [], out
    assert out["history"] == []


def test_cb_stage1_on_minus8():
    d = {"indices": {"KOSPI": {"price": 6992, "change": -8.1},
                     "KOSDAQ": {"price": 1140, "change": -1.0}}}
    out = mh.detect_market_halts(d, {}, now=NOW)
    assert len(out["active"]) == 1, out
    ev = out["active"][0]
    assert ev["type"] == "circuit" and ev["market"] == "KOSPI" and ev["stage"] == 1
    assert ev["id"] == "circuit-KOSPI-20260623"
    assert ev["resumeAt"] == datetime.datetime(2026, 6, 23, 15, 1, tzinfo=KST).isoformat()
    assert ev["endOfDay"] is False


def test_cb_stage3_is_end_of_day():
    d = {"indices": {"KOSPI": {"price": 6080, "change": -20.5}}}
    out = mh.detect_market_halts(d, {}, now=NOW)
    ev = out["active"][0]
    assert ev["stage"] == 3 and ev["endOfDay"] is True and ev["resumeAt"] is None


def test_carry_forward_then_resolve():
    d1 = {"indices": {"KOSPI": {"change": -8.2}}}
    s1 = mh.detect_market_halts(d1, {}, now=NOW)                       # 발동(14:31, resume 15:01)
    assert len(s1["active"]) == 1
    later = NOW + datetime.timedelta(minutes=10)                       # 14:41 등락 회복(-5%)
    s2 = mh.detect_market_halts({"indices": {"KOSPI": {"change": -5.0}}},
                                {"marketHalts": s1}, now=later)
    assert len(s2["active"]) == 1, s2                                  # resume 전 → 유지
    assert s2["active"][0]["triggeredAt"] == s1["active"][0]["triggeredAt"]  # 시작시각 고정
    after = datetime.datetime(2026, 6, 23, 15, 5, tzinfo=KST)          # 15:05 resume 경과
    s3 = mh.detect_market_halts({"indices": {"KOSPI": {"change": -5.0}}},
                                {"marketHalts": s2}, now=after)
    assert s3["active"] == [], s3                                      # 해제
    assert len(s3["history"]) == 1 and s3["history"][0].get("resolvedAt")


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("ALL PASS")


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: 테스트 실행 → 실패 확인 (모듈 없음)**

Run: `python scripts/test_market_halts.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'market_halts'`

- [ ] **Step 3: 감지 모듈 작성** — `scripts/market_halts.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""시장중단(서킷브레이커·사이드카) 감지 — fetch_data.py 가 호출해 data.json.marketHalts 생성.

감지 2겹(정직성 — 무료 실시간 공식 피드 없어 best-effort):
  1겹(확실·무의존): 이미 수집한 KOSPI/KOSDAQ 지수 등락률(전일比 %)로 서킷브레이커 단계 추정.
       임계 -8/-15/-20% = 1/2/3단계 (한국 CB 는 하락 전용).
  2겹(best-effort): NAVER 뉴스에서 '서킷브레이커/사이드카 발동' 헤드라인 감지 → CB 확정 +
       사이드카(선물 ±5/6% — 1겹으로 못 잡음) 포착. NAVER 키 없으면 건너뜀(날조 금지).

직전 data.json 의 active 를 이월: 파이프라인이 10분 주기라 짧은 발동을 놓치지 않도록
resumeAt 전까지 active 유지, 지나면 history 로 이동.

독립 import/테스트 가능(거대 fetch_data.py 를 끌어오지 않음)."""
import os
import re
import datetime

KST = datetime.timezone(datetime.timedelta(hours=9))

# (단계, 임계 등락률%, 매매중단분, 동시호가분, 당일종료)
CB_RULES = [
    (3, -20.0, 0, 0, True),
    (2, -15.0, 20, 10, False),
    (1, -8.0, 20, 10, False),
]
SIDECAR_HALT_MIN = 5
SRC_RANK = {"krx": 3, "naver": 2, "index": 2, "news": 1}


def _log(msg):
    print(msg)


def _halt_id(typ, market, day):
    return f"{typ}-{market}-{day}"


def cb_from_index(market, change_pct, now):
    """지수 등락률(전일比 %) → 서킷브레이커 사건 dict 또는 None. 가장 심각한 충족 단계."""
    if change_pct is None:
        return None
    for stage, thr, halt_min, auc_min, eod in CB_RULES:
        if change_pct <= thr:
            resume = None if eod else now + datetime.timedelta(minutes=halt_min + auc_min)
            return {
                "id": _halt_id("circuit", market, now.strftime("%Y%m%d")),
                "type": "circuit", "market": market, "stage": stage, "direction": "down",
                "reason": f"{market} 지수 전일比 {change_pct:.2f}%",
                "triggeredAt": now.isoformat(),
                "resumeAt": resume.isoformat() if resume else None,
                "endOfDay": eod, "source": "index",
            }
    return None


def scrape_market_halts(now):
    """best-effort: NAVER 뉴스에서 최근 40분 내 '발동' 헤드라인으로 CB/사이드카 감지.
    오탐 방지: 최근성 + 키워드 동시 요구. NAVER_CLIENT_ID/SECRET 없으면 [](날조 금지).
    뉴스원은 정확한 시각/사유 불명 → approx=True, 시각은 기사 발행시각 근사."""
    cid = os.environ.get("NAVER_CLIENT_ID", "").strip()
    csec = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if not cid or not csec:
        return []
    try:
        import requests
        from urllib.parse import quote
    except Exception:
        return []
    out = []
    for typ, kw in (("circuit", "서킷브레이커 발동"), ("sidecar", "사이드카 발동")):
        try:
            r = requests.get(
                "https://openapi.naver.com/v1/search/news.json"
                f"?query={quote(kw)}&display=10&sort=date",
                headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec},
                timeout=12)
            if r.status_code != 200:
                continue
            items = (r.json() or {}).get("items") or []
        except Exception:
            continue
        for it in items:
            text = re.sub(r"<[^>]+>", "",
                          (it.get("title") or "") + " " + (it.get("description") or ""))
            if "발동" not in text:
                continue
            try:
                pub = datetime.datetime.strptime(it.get("pubDate", ""), "%a, %d %b %Y %H:%M:%S %z")
            except (ValueError, TypeError):
                continue
            if (now - pub).total_seconds() > 2400:        # 40분 초과 = 과거 기사
                continue
            market = "KOSDAQ" if "코스닥" in text else "KOSPI"
            down = any(w in text for w in ("하락", "급락", "폭락", "매도"))
            out.append({
                "id": _halt_id(typ, market, now.strftime("%Y%m%d")),
                "type": typ, "market": market,
                "stage": (1 if typ == "circuit" else None),
                "direction": "down" if down else "up",
                "reason": text[:60].strip(),
                "triggeredAt": pub.isoformat(),
                "resumeAt": (pub + datetime.timedelta(
                    minutes=(SIDECAR_HALT_MIN if typ == "sidecar" else 30))).isoformat(),
                "endOfDay": False, "source": "news", "approx": True,
            })
            break                                          # 종류별 1건이면 충분
    return out


def _merge(a, b):
    """같은 id 두 결과 병합 — 더 심각한 단계 + 신뢰도 높은 출처, 시작시각은 더 이른 값 고정,
    사유는 index(정확 %) 선호."""
    if a is None:
        return b
    if b is None:
        return a
    base = a if SRC_RANK.get(a.get("source"), 0) >= SRC_RANK.get(b.get("source"), 0) else b
    out = dict(base)
    out["stage"] = max(a.get("stage") or 0, b.get("stage") or 0) or base.get("stage")
    earliest = min((x for x in (a, b) if x.get("triggeredAt")),
                   key=lambda x: x["triggeredAt"], default=None)
    if earliest:
        out["triggeredAt"] = earliest["triggeredAt"]
        out["resumeAt"] = earliest.get("resumeAt")
        out["endOfDay"] = earliest.get("endOfDay", out.get("endOfDay"))
    for cand in (a, b):
        if cand.get("source") == "index" and cand.get("reason"):
            out["reason"] = cand["reason"]
    return out


def detect_market_halts(data, prev, now=None):
    """data(이번 빌드)+prev(직전 data.json) → marketHalts dict."""
    now = now or datetime.datetime.now(KST)
    prev_halts = (prev or {}).get("marketHalts") or {}
    prev_active = {h["id"]: h for h in prev_halts.get("active", [])
                   if isinstance(h, dict) and h.get("id")}
    history = [h for h in prev_halts.get("history", []) if isinstance(h, dict)]

    candidates = []
    indices = data.get("indices") or {}
    for market in ("KOSPI", "KOSDAQ"):
        ev = cb_from_index(market, (indices.get(market) or {}).get("change"), now)
        if ev:
            candidates.append(ev)
    try:
        candidates.extend(scrape_market_halts(now) or [])
    except Exception as e:
        _log(f"[halts] 스크레이프 실패(무시): {e}")

    by_id = {}
    for ev in candidates:
        by_id[ev["id"]] = _merge(by_id.get(ev["id"]), ev)

    # 직전 active 이월 — resumeAt 전이면 유지(스냅샷 사이 짧은 발동 보존)
    for hid, h in prev_active.items():
        if hid in by_id:
            by_id[hid] = _merge(by_id[hid], h)
            continue
        if h.get("endOfDay"):
            keep = h.get("triggeredAt", "")[:10] == now.strftime("%Y-%m-%d")
        else:
            try:
                keep = bool(h.get("resumeAt")) and datetime.datetime.fromisoformat(h["resumeAt"]) > now
            except (ValueError, TypeError):
                keep = False
        if keep:
            by_id[hid] = h

    active = sorted(by_id.values(), key=lambda x: x.get("triggeredAt", ""))
    active_ids = {h["id"] for h in active}

    # 직전 active 중 사라진 것 = 해제 → history(중복 갱신, 최신순 30건)
    for hid, h in prev_active.items():
        if hid not in active_ids:
            rec = dict(h)
            rec["resolvedAt"] = now.isoformat()
            history = [x for x in history if x.get("id") != hid]
            history.insert(0, rec)
    history = history[:30]

    return {"active": active, "history": history, "asOf": now.isoformat(), "stale": False}
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `python scripts/test_market_halts.py`
Expected: PASS — 4 줄 `✓ ...` 후 `ALL PASS`

- [ ] **Step 5: 커밋**

```bash
git add scripts/market_halts.py scripts/test_market_halts.py
git commit -m "feat: add market-halt detection module (circuit breaker/sidecar)"
```

---

## Task 2: `fetch_data.py` 에 감지 연결

**Files:**
- Modify: `scripts/fetch_data.py` (~7160, `__main__` 블록의 climate 처리 직후 / `output_path = "data.json"` 직전)

**Interfaces:**
- Consumes: `market_halts.detect_market_halts` (Task 1), 기존 `_load_prev_data` (line 4934), 빌드 결과 `d`.
- Produces: `d["marketHalts"]` (data.json 최상위 키).

- [ ] **Step 1: 감지 호출 삽입** — climate `except` 블록(`print(f"[climate] skipped: {_e}")`) 다음 줄이자 `output_path = "data.json"` 바로 앞에 추가:

```python
    # 🚨 시장중단(서킷브레이커·사이드카) 감지 — data.json.marketHalts 생성.
    # 디스크의 직전 data.json(아직 미갱신)을 읽어 active 를 이월. 실패해도 직전 블록 보존(날조 금지).
    try:
        import market_halts
        d["marketHalts"] = market_halts.detect_market_halts(d, _load_prev_data("data.json"))
        _mh = d["marketHalts"]
        log(f"[halts] active={len(_mh.get('active', []))} history={len(_mh.get('history', []))}")
    except Exception as _e:
        print(f"[halts] 감지 skipped: {_e}")
        _prev_mh = (_load_prev_data("data.json") or {}).get("marketHalts")
        if isinstance(_prev_mh, dict):
            d["marketHalts"] = _prev_mh
```

- [ ] **Step 2: 구문/연결 검증 (스모크)** — 기존 data.json 으로 import·호출이 깨지지 않는지만 확인(네트워크 키 없이):

```bash
python -c "import sys; sys.path.insert(0,'scripts'); import market_halts, json; d=json.load(open('data.json',encoding='utf-8')) if __import__('os').path.exists('data.json') else {'indices':{'KOSPI':{'change':-1.0}}}; print(market_halts.detect_market_halts(d, d).keys())"
```
Expected: `dict_keys(['active', 'history', 'asOf', 'stale'])` (에러 없음)

- [ ] **Step 3: 커밋**

```bash
git add scripts/fetch_data.py
git commit -m "feat: wire market-halt detection into fetch_data build"
```

---

## Task 3: `validate_data.py` 형태 검증 (비차단)

**Files:**
- Modify: `scripts/validate_data.py` (~119, `for w in warns:` 루프 직전)

**Interfaces:**
- Consumes: `d["marketHalts"]` (Task 1 스키마).

- [ ] **Step 1: 검증 추가** — `for w in warns:` (line 120) 바로 위에 삽입:

```python
    # 시장중단(서킷브레이커·사이드카) — 있으면 형태 점검(비차단 경고).
    # fetch_data.detect_market_halts 가 항상 생성하지만, 누락/형오류는 게이트가 아닌 경고로 남긴다.
    mh_block = d.get("marketHalts")
    if mh_block is not None:
        if not isinstance(mh_block, dict):
            warns.append(f"marketHalts: dict 예상, {type(mh_block).__name__}")
        else:
            for key in ("active", "history"):
                if not isinstance(mh_block.get(key), list):
                    warns.append(f"marketHalts.{key}: list 아님")
            for h in (mh_block.get("active") or []):
                if not (isinstance(h, dict) and h.get("id") and h.get("type") in ("circuit", "sidecar")):
                    warns.append(f"marketHalts.active 형식 오류: {h!r}")
                    break
```

- [ ] **Step 2: 실행 검증** — 현재 data.json 으로 통과(에러 0)하는지:

Run: `python scripts/validate_data.py`
Expected: `✅ data.json 검증 통과 ...` (exit 0). marketHalts 가 아직 없으면 검증은 조용히 건너뜀.

- [ ] **Step 3: 커밋**

```bash
git add scripts/validate_data.py
git commit -m "feat: validate marketHalts shape (non-blocking)"
```

---

## Task 4: 카카오 발송 `check_halts.py` + 테스트 모드

**Files:**
- Create: `scripts/check_halts.py`
- (런타임 생성) `halts_state.json`

**Interfaces:**
- Consumes: `data.json.marketHalts.active` (Task 1), 기존 `send_kakao_digest` 의 `refresh_access_token(rest, refresh)`, `get_friends(token)`, `_friends_enabled()`, `send_memo(token, msg, with_button=, uuids=)`.
- Produces: `halts_state.json` (사건 id → 발송 이력), 카카오 메시지.

- [ ] **Step 1: 작성** — `scripts/check_halts.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""시장중단(서킷브레이커·사이드카) 카카오톡 알림.

fetch_data.py 가 data.json.marketHalts.active 에 현재 발동 사건을 기록한다. 본 스크립트는
fetch-data.yml 에서 fetch_data.py 직후 실행되어, 직전 발송 이력(halts_state.json)과 비교해
'신규 발동' 과 '해제'만 카카오톡으로 보낸다.

도배 방지: 사건 id 당 발동 1회 + 해제 1회. 이력은 halts_state.json 에 남고 워크플로가
data.json 과 함께 커밋해 런 간 보존한다.

테스트 발송: GITHUB_EVENT_NAME=repository_dispatch 또는 HALTS_TEST=1 이면 가짜 사건 1건만
보내 경로를 검증하며 이력을 갱신하지 않는다.

필요 Secrets: KAKAO_REST_API_KEY, KAKAO_REFRESH_TOKEN (시황 다이제스트와 공용)."""
import os
import json
import datetime

import send_kakao_digest as kakao   # scripts/ 가 sys.path[0]

KST = datetime.timezone(datetime.timedelta(hours=9))
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA_PATH = os.path.join(ROOT, "data.json")
STATE_PATH = os.path.join(ROOT, "halts_state.json")
IS_TEST = (os.environ.get("GITHUB_EVENT_NAME") == "repository_dispatch"
           or os.environ.get("HALTS_TEST") == "1")

TYPE_KO = {"circuit": "서킷브레이커", "sidecar": "사이드카"}
DELAY_NOTICE = "※ 최대 15분 지연 가능 · 정확한 시각은 거래소/증권사 앱 확인"


def _now():
    return datetime.datetime.now(KST)


def _hm(iso):
    try:
        return datetime.datetime.fromisoformat(iso).astimezone(KST).strftime("%H:%M")
    except (ValueError, TypeError):
        return "-"


def _fire_msg(h):
    typ = TYPE_KO.get(h.get("type"), h.get("type"))
    stage = f" {h['stage']}단계" if h.get("type") == "circuit" and h.get("stage") else ""
    icon = "🔴" if h.get("type") == "circuit" else "🟠"
    lines = [f"{icon} [시장경보] {h.get('market', '')} {typ}{stage} 발동",
             f"사유: {h.get('reason', '-')}"]
    if h.get("endOfDay"):
        lines.append(f"매매중단 {_hm(h.get('triggeredAt'))} → 당일 장 종료")
    else:
        lines.append(f"매매중단 {_hm(h.get('triggeredAt'))} → 재개예정 {_hm(h.get('resumeAt'))}")
    lines.append(DELAY_NOTICE)
    return "\n".join(lines)


def _resolve_msg(h):
    typ = TYPE_KO.get(h.get("type"), h.get("type"))
    return (f"🟢 [시장경보 해제] {h.get('market', '')} {typ} — "
            f"{_now().strftime('%H:%M')} 거래 재개\n{DELAY_NOTICE}")


def _send_all(token, uuids, msg):
    kakao.send_memo(token, msg, with_button=True, uuids=uuids)


def main():
    now = _now()
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        print("[halts] data.json 없음/파싱 실패 — 종료")
        return
    halts = data.get("marketHalts") or {}
    active = [h for h in halts.get("active", []) if isinstance(h, dict) and h.get("id")]

    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()

    # 테스트 발송 — 가짜 사건으로 경로만 검증(이력 미갱신)
    if IS_TEST:
        if not rest_key or not refresh_token:
            print("::warning title=Kakao 미설정::KAKAO secrets 없음 — 테스트 발송 불가")
            return
        token = kakao.refresh_access_token(rest_key, refresh_token)
        uuids = [f["uuid"] for f in kakao.get_friends(token)] if kakao._friends_enabled() else []
        fake = {"type": "circuit", "market": "KOSPI", "stage": 1, "endOfDay": False,
                "reason": "테스트 — 지수 전일比 -8.0%", "triggeredAt": now.isoformat(),
                "resumeAt": (now + datetime.timedelta(minutes=30)).isoformat()}
        _send_all(token, uuids, "[테스트] " + _fire_msg(fake))
        print("[halts] 테스트 발송 완료 (이력 미갱신)")
        return

    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}

    active_ids = {h["id"] for h in active}
    new_events = [h for h in active if h["id"] not in state]
    resolved_ids = [hid for hid in state
                    if hid not in active_ids and not state[hid].get("resolvedSent")]

    if new_events or resolved_ids:
        if not rest_key or not refresh_token:
            print("::warning title=Kakao 미설정::KAKAO secrets 없음 — 발송 건너뜀")
        else:
            token = kakao.refresh_access_token(rest_key, refresh_token)
            uuids = [f["uuid"] for f in kakao.get_friends(token)] if kakao._friends_enabled() else []
            for h in new_events:
                _send_all(token, uuids, _fire_msg(h))
                state[h["id"]] = {"firedAt": now.isoformat(), "event": h, "resolvedSent": False}
                print(f"[halts] 발동 발송: {h['id']}")
            for hid in resolved_ids:
                h = state[hid].get("event") or {"id": hid}
                _send_all(token, uuids, _resolve_msg(h))
                state[hid]["resolvedSent"] = True
                state[hid]["resolvedAt"] = now.isoformat()
                print(f"[halts] 해제 발송: {hid}")
    else:
        print(f"[halts] 변동 없음 — active {len(active)}건")

    # 오래된 이력 정리 — 해제 완료 사건은 2일 후 제거
    cutoff = now - datetime.timedelta(days=2)
    cleaned = {}
    for hid, rec in state.items():
        if rec.get("resolvedSent"):
            try:
                if datetime.datetime.fromisoformat(rec.get("resolvedAt") or rec.get("firedAt")) > cutoff:
                    cleaned[hid] = rec
            except (ValueError, TypeError):
                cleaned[hid] = rec
        else:
            cleaned[hid] = rec
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[halts] 완료 — active {len(active)}, 신규 {len(new_events)}, 해제 {len(resolved_ids)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 구문 검증** — secrets 없이 실행해도 깨지지 않고(발송만 건너뜀) state 파일을 만드는지. 임시 data.json fixture 로:

```bash
python - <<'PY'
import json, os, subprocess, tempfile
# active 1건 fixture 를 data.json 자리에 임시 배치하지 않고, 모듈 함수만 호출해 구문 확인
import sys; sys.path.insert(0, 'scripts')
import check_halts  # import 시 에러 없으면 구문 OK
print("import OK; IS_TEST=", check_halts.IS_TEST)
print(check_halts._fire_msg({"type":"sidecar","market":"KOSDAQ","direction":"up",
      "reason":"선물 +6.0%","triggeredAt":"2026-06-23T14:31:00+09:00",
      "resumeAt":"2026-06-23T14:36:00+09:00","endOfDay":False}))
PY
```
Expected: `import OK; IS_TEST= False` 후 사이드카 메시지 3줄 출력(에러 없음).

- [ ] **Step 3: 커밋**

```bash
git add scripts/check_halts.py
git commit -m "feat: add KakaoTalk sender for market-halt events"
```

---

## Task 5: 워크플로 — 발송 스텝 + 커밋 포함 + 수동 테스트

**Files:**
- Modify: `.github/workflows/fetch-data.yml` (Validate 스텝 다음 / Commit 스텝 수정)
- Create: `.github/workflows/halts-test.yml`

**Interfaces:**
- Consumes: `scripts/check_halts.py` (Task 4), secrets `KAKAO_REST_API_KEY`/`KAKAO_REFRESH_TOKEN`.

- [ ] **Step 1: 발송 스텝 추가** — `fetch-data.yml` 의 `Validate data.json` 스텝(`run: python scripts/validate_data.py`) 과 `Commit and push data.json` 스텝 **사이**에 삽입:

```yaml
      # 🚨 시장중단(서킷브레이커·사이드카) 카카오톡 — data.json.marketHalts 의 신규 발동/해제만 발송.
      # best-effort: 실패해도 데이터 커밋을 막지 않도록 continue-on-error.
      - name: Send market-halt alerts (Kakao)
        continue-on-error: true
        env:
          KAKAO_REST_API_KEY:  ${{ secrets.KAKAO_REST_API_KEY }}
          KAKAO_REFRESH_TOKEN: ${{ secrets.KAKAO_REFRESH_TOKEN }}
        run: python scripts/check_halts.py
```

- [ ] **Step 2: 커밋 스텝에 `halts_state.json` 포함** — `Commit and push data.json` 스텝의 `run:` 블록 전체를 아래로 교체(기존 5-retry 푸시 루프 유지 + halts_state.json 추가):

```yaml
        run: |
          git config user.name  'github-actions[bot]'
          git config user.email 'github-actions[bot]@users.noreply.github.com'
          branch="${GITHUB_REF_NAME:-main}"
          if git diff --quiet -- data.json data_meta.json halts_state.json && git diff --staged --quiet -- data.json data_meta.json halts_state.json; then
            echo "변경 사항 없음 — 커밋 건너뜀"; exit 0
          fi
          msg="data: 시장 데이터 업데이트 $(date -u +'%Y-%m-%d %H:%M UTC')"
          cp data.json /tmp/data.json.run
          cp data_meta.json /tmp/data_meta.json.run
          cp halts_state.json /tmp/halts_state.json.run 2>/dev/null || true
          git add data.json data_meta.json
          [ -f halts_state.json ] && git add halts_state.json || true
          git commit -m "$msg" -q || true
          for attempt in 1 2 3 4 5; do
            if git push origin "HEAD:${branch}"; then
              echo "push 성공 (시도 ${attempt})"; exit 0
            fi
            echo "push 실패 (시도 ${attempt}) — 원격 ${branch} 최신 위에 산출물만 재적용"
            git fetch origin "${branch}" || true
            git reset --hard "origin/${branch}" 2>/dev/null || git reset --hard FETCH_HEAD || true
            cp /tmp/data.json.run data.json
            cp /tmp/data_meta.json.run data_meta.json
            cp /tmp/halts_state.json.run halts_state.json 2>/dev/null || true
            git add data.json data_meta.json
            [ -f halts_state.json ] && git add halts_state.json || true
            if git diff --staged --quiet -- data.json data_meta.json halts_state.json; then
              echo "원격이 이미 최신 — 종료"; exit 0
            fi
            git commit -m "$msg" -q || true
            sleep $((attempt * 3))
          done
          echo "::error::data.json push 실패 (재시도 소진)"; exit 1
```

- [ ] **Step 3: 수동 테스트 워크플로 작성** — `.github/workflows/halts-test.yml`:

```yaml
name: Market Halt Alert — Test Send (manual)

# 실제 발동은 드물어 실시간 테스트가 불가하므로, Actions → 'Run workflow' 로
# 가짜 서킷브레이커 사건 1건을 카카오톡으로 보내 발송 경로를 검증한다.
on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  test-send:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: '3.11'
      - run: pip install requests
      - name: Test Kakao halt alert
        env:
          HALTS_TEST: '1'
          KAKAO_REST_API_KEY:  ${{ secrets.KAKAO_REST_API_KEY }}
          KAKAO_REFRESH_TOKEN: ${{ secrets.KAKAO_REFRESH_TOKEN }}
        run: python scripts/check_halts.py
```

- [ ] **Step 4: YAML 구문 검증**

```bash
python -c "import yaml,sys; [yaml.safe_load(open(p,encoding='utf-8')) for p in ['.github/workflows/fetch-data.yml','.github/workflows/halts-test.yml']]; print('YAML OK')"
```
Expected: `YAML OK` (yaml 미설치면 `pip install pyyaml` 후 재실행)

- [ ] **Step 5: 커밋**

```bash
git add .github/workflows/fetch-data.yml .github/workflows/halts-test.yml
git commit -m "feat: run halt alerts in fetch workflow + manual test workflow"
```

---

## Task 6: 프론트엔드 — 배너 + 메뉴 배지 + 이력표

**Files:**
- Modify: `index.html` (CSS ~846, body ~1034–1058, 메뉴 ~1070, 국내증시 페이지 ~1659, JS ~1625/1646)

**Interfaces:**
- Consumes: `data.marketHalts` (Task 1). 기존 `loadRealData()`/`applyRealData(data)`(~15625), `ann-pulse` keyframe(846), `econ_` localStorage 관례.
- Produces: `renderMarketHalts(data)`, `dismissHalt(id)`, 전역 `window._lastRealDataObj`.

- [ ] **Step 1: CSS 추가** — line 846 (`@keyframes ann-pulse { ... }`) **다음 줄**에 삽입:

```css
  /* 🚨 시장중단(서킷브레이커·사이드카) 경고 */
  #marketHaltBanner { position: fixed; top: 56px; left: 0; right: 0; z-index: 299; display: none; flex-direction: column; }
  .halt-banner { display: flex; align-items: center; gap: 10px; padding: 9px 16px; font-size: 13px; font-weight: 600; color: #fff; border-bottom: 1px solid rgba(0,0,0,.25); box-shadow: 0 2px 8px rgba(0,0,0,.3); }
  .halt-banner.circuit { background: linear-gradient(90deg,#c0211b,#e23b30); }
  .halt-banner.sidecar { background: linear-gradient(90deg,#b5631a,#e08a2b); }
  .halt-banner .halt-cd { font-variant-numeric: tabular-nums; opacity: .92; font-weight: 500; }
  .halt-banner .halt-x { margin-left: auto; cursor: pointer; opacity: .8; font-size: 16px; line-height: 1; background: none; border: none; color: #fff; padding: 0 4px; }
  .halt-banner .halt-x:hover { opacity: 1; }
  .halt-hist-table { width: 100%; border-collapse: collapse; font-size: 12px; }
  .halt-hist-table th, .halt-hist-table td { padding: 6px 8px; border-bottom: 1px solid var(--c-border,#3a4054); text-align: left; white-space: nowrap; }
  .halt-hist-table th { color: var(--c-text-dim,#8b93a7); font-weight: 600; }
```

- [ ] **Step 2: 배너 컨테이너 삽입** — `</header>` (line 1055) **다음 줄**, `<div style="display:flex;padding-top:56px;">` (line 1058) **앞**에 삽입:

```html
<div id="marketHaltBanner" role="alert" aria-live="assertive"></div>
```

- [ ] **Step 3: 레이아웃 div 에 id 부여** — line 1058 을 교체(배너 높이만큼 본문을 밀어내기 위해 JS 가 paddingTop 조정):

```html
<div id="appLayout" style="display:flex;padding-top:56px;">
```

- [ ] **Step 4: 메뉴 배지 추가** — line 1070 의 시장 메뉴 항목. 고유 문자열 `candlestick_chart</span>시장 지표</div>` 를 아래로 교체(닫는 `</div>` 앞에 배지 span 삽입):

```html
candlestick_chart</span>시장 지표<span id="marketHaltBadge" style="display:none;width:7px;height:7px;border-radius:50%;background:#ef5350;margin-left:6px;animation:ann-pulse 1.2s ease-in-out infinite;"></span></div>
```
(`시장 지표` 가 파일에 여러 번 나올 수 있으니 위 전체 문자열로 매칭해 메뉴 항목만 정확히 수정한다.)

- [ ] **Step 5: 이력표 컨테이너 삽입** — `<div class="page" id="page-market">` (line 1659) **다음 줄**에 삽입:

```html
  <div id="marketHaltHistory" class="widget" style="display:none;margin-bottom:16px;"></div>
```

- [ ] **Step 6: 렌더 함수 추가** — `loadRealData()` 의 닫는 `}` (line 1646) **다음 줄**에 함수 2개 삽입:

```javascript

// 🚨 시장중단(서킷브레이커·사이드카) — data.marketHalts 를 상단 배너·메뉴배지·이력표로 렌더.
let _haltCountdownTimer = null;
function renderMarketHalts(data) {
  const mh = (data && data.marketHalts) || {};
  const active = Array.isArray(mh.active) ? mh.active : [];
  const history = Array.isArray(mh.history) ? mh.history : [];
  const banner = document.getElementById('marketHaltBanner');
  const badge = document.getElementById('marketHaltBadge');
  const layout = document.getElementById('appLayout');
  if (!banner) return;

  // 닫은 사건 기억(econ_ 접두사 관례). 현재 active 에 없는 id 는 정리.
  let dismissed = {};
  try { dismissed = JSON.parse(localStorage.getItem('econ_halt_dismissed') || '{}') || {}; } catch (_) {}
  const activeIds = new Set(active.map(h => h.id));
  Object.keys(dismissed).forEach(id => { if (!activeIds.has(id)) delete dismissed[id]; });
  try { localStorage.setItem('econ_halt_dismissed', JSON.stringify(dismissed)); } catch (_) {}

  const visible = active.filter(h => !dismissed[h.id]);
  const TYPE_KO = { circuit: '서킷브레이커', sidecar: '사이드카' };
  const esc = s => String(s == null ? '' : s).replace(/[<>&]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
  const hhmm = iso => { try { return new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false }); } catch (_) { return '-'; } };

  banner.innerHTML = visible.map(h => {
    const typ = TYPE_KO[h.type] || h.type;
    const stage = (h.type === 'circuit' && h.stage) ? ` ${h.stage}단계` : '';
    const cls = h.type === 'circuit' ? 'circuit' : 'sidecar';
    const icon = h.type === 'circuit' ? '🔴' : '🟠';
    const when = h.endOfDay
      ? `${hhmm(h.triggeredAt)} 매매중단 → 당일 장 종료`
      : `${hhmm(h.triggeredAt)} 중단 → <span class="halt-cd" data-resume="${esc(h.resumeAt || '')}">${hhmm(h.resumeAt)} 재개예정</span>`;
    const approx = h.approx ? ' · 추정' : '';
    return `<div class="halt-banner ${cls}" data-id="${esc(h.id)}">`
      + `<span>${icon} ${esc(h.market)} ${typ}${stage} 발동 — ${esc(h.reason)} · ${when}${approx}</span>`
      + `<button class="halt-x" title="닫기" onclick="dismissHalt('${esc(h.id)}')">✕</button></div>`;
  }).join('');

  const show = visible.length > 0;
  banner.style.display = show ? 'flex' : 'none';
  if (layout) layout.style.paddingTop = show ? (56 + banner.offsetHeight) + 'px' : '56px';
  if (badge) badge.style.display = active.length > 0 ? 'inline-block' : 'none';

  // 재개까지 카운트다운(1초 간격)
  if (_haltCountdownTimer) { clearInterval(_haltCountdownTimer); _haltCountdownTimer = null; }
  if (show) {
    const tick = () => {
      banner.querySelectorAll('.halt-cd[data-resume]').forEach(el => {
        const t = el.getAttribute('data-resume'); if (!t) return;
        const ms = new Date(t) - new Date();
        if (ms > 0) { const m = Math.floor(ms / 60000), s = Math.floor((ms % 60000) / 1000); el.textContent = `${hhmm(t)} 재개예정 (${m}:${String(s).padStart(2, '0')})`; }
        else { el.textContent = `${hhmm(t)} 재개`; }
      });
    };
    tick(); _haltCountdownTimer = setInterval(tick, 1000);
  }

  // 이력표(국내증시 페이지)
  const histBox = document.getElementById('marketHaltHistory');
  if (histBox) {
    if (history.length) {
      const rows = history.map(h => {
        const typ = TYPE_KO[h.type] || h.type;
        const stage = (h.type === 'circuit' && h.stage) ? `${h.stage}단계` : (h.direction === 'up' ? '매수' : '매도');
        let d = '-';
        try { d = new Date(h.triggeredAt).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }); } catch (_) {}
        const end = h.endOfDay ? '당일종료' : hhmm(h.resumeAt);
        return `<tr><td>${d}</td><td>${typ}</td><td>${esc(h.market)}</td><td>${stage}</td><td>${esc(h.reason)}</td><td>${hhmm(h.triggeredAt)}~${end}</td></tr>`;
      }).join('');
      histBox.innerHTML = `<div style="font-weight:600;margin-bottom:8px;">⚠️ 과거 매매중단 이력 (서킷브레이커·사이드카)</div>`
        + `<div style="overflow-x:auto;"><table class="halt-hist-table"><thead><tr><th>일시</th><th>종류</th><th>시장</th><th>단계/방향</th><th>사유</th><th>중단~재개</th></tr></thead><tbody>${rows}</tbody></table></div>`;
      histBox.style.display = 'block';
    } else {
      histBox.style.display = 'none';
    }
  }
}

function dismissHalt(id) {
  let dismissed = {};
  try { dismissed = JSON.parse(localStorage.getItem('econ_halt_dismissed') || '{}') || {}; } catch (_) {}
  dismissed[id] = 1;
  try { localStorage.setItem('econ_halt_dismissed', JSON.stringify(dismissed)); } catch (_) {}
  if (window._lastRealDataObj) renderMarketHalts(window._lastRealDataObj);
}
```

- [ ] **Step 7: 데이터 로드에 렌더 연결** — `loadRealData()` 의 `applyRealData(data);` (line 15625) **다음 줄**에 삽입:

```javascript
    try { window._lastRealDataObj = data; renderMarketHalts(data); } catch(_) {}
```

- [ ] **Step 8: 가짜 데이터로 브라우저 검증** — 임시 fixture 로 배너/배지/이력/카운트다운 + 콘솔 0 에러 확인:

```bash
# 1) 현재 data.json 백업 후 marketHalts 주입한 fixture 생성
python - <<'PY'
import json, datetime, shutil, os
KST = datetime.timezone(datetime.timedelta(hours=9))
now = datetime.datetime(2026,6,23,14,31,tzinfo=KST)
p = "data.json"
if os.path.exists(p): shutil.copy(p, "data.json.bak")
d = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"lastUpdated": now.isoformat(),"indices":{}}
d["marketHalts"] = {
  "active":[{"id":"circuit-KOSPI-20260623","type":"circuit","market":"KOSPI","stage":1,
     "direction":"down","reason":"코스피 지수 전일比 -8.10%","triggeredAt":now.isoformat(),
     "resumeAt":(now+datetime.timedelta(minutes=30)).isoformat(),"endOfDay":False,"source":"index"}],
  "history":[{"id":"sidecar-KOSDAQ-20260601","type":"sidecar","market":"KOSDAQ","stage":None,
     "direction":"down","reason":"코스닥150 선물 -6.0%","triggeredAt":"2026-06-01T10:05:00+09:00",
     "resumeAt":"2026-06-01T10:10:00+09:00","endOfDay":False,"source":"news","resolvedAt":"2026-06-01T10:10:00+09:00"}],
  "asOf":now.isoformat(),"stale":False}
json.dump(d, open(p,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
print("fixture 주입 완료")
PY
# 2) 로컬 서버 후 브라우저 또는 headless 렌더로 확인
python -m http.server 8000
```
브라우저(또는 repo 의 기존 headless 렌더 점검 방식)로 `http://localhost:8000/?p=market` 열고 확인:
- 상단 빨강 배너 "🔴 KOSPI 서킷브레이커 1단계 발동 … 재개예정 (mm:ss)" + 카운트다운 감소
- '시장 지표' 메뉴에 빨간 점
- 국내증시 페이지에 '과거 매매중단 이력' 표 1행
- DevTools Console 에러 0
- ✕ 클릭 시 배너 사라지고 새로고침해도 (같은 id) 유지

```bash
# 3) fixture 원복 (검증 끝나면)
[ -f data.json.bak ] && mv data.json.bak data.json || true
```
Expected: 위 4개 시각 항목 모두 정상, 콘솔 에러 0. **원복 필수**(data.json 은 봇 소유).

- [ ] **Step 9: 커밋**

```bash
git add index.html
git commit -m "feat: market-halt banner, menu badge, and history table"
```

---

## Task 7: 문서화 + 종단 검증

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: CLAUDE.md Key Files 표에 행 추가** — 표의 `check_alerts.py` 행 아래에 추가:

```markdown
| `scripts/market_halts.py` | Circuit-breaker/sidecar detector → `data.json.marketHalts` |
| `scripts/check_halts.py` | KakaoTalk sender for new/resolved market halts |
| `halts_state.json` | Market-halt send dedup state (bot-committed) |
```

- [ ] **Step 2: CLAUDE.md 워크플로 표에 행 추가** — GitHub Actions Workflows 표에 추가:

```markdown
| `halts-test.yml` | Manual (workflow_dispatch) | `KAKAO_REST_API_KEY`, `KAKAO_REFRESH_TOKEN` |
```

- [ ] **Step 3: CLAUDE.md 에 섹션 추가** — KakaoTalk Integration 섹션 다음에:

```markdown
## Market Halt Alerts (서킷브레이커·사이드카)

- `scripts/market_halts.py` `detect_market_halts()` 가 `fetch_data.py` 빌드 말미에 실행돼 `data.json.marketHalts {active[], history[]}` 를 만든다.
- 감지 2겹: (1) `indices.{KOSPI,KOSDAQ}.change` 등락률로 CB 단계 추정(-8/-15/-20% = 1/2/3), (2) NAVER 뉴스 best-effort 스크레이프로 CB 확정 + 사이드카 포착(`NAVER_CLIENT_ID/SECRET` 있을 때만).
- 직전 active 를 `resumeAt` 전까지 이월(10분 스냅샷의 짧은 발동 보존). 해제 시 `history`(최근 30건)로 이동.
- 프론트 `renderMarketHalts(data)` 가 전 페이지 상단 배너 + '시장 지표' 메뉴 배지 + 국내증시 이력표를 렌더. 닫기 상태는 `localStorage.econ_halt_dismissed`.
- `check_halts.py` 가 `fetch-data.yml` 스텝에서 `marketHalts.active` 의 신규 발동/해제만 카카오톡 발송(`halts_state.json` 도배방지). 수동 검증: `halts-test.yml` 의 'Run workflow'.
- **한계(정직성):** 무료 실시간 공식 피드가 없어 best-effort. 사이드카는 뉴스 스크레이프 의존 → NAVER 키 필요. 향후 KRX 공식 API 연동은 별도 작업.
```

- [ ] **Step 4: 종단 검증 (전체 재확인)**

```bash
python scripts/test_market_halts.py        # → ALL PASS
python scripts/validate_data.py            # → ✅ 검증 통과 (marketHalts 형식 경고 0)
python -c "import yaml; [yaml.safe_load(open(p,encoding='utf-8')) for p in ['.github/workflows/fetch-data.yml','.github/workflows/halts-test.yml']]; print('YAML OK')"
```
Expected: `ALL PASS`, `✅ ... 검증 통과`, `YAML OK`. (브라우저 렌더는 Task 6 Step 8 에서 확인 완료.)

- [ ] **Step 5: 커밋**

```bash
git add CLAUDE.md
git commit -m "docs: document market-halt alert pipeline"
```

- [ ] **Step 6: (선택) 실제 카카오 경로 검증** — secrets 설정돼 있으면 GitHub Actions → `Market Halt Alert — Test Send` → Run workflow → 카카오톡 `[테스트] 🔴 [시장경보] KOSPI 서킷브레이커 1단계 …` 수신 확인.

---

## 미해결/후속 (범위 밖)

- **KRX 공식 API 연동**: 정확한 발동·해제 시각·사유를 KRX 공식 소스에서 받는 업그레이드. 현재는 지수추정 + 뉴스 best-effort.
- **종목별 VI(변동성완화장치)**: 잦고 범위 밖이라 제외.
- **해외(미국) 서킷브레이커**: 스키마는 일반형이라 추후 `market` 확장 가능.
