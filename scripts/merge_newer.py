"""push 재시도 시 origin 의 더 새로운 시세를 되돌리지 않도록 data.json 을 병합한다.

사용: python scripts/merge_newer.py <run.json> <origin.json> <out.json>
규칙: run.json 이 기준. origin.lastUpdated 가 더 새로우면(=그 사이 경량 런이 푸시)
  - indices/fx/commodities: 심볼별로 origin 잎(leaf)을 채택(origin 에 없거나 stale 이면 run 유지)
  - history: origin 의 마지막 점이 run 보다 새 날짜면 그 점을 덧붙이고, 같은 날이면 origin 종가 채택
  - lastUpdated = 둘 중 큰 값, data_meta.json(out 옆)도 맞춰 다시 쓴다
토스 스냅샷 블록은 잎 단위가 아니라 자기 타임스탬프가 더 큰 쪽을 채택한다.
어떤 예외에도 run.json 을 그대로 out 에 쓰고 exit 0 (푸시가 막히면 안 된다).
ponytail: 잎에 개별 타임스탬프가 없어 lastUpdated 로 통째 비교 — 잎별 as_of 가 생기면 심볼 단위로 세분.
"""
import json
import os
import shutil
import sys
from datetime import datetime

SPOT = ("indices", "fx", "commodities")
HIST_SPOT = ("indices", "fx", "commodities")
# 블록 → 타임스탬프 필드 (토스 스냅샷 유래)
SNAP = {"stockFlows": "generatedAt", "rankingsKr": "as_of",
        "marketCalendarKr": "generatedAt", "investorTrading": "lastFetched"}
# rankingsKr 안의 KRX 4목록(2026-10) — 토스 칸과 원천·날짜가 달라 맨 위 as_of(토스 거래일)로 같이 고르면 안 된다
KRX_RANK = ("marketCap", "volume", "high52", "low52")


def _ts(v):
    try:
        d = datetime.fromisoformat(str(v))
        return d.timestamp() if d.tzinfo else d.replace(tzinfo=None).timestamp() - 9 * 3600  # KST 가정
    except Exception:
        return None


def _newer(a, b):
    """a 가 b 보다 확실히 새로우면 True."""
    ta, tb = _ts(a), _ts(b)
    return ta is not None and (tb is None or ta > tb)


def merge(run, origin):
    if _newer(origin.get("lastUpdated"), run.get("lastUpdated")):
        for k in SPOT:
            r, o = run.get(k), origin.get(k)
            if isinstance(r, dict) and isinstance(o, dict):
                for sym, leaf in o.items():
                    if isinstance(leaf, dict) and sym in r and not leaf.get("stale"):
                        r[sym] = leaf
        rh, oh = run.get("history"), origin.get("history")
        if isinstance(rh, dict) and isinstance(oh, dict):
            for k in HIST_SPOT:
                for sym, oarr in (oh.get(k) or {}).items():
                    rarr = (rh.get(k) or {}).get(sym)
                    if not (isinstance(rarr, list) and rarr and isinstance(oarr, list) and oarr):
                        continue
                    ol, rl = oarr[-1], rarr[-1]
                    if ol.get("date", "") == rl.get("date", ""):
                        rl["close"] = ol.get("close", rl.get("close"))
                    elif ol.get("date", "") > rl.get("date", ""):
                        rarr.extend(p for p in oarr if p.get("date", "") > rl.get("date", ""))
        run["lastUpdated"] = origin["lastUpdated"]
    for k, f in SNAP.items():
        r, o = run.get(k), origin.get(k)
        if isinstance(r, dict) and isinstance(o, dict) and _newer(o.get(f), r.get(f)):
            if k == "rankingsKr":
                # KRX 목록은 각자 as_of 로 고르고, 이 런이 일부러 안 실은 목록(52주 축적 중)은 origin 에서 되살리지 않는다
                o = {x: v for x, v in o.items() if x not in KRX_RANK}
                for x in KRX_RANK:
                    if isinstance(r.get(x), dict):
                        ox = origin[k].get(x)
                        o[x] = ox if isinstance(ox, dict) and _newer(ox.get("as_of"), r[x].get("as_of")) else r[x]
            run[k] = o
    return run


def main(run_p, origin_p, out_p):
    try:
        with open(run_p, encoding="utf-8") as f:
            run = json.load(f)
        with open(origin_p, encoding="utf-8") as f:
            origin = json.load(f)
        before = run.get("lastUpdated")
        merged = merge(run, origin)
        payload = json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
        with open(out_p, "w", encoding="utf-8") as f:
            f.write(payload)
        meta = {"lastUpdated": merged.get("lastUpdated"), "bytes": os.path.getsize(out_p)}
        with open(os.path.join(os.path.dirname(os.path.abspath(out_p)), "data_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        print(f"[merge_newer] 병합 완료 lastUpdated {before} → {merged.get('lastUpdated')}")
    except Exception as e:
        print(f"[merge_newer] 병합 실패 — run 산출물 그대로 사용: {e!r}")
        try:
            if os.path.abspath(run_p) != os.path.abspath(out_p):
                shutil.copyfile(run_p, out_p)
        except Exception as e2:
            print(f"[merge_newer] 복사도 실패: {e2!r}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
    sys.exit(0)
