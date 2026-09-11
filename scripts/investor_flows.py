"""투자자별 순매수(외국인·기관·개인) — 알림용 단일 창구 + 두 소스 교차검증.

왜 필요한가
-----------
알림의 수급 숫자가 "실제 값"과 어긋난다는 신고(2026-09-11)를 추적한 결과:

1. 단위·스케일 버그는 없었다. 토스 원시 응답(`buyAmount-sellAmount`)을 1e8 로 나눈
   억원 값이 맞고, 4주체 합도 0 으로 닫힌다.
2. **같은 날 두 소스가 다른 값을 낸다**(억원, 토스 `updatedAt` 20:00 이후 실측):

   | 날짜 | 항목 | 토스 | 네이버 | 차 |
   |---|---|---|---|---|
   | 09-11 | 외국인 | -24,361 | -22,915 | -1,446 |
   | 09-11 | 기관 | -16,539 | -12,253 | -4,286 |
   | 09-10 | 개인 | +12,524 | +3,802 | +8,722 |
   | 09-10 | 기관 | -134 | +5,744 | -5,878 |

   KOSDAQ 도 수백억씩 어긋난다. 집계 유니버스/정의 차이이지 타이밍 문제가 아니다.
3. 알림은 `data.json` 의 investorTrading 마지막 행을 **날짜 검증 없이** 그대로 썼다.
   묵은 수집본이면 어제 수급이 오늘 카드에 실린다.

그래서 이 모듈의 계약
---------------------
* **표시값 = 네이버(포털·언론 기준)**. 사용자가 눈으로 대조하는 값이 그것이므로
  "알림 ≠ 실제 값"은 여기서 근본적으로 사라진다.
* **토스는 교차검증용**. 차이가 크면(부호 뒤집힘·`GROSS_PCT` 초과) 숫자를 아예
  내보내지 않는다 — 추정·보정 금지, 생략이 기본값.
* **오늘 날짜 행만** 오늘 카드에 쓴다. 날짜가 다르면 None.
* 엄격 일치 여부는 값을 죽이지 않고 `agree`/`maxDiffPct` 로 함께 돌려준다.
  (`TOL_ABS`/`TOL_PCT` 한 줄만 바꾸면 "완전 일치만 표기" 정책으로 조일 수 있다.)

`fetch_data.fetch_naver_investor_trading` 과 파서가 겹치지만 역할이 다르다 — 저쪽은
400영업일 히스토리 백필(페이지네이션·스케일 추정 포함), 이쪽은 최근 10영업일 검증.
알림 스크립트가 `fetch_data` 를 import 하면 pykrx·KRX 로그인까지 끌려와 6초+ 걸린다.
"""

import datetime
import re
import urllib.request

KST = datetime.timezone(datetime.timedelta(hours=9))

# 엄격 일치 판정(표시 여부를 좌우하지 않는 참고 플래그).
TOL_ABS = 200.0      # 억원
TOL_PCT = 0.05
# 총체적 오류(= 표시 차단) 임계. 부호 뒤집힘 또는 상대차 초과면 숫자를 내보내지 않는다.
GROSS_PCT = 0.35
GROSS_ABS = 1000.0          # 절대차가 이 미만(억원)이면 상대차가 커도 오류로 보지 않는다
GROSS_SIGN_FLOOR = 1000.0   # 이 미만(억원)은 부호 뒤집힘을 오류로 보지 않는다(0 근처 노이즈)

_NAVER_SOSOK = {"KOSPI": "01", "KOSDAQ": "02"}
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_KEYS = ("foreign", "inst", "retail")


def log(msg):
    print(f"[수급검증] {msg}")


def _num(s):
    s = re.sub(r"[,\s ]", "", s or "")
    if not s or s in ("-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def naver_daily(market="KOSPI", bizdate=None, timeout=15):
    """네이버 '일별 투자자별 매매동향' 최근 10영업일 → [{date, foreign, inst, retail, other}] 오름차순.

    표 구조(중첩 헤더): 날짜 | 개인 | 외국인 | 기관계 | 기관 6개 소분류 | 기타법인 = 11칸.
    캡션 단위는 억원(2026-09-11 실측). 형태가 달라지면 빈 리스트 — 추정하지 않는다.
    """
    sosok = _NAVER_SOSOK.get(market)
    if not sosok:
        return []
    bizdate = bizdate or datetime.datetime.now(KST).strftime("%Y%m%d")
    url = ("https://finance.naver.com/sise/investorDealTrendDay.naver"
           f"?bizdate={bizdate}&sosok={sosok}&page=1")
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept-Language": "ko-KR,ko;q=0.9"})
    html = urllib.request.urlopen(req, timeout=timeout).read().decode("euc-kr", "replace")
    if "억원" not in html:                       # 단위 캡션이 사라지면 값 의미를 보증할 수 없다
        log("네이버 표 단위 캡션(억원) 미확인 — 파싱 중단")
        return []
    rows = []
    for tr in re.findall(r"<tr.*?</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<t[hd].*?</t[hd]>", tr, re.S)]
        if len(cells) < 11:
            continue
        d = re.sub(r"\s", "", cells[0])
        if not re.match(r"^\d\d\.\d\d\.\d\d$", d):
            continue
        vals = [_num(cells[i]) for i in (1, 2, 3, 10)]
        if any(v is None for v in vals):
            continue
        retail, foreign, inst, other = vals
        rows.append({"date": "20" + d.replace(".", "-"), "foreign": foreign,
                     "inst": inst, "retail": retail, "other": other})
    rows.sort(key=lambda r: r["date"])
    return rows


