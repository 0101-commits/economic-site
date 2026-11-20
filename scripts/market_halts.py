#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""시장중단(서킷브레이커·사이드카) 감지 — fetch_data.py 가 호출해 data.json.marketHalts 생성.

발동은 거래소 공시만 만든다(2026-11-20, 기획 4ioDhgSA ① · 결정 D1~D3):
  ① KRX KIND 「오늘의 공시」 시장조치 공시(kind_notices.recent) — 사이드카 · 서킷 모두. 화면 이력도 이것.
  ② 공시를 못 읽은 런만: 지수 등락률(전일 종가 대비)로 서킷 단계를 「추정」(source=index). 사이드카는 추정하지 않는다.
옛 뉴스 헤드라인 경로(「사이드카 발동」 검색 + 현물 ±2.5% 교차검증)는 지웠다 — 10/1~11/20 사이드카 · 서킷 경보 34건 중
18건이 오보였고 전부 이 경로였다(실제 발동 20건은 공시와 1분 안에 맞는다).

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
# 가짜로 확정된 과거 서킷 기록 — 이력·이월에서 뺀다(2026-09-30). 근거 = Yahoo ^KS11 일봉의 그날 저가(전일 종가 대비).
# 산식 버그가 남긴 것이고(check_halts._yahoo_quote docstring), 과거 저가 자료가 파이프라인에 없어 규칙으로 재판정하지
# 못한다 — 그래서 id 를 명시한다. 새 항목은 같은 방식의 실측 근거 없이는 넣지 말 것.
_FALSE_HALTS = {
    "circuit-KOSPI-20260714": "기록 2단계 -15.08%, 그날 저가 -5.26%·종가 +0.73% — 1단계(-8%)에도 닿은 적 없음. "
                              "원인: 5일 누적 등락 + 전일 등락률 재사용(7/16 이전)",
    "circuit-KOSPI-20260716": "기록 1단계 -8.14%, 그날 저가 -7.60%(실제 전일比 -7.34%). 원인: 5일 전 종가를 전일로 쓴 버그",
}


def _log(msg):
    print(msg)


def _halt_id(typ, market, day):
    return f"{typ}-{market}-{day}"


def _in_session(now):
    """KRX 정규장(평일 09:00~15:30 KST) 여부. 공휴일은 모른다(지수가 안 움직여 문턱에서 걸린다)."""
    t = now.astimezone(KST)
    hm = t.hour * 60 + t.minute
    return t.weekday() < 5 and 9 * 60 <= hm <= 15 * 60 + 30


def _prev_business_day(sources, now):
    """직전 영업일(YYYY-MM-DD). 오늘 날짜가 맞는 marketCalendarKr 이 있으면 그것, 없으면 평일 역산
    (공휴일 다음 날은 휴일을 짚어 종가를 못 찾는다 → 감지 보류. 날조보다 누락이 낫다)."""
    today = now.astimezone(KST).date()
    for src in sources:
        cal = (src or {}).get("marketCalendarKr") or {}
        if (cal.get("today") or {}).get("date") == today.isoformat():
            d = (cal.get("previousBusinessDay") or {}).get("date")
            if d:
                return d
    d = today - datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d.isoformat()


def _close_on(sources, market, day):
    """이력(history.indices.<시장>)에서 그 날짜의 종가. 배열 순서가 아니라 날짜로 찾는다."""
    for src in sources:
        for r in reversed((((src or {}).get("history") or {}).get("indices") or {}).get(market) or []):
            if isinstance(r, dict) and r.get("date") == day and r.get("close"):
                return float(r["close"])
    return None


def cb_from_index(market, change_pct, now):
    """지수 등락률(전일比 %) → 서킷브레이커 사건 dict 또는 None. 가장 심각한 충족 단계."""
    # 오염 방어: 지수 하루 변동은 이론상 -30% 미만이 불가능(3단계 -20% 서 당일 거래 종료).
    # 글리치성 극단값(-100 등)·NaN 은 서킷브레이커 날조를 막기 위해 무시한다.
    if change_pct is None or change_pct != change_pct or change_pct < -30.0:
        return None
    # 🛡 세션 게이트 ①: KRX 정규장(평일 09:00~15:30 KST) 밖에서는 지수기반 CB 를 만들지 않는다.
    #    실증: 2026-07-02 15:43 KST 장마감 후 오염 데이터(-8.00%)로 오발송(해제까지 발송) 사건 +
    #    주말 hourly 런이 금요일 -8% '종가'를 보고 오발동하는 것 방지. now 는 주입형이라 테스트 가능.
    if not _in_session(now):
        return None
    t = now.astimezone(KST)
    hm = t.hour * 60 + t.minute
    for stage, thr, halt_min, auc_min, eod in CB_RULES:
        if change_pct <= thr:
            # 🛡 세션 게이트 ②: KRX 규정상 1·2단계는 14:50 이후 발동 불가(3단계=endOfDay 만
            #    장마감 15:30 까지 발동 가능) → 14:50 이후엔 1·2단계 후보를 건너뛴다.
            if not eod and hm >= 14 * 60 + 50:
                continue
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


