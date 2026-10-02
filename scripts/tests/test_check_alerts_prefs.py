#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""새 화면(/prefs) 조건 — python scripts/tests/test_check_alerts_prefs.py

① 변환 6종(price·pct·high52·event·flow·lens)과 매핑 불가 건너뛰기
② 반복 규칙 — once(price·pct·high52·lens 는 끝, event 는 일정마다, flow 는 전환마다 + 같은 방향 24시간),
   daily 하루 한 번·같은 발생 재발송 없음, 발송 실패는 기록하지 않음(렌즈 기준선 포함)
③ /prefs 를 못 받거나 빈 문서(updatedAt 없음)면 상태를 건드리지 않음 · 채널 없는 조건은 평가 안 함
④ 푸시 — 큐 적재 모양, send_push 가 실제로 보낸 것만 --confirm-push 가 확정
⑤ 동기화 키·해시가 로그에 안 찍히고, 리다이렉트를 따라가지 않음 · 공개 로그에 조건 내용(이름·값)이 없음
⑥ main — 현행 뒤에 새 화면 조건 · 전역 OFF·테스트 런이면 안 돎 · 설정 파일이 없어도 돎 · snaps 에 None 안 남김
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
import tempfile
import threading
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.pop("ALERTS_TEST", None)
import check_alerts as ca       # noqa: E402
import notify_discord           # noqa: E402
import prefs_client             # noqa: E402

KST = datetime.timezone(datetime.timedelta(hours=9))
T = lambda d, h, m=0, mo=10: datetime.datetime(2026, mo, d, h, m, tzinfo=KST)   # 10/1 목 · 10/2 금

# ── 가짜 체크아웃 ─────────────────────────────────────────────────────────
tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, "bundles"))
ca.ROOT = tmp
ca.STATE_PATH = os.path.join(tmp, "alerts_state.json")
ca.PUSH_QUEUE_PATH = os.path.join(tmp, "push_queue.json")
ca.PUSH_SENT_PATH = os.path.join(tmp, "push_sent.json")
ca.CONFIG_PATH = os.path.join(tmp, "alerts_config.json")


