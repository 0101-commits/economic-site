#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""상시 감시(watchdog) 배선 — 감시자가 조용히 죽으면 감시가 없는 것보다 나쁘다.

감시자를 믿고 로그를 안 보게 되기 때문이다. 그래서 '감시자가 실제로 그 워크플로를
가리키고 있는가'를 문자열 수준에서 붙잡아 둔다 — workflow_run 의 workflows: 는
이름이 한 글자만 달라도 트리거가 아예 안 걸리고, 어떤 오류도 나지 않는다.
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
WFDIR = os.path.join(ROOT, ".github", "workflows")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import watchdog as W  # noqa: E402

WATCHDOG_YML = open(os.path.join(WFDIR, "watchdog.yml"), encoding="utf-8").read()


def _wf_name(fname):
    for line in open(os.path.join(WFDIR, fname), encoding="utf-8"):
        m = re.match(r"^name:\s*(.+?)\s*$", line)
        if m:
            return m.group(1)
    raise AssertionError(f"{fname} 에 name: 이 없다")


def _trigger_names():
    block = WATCHDOG_YML.split("workflows:", 1)[1].split("types:", 1)[0]
    return [m.group(1) for m in re.finditer(r'^\s*-\s*"(.+)"\s*$', block, re.M)]


def test_trigger_names_match_actual_workflows():
    """workflow_run 의 이름이 실제 워크플로 name 과 한 글자도 달라선 안 된다.

    즉시 통지 대상(instant=True)만 트리거 목록에 있어야 한다 — 산발 실패가 정상인
    워크플로까지 넣으면 감시자가 늑대를 부르고, 그러면 아무도 안 읽는다.
    """
    actual = {_wf_name(k) for k, _n, _l, _i, inst in W.WATCH if inst}
    assert set(_trigger_names()) == actual, f"{sorted(_trigger_names())} != {sorted(actual)}"


def test_trigger_names_have_no_glob_chars():
    """workflows: 는 이름을 glob 패턴으로 본다 — 글자가 같아도 + / * ? [ ] ! 가 있으면 안 걸린다.

    실측: "…10min + Daily 9AM/4PM/10PM KST" 는 위 문자열 일치 테스트를 통과했지만
    2026-09-22~28 fetch-data 실패 즉시 통지가 0건이었다(kakao-daily 의 같은 트리거는 6월부터 0회).
    """
    for n in _trigger_names():
        assert not set(n) & set("+/*?[]!\\"), n


def test_pages_deploy_triggers_match_actual_workflows():
    """pages.yml 의 workflow_run 이름이 어긋나면 봇 코드 커밋(js 압축)이 배포로 안 이어지고 화면이 옛 판에 멈춘다.

    GITHUB_TOKEN 커밋은 on: push 를 깨우지 않아 이 트리거가 봇 코드 커밋의 유일한 배포 경로다.
    데이터 커밋은 일부러 뺐다(2026-11-07) — 숫자 파일은 사이트 앞단이 저장소에서 바로 내준다(cloudflare-pages/_worker.js).
    """
    yml = open(os.path.join(WFDIR, "pages.yml"), encoding="utf-8").read()
    block = yml.split("workflows:", 1)[1].split("types:", 1)[0]
    names = [m.group(1) for m in re.finditer(r'^\s*-\s*"(.+)"\s*$', block, re.M)]
    actual = {_wf_name(f) for f in os.listdir(WFDIR) if f.endswith(".yml")}
    assert "Build Frontend (minify js)" in names
    assert "Market Data Fetch" not in names, "데이터 커밋마다 배포하던 길(하루 ~400번)이 되살아났다"
    assert re.search(r"^  schedule:\n    - cron: '[^']+'", yml, re.M), "대비책 원본의 숫자를 갱신할 주기 배포가 없다"
    for n in names:
        assert n in actual, n
        assert not set(n) & set("+/*?[]!\\"), n


