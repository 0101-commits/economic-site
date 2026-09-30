#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""월 1회 데이터 건강 보고(A18) — data.json 의 dataHealth·diagnostics 를 #시스템 채널 1건으로.

지표 상태 분포 · 비정상 항목 · 원천별 실패 · 교차검증 일치율 · 토스 수집기 · 지난달 대비.
카드(PNG) 생성 실패 시 텍스트만 발송한다. 상태는 health_report_state.json 에 남겨 워크플로가 커밋한다.
  python scripts/health_report.py --dry-run   # 발송·상태 저장 없이 출력
"""
import datetime
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
STATE = os.path.join(ROOT, "scripts", "health_report_state.json")
# data.json state → 보고 라벨 (순서 = 표시 순서)
LABELS = [("정상", ("ok",)), ("지연", ("stale",)), ("보존", ("preserved",)),
          ("미확보", ("missing",)), ("검증 필요", ("failed", "unknown"))]
MAX_ITEMS = 15


def _load(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _label(path):
    """사람이 읽을 이름 — data_sla 에 라벨 함수(label_for)가 생기면 사용, 없으면 path."""
    try:
        import data_sla
        fn = getattr(data_sla, "label_for", None)
        return (fn(path) if fn else None) or path
    except Exception:
        return path


def collect(data, toss_snap=None):
    """data.json(+toss_snapshot) → 보고용 지표 dict. 누락 항목은 None/빈 값으로 방어."""
    items = (data.get("dataHealth") or {}).get("items") or []
    counts = {lab: sum(1 for i in items if i.get("state") in sts) for lab, sts in LABELS}
    ok_states = LABELS[0][1]
    bad = [i for i in items if i.get("state") not in ok_states]
    diag = data.get("diagnostics") or {}
    src = []
    for host, s in (diag.get("sourceStatus") or {}).items():
        calls, fails = s.get("calls") or 0, s.get("fails") or 0
        if fails:
            src.append({"host": host, "calls": calls, "fails": fails,
                        "pct": round(100 * fails / calls, 1) if calls else 100.0,
                        "run": s.get("consecutiveFailRuns") or 0})
    src.sort(key=lambda x: (-x["pct"], -x["fails"]))
    chk, mis = diag.get("investorCrossChecked"), diag.get("investorCrossMismatch")
    rate = round(100 * (chk - mis) / chk, 1) if chk and mis is not None else None
    fx = diag.get("fxTossCross") or {}
    t = diag.get("toss") or {}
    snap = toss_snap or {}
    return {
        "total": len(items), "counts": counts,
        "bad": [{"path": i["path"], "state": i["state"]} for i in bad],
        "sources": src, "hasSourceStatus": "sourceStatus" in diag,
        "crossRate": rate, "crossChecked": chk, "crossMismatch": mis,
        "fxDiffPct": fx.get("diffPct"),
        "toss": {"state": t.get("state"), "host": snap.get("host"),
                 "generatedAt": snap.get("generatedAt") or t.get("generatedAt")},
    }


def diff(cur, prev):
    """지난달 스냅샷 대비 변화. prev 없으면 None."""
    if not prev:
        return None
    pc = prev.get("counts") or {}
    pb = {b["path"] for b in prev.get("bad") or []}
    cb = {b["path"] for b in cur["bad"]}
    return {"counts": {k: cur["counts"][k] - pc.get(k, 0) for k in cur["counts"]},
            "new": sorted(cb - pb), "recovered": sorted(pb - cb), "month": prev.get("month")}


def _d(n):
    return f"{n:+d}" if n else "±0"


def build_text(cur, dif, month):
    L = [f"■ 지표 {cur['total']}개 상태 분포 ({month})"]
    L.append(" · ".join(f"{k} {v}" for k, v in cur["counts"].items()))
    L.append("")
    L.append(f"■ 비정상 항목 {len(cur['bad'])}건")
    for b in cur["bad"][:MAX_ITEMS]:
        st = next(lab for lab, sts in LABELS if b["state"] in sts)
        L.append(f"- {_label(b['path'])} : {st}")
    if len(cur["bad"]) > MAX_ITEMS:
        L.append(f"- 외 {len(cur['bad']) - MAX_ITEMS}건")
    if not cur["bad"]:
        L.append("- 없음")
    L.append("")
    L.append("■ 원천별 실패 상위 5")
    if not cur["hasSourceStatus"]:
        L.append("- 원천 집계 미수집")
    elif not cur["sources"]:
        L.append("- 실패 없음")
    for s in cur["sources"][:5]:
        L.append(f"- {s['host']} : {s['fails']}/{s['calls']}회 ({s['pct']}%) · 연속 실패 {s['run']}회")
    L.append("")
    L.append("■ 교차검증")
    if cur["crossRate"] is None:
        L.append("- 투자자 수급 일치율 : 집계 없음")
    else:
        ok = cur["crossChecked"] - cur["crossMismatch"]
        L.append(f"- 투자자 수급 일치율 : {cur['crossRate']}% ({ok}/{cur['crossChecked']})")
    if cur["fxDiffPct"] is not None:
        L.append(f"- 환율 토스 대비 차이 : {cur['fxDiffPct']}%")
    t = cur["toss"]
    L.append("")
    L.append(f"■ 토스 수집기 : {t['state'] or '미확인'} · 최근 스냅샷 {t['generatedAt'] or '없음'}"
             + (f" · host {t['host']}" if t["host"] else ""))
    L.append("")
    if dif is None:
        L.append("■ 지난달 대비 : 비교 기준 없음(첫 보고)")
    else:
        L.append(f"■ 지난달({dif['month']}) 대비")
        L.append(" · ".join(f"{k} {_d(v)}" for k, v in dif["counts"].items()))
        if dif["new"]:
            L.append("- 신규 비정상 : " + ", ".join(_label(p) for p in dif["new"][:8]))
        if dif["recovered"]:
            L.append("- 회복 : " + ", ".join(_label(p) for p in dif["recovered"][:8]))
    return "\n".join(L)


def build_card(cur, month):
    """상태 분포 막대 + 원천 실패 상위 5 — 실패 시 예외(호출부가 텍스트 폴백)."""
    import discord_card as DC
    plt, _ = DC._setup()
    fig = DC._sq_fig(plt, DC._L("데이터 건강 보고", "Data health"), month)
    n = max(cur["total"], 1)
    ax = fig.add_axes([0.20, 0.55, 0.72, 0.32])
    labs = list(cur["counts"])
    vals = [cur["counts"][k] for k in labs]
    en = ["OK", "Stale", "Preserved", "Missing", "Check"]
    ax.barh([DC._L(k, e) for k, e in zip(labs, en)][::-1], vals[::-1], color=DC.MUT)
    for y, v in enumerate(vals[::-1]):
        ax.text(v + n * 0.01, y, f"{v}", va="center", color=DC.INK, fontsize=DC._fs(14, True))
    ax.set_title(DC._L(f"지표 {cur['total']}개 상태", f"{cur['total']} metrics"), loc="left",
                 color=DC.INK, fontsize=DC._fs(15, True))
    ax2 = fig.add_axes([0.20, 0.12, 0.72, 0.30])
    top = cur["sources"][:5]
    if top:
        ax2.barh([DC._clip(fig, s["host"], 0.17, 12) for s in top][::-1],
                 [s["pct"] for s in top][::-1], color=DC.UP)
        for y, s in enumerate(top[::-1]):
            ax2.text(s["pct"] + 0.5, y, f"{s['pct']}%", va="center", color=DC.INK,
                     fontsize=DC._fs(13, True))
    else:
        ax2.text(0.5, 0.5, DC._L("원천 실패 없음/미집계", "no source failures"), ha="center",
                 color=DC.MUT, fontsize=DC._fs(15, True), transform=ax2.transAxes)
        ax2.set_xticks([]); ax2.set_yticks([])
    ax2.set_title(DC._L("원천별 실패율 상위 5", "Top-5 source failure %"), loc="left",
                  color=DC.INK, fontsize=DC._fs(15, True))
    for a in (ax, ax2):
        for sp in ("top", "right"):
            a.spines[sp].set_visible(False)
        a.tick_params(colors=DC.MUT, labelsize=DC._fs(12, True))
    return DC._save(fig, "health_report.png")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    dry = "--dry-run" in argv
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # 윈도 cp949 콘솔 깨짐 방지
    data = _load(os.path.join(ROOT, "data.json"), {})
    cur = collect(data, _load(os.path.join(ROOT, "toss_snapshot.json"), {}))
    month = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m")
    dif = diff(cur, _load(STATE))
    text = build_text(cur, dif, month)
    if dry:
        print(text)
        return 0
    png = None
    try:
        png = build_card(cur, month)
    except Exception as e:
        print(f"[health] 카드 생성 실패({type(e).__name__}: {e}) — 텍스트만 발송")
    import notify_discord as N
    c = cur["counts"]
    bad = c["지연"] + c["미확보"] + c["검증 필요"]
    ok = N.send(text[:3900], png=png, title=f"📋 월간 데이터 건강 보고 {month}",
                color=N.COLOR_SYSTEM if bad else N.COLOR_RESOLVE, timestamp=True,
                env="DISCORD_WEBHOOK_SYSTEM")
    print(f"[health] 발송 {'성공' if ok else '실패/미설정'}")
    # 발송 실패여도 상태는 남겨 다음 달 비교 기준을 유지한다.
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"month": month, "counts": c, "bad": cur["bad"], "crossRate": cur["crossRate"]},
                  f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
