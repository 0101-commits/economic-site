#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""주식/ETF 카카오톡 알림 — alerts_config.json 의 조건을 평가해 충족 시 카카오톡으로 발송한다.

흐름:
  '투자 현황' 페이지에서 설정한 알림 조건을 Cloudflare Worker(POST /portfolio)가
  저장소 alerts_config.json 에 커밋 → 본 스크립트가 GitHub Actions(stock-alerts.yml,
  장중 매분 — Worker cron dispatch, GHA schedule 5분은 폴백)에서 실행되어
  조건 충족 알림을 카카오톡으로 발송한다. (조건 충족→도착 최악 ~2분)

지원 조건(type):
  price_above / price_below — 목표 가격 도달(이상/이하)
  pct_change               — 전일 종가 대비 등락률 도달(양수=상승, 음수=하락)
  high52 / low52           — 52주 신고가/신저가 도달
  vol_surge                — 당일 거래량이 전일 거래량의 value%(기본 300) 이상
  golden_cross/dead_cross  — 이동평균선(maShort/maLong) 골든/데드크로스 발생일

도배 방지(필수 예외 처리 — PRD):
  가격 기준선(price_below/price_above) — '교차 시 1회 + 재무장':
    미충족→충족으로 전환되는 순간(기준선 돌파)에만 1회 발송하고, 가격이 기준선
    아래(이하 알림)/위(이상 알림)에 머무는 동안은 침묵한다. 가격이 기준선 반대편으로
    회복하면 재무장되어 다음 돌파에서 다시 발송한다. 각 알림의 직전 충족 여부는
    alerts_state.json 의 met 필드에 매 런 기록된다(발송 여부와 무관).
  이벤트형(pct_change/high52/low52/vol_surge/golden_cross/dead_cross):
    limit="daily"  → 같은 알림은 하루(KST) 1회만 발송
    limit="cool60" → 발송 후 1시간 동안 같은 알림 재발송 금지
  종목당 1줄 — 한 종목에서 여러 조건이 동시 충족되면 현재가에 '가장 근접한' 1건만
    발송한다(가격 사다리 동시 충족 시 폭주 방지). 미발송 건도 이력(met/date/ts)은 갱신.
  발송 이력은 alerts_state.json 에 기록되고 워크플로가 커밋해 런 간 보존된다.

데이터 소스(무료·수분 지연 가능):
  한국: 네이버 모바일 API(현재가/등락률) + 네이버 일봉 차트(MA/52주/거래량) — 신규 상장 ETF 포함
  미국: Yahoo Finance 차트 API (러너 IP 차단 대비 전용 Worker/공개 프록시 폴백)
  → 모든 알림 메시지에 시세 지연 고지 문구를 포함한다(PRD 필수). 소스 자체는 실시간급이지만
    무료 API 라 보장이 없어 보수적으로 고지한다. (구 문구 "15분 지연"은 실측과 달라 완화 —
    실제 병목은 평가 주기였고 2026-07-03 매분 평가로 단축됨.)

