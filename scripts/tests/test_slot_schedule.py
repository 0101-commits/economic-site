#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""발송 슬롯 단일 원천 — 워크플로 게이트와 파이썬 편성표가 같은 시각을 봐야 한다.

kakao-daily.yml 이 '지금 발송할 시각인가'를 판정하고, send_kakao_digest.py 가
'그 시각의 편성'을 고른다. 둘이 어긋나면 게이트는 통과하는데 파이썬이 '가장 가까운
슬롯'으로 스냅해 엉뚱한 편성이 나간다 — 예외도 경고도 없다. 워크플로 주석이 이미
"같은 값이어야 한다"고 적어 두었지만, 주석은 어긋남을 막지 못한다.
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import send_kakao_digest as K  # noqa: E402

YML = open(os.path.join(ROOT, ".github", "workflows", "kakao-daily.yml"),
           encoding="utf-8").read()


def _hours():
    """게이트의 HOURS 두 줄 → (평일, 주말) 시각 목록."""
    got = [sorted(int(h) for h in m.split())
           for m in re.findall(r'HOURS="([\d ]+)"', YML)]
    assert len(got) == 2, f"HOURS 줄이 2개가 아니다: {got}"
    return got


def test_weekday_and_weekend_slots_match():
    weekend, weekday = _hours()            # YAML 순서: 주말 → 평일
    assert weekday == sorted(K.SLOT_HOURS_WEEKDAY)
    assert weekend == sorted(K.SLOT_HOURS_WEEKEND)


def test_close_time_matches():
    """마감 리포트 시각 — 15:45 로 앞당기면 수급이 KRX 잠정치다(2026-09-11 회귀)."""
    m = re.search(r'"\$H" = "(\d+)" \] && \[ "\$M" -ge (\d+)', YML)
    assert m, "마감 게이트 조건을 못 찾았다 — 조건식이 바뀌었으면 이 테스트도 따라와야 한다"
    assert (int(m.group(1)), int(m.group(2))) == K.CLOSE_AT


def test_every_slot_has_a_lineup():
    """게이트가 통과시키는 시각마다 편성이 있어야 한다(없으면 ALL_BLOCKS 로 새어 나간다)."""
    weekend, weekday = _hours()
    for h in weekday + weekend:
        assert f"h{h:02d}" in K.SLOT_BLOCKS, f"h{h:02d} 편성 없음"


def test_briefing_cron_matches_slots():
    """briefing.yml 의 cron(UTC) → KST 시각 · 요일이 briefing.SLOT_AT 과 같고, 슬롯 판정 case 가 그 cron 을 그 슬롯으로 읽는다.
    여섯 슬롯이 전부 한 번씩 있어야 한다 — cron 한 줄을 고치고 case 를 안 고치면 그 시각 깨움이 슬롯 없이 끝난다."""
    from alerts_v2 import briefing
    yml = open(os.path.join(ROOT, ".github", "workflows", "briefing.yml"), encoding="utf-8").read()
    got = {}
    for cron, slot in re.findall(r"- cron: '([^']+)'\s+#\s*(\w+)", yml):
        mi, hr, _d, _m, dow = cron.split()
        days = set()
        for part in dow.split(","):
            a, _, b = part.partition("-")
            days.update(range(int(a), int(b or a) + 1))
        shift, rest = divmod(int(hr) * 60 + int(mi) + 9 * 60, 24 * 60)
        kst_days = tuple(sorted((c - 1 + shift) % 7 for c in days))         # cron 0=일 → 파이썬 6=일
        got[slot] = (rest // 60, rest % 60, kst_days)
        assert f"'{cron}') slot={slot} ;;" in yml, f"슬롯 판정 case 에 {cron} → {slot} 이 없다"
    assert got == {s: (h, m, tuple(sorted(dd))) for s, (h, m, dd) in briefing.SLOT_AT.items()}


def test_worker_v2_dispatch_matches_crons():
    """Worker 매분 cron 이 깨우는 알림 v2 표(worker.js V2_DISPATCH, UTC)가 briefing.yml · alerts-v2.yml 의 cron · 슬롯과
    같아야 하고, 그 event_type 을 워크플로가 받아야 한다. GHA schedule 은 5~7시간 늦게 발화해(2026-10-06 실측:
    마감 16:30 → 23:20 KST) Worker 깨움이 본선이다 — 표가 어긋나면 그 슬롯은 다시 늦고, 이름이 어긋나면 dispatch 는
    204 로 성공하고 워크플로만 안 깨어난다."""
    worker = open(os.path.join(ROOT, "cloudflare-worker", "worker.js"), encoding="utf-8").read()
    block = worker.split("export const V2_DISPATCH = [", 1)[1].split("];", 1)[0]
    got = {(f"{mi} {hr} * * {dow}", ev, name)
           for mi, hr, dow, ev, name in re.findall(r"\[(\d+), (\d+), '([\d,*-]+)', '([\w-]+)', \{ \w+: '(\w+)' \}\]", block)}
    want = set()
    for yml_name, ev, pat in (("briefing.yml", "brief", r"- cron: '([^']+)'\s+#\s*(\w+)"),
                              ("alerts-v2.yml", "alerts-v2", r"- cron: '([^']+)'.*—\s*(\w+)\s*$")):
        yml = open(os.path.join(ROOT, ".github", "workflows", yml_name), encoding="utf-8").read()
        found = re.findall(pat, yml, re.M)
        assert found, f"{yml_name} 에서 cron 줄을 못 읽었다"
        want.update((cron, ev, name) for cron, name in found)
        assert re.search(r"repository_dispatch:\s*\n\s*types:\s*\[\s*%s\s*\]" % re.escape(ev), yml), f"{yml_name} 가 {ev} 를 안 받는다"
    assert got == want
