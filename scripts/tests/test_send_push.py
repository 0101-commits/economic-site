#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""send_push 발송기 테스트 — pytest 없이 직접 실행, 네트워크·pywebpush 없이 가짜로.
실행: python scripts/tests/test_send_push.py  (성공 시 'ALL PASS').

지키는 것: 큐 파싱(없음·깨짐·빈 항목·상한) · 조용한 시간(자정 넘김) · 410/404 정리 · 한 기기 실패가 나머지를 안 막음 ·
VAPID claims 를 호출마다 새로 만듦 · 설정 빠지면 아무것도 안 보냄 · 보낸 뒤 큐 비움."""
import datetime
import json
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

import send_push as sp

FAILS = []


def check(label, got, want):
    if got == want:
        print(f"  OK   {label}")
    else:
        FAILS.append(label)
        print(f"  FAIL {label}: {got!r} (기대 {want!r})")


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


tmp = tempfile.mkdtemp()
sp.QUEUE = os.path.join(tmp, "push_queue.json")


def write_queue(v):
    with open(sp.QUEUE, "w", encoding="utf-8") as f:
        f.write(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))


print("큐 파싱")
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

print("조용한 시간")
at = lambda h, m: datetime.datetime(2026, 10, 2, h, m, tzinfo=sp.KST)
night = {"from": "22:00", "to": "07:00"}
check("자정 넘김 23:30 → 안", sp.in_quiet(night, at(23, 30)), True)
check("자정 넘김 06:59 → 안", sp.in_quiet(night, at(6, 59)), True)
check("자정 넘김 07:00 → 밖", sp.in_quiet(night, at(7, 0)), False)
check("낮 구간 12:00~13:00, 12:30 → 안", sp.in_quiet({"from": "12:00", "to": "13:00"}, at(12, 30)), True)
check("UTC 시각도 한국 시각으로 판정", sp.in_quiet(night, datetime.datetime(2026, 10, 2, 14, 0, tzinfo=datetime.timezone.utc)), True)
check("없음 → 밖", sp.in_quiet(None, at(23, 0)), False)
check("같은 시각 → 밖", sp.in_quiet({"from": "09:00", "to": "09:00"}, at(9, 0)), False)

print("발송 · 정리")
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

print("main — 처음부터 끝까지")
HTTP = []


class Resp:
    def __init__(self, j, code=200):
        self._j, self.status_code = j, code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._j


DOC = {"subs": [sub(1), sub(2)], "quiet": None}
sp.requests.get = lambda url, headers, timeout: (HTTP.append(("GET", url, headers)), Resp(DOC))[1]
sp.requests.put = lambda url, headers, json, timeout: (HTTP.append(("PUT", url, json)), Resp({"removed": len(json["endpoints"])}))[1]
mod_push, mod_calls = fake_push({"2": 410})
sys.modules["pywebpush"] = types.SimpleNamespace(webpush=mod_push)   # 실제 패키지 없이 import 경로까지 확인
ENV = {"PUSH_READ_KEY": "rk", "VAPID_PRIVATE_KEY": "priv", "VAPID_SUBJECT": "mailto:x@example.com", "PUSH_WORKER_URL": "https://w.test/"}

os.environ.update({k: "" for k in ENV})
write_queue([{"id": "a", "title": "가"}])
check("설정 빠짐 → 0 · 요청 없음", (sp.main(), HTTP), (0, []))
check("설정 빠짐 → 큐는 그대로", os.path.exists(sp.QUEUE), True)

os.environ.update(ENV)
os.remove(sp.QUEUE)
check("빈 큐 → 0 · 요청 없음", (sp.main(), HTTP), (0, []))

write_queue([{"id": "a", "title": "가"}])
check("정상 → 0", sp.main(), 0)
check("구독 읽기 = 발송기 키 헤더", HTTP[0], ("GET", "https://w.test/push/subscriptions", {"X-Push-Read-Key": "rk"}))
check("410 받은 구독 정리 요청", HTTP[1], ("PUT", "https://w.test/push/prune", {"endpoints": [sub(2)["endpoint"]]}))
check("pywebpush 로 2대에 보냄", len(mod_calls), 2)
check("보낸 뒤 큐 비움", os.path.exists(sp.QUEUE), False)

HTTP.clear(); mod_calls.clear()
DOC["quiet"] = {"from": "00:00", "to": "23:59"}
write_queue([{"id": "a", "title": "가"}])
check("조용한 시간 → 0 · 보내지 않음", (sp.main(), len(mod_calls), [h[0] for h in HTTP]), (0, 0, ["GET"]))
check("조용한 시간에도 큐 비움", os.path.exists(sp.QUEUE), False)

HTTP.clear()
sp.requests.get = lambda url, headers, timeout: Resp({"error": "unauthorized"}, 401)
write_queue([{"id": "a", "title": "가"}])
check("구독 목록 401 → 0 · 발송 없음", (sp.main(), len(mod_calls)), (0, 0))

if FAILS:
    print(f"\n{len(FAILS)}건 실패")
    sys.exit(1)
print("\nALL PASS")
