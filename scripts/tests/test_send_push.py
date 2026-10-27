#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""send_push 발송기 테스트 — 네트워크·pywebpush 없이 가짜로.
실행: python -m pytest scripts/tests/test_send_push.py -q

지키는 것: 큐 파싱(없음·깨짐·빈 항목·상한) · 조용한 시간(자정 넘김) · 410/404 정리 · 한 기기 실패가 나머지를 안 막음 ·
VAPID claims 를 호출마다 새로 만듦 · 설정 빠지면 아무것도 안 보냄 · 보낸 뒤 큐 비움."""
import datetime
import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import send_push as sp


def check(label, got, want):
    assert got == want, f"{label}: {got!r} (기대 {want!r})"


class PushErr(Exception):
    def __init__(self, code):
        super().__init__(f"push {code}")
        self.status_code = code


def fake_push(codes):
    """endpoint 끝 글자 → 상태 코드. 200 이면 성공, 그 밖은 PushErr. 호출 기록을 남긴다."""
    calls = []

    def push(**kw):
        calls.append(kw)
        code = codes.get(kw["subscription_info"]["endpoint"][-1], 201)
        if code > 202:
            raise PushErr(code)
        kw["vapid_claims"]["aud"] = "https://" + kw["subscription_info"]["endpoint"][8:20]   # 진짜처럼 바꿔 본다
    return push, calls


def sub(n):
    return {"endpoint": f"https://fcm.googleapis.com/fcm/send/x{n}", "keys": {"p256dh": "p" * 10, "auth": "a" * 10}}


@pytest.fixture
def write_queue(monkeypatch, tmp_path):
    """큐 파일을 임시 폴더로 돌리고, 내용을 쓰는 함수를 돌려준다."""
    monkeypatch.setattr(sp, "QUEUE", str(tmp_path / "push_queue.json"))

    def write(v):
        with open(sp.QUEUE, "w", encoding="utf-8") as f:
            f.write(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
    return write


def test_queue_parsing(write_queue):
    check("파일 없음 → []", sp.load_queue(), [])
    write_queue("{")
    check("깨진 JSON → []", sp.load_queue(), [])
    write_queue([{"id": "a", "title": "삼성전자 9만원 돌파", "body": "90,100원", "url": "#/alerts", "ts": 1},
                 {"id": "b"}, "문자열", {"id": "c", "body": "본문만"}])
    check("빈 항목·문자열 버림", [x["id"] for x in sp.load_queue()], ["a", "c"])
    write_queue({"items": [{"id": "d", "title": "t"}]})
    check("{items:[…]} 모양도 받음", [x["id"] for x in sp.load_queue()], ["d"])
    write_queue([{"id": str(i), "title": "t"} for i in range(30)])
    q = sp.load_queue()
    check("큐 읽기엔 상한 없음(사람마다 plan_deliveries 가 건다)", (len(q), q[0]["id"], q[-1]["id"]), (30, "0", "29"))
    p = json.loads(sp.payload({"id": "x" * 99, "title": "제" * 300, "body": "b", "url": "#/a", "ts": 5}))
    check("내용 자름", (len(p["id"]), len(p["title"]), p["url"], p["ts"]), (64, 120, "#/a", 5))


def test_quiet_hours():
    at = lambda h, m: datetime.datetime(2026, 10, 2, h, m, tzinfo=sp.KST)
    night = {"from": "22:00", "to": "07:00"}
    check("자정 넘김 23:30 → 안", sp.in_quiet(night, at(23, 30)), True)
    check("자정 넘김 06:59 → 안", sp.in_quiet(night, at(6, 59)), True)
    check("자정 넘김 07:00 → 밖", sp.in_quiet(night, at(7, 0)), False)
    check("낮 구간 12:00~13:00, 12:30 → 안", sp.in_quiet({"from": "12:00", "to": "13:00"}, at(12, 30)), True)
    check("UTC 시각도 한국 시각으로 판정", sp.in_quiet(night, datetime.datetime(2026, 10, 2, 14, 0, tzinfo=datetime.timezone.utc)), True)
    check("없음 → 밖", sp.in_quiet(None, at(23, 0)), False)
    check("같은 시각 → 밖", sp.in_quiet({"from": "09:00", "to": "09:00"}, at(9, 0)), False)


def test_send_all_and_prune():
    items = [{"id": "a", "title": "가"}, {"id": "b", "title": "나"}]
    push, calls = fake_push({"2": 410, "3": 500, "4": 404})
    ok, fail, gone = sp.send_all(items, [sub(1), sub(2), sub(3), sub(4)], "priv", "mailto:x@example.com", push=push)
    check("성공·실패 수(1번 2건 성공, 2·4번은 첫 건에서 멈춤, 3번 2건 실패)", (ok, fail), (2, 4))
    check("410·404 만 정리 대상", gone, [sub(2)["endpoint"], sub(4)["endpoint"]])
    check("claims 가 호출마다 새 것", len({id(c["vapid_claims"]) for c in calls}), len(calls))
    check("claims 에 이전 기기 aud 가 안 섞임", all(set(c["vapid_claims"]) <= {"sub", "aud"} for c in calls) and
          all(c["vapid_claims"]["sub"] == "mailto:x@example.com" for c in calls), True)
    check("TTL·긴급·제한시간", (calls[0]["ttl"], calls[0]["headers"], calls[0]["timeout"]), (sp.TTL, {"Urgency": "high"}, 10))
    check("내용 = sw.js 모양", json.loads(calls[0]["data"])["title"], "가")


# ── main — 처음부터 끝까지 ───────────────────────────────────────────────
class Resp:
    def __init__(self, j, code=200):
        self._j, self.status_code = j, code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._j


ENV = {"PUSH_READ_KEY": "rk", "VAPID_PRIVATE_KEY": "priv", "VAPID_SUBJECT": "mailto:x@example.com", "PUSH_WORKER_URL": "https://w.test/"}


@pytest.fixture
def push_main(monkeypatch, write_queue):
    """가짜 Worker(구독 읽기·정리) + 가짜 pywebpush. 네트워크 0, 실제 패키지 없이 import 경로까지 확인한다."""
    class M:
        pass
    m = M()
    m.http = []
    m.doc = {"subs": [sub(1), sub(2)], "quiet": None}
    m.all_users = None          # None → /all 실패(옛 경로)  ·  목록이면 /push/subscriptions/all 이 그걸 준다
    m.write_queue = write_queue
    def get(url, headers, timeout):
        m.http.append(("GET", url, headers))
        if url.endswith("/all"):
            return Resp({"users": m.all_users}) if m.all_users is not None else Resp({"error": "x"}, 503)
        return Resp(m.doc)
    monkeypatch.setattr(sp.requests, "get", get)
    monkeypatch.setattr(sp.requests, "put", lambda url, headers, json, timeout: (
        m.http.append(("PUT", url, json)), Resp({"removed": len(json["endpoints"])}))[1])
    m.push, m.calls = fake_push({"2": 410})
    monkeypatch.setitem(sys.modules, "pywebpush", types.SimpleNamespace(webpush=m.push))
    m.monkeypatch = monkeypatch
    return m


def test_main_without_config_sends_nothing_and_keeps_queue(push_main):
    for k in ENV:
        push_main.monkeypatch.setenv(k, "")
    push_main.write_queue([{"id": "a", "title": "가"}])
    check("설정 빠짐 → 0 · 요청 없음", (sp.main(), push_main.http), (0, []))
    check("설정 빠짐 → 큐는 그대로", os.path.exists(sp.QUEUE), True)


def test_main_empty_queue_sends_nothing(push_main):
    for k, v in ENV.items():
        push_main.monkeypatch.setenv(k, v)
    check("빈 큐 → 0 · 요청 없음", (sp.main(), push_main.http), (0, []))


def test_main_happy_path_sends_prunes_and_clears_queue(push_main):
    for k, v in ENV.items():
        push_main.monkeypatch.setenv(k, v)
    push_main.all_users = [{"uid": "o" * 16, "role": "owner", "quiet": None, "subs": [sub(1), sub(2)]}]
    push_main.write_queue([{"id": "a", "title": "가"}])
    check("정상 → 0", sp.main(), 0)
    check("구독 읽기 = 발송기 키 헤더(/all 먼저)", push_main.http[0], ("GET", "https://w.test/push/subscriptions/all", {"X-Push-Read-Key": "rk"}))
    check("410 받은 구독 정리 요청", push_main.http[-1], ("PUT", "https://w.test/push/prune", {"uid": "o" * 16, "endpoints": [sub(2)["endpoint"]]}))
    check("pywebpush 로 2대에 보냄", len(push_main.calls), 2)
    check("보낸 뒤 큐 비움", os.path.exists(sp.QUEUE), False)


def test_main_quiet_hours_do_not_send_but_clear_queue(push_main):
    for k, v in ENV.items():
        push_main.monkeypatch.setenv(k, v)
    push_main.all_users = [{"uid": "o" * 16, "role": "owner", "quiet": {"from": "00:00", "to": "23:59"}, "subs": [sub(1), sub(2)]}]
    push_main.write_queue([{"id": "a", "title": "가"}])
    check("조용한 시간 → 0 · 보내지 않음", (sp.main(), len(push_main.calls), [h[0] for h in push_main.http]), (0, 0, ["GET"]))
    check("조용한 시간에도 큐 비움", os.path.exists(sp.QUEUE), False)


def test_main_quiet_hours_let_alarm_through(push_main):
    """「경보는 조용한 시간에도 울리기」— 편성이 내보낸 경보(pierceQuiet)만 보내고 나머지는 버린다.
    디스코드 @everyone 이 밤 경보를 울리던 길이 없어져 푸시가 유일한 울림이다(2026-10-13)."""
    for k, v in ENV.items():
        push_main.monkeypatch.setenv(k, v)
    push_main.all_users = [{"uid": "o" * 16, "role": "owner", "quiet": {"from": "00:00", "to": "23:59"}, "subs": [sub(1), sub(2)]}]
    push_main.write_queue([{"id": "a", "title": "알림"}, {"id": "b", "title": "경보", "pierceQuiet": True}])
    check("조용한 시간 경보 → 0", sp.main(), 0)
    check("경보만 보냄", sorted({json.loads(c["data"])["id"] for c in push_main.calls}), ["b"])
    check("보낸 뒤 큐 비움", os.path.exists(sp.QUEUE), False)


def test_main_subscription_list_401_sends_nothing(push_main):
    for k, v in ENV.items():
        push_main.monkeypatch.setenv(k, v)
    push_main.monkeypatch.setattr(sp.requests, "get", lambda url, headers, timeout: Resp({"error": "unauthorized"}, 401))
    push_main.write_queue([{"id": "a", "title": "가"}])
    check("구독 목록 401 → 0 · 발송 없음", (sp.main(), len(push_main.calls)), (0, 0))


# ── 사람별 발송 (Task 14) ────────────────────────────────────────────────
OWN, M1, M2 = "o" * 16, "a" * 16, "b" * 16
NIGHT = {"from": "00:00", "to": "23:59"}          # 항상 조용한 시간


def three(push_main, m1_quiet=None):
    push_main.all_users = [
        {"uid": OWN, "role": "owner", "quiet": None, "subs": [sub(1)]},
        {"uid": M1, "role": "member", "quiet": m1_quiet, "subs": [sub(5), sub(6)]},
        {"uid": M2, "role": "member", "quiet": None, "subs": [sub(7)]},
    ]
    for k, v in ENV.items():
        push_main.monkeypatch.setenv(k, v)


def by_ep(push_main):
    out = {}
    for c in push_main.calls:
        out.setdefault(c["subscription_info"]["endpoint"][-2:], []).append(json.loads(c["data"])["title"])
    return out


def test_member_items_only_to_that_member(push_main):
    three(push_main)
    push_main.write_queue([{"id": "a", "uid": OWN, "title": "주인"}, {"id": "b", "uid": M1, "title": "멤버1"},
                           {"id": "c", "uid": M2, "title": "멤버2"}, {"id": "d", "title": "옛 항목(uid 없음)"}])
    check("정상 → 0", sp.main(), 0)
    got = by_ep(push_main)
    check("주인 기기엔 주인 것 + uid 없는 것만", sorted(got["x1"]), ["옛 항목(uid 없음)", "주인"])
    check("멤버1 두 기기엔 멤버1 것만", (got["x5"], got["x6"]), (["멤버1"], ["멤버1"]))
    check("멤버2 기기엔 멤버2 것만", got["x7"], ["멤버2"])
    check("GET 은 /all 한 번뿐", [h[1] for h in push_main.http if h[0] == "GET"], ["https://w.test/push/subscriptions/all"])


def test_unknown_uid_dropped_and_log_has_no_uid(push_main, capsys):
    three(push_main)
    push_main.write_queue([{"id": "z", "uid": "f" * 16, "title": "지운 멤버 비밀제목"}, {"id": "b", "uid": M1, "title": "멤버1"}])
    sp.main()
    check("모르는 uid 는 안 보냄", sorted(by_ep(push_main)), ["x5", "x6"])
    out = capsys.readouterr().out
    assert "받을 사람이 없는 알림 1건" in out and "멤버 1명 · 1건" in out, out
    assert "f" * 16 not in out and M1 not in out and "비밀제목" not in out, out


def test_dedupe_by_uid_and_id(push_main):
    three(push_main)
    push_main.write_queue([{"id": "BUNDLE:d:0900", "uid": M1, "title": "m1-첫"}, {"id": "BUNDLE:d:0900", "uid": M1, "title": "m1-중복"},
                           {"id": "BUNDLE:d:0900", "uid": M2, "title": "m2"}, {"id": "BUNDLE:d:0900", "uid": OWN, "title": "own"}])
    sp.main()
    got = by_ep(push_main)
    check("같은 id 도 사람이 다르면 각자 한 번", (got["x5"], got["x7"], got["x1"]), (["m1-첫"], ["m2"], ["own"]))


def test_per_person_limit_keeps_owner(push_main):
    three(push_main)
    push_main.write_queue([{"id": f"m{i}", "uid": M1, "title": f"m{i}"} for i in range(30)] + [{"id": "o1", "uid": OWN, "title": "own"}])
    sp.main()
    got = by_ep(push_main)
    check("멤버는 최신 20건", (len(got["x5"]), got["x5"][0], got["x5"][-1]), (sp.MAX_ITEMS, "m10", "m29"))
    check("주인 항목은 밀려나지 않음", got["x1"], ["own"])


def test_quiet_per_person(push_main):
    three(push_main, m1_quiet=NIGHT)
    push_main.write_queue([{"id": "a", "uid": M1, "title": "보통"}, {"id": "b", "uid": M1, "title": "경보", "pierceQuiet": True},
                           {"id": "c", "uid": M2, "title": "m2 보통"}, {"id": "d", "uid": OWN, "title": "own 보통"}])
    sp.main()
    got = by_ep(push_main)
    check("멤버1 은 경보만", got["x5"], ["경보"])
    check("다른 사람은 영향 없음", (got["x7"], got["x1"]), (["m2 보통"], ["own 보통"]))


def test_member_log_does_not_show_endpoint(push_main, capsys):
    three(push_main)
    push_main.push, push_main.calls = fake_push({"5": 410, "7": 500})
    push_main.monkeypatch.setitem(sys.modules, "pywebpush", types.SimpleNamespace(webpush=push_main.push))
    push_main.write_queue([{"id": "b", "uid": M1, "title": "m1"}, {"id": "c", "uid": M2, "title": "m2"}])
    sp.main()
    out = capsys.readouterr().out
    assert "x5" not in out and "x7" not in out and "fcm/send" not in out, out


def test_fallback_logs_held_count_without_owner_uid(push_main, capsys):
    for k, v in ENV.items():
        push_main.monkeypatch.setenv(k, v)
    push_main.all_users = None
    push_main.doc = {"subs": [sub(1)], "quiet": None}            # 옛 Worker — uid 없음
    push_main.write_queue([{"id": "a", "uid": OWN, "title": "주인"}, {"id": "b", "uid": M1, "title": "멤버"}, {"id": "c", "title": "옛"}])
    sp.main()
    out = capsys.readouterr().out
    assert "uid 달린 알림 2건 보류" in out and OWN not in out and M1 not in out, out
    check("uid 없는 것만 감", by_ep(push_main), {"x1": ["옛"]})


def test_all_failure_falls_back_to_owner_only(push_main):
    for k, v in ENV.items():
        push_main.monkeypatch.setenv(k, v)
    push_main.all_users = None                          # /all 503
    push_main.doc = {"subs": [sub(1)], "quiet": None}
    push_main.write_queue([{"id": "a", "uid": M1, "title": "멤버"}, {"id": "b", "title": "옛 항목"}])
    check("정상 → 0", sp.main(), 0)
    check("주인 기기엔 uid 없는 것만", by_ep(push_main), {"x1": ["옛 항목"]})
    # 옛 경로가 주인 uid 를 알려 주면 그 uid 항목도 주인 것
    push_main.calls.clear()
    push_main.doc = {"subs": [sub(1)], "quiet": None, "uid": OWN}
    push_main.write_queue([{"id": "a", "uid": M1, "title": "멤버"}, {"id": "b", "uid": OWN, "title": "주인"}])
    sp.main()
    check("주인 uid 항목만", by_ep(push_main), {"x1": ["주인"]})


def test_prune_per_uid_and_sent_file_owner_only(push_main):
    three(push_main)
    push_main.all_users[0]["subs"] = [sub(1), sub(2)]    # 주인 2번 = 410
    push_main.all_users[1]["subs"] = [sub(5)]
    push_main.all_users[2]["subs"] = [sub(7), sub(3)]    # 멤버2 3번 = 404
    push_main.push, push_main.calls = fake_push({"2": 410, "3": 404})
    push_main.monkeypatch.setitem(sys.modules, "pywebpush", types.SimpleNamespace(webpush=push_main.push))
    push_main.write_queue([{"id": "own-id", "uid": OWN, "title": "주인제목"}, {"id": "mem-id", "uid": M1, "title": "멤버제목"},
                           {"id": "mem2-id", "uid": M2, "title": "m2"}])
    sp.main()
    puts = [h[2] for h in push_main.http if h[0] == "PUT"]
    check("사람별 prune", sorted(puts, key=lambda p: p["uid"]), sorted(
        [{"uid": OWN, "endpoints": [sub(2)["endpoint"]]}, {"uid": M2, "endpoints": [sub(3)["endpoint"]]}], key=lambda p: p["uid"]))
    raw = open(os.path.join(os.path.dirname(sp.QUEUE), "push_sent.json"), encoding="utf-8").read()
    check("push_sent.json = 주인 id 만", json.loads(raw), ["own-id"])
    assert M1 not in raw and M2 not in raw and "멤버" not in raw and "mem" not in raw, raw
