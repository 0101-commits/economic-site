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
from types import SimpleNamespace

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


def _saved(p):
    """저장된 설정만 — updatedAt 이 없는 빈 문서(저장 전 · Worker 기본값)는 None(load_prefs 와 같은 규칙: 기본 설정으로 구독)."""
    return p if isinstance(p, dict) and p.get("updatedAt") else None


def _people(subscribe):
    """사람별 설정 → (마스터 uid, 마스터 prefs, [(멤버 uid, prefs)], 공개 기록을 정리해도 되는가).

    /prefs/all 을 못 읽었거나(None — 키 없음 · 실패 · 일부만) 마스터가 없으면 지금처럼 마스터 칸 하나(load_prefs)만,
    멤버 없음, 정리 안 함 — 일부만 읽힌 사람 합집합으로 지우면 남의 기록이 사라진다. 마스터 설정이 저장 전 빈 문서여도
    정리하지 않는다(종전 `prefs` 거짓이면 정리 안 함과 같다)."""
    people = subscribe.load_all_prefs()
    owner = next(((u, p) for u, r, p in people or [] if r == "owner"), None)
    if owner is None:
        if people is not None:
            print("[v2] 사람별 설정에 마스터가 없음 — 마스터 칸만 읽고 이번 런은 공개 기록을 정리하지 않음")
        return None, subscribe.load_prefs(), [], False
    prefs = _saved(owner[1])
    return owner[0], prefs, [(u, _saved(p)) for u, r, p in people if r == "member"], prefs is not None


def _keep_keys(subscribe, prefs, members) -> set | None:
    """지금 모든 사람의 공개 기록 키 합집합 — 마스터 조건 id(지금 키) + 멤버 state_key(조건 · 하루 울림 칸).
    소금이 없어 멤버 키를 못 만들면 None(정리하지 않는다)."""
    keep = {a.get("id") for a in (prefs or {}).get("alerts") or []}
    for uid, p in members:
        for cid in [a.get("id") for a in (p or {}).get("alerts") or []] + [subscribe.DAY_SLOT]:
            k = subscribe.state_key(uid, "member", cid)
            if k is None:
                return None
            keep.add(k)
    return keep


class _MemberBook:
    """멤버 편성용 일회용 원장 — 오늘 울린 수(공개 기록 @day 칸)만큼 「울림」 행을 채우고 쓰기는 버린다.
    schedule.plan 의 하루 상한 · 묶음을 그대로 쓰되 공개 원장 sent(마스터 발송 기록)는 건드리지 않는다."""

    def __init__(self, n: int):
        self.rows = [{"key": f"@rung{i}", "level": "alert", "sent": {"push": 1}} for i in range(n)]

    def update_sent(self, key, **sent) -> None:
        return None

    def get(self, key):
        return None


RING_LEVELS = ("alarm", "alert")


def _rung(s) -> int:
    """마스터 원장의 하루 울림 셈(schedule._ring_count_today)과 같게 — 행 등급이 경보 · 알림인 것, 묶음은 묶음 행 + 안의 행."""
    if s.kind == "bundle":
        return 1 + sum(1 for r in s.bundle if r.get("level") in RING_LEVELS)
    return 1 if s.row.get("level") in RING_LEVELS else 0


def _read_book(path: str) -> dict:
    """공개 기록 _prefs 읽기 전용(쓰지 않는 런의 멤버 하루 울림 수) — 없거나 깨졌으면 빈 것."""
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return {}
    p = st.get("_prefs") if isinstance(st, dict) else None
    return p if isinstance(p, dict) else {}


