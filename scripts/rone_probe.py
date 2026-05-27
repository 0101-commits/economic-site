#!/usr/bin/env python3
"""R-ONE 진단 v9 — throttle 적용 후 end-to-end 재검증.

fetch_realestate_kr() 를 실제 호출해 매매/전세(주택종합)/거래현황(행정구역별 아파트)/
미분양/착공이 모두 채워지는지 확인. 크래시 불가능.
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
    w(f"# R-ONE Probe v9 (end-to-end, throttle 적용) @ {datetime.datetime.utcnow().isoformat()}Z")
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
            w(f"  {k}: value={v.get('value')} chg={v.get('chg')} period={v.get('period')} "
              f"source={v.get('source')} histlen={len(v.get('history', {}))}")
        else:
            w(f"  {k}: (없음)")
    w("")
    trd = res.get("trade_count_kr_rone") or {}
    if trd.get("history"):
        ks = sorted(trd["history"].keys())[-5:]
        w("## 거래현황(전국 동(호)수) 최신: " + ", ".join(f"{k}={trd['history'][k]}" for k in ks))

except Exception:
    w("[FATAL]\n" + traceback.format_exc())
finally:
    flush()
