"""토스 수집기는 사람이 쓰는 저장소 폴더를 건드리지 않는다(2026-11-04 사고: reset --hard 로 커밋 전 수정 소실).

임시 원격(bare) + 사람 폴더(clone) + 수집기 전용 worktree 를 만들어, 푸시 뒤에도 사람 폴더의 HEAD · 작업 중 수정이
그대로인지, 원격엔 스냅샷 커밋만 올라갔는지 본다. 네트워크 없이 로컬 git 만 쓴다.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fetch_toss_snapshot as f   # noqa: E402


def g(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True).stdout


@pytest.fixture
def repos(tmp_path, monkeypatch):
    origin, human, push = tmp_path / "origin.git", tmp_path / "human", tmp_path / "push"
    g("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    g("clone", "-q", str(origin), str(human), cwd=tmp_path)
    for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
        g("config", k, v, cwd=human)
    (human / "toss_snapshot.json").write_text(json.dumps({"payloadHash": "old"}), encoding="utf-8")
    (human / "code.py").write_text("print(1)\n", encoding="utf-8")
    g("add", ".", cwd=human)
    g("commit", "-q", "-m", "init", cwd=human)
    g("push", "-q", "origin", "main", cwd=human)
    monkeypatch.setattr(f, "ROOT", str(human))
    monkeypatch.setattr(f, "OUT", str(human / "toss_snapshot.json"))
    monkeypatch.setenv("TOSS_PUSH_DIR", str(push))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.com")
    monkeypatch.setattr(f, "log", lambda *a, **k: None)
    return origin, human, push


def test_push_leaves_human_tree_alone(repos):
    origin, human, push = repos
    (human / "code.py").write_text("print('사람이 고치는 중')\n", encoding="utf-8")   # 커밋 전 수정
    head = g("rev-parse", "HEAD", cwd=human).strip()

    out = f._prepare_push_dir(str(push))
    assert out == os.path.join(str(push), "toss_snapshot.json")
    assert json.load(open(out, encoding="utf-8")) == {"payloadHash": "old"}       # 원격 판을 꺼냈다
    assert not (push / "code.py").exists()                                        # 파일 트리는 펼치지 않는다
    f._LAST_PAYLOAD = json.dumps({"payloadHash": "new"})
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(f._LAST_PAYLOAD)
    assert f.git_push() is True

    assert (human / "code.py").read_text(encoding="utf-8") == "print('사람이 고치는 중')\n"   # 수정 그대로
    assert g("rev-parse", "HEAD", cwd=human).strip() == head                        # 사람 브랜치도 그대로
    assert json.loads((human / "toss_snapshot.json").read_text(encoding="utf-8")) == {"payloadHash": "old"}
    remote = json.loads(g("show", "main:toss_snapshot.json", cwd=origin))
    assert remote == {"payloadHash": "new"}
    changed = g("show", "--name-only", "--format=", "main", cwd=origin).split()
    assert changed == ["toss_snapshot.json"]                                        # 스냅샷만 커밋


def test_clean_human_tree_fast_forwards(repos):
    """수정 중인 파일이 없고 main 이면 사람 폴더도 origin 으로 따라간다(수집기 스크립트가 최신으로 남게)."""
    origin, human, push = repos
    out = f._prepare_push_dir(str(push))
    f._LAST_PAYLOAD = json.dumps({"payloadHash": "ff"})
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(f._LAST_PAYLOAD)
    assert f.git_push() is True
    assert g("rev-parse", "HEAD", cwd=human) == g("rev-parse", "main", cwd=origin)
    assert json.loads((human / "toss_snapshot.json").read_text(encoding="utf-8")) == {"payloadHash": "ff"}


def test_push_retries_over_newer_origin(repos):
    origin, human, push = repos
    out = f._prepare_push_dir(str(push))
    # 그사이 다른 커밋(봇·서버 수집기)이 먼저 올라간다
    (human / "code.py").write_text("print(2)\n", encoding="utf-8")
    g("commit", "-q", "-am", "bot", cwd=human)
    g("push", "-q", "origin", "main", cwd=human)
    f._LAST_PAYLOAD = json.dumps({"payloadHash": "mine"})
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(f._LAST_PAYLOAD)
    assert f.git_push() is True
    assert json.loads(g("show", "main:toss_snapshot.json", cwd=origin)) == {"payloadHash": "mine"}
    assert g("show", "main:code.py", cwd=origin) == "print(2)\n"                     # 남의 커밋 위에 얹었다


def test_no_change_skips(repos):
    _, _, push = repos
    f._prepare_push_dir(str(push))
    assert f.git_push() is True                                                     # 변경 없음 — 커밋 0


def test_push_dir_only_on_windows_or_env(monkeypatch):
    monkeypatch.delenv("TOSS_PUSH_DIR", raising=False)
    monkeypatch.setattr(f.os, "name", "posix")
    assert f.push_dir() is None                                                     # 서버(Linux)는 종전 경로


# ── KRX 로그인 결과(fetch_data) — 실패하면 코드를 남기고 이 런의 재시도를 끈다 ──
def test_krx_login_outcome(monkeypatch):
    import fetch_data as fd
    from pykrx.website.comm import auth
    logs = []
    monkeypatch.setattr(fd, "log", logs.append)
    monkeypatch.setattr(fd, "_PYKRX_AVAILABLE", True)
    monkeypatch.setattr(fd, "_KRX_LOGIN_AVAILABLE", True)
    monkeypatch.setattr(fd, "KRX_LOGIN_TRACE", [(200, "CD003", "비밀번호가 일치하지 않습니다")])
    monkeypatch.setattr(auth, "_auth_session", None, raising=False)
    monkeypatch.setenv("KRX_ID", "someone")
    monkeypatch.setenv("KRX_PW", "x")
    assert fd._krx_login_outcome() is False
    assert "CD003" in logs[-1] and "someone" not in logs[-1]
    assert "KRX_ID" not in os.environ and "KRX_PW" not in os.environ          # 재시도 막힘
    monkeypatch.setattr(auth, "_auth_session", object(), raising=False)
    monkeypatch.setattr(fd, "KRX_LOGIN_TRACE", [(200, "CD001", "")])
    assert fd._krx_login_outcome() is True
