#!/usr/bin/env python3
"""
메르 리스크 렌즈 v2 — P1 글별 구조화 추출.

merblog.json(365일 메타) → 원문 온디맨드 조회 → LLM 구조화(JSON) → mer_extract_cache.jsonl

왜 캐시가 커밋되고 원문은 안 되나:
  공개 저장소라 원문 전량 커밋은 금지(결정 D2). 남는 것은 글의 좌표뿐이다 —
  logNo, 80자 이하 인용, 방향·강도. 원문은 네이버에 있고 숫자는 data.json 에 있다.

멱등: 캐시에 있는 logNo 는 다시 부르지 않는다. 스키마가 오르면 --reextract 로만 재처리.
실패 보존: 어떤 실패에도 기존 캐시를 지우지 않는다(날조 금지 원칙).

실행:
  python scripts/mer_extract.py                 # 증분(신규 글만)
  python scripts/mer_extract.py --limit 60      # 백필을 회차로 쪼갬(GHA 70분 타임아웃 대응)
  python scripts/mer_extract.py --dry-run       # 키 없이 대상만 세어 본다
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(__file__))
import merblog_lib as M  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "mer_extract_cache.jsonl")
MERBLOG = os.path.join(ROOT, "merblog.json")
KST = timezone(timedelta(hours=9))

SCHEMA_VERSION = "v1"
QUOTE_MAX = 80

# 결정 D3 — 비경제 카테고리는 LLM 을 부르기 전에 잘라낸다(129편).
# 「주절주절」은 제목상 대부분 경제(FOMC·국민연금·환율·서킷)라 LLM 의 econ 판별에 맡긴다.
SKIP_CATEGORY = re.compile(r"건강|의학|맛집|일상|역사")

POST_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("MER_EXTRACT_MODEL", "claude-opus-5")
# Google 은 모델을 조용히 퇴역시킨다 — gemini-2.0-flash 도 2.5-flash 도 지금은 404 다
# (2026-09-15 실측, 신규 키 기준). 고정 모델을 먼저 쓰되 404 면 별칭으로 물러선다.
# `-latest` 별칭은 살아 있지만 과부하 503 이 잦아 1순위로 두지 않는다(3/3 실패 실측).
GEMINI_MODEL = os.environ.get("MER_EXTRACT_GEMINI_MODEL", "gemini-3.1-flash-lite")
GEMINI_FALLBACK = "gemini-flash-lite-latest"


def log(msg):
    print(f"[mer_extract] {msg}", flush=True)


# ── 「한줄 코멘트」 — 마지막 매치 ────────────────────────────────────────────
# 프론트(app6.js:187)의 정규식은 첫 매치라 A/S 글에서 재수록된 옛 코멘트를 잡는다
# (2026-09-11 글에서 실증). 서버는 마지막 매치를 쓴다.
# 게으른 수량자로 「마커 … 끝」을 한 번에 잡으면 첫 매치가 글 끝까지 먹어 버려
# 마지막 매치가 생기지 않는다(실측). 마커 위치만 모아 마지막 것을 고른다.
# 구분자(마침표·콜론·줄바꿈)를 **필수**로 둔다. 없으면 "한줄 코멘트가 없는 글" 같은
# 평범한 문장의 조사까지 마커로 잡힌다. 실제 글은 783/813편이 「한줄 코멘트.」로 끝난다.
_ONE_LINER_MARK = re.compile(r"한\s*줄\s*코멘트\s*(?:[.:]|[\r\n])\s*")


def one_liner_last(text):
    ms = list(_ONE_LINER_MARK.finditer(text or ""))
    if not ms:
        return None
    tail = text[ms[-1].end():]
    # 대소문자를 무시해야 한다 — 이 블로그는 소문자 `ps)` 를 흔히 쓰고, 대문자만 잡던
    # 정규식 탓에 PS 노트와 유튜브 링크가 한줄 코멘트에 통째로 붙었다
    # (2026-09-15 표본 검수에서 발견, 캐시 736편 중 21편이 오염돼 있었다).
    tail = re.split(r"\s*PS\s*\)", tail, flags=re.IGNORECASE)[0]
    tail = re.sub(r"\s+", " ", tail).strip()
    return tail or None


# ── 인용 검증 ──────────────────────────────────────────────────────────────
def _norm(s):
    return re.sub(r"\s+", "", s or "")


def quote_is_real(quote, source):
    """인용이 원문에 실재하는지. 공백을 무시하고 비교한다(LLM 이 줄바꿈을 정리한다)."""
    q = _norm(quote)
    return bool(q) and q in _norm(source)


def trim_quote(q):
    q = re.sub(r"\s+", " ", (q or "")).strip()
    return q if len(q) <= QUOTE_MAX else q[: QUOTE_MAX - 1].rstrip() + "…"


# ── 프롬프트 ───────────────────────────────────────────────────────────────
PROMPT = """너는 한국 경제 블로그 글 한 편을 구조화 데이터로 옮기는 추출기다.
아래 글을 읽고 JSON 객체 하나만 출력한다. 설명·머리말·코드펜스 없이 JSON 만.

