#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""디스코드 발송 공용 모듈 — 카카오와 병행(채널 이중화, 카카오 무음 폴백의 근본 해결).

채널 구조(2026-08-05 D5): 발송처별 전용 웹훅 env 를 쓰고, 없으면 기본(DISCORD_WEBHOOK_URL
= #시황-다이제스트)으로 폴백한다 — 시크릿 일부만 등록해도 동작.
  DISCORD_WEBHOOK_URL     #시황-다이제스트 (digest)
  DISCORD_WEBHOOK_ALERTS  #종목-알림     (check_alerts)
  DISCORD_WEBHOOK_SWINGS  #급변-속보     (check_swings·check_halts)
  DISCORD_WEBHOOK_SYSTEM  #시스템        (파이프라인 경고 — system())
미설정이면 조용히 no-op(False). 실패는 경고만 — 호출측 카카오 경로에 절대 영향 없음.
한도: content 2000자 · 제목 256 · description 4096 · 필드 1024 · embed 합 6000 — 넘치면 fit() 이 줄 단위로
자르고 「외 N항목」을 붙인다(글자 중간에서 자르지 않는다). 웹훅당 2초에 5요청.

── 표기 표준(E7) — 채널 전체 일관성의 단일 출처 ─────────────────────────────
색띠(embed color): 정기=네이비(주간=금색) · 급변/서킷 발동=빨강 · 해제=초록 ·
  운영/테스트=회색 · 다이제스트 동적색=코스피 방향(상승 빨강/하락 파랑/보합 회색 —
  국내 관습, ±0.05% 기준).
이모지 사전: 📊 정기 시황 · 🔔 종목/마감 · ⚡ 급변 · 🔴 서킷 · 💚 하트비트 · ⚙️ 운영.
등락 강도(E2): ±2% 미만 ▲/▼ · 이상 ⏫/⏬ (텍스트 embed 는 send_kakao_digest._dc_intensity,
  버튼 라벨은 direction_emoji / dir_label).
필드 순서: 증시 → 환율 → 심리 → 에너지 → 금속 → 곡물 → 운임 → 추세 → 📅 일정.
footer: 항상 신선도 한 줄("시세 HH:MM 기준…" 또는 DELAY_NOTICE).
도달 티어(E1): T1 급변·서킷=@everyone / T2 종목=@종목알림 역할 / T3 정기=무멘션
  (+스레드 멤버 푸시) / T4 운영=무멘션. mention 파라미터: True|"everyone"|"role:이름"|None.
"""
import os
import re
import json
import uuid
import datetime
import urllib.request

WEBHOOK_ENV = "DISCORD_WEBHOOK_URL"
# 디스코드(Cloudflare)가 파이썬 기본 UA(Python-urllib)를 403 으로 차단한다 — 반드시 지정.
_UA = "economic-site-notifier/1.0 (+https://github.com/0101-commits/economic-site)"
_API = "https://discord.com/api/v10"
# 발신 표시명 통일(2026-08-11 사용자 지시) — 웹훅은 메시지별 username 필드로,
# 봇 계정(구 econ-terminal-bot)은 최초 발송 시 /users/@me PATCH 로 개명한다.
BOT_NAME = "ecom"

# ── 버튼 라벨 방향 이모지(기획 2026-08-15) ────────────────────────────────
# 디스코드 네이티브 버튼은 색/이미지가 고정이라 방향·강도를 라벨 이모지로 표현.
# E2 표준(±2%) 임계를 공유 — 텍스트 embed 의 _dc_intensity 와 같은 판정.

def direction_emoji(c):
    """등락률 → 방향 이모지. None/|c|<0.05=➖(보합), ±2% 이상=⏫/⏬, 그 외 📈/📉."""
    try:
        c = float(c)
    except (TypeError, ValueError):
        return "➖"
    if c != c:  # NaN → 보합
        return "➖"
    if abs(c) < 0.05:
        return "➖"
    if c >= 2.0:
        return "⏫"
    if c <= -2.0:
        return "⏬"
    return "📈" if c > 0 else "📉"


def dir_label(name, c):
    """버튼 라벨 — 이모지 + 이름 + 등락률(보합·무데이터는 퍼센트 생략).

    예: dir_label("코스피", 1.8) == "📈 코스피 +1.8%"
        dir_label("구리", None)  == "➖ 구리"
    """
    try:
        c = float(c)
    except (TypeError, ValueError):
        c = None
    emoji = direction_emoji(c)
    pct = "" if emoji == "➖" else f" {c:+.1f}%"
    return f"{emoji} {name}{pct}"

# ── 네이버 증권 딥링크(기획 c661d5b0 v3) ──────────────────────────────────
# 2026-08-11 2중 검사(최종 URL 동일성 + 본문 키워드) 통과분만 등록한다.
# 네이버는 미제공 지표를 404 대신 타 페이지로 조용히 리다이렉트하므로(소프트 200 —
# VKOSPI 가 코스피로 302 하던 실측) 후보 추가는 반드시 검사를 먼저 거칠 것.
#
# ⚠ 2026-09-22 실측 — 네이버가 finance.naver.com 을 stock.naver.com(Npay 증권)으로
#   전면 이전했다. 아래 레거시 URL 은 전부 301 로 새 페이지에 정확히 도착하므로 그대로
#   둔다. 새 주소로 바꾸지 않는 이유는 검사 때문이다: 새 사이트는 SPA 셸이라 어느
#   지표든 <title> 이 "Npay 증권" 하나뿐이고 본문에 지표명이 없다 — 본문 키워드 검사가
#   통째로 무력해져 죽은 링크와 산 링크가 구별되지 않는다. 레거시 URL 은 서버 렌더라
#   check_links.py 의 탐지력이 살아 있다.
#   새 사이트에서 쓸 수 있는 판별은 '요청한 경로에 머무르는가 vs 루트(/)로 튕기는가'다 —
#   없는 코드(metals/ZZZZcv1 대조군)는 stock.naver.com/ 루트로 307 한다.
# ⚠ 2026-09-28 정정 — 09-22 의 'US10Y·KR10Y·EU10Y·DXY 미제공' 판정은 틀렸다(또는 그 뒤에
#   생겼다). CI 실측(check_links.py --probe, Link Check run 36408691685): 아래 bond/.DXY
#   주소는 데스크톱 200 에 머물고, 카카오 인앱 UA 는 m.stock.naver.com 의 같은 지표로 가서
#   제목이 '미국 국채 10년 / 한국 국채 10년 / 독일 국채 10년 / 달러인덱스 - Npay 증권' 이다.
#   목록에서 빠져 있던 탓에 us_pre 카드(주인공 미국채 10Y)의 사진·버튼이 달러-원으로 갔다.
# 미제공 확정: VKOSPI·MOVE·PutCall·HY·SCFI(404), 밀·옥수수(agricultural/ZWcv1·ZCcv1 →
#   루트, 2026-09-28) — 이 둘은 DASH_LINKS 가 대시보드의 같은 지표 화면으로 보낸다.
# 이 dict 의 URL 은 check_links.py 가 주기 점검한다(개편 감지 + 루트 튕김 = 끊김).
_NF = "https://finance.naver.com"
_NS = "https://stock.naver.com"
NAVER_LINKS = {
    "KOSPI": _NF + "/sise/sise_index.naver?code=KOSPI",
    "KOSDAQ": _NF + "/sise/sise_index.naver?code=KOSDAQ",
    "SP500": _NF + "/world/sise.naver?symbol=SPI@SPX",
    "NASDAQ": _NF + "/world/sise.naver?symbol=NAS@IXIC",
    "Nikkei": _NF + "/world/sise.naver?symbol=NII@NI225",
    "SOX": _NF + "/world/sise.naver?symbol=NAS@SOX",
    # 2026-09-22 추가 — 카드 타일에 매번 그려지는데 링크가 없던 셋.
    "Shanghai": _NF + "/world/sise.naver?symbol=SHS@000001",
    "USDKRW": _NF + "/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW",
    "USDJPY": _NF + "/marketindex/worldExchangeDetail.naver?marketindexCd=FX_USDJPY",
    "EURUSD": _NF + "/marketindex/worldExchangeDetail.naver?marketindexCd=FX_EURUSD",
    "Gold": _NF + "/marketindex/worldGoldDetail.naver?marketindexCd=CMDT_GC",
    "Silver": _NF + "/marketindex/worldGoldDetail.naver?marketindexCd=CMDT_SI",
    # 구리만 새 주소다 — 레거시 경로(worldDailyQuote?marketindexCd=CMDT_CDY)는 410 이고
    # 새 사이트에는 페이지가 생겼다. 예전 '미제공' 판정은 레거시 기준이었다.
    "Copper": _NS + "/marketindex/metals/HGcv1/price",
    "WTI": _NF + "/marketindex/worldOilDetail.naver?marketindexCd=OIL_CL",
    "Brent": _NF + "/marketindex/worldOilDetail.naver?marketindexCd=OIL_BRT",
    "NatGas": _NF + "/marketindex/worldOilDetail.naver?marketindexCd=CMDT_NG",
    # 2026-09-28 추가 — 금리·달러 편성(us_pre·weekend)의 칸. 새 사이트 주소(레거시 페이지 없음).
    "US10Y": _NS + "/marketindex/bond/US10YT=RR/price",
    "KR10Y": _NS + "/marketindex/bond/KR10YT=RR/price",
    # 카드의 '유로 10Y' 값은 ECB 유로존 AAA 곡선 10Y 다. 네이버에는 그 곡선이 없어 카드 영문
    # 라벨(Bund 10Y)대로 유로 금리의 벤치마크인 독일 국채 10년에 잇는다(수준은 몇 bp 다르다).
    "EU10Y": _NS + "/marketindex/bond/DE10YT=RR/price",
    "DXY": _NS + "/marketindex/exchange/.DXY/price",
}


# 네이버에 페이지가 없는 카드 지표 → **같은 지표의** 대시보드 화면(ECON_IND canonical).
# 종전 규칙은 '없으면 목록에서 빼고 다음 칸을 대표로'였다 — 그래서 카드가 미국채 10Y 를
# 크게 그려 놓고 사진·버튼은 달러-원 네이버 차트로 갔다(2026-09-28 사용자 제보, us_pre 편성).
# 링크는 다른 지표로 대체하지 않는다. 우리 도메인이라 카카오 중계(go.html)도 필요 없다.
DASHBOARD = "https://0101-commits.github.io/economic-site/"
# 새 카드 키가 네이버·대시보드 어느 쪽에도 없으면 test_card_links 가 실패한다.
DASH_LINKS = {
    "Wheat": DASHBOARD + "?p=market&t=commodity",
    "Corn": DASHBOARD + "?p=market&t=commodity",
}


def asset_link(key):
    """카드 지표 키 → 그 지표의 차트 페이지. 네이버 우선, 없으면 대시보드의 같은 지표 화면.
    모르는 키는 None — 호출측이 다른 지표로 떨어뜨리지 않게 '없음'을 그대로 돌려준다."""
    return NAVER_LINKS.get(key) or DASH_LINKS.get(key)


def naver_stock_url(code):
    """국내 종목(6자리 코드) 네이버 페이지 — 형식이 아니면 None(깨진 링크 방지)."""
    c = str(code or "").strip()
    # 신형 ETF 는 영문이 섞인 6자리다(0018Z0 등, 2026-09-23 실측 — 숫자만 받아 링크가 빠졌다).
    return f"{_NF}/item/main.naver?code={c}" if re.fullmatch(r"[0-9A-Z]{6}", c) else None

# 시맨틱 컬러(D1) — 메시지 글자색은 디스코드가 지원하지 않아(ANSI 코드블록은 모바일 미표시)
# embed 색띠가 표준. 알림 성격별 고정 팔레트:
COLOR_DIGEST = 0x23408E    # 시황 다이제스트 — 네이비(보합 시 기본)
COLOR_WEEKLY = 0xC9A227    # 주간 리포트 — 금색
COLOR_ALERT = 0xE67E22     # 종목 알림 — 주황
COLOR_FIRE = 0xD83C3E      # 급변·서킷 발동 — 빨강
COLOR_RESOLVE = 0x3BA55D   # 경보 해제·하트비트 — 초록
COLOR_SYSTEM = 0x99AAB5    # 시스템(운영 경고) — 회색
COLOR_TEST = 0x99AAB5      # 테스트 — 회색
COLOR_UP = 0xE0443E        # 다이제스트 동적색 — 코스피 상승(빨강, 국내 관습)
COLOR_DOWN = 0x3E7BE0     # 다이제스트 동적색 — 코스피 하락(파랑)
COLOR_FLAT = 0x99AAB5      # 다이제스트 동적색 — 보합(회색)


def _clean(v):
    """env 값 정리 — Windows PowerShell 파이프 등록 시크릿의 BOM(U+FEFF) 방어
    ('unknown url type: ﻿https' 로 죽던 실측)."""
    return (v or "").strip().lstrip("﻿").strip()


def _hook(env):
    """웹훅 URL 결정 — 전용 env 우선, 없으면 기본으로 폴백."""
    for name in ([env, WEBHOOK_ENV] if env and env != WEBHOOK_ENV else [WEBHOOK_ENV]):
        u = _clean(os.environ.get(name))
        if u:
            return u
    return ""


def _bot_token():
    return _clean(os.environ.get("DISCORD_BOT_TOKEN"))


_INFO_CACHE = {}


def _webhook_info(hook):
    """웹훅 → {channel_id, guild_id} (토큰 불필요·프로세스 캐시)."""
    if hook not in _INFO_CACHE:
        _INFO_CACHE[hook] = json.load(urllib.request.urlopen(
            urllib.request.Request(hook, headers={"User-Agent": _UA}), timeout=10))
    return _INFO_CACHE[hook]


def _bot_get(path, tok):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(f"{_API}{path}",
                               headers={"Authorization": f"Bot {tok}", "User-Agent": _UA}),
        timeout=10))


def _ensure_bot_name(tok):
    """봇 계정 username 을 BOT_NAME('ecom')으로 동기화 — 프로세스당 1회, 멱등.
    디스코드 username 변경은 시간당 2회 제한이라 다르면 그때만 PATCH. 실패는 경고만."""
    if _INFO_CACHE.get("_name_synced") or not tok:
        return
    _INFO_CACHE["_name_synced"] = True
    try:
        me = _bot_get("/users/@me", tok)
        if (me.get("username") or "") != BOT_NAME:
            urllib.request.urlopen(urllib.request.Request(
                f"{_API}/users/@me",
                data=json.dumps({"username": BOT_NAME}).encode("utf-8"),
                headers={"Authorization": f"Bot {tok}", "User-Agent": _UA,
                         "Content-Type": "application/json"},
                method="PATCH"), timeout=10)
            print(f"[discord] 봇 이름 {me.get('username')} → {BOT_NAME} 변경")
    except Exception as e:
        print(f"[discord] 봇 이름 동기화 실패 무시: {e}")


_ROLE_CACHE = {}


def _mention_content(mention, hook):
    """멘션 값 → content 문자열(E1 도달 티어).
    True|"everyone" → "@everyone" / "role:이름" → "<@&id>"(봇 토큰으로 이름 조회,
    역할은 '누구나 멘션 허용' 상태여야 웹훅에서도 핑이 감) / 그 외 → None.
    역할을 못 찾으면 None(무멘션) — 발송 자체는 계속한다."""
    if mention is True or mention == "everyone":
        return "@everyone"
    if isinstance(mention, str) and mention.startswith("role:"):
        name = mention[5:].strip()
        tok = _bot_token()
        if not (name and tok):
            return None
        try:
            gid = _webhook_info(hook).get("guild_id")
            if not gid:
                return None
            key = (gid, name)
            if key not in _ROLE_CACHE:
                roles = _bot_get(f"/guilds/{gid}/roles", tok)
                _ROLE_CACHE[key] = next((r["id"] for r in roles if r.get("name") == name), None)
            rid = _ROLE_CACHE[key]
            return f"<@&{rid}>" if rid else None
        except Exception as e:
            print(f"[discord] 역할 멘션 해석 실패({e}) — 무멘션 발송")
            return None
    return None


def _components(buttons):
    """buttons → 디스코드 컴포넌트. 평면 리스트 [(라벨, url|'id:…'), …]=1행(종전 호환)
    또는 행 리스트 [[(…), …], …]=다행(v3 버튼 그리드). 행 5개·행당 5버튼 상한.
    링크 버튼은 style 5(url), 액션 버튼은 style 1(custom_id — Worker /discord 가 처리)."""
    if not buttons:
        return None
    rows_in = buttons if isinstance(buttons[0], list) else [buttons]
    comps = []
    for row_in in rows_in[:5]:
        row = []
        for lab, target in row_in[:5]:
            if str(target).startswith("id:"):
                row.append({"type": 2, "style": 1, "label": str(lab)[:80],
                            "custom_id": str(target)[3:][:100]})
            else:
                row.append({"type": 2, "style": 5, "label": str(lab)[:80], "url": str(target)})
        if row:
            comps.append({"type": 1, "components": row})
    return comps or None


def _select_component(select, placeholder="📈 지표 차트 바로가기…"):
    """select=[(라벨, 값)] → String Select 1행(v4 버튼 다이어트 — 기획 ed0e5496).
    값은 NAVER_LINKS 키를 쓴다(Worker /discord 의 goto_link 가 URL 로 해석).
    옵션 25개 상한. 봇 경로에서만 부착 — 웹훅 폴백은 send() 가 링크 필드로 강등."""
    if not select:
        return None
    opts = [{"label": str(l)[:100], "value": str(v)[:100]} for l, v in select[:25]]
    return {"type": 1, "components": [{
        "type": 3, "custom_id": "goto_link",
        "placeholder": placeholder[:150], "options": opts}]}


def _ensure_thread_member(tid, gid, tok):
    """서버 소유자를 스레드 멤버로 등록 — 스레드 메시지는 '가입자'에게만 알림·푸시가
    가는 디스코드 사양이라, 미가입 상태면 다이제스트가 전부 무음이 된다(실측 원인).
    PUT 은 멱등이라 매 발송 보장해도 무해. 실패는 적재엔 지장 없어 경고만."""
    try:
        own = _bot_get(f"/guilds/{gid}", tok).get("owner_id")
        if own:
            urllib.request.urlopen(urllib.request.Request(
                f"{_API}/channels/{tid}/thread-members/{own}",
                headers={"Authorization": f"Bot {tok}", "User-Agent": _UA}, method="PUT"), timeout=10)
    except Exception as e:
        print(f"::warning title=Discord 스레드 멤버 등록 실패::{e} — 스레드 적재는 되나 푸시가 없을 수 있음")


def _thread_id(hook, name):
    """일자 스레드 확보(D10) — 같은 이름의 활성 스레드가 있으면 재사용, 없으면 생성.
    DISCORD_BOT_TOKEN 필요(웹훅만으론 기존 텍스트 채널에 스레드 생성 불가).
    실패·미설정 시 None → 호출측이 채널 본문으로 발송(기능 열화 없음)."""
    tok = _bot_token()
    if not tok:
        return None
    try:
        info = _webhook_info(hook)
        cid, gid = info.get("channel_id"), info.get("guild_id")
        if not cid or not gid:
            return None
        act = _bot_get(f"/guilds/{gid}/threads/active", tok)
        tid = None
        for t in act.get("threads", []):
            if t.get("parent_id") == cid and t.get("name") == name:
                tid = t["id"]
                break
        if not tid:
            hdr = {"Authorization": f"Bot {tok}", "User-Agent": _UA, "Content-Type": "application/json"}
            made = json.load(urllib.request.urlopen(
                urllib.request.Request(f"{_API}/channels/{cid}/threads",
                                       data=json.dumps({"name": name, "type": 11,
                                                        "auto_archive_duration": 1440}).encode("utf-8"),
                                       headers=hdr, method="POST"), timeout=10))
            tid = made.get("id")
        if tid:
            _ensure_thread_member(tid, gid, tok)
        return tid
    except Exception as e:
        print(f"[discord] 일자 스레드 확보 실패({e}) — 채널 본문으로 발송")
        return None


# 디스코드 글자 한도(API 사양). 칸 하나라도 넘으면 400 으로 메시지가 통째로 거절된다.
LIMIT_CONTENT, LIMIT_TITLE, LIMIT_DESC = 2000, 256, 4096
LIMIT_FIELD_NAME, LIMIT_FIELD, LIMIT_FOOTER, LIMIT_EMBED = 256, 1024, 2048, 6000


def fit(text, limit):
    """한도 맞추기 단일 창구 — send() 의 모든 글 칸(본문·제목·설명·필드·꼬리)이 여기를 지난다.

    넘치면 줄 단위로 앞에서부터 남기고 마지막 줄 끝에 「 외 N항목」을 붙인다(send_kakao_digest._pack 과
    같은 꼴, N = 못 실은 줄 중 빈 줄이 아닌 것). 종전의 `[:4096]` 은 글자 중간에서 잘라 마크다운 링크가
    깨졌고, 받는 쪽은 빠진 줄이 있는지 몰랐다. 첫 줄부터 넘치면 그 줄을 「…」로 자른다."""
    s = "" if text is None else str(text)
    if len(s) <= limit:
        return s
    lines = s.split("\n")
    for k in range(len(lines) - 1, 0, -1):                # k = 남길 줄 수, 많은 쪽부터
        n = sum(1 for x in lines[k:] if x.strip())
        out = "\n".join(lines[:k]).rstrip() + (f" 외 {n}항목" if n else "")
        if len(out) <= limit:
            return out
    n = sum(1 for x in lines[1:] if x.strip())
    tail = f" 외 {n}항목" if n else ""
    out = lines[0][:max(0, limit - len(tail) - 1)] + "…" + tail
    return out if len(out) <= limit else ""


def _fit_embed_total(e):
    """embed 하나의 글자 합(제목+설명+필드+꼬리) 6,000 — 칸마다 한도 안이어도 합이 넘으면 400 이다. 설명부터 줄인다."""
    size = lambda: (len(e.get("title") or "") + len(e.get("description") or "")
                    + len((e.get("footer") or {}).get("text") or "")
                    + sum(len(f["name"]) + len(f["value"]) for f in e.get("fields") or []))
    over = size() - LIMIT_EMBED
    if over > 0 and e.get("description"):
        e["description"] = fit(e["description"], max(0, len(e["description"]) - over))
    # ponytail: 설명으로 못 메우면 뒤 필드를 덜어 낸다(로그만). 필드 합이 6천을 넘는 발송처가 생기면 필드 단위 「외 N항목」.
    while size() > LIMIT_EMBED and e.get("fields"):
        print(f"[discord] embed 6,000자 초과 — 필드 「{e['fields'].pop()['name']}」 생략")


def _post(url, payload, png, filename, extra_headers=None):
    """JSON 또는 (png 있으면) multipart 로 POST. 예외는 호출측에서 처리. 봇·웹훅 두 경로가 다 여기를 지난다."""
    for e in payload.get("embeds") or []:
        _fit_embed_total(e)
    headers = {"User-Agent": _UA}
    headers.update(extra_headers or {})
    if png:
        b = uuid.uuid4().hex
        head = (f'--{b}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
                f'Content-Type: application/json\r\n\r\n'
                + json.dumps(payload, ensure_ascii=False) + "\r\n"
                + f'--{b}\r\nContent-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'
                f'Content-Type: image/png\r\n\r\n').encode("utf-8")
        body = head + png + f"\r\n--{b}--\r\n".encode("utf-8")
        headers["Content-Type"] = f"multipart/form-data; boundary={b}"
        req = urllib.request.Request(url, data=body, headers=headers)
    else:
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers=headers)
    urllib.request.urlopen(req, timeout=20)


def send(text, png=None, filename="chart.png", title=None, url=None,
         color=None, fields=None, footer=None, timestamp=False, mention=False,
         env=WEBHOOK_ENV, thread_name=None, buttons=None, select=None, flags=None):
    """텍스트(+선택 PNG 첨부) 발송. 성공 True / 미설정·실패 False.

    png 는 bytes 또는 파일 경로(str) — build_slot_chart_png 가 경로를 반환하므로 둘 다 받는다.
    title 을 주면 embed 형식: 제목이 url(대시보드 딥링크)로 하이퍼링크, color=좌측 색띠,
    fields=[(이름, 값, inline)] 2열 그리드(D3), footer=신선도 한 줄(D4), timestamp=수신 시각.
    ⚠ 이미지 클릭은 디스코드 정책상 항상 '확대 보기' — 이동은 제목·버튼이 담당.
    mention(E1): True|"everyone"=@everyone / "role:이름"=역할 멘션 / None·False=무멘션.
    buttons(E3): [(라벨, url 또는 "id:custom_id"), …] — 봇 토큰이 있으면 봇 메시지로
    보내 버튼을 단다(웹훅은 컴포넌트 불가). 봇 경로 실패 시 버튼 없이 웹훅 폴백.
    select(v4): [(라벨, NAVER_LINKS 키)] — 지표 딥링크 드롭다운 1행(버튼 다이어트,
    기획 ed0e5496). 버튼과 같은 규칙: 봇 경로만, 폴백 시 링크 필드로 강등.
    flags(v2): 메시지 플래그 비트필드 — SUPPRESS_NOTIFICATIONS(4096)면 알림음 없이 올라간다. None=종전."""
    hook = _hook(env)
    if not hook:
        return False
    tid = None
    if thread_name:                                   # D10 — 일자 스레드로 묶기(실패 시 본문)
        tid = _thread_id(hook, thread_name)
    if title:
        embed = {"title": fit(title, LIMIT_TITLE), "description": fit(text, LIMIT_DESC)}
        if url:
            embed["url"] = url                       # 제목 클릭 → 대시보드
        if color is not None:
            embed["color"] = color
        if fields:
            embed["fields"] = [{"name": fit(n, LIMIT_FIELD_NAME), "value": fit(v, LIMIT_FIELD), "inline": bool(i)}
                               for n, v, i in fields[:25]]
        if footer:
            embed["footer"] = {"text": fit(footer, LIMIT_FOOTER)}
        if timestamp:
            embed["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if png:
            embed["image"] = {"url": f"attachment://{filename}"}
        payload = {"embeds": [embed]}
        m = _mention_content(mention, hook)
        if m:
            payload["content"] = m
        plen = len(embed["description"]) + len(embed["title"])
    else:
        m = _mention_content(mention, hook)
        head = m + " " if m else ""
        payload = {"content": head + fit(text, LIMIT_CONTENT - len(head))}
        plen = len(payload["content"])
    if flags:
        payload["flags"] = flags
    if isinstance(png, str):
        try:
            with open(png, "rb") as f:
                png = f.read()
        except OSError as e:
            print(f"::warning title=Discord 차트 읽기 실패::{e} — 이미지 없이 발송")
            png = None

    # 봇 경로(E3) — 컴포넌트(버튼·드롭다운)가 필요하고 봇 토큰이 있으면 봇 메시지로
    # (웹훅은 컴포넌트 불가). 행 5개 상한은 디스코드 사양.
    tok = _bot_token()
    comps = _components(buttons)
    sel = _select_component(select)
    allc = ((comps or []) + ([sel] if sel else []))[:5]
    if allc and tok:
        try:
            _ensure_bot_name(tok)
            cid = tid or _webhook_info(hook).get("channel_id")
            if cid:
                _post(f"{_API}/channels/{cid}/messages", {**payload, "components": allc},
                      png, filename, {"Authorization": f"Bot {tok}"})
                nbtn = sum(len(r["components"]) for r in (comps or []))
                print(f"[discord] 발송 성공 ({plen}자{', 이미지 첨부' if png else ''}"
                      f"{', embed' if title else ''}, 봇+버튼 {nbtn}개"
                      f"{'+드롭다운' if sel else ''}, env={env})")
                return True
        except Exception as e:
            print(f"[discord] 봇 발송 실패({e}) — 컴포넌트 없이 웹훅 폴백")

    # 웹훅 경로(종전) — 컴포넌트가 빠지므로(웹훅은 컴포넌트 불가) 링크 버튼·드롭다운
    # 옵션을 embed 필드 한 줄로 자동 변환해 도달을 보장한다(v3 안전망 — 평시 봇 경로에선 미표시).
    if (comps or sel) and title:
        try:
            links = [f"[{c['label']}]({c['url']})"
                     for r in (comps or []) for c in r["components"] if c.get("url")]
            if sel:
                for o in sel["components"][0]["options"]:
                    u = NAVER_LINKS.get(o["value"])
                    if u:
                        links.append(f"[{o['label']}]({u})")
            fs = payload["embeds"][0].setdefault("fields", [])
            # 필드당 1024자 제한 — 중간에서 자르면 마크다운 링크가 깨지므로 링크
            # 단위로 청크를 나눠 여러 필드로(최대 3개, 이름은 첫 필드만).
            chunk, chunks = [], []
            for lk in links:
                if sum(len(x) + 3 for x in chunk) + len(lk) > 1000:
                    chunks.append(chunk)
                    chunk = []
                chunk.append(lk)
            if chunk:
                chunks.append(chunk)
            for i, ch in enumerate(chunks[:3]):
                if len(fs) >= 25:
                    break
                fs.append({"name": "바로가기(버튼 대체)" if i == 0 else "​",
                           "value": " · ".join(ch), "inline": False})
        except Exception:
            pass
    try:
        wh = hook + (("&" if "?" in hook else "?") + f"thread_id={tid}" if tid else "")
        _post(wh, {**payload, "username": BOT_NAME}, png, filename)
        print(f"[discord] 발송 성공 ({plen}자{', 이미지 첨부' if png else ''}{', embed' if title else ''}, env={env})")
        return True
    except Exception as e:
        print(f"::warning title=Discord 발송 실패::{type(e).__name__}: {e} — 카카오 경로는 영향 없음")
        return False


def system(text, title="⚙️ 파이프라인 경고", color=None, mention=False):
    """운영 통지(D8·E6) — #시스템 채널로. 토큰 만료·수집 실패·스테일 등 '알림이 안 오는 상황'
    자체와 데일리 하트비트를 통지한다. 실패·미설정은 조용히 무시(경고 채널이 본 경로를
    깨면 본말전도). color 기본=회색, 하트비트는 COLOR_RESOLVE(초록)."""
    try:
        return send(text, title=title, color=COLOR_SYSTEM if color is None else color,
                    timestamp=True, mention=mention, env="DISCORD_WEBHOOK_SYSTEM")
    except Exception:
        return False


# ── 등급별 발송(알림 v2 A5, 계약서 docs/superpowers/plans/2026-10-05-alerts-v2.md 「등급 level」) ──
# 등급 → (웹훅 env, 멘션, 플래그, 색띠). 채널·멘션·무음은 여기 한 표가 단일 원천이다.
SUPPRESS_NOTIFICATIONS = 1 << 12            # 4096 — 알림음·푸시 없이 올라간다(디스코드 공식 플래그)
LEVEL_BODY_MAX = 1500                       # 한 통 embed 글자 합(계약서 Global Constraints)
LEVELS = {
    "alarm":  ("DISCORD_WEBHOOK_SWINGS", "everyone", None, COLOR_FIRE),
    "alert":  ("DISCORD_WEBHOOK_ALERTS", None, None, COLOR_ALERT),
    "notice": ("DISCORD_WEBHOOK_ALERTS", None, SUPPRESS_NOTIFICATIONS, COLOR_DIGEST),
    "brief":  (WEBHOOK_ENV, None, SUPPRESS_NOTIFICATIONS, COLOR_DIGEST),
    "ops":    ("DISCORD_WEBHOOK_SYSTEM", None, None, COLOR_SYSTEM),
}


def send_level(level, title, body, *, fields=None, url=None, buttons=None, png=None,
               footer=None, mention=None):
    """등급 → 채널·멘션·플래그를 정해 send() 로 보낸다. 성공 True / 미설정·실패·기록 False.

    alarm=#급변-속보+@everyone · alert=#종목-알림 · notice=#종목-알림+무음 · brief=#시황-다이제스트+무음 ·
    ops=#시스템. record 는 화면(원장)에만 남기고 보내지 않는다(False). 모르는 등급은 ValueError —
    이름이 어긋난 경보가 조용히 사라지는 것보다 낫다.
    제목은 호출측이 정한 그대로(두 채널 제목 동일 원칙은 compose 가 보장). 본문은 제목·필드·꼬리를 뺀
    남은 글자 안으로 fit() 한다 — embed 합계 LEVEL_BODY_MAX. mention 을 주면 등급 표를 덮는다
    (침묵 감시만 ops 에 "everyone"). 웹훅 env 폴백(→ DISCORD_WEBHOOK_URL)·미설정 no-op 은 send() 규칙 그대로."""
    if level == "record":
        return False
    if level not in LEVELS:
        raise ValueError(f"모르는 등급: {level!r} (알림 {sorted(LEVELS)} · 기록 record)")
    env, lv_mention, flags, color = LEVELS[level]
    used = len(title or "") + len(footer or "") + sum(len(n) + len(v) for n, v, _ in fields or [])
    return send(fit(body, max(0, LEVEL_BODY_MAX - used)), png=png, title=title, url=url, color=color,
                fields=fields, footer=footer, mention=lv_mention if mention is None else mention,
                env=env, buttons=buttons, flags=flags)
