"""알림 v2 실행 — 모드별 추출 → 원장 → (ALERTS_V2=1) 구독 · 편성 · 발송 → latest.json.

  python scripts/alerts_v2/run.py --mode light|full|settle|daily|eve [--dry-run] [--now 2026-10-02T22:16+09:00]

물결 A 에서는 추출과 원장까지만 돈다. 구독(subscribe) · 편성(schedule) · 발송(deliver) 은 물결 B 가
모듈을 채우면 아래 `_pipeline_b` 가 그것을 부른다(없으면 건너뜀).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # scripts/
if hasattr(sys.stdout, "reconfigure"):              # Windows 콘솔(cp949)에서 한글 · 대시 출력
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from alerts_v2 import history_sink, schema          # noqa: E402
from alerts_v2.context import KST, Context          # noqa: E402
from alerts_v2.events import JUDGES, extract        # noqa: E402
from alerts_v2.ledger import Ledger                 # noqa: E402

try:                                                # 물결 A6 · A7 이 채우는 판정 모듈
    from alerts_v2 import judges_market, judges_flow_cal  # noqa: F401,E402
except ImportError:
    pass


def _render():
    try:
        from alerts_v2 import compose
        return compose.render
    except ImportError:
        return None


def _pipeline_b(ctx, new_rows, ledger, dry_run: bool):
    """ALERTS_V2=1 일 때만 구독 → 편성 → 발송. 모듈이 아직 없으면 조용히 건너뜀."""
    if os.environ.get("ALERTS_V2", "0") != "1":
        print(f"[v2] ALERTS_V2 꺼짐 — 원장만 기록({len(new_rows)}건)")
        return
    try:
        from alerts_v2 import deliver, schedule, subscribe
    except ImportError as e:
        print(f"[v2] 발송 모듈 없음({e}) — 원장만 기록")
        return
    decisions = subscribe.match(new_rows, ctx)
    sends = schedule.plan(decisions, ledger, ctx)
    for s in sends:
        if dry_run:
            print(f"[v2 dry-run] {s}")
        else:
            deliver.send(s, ledger, ctx)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=list(schema.RUNS) if hasattr(schema, "RUNS") else
                    ["light", "full", "settle", "daily", "eve"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", default=None, help="ISO 시각(검사용)")
    args = ap.parse_args(argv)

    now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(KST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    events = schema.load_events()
    todo = schema.for_run(events, args.mode)
    missing = [ev["id"] for ev in todo if ev["judge"] not in JUDGES]
    if missing:
        print(f"[v2] 판정 함수 미구현(건너뜀): {', '.join(missing)}")
        todo = [ev for ev in todo if ev["judge"] in JUDGES]
    ctx = Context.load(now=now)
    ledger = Ledger(day=now.astimezone(KST).date())
    new_rows = extract(ctx, todo, ledger, render=_render())
    print(f"[v2] {args.mode}: 사전 {len(todo)} 판정, 새 행 {len(new_rows)}")
    for r in new_rows:
        print(f"  + {r.key} [{r.level}] {r.title}")
    if args.mode == "daily":                         # 이력 1점 묶음(VKOSPI · 금 김프 · 운임 · LME · 폭 · 업종)의 하루치 적재
        history_sink.run(ctx, dry_run=args.dry_run)
    _pipeline_b(ctx, new_rows, ledger, args.dry_run)
    if not args.dry_run:
        ledger.save()
        Ledger.rebuild_latest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
