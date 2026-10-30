"""경제 일정 컨센서스 — 나스닥 경제 일정에서 발표값 · 컨센서스 · 직전 값을 받아 일정 행에 붙인다.

왜 나스닥인가(2026-10-30 실측, 기획서 EiKJcHkR 2-2): 한국(CPI · 기준금리 · GDP · 수출)과 미국 주요 지표의
컨센서스를 날짜별로 주고, 2024년까지 지난 회차도 조회된다. GitHub 서버에서도 받아졌다(임시 가지 시험).
ForexFactory 주간 묶음은 이번 주만 있고 한국이 없다. Investing.com 은 403, Trading Economics 는 유료.

발표값도 여기서 받는다 — 컨센서스와 견줄 값은 같은 자료원이어야 한다. FRED 물가지수로 직접 계산한 미국 CPI
전월비는 2026-10 회차를 +0.7% 로 냈지만 공식 발표와 컨센서스는 0.6% 였다(반올림 차이로 「높음」 오판).
긴 추이 그래프는 지금처럼 FRED 를 쓴다.

나스닥 자료의 함정:
  · 조회일(date=) = 미국 동부 발표일 + 1일. 시각 칸(`gmt`)도 실제로는 미국 동부 시각이다
    (한국 CPI 08:00 KST 가 전날 「19:00」 으로 온다).
  · 같은 이름이 두 줄이다 — 「CPI」 아래 전월 대비와 전년 대비. 직전 값이 작은 쪽이 전월(전기) 대비다.
  · 앞으로의 컨센서스는 발표 며칠 전에야 채워진다 — 일일 런마다 다시 받는다.
  · 빈 칸은 "" · " " · "&nbsp;" 로 온다.
"""
import json
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
NASDAQ_URL = "https://api.nasdaq.com/api/calendar/economicevents?date={}"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
       "Accept": "application/json"}
SOURCE = "나스닥 경제 일정"

# 일정 이름 → (나스닥 나라, 나스닥 지표 이름(소문자), 고르기, 표기)
#   고르기: "short" = 같은 이름 두 줄 중 직전 값이 작은 쪽(전월 · 전기 대비) · "long" = 큰 쪽(전년 대비)
#           "level" = % 가 아닌 줄(주택착공 1.221M) · None = 한 줄뿐
#   표기는 fetch_data._fmt_indicator 와 같은 꼴 — 캘린더의 기존 값과 나란히 놓인다.
CONSENSUS_MAP = {
    "미국 CPI (전월비)":                ("United States", "cpi", "short", "pct1"),
    "미국 CPI (전년비)":                ("United States", "cpi", "long", "pct1"),
    "미국 PPI":                        ("United States", "ppi", "short", "pct1"),
    "미국 소매판매":                    ("United States", "retail sales", "short", "pct1"),
    "미국 GDP":                        ("United States", "gdp", None, "pct1"),
    "미국 PCE 물가지수":                ("United States", "pce price index", "short", "pct1"),
    "미국 비농업고용(NFP)":             ("United States", "nonfarm payrolls", None, "kd"),
    "미국 FOMC 회의":                  ("United States", "fed interest rate decision", None, "pct2"),
    "미국 산업생산":                    ("United States", "industrial production", "short", "pct1"),
    "미국 주택착공 (Housing Starts)":    ("United States", "housing starts", "level", "raw1k"),
    "한국 소비자물가동향":              ("South Korea", "cpi", "long", "pct1"),
    "한국은행 금통위 (통화정책방향)":     ("South Korea", "interest rate decision", None, "pct2"),
    "ECB 통화정책 결정":                ("Euro Zone", "deposit facility rate", None, "pct2"),
    "일본은행(BOJ) 금융정책결정회합":     ("Japan", "boj interest rate decision", None, "pct2"),
}

_FULL_BACK = 62      # 일일 런: 이만큼 지난 회차까지 다시 받는다(캘린더 뒤 창과 같은 폭)
_FULL_AHEAD = 10     # 일일 런: 앞으로 이만큼(컨센서스가 들어오는 구간)
_RECENT_H = 6        # 일반 런: 발표 시각이 최근 이 안에 지난 회차만 받는다(10분 주기 런의 요청 수를 줄인다)


def _us_dst(d):
    """미국 서머타임 — 3월 둘째 일요일 ~ 11월 첫 일요일 전날 (fetch_data._us_dst 와 같은 규칙)."""
    mar, nov = d.replace(month=3, day=1), d.replace(month=11, day=1)
    return (mar + timedelta(days=(6 - mar.weekday()) % 7 + 7)) <= d < (nov + timedelta(days=(6 - nov.weekday()) % 7))


