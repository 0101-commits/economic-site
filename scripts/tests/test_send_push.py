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
    check(f"상한 {sp.MAX_ITEMS}건 · 최신 것", (len(q), q[0]["id"], q[-1]["id"]), (sp.MAX_ITEMS, "10", "29"))
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
    m.write_queue = write_queue
    monkeypatch.setattr(sp.requests, "get", lambda url, headers, timeout: (m.http.append(("GET", url, headers)), Resp(m.doc))[1])
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
    push_main.write_queue([{"id": "a", "title": "가"}])
    check("정상 → 0", sp.main(), 0)
    check("구독 읽기 = 발송기 키 헤더", push_main.http[0], ("GET", "https://w.test/push/subscriptions", {"X-Push-Read-Key": "rk"}))
    check("410 받은 구독 정리 요청", push_main.http[1], ("PUT", "https://w.test/push/prune", {"endpoints": [sub(2)["endpoint"]]}))
    check("pywebpush 로 2대에 보냄", len(push_main.calls), 2)
    check("보낸 뒤 큐 비움", os.path.exists(sp.QUEUE), False)


def test_main_quiet_hours_do_not_send_but_clear_queue(push_main):
    for k, v in ENV.items():
        push_main.monkeypatch.setenv(k, v)
    push_main.doc["quiet"] = {"from": "00:00", "to": "23:59"}
    push_main.write_queue([{"id": "a", "title": "가"}])
    check("조용한 시간 → 0 · 보내지 않음", (sp.main(), len(push_main.calls), [h[0] for h in push_main.http]), (0, 0, ["GET"]))
    check("조용한 시간에도 큐 비움", os.path.exists(sp.QUEUE), False)


def test_main_subscription_list_401_sends_nothing(push_main):
    for k, v in ENV.items():
        push_main.monkeypatch.setenv(k, v)
    push_main.monkeypatch.setattr(sp.requests, "get", lambda url, headers, timeout: Resp({"error": "unauthorized"}, 401))
    push_main.write_queue([{"id": "a", "title": "가"}])
    check("구독 목록 401 → 0 · 발송 없음", (sp.main(), len(push_main.calls)), (0, 0))