def put(rel, obj):
    with open(os.path.join(tmp, rel), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


put("bundles/registry.json", {"rows": [
    {"id": "kospi", "label": "KOSPI", "short": "KOSPI", "decimals": 2, "country": "kr",
     "seriesPath": "history.indices.KOSPI"},
    {"id": "cpi_us", "label": "소비자물가지수 (CPI)", "short": "미국 소비자물가지수", "shortM": "미국 CPI",
     "decimals": 1, "country": "us"},
    {"id": "sp500", "label": "S&P 500", "short": "S&P 500", "decimals": 2, "country": "us"},
]})
HOME = {"strip": [{"id": "kospi", "value": 3000.0, "changePct": 2.5, "asOf": "2026-10-01"},
                  {"id": "cpi_us", "value": 320.1, "changePct": 0.1, "asOf": "2026-09-15"},
                  {"id": "sp500", "value": 7000.0, "changePct": -0.3, "asOf": "2026-09-30"}]}
put("bundles/home.json", HOME)
hist = [{"date": (datetime.date(2026, 6, 1) + datetime.timedelta(days=i)).isoformat(), "close": 2000.0 + i * 10}
        for i in range(100)]                                  # 2000 … 2990 — 3000 이면 52주 최고
DATA = {
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
put("data.json", DATA)
MER = {"indicators": [
    {"id": "us10y", "label": "미국채 10년물", "unit": "%", "state": "below",
     "current": {"value": 5.0, "asOf": "2026-09-29"}, "nearest": {"level": 5.1}},
    {"id": "us_equity", "label": "미국 증시", "state": "below", "current": {"value": 1, "asOf": "2026-09-29"}},
]}
put("mer_signals.json", MER)
ca._PrefsCtx.rows = lambda self: {"sp500": {"merLens": "us_equity"}}   # 레지스트리 원본 대신(별칭 매핑만 본다)

snap_calls = []
SNAP = {"price": 91000.0, "pct": 1.0, "highs": [80000.0] * 100 + [91500.0], "lows": [70000.0] * 101,
        "closes": [80000.0] * 101, "fresh": True}


def fake_snapshot(market, sym, yahoo):
    snap_calls.append(sym)
    return None if sym == "000000" else dict(SNAP)


ca.get_snapshot = fake_snapshot


def A(**kw):
    a = {"id": "x", "target": "kospi", "type": "price", "cond": {}, "repeat": "once",
         "channels": ["discord"], "enabled": True}
    a.update(kw)
    return a


def ev(a, now, rec=None, cfg=None):
    return ca._prefs_eval(a, ca._PrefsCtx(now, {}, cfg), {} if rec is None else rec)


# ── ① 변환 6종 ────────────────────────────────────────────────────────────
now = T(1, 10)
h = ev(A(cond={"op": ">=", "value": 2900}), now)
assert h and h[0] == "KOSPI 2,900.00 이상 도달" and h[2] == "#/i/kospi" and h[3] == "2026-10-01", h
assert ev(A(cond={"op": "<=", "value": 2900}), now) is None
h = ev(A(target="005930", cond={"op": ">=", "value": 90000}), now)          # 국내 종목: 장중·원 표기
assert h and h[0] == "삼성전자 90,000원 이상 도달" and h[2] == "#/market?a=kr&m=all", h
assert ev(A(target="005930", cond={"op": ">=", "value": 90000}), T(1, 16)) is None   # 장 밖
assert ev(A(type="pct", cond={"op": ">=", "value": 2}), now)[0] == "KOSPI 하루 +2% 도달"
assert ev(A(type="pct", cond={"pct": 2}), now)                              # 옛 모양 cond.pct
assert ev(A(type="pct", cond={"op": "<=", "value": -2}), now) is None
assert ev(A(type="high52", cond={"side": "high"}), now)[0] == "KOSPI 52주 최고 돌파"
assert ev(A(type="high52", cond={"side": "low"}), now) is None
assert ev(A(type="high52", target="005930", cond={"side": "high"}), now)[0] == "삼성전자 52주 최고 돌파"
assert ev(A(type="high52", target="sp500", cond={"side": "high"}), now) is None   # 시계열 없음 → 판정 보류
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
# lens — 첫 관측은 기준선, 바뀔 때만. 울릴 때의 새 상태는 다섯째 값(발송 확정 뒤에 기록)
lz = A(type="lens", target="us10y", cond={"state": "crossed"})
rec = {}
assert ev(lz, now, rec) is None and rec["lensState"] == "below"
MER["indicators"][0]["state"] = "crossed"
put("mer_signals.json", MER)
h = ev(lz, now, rec)
assert h and h[0] == "렌즈 돌파 · 미국채 10년물" and h[1] == "지금 5.0% · 기준 5.1%" and h[2] == "#/lens?s=us10y", h
assert rec["lensState"] == "below" and h[4] == {"lensState": "crossed"}     # 울릴 땐 기준선을 미리 안 바꾼다
rec.update(h[4])
assert ev(lz, now, rec) is None                               # 확정 뒤 — 계속 돌파 중
rec = {"lensState": "near"}
MER["indicators"][1]["state"] = "crossed"
put("mer_signals.json", MER)
assert ev(A(type="lens", target="sp500", cond={"state": "crossed"}), now, rec)[0] == "렌즈 돌파 · 미국 증시"   # merLens
out = io.StringIO()
with contextlib.redirect_stdout(out):
    assert ev(A(target="nope"), now) is None
    assert ev(A(type="zzz"), now) is None
    assert ev(A(cond={"op": "!=", "value": 1}), now) is None
assert out.getvalue().count("[prefs] 건너뜀") == 3, out.getvalue()

# ── ② 반복 규칙 ───────────────────────────────────────────────────────────
sent = []
DISCORD_OK = [True]
notify_discord.send = lambda text, **kw: sent.append((text, kw)) or DISCORD_OK[0]
DOC = {"v": 1, "updatedAt": "2026-10-01T00:00:00.000Z", "alerts": []}
prefs_client.fetch = lambda base: copy.deepcopy(DOC)


def run(now, deliver=True):
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


def P(st, aid):
    return st.get("_prefs", {}).get(aid, {})


DOC["alerts"] = [
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
HOME["strip"][0]["asOf"] = "2026-10-02"
put("bundles/home.json", HOME)
ch, st, _ = run(T(2, 10))
assert ch and P(st, "p2")["hist"] == ["20261001", "20261002"] and P(st, "p1")["hist"] == ["20261001"]

# 푸시가 안 갔으면(조용한 시간·구독 0대) 확정하지 않고 다음 런에 다시 쌓는다
DOC["alerts"] = [A(id="q1", cond={"op": ">=", "value": 2900}, channels=["push"])]
ch, st, log = run(T(2, 10, 1), deliver=False)
assert "q1" not in st["_prefs"] and "미발송 대기 해제 1건" in log
ch, st, log = run(T(2, 10, 2))
assert P(st, "q1")["fired"] is True and "푸시 확정 1건" in log

# 디스코드 실패 → 기록 안 함 → 다음 런 재시도. 렌즈 기준선도 그대로라 다음 런에 다시 울린다.
MER["indicators"][0]["state"] = "below"
put("mer_signals.json", MER)
DOC["alerts"] = [A(id="l1", type="lens", target="us10y", cond={"state": "crossed"})]
run(T(2, 11))
assert P(load(ca.STATE_PATH), "l1") == {"lensState": "below"}       # 첫 관측 = 기준선
MER["indicators"][0]["state"] = "crossed"
put("mer_signals.json", MER)
DISCORD_OK[0] = False
ch, st, log = run(T(2, 11, 1))
assert P(st, "l1") == {"lensState": "below"} and "다음 런 재시도" in log
DISCORD_OK[0] = True
ch, st, _ = run(T(2, 11, 2))
assert P(st, "l1")["fired"] is True and P(st, "l1")["lensState"] == "crossed"

# event once = 일정마다 한 번(같은 이름의 다음 발표에는 다시 울림), 영구 종료 아님
DOC["alerts"] = [A(id="e1", type="event", target="cpi_us", cond={"daysBefore": 1})]
ch, st, _ = run(T(1, 22, 10))
assert ch and "fired" not in P(st, "e1") and len(P(st, "e1")["keys"]) == 1
assert run(T(2, 9))[0] is False                                     # 같은 일정은 다음 날 아침에도 안 보냄
ch, st, _ = run(T(9, 22, 0, mo=11))
assert ch and P(st, "e1")["hist"] == ["20261001", "20261109"], P(st, "e1")

# flow once = 전환마다 한 번 + 같은 방향은 24시간 쿨다운
DOC["alerts"] = [A(id="f1", type="flow", cond={"who": "foreign"})]
ch, st, _ = run(T(1, 19))
r = P(st, "f1")
assert "fired" not in r and r["flowDir"] == "buy" and r["flowTs"] == int(T(1, 19).timestamp())
assert run(T(2, 10))[0] is False                                    # 같은 전환(10/1 행) 다시 안 보냄
DATA["investorTrading"]["daily"].append({"date": "2026-10-02", "foreign": -10.0})
put("data.json", DATA)
ch, st, _ = run(T(2, 19))
assert ch and P(st, "f1")["flowDir"] == "sell"                      # 반대 방향은 24시간 안이어도 바로
DATA["investorTrading"]["daily"].append({"date": "2026-10-05", "foreign": 30.0})
put("data.json", DATA)
rec = {"flowDir": "buy", "flowTs": int(T(5, 9).timestamp())}
assert ev(A(type="flow", cond={"who": "foreign"}), T(5, 19), rec) is None          # 같은 방향 24시간 안
rec["flowTs"] = int(T(4, 18).timestamp())
assert ev(A(type="flow", cond={"who": "foreign"}), T(5, 19), rec)[4] == {"flowDir": "buy"}   # 24시간 지남

# ── ③ 못 받음 · 빈 문서 · 채널 없음 ───────────────────────────────────────
before = load(ca.STATE_PATH)
prefs_client.fetch = lambda base: None
assert run(T(2, 12))[0] is False and load(ca.STATE_PATH) == before
prefs_client.fetch = lambda base: {"v": 1, "updatedAt": None, "alerts": []}       # 키 바꾼 직후의 빈 칸
ch, st, log = run(T(2, 12))
assert ch is False and st == before and "빈 문서" in log
prefs_client.fetch = lambda base: copy.deepcopy(DOC)
DOC["alerts"] = [A(id="m0", cond={"op": ">=", "value": 1}, channels=[]), A(id="m9", cond={"op": ">=", "value": 1}, channels=[])]
ch, st, log = run(T(2, 12, 1))
assert "m0" not in st.get("_prefs", {}) and log.count("받을 채널이 없는 조건 2개") == 1 and "조건 충족" not in log

# ── ④ 큐 적재 모양 ─────────────────────────────────────────────────────────
assert ca._enqueue_push([{"id": "a", "title": "t", "body": "b", "url": "#/i/kospi", "ts": 1}])
assert ca._enqueue_push([{"id": "b", "title": "t2", "body": "b2", "url": "#/alerts", "ts": 2}])
q = load(ca.PUSH_QUEUE_PATH)
assert [x["id"] for x in q] == ["a", "b"] and set(q[0]) == {"id", "title", "body", "url", "ts"}
os.remove(ca.PUSH_QUEUE_PATH)

# ── ⑤ 키·해시 로그 미노출 · 리다이렉트 금지 ─────────────────────────────────
import importlib                                                  # noqa: E402
pc = importlib.reload(prefs_client)                               # 위에서 덮어쓴 fetch 를 되돌린다
KEY = "  test-sync-passphrase-7Q  "
HASH = hashlib.sha256(KEY.strip().encode()).hexdigest()
seen = []


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, result):
        self.result = result

    def open(self, req, timeout=None):
        seen.append(req.get_header("X-sync-key-hash"))
        if isinstance(self.result, Exception):
            raise self.result
        return Resp(self.result)


real_opener = pc._OPENER
out = io.StringIO()
with contextlib.redirect_stdout(out):
    for r in (urllib.error.HTTPError("https://w/prefs", 401, "unauthorized", {}, None),
              urllib.error.URLError("down"), TimeoutError(), b"not json", b'{"alerts": "x"}'):
        pc._OPENER = FakeOpener(r)
        assert pc.fetch("https://w", key=KEY) is None
    pc._OPENER = FakeOpener(b'{"v":1,"updatedAt":"x","alerts":[]}')
    assert pc.fetch("https://w/", key=KEY) == {"v": 1, "updatedAt": "x", "alerts": []}
    os.environ.pop("ALERTS_SYNC_KEY", None)
    n = len(seen)
    assert pc.fetch("https://w") is None and len(seen) == n     # 키 없으면 부르지도 않는다
log = out.getvalue()
assert all(s == HASH for s in seen), seen                         # 앞뒤 공백을 자른 키의 SHA-256
assert "HTTP 401" in log and log.count("[prefs]") == 6, log      # 실패마다 한 줄
pc._OPENER = real_opener

hits = []


class Other(http.server.BaseHTTPRequestHandler):                 # 리다이렉트가 가리키는 다른 호스트
    def do_GET(self):
        hits.append(self.headers.get("X-Sync-Key-Hash"))
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
with contextlib.redirect_stdout(io.StringIO()) as o:
    assert pc.fetch(f"http://127.0.0.1:{bounce.server_port}", key=KEY) is None
log += o.getvalue()
assert hits == [] and "HTTP 302" in o.getvalue(), (hits, o.getvalue())
for s in (other, bounce):
    s.shutdown()
for secret in (KEY.strip(), HASH, KEY.strip()[:4], KEY.strip()[-4:], HASH[:8]):
    assert secret not in log, secret

# ── ⑥ main · _write_state · snaps ─────────────────────────────────────────
ca._write_state({"_prefs": {"p": {"date": "20261001"}}, "gone": {}, "keep": {}}, [{"id": "keep"}], T(1, 10))
assert set(load(ca.STATE_PATH)) == {"_prefs", "keep"}
os.remove(ca.STATE_PATH)
ca._now = lambda: T(1, 10)
pcm = sys.modules["prefs_client"]
calls = []
pcm.fetch = lambda base: calls.append("prefs") or {"v": 1, "updatedAt": "x",
                                                     "alerts": [A(id="m1", cond={"op": ">=", "value": 2900})]}
notify_discord.send = lambda text, **kw: True
# 설정 파일이 없어도 새 화면 조건은 돈다
with contextlib.redirect_stdout(io.StringIO()) as o:
    ca.main()
assert "alerts_config.json 없음" in o.getvalue() and calls == ["prefs"]
assert load(ca.STATE_PATH)["_prefs"]["m1"]["fired"] is True
# 현행이 먼저, 새 화면이 나중
order = []
real_main_alerts = ca._main_alerts
ca._main_alerts = lambda now, snaps: order.append("legacy")
pcm.fetch = lambda base: order.append("prefs") or None
with contextlib.redirect_stdout(io.StringIO()):
    ca.main()
assert order == ["legacy", "prefs"], order
ca._main_alerts = real_main_alerts
# 전역 OFF · 테스트 런 → 새 화면 조건 안 돎
put("alerts_config.json", {"settings": {"enabled": False}, "alerts": [{"id": "z", "symbol": "005930"}]})
order.clear()
with contextlib.redirect_stdout(io.StringIO()):
    ca.main()
assert order == [], order
os.remove(ca.CONFIG_PATH)
ca.IS_TEST = True
with contextlib.redirect_stdout(io.StringIO()):
    ca.main()
assert order == [], order
ca.IS_TEST = False
# snaps 에 실패(None)를 남기지 않고, 같은 런 안에서 다시 묻지도 않는다
snaps, snap_calls[:] = {}, []
ctx = ca._PrefsCtx(T(1, 10), snaps, None)
assert ctx.quote(A(target="000000")) is None and ctx.quote(A(target="000000")) is None
assert snaps == {} and snap_calls == ["000000"]
assert ctx.quote(A(target="005930")) and ("KR", "005930") in snaps
print("ok")
