#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""묶음 사용률 게이트 — data.json 최상위 키의 바로 아래 하위 키(객체가 아니면 키 그대로) 중 어느 묶음(meta 포함)에도
값이 실리지 않는 칸 목록.

판정은 '값이 실렸나'다. 묶음 생성 결과의 잎(문자열·숫자)이 data.json 의 어느 최상위 키 아래 있던 **바로 그 객체**인지
id() 로 대조한다. json.load 는 값마다 새 객체를 만들므로(키 이름만 메모한다) 같은 값이 우연히 다른 키에서 온 것으로
잡히지 않는다 — 값 비교와 달리 자료가 바뀌어도 결과가 흔들리지 않는다. 다만 CPython 이 공유하는 객체(None·참/거짓·
작은 정수 -5~256·한 글자 문자열)는 출처를 가를 수 없어 센다에서 뺀다. 계산해 새로 만든 값(반올림 등락·합계)은 실린 것으로
치지 않는다 — 원본 잎이 하나라도 실려야 그 칸을 '읽었다'고 본다(최상위 키 단위로 보면 잎 하나로 키 전체가 통과했다).

기준선(UNREAD)보다 늘면 실패 — 새 수집 키를 묶음에 안 싣고 두면 여기서 걸린다. 줄면 기준선을 줄인다.
실행: python -m pytest scripts/tests/test_bundle_usage.py -q
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import build_bundles as bb  # noqa: E402

# 기준선. 「키」는 그 아래 하위 키 전부, 「키.하위키」는 그 칸만 면한다.
UNREAD = [
    # 운영 기록이라 화면 묶음에 실을 일이 없다 — sources(수집 출처 표) · diagnostics(수집 진단) · historyVersion(옛 화면 캐시 꼬리표)
    "diagnostics", "historyVersion", "sources",
    # 수집 꼬리표(수집 시각 · 출처 글) — 묶음은 기준 시각 · 상태를 따로 만들어 싣는다(계산한 새 값이라 실린 것으로 안 친다)
    "aiBriefing.date", "aiBriefing.generatedAt", "corpEvents.source", "economicCalendar.lastFetched", "economicCalendar.source",
    "freight.lastFetched", "freight.source", "investorTrading.lastFetched", "investorTrading.recentSource",
    "lmeInventory.lastFetched", "lmeInventory.source", "marketBreadth.source", "marketCalendarKr.generatedAt",
    "nps.lastFetched", "rankingsKr.source", "sectorMoves.source", "stockFlows.source", "subscription.lastFetched",
    # 묶음이 판정에만 쓰고 값을 옮기지 않는 칸 — 휴장 판정(오늘 · 다음 영업일), 교차검증 결과, 기업코드 표, 엘니뇨 영향 문장
    "marketCalendarKr.nextBusinessDay", "marketCalendarKr.today", "investorTrading.crossCheck", "corpEvents.corpMap", "climate.impact",
]
excused = lambda u: any(u == e or u.startswith(e + ".") for e in UNREAD)


def _leaves(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _leaves(v)
    elif isinstance(o, list):
        for v in o:
            yield from _leaves(v)
    elif o is not None and not isinstance(o, bool) \
            and not (isinstance(o, int) and -5 <= o <= 256) and not (isinstance(o, str) and len(o) <= 1):
        yield o


def _units(data):
    """판정 단위 — 최상위 키가 객체면 그 바로 아래 하위 키마다 '키.하위키', 아니면(목록·값) 키 그대로."""
    for k, node in data.items():
        if isinstance(node, dict) and node:
            for sk, v in node.items():
                yield "%s.%s" % (k, sk), v
        else:
            yield k, node


def unread_keys(data, mer, now, toss=None):
    """판정 단위(_units) 중 묶음 잎으로 한 번도 실리지 않은 것(이름순). 잎 하나만 실려도 그 최상위 키 전체를 '읽음'으로
    치지 않게 하위 키마다 따로 본다. owner 는 잎 객체 참조도 쥔다 — 빌드가 data 를 고쳐 원본 잎이 풀리면 그 id 가
    새 값에 다시 쓰여 엉뚱한 단위를 '읽음'으로 잡을 수 있다."""
    owner, units = {}, set()
    for u, node in _units(data):
        for v in _leaves(node):   # 셀 잎이 없는 단위(빈 목록 · null 뿐)는 판정할 수 없어 뺀다 — 자료가 비는 날 게이트가 흔들리지 않게
            owner[id(v)] = (u, v)
            units.add(u)
    b = bb.build_all(data, mer, now, toss)
    out = {k: v for k, v in b.items() if not k.startswith("_")}
    out["meta"] = bb.meta(data, mer, {}, now, b)
    used = {owner[id(v)][0] for v in _leaves(out) if id(v) in owner and owner[id(v)][1] is v}
    return sorted(units - used)


def probe_times(data):
    """수집 5분 뒤와 그날 08:30(장 전). 시각 따라 실리는 키가 있다 — marketCalendarKr 의 직전 영업일은 장 전에만
    세션 날짜로 실린다. 두 시각 모두에서 안 실려야 '안 읽는 키'다(CI 런 시각에 따라 게이트가 흔들리지 않게)."""
    t = bb._iso_dt(data["lastUpdated"]).astimezone(bb.KST)
    return [t + dt.timedelta(minutes=5), t.replace(hour=8, minute=30, second=0, microsecond=0)]


def unread_now(data, mer, toss=None):
    return sorted(set.intersection(*(set(unread_keys(data, mer, n, toss)) for n in probe_times(data))))


def test_unread_keys_do_not_grow():
    data, mer = bb.load("data.json"), bb.load("mer_signals.json", {})
    got = unread_now(data, mer, bb.load("toss_snapshot.json", {}))
    new = [u for u in got if not excused(u)]
    assert not new, "묶음에 안 실리는 data.json 칸이 늘었다: %r — 묶음에 싣거나(build_bundles.py) 이유를 적고 기준선에 더할 것" % new


def test_identity_check_catches_dropped_key():
    """판정 장치 자체 — 실린 키는 빠지고, 안 실린 키는 남는다."""
    data = {"lastUpdated": "2026-10-07T10:00:00+09:00", "sentiment": {"fear_greed": {"value": 47.3}, "zzSide": {"v": 12345.5}},
            "zzUnused": {"x": "아무도 안 읽는 값"}, "zzEmpty": {"x": []}}
    got = unread_keys(data, {}, bb._iso_dt(data["lastUpdated"]))
    # 하위 키 단위: 같은 최상위 키의 다른 칸이 실려도 안 실린 칸은 남는다 · 셀 잎이 없는 칸은 판정하지 않는다
    assert got == ["sentiment.zzSide", "zzUnused.x"], got


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(unread_now(bb.load("data.json"), bb.load("mer_signals.json", {}), bb.load("toss_snapshot.json", {})))
