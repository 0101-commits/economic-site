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
    # '1줄=주식/2줄=환율·금리/3줄=원자재' 고정 배분은 폐기 — 매일 같은 틀의 나열이 되어
    # 정보가치가 낮았다. 대신 '이례적 변화 1가지 + 파급 경로 + 내일 확인 지표'를 요구해
    # 스냅샷(수급·금리차·신용스프레드·헤드라인 포함)에서 통찰을 뽑도록 유도한다.
    return (
        "다음은 오늘의 시장 데이터 스냅샷이다(JSON). 한국 개인투자자 관점에서 "
        "'오늘의 매크로 3줄 요약'을 한국어로 작성하라.\n"
        "규칙: 정확히 3줄, 각 줄 90자 이내, 번호/불릿/머리말 없이 본문만, "
        "데이터에 없는 수치를 지어내지 말 것.\n"
        "반드시 포함: ① 스냅샷에서 가장 이례적인 변화 1가지와 그것이 한국 시장에 "
        "미치는 파급 경로, ② 내일 확인해야 할 지표 1가지.\n\n"
        + json.dumps(snap, ensure_ascii=False, default=str)
    )


def try_gemini(snap):
    if not GEMINI_API_KEY:
        return None
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
            # 키를 URL 쿼리(params)가 아닌 헤더로 전달 — 비2xx 응답 시 raise_for_status 예외 메시지에
            # 요청 URL(쿼리 포함)이 박혀 키가 로그로 새는 것을 방지. (worker.js 와 동일 방식)
            headers={"x-goog-api-key": GEMINI_API_KEY},
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
