#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""종목 「왜 움직였나」 — data.json.stockNews · stockReasons (구조 벤치마크 과제 2, 계약 C4).

대상 = 관심목록(ETF 제외) + 거래대금 상위 20(ETF 제외), 최대 30종목 — fetch_data._corp_targets(배당·실적 일정)와 같은 규칙.
종목마다
  ① 오늘 기사 — 네이버 뉴스 검색(「이름 주가」, sort=date, 10건) 중 제목에 종목 이름이 든 것, 24시간 안 → stockNews
  ② 재료(있을 때만) — 지수 동행(같은 방향 · 종목 등락과 그 시장 지수 등락 차이 1%p 안) · 최근 10일 공시(corpEvents)
     · 52주 신고가/신저가(rankingsKr.high52/low52) · 기사 제목. 재료가 하나도 없으면 그 종목은 싣지 않는다.
  ③ 규칙이 재료를 골라 문장을 만들고(「코스피 하락과 함께 내렸습니다 · 10/8 잠정실적 공시 엿새 뒤」) Gemini 는 다듬기만 한다
     (입력 = 규칙 문장 + 재료 글자, 60자 안 한 문장, 출력 숫자 ⊆ 입력 숫자, 금지 낱말). 걸리거나 실패하면 규칙 문장 그대로.
실행 조건: 장 서는 날(marketCalendarKr) KST 08~20시 런. `--force` 면 시각 · 휴장과 무관하게 돈다.
키: NAVER_CLIENT_ID/SECRET 없으면 기사 단계만, GEMINI_API_KEY 없으면 다듬기만 건너뛴다. 어떤 실패에도 exit 0.
호출: 런마다 기사 검색 ≤30 + Gemini ≤30(규칙 문장 · 재료가 직전 런과 같으면 직전 문장을 그대로 써 부르지 않는다).
그 밖의 런(밤 · 휴장일)은 fetch_data 가 직전 두 블록을 그대로 잇고, 묶음(home.reasons)은 오늘 쓴 것만 싣는다.

