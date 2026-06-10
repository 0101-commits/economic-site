#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""매일 07/09/10/12/15/17/20/22시(KST, :03) data.json 시황을 카카오톡으로 발송한다.

기본은 '나에게 보내기'(나와의 채팅)이며, 선택적으로 같은 한 통을 '친구에게 보내기'
API 로 지정한 친구들에게도 발송할 수 있다(아래 친구 발송 참고).

필요한 GitHub Secrets:
  KAKAO_REST_API_KEY   — 카카오 개발자 앱의 REST API 키
  KAKAO_REFRESH_TOKEN  — talk_message 동의로 발급한 refresh_token
                         (친구 발송까지 쓰려면 scope=talk_message,friends 로 발급)

친구 발송(선택) — KAKAO_SETUP.md '친구에게도 보내기' 절 참고:
  변수 KAKAO_SEND_TO_FRIENDS=1  → 앱과 연결된(메시지 수신 허용) 모든 친구에게 발송
  시크릿 KAKAO_FRIEND_UUIDS     → 쉼표 구분 uuid 로 특정 친구만 지정('all'=전체)
  uuid 확인: 로컬에서 `python scripts/send_kakao_digest.py --list-friends`
  ※ 카카오는 '오픈채팅방 발송 API'를 제공하지 않는다(비공식 자동화는 계정 제재 위험).
    불특정 다수에게 보내려면 카카오톡 채널(비즈니스, 사업자 필요)이 공식 경로다.

발송 형식은 '단 한 가지(통일)' — 피드 한 통:
  슬롯별 차트 이미지(당일 인트라데이, 없으면 7일 일봉 폴백)
  + 제목('M/D(요일) H시 시황')
  + 공통 내용 7종: 증시(코스피·S&P) / 환율(달러-원·달러-엔)
    / 심리(공포탐욕·VIX·VKOSPI 코스피위험지수) / 에너지(WTI·천연가스)
    / 금속(금·구리) / 곡물(옥수수·밀·대두) / 운임(SCFI 상하이컨테이너운임지수)
  + '대시보드 보기' 버튼.
  (2026-06 사용자 요청: 시장심리에 코스피위험지수 추가, 원자재를 에너지·금속·곡물로
   분리, 상하이 운임지수 포함. 친구에게도 '나에게 보내기'와 완전히 동일한 한 통이 간다.)

슬롯별 차트(모두 이미지·당일 기준, 당일이 없으면 7일 폴백):
  07·09시          → S&P500 + 달러-원
  10·12·15·17시    → 코스피 + 달러-원
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

# ── 발송 슬롯 — 매일 8회(KST). 워크플로 게이트·차트 구성·제목 표기가 모두 이 목록 기준 ──
SLOT_HOURS = [7, 9, 10, 12, 15, 17, 20, 22]
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
    "h07": _CHART_US, "h09": _CHART_US,
    "h10": _CHART_KR, "h12": _CHART_KR, "h15": _CHART_KR, "h17": _CHART_KR,
    "h20": _CHART_EVE, "h22": _CHART_EVE,
}
_CHART_COLOR = {"KOSPI": "#2962ff", "SP500": "#1e88e5", "USDKRW": "#26a69a", "WTI": "#ef6c00"}
# 당일(인트라데이) 시세용 Yahoo Finance 심볼 — data.json 엔 일별 종가만 있어 차트 생성 시 직접 조회한다.
_YH_SYM = {"KOSPI": "^KS11", "SP500": "^GSPC", "USDKRW": "KRW=X", "WTI": "CL=F"}


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


