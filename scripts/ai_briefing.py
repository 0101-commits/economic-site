#!/usr/bin/env python3
"""
오늘의 매크로 3줄 요약 생성기 (Task 4.2)

data.json 의 최신 시장 데이터를 읽어 '오늘의 매크로 3줄 요약'을 생성하고
data.json 의 aiBriefing 키에 다시 써넣는다. 프런트엔드(index.html)는
aiBriefing 이 존재할 때만 대시보드 홈 상단 배너에 렌더한다.

생성 우선순위:
  1. Gemini API   — GEMINI_API_KEY 설정 시 (generativelanguage.googleapis.com)
  2. OpenAI API   — OPENAI_API_KEY 설정 시 (api.openai.com)
  3. 규칙 기반    — 키가 없거나 API 실패 시, 데이터에서 직접 3줄 조립 (항상 성공)

GitHub Actions 의 fetch-data 워크플로에서 fetch_data.py 직후 실행된다.
어떤 경우에도 예외로 빌드를 깨지 않는다 (실패 시 exit 0 + 기존 값 유지).

근거(2026-10-14 구조 벤치마크 C3): 요약 전에 근거 목록(지표 · 수급 · 기사 · 일정)을 번호 매겨 만들고 AI 에 함께 준다.
문장 끝 [n] 을 refs 로 읽고, 대조(숫자 · 일정 · 금지 낱말 · refs)에 걸린 문장은 버린다. 남은 문장이 2 미만이면 규칙 요약.
결과는 data.json.aiBriefing(items · sources · dropped · check · day)과 briefs/YYYY-MM-DD.json(그날 회차 runs)에 쓴다.
"""

import email.utils
import html
import json
import math
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests

from check_releases import release_due      # 발표 시각 판정 한 곳(알림 · 수집기 백필과 같은 함수)

KST = timezone(timedelta(hours=9))
DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data.json")
BRIEFS_KEEP_DAYS = 30               # briefs/YYYY-MM-DD.json 보관 일수 — 그보다 오래된 파일은 지운다

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()


def log(msg):
    print(f"[ai_briefing] {msg}", flush=True)


def _num(v, nd=2):
    """화면 수치 표기 — 자릿수를 고정하고 trailing zero 를 남긴다.

    프런트의 INDICATOR_DECIMALS(js/app1.js)와 같은 규칙이어야 한다. 같은 지표가
    서버 요약과 티커에서 다른 자릿수로 나오면 같은 숫자가 둘로 보인다.
    현재 규칙은 지수·환율·유가·금·금리 2자리, 공포탐욕 0자리다 — 지표별로
    다른 자릿수를 쓰게 되면 그 표와 여기를 같은 커밋에서 함께 고칠 것.
    """
    try:
        return f"{float(v):,.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def _chg(v):
    """등락 표기 — 방향은 ▲▼ 하나가 말하고 숫자는 절댓값만 적는다.

    프런트의 fmtChgText(js/app1.js)와 같은 규칙이어야 한다. 3줄 요약은 서버가
    만든 문장과 클라이언트 재조립이 같은 자리에 들어가므로, 기호 뒤 공백까지
    같아야 새로고침 전후로 표기가 흔들리지 않는다.
    """
    try:
        f = float(v)
        return f"{'▲' if f >= 0 else '▼'} {abs(f):.2f}%"
    except (TypeError, ValueError):
        return "—"


