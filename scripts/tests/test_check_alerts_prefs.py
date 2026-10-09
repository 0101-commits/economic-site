#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""새 화면(/prefs) 조건 — python -m pytest scripts/tests/test_check_alerts_prefs.py -q

① 변환 6종(price·pct·high52·event·flow·lens)과 매핑 불가 건너뛰기
② 반복 규칙 — once(price·pct·high52·lens 는 끝, event 는 일정마다, flow 는 전환마다 + 같은 방향 24시간),
   daily 하루 한 번·같은 발생 재발송 없음, 발송 실패는 기록하지 않음(렌즈 기준선 포함),
   다시 켜기(cond.armedAt — 미래 시각은 기다림·같은 발생은 다시 안 보냄·새 발생에 한 번·공개 기록에 안 남음),
   발생 키 해시는 ALERTS_STATE_SALT HMAC(공개 일정표로 되짚히지 않음·동기화 키와 무관), 소금이 없으면 평가를 통째로 건너뜀
③ /prefs 를 못 받거나 빈 문서(updatedAt 없음)면 상태를 건드리지 않음 · 채널 없는 조건은 평가 안 함
④ 푸시 — 큐 적재 모양, send_push 가 실제로 보낸 것만 --confirm-push 가 확정
⑤ 동기화 키·해시가 로그에 안 찍히고, 리다이렉트를 따라가지 않음 · 공개 로그에 조건 내용(이름·값)이 없음
⑥ main — 현행 뒤에 새 화면 조건 · 전역 OFF·테스트 런이면 안 돎 · 설정 파일이 없어도 돎 · snaps 에 None 안 남김

