"""발송 — Send 하나를 푸시 · 카톡 · 디스코드로 보내고 원장 행 `sent` 를 갱신한다(기획서 8장 ⑤).

푸시: scripts/push_queue.json 에 덧붙임(같은 잡의 send_push.py 가 보내고 지운다 — 현행 경로).
카톡: send_kakao_digest.send_card 단일 진입점. 친구 모드면 편성(schedule)이 고른 것만 친구에게(울림), 아니면
      (KAKAO_FRIENDS=0 · 친구 0명) **메모(나에게 보내기)로 디스코드에 가는 것을 전부 따라 보낸다** — 카카오 정책상
      소리는 안 나지만 「나와의 채팅」에 쌓인다(2026-10-07 사용자 결정: v2 가 카톡을 통째로 끄자 「안 온다」가 됐다).
      카드 PNG 는 cards.event_card_png(물결 B3) — 없으면 send_card 가 텍스트로 내려가며 경고를 남긴다.
디스코드: notify_discord.send_level(등급 → 채널 · 멘션).
세 채널은 서로 독립 — 하나가 실패해도 나머지는 보내고, 결과는 각각 sent 에 적는다.
"""
from __future__ import annotations

import json
import os
import sys

from .model import Send

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
APP_URL = os.environ.get("APP_URL", "https://0101-commits.github.io/economic-site/")
PUSH_QUEUE_PATH = os.path.join(SCRIPTS, "push_queue.json")
LEVEL_KO = {"alarm": "경보", "alert": "알림", "notice": "안내"}
_KAKAO_SESSION: dict | None = None     # 런 안에서 토큰 · 수신자 한 번만


def abs_url(path: str) -> str:
    return path if path.startswith("http") else APP_URL + path.lstrip("/")


# ---------- 푸시 ----------
def enqueue_push(items: list[dict], path: str = PUSH_QUEUE_PATH) -> bool:
    q = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                q = json.load(f)
        except (OSError, ValueError):
            q = []
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump((q if isinstance(q, list) else []) + items, f, ensure_ascii=False)
        return True
    except OSError as e:
        print(f"[v2] 푸시 큐 기록 실패: {type(e).__name__}")
        return False


def push_item(s: Send) -> dict:
    r = s.row
    return {"id": r["key"], "title": r["title"], "body": r.get("why", "") + ("\n" + r["next"] if r.get("next") else ""),
            "url": abs_url(r.get("url", "#/alerts")), "ts": r.get("ts"),
            "level": s.level, "requireInteraction": s.level == "alarm"}


# ---------- 카톡 ----------
def _kakao_session(log=print) -> dict | None:
    """토큰 + 수신자. uuids = 친구(친구 모드) 또는 None(메모 = 나에게 보내기). 시크릿 · 토큰이 없으면 None."""
    global _KAKAO_SESSION
    if _KAKAO_SESSION is not None:
        return _KAKAO_SESSION or None
    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if not rest_key or not refresh:
        log("[v2] 카톡 시크릿 없음 — 카톡 발송 건너뜀")
        _KAKAO_SESSION = {}
        return None
    try:
        import send_kakao_digest as kakao
        token = kakao.refresh_access_token(rest_key, refresh)
        friends = kakao.get_friends(token) if kakao._friends_enabled() else []
    except (Exception, SystemExit) as e:                     # noqa: BLE001 — 토큰 사망은 SystemExit 로 온다
        log(f"[v2] 카톡 준비 실패: {type(e).__name__} {str(e)[:160]}")
        _KAKAO_SESSION = {}
        return None
    uuids = [f["uuid"] for f in friends if isinstance(f, dict) and f.get("uuid")] or None
    if uuids is None:
        if kakao._friends_enabled():                         # 켜 놓고 친구 0명(200 + 빈 목록)은 get_friends 가 경고를 안 낸다
            print("::warning title=카톡 친구 0명::KAKAO_FRIENDS=1 인데 받을 친구가 없어 메모(소리 없음)로 보냄 — docs/KAKAO_SETUP.md ⑤")
        log("[v2] 카톡 메모 모드(나에게 보내기 · 소리 없음) — 디스코드로 가는 것을 따라 보냄")
    _KAKAO_SESSION = {"token": token, "uuids": uuids, "kakao": kakao}
    return _KAKAO_SESSION


def memo_mode(log=print) -> bool:
    """친구 모드가 아니라 메모로 보내는 중인가 — 그렇다면 디스코드로 가는 것을 카톡도 따라간다."""
    ses = _kakao_session(log)
    return bool(ses) and not ses["uuids"]


def kakao_parts(s: Send) -> dict:
    """카톡 한 통 — 제목 · 설명 2줄 · 행 ≤3 · 버튼 2(8자) · 사진 링크."""
    r = s.row
    name = (r.get("title") or "").split(" ·")[0].split(" ")[0][:5] or "화면"
    items = []
    if r.get("value") not in (None, ""):
        items.append({"item": "값", "item_op": str(r["value"])})
    if s.kind == "bundle":
        for b in s.bundle[:3]:
            items.append({"item": (b.get("title") or "")[:6], "item_op": (b.get("title") or "")[6:20]})
    btn = [(f"{name} 보기"[:8], abs_url(r.get("url", "#/alerts"))), ("받은 알림", abs_url("#/alerts"))]
    return {"title": r["title"], "caption": "\n".join(x for x in (r.get("why"), r.get("next")) if x),
            "items": items[:5], "buttons": btn, "link_url": abs_url(r.get("url", "#/alerts")),
            "kind": f"알림 v2 {LEVEL_KO.get(s.level, s.level)}"}