def build_snapshot(d):
    """LLM 프롬프트/규칙 기반 요약에 공통으로 쓰는 시장 스냅샷."""
    idx = d.get("indices") or {}
    fx = d.get("fx") or {}
    com = d.get("commodities") or {}
    ei_us = (d.get("economicIndicators") or {}).get("us") or {}
    sent = d.get("sentiment") or {}
    fg = sent.get("fear_greed") or {}

    # 날짜 · 요일 · 기준일을 함께 준다 — 없을 때 모델이 「내일 발표되는 미국 CPI」(실제 모레 10/14)라고 쓰고,
    # 금요일 S&P 등락을 오늘 것처럼 적었다(2026-10-12 점검).
    now = datetime.now(KST)
    hist = (d.get("history") or {}).get("indices") or {}

    def with_day(key):
        q, h = idx.get(key), hist.get(key)
        last = h[-1].get("date") if isinstance(h, list) and h and isinstance(h[-1], dict) else None
        return dict(q, 기준일=_md_dow(last)) if isinstance(q, dict) and _md_dow(last) else q

    snap = {
        "오늘": now.strftime("%Y-%m-%d") + f"({_DOW[now.weekday()]})",
        "작성시각": now.strftime("%H:%M KST") + " — 장중 등락률은 이 시각 값이다",
        "KOSPI": with_day("KOSPI"),
        "S&P500": with_day("SP500"),
        "NASDAQ": with_day("NASDAQ"),
        "USDKRW": fx.get("USDKRW"),
        "WTI": com.get("WTI"),
        "Gold": com.get("Gold"),
        "VIX": (ei_us.get("vix") or {}).get("value"),
        "미국기준금리": (ei_us.get("ff_rate") or {}).get("value"),
        "FearGreed": fg.get("value"),
        "FearGreedLabel": fg.get("rating") or fg.get("label"),
    }

    # ── 스냅샷 보강 (LLM 품질 개선) — 모든 항목은 '데이터 없으면 생략' 방어 필수.
    #    누락 시 키 자체를 넣지 않아 LLM 이 없는 수치를 지어낼 여지를 줄인다.
    # ① 외국인 순매매 최근 5일 누적 — 수급 방향 신호 (investorTrading.daily)
    try:
        it = d.get("investorTrading") or {}
        daily = [r for r in (it.get("daily") or []) if isinstance(r, dict)]
        vals = [r.get("foreign") for r in daily[-5:]
                if isinstance(r.get("foreign"), (int, float))]
        if vals:
            unit = it.get("unit") or "억원"
            snap["외국인순매매_최근5일누적"] = f"{round(sum(vals), 1):,} {unit} ({len(vals)}일)"
    except Exception as e:  # noqa: BLE001 — 스냅샷 보강 실패가 브리핑을 막으면 안 됨
        log(f"snapshot 외국인 순매매 생략: {e}")

    # ② 한국 기준금리 + 한미 금리차 (economicIndicators.kr.base_rate_kr)
    try:
        ei_kr = (d.get("economicIndicators") or {}).get("kr") or {}
        kr_rate = (ei_kr.get("base_rate_kr") or {}).get("value")
        us_rate = snap.get("미국기준금리")
        if isinstance(kr_rate, (int, float)):
            snap["한국기준금리"] = kr_rate
            if isinstance(us_rate, (int, float)):
                snap["한미기준금리차"] = round(kr_rate - us_rate, 2)
    except Exception as e:  # noqa: BLE001
        log(f"snapshot 한국 기준금리 생략: {e}")

    # ③ HY 스프레드 현재값 + 전주 대비 — 신용 스트레스 신호 (history 는 날짜→값 dict)
    try:
        hy = ei_us.get("hy_spread") or {}
        hy_val = hy.get("value")
        if isinstance(hy_val, (int, float)):
            snap["HY스프레드"] = hy_val
            hist = hy.get("history") or {}
            dates = sorted(k for k, v in hist.items() if isinstance(v, (int, float)))
            if dates:
                last_d = datetime.strptime(dates[-1], "%Y-%m-%d").date()
                target = (last_d - timedelta(days=7)).isoformat()
                prior = [k for k in dates if k <= target]
                if prior:
                    snap["HY스프레드_전주대비"] = round(hy_val - hist[prior[-1]], 2)
    except Exception as e:  # noqa: BLE001
        log(f"snapshot HY 스프레드 생략: {e}")

    # ④ 뉴스 헤드라인 상위 5건 — 카테고리 전체에서 최신순 (news.<카테고리>=[{title,isoDate}])
    try:
        news = d.get("news") or {}
        arts = []
        for v in news.values():
            if not isinstance(v, list):
                continue
            for a in v:
                if isinstance(a, dict) and a.get("title"):
                    arts.append((str(a.get("isoDate") or ""), str(a["title"]).strip()))
        arts.sort(reverse=True)  # isoDate 내림차순 = 최신 우선
        titles, seen = [], set()
        for _, t in arts:
            if t and t not in seen:
                seen.add(t)
                titles.append(t)
            if len(titles) >= 5:
                break
        if titles:
            snap["뉴스헤드라인"] = titles
    except Exception as e:  # noqa: BLE001
        log(f"snapshot 뉴스 헤드라인 생략: {e}")
    # 오늘~모레 ★3 캘린더 이벤트 — 실제 날짜 · 요일 · 시각을 붙인다(「10/14(수) 21:30 미국 CPI (전월비)」).
    # 발표 전인지는 시각으로 가른다(release_due). 종전 `not act` 는 발표 전에 실적 칸이 찬 미국 CPI(10/14 21:30, 수집기가
    # 00시부터 직전 회차 +0.4% 를 넣었다)를 빼서, 요약이 「예정된 주요 지표 없음」이라고 썼다(2026-10-14 F1).
    snap["upcoming"] = [_up_label(e) for e in _calendar_window(d, now) if e.get("stars", 0) >= 3 and not release_due(e, now)][:3]
    return snap


def _calendar_window(d, now, days=2):
    """오늘~days 일 뒤 일정(날짜 · 시각 순). 날짜를 못 읽는 행은 뺀다."""
    out = []
    for e in ((d.get("economicCalendar") or {}).get("events")) or []:
        try:
            ed = datetime.strptime(str(e.get("iso") or "")[:10], "%Y-%m-%d").date()
        except (AttributeError, ValueError):
            continue
        if 0 <= (ed - now.date()).days <= days:
            out.append(e)
    return sorted(out, key=lambda e: (str(e.get("iso"))[:10], _event_hm(e)))


def _event_hm(e):
    """「10.14 21:30」의 시각. 없으면 ""."""
    return str(e.get("dt") or "").partition(" ")[2]


def _up_label(e):
    """일정 한 줄 — 「10/14(수) 21:30 미국 CPI (전월비)」(규칙 요약 셋째 줄 · 근거 대응에 같은 글자를 쓴다)."""
    return " ".join(x for x in (_md_dow(e.get("iso")), _event_hm(e), e.get("name", "")) if x)


_DOW = "월화수목금토일"


