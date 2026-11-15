#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""읽는 값 — 거시 지표의 지수 · 금액 원값을 사람이 읽는 값(전년비 · 전월비 · 전기비 · 증감 …)으로 바꿔
data.json 지표 잎에 `read` 칸을 단다(기획서 3qh6Z7rw 「거시 지표 읽기 개편」).

왜: 화면이 미국 PCE 를 「132.3 · 전월 131.6 · 전년 127.6」(지수끼리)으로 보여 「몇 % 올랐나」를 사람이 나눠야 했고,
같은 미국 CPI 가 일정표 +0.3% · 카드 337.5 · 상세 ▲0.35% 로 화면마다 달랐다. 이제 읽는 법은 이 파일의 RULES 한 곳에서
정하고, 카드 · 띠 · 상세 · 일정 · 카톡 · 알림은 read 만 읽는다(다시 계산하지 않는다).

원칙
  · 공식값 먼저 — economicCalendar.officialHistory(나스닥 경제 일정 발표값, scripts/consensus.py OFFICIAL_MAP)에 그 기간
    값이 있으면 그것. 없으면 원값 이력으로 계산하고 src="calc" 로 표시한다.
  · 반올림은 한 번 — 계산은 반올림 없이 하고 마지막에 표기 자리수로 한 번만 반올림(ROUND_HALF_UP). 일정 칸이 0.649 →
    0.65 → 0.7 로 두 번 반올림해 공식 0.6% 와 어긋났다.
  · 1년 전은 날짜로 찾는다 — 이력 칸 순서로 12칸 전을 세면 빠진 달(2025-10 미국 CPI, 셧다운)이 있을 때 13개월 전과 비교한다.
  · 큰 숫자 = 컨센서스와 견주는 값(결정 D1) — 미국 물가 = 전월비, 한국 · 유럽 물가 = 전년비, 컨센서스가 없으면 발표
    기관이 앞세우는 값. 다른 기준은 subs(둘째 줄).
  · 빈칸엔 사유 — 「1년 전 값 미발표」 처럼 why 를 단다.

read 모양
  {"name": 화면 이름(없으면 레지스트리 이름), "ref": "2026-10" | "2026-Q3" | "2026-11-14", "freq": "M"|"Q"|"D",
   "released": "2026-11-10"(KST 발표일, 공식값일 때),
   "main": {"b": "mom", "word": "전월 대비", "short": "전월비", "value": 0.4, "unit": "%", "dec": 1, "sign": true,
            "src": "official"|"calc", "lo": 3.75(범위 하단, range 만)},
   "subs": [{… main 과 같은 모양, "ref": 기간이 다를 때만, "why": 값이 없을 때 사유}],
   "prev": 지난 값(main 기준), "cons": 컨센서스, "diff": 발표 − 컨센서스, "size": None|"큼"|"매우 큼",
   "series": [[기간, 값], …](main 기준 최근 24기간, 공식값이 있는 기간은 공식값), "rel": [[기간, 발표, 컨센서스], …](최근 12회),
   "calc": 대조용 계산값(공식값을 쓴 기간)}
