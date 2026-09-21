#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""경제지표 발표 속보 — 발표된 값이 예상과 얼마나 달랐는지 알린다(기획안 P4).

왜 만들었나(기획안 D6):
  data.economicCalendar.events[] 에는 직전치(prev)·예상치(fore)·실제치(act)·서프라이즈
  부호(beat)가 이미 들어 있었는데, 알림은 "오늘 미국 CPI 21:30 ★★★" 라는 예고 한 줄만
  보내고 결과는 한 번도 보내지 않았다. 시장이 반응하는 것은 수치 자체가 아니라 예상과의
  격차다 — 경제캘린더 해설의 기본 명제다.

무엇을 보내나:
  오늘 발표분 중 ★★ 이상이면서 '이례적'인 것만. 이례성 판정은 두 갈래다.
    ① 예상치가 있으면 → 예상 대비 격차(SURPRISE_MIN 이상).
    ② 예상치가 없으면 → 그 지표의 과거 분포에서 상·하위 PCTILE_EDGE% 인지.
  FRED 는 컨센서스를 제공하지 않아 현재 예상치가 있는 이벤트는 일부뿐이다. 그래서 ②가
  주 경로다 — 컨센서스 소스를 새로 붙이지 않고도 "평소와 다른 값인가"를 말할 수 있다.

타이밍에 대한 정직한 한계:
  실제치는 fetch_data 의 캘린더 백필이 FRED 시리즈에서 가져온다. 즉 이 알림은 '발표 순간'이
  아니라 '우리 데이터가 그 값을 받은 직후'에 나간다(시간별 풀 런 기준 최대 1시간). 그래서
  제목도 '속보'가 아니라 발표 결과로 적는다.

도배 방지: 같은 (지표, 발표일)은 한 번만. 이력은 **releases_state.json** 에 둔다.
  alerts_state.json 을 쓰지 않는 이유: 그 파일의 소유권은 stock-alerts.yml 에 있고,
  이 스크립트는 fetch-data.yml 에서 돈다. 두 워크플로가 같은 상태 파일을 커밋하면
  push 경쟁이 나고, 커밋되지 않은 쪽은 이력을 잃어 매 런마다 같은 알림을 다시 보낸다
  (halts_state.json 소유권을 단일화한 것과 같은 이유).
