#!/usr/bin/env python3
"""2026-09-08 파이프라인 수정의 사후 관측 — 실측을 재서 디스코드로 보고한다.

무엇을 고쳤고 무엇을 봐야 하는가:
  · A1  스테일 자동 복구가 풀 런(44~62분) 대신 경량 런(1분 미만)을 깨우게 했다.
  · A2  스테일 임계를 시간대별로 나눴다(장중 120 / 평일 장외 240 / 주말·공휴일 720분).
  · A3  Worker 가 장외·주말에도 매시 :35(UTC) 경량 fetch-data 를 dispatch 한다.
  · B1  토스 스냅샷 작업을 wscript 래퍼로 바꿔 콘솔 창을 없앴다.

디스코드 #시스템 채널은 읽을 수 없으므로 경고 건수는 프록시로 센다: ⚙️ 경고와
_dispatch_fetch_data() 는 같은 분기에서 함께 발화하므로, fetch-data 의 workflow_dispatch
런 수 = 경고 수다. 사람이 손으로 돌린 dispatch 도 같은 이벤트라 섞이지만(actor 로는
구분되지 않는다 — PAT·GITHUB_TOKEN·사람이 전부 저장소 소유자로 찍힌다) 시각과 소요를
같이 보고하므로 눈으로 가려낼 수 있다. 수정이 먹었다면 이 값은 0 이어야 한다.

실행:
    python scripts/verify_pipeline_fix.py            # 최근 24시간, 콘솔 출력 + 디스코드
    python scripts/verify_pipeline_fix.py --hours 3  # 창 좁히기
    python scripts/verify_pipeline_fix.py --quiet    # 디스코드 발송 없이 콘솔만

필요: gh CLI 로그인(런 조회), git(커밋 간격). 없으면 그 항목만 '조회 실패'로 남기고
나머지를 보고한다 — 관측이 실패해도 시끄럽지 않게.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

KST = datetime.timezone(datetime.timedelta(hours=9))
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTIFY = r"C:\Users\cgpar\AI_CLI\scripts\discord-notify.js"

# _stale_limit_min 과 같은 값 — 어긋나면 보고가 거짓이 된다.
LIMIT_MARKET, LIMIT_OFF, LIMIT_WEEKEND = 120, 240, 720


def _run(args, **kw):
    """실패해도 예외를 던지지 않는다 — 관측 도구가 파이프라인을 깨우면 본말전도."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=REPO_DIR, timeout=90, **kw)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as e:                                  # noqa: BLE001
        return 1, "", f"{type(e).__name__}: {e}"


def _in_market_hours(dt_utc):
    """Worker 의 inMarketHours() 와 같은 규칙 — 평일 UTC 00–06 · 13–21."""
    if dt_utc.weekday() > 4:
        return False
    h = dt_utc.hour
    return h <= 6 or 13 <= h <= 21


def _stale_limit(now_kst):
    """send_kakao_digest._stale_limit_min 과 같은 규칙(공휴일은 여기서 판정 불가 → 주말만)."""
    if now_kst.weekday() >= 5:
        return LIMIT_WEEKEND
    h = now_kst.hour
    return LIMIT_MARKET if (h < 7 or 9 <= h < 16 or h >= 22) else LIMIT_OFF


def _slots_between(a, b):
    """공백 (a, b] 안에 들어오는 카카오 다이제스트 슬롯 시각들(KST).

    평일 07~22시 매시간, 주말 11·17시 — kakao-daily.yml 의 발송 창과 같다.
    스테일 판정은 공백의 시작도 끝도 아니라 '슬롯이 도는 순간'에 이뤄지므로,
    경고가 났을지는 이 시각들에서만 물어야 한다(공백 시작 시각으로 재면
    장 마감 직전에 시작해 저녁 내내 이어진 공백을 장중 기준으로 오판한다)."""
    out = []
    t = a.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
    while t <= b:
        h, dow = t.hour, t.weekday()
        if (dow >= 5 and h in (11, 17)) or (dow < 5 and 7 <= h <= 22):
            out.append(t)
        t += datetime.timedelta(hours=1)
    return out


def measure_gaps(hours):
    """data.json 커밋 간격 — 각 공백이 '어떤 슬롯에서' 경고를 냈을지까지 본다."""
    rc, out, err = _run(["git", "log", f"--since={hours + 12} hours ago",
                         "--format=%cI", "--", "data.json"])
    if rc != 0:
        return {"error": err or "git log 실패"}
    stamps = sorted(datetime.datetime.fromisoformat(x) for x in out.split() if x)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    gaps = []
    for a, b in zip(stamps, stamps[1:]):
        if b < cutoff:
            continue
        gaps.append(((b - a).total_seconds() / 60, a.astimezone(KST), b.astimezone(KST)))
    # 슬롯마다 '그 순간의 나이 vs 그 시각의 임계'를 물어 경고가 났을지 센다.
    new_hits, old_hits = [], []
    for mins, a, b in gaps:
        for slot in _slots_between(a, b):
            age = (slot - a).total_seconds() / 60
            if age > _stale_limit(slot):
                new_hits.append((slot, age))
            if age > LIMIT_MARKET:
                old_hits.append((slot, age))
    return {
        "commits": len([s for s in stamps if s >= cutoff]),
        "max": max((g[0] for g in gaps), default=0.0),
        "max_at": max(gaps, default=(0, None, None))[1],
        "hits": new_hits,            # 새 임계로 경고가 났을 슬롯 = 목표 0
        "hits_old": old_hits,        # 종전 단일 120분이었다면 났을 슬롯(대조군)
    }