필요한 GitHub Secrets: KAKAO_REST_API_KEY, KAKAO_REFRESH_TOKEN (시황 다이제스트와 공용)
"""
import os
import re
import json
import datetime

# 카카오 발송/토큰 유틸은 시황 다이제스트와 공용 (scripts/ 가 sys.path[0])
import send_kakao_digest as kakao

KST = datetime.timezone(datetime.timedelta(hours=9))
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CONFIG_PATH = os.path.join(ROOT, "alerts_config.json")
STATE_PATH = os.path.join(ROOT, "alerts_state.json")
TEXT_LIMIT = 200          # 카카오 텍스트 템플릿 길이 제한
MAX_MSGS = 3              # 1회 실행당 최대 발송 통수(폭주 방지)
DELAY_NOTICE = "※ 무료 시세 기준(지연 가능)"
# 시세 오염 방어 — 무료 프록시가 0/오종목/캐시된 이상치를 돌려줄 수 있다.
# 전일 종가 대비 이 %를 넘게 벌어진 스냅샷은 오염 의심으로 폐기(국내 상·하한 ±30% 여유 위).
SANE_MOVE_PCT = 50.0

# 🔔 테스트 발송 모드 — 프런트 '테스트 발송' 버튼 → Worker /portfolio/test →
# repository_dispatch(alerts-test) 로 실행된 런. 설정 검증이 목적이므로
# 장중/쿨다운 가드를 무시하고 평가하며, 발송 이력(state)은 갱신하지 않아
# 이후 정규 cron 의 실제 알림 1일 1회 한도를 소모하지 않는다.
# ⚠️ repository_dispatch 전체가 아니라 'alerts-test' 액션만 테스트로 본다 — Worker cron 의
#    정시성 보강용 'alerts-cron' dispatch 는 정규 런(가드·이력 갱신 적용)이어야 하기 때문.
#    워크플로가 ALERTS_TEST=true/false 를 명시 전달한다(stock-alerts.yml).
IS_TEST = os.environ.get("ALERTS_TEST") == "true"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
WORKER = "https://ecom-dashboard-proxy.baldr0001.workers.dev"


def _now():
    return datetime.datetime.now(KST)


def _http_get_json(url, mobile=False):
    """GET JSON — 직접 호출 실패 시 전용 Worker → 공개 프록시 순 폴백(러너 IP 차단 대비)."""
    try:
        import requests
        from urllib.parse import quote_plus
    except Exception:
        return None
    headers = {"User-Agent": UA, "Accept": "application/json,text/plain,*/*"}
    if mobile:
        headers["Referer"] = "https://m.stock.naver.com/"
    candidates = [
        url,
        f"{WORKER}/?url={quote_plus(url)}",
        f"https://api.allorigins.win/raw?url={quote_plus(url)}",
        f"https://api.codetabs.com/v1/proxy/?quest={quote_plus(url)}",
    ]
    for u in candidates:
        try:
            r = requests.get(u, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            j = r.json()
            if j:
                return j
        except Exception:
            continue
    return None


def _http_get_text(url):
    try:
        import requests
        from urllib.parse import quote_plus
    except Exception:
        return None
    headers = {"User-Agent": UA, "Referer": "https://m.stock.naver.com/"}
    candidates = [
        url,
        f"{WORKER}/?url={quote_plus(url)}",
        f"https://api.allorigins.win/raw?url={quote_plus(url)}",
        f"https://api.codetabs.com/v1/proxy/?quest={quote_plus(url)}",
    ]
    for u in candidates:
        try:
            r = requests.get(u, headers=headers, timeout=15)
            if r.status_code == 200 and r.text and len(r.text) > 50:
                return r.text
        except Exception:
            continue
    return None


# ── 시세 스냅샷 ──────────────────────────────────────────────────────────────
def yahoo_snapshot(symbol):
    """Yahoo 1y 일봉 → {price, pct, closes, highs, lows, vol_today, vol_prev}."""
    j = _http_get_json("https://query1.finance.yahoo.com/v8/finance/chart/"
                       f"{symbol}?range=1y&interval=1d")
    res = (((j or {}).get("chart") or {}).get("result") or [None])[0]
    if not res:
        return None
    meta = res.get("meta") or {}
    quote = (((res.get("indicators") or {}).get("quote") or [{}])[0]) or {}
    rows = [(o, h, l, c, v) for o, h, l, c, v in zip(
        quote.get("open") or [], quote.get("high") or [], quote.get("low") or [],
        quote.get("close") or [], quote.get("volume") or []) if c is not None]
    if len(rows) < 2:
        return None
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if price is None:
        price = rows[-1][3]
    if not prev:
        prev = rows[-2][3]
    closes = [r[3] for r in rows]
    closes[-1] = float(price)  # 마지막 봉은 '현재가' 기준 (장중 라이브 반영)
    return {
        "price": float(price),
        "pct": (float(price) / float(prev) - 1) * 100 if prev else 0.0,
        "closes": closes,
        "highs": [r[1] for r in rows if r[1] is not None],
        "lows": [r[2] for r in rows if r[2] is not None],
        "vol_today": float(rows[-1][4] or 0) or None,
        "vol_prev": float(rows[-2][4] or 0) or None,
    }


def naver_snapshot(code):
    """네이버(국내) — basic API 현재가 + 일봉 차트 1년. 신규 상장 ETF(Yahoo 미등록)도 동작."""
    basic = _http_get_json(f"https://m.stock.naver.com/api/stock/{code}/basic", mobile=True)
    price = pct = None
    if basic:
        try:
            price = float(str(basic.get("closePrice", "")).replace(",", ""))
            pct = float(str(basic.get("fluctuationsRatio", "")).replace(",", ""))
        except (TypeError, ValueError):
            price = pct = None

    fmt = lambda d: d.strftime("%Y%m%d")
    end = _now()
    start = end - datetime.timedelta(days=400)
    txt = _http_get_text(
        "https://m.stock.naver.com/front-api/external/chart/domestic/info"
        f"?symbol={code}&requestType=1&startTime={fmt(start)}&endTime={fmt(end)}&timeframe=day")
    rows = []
    if txt:
        for m in re.finditer(
                r'\[\s*"?(\d{8})"?\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)', txt):
            rows.append((m.group(1), float(m.group(2)), float(m.group(3)),
                         float(m.group(4)), float(m.group(5)), float(m.group(6))))
    if not rows and price is None:
        return None
    closes = [r[4] for r in rows]
    highs = [r[2] for r in rows]
    lows = [r[3] for r in rows]
    vol_today = vol_prev = None
    today = fmt(end)
    if rows:
        if rows[-1][0] == today:                       # 마지막 행이 '당일' → 라이브 봉
            vol_today = rows[-1][5] or None
            vol_prev = rows[-2][5] if len(rows) >= 2 else None
            if price is not None:
                closes[-1] = price
        elif price is not None:                        # 당일 행 없음 → 현재가를 덧붙임
            closes.append(price)
            highs.append(price)
            lows.append(price)
            vol_prev = rows[-1][5] or None
    if price is None and closes:
        price = closes[-1]
        if len(closes) >= 2 and pct is None:
            pct = (closes[-1] / closes[-2] - 1) * 100
    if price is None:
        return None
    return {
        "price": float(price), "pct": float(pct or 0.0),
        "closes": closes, "highs": highs, "lows": lows,
        "vol_today": vol_today, "vol_prev": vol_prev,
    }


def get_snapshot(market, symbol, yahoo_sym):
    if market == "KR":
        snap = naver_snapshot(symbol)
        if snap:
            return snap
        for suf in (".KS", ".KQ"):
            snap = yahoo_snapshot(yahoo_sym or (symbol + suf))
            if snap:
                return snap
        return None
    return yahoo_snapshot(yahoo_sym or symbol)


# ── 조건 평가 ────────────────────────────────────────────────────────────────
def _sma(arr, n, end=None):
    """arr[:end] 의 마지막 n 개 단순평균 (데이터 부족 시 None)."""
    a = arr if end is None else arr[:end]
    if n <= 0 or len(a) < n:
        return None
    return sum(a[-n:]) / n


def _fmt_price(v, market):
    if market == "KR":
        return f"{v:,.0f}원"
    return f"${v:,.2f}"


def evaluate(alert, snap):
    """충족 시 메시지 한 줄 반환, 아니면 None."""
    t = alert.get("type")
    v = alert.get("value")
    market = alert.get("market", "KR")
    price, pct = snap["price"], snap["pct"]
    head = f"{alert.get('name') or alert.get('symbol')} {_fmt_price(price, market)}({pct:+.1f}%)"

    if t == "price_above" and v is not None and price >= v:
        return f"{head} 목표가 {_fmt_price(v, market)} 이상 도달"
    if t == "price_below" and v is not None and price <= v:
        return f"{head} 지정가 {_fmt_price(v, market)} 이하 하락"
    if t == "pct_change" and v:
        if (v > 0 and pct >= v) or (v < 0 and pct <= v):
            return f"{head} 등락률 {v:+g}% 도달"
        return None
    if t == "high52":
        highs = snap["highs"]
        if len(highs) >= 60 and price >= max(highs[:-1]):
            return f"{head} 52주 신고가"
        return None
    if t == "low52":
        lows = snap["lows"]
        if len(lows) >= 60 and price <= min(lows[:-1]):
            return f"{head} 52주 신저가"
        return None
    if t == "vol_surge":
        ratio_req = (v or 300) / 100.0
        vt, vp = snap.get("vol_today"), snap.get("vol_prev")
        if vt and vp and vt >= vp * ratio_req:
            return f"{head} 거래량 전일比 {vt / vp * 100:,.0f}% 폭증"
        return None
    if t in ("golden_cross", "dead_cross"):
        s, l = int(alert.get("maShort") or 20), int(alert.get("maLong") or 60)
        closes = snap["closes"]
        ms_now, ml_now = _sma(closes, s), _sma(closes, l)
        ms_prev, ml_prev = _sma(closes, s, -1), _sma(closes, l, -1)
        if None in (ms_now, ml_now, ms_prev, ml_prev):
            return None
        if t == "golden_cross" and ms_prev <= ml_prev and ms_now > ml_now:
            return f"{head} 골든크로스(MA{s}/{l}) 발생"
        if t == "dead_cross" and ms_prev >= ml_prev and ms_now < ml_now:
            return f"{head} 데드크로스(MA{s}/{l}) 발생"
        return None
    return None


# ── 도배 방지(발송 제한) ────────────────────────────────────────────────────
def should_send(alert, state, now):
    """이벤트형(52주/크로스/등락률/거래량) 쿨다운 가드. 가격 기준선은 교차감지로 별도 처리."""
    rec = state.get(alert["id"]) or {}
    if alert.get("limit") == "cool60":
        return (now.timestamp() - float(rec.get("ts") or 0)) >= 3600
    return rec.get("date") != now.strftime("%Y%m%d")     # 기본: 하루 1회


PRICE_TYPES = ("price_below", "price_above")


def _price_met(t, price, v, snap=None):
    """가격 기준선 충족 여부 — 이하/이상.

    cron 이 한두 분 드롭돼 교차 순간을 지나쳐도 놓치지 않도록, 순간 현재가가 아니라
    '당일 장중 고가/저가'(마지막 일봉의 high/low)를 기준으로 판정한다. 하루 안에서 한 번이라도
    기준선을 넘었으면 충족으로 본다(met 는 회복 시 재무장 — 일봉이 갱신되는 다음 날 자연 리셋)."""
    if v is None:
        return False
    if t == "price_below":
        low = price
        if snap and snap.get("lows"):
            low = min(low, snap["lows"][-1])
        return low <= v
    high = price
    if snap and snap.get("highs"):
        high = max(high, snap["highs"][-1])
    return high >= v


# 종목당 1줄 — 한 종목에서 여러 조건이 동시 충족되면 가장 의미 있는 1건만 남긴다.
# 가격 사다리(이하/이상)는 현재가에 '가장 근접한' 기준선을 채택하고, 그 외 이벤트는
# 가격 기준선이 없을 때만 고정 우선순위로 채택한다.
_EVENT_RANK = {"low52": 0, "high52": 0, "dead_cross": 1, "golden_cross": 1,
               "pct_change": 2, "vol_surge": 3}


def _dedup_per_symbol(triggered, snaps):
    """[(alert, line)] → 종목당 현재가 최근접 1건만. 입력 순서 보존."""
    by_sym, order = {}, []
    for a, line in triggered:
        key = (a.get("market", "KR"), a.get("symbol"))
        if key not in by_sym:
            by_sym[key] = []
            order.append(key)
        by_sym[key].append((a, line))

    def score(item):
        a = item[0]
        v = a.get("value")
        snap = snaps.get((a.get("market", "KR"), a.get("symbol")))
        price = snap["price"] if snap else None
        if v is not None and price is not None:           # 가격 기준선 → 현재가 최근접
            return (0, abs(price - v))
        return (1, _EVENT_RANK.get(a.get("type"), 9))     # 이벤트 → 고정 우선순위

    out = []
    for key in order:
        winner = min(by_sym[key], key=score)
        out.append(winner)
    return out


def _write_state(state, alerts, now):
    """유효 알림만 남겨 alerts_state.json 기록(삭제된 알림 이력 정리)."""
    valid_ids = {a["id"] for a in alerts}
    pruned = {k: v for k, v in state.items() if k in valid_ids}
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _stamp_and_write(state, triggered, alerts, now):
    """충족 알림에 date/ts 스탬프 후 alerts_state.json 기록.

    ⚠ '발송 전에' 호출한다 — 카카오 전송이 5xx 등으로 실패해도(메시지는 이미 나갔을 수 있음)
    이력이 남아, 다음 런에서 같은 알림이 매분 재발송되는 스팸 루프를 막는다.
    (전송 성공 보장보다 재발송 억제를 우선한다 — 교차형은 met, 이벤트형은 date/ts 로 재무장 관리.)"""
    ds = now.strftime("%Y%m%d")
    ts = int(now.timestamp())
    for a, _ in triggered:
        rec = state.get(a["id"]) or {}
        rec["date"] = ds
        rec["ts"] = ts
        state[a["id"]] = rec
    _write_state(state, alerts, now)


def is_market_open(market, now):
    """장중 판정(KST) — 장외 시간엔 가격이 멈춰 stale 데이터로 쿨다운 알림이 반복 발송될 수
    있으므로(특히 cool60), 해당 시장 장중에만 조건을 평가한다."""
    wd, t = now.weekday(), now.hour * 60 + now.minute
    if market == "KR":
        # 평일 09:00 ~ 15:40
        return wd < 5 and (9 * 60) <= t <= (15 * 60 + 40)
    # 미국: KST 밤 22:30 ~ 익일 06:10 (서머타임 22:30 / 표준시 23:30 개장 — 넉넉히 포함)
    if t >= (22 * 60 + 30):
        return wd < 5                  # 월~금 밤 (미국 당일 개장)
    if t <= (6 * 60 + 10):
        return 1 <= wd <= 5            # 화~토 새벽 (미국 전일 세션 마감 전)
    return False


def _pack_messages(lines, header):
    """알림 줄들을 카카오 텍스트 한도(200자) 내 여러 통으로 분할."""
    msgs, cur = [], header
    budget = TEXT_LIMIT - len(DELAY_NOTICE) - 1
    for ln in lines:
        add = "\n" + ln
        if len(cur) + len(add) > budget and cur != header:
            msgs.append(cur + "\n" + DELAY_NOTICE)
            cur = header
        if len(cur) + len(add) <= budget:
            cur += add
        else:                                          # 한 줄이 그 자체로 너무 긴 경우 자름
            cur += add[:budget - len(cur)]
    if cur != header:
        msgs.append(cur + "\n" + DELAY_NOTICE)
    if len(msgs) > MAX_MSGS:
        print(f"::warning title=알림 통수 초과::{len(msgs)}통 중 {MAX_MSGS}통만 발송(초과분 생략) — "
              f"동시 충족 조건이 과다합니다")
    return msgs[:MAX_MSGS]


def main():
    now = _now()

    # 설정 파일 없음/알림 없음 → 조용히 종료(아직 설정 전 — 실패 알림 메일 방지)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        print("[alerts] alerts_config.json 없음 — '투자 현황' 페이지에서 알림을 저장하면 생성됩니다.")
        return
    # [3차-T26] 전역 알림 설정 — 사이트 '설정' 페이지에서 저장한 settings 블록 반영.
    # 구버전 파일(settings 없음)은 ON + daily 로 동작한다(하위 호환).
    settings = cfg.get("settings") or {}
    if settings.get("enabled") is False and not IS_TEST:
        print("[alerts] 전역 알림 OFF (설정 페이지에서 비활성화) — 평가 건너뜀")
        return
    default_limit = "cool60" if settings.get("defaultLimit") == "cool60" else "daily"
    alerts = [a for a in (cfg.get("alerts") or []) if isinstance(a, dict) and a.get("enabled", True)]
    if not alerts:
        print("[alerts] 활성 알림 0개 — 종료")
        return
    for a in alerts:
        if not a.get("limit"):
            a["limit"] = default_limit   # [3차-T26] 개별 미지정 시 전역 기본 도배방지 주기 적용

    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}

    # 종목별 스냅샷 1회 조회 (알림 여러 개가 같은 종목을 공유)
    snaps = {}
    triggered = []          # (alert, line) — 충족·발송 후보 (종목당1줄 축약 전)
    met_now = {}            # alert id -> 현재 가격조건 충족 여부 (재무장 판정용, 매 런 기록)
    for a in alerts:
        market = a.get("market", "KR")
        # 테스트 발송은 즉시 검증이 목적 — 장중/쿨다운/교차 가드를 건너뛰고 무조건 평가
        if not IS_TEST and not is_market_open(market, now):
            continue
        t = a.get("type")
        is_price = t in PRICE_TYPES
        # 이벤트형은 기존 쿨다운(daily/cool60) 가드 유지. 가격 기준선은 교차감지로 별도 판정.
        if not is_price and not IS_TEST and not should_send(a, state, now):
            continue
        key = (market, a.get("symbol"))
        if key not in snaps:
            snaps[key] = get_snapshot(market, a.get("symbol"), a.get("yahoo"))
        snap = snaps[key]
        if not snap:
            print(f"[alerts] 시세 조회 실패: {a.get('symbol')} ({market}) — 건너뜀")
            continue
        # 시세 오염 가드 — 0/음수·비정상 급변(전일比 |%|>SANE) 스냅샷은 폐기해 헛알림 방지.
        if snap["price"] <= 0 or abs(snap.get("pct") or 0.0) > SANE_MOVE_PCT:
            print(f"::warning title=시세 이상::{a.get('symbol')}({market}) 가격 {snap['price']} "
                  f"전일比 {snap.get('pct')}% — 오염 의심, 건너뜀")
            continue

        if is_price:
            m = _price_met(t, snap["price"], a.get("value"), snap)
            met_now[a["id"]] = m                          # 매 런 기록 → 회복 시 재무장
            prev = (state.get(a["id"]) or {}).get("met")
            # 교차 시 1회: 미충족→충족 전환에서만 발송. 충족 지속 중엔 침묵.
            fire = m if IS_TEST else (m and prev is not True)
            if not fire:
                continue
        try:
            line = evaluate(a, snap)
        except Exception as e:
            print(f"[alerts] 평가 오류({a.get('id')}): {e}")
            continue
        if line:
            triggered.append((a, line))
            print(f"[alerts] 조건 충족: {line}")

    # 종목당 1줄 — 동시 충족(사다리/이벤트)을 현재가 최근접 1건으로 축약
    to_send = _dedup_per_symbol(triggered, snaps)

    # 재무장 상태(met)는 발송 여부와 무관하게 항상 보존 → 다음 교차 때 재발송 보장
    if not IS_TEST:
        for aid, m in met_now.items():
            rec = state.get(aid) or {}
            rec["met"] = m
            state[aid] = rec

    if not triggered and not IS_TEST:
        _write_state(state, alerts, now)
        print(f"[alerts] 평가 {len(alerts)}건 — 발송 0건(미충족/충족지속) — 재무장 상태만 저장")
        return

    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if not rest_key or not refresh_token:
        print("::warning title=Kakao 미설정::KAKAO_REST_API_KEY/KAKAO_REFRESH_TOKEN 시크릿이 없어 "
              "알림 발송을 건너뜁니다 (KAKAO_SETUP.md 참고).")
        return

    # 토큰 재발급 실패는 '매분' 실행에선 job 실패 메일 폭탄으로 이어지므로, 한 번만 크게 경고하고
    # exit 0 로 끝낸다(메일 스팸 방지). 재무장/이력 상태는 저장해 다음 런 일관성 유지.
    try:
        access_token = kakao.refresh_access_token(rest_key, refresh_token)
    except SystemExit as e:
        print(f"::error title=Kakao 토큰 재발급 실패::{e} — 이번 발송 건너뜀(토큰 갱신 필요)")
        if not IS_TEST:
            _stamp_and_write(state, triggered, alerts, now)
        return
    friends = kakao.get_friends(access_token) if kakao._friends_enabled() else []
    uuids = [f["uuid"] for f in friends]
    if uuids:
        print(f"[alerts] 수신: 친구 {len(uuids)}명")
    else:
        print("::warning title=푸시 미도달 가능::수신 친구 0명 → '나에게 보내기(메모)'로 발송합니다. "
              "메모는 푸시 알림이 울리지 않습니다(friends scope 필요 — KAKAO_SETUP.md ⑤).")

    prefix = "[테스트] " if IS_TEST else ""
    header = f"{prefix}🔔 {now.month}/{now.day} {now.hour:02d}:{now.minute:02d} 종목 알림"
    if IS_TEST and settings.get("enabled") is False:
        header += "\n⚠ 전역 알림이 OFF 상태입니다 — 정규 알림은 발송되지 않습니다 (테스트만 동작)"
    if IS_TEST and not triggered:
        # 테스트인데 충족 알림이 없어도 확인 메시지 1통은 보낸다 — '파이프라인 정상' 즉시 검증이 목적
        kakao.send_memo(access_token,
                        f"{header}\n알림 {len(alerts)}건 평가 — 현재 충족 조건 없음 (설정·발송 경로 정상)\n{DELAY_NOTICE}",
                        with_button=True, uuids=uuids)
        print(f"[alerts] 테스트 발송 — 평가 {len(alerts)}건, 충족 0건 (확인 메시지 발송)")
        return

    # 🛡 발송 '전에' 이력을 먼저 확정·저장한다(스팸 루프 방지 — _stamp_and_write 주석 참고).
    #    테스트 런은 이력을 남기지 않는다(정규 cron 의 실제 알림을 소모하지 않도록).
    if not IS_TEST:
        _stamp_and_write(state, triggered, alerts, now)

    sent = 0
    try:
        for msg in _pack_messages([ln for _, ln in to_send], header):
            kakao.send_memo(access_token, msg, with_button=True, uuids=uuids)
            sent += 1
    except SystemExit as e:
        # 일부 통 실패해도 job 을 죽이지 않는다(매분 실패 메일·커밋 스텝 스킵 방지). 이력은 이미 저장됨.
        print(f"::warning title=일부 알림 발송 실패::{e} — {sent}통 발송 후 중단(이력 저장됨, 재발송 안 함)")

    if IS_TEST:
        print(f"[alerts] 테스트 발송 완료 — 충족 {len(triggered)}건 / 발송 {len(to_send)}건 (이력 미갱신)")
        return
    print(f"[alerts] 발송 완료 — 충족 {len(triggered)}건 / 발송 시도 {len(to_send)}건, 상태 저장(발송 전 확정)")


if __name__ == "__main__":
    main()