def fetch_notices(now, lookback_min=10 * 60, max_pages=12, timeout=8.0):
    """오늘 시장조치 공시(kind_notices 사건 dict 목록) — 못 읽으면 None(→ 지수 서킷 추정만).

    평일 08:50~18:00 KST 밖이면 [](읽을 것 없음). KIND_OFFLINE=1 이면 None(시험 · 재생 — 네트워크 없이 지수 길만).
    수집 런(10분)은 하루치(기본값)를 읽어 화면 이력을 채우고, 매분 판정 런은 30분 · 2쪽만 읽는다(호출 한도 모름 — 기획 부록)."""
    if os.environ.get("KIND_OFFLINE") == "1":
        LAST_READ[0] = "skip"
        return None
    t = now.astimezone(KST)
    hm = t.hour * 60 + t.minute
    if t.weekday() >= 5 or not (8 * 60 + 50 <= hm <= 18 * 60):
        LAST_READ[0] = "skip"
        return []
    try:
        import kind_notices
        out = kind_notices.recent(now, lookback_min=lookback_min, max_pages=max_pages, timeout=timeout)
        LAST_READ[0] = "ok"
        return out
    except Exception as e:                                 # noqa: BLE001 — 접속 · 형식 오류 = 못 읽음
        _log(f"[halts] 거래소 공시 읽기 실패: {type(e).__name__} {str(e)[:80]}")
        LAST_READ[0] = "fail"
        return None


LAST_READ = ["skip"]      # 마지막 fetch_notices 결과 — ok · fail · skip(장 밖 · 시험). 수집 런의 #시스템 감시(fetch_data)가 읽는다


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
    # endOfDay 는 OR(더 심각한 쪽) 채택 — '가장 이른' 이벤트 기준이면 1→3단계 격상 후에도
    # False 로 남아 당일종료 유지·격상 알림이 깨진다. endOfDay 면 resumeAt 도 의미 없으니 None.
    out["endOfDay"] = bool(a.get("endOfDay")) or bool(b.get("endOfDay"))
    if out["endOfDay"]:
        out["resumeAt"] = None
    for cand in (a, b):
        if cand.get("source") == "index" and cand.get("reason"):
            out["reason"] = cand["reason"]
    return out