안전: 모든 실패는 경고 후 exit 0 — 수집 워크플로를 깨지 않는다.
"""
import os
import re
import json
import datetime

KST = datetime.timezone(datetime.timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, "data.json")
STATE_PATH = os.path.join(ROOT, "releases_state.json")

MIN_STARS = 2            # ★★ 미만은 아예 보지 않는다
EVERYONE_STARS = 3       # ★★★ 만 @everyone — 나머지는 무멘션
# 예상 대비 격차가 이만큼(%p) 넘으면 '예상과 달랐다'로 본다. 미국 CPI 전월비가 0.1%p
# 어긋나는 것은 흔하지만 0.2%p 는 헤드라인이 된다.
SURPRISE_MIN = 0.2
# 예상치가 없을 때의 대체 판정 — 과거 분포의 양 끝 이 %.
PCTILE_EDGE = 10.0
# 분포 판정에 쓸 최소 관측 수. 이보다 적으면 '평소'를 말할 수 없다.
MIN_HISTORY = 24


def _num(s):
    """'+2.1%' · '1,465K' · '-0.7' → float. 못 읽으면 None."""
    if s is None:
        return None
    m = re.search(r"[-+]?\d[\d,]*\.?\d*", str(s))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _get_by_path(data, path):
    node = data
    for part in str(path).split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _history_values(data, name):
    """이벤트 이름 → 실제치(act)와 **같은 단위**의 과거 값 목록(시간순). 없으면 [].

    ⚠ 원시 history 를 그대로 쓰면 안 된다. 미국 CPI 의 history 는 지수 레벨(273~334)인데
    캘린더의 act 는 전월비 %(+0.4%)라, 그대로 비교하면 언제나 '하위 0%'가 되어 매달
    거짓 알림이 나간다. CALENDAR_INDICATOR_MAP 의 fmt 코드가 어떤 변환을 거쳐 act 가
    만들어졌는지 말해 주므로, 같은 변환을 과거 전체에 적용해 비교 가능한 계열을 만든다."""
    try:
        import fetch_data
        mp = (fetch_data.CALENDAR_INDICATOR_MAP or {}).get(name)
    except Exception:                                        # noqa: BLE001
        return []
    if not mp:
        return []
    node = _get_by_path(data, mp[0])
    hist = (node or {}).get("history") or {}
    if not isinstance(hist, dict):
        return []
    fmt = mp[1]
    lv = []
    for k in sorted(hist):
        v = _num(hist[k])
        if v is not None:
            lv.append(v)
    if fmt == "mom1":                                        # 전월비 % — 직전 관측 대비
        return [(lv[i] / lv[i - 1] - 1) * 100
                for i in range(1, len(lv)) if lv[i - 1]]
    if fmt == "yoy1":                                        # 전년비 % — 12개 전 대비
        return [(lv[i] / lv[i - 12] - 1) * 100
                for i in range(12, len(lv)) if lv[i - 12]]
    return lv                                                # raw·pct·k 는 레벨 그대로


def percentile_of(value, values):
    """values 분포에서 value 의 백분위(0~100). 표본 부족이면 None."""
    if value is None or len(values) < MIN_HISTORY:
        return None
    below = sum(1 for v in values if v < value)
    ties = sum(1 for v in values if v == value)
    return (below + 0.5 * ties) / len(values) * 100


def judge(ev, hist):
    """이벤트 → (보낼까?, 근거 한 줄). 이례적이지 않으면 (False, "").

    예상치가 있으면 그 격차를, 없으면 과거 분포에서의 위치를 근거로 쓴다.
    둘 다 못 구하면 보내지 않는다 — '발표됐다'만으로는 알림이 될 이유가 없다."""
    act, fore = _num(ev.get("act")), _num(ev.get("fore"))
    if act is None:
        return False, ""
    if fore is not None:
        gap = act - fore
        if abs(gap) >= SURPRISE_MIN:
            return True, f"예상 {ev['fore']} → 실제 {ev['act']} ({gap:+.1f}%p 차이)"
        return False, ""
    pct = percentile_of(act, hist)
    if pct is None:
        return False, ""
    if pct >= 100 - PCTILE_EDGE:
        return True, f"실제 {ev['act']} — 과거 {len(hist)}회 중 상위 {100 - pct:.0f}%"
    if pct <= PCTILE_EDGE:
        return True, f"실제 {ev['act']} — 과거 {len(hist)}회 중 하위 {pct:.0f}%"
    return False, ""


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def collect(data, today=None):
    """오늘 발표분 중 보낼 것 → [(ev, 근거)]. 순서는 별점 내림차순."""
    today = today or datetime.datetime.now(KST).strftime("%Y-%m-%d")
    out = []
    for ev in ((data.get("economicCalendar") or {}).get("events") or []):
        if not isinstance(ev, dict) or str(ev.get("iso", ""))[:10] != today:
            continue
        if int(ev.get("stars") or 0) < MIN_STARS:
            continue
        ok, why = judge(ev, _history_values(data, ev.get("name", "")))
        if ok:
            out.append((ev, why))
    out.sort(key=lambda t: -(t[0].get("stars") or 0))
    return out


def main():
    data = _load(DATA_PATH, None)
    if not data:
        print("[releases] data.json 읽기 실패 — 건너뜀")
        return
    now = datetime.datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    state = _load(STATE_PATH, {})
    seen = state.get("sent") or {}

    hits = [(ev, why) for ev, why in collect(data, today)
            if f"{ev.get('name')}:{today}" not in seen]
    if not hits:
        return

    ev0, why0 = hits[0]
    stars = int(ev0.get("stars") or 0)
    lines = []
    for ev, why in hits:
        lines.append(f"{'★' * int(ev.get('stars') or 0)} {ev.get('name')}\n{why}")
    body = "\n\n".join(lines)
    print(f"[releases] 발송 대상 {len(hits)}건: {[e.get('name') for e, _ in hits]}")

    sent_ok = False
    try:
        import notify_discord
        png = None
        try:
            import discord_card
            png = discord_card.surprise(ev0, why0, now,
                                        hist=_history_values(data, ev0.get('name', '')))
        except Exception as e:                               # noqa: BLE001
            print(f"[releases] 카드 렌더 예외({e}) — 텍스트만 발송")
        sent_ok = notify_discord.send(
            body, png=png,
            title=f"📊 {ev0.get('name')} {ev0.get('act')} — {why0}"[:256],
            url="https://0101-commits.github.io/economic-site/?p=market",
            color=notify_discord.COLOR_FIRE if stars >= EVERYONE_STARS
            else notify_discord.COLOR_ALERT,
            footer=f"{ev0.get('dt', '')} 발표 · 출처 {ev0.get('source', 'FRED')}",
            timestamp=True, mention=(stars >= EVERYONE_STARS),
            env="DISCORD_WEBHOOK_SWINGS",
            buttons=[("📈 경제지표", "https://0101-commits.github.io/economic-site/?p=market")])
    except Exception as e:                                   # noqa: BLE001
        print(f"[releases] 디스코드 발송 예외 무시: {e}")

    # 카카오는 디스코드와 같은 내용으로(사용자 결정 2026-09-21: 두 채널 동일).
    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if rest_key and refresh_token:
        try:
            import send_kakao_digest as kakao
            token = kakao.refresh_access_token(rest_key, refresh_token)
            friends = kakao.get_friends(token) if kakao._friends_enabled() else []
            kpng = None
            try:
                import discord_card
                kpng = discord_card.surprise(
                    ev0, why0, now,
                    hist=_history_values(data, ev0.get('name', '')), shape="square")
            except Exception:                                # noqa: BLE001
                pass
            kakao.send_card(token, f"{ev0.get('name')} {ev0.get('act')}"[:44], why0[:120],
                            png=kpng, uuids=[f["uuid"] for f in friends], kind="지표 발표",
                            buttons=[("경제지표",
                                      "https://0101-commits.github.io/economic-site/?p=market")])
            sent_ok = True
        except (SystemExit, Exception) as e:                 # noqa: BLE001
            print(f"::warning title=지표 발표 카카오 실패::{e}")

    if not sent_ok:
        return                                               # 다음 런이 재시도
    # 발송 성공 후에만 확정. 오늘 키만 남겨 상태 파일이 자라지 않게 한다.
    seen = {k: v for k, v in seen.items() if k.endswith(today)}
    for ev, _ in hits:
        seen[f"{ev.get('name')}:{today}"] = now.isoformat()
    state["sent"] = seen
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError as e:
        print(f"::warning title=발송 이력 저장 실패::{e} — 같은 발표가 한 번 더 올 수 있음")


def demo():
    """assert 기반 자가 점검 — python scripts/check_releases.py --demo."""
    assert _num("+2.1%") == 2.1 and _num("-0.7%") == -0.7
    assert _num("1,465K") == 1465.0 and _num(None) is None and _num("") is None

    # 예상치가 있으면 격차로 판정
    ok, why = judge({"act": "+0.4%", "fore": "+0.1%"}, [])
    assert ok and "+0.3%p" in why, why
    ok, _ = judge({"act": "+0.2%", "fore": "+0.1%"}, [])
    assert not ok                                            # 0.1%p 는 흔하다

    # 예상치가 없으면 분포로 판정
    hist = [float(i % 10) for i in range(60)]                # 0~9 균등
    ok, why = judge({"act": "9.5"}, hist)
    assert ok and "상위" in why, why
    ok, why = judge({"act": "-1"}, hist)
    assert ok and "하위" in why, why
    ok, _ = judge({"act": "5"}, hist)
    assert not ok                                            # 한가운데
    ok, _ = judge({"act": "9.5"}, hist[:10])
    assert not ok                                            # 표본 부족이면 침묵

    # 실제치가 없으면(발표 전) 아무 일도 없다
    ok, _ = judge({"act": "", "fore": "+0.1%"}, hist)
    assert not ok

    # 과거 계열은 act 와 같은 단위여야 한다 — 지수 레벨을 그대로 쓰면 매번 '하위 0%'가
    # 되어 거짓 알림이 나간다(실측 결함). mom1 은 전월비 %로 변환된다.
    class _FD:
        CALENDAR_INDICATOR_MAP = {"L": ("x.y", "mom1", True), "R": ("x.y", "raw1", True)}
    import sys as _sys
    _sys.modules["fetch_data"] = _FD
    lvl = {f"2020-{m:02d}": 100.0 * (1.01 ** m) for m in range(1, 13)}
    got = _history_values({"x": {"y": {"history": lvl}}}, "L")
    assert len(got) == 11 and all(abs(g - 1.0) < 1e-6 for g in got), got[:3]
    got_raw = _history_values({"x": {"y": {"history": lvl}}}, "R")
    assert len(got_raw) == 12 and got_raw[0] == 101.0, got_raw[:3]
    del _sys.modules["fetch_data"]

    # collect 는 오늘·★★ 이상·이례적인 것만 고른다
    data = {"economicCalendar": {"events": [
        {"iso": "2026-09-21", "name": "X", "stars": 3, "act": "+0.4%", "fore": "+0.1%"},
        {"iso": "2026-09-21", "name": "Y", "stars": 1, "act": "+0.9%", "fore": "+0.1%"},
        {"iso": "2026-09-20", "name": "Z", "stars": 3, "act": "+0.9%", "fore": "+0.1%"},
        {"iso": "2026-09-21", "name": "W", "stars": 3, "act": "+0.1%", "fore": "+0.1%"},
    ]}}
    got = [e.get("name") for e, _ in collect(data, "2026-09-21")]
    assert got == ["X"], got

    print("check_releases.py 자가 점검 통과")


if __name__ == "__main__":
    import sys
    if "--demo" in sys.argv:
        demo()
    else:
        main()