def _md_dow(iso):
    """'2026-10-14' → '10/14(수)'. 못 읽으면 None."""
    try:
        day = datetime.strptime(str(iso)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return f"{day.month}/{day.day}({_DOW[day.weekday()]})"


def rule_based_lines(snap):
    """LLM 없이 데이터에서 직접 3줄 요약 조립 — 항상 동작하는 폴백."""
    k, s, n = snap.get("KOSPI") or {}, snap.get("S&P500") or {}, snap.get("NASDAQ") or {}
    line1 = (f"증시 — KOSPI {_num(k.get('price'))} ({_chg(k.get('change'))}), "
             f"S&P500 {_num(s.get('price'))} ({_chg(s.get('change'))}), "
             f"나스닥 {_num(n.get('price'))} ({_chg(n.get('change'))})")

    fxk = snap.get("USDKRW") or {}
    rate = snap.get("미국기준금리")
    vix = snap.get("VIX")
    line2 = (f"환율·금리 — 원/달러 {_num(fxk.get('rate'))}원 ({_chg(fxk.get('change'))}), "
             f"미국 기준금리 {_num(rate)}%" + (f", VIX {_num(vix)}" if vix is not None else ""))

    wti, gold = snap.get("WTI") or {}, snap.get("Gold") or {}
    fg_v, fg_l = snap.get("FearGreed"), snap.get("FearGreedLabel")
    parts3 = [f"원자재·심리 — WTI ${_num(wti.get('price'))} ({_chg(wti.get('change'))}), "
              f"금 ${_num(gold.get('price'))} ({_chg(gold.get('change'))})"]
    if fg_v is not None:
        parts3.append(f"공포탐욕 {_num(fg_v, 0)}({fg_l or '—'})")
    if snap.get("upcoming"):
        parts3.append("주요 일정: " + ", ".join(snap["upcoming"]))
    line3 = ", ".join(parts3)
    return [line1, line2, line3]


def _llm_prompt(snap, sources=()):
    # '1줄=주식/2줄=환율·금리/3줄=원자재' 고정 배분은 폐기 — 매일 같은 틀의 나열이 되어
    # 정보가치가 낮았다. 대신 '이례적 변화 1가지 + 파급 경로 + 앞으로 확인할 일정(날짜와 함께)'을 요구한다.
    # 자료는 번호 붙은 근거 목록 하나다(C3) — 종전 JSON 스냅샷을 함께 주면 목록에 없는 숫자(키 이름 · 보조 칸)를 써서 대조에 걸렸다.
    return (
        "다음은 오늘 한국 개인투자자에게 보여 줄 시장 요약의 근거 목록이다(번호 · 종류 · 내용 · 출처 · 기준 시각). "
        "이 목록만 근거로 '오늘의 매크로 3줄 요약'을 한국어로 작성하라.\n"
        "규칙: 정확히 3줄(한 줄 = 한 문장), 각 줄 90자 이내, 번호/불릿/머리말 없이 본문만. "
        "각 줄 끝에 그 문장이 기댄 근거 번호를 [1][4]처럼 단다 — 번호 없는 문장은 버려진다. "
        "숫자는 근거에 적힌 값만 그대로(반올림만 허용) 쓰고 새로 계산하거나 지어내지 말 것. "
        "'스냅샷'·'데이터셋'·'JSON' 같은 자료 이름을 쓰지 말 것. 매수·매도 권유 금지.\n"
        "날짜: 아래 '오늘'이 기준이다. 일정은 근거에 적힌 날짜 그대로(예: 10/14(수)) 말하고 '내일'·'모레' 같은 "
        "상대 표현을 쓰지 말 것. 지수 등락률은 그 근거의 기준 시각 값이다(오늘이 아니면 그 날짜를 밝힐 것). "
        "근거에 일정이 있으면 '발표 일정이 없다'고 쓰지 말 것.\n"
        "반드시 포함: ① 가장 이례적인 변화 1가지와 그것이 한국 시장에 미치는 파급 경로, "
        "② 앞으로 확인할 일정·지표 1가지(그 날짜와 함께).\n\n"
        f"오늘: {snap.get('오늘')} · 작성 시각 {snap.get('작성시각')}\n"
        + "\n".join(" · ".join(x for x in (f"[{s['n']}] {s['kind']}", s["label"], s.get("src"), s.get("at")) if x)
                    for s in sources)
    )


def _reply_lines(text):
    """모델 응답 → 문장 줄(앞 번호 「1. 」 · 불릿 제거, 빈 줄 제외) 최대 3. 「1.19%」 처럼 숫자로 시작하는 문장은 그대로 둔다."""
    out = [re.sub(r"^\s*(?:\d+[.)]\s+|[-•*]\s*)", "", ln).strip() for ln in text.strip().splitlines()]
    return [ln for ln in out if ln][:3]


# Google 이 모델을 조용히 퇴역시킨다 — gemini-2.0-flash 는 404 다(2026-09-15 실측).
# 이 브리핑이 몇 달째 규칙 폴백으로만 돌던 원인은 죽은 키와 죽은 모델 둘이었다.
# 고정 모델을 먼저 쓰고 404 면 별칭으로 물러선다.
GEMINI_MODELS = ("gemini-3.1-flash-lite", "gemini-flash-lite-latest")


def _gemini_text(key, prompt, gen, timeout):
    """모델 차례대로 부른다 — 일시 오류(시간 초과 · 연결 · 5xx)는 2초 뒤 한 번 더, 그 밖(404 퇴역 · 429 한도 ·
    4xx · 빈 응답)은 곧장 다음 모델. 다 실패하면 마지막 예외를 올린다. 키는 헤더로(URL 에 넣으면 오류 문구에 찍힌다).
    2026-10-12 실측: 한 번만 묻던 때 브리핑 4통 중 3통이 시간 초과 · 503 한 번에 AI 문장 없이 나갔다."""
    err = None
    for model in GEMINI_MODELS:
        for attempt in range(2):
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": key},
                    json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen},
                    timeout=timeout)
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as e:                           # noqa: BLE001
                err = e
                code = getattr(getattr(e, "response", None), "status_code", None)
                transient = isinstance(e, (requests.Timeout, requests.ConnectionError)) or (code or 0) >= 500
                log(f"Gemini {model} 실패({attempt + 1}회): {e}")
                if not transient or attempt:
                    break
                time.sleep(2)
    raise err or RuntimeError("Gemini 모델 없음")


def try_gemini(snap, sources=()):
    """문장 줄(근거 번호 [n] 포함) 또는 None. 몇 줄을 쓸지는 대조(verify_items)가 정한다."""
    if not GEMINI_API_KEY:
        return None
    try:
        text = _gemini_text(GEMINI_API_KEY, _llm_prompt(snap, sources), {"temperature": 0.4, "maxOutputTokens": 600}, 40)
        lines = _reply_lines(text)
        if lines:
            log(f"Gemini 요약 생성 {len(lines)}줄")
            return lines
        log("Gemini 응답이 비었다 — 폴백")
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 다음 생성기로 폴백
        log(f"Gemini 실패: {e}")
    return None


