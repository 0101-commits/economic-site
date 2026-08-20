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

무엇을 담는가
  · indices        코스피·코스닥 (공식 실시간)
  · yieldCurveKr   국고채 2/3/5/10/20/30Y — ECOS 만기 라벨 밀림을 교정하는 근거
  · stockMovers    국내주식 상승/하락 Top10 (코스피+코스닥, 기준가 기반 등락률)
  · etfMovers      ETF 상승/하락 Top10 (같은 랭킹 응답에서 분리 — 추가 호출 0)
  · rankings       거래대금 상위 + 토스증권 체결 상위(리테일 인기 프록시)
  · investorDaily  코스피 투자자별 순매수(억원)
  · stockData      트래킹 종목별 수급 — 투자자 순매수(주)/공매도/신용/대차/프로그램/경보
  · marketCalendarKr 전일/당일/익영업일 (휴장 판정 정본)
  · usdkrw         토스 고시 환율 (교차검증용)

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

    # 등락상위 — 한 랭킹 응답에서 주식(코스피+코스닥)과 ETF 를 함께 뽑는다.
    # 종전엔 market=="KOSPI" and type=="STOCK" 만 남겨 코스닥이 통째로 빠졌고
    # ("국내 주식" 라벨과 불일치) ETF 행은 버렸다 — 둘 다 여기서 살린다.
    movers, etf_movers = {}, {}
    for stock_key, etf_key, rank_type in (
            ("kospiGainers", "etfGainers", "TOP_GAINERS"),
            ("kospiLosers", "etfLosers", "TOP_LOSERS")):
        rows = toss_api.rankings(rank_type, "KR", "1d", limit=100)
        if not rows:
            continue
        meta = toss_api.stocks([r["code"] for r in rows])
        stocks_out, etf_out = [], []
        for r in rows:
            m = meta.get(r["code"]) or {}
            row = {"name": m.get("name") or r["code"], "code": r["code"],
                   "price": r["price"], "chg": r["chg"], "vol": r["vol"],
                   "market": m.get("market"), "as_of": today}
            if m.get("market") in ("KOSPI", "KOSDAQ") and m.get("type") == "STOCK":
                if len(stocks_out) < 10:
                    stocks_out.append(row)
            elif m.get("type") == "ETF" and len(etf_out) < 10:
                etf_out.append(row)
            if len(stocks_out) >= 10 and len(etf_out) >= 10:
                break
        if stocks_out:
            movers[stock_key] = stocks_out
        if etf_out:
            etf_movers[etf_key] = etf_out
    if movers:
        snap["stockMovers"] = movers
        log("등락상위 " + ", ".join(f"{k} {len(v)}건" for k, v in movers.items()))
    if etf_movers:
        snap["etfMovers"] = etf_movers
        log("ETF등락 " + ", ".join(f"{k} {len(v)}건" for k, v in etf_movers.items()))

    # 거래대금 상위 + 토스증권 체결 상위(국내 유일한 리테일 브로커 체결 랭킹)
    rankings = {}
    for key, rank_type in (("tradingAmount", "MARKET_TRADING_AMOUNT"),
                           ("tossAmount", "TOSS_SECURITIES_TRADING_AMOUNT")):
        rows = toss_api.rankings(rank_type, "KR", "1d", limit=20)
        if not rows:
            continue
        meta = toss_api.stocks([r["code"] for r in rows])
        out = []
        for r in rows:
            m = meta.get(r["code"]) or {}
            out.append({"name": m.get("name") or r["code"], "code": r["code"],
                        "price": r["price"], "chg": r["chg"], "amount": r["amount"],
                        "market": m.get("market"), "type": m.get("type"), "as_of": today})
        rankings[key] = out
    if rankings:
        snap["rankings"] = rankings
        log("랭킹 " + ", ".join(f"{k} {len(v)}건" for k, v in rankings.items()))

    inv = toss_api.index_investor_trading("KOSPI", "1d", max_pages=40)
    if inv:
        snap["investorDaily"] = inv
        log(f"투자자 동향 {len(inv)}일 ({inv[0]['date']} ~ {inv[-1]['date']})")

    sd = collect_stock_data()
    if sd:
        snap["stockData"] = sd
        log(f"종목 수급 {len(sd)}종목")

    cal = toss_api.market_calendar_kr()
    if cal:
        snap["marketCalendarKr"] = cal
        log(f"캘린더 today={cal.get('today')}")

    fx = toss_api.exchange_rate("USD", "KRW")
    if fx:
        snap["usdkrw"] = fx
        log(f"USDKRW {fx['midRate']}")
    return snap


