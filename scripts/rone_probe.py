#!/usr/bin/env python3
"""R-ONE 진단 v7 — 수정 코드(전세 주택종합 A_2024_00019 + 거래현황 A_2024_00549)의
end-to-end 검증. fetch_realestate_kr() 를 실제 호출해 결과를 기록. 크래시 불가능.
"""
import os
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
        print("write fail", e)
    print(rep)

try:
    import importlib.util
    import sys
    import types
    sys.modules.setdefault("yfinance", types.ModuleType("yfinance"))
    w(f"# R-ONE Probe v7 (end-to-end) @ {datetime.datetime.utcnow().isoformat()}Z")
    w(f"REALESTATE_API_KEY set={bool(os.environ.get('REALESTATE_API_KEY','').strip())}")
    w("")
    spec = importlib.util.spec_from_file_location("fd", "scripts/fetch_data.py")
    fd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fd)

    res = fd.fetch_realestate_kr() or {}
    w("## fetch_realestate_kr() 결과")
    for k in ("apt_price_idx_kr", "jns_price_idx_kr", "trade_count_kr_rone",
              "unsold_kr", "permit_kr", "start_kr", "complete_kr"):
        v = res.get(k)
        if isinstance(v, dict):
            hist = v.get("history", {})
            w(f"  {k}: value={v.get('value')} chg={v.get('chg')} period={v.get('period')} "
              f"source={v.get('source')} histlen={len(hist)} desc={v.get('desc')}")
        else:
            w(f"  {k}: (없음)")
    w("")
    # 전세(주택종합) 최신 3개월 시계열 확인
    jns = res.get("jns_price_idx_kr") or {}
    if jns.get("history"):
        ks = sorted(jns["history"].keys())[-4:]
        w("## 전세(주택종합) 최신 시계열: " + ", ".join(f"{k}={jns['history'][k]}" for k in ks))
    trd = res.get("trade_count_kr_rone") or {}
    if trd.get("history"):
        ks = sorted(trd["history"].keys())[-4:]
        w("## 거래현황(전국 동(호)수) 최신: " + ", ".join(f"{k}={trd['history'][k]}" for k in ks))

except Exception:
    w("[FATAL]\n" + traceback.format_exc())
finally:
    flush()
