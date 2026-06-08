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


def _yield_10y(d, side):
    """yieldCurve[side] 에서 국고채/국채 10년물 최신값. 없으면 None."""
    yc = (d.get("yieldCurve", {}) or {}).get(side, {}) or {}
    for s in yc.get("series", []) or []:
        if s.get("tenor") == "10Y":
            pts = [x for x in (s.get("data") or []) if x.get("value") is not None]
            if pts:
                return _f(pts[-1].get("value"))
    return None


def _a1(c):
    """등락률 1자리 화살표 (▲1.8% / ▼6.7%) — 200자 제한 내 가독성 우선."""
    c = _f(c)
    if c is None:
        return ""
    return f"▲{c:.1f}%" if c >= 0 else f"▼{abs(c):.1f}%"


def _short_name(nm, limit=11):
    nm = (nm or "").strip()
    return nm if len(nm) <= limit else nm[:limit - 1] + "…"


def _movers_line(arr, mark, n=3):
    """[{name, chg}] → 'mark이름1 +x.x% 이름2 -y.y% ...' (상위 n)."""
    parts = []
    for it in (arr or [])[:n]:
        c = _f(it.get("chg"))
        if c is None:
            continue
        sign = "+" if c >= 0 else ""
        parts.append(f"{_short_name(it.get('name'))}{sign}{c:.1f}%")
    return (mark + " " + " / ".join(parts)) if parts else None


def build_message(d, limit=TEXT_LIMIT):
    """data.json → 카카오 '나에게 보내기' 단일 메시지(한국어).

    카카오 기본 텍스트 템플릿은 200자 제한이라, 카테고리(증시·투자자·환율·원자재·채권·심리)별
    핵심 수치를 한 줄씩 압축해 우선순위대로 한도 내에서 최대한 담는다. 상세(종목/ETF Top3 등)는
    '대시보드 보기' 버튼으로 연결. 한 통으로만 발송(분할 없음)."""
    idx  = d.get("indices", {}) or {}
    fx   = d.get("fx", {}) or {}
    com  = d.get("commodities", {}) or {}
    sent = d.get("sentiment", {}) or {}
    ei   = d.get("economicIndicators", {}) or {}
    us   = ei.get("us", {}) or {}
    sm   = d.get("stockMovers", {}) or {}
    etf  = d.get("etfMovers", {}) or {}
    inv  = d.get("investorTrading", {}) or {}

    now = datetime.datetime.now(KST)
    wd = "월화수목금토일"[now.weekday()]
    header = f"{now.month}/{now.day}({wd}) 시황"

    def ip(label, key):
        o = idx.get(key)
        if not o or o.get("price") is None:
            return None
        return f"{label}{_num(o['price'], 0)}{_a1(o.get('change'))}"

    blocks = []   # 우선순위 순서 — 한도 내에서 위에서부터 채운다.

    # 증시 (코스피·코스닥·나스닥·S&P)
    eq = [p for p in (ip("코스피", "KOSPI"), ip("코스닥", "KOSDAQ"),
                      ip("나스닥", "NASDAQ"), ip("S&P", "SP500")) if p]
    if eq:
        blocks.append("〔증시〕" + " ".join(eq))

    # 투자자 순매매 (최근 영업일 외국인/기관/개인, 억원)
    daily = inv.get("daily") or []
    if daily:
        last = daily[-1]

        def _s(v):
            v = _f(v)
            return "-" if v is None else f"{'+' if v >= 0 else ''}{v:,.0f}"
        blocks.append(f"〔투자자·억원〕외{_s(last.get('foreign'))} 기{_s(last.get('inst'))} 개{_s(last.get('retail'))}")

    # 환율 (달러·엔100)
    def fxp(label, key, nd=1, mul=1.0):
        o = fx.get(key)
        if not o or o.get("rate") is None:
            return None
        return f"{label}{_num(_f(o['rate']) * mul, nd)}{_a1(o.get('change'))}"
    fxs = [p for p in (fxp("달러 ", "USDKRW", 1), fxp("엔100 ", "JPYKRW", 1, 100.0)) if p]
    if fxs:
        blocks.append("〔환율〕" + " ".join(fxs))

    # 원자재 (WTI·금·구리)
    def cmp_(label, key, nd=1):
        o = com.get(key)
        if not o or o.get("price") is None:
            return None
        return f"{label}${_num(o['price'], nd)}{_a1(o.get('change'))}"
    coms = [p for p in (cmp_("WTI ", "WTI", 1), cmp_("금 ", "Gold", 0), cmp_("구리 ", "Copper", 2)) if p]
    if coms:
        blocks.append("〔원자재〕" + " ".join(coms))

    # 채권 (한·미 10년)
    kr10 = _yield_10y(d, "kr")
    us10 = _yield_10y(d, "us")
    if us10 is None:
        us10 = _f((us.get("us10y") or {}).get("value"))
    bond = []
    if kr10 is not None:
        bond.append(f"韓10년 {_num(kr10, 2)}%")
    if us10 is not None:
        bond.append(f"美10년 {_num(us10, 2)}%")
    if bond:
        blocks.append("〔채권〕" + " ".join(bond))

    # 시장심리 (공포탐욕·VIX)
    pl = []
    fg = sent.get("fear_greed")
    if fg and fg.get("value") is not None:
        pl.append(f"공포탐욕 {int(_f(fg['value']))}({_fg_label(fg['value'])})")
    vix = us.get("vix")
    if vix and vix.get("value") is not None:
        pl.append(f"VIX {_num(vix['value'], 1)}")
    if pl:
        blocks.append("〔심리〕" + " ".join(pl))

    # 종목/ETF Top1 (여유가 있을 때만 — 상세 Top3 는 대시보드)
    up = _movers_line(sm.get("kospiGainers"), "급등", 1)
    dn = _movers_line(sm.get("kospiLosers"), "급락", 1)
    if up and dn:
        blocks.append(f"〔종목〕{up} {dn}")

    # 우선순위대로 200자 한도 내에서 채우기 (들어가지 않는 줄은 건너뜀).
    msg = header
    for b in blocks:
        if len(msg) + 1 + len(b) <= limit:
            msg += "\n" + b
    return msg


