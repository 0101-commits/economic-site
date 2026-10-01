#!/usr/bin/env python3
"""pre-commit 훅에 비밀 검사를 설치한다. 워크트리에서도 맞는 경로를 쓰고, 여러 번 실행해도 안전하다."""
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


def main():
    hooks = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], capture_output=True,
                           text=True, check=True).stdout.strip()
    os.makedirs(hooks, exist_ok=True)
    path = os.path.abspath(os.path.join(hooks, "pre-commit"))
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if MARK in old:
        print("이미 설치됨:", path)
        return
    new = (old.rstrip("\n") + "\n\n" + BLOCK) if old else "#!/bin/sh\n" + BLOCK
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    os.chmod(path, 0o755)
    print("설치함:", path)


if __name__ == "__main__":
    main()
