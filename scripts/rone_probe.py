#!/usr/bin/env python3
"""R-ONE 진단 v8 — A_2024_00549 (행정구역별 아파트거래현황) 격리 진단.

end-to-end 에서 거래현황만 '없음'. 단독 호출로 어떤 파라미터 조합이 전국 동(호)수를
주는지, 혹은 연결끊김인지 확인. 각 요청 3회 재시도. 크래시 불가능.
"""
import os
import time
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
    import requests
    KEY = os.environ.get("REALESTATE_API_KEY", "").strip() or "2e3efb261b524b8eacde37220a909655"
    URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
    UA = {"User-Agent": "Mozilla/5.0 (rone-probe)"}
    w(f"# R-ONE Probe v8 @ {datetime.datetime.utcnow().isoformat()}Z (A_2024_00549 격리)")
    w("")

    def call(params):
        for attempt in range(3):
            try:
                r = requests.get(URL, params={**params, "KEY": KEY}, timeout=30, headers=UA)
                try:
                    j = r.json()
                except ValueError:
                    return None, f"HTTP{r.status_code}/notjson:{r.text[:60]}"
                if isinstance(j, dict) and j.get("RESULT"):
                    return None, j["RESULT"].get("CODE") + ":" + j["RESULT"].get("MESSAGE", "")[:40]
                env = j.get("SttsApiTblData")
                if isinstance(env, list):
                    for blk in env:
                        if isinstance(blk, dict) and isinstance(blk.get("row"), list):
                            return blk["row"], "OK"
                return None, "no-row"
            except Exception as e:
                if attempt == 2:
                    return None, f"EXC:{type(e).__name__}"
                time.sleep(2 * (attempt + 1))
        return None, "fail"

    base = {"Type": "json", "pIndex": 1, "STATBL_ID": "A_2024_00549", "DTACYCLE_CD": "MM"}
    combos = [
        ("CLS=500001 + ITM=100001", {**base, "pSize": 20, "CLS_ID": "500001", "ITM_ID": "100001"}),
        ("CLS=500001 only",         {**base, "pSize": 30, "CLS_ID": "500001"}),
        ("ITM=100001 only",         {**base, "pSize": 30, "ITM_ID": "100001"}),
        ("raw (지역/항목 파악)",      {**base, "pSize": 500}),
    ]
    for label, params in combos:
        time.sleep(1.0)
        rows, st = call(params)
        w(f"## {label} → {st}, n={len(rows) if rows else 0}")
        if rows:
            # 고유 CLS / ITM
            cls = {}
            itm = {}
            for r in rows:
                cls.setdefault((r.get("CLS_ID"), r.get("CLS_NM")), 0)
                cls[(r.get("CLS_ID"), r.get("CLS_NM"))] += 1
                itm.setdefault((r.get("ITM_ID"), r.get("ITM_NM"), r.get("UI_NM")), 0)
                itm[(r.get("ITM_ID"), r.get("ITM_NM"), r.get("UI_NM"))] += 1
            w(f"   CLS 종류({len(cls)}): {dict(list(cls.items())[:10])}")
            w(f"   ITM 종류: {dict(list(itm.items())[:6])}")
            # 전국(또는 합계) + 동(호)수 행의 최신 몇 개
            nat = [r for r in rows if str(r.get("CLS_NM")) in ("전국", "합계")
                   and "동" in str(r.get("ITM_NM", ""))]
            for r in sorted(nat, key=lambda x: x.get("WRTTIME_IDTFR_ID", ""))[-5:]:
                w(f"   최신: {r.get('WRTTIME_IDTFR_ID')} CLS={r.get('CLS_NM')} ITM={r.get('ITM_NM')} VAL={r.get('DTA_VAL')}")
        w("")

except Exception:
    w("[FATAL]\n" + traceback.format_exc())
finally:
    flush()
