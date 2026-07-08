#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""시장중단(서킷브레이커·사이드카) 카카오톡 알림.

fetch_data.py 가 data.json.marketHalts.active 에 현재 발동 사건을 기록한다. 본 스크립트는
fetch-data.yml 에서 fetch_data.py 직후 실행되어, 직전 발송 이력(halts_state.json)과 비교해
'신규 발동' 과 '해제'만 카카오톡으로 보낸다.

도배 방지: 사건 id 당 발동 1회 + 해제 1회. 이력은 halts_state.json 에 남고 워크플로가
data.json 과 함께 커밋해 런 간 보존한다.

테스트 발송: HALTS_TEST=1 이면 가짜 사건 1건만 보내 경로를 검증하며 이력을 갱신하지 않는다.

필요 Secrets: KAKAO_REST_API_KEY, KAKAO_REFRESH_TOKEN (시황 다이제스트와 공용)."""
import os
import json
import datetime

import send_kakao_digest as kakao   # scripts/ 가 sys.path[0]

KST = datetime.timezone(datetime.timedelta(hours=9))
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA_PATH = os.path.join(ROOT, "data.json")
STATE_PATH = os.path.join(ROOT, "halts_state.json")
# ⚠️ HALTS_TEST=1 일 때만 테스트(가짜 사건) 발송. repository_dispatch 전체를 테스트로 보면 안 된다 —
#    Worker cron 의 정시성 보강용 fetch-data dispatch 런에서 가짜 서킷브레이커가 발송되기 때문.
#    테스트 경로(halts-test.yml)는 HALTS_TEST=1 을 명시 전달한다.
IS_TEST = os.environ.get("HALTS_TEST") == "1"
GIVE_UP_TRIES = 3   # 발동 발송 실패 재시도 상한 — 넘게 실패하면 확정(무한 재시도·크래시 스팸 방지)

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


def _flush_state(state):
    """halts_state.json 디스크 기록 — '발송 전'에도 호출해 크래시/전송예외에도 재발송을 막는다."""
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


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
    # pending=True = 직전 런에서 발송에 실패해 재시도 대기 중인 발동 → 다시 발송 대상에 포함(누락 방지).
    new_events = [h for h in active
                  if h["id"] not in state or state[h["id"]].get("pending")]
    resolved_ids = [hid for hid in state
                    if hid not in active_ids and not state[hid].get("resolvedSent")]

    # 🛡 데이터 신선도 가드 — 지수 수집이 비어 halt 감지가 '깜깜이'로 돈 빌드(marketHalts.stale=True)
    #    에서는 지수기반(source=index) 신규 발동을 신뢰하지 않는다. 뉴스/KRX 출처와 '해제'는 그대로 처리.
    if halts.get("stale"):
        dropped = [h for h in new_events if h.get("source") == "index"]
        if dropped:
            print(f"::warning title=시세 stale::지수 데이터 부재로 index 기반 신규 발동 {len(dropped)}건 보류")
        new_events = [h for h in new_events if h.get("source") != "index"]

    if new_events or resolved_ids:
        if not rest_key or not refresh_token:
            print("::warning title=Kakao 미설정::KAKAO secrets 없음 — 발송 건너뜀")
        else:
            try:
                token = kakao.refresh_access_token(rest_key, refresh_token)
            except SystemExit as e:
                print(f"::error title=Kakao 토큰 재발급 실패::{e} — 발송 건너뜀(다음 런 재시도)")
                token = None
            if token:
                uuids = [f["uuid"] for f in kakao.get_friends(token)] if kakao._friends_enabled() else []
                # 🛡 발송 '전' 디스크 확정 — 러너 크래시·전송예외에도 재발송 상한(GIVE_UP_TRIES). 각 건을
                #    pending=True 로 두어 발송 성공 확인 전엔 재시도 대상으로 남긴다(전송 실패 시 다음 런
                #    재발송 = 서킷브레이커 같은 최중요 알림 누락 방지). 성공하면 pending 해제해 중복도 막는다.
                for h in new_events:
                    rec = state.get(h["id"]) or {}
                    rec["event"] = h
                    rec["firedAt"] = rec.get("firedAt") or now.isoformat()
                    rec["resolvedSent"] = False
                    rec["tries"] = int(rec.get("tries", 0)) + 1
                    rec["pending"] = True
                    state[h["id"]] = rec
                _flush_state(state)                       # 발송 전 디스크 확정

                # 발동 발송 — 건별 독립 처리(하나 실패가 다른 건을 막지 않음). 성공만 pending 해제(확정),
                #   실패는 pending 유지(다음 런 재시도), 단 tries 상한 도달 시 포기(확정)해 무한 재발송 차단.
                for h in new_events:
                    rec = state[h["id"]]
                    try:
                        _send_all(token, uuids, _fire_msg(h))
                        rec["pending"] = False
                        rec["tries"] = 0
                        print(f"[halts] 발동 발송: {h['id']}")
                    except (SystemExit, Exception) as e:
                        if int(rec.get("tries", 0)) >= GIVE_UP_TRIES:
                            rec["pending"] = False
                            print(f"::warning title=halt 재시도 포기::{h['id']} {GIVE_UP_TRIES}회 실패 — 확정(중복 방지)")
                        else:
                            print(f"::warning title=halt 발송 실패::{h['id']}({e}) — 다음 런 재시도")

                # 해제 발송 — 성공 시에만 resolvedSent=True(실패 시 다음 런 재시도).
                for hid in resolved_ids:
                    h = state[hid].get("event") or {"id": hid}
                    try:
                        _send_all(token, uuids, _resolve_msg(h))
                        state[hid]["resolvedSent"] = True
                        state[hid]["resolvedAt"] = now.isoformat()
                        print(f"[halts] 해제 발송: {hid}")
                    except (SystemExit, Exception) as e:
                        print(f"::warning title=halt 해제 발송 실패::{hid}({e}) — 다음 런 재시도")
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
    _flush_state(cleaned)
    print(f"[halts] 완료 — active {len(active)}, 신규 {len(new_events)}, 해제 {len(resolved_ids)}")


if __name__ == "__main__":
    main()
