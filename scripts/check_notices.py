"""제공기관 공지 감시 (A15) — 주 1회 각 기관 공지 목록을 읽어 새 제목을 찾고 #시스템 으로 알린다.

배경: EXIM API 도메인 변경(구 도메인 2026-04-30 종료)을 아무도 공지판을 안 봐서 놓쳤다.
새 제목 → 키워드 필터 → (GEMINI_API_KEY 있으면) 영향 있는 것만 Gemini 로 선별.
없으면 아무것도 보내지 않는다. 상태=scripts/notices_state.json.
  python scripts/check_notices.py [--dry-run]
"""
import hashlib
import html
import json
import os
import re
import sys
import datetime

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "notices_state.json")
sys.path.insert(0, HERE)

# (이름, URL, href 힌트 정규식) — 힌트는 공지 항목 링크만 남기는 필터(메뉴 링크 제외).
# 0건이면 SPA(JS 렌더링)이거나 힌트가 안 맞는 것 — 실행 로그의 소스별 제목 수로 확인한다.
NOTICE_SOURCES = [
    ("한국은행 ECOS", "https://ecos.bok.or.kr/api/#/Notice", r"ntt|notice|board"),
    ("KOSIS OpenAPI", "https://kosis.kr/openapi/index/index.jsp", r"clickNoticeList"),
    ("공공데이터포털", "https://www.data.go.kr/bbs/ntc/selectNoticeListView.do", r"fn_view"),
    ("한국부동산원 R-ONE", "https://www.reb.or.kr/r-one/portal/bbs/notice/searchBulletinPage.do", r"Detail|fn_view|searchBulletinView"),
    ("KRX Open API", "https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES001_S1.cmd", r"notice|NOTICE|Notice"),
    ("OpenDART", "https://opendart.fss.or.kr/cop/bbs/selectArticleList.do?bbsId=B0000000000000000001", r"fnDetailView"),
    ("FRED", "https://fredblog.stlouisfed.org/", r"/20\d\d/\d\d/"),
    ("네이버 개발자센터", "https://developers.naver.com/notice/", r"notice/article"),
    ("토스증권 Open API", "https://openapi.tossinvest.com/docs/changelog", None),
    ("수출입은행", "https://www.koreaexim.go.kr/ir/HPHKIR020M01?apino=2&viewtype=C", r"view|Notice|notice"),
    ("금융위 지수시세정보", "https://www.data.go.kr/data/15094807/openapi.do", r"fn_view|notice"),
]

KEYWORDS = re.compile(
    r"주소|도메인|URL|종료|중단|폐지|변경|점검|인증|키|한도|제한|서비스 개편|만료"
    r"|deprecat|sunset|migrat|endpoint|rate limit", re.I)
UA = {"User-Agent": "Mozilla/5.0 (economic-site notice-check)"}
_A = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
_HREF = re.compile(r'href\s*=\s*["\']([^"\']*)["\']', re.I)
_TAG = re.compile(r"<[^>]+>")


def parse_titles(page, base="", limit=15, hint=None):
    """앵커 텍스트 중 제목다운 것(한글/영문 6~120자, 공백 5개 미만 메뉴 제외)을 위에서 limit 개."""
    out, seen = [], set()
    for attrs, inner in _A.findall(page):
        t = re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", inner))).strip()
        if not (6 <= len(t) <= 120) or t in seen or t.lower().startswith(("javascript", "http")):
            continue
        if len(t.split()) < 2:            # 한 단어짜리는 메뉴 링크
            continue
        m = _HREF.search(attrs)
        href = m.group(1) if m else ""
        if hint and not re.search(hint, href + " " + attrs):
            continue
        if href.startswith("/") and base:
            href = base.rstrip("/") + href
        seen.add(t)
        out.append({"title": t, "link": href})
        if len(out) >= limit:
            break
    return out


def fetch(url):
    try:
        r = requests.get(url, headers=UA, timeout=20)
    except requests.exceptions.SSLError:
        # 수출입은행 등 인증서 체인이 불완전한 공공기관 — 공개 공지 읽기 전용이라 검증 없이 재시도
        r = requests.get(url, headers=UA, timeout=20, verify=False)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r.text


def digest(items):
    return hashlib.sha1("\n".join(i["title"] for i in items).encode()).hexdigest()[:12]


def new_items(prev, items):
    """이전 제목 목록에 없던 항목. prev 가 없으면(첫 실행) 기준선만 잡고 빈 목록."""
    if prev is None:
        return []
    old = set(prev.get("titles", []))
    return [i for i in items if i["title"] not in old]


def keyword_filter(cands):
    return [c for c in cands if KEYWORDS.search(c["title"])]


def gemini_pick(cands, key):
    """후보 중 영향 있는 것만 인덱스로 받는다. 실패 시 None(호출부가 키워드 결과로 폴백)."""
    from ai_briefing import GEMINI_MODELS
    lst = "\n".join(f"{n}. [{c['org']}] {c['title']}" for n, c in enumerate(cands))
    prompt = ("경제 대시보드의 수집기는 한국은행 ECOS, KOSIS, 공공데이터포털, 한국부동산원, KRX, OpenDART, "
              "FRED, 네이버, 토스증권, 수출입은행 API 를 쓴다. 아래 공지 중 이 수집기에 영향이 있는 것"
              "(주소·도메인·인증·한도·종료·형식 변경 등)만 골라 번호만 JSON 배열로 답하라. 없으면 [].\n" + lst)
    for model in GEMINI_MODELS:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": 0, "maxOutputTokens": 200}},
                timeout=40)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            idx = json.loads(re.search(r"\[.*?\]", txt, re.S).group(0))
            return [cands[i] for i in idx if isinstance(i, int) and 0 <= i < len(cands)]
        except Exception as e:  # noqa: BLE001
            print(f"Gemini 실패({model}): {e}")
            return None
    return None


def format_message(picked, used_ai):
    lines = []
    for c in picked:
        lines.append(f"{c['org']} · {c['title']} · {c.get('link') or c['url']}")
    foot = "" if used_ai else "\n(Gemini 미사용 — 키워드 필터만 적용)"
    return "\n".join(lines) + foot, f"📋 원천 공지 감시 — 영향 후보 {len(picked)}건"


def main(dry=False):
    state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="seconds")
    cands, counts = [], {}
    for name, url, hint in NOTICE_SOURCES:
        try:
            base = "/".join(url.split("/")[:3])
            items = parse_titles(fetch(url), base, hint=hint)
        except Exception as e:  # noqa: BLE001
            print(f"[{name}] 실패: {type(e).__name__}: {e}")
            counts[name] = "ERR"
            continue
        counts[name] = len(items)
        if not items:                       # 0건이면 상태를 덮어쓰지 않는다(파서 실패≠공지 삭제)
            continue
        for i in new_items(state.get(name), items):
            cands.append({**i, "org": name, "url": url})
        state[name] = {"hash": digest(items), "titles": [i["title"] for i in items], "checkedAt": now}
    print("소스별 제목 수:", json.dumps(counts, ensure_ascii=False))
    hits = keyword_filter(cands)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    picked, used_ai = hits, False
    if key and hits:
        ai = gemini_pick(hits, key)
        if ai is not None:
            picked, used_ai = ai, True
    if picked:
        body, title = format_message(picked, used_ai)
        if dry:
            print(title + "\n" + body)
        else:
            from notify_discord import system
            system(body, title=title)
    else:
        print(f"영향 후보 없음 (새 제목 {len(cands)}건) — 발송 안 함")
    if not dry:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
    return counts


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
