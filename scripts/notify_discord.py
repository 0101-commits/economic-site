#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""디스코드 웹훅 발송 공용 모듈 — 카카오와 병행(채널 이중화, 카카오 무음 폴백의 근본 해결).

DISCORD_WEBHOOK_URL 시크릿(웹훅 URL) 하나면 그 채널 구독자 전원에게 도달한다.
미설정이면 조용히 no-op(False) — 카카오 단독 구성도 그대로 동작. 실패는 경고만,
호출측(digest/alerts/swings)의 카카오 경로에 절대 영향을 주지 않는다.
한도: content 2000자(넘으면 자름), 웹훅당 2초에 5요청 — 본 파이프라인 발송량과 무관.
"""
import os
import json
import uuid
import urllib.request

WEBHOOK_ENV = "DISCORD_WEBHOOK_URL"
# 디스코드(Cloudflare)가 파이썬 기본 UA(Python-urllib)를 403 으로 차단한다 — 반드시 지정.
_UA = "economic-site-notifier/1.0 (+https://github.com/0101-commits/economic-site)"


def send(text, png=None, filename="chart.png"):
    """텍스트(+선택 PNG 첨부) 발송. 성공 True / 미설정·실패 False."""
    url = os.environ.get(WEBHOOK_ENV, "").strip()
    if not url:
        return False
    content = (text or "")[:2000]
    try:
        if png:
            b = uuid.uuid4().hex
            head = (f'--{b}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
                    f'Content-Type: application/json\r\n\r\n'
                    + json.dumps({"content": content}, ensure_ascii=False) + "\r\n"
                    + f'--{b}\r\nContent-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'
                    f'Content-Type: image/png\r\n\r\n').encode("utf-8")
            body = head + png + f"\r\n--{b}--\r\n".encode("utf-8")
            req = urllib.request.Request(url, data=body,
                                         headers={"Content-Type": f"multipart/form-data; boundary={b}",
                                                  "User-Agent": _UA})
        else:
            req = urllib.request.Request(url, data=json.dumps({"content": content}, ensure_ascii=False).encode("utf-8"),
                                         headers={"Content-Type": "application/json", "User-Agent": _UA})
        urllib.request.urlopen(req, timeout=20)
        print(f"[discord] 발송 성공 ({len(content)}자{', 이미지 첨부' if png else ''})")
        return True
    except Exception as e:
        print(f"::warning title=Discord 발송 실패::{type(e).__name__}: {e} — 카카오 경로는 영향 없음")
        return False