"""
import datetime as dt
import re
from decimal import Decimal, ROUND_HALF_UP

# 기준 → (카드 문구, 띠 · 표 짧은 문구)
WORD = {
    "yoy": ("전년 같은 달 대비", "전년비"), "mom": ("전월 대비", "전월비"), "qoq": ("전기 대비", "전기비"),
    "saar": ("전기 대비 연율", "연율"), "dyoy": ("전년 같은 달 대비", "전년비"), "dmom": ("전월 대비", "전월비"),
    "dqoq": ("전분기 대비", "전분기비"), "level": ("", ""), "range": ("목표 범위", "목표"),
}
WORD_Q = {"yoy": ("전년 같은 분기 대비", "전년비"), "dyoy": ("전년 같은 분기 대비", "전년비")}
SIGNED = {"yoy", "mom", "qoq", "saar", "dyoy", "dmom", "dqoq"}
STEP = {"yoy": 12, "dyoy": 12, "mom": 1, "dmom": 1, "qoq": 1, "saar": 1, "dqoq": 1}
ASIA = {"South Korea", "Japan", "China"}      # 아시아 발표는 조회일 = 한국 날짜(미국 동부 전날 저녁), 그 밖은 조회일 − 1


def B(b, off=None, calc=True, asis=False, unit="%", scale=1.0, oscale=1.0, dec=1, freq=None, label=None):
    """기준 하나. off = 공식값 열쇠(consensus.OFFICIAL_MAP) · calc = 원값 이력으로 계산할지 · asis = 잎 값이 이미 그 기준(예:
    영국 CPI 는 전년비 % 로 온다) · scale/oscale = 계산값/공식값 배율(천 명 → 만 명 0.1 · 십억 달러 → 억 달러 10) ·
    label = 기준 말 대신 쓸 이름(수준 값의 「금액」 · 「잔액」 · 「콜금리」)."""
    return {"b": b, "off": off, "calc": calc, "asis": asis, "unit": unit, "scale": scale, "oscale": oscale, "dec": dec,
            "freq": freq, "label": label}


def R(freq, main, subs=(), name=None, lag=1):
    """지표 하나. freq = 원값 이력 주기(M 월 · Q 분기 · D 일) · lag = 월간 공식값의 기준 달 = 조회일 달 − lag."""
    return {"freq": freq, "main": main, "subs": list(subs), "name": name, "lag": lag}


EI = "economicIndicators."
RULES = {
    # 물가 — 미국 = 전월비 · 한국 · 유럽 = 전년비(D1)
    EI + "kr.cpi_kr": R("M", B("yoy", "kr_cpi_yoy"), [B("mom", "kr_cpi_mom")], "소비자물가"),
    EI + "kr.ppi_kr": R("M", B("yoy", "kr_ppi_yoy"), [B("mom", "kr_ppi_mom")], "생산자물가"),
    EI + "us.cpi_us": R("M", B("mom", "us_cpi_mom"), [B("yoy", "us_cpi_yoy")], "소비자물가"),
    EI + "us.core_cpi_us": R("M", B("mom", "us_core_cpi_mom"), [B("yoy", "us_core_cpi_yoy")], "근원 소비자물가"),
    EI + "us.pce_us": R("M", B("mom", "us_pce_mom"), [B("yoy", "us_pce_yoy")], "PCE 물가"),
    EI + "us.core_pce_us": R("M", B("mom", "us_core_pce_mom"), [B("yoy", "us_core_pce_yoy")], "근원 PCE 물가"),
    EI + "us.ppi_us": R("M", B("mom", "us_ppi_mom"), [B("yoy", "us_ppi_yoy")], "생산자물가"),
    EI + "eu.cpi_eu": R("M", B("yoy", "eu_cpi_yoy"), [B("mom", "eu_cpi_mom")], "소비자물가(HICP)"),
    EI + "de.cpi_de": R("M", B("yoy", "de_hicp_yoy"), [B("mom", "de_hicp_mom")], "소비자물가(HICP)"),
    EI + "uk.cpi_uk": R("M", B("yoy", "uk_cpi_yoy", asis=True), [B("mom", "uk_cpi_mom", calc=False)], "소비자물가"),
    EI + "jp.cpi_jp": R("M", B("yoy", "jp_cpi_yoy", asis=True), [B("mom", "jp_cpi_mom", calc=False)], "소비자물가"),
    EI + "cn.cpi_cn": R("M", B("yoy", "cn_cpi_yoy", asis=True), [B("mom", "cn_cpi_mom", calc=False)], "소비자물가"),
    # 경기 — 월간 = 전월비, 분기 GDP = 전기비(미국 · 일본 = 연율)
    EI + "us.ip_us": R("M", B("mom", "us_ip_mom"), [B("yoy", "us_ip_yoy")], "산업생산"),
    EI + "us.retail_us": R("M", B("mom", "us_retail_mom"), [B("yoy", "us_retail_yoy")], "소매판매"),
    # ip_kr 원값은 광공업이 아니라 전산업 지수(ECOS 901Y033 A00)가 잡혀 계산하면 공식 광공업생산과 다르다 → 공식값만
    EI + "kr.ip_kr": R("M", B("mom", "kr_ip_mom", calc=False), [B("yoy", "kr_ip_yoy", calc=False)], "광공업생산"),
    EI + "kr.ip_all_kr": R("M", B("mom"), [B("yoy")], "전산업생산"),
    EI + "kr.retail_kr": R("M", B("mom", "kr_retail_mom"), [B("yoy")], "소매판매"),
    EI + "kr.gdp_kr": R("Q", B("qoq", "kr_gdp_qoq", asis=True), [B("yoy", "kr_gdp_yoy", calc=False)], "GDP 성장률"),
    EI + "us.gdp_growth_us": R("Q", B("saar", "us_gdp", asis=True), [], "GDP 성장률"),
    EI + "eu.gdp_eu": R("Q", B("qoq", "eu_gdp_qoq"), [B("yoy", "eu_gdp_yoy")], "GDP"),
    EI + "de.gdp_de": R("Q", B("qoq", "de_gdp_qoq"), [B("yoy", "de_gdp_yoy")], "GDP"),
    EI + "uk.gdp_uk": R("Q", B("qoq"), [B("yoy")], "GDP"),
    EI + "jp.gdp_jp": R("Q", B("saar"), [B("qoq"), B("yoy")], "GDP"),
    EI + "cn.gdp_yoy_cn": R("Q", B("yoy", "cn_gdp_yoy", asis=True), [B("qoq", "cn_gdp_qoq", calc=False)], "GDP 성장률"),
    # 고용 — 인원은 증감(천 명 → 만 명)
    EI + "us.nfp_us": R("M", B("dmom", "us_nfp", unit="만 명", scale=0.1, oscale=0.1), [], "비농업고용"),
    EI + "kr.employed_kr": R("M", B("dyoy", unit="만 명", scale=0.1), [], "취업자"),
    EI + "us.unemployment": R("M", B("level", "us_unemp", asis=True), [], "실업률"),
    EI + "eu.unemployment_eu": R("M", B("level", "eu_unemp", asis=True), [], "실업률"),
    EI + "uk.unemployment_uk": R("M", B("level", "uk_unemp", asis=True), [], "실업률"),
    EI + "jp.unemployment_jp": R("M", B("level", "jp_unemp", asis=True), [], "실업률"),
    # 금리 · 통화
    EI + "us.ff_target": R("D", B("range", "us_fed", asis=True, dec=2), [], "기준금리"),
    EI + "us.ff_rate": R("M", B("level", asis=True, dec=2), [], "실효 연방기금금리(월평균)"),
    EI + "jp.base_rate_jp": R("M", B("level", "jp_boj", calc=False, dec=2, freq="D"),
                               [B("level", asis=True, dec=3, label="콜금리(월평균)")], "정책금리"),
    EI + "us.m2_us": R("M", B("yoy"), [B("level", asis=True, unit="조 달러", scale=0.001, label="잔액")], "M2 통화량"),
    EI + "kr.household_debt_kr": R("Q", B("dqoq", unit="조 원", scale=0.001), [B("yoy")], "가계신용"),
    # 무역 — 한국 수출은 공식 전년비가 통관 금액보다 한 달 빠르다(산업부 1일 발표)
    EI + "kr.exports_kr": R("M", B("yoy", "kr_exports_yoy"), [B("level", asis=True, unit="억 달러", scale=1e-8, label="금액")], "수출"),
    EI + "kr.exports_idx_kr": R("M", B("yoy"), [], "수출금액지수"),
    EI + "kr.current_account_kr": R("M", B("level", "kr_ca", asis=True, unit="억 달러", scale=0.01, oscale=10),
                                    [B("dmom", unit="억 달러", scale=0.01)], "경상수지", lag=2),
    # 부동산 — 케이스-실러는 전년비(한국 아파트 지수는 지수 자체를 읽으므로 그대로 둔다 — 2026-11-15 결정)
    "realestate.us.case_shiller_national": R("M", B("yoy"), [B("mom")], "케이스-실러 주택가격(전국)"),
    "realestate.us.case_shiller_20city": R("M", B("yoy"), [B("mom")], "케이스-실러 주택가격(20대 도시)"),
}

TOL = 0.15          # 공식값 ↔ 계산값 대조 허용 폭(%p) — 넘으면 diagnostics.readValues.mismatch


def rnd(x, dec):
    """표기 자리수로 한 번만 반올림(사사오입). 0.35 → 0.4 (부동소수 0.34999… 로 내려가지 않게 문자열로)."""
    if x is None:
        return None
    q = Decimal(1).scaleb(-dec)
    return float(Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP)) + 0.0


def _num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


# ── 기간 ─────────────────────────────────────────────────────────────────
def ref_of_key(k, freq):
    """이력 열쇠(2026-10-01 · 202610 · 2026-10 · 2026Q3 · 2026-11-14) → 기간(2026-10 · 2026-Q3 · 2026-11-14)."""
    k = str(k)
    if freq == "D":
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", k)
        return "%s-%s-%s" % m.groups() if m else None
    q = re.match(r"^(\d{4})-?Q([1-4])$", k)
    m = re.match(r"^(\d{4})-?(\d{2})(?:-\d{2})?$", k)
    if freq == "Q":
        if q:
            return "%s-Q%s" % q.groups()
        return "%s-Q%d" % (m.group(1), (int(m.group(2)) - 1) // 3 + 1) if m else None
    if m:
        return "%s-%s" % m.groups()
    return None


def shift(ref, freq, n):
    """기간을 n 칸 옮긴다(M 달 · Q 분기). 음수 = 과거."""
    if freq == "Q":
        y, q = int(ref[:4]), int(ref[-1])
        i = y * 4 + (q - 1) + n
        return "%d-Q%d" % (i // 4, i % 4 + 1)
    y, m = int(ref[:4]), int(ref[5:7])
    i = y * 12 + (m - 1) + n
    return "%d-%02d" % (i // 12, i % 12 + 1)


# 같은 달 말에 그 달 속보가 나오는 지표(유로 · 독일 물가 속보 — 25일 이후 발표면 그 달 값)
SAME_MONTH_LATE = {"eu_cpi_yoy", "eu_cpi_mom", "de_hicp_yoy", "de_hicp_mom"}
# 한 달 전체 값만 받는 날(한국 수출 = 매월 1일 산업부 발표) — 중순의 열흘 · 스무날 잠정치가 지난달 값을 덮지 않게
DAY_WINDOW = {"kr_exports_yoy": (1, 3)}


def ref_of_release(q, freq, lag, country="", key=None):
    """공식값 조회일 → 기준 기간. 날짜는 한국 날짜 발표일(released_of)로 센다 — 조회일(미국 동부 발표일 + 1)로 세면
    9/30 밤 미국 PCE(8월분)가 10/1 조회라 9월분이 됐다(2026-11-15 검토). 월간 = 발표 달 − lag(같은 달 속보는 그 달) ·
    분기 = 발표 10일 전까지 끝난 마지막 분기 · 일간 = 발표일. DAY_WINDOW 밖 날이면 None(받지 않는다)."""
    d = dt.date.fromisoformat(released_of(q, country))
    if key in DAY_WINDOW and not DAY_WINDOW[key][0] <= d.day <= DAY_WINDOW[key][1]:
        return None
    if freq == "D":
        return d.isoformat()
    if freq == "Q":
        e = d - dt.timedelta(days=10)
        return shift("%d-Q%d" % (e.year, (e.month - 1) // 3 + 1), "Q", -1)
    if key in SAME_MONTH_LATE and d.day >= 25:
        return "%d-%02d" % (d.year, d.month)
    return shift("%d-%02d" % (d.year, d.month), "M", -lag)


def released_of(q, country):
    """조회일 → 한국 날짜 발표일. 미국 동부 오전 발표(미국 · 유럽)는 한국 같은 날 밤 = 조회일 − 1."""
    d = dt.date.fromisoformat(str(q)[:10])
    return (d if country in ASIA else d - dt.timedelta(days=1)).isoformat()


# ── 계산 ─────────────────────────────────────────────────────────────────
def norm_history(leaf, freq):
    """잎 이력 → {기간: 값}. 잎의 현재 값(period · value)도 넣는다."""
    out = {}
    for k, v in ((leaf or {}).get("history") or {}).items():
        r, f = ref_of_key(k, freq), _num(v)
        if r and f is not None:
            out[r] = f
    r, f = ref_of_key(leaf.get("period"), freq) if leaf.get("period") else None, _num(leaf.get("value"))
    if r and f is not None:
        out[r] = f
    return out


def calc_series(hist, b, freq):
    """기준 하나의 계산 시계열 {기간: 반올림 전 값} — 비교 기간은 날짜로 찾는다(칸 순서가 아니라)."""
    kind, out = b["b"], {}
    for r, v in hist.items():
        if b["asis"] or kind == "level" or kind == "range":
            out[r] = v * b["scale"]
            continue
        if freq == "D":
            continue
        step = STEP[kind] // (3 if (freq == "Q" and kind in ("yoy", "dyoy")) else 1)
        p = hist.get(shift(r, freq, -step))
        if p is None:
            continue
        if kind in ("dyoy", "dmom", "dqoq"):
            out[r] = (v - p) * b["scale"]
        elif p == 0:
            continue
        elif kind == "saar":
            out[r] = ((v / p) ** 4 - 1) * 100
        else:
            out[r] = (v / p - 1) * 100
    return out


def official_series(entries, b, freq, lag, country="", key=None):
    """공식값 기록 → {기간: {"a", "c", "p", "q"}} (같은 기간은 늦은 조회일이 이긴다 — 수정 · 확정치)."""
    out = {}
    for x in entries or []:
        a = _num(x.get("a"))
        if a is None or not x.get("q"):
            continue
        r = ref_of_release(x["q"], freq, lag, country, key)
        if r is None:
            continue
        if r not in out or x["q"] > out[r]["q"]:
            sc = b["oscale"]
            out[r] = {"a": a * sc, "c": None if _num(x.get("c")) is None else _num(x["c"]) * sc,
                      "p": None if _num(x.get("p")) is None else _num(x["p"]) * sc, "q": x["q"]}
    return out


def _words(b, freq):
    if b.get("label"):
        return {"word": b["label"], "short": b["label"]}
    w = (WORD_Q if freq == "Q" else {}).get(b["b"]) or WORD[b["b"]]
    return {"word": w[0], "short": w[1]}


def _cell(b, freq, value, src):
    out = {"b": b["b"], **_words(b, freq), "value": rnd(value, b["dec"]), "unit": b["unit"], "dec": b["dec"],
           "sign": b["b"] in SIGNED, "src": src}
    if b["b"] == "range" and value is not None:
        out["lo"] = rnd(value - 0.25, b["dec"])          # 연준 목표 범위 폭 0.25%p(2008-12 이후)
    return out


def _size(diff, st):
    """발표 − 컨센서스 크기 — 평소 어긋나는 폭(meanAbs)의 1.5배 = 큼 · 2.5배 = 매우 큼. 기록 6회 미만이면 말하지 않는다."""
    if diff is None or not st or (st.get("n") or 0) < 6:
        return None
    m = st.get("meanAbs") or 0
    if m <= 0:
        return "매우 큼" if abs(diff) > 1e-9 else None
    r = abs(diff) / m
    return "매우 큼" if r >= 2.5 else "큼" if r >= 1.5 else None


def _why(hist, b, freq, ref):
    """값이 없는 이유. 1년 전 기간이 이력 가운데 빠져 있으면 「1년 전 값 미발표」(2025-10 미국 셧다운)."""
    if b["b"] in ("yoy", "dyoy") and hist:
        ago = shift(ref, freq, -(4 if freq == "Q" else 12))
        lo = min(hist)
        if ago not in hist and lo < ago:
            return "1년 전 값 미발표"
        return "1년 전 값 없음"
    return "발표 전"


def build_read(leaf, rule, off_hist, stats):
    """잎 하나의 read. 쓸 값이 하나도 없으면 None."""
    freq, lag = rule["freq"], rule["lag"]
    hist = norm_history(leaf, freq)
    from consensus import OFFICIAL_MAP          # 지연 import — 시험이 consensus 없이도 RULES 를 읽게

    def series_of(b):
        f = b["freq"] or freq
        h = hist if f == freq else norm_history(leaf, f)
        calc = calc_series(h, b, f) if b["calc"] else {}
        off = (official_series((off_hist or {}).get(b["off"]), b, f, lag, OFFICIAL_MAP.get(b["off"], ("",))[0], b["off"])
               if b["off"] else {})
        return f, calc, off

    m = rule["main"]
    mf, mcalc, moff = series_of(m)
    refs = set(mcalc) | set(moff)
    if not refs:
        return None
    ref = max(refs)
    o = moff.get(ref)
    if o is None and mf == "D" and moff:
        # 일간(정책금리): 결정일은 지난 날이고 이력은 오늘까지 이어진다 — 마지막 결정이 지금 수준과 같으면 그 발표값으로 본다
        last = max(r for r in moff if r <= ref) if any(r <= ref for r in moff) else None
        if last and (ref not in mcalc or abs(moff[last]["a"] - mcalc[ref]) < 1e-9):
            o = moff[last]
    value = o["a"] if o else mcalc.get(ref)
    src = "official" if o else "calc"
    country = OFFICIAL_MAP.get(m["off"], ("",))[0] if m["off"] else ""
    read = {"name": rule["name"], "ref": ref, "freq": mf, "main": _cell(m, mf, value, src)}
    if o:
        read["released"] = released_of(o["q"], country)
        if ref in mcalc:
            read["calc"] = round(mcalc[ref], 3)
    # 지난 값 — 공식 발표 줄의 직전 값(수정 반영) 먼저
    pref = shift(ref, mf, -1) if mf in ("M", "Q") else None
    prev = o["p"] if (o and o.get("p") is not None) else None
    if prev is None and pref:
        po = moff.get(pref)
        prev = po["a"] if po else mcalc.get(pref)
    if mf == "D" and prev is not None and rnd(prev, m["dec"]) == read["main"]["value"]:
        prev = None          # 결정에서 안 바뀐 금리 — 「직전」은 마지막으로 달랐던 값(같은 숫자를 두 번 적지 않는다)
    if prev is None and mf == "D":
        older = sorted(r for r in set(mcalc) | set(moff) if r < ref)
        for r in reversed(older):
            pv = moff[r]["a"] if r in moff else mcalc.get(r)
            if pv is not None and rnd(pv, m["dec"]) != read["main"]["value"]:
                prev = pv
                break
    read["prev"] = rnd(prev, m["dec"])
    if o and o.get("c") is not None:
        read["cons"] = rnd(o["c"], m["dec"])
        read["diff"] = rnd(o["a"] - o["c"], m["dec"])
        read["size"] = _size((o["a"] - o["c"]) / (m["oscale"] or 1), (stats or {}).get(m["off"]))
    subs = []
    for b in rule["subs"]:
        bf, bcalc, boff = series_of(b)
        bo = boff.get(ref) if bf == mf else None
        if bo:
            subs.append(_cell(b, bf, bo["a"], "official"))
        elif bf == mf and ref in bcalc:
            subs.append(_cell(b, bf, bcalc[ref], "calc"))
        elif b["b"] == "level" and (bcalc or boff):
            r2 = max(set(bcalc) | set(boff))
            c = _cell(b, bf, boff[r2]["a"] if r2 in boff else bcalc[r2], "official" if r2 in boff else "calc")
            c["ref"] = r2
            subs.append(c)
        else:
            c = _cell(b, bf, None, "none")
            c["why"] = _why(hist, b, bf, ref) if bf == mf else "발표 전"
            subs.append(c)
    read["subs"] = subs
    if mf in ("M", "Q"):
        pts = {r: mcalc[r] for r in mcalc}
        pts.update({r: x["a"] for r, x in moff.items()})
        read["series"] = [[r, rnd(pts[r], m["dec"])] for r in sorted(pts)[-24:]]
        read["rel"] = [[r, rnd(moff[r]["a"], m["dec"]), rnd(moff[r]["c"], m["dec"])] for r in sorted(moff)[-12:]]
    return read


def _get(data, path):
    node = data
    for p in path.split("."):
        node = node.get(p) if isinstance(node, dict) else None
    return node


def attach(data):
    """data.json 의 RULES 잎마다 read 를 단다(못 만들면 지운다). 반환 = 진단(diagnostics.readValues)."""
    cal = data.get("economicCalendar") or {}
    off = (cal.get("officialHistory") or {})
    off_hist, stats = off.get("series") or {}, off.get("stats") or {}
    st = {"filled": 0, "official": 0, "missing": [], "mismatch": [], "extreme": []}
    for path, rule in RULES.items():
        leaf = _get(data, path)
        if not isinstance(leaf, dict):
            continue
        try:
            rd = build_read(leaf, rule, off_hist, stats)
        except Exception as e:                      # 한 지표 실패가 수집 전체를 멈추지 않게
            st["missing"].append("%s: %s" % (path, str(e)[:80]))
            rd = None
        if not rd:
            leaf.pop("read", None)
            continue
        leaf["read"] = rd
        st["filled"] += 1
        if rd["main"]["src"] == "official":
            st["official"] += 1
            c = rd.get("calc")
            if c is not None and rd["main"]["unit"] == "%" and abs(c - rd["main"]["value"]) > TOL:
                st["mismatch"].append({"path": path, "ref": rd["ref"], "official": rd["main"]["value"], "calc": c})
        elif rd["main"]["sign"] and rd["main"]["unit"] == "%" and abs(rd["main"]["value"] or 0) > 50:
            st["extreme"].append({"path": path, "ref": rd["ref"], "calc": rd["main"]["value"]})   # 원천 이력 확인 필요
    return st


if __name__ == "__main__":       # 수집 자료로 한 번 돌려 본다: python scripts/read_values.py [data.json]
    import json
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    d = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "data.json", encoding="utf-8"))
    print(json.dumps(attach(d), ensure_ascii=False, indent=1))
    for path in RULES:
        rd = (_get(d, path) or {}).get("read")
        if rd:
            subs = " · ".join("%s %s" % (s["short"], s["value"]) for s in rd["subs"])
            print("%-40s %-8s %s %s %s(%s) 지난 %s 컨센 %s %s" % (path, rd["ref"], rd["main"]["short"], rd["main"]["value"],
                                                          rd["main"]["unit"], rd["main"]["src"], rd.get("prev"), rd.get("cons"), subs))
