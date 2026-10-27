#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""웹 푸시 발송기 — scripts/push_queue.json 의 알림을 이 사이트를 구독한 기기에 보낸다.

입력  scripts/push_queue.json = [{id, uid, title, body, url, ts}, ...] (check_alerts.py 가 쌓는다). 없거나 비면 종료 0.
구독  Worker GET /push/subscriptions/all (헤더 X-Push-Read-Key) → {users:[{uid, role, quiet, subs}]}. 항목은 uid 의 기기에만,
      uid 없는 옛 항목은 주인에게만. 실패하면 GET /push/subscriptions(주인 한 명)로 물러나 멤버 항목은 안 보낸다.
정리  푸시 서비스가 410·404(구독 사라짐)로 답한 주소는 Worker PUT /push/prune {uid, endpoints} 로 사람별로 지운다.
환경  PUSH_READ_KEY · VAPID_PRIVATE_KEY(base64url 32바이트, scripts/gen_vapid.py) · VAPID_SUBJECT(mailto:…)
      PUSH_WORKER_URL(선택, 기본 운영 Worker).

설정이 빠지면 아무것도 보내지 않고 종료 0 — 알림 워크플로의 다른 스텝을 막지 않는다.
보낸 뒤에는 성공·실패와 관계없이 큐를 비운다(같은 알림이 다음 런에 또 가지 않게).
출력  scripts/push_sent.json = 주인 기기 1대 이상에 실제로 간 큐 id 목록(멤버 항목은 안 적는다). 같은 스텝의 `check_alerts.py --confirm-push` 가
      이것만 「발송됨」으로 확정한다 — 조용한 시간·구독 0대·설정 빠짐으로 안 간 것은 다음 런에 다시 쌓인다.
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
    return items          # 상한은 사람마다 plan_deliveries 가 건다


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


def send_all(items, subs, private_key, subject, push=None, sent=None):
    """모든 구독 × 모든 알림. 반환 (성공 수, 실패 수, 사라진 endpoint 목록). sent(set)를 주면 간 알림 id 를 담는다."""
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
                if sent is not None:
                    sent.add(str(item.get("id") or ""))
            except Exception as e:                    # WebPushException·네트워크 오류 모두 — 한 기기 실패가 나머지를 막지 않게
                code = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
                fail += 1
                if code in (404, 410):
                    gone.append(ep)
                    print(f"[push] 사라진 구독({code}) — 정리 대상: …{ep[-12:]}")
                    break                             # 이 기기엔 남은 알림도 못 간다
                print(f"[push] 발송 실패({code or type(e).__name__}): …{ep[-12:]}")
    return ok, fail, gone


def plan_deliveries(items, users, owner_uid):
    """큐 항목을 사람별로 나눈다. 반환 ({uid: [항목…]}, 대상 없어 버린 건수).
    uid 없는 항목은 주인에게만. 목록에 없는 uid(삭제·멈춘 멤버)는 버린다. 같은 (uid, id)는 한 번만.
    조용한 시간엔 그 사람 설정으로 pierceQuiet 만 통과. 상한(MAX_ITEMS)은 사람마다 — 최신 것부터."""
    by_uid = {u["uid"]: u for u in users}
    per, seen, dropped = {}, set(), 0
    for it in items:
        uid = it.get("uid") or owner_uid
        if not uid or uid not in by_uid:
            dropped += 1
            continue
        iid = str(it.get("id") or "")
        if iid:
            if (uid, iid) in seen:
                continue
            seen.add((uid, iid))
        per.setdefault(uid, []).append(it)
    for uid in list(per):
        q = by_uid[uid].get("quiet")
        if in_quiet(q):
            per[uid] = [i for i in per[uid] if i.get("pierceQuiet")]
        per[uid] = per[uid][-MAX_ITEMS:]
        if not per[uid]:
            del per[uid]
    return per, dropped


