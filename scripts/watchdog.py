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
  silence  30분마다 '최근 런이 있는가'를 본다(Worker cron → repository_dispatch, GHA schedule 은
           Worker 가 죽었을 때의 백업). dispatch 가 끊기면 실패 런이 생기지 않으므로 failure
           모드로는 절대 못 잡는다. 같은 조건은 처음 볼 때 + REMIND_MIN 경계마다만 알린다
           (판정 기준은 '직전 silence 감시' — 감시 간격이 30분이든 백업의 몇 시간이든 성립).

안전: failure 모드는 어떤 실패도 exit 0 — 감시자가 job 을 빨갛게 만들면 그 자체가 소음이 된다.
  silence 모드만 통지 실패·예외를 exit 1 로 끝낸다 — 성공으로 끝나면 다음 감시가 그 런을
  '직전 감시'로 세어 못 알린 조건을 이미 알린 것으로 친다(_prev_check 는 성공 런만 본다).
"""
import os
import re
import json
import base64
import datetime
import urllib.error
import urllib.request

import app_url                            # 사이트 주소 단일 원천
import check_alerts as ca                 # is_market_open 재사용(장중/장외 임계가 다르다)
import notify_discord

KST = datetime.timezone(datetime.timedelta(hours=9))
API = "https://api.github.com"

# 감시 대상 — (워크플로 키, 표시명, 장중 임계(분), 장외 임계(분), 즉시 통지?).
# 키는 워크플로 파일명, 또는 저장소에 파일이 없는 GitHub 관리 워크플로의 숫자 id.
# 임계는 '이보다 오래 아무 런도 없으면 멈춘 것으로 본다'.
#
# 임계는 '거짓 경보를 절대 내지 않는 선'으로 넉넉히 잡는다 — 늑대를 부르는 감시자는
# 곧 무시당한다. 여기서 잡으려는 것은 '몇 분 늦었다'가 아니라 '며칠째 멈췄다'이다.
#
# 즉시 통지(instant)가 False 면 workflow_run 트리거 목록에 넣지 않는다 —
# 산발 실패가 정상인 워크플로는 '연속 실패'로만 본다.
WATCH = [
    ("stock-alerts.yml", "장중 알림 평가", 15, None, True),    # 장외엔 안 도는 게 정상
    ("fetch-data.yml", "시장 데이터 수집", 30, 120, True),
    ("kakao-daily.yml", "다이제스트 게이트", 30, 120, True),
    # 알림 v2 의 시각 정해진 런(브리핑 · settle 18:05 · eve 21:00) — 실패 즉시 통지만(침묵 임계 없음: 하루 몇 번뿐이라
    # 「런이 없다」는 정상이다). 감시 밖이던 동안 원장 커밋 실패 · 발송 예외가 아무 통지 없이 묻혔다(2026-10-11 점검 G10).
    ("briefing.yml", "브리핑", None, None, True),
    ("alerts-v2.yml", "알림 v2 확정 · 예고", None, None, True),
    # 사이트 배포(pages.yml — 2026-09-29 legacy pages-build-deployment(id 268675167)에서 전환).
    # 2026-11-07 부터 데이터 커밋으로는 배포하지 않는다(숫자 파일은 사이트 앞단이 저장소에서 바로 내준다) —
    # 코드 변경 + 6시간마다만 돈다. 그래서 '아예 안 돈다'는 하루(1440분) 넘게 없을 때만 보고, 화면 숫자가
    # 멈췄는지는 아래 check_site_lag 가 사이트를 직접 열어 본다. 산발 실패는 즉시 통지에서 빼고 '연속 실패'만.
    ("pages.yml", "사이트 배포", 1440, 1440, False),
]
# 실패로 세지 않는 결론 — cancelled 는 concurrency 그룹이 앞 런을 밀어낸 정상 동작이고
# (pages 배포·fetch-data 에서 상시 발생), skipped 는 게이트가 통과시키지 않은 것이다.
OK_CONCLUSIONS = ("success", "skipped", "cancelled")
RECENT_N = 50             # pages 배포는 취소 런이 대부분이라 쪽이 넉넉해야 실패 연속을 끝까지 본다
STREAK_MIN = 3            # 최신 런부터 이만큼 연속 실패여야 '연속 실패'(복구된 뒤엔 울리지 않는다)
# 이어지는 조건의 재통지 간격. 종전 판정('최근 10건 중 절반 실패')은 조건이 남은 동안 매 회차
# @멘션이었고, 복구 뒤에도 실패가 절반 남아 한 번 더 울렸다(2026-09-28 검토).
REMIND_MIN = 180


def _api(path):
    req = urllib.request.Request(
        API + path,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "ecom-watchdog",
                 "Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _api_post(path):
    """본문 없는 POST(런 취소). 2xx 가 아니면 HTTPError."""
    req = urllib.request.Request(
        API + path, method="POST", data=b"",
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "ecom-watchdog",
                 "Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def _repo():
    return os.environ.get("GITHUB_REPOSITORY") or "0101-commits/economic-site"


# 사이트 배포(pages.yml)가 'waiting'(github-pages 환경 배포 대기)에 갇히면 concurrency 그룹을 잡아 뒤 런이
# 전부 cancelled 가 되고 화면은 옛 값에 멈춘다 — cancelled 는 정상으로 세므로 침묵 감시가 못 본다
# (2026-10-06 14시간 · 2026-10-07 7.5시간 실측, 둘 다 사람이 `gh run cancel` 로 풀었다). 잡의
# timeout-minutes 는 시작 전 대기엔 안 걸린다. 이 분을 넘긴 대기 런은 취소해 그룹을 비운다 — 다음
# 데이터 커밋이 새 배포를 만든다. 정상 대기는 1~2분이라 20분이면 거짓 취소가 없다.
PAGES_STUCK_MIN = 20


def check_pages_stuck(now=None):
    """pages.yml 의 대기(waiting · queued) 런이 PAGES_STUCK_MIN 분을 넘겼으면 취소 → [(런 id, 상태, 나이 분)]."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    out = []
    for st in ("waiting", "queued"):
        try:
            runs = (_api(f"/repos/{_repo()}/actions/workflows/pages.yml/runs"
                         f"?status={st}&per_page=5") or {}).get("workflow_runs") or []
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"[watchdog] 사이트 배포 {st} 런 조회 실패 — {type(e).__name__}")
            continue
        for r in runs:
            age = _age_min(r.get("created_at"), now)
            if age is None or age < PAGES_STUCK_MIN:
                continue
            try:
                _api_post(f"/repos/{_repo()}/actions/runs/{r['id']}/cancel")
                out.append((r["id"], st, age))
            except (urllib.error.URLError, OSError) as e:        # 좀비 런(이미 끝났는데 queued 로 보임)은 409
                print(f"[watchdog] 사이트 배포 런 {r.get('id')} 취소 실패 — {type(e).__name__}")
    return out


