#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""일일 운영 하트비트 (기획안 P6·설계 원칙 10).

왜 만들었나(기획안 D13):
  notify_discord.system 의 주석에는 '데일리 하트비트'가 명시돼 있는데 호출하는 곳이
  한 군데도 없었다. 그래서 알림이 안 오는 상황(수집 중단·토큰 만료)과 조용한 시장이
  구별되지 않았다. 알림 시스템에서 가장 위험한 실패는 시끄러운 실패가 아니라 침묵이다.

무엇을 보내나 — 하루 한 줄:
  data.json 신선도 · dataHealth 요약 · 스테일 항목 수 · 카카오 토큰 잔여 추정.
  정상이면 초록, 문제가 있으면 회색(운영 채널이라 멘션은 하지 않는다).

안전: 실패는 조용히 무시 — 경고 채널이 본 경로를 깨면 본말전도다.
"""
import os
import json
import datetime

KST = datetime.timezone(datetime.timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# data.json 이 이보다 오래됐으면 '수집 지연'으로 본다. 장외·주말엔 시간당 cron 하나뿐이라
# (실측 미발화율 42%) 여유를 둔다 — 여기서 울리는 것은 '몇 시간째 멈췄다' 수준만이다.
STALE_HOURS = 6


def build(now=None):
    """(본문, 정상여부). 파일을 못 읽어도 예외를 내지 않고 그 사실을 본문에 적는다."""
    now = now or datetime.datetime.now(KST)
    parts, ok = [], True

    try:
        with open(os.path.join(ROOT, "data.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return f"data.json 을 읽지 못했습니다 — {type(e).__name__}", False

    try:
        lu = datetime.datetime.fromisoformat(str(data.get("lastUpdated")))
        # 음수(= 데이터가 미래 시각)는 시계 어긋남이지 스테일이 아니다 — 0 으로 눌러 적는다.
        age_h = max((now - lu.astimezone(KST)).total_seconds() / 3600, 0.0)
        parts.append(f"수집 {age_h:.1f}h 전")
        if age_h > STALE_HOURS:
            ok = False
    except (ValueError, TypeError):
        parts.append("수집 시각 불명")
        ok = False

    dh = (data.get("dataHealth") or {}).get("summary") or {}
    if dh:
        tot, good = dh.get("total"), dh.get("ok")
        parts.append(f"항목 {good}/{tot} 정상")
        bad = (dh.get("stale") or 0) + (dh.get("failed") or 0) + (dh.get("missing") or 0)
        if bad:
            parts.append(f"스테일·결측 {bad}")
        if dh.get("failed"):
            ok = False                               # stale 은 흔하지만 failed 는 사건이다
    if (data.get("dataHealth") or {}).get("blocking"):
        parts.append("차단 항목 있음")
        ok = False

    # 알림 경로 자체의 설정 상태 — 시크릿이 빠지면 알림이 통째로 조용해진다.
    missing = [n for n in ("KAKAO_REST_API_KEY", "KAKAO_REFRESH_TOKEN")
               if not os.environ.get(n, "").strip()]
    if missing:
        parts.append("카카오 미설정")
        ok = False
    if not os.environ.get("DISCORD_WEBHOOK_URL", "").strip():
        parts.append("디스코드 웹훅 미설정")
        ok = False

    return " · ".join(parts), ok


def main():
    body, ok = build()
    print(f"[heartbeat] {'정상' if ok else '점검 필요'} — {body}")
    try:
        import notify_discord
        notify_discord.system(
            body,
            title="💚 알림 파이프라인 정상" if ok else "⚙️ 알림 파이프라인 점검 필요",
            color=notify_discord.COLOR_RESOLVE if ok else None)
    except Exception as e:                           # noqa: BLE001
        print(f"[heartbeat] 발송 예외 무시: {e}")


def demo():
    """assert 기반 자가 점검 — python scripts/heartbeat.py --demo."""
    body, ok = build()
    assert isinstance(body, str) and body, body
    assert isinstance(ok, bool)
    # 시크릿이 없는 로컬에서는 '점검 필요'로 나와야 한다 — 침묵을 정상으로 보고하면
    # 이 스크립트의 존재 이유가 사라진다.
    assert not ok, "시크릿 없는 환경에서 정상으로 보고하면 안 된다"
    assert "미설정" in body, body
    print(f"heartbeat.py 자가 점검 통과 — {body}")


if __name__ == "__main__":
    import sys
    if "--demo" in sys.argv:
        demo()
    else:
        main()