# ── 슬롯 한 문장(2026-09-24 알림 개편 B1) ────────────────────────────────────
# 위 3줄 요약은 fetch-data 가 하루 한 번 만든다. 그 문장을 07·09·12·19·22시 알림이 똑같이
# 실어서, 15시에 쓴 "내일 장중 확인" 이 22시에도 나갔고 본문 숫자(1368원대)와 카드 숫자
# (1,369.2)가 어긋났다. 알림은 발송 직전에 **그 카드의 숫자만** 주고 한 문장을 받는다.
# 실패·검증 탈락은 "" — 호출측이 문장 없이 보낸다(틀린 문장보다 없는 편이 낫다).
SLOT_LINE_MAX = 70
# 발송 시각과 무관하게 참이어야 하는 문장만 받는다 — 상대 시점어는 시각이 지나면 거짓이 된다.
# 권유는 어미로 막는다 — '순매수·순매도'는 수급 사실이라 막으면 안 된다(리뷰 지적).
SLOT_LINE_BANNED = ("내일", "모레", "연휴", "다음 주", "다음주", "이번 주말",
                    "매수하세요", "매도하세요", "매수 추천", "매도 추천", "매수 기회", "사세요", "파세요")


_SLOT_DAY = {"오늘": 0, "어제": -1}     # 내일·모레는 SLOT_LINE_BANNED 가 일정과 무관하게 먼저 막는다
_SLOT_MD = re.compile(r"(?<![\d.])(\d{1,2})\s*(?:월\s*|/)(\d{1,2})\s*일?(?![\d.])")   # 소수 2.5 는 날짜가 아니다
_SLOT_PAST = re.compile(r"발표(?:됐|했|결과)|(?:발표[된한]|나온|공개된)\s")
_SLOT_TERMS = ("CPI", "PPI", "PCE", "GDP", "NFP", "FOMC", "PMI", "ECB", "BOJ", "금통위", "소비자물가", "고용",
               "산업생산", "산업활동", "소매판매", "주택착공")
_SLOT_NOISE = {"미국", "한국", "일본", "유로존", "중국", "영국", "독일", "회의", "결정", "발표", "동향", "지수"}


def _calendar_conflict(s, calendar, now, any_day=False):
    """'오늘/어제/M월 D일 … 발표' 문장이 일정표와 어긋나나 → True. 그 날짜에 그 지표가 없거나, 발표 시각 전후와 시제가 안 맞음.
    any_day=True(홈 브리핑): 한 줄에 날짜가 여럿(「오늘」 · 지수 기준일 + 일정 날짜)일 수 있어, 언급한 날 중 그 지표 일정이
    있는 날이 하나도 없을 때만 어긋남이고 시제는 맞은 날의 일정으로만 본다 — 날마다 따지면 멀쩡한 줄도 버려졌다."""
    from check_releases import release_due, KST
    evs = calendar.get("events") if isinstance(calendar, dict) else calendar
    evs = [e for e in (evs or []) if isinstance(e, dict)]
    now = now or datetime.now(KST)
    now = now if now.tzinfo else now.replace(tzinfo=KST)
    days = [(now + timedelta(days=n)).date() for w, n in _SLOT_DAY.items() if w in s]
    # ponytail: 연도는 now 의 해로 본다 — 연말·연초에 걸친 'M월 D일' 은 대조 못 한다
    days += [d for d in (_try_date(now.year, m, dd) for m, dd in _SLOT_MD.findall(s)) if d]
    if "발표" not in s or not days:
        return False
    words = lambda e: [t for t in (re.sub(r"(동향|결정)$", "", w) for w in re.split(r"[\s()·/]+", str(e.get("name") or "")))
                       if len(t) >= 2 and t not in _SLOT_NOISE]
    # 문장이 가리키는 지표 = 고정 어휘 + 일정표 이름의 낱말 중 문장에 든 것. 일정표에 없는 지표(오늘 PPI)도 잡으려고 어휘를 따로 둔다.
    hit = [t for t in set(_SLOT_TERMS) | {t for e in evs for t in words(e)} if t.lower() in s.lower()]
    named = lambda e: any(t.lower() in str(e.get("name") or "").lower() for t in hit)
    mentioned = bool(hit)
    matched = []
    for d in days:
        today = [e for e in evs if str(e.get("iso") or "")[:10] == d.isoformat()]
        pool = [e for e in today if named(e)] if mentioned else today
        if not pool and not any_day:
            return True                                      # 그 날짜에 그 지표(또는 어떤 발표도) 없다
        if pool:
            matched.append(pool)
    if not matched:
        return True                                          # 언급한 어느 날에도 그 지표 일정이 없다
    for pool in matched:
        due = [release_due(e, now) for e in pool]
        if (bool(_SLOT_PAST.search(s)) and not any(due)) or (not _SLOT_PAST.search(s) and all(due)):
            return True                                      # 안 나온 발표를 '나왔다'·이미 나온 발표를 '앞두고'
    return False


def _try_date(y, m, d):
    try:
        return datetime(y, int(m), int(d)).date()
    except ValueError:
        return None


def brief_lines_ok(lines, calendar=None, now=None):
    """홈 브리핑 3줄 검증 — 알림 한 문장(slot_line_ok)과 같은 금지어(상대 시점어 · 권유)와 일정표 대조. 길이는 보지 않는다
    (모델이 90자 지시를 자주 넘는데 그것만으로 버리면 늘 규칙 요약이 된다). 프롬프트로 「내일 · 모레」를 막아도 모델이 어기면
    거짓 날짜가 화면에 남았다(2026-10-12 「내일 발표되는 미국 CPI」, 실제 10/14)."""
    return bool(lines) and all(
        isinstance(s, str) and s.strip() and not any(w in s for w in SLOT_LINE_BANNED)
        and not (calendar is not None and _calendar_conflict(s, calendar, now, any_day=True)) for s in lines)