def _send_template_object(access_token, template):
    return _http_post_retry(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        {"template_object": json.dumps(template, ensure_ascii=False)},
        headers={"Authorization": f"Bearer {access_token}"},
        what="메시지 발송",
    )


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
    """슬롯별 지표 2종을 '당일(인트라데이)' 차트 1장 PNG(720x640)로 생성.

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
        fig, axes = plt.subplots(2, 1, figsize=(7.2, 6.4))
        # 기간(today/7d)은 패널별 제목에 표기 — 인트라데이/일봉 폴백이 섞일 수 있어 전체 제목엔 넣지 않는다.
        fig.suptitle(suptitle, fontsize=13, x=0.02, ha="left", weight="bold")
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
                a.set_title(f"{label}   {ys[-1]:,.2f}  ({chg:+.1f}% / {span})", fontsize=12, loc="left")
                a.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if intraday else "%m-%d"))
            else:
                a.text(0.5, 0.5, f"{label} N/A", ha="center", va="center", fontsize=11)
                a.set_title(label, fontsize=12, loc="left")
            a.grid(alpha=0.25)
            for lbl in a.get_xticklabels():
                lbl.set_fontsize(8)
        fig.tight_layout(rect=[0, 0, 1, 0.97])
        fig.savefig(out_path, dpi=100)
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


def _feed_template(title, description, image_url, items=None, dims=(720, 640)):
    """피드 템플릿 dict — '나에게 보내기'와 '친구에게 보내기'가 같은 객체를 공유한다."""
    template = {
        "object_type": "feed",
        "content": {
            "title": title,
            "description": description,
            "image_url": image_url,
            "image_width": dims[0], "image_height": dims[1],
            "link": {"web_url": DASHBOARD_URL, "mobile_web_url": DASHBOARD_URL},
        },
        "buttons": [{"title": "대시보드 보기",
                     "link": {"web_url": DASHBOARD_URL, "mobile_web_url": DASHBOARD_URL}}],
    }
    if items:
        template["item_content"] = {"items": items[:5]}
    return template


def _text_template(text, with_button=True):
    """텍스트 템플릿 dict — 차트 피드 실패 시 최후 폴백(내용은 동일)."""
    template = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": DASHBOARD_URL, "mobile_web_url": DASHBOARD_URL},
    }
    if with_button:
        template["button_title"] = "대시보드 보기"
    return template


def send_feed(access_token, template):
    """피드 한 통을 '나에게 보내기'로 발송. 성공 시 True."""
    status, j = _send_template_object(access_token, template)
    if status != 200:
        print(f"[kakao] 피드 발송 실패 HTTP {status}: {j}")
        return False
    c = template.get("content", {})
    n_items = len((template.get("item_content") or {}).get("items") or [])
    print(f"[kakao] 피드(차트) 발송 성공\n{c.get('title')} | {c.get('description')} | 행 {n_items}개")
    return True


def send_chart_feed(access_token, data, title, blocks, slot):
    """슬롯 차트 생성→업로드→'한 통' 피드 발송.

    성공 시 발송한 템플릿 dict 를 반환(친구 발송에 동일 재사용),
    한 단계라도 실패하면 None(→ 동일 내용 텍스트 폴백)."""
    png = build_slot_chart_png(data, slot)
    if not png:
        return None
    image_url = kakao_upload_image(access_token, png)
    if not image_url:
        return None
    desc, items = build_feed_parts(blocks)
    template = _feed_template(title, desc, image_url, items=items)
    if send_feed(access_token, template):
        return template
    # 행(item_content)이 거부되면 행 내용을 설명에 합쳐 한 통 더 시도 → 내용 손실 없이 '한 통' 보장.
    print("[kakao] 피드(행 포함) 실패 — 행 내용을 설명으로 합쳐 재시도")
    full_desc = "\n".join([desc] + [f"{it['item']} {it['item_op']}" for it in (items or [])])
    template = _feed_template(title, full_desc, image_url, items=None)
    return template if send_feed(access_token, template) else None


def send_memo(access_token, text, with_button=True):
    """카카오톡 '나에게 보내기'(기본 텍스트 템플릿) — 발송한 템플릿 dict 반환."""
    template = _text_template(text, with_button)
    status, j = _send_template_object(access_token, template)
    if status != 200:
        raise SystemExit(f"[kakao] 메시지 발송 실패: HTTP {status} {j}")
    print(f"[kakao] 텍스트 발송 성공 ({len(text)}자):\n{text}")
    return template


# ── 친구에게 보내기 (선택 기능) ──────────────────────────────────────────
# 카카오 공식 '친구에게 기본 템플릿 보내기' API. 오픈채팅방 발송 API 는 카카오가 제공하지
# 않으므로(비공식 자동화는 운영정책 위반·계정 제재 위험), 지인 공유는 이 경로가 공식이다.
# 전제(KAKAO_SETUP.md '친구에게도 보내기'): ① 토큰에 friends 동의 포함 ② 수신자도 같은
# 앱에 1회 로그인(연결) ③ 변수 KAKAO_SEND_TO_FRIENDS=1 (또는 KAKAO_FRIEND_UUIDS 지정).
FRIENDS_LIST_URL = "https://kapi.kakao.com/v1/api/talk/friends"
FRIENDS_SEND_URL = "https://kapi.kakao.com/v1/api/talk/friends/message/default/send"


def _http_get(url, headers=None):
    """GET → (status, json). 4xx/5xx 응답은 그대로 반환하고, 전송 오류(DNS 등)만 예외."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return e.code, {}


