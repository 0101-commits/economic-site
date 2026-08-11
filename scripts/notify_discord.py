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
한도: description 4096자/content 2000자(넘으면 자름), 웹훅당 2초에 5요청.

── 표기 표준(E7) — 채널 전체 일관성의 단일 출처 ─────────────────────────────
색띠(embed color): 정기=네이비(주간=금색) · 급변/서킷 발동=빨강 · 해제=초록 ·
  운영/테스트=회색 · 다이제스트 동적색=코스피 방향(상승 빨강/하락 파랑/보합 회색 —
  국내 관습, ±0.05% 기준).
이모지 사전: 📊 정기 시황 · 🔔 종목/마감 · ⚡ 급변 · 🔴 서킷 · 💚 하트비트 · ⚙️ 운영.
등락 강도(E2): ±2% 미만 ▲/▼ · 이상 ⏫/⏬ (변환은 send_kakao_digest._dc_intensity).
필드 순서: 증시 → 환율 → 심리 → 에너지 → 금속 → 곡물 → 운임 → 추세 → 📅 일정.
footer: 항상 신선도 한 줄("시세 HH:MM 기준…" 또는 DELAY_NOTICE).
도달 티어(E1): T1 급변·서킷=@everyone / T2 종목=@종목알림 역할 / T3 정기=무멘션
  (+스레드 멤버 푸시) / T4 운영=무멘션. mention 파라미터: True|"everyone"|"role:이름"|None.
"""
import os
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

# ── 네이버 증권 딥링크(기획 c661d5b0 v3) ──────────────────────────────────
# 2026-08-11 2중 검사(최종 URL 동일성 + 본문 키워드) 통과분만 등록한다.
# 네이버는 미제공 지표를 404 대신 타 페이지로 조용히 리다이렉트하므로(소프트 200 —
# VKOSPI 가 코스피로 302 하던 실측) 후보 추가는 반드시 같은 2중 검사를 먼저 거칠 것.
# 미제공 확정: VKOSPI·MOVE·PutCall·HY·SCFI·구리·밀·옥수수(전 경로 리다이렉트/404).
# 이 dict 의 URL 은 check_links.py 가 주기 점검한다(개편 감지).
_NF = "https://finance.naver.com"
NAVER_LINKS = {
    "KOSPI": _NF + "/sise/sise_index.naver?code=KOSPI",
    "KOSDAQ": _NF + "/sise/sise_index.naver?code=KOSDAQ",
    "SP500": _NF + "/world/sise.naver?symbol=SPI@SPX",
    "NASDAQ": _NF + "/world/sise.naver?symbol=NAS@IXIC",
    "Nikkei": _NF + "/world/sise.naver?symbol=NII@NI225",
    "SOX": _NF + "/world/sise.naver?symbol=NAS@SOX",
    "USDKRW": _NF + "/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW",
    "USDJPY": _NF + "/marketindex/worldExchangeDetail.naver?marketindexCd=FX_USDJPY",
    "Gold": _NF + "/marketindex/worldGoldDetail.naver?marketindexCd=CMDT_GC",
    "Silver": _NF + "/marketindex/worldGoldDetail.naver?marketindexCd=CMDT_SI",
    "WTI": _NF + "/marketindex/worldOilDetail.naver?marketindexCd=OIL_CL",
    "Brent": _NF + "/marketindex/worldOilDetail.naver?marketindexCd=OIL_BRT",
    "NatGas": _NF + "/marketindex/worldOilDetail.naver?marketindexCd=CMDT_NG",
}


def naver_stock_url(code):
    """국내 종목(6자리 코드) 네이버 페이지 — 형식이 아니면 None(깨진 링크 방지)."""
    c = str(code or "").strip()
    return f"{_NF}/item/main.naver?code={c}" if c.isdigit() and len(c) == 6 else None

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


def _post(url, payload, png, filename, extra_headers=None):
    """JSON 또는 (png 있으면) multipart 로 POST. 예외는 호출측에서 처리."""
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
         env=WEBHOOK_ENV, thread_name=None, buttons=None):
    """텍스트(+선택 PNG 첨부) 발송. 성공 True / 미설정·실패 False.

    png 는 bytes 또는 파일 경로(str) — build_slot_chart_png 가 경로를 반환하므로 둘 다 받는다.
    title 을 주면 embed 형식: 제목이 url(대시보드 딥링크)로 하이퍼링크, color=좌측 색띠,
    fields=[(이름, 값, inline)] 2열 그리드(D3), footer=신선도 한 줄(D4), timestamp=수신 시각.
    ⚠ 이미지 클릭은 디스코드 정책상 항상 '확대 보기' — 이동은 제목·버튼이 담당.
    mention(E1): True|"everyone"=@everyone / "role:이름"=역할 멘션 / None·False=무멘션.
    buttons(E3): [(라벨, url 또는 "id:custom_id"), …] — 봇 토큰이 있으면 봇 메시지로
    보내 버튼을 단다(웹훅은 컴포넌트 불가). 봇 경로 실패 시 버튼 없이 웹훅 폴백."""
    hook = _hook(env)
    if not hook:
        return False
    tid = None
    if thread_name:                                   # D10 — 일자 스레드로 묶기(실패 시 본문)
        tid = _thread_id(hook, thread_name)
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
        m = _mention_content(mention, hook)
        if m:
            payload["content"] = m
        plen = len(embed["description"]) + len(embed["title"])
    else:
        m = _mention_content(mention, hook)
        body_text = (m + " " if m else "") + (text or "")
        payload = {"content": body_text[:2000]}
        plen = len(payload["content"])
    if isinstance(png, str):
        try:
            with open(png, "rb") as f:
                png = f.read()
        except OSError as e:
            print(f"::warning title=Discord 차트 읽기 실패::{e} — 이미지 없이 발송")
            png = None

    # 봇 경로(E3) — 버튼이 필요하고 봇 토큰이 있으면 봇 메시지로(웹훅은 컴포넌트 불가).
    tok = _bot_token()
    comps = _components(buttons)
    if comps and tok:
        try:
            _ensure_bot_name(tok)
            cid = tid or _webhook_info(hook).get("channel_id")
            if cid:
                _post(f"{_API}/channels/{cid}/messages", {**payload, "components": comps},
                      png, filename, {"Authorization": f"Bot {tok}"})
                print(f"[discord] 발송 성공 ({plen}자{', 이미지 첨부' if png else ''}"
                      f"{', embed' if title else ''}, 봇+버튼 {len(comps[0]['components'])}개, env={env})")
                return True
        except Exception as e:
            print(f"[discord] 봇 발송 실패({e}) — 버튼 없이 웹훅 폴백")

    # 웹훅 경로(종전) — 버튼이 빠지므로(웹훅은 컴포넌트 불가) 링크 버튼들을 embed
    # 필드 한 줄로 자동 변환해 도달을 보장한다(v3 안전망 — 평시 봇 경로에선 미표시).
    if comps and title:
        try:
            links = [f"[{c['label']}]({c['url']})"
                     for r in comps for c in r["components"] if c.get("url")]
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