def _fetch_users(base, hdr):
    """(users, owner_uid, 모든 사람 목록을 읽었나). /all 이 실패하면 옛 주인 한 명 경로로 물러난다."""
    try:
        r = requests.get(base + "/push/subscriptions/all", headers=hdr, timeout=15)
        r.raise_for_status()
        raw = r.json().get("users")
        users = [u for u in raw if isinstance(u, dict) and u.get("uid")] if isinstance(raw, list) else []
        owner = next((u["uid"] for u in users if u.get("role") == "owner"), None)
        return users, owner, True
    except Exception as e:
        print(f"[push] 사람별 구독 목록을 못 읽음 — 주인 한 명 경로로 시도: {type(e).__name__}")
    try:
        r = requests.get(base + "/push/subscriptions", headers=hdr, timeout=15)
        r.raise_for_status()
        doc = r.json()
    except Exception as e:
        print(f"[push] 구독 목록을 못 읽음 — 이번 런은 보내지 않음: {e}")
        return None, None, False
    # 이 경로는 주인 공간 하나뿐 — uid 를 모르면 uid 없는 항목만 주인 것으로 본다(멤버 항목은 절대 안 보낸다).
    owner = doc.get("uid") if isinstance(doc.get("uid"), str) and doc.get("uid") else "__owner__"
    return [{"uid": owner, "role": "owner", "quiet": doc.get("quiet"), "subs": doc.get("subs") or [],
             "_legacy": owner == "__owner__"}], owner, False


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
    users, owner_uid, _full = _fetch_users(base, hdr)
    if users is None:
        return 0
    per, dropped = plan_deliveries(items, users, owner_uid)
    if dropped:
        print(f"[push] 받을 사람이 없는 알림 {dropped}건 버림")
    quiet_cut = len(items) - dropped - sum(len(v) for v in per.values())
    if quiet_cut > 0:
        print(f"[push] 조용한 시간·중복·상한으로 알림 {quiet_cut}건 보내지 않음")
    sent = set()                                      # 주인 항목 id 만 — 멤버 정보는 파일에 안 남긴다
    members = member_items = 0
    gone_by = {}
    for u in users:
        uid = u["uid"]
        mine = per.get(uid)
        if not mine:
            continue
        is_owner = uid == owner_uid
        subs = [s for s in (u.get("subs") or []) if isinstance(s, dict) and s.get("endpoint")]
        if not is_owner:
            members += 1
            member_items += len(mine)
        if not subs:
            if is_owner:
                print(f"[push] 구독한 기기 없음 — 알림 {len(mine)}건 버림")
            continue
        ok, fail, gone = send_all(items=mine, subs=subs, private_key=priv, subject=subject, sent=sent if is_owner else None)
        if is_owner:
            print(f"[push] 기기 {len(subs)}대 × 알림 {len(mine)}건 — 성공 {ok} · 실패 {fail}")
        if gone:
            gone_by[uid] = (gone, is_owner and u.get("_legacy"))
    if members:
        print(f"[push] 멤버 {members}명 · {member_items}건")
    try:                                              # 확정 재료 — 못 쓰면 다음 런이 다시 쌓는다(중복 쪽으로 실패)
        with open(os.path.join(os.path.dirname(QUEUE), "push_sent.json"), "w", encoding="utf-8") as f:
            json.dump(sorted(sent), f)
    except OSError as e:
        print(f"[push] 보낸 목록 기록 실패: {type(e).__name__}")
    for uid, (gone, legacy) in gone_by.items():
        try:
            body = {"endpoints": gone} if legacy else {"uid": uid, "endpoints": gone}
            r = requests.put(base + "/push/prune", headers=hdr, json=body, timeout=15)
            r.raise_for_status()
            print(f"[push] 사라진 구독 {r.json().get('removed', 0)}개 정리")
        except Exception as e:
            print(f"[push] 사라진 구독 정리 실패 — 다음 런에 다시 정리된다: {type(e).__name__}")
    clear_queue()
    return 0


if __name__ == "__main__":
    sys.exit(main())
