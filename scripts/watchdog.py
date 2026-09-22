#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""알림 파이프라인 상시 감시 — '알림이 안 오는 상황' 자체를 알린다.

왜 만들었나:
  이 저장소의 가장 위험한 실패는 시끄러운 실패가 아니라 침묵이다. 실제로 2026-08-19 에
  생긴 좀비 queued 런 하나가 Cloudflare Worker 의 dispatch 게이트를 34일간 막았고,
  그동안 장중 매분 평가가 통째로 멈춰 있었다 — 워크플로는 전부 초록이었고 아무 알림도
  오지 않았다. 사람이 로그를 열어 보고서야 알았다.

  heartbeat.py 는 data.json 신선도를 하루 한 번 본다. 이 스크립트는 그 위층 —
  '워크플로 자체가 돌고 있는가'를 본다. 둘은 겹치지 않는다.

두 가지 모드:
  failure  워크플로 런이 실패했을 때 즉시(workflow_run 트리거). 어느 스텝이 죽었는지까지.
  silence  주기적으로 '최근 런이 있는가'를 본다(schedule). dispatch 가 끊기면 실패 런이
           생기지 않으므로 failure 모드로는 절대 못 잡는다.

안전: 어떤 실패도 exit 0 — 감시자가 job 을 빨갛게 만들면 그 자체가 소음이 된다.
"""
import os
import json
import datetime
import urllib.error
import urllib.request

import check_alerts as ca                 # is_market_open 재사용(장중/장외 임계가 다르다)
import notify_discord

KST = datetime.timezone(datetime.timedelta(hours=9))
API = "https://api.github.com"

# 감시 대상 — (워크플로 파일, 표시명, 장중 임계(분), 장외 임계(분)).
# 임계는 '이보다 오래 아무 런도 없으면 멈춘 것으로 본다'. 장중 stock-alerts 는 Worker cron
# 이 매분 깨우므로 10분이면 충분히 느슨하고, 장외엔 아예 안 도는 게 정상이라 감시하지 않는다.
# 임계는 '거짓 경보를 절대 내지 않는 선'으로 넉넉히 잡는다 — 늑대를 부르는 감시자는
# 곧 무시당한다. 여기서 잡으려는 것은 '몇 분 늦었다'가 아니라 '며칠째 멈췄다'이다.
WATCH = [
    ("stock-alerts.yml", "장중 알림 평가", 15, None),   # 장외엔 안 도는 게 정상
    ("fetch-data.yml", "시장 데이터 수집", 30, 120),
    ("kakao-daily.yml", "다이제스트 게이트", 30, 120),
]
# 최근 런 몇 개를 실패율 판정에 쓰나 — 한두 건 실패는 일시적 네트워크라 울리지 않는다.
RECENT_N = 10
FAIL_RATIO = 0.5


def _api(path):
    req = urllib.request.Request(
        API + path,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "ecom-watchdog",
                 "Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _repo():
    return os.environ.get("GITHUB_REPOSITORY") or "0101-commits/economic-site"


def _age_min(iso, now):
    """ISO 시각 → 지금까지 몇 분. 시계 어긋남은 0 으로 눌러 '음수 나이'를 만들지 않는다."""
    try:
        t = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (now - t).total_seconds() / 60.0)


def _threshold(wf, now):
    """그 워크플로가 지금 '돌고 있어야 하는가' → 임계(분) 또는 None(감시 안 함)."""
    _f, _name, live, idle = wf
    return live if (ca.is_market_open("KR", now) or ca.is_market_open("US", now)) else idle


def check_silence(now=None):
    """멈춘 워크플로 목록 → [(표시명, 사유)]. 조회 실패는 사유로 남긴다(조용히 넘기지 않는다)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    out = []
    for wf in WATCH:
        fname, name, _live, _idle = wf
        thr = _threshold(wf, now.astimezone(KST))
        if thr is None:
            continue                                  # 지금은 안 도는 게 정상인 시간대
        try:
            runs = (_api(f"/repos/{_repo()}/actions/workflows/{fname}/runs"
                         f"?per_page={RECENT_N}") or {}).get("workflow_runs") or []
        except (urllib.error.URLError, OSError, ValueError) as e:
            out.append((name, f"런 조회 실패 — {type(e).__name__}"))
            continue
        if not runs:
            out.append((name, "런 기록이 없다"))
            continue
        age = _age_min(runs[0].get("created_at"), now)
        if age is not None and age > thr:
            out.append((name, f"마지막 런이 {age:.0f}분 전 (임계 {thr}분) — 트리거가 끊겼다"))
            continue
        done = [r for r in runs if r.get("status") == "completed"]
        bad = [r for r in done if r.get("conclusion") not in ("success", "skipped")]
        if done and len(bad) / len(done) >= FAIL_RATIO:
            out.append((name, f"최근 {len(done)}건 중 {len(bad)}건 실패 — 연속 실패"))
    return out