테스트마다 가짜 체크아웃(tmp_path)을 새로 만들고, 모듈·환경 변수 덮어쓰기는 monkeypatch 로만 한다 —
옛 스크립트형은 import 때 전역을 덮어써 같은 세션의 다른 테스트에 새어 나갔다.
"""
import contextlib
import copy
import datetime
import hashlib
import http.server
import io
import json
import os
import sys
import threading
import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import check_alerts as ca       # noqa: E402
import notify_discord           # noqa: E402
import prefs_client             # noqa: E402

SALT = "test-salt"
KST = datetime.timezone(datetime.timedelta(hours=9))
T = lambda d, h, m=0, mo=10: datetime.datetime(2026, mo, d, h, m, tzinfo=KST)   # 10/1 목 · 10/2 금

SNAP = {"price": 91000.0, "pct": 1.0, "highs": [80000.0] * 100 + [91500.0], "lows": [70000.0] * 101,
        "closes": [80000.0] * 101, "fresh": True}


def A(**kw):
    a = {"id": "x", "target": "kospi", "type": "price", "cond": {}, "repeat": "once",
         "channels": ["discord"], "enabled": True}
    a.update(kw)
    return a


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def P(st, aid):
    return st.get("_prefs", {}).get(aid, {})


class Env:
    """한 테스트의 가짜 체크아웃 + 가짜 발송·시세·/prefs. 덮어쓴 것은 monkeypatch 가 테스트 끝에 되돌린다."""

    def __init__(self, monkeypatch, tmp_path):
        self.mp = monkeypatch
        self.tmp = str(tmp_path)
        os.makedirs(os.path.join(self.tmp, "bundles"))
        monkeypatch.delenv("ALERTS_TEST", raising=False)
        monkeypatch.setenv("ALERTS_STATE_SALT", SALT)    # 공개 기록 발생 키의 HMAC 비밀 — 없으면 _check_prefs 가 돌지 않는다
        monkeypatch.setattr(ca, "IS_TEST", False)
        monkeypatch.setattr(ca, "ROOT", self.tmp)
        monkeypatch.setattr(ca, "STATE_PATH", os.path.join(self.tmp, "alerts_state.json"))
        monkeypatch.setattr(ca, "PUSH_QUEUE_PATH", os.path.join(self.tmp, "push_queue.json"))
        monkeypatch.setattr(ca, "PUSH_SENT_PATH", os.path.join(self.tmp, "push_sent.json"))
        monkeypatch.setattr(ca, "CONFIG_PATH", os.path.join(self.tmp, "alerts_config.json"))

        self.put("bundles/registry.json", {"rows": [
            {"id": "kospi", "label": "KOSPI", "short": "KOSPI", "decimals": 2, "country": "kr",
             "seriesPath": "history.indices.KOSPI"},
            {"id": "cpi_us", "label": "소비자물가지수 (CPI)", "short": "미국 소비자물가지수", "shortM": "미국 CPI",
             "decimals": 1, "country": "us"},
            {"id": "sp500", "label": "S&P 500", "short": "S&P 500", "decimals": 2, "country": "us"},
        ]})
        self.HOME = {"strip": [{"id": "kospi", "value": 3000.0, "changePct": 2.5, "asOf": "2026-10-01"},
                               {"id": "cpi_us", "value": 320.1, "changePct": 0.1, "asOf": "2026-09-15"},
                               {"id": "sp500", "value": 7000.0, "changePct": -0.3, "asOf": "2026-09-30"}]}
        self.put("bundles/home.json", self.HOME)
        hist = [{"date": (datetime.date(2026, 6, 1) + datetime.timedelta(days=i)).isoformat(), "close": 2000.0 + i * 10}
                for i in range(100)]                                  # 2000 … 2990 — 3000 이면 52주 최고
        self.DATA = {
            "history": {"indices": {"KOSPI": hist}},
            "economicCalendar": {"events": [
                {"dt": "10.02 08:00", "cc": "KR", "name": "한국 CPI 발표", "iso": "2026-10-02"},
                {"dt": "10.02 21:30", "cc": "US", "name": "미국 CPI (전월비)", "iso": "2026-10-02"},
                {"dt": "11.10 21:30", "cc": "US", "name": "미국 CPI (전월비)", "iso": "2026-11-10"},
            ]},
            "investorTrading": {"unit": "억원", "daily": [
                {"date": "2026-09-29", "foreign": -50.0, "inst": 10.0},
                {"date": "2026-09-30", "foreign": -100.0, "inst": 20.0},
                {"date": "2026-10-01", "foreign": 200.0, "inst": 30.0}]},
            "stockFlows": {"items": {"005930": {"name": "삼성전자", "investor": []}}},
        }
        self.put("data.json", self.DATA)
        self.MER = {"indicators": [
            {"id": "us10y", "label": "미국채 10년물", "unit": "%", "state": "below",
             "current": {"value": 5.0, "asOf": "2026-09-29"}, "nearest": {"level": 5.1}},
            {"id": "us_equity", "label": "미국 증시", "state": "below", "current": {"value": 1, "asOf": "2026-09-29"}},
        ]}
        self.put("mer_signals.json", self.MER)
        monkeypatch.setattr(ca._PrefsCtx, "rows",
                            lambda self_: {"sp500": {"merLens": "us_equity"}})   # 레지스트리 원본 대신(별칭 매핑만 본다)

        self.snap_calls = []
        monkeypatch.setattr(ca, "get_snapshot", self._fake_snapshot)

        self.sent = []                  # 디스코드로 나간 (본문, 인자)
        self.discord_ok = [True]
        monkeypatch.setattr(notify_discord, "send",
                            lambda text, **kw: self.sent.append((text, kw)) or self.discord_ok[0])
        self.DOC = {"v": 1, "updatedAt": "2026-10-01T00:00:00.000Z", "alerts": []}
        monkeypatch.setattr(prefs_client, "fetch", lambda base: copy.deepcopy(self.DOC))

    def _fake_snapshot(self, market, sym, yahoo):
        self.snap_calls.append(sym)
        return None if sym == "000000" else dict(SNAP)

    def put(self, rel, obj):
        with open(os.path.join(self.tmp, rel), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def ev(self, a, now, rec=None, cfg=None):
        return ca._prefs_eval(a, ca._PrefsCtx(now, {}, cfg), {} if rec is None else rec)

    def run(self, now, deliver=True):
        """한 런: 판정·발송 → (푸시가 간 것으로 치면) send_push 의 보낸 목록 → --confirm-push. → (바뀜, 상태, 로그)."""
        st = load(ca.STATE_PATH) if os.path.exists(ca.STATE_PATH) else {}
        o = io.StringIO()
        with contextlib.redirect_stdout(o):
            ch = ca._check_prefs(st, now, {}, None)
            if ch:
                ca._save_state(st)
            q = load(ca.PUSH_QUEUE_PATH) if os.path.exists(ca.PUSH_QUEUE_PATH) else []
            if q:
                if deliver:
                    with open(ca.PUSH_SENT_PATH, "w", encoding="utf-8") as fh:
                        json.dump([x["id"] for x in q], fh)
                os.remove(ca.PUSH_QUEUE_PATH)                     # send_push 는 보내든 말든 큐를 비운다
                ca.confirm_push()
        return ch, (load(ca.STATE_PATH) if os.path.exists(ca.STATE_PATH) else {}), o.getvalue()


@pytest.fixture
def env(monkeypatch, tmp_path):
    return Env(monkeypatch, tmp_path)


# ── ① 변환 6종 ────────────────────────────────────────────────────────────
def test_convert_price(env):
    ev, now = env.ev, T(1, 10)
    h = ev(A(cond={"op": ">=", "value": 2900}), now)
    assert h and h[0] == "KOSPI 2,900.00 이상 도달" and h[2] == "#/i/kospi" and h[3] == "2026-10-01", h
    assert ev(A(cond={"op": "<=", "value": 2900}), now) is None
    h = ev(A(target="005930", cond={"op": ">=", "value": 90000}), now)          # 국내 종목: 장중·원 표기
    assert h and h[0] == "삼성전자 90,000원 이상 도달" and h[2] == "#/market?a=kr&m=all", h
    assert ev(A(target="005930", cond={"op": ">=", "value": 90000}), T(1, 16)) is None   # 장 밖


def test_convert_pct(env):
    ev, now = env.ev, T(1, 10)
    assert ev(A(type="pct", cond={"op": ">=", "value": 2}), now)[0] == "KOSPI 하루 +2% 도달"
    assert ev(A(type="pct", cond={"pct": 2}), now)                              # 옛 모양 cond.pct
    assert ev(A(type="pct", cond={"op": "<=", "value": -2}), now) is None


def test_convert_high52(env):
    ev, now = env.ev, T(1, 10)
    assert ev(A(type="high52", cond={"side": "high"}), now)[0] == "KOSPI 52주 최고 돌파"
    assert ev(A(type="high52", cond={"side": "low"}), now) is None
    assert ev(A(type="high52", target="005930", cond={"side": "high"}), now)[0] == "삼성전자 52주 최고 돌파"
    assert ev(A(type="high52", target="sp500", cond={"side": "high"}), now) is None   # 시계열 없음 → 판정 보류


def test_convert_event(env):
    ev = env.ev
    # event — N일 전 21:00 이후·발표 전, 나라가 같은 일정만
    e = A(type="event", target="cpi_us", cond={"daysBefore": 1})
    h = ev(e, T(1, 22, 10))
    assert h and h[0] == "내일 21:30 미국 CPI (전월비)" and h[3] == "2026-10-02 미국 CPI (전월비)", h
    assert ev(e, T(1, 20)) is None                                # 21:00 전
    assert ev(e, T(2, 21, 31)) is None                            # 발표 뒤
    assert ev(e, T(2, 9))[0].startswith("오늘 21:30")
    assert ev(A(type="event", target="cpi_us", cond={"daysBefore": 0}), T(2, 9))[0].startswith("오늘 21:30")   # 0 = 당일
    assert ev(A(type="event", target="cpi_us", cond={"daysBefore": 0}), T(1, 22, 10)) is None
    assert ev(e, T(1, 22, 10), rec={"keys": [ca._kh("2026-10-02 미국 CPI (전월비)")]}) is None   # 같은 일정 두 번 안 보냄


def test_convert_flow(env):
    ev = env.ev
    # flow — 18시 KRX 확정 전엔 오늘 행을 안 본다
    f = A(type="flow", cond={"who": "foreign"})
    assert ev(f, T(1, 10)) is None                                # 10/1 행은 장중 잠정치
    h = ev(f, T(1, 19))
    assert h and h[0] == "KOSPI 외국인 순매수 전환" and h[1] == "2026-10-01 +200억원 (직전 -100억원)", h
    assert h[3] == "2026-10-01" and h[4] == {"flowDir": "buy"}
    assert ev(f, T(2, 10))                                        # 다음 날 장중이면 10/1 은 확정 행
    assert ev(A(type="flow", cond={"who": "inst"}), T(1, 19)) is None
    assert ev(A(type="flow", cond={"who": "inst", "days": 3}), T(1, 19)) is None   # 3일째지만 그 전날이 없다
    assert ev(f, T(20, 10)) is None                               # 낡은 자료(7일 초과)
    assert ev(A(type="flow", target="sp500", cond={"who": "foreign"}), T(1, 19)) is None   # 수급 없는 대상


def test_convert_lens(env):
    ev, now = env.ev, T(1, 10)
    # lens — 첫 관측은 기준선, 바뀔 때만. 울릴 때의 새 상태는 다섯째 값(발송 확정 뒤에 기록)
    lz = A(type="lens", target="us10y", cond={"state": "crossed"})
    rec = {}
    assert ev(lz, now, rec) is None and rec["lensState"] == "below"
    env.MER["indicators"][0]["state"] = "crossed"
    env.put("mer_signals.json", env.MER)
    h = ev(lz, now, rec)
    assert h and h[0] == "렌즈 돌파 · 미국채 10년물" and h[1] == "지금 5.0% · 기준 5.1%" and h[2] == "#/lens?s=us10y", h
    assert rec["lensState"] == "below" and h[4] == {"lensState": "crossed"}     # 울릴 땐 기준선을 미리 안 바꾼다
    rec.update(h[4])
    assert ev(lz, now, rec) is None                               # 확정 뒤 — 계속 돌파 중
    rec = {"lensState": "near"}
    env.MER["indicators"][1]["state"] = "crossed"
    env.put("mer_signals.json", env.MER)
    assert ev(A(type="lens", target="sp500", cond={"state": "crossed"}), now, rec)[0] == "렌즈 돌파 · 미국 증시"   # merLens


def test_unmappable_conditions_are_skipped_with_a_log_line(env):
    ev, now = env.ev, T(1, 10)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert ev(A(target="nope"), now) is None
        assert ev(A(type="zzz"), now) is None
        assert ev(A(cond={"op": "!=", "value": 1}), now) is None
    assert out.getvalue().count("[prefs] 건너뜀") == 3, out.getvalue()


# ── ② 반복 규칙 ───────────────────────────────────────────────────────────
def test_once_and_daily_rules_and_public_log(env):
    run, sent = env.run, env.sent
    env.DOC["alerts"] = [
        A(id="p1", cond={"op": ">=", "value": 2900}, repeat="once", channels=["discord"]),
        A(id="p2", type="pct", cond={"op": ">=", "value": 2}, repeat="daily", channels=["push"]),
        A(id="p3", type="pct", cond={"op": ">=", "value": 2}, repeat="daily", channels=["discord"], enabled=False),
    ]
    ch, st, log = run(T(1, 10))
    assert ch and set(st["_prefs"]) == {"p1", "p2"}, st                # 꺼 둔 p3 은 평가도 기록도 없음
    p1, p2 = P(st, "p1"), P(st, "p2")
    assert p1["fired"] is True and p1["date"] == "20261001" and p1["hist"] == ["20261001"] and p1["source"] == "prefs"
    assert p1["type"] == "price" and isinstance(p1["ts"], int) and "target" not in p1 and "title" not in p1
    assert "fired" not in p2 and p2["date"] == "20261001" and "pend" not in p2   # 푸시는 보낸 목록으로 확정됨
    assert len(sent) == 1 and sent[0][0].startswith("KOSPI 2,900.00 이상 도달") and sent[0][1]["env"] == "DISCORD_WEBHOOK_ALERTS"
    for secret in ("KOSPI", "2,900", "3,000", "kospi"):                 # 공개 Actions 로그에 조건 내용이 없다
        assert secret not in log, (secret, log)
    assert "조건 충족 p1(price)" in log
    ch, st2, _ = run(T(1, 10, 5))
    assert not ch and st2 == st and len(sent) == 1                      # 같은 날: once 끝, daily 오늘 이미
    ch, st, _ = run(T(2, 10))
    assert not ch                                                       # 다음 날이어도 같은 발생(asOf 10/1)
    env.HOME["strip"][0]["asOf"] = "2026-10-02"
    env.put("bundles/home.json", env.HOME)
    ch, st, _ = run(T(2, 10))
    assert ch and P(st, "p2")["hist"] == ["20261001", "20261002"] and P(st, "p1")["hist"] == ["20261001"]


def test_push_not_delivered_is_requeued_not_confirmed(env):
    # 푸시가 안 갔으면(조용한 시간·구독 0대) 확정하지 않고 다음 런에 다시 쌓는다
    env.HOME["strip"][0]["asOf"] = "2026-10-02"
    env.put("bundles/home.json", env.HOME)
    env.DOC["alerts"] = [A(id="q1", cond={"op": ">=", "value": 2900}, channels=["push"])]
    ch, st, log = env.run(T(2, 10, 1), deliver=False)
    assert "q1" not in st.get("_prefs", {}) and "미발송 대기 해제 1건" in log
    ch, st, log = env.run(T(2, 10, 2))
    assert P(st, "q1")["fired"] is True and "푸시 확정 1건" in log


def test_discord_failure_is_not_recorded_and_lens_baseline_stays(env):
    # 디스코드 실패 → 기록 안 함 → 다음 런 재시도. 렌즈 기준선도 그대로라 다음 런에 다시 울린다.
    run = env.run
    env.HOME["strip"][0]["asOf"] = "2026-10-02"
    env.put("bundles/home.json", env.HOME)
    env.MER["indicators"][0]["state"] = "below"
    env.put("mer_signals.json", env.MER)
    env.DOC["alerts"] = [A(id="l1", type="lens", target="us10y", cond={"state": "crossed"})]
    run(T(2, 11))
    assert P(load(ca.STATE_PATH), "l1") == {"lensState": "below"}       # 첫 관측 = 기준선
    env.MER["indicators"][0]["state"] = "crossed"
    env.put("mer_signals.json", env.MER)
    env.discord_ok[0] = False
    ch, st, log = run(T(2, 11, 1))
    assert P(st, "l1") == {"lensState": "below"} and "다음 런 재시도" in log
    env.discord_ok[0] = True
    ch, st, _ = run(T(2, 11, 2))
    assert P(st, "l1")["fired"] is True and P(st, "l1")["lensState"] == "crossed"


def test_rearm_opens_the_once_gate_only_for_a_new_occurrence(env):
    # 다시 켜기 — 화면(alertStatus.ts rearm)이 cond.armedAt 을 마지막 발동 뒤로 찍으면 끝난 once 를 다시 본다(같은 id·이력 유지).
    #   fired 관문만 연다 — 같은 발생(같은 asOf)은 다시 안 보내고, 새 발생에서 한 번 울린 뒤 다시 끝난다.
    run, sent = env.run, env.sent
    env.HOME["strip"][0]["asOf"] = "2026-10-02"
    env.put("bundles/home.json", env.HOME)
    env.DOC["alerts"] = [A(id="r1", cond={"op": ">=", "value": 2900})]
    ch, st, _ = run(T(2, 13))
    assert ch and P(st, "r1")["fired"] is True and P(st, "r1")["hist"] == ["20261002"]
    n = len(sent)
    assert run(T(2, 13, 5))[0] is False and len(sent) == n                    # 끝난 once — 보지 않는다
    iso = lambda t: t.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    env.DOC["alerts"][0]["cond"]["armedAt"] = iso(T(2, 14))                   # 아직 안 온 시각(시계가 앞선 기기) — 기다린다
    assert run(T(2, 13, 10))[0] is False and len(sent) == n
    assert run(T(2, 14, 1))[0] is False and len(sent) == n                    # 다시 켰어도 같은 발생(10/2 asOf)은 안 보낸다
    env.DOC["alerts"][0]["cond"]["armedAt"] = iso(T(3, 12))                   # 토요일에 다시 켬 → 21:05 런은 금요일 값뿐
    assert run(T(3, 21, 5))[0] is False and len(sent) == n
    env.HOME["strip"][0]["asOf"] = "2026-10-05"
    env.put("bundles/home.json", env.HOME)
    ch, st, _ = run(T(5, 10))                                                 # 새 발생(월요일 값) — 한 번 울린다
    assert ch and len(sent) == n + 1 and P(st, "r1")["hist"] == ["20261002", "20261005"], P(st, "r1")
    assert "armedAt" not in json.dumps(st) and "2900" not in json.dumps(st)  # 공개 기록엔 armedAt·조건 값이 없다
    assert run(T(5, 10, 5))[0] is False and len(sent) == n + 1                # 다시 울린 뒤엔 다시 끝(되풀이 없음)
    env.DOC["alerts"][0]["cond"]["armedAt"] = "not-a-date"                    # 읽을 수 없는 시각은 관문을 열지 않는다
    env.HOME["strip"][0]["asOf"] = "2026-10-06"
    env.put("bundles/home.json", env.HOME)
    assert run(T(6, 10))[0] is False and len(sent) == n + 1


def test_occurrence_key_hash_is_salted_and_independent_of_sync_key(env, monkeypatch):
    # 발생 키 해시 — 소금 없는 SHA-256 이면 공개 일정표(이름·날짜)를 넣어 보는 것만으로 어떤 일정 조건인지 드러난다.
    #   비밀은 ALERTS_STATE_SALT 하나이고 동기화 키와 무관하다(공개 해시가 동기화 키 대입 창구가 되지 않게).
    ek = "2026-10-02 미국 CPI (전월비)"
    monkeypatch.setenv("ALERTS_STATE_SALT", "s1")
    h1 = ca._kh(ek)
    assert h1 != hashlib.sha256(ek.encode("utf-8")).hexdigest()[:12] and len(h1) == 12
    monkeypatch.setenv("ALERTS_STATE_SALT", "s2")
    assert ca._kh(ek) != h1


def test_missing_salt_skips_prefs_evaluation_without_plain_hash(env, monkeypatch):
    # 소금이 없으면 평문 해시로 되돌아가지 않고 /prefs 평가를 통째로 건너뛴다 — 받으러 가지도 않고 예외도 없다
    ek = "2026-10-02 미국 CPI (전월비)"
    env.DOC["alerts"] = [A(id="s0", cond={"op": ">=", "value": 2900})]
    env.run(T(1, 10))                                             # 소금이 있을 때 한 번 돌려 기록이 있는 상태를 만든다
    assert os.path.exists(ca.STATE_PATH)
    monkeypatch.delenv("ALERTS_STATE_SALT")
    fetched = []
    monkeypatch.setattr(prefs_client, "fetch", lambda base: fetched.append(1) or copy.deepcopy(env.DOC))
    before = load(ca.STATE_PATH)
    ch, st, log = env.run(T(6, 11))
    assert ch is False and fetched == [] and st == before and "ALERTS_STATE_SALT 없음 — /prefs 조건 평가 건너뜀" in log, log
    with pytest.raises(RuntimeError):
        ca._kh(ek)                                                # 소금 없이 해시하면 예외 — 평문으로 조용히 되돌아가지 않는다


def test_event_once_fires_once_per_schedule_not_forever(env):
    # event once = 일정마다 한 번(같은 이름의 다음 발표에는 다시 울림), 영구 종료 아님
    run = env.run
    env.DOC["alerts"] = [A(id="e1", type="event", target="cpi_us", cond={"daysBefore": 1})]
    ch, st, _ = run(T(1, 22, 10))
    assert ch and "fired" not in P(st, "e1") and len(P(st, "e1")["keys"]) == 1
    assert run(T(2, 9))[0] is False                                     # 같은 일정은 다음 날 아침에도 안 보냄
    ch, st, _ = run(T(9, 22, 0, mo=11))
    assert ch and P(st, "e1")["hist"] == ["20261001", "20261109"], P(st, "e1")


def test_flow_once_fires_per_transition_with_24h_same_direction_cooldown(env):
    # flow once = 전환마다 한 번 + 같은 방향은 24시간 쿨다운
    run = env.run
    env.DOC["alerts"] = [A(id="f1", type="flow", cond={"who": "foreign"})]
    ch, st, _ = run(T(1, 19))
    r = P(st, "f1")
    assert "fired" not in r and r["flowDir"] == "buy" and r["flowTs"] == int(T(1, 19).timestamp())
    assert run(T(2, 10))[0] is False                                    # 같은 전환(10/1 행) 다시 안 보냄
    env.DATA["investorTrading"]["daily"].append({"date": "2026-10-02", "foreign": -10.0})
    env.put("data.json", env.DATA)
    ch, st, _ = run(T(2, 19))
    assert ch and P(st, "f1")["flowDir"] == "sell"                      # 반대 방향은 24시간 안이어도 바로
    env.DATA["investorTrading"]["daily"].append({"date": "2026-10-05", "foreign": 30.0})
    env.put("data.json", env.DATA)
    rec = {"flowDir": "buy", "flowTs": int(T(5, 9).timestamp())}
    assert env.ev(A(type="flow", cond={"who": "foreign"}), T(5, 19), rec) is None          # 같은 방향 24시간 안
    rec["flowTs"] = int(T(4, 18).timestamp())
    assert env.ev(A(type="flow", cond={"who": "foreign"}), T(5, 19), rec)[4] == {"flowDir": "buy"}   # 24시간 지남


# ── ③ 못 받음 · 빈 문서 · 채널 없음 ───────────────────────────────────────
def test_prefs_not_received_empty_doc_and_no_channel_leave_state_alone(env, monkeypatch):
    env.DOC["alerts"] = [A(id="s0", cond={"op": ">=", "value": 2900})]
    env.run(T(1, 10))                                             # 기록이 있는 상태를 만든다
    before = load(ca.STATE_PATH)
    monkeypatch.setattr(prefs_client, "fetch", lambda base: None)
    assert env.run(T(2, 12))[0] is False and load(ca.STATE_PATH) == before
    monkeypatch.setattr(prefs_client, "fetch", lambda base: {"v": 1, "updatedAt": None, "alerts": []})   # 키 바꾼 직후의 빈 칸
    ch, st, log = env.run(T(2, 12))
    assert ch is False and st == before and "빈 문서" in log
    monkeypatch.setattr(prefs_client, "fetch", lambda base: copy.deepcopy(env.DOC))
    env.DOC["alerts"] = [A(id="m0", cond={"op": ">=", "value": 1}, channels=[]),
                         A(id="m9", cond={"op": ">=", "value": 1}, channels=[])]
    ch, st, log = env.run(T(2, 12, 1))
    assert "m0" not in st.get("_prefs", {}) and log.count("받을 채널이 없는 조건 2개") == 1 and "조건 충족" not in log


# ── ④ 큐 적재 모양 ─────────────────────────────────────────────────────────
def test_push_queue_shape(env):
    assert ca._enqueue_push([{"id": "a", "title": "t", "body": "b", "url": "#/i/kospi", "ts": 1}])
    assert ca._enqueue_push([{"id": "b", "title": "t2", "body": "b2", "url": "#/alerts", "ts": 2}])
    q = load(ca.PUSH_QUEUE_PATH)
    assert [x["id"] for x in q] == ["a", "b"] and set(q[0]) == {"id", "title", "body", "url", "ts"}


# ── ⑤ 키·해시 로그 미노출 · 리다이렉트 금지 ─────────────────────────────────
KEY = "  test-read-key-7Q  "


def _no_secret_in(log):
    for secret in (KEY.strip(), KEY.strip()[:4], KEY.strip()[-4:]):
        assert secret not in log, secret


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, result, seen):
        self.result, self.seen = result, seen

    def open(self, req, timeout=None):
        self.seen.append(req.get_header("X-push-read-key"))
        if isinstance(self.result, Exception):
            raise self.result
        return Resp(self.result)


def test_read_key_is_sent_but_never_logged(monkeypatch):
    pc = prefs_client
    monkeypatch.setenv("PUSH_READ_KEY", KEY)
    seen = []
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        for r in (urllib.error.HTTPError("https://w/prefs", 401, "unauthorized", {}, None),
                  urllib.error.URLError("down"), TimeoutError(), b"not json", b'{"alerts": "x"}'):
            monkeypatch.setattr(pc, "_OPENER", FakeOpener(r, seen))
            assert pc.fetch("https://w") is None
        monkeypatch.setattr(pc, "_OPENER", FakeOpener(b'{"v":1,"updatedAt":"x","alerts":[]}', seen))
        assert pc.fetch("https://w/") == {"v": 1, "updatedAt": "x", "alerts": []}
        monkeypatch.delenv("PUSH_READ_KEY")
        n = len(seen)
        assert pc.fetch("https://w") is None and len(seen) == n     # 키 없으면 부르지도 않는다
    log = out.getvalue()
    assert all(s == KEY.strip() for s in seen), seen                  # 앞뒤 공백을 자른 읽기 키
    assert "HTTP 401" in log and log.count("[prefs]") == 6, log      # 실패마다 한 줄
    _no_secret_in(log)


def test_only_push_read_key_is_used(monkeypatch):
    # B6 — CI 는 동기화 키 없이 읽기 키(PUSH_READ_KEY)로만 읽는다. GitHub 시크릿 ALERTS_SYNC_KEY 는 2026-10-09 삭제 —
    #   환경에 남아 있어도 동기화 키 해시를 보내지 않고, 읽기 키가 없으면 부르지도 않는다. 읽기 키도 로그에 안 찍힌다.
    pc = prefs_client
    sent = []

    class Opener:
        def open(self, req, timeout=None):
            sent.append({k.lower(): v for k, v in req.header_items()})
            return Resp(b'{"v":2,"updatedAt":"x","alerts":[]}')

    monkeypatch.setattr(pc, "_OPENER", Opener())
    monkeypatch.setenv("ALERTS_SYNC_KEY", KEY)
    monkeypatch.setenv("PUSH_READ_KEY", " read-key-for-test \n")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert pc.fetch("https://w") is not None
        monkeypatch.delenv("PUSH_READ_KEY")
        assert pc.fetch("https://w") is None
    assert len(sent) == 1, sent
    assert sent[0].get("x-push-read-key") == "read-key-for-test" and "x-sync-key-hash" not in sent[0], sent[0]
    log = out.getvalue()
    assert "read-key" not in log and "PUSH_READ_KEY 없음" in log, log
    _no_secret_in(log)


def test_redirects_are_not_followed_so_the_key_never_leaves_the_worker(monkeypatch):
    monkeypatch.setenv("PUSH_READ_KEY", KEY)
    hits = []

    class Other(http.server.BaseHTTPRequestHandler):                 # 리다이렉트가 가리키는 다른 호스트
        def do_GET(self):
            hits.append(self.headers.get("X-Push-Read-Key"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"v":1,"updatedAt":"x","alerts":[]}')

        def log_message(self, *a):
            pass

    other = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Other)

    class Bouncer(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{other.server_port}/prefs")
            self.end_headers()

        def log_message(self, *a):
            pass

    bounce = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Bouncer)
    for s in (other, bounce):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        with contextlib.redirect_stdout(io.StringIO()) as o:
            assert prefs_client.fetch(f"http://127.0.0.1:{bounce.server_port}") is None
        assert hits == [] and "HTTP 302" in o.getvalue(), (hits, o.getvalue())
        _no_secret_in(o.getvalue())
    finally:
        for s in (other, bounce):
            s.shutdown()
            s.server_close()


# ── ⑥ main · _write_state · snaps ─────────────────────────────────────────
def test_write_state_keeps_only_listed_conditions_and_prefs(env):
    ca._write_state({"_prefs": {"p": {"date": "20261001"}}, "gone": {}, "keep": {}}, [{"id": "keep"}], T(1, 10))
    assert set(load(ca.STATE_PATH)) == {"_prefs", "keep"}


def test_main_runs_prefs_even_without_config_file(env, monkeypatch):
    monkeypatch.setattr(ca, "_now", lambda: T(1, 10))
    calls = []
    monkeypatch.setattr(prefs_client, "fetch", lambda base: calls.append("prefs") or {
        "v": 1, "updatedAt": "x", "alerts": [A(id="m1", cond={"op": ">=", "value": 2900})]})
    monkeypatch.setattr(notify_discord, "send", lambda text, **kw: True)
    # 설정 파일이 없어도 새 화면 조건은 돈다
    with contextlib.redirect_stdout(io.StringIO()) as o:
        ca.main()
    assert "alerts_config.json 없음" in o.getvalue() and calls == ["prefs"]
    assert load(ca.STATE_PATH)["_prefs"]["m1"]["fired"] is True


def test_main_runs_legacy_first_then_prefs(env, monkeypatch):
    monkeypatch.setattr(ca, "_now", lambda: T(1, 10))
    order = []
    monkeypatch.setattr(ca, "_main_alerts", lambda now, snaps: order.append("legacy"))
    monkeypatch.setattr(prefs_client, "fetch", lambda base: order.append("prefs") or None)
    with contextlib.redirect_stdout(io.StringIO()):
        ca.main()
    assert order == ["legacy", "prefs"], order


def test_main_skips_prefs_when_global_off_or_test_run(env, monkeypatch):
    monkeypatch.setattr(ca, "_now", lambda: T(1, 10))
    order = []
    monkeypatch.setattr(prefs_client, "fetch", lambda base: order.append("prefs") or None)
    # 전역 OFF → 새 화면 조건 안 돎
    env.put("alerts_config.json", {"settings": {"enabled": False}, "alerts": [{"id": "z", "symbol": "005930"}]})
    with contextlib.redirect_stdout(io.StringIO()):
        ca.main()
    assert order == [], order
    os.remove(ca.CONFIG_PATH)
    # 테스트 런 → 새 화면 조건 안 돎
    monkeypatch.setattr(ca, "IS_TEST", True)
    with contextlib.redirect_stdout(io.StringIO()):
        ca.main()
    assert order == [], order


def test_prefs_snaps_keep_no_failures_and_do_not_requery(env):
    # snaps 에 실패(None)를 남기지 않고, 같은 런 안에서 다시 묻지도 않는다
    snaps = {}
    ctx = ca._PrefsCtx(T(1, 10), snaps, None)
    assert ctx.quote(A(target="000000")) is None and ctx.quote(A(target="000000")) is None
    assert snaps == {} and env.snap_calls == ["000000"]
    assert ctx.quote(A(target="005930")) and ("KR", "005930") in snaps