def _age_min(iso, now):
    """ISO 시각 → 지금까지 몇 분. 시계 어긋남은 0 으로 눌러 '음수 나이'를 만들지 않는다."""
    try:
        t = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (now - t).total_seconds() / 60.0)


def _due(over, prev_over):
    """조건이 지금 over 분째, 직전 silence 감시 때는 prev_over 분째 — 지금 알릴 차례인가.

    prev_over 가 None 이거나 음수면 직전 감시 때는 조건이 아니었다(또는 모른다) → 첫 통지.
    이어지는 조건은 REMIND_MIN 경계를 넘을 때만 다시 알린다. 고정 창(over % 180 < 31)은 감시가
    정확히 30분마다 한 번 돌 때만 맞았다 — 백업 schedule(3~5시간 간격)이면 첫 통지를 거의 놓치고,
    두 감시가 한 창에 들면 두 번 울렸다. 모르면 알린다(침묵보다 중복).
    """
    if over is None:
        return False
    if prev_over is None or prev_over < 0:
        return True
    return over // REMIND_MIN > prev_over // REMIND_MIN


def _prev_check():
    """직전 silence 감시가 실제로 시작된 시각(UTC) — 없거나 조회 실패면 None.

    이벤트로 서버에서 거른다. failure 모드 런(workflow_run)도 success 로 끝나므로, 종목 알림이
    매분 실패하는 동안 한 쪽(20건)을 전부 채워 silence 런이 밀려나면 매 회차 '처음 본 조건'이
    됐다(2026-09-28 리뷰). silence 런은 통지에 실패하면 실패로 끝나(main) 여기서 빠진다.
    시각은 created_at 이 아니라 run_started_at — 러너 대기 동안 시작된 조건을 두 번 알리지 않게.
    """
    me = str(os.environ.get("GITHUB_RUN_ID") or "")
    best = None
    for ev in ("repository_dispatch", "schedule", "workflow_dispatch"):
        try:
            runs = (_api(f"/repos/{_repo()}/actions/workflows/watchdog.yml/runs"
                         f"?status=success&event={ev}&per_page=2") or {}).get("workflow_runs") or []
        except (urllib.error.URLError, OSError, ValueError):
            continue
        for r in runs:
            if str(r.get("id")) == me:
                continue
            try:
                t = datetime.datetime.fromisoformat(
                    str(r.get("run_started_at") or r.get("created_at")).replace("Z", "+00:00"))
            except ValueError:
                break
            best = t if best is None or t > best else best
            break
    return best


