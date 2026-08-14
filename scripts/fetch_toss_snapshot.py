#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""토스증권 스냅샷 수집기 — **사용자 PC 에서** 실행한다.

왜 PC 인가
----------
토스 Open API 는 클라이언트마다 '허용 IP 목록'을 두고, 목록 밖 IP 의 호출을 막는다
(2026-08-14 실측: 집 IP 통과, GitHub Actions 러너 403, Cloudflare Worker 401
`unidentified-client`). GitHub Actions·Cloudflare 는 출구 IP 가 유동이라 등록 자체가
불가능하다. 그래서 **허용 IP 가 등록된 PC** 에서 이 스크립트가 토스 데이터를 받아
`toss_snapshot.json` 으로 저장·커밋하고, 클라우드의 fetch_data.py 가 그 파일을 읽는다.

PC 가 꺼져 있으면 스냅샷이 낡을 뿐이고, fetch_data.py 의 신선도 가드가 낡은 값을
버리고 기존 소스(pykrx/네이버/Yahoo) 로 그대로 흐른다 — 파이프라인은 멈추지 않는다.

무엇을 담는가 (전부 하루 1~2회면 충분한 것들)
  · indices      코스피·코스닥 (공식 실시간)
  · yieldCurveKr 국고채 2/3/5/10/20/30Y — ECOS 만기 라벨 밀림을 교정하는 근거
  · stockMovers  코스피 상승/하락 Top10 (기준가 기반 등락률)
  · investorDaily 코스피 투자자별 순매수(억원)
  · usdkrw       토스 고시 환율 (교차검증용)

사용
  python scripts/fetch_toss_snapshot.py            # 수집 후 파일만 갱신
  python scripts/fetch_toss_snapshot.py --push     # 갱신 + 커밋·푸시 (스케줄러용)
환경변수: TOSS_CLIENT_ID, TOSS_CLIENT_SECRET (없으면 아무것도 하지 않고 종료)
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toss_api                                              # noqa: E402

KST = timezone(timedelta(hours=9))
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
OUT = os.path.join(ROOT, "toss_snapshot.json")

# yieldCurve.kr 10칸 만기축의 슬롯 ↔ 토스 심볼 (fetch_data._TOSS_BOND_SLOTS 와 동일)
BOND_SLOTS = [(4, "KR_BOND_2Y", "2Y"), (5, "KR_BOND_5Y", "5Y"),
              (7, "KR_BOND_10Y", "10Y"), (8, "KR_BOND_20Y", "20Y"),
              (9, "KR_BOND_30Y", "30Y")]


def log(msg):
    print(f"[toss-snap] {msg}", flush=True)


def collect():
    """실패한 항목은 넣지 않는다 — 부분 성공도 그대로 쓸모가 있다(날조 금지)."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    snap = {"generatedAt": datetime.now(KST).isoformat(), "source": "토스증권 Open API"}

    idx = {}
    for name in ("KOSPI", "KOSDAQ"):
        q = toss_api.index_quote(name)
        if q:
            idx[name] = {"price": q["price"], "change": q["change"], "asOf": q["asOf"]}
    if idx:
        snap["indices"] = idx
        log(f"지수 {list(idx)}")

    spot = toss_api.indicator_prices([s for _, s, _ in BOND_SLOTS] + ["KR_BOND_3Y"])
    if spot:
        cur, prv, series = [None] * 10, [None] * 10, []
        for slot, sym, label in BOND_SLOTS:
            cs = toss_api.indicator_candles(sym, "1d", 200)
            v = spot.get(sym) or (cs[-1]["close"] if cs else None)
            if v is None:
                continue
            cur[slot] = round(v, 3)
            if len(cs) > 21:
                prv[slot] = round(cs[-22]["close"], 3)
            elif cs:
                prv[slot] = round(cs[0]["close"], 3)
            if cs:
                series.append({"tenor": label, "label": label, "toss_symbol": sym,
                               "data": [{"date": c["date"], "value": c["close"]} for c in cs]})
        if any(v is not None for v in cur):
            yc = {"current": cur, "prev_month": prv, "series": series}
            if spot.get("KR_BOND_3Y") is not None:
                yc["extra"] = {"3Y": round(spot["KR_BOND_3Y"], 3)}
            snap["yieldCurveKr"] = yc
            log(f"국고채 {[v for v in cur if v is not None]}")

    movers = {}
    for side, rank_type in (("kospiGainers", "TOP_GAINERS"), ("kospiLosers", "TOP_LOSERS")):
        rows = toss_api.rankings(rank_type, "KR", "1d", limit=60)
        if not rows:
            continue
        meta = toss_api.stocks([r["code"] for r in rows])
        out = []
        for r in rows:
            m = meta.get(r["code"]) or {}
            if m.get("market") != "KOSPI" or m.get("type") != "STOCK":
                continue
            out.append({"name": m.get("name") or r["code"], "code": r["code"],
                        "price": r["price"], "chg": r["chg"], "vol": r["vol"],
                        "as_of": today})
            if len(out) >= 10:
                break
        if out:
            movers[side] = out
    if movers:
        snap["stockMovers"] = movers
        log("등락상위 " + ", ".join(f"{k} {len(v)}건" for k, v in movers.items()))

    inv = toss_api.index_investor_trading("KOSPI", "1d", max_pages=40)
    if inv:
        snap["investorDaily"] = inv
        log(f"투자자 동향 {len(inv)}일 ({inv[0]['date']} ~ {inv[-1]['date']})")

    fx = toss_api.exchange_rate("USD", "KRW")
    if fx:
        snap["usdkrw"] = fx
        log(f"USDKRW {fx['midRate']}")
    return snap


def git_push():
    """toss_snapshot.json 만 커밋·푸시. 봇 커밋과 충돌해도 rebase 로 흡수된다."""
    def run(*args):
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True)

    # `git diff --quiet` 는 **추적되지 않는 파일을 '변경 없음'으로 본다** — 최초 실행에서
    # 스냅샷이 영원히 푸시되지 않는 함정. status --porcelain 으로 신규/변경을 함께 본다.
    if not run("git", "status", "--porcelain", "--", "toss_snapshot.json").stdout.strip():
        log("변경 없음 — 푸시 생략")
        return True
    run("git", "add", "toss_snapshot.json")
    stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    run("git", "commit", "-m", f"data: 토스 스냅샷 {stamp}")
    for attempt in range(3):
        run("git", "pull", "--rebase", "-q")
        r = run("git", "push", "-q")
        if r.returncode == 0:
            log("푸시 완료")
            return True
        log(f"푸시 실패({attempt + 1}/3): {(r.stderr or '').strip()[:200]}")
    return False


def main():
    if not toss_api.enabled():
        log("TOSS_CLIENT_ID/SECRET 미설정 — 종료")
        return 1
    snap = collect()
    payload_keys = [k for k in snap if k not in ("generatedAt", "source")]
    if not payload_keys:
        log("수집 0건 — 파일 미갱신 (허용 IP 목록에 이 PC 의 공인 IP 가 있는지 확인)")
        return 2
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
    log(f"저장 {OUT} ({os.path.getsize(OUT) // 1024}KB, 항목 {payload_keys})")
    if "--push" in sys.argv:
        return 0 if git_push() else 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
