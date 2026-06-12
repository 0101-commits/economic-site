#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""주식/ETF 카카오톡 알림 — alerts_config.json 의 조건을 평가해 충족 시 카카오톡으로 발송한다.

흐름:
  '투자 현황' 페이지에서 설정한 알림 조건을 Cloudflare Worker(POST /portfolio)가
  저장소 alerts_config.json 에 커밋 → 본 스크립트가 GitHub Actions(stock-alerts.yml,
  장중 15분 주기)에서 실행되어 조건 충족 알림을 카카오톡으로 발송한다.

지원 조건(type):
  price_above / price_below — 목표 가격 도달(이상/이하)
  pct_change               — 전일 종가 대비 등락률 도달(양수=상승, 음수=하락)
  high52 / low52           — 52주 신고가/신저가 도달
  vol_surge                — 당일 거래량이 전일 거래량의 value%(기본 300) 이상
  golden_cross/dead_cross  — 이동평균선(maShort/maLong) 골든/데드크로스 발생일

도배 방지(필수 예외 처리 — PRD):
  limit="daily"  → 같은 알림은 하루(KST) 1회만 발송
  limit="cool60" → 발송 후 1시간 동안 같은 알림 재발송 금지
  발송 이력은 alerts_state.json 에 기록되고 워크플로가 커밋해 런 간 보존된다.

데이터 소스(무료·15분 지연 가능):
  한국: 네이버 모바일 API(현재가/등락률) + 네이버 일봉 차트(MA/52주/거래량) — 신규 상장 ETF 포함
  미국: Yahoo Finance 차트 API (러너 IP 차단 대비 전용 Worker/공개 프록시 폴백)
  → 모든 알림 메시지에 "15분 지연 데이터 기준" 문구를 포함한다(PRD 필수).

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
DELAY_NOTICE = "※ 15분 지연 데이터 기준"

# 🔔 테스트 발송 모드 — 프런트 '테스트 발송' 버튼 → Worker /portfolio/test →
# repository_dispatch(alerts-test) 로 실행된 런. 설정 검증이 목적이므로
# 장중/쿨다운 가드를 무시하고 평가하며, 발송 이력(state)은 갱신하지 않아
# 이후 정규 cron 의 실제 알림 1일 1회 한도를 소모하지 않는다.
IS_TEST = os.environ.get("GITHUB_EVENT_NAME") == "repository_dispatch"

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
    rec = state.get(alert["id"]) or {}
    if alert.get("limit") == "cool60":
        return (now.timestamp() - float(rec.get("ts") or 0)) >= 3600
    return rec.get("date") != now.strftime("%Y%m%d")     # 기본: 하루 1회


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
    triggered = []          # (alert, line)
    for a in alerts:
        market = a.get("market", "KR")
        # 테스트 발송은 즉시 검증이 목적 — 장중/쿨다운 가드를 건너뛰고 무조건 평가
        if not IS_TEST and not is_market_open(market, now):
            continue
        if not IS_TEST and not should_send(a, state, now):
            continue
        key = (market, a.get("symbol"))
        if key not in snaps:
            snaps[key] = get_snapshot(market, a.get("symbol"), a.get("yahoo"))
        snap = snaps[key]
        if not snap:
            print(f"[alerts] 시세 조회 실패: {a.get('symbol')} ({market}) — 건너뜀")
            continue
        try:
            line = evaluate(a, snap)
        except Exception as e:
            print(f"[alerts] 평가 오류({a.get('id')}): {e}")
            continue
        if line:
            triggered.append((a, line))
            print(f"[alerts] 조건 충족: {line}")

    if not triggered and not IS_TEST:
        print(f"[alerts] 평가 {len(alerts)}건 — 충족 0건, 발송 없음")
        return

    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if not rest_key or not refresh_token:
        print("::warning title=Kakao 미설정::KAKAO_REST_API_KEY/KAKAO_REFRESH_TOKEN 시크릿이 없어 "
              "알림 발송을 건너뜁니다 (KAKAO_SETUP.md 참고).")
        return

    access_token = kakao.refresh_access_token(rest_key, refresh_token)
    friends = kakao.get_friends(access_token) if kakao._friends_enabled() else []
    uuids = [f["uuid"] for f in friends]
    print(f"[alerts] 수신: " + (f"친구 {len(uuids)}명" if uuids else "나와의 채팅(메모)"))

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
    for msg in _pack_messages([ln for _, ln in triggered], header):
        kakao.send_memo(access_token, msg, with_button=True, uuids=uuids)

    # 테스트 런은 이력을 남기지 않는다 — 정규 cron 의 실제 알림(1일 1회/쿨다운)을 소모하지 않도록
    if IS_TEST:
        print(f"[alerts] 테스트 발송 완료 — 알림 {len(triggered)}건 (이력 미갱신)")
        return

    # 발송 성공 후에만 이력 갱신 → 워크플로가 커밋해 도배 방지 이력 보존
    for a, _ in triggered:
        state[a["id"]] = {"date": now.strftime("%Y%m%d"), "ts": int(now.timestamp())}
    # 오래된 이력 정리(설정에서 삭제된 알림)
    valid_ids = {a["id"] for a in alerts}
    state = {k: v for k, v in state.items() if k in valid_ids}
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[alerts] 발송 완료 — 알림 {len(triggered)}건, 상태 저장")


if __name__ == "__main__":
    main()