def _last_success_age(key, now):
    """마지막 성공 런이 끝난 지 몇 분 — 조회 실패·기록 없음은 None."""
    try:
        runs = (_api(f"/repos/{_repo()}/actions/workflows/{key}/runs"
                     f"?status=success&per_page=1") or {}).get("workflow_runs") or []
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return _age_min(runs[0].get("updated_at"), now) if runs else None


def _kakao_active(now):
    """다이제스트 게이트(kakao-daily)가 지금 돌고 있어야 하는가(KST).

    Worker 가 발송 슬롯 시각(평일 07~22시, 주말 11·17시)에만 5분마다 깨운다. 그 밖은 런이
    없는 게 정상인데 장외 임계(120분)로 재서, 새벽 03~06시에 '침묵 감지'를 3번 보냈다
    (2026-09-22·23 실측 — 전부 오탐). 첫 런 여유 30분, 마지막 슬롯 뒤 한 시간까지 본다.
    """
    hm = now.hour * 60 + now.minute
    if now.weekday() >= 5:
        return any(h * 60 + 30 <= hm < (h + 2) * 60 for h in (11, 17))
    # Worker 는 22:59 까지만 깨운다(worker.js inKakaoSlot). 23시 이후엔 US 장중 임계 30분이 걸려
    # 23:33 감시가 매일 '끊김'을 냈다(2026-09-28 리뷰에서 재현).
    return 7 * 60 + 30 <= hm < 23 * 60


