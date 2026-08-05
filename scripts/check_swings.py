#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""시장 급변 속보(옵션 A) — 지수·환율이 임계치를 넘게 움직이면 슬롯과 무관하게 즉시 카카오톡 1통.

stock-alerts.yml 의 별도 스텝으로 장중 매분(Worker cron dispatch) 실행된다.
서킷브레이커 알림(check_halts, -8% 이상 시장 중단)과 역할 구분 — 이쪽은 그 '전 단계' 조기 경보.

규칙(기획안 2026-08-05):
  코스피 ±2% / S&P500 ±2% / 달러-원 ±1% (전일 종가 대비, Yahoo 라이브)
도배 방지:
  같은 심볼·같은 방향은 하루(KST) 1회 — 방향이 바뀌면(급락→급반등) 당일에도 다시 알린다.
  쿨다운은 alerts_state.json 의 "_swings" 키에 기록(소유권 본 스크립트,
  check_alerts._write_state 가 '_' 접두 키를 보존한다). 워크플로 커밋 경로는 기존 그대로.
안전:
  발송 성공 후에만 쿨다운 확정(실패 시 다음 런 재시도). 시세 오염(|pct|>50%)·휴장(fresh=False)
  스킵. 모든 실패는 경고 후 exit 0 — 매분 런이라 job 실패 = 실패 메일 폭탄.
"""
import os
import json
import datetime

import check_alerts as ca               # yahoo_snapshot / is_market_open 재사용
import send_kakao_digest as kakao       # 토큰 재발급·발송 공용

KST = datetime.timezone(datetime.timedelta(hours=9))
STATE_PATH = ca.STATE_PATH              # alerts_state.json — "_swings" 키만 소유

# (표시명, Yahoo 심볼, 세션, |전일比%| 임계) — 세션 "ANY"=본 워크플로가 도는 시간대 전부(한·미 장중)
SWING_RULES = [
    ("코스피", "^KS11", "KR", 2.0),
    ("S&P500", "^GSPC", "US", 2.0),
    ("달러-원", "KRW=X", "ANY", 1.0),
]
SANE_PCT = 50.0                          # 프록시 글리치 폐기선(지수·환율에 50%면 충분)


def _session_open(market, now):
    if market == "ANY":
        return ca.is_market_open("KR", now) or ca.is_market_open("US", now)
    return ca.is_market_open(market, now)


def main():
    if os.environ.get("ALERTS_TEST") == "true":
        print("[swings] 테스트 dispatch — 급변 속보는 건너뜀(정규 cron 만 평가)")
        return
    now = datetime.datetime.now(KST)
    day = now.strftime("%Y-%m-%d")

    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    swings = state.get("_swings") or {}

    hits = []                            # (쿨다운 키, 발송 줄)
    for name, sym, market, thr in SWING_RULES:
        if not _session_open(market, now):
            continue
        snap = ca.yahoo_snapshot(sym)
        if not snap:
            print(f"[swings] 시세 조회 실패: {name}({sym}) — 건너뜀")
            continue
        pct = snap.get("pct") or 0.0
        if snap["price"] <= 0 or abs(pct) > SANE_PCT:
            print(f"::warning title=시세 이상::{name} {snap['price']} {pct}% — 오염 의심, 건너뜀")
            continue
        if snap.get("fresh") is False:
            continue                     # 휴장(공휴일)/스테일 — 전일 종가로 오발동 방지
        if abs(pct) < thr:
            continue
        direction = "up" if pct > 0 else "down"
        key = f"{sym}:{direction}:{day}"
        if key in swings:
            continue                     # 같은 방향은 하루 1회
        arrow = "▲" if pct > 0 else "▼"
        nd = 1 if sym == "KRW=X" else 0              # 환율만 소수 1자리, 지수는 정수(단위 없음)
        hits.append((key, f"{name} {snap['price']:,.{nd}f} {arrow}{abs(pct):.1f}%"))
        print(f"[swings] 급변 감지: {hits[-1][1]}")

    if not hits:
        return

    msg = (f"⚡ {now.month}/{now.day} {now.hour:02d}:{now.minute:02d} 시장 급변\n"
           + "\n".join(line for _, line in hits)
           + f"\n{ca.DELAY_NOTICE}")

    # 카카오 + 디스코드 병행 — 어느 한쪽이라도 성공하면 쿨다운 확정(같은 급변 재발송 방지).
    # 둘 다 실패한 경우만 미확정 → 다음 분 런이 재시도. job 은 항상 green(실패 메일 방지).
    sent_ok = False
    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if rest_key and refresh_token:
        try:
            access_token = kakao.refresh_access_token(rest_key, refresh_token)
            friends = kakao.get_friends(access_token) if kakao._friends_enabled() else []
            kakao.send_memo(access_token, msg, with_button=True, uuids=[f["uuid"] for f in friends])
            sent_ok = True
        except (SystemExit, Exception) as e:
            print(f"::warning title=급변 속보 카카오 실패::{e} — 디스코드 경로 시도")
    else:
        print("::warning title=Kakao 미설정::급변 속보 카카오 건너뜀 (KAKAO_SETUP.md 참고)")
    try:
        import notify_discord
        if notify_discord.send(msg):
            sent_ok = True
    except Exception as e:
        print(f"[discord] 병행 발송 예외 무시: {e}")
    if not sent_ok:
        return

    # 발송 성공 후에만 쿨다운 확정 — 당일 키만 남겨 상태 파일이 자라지 않게 한다.
    swings = {k: v for k, v in swings.items() if k.endswith(day)}
    for key, _ in hits:
        swings[key] = now.isoformat()
    state["_swings"] = swings
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError as e:
        print(f"::warning title=쿨다운 저장 실패::{e} — 같은 급변이 한 번 더 올 수 있음")
    print(f"[swings] 발송 완료 — {len(hits)}건")


if __name__ == "__main__":
    main()