def test_failure_streak_notifies_first_only(monkeypatch):
    """연속 실패는 첫 건만 — 직전 완료 런(취소 제외)이 실패면 생략, 성공이면 통지."""
    runs = {"workflow_runs": [
        {"id": 3, "conclusion": "failure"},     # 지금 런
        {"id": 2, "conclusion": "cancelled"},   # concurrency 취소는 건너뛴다
        {"id": 1, "conclusion": "failure"},
    ]}
    monkeypatch.setattr(W, "_api", lambda _p: runs)
    assert W._streak_continues("123", "3") is True
    runs["workflow_runs"][2]["conclusion"] = "success"
    assert W._streak_continues("123", "3") is False
    assert W._streak_continues("", "3") is False            # id 없으면 통지(침묵보다 중복)

    def boom(_p):
        raise OSError("down")
    monkeypatch.setattr(W, "_api", boom)
    assert W._streak_continues("123", "3") is False


def test_worker_dispatch_matches_trigger():
    """Worker 가 30분마다 보내는 event_type 이 watchdog.yml 의 repository_dispatch types 와 같아야 한다.

    어긋나면 dispatch 는 204 로 성공하고 워크플로만 안 깨어난다 — 아무 오류도 없다.
    """
    worker = open(os.path.join(ROOT, "cloudflare-worker", "worker.js"), encoding="utf-8").read()
    m = re.search(r"ghDispatch\(env, '([\w-]+)', \{\}, 'ecom-watchdog-cron'\)", worker)
    assert m, "Worker 의 watchdog dispatch 가 없다"
    assert re.search(r"repository_dispatch:\s*\n\s*types:\s*\[\s*%s\s*\]" % re.escape(m.group(1)),
                     WATCHDOG_YML), m.group(1)


def _silence(monkeypatch, runs, prev_ago=30, success_ago=None, thr=lambda _wf, _t: 30):
    """WATCH 한 종으로 check_silence 를 돌린다. 지금 = 12:00 UTC(21:00 KST), 직전 감시 = prev_ago 분 전."""
    import datetime as dt
    now = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
    iso = lambda m: (now - dt.timedelta(minutes=m)).isoformat()
    runs = [dict(r) for r in runs]
    for r in runs:
        ago = r.pop("ago")
        r.setdefault("status", "completed")
        r["created_at"], r["updated_at"] = iso(ago), iso(r.pop("done", ago))
    monkeypatch.setattr(W, "WATCH", [("x.yml", "X", 30, 30, True)])
    monkeypatch.setattr(W, "_threshold", thr)
    monkeypatch.setattr(W, "_prev_check",
                        lambda: None if prev_ago is None else now - dt.timedelta(minutes=prev_ago))
    ok = {"workflow_runs": [{"updated_at": iso(success_ago)}]} if success_ago is not None else {}
    monkeypatch.setattr(W, "_api", lambda p: ok if "status=success" in p else {"workflow_runs": runs})
    return W.check_silence(now)


def test_silence_quiet_after_recovery(monkeypatch):
    """최신 런이 성공이면 앞에 실패가 여럿 남아 있어도 울리지 않는다(종전 '10건 중 절반' 판정은 울렸다)."""
    runs = [{"ago": 2, "conclusion": "success"}] + [{"ago": 5 * i, "conclusion": "failure"} for i in range(1, 8)]
    assert _silence(monkeypatch, runs) == []


FRESH_STREAK = [{"ago": 1, "done": 1, "conclusion": "failure"},     # 3번째 실패 = 1분 전에 끝남
                {"ago": 6, "done": 5, "conclusion": "failure"},
                {"ago": 11, "done": 10, "conclusion": "failure"},
                {"ago": 16, "done": 15, "conclusion": "success"}]


def test_silence_streak_notified_once(monkeypatch):
    """연속 실패는 직전 감시 뒤에 시작됐을 때만 — 바로 뒤 감시(:04 이중 발화·백업 겹침)는 다시 안 울린다."""
    assert len(_silence(monkeypatch, FRESH_STREAK, prev_ago=30)) == 1
    assert _silence(monkeypatch, FRESH_STREAK, prev_ago=0.5) == []


