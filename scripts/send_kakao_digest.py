#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""매일 07~17시 매시간 + 20·22시(KST, :03) data.json 시황을 카카오톡으로 발송한다.

수신 모드(자동 판별):
  * 친구에게 보내기(우선) — 앱과 연결·동의된 카카오톡 친구가 있으면 그 친구들에게 발송.
    일반 메시지처럼 '푸시 알림'이 울린다. (2026-06 사용자 요청: 나에게 보내기는 내가 보낸
    메시지라 알림이 없음 → 보조 계정을 발신자로 두고 본 계정을 친구로 수신.)
    검수 전 앱은 '팀 멤버'로 등록된 친구만 조회된다. 설정 절차는 KAKAO_SETUP.md ⑤ 참고.
    쿼터: 발신자당 일 100건·발신자→수신자 쌍당 일 20건 — 하루 13회 발송 기준 친구 7명까지 안전.
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

슬롯별 차트(모두 이미지·당일 기준, 당일이 없으면 7일 폴백):
  07~09시          → S&P500 + 달러-원
  10~17시          → 코스피 + 달러-원
  20·22시          → 달러-원 + WTI

신뢰성 원칙 — '형식이 다른 메시지'가 다시는 나가지 않도록:
  * 모든 카카오 API 호출(토큰 재발급·이미지 업로드·발송)에 지수 백오프 재시도.
    (2026-06-10 10시 발송이 러너의 일시적 DNS 실패 1회로 차트 없는 콘솔 템플릿 폴백으로
     나간 사례의 재발 방지 — 콘솔 커스텀 템플릿 폴백 경로 자체도 제거했다.)
  * 모든 단계가 같은 build_digest_parts() 의 내용을 쓰므로, 최후 폴백(텍스트)도
    이미지 유무만 다를 뿐 '내용 구성'은 동일하다.

