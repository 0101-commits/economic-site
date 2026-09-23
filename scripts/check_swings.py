#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""시장 급변 속보(옵션 A) — 지수·환율이 임계치를 넘게 움직이면 슬롯과 무관하게 즉시 카카오톡 1통.

stock-alerts.yml 의 별도 스텝으로 장중 매분(Worker cron dispatch) 실행된다.
서킷브레이커 알림(check_halts, -8% 이상 시장 중단)과 역할 구분 — 이쪽은 그 '전 단계' 조기 경보.

규칙(기획안 2026-09-21 P0 — 고정 %에서 σ 대비로):
  |z| ≥ 2.5 (z = 전일比 등락률 ÷ 최근 250거래일 일간 수익률 σ).
  σ 를 못 구하면(표본 60개 미만) 종전 고정 임계(코스피·S&P ±2% / 달러-원 ±1%)로 폴백한다.

  왜 바꿨나: 고정 ±2% 는 자산마다 전혀 다른 드물기를 뜻했다. 최근 250일 코스피 σ=3.38%
  라 ±2% 가 연 103회 발동한 반면 S&P500 은 σ=0.81% 라 연 5회였다(27배 격차). 최근
  60거래일만 보면 코스피가 ±2% 를 넘는 날이 50.0% — 격일로 @everyone 이 울렸다.
  롤링 σ 백테스트(최근 500거래일) 기준 2.5σ 의 연간 발동은 자산당 5~16회다.

  FLOOR_PCT: 초저변동 국면에서 z 만 보면 0.3% 움직임도 '급변'이 된다 — 절대 하한을 둔다.
도배 방지:
  같은 심볼·같은 방향은 하루(KST) 1회 — 방향이 바뀌면(급락→급반등) 당일에도 다시 알린다.
  쿨다운은 alerts_state.json 의 "_swings" 키에 기록(소유권 본 스크립트,
  check_alerts._write_state 가 '_' 접두 키를 보존한다). 워크플로 커밋 경로는 기존 그대로.
안전:
  발송 성공 후에만 쿨다운 확정(실패 시 다음 런 재시도). 시세 오염(|pct|>50%)·휴장(fresh=False)
  스킵. 모든 실패는 경고 후 exit 0 — 매분 런이라 job 실패 = 실패 메일 폭탄.
