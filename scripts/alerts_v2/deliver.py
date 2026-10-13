"""발송 — Send 하나를 푸시 · 카톡으로 보내고 원장 행 `sent` 를 갱신한다(기획서 8장 ⑤).

폰 알림 경로 고정(2026-10-13 사용자 지시): 경제 알림 = 웹앱 푸시(울림) + 카톡. **디스코드에는 보내지 않는다**
(운영 경고 #시스템만 notify_discord.system 으로 무음).
푸시: scripts/push_queue.json 에 덧붙임(같은 잡의 send_push.py 가 보내고 지운다 — 현행 경로).
카톡: send_kakao_digest.send_card 단일 진입점. 친구 모드면 편성(schedule)이 고른 것만 친구에게(울림), 아니면
      (KAKAO_FRIENDS=0 · 친구 0명) **메모(나에게 보내기)로 전부 보낸다** — 조용한 시간 보류분까지. 카카오 정책상
      소리는 안 나고 「나와의 채팅」에 쌓인다(울림은 푸시가 맡는다).
      카드 PNG 는 cards.event_card_png(물결 B3) — 없으면 send_card 가 텍스트로 내려가며 경고를 남긴다.
두 채널은 서로 독립 — 하나가 실패해도 나머지는 보내고, 결과는 각각 sent 에 적는다.
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
            "level": s.level, "requireInteraction": s.level == "alarm",
            "pierceQuiet": s.level == "alarm"}   # 조용한 시간에 나간 경보 = 「경보는 조용한 시간에도 울리기」(편성이 이미 골랐다)


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
        log("[v2] 카톡 메모 모드(나에게 보내기 · 소리 없음) — 알림을 전부 메모로 남김")
    _KAKAO_SESSION = {"token": token, "uuids": uuids, "kakao": kakao}
    return _KAKAO_SESSION


def kakao_rings(log=print) -> bool:
    """카톡이 실제로 울리는가 — 친구 모드로 받을 친구가 있을 때만(메모 = 나에게 보내기는 소리가 안 난다)."""
    ses = _kakao_session(log)
    return bool(ses) and bool(ses["uuids"])


def memo_mode(log=print) -> bool:
    """친구 모드가 아니라 메모로 보내는 중인가 — 그렇다면 편성과 무관하게 모든 알림을 메모로 남긴다."""
    ses = _kakao_session(log)
    return bool(ses) and not ses["uuids"]


# 버튼 글자 = 그 화면 이름(기획서 5장 「[그 화면 8자][받은 알림]」). 종전엔 제목 첫 낱말 5자를 잘라 「USD/K 보기」 ·
# 「10/9~ 보기」가 됐다. 주소(사전 url)의 화면 → 이름 한 표.
SCREEN_LABELS = (("#/market?a=flow", "수급 보기"), ("#/market?a=macro", "경제 달력"), ("#/market?a=kr", "국내 증시"),
                 ("#/market?a=realestate", "부동산"), ("#/market?a=commod", "원자재"), ("#/lens", "렌즈 보기"),
                 ("#/alerts", "받은 알림"))


def screen_label(row: dict, ctx=None) -> str:
    url = str(row.get("url") or "")
    if url in ("#/", "#", ""):
        return "홈 보기"
    for prefix, lab in SCREEN_LABELS:
        if url.startswith(prefix):
            return lab
    if url.startswith("#/i/"):
        reg = getattr(ctx, "registry", None) or {}
        short = str((reg.get(url[4:]) or {}).get("short") or "")
        return f"{short} 보기" if short and len(short) <= 5 else "지표 보기"
    return "화면 보기"


def kakao_parts(s: Send, ctx=None) -> dict:
    """카톡 한 통 — 카드(숫자 · 차트 · 칸)와 글(제목 · 왜 · 다음)이 겹치지 않게 나눈다(2026-10-11 「그림과 텍스트 중복」).
    숫자 사건 = 카드 + 제목 + 설명 2줄(왜 · 다음), 행 없음(값은 카드 큰 숫자 · 제목이 이미 말한다).
    글자 사건(공시 · 메르 새 글 · 휴장 · 일정 · 입장 · 국면) · 묶음 = 사진 없는 피드(제목 + 설명) — 큰 숫자 자리에
    「3」 · 「잠정실적」이 박히던 카드를 안 만든다."""
    from .cards import photo_worthy
    r = s.row
    btn = [(screen_label(r, ctx)[:8], abs_url(r.get("url", "#/alerts"))), ("받은 알림", abs_url("#/alerts"))]
    if s.kind == "bundle":
        lines = [str(b.get("title") or "") for b in s.bundle[:3]]
        more = len(s.bundle) - len(lines)
        return {"title": r["title"], "caption": "\n".join(lines + ([f"외 {more}건"] if more > 0 else [])),
                "items": [], "buttons": btn[1:], "link_url": abs_url("#/alerts"), "photo": False,
                "kind": f"알림 v2 {LEVEL_KO.get(s.level, s.level)}"}
    btn = btn if btn[0][0] != "받은 알림" else btn[1:]
    return {"title": r["title"], "caption": "\n".join(x for x in (r.get("why"), r.get("next")) if x),
            "items": [], "buttons": btn, "link_url": abs_url(r.get("url", "#/alerts")), "photo": photo_worthy(r),
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
    p = kakao_parts(s, ctx)
    png = _card_png(s, ctx) if p["photo"] else None
    try:
        return bool(ses["kakao"].send_card(ses["token"], p["title"], p["caption"], png=png, uuids=ses["uuids"],
                                           buttons=p["buttons"], items=p["items"], kind=p["kind"],
                                           link_url=p["link_url"], photo=p["photo"]))
    except (Exception, SystemExit) as e:                     # noqa: BLE001
        log(f"[v2] 카톡 발송 예외: {type(e).__name__}")
        _kakao_down(log)
        return False


# ---------- 한 통 ----------
def send(s: Send, ledger, ctx, log=print, queue_path: str = PUSH_QUEUE_PATH) -> dict:
    """두 채널 독립 발송 → 원장 sent 갱신. 돌려주는 값 = {push, kakao, memo}.
    푸시(울리는 채널)가 먼저, 카톡(느릴 수 있는 채널)은 마지막. 메모로 나간 것은 kakao 가 아니라 memo 로 적는다 —
    하루 상한 · 카톡 쿼터(schedule._ring_count_today · _kakao_count_today)와 앱 「오늘 N/20통」은 kakao 만 센다."""
    res = {"push": 0, "kakao": False, "memo": False}
    memo = memo_mode(log)
    if s.held:
        if memo:                                                         # 조용한 시간 — 무음 메모로만 남긴다
            res["memo"] = send_kakao(s, ctx, log)
        ledger.update_sent(s.row["key"], held=True, memo=res["memo"])
        log(f"[v2 send] {s} → 보류(조용한 시간 · 푸시는 아침 브리핑 합류) · memo {res['memo']}")
        return res
    if s.push:
        res["push"] = 1 if enqueue_push([push_item(s)], queue_path) else 0
    if s.kakao or memo:
        res["memo" if memo else "kakao"] = send_kakao(s, ctx, log)
    if s.kind == "bundle":
        for b in s.bundle:
            ledger.update_sent(b["key"], bundled=True, **res)
        if ledger.get(s.row["key"]) is None:
            ledger.append(dict(s.row, sent={**res, "bundled": False, "held": False}))
    else:
        ledger.update_sent(s.row["key"], **res)
    log(f"[v2 send] {s} → push {res['push']} · kakao {res['kakao']} · memo {res['memo']}")
    return res


def held_rows(ledger) -> list[dict]:
    """조용한 시간에 보류된 행 — 아침 브리핑 「밤사이 알림 N건」 재료."""
    return [r for r in ledger.rows if (r.get("sent") or {}).get("held") and not (r.get("sent") or {}).get("push")]