def _mask_uuid(u):
    """공개 저장소 CI 로그 보호 — uuid 는 앞 6자만 남기고 마스킹."""
    return (u[:6] + "…") if isinstance(u, str) and len(u) > 6 else "?"


def get_app_friends(access_token):
    """앱과 연결되고 메시지 수신을 허용한 친구 목록 [{uuid, nickname}].

    refresh_token 에 friends 동의가 없으면(-402) 재발급 안내 경고를 남기고 None.
    수신자가 목록에 없으면: 수신자도 같은 카카오 앱에 로그인(연결)해야 한다."""
    out, offset = [], 0
    while True:
        status, j = _retry(
            lambda: _http_get(f"{FRIENDS_LIST_URL}?limit=100&offset={offset}",
                              {"Authorization": f"Bearer {access_token}"}),
            "친구 목록 조회")
        if status != 200:
            if j.get("code") == -402:
                print("::warning title=Kakao 친구 발송::토큰에 friends 동의가 없습니다. "
                      "KAKAO_SETUP.md '친구에게도 보내기' 절차로 refresh_token 을 "
                      "재발급(scope=talk_message,friends)해 KAKAO_REFRESH_TOKEN 을 교체하세요.")
            else:
                print(f"[kakao-친구] 친구 목록 조회 실패 HTTP {status}: {j}")
            return None
        elems = j.get("elements") or []
        out += [{"uuid": e["uuid"], "nickname": e.get("profile_nickname", "")}
                for e in elems if e.get("uuid") and e.get("allowed_msg", True)]
        offset += 100
        if not elems or offset >= int(j.get("total_count") or 0):
            return out


def send_to_friends(access_token, template):
    """'나에게 보내기'와 완전히 동일한 한 통(template)을 친구들에게도 발송.

    활성화: 변수 KAKAO_SEND_TO_FRIENDS=1 또는 KAKAO_FRIEND_UUIDS 지정 (미설정 시 no-op).
    대상: KAKAO_FRIEND_UUIDS(쉼표 구분 uuid; 빈 값/'all' 이면 앱 연결 친구 전체).
    API 제약으로 1회 최대 5명씩 분할 발송. 본인 발송은 이미 끝난 뒤이므로 여기 실패는
    잡을 실패시키지 않고 경고만 남긴다(다음 슬롯에 또 시도).
    """
    sel = os.environ.get("KAKAO_FRIEND_UUIDS", "").strip()
    flag = os.environ.get("KAKAO_SEND_TO_FRIENDS", "").strip().lower()
    if not (sel or flag in ("1", "true", "yes", "on")):
        return
    if sel and sel.lower() != "all":
        uuids = [u.strip() for u in sel.split(",") if u.strip()]
    else:
        friends = get_app_friends(access_token)
        if friends is None:
            return
        uuids = [f["uuid"] for f in friends]
    if not uuids:
        print("[kakao-친구] 보낼 친구가 없습니다 — 수신자도 같은 앱에 로그인(연결)되어 있고 "
              "메시지 수신이 허용돼야 목록에 나타납니다 (KAKAO_SETUP.md 참고)")
        return
    ok, fail = [], []
    for i in range(0, len(uuids), 5):           # API 제약: receiver_uuids 1회 최대 5명
        chunk = uuids[i:i + 5]
        try:
            status, j = _http_post_retry(FRIENDS_SEND_URL, {
                "receiver_uuids": json.dumps(chunk),
                "template_object": json.dumps(template, ensure_ascii=False),
            }, headers={"Authorization": f"Bearer {access_token}"}, what="친구 발송")
        except Exception as e:
            print(f"[kakao-친구] 발송 전송 오류: {e}")
            fail += chunk
            continue
        if status == 200:
            ok += j.get("successful_receiver_uuids") or chunk
            for fi in (j.get("failure_info") or []):
                bad = fi.get("receiver_uuids") or []
                fail += bad
                ok = [u for u in ok if u not in bad]
        else:
            fail += chunk
            print(f"[kakao-친구] 발송 실패 HTTP {status}: {j}")
    print(f"[kakao-친구] 친구 발송 {len(ok)}명 성공"
          + (f", {len(fail)}명 실패({', '.join(_mask_uuid(u) for u in fail)})" if fail else ""))
    if fail:
        print("::warning title=Kakao 친구 발송::일부 수신자 발송 실패 — 수신자가 앱과 연결돼 있고 "
              "카카오톡 메시지 수신을 허용했는지, uuid 가 올바른지 확인하세요.")


