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
        assert live and live > 0, name
        assert idle is None or idle >= live, name


def test_cancelled_is_not_a_failure():
    """concurrency 가 앞 런을 밀어낸 취소를 실패로 세면 상시 오경보가 된다.

    실측: pages 배포는 데이터 커밋마다 돌아 최근 10건 중 취소가 늘 섞여 있다.
    """
    assert "cancelled" in W.OK_CONCLUSIONS


def test_selftest_passes():
    W.demo()
