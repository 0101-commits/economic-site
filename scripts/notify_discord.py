#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""디스코드 웹훅 발송 공용 모듈 — 카카오와 병행(채널 이중화, 카카오 무음 폴백의 근본 해결).

채널 구조(2026-08-05 D5): 발송처별 전용 웹훅 env 를 쓰고, 없으면 기본(DISCORD_WEBHOOK_URL
= #시황-다이제스트)으로 폴백한다 — 시크릿 일부만 등록해도 동작.
  DISCORD_WEBHOOK_URL     #시황-다이제스트 (digest)
  DISCORD_WEBHOOK_ALERTS  #종목-알림     (check_alerts)
  DISCORD_WEBHOOK_SWINGS  #급변-속보     (check_swings·check_halts)
  DISCORD_WEBHOOK_SYSTEM  #시스템        (파이프라인 경고 — system())
미설정이면 조용히 no-op(False). 실패는 경고만 — 호출측 카카오 경로에 절대 영향 없음.
한도: description 4096자/content 2000자(넘으면 자름), 웹훅당 2초에 5요청.
"""
import os
import json
import uuid
import datetime
import urllib.request

WEBHOOK_ENV = "DISCORD_WEBHOOK_URL"
# 디스코드(Cloudflare)가 파이썬 기본 UA(Python-urllib)를 403 으로 차단한다 — 반드시 지정.
_UA = "economic-site-notifier/1.0 (+https://github.com/0101-commits/economic-site)"

# 시맨틱 컬러(D1) — 메시지 글자색은 디스코드가 지원하지 않아(ANSI 코드블록은 모바일 미표시)
# embed 색띠가 표준. 알림 성격별 고정 팔레트:
COLOR_DIGEST = 0x23408E    # 시황 다이제스트 — 네이비
COLOR_WEEKLY = 0xC9A227    # 주간 리포트 — 금색
COLOR_ALERT = 0xE67E22     # 종목 알림 — 주황
COLOR_FIRE = 0xD83C3E      # 급변·서킷 발동 — 빨강
COLOR_RESOLVE = 0x3BA55D   # 경보 해제 — 초록
COLOR_SYSTEM = 0x99AAB5    # 시스템(운영 경고) — 회색
COLOR_TEST = 0x99AAB5      # 테스트 — 회색


def _hook(env):
    """웹훅 URL 결정 — 전용 env 우선, 없으면 기본으로 폴백. BOM(U+FEFF) 방어 포함
    (Windows PowerShell 파이프 등록 시크릿이 'unknown url type: ﻿https' 로 죽던 실측)."""
    for name in ([env, WEBHOOK_ENV] if env and env != WEBHOOK_ENV else [WEBHOOK_ENV]):
        u = os.environ.get(name, "").strip().lstrip("﻿").strip()
        if u:
            return u
    return ""


def send(text, png=None, filename="chart.png", title=None, url=None,
         color=None, fields=None, footer=None, timestamp=False, mention=False,
         env=WEBHOOK_ENV):
    """텍스트(+선택 PNG 첨부) 발송. 성공 True / 미설정·실패 False.

    png 는 bytes 또는 파일 경로(str) — build_slot_chart_png 가 경로를 반환하므로 둘 다 받는다.
    title 을 주면 embed 형식: 제목이 url(대시보드 딥링크)로 하이퍼링크, color=좌측 색띠,
    fields=[(이름, 값, inline)] 2열 그리드(D3), footer=신선도 한 줄(D4), timestamp=수신 시각.
    ⚠ 이미지 클릭은 디스코드 정책상 항상 '확대 보기' — 이동은 제목이 담당.
    mention=True 면 @everyone 을 content 로 동봉(D6) — 개인 알림 설정과 무관하게 푸시.
    title 없으면 종전 그대로 평문(content)."""
    hook = _hook(env)
    if not hook:
        return False
    if title:
        embed = {"title": title[:256], "description": (text or "")[:4096]}
        if url:
            embed["url"] = url                       # 제목 클릭 → 대시보드
        if color is not None:
            embed["color"] = color
        if fields:
            embed["fields"] = [{"name": str(n)[:256], "value": str(v)[:1024], "inline": bool(i)}
                               for n, v, i in fields[:25]]
        if footer:
            embed["footer"] = {"text": str(footer)[:2048]}
        if timestamp:
            embed["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if png:
            embed["image"] = {"url": f"attachment://{filename}"}
        payload = {"embeds": [embed]}
        if mention:
            payload["content"] = "@everyone"
        plen = len(embed["description"]) + len(embed["title"])
    else:
        body_text = ("@everyone " if mention else "") + (text or "")
        payload = {"content": body_text[:2000]}
        plen = len(payload["content"])
    try:
        if isinstance(png, str):
            with open(png, "rb") as f:
                png = f.read()
        if png:
            b = uuid.uuid4().hex
            head = (f'--{b}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
                    f'Content-Type: application/json\r\n\r\n'
                    + json.dumps(payload, ensure_ascii=False) + "\r\n"
                    + f'--{b}\r\nContent-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'
                    f'Content-Type: image/png\r\n\r\n').encode("utf-8")
            body = head + png + f"\r\n--{b}--\r\n".encode("utf-8")
            req = urllib.request.Request(hook, data=body,
                                         headers={"Content-Type": f"multipart/form-data; boundary={b}",
                                                  "User-Agent": _UA})
        else:
            req = urllib.request.Request(hook, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                         headers={"Content-Type": "application/json", "User-Agent": _UA})
        urllib.request.urlopen(req, timeout=20)
        print(f"[discord] 발송 성공 ({plen}자{', 이미지 첨부' if png else ''}{', embed' if title else ''}, env={env})")
        return True
    except Exception as e:
        print(f"::warning title=Discord 발송 실패::{type(e).__name__}: {e} — 카카오 경로는 영향 없음")
        return False


def system(text, title="⚙️ 파이프라인 경고"):
    """운영 경고(D8) — #시스템 채널로. 토큰 만료·수집 실패·스테일 등 '알림이 안 오는 상황'
    자체를 통지한다. 실패·미설정은 조용히 무시(경고 채널이 본 경로를 깨면 본말전도)."""
    try:
        return send(text, title=title, color=COLOR_SYSTEM, timestamp=True,
                    env="DISCORD_WEBHOOK_SYSTEM")
    except Exception:
        return False
