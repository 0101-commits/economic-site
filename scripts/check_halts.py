#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""시장중단(서킷브레이커·사이드카) 카카오톡 알림.

stock-alerts.yml 에서 장중 5분(Worker cron 보강 시 그 이하) 주기로 실행된다. 기본은
HALTS_LIVE=1 라이브 모드 — ^KS11/^KQ11 시세를 직접 조회해 감지하고(fetch-data 경유의 실효
지연 15분+ 해소), 라이브 조회가 실패하면 data.json.marketHalts(fetch_data.py 산출) 폴백.
직전 발송 이력(halts_state.json)과 비교해 '신규 발동'·'단계 격상'·'해제'만 보낸다.

도배 방지: 사건 id 당 발동 1회 + 단계 격상 시 1회 + 해제 1회. 이력은 halts_state.json 에
남고 stock-alerts 워크플로가 커밋해 런 간 보존한다(소유권은 stock-alerts 로 단일화).

테스트 발송: HALTS_TEST=1 이면 가짜 사건 1건만 보내 경로를 검증하며 이력을 갱신하지 않는다.

필요 Secrets: KAKAO_REST_API_KEY, KAKAO_REFRESH_TOKEN (시황 다이제스트와 공용)."""
import os
import json
import datetime

import market_halts                 # 라이브 모드 감지 재사용 (scripts/ 가 sys.path[0])
import send_kakao_digest as kakao   # scripts/ 가 sys.path[0]

KST = datetime.timezone(datetime.timedelta(hours=9))
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA_PATH = os.path.join(ROOT, "data.json")
STATE_PATH = os.path.join(ROOT, "halts_state.json")
# ⚠️ HALTS_TEST=1 일 때만 테스트(가짜 사건) 발송. repository_dispatch 전체를 테스트로 보면 안 된다 —
#    Worker cron 의 정시성 보강용 fetch-data dispatch 런에서 가짜 서킷브레이커가 발송되기 때문.
#    테스트 경로(halts-test.yml)는 HALTS_TEST=1 을 명시 전달한다.
IS_TEST = os.environ.get("HALTS_TEST") == "1"
# 🔴 라이브 모드 — ^KS11/^KQ11 시세를 직접 조회해 감지(HALTS_LIVE=1, stock-alerts.yml 이 설정).
#    미설정이면 종전대로 data.json.marketHalts 만 사용(halts-test.yml·수동 실행 호환).
IS_LIVE = os.environ.get("HALTS_LIVE") == "1"
# 발동 발송 실패 재시도는 '시간 기준' — 사건 resumeAt(endOfDay 면 당일 장마감 15:30)까지 pending
# 유지·재시도하고, 그 후에도 실패면 ::error 1회 + 확정한다(횟수 기준 3회는 일시 장애에 너무 짧았음).
# 해제 발송은 사건 시한이 없어 횟수 상한으로 영구 잔존을 막는다.
RESOLVE_GIVE_UP_TRIES = 10   # 해제 발송 실패 상한 — 도달 시 확정(state 영구 잔존 방지)

TYPE_KO = {"circuit": "서킷브레이커", "sidecar": "사이드카"}
DELAY_NOTICE = "※ 최대 15분 지연 가능 · 정확한 시각은 거래소/증권사 앱 확인"
# 라이브 시세 조회용 UA — check_alerts.py 의 시세 조회 패턴과 동일
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")


def _now():
    return datetime.datetime.now(KST)


def _hm(iso):
    try:
        return datetime.datetime.fromisoformat(iso).astimezone(KST).strftime("%H:%M")
    except (ValueError, TypeError):
        return "-"


def _fire_msg(h, escalated=False):
    typ = TYPE_KO.get(h.get("type"), h.get("type"))
    stage = f" {h['stage']}단계" if h.get("type") == "circuit" and h.get("stage") else ""
    icon = "🔴" if h.get("type") == "circuit" else "🟠"
    verb = "격상" if escalated else "발동"    # 격상 = 이미 발동을 보낸 사건의 단계 상승 재알림
    lines = [f"{icon} [시장경보] {h.get('market', '')} {typ}{stage} {verb}",
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


def _parse_kst(iso):
    """ISO 문자열 → KST aware datetime (tz 없으면 KST 로 간주). 실패 시 None."""
    try:
        d = datetime.datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    return d.replace(tzinfo=KST) if d.tzinfo is None else d.astimezone(KST)


def _retry_deadline(h):
    """발동 발송 재시도 시한 — endOfDay(3단계) 사건은 당일 장마감 15:30 KST, 그 외는 resumeAt.
    파싱 불가 시 triggeredAt+40분(1·2단계 중단 30분+여유) — 시한 없이 영구 재시도하지 않게."""
    trig = _parse_kst(h.get("triggeredAt"))
    if h.get("endOfDay"):
        base = trig or _now()
        return base.replace(hour=15, minute=30, second=0, microsecond=0)
    resume = _parse_kst(h.get("resumeAt"))
    if resume:
        return resume
    return (trig or _now()) + datetime.timedelta(minutes=40)


def _event_stage(rec):
    """state 레코드에 기록된(마지막으로 알림 대상이 된) 사건의 CB 단계 — 격상 판정 기준."""
    return ((rec or {}).get("event") or {}).get("stage") or 0


def _fire_confirmed(rec):
    """'발동'을 실제로 보냈는가 — 해제 발송 자격. 구 스키마 호환: pending 개념 도입 전 레코드는
    fireSent 키가 없고 firedAt 만 있는데, 당시엔 기록=발송이었으므로 발송한 것으로 판별한다
    (없으면 해제 시 abandoned 로 오분류되어 해제 알림이 유실된다)."""
    return bool(rec.get("fireSent") or ("pending" not in rec and rec.get("firedAt")))


# ── 라이브 감지 (HALTS_LIVE=1) ──────────────────────────────────
def _yahoo_quote(symbol):
    """Yahoo v8 chart 로 (현재가, 전일比%) 조회 — check_alerts.yahoo_snapshot 의 축약판.
    urllib 만 사용(추가 의존성 없음). 실패 시 None — 호출측이 data.json 폴백."""
    import urllib.request
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Accept": "application/json,text/plain,*/*"})
        with urllib.request.urlopen(req, timeout=15) as r:
            j = json.load(r)
        res = ((((j or {}).get("chart") or {}).get("result")) or [None])[0] or {}
        meta = res.get("meta") or {}
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price is None or not prev:
            return None
        return float(price), (float(price) / float(prev) - 1) * 100.0
    except Exception:
        return None


def _live_market_halts(prev_data, now):
    """^KS11/^KQ11 라이브 시세로 marketHalts 를 직접 산출 — fetch-data 경유(성공 런 소요
    12~57분 실측)의 실효 감지주기 15분+ 문제 해소. repo 의 data.json 을 prev 로 삼아 이월·해제
    판단은 market_halts.detect_market_halts 를 그대로 재사용한다.
    ⚠️ 라이브 결과를 data.json 에 쓰지 않는다(프론트 표시는 fetch_data 소관 유지).
    두 지수 모두 조회 실패 시 None → 호출측이 기존 data.json.marketHalts 폴백(현행 동작)."""
    indices = {}
    for market, sym in (("KOSPI", "^KS11"), ("KOSDAQ", "^KQ11")):
        q = _yahoo_quote(sym)
        if q:
            indices[market] = {"value": q[0], "change": q[1]}
    if not indices:
        return None
    return market_halts.detect_market_halts({"indices": indices}, prev_data, now)


def main():
    now = _now()
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        print("[halts] data.json 없음/파싱 실패 — 종료")
        return
    halts = data.get("marketHalts") or {}
    # 🔴 라이브 모드 — 시세를 직접 조회해 감지. 실패 시 위의 data.json.marketHalts 폴백(현행 동작).
    if IS_LIVE and not IS_TEST:
        live = _live_market_halts(data, now)
        if live is not None:
            halts = live
            print(f"[halts] 라이브 감지 — active {len(live.get('active') or [])}건")
        else:
            print("[halts] 라이브 시세 조회 실패 — data.json.marketHalts 폴백")
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
    # 발송 대상 판정:
    #   • 미기록(rec 없음) 또는 pending=True(직전 런 발송 실패 재시도 대기) → 발동 발송 대상.
    #   • CB 단계 격상(-8→-15→-20%): 기록된 event 의 stage 보다 높아지면 재발송 대상 — 종전엔
    #     id 기준만 봐서 1단계 발송 후 2·3단계(최중요: 3단계=당일 장 종료)가 영영 미발송됐다.
    #     ⚠️ id 에 stage 를 넣는 방식은 해제 매칭·이월이 깨지므로 금지 — stage 비교로 판정한다.
    new_events = []
    escalated_ids = set()          # '격상' 재알림(이미 발동을 보낸 사건의 단계 상승) 표기용
    for h in active:
        rec = state.get(h["id"])
        # 격상 판정은 event 를 기록한 레코드만 — 구 스키마(event 없음) 레코드를 stage 0 으로 봐서
        # 활성 사건을 격상으로 오인·재발송하지 않게 한다.
        esc = (rec is not None and rec.get("event") is not None
               and (h.get("stage") or 0) > _event_stage(rec))
        if rec is None or rec.get("pending") or esc:
            new_events.append(h)
            if esc and _fire_confirmed(rec):
                escalated_ids.add(h["id"])
    # active 에서 사라진(=거래 재개) 사건들. 이 중 '발동을 실제로 보낸' 것만 해제 발송.
    # 발동을 끝내 못 보낸 사건(전송 실패 후 재시도 시한 경과 포기, 또는 stale 로 index 발동이 계속
    # 보류된 채로 해제)에 '해제'만 보내면 사용자가 '발동' 없이 '해제'만 받는 유령 알림이 된다 →
    # abandoned 로 분류해 조용히 제거한다. (_fire_confirmed: 구 스키마 firedAt-만 레코드 호환)
    gone_ids = [hid for hid in state
                if hid not in active_ids and not state[hid].get("resolvedSent")]
    resolved_ids = [hid for hid in gone_ids if _fire_confirmed(state[hid])]
    abandoned_ids = [hid for hid in gone_ids if not _fire_confirmed(state[hid])]

    # 🛡 데이터 신선도 가드 — 지수 수집이 비어 halt 감지가 '깜깜이'로 돈 빌드(marketHalts.stale=True)
    #    에서는 지수기반(source=index) 신규 발동을 신뢰하지 않는다. 뉴스/KRX 출처와 '해제'는 그대로 처리.
    if halts.get("stale"):
        dropped = [h for h in new_events if h.get("source") == "index"]
        if dropped:
            print(f"::warning title=시세 stale::지수 데이터 부재로 index 기반 신규 발동 {len(dropped)}건 보류")
        new_events = [h for h in new_events if h.get("source") != "index"]

    if new_events or resolved_ids:
        # 🛡 신규/격상 사건은 '발송 가능 여부와 무관하게' 먼저 state 에 pending 기록 — 토큰 장애 중
        #    발동한 halt 가 state 에 없으면 장애 중 해제됐을 때 무기록으로 영구 유실되기 때문.
        #    tries 는 실제 발송 시도 직전에만 증가시킨다(기록만 하는 런이 재시도 예산을 소모하지 않게).
        for h in new_events:
            rec = state.get(h["id"]) or {}
            if h["id"] in escalated_ids:
                rec["tries"] = 0           # 격상 = 새 알림 — 재시도 카운터 리셋
            rec["event"] = h               # 격상 시 최신 stage 로 갱신(안 하면 매 런 격상 재발송 스팸)
            rec["firedAt"] = rec.get("firedAt") or now.isoformat()
            rec["resolvedSent"] = False
            rec["pending"] = True
            state[h["id"]] = rec
        _flush_state(state)                # 발송 전 디스크 확정 — 크래시에도 기록 보존

        token = None
        if not rest_key or not refresh_token:
            print("::warning title=Kakao 미설정::KAKAO secrets 없음 — 발송 건너뜀(사건은 pending 기록)")
        else:
            try:
                token = kakao.refresh_access_token(rest_key, refresh_token)
            except (SystemExit, Exception) as e:   # SystemExit(응답오류) + 네트워크예외(URLError/timeout)
                # 발송 대상이 있는데 토큰 실패 = 최중요 알림 경로 장애 → ::error 승격(가시화)
                print(f"::error title=Kakao 토큰 재발급 실패::{e} — 발송 불가(사건은 pending 기록, 다음 런 재시도)")
                token = None
        if token:
            uuids = [f["uuid"] for f in kakao.get_friends(token)] if kakao._friends_enabled() else []
            # 🛡 발송 '전' tries 증가 + 디스크 확정 — 러너 크래시·전송예외에도 시도 이력이 남아
            #    무한 재발송을 막는다. 성공하면 pending 해제(확정)해 중복도 막는다.
            for h in new_events:
                state[h["id"]]["tries"] = int(state[h["id"]].get("tries", 0)) + 1
            _flush_state(state)

            # 발동/격상 발송 — 건별 독립 처리(하나 실패가 다른 건을 막지 않음). 실패는 pending 유지
            #   (다음 런 재시도)하되 '시간 기준' 시한: 사건 resumeAt(endOfDay 는 당일 장마감 15:30)
            #   까지 재시도, 그 후에도 실패면 ::error 1회 + 확정(이미 재개된 시장의 발동 알림은 무의미).
            for h in new_events:
                rec = state[h["id"]]
                esc = h["id"] in escalated_ids
                try:
                    _send_all(token, uuids, _fire_msg(h, escalated=esc))
                    rec["pending"] = False
                    rec["tries"] = 0
                    rec["fireSent"] = True   # 발동 실제 발송 확정 — 이후 '해제' 발송 자격
                    print(f"[halts] {'격상' if esc else '발동'} 발송: {h['id']}")
                except (SystemExit, Exception) as e:
                    if now >= _retry_deadline(h):
                        rec["pending"] = False
                        print(f"::error title=halt 발송 포기::{h['id']}({e}) 재시도 시한 경과 — 확정(중복 방지)")
                    else:
                        print(f"::warning title=halt 발송 실패::{h['id']}({e}) — 다음 런 재시도")

            # 해제 발송 — 성공 시에만 resolvedSent=True(실패 시 다음 런 재시도). 단 상한
            #   (RESOLVE_GIVE_UP_TRIES) 도달 시 확정해 state 영구 잔존을 방지.
            for hid in resolved_ids:
                rec = state[hid]
                h = rec.get("event") or {"id": hid}
                rec["resolveTries"] = int(rec.get("resolveTries", 0)) + 1
                try:
                    _send_all(token, uuids, _resolve_msg(h))
                    rec["resolvedSent"] = True
                    rec["resolvedAt"] = now.isoformat()
                    print(f"[halts] 해제 발송: {hid}")
                except (SystemExit, Exception) as e:
                    if rec["resolveTries"] >= RESOLVE_GIVE_UP_TRIES:
                        rec["resolvedSent"] = True
                        rec["resolvedAt"] = now.isoformat()
                        print(f"::warning title=halt 해제 발송 포기::{hid}({e}) "
                              f"{RESOLVE_GIVE_UP_TRIES}회 실패 — 확정(잔존 방지)")
                    else:
                        print(f"::warning title=halt 해제 발송 실패::{hid}({e}) — 다음 런 재시도")
    else:
        print(f"[halts] 변동 없음 — active {len(active)}건")

    # '발동'을 끝내 못 보낸 채 거래 재개된 사건 제거 — 해제 발송 없이 조용히 폐기(유령 해제 방지).
    for hid in abandoned_ids:
        if state.pop(hid, None) is not None:
            print(f"[halts] 발동 미발송 사건 폐기(해제 미발송): {hid}")

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