def test_silence_long_streak_reminds_every_3h(monkeypatch):
    """쪽 전체가 실패면 마지막 성공 시각이 기준 — 3시간 경계를 넘는 감시에서만 다시 알린다."""
    all_fail = [{"ago": 5 * i + 1, "done": 5 * i, "conclusion": "failure"} for i in range(W.RECENT_N)]
    assert _silence(monkeypatch, all_fail, success_ago=100) == []
    assert len(_silence(monkeypatch, all_fail, success_ago=185)) == 1


def test_silence_stall_first_then_reminder(monkeypatch):
    """끊김은 처음 볼 때 + 3시간 경계마다. 이어지는 동안 매 회차 @멘션하지 않는다."""
    assert len(_silence(monkeypatch, [{"ago": 45, "conclusion": "success"}])) == 1   # 15분째, 직전 감시 땐 없었다
    assert _silence(monkeypatch, [{"ago": 95, "conclusion": "success"}]) == []       # 65분째
    assert len(_silence(monkeypatch, [{"ago": 215, "conclusion": "success"}])) == 1  # 185분째


def test_silence_backup_schedule_still_first_alerts(monkeypatch):
    """Worker 가 죽어 백업 schedule 만 도는 경우(간격 4시간) — 창 방식은 첫 통지를 거의 놓쳤다."""
    assert len(_silence(monkeypatch, [{"ago": 130, "conclusion": "success"}], prev_ago=240)) == 1


def test_silence_first_check_of_watch_window(monkeypatch):
    """직전 감시 땐 감시 시간대 밖(임계 None)이었다면 오래된 끊김도 지금이 첫 통지다(장 시작 09:03 등)."""
    thr = lambda _wf, t: 30 if (t.hour, t.minute) >= (21, 0) else None   # 21:00 KST 부터 감시
    assert len(_silence(monkeypatch, [{"ago": 300, "conclusion": "success"}], thr=thr)) == 1


def test_silence_threshold_tightening_first_alerts(monkeypatch):
    """장 시작에 임계가 120→30 으로 조여지는 감시 — 직전 감시 땐 '그 시점 임계'로 정상이었으니 첫 통지다.

    지금 임계로 되짚으면 '그때도 끊김'이 되어 첫 통지를 삼켰다(fetch-data 07:00 정지 → 10:33 첫 통지).
    """
    thr = lambda _wf, t: 30 if (t.hour, t.minute) >= (21, 0) else 120
    assert len(_silence(monkeypatch, [{"ago": 60, "conclusion": "success"}], thr=thr)) == 1


def test_silence_run_fails_when_notify_fails(monkeypatch):
    """통지에 실패한 silence 런이 성공으로 끝나면 다음 감시가 '이미 알렸다'고 친다 — 실패로 끝내야 한다."""
    import pytest
    monkeypatch.setenv("WATCHDOG_MODE", "silence")
    monkeypatch.setattr(W, "check_silence", lambda: [("X", "끊김")])
    monkeypatch.setattr(W, "check_site_lag", lambda: [])
    monkeypatch.setattr(W, "check_recovered", lambda: [])
    monkeypatch.setattr(W.notify_discord, "system", lambda *a, **k: False)
    with pytest.raises(SystemExit):
        W.main()
    monkeypatch.setattr(W.notify_discord, "system", lambda *a, **k: True)
    W.main()                                                         # 통지 성공이면 정상 종료


