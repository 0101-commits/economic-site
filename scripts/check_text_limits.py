#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T4 길이 상한 게이트 — 기획안 v4 10장 「화면 품질 게이트」 표.

글자 수는 파이썬 문자 수(한글 한 글자 = 1)로 센다.

  규칙                         대상                                          상한
  레지스트리 short             지표 레지스트리 JSON 의 short                  8자(모바일)
                               short_pc / shortPc                            12자
  이유 한 줄                   scripts/one_liners.py 의 문장 전부, 없으면      모바일 24자 / PC 44자
                               bundles/*.json 의 reason · line 필드           (한 값이 24~44면 PC 전용 경고 아님: 모바일 초과로 센다)
  버튼 바 항목                 bundles/*.json 의 bar / buttons 배열            항목 6자(모바일)/8자(PC), 개수 7개 이하
  알림 제목                    title_m 18자 · title 30자                      alerts*.json 또는 bundles/alerts*.json

대상 파일이 아직 없으면 「대상 없음」을 출력하고 통과(종료 코드 0)한다.
사용: python scripts/check_text_limits.py [--root .]
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import sys

ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else os.path.join(os.path.dirname(__file__), "..")
ROOT = os.path.abspath(ROOT)
sys.stdout.reconfigure(encoding="utf-8")
fails: list[str] = []
checked: dict[str, int] = {}


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


def limit(rule, where, text, mobile, pc=None):
    if not isinstance(text, str):
        return
    checked[rule] = checked.get(rule, 0) + 1
    n = len(text)
    if n > (pc if pc is not None else mobile):
        fails.append(f"{rule}: {where} {n}자 > {pc if pc is not None else mobile}자 「{text[:30]}」")
    elif pc is not None and n > mobile:
        fails.append(f"{rule}: {where} {n}자 > 모바일 {mobile}자(PC {pc}자는 만족) 「{text[:30]}」")


def json_files(*patterns):
    out = []
    for p in patterns:
        out += glob.glob(os.path.join(ROOT, p))
    return sorted(set(out))


# 1) 레지스트리 short
for f in json_files("indicators*.json", "bundles/indicators*.json", "bundles/registry*.json", "app/src/**/registry*.json"):
    def reg(where, k, v, f=f):
        if k == "short":
            limit("레지스트리 short", f"{os.path.basename(f)}{where}", v, 8)
        elif k in ("short_pc", "shortPc"):
            limit("레지스트리 short_pc", f"{os.path.basename(f)}{where}", v, 12)
    walk(load(f), reg)

# 2) 이유 한 줄: one_liners.py 가 있으면 그 문장들, 없으면 bundles 의 reason/line
ol = os.path.join(ROOT, "scripts", "one_liners.py")
if os.path.exists(ol):
    spec = importlib.util.spec_from_file_location("one_liners", ol)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def strings(o):
        if isinstance(o, str):
            yield o
        elif isinstance(o, dict):
            for v in o.values():
                yield from strings(v)
        elif isinstance(o, (list, tuple, set)):
            for v in o:
                yield from strings(v)

    for name in dir(mod):
        if name.startswith("_"):
            continue
        for s in strings(getattr(mod, name)):
            if len(s) >= 4 and not s.isascii():  # 한글 문장만(상수 키·경로 제외)
                limit("이유 한 줄", f"one_liners.{name}", s, 24, 44)
else:
    for f in json_files("bundles/*.json"):
        walk(load(f), lambda w, k, v, f=f: limit("이유 한 줄", f"{os.path.basename(f)}{w}/{k}", v, 24, 44)
             if k in ("reason", "line") else None)

# 3) 버튼 바
for f in json_files("bundles/*.json"):
    def bar(where, k, v, f=f):
        if k in ("bar", "buttons") and isinstance(v, list):
            checked["버튼 바 개수"] = checked.get("버튼 바 개수", 0) + 1
            if len(v) > 7:
                fails.append(f"버튼 바 개수: {os.path.basename(f)}{where}/{k} {len(v)}개 > 7개")
            for i, it in enumerate(v):
                lab = it if isinstance(it, str) else (it.get("label") if isinstance(it, dict) else None)
                limit("버튼 바 항목", f"{os.path.basename(f)}{where}/{k}[{i}]", lab, 6, 8)
    walk(load(f), bar)

# 4) 알림 제목
for f in json_files("alerts*.json", "bundles/alerts*.json"):
    def al(where, k, v, f=f):
        if k == "title_m":
            limit("알림 제목(모바일)", f"{os.path.basename(f)}{where}", v, 18)
        elif k == "title":
            limit("알림 제목(PC)", f"{os.path.basename(f)}{where}", v, 30)
    walk(load(f), al)

if not checked:
    print("[textlimits] 대상 없음 — 레지스트리·one_liners·bundles·alerts 파일 어디에도 검사할 필드가 아직 없다. 통과.")
    sys.exit(0)
print("[textlimits] 검사한 값: " + ", ".join(f"{k} {v}건" for k, v in checked.items()))
for m in fails:
    print("  위반 " + m)
print(f"위반 {len(fails)}건 → {'실패(종료 코드 1)' if fails else '통과'}")
sys.exit(1 if fails else 0)
