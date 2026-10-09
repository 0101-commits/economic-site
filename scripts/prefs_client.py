#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Worker /prefs 읽기 — 새 화면(app/)에서 만든 알림 조건을 알림 파이프라인이 받는 창구.

인증: 환경변수 PUSH_READ_KEY(발송기 읽기 키) → 헤더 X-Push-Read-Key. Worker 가 지금 유효한 동기화 키 공간을 읽기 전용으로
     내준다 — CI 가 동기화 키를 갖지 않게(B6). PUSH_READ_KEY 가 없을 때만 ALERTS_SYNC_KEY → SHA-256 hex →
     X-Sync-Key-Hash(전환기 호환, Worker _verifySyncKey 와 같은 규칙 — 앞뒤 공백은 잘라서 해시). key 인자를 주면 그것이 동기화 키다.
실패(키 없음·네트워크·401·429·503·JSON 아님)는 None 과 로그 한 줄. 예외를 밖으로 내지 않는다.
키와 해시는 어떤 형태로도 로그에 찍지 않는다 — 둘 다 그 자체로 인증을 통과하는 값이다.
"""
import hashlib
import json
import os
import urllib.error
import urllib.request

TIMEOUT = 10


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """리다이렉트를 따라가지 않는다 — urllib 은 따라갈 때 인증 헤더를 새 주소(다른 호스트일 수 있다)로
    그대로 넘긴다. 읽기 키도 해시도 그 자체로 인증을 통과하는 값이라, 3xx 는 실패로 끝낸다."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _log(msg):
    print(f"[prefs] {msg}")


def auth_header(key=None):
    """(헤더 이름, 값) 또는 None — PUSH_READ_KEY 우선, 없으면 동기화 키의 해시."""
    read = os.environ.get("PUSH_READ_KEY", "").strip()
    if key is None and read:
        return "X-Push-Read-Key", read
    key = (key if key is not None else os.environ.get("ALERTS_SYNC_KEY", "")).strip()
    return ("X-Sync-Key-Hash", hashlib.sha256(key.encode("utf-8")).hexdigest()) if key else None


def fetch(base_url, key=None):
    """GET {base_url}/prefs → 문서(dict) 또는 None."""
    auth = auth_header(key)
    if not auth:
        _log("PUSH_READ_KEY · ALERTS_SYNC_KEY 없음 — 새 화면 조건을 건너뜁니다")
        return None
    req = urllib.request.Request(
        base_url.rstrip("/") + "/prefs",
        headers={auth[0]: auth[1], "Accept": "application/json", "User-Agent": "econ-alerts/1"})
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            doc = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _log(f"조건을 받지 못함 — HTTP {e.code}")
        return None
    except Exception as e:                                    # noqa: BLE001 — 네트워크·JSON 전부 같은 처리
        _log(f"조건을 받지 못함 — {type(e).__name__}")
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("alerts"), list):
        _log("조건 문서 모양이 다름 — 건너뜁니다")
        return None
    return doc