def _members_b(ctx, members, market, sides, events_by_id, cd_history, render, dry_run: bool, light: bool,
               deliver, schedule, subscribe) -> None:
    """멤버마다 판정(사용자 조건 · 시장 사건) → 그 사람 설정으로 편성 → 푸시만. 공개 원장 · 카톡은 건드리지 않는다.

    · 사용자 조건(U1 · U2 · 종목 B1)은 light 런 + 공개 기록을 읽은 런만, 키는 state_key(HMAC). 같은 발생 · 쿨다운은
      member_fresh(공개 기록 keys · ts · fd), 실제로 나간 것만 mark_member · post_fired(/fired).
    · 시장 사건 쿨다운 = 공개 원장에 같은 묶음 키 행이 있으면(누구에게 나갔든) 센다 — 원장 sent 는 마스터 것이라.
      사용자 조건 행(cond)은 빼서 마스터 조건이 멤버를 막지 않게.
    · 하루 상한 = 공개 기록 state_key(uid, member, @day) {d, n} — light 런만 고쳐 쓴다(다른 런은 읽기만, 그 런의 울림은 안 셈).
    · 한 사람의 오류는 그 사람만 건너뛴다 — 마스터 발송이 이미 끝났으니 여기서 런이 죽으면 원장이 저장되지 않아 다음 런이
      마스터에게 같은 알림을 또 보낸다.
    · 로그는 수만(uid · 제목 · 종목 없음 — Actions 로그는 공개다)."""
    env = SimpleNamespace(
        today=ctx.now.date().isoformat(), market=market, sides=sides, events_by_id=events_by_id, render=render,
        dry_run=dry_run, light=light, deliver=deliver, schedule=schedule, subscribe=subscribe,
        book=sides if sides is not None else _read_book(os.path.join(ctx.root, "alerts_state.json")),
        mem_hist=[dict(r, sent={"push": 1}) for r in cd_history if not r.get("cond")],
        write=light and sides is not None and not dry_run)
    n_dec = n_send = n_err = 0
    prev = getattr(ctx, "redact_codes", False)
    ctx.redact_codes = True                                # 멤버 종목 조회 실패 로그에 코드를 찍지 않는다
    try:
        for uid, prefs in members:
            try:
                d, s = _member_one(ctx, uid, prefs, env)
            except Exception as e:                         # noqa: BLE001 — 한 멤버의 오류가 마스터 원장 저장 · 다른 멤버를 막지 않게
                n_err += 1
                print(f"[v2] 멤버 1명 판정 · 발송 오류({type(e).__name__}) — 그 사람만 건너뜀")
                continue
            n_dec, n_send = n_dec + d, n_send + s
    finally:
        ctx.redact_codes = prev
    print(f"[v2] 멤버 {len(members)}명 · 구독 {n_dec} → 발송 {n_send}" + (f" · 오류 {n_err}명" if n_err else "")
          + (" (dry-run)" if dry_run else ""))


def _member_one(ctx, uid: str, prefs: dict | None, env) -> tuple[int, int]:
    """멤버 한 사람 — (구독 수, 발송 수). _members_b 의 규칙 그대로."""
    subscribe, deliver, sides = env.subscribe, env.deliver, env.sides
    key = (lambda cid: subscribe.state_key(uid, "member", cid))
    urows = []
    if env.light and sides is not None:
        urows = subscribe.user_hits(ctx, prefs, [], render=env.render, sides=sides, key=key)
        urows = subscribe.member_fresh(urows, prefs, sides, key, env.events_by_id, ctx.now)
    decisions = subscribe.match([dict(r) for r in env.market] + urows, ctx, prefs, env.events_by_id,
                                uid=uid, role="member")
    settings = dict((prefs or {}).get("settings") or {}, ringChannel="push")   # 멤버는 푸시만(카톡은 마스터 계정)
    day_k = key(subscribe.DAY_SLOT)
    rec = env.book.get(day_k) if day_k else None
    n0 = int(rec.get("n") or 0) if isinstance(rec, dict) and rec.get("d") == env.today else 0
    sends = env.schedule.plan(decisions, _MemberBook(n0), ctx, settings, env.events_by_id, env.mem_hist,
                              kakao_rings=False)
    n, n_send, sent_keys = n0, 0, set()
    for s in sends:
        s.uid = uid
        if env.dry_run:
            n_send += 1
            continue
        res = deliver.send_member(s, uid)
        went = bool(res["push"] or res["held"])
        if res["push"]:
            n_send += 1
            n += _rung(s)
        for r in (s.bundle if s.kind == "bundle" else [s.row]):
            if r.get("cond") and went:                     # 멤버 사용자 조건 — 공개 원장 대신 그 사람 칸(/fired)
                sent_keys.add(r["key"])
                lvl = (r.get("level") or s.level) if s.kind == "bundle" else s.level
                deliver.post_fired(uid, deliver.fired_item(r, lvl, held=bool(s.held)))
    if env.write:
        subscribe.mark_member(sides, prefs, urows, sent_keys, ctx.now, key)
        if day_k and n != n0:
            sides[day_k] = {"d": env.today, "n": n}
    return len(decisions), n_send


