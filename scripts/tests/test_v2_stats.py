"""설정 화면 숫자(P5) — 지난 원장에 지금 규칙을 대 본 하루 폰 알림 통수."""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts_v2 import stats  # noqa: E402


def _r(key, ev, tgt, level, ts, **sent):
    return {"key": key, "event": ev, "target": tgt, "level": level, "ts": f"{ts}+09:00", "sent": sent or {"push": 1}}


def _day(tmp, day, rows):
    with open(os.path.join(tmp, f"{day}.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)


def test_rules_quiet_story_cap_and_morning_brief(tmp_path):
    d = "2026-11-05"
    rows = [
        _r(f"BRIEF:morning:{d}", "BRIEF", "morning", "brief", f"{d}T07:30:00"),
        _r(f"A3:wti:up:{d}", "A3", "wti", "alert", f"{d}T02:00:00", held=True),              # 밤 주의 → 아침 브리핑에 합류
        _r(f"A5:kospi:enter:{d}.sidecar", "A5", "kospi", "alarm", f"{d}T09:21:00"),
        _r(f"A5:kospi:enter:{d}.circuit1", "A5", "kospi", "alarm", f"{d}T09:26:00"),          # 단계 오름
        _r(f"A1:kospi:down:{d}:t5", "A1", "kospi", "alarm", f"{d}T09:26:00"),                # 같은 이야기 낮은 단계
        _r(f"A1:kosdaq:down:{d}:t5", "A1", "kosdaq", "alarm", f"{d}T09:30:00"),              # 같은 무리(국내 증시)
        _r(f"A4:btc:down:{d}", "A4", "btc", "alert", f"{d}T10:00:00"),
        _r(f"B2:usdkrw:up:{d}", "B2", "usdkrw", "alert", f"{d}T11:00:00"),
        _r(f"E1:calendar:new:{d}", "E1", "calendar", "notice", f"{d}T12:00:00"),
        _r(f"U1:x:up:{d}", "U1", "005930", "alert", f"{d}T12:00:00"),                        # 내 조건은 안 센다
        {"key": f"A2:sox:up:{d}", "event": "A2", "target": "sox", "level": "alert", "ts": f"{d}T13:00:00+09:00", "sent": {}},  # 꺼져 있던 것
    ]
    _day(str(tmp_path), d, rows)
    s = stats.build(dt.date(2026, 11, 6), root=str(tmp_path))
    assert s["days"] == 1 and s["from"] == d
    # 보통: 아침 1 + 사이드카 1 + 서킷 1 + 비트코인 1 + 원·달러 1 = 5 (밤 주의 · 같은 이야기 · 안내 · 내 조건 · 꺼진 것 제외)
    assert s["sim"]["normal:10:q"] == [5.0, 5]
    assert s["sim"]["normal:10:n"] == [6.0, 6]                 # 조용한 시간 끔 = 밤 주의도 울림
    assert s["sim"]["normal:1:q"] == [5.0, 5]                  # 상한 1: 비트코인 1 + 넘친 원·달러 묶음 1
    assert s["sim"]["quiet:5:q"] == [3.0, 3]                   # 조용히 = 경보 + 아침
    assert s["sim"]["many:15:q"] == [6.0, 6]                   # 많이 = 안내(그때 켜져 있던 E1)도 한 통


def test_write_file_and_empty_ledger(tmp_path):
    p = stats.write(end=dt.date(2026, 11, 6), root=str(tmp_path))
    s = json.load(open(p, encoding="utf-8"))
    assert s["days"] == 0 and s["sim"]["normal:10:q"] == [0, 0] and len(s["sim"]) == 3 * 50 * 2
