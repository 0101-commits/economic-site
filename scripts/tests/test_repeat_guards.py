#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""같은 알림 반복 가드 3종 — python scripts/tests/test_repeat_guards.py

① 급변 속보 쿨다운 키가 KST 자정에 바뀌지 않는다(환율·US 는 KST-9h 날짜).
② 환율 일봉이 어제 것이면 주인공 후보에서 빠진다.
③ z_move 는 cool60 이어도 하루 1회.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import check_alerts as ca       # noqa: E402
import check_swings as cs       # noqa: E402
import discord_card as dc       # noqa: E402

KST = datetime.timezone(datetime.timedelta(hours=9))

# ① 9/22 10:40 발송분과 9/23 00:00 이 같은 키
a = datetime.datetime(2026, 9, 22, 10, 40, tzinfo=KST)
b = datetime.datetime(2026, 9, 23, 0, 0, tzinfo=KST)
assert cs._move_day("ANY", a) == cs._move_day("ANY", b) == "2026-09-22"
assert cs._move_day("ANY", datetime.datetime(2026, 9, 23, 9, 1, tzinfo=KST)) == "2026-09-23"
assert cs._move_day("KR", b) == "2026-09-23"

# ② 환율만, 어제 봉이면 제외
assert dc._stale_fx("fx", [{"date": "2026-09-22"}], today="2026-09-23")
assert not dc._stale_fx("fx", [{"date": "2026-09-23"}], today="2026-09-23")
assert not dc._stale_fx("indices", [{"date": "2026-09-22"}], today="2026-09-23")

# ③ z_move cool60 — 1시간 지나도 같은 날이면 재발송 안 함
now = datetime.datetime(2026, 9, 22, 11, 41, tzinfo=KST)
rec = {"date": "20260922", "ts": int(now.timestamp()) - 3700}
st = {"x": rec}
assert not ca.should_send({"id": "x", "type": "z_move", "limit": "cool60", "market": "KR"}, st, now)
assert ca.should_send({"id": "x", "type": "high52", "limit": "cool60", "market": "KR"}, st, now)
print("ok")

# ④ 같은 날 주인공 반복 — 더 커지지 않으면 건너뛰고, 0.5σ 이상 커지면 다시 주인공
import json as _json                   # noqa: E402
import tempfile                        # noqa: E402
import send_kakao_digest as sk         # noqa: E402
assert sk._repeat("USDKRW", -3.0, {"USDKRW": -2.8})
assert not sk._repeat("USDKRW", -3.4, {"USDKRW": -2.8})       # 확대
assert not sk._repeat("USDKRW", 2.9, {"USDKRW": -2.8})        # 방향 전환
assert not sk._repeat("KOSPI", 2.5, {"USDKRW": -2.8})
_p = os.path.join(tempfile.mkdtemp(), "f.json")
_t = datetime.datetime(2026, 9, 22, 12, 2, tzinfo=KST)
sk.record_focus(("USDKRW", -2.8), _t, path=_p)
sk.record_focus(("KOSPI", None), _t, path=_p)                  # 고정 주인공은 기록 안 함
assert sk.load_focus_seen(_t, path=_p) == {"USDKRW": -2.8}
assert sk.load_focus_seen(_t + datetime.timedelta(days=1), path=_p) == {}   # 날짜 바뀌면 초기화

# pick_focus 가 seen 을 받아 반복 자산을 고정 주인공으로 돌린다(합성 데이터)
_d = {"fx": {"USDKRW": {"rate": 1350.0, "change": -1.6}},
      "indices": {"KOSPI": {"price": 7000.0, "change": 0.1}},
      "history": {"fx": {"USDKRW": [{"date": "2026-09-22", "close": 1380 + (i % 3)} for i in range(300)]
                         + [{"date": _t.strftime("%Y-%m-%d"), "close": 1350.0}]}}}
_d["history"]["fx"]["USDKRW"][-1]["date"] = datetime.datetime.now(KST).strftime("%Y-%m-%d")
k1 = sk.pick_focus(_d, "h12", False, _t)[0]
k2 = sk.pick_focus(_d, "h12", False, _t, seen={"USDKRW": sk.pick_focus(_d, "h12", False, _t)[1] or -9})[0]
assert k1 == "USDKRW", k1
assert k2 == "KOSPI", k2
print("ok ④")
