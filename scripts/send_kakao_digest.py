#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""매일 10/15/18시(KST) data.json 시황 요약을 카카오톡 '나에게 보내기'로 발송한다.

필요한 GitHub Secrets:
  KAKAO_REST_API_KEY   — 카카오 개발자 앱의 REST API 키
  KAKAO_REFRESH_TOKEN  — talk_message 동의로 발급한 refresh_token

동작:
  1) refresh_token 으로 access_token 재발급 (매 실행마다 신선한 토큰 확보)
  2) data.json 을 읽어 한국어 요약문 작성
     (카카오 기본 '텍스트' 템플릿의 text 는 최대 200자 → 핵심 지표만 간결히, 상세는 대시보드 링크)
  3) POST kapi.kakao.com/v2/api/talk/memo/default/send 로 본인 카톡(나와의 채팅)에 발송

설정 방법(1회): cloudflare-worker/README 가 아니라 저장소 루트 KAKAO_SETUP.md 참고.
표준 라이브러리만 사용 — pip 설치 불필요.
"""
import os
import sys
import json
import datetime
import urllib.parse
import urllib.request
import urllib.error

DASHBOARD_URL = "https://0101-commits.github.io/economic-site/"
KST = datetime.timezone(datetime.timedelta(hours=9))
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.json")
TEXT_LIMIT = 200  # 카카오 텍스트 템플릿 text 최대 길이


def _http_post(url, form, headers=None):
    body = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return e.code, {}


def refresh_access_token(rest_key, refresh_token):
    """refresh_token 으로 access_token 을 재발급한다."""
    status, j = _http_post("https://kauth.kakao.com/oauth/token", {
        "grant_type": "refresh_token",
        "client_id": rest_key,
        "refresh_token": refresh_token,
    })
    if status != 200 or not j.get("access_token"):
        raise SystemExit(f"[kakao] access_token 재발급 실패: HTTP {status} {j}")
    # refresh_token 유효기간이 1개월 미만이면 카카오가 새 토큰을 함께 준다 → 시크릿 교체 안내.
    if j.get("refresh_token"):
        print("::warning title=KAKAO_REFRESH_TOKEN::카카오가 새 refresh_token 을 발급했습니다. "
              "GitHub Secret 의 KAKAO_REFRESH_TOKEN 을 새 값으로 교체하세요(로그에는 마스킹됨).")
        print(f"::add-mask::{j['refresh_token']}")
    return j["access_token"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _arrow(c):
    c = _f(c)
    if c is None:
        return ""
    return f"▲{c:.2f}%" if c >= 0 else f"▼{abs(c):.2f}%"


def _num(v, nd=0):
    v = _f(v)
    return "-" if v is None else f"{v:,.{nd}f}"


def _fg_label(v):
    v = _f(v)
    if v is None:
        return ""
    return ("극도공포" if v < 25 else "공포" if v < 45 else
            "중립" if v < 55 else "탐욕" if v < 75 else "극도탐욕")


def build_summary(d):
    """data.json → 카카오 발송용 한국어 요약문(200자 이내)."""
    idx = d.get("indices", {}) or {}
    fx = d.get("fx", {}) or {}
    com = d.get("commodities", {}) or {}
    sent = d.get("sentiment", {}) or {}
    ei = d.get("economicIndicators", {}) or {}
    us = ei.get("us", {}) or {}

    now = datetime.datetime.now(KST)
    wd = "월화수목금토일"[now.weekday()]
    # 발송 시각(KST)에 맞춰 제목을 바꾼다 — 10시=아침 / 15시=오후 / 18시=마감.
    # (스케줄 지연을 감안해 시각 경계는 넉넉히 잡는다.)
    if now.hour < 12:
        slot = "아침 시황"
    elif now.hour < 17:
        slot = "오후 시황"
    else:
        slot = "마감 시황"
    lines = [f"\U0001F4CA {now.month}/{now.day}({wd}) {slot}"]

    def idx_part(label, key):
        o = idx.get(key)
        if not o or o.get("price") is None:
            return None
        return f"{label} {_num(o['price'], 2)}({_arrow(o.get('change'))})"

    dom = [p for p in (idx_part("코스피", "KOSPI"), idx_part("코스닥", "KOSDAQ")) if p]
    if dom:
        lines.append(" ".join(dom))
    ovs = [p for p in (idx_part("S&P", "SP500"), idx_part("나스닥", "NASDAQ")) if p]
    if ovs:
        lines.append(" ".join(ovs))

    # 환율 (USD/KRW, 100엔/원). JPYKRW 가 1엔당(≈9.4)이면 ×100, 이미 100엔당이면 그대로.
    fxl = []
    u = fx.get("USDKRW")
    if u and u.get("rate") is not None:
        fxl.append(f"달러 {_num(u['rate'], 2)}({_arrow(u.get('change'))})")
    jp = fx.get("JPYKRW")
    if jp and jp.get("rate") is not None:
        jr = _f(jp["rate"])
        if jr is not None:
            fxl.append(f"100엔 {_num(jr * 100 if jr < 50 else jr, 2)}")
    if fxl:
        lines.append(" ".join(fxl))

    # 원자재 (WTI, 금)
    cl = []
    w = com.get("WTI")
    if w and w.get("price") is not None:
        cl.append(f"WTI ${_num(w['price'], 2)}({_arrow(w.get('change'))})")
    g = com.get("Gold")
    if g and g.get("price") is not None:
        cl.append(f"금 ${_num(g['price'], 0)}({_arrow(g.get('change'))})")
    if cl:
        lines.append(" ".join(cl))

    # 시장심리 (공포탐욕, VIX)
    pl = []
    fg = sent.get("fear_greed")
    if fg and fg.get("value") is not None:
        pl.append(f"공포탐욕 {int(_f(fg['value']))}({_fg_label(fg['value'])})")
    vix = us.get("vix")
    if vix and vix.get("value") is not None:
        pl.append(f"VIX {_num(vix['value'], 1)}")
    if pl:
        lines.append(" ".join(pl))

    text = "\n".join(lines)
    if len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT - 1].rstrip() + "…"
    return text


def send_memo(access_token, text):
    """카카오톡 '나에게 보내기'(기본 텍스트 템플릿)로 발송."""
    template = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": DASHBOARD_URL, "mobile_web_url": DASHBOARD_URL},
        "button_title": "대시보드 열기",
    }
    status, j = _http_post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        {"template_object": json.dumps(template, ensure_ascii=False)},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if status != 200:
        raise SystemExit(f"[kakao] 메시지 발송 실패: HTTP {status} {j}")
    print(f"[kakao] 발송 성공 ({len(text)}자):\n{text}")


def main():
    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if not rest_key or not refresh_token:
        raise SystemExit("[kakao] KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN GitHub Secret 이 필요합니다.")

    path = os.path.abspath(DATA_PATH)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"[kakao] data.json 읽기 실패({path}): {e}")

    text = build_summary(data)
    access_token = refresh_access_token(rest_key, refresh_token)
    send_memo(access_token, text)


if __name__ == "__main__":
    main()