def _site_lag(monkeypatch, lag_min, prev_ago=30, src="repo@abcdef0", fail=None):
    """저장소 data_meta = 12:00 KST, 사이트 = 그보다 lag_min 분 앞선 값. 직전 감시 = prev_ago 분 전."""
    import datetime as dt
    now = dt.datetime(2026, 11, 7, 3, 0, tzinfo=dt.timezone.utc)
    repo = dt.datetime(2026, 11, 7, 12, 0, tzinfo=W.KST)
    monkeypatch.setattr(W, "_repo_meta", lambda: repo.isoformat())

    def site():
        if fail:
            raise fail
        return (repo - dt.timedelta(minutes=lag_min)).isoformat(), src
    monkeypatch.setattr(W, "_site_meta", site)
    monkeypatch.setattr(W, "_prev_check", lambda: None if prev_ago is None else now - dt.timedelta(minutes=prev_ago))
    return W.check_site_lag(now)


def test_site_lag_quiet_when_fresh(monkeypatch):
    """사이트 숫자가 저장소와 같거나 조금 늦은 건 정상(배포 없이 바로 내주는 길)."""
    assert _site_lag(monkeypatch, 0) == []
    assert _site_lag(monkeypatch, W.SITE_LAG_MIN) == []


def test_site_lag_first_then_every_3h(monkeypatch):
    """임계를 넘은 첫 감시에 알리고, 이어지는 동안은 3시간 경계에서만 다시 알린다(다른 침묵 감시와 같은 규칙)."""
    first = _site_lag(monkeypatch, W.SITE_LAG_MIN + 10, src="pages (refs 500)")
    assert len(first) == 1 and first[0][0] == W.SITE_NAME and "pages (refs 500)" in first[0][1]
    assert _site_lag(monkeypatch, W.SITE_LAG_MIN + 100) == []                      # 이어지는 중
    assert len(_site_lag(monkeypatch, W.SITE_LAG_MIN + W.REMIND_MIN + 5)) == 1      # 3시간 경계


def test_site_lag_reports_fetch_failure(monkeypatch):
    """사이트를 못 열면 조용히 넘기지 않는다."""
    import urllib.error
    out = _site_lag(monkeypatch, 0, fail=urllib.error.URLError("down"))
    assert len(out) == 1 and "조회 실패" in out[0][1]


def test_site_lag_reads_site_from_app_url():
    """사이트 주소는 app_url 단일 원천에서(주소를 두 곳에 적으면 어긋난다)."""
    import inspect
    assert "app_url.APP_URL" in inspect.getsource(W._site_meta)


def test_watched_workflow_files_exist():
    """파일명으로 지정한 대상은 실제 파일이 있어야 한다(숫자 id 는 GitHub 관리 워크플로)."""
    for key, _n, _l, _i, _inst in W.WATCH:
        if key.isdigit():
            continue
        assert os.path.exists(os.path.join(WFDIR, key)), key


def test_watchdog_does_not_watch_itself():
    """자기 실패를 자기가 통지하면 실패가 실패를 낳는다."""
    assert "watchdog.yml" not in [k for k, _n, _l, _i, _inst in W.WATCH]
    assert _wf_name("watchdog.yml") not in _trigger_names()


def test_silence_thresholds_are_sane():
    """장중 임계가 장외보다 빡빡해야 한다(장외엔 안 도는 게 정상이거나 훨씬 드물다)."""
    for _k, name, live, idle, _inst in W.WATCH:
        if live is None and idle is None:              # 실패 즉시 통지만 하는 감시(시각 정해진 런 — 브리핑 · settle · eve)
            continue
        assert live and live > 0, name
        assert idle is None or idle >= live, name


def test_cancelled_is_not_a_failure():
    """concurrency 가 앞 런을 밀어낸 취소를 실패로 세면 상시 오경보가 된다.

    실측: pages 배포는 데이터 커밋마다 돌아 최근 10건 중 취소가 늘 섞여 있다.
    """
    assert "cancelled" in W.OK_CONCLUSIONS


def test_selftest_passes():
    W.demo()


