#!/usr/bin/env python3
"""GHA 러너에서 네이버 투자자별 매매동향 후보 엔드포인트 가용성 프로브 (임시 디버그용).

sise_index_buyer.naver 가 '표/컬럼 매핑 실패' 로 비는 원인을 파악하기 위해
각 후보 URL 의 HTTP 상태/본문 구조(표 헤더·샘플 행)를 로그로 덤프한다.
"""
import json
import re
from datetime import datetime, timedelta, timezone

import requests

KST = timezone(timedelta(hours=9))
HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Referer": "https://finance.naver.com/sise/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def dump_html(name, url, encoding="euc-kr"):
    print(f"\n{'='*80}\n[{name}] GET {url}")
    try:
        r = requests.get(url, headers=HDRS, timeout=15)
    except Exception as e:
        print(f"  요청 오류: {type(e).__name__}: {e}")
        return
    print(f"  status={r.status_code} bytes={len(r.content)} final_url={r.url}")
    r.encoding = encoding
    txt = r.text
    m = re.search(r"<title>(.*?)</title>", txt, re.S | re.I)
    print(f"  title={m.group(1).strip()[:120] if m else '(없음)'}")
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(txt, "html.parser")
    except Exception as e:
        print(f"  bs4 파싱 실패: {e}")
        print("  body[:800]:", txt[:800].replace("\n", " "))
        return
    tables = soup.find_all("table")
    print(f"  table 수={len(tables)}")
    for i, tbl in enumerate(tables):
        rows = tbl.find_all("tr")
        summary = (tbl.get("summary") or tbl.get("class") or "")
        print(f"  -- table[{i}] rows={len(rows)} attr={summary}")
        for tr in rows[:4]:
            cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
            if cells:
                print(f"     {cells[:12]}")
    body_txt = soup.get_text(" ", strip=True)
    print("  text[:500]:", body_txt[:500])


def dump_json(name, url, headers=None):
    print(f"\n{'='*80}\n[{name}] GET {url}")
    try:
        r = requests.get(url, headers=headers or HDRS, timeout=15)
    except Exception as e:
        print(f"  요청 오류: {type(e).__name__}: {e}")
        return
    print(f"  status={r.status_code} bytes={len(r.content)} ct={r.headers.get('content-type')}")
    try:
        j = r.json()
        print("  json:", json.dumps(j, ensure_ascii=False)[:1200])
    except Exception:
        print("  (JSON 아님) body[:400]:", r.text[:400].replace("\n", " "))


def main():
    now = datetime.now(KST)
    # 최근 평일 추정 (정확한 영업일이 아니어도 표 구조 확인에는 충분)
    d = now
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    bizdate = d.strftime("%Y%m%d")

    # 1) 기존 경로 — 현재 '표/컬럼 매핑 실패' 의 실체 확인
    dump_html("기존 sise_index_buyer KOSPI", "https://finance.naver.com/sise/sise_index_buyer.naver?code=KOSPI")

    # 2) 투자자별 매매동향 일별 표 (데스크톱 레거시)
    dump_html("investorDealTrendDay KOSPI", f"https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={bizdate}&sosok=01&page=1")
    dump_html("investorDealTrendDay KOSDAQ", f"https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={bizdate}&sosok=02&page=1")

    # 3) 모바일/신규 JSON API 후보
    mob_hdrs = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Referer": "https://m.stock.naver.com/domestic/index/KOSPI/total",
        "Accept": "application/json",
    }
    dump_json("m.stock index price", "https://m.stock.naver.com/api/index/KOSPI/price?pageSize=3&page=1", mob_hdrs)
    dump_json("m.stock investorDealTrend(추정)", "https://m.stock.naver.com/api/index/KOSPI/investorDealTrend?pageSize=5&page=1", mob_hdrs)
    dump_json("api.stock investor(추정)", "https://api.stock.naver.com/index/KOSPI/investor", mob_hdrs)
    dump_json("front-api investorDealTrend(추정)", "https://m.stock.naver.com/front-api/investorDealTrend/daily?category=KOSPI&pageSize=5&page=1", mob_hdrs)


if __name__ == "__main__":
    main()