"""
import os
import json
import datetime

import check_alerts as ca               # yahoo_snapshot / is_market_open 재사용
import send_kakao_digest as kakao       # 토큰 재발급·발송 공용
import volatility as vol                # σ 정규화 임계(P0)

KST = datetime.timezone(datetime.timedelta(hours=9))
STATE_PATH = ca.STATE_PATH              # alerts_state.json — "_swings" 키만 소유

# (표시명, Yahoo 심볼, 세션, σ 못 구할 때의 폴백 임계%) — 세션 "ANY"=본 워크플로가 도는 시간대 전부
SWING_RULES = [
    ("코스피", "^KS11", "KR", 2.0),
    ("S&P500", "^GSPC", "US", 2.0),
    ("달러-원", "KRW=X", "ANY", 1.0),
]
# 야후 심볼 → NAVER_LINKS 키. 카카오·디스코드 두 경로가 같은 표를 봐야 한 알림 안에서
# 사진 탭·버튼·제목이 다른 곳으로 가지 않는다(2026-09-22 — 종전엔 디스코드에만 있었다).
_SYM2KEY = {"^KS11": "KOSPI", "^GSPC": "SP500", "KRW=X": "USDKRW"}
Z_THRESHOLD = 2.5                        # |z| 이 값 이상이면 발동(기획안 T1)
FLOOR_PCT = 0.5                          # z 가 아무리 커도 이보다 작게 움직였으면 안 보낸다
# σ 정규화의 알려진 함정 — 위기 국면에선 σ 가 같이 부풀어 임계가 올라가고, 정작 시장이
# 사나울 때 경보가 조용해진다. 실측(2026-09): 코스피 σ=3.38% 라 2.5σ 임계가 ±8.5% 다.
# 그래서 z 와 무관하게 무조건 발동하는 절대 상한을 둔다. 서킷브레이커(check_halts)는
# ±8% 부터라, 그 사이 구간(5~8%)이 이 값이 메우는 자리다.
CEILING_PCT = 5.0
SANE_PCT = 50.0                          # 프록시 글리치 폐기선(지수·환율에 50%면 충분)


def _breach(pct, closes, fallback_thr):
    """발동 여부 판정 → (발동?, 임계%, 근거문구).

    σ 를 구할 수 있으면 z 기준, 못 구하면 종전 고정 임계로 폴백한다. 어느 경우든
    CEILING_PCT 를 넘으면 무조건 발동한다. 임계%는 카드가 그릴 선이고, 근거문구는
    embed 제목 아래 한 줄이다(z + 자연어 서수)."""
    sd = vol.sigma(closes)
    if sd is None:
        thr = min(fallback_thr, CEILING_PCT)
        return abs(pct) >= thr, thr, ""
    thr = min(max(Z_THRESHOLD * sd, FLOOR_PCT), CEILING_PCT)
    return abs(pct) >= thr, thr, vol.sigma_line(pct, closes)


def _move_day(market, now):
    """쿨다운 키의 '하루' — 등락률 기준 봉이 바뀌는 시점에 맞춘다.

    KR 은 KST 달력일. US·환율(ANY)은 KST-9h — 야후의 미국장 세션·환율 일봉이 KST 09시에
    넘어가서다. KST 달력일을 쓰면 자정에 키만 바뀌고 등락률은 그대로라 같은 급변이 또
    나갔다(2026-09-22 10:40 달러-원 ▼ → 09-23 00:00 같은 움직임 재발송, 실측)."""
    base = now if market == "KR" else now - datetime.timedelta(hours=9)
    return base.strftime("%Y-%m-%d")


def _session_open(market, now):
    if market == "ANY":
        return ca.is_market_open("KR", now) or ca.is_market_open("US", now)
    return ca.is_market_open(market, now)


def main():
    if os.environ.get("ALERTS_TEST") == "true":
        print("[swings] 테스트 dispatch — 급변 속보는 건너뜀(정규 cron 만 평가)")
        return
    now = datetime.datetime.now(KST)

    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    swings = state.get("_swings") or {}

    hits = []                            # (쿨다운 키, 발송 줄)
    for name, sym, market, fallback in SWING_RULES:
        if not _session_open(market, now):
            continue
        snap = ca.yahoo_snapshot(sym)
        if not snap:
            print(f"[swings] 시세 조회 실패: {name}({sym}) — 건너뜀")
            continue
        pct = snap.get("pct") or 0.0
        if snap["price"] <= 0 or abs(pct) > SANE_PCT:
            print(f"::warning title=시세 이상::{name} {snap['price']} {pct}% — 오염 의심, 건너뜀")
            continue
        if snap.get("fresh") is False:
            continue                     # 휴장(공휴일)/스테일 — 전일 종가로 오발동 방지
        fired, thr, why = _breach(pct, snap.get("closes"), fallback)
        if not fired:
            continue
        direction = "up" if pct > 0 else "down"
        key = f"{sym}:{direction}:{_move_day(market, now)}"
        if key in swings:
            continue                     # 같은 방향은 하루 1회
        arrow = "▲" if pct > 0 else "▼"
        nd = 1 if sym == "KRW=X" else 0              # 환율만 소수 1자리, 지수는 정수(단위 없음)
        # 줄에는 z 만 붙인다 — 서수 표현("최근 1년 중 N번째")은 제목이 담당한다.
        line = f"{name} {snap['price']:,.{nd}f} {arrow}{abs(pct):.1f}%"
        zpart = next((p for p in why.split(" · ") if p.startswith("z ")), "")
        if zpart:
            line += f"  ({zpart})"
        hits.append((key, line, name, sym, snap["price"], pct, thr, why))
        print(f"[swings] 급변 감지: {line} — 임계 ±{thr:.2f}%")

    if not hits:
        print(f"[swings] 규칙 {len(SWING_RULES)}건 평가 — 발동 0건")
        return

    msg = (f"⚡ {now.month}/{now.day} {now.hour:02d}:{now.minute:02d} 시장 급변\n"
           + "\n".join(h[1] for h in hits)
           + f"\n{ca.DELAY_NOTICE}")

    # 카카오 + 디스코드 병행 — 어느 한쪽이라도 성공하면 쿨다운 확정(같은 급변 재발송 방지).
    # 둘 다 실패한 경우만 미확정 → 다음 분 런이 재시도. job 은 항상 green(실패 메일 방지).
    sent_ok = False
    # 히어로(|등락| 최대) + 인트라데이는 여기서 1회만 조회해 두 채널이 같은 재료를 쓴다
    # (기획 v3 I1 — 카톡도 카드가 본문). P0 소스 체인(토스 1분봉→Yahoo→7일 일봉)으로 빈 패널 방지.
    _, _, name0, sym0, price0, pct0, thr0, why0 = max(hits, key=lambda h: abs(h[5]))
    xs, ys, prev, _src = [], [], None, ""
    try:
        xs, ys, prev, _src = kakao._intraday_chain(sym0)
    except Exception as _ie:
        print(f"[swings] 인트라데이 조회 예외({_ie}) — 카드는 히어로만")
    _lines = msg.split("\n")
    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if rest_key and refresh_token:
        try:
            access_token = kakao.refresh_access_token(rest_key, refresh_token)
            friends = kakao.get_friends(access_token) if kakao._friends_enabled() else []
            _kpng = None
            try:
                import discord_card
                _kpng = discord_card.swing(name0, price0, pct0, thr0, xs, ys, prev, now,
                                           src=_src, shape="square", why=why0)
            except Exception as _ce:
                print(f"[swings] 정사각 카드 예외({_ce}) — 텍스트 폴백")
            import notify_discord as _nd
            _url0 = _nd.NAVER_LINKS.get(_SYM2KEY.get(sym0))
            # 사진 탭 = 급변한 그 지표의 네이버 페이지, 대시보드는 버튼(2026-09-22).
            _btn0 = [(f"{name0} 시세", _url0)] if _url0 else []
            kakao.send_card(access_token, _lines[0][:44], "\n".join(_lines[1:4])[:120],
                            png=_kpng, uuids=[f["uuid"] for f in friends], kind="급변 속보",
                            link_url=_url0,
                            buttons=_btn0 + [("대시보드 보기", kakao.DASHBOARD_URL)])
            sent_ok = True
        except (SystemExit, Exception) as e:
            print(f"::warning title=급변 속보 카카오 실패::{e} — 디스코드 경로 시도")
    else:
        print("::warning title=Kakao 미설정::급변 속보 카카오 건너뜀 (KAKAO_SETUP.md 참고)")
    try:
        import notify_discord
        # 카드 D(기획 2026-08-11) — |등락| 최대 심볼을 히어로로, 인트라데이+임계선.
        # P0(기획 5154773b): 소스 체인(토스 1분봉→Yahoo→7일 일봉)으로 빈 패널 제거.
        # 렌더·시세 실패 시 None → 종전 텍스트 embed 그대로.
        _png = None
        try:
            import discord_card
            # 히어로·인트라데이는 위(카카오 경로 앞)에서 1회 조회한 값을 재사용한다.
            _png = discord_card.swing(name0, price0, pct0, thr0, xs, ys, prev, now,
                                      src=_src, why=why0)
        except Exception as _ce:
            print(f"[swings] 카드 렌더 예외({_ce}) — 텍스트만 발송")
        # v3 버튼 — 급변 지표의 네이버 증권 원클릭(봇 경로). 웹훅 폴백 시엔
        # notify_discord 가 링크 필드로 자동 변환해 도달을 보장한다.
        # v4 버튼 다이어트(기획 ed0e5496) — 위급 채널은 버튼 직행 유지하되 1행 3개 상한
        # (급변 지표 최대 2 + 대시보드 1). 라벨 등락률은 유지(카드 없이 올 수 있는 채널).
        # 순서를 뒤집었다(2026-09-22): 급변한 지표가 앞, 대시보드가 뒤 — 종전엔 첫 버튼이
        # 대시보드라 '그 지표를 보러 가는' 동선이 한 칸 뒤였다.
        _btns = []
        for _, _, nm, sym, _, pct, _, _ in hits[:2]:
            u = notify_discord.NAVER_LINKS.get(_SYM2KEY.get(sym))
            if u:
                _btns.append((notify_discord.dir_label(f"N {nm}", pct), u))
        _btns.append(("대시보드", "https://0101-commits.github.io/economic-site/?p=equity"))
        # 제목=결론 한 줄(기획안 원칙 4) — "언제 급변"이 아니라 "무엇이 얼마나 이례적으로".
        # 근거는 자연어 서수를 먼저 쓰고(금융 저널리즘 관행), 없으면 σ 배수로 적는다.
        # why0 = "z −2.6σ · 최근 1년 중 4번째로 큰 하락" — 서수 조각만 뽑아 쓴다
        # (시세를 다시 조회하지 않는다: 같은 런에서 두 번 부르면 값이 어긋날 수 있다).
        _rank = next((p for p in why0.split(" · ") if p.startswith("최근")), "")
        _head = f"⚡ {name0} {pct0:+.1f}%"
        if _rank:
            _head += f" — {_rank}"
        elif why0:
            _head += f" — 평소 움직임의 {abs(pct0) / max(thr0 / Z_THRESHOLD, 1e-9):.1f}배"
        # description 은 줄 목록만. 종전엔 why0 를 앞에 한 번 더 붙여, 같은 근거 문구가
        # 제목·description·본문 줄에 세 번 나왔다(실측). 카드가 본문이므로 텍스트는 짧게.
        if notify_discord.send(
                "\n".join(h[1] for h in hits), png=_png,
                title=_head[:256],
                # 제목 클릭 = 급변한 지표의 네이버 증권. 대시보드는 버튼(2026-09-22).
                url=(notify_discord.NAVER_LINKS.get(_SYM2KEY.get(sym0))
                     or "https://0101-commits.github.io/economic-site/?p=equity"),
                color=notify_discord.COLOR_FIRE, footer=ca.DELAY_NOTICE,
                timestamp=True, mention=True, env="DISCORD_WEBHOOK_SWINGS",
                buttons=_btns):
            sent_ok = True
    except Exception as e:
        print(f"[discord] 병행 발송 예외 무시: {e}")
    if not sent_ok:
        return

    # 발송 성공 후에만 쿨다운 확정 — 어제·오늘 키만 남겨 상태 파일이 자라지 않게 한다.
    # (US·환율 키는 KST-9h 날짜라 KST 오전엔 '어제' 날짜다 — 당일 키만 남기면 지워져 재발송된다.)
    keep = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    swings = {k: v for k, v in swings.items() if k.rsplit(":", 1)[-1] >= keep}
    for h in hits:
        swings[h[0]] = now.isoformat()
    state["_swings"] = swings
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError as e:
        print(f"::warning title=쿨다운 저장 실패::{e} — 같은 급변이 한 번 더 올 수 있음")
    print(f"[swings] 발송 완료 — {len(hits)}건")


if __name__ == "__main__":
    main()