def test_infra_failure_detected_only_without_failed_steps(monkeypatch):
    # 러너 미획득(GitHub 장애): 실패 스텝 0 + 주석 「not acquired by Runner」 → True. 스텝이 실패했으면 코드 문제 → False.
    note = [{"annotation_level": "failure", "message": "The job was not acquired by Runner of type hosted even after multiple attempts"}]
    infra = {"jobs": [{"id": 1, "conclusion": "cancelled", "steps": []}]}
    code = {"jobs": [{"id": 2, "conclusion": "failure", "steps": [{"name": "검증", "conclusion": "failure"}]}]}
    monkeypatch.setattr(W, "_api", lambda p: note if "annotations" in p else infra)
    assert W._infra_failure("1") is True
    monkeypatch.setattr(W, "_api", lambda p: note if "annotations" in p else code)
    assert W._infra_failure("2") is False
    monkeypatch.setattr(W, "_api", lambda p: [] if "annotations" in p else infra)
    assert W._infra_failure("1") is False          # 주석이 없으면 모른다 → 평소대로 통지


def test_pages_stuck_cancels_only_old_waiting_runs(monkeypatch):
    """사이트 배포 대기 런은 PAGES_STUCK_MIN 분을 넘긴 것만 취소한다 — 정상 대기(1~2분)를 건드리면 배포가 늦어진다.
    2026-10-06·07 에 waiting 런 하나가 그룹을 잡아 14시간·7.5시간 동안 뒤 배포 93건이 전부 취소됐다(cancelled 는 정상으로
    세므로 침묵 감시는 못 본다)."""
    import datetime as dt
    now = dt.datetime(2026, 10, 7, 2, 0, tzinfo=dt.timezone.utc)
    iso = lambda m: (now - dt.timedelta(minutes=m)).isoformat()
    waiting = [{"id": 1, "created_at": iso(25)}, {"id": 2, "created_at": iso(5)}]
    monkeypatch.setattr(W, "_api", lambda p: {"workflow_runs": waiting if "status=waiting" in p else []})
    posted = []
    monkeypatch.setattr(W, "_api_post", lambda p: posted.append(p) or 202)
    got = W.check_pages_stuck(now)
    assert [(rid, st) for rid, st, _ in got] == [(1, "waiting")]
    assert posted == [f"/repos/{W._repo()}/actions/runs/1/cancel"]


def test_pages_stuck_survives_cancel_and_query_failures(monkeypatch):
    """취소 409(좀비 런)·조회 실패는 감시를 죽이지 않고 다음 상태로 넘어간다."""
    import datetime as dt
    import urllib.error
    now = dt.datetime(2026, 10, 7, 2, 0, tzinfo=dt.timezone.utc)
    old = (now - dt.timedelta(minutes=60)).isoformat()

    def api(p):
        if "status=waiting" in p:
            raise urllib.error.URLError("boom")
        return {"workflow_runs": [{"id": 9, "created_at": old}]}
    monkeypatch.setattr(W, "_api", api)

    def post(_p):
        raise urllib.error.HTTPError("u", 409, "Conflict", {}, None)
    monkeypatch.setattr(W, "_api_post", post)
    assert W.check_pages_stuck(now) == []


def test_watchdog_can_cancel_runs():
    """취소는 actions: write 가 있어야 한다 — read 면 403 으로 조용히 실패해 자가 치유가 없는 것과 같다."""
    assert re.search(r"^\s*actions:\s*write", WATCHDOG_YML, re.M), "watchdog.yml 에 actions: write 가 없다"



def _cause_api(notes):
    jobs = {"jobs": [{"id": 7, "conclusion": "failure", "steps": [{"name": "Run actions/deploy-pages@x", "conclusion": "failure"}]}]}
    return lambda p: notes if "annotations" in p else jobs


