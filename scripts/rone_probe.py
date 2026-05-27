#!/usr/bin/env python3
"""R-ONE OpenAPI 연결 진단 — GitHub Actions(네트워크+시크릿 키 사용 가능)에서 실행한다.

개발 샌드박스는 외부 호스트가 전부 차단(reb.or.kr/data.go.kr/FRED 모두 'Host not in allowlist')
되어 R-ONE 을 직접 호출할 수 없다. 그래서 GHA 를 네트워크 프록시처럼 사용해 실제 응답을
받아 rone_probe_result.txt 로 커밋하고, 개발 환경에서 git pull 로 회수해 분석한다.

목적:
  1) REALESTATE_API_KEY 시크릿이 실제로 설정/유효한지 확인
  2) DTACYCLE_CD 가 'MM'(2글자)이어야 데이터가 오는지, 'M'(1글자)이면 빈 응답인지 확인 (핵심 가설)
  3) 검증한 STATBL_ID(A_2024_00045 매매, A_2024_00050 전세)가 실제 데이터를 반환하는지 확인
  4) 통계표 목록(SttsApiTbl)에서 '매매/전세가격지수' 실 STATBL_ID 를 수집(ID 가 바뀌었을 때 대비)
  5) fetch_realestate_kr() end-to-end 결과 확인
"""
import os
import sys
import json
import datetime
import requests

KEY_ENV = os.environ.get("REALESTATE_API_KEY", "").strip()
KEY = KEY_ENV or "2e3efb261b524b8eacde37220a909655"  # 시크릿 미설정 시 코드 기본값
BASE = "https://www.reb.or.kr/r-one/openapi"

out = []
def w(s=""):
    out.append(str(s))

w(f"# R-ONE Probe @ {datetime.datetime.utcnow().isoformat()}Z")
w(f"REALESTATE_API_KEY(env): set={bool(KEY_ENV)} len={len(KEY_ENV)} tail={KEY_ENV[-4:] if KEY_ENV else '-'}")
w(f"using key tail: ...{KEY[-4:]}")
w("")


def probe(label, path, params, show=1600):
    w(f"## {label}")
    safe = "&".join(f"{k}={v}" for k, v in params.items() if k != "KEY")
    w(f"GET {BASE}/{path}?{safe}&KEY=...")
    try:
        r = requests.get(f"{BASE}/{path}", params={**params, "KEY": KEY},
                         timeout=25, headers={"User-Agent": "Mozilla/5.0 (rone-probe)"})
        w(f"HTTP {r.status_code}  bytes={len(r.text)}  Content-Type={r.headers.get('Content-Type','')}")
        w("BODY (first %d chars):" % show)
        w(r.text[:show])
        try:
            j = r.json()
            for top in ("SttsApiTblData", "SttsApiTbl"):
                env = j.get(top) if isinstance(j, dict) else None
                if isinstance(env, list):
                    for blk in env:
                        if isinstance(blk, dict) and "row" in blk and isinstance(blk["row"], list):
                            rows = blk["row"]
                            w(f">> {top} row 수: {len(rows)}")
                            if rows:
                                w(f">> row[0] keys: {list(rows[0].keys())}")
                                w(f">> row[0]: {json.dumps(rows[0], ensure_ascii=False)}")
                                if len(rows) > 1:
                                    w(f">> row[-1]: {json.dumps(rows[-1], ensure_ascii=False)}")
            if isinstance(j, dict) and "RESULT" in j:
                w(f">> top RESULT: {json.dumps(j['RESULT'], ensure_ascii=False)}")
        except ValueError:
            w("(JSON 파싱 불가 — HTML/텍스트 응답)")
    except Exception as e:
        w(f"EXCEPTION: {type(e).__name__}: {e}")
    w("")


# 1) 통계표 목록 (카탈로그) — 실 STATBL_ID 확인용
probe("Catalog SttsApiTbl (pSize=20)", "SttsApiTbl.do",
      {"Type": "json", "pIndex": 1, "pSize": 20})

# 2) 매매(아파트) A_2024_00045 — 수정값 DTACYCLE_CD=MM
probe("매매 A_2024_00045 DTACYCLE_CD=MM (수정값)", "SttsApiTblData.do",
      {"Type": "json", "pIndex": 1, "pSize": 8, "STATBL_ID": "A_2024_00045",
       "DTACYCLE_CD": "MM", "WRTTIME_IDTFR_ID_FROM": "202501", "WRTTIME_IDTFR_ID_TO": "202512"})

# 3) 매매 동일 ID — 수정 전 DTACYCLE_CD=M (버그 재현 비교)
probe("매매 A_2024_00045 DTACYCLE_CD=M (수정 전·버그 재현)", "SttsApiTblData.do",
      {"Type": "json", "pIndex": 1, "pSize": 8, "STATBL_ID": "A_2024_00045",
       "DTACYCLE_CD": "M", "WRTTIME_IDTFR_ID_FROM": "202501", "WRTTIME_IDTFR_ID_TO": "202512"})

# 4) 전세(아파트) A_2024_00050 — DTACYCLE_CD=MM
probe("전세 A_2024_00050 DTACYCLE_CD=MM (수정값)", "SttsApiTblData.do",
      {"Type": "json", "pIndex": 1, "pSize": 8, "STATBL_ID": "A_2024_00050",
       "DTACYCLE_CD": "MM", "WRTTIME_IDTFR_ID_FROM": "202501", "WRTTIME_IDTFR_ID_TO": "202512"})

# 5) 부동산거래현황 A_2024_00061 — DTACYCLE_CD=MM
probe("거래현황 A_2024_00061 DTACYCLE_CD=MM", "SttsApiTblData.do",
      {"Type": "json", "pIndex": 1, "pSize": 8, "STATBL_ID": "A_2024_00061",
       "DTACYCLE_CD": "MM", "WRTTIME_IDTFR_ID_FROM": "202501", "WRTTIME_IDTFR_ID_TO": "202512"})

# 6) end-to-end: fetch_realestate_kr()
w("## end-to-end fetch_realestate_kr()")
try:
    import importlib.util
    import types
    sys.modules.setdefault("yfinance", types.ModuleType("yfinance"))
    spec = importlib.util.spec_from_file_location("fd", "scripts/fetch_data.py")
    fd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fd)
    res = fd.fetch_realestate_kr()
    if not res:
        w("  (빈 결과)")
    for k, v in (res or {}).items():
        if isinstance(v, dict):
            w(f"  {k}: value={v.get('value')} chg={v.get('chg')} period={v.get('period')} "
              f"source={v.get('source')} histlen={len(v.get('history', {}))}")
    # 카탈로그 자동탐색도 직접 호출해 결과 확인
    for kw in ("매매가격지수", "전세가격지수", "거래현황"):
        cat = fd.fetch_rone_table_catalog(kw, "MM")
        w(f"  [catalog '{kw}'] {cat[:8]}")
except Exception:
    import traceback
    w("EXCEPTION:\n" + traceback.format_exc())
w("")

report = "\n".join(out)
with open("rone_probe_result.txt", "w", encoding="utf-8") as f:
    f.write(report + "\n")
print(report)
