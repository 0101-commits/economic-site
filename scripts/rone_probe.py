#!/usr/bin/env python3
"""R-ONE 진단 v5 — 사용자 지정 통계표의 STATBL_ID/ITM_ID/전국값 발견.

찾을 표:
  - (월) 전세가격지수_주택종합   → 전세 카드 교체용
  - (월) 행정구역별 아파트거래현황 → 거래 카드 교체용 (전국 동(호)수 = 거래량)

방법: 통계표목록(SttsApiTbl)을 전부 받아 이름으로 매칭 → 각 후보를 CLS_ID=500001(전국)
으로 조회해 ITM 종류와 최신값을 확인한다. 크래시 불가능(traceback 기록) + 항상 결과 기록.
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
    import requests
    KEY = os.environ.get("REALESTATE_API_KEY", "").strip() or "2e3efb261b524b8eacde37220a909655"
    BASE = "https://www.reb.or.kr/r-one/openapi"
    UA = {"User-Agent": "Mozilla/5.0 (rone-probe)"}
    w(f"# R-ONE Probe v5 @ {datetime.datetime.utcnow().isoformat()}Z key ...{KEY[-4:]}")
    w("")

    def catalog():
        # pSize 가 크면(>~1000) 빈 응답 → 100씩 페이지네이션으로 전체 수집
        rows = []
        for pidx in range(1, 12):  # 최대 11*100=1100 > 738
            try:
                r = requests.get(f"{BASE}/SttsApiTbl.do",
                                 params={"KEY": KEY, "Type": "json", "pIndex": pidx, "pSize": 100},
                                 timeout=40, headers=UA)
                j = r.json()
                env = j.get("SttsApiTbl") if isinstance(j, dict) else None
                page = []
                if isinstance(env, list):
                    for blk in env:
                        if isinstance(blk, dict) and isinstance(blk.get("row"), list):
                            page = blk["row"]
                if not page:
                    break
                rows += page
                if len(page) < 100:
                    break
            except Exception:
                w(f"[catalog p{pidx} EXC] " + traceback.format_exc().splitlines()[-1])
                break
        return rows

    def get_rows(params):
        try:
            r = requests.get(f"{BASE}/SttsApiTblData.do", params={**params, "KEY": KEY},
                             timeout=40, headers=UA)
            j = r.json()
            if isinstance(j, dict) and j.get("RESULT"):
                return [], j["RESULT"].get("CODE", "?") + ":" + j["RESULT"].get("MESSAGE", "")[:40]
            env = j.get("SttsApiTblData") if isinstance(j, dict) else None
            if isinstance(env, list):
                for blk in env:
                    if isinstance(blk, dict) and isinstance(blk.get("row"), list):
                        return blk["row"], "OK"
        except Exception as e:
            return [], f"EXC:{type(e).__name__}"
        return [], "no-row"

    cat = catalog()
    w(f"## 통계표목록 {len(cat)}건 수신")
    keywords = ["전세가격지수_주택종합", "매매가격지수_주택종합", "전세가격지수", "매매가격지수",
                "행정구역별 아파트거래현황", "아파트거래현황", "아파트거래", "거래현황"]
    seen_print = set()
    found = {}  # 조회 대상(타깃)만
    target_kw = ("주택종합", "행정구역별", "거래현황", "아파트거래")
    for kw in keywords:
        ms = [(r.get("STATBL_ID"), r.get("STATBL_NM"), r.get("DTACYCLE_CD"))
              for r in cat if kw in str(r.get("STATBL_NM", ""))]
        w(f"\n### '{kw}' 매칭 {len(ms)}건")
        for sid, nm, cyc in ms[:20]:
            if sid not in seen_print:
                w(f"   {sid}  [{cyc}]  {nm}")
                seen_print.add(sid)
            if any(t in str(nm) for t in target_kw):
                found.setdefault(sid, nm)

    # 각 후보를 전국(CLS_ID=500001)으로 조회해 ITM/최신값 확인
    w("\n## 후보별 전국(CLS_ID=500001) 조회")
    for sid, nm in list(found.items())[:12]:
        rows, st = get_rows({"Type": "json", "pIndex": 1, "pSize": 30,
                             "STATBL_ID": sid, "DTACYCLE_CD": "MM", "CLS_ID": "500001"})
        w(f"\n### {sid} ({nm}) → {st}, n={len(rows)}")
        if rows:
            itms = {}
            for r in rows:
                itms.setdefault((r.get("ITM_ID"), r.get("ITM_NM"), r.get("UI_NM")), 0)
                itms[(r.get("ITM_ID"), r.get("ITM_NM"), r.get("UI_NM"))] += 1
            w(f"   ITM 종류: {dict(list(itms.items())[:8])}")
            ser = sorted([(r.get("WRTTIME_IDTFR_ID"), r.get("ITM_NM"), r.get("DTA_VAL"), r.get("CLS_NM"))
                          for r in rows], key=lambda t: (t[1] or "", t[0] or ""))
            for t in ser[-6:]:
                w(f"   최신: period={t[0]} CLS={t[3]} ITM={t[1]} VAL={t[2]}")

except Exception:
    w("[FATAL]\n" + traceback.format_exc())
finally:
    flush()