def _toss_snapshot_daily(market="KOSPI", days=10):
    """PC 수집기가 커밋한 `toss_snapshot.json` 의 investorDaily → 같은 형태.

    **CI 에서 교차검증이 살아 있게 하는 경로다.** 토스 Open API 는 클라이언트별 허용 IP
    목록에 묶여 GitHub Actions 러너에서 403 이 떨어진다(CLAUDE.md 'Local Toss collector').
    그래서 라이브 호출이 비면 허용 IP PC 가 15분마다 갱신·커밋하는 스냅샷을 대신 읽는다.
    코스닥 시계열은 스냅샷에 없으므로 KOSPI 만 지원한다.
    """
    if market != "KOSPI":
        return []
    import json
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "toss_snapshot.json")
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f).get("investorDaily") or []
    except Exception as e:                                   # noqa: BLE001
        log(f"토스 스냅샷 읽기 실패: {e}")
        return []
    out = [{"date": r["date"], "updatedAt": None, "foreign": r.get("foreign"),
            "inst": r.get("inst"), "retail": r.get("retail")}
           for r in rows if isinstance(r, dict) and r.get("date")
           and all(isinstance(r.get(k), (int, float)) for k in _KEYS)]
    out.sort(key=lambda r: r["date"])
    return out[-days:]


def toss_daily(market="KOSPI"):
    """토스 투자자별 매매동향 최근 10영업일 → 같은 형태(+updatedAt).

    라이브 API(허용 IP PC) → 실패/키 없음이면 PC 스냅샷 파일. 둘 다 없으면 [].
    """
    try:
        import toss_api
    except ImportError:
        return _toss_snapshot_daily(market)
    if not toss_api.enabled():
        return _toss_snapshot_daily(market)
    try:
        res = toss_api.get(f"/api/v1/market-indicators/{market}/investor-trading",
                           {"interval": "1d"})
    except Exception as e:                                   # noqa: BLE001
        log(f"토스 라이브 조회 실패({e}) — PC 스냅샷으로 교차검증")
        return _toss_snapshot_daily(market)
    rows = []

    def _net(node):
        try:
            return (int(node["buyAmount"]) - int(node["sellAmount"])) / 1e8
        except (KeyError, TypeError, ValueError):
            return None

    for r in (res or {}).get("records") or []:
        vals = {"foreign": _net(r.get("foreigner") or {}),
                "inst": _net(r.get("institution") or {}),
                "retail": _net(r.get("individual") or {}),
                "other": _net(r.get("otherCorporation") or {})}
        if not r.get("date") or any(vals[k] is None for k in _KEYS):
            continue
        rows.append({"date": r["date"], "updatedAt": r.get("updatedAt"), **vals})
    rows.sort(key=lambda r: r["date"])
    return rows or _toss_snapshot_daily(market)


def _diff_pct(a, b):
    scale = max(abs(a), abs(b))
    return abs(a - b) / scale if scale else 0.0


def agree(a, b, tol_abs=TOL_ABS, tol_pct=TOL_PCT):
    """3주체 전부 허용오차 안인가 → (bool, 최대 상대차). 허용 = 절대 tol_abs 또는 상대 tol_pct."""
    worst = 0.0
    ok = True
    for k in _KEYS:
        av, bv = a.get(k), b.get(k)
        if av is None or bv is None:
            return False, 1.0
        worst = max(worst, _diff_pct(av, bv))
        if abs(av - bv) > max(tol_abs, tol_pct * max(abs(av), abs(bv))):
            ok = False
    return ok, worst


def gross_mismatch(a, b, gross_pct=GROSS_PCT):
    """총체적 오류(표시 차단 사유) → 사유 문자열, 없으면 None.

    부호 뒤집힘(양쪽 모두 GROSS_SIGN_FLOOR 이상), 또는 절대차 GROSS_ABS 초과 + 상대차 gross_pct 초과.
    """
    for k in _KEYS:
        av, bv = a.get(k), b.get(k)
        if av is None or bv is None:
            return f"{k} 결측"
        if (av > 0) != (bv > 0) and min(abs(av), abs(bv)) >= GROSS_SIGN_FLOOR:
            return f"{k} 부호 불일치({av:+,.0f} vs {bv:+,.0f})"
        # 0 근처에서는 상대차가 쉽게 100% 를 넘는다(+120 vs -130억) — 그건 표시값을
        # 틀리게 만들지 않으므로 절대차 문턱을 함께 요구한다.
        if abs(av - bv) > GROSS_ABS and _diff_pct(av, bv) > gross_pct:
            return f"{k} 상대차 {_diff_pct(av, bv) * 100:.0f}% (>{gross_pct * 100:.0f}%)"
    return None