def _release_kst(ev):
    """일정 행의 발표 시각(KST). dt = 'MM.DD HH:MM'(앞에 ~ 가 붙기도 함), iso = KST 날짜."""
    iso = ev.get("iso") or ""
    hm = str(ev.get("dt") or "").replace("~", "").split()[-1:] or ["00:00"]
    try:
        h, m = (int(x) for x in hm[0].split(":"))
    except ValueError:
        h, m = 0, 0
    try:
        y, mo, d = (int(x) for x in iso.split("-"))
        return datetime(y, mo, d, h, m, tzinfo=KST)
    except ValueError:
        return None


def query_date(ev):
    """일정 행 → 나스닥 조회일. 발표 시각을 미국 동부로 바꾼 날짜 + 1일."""
    k = _release_kst(ev)
    if k is None:
        return None
    naive = k.replace(tzinfo=None)
    et = naive - timedelta(hours=13)
    if not _us_dst(et.date()):
        et = naive - timedelta(hours=14)
    return (et.date() + timedelta(days=1)).isoformat()


def _num(s):
    """'0.6%' · '-5.2%' · '29K' · '1.221M' · '6,368.6B' → (값, 단위). 빈 칸이면 (None, '')."""
    t = str(s or "").replace("&nbsp;", "").replace(",", "").strip()
    if not t:
        return None, ""
    unit = t[-1] if t[-1] in "%KMB" else ""
    try:
        return float(t.rstrip("%KMB")), unit
    except ValueError:
        return None, ""


def _fmt(val, unit, how):
    if val is None:
        return ""
    if how == "pct1":
        return f"{'+' if val >= 0 else ''}{val:.1f}%"
    if how == "pct2":
        return f"{val:.2f}%"
    if how == "kd":       # 천 명 증감 — 나스닥은 'K' 단위로 준다
        v = val * 1000 if unit == "M" else val
        return f"{'+' if v >= 0 else ''}{int(round(v))}K"
    if how == "raw1k":    # 천 호 — 나스닥은 '1.221M'
        return f"{val * 1000 if unit == 'M' else val:.1f}"
    return str(val)


def pick_row(rows, country, name, how):
    """하루 묶음에서 그 지표 줄을 고른다. 고를 수 없으면 None(지어내지 않는다)."""
    cand = [r for r in rows if r.get("country") == country and str(r.get("eventName", "")).strip().lower() == name]
    if how == "level":
        cand = [r for r in cand if _num(r.get("actual") or r.get("previous"))[1] != "%"]
        return cand[0] if len(cand) == 1 else None
    if how is None:
        return cand[0] if len(cand) == 1 else None
    if len(cand) != 2:     # 전월 · 전년 두 줄이 다 와야 가를 수 있다
        return None
    def size(r):
        v = _num(r.get("previous"))[0]
        if v is None:
            v = _num(r.get("actual"))[0]
        return abs(v) if v is not None else 0.0
    a, b = sorted(cand, key=size)
    if abs(size(a) - size(b)) < 0.05:   # 직전 값 크기가 비슷하면 어느 쪽이 전월인지 모른다 — 지어내지 않는다
        return None
    return a if how == "short" else b


