"""판정 함수 — D 수급 · E 일정 · F 공시 · G 렌즈 · H 실물(H2~H4). 계약서 과제 A7.

「어제 상태」는 원장(`Ledger.load_days`) 이나 data 안의 history 로만 본다 — 새 상태 파일은 없다.
같은 자료 시점(asOf)으로 이미 원장에 들어간 key 는 다시 내지 않는다(`_unseen`) — 휴장일 저녁 런이
금요일 수급으로, 다음 날 런이 같은 월간 값으로 또 울리지 않게. 값 · 날짜는 데이터에서만, 없으면 빈 목록.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re

from .context import KST, Context, _get
from .events import Hit, judge
from .ledger import Ledger, make_key

try:                                             # 과제 A3 의 발표 시각 가드 — 합쳐지기 전엔 아래 같은 규칙
    from check_releases import release_due as _release_due_a3
except ImportError:
    _release_due_a3 = None

WHO = {"foreign": "외국인", "inst": "기관", "retail": "개인"}
FINAL_HOUR = 18          # KRX 확정 — 이 시각(KST) 전의 오늘 행은 장중 잠정치(check_alerts.KRX_FINAL_HOUR 와 같은 규칙)
STALE_DAYS = 7           # 마지막 행이 이보다 묵으면 수집이 멎은 것 — 판정하지 않는다(check_alerts 와 같은 규칙)
LOOKBACK_DAYS = 400      # 원장 이력을 보는 기간(F1 접수번호 · 월간 값)
SIDO = {"11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주", "30": "대전", "31": "울산",
        "36": "세종", "41": "경기", "42": "강원", "43": "충북", "44": "충남", "45": "전북", "46": "전남",
        "47": "경북", "48": "경남", "50": "제주"}
VIEW_KO = {2: "강한 긍정", 1: "긍정", 0: "중립", -1: "부정", -2: "강한 부정"}
ENSO_KO = {"elnino": "엘니뇨", "lanina": "라니냐", "neutral": "중립"}
KIND_KO = {"earnings": "실적", "dividend": "배당"}
MRI_PARTS = {"thresholdsCrossed": "임계 돌파", "negativeStance30d": "부정 입장", "riskFlags30d": "위험 신호"}
MEETING = {"ff_target": "FOMC", "base_rate_kr": "금통위"}      # 정책금리 → 일정표 회의 이름에 든 글자


# ── 공통 ────────────────────────────────────────────────────────────────
def _today(ctx: Context) -> dt.date:
    return ctx.now.astimezone(KST).date()


def _d(s) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _pdate(k) -> dt.date | None:
    """기간 키 → 날짜: 'YYYY-MM-DD' · 'YYYY-MM' · 'YYYYMM' · 'YYYYQn'."""
    k = str(k)
    if m := re.fullmatch(r"(\d{4})Q([1-4])", k):
        return dt.date(int(m[1]), int(m[2]) * 3 - 2, 1)
    if m := re.fullmatch(r"(\d{4})-?(\d{2})", k):
        return dt.date(int(m[1]), int(m[2]), 1)
    return _d(k)


def _period_ko(k) -> str:
    k = str(k)
    if re.fullmatch(r"\d{6}", k):
        return f"{k[:4]}-{k[4:]}"
    if re.fullmatch(r"\d{4}-\d{2}-01", k):
        return k[:7]
    return k


def _md(d: dt.date) -> str:
    return f"{d.month}/{d.day}"


def _num(x):
    """'+2.1%' · '1,465K' · -0.7 → float. 못 읽으면 None."""
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"[-+]?\d[\d,]*\.?\d*", str(x))
    try:
        return float(m.group(0).replace(",", "")) if m else None
    except ValueError:
        return None


def _fresh(as_of: dt.date | None, today: dt.date) -> str:
    if as_of is None:
        return "missing"
    if as_of >= today:
        return "live"
    return "prev" if (today - as_of).days <= STALE_DAYS else "stale"


def _eok(x) -> str:
    """억원 → 「−2,040억」 · 「−7.9조」 · 「+3조」."""
    if x is None:
        return ""
    sign = "−" if x < 0 else "+"
    a = abs(x)
    if a >= 10000:
        return f"{sign}{a / 10000:.1f}".rstrip("0").rstrip(".") + "조"
    return f"{sign}{a:,.0f}억"


def _dir_ko(sell: bool) -> str:
    return "순매도" if sell else "순매수"


def _target(ev: dict, default: str) -> str:
    return (ev.get("targets") or [default])[0]


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _ledger_rows(ctx: Context) -> list[dict]:
    """원장 이력(최근 LOOKBACK_DAYS) — 런 한 번에 한 번만 읽는다."""
    rows = ctx.__dict__.get("_a7_rows")
    if rows is None:
        rows = Ledger.load_days(LOOKBACK_DAYS, end=_today(ctx), root=os.path.join(ctx.root, "events"))
        ctx.__dict__["_a7_rows"] = rows
    return rows


def _event_rows(ctx: Context, eid: str) -> list[dict]:
    return [r for r in _ledger_rows(ctx) if r.get("event") == eid]


def _unseen(ctx: Context, ev: dict, hits: list[Hit]) -> list[Hit]:
    """원장 이력에 같은 key(= 같은 자료 시점) 가 있으면 뺀다."""
    seen = {r.get("key") for r in _event_rows(ctx, ev["id"])}
    return [h for h in hits if make_key(ev["id"], h.target, h.dir, h.asOf) not in seen]


def _baseline(ctx: Context, ev: dict, hits: list[Hit]) -> list[Hit]:
    """원장에 이 사건 행이 하나도 없으면(첫 런) 지금 상태는 「새로 바뀐 것」이 아니라 기준선 — 기록 등급으로만 남긴다.
    ponytail: 400일 동안 한 번도 안 걸린 사건의 다음 첫 건도 기록으로 내려간다(드묾)."""
    if not _event_rows(ctx, ev["id"]):
        for h in hits:
            h.fields["level"] = "record"
    return hits


def _streak(vals: list[float]) -> int:
    """끝에서부터 같은 부호가 이어진 수."""
    n = 0
    for x in reversed(vals):
        if (x > 0) != (vals[-1] > 0):
            break
        n += 1
    return n


# ── D 수급(코스피 확정치) ────────────────────────────────────────────────
def _flow(ctx: Context, who: str) -> list[tuple]:
    """investorTrading.daily → [(날짜, 행, who 값)] 시간순. 18시 전 오늘 행 · 0 · 결측 제외,
    마지막 행이 7일 넘게 묵었으면 [] (check_alerts 의 flow 판정 규칙 승계)."""
    today = _today(ctx)
    provisional = ctx.now.astimezone(KST).hour < FINAL_HOUR
    out = []
    for r in (ctx.data.get("investorTrading") or {}).get("daily") or []:
        if not isinstance(r, dict):
            continue
        d, v = _d(r.get("date")), _num(r.get(who))
        if d is None or not v or d > today or (provisional and d == today):
            continue
        out.append((d, r, v))
    out.sort(key=lambda t: t[0])
    if not out or (today - out[-1][0]).days > STALE_DAYS:
        return []
    return out


def _supporter(row: dict, who: str, v: float) -> str:
    """그날 반대 부호로 가장 크게 받은 주체 이름. 없으면 빈칸."""
    opp = [(abs(x), k) for k in WHO if k != who and (x := _num(row.get(k))) and x * v < 0]
    return WHO[max(opp)[1]] if opp else ""


def _flow_hit(ctx, ev, rows, fields) -> Hit:
    d, _, v = rows[-1]
    return Hit(target=_target(ev, "kospi"), dir="sell" if v < 0 else "buy", value=v, unit="억",
               asOf=d.isoformat(), fresh=_fresh(d, _today(ctx)), fields=fields)


@judge("flow_streak_start")
def flow_streak_start(ctx: Context, ev: dict) -> list[Hit]:
    """D1 — 같은 부호가 정확히 days 일째(또는 remind_days 일째)인 날."""
    p = ev.get("params") or {}
    who = p.get("who", "foreign")
    rows = _flow(ctx, who)
    vals = [v for *_, v in rows]
    n = _streak(vals) if vals else 0
    if n not in (int(p.get("days", 5)), int(p.get("remind_days") or 0)) or len(vals) <= n:
        return []                                      # 줄의 시작이 자료 안에 있어야 「정확히 n일째」다
    _, row, v = rows[-1]
    sell = v < 0
    return _unseen(ctx, ev, [_flow_hit(ctx, ev, rows, {
        "streak": n, "cum5": _eok(sum(vals[-5:])), "supporter": _supporter(row, who, v),
        "dir_ko": _dir_ko(sell), "dir_rev_ko": _dir_ko(not sell)})])


@judge("flow_streak_end")
def flow_streak_end(ctx: Context, ev: dict) -> list[Hit]:
    """D2 — min_streak 일 이상 이어진 뒤 오늘 부호가 반대."""
    p = ev.get("params") or {}
    who = p.get("who", "foreign")
    rows = _flow(ctx, who)
    vals = [v for *_, v in rows]
    if len(vals) < 2 or (vals[-1] > 0) == (vals[-2] > 0):
        return []
    prev = vals[:-1]
    n, need = _streak(prev), int(p.get("min_streak", 5))
    if n < need or len(prev) <= n:
        return []
    return _unseen(ctx, ev, [_flow_hit(ctx, ev, rows, {
        "streak": n, "prev_dir_ko": _dir_ko(prev[-1] < 0), "cum": _eok(sum(prev[-n:])),
        "streak_min": need, "dir_ko": _dir_ko(vals[-1] < 0)})])


@judge("flow_cum_enter")
def flow_cum_enter(ctx: Context, ev: dict) -> list[Hit]:
    """D3 — 5일 합이 sell_le 이하 · buy_ge 이상으로 들어온 첫날(어제 5일 합은 밖)."""
    p = ev.get("params") or {}
    who = p.get("who", "foreign")
    rows = _flow(ctx, who)
    vals = [v for *_, v in rows]
    if len(vals) < 6:
        return []
    cum, cum0 = sum(vals[-5:]), sum(vals[-6:-1])
    lo, hi = float(p.get("sell_le", -50000)), float(p.get("buy_ge", 30000))
    if cum <= lo < cum0:
        band, exit_rule = f"{_eok(lo)} 이하", f"5일 합이 {_eok(lo)} 위로 올라오면 해제"
    elif cum >= hi > cum0:
        band, exit_rule = f"{_eok(hi)} 이상", f"5일 합이 {_eok(hi)} 아래로 내려오면 해제"
    else:
        return []
    _, row, v = rows[-1]
    hit = _flow_hit(ctx, ev, rows, {"cum": _eok(cum), "band_ko": band, "exit_rule": exit_rule,
                                    "supporter": _supporter(row, who, v)})
    hit.dir = "sell" if cum < 0 else "buy"             # 방향은 5일 합의 부호(오늘 하루가 아니라)
    return _unseen(ctx, ev, [hit])


@judge("flow_big_day")
def flow_big_day(ctx: Context, ev: dict) -> list[Hit]:
    """D4 — 하루 |값| ≥ abs_ge."""
    p = ev.get("params") or {}
    who = p.get("who", "foreign")
    rows = _flow(ctx, who)
    if not rows or abs(rows[-1][2]) < float(p.get("abs_ge", 20000)):
        return []
    vals = [v for *_, v in rows]
    _, row, v = rows[-1]
    return _unseen(ctx, ev, [_flow_hit(ctx, ev, rows, {
        "inst": _eok(_num(row.get("inst"))), "retail": _eok(_num(row.get("retail"))),
        "cum5": _eok(sum(vals[-5:])) if len(vals) >= 5 else "", "dir_ko": _dir_ko(v < 0)})])


@judge("stock_flow_flip")
def stock_flow_flip(ctx: Context, ev: dict) -> list[Hit]:
    """D5 — 추적 종목(stockFlows.items)마다 외국인 부호 전환(check_alerts flow 「전환」 규칙 승계, 단위 주)."""
    p = ev.get("params") or {}
    who = p.get("who", "foreign")
    today = _today(ctx)
    provisional = ctx.now.astimezone(KST).hour < FINAL_HOUR
    hits = []
    for code, e in ((ctx.data.get("stockFlows") or {}).get("items") or {}).items():
        rows = (e or {}).get("investor")
        if not isinstance(rows, list):
            continue
        vals = sorted((d, v) for r in rows if isinstance(r, dict)
                      if (d := _d(r.get("date"))) and (v := _num(r.get(who)))
                      and not (d > today or (provisional and d == today)))
        if len(vals) < 2 or (today - vals[-1][0]).days > STALE_DAYS:
            continue
        d, v = vals[-1]
        if (vals[-2][1] > 0) == (v > 0):
            continue
        prev = [x for _, x in vals[:-1]]
        hits.append(Hit(target=code, dir="sell" if v < 0 else "buy", value=v, unit="주", asOf=d.isoformat(),
                        fresh=_fresh(d, today), fields={
                            "name": e.get("name") or code, "dir_ko": _dir_ko(v < 0),
                            "prev_days": _streak(prev), "prev_dir_ko": _dir_ko(prev[-1] < 0)}))
    return _unseen(ctx, ev, hits)


# ── E 일정 · 발표 ────────────────────────────────────────────────────────
def _hm(e: dict) -> str:
    m = re.search(r"(\d{1,2}:\d{2})\s*$", str(e.get("dt") or ""))
    return m.group(1) if m else ""


def _release_due(e: dict, now: dt.datetime, delay_min: int = 30) -> bool:
    """발표 시각 가드(A3 와 같은 규칙): 일정 시각 전이면 False, timeApprox 면 +delay_min 분,
    시각 없는 일정은 그날 KST 09:00 뒤."""
    d = _d(e.get("iso"))
    if d is None:
        return False
    h, mi = (int(x) for x in (_hm(e) or "09:00").split(":"))
    when = dt.datetime(d.year, d.month, d.day, h, mi, tzinfo=KST)
    if e.get("timeApprox"):
        when += dt.timedelta(minutes=delay_min)
    return now.astimezone(KST) >= when


def _due(e: dict, now: dt.datetime, delay_min: int) -> bool:
    if _release_due_a3 is not None:
        return bool(_release_due_a3(e, now))
    return _release_due(e, now, delay_min)


def _escalate(ev: dict, stars: int):
    """사전 escalate {cond: "stars>=3", to: alarm} → 해당하면 올릴 등급."""
    esc = ev.get("escalate") or {}
    m = re.fullmatch(r"\s*stars\s*>=\s*(\d+)\s*", str(esc.get("cond") or ""))
    return esc.get("to") if m and stars >= int(m.group(1)) else None


def _next_star3(ctx: Context) -> str:
    """지금 뒤의 첫 ★★★ 일정 「M/D HH:MM 이름」. 없으면 빈칸."""
    now = ctx.now.astimezone(KST)
    best = None
    for e in ctx.calendar:
        d = _d(e.get("iso"))
        if not d or int(e.get("stars") or 0) < 3:
            continue
        h, mi = (int(x) for x in (_hm(e) or "00:00").split(":"))
        when = dt.datetime(d.year, d.month, d.day, h, mi, tzinfo=KST)
        if when > now and (best is None or when < best[0]):
            best = (when, e)
    if not best:
        return ""
    when, e = best
    return f"{_md(when.date())} {_hm(e)} {e.get('name')}".replace("  ", " ")


_CAL_MAP: dict | None = None


def _cal_map() -> dict:
    """일정 이름 → (data 경로, 형식, …) — fetch_data.CALENDAR_INDICATOR_MAP(단일 원천). 무거워서 쓸 때만 읽는다."""
    global _CAL_MAP
    if _CAL_MAP is None:
        try:
            import fetch_data
            _CAL_MAP = dict(fetch_data.CALENDAR_INDICATOR_MAP or {})
        except Exception:                                  # noqa: BLE001 — 없으면 관련 지표만 빈칸
            _CAL_MAP = {}
    return _CAL_MAP


def _related(ctx: Context, names: list[str]) -> str:
    by_path = {r.get("dataPath"): r for r in ctx.registry.values()}
    out = []
    for n in names:
        row = by_path.get((_cal_map().get(n) or [None])[0])
        if row and row.get("label") not in out:
            out.append(row.get("label"))
    return " · ".join(out)


def _hist_values(data: dict, name: str) -> list[float]:
    """발표값과 같은 단위의 과거 값(check_releases 단일 원천)."""
    try:
        import check_releases
        return check_releases._history_values(data, name)
    except Exception:                                      # noqa: BLE001
        return []


@judge("event_eve")
def event_eve(ctx: Context, ev: dict) -> list[Hit]:
    """E1 — 내일(KST) ★ stars_watch 이상 일정을 한 Hit 로. 관심(★★)은 구독 단계가 거른다 — items 에 stars 를 담는다."""
    p = ev.get("params") or {}
    s_all, s_watch = int(p.get("stars_all", 3)), int(p.get("stars_watch", 2))
    tmr = _today(ctx) + dt.timedelta(days=1)
    evs = sorted((e for e in ctx.calendar if _d(e.get("iso")) == tmr
                  and int(e.get("stars") or 0) >= min(s_all, s_watch)), key=lambda e: _hm(e) or "99:99")
    if not evs:
        return []
    lines = [f"{_hm(e)} {e.get('name')}".strip() for e in evs]
    items = [{"time": _hm(e), "name": e.get("name"), "cc": e.get("cc"), "stars": int(e.get("stars") or 0),
              "all": int(e.get("stars") or 0) >= s_all} for e in evs]
    return _unseen(ctx, ev, [Hit(
        target=_target(ev, "calendar"), dir="new", value=len(evs), unit="건", asOf=tmr.isoformat(), fresh="live",
        fields={"count": len(evs), "first": lines[0], "list": "\n".join(lines), "items": items,
                "stars": max(i["stars"] for i in items), "related": _related(ctx, [e.get("name") for e in evs])})])


def _released_today(ctx: Context, ev: dict) -> list[tuple[dict, int]]:
    """오늘(KST) 일정 중 실제치가 있고 발표 시각이 지난 ★ min_stars 이상."""
    p = ev.get("params") or {}
    today = _today(ctx)
    out = []
    for e in ctx.calendar:
        stars = int(e.get("stars") or 0)
        if (_d(e.get("iso")) == today and str(e.get("act") or "").strip() and stars >= int(p.get("min_stars", 2))
                and _due(e, ctx.now, int(p.get("approx_delay_min", 30)))):
            out.append((e, stars))
    return out


@judge("release_result")
def release_result(ctx: Context, ev: dict) -> list[Hit]:
    """E2 — 발표 결과(그날 · 발표 시각 뒤). key 가 일정마다 갈리게 asOf = 「날짜:이름」."""
    hits = []
    nxt = _next_star3(ctx)
    for e, stars in _released_today(ctx, ev):
        act, fore = _num(e.get("act")), _num(e.get("fore"))
        verdict = ("" if act is None or fore is None else
                   "상회" if act > fore + 1e-9 else "하회" if act < fore - 1e-9 else "부합")
        fields = {"event_name": e.get("name"), "act": e.get("act"), "fore": e.get("fore") or "",
                  "prev": e.get("prev") or "", "verdict_ko": verdict, "stars": stars, "next_event": nxt}
        if lvl := _escalate(ev, stars):
            fields["level"] = lvl
        hits.append(Hit(target=_target(ev, "calendar"), dir="new", value=e.get("act"), unit="",
                        asOf=f"{e['iso']}:{e.get('name')}", fresh="live", fields=fields))
    return _unseen(ctx, ev, hits)


@judge("surprise")
def surprise(ctx: Context, ev: dict) -> list[Hit]:
    """E3 — 예상과의 차 |act−fore| 가 그 지표 과거 회차 간 변화 |Δ| 분포에서 상위 (1−pct_rank) 안.
    fore 가 비면 판정하지 않는다. 일정표의 beat 는 방향(±1 · 0)이라 발표 대부분에 붙어 있어 쓰지 않는다."""
    p = ev.get("params") or {}
    need, edge = int(p.get("min_history", 24)), 1 - float(p.get("pct_rank", 0.8))
    hits = []
    for e, stars in _released_today(ctx, ev):
        act, fore = _num(e.get("act")), _num(e.get("fore"))
        if act is None or fore is None:
            continue
        h = _hist_values(ctx.data, e.get("name") or "")
        gaps = [abs(b - a) for a, b in zip(h, h[1:])]
        if len(gaps) < need:
            continue
        gap = act - fore
        share = (sum(1 for g in gaps if g >= abs(gap) - 1e-9) + 1) / (len(gaps) + 1)
        if share > edge:
            continue
        dec = len(m.group(1)) if (m := re.search(r"\.(\d+)", str(e.get("act")))) else 0
        suffix = "%p" if "%" in str(e.get("act")) else "K" if "K" in str(e.get("act")) else ""
        hits.append(Hit(target=_target(ev, "calendar"), dir="new", value=e.get("act"), unit="",
                        asOf=f"{e['iso']}:{e.get('name')}", fresh="live", fields={
                            "event_name": e.get("name"), "act": e.get("act"), "fore": e.get("fore"),
                            "gap": f"{gap:+.{min(dec, 2)}f}{suffix}", "hist_n": len(gaps),
                            "rank_pct": f"{share * 100:.0f}%", "stars": stars, "next_event": _next_star3(ctx)}))
    return _unseen(ctx, ev, hits)


@judge("policy_rate_change")
def policy_rate_change(ctx: Context, ev: dict) -> list[Hit]:
    """E4 — 정책금리 history 의 마지막 변경점이 오늘 · 어제(일간) 또는 이번 달 · 지난달(월간 계열)."""
    today = _today(ctx)
    max_age = int((ev.get("params") or {}).get("max_age_days", 1))
    hits = []
    for t in ev.get("targets") or []:
        row = ctx.registry.get(t) or ctx.registry.get(ctx.rid(t)) or {}
        node = _get(ctx.data, row.get("dataPath") or "") if row.get("dataPath") else None
        hist = (node or {}).get("history") if isinstance(node, dict) else None
        if not isinstance(hist, dict):
            continue
        pts = [(k, v) for k in sorted(hist, key=lambda k: _pdate(k) or dt.date.min) if (v := _num(hist[k])) is not None]
        chg = [(pts[i][0], pts[i - 1][1], pts[i][1]) for i in range(1, len(pts)) if pts[i][1] != pts[i - 1][1]]
        if not chg:
            continue
        k, old, new = chg[-1]
        kd = _pdate(k)
        if kd is None:
            continue
        daily = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(k)))
        age = (today - kd).days if daily else (today.year - kd.year) * 12 + today.month - kd.month
        if not 0 <= age <= (max_age if daily else 1):
            continue
        up = new > old
        prev_up = [c[2] > c[1] for c in chg[:-1]]
        prev_n = _streak([1 if u else -1 for u in prev_up]) if prev_up else 0
        word = MEETING.get(t)
        meet = sorted(d for e in ctx.calendar if word and word in str(e.get("name") or "")
                      if (d := _d(e.get("iso"))) and d > today)
        hits.append(Hit(target=t, dir="up" if up else "down", value=new, unit="%", asOf=str(k),
                        fresh=_fresh(kd, today) if daily else "prev", fields={
                            "name": row.get("label") or t, "prev": old, "chg_bp": round((new - old) * 100),
                            "verb_ko": "인상" if up else "인하", "prev_n": prev_n,
                            "prev_dir_ko": ("인상" if prev_up[-1] else "인하") if prev_up else "",
                            "next_meeting": _md(meet[0]) if meet else ""}))
    return _unseen(ctx, ev, hits)


@judge("holiday_notice")
def holiday_notice(ctx: Context, ev: dict) -> list[Hit]:
    """E5 — 오늘 개장이고 내일부터 다음 영업일 전까지 휴장이 min_gap_days 일 이상(주말만이면 안내하지 않음)."""
    today = _today(ctx)
    cal = (ctx.data.get("marketCalendarKr")
           or (_read_json(os.path.join(ctx.root, "toss_snapshot.json")) or {}).get("marketCalendarKr") or {})
    t, nxt = cal.get("today") or {}, _d((cal.get("nextBusinessDay") or {}).get("date"))
    if _d(t.get("date")) != today or t.get("open") is not True or nxt is None:
        return []
    closed = [today + dt.timedelta(days=i) for i in range(1, (nxt - today).days)]
    if len(closed) < int((ev.get("params") or {}).get("min_gap_days", 2)) or all(d.weekday() >= 5 for d in closed):
        return []
    try:
        import nyse_calendar
        us = [d for d in closed if nyse_calendar.is_trading_day(d)]
        us_status = " · ".join(_md(d) for d in us) + " 개장" if us else "같은 기간 휴장"
    except ImportError:
        us_status = ""
    return _unseen(ctx, ev, [Hit(
        target=_target(ev, "calendar"), dir="new", value=len(closed), unit="일", asOf=closed[0].isoformat(),
        fresh="live", fields={"from_md": _md(closed[0]), "to_md": _md(closed[-1]), "next_md": _md(nxt),
                              "us_status": us_status})])


# ── F 공시 · 종목 ────────────────────────────────────────────────────────
@judge("corp_event_new")
def corp_event_new(ctx: Context, ev: dict) -> list[Hit]:
    """F1 — corpEvents 의 접수번호가 원장 이력(400일)의 F1 행에 없으면 새 것.
    접수일이 7일 넘게 지난 것(첫 런 · 결산 배당의 사업보고서)은 새 공시가 아니라 뺀다."""
    kinds = set((ev.get("params") or {}).get("kinds") or KIND_KO)
    today = _today(ctx)
    seen = {str(r.get("asOf") or "").rsplit(":", 1)[-1] for r in _event_rows(ctx, ev["id"])}
    hits = []
    for it in (ctx.data.get("corpEvents") or {}).get("items") or []:
        rcp, d = str(it.get("rcpNo") or ""), _d(it.get("date"))
        if not rcp or rcp in seen or it.get("kind") not in kinds or d is None or not 0 <= (today - d).days <= STALE_DAYS:
            continue
        seen.add(rcp)
        hits.append(Hit(target=str(it.get("code")), dir="new", value=it.get("title"), unit="",
                        asOf=f"{d.isoformat()}:{rcp}", fresh=_fresh(d, today), fields={
                            "name": it.get("name") or it.get("code"), "kind_ko": KIND_KO.get(it.get("kind"), ""),
                            "doc_title": it.get("detail") or it.get("title") or "",
                            "rcp_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}"}))
    return hits


def _labels(w) -> list[str]:
    """토스 warnings → 지정 이름 목록(check_alerts._check_toss_warnings 와 같은 읽기)."""
    return sorted({str((x or {}).get("name") or (x or {}).get("type") or x) if isinstance(x, dict) else str(x)
                   for x in w if x})


@judge("toss_warning_change")
def toss_warning_change(ctx: Context, ev: dict) -> list[Hit]:
    """F2 — 종목 시장 지정 변화. 직전 = alerts_state._tossWarnings(읽기만) 위에 원장 F2 행을 시간순으로 덮은 것.
    둘 다에 없는 종목은 첫 관측 — 기준선만(알리지 않음)."""
    cur = {s: (e.get("name") or s, set(_labels(e["warnings"])))
           for s, e in ((ctx.data.get("stockFlows") or {}).get("items") or {}).items()
           if isinstance(e, dict) and isinstance(e.get("warnings"), list)}   # 누락 = 조회 실패 → 판단 보류
    base = (_read_json(os.path.join(ctx.root, "alerts_state.json")) or {}).get("_tossWarnings") or {}
    prev = {s: set((v or {}).get("labels") or []) for s, v in base.items()}
    for r in sorted(_event_rows(ctx, ev["id"]), key=lambda r: r.get("ts", "")):
        labs = prev.setdefault(r.get("target"), set())
        (labs.add if r.get("dir") == "enter" else labs.discard)(r.get("value"))
    today = _today(ctx).isoformat()
    hits = []
    for s, (name, labs) in cur.items():
        if s not in prev:
            continue
        old = prev[s]
        before = "직전 " + (", ".join(sorted(old)) if old else "지정 없음")
        for lab, d, verb in [(x, "enter", "지정") for x in sorted(labs - old)] + \
                            [(x, "exit", "해제") for x in sorted(old - labs)]:
            hits.append(Hit(target=s, dir=d, value=lab, unit="", asOf=f"{today}:{lab}", fresh="live",
                            fields={"name": name, "label": lab, "verb_ko": verb, "prev_labels": before}))
    return _unseen(ctx, ev, hits)


@judge("movers_record")
def movers_record(ctx: Context, ev: dict) -> list[Hit]:
    """F3(꺼짐 · 기록 등급) — 특징주 |등락| ≤ max_abs_pct 중 큰 순 3."""
    cap = float((ev.get("params") or {}).get("max_abs_pct", 30))
    rows = [r for lst in (ctx.data.get("stockMovers") or {}).values() if isinstance(lst, list)
            for r in lst if isinstance(r, dict) and (c := _num(r.get("chg"))) is not None and abs(c) <= cap]
    rows.sort(key=lambda r: -abs(_num(r["chg"])))
    today = _today(ctx)
    return _unseen(ctx, ev, [Hit(
        target=str(r.get("code")), dir="up" if _num(r["chg"]) > 0 else "down", value=r.get("price"), unit="원",
        asOf=str(r.get("as_of") or today), fresh=_fresh(_d(r.get("as_of")), today), chg=_num(r["chg"]),
        fields={"name": r.get("name")}) for r in rows[:3]])


# ── G 렌즈 · 메르 ────────────────────────────────────────────────────────
@judge("regime_change")
def regime_change(ctx: Context, ev: dict) -> list[Hit]:
    """G1 — 이번 달 우세 국면이 지난달과 다름."""
    rg = ctx.mer.get("regime") or {}
    dom, months = rg.get("dominant") or [], rg.get("months") or []
    if len(dom) < 2 or len(months) != len(dom) or not dom[-1] or not dom[-2] or dom[-1] == dom[-2]:
        return []
    cnt = (rg.get("counts") or [[]])[-1]
    top = sorted(((c, f) for f, c in zip(rg.get("factors") or [], cnt) if c), reverse=True)[:3]
    return _unseen(ctx, ev, [Hit(
        target=_target(ev, "regime"), dir="change", value=dom[-1], unit="", asOf=str(months[-1]), fresh="live",
        fields={"prev": dom[-2], "counts": " · ".join(f"{f} {c}" for c, f in top)})])


@judge("stance_reversal")
def stance_reversal(ctx: Context, ev: dict) -> list[Hit]:
    """G2 — 자산별 입장 반전(stance.assets[].reversals) 의 마지막 날짜가 오늘 · 어제."""
    today = _today(ctx)
    posts = {p.get("logNo"): p for p in ctx.mer.get("posts") or [] if isinstance(p, dict)}
    hits = []
    for a in (ctx.mer.get("stance") or {}).get("assets") or []:
        last = max(a.get("reversals") or [""])
        d = _d(last)
        if d is None or not 0 <= (today - d).days <= 1:
            continue
        s = sorted(a.get("series") or [], key=lambda x: x.get("date", ""))
        pair = next(((p, c) for p, c in reversed(list(zip(s, s[1:]))) if c.get("date") == last
                     and isinstance(p.get("view"), (int, float)) and isinstance(c.get("view"), (int, float))
                     and p["view"] * c["view"] < 0), None)
        if not pair:
            continue
        p, c = pair
        post = posts.get(c.get("logNo")) or {}
        hits.append(Hit(target=a.get("asset"), dir="up" if c["view"] > p["view"] else "down",
                        value=VIEW_KO.get(round(c["view"]), ""), unit="", asOf=last, fresh=_fresh(d, today),
                        fields={"name": a.get("label") or a.get("asset"), "prev_ko": VIEW_KO.get(round(p["view"]), ""),
                                "post_title": post.get("title") or "", "post_date": last}))
    return _unseen(ctx, ev, hits)


@judge("mer_new_posts")
def mer_new_posts(ctx: Context, ev: dict) -> list[Hit]:
    """G3 — 오늘(KST) 발행 글을 한 Hit 로."""
    today = _today(ctx).isoformat()
    posts = [p for p in ctx.mer.get("posts") or [] if isinstance(p, dict)]
    todays = [p for p in posts if str(p.get("date")) == today]
    if not todays:
        return []
    return _unseen(ctx, ev, [Hit(
        target=_target(ev, "posts"), dir="new", value=len(todays), unit="편", asOf=today, fresh="live",
        fields={"count": len(todays), "titles": "\n".join(str(p.get("title") or "") for p in todays[:3]),
                "month_count": sum(1 for p in posts if today[:7] + "-01" <= str(p.get("date", "")) <= today)})])


@judge("mri_move")
def mri_move(ctx: Context, ev: dict) -> list[Hit]:
    """G4 — 렌즈 점수가 직전 날 대비 |Δ| ≥ delta 이거나 40 · 60 선을 건넘."""
    p = ev.get("params") or {}
    lens = ctx.mer.get("lens") or (ctx.bundles.get("lens") or {}).get("lens") or {}
    score, as_of = _num(lens.get("score")), str(lens.get("asOf") or "")
    before = [h for h in lens.get("history30d") or [] if str(h.get("date", "")) < as_of and _num(h.get("score")) is not None]
    if score is None or not before:
        return []
    prev = _num(before[-1]["score"])
    delta = score - prev
    reasons = [f"{ln} 선 {'위로' if score >= ln else '아래로'}" for ln in p.get("lines") or [40, 60]
               if (prev >= ln) != (score >= ln)]
    if abs(delta) >= float(p.get("delta", 5)):
        reasons.append(f"하루 {delta:+.0f}")
    if not reasons:
        return []
    comp = " · ".join(f"{MRI_PARTS.get(k, k)} {v}" for k, v in (lens.get("components") or {}).items())
    return _unseen(ctx, ev, [Hit(
        target=_target(ev, "mri"), dir="up" if delta > 0 else "down", value=score, unit="점", asOf=as_of,
        fresh=_fresh(_d(as_of), _today(ctx)), chg=delta,
        fields={"reason": " · ".join(reasons), "components": comp, "prev": prev})])


@judge("chain_hot_enter")
def chain_hot_enter(ctx: Context, ev: dict) -> list[Hit]:
    """G5 — 발동 고리(hotStep)가 있는 사슬 중 원장 최근 cooldown 일에 G5 행이 없는 것.
    ponytail: 사슬의 「어제 발동 여부」는 원장 행으로만 안다 — 계속 발동 중이면 cooldown 일마다 다시 낸다.
    정확한 진입만 원하면 사슬 상태 이력을 mer_aggregate 가 내놓을 때 그것과 비교."""
    chains = ctx.mer.get("chains") or (ctx.bundles.get("lens") or {}).get("chains") or []
    days = int((ev.get("cooldown") or {}).get("days", 7))
    cut = (_today(ctx) - dt.timedelta(days=days)).isoformat()
    recent = {r.get("target") for r in _event_rows(ctx, ev["id"]) if str(r.get("ts", ""))[:10] > cut}
    inds = {i.get("id"): i for i in ctx.mer.get("indicators") or [] if isinstance(i, dict)}
    today = _today(ctx).isoformat()
    hits = []
    for c in chains:
        hot = c.get("hotStep")
        if not hot or c.get("id") in recent:
            continue
        steps = c.get("steps") or []
        i = next((k for k, s in enumerate(steps) if s.get("id") == hot), None)
        ind = inds.get(hot) or {}
        cur, lvl = (ind.get("current") or {}).get("value"), (ind.get("nearest") or {}).get("level")
        trig = (f"{ind.get('label')} {cur}{ind.get('unit') or ''} · {lvl} 선 "
                f"{'돌파' if ind.get('state') == 'crossed' else '주시'}") if cur is not None and lvl is not None else ""
        hits.append(Hit(target=c.get("id"), dir="enter", value=steps[i].get("label") if i is not None else hot,
                        unit="", asOf=today, fresh="live", fields={
                            "name": c.get("label"), "step": steps[i].get("label") if i is not None else hot,
                            "trigger": trig or c.get("note") or "",
                            "next_step": steps[i + 1].get("label") if i is not None and i + 1 < len(steps) else ""}))
    return _baseline(ctx, ev, _unseen(ctx, ev, hits))


# ── H 실물 · 월간 ────────────────────────────────────────────────────────
@judge("monthly_new_value")
def monthly_new_value(ctx: Context, ev: dict) -> list[Hit]:
    """H2 — economicIndicators 의 월간 · 분기 잎(마지막 두 기간 간격 25~100일). 그 기간이 원장 이력에 없으면 새 값."""
    by_path = {r.get("dataPath"): rid for rid, r in ctx.registry.items()}
    hits = []
    for region, block in (ctx.data.get("economicIndicators") or {}).items():
        for key, leaf in (block or {}).items() if isinstance(block, dict) else ():
            hist = (leaf or {}).get("history") if isinstance(leaf, dict) else None
            if not isinstance(hist, dict) or len(hist) < 2 or leaf.get("period") is None:
                continue
            ks = sorted((d, k) for k in hist if (d := _pdate(k)))
            if len(ks) < 2 or not 25 <= (ks[-1][0] - ks[-2][0]).days <= 100:
                continue
            rid = by_path.get(f"economicIndicators.{region}.{key}", key)
            hits.append(Hit(target=rid, dir="new", value=leaf.get("value"), unit=str(leaf.get("unit") or ""),
                            asOf=str(leaf["period"]), fresh="prev", fields={
                                "name": (ctx.registry.get(rid) or {}).get("label") or leaf.get("desc") or rid,
                                "period": _period_ko(leaf["period"])}))
    return _baseline(ctx, ev, _unseen(ctx, ev, hits))


@judge("realestate_monthly")
def realestate_monthly(ctx: Context, ev: dict) -> list[Hit]:
    """H3 — realestate.kr.region(시도 아파트 매매 월간 등락) 의 기간이 원장 이력에 없으면 새 값."""
    kr = (ctx.data.get("realestate") or {}).get("kr") or {}
    nat = _num((kr.get("apt_price_idx_kr") or {}).get("chg"))
    today = _today(ctx)
    nxt = sorted(d for e in ctx.calendar if str(e.get("cc")) == "KR" and re.search(r"주택|부동산", str(e.get("name")))
                 if (d := _d(e.get("iso"))) and d > today)
    hits = []
    for r in kr.get("region") or []:
        code, val, per = str(r.get("code")), _num(r.get("val")), r.get("period")
        if code not in SIDO or val is None or not per:
            continue
        hits.append(Hit(target=f"sido_{code}", dir="up" if val > 0 else "down", value=val, unit="%", chg=val,
                        asOf=str(per), fresh="prev", fields={
                            "name": SIDO[code], "period": _period_ko(per),
                            "national": f"{nat:+.2f}%" if nat is not None else "", "next_date": _md(nxt[0]) if nxt else ""}))
    return _baseline(ctx, ev, _unseen(ctx, ev, hits))


@judge("enso_phase")
def enso_phase(ctx: Context, ev: dict) -> list[Hit]:
    """H4 — ENSO 국면이 직전 ONI 계절과 다름(국면 규칙은 fetch_climate.derive_phase 단일 원천)."""
    from fetch_climate import derive_phase
    en = (ctx.data.get("climate") or {}).get("enso") or {}
    oni = en.get("oni") or {}
    vals = [v for x in en.get("oni_history") or [] if (v := _num((x or {}).get("v"))) is not None]
    cur = en.get("phase")
    if vals and oni.get("value") is not None and abs(vals[-1] - float(oni["value"])) < 1e-9:
        vals = vals[:-1]                               # 마지막 행 = 지금 계절
    if cur not in ENSO_KO or not vals:
        return []
    prev = derive_phase(vals[-1])
    if prev == cur:
        return []
    return _unseen(ctx, ev, [Hit(
        target=_target(ev, "enso"), dir="change", value=ENSO_KO[cur], unit="", asOf=str(oni.get("asOf") or ""),
        fresh="prev", fields={"prev": ENSO_KO[prev], "oni": oni.get("value")})])