사용: python scripts/stock_reasons.py [--force]
"""
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_briefing import _gemini_text  # noqa: E402  Gemini 호출(모델 차례 · 일시 오류 재시도)의 단일 창구

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(ROOT, "data.json")
CFG_FILE = os.path.join(ROOT, "alerts_config.json")
KST = timezone(timedelta(hours=9))

MAX_TARGETS, TOP_AMOUNT = 30, 20
RUN_HOURS = range(8, 21)                 # 08시 런 ~ 20시 런(KST) — 장 마감 뒤 기사도 잡는다
NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
NEWS_DISPLAY, NEWS_KEEP, NEWS_HOURS = 10, 5, 24
NEWS_GAP = 0.2                           # 기사 검색 호출 사이 간격(초) — 네이버 검색 초당 10회 한도 아래
COMOVE_PP = 1.0                          # 지수 동행 — 종목 등락과 지수 등락 차이(%p) 상한
DISCLOSURE_DAYS = 10                     # 공시가 이만큼 안에 있으면 재료
HILO_DAYS = 4                            # 52주 목록 기준일(KRX 전일 확정치)이 이만큼 안이면 재료 — 주말 · 하루 휴장을 넘긴다
ARTICLE_REFS = 2                         # 근거 칩으로 싣는 기사 수
LINE_MAX = 60
GEN = {"temperature": 0.2, "maxOutputTokens": 120}
GEMINI_TIMEOUT = 15
GEMINI_FAIL_STOP = 2                     # 연속 실패가 이만큼이면 이 런의 나머지는 규칙 문장(시간 초과 30번을 기다리지 않게)
# 다듬은 문장에 나오면 버린다 — 묶음 · 수집 용어, 상대 시점어(쓴 시각이 지나면 거짓이 된다), 권유 어미
BANNED = ("스냅샷", "묶음", "데이터", "JSON", "내일", "모레", "다음 주", "다음주", "추천", "하세요", "사세요", "파세요")
NEW_ONLY = ("매수", "매도")              # 재료 글자(기사 제목)에 있을 때만 쓸 수 있다 — 없으면 지어낸 수급이거나 권유다
MARKET_INDEX = {"KOSPI": ("KOSPI", "코스피"), "KOSDAQ": ("KOSDAQ", "코스닥")}
DAY_WORD = ("당일", "하루", "이틀", "사흘", "나흘", "닷새", "엿새", "이레", "여드레", "아흐레", "열흘")
_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def log(msg):
    print(f"[stock_reasons] {msg}", flush=True)


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _day(s):
    """'2026-10-14' · '2026-10-14T14:22:00+09:00' → '2026-10-14'. 못 읽으면 None."""
    m = re.match(r"^\d{4}-\d{2}-\d{2}", str(s or ""))
    return m.group(0) if m else None


def _md(day):
    """'2026-10-08' → '10/8'."""
    return "%d/%d" % (int(day[5:7]), int(day[8:10]))


def _gap(later, earlier):
    return (date.fromisoformat(later) - date.fromisoformat(earlier)).days


# ── 대상 ────────────────────────────────────────────────────────────────────
def targets(data, cfg_path=CFG_FILE):
    """(종목코드, 이름) — 관심목록 먼저, 다음 거래대금 상위 20. ETF 는 뺀다. fetch_data._corp_targets 와 같은 규칙이다
    (그 함수를 import 하면 수집기 의존성이 다 딸려 온다 — 둘이 같은지는 test_stock_reasons 가 본다)."""
    try:
        with open(cfg_path, encoding="utf-8") as f:
            items = ((json.load(f).get("tracking") or {}).get("items")) or []
    except (OSError, ValueError):
        items = []
    cands = [(str(it.get("symbol") or ""), it.get("name")) for it in items
             if it.get("market") == "KR" and it.get("secType") != "etf"]
    ta = ((data.get("rankingsKr") or {}).get("tradingAmount") or [])[:TOP_AMOUNT]
    cands += [(str(r.get("code") or ""), r.get("name")) for r in ta if r.get("type") != "ETF"]
    out = {}
    for code, name in cands:
        if re.fullmatch(r"[0-9A-Z]{6}", code) and code not in out:
            out[code] = name or code
    return list(out.items())[:MAX_TARGETS]


def _rows(data):
    """종목코드 → 장 행(chg · market · as_of). 거래대금 → 토스 거래대금 → 등락 상위 순으로 먼저 나온 것.
    KRX 순위(시총 · 52주)는 전일 확정치라 등락의 원천으로 쓰지 않는다."""
    rk, sm = data.get("rankingsKr") or {}, data.get("stockMovers") or {}
    out = {}
    for rows in [rk.get("tradingAmount"), rk.get("tossAmount")] + [sm.get(k) for k in
                                                                    ("kospiGainers", "kospiLosers", "kosdaqGainers", "kosdaqLosers")]:
        for r in rows or []:
            if isinstance(r, dict) and r.get("code"):
                out.setdefault(str(r["code"]), r)
    return out


def _known_names(data, tg):
    """제목 대조용 종목 이름 전부(대상 + 순위 · 등락 목록) — 「SK」 기사 찾기에서 「SK하이닉스」 를 지우려고 쓴다."""
    names = {n for _, n in tg}
    rk, sm = data.get("rankingsKr") or {}, data.get("stockMovers") or {}
    lists = [rk.get("tradingAmount"), rk.get("tossAmount")] + list(sm.values())
    for k in ("marketCap", "volume", "high52", "low52"):
        node = rk.get(k) or {}
        lists += [node.get("kospi"), node.get("kosdaq")]
    for rows in lists:
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and r.get("name"):
                names.add(str(r["name"]))
    return names


# ── 기사 ────────────────────────────────────────────────────────────────────
def clean_title(s):
    """검색 API 제목 — <b> 태그 · HTML 엔티티를 풀고 공백을 한 칸으로."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", str(s or "")))).strip()


def title_has(title, name, others=()):
    """제목에 종목 이름이 있나 — 이 이름을 품은 더 긴 종목 이름(「SK」 ⊂ 「SK하이닉스」, 「삼성전자」 ⊂ 「삼성전자우」)은
    지우고 본다. 남의 기사를 이 종목 근거로 싣지 않게."""
    if not name:
        return False
    t = title
    for o in sorted((o for o in others if o and len(o) > len(name) and name in o), key=len, reverse=True):
        t = t.replace(o, " ")
    return name in t