def fetch_day(q, timeout=15):
    """나스닥 하루 묶음. 실패하면 예외(호출부가 세고 멈춘다)."""
    req = urllib.request.Request(NASDAQ_URL.format(q), headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.load(r)
    return ((body or {}).get("data") or {}).get("rows") or []


def _fetch_days(qs, fetch, pause, st, budget_s=None):
    """조회일 목록을 받는다. 새 날짜부터 · 막힘(403 · 429)이면 그 자리에서 멈추고 나머지 실패는 그 날짜만 건너뛴다.
    budget_s 가 있으면 그 초를 넘기는 순간 멈춘다(나스닥이 요청당 2~7초로 느려지는 때가 있다 — 2026-10-30 저녁 실측)."""
    days = {}
    t0 = time.monotonic()
    for q in sorted((d for d in qs if d), reverse=True):
        if budget_s is not None and time.monotonic() - t0 > budget_s:
            st["budgetHit"] = True
            break
        try:
            st["requests"] += 1
            days[q] = fetch(q)
        except Exception as e:
            st["failed"] += 1
            st["error"] = f"{q}: {str(e)[:120]}"
            if getattr(e, "code", None) in (403, 429) or re.search(r"\b(403|429)\b", str(e)):
                st["blocked"] = True
                break
            continue
        if pause:
            time.sleep(pause)
    return days


def apply_consensus(events, prev_events=None, full=False, now=None, fetch=fetch_day, pause=0.4, days_out=None):
    """일정 행에 fore(컨센서스) · act(발표값) · prev(직전)를 나스닥 값으로 채운다.

    full=True(일일 런)면 지난 62일 ~ 앞으로 10일을 다시 받고, 아니면 최근 6시간 안에 발표된 회차만 받는다.
    이번에 안 받은 회차는 직전 data.json 의 같은 (iso, 이름) 행에서 나스닥 값을 잇는다.
    반환: 진단 dict (요청 수 · 실패 · 채운 행 수).
    """
    now = now or datetime.now(KST)
    carry = {(e.get("iso"), e.get("name")): e for e in prev_events or [] if e.get("consSrc")}
    lo, hi = now - timedelta(days=_FULL_BACK), now + timedelta(days=_FULL_AHEAD)
    want = {}
    for ev in events:
        if ev.get("name") not in CONSENSUS_MAP:
            continue
        k = _release_kst(ev)
        if k is None:
            continue
        due = lo <= k <= hi if full else (now - timedelta(hours=_RECENT_H)) <= k <= now + timedelta(minutes=10)
        old = carry.get((ev.get("iso"), ev.get("name"))) or {}
        if due and not full and old.get("actSrc") and old.get("act"):
            due = False      # 공식 발표값까지 받은 회차 — 10분마다 다시 물을 까닭이 없다(이어받기로 채운다)
        if due:
            want.setdefault(query_date(ev), []).append(ev)
    st = {"requests": 0, "failed": 0, "filled": 0, "carried": 0, "full": bool(full)}
    # 새 날짜부터 받는다 — 앞으로의 컨센서스가 가장 쓸모 있다.
    days = _fetch_days(want, fetch, pause, st)
    if days_out is not None:
        days_out.update(days)
    stamp = now.isoformat(timespec="minutes")
    for ev in events:
        mp = CONSENSUS_MAP.get(ev.get("name"))
        if not mp:
            continue
        country, name, how, fmt = mp
        q = query_date(ev)
        row = pick_row(days[q], country, name, how) if q in days else None
        if row is None:
            old = carry.get((ev.get("iso"), ev.get("name")))
            if old:
                for f in ("fore", "act", "prev"):
                    if old.get(f) and (f == "fore" or old.get("actSrc")):
                        ev[f] = old[f]
                ev["consSrc"] = old.get("consSrc")
                if old.get("actSrc"):
                    ev["actSrc"] = old["actSrc"]
                ev["consAt"] = old.get("consAt")
                st["carried"] += 1
            continue
        a, cons, p = (_num(row.get(k)) for k in ("actual", "consensus", "previous"))
        if cons[0] is not None:
            ev["fore"] = _fmt(cons[0], cons[1], fmt)
        if a[0] is not None:
            ev["act"] = _fmt(a[0], a[1], fmt)
            ev["actSrc"] = SOURCE
            if p[0] is not None:
                ev["prev"] = _fmt(p[0], p[1], fmt)
        elif p[0] is not None and not ev.get("prev"):
            ev["prev"] = _fmt(p[0], p[1], fmt)
        old = carry.get((ev.get("iso"), ev.get("name"))) or {}
        if not ev.get("fore") and old.get("fore"):
            ev["fore"] = old["fore"]       # 나스닥이 이번엔 컨센서스 칸을 비워 보냈다 — 지난번 값을 잇는다
        ev["consSrc"] = SOURCE
        ev["consAt"] = stamp
        st["filled"] += 1
    return st


# ── 지난 회차 기록(P2) ─────────────────────────────────────────────────────────
# 지표마다 최근 1년 「발표값 · 컨센서스 · 직전」을 모아 「평소 어긋나는 폭」(컨센서스 대비 차이의 절댓값 평균)을 낸다.
# 같은 0.2%p 라도 미국 CPI(평소 0.07%p)에선 매우 큰 차이고 미국 GDP(평소 0.5%p)에선 보통이다(2026-10-30 실측).
# 기록은 data.json economicCalendar.consensusHistory 에 둔다. 처음엔 비어 있으므로 일일 런마다 하루 묶음을
# _BACKFILL_PER_RUN 개씩 거꾸로 훑어 1년을 채우고(scannedTo = 거기까지 훑은 가장 오랜 조회일), 그 뒤로는
# 일정 행을 채우며 받은 묶음에서 새 회차를 거둔다.
_HIST_DAYS = 400          # 이만큼 지난 회차까지 둔다(1년 + 여유)
_STATS_DAYS = 370         # 평소 폭은 최근 1년으로 잰다
_BACKFILL_PER_RUN = 120   # 일일 런 한 번에 거꾸로 훑는 날 수(3번이면 1년)
_BACKFILL_BUDGET_S = 300  # 거꾸로 훑기는 런마다 이 초 안에서만 — 느린 날 일일 런이 늘어지지 않게
_UNIT = {"pct1": "%", "pct2": "%", "kd": "K", "raw1k": ""}


def _val(n, how):
    """나스닥 (값, 단위) → 기록용 숫자. 표기 규칙(_fmt)과 같은 배율."""
    v, unit = n
    if v is None:
        return None
    if how in ("kd", "raw1k") and unit == "M":
        v *= 1000
    return round(v, 4)


def harvest(days, series):
    """하루 묶음들에서 짝 지표의 발표된 회차를 series[이름] 에 넣는다(조회일 q 가 같으면 새 값으로 바꾼다)."""
    added = 0
    for q, rows in days.items():
        for name, (country, nm, how, fmt) in CONSENSUS_MAP.items():
            r = pick_row(rows, country, nm, how)
            if r is None:
                continue
            a = _val(_num(r.get("actual")), fmt)
            if a is None:
                continue                      # 아직 발표 전
            item = {"q": q, "a": a, "c": _val(_num(r.get("consensus")), fmt), "p": _val(_num(r.get("previous")), fmt)}
            lst = series.setdefault(name, [])
            old = next((x for x in lst if x.get("q") == q), None)
            if old is None:
                lst.append(item)
                added += 1
            else:
                old.update(item)
    return added


def history_stats(series, today):
    """지표별 최근 1년 통계 — n(컨센서스 있는 회차) · meanAbs(평소 어긋나는 폭) · 높음/같음/낮음 횟수 · 단위."""
    lo = (today - timedelta(days=_STATS_DAYS)).isoformat()
    out = {}
    for name, lst in series.items():
        both = [x for x in lst if x.get("q", "") >= lo and x.get("a") is not None and x.get("c") is not None]
        if not both:
            continue
        d = [round(x["a"] - x["c"], 4) for x in both]
        out[name] = {"n": len(d), "meanAbs": round(sum(abs(v) for v in d) / len(d), 4),
                     "above": sum(1 for v in d if v > 1e-9), "same": sum(1 for v in d if abs(v) <= 1e-9),
                     "below": sum(1 for v in d if v < -1e-9), "unit": _UNIT.get(CONSENSUS_MAP[name][3], "")}
    return out


def update_history(prev_hist, days, full=False, now=None, fetch=fetch_day, pause=0.4):
    """직전 기록 + 이번 런이 받은 묶음 (+ 일일 런이면 거꾸로 훑기) → (새 기록, 진단)."""
    now = now or datetime.now(KST)
    today = now.date()
    prev_hist = prev_hist if isinstance(prev_hist, dict) else {}
    series = {k: [dict(x) for x in v] for k, v in (prev_hist.get("series") or {}).items()
              if k in CONSENSUS_MAP and isinstance(v, list)}
    st = {"requests": 0, "failed": 0, "added": 0}
    st["added"] += harvest(days, series)
    floor = (today - timedelta(days=_HIST_DAYS)).isoformat()
    scanned_to = prev_hist.get("scannedTo")
    if full and (not scanned_to or scanned_to > floor):
        start = date_from(scanned_to) - timedelta(days=1) if scanned_to else today
        qs = []
        d = start
        while len(qs) < _BACKFILL_PER_RUN and d.isoformat() >= floor:
            if d.isoformat() not in days:
                qs.append(d.isoformat())
            d -= timedelta(days=1)
        got = _fetch_days(qs, fetch, pause, st, budget_s=_BACKFILL_BUDGET_S)
        st["added"] += harvest(got, series)
        if got:
            # 막혀서 중간에 멈췄으면 실제로 받은 가장 오랜 날까지만 훑은 것으로 친다(빈 구멍이 남지 않게)
            scanned_to = min(got) if (st.get("blocked") or st.get("budgetHit")) else min(qs)
    for k in series:
        series[k] = sorted((x for x in series[k] if x.get("q", "") >= floor), key=lambda x: x["q"])
    hist = {"series": series, "stats": history_stats(series, today), "scannedTo": scanned_to,
            "source": SOURCE, "updatedAt": now.isoformat(timespec="minutes")}
    st["scannedTo"] = scanned_to
    st["series"] = sum(1 for v in series.values() if v)
    return hist, st


def date_from(iso):
    y, m, d = (int(x) for x in str(iso)[:10].split("-"))
    return datetime(y, m, d).date()
