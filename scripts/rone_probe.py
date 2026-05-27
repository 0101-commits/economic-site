#!/usr/bin/env python3
"""R-ONE OpenAPI 연결 진단 v3 — 크래시 불가능(traceback 기록) + 전국 CLS_ID 발견 + 조회전략 검증.

v2 가 try/except 누락으로 예외 시 종료코드 1 로 죽어 결과를 못 남겼다.
v3 는 어떤 예외가 나도 rone_probe_result.txt 에 traceback 까지 기록하고 항상 exit 0.

확인 목표:
  - DTACYCLE_CD=MM 필수(=핵심 근본원인) 재확인
  - 각 통계표의 '전국' CLS_ID 발견 (API 가 모든 지역을 오래된 순으로 주므로 전국 필터 필요)
  - CLS_ID=<전국> 조회 시 전국 시계열(최신 포함)이 오는지 + 최신 지수/전월비 확인
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
        with open("rone_probe_result.txt", "w", encoding="utf-8") as f:
            f.write(rep + "\n")
    except Exception as e:
        print("write fail:", e)
    print(rep)

try:
    import requests
    KEY = os.environ.get("REALESTATE_API_KEY", "").strip() or "2e3efb261b524b8eacde37220a909655"
    BASE = "https://www.reb.or.kr/r-one/openapi"
    w(f"# R-ONE Probe v3 @ {datetime.datetime.utcnow().isoformat()}Z  key tail ...{KEY[-4:]}  env_set={bool(os.environ.get('REALESTATE_API_KEY','').strip())}")
    w("")

    def get_rows(params, tag=""):
        """SttsApiTblData 호출 → (rows, code, msg). 예외도 안전 처리."""
        try:
            r = requests.get(f"{BASE}/SttsApiTblData.do", params={**params, "KEY": KEY},
                             timeout=40, headers={"User-Agent": "Mozilla/5.0 (rone-probe)"})
        except Exception as e:
            return [], "EXC", f"{type(e).__name__}: {e}"
        try:
            j = r.json()
        except ValueError:
            return [], f"HTTP{r.status_code}", "notjson:" + r.text[:80]
        if isinstance(j, dict) and j.get("RESULT"):
            return [], j["RESULT"].get("CODE", "?"), j["RESULT"].get("MESSAGE", "")[:50]
        env = j.get("SttsApiTblData") if isinstance(j, dict) else None
        rows = []
        if isinstance(env, list):
            for blk in env:
                if isinstance(blk, dict) and isinstance(blk.get("row"), list):
                    rows = blk["row"]
        return rows, "INFO-000", f"{len(rows)}rows"

    def analyze(statbl, label):
        w(f"===== {label}  STATBL_ID={statbl} =====")
        try:
            # A) 한 페이지 받아 '전국' CLS_ID 찾기 (pSize 충분히 — 한 시점의 모든 지역 포함)
            rows, code, msg = get_rows({"Type": "json", "pIndex": 1, "pSize": 500,
                                        "STATBL_ID": statbl, "DTACYCLE_CD": "MM"}, "A")
            w(f"[A] pSize=500 → {code} {msg}")
            if not rows:
                w("    (행 없음 — 중단)\n")
                return
            cls_seen, itm_seen, nat_cls = {}, {}, None
            for r in rows:
                cid, cnm, cfull = r.get("CLS_ID"), r.get("CLS_NM"), r.get("CLS_FULLNM")
                iid, inm = r.get("ITM_ID"), r.get("ITM_NM")
                cls_seen.setdefault(cid, (cnm, cfull))
                itm_seen.setdefault(iid, inm)
                if cnm == "전국" or cfull == "전국":
                    nat_cls = cid
            w(f"[A] 고유 CLS 수={len(cls_seen)}  ITM={itm_seen}  첫행 period={rows[0].get('WRTTIME_IDTFR_ID')}")
            w(f"[A] '전국' CLS_ID = {nat_cls}")
            tops = {cid: nm for cid, (nm, full) in cls_seen.items() if not full or ">" not in str(full)}
            w(f"[A] 최상위(집계) CLS 후보: {dict(list(tops.items())[:15])}")

            # B) 전국 CLS_ID 로 재조회 → 최신 시계열 확인
            if nat_cls is not None:
                rows2, code2, msg2 = get_rows({"Type": "json", "pIndex": 1, "pSize": 800,
                                               "STATBL_ID": statbl, "DTACYCLE_CD": "MM",
                                               "CLS_ID": nat_cls}, "B")
                w(f"[B] CLS_ID={nat_cls} pSize=800 → {code2} {msg2}")
                if rows2:
                    cls_in = sorted({str(r.get("CLS_NM")) for r in rows2})
                    ser = sorted([(r.get("WRTTIME_IDTFR_ID"), r.get("ITM_NM"), r.get("DTA_VAL"))
                                  for r in rows2 if r.get("WRTTIME_IDTFR_ID")], key=lambda t: t[0])
                    w(f"[B] 반환 CLS_NM={cls_in[:6]}  기간 {ser[0][0]}~{ser[-1][0]} (n={len(ser)})")
                    for t in ser[-4:]:
                        w(f"    최신: period={t[0]} ITM={t[1]} VAL={t[2]}")
                    # 최신 2개로 전월비(%) 계산
                    idx = [(p, v) for (p, i, v) in ser if isinstance(v, (int, float))]
                    if len(idx) >= 2:
                        (p1, v1), (p0, v0) = idx[-1], idx[-2]
                        chg = round((v1 - v0) / v0 * 100, 2) if v0 else None
                        w(f"[B] >>> 최신 전국 지수={v1} ({p1}), 전월={v0} ({p0}), 전월비={chg}% <<<")
            else:
                w("[A] 전국 CLS_ID 못 찾음 — 최상위 후보로 재시도 필요")
        except Exception:
            w("[EXC in analyze]\n" + traceback.format_exc())
        w("")

    analyze("A_2024_00045", "매매 (월) 매매가격지수_아파트")
    analyze("A_2024_00050", "전세 (월) 전세가격지수_아파트")

except Exception:
    w("[FATAL]\n" + traceback.format_exc())
finally:
    flush()
