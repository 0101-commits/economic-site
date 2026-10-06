#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T4 길이 상한 게이트 — 기획안 v4 10장 「화면 품질 게이트」 표.

길이는 표시 폭으로 잰다 — 한글·한자 1칸, 영문·숫자·기호·공백 반 칸(one_liners.width 하나).
글자 수로 재면 「유로 GDP 성장률」이 10자로 모바일 8칸을 넘는 것처럼 보이지만 화면 폭은 7.5칸이다.

**상한 표는 이 파일의 LIMITS 한 곳에만 있다.** one_liners(이유 한 줄)·build_bundles(줄임 이름)가 여기서 가져간다.

  규칙            대상                                                 모바일 / PC
  줄임 이름        bundles/registry*.json 의 shortM(모바일) · short(PC)   8 / 12칸
  이유 한 줄       bundles/*.json 의 reasonShort·line.mobile·todayLine.mobile(모바일)
                  reason·line.pc·todayLine.pc(PC), one_liners.py 의 문장 상수   24 / 44칸
  버튼 바 항목     bundles/*.json 의 bar / buttons 배열(개수 7개 이하)       6 / 8칸
  알림 제목        alerts*.json 의 title_m(모바일) · title(PC)             18 / 30칸
  알림 항목(v2)    events/*.json 원장 행의 title(제목 30칸 · 브리핑 48칸) ·
                  why · next(본문 한 줄 40칸 — 푸시 본문은 두 줄 40×2) ·
                  buttons(버튼 8칸). 카톡 버튼 글자는 보낼 때 만들어져(deliver.kakao_parts) 행에는 없다

대상 파일이 아직 없으면 「대상 없음」을 출력하고 통과(종료 코드 0)한다.
사용: python scripts/check_text_limits.py [--root .]
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import sys

# (모바일, PC) 칸. 이 표가 단일 원천이다 — 다른 파일에 숫자를 다시 적지 말 것.
LIMITS = {
    "short": (8, 12),
    "reason": (24, 44),
    "button": (6, 8),
    "alert_title": (18, 30),
    "alert_line": (40, 40),      # 원장 본문 한 줄(why · next). 푸시 본문 = 두 줄이라 40×2
}
BUTTON_MAX_COUNT = 7
BRIEF_TITLE_MAX = 48             # 브리핑(level brief) 제목 상한(계약서 「제목 ≤30자(브리핑 48 상한)」)


def main(argv):
    root = os.path.abspath(argv[argv.index("--root") + 1] if "--root" in argv
                           else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    sys.stdout.reconfigure(encoding="utf-8")
    fails: list[str] = []
    checked: dict[str, int] = {}

    # 폭 자 = one_liners.width (--root 쪽 파일을 읽는다 — 그 저장소의 자로 잰다)
    spec = importlib.util.spec_from_file_location("one_liners", os.path.join(root, "scripts", "one_liners.py"))
    ol = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ol)
    width = ol.width

    def load(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def walk(node, fn, where=""):
        """JSON 을 돌며 (경로, 키, 값) 마다 fn 호출."""
        if isinstance(node, dict):
            for k, v in node.items():
                fn(where, k, v)
                walk(v, fn, f"{where}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, fn, f"{where}[{i}]")

    def limit(rule, where, text, cap):
        if not isinstance(text, str):
            return
        checked[rule] = checked.get(rule, 0) + 1
        n = width(text)
        if n > cap:
            fails.append(f"{rule}: {where} {n:g}칸 > {cap}칸 「{text[:30]}」")

    def json_files(*patterns):
        out = []
        for p in patterns:
            out += glob.glob(os.path.join(root, p))
        return sorted(set(out))

    # 1) 줄임 이름 — shortM 이 모바일, short 가 PC(옛 이름 short_pc·shortPc 도 PC 로 본다)
    m_short, pc_short = LIMITS["short"]
    for f in json_files("indicators*.json", "bundles/indicators*.json", "bundles/registry*.json"):
        def reg(where, k, v, f=f):
            if k == "shortM":
                limit("줄임 이름(모바일)", f"{os.path.basename(f)}{where}", v, m_short)
            elif k in ("short", "short_pc", "shortPc"):
                limit("줄임 이름(PC)", f"{os.path.basename(f)}{where}", v, pc_short)
        walk(load(f), reg)

    # 2) 이유 한 줄 — 묶음이 실제로 낸 문장 + one_liners 의 문장 상수
    m_rs, pc_rs = LIMITS["reason"]
    for f in json_files("bundles/*.json"):
        def rs(where, k, v, f=f):
            at = f"{os.path.basename(f)}{where}/{k}"
            if k == "reason":
                limit("이유 한 줄(PC)", at, v, pc_rs)
            elif k == "reasonShort":
                limit("이유 한 줄(모바일)", at, v, m_rs)
            elif k in ("line", "todayLine") and isinstance(v, dict):
                limit("이유 한 줄(PC)", at + ".pc", v.get("pc"), pc_rs)
                limit("이유 한 줄(모바일)", at + ".mobile", v.get("mobile"), m_rs)
        walk(load(f), rs)

    def strings(o):
        if isinstance(o, str):
            yield o
        elif isinstance(o, dict):
            for v in o.values():
                yield from strings(v)
        elif isinstance(o, (list, tuple, set)):
            for v in o:
                yield from strings(v)

    for name in dir(ol):
        if name.startswith("_"):
            continue
        for s in strings(getattr(ol, name)):
            if len(s) >= 4 and not s.isascii():          # 한글 문장만(상수 키·경로 제외)
                limit("이유 한 줄(문장 상수)", f"one_liners.{name}", s, pc_rs)

    # 3) 버튼 바
    m_bt, _pc_bt = LIMITS["button"]          # 묶음의 버튼은 이름 하나를 두 폭에 다 쓴다 → 모바일 상한으로 잰다
    for f in json_files("bundles/*.json"):
        def bar(where, k, v, f=f):
            if k in ("bar", "buttons") and isinstance(v, list):
                checked["버튼 바 개수"] = checked.get("버튼 바 개수", 0) + 1
                if len(v) > BUTTON_MAX_COUNT:
                    fails.append(f"버튼 바 개수: {os.path.basename(f)}{where}/{k} {len(v)}개 > {BUTTON_MAX_COUNT}개")
                for i, it in enumerate(v):
                    lab = it if isinstance(it, str) else (it.get("label") if isinstance(it, dict) else None)
                    limit("버튼 바 항목", f"{os.path.basename(f)}{where}/{k}[{i}]", lab, m_bt)
        walk(load(f), bar)

    # 4) 알림 제목
    m_al, pc_al = LIMITS["alert_title"]
    for f in json_files("alerts*.json", "bundles/alerts*.json"):
        def al(where, k, v, f=f):
            if k == "title_m":
                limit("알림 제목(모바일)", f"{os.path.basename(f)}{where}", v, m_al)
            elif k == "title":
                limit("알림 제목(PC)", f"{os.path.basename(f)}{where}", v, pc_al)
        walk(load(f), al)

    # 5) 알림 v2 원장 행 — 제목 30 · 본문(왜 · 다음) 한 줄 40. 일별 파일과 latest.json 모두(같은 행이 두 곳에 있어도 각자 잰다).
    ln = LIMITS["alert_line"][1]
    for f in json_files("events/*.json"):
        rows = load(f)
        for i, r in enumerate(rows if isinstance(rows, list) else []):
            if not isinstance(r, dict):
                continue
            at = f"{os.path.basename(f)}[{i}]"
            limit("알림 제목(원장)", f"{at}.title", r.get("title"), BRIEF_TITLE_MAX if r.get("level") == "brief" else pc_al)
            limit("알림 본문(왜)", f"{at}.why", r.get("why"), ln)
            limit("알림 본문(다음)", f"{at}.next", r.get("next"), ln)
            for j, b in enumerate(r.get("buttons") or []):      # 카톡 버튼은 8자(카카오 상한) — PC 상한과 같다
                limit("알림 버튼(원장)", f"{at}.buttons[{j}]", b if isinstance(b, str) else (b.get("label") if isinstance(b, dict) else None), LIMITS["button"][1])

    if not checked:
        print("[textlimits] 대상 없음 — 레지스트리·one_liners·bundles·alerts 파일 어디에도 검사할 필드가 아직 없다. 통과.")
        return 0
    print("[textlimits] 검사한 값: " + ", ".join(f"{k} {v}건" for k, v in checked.items()))
    for msg in fails:
        print("  위반 " + msg)
    print(f"위반 {len(fails)}건 → {'실패(종료 코드 1)' if fails else '통과'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
