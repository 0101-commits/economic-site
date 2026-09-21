#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""data.json 시황을 카카오톡·디스코드로 발송한다 — 평일 6회, 주말·공휴일 1회.

수신 모드(자동 판별):
  * 친구에게 보내기(우선) — 앱과 연결·동의된 카카오톡 친구가 있으면 그 친구들에게 발송.
    일반 메시지처럼 '푸시 알림'이 울린다. (2026-06 사용자 요청: 나에게 보내기는 내가 보낸
    메시지라 알림이 없음 → 보조 계정을 발신자로 두고 본 계정을 친구로 수신.)
    검수 전 앱은 '팀 멤버'로 등록된 친구만 조회된다. 설정 절차는 KAKAO_SETUP.md ⑤ 참고.
    쿼터: 발신자당 일 100건·발신자→수신자 쌍당 일 20건 — 평일 6회 발송 기준 여유가 크다.
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

발송 슬롯(2026-09-21 기획안 P1 — 16회에서 6회로):
  [평일]
    07시   개장 전   간밤 미국장 정산(SOX·나스닥·S&P) + 환율·금리 + 오늘 일정
    09시   개장 직후 코스피·코스닥·환율·닛케이 — 그 시간에 움직이는 것만
    12시   장중      위와 같은 4종 + 외국인 잠정 수급
    16:40  마감      close 슬롯 — 마감 리포트(카드 B, 4분면)
    19시   저녁      금리 3국 + 원자재
    22시   미국 개장 미국 지수 + 오늘밤 지표 예고
  [주말·공휴일]
    11시             주간 요약(일요일은 주간 리포트 모드)

  슬롯 차트는 편성표 카드(discord_card.board)가 실패했을 때의 폴백이다.
  (국채 수익률: 미국은 당일 인트라데이[^TNX], 한국은 일별[ECOS] 추세선)

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
KAKAO_FEED_ROWS = 5  # 피드 item_content.items 표시 한도 — 넘으면 뒤 행이 잘린다
# 발송 '성공' 센티널 — 워크플로(kakao-daily.yml)가 이 파일의 존재로만 '발송됨' 마커를 캐시한다.
# (스크립트는 알림 스팸 방지를 위해 실패해도 exit 0 이므로, 종료코드로는 성공을 알 수 없다.)
SENT_OK_PATH = ".kakao_sent_ok"

# ── 발송 슬롯 — 평일/주말을 분리한다. 워크플로 게이트·차트 구성·제목 표기가 모두 이 목록 기준.
#   • 평일(월~금) 6회(KST): 07 · 09 · 12 · 15:45(마감, close 슬롯) · 19 · 22.
#   • 주말·공휴일  1회(KST): 11시.
#
# 2026-09-21 기획안 P1 — 16회에서 6회로. 근거는 취향이 아니라 실측이다: 주 84회를
# 보내는데 블록 대부분의 원천이 그보다 훨씬 드물게 갱신된다. 운임 SCFI 는 주 1값을
# 84회 반복해 신규성이 1.2%, 공포탐욕·VKOSPI 는 일 1값이라 6.0%였다. 주말 슬롯은
# 본문이 평일과 동일해 금요일 종가가 네 번 더 나갔다.
# 마감 브리핑은 새 슬롯을 만들지 않고 기존 close 슬롯(아래 CLOSE_AT)을 그대로 쓴다.
SLOT_HOURS_WEEKDAY = [7, 9, 12, 19, 22]
SLOT_HOURS_WEEKEND = [11]
# 마감 브리핑 시각(KST) — 워크플로 게이트(kakao-daily.yml)가 같은 값을 쓴다.
# ⚠ 15:45 로 앞당기지 말 것. 마감 직후엔 투자자 수급이 KRX 잠정치라 알림 숫자가
#   포털·언론 확정치와 어긋난다 — 2026-09-11 에 바로 그 이유로 15:40 → 16:40 으로
#   옮겼다. 확정 수급(18시 이후)은 19시 슬롯이 받는다.
CLOSE_AT = (16, 35)

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
_CHART_SP_KOSPI = ([("indices", "SP500", "S&P 500"), ("indices", "KOSPI", "KOSPI")],
                   "S&P500 / KOSPI")
_CHART_BONDS_KRUS = ([("yield", "KR10Y", "KR 10Y"), ("yield", "US10Y", "US 10Y")],
                     "KR 10Y / US 10Y")