def _kr_holidays():
    """한국 휴장일(KST 날짜) — 단일 원천은 worker.js KR_HOLIDAYS(이 날 Worker 가 KR 장중 창을 안 깨운다).
    2026-10-09 한글날 09:03 에 Worker 는 정상으로 쉬었는데 감시자는 평일 장중으로 보고 '장중 알림 평가 침묵'을 냈다.
    파일을 못 읽으면 빈 집합 — 종전 동작(평일 = 장중)으로 돌아간다."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cloudflare-worker", "worker.js"),
                  encoding="utf-8") as f:
            m = re.search(r"KR_HOLIDAYS\s*=\s*new Set\(\[(.*?)\]\)", f.read(), re.S)
        return set(re.findall(r"\d{4}-\d{2}-\d{2}", m.group(1))) if m else set()
    except OSError:
        return set()


def _threshold(wf, now):
    """그 워크플로가 지금 '돌고 있어야 하는가' → 임계(분) 또는 None(감시 안 함)."""
    key, _name, live, idle, _inst = wf
    if key == "kakao-daily.yml" and not _kakao_active(now):
        return None
    kr = ca.is_market_open("KR", now) and now.date().isoformat() not in _kr_holidays()
    return live if (kr or ca.is_market_open("US", now)) else idle


def check_silence(now=None):
    """멈춘 워크플로 목록 → [(표시명, 사유)]. 조회 실패는 사유로 남긴다(조용히 넘기지 않는다)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    prev = _prev_check()
    gap = (now - prev).total_seconds() / 60.0 if prev else None
    out = []
    for wf in WATCH:
        key, name, _live, _idle, _inst = wf
        thr = _threshold(wf, now.astimezone(KST))
        if thr is None:
            continue                                  # 지금은 안 도는 게 정상인 시간대
        # 직전 감시 때의 '그 시점 임계' — 장 시작(09:00·22:30)에 120→30 으로 조여지면 지금 임계로
        # 되짚은 값은 '그때도 끊김'이 돼 첫 통지를 삼켰다(2026-09-28 리뷰에서 재현).
        thr_prev = _threshold(wf, prev.astimezone(KST)) if prev else None
        watched = gap is not None and thr_prev is not None
        try:
            runs = (_api(f"/repos/{_repo()}/actions/workflows/{key}/runs"
                         f"?per_page={RECENT_N}") or {}).get("workflow_runs") or []
        except (urllib.error.URLError, OSError, ValueError) as e:
            out.append((name, f"런 조회 실패 — {type(e).__name__}"))
            continue
        if not runs:
            out.append((name, "런 기록이 없다"))
            continue
        age = _age_min(runs[0].get("created_at"), now)
        if age is not None and age > thr:
            if _due(age - thr, (age - gap - thr_prev) if watched else None):
                out.append((name, f"마지막 런이 {age:.0f}분 전 (임계 {thr}분) — 트리거가 끊겼다"))
            continue
        done = [r for r in runs if r.get("status") == "completed"
                and r.get("conclusion") not in ("cancelled", "skipped")]
        streak = next((i for i, r in enumerate(done)
                       if r.get("conclusion") in OK_CONCLUSIONS), len(done))
        if streak < STREAK_MIN:
            continue
        # 조건 시작 = 연속 실패가 STREAK_MIN 에 닿은 런이 끝난 때. 쪽 전체가 실패면 그 런이 쪽 밖이라
        # 마지막 성공 시각(없으면 쪽의 가장 오래된 실패)으로 갈음한다 — 리마인드 주기만 조금 밀린다.
        since = (_age_min(done[streak - STREAK_MIN].get("updated_at"), now) if streak < len(done)
                 else _last_success_age(key, now) or _age_min(done[-1].get("created_at"), now))
        if _due(since, (since - gap) if (watched and since is not None) else None):
            why = f"최근 {streak}건 연속 실패 — 이어지면 {REMIND_MIN // 60}시간마다 다시 알림"
            cause = _failure_cause(done[0].get("id"))
            if cause:
                gh, note = cause
                why += ("\n  └ GitHub 쪽 장애로 보임(코드 문제 아님 · 보통 저절로 풀림 · githubstatus.com): "
                        if gh else "\n  └ 오류: ") + note
            out.append((name, why))
    return out


# 회복 통지(2026-11-10). 알림은 「실패했다」만 있고 「풀렸다」는 글이 없어 #시스템의 마지막 글이 늘 옛 오류였다 —
# 그걸 보고 「계속 실패 중」으로 읽혀 같은 조사가 네 번 반복됐다(11-06 · 07 · 09 · 10, 실제 마지막 오류 알림은 11-07 03:14,
# 그 뒤 사흘 0건). 알림이 나간 실패가 풀리면 다음 silence 감시가 무음 한 줄을 남긴다(사용자 결정 「회복 한 줄 추가」).
# 알림이 나갔는지는 기록이 없으니 알림 규칙을 그대로 되짚는다 —
#   실패: 즉시 통지 워크플로는 연속의 첫 실패가 러너 미획득(_infra_failure)이 아니면, 아니면 STREAK_MIN 연속.
#   끊김: 직전 감시 때 임계를 넘어 있었고(그때 알렸다) 그 뒤 새 런이 생겼으면.
# 창 = (직전 감시 시작, 이 감시 시작] — 이 런이 시작된 뒤 끝난 회복은 다음 감시가 센다(두 번 쓰지 않게).
RECOVER_WINDOW_MIN = 35   # 직전 감시를 모를 때만 쓰는 창(감시 주기 30분 + 여유) — 모르면 최근 것만, 중복보다 생략


def _ts(iso):
    try:
        return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None


def _kst(t):
    t = t.astimezone(KST)
    return f"{t.month}/{t.day} {t:%H:%M}"


def _self_started(now):
    """이 감시 런이 시작된 시각 — 다음 감시의 '직전 감시'와 같은 값이어야 창이 겹치지 않는다. 모르면 now."""
    rid = os.environ.get("GITHUB_RUN_ID")
    if not rid:
        return now
    try:
        r = _api(f"/repos/{_repo()}/actions/runs/{rid}") or {}
        return _ts(r.get("run_started_at") or r.get("created_at")) or now
    except (urllib.error.URLError, OSError, ValueError):
        return now


