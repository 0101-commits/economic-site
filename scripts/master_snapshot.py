#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""마스터 매일 스냅샷 — 마스터 보유 암호 덩어리를 풀어 종가로 평가액을 계산해 서버 스냅샷에 합쳐 올린다.

흐름  GET /hold/owner (X-Push-Read-Key) → 풀기 → 빠진 평일마다 Yahoo 일봉 종가로 평가 →
      GET /snaps/owner (X-Push-Read-Key) → 풀기 → 합치기 → 새 salt · iv 로 잠가 PUT /snaps/owner (X-Push-Write-Key).
환경  MASTER_HOLD_KEY(보유 열쇠 hex — 앱 holdKeyOf 결과) · PUSH_READ_KEY · PUSH_WRITE_KEY · PUSH_WORKER_URL(선택).
종료  비밀값이 빠졌거나 마스터 보유가 비었거나 시세를 못 받으면 한 줄 이유와 함께 0(워크플로를 시끄럽게 하지 않는다).
      덩어리가 안 풀리면(열쇠 틀림 · 깨진 덩어리) 1 — 눈에 띄어야 한다. 서버 호출 실패도 1.
로그  개수 · 날짜 · 성공 여부만. 금액 · 종목 · 수량 · 이름은 절대 찍지 않는다(예외 문구에도 주소가 실리므로 원인 종류만 적는다).

== 암호 덩어리 형식 (app/src/lib/personal/e2e.ts 와 같다) ==
  { alg:'AES-256-GCM', kdf:'PBKDF2-SHA256', iter:600000, salt:b64(16B), iv:b64(12B), ciphertext:b64 }
  열쇠 = PBKDF2-HMAC-SHA256(「암호」 utf-8, salt, 600000회) → 32바이트. 「암호」 = 보유 열쇠 hex 문자열(MASTER_HOLD_KEY).
  풀 때는 덩어리의 iter 가 아니라 고정 600000 을 쓴다(e2e.ts 와 같다). 올릴 때마다 salt · iv 를 새로 뽑는다.

== 스냅샷 평문 (Part B 앱이 같은 모양으로 읽고 쓴다) ==
  JSON  { "v": 1, "at": "<ISO 시각 — 그 판을 만든 때>",
          "snaps": [ { "d": "YYYY-MM-DD"(한국 날짜), "ev": 정수 원(평가액 = calc.ts totals.basisValue),
                       "ct": 정수 원(원금 = totals.cost), "src": "close" | "app" (선택) } ] }
  날짜 오름차순 · 같은 날짜 하나 · 끝에서 730건만. 같은 날짜가 둘이면 src:"close"(이 작업이 만든 종가 값)가 이긴다.
  「한국 날짜」 d 의 미국 종목 값 = 그 날짜(미국 달력)의 미국 종가.

== 보유 평문 (e2e.ts parsePlain) ==
  JSON 배열 [{ s, m:'KR'|'US', a:평단가, q:수량, fx:매입 환율, n?:이름 }, ..., { t:바뀐 때 }]. 평단가나 수량이 있는 칸만 쓴다.

== 평가식 (calc.ts evaluate 와 같다 — 줄 번호는 app/src/lib/personal/calc.ts) ==
  usd = (m == 'US')                                   (46행 isUsd — Entry 에는 ccy 가 없으니 시장으로)
  qty = q > 0 ? q : 없음 · avg = a > 0 ? a : 없음        (63~64행)
  fxNow = usd ? 그날 달러원 : 1                          (65행) — 없으면 그 종목은 뺀다
  costMul = usd ? (fx 가 참이면 fx, 아니면 fxNow) : 1     (66행 `h.fxBuy || fxNow`)
  cost = avg·qty·costMul (둘 다 있을 때만)               (67행)
  value = 종가·qty·fxNow                                (72행) — 종가나 qty 가 없으면 뺀다(68~71행)
  ev = Σ value  (cost 가 있는 종목만, 78행 basisValue) · ct = Σ cost (같은 종목들, 78행 cost)
  앱이 저장하는 값 = round(ev), round(ct) (store.ts saveTodaySnap) · 둘 다 > 0 일 때만 저장(My.tsx 86행).
  Math.round 는 .5 를 위로 올린다 → floor(x + 0.5).