def pick_articles(raw, name, others, now):
    """검색 응답 항목 → [{title, url, src, at}] 최신순 NEWS_KEEP 건. 제목에 이름이 든 것 · 24시간 안 · http(s) 주소만."""
    out, seen = [], set()
    for it in raw or []:
        if not isinstance(it, dict):
            continue
        title = clean_title(it.get("title"))
        url = str(it.get("originallink") or it.get("link") or "").strip()
        try:
            t = email.utils.parsedate_to_datetime(it.get("pubDate"))
        except (TypeError, ValueError):
            continue
        if not t.tzinfo:
            t = t.replace(tzinfo=KST)
        if not (now - timedelta(hours=NEWS_HOURS) <= t <= now + timedelta(minutes=10)):
            continue
        parts = urllib.parse.urlsplit(url)
        if parts.scheme.lower() not in ("http", "https") or not title_has(title, name, others):
            continue
        if url in seen or title in seen:
            continue
        seen.update((url, title))
        out.append({"title": title, "url": url, "src": (parts.hostname or "").removeprefix("www.") or None,
                    "at": t.astimezone(KST).isoformat(timespec="seconds")})
    out.sort(key=lambda a: a["at"], reverse=True)
    return out[:NEWS_KEEP]


def naver_search(cid, secret):
    """이름 → 검색 응답 items. 실패는 예외로 올린다(그 종목만 넘긴다). 키는 헤더로만 — 오류 글에 찍히지 않게."""
    last = [0.0]

    def call(name):
        wait = NEWS_GAP - (time.monotonic() - last[0])
        if wait > 0:
            time.sleep(wait)
        last[0] = time.monotonic()
        r = requests.get(NEWS_URL, params={"query": f"{name} 주가", "display": NEWS_DISPLAY, "sort": "date"},
                         headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret,
                                  "User-Agent": "economic-site/1.0"}, timeout=8)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        return r.json().get("items") or []
    return call


# ── 재료 → 규칙 문장 ──────────────────────────────────────────────────────────
def index_pct(data, market, day, today):
    """그 시장 지수의 day 등락률(%) — 오늘이면 indices 현재 값, 아니면 history 의 그날 종가 ÷ 전날 종가. 없으면 None."""
    key = (MARKET_INDEX.get(market) or (None,))[0]
    if not key:
        return None
    if day == today:
        v = _num(((data.get("indices") or {}).get(key) or {}).get("change"))
        if v is not None:
            return v
    pts = ((data.get("history") or {}).get("indices") or {}).get(key) or []
    for i, p in enumerate(pts):
        if i and isinstance(p, dict) and p.get("date") == day and isinstance(pts[i - 1], dict):
            c, b = _num(p.get("close")), _num(pts[i - 1].get("close"))
            if c is not None and b:
                return round((c / b - 1) * 100, 2)
    return None


def reason_for(code, row, data, articles, today):
    """(규칙 문장, refs) — 재료가 하나도 없으면 None. today = 'YYYY-MM-DD'(KST).
    등락의 거래일(행 as_of)이 오늘이 아니면 문장 앞에 날짜를 밝힌다(장 전 08시 런은 전날 목록이다)."""
    parts, refs = [], []
    row = row or {}
    session = _day(row.get("as_of"))
    chg, market = _num(row.get("chg")), row.get("market")
    # ① 지수 동행 — 둘 다 0 이 아니고 같은 방향, 차이 1%p 안(부동소수 오차는 경계 안으로 친다)
    ip = index_pct(data, market, session, today) if session and market in MARKET_INDEX else None
    if chg and ip and (chg > 0) == (ip > 0) and abs(chg - ip) <= COMOVE_PP + 1e-9:
        label, up = MARKET_INDEX[market][1], chg > 0
        mark = "" if session == today else _md(session) + " "
        parts.append(f"{mark}{label} {'상승' if up else '하락'}과 함께 {'올랐' if up else '내렸'}습니다")
        refs.append({"kind": "지수", "label": f"{label} {'▲' if ip > 0 else '▼'}{abs(ip):.2f}%", "at": session})
    # ② 최근 공시 — 등락 거래일 이전 10일 안 잠정실적 · 배당결정(공시검색 행만, 결산 배당 표는 공시가 아니다)
    ref_day = session or today
    near = []
    for e in (data.get("corpEvents") or {}).get("items") or []:
        d = _day(e.get("date")) if isinstance(e, dict) else None
        if not d or e.get("code") != code or e.get("via") or e.get("kind") not in ("earnings", "dividend"):
            continue
        if 0 <= _gap(ref_day, d) <= DISCLOSURE_DAYS:
            near.append((_gap(ref_day, d), d, e))
    if near:
        g, d, e = min(near, key=lambda x: x[0])
        title = e.get("title") or ("잠정실적" if e.get("kind") == "earnings" else "배당 결정")
        if g == 0:
            parts.append(f"오늘 {title} 공시" if d == today else f"{_md(d)} {title} 공시 당일")
        else:
            parts.append(f"{_md(d)} {title} 공시 {DAY_WORD[g]} 뒤")
        ref = {"kind": "공시", "label": f"{_md(d)} {title}", "at": d}
        if e.get("rcpNo"):
            ref["url"] = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + urllib.parse.quote(str(e["rcpNo"]))
        refs.append(ref)
    # ③ 52주 신고가 · 신저가 — KRX 목록(시장별 20행)에 있으면. 기준일이 오늘이 아니면 날짜를 붙인다
    rk = data.get("rankingsKr") or {}
    for key, kind in (("high52", "신고가"), ("low52", "신저가")):
        node = rk.get(key) or {}
        d = _day(node.get("as_of"))
        if not d or not 0 <= _gap(today, d) <= HILO_DAYS:
            continue
        if any(isinstance(r, dict) and str(r.get("code")) == code for m in ("kospi", "kosdaq") for r in node.get(m) or []):
            word = ("" if d == today else _md(d) + " ") + "52주 " + kind
            parts.append(word)
            refs.append({"kind": kind, "label": word, "at": d})
    # ④ 기사 제목 — 근거 칩으로 최신 2건. 문장에는 다른 재료가 없을 때만 쓴다(제목은 까닭이 아니라 소식일 때가 많다)
    for a in (articles or [])[:ARTICLE_REFS]:
        refs.append({"kind": "기사", "label": a["title"], "url": a["url"], "at": a["at"]})
    if not parts and articles:
        t = articles[0]["title"]
        parts.append("기사 「%s」" % (t if len(t) <= 40 else t[:39] + "…"))
    return (" · ".join(parts), refs) if refs else None


