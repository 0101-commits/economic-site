#!/usr/bin/env python3
"""GHA 러너에서 수정된 fetch_naver_investor_trading() 실동작 검증 (임시 디버그용).

sise_index_buyer.naver 404 → investorDealTrendDay.naver 교체 후, 실제 수집
결과(일수·범위·샘플 행)를 로그로 덤프해 data.json 에 실릴 형태를 확인한다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_data import fetch_naver_investor_trading  # noqa: E402


def main():
    res = fetch_naver_investor_trading(lookback_days=400)
    daily = res.get("daily", [])
    print(f"\n수집 일수: {len(daily)}  markets={res.get('markets')}  unit={res.get('unit')}")
    if daily:
        print(f"범위: {daily[0]['date']} ~ {daily[-1]['date']}")
        print("최신 5일:")
        for row in daily[-5:]:
            print(" ", json.dumps(row, ensure_ascii=False))
    if not daily:
        sys.exit(1)


if __name__ == "__main__":
    main()