def slot_line_ok(s, calendar=None, now=None):
    """알림 한 문장 검증 — 길이·상대 시점어·투자 권유·여러 줄. calendar(economicCalendar 블록 또는 events 목록)를
    주면 '오늘 발표'·'M월 D일 발표' 문장을 일정표와 대조해 어긋나면 버린다(이미 지난 발표 포함)."""
    s = (s or "").strip()
    return (8 <= len(s) <= SLOT_LINE_MAX and "\n" not in s
            and not any(w in s for w in SLOT_LINE_BANNED)
            and not (calendar is not None and _calendar_conflict(s, calendar, now)))


def slot_line(slot_name, facts, timeout=15, calendar=None):
    """카드 숫자(facts, 한 줄 문자열) → 한 문장 또는 "". 키가 없으면 호출하지 않는다."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key or not facts:
        return ""
    prompt = ("다음은 한국 개인투자자에게 보내는 '" + str(slot_name) + "' 시장 알림 카드의 숫자다.\n"
              + str(facts) + "\n"
              "이 숫자만 근거로 지금 가장 중요한 흐름 하나를 한국어 한 문장(" + str(SLOT_LINE_MAX - 10)
              + "자 이내)으로 써라. 규칙: 주어진 숫자 외의 수치 금지, '내일·연휴·다음 주' 같은 시점 표현 금지, "
              "매수·매도 권유 금지, 머리말·따옴표 없이 문장만.")
    try:
        text = _gemini_text(key, prompt, {"temperature": 0.3, "maxOutputTokens": 120}, timeout).strip().strip('"“”')
    except Exception as e:                                   # noqa: BLE001
        log(f"슬롯 문장 실패: {e}")
        return ""
    return text if slot_line_ok(text, calendar) else ""


def try_openai(snap, sources=()):
    if not OPENAI_API_KEY:
        return None
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": "gpt-4o-mini",
                  "messages": [{"role": "user", "content": _llm_prompt(snap, sources)}],
                  "temperature": 0.4, "max_tokens": 600},
            timeout=40,
        )
        r.raise_for_status()
        lines = _reply_lines(r.json()["choices"][0]["message"]["content"])
        if lines:
            log(f"OpenAI 요약 생성 {len(lines)}줄")
            return lines
        log("OpenAI 응답이 비었다 — 폴백")
    except Exception as e:  # noqa: BLE001
        log(f"OpenAI 실패: {e}")
    return None


# ── 근거 목록 · 대조(C3, 2026-10-14) ─────────────────────────────────────────
# 근거는 요약 전에 data.json 에서 만든다 — 지표 값 · 수급(연속 일수는 investorTrading 행으로 직접 센다, 기사 제목의 「7일째」가
# 아니라) · 기사 제목(출처 · 주소 · 시각) · 오늘~모레 일정. 화면은 문장 끝 근거 번호와 이 목록을 그린다(home.brief).
BRIEF_BANNED = SLOT_LINE_BANNED + ("스냅샷", "묶음", "데이터셋", "JSON", "json")
BRIEF_NEWS = 5                      # 기사 근거 수(최신순)
BRIEF_NEWS_TOPICS = ("주식", "외환", "채권", "미국CPI", "원자재", "원유", "한국은행", "한국수출")   # data.json.news 주제 중 시장 기사
BRIEF_SCHED = 6                     # 일정 근거 상한(★2 이상, 오늘~모레)
_FG_KO = {"extreme fear": "극단적 공포", "fear": "공포", "neutral": "중립", "greed": "탐욕", "extreme greed": "극단적 탐욕"}


def _isnum(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _arrow(v):
    """근거 칸 등락 — 「▲1.19%」(방향은 기호, 숫자는 절댓값 · 규칙 요약과 같은 두 자리)."""
    return f"{'▲' if v >= 0 else '▼'}{abs(v):.2f}%"


def _signed(v, unit=""):
    """근거 칸 금액 — 「+8,005억원」 · 「−11,715억원」."""
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):,.0f}{unit}"


def _parse_dt(s):
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=KST)


def _when(t, now, with_time=False):
    """기준 시각 — 오늘이면 「14:35」, 아니면 「10/13(화)」(with_time 이면 「10/13(화) 16:52」)."""
    t = t.astimezone(KST)
    if t.date() == now.date():
        return t.strftime("%H:%M")
    day = _md_dow(t.date().isoformat())
    return f"{day} {t.strftime('%H:%M')}" if with_time else day


def _streak(rows, who):
    """끝 행부터 같은 부호가 이어진 거래일 수와 방향(+1 순매수 · −1 순매도). 값이 없거나 0 이면 거기서 끊는다."""
    n, sign = 0, 0
    for r in reversed(rows):
        v = r.get(who)
        s = ((v > 0) - (v < 0)) if _isnum(v) else 0
        if not s or (sign and s != sign):
            break
        sign, n = s, n + 1
    return n, sign


def build_sources(d, snap, now=None):
    """근거 목록 — [{n, kind(지표 · 수급 · 기사 · 일정), label, at?, src?, url?}]. 밑줄 칸(_key · _iso · _up)은 안에서만 쓴다.
    값이 없는 항목은 싣지 않는다(지어내지 않는다)."""
    now = now or datetime.now(KST)
    today = now.date().isoformat()
    out = []

    def add(kind, label, key=None, **kw):
        out.append({"n": len(out) + 1, "kind": kind, "label": label,
                    **{k: v for k, v in kw.items() if v is not None}, **({"_key": key} if key else {})})

    upd = _parse_dt(d.get("lastUpdated"))
    upd_at = _when(upd, now) if upd else None
    hist = (d.get("history") or {}).get("indices") or {}
    idx = d.get("indices") or {}
    for key, name in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥"), ("SP500", "S&P500"), ("NASDAQ", "나스닥")):
        q, h = idx.get(key) or {}, hist.get(key)
        if not _isnum(q.get("price")):
            continue
        last = h[-1].get("date") if isinstance(h, list) and h and isinstance(h[-1], dict) else None
        add("지표", f"{name} {_num(q['price'])}" + (f" {_arrow(q['change'])}" if _isnum(q.get("change")) else ""),
            key, at=_md_dow(last) if last and last != today else upd_at)
    for key, name, q, pre, post in (("USDKRW", "원/달러", (d.get("fx") or {}).get("USDKRW") or {}, "", "원"),
                                    ("WTI", "WTI", (d.get("commodities") or {}).get("WTI") or {}, "$", ""),
                                    ("Gold", "금", (d.get("commodities") or {}).get("Gold") or {}, "$", "")):
        v = q.get("rate") if key == "USDKRW" else q.get("price")
        if _isnum(v):
            add("지표", f"{name} {pre}{_num(v)}{post}" + (f" {_arrow(q['change'])}" if _isnum(q.get("change")) else ""),
                key, at=upd_at)
    ei = d.get("economicIndicators") or {}
    vix = ((ei.get("us") or {}).get("vix") or {})
    if _isnum(vix.get("value")):
        add("지표", f"VIX {_num(vix['value'])}", "VIX", at=_md_dow(vix.get("period")))
    if _isnum(snap.get("미국기준금리")):
        add("지표", f"미국 기준금리 {_num(snap['미국기준금리'])}%", "미국기준금리")
    if _isnum(snap.get("한국기준금리")):
        gap = snap.get("한미기준금리차")
        add("지표", f"한국 기준금리 {_num(snap['한국기준금리'])}%" + (f" · 한미 차 {_signed_pp(gap)}" if _isnum(gap) else ""),
            "한국기준금리")
    if _isnum(snap.get("HY스프레드")):
        wk = snap.get("HY스프레드_전주대비")
        add("지표", f"미국 하이일드 스프레드 {_num(snap['HY스프레드'])}%p" + (f" · 1주 전보다 {_signed_pp(wk)}" if _isnum(wk) else ""),
            "HY", at=_md_dow(((ei.get("us") or {}).get("hy_spread") or {}).get("period")))
    fg = (d.get("sentiment") or {}).get("fear_greed") or {}
    if _isnum(fg.get("value")):
        rating = fg.get("rating") or fg.get("label")
        add("지표", f"공포·탐욕 지수 {fg['value']}" + (f" ({_FG_KO.get(str(rating).lower(), rating)})" if rating else ""),
            "FearGreed", at=upd_at if fg.get("as_of") == today else _md_dow(fg.get("as_of")))

    # 수급 — 오늘(마지막 거래일) 값 · 연속 일수 · (외국인) 5일 누적. 시각은 포털 수집 시각(네이버 행) 또는 수집 시각.
    it = d.get("investorTrading") or {}
    rows = [r for r in (it.get("daily") or []) if isinstance(r, dict) and r.get("date")]
    if rows:
        last = rows[-1]
        t = _parse_dt(it.get("portalFetchedAt") if last.get("src") == "naver" else it.get("lastFetched"))
        at = (_when(t, now) if t and t.date() == now.date() else None) if last["date"] == today else _md_dow(last["date"])
        unit = it.get("unit") or "억원"
        for who, name in (("foreign", "외국인"), ("inst", "기관")):
            v = last.get(who)
            if not _isnum(v):
                continue
            n, sign = _streak(rows, who)
            five = [r.get(who) for r in rows[-5:]]
            label = f"{name} {_signed(v, unit)}" + (f" · {n}일 연속 순{'매수' if sign > 0 else '매도'}" if n >= 2 else "")
            if who == "foreign" and len(five) == 5 and all(_isnum(x) for x in five):
                label += f" · 5일 누적 {_signed(sum(five), unit)}"
            add("수급", label, who, at=at)

    # 기사 — 시장 주제(BRIEF_NEWS_TOPICS) 최신순 BRIEF_NEWS 건(같은 주소 · 같은 제목은 한 번). 출처 = 주소의 호스트.
    #   전 주제에서 고르면 미술관 · 건설 기사가 근거 칸을 채웠다(2026-10-14 17:08 자료 5건 중 4건). 시장 주제가 비면 전 주제.
    news = d.get("news") or {}
    picked = [news.get(t) for t in BRIEF_NEWS_TOPICS if isinstance(news.get(t), list) and news.get(t)]
    arts, seen = [], set()
    for items in picked or list(news.values()):
        for a in items if isinstance(items, list) else []:
            if not isinstance(a, dict):
                continue
            title = re.sub(r"\s+", " ", html.unescape(str(a.get("title") or ""))).strip()
            url = a.get("url") if isinstance(a.get("url"), str) else ""
            if not title or not re.match(r"https?://", url) or url in seen or title in seen:
                continue
            seen.update((url, title))
            try:
                t = email.utils.parsedate_to_datetime(a.get("pubDate"))
            except (TypeError, ValueError):
                t = None
            t = (t if t.tzinfo else t.replace(tzinfo=timezone.utc)) if t else None
            arts.append((t.timestamp() if t else 0, title, url, t))
    for _, title, url, t in sorted(arts, key=lambda x: -x[0])[:BRIEF_NEWS]:
        add("기사", title, src=(urllib.parse.urlsplit(url).hostname or "").removeprefix("www.") or None, url=url,
            at=_when(t, now, with_time=True) if t else None)

    # 일정 — 오늘~모레 ★2 이상. 발표 시각이 지났고 실적이 있으면 그 값을 붙인다(release_due — 시각으로 판정).
    for e in [e for e in _calendar_window(d, now) if (e.get("stars") or 0) >= 2][:BRIEF_SCHED]:
        due = release_due(e, now)
        label = " · ".join(x for x in (e.get("name"), " ".join(x for x in (_md_dow(e.get("iso")), _event_hm(e)) if x),
                                       "★" * int(e.get("stars") or 0), f"발표 {e['act']}" if due and e.get("act") else None) if x)
        src = {"kind": "일정", "label": label, "_iso": str(e.get("iso"))[:10]}
        if (e.get("stars") or 0) >= 3 and not due:
            src["_up"] = _up_label(e)
        out.append({"n": len(out) + 1, **src})
    return out


def _signed_pp(v):
    """%p 차 — 「−0.75%p」 · 「+0.05%p」."""
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.2f}%p"


_REFS = re.compile(r"\s*\[(\d{1,2}(?:\s*[,，]\s*\d{1,2})*)\]")


def parse_items(lines, n_sources):
    """「…줄었습니다 [1][3]」 → {text, refs}. 없는 번호는 버리고 같은 번호는 한 번만."""
    items = []
    for ln in lines:
        refs = []
        for grp in _REFS.findall(ln):
            for x in re.split(r"\s*[,，]\s*", grp):
                if 1 <= int(x) <= n_sources and int(x) not in refs:
                    refs.append(int(x))
        text = re.sub(r"\s+([.,!?])", r"\1", _REFS.sub("", ln)).strip()
        items.append({"text": text, "refs": refs})
    return items


# 숫자 대조 — 날짜 · 시각 · 순서 숫자(「10/14」 「21:30」 「3분기」 「1위」)와 이름 속 숫자(「S&P500」 「코스피200」)는 값이 아니라 뺀다.
_NUM_NAMES = re.compile(r"S&P\s*500|(?:코스피|코스닥|나스닥|KOSPI|KOSDAQ|NASDAQ)\d+")    # 붙은 숫자만(「코스피 6,008」은 값)
_NOT_VALUE = re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}/\d{1,2}(?:\s*\([월화수목금토일]\))?|\d{1,2}:\d{2}"
                        r"|\d{1,2}일\s*\([월화수목금토일]\)"
                        r"|(?<![\d.,])\d+(?:년|월|분기|시|분|초|번째|번|차|가지|줄|위(?!안))")
_NUM_TOKEN = r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?"
_BIG = re.compile(r"(?<![\d.,])(\d+)(?:\.(\d+))?\s*조(?:\s*(\d{1,3}(?:,\d{3})+|\d+)\s*억)?|(?<![\d.,])(\d+)\s*천\s*억")
_RANGE = re.compile(r"(?<![A-Za-z&\d.,])" + _NUM_TOKEN + r"\s*(?:원|달러|포인트|%p?|bp)?\s*(대(?!비|규모|형|폭|량)|선(?!물|거|박|택))")
_PLAIN = re.compile(r"(?<![A-Za-z&\d.,])" + _NUM_TOKEN)


def _clean_nums(s):
    return _NOT_VALUE.sub(" ", _NUM_NAMES.sub(" ", s))


def _tokens(s):
    """문장 숫자 → [(값, 소수 자릿수, 배율, 꼴)]. 꼴 = eq(반올림 · 버림 일치) · range(「1,330원대」) · level(「6000선」 ±5%).
    억 단위 근거와 맞추려고 「1조 1,715억」 = 11715 · 「1.2조」 = 1.2 × 10000 · 「4천억」 = 4 × 1000 으로 센다."""
    s, out = _clean_nums(s), []

    def big(m):
        if m.group(4):
            out.append((float(m.group(4)), 0, 1000.0, "eq"))
        elif m.group(3):
            out.append((float(m.group(1)) * 10000 + float(m.group(3).replace(",", "")), 0, 1.0, "eq"))
        else:
            out.append((float(m.group(1) + "." + (m.group(2) or "0")), len(m.group(2) or ""), 10000.0, "eq"))
        return " "

    def rng(m):
        out.append((float(m.group(1).replace(",", "") + "." + (m.group(2) or "0")), len(m.group(2) or ""), 1.0,
                    "range" if m.group(3).startswith("대") else "level"))
        return " "

    s = _RANGE.sub(rng, _BIG.sub(big, s))
    out += [(float(m.group(1).replace(",", "") + "." + (m.group(2) or "0")), len(m.group(2) or ""), 1.0, "eq")
            for m in _PLAIN.finditer(s)]
    return out


def _pool(labels):
    """근거 칸 글자 속 숫자(절댓값)."""
    return [float(m.group(1).replace(",", "") + "." + (m.group(2) or "0"))
            for lb in labels for m in _PLAIN.finditer(_clean_nums(lb))]


def _num_ok(tok, y):
    x, d, mult, kind = tok
    v = abs(y) / mult
    if kind == "level":
        return x > 0 and abs(v - x) <= 0.05 * x
    if kind == "range":
        step = 10.0 ** -d if d else 10.0 ** (len(str(int(x))) - len(str(int(x)).rstrip("0"))) if x else 1.0
        return x <= v < x + step
    eps = 10.0 ** -(d + 6)
    return abs(round(v, d) - x) < eps or abs(math.floor(v * 10 ** d + eps) / 10 ** d - x) < eps


# 「발표 없」류 — 「예정된 주요 지표나 이벤트는 없으나」(2026-10-14 F1 문장)
_NO_RELEASE = re.compile(r"(?:일정|발표|지표|이벤트)[^.,。]{0,12}(?:없|부재)")


def check_item(item, by_n, calendar=None, now=None, today_sched=False):
    """한 문장 대조 → (통과, 걸린 이유, 통과한 숫자 수, 일정 근거 수). 이유는 로그용."""
    s, refs = item["text"], item["refs"]
    if not refs:
        return False, "근거 번호 없음", 0, 0
    if any(w in s for w in BRIEF_BANNED):
        return False, "금지 낱말", 0, 0
    if calendar is not None and _calendar_conflict(s, calendar, now, any_day=True):
        return False, "일정표와 어긋남", 0, 0
    if today_sched and _NO_RELEASE.search(s):
        return False, "오늘 일정이 있는데 「발표 없음」", 0, 0
    cited = [by_n[n] for n in refs if n in by_n]
    pool = _pool(c["label"] for c in cited)
    toks = _tokens(s)
    bad = [t for t in toks if not any(_num_ok(t, y) for y in pool)]
    if bad:
        return False, "근거에 없는 숫자 %s" % [t[0] for t in bad], 0, 0
    return True, None, len(toks), sum(1 for c in cited if c["kind"] == "일정")


def verify_items(lines, sources, calendar=None, now=None):
    """AI 줄 → (남은 items, 버린 수, 통과 숫자 수, 일정 수). 하나라도 걸린 문장은 통째로 버린다."""
    by_n = {s["n"]: s for s in sources}
    today = (now or datetime.now(KST)).date().isoformat()
    today_sched = any(s["kind"] == "일정" and s.get("_iso") == today for s in sources)
    kept, dropped, nums, sched = [], 0, 0, 0
    for it in parse_items(lines, len(sources)):
        ok, why, n, k = check_item(it, by_n, calendar, now, today_sched)
        if not ok:
            dropped += 1
            log(f"대조에서 버림({why}): {it['text']}")
            continue
        kept.append(it)
        nums, sched = nums + n, sched + k
    return kept, dropped, nums, sched


def rule_items(snap, sources):
    """규칙 요약 3줄 + 그 줄이 쓴 근거 번호(지표 키 · 일정 글자로 찾는다). 대조 수는 같은 숫자 대조로 센다."""
    key = {s["_key"]: s["n"] for s in sources if s.get("_key")}
    up = set(snap.get("upcoming") or [])
    groups = (("KOSPI", "SP500", "NASDAQ"), ("USDKRW", "미국기준금리", "VIX"), ("WTI", "Gold", "FearGreed"))
    items = []
    for i, (ln, ks) in enumerate(zip(rule_based_lines(snap), groups)):
        refs = [key[k] for k in ks if k in key] + ([s["n"] for s in sources if s.get("_up") in up] if i == 2 else [])
        items.append({"text": ln, "refs": refs})
    by_n = {s["n"]: s for s in sources}
    nums = sum(sum(1 for t in _tokens(it["text"]) if any(_num_ok(t, y) for y in _pool(by_n[n]["label"] for n in it["refs"])))
               for it in items)
    sched = sum(1 for it in items for n in it["refs"] if by_n[n]["kind"] == "일정")
    return items, nums, sched


def save_brief_run(brief, now, briefs_dir):
    """briefs/YYYY-MM-DD.json 에 이번 회차를 더한다(같은 at 이면 바꿔 끼움) · BRIEFS_KEEP_DAYS 일 지난 파일은 지운다.
    화면이 회차를 넘겨 본다 — 파일 = {date, runs:[{at, source, day, lines, items, sources, dropped, check}]}."""
    os.makedirs(briefs_dir, exist_ok=True)
    day = now.strftime("%Y-%m-%d")
    path = os.path.join(briefs_dir, day + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        doc = None
    if not isinstance(doc, dict) or doc.get("date") != day or not isinstance(doc.get("runs"), list):
        doc = {"date": day, "runs": []}
    run = {"at": now.strftime("%H:%M"), **{k: brief.get(k) for k in ("source", "day", "lines", "items", "sources", "dropped", "check")}}
    same = [i for i, r in enumerate(doc["runs"]) if isinstance(r, dict) and r.get("at") == run["at"]]
    if same:
        doc["runs"][same[0]] = run
    else:
        doc["runs"].append(run)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    cut = now.date() - timedelta(days=BRIEFS_KEEP_DAYS)
    for name in os.listdir(briefs_dir):
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.json", name)
        if m and datetime.strptime(m.group(1), "%Y-%m-%d").date() < cut:
            os.remove(os.path.join(briefs_dir, name))


def main():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:  # noqa: BLE001
        log(f"data.json 로드 실패 — 건너뜀: {e}")
        return 0

    now = datetime.now(KST)
    snap = build_snapshot(d)
    sources = build_sources(d, snap, now)
    source, items, dropped, nums, sched = "rule", None, 0, 0, 0
    cal = d.get("economicCalendar")
    for name, gen in (("gemini", try_gemini), ("openai", try_openai)):
        got = gen(snap, sources)
        if not got:
            continue
        # 문장 단위 대조(C3) — 숫자 · 일정 · 금지 낱말 · 근거 번호. 걸린 문장만 버리고 2문장 이상 남으면 싣는다.
        kept, dropped, nums, sched = verify_items(got, sources, cal, now)
        if len(kept) >= 2:
            source, items = name, kept
            break
        log(f"{name} 요약이 대조 뒤 {len(kept)}문장 — 다음 생성기로")
    if not items:
        items, nums, sched = rule_items(snap, sources)
        log("규칙 기반 요약 사용 (LLM 키 미설정 · 실패 · 대조 탈락)")

    by_n = {s["n"]: s for s in sources}
    used = sorted({n for it in items for n in it["refs"]})
    d["aiBriefing"] = {
        "date": now.strftime("%Y-%m-%d"),
        "generatedAt": now.strftime("%Y-%m-%d %H:%M KST"),
        "lines": [it["text"] for it in items],            # 옛 화면 · 알림 호환(글자만)
        "source": source,
        "day": now.strftime("%Y-%m-%d"),
        "items": items,
        "sources": [{k: v for k, v in by_n[n].items() if not k.startswith("_")} for n in used],   # 문장이 단 근거만
        "dropped": dropped,
        "check": {"numbers": nums, "schedule": sched},
    }
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            # data.json 기록자 공통 압축 형식 — 하나라도 indent 로 쓰면 1.5MB 목표가 깨진다(test_history_split 이 고정)
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        log(f"aiBriefing 갱신 완료 (source={source}, 버린 문장 {dropped})")
    except Exception as e:  # noqa: BLE001
        log(f"data.json 저장 실패: {e}")
        return 0
    try:
        save_brief_run(d["aiBriefing"], now, os.path.join(os.path.dirname(DATA_FILE), "briefs"))
    except Exception as e:  # noqa: BLE001 — 회차 파일 실패가 요약을 막지 않는다
        log(f"briefs 저장 실패: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