# ── AI 다듬기 ─────────────────────────────────────────────────────────────────
def _numbers(s):
    out = set()
    for tok in _NUM.findall(s or ""):
        try:
            out.add(float(tok.replace(",", "")))
        except ValueError:
            pass
    return out


def polish_prompt(rule, refs):
    mats = "\n".join(f"- {r['kind']}: {r['label']}" for r in refs)
    return ("다음은 한 종목이 움직인 까닭을 규칙으로 고른 문장과 그 재료다. 문장을 자연스러운 한국어 한 문장"
            f"({LINE_MAX}자 이내)으로 다듬어라.\n"
            "규칙: 재료에 없는 사실 · 숫자 · 전망 금지, 매수 · 매도 권유 금지, '내일 · 다음 주' 같은 시점 표현 금지, "
            "종목 이름 · 머리말 · 따옴표 없이 문장만.\n"
            f"문장: {rule}\n재료:\n{mats}")


def polish_ok(text, rule, refs):
    """다듬은 문장 대조 — 길이 · 한 줄 · 금지 낱말 · 새 숫자(출력 숫자 ⊆ 규칙 문장 + 재료 글자의 숫자)."""
    s = (text or "").strip()
    src = rule + " " + " ".join(str(r.get("label") or "") for r in refs)
    return (8 <= len(s) <= LINE_MAX and "\n" not in s
            and not any(w in s for w in BANNED)
            and not any(w in s and w not in src for w in NEW_ONLY)
            and _numbers(s) <= _numbers(src))


def _clean_ai(text):
    return str(text or "").strip().strip("\"'“”‘’「」").strip()


