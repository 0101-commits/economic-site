"""standby 역할: 다른 host 의 신선한 스냅샷이 있으면 건너뛰고, 아니면 진행한다."""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fetch_toss_snapshot as f  # noqa: E402

KST = timezone(timedelta(hours=9))


def _stub(monkeypatch, host, age_min):
    gen = (datetime.now(KST) - timedelta(minutes=age_min)).isoformat()
    out = json.dumps({"host": host, "generatedAt": gen})

    def run(args, **kw):
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")
    monkeypatch.setattr(f.subprocess, "run", run)
    monkeypatch.setattr(f.toss_api, "enabled", lambda: True)
    monkeypatch.setattr(f, "collect", lambda: {})       # 진행하면 여기로 온다 -> 수집 0건 종료(2)
    monkeypatch.setattr(f, "_notify_failure", lambda: None)
    monkeypatch.setenv("TOSS_SNAPSHOT_ROLE", "standby")
    monkeypatch.setenv("TOSS_SNAPSHOT_HOST", "pc")
    monkeypatch.setattr(sys, "argv", ["x"])


def test_standby_skips_when_other_fresh(monkeypatch):
    _stub(monkeypatch, "oracle", 10)
    assert f.main() == 0


def test_standby_proceeds_when_other_stale(monkeypatch):
    _stub(monkeypatch, "oracle", 90)
    assert f.main() == 2


def test_standby_proceeds_when_same_host(monkeypatch):
    _stub(monkeypatch, "pc", 5)
    assert f.main() == 2


def test_primary_ignores_other(monkeypatch):
    _stub(monkeypatch, "oracle", 5)
    monkeypatch.setenv("TOSS_SNAPSHOT_ROLE", "primary")
    assert f.main() == 2
