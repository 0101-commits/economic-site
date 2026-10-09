"""판정 문맥 — data.json · bundles · registry · mer_signals · 달력을 한 번 읽고, 값의 단일 원천을 준다.

`value(target)` 는 번들(화면과 같은 값)에서 먼저 찾고, 없으면 레지스트리 dataPath 로 data.json 을 본다.
`series(target, n)` 은 레지스트리 seriesPath(없으면 dataPath) 의 일봉 n개 [{date, close}] 를 준다.
사전 · 레지스트리 밖의 종목(국내 6자리 · 미국 티커 — 사용자 조건의 대상)은 `stock(target)` 이 값을 대고,
같은 다섯 함수가 그것을 그대로 돌려준다(아래 「종목」 절).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUNDLE_FILES = ("home", "market-domestic", "market-global", "market-fxrates", "market-commodities",
                "market-macro", "market-flows", "market-realestate", "lens", "meta")

# 사전 대상 id → 레지스트리 id 가 다를 때의 별칭(레지스트리에 없는 번들 칸 포함)
# vix · ff_target 은 레지스트리 id 가 그대로다(vix_us · ff_target_us 라는 행은 없다 — 2026-10-05 실측, 값이 늘 None 이었다).
ALIASES = {
    "btc": "btc", "vix": "vix", "move": "move", "fear_greed": "fear_greed", "vkospi": "vkospi",
    "t10y2y": "t10y2y_us", "ff_target": "ff_target", "gold_premium": "gold_premium",
}
# 메르 렌즈 지표 id → 레지스트리 id. 대부분은 dataPath 비교로 이어지고, 이어지지 않는 것만 적는다.
# 렌즈는 일본 국채를 mer_series.jgb 에서 읽어 경로가 레지스트리(yieldCurve.jp)와 다르다.
LENS_ALIASES = {"jgb10y": "jp10y", "jgb30y": "jp30y"}
# 레지스트리에 행이 없는 대상의 가상 행 — 사전이 쓰는데(C1 기본 켜짐 · C7 대상) build_indicators 가 만들지 않는다.
EXTRA_ROWS = {
    "jp30y": {"id": "jp30y", "label": "일본 국채 30Y", "short": "일본 국채 30Y", "unit": "%", "decimals": 3,
              "dataPath": "yieldCurve.jp:30Y"},
}
FRESH_STATES = ("live", "prev", "stale", "kept", "missing")    # 번들 신선도 5종(meta.json states)
KR_CODE = re.compile(r"[0-9][0-9A-Z]{5}")         # 국내 종목 코드(check_alerts.KR_CODE 와 같은 꼴 — 신규 ETF 0018Z0)
US_TICKER = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")  # 미국 티커. 사전 · 레지스트리 id 는 소문자라 겹치지 않는다(2026-10-09 127행 실측)


def is_stock(target) -> bool:
    t = str(target or "")
    return bool(KR_CODE.fullmatch(t) or US_TICKER.fullmatch(t))


def _tenor_row(node, tenor: str):
    """yieldCurve.<나라> 의 만기 행. `series` 가 [{tenor, data:[{date, value}]}] 이고 `current` 는 값만 든 목록이다."""
    if not isinstance(node, dict):
        return None
    for key in ("series", "current"):
        rows = node.get(key)
        if isinstance(rows, list):
            hit = next((r for r in rows if isinstance(r, dict) and r.get("tenor") == tenor), None)
            if hit is not None:
                return hit
    return None


def _get(obj, path: str):
    """점 경로 + `a.b:10Y`(만기) 지원. 없으면 None."""
    cur = obj
    for part in path.split("."):
        tenor = None
        if ":" in part:
            part, tenor = part.split(":", 1)
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            return None
        if tenor is not None:
            cur = _tenor_row(cur, tenor)
        if cur is None:
            return None
    return cur


def _check_alerts():
    """옛 종목 알림 모듈 — 종목을 물을 때만 읽는다(판정 · 재생 · 테스트는 네트워크를 안 쓴다)."""
    scripts = os.path.join(ROOT, "scripts")
    if scripts not in sys.path:
        sys.path.append(scripts)
    import check_alerts
    return check_alerts


def _last_point(rows: list):
    """일봉 목록의 끝 값(close 또는 value). 없으면 None."""
    for r in reversed(rows):
        if isinstance(r, dict):
            v = r.get("close", r.get("value"))
            if v is not None:
                return v
    return None


@dataclass
class Context:
    now: dt.datetime
    data: dict
    bundles: dict
    registry: dict               # id → 행
    mer: dict
    root: str = ROOT
    _strip: dict = field(default_factory=dict)
    _stocks: dict = field(default_factory=dict)      # 종목 → 값 칸(None = 장 밖 · 휴장 · 조회 실패), 한 런 캐시
    _snaps: dict = field(default_factory=dict)       # 종목 → check_alerts 스냅샷(None = 실패), 한 런 캐시
    _stock_rows: dict | None = None                  # 묶음의 종목 행(값은 오늘 live 칸만) — 처음 물을 때 만든다

    @classmethod
    def load(cls, now: dt.datetime | None = None, root: str = ROOT) -> "Context":
        now = now or dt.datetime.now(KST)
        with open(os.path.join(root, "data.json"), encoding="utf-8") as f:
            data = json.load(f)
        bundles = {}
        for name in BUNDLE_FILES:
            p = os.path.join(root, "bundles", f"{name}.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    bundles[name] = json.load(f)
        reg_rows = bundles.get("registry") or []
        if not reg_rows:
            p = os.path.join(root, "bundles", "registry.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    reg_rows = json.load(f)
        if isinstance(reg_rows, dict):
            reg_rows = reg_rows.get("items") or reg_rows.get("rows") or []
        registry = {r["id"]: r for r in reg_rows if isinstance(r, dict) and "id" in r}
        mer = {}
        p = os.path.join(root, "mer_signals.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                mer = json.load(f)
        ctx = cls(now=now, data=data, bundles=bundles, registry=registry, mer=mer, root=root)
        ctx._index_strips()
        return ctx

    # ---- 번들 띠 색인(화면과 같은 값) ----
    def _index_strips(self) -> None:
        """띠(strip)를 먼저, 그다음 보기(views) 안의 같은 모양 행을 색인한다.

        VIX · MOVE · 공포탐욕 · 미 30년 · 장단기 금리차는 띠에 없고 보기 칸에만 있다(2026-10-05 실측 137개 id,
        같은 id 가 두 곳에서 다른 값인 경우 0). 렌즈 묶음의 트리거 행은 state 가 crossed/below 라 걸러진다."""
        for b in self.bundles.values():
            if isinstance(b, dict):
                for s in (b.get("strip") or []):
                    if isinstance(s, dict) and s.get("id"):
                        self._strip.setdefault(s["id"], s)

        def walk(o):
            if isinstance(o, dict):
                if (o.get("id") and "value" in o
                        and (o.get("fresh") or o.get("state")) in FRESH_STATES):
                    self._strip.setdefault(o["id"], o)
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        for name, b in self.bundles.items():
            if isinstance(b, dict) and name != "meta":
                walk(b.get("views"))

    def rid(self, target: str) -> str:
        return ALIASES.get(target, target)

    def row(self, target: str) -> dict | None:
        """레지스트리 행(없으면 가상 행 EXTRA_ROWS)."""
        r = self.rid(target)
        return self.registry.get(r) or EXTRA_ROWS.get(r)

    def strip(self, target: str) -> dict | None:
        return self._strip.get(self.rid(target))

    def value(self, target: str):
        """현재값(화면 값과 같은 원천). 번들 띠 → 레지스트리 dataPath 순."""
        s = self.strip(target)
        if s and s.get("value") is not None:
            return s["value"]
        row = self.row(target)
        if row and row.get("dataPath"):
            v = _get(self.data, row["dataPath"])
            if isinstance(v, dict):
                if isinstance(v.get("data"), list):            # 만기 행(yieldCurve) — 끝 점
                    return _last_point(v["data"])
                return v.get("value", v.get("price", v.get("rate")))
            if isinstance(v, list):                            # 일봉 목록(가상자산) — 끝 종가
                return _last_point(v)
            return v
        q = self.stock(target)
        return q["value"] if q else None

    def scale(self, target: str):
        """화면 축척 — 화면 값 = 원본 ÷ scale(app lib/format.ts scaled, 예: 엔/원 0.01 → 100엔당 원). 번들 띠 → 레지스트리, 없으면 None."""
        return (self.strip(target) or {}).get("scale") or (self.row(target) or {}).get("scale")

    def change_pct(self, target: str):
        s = self.strip(target)
        if s and s.get("changePct") is not None:
            return s["changePct"]
        q = self.stock(target)
        return q["changePct"] if q else None

    def fresh(self, target: str) -> str:
        """번들 신선도 5종. 번들 칸은 `state` 로 싣는다. 번들에 없고 data.json 에만 값이 있으면 prev(직전 값)."""
        s = self.strip(target)
        if s:
            return s.get("fresh") or s.get("state") or "missing"
        q = self.stock(target)
        if q:
            return q["fresh"]
        return "prev" if self.value(target) is not None else "missing"

    def as_of(self, target: str) -> str:
        """기준 시각. 번들 칸 asOf → data.json 잎의 as_of/period → 일봉 끝 날짜 → 오늘."""
        s = self.strip(target)
        if s and s.get("asOf"):
            return s["asOf"]
        row = self.row(target)
        if row and row.get("dataPath"):
            v = _get(self.data, row["dataPath"])
            if isinstance(v, dict):
                a = v.get("as_of") or v.get("asOf") or v.get("period")
                if a:
                    return str(a)
        q = self.stock(target)
        if q:
            return q["asOf"]
        ser = self.series(target, 1)
        if ser and ser[-1].get("date"):
            return str(ser[-1]["date"])
        return self.now.date().isoformat()

    def series(self, target: str, n: int = 400) -> list[dict]:
        row = self.row(target) or {}
        path = row.get("seriesPath") or row.get("dataPath")
        if not path:
            if not self.stock(target):                     # 장 밖 · 휴장 · 사전 밖 대상이면 비교하지 않는다
                return []
            sn = self._snap(str(target)) or {}
            cl = sn.get("closes") or []
            hi, lo = sn.get("highs") or [], sn.get("lows") or []
            ok = len(hi) == len(lo) == len(cl)             # 장중 고가 · 저가(52주 판정) — 칸이 어긋나면(야후 빈 봉) 종가만
            return [{"date": d, "close": c, "high": hi[i] if ok else None, "low": lo[i] if ok else None}
                    for i, (d, c) in enumerate(zip(sn.get("dates") or [], cl))][-n:]
        v = _get(self.data, path)
        if isinstance(v, dict) and "data" in v:
            v = v["data"]
        if isinstance(v, dict) and "history" in v:          # economicIndicators 잎: {날짜: 값}
            h = v["history"]
            v = [{"date": k, "close": h[k]} for k in sorted(h)]
        if not isinstance(v, list):
            return []
        out = [{"date": r.get("date"), "close": r.get("close", r.get("value"))} for r in v if isinstance(r, dict)]
        return out[-n:]

    # ---- 종목(국내 6자리 · 미국 티커) — 사전 · 레지스트리 밖 대상. 사용자 조건(U1 · U2 · B1)만 묻는다 ----
    def stock(self, target) -> dict | None:
        """종목의 지금 값 {value, changePct, asOf, fresh, name} 또는 None — 한 런에 종목당 한 번.

        옛 종목 알림(check_alerts._PrefsCtx.quote · 현행 루프)과 같은 규칙: 장 밖(is_market_open)이면 보지 않는다(멈춘 시세),
        휴장(마지막 일봉이 오늘 아님) · 오염(가격 0 이하 · 하루 등락 상한 초과) · 조회 실패면 None.
        값은 직접 조회(지금 값)가 먼저, 그게 없을 때만 묶음의 그 종목 행(오늘 live 칸 — 최대 ~25분 늦다)."""
        t = str(target or "")
        if t in self._stocks:
            return self._stocks[t]
        q = None
        if is_stock(t) and self.strip(t) is None and self.row(t) is None:
            ca = _check_alerts()
            kr = bool(KR_CODE.fullmatch(t))
            if ca.is_market_open("KR" if kr else "US", self.now.astimezone(KST)):
                b = self._bundle_stock(t) if kr else None
                sn = self._snap(t)
                if sn:
                    q = {"value": sn["price"], "changePct": sn.get("pct"), "fresh": "live",
                         "asOf": (sn.get("dates") or [self.now.astimezone(KST).date().isoformat()])[-1]}
                elif b and b["_live"]:
                    q = {"value": b["price"], "changePct": b.get("chgPct"), "asOf": b["_asOf"], "fresh": "live"}
                if q:
                    flows = ((self.data.get("stockFlows") or {}).get("items") or {}).get(t) or {}
                    q["name"] = (b or {}).get("short") or (b or {}).get("name") or flows.get("name") or t
        self._stocks[t] = q
        return q

    def _snap(self, t: str):
        """옛 종목 알림의 시세 길 그대로(check_alerts.get_snapshot: 국내 네이버 → 야후 .KS/.KQ, 미국 야후) — 실패도 기억."""
        if t not in self._snaps:
            ca = _check_alerts()
            kr = bool(KR_CODE.fullmatch(t))
            why = ""
            try:
                sn = ca.get_snapshot("KR" if kr else "US", t, None)
            except Exception as e:                         # noqa: BLE001 — 한 종목의 실패가 다른 판정을 막지 않는다
                sn, why = None, type(e).__name__
            sane = ca.SANE_MOVE_PCT_KR if kr else ca.SANE_MOVE_PCT_US
            if sn and sn.get("fresh") is False:
                sn, why = None, "휴장 · 묵은 시세"
            elif sn and (sn["price"] <= 0 or abs(sn.get("pct") or 0) > sane):
                sn, why = None, f"오염 의심 {sn['price']} {sn.get('pct')}%"
            if sn is None:
                print(f"[v2] 종목 시세 없음 {t}({why or '조회 실패'}) — 이 종목만 건너뜀")
            self._snaps[t] = sn
        return self._snaps[t]

    def _bundle_stock(self, code: str) -> dict | None:
        """묶음(순위 · 시가총액 · 52주 …)의 그 종목 행. 값은 `_live`(칸 state 가 live 이고 asOf 가 오늘 KST)일 때만 쓰고,
        아니면 이름만 쓴다. live 행이 있으면 그것이 이긴다."""
        if self._stock_rows is None:
            self._stock_rows = {}
            today = self.now.astimezone(KST).date().isoformat()

            def walk(o, st, asof):
                if isinstance(o, dict):
                    st, asof = o.get("state", st), o.get("asOf", asof)
                    c = str(o.get("code") or "")
                    if KR_CODE.fullmatch(c) and o.get("price") is not None:
                        live = st == "live" and str(asof or "")[:10] == today
                        if c not in self._stock_rows or (live and not self._stock_rows[c]["_live"]):
                            self._stock_rows[c] = dict(o, _asOf=today, _live=live)
                    for v in o.values():
                        walk(v, st, asof)
                elif isinstance(o, list):
                    for v in o:
                        walk(v, st, asof)
            walk(self.bundles, None, None)
        return self._stock_rows.get(code)

    @property
    def calendar(self) -> list[dict]:
        return ((self.data.get("economicCalendar") or {}).get("events") or [])

    @property
    def kr_open_today(self) -> bool | None:
        cal = self.data.get("marketCalendarKr") or {}
        today = cal.get("today") or {}
        return today.get("open") if today.get("date") == self.now.date().isoformat() else None
