"""CI 관문 — 수집·발송 워크플로 셋에 「Run tests」 단계가 있고, 발송·수집 단계보다 앞이며, 실패를 삼키지 않는다.

테스트가 깨진 코드로 알림이 나가거나 data.json 이 커밋되는 것을 막는 장치가 이 한 단계다. 그래서 그 단계가
①없어지거나 ②발송 단계 뒤로 밀리거나 ③continue-on-error 로 실패를 삼키거나 ④명령이 바뀌어 일부만 도는 일이
조용히 일어나지 않게, 워크플로 파일을 글자로 읽어 확인한다(PyYAML 없이 — 줄 단위).

「Run tests」 는 통과 마커(actions/cache)가 적중하면 건너뛸 수 있다 — 그 조건부 구조도 같이 지킨다(marker_problems).

주석 줄(`#`)은 보지 않는다. 주석에는 「continue-on-error 를 달지 말 것」 같은 설명이 있어 그대로 찾으면 오탐이다.
"""
import os
import re

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORKFLOWS_DIR = os.path.join(ROOT, ".github", "workflows")

STEP_NAME = "Run tests"
PYTEST_CMD = "python -m pytest scripts/tests -q -x"

# 워크플로마다 「이 스크립트를 돌리는 줄」이 대표 발송·수집 단계다(과제 계약서 A1).
WORKFLOWS = {
    "fetch-data.yml": "fetch_data.py",
    "stock-alerts.yml": "check_alerts.py",
    "kakao-daily.yml": "send_kakao_digest.py",
}

_STEP_START = re.compile(r"^\s*-\s+name:\s*(.*?)\s*$")
_SCRIPT_RUN = re.compile(r"\bpython3?\s+scripts/\S+\.py\b")
_PIP_INSTALL = re.compile(r"\bpip\s+install\b")
_CONTINUE = re.compile(r"^\s*continue-on-error\s*:")


def split_steps(text):
    """`- name:` 마다 한 단계. 반환 = [(이름, 주석 뺀 줄 목록)]."""
    steps = []
    for raw in text.splitlines():
        m = _STEP_START.match(raw)
        if m:
            steps.append((m.group(1).strip("'\""), []))
            continue
        if steps and not raw.lstrip().startswith("#"):
            steps[-1][1].append(raw)
    return steps


def _field(lines, key):
    """단계 줄들에서 `key: 값` 의 값(뒤 주석 뺀 것). 없으면 ""."""
    for x in lines:
        m = re.match(rf"^\s*{key}:\s*(.*?)\s*$", x)
        if m:
            return re.sub(r"\s+#.*$", "", m.group(1))
    return ""


# 통과 마커(같은 코드 상태에서 이미 통과했으면 Run tests 를 건너뛰는 캐시). 마커가 거짓으로 저장되면 관문이 조용히
# 꺼지므로, 「적중일 때만 건너뜀 · 복원이 테스트 앞 · 저장이 테스트 뒤(성공했을 때만)」 구조를 글자로 지킨다.
TESTS_OK = "tests-ok"
SKIP_ON_HIT = "steps.tests-ok.outputs.cache-hit != 'true'"
ALLOWED_IF = {SKIP_ON_HIT, "steps.gate.outputs.proceed == 'true'", "steps.marker.outputs.cache-hit != 'true'"}


def marker_problems(steps, t):
    cond = _field(steps[t][1], "if")
    if not cond:
        return []                                   # 무조건 도는 단계 — 마커를 쓰지 않는다
    parts = [p.strip() for p in cond.split("&&")]
    out = []
    if "||" in cond or any(p not in ALLOWED_IF for p in parts):
        out.append(f"「{STEP_NAME}」 의 if 가 허용된 조건(마커 적중·발송 창·중복 발송 마커)의 && 연결이 아니다: {cond}")
    if SKIP_ON_HIT not in parts:
        return out
    restore = [i for i, (_n, ls) in enumerate(steps) if _field(ls, "id") == TESTS_OK]
    if len(restore) != 1:
        return out + [f"id: {TESTS_OK} 단계가 {len(restore)}개다(정확히 1개여야 한다)"]
    r = restore[0]
    rl = steps[r][1]
    key, path = _field(rl, "key"), _field(rl, "path")
    if r > t:
        out.append("마커 복원 단계가 「Run tests」 보다 뒤다")
    if not _field(rl, "uses").startswith("actions/cache/restore@"):
        out.append("마커 복원 단계가 actions/cache/restore 가 아니다")
    if not (key.startswith("pytest-ok-") and "hashFiles(" in key and "scripts/**/*.py" in key):
        out.append(f"마커 키가 `pytest-ok-${{{{ hashFiles('scripts/**/*.py', …) }}}}` 꼴이 아니다: {key}")
    saves = [i for i, (_n, ls) in enumerate(steps) if _field(ls, "uses").startswith("actions/cache/save@")
             and _field(ls, "path") == path]
    if len(saves) != 1:
        return out + [f"마커 저장 단계(actions/cache/save, path={path})가 {len(saves)}개다(정확히 1개여야 한다)"]
    s = saves[0]
    sl = steps[s][1]
    if s < t:
        out.append("마커 저장 단계가 「Run tests」 보다 앞이다 — 테스트 전에 마커가 저장된다")
    if _field(sl, "key") != key:
        out.append("마커 저장 키가 복원 키와 다르다")
    if re.search(r"\b(always|failure|cancelled)\(\)", _field(sl, "if")):
        out.append("마커 저장 단계의 if 가 always()/failure()/cancelled() 다 — 테스트가 실패해도 저장된다")
    return out


