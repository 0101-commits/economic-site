"""마스터 매일 스냅샷(scripts/master_snapshot.py) — 암호 형식 · 평가식 · 합치기 · 로그. 네트워크 없이(가짜 HTTP · 가짜 Yahoo)."""
import base64
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import master_snapshot as M  # noqa: E402

E2E = os.path.join(ROOT, "app", "src", "lib", "personal", "e2e.ts")
CALC = os.path.join(ROOT, "app", "src", "lib", "personal", "calc.ts")
PASS = "ab" * 32   # 보유 열쇠 hex 모양(64자)

# 암호 시험은 cryptography 가 있을 때만 돈다 — 알림 · 수집 워크플로의 시험 단계엔 이 모듈이 없다
# (작업 자체는 master-snapshot.yml 이 따로 설치한다). 없는 곳에서 실패하면 그 워크플로가 통째로 멈춘다.
try:
    import cryptography  # noqa: F401
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False
needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography 없음")


def _node(js, payload):
    """node 로 앱의 진짜 .ts 를 돌린다. node 가 없거나 못 돌리면 시험을 건너뛴다."""
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node 없음")
    r = subprocess.run([exe, "--input-type=module", "-e", js], input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", timeout=120)
    if r.returncode != 0:
        pytest.skip("node 가 앱 .ts 를 못 돌림: " + r.stderr[-200:])
    return json.loads(r.stdout)


# ── 형식 ────────────────────────────────────────────────────────
def test_constants_match_e2e_ts():
    src = open(E2E, encoding="utf-8").read()
    assert re.search(r"export const ITER = 600_000", src) and M.ITER == 600_000
    assert "'AES-256-GCM'" in src and "'PBKDF2-SHA256'" in src
    assert "salt: 'ecom-holdings-v1'" not in src and "getRandomValues(new Uint8Array(16))" in src and "new Uint8Array(12)" in src
    assert M.MAX_SNAPS == 730 and "slice(-730)" in open(CALC, encoding="utf-8").read()


@needs_crypto
def test_roundtrip_and_blob_shape():
    plain = {"v": 1, "at": "2026-10-27T00:00:00Z", "snaps": [{"d": "2026-10-26", "ev": 1, "ct": 1, "src": "close"}]}
    b = M.encrypt_blob(plain, PASS)
    assert set(b) == {"alg", "kdf", "iter", "salt", "iv", "ciphertext"} and b["iter"] == 600000
    assert len(base64.b64decode(b["salt"])) == 16 and len(base64.b64decode(b["iv"])) == 12
    assert M.decrypt_blob(b, PASS) == plain
    b2 = M.encrypt_blob(plain, PASS)
    assert b2["salt"] != b["salt"] and b2["iv"] != b["iv"], "올릴 때마다 salt · iv 가 새로여야 한다"
    with pytest.raises(M.DecryptError):
        M.decrypt_blob(b, "x" * 64)
    bad = dict(b, ciphertext=base64.b64encode(b"junk" * 10).decode())
    with pytest.raises(M.DecryptError):
        M.decrypt_blob(bad, PASS)


@needs_crypto
def test_trimmed_password_fallback():
    b = M.encrypt_blob([1], PASS)
    assert M.open_with_fallback(b, PASS + "\n") == [1]


@needs_crypto
def test_decrypts_blob_made_by_apps_e2e_ts():
    """앱 e2e.ts encrypt 가 만든 덩어리(보유 칸 + 바뀐 때 {t})를 파이썬이 풀어 칸을 읽는다."""
    js = f"""
import {{ encrypt }} from 'file:///{E2E.replace(os.sep, '/')}';
const inp = JSON.parse(await new Promise(r => {{ let s=''; process.stdin.on('data', d => s += d); process.stdin.on('end', () => r(s)); }}));
console.log(JSON.stringify(await encrypt(inp.entries, inp.pass, inp.at)));
"""
    entries = [{"s": "005930", "m": "KR", "a": 70000, "q": 10, "fx": None, "n": "삼성전자"}, {"s": "AAPL", "m": "US", "a": 150, "q": 2, "fx": 1300}]
    blob = _node(js, {"entries": entries, "pass": PASS, "at": "2026-10-27T01:02:03.000Z"})
    got = M.parse_holdings(M.decrypt_blob(blob, PASS))
    assert [(e["s"], e["m"], e["a"], e["q"], e["fx"]) for e in got] == [("005930", "KR", 70000, 10, None), ("AAPL", "US", 150, 2, 1300)]


@needs_crypto
def test_app_e2e_ts_decrypts_blob_made_here():
    js = f"""
import {{ decrypt }} from 'file:///{E2E.replace(os.sep, '/')}';
const inp = JSON.parse(await new Promise(r => {{ let s=''; process.stdin.on('data', d => s += d); process.stdin.on('end', () => r(s)); }}));
const d = await decrypt(inp.blob, inp.pass);
console.log(JSON.stringify(d));
"""
    blob = M.encrypt_blob([{"s": "000660", "m": "KR", "a": 100000, "q": 3, "fx": None}, {"t": "2026-10-27T00:00:00Z"}], PASS)
    d = _node(js, {"blob": blob, "pass": PASS})
    assert d["at"] == "2026-10-27T00:00:00Z" and d["entries"][0]["s"] == "000660" and d["entries"][0]["q"] == 3


# ── 평가식 패리티(calc.ts) ───────────────────────────────────────
SAMPLE = [
    {"s": "005930", "m": "KR", "a": 70000.0, "q": 10.0, "fx": None},   # 국내
    {"s": "AAPL", "m": "US", "a": 150.0, "q": 2.0, "fx": 1300.0},      # 해외 + 매입 환율
    {"s": "MSFT", "m": "US", "a": 10.0, "q": 1.0, "fx": None},         # 해외, 매입 환율 없음 → 지금 환율(calc.ts 66행)
    {"s": "035720", "m": "KR", "a": None, "q": 3.0, "fx": None},       # 평단가 없음 → 원금 없음 → ev · ct 에서 제외(78행)
    {"s": "000660", "m": "KR", "a": 90000.0, "q": None, "fx": None},   # 수량 없음 → 제외
    {"s": "NOPX", "m": "KR", "a": 5.0, "q": 4.0, "fx": None},          # 시세 없음 → 제외(68~71행)
]
PRICES = {"005930": 80000.0, "AAPL": 200.0, "MSFT": 20.0, "035720": 1000.0, "000660": 120000.0}
FX_NOW = 1400.0


def test_valuation_matches_hand_calculation_from_calc_ts():
    # calc.ts 72행 value = price·qty·fxNow · 67행 cost = avg·qty·costMul(66행) · 78행 basisValue/cost 는 둘 다 있는 종목만
    # 005930: 80000·10 = 800000 · 원금 70000·10 = 700000
    # AAPL:   200·2·1400 = 560000 · 원금 150·2·1300 = 390000
    # MSFT:   20·1·1400 = 28000 · 원금 10·1·1400 = 14000 (fxBuy 없음 → 지금 환율)
    # 035720: 원금 없음 → 빠짐 · 000660: 수량 없음 → 빠짐 · NOPX: 시세 없음 → 빠짐
    ev, ct, missing = M.evaluate(SAMPLE, lambda e: PRICES.get(e["s"]), FX_NOW)
    assert (ev, ct) == (800000 + 560000 + 28000, 700000 + 390000 + 14000) == (1388000, 1104000)
    assert missing == 1    # 시세 없는 NOPX(수량 있음) — 평단가 없는 칸은 시세가 있으니 세지 않는다
    s = M.snap_of("2026-10-26", SAMPLE, lambda e: PRICES.get(e["s"]), FX_NOW)
    assert s == {"d": "2026-10-26", "ev": 1388000, "ct": 1104000, "src": "close"}


def test_valuation_matches_calc_ts_run_in_node():
    """같은 입력을 앱 calc.ts evaluate 에 넣어 totals.basisValue · cost 가 파이썬 값과 같은지 본다."""
    js = f"""
import {{ evaluate }} from 'file:///{CALC.replace(os.sep, '/')}';
const inp = JSON.parse(await new Promise(r => {{ let s=''; process.stdin.on('data', d => s += d); process.stdin.on('end', () => r(s)); }}));
const hs = inp.entries.map((e, i) => ({{ id: 'h' + i, symbol: e.s, market: e.m, qty: e.q, avg: e.a, fxBuy: e.fx }}));
const qs = new Map(Object.entries(inp.prices).map(([k, v]) => [k, {{ price: v, pct: null }}]));
const {{ totals }} = evaluate(hs, qs, {{ now: inp.fx, prev: null }});
console.log(JSON.stringify({{ ev: totals.basisValue, ct: totals.cost, missing: totals.missing }}));
"""
    app = _node(js, {"entries": SAMPLE, "prices": PRICES, "fx": FX_NOW})
    ev, ct, missing = M.evaluate(SAMPLE, lambda e: PRICES.get(e["s"]), FX_NOW)
    assert (app["ev"], app["ct"], app["missing"]) == (ev, ct, missing)


def test_rounding_is_javascript_round_and_needs_positive_values():
    assert [M.js_round(x) for x in (0.5, 1.5, 2.5, 2.4, 100.49)] == [1, 2, 3, 2, 100]
    one = [{"s": "X", "m": "KR", "a": 100.0, "q": 1.0, "fx": None}]
    assert M.snap_of("2026-10-26", one, lambda e: 100.5, None)["ev"] == 101     # Math.round(100.5) = 101
    assert M.snap_of("2026-10-26", [{"s": "X", "m": "KR", "a": None, "q": 1.0, "fx": None}], lambda e: 5.0, None) is None
    assert M.snap_of("2026-10-26", one, lambda e: None, None) is None            # 시세 없음 → 저장 안 함(My.tsx 86행)
    us = [{"s": "A", "m": "US", "a": 1.0, "q": 1.0, "fx": None}]
    assert M.snap_of("2026-10-26", us, lambda e: 5.0, None) is None              # 환율 없음 → 해외는 뺀다


# ── 합치기 ────────────────────────────────────────────────────────
def test_merge_close_wins_over_app_and_sorts():
    existing = [{"d": "2026-10-23", "ev": 1, "ct": 1, "src": "app"}, {"d": "2026-10-22", "ev": 5, "ct": 5}, {"d": "bad", "ev": 1, "ct": 1}, {"d": "2026-10-21", "ev": "x", "ct": 1}]
    new = [{"d": "2026-10-23", "ev": 9, "ct": 8, "src": "close"}, {"d": "2026-10-26", "ev": 7, "ct": 6, "src": "close"}]
    got = M.merge_snaps(existing, new)
    assert got == [{"d": "2026-10-22", "ev": 5, "ct": 5}, {"d": "2026-10-23", "ev": 9, "ct": 8, "src": "close"}, {"d": "2026-10-26", "ev": 7, "ct": 6, "src": "close"}]


def test_merge_keeps_existing_close_when_not_recomputed_and_new_replaces_old_close():
    old = [{"d": "2026-10-20", "ev": 3, "ct": 3, "src": "close"}, {"d": "2026-10-21", "ev": 4, "ct": 4, "src": "close"}]
    got = M.merge_snaps(old, [{"d": "2026-10-21", "ev": 40, "ct": 40, "src": "close"}])
    assert got[0]["ev"] == 3 and got[1]["ev"] == 40
    dup = M.merge_snaps([{"d": "2026-10-20", "ev": 1, "ct": 1, "src": "app"}, {"d": "2026-10-20", "ev": 2, "ct": 2, "src": "close"}], [])
    assert dup == [{"d": "2026-10-20", "ev": 2, "ct": 2, "src": "close"}]


def test_merge_caps_at_730_newest():
    start = datetime.date(2020, 1, 1)
    existing = [{"d": (start + datetime.timedelta(days=i)).isoformat(), "ev": i + 1, "ct": 1} for i in range(800)]
    got = M.merge_snaps(existing, [{"d": "2030-01-01", "ev": 1, "ct": 1, "src": "close"}])
    assert len(got) == 730 and got[-1]["d"] == "2030-01-01" and got[0]["d"] == existing[71]["d"]
    assert [s["d"] for s in got] == sorted(s["d"] for s in got)


def test_target_days_missing_weekdays_and_yesterday():
    today = datetime.date(2026, 10, 27)   # 화
    assert M.last_weekdays(datetime.date(2026, 10, 26))[-1] == "2026-10-26" and len(M.last_weekdays(datetime.date(2026, 10, 26))) == 10
    assert all(datetime.date.fromisoformat(d).weekday() < 5 for d in M.last_weekdays(datetime.date(2026, 10, 26)))
    all_days = M.last_weekdays(today - datetime.timedelta(days=1))
    existing = [{"d": d, "ev": 1, "ct": 1, "src": "close"} for d in all_days]
    assert M.target_days(existing, today) == ["2026-10-26"]                        # 어제는 늘 다시
    assert M.target_days([], today) == all_days
    assert M.target_days([{"d": all_days[0], "ev": 1, "ct": 1, "src": "app"}], today) == all_days   # app 값은 종가로 덮을 대상
    assert M.kst_today(datetime.datetime(2026, 10, 26, 22, 10, tzinfo=datetime.timezone.utc)) == datetime.date(2026, 10, 27)


def test_parse_chart_uses_exchange_local_date():
    j = {"chart": {"result": [{"meta": {"gmtoffset": 32400}, "timestamp": [1792969200, 1793055600], "indicators": {"quote": [{"close": [100.5, None]}]}}]}}
    # 1792969200 = 2026-10-25T23:00:00Z → +9h = 10-26 08:00 현지
    assert M.parse_chart(j) == {"2026-10-26": 100.5}
    assert M.parse_chart({"chart": {"result": None}}) == {}


# ── 전체 실행(가짜 HTTP · 가짜 Yahoo) · 로그 ──────────────────────
HOLD_PLAIN = [
    {"s": "005930", "m": "KR", "a": 70000, "q": 12345, "fx": None, "n": "비밀이름전자"},
    {"s": "AAPL", "m": "US", "a": 150, "q": 77, "fx": 1300},
    {"t": "2026-10-27T00:00:00Z"},
]
ENV = {"MASTER_HOLD_KEY": PASS, "PUSH_READ_KEY": "rk", "PUSH_WRITE_KEY": "wk"}
NOW = datetime.datetime(2026, 10, 26, 22, 10, tzinfo=datetime.timezone.utc)   # 화 07:10 KST


def _bars(price):
    days = M.last_weekdays(datetime.date(2026, 10, 26))
    return {d: price + i for i, d in enumerate(days)}


def _fake_fetch(sym):
    if sym == "KRW=X":
        return _bars(1400.0)
    if sym in ("005930.KS", "AAPL"):
        return _bars(80000.0 if sym.endswith(".KS") else 200.0)
    return {}


@pytest.fixture
def fake_net(monkeypatch):
    if not _HAS_CRYPTO:                 # 이 묶음을 쓰는 시험은 전부 암호 덩어리를 만든다
        pytest.skip("cryptography 없음")
    state = {"puts": [], "snaps": None, "hold": M.encrypt_blob(HOLD_PLAIN, PASS)}

    def get(url, headers=None, timeout=20):
        assert headers.get("X-Push-Read-Key") == "rk"
        if url.endswith("/hold/owner"):
            return {"ok": True, "encHoldings": state["hold"]}
        if url.endswith("/snaps/owner"):
            return {"ok": True, "encSnaps": state["snaps"]}
        raise AssertionError(url)

    def put(url, headers, body, timeout=30):
        assert url.endswith("/snaps/owner") and headers.get("X-Push-Write-Key") == "wk"
        state["puts"].append(body)
        state["snaps"] = body["encSnaps"]
        return 200

    monkeypatch.setattr(M, "http_get_json", get)
    monkeypatch.setattr(M, "http_put_json", put)
    return state


def test_run_end_to_end_logs_no_amounts(fake_net, capsys):
    assert M.run(env=ENV, now=NOW, fetch=_fake_fetch) == 0
    out = capsys.readouterr().out
    assert len(fake_net["puts"]) == 1
    plain = M.decrypt_blob(fake_net["puts"][0]["encSnaps"], PASS)
    assert plain["v"] == 1 and re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", plain["at"])
    snaps = plain["snaps"]
    assert len(snaps) == 10 and all(s["src"] == "close" for s in snaps) and snaps[-1]["d"] == "2026-10-26"
    last = snaps[-1]    # 그 날: KR 80009·12345 · US 200+9 = 209 · 환율 1409
    assert last["ev"] == M.js_round(80009 * 12345 + 209 * 77 * 1409) and last["ct"] == M.js_round(70000 * 12345 + 150 * 77 * 1300)
    # 로그: 개수 · 날짜만 — 금액 · 종목 · 수량 · 이름이 새지 않는다
    for secret in ("005930", "AAPL", "12345", "77", "비밀이름", str(last["ev"]), str(last["ct"]), "80009", "1409", PASS):
        assert secret not in out, secret
    assert "완료" in out and "10일" in out


def test_run_merges_with_existing_server_snaps_and_skips_when_unchanged(fake_net, capsys):
    app_snap = {"d": "2026-10-26", "ev": 1, "ct": 1, "src": "app"}
    older = {"d": "2026-01-02", "ev": 5, "ct": 4}
    fake_net["snaps"] = M.encrypt_blob({"v": 1, "at": "2026-10-26T00:00:00Z", "snaps": [older, app_snap]}, PASS)
    assert M.run(env=ENV, now=NOW, fetch=_fake_fetch) == 0
    snaps = M.decrypt_blob(fake_net["puts"][0]["encSnaps"], PASS)["snaps"]
    assert snaps[0] == older and snaps[-1]["src"] == "close" and snaps[-1]["ev"] != 1 and len({s["d"] for s in snaps}) == len(snaps)
    n = len(fake_net["puts"])
    assert M.run(env=ENV, now=NOW, fetch=_fake_fetch) == 0
    assert len(fake_net["puts"]) == n and "변경 없음" in capsys.readouterr().out


def test_run_exit_codes(fake_net, capsys):
    assert M.run(env={}, now=NOW, fetch=_fake_fetch) == 0
    assert "건너뜀" in capsys.readouterr().out
    fake_net["hold"] = None
    assert M.run(env=ENV, now=NOW, fetch=_fake_fetch) == 0
    fake_net["hold"] = M.encrypt_blob([{"t": "x"}], PASS)
    assert M.run(env=ENV, now=NOW, fetch=_fake_fetch) == 0           # 종목 없음
    fake_net["hold"] = M.encrypt_blob(HOLD_PLAIN, "z" * 64)
    assert M.run(env=ENV, now=NOW, fetch=_fake_fetch) == 1           # 열쇠 틀림 → 실패
    assert "실패" in capsys.readouterr().out
    fake_net["hold"] = M.encrypt_blob(HOLD_PLAIN, PASS)
    fake_net["snaps"] = M.encrypt_blob({"v": 1, "snaps": []}, "z" * 64)
    assert M.run(env=ENV, now=NOW, fetch=_fake_fetch) == 1           # 서버 스냅샷 안 풀림 → 실패
    fake_net["snaps"] = None
    assert M.run(env=ENV, now=NOW, fetch=lambda s: {}) == 0          # 시세 없음 → 조용히 건너뜀
    assert fake_net["puts"] == []


def test_run_refuses_raw_app_key_without_network_or_echo(capsys):
    """앱키 원문을 MASTER_HOLD_KEY 에 넣으면 네트워크 전에 멈추고, 그 값을 로그에 찍지 않는다."""
    for raw in ("ECOM-ABCD-EFGH-JKMN", "my-old-sync-key-123", "AB" * 32):
        env = dict(ENV, MASTER_HOLD_KEY=raw)
        assert M.run(env=env, now=NOW, fetch=lambda s: (_ for _ in ()).throw(AssertionError("시세 조회 금지"))) == 1
        out = capsys.readouterr().out
        assert "보유 열쇠 모양" in out and raw not in out


def test_run_put_failure_is_exit_1_without_leaking(monkeypatch, fake_net, capsys):
    def boom(url, headers, body, timeout=30):
        raise RuntimeError("https://x/?s=005930 amount 999")
    monkeypatch.setattr(M, "http_put_json", boom)
    assert M.run(env=ENV, now=NOW, fetch=_fake_fetch) == 1
    out = capsys.readouterr().out
    assert "RuntimeError" in out and "005930" not in out and "999" not in out


def test_workflow_file_shape():
    y = open(os.path.join(ROOT, ".github", "workflows", "master-snapshot.yml"), encoding="utf-8").read()
    assert "cron: '10 22 * * 1-5'" in y and "workflow_dispatch" in y and "timeout-minutes: 10" in y
    assert "python-version: '3.11'" in y and "pip install cryptography requests" in y
    for k in ("MASTER_HOLD_KEY", "PUSH_READ_KEY", "PUSH_WRITE_KEY"):
        assert f"{k}: ${{{{ secrets.{k} }}}}" in y
    assert "git commit" not in y and "git push" not in y and "contents: read" in y


def test_compute_days_skips_day_without_fx_or_price():
    es = [{"s": "K", "m": "KR", "a": 100.0, "q": 1.0, "fx": None}, {"s": "U", "m": "US", "a": 1.0, "q": 1.0, "fx": None}]
    series = {("KR", "K"): {"2026-10-20": 100.0, "2026-10-21": 100.0}, ("US", "U"): {"2026-10-20": 5.0, "2026-10-21": 5.0}}
    fx = {"2026-10-21": 1400.0}   # 10-20 에는 이 날 이전 환율 봉이 없다
    got = M.compute_days(es, ["2026-10-20", "2026-10-21"], series, fx)
    assert [s["d"] for s in got] == ["2026-10-21"]
    series[("US", "U")] = {"2026-10-21": 5.0}   # 10-20 에는 US 시세 봉이 없다(이전도 없음)
    fx = {"2026-10-19": 1400.0, "2026-10-21": 1400.0}
    assert [s["d"] for s in M.compute_days(es, ["2026-10-20", "2026-10-21"], series, fx)] == ["2026-10-21"]


def test_run_logs_distinct_reason_when_symbol_unpriced(fake_net, capsys):
    f = lambda sym: {} if sym == "AAPL" else _fake_fetch(sym)
    assert M.run(env=ENV, now=NOW, fetch=f) == 0
    out = capsys.readouterr().out
    assert "시세를 못 받은 종목 1개" in out and "AAPL" not in out and fake_net["puts"] == []


def test_run_no_write_when_server_blob_out_of_order(fake_net):
    assert M.run(env=ENV, now=NOW, fetch=_fake_fetch) == 0
    snaps = M.decrypt_blob(fake_net["puts"][0]["encSnaps"], PASS)["snaps"]
    fake_net["snaps"] = M.encrypt_blob({"v": 1, "at": "x", "snaps": list(reversed(snaps))}, PASS)
    assert M.run(env=ENV, now=NOW, fetch=_fake_fetch) == 0
    assert len(fake_net["puts"]) == 1
