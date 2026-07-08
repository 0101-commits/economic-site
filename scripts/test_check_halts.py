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


def _fire(now, hid="circuit-KOSPI-20260708"):
    return {"id": hid, "type": "circuit", "market": "KOSPI", "stage": 1,
            "direction": "down", "reason": "지수 전일比 -8.0%", "source": "index",
            "triggeredAt": now.isoformat(),
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
    """발동 발송이 계속 실패해 재시도 소진(포기)된 뒤 거래 재개 → '해제'를 보내면 안 된다."""
    _reset()
    now = datetime.datetime(2026, 7, 8, 14, 0, tzinfo=KST)
    ev = _fire(now)
    FAIL["on"] = True
    for _ in range(ch.GIVE_UP_TRIES):        # 3회 발송 실패 → 포기
        _run([ev])
    st = _state()
    assert st[ev["id"]]["pending"] is False, st          # 포기 확정
    assert not st[ev["id"]].get("fireSent"), st          # 발동 미발송
    assert SENT == [], SENT                              # 아무것도 도달 못함

    FAIL["on"] = False
    _run([])                                             # 거래 재개(해제)
    assert SENT == [], f"유령 해제 발송됨: {SENT}"          # ★ 핵심: 해제 미발송
    assert ev["id"] not in _state(), _state()            # 조용히 폐기


def test_stale_pending_index_then_resolve_no_ghost():
    """stale 로 index 발동이 계속 보류되다 해제되면 '해제'를 보내면 안 된다."""
    _reset()
    now = datetime.datetime(2026, 7, 8, 14, 0, tzinfo=KST)
    ev = _fire(now)
    _run([ev], stale=True)                               # stale → index 발동 보류(발송 0)
    assert SENT == [], SENT
    _run([], stale=True)                                 # 해제
    assert SENT == [], f"유령 해제 발송됨: {SENT}"
    assert ev["id"] not in _state(), _state()


def test_happy_fire_then_resolve():
    """정상 경로: 발동 성공 → 재개 시 해제 발송, 상태 확정."""
    _reset()
    now = datetime.datetime(2026, 7, 8, 14, 0, tzinfo=KST)
    ev = _fire(now)
    _run([ev])
    assert len(SENT) == 1 and "발동" in SENT[0], SENT
    assert _state()[ev["id"]]["fireSent"] is True

    SENT.clear()
    _run([])                                             # 재개
    assert len(SENT) == 1 and "해제" in SENT[0], SENT
    assert _state()[ev["id"]]["resolvedSent"] is True


def test_fire_retry_succeeds_second_run():
    """1회차 발송 실패(pending) → 2회차 성공 → 중복 없이 1통, 이후 정상 해제."""
    _reset()
    now = datetime.datetime(2026, 7, 8, 14, 0, tzinfo=KST)
    ev = _fire(now)
    FAIL["on"] = True
    _run([ev])                                           # 실패 → pending
    assert SENT == [] and _state()[ev["id"]]["pending"] is True
    FAIL["on"] = False
    _run([ev])                                           # 재시도 성공
    assert len(SENT) == 1 and "발동" in SENT[0], SENT
    assert _state()[ev["id"]]["fireSent"] is True


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("ALL PASS")


if __name__ == "__main__":
    run()