# 평일 슬롯별 차트(P1 개편 6슬롯): 07=S&P·코스피(간밤 미국장) / 09=코스피·달러원
#               / 12=코스피·달러원 / 19=한·미국채 / 22=달러원·WTI.
# 이 매핑은 편성표 카드(discord_card.board)가 실패했을 때의 폴백 차트다 — 평시엔
# PROFILES 카드가 본문이라 여기까지 내려오지 않는다.
SLOT_CHARTS_WEEKDAY = {
    "h07": _CHART_SP_KOSPI, "h09": _CHART_KR, "h12": _CHART_KR,
    "h19": _CHART_BONDS_KRUS, "h22": _CHART_EVE,
}
# 주말 슬롯 차트: 달러원·금(주말에 움직이는 것이 거의 없다).
SLOT_CHARTS_WEEKEND = {
    "h11": _CHART_FX_GOLD,
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
# 세로가 길수록 말풍선에서 크게(확대) 보이고, 표시 한도를 넘으면 상하가 크롭된다.
# 이력: 1080x1440(3:4 경계) → 상단 크롭 → 864x1080(4:5, 폭/높이=0.8) 로 낮췄으나 여전히
# "확대되어 잘림"(2026-07-08 사용자 보고). → 정사각 1:1 로 더 낮춰 말풍선에서 덜 확대되고
# 어떤 재인코딩에도 크롭되지 않게 한다. 2패널(위·아래)은 정사각에서도 충분히 읽힌다.
# (더 작게/크게가 필요하면 높이만 조정 — 폭 대비 높이를 키우면 커지고, 줄이면 작아진다.)
_CHART_DPI = 150
CHART_PX = (1080, 1080)   # 1:1 (정사각 — 말풍선 확대·크롭 방지)


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


def _update_github_secret(name, value):
    """회전된 refresh_token 을 GitHub Actions Secret 에 자동 반영(auto-rotate) → 사실상 무기한 연장.

    카카오는 refresh_token 만료 1개월 전부터 갱신 때마다 '새 refresh_token' 을 함께 준다.
    이 함수가 그 값을 시크릿에 되써 주면 매달 스스로 연장돼 '수동 재발급'이 사라진다.
    필요: 저장소 시크릿 GH_SECRETS_PAT(이 저장소 Secrets: write 권한 PAT). 없으면 조용히 skip
    (기존 토큰이 회전 후에도 ~1개월 유효 → 다음 회전/수동 갱신으로 복구되므로 발송은 안 끊긴다).
    실패해도 예외를 올리지 않는다(발송 자체는 이미 성공한 뒤 호출)."""
    pat = os.environ.get("GH_SECRETS_PAT", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()   # Actions 가 자동 제공 "owner/name"
    if not pat or not repo:
        print("::warning title=토큰 자동회전 불가::GH_SECRETS_PAT 미설정 — 회전된 refresh_token 을 "
              "자동 저장하지 못했습니다. 기존 토큰은 ~1개월 유효하나, KAKAO_SETUP.md 절차로 수동 갱신 필요.")
        return False
    try:
        import base64
        import requests
        from nacl import public, encoding
    except Exception as e:
        print(f"::warning title=토큰 자동회전 불가::pynacl/requests 미설치({e}) — 수동 갱신 필요")
        return False
    api = f"https://api.github.com/repos/{repo}/actions/secrets"
    hdr = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json",
           "X-GitHub-Api-Version": "2022-11-28"}
    try:
        pk = requests.get(f"{api}/public-key", headers=hdr, timeout=15)
        if pk.status_code != 200:
            print(f"::warning title=토큰 자동회전 실패::public-key HTTP {pk.status_code} — 수동 갱신 필요")
            return False
        pkj = pk.json()
        # GitHub Actions 시크릿은 저장소 공개키로 libsodium sealed box 암호화해 올린다.
        sealed = public.SealedBox(
            public.PublicKey(pkj["key"], encoding.Base64Encoder())).encrypt(value.encode("utf-8"))
        put = requests.put(f"{api}/{name}", headers=hdr, timeout=15,
                           json={"encrypted_value": base64.b64encode(sealed).decode(),
                                 "key_id": pkj["key_id"]})
        if put.status_code in (201, 204):
            print(f"::notice title=토큰 자동회전 완료::{name} 시크릿을 새 refresh_token 으로 갱신했습니다 "
                  "(다음 런부터 자동 적용 — 수동 재발급 불필요).")
            return True
        print(f"::warning title=토큰 자동회전 실패::PUT HTTP {put.status_code} {put.text[:120]} — 수동 갱신 필요")
        return False
    except Exception as e:
        print(f"::warning title=토큰 자동회전 실패::{e} — 수동 갱신 필요")
        return False


def _gh_issue_notify(title, body):
    """치명 상태(토큰 만료·회전 실패)를 GitHub Issue 로 승격 — '무음 중단' 방지.

    발송 실패를 잡 실패(exit 1)로 만들면 슬롯/매분 실행마다 실패 메일이 도배되므로 잡은 green 으로
    유지하되, 로그를 열어야만 보이는 ::warning 대신 이슈 1건으로 확실히 통지한다(이슈 생성은
    저장소 소유자에게 알림이 간다). 같은 제목의 열린 이슈가 있으면 생성하지 않는다(스팸 방지).
    필요: GITHUB_TOKEN(워크플로 permissions: issues: write) + GITHUB_REPOSITORY(러너 자동 제공).
    미설정/실패 시 조용히 경고만 — 통지는 best-effort 이며 발송 로직에 영향을 주지 않는다."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repo:
        return
    hdr = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
           "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ecom-kakao-notify"}
    try:
        status, issues = _http_get(
            f"https://api.github.com/repos/{repo}/issues?state=open&per_page=100", hdr)
        if status == 200 and any(isinstance(i, dict) and i.get("title") == title
                                 for i in (issues if isinstance(issues, list) else [])):
            return                                     # 이미 통지됨 — 중복 이슈 방지
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues",
            data=json.dumps({"title": title, "body": body}, ensure_ascii=False).encode("utf-8"),
            headers=dict(hdr, **{"Content-Type": "application/json"}), method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            if r.status in (200, 201):
                print(f"::notice title=이슈로 통지::{title}")
                # #시스템 채널 병행(D8) — 이슈 신규 생성 시에만 도달하므로(위 dedup)
                # 매분 런에서도 스팸 없이 '치명 상태 1건 = 디스코드 1통'이 보장된다.
                try:
                    import notify_discord
                    notify_discord.system(f"{title}\n{body[:800]}")
                except Exception:
                    pass
    except Exception as e:
        print(f"[notify] GitHub 이슈 통지 실패({e}) — 경고 로그로 갈음")


def refresh_access_token(rest_key, refresh_token):
    """refresh_token 으로 access_token 을 재발급한다."""
    status, j = _http_post_retry("https://kauth.kakao.com/oauth/token", {
        "grant_type": "refresh_token",
        "client_id": rest_key,
        "refresh_token": refresh_token,
    }, what="토큰 재발급")
    if status != 200 or not j.get("access_token"):
        # 400 응답의 error_code 를 메시지에 명시 — KOE320/KOE322 는 refresh_token 자체가 만료/무효라
        # 재시도로는 절대 복구되지 않는다(KAKAO_SETUP.md ③ 재발급이 유일한 해법임을 바로 알 수 있게).
        ecode = str(j.get("error_code") or "")
        hint = (" — refresh_token 만료 — KAKAO_SETUP.md 재발급 필요"
                if ecode in ("KOE320", "KOE322") else "")
        if ecode in ("KOE320", "KOE322"):
            # 재시도 불가능한 '토큰 사망' — 이 순간부터 모든 카카오 발송(다이제스트·종목·서킷)이
            # 조용히 중단된다. 사용자가 메시지 부재를 눈치챌 때까지 며칠 걸리던 무음 유실을
            # 이슈 1건으로 즉시 통지한다(digest/alerts/halts 세 경로 모두 이 함수를 지나간다).
            _gh_issue_notify(
                "🚨 카카오 refresh_token 만료 — 카톡 알림 전체 중단 (재발급 필요)",
                f"카카오 토큰 재발급이 `HTTP {status} {ecode}` 로 실패해 시황 다이제스트·종목 알림·"
                f"서킷브레이커 알림이 모두 중단된 상태입니다.\n\n"
                f"**복구 방법**: `KAKAO_SETUP.md` ③ 절차로 refresh_token 을 재발급해 "
                f"저장소 Secret `KAKAO_REFRESH_TOKEN` 을 교체하세요. 교체 즉시 다음 런부터 복구됩니다.\n\n"
                f"응답: `{j}`")
        raise SystemExit(f"[kakao] access_token 재발급 실패: HTTP {status}"
                         f"{f' {ecode}' if ecode else ''} {j}{hint}")
    # refresh_token 유효기간이 1개월 미만이면 카카오가 새 토큰을 함께 준다.
    if j.get("refresh_token"):
        # ⚠ 보안: 공개 저장소라 Actions 로그가 공개된다 → 새 토큰 값은 절대 로그에 노출 금지(마스킹 먼저).
        print(f"::add-mask::{j['refresh_token']}")
        # auto-rotate: 새 토큰을 GitHub Secret 에 자동 반영해 사실상 무기한 연장(수동 재발급 제거).
        # GH_SECRETS_PAT 없거나 실패하면 경고만 — 기존 토큰이 회전 후 ~1개월 유효해 발송은 안 끊긴다.
        if not _update_github_secret("KAKAO_REFRESH_TOKEN", j["refresh_token"]):
            print("::warning title=KAKAO_REFRESH_TOKEN 회전됨::카카오가 refresh_token 을 회전했으나 "
                  "자동 반영에 실패했습니다. 기존 토큰은 약 1개월 더 유효 — 그 안에 KAKAO_SETUP.md 절차로 "
                  "GitHub Secret 을 갱신하세요.")
            # 아직 발송이 살아있는 '지금'이 통지 적기 — 1개월 뒤 만료되면 그때는 전 채널 무음 중단이다.
            _gh_issue_notify(
                "⚠️ 카카오 refresh_token 회전 자동반영 실패 — 1개월 내 수동 갱신 필요",
                "카카오가 refresh_token 을 회전 발급했지만 GitHub Secret 자동 갱신(GH_SECRETS_PAT)이 "
                "실패했습니다. 기존 토큰은 약 1개월 더 유효하며, 그 안에 `KAKAO_SETUP.md` ③ 절차로 "
                "`KAKAO_REFRESH_TOKEN` Secret 을 갱신하지 않으면 카톡 알림 전체가 중단됩니다.\n\n"
                "GH_SECRETS_PAT 시크릿(이 저장소 Secrets: write 권한 fine-grained PAT)을 점검하세요.")
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


def _stale_tag(s, now):
    """항목별 신선도 라벨(P2) — as_of/date 가 오늘이 아니면 '·전일'/'·M/D' 를 돌려준다.

    라이브 보정 항목(증시·환율·원자재)은 발송 시점 시세라 무표기, 스냅샷 항목(심리·운임)만
    기준일을 밝혀 묵은 수치가 '지금 시황'처럼 읽히지 않게 한다. 파싱 실패는 무표기(기존 동작)."""
    try:
        d = datetime.datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return ""
    days = (now.date() - d).days
    if days <= 0:
        return ""
    return "·전일" if days == 1 else f"·{d.month}/{d.day}"


# 카드 타일 키 → 본문 지표 라벨. 두 쪽에 같이 나오는 지표만 담는다(중복 제거 대상).
# 금리·SOX·상하이·유로달러는 본문 블록에 아예 없으므로 여기 없다.
_CARD_DUP_LABEL = {"KOSPI": "코스피", "KOSDAQ": "코스닥", "SP500": "S&P", "NASDAQ": "나스닥",
                   "USDKRW": "달러-원", "USDJPY": "달러-엔", "WTI": "WTI",
                   "NatGas": "천연가스", "Gold": "금", "Copper": "구리"}


def _card_tile_labels(slot, weekend, now):
    """이번 슬롯 카드가 이미 타일로 보여주는 지표의 본문 라벨 집합.

    카드(편성표)와 본문(블록)은 서로를 모르는 두 원천이라, 장중 편성에서는 카드 타일 6종 중
    4종이 피드 설명·행에 그대로 한 번 더 실렸다 — 한 통 안 표시 슬롯 12개 중 5개가 같은 숫자
    (2026-09-18 실측). 카드가 실제로 렌더된 경우에만 호출측이 이 집합을 빼고 본문을 만든다."""
    try:
        import discord_card
        prof = discord_card.PROFILES.get(discord_card.profile_for(slot, weekend, now)) or {}
        keys = [k for row in (prof.get("rows") or []) for k in row]
        return {_CARD_DUP_LABEL[k] for k in keys if k in _CARD_DUP_LABEL}
    except Exception as e:
        print(f"[digest] 카드 타일 목록 조회 실패({e}) — 중복 제거 생략")
        return set()


# 슬롯별 본문 편성(2026-09-21 기획안 P3) — 여섯 통이 같은 내용을 담지 않게 한다.
# 값은 build_digest_parts 가 만드는 블록 라벨이고, 순서가 곧 표시 순서다.
# 판단 기준은 하나다: 그 시각에 갱신되는 것만 넣는다. 한국 장중에 곡물·운임은
# 세션이 닫혀 있어 어제 값이 그대로 나가고, 심리 3종은 하루 한 번만 바뀐다.
SLOT_BLOCKS = {
    "h07": ("미국증시", "환율", "금리", "심리", "일정"),      # 개장 전 — 간밤 정산
    "h09": ("국내증시", "환율", "아시아"),                    # 개장 직후
    "h12": ("국내증시", "환율", "아시아", "수급"),            # 장중
    "h19": ("금리", "에너지", "금속", "수급"),                # 저녁 — 금리·원자재
    # 22시 — 슬롯이 :0x 에 도는데 미국 정규장은 22:30(서머타임)/23:30 개장이라, 이 시각
    # 미국 지수는 아직 전일 종가다(07시 슬롯과 같은 숫자). 그래서 이 통의 일은 '무엇이
    # 움직였나'가 아니라 '오늘 밤 무엇을 볼 것인가'다 — 일정을 맨 앞에 둔다. 환율은
    # 역외 거래로 이 시각에도 움직이는 몇 안 되는 값이다.
    "h22": ("일정", "환율", "미국증시"),
    "h11": ("국내증시", "미국증시", "환율", "심리",
            "에너지", "금속", "운임"),                        # 주말·공휴일 1회 — 넓게
}
# 슬롯을 모르는 경로(수동 실행·마감 리포트·테스트)는 전부 싣는다 — 종전 동작.
ALL_BLOCKS = ("국내증시", "미국증시", "아시아", "환율", "금리", "심리",
              "에너지", "금속", "곡물", "운임", "수급", "일정")


def build_digest_parts(d, drop=(), slot=None):
    """data.json → (제목, 블록 [(라벨, 값), ...]).

    slot(h07·h09·…)을 주면 SLOT_BLOCKS 편성만 골라 담는다. 없으면 전부(종전 동작).
    피드·텍스트 등 모든 발송 경로가 이 한 곳의 결과만 쓰므로 경로별 내용 차이가 생길 수 없다.

    2026-09-21 이전에는 슬롯과 무관하게 여덟 블록이 늘 같이 나갔다. 그런데 운임 SCFI 는
    주 1회, 심리는 일 1회만 갱신돼 주 84회 발송 중 신규성이 각각 1.2%·6.0% 였다 —
    같은 숫자를 반복해 읽히는 알림의 주된 원인이었다.

    drop = 빼고 만들 지표 라벨 집합(카드가 이미 보여주는 것 — _card_tile_labels). 문자열을
    만든 뒤 잘라내지 않고 **조립 단계에서** 빼므로, 한 지표가 빠져 블록이 비면 블록 자체가
    사라진다(텍스트 폴백 경로는 drop 없이 불러 전체를 싣는다)."""
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

    drop = set(drop or ())

    def ip(label, key, nd=0):
        o = idx.get(key)
        if label in drop or not o or o.get("price") is None:
            return None
        return f"{label} {_num(o['price'], nd)}{_a1(o.get('change'))}"

    def fxp(label, key, nd=1):
        o = fx.get(key)
        if label in drop or not o or o.get("rate") is None:
            return None
        return f"{label} {_num(o['rate'], nd)}{_a1(o.get('change'))}"

    def cp(label, key, nd=1):
        o = com.get(key)
        if label in drop or not o or o.get("price") is None:
            return None
        return f"{label} {_num(o['price'], nd)}{_a1(o.get('change'))}"

    blocks = []
    kr_eq = [p for p in (ip("코스피", "KOSPI"), ip("코스닥", "KOSDAQ")) if p]
    if kr_eq:
        blocks.append(("국내증시", " ".join(kr_eq)))
    # 간밤 미국장 — SOX 를 함께 싣는다. 전일 SOX 등락과 당일 코스피 등락의 상관이
    # +0.44 로 S&P(+0.37)·나스닥(+0.41)보다 높다(2026-09-21 실측, 최근 250거래일).
    us_eq = [p for p in (ip("S&P", "SP500"), ip("나스닥", "NASDAQ"), ip("SOX", "SOX")) if p]
    if us_eq:
        blocks.append(("미국증시", " ".join(us_eq)))
    # 아시아 — 한국 장중과 같은 시간대에 움직이는 것. 닛케이는 코스피와 동시간 상관이
    # +0.765 로 가장 높고, 상하이는 +0.525 라 맥락용으로만 뒤에 붙인다.
    asia = [p for p in (ip("닛케이", "Nikkei"), ip("상하이", "Shanghai")) if p]
    if asia:
        blocks.append(("아시아", " ".join(asia)))
    fxs = [p for p in (fxp("달러-원", "USDKRW"), fxp("달러-엔", "USDJPY")) if p]
    if fxs:
        blocks.append(("환율", " ".join(fxs)))
    # 금리 — 미·한 10년물과 그 차이. 한미 금리차는 환율 방향을 읽는 기본 재료인데
    # 종전 본문엔 어느 슬롯에도 없었다(카드 캡션에만 있었다).
    yc = d.get("yieldCurve") or {}

    def _y10(cc):
        for se in ((yc.get(cc) or {}).get("series") or []):
            if se.get("tenor") == "10Y":
                dt = [x for x in (se.get("data") or []) if _f(x.get("value")) is not None]
                if dt:
                    return _f(dt[-1]["value"])
        return None

    us10, kr10 = _y10("us"), _y10("kr")
    rate = []
    if us10 is not None:
        rate.append(f"미국채10Y {us10:.2f}%")
    if kr10 is not None:
        rate.append(f"한국채10Y {kr10:.2f}%")
    if us10 is not None and kr10 is not None:
        rate.append(f"한미차 {(us10 - kr10) * 100:+.0f}bp")
    if rate:
        blocks.append(("금리", " ".join(rate)))
    pl = []
    fg = sent.get("fear_greed")
    if fg and fg.get("value") is not None:
        pl.append(f"공포탐욕 {int(_f(fg['value']))}({_fg_label(fg['value'])}){_stale_tag(fg.get('as_of'), now)}")
    vix = us.get("vix")
    vix_v = _f(vix.get("value")) if vix else None
    if vix_v is not None:
        pl.append(f"VIX {_num(vix_v, 1)}")
    vk = sent.get("vkospi")   # 코스피 위험지수(KOSPI 변동성지수, VKOSPI)
    vk_v = _f(vk.get("value")) if vk else None
    # as_of 스테일 가드 — 수집원이 며칠씩 죽어 carry-forward 된 값(실측: 11일 묵은 as_of)이
    # '지금 심리'처럼 발송되지 않게, 5일 넘게 묵으면 표기를 생략한다(2026-07 감사).
    if vk_v is not None and vk and vk.get("as_of"):
        try:
            vk_age = (now.date() - datetime.datetime.strptime(str(vk["as_of"])[:10], "%Y-%m-%d").date()).days
            if vk_age > 5:
                print(f"[digest] VKOSPI as_of {vk['as_of']} — {vk_age}일 경과 스테일, 표기 생략")
                vk_v = None
        except ValueError:
            pass
    # 이상치 가드 — 스크래핑 오류 값이 carry-forward 되어 발송되는 것 방지(2026-06-11: VIX 19.9
    # 인데 VKOSPI 86.5 가 나간 사례). 정상 범위(5~60) 밖이면서 VIX 의 3배를 넘으면(역사적
    # VKOSPI/VIX 비율은 대체로 1~2배) 신뢰 불가로 보고 표기를 생략한다.
    if vk_v is not None and not (5 <= vk_v <= 60) and (vix_v is None or vk_v > 3 * vix_v):
        print(f"[digest] VKOSPI {vk_v} 이상치 의심(VIX {vix_v}) — 표기 생략")
        vk_v = None
    if vk_v is not None:
        pl.append(f"VKOSPI {_num(vk_v, 1)}{_stale_tag(vk.get('as_of'), now)}")
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
        blocks.append(("운임", f"SCFI {_num(scfi['price'])}{_a1(scfi.get('chgPct'))}{_stale_tag(scfi.get('date'), now)}"))
    # 투자자 수급(코스피) — **확정치만** 싣는다. KRX 확정은 18시 이후라 그 전 슬롯에선 줄이
    # 아예 없다(잠정치를 확정처럼 보여 "알림 값이 실제와 다르다"가 났던 게 이 블록의 이유).
    _inv = _verified_investor()
    if _inv and _inv.get("confirmed"):
        # 꼬리표는 investor_flows 가 판정한 문구를 그대로 쓴다 — '확정'을 하드코딩하면
        # 교차검증을 못 한 날(네이버 410 으로 토스 단독인 경우)에도 확정처럼 보인다.
        blocks.append(("수급", f"외국인 {_inv['foreign']:+,.0f}억 · 기관 {_inv['inst']:+,.0f}억"
                               f" ({str(_inv['date'])[5:]} {_inv.get('reason') or '확정'})"))
    # 오늘(22시 슬롯은 오늘 밤) 주요 지표 발표 — 별 2개 이상만. 재료는 이미 있었는데
    # 카드 헤더에만 쓰였고 본문엔 없었다.
    cal = _dc_cal_line(d)
    if cal:
        blocks.append(("일정", cal))

    # 슬롯 편성 적용 — 순서는 SLOT_BLOCKS 를 따른다(표시 우선순위가 곧 잘림 순서).
    want = SLOT_BLOCKS.get(str(slot or "").strip().lower(), ALL_BLOCKS)
    by = dict(blocks)
    return title, [(lab, by[lab]) for lab in want if lab in by]


# ── 주간 리포트(옵션 D) — 일요일 17시 슬롯을 주간 모드로 ────────────────────
def _wk_pct(hist, now, days=7):
    """history 일봉([{date, close}])에서 최근 종가 vs ~days일 전(이하 가장 가까운 과거) 종가의 %.

    데이터 부족(2개 미만·기준일 못 찾음)이면 None — 호출측이 항목을 생략한다."""
    if not isinstance(hist, list) or len(hist) < 2:
        return None
    try:
        rows = [(datetime.datetime.strptime(str(r["date"])[:10], "%Y-%m-%d").date(), _f(r.get("close")))
                for r in hist if r.get("date") and r.get("close") is not None]
    except (ValueError, TypeError, KeyError):
        return None
    if len(rows) < 2:
        return None
    cutoff = now.date() - datetime.timedelta(days=days)
    base = next((c for d0, c in reversed(rows) if d0 <= cutoff), None)
    last = rows[-1][1]
    if not base or not last:
        return None
    return (last / base - 1) * 100


def _wk_line(pairs):
    """[(라벨, pct)] → '코스피 +2.1% 코스닥 -0.4%' (None 항목 생략). 전부 None 이면 ''."""
    parts = [f"{lab} {p:+.1f}%" for lab, p in pairs if p is not None]
    return " ".join(parts)


def build_weekly_parts(d, now):
    """data.json history → 주간 리포트 (제목, 블록). 핵심 데이터가 없으면 (None, None) —
    호출측이 일반 다이제스트로 폴백한다(주간 모드가 발송 자체를 깨지 않게)."""
    h = d.get("history", {}) or {}
    hi, hf, hc = h.get("indices", {}) or {}, h.get("fx", {}) or {}, h.get("commodities", {}) or {}
    eq = _wk_line([("코스피", _wk_pct(hi.get("KOSPI"), now)), ("코스닥", _wk_pct(hi.get("KOSDAQ"), now)),
                   ("S&P", _wk_pct(hi.get("SP500"), now)), ("나스닥", _wk_pct(hi.get("NASDAQ"), now))])
    if not eq:
        return None, None                            # 증시 주간 변화조차 없으면 주간 모드 포기
    fxl = _wk_line([("달러-원", _wk_pct(hf.get("USDKRW"), now)), ("달러-엔", _wk_pct(hf.get("USDJPY"), now))])
    cml = _wk_line([("금", _wk_pct(hc.get("Gold"), now)), ("WTI", _wk_pct(hc.get("WTI"), now)),
                    ("구리", _wk_pct(hc.get("Copper"), now))])
    blocks = [("주간증시", eq)]
    if fxl:
        blocks.append(("주간환율", fxl))
    if cml:
        blocks.append(("주간원자재", cml))
    # 다음 주 주요 일정 — economicCalendar.events(dt='MM.DD HH:MM', 연도 없음)에서
    # 오늘 초과~7일 이내·별 많은 순 상위 3건. 연도는 현재 연도로 두되 연말 롤오버만 보정.
    evs = []
    for ev in ((d.get("economicCalendar", {}) or {}).get("events") or []):
        m = re.match(r"(\d{2})\.(\d{2})", str(ev.get("dt", "")))
        if not m:
            continue
        try:
            ed = datetime.date(now.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        if ed < now.date() - datetime.timedelta(days=180):
            ed = ed.replace(year=now.year + 1)       # 12월에 보는 1월 일정
        if now.date() < ed <= now.date() + datetime.timedelta(days=7):
            evs.append((-(ev.get("stars") or 0), ed, str(ev.get("name", "")).strip()))
    evs.sort()
    if evs:
        blocks.append(("다음주", " · ".join(f"{ed.month}/{ed.day} {name}" for _, ed, name in evs[:3])))
    start = now.date() - datetime.timedelta(days=6)  # 일요일 발송 기준 지난 월~일
    title = f"주간 시황 {start.month}/{start.day}~{now.month}/{now.day}"
    return title, blocks


def _pack(prefix, lines, limit):
    """prefix 뒤에 줄을 한도 내에서 채워 한 문자열로.

    못 들어간 줄은 버리되 '외 N항목'을 남긴다 — 종전엔 한도 초과 줄을 아무 표시 없이
    버려서, 받는 쪽은 뒷 블록(에너지·금속·곡물·운임)이 아예 없는 날과 자리가 없어
    잘린 날을 구별할 수 없었다(2026-09-18). 꼬리표 자리는 미리 비워 두고 채운다."""
    lines = [ln for ln in lines if ln]
    msg, left = prefix, len(lines)
    for ln in lines:
        add = ln if not msg else "\n" + ln
        tail = len(f" 외 {left - 1}항목") if left > 1 else 0
        if len(msg) + len(add) + tail <= limit:
            msg += add
            left -= 1
    if not left:
        return msg
    # 한 줄도 못 들어간 경우엔 위 예약이 돌지 않았으므로 여기서 다시 한도를 맞춘다
    # (prefix 가 한도에 가까운 호출 — 실측 _pack('P'*195, ['abcdefghij'], 200) → 201자).
    tail = f" 외 {left}항목"
    if len(msg) + len(tail) > limit:
        msg = msg[:max(0, limit - len(tail))]
    return msg + tail


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
        # 403(insufficient scopes) = 토큰에 friends 동의가 없어 '친구에게 보내기'가 상시 죽어 있고
        # 매 발송이 무음(푸시 없음)인 '나와의 채팅'으로만 간다 — 로그 한 줄로는 묻히던 것을
        # ::warning 으로 승격해 런 Annotations 첫 화면에서 보이게 한다(2026-07 감사: 매 런 재현 확인).
        print(f"::warning title=친구 발송 미동작::친구 목록 조회 불가 HTTP {status}({j.get('msg', j)}) — "
              "'나에게 보내기'로 폴백(푸시 알림 없음). friends 스코프 동의로 refresh_token 을 "
              "재발급해야 복구됩니다(KAKAO_SETUP.md ⑤). 친구 발송을 안 쓰면 변수 KAKAO_FRIENDS=0 으로 끄세요.")
        return []
    return [el for el in (j.get("elements") or []) if isinstance(el, dict) and el.get("uuid")]


def _send_template_object(access_token, template, uuids=None):
    """template_object 발송 — uuids 가 있으면 '친구에게 보내기', 없으면 '나에게 보내기'(메모).

    친구에게는 한 호출당 최대 5명(카카오 한도)이라 5명씩 나눠 보낸다. HTTP 200 이면 그 묶음은
    성공으로 본다(failure_info 의 개별 수신 거부 등은 로그만 — 재발송하면 성공자에게 중복이 가므로)."""
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {"template_object": json.dumps(template, ensure_ascii=False)}
    if not uuids:
        # 메모 경로도 친구 경로처럼 전송예외(URLError/타임아웃 등 재시도 소진)를 흡수한다 — 종전엔
        # 그대로 raise 돼 소비자(digest/check_alerts/check_halts)의 except SystemExit 를 비껴가
        # 스택트레이스 크래시로 끝났다. SystemExit 로 변환해 세 소비자가 일관되게 잡도록 한다.
        # (실패이므로 발송 성공 센티널(.kakao_sent_ok)은 당연히 안 생긴다.)
        try:
            return _http_post_retry("https://kapi.kakao.com/v2/api/talk/memo/default/send",
                                    payload, headers, what="메시지 발송(나에게)")
        except Exception as e:
            raise SystemExit(f"[kakao] 메모 발송 실패: {e}")
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
    """'주말 패턴' 발송 여부 = 주말(토·일) 또는 공휴일. weekday(): 월=0 … 토=5, 일=6.

    공휴일(대체·임시 포함)은 KR_HOLIDAY=1 로 판정 — kakao-daily.yml 게이트가
    Nager.Date API 로 하루 한 번 판정해 주입하는 단일 진실원(2026-08-20 사용자 요청:
    공휴일엔 주말과 동일하게 11·17시 2회, 카카오·디스코드 공통). 스크립트가 직접
    API 를 부르지 않는 이유: 게이트(발송 창)와 판정이 어긋나면 슬롯·차트가 엇갈린다."""
    if os.environ.get("KR_HOLIDAY", "").strip() == "1":
        return True
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
        f"https://ecom-dashboard-proxy.e-hcg.workers.dev/?url={quote_plus(base)}",
        f"https://corsproxy.io/?{quote_plus(base)}",
        f"https://api.allorigins.win/raw?url={quote_plus(base)}",
        f"https://api.codetabs.com/v1/proxy/?quest={quote_plus(base)}",
    ]
    # 후보별 실패 사유를 한 줄씩 남긴다 — 종전엔 조용히 continue 해 '왜 인트라데이가 없는지'
    # (Yahoo 403? 프록시 다운?) 로그로 알 수 없었다. URL 쿼리는 빼고 호스트만 적는다(민감정보 없음).
    for url in candidates:
        host = urllib.parse.urlsplit(url).netloc
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                print(f"[chart] {symbol} {host} 실패: HTTP {r.status_code}")
                continue
            res = (((r.json() or {}).get("chart") or {}).get("result") or [None])[0]
            if res:
                return res
            print(f"[chart] {symbol} {host} 실패: HTTP 200 이지만 result 비어 있음")
        except Exception as e:
            print(f"[chart] {symbol} {host} 실패: {e}")
            continue
    return None


# 인트라데이로 '인정'할 최소 점수. 세션이 갓 개장한 순간(예: KST 08시 발송 시 KRW=X —
# 서울 FX 는 09시 개장이라 8시엔 야후가 1~2점만 반환)엔 점이 너무 적어 ① 선이 그려지지 않고
# (matplotlib 은 점 1개면 선을 못 그림·fill 도 투명) ② x축이 '00:00' 로 붕괴한다. 그런데도
# bool(xs)=True 라 호출부가 '유효한 7일 일봉 폴백'을 건너뛰어 빈 패널이 그대로 발송됐다
# (2026-07 사용자 보고: 아침 8시 '달러원' 차트가 항상 빔 — Gold 는 야간 선물이라 정상).
# 임계 미만이면 인트라데이를 버리고 일봉 폴백을 태워 '항상 볼 수 있는' 차트를 보장한다.
_MIN_INTRADAY_PTS = 3


def _yahoo_intraday(symbol, rng="1d", interval="5m"):
    """당일(최근 세션) 인트라데이 (시각[KST naive] 목록, 가격 목록, 전일 종가). 실패 시 ([], [], None).

    점이 _MIN_INTRADAY_PTS 미만이면 '유효한 인트라데이 없음'으로 보고 빈 결과를 돌려
    호출부가 일봉 폴백을 쓰게 한다(세션 갓 개장 시 1~2점 → 빈 패널 방지).

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
        if len(xs) >= _MIN_INTRADAY_PTS:
            return xs, ys, prev
        if xs:
            print(f"[chart] 인트라데이 점 부족({symbol}: {len(xs)}점<{_MIN_INTRADAY_PTS}) "
                  f"— 세션 갓 개장 추정, 일봉 폴백")
            return [], [], None
    print(f"[chart] 인트라데이 실패({symbol}) — 7일 일봉으로 폴백")
    return [], [], None


# ── 카드용 차트 소스 체인(기획 5154773b P0 — 빈 패널 금지) ─────────────────────
_TOSS_IDX = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}