def _pipeline_b(ctx, new_rows, ledger, dry_run: bool, mode: str = "") -> dict | None:
    """ALERTS_V2=1 일 때만 구독 → 편성 → 발송. 모듈이 아직 없으면 조용히 건너뜀.

    사용자 조건(U1 · U2 · 종목 B1)은 light 런(stock-alerts)만 판정한다 — 그 런만 alerts_state.json 을 커밋하고(U1 의 직전 쪽 ·
    울림 기록), 풀 런(fetch-data)은 12~57분 늦은 원장으로 같은 조건을 또 보내며 푸시 재시도가 events/ 하루치를 덮는다.
    사람별(2026-10-27): 마스터는 종전 경로 그대로(공개 기록 키 = 조건 id, 원장 · 카톡), 그 뒤 멤버마다 _members_b.
    돌려주는 값 = 원장을 저장한 뒤에 쓸 alerts_state.json 문서(바뀌지 않았거나 드라이런 · light 밖이면 None)."""
    if os.environ.get("ALERTS_V2", "0") != "1":
        print(f"[v2] ALERTS_V2 꺼짐 — 원장만 기록({len(new_rows)}건)")
        return None
    from alerts_v2 import deliver, schedule, subscribe
    events_by_id = schema.by_id(schema.load_events())
    owner_uid, prefs, members, prune = _people(subscribe)
    # 쿨다운 · 한 번 조건 판정용(오늘 포함). 다시 켠 조건의 그 전 울림은 빼고 본다
    history = subscribe.since_arm(prefs, Ledger.load_days(8, end=ledger.day))
    # 편성 쿨다운은 사전의 가장 긴 쿨다운만큼 본다 — 8일 고정이라 C1 365일 · G1 · C8 30일이 사실상 8일이었다(2026-10-11 점검).
    # 사용자 조건(「한 번」)의 판정은 종전대로 8일 + 공개 기록(fired).
    longest = max([int((ev.get("cooldown") or {}).get("days") or 0) for ev in events_by_id.values()] + [8])
    cd_history = subscribe.since_arm(prefs, Ledger.load_days(min(longest, 400) + 1, end=ledger.day)) if longest > 8 else history
    render = _render(ctx)
    light = mode == "light"
    state = load_state(os.path.join(ctx.root, "alerts_state.json")) if light else None
    sides = None
    if state is not None:
        sides = state["_prefs"] if isinstance(state.get("_prefs"), dict) else {}
        state["_prefs"] = sides
    before = json.dumps(sides, sort_keys=True)
    if sides is not None and prune:                # 사람별 설정을 정상으로 읽은 런만 — 지운 조건의 기록을 정리(꺼 둔 조건은 남긴다)
        keep = _keep_keys(subscribe, prefs, members)   # 모든 사람의 지금 키 합집합 밖만(멤버 정리가 마스터 기록을 지우지 않게)
        if keep is None:
            print("[v2] ALERTS_STATE_SALT 없음 — 멤버 기록 키를 몰라 이번 런은 공개 기록을 정리하지 않음")
        else:
            for k in [k for k in sides if k not in keep]:
                del sides[k]
    user_rows = subscribe.user_hits(ctx, prefs, history, render=render, sides=sides) if light else []
    rows = [r.to_dict() if hasattr(r, "to_dict") else r for r in new_rows]
    market = [dict(r) for r in rows]               # 멤버 판정용 사본(시장 사건만 — 마스터 사용자 조건 행은 안 섞는다)
    added = [ur for ur in user_rows if ledger.append(ur)]
    rows += added
    decisions = subscribe.match(rows, ctx, prefs, events_by_id, uid=owner_uid, role="owner")
    settings = (prefs or {}).get("settings")
    ring_kakao = dry_run or (settings or {}).get("ringChannel") != "kakao" or deliver.kakao_rings()   # 메모 모드면 카톡은 안 울린다
    sends = schedule.plan(decisions, ledger, ctx, settings, events_by_id, cd_history, kakao_rings=ring_kakao)
    print(f"[v2] 구독 {len(decisions)} → 발송 {len(sends)}" + (" (dry-run)" if dry_run else ""))
    for s in sends:
        s.uid = owner_uid                          # 푸시 큐 항목에 마스터 uid(모르면 없음 = 마스터에게만)
        if dry_run:
            print(f"[v2 dry-run] {s}")
        else:
            deliver.send(s, ledger, ctx)
    subscribe.mark_sent(sides, prefs, added, ledger, ctx.now)
    if members:
        _members_b(ctx, members, market, sides, events_by_id, cd_history, render, dry_run, light,
                   deliver, schedule, subscribe)
    if sides is None or dry_run or json.dumps(sides, sort_keys=True) == before:
        return None
    return state