def check_recovered(now=None):
    """직전 silence 감시 뒤에 풀린 실패 · 끊김 → [(표시명, 설명)]. 회복 통지는 덤이라 조회 실패는 조용히 넘긴다."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    prev = _prev_check()
    lo = prev or (now - datetime.timedelta(minutes=RECOVER_WINDOW_MIN))
    hi = _self_started(now)
    out = []
    for wf in WATCH:
        key, name, _live, _idle, inst = wf
        try:
            runs = (_api(f"/repos/{_repo()}/actions/workflows/{key}/runs"
                         f"?per_page={RECENT_N}") or {}).get("workflow_runs") or []
        except (urllib.error.URLError, OSError, ValueError):
            continue
        done = [r for r in runs if r.get("status") == "completed"
                and r.get("conclusion") not in ("cancelled", "skipped")]
        first_bad = next((i for i, r in enumerate(done) if r.get("conclusion") not in OK_CONCLUSIONS), None)
        if first_bad:                                  # 0 = 아직 실패 중, None = 쪽 안에 실패 없음
            end = next((j for j in range(first_bad, len(done))
                        if done[j].get("conclusion") in OK_CONCLUSIONS), len(done))
            fails = done[first_bad:end]
            back = _ts(done[first_bad - 1].get("updated_at"))          # 실패 뒤 첫 성공이 끝난 때
            t0 = _ts(fails[-1].get("created_at"))
            if back and t0 and lo < back <= hi and (
                    len(fails) >= STREAK_MIN or (inst and not _infra_failure(fails[-1].get("id")))):
                out.append((name, f"{_kst(t0)}부터 실패 {len(fails)}건 → {_kst(back)} 다시 정상"))
                continue
        if prev is None:
            continue
        thr_prev = _threshold(wf, prev.astimezone(KST))
        if thr_prev is None:
            continue
        before = next((r for r in runs if (_ts(r.get("created_at")) or hi) <= prev), None)
        fresh = [t for t in (_ts(r.get("created_at")) for r in runs) if t and prev < t <= hi]
        gap = _age_min(before.get("created_at"), prev) if before else None
        if fresh and gap is not None and gap > thr_prev:
            out.append((name, f"런이 다시 돈다 — {_kst(min(fresh))} 새 런(직전 감시 때 {gap:.0f}분째 없었다)"))
    return out


# 사이트 화면 숫자가 저장소보다 늦은가(2026-11-07). 숫자 파일은 배포 없이 사이트 앞단(cloudflare-pages/_worker.js)이
# 저장소에서 바로 내준다. 앞단이 깨지거나 대비책(6시간마다 배포되는 원본)으로 떨어지면 데이터 커밋은 계속 초록인데
# 화면 숫자만 멈춘다 — 실패 런이 생기지 않는 종류라 런 감시로는 못 잡는다. 사이트를 직접 열어 data_meta 의
# lastUpdated 를 저장소 main 의 것과 견준다. 앞단이 어느 길로 내줬는지는 머리 x-ecom-src(repo@번호 · repo-main · pages).
SITE_LAG_MIN = 30
SITE_NAME = "사이트 화면 숫자"


def _site_meta():
    """사이트가 지금 내주는 (data_meta.lastUpdated, x-ecom-src)."""
    req = urllib.request.Request(app_url.APP_URL + "data_meta.json",
                                 headers={"User-Agent": "ecom-watchdog", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r).get("lastUpdated"), r.headers.get("x-ecom-src") or "?"


def _repo_meta():
    """저장소 main 의 data_meta.lastUpdated."""
    j = _api(f"/repos/{_repo()}/contents/data_meta.json?ref=main") or {}
    return json.loads(base64.b64decode(j.get("content") or "")).get("lastUpdated")


def check_site_lag(now=None):
    """사이트 숫자가 저장소보다 SITE_LAG_MIN 분 넘게 늦으면 [(표시명, 사유)] — 처음 + 3시간 경계마다."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        repo_ts = _repo_meta()
        site_ts, src = _site_meta()
        lag = (datetime.datetime.fromisoformat(repo_ts) - datetime.datetime.fromisoformat(site_ts)).total_seconds() / 60.0
    except (urllib.error.URLError, OSError, ValueError, TypeError) as e:
        return [(SITE_NAME, f"사이트 · 저장소 조회 실패 — {type(e).__name__}")]
    over = lag - SITE_LAG_MIN
    if over <= 0:
        return []
    prev = _prev_check()
    gap = (now - prev).total_seconds() / 60.0 if prev else None
    if not _due(over, (over - gap) if gap is not None else None):
        return []
    return [(SITE_NAME, f"저장소보다 {lag:.0f}분 늦다(내준 길: {src}) — 앞단 cloudflare-pages/_worker.js · "
                        "githubstatus.com 확인. 「pages」면 저장소 길이 막혀 대비책 원본을 비추는 중")]


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


