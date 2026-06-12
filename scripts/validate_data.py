#!/usr/bin/env python3
"""
data.json 무결성 게이트 — fetch_data.py 산출물을 커밋 전에 검증한다.

왜: 외부 API 응답 포맷이 바뀌면 빈 배열/null 이 그대로 배포되어 위젯이 일제히 "—" 가
된다. 여기서 실패(exit 1)하면 워크플로가 커밋 단계 전에 중단되어 직전 정상 data.json 이
유지된다(fail-safe). 검증은 '치명적 결손'만 잡는다 — 개별 지표 일부 누락은 fetch_data.py
의 직전값 보존(preserve) 로직이 처리하므로 여기서 막지 않는다.

워크플로: .github/workflows/fetch-data.yml 의 커밋 step 직전에 실행.
"""
import json
import sys
from datetime import datetime

# 항상 존재해야 하는 최상위 키와 타입 — fetch_data.py build_data() 가 무조건 생성하는 골격
REQUIRED = {
    "lastUpdated": str,
    "fx":          dict,
    "indices":     dict,
    "commodities": dict,
    "history":     dict,
    "news":        dict,
}
MIN_SERIES_LEN = 5   # 핵심 시계열 최소 길이 — 전부 비면 실패 처리


def main():
    errs = []
    try:
        with open("data.json", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        print(f"❌ data.json 로드 실패: {e}")
        sys.exit(1)

    for k, t in REQUIRED.items():
        if k not in d:
            errs.append(f"missing key: {k}")
        elif not isinstance(d[k], t):
            errs.append(f"type mismatch: {k} (expected {t.__name__}, got {type(d[k]).__name__})")

    # lastUpdated 가 ISO 날짜로 파싱 가능한지
    ts = d.get("lastUpdated")
    if isinstance(ts, str):
        try:
            datetime.fromisoformat(ts)
        except ValueError:
            errs.append(f"lastUpdated not ISO format: {ts!r}")

    # 핵심 시계열 — KOSPI 일별 종가 (대시보드 메인 차트의 근간)
    series = ((d.get("history") or {}).get("indices") or {}).get("KOSPI") or []
    if len(series) < MIN_SERIES_LEN:
        errs.append(f"history.indices.KOSPI too short: {len(series)} (< {MIN_SERIES_LEN})")

    # 환율 — USDKRW 현재가가 존재해야 헤더/티커가 의미를 가진다
    if not (d.get("fx") or {}).get("USDKRW"):
        errs.append("fx.USDKRW missing/empty")

    # data_meta.json(프런트 경량 선조회용) 이 본체와 일치하는지
    try:
        with open("data_meta.json", encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("lastUpdated") != d.get("lastUpdated"):
            errs.append("data_meta.json lastUpdated mismatch with data.json")
    except (OSError, ValueError):
        errs.append("data_meta.json missing/unreadable (fetch_data.py 가 함께 생성해야 함)")

    if errs:
        print("❌ data.json 검증 실패:\n - " + "\n - ".join(errs))
        sys.exit(1)
    print(f"✅ data.json 검증 통과 (lastUpdated={ts}, KOSPI series={len(series)})")


if __name__ == "__main__":
    main()