BRIEF_SENT_MARKER = ".brief_sent_marker"            # briefing.yml 의 중복 발송 방지 캐시가 이 파일을 저장한다


def _brief(slot: str, now, dry_run: bool) -> int:
    """브리핑 한 통 — 추출 없음. ALERTS_V2=1 이고 --dry-run 이 아닐 때만 실제 발송, 아니면 드라이런 출력."""
    import send_kakao_digest as kakao
    from alerts_v2 import briefing, subscribe
    live = os.environ.get("ALERTS_V2", "0") == "1" and not dry_run
    if os.environ.get("GITHUB_EVENT_NAME") in ("schedule", "repository_dispatch"):   # 자동 깨움만 — 수동 실행 · 로컬은 그대로
        late = briefing.late_min(slot, now)
        if late is None or late > briefing.LATE_MAX_MIN:
            print(f"[v2 brief] {slot} 정시({briefing.SLOT_AT[slot][0]:02d}:{briefing.SLOT_AT[slot][1]:02d}) 몫이 아님"
                  f"({'정시 전 · 다른 요일' if late is None else f'{late}분 늦음'}) — 보내지 않음")
            if late is not None:                       # 같은 날인데 마커가 없다 = 오늘 정시 발송이 안 됐다(꺼진 슬롯 · 휴장일 일 수도)
                print(f"::warning::브리핑 {slot} 오늘 정시 발송 마커 없음 — {late}분 늦은 예비 실행은 보내지 않음")
            return 0
    ctx = Context.load(now=now)
    briefing.roll_calendar(ctx.data, now.astimezone(KST).date())   # 휴장 판정(kr_closed)이 보는 달력을 오늘로
    for fix in (kakao.apply_live_quotes, kakao.load_mri):   # 현행 다이제스트와 같은 발송 직전 보정(시세 · 리스크 지수)
        try:
            fix(ctx.data)
        except Exception as e:                                 # noqa: BLE001 — 보정 실패는 스냅샷 값으로 간다
            print(f"[v2 brief] {fix.__name__} 실패: {type(e).__name__}")
    owner_uid, prefs, members, _prune = _people(subscribe)
    settings = (prefs or {}).get("settings")
    res = briefing.send(slot, ctx, Ledger(day=now.astimezone(KST).date()), settings, dry_run=not live,
                        uid=owner_uid, members=[(u, (p or {}).get("settings")) for u, p in members])
    if live:
        Ledger.rebuild_latest()
        # 메모만 나간 건 성공이 아니다 — 두 번째 깨움이 다시 시도. 마스터가 그 슬롯을 껐고 멤버만 받았으면 그것으로 성공
        # (마스터 실패 + 멤버 성공이면 마커 없음 — 두 번째 깨움이 마스터를 다시 시도하고 멤버는 한 번 더 받을 수 있다)
        if res["push"] or res["kakao"] or (not briefing.enabled(slot, settings) and res.get("members")):
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
    if args.mode == "daily":                         # 일일 런 = 그 시각의 풀 런 몫까지(Worker 가 09 · 16 · 22시엔 daily 만 깨운다)
        todo += schema.for_run(events, "full")
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
    state = _pipeline_b(ctx, new_rows, ledger, args.dry_run, args.mode)
    if not args.dry_run:
        ledger.save()
        Ledger.rebuild_latest()
        if state is not None:                        # 쪽 · 울림 기록은 원장을 저장한 뒤에만(발송 중 예외면 둘 다 그대로)
            save_state(os.path.join(ctx.root, "alerts_state.json"), state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