def _failed_steps(run_id):
    """실패한 job 의 실패 스텝 이름 → 'job › step' 목록. 조회 실패면 빈 목록."""
    try:
        jobs = (_api(f"/repos/{_repo()}/actions/runs/{run_id}/jobs") or {}).get("jobs") or []
    except (urllib.error.URLError, OSError, ValueError):
        return []
    out = []
    for j in jobs:
        if j.get("conclusion") == "success":
            continue
        for s in (j.get("steps") or []):
            if s.get("conclusion") == "failure":
                out.append(f"{j.get('name')} › {s.get('name')}")
    return out


def main():
    mode = (os.environ.get("WATCHDOG_MODE") or "silence").strip()
    if mode == "failure":
        name = os.environ.get("WF_NAME") or "(이름 없음)"
        url = os.environ.get("WF_URL") or ""
        rid = os.environ.get("WF_RUN_ID") or ""
        steps = _failed_steps(rid) if rid else []
        body = f"**{name}** 런이 실패했습니다."
        if steps:
            body += "\n" + "\n".join(f"· {s}" for s in steps[:6])
        if url:
            body += f"\n{url}"
        print(f"[watchdog] 실패 통지: {name} — 스텝 {len(steps)}개")
        notify_discord.system(body, title="🚨 워크플로 실패",
                              color=notify_discord.COLOR_FIRE)
        return

    stalled = check_silence()
    if not stalled:
        # 조용히 return 하면 '감시가 돌았다'는 증거가 남지 않는다.
        print(f"[watchdog] 워크플로 {len(WATCH)}종 점검 — 이상 0건")
        return
    body = "\n".join(f"· **{n}** — {why}" for n, why in stalled)
    print(f"[watchdog] 침묵 감지 {len(stalled)}건: {[n for n, _ in stalled]}")
    notify_discord.system(
        body + "\n\n트리거(Cloudflare Worker cron / GHA schedule)를 확인하세요.",
        title="🔇 알림 파이프라인 침묵", color=notify_discord.COLOR_FIRE, mention=True)


def demo():
    now = datetime.datetime(2026, 9, 22, 3, 0, tzinfo=datetime.timezone.utc)  # 12시 KST = 장중
    assert _threshold(WATCH[0], now.astimezone(KST)) == 15
    night = datetime.datetime(2026, 9, 22, 10, 0, tzinfo=datetime.timezone.utc)  # 19시 KST
    assert _threshold(WATCH[0], night.astimezone(KST)) is None, "장외 stock-alerts 는 감시 제외"
    assert _threshold(WATCH[1], night.astimezone(KST)) == 120
    # 시계 어긋남으로 미래 시각이 와도 '음수 나이'가 되면 안 된다(임계 비교가 뒤집힌다).
    fut = (now + datetime.timedelta(minutes=5)).isoformat()
    assert _age_min(fut, now) == 0.0
    assert _age_min("쓰레기", now) is None
    print("watchdog.py 자가 점검 통과")


if __name__ == "__main__":
    if os.environ.get("WATCHDOG_SELFTEST") == "1":
        demo()
    else:
        try:
            main()
        except Exception as e:                        # noqa: BLE001
            print(f"[watchdog] 예외 무시({type(e).__name__}: {e}) — 감시자는 job 을 깨지 않는다")