def _card_png(s: Send, ctx) -> bytes | None:
    try:
        from . import cards
    except ImportError:
        return None
    try:
        return cards.event_card_png(s.row, ctx) if s.kind != "bundle" else cards.bundle_card_png(s.bundle, ctx)
    except Exception as e:                                   # noqa: BLE001
        print(f"[v2] 카드 렌더 실패: {type(e).__name__}")
        return None


def _kakao_down(log=print) -> None:
    """한 통이 실패하면 그 런의 나머지 카톡은 건너뛴다 — 카카오가 시간을 끌면 한 통에 수 분이라 잡 시한을 넘긴다."""
    global _KAKAO_SESSION
    _KAKAO_SESSION = {}
    log("[v2] 카톡 실패 — 이 런의 나머지 카톡은 건너뜀")


def send_kakao(s: Send, ctx, log=print) -> bool:
    ses = _kakao_session(log)
    if not ses:
        return False
    p = kakao_parts(s)
    png = _card_png(s, ctx)
    try:
        return bool(ses["kakao"].send_card(ses["token"], p["title"], p["caption"], png=png, uuids=ses["uuids"],
                                           buttons=p["buttons"], items=p["items"], kind=p["kind"],
                                           link_url=p["link_url"]))
    except (Exception, SystemExit) as e:                     # noqa: BLE001
        log(f"[v2] 카톡 발송 예외: {type(e).__name__}")
        _kakao_down(log)
        return False


# ---------- 디스코드 ----------
def send_discord(s: Send, log=print) -> bool:
    r = s.row
    try:
        import notify_discord
    except ImportError:
        return False
    fields = []
    if r.get("value") not in (None, ""):
        fields.append(("값", str(r["value"]), True))
    fields.append(("등급", LEVEL_KO.get(s.level, s.level), True))
    if r.get("asOf"):
        fields.append(("기준", f"{r['asOf']} · {r.get('fresh', '')}".strip(" ·"), True))
    body = "\n".join(x for x in (r.get("why"), r.get("next")) if x)
    if s.kind == "bundle":
        body = "\n".join(f"· {b.get('title')}" for b in s.bundle[:6]) + (f"\n+{len(s.bundle) - 6}" if len(s.bundle) > 6 else "")
    try:
        return bool(notify_discord.send_level(s.level, r["title"], body, fields=fields, url=abs_url(r.get("url", "#/alerts")),
                                              footer=f"알림 사전 {r.get('event')} · {r.get('key')}"))
    except Exception as e:                                   # noqa: BLE001
        log(f"[v2] 디스코드 발송 예외: {type(e).__name__}")
        return False


# ---------- 한 통 ----------
def send(s: Send, ledger, ctx, log=print, queue_path: str = PUSH_QUEUE_PATH) -> dict:
    """세 채널 독립 발송 → 원장 sent 갱신. 돌려주는 값 = {push, kakao, discord, memo}.
    디스코드(울리는 채널)가 먼저, 카톡(느릴 수 있는 채널)은 마지막. 메모로 나간 것은 kakao 가 아니라 memo 로 적는다 —
    하루 상한 · 카톡 쿼터(schedule._ring_count_today · _kakao_count_today)와 앱 「오늘 N/20통」은 kakao 만 센다."""
    res = {"push": 0, "kakao": False, "discord": False, "memo": False}
    if s.held:
        res["discord"] = send_discord(s, log)
        ledger.update_sent(s.row["key"], held=True, discord=res["discord"])
        return res
    if s.push:
        res["push"] = 1 if enqueue_push([push_item(s)], queue_path) else 0
    if s.discord:
        res["discord"] = send_discord(s, log)
    if s.kakao or (s.discord and memo_mode(log)):
        res["memo" if memo_mode(log) else "kakao"] = send_kakao(s, ctx, log)
    if s.kind == "bundle":
        for b in s.bundle:
            ledger.update_sent(b["key"], bundled=True, push=res["push"], kakao=res["kakao"], discord=res["discord"],
                               memo=res["memo"])
        if ledger.get(s.row["key"]) is None:
            ledger.append(dict(s.row, sent={**res, "bundled": False, "held": False}))
    else:
        ledger.update_sent(s.row["key"], **res)
    log(f"[v2 send] {s} → push {res['push']} · kakao {res['kakao']} · memo {res['memo']} · discord {res['discord']}")
    return res


def held_rows(ledger) -> list[dict]:
    """조용한 시간에 보류된 행 — 아침 브리핑 「밤사이 알림 N건」 재료."""
    return [r for r in ledger.rows if (r.get("sent") or {}).get("held") and not (r.get("sent") or {}).get("push")]
