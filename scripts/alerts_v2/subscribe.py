"""구독 — 원장 새 행 × (기본 켜짐 · 꾸러미 · 별표 · 갈래 · 사용자 조건) → Decision.

/prefs 는 `prefs_client.fetch` 로 읽는다(읽기 키 PUSH_READ_KEY, 없으면 기본 설정만). v1 문서는 `upgrade_prefs` 가 v2 로 바꾼다.
사용자 조건(U1 수준 도달 · U2 급변 값 · 종목 대상 B1 52주 신고 · 신저)은 여기서 판정해 원장에 넣는다 — 발생 키는
ALERTS_STATE_SALT HMAC 12자, 소금이 없으면 사용자 조건은 통째로 건너뛴다(현행 규칙, 평문 해시로 되돌아가지 않는다).
종목(국내 6자리 · 미국 티커) 값은 Context.stock 이 옛 종목 알림의 시세 길로 댄다. 지표 대상 B1 조건은 사전 판정(full 런)
행에 대한 조정이라 match 의 _override 가 맡는다.
U1 은 넘는 순간만 울린다(2026-10-09 사용자 결정) — 직전 쪽은 공개 파일 alerts_state.json._prefs[조건 id].side 한 글자
(u 임계 위 · d 아래)로만 남기고, 임계 · 값은 남기지 않는다. 사용자 조건은 그 파일을 커밋하는 런(stock-alerts 의 light)만 본다.
쪽(관측)과 울림 기록(ts · fired)은 따로 — 울림 기록은 원장에 들어가 실제로 나간 행만(mark_sent).
사람별(2026-10-27 멤버): 공개 기록 키는 state_key — 마스터는 조건 id 그대로(지금 키), 멤버는 HMAC(uid:조건 id).
멤버 사용자 조건 행은 공개 원장에 넣지 않으므로 같은 발생 · 쿨다운을 그 기록의 keys(발생 HMAC) · ts · fd(방향 한 글자)로 본다
(member_fresh · mark_member). 멤버 하루 울림 수는 state_key(uid, member, "@day") 한 칸({d: 날짜, n: 수}).
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


def load_all_prefs(log=print) -> list[tuple[str, str, dict]] | None:
    """사람별 설정 [(uid, role, v2 로 올린 prefs)].
    None = 읽기 키 없음 · 읽기 실패 · 일부만 받음 · 한 사람이라도 변환 실패 — 호출 쪽은 정리(_prefs 가지치기)를 건너뛰어야 한다.
    [] = 정말로 활성 사용자가 0명. role 은 owner/member 외에는 member 로 낮춘다(최소 권한)."""
    try:
        import prefs_client
    except ImportError:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import prefs_client
    if not prefs_client.auth_header():
        log("[v2] PUSH_READ_KEY 없음 — 사람별 설정 없음(기본 설정으로 구독)")
        return None
    users = prefs_client.fetch_all(PREFS_URL)
    if users is None:
        return None
    out, fixed = [], 0
    for u in users:
        role = u.get("role")
        if role not in ("owner", "member"):
            role, fixed = "member", fixed + 1
        try:
            out.append((u["uid"], role, upgrade_prefs(u["prefs"])))
        except Exception as e:                                # noqa: BLE001 — 한 사람 실패는 부분 실패
            log(f"[v2] 사람별 설정 변환 실패({type(e).__name__}) — 일부만 읽힌 것으로 보고 건너뜁니다")
            return None
    if fixed:
        log(f"[v2] 역할 값이 다른 {fixed}명은 member 로 낮춤")
    return out


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


DAY_SLOT = "@day"                                   # 멤버 하루 울림 수 칸의 이름(state_key 로 HMAC 된다 — 조건 id 와 겹치지 않는 글자)
MEMBER_KEYS_KEEP = 5                                # 멤버 조건 기록에 남기는 발생 HMAC 수


def state_key(uid: str, role: str, cond_id: str) -> str | None:
    """공개 alerts_state.json._prefs 의 키. 마스터 = 조건 id 그대로(지금 키 — 바뀌면 쪽 · 울림 기록이 끊긴다),
    멤버 = HMAC(ALERTS_STATE_SALT, uid:조건 id) 12자 — 공개 파일에 멤버의 uid · 조건 id 원문이 남지 않는다.
    소금이 없으면 멤버 키는 None(그 멤버의 사용자 조건은 판정하지 않는다)."""
    if role == "owner":
        return cond_id
    return hmac_key(f"{uid}:{cond_id}")


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


def since_arm(prefs: dict | None, history: list[dict]) -> list[dict]:
    """다시 켠(armedAt) 조건의 그 전 행은 뺀다 — 쿨다운 · 「한 번」 판정은 지금 켠 뒤의 울림만 본다."""
    armed = {a.get("id"): _sec(a["armedAt"]) for a in (prefs or {}).get("alerts") or [] if a.get("armedAt")}
    return [r for r in history if not (r.get("cond") in armed and _sec(r.get("ts")) <= armed[r["cond"]])]


def mark_sent(sides: dict | None, prefs: dict | None, rows: list[dict], ledger, now: dt.datetime) -> None:
    """이번 런에 원장에 들어가 실제로 나간(sent 의 어느 칸이든 참) 사용자 조건 행만 공개 기록에 ts(초) ·
    「한 번」이면 fired 를 남긴다 — 쿨다운 · 발송 실패로 안 나간 행은 남기지 않는다(화면 「울림」 · 멈춤과 같은 기준)."""
    if sides is None:
        return
    once = {a.get("id") for a in (prefs or {}).get("alerts") or [] if a.get("repeat") == "once"}
    for r in rows:
        sent = (ledger.get(r["key"]) or {}).get("sent") or {}
        if not any(sent.get(k) for k in ("push", "kakao", "discord", "memo", "held")):   # 보류도 나간 것(아침 합류)
            continue
        rec = sides.get(r["cond"])
        rec = dict(rec) if isinstance(rec, dict) else {}
        rec["ts"] = int(now.timestamp())
        if r["cond"] in once:
            rec["fired"] = True
        sides[r["cond"]] = rec


def _occ(row: dict) -> str:
    """사용자 조건 행 key 의 끝 칸 = 발생 HMAC(조건 id · armedAt · 기준일 · 방향, 소금 HMAC 12자)."""
    return str(row.get("key") or "").rsplit(":", 1)[-1]


def _fd(direction) -> str:
    return "d" if direction == "down" else "u"


def member_fresh(rows: list[dict], prefs: dict | None, sides: dict | None, key, events_by_id: dict | None,
                 now: dt.datetime) -> list[dict]:
    """멤버 사용자 조건 행 거르기 — 공개 원장에 넣지 않으므로 원장 키(같은 발생 한 번) · 원장 쿨다운 대신
    공개 기록 sides[key(조건 id)] 의 keys(최근 발생 HMAC) · ts · fd(마지막 울림 방향)로 막는다.
    쿨다운 = 사전 cooldown.days 안에 같은 방향으로 울렸으면(다시 켠 armedAt 뒤의 울림만 센다). 남의 행(공개 원장)은 안 본다."""
    conds = {a.get("id"): a for a in (prefs or {}).get("alerts") or [] if isinstance(a, dict)}
    out = []
    for r in rows:
        rec = (sides or {}).get(key(r.get("cond")))
        rec = rec if isinstance(rec, dict) else {}
        if _occ(r) in (rec.get("keys") or []):
            continue
        days = int((((events_by_id or {}).get(r.get("event")) or {}).get("cooldown") or {}).get("days") or 0)
        c = conds.get(r.get("cond")) or {}
        armed = _sec(c["armedAt"]) if c.get("armedAt") else 0.0
        ts = rec.get("ts")
        if (days > 0 and isinstance(ts, (int, float)) and ts > armed and rec.get("fd") == _fd(r.get("dir"))
                and now.timestamp() - ts < days * 86400):
            continue
        out.append(r)
    return out


def mark_member(sides: dict | None, prefs: dict | None, rows: list[dict], sent_keys: set, now: dt.datetime,
                key) -> None:
    """멤버 판 mark_sent — 원장이 없으니 실제로 나간 행(sent_keys: 푸시 큐 적재 또는 조용한 시간 보류)만 공개 기록에
    ts · fd · keys(발생 HMAC 최근 MEMBER_KEYS_KEEP 개) · 「한 번」 fired 를 남긴다. 값 · 임계 · 대상은 남기지 않는다."""
    if sides is None:
        return
    once = {a.get("id") for a in (prefs or {}).get("alerts") or [] if a.get("repeat") == "once"}
    for r in rows:
        if r.get("key") not in sent_keys:
            continue
        k = key(r["cond"])
        if not k:
            continue
        rec = dict(sides[k]) if isinstance(sides.get(k), dict) else {}
        rec["ts"] = int(now.timestamp())
        rec["fd"] = _fd(r.get("dir"))
        rec["keys"] = ([x for x in rec.get("keys") or [] if isinstance(x, str)] + [_occ(r)])[-MEMBER_KEYS_KEEP:]
        if r["cond"] in once:
            rec["fired"] = True
        sides[k] = rec


def _stock_b1(ctx, target: str, want: str | None):
    """종목 52주 신고 · 신저 — 사전 B1 의 판정 함수(high52)를 그 종목 하나에 그대로 쓴다(일봉 = 옛 종목 알림의 1년 일봉).
    → (Hit 또는 None, 사전 B1 행). 조건에 방향(dir)이 있으면 그 방향만."""
    from . import judges_market, schema
    ev = schema.by_id(schema.load_events()).get("B1") or {}
    hits = [h for h in judges_market.high52(ctx, dict(ev, targets=[target])) if want in (None, h.dir)]
    return (hits[0] if hits else None), ev


def user_hits(ctx, prefs: dict | None, history: list[dict], render=None, log=print,
              sides: dict | None = None, key=None) -> list[Row]:
    """U1 · U2 · 종목 B1 판정 → 원장 행(아직 원장엔 안 넣음). 소금 없으면 빈 목록.

    sides = alerts_state.json._prefs(키 → {side?, at?, ts?, fired?}) — U1 의 직전 쪽은 그 자리에서 고친다.
    key = 조건 id → 공개 기록 키(state_key). 없으면 조건 id 그대로(마스터).
    U1 은 직전 쪽이 반대편이었다가 이번에 임계를 넘었을 때만 울린다. 처음 보는 조건 · 깨진 기록은 지금 쪽만 남긴다.
    sides 가 None 이면(깨진 파일) U1 은 보지 않는다. U2 · B1 은 하루 한 번(원장 키). 울림 기록(ts · fired)은 mark_sent."""
    if not prefs:
        return []
    key = key or (lambda cid: cid)
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
        rec = (sides or {}).get(key(c.get("id")))
        rec = rec if isinstance(rec, dict) else {}
        if c.get("repeat") == "once" and _fired_after_arm(c, history, rec):
            continue
        if c["event"] == "U1" and sides is None:
            continue
        val = ctx.value(target)
        sc = ctx.scale(target)
        if val is not None and sc:
            val = float(val) / sc                # 화면 단위 — 조건 값은 사용자가 화면에서 본 그대로(엔/원 원본 9.3 → 930원)
        chg = ctx.change_pct(target)
        hit = None
        # 공개 원장(G5): 임계값 · 사용자가 붙인 이름은 행에 싣지 않는다 — 화면이 cond id 로 이 기기에서 붙인다
        if c["event"] == "B1":
            hit, b1 = _stock_b1(ctx, target, c.get("dir")) if val is not None else (None, {})
        elif c["event"] == "U1" and val is not None:
            d = c.get("dir") or "up"
            met = float(val) >= float(thr) if d == "up" else float(val) <= float(thr)
            side = ("u" if met else "d") if d == "up" else ("d" if met else "u")
            prev, new = rec.get("side"), dict(rec, side=side)   # 공개 기록 — 쪽 한 글자만(임계 · 값 없음)
            armed = int(_sec(c["armedAt"])) if c.get("armedAt") else 0
            if armed and not (isinstance(rec.get("at"), int) and rec["at"] >= armed):
                # 저장 · 켜기(armedAt) 뒤 첫 관측 — 남은 쪽은 예전 임계 · 꺼 둔 동안의 것이라 화면이 그 순간 잰 쪽(armSide)을
                # 직전 쪽으로 본다(없으면 첫 관측 무음). at = 이 기록이 그 켜기를 반영한 때
                prev, new["at"] = c.get("armSide"), max(int(ctx.now.timestamp()), armed)
            crossed = met and prev in ("u", "d") and prev != side
            sides[key(c["id"])] = new
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
        k = hmac_key(f"{c['id']}:{c.get('armedAt', '')}:{hit.asOf}:{hit.dir}", salt)   # 다시 켜면 새 키
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


ALWAYS_ON = {"A5"}                                  # 서킷브레이커 · 사이드카 — 「켜짐(끌 수 없음)」(기획서 3장)


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


def match(rows: list[dict], ctx, prefs: dict | None = None, events_by_id: dict | None = None,
          uid: str | None = None, role: str | None = None) -> list[Decision]:
    """원장 행 × 한 사람의 설정 → Decision(그 사람 uid · role 을 단다)."""
    out = _match(rows, prefs, events_by_id)
    for d in out:
        d.uid, d.role = uid, role
    return out


def _match(rows: list[dict], prefs: dict | None, events_by_id: dict | None) -> list[Decision]:
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
            mine = next((a for a in (prefs or {}).get("alerts") or [] if a.get("id") == cond_id), {})
            if mine.get("ring") is False:              # 「울림 끄기」 = 받은 알림(원장)에만(기획서 7장 여섯 칸 「울림」)
                out.append(Decision(r, level, False, "울림 끔", cond_id, on=False))
                continue
            out.append(Decision(r, level, True, "내 조건", cond_id))
            continue
        ov = _override(prefs, r)
        if ov:
            if ov.get("enabled") is False:
                out.append(Decision(r, level, False, "꺼짐", ov.get("id"), on=False))
                continue
            if ov.get("level") in LEVELS:
                level = ov["level"]
        fam = ev.get("family")
        if fam and families.get(fam) is False and r.get("event") not in ALWAYS_ON:
            out.append(Decision(r, level, False, "갈래 꺼짐", on=False))
            continue
        if not strength_ok(r, ev, ov):
            out.append(Decision(r, "record", False, "세기 미달", on=False))   # 2σ 는 넘었지만 내 세기엔 못 미침 — 기록만
            continue
        target = r.get("target")
        # 대상이 묶음(렌즈 · 일정 …)인 사건은 행 대상이 노드 id 다 — default_on 이 있으면 그 사건 전체가 켜짐(기획서 3장 C1 「켜짐」,
        # 기본 지표 5개는 escalate 로 경보). 종전엔 그 5개만 울렸다.
        on = target in (ev.get("default_on") or []) or (bool(ev.get("default_on"))
                                                        and (target in SPECIAL_TARGETS or bool(set(ev.get("targets") or []) & SPECIAL_TARGETS)))
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
        out.append(Decision(r, level, ring, reason,
                            on=on or r.get("event") in ALWAYS_ON or (prefs is None and level == "notice")))
    return out