def problems(text, main_script):
    """워크플로 본문 하나를 점검해 문제 문장 목록을 돌려준다(없으면 [])."""
    steps = split_steps(text)
    names = [n for n, _ in steps]
    out = []
    idx = [i for i, n in enumerate(names) if n == STEP_NAME]
    if len(idx) != 1:
        return [f"「{STEP_NAME}」 단계가 {len(idx)}개다(정확히 1개여야 한다)"]
    t = idx[0]
    body = "\n".join(steps[t][1])
    if PYTEST_CMD not in body:
        out.append(f"「{STEP_NAME}」 단계에 `{PYTEST_CMD}` 가 없다")
    if any(_CONTINUE.match(line) for line in steps[t][1]):
        out.append(f"「{STEP_NAME}」 단계에 continue-on-error 가 있다 — 실패가 삼켜진다")
    # Install deps 뒤: 테스트 단계가 아닌 첫 pip install 단계보다 뒤
    installs = [i for i, (n, ls) in enumerate(steps) if i != t and any(_PIP_INSTALL.search(x) for x in ls)]
    if not installs:
        out.append("패키지 설치(pip install) 단계를 찾지 못했다")
    elif t < installs[0]:
        out.append(f"「{STEP_NAME}」 단계가 패키지 설치 단계(「{names[installs[0]]}」)보다 앞이다")
    # 발송·수집 앞: python scripts/*.py 를 돌리는 첫 단계보다 앞(대표 스크립트는 반드시 찾아야 한다)
    runs = [i for i, (n, ls) in enumerate(steps) if i != t and any(_SCRIPT_RUN.search(x) for x in ls)]
    main_at = [i for i, (n, ls) in enumerate(steps)
               if i != t and any(re.search(rf"\bpython3?\s+scripts/{re.escape(main_script)}\b", x) for x in ls)]
    if not main_at:
        out.append(f"`python scripts/{main_script}` 를 돌리는 단계를 찾지 못했다 — 이 검사가 낡았다")
    if runs and t > runs[0]:
        out.append(f"「{STEP_NAME}」 단계가 스크립트 실행 단계(「{names[runs[0]]}」)보다 뒤다")
    if main_at and t > main_at[0]:
        out.append(f"「{STEP_NAME}」 단계가 `{main_script}` 실행 단계보다 뒤다")
    return out + marker_problems(steps, t)


@pytest.mark.parametrize("name,main_script", sorted(WORKFLOWS.items()))
def test_workflow_runs_pytest_before_sending(name, main_script):
    path = os.path.join(WORKFLOWS_DIR, name)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert problems(text, main_script) == [], f"{name}: " + " / ".join(problems(text, main_script))


# ── 검사기 자체 — 아무것도 못 잡는 검사가 되지 않게, 일부러 틀린 워크플로를 먹여 본다 ──────────
GOOD = """\
jobs:
  j:
    steps:
      - name: Install deps
        run: pip install requests
      # continue-on-error 를 달지 말 것 — 이 주석은 문제가 아니다
      - name: Run tests
        run: |
          pip install pytest
          python -m pytest scripts/tests -q -x
      - name: Send
        run: python scripts/check_alerts.py
"""


def test_checker_accepts_a_good_workflow():
    assert problems(GOOD, "check_alerts.py") == []


def test_checker_flags_missing_step():
    bad = GOOD.replace("- name: Run tests", "- name: Something else")
    assert problems(bad, "check_alerts.py")