"""
import base64
import datetime
import json
import math
import os
import re
import sys

try:                                    # Windows cp949 콘솔에서도 한글 로그가 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

WORKER = "https://ecom-dashboard-proxy.e-hcg.workers.dev"
ITER = 600_000                          # e2e.ts ITER
MAX_SNAPS = 730                         # calc.ts upsertSnap
BACKFILL_WEEKDAYS = 10
KST = datetime.timezone(datetime.timedelta(hours=9))
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UA = "Mozilla/5.0 (compatible; ecom-master-snapshot)"


class DecryptError(Exception):
    pass


# ── 암호 ──────────────────────────────────────────────────────────
def _key(password, salt):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(password.encode("utf-8"))


def decrypt_blob(blob, password):
    """덩어리 → 평문 JSON 값. 열쇠가 틀리거나 덩어리가 깨졌으면 DecryptError."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        if blob.get("alg") != "AES-256-GCM" or blob.get("kdf") != "PBKDF2-SHA256":
            raise ValueError("format")
        salt, iv, ct = (base64.b64decode(blob[k], validate=True) for k in ("salt", "iv", "ciphertext"))
        pt = AESGCM(_key(password, salt)).decrypt(iv, ct, None)
        return json.loads(pt.decode("utf-8"))
    except Exception as e:              # 원인 문구에 값이 섞일 수 있어 종류만 남긴다
        raise DecryptError(type(e).__name__) from None


