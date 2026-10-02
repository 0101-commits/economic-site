#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""웹 푸시 발송기 — scripts/push_queue.json 의 알림을 이 사이트를 구독한 기기에 보낸다.

입력  scripts/push_queue.json = [{id, title, body, url, ts}, ...] (check_alerts.py 가 쌓는다). 없거나 비면 종료 0.
구독  Worker GET /push/subscriptions (헤더 X-Push-Read-Key = 시크릿 PUSH_READ_KEY) → {subs, quiet}.
정리  푸시 서비스가 410·404(구독 사라짐)로 답한 주소는 Worker PUT /push/prune 으로 지운다.
환경  PUSH_READ_KEY · VAPID_PRIVATE_KEY(base64url 32바이트, scripts/gen_vapid.py) · VAPID_SUBJECT(mailto:…)
      PUSH_WORKER_URL(선택, 기본 운영 Worker).

설정이 빠지면 아무것도 보내지 않고 종료 0 — 알림 워크플로의 다른 스텝을 막지 않는다.
보낸 뒤에는 성공·실패와 관계없이 큐를 비운다(같은 알림이 다음 런에 또 가지 않게).
ponytail: 실패한 기기에 다시 보내지 않는다(최대 한 번 전달). 재시도가 필요하면 기기별 실패 큐를 둔다.
실행: python scripts/send_push.py   테스트: python scripts/tests/test_send_push.py
"""
import datetime
import json
import os
import sys

import requests

try:                                    # Windows cp949 콘솔에서도 한글 로그가 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

QUEUE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "push_queue.json")
WORKER = "https://ecom-dashboard-proxy.e-hcg.workers.dev"
MAX_ITEMS = 20          # 한 런에 보낼 알림 상한(최신 것부터) — 몰려도 폰을 도배하지 않게
TTL = 3600              # 기기가 꺼져 있으면 1시간까지 푸시 서비스가 들고 있다가 버린다(낡은 시세 알림은 의미 없음)
KST = datetime.timezone(datetime.timedelta(hours=9))


def load_queue(path=None):
    """큐 파일을 읽는다. 없거나 깨졌거나 비면 []. 제목·본문이 다 빈 항목은 버린다."""
    try:
        with open(path or QUEUE, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        print(f"[push] 큐 파일을 읽지 못함 — 건너뜀: {e}")
        return []
    if isinstance(raw, dict):
        raw = raw.get("items", [])
    items = [x for x in raw if isinstance(x, dict) and (x.get("title") or x.get("body"))] if isinstance(raw, list) else []
    return items[-MAX_ITEMS:]


def clear_queue(path=None):
    try:
        os.remove(path or QUEUE)
    except FileNotFoundError:
        pass


def in_quiet(quiet, now=None):
    """조용한 시간(한국 시각 {from:'22:00', to:'07:00'}) 안이면 True. 자정을 넘는 구간도 된다."""
    if not isinstance(quiet, dict):
        return False
    a, b = str(quiet.get("from") or ""), str(quiet.get("to") or "")
    if len(a) != 5 or len(b) != 5 or a == b:
        return False
    t = (now or datetime.datetime.now(KST)).astimezone(KST).strftime("%H:%M")
    return a <= t < b if a < b else (t >= a or t < b)


def payload(item):
    """서비스 워커(app/public/sw.js)가 읽는 모양. 푸시 내용 상한(약 4KB) 안으로 자른다."""
    return json.dumps({
        "id": str(item.get("id") or "")[:64],
        "title": str(item.get("title") or "")[:120],
        "body": str(item.get("body") or "")[:400],
        "url": str(item.get("url") or "")[:300],
        "ts": item.get("ts"),
    }, ensure_ascii=False)


def send_all(items, subs, private_key, subject, push=None):
    """모든 구독 × 모든 알림. 반환 (성공 수, 실패 수, 사라진 endpoint 목록)."""
    if push is None:
        from pywebpush import webpush as push       # 실행 때만 — 테스트는 가짜를 넘긴다
    ok = fail = 0
    gone = []
    for s in subs:
        ep = s.get("endpoint", "")
        for item in items:
            try:
                # vapid_claims 는 호출마다 새 딕셔너리 — pywebpush 가 aud(푸시 서비스 주소)를 채워 넣어 바꾸기 때문에,
                # 같은 것을 돌려 쓰면 첫 기기의 aud 가 다른 회사 푸시 서비스로 가서 403 이 난다.
                push(subscription_info={"endpoint": ep, "keys": s.get("keys") or {}}, data=payload(item),
                     vapid_private_key=private_key, vapid_claims={"sub": subject},
                     ttl=TTL, headers={"Urgency": "high"}, timeout=10)
                ok += 1
            except Exception as e:                    # WebPushException·네트워크 오류 모두 — 한 기기 실패가 나머지를 막지 않게
                code = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
                fail += 1
                if code in (404, 410):
                    gone.append(ep)
                    print(f"[push] 사라진 구독({code}) — 정리 대상: …{ep[-12:]}")
                    break                             # 이 기기엔 남은 알림도 못 간다
                print(f"[push] 발송 실패({code or type(e).__name__}): …{ep[-12:]}")
    return ok, fail, gone


def main():
    items = load_queue()
    if not items:
        print("[push] 보낼 알림 없음")
        return 0
    read_key = os.environ.get("PUSH_READ_KEY", "").strip()
    priv = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    subject = os.environ.get("VAPID_SUBJECT", "").strip()
    if not (read_key and priv and subject):
        print("[push] PUSH_READ_KEY·VAPID_PRIVATE_KEY·VAPID_SUBJECT 중 빠진 것이 있어 건너뜀")
        return 0
    base = os.environ.get("PUSH_WORKER_URL", "").strip().rstrip("/") or WORKER
    hdr = {"X-Push-Read-Key": read_key}
    try:
        r = requests.get(base + "/push/subscriptions", headers=hdr, timeout=15)
        r.raise_for_status()
        doc = r.json()
    except Exception as e:
        print(f"[push] 구독 목록을 못 읽음 — 이번 런은 보내지 않음: {e}")
        return 0
    subs = [s for s in (doc.get("subs") or []) if isinstance(s, dict) and s.get("endpoint")]
    if in_quiet(doc.get("quiet")):
        print(f"[push] 조용한 시간({doc['quiet'].get('from')}~{doc['quiet'].get('to')}) — 알림 {len(items)}건 보내지 않음")
        clear_queue()
        return 0
    if not subs:
        print(f"[push] 구독한 기기 없음 — 알림 {len(items)}건 버림")
        clear_queue()
        return 0
    ok, fail, gone = send_all(items, subs, priv, subject)
    print(f"[push] 기기 {len(subs)}대 × 알림 {len(items)}건 — 성공 {ok} · 실패 {fail}")
    if gone:
        try:
            r = requests.put(base + "/push/prune", headers=hdr, json={"endpoints": gone}, timeout=15)
            r.raise_for_status()
            print(f"[push] 사라진 구독 {r.json().get('removed', 0)}개 정리")
        except Exception as e:
            print(f"[push] 사라진 구독 정리 실패 — 다음 런에 다시 정리된다: {e}")
    clear_queue()
    return 0


if __name__ == "__main__":
    sys.exit(main())
