"""폰 알림 글자 수 검사(알림 개편 P5 · 커밋 전 검사) — 사전 39종 × 예제 값 → 잠금 화면 한 줄에 들어가나.

제목 = compose.TITLE_W(한글 18칸), 본문 = compose.BODY_W(20칸, 폭은 compose.width — 한글 1 · 그 밖 0.6).
넘치면 compose 가 줄이고 그래도 넘치면 「…」로 자르는데, 예제 값에서 「…」가 나오면 틀이 너무 긴 것이다 → 실패.
예제 값은 실제로 나온 값 가운데 넓은 쪽(11/6 알림 기록 · 지난 4주 원장)으로 둔다. 새 사건 · 새 틀 변수를 넣으면
여기 예제도 같이 넣는다(없는 변수는 틀이 조용히 빠지므로 검사가 헐거워진다 — 빠진 변수는 따로 알린다).

  python scripts/alerts_v2/check_copy.py      # 0 = 통과 · 1 = 넘침
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alerts_v2 import compose, schema  # noqa: E402
from alerts_v2.events import Hit  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FMT = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::[^}]*)?\}")

# 틀 변수 예제(넓은 쪽). 사건마다 다른 것은 아래 PER_EVENT 가 덮는다.
COMMON = {
    "peer": "코스닥", "news": "미국 금리 인하 기대", "zx": "2.4", "next_event": "11/12 미국 CPI", "next_round": "4,000",
    "next_tier": "5", "lens_line": "메르 렌즈 1,450선", "halt_kind": "사이드카", "stage": 1, "source": "거래소 발표",
    "next_stage": "8", "hl_ko": "신고가", "prev_extreme": "4,321.55", "prev_md": "10/28", "level_value": "4,000",
    "from_high": "−3.2", "next_level": "4,100", "line": "1,450", "chain": "환율 사슬", "step": "2", "next_line": "1,480",
    "dist": "1.2", "peer_chg": "−2.1%", "band_ko": "극단적 공포", "prev": "+2.9%", "exit_rule": "25 위로 올라오면 해제",
    "reason": "20일 평균의 1.5배", "realized": "18.2", "chg_bp": 12, "flip_ko": "역전 해소", "streak": 5, "dir_ko": "순매도",
    "cum5": "−3.21조", "support_ko": "기관이 받음", "prev_dir_ko": "순매수", "cum": "−2.40조", "inst": "+1,230억",
    "retail": "+2,100억", "prev_days": 4, "count": 3, "first": "미국 CPI", "list": "미국 CPI · 일본은행", "related": "미 국채 10년",
    "event_name": "한국 소비자물가동향", "act": "+2.8%", "vs_fore": "예상 밑돎", "vs_big": "예상과 큰 차이", "fore": "+2.9%", "why_line": "평소 어긋나는 폭의 3.1배",
    "verb_ko": "인상", "prev_n": 3, "next_meeting": "12/10", "from_md": "12/31", "to_md": "1/1", "next_md": "1/2",
    "us_status": "정상 개장", "kind_ko": "유상증자", "doc_title": "주요사항보고서(유상증자결정)", "label": "투자경고", "prev_labels": "투자주의",
    "counts": "경계 4일 · 안정 2일", "prev_ko": "중립", "post_title": "환율은 어디까지 오를까", "post_date": "11/5", "month_count": 12,
    "titles": "환율 · 반도체 · 금리", "components": "환율 · 금리 · 유가", "trigger": "원·달러 1,450 돌파", "next_step": "다음 단계 1,480",
    "krw_g": "193,500원", "usd_oz": "$4,012", "period": "9월", "national": "+0.12%", "next_date": "12/15", "threshold": "1,450",
}
PER_EVENT = {   # id: (값, 단위, 등락, 덮을 변수)
    "A1": (4123.45, "", -5.3, {}), "A2": (1452.3, "원", 1.8, {}), "A3": (4012.5, "$", 3.2, {}), "A4": (76981, "$", -4.3, {}),
    "A5": (3901.2, "", -7.8, {"stage_label": "1단계"}), "B1": (4321.55, "", 1.2, {}), "B2": (4000.12, "", 1.1, {}),
    "C1": (1452.3, "원", 0.8, {"name": "원·달러"}), "C2": (1440.1, "원", 0.4, {"name": "원·달러"}), "C3": (32.4, "", 12.0, {"stage": 30}),
    "C4": (142.3, "", 6.0, {"stage": 140}), "C5": (18, "", -4.0, {}), "C6": (38.5, "", 9.0, {}), "C7": (4.62, "%", 0.3, {}),
    "C8": (-0.12, "%p", None, {}), "D1": (-8123, "억", None, {}), "D2": (5230, "억", None, {}), "D3": (-1230, "억", None, {}),
    "D4": (-8123, "억", None, {}), "D5": (-1230000, "주", None, {"name": "SK하이닉스"}), "E1": (3, "건", None, {}),
    "E2": ("+2.8%", "", None, {}), "E3": ("+0.4%", "", None, {"event_name": "미국 CPI (전월비)"}), "E4": (3.25, "%", None, {}),
    "E5": (None, "", None, {}), "F1": (None, "", None, {"name": "삼성전자"}), "F2": (None, "", None, {"name": "에코프로비엠"}),
    "F3": (None, "", 29.9, {"name": "에코프로비엠"}), "G1": ("경계", "", None, {"prev": "안정"}), "G2": ("비중 축소", "", None, {"name": "반도체"}),
    "G3": (3, "편", None, {}), "G4": (72, "점", None, {}), "G5": (None, "", None, {"name": "환율"}), "H1": (2.4, "%", None, {}),
    "H2": (2.8, "%", None, {"name": "한국 실업률"}), "H3": (None, "", 0.42, {"name": "서울 강남구"}), "H4": ("라니냐", "", None, {"prev": "중립"}),
    "U1": (8970, "원", None, {"name": "K휴머노이드", "threshold": "9,000", "dir_ko": "아래로"}),
    "U2": (8970, "원", -5.2, {"name": "K휴머노이드", "threshold": "5"}),
}


# 경제 일정 ★★ 이상 이름(data.json economicCalendar, 2026-11-06) — 새 일정 원천을 붙이면 여기도
CAL_NAMES = ("ECB 통화정책 결정", "미국 CPI (전월비)", "미국 FOMC 회의", "미국 GDP", "미국 PCE 물가지수", "미국 PPI",
             "미국 비농업고용(NFP)", "미국 산업생산", "미국 소매판매", "미국 주택착공 (Housing Starts)",
             "일본은행(BOJ) 금융정책결정회합", "한국 고용동향", "한국 산업활동동향", "한국 소비자물가동향", "한국은행 금통위 (통화정책방향)")


CAL_ACT = {"미국 비농업고용(NFP)": "+150K", "미국 주택착공 (Housing Starts)": "1.221M", "미국 FOMC 회의": "4.00%",
           "ECB 통화정책 결정": "2.00%", "일본은행(BOJ) 금융정책결정회합": "0.75%", "한국은행 금통위 (통화정책방향)": "2.50%",
           "미국 GDP": "+1.8%", "미국 CPI (전월비)": "+0.4%"}


class _Ctx:
    """compose 가 읽는 것만 — 이름 사전(bundles/registry.json)과 오늘."""
    def __init__(self):
        p = os.path.join(ROOT, "bundles", "registry.json")
        rows = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else []
        rows = rows.get("rows", rows) if isinstance(rows, dict) else rows
        self.registry = {r["id"]: r for r in rows if isinstance(r, dict) and "id" in r}
        self.now = dt.datetime(2026, 11, 6, 9, 30, tzinfo=dt.timezone(dt.timedelta(hours=9)))

    def rid(self, t):
        return t


def check() -> list[str]:
    ctx, bad = _Ctx(), []
    for ev in schema.load_events():
        if ev.get("level") in ("brief", "record"):
            continue                                   # 폰 알림으로 안 간다
        value, unit, chg, over = PER_EVENT.get(ev["id"], (1234.5, "", 1.2, {}))
        used = {m for k in ("title", "why", "next") for t in (ev.get(k) if isinstance(ev.get(k), list) else [ev.get(k)]) for m in FMT.findall(t or "")}
        missing = sorted(used - set(COMMON) - set(over) - set(compose.variables(ev, Hit("x", "up", 1, "", "2026-11-06", "live"), None)))
        if missing:
            bad.append(f"{ev['id']}: 예제 없는 변수 {', '.join(missing)} — check_copy.COMMON 에 넣을 것")
        # 일정 사건(E)은 실제 ★★ 일정 이름 전부로, 그 밖은 대상 앞 셋으로
        cases = ([("calendar", {"event_name": n, "act": CAL_ACT.get(n, "+2.8%")}) for n in CAL_NAMES] if ev["family"] == "E" and "event_name" in used
                 else [(t, {}) for t in (ev.get("targets") or ["x"])[:3]])
        for tgt, extra in cases:
            h = Hit(target=tgt, dir="down" if (chg or 0) < 0 else "up", value=value, unit=unit, asOf="2026-11-06", fresh="live",
                    chg=chg, fields={**COMMON, **over, **extra})
            r = compose.render(ev, h, ctx)
            for part, w, s in (("제목", compose.TITLE_W, r["title"]), ("본문", compose.BODY_W, r.get("body_push") or "")):
                # 뒤가 잘린 것(「…」로 끝남)은 실패. 이름만 줄인 것(「K휴머노… 8,970 · …」)은 P2 규칙이라 둔다 — 일정 이름은 줄임 표로 맞춘다
                if compose.width(s) > w or s.endswith("…") or ("…" in s and ev["family"] == "E"):
                    bad.append(f"{ev['id']}/{extra.get('event_name') or tgt} {part} {compose.width(s):.1f}칸(한도 {w}): {s}")
    return bad


def main() -> int:
    bad = check()
    for b in bad:
        print(f"[글자 수] {b}")
    print(f"폰 알림 글자 수 {'넘침 ' + str(len(bad)) + '건' if bad else '0건. 통과'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
