"""알림 v2 실행 — 모드별 추출 → 원장 → (ALERTS_V2=1) 구독 · 편성 · 발송 → latest.json.

  python scripts/alerts_v2/run.py --mode light|full|settle|daily|eve [--dry-run] [--now 2026-10-02T22:16+09:00]
  python scripts/alerts_v2/run.py --mode brief --slot morning|close|noon|evening|us|weekly [--dry-run]

물결 A 에서는 추출과 원장까지만 돈다. 구독(subscribe) · 편성(schedule) · 발송(deliver) 은 물결 B 가
모듈을 채우면 아래 `_pipeline_b` 가 그것을 부른다(없으면 건너뜀).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
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

try:                                                # 물결 A6 · A7 이 채우는 판정 모듈 — 하나가 없어도 다른 하나는 읽는다
    from alerts_v2 import judges_market  # noqa: F401,E402
except ImportError:
    pass
try:
    from alerts_v2 import judges_flow_cal  # noqa: F401,E402
except ImportError:
    pass


def _render(ctx):
    try:
        from alerts_v2 import compose
        return lambda ev, h: compose.render(ev, h, ctx)
    except ImportError:
        return None


def load_state(path: str) -> dict | None:
    """alerts_state.json — 없으면 빈 문서, 깨졌으면 None(U1 은 이번 런 판정하지 않고 파일도 안 쓴다)."""
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        print("[v2] alerts_state.json 을 읽지 못함 — U1(넘는 순간) 판정 건너뜀")
        return None
    return st if isinstance(st, dict) else None


def save_state(path: str, st: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:              # check_alerts._save_state 와 같은 모양
        json.dump(st, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _pipeline_b(ctx, new_rows, ledger, dry_run: bool, mode: str = ""):
    """ALERTS_V2=1 일 때만 구독 → 편성 → 발송. 모듈이 아직 없으면 조용히 건너뜀.

    U1(넘는 순간)의 직전 쪽은 alerts_state.json._prefs 에 남는다 — 그 파일을 커밋하는 stock-alerts(light)만 본다."""
    if os.environ.get("ALERTS_V2", "0") != "1":
        print(f"[v2] ALERTS_V2 꺼짐 — 원장만 기록({len(new_rows)}건)")
        return
    from alerts_v2 import deliver, schedule, subscribe
    events_by_id = schema.by_id(schema.load_events())
    prefs = subscribe.load_prefs()
    history = Ledger.load_days(8, end=ledger.day)          # 쿨다운 · 한 번 조건 판정용(오늘 포함)
    render = _render(ctx)
    path = os.path.join(ctx.root, "alerts_state.json")
    state = load_state(path) if mode == "light" else None
    sides = None
    if state is not None:
        sides = state["_prefs"] if isinstance(state.get("_prefs"), dict) else {}
        state["_prefs"] = sides
    before = json.dumps(sides, sort_keys=True)
    user_rows = subscribe.user_hits(ctx, prefs, history, render=render, sides=sides)
    if sides is not None and not dry_run and json.dumps(sides, sort_keys=True) != before:
        save_state(path, state)
    rows = [r.to_dict() if hasattr(r, "to_dict") else r for r in new_rows]
    for ur in user_rows:
        if ledger.append(ur):
            rows.append(ur)
    decisions = subscribe.match(rows, ctx, prefs, events_by_id)
    settings = (prefs or {}).get("settings")
    sends = schedule.plan(decisions, ledger, ctx, settings, events_by_id, history)
    print(f"[v2] 구독 {len(decisions)} → 발송 {len(sends)}" + (" (dry-run)" if dry_run else ""))
    for s in sends:
        if dry_run:
            print(f"[v2 dry-run] {s}")
        else:
            deliver.send(s, ledger, ctx)


BRIEF_SENT_MARKER = ".brief_sent_marker"            # briefing.yml 의 중복 발송 방지 캐시가 이 파일을 저장한다


def _brief(slot: str, now, dry_run: bool) -> int:
    """브리핑 한 통 — 추출 없음. ALERTS_V2=1 이고 --dry-run 이 아닐 때만 실제 발송, 아니면 드라이런 출력."""
    import send_kakao_digest as kakao
    from alerts_v2 import briefing, subscribe
    live = os.environ.get("ALERTS_V2", "0") == "1" and not dry_run
    ctx = Context.load(now=now)
    briefing.roll_calendar(ctx.data, now.astimezone(KST).date())   # 휴장 판정(kr_closed)이 보는 달력을 오늘로
    for fix in (kakao.apply_live_quotes, kakao.load_mri):   # 현행 다이제스트와 같은 발송 직전 보정(시세 · 리스크 지수)
        try:
            fix(ctx.data)
        except Exception as e:                                 # noqa: BLE001 — 보정 실패는 스냅샷 값으로 간다
            print(f"[v2 brief] {fix.__name__} 실패: {type(e).__name__}")
    settings = (subscribe.load_prefs() or {}).get("settings")
    res = briefing.send(slot, ctx, Ledger(day=now.astimezone(KST).date()), settings, dry_run=not live)
    if live:
        Ledger.rebuild_latest()
        if res["discord"] or res["push"] or res["kakao"]:     # 메모만 나간 건 성공이 아니다 — 두 번째 깨움이 다시 시도
            open(BRIEF_SENT_MARKER, "w").close()
    return 0


def missing_judges(todo) -> list[str]:
    """판정 함수가 없는 사건 id — 사용자 조건(judge user_*: U1 · U2, 사전 family 는 A)은 subscribe 가 판정하므로 뺀다."""
    return [ev["id"] for ev in todo if ev["judge"] not in JUDGES and not str(ev["judge"]).startswith("user_")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=[*schema.RUNS, "brief"])   # brief 는 평가 런(RUNS) 밖
    ap.add_argument("--slot", default=None, help="--mode brief 의 슬롯(morning · close · noon · evening · us · weekly)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", default=None, help="ISO 시각(검사용)")
    args = ap.parse_args(argv)

    now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(KST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    if args.mode == "brief":
        from alerts_v2.briefing import SLOTS
        if args.slot not in SLOTS:
            ap.error(f"--mode brief 에는 --slot {'|'.join(SLOTS)} 가 필요하다")
        return _brief(args.slot, now, args.dry_run)
    events = schema.load_events()
    todo = schema.for_run(events, args.mode)
    missing = missing_judges(todo)
    if missing:
        print(f"[v2] 판정 함수 미구현(건너뜀): {', '.join(missing)}")
    todo = [ev for ev in todo if ev["judge"] in JUDGES]      # 사용자 조건(U1 · U2)도 여기서 빠진다 — subscribe 가 판정
    ctx = Context.load(now=now)
    ledger = Ledger(day=now.astimezone(KST).date())
    new_rows = extract(ctx, todo, ledger, render=_render(ctx))
    print(f"[v2] {args.mode}: 사전 {len(todo)} 판정, 새 행 {len(new_rows)}")
    for r in new_rows:
        print(f"  + {r.key} [{r.level}] {r.title}")
    if args.mode == "daily":                         # 이력 1점 묶음(VKOSPI · 금 김프 · 운임 · LME · 폭 · 업종)의 하루치 적재
        history_sink.run(ctx, dry_run=args.dry_run)
    _pipeline_b(ctx, new_rows, ledger, args.dry_run, args.mode)
    if not args.dry_run:
        ledger.save()
        Ledger.rebuild_latest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
