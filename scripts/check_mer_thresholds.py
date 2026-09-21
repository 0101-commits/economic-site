#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""메르 리스크 렌즈 임계 돌파 속보 (기획안 P5).

왜 만들었나(기획안 D8):
  mer_signals.json 에는 지표마다 '임계선'이 붙어 있다. 그냥 숫자가 아니라 그 선이
  왜 중요한지를 적은 한 줄(meaning)과 출처 인용(quote)이 함께 있다 —
  예: 엔달러 160.0 = "160엔 돌파시 일본 재무성 개입 시작".
  이건 이 저장소가 가진 재료 중 '왜 중요한가'를 말할 수 있는 유일한 것인데,
  대시보드에만 있고 알림에는 한 번도 쓰이지 않았다.

무엇을 보내나:
  **새로 넘은 선만**. 이미 몇 달째 넘어 있는 선(한국 CPI > 2% 등)은 사건이 아니다.
  그래서 직전 런의 돌파 목록을 저장해 두고 차집합만 알린다.

첫 실행:
  비교 대상이 없으므로 '지금 넘어 있는 선'을 조용히 기록만 하고 아무것도 보내지
  않는다. 이 시딩이 없으면 첫 런에서 수십 건이 한꺼번에 나간다.

신선도:
  지표의 asOf 가 MAX_AGE_DAYS 보다 오래됐으면 건너뛴다 — 월간 지표가 갱신도 없이
  같은 값으로 남아 있을 때 '방금 돌파'처럼 보이지 않게.

