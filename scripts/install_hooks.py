#!/usr/bin/env python3
"""pre-commit 훅에 비밀 검사 · 화면 금지어 · 폰 알림 글자 수 검사를 설치한다. 워크트리에서도 맞는 경로를 쓰고, 여러 번 실행해도 안전하다."""
import os
import subprocess

MARK = "scripts/check_secrets.py"
BLOCK = f"""# 비밀값 검사 (scripts/install_hooks.py 가 추가)
# 스크립트가 없는 체크아웃(훅 경로는 워크트리끼리 공유)에서는 건너뛴다
if [ -f {MARK} ]; then
  if command -v python >/dev/null 2>&1; then
    python {MARK} || exit 1
  else
    py -3 {MARK} || exit 1
  fi
fi
"""


TERMS = "scripts/check_terms.py"
TERMS_BLOCK = f"""# 화면 금지어 검사 (scripts/install_hooks.py 가 추가 · 용어 정제 2026-10-30)
if [ -f {TERMS} ]; then
  if command -v python >/dev/null 2>&1; then
    python {TERMS} || exit 1
  else
    py -3 {TERMS} || exit 1
  fi
fi
"""


COPY = "scripts/alerts_v2/check_copy.py"
COPY_BLOCK = f"""# 폰 알림 글자 수 검사 (scripts/install_hooks.py 가 추가 · 알림 개편 P5 2026-11-06) — 알림 글 파일을 바꾼 커밋만
if [ -f {COPY} ] && git diff --cached --name-only | grep -qE '^scripts/alerts_v2/(events\.yml|compose\.py|judges_[a-z_]+\.py|check_copy\.py)$'; then
  PY=python; command -v python >/dev/null 2>&1 || PY="py -3"
  if $PY -c "import yaml, zoneinfo; zoneinfo.ZoneInfo('Asia/Seoul')" >/dev/null 2>&1; then
    $PY {COPY} || exit 1
  else
    echo "[글자 수] 건너뜀 — 이 파이썬에 pyyaml · tzdata 가 없다(CI 시험 test_v2_check_copy 가 대신 막는다)"
  fi
fi
"""


def main():
    hooks = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], capture_output=True,
                           text=True, check=True).stdout.strip()
    os.makedirs(hooks, exist_ok=True)
    path = os.path.abspath(os.path.join(hooks, "pre-commit"))
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    new = old
    for mark, block in ((MARK, BLOCK), (TERMS, TERMS_BLOCK), (COPY, COPY_BLOCK)):
        if mark not in new:
            new = (new.rstrip("\n") + "\n\n" + block) if new else "#!/bin/sh\n" + block
    if new == old:
        print("이미 설치됨:", path)
        return
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    os.chmod(path, 0o755)
    print("설치함:", path)


if __name__ == "__main__":
    main()
