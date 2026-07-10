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
    # 오염 방어: 지수 하루 변동은 이론상 -30% 미만이 불가능(3단계 -20% 서 당일 거래 종료).
    # 글리치성 극단값(-100 등)·NaN 은 서킷브레이커 날조를 막기 위해 무시한다.
    if change_pct is None or change_pct != change_pct or change_pct < -30.0:
        return None
    # 🛡 세션 게이트 ①: KRX 정규장(평일 09:00~15:30 KST) 밖에서는 지수기반 CB 를 만들지 않는다.
    #    실증: 2026-07-02 15:43 KST 장마감 후 오염 데이터(-8.00%)로 오발송(해제까지 발송) 사건 +
    #    주말 hourly 런이 금요일 -8% '종가'를 보고 오발동하는 것 방지. now 는 주입형이라 테스트 가능.
    t = now.astimezone(KST)
    if t.weekday() >= 5:                              # 토(5)·일(6)
        return None
    hm = t.hour * 60 + t.minute
    if not (9 * 60 <= hm <= 15 * 60 + 30):            # 09:00~15:30 밖
        return None
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
    prev_active = {h["id"]: h for h in prev_halts.get("active", [])
                   if isinstance(h, dict) and h.get("id")}
    history = [h for h in prev_halts.get("history", []) if isinstance(h, dict)]

    candidates = []
    indices = data.get("indices") or {}

    # 🛡 세션 게이트 ③(데이터 정합): 지수 값(price/value)이 None 인데 change 만 있으면 오염으로
    #    간주하고 그 market 의 지수기반 감지를 스킵한다 — 2026-07-02 실사건의 직접 원인
    #    (value=None·change=-8.00 오염 데이터로 서킷브레이커 오발송). 키 이름은 fetch_data 산출
    #    (price)과 check_halts 라이브 모드 산출(value)을 모두 수용한다.
    def _idx_value(m):
        e = indices.get(m) or {}
        return e.get("price") if e.get("price") is not None else e.get("value")

    # 지수 등락률이 둘 다 없으면(또는 값이 None 으로 오염) 감지가 '깜깜이'로 돈 것 → stale 로 표시해
    # 소비측(check_halts)이 지수기반 신규 발동을 보류하게 한다(부분실패로 보존된 옛 값 오탐 방지).
    have_index = any((indices.get(m) or {}).get("change") is not None
                     and _idx_value(m) is not None
                     for m in ("KOSPI", "KOSDAQ"))
    for market in ("KOSPI", "KOSDAQ"):
        if _idx_value(market) is None:                 # 값 오염 → change 불신, 감지 스킵
            continue
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

    return {"active": active, "history": history, "asOf": now.isoformat(),
            "stale": not have_index}