def _infra_failure(run_id):
    """GitHub 쪽 장애로 러너를 못 잡은 실패인가 — 잡에 실패 스텝이 하나도 없고 주석이 그렇게 말할 때.
    2026-10-05 19:11~21:05 UTC Actions 장애에서 25런이 전부 이 모양이었다(코드 결함 0). 저장소 문제로 알리면 늑대가 된다."""
    try:
        jobs = (_api(f"/repos/{_repo()}/actions/runs/{run_id}/jobs") or {}).get("jobs") or []
        for j in jobs:
            if any(s.get("conclusion") == "failure" for s in (j.get("steps") or [])):
                return False
        for j in jobs:
            notes = _api(f"/repos/{_repo()}/check-runs/{j.get('id')}/annotations") or []
            if any("not acquired by Runner" in str(n.get("message", "")) for n in notes):
                return True
    except (urllib.error.URLError, OSError, ValueError):
        pass
    return False


# GitHub 쪽 장애가 남기는 오류 주석 — 우리 스텝이 죽으면 이런 말 대신 「exit code 1」 류가 남는다.
# 2026-11-04 18:32~19:05 UTC 사이트 배포가 GitHub 안에서 멈춰(updating_pages 10분 → 「in progress deployment」
# 9건 연속) 침묵 감시가 「사이트 배포 연속 실패」를 냈는데, 알림만 봐서는 코드 탓인지 알 수 없었다.
GITHUB_SIDE = re.compile(
    r"status: 5\d\d"                              # Pages 배포 만들기 500 · 504
    r"|in progress deployment"                    # 앞 배포가 GitHub 쪽에서 안 끝남
    r"|Timeout reached, aborting"                 # deploy-pages 가 배포 상태 대기에서 멈춤
    r"|Deployment failed, try again later"        # 배포가 deployment_queued 에서 안 풀려 GitHub 가 거절(2026-11-06 7건)
    r"|Fetching artifact metadata failed|Failed to FinalizeArtifact"
    r"|couldn't respond to your request in time|githubstatus\.com"
    r"|not acquired by Runner"
    # OIDC 토큰 요청 시간 초과(2026-11-06 07:36 UTC) — 권한은 pages.yml 에 있고 test_watchdog 이 지킨다.
    r'|Ensure GITHUB_TOKEN has permission "id-token: write"')
CAUSE_MAX = 110           # 알림 한 줄에 붙이는 오류 주석 길이


def _failure_cause(run_id):
    """실패 런의 오류 주석 → (GitHub 쪽 장애인가, 한 줄 요약). 주석이 없거나 조회 실패면 None(덧붙이지 않는다)."""
    if not run_id:
        return None
    msgs = []
    try:
        jobs = (_api(f"/repos/{_repo()}/actions/runs/{run_id}/jobs") or {}).get("jobs") or []
        for j in jobs:
            if j.get("conclusion") == "success":
                continue
            notes = _api(f"/repos/{_repo()}/check-runs/{j.get('id')}/annotations") or []
            if isinstance(notes, list):
                msgs += [str(n.get("message") or "") for n in notes if n.get("annotation_level") == "failure"]
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        return None
    msgs = [re.sub(r"\s+", " ", re.sub(r"\s*Request ID [\w:]+\.?", "", m)).strip() for m in msgs]
    msgs = [m for m in msgs if m]
    if not msgs:
        return None
    # 원인 낱말이 앞에 있는 주석을 고른다 — 「status: 400 … Responded with: … in progress deployment」보다
    # 「HttpError: … due to in progress deployment」가 한 줄 안에 원인을 보여 준다.
    hits = []
    for m in msgs:
        hit = GITHUB_SIDE.search(m)
        if hit:
            hits.append((hit.start(), m))
    gh = [m for _, m in sorted(hits)]
    note = re.sub(r"\b([0-9a-f]{7})[0-9a-f]{33}\b", r"\1", (gh or msgs)[0])   # 커밋 해시는 7자로
    if len(note) > CAUSE_MAX:
        note = note[:CAUSE_MAX - 1] + "…"
    return bool(gh), note