def verified_latest(market="KOSPI", today=None, now=None):
    """오늘자 검증 통과 수급 → dict, 아니면 None.

    반환: {date, foreign, inst, retail, primary, cross, agree, maxDiffPct, confirmed, reason}
    - 값은 **네이버(포털·언론 기준)**. 토스는 교차검증용.
    - 오늘 날짜 행이 없으면 None(= 묵은 값 금지).
    - 토스 키가 없어 교차검증이 불가하면 agree=None 으로 통과시킨다(네이버 단독값은
      사용자가 대조하는 그 값이라 '틀린 값'이 아니다).
    """
    now = now or datetime.datetime.now(KST)
    today = today or now.strftime("%Y-%m-%d")
    try:
        nrows = naver_daily(market, bizdate=today.replace("-", ""))
    except Exception as e:                                   # noqa: BLE001
        log(f"네이버 조회 실패: {e}")
        return None
    nav = next((r for r in reversed(nrows) if r["date"] == today), None)
    if not nav:
        log(f"네이버에 {today} 행 없음 — 수급 표기 생략")
        return None
    trows = toss_daily(market)
    tos = next((r for r in reversed(trows) if r["date"] == today), None)
    out = {"date": today, "primary": "naver", "cross": "toss" if tos else None,
           "agree": None, "maxDiffPct": None, "confirmed": False, "reason": ""}
    out.update({k: nav[k] for k in _KEYS})
    if tos:
        bad = gross_mismatch(nav, tos)
        if bad:
            log(f"교차검증 실패({bad}) — 수급 표기 생략")
            return None
        ok, worst = agree(nav, tos)
        out["agree"], out["maxDiffPct"] = ok, round(worst * 100, 1)
        upd = str(tos.get("updatedAt") or "")
        m = re.match(r"^\d{4}-\d\d-\d\dT(\d\d):", upd)
        out["confirmed"] = bool(m) and int(m.group(1)) >= 18
    else:
        out["confirmed"] = now.hour >= 19
    out["reason"] = ("확정" if out["confirmed"] else "잠정")
    log(f"{market} {today} 외국인 {out['foreign']:+,.0f} 기관 {out['inst']:+,.0f} "
        f"개인 {out['retail']:+,.0f}억 ({out['reason']}, 일치={out['agree']}, "
        f"최대차={out['maxDiffPct']}%)")
    return out


def week_sum(market="KOSPI", days=5):
    """최근 `days` 영업일 외국인·기관 순매수 합 → {from, to, days, foreign, inst} / 실패 시 None.

    주간 카드용. 일별 표시와 **같은 소스(네이버)** 를 쓴다 — 종전엔 주간 합계는 토스
    시계열, 일별 타일은 다른 값이라 같은 카드 안에서 기준이 갈렸다.
    """
    try:
        rows = naver_daily(market)[-days:]
    except Exception as e:                                   # noqa: BLE001
        log(f"주간 합계 조회 실패: {e}")
        return None
    if len(rows) < days:
        return None
    return {"from": rows[0]["date"], "to": rows[-1]["date"], "days": len(rows),
            "foreign": sum(r["foreign"] for r in rows),
            "inst": sum(r["inst"] for r in rows)}


def asof_label(inv, lang_ko=True):
    """카드 타일용 as-of 라벨 — '09-11 확정' / '09-11 잠정'."""
    if not inv:
        return ""
    d = str(inv.get("date") or "")[5:]
    tail = inv.get("reason") or ""
    if not lang_ko:
        tail = {"확정": "final", "잠정": "provisional"}.get(tail, tail)
    return f"{d} {tail}".strip()


if __name__ == "__main__":                                   # 수동 점검
    import sys
    sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else ".")
    for mkt in ("KOSPI", "KOSDAQ"):
        n = {r["date"]: r for r in naver_daily(mkt)}
        t = {r["date"]: r for r in toss_daily(mkt)}
        print(f"== {mkt}")
        for d in sorted(set(n) & set(t), reverse=True)[:5]:
            ok, worst = agree(n[d], t[d])
            print(f"  {d} 네이버 외인{n[d]['foreign']:+9,.0f} 토스{t[d]['foreign']:+9,.0f} "
                  f"| 일치={ok} 최대차={worst * 100:.1f}% | gross={gross_mismatch(n[d], t[d])}")
        print(f"  verified_latest → {verified_latest(mkt)}")
