#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""종목 펀더멘털 수집 → fundamentals.json (2026-08-11 재구성 기획안 P2)

대상: alerts_config.json 의 tracking.items (공개 관심목록 — 보유량 정보 없음).
  - KR: OpenDART (OPENDART_API_KEY 시크릿 필요, 없으면 KR 은 건너뜀)
        corpCode zip → 종목코드 매핑, 주요계정(fnlttSinglAcnt)·발행주식(stockTotqySttus)·
        배당(alotMatter) 에서 EPS/BPS/ROE/영업이익률/부채비율/DPS 산출.
        PER/PBR 은 저장하지 않는다 — 프론트가 현재가/EPS·BPS 로 일일 재계산(신선도).
  - US: yfinance Ticker.info 최소 세트 + 다음 실적 발표일.

원칙 (fetch_data.py 와 동일):
  - 키 없음/개별 실패 = 해당 항목 skip, 이전 fundamentals.json 항목 보존 (날조 금지).
  - 어떤 경우에도 exit 0 (파이프라인 비차단 — 워크플로 continue-on-error 와 이중 안전).
  - data.json 에 넣지 않고 별도 파일 — validate 게이트·파일 비대 영향 차단.

실행 주기: fetch-data.yml 일일 풀런(AV_FETCH_FULL=1)에서만.
"""
import io
import json
import os
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

import requests

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(ROOT, "fundamentals.json")
CFG_PATH = os.path.join(ROOT, "alerts_config.json")
DART_KEY = os.environ.get("OPENDART_API_KEY", "").strip()
DART = "https://opendart.fss.or.kr/api"


def log(msg):
    print(msg, flush=True)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_symbols():
    """공개 관심목록에서 (KR 코드 목록, US {symbol: yahoo}) 추출."""
    cfg = load_json(CFG_PATH) or {}
    items = ((cfg.get("tracking") or {}).get("items")) or []
    kr, us = [], {}
    for it in items:
        sym = str(it.get("symbol") or "").strip()
        mkt = it.get("market")
        if mkt == "KR" and len(sym) == 6 and sym.isdigit():
            kr.append({"code": sym, "name": it.get("name") or sym})
        elif mkt == "US" and sym:
            us[sym.upper()] = (it.get("yahoo") or sym).upper()
    return kr, us


# ── OpenDART (KR) ─────────────────────────────────────────
def dart_get(endpoint, **params):
    params["crtfc_key"] = DART_KEY
    r = requests.get(f"{DART}/{endpoint}", params=params, timeout=20)
    r.raise_for_status()
    j = r.json()
    if j.get("status") not in ("000", "013"):  # 013 = 조회 데이터 없음
        raise RuntimeError(f"DART {endpoint} status={j.get('status')} {j.get('message')}")
    return j


def build_corp_map(needed_codes, prev_map):
    """stock_code → corp_code. 이전 맵이 필요 코드를 전부 커버하면 zip 재다운 생략."""
    prev_map = prev_map or {}
    if all(c in prev_map for c in needed_codes):
        return prev_map
    r = requests.get(f"{DART}/corpCode.xml", params={"crtfc_key": DART_KEY}, timeout=60)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    xml = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml)
    want = set(needed_codes)
    out = dict(prev_map)
    for el in root.iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        if sc in want:
            out[sc] = (el.findtext("corp_code") or "").strip()
    return out


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (ValueError, TypeError):
        return None


def fetch_kr_one(corp_code, code, name, year):
    """주요계정 + 발행주식 + 배당 → 파생 지표. 최신 확정 사업보고서(11011)부터 역순 탐색."""
    fin = None
    used_year, used_reprt = None, None
    for y, reprt in [(year, "11011"), (year - 1, "11011")]:
        try:
            j = dart_get("fnlttSinglAcnt.json", corp_code=corp_code, bsns_year=str(y), reprt_code=reprt)
            rows = j.get("list") or []
            if rows:
                fin = rows
                used_year, used_reprt = y, reprt
                break
        except Exception:
            continue
        finally:
            time.sleep(0.15)
    if not fin:
        return None
    # CFS(연결) 우선, 없으면 OFS(별도)
    acc = {}
    for pref in ("CFS", "OFS"):
        for row in fin:
            if row.get("fs_div") != pref:
                continue
            nm = (row.get("account_nm") or "").strip()
            v = _num(row.get("thstrm_amount"))
            if v is not None and nm not in acc:
                acc[nm] = v
        if acc:
            break
    revenue = acc.get("매출액")
    op = acc.get("영업이익")
    net = acc.get("당기순이익")
    equity = acc.get("자본총계")
    debt = acc.get("부채총계")

    shares = None
    try:
        j = dart_get("stockTotqySttus.json", corp_code=corp_code, bsns_year=str(used_year), reprt_code=used_reprt)
        for row in (j.get("list") or []):
            if "보통주" in (row.get("se") or ""):
                shares = _num(row.get("distb_stock_co")) or _num(row.get("istc_totqy"))
                break
        time.sleep(0.15)
    except Exception:
        pass

    dps = None
    try:
        j = dart_get("alotMatter.json", corp_code=corp_code, bsns_year=str(used_year), reprt_code=used_reprt)
        for row in (j.get("list") or []):
            se = (row.get("se") or "")
            if "주당 현금배당금" in se:
                dps = _num(row.get("thstrm"))
                if dps:
                    break
        time.sleep(0.15)
    except Exception:
        pass

    out = {
        "name": name, "year": used_year, "reprt": used_reprt,
        "revenue": revenue, "opIncome": op, "netIncome": net,
        "equity": equity, "debt": debt, "shares": shares, "dps": dps,
    }
    if net is not None and shares:
        out["eps"] = round(net / shares, 2)
    if equity is not None and shares:
        out["bps"] = round(equity / shares, 2)
    if net is not None and equity:
        out["roe"] = round(net / equity * 100, 1)
    if op is not None and revenue:
        out["opMargin"] = round(op / revenue * 100, 1)
    if debt is not None and equity:
        out["debtRatio"] = round(debt / equity * 100, 1)
    return out


# ── yfinance (US) ─────────────────────────────────────────
def fetch_us_one(yahoo_sym):
    import yfinance as yf
    t = yf.Ticker(yahoo_sym)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    out = {}
    for src, dst in [("trailingPE", "per"), ("trailingEps", "eps"), ("priceToBook", "pbr"),
                     ("bookValue", "bps"), ("returnOnEquity", "roe"), ("dividendYield", "divYield"),
                     ("operatingMargins", "opMargin"), ("marketCap", "marketCap")]:
        v = info.get(src)
        if isinstance(v, (int, float)):
            out[dst] = v
    # 비율 정규화: yfinance 는 roe/margin 을 0~1 소수로 주는 경우가 있음
    for k in ("roe", "opMargin"):
        if k in out and abs(out[k]) <= 1.5:
            out[k] = round(out[k] * 100, 1)
    if "divYield" in out and out["divYield"] <= 1.0:  # 0.0042 식 소수 → %
        out["divYield"] = round(out["divYield"] * 100, 2)
    try:
        cal = t.calendar
        ed = None
        if isinstance(cal, dict):
            v = cal.get("Earnings Date")
            if isinstance(v, (list, tuple)) and v:
                ed = v[0]
            else:
                ed = v
        if ed is not None:
            out["earningsDate"] = str(ed)[:10]
    except Exception:
        pass
    return out or None


def main():
    prev = load_json(OUT_PATH) or {}
    kr_items, us_items = load_symbols()
    log(f"[FUNDA] 대상: KR {len(kr_items)}종목, US {len(us_items)}종목")
    out = {
        "asOf": datetime.now(KST).isoformat(timespec="seconds"),
        "kr": dict(prev.get("kr") or {}),
        "us": dict(prev.get("us") or {}),
        "corpMap": dict(prev.get("corpMap") or {}),
        "sources": {"kr": "OpenDART (사업보고서 주요계정)", "us": "yfinance Ticker.info"},
    }
    year = datetime.now(KST).year

    if kr_items and not DART_KEY:
        log("[FUNDA] OPENDART_API_KEY 미설정 — KR 펀더멘털 건너뜀 (키 등록 시 자동 활성)")
    elif kr_items:
        try:
            out["corpMap"] = build_corp_map([k["code"] for k in kr_items], out["corpMap"])
            log(f"[FUNDA] corpMap {len(out['corpMap'])}건")
        except Exception as e:
            log(f"[FUNDA] corpMap 실패: {e}")
        for k in kr_items:
            cc = out["corpMap"].get(k["code"])
            if not cc:
                log(f"[FUNDA] KR {k['code']} corp_code 미매핑(ETF 등) — skip")
                continue
            try:
                row = fetch_kr_one(cc, k["code"], k["name"], year)
                if row:
                    row["fetchedAt"] = datetime.now(KST).strftime("%Y-%m-%d")
                    out["kr"][k["code"]] = row
                    log(f"[FUNDA] KR {k['code']} {k['name']}: {row.get('year')}년 EPS={row.get('eps')} ROE={row.get('roe')}%")
                else:
                    log(f"[FUNDA] KR {k['code']} 보고서 없음 — 기존 값 보존")
            except Exception as e:
                log(f"[FUNDA] KR {k['code']} 오류(보존): {e}")

    if us_items:
        try:
            import yfinance  # noqa: F401
            for sym, ysym in us_items.items():
                try:
                    row = fetch_us_one(ysym)
                    if row:
                        row["fetchedAt"] = datetime.now(KST).strftime("%Y-%m-%d")
                        out["us"][sym] = row
                        log(f"[FUNDA] US {sym}: PER={row.get('per')} 실적일={row.get('earningsDate')}")
                    else:
                        log(f"[FUNDA] US {sym} info 비어있음 — 기존 값 보존")
                    time.sleep(0.4)
                except Exception as e:
                    log(f"[FUNDA] US {sym} 오류(보존): {e}")
        except ImportError:
            log("[FUNDA] yfinance 미설치 — US 건너뜀")

    try:
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        log(f"[FUNDA] fundamentals.json 저장 — KR {len(out['kr'])} · US {len(out['us'])}")
    except Exception as e:
        log(f"[FUNDA] 저장 실패: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"[FUNDA] 치명 오류(파이프라인 비차단): {e}")
    sys.exit(0)