def _tracking_symbols():
    """alerts_config.json 트래킹 목록의 KR 심볼(공개 파일 — 보유정보 없음)."""
    try:
        with open(os.path.join(ROOT, "alerts_config.json"), encoding="utf-8") as f:
            items = (json.load(f).get("tracking") or {}).get("items") or []
    except Exception:                                        # noqa: BLE001
        return []
    return [t["symbol"] for t in items
            if t.get("symbol") and (t.get("market") or "KR").upper() == "KR"]


def collect_stock_data(days=20):
    """트래킹 종목별 수급 5종 + 경보 + 마스터(시총 재료).

    수급 엔드포인트는 전부 KR 전용. ETF 는 커버리지가 갈린다(2026-08-20 실측:
    investor·credit 은 실데이터, lending·program 은 빈 records) — 빈 항목은
    넣지 않고, 프론트가 없는 항목의 칸을 숨긴다(날조 금지).
    """
    syms = _tracking_symbols()
    if not syms:
        return {}
    meta = toss_api.stocks(syms)
    out = {}
    for sym in syms:
        entry = {}
        m = meta.get(sym) or {}
        if m.get("name"):
            entry["name"], entry["market"] = m["name"], m.get("market")
            entry["secType"] = m.get("type")
            if m.get("shares"):
                entry["shares"] = m["shares"]
        try:
            inv = toss_api.stock_investor_trading(sym, max_pages=2)[-days:]
            if inv:
                entry["investor"] = inv
            short = toss_api.stock_short_selling(sym)[-days:]
            if short:
                entry["short"] = short
            credit = toss_api.stock_credit_trades(sym)[-days:]
            if credit:
                entry["credit"] = credit
            lend = toss_api.stock_securities_lending(sym)[-days:]
            if lend:
                entry["lending"] = lend
            prog = toss_api.stock_program_trades(sym)[-days:]
            if prog:
                entry["program"] = prog
            warn = toss_api.stock_warnings(sym)
            if warn is not None:                 # []=경보 없음(유의미), None=조회 실패
                entry["warnings"] = warn
        except Exception as e:                                # noqa: BLE001
            log(f"수급 {sym} 오류: {e}")
        if any(k in entry for k in ("investor", "short", "credit", "lending",
                                    "program", "warnings")):
            out[sym] = entry
    return out


def git_push():
    """toss_snapshot.json 만 커밋·푸시. 봇 커밋과 충돌해도 rebase 로 흡수된다."""
    def run(*args):
        # ⚠ encoding 을 명시한다. text=True 만 주면 파이썬이 **로케일 인코딩(cp949)** 으로
        #   디코드하는데 git 출력은 UTF-8 이라(커밋 메시지에 한글) 리더 스레드가
        #   UnicodeDecodeError 로 죽고 stdout 이 None 이 된다 — 스케줄러 실행에서 실측된 버그.
        return subprocess.run(args, cwd=ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")

    # `git diff --quiet` 는 **추적되지 않는 파일을 '변경 없음'으로 본다** — 최초 실행에서
    # 스냅샷이 영원히 푸시되지 않는 함정. status --porcelain 으로 신규/변경을 함께 본다.
    if not (run("git", "status", "--porcelain", "--", "toss_snapshot.json").stdout or "").strip():
        log("변경 없음 — 푸시 생략")
        return True
    run("git", "add", "toss_snapshot.json")
    stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    c = run("git", "commit", "-m", f"data: 토스 스냅샷 {stamp}")
    if c.returncode != 0:
        log(f"커밋 실패 — 푸시 중단: {((c.stdout or '') + (c.stderr or '')).strip()[:200]}")
        return False
    for attempt in range(3):
        # --autostash: 다른 작업으로 워킹트리가 더러워도 rebase 가 멈추지 않게 한다.
        # (이 스크립트는 PC 가 켜질 때마다 배경에서 돌아 — 사람이 편집 중일 수 있다.)
        run("git", "pull", "--rebase", "--autostash", "-q")
        r = run("git", "push", "-q")
        if r.returncode == 0:
            log("푸시 완료")
            return True
        log(f"푸시 실패({attempt + 1}/3): {(r.stderr or '').strip()[:200]}")
    return False


# 커밋 스팸 방지 — 이 스크립트는 로그온·매시간 등 자주 돌지만, 장 마감 뒤·주말엔
# 값이 하나도 안 바뀐다. fetch_data.py 가 **실제로 소비하는 항목**만 해시해서 같으면
# 파일을 아예 건드리지 않는다(=커밋 없음). usdkrw 는 24시간 미세하게 흔들리는데
# 소비처가 없어 해시에서 뺀다 — 넣으면 매 실행이 새 커밋이 된다.
_HASHED_KEYS = ("indices", "yieldCurveKr", "stockMovers", "etfMovers", "rankings",
                "investorDaily", "stockData", "marketCalendarKr")


def _payload_hash(snap):
    import hashlib
    body = {k: snap.get(k) for k in _HASHED_KEYS if k in snap}
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode()).hexdigest()


