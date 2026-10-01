"""check_secrets / install_hooks 검사. 실행: python scripts/tests/test_check_secrets.py"""
import os
import subprocess
import sys
import tempfile

SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CHECK = os.path.join(SCRIPTS, "check_secrets.py")
INSTALL = os.path.join(SCRIPTS, "install_hooks.py")

# 가짜 값은 조각을 이어 붙여 만든다 (이 파일 자체가 스캔에 걸리지 않도록)
GH = "ghp" + "_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
PEM = "-----BEGIN RSA " + "PRIVATE KEY-----"
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
HEX = "0123456789abcdef" * 2 + "0123"


def repo(files):
    d = tempfile.mkdtemp()
    run = lambda *a, **k: subprocess.run(a, cwd=d, capture_output=True, text=True, **k)
    run("git", "init", "-q")
    for name, body in files.items():
        p = os.path.join(d, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
    run("git", "add", "-A")
    return d


def check(d, *args):
    return subprocess.run([sys.executable, CHECK, *args], cwd=d, capture_output=True,
                          text=True, encoding="utf-8")


def t_github_token():
    r = check(repo({"a.py": f'T = "{GH}"\n'}))
    assert r.returncode == 1 and "a.py:1" in r.stdout and GH not in r.stdout, r.stdout


def t_pem():
    r = check(repo({"k.txt": f"x\n{PEM}\nabc\n"}))
    assert r.returncode == 1 and "k.txt:2" in r.stdout


def t_aws_and_hex_near_name():
    r = check(repo({"a.py": f'a="{AWS}"\napi_secret = "{HEX}"\n'}))
    assert r.returncode == 1 and "a.py:1" in r.stdout and "a.py:2" in r.stdout


def t_allow_comment():
    r = check(repo({"a.py": f'T = "{GH}"  # secret-ok\n'}))
    assert r.returncode == 0, r.stdout


def t_bot_files_skipped():
    r = check(repo({"data.json": f'{{"token": "{GH}"}}', "bundles/x.json": f'"{GH}"',
                    "node_modules/m/i.js": f'"{GH}"'}))
    assert r.returncode == 0, r.stdout


def t_filename_patterns():
    r = check(repo({"a.key": "x", "b.pem": "x", "동기화키.txt": "x", ".env": "A=1",
                    ".dev.vars": "A=1", ".env.example": "A=", "ok.py": "x=1\n"}))
    assert r.returncode == 1
    for n in ("a.key", "b.pem", "동기화키.txt", ".env", ".dev.vars"):
        assert n in r.stdout, (n, r.stdout)
    assert ".env.example" not in r.stdout and "ok.py" not in r.stdout


def t_binary_and_clean():
    d = repo({"img.bin": "\0\0" + GH, "ok.py": "token = os.environ['T']\nBearer ${T}\n"})
    assert check(d).returncode == 0


def t_all_flag_and_staged_scope():
    d = repo({"a.py": "x=1\n"})
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"],
                   cwd=d, capture_output=True)
    with open(os.path.join(d, "b.py"), "w") as f:
        f.write(f'T="{GH}"\n')  # 스테이징 안 한 파일
    subprocess.run(["git", "add", "-N", "b.py"], cwd=d)
    assert check(d).returncode == 0  # 기본: 스테이징 대상 아님(-N 은 내용 없음)
    subprocess.run(["git", "add", "b.py"], cwd=d)
    assert check(d, "--all").returncode == 1


def t_install_idempotent_and_append():
    d = repo({"a.py": "x=1\n"})
    hook = os.path.join(d, ".git", "hooks", "pre-commit")
    os.makedirs(os.path.dirname(hook), exist_ok=True)
    with open(hook, "w") as f:
        f.write("#!/bin/sh\necho existing\n")
    for _ in range(2):
        subprocess.run([sys.executable, INSTALL], cwd=d, check=True, capture_output=True)
    body = open(hook, encoding="utf-8").read()
    assert "echo existing" in body and body.count("scripts/check_secrets.py") == 3  # 존재 확인 + python + py 분기
    assert body.count("install_hooks.py 가 추가") == 1


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            try:
                fn()
                print("통과", name)
            except AssertionError as e:
                fails += 1
                print("실패", name, e)
    sys.exit(1 if fails else 0)