def _toss_index_intraday(symbol):
    """토스 지수 1분봉(공식·실시간) — (xs, ys, prev). 실패 ([], [], None).
    CI 에선 toss_api 가 403→Worker 릴레이로 자동 전환(TOSS_RELAY_KEY 필요).
    스파이크 실측(2026-08-20): 지수 캔들 interval 은 1m/1d 만 지원, 최신→과거 순."""
    name = _TOSS_IDX.get(symbol)
    if not name:
        return [], [], None
    try:
        import toss_api
        if not toss_api.enabled():
            return [], [], None
        # count 상한 200(실측 400 은 400 invalid-request) — 최근 200분(~세션 후반 3.3h).
        # ponytail: 전 세션이 필요하면 페이징 추가, 지금은 급변 맥락용으로 충분.
        res = toss_api.get(f"/api/v1/market-indicators/{name}/candles",
                           {"interval": "1m", "count": 200}) or {}
        cs = ((res.get("result") or {}).get("candles")
              if isinstance(res.get("result"), dict) else None) or res.get("candles") or []
        rows = []
        for c in cs:
            try:
                t = datetime.datetime.fromisoformat(str(c.get("timestamp"))[:19])
                v = float(c.get("closePrice"))
            except (TypeError, ValueError):
                continue
            rows.append((t, v))
        rows.sort()
        if not rows:
            return [], [], None
        day0 = rows[-1][0].date()                     # 최신 세션만(전일 봉 섞임 방지)
        rows = [r for r in rows if r[0].date() == day0]
        # 전일 종가 — 일봉 2개(오늘 진행봉·전일 확정봉)에서.
        prev = None
        dres = toss_api.get(f"/api/v1/market-indicators/{name}/candles",
                            {"interval": "1d", "count": 3}) or {}
        dcs = ((dres.get("result") or {}).get("candles")
               if isinstance(dres.get("result"), dict) else None) or dres.get("candles") or []
        for c in dcs:
            if str(c.get("timestamp"))[:10] != day0.isoformat():
                try:
                    prev = float(c.get("closePrice"))
                except (TypeError, ValueError):
                    prev = None
                break
        return [r[0] for r in rows], [r[1] for r in rows], prev
    except Exception as e:
        print(f"[chart] 토스 지수 분봉 실패({symbol}): {e}")
        return [], [], None