def test_failure_cause_marks_github_side(monkeypatch):
    # 2026-11-04 사이트 배포 멈춤의 실제 주석 — GitHub 쪽 장애로 읽고 커밋 해시는 7자로 줄인다.
    notes = [{"annotation_level": "failure", "message": "Error: Failed to create deployment (status: 400) with build version 2a69791d56e6c7febfd953c54c8c3cb8b4013fc9."},
             {"annotation_level": "failure", "message": "HttpError: Deployment request failed for 2a69791d56e6c7febfd953c54c8c3cb8b4013fc9 due to in progress deployment. Please cancel 68ecb5d2cbd6c6e18bb0e8f44eea9ee90180505c first or wait for it to complete."},
             {"annotation_level": "notice", "message": "The ubuntu-latest label will migrate to Ubuntu 26"}]
    monkeypatch.setattr(W, "_api", _cause_api(notes))
    gh, note = W._failure_cause("1")
    assert gh is True
    assert "in progress deployment" in note and "68ecb5d " in note and "68ecb5d2c" not in note
    assert len(note) <= W.CAUSE_MAX
    for msg in ("Error: Failed to create deployment (status: 504) with build version abc",
                "Timeout reached, aborting!",
                "Fetching artifact metadata failed. Is githubstatus.com reporting issues",
                # 2026-11-06 17:55~18:16 UTC — 배포가 deployment_queued 에서 3분 멈춘 뒤 GitHub 가 거절(7건 연속).
                # 이 주석만 남아 알림이 「오류:」(우리 코드 탓)로 나갔다.
                "Deployment failed, try again later."):
        monkeypatch.setattr(W, "_api", _cause_api([{"annotation_level": "failure", "message": msg}]))
        assert W._failure_cause("1")[0] is True, msg


def test_failure_cause_code_error_is_not_github(monkeypatch):
    # 우리 스텝 실패(시험·빌드)는 GitHub 탓으로 적지 않는다 — 오류 문구만 그대로 붙인다.
    monkeypatch.setattr(W, "_api", _cause_api([{"annotation_level": "failure", "message": "Process completed with exit code 1."}]))
    assert W._failure_cause("1") == (False, "Process completed with exit code 1.")
    monkeypatch.setattr(W, "_api", _cause_api([{"annotation_level": "notice", "message": "x"}]))
    assert W._failure_cause("1") is None           # 오류 주석이 없으면 덧붙이지 않는다
    assert W._failure_cause("") is None


def test_silence_streak_shows_cause(monkeypatch):
    runs = [dict(r, id=i) for i, r in enumerate(FRESH_STREAK)]
    monkeypatch.setattr(W, "_failure_cause", lambda rid: (True, "due to in progress deployment") if rid == 0 else None)
    (name, why), = _silence(monkeypatch, runs)
    assert "GitHub 쪽 장애로 보임" in why and "in progress deployment" in why
    monkeypatch.setattr(W, "_failure_cause", lambda rid: None)
    (name, why), = _silence(monkeypatch, runs)
    assert "└" not in why                          # 원인을 모르면 종전 문장 그대로


def test_pages_keeps_id_token_permission():
    """「id-token: write」 주석을 GitHub 쪽 장애(OIDC 시간 초과)로 읽는 근거 — 권한이 빠지면 그 판정이 거짓이 된다."""
    yml = open(os.path.join(WFDIR, "pages.yml"), encoding="utf-8").read()
    assert re.search(r"^permissions:(?:\n  .*)*\n  id-token: write", yml, re.M)
    assert W.GITHUB_SIDE.search('Ensure GITHUB_TOKEN has permission "id-token: write".')


def test_pages_deploy_retries_then_fails_loud():
    """배포는 GitHub 쪽 일시 장애를 두 번 더 시도해 흡수하되, 마지막 번은 실패를 삼키지 않는다.

    마지막 번까지 continue-on-error 면 오래가는 장애에도 런이 초록이라 watchdog 의 연속 실패·정지 감시가 눈을 감는다.
    """
    yml = open(os.path.join(WFDIR, "pages.yml"), encoding="utf-8").read()
    steps = re.split(r"\n      - ", yml.split("\n    steps:\n", 1)[1])
    deploys = [s for s in steps if "uses: actions/deploy-pages@" in s]
    assert len(deploys) == 3
    pins = {re.search(r"deploy-pages@([0-9a-f]{40})", s).group(1) for s in deploys}
    assert len(pins) == 1                                   # 세 번 모두 같은 판
    assert all("continue-on-error: true" in s for s in deploys[:2])
    assert "continue-on-error" not in deploys[-1]
    for s in deploys[1:]:
        assert re.search(r"if: steps\.deployment\.outcome == 'failure'", s)
    url = re.search(r"^      url: (.+)$", yml, re.M).group(1)
    for sid in ("deployment", "deployment_retry1", "deployment_retry2"):
        assert f"steps.{sid}.outputs.page_url" in url, sid
        assert f"id: {sid}" in yml, sid


