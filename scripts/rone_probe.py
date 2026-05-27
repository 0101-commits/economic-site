#!/usr/bin/env python3
"""R-ONE 최종 검증 probe v4 — 수정된 fetch_realestate_kr() 를 실제 API 로 end-to-end 검증.

확인:
  1) fetch_realestate_kr() 가 CLS_ID=500001 경로로 매매/전세 전국 최신값·전월비·시계열을 뽑는지
  2) unsold/permit/start 전국 집계가 잡히는지
  3) 통계표 목록에서 '아파트 매매거래(호수)' 거래량 테이블 STATBL_ID 를 탐색 (거래 카드용)
모든 예외는 결과 파일에 기록하고 항상 exit 0.
"""
import os
import json
import datetime
import traceback

out = []
def w(s=""):
    out.append(str(s))

def flush():
    rep = "\n".join(out)
    try:
        open("rone_probe_result.txt", "w", encoding="utf-8").write(rep + "\n")
    except Exception as e:
        print("write fail:", e)
    print(rep)

try:
    import requests
    KEY = os.environ.get("REALESTATE_API_KEY", "").strip() or "2e3efb261b524b8eacde37220a909655"
    BASE = "https://www.reb.or.kr/r-one/openapi"
    w(f"# R-ONE Probe v4 @ {datetime.datetime.utcnow().isoformat()}Z key ...{KEY[-4:]}")
    w("")

    # 1) 수정된 fetch_realestate_kr() end-to-end
    w("## end-to-end fetch_realestate_kr() (수정 코드)")
    try:
        import importlib.util
        import types
        sys_mod = __import__("sys")
        sys_mod.modules.setdefault("yfinance", types.ModuleType("yfinance"))
        spec = importlib.util.spec_from_file_location("fd", "scripts/fetch_data.py")
        fd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fd)
        res = fd.fetch_realestate_kr()
        if not res:
            w("  (빈 결과)")
        for k, v in (res or {}).items():
            if isinstance(v, dict):
                w(f"  {k}: value={v.get('value')} chg={v.get('chg')} period={v.get('period')} "
                  f"source={v.get('source')} histlen={len(v.get('history', {}))} desc={v.get('desc')}")
    except Exception:
        w("EXC:\n" + traceback.format_exc())
    w("")

    # 2) 거래량(호수) 통계표 탐색 — 카탈로그 전체에서 이름으로 검색
    w("## 거래(호수/거래량) 통계표 탐색")
    try:
        r = requests.get(f"{BASE}/SttsApiTbl.do",
                         params={"KEY": KEY, "Type": "json", "pIndex": 1, "pSize": 800},
                         timeout=40, headers={"User-Agent": "Mozilla/5.0"})
        j = r.json()
        rows = []
        env = j.get("SttsApiTbl") if isinstance(j, dict) else None
        if isinstance(env, list):
            for blk in env:
                if isinstance(blk, dict) and isinstance(blk.get("row"), list):
                    rows = blk["row"]
        w(f"  통계표 총 {len(rows)}개 로드")
        hits = []
        for row in rows:
            nm = row.get("STATBL_NM", "") or ""
            if any(kw in nm for kw in ("매매거래", "거래현황", "거래량", "거래(호", "호수")):
                hits.append((row.get("STATBL_ID"), nm, row.get("DTACYCLE_CD")))
        for sid, nm, cyc in hits[:30]:
            w(f"    {sid}  [{cyc}]  {nm}")
        if not hits:
            w("    (이름 매칭 없음 — '아파트','주택' 키워드로 재검색)")
            for row in rows:
                nm = row.get("STATBL_NM", "") or ""
                if ("아파트" in nm and ("거래" in nm or "건수" in nm)):
                    w(f"    {row.get('STATBL_ID')}  [{row.get('DTACYCLE_CD')}]  {nm}")
    except Exception:
        w("EXC:\n" + traceback.format_exc())
    w("")

except Exception:
    w("[FATAL]\n" + traceback.format_exc())
finally:
    flush()