def send_memo(access_token, text, with_button=True):
    """카카오톡 '나에게 보내기'(기본 텍스트 템플릿)로 발송."""
    template = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": DASHBOARD_URL, "mobile_web_url": DASHBOARD_URL},
    }
    if with_button:
        template["button_title"] = "대시보드 보기"
    status, j = _http_post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        {"template_object": json.dumps(template, ensure_ascii=False)},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if status != 200:
        raise SystemExit(f"[kakao] 메시지 발송 실패: HTTP {status} {j}")
    print(f"[kakao] 발송 성공 ({len(text)}자):\n{text}\n---")


def main():
    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if not rest_key or not refresh_token:
        # 시크릿 미설정 = 아직 설정 전(또는 설정 진행 중). 이때 워크플로를 '실패'로 끝내면 매 스케줄마다
        # GitHub 가 'run failed' 알림 메일을 보내 사용자를 괴롭힌다. 따라서 이 경우엔 경고만 남기고
        # 정상 종료(exit 0)한다 — KAKAO_SETUP.md 의 ③~④(refresh_token 발급·시크릿 등록)를 마치면
        # 다음 스케줄부터 자동으로 발송된다. (토큰 만료 등 '진짜 오류'는 아래에서 그대로 실패 처리.)
        missing = [n for n, v in (("KAKAO_REST_API_KEY", rest_key),
                                  ("KAKAO_REFRESH_TOKEN", refresh_token)) if not v]
        print(f"::warning title=Kakao 미설정::{', '.join(missing)} 시크릿이 아직 없어 발송을 건너뜁니다. "
              "설정 방법은 KAKAO_SETUP.md 참고. (워크플로는 정상 종료 — 실패 알림 없음)")
        return

    path = os.path.abspath(DATA_PATH)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"[kakao] data.json 읽기 실패({path}): {e}")

    text = build_message(data)
    access_token = refresh_access_token(rest_key, refresh_token)
    # 한 통으로만 발송 — '대시보드 보기' 버튼은 https://0101-commits.github.io/economic-site/ 로 연결.
    send_memo(access_token, text, with_button=True)
    print("[kakao] 단일 메시지 발송 완료")


if __name__ == "__main__":
    main()