def list_friends_cli():
    """로컬 1회 실행용: 앱과 연결된 친구의 닉네임/uuid 를 출력 (KAKAO_FRIEND_UUIDS 작성용).

    사용: KAKAO_REST_API_KEY=... KAKAO_REFRESH_TOKEN=... python scripts/send_kakao_digest.py --list-friends
    ※ 닉네임·uuid 가 출력되므로 공개 CI 로그에서는 실행하지 말 것(로컬 전용)."""
    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if not rest_key or not refresh_token:
        raise SystemExit("KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN 환경변수를 설정하고 실행하세요.")
    access_token = refresh_access_token(rest_key, refresh_token)
    friends = get_app_friends(access_token)
    if friends is None:
        raise SystemExit("친구 목록 조회 실패 — 위 메시지 참고 (friends 동의 포함 토큰인지 확인).")
    if not friends:
        print("앱과 연결된 친구가 없습니다 — 수신자가 같은 앱에 로그인(연결)했는지 확인하세요.")
        return
    print(f"앱 연결 친구 {len(friends)}명 (KAKAO_FRIEND_UUIDS 에 쉼표로 나열):")
    for f in friends:
        print(f"  {f['nickname'] or '(닉네임 비공개)'}\t{f['uuid']}")


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

    # ① 기본(통일) 형식 = '한 통' 피드: 슬롯별 차트 이미지 + 증시·환율(설명)
    #    + 심리·에너지·금속·곡물·운임(행) + '대시보드 보기' 버튼.
    #    차트는 당일 인트라데이, 없으면 7일 일봉 폴백.
    sent_template = None
    if _charts_enabled():
        sent_template = send_chart_feed(access_token, data, title, blocks, slot)
        if sent_template:
            print(f"[kakao] 발송 완료 (차트 피드 한 통, slot={slot})")
        else:
            print("[kakao] 차트 피드 실패 — 동일 내용 텍스트로 폴백")

    # ② 최후 폴백: 기본 텍스트 한 통 — 피드와 '동일한 공통 블록(증시~운임)' + '대시보드 보기' 버튼.
    #    (콘솔 커스텀 템플릿 폴백은 형식이 달라 혼란을 줬으므로 제거 — 2026-06-10 10시 사례)
    if not sent_template:
        sent_template = send_memo(access_token, build_text_message(title, blocks), with_button=True)
        print(f"[kakao] 발송 완료 (텍스트 폴백, slot={slot})")

    # ③ (선택) 친구에게도 동일한 한 통 — 차트 이미지는 카카오 CDN URL 이라 그대로 재사용된다.
    #    미설정 시 no-op. 실패해도 본인 발송은 끝났으므로 경고만 남기고 잡은 성공 처리.
    try:
        send_to_friends(access_token, sent_template)
    except Exception as e:
        print(f"::warning title=Kakao 친구 발송::친구 발송 중 오류(본인 발송은 완료): {e}")


if __name__ == "__main__":
    if "--list-friends" in sys.argv:
        list_friends_cli()
    else:
        main()
