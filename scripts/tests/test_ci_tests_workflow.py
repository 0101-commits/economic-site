#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""병합 전 시험(tests.yml)이 운영 시험 관문과 같은 환경인가 — 글자로 맞춘다.

운영 관문(stock-alerts · kakao-daily · fetch-data 의 「Run tests」)만 있던 동안 깨진 시험은 main 에 들어간 뒤에야
드러났고, 그때마다 매분 런이 멈추며 #시스템에 실패 알림이 떴다(2026-10-27 ~ 11-04, 8건). tests.yml 이 그걸 병합 전에
잡으려면 운영과 **같은 패키지**로 돌아야 한다 — 한쪽에만 pykrx · cryptography 가 있으면 「병합 전엔 초록, 운영에선 빨강」이
다시 생긴다(11-04 test_toss_push_dir 이 정확히 그랬다). 운영 쪽 pip install 을 바꾸면 tests.yml 의 matrix 도 같이 바꿀 것.
"""
import os
import re
import shlex

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
WFDIR = os.path.join(ROOT, ".github", "workflows")

# 운영 워크플로 → tests.yml matrix 의 env 이름
PROD = {"stock-alerts.yml": "light", "kakao-daily.yml": "light", "fetch-data.yml": "full"}


def _read(name):
    with open(os.path.join(WFDIR, name), encoding="utf-8") as f:
        return f.read()


def _pkgs(line):
    """`pip install a "b==1" c` → {"a", "b==1", "c"} (소문자 — PyYAML 과 pyyaml 은 같은 패키지)."""
    args = shlex.split(line.split("pip install", 1)[1])
    return {a.lower() for a in args if not a.startswith("-")}


def _steps(text):
    """`- name:` 단위로 [(이름, 주석 뺀 줄들)]."""
    out = []
    for raw in text.splitlines():
        m = re.match(r"^\s*-\s+name:\s*(.*?)\s*$", raw)
        if m:
            out.append((m.group(1).strip("'\""), []))
        elif out and not raw.lstrip().startswith("#"):
            out[-1][1].append(raw)
    return out


def prod_test_env(name):
    """운영 워크플로에서 「Run tests」 까지(포함) 깔리는 패키지 전부."""
    pkgs = set()
    for step, lines in _steps(_read(name)):
        for x in lines:
            if re.search(r"\bpip install\b", x):
                pkgs |= _pkgs(x)
        if step == "Run tests":
            return pkgs
    raise AssertionError(f"{name} 에 「Run tests」 단계가 없다")


def ci_envs():
    text = _read("tests.yml")
    envs = dict(re.findall(r"-\s*env:\s*(\w+)\s*\n\s*deps:\s*(.+)", text))
    return {k: _pkgs("pip install " + v) for k, v in envs.items()}


def test_ci_envs_match_production_gates():
    envs = ci_envs()
    assert set(envs) == set(PROD.values()), envs
    for wf, env in PROD.items():
        assert prod_test_env(wf) == envs[env], (
            f"{wf} 의 시험 환경 {sorted(prod_test_env(wf))} 과 tests.yml {env} {sorted(envs[env])} 이 다르다")


def test_ci_runs_whole_suite_on_pull_requests():
    text = _read("tests.yml")
    assert re.search(r"^  pull_request:\s*\n\s+branches:\s*\[\s*main\s*\]", text, re.M), "PR 에서 안 돈다"
    assert "python -m pytest scripts/tests" in text
    run = dict(_steps(text)).get("Run tests") or []
    assert not any(re.match(r"^\s*continue-on-error\s*:", x) for x in run), "시험 실패를 삼킨다"
    assert not any(re.match(r"^\s*if\s*:", x) for x in run), "시험이 조건부로 건너뛰어진다"


def test_ci_python_matches_production():
    ver = lambda t: set(re.findall(r"python-version:\s*'([\d.]+)'", t))
    want = set().union(*(ver(_read(wf)) for wf in PROD))
    assert ver(_read("tests.yml")) == want, (ver(_read("tests.yml")), want)