규칙:
- 모든 quote 는 원문에서 **그대로 잘라낸 연속된 문자열**이어야 한다. 요약·의역·창작 금지. 80자 이내.
- 원문에 없는 수치·주장·자산명을 만들지 마라. 근거가 없으면 그 필드를 빈 배열로 둔다.
- asset 은 반드시 **하나씩** 적는다. "삼성전자·SK하이닉스" 처럼 묶지 말고 항목을 나눠라.
- thresholds 는 "이 숫자를 넘으면 이런 일이 생긴다" 는 조건문만. 단순 현재값은 indicators 에 넣는다.
- view 는 -2(강한 매도) ~ +2(강한 매수) 정수. 판단 유보는 0 이고, "언급 없음" 과 다르다.
- econ 은 이 글이 경제·시장·정책·산업을 다루면 true, 건강·맛집·일상·역사면 false.

출력 스키마:
{"econ": bool,
 "topics": [string],
 "indicators": [{"name": string, "value": string, "kind": "level"|"rate"|"count",
                 "direction": "up"|"down"|"flat", "quote": string}],
 "thresholds": [{"indicator": string, "level": string, "meaning": string, "quote": string}],
 "impacts": [{"from": string, "to": string, "direction": "+"|"-"|"±",
              "strength": 1|2|3, "horizon": "단기"|"중기"|"장기", "quote": string}],
 "stance": [{"asset": string, "view": -2|-1|0|1|2, "why": string}],
 "chain": string|null,
 "risk_flags": [string]}

risk_flags 는 다음 중에서만 고른다:
["정책","지정학","유동성","금리발작","신용","관세","부동산","엔캐리 청산","공급망","AI버블"]

