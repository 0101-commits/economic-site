#!/usr/bin/env python3
"""화면 금지어 검사 — 용어 정제(2026-10-30, 기획서 EiKJcHkR 판 2)에서 바꾼 말이 화면 글자로 되돌아오지 않게 막는다.

화면에 보이는 글자만 본다: 태그 사이 글자와 한글이 든 따옴표 문자열. 주석 · console.* 줄은 뺀다.
어쩔 수 없이 남겨야 하는 줄은 줄 끝에 `term-ok` 를 적는다(이유를 같은 줄 주석에).

실행: python scripts/check_terms.py        (위반이 있으면 exit 1)
      python scripts/check_terms.py --list (위반 줄 전부)
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["index.html"] + [f"js/app{n}.js" for n in range(0, 8)]

# 금지어 → 쓸 말. 정규식이다(같은 말이 다른 뜻으로 쓰이는 낱말은 앞뒤 문맥까지 적었다).
BANNED = {
    r"프록시 미설정": "알림 서버 연결 안 됨",
    r"폴백": "다른 자료 대체",
    r"쿨다운": "「30초에 한 번」 · 「일시 중지」",
    r"레이트\s?리밋": "요청 과다",
    r"파싱": "읽지 못함",
    r"IndexedDB|localStorage": "빼기(「본 브라우저」)",
    r"data\.json": "빼기",
    r"pykrx": "거래소 자료",
    r"정적 스냅샷": "자동 갱신 불가한 저장값",
    r"전년동기비|전년동월비|전년비(?!교)": "전년 대비",   # 「전년비교」(비교 단추)는 다른 말
    r"전월비": "전월 대비",
    r"전기비": "전기 대비",
    r"(?<![A-Za-z])(YoY|MoM)(?![A-Za-z])": "전년 대비 · 전월 대비",
    r"예측값": "컨센서스",
    r"이전값": "직전",
    r"실제값": "발표값",
    r"매크로 서프라이즈": "「컨센서스보다 0.2%p 높음」",
    r"호재|악재": "사실만(높음 · 낮음)",
    r"트리거 (래더|레벨|모니터)": "경보 단계",
    r"위젯": "필드",
    r"(코드|또는|미국)\s*/?\s*티커": "종목 코드",
    r"클릭하여": "빼기",
    r"참고용 대표 데이터": "빼기",
}
_BAN = [(re.compile(k), v) for k, v in BANNED.items()]
_TEXT = re.compile(r">([^<>{}]*[가-힣][^<>{}]*)<|(['\"`])((?:(?!\2)[^\\\n]|\\.)*?[가-힣](?:(?!\2)[^\\\n]|\\.)*?)\2")
_LINE_COMMENT = re.compile(r"(^|[^:'\"`\\])//.*$")
_CONSOLE = re.compile(r"console\.(log|warn|error|info|debug)\(")
_ALIASES = re.compile(r'"aliases": \[[^\]]*\]')   # 생성물(app0)의 옛 이름 — ECON_IND.find('옛 이름') 용이라 화면 글자가 아니다


def _strip_block_comments(src):
    """주석 블록을 같은 줄 수의 빈 줄로 바꾼다(줄 번호 유지)."""
    blank = lambda m: "\n" * m.group(0).count("\n")   # noqa: E731
    return re.sub(r"<!--[\s\S]*?-->", blank, re.sub(r"/\*[\s\S]*?\*/", blank, src))


def scan(path):
    src = _strip_block_comments(open(path, encoding="utf-8").read())
    out = []
    for no, line in enumerate(src.split("\n"), 1):
        if "term-ok" in line or _CONSOLE.search(line):
            continue
        line = _ALIASES.sub("", _LINE_COMMENT.sub(r"\1", line))
        for m in _TEXT.finditer(line):
            # 객체 열쇠('미국 CPI (전월비)': …)는 화면 글자가 아니다 — 줄 머리 · { · , 뒤에 오고 : 가 따라온다
            if m.group(3) is not None and re.match(r"\s*:(?!:)", line[m.end():]) \
                    and re.search(r"(^|[{,])\s*$", line[:m.start()]):
                continue
            t = (m.group(1) or m.group(3) or "").strip()
            for rx, repl in _BAN:
                hit = rx.search(t)
                if hit:
                    out.append((no, hit.group(0), repl, t[:80]))
    return out


def main():
    # pre-commit 훅은 윈도 콘솔(cp949)에서 돈다 — 한글 · 기호 출력이 막히면 검사 대신 인코딩 오류로 멈춘다
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    show_all = "--list" in sys.argv
    total = 0
    for f in FILES:
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            continue
        hits = scan(p)
        total += len(hits)
        for no, word, repl, text in hits if show_all else hits[:5]:
            print(f"{f}:{no}: 「{word}」 → {repl}  |  {text}")
        if hits and not show_all and len(hits) > 5:
            print(f"{f}: … 외 {len(hits) - 5}줄 (--list 로 전부)")
    print(f"화면 금지어 {total}건" + ("" if total else ". 통과"))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