# ── 회복 통지(2026-11-10) ─────────────────────────────────────────────────────────────
# 실패 알림만 있고 「풀렸다」는 글이 없어 #시스템의 마지막 글이 늘 옛 오류였다 — 사흘 동안 새 알림이 0건인데도
# 「계속 실패 중」으로 읽혀 같은 조사가 반복됐다. 알림이 나간 실패만, 한 번만 회복을 쓴다.

def _recovered(monkeypatch, runs, prev_ago=30, inst=True, infra=False, thr=lambda _wf, _t: 30):
    """WATCH 한 종으로 check_recovered 를 돌린다. 지금 = 이 감시 시작 = 12:00 UTC, 직전 감시 = prev_ago 분 전."""
    import datetime as dt
    now = dt.datetime(2026, 11, 10, 12, 0, tzinfo=dt.timezone.utc)
    iso = lambda m: (now - dt.timedelta(minutes=m)).isoformat()
    runs = [dict(r) for r in runs]
    for i, r in enumerate(runs):
        ago = r.pop("ago")
        r.setdefault("status", "completed")
        r.setdefault("id", 100 - i)
        r["created_at"], r["updated_at"] = iso(ago), iso(r.pop("done", ago))
    monkeypatch.setattr(W, "WATCH", [("x.yml", "X", 30, 30, inst)])
    monkeypatch.setattr(W, "_threshold", thr)
    monkeypatch.setattr(W, "_prev_check",
                        lambda: None if prev_ago is None else now - dt.timedelta(minutes=prev_ago))
    monkeypatch.setattr(W, "_self_started", lambda n: n)
    monkeypatch.setattr(W, "_infra_failure", lambda _rid: infra)
    monkeypatch.setattr(W, "_api", lambda _p: {"workflow_runs": runs})
    return W.check_recovered(now)


BACK = [{"ago": 3, "conclusion": "success"},        # 3분 전 다시 정상
        {"ago": 8, "conclusion": "failure"},
        {"ago": 13, "conclusion": "failure"},
        {"ago": 60, "conclusion": "success"}]


def test_recovery_reported_once_after_notified_failure(monkeypatch):
    """즉시 통지가 나간 실패가 풀리면 한 줄 — 다음 감시(창이 지난 뒤)는 다시 안 쓴다."""
    out = _recovered(monkeypatch, BACK)
    assert len(out) == 1 and "실패 2건" in out[0][1] and "다시 정상" in out[0][1], out
    assert _recovered(monkeypatch, BACK, prev_ago=1) == []


def test_recovery_only_for_failures_that_were_notified(monkeypatch):
    """알린 적 없는 실패의 회복은 쓰지 않는다 — 혼자 뜬 「회복」은 무엇이 고장 났었는지 되묻게 만든다."""
    assert _recovered(monkeypatch, BACK, inst=False) == []       # 즉시 통지 밖 · 2건 < STREAK_MIN
    assert _recovered(monkeypatch, BACK, infra=True) == []       # 러너 미획득은 통지를 생략했었다
    three = BACK[:3] + [{"ago": 18, "conclusion": "failure"}] + BACK[3:]
    assert len(_recovered(monkeypatch, three, inst=False)) == 1  # 연속 실패 3건은 침묵 감시가 알렸다


