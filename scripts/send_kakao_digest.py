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
import time as _time
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


def build_blocks(d):
    """data.json → 카카오 발송용 한국어 섹션 블록 리스트 + 헤더.

    카테고리(증시·Top3 / 채권 / 환율 / 원자재 / 투자자 순매매 / 심리)별 블록으로 묶고,
    카카오 텍스트 템플릿 200자 제한에 맞춰 여러 메시지로 분할 발송한다.
    """
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
    # 발송 시각(KST)에 맞춰 제목 — 10시=아침 / 15시=오후 / 18시(이후)=마감.
    if now.hour < 12:
        slot = "아침 시황"
    elif now.hour < 17:
        slot = "오후 시황"
    else:
        slot = "마감 시황"
    header = f"\U0001F4CA {now.month}/{now.day}({wd}) {slot} ({now.hour:02d}:{now.minute:02d})"

    blocks = []

    def idx_part(label, key):
        o = idx.get(key)
        if not o or o.get("price") is None:
            return None
        return f"{label} {_num(o['price'], 0)}({_a1(o.get('change'))})"

    # 〔주요 증시〕 — 국내·해외 6개 (2개/줄)
    eq = [p for p in (idx_part("코스피", "KOSPI"), idx_part("코스닥", "KOSDAQ"),
                      idx_part("나스닥", "NASDAQ"), idx_part("S&P", "SP500"),
                      idx_part("닛케이", "Nikkei"), idx_part("상해", "Shanghai")) if p]
    if eq:
        rows = [" ".join(eq[i:i + 2]) for i in range(0, len(eq), 2)]
        blocks.append("〔주요 증시〕\n" + "\n".join(rows))

    # 〔종목 Top3〕 — 코스피 상승/하락 상위 3
    up = _movers_line(sm.get("kospiGainers"), "▲상승", 3)
    dn = _movers_line(sm.get("kospiLosers"),  "▼하락", 3)
    if up or dn:
        blocks.append("〔종목 Top3〕\n" + "\n".join([x for x in (up, dn) if x]))

    # 〔ETF Top3〕 — 상승/하락 상위 3
    eup = _movers_line(etf.get("etfGainers"), "▲상승", 3)
    edn = _movers_line(etf.get("etfLosers"),  "▼하락", 3)
    if eup or edn:
        blocks.append("〔ETF Top3〕\n" + "\n".join([x for x in (eup, edn) if x]))

    # 〔한·미 채권〕 — 10년물 (yieldCurve 우선, 없으면 economicIndicators 폴백)
    kr10 = _yield_10y(d, "kr")
    us10 = _yield_10y(d, "us")
    if us10 is None:
        us10 = _f((us.get("us10y") or {}).get("value"))
    bond = []
    if kr10 is not None:
        bond.append(f"韓국고10년 {_num(kr10, 2)}%")
    if us10 is not None:
        bond.append(f"美10년 {_num(us10, 2)}%")
    if bond:
        blocks.append("〔한·미 채권〕 " + " ".join(bond))

    # 〔환율〕 — 달러/유로/엔(100)/엔달러/유로달러/위안 (더 풍부하게)
    def fx_part(label, key, nd=1, mul=1.0):
        o = fx.get(key)
        if not o or o.get("rate") is None:
            return None
        return f"{label} {_num(_f(o['rate']) * mul, nd)}({_a1(o.get('change'))})"
    fxs = [p for p in (
        fx_part("달러", "USDKRW", 1),
        fx_part("유로", "EURKRW", 1),
        fx_part("엔100", "JPYKRW", 1, 100.0),   # JPYKRW 는 1엔당 → ×100 표기
        fx_part("위안", "CNYKRW", 1),
        fx_part("엔/달러", "USDJPY", 2),
        fx_part("유로/달러", "EURUSD", 4),
    ) if p]
    if fxs:
        rows = [" ".join(fxs[i:i + 2]) for i in range(0, len(fxs), 2)]
        blocks.append("〔환율〕\n" + "\n".join(rows))

    # 〔원자재〕 — WTI/브렌트/금/은/구리/천연가스 (더 풍부하게)
    def com_part(label, key, nd=1, pre="$"):
        o = com.get(key)
        if not o or o.get("price") is None:
            return None
        return f"{label} {pre}{_num(o['price'], nd)}({_a1(o.get('change'))})"
    coms = [p for p in (
        com_part("WTI", "WTI", 1),
        com_part("브렌트", "Brent", 1),
        com_part("금", "Gold", 0),
        com_part("은", "Silver", 1),
        com_part("구리", "Copper", 2),
        com_part("천연가스", "NatGas", 2),
    ) if p]
    if coms:
        rows = [" ".join(coms[i:i + 2]) for i in range(0, len(coms), 2)]
        blocks.append("〔원자재〕\n" + "\n".join(rows))

    # 〔투자자 순매매〕 — 최근 영업일 외국인/기관/개인 (억원)
    daily = inv.get("daily") or []
    if daily:
        last = daily[-1]
        unit = inv.get("unit", "억원")

        def _sig(v):
            v = _f(v)
            return "-" if v is None else f"{'+' if v >= 0 else ''}{v:,.0f}"
        blocks.append(
            f"〔투자자 순매매·{unit}〕({last.get('date','')})\n"
            f"외국인 {_sig(last.get('foreign'))} 기관 {_sig(last.get('inst'))} 개인 {_sig(last.get('retail'))}"
        )

    # 〔시장심리〕 — 공포탐욕, VIX
    pl = []
    fg = sent.get("fear_greed")
    if fg and fg.get("value") is not None:
        pl.append(f"공포탐욕 {int(_f(fg['value']))}({_fg_label(fg['value'])})")
    vix = us.get("vix")
    if vix and vix.get("value") is not None:
        pl.append(f"VIX {_num(vix['value'], 1)}")
    if pl:
        blocks.append("〔시장심리〕 " + " ".join(pl))

    return header, blocks