제목: {title}
날짜: {date}
본문:
{body}
"""


def build_prompt(post, body):
    return (PROMPT
            .replace("{title}", post.get("title") or "")
            .replace("{date}", (post.get("date") or "")[:10])
            .replace("{body}", body[:18000]))


def _strip_fence(text):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    i, j = t.find("{"), t.rfind("}")
    return t[i:j + 1] if i >= 0 and j > i else t


def call_anthropic(prompt):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_KEY,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": ANTHROPIC_MODEL, "max_tokens": 2000,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=120,
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", []))


def _gemini_once(model, prompt):
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": GEMINI_KEY},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2000,
                                   "responseMimeType": "application/json"}},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _gemini_with_retry(model, prompt):
    """429(쿼터)·503(과부하)은 글의 문제가 아니라 순간 상태다 — 한 번은 물러섰다 다시 친다.
    백필 349편에서 429 가 1건, -latest 별칭에서 503 이 3건 관측됐다(2026-09-15)."""
    for attempt in range(2):
        try:
            return _gemini_once(model, prompt)
        except requests.HTTPError as e:
            if attempt or getattr(e.response, "status_code", None) not in (429, 503):
                raise
            time.sleep(20)


def call_gemini(prompt):
    try:
        return _gemini_with_retry(GEMINI_MODEL, prompt)
    except requests.HTTPError as e:
        # 404 = 그 모델이 퇴역했다는 뜻. 편마다 같은 404 를 맞기보다 별칭으로 넘어간다.
        if getattr(e.response, "status_code", None) != 404 or GEMINI_FALLBACK == GEMINI_MODEL:
            raise
        log(f"  {GEMINI_MODEL} 404(퇴역) — {GEMINI_FALLBACK} 로 폴백")
        return _gemini_with_retry(GEMINI_FALLBACK, prompt)


def provider():
    """결정 D1 — Anthropic 권고안이 우선이고, 키가 없으면 GHA 에 이미 있는 Gemini 로 돈다."""
    if ANTHROPIC_KEY:
        return "anthropic", call_anthropic, ANTHROPIC_MODEL
    if GEMINI_KEY:
        return "gemini", call_gemini, GEMINI_MODEL
    return None, None, None


# ── 스키마 정규화·검증 ─────────────────────────────────────────────────────
_VALID_DIR = {"+", "-", "±"}
_VALID_HORIZON = {"단기", "중기", "장기"}


def sanitize(raw, post, body, model):
    """LLM 출력 → 캐시 1행. 인용이 원문에 없는 항목은 **버린다**(날조 차단)."""
    out = {
        "logNo": str(post["logNo"]),
        "date": (post.get("date") or "")[:10],
        "title": post.get("title") or "",
        "econ": bool(raw.get("econ")),
        "topics": [str(t) for t in (raw.get("topics") or [])][:8],
        "indicators": [], "thresholds": [], "impacts": [], "stance": [],
        "chain": (raw.get("chain") or None),
        "one_liner": one_liner_last(body),
        "risk_flags": [str(f) for f in (raw.get("risk_flags") or [])][:6],
        "series": None,
        "_meta": {"model": model, "schema": SCHEMA_VERSION,
                  "extractedAt": datetime.now(KST).isoformat(timespec="seconds")},
    }
    dropped = 0

    for it in raw.get("indicators") or []:
        q = trim_quote(it.get("quote"))
        if not quote_is_real(q.rstrip("…"), body):
            dropped += 1
            continue
        out["indicators"].append({"name": str(it.get("name") or ""), "value": str(it.get("value") or ""),
                                  "kind": str(it.get("kind") or "level"),
                                  "direction": str(it.get("direction") or "flat"), "quote": q})

    for it in raw.get("thresholds") or []:
        q = trim_quote(it.get("quote"))
        if not quote_is_real(q.rstrip("…"), body):
            dropped += 1
            continue
        out["thresholds"].append({"indicator": str(it.get("indicator") or ""),
                                  "level": str(it.get("level") or ""),
                                  "meaning": str(it.get("meaning") or ""), "quote": q})

    for it in raw.get("impacts") or []:
        q = trim_quote(it.get("quote"))
        if not quote_is_real(q.rstrip("…"), body):
            dropped += 1
            continue
        d = str(it.get("direction") or "±")
        try:
            s = int(it.get("strength") or 1)
        except (TypeError, ValueError):
            s = 1
        out["impacts"].append({"from": str(it.get("from") or ""), "to": str(it.get("to") or ""),
                               "direction": d if d in _VALID_DIR else "±",
                               "strength": min(max(s, 1), 3),
                               "horizon": (it.get("horizon") if it.get("horizon") in _VALID_HORIZON else "중기"),
                               "quote": q})

    for it in raw.get("stance") or []:
        try:
            v = int(it.get("view"))
        except (TypeError, ValueError):
            continue
        out["stance"].append({"asset": str(it.get("asset") or ""), "view": min(max(v, -2), 2),
                              "why": str(it.get("why") or "")})

    return out, dropped


# ── 캐시 입출력 ────────────────────────────────────────────────────────────
def load_cache():
    rows, seen = [], set()
    if not os.path.exists(CACHE):
        return rows, seen
    with open(CACHE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append(r)
            seen.add(str(r.get("logNo")))
    return rows, seen


def write_cache(rows):
    """원자적 교체 — 도중에 죽어도 기존 캐시가 반쯤 지워지지 않는다."""
    rows.sort(key=lambda r: (r.get("date") or "", str(r.get("logNo"))))
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, CACHE)


def is_systemic_failure(auth_dead, ok, fail):
    """이 회차가 "키·모델이 죽어서" 실패한 것인지 판정한다.

    GHA 스텝이 continue-on-error 라 exit 0 이면 워크플로가 초록으로 남고
    "며칠째 0건 추출"이 아무에게도 안 보인다(2026-09-15 실측 — GEMINI_API_KEY 401 로
    40편 전부 실패했는데 런은 success 였다). 그래서 체계적 실패만 종료코드로 알린다.

    개별 글의 실패로는 울리지 않는다 — 원문이 96자뿐인 글 하나 때문에 알림이 가면
    사람이 알림을 끄게 되고, 그러면 진짜 고장도 같이 묻힌다.
    """
    return bool(auth_dead) or (ok == 0 and fail >= 5)


def fetch_body(log_no):
    url = f"https://blog.naver.com/PostView.naver?blogId={M.BLOG_ID}&logNo={log_no}"
    r = requests.get(url, headers={"User-Agent": POST_UA}, timeout=20)
    r.raise_for_status()
    return M.extract_fulltext(r.text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="이번 회차에 처리할 최대 편수(0=제한 없음)")
    ap.add_argument("--reextract", action="store_true", help="캐시를 무시하고 다시 추출")
    ap.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 대상만 센다")
    args = ap.parse_args()

    if not os.path.exists(MERBLOG):
        log("merblog.json 없음 — 먼저 scripts/fetch_merblog.py 를 돌려라")
        return 0
    with open(MERBLOG, encoding="utf-8") as f:
        posts = (json.load(f) or {}).get("posts") or []

    rows, seen = load_cache()
    todo = []
    for p in posts:
        if SKIP_CATEGORY.search(p.get("category") or ""):
            continue                      # 결정 D3 — 비경제 카테고리 사전 제외
        if not args.reextract and str(p.get("logNo")) in seen:
            continue
        todo.append(p)
    todo.sort(key=lambda p: (p.get("date") or ""), reverse=True)   # 최신 글 우선
    if args.limit:
        todo = todo[: args.limit]

    name, call, model = provider()
    log(f"대상 {len(todo)}편 (캐시 {len(rows)}편 / 글 {len(posts)}편) · 제공자={name or '없음'}")
    if args.dry_run or not todo:
        return 0
    if not call:
        log("ANTHROPIC_API_KEY / GEMINI_API_KEY 둘 다 없음 — 추출 건너뜀(캐시 보존)")
        return 0

    by_log = {str(r.get("logNo")): r for r in rows}
    ok = fail = dropped_total = 0
    auth_dead = False
    for i, p in enumerate(todo, 1):
        log_no = str(p["logNo"])
        try:
            body = fetch_body(log_no)
            if len(body) < 200:
                raise RuntimeError(f"원문 {len(body)}자 — 너무 짧음")
            text = call(build_prompt(p, body))
            raw = json.loads(_strip_fence(text))
            row, dropped = sanitize(raw, p, body, model)
            by_log[log_no] = row
            ok += 1
            dropped_total += dropped
        except Exception as e:                        # noqa: BLE001 — 한 편 실패가 회차를 깨지 않는다
            fail += 1
            log(f"  실패 {log_no}: {type(e).__name__}: {str(e)[:120]}")
            # 인증 실패는 글의 문제가 아니라 키의 문제다. 남은 편수만큼 같은 401 을
            # 되풀이해 봐야 로그만 길어지고, 런은 continue-on-error 라 성공으로 보여
            # 원인이 묻힌다(2026-09-15 실측: GHA GEMINI_API_KEY 가 401, 40편 전부 실패).
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (401, 403):
                log(f"!! {name} 키 인증 실패({status}) — 남은 {len(todo) - i}편 건너뜀. "
                    f"키를 갱신하거나 ANTHROPIC_API_KEY 를 등록해야 추출이 돈다.")
                auth_dead = True
                break
        if i % 10 == 0 or i == len(todo):
            write_cache(list(by_log.values()))        # 중간 저장 — 타임아웃에도 진척이 남는다
            log(f"  {i}/{len(todo)} 처리 (성공 {ok} 실패 {fail})")
        time.sleep(0.4)

    write_cache(list(by_log.values()))
    log(f"완료 — 성공 {ok} · 실패 {fail} · 인용 미검증으로 버린 항목 {dropped_total} · 캐시 {len(by_log)}편")

    if is_systemic_failure(auth_dead, ok, fail):
        log("!! 체계적 실패 — exit 2 로 알린다(워크플로 알림 스텝이 이 결과를 읽는다)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