def encrypt_blob(plain, password, salt=None, iv=None):
    """평문 JSON 값 → 덩어리(새 salt · iv). salt · iv 인자는 시험용."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = salt or os.urandom(16)
    iv = iv or os.urandom(12)
    ct = AESGCM(_key(password, salt)).encrypt(iv, json.dumps(plain, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return {"alg": "AES-256-GCM", "kdf": "PBKDF2-SHA256", "iter": ITER, "salt": b64(salt), "iv": b64(iv), "ciphertext": b64(ct)}


def open_with_fallback(blob, password):
    """원문 암호로 풀고, 안 되면 앞뒤 공백을 뺀 값으로 한 번 더(e2e.ts decryptAs)."""
    try:
        return decrypt_blob(blob, password)
    except DecryptError:
        if password.strip() == password:
            raise
        return decrypt_blob(blob, password.strip())


# ── 보유 · 평가 ───────────────────────────────────────────────────
def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def parse_holdings(plain):
    """e2e.ts parsePlain 과 같다 — 칸 목록만(바뀐 때 {t} 줄은 버린다). 모양이 틀리면 DecryptError."""
    if not isinstance(plain, list):
        raise DecryptError("shape")
    out = []
    for h in plain:
        if not isinstance(h, dict) or not isinstance(h.get("s"), str) or not h["s"]:
            continue
        e = {"s": h["s"][:40], "m": "US" if h.get("m") == "US" else "KR", "a": _num(h.get("a")), "q": _num(h.get("q")), "fx": _num(h.get("fx"))}
        if e["a"] is not None or e["q"] is not None:
            out.append(e)
    return out


def js_round(x):
    """JavaScript Math.round — .5 는 위로."""
    return int(math.floor(x + 0.5))


def evaluate(entries, price_of, fx_now):
    """한 날짜의 (ev, ct) — calc.ts evaluate 의 basisValue · cost 와 같다.
    price_of(entry) = 그날 종가 또는 None, fx_now = 그날 달러원 또는 None.
    반환 (ev, ct, missing). 앱이 저장하는 정수 반올림은 호출하는 쪽(snap_of)이 한다."""
    ev = ct = 0.0
    missing = 0
    for e in entries:
        usd = e["m"] == "US"
        qty = e["q"] if e["q"] is not None and e["q"] > 0 else None
        avg = e["a"] if e["a"] is not None and e["a"] > 0 else None
        fxn = fx_now if usd else 1
        cost_mul = (e["fx"] or fxn) if usd else 1
        cost = avg * qty * cost_mul if (avg is not None and qty is not None and cost_mul is not None) else None
        px = price_of(e)
        if px is None or qty is None or fxn is None:
            if qty is not None:
                missing += 1
            continue
        value = px * qty * fxn
        if cost is not None:
            ct += cost
            ev += value
    return ev, ct, missing


def snap_of(day, entries, price_of, fx_now):
    """{d, ev, ct, src:'close'} 또는 None(앱처럼 평가액 · 원금이 둘 다 양수일 때만)."""
    ev, ct, _ = evaluate(entries, price_of, fx_now)
    if not (ev > 0 and ct > 0):
        return None
    return {"d": day, "ev": js_round(ev), "ct": js_round(ct), "src": "close"}


# ── 합치기 ────────────────────────────────────────────────────────
def clean_snaps(snaps):
    out = []
    for s in snaps if isinstance(snaps, list) else []:
        if isinstance(s, dict) and isinstance(s.get("d"), str) and _DAY.match(s["d"]) and _num(s.get("ev")) is not None and _num(s.get("ct")) is not None:
            r = {"d": s["d"], "ev": js_round(s["ev"]), "ct": js_round(s["ct"])}
            if s.get("src") in ("close", "app"):
                r["src"] = s["src"]
            out.append(r)
    return out


def merge_snaps(existing, new):
    """날짜별 하나. 이 작업이 만든 값(new, src:'close')이 같은 날짜의 기존 값(app 이든 옛 close 든)을 이긴다.
    기존끼리 겹치면 close 가 이긴다. 날짜 오름차순, 끝에서 730건."""
    by = {}
    for s in clean_snaps(existing):
        cur = by.get(s["d"])
        if cur is None or (s.get("src") == "close" and cur.get("src") != "close"):
            by[s["d"]] = s
    for s in clean_snaps(new):
        by[s["d"]] = {**s, "src": "close"}
    return [by[d] for d in sorted(by)][-MAX_SNAPS:]


# ── 날짜 ──────────────────────────────────────────────────────────
def kst_today(now=None):
    return (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(KST).date()


def last_weekdays(end, n=BACKFILL_WEEKDAYS):
    """end(포함) 이하의 평일 n개, 오름차순."""
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= datetime.timedelta(days=1)
    return out[::-1]


def target_days(existing, today):
    """어제까지 최근 평일 10일 중 종가 값이 아직 없는 날 + 어제(평일이면 늘 다시 계산)."""
    cands = last_weekdays(today - datetime.timedelta(days=1))
    have = {s["d"] for s in clean_snaps(existing) if s.get("src") == "close"}
    return [d for d in cands if d not in have or d == cands[-1]]


# ── 시세(Yahoo 일봉) ──────────────────────────────────────────────
def http_get_json(url, headers=None, timeout=20):
    import requests
    r = requests.get(url, headers={"User-Agent": UA, **(headers or {})}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def http_put_json(url, headers, body, timeout=30):
    import requests
    r = requests.put(url, headers={"User-Agent": UA, "Content-Type": "application/json", **headers}, data=json.dumps(body), timeout=timeout)
    r.raise_for_status()
    return r.status_code


def parse_chart(j):
    """Yahoo chart 답 → {'YYYY-MM-DD'(거래소 현지 날짜): 종가}. 모양이 다르면 {}."""
    try:
        res = j["chart"]["result"][0]
        off = int(res.get("meta", {}).get("gmtoffset") or 0)
        closes = res["indicators"]["quote"][0]["close"]
        out = {}
        for ts, c in zip(res["timestamp"], closes):
            if c is None or not math.isfinite(c):
                continue
            d = (datetime.datetime.fromtimestamp(ts, datetime.timezone.utc) + datetime.timedelta(seconds=off)).date().isoformat()
            out[d] = float(c)
        return out
    except (KeyError, IndexError, TypeError, ValueError):
        return {}


def _yahoo(sym):
    from urllib.parse import quote
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(sym)}?range=2mo&interval=1d"
    return parse_chart(http_get_json(url))


def yahoo_candidates(e):
    s = e["s"].strip().upper()
    if e["m"] == "US":
        return [s.replace(".", "-")]
    s = re.sub(r"^A(?=\d{6}$)", "", s)
    return [s + ".KS", s + ".KQ"]


def fetch_series(entries, fetch=_yahoo):
    """entries 의 종목마다 일봉 종가 + 달러원. 반환 ({(m,s): {날짜: 종가}}, {날짜: 달러원}, 못 받은 종목 수).
    못 받은 종목은 키가 없다(숫자만 세고 이름은 남기지 않는다)."""
    series, failed = {}, 0
    for e in entries:
        key = (e["m"], e["s"])
        if key in series or e["q"] is None or e["q"] <= 0:
            continue
        got = {}
        for sym in yahoo_candidates(e):
            try:
                got = fetch(sym)
            except Exception:
                got = {}
            if got:
                break
        if got:
            series[key] = got
        else:
            failed += 1
    fx = {}
    if any(e["m"] == "US" for e in entries):
        try:
            fx = fetch("KRW=X")
        except Exception:
            fx = {}
    return series, fx, failed


def carry(series, day):
    """day 이하에서 가장 가까운 값(휴장일은 직전 종가). 없으면 None."""
    best = None
    for d in series:
        if d <= day and (best is None or d > best):
            best = d
    return series[best] if best else None


def compute_days(entries, days, series, fx):
    """days 마다 {d, ev, ct, src:'close'}. 어떤 종목도 그날 봉이 없으면(전 시장 휴장) 건너뛴다."""
    out = []
    for day in days:
        if not any(day in s for s in series.values()):
            continue
        price = lambda e, _d=day: carry(series[(e["m"], e["s"])], _d) if (e["m"], e["s"]) in series else None
        fxn = carry(fx, day) if fx else None
        # 그날 시세(또는 달러원)가 없는 보유가 하나라도 있으면 그날은 건너뛴다 — 일부만 더하면 ev 가 틀어진다.
        if any(e["q"] and e["q"] > 0 and (price(e) is None or (e["m"] == "US" and fxn is None)) for e in entries):
            continue
        s = snap_of(day, entries, price, fxn)
        if s:
            out.append(s)
    return out


# ── 실행 ──────────────────────────────────────────────────────────
def log(msg):
    print(f"[master_snapshot] {msg}", flush=True)


def run(env=None, now=None, fetch=_yahoo):
    env = os.environ if env is None else env
    hold_key = (env.get("MASTER_HOLD_KEY") or "").strip()
    rk = (env.get("PUSH_READ_KEY") or "").strip()
    wk = (env.get("PUSH_WRITE_KEY") or "").strip()
    if not (hold_key and rk and wk):
        log("건너뜀: 비밀값(MASTER_HOLD_KEY · PUSH_READ_KEY · PUSH_WRITE_KEY)이 빠졌다")
        return 0
    base = (env.get("PUSH_WORKER_URL") or WORKER).rstrip("/")
    rh, wh = {"X-Push-Read-Key": rk}, {"X-Push-Write-Key": wk}
    try:
        hb = http_get_json(base + "/hold/owner", rh).get("encHoldings")
    except Exception as e:
        log(f"실패: 보유 덩어리를 못 받았다({type(e).__name__})")
        return 1
    if not hb:
        log("건너뜀: 마스터 보유 덩어리가 없다")
        return 0
    try:
        entries = parse_holdings(open_with_fallback(hb, hold_key))
    except DecryptError as e:
        log(f"실패: 보유 덩어리를 풀지 못했다({e})")
        return 1
    if not entries:
        log("건너뜀: 마스터 보유 종목이 없다")
        return 0
    try:
        sb = http_get_json(base + "/snaps/owner", rh).get("encSnaps")
    except Exception as e:
        log(f"실패: 서버 스냅샷을 못 받았다({type(e).__name__})")
        return 1
    existing = []
    if sb:
        try:
            plain = open_with_fallback(sb, hold_key)
            existing = plain.get("snaps") if isinstance(plain, dict) else None
            if not isinstance(existing, list):
                raise DecryptError("shape")
        except DecryptError as e:
            log(f"실패: 서버 스냅샷을 풀지 못했다({e})")
            return 1
    days = target_days(existing, kst_today(now))
    series, fx, failed = fetch_series(entries, fetch)
    log(f"계산할 날 {len(days)}일 · 시세 받은 종목 {len(series)}개 · 못 받은 종목 {failed}개")
    if failed:
        log(f"건너뜀: 시세를 못 받은 종목 {failed}개 — 일부만 더하면 값이 틀어진다(계속되면 Yahoo 심볼 확인)")
        return 0
    if any(e["m"] == "US" and e["q"] and e["q"] > 0 for e in entries) and not fx:
        log("건너뜀: 달러원 종가를 못 받았다")
        return 0
    new = compute_days(entries, days, series, fx)
    if not new:
        log("건너뜀: 계산된 날이 없다(휴장 등)")
        return 0
    merged = merge_snaps(existing, new)
    if merged == merge_snaps(existing, []):
        log(f"변경 없음: 새로 계산한 {len(new)}일이 서버 값과 같다")
        return 0
    at = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    blob = encrypt_blob({"v": 1, "at": at, "snaps": merged}, hold_key)
    try:
        http_put_json(base + "/snaps/owner", wh, {"encSnaps": blob})
    except Exception as e:
        log(f"실패: 서버에 올리지 못했다({type(e).__name__})")
        return 1
    log(f"완료: {len(new)}일 계산({new[0]['d']}~{new[-1]['d']}) · 서버 스냅샷 {len(merged)}건으로 올렸다")
    return 0


if __name__ == "__main__":
    sys.exit(run())