def _streak_continues(wf_id, run_id):
    """이 런 직전의 완료 런도 실패였는가 — 연속 실패는 첫 건만 즉시 통지한다.

    fetch-data 는 장중 5분마다 돌아 30분 연속 실패면 11건이다(2026-09-28 09:00~09:30 실측).
    건마다 울리면 늑대가 된다. 이어지는 실패는 silence 모드의 '연속 실패' 판정이 본다.
    조회 실패는 False(통지) — 침묵보다 중복이 낫다.
    """
    if not wf_id:
        return False
    try:
        runs = (_api(f"/repos/{_repo()}/actions/workflows/{wf_id}/runs"
                     f"?status=completed&per_page={RECENT_N}") or {}).get("workflow_runs") or []
    except (urllib.error.URLError, OSError, ValueError):
        return False
    prev = [r for r in runs if str(r.get("id")) != str(run_id)
            and r.get("conclusion") not in ("cancelled", "skipped")]
    return bool(prev) and prev[0].get("conclusion") == "failure"


def main():
    mode = (os.environ.get("WATCHDOG_MODE") or "silence").strip()
    if mode == "failure":
        name = os.environ.get("WF_NAME") or "(이름 없음)"
        url = os.environ.get("WF_URL") or ""
        rid = os.environ.get("WF_RUN_ID") or ""
        if _streak_continues(os.environ.get("WF_ID"), rid):
            print(f"[watchdog] {name} 연속 실패 — 첫 건에 이미 통지, 이번은 생략")
            return
        if rid and _infra_failure(rid):
            print(f"[watchdog] {name} — GitHub 러너 미획득(인프라 장애), 저장소 문제 아님 — 통지 생략")
            return
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

    healed = check_pages_stuck()
    if healed:
        print(f"[watchdog] 사이트 배포 대기 런 취소 {len(healed)}건: {[rid for rid, _, _ in healed]}")
        notify_discord.system(
            "\n".join(f"· 런 {rid} — {st} {age:.0f}분" for rid, st, age in healed)
            + "\n\n대기 런이 concurrency 그룹을 잡아 뒤 배포가 전부 취소되던 것을 풀었다. 다음 배포(코드 변경 · 6시간 주기)가 새로 올린다.",
            title="🩹 사이트 배포 대기 런 취소(자가 치유)", color=notify_discord.COLOR_FIRE)
    stalled = check_silence() + check_site_lag()
    try:
        recovered = check_recovered()
    except Exception as e:                             # noqa: BLE001 — 회복 통지가 감시 런을 깨면 본말전도
        print(f"[watchdog] 회복 점검 건너뜀({type(e).__name__}: {e})")
        recovered = []
    # 회복과 남은 이상은 한 통으로 — 따로 보내면 회복을 쓴 뒤 침묵 통지가 실패했을 때 이 런이 실패로 끝나
    # 다음 감시가 같은 창을 다시 보고 회복을 두 번 쓴다(2026-11-10 검토). 회복만 있을 때 통지가 실패해도
    # 런을 실패로 끝낸다 — 다음 감시가 직전 감시를 그 앞 런으로 보고 같은 회복을 다시 쓴다(이 런엔 다른 통지가 없다).
    rec = "\n".join(f"· **{n}** — {why}" for n, why in recovered)
    if recovered:
        print(f"[watchdog] 회복 {len(recovered)}건: {[n for n, _ in recovered]}")
    if not stalled:
        # 조용히 return 하면 '감시가 돌았다'는 증거가 남지 않는다.
        print(f"[watchdog] 워크플로 {len(WATCH)}종 + 사이트 숫자 점검 — 이상 0건")
        if recovered and not notify_discord.system(rec, title="✅ 회복", color=notify_discord.COLOR_RESOLVE):
            raise SystemExit("[watchdog] 회복 통지 실패 — 이 런은 감시로 세지 않는다")
        return
    body = "\n".join(f"· **{n}** — {why}" for n, why in stalled)
    print(f"[watchdog] 침묵 감지 {len(stalled)}건: {[n for n, _ in stalled]}")
    ok = notify_discord.system(
        body + "\n\n트리거(Cloudflare Worker cron / GHA schedule)를 확인하세요."
        + (f"\n\n✅ 회복\n{rec}" if recovered else ""),
        title="🔇 알림 파이프라인 침묵", color=notify_discord.COLOR_FIRE)   # #시스템은 무음(2026-10-13)
    if not ok:
        # 통지를 못 했는데 success 로 끝나면 다음 감시가 이 런을 '직전 감시'로 보고 이미 알린
        # 것으로 친다 — 최대 3시간 무통지. 실패로 끝내 _prev_check 에서 빠지게 한다.
        raise SystemExit("[watchdog] 침묵 통지 실패 — 이 런은 감시로 세지 않는다")


