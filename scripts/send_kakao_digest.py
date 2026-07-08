#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""data.json 시황을 카카오톡으로 발송한다 — 평일은 07~22시(:03), 주말은 11·17시만.

수신 모드(자동 판별):
  * 친구에게 보내기(우선) — 앱과 연결·동의된 카카오톡 친구가 있으면 그 친구들에게 발송.
    일반 메시지처럼 '푸시 알림'이 울린다. (2026-06 사용자 요청: 나에게 보내기는 내가 보낸
    메시지라 알림이 없음 → 보조 계정을 발신자로 두고 본 계정을 친구로 수신.)
    검수 전 앱은 '팀 멤버'로 등록된 친구만 조회된다. 설정 절차는 KAKAO_SETUP.md ⑤ 참고.
    쿼터: 발신자당 일 100건·발신자→수신자 쌍당 일 20건 — 평일 16회 발송 기준 친구 6명까지 안전.
  * 나에게 보내기(폴백) — 친구가 없거나 friends 동의가 없으면 종전대로 '나와의 채팅'으로.

필요한 GitHub Secrets:
  KAKAO_REST_API_KEY   — 카카오 개발자 앱의 REST API 키
  KAKAO_REFRESH_TOKEN  — talk_message(+friends) 동의로 발급한 refresh_token
                         (친구에게 보내기를 쓰려면 '발신용 보조 계정'의 토큰)

발송 형식은 '단 한 가지(통일)' — 피드 한 통:
  슬롯별 차트 이미지(당일 인트라데이, 없으면 7일 일봉 폴백)
  + 제목('M/D(요일) H시 시황')
  + 공통 내용 7종: 증시(코스피·S&P) / 환율(달러-원·달러-엔)
    / 심리(공포탐욕·VIX·VKOSPI 코스피위험지수) / 에너지(WTI·천연가스)
    / 금속(금·구리) / 곡물(옥수수·밀·대두) / 운임(SCFI 상하이컨테이너운임지수)
  + '대시보드 보기' 버튼.
  (2026-06 사용자 요청: 시장심리에 코스피위험지수 추가, 원자재를 에너지·금속·곡물로
   분리, 상하이 운임지수 포함.)

슬롯별 차트(주가/환율/원자재는 당일 인트라데이, 없으면 일봉 폴백.
            국채 수익률: 미국은 당일 인트라데이[^TNX], 한국은 일별[ECOS],
            일본은 일별[재무성 MOF CSV, 실패 시 FRED 월별 폴백] 추세선):
  [평일]
    07시           → 미국 10년 국채 + 일본 10년 국채
    08시           → 달러-원 + 금
    09시           → S&P500 + 코스피
    10~16시        → 코스피 + 달러-원
    17시           → 달러-원 + 금
    18시           → 달러-엔 + 천연가스
    19시           → 은 + 구리
    20시           → 천연가스 + 밀
    21시           → 한국 10년 국채 + 미국 10년 국채
    22시           → 달러-원 + WTI
  [주말] 본문은 평일과 동일, 사진만 달러-원 + 금
    11시·17시      → 달러-원 + 금

신뢰성 원칙 — '형식이 다른 메시지'가 다시는 나가지 않도록:
  * 모든 카카오 API 호출(토큰 재발급·이미지 업로드·발송)에 지수 백오프 재시도.
    (2026-06-10 10시 발송이 러너의 일시적 DNS 실패 1회로 차트 없는 콘솔 템플릿 폴백으로
     나간 사례의 재발 방지 — 콘솔 커스텀 템플릿 폴백 경로 자체도 제거했다.)
  * 모든 단계가 같은 build_digest_parts() 의 내용을 쓰므로, 최후 폴백(텍스트)도
    이미지 유무만 다를 뿐 '내용 구성'은 동일하다.

