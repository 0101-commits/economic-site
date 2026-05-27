#!/usr/bin/env python3
"""R-ONE OpenAPI 연결 진단 v2 — '전국' CLS_ID 발견 + 최신값 조회 전략 검증.

1차 진단 결론:
  - DTACYCLE_CD=MM 이어야 데이터가 온다 (M 이면 INFO-200). [확정]
  - 그러나 SttsApiTblData 는 날짜범위를 무시하고 2003년부터 오래된 순으로 모든 지역을 반환.
  - '전국' 행을 앞쪽에서 못 찾아 최신 전국값 추출 실패.

v2 목적: 각 통계표에서
  A) CLS_NM=='전국' 인 행의 CLS_ID / ITM_ID 발견
  B) CLS_ID=<전국> 으로 재조회 시 전국 시계열(최신 포함)이 오는지 확인
  C) CLS_ID + 날짜범위 조합이 동작하는지 확인
  D) 정렬/페이지로 최신 period 를 얻는 방법 확인
"""
import os
import json
import datetime
import requests

KEY = os.environ.get("REALESTATE_API_KEY", "").strip() or "2e3efb261b524b8eacde37220a909655"
BASE = "https://www.reb.or.kr/r-one/openapi"
out = []
def w(s=""):
    out.append(str(s))

w(f"# R-ONE Probe v2 @ {datetime.datetime.utcnow().isoformat()}Z  key tail ...{KEY[-4:]}")
w("")


def get_rows(params):
    """SttsApiTblData 호출 → (rows, result_code, raw_first120)."""
    r = requests.get(f"{BASE}/SttsApiTblData.do", params={**params, "KEY": KEY},
                     timeout=30, headers={"User-Agent": "Mozilla/5.0 (rone-probe)"})
    try:
        j = r.json()
    except ValueError:
        return [], f"HTTP{r.status_code}/notjson", r.text[:120]
    if isinstance(j, dict) and j.get("RESULT"):
        return [], j["RESULT"].get("CODE", "?"), j["RESULT"].get("MESSAGE", "")[:60]
    env = j.get("SttsApiTblData") if isinstance(j, dict) else None
    rows = []
    if isinstance(env, list):
        for blk in env:
            if isinstance(blk, dict) and isinstance(blk.get("row"), list):
                rows = blk["row"]
    return rows, "INFO-000", f"{len(rows)}rows"


def analyze(statbl, label):
    w(f"===== {label}  STATBL_ID={statbl} =====")
    # A) 한 페이지(많은 지역) 받아 '전국' CLS_ID 찾기
    rows, code, msg = get_rows({"Type": "json", "pIndex": 1, "pSize": 400,
                                "STATBL_ID": statbl, "DTACYCLE_CD": "MM"})
    w(f"[A] pSize=400 → {code} {msg}")
    if not rows:
        w("    (행 없음 — 중단)")
        w("")
        return
    # 고유 CLS / ITM 수집
    cls_seen = {}
    itm_seen = {}
    nat_cls = None
    for r in rows:
        cid, cnm = r.get("CLS_ID"), r.get("CLS_NM")
        cfull = r.get("CLS_FULLNM")
        iid, inm = r.get("ITM_ID"), r.get("ITM_NM")
        if cid not in cls_seen:
            cls_seen[cid] = (cnm, cfull)
        if iid not in itm_seen:
            itm_seen[iid] = inm
        if cnm == "전국" or cfull == "전국":
            nat_cls = cid
    w(f"[A] 고유 CLS 수={len(cls_seen)}  고유 ITM={itm_seen}")
    w(f"[A] '전국' CLS_ID = {nat_cls}")
    # CLS_FULLNM 에 '>' 없는(상위 집계) 후보도 출력
    tops = {cid: nm for cid, (nm, full) in cls_seen.items()
            if full and ">" not in str(full)}
    w(f"[A] 최상위(집계) CLS 후보 (full에 '>' 없음): {dict(list(tops.items())[:12])}")
    period0 = rows[0].get("WRTTIME_IDTFR_ID")
    w(f"[A] 첫 행 period={period0} (오래된 순 정렬 확인용)")

    # B) 전국 CLS_ID 로 재조회 → 시계열 최신 확인
    if nat_cls is not None:
        rows2, code2, msg2 = get_rows({"Type": "json", "pIndex": 1, "pSize": 600,
                                       "STATBL_ID": statbl, "DTACYCLE_CD": "MM",
                                       "CLS_ID": nat_cls})
        w(f"[B] CLS_ID={nat_cls} pSize=600 → {code2} {msg2}")
        if rows2:
            # 전국만 왔는지 + 시계열 범위
            cls_in = {r.get("CLS_NM") for r in rows2}
            ps = sorted(r.get("WRTTIME_IDTFR_ID") for r in rows2 if r.get("WRTTIME_IDTFR_ID"))
            w(f"[B] 반환 CLS_NM 집합={list(cls_in)[:5]} (수 {len(cls_in)})  period {ps[0]}~{ps[-1]} (n={len(ps)})")
            last = rows2[-1]
            w(f"[B] 마지막 행: period={last.get('WRTTIME_IDTFR_ID')} CLS={last.get('CLS_NM')} ITM={last.get('ITM_NM')} VAL={last.get('DTA_VAL')}")
            # 최신 2개 period 의 전국 지수값
            recent = sorted([r for r in rows2 if r.get("CLS_NM") == "전국" or nat_cls == r.get("CLS_ID")],
                            key=lambda r: r.get("WRTTIME_IDTFR_ID", ""))[-3:]
            for r in recent:
                w(f"    최신: {r.get('WRTTIME_IDTFR_ID')} {r.get('ITM_NM')} = {r.get('DTA_VAL')}")
    # C) CLS_ID + 날짜범위 조합
    if nat_cls is not None:
        rows3, code3, msg3 = get_rows({"Type": "json", "pIndex": 1, "pSize": 24,
                                       "STATBL_ID": statbl, "DTACYCLE_CD": "MM", "CLS_ID": nat_cls,
                                       "WRTTIME_IDTFR_ID_FROM": "202401", "WRTTIME_IDTFR_ID_TO": "202612"})
        if rows3:
            ps = sorted(r.get("WRTTIME_IDTFR_ID") for r in rows3)
            w(f"[C] CLS_ID+날짜범위(202401~202612) → {code3} n={len(rows3)} period {ps[0]}~{ps[-1]}")
        else:
            w(f"[C] CLS_ID+날짜범위 → {code3} {msg3}")
    w("")


analyze("A_2024_00045", "매매 (월) 매매가격지수_아파트")
analyze("A_2024_00050", "전세 (월) 전세가격지수_아파트")

report = "\n".join(out)
with open("rone_probe_result.txt", "w", encoding="utf-8") as f:
    f.write(report + "\n")
print(report)