def _daily7(symbol):
    """7일 일봉 폴백 — (xs, ys, prev). prev=마지막 봉 직전 종가(임계선 기준)."""
    res = _yahoo_chart_result(symbol, "7d", "1d")
    if not res:
        return [], [], None
    ts = res.get("timestamp") or []
    closes = (((res.get("indicators") or {}).get("quote") or [{}])[0] or {}).get("close") or []
    xs, ys = [], []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        xs.append(datetime.datetime.fromtimestamp(t, KST).replace(tzinfo=None))
        ys.append(float(c))
    if len(ys) < 3:
        return [], [], None
    return xs, ys, ys[-2]


def _intraday_chain(symbol):
    """급변·서킷·마감 카드용 시계열 — (xs, ys, prev, 폴백라벨).
    ①국내지수=토스 1분봉 → ②Yahoo 인트라데이 → ③7일 일봉(라벨 '일봉 7D' — 카드가
    패널에 표기해 인트라데이 오독 방지). 전부 실패 시만 빈값(카드가 종전처럼 패널 생략)."""
    xs, ys, prev = _toss_index_intraday(symbol)
    if len(ys) >= _MIN_INTRADAY_PTS:
        return xs, ys, prev, ""
    xs, ys, prev = _yahoo_intraday(symbol)
    if ys:
        return xs, ys, prev, ""
    xs, ys, prev = _daily7(symbol)
    if ys:
        return xs, ys, prev, "일봉 7D"
    return [], [], None, ""


def _session_chain(symbol):
    """다이제스트 히어로용 시계열 — (xs, ys, prev, 폴백라벨). 당일 '전 구간'이 목적이다.

    _intraday_chain 과 우선순위가 반대인 이유: 토스 1분봉은 count 상한 200 이라 최근
    3.3시간만 돌려준다(15:39 조회 시 12:11~15:30 — 오전장 누락, 2026-08-25 실측).
    급변·서킷 카드는 '방금 무슨 일이 났나'라 1분 해상도·최신성이 전 구간보다 중요하므로
    그쪽은 _intraday_chain 을 그대로 쓴다. 한 함수로 두 요구를 만족시키면 한쪽이 나빠진다."""
    xs, ys, prev = _yahoo_intraday(symbol)
    if ys:
        return xs, ys, prev, ""
    xs, ys, prev = _toss_index_intraday(symbol)
    if len(ys) >= _MIN_INTRADAY_PTS:
        return xs, ys, prev, "1분봉 최근"
    xs, ys, prev = _daily7(symbol)
    if ys:
        return xs, ys, prev, "일봉 7D"
    return [], [], None, ""


def _hero_symbol(key):
    """타일 키 → 인트라데이 조회 심볼. 기존 두 표(_YH_SYM·_YIELD_INTRADAY_SYM)를 그대로 쓴다."""
    return _YH_SYM.get(key) or _YIELD_INTRADAY_SYM.get(key) or ""


def pick_focus(data, slot, weekend, now):
    """그날 카드의 주인공 → (키, z|None). 두 카드(디스코드·카카오)가 같은 값을 쓰게 한다.

    이례적인 날에는 그날 가장 크게 움직인 자산이 히어로 패널·추세 첫 칸·타일을 가져간다
    (기획안 확장, 2026-09-21). 후보를 '인트라데이를 그릴 수 있는 키'로 제한하는 이유는
    여기서만 심볼 표를 알기 때문이다 — 심볼이 없는 키를 주인공으로 뽑으면 빈 패널이 된다.
    실패하면 (None, None) 을 돌려 카드가 종전 고정 주인공으로 가게 둔다."""
    try:
        import discord_card
        allowed = set(_YH_SYM) | set(_YIELD_INTRADAY_SYM)
        pkey = discord_card.profile_for(slot, weekend, now)
        prof = discord_card.PROFILES.get(pkey) or discord_card.PROFILES[discord_card.DEFAULT_PROFILE]
        key, z = discord_card.focus_of(data, prof, pkey, allowed=allowed)
        if z is not None:
            print(f"[digest] 오늘의 주인공 교체: {key} (z {z:+.1f}σ)")
        return key, z
    except Exception as e:                                   # noqa: BLE001
        print(f"[digest] 주인공 선정 실패({e}) — 고정 편성 유지")
        return None, None


def _build_kakao_card(data, now, slot, weekend, weekly=False, next_week="", focus=None):
    """카톡 피드 이미지 — 디스코드와 같은 편성표(PROFILES)의 정사각 캔버스(기획 d18ebb33 P1).

    weekly=True(기획 v3 I2)면 주간 정사각 카드(주간 수익률 바 + 수급·일정 타일)를 그린다 —
    종전에는 주간 슬롯만 카드를 건너뛰고 옛 2티커 라인 차트로 나갔다. '지금 시각 타일이
    주간 본문과 어긋난다'는 종전 사유는 타일 내용을 주간 수치로 바꿔서 해소했다.

    히어로 인트라데이는 여기서 조회해 넘긴다(discord_card 는 시세를 직접 조회하지 않는다).
    실패 시 None → 호출측이 종전 슬롯 차트로 폴백하므로 이미지가 비는 일은 없다.
    (_dc_cal_line 은 '일정 한 줄' 문구 재사용일 뿐 — 카카오 본문 blocks 는 건드리지 않는다.)"""
    try:
        import discord_card
        if weekly:
            return discord_card.weekly(data, now, next_week=next_week, shape="square")
        fkey, fz = focus if focus else (None, None)
        if not fkey:
            pkey = discord_card.profile_for(slot, weekend, now)
            fkey = discord_card.HERO.get(pkey, "")
        sym = _hero_symbol(fkey)
        hero = _session_chain(sym) if sym else ([], [], None, "")
        return discord_card.board(data, now, cal=_dc_cal_line(data), slot=slot,
                                  weekend=weekend, shape="square", hero=hero,
                                  focus=(fkey, fz) if fkey else None)
    except Exception as e:
        print(f"::warning title=카톡 카드 실패::{e} — 종전 슬롯 차트로 폴백")
        return None


def load_mri(data):
    """메르 리스크 지수(mer_signals.lens)를 data 에 _mri 로 얹는다 — 카드 헤더용.

    mer_signals.json 은 data.json 과 별도 파일이라 카드 렌더러가 직접 읽을 수 없다.
    _liveTiles 와 같은 방식으로 발송 직전에 주입한다. 실패·부재는 조용히 무시(없으면
    헤더에 안 그린다). 7일 넘게 묵은 계산은 '지금 위험도'가 아니므로 버린다."""
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mer_signals.json")
        with open(path, encoding="utf-8") as f:
            lens = (json.load(f) or {}).get("lens") or {}
        score = _f(lens.get("score"))
        if score is None:
            return
        as_of = str(lens.get("asOf") or "")[:10]
        if as_of:
            age = (datetime.datetime.now(KST).date()
                   - datetime.datetime.strptime(as_of, "%Y-%m-%d").date()).days
            if age > 7:
                print(f"[digest] MRI as_of {as_of} — {age}일 경과 스테일, 헤더 표기 생략")
                return
        # 30일 전 대비 변화 — 점수 하나만으로는 방향을 알 수 없다.
        hist = [h for h in (lens.get("history30d") or []) if _f(h.get("score")) is not None]
        prev = _f(hist[0]["score"]) if hist else None
        data["_mri"] = {"score": score, "delta": (score - prev) if prev is not None else None}
    except Exception as e:                                   # noqa: BLE001
        print(f"[digest] MRI 로드 실패({e}) — 헤더 표기 생략")


def _news_field(data, n=2):
    """오늘·어제 뉴스 상위 n건 → (라벨, 값, inline) 또는 None.

    data.news 는 주제별 리스트 16종인데 발송 경로가 한 번도 쓰지 않았다(기획안 D7).
    주제를 섞어 최신순으로 뽑고, 제목은 잘리지 않게 60자로 자른다."""
    try:
        news = data.get("news") or {}
        rows = []
        for topic, items in news.items():
            if not isinstance(items, list):
                continue                                     # lastFetched 같은 스칼라 키
            for it in items[:3]:
                if isinstance(it, dict) and it.get("title") and it.get("isoDate"):
                    rows.append((str(it["isoDate"])[:10], str(it["title"]).strip(),
                                 it.get("url") or ""))
        if not rows:
            return None
        rows.sort(reverse=True)
        seen, picked = set(), []
        for _dt, title, url in rows:
            key = title[:20]
            if key in seen:
                continue                                     # 같은 사건의 중복 기사 제거
            seen.add(key)
            picked.append(f"· [{title[:60]}]({url})" if url else f"· {title[:60]}")
            if len(picked) >= n:
                break
        return ("📰 뉴스", "\n".join(picked), False) if picked else None
    except Exception:
        return None


def _ai_line(data, n=2):
    """aiBriefing(LLM 3줄 요약, fetch-data 가 매일 생성·커밋) 상위 n줄 — 디스코드
    embed description 용(기획 5154773b P3). 오늘 자가 아니면 ""(묵은 요약이 '지금
    시황'처럼 보이지 않게 — 스테일 가드)."""
    try:
        ab = data.get("aiBriefing") or {}
        if str(ab.get("date")) != datetime.datetime.now(KST).strftime("%Y-%m-%d"):
            return ""
        return "\n".join(str(x) for x in (ab.get("lines") or [])[:n])
    except Exception:
        return ""


