"""구독 — 원장 새 행 × (기본 켜짐 · 꾸러미 · 별표 · 갈래 · 사용자 조건) → Decision.

/prefs 는 `prefs_client.fetch` 로 읽는다(읽기 키 PUSH_READ_KEY, 없으면 기본 설정만). v1 문서는 `upgrade_prefs` 가 v2 로 바꾼다.
사용자 조건(U1 수준 도달 · U2 급변 값 · 종목 대상 B1 52주 신고 · 신저)은 여기서 판정해 원장에 넣는다 — 발생 키는
ALERTS_STATE_SALT HMAC 12자, 소금이 없으면 사용자 조건은 통째로 건너뛴다(현행 규칙, 평문 해시로 되돌아가지 않는다).
종목(국내 6자리 · 미국 티커) 값은 Context.stock 이 옛 종목 알림의 시세 길로 댄다. 지표 대상 B1 조건은 사전 판정(full 런)
행에 대한 조정이라 match 의 _override 가 맡는다.
U1 은 넘는 순간만 울린다(2026-10-09 사용자 결정) — 직전 쪽은 공개 파일 alerts_state.json._prefs[조건 id].side 한 글자
(u 임계 위 · d 아래)로만 남기고, 임계 · 값은 남기지 않는다. 그 파일을 커밋하는 런(stock-alerts 의 light)만 U1 을 본다.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os

from . import LEVELS, PACKAGES, SIGMA
from .context import is_stock
from .events import Hit
from .ledger import Ledger, Row
from .model import DEFAULT_SETTINGS, Decision

# Worker 바탕 주소 — prefs_client.fetch 가 /prefs 를 붙인다(/prefs 까지 적으면 /prefs/prefs 로 가서 상태 JSON 을 받고 「모양이 다름」이 된다, 2026-10-06 실측)
PREFS_URL = os.environ.get("PREFS_URL", "https://ecom-dashboard-proxy.e-hcg.workers.dev").rstrip("/").removesuffix("/prefs")
# 대상이 「지표」가 아닌 사건들 — 별표와 무관하게 사전 default_on 이 결정한다
SPECIAL_TARGETS = {"calendar", "lens", "regime", "stance", "posts", "mri", "chains", "monthly", "regions",
                   "enso", "movers", "watch_stocks", "bundle"}
V1_EVENT = {"price": "U1", "pct": "U2", "high52": "B1", "event": "E1", "flow": "D2", "lens": "C1"}
U1_DIR_KO = {"up": "위로", "down": "아래로"}


# ---------- 설정 읽기 ----------
def load_prefs(log=print) -> dict | None:
    try:
        import prefs_client
    except ImportError:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import prefs_client
    # 읽기 키(PUSH_READ_KEY) 하나로 읽는다 — 키를 고르는 일은 prefs_client 한 곳.
    if not prefs_client.auth_header():
        log("[v2] PUSH_READ_KEY 없음 — 기본 설정으로 구독(사용자 조건 · 별표 없음)")
        return None
    doc = prefs_client.fetch(PREFS_URL)
    if not doc:
        return None
    if not doc.get("updatedAt"):
        log("[v2] /prefs 비어 있음 — 기본 설정으로 구독(사용자 조건 · 별표 없음)")
        return None
    return upgrade_prefs(doc)


def upgrade_prefs(doc: dict) -> dict:
    """v1(type 6종) → v2(event · strength · ring). v2 는 그대로."""
    out = dict(doc)
    alerts = []
    for a in doc.get("alerts") or []:
        a = dict(a)
        if a.get("event"):
            alerts.append(a)
            continue
        t = a.pop("type", None)
        cond = a.pop("cond", {}) or {}
        ev = V1_EVENT.get(t)
        if not ev:
            continue
        a["event"] = ev
        a["repeat"] = "once" if a.get("repeat") == "once" else "each"
        a["ring"] = "push" in (a.get("channels") or ["push"]) or "discord" in (a.get("channels") or [])
        if ev == "U1":
            a["dir"] = "down" if cond.get("op") == "<=" else "up"
            a["value"] = cond.get("value")
        elif ev == "U2":
            a["value"] = abs(float(cond.get("value") or 0))
            a["dir"] = "down" if float(cond.get("value") or 0) < 0 else "up"
        elif ev == "B1":
            a["dir"] = "down" if cond.get("side") == "low" else "up"
        elif ev == "D2" and a.get("target") and a["target"] != "kospi":
            a["event"] = "D5"
        if cond.get("armedAt"):
            a["armedAt"] = cond["armedAt"]
        a.pop("channels", None)
        alerts.append(a)
    out["alerts"] = alerts
    s = dict(DEFAULT_SETTINGS)
    raw = doc.get("settings") or {}
    is_v2 = doc.get("v") == 2 or "package" in raw
    # v1 의 quiet:null 은 「미설정」 → 기본 23:00~07:00, v2 의 quiet:null 은 「끔」 그대로(화면 prefsV2 와 같은 규칙)
    s.update({k: v for k, v in raw.items() if v is not None or (is_v2 and k == "quiet")})
    if s.get("package") not in PACKAGES:
        s["package"] = "normal"
    out["settings"] = s
    out["v"] = 2
    return out


# ---------- 사용자 조건 ----------
def _salt() -> bytes | None:
    return os.environ.get("ALERTS_STATE_SALT", "").strip().encode("utf-8") or None


def hmac_key(raw: str, salt: bytes | None = None) -> str | None:
    salt = salt or _salt()
    if not salt:
        return None
    return hmac.new(salt, raw.encode("utf-8"), hashlib.sha256).hexdigest()[:12]


def _sec(iso) -> float:
    """ISO 시각 → 초. 화면 armedAt 은 UTC(Z), 원장 ts 는 KST(+09:00)라 글자로 견주면 9시간 어긋난다. 못 읽으면 0."""
    try:
        t = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (t if t.tzinfo else t.replace(tzinfo=dt.timezone(dt.timedelta(hours=9)))).timestamp()


def _fired_after_arm(cond: dict, history: list[dict], rec: dict | None = None) -> bool:
    """한 번(once) 조건: armedAt 뒤에 이미 울렸으면 멈춤 — 원장 행(8일) 또는 공개 기록 _prefs[id] 의 fired · ts
    (원장 창보다 오래된 울림. 화면 alertStatus.condStatus 와 같은 규칙)."""
    armed = _sec(cond.get("armedAt")) if cond.get("armedAt") else 0.0
    if isinstance(rec, dict) and rec.get("fired") and isinstance(rec.get("ts"), (int, float)) and rec["ts"] > armed:
        return True
    return any(r.get("cond") == cond.get("id") and _sec(r.get("ts")) > armed for r in history)


def _stock_b1(ctx, target: str, want: str | None):
    """종목 52주 신고 · 신저 — 사전 B1 의 판정 함수(high52)를 그 종목 하나에 그대로 쓴다(일봉 = 옛 종목 알림의 1년 일봉).
    → (Hit 또는 None, 사전 B1 행). 조건에 방향(dir)이 있으면 그 방향만."""
    from . import judges_market, schema
    ev = schema.by_id(schema.load_events()).get("B1") or {}
    hits = [h for h in judges_market.high52(ctx, dict(ev, targets=[target])) if want in (None, h.dir)]
    return (hits[0] if hits else None), ev


def user_hits(ctx, prefs: dict | None, history: list[dict], render=None, log=print,
              sides: dict | None = None) -> list[Row]:
    """U1 · U2 · 종목 B1 판정 → 원장 행(아직 원장엔 안 넣음). 소금 없으면 빈 목록.

    sides = alerts_state.json._prefs(조건 id → {side, ts?, fired?}) — U1 의 직전 쪽. 그 자리에서 고친다.
    U1 은 직전 쪽이 반대편이었다가 이번에 임계를 넘었을 때만 울린다. 처음 보는 조건 · 깨진 기록은 지금 쪽만 남긴다.
    sides 가 None 이면(직전 쪽을 커밋하지 않는 런) U1 은 보지 않는다. U2 · B1 은 하루 한 번(원장 키)."""
    if not prefs:
        return []
    salt = _salt()
    conds = [a for a in prefs.get("alerts") or [] if a.get("enabled", True)
             and (a.get("event") in ("U1", "U2") or (a.get("event") == "B1" and is_stock(a.get("target"))))]
    if conds and not salt:
        log("[v2] ALERTS_STATE_SALT 없음 — 사용자 조건 판정 건너뜀")
        return []
    rows: list[Row] = []
    today = ctx.now.date().isoformat()
    for c in conds:
        target = c.get("target")
        thr = c.get("value")
        if not target or (thr is None and c["event"] != "B1"):
            continue
        rec = (sides or {}).get(c.get("id"))
        rec = rec if isinstance(rec, dict) else {}
        if c.get("repeat") == "once" and _fired_after_arm(c, history, rec):
            continue
        if c["event"] == "U1" and sides is None:
            continue
        val = ctx.value(target)
        chg = ctx.change_pct(target)
        hit = None
        # 공개 원장(G5): 임계값 · 사용자가 붙인 이름은 행에 싣지 않는다 — 화면이 cond id 로 이 기기에서 붙인다
        if c["event"] == "B1":
            hit, b1 = _stock_b1(ctx, target, c.get("dir")) if val is not None else (None, {})
        elif c["event"] == "U1" and val is not None:
            d = c.get("dir") or "up"
            met = float(val) >= float(thr) if d == "up" else float(val) <= float(thr)
            side = ("u" if met else "d") if d == "up" else ("d" if met else "u")
            crossed = met and rec.get("side") in ("u", "d") and rec["side"] != side
            sides[c["id"]] = dict(rec, side=side)          # 공개 기록 — 쪽 한 글자만(임계 · 값 없음)
            if crossed:
                hit = Hit(target=target, dir=d, value=val, unit="", asOf=ctx.as_of(target), fresh=ctx.fresh(target),
                          chg=chg, fields={"dir_ko": U1_DIR_KO[d]})
        elif c["event"] == "U2" and chg is not None:
            if abs(float(chg)) >= float(thr):
                d = "up" if float(chg) > 0 else "down"
                hit = Hit(target=target, dir=d, value=val, unit="", asOf=ctx.as_of(target), fresh=ctx.fresh(target),
                          chg=chg, fields={})
        if not hit:
            continue
        if is_stock(target):                     # 종목 이름(공개 시세의 이름) — 없으면 코드 그대로
            hit.fields.setdefault("name", (ctx.stock(target) or {}).get("name"))
        ev = {"id": c["event"], "level": c.get("level") or "alert", "url": f"#/i/{target}",
              "title": "{name} {value} · 내 조건 {dir_ko}" if c["event"] == "U1" else "{name} {chg:+.1f}% · {value}",
              "why": ["내 조건"], "next": []}
        if c["event"] == "B1":                   # 문구는 사전 B1 틀 그대로(직전 신고 · 신저와 그 날짜)
            ev.update({k: b1[k] for k in ("title", "why", "next") if k in b1})
        txt = render(ev, hit) if render else {"title": ev["title"], "why": "내 조건", "next": "", "url": ev["url"]}
        k = hmac_key(f"{c['id']}:{hit.asOf}:{hit.dir}", salt)
        row = Row(key=f"{c['event']}:{target}:{hit.dir}:{k}", event=c["event"], target=target, dir=hit.dir,
                  level=ev["level"] if ev["level"] in LEVELS else "alert", value=hit.value, unit="",
                  asOf=hit.asOf, fresh=hit.fresh, title=txt["title"], why=txt.get("why", ""), next=txt.get("next", ""),
                  url=txt.get("url") or ev["url"], ts=ctx.now.isoformat(timespec="seconds"))
        d = row.to_dict()
        d["cond"] = c["id"]                      # 조건 id 만(임계값 없음) — 화면이 이름을 찾는 열쇠
        rows.append(d)
        if c["event"] == "U1":                   # 화면 상태(울림 · 멈춤)와 원장 창 밖의 「한 번」 멈춤용
            sides[c["id"]]["ts"] = int(ctx.now.timestamp())
            if c.get("repeat") == "once":
                sides[c["id"]]["fired"] = True
    return rows


# ---------- 구독 매칭 ----------
def _watch_ids(prefs: dict | None) -> set[str]:
    return {w.get("id") for w in ((prefs or {}).get("watch") or []) if isinstance(w, dict) and w.get("id")}


def _override(prefs: dict | None, row: dict) -> dict | None:
    """사전 사건에 대한 사용자 조정(같은 event + target 또는 target '*')."""
    for a in (prefs or {}).get("alerts") or []:
        if a.get("event") == row.get("event") and a.get("target") in (row.get("target"), "*"):
            return a
    return None


def strength_ok(row: dict, ev: dict, override: dict | None) -> bool:
    """급변 사건(swing_sigma)의 사용자 세기 — 사전은 2.0σ 로 넓게 잡아 원장에 두고, 울림은 여기서 거른다.
    세기 = override.strength(normal 2σ · big 2.5σ · huge 3σ · value = override.value %), 없으면 big.
    임계 = min(max(kσ, 하한), 상한)(사전 clamp_pct, 현행 check_swings 와 같은 식). σ = |등락| / z."""
    if ev.get("judge") != "swing_sigma":
        return True
    chg, z = row.get("chg"), row.get("z")
    if chg is None or not z:
        return True                                   # 세기를 잴 수 없으면 사전 판정 그대로
    p = ev.get("params") or {}
    lo, hi = (list(p.get("clamp_pct") or [0.5, 5.0]) + [5.0])[:2]
    st = (override or {}).get("strength") or "big"
    if st == "value":
        thr = float((override or {}).get("value") or 0) or None
        return thr is None or abs(float(chg)) >= thr
    sigma = abs(float(chg)) / float(z)
    thr = min(max(SIGMA.get(st, 2.5) * sigma, float(lo)), float(hi))
    return abs(float(chg)) >= thr


def match(rows: list[dict], ctx, prefs: dict | None = None, events_by_id: dict | None = None) -> list[Decision]:
    settings = dict(DEFAULT_SETTINGS)
    settings.update((prefs or {}).get("settings") or {})
    package = settings.get("package") if settings.get("package") in PACKAGES else "normal"
    families = settings.get("families") or DEFAULT_SETTINGS["families"]
    watch = _watch_ids(prefs)
    out: list[Decision] = []
    for row in rows:
        r = row.to_dict() if isinstance(row, Row) else row
        ev = (events_by_id or {}).get(r.get("event"), {})
        level = r.get("level") if r.get("level") in LEVELS else ev.get("level", "notice")
        cond_id = r.get("cond")
        if cond_id or str(r.get("event", "")).startswith("U"):
            out.append(Decision(r, level, True, "내 조건", cond_id))
            continue
        ov = _override(prefs, r)
        if ov:
            if ov.get("enabled") is False:
                out.append(Decision(r, level, False, "꺼짐", ov.get("id")))
                continue
            if ov.get("level") in LEVELS:
                level = ov["level"]
        fam = ev.get("family")
        if fam and families.get(fam) is False:
            out.append(Decision(r, level, False, "갈래 꺼짐"))
            continue
        if not strength_ok(r, ev, ov):
            out.append(Decision(r, "record", False, "세기 미달"))      # 2σ 는 넘었지만 내 세기엔 못 미침 — 기록만
            continue
        target = r.get("target")
        on = target in (ev.get("default_on") or []) or (target in SPECIAL_TARGETS and bool(ev.get("default_on")))
        reason = "기본 켜짐" if on else ""
        if not on and target in watch:
            on, reason = True, "관심"
        if ov and ov.get("ring") is not None:
            on, reason = bool(ov["ring"]), "내 설정"
        if level == "record":
            out.append(Decision(r, level, False, "기록"))
            continue
        if package == "quiet":
            ring = on and level == "alarm"
            reason = reason if ring else "꾸러미 조용히"
        elif package == "many":
            ring = on
            if ring and level == "notice":
                level = "alert"                      # 많이 = 안내도 울림
        else:
            ring = on and level in ("alarm", "alert")
            if on and level == "notice":
                reason = "안내"
        if not on and not reason:
            reason = "관심 아님"
        out.append(Decision(r, level, ring, reason))
    return out
