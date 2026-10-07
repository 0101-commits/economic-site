"""구독 — 원장 새 행 × (기본 켜짐 · 꾸러미 · 별표 · 갈래 · 사용자 조건) → Decision.

/prefs 는 `prefs_client.fetch` 로 읽는다(읽기 키 PUSH_READ_KEY 우선, 둘 다 없으면 기본 설정만). v1 문서는 `upgrade_prefs` 가 v2 로 바꾼다.
사용자 조건(U1 수준 도달 · U2 급변 값)은 여기서 판정해 원장에 넣는다 — 발생 키는 ALERTS_STATE_SALT HMAC 12자,
소금이 없으면 사용자 조건은 통째로 건너뛴다(현행 규칙, 평문 해시로 되돌아가지 않는다).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os

from . import LEVELS, PACKAGES, SIGMA
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
    # 읽기 키(PUSH_READ_KEY)가 있으면 그것으로, 없을 때만 ALERTS_SYNC_KEY(전환기 호환) — 고르는 일은 prefs_client 한 곳.
    if not prefs_client.auth_header():
        log("[v2] PUSH_READ_KEY · ALERTS_SYNC_KEY 없음 — 기본 설정으로 구독(사용자 조건 · 별표 없음)")
        return None
    doc = prefs_client.fetch(PREFS_URL)
    if not doc or not doc.get("updatedAt"):
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


def _fired_after_arm(cond: dict, history: list[dict]) -> bool:
    """한 번(once) 조건: armedAt 뒤에 이미 울린 행이 있으면 멈춤."""
    armed = cond.get("armedAt") or ""
    for r in history:
        if r.get("cond") != cond.get("id"):
            continue
        if r.get("ts", "") > armed:
            return True
    return False


def user_hits(ctx, prefs: dict | None, history: list[dict], render=None, log=print) -> list[Row]:
    """U1 · U2 판정 → 원장 행(아직 원장엔 안 넣음). 소금 없으면 빈 목록."""
    if not prefs:
        return []
    salt = _salt()
    conds = [a for a in prefs.get("alerts") or [] if a.get("enabled", True) and a.get("event") in ("U1", "U2")]
    if conds and not salt:
        log("[v2] ALERTS_STATE_SALT 없음 — 사용자 조건 판정 건너뜀")
        return []
    rows: list[Row] = []
    today = ctx.now.date().isoformat()
    for c in conds:
        target = c.get("target")
        thr = c.get("value")
        if not target or thr is None:
            continue
        if c.get("repeat") == "once" and _fired_after_arm(c, history):
            continue
        val = ctx.value(target)
        chg = ctx.change_pct(target)
        hit = None
        # 공개 원장(G5): 임계값 · 사용자가 붙인 이름은 행에 싣지 않는다 — 화면이 cond id 로 이 기기에서 붙인다
        if c["event"] == "U1" and val is not None:
            d = c.get("dir") or "up"
            if (d == "up" and float(val) >= float(thr)) or (d == "down" and float(val) <= float(thr)):
                hit = Hit(target=target, dir=d, value=val, unit="", asOf=ctx.as_of(target), fresh=ctx.fresh(target),
                          chg=chg, fields={"dir_ko": U1_DIR_KO[d]})
        elif c["event"] == "U2" and chg is not None:
            if abs(float(chg)) >= float(thr):
                d = "up" if float(chg) > 0 else "down"
                hit = Hit(target=target, dir=d, value=val, unit="", asOf=ctx.as_of(target), fresh=ctx.fresh(target),
                          chg=chg, fields={})
        if not hit:
            continue
        ev = {"id": c["event"], "level": c.get("level") or "alert", "url": f"#/i/{target}",
              "title": "{name} {value} · 내 조건 {dir_ko}" if c["event"] == "U1" else "{name} {chg:+.1f}% · {value}",
              "why": ["내 조건"], "next": []}
        txt = render(ev, hit) if render else {"title": ev["title"], "why": "내 조건", "next": "", "url": ev["url"]}
        k = hmac_key(f"{c['id']}:{hit.asOf}:{hit.dir}", salt)
        row = Row(key=f"{c['event']}:{target}:{hit.dir}:{k}", event=c["event"], target=target, dir=hit.dir,
                  level=ev["level"] if ev["level"] in LEVELS else "alert", value=hit.value, unit="",
                  asOf=hit.asOf, fresh=hit.fresh, title=txt["title"], why=txt.get("why", ""), next=txt.get("next", ""),
                  url=txt.get("url") or ev["url"], ts=ctx.now.isoformat(timespec="seconds"))
        d = row.to_dict()
        d["cond"] = c["id"]                      # 조건 id 만(임계값 없음) — 화면이 이름을 찾는 열쇠
        rows.append(d)
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
