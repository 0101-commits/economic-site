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