def test_checker_flags_test_step_after_send_step():
    bad = """\
jobs:
  j:
    steps:
      - name: Install deps
        run: pip install requests
      - name: Send
        run: python scripts/check_alerts.py
      - name: Run tests
        run: |
          pip install pytest
          python -m pytest scripts/tests -q -x
"""
    ps = problems(bad, "check_alerts.py")
    assert ps and any("뒤" in p for p in ps)


def test_checker_flags_continue_on_error():
    bad = GOOD.replace("      - name: Run tests\n", "      - name: Run tests\n        continue-on-error: true\n")
    assert any("continue-on-error" in p for p in problems(bad, "check_alerts.py"))


def test_checker_flags_changed_command():
    for cmd in ("python -m pytest scripts/tests -q", "python -m pytest scripts/tests/test_a.py -q -x"):
        bad = GOOD.replace(PYTEST_CMD, cmd)
        assert any("가 없다" in p for p in problems(bad, "check_alerts.py")), cmd


def test_checker_flags_test_step_before_install():
    bad = """\
jobs:
  j:
    steps:
      - name: Run tests
        run: |
          python -m pytest scripts/tests -q -x
      - name: Install deps
        run: pip install requests
      - name: Send
        run: python scripts/check_alerts.py
"""
    assert any("패키지 설치" in p for p in problems(bad, "check_alerts.py"))


def test_checker_ignores_a_commented_out_pytest_line():
    bad = GOOD.replace("          python -m pytest scripts/tests -q -x", "          # python -m pytest scripts/tests -q -x")
    assert any("가 없다" in p for p in problems(bad, "check_alerts.py"))


# ── 통과 마커 구조 ────────────────────────────────────────────────────────
KEY = "pytest-ok-${{ hashFiles('scripts/**/*.py', 'scripts/alerts_v2/events.yml') }}"
SKIP = "if: steps.tests-ok.outputs.cache-hit != 'true'"
MARKED = f"""\
jobs:
  j:
    steps:
      - name: Install deps
        run: pip install requests
      - name: Restore test pass marker
        id: tests-ok
        uses: actions/cache/restore@abc # v4
        with:
          path: .pytest_ok
          key: {KEY}
      - name: Run tests
        {SKIP}
        run: |
          pip install pytest
          python -m pytest scripts/tests -q -x
          touch .pytest_ok
      - name: Save test pass marker
        {SKIP}
        uses: actions/cache/save@abc # v4
        with:
          path: .pytest_ok
          key: {KEY}
      - name: Send
        run: python scripts/check_alerts.py
"""


def _swap(text, a, b):
    """이름이 a·b 로 시작하는 두 단계의 자리를 바꾼다."""
    parts = text.split("      - name: ")
    i = next(k for k, p in enumerate(parts) if p.startswith(a))
    j = next(k for k, p in enumerate(parts) if p.startswith(b))
    parts[i], parts[j] = parts[j], parts[i]
    return "      - name: ".join(parts)


def test_marker_structure_is_accepted():
    assert problems(MARKED, "check_alerts.py") == []


@pytest.mark.parametrize("bad_if", [
    "if: steps.tests-ok.outputs.cache-hit == 'true'",                        # 적중일 때만 도는 거꾸로 된 조건
    "if: false",                                                             # 영영 안 도는 조건
    "if: steps.tests-ok.outputs.cache-hit != 'true' || always()",
])
def test_marker_flags_a_run_condition_that_can_skip_wrongly(bad_if):
    ps = problems(MARKED.replace(SKIP, bad_if, 1), "check_alerts.py")
    assert any("허용된 조건" in p for p in ps), ps


def test_marker_flags_save_that_runs_even_when_tests_fail():
    save_at = MARKED.index("Save test pass marker")
    bad = MARKED[:save_at] + MARKED[save_at:].replace(SKIP, "if: always()", 1)
    assert any("always" in p for p in problems(bad, "check_alerts.py"))


def test_marker_flags_save_before_tests():
    assert any("앞이다" in p for p in problems(_swap(MARKED, "Run tests", "Save test pass marker"), "check_alerts.py"))


def test_marker_flags_restore_after_tests():
    ps = problems(_swap(MARKED, "Restore test pass marker", "Run tests"), "check_alerts.py")
    assert any("복원 단계가" in p and "뒤다" in p for p in ps), ps


def test_marker_flags_key_mismatch_and_missing_save():
    assert any("다르다" in p for p in problems(MARKED.replace("scripts/alerts_v2/events.yml", "x", 1), "check_alerts.py"))
    no_save = MARKED.split("      - name: Save test pass marker")[0] + "      - name: Send\n        run: python scripts/check_alerts.py\n"
    assert any("저장 단계" in p for p in problems(no_save, "check_alerts.py"))
