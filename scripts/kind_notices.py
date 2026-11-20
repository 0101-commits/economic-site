#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""거래소 시장조치 공시(사이드카 · 서킷브레이커) — KRX KIND 「오늘의 공시」에서 읽는다.

왜: 사이드카 · 서킷 경보 34건 중 18건이 오보였다(10/1~11/20, 기획 4ioDhgSA ①). 뉴스 헤드라인 + 현물 ±2.5% 로
「발동」을 추정했기 때문이다. 이제 발동은 거래소 공시만 만든다.

읽는 길(리버스엔지니어링, GitHub 실행기에서 200 · 0.3~0.5초 실측):
  ① 목록  POST /disclosure/todaydisclosure.do  method=searchTodayDisclosureSub · selDate · 100건 · 최신순(HTML 표)
  ② 거르기 제출인 「유가증권시장본부 · 코스닥시장본부」 + 제목에 「발동」(사이드카 · CB)
  ③ 본문  disclsviewer.do?method=search&acptno → 문서 번호 → method=searchContents → /external/…htm
         발동 일시(초) · 선물(서킷은 지수) 현재가 · 기준가 · 등락률
같은 발동이 공시 두 줄로 나온 날이 있다(10/30) — 「시장 · 종류 · 방향 · 단계」가 같으면 하나로 친다(하루 한 번만 발동하는 조치다).
"""
import datetime as dt
import html
import re
import time
import urllib.parse
import urllib.request

KST = dt.timezone(dt.timedelta(hours=9))
BASE = "https://kind.krx.co.kr"
LIST = BASE + "/disclosure/todaydisclosure.do"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
OFFICES = {"유가증권시장본부": "KOSPI", "코스닥시장본부": "KOSDAQ"}
SIDECAR_MIN = 5          # 사이드카 = 프로그램 호가 5분 효력정지
CB_HALT_MIN = 20         # 서킷 1 · 2단계 = 20분 매매 중단(그 뒤 10분 단일가)


class ReadError(Exception):
    """목록을 못 읽음(접속 · 형식). 호출부는 「공시를 못 읽을 때」 규칙(D3)으로 간다."""


def _post(url: str, data: dict, timeout: float) -> str:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers={
        "User-Agent": UA, "X-Requested-With": "XMLHttpRequest", "Referer": LIST + "?method=searchTodayDisclosureMain"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _get(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
    for enc in ("utf-8", "cp949"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("utf-8", "replace")


def _cells(tr: str) -> list[str]:
    return [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split())
            for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]


def parse_list(page_html: str) -> list[dict]:
    """목록 HTML → [{time HH:MM, corp, title, by, acptno}] (최신순). 표가 아니면 ReadError."""
    if "openDisclsViewer" not in page_html and "<tr" not in page_html:
        raise ReadError("목록 표 없음")
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page_html, re.S):
        c = _cells(tr)
        acpt = re.findall(r"openDisclsViewer\('(\d+)'", tr)
        if len(c) >= 4 and re.fullmatch(r"\d{2}:\d{2}", c[0]):
            out.append({"time": c[0], "corp": c[1], "title": c[2], "by": c[3], "acptno": acpt[0] if acpt else ""})
    return out


def parse_title(title, by=None) -> dict | None:
    """시장조치 공시 제목 → {market, type, direction, stage}. 시장조치 발동이 아니면 None.

    예) 유가증권시장 매도 사이드카(Side car) 발동 · 코스닥시장 프로그램매수호가 일시효력정지(Sidecar 발동)
        유가증권시장 매매거래 일시중단(1단계 CB 발동) · 유가증권시장 매매거래 종료(3단계 CB 발동)"""
    t = str(title or "")
    if "발동" not in t:
        return None
    market = OFFICES.get(str(by or "").strip())
    if market is None:
        market = "KOSDAQ" if t.startswith("코스닥") else "KOSPI" if t.startswith("유가증권") else None
    if market is None:
        return None
    low = t.lower().replace(" ", "")
    if "sidecar" in low or "사이드카" in t:
        if "매도" in t:
            direction = "down"
        elif "매수" in t:
            direction = "up"
        else:
            return None
        return {"market": market, "type": "sidecar", "direction": direction, "stage": None}
    m = re.search(r"(\d)\s*단계\s*CB", t, re.I)
    if m:
        return {"market": market, "type": "circuit", "direction": "down", "stage": int(m.group(1))}
    return None


def _halt_id(typ: str, market: str, day: str) -> str:
    return f"{typ}-{market}-{day.replace('-', '')}"


def to_halt(row: dict, day: str, facts: dict | None = None) -> dict | None:
    """목록 행(+ 본문 사실) → market_halts 사건 dict(source krx). 시장조치가 아니면 None."""
    p = parse_title(row.get("title"), row.get("by"))
    if not p:
        return None
    facts = facts or {}
    at = facts.get("at")
    if not at:
        hh, mm = (int(x) for x in str(row.get("time") or "00:00").split(":"))
        y, mo, d = (int(x) for x in day.split("-"))
        at = dt.datetime(y, mo, d, hh, mm, tzinfo=KST)
    typ, stage = p["type"], p["stage"]
    eod = typ == "circuit" and stage == 3
    halt = SIDECAR_MIN if typ == "sidecar" else CB_HALT_MIN
    hid = _halt_id(typ, p["market"], day)
    if typ == "sidecar":
        hid += "-" + p["direction"]                   # 매수 · 매도 사이드카는 하루에 각각 한 번 — id 를 가른다
    return {
        "id": hid, "type": typ, "market": p["market"], "stage": stage, "direction": p["direction"],
        "reason": row.get("title"), "triggeredAt": at.isoformat(timespec="seconds"),
        "resumeAt": None if eod else (at + dt.timedelta(minutes=halt)).isoformat(timespec="seconds"),
        "endOfDay": eod, "source": "krx", "acptno": row.get("acptno") or "",
        "basePct": facts.get("pct"), "baseKind": facts.get("kind"),
    }


_NUM = r"(-?[\d,]+\.?\d*)"


def parse_body(text: str) -> dict:
    """본문 글 → {at: datetime(초), pct: 등락률, kind: 'fut'|'index'}. 못 찾은 칸은 뺀다."""
    out = {}
    m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s*(\d{1,2})시\s*(\d{1,2})분\s*(\d{1,2})초", text)
    m = m or re.search(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})", text)
    if m:
        out["at"] = dt.datetime(*(int(x) for x in m.groups()), tzinfo=KST)
    m = re.search(r"선물가격\s+" + r"\s+".join([_NUM] * 4), text)       # 코스닥: 구분 · 선물가격 · 현물지수
    if not m:
        m = re.search(r"등락율\s*\(%\)\s+" + r"\s+".join([_NUM] * 4), text)
    kind = "index" if "현재지수" in text else "fut"                    # 서킷 = 종합지수 · 사이드카 = 선물
    if m:
        try:
            out["pct"] = float(m.group(4).replace(",", ""))
            out["kind"] = kind
        except ValueError:
            pass
    return out


def body_facts(acptno: str, timeout: float = 8.0) -> dict:
    """공시 번호 → 본문 사실(parse_body). 실패하면 {}(목록 시각으로 간다)."""
    if not acptno:
        return {}
    try:
        v = _get(f"{BASE}/common/disclsviewer.do?method=search&acptno={acptno}&docno=&viewerhost=&viewerport=", timeout)
        m = re.search(r"<option value='(\d+)\|Y'", v)
        if not m:
            return {}
        c = _get(f"{BASE}/common/disclsviewer.do?method=searchContents&docNo={m.group(1)}", timeout)
        p = re.search(r"setPath\('[^']*','([^']+\.htm)'", c)
        if not p:
            return {}
        url = p.group(1) if p.group(1).startswith("http") else BASE + p.group(1)
        d = _get(url, timeout)
    except Exception as e:                                 # noqa: BLE001
        print(f"[kind] 본문 {acptno} 실패: {type(e).__name__}")
        return {}
    t = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", "", d)))
    return parse_body(" ".join(t.split()))


def recent(now: dt.datetime | None = None, lookback_min: int = 60, max_pages: int = 5,
           body_min: int = 20, timeout: float = 8.0) -> list[dict]:
    """오늘 공시 목록을 최신순으로 lookback_min 분 전까지 읽어 시장조치 사건만 돌려준다.

    body_min 분 안의 공시는 본문까지 읽어 발동 시각(초) · 등락률을 붙인다(오래된 것은 목록 시각만 — 이미 알린 사건).
    목록을 한 쪽도 못 읽으면 ReadError."""
    now = (now or dt.datetime.now(KST)).astimezone(KST)
    day = now.date().isoformat()
    cutoff = now - dt.timedelta(minutes=lookback_min)
    found, seen = {}, set()
    for page in range(1, max_pages + 1):
        try:
            s = _post(LIST, {
                "method": "searchTodayDisclosureSub", "currentPageSize": 100, "pageIndex": page, "orderMode": 0,
                "orderStat": "D", "marketType": "", "forward": "todaydisclosure_sub", "searchMode": "",
                "searchCodeType": "", "chose": "S", "todayFlag": "N", "repIsuSrtCd": "", "kosdaqSegment": "",
                "selDate": day, "searchCorpName": "", "copyUrl": ""}, timeout)
            rows = parse_list(s)
        except ReadError:
            if page == 1:
                raise
            break
        except Exception as e:                             # noqa: BLE001
            if page == 1:
                raise ReadError(f"{type(e).__name__}") from e
            break
        new = [r for r in rows if r["acptno"] not in seen]
        seen.update(r["acptno"] for r in rows)
        for r in new:
            h = to_halt(r, day)
            if not h:
                continue
            key = (h["market"], h["type"], h["direction"], h["stage"])
            if key in found:                               # 같은 발동의 중복 공시(10/30) — 이른 것 하나
                continue
            if dt.datetime.fromisoformat(h["triggeredAt"]) >= now - dt.timedelta(minutes=body_min):
                facts = body_facts(r["acptno"], timeout)
                if facts:
                    h = to_halt(r, day, facts)
            found[key] = h
        oldest = rows[-1]["time"] if rows else "00:00"
        hh, mm = (int(x) for x in oldest.split(":"))
        if not new or len(rows) < 100 or now.replace(hour=hh, minute=mm, second=0, microsecond=0) < cutoff:
            break
        time.sleep(0.3)
    return sorted(found.values(), key=lambda h: h["triggeredAt"])


if __name__ == "__main__":
    import json
    import sys
    when = dt.datetime.fromisoformat(sys.argv[1]).replace(tzinfo=KST) if len(sys.argv) > 1 else None
    print(json.dumps(recent(when, lookback_min=600, max_pages=12), ensure_ascii=False, indent=1))