def _gh_runs(workflow, hours):
    created = (datetime.datetime.now(datetime.timezone.utc)
               - datetime.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rc, out, err = _run(["gh", "run", "list", "--workflow", workflow, "--limit", "300",
                         "--created", f">{created}", "--json",
                         "event,status,conclusion,createdAt,updatedAt"])
    if rc != 0:
        return None, err.splitlines()[0] if err else "gh run list 실패"
    try:
        return json.loads(out or "[]"), None
    except json.JSONDecodeError as e:
        return None, f"JSON 파싱 실패: {e}"


def measure_runs(hours):
    runs, err = _gh_runs("fetch-data.yml", hours)
    if runs is None:
        return {"error": err}
    warns, offhours, longest = [], [], 0.0
    for r in runs:
        created = datetime.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))
        updated = datetime.datetime.fromisoformat(r["updatedAt"].replace("Z", "+00:00"))
        mins = (updated - created).total_seconds() / 60
        if r["event"] == "workflow_dispatch":
            warns.append((created.astimezone(KST), mins))       # = ⚙️ 경고 후보 1건
        if (r["event"] == "repository_dispatch" and not _in_market_hours(created)
                and 35 <= created.minute <= 40):
            offhours.append(created.astimezone(KST))
        if r.get("conclusion") == "success":
            longest = max(longest, mins)
    return {"total": len(runs), "warnings": warns, "offhours": offhours, "longest": longest}


def measure_task():
    """토스 작업 로그의 종료 코드 — 팝업을 없애면서 실행이 깨지지 않았는지."""
    log = os.path.join(os.environ.get("TEMP", ""), "toss_snapshot.log")
    if not os.path.exists(log):
        return {"error": "toss_snapshot.log 없음"}
    try:
        with open(log, encoding="utf-8", errors="replace") as f:
            tail = f.readlines()[-400:]
    except OSError as e:
        return {"error": f"로그 읽기 실패: {e}"}
    codes = [int(m.group(1)) for line in tail
             if (m := re.search(r"\]\s*exit\s+(-?\d+)", line))]
    return {"runs": len(codes), "fail": [c for c in codes if c != 0]}


def build_report(hours, gaps, runs, task):
    lines = []
    if "error" in gaps:
        lines.append(f"공백: 조회 실패({gaps['error'][:80]})")
    else:
        at = gaps["max_at"].strftime("%m-%d %H:%M") if gaps["max_at"] else "-"
        hits = gaps["hits"]
        lines.append(f"공백 최대 {gaps['max']:.0f}분({at} 시작) · 커밋 {gaps['commits']}건")
        lines.append(f"경고났을 슬롯 {len(hits)}개(종전 임계라면 {len(gaps['hits_old'])}개)"
                     + (" · " + ", ".join(f"{t:%m-%d %H시}({a:.0f}분)" for t, a in hits[:5]) if hits else ""))
    if "error" in runs:
        lines.append(f"런: 조회 실패({runs['error'][:80]})")
    else:
        w = runs["warnings"]
        lines.append(f"스테일 경고(=자동복구 dispatch, 수동 포함) {len(w)}건"
                     + (" · " + ", ".join(f"{t:%m-%d %H:%M}({m:.0f}분)" for t, m in w[:5]) if w else ""))
        lines.append(f"장외 :35 보강 {len(runs['offhours'])}건 · fetch-data 런 {runs['total']}건 "
                     f"· 최장 {runs['longest']:.0f}분")
    if "error" in task:
        lines.append(f"토스 작업: {task['error']}")
    else:
        lines.append(f"토스 작업 {task['runs']}회 · 실패 {len(task['fail'])}건"
                     + (f" {task['fail'][:5]}" if task["fail"] else ""))
    return f"최근 {hours}시간", "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=None,
                    help="관측 창(기본: 월요일 72시간=주말 포함, 그 외 30시간)")
    ap.add_argument("--quiet", action="store_true", help="디스코드 발송 없이 콘솔만")
    a = ap.parse_args()

    # 인자 없이도 맞는 창을 고른다 — 작업 스케줄러 트리거마다 인자를 다르게 주는 것보다
    # 스크립트가 요일을 보는 편이 단순하다. 30시간(24 아님)은 하루 경계에서 슬롯이
    # 통째로 빠지는 것을 막는 겹침이다.
    hours = a.hours if a.hours else (72 if datetime.datetime.now(KST).weekday() == 0 else 30)

    gaps = measure_gaps(hours)
    runs = measure_runs(hours)
    task = measure_task()
    title, body = build_report(hours, gaps, runs, task)

    print(f"[verify] {title}")
    for ln in body.split("\n"):
        print("  " + ln)

    if a.quiet or not os.path.exists(NOTIFY):
        return 0
    # 한글이 깨지는 셸을 피해 stdin JSON 으로 넘긴다(AI_CLI 규약).
    payload = json.dumps({"type": "progress", "title": f"파이프라인 관측 · {title}",
                          "desc": body, "cli": "claude"}, ensure_ascii=False)
    try:
        p = subprocess.run(["node", NOTIFY, "send"], input=payload, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60)
        if p.returncode != 0:
            print(f"[verify] 디스코드 발송 실패(rc={p.returncode}): {(p.stderr or '')[:200]}")
    except Exception as e:                                  # noqa: BLE001
        print(f"[verify] 디스코드 발송 실패: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
