"""판정 함수 — 시장 갈래(A1~A5 급변 · B1~B2 기록 · C1~C8 임계 · H1 김치프리미엄). 물결 A6.

계약서 docs/superpowers/plans/2026-10-05-alerts-v2.md 「판정 함수 계약」. 함수마다 사전(events.yml)의
judge 이름으로 `events.JUDGES` 에 등록되고 (ctx, ev) -> list[Hit] 를 돌려준다.

공통 규칙
- 값 · 등락 · 신선도 · 기준시각은 ctx.value / change_pct / fresh / as_of(번들 = 화면과 같은 값)에서만 꺼낸다.
  일봉(ctx.series)은 σ · 52주 · 직전 값처럼 「과거」를 볼 때만 쓴다. 렌즈(C1 · C2)는 선이 메르 지표의 값
  (전년비 등 단위가 레지스트리와 다를 수 있다)에 걸려 있어 mer_signals 의 current 를 쓴다.
- 네트워크를 쓰지 않는다. 값이 없으면 빈 목록(날조 금지).
- Hit.asOf 는 관측 날짜다(YYYY-MM-DD, 월간은 원천 표기). 같은 관측이면 같은 원장 key 가 되어, 같은 값을
  다시 판정하는 런(매분 · 매시 · 주말)이 원장에 두 번 들어가지 않는다(Ledger.append 가 지난 원장도 본다).
- 사전의 escalate(abs_z>=3.0 · stage>=40 · default_target)를 만족하면 fields["level"] 에 올릴 등급을 적는다.

Hit.fields — 문구 틀 변수. 숫자는 날것(표시 형식은 compose 몫), 글자는 완성된 말.
  A1~A4  z · abs_z(σ 없으면 None) · sigma · thr(임계 %) · peer(같은 방향 1σ 이상 동반 지표 이름, 없으면 "")
         · next_round(다음 마디 값)
  A5     stage(서킷 1~3, 사이드카 None) · halt_kind · approx(「(추정)」 또는 "") · source · next_stage(%) · peer
         · halt_id. 단계 · 종류가 바뀌면 다른 사건이라 asOf 에 「날짜.종류단계」를 싣는다(예 2026-10-05.circuit2).
  B1     prev_extreme · prev_date · next_round
  B2     level_value · next_level · from_high(52주 고점 대비 %)
  C1     line · chain · chain_id · step · post_date · next_line · dist(다음 선까지 %) · node(렌즈 노드 id)
  C2     line · dist(선까지 %) · chain · chain_id · step · node
  C3·C4  stage · next_stage · peer · peer_chg(「+0.7%」 · 「-12bp」) · prev
  C5     band_ko · prev · exit_rule
  C6     reason · realized(코스피 20일 실현변동성, 연율 %) · ratio
  C7     chg_bp(정수) · asof_md(「10/1」) · peer · peer_chg
  C8     flip_ko · prev
  H1     krw_g · usd_oz
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import statistics
import sys
from functools import lru_cache

from .context import KST, LENS_ALIASES, Context, _get
from .events import Hit, judge

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS not in sys.path:
    sys.path.append(_SCRIPTS)
import market_halts  # noqa: E402  서킷브레이커 단계 판정(현행 단일 원천)
import volatility as vol  # noqa: E402  σ · 임계 clamp(check_swings 와 같은 식)

SANE_PCT = 50.0                              # check_swings 와 같은 오염 폐기선(지수 · 환율에 하루 50%면 글리치)
ASIA = ("kr", "jp", "cn", "hk")              # 거래일 = KST 날짜. 그 밖(미국 지수 · 환율 · 원자재)은 UTC 날짜
PEERS = {"vix": "sp500", "move": "us10y"}    # C3 · C4 「왜」 줄의 짝 — 사전 문구(S&P500 · 미 10년)와 같은 대상
_HALT_SRC = {"index": "지수 등락", "news": "뉴스 대조", "krx": "거래소"}
_COND = re.compile(r"^\s*([A-Za-z_]\w*)\s*(>=|<=|==|>|<)\s*(-?\d+(?:\.\d+)?)\s*$")


# ───────────────────────── 공용 ─────────────────────────
def _num(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _r(x, n):
    return None if x is None else round(x, n)


def _tidy(x):
    """마디 · 선 값 정리 — 부동소수 찌꺼기를 없애고 정수면 int."""
    if x is None:
        return None
    x = round(float(x), 10)
    return int(x) if x == int(x) else x


def _is_date(s: str) -> bool:
    try:
        dt.date.fromisoformat(s)
        return True
    except (TypeError, ValueError):
        return False


def _parse_day(s) -> dt.date | None:
    """'2026-10-01' · '202609' · '2026-09' → date(월간은 그달 1일). 못 읽으면 None."""
    s = str(s or "").strip()
    for fmt, cut in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y%m", 6)):
        try:
            return dt.datetime.strptime(s[:cut], fmt).date()
        except ValueError:
            continue
    return None


def _kst_day(iso) -> str | None:
    try:
        t = dt.datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=KST)
    return t.astimezone(KST).date().isoformat()


def _bars(ctx: Context, target: str, n: int = 400) -> list[tuple[str, float]]:
    out = []
    for b in ctx.series(target, n):
        c, d = _num(b.get("close")), b.get("date")
        if c is not None and d:
            out.append((str(d), c))
    return out


def _same(a, b) -> bool:
    return a is not None and b is not None and abs(a - b) <= max(1e-9, abs(b) * 1e-4)


def _name(ctx: Context, target: str) -> str:
    for src in (ctx.strip(target), ctx.row(target)):
        if src and (src.get("short") or src.get("label")):
            return str(src.get("short") or src.get("label"))
    return target


def _unit(ctx: Context, target: str) -> str:
    u = str((ctx.strip(target) or {}).get("unit") or (ctx.row(target) or {}).get("unit") or "")
    return u.split(" ")[0] if len(u) > 4 else u           # 레지스트리 unit 은 「% (연이율)」 같은 설명일 때가 있다


def _day_of(ctx: Context, target: str, value: float, fresh: str, bars) -> str:
    """값이 속한 거래일(YYYY-MM-DD).

    실시간이면 asOf 시각을 시장 쪽 날짜로 — 아시아는 KST, 그 밖은 UTC(미국 지수 · 환율 일봉이 KST 09시에
    넘어간다, check_swings._move_day). 아니면 값과 같은 마지막 일봉의 날짜 — 토스 스냅샷 시각이 asOf 에
    찍혀도 값은 전일 종가일 수 있다(2026-10-05 KOSPI asOf 13:15 · 값 = 10/2 종가, 실측)."""
    a = str(ctx.as_of(target) or "")
    if fresh == "live" and "T" in a:
        try:
            t = dt.datetime.fromisoformat(a)
            if t.tzinfo is None:
                t = t.replace(tzinfo=KST)
            asia = str((ctx.row(target) or {}).get("country") or "").lower() in ASIA
            return t.astimezone(KST if asia else dt.timezone.utc).date().isoformat()
        except ValueError:
            pass
    d = a[:10] if _is_date(a[:10]) else None
    upto = [b for b in bars if d is None or b[0] <= d]
    if upto and _same(upto[-1][1], value):
        return upto[-1][0]
    return d or (bars[-1][0] if bars else ctx.now.astimezone(KST).date().isoformat())


def _today(ctx: Context, target: str, daily: bool = False):
    """(오늘 값, 그 거래일, 그 이전 일봉[(date, close)], 등락%, 신선도) 또는 None.

    daily=True 면 일봉만 본다(장중 값이 없는 대상 — 비트코인 A4): 오늘 = 끝 봉, 등락 = 끝 두 봉."""
    bars = _bars(ctx, target)
    if daily:
        if len(bars) < 2 or not bars[-2][1]:
            return None
        (day, v), prior = bars[-1], bars[:-1]
        return v, day, prior, (v / prior[-1][1] - 1) * 100, ctx.fresh(target)
    v = _num(ctx.value(target))
    if v is None:
        return None
    fresh = ctx.fresh(target)
    day = _day_of(ctx, target, v, fresh, bars)
    prior = [b for b in bars if b[0] < day]
    chg = _num(ctx.change_pct(target))
    if chg is None and prior and prior[-1][1]:
        chg = (v / prior[-1][1] - 1) * 100                 # 번들에 등락률이 없으면 일봉 끝 두 점(직전 종가 대비)
    return v, day, prior, chg, fresh


def _prev_value(ctx: Context, target: str, v: float, prior) -> float | None:
    """직전 값 — 번들 칸의 등락(절대) → 등락률 → 일봉의 직전 점. 앞의 둘은 그 칸이 말하는 직전 값 그대로다."""
    ch = _num((ctx.strip(target) or {}).get("change"))
    if ch is not None:
        return v - ch
    p = _num(ctx.change_pct(target))
    if p is not None and p > -100:
        return v / (1 + p / 100)
    return prior[-1][1] if prior else None


def _chg_text(ctx: Context, target: str) -> str:
    """짝 지표의 오늘 움직임 한 토막 — 금리는 bp, 그 밖은 %."""
    if str((ctx.row(target) or {}).get("dataPath") or "").startswith("yieldCurve"):
        ch = _num((ctx.strip(target) or {}).get("change"))
        if ch is None:
            b = _bars(ctx, target)
            ch = (b[-1][1] - b[-2][1]) if len(b) >= 2 else None
        return "" if ch is None else f"{int(round(ch * 100)):+d}bp"
    p = _num(ctx.change_pct(target))
    return "" if p is None else f"{p:+.1f}%"


@lru_cache(maxsize=1)
def _b2_steps() -> dict:
    """사전 B2(마디 돌파)의 마디표 — 「다음 마디」를 A · B 갈래가 같은 간격으로 말하게."""
    try:
        from . import schema
        ev = next((e for e in schema.load_events() if e.get("judge") == "round_level"), None)
        return dict(((ev or {}).get("params") or {}).get("step") or {})
    except Exception:                                  # noqa: BLE001 — 사전이 깨져도 판정은 돈다(간격만 추정)
        return {}


def _nice_step(v: float) -> float | None:
    """마디표에 없는 대상의 간격 — 값의 5% 이상인 가장 작은 1·2·5×10ⁿ."""
    if not v or v <= 0:
        return None
    want = v * 0.05
    e = math.floor(math.log10(want))
    for m in (1, 2, 5, 10):
        if m * 10 ** e >= want:
            return m * 10 ** e
    return None


def _next_round(ctx: Context, target: str, v: float, up: bool):
    step = _num(_b2_steps().get(target)) or _nice_step(abs(v))
    if not step:
        return None
    k = math.floor(v / step + 1e-9) + 1 if up else math.ceil(v / step - 1e-9) - 1
    return _tidy(k * step)


def _escalate(ev: dict, hit: Hit) -> None:
    esc = ev.get("escalate") or {}
    cond, to = esc.get("cond"), esc.get("to")
    if not cond or not to:
        return
    if cond == "default_target":
        ok = hit.target in (ev.get("default_on") or [])
    else:
        m = _COND.match(str(cond))
        x = _num(hit.fields.get(m.group(1))) if m else None
        if x is None:
            return
        y, op = float(m.group(3)), m.group(2)
        ok = {">=": x >= y, "<=": x <= y, ">": x > y, "<": x < y, "==": x == y}[op]
    if ok:
        hit.fields["level"] = to


def _market_judge(name: str):
    """judge(name) 등록 + 사전 escalate 적용."""
    def deco(fn):
        def wrapped(ctx, ev):
            hits = fn(ctx, ev) or []
            for h in hits:
                _escalate(ev, h)
            return hits
        wrapped.__name__, wrapped.__doc__ = fn.__name__, fn.__doc__
        judge(name)(wrapped)
        return wrapped
    return deco


def _points(obj) -> list[tuple[str, float]]:
    """이력 모양 셋을 [(date, value)] 로 — {날짜: 값} · [{date, value|close}] · [[날짜, 값]] · {points|rows: …}."""
    if isinstance(obj, dict):
        for k in ("points", "rows", "history", "data"):
            if isinstance(obj.get(k), (list, dict)):
                return _points(obj[k])
        pts = [(str(k), _num(v)) for k, v in obj.items()]
    elif isinstance(obj, list):
        pts = []
        for r in obj:
            if isinstance(r, dict):
                pts.append((str(r.get("date") or ""), _num(r.get("value", r.get("close")))))
            elif isinstance(r, (list, tuple)) and len(r) >= 2:
                pts.append((str(r[0]), _num(r[1])))
    else:
        return []
    return sorted((d, v) for d, v in pts if d and v is not None)


def _history_file(ctx: Context, key: str):
    """events/history/<key>.json — 1점짜리 묶음을 날마다 쌓는 적재기(물결 A4 history_sink)의 산출."""
    p = os.path.join(ctx.root, "events", "history", f"{key}.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ───────────────────────── A 급변 ─────────────────────────
def _swing_state(ctx: Context, target: str, daily: bool):
    t = _today(ctx, target, daily)
    if not t:
        return None
    v, day, prior, chg, fresh = t
    if chg is None or abs(chg) > SANE_PCT:
        return None
    if not daily and fresh != "live":
        return None              # 장중 값만 — 직전 종가로 「오늘 급변」을 말하지 않는다(check_swings 의 장중 · fresh 가드)
    sd = vol.sigma([c for _, c in prior], exclude_last=False)     # 직전 250일 일간 수익률 σ(오늘 제외)
    return v, day, chg, sd, fresh


def _swing_peer(ctx: Context, target: str, up: bool, states: dict) -> str:
    """같은 갈래(같은 사건의 대상들)에서 같은 방향으로 1σ 이상 움직인 지표 이름 1개 — 가장 큰 것."""
    best, best_z = "", 0.0
    for t, st in states.items():
        if t == target or not st:
            continue
        _, _, chg, sd, _ = st
        if not sd or chg == 0 or (chg > 0) != up:
            continue
        z = abs(chg / sd)
        if z >= 1.0 and z > best_z:
            best, best_z = _name(ctx, t), z
    return best


@_market_judge("swing_sigma")
def swing_sigma(ctx: Context, ev: dict) -> list[Hit]:
    """A1~A4 — |오늘 등락| ≥ min(max(kσ, 하한), 상한). σ 를 못 내면 fallback_pct(없으면 판정 안 함)."""
    p = ev.get("params") or {}
    k = float(p.get("sigma", 2.5))
    lo, hi = (list(p.get("clamp_pct") or [0.5, 5.0]) + [5.0])[:2]
    fallback = p.get("fallback_pct") or {}
    daily = bool(p.get("daily"))
    targets = list(ev.get("targets") or [])
    states = {t: _swing_state(ctx, t, daily) for t in targets}
    hits = []
    for t in targets:
        st = states[t]
        if not st:
            continue
        v, day, chg, sd, fresh = st
        thr = vol.clamp_threshold(sd, k, float(lo), float(hi), _num(fallback.get(t)))
        if thr is None or chg == 0 or abs(chg) < thr:
            continue
        up = chg > 0
        z = chg / sd if sd else None
        hits.append(Hit(
            target=t, dir="up" if up else "down", value=v, unit=_unit(ctx, t), asOf=day, fresh=fresh,
            chg=_r(chg, 2),
            fields={"z": _r(z, 2), "abs_z": _r(abs(z), 2) if z is not None else None, "sigma": _r(sd, 3),
                    "thr": _r(thr, 2), "peer": _swing_peer(ctx, t, up, states),
                    "next_round": _next_round(ctx, t, v, up)}))
    return hits


@_market_judge("market_halt")
def market_halt(ctx: Context, ev: dict) -> list[Hit]:
    """A5 — 서킷브레이커 · 사이드카 발동(enter) · 해제(exit).

    발동 후보 둘: ① 실시간 지수 등락률 → market_halts.cb_from_index(−8/−15/−20%, 정규장 · 14:50 게이트 그대로)
    ② data.json marketHalts.active(수집 런의 detect_market_halts — 사이드카 = ±2.5% + 뉴스 대조). 같은 id 는
    market_halts._merge 로 합친다(더 심한 단계 · 이른 시각). 해제 = marketHalts.history 에서 오늘 풀린 것."""
    from check_halts import TYPE_KO                    # 서킷브레이커 · 사이드카 이름의 현행 단일 원천
    stages = [x for x in (_num(s) for s in ((ev.get("params") or {}).get("stages_pct") or [-8, -15, -20]))
              if x is not None]
    stages.sort(reverse=True)                          # −8 → −15 → −20
    halts = ctx.data.get("marketHalts") or {}
    today = ctx.now.astimezone(KST).date().isoformat()

    def trusted(h):
        return (isinstance(h, dict) and h.get("id") and h.get("id") not in market_halts._FALSE_HALTS
                and (h.get("source") != "news" or h.get("corroborated")))

    per = {}
    for t in ev.get("targets") or []:
        market = str((ctx.row(t) or {}).get("dataPath") or "").split(".")[-1].upper()
        if market not in ("KOSPI", "KOSDAQ"):
            continue
        live_chg = _num(ctx.change_pct(t)) if ctx.fresh(t) == "live" else None
        cands = {}
        if live_chg is not None and abs(live_chg) <= SANE_PCT:
            h = market_halts.cb_from_index(market, live_chg, ctx.now)
            if h:
                cands[h["id"]] = h
        for h in halts.get("active") or []:
            if not trusted(h) or h.get("market") != market:
                continue
            if h.get("source") == "index" and halts.get("stale"):
                continue                               # 지수가 깜깜이였던 빌드의 지수 사건은 믿지 않는다(check_halts 가드)
            if _kst_day(h.get("triggeredAt")) != today:
                continue
            cands[h["id"]] = market_halts._merge(cands.get(h["id"]), h)
        exits = [h for h in (halts.get("history") or [])
                 if trusted(h) and h.get("market") == market and h["id"] not in cands
                 and _kst_day(h.get("resolvedAt")) == today]
        per[t] = (list(cands.values()), exits)

    hits = []
    for t, (actives, exits) in per.items():
        others = [x for x in per if x != t and per[x][0]]
        peer = _name(ctx, others[0]) if others else ""
        for h, d in [(h, "enter") for h in actives] + [(h, "exit") for h in exits]:
            typ = str(h.get("type") or "circuit")
            stage = h.get("stage") if typ == "circuit" else None
            nxt = stages[stage] if (stage and stage < len(stages)) else (stages[0] if typ != "circuit" and stages
                                                                        else None)
            day = _kst_day(h.get("resolvedAt") if d == "exit" else h.get("triggeredAt")) or today
            hits.append(Hit(
                target=t, dir=d, value=_num(ctx.value(t)), unit=_unit(ctx, t),
                asOf=f"{day}.{typ}{stage or ''}", fresh=ctx.fresh(t), chg=_r(_num(ctx.change_pct(t)), 2),
                fields={"stage": stage, "halt_kind": TYPE_KO.get(typ, typ),
                        "approx": "" if h.get("source") == "krx" else "(추정)",
                        "source": _HALT_SRC.get(h.get("source"), str(h.get("source") or "")),
                        "next_stage": _tidy(nxt), "peer": peer, "halt_id": h.get("id")}))
    return hits


# ───────────────────────── B 기록 · 마디 ─────────────────────────
def _extreme(ref, up: bool):
    """(값, 날짜) — 같은 값이 여럿이면 가장 최근 날짜."""
    val = max(c for _, c in ref) if up else min(c for _, c in ref)
    return val, next(d for d, c in reversed(ref) if c == val)


@_market_judge("high52")
def high52(ctx: Context, ev: dict) -> list[Hit]:
    """B1 — 오늘 값이 직전 window 봉(최소 min_points)의 최고/최저를 넘은 첫날만(어제 종가도 넘어 있었으면 아님)."""
    p = ev.get("params") or {}
    window, min_pts = int(p.get("window", 250)), int(p.get("min_points", 60))
    hits = []
    for t in ev.get("targets") or []:
        st = _today(ctx, t)
        if not st:
            continue
        v, day, prior, chg, fresh = st
        ref = prior[-window:]
        if len(ref) < min_pts or fresh == "missing" or (chg is not None and abs(chg) > SANE_PCT):
            continue
        for up in (True, False):
            ext, ext_date = _extreme(ref, up)
            if not (v > ext if up else v < ext):
                continue
            y, y_ref = prior[-1][1], prior[:-1][-window:]
            if len(y_ref) >= min_pts:
                y_ext, _ = _extreme(y_ref, up)
                if (y > y_ext) if up else (y < y_ext):
                    continue                           # 어제도 신고(저)가 = 이어지는 기록, 새 사건 아님
            hits.append(Hit(target=t, dir="up" if up else "down", value=v, unit=_unit(ctx, t), asOf=day,
                            fresh=fresh, chg=_r(chg, 2),
                            fields={"prev_extreme": ext, "prev_date": ext_date,
                                    "next_round": _next_round(ctx, t, v, up)}))
    return hits


@_market_judge("round_level")
def round_level(ctx: Context, ev: dict) -> list[Hit]:
    """B2 — 직전 값과 오늘 값 사이에 마디(step 배수)가 있으면. 여러 개를 건넜으면 가장 멀리 간 마디."""
    steps = (ev.get("params") or {}).get("step") or {}
    hits = []
    for t in ev.get("targets") or []:
        step = _num(steps.get(t))
        st = _today(ctx, t) if step and step > 0 else None
        if not st:
            continue
        v, day, prior, chg, fresh = st
        if fresh == "missing" or (chg is not None and abs(chg) > SANE_PCT):
            continue
        prev = _prev_value(ctx, t, v, prior)
        if prev is None or prev == v:
            continue
        up = v > prev
        if up:
            m = math.floor(v / step + 1e-9) * step        # 오늘 값 이하 가장 큰 마디 — 직전 값보다 위여야 건넌 것
            if not m > prev:
                continue
        else:
            m = (math.floor(v / step + 1e-9) + 1) * step  # 오늘 값보다 큰 가장 작은 마디 — 직전 값 이하여야 건넌 것
            if not m <= prev:
                continue
        hi = max([c for _, c in prior[-250:]] + [v])
        hits.append(Hit(target=t, dir="up" if up else "down", value=v, unit=_unit(ctx, t), asOf=day,
                        fresh=fresh, chg=_r(chg, 2),
                        fields={"level_value": _tidy(m), "next_level": _tidy(m + step if up else m - step),
                                "from_high": _r((v / hi - 1) * 100, 1) if hi else None}))
    return hits


# ───────────────────────── C 임계 · 렌즈 ─────────────────────────
def _mer_indicators(ctx: Context) -> list[dict]:
    return [i for i in (ctx.mer.get("indicators") or []) if isinstance(i, dict) and i.get("id")]


def _lens_target(ctx: Context, ind: dict) -> str:
    """메르 지표 id → 사전 대상 id. LENS_ALIASES → dataPath/seriesPath 가 같은 레지스트리 행 → 그 id 그대로.
    사전이 별칭으로 부르는 것(t10y2y → t10y2y_us)은 별칭 쪽 이름을 쓴다. 레지스트리에 없는 렌즈 전용 지표
    (회사채 · LME 재고 · 운임 · 연금 비중 · 외국인 수급)는 메르 id 그대로."""
    iid = str(ind.get("id"))
    rid = LENS_ALIASES.get(iid)
    path = ind.get("dataPath")
    if rid is None and path:
        rid = next((r["id"] for r in ctx.registry.values()
                    if isinstance(r, dict) and r.get("id") and path in (r.get("dataPath"), r.get("seriesPath"))), None)
    if rid is None and ctx.row(iid):
        rid = ctx.rid(iid)
    if rid is None:
        return iid
    return iid if ctx.rid(iid) == rid else rid


def _lens_line(ind: dict):
    """(선 값, 상향?) — mer_aggregate 가 state 를 정한 그 선(nearest)과 그 선의 방향."""
    lv = _num((ind.get("nearest") or {}).get("level"))
    if lv is None:
        return None
    dirs = [t.get("dir") for t in (ind.get("thresholds") or [])
            if isinstance(t, dict) and t.get("kind") == "level" and _num(t.get("level")) == lv]
    return lv, (dirs[0] if dirs else "up") != "down"


def _lens_points(ind: dict) -> list[tuple[str, float]]:
    """history1y + (끝 점이 current 보다 이르면) current."""
    pts = [(str(p.get("date")), _num(p.get("value"))) for p in (ind.get("history1y") or [])
           if isinstance(p, dict) and p.get("date")]
    pts = [(d, v) for d, v in pts if v is not None]
    cur = ind.get("current") or {}
    cv, ca = _num(cur.get("value")), str(cur.get("asOf") or "")
    if cv is not None and ca and (not pts or (_parse_day(ca) and _parse_day(pts[-1][0])
                                               and _parse_day(ca) > _parse_day(pts[-1][0]))):
        pts.append((ca, cv))
    return pts


def _chain_of(ctx: Context, iid: str) -> dict:
    """그 지표가 들어 있는 사슬 — 지금 달아오른 칸(hotStep)인 사슬 우선, 그다음 최근 글."""
    best = None
    for c in ctx.mer.get("chains") or []:
        if not isinstance(c, dict):
            continue
        ids = [s.get("id") for s in (c.get("steps") or []) if isinstance(s, dict)]
        if iid not in ids:
            continue
        key = (c.get("hotStep") == iid, str(c.get("lastDate") or ""))
        if best is None or key > best[0]:
            best = (key, c, ids.index(iid) + 1)
    if not best:
        return {"chain": "", "chain_id": "", "step": None}
    _, c, step = best
    return {"chain": str(c.get("label") or ""), "chain_id": str(c.get("id") or ""), "step": step}


def _lens_fresh(ctx: Context, target: str) -> str:
    f = ctx.fresh(target)
    return "prev" if f == "missing" else f                 # 렌즈 current 가 있으니 「자료 없음」은 아니다


def _beyond(x: float, lv: float, up: bool) -> bool:
    return x >= lv if up else x <= lv                      # mer_aggregate 의 crossed 와 같은 식


@_market_judge("lens_cross")
def lens_cross(ctx: Context, ev: dict) -> list[Hit]:
    """C1 — crossed 이고 · persist_days 점째 이어진 날(지속이 막 확인된 날만 — 그 뒤 날은 이미 알린 돌파) ·
    first_in_days 안에 같은 선을 같은 쪽으로 넘은 날이 없음. 창 첫 점부터 넘어 있던 선(1년 넘게 넘어 있던
    미 PCE · JGB10 · 한국 CPI)은 돌파한 날이 창 안에 없으므로 걸리지 않는다."""
    p = ev.get("params") or {}
    persist, first_in = int(p.get("persist_days", 2)), int(p.get("first_in_days", 365))
    hits = []
    for ind in _mer_indicators(ctx):
        if ind.get("state") != "crossed":
            continue
        line = _lens_line(ind)
        pts = _lens_points(ind)
        if not line or len(pts) < persist + 1:
            continue                                       # 돌파한 날(그 앞 점은 선 안쪽)을 창 안에서 볼 수 없다
        lv, up = line
        beyond = [_beyond(x, lv, up) for _, x in pts]
        run = 0
        for b in reversed(beyond):
            if not b:
                break
            run += 1
        if run != persist:
            continue                                       # 점이 persist+1 개 이상이라 이 run 은 창 첫 점에서 시작하지 않는다
        start = len(pts) - run
        d0 = _parse_day(pts[start][0])
        earlier = [d for (d, _), b in zip(pts[:start], beyond[:start])
                   if b and (d0 is None or _parse_day(d) is None or (d0 - _parse_day(d)).days <= first_in)]
        if earlier:
            continue                                       # 1년 안에 같은 선을 넘은 적 있음 = 새 돌파 아님
        iid = str(ind["id"])
        target = _lens_target(ctx, ind)
        v, asof = pts[-1][1], pts[-1][0]
        levels = sorted({x for x in (_num(t.get("level")) for t in (ind.get("thresholds") or [])
                                     if isinstance(t, dict) and t.get("kind") == "level") if x is not None})
        nxt = (min((x for x in levels if x > v), default=None) if up
               else max((x for x in levels if x < v), default=None))
        post = max((str(t.get("date") or "") for t in (ind.get("thresholds") or [])
                    if isinstance(t, dict) and t.get("kind") == "level" and _num(t.get("level")) == lv), default="")
        hits.append(Hit(
            target=target, dir="up" if up else "down", value=v, unit=str(ind.get("unit") or ""), asOf=asof,
            fresh=_lens_fresh(ctx, target), chg=None,
            fields={"line": _tidy(lv), **_chain_of(ctx, iid), "post_date": post or None, "next_line": _tidy(nxt),
                    "dist": _r(abs((nxt - v) / v * 100), 2) if (nxt is not None and v) else None, "node": iid}))
    return hits


@_market_judge("lens_near")
def lens_near(ctx: Context, ev: dict) -> list[Hit]:
    """C2 — 주시(near) 진입: 어제는 선에서 near_pct 밖(돌파도 아님)이었고 오늘은 안. 선당 7일 쉼은 편성(B2)이 맡는다."""
    near = float((ev.get("params") or {}).get("near_pct", 2.0))
    hits = []
    for ind in _mer_indicators(ctx):
        if ind.get("state") != "near":
            continue
        line = _lens_line(ind)
        pts = _lens_points(ind)
        if not line or len(pts) < 2:
            continue
        lv, up = line
        (asof, v), (_, y) = pts[-1], pts[-2]
        if not lv or _beyond(v, lv, up) or abs((v - lv) / lv * 100) > near:
            continue
        if _beyond(y, lv, up) or abs((y - lv) / lv * 100) <= near:
            continue                                       # 어제도 주시(또는 돌파) = 진입 아님
        iid = str(ind["id"])
        target = _lens_target(ctx, ind)
        hits.append(Hit(
            target=target, dir="near", value=v, unit=str(ind.get("unit") or ""), asOf=asof,
            fresh=_lens_fresh(ctx, target), chg=None,
            fields={"line": _tidy(lv), "dist": _r(abs((lv - v) / v * 100), 2), **_chain_of(ctx, iid), "node": iid}))
    return hits


@_market_judge("stage_up")
def stage_up(ctx: Context, ev: dict) -> list[Hit]:
    """C3 · C4 — 직전 값 < 단계 ≤ 오늘 값(상향 돌파한 날). 여러 단계를 한 번에 넘었으면 가장 높은 단계."""
    stages = sorted(x for x in (_num(s) for s in ((ev.get("params") or {}).get("stages") or [])) if x is not None)
    hits = []
    for t in ev.get("targets") or []:
        st = _today(ctx, t)
        if not st or not stages:
            continue
        v, day, prior, chg, fresh = st
        prev = _prev_value(ctx, t, v, prior)
        crossed = [s for s in stages if prev is not None and prev < s <= v]
        if fresh == "missing" or not crossed:
            continue
        s = max(crossed)
        peer_t = PEERS.get(t)
        hits.append(Hit(
            target=t, dir="up", value=v, unit=_unit(ctx, t), asOf=day, fresh=fresh, chg=_r(chg, 2),
            fields={"stage": _tidy(s), "next_stage": _tidy(min((x for x in stages if x > s), default=None)),
                    "peer": _name(ctx, peer_t) if peer_t else "", "peer_chg": _chg_text(ctx, peer_t) if peer_t else "",
                    "prev": _r(prev, 2)}))
    return hits


@_market_judge("band_enter")
def band_enter(ctx: Context, ev: dict) -> list[Hit]:
    """C5 — low 미만 또는 high 초과로 진입(직전 값은 그 띠 밖)."""
    p = ev.get("params") or {}
    low, high = _num(p.get("low")), _num(p.get("high"))
    hits = []
    for t in ev.get("targets") or []:
        st = _today(ctx, t)
        if not st:
            continue
        v, day, prior, chg, fresh = st
        prev = _prev_value(ctx, t, v, prior)
        if prev is None or fresh == "missing":
            continue
        if low is not None and v < low and not prev < low:
            d, band, rule = "down", "극단 공포", f"{_tidy(low)} 이상으로 돌아오면 해제"
        elif high is not None and v > high and not prev > high:
            d, band, rule = "up", "극단 탐욕", f"{_tidy(high)} 이하로 내려오면 해제"
        else:
            continue
        hits.append(Hit(target=t, dir=d, value=v, unit=_unit(ctx, t), asOf=day, fresh=fresh, chg=_r(chg, 2),
                        fields={"band_ko": band, "prev": _r(prev, 1), "exit_rule": rule}))
    return hits


def _realized(bars, day: str) -> float | None:
    """day 까지 20거래일 실현변동성(연율 %) — 일간 수익률 표준편차 × √252."""
    closes = [c for d, c in bars if d <= day][-21:]
    r = vol.daily_returns(closes, window=20, exclude_last=False)
    return statistics.pstdev(r) * math.sqrt(252) if len(r) >= 20 else None


@_market_judge("vkospi_rel")
def vkospi_rel(ctx: Context, ev: dict) -> list[Hit]:
    """C6 — VKOSPI 가 코스피 20일 실현변동성의 ratio 배 이상으로 진입했거나, 하루 ±day_pct% 이상.

    이력(events/history/vkospi.json, 없으면 data.json 의 sentiment.vkospi.history)이 min_history 점 미만이면
    판정하지 않는다 — 평소 배수를 모르는 채로 「이상」이라 말하지 않는다."""
    p = ev.get("params") or {}
    min_hist, ratio, day_pct = int(p.get("min_history", 90)), float(p.get("ratio", 1.5)), float(p.get("day_pct", 10))
    hits = []
    for t in ev.get("targets") or []:
        leaf = _get(ctx.data, str((ctx.row(t) or {}).get("dataPath") or "")) if (ctx.row(t) or {}).get("dataPath") else None
        hist = _points(_history_file(ctx, t)) or _points((leaf or {}).get("history") if isinstance(leaf, dict) else None)
        st = _today(ctx, t) if len(hist) >= min_hist else None
        if not st:
            continue
        v, day, prior, chg, fresh = st
        kospi = _bars(ctx, "kospi")
        rv = _realized(kospi, day)
        prev_pt = next(((d, x) for d, x in reversed(hist) if d < day), None)
        r_now = v / rv if rv else None
        r_prev = None
        if prev_pt:
            rv_prev = _realized(kospi, prev_pt[0])
            r_prev = prev_pt[1] / rv_prev if rv_prev else None
        reasons, d = [], None
        if chg is not None and abs(chg) >= day_pct:
            reasons.append(f"하루 {chg:+.1f}%")
            d = "up" if chg > 0 else "down"
        if r_now is not None and r_now >= ratio and (r_prev is None or r_prev < ratio):
            reasons.append(f"실현변동성의 {r_now:.1f}배")
            d = d or "up"
        if not reasons:
            continue
        hits.append(Hit(target=t, dir=d, value=v, unit=_unit(ctx, t), asOf=day, fresh=fresh, chg=_r(chg, 2),
                        fields={"reason": " · ".join(reasons), "realized": _r(rv, 1), "ratio": _r(r_now, 2)}))
    return hits


@_market_judge("rate_jump")
def rate_jump(ctx: Context, ev: dict) -> list[Hit]:
    """C7 — 금리 시계열(yieldCurve series) 끝 두 점 차 |Δ| ≥ bp. 짝 = 같은 날 가장 크게 움직인 다른 대상."""
    bp = float((ev.get("params") or {}).get("bp", 10))
    moves = {}
    for t in ev.get("targets") or []:
        b = _bars(ctx, t)
        if len(b) >= 2:
            moves[t] = (b[-1][0], round((b[-1][1] - b[-2][1]) * 100, 6), b[-1][1])
    hits = []
    for t, (d1, chg_bp, last) in moves.items():
        if abs(chg_bp) < bp:
            continue
        others = [(abs(m), u, m) for u, (dd, m, _) in moves.items() if u != t and dd == d1]
        _, pu, pm = max(others, default=(0, None, None))
        day = _parse_day(d1)
        v = _num(ctx.value(t))
        hits.append(Hit(
            target=t, dir="up" if chg_bp > 0 else "down", value=v if v is not None else last, unit="%",
            asOf=d1, fresh=ctx.fresh(t), chg=None,
            fields={"chg_bp": int(round(chg_bp)), "asof_md": f"{day.month}/{day.day}" if day else d1,
                    "peer": _name(ctx, pu) if pu else "", "peer_chg": f"{int(round(pm)):+d}bp" if pu else ""}))
    return hits


@_market_judge("sign_flip")
def sign_flip(ctx: Context, ev: dict) -> list[Hit]:
    """C8 — 직전 값과 오늘 값의 부호가 갈림(음수로 = 역전, 0 이상으로 = 역전 해소)."""
    hits = []
    for t in ev.get("targets") or []:
        st = _today(ctx, t)
        if not st:
            continue
        v, day, prior, chg, fresh = st
        prev = _prev_value(ctx, t, v, prior)
        if prev is None or fresh == "missing" or (prev < 0) == (v < 0):
            continue
        down = v < 0
        hits.append(Hit(target=t, dir="down" if down else "up", value=v, unit=_unit(ctx, t), asOf=day,
                        fresh=fresh, chg=_r(chg, 2),
                        fields={"flip_ko": "역전" if down else "역전 해소", "prev": _r(prev, 2)}))
    return hits


# ───────────────────────── H 실물 ─────────────────────────
@_market_judge("gold_premium")
def gold_premium(ctx: Context, ev: dict) -> list[Hit]:
    """H1 — |금 김치프리미엄| ≥ abs_pct. 이력(events/history/gold_premium.json)이 min_history 점 미만이면 판정 안 함."""
    p = ev.get("params") or {}
    min_hist, abs_pct = int(p.get("min_history", 30)), float(p.get("abs_pct", 1.0))
    hits = []
    for t in ev.get("targets") or []:
        v = _num(ctx.value(t))
        if len(_points(_history_file(ctx, t))) < min_hist or v is None or abs(v) < abs_pct:
            continue
        a = str(ctx.as_of(t))[:10]
        usd_oz = next((c for d, c in reversed(_bars(ctx, "gold")) if d == a), None)   # 프리미엄을 잰 그날의 국제 금
        hits.append(Hit(target=t, dir="up" if v > 0 else "down", value=v, unit="%", asOf=a, fresh=ctx.fresh(t),
                        chg=None,
                        fields={"krw_g": _num(ctx.value("goldkrw")),
                                "usd_oz": usd_oz if usd_oz is not None else _num(ctx.value("gold"))}))
    return hits