상태 파일: releases_state.json 의 "mer" 키(같은 워크플로가 커밋하는 파일).
안전: 모든 실패는 경고 후 exit 0 — 수집 워크플로를 깨지 않는다.
"""
import os
import json
import datetime

KST = datetime.timezone(datetime.timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGNALS_PATH = os.path.join(ROOT, "mer_signals.json")
STATE_PATH = os.path.join(ROOT, "releases_state.json")

MAX_AGE_DAYS = 45        # 지표 관측치가 이보다 오래됐으면 '지금 넘었다'고 말하지 않는다
MAX_PER_RUN = 3          # 한 번에 이만큼만 — 여러 선을 동시에 넘어도 한 통으로 묶는다


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _age_days(as_of, now):
    """asOf('2026-09-17' 또는 '202608') → 경과일. 못 읽으면 None."""
    s = str(as_of or "").strip()
    for fmt, cut in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y%m", 6)):
        try:
            return (now.date() - datetime.datetime.strptime(s[:cut], fmt).date()).days
        except ValueError:
            continue
    return None


def crossed_levels(ind):
    """지금 넘어 있는 임계선 → [(level, meaning, quote)]. 수치형(kind=level)만 본다.

    dir='up' 이면 현재값이 그 선 이상일 때, 'down' 이면 이하일 때 넘은 것으로 본다.
    dir 이 없으면 'up' 으로 둔다 — 사전의 임계는 대부분 상향 돌파를 말한다."""
    cur = _f((ind.get("current") or {}).get("value"))
    if cur is None:
        return []
    out = []
    for t in (ind.get("thresholds") or []):
        if t.get("kind") != "level":
            continue                                 # 정성적 서술은 판정할 수 없다
        lv = _f(t.get("level"))
        if lv is None:
            continue
        down = str(t.get("dir") or "up") == "down"
        if (cur <= lv) if down else (cur >= lv):
            out.append((lv, str(t.get("meaning") or "").strip(),
                        str(t.get("quote") or "").strip()))
    return out


def find_new(signals, prev, now=None):
    """(보낼 것 [(ind, level, meaning, quote)], 새 상태 dict, 시딩여부).

    prev 가 비어 있으면 시딩 런 — 기록만 하고 보낼 것은 비운다."""
    now = now or datetime.datetime.now(KST)
    seeding = not prev
    hits, state = [], {}
    for ind in (signals.get("indicators") or []):
        key = str(ind.get("id") or ind.get("label") or "")
        if not key:
            continue
        levels = crossed_levels(ind)
        state[key] = sorted({lv for lv, _, _ in levels})
        if seeding:
            continue
        age = _age_days((ind.get("current") or {}).get("asOf"), now)
        if age is not None and age > MAX_AGE_DAYS:
            continue                                 # 묵은 관측치로 '방금 돌파'를 말하지 않는다
        before = set(prev.get(key) or [])
        for lv, meaning, quote in levels:
            if lv not in before:
                hits.append((ind, lv, meaning, quote))
    return hits, state, seeding


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _fmt(ind, lv, meaning):
    unit = str(ind.get("unit") or "")
    cur = _f((ind.get("current") or {}).get("value"))
    head = f"{ind.get('label')} {cur:g}{unit} — {lv:g}{unit} 돌파"
    return head + (f"\n{meaning}" if meaning else "")


def main():
    signals = _load(SIGNALS_PATH, None)
    if not signals:
        print("[mer] mer_signals.json 읽기 실패 — 건너뜀")
        return
    now = datetime.datetime.now(KST)
    state_all = _load(STATE_PATH, {})
    hits, new_state, seeding = find_new(signals, state_all.get("mer") or {}, now)

    def _save():
        state_all["mer"] = new_state
        try:
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state_all, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except OSError as e:
            print(f"::warning title=메르 임계 상태 저장 실패::{e}")

    if seeding:
        print(f"[mer] 시딩 런 — 지금 넘어 있는 선 {sum(len(v) for v in new_state.values())}개 기록, 발송 없음")
        _save()
        return
    if not hits:
        _save()                                      # 되돌아온(다시 내려간) 선도 반영한다
        return

    hits = hits[:MAX_PER_RUN]
    print(f"[mer] 돌파 {len(hits)}건: {[h[0].get('label') for h in hits]}")
    ind0, lv0, meaning0, quote0 = hits[0]
    body = "\n\n".join(_fmt(i, lv, m) for i, lv, m, _ in hits)
    if quote0:
        body += f"\n\n> {quote0[:300]}"

    sent = False
    try:
        import notify_discord
        png = None
        try:
            import discord_card
            cur = _f((ind0.get("current") or {}).get("value"))
            png = discord_card.status(
                f"{ind0.get('label')} {lv0:g}{ind0.get('unit') or ''} 돌파",
                f"{cur:g}{ind0.get('unit') or ''}", meaning0 or quote0[:80],
                tiles=[("현재", f"{cur:g}", str(ind0.get("unit") or ""), None),
                       ("임계", f"{lv0:g}", str(ind0.get("unit") or ""), None),
                       ("기준일", str((ind0.get("current") or {}).get("asOf") or "—"), "", None)],
                now=now, tone="warn")
        except Exception as e:                       # noqa: BLE001
            print(f"[mer] 카드 렌더 예외({e}) — 텍스트만 발송")
        sent = notify_discord.send(
            body, png=png,
            title=f"🎯 {ind0.get('label')} {lv0:g}{ind0.get('unit') or ''} 돌파 — {meaning0}"[:256],
            url="https://0101-commits.github.io/economic-site/?p=merlens",
            color=notify_discord.COLOR_ALERT, timestamp=True,
            footer=f"메르 리스크 렌즈 · 기준일 {(ind0.get('current') or {}).get('asOf', '—')}",
            env="DISCORD_WEBHOOK_SWINGS",
            buttons=[("🎯 리스크 렌즈",
                      "https://0101-commits.github.io/economic-site/?p=merlens")])
    except Exception as e:                           # noqa: BLE001
        print(f"[mer] 디스코드 발송 예외 무시: {e}")

    if sent:
        _save()                                      # 발송 성공 후에만 확정 — 실패는 다음 런 재시도


def demo():
    """assert 기반 자가 점검 — python scripts/check_mer_thresholds.py --demo."""
    now = datetime.datetime(2026, 9, 21, tzinfo=KST)

    def ind(idv, val, levels, as_of="2026-09-20", unit="%"):
        return {"id": idv, "label": idv, "unit": unit,
                "current": {"value": val, "asOf": as_of},
                "thresholds": [{"kind": "level", "level": lv, "dir": dr,
                                "meaning": f"m{lv}", "quote": f"q{lv}"}
                               for lv, dr in levels]}

    # 상향/하향 판정
    assert [lv for lv, _, _ in crossed_levels(ind("a", 5.0, [(4.0, "up"), (6.0, "up")]))] == [4.0]
    assert [lv for lv, _, _ in crossed_levels(ind("a", 5.0, [(6.0, "down"), (4.0, "down")]))] == [6.0]
    # 정성적 임계는 무시
    q = {"id": "q", "current": {"value": 5}, "thresholds": [{"kind": "qualitative", "level": None}]}
    assert crossed_levels(q) == []

    sig = {"indicators": [ind("a", 5.0, [(4.0, "up"), (6.0, "up")])]}
    # 첫 런 = 시딩 — 기록만 하고 아무것도 안 보낸다
    hits, st, seeding = find_new(sig, {}, now)
    assert seeding and hits == [] and st == {"a": [4.0]}, (hits, st)
    # 같은 상태 = 조용
    hits, st, seeding = find_new(sig, st, now)
    assert not seeding and hits == [], hits
    # 새 선을 넘으면 그것만
    sig2 = {"indicators": [ind("a", 6.5, [(4.0, "up"), (6.0, "up")])]}
    hits, st2, _ = find_new(sig2, st, now)
    assert [h[1] for h in hits] == [6.0], hits
    assert st2 == {"a": [4.0, 6.0]}
    # 다시 내려가면 상태가 되돌아가 다음 돌파를 또 알릴 수 있다
    hits, st3, _ = find_new(sig, st2, now)
    assert hits == [] and st3 == {"a": [4.0]}
    hits, _, _ = find_new(sig2, st3, now)
    assert [h[1] for h in hits] == [6.0]

    # 묵은 관측치는 '방금 돌파'로 보내지 않는다
    old = {"indicators": [ind("a", 6.5, [(4.0, "up"), (6.0, "up")], as_of="2026-01-01")]}
    hits, _, _ = find_new(old, st, now)
    assert hits == [], hits
    # 날짜 형식 세 가지
    assert _age_days("2026-09-20", now) == 1
    assert _age_days("202608", now) is not None
    assert _age_days("2026-08", now) is not None
    assert _age_days("", now) is None

    print("check_mer_thresholds.py 자가 점검 통과")


if __name__ == "__main__":
    import sys
    if "--demo" in sys.argv:
        demo()
    else:
        main()