# ── 조립 ────────────────────────────────────────────────────────────────────
def build(data, now, cfg_path=CFG_FILE, news=None, polish=None):
    """→ (stockNews 또는 None, stockReasons). now = KST aware datetime.
    news(name) = 검색 응답 items(실패면 예외) — None 이면 기사 단계를 건너뛰고 stockNews 도 만들지 않는다.
    polish(prompt) = Gemini 응답 글 — None 이면 다듬기를 건너뛴다."""
    today = now.date().isoformat()
    at = now.isoformat(timespec="seconds")
    tg = targets(data, cfg_path)
    rows, others = _rows(data), _known_names(data, tg)
    prev_news = (data.get("stockNews") or {}).get("items") or {}
    prev_rs = (data.get("stockReasons") or {}).get("items") or {}
    news_items, reasons = {}, {}
    news_fail = ai_fail = ai_used = 0
    for code, name in tg:
        arts = []
        if news:
            try:
                arts = pick_articles(news(name), name, others, now)
            except Exception as e:                   # noqa: BLE001 — 그 종목만 넘긴다(직전 기사 중 24시간 안 것은 잇는다)
                news_fail += 1
                log(f"{code} 기사 검색 실패({type(e).__name__}: {e}) — 직전 기사 중 24시간 안 것만 잇는다")
                cut = now - timedelta(hours=NEWS_HOURS)
                arts = [a for a in prev_news.get(code) or []
                        if isinstance(a, dict) and a.get("title") and a.get("url")
                        and (lambda t: t is not None and t >= cut)(_parse_at(a.get("at")))]
            if arts:
                news_items[code] = arts
        got = reason_for(code, rows.get(code), data, arts, today)
        if not got:
            continue
        rule, refs = got
        labels = [r["label"] for r in refs]
        line, source = rule, "rule"
        p = prev_rs.get(code) if isinstance(prev_rs.get(code), dict) else {}
        if (p.get("source") == "gemini" and p.get("line") and p.get("rule") == rule and _day(p.get("at")) == today
                and [r.get("label") for r in p.get("refs") or [] if isinstance(r, dict)] == labels):
            line, source = p["line"], "gemini"           # 재료가 그대로다 — 다시 묻지 않는다
        elif polish and ai_fail < GEMINI_FAIL_STOP:
            try:
                out = _clean_ai(polish(polish_prompt(rule, refs)))
                ai_fail, ai_used = 0, ai_used + 1
                if polish_ok(out, rule, refs):
                    line, source = out, "gemini"
                else:
                    log(f"{code} 다듬은 문장이 대조에 걸림 — 규칙 문장을 쓴다: {out!r}")
            except Exception as e:                   # noqa: BLE001 — 규칙 문장으로
                ai_fail += 1
                log(f"{code} Gemini 실패({type(e).__name__})" + (" — 이 런의 나머지는 규칙 문장" if ai_fail >= GEMINI_FAIL_STOP else ""))
        reasons[code] = {"line": line, "rule": rule, "source": source, "at": at, "refs": refs}
    log(f"대상 {len(tg)}종목 · 기사 {len(news_items)}종목" + (f"(검색 실패 {news_fail})" if news else "(검색 건너뜀)")
        + f" · 이유 {len(reasons)}종목(gemini {sum(r['source'] == 'gemini' for r in reasons.values())}, 호출 {ai_used})")
    return ({"asOf": at, "items": news_items} if news else None), {"asOf": at, "items": reasons}


def _parse_at(s):
    try:
        t = datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=KST)


def should_run(data, now):
    """장 서는 날 KST 08~20시 런. 휴장 판정은 marketCalendarKr 가 오늘 날짜를 가질 때만 믿고, 아니면 평일이면 연다."""
    t = (data.get("marketCalendarKr") or {}).get("today") or {}
    open_day = bool(t.get("open")) if t.get("date") == now.date().isoformat() else now.weekday() < 5
    return open_day and now.hour in RUN_HOURS


def main(argv):
    now = datetime.now(KST)
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:                           # noqa: BLE001
        log(f"data.json 로드 실패 — 건너뜀: {type(e).__name__}")
        return 0
    if "--force" not in argv and not should_run(d, now):
        log(f"장 서는 날 08~20시 런이 아니다({now:%m-%d %H:%M} KST) — 건너뜀(직전 블록은 수집기가 잇는다)")
        return 0
    cid, secret = os.environ.get("NAVER_CLIENT_ID", "").strip(), os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    news = naver_search(cid, secret) if cid and secret else None
    if not news:
        log("NAVER_CLIENT_ID/SECRET 없음 — 기사 단계 건너뜀(직전 기사 블록 유지)")
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    polish = (lambda prompt: _gemini_text(key, prompt, GEN, GEMINI_TIMEOUT)) if key else None
    if not polish:
        log("GEMINI_API_KEY 없음 — 규칙 문장만")
    try:
        sn, sr = build(d, now, CFG_FILE, news, polish)
    except Exception as e:                           # noqa: BLE001 — data.json 은 그대로 둔다
        log(f"오류 — data.json 을 건드리지 않는다: {type(e).__name__}: {e}")
        return 0
    if sn is not None:
        d["stockNews"] = sn
    d["stockReasons"] = sr
    # 직렬화를 먼저 끝내고 쓴다 — 도중에 죽어도 data.json 이 반쯤 잘린 채로 남지 않게. data.json 기록자 공통 압축 형식
    payload = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        f.write(payload)
    log("data.json 갱신 — stockReasons" + (" · stockNews" if sn is not None else ""))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