def test_recovery_quiet_while_failing_or_clean(monkeypatch):
    assert _recovered(monkeypatch, [{"ago": 2, "conclusion": "failure"}] + BACK) == []   # 다시 실패 중
    assert _recovered(monkeypatch, [{"ago": m, "conclusion": "success"} for m in (2, 7, 12)]) == []
    cancelled = [{"ago": 2, "conclusion": "cancelled"}] + BACK                         # 취소는 건너뛴다
    assert len(_recovered(monkeypatch, cancelled)) == 1


def test_recovery_unknown_prev_uses_short_window(monkeypatch):
    """직전 감시를 모르면 최근 RECOVER_WINDOW_MIN 분 안의 회복만 — 모를 때 옛 회복을 매번 다시 쓰지 않는다."""
    assert len(_recovered(monkeypatch, BACK, prev_ago=None)) == 1
    old = [dict(r, ago=r["ago"] + 60) for r in BACK]
    assert _recovered(monkeypatch, old, prev_ago=None) == []


def test_stall_recovery(monkeypatch):
    """끊김 알림(직전 감시 때 임계 초과)이 나간 뒤 새 런이 생기면 회복."""
    stall = [{"ago": 5, "conclusion": "success"}, {"ago": 100, "conclusion": "success"}]
    out = _recovered(monkeypatch, stall)                      # 직전 감시 땐 70분째 없었다 > 임계 30
    assert len(out) == 1 and "다시 돈다" in out[0][1], out
    assert _recovered(monkeypatch, stall, thr=lambda _wf, _t: 120) == []   # 임계 안 — 알린 적 없다
    assert _recovered(monkeypatch, stall, thr=lambda _wf, _t: None) == []  # 감시 밖 시간
    steady = [{"ago": 5, "conclusion": "success"}, {"ago": 40, "conclusion": "success"}]
    assert _recovered(monkeypatch, steady) == []              # 직전 감시 땐 10분째 — 끊김 아니었다


def _main_calls(monkeypatch, stalled, recovered, ok=True):
    calls = []
    monkeypatch.setenv("WATCHDOG_MODE", "silence")
    monkeypatch.setattr(W, "check_pages_stuck", lambda: [])
    monkeypatch.setattr(W, "check_silence", lambda: list(stalled))
    monkeypatch.setattr(W, "check_site_lag", lambda: [])
    monkeypatch.setattr(W, "check_recovered", recovered if callable(recovered) else (lambda: list(recovered)))
    monkeypatch.setattr(W.notify_discord, "system", lambda b, title="", **_k: calls.append((title, b)) or ok)
    W.main()
    return calls


def test_main_recovery_alone_or_merged_into_remaining_alert(monkeypatch):
    """회복만 있으면 회복 한 통. 남은 이상이 있으면 한 통에 합친다 — 따로 보내면 회복을 쓴 뒤 침묵 통지가 실패했을 때
    런이 실패로 끝나 다음 감시가 같은 회복을 또 쓴다(2026-11-10 검토)."""
    calls = _main_calls(monkeypatch, [], [("X", "다시 정상")])
    assert [t for t, _ in calls] == ["✅ 회복"], calls
    calls = _main_calls(monkeypatch, [("Y", "끊김")], [("X", "다시 정상")])
    assert len(calls) == 1 and calls[0][0] == "🔇 알림 파이프라인 침묵", calls
    assert calls[0][1].index("Y") < calls[0][1].index("✅ 회복") < calls[0][1].index("X"), calls[0][1]
    assert _main_calls(monkeypatch, [], []) == []


def test_main_recovery_notify_failure_fails_run(monkeypatch):
    """회복 통지를 못 했는데 성공으로 끝나면 다음 감시가 이 런을 '직전 감시'로 세어 회복을 영영 안 쓴다."""
    import pytest
    with pytest.raises(SystemExit):
        _main_calls(monkeypatch, [], [("X", "다시 정상")], ok=False)


def test_main_survives_recovery_check_crash(monkeypatch):
    def boom():
        raise RuntimeError("x")
    calls = _main_calls(monkeypatch, [("Y", "끊김")], boom)
    assert len(calls) == 1 and "✅ 회복" not in calls[0][1], calls