def pack_messages(header, blocks, limit=TEXT_LIMIT):
    """헤더 + 섹션 블록들을 200자 이내 메시지 여러 개로 묶는다 (블록은 분할하지 않음)."""
    msgs, cur = [], header
    for b in blocks:
        cand = (cur + "\n\n" + b) if cur else b
        if cur and len(cand) > limit:
            msgs.append(cur)
            cur = b
        else:
            cur = cand
    if cur:
        msgs.append(cur)
    # 단일 블록이 한도를 넘으면(드묾) 안전하게 자른다.
    return [m if len(m) <= limit else m[:limit - 1].rstrip() + "…" for m in msgs]


def build_summary(d):
    """하위호환: 첫 메시지(헤더+핵심)만 반환."""
    header, blocks = build_blocks(d)
    return pack_messages(header, blocks)[0]


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

    header, blocks = build_blocks(data)
    # 진행표시 '(i/n)' 프리픽스 자리를 위해 여유(10자)를 두고 분할 → 프리픽스 후에도 200자 이내.
    messages = pack_messages(header, blocks, limit=TEXT_LIMIT - 10)
    access_token = refresh_access_token(rest_key, refresh_token)
    # 200자 제한 때문에 섹션을 여러 메시지로 나눠 순차 발송한다(대시보드 버튼은 마지막에만).
    n = len(messages)
    for i, msg in enumerate(messages):
        last = (i == n - 1)
        # 다중 메시지면 진행 표시 '(i/n)' 를 붙여 맥락 유지.
        body = msg if n == 1 else (f"{msg}\n(1/{n})" if i == 0 else f"({i + 1}/{n})\n{msg}")
        if len(body) > TEXT_LIMIT:
            body = body[:TEXT_LIMIT - 1].rstrip() + "…"
        send_memo(access_token, body, with_button=last)
        if not last:
            _time.sleep(0.5)   # 연속 발송 간 약간의 간격
    print(f"[kakao] 총 {n}개 메시지 발송 완료")


if __name__ == "__main__":
    main()