설정 방법(1회): 저장소 루트 KAKAO_SETUP.md 참고.
"""
import os
import re
import sys
import time
import json
import datetime
import urllib.parse
import urllib.request
import urllib.error

DASHBOARD_URL = "https://0101-commits.github.io/economic-site/"
KST = datetime.timezone(datetime.timedelta(hours=9))
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.json")
TEXT_LIMIT = 200  # 카카오 텍스트 템플릿 text 최대 길이

# ── 발송 슬롯 — 평일/주말을 분리한다. 워크플로 게이트·차트 구성·제목 표기가 모두 이 목록 기준.
#    (2026-06 사용자 요청: 평일은 종전 시간대 유지 + 18·19·21시 추가, 주말은 11·17시 2회만.)
#   • 평일(월~금) 16회(KST): 07~22시 매시간(다만 23~06시 미발송).
#   • 주말(토·일)  2회(KST): 11시·17시.
SLOT_HOURS_WEEKDAY = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]
SLOT_HOURS_WEEKEND = [11, 17]

# 슬롯별 차트 구성 — 패널 2개(위·아래)를 1장으로 합쳐 보낸다. 각 패널은 (카테고리, 키, 라벨).
#   • 카테고리 "indices"/"fx"/"commodities" → data.json history[cat][key] 일봉 + Yahoo 인트라데이.
#   • 카테고리 "yield" → 국채 수익률. US10Y·KR10Y 는 yieldCurve(일별), JP10Y 는
#     economicIndicators.jp.bond10y_jp(월별). 인트라데이 없음 → 추세선(값은 %, 변화는 bp 표기).
# (라벨은 CI 한글폰트 부재 대비 영문)
_CHART_KR = ([("indices", "KOSPI", "KOSPI"), ("fx", "USDKRW", "USD/KRW")],
             "KOSPI / USD-KRW")
_CHART_EVE = ([("fx", "USDKRW", "USD/KRW"), ("commodities", "WTI", "WTI Crude")],
              "USD-KRW / WTI")
_CHART_FX_GOLD = ([("fx", "USDKRW", "USD/KRW"), ("commodities", "Gold", "Gold")],
                  "USD-KRW / Gold")
# (2026-06 사용자 요청) 슬롯별 신규 구성.
_CHART_BONDS_USJP = ([("yield", "US10Y", "US 10Y"), ("yield", "JP10Y", "JP 10Y")],
                     "US 10Y / JP 10Y")
_CHART_SP_KOSPI = ([("indices", "SP500", "S&P 500"), ("indices", "KOSPI", "KOSPI")],
                   "S&P500 / KOSPI")
_CHART_JPY_GAS = ([("fx", "USDJPY", "USD/JPY"), ("commodities", "NatGas", "NatGas")],
                  "USD-JPY / NatGas")
_CHART_SILVER_COPPER = ([("commodities", "Silver", "Silver"), ("commodities", "Copper", "Copper")],
                        "Silver / Copper")
_CHART_GAS_WHEAT = ([("commodities", "NatGas", "NatGas"), ("commodities", "Wheat", "Wheat")],
                    "NatGas / Wheat")
_CHART_BONDS_KRUS = ([("yield", "KR10Y", "KR 10Y"), ("yield", "US10Y", "US 10Y")],
                     "KR 10Y / US 10Y")
# 평일 슬롯별 차트: 07=미·일국채 / 08=달러원·금 / 09=S&P·코스피 / 10~16=코스피·달러원
#               / 17=달러원·금 / 18=달러엔·천연가스 / 19=은·구리 / 20=천연가스·밀
#               / 21=한·미국채 / 22=달러원·WTI.
SLOT_CHARTS_WEEKDAY = {
    "h07": _CHART_BONDS_USJP, "h08": _CHART_FX_GOLD, "h09": _CHART_SP_KOSPI,
    "h10": _CHART_KR, "h11": _CHART_KR, "h12": _CHART_KR, "h13": _CHART_KR,
    "h14": _CHART_KR, "h15": _CHART_KR, "h16": _CHART_KR, "h17": _CHART_FX_GOLD,
    "h18": _CHART_JPY_GAS, "h19": _CHART_SILVER_COPPER, "h20": _CHART_GAS_WHEAT,
    "h21": _CHART_BONDS_KRUS, "h22": _CHART_EVE,
}
# 주말 슬롯별 차트: 본문은 평일과 동일, 사진만 달러원·금.
SLOT_CHARTS_WEEKEND = {
    "h11": _CHART_FX_GOLD, "h17": _CHART_FX_GOLD,
}
_CHART_COLOR = {"KOSPI": "#2962ff", "SP500": "#1e88e5", "USDKRW": "#26a69a",
                "WTI": "#ef6c00", "Gold": "#fbc02d", "USDJPY": "#00897b",
                "NatGas": "#5e35b1", "Silver": "#90a4ae", "Copper": "#c0631f",
                "Wheat": "#8d6e63", "US10Y": "#d32f2f", "KR10Y": "#1565c0",
                "JP10Y": "#6a1b9a"}
# 당일(인트라데이) 시세용 Yahoo Finance 심볼 — data.json 엔 일별 종가만 있어 차트 생성 시 직접 조회한다.
# (국채 수익률은 별도 경로: US10Y 는 _YIELD_INTRADAY_SYM[^TNX] 인트라데이,
#  KR10Y·JP10Y 는 인트라데이 소스가 없어 일별 추세선 — _draw_yield_panel 참고.)
_YH_SYM = {"KOSPI": "^KS11", "SP500": "^GSPC", "USDKRW": "KRW=X", "WTI": "CL=F",
           "Gold": "GC=F", "USDJPY": "JPY=X", "NatGas": "NG=F", "Silver": "SI=F",
           "Copper": "HG=F", "Wheat": "ZW=F"}
# 차트 PNG 크기(px) — 카톡 피드 이미지는 말풍선 '폭'이 고정이고 높이만 비율을 따라 늘어난다.
# 카카오 이미지 표시 허용 비율은 가로 2:1 ~ 세로 3:4 이며, '3:4 를 초과(더 세로로 김)'하면 상단
# 기준으로 자동 크롭된다. 1080x1440 은 정확히 3:4(경계선)라, 카카오가 큰 이미지를 재인코딩·
# 리사이즈할 때 반올림으로 경계를 살짝 넘으면 상단이 잘리는 일이 생겼다(2026-07 사용자 보고:
# "사진이 잘릴 때가 있음"). → 경계에서 안전 여백을 둔 4:5(세로형, 폭/높이=0.8)로 낮춰 어떤
# 재인코딩에도 크롭되지 않게 한다. 픽셀도 과대하지 않게(≤1080) 유지해 서버 리사이즈를 줄인다.
# (2026-06 사용자 요청 '사진이 작음'은 비율이 좌우 — 4:5 도 세로형이라 말풍선에서 크게 보인다.)
_CHART_DPI = 150
CHART_PX = (864, 1080)   # 4:5 (세로형, 2:1~3:4 허용대 안쪽 안전 여백)


def _retry(fn, what, tries=3, delay=2):
    """일시 네트워크 장애(러너 DNS 실패 등) 대비 재시도(지수 백오프). 마지막 실패는 그대로 올린다."""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"[retry] {what} 실패({e}) — {delay}s 후 재시도 ({i + 2}/{tries})")
            time.sleep(delay)
            delay *= 2


def _http_post(url, form, headers=None):
    """폼 POST → (status, json). 4xx/5xx 응답은 그대로 반환하고, 전송 오류(DNS 등)만 예외."""
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


# 카카오/OAuth 일시 오류(429·5xx)는 재시도 대상 — 4xx(권한·형식)는 즉시 반환.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _retry_status(fn, what, tries=3, delay=2):
    """(status, json) 반환 fn 을 감싸 전송오류(예외) + 일시 서버오류(429/5xx)에 지수 백오프 재시도.

    _retry 는 예외만 재시도하지만 _http_post/_http_get 은 4xx/5xx 를 (status, json) 으로 '반환'하므로,
    5xx·429 가 첫 시도에 그대로 실패로 굳던 문제를 막는다."""
    for i in range(tries):
        try:
            status, j = fn()
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"[retry] {what} 전송오류({e}) — {delay}s 후 재시도 ({i + 2}/{tries})")
            time.sleep(delay)
            delay *= 2
            continue
        if status in RETRYABLE_STATUS and i < tries - 1:
            print(f"[retry] {what} HTTP {status} — {delay}s 후 재시도 ({i + 2}/{tries})")
            time.sleep(delay)
            delay *= 2
            continue
        return status, j


def _http_post_retry(url, form, headers=None, what="HTTP POST"):
    return _retry_status(lambda: _http_post(url, form, headers), what)


def _http_get_retry(url, headers=None, what="HTTP GET"):
    return _retry_status(lambda: _http_get(url, headers), what)


def _http_get(url, headers=None):
    """GET → (status, json). 4xx/5xx 응답은 그대로 반환하고, 전송 오류(DNS 등)만 예외."""
    req = urllib.request.Request(url, headers=headers or {})
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
    status, j = _http_post_retry("https://kauth.kakao.com/oauth/token", {
        "grant_type": "refresh_token",
        "client_id": rest_key,
        "refresh_token": refresh_token,
    }, what="토큰 재발급")
    if status != 200 or not j.get("access_token"):
        raise SystemExit(f"[kakao] access_token 재발급 실패: HTTP {status} {j}")
    # refresh_token 유효기간이 1개월 미만이면 카카오가 새 토큰을 함께 준다 → 시크릿 교체 안내.
    if j.get("refresh_token"):
        # ⚠ 보안: 공개 저장소라 Actions 로그가 공개된다 → 새 토큰을 로그에 노출하면 안 됨(마스킹 유지).
        #    기존 refresh_token 은 회전 후에도 약 1개월 유효하므로, 그 안에 재발급하면 된다.
        print("::warning title=KAKAO_REFRESH_TOKEN 회전됨::카카오가 refresh_token 을 회전했습니다. "
              "기존 토큰은 약 1개월 더 유효하나, 만료 전 KAKAO_SETUP.md 절차로 재발급해 GitHub Secret 을 "
              "갱신하세요. (보안상 새 토큰 값은 공개 로그에 노출하지 않습니다.)")
        print(f"::add-mask::{j['refresh_token']}")
    return j["access_token"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _num(v, nd=0):
    v = _f(v)
    return "-" if v is None else f"{v:,.{nd}f}"


def _a1(c):
    """등락률 1자리 화살표 (▲1.8% / ▼6.7%)."""
    c = _f(c)
    if c is None:
        return ""
    return f"▲{c:.1f}%" if c >= 0 else f"▼{abs(c):.1f}%"


def _fg_label(v):
    v = _f(v)
    if v is None:
        return ""
    return ("극도공포" if v < 25 else "공포" if v < 45 else
            "중립" if v < 55 else "탐욕" if v < 75 else "극도탐욕")


def build_digest_parts(d):
    """data.json → (제목, 공통 블록 [(라벨, 값), ...]).

    공통 내용(모든 슬롯 동일):
      증시(코스피·S&P) / 환율(달러-원·달러-엔) / 심리(공포탐욕·VIX·VKOSPI)
      / 에너지(WTI·천연가스) / 금속(금·구리) / 곡물(옥수수·밀·대두) / 운임(SCFI).
    피드·텍스트 등 모든 발송 경로가 이 한 곳의 결과만 쓰므로 경로별 내용 차이가 생길 수 없다."""
    idx  = d.get("indices", {}) or {}
    fx   = d.get("fx", {}) or {}
    com  = d.get("commodities", {}) or {}
    sent = d.get("sentiment", {}) or {}
    us   = (d.get("economicIndicators", {}) or {}).get("us", {}) or {}

    # 제목의 시각은 '실제 발송 시각(now)' 기준 — 슬롯 라벨이 아니라 받는 시각과 항상 일치시킨다.
    # (정시 발송에선 슬롯 시각 == now 시각이라 동일하지만, 수동·지연 등으로 어긋나도 시각이 거짓이 되지 않게.
    #  과거 토 15:02 발송이 '17시'로 표기된 사례 방지 — 트리거 게이트 보강과 함께 이중 안전장치.)
    now = datetime.datetime.now(KST)
    wd = "월화수목금토일"[now.weekday()]
    title = f"{now.month}/{now.day}({wd}) {now.hour}시 시황"

    def ip(label, key, nd=0):
        o = idx.get(key)
        if not o or o.get("price") is None:
            return None
        return f"{label} {_num(o['price'], nd)}{_a1(o.get('change'))}"

    def fxp(label, key, nd=1):
        o = fx.get(key)
        if not o or o.get("rate") is None:
            return None
        return f"{label} {_num(o['rate'], nd)}{_a1(o.get('change'))}"

    def cp(label, key, nd=1):
        o = com.get(key)
        if not o or o.get("price") is None:
            return None
        return f"{label} {_num(o['price'], nd)}{_a1(o.get('change'))}"

    blocks = []
    eq = [p for p in (ip("코스피", "KOSPI"), ip("S&P", "SP500")) if p]
    if eq:
        blocks.append(("증시", " ".join(eq)))
    fxs = [p for p in (fxp("달러-원", "USDKRW"), fxp("달러-엔", "USDJPY")) if p]
    if fxs:
        blocks.append(("환율", " ".join(fxs)))
    pl = []
    fg = sent.get("fear_greed")
    if fg and fg.get("value") is not None:
        pl.append(f"공포탐욕 {int(_f(fg['value']))}({_fg_label(fg['value'])})")
    vix = us.get("vix")
    vix_v = _f(vix.get("value")) if vix else None
    if vix_v is not None:
        pl.append(f"VIX {_num(vix_v, 1)}")
    vk = sent.get("vkospi")   # 코스피 위험지수(KOSPI 변동성지수, VKOSPI)
    vk_v = _f(vk.get("value")) if vk else None
    # 이상치 가드 — 스크래핑 오류 값이 carry-forward 되어 발송되는 것 방지(2026-06-11: VIX 19.9
    # 인데 VKOSPI 86.5 가 나간 사례). 정상 범위(5~60) 밖이면서 VIX 의 3배를 넘으면(역사적
    # VKOSPI/VIX 비율은 대체로 1~2배) 신뢰 불가로 보고 표기를 생략한다.
    if vk_v is not None and not (5 <= vk_v <= 60) and (vix_v is None or vk_v > 3 * vix_v):
        print(f"[digest] VKOSPI {vk_v} 이상치 의심(VIX {vix_v}) — 표기 생략")
        vk_v = None
    if vk_v is not None:
        pl.append(f"VKOSPI {_num(vk_v, 1)}")
    if pl:
        blocks.append(("심리", " ".join(pl)))
    # 원자재 — 에너지 / 금속 / 곡물 분리
    energy = [p for p in (cp("WTI", "WTI"), cp("천연가스", "NatGas", 2)) if p]
    if energy:
        blocks.append(("에너지", " ".join(energy)))
    metal = [p for p in (cp("금", "Gold", 0), cp("구리", "Copper", 2)) if p]
    if metal:
        blocks.append(("금속", " ".join(metal)))
    grain = [p for p in (cp("옥수수", "Corn", 0), cp("밀", "Wheat", 0), cp("대두", "Soybean", 0)) if p]
    if grain:
        blocks.append(("곡물", " ".join(grain)))
    # 해상 운임 — 상하이컨테이너운임지수(SCFI). freight.items 는 change 대신 chgPct(%) 사용.
    scfi = next((it for it in ((d.get("freight", {}) or {}).get("items") or [])
                 if isinstance(it, dict) and it.get("code") == "SCFI"
                 and it.get("price") is not None), None)
    if scfi:
        blocks.append(("운임", f"SCFI {_num(scfi['price'])}{_a1(scfi.get('chgPct'))}"))
    return title, blocks


def _pack(prefix, lines, limit):
    """prefix 뒤에 줄을 한도 내에서 채워 한 문자열로(못 들어가는 줄은 생략)."""
    msg = prefix
    for ln in lines:
        add = ln if not msg else "\n" + ln
        if len(msg) + len(add) <= limit:
            msg += add
    return msg


def build_text_message(title, blocks, limit=TEXT_LIMIT):
    """텍스트 폴백용 단일 문자열 — 피드와 동일한 공통 블록(증시~운임)을 200자 내에 담는다.

    카카오 텍스트 템플릿 한도(200자)를 넘는 뒷줄은 _pack 이 생략한다 — blocks 순서가
    곧 우선순위(증시 > 환율 > 심리 > 에너지 > 금속 > 곡물 > 운임)."""
    return _pack(title, [f"〔{lab}〕{val}" for lab, val in blocks], limit)


def _friends_enabled():
    """'친구에게 보내기' on/off — 기본 on(친구가 조회되면 자동 사용). 끄려면 워크플로 변수 KAKAO_FRIENDS=0."""
    return os.environ.get("KAKAO_FRIENDS", "1").strip().lower() not in ("0", "false", "no", "off")


def get_friends(access_token):
    """'친구에게 보내기' 수신자 목록 — 앱과 연결되고 친구 목록 제공(friends)에 동의한 카카오톡 친구.

    검수 전 앱은 '팀 멤버'로 등록된 친구만 조회된다(설정 절차: KAKAO_SETUP.md ⑤).
    friends 동의가 없으면(HTTP 403) 빈 목록 — 이때는 종전 '나에게 보내기'로 발송하므로,
    보조 계정·동의 설정을 마치기 전에도 기존 동작이 그대로 유지된다."""
    try:
        status, j = _http_get_retry(
            "https://kapi.kakao.com/v1/api/talk/friends?limit=100",
            {"Authorization": f"Bearer {access_token}"}, what="친구 목록 조회")
    except Exception as e:
        print(f"[kakao] 친구 목록 조회 실패({e}) — 나에게 보내기로 발송")
        return []
    if status != 200:
        print(f"[kakao] 친구 목록 조회 불가 HTTP {status}({j.get('msg', j)}) — 나에게 보내기로 발송")
        return []
    return [el for el in (j.get("elements") or []) if isinstance(el, dict) and el.get("uuid")]


def _send_template_object(access_token, template, uuids=None):
    """template_object 발송 — uuids 가 있으면 '친구에게 보내기', 없으면 '나에게 보내기'(메모).

    친구에게는 한 호출당 최대 5명(카카오 한도)이라 5명씩 나눠 보낸다. HTTP 200 이면 그 묶음은
    성공으로 본다(failure_info 의 개별 수신 거부 등은 로그만 — 재발송하면 성공자에게 중복이 가므로)."""
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {"template_object": json.dumps(template, ensure_ascii=False)}
    if not uuids:
        return _http_post_retry("https://kapi.kakao.com/v2/api/talk/memo/default/send",
                                payload, headers, what="메시지 발송(나에게)")
    worst = (200, {})
    for i in range(0, len(uuids), 5):
        chunk = uuids[i:i + 5]
        # 청크별 전송오류(URLError/타임아웃 등 재시도 소진)를 예외로 던지지 않고 '실패 status'로
        # 흡수한다 — 앞 청크가 성공(200)한 뒤 뒤 청크에서 예외가 튀면 send 전체가 크래시하고
        # (kakao-daily) 발송 마커가 안 찍혀 다음 깨움이 '이미 받은 친구에게' 전체 재발송하던 문제 방지.
        try:
            status, j = _http_post_retry(
                "https://kapi.kakao.com/v1/api/talk/friends/message/default/send",
                dict(payload, receiver_uuids=json.dumps(chunk)), headers,
                what=f"메시지 발송(친구 {i + 1}~{i + len(chunk)}번째)")
        except Exception as e:
            print(f"[kakao] 친구 {i + 1}~{i + len(chunk)}번째 전송오류({e}) — 실패 처리")
            worst = (0, {"error": str(e)})
            continue
        if status != 200:
            worst = (status, j)
        elif j.get("failure_info"):
            print(f"[kakao] 일부 친구 수신 실패(개별 사유): {j['failure_info']}")
    return worst


def _is_weekend(now=None):
    """현재 KST 기준 주말(토·일) 여부. weekday(): 월=0 … 토=5, 일=6."""
    return (now or datetime.datetime.now(KST)).weekday() >= 5


def _slot_charts(weekend):
    """요일 유형별 슬롯→차트 매핑."""
    return SLOT_CHARTS_WEEKEND if weekend else SLOT_CHARTS_WEEKDAY


def _slot_hours(weekend):
    """요일 유형별 발송 시각 목록."""
    return SLOT_HOURS_WEEKEND if weekend else SLOT_HOURS_WEEKDAY


def _resolve_slot(weekend):
    """발송 슬롯(h07~h22) 판정 — 워크플로가 넘긴 KAKAO_SLOT 우선, 없거나 manual 이면
    현재 KST 시각에서 (해당 요일 유형의) 가장 가까운 슬롯을 고른다."""
    charts = _slot_charts(weekend)
    s = os.environ.get("KAKAO_SLOT", "").strip().lower()
    if s in charts:
        return s
    hr = datetime.datetime.now(KST).hour
    nearest = min(_slot_hours(weekend), key=lambda h: abs(h - hr))
    return f"h{nearest:02d}"


def _charts_enabled():
    """차트 이미지 발송 on/off — 기본 on. 끄려면 워크플로 변수 KAKAO_CHARTS=0."""
    return os.environ.get("KAKAO_CHARTS", "1").strip().lower() not in ("0", "false", "no", "off")


def _yahoo_chart_result(symbol, rng="1d", interval="5m"):
    """Yahoo 차트 API 의 result[0](meta + 시계열)을 반환. 실패 시 None.

    GitHub Actions 러너 IP 는 Yahoo 가 자주 403 으로 막으므로(fetch_data.py 와 동일 경험),
    직접 호출 실패 시 전용 Worker → 공개 CORS 프록시로 순차 우회한다."""
    try:
        import requests
        from urllib.parse import quote_plus
    except Exception:
        return None
    base = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            f"?range={rng}&interval={interval}")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"}
    candidates = [
        base,
        # 저장소 전용 Cloudflare 프록시(Yahoo 허용·헤더 주입 → 가장 안정적). 공개 프록시는 폴백.
        f"https://ecom-dashboard-proxy.baldr0001.workers.dev/?url={quote_plus(base)}",
        f"https://corsproxy.io/?{quote_plus(base)}",
        f"https://api.allorigins.win/raw?url={quote_plus(base)}",
        f"https://api.codetabs.com/v1/proxy/?quest={quote_plus(base)}",
    ]
    for url in candidates:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            res = (((r.json() or {}).get("chart") or {}).get("result") or [None])[0]
            if res:
                return res
        except Exception:
            continue
    return None


def _yahoo_intraday(symbol, rng="1d", interval="5m"):
    """당일(최근 세션) 인트라데이 (시각[KST naive] 목록, 가격 목록, 전일 종가). 실패 시 ([], [], None).

    전일 종가(chartPreviousClose)도 함께 반환해 차트 제목의 등락률을 '차트 마지막 값과 같은
    기준'으로 계산할 수 있게 한다 — data.json 스냅샷의 change 와 섞이면 값·등락률의 기준이
    어긋나 본문/차트 수치 불일치로 보였다(2026-06 사용자 보고)."""
    res = _yahoo_chart_result(symbol, rng, interval)
    if res:
        meta = res.get("meta") or {}
        prev = _f(meta.get("chartPreviousClose"))
        if prev is None:
            prev = _f(meta.get("previousClose"))
        ts = res.get("timestamp") or []
        quote = (((res.get("indicators") or {}).get("quote") or [{}])[0]) or {}
        closes = quote.get("close") or []
        xs, ys = [], []
        for t, c in zip(ts, closes):
            if c is None:
                continue
            xs.append(datetime.datetime.fromtimestamp(t, KST).replace(tzinfo=None))  # KST 로컬시각(naive)
            ys.append(float(c))
        if xs:
            return xs, ys, prev
    print(f"[chart] 인트라데이 실패({symbol}) — 7일 일봉으로 폴백")
    return [], [], None


def _yahoo_live_quote(symbol):
    """발송 시점 시세 — (현재가, 전일 종가 대비 %) 또는 None."""
    res = _yahoo_chart_result(symbol)
    if not res:
        return None
    meta = res.get("meta") or {}
    price = _f(meta.get("regularMarketPrice"))
    if price is None:
        closes = [c for c in ((((res.get("indicators") or {}).get("quote") or [{}])[0]) or {})
                  .get("close") or [] if c is not None]
        price = closes[-1] if closes else None
    if price is None or price <= 0:
        return None
    prev = _f(meta.get("chartPreviousClose"))
    if prev is None:
        prev = _f(meta.get("previousClose"))
    pct = ((price / prev) - 1) * 100 if prev else None
    return price, pct


# ── 본문 수치 라이브 보정 ────────────────────────────────────────────────────
# data.json 은 GitHub Actions cron 지연으로 수십 분~수 시간 묵을 수 있고, 환율(rate)은
# open.er-api 의 '일 1회 갱신' 값이라 장중 변동을 반영하지 못한다. 그 결과 같은 메시지에서
# 본문(달러-원 1,522.5)과 차트(1,531.08)가 어긋났다(2026-06-11 사용자 보고). 발송 직전에
# 차트와 같은 출처(Yahoo)의 시세로 본문 값을 덮어써 메시지 내부·실제 시세와 일치시킨다.
# 조회 실패 시 기존 data.json 값을 그대로 쓰므로 안전하다.
_LIVE_QUOTES = [
    ("indices", "KOSPI", "price", "^KS11"),
    ("indices", "SP500", "price", "^GSPC"),
    ("fx", "USDKRW", "rate", "KRW=X"),
    ("fx", "USDJPY", "rate", "JPY=X"),
    ("commodities", "WTI", "price", "CL=F"),
    ("commodities", "NatGas", "price", "NG=F"),
    ("commodities", "Gold", "price", "GC=F"),
    ("commodities", "Silver", "price", "SI=F"),
    ("commodities", "Copper", "price", "HG=F"),
    ("commodities", "Corn", "price", "ZC=F"),
    ("commodities", "Wheat", "price", "ZW=F"),
    ("commodities", "Soybean", "price", "ZS=F"),
]


def apply_live_quotes(d):
    """data.json 스냅샷의 본문용 수치를 발송 시점 Yahoo 시세로 보정(실패 항목은 기존 값 유지)."""
    from concurrent.futures import ThreadPoolExecutor
    syms = sorted({sym for _, _, _, sym in _LIVE_QUOTES} | {"^VIX"})
    try:
        with ThreadPoolExecutor(max_workers=6) as ex:
            quotes = dict(zip(syms, ex.map(_yahoo_live_quote, syms)))
    except Exception as e:
        print(f"[live] 시세 보정 실패(전체 생략): {e}")
        return
    updated = []
    for cat, key, field, sym in _LIVE_QUOTES:
        q = quotes.get(sym)
        if not q:
            continue
        price, pct = q
        node = (d.get(cat) or {}).get(key)
        if not isinstance(node, dict):
            node = {}
            d.setdefault(cat, {})[key] = node
        old = _f(node.get(field))
        # 기존 값 대비 ±20% 초과 차이는 심볼 오매핑/이상치로 보고 무시(기존 값 유지)
        if old and abs(price / old - 1) > 0.20:
            print(f"[live] {key} 이상치 의심({old} → {price}) — 보정 생략")
            continue
        node[field] = price
        if pct is not None:
            node["change"] = pct
        updated.append(f"{key}={price:,.2f}")
    # VIX — data.json 은 FRED VIXCLS(전일 종가)라 장중과 어긋남. 라이브 ^VIX 로 보정.
    vq = quotes.get("^VIX")
    if vq and vq[0]:
        us = d.setdefault("economicIndicators", {}).setdefault("us", {})
        vix = us.setdefault("vix", {})
        old = _f(vix.get("value"))
        if not old or abs(vq[0] / old - 1) <= 0.5:
            vix["value"] = vq[0]
            updated.append(f"VIX={vq[0]:.1f}")
    if updated:
        print("[live] 발송 시점 시세 보정: " + ", ".join(updated))


# ── 일본 국채 일별 수익률 (재무성 MOF CSV) ──────────────────────────────────
# FRED 의 일본 10년 국채는 '월별'뿐이라 카톡 차트가 1~2개월 묵은 값으로 나갔다
# (2026-07 사용자 보고: "45일·1년 단위 차트 = outdated"). 재무성이 매영업일 공표하는
# 국債金利情報 CSV(Shift-JIS, 연호 날짜)에서 10년물을 직접 읽어 일별 시계열로 그린다.
# 당월분(jgbcm.csv)은 월초엔 며칠뿐이라 과거 전체분(jgbcm_all.csv)과 병합해 45일을 채운다.
_MOF_JGB_URLS = (
    "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv",  # 과거 전체(~전월 말)
    "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv",           # 당월(매영업일 갱신)
)


def _parse_mof_era_date(s):
    """MOF 연호 날짜 → datetime. 'R8.7.2'(令和8년=2026) / 'H31.4.30'(平成31년=2019). 그 외 None."""
    m = re.match(r"([RH])(\d+)\.(\d+)\.(\d+)$", (s or "").strip())
    if not m:
        return None
    base = 2018 if m.group(1) == "R" else 1988   # 令和1=2019, 平成1=1989
    try:
        return datetime.datetime(base + int(m.group(2)), int(m.group(3)), int(m.group(4)))
    except ValueError:
        return None


def parse_jgb_10y(text):
    """MOF 국채금리 CSV 본문 → {'YYYY-MM-DD': 10년물 수익률(float)}.

    열 구성: 基準日,1年,…,9年,10年,15年,…,40年 → 10년물은 11번째 열(index 10).
    헤더·빈 행·꼬리 주석은 연호 날짜 파싱 실패로, 결측값('-')은 float 변환 실패로 걸러진다."""
    out = {}
    for ln in text.splitlines():
        cols = [c.strip() for c in ln.split(",")]
        if len(cols) < 11:
            continue
        dt = _parse_mof_era_date(cols[0])
        if not dt:
            continue
        try:
            out[dt.strftime("%Y-%m-%d")] = float(cols[10])
        except ValueError:
            pass
    return out


def _fetch_jgb_daily(n=45):
    """일본 10년 국채 '일별' 수익률 최근 n일 — {'YYYY-MM-DD': float}. 실패 시 빈 dict(→ 월별 폴백)."""
    merged = {}
    for url in _MOF_JGB_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                merged.update(parse_jgb_10y(r.read().decode("shift-jis", errors="replace")))
        except Exception as e:
            print(f"[chart] MOF JGB CSV 조회 실패({url.rsplit('/', 1)[-1]}): {e}")
    return dict(sorted(merged.items())[-n:])


def _yield_series(d, key, n_daily=45):
    """국채 수익률 시계열 → (xs[datetime], ys[float], monthly?).

    US10Y·KR10Y 는 yieldCurve.{us,kr} 의 10Y 텐서(일별, FRED DGS10 / ECOS),
    JP10Y 는 재무성 MOF CSV(일별) 우선, 실패 시 economicIndicators.jp.bond10y_jp
    (월별, FRED IRLTLT01JPM156N) 폴백.
    데이터가 아직 없으면(예: 파이프라인 미수집) 빈 시계열을 돌려 패널은 'N/A'로 그려진다."""
    if key == "JP10Y":
        daily = _fetch_jgb_daily(n_daily)
        if daily:
            xs = [datetime.datetime.strptime(ds, "%Y-%m-%d") for ds in daily]
            return xs, [float(v) for v in daily.values()], False
        print("[chart] JP10Y 일별(MOF) 없음 — FRED 월별로 폴백")
        hist = ((((d.get("economicIndicators") or {}).get("jp") or {})
                 .get("bond10y_jp") or {}).get("history") or {})
        xs, ys = [], []
        for ds, v in sorted(hist.items())[-12:]:   # 최근 12개월
            try:
                xs.append(datetime.datetime.strptime(ds, "%Y-%m-%d"))
                ys.append(float(v))
            except (ValueError, TypeError):
                pass
        return xs, ys, True
    region = "us" if key == "US10Y" else "kr"
    yc = (d.get("yieldCurve") or {}).get(region) or {}
    ser = next((s for s in (yc.get("series") or []) if s.get("tenor") == "10Y"), None)
    xs, ys = [], []
    for pt in ((ser or {}).get("data") or [])[-n_daily:]:
        v = pt.get("value")
        if v is None:
            continue
        try:
            xs.append(datetime.datetime.strptime(pt["date"], "%Y-%m-%d"))
            ys.append(float(v))
        except (ValueError, TypeError):
            pass
    return xs, ys, False


# 인트라데이 조회 가능한 수익률 — Yahoo ^TNX(CBOE 10년물 수익률 지수)는 값 자체가 %.
# (KR10Y·JP10Y 는 인트라데이 소스가 없어 일별 추세선 + 기준일 표기로 신선도를 드러낸다.)
_YIELD_INTRADAY_SYM = {"US10Y": "^TNX"}


def _draw_yield_panel(ax, d, key, label, color, mdates):
    """국채 수익률 패널 — 값은 '%', 변화는 'bp'로 표기.

    (수익률을 가격처럼 ±% 로 적으면 '4.0→4.4 = +10%' 식으로 오해를 부르므로 bp[=0.01%p] 사용.)
    US10Y 는 당일 인트라데이(^TNX) 우선 — 다른 자산 패널과 동일한 'today' 차트.
    일별·월별 추세선은 마지막 데이터가 오늘이 아니면 제목에 기준일(~M/D)을 붙여
    묵은 값이 최신처럼 보이지 않게 한다(2026-07 사용자 보고: 45d·12mo 차트 = outdated).
    grid·tick 은 호출부 루프가 'yield' 분기에서 즉시 continue 하므로 이 안에서 직접 적용한다."""
    sym = _YIELD_INTRADAY_SYM.get(key)
    if sym:
        xs, ys, prev = _yahoo_intraday(sym)
        if xs:
            ax.plot(xs, ys, color=color, linewidth=1.8)
            ax.fill_between(xs, ys, min(ys), color=color, alpha=0.08)
            chg_bp = (ys[-1] - prev) * 100 if prev else (ys[-1] - ys[0]) * 100
            ax.set_title(f"{label}   {ys[-1]:.2f}%  ({chg_bp:+.0f}bp / today)",
                         fontsize=26, loc="left")
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
            ax.grid(alpha=0.25)
            ax.tick_params(axis="both", labelsize=12)
            return
    xs, ys, monthly = _yield_series(d, key)
    if not xs:
        ax.text(0.5, 0.5, f"{label} N/A", ha="center", va="center", fontsize=24)
        ax.set_title(label, fontsize=26, loc="left")
        ax.grid(alpha=0.25)
        ax.tick_params(axis="both", labelsize=12)
        return
    ax.plot(xs, ys, color=color, linewidth=1.8,
            marker=("o" if len(xs) <= 14 else None), markersize=3)
    ax.fill_between(xs, ys, min(ys), color=color, alpha=0.08)
    chg_bp = (ys[-1] - ys[0]) * 100
    span = "12mo" if monthly else f"{len(xs)}d"
    # 마지막 데이터가 오늘(KST)이 아니면 기준일을 표기 — 신선도가 제목에서 바로 보이게.
    asof = ""
    if xs[-1].date() < datetime.datetime.now(KST).date():
        asof = f", ~{xs[-1].month}/{xs[-1].day}"
    ax.set_title(f"{label}   {ys[-1]:.2f}%  ({chg_bp:+.0f}bp / {span}{asof})",
                 fontsize=26, loc="left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m" if monthly else "%m-%d"))
    ax.grid(alpha=0.25)
    ax.tick_params(axis="both", labelsize=12)


def build_slot_chart_png(d, slot, weekend, out_path="/tmp/kakao_chart.png"):
    """슬롯별 지표 2종을 '당일(인트라데이)' 차트 1장 PNG(CHART_PX=1080x1440, 3:4 세로형)로 생성.

    당일 시세는 Yahoo 차트 API 에서 직접 조회(data.json 엔 일별 종가만 있음). 당일 조회 실패 시
    data.json history 의 7일 일봉으로 폴백. matplotlib 미설치/생성 실패 시 None(→ 텍스트 폴백)."""
    spec = _slot_charts(weekend).get(slot)
    if not spec:
        return None
    panels, suptitle = spec
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except Exception as e:
        print(f"[chart] matplotlib 미설치 — 이미지 생략 ({e})")
        return None
    h = d.get("history", {}) or {}

    def daily_series(cat, key, n=7):
        arr = [x for x in ((h.get(cat) or {}).get(key) or []) if x.get("close") is not None][-n:]
        xs, ys = [], []
        for x in arr:
            try:
                xs.append(datetime.datetime.strptime(x["date"], "%Y-%m-%d"))
                ys.append(float(x["close"]))
            except (ValueError, TypeError):
                pass
        return xs, ys

    try:
        fig, axes = plt.subplots(2, 1, figsize=(CHART_PX[0] / _CHART_DPI, CHART_PX[1] / _CHART_DPI))
        # 기간(today/7d)은 패널별 제목에 표기 — 인트라데이/일봉 폴백이 섞일 수 있어 전체 제목엔 넣지 않는다.
        # 폰트는 채팅방 표시 기준으로 보이도록 크게(2026-06 사용자 요청: 이미지 안 수치가 작음).
        # 이미지(1080px)가 말풍선 폭(약 270dp)으로 1/4 축소되므로, 패널 제목이 카톡 본문
        # 글씨(약 15dp)와 같아 보이려면 26pt(150dpi에서 약 54px)가 필요하다.
        fig.suptitle(suptitle, fontsize=17, x=0.02, ha="left", weight="bold")
        for a, (cat, key, label) in zip(axes, panels):
            color = _CHART_COLOR.get(key, "#333333")
            # 국채 수익률 패널은 별도 경로(yieldCurve/economicIndicators) — % 값·bp 변화로 그린다.
            if cat == "yield":
                _draw_yield_panel(a, d, key, label, color, mdates)
                continue
            # 1순위: 당일 인트라데이(Yahoo). 실패 시 7일 일봉으로 폴백.
            xs, ys, prev_close = _yahoo_intraday(_YH_SYM.get(key, "")) if _YH_SYM.get(key) else ([], [], None)
            intraday = bool(xs)
            if not xs:
                xs, ys = daily_series(cat, key, 7)
            if xs:
                a.plot(xs, ys, color=color, linewidth=1.8,
                       marker=("o" if (not intraday and len(xs) <= 10) else None), markersize=3)
                a.fill_between(xs, ys, min(ys), color=color, alpha=0.08)
                # 제목 수치(값·등락률)는 본문과 '동일한 출처'(apply_live_quotes 로 보정된 d)에서 읽어
                # 본문과 차트가 절대 어긋나지 않게 한다 — 차트 '선'은 시계열을 그대로 그리되 제목 숫자만 본문과 맞춘다.
                # (2026-06 사용자 보고: 본문 '금 ▼3.0%' 인데 차트 'Gold +3.1%' 로 부호가 반대였던 사례 —
                #  본문·차트가 서로 다른 fetch 를 써서 전일종가 기준이 어긋난 탓. 이제 단일 출처로 통일.)
                node = (d.get(cat, {}) or {}).get(key) or {}
                disp_val = _f(node.get("price"))
                if disp_val is None:
                    disp_val = _f(node.get("rate"))
                if disp_val is None:
                    disp_val = ys[-1]
                disp_chg = _f(node.get("change"))
                if disp_chg is None:   # d 에 등락률이 없을 때만 시계열로 추정
                    if intraday and prev_close:
                        disp_chg = (ys[-1] / prev_close - 1) * 100
                    else:
                        disp_chg = (ys[-1] / ys[0] - 1) * 100 if ys[0] else 0.0
                span = "today" if intraday else "7d"
                a.set_title(f"{label}   {disp_val:,.2f}  ({disp_chg:+.1f}% / {span})", fontsize=26, loc="left")
                a.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if intraday else "%m-%d"))
            else:
                a.text(0.5, 0.5, f"{label} N/A", ha="center", va="center", fontsize=24)
                a.set_title(label, fontsize=26, loc="left")
            a.grid(alpha=0.25)
            a.tick_params(axis="both", labelsize=12)
        fig.tight_layout(rect=[0, 0, 1, 0.97])
        fig.savefig(out_path, dpi=_CHART_DPI)
        plt.close(fig)
        return out_path
    except Exception as e:
        print(f"[chart] 생성 실패 ({e})")
        try:
            plt.close("all")
        except Exception:
            pass
        return None


def kakao_upload_image(access_token, png_path):
    """차트 PNG 를 카카오 이미지 서버에 업로드하고 image_url 반환(실패 시 None).

    카카오 CDN URL 을 받으므로 사이트 도메인/호스팅 등록이 필요 없다.
    일시 네트워크 장애로 차트 없는 메시지가 나가지 않도록 전송 오류는 재시도한다."""
    try:
        import requests
    except Exception as e:
        print(f"[chart] requests 미설치 — 업로드 생략 ({e})")
        return None

    def _upload():
        with open(png_path, "rb") as fp:
            return requests.post(
                "https://kapi.kakao.com/v2/api/talk/message/image/upload",
                headers={"Authorization": f"Bearer {access_token}"},
                files={"file": fp}, timeout=25)
    # 전송오류(예외)뿐 아니라 일시 서버오류(429/5xx)도 재시도한다 — 카카오 이미지 서버가 429/502 를
    # 한 번 돌려주면 (구) _retry 는 그대로 None 을 반환해 '차트 없는 텍스트 폴백'으로 나갔다
    # (사용자 보고: "가끔 사진이 안 뜸"). 이제 업로드도 토큰/발송과 같은 백오프 재시도를 쓴다.
    tries, delay = 3, 2
    for i in range(tries):
        try:
            r = _upload()
        except Exception as e:
            if i == tries - 1:
                print(f"[chart] 업로드 오류 ({e})")
                return None
            print(f"[retry] 차트 업로드 전송오류({e}) — {delay}s 후 재시도 ({i + 2}/{tries})")
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code == 200:
            url = (((r.json().get("infos") or {}).get("original") or {}).get("url"))
            if url:
                print(f"[chart] 업로드 성공: {url}")
            return url
        if r.status_code in RETRYABLE_STATUS and i < tries - 1:
            print(f"[retry] 차트 업로드 HTTP {r.status_code} — {delay}s 후 재시도 ({i + 2}/{tries})")
            time.sleep(delay)
            delay *= 2
            continue
        print(f"[chart] 업로드 실패 HTTP {r.status_code}: {r.text[:200]}")
        return None
    return None


def build_feed_parts(blocks):
    """공통 블록 → 피드용 (description, items).

    설명(2줄): 증시(코스피·S&P) / 환율(달러-원·달러-엔) — 헤드라인.
    행(item): 심리 / 에너지 / 금속 / 곡물 / 운임 — 카카오 피드 행 한도(5개)와 일치.
    일곱 카테고리가 항상 한 통에 모두 담기며, 행 값이 길어 뒤가 잘리는 일이 없게 배치한다."""
    val = dict(blocks)
    desc = "\n".join(x for x in (val.get("증시", ""), val.get("환율", "")) if x)
    items = [{"item": lab, "item_op": val[lab]}
             for lab in ("심리", "에너지", "금속", "곡물", "운임") if val.get(lab)]
    return desc, items


def send_feed(access_token, title, description, image_url, items=None, dims=CHART_PX, uuids=None):
    """피드 한 통 — 차트 이미지 + 제목 + 증시·환율(설명) + 심리·에너지·금속·곡물·운임(행) + '대시보드 보기' 버튼."""
    content = {
        "title": title,
        "description": description,
        "image_url": image_url,
        "image_width": dims[0], "image_height": dims[1],
        "link": {"web_url": DASHBOARD_URL, "mobile_web_url": DASHBOARD_URL},
    }
    template = {
        "object_type": "feed",
        "content": content,
        "buttons": [{"title": "대시보드 보기",
                     "link": {"web_url": DASHBOARD_URL, "mobile_web_url": DASHBOARD_URL}}],
    }
    if items:
        template["item_content"] = {"items": items[:5]}
    status, j = _send_template_object(access_token, template, uuids=uuids)
    if status != 200:
        print(f"[kakao] 피드 발송 실패 HTTP {status}: {j}")
        return False
    print(f"[kakao] 피드(차트) 발송 성공\n{title} | {description} | 행 {len(items) if items else 0}개")
    return True


def send_chart_feed(access_token, data, title, blocks, slot, weekend, uuids=None):
    """슬롯 차트 생성→업로드→'한 통' 피드 발송. 한 단계라도 실패 시 False(→ 동일 내용 텍스트 폴백)."""
    png = build_slot_chart_png(data, slot, weekend)
    if not png:
        return False
    image_url = kakao_upload_image(access_token, png)
    if not image_url:
        return False
    desc, items = build_feed_parts(blocks)
    if send_feed(access_token, title, desc, image_url, items=items, uuids=uuids):
        return True
    # 행(item_content)이 거부되면 행 내용을 설명에 합쳐 한 통 더 시도 → 내용 손실 없이 '한 통' 보장.
    print("[kakao] 피드(행 포함) 실패 — 행 내용을 설명으로 합쳐 재시도")
    full_desc = "\n".join([desc] + [f"{it['item']} {it['item_op']}" for it in (items or [])])
    return send_feed(access_token, title, full_desc, image_url, items=None, uuids=uuids)


def send_memo(access_token, text, with_button=True, uuids=None):
    """기본 텍스트 템플릿 발송 — 차트 피드 실패 시 최후 폴백(내용은 동일, 수신 모드도 동일)."""
    template = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": DASHBOARD_URL, "mobile_web_url": DASHBOARD_URL},
    }
    if with_button:
        template["button_title"] = "대시보드 보기"
    status, j = _send_template_object(access_token, template, uuids=uuids)
    if status != 200:
        raise SystemExit(f"[kakao] 메시지 발송 실패: HTTP {status} {j}")
    print(f"[kakao] 텍스트 발송 성공 ({len(text)}자):\n{text}")


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

    weekend = _is_weekend()                          # 주말(토·일)이면 11·17시만, 사진은 달러원·금
    slot = _resolve_slot(weekend)
    apply_live_quotes(data)                          # 본문 수치를 발송 시점 시세로 보정(차트와 동일 출처)
    title, blocks = build_digest_parts(data)         # 제목 시각은 실제 발송 시각(now) 기준

    # 토큰 재발급·발송 실패는 '매 슬롯(평일 16회) 실행'이라 job 실패 시 GitHub 실패 알림 메일이
    # 슬롯마다 쏟아진다. (2026-07-08 18:00 KST~ KAKAO_REFRESH_TOKEN 만료/회전 추정으로 전 슬롯
    # 실패가 연속 발생해 실패 알림이 도배된 사건.) check_alerts.py 와 동일하게 SystemExit 를 삼켜
    # ::warning + 정상 종료(exit 0)로 알림 스팸을 막는다. 단, 이는 '증상(스팸)'만 멈추는 것 —
    # 토큰 만료면 KAKAO_SETUP.md ③ 절차로 KAKAO_REFRESH_TOKEN 시크릿을 갱신해야 실제 발송이 복구된다.
    try:
        access_token = refresh_access_token(rest_key, refresh_token)

        # 수신 모드 자동 판별 — 연결·동의된 친구가 있으면 '친구에게 보내기'(푸시 알림 정상),
        # 없으면 종전대로 '나에게 보내기'(나와의 채팅, 알림 없음).
        friends = get_friends(access_token) if _friends_enabled() else []
        uuids = [f["uuid"] for f in friends]
        if uuids:
            names = ", ".join(f.get("profile_nickname") or "?" for f in friends)
            print(f"[kakao] 수신: 친구 {len(uuids)}명 ({names})")
        else:
            print("[kakao] 수신: 나와의 채팅(메모)")

        # ① 기본(통일) 형식 = '한 통' 피드: 슬롯별 차트 이미지 + 증시·환율(설명)
        #    + 심리·에너지·금속·곡물·운임(행) + '대시보드 보기' 버튼.
        #    차트는 당일 인트라데이, 없으면 7일 일봉 폴백.
        if _charts_enabled():
            if send_chart_feed(access_token, data, title, blocks, slot, weekend, uuids=uuids):
                print(f"[kakao] 발송 완료 (차트 피드 한 통, slot={slot})")
                return
            print("[kakao] 차트 피드 실패 — 동일 내용 텍스트로 폴백")

        # ② 최후 폴백: 기본 텍스트 한 통 — 피드와 '동일한 공통 블록(증시~운임)' + '대시보드 보기' 버튼.
        #    (콘솔 커스텀 템플릿 폴백은 형식이 달라 혼란을 줬으므로 제거 — 2026-06-10 10시 사례)
        send_memo(access_token, build_text_message(title, blocks), with_button=True, uuids=uuids)
        print(f"[kakao] 발송 완료 (텍스트 폴백, slot={slot})")
    except SystemExit as e:
        print(f"::warning title=Kakao 발송 건너뜀::{e} — 토큰 만료/회전 또는 발송 실패 추정. "
              "KAKAO_SETUP.md ③ 절차로 KAKAO_REFRESH_TOKEN 시크릿을 갱신하면 다음 슬롯부터 발송이 복구됩니다. "
              "(워크플로는 정상 종료 — 매 슬롯 실패 알림 메일 방지)")


if __name__ == "__main__":
    main()
