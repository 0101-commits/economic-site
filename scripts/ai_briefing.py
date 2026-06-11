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
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

KST = timezone(timedelta(hours=9))
DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data.json")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()


def log(msg):
    print(f"[ai_briefing] {msg}", flush=True)


def _num(v, nd=2):
    try:
        return f"{float(v):,.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def _chg(v):
    try:
        f = float(v)
        return f"{'▲' if f >= 0 else '▼'}{abs(f):.2f}%"
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

    snap = {
        "KOSPI": idx.get("KOSPI"),
        "S&P500": idx.get("SP500"),
        "NASDAQ": idx.get("NASDAQ"),
        "USDKRW": fx.get("USDKRW"),
        "WTI": com.get("WTI"),
        "Gold": com.get("Gold"),
        "VIX": (ei_us.get("vix") or {}).get("value"),
        "미국기준금리": (ei_us.get("ff_rate") or {}).get("value"),
        "FearGreed": fg.get("value"),
        "FearGreedLabel": fg.get("rating") or fg.get("label"),
    }
    # 오늘/내일 ★3 캘린더 이벤트
    today = datetime.now(KST).date()
    events = ((d.get("economicCalendar") or {}).get("events")) or []
    upcoming = []
    for e in events:
        iso = e.get("iso") or ""
        if e.get("stars", 0) >= 3 and not e.get("act"):
            try:
                ed = datetime.strptime(iso, "%Y-%m-%d").date()
                if 0 <= (ed - today).days <= 2:
                    upcoming.append(e.get("name", ""))
            except ValueError:
                pass
    snap["upcoming"] = upcoming[:3]
    return snap


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


def _llm_prompt(snap):
    return (
        "다음은 오늘의 시장 데이터 스냅샷이다(JSON). 한국 개인투자자 관점에서 "
        "'오늘의 매크로 3줄 요약'을 한국어로 작성하라.\n"
        "규칙: 정확히 3줄, 각 줄 90자 이내, 번호/불릿/머리말 없이 본문만, "
        "데이터에 없는 수치를 지어내지 말 것. 1줄=주식시장, 2줄=환율·금리, 3줄=원자재·시장심리·일정.\n\n"
        + json.dumps(snap, ensure_ascii=False, default=str)
    )


def try_gemini(snap):
    if not GEMINI_API_KEY:
        return None
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
            params={"key": GEMINI_API_KEY},
            json={"contents": [{"parts": [{"text": _llm_prompt(snap)}]}],
                  "generationConfig": {"temperature": 0.4, "maxOutputTokens": 400}},
            timeout=40,
        )
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        lines = [ln.strip().lstrip("0123456789.-•* ") for ln in text.strip().splitlines() if ln.strip()]
        if len(lines) >= 3:
            log("Gemini 요약 생성 성공")
            return lines[:3]
        log(f"Gemini 응답이 3줄 미만 — 폴백 ({len(lines)}줄)")
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 다음 생성기로 폴백
        log(f"Gemini 실패: {e}")
    return None


def try_openai(snap):
    if not OPENAI_API_KEY:
        return None
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": "gpt-4o-mini",
                  "messages": [{"role": "user", "content": _llm_prompt(snap)}],
                  "temperature": 0.4, "max_tokens": 400},
            timeout=40,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        lines = [ln.strip().lstrip("0123456789.-•* ") for ln in text.strip().splitlines() if ln.strip()]
        if len(lines) >= 3:
            log("OpenAI 요약 생성 성공")
            return lines[:3]
        log(f"OpenAI 응답이 3줄 미만 — 폴백 ({len(lines)}줄)")
    except Exception as e:  # noqa: BLE001
        log(f"OpenAI 실패: {e}")
    return None


def main():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:  # noqa: BLE001
        log(f"data.json 로드 실패 — 건너뜀: {e}")
        return 0

    snap = build_snapshot(d)
    source = "rule"
    lines = try_gemini(snap)
    if lines:
        source = "gemini"
    else:
        lines = try_openai(snap)
        if lines:
            source = "openai"
    if not lines:
        lines = rule_based_lines(snap)
        log("규칙 기반 요약 사용 (LLM 키 미설정 또는 실패)")

    now = datetime.now(KST)
    d["aiBriefing"] = {
        "date": now.strftime("%Y-%m-%d"),
        "generatedAt": now.strftime("%Y-%m-%d %H:%M KST"),
        "lines": lines,
        "source": source,
    }
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            # fetch_data.py 와 동일한 포맷 유지 (diff 최소화)
            json.dump(d, f, ensure_ascii=False, indent=2)
        log(f"aiBriefing 갱신 완료 (source={source})")
    except Exception as e:  # noqa: BLE001
        log(f"data.json 저장 실패: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
