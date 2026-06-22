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

    # ── [3차-T31] WARN 레벨 정확성 점검 (비차단) ─────────────────────────────
    # 왜: '치명적 결손' 게이트(아래 errs)와 별개로, 배포는 막지 않되 사람이 봐야 할
    # 데이터 품질 신호(오래된 시계열·결측·이상 급변·범위 이탈)를 Actions 로그에 남긴다.
    # 사이트의 '설정 → 시스템 진단'(T28)이 같은 규칙을 브라우저에서 수행해 이중 검증한다.
    warns = []

    def _check_series(label, seq, max_stale_days, jump_pct):
        if not seq:
            warns.append(f"{label}: 시계열 없음")
            return
        last = seq[-1] if isinstance(seq[-1], dict) else {}
        if isinstance(last.get("date"), str):
            try:
                stale = (datetime.now() - datetime.fromisoformat(last["date"])).days
                if stale > max_stale_days:
                    warns.append(f"{label}: 마지막 데이터가 {stale}일 전 ({last['date']})")
            except ValueError:
                warns.append(f"{label}: date 파싱 불가 ({last.get('date')!r})")
        closes = [p.get("close") for p in seq[-10:] if isinstance(p, dict) and isinstance(p.get("close"), (int, float))]
        nulls = sum(1 for p in seq[-30:] if not (isinstance(p, dict) and isinstance(p.get("close"), (int, float))))
        if nulls:
            warns.append(f"{label}: 최근 30포인트 중 결측 {nulls}건")
        for a, b in zip(closes, closes[1:]):
            if a and abs(b / a - 1) * 100 > jump_pct:
                warns.append(f"{label}: 일간 {abs(b / a - 1) * 100:.1f}% 급변 — 수집 오류 여부 확인 ({a} → {b})")
                break

    hist = d.get("history") or {}
    _check_series("history.indices.KOSPI", (hist.get("indices") or {}).get("KOSPI"), 5, 12)
    _check_series("history.indices.SP500", (hist.get("indices") or {}).get("SP500"), 5, 12)
    _check_series("history.fx.USDKRW",     (hist.get("fx") or {}).get("USDKRW"),     5, 6)

    # 절대 범위 sanity — 단위 실수(원↔달러 등)·소스 오염을 조기 감지
    usdkrw = ((d.get("fx") or {}).get("USDKRW") or {}).get("rate")
    if isinstance(usdkrw, (int, float)) and not (800 <= usdkrw <= 2500):
        warns.append(f"fx.USDKRW.rate={usdkrw} — 정상 범위(800~2,500) 이탈")

    # ENSO 실측 신선도 — 비차단 경고(배포는 막지 않음)
    enso = (d.get("climate") or {}).get("enso") or {}
    if enso and enso.get("stale", {}).get("oni") is True:
        warns.append("climate.enso.oni: 최신 ONI 수집 실패(직전값 사용 중)")

    # 기후→경제 영향 매핑(climate.impact) 구조 — 비차단 경고(블록이 있을 때만 점검)
    impact = (d.get("climate") or {}).get("impact") or {}
    if impact:
        if impact.get("activePhase") not in ("elnino", "lanina", "neutral"):
            warns.append(f"climate.impact.activePhase 이상값: {impact.get('activePhase')!r}")
        imap = impact.get("map")
        if not isinstance(imap, dict) or not imap.get(impact.get("activePhase")):
            warns.append("climate.impact.map 에 활성 국면 매핑 누락")

    for w in warns:
        print(f"::warning title=데이터 품질::{w}")

    if errs:
        print("❌ data.json 검증 실패:\n - " + "\n - ".join(errs))
        sys.exit(1)
    print(f"✅ data.json 검증 통과 (lastUpdated={ts}, KOSPI series={len(series)}, 품질경고 {len(warns)}건)")


if __name__ == "__main__":
    main()