def _yahoo_live_quote(symbol):
    """발송 시점 시세 — (현재가, 전일 종가 대비 %) 또는 None.

    국내 지수(^KS11/^KQ11)는 토스증권 공식 시세 우선 — 알림 본문 숫자가 사이트와
    어긋나던 주 원인이 Yahoo 국내 지수의 지연·결측이었다."""
    import toss_api
    if symbol in toss_api.YAHOO_INDEX_MAP:
        q = toss_api.live_quote(symbol)
        if q:
            return q
    # ⚠ 전일 종가는 meta.chartPreviousClose 를 믿지 않고 **일봉 배열의 직전 확정 종가**로
    #   계산한다. Yahoo 의 chartPreviousClose 는 지수에서 실측이 어긋난다 — 2026-08-14
    #   ^KQ11 은 이 필드 기준 +0.67% 였지만 실제(토스·KRX·사이트)는 +0.38% 였고, 그 값이
    #   그대로 카톡·디스코드 본문에 실려 '알림 숫자가 사이트와 다르다'의 원인이 됐다.
    #   check_halts._yahoo_quote 가 서킷브레이커 오발동을 막으려 쓴 것과 같은 방식이다.
    res = _yahoo_chart_result(symbol, rng="5d", interval="1d")
    if not res:
        return None
    meta = res.get("meta") or {}
    closes = [c for c in ((((res.get("indicators") or {}).get("quote") or [{}])[0]) or {})
              .get("close") or [] if c is not None]
    price = _f(meta.get("regularMarketPrice"))
    if price is None:
        price = closes[-1] if closes else None
    if price is None or price <= 0:
        return None
    # 직전 봉이 곧 기준가다. 장중이면 closes[-1]=오늘 봉·closes[-2]=전일 종가이고,
    # 마감 후·휴장이면 closes[-1]=마지막 세션 종가·closes[-2]=그 전날이라 '마지막 세션의
    # 등락률'이 나온다 — 사이트가 표시하는 것과 같은 값이다. (여기서 '신선도'로 pct 를 0 으로
    # 눌러선 안 된다. 그건 알림 발동 판정의 규칙이고, 본문 표시는 마감 후에도 값이 필요하다.)
    prev = closes[-2] if len(closes) >= 2 else None
    if prev is None:
        prev = _f(meta.get("chartPreviousClose")) or _f(meta.get("previousClose"))
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
    ("indices", "KOSDAQ", "price", "^KQ11"),
    ("indices", "SP500", "price", "^GSPC"),
    ("indices", "NASDAQ", "price", "^IXIC"),
    # 닛케이·SOX(2026-08-25) — 디스코드 카드 슬롯 편성이 타일로 쓴다. 특히 닛케이는
    # 한국 장중과 같은 시간대에 거래되는데 종전엔 보정 대상이 아니라 스냅샷 값이
    # 그대로 나갔다(실측: data.json 65,599 ▲0.09% vs 라이브 65,801 ▲0.42%).
    ("indices", "Nikkei", "price", "^N225"),
    ("indices", "SOX", "price", "^SOX"),
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
    syms = sorted({sym for _, _, _, sym in _LIVE_QUOTES} | {"^VIX", "DX-Y.NYB", "^TNX"})
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
    # 카드 타일 전용 오버레이 — data.json 에 노드가 없거나(달러인덱스) 소스가 지연되는
    # (미국채 10Y = FRED 2영업일) 항목. discord_card._node 가 이 dict 를 먼저 본다.
    # d 는 메모리 사본이라 data.json 파일에는 절대 쓰이지 않는다(data.json 은 봇 소유).
    tiles = d.setdefault("_liveTiles", {})
    dq = quotes.get("DX-Y.NYB")
    if dq and dq[0]:
        tiles["DXY"] = {"value": dq[0], "change": dq[1]}
        updated.append(f"DXY={dq[0]:.2f}")
    tq = quotes.get("^TNX")
    if tq and tq[0]:
        # ^TNX 의 change 는 '수익률의 %변화'다 — 타일은 bp 를 쓰므로 전일값에서 역산.
        bp = None
        if tq[1] is not None and (1 + tq[1] / 100.0):
            bp = round((tq[0] - tq[0] / (1 + tq[1] / 100.0)) * 100)
        tiles["US10Y"] = {"value": tq[0], "change": bp}
        updated.append(f"US10Y={tq[0]:.3f}%")
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
    """슬롯별 지표 2종을 '당일(인트라데이)' 차트 1장 PNG(CHART_PX=1080x1080, 1:1 정사각)로 생성.

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
        print(f"::warning title=차트 누락 폴백::[chart] matplotlib 미설치 — 이미지 생략 ({e})")
        return None
    # 한글 폰트 — 카드 렌더러와 같은 탐지 경로를 태운다. 종전엔 rcParams 를 건드리지 않아
    # matplotlib 기본(DejaVu Sans)으로 그려졌고, 그래서 라벨을 영문으로 박아 뒀다.
    # kakao-daily.yml 이 이 잡에서 이미 fonts-noto-cjk 를 설치한다(디스코드 카드용).
    ko = {}
    try:
        import discord_card
        discord_card._setup()
        ko = {k: v[0] for k, v in discord_card._CATALOG.items()}
        ko.setdefault("JP10Y", "일본채 10Y")   # 재무성 CSV 직접 수집 — 카탈로그엔 없다
    except Exception as e:
        print(f"[chart] 한글 폰트 설정 생략({e}) — 영문 라벨 유지")
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
        sup = " / ".join(ko.get(k, lab) for _c, k, lab in panels) if ko else suptitle
        fig.suptitle(sup, fontsize=17, x=0.02, ha="left", weight="bold")
        for a, (cat, key, label) in zip(axes, panels):
            label = ko.get(key, label)
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
                # 기간 라벨은 '등락률의 기준'과 일치시킨다 — 본문 change 는 '전일 대비'라, 7일 일봉
                # 폴백에서 종전처럼 "/ 7d" 로 적으면 값(1일 등락)과 라벨(7일)이 어긋난 거짓 표기였다
                # (2026-07 감사). 본문 수치와의 단일 출처 원칙은 유지하고 라벨만 1d 로 바로잡는다.
                # 시계열로 '추정'한 경우에만 실제 계산 구간(오늘/일봉 n일)을 라벨로 쓴다.
                disp_chg = _f(node.get("change"))
                if disp_chg is not None:             # 본문과 동일 출처(전일 대비)
                    span = "today" if intraday else "1d"
                elif intraday and prev_close:        # 인트라데이 추정(전일 종가 대비)
                    disp_chg = (ys[-1] / prev_close - 1) * 100
                    span = "today"
                else:                                # 그려진 시계열 처음~끝 기준 추정
                    disp_chg = (ys[-1] / ys[0] - 1) * 100 if ys[0] else 0.0
                    span = "today" if intraday else f"{len(xs)}d"
                t = f"{label}   {disp_val:,.2f}  ({disp_chg:+.1f}% / {span})"
                # 26pt 는 말풍선 축소(1080px → 약 270dp) 후에도 본문 글씨만큼 보이는 크기지만,
                # 긴 제목은 축 폭을 넘어 오른쪽이 잘렸다("(+0.1% / today" 에서 ')' 크롭 —
                # 2026-08-25 실측). 넘칠 때만 단계적으로 줄인다 — 짧은 제목은 종전 크기 유지.
                a.set_title(t, fontsize=(26 if len(t) <= 27 else 22 if len(t) <= 32 else 19),
                            loc="left")
                a.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if intraday else "%m-%d"))
            else:
                a.text(0.5, 0.5, f"{label} N/A", ha="center", va="center", fontsize=24)
                a.set_title(label, fontsize=26, loc="left")
            a.grid(alpha=0.25)
            a.tick_params(axis="both", labelsize=12)
        # rect 좌우에 1.5% 거터 — 축 눈금 라벨이 캔버스 가장자리에 닿아 미세하게 잘리던 것
        # 방지(2026-08-05 디스코드 표시 확인). 캔버스 픽셀 크기는 그대로라 카카오 비율 불변.
        fig.tight_layout(rect=[0.015, 0.005, 0.985, 0.97])
        fig.savefig(out_path, dpi=_CHART_DPI)
        plt.close(fig)
        return out_path
    except Exception as e:
        print(f"::warning title=차트 누락 폴백::[chart] 생성 실패 ({e})")
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
        print(f"::warning title=차트 누락 폴백::[chart] requests 미설치 — 업로드 생략 ({e})")
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
                print(f"::warning title=차트 누락 폴백::[chart] 업로드 전송오류 ({e}) — 재시도 소진")
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
        # 최종 실패 — 카카오 오류 코드(KOE···/숫자 code)를 파싱해 함께 남긴다(원인 파악용).
        try:
            ej = r.json() or {}
        except Exception:
            ej = {}
        ecode = str(ej.get("error_code") or ej.get("code") or "")
        print(f"::warning title=차트 누락 폴백::[chart] 업로드 실패 HTTP {r.status_code}"
              f"{f' code={ecode}' if ecode else ''}: {r.text[:200]}")
        return None
    return None


def build_feed_parts(blocks):
    """공통 블록 → 피드용 (description, items).

    설명(2줄): 증시(코스피·S&P) / 환율(달러-원·달러-엔) — 헤드라인.
    행(item): 심리 / 에너지 / 금속 / 곡물 / 운임 / 수급 — 카카오 피드 행 한도는 5개다.

    ⚠ 행이 한도를 넘으면 '뒤에서 자르지 않는다'. 블록 순서상 맨 뒤인 수급이 매번
    탈락했기 때문이다(2026-09-17 실측): 수급 블록은 KRX 확정치가 나오는 18시 이후
    슬롯에만 붙는데, 붙는 순간 항상 6번째라 100% 잘려 나갔다. '확정치만 싣는다'고
    공들여 만든 블록이 한 번도 도착하지 않았다.
    → 한도를 넘으면 뒤 두 행을 한 행으로 합쳐 둘 다 살린다.

    ⚠ 설명/행을 **라벨로** 가른다(위치 blocks[:2] 아님 — 2026-09-18). 카드 중복 제거로
    환율 블록이 통째로 빠지는 슬롯(장중·마감·주말은 달러-원·달러-엔이 둘 다 카드 타일)에서
    위치로 가르면 심리가 조용히 헤드라인으로 승격되고 행이 하나 줄었다."""
    desc_rows = [(lab, v) for lab, v in blocks if v and lab in DESC_LABELS]
    rows = [(lab, v) for lab, v in blocks if v and lab not in DESC_LABELS]
    if not desc_rows and rows:                    # 헤드라인 후보가 다 빠진 날은 첫 행을 올린다
        desc_rows, rows = rows[:1], rows[1:]
    desc = "\n".join(v for _, v in desc_rows)
    while len(rows) > KAKAO_FEED_ROWS:            # 초과분은 버리지 않고 앞 행에 접는다
        (l1, v1), (l2, v2) = rows[-2], rows[-1]
        rows[-2:] = [(f"{l1}·{l2}", f"{v1} / {v2}")]
    return desc, [kakao_item(lab, v) for lab, v in rows]


def _hero_button(slot, weekend, now):
    """피드 2번째 버튼 — 그 슬롯 히어로 지표의 네이버 페이지. 검증된 링크가 없으면 None.
    (NAVER_LINKS 는 최종 URL 동일성 + 본문 키워드 2중 검사를 통과한 것만 담고 있다.)"""
    try:
        import discord_card
        import notify_discord
        key = discord_card.HERO.get(discord_card.profile_for(slot, weekend, now), "")
        url = notify_discord.NAVER_LINKS.get(key)
        if not url:
            return None
        ko = (discord_card._CATALOG.get(key) or (key,))[0]
        return {"title": f"{ko} 시세", "link": {"web_url": url, "mobile_web_url": url}}
    except Exception:
        return None


# 피드 설명(헤드라인)으로 올라가는 블록 라벨 — 일간·주간 공통. 나머지는 행이 된다.
DESC_LABELS = ("증시", "환율", "주간증시", "주간환율")

# 행 이름 상한도 값과 같은 이유로 안전 레일이다 — 8자로 뒀더니 공백을 품은 ETF 이름이
# 'TIGER 미…' 로 잘렸다(실측). 모르는 상태에서 짧게 자르면 카카오가 보여줄 수 있었던
# 글자를 우리가 버린다. 실제 표시 한도는 발송 1회로 재서 확정할 것.
KAKAO_ITEM_LABEL = 20
# 행 값 상한은 '안전 레일'로 넉넉히 둔다 — 카카오의 실제 표시 한도를 아직 실측하지 않았고,
# 모르는 상태에서 짧게 자르면 렌더러가 보여줄 수 있었던 글자를 우리 손으로 버린다.
# 다음 발송 1회를 수신 화면으로 재서 확정할 것(그때 이 값만 바꾸면 전 경로가 따라온다).
KAKAO_ITEM_VALUE = 60


def kakao_item(label, value):
    """피드 행 한 줄 {item, item_op} — 카카오 표기 규격의 단일 창구.

    카카오는 행 이름·값을 각각 한 줄로만 렌더하고 넘치면 스스로 말줄임한다. 자르는 지점이
    코드와 렌더러 두 곳에 있으면 무엇이 보일지 예측할 수 없다(종목 알림은 40자, 다이제스트는
    무제한으로 달랐다 — 2026-09-18). 상한을 여기 한 곳에 두고, 자를 때는 말줄임표를 남겨
    '잘렸다'가 보이게 한다."""
    def cut(s, n):
        s = " ".join(str(s or "").split())
        return s if len(s) <= n else s[:n - 1].rstrip() + "…"
    return {"item": cut(label, KAKAO_ITEM_LABEL), "item_op": cut(value, KAKAO_ITEM_VALUE)}


def kakao_button(title, url):
    """카카오 피드 버튼 — 이름은 8자 이하 권장(카카오 문서)이라 잘라서 넣는다."""
    return {"title": str(title)[:8], "link": {"web_url": url, "mobile_web_url": url}}


def send_feed(access_token, title, description, image_url, items=None, dims=CHART_PX,
              uuids=None, extra_button=None, buttons=None):
    """피드 한 통 — 차트 이미지 + 제목 + 증시·환율(설명) + 심리·에너지·금속·곡물·운임(행) + '대시보드 보기' 버튼.

    buttons = [{title, link}] 을 주면 기본 버튼 구성을 그것으로 대체한다(카카오 상한 2개)."""
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
        "buttons": (buttons[:2] if buttons else
                    [kakao_button("대시보드 보기", DASHBOARD_URL)]),
    }
    if extra_button and not buttons:
        template["buttons"].append(extra_button)
    if items:
        template["item_content"] = {"items": items[:5]}
    status, j = _send_template_object(access_token, template, uuids=uuids)
    if status != 200:
        print(f"[kakao] 피드 발송 실패 HTTP {status}: {j}")
        return False
    print(f"[kakao] 피드(차트) 발송 성공\n{title} | {description} | 행 {len(items) if items else 0}개")
    return True


def send_chart_feed(access_token, data, title, blocks, slot, weekend, uuids=None, png=None,
                    full_blocks=None):
    """슬롯 차트 생성→업로드→'한 통' 피드 발송. png 를 넘기면 재사용(디스코드 병행 발송과
    이중 생성 방지). 실제 발송·폴백은 send_card 가 담당한다(기획 v3 I1 — 단일 진입점).

    blocks = 카드와 중복을 뺀 피드 본문. full_blocks = 중복 제거 전 전체 —
    **사진이 실패해 텍스트로 내려갈 때 쓴다.** 이미지가 없는 순간엔 카드가 들고 있던
    코스피·환율이 아무 데도 없게 되므로, 그 경로만 전체를 싣는다(2026-09-18 리뷰 지적)."""
    png = png or build_slot_chart_png(data, slot, weekend)
    desc, items = build_feed_parts(blocks)
    text = build_text_message(title, full_blocks or blocks)
    buttons = [("대시보드 보기", DASHBOARD_URL)]
    btn = _hero_button(slot, weekend, datetime.datetime.now(KST))
    if btn:
        buttons.append((btn["title"], btn["link"]["web_url"]))
    return send_card(access_token, title, desc, png=png, uuids=uuids, buttons=buttons,
                     items=items, kind="정기 시황", text=text)


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


def _system_notice(text):
    """운영 통지 — 디스코드 #시스템. 카카오 경로가 열화·실패한 사실 자체를 알린다(기획 v3 I7).
    통보가 본 경로를 깨면 본말전도라 실패는 조용히 무시."""
    try:
        import notify_discord
        notify_discord.system(text, title="⚙️ 카톡 카드 경고")
    except Exception:
        pass


def send_card(access_token, title, caption, png=None, uuids=None, buttons=None,
              fallback_png=None, items=None, kind="", text=None):
    """카톡 한 통 — 카드 이미지가 본문(기획 v3 I1). 모든 카카오 발송의 단일 진입점.

    3단 폴백(I7): ① 카드 PNG → ② fallback_png(슬롯 라인 차트 등) → ③ 텍스트(제목+캡션).
    png=None 으로 부르면 '사진 없는 발송'이므로 경고 + #시스템 교차 통보를 남긴다(I5) —
    라인업에 새 구멍이 생기는 것을 로그·알림에서 바로 보이게 하는 장치다.

    buttons = [(라벨, url)] 최대 2개(카카오 상한, 라벨 8자). 기본 = 대시보드 1개.
    반환 True/False. 텍스트 폴백까지 실패하면 send_memo 가 SystemExit 를 던진다(호출측이 잡음)."""
    btns = [kakao_button(t, u) for t, u in (buttons or [])][:2] or None
    if not png:
        print(f"::warning title=카드 없는 카톡 발송::{kind or title} — 텍스트로 발송(기획 v3 I5)")
        _system_notice(f"카톡 '{kind or title}' 발송에 카드가 없습니다 — 텍스트 폴백으로 나갔습니다.")
    for cand in [p for p in (png, fallback_png) if p]:
        image_url = kakao_upload_image(access_token, cand)
        if not image_url:
            continue
        if send_feed(access_token, title, caption, image_url, items=items,
                     uuids=uuids, buttons=btns):
            return True
        if items:                                     # 행 거부 — 행 내용을 설명에 합쳐 재시도
            merged = "\n".join([caption] + [f"{it['item']} {it['item_op']}" for it in items])
            if send_feed(access_token, title, merged, image_url, items=None,
                         uuids=uuids, buttons=btns):
                return True
    if png or fallback_png:
        print(f"::warning title=차트 누락 폴백::{kind or title} 카드/업로드 실패 — 텍스트로 발송")
        _system_notice(f"카톡 '{kind or title}' 카드·업로드 실패 — 텍스트로 발송했습니다.")
    # text = 사진 없이 내려갈 때의 전문(호출측이 전체 블록으로 만든 것). 없으면 캡션.
    # ⚠ 캡션은 피드용이라 카드와 중복을 뺀 내용이다 — 그걸 그대로 텍스트로 보내면
    #   카드가 들고 있던 지표(코스피·환율)가 통째로 빠진 메시지가 나간다(리뷰 지적).
    send_memo(access_token, text or _pack(title, [caption] if caption else [], TEXT_LIMIT),
              with_button=True, uuids=uuids)
    return True


def _stale_limit_min(now_kst, weekend):
    """⚙️ 스테일 경고를 낼 '정상 공백 상한'(분). 공급 케이던스가 시간대마다 다르므로 임계도 나눈다.

    weekend 는 _is_weekend() 값 — 토·일과 공휴일(KR_HOLIDAY=1)을 이미 함께 담고 있다.

    2026-09-08 진단 — 종전의 단일 120분은 장중 기준이었고, 공급이 없는 시간대까지 같은 잣대로
    재서 구조적 오탐을 냈다(10일간 120분 초과 공백 28건이 전부 장외·주말, 최장 324분).

      · 장중(평일 09~16시·22~07시 KST) = Worker cron 이 경량 런을 5분 주기로 깨우는 구간.
        여기서 120분이 넘으면 진짜 이상이다 — 종전 값을 그대로 쓴다.
      · 평일 장외 = 공급이 GHA 시간당 cron 1회뿐이고 풀 런이 44~62분 걸린다. 드롭 한 번이면
        정상적으로 120분을 넘으므로 240분.
      · 주말·공휴일 = Worker 가 아예 깨우지 않아(inMarketHours) 공급이 시간당 cron 하나이고,
        그 cron 의 실측 미발화율이 42%다. 720분.

    카카오/디스코드 제목의 '(수집 N.Nh 전)' 표기는 이 함수를 쓰지 않는다 — 그건 경고가 아니라
    묵은 수치를 '지금 시황'으로 읽지 않게 하는 정직성 표기라 120분 기준을 유지한다."""
    if weekend:
        return 720
    h = now_kst.hour
    in_market = h < 7 or 9 <= h < 16 or h >= 22
    return 120 if in_market else 240


def _dispatch_fetch_data():
    """data.json 스테일 시 fetch-data 를 workflow_dispatch 로 깨운다(P3 자동 복구).

    kakao-daily.yml 이 GITHUB_TOKEN(permissions.actions: write)을 넘긴다. fetch-data 쪽
    concurrency 그룹이 동시 실행을 직렬화하므로 중복 트리거도 안전. 실패는 경고만 — 발송을 막지 않는다.

    ⚠ inputs.light=true — 반드시 경량 런으로 깨운다(2026-09-08 진단). 종전의 입력 없는
      dispatch 는 풀 런(실측 44~62분)이라 이번 슬롯 안에 끝나지 못했고, 다음 슬롯이 여전히
      스테일이라 ⚙️ 경고 → 또 풀 런이 매시간 반복됐다. 경량 런은 1분 미만이라 다음 슬롯에는
      확실히 신선하고, 갱신 0건이면 커밋조차 하지 않는다(run_light_build)."""
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not tok or not repo:
        return
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/workflows/fetch-data.yml/dispatches",
            data=json.dumps({"ref": "main", "inputs": {"light": "true"}}).encode("utf-8"),
            headers={"Authorization": f"Bearer {tok}",
                     "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json"},
            method="POST")
        urllib.request.urlopen(req, timeout=15)
        print("[digest] 스테일 감지 — fetch-data 경량 런 트리거(다음 슬롯부터 정상화)")
        try:
            import notify_discord
            notify_discord.system("data.json 스테일 감지 — fetch-data 경량 런을 자동 트리거했습니다. "
                                  "이번 발송은 라이브 보정 값으로 진행, 다음 슬롯부터 정상화 예상.")
        except Exception:
            pass
    except Exception as e:
        print(f"::warning title=fetch-data 트리거 실패::{type(e).__name__}: {e} — 발송은 계속(라이브 보정)")
        try:
            import notify_discord
            notify_discord.system(f"스테일 복구용 fetch-data 트리거 실패: {type(e).__name__}: {e}")
        except Exception:
            pass


# ── 디스코드 전용 표현 헬퍼(E2·E5·E6) — 카카오 본문(blocks)은 절대 건드리지 않는다 ──

_SPARK_CH = "▁▂▃▄▅▆▇█"


def _spark(hist, n=7):
    """일봉 [{date, close}] 끝 n개 → 유니코드 스파크라인(▂▃▅▇…). 3점 미만이면 ''."""
    closes = [h.get("close") for h in (hist or [])[-n:]
              if isinstance(h.get("close"), (int, float))]
    if len(closes) < 3:
        return ""
    lo, hi = min(closes), max(closes)
    if hi - lo < 1e-9:
        return "▄" * len(closes)
    return "".join(_SPARK_CH[int((c - lo) / (hi - lo) * 7 + 0.5)] for c in closes)


def _dc_intensity(v):
    """등락 강도 표기(E2) — ±2% 이상이면 ▲→⏫ / ▼→⏬ (기호가 크기도 전달)."""
    def rep(m):
        return (("⏫" if m.group(1) == "▲" else "⏬") + m.group(2) + "%"
                if float(m.group(2)) >= 2.0 else m.group(0))
    return re.sub(r"([▲▼])(\d+(?:\.\d+)?)%", rep, v)


def _dc_cal_line(d, tgt=None):
    """경제 캘린더에서 tgt일(기본 오늘) 별점 최상위 1건 → "US CPI 21:30 ★★★" (없으면 '')."""
    try:
        ev = (d.get("economicCalendar") or {}).get("events") or []
        tgt = tgt or datetime.datetime.now(KST)
        key = f"{tgt.month:02d}.{tgt.day:02d}"
        todays = [e for e in ev if str(e.get("dt", "")).startswith(key)]
        if not todays:
            return ""
        e = max(todays, key=lambda x: (x.get("stars") or 0))
        stars = int(e.get("stars") or 0)
        if stars < 2:
            return ""
        t = str(e.get("dt", ""))[6:]
        return f"{e.get('cc', '')} {e.get('name', '')} {t} {'★' * stars}".strip()
    except Exception:
        return ""


DC_FIELD_INLINE_MAX = 24        # 이 길이까지만 2열 그리드에 넣는다(넘으면 전폭 한 줄)


def _dc_fields(blocks, d):
    """카카오 공통 blocks → 디스코드 필드(E2): 강도 기호 변환 + 추세 스파크라인 + 오늘 일정.

    긴 블록은 inline 을 끈다 — inline 필드는 폭이 화면 1/3 이라 '증시' 한 칸에 4종목
    76자를 넣으면 3~4줄로 제멋대로 접히고 숫자 정렬이 사라진다(2026-09-18). 이 경로는
    카드 렌더가 실패한 날에만 나오는 폴백이라, 그날 가장 읽혀야 하는 화면이다."""
    fs = [(lab, _dc_intensity(v), len(v) <= DC_FIELD_INLINE_MAX) for lab, v in blocks if v]
    hi = (d.get("history") or {}).get("indices") or {}
    sp = []
    for lab, key in (("코스피", "KOSPI"), ("나스닥", "NASDAQ")):
        s = _spark(hi.get(key))
        if s:
            sp.append(f"{lab} {s}")
    if sp:
        fs.append(("추세 7일", " · ".join(sp), True))
    cal = _dc_cal_line(d)
    if cal:
        fs.append(("📅 오늘", cal, True))
    return fs


def _dc_buttons():
    """다이제스트·마감 리포트 공통 버튼(E3) — 봇 토큰 있을 때만 실제로 붙는다."""
    return [("🌐 대시보드", DASHBOARD_URL), ("📊 시장 지표", DASHBOARD_URL + "?p=market"),
            ("🔄 지금 시세", "id:refresh_quotes")]


def _dc_select(data, weekly=False):
    """v4 지표 드롭다운(기획 ed0e5496 — 버튼 다이어트) — 구 버튼 그리드(v3, 16버튼)를
    String Select 1행으로 압축. 옵션 = 네이버 제공 지표만(값 = NAVER_LINKS 키,
    Worker /discord goto_link 가 URL 로 해석해 에페메랄 응답). 라벨은 발송 시점
    등락 스냅샷(「{이모지} {지표}{등락률}」) — 목록 내 훑어보기 힌트."""
    import discord_card
    import notify_discord
    if weekly:
        seq = [(ko, key, chg) for ko, en, key, chg in discord_card.weekly_rows(data)]
    else:
        seq = []
        for ko, en, cat, key in discord_card._ASSETS:
            n = (data.get(cat) or {}).get(key) or {}
            seq.append((ko, key, _f(n.get("change") if n.get("change") is not None
                                    else n.get("chgPct"))))
    return [(notify_discord.dir_label(ko, chg), key) for ko, key, chg in seq
            if key in notify_discord.NAVER_LINKS][:25]


def _dc_thread_name(now):
    """일자 스레드 이름(D10) — 변수 DISCORD_DIGEST_THREADS=0 이면 None(채널 본문)."""
    if os.environ.get("DISCORD_DIGEST_THREADS", "1").strip().lower() in ("0", "false", "off"):
        return None
    return f"📅 {now.month}/{now.day} 시황"


_INV_CACHE = {}


def _verified_investor(market="KOSPI"):
    """오늘자 검증 통과 수급 → {date, foreign, inst, retail, reason, ...} / 없으면 None.

    네이버(포털·언론 기준)값을 토스로 교차검증한 것만 통과시킨다. 실패는 조용히 None —
    카드·필드에서 수급을 빼고 '집계 중'으로 적는다(틀린 숫자 노출 금지).
    프로세스당 1회만 조회한다 — build_digest_parts 를 전체용·피드용으로 두 번 부르면서
    같은 네트워크 조회를 두 번 하지 않게(값이 달라지면 두 경로가 어긋난다)."""
    if market in _INV_CACHE:
        return _INV_CACHE[market]
    try:
        import investor_flows
        _INV_CACHE[market] = investor_flows.verified_latest(market)
    except Exception as e:                                   # noqa: BLE001
        print(f"[수급] 검증 조회 실패({e}) — 수급 표기 생략")
        _INV_CACHE[market] = None
    return _INV_CACHE[market]


def _investor_row(inv):
    """텍스트 필드용 수급 한 줄 — (라벨, 값, inline). 미검증이면 '집계 중'."""
    if not inv:
        return ("투자자 수급", "집계 중(확정 전)", False)
    asof = " ".join(x for x in (str(inv.get("date") or "")[5:], inv.get("reason") or "") if x)
    return ("투자자 수급(코스피)",
            f"외국인 {inv['foreign']:+,.0f}억 · 기관 {inv['inst']:+,.0f}억"
            + (f" ({asof})" if asof else ""),
            False)


def _send_close_report(data):
    """장 마감 리포트(E5) — 16:40 KST 전용 슬롯(close). 디스코드 전용(카카오 무변경),
    당일 스레드의 '마침표': 마감 지수 + 오늘 발동 알림 수 + 내일 주요 일정."""
    import notify_discord
    now = datetime.datetime.now(KST)
    idx = data.get("indices") or {}
    fx = data.get("fx") or {}
    rows = []
    citems = []                                       # 카드 B 용 수치 (라벨, 가격, 등락%)
    for lab, key in (("코스피", "KOSPI"), ("코스닥", "KOSDAQ"),
                     ("S&P500", "SP500"), ("나스닥", "NASDAQ")):
        n = idx.get(key) or {}
        v = _f(n.get("price"))
        if v is not None:
            rows.append((lab, f"{v:,.0f} {_a1(n.get('change'))}".strip(), True))
            citems.append((lab, v, _f(n.get("change"))))
    kr = fx.get("USDKRW") or {}
    v = _f(kr.get("rate"))
    if v is not None:
        rows.append(("달러-원", f"{v:,.1f} {_a1(kr.get('change'))}".strip(), True))
        citems.append(("달러-원", v, _f(kr.get("change"))))
    cnt = None
    try:
        sp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "alerts_state.json")
        with open(sp, encoding="utf-8") as f:
            st = json.load(f)
        today = now.strftime("%Y%m%d")
        cnt = sum(1 for k, r in st.items()
                  if not k.startswith("_") and isinstance(r, dict) and r.get("date") == today)
        rows.append(("오늘 발동 알림", f"{cnt}건", True))
    except Exception:
        pass                                          # 이력 파일 없으면 필드 생략
    # 트래킹 종목 외국인 수급 한 줄 (data.stockFlows — 토스 PC 스냅샷, 단위 주수).
    # 당일 레코드가 있는 종목만 집계 — 스냅샷이 낡았으면 필드 자체를 생략(날조 금지).
    try:
        _items = ((data.get("stockFlows") or {}).get("items") or {})
        _tday = now.strftime("%Y-%m-%d")
        _fl = []
        for _sym, _e in _items.items():
            _inv = _e.get("investor") or []
            if _inv and _inv[-1].get("date") == _tday and _inv[-1].get("foreign") is not None:
                _fl.append(((_e.get("name") or _sym), _inv[-1]["foreign"]))
        if _fl:
            _fl.sort(key=lambda x: x[1])

            def _shfmt(v):
                a = abs(v)
                return (f"{a / 1e4:,.1f}만주" if a >= 1e4 else f"{a:,.0f}주")
            _parts = []
            if _fl[-1][1] > 0:
                _parts.append(f"매수 {_fl[-1][0]} +{_shfmt(_fl[-1][1])}")
            if _fl[0][1] < 0:
                _parts.append(f"매도 {_fl[0][0]} −{_shfmt(_fl[0][1])}")
            if _parts:
                rows.append(("외국인 수급(관심종목)", " · ".join(_parts), False))
    except Exception:
        pass
    # 시장 전체 수급(외국인·기관) — 라이브 교차검증본. 카드와 텍스트 필드가 같은 값을 쓴다.
    _inv = _verified_investor()
    rows.append(_investor_row(_inv))
    cal = _dc_cal_line(data, now + datetime.timedelta(days=1))
    if cal:
        rows.append(("📅 내일", cal, True))
    kchg = _f((idx.get("KOSPI") or {}).get("change"))
    color = (notify_discord.COLOR_FLAT if kchg is None or abs(kchg) < 0.05
             else notify_discord.COLOR_UP if kchg >= 0 else notify_discord.COLOR_DOWN)
    # 카드 B 4분면(기획 5154773b P2) — 바 + 코스피 인트라데이 + 수급 3주체 + 특징주·발동
    # 종목명. 재료가 결측인 분면은 카드가 생략. 실패 시 필드만(종전 형식).
    png = None
    # 카드 재료 기본값 — 아래 try 가 중간에 끊겨도 카카오 카드 블록이 미정의 변수를 보지 않게.
    _intr, _mv, _fired = None, None, []          # _inv 는 위에서 이미 검증본으로 확정
    try:
        import discord_card
        _intr = _intraday_chain("^KS11")                 # P0 체인 재사용(빈 패널 금지)
        _sm = data.get("stockMovers") or {}
        _mv = ((_sm.get("kospiGainers") or [])[:3], (_sm.get("kospiLosers") or [])[:3])
        _fired = []
        try:                                             # 발동 알림 '이름' — 설정에서 id→이름
            cp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "alerts_config.json")
            with open(cp, encoding="utf-8") as f:
                _cfg = json.load(f)
            _nm = {a.get("id"): (a.get("name") or a.get("symbol"))
                   for a in (_cfg.get("alerts") or [])}
            today = now.strftime("%Y%m%d")
            _fired = sorted({str(_nm.get(k)) for k, r in st.items()
                             if not k.startswith("_") and isinstance(r, dict)
                             and r.get("date") == today and _nm.get(k)})
        except Exception:
            pass
        png = discord_card.close_report(citems, now, alerts_cnt=cnt, cal=cal,
                                        intraday=_intr, investor=_inv, movers=_mv,
                                        fired_names=_fired)
    except Exception as e:
        print(f"[discord] 마감 카드 예외({e}) — 필드만 발송")
    # v4(버튼 다이어트): 유틸 버튼 1행 + 지표 드롭다운 — 등락 정보는 카드 B 가 담당,
    # 구 지표 미러 버튼 행은 폐기(기획 ed0e5496). description = AI 요약 1줄(P3).
    ok = notify_discord.send(
        _ai_line(data, 1), png=png, title=f"🔔 {now.month}/{now.day} 장 마감 요약 — 시장 지표 보기",
        url=DASHBOARD_URL + "?p=market", color=color,
        fields=None if png else rows,
        footer=f"시세 {now.strftime('%H:%M')} 기준(발송 직전 보정) · 무료 시세 지연 가능",
        timestamp=True, thread_name=_dc_thread_name(now),
        buttons=[_dc_buttons()], select=_dc_select(data))
    # 카카오 병행(기획 v3 §02 P2) — 마감도 카톡으로. 카드는 정사각 변형을 따로 그린다
    # (가로 4분면은 말풍선에서 축소돼 읽히지 않는다). 실패는 경고만 — 디스코드는 이미 나갔다.
    kok = False
    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if rest_key and refresh_token:
        try:
            _tok = refresh_access_token(rest_key, refresh_token)
            _uuids = [f["uuid"] for f in get_friends(_tok)] if _friends_enabled() else []
            _kpng = None
            try:
                import discord_card
                _kpng = discord_card.close_report(citems, now, alerts_cnt=cnt, cal=cal,
                                                  intraday=_intr, investor=_inv, movers=_mv,
                                                  fired_names=_fired, shape="square")
            except Exception as e:
                print(f"[kakao] 마감 정사각 카드 예외({e}) — 텍스트 폴백")
            _cap = " · ".join(f"{lab} {val}" for lab, val, _i in rows[:3])
            kok = send_card(_tok, f"🔔 {now.month}/{now.day} 장 마감", _cap, png=_kpng,
                            uuids=_uuids, kind="장 마감",
                            buttons=[("대시보드", DASHBOARD_URL),
                                     ("시장 지표", DASHBOARD_URL + "?p=market")])
        except (SystemExit, Exception) as e:
            print(f"::warning title=마감 카톡 실패::{e} — 디스코드는 별도 경로로 발송됨")
    if ok or kok:
        _mark_sent_ok()
        print(f"[digest] 장 마감 리포트 발송 완료 (필드 {len(rows)}개, 카톡={'O' if kok else 'X'})")
    else:
        print("::warning title=장 마감 리포트 실패::양 채널 발송 실패 — 다음 깨움이 재시도")


def _mark_sent_ok():
    """'실제 발송 성공' 직후에만 호출 — SENT_OK_PATH 센티널 파일을 만든다.

    과거엔 워크플로가 스크립트 종료 후 무조건 마커(.kakao_sent_marker)를 만들어, 토큰 만료·발송
    실패로 SystemExit 를 삼키고 exit 0 한 슬롯까지 '발송됨'으로 캐시됐다 → 백업 스케줄의 같은
    슬롯 재시도가 하루 종일 차단되는 '무음 유실'. 이제 성공 시에만 이 파일이 생기고, 워크플로는
    이 파일이 있을 때만 마커를 만든다(실패 슬롯은 다음 깨움이 재시도)."""
    try:
        open(SENT_OK_PATH, "w").close()
    except OSError as e:
        # 센티널 생성 실패 = 마커가 안 찍혀 같은 슬롯이 중복 발송될 수 있음(유실보다는 낫다) — 경고만.
        print(f"::warning title=발송 센티널 생성 실패::{SENT_OK_PATH} 생성 불가({e}) — "
              "같은 슬롯이 중복 발송될 수 있습니다")


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
        print(f"::warning title=Kakao 미설정::{', '.join(missing)} 시크릿이 아직 없어 카카오 발송을 "
              "건너뜁니다. 설정 방법은 KAKAO_SETUP.md 참고. (워크플로는 정상 종료 — 실패 알림 없음)")
    # ⚠ 여기서 return 하지 않는다. 종전엔 카카오 시크릿이 없으면 그대로 끝나서 디스코드
    #   다이제스트까지 함께 멈췄다 — 이 모듈이 "디스코드 병행 발송은 카카오와 완전 독립"이라고
    #   적어 둔 것과 어긋난다. 시크릿을 재발급하려고 잠깐 지우기만 해도 두 채널이 동시에
    #   조용해지는데, 그 침묵은 '조용한 시장'과 구별되지 않는다(기획안 설계 원칙 10).
    kakao_ready = bool(rest_key and refresh_token)

    # 토큰 재발급·발송 실패는 '매 슬롯(평일 16회) 실행'이라 job 실패 시 GitHub 실패 알림 메일이
    # 슬롯마다 쏟아진다. (2026-07-08 18:00 KST~ KAKAO_REFRESH_TOKEN 만료/회전 추정으로 전 슬롯
    # 실패가 연속 발생해 실패 알림이 도배된 사건.) check_alerts.py 와 동일하게 SystemExit 를 삼켜
    # ::warning + 정상 종료(exit 0)로 알림 스팸을 막는다. 단, 이는 '증상(스팸)'만 멈추는 것 —
    # 토큰 만료면 KAKAO_SETUP.md ③ 절차로 KAKAO_REFRESH_TOKEN 시크릿을 갱신해야 실제 발송이 복구된다.
    # ⚠ data.json 로드·라이브 보정·본문 구성도 try 안에 둔다 — 종전엔 try '밖'이라 여기서의 예외
    #   (일시 네트워크 장애·데이터 이상)가 미포획 traceback → job 실패 → 실패 메일로 새던 구멍이었다.
    #   센티널(.kakao_sent_ok)이 없으므로 백업 깨움이 같은 슬롯을 재시도한다(무음 유실 아님).
    try:
        path = os.path.abspath(DATA_PATH)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise SystemExit(f"[kakao] data.json 읽기 실패({path}): {e}")

        weekend = _is_weekend()                      # 주말(토·일)·공휴일(KR_HOLIDAY)이면 11시 1회
        apply_live_quotes(data)                      # 본문 수치를 발송 시점 시세로 보정(차트와 동일 출처)
        load_mri(data)                               # 카드 헤더의 리스크 지수(P3)

        # 장 마감 리포트 = 마감 브리핑 — 게이트가 KAKAO_SLOT=close 를 주는 16:40 전용 경로.
        # 디스코드만 발송하고 즉시 종료(카카오·차트 경로 완전 무변경).
        if os.environ.get("KAKAO_SLOT", "").strip() == "close":
            _send_close_report(data)
            return

        slot = _resolve_slot(weekend)
        # 슬롯별 편성(P3) — 여섯 통이 각기 다른 질문에 답하도록 본문 블록을 고른다.
        title, blocks = build_digest_parts(data, slot=slot)   # 제목 시각은 실제 발송 시각(now)

        # 주간 리포트(옵션 D) — 일요일 11시 슬롯만 주간 모드(지난 7일 등락 + 다음 주 일정).
        # 데이터 부족으로 주간 블록을 못 만들면 그대로 일반 다이제스트 발송(무발송보다 낫다).
        _now_kst = datetime.datetime.now(KST)
        if weekend and _now_kst.weekday() == 6 and slot == "h11":
            wt, wb = build_weekly_parts(data, _now_kst)
            if wb:
                title, blocks = wt, wb
                print(f"[digest] 주간 리포트 모드(일 11시): {title}")

        # 수집 파이프라인 정체 가시화 — 주요 시세는 apply_live_quotes 가 발송 시점 값으로 보정하지만,
        # 심리(공포탐욕)·운임(SCFI) 등 비보정 항목은 data.json 그대로다. 커밋이 2시간 넘게 끊겼으면
        # (fetch-data 타임아웃/취소 적체 실측 최대 3.4h — 2026-07 감사) 제목에 기준시각을 밝혀
        # 묵은 수치가 '지금 시황'처럼 보이지 않게 한다.
        try:
            lu = datetime.datetime.fromisoformat(str(data.get("lastUpdated")))
            age_min = (datetime.datetime.now(KST) - lu.astimezone(KST)).total_seconds() / 60
        except (ValueError, TypeError):
            age_min = None
        if age_min is not None and age_min > 120:
            title += f" (수집 {age_min / 60:.1f}h 전)"
            print(f"::warning title=데이터 스테일::data.json 이 {age_min:.0f}분 전 수집본 — 제목에 표기")
        # 스테일 자동 복구(P3) — 임계는 시간대별이다(_stale_limit_min). 2026-08-11 에 60→120 으로
        # 올렸는데도 장외·주말 오탐이 남았던 이유는 값이 아니라 '단일 임계'였기 때문이다:
        # 장중엔 Worker 가 5분마다 경량 런을 깨우지만 장외·주말엔 GHA 시간당 cron 하나뿐이고
        # 그 cron 의 실측 미발화율이 42%다(2026-09-08 진단, 10일 공백 28건 전부 장외).
        # 이번 발송은 라이브 보정 값으로 그대로 진행, 실패는 경고만.
        _stale_lim = _stale_limit_min(_now_kst, weekend)
        if age_min is not None and age_min > _stale_lim:
            print(f"[digest] 스테일 {age_min:.0f}분 > 임계 {_stale_lim}분 — 자동 복구 트리거")
            _dispatch_fetch_data()

        # 디스코드 병행 발송 — 카카오와 완전 독립(토큰 만료·발송 실패와 무관하게 도달).
        # 웹훅(DISCORD_WEBHOOK_URL) 미설정이면 no-op. 차트는 여기서 1회 생성해 카카오 피드에 재사용.
        _dc_png = None                               # 카카오 피드 이미지
        _card_ok = False                             # 편성표 카드 렌더 성공 여부
        _weekly_mode = title.startswith("주간")
        # 그날의 주인공을 한 번만 고른다 — 두 채널 카드가 같은 자산을 가리켜야 한다.
        _focus = (None, None) if _weekly_mode else pick_focus(
            data, slot, weekend, datetime.datetime.now(KST))
        try:
            import notify_discord
            if _charts_enabled():
                # 카톡 이미지도 디스코드와 같은 편성표를 쓴다(기획 d18ebb33 P1) —
                # 정사각 캔버스에 타일 9 + 히어로 인트라데이 1. 실패하면 종전 슬롯
                # 차트로 내려간다. 주간 리포트 슬롯은 본문이 '지난 7일'이라 지금 시각
                # 타일과 어긋나므로 종전 슬롯 차트를 유지한다.
                # 주간 슬롯도 카드로(기획 v3 I2) — 종전엔 여기서 None 으로 빠져 카톡만
                # 옛 라인 차트를 받았다. 주간은 주간 전용 정사각 카드를 쓴다.
                _dc_png = _build_kakao_card(
                    data, datetime.datetime.now(KST), slot, weekend,
                    weekly=_weekly_mode,
                    next_week=(next((v for lab, v in blocks if lab == "다음주"), "")
                               if _weekly_mode else ""),
                    focus=_focus if _focus[0] else None)
                _card_ok = bool(_dc_png)             # 편성표 카드가 실제로 그려졌나(중복 제거 조건)
                if not _dc_png:
                    _dc_png = build_slot_chart_png(data, slot, weekend)
            # embed(D1~D4 + E2) — 제목 클릭=대시보드, 필드=강도 기호(⏫⏬)+추세 스파크라인
            # +오늘 일정, 색띠=코스피 방향 동적(상승 빨강/하락 파랑/보합 회색 — 주간은 금색),
            # 버튼(E3)=딥링크 2개+지금 시세(봇 토큰 있을 때만 부착, 없으면 웹훅 그대로).
            # 시각 보드 카드(기획 2026-08-11) — 디스코드 본문은 카드 1장(평시=보드 A,
            # 주간=수익률 바 C). 렌더 실패 시 카카오용 슬롯 차트로 폴백해 이미지가
            # 절대 비지 않는다. 카카오 피드는 계속 _dc_png(슬롯 차트)를 쓴다.
            _card_png = None
            try:
                import discord_card
                _dc_now = datetime.datetime.now(KST)
                if _weekly_mode:
                    # 다음 주 일정은 build_weekly_parts 의 '다음주' 블록 재사용(단일 원천).
                    _nw = next((v for lab, v in blocks if lab == "다음주"), "")
                    _card_png = discord_card.weekly(data, _dc_now, next_week=_nw)
                else:
                    # 슬롯별 편성(2026-08-25) — 07시엔 한국·일본장이, 14시엔 미국장이
                    # 멈춰 있어 고정 12타일의 절반이 '안 움직이는 숫자'였다.
                    _card_png = discord_card.board(data, _dc_now, cal=_dc_cal_line(data),
                                                   slot=slot, weekend=weekend,
                                                   focus=_focus if _focus[0] else None)
            except Exception as _ce:
                print(f"[discord] 카드 렌더 예외({_ce}) — 슬롯 차트 폴백")
            _kchg = _f(((data.get("indices") or {}).get("KOSPI") or {}).get("change"))
            _dc_color = (notify_discord.COLOR_WEEKLY if _weekly_mode
                         else notify_discord.COLOR_FLAT if _kchg is None or abs(_kchg) < 0.05
                         else notify_discord.COLOR_UP if _kchg >= 0 else notify_discord.COLOR_DOWN)
            # v4(버튼 다이어트, 기획 ed0e5496): 카드가 있으면 필드 0개(이미지 최대
            # 노출), 카드 실패 시에만 종전 텍스트 필드로 폴백. 컴포넌트 = 유틸 버튼
            # 1행(3개) + 지표 드롭다운 1행 — 등락 정보는 카드가 단독 담당(구 v3
            # 타일 미러 그리드 16버튼 폐기). 웹훅 폴백 시 링크 필드로 자동 변환.
            # 개장 전 슬롯은 브리핑이라 본문이 더 길다(기획안 P3): AI 요약을 3줄 전부 싣고
            # 뉴스 2건을 필드로 붙인다. 다른 슬롯은 종전대로 2줄·필드 없음 — 카드가 본문이다.
            _is_brief = slot == "h07"
            _fields = None if _card_png else _dc_fields(blocks, data)
            if _is_brief:
                _nf = _news_field(data)
                if _nf:
                    _fields = (_fields or []) + [_nf]
            # 모바일 알림 미리보기에 보이는 것은 제목 한 줄뿐이다 — 이례적인 날은
            # 그 한 줄이 '무슨 일이 있었나'를 말해야 한다(기획안 원칙 4).
            _title = title
            if _focus[1] is not None:
                try:
                    import discord_card as _dcm
                    _n = _dcm.focus_note(data, _focus[0], _focus[1])
                    if _n:
                        _title = f"{title} · {_n}"
                except Exception:                            # noqa: BLE001
                    pass
            notify_discord.send(
                # P3(기획 5154773b) — AI 요약을 description 으로(카드 실패 폴백에도 도달).
                _ai_line(data, 3 if _is_brief else 2),
                png=_card_png or _dc_png, title=_title, url=DASHBOARD_URL,
                color=_dc_color,
                fields=_fields,
                footer=f"시세 {datetime.datetime.now(KST).strftime('%H:%M')} 기준(발송 직전 보정) · 무료 시세 지연 가능",
                timestamp=True, thread_name=_dc_thread_name(datetime.datetime.now(KST)),
                buttons=[_dc_buttons()], select=_dc_select(data, weekly=_weekly_mode))
        except Exception as _dce:
            print(f"[discord] 병행 발송 예외 무시: {_dce}")

        if not kakao_ready:
            # 디스코드는 위에서 이미 나갔다. 카카오 시크릿만 없으니 여기서 끝낸다 —
            # 센티널(.kakao_sent_ok)은 만들지 않아 백업 깨움이 재시도한다.
            print("[kakao] 시크릿 미설정 — 디스코드만 발송하고 종료")
            return

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
        # 피드 전용 본문 — 카드가 타일로 보여주는 지표는 빼고 조립한다(중복 제거).
        # 카드가 실패해 슬롯 라인 차트로 내려간 경우엔 편성표와 무관한 2티커 차트라
        # 그대로 전체를 싣는다. 텍스트 폴백(②③)도 계속 전체 blocks 를 쓴다.
        feed_blocks = blocks
        if _card_ok and not _weekly_mode:
            _drop = _card_tile_labels(slot, weekend, _now_kst)
            if _drop:
                _fb = build_digest_parts(data, drop=_drop, slot=slot)[1]
                if _fb:
                    feed_blocks = _fb
                    print(f"[digest] 카드 중복 제거: {', '.join(sorted(_drop))} → 본문 블록 "
                          f"{len(blocks)}→{len(_fb)}개")

        if _charts_enabled():
            if send_chart_feed(access_token, data, title, feed_blocks, slot, weekend,
                               uuids=uuids, png=_dc_png, full_blocks=blocks):
                _mark_sent_ok()                      # 실제 발송 성공 — 여기서만 센티널 생성
                print(f"[kakao] 발송 완료 (차트 피드 한 통, slot={slot})")
                return
            # 차트 없는 발송으로 열화되는 순간 — 로그를 훑지 않아도 런 요약(Annotations)에 바로 보이게.
            print(f"::warning title=차트 누락 폴백::차트 피드 실패 — 동일 내용 텍스트로 폴백(slot={slot}). "
                  "사유는 앞선 [chart] 경고 참고")

        # ② 차트 비활성(KAKAO_CHARTS=0) 경로 — 사진 없는 발송이 의도인 유일한 자리다
        #    (기획 v3 I5 화이트리스트). 카드가 있는 평시 경로는 send_chart_feed → send_card 가 담당.
        #    (콘솔 커스텀 템플릿 폴백은 형식이 달라 혼란을 줬으므로 제거 — 2026-06-10 10시 사례)
        send_memo(access_token, build_text_message(title, blocks), with_button=True, uuids=uuids)
        _mark_sent_ok()                              # 텍스트 폴백도 '발송 성공'(실패면 위에서 SystemExit)
        print(f"[kakao] 발송 완료 (텍스트 폴백, slot={slot})")
    except SystemExit as e:
        print(f"::warning title=Kakao 발송 건너뜀::{e} — 토큰 만료/회전 또는 발송 실패 추정. "
              "KAKAO_SETUP.md ③ 절차로 KAKAO_REFRESH_TOKEN 시크릿을 갱신하면 다음 슬롯부터 발송이 복구됩니다. "
              "(워크플로는 정상 종료 — 매 슬롯 실패 알림 메일 방지)")
        _step_summary(f"❌ 카카오 발송 건너뜀: {e}")
        try:
            import notify_discord
            notify_discord.system(f"카카오 다이제스트 발송 실패(토큰 만료/발송 오류 추정): {e}\n"
                                  "디스코드 발송은 별도 경로라 정상일 수 있음. KAKAO_SETUP.md ③ 참고.")
        except Exception:
            pass
    except Exception as e:
        # 예상 밖 예외(토큰 재발급 전송예외의 재시도 소진, 데이터 필드 이상 등)도 job 을 죽이지
        # 않는다 — job 실패는 곧 실패 메일이고, 센티널 부재로 백업 깨움이 어차피 재시도한다.
        # (2026-07 감사: except SystemExit 만 잡아 URLError 등이 그대로 새던 구멍 봉합.)
        print(f"::warning title=Kakao 발송 실패(예상 밖 오류)::{type(e).__name__}: {e} — "
              "워크플로는 정상 종료(실패 메일 방지), 같은 슬롯은 백업 깨움이 재시도합니다.")
        _step_summary(f"❌ 카카오 발송 실패(예상 밖 오류): {type(e).__name__}: {e}")


def _step_summary(line):
    """::warning 은 로그를 열어야 보인다 — 런 첫 화면(Summary)에도 남겨 무음 유실을 눈에 띄게 한다."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return
    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"{line}\n\n")
    except OSError as we:
        print(f"[kakao] STEP_SUMMARY 기록 실패({we}) — 경고 로그로 갈음")


if __name__ == "__main__":
    main()
