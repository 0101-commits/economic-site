#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_halts 카카오 발송/상태 로직 테스트 — pytest 없이 직접 실행.
실행: python scripts/test_check_halts.py  (성공 시 'ALL PASS').

핵심 회귀: '발동'을 실제로 못 보낸 사건에 '해제'만 발송되는 유령 알림 방지(fireSent 게이트).
카카오 네트워크 발송은 스텁으로 대체해 결정적으로 검증한다."""
import os
import sys
import json
import tempfile
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                                    # Windows cp949 콘솔에서도 한글/em-dash 로그 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass
os.environ["KAKAO_REST_API_KEY"] = "dummy"
os.environ["KAKAO_REFRESH_TOKEN"] = "dummy"
os.environ.pop("HALTS_TEST", None)
os.environ.pop("HALTS_LIVE", None)      # 라이브 모드 비활성 — 네트워크 없이 결정적으로 테스트

import check_halts as ch

KST = datetime.timezone(datetime.timedelta(hours=9))

# ── 카카오 발송 스텁 ─────────────────────────────────────────────
SENT = []          # 실제 발송된 메시지 텍스트 기록
FAIL = {"on": False}


def _stub_send_memo(access_token, text, with_button=True, uuids=None):
    if FAIL["on"]:
        raise SystemExit("[stub] 발송 실패 시뮬레이션")
    SENT.append(text)


ch.kakao.refresh_access_token = lambda k, t: "STUB_TOKEN"
ch.kakao._friends_enabled = lambda: False        # uuids=[] → 메모 경로(스텁이 가로챔)
ch.kakao.get_friends = lambda t: []
ch.kakao.send_memo = _stub_send_memo


# ── 임시 data.json / halts_state.json ───────────────────────────
_TMP = tempfile.mkdtemp(prefix="halts_test_")
ch.DATA_PATH = os.path.join(_TMP, "data.json")
ch.STATE_PATH = os.path.join(_TMP, "halts_state.json")


def _fire(now, hid="circuit-KOSPI-20260708", stage=1):
    # ⚠ 발동 재시도 시한이 '시간 기준'(resumeAt 까지)이 되어, 재시도 시나리오는 resumeAt 이
    #   미래(now+30분)여야 한다 — 테스트는 실행 시각(ch._now()) 기준으로 사건을 만든다.
    return {"id": hid, "type": "circuit", "market": "KOSPI", "stage": stage,
            "direction": "down", "reason": f"지수 전일比 {-8.0 if stage == 1 else -15.0}%",
            "source": "index", "triggeredAt": now.isoformat(),
            "resumeAt": (now + datetime.timedelta(minutes=30)).isoformat(),
            "endOfDay": False}


def _run(active, stale=False):
    with open(ch.DATA_PATH, "w", encoding="utf-8") as f:
        json.dump({"marketHalts": {"active": active, "stale": stale}}, f)
    ch.main()


def _state():
    try:
        with open(ch.STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _reset():
    SENT.clear()
    FAIL["on"] = False
    for p in (ch.DATA_PATH, ch.STATE_PATH):
        try:
            os.remove(p)
        except OSError:
            pass


# ── 테스트 ──────────────────────────────────────────────────────
def test_ghost_resolve_suppressed_after_giveup():
    """발동 발송이 재시도 시한(resumeAt) 경과까지 실패해 포기된 뒤 거래 재개 → '해제' 금지."""
    _reset()
    past = ch._now() - datetime.timedelta(hours=2)       # resumeAt(=past+30분)도 이미 경과
    ev = _fire(past)
    FAIL["on"] = True
    _run([ev])                                           # 시한 경과 상태의 발송 실패 → 즉시 포기 확정
    st = _state()
    assert st[ev["id"]]["pending"] is False, st          # 포기 확정(::error 1회)
    assert not st[ev["id"]].get("fireSent"), st          # 발동 미발송
    assert SENT == [], SENT                              # 아무것도 도달 못함
    _run([ev])                                           # 같은 사건 재등장 → 재발송 안 함(스팸 차단)
    assert SENT == [], SENT

    FAIL["on"] = False
    _run([])                                             # 거래 재개(해제)
    assert SENT == [], f"유령 해제 발송됨: {SENT}"          # ★ 핵심: 해제 미발송
    assert ev["id"] not in _state(), _state()            # 조용히 폐기


def test_stale_pending_index_then_resolve_no_ghost():
    """stale 로 index 발동이 계속 보류되다 해제되면 '해제'를 보내면 안 된다."""
    _reset()
    ev = _fire(ch._now())
    _run([ev], stale=True)                               # stale → index 발동 보류(발송 0)
    assert SENT == [], SENT
    _run([], stale=True)                                 # 해제
    assert SENT == [], f"유령 해제 발송됨: {SENT}"
    assert ev["id"] not in _state(), _state()


def test_happy_fire_then_resolve():
    """정상 경로: 발동 성공 → 재개 시 해제 발송, 상태 확정."""
    _reset()
    ev = _fire(ch._now())
    _run([ev])
    assert len(SENT) == 1 and "발동" in SENT[0], SENT
    assert _state()[ev["id"]]["fireSent"] is True

    SENT.clear()
    _run([])                                             # 재개
    assert len(SENT) == 1 and "해제" in SENT[0], SENT
    assert _state()[ev["id"]]["resolvedSent"] is True


def test_fire_retry_succeeds_second_run():
    """1회차 발송 실패(pending, 시한 전) → 2회차 성공 → 중복 없이 1통, 이후 정상 해제."""
    _reset()
    ev = _fire(ch._now())                                # resumeAt = now+30분(시한 전 → 재시도 유지)
    FAIL["on"] = True
    _run([ev])                                           # 실패 → pending
    assert SENT == [] and _state()[ev["id"]]["pending"] is True
    FAIL["on"] = False
    _run([ev])                                           # 재시도 성공
    assert len(SENT) == 1 and "발동" in SENT[0], SENT
    assert _state()[ev["id"]]["fireSent"] is True


def test_stage_escalation_realerts():
    """B 회귀: CB 1단계 발송 후 2단계 격상(-8→-15%) → '격상' 재알림 1통, 매 런 스팸 없음,
    이후 해제 1통. (종전엔 id 기준만 봐서 격상이 영영 미발송)."""
    _reset()
    now = ch._now()
    _run([_fire(now, stage=1)])                          # 1단계 발동 발송
    assert len(SENT) == 1 and "발동" in SENT[0], SENT
    SENT.clear()

    ev2 = _fire(now, stage=2)                            # 같은 id, 2단계 격상
    _run([ev2])
    assert len(SENT) == 1 and "격상" in SENT[0] and "2단계" in SENT[0], SENT
    st = _state()[ev2["id"]]
    assert st["event"]["stage"] == 2 and st["fireSent"] is True, st  # event 갱신(스팸 방지 근거)
    assert st["tries"] == 0, st                          # 격상 재발송 성공 → 카운터 리셋

    SENT.clear()
    _run([ev2])                                          # 같은 2단계 재등장 → 재발송 없음
    assert SENT == [], f"격상 스팸: {SENT}"

    _run([])                                             # 재개 → 해제 1통
    assert len(SENT) == 1 and "해제" in SENT[0], SENT


def test_pending_recorded_without_token():
    """D 회귀: 토큰 장애 중 발동한 사건도 state 에 pending 으로 남아야 한다(무기록 유실 방지).
    tries 는 실제 발송 시도가 아니므로 소모되지 않는다."""
    _reset()
    ev = _fire(ch._now())

    # ① secrets 자체가 없는 런
    os.environ["KAKAO_REST_API_KEY"] = ""
    try:
        _run([ev])
    finally:
        os.environ["KAKAO_REST_API_KEY"] = "dummy"
    st = _state()
    assert st[ev["id"]]["pending"] is True, st           # ★ 핵심: 기록은 남는다
    assert st[ev["id"]].get("tries", 0) == 0, st         # 발송 시도 아님 → 예산 미소모
    assert SENT == [], SENT

    # ② 토큰 재발급 실패 런
    orig = ch.kakao.refresh_access_token
    ch.kakao.refresh_access_token = lambda k, t: (_ for _ in ()).throw(SystemExit("token dead"))
    try:
        _run([ev])
    finally:
        ch.kakao.refresh_access_token = orig
    st = _state()
    assert st[ev["id"]]["pending"] is True and SENT == [], (st, SENT)

    # ③ 토큰 복구 → pending 재시도로 정상 발송
    _run([ev])
    assert len(SENT) == 1 and "발동" in SENT[0], SENT
    assert _state()[ev["id"]]["fireSent"] is True


def test_resolve_giveup_cap():
    """E 회귀: 해제 발송이 계속 실패해도 상한(RESOLVE_GIVE_UP_TRIES) 도달 시 확정 —
    state 에 영구 잔존해 매 런 재시도 스팸이 되는 것을 방지."""
    _reset()
    ev = _fire(ch._now())
    _run([ev])                                           # 발동 성공
    SENT.clear()
    FAIL["on"] = True
    for _ in range(ch.RESOLVE_GIVE_UP_TRIES):            # 해제 발송 10회 연속 실패
        _run([])
    st = _state()
    assert st[ev["id"]]["resolvedSent"] is True, st      # 상한 도달 → 확정(잔존 방지)
    assert SENT == [], SENT


def test_legacy_record_resolves():
    """F 회귀: 구 스키마 레코드(fireSent/pending 없음, firedAt 만) → 해제 시 abandoned 로
    오분류하지 않고 '해제'를 발송한다."""
    _reset()
    now = ch._now()
    hid = "circuit-KOSPI-20260701"
    with open(ch.STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({hid: {"firedAt": now.isoformat(), "resolvedSent": False}}, f)
    _run([])                                             # active 에 없음 = 해제
    assert len(SENT) == 1 and "해제" in SENT[0], SENT
    assert _state()[hid]["resolvedSent"] is True


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("ALL PASS")


if __name__ == "__main__":
    run()