def demo():
    now = datetime.datetime(2026, 9, 22, 3, 0, tzinfo=datetime.timezone.utc)  # 12시 KST = 장중
    assert _threshold(WATCH[0], now.astimezone(KST)) == 15
    night = datetime.datetime(2026, 9, 22, 10, 0, tzinfo=datetime.timezone.utc)  # 19시 KST
    assert _threshold(WATCH[0], night.astimezone(KST)) is None, "장외 stock-alerts 는 감시 제외"
    assert _threshold(WATCH[1], night.astimezone(KST)) == 120
    hangul = datetime.datetime(2026, 10, 9, 0, 3, tzinfo=datetime.timezone.utc)  # 금 09:03 KST 한글날
    assert "2026-10-09" in _kr_holidays(), "worker.js KR_HOLIDAYS 를 못 읽었다"
    assert _threshold(WATCH[0], hangul.astimezone(KST)) is None, "휴장일 KR 장중 창엔 stock-alerts 감시 제외"
    assert _threshold(WATCH[1], hangul.astimezone(KST)) == 120, "휴장일엔 장외 임계"
    assert [w[0] for w in WATCH if not w[4]] == ["pages.yml"], "즉시 통지 제외는 pages 뿐"
    kakao = next(w for w in WATCH if w[0] == "kakao-daily.yml")
    dawn = datetime.datetime(2026, 9, 22, 18, 30, tzinfo=datetime.timezone.utc)  # 수 03:30 KST
    assert _threshold(kakao, dawn.astimezone(KST)) is None, "새벽엔 다이제스트 게이트가 안 도는 게 정상"
    sat = datetime.datetime(2026, 9, 26, 5, 0, tzinfo=datetime.timezone.utc)     # 토 14:00 KST
    assert _threshold(kakao, sat.astimezone(KST)) is None, "주말 11·17시 슬롯 사이는 감시 제외"
    assert _threshold(kakao, now.astimezone(KST)) == 30, "평일 장중엔 감시"
    assert "cancelled" in OK_CONCLUSIONS, "concurrency 취소를 실패로 세면 상시 오경보다"
    assert _due(5, -25) and not _due(40, 10), "직전 감시 뒤 시작만 첫 통지"
    assert _due(185, 155) and not _due(215, 185), "이어지면 3시간 경계마다"
    assert _due(100, -140), "백업 schedule(4시간 간격)도 첫 통지를 놓치지 않는다"
    assert _due(400, None) and not _due(None, 30)
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
            print(f"[watchdog] 예외({type(e).__name__}: {e})")
            # failure 모드는 초록으로 끝낸다(감시자가 job 을 깨면 그 자체가 소음). silence 는 실패로 —
            # 성공으로 끝나면 다음 감시가 이 런을 '직전 감시'로 세어 조건을 이미 알린 것으로 친다.
            if (os.environ.get("WATCHDOG_MODE") or "silence").strip() != "failure":
                raise SystemExit(1)
