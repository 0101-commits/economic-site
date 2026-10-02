#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""디스코드 글자 한도 — fit() 단일 창구와, send() 의 모든 칸·embed 합(6,000)이 그걸 지나는지.

한도를 넘기면 디스코드는 400 으로 메시지를 통째로 거절한다. 종전 `[:4096]` 은 글자 중간에서 잘라
마크다운 링크가 깨지고 빠진 줄 고지가 없었다. 실행: python -m pytest scripts/tests/test_discord_limits.py -q
"""
import importlib.util
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))


def _fresh():
    # 다른 검사(test_check_alerts_prefs)가 공유 모듈의 send 를 갈아 끼우므로 따로 한 벌 읽는다
    spec = importlib.util.spec_from_file_location("nd_limits", os.path.join(HERE, "..", "notify_discord.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


nd = _fresh()
SENT = []
# 망을 타지 않게 이 사본의 urllib 만 바꾼다 — _post 가 실제로 보낼 본문을 받아 적는다
nd.urllib = types.SimpleNamespace(request=types.SimpleNamespace(
    Request=lambda url, data=None, headers=None: (url, data),
    urlopen=lambda req, timeout=None: SENT.append(json.loads(req[1]))))
nd._hook = lambda env: "https://hook.invalid/x"
nd._bot_token = lambda: ""


def _send(text, **kw):
    SENT.clear()
    assert nd.send(text, **kw) is True
    return SENT[-1]


def test_fit_keeps_whole_lines_and_counts_the_rest():
    lines = [f"{i:03d} " + "가" * 40 for i in range(200)]          # 줄당 44자
    out = nd.fit("\n".join(lines), 4096)
    assert len(out) <= 4096
    kept = out.split("\n")
    assert kept[:-1] == lines[:len(kept) - 1]                        # 앞줄은 통째로
    assert kept[-1] == lines[len(kept) - 1] + f" 외 {200 - len(kept)}항목"


def test_fit_short_text_and_blank_lines():
    assert nd.fit("a\n\nb", 10) == "a\n\nb"
    assert nd.fit(None, 10) == ""
    assert nd.fit("aaaa\n\n\n\n", 4) == "aaaa"                      # 남는 게 빈 줄뿐이면 꼬리표 없음
    assert nd.fit("aa\n\nbb\ncc", 8) == "aa 외 2항목"                # 빈 줄은 항목으로 세지 않는다


def test_fit_single_long_line_is_cut_with_ellipsis():
    out = nd.fit("x" * 300 + "\n둘째", 256)
    assert len(out) <= 256 and out.endswith("… 외 1항목")
    assert nd.fit("가" * 300, 256) == "가" * 255 + "…"


def test_send_embed_every_slot_within_limits():
    desc = "\n".join(f"[종목 {i}](https://finance.naver.com/item/main.naver?code={i:06d}) +{i}%" for i in range(120))
    p = _send(desc, title="제" * 300, fields=[("이" * 300, "\n".join("값" * 30 for _ in range(60)), False)],
              footer="꼬" * 2100)
    e = p["embeds"][0]
    assert len(e["title"]) <= 256 and len(e["description"]) <= 4096
    assert len(e["fields"][0]["name"]) <= 256 and len(e["fields"][0]["value"]) <= 1024
    assert len(e["footer"]["text"]) <= 2048
    assert e["description"].endswith("항목") and e["fields"][0]["value"].endswith("항목")
    # 링크 줄은 통째로 남는다(괄호가 열린 채 잘린 줄이 없다)
    assert all(ln.count("(") == ln.count(")") for ln in e["description"].split("\n"))


def test_send_embed_total_6000():
    desc = "\n".join("설" * 99 for _ in range(40))                  # 3,999자
    p = _send(desc, title="t", fields=[(f"f{i}", "v" * 1000, True) for i in range(3)], footer="ft")
    e = p["embeds"][0]
    total = len(e["title"]) + len(e["description"]) + len(e["footer"]["text"]) + sum(
        len(f["name"]) + len(f["value"]) for f in e["fields"])
    assert total <= 6000 and len(e["fields"]) == 3 and e["description"].endswith("항목")


def test_send_content_with_mention_within_2000():
    p = _send("\n".join("본" * 50 for _ in range(60)), mention=True)
    assert p["content"].startswith("@everyone ") and len(p["content"]) <= 2000
    assert p["content"].endswith("항목")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print("ok  " + t.__name__)
    print("%d개 통과" % len(tests))