def detect_market_halts(data, prev, now=None):
    """data(이번 빌드)+prev(직전 data.json) → marketHalts dict."""
    now = now or datetime.datetime.now(KST)
    prev_halts = (prev or {}).get("marketHalts") or {}
    # 교차검증 없이 들어간 옛 뉴스 사건(2026-09-30 오탐 2건)과 _FALSE_HALTS 는 이월·이력에서 뺀다 — 화면 '매매중단 이력'에 남지 않게.
    # 뉴스 사건은 교차검증(corroborated)이 붙었어도 뺀다 — 2026-11-20 개편 전 뉴스 경로의 오보(11/20 09:42 · 10:21 등)가
    # 화면 이력에 남지 않게. 발동은 이제 거래소 공시(source krx)만 만든다.
    trusted = lambda h: (isinstance(h, dict) and h.get("id") not in _FALSE_HALTS and h.get("source") != "news")
    prev_active = {h["id"]: h for h in prev_halts.get("active", []) if trusted(h) and h.get("id")}
    history = [h for h in prev_halts.get("history", []) if trusted(h)]

    candidates = []
    indices = data.get("indices") or {}

    # 🛡 세션 게이트 ③(데이터 정합): 지수 값(price/value)이 None 인데 change 만 있으면 오염으로
    #    간주하고 그 market 의 지수기반 감지를 스킵한다 — 2026-07-02 실사건의 직접 원인
    #    (value=None·change=-8.00 오염 데이터로 서킷브레이커 오발송). 키 이름은 fetch_data 산출
    #    (price)과 check_halts 라이브 모드 산출(value)을 모두 수용한다.
    def _idx_value(m):
        e = indices.get(m) or {}
        return e.get("price") if e.get("price") is not None else e.get("value")

    # 🛡 전일 종가는 '직전 영업일 날짜'로 이력에서 찾아 등락률을 직접 계산한다 — 공급원의 change 와
    #    일봉 배열 순서(rows[-2])를 믿지 않는다. 2026-07-29 실사건: 개장 무렵 Yahoo 일봉이 7/28 봉을
    #    7/29 날짜로 내보내 전일이 7/27 로 밀렸고, 장이 +1.5% 인 09:12 에 KOSPI -10.84%(=전일 등락률)
    #    1단계, 09:45 KOSDAQ 1단계, 11:20·12:23 두 시장 2단계가 전부 가짜로 나갔다. 7/14 09:02 도 같은 모양.
    #    종가를 못 찾으면 감지 보류(stale) — 가짜 서킷보다 누락이 낫다.
    srcs = (data, prev or {})
    prev_day = _prev_business_day(srcs, now)

    def _change(m):
        price, pc = _idx_value(m), _close_on(srcs, m, prev_day)
        if price is None or not pc:
            return None
        chg = (float(price) / pc - 1) * 100
        src = (indices.get(m) or {}).get("change")
        if src is not None and abs(src - chg) > 0.5:
            _log(f"[halts] {m} 등락률 불일치: 공급원 {src:.2f}% / {prev_day} 종가 기준 {chg:.2f}% (후자 사용)")
        return chg

    changes = {m: _change(m) for m in ("KOSPI", "KOSDAQ")}
    # 등락률을 하나도 못 구하면 감지가 '깜깜이'로 돈 것 → stale 로 표시해
    # 소비측(check_halts)이 지수기반 신규 발동을 보류하게 한다(부분실패로 보존된 옛 값 오탐 방지).
    have_index = any(c is not None for c in changes.values())
    notices = fetch_notices(now)
    kind_ok = notices is not None
    if kind_ok:
        candidates.extend(dict(h) for h in notices)
    else:                                              # 공시를 못 읽은 런 — 서킷만 지수로 추정(D3), 사이드카는 없음
        for market in ("KOSPI", "KOSDAQ"):
            ev = cb_from_index(market, changes[market], now)
            if ev:
                candidates.append(ev)

    by_id = {}
    for ev in candidates:
        by_id[ev["id"]] = _merge(by_id.get(ev["id"]), ev)

    # 직전 active 이월 — resumeAt 전이면 유지(스냅샷 사이 짧은 발동 보존)
    for hid, h in prev_active.items():
        if hid in by_id:
            by_id[hid] = _merge(by_id[hid], h)
            continue
        if kind_ok and h.get("source") != "krx":
            continue                                   # 공시가 정답 — 공시에 없는 추정 사건은 끝
        if h.get("endOfDay"):
            keep = h.get("triggeredAt", "")[:10] == now.strftime("%Y-%m-%d")
        else:
            try:
                keep = bool(h.get("resumeAt")) and datetime.datetime.fromisoformat(h["resumeAt"]) > now
            except (ValueError, TypeError):
                keep = False
        if keep:
            by_id[hid] = h

    def _still(h):
        if h.get("endOfDay"):
            return str(h.get("triggeredAt", ""))[:10] == now.strftime("%Y-%m-%d")
        try:
            return bool(h.get("resumeAt")) and datetime.datetime.fromisoformat(h["resumeAt"]) > now
        except (ValueError, TypeError):
            return False

    done = [h for h in by_id.values() if h.get("source") == "krx" and not _still(h)]
    active = sorted((h for h in by_id.values() if h not in done), key=lambda x: x.get("triggeredAt", ""))
    active_ids = {h["id"] for h in active}
    for h in done:                                     # 공시로 처음 본 사건이 이미 풀렸다(10분 런 사이) — 바로 이력
        if h["id"] not in prev_active and not any(x.get("id") == h["id"] for x in history):
            history.insert(0, dict(h, resolvedAt=h.get("resumeAt") or now.isoformat()))

    # 직전 active 중 사라진 것 = 해제 → history(중복 갱신, 최신순 30건)
    for hid, h in prev_active.items():
        if hid not in active_ids:
            rec = dict(h)
            rec["resolvedAt"] = now.isoformat()
            history = [x for x in history if x.get("id") != hid]
            history.insert(0, rec)
    history = history[:30]

    return {"active": active, "history": history, "asOf": now.isoformat(),
            "stale": not have_index, "kindRead": LAST_READ[0]}