def _prev_hash():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f).get("payloadHash")
    except Exception:                                        # noqa: BLE001
        return None


# 수집이 0건이면 디스코드로 알린다. 하루 1회로 묶어 두는 이유: 이 작업은 로그온·매시간
# 돌기 때문에 IP 가 빠진 동안 알림이 수십 개 쌓인다.
_NOTIFY = r"C:\Users\cgpar\AI_CLI\scripts\discord-notify.js"
_NOTIFY_STAMP = os.path.join(os.environ.get("TEMP", ROOT), "toss_snapshot_notified.txt")


def _notify_failure():
    today = datetime.now(KST).strftime("%Y-%m-%d")
    try:
        if os.path.exists(_NOTIFY_STAMP) and open(_NOTIFY_STAMP).read().strip() == today:
            return
        if not os.path.exists(_NOTIFY):
            return
        subprocess.run(
            ["node", _NOTIFY, "error", "토스 스냅샷 수집 실패",
             "토스 API 가 한 건도 응답하지 않았습니다. 이 PC 의 공인 IP 가 바뀌어 "
             "허용 IP 목록에서 빠졌을 가능성이 큽니다 — 토스증권 PC웹 → 설정 → "
             "Open API → 허용 IP 관리에서 현재 IP 를 등록하세요. "
             "그 동안 사이트는 기존 소스로 계속 동작합니다."],
            cwd=ROOT, capture_output=True, timeout=30)
        with open(_NOTIFY_STAMP, "w") as f:
            f.write(today)
        log("실패 알림 발송")
    except Exception as e:                                   # noqa: BLE001
        log(f"실패 알림 불가(무시): {e}")


def main():
    if not toss_api.enabled():
        log("TOSS_CLIENT_ID/SECRET 미설정 — 종료")
        return 1
    snap = collect()
    payload_keys = [k for k in snap if k not in ("generatedAt", "source")]
    if not payload_keys:
        log("수집 0건 — 파일 미갱신 (허용 IP 목록에 이 PC 의 공인 IP 가 있는지 확인)")
        # 배경 작업이라 아무도 로그를 안 본다. 가장 흔한 원인(공인 IP 변경으로 허용 목록
        # 이탈)은 조용히 계속 실패하므로 한 번은 알린다.
        _notify_failure()
        return 2
    snap["payloadHash"] = _payload_hash(snap)
    if snap["payloadHash"] == _prev_hash() and "--force" not in sys.argv:
        # generatedAt 을 일부러 갱신하지 않는다. 새 데이터가 없는데 시각만 새로 찍으면
        # fetch_data 의 신선도 가드가 '방금 받은 값'으로 오인한다(정직성 우선).
        log("데이터 변동 없음 — 파일 재작성 생략")
    else:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
        log(f"저장 {OUT} ({os.path.getsize(OUT) // 1024}KB, 항목 {payload_keys})")
    # 푸시 여부는 해시가 아니라 **git 상태**가 정한다. 해시로 파일 재작성을 건너뛰었더라도
    # 직전 실행이 푸시에 실패했으면 워킹트리가 dirty 인 채로 남아 있고, 그걸 계속
    # 방치하면 영영 커밋되지 않는다. git_push() 는 HEAD 와 같으면 스스로 no-op 한다.
    if "--push" in sys.argv:
        return 0 if git_push() else 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