설정 방법(1회): 저장소 루트 KAKAO_SETUP.md 참고.
"""
import os
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

# ── 발송 슬롯 — 매일 13회(KST): 07~17시 매시간 + 20·22시. 워크플로 게이트·차트 구성·제목 표기가
#    모두 이 목록 기준. (2026-06 사용자 요청: 07~16시 매시간으로 확대, 저녁 17·20·22시는 유지) ──
SLOT_HOURS = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 20, 22]
SLOT_HOUR = {f"h{h:02d}": f"{h}시" for h in SLOT_HOURS}

# 슬롯별 차트 구성 — (history 카테고리, 키, 라벨) 2개를 1장(위·아래)으로 합쳐 보낸다.
# (라벨은 CI 한글폰트 부재 대비 영문)
_CHART_US = ([("indices", "SP500", "S&P 500"), ("fx", "USDKRW", "USD/KRW")],
             "S&P500 / USD-KRW")
_CHART_KR = ([("indices", "KOSPI", "KOSPI"), ("fx", "USDKRW", "USD/KRW")],
             "KOSPI / USD-KRW")
_CHART_EVE = ([("fx", "USDKRW", "USD/KRW"), ("commodities", "WTI", "WTI Crude")],
              "USD-KRW / WTI")
SLOT_CHARTS = {
    "h07": _CHART_US, "h08": _CHART_US, "h09": _CHART_US,
    "h10": _CHART_KR, "h11": _CHART_KR, "h12": _CHART_KR, "h13": _CHART_KR,
    "h14": _CHART_KR, "h15": _CHART_KR, "h16": _CHART_KR, "h17": _CHART_KR,
    "h20": _CHART_EVE, "h22": _CHART_EVE,
}
_CHART_COLOR = {"KOSPI": "#2962ff", "SP500": "#1e88e5", "USDKRW": "#26a69a", "WTI": "#ef6c00"}
# 당일(인트라데이) 시세용 Yahoo Finance 심볼 — data.json 엔 일별 종가만 있어 차트 생성 시 직접 조회한다.
_YH_SYM = {"KOSPI": "^KS11", "SP500": "^GSPC", "USDKRW": "KRW=X", "WTI": "CL=F"}
# 차트 PNG 크기(px) — 카톡 피드 이미지는 말풍선 '폭'이 고정이고 높이만 비율을 따라 늘어나므로,
# 가로형(구 720x640)은 화면에서 작게 보인다. 잘리지 않는 최대 세로 비율(3:4)·고해상도로 키운다.
# (2026-06 사용자 요청: 카톡 사진이 작아 잘 안 보임)
_CHART_DPI = 150
CHART_PX = (1080, 1440)


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


def _http_post_retry(url, form, headers=None, what="HTTP POST"):
    return _retry(lambda: _http_post(url, form, headers), what)


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
        print("::warning title=KAKAO_REFRESH_TOKEN::카카오가 새 refresh_token 을 발급했습니다. "
              "GitHub Secret 의 KAKAO_REFRESH_TOKEN 을 새 값으로 교체하세요(로그에는 마스킹됨).")
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


def build_digest_parts(d, slot=None):
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

    now = datetime.datetime.now(KST)
    wd = "월화수목금토일"[now.weekday()]
    hh = SLOT_HOUR.get(slot, "")
    title = f"{now.month}/{now.day}({wd}) {hh} 시황".replace("  ", " ")

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
    if vix and vix.get("value") is not None:
        pl.append(f"VIX {_num(vix['value'], 1)}")
    vk = sent.get("vkospi")   # 코스피 위험지수(KOSPI 변동성지수, VKOSPI)
    if vk and vk.get("value") is not None:
        pl.append(f"VKOSPI {_num(vk['value'], 1)}")
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
        status, j = _retry(lambda: _http_get(
            "https://kapi.kakao.com/v1/api/talk/friends?limit=100",
            {"Authorization": f"Bearer {access_token}"}), "친구 목록 조회")
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
        status, j = _http_post_retry(
            "https://kapi.kakao.com/v1/api/talk/friends/message/default/send",
            dict(payload, receiver_uuids=json.dumps(chunk)), headers,
            what=f"메시지 발송(친구 {i + 1}~{i + len(chunk)}번째)")
        if status != 200:
            worst = (status, j)
        elif j.get("failure_info"):
            print(f"[kakao] 일부 친구 수신 실패(개별 사유): {j['failure_info']}")
    return worst


def _resolve_slot():
    """발송 슬롯(h07~h22) 판정 — 워크플로가 넘긴 KAKAO_SLOT 우선, 없거나 manual 이면
    현재 KST 시각에서 가장 가까운 슬롯을 고른다."""
    s = os.environ.get("KAKAO_SLOT", "").strip().lower()
    if s in SLOT_CHARTS:
        return s
    hr = datetime.datetime.now(KST).hour
    nearest = min(SLOT_HOURS, key=lambda h: abs(h - hr))
    return f"h{nearest:02d}"


def _charts_enabled():
    """차트 이미지 발송 on/off — 기본 on. 끄려면 워크플로 변수 KAKAO_CHARTS=0."""
    return os.environ.get("KAKAO_CHARTS", "1").strip().lower() not in ("0", "false", "no", "off")


def _yahoo_intraday(symbol, rng="1d", interval="5m"):
    """Yahoo 차트 API 에서 당일(최근 세션) 인트라데이 (시각[KST naive], 가격) 시계열. 실패 시 ([], []).

    GitHub Actions 러너 IP 는 Yahoo 가 자주 403 으로 막으므로(fetch_data.py 와 동일 경험),
    직접 호출 실패 시 공개 CORS 프록시(corsproxy.io / allorigins.win / codetabs)로 순차 우회한다."""
    try:
        import requests
        from urllib.parse import quote_plus
    except Exception:
        return [], []
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
            if not res:
                continue
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
                return xs, ys
        except Exception:
            continue
    print(f"[chart] 인트라데이 실패({symbol}) — 7일 일봉으로 폴백")
    return [], []


def build_slot_chart_png(d, slot, out_path="/tmp/kakao_chart.png"):
    """슬롯별 지표 2종을 '당일(인트라데이)' 차트 1장 PNG(CHART_PX=1080x1440, 3:4 세로형)로 생성.

    당일 시세는 Yahoo 차트 API 에서 직접 조회(data.json 엔 일별 종가만 있음). 당일 조회 실패 시
    data.json history 의 7일 일봉으로 폴백. matplotlib 미설치/생성 실패 시 None(→ 텍스트 폴백)."""
    spec = SLOT_CHARTS.get(slot)
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

    def snap_change(cat, key):
        o = (d.get(cat, {}) or {}).get(key) or {}
        return _f(o.get("change"))

    try:
        fig, axes = plt.subplots(2, 1, figsize=(CHART_PX[0] / _CHART_DPI, CHART_PX[1] / _CHART_DPI))
        # 기간(today/7d)은 패널별 제목에 표기 — 인트라데이/일봉 폴백이 섞일 수 있어 전체 제목엔 넣지 않는다.
        # 폰트는 채팅방 표시 기준으로 보이도록 크게(2026-06 사용자 요청: 이미지 안 수치가 작음).
        # 이미지(1080px)가 말풍선 폭(약 270dp)으로 1/4 축소되므로, 패널 제목이 카톡 본문
        # 글씨(약 15dp)와 같아 보이려면 26pt(150dpi에서 약 54px)가 필요하다.
        fig.suptitle(suptitle, fontsize=17, x=0.02, ha="left", weight="bold")
        for a, (cat, key, label) in zip(axes, panels):
            color = _CHART_COLOR.get(key, "#333333")
            # 1순위: 당일 인트라데이(Yahoo). 실패 시 7일 일봉으로 폴백.
            xs, ys = _yahoo_intraday(_YH_SYM.get(key, "")) if _YH_SYM.get(key) else ([], [])
            intraday = bool(xs)
            if not xs:
                xs, ys = daily_series(cat, key, 7)
            if xs:
                a.plot(xs, ys, color=color, linewidth=1.8,
                       marker=("o" if (not intraday and len(xs) <= 10) else None), markersize=3)
                a.fill_between(xs, ys, min(ys), color=color, alpha=0.08)
                chg = snap_change(cat, key)
                if chg is None:
                    chg = (ys[-1] / ys[0] - 1) * 100 if ys[0] else 0.0
                span = "today" if intraday else "7d"
                a.set_title(f"{label}   {ys[-1]:,.2f}  ({chg:+.1f}% / {span})", fontsize=26, loc="left")
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
    try:
        r = _retry(_upload, "차트 업로드")
        if r.status_code != 200:
            print(f"[chart] 업로드 실패 HTTP {r.status_code}: {r.text[:200]}")
            return None
        url = (((r.json().get("infos") or {}).get("original") or {}).get("url"))
        if url:
            print(f"[chart] 업로드 성공: {url}")
        return url
    except Exception as e:
        print(f"[chart] 업로드 오류 ({e})")
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


def send_chart_feed(access_token, data, title, blocks, slot, uuids=None):
    """슬롯 차트 생성→업로드→'한 통' 피드 발송. 한 단계라도 실패 시 False(→ 동일 내용 텍스트 폴백)."""
    png = build_slot_chart_png(data, slot)
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

    slot = _resolve_slot()
    title, blocks = build_digest_parts(data, slot)   # 제목에 슬롯 시각(7~22시) 포함
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
        if send_chart_feed(access_token, data, title, blocks, slot, uuids=uuids):
            print(f"[kakao] 발송 완료 (차트 피드 한 통, slot={slot})")
            return
        print("[kakao] 차트 피드 실패 — 동일 내용 텍스트로 폴백")

    # ② 최후 폴백: 기본 텍스트 한 통 — 피드와 '동일한 공통 블록(증시~운임)' + '대시보드 보기' 버튼.
    #    (콘솔 커스텀 템플릿 폴백은 형식이 달라 혼란을 줬으므로 제거 — 2026-06-10 10시 사례)
    send_memo(access_token, build_text_message(title, blocks), with_button=True, uuids=uuids)
    print(f"[kakao] 발송 완료 (텍스트 폴백, slot={slot})")


if __name__ == "__main__":
    main()
